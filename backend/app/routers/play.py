"""Student-facing engine: start/resume a scenario, talk to characters, report
content. (SRS 3.2, 3.3, 3.4; UC-02, UC-03, UC-04.)

There are no decision buttons. After each student message a judge model reads
the scene's conversation and says whether the student has taken one of the
scene's paths; the application checks that against the scenario and moves the
student on. A scene that reaches its message limit takes the closest path."""
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import ai, config, moderation, settings_store
from ..access import get_session_for_view, is_assigned_to, student_class_ids
from ..database import SessionLocal, get_db
from ..models import (Assignment, Classroom, Decision, Flag, Message, PlaySession, Scenario,
                      User)
from ..scenario_schema import fallback_choice, normalize
from ..security import current_user, require, turn_rate_limit

log = logging.getLogger("aicss.play")
router = APIRouter(prefix="/api", tags=["play"])
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ai")   # reply and judge run side by side


def utcnow():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ helpers --
def session_state(db: Session, s: PlaySession, viewer: User) -> dict:
    sc = s.snapshot
    node = sc["nodes"][s.node]
    ch = ai.character_for(sc, s.node)
    privileged = viewer.role in ("teacher", "admin") and viewer.id != s.student_id
    # Instructors (and instructors previewing their own scenario) also see each scene's
    # paths and why the judge moved the scene on. Students never do.
    insight = privileged or (s.is_preview and viewer.id == s.student_id)
    msgs = db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id)).all()
    if not insight:
        msgs = [m for m in msgs if m.speaker != "Inference"]
    turns_here = sum(1 for m in msgs if m.role == "user" and m.node == s.node and m.in_context)
    decisions = db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)).all()
    visited = {s.snapshot["start"], *(d.next_node for d in decisions)}
    ending = node.get("ending")
    return {
        "id": s.id, "status": s.status, "attempt": s.attempt, "is_preview": s.is_preview,
        "ai_paused": s.ai_paused, "turns": s.turns, "max_turns": s.scenario.max_turns,
        "student_id": s.student_id,
        "student_name": s.student.name if privileged else None,
        "scenario": {"id": s.scenario_id, "title": s.scenario.title, "description": s.scenario.description,
                     "setting": sc["setting"], "objectives": sc["objectives"],
                     "characters": [{"id": c["id"], "name": c["name"], "role": c["role"]} for c in sc["characters"]]},
        "node": {"id": s.node, "title": node["title"], "prompt": node["prompt"],
                 "character": {"name": ch["name"], "role": ch["role"]},
                 "paths": ([{"label": c["label"], "signal": c.get("signal", "")} for c in node["choices"]]
                           if insight else None),
                 "min_turns": node["min_turns"], "wrap_after": node.get("wrap_after", 0),
                 "turns_here": turns_here, "is_ending": bool(ending)},
        "insight": insight,
        "messages": [{
            "id": m.id, "role": m.role, "speaker": m.speaker, "node": m.node,
            "content": m.content if (not m.hidden or privileged) else "[Removed by an administrator]",
            "hidden": m.hidden, "created_at": m.created_at.isoformat()} for m in msgs],
        "path": [{"node": d.node, "node_title": sc["nodes"].get(d.node, {}).get("title", d.node),
                  "choice": d.choice, "next": d.next_node} for d in decisions],
        # Only scenes this student has actually reached (no spoilers for other branches).
        "scenes": {nid: {"title": sc["nodes"][nid]["title"], "prompt": sc["nodes"][nid]["prompt"]}
                   for nid in visited if nid in sc["nodes"]},
        "start": sc["start"],
        "outcome": ({"label": s.outcome, "type": s.outcome_type,
                     "teacher_feedback": ending["feedback"] if ending else "",
                     "ai_feedback": s.feedback or ""} if s.status == "completed" else None),
        "progress": {"visited": len(visited), "total": len(sc["nodes"])},
    }


def _own_active_session(db: Session, user: User, session_id: int) -> PlaySession:
    s = db.get(PlaySession, session_id)
    if not s or s.student_id != user.id:       # only the player may act in a session
        raise HTTPException(404, "Session not found.")
    if s.status == "completed":
        raise HTTPException(409, "This scenario is already complete.")
    return s


def _flag(db, s: PlaySession, hit: moderation.Hit, source: str, excerpt: str, message_id=None):
    db.add(Flag(session_id=s.id, message_id=message_id, student_id=s.student_id, source=source,
                category=hit.category, severity=hit.severity, reason=hit.reason, excerpt=excerpt[:2000]))


def _maybe_escalate(db, s: PlaySession):
    n = db.scalar(select(func.count(Flag.id)).where(
        Flag.session_id == s.id, Flag.source.in_(("auto_input", "ai_review"))))
    already = db.scalar(select(Flag.id).where(Flag.session_id == s.id, Flag.category == "repeated").limit(1))
    if n >= config.ESCALATE_AFTER_FLAGS and not already:
        db.add(Flag(session_id=s.id, student_id=s.student_id, source="auto_input", category="repeated",
                    severity="high", reason=f"{n} flagged messages in one session. Possible deliberate misuse.",
                    excerpt=""))


def _background_review(session_id: int, user_msg_id: int, student_text: str, ai_text: str):
    """Second-opinion check by Claude after the student already has their reply."""
    verdict = ai.engine().review(student_text, ai_text)
    if not verdict or not verdict.get("flag"):
        return
    db = SessionLocal()
    try:
        s = db.get(PlaySession, session_id)
        if not s:
            return
        sev = verdict.get("severity") if verdict.get("severity") in ("low", "medium", "high") else "medium"
        db.add(Flag(session_id=s.id, message_id=user_msg_id, student_id=s.student_id, source="ai_review",
                    category=str(verdict.get("category") or "other")[:30], severity=sev,
                    reason=str(verdict.get("reason") or "Flagged by AI review")[:500],
                    excerpt=f"Student: {student_text}\nAI: {ai_text}"[:2000]))
        db.flush()
        if not _maybe_autopause(db, s):
            _maybe_escalate(db, s)
        db.commit()
    finally:
        db.close()


def _judge(eng, sc: dict, node_id: str, transcript: list[dict], forced: bool) -> dict | None:
    """Ask the judge which path (if any) the student has taken. None if the AI is unavailable."""
    system, user_msg = ai.judge_request(sc, node_id, transcript, forced)
    if not system:
        return None
    try:
        text = eng.judge(system, user_msg)
    except ai.AIUnavailable:
        return None
    return ai.parse_judgement(text, len(sc["nodes"][node_id]["choices"]), forced)


FALLBACK_REASON = "No path was clearly shown by the end of the scene, so the scene's fallback path was taken."


def _decide(sc: dict, node_id: str, verdict: dict | None, forced: bool) -> tuple[dict | None, str]:
    """Turn a judgement into the path to take, or (None, "") to stay in the scene.
    A path counts only when the judge is confident. When a scene must wrap up and no
    path was clearly shown (or the AI was unavailable), the scene's fallback path is
    taken, which by default leads toward the worst outcome."""
    choices = sc["nodes"][node_id]["choices"]
    if verdict and verdict["index"] is not None and verdict["confidence"] >= config.JUDGE_CONFIDENCE:
        return choices[verdict["index"]], verdict["reason"]
    if forced:
        return fallback_choice(sc, node_id), FALLBACK_REASON
    return None, ""


# Flags that count towards an automatic pause: the student's own flagged messages.
# Self-harm is excluded: it gets support, not a penalty.
PAUSE_SOURCES = ("auto_input", "ai_review")
PAUSE_EXCLUDED = ("self_harm", "repeated")
PAUSE_MESSAGE = ("This session has been paused because several messages were flagged by the safety checks. "
                 "An administrator will review it. Your progress is saved, and you can continue if they resume it.")


def _flagged_messages(db, s: PlaySession) -> int:
    return db.scalar(select(func.count(func.distinct(Flag.message_id))).where(
        Flag.session_id == s.id, Flag.source.in_(PAUSE_SOURCES), Flag.message_id.is_not(None),
        Flag.category.not_in(PAUSE_EXCLUDED))) or 0


def _maybe_autopause(db, s: PlaySession) -> bool:
    """Pause the session for administrator review once enough of the student's messages
    have been flagged (AUTO_PAUSE_AFTER_FLAGS). Returns True if it paused now."""
    if s.is_preview or s.ai_paused or s.status == "completed" or config.AUTO_PAUSE_AFTER_FLAGS <= 0:
        return False
    n = _flagged_messages(db, s)
    if n < config.AUTO_PAUSE_AFTER_FLAGS:
        return False
    s.ai_paused = True
    s.updated_at = utcnow()
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Paused",
                   content=PAUSE_MESSAGE))
    db.add(Flag(session_id=s.id, student_id=s.student_id, source="auto_input", category="repeated",
                severity="high", excerpt="",
                reason=f"Session paused automatically after {n} flagged messages. Resume it from the "
                       "conversation view once reviewed."))
    return True


def _path_so_far(db, s: PlaySession) -> list[str]:
    sc = s.snapshot
    out = []
    for d in db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)):
        label = d.choice[:1].lower() + d.choice[1:]
        out.append(f"in “{sc['nodes'].get(d.node, {}).get('title', d.node)}” the student {label}")
    return out


def _advance(db, s: PlaySession, choice: dict, reason: str, forced: bool) -> dict | None:
    """Move to the scene a path leads to (UC-04). Pure application logic: only paths
    the teacher wrote can be taken, and only to scenes that exist (REQ-3.3.8)."""
    sc = s.snapshot
    nxt = choice.get("next")
    if nxt not in sc["nodes"]:
        return None
    target = sc["nodes"][nxt]
    db.add(Decision(session_id=s.id, node=s.node, choice=choice["label"], next_node=nxt))
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Decision",
                   content=choice["label"]))
    note = (reason or "").strip()
    if forced:
        note = f"Wrapped up at the message limit. {note}".strip()
    if note:          # shown to instructors only (see session_state)
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Inference",
                       content=note[:1000]))
    if reason == FALLBACK_REASON:
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Feedback",
                       content="You didn't clearly take an approach in this scene, so it ended and the "
                               "situation moved on without you."))
    elif choice.get("feedback"):
        db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Feedback",
                       content=choice["feedback"]))
    s.node = nxt
    s.updated_at = utcnow()
    ending = target.get("ending")
    if ending:
        s.status, s.outcome, s.outcome_type = "completed", ending["label"], ending["type"]
        s.completed_at = utcnow()
        db.flush()
        transcript = [{"role": m.role, "content": m.content, "speaker": m.speaker} for m in db.scalars(
            select(Message).where(Message.session_id == s.id, Message.in_context.is_(True)).order_by(Message.id))]
        path = [d.choice for d in db.scalars(select(Decision).where(Decision.session_id == s.id)
                                             .order_by(Decision.id))]
        try:
            r = ai.engine().debrief(ai.debrief_prompt(sc, s.scenario.title, transcript, path, ending))
            fb = r.text
            if fb and moderation.screen_output(fb):
                fb = ""
            s.feedback = fb or None
        except ai.AIUnavailable:
            s.feedback = None          # teacher-written feedback is still shown
    return {"label": choice["label"], "to": target["title"], "ending": bool(ending), "forced": forced}


def _wrap_up(db, s: PlaySession) -> None:
    """The student has used every message: take the closest path from each remaining
    scene, judged on the whole conversation, until an ending is reached."""
    sc = s.snapshot
    transcript = [{"role": m.role, "content": m.content} for m in db.scalars(
        select(Message).where(Message.session_id == s.id, Message.in_context.is_(True),
                              Message.role.in_(("user", "assistant"))).order_by(Message.id))]
    eng = ai.engine()
    for _ in range(len(sc["nodes"]) + 1):           # a loop in the scenario can't spin forever
        node = sc["nodes"][s.node]
        if node.get("ending") or not node["choices"] or s.status == "completed":
            return
        choice, reason = _decide(sc, s.node, _judge(eng, sc, s.node, transcript, forced=True), forced=True)
        if not choice or not _advance(db, s, choice, reason, forced=True):
            return
        db.flush()


# ---------------------------------------------------------------- endpoints --
@router.get("/student/assignments")
def my_assignments(user: User = Depends(require("student")), db: Session = Depends(get_db)):
    class_ids = student_class_ids(db, user.id)
    if not class_ids:
        return []
    rows = db.execute(
        select(Assignment, Scenario, Classroom).join(Scenario, Scenario.id == Assignment.scenario_id)
        .join(Classroom, Classroom.id == Assignment.class_id)
        .where(Assignment.class_id.in_(class_ids), Scenario.status == "published")
        .order_by(Assignment.due_at.is_(None), Assignment.due_at, Assignment.id.desc())).all()
    out, seen = [], set()
    for a, sc, cl in rows:
        if sc.id in seen:
            continue
        seen.add(sc.id)
        sessions = db.scalars(select(PlaySession).where(
            PlaySession.scenario_id == sc.id, PlaySession.student_id == user.id,
            PlaySession.is_preview.is_(False)).order_by(PlaySession.id.desc())).all()
        latest = sessions[0] if sessions else None
        best = next((x for x in sessions if x.outcome_type == "success"), None) or \
            next((x for x in sessions if x.status == "completed"), None)
        out.append({
            "scenario_id": sc.id, "title": sc.title, "description": sc.description,
            "class_name": cl.name, "due_at": a.due_at.isoformat() if a.due_at else None,
            "objectives": sc.definition.get("objectives", []),
            "status": "not_started" if not latest else latest.status,
            "session_id": latest.id if latest else None,
            "attempts": len(sessions),
            "outcome": best.outcome if best else None, "outcome_type": best.outcome_type if best else None,
        })
    return out


class StartReq(BaseModel):
    scenario_id: int
    preview: bool = False
    restart: bool = False


@router.post("/sessions")
def start_session(req: StartReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Start or resume (REQ: progress is preserved). Teachers use preview=true."""
    sc = db.get(Scenario, req.scenario_id)
    if not sc:
        raise HTTPException(404, "Scenario not found.")
    if req.preview:
        if not (user.role == "admin" or (user.role == "teacher" and sc.owner_id == user.id)):
            raise HTTPException(403, "Only the scenario's owner can preview it.")
        for old in db.scalars(select(PlaySession).where(PlaySession.scenario_id == sc.id,
                                                        PlaySession.student_id == user.id,
                                                        PlaySession.is_preview.is_(True))):
            db.delete(old)
    else:
        if user.role != "student":
            raise HTTPException(403, "Use Preview to try a scenario as an instructor.")
        if sc.status != "published" or not is_assigned_to(db, sc.id, user.id):
            raise HTTPException(404, "This scenario isn't assigned to you.")
        existing = db.scalars(select(PlaySession).where(
            PlaySession.scenario_id == sc.id, PlaySession.student_id == user.id,
            PlaySession.is_preview.is_(False)).order_by(PlaySession.id.desc())).first()
        if existing and existing.status == "in_progress" and not req.restart:
            return session_state(db, existing, user)
        if existing and existing.status == "in_progress" and existing.ai_paused:
            raise HTTPException(423, "This scenario is paused until an administrator reviews your session.")
        if existing and existing.status == "in_progress" and req.restart:
            existing.status = "abandoned"
            existing.updated_at = utcnow()

    d = normalize(sc.definition)
    if d["start"] not in d["nodes"]:
        raise HTTPException(409, "This scenario isn't finished yet. Ask your instructor to check it.")
    attempts = db.scalar(select(func.count(PlaySession.id)).where(
        PlaySession.scenario_id == sc.id, PlaySession.student_id == user.id,
        PlaySession.is_preview.is_(req.preview))) or 0
    s = PlaySession(scenario_id=sc.id, student_id=user.id, node=d["start"], snapshot=d,
                    is_preview=req.preview, attempt=attempts + 1)
    db.add(s)
    db.commit()
    return session_state(db, s, user)


@router.get("/sessions/{session_id}")
def get_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return session_state(db, get_session_for_view(db, user, session_id), user)


class TurnReq(BaseModel):
    text: str = Field(max_length=10_000)


@router.post("/sessions/{session_id}/turn")
def student_turn(session_id: int, req: TurnReq, bg: BackgroundTasks,
                 user: User = Depends(turn_rate_limit), db: Session = Depends(get_db)):
    """Free-text dialogue with the AI character (UC-03)."""
    s = _own_active_session(db, user, session_id)
    if s.ai_paused:
        raise HTTPException(423, "This session is paused until an administrator reviews it.")
    if s.snapshot["nodes"][s.node].get("ending"):
        raise HTTPException(409, "This scenario is already complete.")
    if s.turns >= s.scenario.max_turns:
        raise HTTPException(429, f"You've used all {s.scenario.max_turns} messages for this scenario.")
    text = req.text.strip()
    if not text or len(text) > config.MAX_INPUT_CHARS:
        raise HTTPException(422, f"Messages must be between 1 and {config.MAX_INPUT_CHARS} characters.")

    sc = s.snapshot
    ch = ai.character_for(sc, s.node)
    hits = moderation.screen_input(text)
    flag_src = "auto_input"
    track = not s.is_preview            # teacher test runs don't fill the admin queue

    # Self-harm language: pause the role-play and show support info instead of calling the AI.
    if any(h.block_ai for h in hits):
        um = Message(session_id=s.id, role="user", content=text, node=s.node, in_context=False)
        db.add(um)
        db.flush()
        db.add(Message(session_id=s.id, role="system", content=moderation.SUPPORT_MESSAGE,
                       node=s.node, in_context=False, speaker="Support"))
        if track:
            for h in hits:
                _flag(db, s, h, flag_src, text, um.id)
        s.updated_at = utcnow()
        db.commit()
        return session_state(db, s, user)

    # Repeated baiting: if this flagged message reaches the limit, record it and pause
    # the session for an administrator instead of letting the conversation go on.
    counted = [h for h in hits if h.category not in PAUSE_EXCLUDED]
    if track and counted and config.AUTO_PAUSE_AFTER_FLAGS > 0 and \
            _flagged_messages(db, s) + 1 >= config.AUTO_PAUSE_AFTER_FLAGS:
        um = Message(session_id=s.id, role="user", content=text, node=s.node, in_context=False)
        db.add(um)
        db.flush()
        for h in hits:
            _flag(db, s, h, flag_src, text, um.id)
        db.flush()
        _maybe_autopause(db, s)
        db.commit()
        return session_state(db, s, user)

    history = [{"role": m.role, "content": m.content} for m in reversed(db.scalars(
        select(Message).where(Message.session_id == s.id, Message.in_context.is_(True),
                              Message.role.in_(("user", "assistant")))
        .order_by(Message.id.desc()).limit(config.HISTORY_TURNS * 2)).all())]
    path = _path_so_far(db, s)

    # Should this message be judged? Only once the scene's minimum is met; and the
    # judgement is forced (closest path) when the scene or the scenario runs out of messages.
    node = sc["nodes"][s.node]
    scene_msgs = [{"role": m.role, "content": m.content} for m in db.scalars(
        select(Message).where(Message.session_id == s.id, Message.node == s.node, Message.in_context.is_(True),
                              Message.role.in_(("user", "assistant"))).order_by(Message.id))]
    turns_here = sum(1 for m in scene_msgs if m["role"] == "user") + 1      # counting this message
    at_limit = s.turns + 1 >= s.scenario.max_turns
    judge_now = bool(node["choices"]) and turns_here >= max(1, node["min_turns"])
    forced = judge_now and (at_limit or 0 < node.get("wrap_after", 0) <= turns_here)

    eng = ai.engine()
    reply_f = _pool.submit(eng.reply, ai.build_system_prompt(sc, s.node, path), history, text)
    judge_f = (_pool.submit(_judge, eng, sc, s.node, scene_msgs + [{"role": "user", "content": text}], forced)
               if judge_now else None)
    try:
        result = reply_f.result()
    except ai.AIUnavailable:
        # REQ-3.2.3.9: nothing is saved, so the student can simply retry the same message.
        raise HTTPException(503, f"{ch['name']} can't respond right now because the AI service is unavailable. "
                                 "Your progress is saved. Try sending your message again in a moment.")

    reply = result.text
    out_hits = moderation.screen_output(reply) if reply else []
    if out_hits or not reply:
        # Never show a blocked reply. Keep the original for the admin to review.
        if track:
            for h in out_hits:
                _flag(db, s, h, "auto_output", f"Student: {text}\nAI (blocked): {reply}")
        reply = f"({ch['name']} pauses and waits for you to go on.)"

    um = Message(session_id=s.id, role="user", content=text, node=s.node)
    db.add(um)
    db.flush()
    db.add(Message(session_id=s.id, role="assistant", content=reply, node=s.node, speaker=ch["name"],
                   input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                   cached_tokens=result.cached_tokens, latency_ms=result.latency_ms))
    if track:
        for h in hits:
            _flag(db, s, h, flag_src, text, um.id)
    s.turns += 1
    s.updated_at = utcnow()
    db.flush()
    if track and hits:
        _maybe_escalate(db, s)

    # Move the scene on if the student's words show they've taken a path.
    advanced = None
    if judge_f:
        choice, reason = _decide(sc, s.node, judge_f.result(), forced)
        if choice:
            advanced = _advance(db, s, choice, reason, forced)
            db.flush()
    if at_limit and s.status != "completed":
        _wrap_up(db, s)
        advanced = advanced or {"forced": True, "ending": s.status == "completed"}
    db.commit()
    if track and settings_store.ai_settings().ai_review:
        bg.add_task(_background_review, s.id, um.id, text, reply)
    state = session_state(db, s, user)
    state["slow"] = result.latency_ms > config.SLOW_AI_SECONDS * 1000
    state["advanced"] = advanced
    return state


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """For a session that has used every message but hasn't reached an ending (for
    example one started before scenes moved on automatically): wrap it up now."""
    s = _own_active_session(db, user, session_id)
    if s.turns < s.scenario.max_turns:
        raise HTTPException(409, "You still have messages left. Keep the conversation going.")
    _wrap_up(db, s)
    db.commit()
    state = session_state(db, s, user)
    state["advanced"] = {"forced": True, "ending": s.status == "completed"}
    return state


class ReportReq(BaseModel):
    message_id: int | None = None
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/sessions/{session_id}/report")
def report(session_id: int, req: ReportReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Any participant or teacher can report content to administrators (NFR-5.2.7)."""
    s = get_session_for_view(db, user, session_id)
    excerpt = ""
    if req.message_id:
        m = db.get(Message, req.message_id)
        if not m or m.session_id != s.id:
            raise HTTPException(404, "Message not found.")
        excerpt = m.content
    db.add(Flag(session_id=s.id, message_id=req.message_id, student_id=s.student_id, reporter_id=user.id,
                source="report", category="ai_output" if user.role == "student" else "other",
                severity="medium", reason=f"Reported by {user.role}: {req.reason}", excerpt=excerpt[:2000]))
    db.commit()
    return {"ok": True, "message": "Thanks. An administrator will review this."}
