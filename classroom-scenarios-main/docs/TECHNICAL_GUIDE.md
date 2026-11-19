# Technical guide

For whoever maintains, extends or audits the AI Classroom Scenario System, version 2.
`README.md` has the quick start and file map, `DEPLOY.md` covers hosting and every
environment setting, and `docs/REQUIREMENTS_TRACE.md` maps the SRS to the code. This guide
explains how the parts fit together.

* [1. Architecture](#1-architecture)
* [2. Backend modules](#2-backend-modules)
* [3. One student turn](#3-one-student-turn)
* [4. Scenario format](#4-scenario-format)
* [5. Data model](#5-data-model)
* [6. HTTP API](#6-http-api)
* [7. Security and privacy](#7-security-and-privacy)
* [8. Safety and moderation](#8-safety-and-moderation)
* [9. The AI layer](#9-the-ai-layer)
* [10. Frontend](#10-frontend)
* [11. Configuration](#11-configuration)
* [12. Testing](#12-testing)
* [13. Demo data](#13-demo-data)
* [14. Extending the system](#14-extending-the-system)
* [15. Operations](#15-operations)
* [16. Known limits](#16-known-limits)

---

## 1. Architecture

```
 Browser (React SPA)  ──HTTPS/JSON──▶  FastAPI app  ──SQLAlchemy──▶  PostgreSQL (prod) / SQLite (dev)
                                          │
                                          └──Anthropic SDK──▶  Claude (character replies, judge,
                                                                   safety review, debrief)
```

* **One process serves everything.** FastAPI serves the API under `/api/…` and the built
  React app (`frontend/dist`) for every other path. Unknown `/api/…` paths return a JSON
  404; any other unknown path returns `index.html` so the browser router can show the page.
* **Stateless app servers.** Sign-in is a signed, expiring token; rate limits can be shared
  through the database (`RATE_LIMIT_BACKEND=db`), so several processes or servers can run
  side by side.
* **The application, not the AI, controls progression.** Claude writes the characters'
  lines and suggests which instructor-written path a student has taken; the application
  validates that suggestion against the scenario and moves the scene (§3).

## 2. Backend modules

`backend/app/`, in two layers.

**Rules**: plain functions, no database, web or AI imports, tested directly:

| Module | Responsibility |
|---|---|
| `scenario_schema.py` | Scenario format, `normalize` (accepts older formats), `validate` (errors and warnings), `scene_cast`, `fallback_choice` |
| `dialogue.py` | System prompt (`build_system_prompt`), history for the model, judge request and `parse_judgement`, `turn_plan` (when to judge, when a scene is forced to wrap up), `decide`, `parse_reply` (split a multi-character reply into lines), `debrief_prompt` |
| `moderation.py` | `screen_input` / `screen_output` keyword screening; support message; optional `BLOCKLIST_FILE` |
| `exports.py` | CSV (with formula-injection protection and a BOM for Excel) and PDF (ReportLab) |

**Parts that use the database or the AI:**

| Module | Responsibility |
|---|---|
| `engine.py` | One student turn (`take_turn`), moving scenes (`advance`), ending an attempt that is out of messages (`wrap_up`, `close_unfinished`), the debrief, background review, one-turn-at-a-time lock |
| `safety.py` | Adding flags, counting flags towards the pause limit (`reaches_pause`), pausing and resuming |
| `transcripts.py` | Reading a session back out: player state, instructor/admin views, export records |
| `ai.py` | The only module that calls Claude (`ClaudeEngine`), and the demo engine (`MockEngine`) |
| `settings_store.py` | Dashboard-set AI key, model and mode (key encrypted), AI health record |
| `access.py` | Who may see what: one place to audit visibility rules |
| `security.py` | Password hashing, tokens, `current_user`, `require(...)` role checks, rate limits |
| `errors.py` | Turns every failure into a clear message; unexpected errors get a reference that matches the log |
| `database.py` | Engine and sessions; each request rolls back if it fails |
| `models.py` | Tables (§5) and `audit()` |
| `config.py` | Every setting, from environment variables (§11) |
| `main.py` | App setup, security headers, HTTPS redirect, first admin, optional demo data, health check, serving the frontend |
| `routers/` | `auth`, `play` (student), `teacher`, `admin`, `system` (AI connection). Thin: check access, call a module, return |

Also in `backend/`: `seed.py` (first admin, or the demo school), `demo_content.py` (demo
scenarios and scripted conversations), `tests/`.

## 3. One student turn

`POST /api/sessions/{id}/turn` → `routers/play.student_turn` checks the session is the
user's, in progress, not paused, not at an ending and not out of messages, then calls
`engine.take_turn` inside `engine.one_turn_at_a_time(id)` (a second concurrent message for
the same session is refused).

`engine.take_turn`:

1. **Screen the input** (`moderation.screen_input`).
   * Self-harm language: store the message out of AI context, show the support message,
     flag it, and stop. No AI call.
   * A flagged message that brings the session to `AUTO_PAUSE_AFTER_FLAGS`: record it and
     pause (`_pause_now`). No reply.
2. **Plan the turn** (`dialogue.turn_plan`): count messages in this scene and overall; decide
   whether the judge's answer can be used yet (`min_turns`) and whether the scene is forced
   to wrap up (`wrap_after`, or the scenario's last message).
3. **Call the AI in parallel**: the character reply (`eng.reply`, given the system prompt,
   the last `HISTORY_TURNS` exchanges and the cast) and the judge (`_judge`, given the
   scene's conversation). The judge runs on every message because it also detects baiting.
   * If the reply fails, nothing is saved and the student gets a 503 saying progress is
     saved; they resend.
   * A failed judge returns `None`; the turn continues without a scene change.
4. **Re-check the session** after the AI calls (it may have been paused, restarted or
   answered elsewhere in the meantime). If it changed, return 409 and save nothing.
5. **Baiting from the judge**: if this pushes the session to the limit, pause instead of
   showing the reply.
6. **Screen the output** (`moderation.screen_output`) and parse it into speaker lines
   (`dialogue.parse_reply`). A blocked or empty reply is replaced with a neutral line and
   the original is flagged for review.
7. **Save** the student's message and each character line (tokens, latency).
8. **Decide** (`dialogue.decide` with `JUDGE_CONFIDENCE`): take the judged path, or when
   forced, the judged path if clearly shown, otherwise the scene's fallback.
   **`engine.advance`** then records the `Decision`, adds the system lines (decision label,
   judge reasoning for instructors, feedback), moves `session.node`, and if the target is an
   ending, completes the session and asks for the debrief.
9. **Out of messages**: `engine.wrap_up` judges each remaining scene on the whole
   conversation and advances until an ending; if a scene has no way out,
   `close_unfinished` ends the attempt with a clear outcome.
10. Return the session state; optionally queue `background_review` (a second-opinion safety
    review by Claude, `MODERATION_AI_REVIEW`) to run after the response is sent.

`POST /api/sessions/{id}/finish` runs `wrap_up` for a session that has used every message.

**Snapshots.** `PlaySession.snapshot` stores the scenario definition at start. Every step
above reads the snapshot, so editing a live scenario never breaks an attempt in progress.

## 4. Scenario format

Stored as JSON in `scenarios.definition`; the full annotated example is the docstring at the
top of `scenario_schema.py`. In short:

```json
{
  "setting": "…", "objectives": ["…"], "boundaries": ["…"], "feedback_guidance": "…",
  "characters": [{"id": "carol", "name": "Carol", "role": "the bank's president", "traits": "…"}],
  "start": "briefing",
  "nodes": {
    "briefing": {
      "title": "The question", "prompt": "What's happening…",
      "characters": ["carol"], "min_turns": 2, "wrap_after": 4, "fallback": "",
      "choices": [{"label": "Explained the interest-rate risk", "signal": "What the student says…",
                   "next": "sound", "feedback": ""}],
      "ending": null
    },
    "sound": {"title": "Sound advice", "prompt": "…", "characters": ["carol"], "choices": [],
              "ending": {"label": "Sound recommendation", "type": "success", "feedback": "…"}}
  }
}
```

Limits: up to 80 scenes, 8 paths per scene, 4 characters per scene. Ending types are
`success`, `partial`, `fail`. `wrap_after` defaults to 8 (0 = no per-scene limit). An empty
`fallback` means "the path that can lead to the worst ending" (`fallback_choice`).
`normalize` converts older formats (single `character`, dict-shaped choices, string
endings). `validate` returns `{"errors": [...], "warnings": [...]}`, each with a `field` path
the builder uses to jump to the problem; publishing is refused while there are errors.

## 5. Data model

| Table | Key columns | Notes |
|---|---|---|
| `users` | email (unique), name, role, password_hash, active, must_change_password, token_version | Roles: `student`, `teacher`, `admin`, `it_support`. Bumping `token_version` invalidates existing tokens |
| `classes` | name, teacher_id | A course |
| `enrollments` | class_id, student_id | |
| `scenarios` | owner_id, title, definition (JSON), status, max_turns | Status `draft` / `published` / `archived` |
| `assignments` | scenario_id, class_id, due_at | |
| `sessions` | scenario_id, student_id, node, status, outcome, outcome_type, feedback, turns, attempt, is_preview, ai_paused, snapshot (JSON) | One attempt. Preview sessions are excluded from results and the safety queue |
| `messages` | session_id, role (`user`/`assistant`/`system`), content, node, speaker, in_context, hidden, tokens, latency_ms | `in_context=False` keeps a line out of the AI history; system lines carry speakers such as `Decision`, `Inference`, `Feedback`, `Support` |
| `decisions` | session_id, node, choice, next_node | Each path taken |
| `flags` | session_id, message_id, student_id, source, category, severity, reason, excerpt, status, review_note, reviewer_id | Safety queue |
| `audit_log` | actor_id, action, target, detail (JSON) | |
| `system_settings` | key, value (JSON) | Dashboard AI settings; the key is stored encrypted |
| `rate_hits` | key, at | Shared rate limits when `RATE_LIMIT_BACKEND=db` |

Tables are created on start (`database.init_db`). There is no migration tool yet; version 2
changed no tables, so it runs on a version 1 database unchanged.

## 6. HTTP API

All endpoints are JSON under `/api`. Send `Authorization: Bearer <token>` (from
`/api/auth/login`). Errors return `{"detail": "…"}` with a plain-language message. In
development the interactive docs are at `/api/docs`; production hides them.

**Auth** (`routers/auth.py`)

| Method & path | Who | Purpose |
|---|---|---|
| `POST /api/auth/login` | anyone | Email + password → token, expiry, user. Rate-limited |
| `GET /api/auth/me` | signed in | Current user |
| `POST /api/auth/refresh` | signed in | New token (sliding session) |
| `POST /api/auth/password` | signed in | Change password |

**Playing** (`routers/play.py`)

| Method & path | Who | Purpose |
|---|---|---|
| `GET /api/student/assignments` | student | Assigned scenarios with status |
| `POST /api/sessions` | signed in | Start or resume (`restart`, `preview` for staff) |
| `GET /api/sessions/{id}` | owner or staff with access | Session state |
| `POST /api/sessions/{id}/turn` | owner | Send a message (§3). Rate-limited |
| `POST /api/sessions/{id}/finish` | owner | Wrap up a session that is out of messages |
| `POST /api/sessions/{id}/report` | participant or instructor | Report content |
| `GET /api/sessions/{id}/export.csv` / `.pdf` | teacher, admin | Export one conversation |

**Teaching** (`routers/teacher.py`, teacher or admin; teachers only their own)

| Method & path | Purpose |
|---|---|
| `GET /api/scenarios`, `POST /api/scenarios` | List; create (`template`: `blank` or `example`) |
| `GET/PUT/DELETE /api/scenarios/{id}` | Read, save, delete |
| `POST /api/scenarios/validate` | Validate a draft without saving |
| `POST /api/scenarios/{id}/publish` · `/unpublish` · `/archive` · `/restore` · `/duplicate` | Lifecycle |
| `POST /api/scenarios/{id}/assignments`, `DELETE …/assignments/{class_id}` | Assign to / remove from a course |
| `GET /api/scenarios/{id}/analytics` | Results |
| `GET /api/scenarios/{id}/export.csv` | Results export |
| `GET /api/scenarios/{id}/conversations.csv` / `.pdf` | All conversations for a scenario |
| `GET/POST /api/classes`, `PATCH/DELETE /api/classes/{id}` | Courses |
| `POST /api/classes/{id}/students`, `DELETE …/students/{student_id}` | Enrol by email / remove |
| `GET /api/teacher/overview` | Recent activity |
| `GET /api/students/{id}/sessions` | A student's attempts (teachers: only at their scenarios) |

**Administration** (`routers/admin.py`, admin unless noted)

| Method & path | Purpose |
|---|---|
| `GET/POST /api/admin/users`, `PATCH/DELETE /api/admin/users/{id}` | Accounts |
| `POST /api/admin/users/import` | Bulk create, optionally into a course |
| `POST /api/admin/users/bulk` | Role / enable / disable many |
| `POST /api/admin/users/{id}/reset-password` | Temporary password |
| `DELETE /api/admin/users/{id}/data` | Delete a student's conversations and results |
| `POST /api/admin/retention/purge` | Delete sessions older than N days (30–3650) |
| `GET /api/admin/flags`, `GET /api/admin/flags/{id}`, `POST …/{id}/review` | Safety queue |
| `POST /api/admin/sessions/{id}/pause` | Pause or resume |
| `POST /api/admin/messages/{id}/hide` | Hide a message |
| `GET /api/admin/sessions`, `…/export.csv`, `…/export.pdf` | Conversations list and export |
| `GET /api/admin/audit`, `GET /api/admin/stats` | Audit log, system status (admin **and IT support**) |

**AI connection** (`routers/system.py`)

| Method & path | Who | Purpose |
|---|---|---|
| `GET /api/admin/ai` | admin, IT support | State, model, mode, last error |
| `POST /api/admin/ai/test` | admin, IT support | One-word test request |
| `PUT /api/admin/ai/key`, `DELETE /api/admin/ai/key` | admin | Test-then-save / remove the dashboard key |
| `PATCH /api/admin/ai` | admin | Model, mode, background review |

**Public:** `GET /api/health` (database reachable or not; says nothing about configuration).

> Version 2 removed `GET /api/auth/demo`, which listed demo accounts and the default demo
> password to anyone. It now returns 404 like any unknown path.

## 7. Security and privacy

* **Passwords**: PBKDF2-SHA256, 600,000 iterations. Minimum length `PASSWORD_MIN_LENGTH`.
  Temporary passwords force a change at next sign-in.
* **Tokens**: signed with `SECRET_KEY`, expire after `SESSION_TIMEOUT_MINUTES` of
  inactivity; the UI refreshes them while the user is active. Disabling an account or
  changing a password bumps `token_version`, so old tokens stop working at once.
* **Roles**: every route declares its roles (`require(...)`); visibility rules that depend
  on ownership (an instructor's own scenarios and courses) live in `access.py`.
* **Rate limits**: sign-in 8 per 5 minutes per email and IP; AI turns 10 per minute per
  user.
* **Transport**: `APP_ENV=production` refuses to start without a strong `SECRET_KEY`,
  redirects HTTP to HTTPS and sends HSTS and security headers.
* **The Claude key**: server-side only. Set from the dashboard, it is tested, encrypted with
  a key derived from `SECRET_KEY`, and shown only as a hint. Changing `SECRET_KEY` makes a
  dashboard-saved key unreadable (re-enter it).
* **Data minimisation**: Claude receives scenario text and conversation, never names or
  emails. Logs never contain message text.
* **Audit**: administrative actions, safety reviews, exports, data deletion and AI settings
  changes are written to `audit_log`.
* **Exports**: spreadsheet cells that begin with `=`, `+`, `-` or `@` are neutralised so they
  can't run as formulas.

## 8. Safety and moderation

Layers, in order of a turn:

1. **Keyword screening of input** (`moderation.screen_input`). Self-harm stops the AI call
   and shows support resources. Other categories (abuse, baiting…) are flagged and the
   student is still answered in character.
2. **Judge misuse check**: the judge call also reports whether the latest message is
   baiting.
3. **Output screening** (`screen_output`): replies that break character or are
   inappropriate are replaced, and the original goes to the queue.
4. **Background AI review** (`MODERATION_AI_REVIEW`): Claude re-reads the exchange after the
   response is sent.
5. **Reports** from students and instructors.

**Auto-pause**: when `AUTO_PAUSE_AFTER_FLAGS` of a student's messages in one session are
flagged (excluding self-harm), the session pauses and a high-severity "Repeated misuse"
flag is raised. Resuming resets the count. Separately, `ESCALATE_AFTER_FLAGS` (default 3)
raises one high-severity "Repeated misuse" flag for a session that reaches that many
flags, if none is open and it isn't already paused.

Add institution-specific patterns with `BLOCKLIST_FILE` (one regular expression per line).

## 9. The AI layer

`ai.engine()` returns `ClaudeEngine` when a key is available (dashboard key first, then
`ANTHROPIC_API_KEY`) and the mode isn't `mock`; otherwise `MockEngine`, which gives generic
replies and a word-matching judge so every screen can be exercised without a key.

Calls: character **reply**, **judge**, **debrief** at an ending, background **review**.
`CLAUDE_MODEL` (default `claude-haiku-5-5`) for dialogue; `CLAUDE_REVIEW_MODEL` for review
and debrief (blank = same). The SDK retries rate limits and server errors
(`AI_MAX_RETRIES`); a single request gives up after `AI_TIMEOUT_SECONDS`. Every call records
success or the kind of failure for the AI connection page. Replies slower than
`SLOW_AI_SECONDS` are flagged to the student as slow.

## 10. Frontend

React with Vite; no UI or router libraries. (`package.json` asks for React 18; the
prebuilt `dist` was bundled with React 19.2, which runs the same code.)

| File | Purpose |
|---|---|
| `src/main.jsx` | Entry; self-hosted fonts |
| `src/App.jsx` | Role-based navigation (`NAV`) and routes (`ROUTES`), user menu, layout |
| `src/lib.jsx` | API client (token, retries for safe GETs), auth context, router with normal URLs, toasts, `useApi`/`useBusy`/`useDebounced` |
| `src/ui.jsx` | Shared components: fields, dialogs with focus trap, export menu, error boundary, icons |
| `src/graph.js` | Scenario routes and story order (plain functions) |
| `src/pages/Common.jsx` | Sign-in, change password, help, student home |
| `src/pages/Play.jsx` | The player (students and previews) |
| `src/pages/teacher/` | Overview, scenario manager, results, courses (`Teacher.jsx`), builder (`Editor.jsx`) |
| `src/pages/admin/` | Overview, users, safety review, conversations, audit, system status (`Admin.jsx`), AI connection |
| `src/components/` | Conversation transcript (`Script.jsx`) and scenario map (`FlowMap.jsx`) |

`npm run dev` serves on :5173 and proxies `/api` to :8000. `npm run build` writes
`frontend/dist`, which the backend serves. A prebuilt `dist` is included so the backend
runs without Node; it uses the system font, while `npm run build` and the Docker image bundle
Public Sans and Source Serif 4. **Rebuild `dist` after any frontend change.**

## 11. Configuration

Everything is an environment variable read in `config.py`; the full table with defaults is
in `DEPLOY.md` ("Settings reference"). The ones that matter most:

| Setting | Why it matters |
|---|---|
| `APP_ENV=production` | Turns on the production safeguards |
| `SECRET_KEY` | Signs tokens and encrypts the dashboard key. Keep it stable |
| `DATABASE_URL` | PostgreSQL in production |
| `ANTHROPIC_API_KEY` / `AI_MODE` / `CLAUDE_MODEL` | AI engine (also settable from the dashboard) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | First administrator |
| `JUDGE_CONFIDENCE`, `AUTO_PAUSE_AFTER_FLAGS` | Progression and safety tuning |
| `LOAD_DEMO_DATA`, `DEMO_PASSWORD` | Demo school; not for real use |

## 12. Testing

```bash
cd backend
pytest -q                                            # all 54 tests
pytest -q tests/test_logic.py tests/test_exports.py  # rules and exports only: no FastAPI or database needed
```

* `test_logic.py`: validation, prompts, judgement parsing, turn planning, fallback choice,
  reply parsing, the demo scenarios and their scripts.
* `test_exports.py`: CSV and PDF output, formula neutralisation.
* `test_api.py`: end to end against an in-memory demo school with the mock AI engine, so no
  API key is needed: roles and access, play, pausing and resuming, exports, archive and
  restore, and that `/api/auth/demo` no longer exists.

## 13. Demo data

`python seed.py --demo` (or `LOAD_DEMO_DATA=true`) loads a demo university once: accounts
for every role, three courses, three published scenarios and a draft, and scripted
conversations in deliberately different states. `docs/DEMO_GUIDE.md` lists them. The demo
accounts are **not** shown on the sign-in page; share them with the people you are showing
the site to. Disable them (or use a separate site) before real students use it.

## 14. Extending the system

| To change… | Do this |
|---|---|
| A rule about scenes, prompts or progression | Edit `dialogue.py` or `scenario_schema.py`; add a test in `tests/test_logic.py` |
| What happens in a turn | `engine.take_turn` / `advance` / `wrap_up`; keep the rules in `dialogue.py` |
| Safety patterns | `moderation.py`, or `BLOCKLIST_FILE` for local additions |
| An export format | `exports.py` plus a route that checks access and calls it |
| Who can see what | `access.py` and the route's `require(...)` |
| A new screen | A page in `frontend/src/pages/`, an entry in `NAV`/`ROUTES` in `App.jsx`, and a thin endpoint in `routers/` |
| A database column | Introduce Alembic first (there are no migrations yet), then add the column |

## 15. Operations

* **Health**: `GET /api/health` for uptime monitors.
* **Logs**: errors carry a reference shown to the user; search the log for it. Message text
  is never logged.
* **Backups**: nightly `pg_dump` in the Docker setup (kept 14 days), or the host's managed
  backups on Render. Restore steps are in `DEPLOY.md`.
* **AI problems**: Admin → AI connection shows the last error type; IT support can run a
  test.
* **Locked-out administrator**: `ADMIN_RESET_PASSWORD=true` with `ADMIN_EMAIL` /
  `ADMIN_PASSWORD`, restart, sign in, then remove the setting.
* **Retention**: Admin → Users and roles → retention purge, or per-student data deletion.

## 16. Known limits

See "Known gaps / next steps" in `README.md`: no LMS/LTI integration yet, English only,
replies are not streamed, no migration tool, per-process turn locking, and a formal WCAG
audit and FERPA review are still to do.
