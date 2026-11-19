"""Safety flags, and pausing and resuming a student's session.

How a pause works, start to finish:

1. Each flagged student message adds a row to `flags`.
2. When AUTO_PAUSE_AFTER_FLAGS of a session's messages have been flagged, the
   session is paused: `ai_paused` is set, the student sees PAUSE_MESSAGE, and a
   high-severity "Repeated misuse" flag is raised for administrators.
3. An administrator reviews it and resumes the session (from the flag, from the
   conversation, or from the paused-sessions list). resume() clears `ai_paused`,
   tells the student, and starts the count again from zero: only messages flagged
   *after* the resume count towards the next pause. (Before this, the old flags
   kept counting, so one more flag paused the session again straight away.)

An administrator can also pause a session by hand; resuming works the same way.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config, moderation
from .models import Flag, Message, PlaySession, User, audit, now

# Flags that count towards an automatic pause: the student's own flagged messages.
# Self-harm is excluded: it gets support, not a penalty. Personal info is excluded too:
# it's flagged so an administrator can protect the student, but it isn't misuse, and the
# pattern also matches in-story details ("the house at 412 Elm Street"), so it must not
# pause a session or stop a scene from moving on.
PAUSE_SOURCES = ("auto_input", "ai_review", "ai_judge")
PAUSE_EXCLUDED = ("self_harm", "repeated", "personal_info")
PAUSE_MESSAGE = ("Paused for review: several of your messages were flagged. You can continue once an "
                 "administrator resumes the session.")
ADMIN_PAUSE_MESSAGE = ("An administrator has paused this session for review. You can continue once it is resumed.")
RESUME_MESSAGE = "An administrator reviewed this session and resumed it. You can continue."


def add_flag(db: Session, s: PlaySession, hit: moderation.Hit, source: str, excerpt: str, message_id=None) -> None:
    db.add(Flag(session_id=s.id, message_id=message_id, student_id=s.student_id, source=source,
                category=hit.category, severity=hit.severity, reason=hit.reason, excerpt=(excerpt or "")[:2000]))


def _counting_from(db: Session, s: PlaySession) -> int:
    """Message id of the latest resume. Flags on earlier messages no longer count."""
    return db.scalar(select(func.max(Message.id)).where(
        Message.session_id == s.id, Message.role == "system", Message.speaker == "Resumed")) or 0


def flagged_messages(db: Session, s: PlaySession) -> int:
    """How many of the student's messages have been flagged since the last resume."""
    return db.scalar(select(func.count(func.distinct(Flag.message_id))).where(
        Flag.session_id == s.id, Flag.source.in_(PAUSE_SOURCES), Flag.message_id.is_not(None),
        Flag.message_id > _counting_from(db, s), Flag.category.not_in(PAUSE_EXCLUDED))) or 0


def reaches_pause(db: Session, s: PlaySession) -> bool:
    """Would one more flagged message reach the automatic-pause limit?"""
    return config.AUTO_PAUSE_AFTER_FLAGS > 0 and flagged_messages(db, s) + 1 >= config.AUTO_PAUSE_AFTER_FLAGS


def maybe_autopause(db: Session, s: PlaySession) -> bool:
    """Pause the session for administrator review once enough of the student's messages
    have been flagged (AUTO_PAUSE_AFTER_FLAGS). Returns True if it paused now.
    Call after flushing the new flags."""
    if s.ai_paused or s.status != "in_progress" or config.AUTO_PAUSE_AFTER_FLAGS <= 0:
        return False
    n = flagged_messages(db, s)
    if n < config.AUTO_PAUSE_AFTER_FLAGS:
        return False
    s.ai_paused = True
    s.updated_at = now()
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Paused",
                   content=PAUSE_MESSAGE))
    db.add(Flag(session_id=s.id, student_id=s.student_id, source="auto_input", category="repeated",
                severity="high", excerpt="",
                reason=f"Session paused automatically after {n} flagged messages. Review the conversation, "
                       "then resume the session so the student can continue."))
    return True


def maybe_escalate(db: Session, s: PlaySession) -> None:
    """Raise one high-severity flag when a session keeps collecting flags without being
    paused (for example when automatic pausing is turned off)."""
    n = db.scalar(select(func.count(Flag.id)).where(
        Flag.session_id == s.id, Flag.source.in_(("auto_input", "ai_review")), Flag.category != "repeated")) or 0
    waiting = db.scalar(select(Flag.id).where(Flag.session_id == s.id, Flag.category == "repeated",
                                              Flag.status == "open").limit(1))
    if n >= config.ESCALATE_AFTER_FLAGS and not waiting and not s.ai_paused:
        db.add(Flag(session_id=s.id, student_id=s.student_id, source="auto_input", category="repeated",
                    severity="high", reason=f"{n} flagged messages in one session. Possible deliberate misuse.",
                    excerpt=""))


def pause(db: Session, s: PlaySession, actor: User | None) -> bool:
    """Pause by hand. Returns False if it was already paused. Only sessions that are
    still in progress can be paused (the caller checks and reports that)."""
    if s.ai_paused:
        return False
    s.ai_paused = True
    s.updated_at = now()
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Paused",
                   content=ADMIN_PAUSE_MESSAGE))
    audit(db, actor, "session.pause", f"session:{s.id}")
    return True


def resume(db: Session, s: PlaySession, actor: User | None) -> bool:
    """Let the student continue. Returns False if the session wasn't paused.
    Adds the "Resumed" marker that both tells the student and restarts the flag count."""
    if not s.ai_paused:
        return False
    s.ai_paused = False
    s.updated_at = now()
    db.add(Message(session_id=s.id, role="system", node=s.node, in_context=False, speaker="Resumed",
                   content=RESUME_MESSAGE))
    audit(db, actor, "session.resume", f"session:{s.id}")
    return True
