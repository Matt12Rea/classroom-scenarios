"""Student-facing engine: start/resume a scenario, talk to characters, make
decisions, report content. (SRS 3.2, 3.3, 3.4; UC-02, UC-03, UC-04.)"""
import logging
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
from ..scenario_schema import normalize
from ..security import current_user, require, turn_rate_limit

log = logging.getLogger("aicss.play")
router = APIRouter(prefix="/api", tags=["play"])


def utcnow():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ helpers --
def session_state(db: Session, s: PlaySession, viewer: User) -> dict:
    sc = s.snapshot
    node = sc["nodes"][s.node]
    ch = ai.character_for(sc, s.node)
    privileged = viewer.role in ("teacher", "admin") and viewer.id != s.student_id
    msgs = db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id)).all()
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
                 "choices": [{"label": c["label"]} for c in node["choices"]],
                 "min_turns": node["min_turns"], "turns_here": turns_here,
                 "choices_locked": turns_here < node["min_turns"], "is_ending": bool(ending)},
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
        _maybe_escalate(db, s)
        db.commit()
    finally:
        db.close()


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
            raise HTTPException(403, "Use Preview to try a scenario as a teacher.")
        if sc.status != "published" or not is_assigned_to(db, sc.id, user.id):
            raise HTTPException(404, "This scenario isn't assigned to you.")
        existing = db.scalars(select(PlaySession).where(
            PlaySession.scenario_id == sc.id, PlaySession.student_id == user.id,
            PlaySession.is_preview.is_(False)).order_by(PlaySession.id.desc())).first()
        if existing and existing.status == "in_progress" and not req.restart:
            return session_state(db, existing, user)
        if existing and existing.status == "in_progress" and req.restart:
            existing.status = "abandoned"
            existing.updated_at = utcnow()

    d = normalize(sc.definition)
    if d["start"] not in d["nodes"]:
        raise HTTPException(409, "This scenario isn't finished yet. Ask your teacher to check it.")
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
        raise HTTPException(423, "Conversation is paused for this scenario. You can still make decisions, "
                                 "or ask your teacher for help.")
    if s.snapshot["nodes"][s.node].get("ending"):
        raise HTTPException(409, "This scenario is already complete.")
    if s.turns >= s.scenario.max_turns:
        raise HTTPException(429, f"You've used all {s.scenario.max_turns} messages for this scenario. "
                                 "Choose a decision to continue.")
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

    history = [{"role": m.role, "content": m.content} for m in reversed(db.scalars(
        select(Message).where(Message.session_id == s.id, Message.in_context.is_(True),
                              Message.role.in_(("user", "assistant")))
        .order_by(Message.id.desc()).limit(config.HISTORY_TURNS * 2)).all())]
    decisions = db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)).all()
    path = [f"the student chose “{d.choice}”" for d in decisions]

    try:
        result = ai.engine().reply(ai.build_system_prompt(sc, s.node, path), history, text)
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
    db.commit()
    if track and settings_store.ai_settings().ai_review:
        bg.add_task(_background_review, s.id, um.id, text, reply)
    state = session_state(db, s, user)
    state["slow"] = result.latency_ms > config.SLOW_AI_SECONDS * 1000
    return state


class DecisionReq(BaseModel):
    choice: str


@router.post("/sessions/{session_id}/decision")
def student_decision(session_id: int, req: DecisionReq, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Branching (UC-04). Pure application logic; the AI never decides progression."""
    s = _own_active_session(db, user, session_id)
    sc = s.snapshot
    node = sc["nodes"][s.node]
    choice = next((c for c in node["choices"] if c["label"] == req.choice), None)
    if not choice or choice["next"] not in sc["nodes"]:          # REQ-3.3.8
        raise HTTPException(422, "That isn't one of the available decisions.")
    turns_here = db.scalar(select(func.count(Message.id)).where(
        Message.session_id == s.id, Message.node == s.node, Message.role == "user",
        Message.in_context.is_(True))) or 0
    if turns_here < node["min_turns"] and not s.ai_paused:
        need = node["min_turns"] - turns_here
        ch = ai.character_for(sc, s.node)
        raise HTTPException(409, f"Talk with {ch['name']} a little more first "
                                 f"({need} more message{'s' if need != 1 else ''}).")

    nxt = choice["next"]
    target = sc["nodes"][nxt]
    db.add(Decision(session_id=s.id, node=s.node, choice=choice["label"], next_node=nxt))
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Decision",
                   content=choice["label"]))
    if choice.get("feedback"):
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
    db.commit()
    return session_state(db, s, user)


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
