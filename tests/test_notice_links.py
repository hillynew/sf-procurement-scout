"""Agencies that publish solicitations as a list of public-notice links."""

from __future__ import annotations

import pytest

from src.sources.notice_links import NoticeLinksAdapter

CFG = {
    "id": "coral_gables",
    "name": "City of Coral Gables Procurement Notices",
    "county": "miami-dade",
    "agency": "City of Coral Gables",
    "portal_url": "https://www.coralgables.com/department/procurement/procurement-notices",
}


def _adapter(monkeypatch, html: str, **overrides):
    class _Resp:
        text = html

    monkeypatch.setattr("src.sources.notice_links.get", lambda *a, **k: _Resp())
    return NoticeLinksAdapter({**CFG, **overrides})


def _page(*anchors):
    return "<html><body>" + "".join(anchors) + "</body></html>"


def _link(text, href="/sites/default/files/notice.pdf"):
    return f'<a href="{href}">{text}</a>'


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_parses_the_live_page(monkeypatch, fixtures_dir):
    html = (fixtures_dir / "coral_gables_notices.html").read_text()
    opps = _adapter(monkeypatch, html).fetch()

    assert len(opps) == 4
    assert all(o.external_id for o in opps)
    assert all(o.status == "open" for o in opps)
    assert all(o.url.startswith("https://www.coralgables.com/") for o in opps)


@pytest.mark.parametrize(
    "text, ref, title",
    [
        ("Public Notice - RFP 2026-023 - Plan Review Services [PDF]", "RFP 2026-023", "Plan Review Services"),
        ("Public Notice - IFB 2026-019 - Rotary Park Renovation Revised [PDF]", "IFB 2026-019", "Rotary Park Renovation"),
        ("2nd REVISED Public-Notice-IFB-2026-021 Art Cinema Expansion [PDF]", "IFB 2026-021", "Art Cinema Expansion"),
        ("ITB No. 25-26-120 Pressure Washing Services", "ITB 25-26-120", "Pressure Washing Services"),
    ],
)
def test_reference_and_title_are_separated(monkeypatch, text, ref, title):
    (o,) = _adapter(monkeypatch, _page(_link(text))).fetch()
    assert o.external_id == ref
    assert o.title == title


def test_notice_boilerplate_is_stripped_even_when_stacked(monkeypatch):
    """'... Revised [PDF]' needs more than one pass to peel off."""
    (o,) = _adapter(monkeypatch, _page(_link("Public Notice - IFB 2026-024 - Roof Work Revised [PDF]"))).fetch()
    assert o.title == "Roof Work"


def test_relative_hrefs_resolve_against_the_portal(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_link("RFP 2026-001 - Study", "/files/a.pdf"))).fetch()
    assert o.url == "https://www.coralgables.com/files/a.pdf"


def test_solicitation_type_is_classified(monkeypatch):
    (o,) = _adapter(monkeypatch, _page(_link("Public Notice - RFP 2026-023 - Plan Review"))).fetch()
    assert o.solicitation_type == "RFP"


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def test_links_without_a_reference_are_ignored(monkeypatch):
    page = _page(_link("Procurement home"), _link("Code of Ethics"), _link("Surplus auctions"))
    assert _adapter(monkeypatch, page).fetch() == []


@pytest.mark.parametrize(
    "text",
    [
        "Notice of Award - RFP 2026-005 - Janitorial",
        "Bid Tabulation - IFB 2026-006 - Paving",
        "Intent to Award - RFP 2026-007 - Consulting",
    ],
)
def test_award_notices_are_not_solicitations(monkeypatch, text):
    """These describe a procurement that has already been decided."""
    assert _adapter(monkeypatch, _page(_link(text))).fetch() == []


def test_repostings_collapse_to_one_record(monkeypatch):
    """A solicitation is often re-posted revised; keep the fullest title."""
    page = _page(
        _link("Public Notice - IFB 2026-021 - Art Cinema"),
        _link("REVISED Public Notice - IFB 2026-021 - Art Cinema Expansion Project [PDF]"),
    )
    (o,) = _adapter(monkeypatch, page).fetch()
    assert o.title == "Art Cinema Expansion Project"


def test_titles_too_short_are_skipped(monkeypatch):
    assert _adapter(monkeypatch, _page(_link("RFP 2026-002 - Ads"))).fetch() == []


def test_link_selector_scopes_the_search(monkeypatch):
    html = (
        '<html><body><div class="sidebar">'
        + _link("RFP 2026-900 - Archived Study")
        + '</div><div class="main">'
        + _link("RFP 2026-100 - Drainage Study")
        + "</div></body></html>"
    )
    opps = _adapter(monkeypatch, html, link_selector="div.main").fetch()
    assert [o.external_id for o in opps] == ["RFP 2026-100"]


def test_missing_selector_falls_back_to_whole_page(monkeypatch):
    page = _page(_link("RFP 2026-100 - Drainage Study"))
    opps = _adapter(monkeypatch, page, link_selector="div.does-not-exist").fetch()
    assert len(opps) == 1


def test_empty_page_returns_nothing(monkeypatch):
    assert _adapter(monkeypatch, "<html><body></body></html>").fetch() == []
