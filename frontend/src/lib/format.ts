import { format, parseISO } from "date-fns";

// "county" is really the geography slug. Since the statewide expansion it can
// be any of Florida's 67 counties plus the statewide/federal/unknown buckets —
// the authoritative labels come from /api/taxonomy. This map keeps only the
// slugs whose display form can't be derived from the slug itself; everything
// else goes through countyLabel(), which title-cases rather than ever showing
// a raw slug like "st-johns" in the UI.
export const COUNTY_LABEL: Record<string, string> = {
  "miami-dade": "Miami-Dade",
  broward: "Broward",
  "palm-beach": "Palm Beach",
  federal: "Federal",
  florida: "Florida State",
  statewide: "Statewide",
  unknown: "Unknown",
  "st-lucie": "St. Lucie",
  "st-johns": "St. Johns",
  "santa-rosa": "Santa Rosa",
  "indian-river": "Indian River",
  desoto: "DeSoto",
};

export function countyLabel(slug: string): string {
  return (
    COUNTY_LABEL[slug] ??
    slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

export const COUNTY_COLOR: Record<string, string> = {
  "miami-dade": "var(--color-miami)",
  broward: "var(--color-broward)",
  "palm-beach": "var(--color-palmbeach)",
  federal: "var(--color-federal)",
  florida: "var(--color-flstate)",
};

export const COUNTY_SOFT: Record<string, string> = {
  "miami-dade": "var(--color-miami-soft)",
  broward: "var(--color-broward-soft)",
  "palm-beach": "var(--color-palmbeach-soft)",
  federal: "var(--color-federal-soft)",
  florida: "var(--color-flstate-soft)",
};

export const OFFER_LABEL: Record<string, string> = {
  goods: "Goods",
  services: "Services",
  construction: "Construction",
  professional_services: "Professional svcs",
  mixed: "Mixed",
  unknown: "—",
};

export const STAGES = ["watching", "preparing", "submitted", "result"] as const;

export const STAGE_LABEL: Record<string, string> = {
  watching: "Watching",
  preparing: "Preparing bid",
  submitted: "Submitted",
  result: "Result",
};

/** $1.4M / $250k / $900 — dollars in, short string out. */
export function fmtMoney(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`.replace(".0M", "M");
  if (n >= 1_000) return `$${Math.round(n / 1_000)}k`;
  return `$${n}`;
}

export function fmtMoneyCents(cents: number | null | undefined): string | null {
  if (cents === null || cents === undefined) return null;
  return fmtMoney(Math.round(cents / 100));
}

export function fmtMoneyFull(cents: number | null | undefined): string | null {
  if (cents === null || cents === undefined) return null;
  return (cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    return format(parseISO(iso), "MMM d");
  } catch {
    return "";
  }
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  try {
    const d = parseISO(iso);
    return d.getHours() || d.getMinutes()
      ? format(d, "MMM d, h:mmaaa").replace("AM", "am").replace("PM", "pm")
      : format(d, "MMM d");
  } catch {
    return "";
  }
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z").getTime();
  const mins = Math.max(0, Math.round((Date.now() - then) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** Urgency bucket for due badges. */
export function dueTone(days: number | null | undefined, status: string):
  "closed" | "danger" | "warn" | "ok" | "none" {
  if (status !== "open" && status !== "upcoming") return "closed";
  if (days === null || days === undefined) return "none";
  if (days < 0) return "closed";
  if (days <= 3) return "danger";
  if (days <= 7) return "warn";
  return "ok";
}

export function dueText(days: number | null | undefined, status: string): string {
  if (status === "closed" || status === "cancelled") return status;
  if (days === null || days === undefined) return "no due date";
  if (days < 0) return "closed";
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  return `${days}d left`;
}

// --- Contractor network -----------------------------------------------------

/** Per-deal outreach pipeline on one bid↔contractor match. */
export const MATCH_STATUS_LABEL: Record<string, string> = {
  suggested: "Suggested",
  pitched: "Pitched",
  interested: "Interested",
  committed: "Committed",
  passed: "Passed",
};

/** The standing relationship with a firm, independent of any one bid. */
export const CONTRACTOR_STATUS_LABEL: Record<string, string> = {
  prospect: "Prospect",
  contacted: "Contacted",
  in_network: "In network",
  passed: "Passed",
};
