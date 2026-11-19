"""Run-time settings an administrator changes from the dashboard, chiefly the
Claude API connection (REQ-3.2.3.10, SRS 2.4 "secure API interface").

* The API key never leaves the server. The admin screen can replace or remove
  it, but only ever shows a short hint such as "sk-ant-…3fQx".
* Stored keys are encrypted (Fernet: AES-128-CBC + HMAC-SHA256) with a key
  derived from SECRET_KEY, so a copy of the database alone does not reveal it.
  If SECRET_KEY changes, the stored key can't be decrypted: the app falls back
  to the ANTHROPIC_API_KEY environment variable and the admin screen says so.
* Values are cached for a few seconds, so a change made on one server process
  reaches the others without a restart.
"""
import base64
import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from . import config
from .database import SessionLocal
from .models import SystemSetting

log = logging.getLogger("aicss.settings")

AI_KEY = "ai"                 # admin overrides: encrypted key, model, mode, review
AI_STATUS_KEY = "ai_status"   # last success / failure, shown on the admin screens
_TTL = 10.0                   # seconds a cached value is trusted

_fernet = Fernet(base64.urlsafe_b64encode(
    hashlib.sha256(b"aicss-settings-v1:" + config.SECRET_KEY.encode()).digest()))


def encrypt(secret: str) -> str:
    return _fernet.encrypt(secret.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def key_hint(secret: str | None) -> str | None:
    if not secret:
        return None
    return f"{secret[:7]}…{secret[-4:]}" if len(secret) > 14 else "…" + secret[-2:]


@dataclass
class AISettings:
    api_key: str = ""
    source: str = "none"            # dashboard | environment | none
    mode: str = "mock"              # claude | mock
    model: str = config.CLAUDE_MODEL
    review_model: str = config.CLAUDE_MODEL
    ai_review: bool = False
    key_unreadable: bool = False    # a dashboard key exists but SECRET_KEY changed
    updated_at: str | None = None
    updated_by: int | None = None
    fingerprint: str = field(default="", repr=False)


_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


def invalidate():
    with _lock:
        _cache.clear()


def _read(key: str) -> tuple[dict, datetime | None, int | None]:
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        return (dict(row.value or {}), row.updated_at, row.updated_by) if row else ({}, None, None)
    finally:
        db.close()


def _write(key: str, value: dict, actor_id: int | None = None):
    db = SessionLocal()
    try:
        row = db.get(SystemSetting, key)
        if row:
            row.value, row.updated_by = value, actor_id
        else:
            db.add(SystemSetting(key=key, value=value, updated_by=actor_id))
        db.commit()
    finally:
        db.close()
    invalidate()


def ai_settings() -> AISettings:
    """The effective AI configuration: dashboard overrides first, then environment."""
    with _lock:
        hit = _cache.get(AI_KEY)
        if hit and time.monotonic() - hit[0] < _TTL:
            return hit[1]  # type: ignore[return-value]
    raw, updated_at, updated_by = _read(AI_KEY)
    s = AISettings(updated_at=updated_at.isoformat() if updated_at else None, updated_by=updated_by)
    if raw.get("api_key_enc"):
        k = decrypt(raw["api_key_enc"])
        if k:
            s.api_key, s.source = k, "dashboard"
        else:
            s.key_unreadable = True
            log.error("Stored AI key can't be decrypted (SECRET_KEY changed?). Falling back to environment.")
    if not s.api_key and config.ANTHROPIC_API_KEY:
        s.api_key, s.source = config.ANTHROPIC_API_KEY, "environment"
    mode = raw.get("mode") or config.AI_MODE or ("claude" if s.api_key else "mock")
    s.mode = "claude" if (mode == "claude" and s.api_key) else "mock"
    s.model = raw.get("model") or config.CLAUDE_MODEL
    s.review_model = raw.get("review_model") or config.CLAUDE_REVIEW_MODEL or s.model
    s.ai_review = s.mode == "claude" and bool(raw.get("ai_review", config.MODERATION_AI_REVIEW))
    s.fingerprint = hashlib.sha256(f"{s.api_key}|{s.mode}".encode()).hexdigest()[:16]
    with _lock:
        _cache[AI_KEY] = (time.monotonic(), s)
    return s


def update_ai(actor_id: int | None, **changes):
    """changes: api_key (str, "" to remove), mode, model, review_model, ai_review."""
    raw, _, _ = _read(AI_KEY)
    if "api_key" in changes:
        k = changes.pop("api_key")
        if k:
            raw["api_key_enc"] = encrypt(k)
        else:
            raw.pop("api_key_enc", None)
    for name, v in changes.items():
        if v is None:
            raw.pop(name, None)
        else:
            raw[name] = v
    _write(AI_KEY, raw, actor_id)


# ------------------------------------------------------------------ status --
# Recorded on every AI call, written to the database only when the state
# changes (or every few minutes), so the hot path stays cheap.
_status_mem: dict = {}
_status_written = 0.0


def record_ai_result(ok: bool, kind: str = "", latency_ms: int | None = None):
    global _status_written
    now_iso = datetime.now(timezone.utc).isoformat()
    prev_state = _status_mem.get("state")
    if ok:
        _status_mem.update(state="ok", last_ok_at=now_iso, last_latency_ms=latency_ms)
        _status_mem.pop("consecutive_errors", None)
    else:
        _status_mem.update(state="error", last_error_at=now_iso, last_error_kind=kind,
                           consecutive_errors=_status_mem.get("consecutive_errors", 0) + 1)
    if prev_state != _status_mem["state"] or time.monotonic() - _status_written > 300:
        try:
            raw, _, _ = _read(AI_STATUS_KEY)
            raw.update(_status_mem)
            _write(AI_STATUS_KEY, raw)
            _status_written = time.monotonic()
        except Exception:                     # never break a student's turn over bookkeeping
            log.exception("Couldn't save AI status")


def ai_status() -> dict:
    """Latest known status. Another process may have seen something newer than
    this one (or the reverse), so keep whichever record has the latest event."""
    stored, _, _ = _read(AI_STATUS_KEY)

    def latest(d):
        return max(d.get("last_ok_at") or "", d.get("last_error_at") or "")
    return dict(_status_mem) if latest(_status_mem) > latest(stored) else stored
