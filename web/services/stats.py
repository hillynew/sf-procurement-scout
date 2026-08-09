"""Dashboard aggregates. All computed in Python over the loaded snapshot."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

from src.db import store as db
from src.models.opportunity import Opportunity

from .matching import offer_key


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def build_stats(opps: List[Opportunity], workflow: Dict[str, dict]) -> dict:
    open_opps = [o for o in opps if o.status == "open"]
    upcoming = [o for o in opps if o.status == "upcoming"]

    def value_sum(pool) -> int:
        return sum(o.budget_amount or 0 for o in pool)

    today = date.today()
    due_7d = [
        o for o in open_opps
        if o.days_until_due is not None and 0 <= o.days_until_due <= 7
    ]

    # County / type breakdowns over live bids.
    by_county: Dict[str, dict] = {}
    for o in open_opps + upcoming:
        row = by_county.setdefault(o.county, {"county": o.county, "open": 0,
                                              "upcoming": 0, "value": 0})
        row["open" if o.status == "open" else "upcoming"] += 1
        row["value"] += o.budget_amount or 0

    by_type: Dict[str, dict] = {}
    for o in open_opps:
        key = offer_key(o)
        row = by_type.setdefault(key, {"type": key, "count": 0, "value": 0})
        row["count"] += 1
        row["value"] += o.budget_amount or 0

    # Deadline load, next 8 weeks.
    weeks = [_monday(today) + timedelta(weeks=i) for i in range(8)]
    load = {w.isoformat(): {"week": w.isoformat(), "count": 0, "value": 0} for w in weeks}
    for o in open_opps:
        if not o.due_date:
            continue
        w = _monday(o.due_date.date()).isoformat()
        if w in load:
            load[w]["count"] += 1
            load[w]["value"] += o.budget_amount or 0

    # Pipeline stage counts and dollar totals.
    by_id = {o.opportunity_id: o for o in opps}
    stages = {s: {"stage": s, "count": 0, "value": 0} for s in db.STAGES}
    for oid, wf in workflow.items():
        if wf["archived"]:
            continue
        row = stages.get(wf["stage"])
        if row is None:
            continue
        row["count"] += 1
        opp = by_id.get(oid)
        row["value"] += (opp.budget_amount or 0) if opp else 0

    # Win/loss record and revenue by month.
    won = lost = 0
    revenue_cents = 0
    by_month: Dict[str, dict] = {}
    for wf in workflow.values():
        result = wf.get("result")
        if not result:
            continue
        month = str(result["decided_on"])[:7]
        row = by_month.setdefault(month, {"month": month, "won": 0, "lost": 0,
                                          "revenue_cents": 0})
        if result["outcome"] == "won":
            won += 1
            row["won"] += 1
            revenue_cents += result["amount_cents"] or 0
            row["revenue_cents"] += result["amount_cents"] or 0
        else:
            lost += 1
            row["lost"] += 1
    decided = won + lost

    # Source productivity from the latest run's health.
    sources = []
    for h in db.latest_health():
        sources.append({
            "source_id": h.source_id, "name": h.name, "count": h.count,
            "status": str(h.status), "elapsed_ms": h.elapsed_ms,
        })
    sources.sort(key=lambda s: -s["count"])

    trend = [
        {
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "count": r["opp_count"],
            "new_count": r["new_count"],
        }
        for r in db.recent_runs(30)
        if r["status"] == "done"
    ]

    # Needs attention: tracked bids due soon or with unmet requirements.
    attention = []
    for oid, wf in sorted(workflow.items()):
        if wf["archived"] or wf["stage"] == "result":
            continue
        opp = by_id.get(oid)
        # Past-due bids aren't actionable — the pipeline's Result column is
        # where those get resolved.
        if opp is None or opp.days_until_due is None or opp.days_until_due < 0:
            continue
        unmet = [r for i, r in enumerate(opp.requirements)
                 if not (wf["checks"] or {}).get(str(i))]
        if opp.days_until_due <= 7 or (unmet and opp.days_until_due <= 14):
            attention.append({
                "opportunity_id": oid,
                "title": opp.title,
                "days_until_due": opp.days_until_due,
                "stage": wf["stage"],
                "unmet_count": len(unmet),
                "budget_amount": opp.budget_amount,
            })
    attention.sort(key=lambda a: a["days_until_due"])

    return {
        "totals": {
            "open_count": len(open_opps),
            "upcoming_count": len(upcoming),
            "open_value": value_sum(open_opps),
            "due_7d": len(due_7d),
            "due_7d_value": value_sum(due_7d),
            "tracked": sum(1 for wf in workflow.values() if not wf["archived"]),
            "won": won,
            "lost": lost,
            "win_rate": round(won / decided, 3) if decided else None,
            "revenue_cents": revenue_cents,
        },
        "by_county": sorted(by_county.values(), key=lambda r: r["county"]),
        "by_type": sorted(by_type.values(), key=lambda r: -r["count"]),
        "deadline_load": list(load.values()),
        "pipeline": {"stages": list(stages.values())},
        "results_by_month": sorted(by_month.values(), key=lambda r: r["month"]),
        "sources": sources[:10],
        "trend": trend,
        "attention": attention[:8],
    }


# ---------------------------------------------------------------------------
# Data quality
# ---------------------------------------------------------------------------

#: The fields a record is judged on, in display order. Each is (key, label,
#: predicate). "Category" counts anything better than the classifier's
#: "general" fallback; "contact" counts any of the three contact fields.
_QUALITY_FIELDS = (
    ("due_date", "Close date", lambda o: o.due_date is not None),
    ("posted_date", "Issue date", lambda o: o.posted_date is not None),
    ("description", "Description", lambda o: bool(o.description or o.scope)),
    ("category", "Category", lambda o: bool(
        o.raw_category or o.commodity_codes
        or any(c != "general" for c in o.categories))),
    ("commodity_codes", "Commodity codes", lambda o: bool(o.commodity_codes)),
    ("documents", "Documents", lambda o: bool(o.documents)),
    ("budget", "Est. value", lambda o: bool(o.budget)),
    ("contact", "Contact", lambda o: bool(o.contact or o.contact_email or o.contact_phone)),
    ("external_id", "Solicitation #", lambda o: bool(o.external_id)),
    ("tier", "Agency tier", lambda o: bool(o.tier and o.tier != "unknown")),
)

#: Judged over award-status records only.
_AWARD_FIELDS = (
    ("awarded_vendor", "Awarded vendor", lambda o: bool(o.awarded_vendor)),
    ("award_amount", "Award amount", lambda o: o.award_amount is not None),
)


def quality_report(opps: List[Opportunity]) -> dict:
    """Percent of records with each field populated, broken out by source.

    This is the honesty meter: capture fixes and scraper breakage both move
    these numbers, and nothing else in the app states them.
    """
    by_source: Dict[str, List[Opportunity]] = {}
    for o in opps:
        if o.status == "catalog":
            continue
        by_source.setdefault(o.source_id, []).append(o)

    def block(rows: List[Opportunity]) -> dict:
        awards = [o for o in rows if o.status == "award"]
        fields = {
            key: {
                "label": label,
                "count": sum(1 for o in rows if pred(o)),
                "pct": round(100 * sum(1 for o in rows if pred(o)) / len(rows)) if rows else 0,
            }
            for key, label, pred in _QUALITY_FIELDS
        }
        for key, label, pred in _AWARD_FIELDS:
            fields[key] = {
                "label": label,
                "count": sum(1 for o in awards if pred(o)),
                "pct": round(100 * sum(1 for o in awards if pred(o)) / len(awards)) if awards else None,
            }
        return {"records": len(rows), "awards": len(awards), "fields": fields}

    sources = []
    for source_id, rows in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        entry = block(rows)
        entry["source_id"] = source_id
        entry["source_name"] = rows[0].source_name
        sources.append(entry)

    everything = [o for rows in by_source.values() for o in rows]
    return {"overall": block(everything), "sources": sources}
