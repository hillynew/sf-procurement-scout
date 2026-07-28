"""CivicPlus Bids module — the shared adapter behind most city boards."""

from __future__ import annotations

from datetime import datetime

import pytest

from src.sources.civicplus import CivicPlusAdapter

CFG = {
    "id": "north_miami",
    "name": "City of North Miami",
    "county": "miami-dade",
    "agency": "City of North Miami",
    "portal_url": "https://www.northmiamifl.gov/bids.aspx",
}


def _adapter(monkeypatch, html: str, **cfg_overrides):
    class _Resp:
        text = html

    monkeypatch.setattr("src.sources.civicplus.get", lambda *a, **k: _Resp())
    return CivicPlusAdapter({**CFG, **cfg_overrides})


def _row(
    title="Stormwater Drainage Improvement Project",
    href="bids.aspx?bidID=110",
    ref="IFB No. 22-25-26",
    status="Open",
    closes="Upon Contract",
    scope="SCOPE OF WORK The City is soliciting bids from licensed contractors... [",
):
    return f"""
    <div class="listItemsRow bid">
      <div class="bidTitle">
        <span><a href="{href}">{title}</a></span>
        <span><strong>Bid No.</strong> {ref}</span>
        <span>{scope}<a href="{href}">Read on<span class="visuallyHidden">: {title}</span></a>]</span>
      </div>
      <div class="bidStatus">
        <div><span>Status:</span><span>Closes:</span></div>
        <div><span>{status}</span><span>{closes}</span></div>
      </div>
    </div>
    """


def _page(*rows):
    return '<html><body><div class="listItems">' + "".join(rows) + "</div></body></html>"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_a_board(monkeypatch, fixtures_dir):
    html = (fixtures_dir / "civicplus_bids.html").read_text()
    opps = _adapter(monkeypatch, html).fetch()

    assert len(opps) == 4
    assert all(o.external_id for o in opps)
    assert all(o.agency == "City of North Miami" for o in opps)
    assert all(o.url.startswith("https://www.northmiamifl.gov/bids.aspx?bidID=") for o in opps)


def test_relative_links_become_absolute(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_row())).fetch()
    assert o.url == "https://www.northmiamifl.gov/bids.aspx?bidID=110"


def test_bid_number_is_extracted(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_row(ref="RFP No. 45-24-25"))).fetch()
    assert o.external_id == "RFP No. 45-24-25"


def test_read_on_affordance_is_stripped_from_description(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_row())).fetch()
    assert "Read on" not in (o.description or "")
    assert (o.description or "").startswith("SCOPE OF WORK")


def test_the_read_on_link_does_not_become_a_second_record(monkeypatch):
    """Each row carries two links to the same bid; only one opportunity."""
    assert len(_adapter(monkeypatch, _page(_row())).fetch()) == 1


def test_duplicate_rows_collapse(monkeypatch):
    page = _page(_row(href="bids.aspx?bidID=7"), _row(href="bids.aspx?bidID=7"))
    assert len(_adapter(monkeypatch, page).fetch()) == 1


# ---------------------------------------------------------------------------
# Status and dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Open", "open"),
        ("Closed", "closed"),
        ("Cancelled", "cancelled"),
        ("Canceled", "cancelled"),
        ("Awarded", "closed"),
        ("Intent to Award", "closed"),
        ("Archived", "closed"),
    ],
)
def test_status_column_is_mapped(monkeypatch, raw, expected):
    (o,) = _adapter(monkeypatch, _page(_row(status=raw))).fetch()
    assert o.status == expected


def test_real_closing_date_is_parsed(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_row(closes="August 19, 2026 2:00 PM"))).fetch()
    assert o.due_date == datetime(2026, 8, 19, 14, 0)


@pytest.mark.parametrize("closes", ["Upon Contract", "See Documents", "N/A", "TBD", ""])
def test_non_dates_do_not_become_due_dates(monkeypatch, closes):
    """CivicPlus puts prose in the Closes column; none of it is a deadline."""
    (o,) = _adapter(monkeypatch, _page(_row(closes=closes))).fetch()
    assert o.due_date is None


def test_missing_status_block_defaults_to_open(monkeypatch):
    row = """
    <div class="listItemsRow bid">
      <div class="bidTitle"><span><a href="bids.aspx?bidID=3">Fence Repair Project</a></span></div>
    </div>
    """
    (o,) = _adapter(monkeypatch, _page(row)).fetch()
    assert o.status == "open" and o.due_date is None


# ---------------------------------------------------------------------------
# Empty boards and config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "There are no open bid postings at this time.",
        "No bid postings are currently available.",
        "There are no bids at this time.",
    ],
)
def test_empty_board_returns_nothing(monkeypatch, phrase):
    """An empty board is a real answer, not a placeholder opportunity."""
    assert _adapter(monkeypatch, f"<html><body><p>{phrase}</p></body></html>").fetch() == []


def test_rows_win_over_an_empty_phrase(monkeypatch):
    """A board can carry both live rows and boilerplate about empty categories."""
    page = _page(_row()) + "<p>There are no bids at this time in other categories.</p>"
    assert len(_adapter(monkeypatch, page).fetch()) == 1


def test_default_categories_are_applied(monkeypatch):
    """Lets a single-purpose board (e.g. the waste authority) tag its rows."""
    adapter = _adapter(monkeypatch, _page(_row()), default_categories=["waste_recycling"])
    (o,) = adapter.fetch()
    assert o.categories[0] == "waste_recycling"


def test_default_categories_do_not_duplicate_detected_ones(monkeypatch):
    adapter = _adapter(
        monkeypatch,
        _page(_row(title="Stormwater Drainage Construction")),
        default_categories=["construction"],
    )
    (o,) = adapter.fetch()
    assert o.categories.count("construction") == 1


def test_alternate_skin_without_listitemsrow(monkeypatch):
    """Some cities render bidTitle blocks without the wrapper class."""
    html = (
        '<html><body><div><div class="bidTitle">'
        '<span><a href="bids.aspx?bidID=9">Roof Replacement at City Hall</a></span>'
        "</div></div></body></html>"
    )
    (o,) = _adapter(monkeypatch, html).fetch()
    assert o.title == "Roof Replacement at City Hall"


def test_titles_too_short_are_skipped(monkeypatch):
    (rows) = _page(_row(title="Bid"))
    assert _adapter(monkeypatch, rows).fetch() == []
