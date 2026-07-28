"""Classification rules and deal-brief generation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.classify import (
    classify_text,
    detect_solicitation_type,
    enrich,
    extract_external_id,
)
from src.models.opportunity import OfferType, SolicitationType
from src.summarize import apply_briefs, make_brief


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Request for Proposals for Janitorial Services", SolicitationType.RFP),
        ("ITB 25-26-120 Pressure Washing", SolicitationType.ITB),
        ("Invitation to Negotiate — Software", SolicitationType.ITN),
        ("Request for Qualifications for Fence Repair", SolicitationType.RFQ),
        ("CCNA Continuing Services", SolicitationType.CCNA),
        # Florida-specific types that appear throughout the live data
        ("RPQ No P16370 Pump Station Generator Relocation", SolicitationType.RPQ),
        ("Request for Price Quotation — Sidewalk Repair", SolicitationType.RPQ),
        ("ITQ No. 20-25-26 Neat Streets Tree Planting", SolicitationType.ITQ),
        ("Invitation to Quote for Safety Boots", SolicitationType.ITQ),
        ("RLI No. 12-26 Design Services", SolicitationType.RLI),
        ("Lost and Found Management Software", SolicitationType.UNKNOWN),
        ("", SolicitationType.UNKNOWN),
    ],
)
def test_solicitation_type_detection(text, expected):
    assert detect_solicitation_type(text) == expected


def test_price_quotation_is_not_confused_with_qualifications():
    """RPQ and RFQ are different instruments; both appear in Miami-Dade data."""
    assert detect_solicitation_type("RPQ No AC013A") == SolicitationType.RPQ
    assert detect_solicitation_type("Request for Qualifications") == SolicitationType.RFQ


@pytest.mark.parametrize(
    "title, category, offer",
    [
        ("Roof Replacement at Fire Station 12", "construction", OfferType.CONSTRUCTION),
        ("Managed Security Operations Center Services", "it_software", OfferType.SERVICES),
        ("Tree Trimming & Grounds Services", "facilities_maintenance", OfferType.SERVICES),
        ("Safety Shoes and Boots", "goods_supplies", OfferType.GOODS),
    ],
)
def test_category_and_offer_classification(title, category, offer):
    cats, got_offer, _ = classify_text(title)
    assert category in cats
    assert got_offer == offer


def test_construction_wins_over_other_signals():
    """A roofing job that mentions software is still construction work."""
    _, offer, _ = classify_text("Roof Replacement including HVAC controls software")
    assert offer == OfferType.CONSTRUCTION


def test_unclassifiable_title_is_general_and_unknown():
    cats, offer, _ = classify_text("Greynolds Park Love-In")
    assert cats == ["general"]
    assert offer == OfferType.UNKNOWN


@pytest.mark.parametrize(
    "text, expected",
    [
        ("ITB 25-26-120 MK-Pressure Washing", "ITB 25-26-120"),
        ("Reference number: RFP0000004 Cellular Devices", "RFP0000004"),
        ("Nothing here at all", None),
    ],
)
def test_external_id_extraction(text, expected):
    assert extract_external_id(text) == expected


def test_enrich_prefers_the_supplied_reference():
    fields = enrich("Pressure Washing", external_id="ITB 25-26-120")
    assert fields["external_id"] == "ITB 25-26-120"
    assert fields["solicitation_type"] == SolicitationType.ITB


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


def test_brief_flags_an_urgent_deadline(opp_factory):
    o = opp_factory(due_date=datetime.now() + timedelta(days=3), status="open")
    assert "URGENT" in make_brief(o)


def test_brief_flags_due_today(opp_factory):
    o = opp_factory(due_date=datetime.now().replace(hour=23, minute=59), status="open")
    assert "DUE TODAY" in make_brief(o)


def test_brief_is_calm_for_a_distant_deadline(opp_factory):
    o = opp_factory(due_date=datetime.now() + timedelta(days=45), status="open")
    brief = make_brief(o)
    assert "URGENT" not in brief and "due in 45d" in brief


def test_brief_handles_a_missing_due_date(opp_factory):
    assert "not published" in make_brief(opp_factory(due_date=None))


def test_brief_names_the_agency_and_reference(opp_factory):
    o = opp_factory(agency="Broward County", external_id="ITB-2026-042")
    brief = make_brief(o)
    assert "Broward County" in brief and "ITB-2026-042" in brief


def test_apply_briefs_does_not_overwrite_an_existing_brief(opp_factory):
    o = opp_factory(brief="hand written")
    apply_briefs([o])
    assert o.brief == "hand written"


def test_apply_briefs_fills_empty_ones(opp_factory):
    o = opp_factory()
    apply_briefs([o])
    assert o.brief


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


def test_opportunity_id_is_stable_across_refreshes(opp_factory):
    assert opp_factory().opportunity_id == opp_factory().opportunity_id


def test_opportunity_id_differs_between_listings(opp_factory):
    a = opp_factory(title="Roof Repair")
    b = opp_factory(title="Fence Repair")
    assert a.opportunity_id != b.opportunity_id


def test_days_until_due(opp_factory):
    assert opp_factory(due_date=datetime.now() + timedelta(days=10)).days_until_due == 10
    assert opp_factory(due_date=None).days_until_due is None


def test_to_row_flattens_for_csv(opp_factory):
    row = opp_factory(categories=["construction", "goods_supplies"]).to_row()
    assert row["categories"] == "construction, goods_supplies"
    assert set(row) >= {"opportunity_id", "title", "county", "url", "status", "due_date"}
    assert all(not isinstance(v, (list, dict)) for v in row.values())
