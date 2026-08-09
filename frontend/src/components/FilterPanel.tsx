import { useEffect, useMemo, useRef, useState } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { useTaxonomy } from "../api/hooks";
import type { TaxonomyResponse } from "../api/types";
import type { BidFilters } from "../lib/filters";
import { countActive, DEFAULT_FILTERS, EMPTY_FILTERS } from "../lib/filters";
import { countyLabel, fmtMoney, OFFER_LABEL } from "../lib/format";
import MultiSelect, { type MultiSelectOption } from "./MultiSelect";
import { FilterChip } from "./ui";

const TIER_OPTIONS: [string, string][] = [
  ["state", "State"], ["county", "County"], ["municipal", "City"],
  ["school_district", "Schools"], ["higher_ed", "Higher ed"],
  ["special_district", "Districts"], ["federal", "Federal"],
];

const STATUS_OPTIONS = [
  ["open", "Open"], ["upcoming", "Upcoming"], ["award", "Awarded"], ["closed", "Closed"],
] as const;
const DUE_OPTIONS = [
  [null, "Any time"], [7, "7 days"], [14, "14 days"], [30, "30 days"],
] as const;
const FLAG_OPTIONS: [keyof BidFilters, string][] = [
  ["trackedOnly", "Tracked only"],
  ["rebidsOnly", "Rebids only"],
  ["hasBrief", "Has AI brief"],
  ["noBond", "No bond required"],
];

function Section({ label, hint, children }: {
  label: string; hint?: string; children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-faint">
          {label}
        </span>
        {hint && <span className="text-[11px] text-ink-faint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

function toggle(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** One button, every filter. Popover on desktop, bottom sheet on mobile.
 *
 *  The vocabulary comes from /api/taxonomy, not from the loaded snapshot:
 *  since the statewide expansion "region" means any of the 67 counties, and
 *  five hard-coded chips silently made most of the state unfilterable. */
export default function FilterPanel({ filters, onChange, matchCount }: {
  filters: BidFilters;
  onChange: (next: BidFilters) => void;
  matchCount: number;
}) {
  const [open, setOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const { data: tax } = useTaxonomy();
  const active = countActive(filters);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const set = (patch: Partial<BidFilters>) => onChange({ ...filters, ...patch });

  const countyOptions: MultiSelectOption[] = useMemo(
    () =>
      (tax?.counties ?? []).map((c) => ({
        value: c.slug,
        label: c.label,
        group: c.region_label,
        count: c.count,
      })),
    [tax],
  );
  const countyGroupOrder = useMemo(() => {
    const seen: { key: string; label: string }[] = [];
    for (const c of tax?.counties ?? []) {
      if (!seen.some((g) => g.key === c.region_label)) {
        seen.push({ key: c.region_label, label: c.region_label });
      }
    }
    return seen;
  }, [tax]);

  const categoryOptions: MultiSelectOption[] = useMemo(
    () =>
      (tax?.categories ?? []).map((c) => ({
        value: c.slug,
        label: c.label,
        group: c.group,
        count: c.count,
        synonyms: c.slug.replace(/_/g, " "),
      })),
    [tax],
  );

  const offerOptions = tax?.offer_types ?? [
    { key: "construction", label: "Construction", count: 0 },
    { key: "services", label: "Services", count: 0 },
    { key: "professional_services", label: "Professional services", count: 0 },
    { key: "goods", label: "Goods", count: 0 },
  ];

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
                <div key={value} className="mr-1.5 inline-block">
                  <FilterChip active={filters.statuses.includes(value)}
                              onClick={() => set({ statuses: toggle(filters.statuses, value) })}>
                    {label}
                  </FilterChip>
                </div>
              ))}
            </Section>

            <Section label="Tier" hint="which level of government">
              {TIER_OPTIONS.map(([value, label]) => (
                <div key={value} className="mr-1.5 inline-block">
                  <FilterChip active={filters.tiers.includes(value)}
                              onClick={() => set({ tiers: toggle(filters.tiers, value) })}>
                    {label}
                  </FilterChip>
                </div>
              ))}
            </Section>

            <Section label="Category"
                     hint={tax ? `${categoryOptions.length} to choose from` : undefined}>
              <MultiSelect
                options={categoryOptions}
                selected={filters.categories}
                onChange={(next) => set({ categories: next })}
                placeholder="Any category"
                groupOrder={(tax?.groups ?? []).map((g) => ({ key: g.slug, label: g.label }))}
              />
            </Section>

            <Section label="County" hint="all 67, grouped by region">
              <MultiSelect
                options={countyOptions}
                selected={filters.regions}
                onChange={(next) => set({ regions: next })}
                placeholder="Anywhere in Florida"
                groupOrder={countyGroupOrder}
              />
            </Section>

            <Section label="Work type">
              <div className="flex flex-wrap gap-1.5">
                {offerOptions.map((o) => (
                  <FilterChip key={o.key} active={filters.types.includes(o.key)}
                              onClick={() => set({ types: toggle(filters.types, o.key) })}>
                    {o.label}
                    {o.count > 0 && (
                      <span className="ml-1 text-[10px] opacity-70">{o.count}</span>
                    )}
                  </FilterChip>
                ))}
              </div>
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
                <div key={label} className="mr-1.5 inline-block">
                  <FilterChip active={filters.dueWithin === value}
                              onClick={() => set({ dueWithin: value })}>
                    {label}
                  </FilterChip>
                </div>
              ))}
            </Section>

            <Section label="More">
              <div className="flex flex-wrap gap-1.5">
                {FLAG_OPTIONS.map(([key, label]) => (
                  <FilterChip key={key} active={Boolean(filters[key])}
                              onClick={() => set({ [key]: !filters[key] } as Partial<BidFilters>)}>
                    {label}
                  </FilterChip>
                ))}
              </div>
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
  const { data: tax } = useTaxonomy();
  const chips: { label: string; remove: () => void }[] = [];
  const set = (patch: Partial<BidFilters>) => onChange({ ...filters, ...patch });

  const catLabel = (slug: string, t?: TaxonomyResponse) =>
    t?.categories.find((c) => c.slug === slug)?.label ?? slug.replace(/_/g, " ");

  for (const s of filters.statuses) {
    chips.push({
      label: s[0].toUpperCase() + s.slice(1),
      remove: () => set({ statuses: filters.statuses.filter((v) => v !== s) }),
    });
  }
  for (const c of filters.categories) {
    chips.push({
      label: catLabel(c, tax),
      remove: () => set({ categories: filters.categories.filter((v) => v !== c) }),
    });
  }
  for (const r of filters.regions) {
    chips.push({
      label: tax?.county_labels[r] ?? countyLabel(r),
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
