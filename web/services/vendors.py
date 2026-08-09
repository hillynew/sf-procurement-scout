"""Vendor profiles: who wins what, from awards and both contract registers.

"Apex Roofing LLC" on a Legistar agenda, "APEX ROOFING, INC." in FACTS and
"Apex Roofing" in a Bonfire register are one firm. Grouping reuses the same
suffix-stripping normalisation the contractor scout uses (`contractor_id`),
and the display name is the raw form seen most often — never an invented
canonical spelling.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from src.ai.contractors import contractor_id
from src.db import store as db
from src.taxonomy import label_for


def build_vendors(limit: int = 200) -> dict:
    profiles: Dict[str, dict] = {}

    def profile(raw_name: str) -> dict:
        key = contractor_id(raw_name)
        entry = profiles.setdefault(key, {
            "names": Counter(), "awards": 0, "awarded_total": 0,
            "contracts": 0, "agencies": Counter(), "categories": Counter(),
            "last_award": None,
        })
        entry["names"][raw_name.strip()] += 1
        return entry

    for o in db.load_opportunities():
        if o.status != "award" or not o.awarded_vendor:
            continue
        entry = profile(o.awarded_vendor)
        entry["awards"] += 1
        if o.award_amount:
            entry["awarded_total"] += o.award_amount
        entry["agencies"][o.agency] += 1
        for slug in o.categories:
            if slug != "general":
                entry["categories"][slug] += 1
        when = o.award_date or o.posted_date
        if when and (entry["last_award"] is None or when > entry["last_award"]):
            entry["last_award"] = when

    for c in db.load_contracts():
        if not c.vendor:
            continue
        entry = profile(c.vendor)
        entry["contracts"] += 1
        entry["agencies"][c.agency] += 1

    vendors: List[dict] = []
    for entry in profiles.values():
        display, _ = entry["names"].most_common(1)[0]
        vendors.append({
            "name": display,
            "awards": entry["awards"],
            "awarded_total": entry["awarded_total"] or None,
            "contracts": entry["contracts"],
            "agencies": [a for a, _ in entry["agencies"].most_common(3)],
            "categories": [label_for(s) for s, _ in entry["categories"].most_common(3)],
            "last_award": entry["last_award"].isoformat() if entry["last_award"] else None,
        })
    # The firms with the most decided work first: awards weigh over register
    # rows, dollars break ties.
    vendors.sort(key=lambda v: (-v["awards"], -(v["awarded_total"] or 0), -v["contracts"]))
    return {"vendors": vendors[:limit], "total": len(vendors)}
