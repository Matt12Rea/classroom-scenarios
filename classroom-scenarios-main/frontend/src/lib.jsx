// API client, auth state, router and toasts. Small on purpose: no external
// dependencies beyond React, so the project is easy to read and maintain.
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const BASE = import.meta.env?.VITE_API_URL ?? "";
const TOKEN_KEY = "aicss.token";

export class ApiError extends Error {
  constructor(status, message, errors = []) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

let onUnauthorized = () => {};

function readToken() {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function writeToken(t) {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}

function errorFrom(status, body) {
  const d = body?.detail;
  if (typeof d === "string") return new ApiError(status, d);
  if (d && typeof d === "object" && !Array.isArray(d)) return new ApiError(status, d.message || "Request failed.", d.errors || []);
  if (Array.isArray(d)) {   // FastAPI field validation
    const errs = d.map((e) => ({ field: (e.loc || []).slice(1).join("."), message: e.msg }));
    return new ApiError(status, "Some fields need attention.", errs);
  }
  if (status >= 500) return new ApiError(status, "The server had a problem. Your saved work is safe. Try again in a moment.");
  return new ApiError(status, "Request failed.");
}

// Longest we wait for the server. AI replies can take a while, so this is generous;
// without it a dropped connection would leave a button spinning for ever.
const TIMEOUT_MS = 90_000;

export async function api(path, { method = "GET", body, raw = false, retries, timeout = TIMEOUT_MS } = {}) {
  const headers = {};
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // Only safe (GET) requests are retried automatically, so nothing is ever duplicated.
  let attempts = retries ?? (method === "GET" ? 2 : 0);
  for (;;) {
    let res;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeout);
    try {
      res = await fetch(BASE + path, { method, headers, signal: ctl.signal, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (e) {
      clearTimeout(timer);
      if (e?.name === "AbortError") throw new ApiError(0, "The server took too long to answer. Check your connection and try again.");
      if (attempts-- > 0) { await new Promise((r) => setTimeout(r, 700)); continue; }
      throw new ApiError(0, "Can't reach the server. Check your internet connection and try again.");
    }
    clearTimeout(timer);
    if (res.status === 401 && token) { onUnauthorized(); }
    if (!res.ok) {
      if (res.status >= 502 && res.status !== 503 && attempts-- > 0) { await new Promise((r) => setTimeout(r, 700)); continue; }
      let data = null;
      try { data = await res.json(); } catch { /* not json */ }
      throw errorFrom(res.status, data);
    }
    if (raw) return res;
    if (res.status === 204) return null;
    try { return await res.json(); }
    catch { throw new ApiError(res.status, "The server sent a reply this page couldn't read. Reload and try again."); }
  }
}

export async function downloadFile(path, fallbackName) {
  const res = await api(path, { raw: true, timeout: 180_000 });
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] || fallbackName;
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ------------------------------------------------------------------- auth --
const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState("");
  const lastActive = useRef(Date.now());

  const logout = useCallback((message = "") => {
    writeToken(null); setUser(null); setNotice(message); navigate("/");
  }, []);

  useEffect(() => {
    onUnauthorized = () => logout("Your session ended. Please sign in again.");
    if (!readToken()) { setReady(true); return; }
    api("/api/auth/me").then(setUser).catch(() => writeToken(null)).finally(() => setReady(true));
  }, [logout]);

  // Keep active users signed in; idle users time out (NFR-5.3.5).
  useEffect(() => {
    if (!user) return;
    const mark = () => { lastActive.current = Date.now(); };
    const evs = ["keydown", "pointerdown", "scroll"];
    evs.forEach((e) => window.addEventListener(e, mark, { passive: true }));
    const id = setInterval(() => {
      if (Date.now() - lastActive.current < 10 * 60 * 1000) {
        api("/api/auth/refresh", { method: "POST" }).then((r) => writeToken(r.token)).catch(() => {});
      }
    }, 10 * 60 * 1000);
    return () => { clearInterval(id); evs.forEach((e) => window.removeEventListener(e, mark)); };
  }, [user]);

  const login = async (email, password) => {
    const r = await api("/api/auth/login", { method: "POST", body: { email, password } });
    writeToken(r.token); setNotice(""); setUser(r.user); navigate("/");
  };
  const replaceToken = (r) => { writeToken(r.token); if (r.user) setUser(r.user); };

  return <AuthCtx.Provider value={{ user, ready, login, logout, notice, replaceToken, setUser }}>{children}</AuthCtx.Provider>;
}

// ----------------------------------------------------------------- router --
// Normal URLs (/scenarios/4), using the browser History API. The server sends
// index.html for any page address, so links can be bookmarked and shared.
const ROUTE_EVENT = "aicss:navigate";

// A page with unsaved work (the scenario builder) sets a question to ask before leaving.
let leaveGuard = null;
export function setLeaveGuard(question) { leaveGuard = question || null; }

export function navigate(path, { replace = false, force = false } = {}) {
  if (location.pathname + location.search === path) return;
  if (leaveGuard && !force && !window.confirm(leaveGuard)) return;
  leaveGuard = null;
  history[replace ? "replaceState" : "pushState"](null, "", path);
  window.dispatchEvent(new Event(ROUTE_EVENT));
}

// Old links used "#/path". Send them to the same page at its new address.
if (location.hash.startsWith("#/")) history.replaceState(null, "", location.hash.slice(1));

// Handle clicks on ordinary <a href="/..."> links inside the app without a page reload.
if (typeof document !== "undefined") {
  document.addEventListener("click", (e) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest?.("a[href]");
    if (!a || a.target || a.hasAttribute("download")) return;
    const href = a.getAttribute("href");
    if (!href.startsWith("/") || href.startsWith("//") || href.startsWith("/api/")) return;
    e.preventDefault();
    navigate(href);
  });
}

export function useRoute() {
  const get = () => location.pathname + location.search;
  const [path, setPath] = useState(get);
  useEffect(() => {
    const on = () => { setPath(get()); window.scrollTo(0, 0); };
    window.addEventListener("popstate", on);
    window.addEventListener(ROUTE_EVENT, on);
    return () => { window.removeEventListener("popstate", on); window.removeEventListener(ROUTE_EVENT, on); };
  }, []);
  const [pathname, query = ""] = path.split("?");
  return { path: pathname.replace(/\/+$/, "") || "/", query: new URLSearchParams(query) };
}

/** match("/scenarios/:id", "/scenarios/4") -> {id: "4"} or null */
export function match(pattern, path) {
  const p = pattern.split("/"), s = path.split("/");
  if (p.length !== s.length) return null;
  const params = {};
  for (let i = 0; i < p.length; i++) {
    if (p[i].startsWith(":")) params[p[i].slice(1)] = decodeURIComponent(s[i]);
    else if (p[i] !== s[i]) return null;
  }
  return params;
}

// ----------------------------------------------------------------- toasts --
const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((message, kind = "ok") => {
    const id = Math.random();
    setItems((x) => [...x, { id, message, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span className="grow">{t.message}</span>
            <button aria-label="Dismiss" onClick={() => setItems((x) => x.filter((y) => y.id !== t.id))}>×</button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

// ------------------------------------------------------------ data hook --
// Loads `path` and reloads when it changes. If the path changes again before the
// first answer arrives (typing in a search box), the older answer is ignored, so a
// slow early request can never overwrite a newer one. Data from the previous load
// stays on screen while the next one is in flight.
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: !!path });
  const seq = useRef(0);
  const load = useCallback(() => {
    if (!path) return;
    const mine = ++seq.current;
    setState((s) => ({ ...s, loading: true, error: null }));
    api(path).then((data) => { if (mine === seq.current) setState({ data, error: null, loading: false }); })
      .catch((error) => { if (mine === seq.current) setState((s) => ({ data: s.data, error, loading: false })); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(() => { load(); return () => { seq.current++; }; }, [load]);
  const setData = useCallback((data) => setState((s) => ({ ...s, data })), []);
  return { ...state, reload: load, setData };
}

/** The value, but only after it has stopped changing for `ms` (for search boxes). */
export function useDebounced(value, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [value, ms]);
  return v;
}

/** Run an async action once at a time: returns [run, busy]. Extra clicks while it is
 *  running are ignored, so nothing is submitted twice. */
export function useBusy() {
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const run = useCallback(async (fn) => {
    if (lock.current) return undefined;
    lock.current = true; setBusy(true);
    try { return await fn(); } finally { lock.current = false; setBusy(false); }
  }, []);
  return [run, busy];
}

/** "Ana Torres", "Ana Torres and Luis Torres", "A, B and C". */
export function nameList(names) {
  const n = names.filter(Boolean);
  if (n.length <= 1) return n[0] || "the character";
  return `${n.slice(0, -1).join(", ")} and ${n.at(-1)}`;
}

export const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
export const fmtDateTime = (iso) => iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
export const ROLE_LABEL = { student: "Student", teacher: "Instructor", admin: "Administrator", it_support: "IT support" };
export const STATUS_LABEL = {
  not_started: "Not started", in_progress: "In progress", completed: "Completed", abandoned: "Restarted",
  draft: "Draft", published: "Published", archived: "Archived",
  open: "Open", dismissed: "Dismissed", actioned: "Action taken",
};
export const OUTCOME_LABEL = { success: "Success", partial: "Partial", fail: "Didn't succeed" };
export const CATEGORY_LABEL = {
  manipulation: "Baiting the AI", self_harm: "Self-harm concern", violence: "Violence or threat",
  harassment: "Abusive language", sexual: "Sexual content", personal_info: "Personal info shared",
  ai_output: "AI reply problem", repeated: "Repeated misuse", other: "Other",
};
export const SEVERITY_LABEL = { high: "Serious", medium: "Medium", low: "Low" };
