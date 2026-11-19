# User guide

Classroom Scenarios (the AI Classroom Scenario System) is a website where students practise
professional conversations with characters voiced by Claude. Instructors write the
scenarios; administrators look after accounts, safety and the AI connection; IT support
watches the system's health.

This guide covers each role in turn. The site's own **Help** page (in the masthead and the
user menu) shows a shorter, role-specific version of the same material.

* [Signing in](#signing-in)
* [Students](#students)
* [Instructors](#instructors)
* [Administrators](#administrators)
* [IT support](#it-support)
* [Privacy: what is stored and what goes to the AI](#privacy-what-is-stored-and-what-goes-to-the-ai)
* [Common messages and what to do](#common-messages-and-what-to-do)

---

## Signing in

1. Open the site's address and enter your email address and password.
2. If your account was just created or your password was reset, you signed in with a
   **temporary password**. The site asks you to choose your own before you can continue:
   at least 8 characters, mixing letters with numbers or symbols.
3. To change your password later, open the user menu (your name, top right) and choose
   **Change password**.

**Forgot your password?** There is no self-service reset. Ask your instructor or an
administrator; they can give you a new temporary password.

**Signed out unexpectedly?** For security you are signed out after a period of inactivity
(60 minutes by default). Sign in again; nothing you had saved is lost.

**Too many attempts.** After 8 failed sign-ins for the same email in 5 minutes, the site asks
you to wait a few minutes.

---

## Students

### Your scenarios

After signing in you see **My scenarios**: every scenario assigned to one of your courses,
with its status (not started, in progress, or finished with an outcome).

* **Start** opens a new attempt.
* **Continue** reopens an attempt in progress exactly where you left it. Progress is saved
  after every message, so you can close the browser and come back.
* **Try again** starts a fresh attempt after you have finished. Earlier attempts are kept.

### Playing a scenario

The page has two parts: the conversation, and a **case brief** beside it with the setting,
your goals and the people involved. Read the brief first.

1. **Talk to the character as you would to a real person.** There are no buttons to choose
   from. You can also describe actions, for example *"I sketch a Punnett square for them."*
2. **Some scenes have more than one character.** Everyone present is listed under "In this
   scene". Either may answer, and sometimes both do.
3. **Scenes move on by what you say.** When your approach in a scene is clear, the scenario
   moves to the next scene and shows a short line describing what it took from your
   messages.
4. **There is a message limit.** Each scene and the scenario as a whole allow a set number
   of messages; the counter is shown on the page. If a scene reaches its limit without a
   clear approach from you, the situation moves on without you. Short or off-topic answers
   do not lead to good outcomes.
5. **The ending.** When you reach an ending you see the outcome (succeeded, partly
   succeeded, or didn't succeed), your instructor's feedback for that ending, and a short
   personalised debrief.

If a reply is slow, the page tells you. If the AI service is unavailable, you'll see a
message saying so: **your progress is saved**, and you can send the same message again a
moment later with the retry button.

### Reporting a message

If a character says something inappropriate or wrong, hover over (or tap) the message and
choose **Report**. Add a short note if you like. An administrator reviews every report.

### Paused sessions

Messages that try to make the character break role, say something inappropriate or derail
the scenario are flagged automatically. After several flagged messages in one attempt
(3 by default), the attempt **pauses**: you can't send more messages until an administrator
has reviewed it. The page updates by itself when the session is resumed.

If you write something that suggests you may be at risk of harm, the role-play stops for
that message and the site shows support resources instead of a character reply.

---

## Instructors

Your navigation has **Overview**, **Scenarios** and **Courses**.

### Overview

Recent student activity across your scenarios: who started or finished what, and anything
that needs your attention.

### Courses

A course is a group of students that you assign scenarios to.

* **Create a course** with a name (for example "ECON 210 – Money and Banking").
* **Add students** by email address. Accounts are created by administrators, so the
  students must already have accounts. Adding an email that is already in the course
  doesn't cause an error.
* **Remove** a student or rename or delete a course from the same page.

### Building a scenario

Open **Scenarios → New scenario**. You can start from a blank scenario or from the worked
example (a community bank and interest-rate risk). The builder has four steps; each step
shows how many problems it has ("2 to fix"), and clicking a problem takes you to the field.

**1. Overview.** Title, setting (where the student is and what's going on), learning
objectives, boundaries for the AI, feedback focus for the debrief, and the message limit
for the whole scenario. **Messages per scene** sets every scene's limit at once.

**2. Characters.** The people the AI plays. Each needs a name, a role (for example "the
bank's president") and, ideally, a personality ("practical, not an economist"). Two
characters can't share a name.

**3. Scenes and paths.** The situations the student moves through. For each scene:

* Say **what's happening**: this is what the AI is told about the scene.
* Tick **who is in it**. A scene can have up to four characters.
* Make it an **ending** (name the outcome, choose success / partial / didn't succeed, and
  write the feedback the student will read), **or** give it **paths**.
* Each path is a rule: *If the student…* (the **signal**: what the student says or does),
  *then go to…* (the next scene or ending). Give it a **name**: the student sees the name
  when the path is taken, e.g. "Explained the bank's interest-rate risk". Up to eight paths
  per scene.
* **If no path is clear**: the path to take when the scene runs out of messages without a
  clear approach. Leave it on the default to use the path that can lead to the worst
  ending, so not engaging never pays off.
* **Minimum and maximum messages** for the scene. A scene can't move on before its minimum;
  at its maximum it wraps up.

**4. Review and publish.** Lists every route from the first scene to each ending, with a
labelled map, and any remaining problems. From here you can **Preview** and **Publish**.

Your work saves as a **draft** until you publish. Students never see drafts.

### What the checks look for

Publishing is blocked until these are fixed:

* Missing title, setting, objectives, characters or scenes, or no start scene.
* A scene with no description, no characters, or no way out (it needs a path or must be an
  ending).
* A path with no name, two paths with the same name, or a path that doesn't lead anywhere.
* A scene whose limit is below its minimum.
* No ending reachable from the start.

These are warnings (you can still publish): a scene that can't be reached, a loop with no
way to an ending, a path with no signal, a character who isn't in any scene, no
boundaries set (the standard safety boundaries always apply anyway).

### How scenes move on

Students never see your paths. After each student message, a second AI call (the *judge*)
reads the scene's conversation and says which of your paths, if any, the student has
clearly taken, how sure it is, and why. It can only choose paths you wrote. The scene moves
on when the judge is sure enough (after the scene's minimum), when the scene reaches its
maximum, or when the student uses the scenario's last message (then each remaining scene is
wrapped up in the same way until an ending).

### Previewing

**Preview** plays the scenario as a student would. Under the message box an
**Instructor view** panel lists the scene's paths, and each scene change explains why it
happened. Preview attempts don't appear in your results and their flags don't go to the
safety queue.

### Publishing, assigning and changing a scenario

* **Publish**, then **Assign** to one or more courses. Assigned students see it at once.
* The **Scenarios** page shows each scenario's stage: *still being built*, *ready to
  publish*, *published but not assigned*, or *live*, and its next actions.
* You can edit a live scenario. Students who already started keep the version they started
  with; new attempts use the new version.
* **Unpublish** hides it from students again. **Archive** puts it away (restore brings it
  back as a draft). **Duplicate** makes a copy to adapt. **Delete** removes it.

### Results

Open a scenario's **Results** to see who has started and finished, which paths and endings
students reached, and every conversation. Filter by course, student or date.

Each transcript includes **Why the scene moved on**: the judge's reasoning for each scene
change. Students don't see this.

**Export** downloads the results summary as CSV, or the conversations themselves as PDF or
CSV. Any single conversation can also be exported from its own page.

You see only your own scenarios and your students' work on them.

---

## Administrators

Your navigation has **Overview**, **Oversight** (Safety review, Conversations),
**Teaching** (Scenarios, Courses) and **Administration** (Users and roles, AI connection,
Audit log). Administrators can do everything an instructor can, for every scenario and
course.

### Site overview

Accounts, recent activity, the AI connection's state, and anything that needs review,
including **paused sessions** with a Resume button for each. If the site is in demo mode
(no AI key), a banner says so with a link to set up the AI connection.

### Users and roles

* **Add** one account (name, email, role). The site shows a temporary password; give it to
  the person. They choose their own at first sign-in.
* **Import list** creates many accounts at once from a pasted roster, optionally adding the
  students to a course. Each row succeeds or reports its own problem.
* **Change a role**, **disable** or **enable** accounts, singly or by selecting several.
  Disabling signs the person out at once.
* **Reset password** gives a new temporary password.
* **Delete data** removes a student's conversations and results (for deletion requests).
  **Delete account** removes the account.
* **Retention**: delete all sessions older than a chosen number of days (30 at least).

Roles: **Student**, **Instructor**, **Administrator**, **IT support**.

### Safety review

Flagged and reported messages, most serious first. Flags come from keyword checks, the AI
judge (baiting), the background AI review of each exchange, blocked character replies, and
reports by students or instructors.

Open a flag to see the message in context, then either dismiss it or act on it:

* **Hide the message** so it no longer shows in the conversation.
* **Pause the session** so the student can't continue.
* **Resume the session** (tick box in the review) if it was paused.
* **Disable the account.**

Write a note; every review is recorded in the audit log.

### Paused sessions

A session pauses automatically after a set number of the student's messages are flagged
(3 by default; `AUTO_PAUSE_AFTER_FLAGS`), and a high-priority **Repeated misuse** flag is
raised. Resume it from any of: the site overview, the flag (button or tick box), the
conversation page, or **Conversations** with *Paused only* ticked. After a resume the flag
count starts again from zero.

### Conversations

Every student conversation with the AI, newest first, with search and filters (including
flagged and paused only). Open one to read it, hide a message, pause or resume, or export
it. **Export** on the list downloads every conversation the current filters show, as PDF or
CSV. Every export is recorded in the audit log.

### AI connection

Shows whether Claude is answering, and the cause if not (invalid key, out of credit, rate
limited, service outage).

* **Add or replace the key.** The key is tested before it is saved, stored encrypted, and
  afterwards shown only as `sk-ant-…WXYZ`. Removing it falls back to the server's
  environment key, if there is one, or to demo mode.
* **Model**: choose from the list or type a model id.
* **Mode**: Claude, or **Demo** (canned replies, nothing sent to Claude, no cost).
* **Background safety review** on or off.
* **Run a test** sends a one-word request; no student data is sent.

### Audit log

Significant administrative actions, newest first: account and role changes, safety reviews,
pauses and resumes, data deletion, exports, and AI key and settings changes.

---

## IT support

Your navigation has **System status** and **AI connection**.

* **System status**: the last 24 hours of AI usage and reply times, the AI connection's
  state, and the audit log.
* **AI connection**: whether Claude is answering, and **Run a test**. Only administrators
  can change the key, model or mode.

IT support cannot see student conversations.

---

## Privacy: what is stored and what goes to the AI

* **Stored on the site:** accounts (name, email, role), courses, scenarios, every
  conversation, the paths taken, outcomes, safety flags and the audit log.
* **Who can read conversations:** the student, the instructor who owns the scenario, and
  administrators.
* **Sent to Claude:** the scenario text and the conversation. **Never** names or email
  addresses.
* **Not in the server logs:** message text.
* Fonts and scripts are served from the site itself, so no third party sees visits.

---

## Common messages and what to do

| Message | What it means | What to do |
|---|---|---|
| "That email and password don't match." | Wrong email or password | Check both; ask for a reset if needed |
| "This account is disabled." | An administrator disabled it | Contact your site administrator |
| "Too many sign-in attempts." | 8 failures in 5 minutes | Wait a few minutes |
| "…can't respond right now because the AI service is unavailable. Your progress is saved." | Claude didn't answer | Send the message again shortly. Administrators: check **AI connection** |
| "You've used all … messages for this scenario." | The scenario's message limit | The attempt wraps up; try again from **My scenarios** |
| The session is paused | Several flagged messages | Wait for an administrator to review it |
| "This page isn't available" | Your role can't open that page | Use the navigation for your role |
| A message with a reference code | Something unexpected went wrong | Try again; give the reference to IT support, who can find it in the server log |
