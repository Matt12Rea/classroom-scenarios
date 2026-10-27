"""Application entry point.

    uvicorn app.main:app --reload                       (development, from backend/)
    uvicorn app.main:app --host 0.0.0.0 --proxy-headers (production, behind HTTPS proxy)

One process serves both the API (/api/...) and the website (everything else),
so the site and its API share one address and one HTTPS certificate.
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, text

from . import config
from .database import SessionLocal, init_db
from .routers import admin, auth, play, system, teacher

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aicss")

app = FastAPI(title="AI Classroom Scenario System", version="1.0.0",
              # The interactive API docs are handy in development but needn't be public.
              docs_url=None if config.IS_PROD else "/api/docs", redoc_url=None,
              openapi_url=None if config.IS_PROD else "/api/openapi.json")
if config.CORS_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["Authorization", "Content-Type"])

for r in (auth.router, play.router, teacher.router, admin.router, system.router):
    app.include_router(r)

# Content Security Policy: everything (scripts, styles, fonts) is served from this
# site. No third-party scripts, trackers or font services see student traffic.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")


@app.middleware("http")
async def https_and_headers(request: Request, call_next):
    # SRS 2.4 / 4.4 / NFR-5.3.3: all traffic over HTTPS. The reverse proxy terminates
    # TLS and reports the original scheme; plain-HTTP visitors are redirected.
    if config.FORCE_HTTPS and request.url.scheme == "http" and request.url.path != "/api/health":
        return RedirectResponse(str(request.url.replace(scheme="https")), status_code=308)
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), interest-cohort=()")
    h.setdefault("Content-Security-Policy", CSP)
    if config.FORCE_HTTPS:
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")      # never cache student data
    return response


def bootstrap_admin():
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD when the
    database has none, so a hosted site can be set up without shell access.

    ADMIN_PASSWORD is only a temporary password: the admin must choose a new one
    (which does have to meet the password rules) at first sign-in.

    Locked out? Set ADMIN_RESET_PASSWORD=true and restart: the ADMIN_EMAIL account's
    password is reset to ADMIN_PASSWORD (again temporary). Then remove the setting."""
    if not config.ADMIN_EMAIL:
        return
    from .models import User, audit
    from .security import hash_password, temp_password
    db = SessionLocal()
    try:
        existing = db.scalar(select(User).where(User.email == config.ADMIN_EMAIL))
        any_admin = db.scalar(select(User.id).where(User.role == "admin").limit(1))
        reset = config.ADMIN_RESET_PASSWORD
        if any_admin and not reset:
            return
        pw = config.ADMIN_PASSWORD or temp_password()
        if existing:
            existing.role, existing.active = "admin", True
            existing.password_hash, existing.must_change_password = hash_password(pw), True
            existing.token_version += 1
            audit(db, None, "admin.bootstrap_reset", f"user:{existing.id}", email=config.ADMIN_EMAIL)
            action = "Reset the password for administrator"
        else:
            u = User(name="Administrator", email=config.ADMIN_EMAIL, role="admin",
                     password_hash=hash_password(pw), must_change_password=True)
            db.add(u)
            db.flush()
            audit(db, None, "admin.bootstrap_create", f"user:{u.id}", email=config.ADMIN_EMAIL)
            action = "Created first administrator"
        db.commit()
        log.warning("%s %s. %s", action, config.ADMIN_EMAIL,
                    "Sign in with ADMIN_PASSWORD; you'll be asked to choose a new password."
                    if config.ADMIN_PASSWORD else f"Temporary password: {pw}")
        if reset:
            log.warning("ADMIN_RESET_PASSWORD is on. Remove it now, or the password is reset "
                        "again every time the site restarts.")
    finally:
        db.close()


def load_demo_data():
    """LOAD_DEMO_DATA=true: add the demo school once (accounts for every role, classes,
    scenarios and sample activity). Does nothing if it's already there."""
    if not config.LOAD_DEMO_DATA:
        return
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import seed
    from .models import User
    db = SessionLocal()
    try:
        if db.scalar(select(User.id).where(User.email == "admin@demo.school")):
            return
        seed.demo(db)
        log.warning("Loaded the demo school. Demo accounts: admin@demo.school, teacher@demo.school, "
                    "student@demo.school, it@demo.school (password: DEMO_PASSWORD, or demo-pass-1 if unset).")
    except Exception:
        db.rollback()
        log.exception("Couldn't load the demo school")
    finally:
        db.close()


init_db()
bootstrap_admin()
load_demo_data()


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    # NFR-5.4.11: log enough to diagnose, but never request bodies (student text).
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Something went wrong on the server. Your saved work is safe. "
                                   "Try again, and contact support if it keeps happening."}, status_code=500)


@app.get("/api/health")
def health():
    """For uptime monitors and the hosting platform's health check. Public, so it
    says nothing about configuration."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        ok = True
    except Exception:
        log.exception("Health check: database unreachable")
        ok = False
    finally:
        db.close()
    return JSONResponse({"ok": ok, "database": "ok" if ok else "unreachable"}, status_code=200 if ok else 503)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(path: str):
    return JSONResponse({"detail": "Not found."}, status_code=404)


# Serve the built website (frontend/dist). Pages use normal paths such as
# /scenarios/4, so any path that isn't a file gets index.html and the browser
# app shows the right page.
_dist = os.path.abspath(config.FRONTEND_DIST)
if os.path.isdir(_dist):
    @app.get("/{path:path}", include_in_schema=False)
    def site(path: str):
        f = os.path.abspath(os.path.join(_dist, path))
        if path and f.startswith(_dist + os.sep) and os.path.isfile(f):
            # Built assets have content hashes in their names, so they can be cached forever.
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "public, max-age=3600"
            return FileResponse(f, headers={"Cache-Control": cache})
        return FileResponse(os.path.join(_dist, "index.html"), headers={"Cache-Control": "no-cache"})
else:
    log.warning("No built website at %s. Run `npm run build` in frontend/ (the Docker image does this).", _dist)
