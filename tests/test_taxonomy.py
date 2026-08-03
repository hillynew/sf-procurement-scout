"""The filter vocabulary, and the invariants that keep it honest.

The point of these tests is narrow but load-bearing: the watchlist dropdown
offers every category in the taxonomy, so anything unreachable by the
classifier becomes a filter that silently matches nothing forever. "0 matches"
then reads as *no such work exists* rather than *this filter is broken*, and
nothing in the UI can tell the two apart.
"""

from __future__ import annotations

import re

import pytest

from src import taxonomy as tx
from src.classify import classify_text, enrich
from src.models.opportunity import OfferType
from web.services.matching import matches_rules


def test_every_offered_category_is_reachable():
    """A category in the dropdown must be one the classifier can actually emit."""
    unreachable = [
        c.slug
        for c in tx.CATEGORIES
        if c.slug != "general" and not c.patterns and not c.anticipated
    ]
    assert not unreachable, (
        "these categories are selectable but can never match: "
        f"{unreachable} — give them patterns or mark anticipated=True"
    )


def test_all_patterns_compile():
    for cat in tx.CATEGORIES:
        for pat in cat.patterns:
            re.compile(pat, re.I)  # raises on a malformed pattern


def test_slugs_are_unique():
    slugs = [c.slug for c in tx.CATEGORIES]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    assert not dupes, f"duplicate category slugs: {sorted(dupes)}"


def test_legacy_slugs_all_survive():
    """Stored opportunities and saved watchlists reference these by name."""
    missing = [s for s in tx.LEGACY_SLUGS if s not in tx.BY_SLUG]
    assert not missing, f"legacy slugs dropped from the taxonomy: {missing}"


def test_umbrellas_resolve_and_do_not_chain():
    for cat in tx.CATEGORIES:
        if not cat.umbrella:
            continue
        assert cat.umbrella in tx.BY_SLUG, f"{cat.slug} points at unknown {cat.umbrella}"
        parent = tx.BY_SLUG[cat.umbrella]
        # `expand()` is deliberately single-level; a chain would silently drop
        # the grandparent and break the legacy filter it exists to preserve.
        assert not parent.umbrella, f"{cat.slug} -> {parent.slug} -> {parent.umbrella}"


def test_every_category_belongs_to_a_declared_group():
    groups = {g.slug for g in tx.GROUPS}
    orphans = [c.slug for c in tx.CATEGORIES if c.group not in groups]
    assert not orphans, f"categories in undeclared groups: {orphans}"


@pytest.mark.parametrize(
    "title, expected_slug, umbrella",
    [
        ("Re-Roofing of Fire Station 12", "roofing", "construction"),
        ("Mosquito Control Aerial Spraying Services", "mosquito_control", None),
        ("Wetland Mitigation and Mangrove Restoration", "habitat_mitigation", None),
        ("Actuarial Services for OPEB Valuation", "actuarial", "professional_services"),
        ("Crossing Guard Services for School Zones", "crossing_guards", "public_safety"),
        ("Naming Rights for the Community Stadium", "advertising_rights",
         "concession_agreements"),
        ("EV Charging Station Installation", "ev_charging", "transportation"),
        ("ASL Interpretation Services", "translation_interpretation",
         "professional_services"),
        ("Employee Benefits Brokerage", "employee_benefits", "financial_services"),
        ("Purchase of Six Backhoe Loaders", "heavy_equipment", "goods_supplies"),
    ],
)
def test_new_categories_are_detected(title, expected_slug, umbrella):
    cats, _, _ = classify_text(title)
    assert expected_slug in cats, f"{title!r} -> {cats}"
    if umbrella:
        assert umbrella in cats, f"{title!r} should roll up into {umbrella}: {cats}"


def test_umbrella_keeps_old_watchlists_working():
    """A rule written against the old vocabulary still catches the new tags."""
    cats, _, _ = classify_text("Re-Roofing of the Public Works Annex")
    assert "roofing" in cats and "construction" in cats


@pytest.mark.parametrize(
    "title, unexpected",
    [
        # These used to be silently mis-filed; the umbrella audit removed them.
        ("Beach Renourishment and Dune Restoration", "waste_recycling"),
        ("Mosquito Control Aerial Spraying", "waste_recycling"),
        ("Homeless Shelter Operations", "healthcare"),
        ("Purchase of Six Backhoe Loaders", "transportation"),
    ],
)
def test_umbrellas_do_not_invent_false_positives(title, unexpected):
    cats, _, _ = classify_text(title)
    assert unexpected not in cats, f"{title!r} wrongly rolled into {unexpected}: {cats}"


def test_bare_pronoun_does_not_tag_it_software():
    """`\\bIT\\b` case-insensitively matches the word "it" — it must not be a rule."""
    cats, _, _ = classify_text("Removal of a Tree and the Stump Under It")
    assert "it_software" not in cats


def test_categories_are_capped_but_umbrellas_survive_the_cap():
    cats, _, _ = classify_text(
        "Construction, Roofing, HVAC, Plumbing, Electrical, Painting, Flooring, "
        "Fencing, Demolition, Concrete and Paving Services"
    )
    detected = [c for c in cats if not tx.BY_SLUG[c].umbrella]
    assert len(cats) >= len(detected)
    assert "construction" in cats


def test_expand_adds_the_umbrella():
    assert tx.expand(["roofing"]) == ["roofing", "construction"]
    assert tx.expand([]) == []
    # Unknown slugs pass through rather than raising — rules outlive taxonomies.
    assert tx.expand(["not_a_real_category"]) == ["not_a_real_category"]


def test_label_and_offer_lookup_degrade_gracefully():
    assert tx.label_for("roofing") == "Roofing"
    assert tx.label_for("some_future_thing") == "Some future thing"
    assert tx.offer_for("roofing") == OfferType.CONSTRUCTION
    assert tx.offer_for("some_future_thing") == OfferType.UNKNOWN


def test_as_dicts_omits_the_fallback_bucket():
    slugs = {c["slug"] for c in tx.as_dicts()}
    assert "general" not in slugs, "'Uncategorized' is not something to watch for"
    assert "roofing" in slugs


# --- rule matching ----------------------------------------------------------


def _opp(opp_factory, **kw):
    return opp_factory(**kw)


def test_category_rule_matches_on_any_overlap(opp_factory):
    o = opp_factory(title="Re-Roofing", categories=["roofing", "construction"])
    assert matches_rules(o, {"categories": ["roofing"]})
    assert matches_rules(o, {"categories": ["construction"]})
    assert matches_rules(o, {"categories": ["plumbing_trade", "roofing"]})
    assert not matches_rules(o, {"categories": ["mosquito_control"]})


def test_category_rule_combines_with_other_rules(opp_factory):
    o = opp_factory(title="Re-Roofing", categories=["roofing"], county="broward")
    assert matches_rules(o, {"categories": ["roofing"], "counties": ["broward"]})
    assert not matches_rules(o, {"categories": ["roofing"], "counties": ["duval"]})


def test_empty_category_rule_is_not_a_filter(opp_factory):
    o = opp_factory(title="Anything", categories=["roofing"])
    assert matches_rules(o, {"categories": []})
    assert matches_rules(o, {})


def test_enrich_still_returns_the_documented_shape():
    fields = enrich("ITB 25-01 Roof Replacement")
    assert set(fields) == {
        "solicitation_type", "offer_type", "categories", "keywords", "external_id",
    }
    assert "construction" in fields["categories"]
