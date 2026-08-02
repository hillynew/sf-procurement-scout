import { useEffect } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import {
  Calendar,
  Kanban,
  LayoutDashboard,
  List,
  Radar,
  Search,
  Settings,
  Star,
} from "lucide-react";
import { useOpportunities, useWatchlists } from "../api/hooks";
import { fmtRelative } from "../lib/format";
import FetchButton from "../features/FetchButton";
import NotificationBell from "../features/NotificationBell";
import BidDrawer from "../features/BidDrawer";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/bids", label: "All bids", icon: List },
  { to: "/calendar", label: "Calendar", icon: Calendar },
  { to: "/pipeline", label: "Pipeline", icon: Kanban },
  { to: "/watchlists", label: "Watchlists", icon: Star },
  { to: "/sources", label: "Sources", icon: Radar },
  { to: "/settings", label: "Settings", icon: Settings },
];

const MOBILE_NAV = NAV.filter((n) =>
  ["/", "/bids", "/calendar", "/pipeline", "/watchlists"].includes(n.to),
);

export default function AppShell() {
  const { data: snapshot } = useOpportunities();
  const { data: watchlists } = useWatchlists();
  const navigate = useNavigate();

  const openCount =
    snapshot?.opportunities.filter((o) => o.status === "open").length ?? 0;
  const trackedCount =
    snapshot?.opportunities.filter((o) => o.tracked && !o.archived).length ?? 0;
  const newMatches =
    watchlists?.watchlists.reduce((sum, wl) => sum + wl.new_count, 0) ?? 0;

  const badges: Record<string, number> = {
    "/bids": openCount,
    "/pipeline": trackedCount,
    "/watchlists": newMatches,
  };

  // Keyboard shortcuts: / or ⌘K → search on All bids, Esc handled per-view.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") ||
          (!typing && e.key === "/")) {
        e.preventDefault();
        navigate("/bids?focus=1");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line bg-surface px-3 py-5 md:flex">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-lg text-white">
            🔎
          </div>
          <div>
            <div className="text-sm font-extrabold leading-tight">Scout</div>
            <div className="text-[11px] leading-tight text-ink-faint">SF procurement</div>
          </div>
        </div>
        <nav className="flex flex-1 flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-[10px] px-3 py-2 text-sm font-semibold transition-colors ${
                  isActive
                    ? "bg-accent-soft text-accent"
                    : "text-ink-soft hover:bg-bg hover:text-ink"
                }`
              }
            >
              <Icon size={16} />
              <span className="flex-1">{label}</span>
              {(badges[to] ?? 0) > 0 && (
                <span className="rounded-full bg-bg px-1.5 py-0.5 text-[11px] font-bold text-ink-soft">
                  {badges[to]}
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="px-3 text-[11px] text-ink-faint">
          {snapshot?.fetched_at
            ? `Data ${fmtRelative(snapshot.fetched_at)}`
            : "No data yet"}
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-line bg-bg/85 px-4 py-3 backdrop-blur md:px-6">
          <button
            onClick={() => navigate("/bids?focus=1")}
            className="flex flex-1 items-center gap-2 rounded-[10px] border border-line bg-surface px-3 py-2 text-sm text-ink-faint transition-colors hover:border-accent sm:max-w-sm"
          >
            <Search size={15} />
            <span className="flex-1 text-left">Search bids…</span>
            <kbd className="hidden rounded border border-line bg-bg px-1.5 text-[11px] font-semibold sm:inline">
              ⌘K
            </kbd>
          </button>
          <div className="flex items-center gap-2">
            <NotificationBell />
            <FetchButton />
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-4 pb-24 pt-5 md:px-6 md:pb-10">
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface/95 backdrop-blur md:hidden">
        {MOBILE_NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `relative flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-semibold ${
                isActive ? "text-accent" : "text-ink-faint"
              }`
            }
          >
            <Icon size={18} />
            {label}
            {(badges[to] ?? 0) > 0 && (
              <span className="absolute right-[22%] top-1 h-1.5 w-1.5 rounded-full bg-accent" />
            )}
          </NavLink>
        ))}
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center gap-0.5 py-2.5 text-[10px] font-semibold ${
              isActive ? "text-accent" : "text-ink-faint"
            }`
          }
        >
          <Settings size={18} />
          More
        </NavLink>
      </nav>

      <BidDrawer />
    </div>
  );
}
