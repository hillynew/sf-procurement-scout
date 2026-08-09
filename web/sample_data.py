"""Sample snapshot for demoing the Scout Classic screens without a live fetch.

Mirrors the bid set in the design handoff (``Scout Classic.dc.html``) using
real ``Opportunity`` objects, with dates pinned relative to today so the
Today / Pipeline urgency states always look the way the design intends.
Loaded on demand from the dashboard's empty state; a real fetch overwrites it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Dict, List, Tuple

from src.classify import classify_text
from src.models.opportunity import Document, HealthStatus, Opportunity, SourceHealth
from src.sources.registry import load_source_config

_ROOF_SCOPE_LEAD = (
    "Remove and replace the existing modified-bitumen roof system at Fire "
    "Station 12, 2801 NW 9th Avenue, including tear-off to deck, replacement "
    "of deteriorated decking (unit-priced), new tapered insulation, a two-ply "
    "SBS membrane, flashings, copings, and reinstallation of the "
    "lightning-protection system. Work must be sequenced so the station "
    "remains fully operational; crane staging is limited to the west apron."
)
_ROOF_SCOPE_REST = (
    "The contractor shall provide temporary waterproofing at the end of each "
    "shift; no roof area may be left open overnight. Existing rooftop "
    "equipment (two condensing units, antenna mast) shall be disconnected, "
    "cradled, and reinstalled by licensed trades. Per Addendum 1, the "
    "specified membrane is revised to a 60-mil cap sheet, granule-surfaced, "
    "white; bids priced on the original spec will be considered "
    "non-responsive. Warranty: 20-year NDL manufacturer's warranty plus a "
    "2-year contractor workmanship warranty. Liquidated damages of $500 per "
    "calendar day apply beyond the 120-day contract time."
)


def _due(days: int, hour: int = 14) -> datetime:
    return datetime.combine(date.today() + timedelta(days=days), time(hour, 0))


def _mon_day(days: int) -> str:
    d = date.today() + timedelta(days=days)
    return d.strftime("%b %-d") if hasattr(d, "strftime") else str(d)


def build_sample() -> Tuple[Dict[str, Opportunity], List[SourceHealth]]:
    """Return the sample bids keyed like the design prototype, plus health."""
    today = date.today()
    bids: Dict[str, Opportunity] = {}

    def add(key: str, **kw) -> None:
        base = dict(
            source_id="sample",
            source_name="Sample data",
            url="https://example.com/bids/" + key,
            status="open",
            detail_fetched=True,
        )
        base.update(kw)
        # Sample bids declare their offer_type by hand but not their
        # categories, which left every entry in the category picker reading
        # zero on a first-run "Load sample data" — the filter looked broken
        # before the user had any real data to judge it by. Derive them the
        # same way a fetched bid would, without touching the curated fields.
        if not base.get("categories"):
            base["categories"] = classify_text(
                base.get("title", ""), base.get("scope") or ""
            )[0]
        bids[key] = Opportunity(**base)

    add(
        "r1",
        title="Roof repairs — Fire Station 12",
        external_id="RPQ-2026-114",
        agency="Broward County BPRO",
        county="broward",
        solicitation_type="RPQ",
        offer_type="construction",
        posted_date=today - timedelta(days=21),
        due_date=_due(2),
        questions_due=_due(-5, 17),
        budget="$180,000",
        duration_days=120,
        liquidated_damages="$500 / day",
        licenses="CGC or CCC",
        contact="R. Delgado",
        contact_phone="954-357-6065",
        scope=_ROOF_SCOPE_LEAD + " " + _ROOF_SCOPE_REST,
        requirements=["Bid bond 5%", "Performance bond", "E-Verify",
                      "Mandatory site visit"],
        submittal_info="City Hall Rm 210 (sealed, 2 copies)",
        documents=[
            Document(name="Bid package — RPQ-2026-114.pdf", url="#", kind="document"),
            Document(name="Addendum 1 — roofing spec change", url="#", kind="addendum"),
            Document(name="Plans set — FS12 roof.pdf", url="#", kind="drawing"),
            Document(name="Bid form.docx", url="#", kind="document"),
            Document(name="Wage rates.pdf", url="#", kind="document"),
            Document(name="Insurance requirements.pdf", url="#", kind="document"),
        ],
    )
    add(
        "r2",
        title="Janitorial services, citywide",
        external_id="ITB 26-041",
        agency="City of Hollywood",
        county="broward",
        solicitation_type="ITB",
        offer_type="services",
        posted_date=today - timedelta(days=14),
        due_date=_due(3, 15),
        pre_bid_meeting=f"{_mon_day(6)}, 10:00am (non-mandatory)",
        scope=(
            "Custodial services for 14 city facilities including city hall, "
            "three community centers and the police headquarters; day-porter "
            "coverage at two sites."
        ),
        requirements=["Insurance cert", "Local preference affidavit",
                      "References x3"],
        prior_cycles=2,
        last_cycle_closed=date(2023, 3, 31),
        documents=[
            Document(name="ITB 26-041 package.pdf", url="#", kind="document"),
            Document(name="Facility list + sq footage.xlsx", url="#", kind="document"),
        ],
    )
    add(
        "r3",
        title="Sidewalk ADA improvements Ph. 2",
        external_id="ISD-26-2210",
        agency="Miami-Dade ISD",
        county="miami-dade",
        solicitation_type="ITB",
        offer_type="construction",
        posted_date=today,
        due_date=_due(12),
        budget="$450,000",
        duration_days=180,
        licenses="CGC",
        project_location="NW 7th Ave corridor",
        scope=(
            "Removal and replacement of non-compliant sidewalk segments, curb "
            "ramps and detectable warnings along the NW 7th Avenue corridor; "
            "unit-price contract."
        ),
        requirements=["Bid bond 5%", "SBE 15% goal", "Prevailing wage"],
        documents=[
            Document(name="Bid package ISD-26-2210.pdf", url="#", kind="document"),
            Document(name="Plan sheets 1–44.pdf", url="#", kind="drawing"),
        ],
    )
    add(
        "r4",
        title="Park pavilion re-roof",
        external_id="B-26-18",
        agency="City of Tamarac",
        county="broward",
        solicitation_type="ITB",
        offer_type="construction",
        posted_date=today,
        due_date=_due(17),
        budget="$120,000",
        licenses="CCC",
        scope=(
            "Re-roof of four park pavilions: standing-seam metal over new "
            "underlayment; incidental fascia repair."
        ),
        requirements=["Bid bond 5%", "Insurance cert"],
        documents=[Document(name="Bid B-26-18 package.pdf", url="#", kind="document")],
    )
    add(
        "r5",
        title="HVAC preventive maintenance, 3 yr",
        external_id="RFP 26-207",
        agency="Florida Atlantic University",
        county="palm-beach",
        solicitation_type="RFP",
        offer_type="services",
        posted_date=today,
        due_date=_due(26),
        questions_due=_due(10, 17),
        scope=(
            "Scheduled preventive maintenance for campus air-handling units, "
            "chillers and controls across the Boca Raton campus; quarterly "
            "service schedule."
        ),
        requirements=["Insurance cert", "References x3",
                      "Technician certifications"],
        documents=[
            Document(name="RFP 26-207.pdf", url="#", kind="document"),
            Document(name="Equipment schedule.xlsx", url="#", kind="document"),
        ],
    )
    add(
        "r6",
        title="Guardrail replacement, district-wide",
        external_id="PBS 26-C-011",
        agency="Palm Beach Schools",
        county="palm-beach",
        solicitation_type="ITB",
        offer_type="construction",
        posted_date=today,
        due_date=_due(24),
        budget="$210,000",
        duration_days=90,
        licenses="CGC",
        scope=(
            "Replacement of damaged guardrail and bollards at 12 school "
            "sites; unit-price contract with district-issued work orders."
        ),
        requirements=["Bid bond 5%", "Jessica Lunsford screening"],
        documents=[Document(name="Bid PBS 26-C-011.pdf", url="#", kind="document")],
    )
    add(
        "p1",
        title="Fence repairs, parks pkg C",
        external_id="ITB 25-119C",
        agency="Broward County",
        county="broward",
        solicitation_type="ITB",
        offer_type="construction",
        status="closed",
        posted_date=today - timedelta(days=40),
        due_date=_due(-11),
        bid_opening=f"{_mon_day(18)}, 10:00am",
        scope="Chain-link and ornamental fence repair at seven regional parks.",
        requirements=["Performance bond on award"],
        documents=[Document(name="Our submission — pkg C.pdf", url="#", kind="document")],
    )
    add(
        "p2",
        title="Sidewalk grinding, zone 4",
        external_id="B-25-201",
        agency="City of Hollywood",
        county="broward",
        solicitation_type="ITB",
        offer_type="construction",
        status="closed",
        posted_date=today - timedelta(days=55),
        due_date=_due(-25),
        scope="Trip-hazard grinding and panel replacement, residential zone 4.",
        documents=[
            Document(name="Our submission.pdf", url="#", kind="document"),
            Document(name="Bid tab (opening).pdf", url="#", kind="document"),
        ],
    )
    add(
        "p3",
        title="Pressure washing, garages",
        external_id="ITB 26-006",
        agency="City of Boca Raton",
        county="palm-beach",
        solicitation_type="ITB",
        offer_type="services",
        status="closed",
        posted_date=today - timedelta(days=63),
        due_date=_due(-33),
        scope="Quarterly pressure washing of three municipal parking structures.",
        documents=[Document(name="Our submission.pdf", url="#", kind="document")],
    )
    add(
        "b1",
        title="Fence repairs, parks pkg B",
        external_id="ITB 25-119B",
        agency="Broward County",
        county="broward",
        solicitation_type="ITB",
        offer_type="construction",
        status="closed",
        posted_date=today - timedelta(days=120),
        due_date=_due(-80),
        scope="Chain-link and ornamental fence repair at five regional parks.",
        documents=[Document(name="Our submission — pkg B.pdf", url="#", kind="document")],
    )
    add(
        "w3",
        title="Library roof recoat",
        external_id="B-26-031",
        agency="City of Boca Raton",
        county="palm-beach",
        solicitation_type="ITB",
        offer_type="construction",
        posted_date=today - timedelta(days=10),
        due_date=_due(41),
        licenses="CCC",
        scope=(
            "Silicone recoat of the downtown library roof, approx 22,000 sf, "
            "including minor blister repair."
        ),
        requirements=["Insurance cert"],
        documents=[Document(name="Bid B-26-031.pdf", url="#", kind="document")],
    )
    add(
        "w4",
        title="Custodial services, MDC North",
        external_id="MDC-2026-08",
        agency="Miami Dade College",
        county="miami-dade",
        solicitation_type="ITB",
        offer_type="services",
        posted_date=today - timedelta(days=8),
        due_date=_due(37),
        project_location="North campus, 11380 NW 27th Ave",
        scope=(
            "Full custodial services for the North campus academic buildings; "
            "night crew plus day porters."
        ),
        requirements=["Insurance cert", "References x3"],
        documents=[Document(name="MDC bid posting.pdf", url="#", kind="document")],
    )

    # Award records — the decided side of the market. Without these the
    # Awards screen, the protest card, and the price medians all demo as
    # empty states, which reads as "the feature does not exist" on a first
    # look. One carries a live 72-hour protest window.
    from src.protest import protest_deadline

    add(
        "a1",
        title="Intended award: Roof repairs — Fire Station 12",
        agency="City of Hollywood",
        county="broward",
        solicitation_type="ITB",
        offer_type="construction",
        status="award",
        external_id="ITB-26-104",
        posted_date=today,
        award_date=today,
        awarded_vendor="Crown Roofing & Sheet Metal, Inc",
        award_amount=487_500,
        linked_ref="ITB-26-104",
        award_linkage="ref",
        protest_deadline=protest_deadline(datetime.combine(today, time(14, 0))),
        description="Notice of intended decision posted; 72-hour protest clock running.",
    )
    add(
        "a2",
        title="MOTION TO AWARD open-end contract to low bidder, Sunshine Custodial "
              "Services, LLC, for Janitorial Services, Bid No. JN-25-011, in the "
              "initial one-year estimated amount of $193,500",
        agency="Broward County",
        county="broward",
        solicitation_type="ITB",
        offer_type="services",
        status="award",
        external_id="2026-0412",
        posted_date=today - timedelta(days=3),
        award_date=today - timedelta(days=3),
        awarded_vendor="Sunshine Custodial Services, LLC",
        award_amount=193_500,
        linked_ref="JN-25-011",
        award_linkage="ref",
    )
    add(
        "a3",
        title="FDOT letting 07/31: contract E4Y08 — Miami-Dade County",
        agency="Florida Department of Transportation",
        county="miami-dade",
        offer_type="construction",
        status="award",
        external_id="E4Y08",
        posted_date=today - timedelta(days=9),
        award_date=today - timedelta(days=9),
        awarded_vendor="H&R Paving, Inc",
        award_amount=31_366_638,
        linked_ref="429487-2-52-01",
        award_linkage="ref",
        description="Preliminary letting results (apparent low bid first). 4 bids.",
    )

    return bids, _sample_health()


def _sample_health() -> List[SourceHealth]:
    """Plausible health for the *real* configured sources."""
    degraded_notes = {
        "west_palm_beach": "WAF blocked · using DemandStar fallback · 3rd day",
        "hialeah": "parsed 0 rows where rows expected · layout change?",
    }
    health: List[SourceHealth] = []
    degraded_used = 0
    for i, cfg in enumerate(load_source_config()):
        sid = str(cfg.get("id", f"src{i}"))
        name = str(cfg.get("name", sid))
        note_key = next((k for k in degraded_notes if k in sid.lower()), None)
        if note_key and degraded_used < 2:
            degraded_used += 1
            health.append(SourceHealth(
                source_id=sid, name=name, ok=False, count=0,
                elapsed_ms=400 + (i * 137) % 900,
                status=HealthStatus.DEGRADED, note=degraded_notes[note_key],
            ))
        elif i % 13 == 7:
            health.append(SourceHealth(
                source_id=sid, name=name, ok=True, count=0,
                elapsed_ms=300 + (i * 211) % 1200, status=HealthStatus.EMPTY,
                note="no listings",
            ))
        else:
            health.append(SourceHealth(
                source_id=sid, name=name, ok=True, count=1 + (i * 7) % 14,
                elapsed_ms=600 + (i * 173) % 2500, status=HealthStatus.OK,
            ))
    return health


def load_sample() -> dict:
    """Write the sample snapshot to the database and seed a matching pipeline.

    Refused outright while real captured records exist: saving a snapshot
    marks every row not in it absent and ages open ones to closed, so a demo
    load against a live database replaces the pipeline with fiction. That is
    exactly what happened in production on 2026-08-09 — this endpoint is
    reachable by one click from the Settings screen. Loading over a previous
    *demo* snapshot stays allowed, so the button is still re-runnable where
    it belongs: a fresh or demo-only database.
    """
    from src.db import store as db

    db.bootstrap()
    real = db.count_real_opportunities()
    if real:
        return {"count": 0, "seeded_pipeline": False, "loaded": False,
                "real_rows": real}

    bids, health = build_sample()
    # A sentinel health row marks the run as demo-born, so `purge("demo")`
    # can find and remove it without touching real run history.
    health.insert(0, SourceHealth(
        source_id="sample", name="Sample data", ok=True, count=len(bids),
        status=HealthStatus.OK, note="demo snapshot — nothing was fetched",
    ))
    result = db.save_snapshot(list(bids.values()), health)

    if db.workflow_state():
        return {"count": result.count, "seeded_pipeline": False, "loaded": True}

    seed_stages = {
        "r3": "watching", "r6": "watching", "w3": "watching", "w4": "watching",
        "r1": "preparing", "r2": "preparing",
        "p1": "submitted", "p2": "submitted",
        "p3": "result", "b1": "result",
    }
    # A small contract register so "expiring — likely rebids" demos too.
    from src.contracts import Contract

    db.save_contracts([
        Contract(
            contract_id="SAMPLE-JAN-22", agency="Broward County",
            name="Janitorial Services — Government Center", source_id="sample",
            vendor="Sparkle Building Services, Inc",
            start_date=date.today() - timedelta(days=1000),
            end_date=date.today() + timedelta(days=55),
            extendable=False, amount=612_000.0,
        ),
        Contract(
            contract_id="SAMPLE-HVAC-19", agency="City of Hollywood",
            name="HVAC Preventive Maintenance, citywide", source_id="sample",
            vendor="Polar Air Mechanical Corp",
            start_date=date.today() - timedelta(days=700),
            end_date=date.today() + timedelta(days=130),
            extendable=True,
        ),
    ])

    for key, stage in seed_stages.items():
        oid = bids[key].opportunity_id
        db.set_tracked(oid, True)
        if stage != "watching":
            db.update_tracked(oid, stage=stage)
    # Two decided bids so win rate and revenue demo well on the Dashboard.
    db.set_result(bids["b1"].opportunity_id, "won", amount_cents=9_240_000,
                  notes="Beat two other bidders on price.",
                  decided_on=date.today() - timedelta(days=18))
    db.set_result(bids["p3"].opportunity_id, "lost",
                  notes="Lost on bonding capacity.",
                  decided_on=date.today() - timedelta(days=41))
    db.update_tracked(bids["r1"].opportunity_id, checks={"0": True})
    return {"count": result.count, "seeded_pipeline": True, "loaded": True}
