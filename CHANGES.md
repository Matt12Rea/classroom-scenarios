# Version 2: what changed

## Fixes after review (2.0.1)

No database changes. Rebuilt `frontend/dist` is included.

* **Temporary passwords are now enforced by the server.** The forced password change was only
  enforced by the sign-in screen: an account with a temporary password could call every API
  endpoint directly. Until the password is changed, only `/api/auth/me`, `/api/auth/refresh`
  and `/api/auth/password` work; everything else answers 403.
* **Personal-info matches no longer pause sessions or hold scenes back.** Personal-info flags
  counted as misuse: a student who typed something like "the buyer at 412 Elm Street" (the
  street-address pattern) couldn't move the scene on with that message, and three such
  messages paused the session. These are still flagged for administrators, but they no longer
  count towards a pause.
* **Some confirm dialogs still closed when their action failed** (delete course, remove student,
  delete a student's conversations, remove the saved AI key). Each one caught its own error, so
  the dialog never saw the failure. They now stay open and say why.
* **Results date filter.** The "Started from" date was read as midnight UTC, not local
  midnight, so the start of the range was shifted by the time-zone offset. Both ends now use
  the viewer's time zone.
* **Dialogs.** A dialog no longer moves focus back to its first field when the page behind it
  re-renders. With a dialog opened from another dialog, Escape now closes only the top one.
* **AI status** kept the old "consecutive errors" count in the stored record after the
  connection recovered.
* **Several workers starting at once** (`WEB_CONCURRENCY=2`, the Docker default) could both try
  to create the first administrator, and one would crash at start-up. That case is now handled.
* **`.env.production.example` was missing.** `DEPLOY.md` (Route B) and `docker-compose.yml`
  tell you to copy it. It's now included.

No database tables changed. Version 2 runs on a version 1 database as it is, and attempts that
were in progress under version 1 can be continued.

## Fixed

* **Paused sessions could not be resumed from Safety review.** The server could resume a
  session, but the flag screen had no control for it and the only button was on a page the
  flag did not link to. A paused session can now be resumed from the flag (button, or a tick
  box in the review), the conversation, the site overview, and the Conversations list.
* **A resumed session paused again on the next flag.** Old flags kept counting towards the
  limit. The count now restarts at each resume.
* An attempt that ran out of messages in a scene with no way out stayed "in progress" for
  ever. It now ends with a clear outcome.
* Two messages sent at once for one session (a double click, two tabs) could save out of
  order. The second is refused while the first is being answered.
* Adding the same email twice to a course, or importing accounts into a course that no longer
  exists, returned a server error. Both are handled.
* An unexpected error from the AI library, or a failed judge call, could lose the student's
  turn. Both now fall back safely, and the student can resend.
* A confirm dialog closed even when its action failed. It now stays open and says why.
* A slow early search could overwrite a newer one on screen. Search boxes wait for typing to
  stop, and stale answers are ignored.
* Running a plain `pytest` in `backend/` failed with "No module named 'app'" (only
  `python -m pytest` worked). `backend/pytest.ini` now sets the import path, so both work.
* The two PDF export tests were skipped on a fresh install because `pdfplumber`, which they
  use to read the PDF back, wasn't in `requirements.txt`. It is now.
* An instructor could open a student's conversations from another instructor's course if they
  taught that student elsewhere. Access now follows the scenario and the course.

## New

* **Several characters in one scene.** Tick who is present; the AI decides who answers each
  message, and sometimes two do. Each line is stored and shown under its own speaker.
* **Scenario builder, rebuilt.** Four steps. Paths are written as rules ("If the student…,
  then go to…"), the "if no path is clear" rule is always visible, and the review step lists
  every route from the first scene to each ending, with a labelled map.
* **Scenario manager.** Each scenario shows its stage (still being built, ready to publish,
  published but not assigned, live), its contents and its next actions. Archive can be undone.
* **Export of logged conversations as PDF or CSV**: one conversation, a whole scenario, or an
  administrator's filtered list. Spreadsheet cells can't run as formulas. Every export is in
  the audit log. PDF needs the new `reportlab` requirement.
* **Error handling in one place** (`errors.py`): form problems name the field in plain words,
  database trouble says to retry, anything unexpected gives a reference that matches the log.
  A page that crashes shows a message instead of a blank screen.
* **Demo school rewritten** (see `docs/DEMO_GUIDE.md`).

## Removed

* **The demo account list on the sign-in page** ("This is a demo site with sample data. Sign
  in as any role with one click"). The sign-in page now shows only the normal form. The
  `GET /api/auth/demo` endpoint behind it is gone too: it told anyone who asked which demo
  accounts existed and, with the default password, what the password was, which included the
  demo administrator. Demo accounts still work; type the email and password into the form
  (`docs/DEMO_GUIDE.md` lists them). `config.DEMO_PASSWORD` was only used by that endpoint and
  has been removed; `seed.py` still reads the `DEMO_PASSWORD` environment variable.

## Reworked

The 540-line play router was split so each part can be changed and tested alone:
`dialogue.py` (prompts, reading replies, when a scene moves on), `engine.py` (one turn),
`safety.py` (flags, pause, resume), `transcripts.py` (reading a session out), `exports.py`.
The rules have their own tests that need no server.

## Documentation

* New `docs/USER_GUIDE.md` (every role) and `docs/TECHNICAL_GUIDE.md` (architecture, data
  model, API, security, testing, how to extend it).
* `docs/REQUIREMENTS_TRACE.md` updated for version 2: scene progression now points to
  `engine.py` (`take_turn`, `advance`, `wrap_up`) and `dialogue.py`, not the old
  `play.py: student_turn, _advance, _wrap_up`; the "New in 1.0" markers are replaced by a
  table of the rows that changed in version 2.
* `DEPLOY.md` refers to the version 2 zip and folder name, and its demo description matches
  the current demo school.

## Upgrading

1. Replace the code. 2. `pip install -r backend/requirements.txt` (adds `reportlab`).
3. Restart. With Docker, rebuild the image; nothing else changes.
4. If you rebuild the frontend yourself, run `npm run build` in `frontend/`; a rebuilt
   `frontend/dist` without the demo sign-in list is already included.
