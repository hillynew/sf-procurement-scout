import { Link, useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { format, parseISO } from "date-fns";
import { useLoadDemo, useStats } from "../api/hooks";
import { Button, EmptyState, Spinner, StatCard } from "../components/ui";
import {
  COUNTY_COLOR,
  countyLabel,
  fmtMoney,
  fmtMoneyCents,
  OFFER_LABEL,
  STAGE_LABEL,
} from "../lib/format";

const TYPE_COLORS = ["#6E56F8", "#0E9BB5", "#2AA463", "#E08A00", "#8A93A6"];

function ChartCard({ title, children, height = 220 }: {
  title: string; children: React.ReactElement; height?: number;
}) {
  return (
    <div className="card p-4">
      <div className="mb-3 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
        {title}
      </div>
      <ResponsiveContainer width="100%" height={height}>{children}</ResponsiveContainer>
    </div>
  );
}

const tooltipStyle = {
  borderRadius: 10,
  border: "1px solid var(--color-line)",
  fontSize: 12,
  fontFamily: "inherit",
};

export default function Dashboard() {
  const { data: stats, isLoading } = useStats();
  const demo = useLoadDemo();
  const navigate = useNavigate();

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;

  if (!stats || (stats.totals.open_count === 0 && stats.totals.tracked === 0)) {
    return (
      <EmptyState
        title="Welcome to Scout 👋"
        body="One dashboard for every bid across Miami-Dade, Broward, and Palm Beach. Fetch live data or explore with the sample set."
        action={
          <div className="flex gap-2">
            <Button onClick={() => demo.mutate()} disabled={demo.isPending}>
              {demo.isPending ? "Loading…" : "Load sample data"}
            </Button>
          </div>
        }
      />
    );
  }

  const t = stats.totals;
  const countyData = stats.by_county.map((c) => ({
    name: countyLabel(c.county),
    county: c.county,
    open: c.open,
    upcoming: c.upcoming,
    value: c.value,
  }));
  const typeData = stats.by_type.map((r) => ({ ...r, name: OFFER_LABEL[r.type] ?? r.type }));
  const loadData = stats.deadline_load.map((w) => ({
    ...w,
    name: format(parseISO(w.week), "MMM d"),
  }));
  const monthData = stats.results_by_month.map((m) => ({
    ...m,
    name: m.month.slice(2),
    revenue: m.revenue_cents / 100,
  }));

  return (
    <div className="fade-up space-y-4">
      <div>
        <h1 className="text-xl font-extrabold">Dashboard</h1>
        <p className="text-sm text-ink-soft">The whole market at a glance</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatCard label="Open bids" value={t.open_count} accent
                  sub={`+${t.upcoming_count} upcoming`} />
        <StatCard label="Open value" value={fmtMoney(t.open_value) ?? "—"}
                  sub="sum of estimates" />
        <StatCard label="Due in 7 days" value={t.due_7d}
                  sub={fmtMoney(t.due_7d_value) ?? undefined} />
        <StatCard label="Tracked" value={t.tracked} sub="in your pipeline" />
        <StatCard label="Win rate"
                  value={t.win_rate != null ? `${Math.round(t.win_rate * 100)}%` : "—"}
                  sub={t.revenue_cents > 0 ? `${fmtMoneyCents(t.revenue_cents)} won` : `${t.won}W – ${t.lost}L`} />
      </div>

      {stats.protest_windows.length > 0 && (
        <div className="card border-2 p-4" style={{ borderColor: "var(--color-warn)" }}>
          <div className="mb-2.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-wide"
               style={{ color: "var(--color-warn)" }}>
            <span aria-hidden>⏱</span> Protest windows open — 72-hour clocks running
          </div>
          <div className="space-y-1.5">
            {stats.protest_windows.map((w) => (
              <button key={w.opportunity_id}
                      onClick={() => navigate(`/bids/${w.opportunity_id}`)}
                      className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-bg">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">{w.title}</span>
                  <span className="block truncate text-xs text-ink-soft">
                    {w.agency}
                    {w.awarded_vendor ? ` · to ${w.awarded_vendor}` : ""}
                    {w.award_amount != null ? ` · ${fmtMoney(w.award_amount)}` : ""}
                  </span>
                </span>
                <span className="shrink-0 rounded-full px-2.5 py-1 text-xs font-bold"
                      style={{ background: "var(--color-warn-soft)", color: "var(--color-warn)" }}>
                  {w.hours_left < 24
                    ? `${Math.round(w.hours_left)}h left`
                    : `~${Math.round(w.hours_left / 24)} business days`}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      {stats.attention.length > 0 && (
        <div className="card p-4">
          <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Needs attention
          </div>
          <div className="space-y-1.5">
            {stats.attention.map((a) => (
              <button key={a.opportunity_id}
                      onClick={() => navigate(`/bids/${a.opportunity_id}`)}
                      className="flex w-full items-center gap-3 rounded-[10px] px-2.5 py-2 text-left hover:bg-bg">
                <span className={`w-14 shrink-0 text-xs font-extrabold ${
                  a.days_until_due <= 3 ? "text-danger" : "text-warn"}`}>
                  {a.days_until_due === 0 ? "today" : `${a.days_until_due}d left`}
                </span>
                <span className="min-w-0 flex-1 truncate text-sm font-semibold">{a.title}</span>
                {a.unmet_count > 0 && (
                  <span className="shrink-0 text-xs font-semibold text-warn">
                    {a.unmet_count} unmet
                  </span>
                )}
                <span className="money hidden shrink-0 text-xs sm:block">
                  {fmtMoney(a.budget_amount)}
                </span>
                <span className="shrink-0 rounded-full bg-bg px-2 py-0.5 text-[10px] font-bold uppercase text-ink-faint">
                  {STAGE_LABEL[a.stage]}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Live bids by county">
          <BarChart data={countyData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--color-bg)" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="open" name="Open" radius={[6, 6, 0, 0]}>
              {countyData.map((c) => (
                <Cell key={c.county} fill={COUNTY_COLOR[c.county] ?? "#8A93A6"} />
              ))}
            </Bar>
            <Bar dataKey="upcoming" name="Upcoming" fill="#c9d2e3" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ChartCard>

        <ChartCard title="Open value by work type">
          <BarChart data={typeData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 12 }} axisLine={false} tickLine={false}
                   tickFormatter={(v: number) => fmtMoney(v) ?? ""} />
            <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 12 }}
                   axisLine={false} tickLine={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--color-bg)" }}
                     formatter={(v) => fmtMoney(Number(v)) ?? "0"} />
            <Bar dataKey="value" name="Est. value" radius={[0, 6, 6, 0]}>
              {typeData.map((_, i) => (
                <Cell key={i} fill={TYPE_COLORS[i % TYPE_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ChartCard>

        <ChartCard title="Deadline load — next 8 weeks">
          <BarChart data={loadData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} allowDecimals={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--color-bg)" }}
                     formatter={(v, name) =>
                       name === "Est. value" ? (fmtMoney(Number(v)) ?? "0") : v} />
            <Bar dataKey="count" name="Bids due" fill="#6E56F8" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ChartCard>

        {monthData.length > 0 ? (
          <ChartCard title="Won revenue by month">
            <BarChart data={monthData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false}
                     tickFormatter={(v: number) => fmtMoney(v) ?? ""} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--color-bg)" }}
                       formatter={(v, name) =>
                         name === "Revenue" ? (fmtMoney(Number(v)) ?? "0") : v} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="revenue" name="Revenue" fill="#0F7B5F" radius={[6, 6, 0, 0]} />
              <Bar dataKey="lost" name="Losses" fill="#e5b9b9" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ChartCard>
        ) : (
          <ChartCard title="Bids captured per fetch">
            <LineChart data={stats.trend.map((r, i) => ({
              name: r.finished_at ? format(parseISO(r.finished_at), "MMM d HH:mm") : String(i),
              count: r.count, new: r.new_count,
            }))}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-line)" vertical={false} />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Line type="monotone" dataKey="count" name="Total" stroke="#6E56F8"
                    strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="new" name="New" stroke="#2AA463"
                    strokeWidth={2} dot={false} />
            </LineChart>
          </ChartCard>
        )}
      </div>

      <div className="card p-4">
        <div className="mb-2.5 flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">
            Top sources this scan
          </span>
          <Link to="/sources" className="text-xs font-bold text-accent hover:underline">
            All sources →
          </Link>
        </div>
        <div className="space-y-1.5">
          {stats.sources.slice(0, 8).map((s) => {
            const max = stats.sources[0]?.count || 1;
            return (
              <div key={s.source_id} className="flex items-center gap-3">
                <span className="w-44 truncate text-xs font-semibold text-ink-soft sm:w-56">
                  {s.name}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-bg">
                  <div className="h-full rounded-full bg-accent/70"
                       style={{ width: `${(s.count / max) * 100}%` }} />
                </div>
                <span className="w-8 text-right text-xs font-bold">{s.count}</span>
              </div>
            );
          })}
          {stats.sources.length === 0 && (
            <div className="py-4 text-center text-sm text-ink-faint">
              No scan yet — hit “Fetch live data”.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
