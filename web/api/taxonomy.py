"""The filter vocabulary: what you can watch for, independent of what's in stock.

The dropdown is served from here rather than assembled from the current
snapshot on purpose. A picker built from live data can only offer what has
already been fetched, which quietly makes the most useful watchlist — "tell me
when the first one of these appears" — the one thing you cannot create.

Counts still come along, because an anticipatory vocabulary without them is
indistinguishable from a broken one: "0 matches" should read as *nothing open
right now*, not *this filter does nothing*. The UI shows the count next to the
label and keeps every option selectable either way.
"""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter

from src import taxonomy as tx
from src.db import store as db
from src.fl_geo import ALL_REGIONS, COUNTY_NAMES, PSEUDO_COUNTIES, REGION_LABEL, region_of
from src.models.opportunity import OfferType

router = APIRouter()

#: Order matters — this is the order the coarse work-type picker renders in.
OFFER_LABELS = [
    (OfferType.CONSTRUCTION.value, "Construction"),
    (OfferType.SERVICES.value, "Services"),
    (OfferType.PROFESSIONAL_SERVICES.value, "Professional services"),
    (OfferType.GOODS.value, "Goods"),
    (OfferType.MIXED.value, "Mixed"),
    (OfferType.UNKNOWN.value, "Unclassified"),
]


@router.get("/taxonomy")
def get_taxonomy():
    """Every filterable category, county, and work type, with live counts."""
    try:
        opps = db.load_opportunities(present_only=True)
    except Exception:  # noqa: BLE001 — an empty DB must still yield a full picker
        opps = []

    open_pool = [o for o in opps if o.status in ("open", "upcoming")]

    cat_counts: Counter = Counter()
    for o in open_pool:
        for slug in set(o.categories or []):
            cat_counts[slug] += 1

    county_counts = Counter(o.county for o in open_pool)
    offer_counts: Counter = Counter()
    for o in open_pool:
        ot = o.offer_type
        offer_counts[str(ot.value if hasattr(ot, "value") else ot or "unknown")] += 1

    categories = [
        dict(c, count=cat_counts.get(c["slug"], 0)) for c in tx.as_dicts()
    ]

    # Counties: the canonical 67 plus the buckets, not merely the ones seen.
    counties = [
        {
            "slug": slug,
            "label": label,
            "region": region_of(slug),
            "region_label": REGION_LABEL.get(region_of(slug), "Other"),
            "count": county_counts.get(slug, 0),
        }
        for slug, label in list(COUNTY_NAMES.items()) + list(PSEUDO_COUNTIES.items())
    ]
    counties.sort(key=lambda c: (c["region_label"], c["label"]))

    return {
        "groups": tx.groups_as_dicts(),
        "categories": categories,
        "offer_types": [
            {"key": k, "label": lbl, "count": offer_counts.get(k, 0)}
            for k, lbl in OFFER_LABELS
        ],
        "counties": counties,
        "county_labels": ALL_REGIONS,
        "total_open": len(open_pool),
    }
