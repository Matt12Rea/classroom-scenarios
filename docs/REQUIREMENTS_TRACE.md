# Requirements traceability

Maps every requirement in the SRS (v1.0, Kyrin Ellis & Matt Rea, 9/24/2026) to where
it is met in this version. **Status:** Met, Partial (works, with a stated limit), or
Not started.

Items marked **New in 1.0** were added in the website release (deployment, redesigned
interface, AI connection management).

## 2.4 Design and implementation constraints

| Constraint | Status | Where |
|---|---|---|
| FERPA / COPPA student data privacy | Partial | Role-based access (`access.py`), data minimisation (no names/emails to Claude), retention purge and per-student deletion (`admin.py`). Formal compliance review is the institution's. |
| HTTPS for all communications | Met (New in 1.0) | Caddy or Render terminate TLS; `FORCE_HTTPS` redirects HTTP and sends HSTS (`main.py`) |
| AI responses within 2 seconds | Partial | Haiku model by default, history capped at 10 exchanges, slow replies flagged to the student (NFR-5.1.6). Depends on the external service. |
| Claude AI as the primary engine, via a secure API interface | Met | `ai.py` is the only module that calls Claude; key server-side only (see 3.2) |
| Application controls scenario progression, not the AI | Met | Decisions and endings are application logic (`play.py: student_decision`) |

## 3.1 Scenario authoring and management

| ID | Status | Where |
|---|---|---|
| REQ-3.1.1 Only authorized teachers create scenarios | Met | `require("teacher","admin")` on scenario routes |
| REQ-3.1.2 Multiple decision points | Met | Scenes with decisions, Editor → Scenes |
| REQ-3.1.3 Multiple outcomes per decision point | Met | Each decision leads to any scene or ending |
| REQ-3.1.4 Edit/delete own scenarios | Met | Ownership checks in `access.py` |
| REQ-3.1.5 Save as draft | Met | Status `draft` until published |
| REQ-3.1.6 Validate before publishing | Met | `scenario_schema.validate`; publish blocked with errors |
| REQ-3.1.7 Preview before publishing | Met | "Preview as student" (sessions flagged `is_preview`) |
| REQ-3.1.8 Error on missing/invalid field | Met | Field-level errors shown on the affected tab and field |

## 3.2 Role-play engine

| ID | Status | Where |
|---|---|---|
| REQ-3.2.3.1 Claude as primary engine | Met | `ai.ClaudeEngine` |
| REQ-3.2.3.2 Submit scenario context | Met | `build_system_prompt` |
| REQ-3.2.3.3 Character role and traits | Met | Scene speaker's name, role, personality |
| REQ-3.2.3.4 Conversation history | Met | Last `HISTORY_TURNS` exchanges |
| REQ-3.2.3.5 Student's current input | Met | |
| REQ-3.2.3.6 Scenario instructions and boundaries | Met | Teacher boundaries + fixed school-safety rules |
| REQ-3.2.3.7 Validate response before display | Met | `moderation.screen_output`; blocked replies replaced and queued for review |
| REQ-3.2.3.8 Record interactions | Met | `messages` table with tokens and latency |
| REQ-3.2.3.9 Notify and recover when Claude is unavailable | Met (improved in 1.0) | Automatic retries with backoff; student keeps progress and can resend; admins see the cause on Overview and **AI connection** |
| REQ-3.2.3.10 No unauthorized access to AI credentials | Met (New in 1.0) | Key never sent to browsers; dashboard key is write-only, encrypted at rest (`settings_store.py`), shown only as a hint; only admins can change it; all changes audited |

## 3.3 Problem-solving pathing

| ID | Status | Where |
|---|---|---|
| REQ-3.3.1 Multiple decision points | Met | |
| REQ-3.3.2 Multiple paths per decision point | Met | |
| REQ-3.3.3 Each decision tied to a branch/outcome | Met | `choices[].next` |
| REQ-3.3.4 Show next step after decision | Met | |
| REQ-3.3.5 Record each decision | Met | `decisions` table |
| REQ-3.3.6 Multiple completion outcomes | Met | Endings typed success / partial / didn't succeed |
| REQ-3.3.7 Feedback on incomplete/invalid paths | Met | Dead ends, unreachable scenes and broken links flagged in the editor and on the map |
| REQ-3.3.8 Students can't modify paths | Met | Server checks the choice against the frozen scenario snapshot |

## 3.4 Interactive case-based learning

| ID | Status | Where |
|---|---|---|
| REQ-3.4.1 Teachers create case studies | Met | Same builder: setting, objectives, scenes |
| REQ-3.4.2 Objectives and completion criteria | Met | Objectives; endings and per-scene minimum messages |
| REQ-3.4.3 Review case information before deciding | Met | Case brief beside the conversation (setting, goals, people) |
| REQ-3.4.4 Submit responses | Met | |
| REQ-3.4.5 AI-guided feedback configured by teacher | Met | Debrief guided by the teacher's feedback focus and ending notes |
| REQ-3.4.6 Record responses and outcomes | Met | |
| REQ-3.4.7 Notify on completion | Met | Ending panel and confirmation message |

## 3.5 Analytics / reporting

| ID | Status | Where |
|---|---|---|
| REQ-3.5.1 Participation data | Met | Sessions |
| REQ-3.5.2 Completion data | Met | |
| REQ-3.5.3 Decisions | Met | |
| REQ-3.5.4 Student and class performance | Met | Results page |
| REQ-3.5.5 Filter by student, class, scenario, date | Met | Results filters and per-student rows |
| REQ-3.5.6 Restrict by permission | Met | |
| REQ-3.5.7 Export CSV or PDF | Partial | CSV export; PDF via the browser's print (print stylesheet added in 1.0) |
| REQ-3.5.8 Error if data unavailable | Met | Error banners with retry |

## 3.6 User and access management

| ID | Status | Where |
|---|---|---|
| REQ-3.6.1 Teacher, student, admin, IT support roles | Met | `models.ROLES` |
| REQ-3.6.2 Restrict by role | Met | Server checks; each role sees only its own navigation |
| REQ-3.6.3 Create and manage accounts | Met | Users and roles; bulk import |
| REQ-3.6.4 Assign and modify roles | Met | Single and bulk |
| REQ-3.6.5 Block admin functions for others | Met | |
| REQ-3.6.6 Error on insufficient permission | Met | 403 message and "page isn't available" screen |

## 4 External interfaces

| Requirement | Status | Where |
|---|---|---|
| 4.1 Responsive web UI for all roles | Met (redesigned in 1.0) | Works from phone width up; consistent masthead, grouped navigation and breadcrumbs |
| 4.1 Confirmation after actions, clear errors | Met | Toasts and banners |
| 4.1 Help from major areas | Met | Help in the masthead and user menu, role-specific |
| 4.1 Readable typography and contrast | Met | Public Sans UI type; colours meet WCAG AA contrast |
| 4.2 No special hardware | Met | |
| 4.3 Relational database | Met | PostgreSQL in production, SQLite for development |
| 4.3 Cloud AI service interface | Met | |
| 4.3 LMS integration (LTI) | Not started | See UC-07 |
| 4.3 Validate external data; log integration errors without student data | Met | Error classes logged, never message text |
| 4.4 HTTPS/TLS; session management | Met (New in 1.0) | TLS at the proxy; signed expiring tokens |
| 4.4 Detect failures, retry without duplicates | Met | Browser retries only safe GET requests; server retries AI calls |
| 4.4 No student data to external services unless required | Met | Only scenario text and conversation go to Claude; fonts and scripts are self-hosted (New in 1.0) |

## 5 Nonfunctional

| ID | Status | Notes |
|---|---|---|
| NFR-5.1.1 Pages within 3 s | Met | Static assets cached long-term with content hashes |
| NFR-5.1.2 AI within 2 s for 90% | Partial | Depends on Claude; latency recorded per reply and shown to admins/IT |
| NFR-5.1.3 Loading indicator after 1 s | Met | |
| NFR-5.1.4 80 concurrent users | Met | Multiple worker processes, PostgreSQL, shared rate limits (New in 1.0) |
| NFR-5.1.5 Queries within 2 s | Met | Indexed foreign keys |
| NFR-5.1.6 Notify when external service is slow | Met | |
| NFR-5.2.1 Admin can report/disable AI content | Met | Hide message, pause AI per session |
| NFR-5.2.2 Students can't reach admin functions | Met | |
| NFR-5.2.3 Teacher review before release | Met | Draft and preview |
| NFR-5.2.4 Teacher-defined AI boundaries | Met | |
| NFR-5.2.5 Fallback on invalid AI response | Met | |
| NFR-5.2.6 No physically unsafe instructions | Met | Fixed safety rules + output screening |
| NFR-5.2.7 Users can report content | Met | Report on any character line |
| NFR-5.3.1 Authentication required | Met | |
| NFR-5.3.2 RBAC | Met | |
| NFR-5.3.3 HTTPS/TLS | Met (New in 1.0) | |
| NFR-5.3.4 Secure password hashing | Met | PBKDF2-SHA256, 600k iterations |
| NFR-5.3.5 Session timeout | Met | `SESSION_TIMEOUT_MINUTES` |
| NFR-5.3.6 Students isolated from each other | Met | |
| NFR-5.3.7 Report access by role | Met | |
| NFR-5.3.8 Audit of admin actions | Met | Now includes AI key and settings changes |
| NFR-5.3.9 Protect stored student info | Met | Access control; database not publicly exposed in either deployment |
| NFR-5.3.10 FERPA/COPPA | Partial | Technical controls in place; institutional review required |
| NFR-5.3.11 Minimise PII | Met | Name and email only |
| NFR-5.3.12 Retention and deletion | Met | |
| NFR-5.4.1–3 Usability | Met | Form-based builder; plain-language errors |
| NFR-5.4.4 Preserve saved data on error | Met | |
| NFR-5.4.5 Handle external outages | Met | |
| NFR-5.4.6 Regular backups | Met (New in 1.0) | Nightly `pg_dump` (Docker) or Render managed backups |
| NFR-5.4.7 99% availability | Partial | Health check endpoint and container restart policy; depends on hosting |
| NFR-5.4.8 Maintenance notices | Not started | Use a banner or email for now |
| NFR-5.4.9 Modular components | Met | AI, moderation, settings, routers separated |
| NFR-5.4.10 Technical documentation | Met | README, DEPLOY, this file |
| NFR-5.4.11 Diagnosable error logs | Met | |
| NFR-5.4.12–13 Scalability | Met | Stateless app, horizontal scaling, shared rate limits |
| NFR-5.4.14–15 Browsers and devices | Met | Current Chrome, Edge, Firefox, Safari; Windows, macOS, iOS, Android |
| NFR-5.4.16 LMS interfaces documented | Not started | |
| NFR-5.4.17 Standard protocols | Met | HTTPS/JSON |
| NFR-5.4.18–19 Testability and logs | Met | `tests/test_api.py`; AI status recorded for admins/testers |
| NFR-5.5.1–6 Privacy | Met | What goes to Claude is documented on the Help and AI connection pages |
| NFR-5.6.1 Keyboard access | Met | Skip link, focus trap in dialogs, keyboard-operable scenario map |
| NFR-5.6.2 Text alternatives | Met | |
| NFR-5.6.3 Contrast | Met | |
| NFR-5.6.4 Labelled fields | Met | |
| NFR-5.6.5 Accessible errors | Met | `role="alert"` |
| NFR-5.6.6 WCAG 2.1 AA | Partial | Designed to AA; a formal audit is still to do |

## 6 Use cases

| UC | Status |
|---|---|
| UC-01 Create scenario | Met |
| UC-02 Participate in scenario | Met |
| UC-03 Interact with AI character (incl. retry when Claude is unavailable) | Met |
| UC-04 Make scenario decision | Met |
| UC-05 View analytics | Met |
| UC-06 Manage users | Met |
| UC-07 Exchange data with LMS | Not started |

## 7 Other requirements

| Requirement | Status |
|---|---|
| Internationalisation (English, Spanish, French) | Not started (English only) |
| Reuse of existing AI/NLP components | Met (Anthropic SDK) |
