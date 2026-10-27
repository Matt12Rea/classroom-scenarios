from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
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
    email: str
    password: str


@router.post("/login")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    limit, window = config.LOGIN_RATE_LIMIT
    hit(f"login:{req.email.lower()}:{client_ip(request)}", limit, window,
        "Too many sign-in attempts. Wait a few minutes and try again.")
    user = check_login(db, req.email, req.password)
    if not user:
        raise HTTPException(401, "That email and password don't match. Check both and try again.")
    if not user.active:
        raise HTTPException(403, "This account is disabled. Contact your school administrator.")
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
    current_password: str
    new_password: str


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
