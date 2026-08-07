"""Ionwave: the four public lists, the request budget, and the challenge."""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from src.http_util import SourceBlocked, is_challenge
from src.sources.ionwave import (
    HISTORY_TYPES,
    PAGE_SIZE,
    REQUEST_BUDGET,
    SOURCE_TYPES,
    IonwaveAdapter,
    grid_rows,
)

CFG = {
    "id": "iw_lee_county",
    "name": "Lee County (Ionwave)",
    "county": "lee",
    "agency": "Lee County Board of County Commissioners",
    "portal_url": "https://leegov.ionwave.net/SourcingEvents.aspx?SourceType=1",
    "ionwave_host": "leegov.ionwave.net",
}

#: The two column sets the platform actually serves. Current and Closed end on
#: a close date/time; Awarded and Non Awarded drop that and end on a decision
#: date instead — one column fewer, which is the whole reason for header-name
#: reading.
OPEN_HEADERS = ["", "Bid Number", "Bid Title", "Bid Type", "Organization",
                "Bid Issue Date", "Bid Close Date/Time"]
AWARD_HEADERS = ["", "Bid Number", "Bid Title", "Bid Type", "Organization",
                 "Bid Award Date"]

CHALLENGE = (
    '<!DOCTYPE html><html><head><title>Just a moment...</title>'
    '<meta http-equiv="content-security-policy" '
    'content="script-src https://challenges.cloudflare.com"></head><body></body></html>'
)


def _row(number="IFB-2026-14", title="Roof Repair", btype="IFB",
         issue="7/12/2026", close="8/21/2026 10:00:00 AM (ET)", alt=False):
    return (
        f'<tr class="{"rgAltRow" if alt else "rgRow"}">'
        '<td><span class="flaticon-grid_View" title="View Bid"></span></td>'
        f"<td>{number}</td><td>{title}</td><td>{btype}</td>"
        '<td style="display:none;">Procurement Division</td>'
        f"<td>{issue}</td><td>{close}</td></tr>"
    )


def _award_row(number="RFQ-04-14", title="Social Media Archiving",
               awarded="7/28/2026 01:00:00 AM (ET)"):
    return (
        '<tr class="rgRow">'
        '<td><span class="flaticon-grid_View"></span></td>'
        f"<td>{number}</td><td>{title}</td><td>RFQ</td>"
        '<td style="display:none;">Procurement Division</td>'
        f"<td>{awarded}</td></tr>"
    )


def _page(rows, *, headers=OPEN_HEADERS, items=None, pages=1, viewstate="VS1"):
    head = "".join(f"<th>{h}</th>" for h in headers)
    numbers = "".join(
        f"<a href=\"javascript:__doPostBack('pager$ctl{3 + 2 * n:02d}','')\"><span>{n}</span></a>"
        for n in range(1, pages + 1)
    )
    return f"""
    <html><body>
      <input type="hidden" name="__VIEWSTATE" value="{viewstate}"/>
      <input type="hidden" name="__VIEWSTATEGENERATOR" value="G1"/>
      <table id="ctl00_mainContent_rgBidList_ctl00">
        <tr>{head}</tr>
        <tr class="rgFilterRow"><td></td></tr>
        {"".join(rows)}
        <tr class="rgPager"><td>
          <div class="rgNumPart">{numbers}</div>
          <div class="rgInfoPart">{items if items is not None else len(rows)} items in {pages} pages</div>
        </td></tr>
      </table>
    </body></html>
    """


# -- parsing ---------------------------------------------------------------


def test_rows_are_read_by_header_name():
    (row,) = grid_rows(BeautifulSoup(_page([_row()]), "lxml"))

    assert row["bid number"] == "IFB-2026-14"
    assert row["bid title"] == "Roof Repair"
    assert row["bid close date/time"] == "8/21/2026 10:00:00 AM (ET)"
    assert row["bid issue date"] == "7/12/2026"


def test_the_awarded_column_set_does_not_shift_the_date():
    """Awarded drops a column, so position 5 is an award date, not an issue date."""
    (row,) = grid_rows(BeautifulSoup(_page([_award_row()], headers=AWARD_HEADERS), "lxml"))

    assert row["bid award date"] == "7/28/2026 01:00:00 AM (ET)"
    assert "bid issue date" not in row


def test_the_filter_row_and_pager_are_not_solicitations():
    rows = grid_rows(BeautifulSoup(_page([_row(), _row(number="B-2", alt=True)]), "lxml"))
    assert len(rows) == 2


def test_a_missing_grid_is_empty_not_an_error():
    assert grid_rows(BeautifulSoup("<html><body>maintenance</body></html>", "lxml")) == []


def test_the_zone_label_does_not_swallow_the_date():
    """Every close date on every list arrives as "... 10:00:00 AM (ET)".

    Left on, the suffix defeats the parser and the whole platform reports
    dateless bids — which looks like a portal that publishes no deadlines
    rather than a four-character parsing bug.
    """
    from src.sources.ionwave import _when

    assert _when("8/21/2026 10:00:00 AM (ET)").hour == 10
    assert _when("7/12/2026").day == 12
    assert _when("3/1/2026 9:00:00 AM (EDT)") is not None


def test_a_zone_we_do_not_assume_is_left_unparsed():
    """Better a bid with no date than one three hours wrong."""
    from src.sources.ionwave import _when

    assert _when("8/21/2026 10:00:00 AM (PT)") is None
    assert _when(None) is None


# -- the lists -------------------------------------------------------------


def _adapter(monkeypatch, pages, *, posts=None):
    """Serve `pages` for GETs (keyed by source type) and `posts` for postbacks."""
    a = IonwaveAdapter(CFG)
    seen = {"gets": [], "posts": 0}

    def fake_get(url, **kwargs):
        source_type = int(url.rsplit("=", 1)[1])
        seen["gets"].append(source_type)
        body = pages.get(source_type)
        if body is None:
            raise SourceBlocked("bot challenge served instead of the page")
        return type("R", (), {"text": body, "status_code": 200})()

    class FakeSession:
        def post(self, url, data=None, timeout=None):
            body = (posts or [])[seen["posts"]] if seen["posts"] < len(posts or []) else CHALLENGE
            seen["posts"] += 1
            # Cloudflare serves the interstitial with 429, and `is_challenge`
            # keys on the pair — a challenge body under a 200 is a real page.
            return type("R", (), {"text": body,
                                  "status_code": 429 if body is CHALLENGE else 200})()

    monkeypatch.setattr("src.sources.ionwave.get", fake_get)
    monkeypatch.setattr("src.sources.ionwave.check", lambda url: None)
    monkeypatch.setattr(IonwaveAdapter, "_session", lambda self: FakeSession())
    return a, seen


def test_a_current_row_becomes_an_open_opportunity(monkeypatch):
    a, _ = _adapter(monkeypatch, {1: _page([_row()])})
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.external_id == "IFB-2026-14"
    assert opp.due_date is not None and opp.due_date.day == 21
    assert opp.posted_date is not None and opp.posted_date.month == 7
    assert opp.url.endswith("SourceType=1")


def test_fetch_costs_exactly_one_request(monkeypatch):
    """The whole reason the routine crawl never meets the challenge."""
    a, seen = _adapter(monkeypatch, {1: _page([_row()])})
    a.fetch()

    assert seen["gets"] == [1]
    assert seen["posts"] == 0
    assert a.degraded_reason is None


def test_an_awarded_row_carries_the_protest_clock(monkeypatch):
    a, _ = _adapter(monkeypatch, {3: _page([_award_row()], headers=AWARD_HEADERS)})
    (opp,) = a._collect(3)

    assert opp.status == "award"
    assert opp.protest_deadline is not None
    # 72 business hours from a 28 July award, so a few days out, never the day of.
    assert opp.protest_deadline.date() > opp.posted_date


def test_only_awards_get_a_protest_deadline(monkeypatch):
    """A closed bid has no decision to protest, and no clock to put on the board."""
    a, _ = _adapter(monkeypatch, {2: _page([_row()])})
    (opp,) = a._collect(2)

    assert opp.status == "closed"
    assert opp.protest_deadline is None


def test_a_non_awarded_bid_is_cancelled_not_closed(monkeypatch):
    """Nothing was bought, so the requirement is probably coming back."""
    page = _page([_award_row()], headers=["", "Bid Number", "Bid Title", "Bid Type",
                                          "Organization", "Bid Non Award Date"])
    a, _ = _adapter(monkeypatch, {4: page})
    (opp,) = a._collect(4)

    assert opp.status == "cancelled"
    assert opp.posted_date is not None, "the decision date is the only date these rows have"


def test_the_four_lists_are_the_documented_ones():
    assert [SOURCE_TYPES[n][0] for n in (1, 2, 3, 4)] == [
        "Current Bids", "Closed Bids", "Awarded Bids", "Non Awarded Bids"
    ]


def test_detail_is_not_claimed():
    """The View Bid cell is a <span> with no href; the row click needs a login."""
    assert IonwaveAdapter.supports_detail is False


def test_a_missing_host_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "ionwave_host"}
    with pytest.raises(ValueError, match="ionwave_host"):
        IonwaveAdapter(cfg).fetch()


# -- paging ----------------------------------------------------------------


def test_one_page_is_not_paged(monkeypatch):
    """The pager says "2 items in 1 pages", so there is nothing to post back for."""
    a, seen = _adapter(monkeypatch, {1: _page([_row(), _row(number="B-2")], pages=1)})
    a.fetch()

    assert seen["posts"] == 0


def test_a_second_page_is_fetched_when_the_pager_says_so(monkeypatch):
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    second = _page([_row(number="LATER")], items=21, pages=2)
    a, seen = _adapter(monkeypatch, {2: _page(full, items=21, pages=2)}, posts=[second])
    opps = a._collect(2)

    assert seen["posts"] == 1
    assert any(o.external_id == "LATER" for o in opps)


def test_a_page_target_is_read_off_the_pager_not_computed(monkeypatch):
    """RadGrid renumbers its pager controls as the visible window slides."""
    from src.sources.ionwave import _page_target

    soup = BeautifulSoup(_page([_row()], pages=4), "lxml")
    assert _page_target(soup, 2) == "pager$ctl07"
    assert _page_target(soup, 3) == "pager$ctl09"
    assert _page_target(soup, 9) is None


def test_the_pager_total_is_read_rather_than_inferred():
    from src.sources.ionwave import _total_pages

    soup = BeautifulSoup(_page([_row()], items=68, pages=4), "lxml")
    assert _total_pages(soup) == 4
    assert _total_pages(BeautifulSoup("<html></html>", "lxml")) is None


# -- the budget and the challenge ------------------------------------------


def test_the_walk_stops_at_the_request_budget(monkeypatch):
    """Never more requests than Cloudflare serves one session."""
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    page = _page(full, items=400, pages=20)
    a, seen = _adapter(monkeypatch, {2: page}, posts=[page] * 20)
    a._collect(2)

    assert seen["gets"].count(2) + seen["posts"] == REQUEST_BUDGET


def test_a_truncated_walk_says_how_far_it_got(monkeypatch):
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    page = _page(full, items=400, pages=20)
    a, _ = _adapter(monkeypatch, {2: page}, posts=[page] * 20)
    a._collect(2)

    assert a.degraded_reason and "of 20 pages" in a.degraded_reason


def test_the_challenge_is_reported_not_retried(monkeypatch):
    """`http_util` raises SourceBlocked for it, so there is nothing to retry into."""
    a, seen = _adapter(monkeypatch, {})
    assert a.fetch() == []
    assert seen["gets"] == [1], "a challenge is a refusal, not backpressure"
    assert a.degraded_reason and "Cloudflare" in a.degraded_reason


def test_a_challenge_stops_the_walk_rather_than_probing_on(monkeypatch):
    """The challenge is soft — a later request is often served anyway.

    Taking that one is working around a refusal by waiting for a gap in it,
    which is the same move as rotating the session and wrong for the same
    reason. Observed live: after the challenge landed on the awarded pager,
    the closed list still answered.
    """
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    pages = {3: _page(full, items=400, pages=20), 2: _page([_row()]), 4: _page([_row()])}
    a, seen = _adapter(monkeypatch, pages, posts=[CHALLENGE])
    a.fetch_history()

    assert seen["gets"] == [3], "the closed and non-awarded lists were not tried"
    assert a.degraded_reason and "Cloudflare" in a.degraded_reason


def test_history_spends_the_budget_on_awards_first(monkeypatch):
    """Awarded is the list that feeds the protest clock and the records trigger."""
    assert HISTORY_TYPES[0] == 3

    pages = {n: _page([_award_row(number=f"A-{n}")], headers=AWARD_HEADERS)
             for n in HISTORY_TYPES}
    a, seen = _adapter(monkeypatch, pages)
    a.fetch_history()

    assert seen["gets"][0] == 3


def test_history_names_the_lists_it_never_reached(monkeypatch):
    """A partial archive presented as the whole one is the failure worth avoiding."""
    full = [_row(number=f"B-{i}") for i in range(PAGE_SIZE)]
    big = _page(full, items=400, pages=20, headers=OPEN_HEADERS)
    a, _ = _adapter(monkeypatch, {3: big, 2: big, 4: big}, posts=[big] * 20)
    a.fetch_history()

    assert a.degraded_reason
    assert "Closed Bids" in a.degraded_reason and "Non Awarded Bids" in a.degraded_reason


# -- the shared challenge rule ---------------------------------------------


def test_a_challenge_body_is_a_refusal_whatever_its_status():
    for status in (403, 429, 503):
        resp = type("R", (), {"status_code": status, "text": CHALLENGE})()
        assert is_challenge(resp), f"{status} carrying the interstitial"


def test_an_honest_429_is_still_backpressure():
    """Portals that mean 'slow down' say it without an interstitial, and retry."""
    resp = type("R", (), {"status_code": 429, "text": "Rate limit exceeded"})()
    assert not is_challenge(resp)


def test_a_normal_page_is_never_a_challenge():
    resp = type("R", (), {"status_code": 200, "text": CHALLENGE})()
    assert not is_challenge(resp), "status 200 is the page, whatever it contains"


def test_the_robots_override_is_declared_with_its_reason():
    """Ionwave serves Disallow: / on every tenant, as Bonfire does."""
    from src.netpolicy import ROBOTS_OVERRIDES, robots_allows

    assert "*.ionwave.net" in ROBOTS_OVERRIDES
    assert ROBOTS_OVERRIDES["*.ionwave.net"].strip()

    allowed, why = robots_allows("https://leegov.ionwave.net/SourcingEvents.aspx?SourceType=1")
    assert allowed and why.startswith("override:")


def test_strict_robots_drops_the_override(monkeypatch):
    from src import netpolicy

    monkeypatch.setenv("SF_SCOUT_STRICT_ROBOTS", "1")
    assert netpolicy._override_reason("leegov.ionwave.net") is None
