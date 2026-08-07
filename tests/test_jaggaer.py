"""Jaggaer: rows with no columns, four tabs, and a tenant that left."""

from __future__ import annotations

import pytest

from src.sources.jaggaer import (
    ARCHIVE_TABS,
    LIVE_TABS,
    PAGE_SIZE,
    TABS,
    JaggaerAdapter,
    event_rows,
    is_empty_tab,
)

CFG = {
    "id": "jaggaer_fsu",
    "name": "Florida State University (Jaggaer)",
    "county": "leon",
    "agency": "Florida State University",
    "portal_url": "https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=FSU",
    "jaggaer_org": "FSU",
}


def _pair(label, value):
    return (
        '<div class="phx table-row-layout">'
        f'<div class="phx table-cell-layout"><div class="phx data-row-name">{label}</div></div>'
        f'<div class="phx table-cell-layout"><div class="phx data-row-content">{value}</div></div>'
        "</div>"
    )


def _row(title="Landscape Maintenance", number="ITN-6823-8", kind="ITN",
         opened="8/3/2026, 12:00 AM EDT", closes="9/14/2026, 3:00 PM EDT",
         contact="Angelena K. Turvaville aklang@fsu.edu", status="Open",
         description="Respondent to provide comprehensive landscape maintenance."):
    # The whole row really is one <td> holding a nested block. Reproduced,
    # because "read the third column" is exactly what does not work here.
    return (
        "<tr>"
        f'<td><span class="mosaic status-badge status-badge-blue">{status}</span></td>'
        "<td>"
        f'<a class="btn btn-link btn-link-header" href="https://app01.jaggaer.com/apps/Router/'
        f'ViewSourcingEvent?AuthToken=1%3AAES2%23xyz">{title}</a>'
        f'<div class="phx display-block phxText label-mini">{description}</div>'
        '<div class="phx table-layout">'
        + _pair("Open", opened) + _pair("Close", closes)
        + _pair("Type", kind) + _pair("Number", number)
        + _pair("Contact", contact)
        + "</div></td></tr>"
    )


def _page(rows):
    return (
        '<html><body><table class="table phx table-hover no-column-borders">'
        "<tr><th>Status</th><th>Details</th></tr>"
        f"{''.join(rows)}</table></body></html>"
    )


EMPTY_PAGE = (
    '<html><body><table class="table phx table-hover"><tr><th>Status</th></tr></table>'
    "<div>No Events have upcoming close dates.</div></body></html>"
)


# -- parsing ---------------------------------------------------------------


def test_fields_come_from_the_portals_own_labels_not_column_position():
    """There is no column position to read: the whole row is one <td>."""
    (row,) = event_rows(_page([_row()]))

    assert row["title"] == "Landscape Maintenance"
    assert row["number"] == "ITN-6823-8"
    assert row["type"] == "ITN"
    assert row["close"] == "9/14/2026, 3:00 PM EDT"
    assert row["open"] == "8/3/2026, 12:00 AM EDT"
    assert row["contact"].endswith("aklang@fsu.edu")
    assert "landscape maintenance" in row["description"].lower()


def test_the_header_row_is_not_an_event():
    assert len(event_rows(_page([_row()]))) == 1


def test_a_row_with_no_title_link_is_not_an_event():
    """The title link is what makes a row a solicitation rather than chrome."""
    assert event_rows('<table class="table-hover"><tr><td>chrome</td></tr></table>') == []


def test_a_missing_grid_is_empty_not_an_error():
    assert event_rows("<html><body>maintenance</body></html>") == []
    assert event_rows("") == []


def test_the_portal_saying_a_tab_is_empty_is_told_apart_from_a_broken_parse():
    """One is an agency between solicitations; the other is markup that moved."""
    assert is_empty_tab(EMPTY_PAGE)
    assert not is_empty_tab(_page([_row()]))


# -- the tabs --------------------------------------------------------------


def _adapter(monkeypatch, pages):
    """Serve one body per tab."""
    a = JaggaerAdapter(CFG)
    seen = []

    def fake_get(url, **kwargs):
        tab = url.rsplit("tab=", 1)[1]
        seen.append(tab)
        body = pages.get(tab)
        if body is None:
            raise RuntimeError("500")
        return type("R", (), {"text": body, "status_code": 200})()

    monkeypatch.setattr("src.sources.jaggaer.get", fake_get)
    monkeypatch.setattr(JaggaerAdapter, "_session", lambda self: None)
    return a, seen


def test_an_open_row_becomes_an_open_opportunity(monkeypatch):
    a, _ = _adapter(monkeypatch, {LIVE_TABS[0]: _page([_row()]), LIVE_TABS[1]: EMPTY_PAGE})
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.external_id == "ITN-6823-8"
    assert opp.due_date is not None and opp.due_date.month == 9
    assert opp.posted_date is not None
    assert opp.contact and "fsu.edu" in opp.contact
    assert opp.description


def test_the_upcoming_tab_is_upcoming_not_open(monkeypatch):
    a, _ = _adapter(monkeypatch, {LIVE_TABS[0]: EMPTY_PAGE, LIVE_TABS[1]: _page([_row()])})
    (opp,) = a.fetch()

    assert opp.status == "upcoming"


def test_fetch_reads_only_the_two_live_tabs(monkeypatch):
    a, seen = _adapter(monkeypatch, {t: EMPTY_PAGE for t in TABS})
    a.fetch()

    assert seen == list(LIVE_TABS)


def test_history_reads_only_the_two_archive_tabs(monkeypatch):
    a, seen = _adapter(monkeypatch, {t: EMPTY_PAGE for t in TABS})
    a.fetch_history()

    assert seen == list(ARCHIVE_TABS)


def test_an_awarded_row_keeps_the_award_status(monkeypatch):
    a, _ = _adapter(monkeypatch, {ARCHIVE_TABS[0]: EMPTY_PAGE,
                                  ARCHIVE_TABS[1]: _page([_row(status="Awarded")])})
    (opp,) = a.fetch_history()

    assert opp.status == "award"


def test_a_full_archive_page_says_it_is_only_a_page(monkeypatch):
    """Twenty rows with no pager is a page, not a total. Reporting it as the
    whole archive would understate an agency's history forever."""
    full = _page([_row(number=f"ITN-{i}", title=f"Job {i}") for i in range(PAGE_SIZE)])
    a, _ = _adapter(monkeypatch, {ARCHIVE_TABS[0]: full, ARCHIVE_TABS[1]: EMPTY_PAGE})
    a.fetch_history()

    assert a.degraded_reason and "not the whole archive" in a.degraded_reason


def test_a_short_archive_page_is_not_flagged(monkeypatch):
    a, _ = _adapter(monkeypatch, {ARCHIVE_TABS[0]: _page([_row()]), ARCHIVE_TABS[1]: EMPTY_PAGE})
    a.fetch_history()

    assert a.degraded_reason is None


# -- failure ---------------------------------------------------------------


def test_an_empty_tab_is_not_a_fault(monkeypatch):
    """FAU has nothing open today and is still a live tenant."""
    a, _ = _adapter(monkeypatch, {t: EMPTY_PAGE for t in LIVE_TABS})

    assert a.fetch() == []
    assert a.degraded_reason is None


def test_a_tab_that_renders_nothing_recognisable_is_reported(monkeypatch):
    """No rows *and* no "No Events" message means the markup moved."""
    a, _ = _adapter(monkeypatch, {LIVE_TABS[0]: "<html><body>?</body></html>",
                                  LIVE_TABS[1]: EMPTY_PAGE})
    a.fetch()

    assert a.degraded_reason and "no readable rows" in a.degraded_reason


def test_every_tab_failing_is_reported(monkeypatch):
    a, _ = _adapter(monkeypatch, {})

    assert a.fetch() == []
    assert a.degraded_reason and "no tab" in a.degraded_reason


def test_one_tab_failing_does_not_lose_the_other(monkeypatch):
    a, _ = _adapter(monkeypatch, {LIVE_TABS[0]: _page([_row()])})
    assert len(a.fetch()) == 1


def test_a_missing_tenant_code_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "jaggaer_org"}
    with pytest.raises(ValueError, match="jaggaer_org"):
        JaggaerAdapter(cfg).fetch()


def test_detail_is_not_claimed():
    """The row's link carries a per-render AuthToken — a fetch-now URL, not an
    address, so there is nothing stable to enrich from."""
    assert JaggaerAdapter.supports_detail is False


# -- the shipped tenants ---------------------------------------------------


def test_unf_is_not_configured():
    """It announced its move — "Beginning July 1, 2026, all University of North
    Florida solicitations will be posted through the University's new Bid
    Portal" — and both live tabs return no events. A source that can only ever
    return zero reads as a quiet agency rather than a departed one.
    """
    from src.sources.registry import load_source_config

    orgs = {c.get("jaggaer_org") for c in load_source_config()
            if isinstance(c, dict) and c.get("adapter") == "jaggaer"}

    assert orgs == {"FSU", "FAU", "FIU", "Florida", "USFlorida"}
    assert "UNF" not in orgs


def test_usf_is_configured_under_the_key_its_own_page_links():
    """It was recorded here as "a tenant with nothing in any tab, a shell, not a
    source". That was the wrong key: `CustomerOrg=USF` is empty, and
    `CustomerOrg=USFlorida` — which USF's own purchasing page links — returns 25
    archived solicitations. The same lesson as every other platform here.
    """
    from src.sources.registry import load_source_config

    orgs = {c.get("jaggaer_org") for c in load_source_config()
            if isinstance(c, dict) and c.get("adapter") == "jaggaer"}

    assert "USFlorida" in orgs
    assert "USF" not in orgs, "the empty tenant key, kept out on purpose"


def test_the_robots_override_is_declared_with_its_reason():
    from src.netpolicy import ROBOTS_OVERRIDES, robots_allows

    assert ROBOTS_OVERRIDES["bids.sciquest.com"].strip()

    allowed, why = robots_allows(
        "https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=FSU"
    )
    assert allowed and why.startswith("override:")


def test_strict_robots_drops_the_override(monkeypatch):
    from src import netpolicy

    monkeypatch.setenv("SF_SCOUT_STRICT_ROBOTS", "1")
    assert netpolicy._override_reason("bids.sciquest.com") is None
