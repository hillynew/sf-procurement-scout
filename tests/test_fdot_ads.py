"""FDOT advertisements: the token, the planned ads, and the district problem."""

from __future__ import annotations

import json

import pytest

from src.sources.fdot_ads import (
    API,
    DISTRICT_COUNTIES,
    STATUS,
    FdotAdsAdapter,
    akey_from,
    district_label,
)

CFG = {
    "id": "fdot_ps",
    "name": "FDOT Professional Services Advertisements",
    "county": "statewide",
    "agency": "Florida Department of Transportation",
    "portal_url": "https://pdaexternal.fdot.gov/Pub/AdvertisementPublic/AllAdDetail/PS/A",
    "fdot_procurement_path": "PS",
}

AKEY = "e74c64f19f5849e399bd6a539b5f5d48:JmeSlJCH:b8d55bad:1786110262"


def _page(akey=AKEY, var="AllAdInitParams"):
    params = json.dumps({"ProcrPathCodeValue": "PS", "PageView": "A", "akey": akey})
    return (
        f"<html><body><script>window.{var} = JSON.parse('{params}');"
        f" uuid = window.{var}.akey;</script></body></html>"
    )


def _ad(number="27220", description="I-10(SR8) from W of SR25(US41)",
        status="Current", district="02", deadline="2026-08-17T17:00:00",
        advertised="2026-08-03T16:00:00", amount="2950000.0"):
    return {
        "AdNumber": number,
        "AdShortDescription": description,
        "AdStatusTypeName": status,
        "DotAssignedDistrictCode": district,
        "ResponseDeadlineDateTime": deadline,
        "LastDateAdvertised": advertised,
        "AdContractAmount": amount,
        # The API really does send display HTML inside JSON, doubly escaped.
        "MinorWorkTypesText": " 7.1-Signing, Pavement Marking &amp; Channelization &lt;br/&gt; ",
    }


def _adapter(monkeypatch, ads, *, page=None):
    a = FdotAdsAdapter(CFG)
    seen = {"headers": None, "params": None}

    monkeypatch.setattr(
        "src.sources.fdot_ads.get",
        lambda url, **kw: type("R", (), {"text": _page() if page is None else page})(),
    )

    def fake_json(url, **kw):
        seen["headers"] = kw.get("headers") or {}
        seen["params"] = kw.get("params") or {}
        assert url == API
        return {"Model": {"AdList": ads}}

    monkeypatch.setattr("src.sources.fdot_ads.get_json", fake_json)
    monkeypatch.setattr(FdotAdsAdapter, "_session", lambda self: None)
    return a, seen


# -- the token -------------------------------------------------------------


def test_the_token_is_read_off_the_page_that_mints_it():
    assert akey_from(_page()) == AKEY


def test_both_spellings_of_the_token_variable_are_accepted():
    """`InitParams` on the district-selection page, `AllAdInitParams` here."""
    assert akey_from(_page(var="InitParams")) == AKEY
    assert akey_from(_page(var="AllAdInitParams")) == AKEY


def test_a_page_without_a_token_yields_none():
    assert akey_from("<html><body>maintenance</body></html>") is None
    assert akey_from("") is None


def test_a_token_that_is_not_json_yields_none():
    assert akey_from("<script>window.InitParams = JSON.parse('not json');</script>") is None


def test_the_token_is_sent_as_the_header_the_api_wants(monkeypatch):
    """Without it the API answers 401 with an empty body, which reads as a
    broken endpoint rather than a missing header."""
    a, seen = _adapter(monkeypatch, [_ad()])
    a.fetch()

    assert seen["headers"]["Authentication"] == AKEY


def test_a_page_with_no_token_is_reported_not_guessed(monkeypatch):
    a, _ = _adapter(monkeypatch, [_ad()], page="<html>down</html>")

    assert a.fetch() == []
    assert a.degraded_reason and "token" in a.degraded_reason


# -- the query -------------------------------------------------------------


def test_one_call_asks_for_every_district_and_every_status(monkeypatch):
    """Empty DistrictCode is statewide and PageView=A is all four views, so one
    request does the work of thirty-two."""
    a, seen = _adapter(monkeypatch, [_ad()])
    a.fetch()

    assert seen["params"]["DistrictCode"] == ""
    assert seen["params"]["PageView"] == "A"
    assert seen["params"]["ProcrPathCodeValue"] == "PS"


def test_the_procurement_path_is_validated():
    cfg = {**CFG, "fdot_procurement_path": "PROFESSIONAL"}
    with pytest.raises(ValueError, match="PS or D-B"):
        FdotAdsAdapter(cfg).fetch()


def test_a_missing_procurement_path_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "fdot_procurement_path"}
    with pytest.raises(ValueError, match="fdot_procurement_path"):
        FdotAdsAdapter(cfg).fetch()


# -- mapping ---------------------------------------------------------------


def test_a_current_ad_becomes_an_open_opportunity(monkeypatch):
    a, _ = _adapter(monkeypatch, [_ad()])
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.external_id == "27220"
    assert opp.due_date is not None and opp.due_date.hour == 17
    assert opp.posted_date is not None and opp.posted_date.day == 3
    assert opp.budget == "$3.0M"
    assert opp.department == "FDOT District 2"


def test_a_planned_ad_is_upcoming_not_open(monkeypatch):
    """A Notice of Planned Advertisement is months ahead of the advertisement.

    Nothing else in this build sees work that early, and it must not sit on the
    open board as though it could be bid today.
    """
    a, _ = _adapter(monkeypatch, [_ad(status="Planned")])
    (opp,) = a.fetch()

    assert opp.status == "upcoming"


@pytest.mark.parametrize("portal,expected", [
    ("Current", "open"),
    ("Planned", "upcoming"),
    ("Ad Closed", "closed"),
    ("Not Yet Selected", "closed"),
    ("Cancelled", "cancelled"),
])
def test_every_portal_status_maps(portal, expected):
    assert STATUS[portal.lower()] == expected


def test_an_unknown_status_is_treated_as_closed(monkeypatch):
    """The safe direction: a false alarm on the board is worse than a miss."""
    a, _ = _adapter(monkeypatch, [_ad(status="Something New")])

    assert a.fetch() == []
    assert len(a.fetch_history()) == 1


def test_closed_and_awaiting_selection_are_history(monkeypatch):
    a, _ = _adapter(monkeypatch, [
        _ad(number="A", status="Current"),
        _ad(number="B", status="Ad Closed"),
        _ad(number="C", status="Not Yet Selected"),
    ])

    assert [o.external_id for o in a.fetch()] == ["A"]
    assert sorted(o.external_id for o in a.fetch_history()) == ["B", "C"]


def test_an_ad_with_only_a_number_still_arrives(monkeypatch):
    """A bare id is actionable when the deadline and work types are there."""
    a, _ = _adapter(monkeypatch, [_ad(description="")])
    (opp,) = a.fetch()

    assert opp.external_id == "27220"
    assert "27220" in opp.title


def test_a_row_with_neither_a_number_nor_a_title_is_skipped(monkeypatch):
    a, _ = _adapter(monkeypatch, [_ad(number="", description="")])
    assert a.fetch() == []


# -- the display HTML inside the JSON --------------------------------------


def test_escaped_markup_in_a_field_becomes_readable_text():
    """Work types arrive as ` 7.1-Signing &amp; Channelization &lt;br/&gt; `,
    escaped twice. Left alone, the `<br/>` glues two work types together."""
    from src.sources.fdot_ads import _text

    assert _text(" 7.1-Signing &amp; Channelization &lt;br/&gt; ") == "7.1-Signing & Channelization"
    assert _text(" 21307453201 &lt;br/&gt; 42880533201") == "21307453201 · 42880533201"
    assert _text(None) == ""


def test_the_amount_is_rendered_not_dumped():
    """`budget` is a display string and the API sends '2950000.0'."""
    from src.sources.fdot_ads import _amount

    assert _amount("2950000.0") == "$3.0M"
    assert _amount("225000000.0") == "$225.0M"
    assert _amount("45000") == "$45,000"
    assert _amount("0") is None
    assert _amount("") is None
    assert _amount("n/a") is None


# -- geography -------------------------------------------------------------


def test_a_districts_counties_are_searchable_even_though_county_is_not(monkeypatch):
    """District 4 is six counties and `county` holds one, so it stays
    statewide — but someone searching "broward" must still find the ad."""
    a, _ = _adapter(monkeypatch, [_ad(district="04")])
    (opp,) = a.fetch()

    assert opp.county == "statewide"
    assert "broward" in opp.keywords
    assert "palm-beach" in opp.keywords
    assert "miami-dade" not in opp.keywords, "that is District 6"


def test_the_two_districts_that_are_not_regions_are_named():
    assert district_label("08") == "FDOT Florida's Turnpike Enterprise"
    assert district_label("99") == "FDOT Central Office"
    assert district_label("04") == "FDOT District 4"
    assert district_label("") is None


def test_every_district_maps_to_real_county_slugs():
    """A typo here would put an ad in a county that does not exist, where no
    watchlist would ever look."""
    from src.fl_geo import COUNTY_SLUGS

    for district, counties in DISTRICT_COUNTIES.items():
        for county in counties:
            assert county in COUNTY_SLUGS, f"district {district}: {county}"


def test_the_seven_regional_districts_cover_florida_once():
    """Okeechobee genuinely sits in two districts; nothing else should."""
    from collections import Counter

    seen = Counter(
        c for d, counties in DISTRICT_COUNTIES.items() if d not in ("08", "99")
        for c in counties
    )
    assert [c for c, n in seen.items() if n > 1] == ["okeechobee"]
    assert len(seen) == 67, "every Florida county belongs to a district"


# -- failure ---------------------------------------------------------------


def test_an_api_that_does_not_answer_is_reported(monkeypatch):
    a, _ = _adapter(monkeypatch, [])

    def boom(url, **kw):
        raise RuntimeError("timeout")

    monkeypatch.setattr("src.sources.fdot_ads.get_json", boom)
    assert a.fetch() == []
    assert a.degraded_reason and "API" in a.degraded_reason


def test_an_unreadable_page_is_reported(monkeypatch):
    a = FdotAdsAdapter(CFG)

    def boom(url, **kw):
        raise RuntimeError("503")

    monkeypatch.setattr("src.sources.fdot_ads.get", boom)
    monkeypatch.setattr(FdotAdsAdapter, "_session", lambda self: None)
    assert a.fetch() == []
    assert a.degraded_reason and "page" in a.degraded_reason


def test_ads_that_all_fail_to_parse_are_reported_not_silent(monkeypatch):
    a, _ = _adapter(monkeypatch, [_ad(number="", description="") for _ in range(5)])
    a.fetch()

    assert a.degraded_reason and "none parsed" in a.degraded_reason


def test_an_empty_board_is_not_a_fault(monkeypatch):
    a, _ = _adapter(monkeypatch, [])
    assert a.fetch() == []
    assert a.degraded_reason is None
