"""Go/no-go scorecard heuristics for the Bid Workroom.

Three meters, each 0–100 with a written breakdown so the UI can explain
itself (and tests can pin behavior):

- **Fit for our crews** — does this bid look like the work the user already
  tracks, watches and wins?
- **Capacity in <month>** — how loaded is the pipeline around this bid's
  due date?
- **Expected margin** — commercial-risk signals read off the bid itself
  (rebids, liquidated damages, bonding/compliance overhead, $/day).

These are transparent heuristics over data the pipeline already extracts —
not predictions. Every adjustment carries a reason string, shown as a
tooltip on the meter.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Dict, List, Optional, Sequence

from .models.opportunity import Opportunity

# Requirements whose presence adds compliance overhead to a bid.
_COMPLIANCE = re.compile(
    r"prevailing wage|davis[- ]bacon|sbe|mbe|dbe|local preference", re.I
)


@dataclass
class Meter:
    label: str
    score: int
    reasons: List[str] = field(default_factory=list)

    @property
    def tooltip(self) -> str:
        return " · ".join(self.reasons)


def _clamp(n: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(n))))


def _offer(o: Opportunity) -> str:
    s = o.offer_type
    return str(s.value if hasattr(s, "value") else s or "unknown")


def fit_score(
    o: Opportunity,
    tracked: Sequence[Opportunity],
    *,
    watchlist_hits: int = 0,
    won_offers: Sequence[str] = (),
) -> Meter:
    score = 40.0
    reasons = ["baseline 40"]

    if watchlist_hits:
        bump = 20 if watchlist_hits == 1 else 30
        score += bump
        plural = "" if watchlist_hits == 1 else "s"
        reasons.append(f"matches {watchlist_hits} of your watchlist{plural} (+{bump})")

    others = [t for t in tracked if t.opportunity_id != o.opportunity_id]
    if others:
        offers = Counter(_offer(t) for t in others)
        modal, _ = offers.most_common(1)[0]
        if modal != "unknown" and _offer(o) == modal:
            score += 15
            reasons.append(f"most of your pipeline is {modal.replace('_', ' ')} (+15)")
        if any(t.county == o.county for t in others):
            score += 5
            reasons.append("you already work this county (+5)")

    if _offer(o) in set(won_offers):
        score += 10
        reasons.append(f"you have won {_offer(o).replace('_', ' ')} work (+10)")

    if _offer(o) == "unknown":
        score -= 10
        reasons.append("work type unclear from the listing (−10)")

    return Meter("Fit for our crews", _clamp(score, 5, 95), reasons)


def capacity_score(
    o: Opportunity,
    committed: Sequence[Opportunity],
    *,
    window_days: int = 14,
) -> Meter:
    """Load = other bids you are preparing/submitted with due dates near this one."""
    label_month = (o.due_date.strftime("%B") if o.due_date else None) or "this window"
    label = f"Capacity in {label_month}"
    if not o.due_date:
        return Meter(label, 60, ["no due date — assuming moderate load"])
    near = 0
    window = timedelta(days=window_days)
    for t in committed:
        if t.opportunity_id == o.opportunity_id or not t.due_date:
            continue
        if abs(t.due_date - o.due_date) <= window:
            near += 1
    score = 90 - 20 * near
    if near:
        plural = "" if near == 1 else "s"
        reasons = [f"{near} other committed bid{plural} due within {window_days} days (−{20 * near})"]
    else:
        reasons = ["no other committed bids due near this one"]
    return Meter(label, _clamp(score, 10, 90), reasons)


def margin_score(o: Opportunity) -> Meter:
    score = 60.0
    reasons = ["baseline 60"]

    if o.prior_cycles:
        score -= 10
        reasons.append("rebid — likely a priced incumbent (−10)")
    if o.liquidated_damages:
        score -= 10
        reasons.append(f"liquidated damages {o.liquidated_damages} (−10)")
    if any("bond" in r.lower() for r in o.requirements):
        score -= 5
        reasons.append("bonding costs (−5)")
    if any(_COMPLIANCE.search(r) for r in o.requirements):
        score -= 5
        reasons.append("compliance overhead — wage/participation terms (−5)")

    per_day = _budget_per_day(o)
    if per_day is not None:
        if per_day >= 3_000:
            score += 10
            reasons.append(f"roomy schedule at ~${per_day:,.0f}/day (+10)")
        elif per_day < 1_000:
            score -= 10
            reasons.append(f"tight at ~${per_day:,.0f}/day (−10)")

    if o.detail_score < 50:
        score -= 5
        reasons.append("thin listing — unknowns cost margin (−5)")

    return Meter("Expected margin", _clamp(score, 15, 90), reasons)


def _budget_per_day(o: Opportunity) -> Optional[float]:
    if not o.budget or not o.duration_days:
        return None
    digits = re.sub(r"[^\d]", "", o.budget.split("-")[0].split("–")[0])
    if not digits:
        return None
    return int(digits) / o.duration_days


def go_no_go(
    o: Opportunity,
    *,
    tracked: Sequence[Opportunity],
    committed: Sequence[Opportunity],
    watchlist_hits: int = 0,
    results: Optional[Dict[str, str]] = None,
    tracked_by_id: Optional[Dict[str, Opportunity]] = None,
) -> List[Meter]:
    """The three workroom meters for one bid."""
    won_offers: List[str] = []
    for oid, outcome in (results or {}).items():
        if str(outcome).upper().startswith("WON") and tracked_by_id and oid in tracked_by_id:
            won_offers.append(_offer(tracked_by_id[oid]))
    return [
        fit_score(o, tracked, watchlist_hits=watchlist_hits, won_offers=won_offers),
        capacity_score(o, committed),
        margin_score(o),
    ]
