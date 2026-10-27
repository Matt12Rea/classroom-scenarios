// Administrator screens: overview, users & roles, safety review, interactions,
// audit log. Also the shared conversation view used by teachers.
import { useEffect, useState } from "react";
import Script from "../../components/Script.jsx";
import { api, CATEGORY_LABEL, fmtDateTime, OUTCOME_LABEL, ROLE_LABEL, useApi, useAuth, useToast } from "../../lib.jsx";
import { ReportDialog } from "../Play.jsx";
import { Breadcrumbs, Confirm, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Status } from "../../ui.jsx";

const SOURCE_LABEL = { auto_input: "Automatic check", auto_output: "Blocked AI reply", ai_review: "AI safety review", report: "User report" };

// ============================================================ overview ==
export function AdminHome() {
  const { data: s, error, reload } = useApi("/api/admin/stats");
  const { data: flags } = useApi("/api/admin/flags?status=open");
  return (
    <div className="page">
      <PageHead title="School overview" sub="Accounts, live activity and anything that needs a person to look at it." />
      <ErrorBanner error={error} onRetry={reload} />
      {!s && !error && <Loading />}
      {s && <>
        <div className="figures">
          <a className="figure" href="/flags" style={{ textDecoration: "none", color: "inherit", borderColor: s.open_flags.high ? "var(--bad)" : undefined }}>
            <b>{(s.open_flags.high || 0) + (s.open_flags.medium || 0) + (s.open_flags.low || 0)}</b>
            <span>open safety flags{s.open_flags.high ? `, ${s.open_flags.high} serious` : ""}</span>
          </a>
          <div className="figure"><b>{s.sessions_active}</b><span>scenarios in progress</span></div>
          <div className="figure"><b>{(s.users.student || 0)} / {(s.users.teacher || 0)}</b><span>students / teachers</span></div>
          <div className="figure"><b>{s.ai_last_24h.avg_latency_ms != null ? `${(s.ai_last_24h.avg_latency_ms / 1000).toFixed(1)}s` : "–"}</b><span>avg. AI reply time (24h, {s.ai_last_24h.replies} replies)</span></div>
        </div>
        {s.ai_mode === "mock" && <div className="banner warn row between"><span>The AI is in demo mode, so characters give canned replies. Add a Claude API key to turn on live conversations.</span><a className="btn small" href="/ai">Set up AI connection</a></div>}
        {s.ai_error && <div className="banner error row between"><span><b>Students can't get AI replies right now.</b> {s.ai_error}</span><a className="btn small" href="/ai">Open AI connection</a></div>}
      </>}
      <div className="panel">
        <div className="panel-head"><h2>Needs review</h2><a href="/flags">Safety review</a></div>
        {flags?.length === 0 && <Empty title="Nothing to review">Flagged conversations will appear here.</Empty>}
        {flags && flags.length > 0 && <FlagList flags={flags.slice(0, 6)} />}
      </div>
    </div>
  );
}

// =============================================================== users ==
export function Users() {
  const toast = useToast();
  const { user: me } = useAuth();
  const [q, setQ] = useState(""), [role, setRole] = useState(""), [status, setStatus] = useState("");
  const qs = new URLSearchParams(Object.entries({ q, role, status }).filter(([, v]) => v)).toString();
  const { data, error, loading, reload } = useApi(`/api/admin/users${qs ? "?" + qs : ""}`);
  const [sel, setSel] = useState(new Set());
  const [bulkRole, setBulkRole] = useState("");
  const [modal, setModal] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => setSel(new Set()), [qs]);

  const toggle = (id) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allSel = data?.length > 0 && data.every((u) => sel.has(u.id));
  const bulk = async (patch, label) => {
    setErr(null);
    try {
      const r = await api("/api/admin/users/bulk", { method: "POST", body: { ids: [...sel], ...patch } });
      toast(`${label}: ${r.changed} account${r.changed === 1 ? "" : "s"} updated.${r.skipped.length ? ` ${r.skipped.length} skipped.` : ""}`);
      setSel(new Set()); setBulkRole(""); reload();
    } catch (e) { setErr(e); }
  };

  return (
    <div className="page">
      <PageHead title="Users and roles" sub="Create accounts, change roles, and disable access.">
        <button className="btn" onClick={() => setModal({ kind: "import" })}>Import list</button>
        <button className="btn primary" onClick={() => setModal({ kind: "create" })}>Add user</button>
      </PageHead>
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="grow" style={{ minWidth: 220 }}><label htmlFor="uq" className="sr-only">Search users</label>
          <input id="uq" type="search" placeholder="Search by name or email" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <label className="sr-only" htmlFor="ur">Role</label>
        <select id="ur" value={role} onChange={(e) => setRole(e.target.value)} style={{ width: "auto" }}>
          <option value="">All roles</option>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <label className="sr-only" htmlFor="us">Status</label>
        <select id="us" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
          <option value="">Active and disabled</option><option value="active">Active</option><option value="disabled">Disabled</option>
        </select>
      </div>
      <ErrorBanner error={error || err} onRetry={error ? reload : null} />
      {loading && !data && <Loading />}
      {data && data.length === 0 && <Empty title="No users match">Try a different search or filter.</Empty>}
      {data && data.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr>
              <th style={{ width: 40 }}><input type="checkbox" aria-label="Select all" checked={allSel} onChange={() => setSel(allSel ? new Set() : new Set(data.map((u) => u.id)))} /></th>
              <th>Name</th><th>Role</th><th>Classes</th><th>Status</th><th>Last sign-in</th><th><span className="sr-only">Actions</span></th>
            </tr></thead>
            <tbody>{data.map((u) => (
              <tr key={u.id} className={sel.has(u.id) ? "selected" : ""}>
                <td><input type="checkbox" aria-label={`Select ${u.name}`} checked={sel.has(u.id)} onChange={() => toggle(u.id)} /></td>
                <td><b>{u.name}</b><div className="small muted">{u.email}</div></td>
                <td>{ROLE_LABEL[u.role]}</td>
                <td className="small">{u.classes.join(", ") || <span className="muted">–</span>}</td>
                <td>{u.active ? <Status value="ok" label={u.must_change_password ? "Awaiting first sign-in" : "Active"} /> : <Status value="disabled" label="Disabled" />}</td>
                <td className="nowrap small">{u.last_login ? fmtDateTime(u.last_login) : <span className="muted">Never</span>}</td>
                <td className="nowrap"><button className="btn small" onClick={() => setModal({ kind: "edit", u })}>Manage</button></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      {sel.size > 0 && (
        <div className="bulkbar" role="region" aria-label="Bulk actions">
          <b>{sel.size} selected</b>
          <label className="sr-only" htmlFor="bulk-role">New role</label>
          <select id="bulk-role" value={bulkRole} onChange={(e) => setBulkRole(e.target.value)}>
            <option value="">Change role to…</option>{Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <button className="btn primary" disabled={!bulkRole} onClick={() => bulk({ role: bulkRole }, "Role changed")}>Apply</button>
          <button className="btn" onClick={() => bulk({ active: true }, "Enabled")}>Enable</button>
          <button className="btn danger" style={{ background: "#fff" }} onClick={() => bulk({ active: false }, "Disabled")}>Disable</button>
          <button className="btn quiet" style={{ color: "#fff" }} onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}
      {modal?.kind === "create" && <CreateUser onClose={() => setModal(null)} onDone={reload} />}
      {modal?.kind === "import" && <ImportUsers onClose={() => setModal(null)} onDone={reload} />}
      {modal?.kind === "edit" && <ManageUser u={modal.u} isSelf={modal.u.id === me.id} onClose={() => setModal(null)} onDone={reload} />}
    </div>
  );
}

function CreateUser({ onClose, onDone }) {
  const [f, setF] = useState({ name: "", email: "", role: "student" });
  const [err, setErr] = useState(null);
  const [made, setMade] = useState(null);
  const submit = async () => {
    try { const r = await api("/api/admin/users", { method: "POST", body: f }); setMade(r); onDone(); }
    catch (e) { setErr(e); }
  };
  if (made) return (
    <Modal title="Account created" onClose={onClose}>
      <p><b>{made.user.name}</b> ({made.user.email}) can sign in with this temporary password:</p>
      <p><span className="mono-pw" style={{ fontSize: "1.2rem" }}>{made.temporary_password}</span></p>
      <p className="muted small">They'll choose their own password at first sign-in. This password won't be shown again.</p>
      <div className="modal-foot"><button className="btn primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
  return (
    <Modal title="Add user" onClose={onClose}>
      <ErrorBanner error={err} />
      <div className="stack">
        <Field label="Full name">{(id) => <input id={id} type="text" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        <Field label="Email">{(id) => <input id={id} type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />}</Field>
        <Field label="Role">{(id) => (
          <select id={id} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>)}</Field>
      </div>
      <div className="modal-foot"><button className="btn quiet" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!f.name || !f.email} onClick={submit}>Create account</button></div>
    </Modal>
  );
}

function ImportUsers({ onClose, onDone }) {
  const { data: classes } = useApi("/api/classes");
  const [text, setText] = useState("");
  const [cls, setCls] = useState("");
  const [res, setRes] = useState(null);
  const [err, setErr] = useState(null);
  const rows = text.split("\n").map((l) => l.split(/[,\t]/).map((x) => x.trim())).filter((r) => r[0]);
  const submit = async () => {
    try {
      const r = await api("/api/admin/users/import", { method: "POST", body: {
        class_id: cls ? Number(cls) : null,
        users: rows.map(([name, email, role]) => ({ name, email: email || "", role: (role || "student").toLowerCase().replace(" ", "_") })) } });
      setRes(r); onDone();
    } catch (e) { setErr(e); }
  };
  const downloadCsv = () => {
    const csv = "name,email,role,temporary_password\n" + res.created.map((u) => [u.name, u.email, u.role, u.temporary_password].join(",")).join("\n");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob([csv], { type: "text/csv" })), download: "new-accounts.csv" });
    a.click();
  };
  if (res) return (
    <Modal title="Import finished" onClose={onClose} wide>
      <p>Created {res.created.length} account{res.created.length === 1 ? "" : "s"}. Download the temporary passwords now; they won't be shown again.</p>
      {res.errors.length > 0 && <div className="banner warn">{res.errors.length} row{res.errors.length === 1 ? "" : "s"} skipped:<ul>{res.errors.map((e) => <li key={e.row}>Row {e.row} ({e.email || "no email"}): {e.message}</li>)}</ul></div>}
      <div className="modal-foot">{res.created.length > 0 && <button className="btn" onClick={downloadCsv}>Download passwords (CSV)</button>}<button className="btn primary" onClick={onClose}>Done</button></div>
    </Modal>
  );
  return (
    <Modal title="Import users" onClose={onClose} wide>
      <ErrorBanner error={err} />
      <div className="stack">
        <Field label="One person per line: name, email, role" hint="Role is optional and defaults to student. You can paste straight from a spreadsheet.">
          {(id) => <textarea id={id} rows={8} value={text} onChange={(e) => setText(e.target.value)} placeholder={"Maya Chen, maya@school.edu\nDana Rivera, dana@school.edu, teacher"} />}
        </Field>
        <Field label="Also add new students to a class (optional)">{(id) => (
          <select id={id} value={cls} onChange={(e) => setCls(e.target.value)}>
            <option value="">No class</option>{classes?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>)}</Field>
      </div>
      <div className="modal-foot"><button className="btn quiet" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!rows.length} onClick={submit}>Import {rows.length || ""} {rows.length === 1 ? "person" : "people"}</button></div>
    </Modal>
  );
}

function ManageUser({ u, isSelf, onClose, onDone }) {
  const toast = useToast();
  const [f, setF] = useState({ name: u.name, role: u.role });
  const [err, setErr] = useState(null);
  const [pw, setPw] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const save = async (patch, msg) => {
    try { await api(`/api/admin/users/${u.id}`, { method: "PATCH", body: patch }); toast(msg); onDone(); onClose(); }
    catch (e) { setErr(e); }
  };
  return (
    <Modal title={`Manage ${u.name}`} onClose={onClose}>
      <ErrorBanner error={err} />
      <p className="muted" style={{ marginTop: -8 }}>{u.email}</p>
      <div className="stack">
        <Field label="Full name">{(id) => <input id={id} type="text" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        <Field label="Role" hint={isSelf ? "You can't change your own role." : "Takes effect the next time they sign in."}>{(id) => (
          <select id={id} value={f.role} disabled={isSelf} onChange={(e) => setF({ ...f, role: e.target.value })}>
            {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>)}</Field>
        {pw && <div className="banner ok">New temporary password: <span className="mono-pw">{pw}</span></div>}
        <div className="row" style={{ borderTop: "1px solid var(--line-2)", paddingTop: 16 }}>
          <button className="btn small" onClick={async () => { try { setPw((await api(`/api/admin/users/${u.id}/reset-password`, { method: "POST" })).temporary_password); } catch (e) { setErr(e); } }}>Reset password</button>
          {!isSelf && (u.active
            ? <button className="btn small danger" onClick={() => save({ active: false }, `${u.name} disabled.`)}>Disable account</button>
            : <button className="btn small" onClick={() => save({ active: true }, `${u.name} enabled.`)}>Enable account</button>)}
          {u.role === "student" && <button className="btn small danger" onClick={() => setConfirm("data")}>Delete conversations</button>}
        </div>
      </div>
      <div className="modal-foot"><button className="btn quiet" onClick={onClose}>Cancel</button><button className="btn primary" onClick={() => save(f, "Changes saved.")}>Save changes</button></div>
      {confirm === "data" && (
        <Confirm title={`Delete all of ${u.name}'s conversations?`} danger confirmLabel="Delete permanently" onClose={() => setConfirm(null)} onConfirm={async () => {
          try { const r = await api(`/api/admin/users/${u.id}/data`, { method: "DELETE" }); toast(`Deleted ${r.deleted_sessions} conversation${r.deleted_sessions === 1 ? "" : "s"}.`); onDone(); } catch (e) { setErr(e); }
        }}><p>Use this for data-deletion requests. Their transcripts, decisions and results are removed permanently. The account stays.</p></Confirm>
      )}
    </Modal>
  );
}

// ====================================================== safety review ==
function FlagList({ flags }) {
  return (
    <div>{flags.map((f) => (
      <a key={f.id} className="flag-item" href={`/flags/${f.id}`}>
        <span className={`badge ${f.severity}`}>{f.severity === "high" ? "Serious" : f.severity === "medium" ? "Medium" : "Low"}</span>
        <div style={{ minWidth: 0 }}>
          <b>{CATEGORY_LABEL[f.category] || f.category}</b><div className="muted small">{f.student?.name || "Unknown student"}, {f.scenario}</div>
          <div className="small">{f.reason}</div>
          {f.excerpt && <div className="excerpt">{f.excerpt}</div>}
        </div>
        <span className="small muted nowrap">{fmtDateTime(f.created_at)}<br />{SOURCE_LABEL[f.source]}</span>
      </a>
    ))}</div>
  );
}

export function Flags() {
  const [status, setStatus] = useState("open");
  const [severity, setSeverity] = useState("");
  const { data, error, loading, reload } = useApi(`/api/admin/flags?status=${status}${severity ? `&severity=${severity}` : ""}`);
  return (
    <div className="page">
      <PageHead title="Safety review" sub="Messages caught by automatic checks or reported by users. Serious items are listed first." />
      <div className="row between" style={{ marginBottom: 0 }}>
        <div className="tabs" role="tablist" style={{ flex: 1 }}>
          {["open", "actioned", "dismissed"].map((s) => <button key={s} role="tab" aria-selected={status === s} onClick={() => setStatus(s)}>{{ open: "To review", actioned: "Action taken", dismissed: "Dismissed" }[s]}</button>)}
        </div>
        <label className="sr-only" htmlFor="sev">Severity</label>
        <select id="sev" value={severity} onChange={(e) => setSeverity(e.target.value)} style={{ width: "auto", marginBottom: 24 }}>
          <option value="">All severities</option><option value="high">Serious</option><option value="medium">Medium</option><option value="low">Low</option>
        </select>
      </div>
      <ErrorBanner error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data?.length === 0 && <Empty title={status === "open" ? "Nothing to review" : "Nothing here yet"}>{status === "open" && "New flags appear here as soon as they're raised."}</Empty>}
      {data?.length > 0 && <div className="panel" style={{ padding: 0 }}><FlagList flags={data} /></div>}
    </div>
  );
}

export function FlagDetail({ id }) {
  const toast = useToast();
  const { data: f, error, loading, reload } = useApi(`/api/admin/flags/${id}`, [id]);
  const [note, setNote] = useState("");
  const [opts, setOpts] = useState({ hide_message: false, pause_ai: false, disable_student: false });
  const [err, setErr] = useState(null);
  useEffect(() => {
    if (f?.message_id) setTimeout(() => document.getElementById(`m${f.message_id}`)?.scrollIntoView({ block: "center" }), 100);
  }, [f?.message_id]);
  if (loading && !f) return <Loading />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  const review = async (status) => {
    try {
      await api(`/api/admin/flags/${id}/review`, { method: "POST", body: { status, note, ...(status === "actioned" ? opts : {}) } });
      toast(status === "dismissed" ? "Flag dismissed." : status === "open" ? "Flag reopened." : "Action recorded."); reload();
    } catch (e) { setErr(e); }
  };
  const anyAction = Object.values(opts).some(Boolean);
  return (
    <div className="page">
      <Breadcrumbs items={[["/flags", "Safety review"], [null, CATEGORY_LABEL[f.category] || f.category]]} />
      <PageHead title={CATEGORY_LABEL[f.category] || f.category}>
        <span className={`badge ${f.severity}`}>{f.severity === "high" ? "Serious" : f.severity === "medium" ? "Medium" : "Low"}</span>
        <Status value={f.status} />
      </PageHead>
      <div className="split">
        <div>
          {f.session ? <Script state={f.session} youLabel={f.student?.name || "Student"} highlightId={f.message_id} />
            : <div className="panel"><p className="muted">The conversation for this flag has been deleted.</p></div>}
        </div>
        <aside className="stack">
          <div className="panel tight stack">
            <div><span className="label">Why it was flagged</span><p style={{ margin: 0 }}>{f.reason}</p></div>
            <div className="small muted">{SOURCE_LABEL[f.source]}, {fmtDateTime(f.created_at)}</div>
            {f.excerpt && f.source === "auto_output" && <div><span className="label">Blocked AI text (never shown to the student)</span><p className="small" style={{ whiteSpace: "pre-wrap" }}>{f.excerpt}</p></div>}
            <div><span className="label">Student</span><p style={{ margin: 0 }}>{f.student?.name} {f.student && !f.student.active && <Status value="disabled" label="Disabled" />}<br /><span className="small muted">{f.student?.email}</span></p></div>
            <div><span className="label">Scenario</span><p style={{ margin: 0 }}>{f.scenario}</p></div>
            {f.related.length > 0 && <div><span className="label">Other flags in this conversation</span>
              <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>{f.related.map((r) => <li key={r.id}><a href={`/flags/${r.id}`}>{CATEGORY_LABEL[r.category]}</a> ({r.status})</li>)}</ul></div>}
          </div>
          {f.status === "open" ? (
            <div className="panel tight stack">
              <h2 style={{ fontSize: "1.05rem" }}>Your review</h2>
              <ErrorBanner error={err} />
              <Field label="Note (optional)" hint="Saved to the audit log.">{(fid) => <textarea id={fid} rows={3} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
              <fieldset style={{ border: 0, padding: 0, margin: "16px 0 0", minWidth: 0 }} className="stack">
                <legend className="label" style={{ marginBottom: 8 }}>Actions</legend>
                {f.message_id && <label className="check"><input type="checkbox" checked={opts.hide_message} onChange={(e) => setOpts({ ...opts, hide_message: e.target.checked })} /><span>Hide this message and the AI's reply from the transcript</span></label>}
                {f.session && <label className="check"><input type="checkbox" checked={opts.pause_ai} disabled={f.ai_paused} onChange={(e) => setOpts({ ...opts, pause_ai: e.target.checked })} /><span>Pause AI conversation in this session{f.ai_paused ? " (already paused)" : ""}</span></label>}
                {f.student?.active && <label className="check"><input type="checkbox" checked={opts.disable_student} onChange={(e) => setOpts({ ...opts, disable_student: e.target.checked })} /><span>Disable the student's account</span></label>}
              </fieldset>
              <div className="row">
                <button className="btn primary" onClick={() => review("actioned")}>{anyAction ? "Take action" : "Mark as handled"}</button>
                <button className="btn" onClick={() => review("dismissed")}>Dismiss</button>
              </div>
              {f.category === "self_harm" && <div className="banner warn small">Self-harm flags should also follow your school's safeguarding procedure. Contact the student's counselor or designated safeguarding lead.</div>}
            </div>
          ) : (
            <div className="panel tight">
              <p style={{ margin: 0 }}><b>{f.status === "dismissed" ? "Dismissed" : "Action taken"}</b> by {f.reviewer}, {fmtDateTime(f.reviewed_at)}</p>
              {f.review_note && <p className="small" style={{ margin: "8px 0 0" }}>{f.review_note}</p>}
              <button className="btn small" style={{ marginTop: 12 }} onClick={() => review("open")}>Reopen</button>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

// ======================================================= interactions ==
export function Interactions() {
  const [q, setQ] = useState("");
  const [flagged, setFlagged] = useState(false);
  const { data, error, loading, reload } = useApi(`/api/admin/sessions?q=${encodeURIComponent(q)}${flagged ? "&flagged=true" : ""}`);
  return (
    <div className="page">
      <PageHead title="Conversations" sub="Every student conversation with the AI, newest first." />
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="grow" style={{ minWidth: 220 }}><label htmlFor="iq" className="sr-only">Search</label>
          <input id="iq" type="search" placeholder="Search by student or scenario" value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <label className="check"><input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} /><span>Flagged only</span></label>
      </div>
      <ErrorBanner error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data?.length === 0 && <Empty title="No conversations found" />}
      {data?.length > 0 && (
        <div className="table-wrap"><table>
          <thead><tr><th>Student</th><th>Scenario</th><th>Status</th><th className="num">Messages</th><th>Flags</th><th>Last activity</th><th><span className="sr-only">Open</span></th></tr></thead>
          <tbody>{data.map((s) => (
            <tr key={s.session_id}>
              <td>{s.student}<div className="small muted">{s.student_email}</div></td><td>{s.scenario}</td>
              <td><Status value={s.status} />{s.ai_paused && <> <span className="badge warn plain">AI paused</span></>}</td>
              <td className="num">{s.turns}</td>
              <td>{s.flags ? <span className={`badge ${s.open_flags ? "high" : "dismissed"}`}>{s.open_flags ? `${s.open_flags} open` : `${s.flags} reviewed`}</span> : <span className="muted">–</span>}</td>
              <td className="nowrap small">{fmtDateTime(s.updated_at)}</td>
              <td><a href={`/sessions/${s.session_id}`}>Open</a></td>
            </tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

// Teacher + admin view of one conversation.
export function SessionView({ id }) {
  const { user } = useAuth();
  const toast = useToast();
  const { data: s, error, loading, reload } = useApi(`/api/sessions/${id}`, [id]);
  const [reporting, setReporting] = useState(null);
  const [err, setErr] = useState(null);
  if (loading && !s) return <Loading />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  const isAdmin = user.role === "admin";
  const name = s.student_name || "Student";
  const setHidden = async (m, hidden) => {
    try { await api(`/api/admin/messages/${m.id}/hide`, { method: "POST", body: { hidden } }); toast(hidden ? "Message hidden." : "Message restored."); reload(); }
    catch (e) { setErr(e); }
  };
  const pause = async (paused) => {
    try { await api(`/api/admin/sessions/${s.id}/pause`, { method: "POST", body: { paused } }); toast(paused ? "AI paused for this session." : "AI resumed."); reload(); }
    catch (e) { setErr(e); }
  };
  return (
    <div className="page">
      <Breadcrumbs items={isAdmin ? [["/interactions", "Conversations"], [null, name]] : [["/scenarios", "Scenarios"], [`/scenarios/${s.scenario.id}/results`, "Results"], [null, name]]} />
      <PageHead title={s.scenario.title} sub={`${name}. Attempt ${s.attempt}, ${s.turns} message${s.turns === 1 ? "" : "s"}.`}>
        <Status value={s.status} />
        {s.outcome && <span className={`badge ${s.outcome.type}`}>{OUTCOME_LABEL[s.outcome.type]}: {s.outcome.label}</span>}
        {isAdmin && s.status === "in_progress" && <button className="btn small" onClick={() => pause(!s.ai_paused)}>{s.ai_paused ? "Resume AI" : "Pause AI"}</button>}
      </PageHead>
      <ErrorBanner error={err} />
      <div className="split">
        <Script state={s} youLabel={name} tools={(m) => m.role !== "system" && (isAdmin
          ? <button className="btn quiet small" onClick={() => setHidden(m, !m.hidden)}>{m.hidden ? "Restore" : "Hide"}</button>
          : m.role === "assistant" && <button className="btn quiet small" onClick={() => setReporting(m)}>Report</button>)} />
        <aside className="stack">
          <div className="panel tight">
            <span className="label">Decisions</span>
            {s.path.length === 0 ? <p className="small muted" style={{ margin: 0 }}>None yet.</p> :
              <ol className="small" style={{ margin: "6px 0 0", paddingLeft: 18 }}>{s.path.map((p, i) => <li key={i}><span className="muted">{p.node_title}:</span> {p.choice}</li>)}</ol>}
          </div>
          {s.outcome?.ai_feedback && <div className="panel tight"><span className="label">Feedback the student saw</span><p className="small" style={{ margin: "6px 0 0" }}>{s.outcome.ai_feedback}</p></div>}
          {!isAdmin && <p className="small muted">See something concerning? Hover a character's line and choose Report to send it to an administrator.</p>}
        </aside>
      </div>
      {reporting && <ReportDialog sessionId={s.id} message={reporting} onClose={() => setReporting(null)} />}
    </div>
  );
}

// =============================================================== audit ==
export function Audit() {
  const { data, error, loading, reload } = useApi("/api/admin/audit");
  return (
    <div className="page">
      <PageHead title="Audit log" sub="Significant administrative actions, newest first." />
      <ErrorBanner error={error} onRetry={reload} />
      {loading && !data && <Loading />}
      {data && (
        <div className="table-wrap"><table>
          <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
          <tbody>{data.map((a) => (
            <tr key={a.id}><td className="nowrap small">{fmtDateTime(a.created_at)}</td><td>{a.actor}</td><td><code>{a.action}</code></td><td className="small">{a.target}</td>
              <td className="small muted">{Object.entries(a.detail || {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(" → ") : v}`).join("; ")}</td></tr>))}</tbody>
        </table></div>
      )}
    </div>
  );
}

export function SystemStatus() {
  const { data: s, error, reload } = useApi("/api/admin/stats");
  return (
    <div className="page">
      <PageHead title="System status" sub="Health of the application and the AI service. Student conversations aren't visible to IT support." />
      <ErrorBanner error={error} onRetry={reload} />
      {s && <div className="figures">
        <a className="figure" href="/ai"><b>{s.ai_state === "ok" ? "Connected" : s.ai_state === "error" ? "Failing" : s.ai_state === "demo" ? "Demo mode" : "Not yet used"}</b><span>AI connection ({s.model})</span></a>
        <div className="figure"><b>{s.ai_last_24h.replies}</b><span>AI replies, last 24h</span></div>
        <div className="figure"><b>{s.ai_last_24h.avg_latency_ms != null ? `${(s.ai_last_24h.avg_latency_ms / 1000).toFixed(2)}s` : "–"}</b><span>avg. reply time</span></div>
        <div className="figure"><b>{(s.ai_last_24h.input_tokens + s.ai_last_24h.output_tokens).toLocaleString()}</b><span>tokens used, last 24h</span></div>
        <div className="figure"><b>{s.sessions_active}</b><span>active sessions</span></div>
        <div className="figure"><b>{s.ai_review ? "On" : "Off"}</b><span>background AI safety review</span></div>
      </div>}
      <Audit />
    </div>
  );
}
