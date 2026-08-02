"""Watchlist rule matching, shared by the API, digests, and post-fetch hooks.

Rules shape (all keys optional):
    keywords: list[str]        — any keyword appearing in title/scope/description/categories
    counties: list[str]        — county slugs
    offers:   list[str]        — offer_type keys (construction, services, ...)
    min_value / max_value: int — dollar bounds against the parsed budget
    no_bond: bool              — exclude bids with a bond requirement
    recurring_only: bool       — only bids with prior cycles on record
"""

from __future__ import annotations

from typing import List

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


def matches_rules(o: Opportunity, rules: dict) -> bool:
    if rules.get("counties") and o.county not in rules["counties"]:
        return False
    if rules.get("offers") and offer_key(o) not in rules["offers"]:
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
