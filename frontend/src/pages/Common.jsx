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
              <p className="muted">Use the account your school gave you.</p>
            </div>
            {notice && <div className="banner info" role="status">{notice}</div>}
            <ErrorBanner error={err} />
            <Field label="Email address">{(id) => <input id={id} type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
            <Field label="Password">{(id) => <input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
            <button className="btn primary block" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
            <p className="small muted">Forgot your password? Your teacher or school administrator can reset it.</p>
          </form>
          <aside className="login-about">
            <h2>About this service</h2>
            <p>Classroom Scenarios lets students practise difficult conversations and decisions in realistic situations written by their teachers.</p>
            <dl>
              <dt>Students</dt><dd>talk with characters, choose what to do, and get feedback on the outcome.</dd>
              <dt>Teachers</dt><dd>write scenarios, assign them to classes and review each student's path.</dd>
              <dt>Administrators</dt><dd>manage accounts and review anything flagged by safety checks.</dd>
            </dl>
          </aside>
        </div>
      </main>
      <footer className="login-foot">
        <span>Conversations are stored for teaching and safety review. Names and email addresses are never sent to the AI service.</span>
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
      <PageHead title="My scenarios" sub={`Welcome, ${first}. These are the scenarios your teachers have assigned. Read the brief, talk with the characters, then decide what to do.`} />
      <ErrorBanner error={error || err} onRetry={error ? reload : null} />
      {loading && <Loading />}
      {data && data.length === 0 && (
        <Empty title="Nothing assigned yet">When a teacher assigns you a scenario it will appear here.</Empty>
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
          <li>Type to the character the way you would talk to a real person. Enter sends your message.</li>
          <li>When you're ready, pick a decision under “What do you do?”. Some scenes ask you to talk first.</li>
          <li>Your decisions lead to different endings. At the end you'll see feedback and can try again.</li>
        </ol>
        <p>If a character says something upsetting or inappropriate, hover over the message and choose Report.</p>
      </>}
      {(user.role === "teacher" || user.role === "admin") && <>
        <h2>Building a scenario</h2>
        <ol>
          <li><b>Basics</b>: title, setting and what students should learn.</li>
          <li><b>Characters</b>: who the AI plays. Personality notes shape how they react.</li>
          <li><b>Scenes</b>: each scene is a situation. Add decisions that lead to other scenes, or mark the scene as an ending (success, partial or didn't succeed).</li>
          <li><b>Review &amp; publish</b>: check the map, fix anything flagged, preview it yourself, publish, then assign it to a class.</li>
        </ol>
        <p>The AI only voices characters. It never decides which scene comes next or how the scenario ends; your decisions and endings do.</p>
        <h2>Results</h2>
        <p>Open a scenario's Results to see who has started and finished, which endings students reached, which decisions were popular, and each student's full conversation. Export downloads a CSV.</p>
      </>}
      {user.role === "admin" && <>
        <h2>Safety review</h2>
        <p>Messages are checked automatically. Attempts to bait the AI, self-harm language, threats, abusive language, shared contact details and blocked AI replies appear in Safety review, most serious first. Open a flag to read it in context, then dismiss it or take action: hide the message, pause the AI for that session, or disable the student's account.</p>
        <h2>Accounts</h2>
        <p>Create accounts one at a time or import a list. New accounts get a temporary password and must choose their own at first sign-in.</p>
        <h2>AI connection</h2>
        <p>Characters are voiced by Claude through your school's API key. Open <a href="/ai">AI connection</a> to add or replace the key, choose the model, or switch to demo mode. The key is tested before it's saved, stored encrypted, and can't be viewed again. If replies stop working, that page explains why, for example when the account needs more credit.</p>
      </>}
      {user.role === "it_support" && <>
        <h2>System status</h2>
        <p>The status page shows AI usage and reply times for the last 24 hours, and the audit log. <a href="/ai">AI connection</a> shows whether Claude is answering and lets you run a test. Only administrators can change the key or model.</p>
        <p>Student conversations aren't visible to IT support.</p>
      </>}
      <h2>Privacy</h2>
      <p>Conversations are stored so teachers can give feedback. Only the student, their teachers and school administrators can read them. Messages are sent to the AI service to generate replies; names and emails are not.</p>
    </div>
  );
}
