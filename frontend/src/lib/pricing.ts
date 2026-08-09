import type { Opportunity, PriceBucket, PricingReport } from "../api/types";

export interface PriceHint extends PriceBucket {
  label: string;
  scope: "county" | "all";
}

/** The going rate for one bid's kind of work — county numbers first, the
 *  category overall otherwise, nothing rather than a guess. Mirrors the
 *  server's web/services/pricing.py::price_hint. */
export function priceHint(opp: Opportunity, pricing: PricingReport | undefined): PriceHint | null {
  if (!pricing) return null;
  const bySlug = new Map(pricing.categories.map((c) => [c.slug, c]));
  for (const slug of opp.categories) {
    const entry = bySlug.get(slug);
    if (!entry) continue;
    const county = entry.by_county[opp.county];
    if (county) return { label: entry.label, scope: "county", ...county };
    return { label: entry.label, scope: "all", count: entry.count, median: entry.median, low: entry.low, high: entry.high };
  }
  return null;
}
