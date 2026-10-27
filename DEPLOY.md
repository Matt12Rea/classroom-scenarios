# Putting Classroom Scenarios on the web

This guide takes the app from `localhost` to a real website with its own address
and HTTPS, for example `https://scenarios.yourschool.edu`.

The whole site (pages and API) runs as **one container**. It needs a PostgreSQL
database and something in front of it that handles HTTPS. Pick one of the two
routes below.

| | Route A: Render (managed) | Route B: your own Ubuntu server |
|---|---|---|
| Good for | Getting live quickly and free, no server to look after | Matches the SRS's Ubuntu server environment; full control |
| You need | GitHub, Render and Neon accounts (all free, no technical setup) | A Linux server (school server, DigitalOcean, AWS Lightsail…) and a domain name |
| HTTPS | Automatic | Automatic (Caddy + Let's Encrypt) |
| Backups | Neon keeps a short history you can restore from | Nightly `pg_dump` to `./backups` (included) |
| Time | About 30 minutes, mostly waiting | About 30 minutes, needs command-line comfort |

Before either route, get a **Claude API key**: sign in at the Anthropic Console,
open *API keys*, create a key named something like `classroom-scenarios`, and copy it.
You can also skip this and add the key later from the site itself (see
[The AI connection](#the-ai-connection)).

---

## Route A: Render

[Render](https://render.com) is a hosting service: you give it your code and it runs
the website on its servers, gives it an `https://` address, and runs the database.
You never log in to a server yourself. Render reads the `render.yaml` file in this
project, which already describes everything the site needs, so most of the setup is
clicking through screens.

The whole process has four parts, and all the hosting is free:

1. Put the project on **GitHub**, so Render can read it.
2. Create a free database on **Neon**.
3. Ask **Render** to build the site from it.
4. **Sign in** to your new site and finish setting it up.

### What you need before you start

* The project folder. Unzip `aicss-website-v1.0.zip`; you'll get a folder called `aicss`.
* A free GitHub account (github.com).
* A Render account. You can sign up at render.com using your GitHub account, which also
  connects the two. The free plan is enough.
* A Neon account for the free database (neon.com). Part 1b covers this.
* Optionally, your Claude API key (see the start of this guide). You can add it later instead.

### Part 1: Put the project on GitHub

GitHub stores your code online. Render builds the site from it, and every time you
change the code on GitHub, Render rebuilds the site automatically.

1. Sign in at github.com and click **New** (or the **+** menu in the top right, then
   **New repository**).
2. Name it, for example `classroom-scenarios`. Choose **Private**, so only you can
   see the code. Leave the other options as they are and click **Create repository**.
3. On the empty repository page, click the link **uploading an existing file**.
4. Open the `aicss` folder on your computer. Select **everything inside it** (the
   `backend` and `frontend` folders, `Dockerfile`, `render.yaml` and the other files)
   and drag it onto the upload area in your browser.

   Drag the *contents* of `aicss`, not the `aicss` folder itself. Render looks for
   `render.yaml` and `Dockerfile` at the top level of the repository.
5. Wait for the files to finish uploading, then click **Commit changes** at the bottom.
6. Check the result: the repository's main page should list `backend`, `frontend`,
   `Dockerfile`, `render.yaml`, `README.md` and so on directly, not inside another folder.

> If you'd rather not drag files in a browser, **GitHub Desktop** (desktop.github.com)
> does the same job: *File → Add local repository*, choose the `aicss` folder, then
> *Publish repository* with **Keep this code private** ticked.

### Part 1b: Create a free database on Neon

The site needs a PostgreSQL database to store accounts, scenarios and conversations.
`render.yaml` is set up to use a free one from [Neon](https://neon.com), which, unlike
Render's free database, isn't deleted after 30 days.

1. Sign up at neon.com (you can sign in with GitHub).
2. Create a project. Name it `classroom-scenarios` and pick the region closest to you
   (for example a US East or US Central region). Leave the other settings as they are.
3. On the project's dashboard, click **Connect**. Neon shows a **connection string**
   that starts with `postgresql://` and ends with something like `?sslmode=require`.
4. Copy the whole string and keep it somewhere safe for the next part. It contains the
   database password, so don't share it or put it in GitHub.

The free database pauses itself after a few minutes without use and wakes up in under a
second when the site needs it. It holds 1 GB, which is plenty for a school's scenarios
and conversations.

### Part 2: Create the site on Render

1. Sign in at dashboard.render.com.
2. Click **New** (top right) and choose **Blueprint**. A Blueprint is Render's name for
   "set up everything described in a `render.yaml` file".
3. If Render asks, connect your GitHub account and give it access to the
   `classroom-scenarios` repository. Then select that repository.
4. Give the Blueprint a name (for example `classroom-scenarios`). Render reads
   `render.yaml` and shows what it will create:
   * **classroomscenarios**, a free web service. This is the website.
5. Render then asks you to fill in four values. These are kept secret on Render and
   are never stored in your code:

   | Setting | What to enter |
   |---|---|
   | `DATABASE_URL` | The Neon connection string from Part 1b. |
   | `ANTHROPIC_API_KEY` | Your Claude API key, starting `sk-ant-`. You can leave it empty and add it from the site later; until then characters give canned demo replies. |
   | `ADMIN_EMAIL` | Your email address. It becomes the first administrator account. |
   | `ADMIN_PASSWORD` | A temporary password of at least 8 characters, mixing letters with numbers or symbols. You'll replace it the first time you sign in. |

   If Render shows a plan or instance type, make sure it says **Free**.

   The other settings are filled in automatically. Render generates `SECRET_KEY` (a long
   random value used to keep sign-ins secure) by itself. Never change it afterwards: doing
   so signs everyone out and makes a key saved from the site unreadable.
6. Confirm to create the resources. Render builds the website. The first build takes several minutes, because Render is building the whole
   app from scratch.
7. Open **classroomscenarios** in your Render dashboard and watch the **Events** or **Logs** tab.
   When the status changes to **Live**, the site is running.

### Part 3: Open the site and finish setting it up

1. At the top of the **classroomscenarios** page, Render shows the site's address,
   `https://classroomscenarios.onrender.com`. Open it. This is your website, and you can share
   this address with teachers and students.

   The address comes from the service name in `render.yaml` and is fixed when the service is
   first created. If another Render user already has that name, Render adds a few random
   characters to the end (for example `classroomscenarios-x7k2.onrender.com`). To choose an
   address freely, use your own domain (see below).
2. Sign in with your `ADMIN_EMAIL` and `ADMIN_PASSWORD`. You'll be asked to choose a
   new password straight away.
3. Go to **AI connection** in the left-hand menu.
   * If you entered an API key on Render, check that the status says **Connected**, or
     click **Test connection**.
   * If you didn't, paste your key into **Add a key** and click **Save and test key**.
4. Go to **Users and roles** to add teachers and students, one at a time or with
   **Import list** (paste names and emails from a spreadsheet). Each person gets a
   temporary password to give them, and chooses their own at first sign-in.
5. Teachers can then sign in, create classes, build scenarios and assign them.

### Using your school's own web address (optional)

To use an address like `scenarios.yourschool.edu` instead of `onrender.com`:

1. In Render, open **classroomscenarios → Settings → Custom Domains** and add the address.
2. Render shows a DNS record to create. Send it to whoever manages your school's
   domain (usually IT), and ask them to add it.
3. Once the record is in place, Render issues the HTTPS certificate automatically.
   The `onrender.com` address keeps working too.

### Updating the site later

Change the files in your GitHub repository (upload the changed files again, or use
GitHub Desktop). Render notices the change and rebuilds the site automatically. Accounts,
scenarios and conversations are in the database, so they're kept across updates.

### If something goes wrong

* **The build failed.** Open **classroomscenarios → Logs** and read the last red lines. The most common
  cause is that the files were uploaded inside an extra folder, so Render can't find the
  `Dockerfile`. Check Part 1, step 6.
* **I can't sign in as the administrator.** In **classroomscenarios → Logs**, search for
  `first administrator`. If your `ADMIN_PASSWORD` was too short or too simple, the app made
  a temporary password instead and wrote it in that log line.
* **The site takes about a minute to open after a quiet period.** That's the free plan:
  it sleeps after 15 minutes without visitors. Open the site a minute or two before a class
  starts. To stop it sleeping, choose a paid instance type in **classroomscenarios → Settings**.
* **The build log says it can't connect to the database.** Check `DATABASE_URL` in
  **classroomscenarios → Environment**: it must be the complete Neon string, starting with
  `postgresql://`.
* **Characters only give canned replies.** No API key is set. Add one in **AI connection**.

### What it costs

| Part | Cost |
|---|---|
| Website on Render (free plan) | Free. Sleeps after 15 minutes idle; 750 free hours a month, which covers one site running all month. |
| Database on Neon (free plan) | Free. 1 GB of storage; doesn't expire. |
| `onrender.com` address and HTTPS | Free |
| Your own domain (optional) | Whatever your domain registrar charges; often the school already has one |
| Claude API | Pay per use, billed by Anthropic. Demo mode (no key) costs nothing. |

The only part that can't be free is Claude itself: each character reply is a small
charge on your Anthropic account. The Haiku model the site uses by default is the
cheapest. To keep spending predictable, set a monthly spend limit in the Anthropic
Console. Without a key, the site still works in demo mode with canned replies, which
is fine for showing it to people.

If you later need the site to be always awake (for example, many classes using it every
day), change `plan: free` to `plan: 0.5c-512mb` in `render.yaml`.

---

## Route B: your own Ubuntu server

You need a server with a public IP address and a domain name you control.

1. **Point the domain at the server.** In your DNS settings, create an `A` record
   for `scenarios.yourschool.edu` with the server's IP address.
2. **Install Docker** on the server:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Copy the project to the server** (`git clone`, or upload this folder) and go into it.
4. **Create the settings file:**
   ```bash
   cp .env.production.example .env
   nano .env
   ```
   Fill in `DOMAIN`, `PUBLIC_URL`, `SECRET_KEY`, `POSTGRES_PASSWORD`, `ADMIN_EMAIL`,
   `ADMIN_PASSWORD`, and optionally `ANTHROPIC_API_KEY`. Generate the two random values with:
   ```bash
   python3 -c "import secrets;print(secrets.token_urlsafe(48))"
   ```
5. **Start it:**
   ```bash
   docker compose up -d --build
   ```
   This starts four containers: the app, PostgreSQL, a nightly backup job, and Caddy.
   Caddy gets the HTTPS certificate automatically (ports 80 and 443 must be open).
6. Open `https://scenarios.yourschool.edu` and sign in with `ADMIN_EMAIL`.

Useful commands:

```bash
docker compose logs -f app                 # application log
docker compose pull && docker compose up -d --build   # update after pulling new code
ls backups/                                # nightly database backups (14 days kept)
# restore a backup:
docker compose exec -T db pg_restore -U aicss -d aicss --clean < backups/aicss-YYYYMMDD-HHMM.dump
```

Copy `backups/` somewhere off the server too (for example with `rclone` to cloud storage),
so losing the server doesn't lose the backups.

---

## The AI connection

The Claude API key is only ever used on the server. Browsers never see it, and
students, teachers and IT staff can't read it (REQ-3.2.3.10). There are two ways to
provide it, and you can use either:

* **Environment variable** `ANTHROPIC_API_KEY`, set in Render or in `.env`.
* **Admin → AI connection** on the site. Paste the key, and it's tested with Claude
  before it's saved. It's stored encrypted in the database and only a hint
  (`sk-ant-…WXYZ`) is shown afterwards. A key saved here takes priority over the
  environment variable, and replacing it takes effect within seconds, with no redeploy.

The same page lets administrators choose the model, switch between live and demo
mode, run a connection test, and see when Claude last answered or failed and why.
IT support can view it and run tests but not change anything. Every change is
recorded in the audit log.

### Keeping it working indefinitely

A Claude API key doesn't expire. It stops working only when:

1. **The account runs out of credit.** In the Anthropic Console go to *Billing* and turn
   on **auto-reload**, so credit is topped up automatically before it runs out. Set a
   monthly spend limit you're comfortable with as a safety net.
2. **The key is deleted or revoked** in the Console. Use a key created only for this
   site, so nobody deletes it while tidying up keys for something else.
3. **The model is retired.** Anthropic retires old models with notice. If that happens,
   pick a current model in *Admin → AI connection*.

The app also protects students from short outages:

* Failed requests are retried automatically with backoff (`AI_MAX_RETRIES`, default 2).
* If Claude still can't answer, the student sees a clear message, their progress is
  kept, and they can resend the same message (REQ-3.2.3.9).
* Administrators see a red warning on their overview, and *AI connection* explains
  the cause in plain words, for example "The Anthropic account is out of credit".

Point an uptime monitor (UptimeRobot, Better Stack, etc.) at
`https://your-site/api/health` to be alerted if the site or its database goes down.

---

## Settings reference

| Variable | Default | What it does |
|---|---|---|
| `APP_ENV` | `development` | `production` requires a strong `SECRET_KEY`, forces HTTPS and hides the API docs |
| `SECRET_KEY` | random | Signs sign-in tokens and encrypts a dashboard-saved API key. **Keep it stable.** |
| `DATABASE_URL` | SQLite file | `postgresql://…` URLs from hosts are accepted as-is |
| `PUBLIC_URL` | | The site's address |
| `ANTHROPIC_API_KEY` | | Claude key (optional if set from the dashboard) |
| `CLAUDE_MODEL` | `claude-haiku-5-5` | Default model (changeable from the dashboard) |
| `CLAUDE_MODELS` | Haiku, Sonnet, Opus 5.5 | Models offered in the dashboard dropdown |
| `AI_MODE` | automatic | `mock` forces demo replies; blank uses Claude when a key exists |
| `AI_MAX_RETRIES` | `2` | Automatic retries for temporary AI errors |
| `AI_TIMEOUT_SECONDS` | `20` | Give up on a single AI request after this long |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | | Creates the first administrator if none exists |
| `SESSION_TIMEOUT_MINUTES` | `60` | Inactive users are signed out (NFR-5.3.5) |
| `FORCE_HTTPS` | on in production | Redirect HTTP to HTTPS and send HSTS |
| `RATE_LIMIT_BACKEND` | `db` in production | Shares rate limits between server processes |
| `WEB_CONCURRENCY` | `2` | Server processes in the container |
| `MODERATION_AI_REVIEW` | `true` | Default for the background safety review |

## Security checklist before students use it

- [ ] `APP_ENV=production` and a long random `SECRET_KEY`
- [ ] Site opens on `https://` and `http://` redirects to it
- [ ] Demo accounts are **not** loaded (`seed.py --demo` is for trying the app only)
- [ ] First admin has changed the temporary password
- [ ] Auto-reload and a spend limit are set in the Anthropic Console
- [ ] Backups are running and you've tried restoring one
- [ ] Your school's privacy lead has reviewed what is sent to the AI service (see the Help page and NFR-5.5.5)
