"""Who may see what. Kept in one place so the rules are easy to audit (NFR-5.3.6/5.3.7)."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Assignment, Classroom, Enrollment, PlaySession, Scenario, User


def student_class_ids(db: Session, student_id: int) -> list[int]:
    return list(db.scalars(select(Enrollment.class_id).where(Enrollment.student_id == student_id)))


def teacher_class_ids(db: Session, teacher_id: int) -> list[int]:
    return list(db.scalars(select(Classroom.id).where(Classroom.teacher_id == teacher_id)))


def is_assigned_to(db: Session, scenario_id: int, student_id: int) -> bool:
    return db.scalar(
        select(Assignment.id).join(Enrollment, Enrollment.class_id == Assignment.class_id)
        .where(Assignment.scenario_id == scenario_id, Enrollment.student_id == student_id).limit(1)
    ) is not None


def can_manage_scenario(user: User, sc: Scenario) -> bool:
    return user.role == "admin" or (user.role == "teacher" and sc.owner_id == user.id)


def get_scenario_for_edit(db: Session, user: User, scenario_id: int) -> Scenario:
    sc = db.get(Scenario, scenario_id)
    if not sc or not can_manage_scenario(user, sc):
        raise HTTPException(404, "Scenario not found.")
    return sc


def teacher_can_see_student(db: Session, teacher: User, student_id: int) -> bool:
    return db.scalar(
        select(Enrollment.id).join(Classroom, Classroom.id == Enrollment.class_id)
        .where(Classroom.teacher_id == teacher.id, Enrollment.student_id == student_id).limit(1)
    ) is not None


def can_view_session(db: Session, user: User, s: PlaySession) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return s.student_id == user.id
    if user.role == "teacher":
        if s.student_id == user.id:            # their own preview runs
            return True
        sc = db.get(Scenario, s.scenario_id)
        return bool(sc and sc.owner_id == user.id) or teacher_can_see_student(db, user, s.student_id)
    return False   # it_support: no access to student conversations (privacy)


def get_session_for_view(db: Session, user: User, session_id: int) -> PlaySession:
    s = db.get(PlaySession, session_id)
    if not s or not can_view_session(db, user, s):
        raise HTTPException(404, "Session not found.")
    return s
