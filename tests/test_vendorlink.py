"""VendorLink: grid parsing, ASP.NET paging, and the directory scoping trap."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.sources.vendorlink import (
    AGENCY_SELECT_ID,
    GRID_ID,
    PAGE_SIZE,
    VendorLinkAdapter,
    _grid_rows,
)

CFG = {
    "id": "vl_70",
    "name": "Brevard County (VendorLink)",
    "county": "brevard",
    "agency": "Brevard County Board of County Commissioners",
    "portal_url": "https://www.myvendorlink.com/external/bids?a=70",
    "vendorlink_agency": 70,
}

HEADERS = [
    "Agency", "Number", "Title", "Online Quote/Bid", "Status",
    "Broadcast Date", "Mandatory Pre-Bid", "Question End Date", "Due Date", "View",
]


def _row(number="B-1-26-01", title="Roof Repair", status="Active",
         broadcast="7/30/2026 12:00 PM", question="8/7/2026 5:00 PM",
         due="8/21/2026 10:00 AM", mandatory=False):
    checked = " checked" if mandatory else ""
    return (
        "<tr>"
        "<td>Brevard County Board of County Commissioners</td>"
        f"<td>{number}</td><td>{title}</td>"
        '<td><input type="checkbox"/></td>'
        f'<td><span class="badge">{status}</span></td>'
        f"<td>{broadcast}</td>"
        f'<td><input type="checkbox"{checked}/></td>'
        f"<td>{question}</td><td>{due}</td><td></td>"
        "</tr>"
    )


def _page(rows, *, viewstate="VS1", pager=True):
    head = "".join(f"<th>{h}</th>" for h in HEADERS)
    pager_row = '<tr><td colspan="10">1 2 3 &gt;&gt;</td></tr>' if pager else ""
    return f"""
    <html><body>
      <input type="hidden" name="__VIEWSTATE" value="{viewstate}"/>
      <input type="hidden" name="__VIEWSTATEGENERATOR" value="G1"/>
      <input type="hidden" name="__EVENTVALIDATION" value="EV1"/>
      <select id="{AGENCY_SELECT_ID}">
        <option value="">Select</option>
        <option value="70">Brevard County Board of County Commissioners</option>
        <option value="60">Citrus County Board of County Commissioners</option>
      </select>
      <select id="ctl00_RegionMiddle_ddlFiscalYear">
        <option value="2026">2026</option><option value="1998">1998</option>
      </select>
      <table id="{GRID_ID}"><tr>{head}</tr>{"".join(rows)}{pager_row}</table>
    </body></html>
    """


# -- parsing ---------------------------------------------------------------


def test_rows_are_read_by_header_name():
    (row,) = _grid_rows(BeautifulSoup(_page([_row()]), "lxml"))

    assert row["number"] == "B-1-26-01"
    assert row["title"] == "Roof Repair"
    assert row["status"] == "Active"
    assert row["due date"] == "8/21/2026 10:00 AM"
    assert row["question end date"] == "8/7/2026 5:00 PM"


def test_the_pager_row_is_not_read_as_a_solicitation():
    rows = _grid_rows(BeautifulSoup(_page([_row()]), "lxml"))
    assert len(rows) == 1


def test_a_checked_box_becomes_a_flag_not_its_label():
    rows = _grid_rows(BeautifulSoup(_page([_row(mandatory=True)]), "lxml"))
    assert rows[0]["mandatory pre-bid"] == "yes"

    rows = _grid_rows(BeautifulSoup(_page([_row(mandatory=False)]), "lxml"))
    assert rows[0]["mandatory pre-bid"] == ""


def test_a_missing_grid_is_empty_not_an_error():
    assert _grid_rows(BeautifulSoup("<html><body>no grid</body></html>", "lxml")) == []


# -- mapping ---------------------------------------------------------------


def _adapter(monkeypatch, pages):
    """Serve `pages` in order: page one from GET, the rest from postbacks."""
    a = VendorLinkAdapter(CFG)
    served = {"n": 0}

    def page_one(self):
        served["n"] = 1
        return BeautifulSoup(pages[0], "lxml")

    def next_page(self, soup, page):
        if page - 1 >= len(pages):
            return None
        served["n"] = page
        return BeautifulSoup(pages[page - 1], "lxml")

    monkeypatch.setattr(VendorLinkAdapter, "_page_one", page_one)
    monkeypatch.setattr(VendorLinkAdapter, "_next_page", next_page)
    return a


def test_an_active_row_becomes_an_open_opportunity(monkeypatch):
    a = _adapter(monkeypatch, [_page([_row()], pager=False)])
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.external_id == "B-1-26-01"
    assert opp.due_date is not None and opp.due_date.day == 21
    assert opp.questions_due is not None
    assert opp.posted_date is not None


def test_a_mandatory_pre_bid_is_recorded(monkeypatch):
    a = _adapter(monkeypatch, [_page([_row(mandatory=True)], pager=False)])
    (opp,) = a.fetch()
    assert opp.pre_bid_meeting == "Mandatory pre-bid meeting"


@pytest.mark.parametrize("badge,expected", [
    ("Active", "open"),
    ("Awarded", "closed"),
    ("Under Evaluation", "closed"),
    ("Closed / Completed", "closed"),
    ("Canceled", "cancelled"),
    ("All bids rejected", "closed"),
])
def test_every_portal_status_maps(monkeypatch, badge, expected):
    a = _adapter(monkeypatch, [_page([_row(status=badge)], pager=False)])
    opps = a.fetch() if expected == "open" else a.fetch_history()

    assert opps and opps[0].status == expected


def test_an_unknown_badge_is_treated_as_closed(monkeypatch):
    """The safe direction: a false alarm on the board is worse than a miss."""
    a = _adapter(monkeypatch, [_page([_row(status="Something New")], pager=False)])

    assert a.fetch() == []
    assert len(a.fetch_history()) == 1


def test_detail_is_not_claimed():
    """BidDetail.aspx redirects to a login, and we do not hold accounts."""
    assert VendorLinkAdapter.supports_detail is False


def test_a_missing_agency_id_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "vendorlink_agency"}
    with pytest.raises(ValueError, match="vendorlink_agency"):
        VendorLinkAdapter(cfg).fetch()


# -- paging ----------------------------------------------------------------


def test_a_full_page_of_open_rows_pages_on(monkeypatch):
    """22 rows is the page size, not a small agency."""
    full = [_row(number=f"B-{i}", title=f"Job {i}") for i in range(PAGE_SIZE)]
    second = [_row(number="B-99", title="Job 99")]
    a = _adapter(monkeypatch, [_page(full), _page(second, pager=False)])

    assert len(a.fetch()) == PAGE_SIZE + 1


def test_paging_stops_once_a_page_holds_nothing_open(monkeypatch):
    """The grid is newest-first, so no open rows here means none further back."""
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    closed = [_row(number=f"C-{i}", status="Awarded") for i in range(PAGE_SIZE)]
    never = [_row(number="LATER")]
    a = _adapter(monkeypatch, [_page(full), _page(closed), _page(never)])

    opps = a.fetch()
    assert len(opps) == PAGE_SIZE
    assert not any(o.external_id == "LATER" for o in opps)


def test_history_keeps_walking_past_a_closed_page(monkeypatch):
    full = [_row(number=f"B-{i}", status="Awarded") for i in range(PAGE_SIZE)]
    more = [_row(number="OLD", status="Awarded")]
    a = _adapter(monkeypatch, [_page(full), _page(more, pager=False)])

    assert any(o.external_id == "OLD" for o in a.fetch_history())


def test_a_short_page_ends_the_walk(monkeypatch):
    a = _adapter(monkeypatch, [_page([_row()], pager=False), _page([_row(number="NOPE")])])
    opps = a.fetch()

    assert len(opps) == 1
    assert not any(o.external_id == "NOPE" for o in opps)


def test_a_grid_that_never_appears_is_reported(monkeypatch):
    a = _adapter(monkeypatch, ["<html><body>maintenance</body></html>"])
    assert a.fetch() == []
    assert a.degraded_reason and "grid" in a.degraded_reason


# -- the directory ---------------------------------------------------------


def test_the_directory_reads_only_the_agency_dropdown(monkeypatch):
    """Fiscal-year options are numeric too — reading every select yields "1998"."""
    a = _adapter(monkeypatch, [_page([_row()], pager=False)])
    directory = a.agencies()

    assert directory == {
        "70": "Brevard County Board of County Commissioners",
        "60": "Citrus County Board of County Commissioners",
    }
    assert "1998" not in directory
    assert "2026" not in directory


def test_a_page_without_the_dropdown_yields_no_directory(monkeypatch):
    a = _adapter(monkeypatch, ["<html><body>no select</body></html>"])
    assert a.agencies() == {}
