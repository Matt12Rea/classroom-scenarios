"""Create the first accounts, and optionally the demo school.

    python seed.py --admin admin@university.edu    # first admin only (prints a temporary password)
    python seed.py --demo                          # the demo school (see docs/DEMO_GUIDE.md)

Demo accounts all use the password  demo-pass-1  (set DEMO_PASSWORD to choose your own).

The demo school is small on purpose, and nothing in it is random: every student is
in exactly one clearly different state, and every conversation was written to match
its result (demo_content.py). docs/DEMO_GUIDE.md lists who is who and what to click.
"""
import argparse
import os
from datetime import timedelta

from app import safety
from app.database import SessionLocal, init_db
from app.models import (Assignment, Classroom, Decision, Enrollment, Flag, Message, PlaySession, Scenario,
                        User, now)
from app.security import hash_password, temp_password
from demo_content import BAITING, BANK_CASE, GENETICS_CASE, HISTORY_CASE, IRB_CASE, SCRIPTS

# Shared password for every demo account. Set DEMO_PASSWORD to choose your own.
DEMO_PW = os.getenv("DEMO_PASSWORD", "") or "demo-pass-1"

BANK_TITLE = "Prairie State Bank: the fixed-rate question"
IRB_TITLE = "IRB review: the Cyberball study"
GENETICS_TITLE = "Genetics clinic: two carriers"
HISTORY_TITLE = "1787: the representation deadlock"

# name, email. student@demo.school (Maya) is the account to sign in with: she is in all
# three courses, with one scenario finished, one under way and one not started.
STUDENTS = [("Maya Chen", "student@demo.school"), ("Leo Park", "leo@demo.school"),
            ("Priya Singh", "priya@demo.school"), ("Owen Brooks", "owen@demo.school"),
            ("Zoe Martin", "zoe@demo.school"), ("Eli Duarte", "eli@demo.school"),
            ("Nora Kim", "nora@demo.school"), ("Sam Patel", "sam@demo.school"),
            ("Ava Lopez", "ava@demo.school"), ("Ben Carter", "ben@demo.school")]
ROSTERS = {"econ": ["Maya Chen", "Leo Park", "Priya Singh", "Owen Brooks"],
           "psyc": ["Maya Chen", "Zoe Martin", "Eli Duarte", "Nora Kim"],
           "biol": ["Maya Chen", "Sam Patel", "Ava Lopez", "Ben Carter"]}

# Who has done what. route = the paths taken, in order; a final (scene, None) is a
# conversation still in progress. Students not listed here have not started.
ATTEMPTS = [
    # ECON 210: one success, one partial, one mid-way (and Owen, paused: see below)
    ("bank", "Maya Chen", 6, [("briefing", "Explained the bank's interest-rate risk"),
                              ("options", "Recommended a way to manage the risk")]),
    ("bank", "Leo Park", 4, [("briefing", "Endorsed writing more fixed-rate loans"),
                             ("squeeze", "Diagnosed the maturity mismatch")]),
    ("bank", "Priya Singh", 1, [("briefing", "Explained the bank's interest-rate risk"), ("options", None)]),
    # PSYC 310: one success, one not successful, one just begun (Nora has not started)
    ("irb", "Zoe Martin", 5, [("deception", "Justified the deception and planned a debriefing"),
                              ("pool", "Protected voluntariness and participant welfare")]),
    ("irb", "Eli Duarte", 3, [("deception", "Waved the concern away"), ("revise", "Withdrew the protocol")]),
    ("irb", "Maya Chen", 0, [("deception", None)]),
    # BIOL 340 (two characters in a scene): success, partial, not successful (Maya has not started)
    ("genetics", "Sam Patel", 5, [("results", "Explained autosomal recessive inheritance accurately"),
                                  ("options", "Described testing options non-directively")]),
    ("genetics", "Ava Lopez", 2, [("results", "Explained autosomal recessive inheritance accurately"),
                                  ("options", "Steered the couple's decision")]),
    ("genetics", "Ben Carter", 2, [("results", "Gave inaccurate risk information"),
                                   ("confusion", "Left the misunderstanding in place")]),
]
# The AI's written feedback for one finished attempt, so the feedback panel has an example.
MAYA_FEEDBACK = ("You explained the risk in terms Carol could act on: “we'd be paying more for the money than the "
                 "loan earns” is exactly the maturity mismatch, with numbers. Your recommendation kept the builder's "
                 "business instead of refusing the loans. Next time, say how much higher than 6% the fixed rate would "
                 "need to be, so the committee has a figure to react to.")


def user(db, name, email, role):
    u = db.query(User).filter_by(email=email).first()
    if not u:
        u = User(name=name, email=email, role=role, password_hash=hash_password(DEMO_PW))
        db.add(u)
        db.flush()
    return u


def play(db, scenario: Scenario, key: str, student: User, days_ago: int, route: list) -> PlaySession:
    """Write one demo attempt by following `route` through the scripted conversations."""
    d = scenario.definition
    names = {c["id"]: c["name"] for c in d["characters"]}
    t = now() - timedelta(days=days_ago, hours=3)
    ps = PlaySession(scenario_id=scenario.id, student_id=student.id, node=d["start"], snapshot=d,
                     started_at=t, updated_at=t)
    db.add(ps)
    db.flush()
    node = d["start"]
    for scene, label in route:
        assert scene == node, f"demo route for {student.name} leaves the scenario at {scene}"
        script = SCRIPTS[key][(scene, label)]
        for said, replies in script["turns"]:
            t += timedelta(minutes=1, seconds=20)
            db.add(Message(session_id=ps.id, role="user", content=said, node=node, created_at=t))
            for i, (cid, line) in enumerate(replies):
                first = i == 0          # usage and timing are recorded once per AI reply
                db.add(Message(session_id=ps.id, role="assistant", content=line, node=node, speaker=names[cid],
                               created_at=t + timedelta(seconds=2 + i),
                               latency_ms=1200 if first else None, input_tokens=700 if first else None,
                               output_tokens=45 if first else None))
            ps.turns += 1
        if label is None:               # still in this scene
            break
        choice = next(c for c in d["nodes"][node]["choices"] if c["label"] == label)
        t += timedelta(seconds=5)
        db.add(Decision(session_id=ps.id, node=node, choice=label, next_node=choice["next"], created_at=t))
        db.add(Message(session_id=ps.id, role="system", content=label, node=node, speaker="Decision",
                       in_context=False, created_at=t))
        db.add(Message(session_id=ps.id, role="system", content=script["why"], node=node, speaker="Inference",
                       in_context=False, created_at=t))
        if choice.get("feedback"):
            db.add(Message(session_id=ps.id, role="system", content=choice["feedback"], node=node,
                           speaker="Feedback", in_context=False, created_at=t))
        node = choice["next"]
    ps.node, ps.updated_at = node, t
    ending = d["nodes"][node].get("ending")
    if ending:
        ps.status, ps.outcome, ps.outcome_type, ps.completed_at = "completed", ending["label"], ending["type"], t
    db.flush()
    return ps


def paused_session(db, scenario: Scenario, student: User) -> PlaySession:
    """Owen's attempt: three baiting messages, so it was paused automatically and is
    waiting for an administrator to review and resume it."""
    d = scenario.definition
    t = now() - timedelta(hours=5)
    ps = PlaySession(scenario_id=scenario.id, student_id=student.id, node=d["start"], snapshot=d,
                     started_at=t, updated_at=t, ai_paused=True)
    db.add(ps)
    db.flush()
    carol = d["characters"][0]["name"]
    for said, reply, reason in BAITING:
        t += timedelta(minutes=1)
        answered = reply is not None
        m = Message(session_id=ps.id, role="user", content=said, node=ps.node, created_at=t, in_context=answered)
        db.add(m)
        db.flush()
        if answered:
            db.add(Message(session_id=ps.id, role="assistant", content=reply, node=ps.node, speaker=carol,
                           created_at=t + timedelta(seconds=2), latency_ms=1100, input_tokens=700,
                           output_tokens=30))
            ps.turns += 1
        db.add(Flag(session_id=ps.id, message_id=m.id, student_id=student.id, source="auto_input",
                    category="manipulation", severity="medium", excerpt=said, reason=reason, created_at=t))
    db.add(Message(session_id=ps.id, role="system", content=safety.PAUSE_MESSAGE, node=ps.node, speaker="Paused",
                   in_context=False, created_at=t))
    db.add(Flag(session_id=ps.id, student_id=student.id, source="auto_input", category="repeated",
                severity="high", excerpt="", created_at=t,
                reason=f"Session paused automatically after {len(BAITING)} flagged messages. Review the "
                       "conversation, then resume the session so the student can continue."))
    ps.updated_at = t
    return ps


def demo(db):
    admin = user(db, "Avery Admin", "admin@demo.school", "admin")
    user(db, "Ira Support", "it@demo.school", "it_support")
    rivera = user(db, "Dr. Dana Rivera", "teacher@demo.school", "teacher")
    okafor = user(db, "Prof. Chris Okafor", "teacher2@demo.school", "teacher")
    people = {name: user(db, name, email, "student") for name, email in STUDENTS}

    courses = {"econ": Classroom(name="ECON 210 – Money and Banking", teacher_id=rivera.id),
               "psyc": Classroom(name="PSYC 310 – Research Methods", teacher_id=rivera.id),
               "biol": Classroom(name="BIOL 340 – Human Genetics", teacher_id=okafor.id)}
    db.add_all(courses.values())
    db.flush()
    for key, names in ROSTERS.items():
        for name in names:
            db.add(Enrollment(class_id=courses[key].id, student_id=people[name].id))

    scenarios = {
        "bank": Scenario(owner_id=rivera.id, title=BANK_TITLE, status="published", definition=BANK_CASE,
                         description="Advise a community bank's president whether to write 30-year fixed-rate "
                                     "mortgages as the Fed raises rates."),
        "irb": Scenario(owner_id=rivera.id, title=IRB_TITLE, status="published", definition=IRB_CASE, max_turns=24,
                        description="Defend a deception study in front of the Institutional Review Board."),
        "genetics": Scenario(owner_id=okafor.id, title=GENETICS_TITLE, status="published",
                             definition=GENETICS_CASE, max_turns=24,
                             description="Explain a cystic fibrosis carrier result to an expecting couple. "
                                         "Both parents are in the room and both speak."),
        "history": Scenario(owner_id=rivera.id, title=HISTORY_TITLE, status="draft", definition=HISTORY_CASE,
                            description="A draft, not yet published: as a small-state delegate, break the "
                                        "Convention's deadlock over representation."),
    }
    db.add_all(scenarios.values())
    db.flush()
    db.add_all([Assignment(scenario_id=scenarios["bank"].id, class_id=courses["econ"].id,
                           due_at=now() + timedelta(days=5)),
                Assignment(scenario_id=scenarios["irb"].id, class_id=courses["psyc"].id,
                           due_at=now() + timedelta(days=9)),
                Assignment(scenario_id=scenarios["genetics"].id, class_id=courses["biol"].id,
                           due_at=now() + timedelta(days=12))])

    sessions = {}
    for key, name, days_ago, route in ATTEMPTS:
        sessions[(key, name)] = play(db, scenarios[key], key, people[name], days_ago, route)
    sessions[("bank", "Maya Chen")].feedback = MAYA_FEEDBACK
    paused_session(db, scenarios["bank"], people["Owen Brooks"])

    # One flag that has already been dealt with, so the "Action taken" tab has an example:
    # the instructor reported a character's line, and the administrator followed up.
    ben = sessions[("genetics", "Ben Carter")]
    line = db.query(Message).filter_by(session_id=ben.id, role="assistant").order_by(Message.id.desc()).first()
    db.add(Flag(session_id=ben.id, message_id=line.id, student_id=ben.student_id, reporter_id=okafor.id,
                source="report", category="other", severity="low", excerpt=line.content, status="actioned",
                reason="Reported by teacher: Luis accepts the wrong statistic too easily here. Is that intended?",
                reviewer_id=admin.id, reviewed_at=now() - timedelta(days=1),
                review_note="Checked with Prof. Okafor: intended. Luis's misunderstanding is the point of the "
                            "scene. No change needed.",
                created_at=now() - timedelta(days=2)))
    db.commit()
    print("Demo school created. Every demo account uses the password:", DEMO_PW)
    for e, what in (("admin@demo.school", "administrator: one paused session is waiting for review"),
                    ("teacher@demo.school", "instructor: two published scenarios with results, one draft"),
                    ("student@demo.school", "student: one finished, one in progress, one not started"),
                    ("it@demo.school", "IT support: system status only")):
        print(f"   {e:<22} {what}")
    print("See docs/DEMO_GUIDE.md for a five-minute walkthrough.")


def first_admin(db, email):
    if db.query(User).filter_by(email=email.lower()).first():
        print("That account already exists.")
        return
    pw = temp_password()
    db.add(User(name="Administrator", email=email.lower(), role="admin", password_hash=hash_password(pw),
                must_change_password=True))
    db.commit()
    print(f"Admin created: {email}\nTemporary password: {pw}\n(You'll be asked to change it on first sign-in.)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--admin", help="email for the first administrator account")
    ap.add_argument("--demo", action="store_true", help="load the demo school (see docs/DEMO_GUIDE.md)")
    a = ap.parse_args()
    init_db()
    db = SessionLocal()
    try:
        if a.demo:
            if db.query(User).filter_by(email="admin@demo.school").first():
                print("Demo data already loaded.")
            else:
                demo(db)
        if a.admin:
            first_admin(db, a.admin)
        if not (a.demo or a.admin):
            ap.print_help()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
