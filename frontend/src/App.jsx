import { useEffect, useRef, useState } from "react";
import { AuthProvider, match, ROLE_LABEL, ToastProvider, useApi, useAuth, useRoute } from "./lib.jsx";
import { Loading, Logo } from "./ui.jsx";
import { ChangePassword, Help, Login, StudentHome } from "./pages/Common.jsx";
import Play from "./pages/Play.jsx";
import Editor from "./pages/teacher/Editor.jsx";
import { Classes, Results, ScenarioList, TeacherHome } from "./pages/teacher/Teacher.jsx";
import { AdminHome, Audit, FlagDetail, Flags, Interactions, SessionView, SystemStatus, Users } from "./pages/admin/Admin.jsx";
import AIConnection from "./pages/admin/AIConnection.jsx";

// Each role sees only its own navigation and routes (REQ-3.6.2).
// Navigation is grouped so the same items always appear in the same place (NFR-5.4.2).
const NAV = {
  student: [[null, [["/", "My scenarios"]]]],
  teacher: [[null, [["/", "Overview"], ["/scenarios", "Scenarios"], ["/classes", "Classes"]]]],
  admin: [
    [null, [["/", "Overview"]]],
    ["Oversight", [["/flags", "Safety review"], ["/interactions", "Conversations"]]],
    ["Teaching", [["/scenarios", "Scenarios"], ["/classes", "Classes"]]],
    ["Administration", [["/users", "Users and roles"], ["/ai", "AI connection"], ["/audit", "Audit log"]]],
  ],
  it_support: [[null, [["/", "System status"], ["/ai", "AI connection"]]]],
};

const ROUTES = {
  student: [["/", StudentHome], ["/play/:id", ({ id }) => <Play sessionId={id} />]],
  teacher: [["/", TeacherHome], ["/scenarios", ScenarioList], ["/scenarios/:id", ({ id }) => <Editor id={id} />],
    ["/scenarios/:id/results", ({ id }) => <Results id={id} />], ["/classes", Classes],
    ["/sessions/:id", ({ id }) => <SessionView id={id} />], ["/preview/:id", ({ id }) => <Play sessionId={id} />]],
  admin: [["/", AdminHome], ["/flags", Flags], ["/flags/:id", ({ id }) => <FlagDetail id={id} />], ["/interactions", Interactions],
    ["/users", Users], ["/classes", Classes], ["/scenarios", ScenarioList], ["/scenarios/:id", ({ id }) => <Editor id={id} />],
    ["/scenarios/:id/results", ({ id }) => <Results id={id} />], ["/sessions/:id", ({ id }) => <SessionView id={id} />],
    ["/preview/:id", ({ id }) => <Play sessionId={id} />], ["/audit", Audit], ["/ai", AIConnection]],
  it_support: [["/", SystemStatus], ["/ai", AIConnection]],
};
const SHARED = [["/help", Help], ["/account", () => <ChangePassword />]];

function UserMenu({ user, logout }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const initials = user.name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div className="user-menu" ref={ref}>
      <button className="user-btn" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)}>
        <span className="avatar" aria-hidden="true">{initials}</span>
        <span className="user-name">{user.name}<small>{ROLE_LABEL[user.role]}</small></span>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
      </button>
      {open && (
        <div className="menu" role="menu">
          <div className="menu-id">{user.email}</div>
          <a role="menuitem" href="/account" onClick={() => setOpen(false)}>Change password</a>
          <a role="menuitem" href="/help" onClick={() => setOpen(false)}>Help</a>
          <button role="menuitem" onClick={() => logout("You've signed out.")}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function Shell() {
  const { user, ready, logout } = useAuth();
  const { path } = useRoute();
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [path]);
  const { data: openFlags } = useApi(user?.role === "admin" ? "/api/admin/flags?status=open" : null, [path]);

  useEffect(() => {
    const label = NAV[user?.role]?.flatMap(([, items]) => items).find(([to]) => to !== "/" && path.startsWith(to))?.[1];
    document.title = label ? `${label} | Classroom Scenarios` : "Classroom Scenarios";
  }, [path, user]);

  if (!ready) return <div className="boot"><Loading /></div>;
  if (!user) return <Login />;
  if (user.must_change_password) {
    return (
      <div className="app">
        <header className="masthead"><a className="wordmark" href="/"><Logo /><span>Classroom Scenarios</span></a></header>
        <main className="main solo" id="main"><ChangePassword forced /></main>
      </div>
    );
  }

  let page = null;
  for (const [pattern, C] of [...ROUTES[user.role], ...SHARED]) {
    const params = match(pattern, path);
    if (params) { page = <C {...params} />; break; }
  }
  if (!page) {
    page = (
      <div className="empty"><h3>This page isn't available</h3>
        <p>It may have moved, or your account doesn't have access to it. Ask an administrator if you think you should.</p>
        <a className="btn" href="/">Go to overview</a></div>
    );
  }
  // Pages reached from a list keep that list's navigation item highlighted.
  const PARENT = { "/play": "/", "/preview": "/scenarios", "/sessions": user.role === "admin" ? "/interactions" : "/scenarios" };
  const section = PARENT[`/${path.split("/")[1]}`];
  const current = (to) => (to === "/" ? path === "/" || section === "/" : path === to || path.startsWith(to + "/") || section === to);
  const hasSide = user.role !== "student";
  const flagCount = openFlags?.length || 0;

  return (
    <div className="app">
      <a href="#main" className="skip" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to main content</a>
      <header className="masthead">
        {hasSide && <button className="menu-toggle" onClick={() => setMenu(true)} aria-label="Open navigation" aria-expanded={menu}>
          <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18" stroke="currentColor" strokeWidth="2" /></svg>
        </button>}
        <a className="wordmark" href="/"><Logo /><span>Classroom Scenarios</span></a>
        <div className="masthead-end">
          {!hasSide && <a className="masthead-link" href="/" aria-current={path === "/" ? "page" : undefined}>My scenarios</a>}
          <a className="masthead-link" href="/help">Help</a>
          <UserMenu user={user} logout={logout} />
        </div>
      </header>
      <div className={`shell ${hasSide ? "" : "no-side"}`}>
        {hasSide && <nav className={`side ${menu ? "open" : ""}`} aria-label="Main" onClick={(e) => e.target === e.currentTarget && setMenu(false)}>
          <div className="side-inner">
            {NAV[user.role].map(([group, items]) => (
              <div className="nav-group" key={group || "main"}>
                {group && <div className="nav-label">{group}</div>}
                {items.map(([to, label]) => (
                  <a key={to} href={to} aria-current={current(to) ? "page" : undefined}>
                    <span>{label}</span>
                    {to === "/flags" && flagCount > 0 && <span className="count" aria-label={`${flagCount} open`}>{flagCount}</span>}
                  </a>
                ))}
              </div>
            ))}
            <div className="side-foot">
              Signed in as {ROLE_LABEL[user.role].toLowerCase()}.
              <br /><a href="/help">Privacy and help</a>
            </div>
          </div>
        </nav>}
        <main className="main" id="main" tabIndex={-1}>{page}</main>
      </div>
    </div>
  );
}

export default function App() {
  return <ToastProvider><AuthProvider><Shell /></AuthProvider></ToastProvider>;
}
