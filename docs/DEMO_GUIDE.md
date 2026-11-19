# Demo guide

The demo school is loaded with `python seed.py --demo` (or `LOAD_DEMO_DATA=true` on a hosted
site). Every account uses the password `demo-pass-1` unless `DEMO_PASSWORD` is set. The
sign-in page does not list the demo accounts: type the email and password below into the
normal sign-in form. If you are showing the site to someone, give them this table.

Nothing in the demo is random. Each student is in one clearly different state, and every
conversation was written to match its result, so what you read always agrees with the outcome
shown beside it.

## Who to sign in as

| Sign in as | Person | What you will see |
|---|---|---|
| `admin@demo.school` | Avery Admin, administrator | One paused session waiting for review, the safety queue, every conversation, accounts |
| `teacher@demo.school` | Dr. Dana Rivera, instructor | Two published scenarios with results, one draft |
| `student@demo.school` | Maya Chen, student | One scenario finished, one in progress, one not started |
| `it@demo.school` | Ira Support, IT support | System status and the AI connection only (no student conversations) |

A second instructor, `teacher2@demo.school` (Prof. Chris Okafor), owns the genetics scenario.
It shows that instructors see only their own scenarios and students' work for them.

## The three courses

| Course | Instructor | Scenario | What it shows |
|---|---|---|---|
| ECON 210 – Money and Banking | Dr. Rivera | Prairie State Bank: the fixed-rate question | One character. A branch where a mistake leads to a harder second scene |
| PSYC 310 – Research Methods | Dr. Rivera | IRB review: the Cyberball study | A "second chance" scene after a weak answer |
| BIOL 340 – Human Genetics | Prof. Okafor | Genetics clinic: two carriers | **Two characters in one scene**: both parents are present and either may answer |

Dr. Rivera also has a draft, *1787: the representation deadlock*, which is not published and
which no student can see.

## Every student, and the state they are in

| Student | ECON 210 (bank) | PSYC 310 (IRB) | BIOL 340 (genetics) |
|---|---|---|---|
| Maya Chen (`student@`) | Finished: **success**, with written AI feedback | **In progress**, one message sent | **Not started** |
| Leo Park | Finished: **partial** (endorsed the loans, then diagnosed the losses) | | |
| Priya Singh | **In progress**, in the second scene | | |
| Owen Brooks | **Paused for review** after three flagged messages | | |
| Zoe Martin | | Finished: **success** | |
| Eli Duarte | | Finished: **didn't succeed** (withdrew the protocol) | |
| Nora Kim | | **Not started** | |
| Sam Patel | | | Finished: **success** |
| Ava Lopez | | | Finished: **partial** (steered the couple's decision) |
| Ben Carter | | | Finished: **didn't succeed** (left the couple misinformed) |

Blank cells mean the student is not in that course.

The safety queue holds four open flags, all from Owen's session (three flagged messages and
the automatic pause). Under "Action taken" there is one finished example: Prof. Okafor reported
a character's line and the administrator recorded a decision.

## Five-minute walkthrough

1. **Student.** Sign in as the student. Open *IRB review* (in progress) and send a message.
   Open *Genetics clinic* and start it: Ana and Luis are both listed as "In this scene", and
   replies come from either or both.
2. **Instructor.** Sign in as the instructor. Open *Scenarios*, then *Prairie State Bank*.
   Step 3, *Scenes and paths*, shows each scene and its paths written as "If the student…,
   then go to…". Step 4, *Review and publish*, lists every route from the first scene to each
   ending. Then open *Results* and use *Export*.
3. **Administrator.** Sign in as the administrator. The overview shows one paused session.
   Open the "Repeated misuse" flag, read Owen's three messages, tick *Resume the session* and
   choose *Take action* (or use the *Resume session* button). Owen can now continue, and it
   takes three new flagged messages to pause him again. Open any conversation and choose
   *Export* for a PDF.

## Resetting the demo

Delete the database file (`backend/classroom.db` in development) and run
`python seed.py --demo` again. The demo is only added when `admin@demo.school` does not exist.

## Demo mode and the AI

Without a Claude API key the site runs in demo mode: characters give stock replies that are
obviously generic, and a word-matching stand-in decides when scenes move on. The conversations
already in the demo were written by hand to show what real ones look like. Add a key under
*AI connection* for live replies.
