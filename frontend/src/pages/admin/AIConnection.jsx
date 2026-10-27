// Admin > AI connection. Add, replace or remove the Claude API key, choose the
// model, and check the connection's health. The key itself is never shown or
// sent back to the browser (REQ-3.2.3.10). IT support can view and test only.
import { useEffect, useState } from "react";
import { api, fmtDateTime, useApi, useAuth, useToast } from "../../lib.jsx";
import { Confirm, ErrorBanner, Field, Loading, PageHead } from "../../ui.jsx";

const STATE = {
  ok: { label: "Connected", tone: "ok", text: "Claude is answering normally." },
  error: { label: "Not working", tone: "bad", text: "Recent requests to Claude failed." },
  unknown: { label: "Not yet used", tone: "info", text: "No requests have been sent since the key was set. Run a test to check it." },
  demo: { label: "Demo mode", tone: "warn", text: "Characters give canned replies. Nothing is sent to Claude and nothing is billed." },
};
const SOURCE = {
  dashboard: "Saved from this page",
  environment: "Set on the server (ANTHROPIC_API_KEY)",
  none: "No key",
};

export default function AIConnection() {
  const { user } = useAuth();
  const canEdit = user.role === "admin";
  const { data, error, loading, reload, setData } = useApi("/api/admin/ai");

  if (loading && !data) return <Loading />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  const st = STATE[data.status.state] || STATE.unknown;

  return (
    <div className="page narrow">
      <PageHead title="AI connection"
        sub="How this site connects to Claude, the AI that voices scenario characters. The key is kept on the server and can't be viewed after it's saved." />

      <section className="panel section-panel" aria-labelledby="ai-status">
        <div className="panel-head">
          <h2 id="ai-status">Status</h2>
          <TestButton onDone={reload} />
        </div>
        <div className={`status-line ${st.tone}`}>
          <span className="status-dot" aria-hidden="true" />
          <div>
            <b>{st.label}</b>
            <p>{data.status.message || st.text}</p>
          </div>
        </div>
        <dl className="facts">
          <div><dt>Last successful reply</dt><dd>{data.status.last_ok_at ? fmtDateTime(data.status.last_ok_at) : "None yet"}{data.status.last_latency_ms ? `, ${(data.status.last_latency_ms / 1000).toFixed(1)} s` : ""}</dd></div>
          <div><dt>Last failure</dt><dd>{data.status.last_error_at ? fmtDateTime(data.status.last_error_at) : "None"}</dd></div>
          <div><dt>Model</dt><dd><code>{data.model}</code></dd></div>
          <div><dt>Background safety review</dt><dd>{data.ai_review ? "On" : "Off"}</dd></div>
        </dl>
      </section>

      <KeySection data={data} canEdit={canEdit} onChange={setData} />
      <ModelSection data={data} canEdit={canEdit} onChange={setData} />

      <section className="panel section-panel" aria-labelledby="ai-keep">
        <h2 id="ai-keep">Keeping the connection running</h2>
        <ul className="plain-list">
          <li>API keys don't expire. A key stops working only if it's deleted in the Anthropic Console or the account runs out of credit.</li>
          <li>In the Anthropic Console, under Billing, turn on <b>auto-reload</b> so credit is topped up before it runs out, and set a monthly spend limit you're comfortable with.</li>
          <li>Create a key just for this site, so you can replace it here without affecting anything else.</li>
          <li>If replies stop, this page shows why, and administrators see a warning on their overview.</li>
        </ul>
        <p className="small muted">What is sent to Claude: the scenario text and the student's messages in that conversation. Student names and email addresses are never sent.</p>
      </section>
    </div>
  );
}

function TestButton({ onDone }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api("/api/admin/ai/test", { method: "POST" });
      toast(r.message, r.ok ? "ok" : "error");
      onDone();
    } catch (e) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return <button className="btn" onClick={run} disabled={busy}>{busy ? "Testing…" : "Test connection"}</button>;
}

function KeySection({ data, canEdit, onChange }) {
  const toast = useToast();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [confirm, setConfirm] = useState(false);
  const save = async (e) => {
    e.preventDefault(); setBusy(true); setErr(null);
    try {
      const r = await api("/api/admin/ai/key", { method: "PUT", body: { api_key: key.trim() } });
      setKey(""); onChange(r);
      toast(r.warning || "Key saved and tested. Live conversations are on.", r.warning ? "error" : "ok");
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <section className="panel section-panel" aria-labelledby="ai-key">
      <h2 id="ai-key">API key</h2>
      {data.key_unreadable && (
        <div className="banner error">A key was saved here, but it can't be read because the server's SECRET_KEY changed. Add the key again.</div>
      )}
      <dl className="facts">
        <div><dt>Key in use</dt><dd>{data.key_hint ? <code>{data.key_hint}</code> : <span className="muted">None</span>}</dd></div>
        <div><dt>Where it comes from</dt><dd>{SOURCE[data.source]}</dd></div>
        {data.updated_at && <div><dt>Last changed</dt><dd>{fmtDateTime(data.updated_at)}{data.updated_by ? ` by ${data.updated_by}` : ""}</dd></div>}
      </dl>
      {canEdit && (
        <form className="key-form stack" onSubmit={save}>
          <ErrorBanner error={err} />
          <Field label={data.key_hint ? "Replace with a new key" : "Add a key"}
            hint="Create one in the Anthropic Console under API keys. It starts with “sk-ant-”. We test it before saving.">
            {(id) => <input id={id} type="password" autoComplete="off" spellCheck={false} value={key}
              placeholder="sk-ant-…" onChange={(e) => setKey(e.target.value)} />}
          </Field>
          <div className="row">
            <button className="btn primary" disabled={busy || key.trim().length < 20}>{busy ? "Testing key…" : "Save and test key"}</button>
            {data.source === "dashboard" && (
              <button type="button" className="btn danger" onClick={() => setConfirm(true)}>Remove saved key</button>
            )}
          </div>
          {data.source === "environment" && (
            <p className="small muted">A key saved here takes priority over the one set on the server.</p>
          )}
        </form>
      )}
      {confirm && (
        <Confirm title="Remove the saved key?" danger confirmLabel="Remove key" onClose={() => setConfirm(false)}
          onConfirm={async () => {
            try { const r = await api("/api/admin/ai/key", { method: "DELETE" }); onChange(r); toast("Key removed."); }
            catch (x) { setErr(x); }
          }}>
          <p>{data.environment_key_hint
            ? `The site will go back to using the key set on the server (${data.environment_key_hint}).`
            : "There's no other key, so the site will switch to demo mode and characters will give canned replies."}</p>
        </Confirm>
      )}
    </section>
  );
}

function ModelSection({ data, canEdit, onChange }) {
  const toast = useToast();
  const [f, setF] = useState({ mode: data.mode, model: data.model, ai_review: data.ai_review });
  const [err, setErr] = useState(null);
  useEffect(() => setF({ mode: data.mode, model: data.model, ai_review: data.ai_review }), [data.mode, data.model, data.ai_review]);
  const changed = f.mode !== data.mode || f.model !== data.model || f.ai_review !== data.ai_review;
  const save = async (e) => {
    e.preventDefault(); setErr(null);
    try { const r = await api("/api/admin/ai", { method: "PATCH", body: f }); onChange(r); toast("AI settings saved."); }
    catch (x) { setErr(x); }
  };
  const options = data.models.includes(f.model) ? data.models : [...data.models, f.model];
  return (
    <section className="panel section-panel" aria-labelledby="ai-model">
      <h2 id="ai-model">Model and behaviour</h2>
      <form className="stack" onSubmit={save}>
        <ErrorBanner error={err} />
        <fieldset className="radio-group" disabled={!canEdit}>
          <legend>Conversations</legend>
          <label className="check"><input type="radio" name="mode" checked={f.mode === "claude"} disabled={!data.key_hint}
            onChange={() => setF({ ...f, mode: "claude" })} />
            <span><b>Live</b><br /><span className="muted small">Characters are voiced by Claude.{!data.key_hint && " Add a key first."}</span></span></label>
          <label className="check"><input type="radio" name="mode" checked={f.mode === "mock"}
            onChange={() => setF({ ...f, mode: "mock", ai_review: false })} />
            <span><b>Demo</b><br /><span className="muted small">Canned replies, for training or trying the site without cost.</span></span></label>
        </fieldset>
        <Field label="Model" hint="Haiku is fastest and cheapest and suits most classroom scenarios. Sonnet and Opus give richer replies but answer more slowly and cost more.">
          {(id) => (
            <select id={id} value={f.model} disabled={!canEdit} onChange={(e) => setF({ ...f, model: e.target.value })}>
              {options.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>)}
        </Field>
        <label className="check">
          <input type="checkbox" checked={f.ai_review} disabled={!canEdit || f.mode !== "claude"} onChange={(e) => setF({ ...f, ai_review: e.target.checked })} />
          <span><b>Background safety review</b><br /><span className="muted small">After each reply, Claude double-checks the exchange and flags anything concerning for administrators. Adds no delay for students.</span></span>
        </label>
        {canEdit && <div><button className="btn primary" disabled={!changed}>Save settings</button></div>}
      </form>
    </section>
  );
}
