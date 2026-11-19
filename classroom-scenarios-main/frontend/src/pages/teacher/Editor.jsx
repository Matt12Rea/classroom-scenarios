// Scenario builder (SRS 3.1, UC-01). Four steps: Overview, Characters, Scenes and
// paths, Review and publish. Form-based, so no programming is needed.
//
// The idea every screen here tries to make obvious: a scenario is a set of scenes.
// Each scene either ends the scenario or leads to other scenes by "paths". A path
// is a rule: IF the student does this, THEN go to that scene. Students never see
// the rules; the AI judge checks them after each message.
import { useEffect, useMemo, useRef, useState } from "react";
import FlowMap from "../../components/FlowMap.jsx";
import { fallbackIndex, incoming, routes as allRoutes, storyOrder, summary } from "../../graph.js";
import { api, fmtDate, nameList, navigate, OUTCOME_LABEL, setLeaveGuard, useApi, useToast } from "../../lib.jsx";
import { Breadcrumbs, Confirm, ErrorBanner, Field, Icon, ListEditor, Loading, Status } from "../../ui.jsx";

const STEPS = [
  { id: "basics", label: "Overview", fields: ["title", "setting", "objectives", "boundaries"] },
  { id: "characters", label: "Characters", fields: ["characters"] },
  { id: "scenes", label: "Scenes and paths", fields: ["nodes", "start"] },
  { id: "review", label: "Review and publish", fields: [] },
];
const MAX_CAST = 4;
const LETTER = "ABCDEFGH";

function newId(prefix, taken) {
  let i = 1;
  while (taken.includes(`${prefix}_${i}`)) i++;
  return `${prefix}_${i}`;
}
const castOf = (n) => (n.characters?.length ? n.characters : n.character ? [n.character] : []);
const blankScene = (title, cast) => ({ title, prompt: "", characters: cast, character: cast[0] || "", min_turns: 1, wrap_after: 8, fallback: "", choices: [], ending: null });

export default function Editor({ id }) {
  const toast = useToast();
  const { data, error, loading, reload } = useApi(`/api/scenarios/${id}`, [id]);
  const [sc, setSc] = useState(null);
  const [dirty, setDirty] = useState(false);
  const [step, setStep] = useState("basics");
  const [scene, setScene] = useState(null);
  const [v, setV] = useState({ errors: [], warnings: [] });
  const [busy, setBusy] = useState("");
  const [actionErr, setActionErr] = useState(null);
  const [confirm, setConfirm] = useState(null);

  useEffect(() => {
    if (data) {
      setSc({ title: data.title, description: data.description, max_turns: data.max_turns, definition: data.definition });
      setV(data.validation); setDirty(false);
      setScene((s) => (s && data.definition.nodes[s] ? s : data.definition.start || Object.keys(data.definition.nodes)[0]));
    }
  }, [data]);

  // Live checks while editing (debounced). If the check itself can't run, the last
  // result stays; saving and publishing check again on the server.
  const timer = useRef();
  useEffect(() => {
    if (!sc || !dirty) return undefined;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api("/api/scenarios/validate", { method: "POST", body: { title: sc.title, definition: sc.definition } }).then(setV).catch(() => {});
    }, 500);
    return () => clearTimeout(timer.current);
  }, [sc, dirty]);

  // Don't lose unsaved work: warn on reload/close and on moving to another page.
  useEffect(() => {
    const warn = (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    setLeaveGuard(dirty ? "You have unsaved changes to this scenario. Leave without saving?" : null);
    return () => { window.removeEventListener("beforeunload", warn); setLeaveGuard(null); };
  }, [dirty]);

  const errFor = useMemo(() => {
    const m = {};
    v.errors.forEach((e) => { m[e.field] ||= e.message; });
    return (f) => m[f];
  }, [v]);
  const stepErrors = (t) => v.errors.filter((e) => t.fields.some((f) => e.field === f || e.field.startsWith(f + "."))).length;

  if (loading && !sc) return <Loading label="Loading scenario…" />;
  if (error && !sc) return <ErrorBanner error={error} onRetry={reload} />;
  if (!sc || !data) return null;

  const d = sc.definition;
  const set = (patch) => { setSc((s) => ({ ...s, ...patch })); setDirty(true); };
  const setDef = (patch) => setSc((s) => { setDirty(true); return { ...s, definition: { ...s.definition, ...patch } }; });
  const setNode = (nid, patch) => setSc((s) => {
    setDirty(true);
    const nodes = s.definition.nodes;
    return { ...s, definition: { ...s.definition, nodes: { ...nodes, [nid]: { ...nodes[nid], ...patch } } } };
  });

  async function save({ quiet } = {}) {
    setBusy("save"); setActionErr(null);
    try {
      const r = await api(`/api/scenarios/${id}`, { method: "PUT", body: sc });
      setV(r.validation); setDirty(false);
      if (!quiet) toast("Saved.");
      return r;
    } catch (e) { setActionErr(e); throw e; } finally { setBusy(""); }
  }
  async function act(kind) {
    if (busy) return;
    setActionErr(null);
    try {
      if (dirty) await save({ quiet: true });
      setBusy(kind);
      if (kind === "preview") {
        const st = await api("/api/sessions", { method: "POST", body: { scenario_id: Number(id), preview: true } });
        navigate(`/preview/${st.id}`, { force: true }); return;
      }
      await api(`/api/scenarios/${id}/${kind}`, { method: "POST" });
      toast({ publish: "Published. Assign it to a course so students can see it.", unpublish: "Unpublished. It's a draft again.", archive: "Archived.", restore: "Restored as a draft." }[kind]);
      reload();
    } catch (e) {
      setActionErr(e);
      if (kind === "publish" && e.errors?.length) setStep("review");
    } finally { setBusy(""); }
  }
  async function duplicate() {
    try {
      if (dirty) await save({ quiet: true });
      const r = await api(`/api/scenarios/${id}/duplicate`, { method: "POST" });
      toast("Copy created."); navigate(`/scenarios/${r.id}`, { force: true });
    } catch (e) { setActionErr(e); }
  }

  function jump(field) {
    const parts = field.split(".");
    if (parts[0] === "nodes" && parts[1]) { setStep("scenes"); setScene(parts[1]); }
    else setStep(STEPS.find((t) => t.fields.includes(parts[0]))?.id || "basics");
    window.scrollTo(0, 0);
  }
  const stepIndex = STEPS.findIndex((s) => s.id === step);
  const published = data.status === "published";

  return (
    <div className="page editor">
      <div className="editor-bar">
        <div className="grow">
          <Breadcrumbs items={[["/scenarios", "Scenarios"], [null, sc.title || "Untitled scenario"]]} />
          <div className="row" style={{ marginTop: 6 }}>
            <h1>{sc.title || "Untitled scenario"}</h1>
            <Status value={data.status} />
            <span className="small muted" role="status">{dirty ? "Unsaved changes" : "All changes saved"}</span>
          </div>
        </div>
        <div className="row">
          <button className="btn" onClick={() => save().catch(() => {})} disabled={!!busy || !dirty}>{busy === "save" ? "Saving…" : "Save"}</button>
          <button className="btn" onClick={() => act("preview")} disabled={!!busy}><Icon name="eye" size={16} />{busy === "preview" ? "Opening…" : "Preview"}</button>
          {published
            ? <button className="btn" onClick={() => act("unpublish")} disabled={!!busy}>Unpublish</button>
            : data.status === "archived"
              ? <button className="btn primary" onClick={() => act("restore")} disabled={!!busy}>Restore as draft</button>
              : <button className="btn primary" onClick={() => (v.errors.length ? setStep("review") : act("publish"))} disabled={!!busy}>{busy === "publish" ? "Publishing…" : "Publish"}</button>}
        </div>
      </div>
      <ErrorBanner error={actionErr} />
      {published && <div className="banner info">This scenario is live. Changes you save apply to attempts started from now on; attempts already under way keep the version they started with.</div>}

      <div className="steps" role="tablist" aria-label="Builder steps">
        {STEPS.map((t, i) => {
          const n = t.id === "review" ? 0 : stepErrors(t);
          return (
            <button key={t.id} role="tab" aria-selected={step === t.id} onClick={() => setStep(t.id)}>
              <span className={`step-no ${n ? "err" : ""}`} aria-hidden="true">{i + 1}</span>
              <span>{t.label}</span>
              {n > 0 && <span className="step-count" aria-label={`${n} to fix`}>{n} to fix</span>}
            </button>
          );
        })}
      </div>

      {step === "basics" && (
        <div className="panel stack" role="tabpanel">
          <Field label="Title" error={errFor("title")}>{(fid) => <input id={fid} type="text" maxLength={200} value={sc.title} onChange={(e) => set({ title: e.target.value })} />}</Field>
          <Field label="Short description" hint="Shown on students' scenario list.">{(fid) => <textarea id={fid} rows={2} maxLength={4000} value={sc.description} onChange={(e) => set({ description: e.target.value })} />}</Field>
          <Field label="Setting" hint="Where and when, and who the student plays." error={errFor("setting")}>
            {(fid) => <textarea id={fid} rows={3} value={d.setting} placeholder="A community bank in Iowa as the Fed raises rates. You are a junior analyst advising the bank's president." onChange={(e) => setDef({ setting: e.target.value })} />}
          </Field>
          <div className={`field ${errFor("objectives") ? "invalid" : ""}`}>
            <span className="label">Learning objectives</span>
            <span className="hint">Shown to students as their goals, and used for feedback.</span>
            <ListEditor items={d.objectives} onChange={(objectives) => setDef({ objectives })} placeholder="Objective" addLabel="Add objective" invalid />
            {errFor("objectives") && <span className="error-text">{errFor("objectives")}</span>}
          </div>
          <div className="field">
            <span className="label">Boundaries for the AI</span>
            <span className="hint">Rules every character follows, on top of the standard safety rules.</span>
            <ListEditor items={d.boundaries} onChange={(boundaries) => setDef({ boundaries })} placeholder="Boundary" addLabel="Add boundary" />
          </div>
          <Field label="Feedback focus" hint="Guides the AI's written feedback at the end.">
            {(fid) => <textarea id={fid} rows={2} value={d.feedback_guidance} placeholder="Did the student identify the bank's interest-rate risk and propose a realistic way to manage it?" onChange={(e) => setDef({ feedback_guidance: e.target.value })} />}
          </Field>
          <Field label="Message limit for the whole scenario" hint="How many messages a student can send in one attempt. When they run out, the scenario wraps up.">
            {(fid) => <input id={fid} type="number" min={1} max={200} value={sc.max_turns} style={{ maxWidth: 140 }} onChange={(e) => set({ max_turns: Math.max(1, Math.min(200, Number(e.target.value) || 1)) })} />}
          </Field>
        </div>
      )}

      {step === "characters" && <CharactersStep d={d} setDef={setDef} errFor={errFor} />}

      {step === "scenes" && (
        <ScenesStep d={d} setDef={setDef} setNode={setNode} scene={scene} setScene={setScene} errFor={errFor} errors={v.errors} warnings={v.warnings} />
      )}

      {step === "review" && (
        <ReviewStep d={d} v={v} data={data} busy={busy} dirty={dirty} act={act} jump={jump}
          openScene={(nid) => { setScene(nid); setStep("scenes"); window.scrollTo(0, 0); }}
          reload={reload} duplicate={duplicate} setConfirm={setConfirm} id={id} />
      )}

      <div className="step-nav">
        {stepIndex > 0 ? <button className="btn" onClick={() => { setStep(STEPS[stepIndex - 1].id); window.scrollTo(0, 0); }}>Back: {STEPS[stepIndex - 1].label}</button> : <span />}
        {stepIndex < STEPS.length - 1 && <button className="btn primary" onClick={() => { setStep(STEPS[stepIndex + 1].id); window.scrollTo(0, 0); }}>Next: {STEPS[stepIndex + 1].label}<Icon name="arrow" size={16} /></button>}
      </div>

      {confirm === "archive" && (
        <Confirm title="Archive this scenario?" confirmLabel="Archive" onClose={() => setConfirm(null)} onConfirm={() => act("archive")}>
          <p>Students won't see it anymore. Their results are kept, and you can restore it later.</p>
        </Confirm>
      )}
      {confirm === "delete" && (
        <Confirm title="Delete this scenario?" confirmLabel="Delete" danger onClose={() => setConfirm(null)} onConfirm={async () => {
          await api(`/api/scenarios/${id}`, { method: "DELETE" });
          toast("Scenario deleted."); navigate("/scenarios", { force: true });
        }}>
          <p>This can't be undone. If students have already played it, it can only be archived, so their results are kept.</p>
        </Confirm>
      )}
    </div>
  );
}

// ------------------------------------------------------------ step 2 --
function CharactersStep({ d, setDef, errFor }) {
  return (
    <div className="stack" role="tabpanel">
      <p className="lede">The people the AI plays. You choose who is in each scene in the next step; a scene can have several of them in the room.</p>
      {errFor("characters") && <div className="banner error">{errFor("characters")}</div>}
      {d.characters.map((c, i) => {
        const upd = (patch) => setDef({ characters: d.characters.map((x, j) => (j === i ? { ...x, ...patch } : x)) });
        const scenes = Object.values(d.nodes).filter((n) => castOf(n).includes(c.id)).map((n) => n.title);
        return (
          <div className="panel stack" key={c.id}>
            <div className="grid-2">
              <Field label="Name" error={errFor(`characters.${i}.name`)}>{(fid) => <input id={fid} type="text" maxLength={120} value={c.name} placeholder="Carol Brennan" onChange={(e) => upd({ name: e.target.value })} />}</Field>
              <Field label="Who they are" error={errFor(`characters.${i}.role`)}>{(fid) => <input id={fid} type="text" value={c.role} placeholder="the bank's president" onChange={(e) => upd({ role: e.target.value })} />}</Field>
            </div>
            <Field label="Personality and background" hint="How they talk, and what makes them open up or shut down.">
              {(fid) => <textarea id={fid} rows={3} value={c.traits} placeholder="Practical, not an economist. Wants plain English and a concrete numerical example." onChange={(e) => upd({ traits: e.target.value })} />}
            </Field>
            <div className="row between">
              <span className="small muted">{scenes.length ? `In ${scenes.length} scene${scenes.length === 1 ? "" : "s"}: ${scenes.join(", ")}` : "Not in any scene yet."}</span>
              <button className="btn danger small" disabled={scenes.length > 0} title={scenes.length ? "Take them out of those scenes first." : ""}
                onClick={() => setDef({ characters: d.characters.filter((_, j) => j !== i) })}>Remove character</button>
            </div>
          </div>
        );
      })}
      <div><button className="btn" onClick={() => {
        const cid = newId("character", d.characters.map((c) => c.id));
        setDef({ characters: [...d.characters, { id: cid, name: "", role: "", traits: "" }] });
      }}><Icon name="plus" size={16} />Add character</button></div>
    </div>
  );
}

// ------------------------------------------------------------ step 3 --
function sceneKind(n) {
  if (n.ending) return { text: `Ending: ${OUTCOME_LABEL[n.ending.type] || "Partial"}`, cls: n.ending.type };
  const k = (n.choices || []).length;
  return { text: `${k} path${k === 1 ? "" : "s"} out`, cls: k ? "" : "bad" };
}

function ScenesStep({ d, setDef, setNode, scene, setScene, errFor, errors, warnings }) {
  const ids = Object.keys(d.nodes);
  const { order, unreachable } = useMemo(() => storyOrder(d), [d]);
  const into = useMemo(() => incoming(d), [d]);
  const nid = d.nodes[scene] ? scene : order[0];
  const n = d.nodes[nid];
  const sceneHasErr = (id) => errors.some((e) => e.field.startsWith(`nodes.${id}.`) || e.field === `nodes.${id}`);
  const names = Object.fromEntries(d.characters.map((c) => [c.id, c.name || "(unnamed)"]));
  const defaultCast = d.characters[0] ? [d.characters[0].id] : [];

  const addScene = () => {
    const id = newId("scene", ids);
    setDef({ nodes: { ...d.nodes, [id]: blankScene(`Scene ${ids.length + 1}`, n ? castOf(n) : defaultCast) }, start: d.start || id });
    setScene(id);
  };
  const removeScene = (id) => {
    // Rebuild every scene without the deleted one, clearing any path that pointed at it.
    const nodes = Object.fromEntries(Object.entries(d.nodes).filter(([k]) => k !== id).map(([k, x]) =>
      [k, { ...x, choices: (x.choices || []).map((c) => (c.next === id ? { ...c, next: "" } : c)) }]));
    const start = d.start === id ? Object.keys(nodes)[0] || "" : d.start;
    setDef({ nodes, start });
    setScene(start);
  };
  if (!n) {
    return <div className="panel" role="tabpanel"><p>A scenario is made of scenes. Start with the moment the student walks into.</p><button className="btn primary" onClick={addScene}>Add the first scene</button></div>;
  }

  const cast = castOf(n);
  const setChoice = (j, patch) => setNode(nid, { choices: n.choices.map((c, k) => (k === j ? { ...c, ...patch } : c)) });
  const renameChoice = (j, label) => {
    // Keep the "if nothing is clear" rule pointing at this path when it is renamed.
    const patch = { choices: n.choices.map((c, k) => (k === j ? { ...c, label } : c)) };
    if (n.fallback && n.fallback === n.choices[j].label) patch.fallback = label;
    setNode(nid, patch);
  };
  const removeChoice = (j) => setNode(nid, { choices: n.choices.filter((_, k) => k !== j), fallback: n.fallback === n.choices[j].label ? "" : n.fallback });
  const toggleCast = (cid) => {
    const next = cast.includes(cid) ? cast.filter((x) => x !== cid) : [...cast, cid].slice(0, MAX_CAST);
    setNode(nid, { characters: next, character: next[0] || "" });
  };
  const newSceneFor = (j) => {
    const c = n.choices[j];
    const id = newId("scene", ids);
    setDef({ nodes: { ...d.nodes,
      [nid]: { ...n, choices: n.choices.map((x, k) => (k === j ? { ...x, next: id } : x)) },
      [id]: blankScene(c.label ? `After “${c.label.slice(0, 40)}”` : `Scene ${ids.length + 1}`, cast) } });
  };
  const fb = fallbackIndex(d, nid);
  const sceneWarnings = warnings.filter((w) => w.field === `nodes.${nid}`);

  return (
    <div className="scenes" role="tabpanel">
      <nav className="outline" aria-label="Scenes">
        <div className="outline-head">Scenes, in story order</div>
        {order.map((id, i) => {
          const x = d.nodes[id];
          const kind = sceneKind(x);
          const first = unreachable[0] === id;
          return (
            <div key={id}>
              {first && <div className="outline-head sub">Not connected to the story yet</div>}
              <button aria-current={id === nid} onClick={() => setScene(id)}>
                <span className="outline-no" aria-hidden="true">{i + 1}</span>
                <span className="outline-body">
                  <b>{x.title || "Untitled scene"}</b>
                  <span className="outline-meta">
                    {id === d.start && <span className="chip start">Start</span>}
                    <span className={`chip ${kind.cls}`}>{kind.text}</span>
                    {sceneHasErr(id) && <span className="chip bad">Needs attention</span>}
                  </span>
                </span>
              </button>
            </div>
          );
        })}
        <button className="outline-add" onClick={addScene}><Icon name="plus" size={16} />Add scene</button>
      </nav>

      <div className="scene-editor" key={nid}>
        <section className="panel stack">
          <div className="row between">
            <h2>Scene {order.indexOf(nid) + 1}</h2>
            {nid === d.start ? <span className="chip start">Students start here</span>
              : <button className="btn small" onClick={() => setDef({ start: nid })}>Make this the starting scene</button>}
          </div>
          {nid !== d.start && (
            <p className="small muted arrive">
              {into[nid]?.length
                ? <>Students arrive here from {into[nid].map((x, i) => <span key={i}>{i > 0 && "; "}<button className="linkish" onClick={() => setScene(x.from)}>{d.nodes[x.from].title}</button> by “{x.label || "an unnamed path"}”</span>)}.</>
                : "No path leads here yet, so students can't reach this scene. Open another scene and point one of its paths at this one."}
            </p>
          )}
          {sceneWarnings.map((w, i) => <div key={i} className="banner warn small">{w.message}</div>)}
          <Field label="Scene title" hint="Students see this as the scene's heading.">{(fid) => <input id={fid} type="text" maxLength={200} value={n.title} onChange={(e) => setNode(nid, { title: e.target.value })} />}</Field>
          <Field label="What's happening" hint="Shown to the student when the scene opens, and given to the AI." error={errFor(`nodes.${nid}.prompt`)}>
            {(fid) => <textarea id={fid} rows={3} value={n.prompt} onChange={(e) => setNode(nid, { prompt: e.target.value })} />}
          </Field>
          <fieldset className={`field plain ${errFor(`nodes.${nid}.characters`) ? "invalid" : ""}`}>
            <legend>Who is in this scene</legend>
            <span className="hint">Tick everyone present (up to {MAX_CAST}). With two or more, the AI decides who answers each message, and sometimes two of them do.</span>
            {d.characters.length === 0 ? <p className="small muted">Add a character in step 2 first.</p> : (
              <div className="pick">
                {d.characters.map((c) => {
                  const on = cast.includes(c.id);
                  return (
                    <label key={c.id} className={on ? "on" : ""}>
                      <input type="checkbox" checked={on} disabled={!on && cast.length >= MAX_CAST} onChange={() => toggleCast(c.id)} />
                      <span><b>{c.name || "(unnamed)"}</b>{c.role && <small>{c.role}</small>}</span>
                    </label>
                  );
                })}
              </div>
            )}
            {errFor(`nodes.${nid}.characters`) && <span className="error-text" role="alert">{errFor(`nodes.${nid}.characters`)}</span>}
          </fieldset>
        </section>

        <section className="panel stack">
          <h2>How this scene ends</h2>
          <div className="seg wide" role="radiogroup" aria-label="How this scene ends">
            <label><input type="radio" name={`kind-${nid}`} checked={!n.ending} onChange={() => setNode(nid, { ending: null })} />
              <span><b>It leads to another scene</b><small>Which one depends on what the student says or does.</small></span></label>
            <label><input type="radio" name={`kind-${nid}`} checked={!!n.ending} onChange={() => setNode(nid, { ending: { label: "", type: "success", feedback: "" }, choices: [], fallback: "" })} />
              <span><b>The scenario ends here</b><small>The student sees an outcome and feedback.</small></span></label>
          </div>

          {!n.ending && <>
            <div className="explain">
              <b>How paths work.</b> Students never see them. After each message, the AI checks whether the student
              has done what a path describes. The first time one clearly fits, the scene moves on to that path's scene.
            </div>
            {errFor(`nodes.${nid}.choices`) && <div className="banner error">{errFor(`nodes.${nid}.choices`)}</div>}
            {n.choices.map((c, j) => {
              const target = d.nodes[c.next];
              const tk = target ? sceneKind(target) : null;
              return (
                <div className="rule" key={j}>
                  <div className="rule-head">
                    <span className="rule-tag">Path {LETTER[j] || j + 1}</span>
                    <button className="btn quiet small" onClick={() => removeChoice(j)} aria-label={`Remove path ${LETTER[j] || j + 1}`}>Remove</button>
                  </div>
                  <div className="rule-row">
                    <span className="rule-word">If</span>
                    <Field label="the student…" hint="Describe what they say or do. Be specific: this is what the AI looks for." error={errFor(`nodes.${nid}.choices.${j}.signal`)}>
                      {(fid) => <textarea id={fid} rows={2} value={c.signal || ""} placeholder="explains that deposit costs rise with Fed rate increases while the fixed mortgage income doesn't, squeezing the bank's margin." onChange={(e) => setChoice(j, { signal: e.target.value })} />}
                    </Field>
                  </div>
                  <div className="rule-row">
                    <span className="rule-word">Then</span>
                    <Field label="go to the scene" error={errFor(`nodes.${nid}.choices.${j}.next`) ? "Choose where this path leads." : null}>
                      {(fid) => (
                        <div className="row nowrap-row">
                          <select id={fid} value={c.next} onChange={(e) => (e.target.value === "__new" ? newSceneFor(j) : setChoice(j, { next: e.target.value }))}>
                            <option value="">Choose a scene…</option>
                            {order.filter((x) => x !== nid).map((x) => <option key={x} value={x}>{d.nodes[x].title}{d.nodes[x].ending ? ` (ending: ${OUTCOME_LABEL[d.nodes[x].ending.type].toLowerCase()})` : ""}</option>)}
                            <option value={nid}>{n.title} (stay in this scene)</option>
                            <option value="__new">Create a new scene…</option>
                          </select>
                          {target && c.next !== nid && <button className="btn small" onClick={() => setScene(c.next)}>Open</button>}
                        </div>
                      )}
                    </Field>
                    {tk && <span className={`chip ${tk.cls}`}>{target.ending ? tk.text : "Continues"}</span>}
                  </div>
                  <div className="rule-row">
                    <span className="rule-word">Call it</span>
                    <Field label="a short name for what the student did" hint="Shown to the student after the scene moves on, and in your results." error={errFor(`nodes.${nid}.choices.${j}.label`)}>
                      {(fid) => <input id={fid} type="text" maxLength={200} value={c.label} placeholder="Explained the bank's interest-rate risk" onChange={(e) => renameChoice(j, e.target.value)} />}
                    </Field>
                  </div>
                  <details className="more" open={!!c.feedback}>
                    <summary>Add a note the student sees when this path is taken</summary>
                    <input type="text" value={c.feedback} aria-label={`Note for path ${LETTER[j] || j + 1}`} placeholder="For example: Spotting the mismatch is the core of interest-rate risk." onChange={(e) => setChoice(j, { feedback: e.target.value })} />
                  </details>
                </div>
              );
            })}
            <div><button className="btn" disabled={n.choices.length >= 8} onClick={() => setNode(nid, { choices: [...n.choices, { label: "", signal: "", next: "", feedback: "" }] })}><Icon name="plus" size={16} />Add {n.choices.length ? "another" : "a"} path</button></div>

            <div className="rule limits">
              <div className="rule-head"><span className="rule-tag plain">How long the scene can run</span></div>
              <div className="sentence">
                A path can be taken after at least
                <input type="number" min={0} max={20} value={n.min_turns} aria-label="Minimum messages" className={errFor(`nodes.${nid}.min_turns`) ? "invalid" : ""}
                  onChange={(e) => setNode(nid, { min_turns: Math.max(0, Math.min(20, Number(e.target.value) || 0)) })} />
                message{n.min_turns === 1 ? "" : "s"}. The scene wraps up after
                <input type="number" min={0} max={50} value={n.wrap_after ?? 8} aria-label="Maximum messages" className={errFor(`nodes.${nid}.wrap_after`) ? "invalid" : ""}
                  onChange={(e) => setNode(nid, { wrap_after: Math.max(0, Math.min(50, Number(e.target.value) || 0)) })} />
                message{n.wrap_after === 1 ? "" : "s"}{n.wrap_after === 0 ? " (0 means no limit for this scene)" : ""}.
              </div>
              {errFor(`nodes.${nid}.wrap_after`) && <span className="error-text" role="alert">{errFor(`nodes.${nid}.wrap_after`)}</span>}
            </div>

            {n.choices.length > 0 && (
              <div className="rule fallback">
                <div className="rule-head"><span className="rule-tag plain">If no path is clear</span></div>
                <p className="small">
                  When the scene {n.wrap_after ? `reaches ${n.wrap_after} message${n.wrap_after === 1 ? "" : "s"}` : "runs out of messages"} and the
                  student still hasn't clearly taken a path (one-word answers, going off-topic, refusing to engage), the scene moves on anyway:
                </p>
                <Field label="Take this path" error={errFor(`nodes.${nid}.fallback`)}>
                  {(fid) => (
                    <select id={fid} value={n.fallback || ""} onChange={(e) => setNode(nid, { fallback: e.target.value })}>
                      <option value="">Automatic{fb >= 0 ? `: currently “${n.choices[fb].label || `Path ${LETTER[fb]}`}”` : ""}</option>
                      {n.choices.filter((c) => c.label.trim()).map((c) => <option key={c.label} value={c.label}>Always “{c.label}”</option>)}
                    </select>
                  )}
                </Field>
                {!n.fallback && <p className="small muted" style={{ margin: 0 }}>Automatic picks the path that can lead to the worst ending, so not engaging never earns a good result.</p>}
              </div>
            )}
          </>}

          {n.ending && <>
            <div className="grid-2">
              <Field label="Outcome name" hint="For example: Sound recommendation." error={errFor(`nodes.${nid}.ending.label`)}>{(fid) => <input id={fid} type="text" maxLength={200} value={n.ending.label} onChange={(e) => setNode(nid, { ending: { ...n.ending, label: e.target.value } })} />}</Field>
              <div className="field">
                <span className="label">How did it go?</span>
                <div className="seg" role="radiogroup" aria-label="Outcome type">
                  {[["success", "Success"], ["partial", "Partial"], ["fail", "Didn't succeed"]].map(([val, lab]) => (
                    <label key={val}><input type="radio" name={`otype-${nid}`} checked={n.ending.type === val} onChange={() => setNode(nid, { ending: { ...n.ending, type: val } })} />{lab}</label>
                  ))}
                </div>
              </div>
            </div>
            <Field label="Feedback for this ending" hint="What the student should take away. Shown with the outcome.">
              {(fid) => <textarea id={fid} rows={3} value={n.ending.feedback} onChange={(e) => setNode(nid, { ending: { ...n.ending, feedback: e.target.value } })} />}
            </Field>
          </>}
        </section>

        <div className="row end">
          <button className="btn danger small" onClick={() => removeScene(nid)} disabled={ids.length === 1}><Icon name="trash" size={15} />Delete this scene</button>
        </div>
      </div>
    </div>
  );
}

// ------------------------------------------------------------ step 4 --
function ReviewStep({ d, v, data, busy, dirty, act, jump, openScene, reload, duplicate, setConfirm, id }) {
  const { routes, truncated } = useMemo(() => allRoutes(d), [d]);
  const sum = useMemo(() => summary(d), [d]);
  const title = (nid) => d.nodes[nid]?.title || "a missing scene";
  const published = data.status === "published";
  const ready = v.errors.length === 0;
  const count = (fields) => v.errors.filter((e) => fields.some((f) => e.field === f || e.field.startsWith(f + "."))).length;
  const checks = [
    ["Overview is filled in", count(["title", "setting", "objectives"]), "title"],
    ["Characters have names and roles", count(["characters"]), "characters"],
    ["Every scene has a description, people, and a way out", v.errors.filter((e) => e.field.startsWith("nodes.")).length, v.errors.find((e) => e.field.startsWith("nodes."))?.field || "nodes"],
    ["Students can reach an ending from the start", v.errors.filter((e) => e.field === "nodes" || e.field === "start").length, "start"],
  ];

  return (
    <div className="stack" role="tabpanel">
      <section className="panel">
        <div className="panel-head">
          <h2>{ready ? (published ? "Published" : "Ready to publish") : `${v.errors.length} thing${v.errors.length === 1 ? "" : "s"} to fix before publishing`}</h2>
          <span className="small muted">{sum.scenes} scene{sum.scenes === 1 ? "" : "s"}, {sum.endings} ending{sum.endings === 1 ? "" : "s"}, {routes.length}{truncated ? "+" : ""} route{routes.length === 1 ? "" : "s"}</span>
        </div>
        <ul className="checks">
          {checks.map(([label, n, field]) => (
            <li key={label} className={n ? "todo" : "done"}>
              <span className="mark" aria-hidden="true"><Icon name={n ? "alert" : "check"} size={16} /></span>
              <span>{label}</span>
              {n > 0 && <button className="linkish" onClick={() => jump(field)}>{n} to fix</button>}
            </li>
          ))}
        </ul>
        {v.errors.length > 0 && (
          <div className="banner error"><b>Fix before publishing</b>
            <ul className="issues">{v.errors.map((e, i) => <li key={i}><button onClick={() => jump(e.field)}>{e.message}</button></li>)}</ul>
          </div>
        )}
        {v.warnings.length > 0 && (
          <div className="banner warn"><b>Worth a look (won't stop you publishing)</b>
            <ul className="issues">{v.warnings.map((e, i) => <li key={i}><button onClick={() => jump(e.field)}>{e.message}</button></li>)}</ul>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Every route through the scenario</h2></div>
        <p className="lede">Each line is one way a student can go from the first scene to an ending. Read across: a scene, then the path taken out of it. If a route is missing or ends in the wrong place, open the scene and change its paths.</p>
        {routes.length === 0 && <p className="muted">No routes yet. Choose a starting scene and give it at least one path.</p>}
        <ol className="routes">
          {routes.map((r, i) => {
            const end = r.end ? d.nodes[r.end] : null;
            const type = r.problem ? "bad" : end?.ending?.type;
            return (
              <li key={i} className={type || ""}>
                <span className="route-no">Route {i + 1}</span>
                <span className="route-steps">
                  {r.steps.map((s, k) => (
                    <span key={k} className="route-step">
                      <button className="route-scene" onClick={() => openScene(s.scene)}>{title(s.scene)}</button>
                      <span className="route-path"><Icon name="arrow" size={14} />{s.path}</span>
                    </span>
                  ))}
                  {r.steps.length === 0 && r.end && <button className="route-scene" onClick={() => openScene(r.end)}>{title(r.end)}</button>}
                </span>
                <span className="route-end">
                  {r.problem === "broken" && <span className="chip bad">Path leads nowhere</span>}
                  {r.problem === "dead-end" && <><button className="route-scene" onClick={() => openScene(r.end)}>{title(r.end)}</button><span className="chip bad">No way out of this scene</span></>}
                  {r.problem === "loop" && <><button className="route-scene" onClick={() => openScene(r.end)}>{title(r.end)}</button><span className="chip">Returns to an earlier scene</span></>}
                  {!r.problem && end && <><button className="route-scene" onClick={() => openScene(r.end)}>{end.ending.label || title(r.end)}</button><span className={`chip ${end.ending.type}`}>{OUTCOME_LABEL[end.ending.type]}</span></>}
                </span>
              </li>
            );
          })}
        </ol>
        {truncated && <p className="small muted">Showing the first {routes.length} routes. This scenario has more.</p>}
      </section>

      <section className="panel">
        <div className="panel-head"><h2>Map</h2><span className="small muted">Arrows are paths. Click a scene to open it.</span></div>
        <FlowMap def={d} onSelect={openScene} />
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 12 }}>Publish</h2>
        <ol className="publish-steps">
          <li className="done-ish">
            <div><b>Try it yourself</b><p>Preview plays the scenario as a student would. Only you see it, and it shows which path the AI is listening for.</p></div>
            <button className="btn" onClick={() => act("preview")} disabled={!!busy}><Icon name="eye" size={16} />Preview</button>
          </li>
          <li className={published ? "done" : ""}>
            <div><b>Publish</b><p>{published ? "Published. It can be assigned to courses." : "Publishing doesn't show it to anyone yet. It makes the scenario available to assign."}</p></div>
            {published ? <span className="chip success">Published</span>
              : <button className="btn primary" onClick={() => act("publish")} disabled={!!busy || !ready} title={ready ? "" : "Fix the items above first."}>{busy === "publish" ? "Publishing…" : dirty ? "Save and publish" : "Publish"}</button>}
          </li>
          <li className={data.assignments.length ? "done" : ""}>
            <div><b>Assign to a course</b><p>Students see the scenario once it's assigned to a course they're in.</p></div>
            {data.assignments.length > 0 && <span className="chip success">{data.assignments.length} course{data.assignments.length === 1 ? "" : "s"}</span>}
          </li>
        </ol>
        <AssignPanel scenario={data} onChange={reload} />
      </section>

      <section className="panel">
        <h2 style={{ marginBottom: 12 }}>Other actions</h2>
        <div className="row">
          <button className="btn" onClick={duplicate}><Icon name="copy" size={16} />Duplicate</button>
          {data.sessions > 0 && <a className="btn" href={`/scenarios/${id}/results`}><Icon name="chart" size={16} />View results</a>}
          {data.status !== "archived" && <button className="btn" onClick={() => setConfirm("archive")}>Archive</button>}
          {data.sessions === 0 && <button className="btn danger" onClick={() => setConfirm("delete")}><Icon name="trash" size={16} />Delete</button>}
        </div>
      </section>
    </div>
  );
}

function AssignPanel({ scenario, onChange }) {
  const toast = useToast();
  const { data: classes } = useApi("/api/classes");
  const [cls, setCls] = useState("");
  const [due, setDue] = useState("");
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const assigned = new Set(scenario.assignments.map((a) => a.class_id));
  const assign = async () => {
    setErr(null); setBusy(true);
    try {
      await api(`/api/scenarios/${scenario.id}/assignments`, { method: "POST", body: { class_id: Number(cls), due_at: due ? new Date(`${due}T23:59:00`).toISOString() : null } });
      toast("Assigned."); setCls(""); setDue(""); onChange();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const unassign = async (cid) => {
    try { await api(`/api/scenarios/${scenario.id}/assignments/${cid}`, { method: "DELETE" }); toast("Unassigned."); onChange(); }
    catch (e) { setErr(e); }
  };
  if (scenario.status !== "published") return null;
  const free = classes?.filter((c) => !assigned.has(c.id)) || [];
  return (
    <div className="assign">
      <ErrorBanner error={err} />
      {scenario.assignments.length > 0 && (
        <ul className="assigned">
          {scenario.assignments.map((a) => (
            <li key={a.class_id}>
              <span><b>{a.class_name}</b>{a.due_at && <span className="muted">, due {fmtDate(a.due_at)}</span>}</span>
              <button className="btn quiet small" onClick={() => unassign(a.class_id)}>Unassign</button>
            </li>
          ))}
        </ul>
      )}
      {free.length > 0 && (
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field grow" style={{ minWidth: 200 }}>
            <label htmlFor="assign-class">Course</label>
            <select id="assign-class" value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="">Choose a course…</option>
              {free.map((c) => <option key={c.id} value={c.id}>{c.name} ({c.students.length} student{c.students.length === 1 ? "" : "s"})</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="assign-due">Due date (optional)</label>
            <input id="assign-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
          </div>
          <button className="btn primary" disabled={!cls || busy} onClick={assign}>Assign</button>
        </div>
      )}
      {classes?.length === 0 && <p className="small muted">You don't have any courses yet. <a href="/classes">Create one</a>.</p>}
      {classes?.length > 0 && free.length === 0 && <p className="small muted">Assigned to all of your courses.</p>}
    </div>
  );
}
