"""Reading a session back out of the database: the state the player and the
conversation views show, and the plain records the exports are built from."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Classroom, Decision, Enrollment, Flag, Message, PlaySession, User
from .scenario_schema import scene_cast

REMOVED = "[Removed by an administrator]"
# System lines by "speaker": what each one is, for exports.
SYSTEM_KIND = {"Decision": "path", "Inference": "judge_note", "Feedback": "feedback"}


def current_node_id(s: PlaySession) -> str:
    """The session's scene id, repaired if the stored one isn't in its snapshot
    (which should never happen, but must not crash the player if it does)."""
    nodes = (s.snapshot or {}).get("nodes") or {}
    if s.node in nodes:
        return s.node
    start = (s.snapshot or {}).get("start")
    return start if start in nodes else next(iter(nodes), "")


def session_state(db: Session, s: PlaySession, viewer: User) -> dict:
    sc = s.snapshot or {}
    nodes = sc.get("nodes") or {}
    node_id = current_node_id(s)
    node = nodes.get(node_id) or {"title": "Scene unavailable", "prompt": "", "choices": [], "ending": None,
                                  "min_turns": 0, "wrap_after": 0}
    cast = scene_cast(sc, node_id)
    privileged = viewer.role in ("teacher", "admin") and viewer.id != s.student_id
    # Instructors (and instructors previewing their own scenario) also see each scene's
    # paths and why the judge moved the scene on. Students never do.
    insight = privileged or (s.is_preview and viewer.id == s.student_id)
    msgs = db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id)).all()
    if not insight:
        msgs = [m for m in msgs if m.speaker != "Inference"]
    turns_here = sum(1 for m in msgs if m.role == "user" and m.node == node_id and m.in_context)
    decisions = db.scalars(select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)).all()
    visited = {sc.get("start"), *(d.next_node for d in decisions)}
    ending = node.get("ending")
    scenario = s.scenario
    return {
        "id": s.id, "status": s.status, "attempt": s.attempt, "is_preview": s.is_preview,
        "ai_paused": s.ai_paused, "turns": s.turns, "max_turns": scenario.max_turns if scenario else s.turns,
        "student_id": s.student_id,
        "student_name": s.student.name if privileged and s.student else None,
        "scenario": {"id": s.scenario_id, "title": scenario.title if scenario else "Deleted scenario",
                     "description": scenario.description if scenario else "",
                     "setting": sc.get("setting", ""), "objectives": sc.get("objectives", []),
                     "characters": [{"id": c["id"], "name": c["name"], "role": c["role"]}
                                    for c in sc.get("characters", [])]},
        "node": {"id": node_id, "title": node.get("title", ""), "prompt": node.get("prompt", ""),
                 # "characters": everyone present, in speaking order. "character": the first of
                 # them, kept for older clients.
                 "characters": [{"id": c.get("id", ""), "name": c["name"], "role": c["role"]} for c in cast],
                 "character": {"name": cast[0]["name"], "role": cast[0]["role"]},
                 "paths": ([{"label": c["label"], "signal": c.get("signal", "")} for c in node.get("choices", [])]
                           if insight else None),
                 "min_turns": node.get("min_turns", 0), "wrap_after": node.get("wrap_after", 0),
                 "turns_here": turns_here, "is_ending": bool(ending)},
        "insight": insight,
        "messages": [{
            "id": m.id, "role": m.role, "speaker": m.speaker, "node": m.node,
            "content": m.content if (not m.hidden or privileged) else REMOVED,
            "hidden": m.hidden, "created_at": m.created_at.isoformat() if m.created_at else None} for m in msgs],
        "path": [{"node": d.node, "node_title": nodes.get(d.node, {}).get("title", d.node),
                  "choice": d.choice, "next": d.next_node} for d in decisions],
        # Only scenes this student has actually reached (no spoilers for other branches).
        "scenes": {nid: {"title": nodes[nid]["title"], "prompt": nodes[nid]["prompt"]}
                   for nid in visited if nid in nodes},
        "start": sc.get("start"),
        "outcome": ({"label": s.outcome, "type": s.outcome_type,
                     "teacher_feedback": ending["feedback"] if ending else "",
                     "ai_feedback": s.feedback or ""} if s.status == "completed" else None),
        "progress": {"visited": len([v for v in visited if v in nodes]), "total": max(1, len(nodes))},
    }


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def conversation_record(db: Session, s: PlaySession, course: str | None = None) -> dict:
    """One conversation as a plain dictionary for exports (see exports.py for the shape).
    Staff-only data: includes the judge's notes and text an administrator hid."""
    nodes = (s.snapshot or {}).get("nodes") or {}
    student = s.student
    name = student.name if student else "Deleted student"
    if course is None:
        course = db.scalar(
            select(Classroom.name).join(Enrollment, Enrollment.class_id == Classroom.id)
            .where(Enrollment.student_id == s.student_id).order_by(Classroom.name).limit(1)) or ""
    lines = []
    for m in db.scalars(select(Message).where(Message.session_id == s.id).order_by(Message.id)):
        if m.role == "user":
            kind, speaker = "student", name
        elif m.role == "assistant":
            kind, speaker = "character", m.speaker or "Character"
        else:
            kind, speaker = SYSTEM_KIND.get(m.speaker or "", "notice"), ""
        lines.append({"at": _iso(m.created_at), "scene": nodes.get(m.node, {}).get("title", m.node or ""),
                      "kind": kind, "speaker": speaker, "text": m.content, "hidden": bool(m.hidden)})
    flags = db.scalar(select(func.count(Flag.id)).where(Flag.session_id == s.id)) or 0
    return {
        "id": s.id, "scenario": s.scenario.title if s.scenario else "Deleted scenario",
        "student": name, "email": student.email if student else "", "course": course,
        "attempt": s.attempt, "status": s.status, "paused": bool(s.ai_paused),
        "outcome": s.outcome, "outcome_type": s.outcome_type, "messages_used": s.turns,
        "started_at": _iso(s.started_at), "completed_at": _iso(s.completed_at),
        "flags": flags, "feedback": s.feedback or "", "lines": lines,
    }
