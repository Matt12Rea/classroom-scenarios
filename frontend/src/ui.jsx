import { useEffect, useId, useRef, useState } from "react";
import { STATUS_LABEL } from "./lib.jsx";

export function Field({ label, hint, error, children, id }) {
  const auto = useId();
  const fid = id || auto;
  const child = typeof children === "function" ? children(fid) : children;
  return (
    <div className={`field ${error ? "invalid" : ""}`}>
      <label htmlFor={fid}>{label}</label>
      {hint && <span className="hint" id={`${fid}-hint`}>{hint}</span>}
      {child}
      {error && <span className="error-text" role="alert">{error}</span>}
    </div>
  );
}

/** Shows only if loading lasts more than ~1s (NFR-5.1.3), to avoid flicker. */
export function Loading({ label = "Loading…", delay = 350 }) {
  const [show, setShow] = useState(delay === 0);
  useEffect(() => { const t = setTimeout(() => setShow(true), delay); return () => clearTimeout(t); }, [delay]);
  return show ? <div className="spinner" role="status">{label}</div> : null;
}

export function ErrorBanner({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="banner error" role="alert">
      <div className="row between">
        <span>{error.message || String(error)}</span>
        {onRetry && <button className="btn small" onClick={onRetry}>Try again</button>}
      </div>
      {error.errors?.length > 0 && <ul>{error.errors.map((e, i) => <li key={i}>{e.message}</li>)}</ul>}
    </div>
  );
}

export function Status({ value, label }) {
  return <span className={`badge ${value}`}>{label || STATUS_LABEL[value] || value}</span>;
}

export function Empty({ title, children }) {
  return <div className="empty"><h3>{title}</h3>{children}</div>;
}

export function Modal({ title, onClose, children, wide }) {
  const ref = useRef(null);
  useEffect(() => {
    const prev = document.activeElement;
    const el = ref.current;
    el?.querySelector("input, textarea, select, button")?.focus();
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab" && el) {     // keep keyboard focus inside the dialog
        const f = [...el.querySelectorAll("button, [href], input, select, textarea")].filter((x) => !x.disabled);
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
        else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, children, confirmLabel, danger, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose}>
      <div>{children}</div>
      <div className="modal-foot">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? "danger" : "primary"}`} disabled={busy}
          onClick={async () => { setBusy(true); try { await onConfirm(); onClose(); } finally { setBusy(false); } }}>
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export function PageHead({ title, sub, children }) {
  return (
    <div className="page-head">
      <div><h1>{title}</h1>{sub && <p>{sub}</p>}</div>
      {children && <div className="row">{children}</div>}
    </div>
  );
}

export function ListEditor({ items, onChange, placeholder, addLabel, invalid }) {
  return (
    <div className="list-editor">
      {items.map((v, i) => (
        <div className="item" key={i}>
          <input type="text" value={v} placeholder={placeholder} aria-label={`${placeholder} ${i + 1}`}
            className={invalid && !v.trim() ? "invalid" : ""}
            onChange={(e) => onChange(items.map((x, j) => (j === i ? e.target.value : x)))} />
          <button className="btn quiet small" type="button" aria-label={`Remove item ${i + 1}`}
            onClick={() => onChange(items.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div><button className="btn small" type="button" onClick={() => onChange([...items, ""])}>{addLabel}</button></div>
    </div>
  );
}

/** The product mark: a path that branches into outcomes (problem-solving pathing). */
// The crest: a shield holding an open book, drawn in one colour (currentColor).
export function Logo({ size = 28, className = "logo" }) {
  return (
    <svg className={className} width={size} height={size * 36 / 32} viewBox="0 0 32 36" aria-hidden="true" focusable="false">
      <path d="M16 1.5 29 5v11.5c0 8.2-5.6 14.6-13 18-7.4-3.4-13-9.8-13-18V5Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M16 12.5c-2.6-1.7-5.4-2.2-8.2-1.8v12c2.8-.4 5.6.1 8.2 1.8 2.6-1.7 5.4-2.2 8.2-1.8v-12c-2.8-.4-5.6.1-8.2 1.8Z" fill="currentColor" opacity=".22" />
      <path d="M16 12.5c-2.6-1.7-5.4-2.2-8.2-1.8v12c2.8-.4 5.6.1 8.2 1.8m0-12c2.6-1.7 5.4-2.2 8.2-1.8v12c-2.8-.4-5.6.1-8.2 1.8m0-12v12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M16 5.2v3.2M14.4 6.8h3.2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function Breadcrumbs({ items }) {
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <ol>{items.map(([href, label], i) => (
        <li key={i}>{href && i < items.length - 1 ? <a href={href}>{label}</a> : <span aria-current={i === items.length - 1 ? "page" : undefined}>{label}</span>}</li>
      ))}</ol>
    </nav>
  );
}
