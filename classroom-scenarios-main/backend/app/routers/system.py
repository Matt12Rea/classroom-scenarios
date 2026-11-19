"""AI connection settings (Admin > AI connection).

Administrators can add, replace or remove the Claude API key, choose the model
and switch between live and demo mode, all without redeploying. IT support can
see the connection's health and run a test, but can't change anything.
Nobody can read the key back (REQ-3.2.3.10); every change is audited (NFR-5.3.8).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import ai, config, settings_store
from ..database import get_db
from ..models import User, audit
from ..security import require

router = APIRouter(prefix="/api/admin/ai", tags=["admin"])
admin = require("admin")
viewer = require("admin", "it_support")


def _state(db: Session) -> dict:
    s = settings_store.ai_settings()
    st = settings_store.ai_status()
    kind = st.get("last_error_kind") if st.get("state") == "error" else None
    env_hint = settings_store.key_hint(config.ANTHROPIC_API_KEY)
    who = db.get(User, s.updated_by) if s.updated_by else None
    return {
        "mode": s.mode,
        "source": s.source,
        "key_hint": settings_store.key_hint(s.api_key),
        "environment_key_hint": env_hint,
        "key_unreadable": s.key_unreadable,
        "model": s.model,
        "review_model": s.review_model,
        "ai_review": s.ai_review,
        "models": config.CLAUDE_MODELS,
        "updated_at": s.updated_at,
        "updated_by": who.name if who else None,
        "status": {
            "state": "demo" if s.mode == "mock" else (st.get("state") or "unknown"),
            "last_ok_at": st.get("last_ok_at"),
            "last_error_at": st.get("last_error_at"),
            "last_error_kind": st.get("last_error_kind"),
            "consecutive_errors": st.get("consecutive_errors", 0),
            "last_latency_ms": st.get("last_latency_ms"),
            "message": ai.ERROR_HELP.get(kind) if kind else None,
        },
    }


@router.get("")
def get_ai(user: User = Depends(viewer), db: Session = Depends(get_db)):
    return _state(db)


class KeyReq(BaseModel):
    api_key: str = Field(min_length=20, max_length=300)


@router.put("/key")
def set_key(req: KeyReq, user: User = Depends(admin), db: Session = Depends(get_db)):
    """Test a new key, and save it only if Claude accepts it."""
    key = req.api_key.strip()
    if not key.startswith("sk-ant-") or any(c.isspace() for c in key):
        raise HTTPException(422, "That doesn't look like a Claude API key. Keys start with “sk-ant-”. "
                                 "Copy it again from the Anthropic Console.")
    s = settings_store.ai_settings()
    ok, kind, _ = ai.test_key(key, s.model)
    # A key that's valid but temporarily rate-limited or overloaded is still worth saving.
    if not ok and kind in ("auth", "permission", "billing", "model", "bad_request"):
        raise HTTPException(422, f"The key wasn't saved. {ai.ERROR_HELP[kind]}")
    settings_store.update_ai(user.id, api_key=key, mode="claude")
    audit(db, user, "ai.key.set", "ai", hint=settings_store.key_hint(key), verified=ok)
    db.commit()
    if ok:
        settings_store.record_ai_result(True)
    return {**_state(db), "saved": True,
            "warning": None if ok else f"Saved, but the first test didn't succeed: {ai.ERROR_HELP[kind]}"}


@router.delete("/key")
def remove_key(user: User = Depends(admin), db: Session = Depends(get_db)):
    """Remove the dashboard key. The environment key (if any) is used instead."""
    before = settings_store.ai_settings()
    if before.source != "dashboard" and not before.key_unreadable:
        raise HTTPException(409, "There's no key saved from the dashboard. A key set as the "
                                 "ANTHROPIC_API_KEY environment variable can only be changed on the server.")
    settings_store.update_ai(user.id, api_key="")
    audit(db, user, "ai.key.remove", "ai", hint=settings_store.key_hint(before.api_key))
    db.commit()
    return _state(db)


class AIPatch(BaseModel):
    mode: str | None = None              # claude | mock
    model: str | None = Field(default=None, max_length=100)
    review_model: str | None = Field(default=None, max_length=100)
    ai_review: bool | None = None


@router.patch("")
def update_ai(req: AIPatch, user: User = Depends(admin), db: Session = Depends(get_db)):
    changes = req.model_dump(exclude_none=True)
    if not changes:
        return _state(db)
    if "mode" in changes:
        if changes["mode"] not in ("claude", "mock"):
            raise HTTPException(422, "Mode must be “claude” (live) or “mock” (demo replies).")
        if changes["mode"] == "claude" and not settings_store.ai_settings().api_key:
            raise HTTPException(409, "Add an API key before switching to live mode.")
    for f in ("model", "review_model"):
        if f in changes:
            changes[f] = changes[f].strip()
            if changes[f] and not changes[f].replace("-", "").replace(".", "").replace("_", "").isalnum():
                raise HTTPException(422, "Model names contain only letters, numbers and dashes.")
            if not changes[f]:
                changes[f] = None if f == "review_model" else config.CLAUDE_MODEL
    settings_store.update_ai(user.id, **changes)
    audit(db, user, "ai.settings", "ai", **{k: v for k, v in changes.items()})
    db.commit()
    return _state(db)


@router.post("/test")
def test_connection(user: User = Depends(viewer), db: Session = Depends(get_db)):
    """Send a one-word request with the current settings. No student data is sent."""
    s = settings_store.ai_settings()
    if s.mode != "claude":
        return {"ok": True, "demo": True, "message": "Demo mode is on, so no request was sent to Claude."}
    ok, kind, latency = ai.test_key(s.api_key, s.model)
    settings_store.record_ai_result(ok, kind, latency)
    audit(db, user, "ai.test", "ai", ok=ok, kind=kind)
    db.commit()
    return {"ok": ok, "latency_ms": latency, "kind": kind or None,
            "message": f"Claude answered in {latency} ms." if ok else ai.ERROR_HELP.get(kind, ai.ERROR_HELP["unknown"])}
