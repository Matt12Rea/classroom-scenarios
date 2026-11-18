"""The scenario engine: what happens when a student sends a message.

There are no decision buttons. After each student message a judge model reads
the scene's conversation and says whether the student has taken one of the
scene's paths; the application checks that against the scenario and moves the
student on. A scene that reaches its message limit takes its fallback path.

One turn, in order (take_turn):

  1. Screen the message (moderation). Self-harm language gets support information
     and never reaches the AI. A message that takes the session to its flag limit
     pauses it instead (safety.py).
  2. Ask the AI for the characters' reply and, at the same time, ask the judge
     which path (if any) the student has taken.
  3. Screen the reply. Save the student's message and each character's line.
  4. Move to the next scene if a path was taken, or if the scene is out of messages.
  5. If the scenario is out of messages, wrap it up so every attempt ends.

Nothing is saved until step 3, so if the AI is unavailable the student can simply
send the same message again. The rules themselves (prompts, parsing, when a scene
moves on) are plain functions in dialogue.py.
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import ai, config, dialogue, moderation, safety, settings_store
from .database import session_scope
from .models import Decision, Flag, Message, PlaySession, User, now
from .scenario_schema import scene_cast
from .transcripts import current_node_id, session_state

log = logging.getLogger("aicss.engine")
_pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ai")   # reply and judge run side by side

UNFINISHED_OUTCOME = "Ended without reaching an ending"
BUSY = "Your last message is still being answered. Wait for the reply, then send the next one."
CHANGED = ("This conversation changed while your message was being answered, so it wasn't sent. "
           "The page has the latest version; try again.")

# ------------------------------------------------------- one turn at a time --
_busy: set[int] = set()
_busy_lock = threading.Lock()


@contextmanager
def one_turn_at_a_time(session_id: int):
    """Refuse a second message for a session while the first is still being answered
    (a double click, or the same session open in two tabs). Without this both turns
    would read the same history and save out of order."""
    with _busy_lock:
        if session_id in _busy:
            raise HTTPException(409, BUSY)
        _busy.add(session_id)
    try:
        yield
    finally:
        with _busy_lock:
            _busy.discard(session_id)


# ------------------------------------------------------------------ helpers --
def _context(db: Session, s: PlaySession, node: str | None = None, limit: int | None = None) -> list[dict]:
    """The spoken lines the AI is shown: oldest first, optionally one scene only or
    only the most recent `limit`."""
    q = select(Message).where(Message.session_id == s.id, Message.in_context.is_(True),
                              Message.role.in_(("user", "assistant")))
    if node is not None:
        q = q.where(Message.node == node)
    if limit:
        rows = list(reversed(db.scalars(q.order_by(Message.id.desc()).limit(limit)).all()))
    else:
        rows = db.scalars(q.order_by(Message.id)).all()
    return [{"role": m.role, "content": m.content, "speaker": m.speaker} for m in rows]


def path_so_far(db: Session, s: PlaySession) -> list[str]:
    nodes = s.snapshot["nodes"]
    out = []
    for d in db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)):
        label = d.choice[:1].lower() + d.choice[1:]
        out.append(f"in “{nodes.get(d.node, {}).get('title', d.node)}” the student {label}")
    return out


def _judge(eng, sc: dict, node_id: str, transcript: list[dict], forced: bool) -> dict | None:
    """Ask the judge which path (if any) the student has taken. None if the AI is
    unavailable or anything at all goes wrong: a failed judgement must never lose a turn."""
    try:
        system, user_msg = dialogue.judge_request(sc, node_id, transcript, forced)
        if not system:
            return None
        text = eng.judge(system, user_msg)
        return dialogue.parse_judgement(text, len(sc["nodes"][node_id]["choices"]), forced)
    except ai.AIUnavailable:
        return None
    except Exception as e:
        log.error("Judge failed: %s", type(e).__name__)
        return None


def _decide(sc: dict, node_id: str, verdict: dict | None, forced: bool) -> tuple[dict | None, str]:
    return dialogue.decide(sc, node_id, verdict, forced, config.JUDGE_CONFIDENCE)


def _debrief(db: Session, s: PlaySession, ending: dict) -> str | None:
    """The AI's end-of-scenario feedback, or None (the instructor's written feedback is
    always shown either way)."""
    sc = s.snapshot
    transcript = _context(db, s)
    path = [d.choice for d in db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id))]
    title = s.scenario.title if s.scenario else ""
    try:
        fb = ai.engine().debrief(dialogue.debrief_prompt(sc, title, transcript, path, ending)).text
    except ai.AIUnavailable:
        return None
    except Exception as e:
        log.error("Debrief failed: %s", type(e).__name__)
        return None
    if not fb or moderation.screen_output(fb):
        return None
    return fb


def advance(db: Session, s: PlaySession, choice: dict, reason: str, forced: bool) -> dict | None:
    """Move to the scene a path leads to (UC-04). Pure application logic: only paths
    the instructor wrote can be taken, and only to scenes that exist (REQ-3.3.8)."""
    sc = s.snapshot
    nxt = choice.get("next")
    if nxt not in sc["nodes"]:
        return None
    target = sc["nodes"][nxt]
    label = str(choice.get("label") or "Moved on")[:300]
    db.add(Decision(session_id=s.id, node=s.node, choice=label, next_node=nxt))
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Decision",
                   content=label))
    note = (reason or "").strip()
    if forced:
        note = f"Wrapped up at the message limit. {note}".strip()
    if note:          # shown to instructors only (see transcripts.session_state)
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Inference",
                       content=note[:1000]))
    if reason == dialogue.FALLBACK_REASON:
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Feedback",
                       content="No clear approach in this scene, so the situation moved on without you."))
    elif choice.get("feedback"):
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Feedback",
                       content=choice["feedback"]))
    s.node = nxt
    s.updated_at = now()
    ending = target.get("ending")
    if ending:
        s.status, s.outcome, s.outcome_type = "completed", str(ending["label"])[:200], ending["type"]
        s.completed_at = now()
        db.flush()
        s.feedback = _debrief(db, s, ending)
    return {"label": label, "to": target["title"], "ending": bool(ending), "forced": forced}


def close_unfinished(db: Session, s: PlaySession) -> None:
    """End an attempt that is out of messages in a scene with no way to an ending.
    A published scenario can't get here (validation requires every scene to lead
    somewhere); a draft being previewed, or very old data, can. Without this the
    attempt would stay "in progress" forever."""
    s.status, s.outcome, s.outcome_type = "completed", UNFINISHED_OUTCOME, "partial"
    s.completed_at = s.updated_at = now()
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Feedback",
                   content="You've used all your messages, and this scene has no path to an ending, "
                           "so the scenario stops here."))


def wrap_up(db: Session, s: PlaySession) -> None:
    """The student has used every message: take the best-matching path from each
    remaining scene, judged on the whole conversation, until an ending is reached."""
    sc = s.snapshot
    transcript = _context(db, s)
    try:
        eng = ai.engine()
    except ai.AIUnavailable:
        eng = None
    for _ in range(len(sc["nodes"]) + 1):           # a loop in the scenario can't spin forever
        node = sc["nodes"].get(s.node)
        if s.status == "completed" or not node or node.get("ending") or not node.get("choices"):
            break
        verdict = _judge(eng, sc, s.node, transcript, forced=True) if eng else None
        choice, reason = _decide(sc, s.node, verdict, forced=True)
        if not choice or not advance(db, s, choice, reason, forced=True):
            break
        db.flush()
    if s.status != "completed":
        close_unfinished(db, s)


def _pause_now(db: Session, s: PlaySession, viewer: User, text: str, hits: list) -> dict:
    """Record the flagged message (kept out of the AI's context), flag it, and pause."""
    um = Message(session_id=s.id, role="user", content=text, node=s.node, in_context=False)
    db.add(um)
    db.flush()
    for h, source in hits:
        safety.add_flag(db, s, h, source, text, um.id)
    s.updated_at = now()
    db.flush()
    safety.maybe_autopause(db, s)
    db.commit()
    return session_state(db, s, viewer)


def background_review(session_id: int, user_msg_id: int, student_text: str, ai_text: str) -> None:
    """Second-opinion check by Claude after the student already has their reply.
    Runs after the response is sent; any failure is logged and never affects the student."""
    try:
        verdict = ai.engine().review(student_text, ai_text)
        if not verdict or not verdict.get("flag"):
            return
        with session_scope() as db:
            s = db.get(PlaySession, session_id)
            if not s:
                return
            sev = verdict.get("severity") if verdict.get("severity") in ("low", "medium", "high") else "medium"
            db.add(Flag(session_id=s.id, message_id=user_msg_id, student_id=s.student_id, source="ai_review",
                        category=str(verdict.get("category") or "other")[:30], severity=sev,
                        reason=str(verdict.get("reason") or "Flagged by AI review")[:500],
                        excerpt=f"Student: {student_text}\nAI: {ai_text}"[:2000]))
            db.flush()
            if not safety.maybe_autopause(db, s):
                safety.maybe_escalate(db, s)
    except Exception as e:
        log.error("Background safety review failed: %s", type(e).__name__)


# ----------------------------------------------------------------- the turn --
def take_turn(db: Session, s: PlaySession, user: User, text: str) -> tuple[dict, tuple | None]:
    """Handle one student message. Returns (session state, background review job or None).
    The caller has already checked the session is the user's, in progress and not paused."""
    sc = s.snapshot
    node_id = current_node_id(s)
    if not node_id:
        raise HTTPException(409, "This scenario has no scenes yet. Ask your instructor to check it.")
    if node_id != s.node:
        s.node = node_id
    node = sc["nodes"][node_id]
    cast = scene_cast(sc, node_id)
    lead = cast[0]["name"]
    max_turns = s.scenario.max_turns
    turns_before = s.turns
    hits = moderation.screen_input(text)
    flag_src = "auto_input"
    # Instructor previews are flagged and paused like real sessions so the safety rules can be
    # tested, but their flags are kept out of the admin queue (see admin.list_flags), and
    # they get no background AI review.
    track = not s.is_preview

    # Self-harm language: pause the role-play and show support info instead of calling the AI.
    if any(h.block_ai for h in hits):
        um = Message(session_id=s.id, role="user", content=text, node=s.node, in_context=False)
        db.add(um)
        db.flush()
        db.add(Message(session_id=s.id, role="system", content=moderation.SUPPORT_MESSAGE,
                       node=s.node, in_context=False, speaker="Support"))
        if track:
            for h in hits:
                safety.add_flag(db, s, h, flag_src, text, um.id)
        s.updated_at = now()
        db.commit()
        return session_state(db, s, user), None

    # Repeated baiting: if this flagged message reaches the limit, record it and pause
    # the session for an administrator instead of letting the conversation go on.
    counted = [h for h in hits if h.category not in safety.PAUSE_EXCLUDED]
    if counted and safety.reaches_pause(db, s):
        return _pause_now(db, s, user, text, [(h, flag_src) for h in hits]), None

    label = dialogue.labels_speakers(sc)
    history = dialogue.history_for_model(_context(db, s, limit=config.HISTORY_TURNS * 3), label)
    scene_msgs = _context(db, s, node=node_id)
    turns_here = sum(1 for m in scene_msgs if m["role"] == "user") + 1      # counting this message
    plan = dialogue.turn_plan(node, turns_here, s.turns + 1, max_turns)
    judge_now, forced, at_limit = plan["judge_now"], plan["forced"], plan["at_limit"]

    unavailable = HTTPException(503, f"{lead} can't respond right now because the AI service is unavailable. "
                                     "Your progress is saved. Try sending your message again in a moment.")
    try:
        eng = ai.engine()
    except ai.AIUnavailable:
        raise unavailable
    reply_f = _pool.submit(eng.reply, dialogue.build_system_prompt(sc, node_id, path_so_far(db, s)),
                           history, text, cast)
    # The judge runs on every message: it also screens the message for baiting. Its path
    # answer is used only once the scene's minimum is met.
    judge_f = (_pool.submit(_judge, eng, sc, node_id, scene_msgs + [{"role": "user", "content": text}], forced)
               if node.get("choices") else None)
    try:
        result = reply_f.result()
    except ai.AIUnavailable:
        # REQ-3.2.3.9: nothing is saved, so the student can simply retry the same message.
        raise unavailable
    except Exception as e:
        log.error("AI reply failed unexpectedly: %s", type(e).__name__)
        raise unavailable
    verdict = judge_f.result() if judge_f else None       # _judge never raises

    # The AI call can take seconds. If an administrator paused the session, or it was
    # restarted or answered elsewhere in the meantime, don't write on top of that.
    db.refresh(s)
    if s.status != "in_progress" or s.ai_paused or s.turns != turns_before:
        raise HTTPException(409, CHANGED)
    if s.node != node_id:        # refresh() reloaded the stored scene id; keep the repaired one
        s.node = node_id

    judge_hits = []
    if verdict and verdict.get("misuse"):
        judge_hits.append(moderation.Hit(verdict["misuse"]["category"], "medium",
                                         f"AI judge: {verdict['misuse']['reason']}"))
    # This message is baiting and takes the student to the limit: don't show the reply, pause.
    if judge_hits and not counted and safety.reaches_pause(db, s):
        return _pause_now(db, s, user, text,
                          [(h, flag_src) for h in hits] + [(h, "ai_judge") for h in judge_hits]), None

    lines = dialogue.parse_reply(result.text, cast)
    out_hits = moderation.screen_output(result.text) if result.text else []
    if out_hits or not lines:
        # Never show a blocked reply. Keep the original for the admin to review.
        if track:
            for h in out_hits:
                safety.add_flag(db, s, h, "auto_output", f"Student: {text}\nAI (blocked): {result.text}")
        lines = [(lead, f"({lead} pauses and waits for you to go on.)")]

    um = Message(session_id=s.id, role="user", content=text, node=s.node)
    db.add(um)
    db.flush()
    for i, (speaker, said) in enumerate(lines):
        # Usage and timing belong to the one AI call, so they are stored on its first line only.
        db.add(Message(session_id=s.id, role="assistant", content=said, node=s.node, speaker=speaker[:120],
                       input_tokens=result.input_tokens if i == 0 else None,
                       output_tokens=result.output_tokens if i == 0 else None,
                       cached_tokens=result.cached_tokens if i == 0 else None,
                       latency_ms=result.latency_ms if i == 0 else None))
    for h in hits:
        safety.add_flag(db, s, h, flag_src, text, um.id)
    if not counted:              # the keyword check already flagged this message
        for h in judge_hits:
            safety.add_flag(db, s, h, "ai_judge", text, um.id)
    s.turns += 1
    s.updated_at = now()
    db.flush()
    if track and hits:
        safety.maybe_escalate(db, s)

    # Move the scene on if the student's words show they've taken a path.
    advanced = None
    if judge_now and not (counted or judge_hits):     # baiting never moves a scene on by itself
        choice, reason = _decide(sc, s.node, verdict, forced)
        if choice:
            advanced = advance(db, s, choice, reason, forced)
            db.flush()
    elif judge_now and forced:
        choice, reason = _decide(sc, s.node, None, forced)
        if choice:
            advanced = advance(db, s, choice, reason, forced)
            db.flush()
    if at_limit and s.status != "completed":
        wrap_up(db, s)
        advanced = advanced or {"forced": True, "ending": s.status == "completed"}
    db.commit()

    job = None
    if track and settings_store.ai_settings().ai_review:
        job = (s.id, um.id, text, "\n".join(f"{n}: {t}" for n, t in lines))
    state = session_state(db, s, user)
    state["slow"] = result.latency_ms > config.SLOW_AI_SECONDS * 1000
    state["advanced"] = advanced
    return state, job
