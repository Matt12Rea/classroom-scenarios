"""Administrator tools: users and roles (SRS 3.6), safety review queue
(NFR-5.2.1), interaction oversight, audit log (NFR-5.3.8), data retention (NFR-5.3.12)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .. import ai, exports, safety, settings_store
from ..database import get_db
from ..models import (ROLES, AuditLog, Classroom, Enrollment, Flag, Message, PlaySession, Scenario, User,
                      audit, now)
from ..security import hash_password, require, temp_password, validate_new_password
from ..transcripts import conversation_record, session_state
from .auth import user_out

router = APIRouter(prefix="/api/admin", tags=["admin"])
admin = require("admin")


# ==================================================================== users ==
@router.get("/users")
def list_users(q: str = "", role: str = "", status: str = "", user: User = Depends(admin),
               db: Session = Depends(get_db)):
    query = select(User).order_by(User.name)
    if q:
        like = f"%{q.lower()}%"
        query = query.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like)))
    if role:
        query = query.where(User.role == role)
    if status in ("active", "disabled"):
        query = query.where(User.active.is_(status == "active"))
    users = db.scalars(query.limit(1000)).all()
    classes: dict[int, list[str]] = {}
    for e, c in db.execute(select(Enrollment, Classroom).join(Classroom, Classroom.id == Enrollment.class_id)):
        classes.setdefault(e.student_id, []).append(c.name)
    for c in db.scalars(select(Classroom).where(Classroom.teacher_id.is_not(None))):
        classes.setdefault(c.teacher_id, []).append(c.name)
    return [{**user_out(u), "classes": classes.get(u.id, [])} for u in users]


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    role: str = "student"
    password: str | None = Field(default=None, max_length=256)


def _create_user(db, actor, req: UserCreate) -> tuple[User, str]:
    email = req.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, f"“{req.email}” isn't a valid email address.")
    if req.role not in ROLES:
        raise HTTPException(422, f"Role must be one of: {', '.join(ROLES)}.")
    if not req.name.strip():
        raise HTTPException(422, "Every account needs a name.")
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, f"An account already exists for {email}.")
    pw = req.password or temp_password()
    if req.password:
        validate_new_password(pw)
    u = User(name=req.name.strip(), email=email, role=req.role, password_hash=hash_password(pw),
             must_change_password=True)
    db.add(u)
    db.flush()
    audit(db, actor, "user.create", f"user:{u.id}", email=email, role=req.role)
    return u, pw


@router.post("/users")
def create_user(req: UserCreate, user: User = Depends(admin), db: Session = Depends(get_db)):
    u, pw = _create_user(db, user, req)
    db.commit()
    return {"user": user_out(u), "temporary_password": pw}


class BulkCreate(BaseModel):
    users: list[UserCreate] = Field(max_length=2000)
    class_id: int | None = None


@router.post("/users/import")
def import_users(req: BulkCreate, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Create many accounts at once (e.g. pasted from a roster). Each row succeeds or
    reports its own error; nothing is half-created."""
    if req.class_id and not db.get(Classroom, req.class_id):
        raise HTTPException(404, "That course no longer exists. Choose another, or import without a course.")
    created, errors = [], []
    for i, row in enumerate(req.users):
        try:
            with db.begin_nested():
                u, pw = _create_user(db, user, row)
                if req.class_id and u.role == "student":
                    db.add(Enrollment(class_id=req.class_id, student_id=u.id))
            created.append({"name": u.name, "email": u.email, "role": u.role, "temporary_password": pw})
        except HTTPException as e:
            errors.append({"row": i + 1, "email": row.email, "message": e.detail})
    db.commit()
    return {"created": created, "errors": errors}


class UserPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    active: bool | None = None


def _apply_patch(db, actor: User, u: User, req: UserPatch):
    if u.id == actor.id and (req.active is False or (req.role and req.role != "admin")):
        raise HTTPException(409, "You can't disable or demote your own account. Ask another administrator.")
    changes = {}
    if req.name is not None and req.name.strip():
        u.name = req.name.strip()
        changes["name"] = u.name
    if req.role is not None and req.role != u.role:
        if req.role not in ROLES:
            raise HTTPException(422, f"Role must be one of: {', '.join(ROLES)}.")
        changes["role"] = [u.role, req.role]
        u.role = req.role
        u.token_version += 1            # new permissions take effect on next sign-in
    if req.active is not None and req.active != u.active:
        u.active = req.active
        changes["active"] = req.active
        if not req.active:
            u.token_version += 1        # sign them out everywhere now
    if changes:
        audit(db, actor, "user.update", f"user:{u.id}", **changes)


@router.patch("/users/{user_id}")
def update_user(user_id: int, req: UserPatch, user: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    _apply_patch(db, user, u, req)
    db.commit()
    return user_out(u)


class BulkPatch(UserPatch):
    ids: list[int] = Field(max_length=5000)


@router.post("/users/bulk")
def bulk_update(req: BulkPatch, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Assign a role or enable/disable many users at once (SRS 3.6.2 'en masse')."""
    changed, skipped = 0, []
    for uid in req.ids:
        u = db.get(User, uid)
        if not u:
            continue
        try:
            _apply_patch(db, user, u, UserPatch(role=req.role, active=req.active))
            changed += 1
        except HTTPException as e:
            skipped.append({"id": uid, "message": e.detail})
    db.commit()
    return {"changed": changed, "skipped": skipped}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    pw = temp_password()
    u.password_hash, u.must_change_password = hash_password(pw), True
    u.token_version += 1
    audit(db, user, "user.reset_password", f"user:{u.id}")
    db.commit()
    return {"temporary_password": pw}


@router.delete("/users/{user_id}/data")
def delete_student_data(user_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Delete a student's conversations and results (retention / deletion requests)."""
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    sessions = db.scalars(select(PlaySession).where(PlaySession.student_id == u.id)).all()
    for s in sessions:
        db.delete(s)
    audit(db, user, "data.delete_student", f"user:{u.id}", sessions=len(sessions))
    db.commit()
    return {"deleted_sessions": len(sessions)}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found.")
    if u.id == user.id:
        raise HTTPException(409, "You can't delete your own account.")
    if db.scalar(select(Scenario.id).where(Scenario.owner_id == u.id).limit(1)):
        raise HTTPException(409, "This instructor owns scenarios. Disable the account instead, "
                                 "or transfer the scenarios first.")
    audit(db, user, "user.delete", f"user:{u.id}", email=u.email)
    db.delete(u)
    db.commit()
    return {"ok": True}


class RetentionReq(BaseModel):
    older_than_days: int = Field(ge=30, le=3650)


@router.post("/retention/purge")
def purge_old(req: RetentionReq, user: User = Depends(admin), db: Session = Depends(get_db)):
    cutoff = datetime.now(timezone.utc) - timedelta(days=req.older_than_days)
    old = db.scalars(select(PlaySession).where(PlaySession.updated_at < cutoff)).all()
    for s in old:
        db.delete(s)
    audit(db, user, "data.purge", "sessions", older_than_days=req.older_than_days, deleted=len(old))
    db.commit()
    return {"deleted_sessions": len(old)}


# ==================================================================== flags ==
def flag_out(f: Flag, db: Session) -> dict:
    s = f.session
    sc_title = s.scenario.title if s and s.scenario else None
    reviewer = db.get(User, f.reviewer_id) if f.reviewer_id else None
    return {"id": f.id, "session_id": f.session_id, "message_id": f.message_id, "source": f.source,
            "category": f.category, "severity": f.severity, "reason": f.reason, "excerpt": f.excerpt,
            "status": f.status, "review_note": f.review_note,
            "reviewer": reviewer.name if reviewer else None,
            "student": {"id": f.student.id, "name": f.student.name, "email": f.student.email,
                        "active": f.student.active} if f.student else None,
            "scenario": sc_title, "ai_paused": bool(s.ai_paused) if s else False,
            "session_status": s.status if s else None,
            "created_at": f.created_at.isoformat(),
            "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None}


@router.get("/flags")
def list_flags(status: str = "open", severity: str = "", category: str = "",
               user: User = Depends(admin), db: Session = Depends(get_db)):
    # Flags from instructors' previews stay out of the queue.
    q = select(Flag).outerjoin(PlaySession, PlaySession.id == Flag.session_id).where(
        or_(Flag.session_id.is_(None), PlaySession.is_preview.is_(False)))
    if status:
        q = q.where(Flag.status == status)
    if severity:
        q = q.where(Flag.severity == severity)
    if category:
        q = q.where(Flag.category == category)
    flags = db.scalars(q.order_by(Flag.id.desc()).limit(500)).all()
    if status == "open":                      # most serious first in the work queue
        order = {"high": 0, "medium": 1, "low": 2}
        flags = sorted(flags, key=lambda f: (order.get(f.severity, 3), -f.id))
    return [flag_out(f, db) for f in flags]


@router.get("/flags/{flag_id}")
def get_flag(flag_id: int, user: User = Depends(admin), db: Session = Depends(get_db)):
    f = db.get(Flag, flag_id)
    if not f:
        raise HTTPException(404, "Flag not found.")
    out = flag_out(f, db)
    out["session"] = session_state(db, f.session, user) if f.session else None
    out["related"] = [flag_out(x, db) for x in db.scalars(
        select(Flag).where(Flag.session_id == f.session_id, Flag.id != f.id).order_by(Flag.id))] \
        if f.session_id else []
    return out


class ReviewReq(BaseModel):
    status: str                         # dismissed | actioned | open
    note: str = Field(default="", max_length=2000)
    hide_message: bool = False          # remove the message from the transcript
    pause_ai: bool = False              # stop further AI conversation in that session
    resume_session: bool = False        # let a paused session continue
    disable_student: bool = False       # disable the student's account


def _require_in_progress(s: PlaySession):
    if s.status != "in_progress":
        raise HTTPException(409, "This attempt has already ended, so there is nothing to pause or resume.")


@router.post("/flags/{flag_id}/review")
def review_flag(flag_id: int, req: ReviewReq, user: User = Depends(admin), db: Session = Depends(get_db)):
    f = db.get(Flag, flag_id)
    if not f:
        raise HTTPException(404, "Flag not found.")
    if req.status not in ("dismissed", "actioned", "open"):
        raise HTTPException(422, "Status must be dismissed, actioned or open.")
    if req.pause_ai and req.resume_session:
        raise HTTPException(422, "Choose either pause or resume, not both.")
    f.status, f.review_note, f.reviewer_id, f.reviewed_at = req.status, req.note, user.id, now()
    actions = []
    if req.hide_message and f.message_id:
        m = db.get(Message, f.message_id)
        if m:
            m.hidden = True
            # Also hide the AI lines that answered it (everything up to the student's next message).
            for nxt in db.scalars(select(Message).where(Message.session_id == m.session_id, Message.id > m.id)
                                  .order_by(Message.id)):
                if nxt.role == "user":
                    break
                if nxt.role == "assistant":
                    nxt.hidden = True
            actions.append("hid message")
    s = f.session
    if req.pause_ai and s and s.status == "in_progress" and safety.pause(db, s, user):
        actions.append("paused session")
    if req.resume_session and s and safety.resume(db, s, user):
        actions.append("resumed session")
    if req.disable_student and f.student and f.student.role == "student":
        f.student.active = False
        f.student.token_version += 1
        actions.append("disabled student")
    audit(db, user, "flag.review", f"flag:{f.id}", status=req.status, actions=actions, note=req.note)
    db.commit()
    return flag_out(f, db)


class PauseReq(BaseModel):
    paused: bool


@router.post("/sessions/{session_id}/pause")
def pause_session(session_id: int, req: PauseReq, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Pause a session, or resume a paused one so the student can continue.
    Resuming also restarts the flag count (see safety.py)."""
    s = db.get(PlaySession, session_id)
    if not s:
        raise HTTPException(404, "Session not found.")
    if req.paused:
        _require_in_progress(s)
        changed = safety.pause(db, s, user)
    else:
        changed = safety.resume(db, s, user)
    db.commit()
    return {"ok": True, "ai_paused": s.ai_paused, "changed": changed, "status": s.status}


class HideReq(BaseModel):
    hidden: bool


@router.post("/messages/{message_id}/hide")
def hide_message(message_id: int, req: HideReq, user: User = Depends(admin), db: Session = Depends(get_db)):
    m = db.get(Message, message_id)
    if not m:
        raise HTTPException(404, "Message not found.")
    m.hidden = req.hidden
    audit(db, user, "message.hide" if req.hidden else "message.unhide", f"message:{m.id}")
    db.commit()
    return {"ok": True}


# ============================================================= interactions ==
def _session_rows(db: Session, q: str, scenario_id: int | None, flagged: bool, status: str, paused: bool,
                  limit: int):
    """Sessions matching the Conversations page's filters, newest first.
    Each row: (session, student, scenario, flag count, open flag count)."""
    flag_counts = select(Flag.session_id, func.count(Flag.id).label("n"),
                         func.sum(case((Flag.status == "open", 1), else_=0)).label("open")
                         ).group_by(Flag.session_id).subquery()
    query = (select(PlaySession, User, Scenario, flag_counts.c.n, flag_counts.c.open)
             .join(User, User.id == PlaySession.student_id)
             .join(Scenario, Scenario.id == PlaySession.scenario_id)
             .outerjoin(flag_counts, flag_counts.c.session_id == PlaySession.id)
             .where(PlaySession.is_preview.is_(False)))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like),
                                func.lower(Scenario.title).like(like)))
    if scenario_id:
        query = query.where(PlaySession.scenario_id == scenario_id)
    if flagged:
        query = query.where(flag_counts.c.n > 0)
    if paused:
        query = query.where(PlaySession.ai_paused.is_(True), PlaySession.status == "in_progress")
    if status:
        query = query.where(PlaySession.status == status)
    return db.execute(query.order_by(PlaySession.updated_at.desc()).limit(limit)).all()


@router.get("/sessions")
def list_sessions(q: str = "", scenario_id: int | None = None, flagged: bool = False, status: str = "",
                  paused: bool = False, user: User = Depends(admin), db: Session = Depends(get_db)):
    rows = _session_rows(db, q, scenario_id, flagged, status, paused, 300)
    return [{"session_id": s.id, "student": u.name, "student_email": u.email, "scenario": sc.title,
             "status": s.status, "outcome": s.outcome, "outcome_type": s.outcome_type, "turns": s.turns,
             "ai_paused": bool(s.ai_paused and s.status == "in_progress"), "flags": n or 0,
             "open_flags": int(o or 0), "updated_at": s.updated_at.isoformat()} for s, u, sc, n, o in rows]


def _export_sessions(db: Session, user: User, fmt: str, q: str, scenario_id: int | None, flagged: bool,
                     status: str, paused: bool) -> Response:
    cap = exports.MAX_PDF_CONVERSATIONS if fmt == "pdf" else exports.MAX_CSV_CONVERSATIONS
    rows = _session_rows(db, q, scenario_id, flagged, status, paused, cap + 1)
    if len(rows) > cap:
        raise HTTPException(413, f"That's more than {cap} conversations, which is too many for one "
                                 f"{fmt.upper()} file. Narrow the search (or export CSV) and try again.")
    records = [conversation_record(db, s) for s, *_ in rows]
    if fmt == "pdf":
        body, media = exports.conversations_pdf(records, title="Conversations", generated_by=user.name), "application/pdf"
    else:
        body, media = exports.conversations_csv(records), "text/csv; charset=utf-8"
    audit(db, user, "conversation.export", "sessions", format=fmt, conversations=len(records))
    db.commit()
    name = exports.safe_filename("conversations", fmt)
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/sessions/export.csv")
def export_sessions_csv(q: str = "", scenario_id: int | None = None, flagged: bool = False, status: str = "",
                        paused: bool = False, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Every line of every conversation matching the filters, as a spreadsheet."""
    return _export_sessions(db, user, "csv", q, scenario_id, flagged, status, paused)


@router.get("/sessions/export.pdf")
def export_sessions_pdf(q: str = "", scenario_id: int | None = None, flagged: bool = False, status: str = "",
                        paused: bool = False, user: User = Depends(admin), db: Session = Depends(get_db)):
    """The conversations matching the filters as one printable document."""
    return _export_sessions(db, user, "pdf", q, scenario_id, flagged, status, paused)


# ==================================================================== audit ==
@router.get("/audit")
def audit_log(action: str = "", limit: int = 200, user: User = Depends(require("admin", "it_support")),
              db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(max(1, min(limit, 1000)))
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    return [{"id": a.id, "action": a.action, "target": a.target, "detail": a.detail,
             "actor": a.actor.name if a.actor else "system", "created_at": a.created_at.isoformat()}
            for a in db.scalars(q)]


@router.get("/stats")
def stats(user: User = Depends(require("admin", "it_support")), db: Session = Depends(get_db)):
    roles = dict(db.execute(select(User.role, func.count(User.id)).group_by(User.role)).all())
    day = datetime.now(timezone.utc) - timedelta(days=1)
    # One AI call can produce several character lines; timing and usage are stored on the
    # first, so counting rows that have a latency counts calls, not lines.
    msgs = db.execute(select(func.count(Message.id), func.avg(Message.latency_ms),
                             func.sum(Message.input_tokens), func.sum(Message.output_tokens))
                      .where(Message.role == "assistant", Message.latency_ms.is_not(None),
                             Message.created_at >= day)).one()
    open_flags = dict(db.execute(select(Flag.severity, func.count(Flag.id))
                                 .outerjoin(PlaySession, PlaySession.id == Flag.session_id)
                                 .where(Flag.status == "open",
                                        or_(Flag.session_id.is_(None), PlaySession.is_preview.is_(False)))
                                 .group_by(Flag.severity)).all())
    ai_cfg, ai_st = settings_store.ai_settings(), settings_store.ai_status()
    return {
        "users": roles,
        "disabled_users": db.scalar(select(func.count(User.id)).where(User.active.is_(False))) or 0,
        "scenarios": db.scalar(select(func.count(Scenario.id))) or 0,
        "sessions_active": db.scalar(select(func.count(PlaySession.id)).where(
            PlaySession.status == "in_progress", PlaySession.is_preview.is_(False))) or 0,
        "sessions_paused": db.scalar(select(func.count(PlaySession.id)).where(
            PlaySession.status == "in_progress", PlaySession.ai_paused.is_(True),
            PlaySession.is_preview.is_(False))) or 0,
        "open_flags": open_flags,
        "ai_last_24h": {"replies": msgs[0] or 0, "avg_latency_ms": round(msgs[1]) if msgs[1] else None,
                        "input_tokens": msgs[2] or 0, "output_tokens": msgs[3] or 0},
        "ai_mode": ai_cfg.mode, "model": ai_cfg.model, "ai_review": ai_cfg.ai_review,
        "ai_state": "demo" if ai_cfg.mode == "mock" else (ai_st.get("state") or "unknown"),
        "ai_error": ai.ERROR_HELP.get(ai_st.get("last_error_kind"))
        if ai_cfg.mode == "claude" and ai_st.get("state") == "error" else None,
    }
