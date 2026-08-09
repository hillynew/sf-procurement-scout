"""Miami-Dade govaction awards: parsing a real results page, offline.

The fixture is a verbatim capture (2026-08-09) of the POST described in the
adapter docstring — mttitle=award, mtdtpass=12-16-2025 — four result rows,
one of which is an award with the amount and vendor in its short title.
"""

from __future__ import annotations

import pytest

from src.sources.miami_dade_govaction import (
    MiamiDadeGovactionAdapter,
    _result_rows,
    _vendor,
)

CFG = {
    "id": "miami_dade_govaction",
    "name": "Miami-Dade BCC awards (govaction)",
    "county": "miami-dade",
    "agency": "Miami-Dade County",
    "portal_url": "https://www.miamidade.gov/govaction/searchleg.asp",
}

FORM_RESERVED = """
<html><body><form method="POST" action="searchleg.asp" name="form1">
<td valign="top">Please enter the information you wish to search for or enter
a portion of it in field(s) like</td>
<input name="mttitle" value=""><input type="submit" name="btnSubmit" value="Search">
</form></body></html>
"""


@pytest.fixture
def adapter(monkeypatch, fixtures_dir):
    html = (fixtures_dir / "govaction_results.html").read_text()
    monkeypatch.setattr("src.sources.miami_dade_govaction._search", lambda title: html)
    # The fixture's rows are from late 2025; pin the window open so the test
    # does not start failing as today's date walks away from the capture.
    monkeypatch.setattr("src.sources.miami_dade_govaction.LOOKBACK_DAYS", 36500)
    return MiamiDadeGovactionAdapter(CFG)


def test_fixture_rows_are_all_found(fixtures_dir):
    html = (fixtures_dir / "govaction_results.html").read_text()
    rows = _result_rows(html)
    assert [r["file_number"] for r in rows] == ["252422", "252360", "252327", "251897"]
    assert all(r["matter"] == r["file_number"] for r in rows)


def test_award_row_carries_file_number_amount_and_vendor(adapter):
    opps = adapter.fetch()
    # Four rows come back; only one short title contains the word "award" —
    # the others matched mttitle=award in their *full* titles only.
    assert len(opps) == 1
    (o,) = opps

    assert o.status == "award"
    assert o.external_id == "252327"
    assert o.award_amount == 31_366_638
    assert o.awarded_vendor == "H&R Paving, Inc"
    assert o.url == "https://www.miamidade.gov/govaction/matter.asp?matter=252327"
    assert str(o.posted_date) == "2025-11-19"  # the row's Introduced date
    assert str(o.award_date) == "2025-11-19"
    assert o.raw["govaction"]["title"].startswith("AWARD OF $31,366,638.18")
    assert adapter.degraded_reason is None


def test_healthy_fetch_never_reports_amount_zero(adapter):
    assert all(o.award_amount != 0 for o in adapter.fetch())


def test_form_reserved_page_is_degraded_not_a_healthy_empty(monkeypatch):
    """Zero matches and a rejected POST both re-serve the form. For a query
    that matches five thousand matters of record, a rowless page means the
    search broke — it must surface as degraded, never as a clean empty."""
    monkeypatch.setattr(
        "src.sources.miami_dade_govaction._search", lambda title: FORM_RESERVED
    )
    adapter = MiamiDadeGovactionAdapter(CFG)

    assert adapter.fetch() == []
    assert adapter.degraded_reason
    assert adapter.empty_note is None


def test_rows_outside_the_lookback_window_are_an_empty_not_a_fault(
    monkeypatch, fixtures_dir
):
    html = (fixtures_dir / "govaction_results.html").read_text()
    monkeypatch.setattr("src.sources.miami_dade_govaction._search", lambda title: html)
    monkeypatch.setattr("src.sources.miami_dade_govaction.LOOKBACK_DAYS", 1)
    adapter = MiamiDadeGovactionAdapter(CFG)

    assert adapter.fetch() == []
    assert adapter.empty_note
    assert adapter.degraded_reason is None


@pytest.mark.parametrize(
    "title, expected",
    [
        # ALL-CAPS short titles, as the results table actually prints them.
        ("AWARD OF $31,366,638.18 TO H&R PAVING, INC", "H&R Paving, Inc"),
        ("CONTRACT AWARD TO HORIZON CONTRACTORS INC.", "Horizon Contractors Inc"),
        ("AWARD TO AECOM TECHNICAL SERVICES, INC.", "Aecom Technical Services, Inc"),
        ("BUILD AWARD TO KARMIL CONSTRUCTION INC", "Karmil Construction Inc"),
        # No vendor named — must stay None rather than grab prose.
        ("FY 2025 RFA AWARDS", None),
    ],
)
def test_all_caps_titles_reach_the_shared_vendor_parser(title, expected):
    assert _vendor(title) == expected
