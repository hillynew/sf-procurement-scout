"""Statewide geography: the 67 counties and county inference.

County stopped being cosmetic when the scout went statewide — it is the primary
filter in the UI, so a bad inference does not look like a bug, it looks like the
bid does not exist. These tests pin the cases that actually bite.
"""

from __future__ import annotations

import pytest

from src.fl_geo import (
    ALL_REGIONS,
    COUNTY_NAMES,
    COUNTY_REGION,
    PSEUDO_COUNTIES,
    REGIONS,
    county_label,
    infer_county,
    region_of,
    summarise_coverage,
)


def test_there_are_exactly_sixty_seven_counties():
    assert len(COUNTY_NAMES) == 67


def test_every_county_belongs_to_exactly_one_region():
    seen: list[str] = []
    for counties in REGIONS.values():
        seen.extend(counties)
    assert len(seen) == len(set(seen)), "a county is listed in two regions"
    assert set(seen) == set(COUNTY_NAMES)


def test_labels_cover_counties_and_buckets():
    assert set(ALL_REGIONS) == set(COUNTY_NAMES) | set(PSEUDO_COUNTIES)
    assert county_label("miami-dade") == "Miami-Dade"
    assert county_label("st-johns") == "St. Johns"
    assert county_label("desoto") == "DeSoto"


def test_unknown_slug_degrades_to_something_printable():
    """A label lookup must never surface a raw slug like 'st-johns' to a user."""
    assert county_label("made-up-place") == "Made Up Place"


@pytest.mark.parametrize(
    "name,expected",
    [
        # Explicit "<County> County" is the strongest signal.
        ("Broward County Purchasing Division", "broward"),
        ("St. Johns County - Purchasing Department", "st-johns"),
        ("Escambia County School District", "escambia"),
        # Cities whose name gives no county away.
        ("City of Ocoee", "orange"),
        ("City of North Port", "sarasota"),
        ("Village of Estero", "lee"),
        ("Town of Palm Beach", "palm-beach"),
        # Institutions that follow no place-name pattern.
        ("University of West Florida", "escambia"),
        ("Emerald Coast Utilities Authority", "escambia"),
        ("Central Florida Expressway Authority", "orange"),
        ("Pasco-Hernando State College", "pasco"),
        # Bodies that span the state.
        ("Florida Department of Transportation (FDOT)", "statewide"),
        ("Southwest Florida Water Management District", "statewide"),
        ("Department of Children and Families (DCF)", "statewide"),
        ("Agency for Persons with Disabilities", "statewide"),
    ],
)
def test_infer_county(name, expected):
    assert infer_county(name) == expected


def test_state_body_prefix_does_not_swallow_a_county_department():
    """'Miami-Dade County Department of X' is local, not statewide.

    The state-body rule is anchored at the start of the string precisely so a
    county's own departments keep their county.
    """
    assert infer_county("Miami-Dade County Department of Transportation") == "miami-dade"
    assert infer_county("Broward County Office of Economic Development") == "broward"


def test_longest_city_match_wins():
    """'Miami Beach' must not be swallowed by the substring 'Miami'."""
    assert infer_county("City of Miami Beach") == "miami-dade"
    assert infer_county("City of Miami") == "miami-dade"
    assert infer_county("City of Palm Beach Gardens") == "palm-beach"


def test_an_unplaceable_name_is_unknown_rather_than_a_guess():
    """Filing a Panhandle agency under Miami-Dade is worse than admitting doubt."""
    assert infer_county("Acme Consulting LLC") == "unknown"
    assert infer_county("") == "unknown"


def test_an_explicit_hint_beats_inference():
    assert infer_county("City of Ocoee", hint="Orange") == "orange"
    assert infer_county("Some Vendor", hint="leon") == "leon"


def test_region_lookup():
    assert region_of("st-johns") == "northeast"
    assert region_of("miami-dade") == "southeast"
    assert region_of("statewide") == "statewide"
    assert COUNTY_REGION["leon"] == "northwest"


def test_coverage_counts_only_real_counties():
    covered, total = summarise_coverage(
        ["broward", "leon", "statewide", "federal", "unknown", "broward"]
    )
    assert (covered, total) == (2, 67)
