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

export async function api(path, { method = "GET", body, raw = false, retries } = {}) {
  const headers = {};
  const token = readToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  // Only safe (GET) requests are retried automatically, so nothing is ever duplicated.
  let attempts = retries ?? (method === "GET" ? 2 : 0);
  for (;;) {
    let res;
    try {
      res = await fetch(BASE + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch {
      if (attempts-- > 0) { await new Promise((r) => setTimeout(r, 700)); continue; }
      throw new ApiError(0, "Can't reach the server. Check your internet connection and try again.");
    }
    if (res.status === 401 && token) { onUnauthorized(); }
    if (!res.ok) {
      if (res.status >= 502 && res.status !== 503 && attempts-- > 0) { await new Promise((r) => setTimeout(r, 700)); continue; }
      let data = null;
      try { data = await res.json(); } catch { /* not json */ }
      throw errorFrom(res.status, data);
    }
    if (raw) return res;
    return res.status === 204 ? null : res.json();
  }
}

export async function downloadFile(path, fallbackName) {
  const res = await api(path, { raw: true });
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

export function navigate(path, { replace = false } = {}) {
  if (location.pathname + location.search === path) return;
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
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const load = useCallback(() => {
    if (!path) return;
    setState((s) => ({ ...s, loading: true, error: null }));
    api(path).then((data) => setState({ data, error: null, loading: false }))
      .catch((error) => setState({ data: null, error, loading: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  useEffect(load, [load]);
  return { ...state, reload: load, setData: (data) => setState((s) => ({ ...s, data })) };
}

export const fmtDate = (iso) => iso ? new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
export const fmtDateTime = (iso) => iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
export const ROLE_LABEL = { student: "Student", teacher: "Teacher", admin: "Administrator", it_support: "IT support" };
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
