import { useEffect, useRef, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import type { BidFilters } from "../lib/filters";
import { countActive, DEFAULT_FILTERS, EMPTY_FILTERS } from "../lib/filters";
import { COUNTY_LABEL, fmtMoney, OFFER_LABEL } from "../lib/format";
import { FilterChip } from "./ui";

const STATUS_OPTIONS = [
  ["open", "Open"], ["upcoming", "Upcoming"], ["closed", "Closed"],
] as const;
const TYPE_OPTIONS = ["construction", "services", "goods", "professional_services"];
const DUE_OPTIONS = [
  [null, "Any time"], [7, "7 days"], [14, "14 days"], [30, "30 days"],
] as const;
const FLAG_OPTIONS: [keyof BidFilters, string][] = [
  ["trackedOnly", "Tracked only"],
  ["rebidsOnly", "Rebids only"],
  ["hasBrief", "Has AI brief"],
  ["noBond", "No bond required"],
];

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wide text-ink-faint">
        {label}
      </div>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  );
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** One button, every filter. Popover on desktop, bottom sheet on mobile. */
export default function FilterPanel({ filters, onChange, matchCount }: {
  filters: BidFilters;
  onChange: (next: BidFilters) => void;
  matchCount: number;
}) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const active = countActive(filters);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const set = (patch: Partial<BidFilters>) => onChange({ ...filters, ...patch });

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-2 rounded-[10px] border px-3.5 py-2 text-sm font-semibold transition-colors ${
          active > 0
            ? "border-accent bg-accent-soft text-accent"
            : "border-line bg-surface text-ink-soft hover:border-accent hover:text-accent"
        }`}
      >
        <SlidersHorizontal size={15} />
        Filters
        {active > 0 && (
          <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-accent px-1 text-[11px] font-bold text-white">
            {active}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30 bg-ink/20 sm:bg-transparent"
               onClick={() => setOpen(false)} />
          <div
            ref={panelRef}
            className="sheet-in fixed inset-x-0 bottom-0 z-40 max-h-[85vh] space-y-4 overflow-y-auto rounded-t-[14px] border border-line bg-surface p-4 shadow-(--shadow-pop) sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:mt-2 sm:w-[26rem] sm:rounded-[14px]"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-bold">Filter bids</span>
              <button onClick={() => setOpen(false)}
                      className="rounded-lg p-1 text-ink-faint hover:bg-bg hover:text-ink">
                <X size={16} />
              </button>
            </div>

            <Section label="Status">
              {STATUS_OPTIONS.map(([value, label]) => (
                <FilterChip key={value} active={filters.statuses.includes(value)}
                            onClick={() => set({ statuses: toggle(filters.statuses, value) })}>
                  {label}
                </FilterChip>
              ))}
            </Section>

            <Section label="Region">
              {Object.entries(COUNTY_LABEL).map(([value, label]) => (
                <FilterChip key={value} active={filters.regions.includes(value)}
                            onClick={() => set({ regions: toggle(filters.regions, value) })}>
                  {label}
                </FilterChip>
              ))}
            </Section>

            <Section label="Work type">
              {TYPE_OPTIONS.map((value) => (
                <FilterChip key={value} active={filters.types.includes(value)}
                            onClick={() => set({ types: toggle(filters.types, value) })}>
                  {OFFER_LABEL[value]}
                </FilterChip>
              ))}
            </Section>

            <Section label="Estimated value ($)">
              <div className="flex w-full items-center gap-2">
                <input
                  inputMode="numeric" placeholder="min"
                  defaultValue={filters.minValue ?? ""}
                  key={`min-${filters.minValue}`}
                  onBlur={(e) => {
                    const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
                    set({ minValue: Number.isFinite(n) ? n : null });
                  }}
                  className="w-full rounded-[10px] border border-line px-3 py-2 text-sm outline-none focus:border-accent"
                />
                <span className="text-ink-faint">–</span>
                <input
                  inputMode="numeric" placeholder="max"
                  defaultValue={filters.maxValue ?? ""}
                  key={`max-${filters.maxValue}`}
                  onBlur={(e) => {
                    const n = parseInt(e.target.value.replace(/\D/g, ""), 10);
                    set({ maxValue: Number.isFinite(n) ? n : null });
                  }}
                  className="w-full rounded-[10px] border border-line px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </div>
            </Section>

            <Section label="Due within">
              {DUE_OPTIONS.map(([value, label]) => (
                <FilterChip key={label} active={filters.dueWithin === value}
                            onClick={() => set({ dueWithin: value })}>
                  {label}
                </FilterChip>
              ))}
            </Section>

            <Section label="More">
              {FLAG_OPTIONS.map(([key, label]) => (
                <FilterChip key={key} active={Boolean(filters[key])}
                            onClick={() => set({ [key]: !filters[key] } as Partial<BidFilters>)}>
                  {label}
                </FilterChip>
              ))}
            </Section>

            <div className="flex items-center justify-between border-t border-line pt-3">
              <span className="text-sm font-bold text-accent">
                {matchCount} bid{matchCount !== 1 ? "s" : ""} match
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => onChange({ ...EMPTY_FILTERS })}
                  className="rounded-[10px] px-3 py-1.5 text-sm font-semibold text-ink-soft hover:bg-bg"
                >
                  Clear all
                </button>
                <button
                  onClick={() => onChange({ ...DEFAULT_FILTERS })}
                  className="rounded-[10px] px-3 py-1.5 text-sm font-semibold text-ink-soft hover:bg-bg"
                >
                  Reset
                </button>
                <button
                  onClick={() => setOpen(false)}
                  className="rounded-[10px] bg-accent px-3.5 py-1.5 text-sm font-bold text-white hover:bg-accent-deep"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Removable summary chips shown next to the Filters button. */
export function ActiveFilterChips({ filters, onChange }: {
  filters: BidFilters;
  onChange: (next: BidFilters) => void;
}) {
  const chips: { label: string; remove: () => void }[] = [];
  const set = (patch: Partial<BidFilters>) => onChange({ ...filters, ...patch });

  for (const s of filters.statuses) {
    chips.push({
      label: s[0].toUpperCase() + s.slice(1),
      remove: () => set({ statuses: filters.statuses.filter((v) => v !== s) }),
    });
  }
  for (const r of filters.regions) {
    chips.push({
      label: COUNTY_LABEL[r] ?? r,
      remove: () => set({ regions: filters.regions.filter((v) => v !== r) }),
    });
  }
  for (const t of filters.types) {
    chips.push({
      label: OFFER_LABEL[t] ?? t,
      remove: () => set({ types: filters.types.filter((v) => v !== t) }),
    });
  }
  if (filters.minValue != null || filters.maxValue != null) {
    const label = `${filters.minValue != null ? fmtMoney(filters.minValue) : "$0"} – ${
      filters.maxValue != null ? fmtMoney(filters.maxValue) : "any"}`;
    chips.push({ label, remove: () => set({ minValue: null, maxValue: null }) });
  }
  if (filters.dueWithin != null) {
    chips.push({ label: `Due ≤ ${filters.dueWithin}d`, remove: () => set({ dueWithin: null }) });
  }
  const flagLabels: [keyof BidFilters, string][] = [
    ["trackedOnly", "Tracked"], ["rebidsOnly", "Rebids"],
    ["hasBrief", "AI brief"], ["noBond", "No bond"],
  ];
  for (const [key, label] of flagLabels) {
    if (filters[key]) chips.push({ label, remove: () => set({ [key]: false } as Partial<BidFilters>) });
  }

  if (chips.length === 0) return null;
  return (
    <>
      {chips.map((chip, i) => (
        <button
          key={`${chip.label}-${i}`}
          onClick={chip.remove}
          title="Remove filter"
          className="group flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-xs font-semibold text-accent transition-colors hover:bg-accent hover:text-white"
        >
          {chip.label}
          <X size={11} className="opacity-60 group-hover:opacity-100" />
        </button>
      ))}
    </>
  );
}
