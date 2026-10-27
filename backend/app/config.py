"""Central configuration. Every value can be overridden with an environment
variable (or a .env file loaded by your process manager)."""
import logging
import os
import secrets
import sys

log = logging.getLogger("aicss")

# "production" turns on the safety checks below (required SECRET_KEY, HTTPS
# redirect, HSTS). Anything else is treated as development.
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PROD = APP_ENV == "production"


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# ---- database -------------------------------------------------------------
# SQLite for development. For production point this at PostgreSQL, e.g.
#   postgresql+psycopg://user:pass@localhost/aicss
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./classroom.db")
# Hosting providers (Render, Railway, Heroku…) hand out "postgres://" URLs.
# SQLAlchemy needs the driver named explicitly.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

# ---- auth -----------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY") or ""
if IS_PROD and len(SECRET_KEY) < 32:
    sys.exit("SECRET_KEY must be set to a random value of at least 32 characters when APP_ENV=production. "
             "Generate one with: python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_urlsafe(48)
    log.warning("SECRET_KEY not set: using a random key. Everyone is logged out on restart.")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))   # NFR-5.3.5
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))
LOGIN_RATE_LIMIT = (8, 300)          # 8 attempts per 5 minutes per email+IP

# ---- first administrator ----------------------------------------------------
# On a hosted service with no shell access, set these once. On start-up, if the
# database has no administrator yet, this account is created. ADMIN_PASSWORD is
# temporary: the admin must choose a new one at first sign-in.
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Emergency reset: when true, the ADMIN_EMAIL account's password is set back to
# ADMIN_PASSWORD on every start. Turn it on, restart, sign in, then turn it off.
ADMIN_RESET_PASSWORD = _bool("ADMIN_RESET_PASSWORD", False)

# ---- demo school ------------------------------------------------------------
# LOAD_DEMO_DATA=true adds sample accounts for every role, classes, scenarios and
# activity on start-up (once). For showing the site to people, not for real use.
LOAD_DEMO_DATA = _bool("LOAD_DEMO_DATA", False)
DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "") or "demo-pass-1"

# ---- AI engine ------------------------------------------------------------
# These environment values are the defaults. An administrator can override the
# key, model and mode from Admin > AI connection without redeploying; those
# overrides are stored encrypted in the database (see settings_store.py).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# "claude" uses the real API. "mock" returns canned in-character lines so the app
# can be demoed and tested without an API key (or any cost). Leave unset to use
# Claude whenever a key is available (from the environment or the dashboard).
AI_MODE = os.getenv("AI_MODE", "").strip().lower()
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")        # dialogue
CLAUDE_REVIEW_MODEL = os.getenv("CLAUDE_REVIEW_MODEL", "")           # safety review + debrief ("" = same)
AI_MAX_RETRIES = int(os.getenv("AI_MAX_RETRIES", "2"))               # SDK retries 429/5xx with backoff
# Models offered in the admin dropdown. Any model id can still be typed in.
CLAUDE_MODELS = [m.strip() for m in os.getenv(
    "CLAUDE_MODELS", "claude-haiku-5-5,claude-sonnet-5-5,claude-opus-5-5").split(",") if m.strip()]
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "300"))
AI_TIMEOUT_SECONDS = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))
SLOW_AI_SECONDS = float(os.getenv("SLOW_AI_SECONDS", "2"))            # NFR-5.1.6
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "10"))
MAX_INPUT_CHARS = int(os.getenv("MAX_INPUT_CHARS", "1500"))
TURN_RATE_LIMIT = (10, 60)           # 10 AI turns per minute per user

# Second-opinion safety review of each exchange by Claude, run in the background
# after the reply is sent, so it adds no latency for the student.
MODERATION_AI_REVIEW = _bool("MODERATION_AI_REVIEW", True)
# Number of auto-flags in one session before the session is escalated to "high".
ESCALATE_AFTER_FLAGS = int(os.getenv("ESCALATE_AFTER_FLAGS", "3"))

# ---- web ------------------------------------------------------------------
# The public address of the site, e.g. https://scenarios.yourschool.edu
PUBLIC_URL = os.getenv("PUBLIC_URL", "").rstrip("/")
# The site and its API are served from the same address, so cross-origin access
# is only needed for the Vite dev server.
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "" if IS_PROD else "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
# Redirect plain-HTTP requests to HTTPS and send HSTS (SRS 2.4, 4.4, NFR-5.3.3).
# Relies on the reverse proxy's X-Forwarded-Proto header (uvicorn --proxy-headers).
FORCE_HTTPS = _bool("FORCE_HTTPS", IS_PROD)
# "memory" is fine for one process. "db" shares limits across several workers or servers.
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "db" if IS_PROD else "memory")
FRONTEND_DIST = os.getenv("FRONTEND_DIST", os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist"))
