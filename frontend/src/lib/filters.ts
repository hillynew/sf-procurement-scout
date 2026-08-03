import type { Opportunity } from "../api/types";

/** Every dimension the All Bids filter panel can constrain.
 *  Sections combine with AND; selections within a section are OR. */
export interface BidFilters {
  statuses: string[]; // open | upcoming | closed (closed includes cancelled)
  regions: string[]; // county slugs — any of the 67 plus statewide/federal/unknown
  types: string[];
  categories: string[]; // taxonomy slugs (roofing, mosquito_control, ...)
  minValue: number | null;
  maxValue: number | null;
  dueWithin: number | null; // days, null = any
  trackedOnly: boolean;
  rebidsOnly: boolean;
  hasBrief: boolean;
  noBond: boolean;
}

export const EMPTY_FILTERS: BidFilters = {
  statuses: [],
  regions: [],
  types: [],
  categories: [],
  minValue: null,
  maxValue: null,
  dueWithin: null,
  trackedOnly: false,
  rebidsOnly: false,
  hasBrief: false,
  noBond: false,
};

export const DEFAULT_FILTERS: BidFilters = { ...EMPTY_FILTERS, statuses: ["open"] };

const FLAG_KEYS = ["trackedOnly", "rebidsOnly", "hasBrief", "noBond"] as const;
const FLAG_CODES: Record<(typeof FLAG_KEYS)[number], string> = {
  trackedOnly: "tracked",
  rebidsOnly: "rebid",
  hasBrief: "brief",
  noBond: "nobond",
};

function list(params: URLSearchParams, key: string): string[] {
  const raw = params.get(key);
  return raw ? raw.split(",").filter(Boolean) : [];
}

function num(params: URLSearchParams, key: string): number | null {
  const raw = params.get(key);
  if (!raw) return null;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** URL → filters. A missing URL (no filter params at all) means the default
 *  Open view; an explicit `f=` with other params present is respected. */
export function parseFilters(params: URLSearchParams): BidFilters {
  const keys = ["f", "c", "t", "cat", "vmin", "vmax", "due", "flags"];
  const anySet = keys.some((k) => params.get(k) !== null);
  if (!anySet) return DEFAULT_FILTERS;
  const flags = new Set(list(params, "flags"));
  return {
    statuses: list(params, "f").filter((s) => s !== "all"),
    regions: list(params, "c"),
    types: list(params, "t"),
    categories: list(params, "cat"),
    minValue: num(params, "vmin"),
    maxValue: num(params, "vmax"),
    dueWithin: num(params, "due"),
    trackedOnly: flags.has(FLAG_CODES.trackedOnly),
    rebidsOnly: flags.has(FLAG_CODES.rebidsOnly),
    hasBrief: flags.has(FLAG_CODES.hasBrief),
    noBond: flags.has(FLAG_CODES.noBond),
  };
}

/** Filters → URL params (mutates a copy the caller applies). */
export function writeFilters(params: URLSearchParams, filters: BidFilters): URLSearchParams {
  const next = new URLSearchParams(params);
  const setOrDelete = (key: string, value: string) => {
    if (value) next.set(key, value);
    else next.delete(key);
  };
  // "f=" (present but empty) distinguishes "no status filter" from "default".
  const isDefault = JSON.stringify(filters) === JSON.stringify(DEFAULT_FILTERS);
  if (isDefault) {
    ["f", "c", "t", "cat", "vmin", "vmax", "due", "flags"].forEach((k) => next.delete(k));
    return next;
  }
  next.set("f", filters.statuses.join(","));
  setOrDelete("c", filters.regions.join(","));
  setOrDelete("t", filters.types.join(","));
  setOrDelete("cat", filters.categories.join(","));
  setOrDelete("vmin", filters.minValue != null ? String(filters.minValue) : "");
  setOrDelete("vmax", filters.maxValue != null ? String(filters.maxValue) : "");
  setOrDelete("due", filters.dueWithin != null ? String(filters.dueWithin) : "");
  setOrDelete("flags", FLAG_KEYS.filter((k) => filters[k]).map((k) => FLAG_CODES[k]).join(","));
  return next;
}

function statusMatches(o: Opportunity, statuses: string[]): boolean {
  if (statuses.length === 0) return o.status !== "catalog";
  return statuses.some((s) =>
    s === "closed" ? ["closed", "cancelled"].includes(o.status) : o.status === s,
  );
}

export function applyFilters(opps: Opportunity[], f: BidFilters): Opportunity[] {
  return opps.filter((o) => {
    if (o.status === "catalog") return false;
    if (!statusMatches(o, f.statuses)) return false;
    if (f.regions.length && !f.regions.includes(o.county)) return false;
    if (f.types.length && !f.types.includes(o.offer_type)) return false;
    if (f.categories.length && !o.categories.some((c) => f.categories.includes(c))) {
      return false;
    }
    if (f.minValue != null && (o.budget_amount == null || o.budget_amount < f.minValue)) {
      return false;
    }
    if (f.maxValue != null && (o.budget_amount == null || o.budget_amount > f.maxValue)) {
      return false;
    }
    if (f.dueWithin != null &&
        (o.days_until_due == null || o.days_until_due < 0 || o.days_until_due > f.dueWithin)) {
      return false;
    }
    if (f.trackedOnly && !o.tracked) return false;
    if (f.rebidsOnly && !o.prior_cycles) return false;
    if (f.hasBrief && !o.has_summary) return false;
    if (f.noBond && o.requirements.some((r) => r.toLowerCase().includes("bond"))) {
      return false;
    }
    return true;
  });
}

/** How many constraints are active (for the button badge). */
export function countActive(f: BidFilters): number {
  let n = 0;
  if (f.statuses.length) n += 1;
  if (f.regions.length) n += 1;
  if (f.types.length) n += 1;
  if (f.categories.length) n += 1;
  if (f.minValue != null || f.maxValue != null) n += 1;
  if (f.dueWithin != null) n += 1;
  for (const key of FLAG_KEYS) if (f[key]) n += 1;
  return n;
}
