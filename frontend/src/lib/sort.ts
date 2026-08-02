import { useCallback, useState } from "react";
import type { Opportunity } from "../api/types";

export type SortDir = "asc" | "desc";

export interface SortPref {
  key: string;
  dir: SortDir;
}

export interface SortKeyDef {
  value: string;
  label: string;
  /** The direction that makes sense when this key is first picked. */
  defaultDir: SortDir;
}

export const BID_SORT_KEYS: SortKeyDef[] = [
  { value: "due", label: "Due date", defaultDir: "asc" },
  { value: "posted", label: "Posted", defaultDir: "desc" },
  { value: "value", label: "Value", defaultDir: "desc" },
  { value: "title", label: "Title", defaultDir: "asc" },
  { value: "agency", label: "Agency", defaultDir: "asc" },
  { value: "county", label: "Region", defaultDir: "asc" },
  { value: "score", label: "Detail score", defaultDir: "desc" },
];

export const PIPELINE_SORT_KEYS: SortKeyDef[] = [
  { value: "due", label: "Due date", defaultDir: "asc" },
  { value: "value", label: "Value", defaultDir: "desc" },
  { value: "tracked", label: "Recently tracked", defaultDir: "desc" },
  { value: "title", label: "Title", defaultDir: "asc" },
];

/** Missing values (no due date, no budget) always sort last, either direction. */
function rank(o: Opportunity, key: string): number | string | null {
  switch (key) {
    case "due":
      return o.days_until_due;
    case "posted":
      return o.posted_date;
    case "value":
      return o.budget_amount;
    case "title":
      return o.title.toLowerCase();
    case "agency":
      return o.agency.toLowerCase();
    case "county":
      return o.county;
    case "score":
      return o.detail_score;
    case "tracked":
      return o.tracked_on;
    default:
      return null;
  }
}

export function sortOpportunities(
  list: Opportunity[],
  key: string,
  dir: SortDir,
): Opportunity[] {
  const sign = dir === "desc" ? -1 : 1;
  return [...list].sort((a, b) => {
    const av = rank(a, key);
    const bv = rank(b, key);
    if (av == null && bv == null) return a.title.localeCompare(b.title);
    if (av == null) return 1; // nulls last regardless of direction
    if (bv == null) return -1;
    let cmp: number;
    if (typeof av === "string" || typeof bv === "string") {
      cmp = String(av).localeCompare(String(bv));
    } else {
      cmp = av - bv;
    }
    if (cmp === 0) return a.title.localeCompare(b.title);
    return cmp * sign;
  });
}

/** Per-screen sort preference persisted in localStorage. */
export function useSortPref(
  screen: string,
  fallback: SortPref,
): [SortPref, (next: SortPref) => void] {
  const storageKey = `scout.sort.${screen}`;
  const [pref, setPref] = useState<SortPref>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed?.key && (parsed.dir === "asc" || parsed.dir === "desc")) {
          return parsed as SortPref;
        }
      }
    } catch {
      // localStorage unavailable (private mode) — fall through
    }
    return fallback;
  });

  const update = useCallback(
    (next: SortPref) => {
      setPref(next);
      try {
        localStorage.setItem(storageKey, JSON.stringify(next));
      } catch {
        // best-effort persistence only
      }
    },
    [storageKey],
  );

  return [pref, update];
}
