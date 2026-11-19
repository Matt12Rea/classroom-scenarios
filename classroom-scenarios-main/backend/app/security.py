"""Passwords, login tokens, role checks and rate limiting."""
import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import config
from .database import get_db
from .models import User

# ---------------------------------------------------------------- passwords --
# PBKDF2-HMAC-SHA256 with 600k iterations (OWASP 2023+ guidance, NFR-5.3.4).
# Standard library only, so there is no native dependency to install.
_ITER = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITER)
    return f"pbkdf2_sha256${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iters))
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_hex(8))


def check_login(db: Session, email: str, password: str) -> User | None:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user:
        verify_password(password, _DUMMY_HASH)   # same timing whether or not the email exists
        return None
    return user if verify_password(password, user.password_hash) else None


def validate_new_password(pw: str):
    if len(pw) < config.PASSWORD_MIN_LENGTH:
        raise HTTPException(422, f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters.")
    if pw.isalpha() or pw.isdigit():
        raise HTTPException(422, "Password must mix letters with numbers or symbols.")


def temp_password() -> str:
    return "-".join(secrets.token_hex(2) for _ in range(3))   # e.g. 3f2a-91bc-07de


# ------------------------------------------------------------------- tokens --
def create_token(user: User) -> tuple[str, datetime]:
    exp = datetime.now(timezone.utc) + timedelta(minutes=config.SESSION_TIMEOUT_MINUTES)
    token = jwt.encode({"sub": str(user.id), "role": user.role, "tv": user.token_version,
                        "exp": exp}, config.SECRET_KEY, algorithm="HS256")
    return token, exp


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    """Replaces the old 'student:42' placeholder. The token is signed, expires,
    and is re-checked against the database on every request so a disabled account
    or changed password locks the user out immediately."""
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Please sign in.")
    try:
        data = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Please sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "Please sign in.")
    user = db.get(User, int(data["sub"]))
    if not user or not user.active or user.token_version != data.get("tv"):
        raise HTTPException(401, "Please sign in.")
    return user


def require(*roles: str):
    """Dependency factory: require(“teacher”, “admin”) – REQ-3.6.2 / 3.6.5."""
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You don't have permission to do that. "   # REQ-3.6.6
                                     "Ask an administrator if you need access.")
        return user
    return checker


# ------------------------------------------------------------ rate limiting --
_hits: dict[str, deque] = defaultdict(deque)


def _hit_memory(key: str, limit: int, window: int) -> bool:
    q, t = _hits[key], time.time()
    while q and q[0] < t - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(t)
    return True


def _hit_db(key: str, limit: int, window: int) -> bool:
    """Shared across processes and servers. Uses its own short transaction so a
    failed request never rolls back the count."""
    from .database import SessionLocal
    from .models import RateHit
    t = time.time()
    db = SessionLocal()
    try:
        n = db.scalar(select(func.count(RateHit.id)).where(RateHit.key == key, RateHit.at >= t - window)) or 0
        if n >= limit:
            return False
        db.add(RateHit(key=key, at=t))
        if secrets.randbelow(200) == 0:          # occasional clean-up of old entries
            db.execute(delete(RateHit).where(RateHit.at < t - 3600))
        db.commit()
        return True
    finally:
        db.close()


def hit(key: str, limit: int, window: int, message: str):
    ok = (_hit_db if config.RATE_LIMIT_BACKEND == "db" else _hit_memory)(key, limit, window)
    if not ok:
        raise HTTPException(429, message)


def reset_rate_limits():
    """Used by the tests."""
    _hits.clear()
    from .database import SessionLocal
    from .models import RateHit
    db = SessionLocal()
    try:
        db.execute(delete(RateHit))
        db.commit()
    finally:
        db.close()


def turn_rate_limit(user: User = Depends(current_user)) -> User:
    limit, window = config.TURN_RATE_LIMIT
    hit(f"turn:{user.id}", limit, window, "You're sending messages very quickly. Wait a moment and try again.")
    return user


def client_ip(request: Request) -> str:
    # Behind a reverse proxy, uvicorn --proxy-headers puts the real visitor's
    # address here (from X-Forwarded-For), so limits apply per visitor.
    return request.client.host if request.client else "?"
