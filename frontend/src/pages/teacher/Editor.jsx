// Scenario builder (SRS 3.1, UC-01). Form-based so no programming is needed.
import { useEffect, useMemo, useRef, useState } from "react";
import FlowMap from "../../components/FlowMap.jsx";
import { api, fmtDate, navigate, useApi, useToast } from "../../lib.jsx";
import { Breadcrumbs, Confirm, ErrorBanner, Field, ListEditor, Loading, Status } from "../../ui.jsx";

const TABS = [
  { id: "basics", label: "Basics", fields: ["title", "setting", "objectives", "boundaries"] },
  { id: "characters", label: "Characters", fields: ["characters"] },
  { id: "scenes", label: "Scenes", fields: ["nodes", "start"] },
  { id: "review", label: "Review & publish", fields: [] },
];

function newId(prefix, taken) {
  let i = 1;
  while (taken.includes(`${prefix}_${i}`)) i++;
  return `${prefix}_${i}`;
}

export default function Editor({ id }) {
  const toast = useToast();
  const { data, error, loading, reload } = useApi(`/api/scenarios/${id}`, [id]);
  const [sc, setSc] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("basics");
  const [scene, setScene] = useState(null);
  const [v, setV] = useState({ errors: [], warnings: [] });
  const [busy, setBusy] = useState("");
  const [actionErr, setActionErr] = useState(null);
  const [confirm, setConfirm] = useState(null);

  useEffect(() => {
    if (data) {
      setSc({ title: data.title, description: data.description, max_turns: data.max_turns, definition: data.definition });
      setV(data.validation); setDirty(false);
      setScene((s) => s && data.definition.nodes[s] ? s : data.definition.start || Object.keys(data.definition.nodes)[0]);
    }
  }, [data]);

  // Live validation while editing (debounced).
  const timer = useRef();
  useEffect(() => {
    if (!sc || !dirty) return;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api("/api/scenarios/validate", { method: "POST", body: { title: sc.title, definition: sc.definition } }).then(setV).catch(() => {});
    }, 500);
    return () => clearTimeout(timer.current);
  }, [sc, dirty]);

  useEffect(() => {
    const warn = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const errFor = useMemo(() => {
    const m = {};
    v.errors.forEach((e) => { m[e.field] ||= e.message; });
    return (f) => m[f];
  }, [v]);
  const tabErrors = (t) => v.errors.filter((e) => t.fields.some((f) => e.field === f || e.field.startsWith(f + "."))).length;

  if (loading && !sc) return <Loading label="Loading scenario…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!sc) return null;

  const d = sc.definition;
  const set = (patch) => { setSc((s) => ({ ...s, ...patch })); setDirty(true); };
  const setDef = (patch) => set({ definition: { ...sc.definition, ...patch } });
  const setNode = (nid, patch) => setDef({ nodes: { ...d.nodes, [nid]: { ...d.nodes[nid], ...patch } } });

  async function save({ quiet } = {}) {
    setBusy("save"); setActionErr(null);
    try {
      const r = await api(`/api/scenarios/${id}`, { method: "PUT", body: sc });
      setV(r.validation); setDirty(false);
      if (!quiet) toast("Draft saved.");
      return r;
    } catch (e) { setActionErr(e); throw e; } finally { setBusy(""); }
  }
  async function act(kind) {
    setActionErr(null);
    try {
      if (dirty) await save({ quiet: true });
      setBusy(kind);
      if (kind === "preview") {
        const st = await api("/api/sessions", { method: "POST", body: { scenario_id: Number(id), preview: true } });
        navigate(`/preview/${st.id}`); return;
      }
      await api(`/api/scenarios/${id}/${kind}`, { method: "POST" });
      toast({ publish: "Published. Students in assigned courses can now see it.", unpublish: "Unpublished. It's a draft again.", archive: "Archived." }[kind]);
      reload();
    } catch (e) {
      setActionErr(e);
      if (kind === "publish" && e.errors?.length) setTab("review");
    } finally { setBusy(""); }
  }
  async function duplicate() {
    try { const r = await api(`/api/scenarios/${id}/duplicate`, { method: "POST" }); toast("Copy created."); navigate(`/scenarios/${r.id}`); }
    catch (e) { setActionErr(e); }
  }

  function jump(field) {
    const parts = field.split(".");
    if (parts[0] === "nodes" && parts[1]) { setTab("scenes"); setScene(parts[1]); }
    else setTab(TABS.find((t) => t.fields.includes(parts[0]))?.id || "basics");
  }

  return (
    <div className="page">
      <div className="editor-bar">
        <div>
          <Breadcrumbs items={[["/scenarios", "Scenarios"], [null, sc.title || "Untitled scenario"]]} />
          <div className="row" style={{ marginTop: 6 }}>
            <h1>{sc.title || "Untitled scenario"}</h1>
            <Status value={data.status} />
            {dirty && <span className="small muted">Unsaved changes</span>}
          </div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => save()} disabled={!!busy || !dirty}>{busy === "save" ? "Saving…" : "Save draft"}</button>
          <button className="btn" onClick={() => act("preview")} disabled={!!busy}>Preview as student</button>
          {data.status === "published"
            ? <button className="btn" onClick={() => act("unpublish")} disabled={!!busy}>Unpublish</button>
            : <button className="btn primary" onClick={() => act("publish")} disabled={!!busy}>{busy === "publish" ? "Publishing…" : "Publish"}</button>}
        </div>
      </div>
      <ErrorBanner error={actionErr} />

      <div className="tabs" role="tablist" aria-label="Scenario sections">
        {TABS.map((t, i) => {
          const n = tabErrors(t);
          return (
            <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}>
              <span className={`step ${n ? "err" : ""}`} aria-hidden="true">{i + 1}</span>{t.label}
              {n > 0 && <span className="sr-only">({n} problems)</span>}
            </button>
          );
        })}
      </div>

      {tab === "basics" && (
        <div className="panel stack" role="tabpanel">
          <Field label="Title" error={errFor("title")}>{(fid) => <input id={fid} type="text" value={sc.title} onChange={(e) => set({ title: e.target.value })} />}</Field>
          <Field label="Short description" hint="Shown on students' scenario list.">{(fid) => <textarea id={fid} rows={2} value={sc.description} onChange={(e) => set({ description: e.target.value })} />}</Field>
          <Field label="Setting" hint="Where and when, and who the student plays." error={errFor("setting")}>
            {(fid) => <textarea id={fid} rows={3} value={d.setting} placeholder="A community bank in Iowa as the Fed raises rates. You are a junior analyst advising the bank's president." onChange={(e) => setDef({ setting: e.target.value })} />}
          </Field>
          <div className={`field ${errFor("objectives") ? "invalid" : ""}`}>
            <span className="label">Learning objectives</span>
            <span className="hint">Shown to students and used for feedback.</span>
            <ListEditor items={d.objectives} onChange={(objectives) => setDef({ objectives })} placeholder="Objective" addLabel="Add objective" invalid />
            {errFor("objectives") && <span className="error-text">{errFor("objectives")}</span>}
          </div>
          <div className="field">
            <span className="label">Boundaries for the AI</span>
            <span className="hint">Rules every character follows, on top of the standard safety rules.</span>
            <ListEditor items={d.boundaries} onChange={(boundaries) => setDef({ boundaries })} placeholder="Boundary" addLabel="Add boundary" />
          </div>
          <Field label="Feedback focus" hint="Guides the AI's end-of-scenario debrief.">
            {(fid) => <textarea id={fid} rows={2} value={d.feedback_guidance} placeholder="Did the student identify the bank's interest-rate risk and propose a realistic way to manage it?" onChange={(e) => setDef({ feedback_guidance: e.target.value })} />}
          </Field>
          <div className="grid-2">
            <Field label="Message limit" hint="Per attempt. When it runs out, the scenario wraps up.">
              {(fid) => <input id={fid} type="number" min={1} max={200} value={sc.max_turns} style={{ maxWidth: 140 }} onChange={(e) => set({ max_turns: Number(e.target.value) || 1 })} />}
            </Field>
            <SceneLength d={d} setDef={setDef} />
          </div>
        </div>
      )}

      {tab === "characters" && (
        <div className="stack" role="tabpanel">
          {errFor("characters") && <div className="banner error">{errFor("characters")}</div>}
          {d.characters.map((c, i) => {
            const upd = (patch) => setDef({ characters: d.characters.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
            const used = Object.values(d.nodes).some((n) => n.character === c.id);
            return (
              <div className="char-card stack" key={c.id}>
                <div className="grid-2">
                  <Field label="Name" error={errFor(`characters.${i}.name`)}>{(fid) => <input id={fid} type="text" value={c.name} placeholder="Carol Brennan" onChange={(e) => upd({ name: e.target.value })} />}</Field>
                  <Field label="Who they are" error={errFor(`characters.${i}.role`)}>{(fid) => <input id={fid} type="text" value={c.role} placeholder="the bank's president" onChange={(e) => upd({ role: e.target.value })} />}</Field>
                </div>
                <Field label="Personality and background" hint="How they talk, and what makes them open up or shut down.">
                  {(fid) => <textarea id={fid} rows={3} value={c.traits} placeholder="Practical, not an economist. Wants plain English and a concrete numerical example." onChange={(e) => upd({ traits: e.target.value })} />}
                </Field>
                <div className="row end">
                  <button className="btn danger small" disabled={used} title={used ? "Used in a scene. Change those scenes first." : ""}
                    onClick={() => setDef({ characters: d.characters.filter((_, j) => j !== i) })}>Remove character</button>
                </div>
              </div>
            );
          })}
          <div><button className="btn" onClick={() => {
            const cid = newId("character", d.characters.map((c) => c.id));
            setDef({ characters: [...d.characters, { id: cid, name: "", role: "", traits: "" }] });
          }}>Add character</button></div>
        </div>
      )}

      {tab === "scenes" && (
        <ScenesTab d={d} setDef={setDef} setNode={setNode} scene={scene} setScene={setScene} errFor={errFor} errors={v.errors} />
      )}

      {tab === "review" && (
        <div className="stack" role="tabpanel">
          <div className="panel">
            <div className="panel-head"><h2>Scenario map</h2><span className="small muted">Click a scene to edit it. Dashed scenes can't be reached.</span></div>
            <FlowMap def={d} onSelect={(nid) => { setScene(nid); setTab("scenes"); }} />
          </div>
          <div className="panel">
            <h2 style={{ marginBottom: 12 }}>Checks</h2>
            {v.errors.length === 0 && v.warnings.length === 0 && <div className="banner ok">No problems found. Preview it, then publish.</div>}
            {v.errors.length > 0 && (
              <div className="banner error"><b>Fix before publishing</b>
                <ul className="issues">{v.errors.map((e, i) => <li key={i}><button onClick={() => jump(e.field)}>{e.message}</button></li>)}</ul>
              </div>
            )}
            {v.warnings.length > 0 && (
              <div className="banner warn"><b>Worth a look</b>
                <ul className="issues">{v.warnings.map((e, i) => <li key={i}><button onClick={() => jump(e.field)}>{e.message}</button></li>)}</ul>
              </div>
            )}
            <div className="row">
              <button className="btn" onClick={() => act("preview")} disabled={!!busy}>Preview as student</button>
              {data.status !== "published" && <button className="btn primary" onClick={() => act("publish")} disabled={!!busy || v.errors.length > 0}>Publish</button>}
            </div>
          </div>
          <AssignPanel scenario={data} onChange={reload} />
          <div className="panel">
            <h2 style={{ marginBottom: 12 }}>More</h2>
            <div className="row">
              <button className="btn" onClick={duplicate}>Duplicate</button>
              {data.sessions > 0 && <a className="btn" href={`/scenarios/${id}/results`}>View results</a>}
              {data.status !== "archived" && <button className="btn" onClick={() => setConfirm("archive")}>Archive</button>}
              <button className="btn danger" onClick={() => setConfirm("delete")}>Delete</button>
            </div>
          </div>
        </div>
      )}

      {confirm === "archive" && (
        <Confirm title="Archive this scenario?" confirmLabel="Archive" onClose={() => setConfirm(null)} onConfirm={() => act("archive")}>
          <p>Students won't see it anymore. Their results are kept and you can still view them.</p>
        </Confirm>
      )}
      {confirm === "delete" && (
        <Confirm title="Delete this scenario?" confirmLabel="Delete" danger onClose={() => setConfirm(null)} onConfirm={async () => {
          try { await api(`/api/scenarios/${id}`, { method: "DELETE" }); toast("Scenario deleted."); navigate("/scenarios"); }
          catch (e) { setActionErr(e); }
        }}>
          <p>This can't be undone. If students have already played it, archive it instead.</p>
        </Confirm>
      )}
    </div>
  );
}

function ScenesTab({ d, setDef, setNode, scene, setScene, errFor, errors }) {
  const ids = Object.keys(d.nodes);
  const nid = d.nodes[scene] ? scene : ids[0];
  const n = d.nodes[nid];
  const sceneHasErr = (id) => errors.some((e) => e.field.startsWith(`nodes.${id}.`) || e.field === `nodes.${id}`);

  const addScene = (from) => {
    const id = newId("scene", ids);
    const nodes = { ...d.nodes, [id]: { title: `Scene ${ids.length + 1}`, prompt: "", character: d.characters[0]?.id || "", min_turns: 1, wrap_after: 8, choices: [], ending: null } };
    setDef({ nodes, start: d.start || id });
    setScene(id);
    return { id, nodes, from };
  };
  const removeScene = (id) => {
    const nodes = { ...d.nodes };
    delete nodes[id];
    Object.values(nodes).forEach((x) => { x.choices = (x.choices || []).map((c) => (c.next === id ? { ...c, next: "" } : c)); });
    setDef({ nodes, start: d.start === id ? Object.keys(nodes)[0] || "" : d.start });
    setScene(d.start === id ? Object.keys(nodes)[0] : d.start);
  };
  const setChoice = (j, patch) => setNode(nid, { choices: n.choices.map((c, k) => (k === j ? { ...c, ...patch } : c)) });

  if (!n) return <div className="panel"><button className="btn primary" onClick={() => addScene()}>Add the first scene</button></div>;

  return (
    <div className="scenes" role="tabpanel">
      <nav className="scene-list" aria-label="Scenes">
        {ids.map((id) => {
          const x = d.nodes[id];
          return (
            <button key={id} aria-current={id === nid} onClick={() => setScene(id)}>
              <span><b>{x.title || id}</b> {sceneHasErr(id) && <span className="err-dot" aria-label="has problems">●</span>}</span>
              <span className="kind">{id === d.start ? "Starting scene. " : ""}{x.ending ? `Ending (${x.ending.type})` : `${x.choices.length} path${x.choices.length === 1 ? "" : "s"}`}</span>
            </button>
          );
        })}
        <button onClick={() => addScene()} style={{ borderStyle: "dashed" }}><b>Add scene</b></button>
      </nav>

      <div className="panel stack" key={nid}>
        <div className="grid-2">
          <Field label="Scene title">{(fid) => <input id={fid} type="text" value={n.title} onChange={(e) => setNode(nid, { title: e.target.value })} />}</Field>
          <Field label="Who's speaking" error={errFor(`nodes.${nid}.character`)}>
            {(fid) => (
              <select id={fid} value={n.character} onChange={(e) => setNode(nid, { character: e.target.value })}>
                {d.characters.length === 0 && <option value="">Add a character first</option>}
                {d.characters.map((c) => <option key={c.id} value={c.id}>{c.name || "(unnamed)"}</option>)}
              </select>
            )}
          </Field>
        </div>
        <Field label="What's happening" hint="Shown when the scene opens, and given to the character." error={errFor(`nodes.${nid}.prompt`)}>
          {(fid) => <textarea id={fid} rows={3} value={n.prompt} onChange={(e) => setNode(nid, { prompt: e.target.value })} />}
        </Field>

        <div className="field">
          <span className="label">This scene…</span>
          <div className="seg" role="radiogroup" aria-label="Scene type">
            <label><input type="radio" name="kind" checked={!n.ending} onChange={() => setNode(nid, { ending: null })} />branches on what the student does</label>
            <label><input type="radio" name="kind" checked={!!n.ending} onChange={() => setNode(nid, { ending: { label: "", type: "success", feedback: "" }, choices: [] })} />is an ending</label>
          </div>
        </div>

        {!n.ending && <>
          <div className="grid-2">
            <Field label="Minimum messages" hint="Before the scene can move on." error={errFor(`nodes.${nid}.min_turns`)}>
              {(fid) => <input id={fid} type="number" min={0} max={20} value={n.min_turns} style={{ maxWidth: 120 }} onChange={(e) => setNode(nid, { min_turns: Math.max(0, Number(e.target.value) || 0) })} />}
            </Field>
            <Field label="Maximum messages" hint="Then the scene wraps up. 0 for no limit." error={errFor(`nodes.${nid}.wrap_after`)}>
              {(fid) => <input id={fid} type="number" min={0} max={50} value={n.wrap_after ?? 8} style={{ maxWidth: 120 }} onChange={(e) => setNode(nid, { wrap_after: Math.max(0, Number(e.target.value) || 0) })} />}
            </Field>
          </div>
          <div className="stack" style={{ marginTop: 8 }}>
            <span className="label">Paths out of this scene</span>
            <p className="hint small muted" style={{ margin: 0 }}>Students don't see these. After each message, the AI checks whether the student has taken one. Name each path as what the student did; they'll see it when the scene moves on.</p>
            {errFor(`nodes.${nid}.choices`) && <div className="banner error">{errFor(`nodes.${nid}.choices`)}</div>}
            {n.choices.map((c, j) => (
              <div className="decision-row" key={j}>
                <Field label={`Path ${j + 1}`} error={errFor(`nodes.${nid}.choices.${j}.label`)}>
                  {(fid) => <input id={fid} type="text" value={c.label} placeholder="Explained the bank's interest-rate risk" onChange={(e) => setChoice(j, { label: e.target.value })} />}
                </Field>
                <Field label="Leads to" error={errFor(`nodes.${nid}.choices.${j}.next`) ? "Pick a scene" : null}>
                  {(fid) => (
                    <select id={fid} value={c.next} onChange={(e) => {
                      if (e.target.value === "__new") {
                        const id = newId("scene", ids);
                        const nodes = { ...d.nodes,
                          [nid]: { ...n, choices: n.choices.map((x, k) => (k === j ? { ...x, next: id } : x)) },
                          [id]: { title: c.label ? `After “${c.label.slice(0, 30)}”` : `Scene ${ids.length + 1}`, prompt: "", character: n.character, min_turns: 1, wrap_after: 8, choices: [], ending: null } };
                        setDef({ nodes });
                      } else setChoice(j, { next: e.target.value });
                    }}>
                      <option value="">Choose a scene…</option>
                      {ids.filter((x) => x !== nid).map((x) => <option key={x} value={x}>{d.nodes[x].title}{d.nodes[x].ending ? " (ending)" : ""}</option>)}
                      {ids.includes(nid) && <option value={nid}>{n.title} (repeat this scene)</option>}
                      <option value="__new">+ New scene</option>
                    </select>
                  )}
                </Field>
                <button className="btn quiet small" aria-label={`Remove path ${j + 1}`} onClick={() => setNode(nid, { choices: n.choices.filter((_, k) => k !== j) })}>Remove</button>
                <div className="sig">
                  <Field label="How the student takes this path" hint="Be specific about what they say or do." error={errFor(`nodes.${nid}.choices.${j}.signal`)}>
                    {(fid) => <textarea id={fid} rows={2} value={c.signal || ""} placeholder="The student explains that deposit costs rise with Fed rate increases while the fixed mortgage income doesn't, squeezing the bank's margin." onChange={(e) => setChoice(j, { signal: e.target.value })} />}
                  </Field>
                </div>
                <details className="fb more" open={!!c.feedback}>
                  <summary>Feedback for this path</summary>
                  <input type="text" value={c.feedback} aria-label={`Feedback for path ${j + 1}`} placeholder="Shown to the student as the scene moves on" onChange={(e) => setChoice(j, { feedback: e.target.value })} />
                </details>
              </div>
            ))}
            <div><button className="btn small" onClick={() => setNode(nid, { choices: [...n.choices, { label: "", signal: "", next: "", feedback: "" }] })}>Add path</button></div>
            {n.choices.length > 0 && (
              <details className="more" open={!!n.fallback || !!errFor(`nodes.${nid}.fallback`)}>
              <summary>More options</summary>
              <Field label="If no path is clear at the maximum" hint="Covers one-word answers, refusing to engage, or going off-topic." error={errFor(`nodes.${nid}.fallback`)}>
                {(fid) => (
                  <select id={fid} value={n.fallback || ""} onChange={(e) => setNode(nid, { fallback: e.target.value })}>
                    <option value="">Automatic (path toward the worst ending)</option>
                    {n.choices.filter((c) => c.label.trim()).map((c) => <option key={c.label} value={c.label}>Take “{c.label}”</option>)}
                  </select>
                )}
              </Field>
              </details>
            )}
          </div>
        </>}

        {n.ending && <>
          <div className="grid-2">
            <Field label="Outcome name" error={errFor(`nodes.${nid}.ending.label`)}>{(fid) => <input id={fid} type="text" value={n.ending.label} placeholder="Sound recommendation" onChange={(e) => setNode(nid, { ending: { ...n.ending, label: e.target.value } })} />}</Field>
            <div className="field">
              <span className="label">How did it go?</span>
              <div className="seg" role="radiogroup" aria-label="Outcome type">
                {[["success", "Success"], ["partial", "Partial"], ["fail", "Didn't succeed"]].map(([val, lab]) => (
                  <label key={val}><input type="radio" name="otype" checked={n.ending.type === val} onChange={() => setNode(nid, { ending: { ...n.ending, type: val } })} />{lab}</label>
                ))}
              </div>
            </div>
          </div>
          <Field label="Feedback for this ending" hint="What the student should take away.">
            {(fid) => <textarea id={fid} rows={3} value={n.ending.feedback} onChange={(e) => setNode(nid, { ending: { ...n.ending, feedback: e.target.value } })} />}
          </Field>
        </>}

        <div className="row between" style={{ borderTop: "1px solid var(--line-2)", paddingTop: 16 }}>
          {nid === d.start ? <span className="small muted">Students start here.</span>
            : <button className="btn small" onClick={() => setDef({ start: nid })}>Make this the starting scene</button>}
          <button className="btn danger small" onClick={() => removeScene(nid)} disabled={ids.length === 1}>Delete scene</button>
        </div>
      </div>
    </div>
  );
}

// One control for every scene's wrap-up limit; individual scenes can still differ.
function SceneLength({ d, setDef }) {
  const branching = Object.entries(d.nodes).filter(([, n]) => !n.ending);
  const values = [...new Set(branching.map(([, n]) => n.wrap_after ?? 8))];
  const [draft, setDraft] = useState("");
  const shown = draft !== "" ? draft : values.length === 1 ? String(values[0]) : "";
  const apply = (v) => {
    const num = Math.max(0, Math.min(50, Number(v) || 0));
    const nodes = Object.fromEntries(Object.entries(d.nodes).map(([id, n]) =>
      [id, n.ending ? n : { ...n, wrap_after: num, min_turns: Math.min(n.min_turns, num || n.min_turns) }]));
    setDef({ nodes });
    setDraft("");
  };
  return (
    <Field label="Messages per scene" hint={values.length > 1 ? "Scenes differ. Enter a number to set them all." : "Sets every scene. Change single scenes under Scenes."}>
      {(fid) => (
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input id={fid} type="number" min={0} max={50} value={shown} placeholder="Mixed" style={{ maxWidth: 120 }}
            onChange={(e) => setDraft(e.target.value)} onBlur={() => draft !== "" && apply(draft)}
            onKeyDown={(e) => { if (e.key === "Enter" && draft !== "") apply(draft); }} />
          {draft !== "" && <button className="btn small" onClick={() => apply(draft)}>Apply to all scenes</button>}
        </div>
      )}
    </Field>
  );
}

function AssignPanel({ scenario, onChange }) {
  const toast = useToast();
  const { data: classes } = useApi("/api/classes");
  const [cls, setCls] = useState("");
  const [due, setDue] = useState("");
  const [err, setErr] = useState(null);
  const assigned = new Set(scenario.assignments.map((a) => a.class_id));
  const assign = async () => {
    setErr(null);
    try {
      await api(`/api/scenarios/${scenario.id}/assignments`, { method: "POST", body: { class_id: Number(cls), due_at: due ? new Date(due).toISOString() : null } });
      toast("Assigned."); setCls(""); setDue(""); onChange();
    } catch (e) { setErr(e); }
  };
  const unassign = async (cid) => {
    try { await api(`/api/scenarios/${scenario.id}/assignments/${cid}`, { method: "DELETE" }); toast("Unassigned."); onChange(); }
    catch (e) { setErr(e); }
  };
  return (
    <div className="panel">
      <h2 style={{ marginBottom: 12 }}>Assign to courses</h2>
      <ErrorBanner error={err} />
      {scenario.status !== "published" && <p className="muted">Publish the scenario to assign it.</p>}
      {scenario.assignments.length > 0 && (
        <ul style={{ paddingLeft: 0, listStyle: "none" }}>
          {scenario.assignments.map((a) => (
            <li key={a.class_id} className="row between" style={{ padding: "6px 0", borderBottom: "1px solid var(--line-2)" }}>
              <span><b>{a.class_name}</b>{a.due_at && <span className="muted">, due {fmtDate(a.due_at)}</span>}</span>
              <button className="btn quiet small" onClick={() => unassign(a.class_id)}>Unassign</button>
            </li>
          ))}
        </ul>
      )}
      {scenario.status === "published" && (
        <div className="row" style={{ alignItems: "flex-end", marginTop: 12 }}>
          <div className="field grow" style={{ minWidth: 200 }}>
            <label htmlFor="assign-class">Course</label>
            <select id="assign-class" value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="">Choose a course…</option>
              {classes?.filter((c) => !assigned.has(c.id)).map((c) => <option key={c.id} value={c.id}>{c.name} ({c.students.length} students)</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="assign-due">Due date (optional)</label>
            <input id="assign-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
          <button className="btn primary" disabled={!cls} onClick={assign}>Assign</button>
        </div>
      )}
      {classes?.length === 0 && <p className="small muted">You don't have any courses yet. <a href="/classes">Create one</a>.</p>}
    </div>
  );
}
