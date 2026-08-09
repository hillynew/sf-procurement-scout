"""FDOT letting results: the district page walk and the bid-tab parse."""

from datetime import date

from src.sources.fdot_letting import FdotLettingAdapter

CFG = {
    "id": "fdot_lettings",
    "name": "FDOT letting results (bid tabs)",
    "county": "statewide",
    "agency": "Florida Department of Transportation",
    "portal_url": "https://bidletting.fdot.gov/LettingMain",
    "districts": ["04"],
}


def _fixture(name, fixtures_dir):
    return (fixtures_dir / name).read_text()


def test_report_parses_contracts_and_all_bidders(monkeypatch, fixtures_dir):
    pages = {
        "districtID=04": _fixture("fdot_letting_list.html", fixtures_dir),
        "DisplayPreliminaryReport": _fixture("fdot_prelim_report.html", fixtures_dir),
    }

    def fake_get(url, **kw):
        for key, html in pages.items():
            if key in url:
                return type("R", (), {"text": html})()
        raise AssertionError(url)

    monkeypatch.setattr("src.sources.fdot_letting.get", fake_get)
    # Freeze "today" so the fixture's 7/31/2026 letting counts as recent.
    monkeypatch.setattr(
        "src.sources.fdot_letting.date",
        type("D", (), {"today": staticmethod(lambda: date(2026, 8, 9))}),
    )

    opps = FdotLettingAdapter(CFG).fetch()
    assert opps, "the fixture report holds at least one contract"
    o = opps[0]
    assert o.status == "award"
    assert o.external_id == "E4Y08"
    assert o.county == "miami-dade"
    assert o.awarded_vendor == "PRINCE-RAILWORKS JV"
    assert o.award_amount == 91_363_180  # $91,363,180.50, to whole dollars
    assert o.linked_ref == "429487-2-52-01"
    assert o.award_linkage == "ref"
    # The most recent past letting in the fixture list (frozen today = 8/9).
    assert str(o.award_date) == "2026-08-07"
    assert "apparent low bid" in o.description
    # Every bidder's number is kept in raw.
    assert len(o.raw["letting"]["bidders"]) == 4


def test_unreadable_districts_degrade(monkeypatch):
    def boom(url, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr("src.sources.fdot_letting.get", boom)
    adapter = FdotLettingAdapter(CFG)
    assert adapter.fetch() == []
    assert adapter.degraded_reason
