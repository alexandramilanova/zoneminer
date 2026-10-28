import { NavLink, Outlet } from "react-router-dom";
import { Suspense, useEffect, useState, type ReactNode } from "react";
import { useAppState } from "../state";
import Tour from "./Tour";
import { sessionInfo, type SessionInfo } from "../api";

function SessionNotice() {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [error, setError] = useState("");
  const [expired, setExpired] = useState(false);
  useEffect(() => {
    sessionInfo().then(setInfo).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!info?.expires_at) return;
    const update = () => setExpired(Date.now() / 1000 >= info.expires_at!);
    update();
    const timer = window.setInterval(update, 10000);
    return () => window.clearInterval(timer);
  }, [info]);
  if (!error && info?.mode !== "anonymous") return null;
  const reset = async () => {
    const response = await fetch("/api/session", { method: "DELETE" });
    if (!response.ok) { setError("Session could not be deleted. Please try again."); return; }
    localStorage.removeItem("zone-analytics-current");
    window.location.assign(window.location.pathname);
  };
  return <div className="notice" role="status">
    {error || (expired ? "This temporary session has expired. Start a new session to continue." :
      `Temporary private workspace. Uploads and results expire at ${new Date(info!.expires_at! * 1000).toLocaleString()}. Download results you want to keep.${info!.upload_mb === null ? "" : ` Upload limit: ${info!.upload_mb} MB.`}`)}
    {" "}<button onClick={() => { void reset().catch(() => setError("Session could not be deleted. Please try again.")); }}>
      {expired || error ? "Start new session" : "Delete session and files"}
    </button>
  </div>;
}

function Icon({ d, size = 16 }: { d: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

const ICONS = {
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  overview: "M3 3v18h18M8 16v-5m5 5V8m5 8v-3",
  replay: "M8 5.5v13l11-6.5-11-6.5Z",
  trends: "M3 17l6-6 4 4 8-8m0 0h-5m5 0v5",
  deps: "M6 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm12 14a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm12-14a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8 7l8 1m-8 9 8 1M6 8v8m12-8v8",
  predict: "M12 2a7 7 0 0 1 7 7c0 2.4-1.2 4.1-2.6 5.6-.9 1-1.4 1.7-1.4 2.9h-6c0-1.2-.5-1.9-1.4-2.9C6.2 13.1 5 11.4 5 9a7 7 0 0 1 7-7Zm-3 18h6m-5 2h4",
  metrics: "M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15Zm0 0A2.5 2.5 0 0 0 6.5 22H20v-5",
  flow: "M3 11c2.5-3.2 5-3.2 7.5 0s5 3.2 7.5 0 2-2.4 3-3M3 17c2.5-3.2 5-3.2 7.5 0s5 3.2 7.5 0 2-2.4 3-3",
};

const VIEWS = [
  { to: "/overview", label: "Overview & Alerts", icon: ICONS.overview },
  { to: "/replay", label: "Token replay", icon: ICONS.replay },
  { to: "/trends", label: "Trends & Change points", icon: ICONS.trends },
  { to: "/flow", label: "Flow patterns", icon: ICONS.flow },
  { to: "/dependencies", label: "Dependencies", icon: ICONS.deps },
  { to: "/prediction", label: "Prediction", icon: ICONS.predict },
  { to: "/metrics", label: "Metrics reference", icon: ICONS.metrics },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<string>(() => localStorage.getItem("theme") ?? "auto");
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);
  const next = theme === "auto" ? "light" : theme === "light" ? "dark" : "auto";
  const icon = theme === "auto" ? "◐" : theme === "light" ? "☀" : "☾";
  return (
    <button onClick={() => setTheme(next)} title={`Theme: ${theme} (click to switch)`}>
      {icon} {theme}
    </button>
  );
}

function NavItem({ to, label, icon, disabled }: { to: string; label: string; icon: ReactNode; disabled?: boolean }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        `nav-link${isActive ? " active" : ""}${disabled ? " disabled" : ""}`
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export default function Layout() {
  const { analysis } = useAppState();
  const ready = Boolean(analysis?.has_artifacts);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-logo">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
              <circle cx="6" cy="12" r="3" fill="#fff" />
              <circle cx="18" cy="6" r="2.4" fill="#fff" opacity="0.85" />
              <circle cx="18" cy="18" r="2.4" fill="#fff" opacity="0.85" />
              <path d="M8.6 10.8 15.6 7M8.6 13.2l7 3.8" stroke="#fff" strokeWidth="1.6" />
            </svg>
          </span>
          <span>
            ZoneMiner
            <small>token-flow analysis by process zones</small>
          </span>
        </div>
        <NavItem to="/" label="Data, Model & Zones" icon={<Icon d={ICONS.data} />} />
        <h3>Analysis</h3>
        {VIEWS.map((v) => (
          <NavItem key={v.to} to={v.to} label={v.label} icon={<Icon d={v.icon} />} disabled={!ready} />
        ))}
        <div className="foot">
          <div className="row" style={{ gap: 8 }}>
            <ThemeToggle />
            {ready && <Tour />}
            <a href="/THIRD_PARTY_NOTICES.txt" target="_blank" rel="noreferrer">Licenses</a>
          </div>
        </div>
      </aside>
      <main className="main fade-in">
        <SessionNotice />
        <Suspense fallback={<p role="status">Loading view…</p>}><Outlet /></Suspense>
      </main>
    </div>
  );
}
