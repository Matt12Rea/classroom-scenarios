from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import User, audit
from ..security import (check_login, client_ip, create_token, current_user, hash_password, hit,
                        validate_new_password, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "must_change_password": u.must_change_password,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "last_login": u.last_login.isoformat() if u.last_login else None}


class LoginReq(BaseModel):
    # Length limits keep an attacker from making the server hash megabytes of "password".
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


# The demo accounts, in the order the sign-in page offers them.
DEMO_ACCOUNTS = [("admin@demo.school", "Administrator", "Reviews safety flags, resumes paused sessions, manages accounts"),
                 ("teacher@demo.school", "Instructor", "Builds scenarios, assigns them, reads results"),
                 ("student@demo.school", "Student", "Plays the assigned scenarios"),
                 ("it@demo.school", "IT support", "Checks system status and the AI connection")]


@router.get("/demo")
def demo_accounts(db: Session = Depends(get_db)):
    """Lets the sign-in page offer the demo accounts when (and only when) this is a
    demo site: LOAD_DEMO_DATA is on, or it's a development copy with the demo school
    loaded. The password is included only if it is the published default."""
    if not (config.LOAD_DEMO_DATA or not config.IS_PROD):
        return {"demo": False, "accounts": []}
    emails = [e for e, _, _ in DEMO_ACCOUNTS]
    present = set(db.scalars(select(User.email).where(User.email.in_(emails), User.active.is_(True))))
    if "admin@demo.school" not in present:
        return {"demo": False, "accounts": []}
    default_pw = config.DEMO_PASSWORD == "demo-pass-1"
    return {"demo": True, "password": config.DEMO_PASSWORD if default_pw else None,
            "accounts": [{"email": e, "role": role, "about": about}
                         for e, role, about in DEMO_ACCOUNTS if e in present]}


@router.post("/login")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    limit, window = config.LOGIN_RATE_LIMIT
    hit(f"login:{req.email.lower()}:{client_ip(request)}", limit, window,
        "Too many sign-in attempts. Wait a few minutes and try again.")
    user = check_login(db, req.email, req.password)
    if not user:
        raise HTTPException(401, "That email and password don't match. Check both and try again.")
    if not user.active:
        raise HTTPException(403, "This account is disabled. Contact your site administrator.")
    user.last_login = datetime.now(timezone.utc)
    db.commit()
    token, exp = create_token(user)
    return {"token": token, "expires_at": exp.isoformat(), "user": user_out(user)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/refresh")
def refresh(user: User = Depends(current_user)):
    """Sliding session: the UI calls this while the user is active."""
    token, exp = create_token(user)
    return {"token": token, "expires_at": exp.isoformat()}


class PasswordReq(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


@router.post("/password")
def change_password(req: PasswordReq, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(400, "Your current password is incorrect.")
    validate_new_password(req.new_password)
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    user.token_version += 1
    audit(db, user, "password.change", f"user:{user.id}")
    db.commit()
    token, exp = create_token(user)
    return {"token": token, "expires_at": exp.isoformat(), "user": user_out(user)}
