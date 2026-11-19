import { Component, useEffect, useId, useRef, useState } from "react";
import { downloadFile, STATUS_LABEL, useToast } from "./lib.jsx";

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
  // Callers usually pass a new onClose function on every render. Reading it through a
  // ref keeps the effect below to open/close only; otherwise each re-render of the
  // parent would move focus back to the first field while someone is typing.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement;
    const el = ref.current;
    el?.querySelector("input, textarea, select, button")?.focus();
    const onKey = (e) => {
      // With a dialog opened from a dialog, only the one on top responds.
      const open = document.querySelectorAll(".modal");
      if (open.length && open[open.length - 1] !== el) return;
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab" && el) {     // keep keyboard focus inside the dialog
        const f = [...el.querySelectorAll("button, [href], input, select, textarea")].filter((x) => !x.disabled);
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
        else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, []);
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && closeRef.current()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  );
}

export function Confirm({ title, children, confirmLabel, danger, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  // The dialog closes only if the action worked. If it failed, it stays open and says why.
  const go = async () => {
    setBusy(true); setErr(null);
    try { await onConfirm(); onClose(); }
    catch (e) { setErr(e); }
    finally { setBusy(false); }
  };
  return (
    <Modal title={title} onClose={onClose}>
      <ErrorBanner error={err} />
      <div>{children}</div>
      <div className="modal-foot">
        <button className="btn quiet" onClick={onClose}>Cancel</button>
        <button className={`btn ${danger ? "danger" : "primary"}`} disabled={busy} onClick={go}>
          {busy ? "Working…" : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

/** Catches a crash while drawing a page, so one broken screen never blanks the whole
 *  app. The navigation stays usable and the person is told what to do next. */
export class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error, info) { console.error("Page crashed:", error, info?.componentStack); }
  componentDidUpdate(prev) { if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="empty" role="alert">
        <h3>This page ran into a problem</h3>
        <p>Nothing you saved was lost. Reload the page; if it happens again, tell an administrator what you were doing.</p>
        <div className="row" style={{ justifyContent: "center" }}>
          <button className="btn primary" onClick={() => location.reload()}>Reload page</button>
          <a className="btn" href="/">Go to the start page</a>
        </div>
      </div>
    );
  }
}

const ICONS = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z",
  shield: "M12 3 20 6v6c0 4.6-3.2 7.9-8 9-4.8-1.1-8-4.4-8-9V6Z",
  chat: "M4 5h16v11H9l-5 4Z",
  book: "M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3Zm0 13a3 3 0 0 1 3-3h10",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9c0-3.3 2.7-6 6-6s6 2.7 6 6M16 4.5a3.5 3.5 0 0 1 0 6.5M17.5 14.3c2.1.8 3.5 2.9 3.5 5.7",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-8 9c0-4.4 3.6-7 8-7s8 2.6 8 7",
  plug: "M9 3v5m6-5v5M6 8h12v3a6 6 0 0 1-12 0Zm6 9v4",
  list: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  download: "M12 4v11m0 0-4-4m4 4 4-4M5 20h14",
  pause: "M8 5v14M16 5v14",
  play: "M7 5v14l11-7Z",
  plus: "M12 5v14M5 12h14",
  check: "m5 12.5 4.5 4.5L19 7.5",
  alert: "M12 4 3 20h18Zm0 6v4m0 3h.01",
  arrow: "M5 12h14m0 0-5-5m5 5-5 5",
  trash: "M5 7h14M10 7V4h4v3m-7 0 1 13h8l1-13",
  copy: "M9 9h10v11H9ZM5 15V4h10",
  eye: "M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Zm9.5 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  chart: "M5 20V10m7 10V4m7 16v-7",
  flag: "M5 21V4h11l-2 4 2 4H5",
  up: "m6 15 6-6 6 6",
  down: "m6 9 6 6 6-6",
};

/** Small line icons, drawn in the current text colour. Decorative: always paired with a label. */
export function Icon({ name, size = 18 }) {
  const d = ICONS[name];
  if (!d) return null;
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={d} /></svg>
  );
}

/** A button that opens a short list of downloads, e.g. Export > PDF / CSV.
 *  items: [{ label, hint, path, filename }] */
export function ExportMenu({ label = "Export", items, small }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState("");
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const get = async (it) => {
    if (busy) return;
    setBusy(it.label); setOpen(false);
    try { await downloadFile(it.path, it.filename); toast(`${it.label} downloaded.`); }
    catch (e) { toast(e.message || "The export failed. Try again.", "error"); }
    finally { setBusy(""); }
  };
  return (
    <div className="export-menu" ref={ref}>
      <button className={`btn ${small ? "small" : ""}`} aria-haspopup="menu" aria-expanded={open} disabled={!!busy} onClick={() => setOpen(!open)}>
        <Icon name="download" size={16} />{busy ? "Preparing…" : label}
      </button>
      {open && (
        <div className="menu" role="menu">
          {items.map((it) => (
            <button key={it.label} role="menuitem" onClick={() => get(it)}>
              <b>{it.label}</b>{it.hint && <small>{it.hint}</small>}
            </button>
          ))}
        </div>
      )}
    </div>
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
