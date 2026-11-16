// Renders a session as a transcript: scene headings and narration (set like a
// case file), then each spoken line with the speaker in a left-hand column.
// When a scene moves on, a line shows the approach the student's words were
// matched to. Used by the student player and the instructor/admin views.
import { Fragment } from "react";

// Scenes are numbered like the acts of a case: I, II, III…
function roman(n) {
  const map = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
  let out = "";
  for (const [v, r] of map) while (n >= v) { out += r; n -= v; }
  return out;
}

export default function Script({ state, youLabel = "You", highlightId, tools, children }) {
  const seq = [state.start, ...state.path.map((p) => p.next)];
  const out = [];
  let sceneIdx = 0;
  let pending = true;

  const sceneHead = (key) => {
    const nid = seq[sceneIdx];
    const sc = state.scenes[nid] || { title: nid, prompt: "" };
    out.push(
      <Fragment key={key}>
        <div className="scene-head">
          <span className="scene-no">Scene {roman(sceneIdx + 1)}</span>
          <h2>{sc.title}</h2>
        </div>
        {sc.prompt && <p className="narration">{sc.prompt}</p>}
      </Fragment>,
    );
    pending = false;
  };

  state.messages.forEach((m, i) => {
    if (pending && !(m.role === "system" && (m.speaker === "Feedback" || m.speaker === "Inference"))) sceneHead(`scene-${i}`);
    const flagged = m.id === highlightId;
    const tool = tools?.(m);
    if (m.role === "system" && m.speaker === "Decision") {
      out.push(
        <div key={m.id} className="decision-line" id={`m${m.id}`}>
          <span className="decision-who">{youLabel === "You" ? "Your approach" : `${youLabel}'s approach`}</span>
          <span className="decision-what">{m.content}</span>
        </div>,
      );
      sceneIdx += 1;
      pending = true;
    } else if (m.role === "system" && m.speaker === "Inference") {
      // Only sent to instructors and admins: why the scene moved on.
      out.push(<p key={m.id} className="insight-line"><b>Why the scene moved on:</b> {m.content}</p>);
    } else if (m.role === "system" && m.speaker === "Feedback") {
      out.push(<p key={m.id} className="note-line"><span className="sr-only">Instructor's note: </span>{m.content}</p>);
    } else if (m.role === "system") {
      out.push(<div key={m.id} className="support-line" role="note">{m.content}</div>);
    } else {
      const you = m.role === "user";
      out.push(
        <div key={m.id} id={`m${m.id}`} className={`speech ${you ? "you" : ""} ${m.hidden ? "removed" : ""} ${flagged ? "flagged" : ""}`}>
          <div className="cue">{you ? youLabel : m.speaker}{m.hidden && youLabel !== "You" ? <small>Hidden</small> : null}</div>
          <p className="dialogue">{m.content}</p>
          {tool && <div className="msg-tools">{tool}</div>}
        </div>,
      );
    }
  });
  if (pending && sceneIdx < seq.length) sceneHead("scene-end");

  return (
    <div className="script">
      <div className="script-body" aria-live="polite" aria-relevant="additions">
        {out}
        {children}
      </div>
    </div>
  );
}
