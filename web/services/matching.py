"""Watchlist rule matching, shared by the API, digests, and post-fetch hooks.

Rules shape (all keys optional):
    keywords: list[str]        — any keyword appearing in title/scope/description/categories
    counties: list[str]        — county slugs
    offers:   list[str]        — offer_type keys (construction, services, ...)
    categories: list[str]      — taxonomy slugs (roofing, mosquito_control, ...)
    min_value / max_value: int — dollar bounds against the parsed budget
    no_bond: bool              — exclude bids with a bond requirement
    recurring_only: bool       — only bids with prior cycles on record
    include_statewide: bool    — with `counties`, also keep statewide bids that
                                 name no county at all (see below)

## Why `counties` has to look past the county field

A growing share of this build's sources are statewide by nature: MyFloridaMarketPlace,
FACTS, SAM.gov, and both FDOT advertisement feeds. Their `county` is
`statewide`, which is honest — an FDOT District 4 job spans six counties and a
state term contract spans all of them.

Matched on the county field alone, a Broward watchlist silently drops every one
of them. Measured against a live sample of 307 bids, a tri-county rule kept 24
and discarded 241 — including all 24 FDOT District 4 advertisements, which are
Broward and Palm Beach road work. The user's own county filter was hiding the
work in their own county.

So a statewide bid matches a county rule when it *names* one of those counties,
either in the keywords an adapter stamped on it (FDOT writes its district's
counties there for exactly this) or in its own text. On that same sample the
rule recovers 147 of the 241.

The remaining 94 are genuinely unlocated — a state contract that could be
performed anywhere. They stay out unless `include_statewide` asks for them,
because four times as much unlocated noise as located signal is not a filter.
"""

from __future__ import annotations

from typing import List, Set

from src.fl_geo import COUNTY_SLUGS, infer_county
from src.models.opportunity import Opportunity


def offer_key(o: Opportunity) -> str:
    s = o.offer_type
    return str(s.value if hasattr(s, "value") else s or "unknown")


def by_due(opps: List[Opportunity]) -> List[Opportunity]:
    return sorted(
        opps,
        key=lambda o: (
            o.days_until_due if o.days_until_due is not None else 9_999,
            o.title.lower(),
        ),
    )


def counties_named(o: Opportunity) -> Set[str]:
    """Every county this bid names, beyond the one in its `county` field.

    Two places carry it. Adapters for multi-county sources stamp the slugs into
    `keywords` — FDOT writes its district's six counties there — and the rest of
    the time the county is in the prose, where `infer_county` finds it.
    """
    found = {k for k in (o.keywords or []) if k in COUNTY_SLUGS}
    text = " ".join(part for part in (o.title, o.description, o.department) if part)
    guess = infer_county(text)
    if guess in COUNTY_SLUGS:
        found.add(guess)
    return found


def _county_ok(o: Opportunity, rules: dict) -> bool:
    wanted = rules.get("counties")
    if not wanted:
        return True
    if o.county in wanted:
        return True
    if o.county != "statewide":
        return False
    # Statewide by nature. Keep it when it names a county the rule asked for;
    # keep an unlocated one only when the rule opted in. See the module
    # docstring — this is where FDOT District 4's Broward work was being lost.
    named = counties_named(o)
    if named:
        return bool(named & set(wanted))
    return bool(rules.get("include_statewide"))


def matches_rules(o: Opportunity, rules: dict) -> bool:
    if not _county_ok(o, rules):
        return False
    if rules.get("offers") and offer_key(o) not in rules["offers"]:
        return False
    if rules.get("categories"):
        # The classifier already stamps umbrellas onto each bid, so a rule for
        # `construction` matches a bid tagged `roofing` without expanding here.
        if not set(rules["categories"]) & set(o.categories or []):
            return False
    amount = o.budget_amount
    if rules.get("min_value") and amount is not None and amount < rules["min_value"]:
        return False
    if rules.get("max_value") and amount is not None and amount > rules["max_value"]:
        return False
    if rules.get("no_bond") and any("bond" in r.lower() for r in o.requirements):
        return False
    if rules.get("recurring_only") and not o.prior_cycles:
        return False
    if rules.get("keywords"):
        text = " ".join(
            [o.title, o.scope or "", o.description or ""] + (o.categories or [])
        ).lower()
        if not any(str(kw).lower() in text for kw in rules["keywords"]):
            return False
    return True


def wl_matches(rules: dict, opps: List[Opportunity]) -> List[Opportunity]:
    """Open/upcoming bids matching a watchlist's rules, soonest-due first."""
    pool = [o for o in opps if o.status in ("open", "upcoming")]
    return by_due([o for o in pool if matches_rules(o, rules or {})])
