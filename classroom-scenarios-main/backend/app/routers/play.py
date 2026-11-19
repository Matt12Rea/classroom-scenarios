"""Student-facing endpoints: start or resume a scenario, talk to the characters,
report content, export a conversation. (SRS 3.2, 3.3, 3.4; UC-02, UC-03, UC-04.)

The rules of a turn live in engine.py; this file only checks who is asking and
passes the request on."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import config, engine, exports
from ..access import get_session_for_view, is_assigned_to, student_class_ids
from ..database import get_db
from ..models import Assignment, Classroom, Flag, Message, PlaySession, Scenario, User, audit, now
from ..scenario_schema import normalize
from ..security import current_user, require, turn_rate_limit
from ..transcripts import conversation_record, session_state

router = APIRouter(prefix="/api", tags=["play"])

PAUSED = "This session is paused until an administrator reviews it."


def _own_active_session(db: Session, user: User, session_id: int) -> PlaySession:
    s = db.get(PlaySession, session_id)
    if not s or s.student_id != user.id:       # only the player may act in a session
        raise HTTPException(404, "Session not found.")
    if s.status != "in_progress":
        raise HTTPException(409, "This scenario is already complete." if s.status == "completed"
                            else "This attempt was restarted. Open the scenario again from your list.")
    return s


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
        definition = sc.definition if isinstance(sc.definition, dict) else {}
        out.append({
            "scenario_id": sc.id, "title": sc.title, "description": sc.description,
            "class_name": cl.name, "due_at": a.due_at.isoformat() if a.due_at else None,
            "objectives": definition.get("objectives", []),
            "status": "not_started" if not latest else latest.status,
            "paused": bool(latest and latest.status == "in_progress" and latest.ai_paused),
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
    """Start or resume (REQ: progress is preserved). Instructors use preview=true."""
    sc = db.get(Scenario, req.scenario_id)
    if not sc:
        raise HTTPException(404, "Scenario not found.")
    existing = None
    if req.preview:
        if not (user.role == "admin" or (user.role == "teacher" and sc.owner_id == user.id)):
            raise HTTPException(403, "Only the scenario's owner can preview it.")
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

    d = normalize(sc.definition)
    if d["start"] not in d["nodes"]:
        raise HTTPException(409, "This scenario isn't finished yet: it has no starting scene."
                            if req.preview else
                            "This scenario isn't finished yet. Ask your instructor to check it.")
    # Only now, when the new attempt is certain to start, replace the old one.
    if req.preview:
        for old in db.scalars(select(PlaySession).where(PlaySession.scenario_id == sc.id,
                                                        PlaySession.student_id == user.id,
                                                        PlaySession.is_preview.is_(True))):
            db.delete(old)
    elif existing and existing.status == "in_progress":
        existing.status = "abandoned"
        existing.updated_at = now()
    attempts = db.scalar(select(func.count(PlaySession.id)).where(
        PlaySession.scenario_id == sc.id, PlaySession.student_id == user.id,
        PlaySession.is_preview.is_(req.preview))) or 0
    s = PlaySession(scenario_id=sc.id, student_id=user.id, node=d["start"], snapshot=d,
                    is_preview=req.preview, attempt=1 if req.preview else attempts + 1)
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
    """Free-text dialogue with the AI characters (UC-03)."""
    with engine.one_turn_at_a_time(session_id):
        s = _own_active_session(db, user, session_id)
        if s.ai_paused:
            raise HTTPException(423, PAUSED)
        node = s.snapshot.get("nodes", {}).get(s.node) or {}
        if node.get("ending"):
            raise HTTPException(409, "This scenario is already complete.")
        max_turns = s.scenario.max_turns
        if s.turns >= max_turns:
            raise HTTPException(429, f"You've used all {max_turns} messages for this scenario.")
        text = req.text.strip()
        if not text or len(text) > config.MAX_INPUT_CHARS:
            raise HTTPException(422, f"Messages must be between 1 and {config.MAX_INPUT_CHARS} characters.")
        state, review_job = engine.take_turn(db, s, user, text)
    if review_job:
        bg.add_task(engine.background_review, *review_job)
    return state


@router.post("/sessions/{session_id}/finish")
def finish_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """For a session that has used every message but hasn't reached an ending: wrap it up now."""
    with engine.one_turn_at_a_time(session_id):
        s = _own_active_session(db, user, session_id)
        if s.ai_paused:
            raise HTTPException(423, PAUSED)
        if s.turns < s.scenario.max_turns:
            raise HTTPException(409, "You still have messages left. Keep the conversation going.")
        engine.wrap_up(db, s)
        db.commit()
        state = session_state(db, s, user)
    state["advanced"] = {"forced": True, "ending": s.status == "completed"}
    return state


class ReportReq(BaseModel):
    message_id: int | None = None
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/sessions/{session_id}/report")
def report(session_id: int, req: ReportReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Any participant or instructor can report content to administrators (NFR-5.2.7)."""
    s = get_session_for_view(db, user, session_id)
    excerpt = ""
    if req.message_id:
        m = db.get(Message, req.message_id)
        if not m or m.session_id != s.id:
            raise HTTPException(404, "Message not found.")
        excerpt = m.content
    db.add(Flag(session_id=s.id, message_id=req.message_id, student_id=s.student_id, reporter_id=user.id,
                source="report", category="ai_output" if user.role == "student" else "other",
                severity="medium", reason=f"Reported by {user.role}: {req.reason.strip()}", excerpt=excerpt[:2000]))
    db.commit()
    return {"ok": True, "message": "Thanks. An administrator will review this."}


# ------------------------------------------------------------------ exports --
def _export_one(db: Session, user: User, session_id: int, fmt: str) -> Response:
    """One logged conversation as a file. Instructors and administrators only: the
    file includes the judge's notes and anything an administrator hid from the student."""
    s = get_session_for_view(db, user, session_id)
    record = conversation_record(db, s)
    name = exports.safe_filename(f"{record['scenario']} {record['student']} attempt {record['attempt']}", fmt)
    if fmt == "pdf":
        body = exports.conversations_pdf([record], title=f"Conversation: {record['scenario']}",
                                         generated_by=user.name)
        media = "application/pdf"
    else:
        body, media = exports.conversations_csv([record]), "text/csv; charset=utf-8"
    audit(db, user, "conversation.export", f"session:{s.id}", format=fmt)
    db.commit()
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/sessions/{session_id}/export.csv")
def export_session_csv(session_id: int, user: User = Depends(require("teacher", "admin")),
                       db: Session = Depends(get_db)):
    return _export_one(db, user, session_id, "csv")


@router.get("/sessions/{session_id}/export.pdf")
def export_session_pdf(session_id: int, user: User = Depends(require("teacher", "admin")),
                       db: Session = Depends(get_db)):
    return _export_one(db, user, session_id, "pdf")
