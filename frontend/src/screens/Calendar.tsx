import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  addDays,
  addMonths,
  format,
  isSameDay,
  isSameMonth,
  parseISO,
  startOfMonth,
  startOfWeek,
} from "date-fns";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useLoadDemo, useOpportunities } from "../api/hooks";
import type { Opportunity } from "../api/types";
import BidRow from "../components/BidRow";
import { Button, EmptyState, Modal, Spinner, ValueTag } from "../components/ui";
import { COUNTY_COLOR, fmtMoney } from "../lib/format";

export default function CalendarScreen() {
  const { data, isLoading } = useOpportunities();
  const demo = useLoadDemo();
  const [params, setParams] = useSearchParams();
  const [month, setMonth] = useState(() => startOfMonth(new Date()));
  const [dayOpen, setDayOpen] = useState<Date | null>(null);

  const byDay = useMemo(() => {
    const map = new Map<string, Opportunity[]>();
    for (const o of data?.opportunities ?? []) {
      if (!o.due_date || o.status === "catalog") continue;
      const key = format(parseISO(o.due_date), "yyyy-MM-dd");
      map.set(key, [...(map.get(key) ?? []), o]);
    }
    for (const list of map.values()) {
      list.sort((a, b) => (b.budget_amount ?? 0) - (a.budget_amount ?? 0));
    }
    return map;
  }, [data]);

  if (isLoading) return <div className="flex justify-center py-24"><Spinner size={26} /></div>;
  if ((data?.count ?? 0) === 0) {
    return (
      <EmptyState title="Calendar is empty"
                  body="Bids land here on their due dates once you fetch or load sample data."
                  action={<Button onClick={() => demo.mutate()}>Load sample data</Button>} />
    );
  }

  const gridStart = startOfWeek(startOfMonth(month));
  const days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
  const today = new Date();
  const dueThisMonth = [...byDay.entries()]
    .filter(([key]) => isSameMonth(parseISO(key), month))
    .reduce((sum, [, list]) => sum + list.length, 0);

  const openDrawer = (id: string) => {
    params.set("drawer", id);
    setParams(params);
  };

  const chip = (o: Opportunity) => (
    <button
      key={o.opportunity_id}
      onClick={(e) => { e.stopPropagation(); openDrawer(o.opportunity_id); }}
      className={`flex w-full items-center gap-1 truncate rounded-md px-1.5 py-1 text-left text-[11px] font-semibold transition-colors hover:bg-accent-soft ${
        (o.days_until_due ?? 99) <= 3 && o.status === "open" ? "text-danger" :
        o.status === "open" || o.status === "upcoming" ? "text-ink" : "text-ink-faint line-through"
      }`}
      title={o.title}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-full"
            style={{ background: COUNTY_COLOR[o.county] ?? "var(--color-ink-faint)" }} />
      <span className="truncate">{o.title}</span>
      {o.budget_amount != null && (
        <span className="money ml-auto shrink-0 text-[10px]">{fmtMoney(o.budget_amount)}</span>
      )}
    </button>
  );

  return (
    <div className="fade-up">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-extrabold">{format(month, "MMMM yyyy")}</h1>
          <p className="text-sm text-ink-soft">{dueThisMonth} bids due this month</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={() => setMonth(addMonths(month, -1))}
                  className="rounded-[10px] border border-line bg-surface p-2 text-ink-soft hover:border-accent hover:text-accent">
            <ChevronLeft size={16} />
          </button>
          <Button kind="ghost" onClick={() => setMonth(startOfMonth(new Date()))}>Today</Button>
          <button onClick={() => setMonth(addMonths(month, 1))}
                  className="rounded-[10px] border border-line bg-surface p-2 text-ink-soft hover:border-accent hover:text-accent">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Desktop month grid */}
      <div className="card hidden overflow-hidden md:block">
        <div className="grid grid-cols-7 border-b border-line bg-bg text-center text-[11px] font-bold uppercase tracking-wide text-ink-faint">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((d) => (
            <div key={d} className="py-2">{d}</div>
          ))}
        </div>
        <div className="grid grid-cols-7">
          {days.map((day) => {
            const key = format(day, "yyyy-MM-dd");
            const list = byDay.get(key) ?? [];
            const isToday = isSameDay(day, today);
            const inMonth = isSameMonth(day, month);
            const weekend = day.getDay() === 0 || day.getDay() === 6;
            return (
              <div
                key={key}
                onClick={() => list.length > 0 && setDayOpen(day)}
                className={`min-h-24 border-b border-r border-line p-1.5 [&:nth-child(7n)]:border-r-0 ${
                  weekend ? "bg-bg/60" : ""
                } ${inMonth ? "" : "opacity-40"} ${list.length > 0 ? "cursor-pointer hover:bg-accent-soft/30" : ""}`}
              >
                <div className={`mb-1 flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
                  isToday ? "bg-accent text-white" : "text-ink-soft"
                }`}>
                  {format(day, "d")}
                </div>
                {list.slice(0, 3).map(chip)}
                {list.length > 3 && (
                  <div className="px-1.5 pt-0.5 text-[11px] font-bold text-accent">
                    +{list.length - 3} more
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Mobile agenda */}
      <div className="space-y-4 md:hidden">
        {days
          .filter((d) => isSameMonth(d, month) && (byDay.get(format(d, "yyyy-MM-dd")) ?? []).length > 0)
          .map((day) => {
            const list = byDay.get(format(day, "yyyy-MM-dd")) ?? [];
            return (
              <div key={day.toISOString()}>
                <div className={`mb-1.5 text-xs font-bold uppercase tracking-wide ${
                  isSameDay(day, today) ? "text-accent" : "text-ink-faint"}`}>
                  {format(day, "EEE, MMM d")}{isSameDay(day, today) && " · today"}
                </div>
                <div className="space-y-2">
                  {list.map((o) => <BidRow key={o.opportunity_id} bid={o} />)}
                </div>
              </div>
            );
          })}
      </div>

      {dayOpen && (
        <Modal title={format(dayOpen, "EEEE, MMMM d")} onClose={() => setDayOpen(null)} wide>
          <div className="space-y-2">
            {(byDay.get(format(dayOpen, "yyyy-MM-dd")) ?? []).map((o) => (
              <button key={o.opportunity_id}
                      onClick={() => { setDayOpen(null); openDrawer(o.opportunity_id); }}
                      className="card flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:border-accent/40">
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">{o.title}</div>
                  <div className="truncate text-xs text-ink-soft">{o.agency}</div>
                </div>
                <ValueTag amount={o.budget_amount} />
              </button>
            ))}
          </div>
        </Modal>
      )}
    </div>
  );
}
