"""Legistar award adapter: title parsing is the whole product."""

from src.sources.legistar import (
    LegistarAwardsAdapter, _first_amount, _ref_from, _vendor_from,
)

CFG = {
    "id": "legistar_broward",
    "name": "Broward County commission awards",
    "county": "broward",
    "agency": "Broward County",
    "portal_url": "https://broward.legistar.com/Legislation.aspx",
    "legistar_client": "broward",
}

BROWARD_TITLE = (
    "MOTION TO AWARD open-end contract to low bidder, Crown USA, Inc., for "
    "Runway Acrylic Traffic Paint, Bid No. OPN2131620B1, in the initial "
    "one-year estimated amount of $193,500; and authorize renewals for a "
    "ten-year estimated amount of $1,935,000."
)

FTL_TITLE = (
    "Resolution approving agreement for RFQ No. 449 Continuing Services with "
    "BCC Engineering, LLC - $2,165,000 (initial two (2)-year term estimated "
    "aggregate amount)"
)


def test_broward_style_title_parses_completely():
    assert _vendor_from(BROWARD_TITLE) == "Crown USA, Inc"
    assert _first_amount(BROWARD_TITLE) == 193_500  # the term, not the lifetime
    assert _ref_from(BROWARD_TITLE) == "OPN2131620B1"


def test_fort_lauderdale_style_title_parses():
    assert _vendor_from(FTL_TITLE) == "BCC Engineering, LLC"
    assert _first_amount(FTL_TITLE) == 2_165_000
    assert _ref_from(FTL_TITLE) == "449"


def test_fetch_maps_matters_to_award_records(monkeypatch):
    rows = [
        {
            "MatterId": 100, "MatterFile": "2026-123", "MatterTitle": BROWARD_TITLE,
            "MatterAgendaDate": "2026-08-20T00:00:00", "MatterPassedDate": None,
            "MatterTypeName": "Motion", "MatterStatusName": "Agenda Ready",
        },
        # Matched by substringof('ward') but not an award — must be dropped.
        {
            "MatterId": 101, "MatterFile": "2026-124",
            "MatterTitle": "Appointment to the Broward Planning Council",
            "MatterAgendaDate": "2026-08-20T00:00:00",
        },
    ]
    monkeypatch.setattr("src.sources.legistar.get_json", lambda url, params=None, **kw: rows)
    (opp,) = LegistarAwardsAdapter(CFG).fetch()

    assert opp.status == "award"
    assert opp.awarded_vendor == "Crown USA, Inc"
    assert opp.award_amount == 193_500
    assert opp.linked_ref == "OPN2131620B1"
    assert opp.award_linkage == "ref"
    assert opp.external_id == "2026-123"
    assert str(opp.award_date) == "2026-08-20"


def test_empty_agenda_reports_empty_not_error(monkeypatch):
    monkeypatch.setattr("src.sources.legistar.get_json", lambda url, params=None, **kw: [])
    adapter = LegistarAwardsAdapter(CFG)
    assert adapter.fetch() == []
    assert adapter.empty_note
