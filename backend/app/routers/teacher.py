"""Teacher tools: scenario authoring (SRS 3.1), classes and assignments,
analytics and reports (SRS 3.5)."""
import csv
import io
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import get_scenario_for_edit, teacher_can_see_student
from ..database import get_db
from ..models import (Assignment, Classroom, Decision, Enrollment, Flag, PlaySession, Scenario, User,
                      audit, now)
from ..scenario_schema import DEFAULT_BOUNDARIES, EXAMPLE, normalize, validate
from ..security import require

router = APIRouter(prefix="/api", tags=["teacher"])
staff = require("teacher", "admin")


# ================================================================ scenarios ==
def scenario_out(db: Session, sc: Scenario, full: bool = False) -> dict:
    assigns = db.execute(select(Assignment, Classroom).join(Classroom, Classroom.id == Assignment.class_id)
                         .where(Assignment.scenario_id == sc.id)).all()
    played = db.scalar(select(func.count(PlaySession.id)).where(
        PlaySession.scenario_id == sc.id, PlaySession.is_preview.is_(False))) or 0
    d = normalize(sc.definition)
    out = {"id": sc.id, "title": sc.title, "description": sc.description, "status": sc.status,
           "max_turns": sc.max_turns, "owner_id": sc.owner_id, "owner_name": sc.owner.name if sc.owner else "",
           "updated_at": sc.updated_at.isoformat() if sc.updated_at else None,
           "scene_count": len(d["nodes"]), "sessions": played,
           "assignments": [{"class_id": c.id, "class_name": c.name,
                            "due_at": a.due_at.isoformat() if a.due_at else None} for a, c in assigns]}
    if full:
        out["definition"] = d
        out["validation"] = validate(sc.title, d)
    return out


@router.get("/scenarios")
def list_scenarios(user: User = Depends(staff), db: Session = Depends(get_db)):
    q = select(Scenario).order_by(Scenario.updated_at.desc())
    if user.role == "teacher":
        q = q.where(Scenario.owner_id == user.id)
    return [scenario_out(db, sc) for sc in db.scalars(q)]


class ScenarioIn(BaseModel):
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    definition: dict = Field(default_factory=dict)
    max_turns: int = Field(default=30, ge=1, le=200)


class CreateReq(ScenarioIn):
    template: str = "blank"     # blank | example


@router.post("/scenarios")
def create_scenario(req: CreateReq, user: User = Depends(require("teacher", "admin")),
                    db: Session = Depends(get_db)):           # REQ-3.1.1
    if req.template == "example":
        d, title = EXAMPLE, req.title or "Hallway conflict (example)"
        desc = req.description or "Help a frustrated classmate who thinks a grade was unfair."
    else:
        d = normalize(req.definition) if req.definition else normalize({
            "boundaries": DEFAULT_BOUNDARIES, "characters": [], "start": "scene_1",
            "nodes": {"scene_1": {"title": "Opening scene", "prompt": "", "choices": []}}})
        title, desc = req.title or "Untitled scenario", req.description
    sc = Scenario(owner_id=user.id, title=title, description=desc, definition=d, max_turns=req.max_turns)
    db.add(sc)
    db.flush()
    audit(db, user, "scenario.create", f"scenario:{sc.id}", title=title)
    db.commit()
    return scenario_out(db, sc, full=True)


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    return scenario_out(db, get_scenario_for_edit(db, user, scenario_id), full=True)


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: int, req: ScenarioIn, user: User = Depends(staff),
                    db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    d = normalize(req.definition)
    if not req.title.strip():
        raise HTTPException(422, {"message": "Give the scenario a title before saving.",
                                  "errors": [{"field": "title", "message": "Give the scenario a title."}]})
    if sc.status == "published":
        v = validate(req.title, d)
        if v["errors"]:
            raise HTTPException(422, {"message": "This scenario is live, so it can't be saved with problems. "
                                                 "Fix the highlighted fields or unpublish it first.",
                                      "errors": v["errors"]})
    sc.title, sc.description, sc.definition, sc.max_turns = req.title.strip(), req.description, d, req.max_turns
    sc.updated_at = now()
    db.commit()
    return scenario_out(db, sc, full=True)


class ValidateReq(BaseModel):
    title: str = ""
    definition: dict = Field(default_factory=dict)


@router.post("/scenarios/validate")
def validate_draft(req: ValidateReq, user: User = Depends(staff)):
    return validate(req.title, normalize(req.definition))


@router.post("/scenarios/{scenario_id}/publish")
def publish(scenario_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    v = validate(sc.title, normalize(sc.definition))
    if v["errors"]:                                                  # REQ-3.1.6
        raise HTTPException(422, {"message": f"Fix {len(v['errors'])} problem(s) before publishing.",
                                  "errors": v["errors"]})
    sc.status = "published"
    audit(db, user, "scenario.publish", f"scenario:{sc.id}", title=sc.title)
    db.commit()
    return scenario_out(db, sc, full=True)


@router.post("/scenarios/{scenario_id}/unpublish")
def unpublish(scenario_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    sc.status = "draft"
    audit(db, user, "scenario.unpublish", f"scenario:{sc.id}", title=sc.title)
    db.commit()
    return scenario_out(db, sc, full=True)


@router.post("/scenarios/{scenario_id}/archive")
def archive(scenario_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    sc.status = "archived"
    audit(db, user, "scenario.archive", f"scenario:{sc.id}", title=sc.title)
    db.commit()
    return scenario_out(db, sc, full=True)


@router.post("/scenarios/{scenario_id}/duplicate")
def duplicate(scenario_id: int, user: User = Depends(require("teacher", "admin")), db: Session = Depends(get_db)):
    src = get_scenario_for_edit(db, user, scenario_id)
    sc = Scenario(owner_id=user.id, title=f"{src.title} (copy)", description=src.description,
                  definition=normalize(src.definition), max_turns=src.max_turns)
    db.add(sc)
    db.commit()
    return scenario_out(db, sc, full=True)


@router.delete("/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    played = db.scalar(select(func.count(PlaySession.id)).where(
        PlaySession.scenario_id == sc.id, PlaySession.is_preview.is_(False)))
    if played:
        raise HTTPException(409, "Students have played this scenario. Archive it instead so their results are kept.")
    audit(db, user, "scenario.delete", f"scenario:{sc.id}", title=sc.title)
    db.delete(sc)
    db.commit()
    return {"ok": True}


class AssignReq(BaseModel):
    class_id: int
    due_at: datetime | None = None


@router.post("/scenarios/{scenario_id}/assignments")
def assign(scenario_id: int, req: AssignReq, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    cl = db.get(Classroom, req.class_id)
    if not cl or (user.role == "teacher" and cl.teacher_id != user.id):
        raise HTTPException(404, "Class not found.")
    if sc.status != "published":
        raise HTTPException(409, "Publish the scenario before assigning it.")
    a = db.scalar(select(Assignment).where(Assignment.scenario_id == sc.id, Assignment.class_id == cl.id))
    if a:
        a.due_at = req.due_at
    else:
        db.add(Assignment(scenario_id=sc.id, class_id=cl.id, due_at=req.due_at))
    db.commit()
    return scenario_out(db, sc, full=True)


@router.delete("/scenarios/{scenario_id}/assignments/{class_id}")
def unassign(scenario_id: int, class_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    a = db.scalar(select(Assignment).where(Assignment.scenario_id == sc.id, Assignment.class_id == class_id))
    if a:
        db.delete(a)
        db.commit()
    return scenario_out(db, sc, full=True)


# ================================================================== classes ==
def class_out(db: Session, cl: Classroom) -> dict:
    students = db.scalars(select(User).join(Enrollment, Enrollment.student_id == User.id)
                          .where(Enrollment.class_id == cl.id).order_by(User.name)).all()
    return {"id": cl.id, "name": cl.name, "teacher_id": cl.teacher_id,
            "teacher_name": cl.teacher.name if cl.teacher else None,
            "students": [{"id": s.id, "name": s.name, "email": s.email, "active": s.active} for s in students]}


def _class_for_edit(db, user, class_id) -> Classroom:
    cl = db.get(Classroom, class_id)
    if not cl or (user.role == "teacher" and cl.teacher_id != user.id):
        raise HTTPException(404, "Class not found.")
    return cl


@router.get("/classes")
def list_classes(user: User = Depends(staff), db: Session = Depends(get_db)):
    q = select(Classroom).order_by(Classroom.name)
    if user.role == "teacher":
        q = q.where(Classroom.teacher_id == user.id)
    return [class_out(db, c) for c in db.scalars(q)]


class ClassReq(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    teacher_id: int | None = None


@router.post("/classes")
def create_class(req: ClassReq, user: User = Depends(staff), db: Session = Depends(get_db)):
    teacher_id = user.id if user.role == "teacher" else req.teacher_id
    if teacher_id:
        t = db.get(User, teacher_id)
        if not t or t.role != "teacher":
            raise HTTPException(422, "Choose a teacher account for this class.")
    cl = Classroom(name=req.name.strip(), teacher_id=teacher_id)
    db.add(cl)
    db.flush()
    audit(db, user, "class.create", f"class:{cl.id}", name=cl.name)
    db.commit()
    return class_out(db, cl)


@router.patch("/classes/{class_id}")
def update_class(class_id: int, req: ClassReq, user: User = Depends(staff), db: Session = Depends(get_db)):
    cl = _class_for_edit(db, user, class_id)
    cl.name = req.name.strip()
    if user.role == "admin" and req.teacher_id is not None:
        t = db.get(User, req.teacher_id)
        if not t or t.role != "teacher":
            raise HTTPException(422, "Choose a teacher account for this class.")
        cl.teacher_id = req.teacher_id
    audit(db, user, "class.update", f"class:{cl.id}", name=cl.name, teacher_id=cl.teacher_id)
    db.commit()
    return class_out(db, cl)


@router.delete("/classes/{class_id}")
def delete_class(class_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    cl = _class_for_edit(db, user, class_id)
    audit(db, user, "class.delete", f"class:{cl.id}", name=cl.name)
    db.delete(cl)
    db.commit()
    return {"ok": True}


class EnrollReq(BaseModel):
    emails: list[str]


@router.post("/classes/{class_id}/students")
def enroll(class_id: int, req: EnrollReq, user: User = Depends(staff), db: Session = Depends(get_db)):
    """Add existing student accounts by email. Accounts are created by admins."""
    cl = _class_for_edit(db, user, class_id)
    added, missing = [], []
    for raw in req.emails:
        email = raw.strip().lower()
        if not email:
            continue
        s = db.scalar(select(User).where(User.email == email, User.role == "student"))
        if not s:
            missing.append(email)
            continue
        if not db.scalar(select(Enrollment.id).where(Enrollment.class_id == cl.id, Enrollment.student_id == s.id)):
            db.add(Enrollment(class_id=cl.id, student_id=s.id))
            added.append(email)
    audit(db, user, "class.enroll", f"class:{cl.id}", added=added)
    db.commit()
    return {**class_out(db, cl), "added": added, "not_found": missing}


@router.delete("/classes/{class_id}/students/{student_id}")
def unenroll(class_id: int, student_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    cl = _class_for_edit(db, user, class_id)
    e = db.scalar(select(Enrollment).where(Enrollment.class_id == cl.id, Enrollment.student_id == student_id))
    if e:
        db.delete(e)
        audit(db, user, "class.unenroll", f"class:{cl.id}", student_id=student_id)
        db.commit()
    return class_out(db, cl)


# ================================================================ analytics ==
def _filtered_sessions(db, sc_id, class_id, date_from, date_to, student_ids=None):
    q = select(PlaySession).where(PlaySession.scenario_id == sc_id, PlaySession.is_preview.is_(False),
                                  PlaySession.status != "abandoned")
    if date_from:
        q = q.where(PlaySession.started_at >= date_from)
    if date_to:
        q = q.where(PlaySession.started_at <= date_to)
    if student_ids is not None:
        q = q.where(PlaySession.student_id.in_(student_ids))
    return db.scalars(q.order_by(PlaySession.id)).all()


def _roster(db, sc: Scenario, user: User, class_id: int | None):
    """Students the viewer may see who have this scenario assigned."""
    q = (select(User, Classroom).join(Enrollment, Enrollment.student_id == User.id)
         .join(Classroom, Classroom.id == Enrollment.class_id)
         .join(Assignment, Assignment.class_id == Classroom.id)
         .where(Assignment.scenario_id == sc.id))
    if user.role == "teacher":
        q = q.where(Classroom.teacher_id == user.id)
    if class_id:
        q = q.where(Classroom.id == class_id)
    roster = {}
    for u, c in db.execute(q.order_by(User.name)).all():
        roster.setdefault(u.id, (u, c.name))
    return roster


@router.get("/scenarios/{scenario_id}/analytics")
def analytics(scenario_id: int, class_id: int | None = None, date_from: datetime | None = Query(None, alias="from"),
              date_to: datetime | None = Query(None, alias="to"), user: User = Depends(staff),
              db: Session = Depends(get_db)):
    sc = get_scenario_for_edit(db, user, scenario_id)
    d = normalize(sc.definition)
    roster = _roster(db, sc, user, class_id)
    sessions = _filtered_sessions(db, sc.id, class_id, date_from, date_to, list(roster))
    latest: dict[int, PlaySession] = {}
    attempts = Counter()
    for s in sessions:
        latest[s.student_id] = s
        attempts[s.student_id] += 1
    flags = Counter(dict(db.execute(select(Flag.student_id, func.count(Flag.id)).where(
        Flag.session_id.in_([s.id for s in sessions] or [0])).group_by(Flag.student_id)).all()))

    students = []
    for uid, (u, cname) in roster.items():
        s = latest.get(uid)
        students.append({"student_id": uid, "name": u.name, "email": u.email, "class_name": cname,
                         "status": s.status if s else "not_started", "attempts": attempts[uid],
                         "outcome": s.outcome if s else None, "outcome_type": s.outcome_type if s else None,
                         "turns": s.turns if s else 0, "session_id": s.id if s else None,
                         "last_activity": s.updated_at.isoformat() if s else None, "flags": flags[uid]})

    done = [s for s in latest.values() if s.status == "completed"]
    mins = [(s.completed_at - s.started_at).total_seconds() / 60 for s in done if s.completed_at and s.started_at]
    outcomes = Counter((s.outcome, s.outcome_type) for s in done)
    choice_counts: dict[str, Counter] = defaultdict(Counter)
    for dec in db.scalars(select(Decision).where(Decision.session_id.in_([s.id for s in sessions] or [0]))):
        choice_counts[dec.node][dec.choice] += 1
    return {
        "scenario": {"id": sc.id, "title": sc.title, "status": sc.status},
        "summary": {"assigned": len(roster), "started": len(latest), "completed": len(done),
                    "success": sum(1 for s in done if s.outcome_type == "success"),
                    "partial": sum(1 for s in done if s.outcome_type == "partial"),
                    "fail": sum(1 for s in done if s.outcome_type == "fail"),
                    "avg_turns": round(sum(s.turns for s in done) / len(done), 1) if done else None,
                    "avg_minutes": round(sum(mins) / len(mins), 1) if mins else None},
        "outcomes": [{"label": k[0], "type": k[1], "count": v} for k, v in outcomes.most_common()],
        "decisions": [{"node": nid, "node_title": d["nodes"].get(nid, {}).get("title", nid),
                       "choices": [{"label": c["label"], "count": choice_counts[nid].get(c["label"], 0)}
                                   for c in d["nodes"].get(nid, {}).get("choices", [])]}
                      for nid in d["nodes"] if not d["nodes"][nid]["ending"]],
        "students": students,
    }


@router.get("/scenarios/{scenario_id}/export.csv")
def export_csv(scenario_id: int, class_id: int | None = None,
               date_from: datetime | None = Query(None, alias="from"),
               date_to: datetime | None = Query(None, alias="to"),
               user: User = Depends(staff), db: Session = Depends(get_db)):   # REQ-3.5.7
    sc = get_scenario_for_edit(db, user, scenario_id)
    roster = _roster(db, sc, user, class_id)
    sessions = _filtered_sessions(db, sc.id, class_id, date_from, date_to, list(roster))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["student", "email", "class", "attempt", "status", "outcome", "outcome_type", "messages",
                "decisions", "started", "completed"])
    for s in sessions:
        u, cname = roster[s.student_id]
        path = " > ".join(x.choice for x in db.scalars(
            select(Decision).where(Decision.session_id == s.id).order_by(Decision.id)))
        w.writerow([u.name, u.email, cname, s.attempt, s.status, s.outcome or "", s.outcome_type or "", s.turns,
                    path, s.started_at.isoformat() if s.started_at else "",
                    s.completed_at.isoformat() if s.completed_at else ""])
    audit(db, user, "report.export", f"scenario:{sc.id}", rows=len(sessions))
    db.commit()
    name = "".join(ch if ch.isalnum() else "_" for ch in sc.title)[:40] or "report"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


@router.get("/teacher/overview")
def overview(user: User = Depends(staff), db: Session = Depends(get_db)):
    sc_q = select(Scenario.id)
    if user.role == "teacher":
        sc_q = sc_q.where(Scenario.owner_id == user.id)
    sc_ids = list(db.scalars(sc_q)) or [0]
    recent = db.execute(
        select(PlaySession, User, Scenario).join(User, User.id == PlaySession.student_id)
        .join(Scenario, Scenario.id == PlaySession.scenario_id)
        .where(PlaySession.scenario_id.in_(sc_ids), PlaySession.is_preview.is_(False),
               PlaySession.status != "abandoned")
        .order_by(PlaySession.updated_at.desc()).limit(12)).all()
    counts = dict(db.execute(select(Scenario.status, func.count(Scenario.id))
                             .where(Scenario.id.in_(sc_ids)).group_by(Scenario.status)).all())
    return {
        "scenarios": counts,
        "classes": len(list(db.scalars(select(Classroom.id).where(Classroom.teacher_id == user.id)))),
        "in_progress": db.scalar(select(func.count(PlaySession.id)).where(
            PlaySession.scenario_id.in_(sc_ids), PlaySession.status == "in_progress",
            PlaySession.is_preview.is_(False))) or 0,
        "completed": db.scalar(select(func.count(PlaySession.id)).where(
            PlaySession.scenario_id.in_(sc_ids), PlaySession.status == "completed",
            PlaySession.is_preview.is_(False))) or 0,
        "recent": [{"session_id": s.id, "student": u.name, "scenario": sc.title, "status": s.status,
                    "outcome": s.outcome, "outcome_type": s.outcome_type,
                    "updated_at": s.updated_at.isoformat()} for s, u, sc in recent],
    }


@router.get("/students/{student_id}/sessions")
def student_history(student_id: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    if user.role == "teacher" and not teacher_can_see_student(db, user, student_id):
        raise HTTPException(404, "Student not found.")
    q = select(PlaySession, Scenario).join(Scenario, Scenario.id == PlaySession.scenario_id).where(
        PlaySession.student_id == student_id, PlaySession.is_preview.is_(False))
    return [{"session_id": s.id, "scenario": sc.title, "status": s.status, "outcome": s.outcome,
             "outcome_type": s.outcome_type, "turns": s.turns, "attempt": s.attempt,
             "updated_at": s.updated_at.isoformat()}
            for s, sc in db.execute(q.order_by(PlaySession.id.desc())).all()]
