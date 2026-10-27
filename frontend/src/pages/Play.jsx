// The student's scenario player (UC-02, UC-03, UC-04). Teachers see the same
// screen when previewing a scenario.
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
  const [deciding, setDeciding] = useState(null);
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
  const remaining = node.min_turns - node.turns_here;
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
    } catch (err) {
      setActionError(err);
      if (err.status === 503 || err.status === 0) setFailedText(msg);   // offer a one-click retry
      else if (!retryText) setText(msg);
    } finally {
      clearTimeout(slowTimer); setSending(false); setSlow(false);
      inputRef.current?.focus();
    }
  }

  async function decide(label) {
    setDeciding(label); setActionError(null);
    try {
      const st = await api(`/api/sessions/${sessionId}/decision`, { method: "POST", body: { choice: label } });
      setData(st);
      if (st.status === "completed") toast("Scenario complete.");
    } catch (err) { setActionError(err); } finally { setDeciding(null); }
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
          <Breadcrumbs items={isPreview ? [["/scenarios", "Scenarios"], [backTo, "Editor"], [null, "Preview"]] : [["/", "My scenarios"], [null, state.scenario.title]]} />
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
            {done ? "Finished." : `Scene ${state.path.length + 1}.`} {state.turns} of {state.max_turns} messages used.
          </p>
        </section>
        <p className="small muted">Your conversation is saved so you can come back later. Teachers and school administrators can read it.</p>
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
              {state.outcome.ai_feedback && (<><h3 style={{ marginTop: 16 }}>Feedback on how you did</h3><p>{state.outcome.ai_feedback}</p></>)}
              <h3 style={{ marginTop: 16 }}>The path you took</h3>
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
              <div className="banner warn">Conversation is paused for this scenario. You can still make a decision below.</div>
            ) : state.turns >= state.max_turns ? (
              <div className="banner info">You've used all your messages. Choose a decision to continue.</div>
            ) : (
              <form className="composer" onSubmit={send}>
                <div className="grow">
                  <label htmlFor="say" className="sr-only">Your message to {ch.name}</label>
                  <textarea id="say" ref={inputRef} value={text} maxLength={MAX_CHARS} rows={2}
                    placeholder={`Say something to ${ch.name}…`} disabled={sending}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }} />
                  <div className="count" aria-hidden="true">Press Enter to send, Shift+Enter for a new line{text.length > MAX_CHARS - 200 ? `. ${MAX_CHARS - text.length} characters left.` : ""}</div>
                </div>
                <button className="btn primary" type="submit" disabled={sending || !text.trim()} style={{ marginBottom: 22 }}>
                  {sending ? "Sending…" : "Send"}
                </button>
              </form>
            )}
            {node.choices.length > 0 && (
              <div className="choices">
                <h2>What do you do?</h2>
                {node.choices_locked && !state.ai_paused && (
                  <p className="lock-note">Talk with {ch.name} first. Decisions unlock after {remaining} more message{remaining === 1 ? "" : "s"}.</p>
                )}
                <div className="choice-list">
                  {node.choices.map((c) => (
                    <button key={c.label} className="choice" disabled={(node.choices_locked && !state.ai_paused) || !!deciding || sending}
                      onClick={() => decide(c.label)}>
                      <span>{c.label}</span>{deciding === c.label && <span className="small muted">Saving…</span>}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </section>
      {reporting && <ReportDialog sessionId={sessionId} message={reporting} onClose={() => setReporting(null)} />}
    </div>
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
          placeholder="For example: it was rude, upsetting, or not about the scenario." />
      </div>
      <div className="modal-foot">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={reason.trim().length < 3} onClick={submit}>Send report</button>
      </div>
    </Modal>
  );
}
