# AI Classroom Scenario System

Role-play scenarios for students, built by teachers, overseen by administrators.
Claude voices the characters. The application decides how a scenario progresses and ends.

```
aicss/
├── backend/            FastAPI + SQLAlchemy (SQLite in dev, PostgreSQL-ready)
│   ├── app/
│   │   ├── main.py             app setup, error handling, serves the built frontend
│   │   ├── config.py           every setting, all overridable by environment variables
│   │   ├── database.py         DB connection (change DATABASE_URL to switch databases)
│   │   ├── models.py           tables: users, classes, enrollments, scenarios, assignments,
│   │   │                       sessions, messages, decisions, flags, audit_log
│   │   ├── security.py         password hashing, login tokens, role checks, rate limits
│   │   ├── access.py           who may see what (one place to audit)
│   │   ├── scenario_schema.py  scenario format, validation (dead ends, unreachable scenes…)
│   │   ├── moderation.py       safety screening of student input and AI output
│   │   ├── ai.py               the only module that talks to Claude (+ demo/mock engine)
│   │   ├── settings_store.py   AI key/model set from the dashboard (encrypted), AI health
│   │   └── routers/            auth, play (student), teacher, admin, system (AI connection)
│   ├── seed.py                 first admin account, or a demo school
│   └── tests/test_api.py       end-to-end tests (no API key needed)
├── frontend/           React (Vite). No UI libraries, no router dependency.
│   ├── src/App.jsx             role-based navigation and routes
│   ├── src/lib.jsx             API client, auth, router (normal URLs), toasts
│   ├── src/styles.css          design tokens and components
│   ├── src/pages/Play.jsx      the student player
│   ├── src/pages/teacher/      scenario builder, results, classes
│   ├── src/pages/admin/        users, safety review, conversations, audit, AI connection
│   └── dist/                   a prebuilt copy so you can run without Node
├── Dockerfile          builds the site and server into one image
├── docker-compose.yml  production on your own server: app + PostgreSQL + backups + HTTPS (Caddy)
├── render.yaml         one-click hosting on Render
├── DEPLOY.md           step-by-step guide to putting the site online
└── docs/REQUIREMENTS_TRACE.md   every SRS requirement and where it's met
```

**To put the site online, follow [DEPLOY.md](DEPLOY.md).** The sections below are for
running it on your own computer while developing.

## Run it (development)

**Backend** (Python 3.10+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python seed.py --demo                 # demo school; every demo password is demo-pass-1
export ANTHROPIC_API_KEY=sk-ant-...   # leave unset to use canned "demo mode" replies
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
uvicorn app.main:app --reload
```

Open http://localhost:8000. The backend serves `frontend/dist`, so this alone gives you the whole app.
(The prebuilt `dist` uses your computer's system font; `npm run build` and the Docker image bundle the
Public Sans and Source Serif 4 fonts.)

Demo accounts: `admin@demo.school`, `teacher@demo.school`, `student@demo.school`, `it@demo.school`.
Each uses the password `demo-pass-1`.

**Frontend, when you're changing it** (Node 18+):

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173, hot reload; /api is proxied to :8000
npm run build      # refreshes frontend/dist for the backend to serve
```

**Tests:** `cd backend && pytest -q`

## Going to production

See **[DEPLOY.md](DEPLOY.md)**. In short:

* `docker compose up -d --build` on an Ubuntu server gives you the app, PostgreSQL, nightly
  backups and automatic HTTPS for your domain; or deploy `render.yaml` on Render.
* `APP_ENV=production` refuses to start without a strong `SECRET_KEY`, redirects HTTP to HTTPS,
  sends HSTS and security headers, and hides the API docs.
* The first administrator is created from `ADMIN_EMAIL` / `ADMIN_PASSWORD` on first start
  (or with `python seed.py --admin you@school.edu`).
* The Claude key can be set as `ANTHROPIC_API_KEY` or added later in **Admin → AI connection**,
  where it's tested, stored encrypted, and can be replaced without a redeploy.

## How the pieces fit

**Student flow (UC-02/03/04).** `POST /api/sessions` starts the scenario, or resumes it if one is already in progress, so progress is never lost. Each message goes through these steps:

1. The message is screened (`moderation.screen_input`). Self-harm language stops the AI call, shows support resources and raises a serious flag. Baiting attempts are flagged but still answered in character.
2. Claude replies, given the scenario's static rules plus the current scene, the decisions made so far and the last 10 exchanges.
3. The reply is screened (`screen_output`). A reply that breaks character or is inappropriate is replaced with a neutral line, and the original goes to the admin queue.
4. Optionally, Claude re-reviews the exchange in the background (`MODERATION_AI_REVIEW`). This adds no delay for the student.

Decisions are plain application logic. Each scene can require N messages before its decisions unlock.
When a student reaches an ending, the teacher's ending feedback is shown alongside a short personalised debrief from Claude, guided by the teacher's notes.

**Scenario snapshot.** A session stores a copy of the scenario as it was when the student started, so a teacher can edit a live scenario without breaking attempts already in progress.

**Roles.**

| | Student | Teacher | Admin | IT support |
|---|---|---|---|---|
| Play assigned scenarios | ✓ | preview only | preview only | |
| Build, publish and assign scenarios | | own | all | |
| Classes | | own | all | |
| Results and conversations | own | their students | all | |
| Users, roles, safety review, data deletion | | | ✓ | |
| AI connection: change key, model, mode | | | ✓ | |
| AI connection: view status, run a test | | | ✓ | ✓ |
| Audit log and system status | | | ✓ | ✓ |

**Privacy.** Claude receives the scenario text and the conversation, never student names or emails. Logs never include message text.
Fonts and scripts are served from the site itself, so no third party sees students' visits.

**The API key.** Only the server uses it. From the dashboard it's write-only: it's tested before it's
saved, encrypted with a key derived from `SECRET_KEY`, and shown afterwards only as `sk-ant-…WXYZ`.
Each AI call records success or the kind of failure (invalid key, out of credit, rate limit, outage),
so administrators see what's wrong without reading server logs.

## What changed from the original `engine.py`

| Original | Now |
|---|---|
| Placeholder auth: any `Bearer admin:1` header was trusted | Real accounts: hashed passwords (PBKDF2, 600k rounds), signed expiring tokens, a database check on every request so disabling a user or changing a password takes effect immediately |
| `sqlite3` connections opened per call and never closed | SQLAlchemy session per request; switching to PostgreSQL is a config change |
| Students could start any scenario by id, including drafts | Only published scenarios assigned to one of their classes |
| Every start created a new session | Resumes the in-progress attempt; "Try again" starts a fresh one |
| Bad scenario JSON caused a `KeyError` (500) | Full validation with field-level messages; publishing blocked until clean |
| Fallback line hard-coded to "Jordan" | Uses whichever character is speaking |
| No moderation (TODO) | Input and output screening, admin queue, escalation after repeated flags |
| One character, no teacher endpoints | Several characters per scenario, scene-level speakers, full authoring API |
| Editing a scenario could break running sessions | Sessions keep a snapshot |
| No CORS, no static serving | Both, plus a JSON error handler that doesn't leak internals |

The original scenario JSON format still loads; `scenario_schema.normalize()` converts it.

## Known gaps / next steps

* **LMS / LTI integration (UC-07)**: not started. `Assignment` and `PlaySession` already hold the course, assignment and completion data an LTI grade passback would need.
* **Internationalisation (ES/FR)**: the UI strings are plain English in the components. Pull them into a dictionary when you add languages.
* **Streaming replies**: responses arrive whole. Switching `ai.ClaudeEngine.reply` to `messages.stream` and the endpoint to SSE would make long replies feel faster.
* **PDF export**: CSV only for now.
* Prompt caching is turned on, but the system prompt is shorter than Claude's minimum cacheable length, so it won't save anything until prompts grow.
* The keyword patterns in `moderation.py` are a starting point. Add institution-specific ones with `BLOCKLIST_FILE` (one regex per line), and keep `MODERATION_AI_REVIEW` on in production.
