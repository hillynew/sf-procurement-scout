"""Price intelligence: what similar work has actually gone for.

Three pools of real dollars feed it, none of them estimates:

* award records with an amount (Legistar approvals, SAM award notices, FDOT
  bid tabs, parsed award notices),
* executed contracts from the registers (FACTS carries an amount on 82% of
  state contracts; Bonfire's register carries none and contributes nothing
  here),

grouped by taxonomy category — the same slugs the rest of the app filters by
— and broken out by county where enough data exists. Medians, not means: one
$7B Medicaid contract must not move the price of janitorial.

Contracts arrive uncategorised, so their names run through the same
classifier the adapters use. A contract the classifier can't place lands in
"general" and still counts toward the overall row.
"""

from __future__ import annotations

from statistics import median
from typing import Dict, List, Optional

from src.classify import classify_text
from src.db import store as db
from src.models.opportunity import Opportunity
from src.taxonomy import label_for

#: Groups thinner than this stay out — a "median" of two numbers is an
#: anecdote wearing a statistic's clothes.
MIN_SAMPLES = 3


def _bucket(amounts: List[int]) -> dict:
    ordered = sorted(amounts)
    n = len(ordered)
    return {
        "count": n,
        "median": int(median(ordered)),
        "low": ordered[max(0, n // 4)],
        "high": ordered[min(n - 1, (3 * n) // 4)],
    }


def build_pricing(opps: Optional[List[Opportunity]] = None) -> dict:
    """Per-category price picture from every real dollar figure stored."""
    samples: Dict[str, List[int]] = {}
    by_county: Dict[str, Dict[str, List[int]]] = {}

    def add(categories: List[str], county: Optional[str], amount: Optional[float]) -> None:
        if amount is None or amount <= 0:
            return
        dollars = int(round(amount))
        for slug in categories or ["general"]:
            samples.setdefault(slug, []).append(dollars)
            if county:
                by_county.setdefault(slug, {}).setdefault(county, []).append(dollars)

    for o in opps if opps is not None else db.load_opportunities():
        if o.status == "award" and o.award_amount:
            county = o.county if o.county not in ("statewide", "federal", "unknown") else None
            add([c for c in o.categories if c != "general"], county, o.award_amount)

    for c in db.load_contracts():
        if not c.amount:
            continue
        cats, _offer, _kw = classify_text(f"{c.name} {c.commodity or ''}")
        add([slug for slug in cats if slug != "general"], None, c.amount)

    categories = []
    for slug, amounts in samples.items():
        if len(amounts) < MIN_SAMPLES:
            continue
        entry = _bucket(amounts)
        entry["slug"] = slug
        entry["label"] = label_for(slug)
        entry["by_county"] = {
            county: _bucket(vals)
            for county, vals in sorted(by_county.get(slug, {}).items())
            if len(vals) >= MIN_SAMPLES
        }
        categories.append(entry)
    categories.sort(key=lambda e: -e["count"])
    return {"categories": categories, "min_samples": MIN_SAMPLES}


def price_hint(opp: Opportunity, pricing: dict) -> Optional[dict]:
    """The going rate for one bid's kind of work, county-first.

    Returns the narrowest bucket with enough data: this county's numbers if
    they exist, the category overall otherwise, nothing rather than a guess.
    """
    by_slug = {c["slug"]: c for c in pricing.get("categories", [])}
    for slug in opp.categories:
        entry = by_slug.get(slug)
        if not entry:
            continue
        county_bucket = entry.get("by_county", {}).get(opp.county)
        if county_bucket:
            return {"label": entry["label"], "scope": "county", **county_bucket}
        return {"label": entry["label"], "scope": "all", **entry}
    return None
