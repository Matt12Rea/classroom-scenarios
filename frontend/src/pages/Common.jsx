// Sign-in, password change, help, and the student's home page.
import { useState } from "react";
import { api, fmtDate, navigate, OUTCOME_LABEL, useApi, useAuth, useToast } from "../lib.jsx";
import { Empty, ErrorBanner, Field, Loading, Logo, PageHead, Status } from "../ui.jsx";

export function Login() {
  const { login, notice } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try { await login(email, password); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div className="login">
      <header className="masthead"><span className="wordmark"><Logo /><span>Classroom Scenarios</span></span></header>
      <main className="login-body" id="main">
        <div className="login-card">
          <form className="login-form stack" onSubmit={submit} noValidate={false}>
            <div>
              <h1>Sign in</h1>
              <p className="muted">Use your university account.</p>
            </div>
            {notice && <div className="banner info" role="status">{notice}</div>}
            <ErrorBanner error={err} />
            <Field label="Email address">{(id) => <input id={id} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="Password">{(id) => <input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
            <button className="btn primary block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
            <p className="small muted">Forgot your password? Your instructor or an administrator can reset it.</p>
          </form>
          <aside className="login-about">
            <Logo size={56} className="crest" />
            <h2>Practise the conversations your discipline depends on.</h2>
            <p>Role-plays written by your instructors, where you put course material to work: advise a bank on interest-rate risk, defend a study to an ethics board, explain a genetic test result.</p>
            <dl>
              <dt>Students</dt><dd>talk with AI characters. What they say decides where the scenario goes.</dd>
              <dt>Instructors</dt><dd>write scenarios, assign them to courses, and review each conversation.</dd>
              <dt>Administrators</dt><dd>manage accounts and review flagged messages.</dd>
            </dl>
          </aside>
        </div>
      </main>
      <footer className="login-foot">
        <span>Conversations are stored for instruction and safety review. Names and emails are never sent to the AI.</span>
      </footer>
    </div>
  );
}

export function ChangePassword({ forced }) {
  const { replaceToken } = useAuth();
  const toast = useToast();
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const [err, setErr] = useState(null);
  const mismatch = f.confirm && f.confirm !== f.new_password;
  const submit = async (e) => {
    e.preventDefault(); setErr(null);
    try {
      const r = await api("/api/auth/password", { method: "POST", body: { current_password: f.current_password, new_password: f.new_password } });
      replaceToken(r); toast("Password changed."); navigate("/");
    } catch (x) { setErr(x); }
  };
  return (
    <div className="page" style={{ maxWidth: 480 }}>
      <PageHead title={forced ? "Choose a new password" : "Change password"}
        sub={forced ? "You signed in with a temporary password. Choose your own before continuing." : null} />
      <form className="panel stack" onSubmit={submit}>
        <ErrorBanner error={err} />
        <Field label={forced ? "Temporary password" : "Current password"}>{(id) => <input id={id} type="password" autoComplete="current-password" required value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} />}</Field>
        <Field label="New password" hint="At least 8 characters, mixing letters with numbers or symbols.">{(id) => <input id={id} type="password" autoComplete="new-password" required value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} />}</Field>
        <Field label="Repeat new password" error={mismatch ? "The passwords don't match." : null}>{(id) => <input id={id} type="password" autoComplete="new-password" required value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} />}</Field>
        <button className="btn primary" disabled={!f.new_password || mismatch}>Change password</button>
      </form>
    </div>
  );
}

export function StudentHome() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi("/api/student/assignments");
  const [err, setErr] = useState(null);
  const open = async (a, restart = false) => {
    if (a.session_id && a.status === "in_progress" && !restart) return navigate(`/play/${a.session_id}`);
    try {
      const st = await api("/api/sessions", { method: "POST", body: { scenario_id: a.scenario_id, restart } });
      navigate(`/play/${st.id}`);
    } catch (x) { setErr(x); }
  };
  const first = user.name.split(" ")[0];
  return (
    <div className="page">
      <PageHead title="My scenarios" sub={`Welcome, ${first}. Read each brief, then handle the situation in your own words.`} />
      <ErrorBanner error={error || err} onRetry={error ? reload : null} />
      {loading && <Loading />}
      {data && data.length === 0 && (
        <Empty title="Nothing assigned yet">Scenarios your instructors assign will appear here.</Empty>
      )}
      {data?.length > 0 && (
        <div className="assignments">
          {data.map((a) => (
            <article className="assignment" key={a.scenario_id}>
              <div className="assignment-main">
                <h2>{a.title}</h2>
                <p className="assignment-class">{a.class_name}{a.due_at && <> <span aria-hidden="true">/</span> Due {fmtDate(a.due_at)}</>}</p>
                {a.description && <p className="assignment-desc">{a.description}</p>}
                {a.objectives.length > 0 && <>
                  <h3 className="sr-only">Goals</h3>
                  <ul>{a.objectives.slice(0, 3).map((o) => <li key={o}>{o}</li>)}</ul>
                </>}
              </div>
              <div className="assignment-side">
                <div className="row end">
                  <Status value={a.status} />
                  {a.outcome_type && <span className={`badge ${a.outcome_type}`}>{OUTCOME_LABEL[a.outcome_type]}</span>}
                </div>
                <div className="row end">
                  {a.status === "in_progress" && <button className="btn primary" onClick={() => open(a)}>Continue</button>}
                  {a.status === "not_started" && <button className="btn primary" onClick={() => open(a)}>Start scenario</button>}
                  {(a.status === "completed" || a.status === "abandoned") && <>
                    {a.session_id && <a className="btn" href={`/play/${a.session_id}`}>See result</a>}
                    <button className="btn primary" onClick={() => open(a, true)}>Try again</button>
                  </>}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}

export function Help() {
  const { user } = useAuth();
  return (
    <div className="page help">
      <PageHead title="Help" />
      {user.role === "student" && <>
        <h2>Playing a scenario</h2>
        <ol>
          <li>Open a scenario from <a href="/">My scenarios</a> and read the setting and your goals.</li>
          <li>Reply to the character as you would to a real person. You can describe actions, such as “I sketch a Punnett square.”</li>
          <li>When your approach is clear, the scene moves on and shows what it took from your messages.</li>
          <li>Each scenario has a message limit. At the end you'll get feedback and can try again.</li>
        </ol>
        <p>To report a character's message, hover over it and choose Report.</p>
        <p>Messages that try to make the AI break character are flagged. After several, the session pauses until an administrator reviews it.</p>
      </>}
      {(user.role === "teacher" || user.role === "admin") && <>
        <h2>Building a scenario</h2>
        <ol>
          <li><b>Basics</b>: title, setting, objectives and message limits.</li>
          <li><b>Characters</b>: who the AI plays and how they behave.</li>
          <li><b>Scenes</b>: the situations. Give each scene paths to other scenes, and describe what a student says or does to take each one. Or make the scene an ending.</li>
          <li><b>Review &amp; publish</b>: check the map, preview, publish, then assign to a course.</li>
        </ol>
        <h2>How scenes move on</h2>
        <p>Students never see your paths. After each message, an AI judge checks whether the student's words match one of them. It can only choose paths you wrote.</p>
        <p>Each scene has a minimum and a maximum number of messages. At the maximum, if no path was clearly taken, the scene's fallback path is used. By default that's the path toward the worst ending, so not engaging never pays off.</p>
        <p>In Preview, a panel below the message box lists the scene's paths, and each scene change explains why it happened. Students see neither.</p>
        <h2>Results</h2>
        <p>Results show who has started and finished, which paths and endings students reached, and each full conversation. Export downloads a CSV.</p>
      </>}
      {user.role === "admin" && <>
        <h2>Safety review</h2>
        <p>Flagged messages appear in Safety review, most serious first. Open one to see it in context, then dismiss it or act: hide the message, pause the session, or disable the account.</p>
        <p>Messages are checked by keyword and, when Claude is connected, by the AI judge. After 3 flagged messages in one session (set with <code>AUTO_PAUSE_AFTER_FLAGS</code>), the session pauses and a “Repeated misuse” flag appears. Resume it from the conversation.</p>
        <h2>Accounts</h2>
        <p>Add accounts one at a time or import a list. New accounts get a temporary password.</p>
        <h2>AI connection</h2>
        <p>Characters are voiced by Claude using your institution's API key. Open <a href="/ai">AI connection</a> to add or replace the key, pick a model, or switch to demo mode. Keys are tested before saving and stored encrypted. If replies stop, that page shows why.</p>
      </>}
      {user.role === "it_support" && <>
        <h2>System status</h2>
        <p>System status shows the last 24 hours of AI usage and reply times, plus the audit log. <a href="/ai">AI connection</a> shows whether Claude is answering and can run a test. Only administrators can change the key or model.</p>
        <p>IT support can't see student conversations.</p>
      </>}
      <h2>Privacy</h2>
      <p>Conversations are stored so instructors can give feedback. Only the student, their instructors and administrators can read them. Messages go to the AI service; names and emails don't.</p>
    </div>
  );
}
