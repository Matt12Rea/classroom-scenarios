// Teacher home, scenario list, results/analytics (SRS 3.5), and classes.
import { useState } from "react";
import { api, downloadFile, fmtDate, fmtDateTime, navigate, useApi, useAuth, useToast } from "../../lib.jsx";
import { Breadcrumbs, Confirm, Empty, ErrorBanner, Field, Loading, Modal, PageHead, Status } from "../../ui.jsx";

export function TeacherHome() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi("/api/teacher/overview");
  return (
    <div className="page">
      <PageHead title={`Welcome back, ${user.name.split(" ")[0]}`} sub="Recent student activity across your scenarios.">
        <NewScenarioButton primary />
      </PageHead>
      <ErrorBanner error={error} onRetry={reload} />
      {loading && <Loading />}
      {data && <>
        <div className="figures">
          <div className="figure"><b>{data.scenarios.published || 0}</b><span>published scenarios</span></div>
          <div className="figure"><b>{data.scenarios.draft || 0}</b><span>drafts</span></div>
          <div className="figure"><b>{data.in_progress}</b><span>students mid-scenario</span></div>
          <div className="figure"><b>{data.completed}</b><span>completed attempts</span></div>
        </div>
        <div className="panel">
          <div className="panel-head"><h2>Recent activity</h2><a href="/scenarios">All scenarios</a></div>
          {data.recent.length === 0 ? <Empty title="No activity yet">Assign a published scenario to a class and student activity will show up here.</Empty> : (
            <div className="table-wrap" style={{ border: 0 }}>
              <table>
                <thead><tr><th>Student</th><th>Scenario</th><th>Status</th><th>Outcome</th><th>Last activity</th><th><span className="sr-only">Open</span></th></tr></thead>
                <tbody>{data.recent.map((r) => (
                  <tr key={r.session_id}>
                    <td>{r.student}</td><td>{r.scenario}</td><td><Status value={r.status} /></td>
                    <td>{r.outcome_type ? <span className={`badge ${r.outcome_type}`}>{r.outcome}</span> : <span className="muted">–</span>}</td>
                    <td className="nowrap">{fmtDateTime(r.updated_at)}</td>
                    <td><a href={`/sessions/${r.session_id}`}>Conversation</a></td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </div>
      </>}
    </div>
  );
}

function NewScenarioButton({ primary }) {
  const [open, setOpen] = useState(false);
  const [err, setErr] = useState(null);
  const create = async (template) => {
    try { const r = await api("/api/scenarios", { method: "POST", body: { template } }); navigate(`/scenarios/${r.id}`); }
    catch (e) { setErr(e); }
  };
  return <>
    <button className={`btn ${primary ? "primary" : ""}`} onClick={() => setOpen(true)}>Create scenario</button>
    {open && (
      <Modal title="Create a scenario" onClose={() => setOpen(false)}>
        <ErrorBanner error={err} />
        <div className="stack">
          <button className="choice" onClick={() => create("blank")}><span>Start from scratch<br /><span className="small muted" style={{ fontWeight: 400 }}>An empty scenario with standard safety boundaries.</span></span></button>
          <button className="choice" onClick={() => create("example")}><span>Start from an example<br /><span className="small muted" style={{ fontWeight: 400 }}>A finished conflict-resolution scenario you can edit to see how it fits together.</span></span></button>
        </div>
        <div className="modal-foot"><button className="btn quiet" onClick={() => setOpen(false)}>Cancel</button></div>
      </Modal>
    )}
  </>;
}

export function ScenarioList() {
  const { user } = useAuth();
  const { data, error, loading, reload } = useApi("/api/scenarios");
  const [filter, setFilter] = useState("active");
  const list = data?.filter((s) => (filter === "active" ? s.status !== "archived" : s.status === "archived"));
  return (
    <div className="page">
      <PageHead title="Scenarios" sub={user.role === "admin" ? "Every scenario in the school." : "Scenarios you've created."}>
        <NewScenarioButton primary />
      </PageHead>
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={filter === "active"} onClick={() => setFilter("active")}>Active</button>
        <button role="tab" aria-selected={filter === "archived"} onClick={() => setFilter("archived")}>Archived</button>
      </div>
      <ErrorBanner error={error} onRetry={reload} />
      {loading && <Loading />}
      {list && list.length === 0 && <Empty title={filter === "active" ? "No scenarios yet" : "Nothing archived"}>{filter === "active" && "Create your first scenario, or start from the example to see how one works."}</Empty>}
      {list && list.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Title</th><th>Status</th><th>Assigned to</th><th className="num">Scenes</th><th className="num">Attempts</th><th>Updated</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody>{list.map((s) => (
              <tr key={s.id}>
                <td><a href={`/scenarios/${s.id}`}><b>{s.title}</b></a>{user.role === "admin" && <div className="small muted">{s.owner_name}</div>}</td>
                <td><Status value={s.status} /></td>
                <td className="small">{s.assignments.map((a) => a.class_name).join(", ") || <span className="muted">Not assigned</span>}</td>
                <td className="num">{s.scene_count}</td><td className="num">{s.sessions}</td>
                <td className="nowrap">{fmtDate(s.updated_at)}</td>
                <td className="nowrap"><a className="btn small" href={`/scenarios/${s.id}`}>Edit</a> <a className="btn small" href={`/scenarios/${s.id}/results`}>Results</a></td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function Results({ id }) {
  const { data: classes } = useApi("/api/classes");
  const [f, setF] = useState({ class_id: "", from: "", to: "" });
  const qs = new URLSearchParams(Object.entries({ ...f, from: f.from && new Date(f.from).toISOString(), to: f.to && new Date(f.to + "T23:59:59").toISOString() }).filter(([, v]) => v)).toString();
  const { data, error, loading, reload } = useApi(`/api/scenarios/${id}/analytics${qs ? "?" + qs : ""}`);
  const [exportErr, setExportErr] = useState(null);

  return (
    <div className="page">
      <Breadcrumbs items={[["/scenarios", "Scenarios"], [`/scenarios/${id}`, data?.scenario.title || "Scenario"], [null, "Results"]]} />
      <PageHead title={data ? `Results: ${data.scenario.title}` : "Results"}>
        <button className="btn" onClick={() => downloadFile(`/api/scenarios/${id}/export.csv${qs ? "?" + qs : ""}`, "results.csv").catch(setExportErr)}>Export CSV</button>
      </PageHead>
      <div className="panel tight row" style={{ marginBottom: 20, alignItems: "flex-end" }}>
        <Field label="Class">{(fid) => (
          <select id={fid} value={f.class_id} onChange={(e) => setF({ ...f, class_id: e.target.value })}>
            <option value="">All my classes</option>{classes?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>)}</Field>
        <Field label="Started from">{(fid) => <input id={fid} type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} />}</Field>
        <Field label="to">{(fid) => <input id={fid} type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} />}</Field>
        {(f.class_id || f.from || f.to) && <button className="btn quiet" onClick={() => setF({ class_id: "", from: "", to: "" })}>Clear filters</button>}
      </div>
      <ErrorBanner error={error || exportErr} onRetry={error ? reload : null} />
      {loading && <Loading />}
      {data && <ResultsBody data={data} />}
    </div>
  );
}

function ResultsBody({ data }) {
  const s = data.summary;
  const pct = (n) => (s.completed ? (n / s.completed) * 100 : 0);
  if (s.assigned === 0) return <Empty title="No students to report on">Assign this scenario to a class with students, or clear the filters.</Empty>;
  return <>
    <div className="figures">
      <div className="figure"><b>{s.started} / {s.assigned}</b><span>students started</span></div>
      <div className="figure"><b>{s.completed}</b><span>finished</span></div>
      <div className="figure"><b>{s.avg_turns ?? "–"}</b><span>avg. messages to finish</span></div>
      <div className="figure"><b>{s.avg_minutes != null ? `${s.avg_minutes} min` : "–"}</b><span>avg. time to finish</span></div>
    </div>
    <div className="grid-2" style={{ marginBottom: 20 }}>
      <div className="panel">
        <h2>Endings reached</h2>
        <p className="small muted" style={{ margin: "4px 0 12px" }}>Each student's latest attempt.</p>
        {s.completed === 0 ? <p className="muted">No one has finished yet.</p> : <>
          <div className="bar" role="img" aria-label={`${s.success} success, ${s.partial} partial, ${s.fail} didn't succeed`}>
            <span className="success" style={{ width: `${pct(s.success)}%` }} /><span className="partial" style={{ width: `${pct(s.partial)}%` }} /><span className="fail" style={{ width: `${pct(s.fail)}%` }} />
          </div>
          <div className="legend"><span><i style={{ background: "var(--ok)" }} />Success {s.success}</span><span><i style={{ background: "var(--pencil)" }} />Partial {s.partial}</span><span><i style={{ background: "var(--bad)" }} />Didn't succeed {s.fail}</span></div>
          <ul style={{ marginTop: 12, paddingLeft: 18 }}>{data.outcomes.map((o) => <li key={o.label}>{o.label}: <b>{o.count}</b></li>)}</ul>
        </>}
      </div>
      <div className="panel">
        <h2>Decisions made</h2>
        <p className="small muted" style={{ margin: "4px 0 12px" }}>Across all attempts.</p>
        {data.decisions.map((dn) => {
          const total = dn.choices.reduce((a, c) => a + c.count, 0);
          return (
            <div key={dn.node} style={{ marginBottom: 14 }}>
              <h3 style={{ fontSize: "0.95rem" }}>{dn.node_title}</h3>
              {total === 0 ? <p className="small muted">No one reached this decision.</p> : dn.choices.map((c) => (
                <div className="hbar" key={c.label}>
                  <span className="small">{c.label}</span>
                  <span className="track" aria-hidden="true"><span style={{ width: `${(c.count / total) * 100}%` }} /></span>
                  <span className="small num">{c.count}</span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
    <h2 style={{ marginBottom: 12 }}>Students</h2>
    <div className="table-wrap">
      <table>
        <thead><tr><th>Student</th><th>Class</th><th>Status</th><th>Outcome</th><th className="num">Messages</th><th className="num">Attempts</th><th>Last activity</th><th><span className="sr-only">Open</span></th></tr></thead>
        <tbody>{data.students.map((r) => (
          <tr key={r.student_id}>
            <td>{r.name}{r.flags > 0 && <> <span className="badge high" title="Has safety flags">{r.flags} flag{r.flags > 1 ? "s" : ""}</span></>}</td>
            <td className="small">{r.class_name}</td>
            <td><Status value={r.status} /></td>
            <td>{r.outcome_type ? <span className={`badge ${r.outcome_type}`}>{r.outcome}</span> : <span className="muted">–</span>}</td>
            <td className="num">{r.turns}</td><td className="num">{r.attempts}</td>
            <td className="nowrap">{fmtDateTime(r.last_activity)}</td>
            <td>{r.session_id && <a href={`/sessions/${r.session_id}`}>Conversation</a>}</td>
          </tr>))}</tbody>
      </table>
    </div>
  </>;
}

export function Classes() {
  const { user } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useApi("/api/classes");
  const { data: teachers } = useApi(user.role === "admin" ? "/api/admin/users?role=teacher" : null);
  const [creating, setCreating] = useState(false);
  const [adding, setAdding] = useState(null);
  const [removing, setRemoving] = useState(null);
  const [err, setErr] = useState(null);

  return (
    <div className="page">
      <PageHead title="Classes" sub={user.role === "admin" ? "Every class in the school and its teacher." : "Your classes and the students in them."}>
        <button className="btn primary" onClick={() => setCreating(true)}>Create class</button>
      </PageHead>
      <ErrorBanner error={error || err} onRetry={error ? reload : null} />
      {loading && <Loading />}
      {data?.length === 0 && <Empty title="No classes yet">Create a class, then add students to it so you can assign scenarios.</Empty>}
      <div className="stack">
        {data?.map((c) => (
          <section className="panel" key={c.id}>
            <div className="panel-head">
              <div><h2>{c.name}</h2>{user.role === "admin" && <span className="small muted">{c.teacher_name || "No teacher"}</span>}</div>
              <div className="row">
                <button className="btn small" onClick={() => setAdding(c)}>Add students</button>
                <button className="btn quiet small" onClick={() => setRemoving({ kind: "class", c })}>Delete class</button>
              </div>
            </div>
            {c.students.length === 0 ? <p className="muted">No students yet.</p> : (
              <div className="table-wrap"><table>
                <thead><tr><th>Name</th><th>Email</th><th><span className="sr-only">Actions</span></th></tr></thead>
                <tbody>{c.students.map((s) => (
                  <tr key={s.id}><td>{s.name}{!s.active && <> <Status value="disabled" label="Disabled" /></>}</td><td className="small">{s.email}</td>
                    <td className="num"><button className="btn quiet small" onClick={() => setRemoving({ kind: "student", c, s })}>Remove</button></td></tr>))}
                </tbody>
              </table></div>
            )}
          </section>
        ))}
      </div>
      {creating && <CreateClass teachers={teachers} isAdmin={user.role === "admin"} onClose={() => setCreating(false)} onDone={() => { reload(); toast("Class created."); }} />}
      {adding && <AddStudents cls={adding} onClose={() => setAdding(null)} onDone={reload} />}
      {removing?.kind === "student" && (
        <Confirm title={`Remove ${removing.s.name}?`} confirmLabel="Remove from class" onClose={() => setRemoving(null)} onConfirm={async () => {
          try { await api(`/api/classes/${removing.c.id}/students/${removing.s.id}`, { method: "DELETE" }); toast("Student removed."); reload(); } catch (e) { setErr(e); }
        }}><p>They'll stop seeing scenarios assigned to {removing.c.name}. Their past results are kept.</p></Confirm>
      )}
      {removing?.kind === "class" && (
        <Confirm title={`Delete ${removing.c.name}?`} danger confirmLabel="Delete class" onClose={() => setRemoving(null)} onConfirm={async () => {
          try { await api(`/api/classes/${removing.c.id}`, { method: "DELETE" }); toast("Class deleted."); reload(); } catch (e) { setErr(e); }
        }}><p>Students stay in the system and keep their results, but lose access to scenarios assigned through this class.</p></Confirm>
      )}
    </div>
  );
}

function CreateClass({ teachers, isAdmin, onClose, onDone }) {
  const [name, setName] = useState("");
  const [teacher, setTeacher] = useState("");
  const [err, setErr] = useState(null);
  const submit = async () => {
    try { await api("/api/classes", { method: "POST", body: { name, teacher_id: teacher ? Number(teacher) : null } }); onDone(); onClose(); }
    catch (e) { setErr(e); }
  };
  return (
    <Modal title="Create class" onClose={onClose}>
      <ErrorBanner error={err} />
      <div className="stack">
        <Field label="Class name">{(fid) => <input id={fid} type="text" value={name} placeholder="Period 3 – English 10" onChange={(e) => setName(e.target.value)} />}</Field>
        {isAdmin && <Field label="Teacher">{(fid) => (
          <select id={fid} value={teacher} onChange={(e) => setTeacher(e.target.value)}>
            <option value="">Choose a teacher…</option>{teachers?.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>)}</Field>}
      </div>
      <div className="modal-foot"><button className="btn quiet" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!name.trim()} onClick={submit}>Create class</button></div>
    </Modal>
  );
}

function AddStudents({ cls, onClose, onDone }) {
  const toast = useToast();
  const [text, setText] = useState("");
  const [err, setErr] = useState(null);
  const [result, setResult] = useState(null);
  const submit = async () => {
    try {
      const r = await api(`/api/classes/${cls.id}/students`, { method: "POST", body: { emails: text.split(/[\s,;]+/).filter(Boolean) } });
      setResult(r); onDone();
      if (!r.not_found.length) { toast(`Added ${r.added.length} student${r.added.length === 1 ? "" : "s"}.`); onClose(); }
    } catch (e) { setErr(e); }
  };
  return (
    <Modal title={`Add students to ${cls.name}`} onClose={onClose}>
      <ErrorBanner error={err} />
      {result?.not_found.length > 0 && (
        <div className="banner warn">Added {result.added.length}. These emails don't match a student account, so ask an administrator to create them:
          <ul>{result.not_found.map((e) => <li key={e}>{e}</li>)}</ul></div>
      )}
      <Field label="Student emails" hint="Paste one or more, separated by commas, spaces or new lines.">
        {(fid) => <textarea id={fid} rows={5} value={text} onChange={(e) => setText(e.target.value)} placeholder="maya@school.edu, leo@school.edu" />}
      </Field>
      <div className="modal-foot"><button className="btn quiet" onClick={onClose}>Close</button><button className="btn primary" disabled={!text.trim()} onClick={submit}>Add students</button></div>
    </Modal>
  );
}

