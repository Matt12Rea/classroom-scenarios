# AI Classroom Scenario System

Role-play scenarios for university students, built by instructors, overseen by administrators.
Claude voices the characters. Students move through a scenario by what they say, not by clicking
choices: a separate Claude call judges which of the instructor's paths the student has taken, and the
application makes the move.

```
AICSG/
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
│   ├── seed.py                 first admin account, or a demo university
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
python seed.py --demo                 # demo university; every demo password is demo-pass-1
export ANTHROPIC_API_KEY=sk-ant-...   # leave unset to use canned "demo mode" replies
export SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
uvicorn app.main:app --reload
```

Open http://localhost:8000. The backend serves `frontend/dist`, so this alone gives you the whole app.
(The prebuilt `dist` uses your computer's system font; `npm run build` and the Docker image bundle the
Public Sans and Source Serif 4 fonts.)

Demo accounts: `admin@demo.school`, `teacher@demo.school` (an instructor), `student@demo.school`, `it@demo.school`.
The demo includes three published, course-based scenarios (ECON 210: advising a community bank on interest-rate
risk; PSYC 310: defending a deception study to the IRB; BIOL 340: explaining a cystic fibrosis carrier result)
and a draft (HIST: the 1787 representation deadlock).
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
  (or with `python seed.py --admin you@university.edu`).
* The Claude key can be set as `ANTHROPIC_API_KEY` or added later in **Admin → AI connection**,
  where it's tested, stored encrypted, and can be replaced without a redeploy.

## Pipeline

**Student flow (UC-02/03/04).** `POST /api/sessions` starts the scenario, or resumes it if one is already in progress, so progress is never lost. Each message goes through these steps:

1. The message is screened (`moderation.screen_input`). Self-harm language stops the AI call, shows support resources and raises a serious flag. Baiting attempts are flagged but still answered in character.
2. Claude replies, given the scenario's static rules plus the current scene, how the student's approach has moved the scenario so far, and the last 10 exchanges.
   At the same time (once the scene's minimum number of messages is met), a second Claude call, the *judge*, reads the scene's conversation and returns which of the scene's paths, if any, the student has clearly taken, with a confidence and a one-line reason (`ai.judge_request`, `ai.parse_judgement`).
3. The reply is screened (`screen_output`). A reply that breaks character or is inappropriate is replaced with a neutral line, and the original goes to the admin queue.
4. Optionally, Claude re-reviews the exchange in the background (`MODERATION_AI_REVIEW`). This adds no delay for the student.

**Scene progression.** There are no decision buttons. Each path in a scene has a name (shown to the student when it's taken, e.g.
"Explained the bank's interest-rate risk") and a *signal*: what the student says or does to take it. The judge can only pick from those paths;
the application checks the pick, records it in `decisions`, and moves the student on. A scene moves on when:

* the judge picks a path with confidence ≥ `JUDGE_CONFIDENCE` (default 0.6) after the scene's `min_turns`, or
* the scene reaches its `wrap_after` limit (default 8 messages; "Messages per scene" under Basics sets every scene
  at once; the demo uses 4), or
* the student uses the scenario's last message, when every remaining scene is wrapped up the same way until an ending.

At a wrap-up, a path is taken only if the student clearly showed it. Otherwise the scene's *fallback* path is
taken: the one the instructor picked, or by default the path that can lead to the worst ending
(`scenario_schema.fallback_choice`). One-word answers, refusing to engage and baiting therefore never earn a good
ending, and the student is told the scene moved on without them.

**Repeated baiting.** When `AUTO_PAUSE_AFTER_FLAGS` (default 3) of a student's messages in one session have been
flagged, the session pauses: no AI reply, no restart, and a high-priority "Repeated misuse" flag for administrators,
who can resume it from the conversation view.

Students never see the paths or the judge's reasoning. Instructors see both: in Preview (an "Instructor view" panel under the
message box) and in students' transcripts ("Why the scene moved on"). In demo mode (no API key) the judge matches words
between the student's messages and each path, so you can still click through every screen.
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



## Known gaps / next steps

* **LMS / LTI integration (UC-07)**: not started. `Assignment` and `PlaySession` already hold the course, assignment and completion data an LTI grade passback would need.
* **Internationalisation (ES/FR)**: the UI strings are plain English in the components. Pull them into a dictionary when you add languages.
* **Streaming replies**: responses arrive whole. Switching `ai.ClaudeEngine.reply` to `messages.stream` and the endpoint to SSE would make long replies feel faster.
* **PDF export**: CSV only for now.
* Prompt caching is turned on, but the system prompt is shorter than Claude's minimum cacheable length, so it won't save anything until prompts grow.
* The keyword patterns in `moderation.py` are a starting point. Add institution-specific ones with `BLOCKLIST_FILE` (one regex per line), and keep `MODERATION_AI_REVIEW` on in production.
