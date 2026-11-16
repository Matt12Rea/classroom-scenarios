// The student's scenario player (UC-02, UC-03, UC-04). Instructors see the same
// screen when previewing a scenario, plus the current scene's paths.
// There are no decision buttons: the server reads what the student says and
// moves the scene on when their approach matches one of the scene's paths.
import { useEffect, useRef, useState } from "react";
import Script from "../components/Script.jsx";
import { api, navigate, OUTCOME_LABEL, useApi, useAuth, useToast } from "../lib.jsx";
import { Breadcrumbs, ErrorBanner, Loading, Modal } from "../ui.jsx";

const MAX_CHARS = 1500;

export default function Play({ sessionId }) {
  const { user } = useAuth();
  const toast = useToast();
  const { data: state, error, loading, reload, setData } = useApi(`/api/sessions/${sessionId}`, [sessionId]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [slow, setSlow] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [failedText, setFailedText] = useState("");
  const [reporting, setReporting] = useState(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  const count = state?.messages.length;
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }, [count, sending]);

  if (loading && !state) return <Loading label="Loading scenario…" />;
  if (error) return <ErrorBanner error={error} onRetry={reload} />;
  if (!state) return null;

  const isPreview = state.is_preview;
  const done = state.status === "completed";
  const node = state.node;
  const ch = node.character;
  const backTo = isPreview ? `/scenarios/${state.scenario.id}` : "/";

  async function send(e, retryText) {
    e?.preventDefault();
    const msg = (retryText ?? text).trim();
    if (!msg || sending) return;
    setSending(true); setActionError(null); setSlow(false);
    const slowTimer = setTimeout(() => setSlow(true), 2500);     // NFR-5.1.6
    if (!retryText) setText("");
    try {
      const st = await api(`/api/sessions/${sessionId}/turn`, { method: "POST", body: { text: msg } });
      setData(st); setFailedText("");
      if (st.advanced) {
        if (st.status === "completed") toast(st.advanced.forced ? "Out of messages. The scenario has wrapped up." : "Scenario complete.");
        else toast(`New scene: ${st.node.title}`);
      }
    } catch (err) {
      setActionError(err);
      if (err.status === 503 || err.status === 0) setFailedText(msg);   // offer a one-click retry
      else if (!retryText) setText(msg);
    } finally {
      clearTimeout(slowTimer); setSending(false); setSlow(false);
      inputRef.current?.focus();
    }
  }

  async function finish() {
    setActionError(null);
    try { const st = await api(`/api/sessions/${sessionId}/finish`, { method: "POST" }); setData(st); toast("Scenario complete."); }
    catch (err) { setActionError(err); }
  }

  async function restart() {
    try {
      const st = await api("/api/sessions", { method: "POST",
        body: { scenario_id: state.scenario.id, restart: true, preview: isPreview } });
      navigate(isPreview ? `/preview/${st.id}` : `/play/${st.id}`);
    } catch (err) { setActionError(err); }
  }

  const pct = Math.round((state.progress.visited / Math.max(1, state.progress.total)) * 100);

  return (
    <div className="play">
      <aside className="brief" aria-label="Scenario briefing">
        <div>
          {isPreview
            ? <Breadcrumbs items={[["/scenarios", "Scenarios"], [backTo, "Editor"], [null, "Preview"]]} />
            : <a className="small" href="/">My scenarios</a>}
          <h1>{state.scenario.title}</h1>
          {isPreview && <p className="badge info plain" style={{ marginTop: 8 }}>Preview. Not saved to results.</p>}
        </div>
        <section className="brief-sec">
          <h2>Setting</h2>
          <p className="case-text">{state.scenario.setting}</p>
        </section>
        <section className="brief-sec">
          <h2>Your goals</h2>
          <ul>{state.scenario.objectives.map((o) => <li key={o}>{o}</li>)}</ul>
        </section>
        <section className="brief-sec">
          <h2>People in this scenario</h2>
          <ul className="cast">
            {state.scenario.characters.map((c) => <li key={c.id}><b>{c.name}</b> <span className="muted">{c.role}</span></li>)}
          </ul>
        </section>
        <section className="brief-sec">
          <h2>Progress</h2>
          <div className="progress-track" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}
            aria-label="Scenes reached"><span style={{ width: `${pct}%` }} /></div>
          <p className="small muted" style={{ margin: "6px 0 0" }}>
            {done ? "Finished. " : ""}{state.turns} of {state.max_turns} messages used.
          </p>
        </section>
      </aside>

      <section aria-label="Scenario">
        <Script state={state} tools={done ? null : (m) => m.role === "assistant" && (
          <button className="btn quiet small" onClick={() => setReporting(m)} aria-label={`Report this message from ${m.speaker}`}>Report</button>
        )}>
          {sending && <p className="typing" role="status"><span className="dots" aria-hidden="true"><i /><i /><i /></span>{ch.name} is replying…{slow ? " This is taking longer than usual." : ""}</p>}
          {done && state.outcome && (
            <div className={`ending ${state.outcome.type}`} role="status">
              <span className={`badge ${state.outcome.type}`}>{OUTCOME_LABEL[state.outcome.type]}</span>
              <h2>{state.outcome.label}</h2>
              {state.outcome.teacher_feedback && <p>{state.outcome.teacher_feedback}</p>}
              {state.outcome.ai_feedback && (<><h3 style={{ marginTop: 16 }}>Feedback</h3><p>{state.outcome.ai_feedback}</p></>)}
              <h3 style={{ marginTop: 16 }}>Your path</h3>
              <ol className="path">{state.path.map((p, i) => <li key={i}>{p.choice}</li>)}</ol>
              <div className="row" style={{ marginTop: 16 }}>
                <a className="btn primary" href={backTo}>{isPreview ? "Back to editor" : "Back to my scenarios"}</a>
                <button className="btn" onClick={restart}>Try again</button>
              </div>
            </div>
          )}
          <div ref={endRef} />
        </Script>

        {!done && (
          <div className="dock">
            <ErrorBanner error={actionError} />
            {failedText && (
              <div className="row"><button className="btn" onClick={() => send(null, failedText)} disabled={sending}>Send again</button>
                <span className="small muted">“{failedText.slice(0, 60)}{failedText.length > 60 ? "…" : ""}”</span></div>
            )}
            {state.ai_paused ? (
              <div className="banner warn">{isPreview
                ? <><b>Preview paused.</b> A student's session would now wait for an administrator. Start a new preview from the editor.</>
                : <><b>This session is paused for review.</b> You can continue once an administrator resumes it.</>}</div>
            ) : state.turns >= state.max_turns ? (
              <div className="banner info row"><span>You've used all your messages.</span>
                <button className="btn primary small" onClick={finish}>Finish scenario</button></div>
            ) : (
              <form className="composer" onSubmit={send}>
                <div className="grow">
                  <label htmlFor="say" className="sr-only">Your message to {ch.name}</label>
                  <textarea id="say" ref={inputRef} value={text} maxLength={MAX_CHARS} rows={2}
                    placeholder={`Reply to ${ch.name}, or describe what you do…`} disabled={sending}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }} />
                  <div className="count" aria-hidden="true">{[state.max_turns - state.turns <= 3 && `${state.max_turns - state.turns} message${state.max_turns - state.turns === 1 ? "" : "s"} left`, text.length > MAX_CHARS - 200 && `${MAX_CHARS - text.length} characters left`].filter(Boolean).join(". ")}</div>
                </div>
                <button className="btn primary" type="submit" disabled={sending || !text.trim()} style={{ marginBottom: 22 }}>
                  {sending ? "Sending…" : "Send"}
                </button>
              </form>
            )}
            {state.insight && node.paths?.length > 0 && <PathsPanel node={node} />}
          </div>
        )}
      </section>
      {reporting && <ReportDialog sessionId={sessionId} message={reporting} onClose={() => setReporting(null)} />}
    </div>
  );
}

// Instructor-only: what the judge is listening for in this scene. Never sent to students.
function PathsPanel({ node }) {
  const before = Math.max(0, node.min_turns - node.turns_here);
  const wrap = node.wrap_after ? Math.max(0, node.wrap_after - node.turns_here) : null;
  return (
    <details className="insight-panel">
      <summary>Instructor view: this scene's paths</summary>
      <p className="small muted">
        {before > 0 ? `Can move on after ${before} more message${before === 1 ? "" : "s"}. ` : "Can move on now. "}
        {wrap !== null ? `Wraps up after ${wrap} more.` : "No message limit for this scene."}
      </p>
      <ol>{node.paths.map((p) => <li key={p.label}><b>{p.label}</b>{p.signal && <span className="muted">: {p.signal}</span>}</li>)}</ol>
    </details>
  );
}

export function ReportDialog({ sessionId, message, onClose }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const [err, setErr] = useState(null);
  const submit = async () => {
    try {
      await api(`/api/sessions/${sessionId}/report`, { method: "POST", body: { message_id: message?.id, reason } });
      toast("Report sent. An administrator will review it."); onClose();
    } catch (e) { setErr(e); }
  };
  return (
    <Modal title="Report this message" onClose={onClose}>
      {message && <blockquote className="quote">{message.content}</blockquote>}
      <ErrorBanner error={err} />
      <div className="field">
        <label htmlFor="reason">What's wrong with it?</label>
        <textarea id="reason" value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="For example: rude, upsetting, or off-topic." />
      </div>
      <div className="modal-foot">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={reason.trim().length < 3} onClick={submit}>Send report</button>
      </div>
    </Modal>
  );
}
