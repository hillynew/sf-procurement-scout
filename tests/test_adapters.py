"""Adapter parsing, driven by saved portal responses (no network)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup

from src.sources.mdc_college import MdcCollegeAdapter, _extract_ref
from src.sources.miami_dade_construction import (
    MiamiDadeConstructionAdapter,
    MiamiDadeFutureAdapter,
)
from src.sources.swa import SwaAdapter

MD_CFG = {
    "id": "miami_dade_construction",
    "name": "Miami-Dade Construction Solicitations",
    "county": "miami-dade",
    "agency": "Miami-Dade County",
    "portal_url": "https://www.miamidade.gov/apps/ISD/stratproc/Home/CurrentSolicitations",
}
MDC_CFG = {
    "id": "mdc_college",
    "name": "Miami Dade College Bid Posting",
    "county": "miami-dade",
    "agency": "Miami Dade College",
    "portal_url": "https://www.mdc.edu/purchasing/bid-posting/",
    "register_url": "https://www.bidnetdirect.com/florida/miamidadecollege",
}
SWA_CFG = {
    "id": "swa_pbc",
    "name": "Solid Waste Authority of Palm Beach County",
    "county": "palm-beach",
    "agency": "Solid Waste Authority of Palm Beach County",
    "portal_url": "https://www.swa.org/Bids.aspx",
}


# ---------------------------------------------------------------------------
# Miami-Dade ISD — was returning zero rows because the table is AJAX-filled
# ---------------------------------------------------------------------------


@pytest.fixture
def md_current(fixtures_dir):
    return json.loads((fixtures_dir / "md_current.json").read_text())


@pytest.fixture
def md_future(fixtures_dir):
    return json.loads((fixtures_dir / "md_future.json").read_text())


def test_current_solicitations_are_parsed(monkeypatch, md_current):
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._fetch_list", lambda *a, **k: md_current
    )
    opps = MiamiDadeConstructionAdapter(MD_CFG).fetch()

    assert len(opps) == len(md_current)
    assert all(o.status == "open" for o in opps)
    assert all(o.due_date is not None for o in opps), "opening date drives urgency"
    assert all(o.external_id for o in opps)


def test_current_solicitation_links_to_its_detail_page(monkeypatch, md_current):
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._fetch_list", lambda *a, **k: md_current
    )
    o = MiamiDadeConstructionAdapter(MD_CFG).fetch()[0]
    assert "SolicitationDetails?solNumber=" in o.url, "must deep-link, not just the index"


def test_date_filed_as_title_falls_back_to_reference(monkeypatch):
    """The portal really does publish rows whose title column holds a date."""
    row = [
        {
            "solicitationNumber": "RPQ No M2026-009",
            "solicitationType": "Bids & Contracts",
            "title": "8/10/2026",
            "openingDate": "10/18/2026",
            "postedDate": "07/20/2026",
        }
    ]
    monkeypatch.setattr("src.sources.miami_dade_construction._fetch_list", lambda *a, **k: row)
    (o,) = MiamiDadeConstructionAdapter(MD_CFG).fetch()
    assert o.title == "RPQ No M2026-009"


def test_row_without_title_or_reference_is_skipped(monkeypatch):
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._fetch_list",
        lambda *a, **k: [{"title": "", "solicitationNumber": ""}],
    )
    assert MiamiDadeConstructionAdapter(MD_CFG).fetch() == []


def test_future_solicitations_are_upcoming_with_contact(monkeypatch, md_future):
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._fetch_list", lambda *a, **k: md_future
    )
    opps = MiamiDadeFutureAdapter({**MD_CFG, "id": "miami_dade_future"}).fetch()

    assert opps and all(o.status == "upcoming" for o in opps)
    assert all(o.due_date is None for o in opps), "advance notices have no bid date"
    assert any("@" in (o.contact or "") for o in opps), "buyer email should survive"
    assert all(o.external_id for o in opps), "posting counter is the stable key"


def test_unexpected_json_shape_yields_no_rows(monkeypatch):
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._fetch_list", lambda *a, **k: []
    )
    monkeypatch.setattr(
        "src.sources.miami_dade_construction._parse_html_fallback", lambda *a, **k: []
    )
    assert MiamiDadeConstructionAdapter(MD_CFG).fetch() == []


# ---------------------------------------------------------------------------
# Miami Dade College — was emitting ~110 duplicate, permanently "open" rows
# ---------------------------------------------------------------------------


@pytest.fixture
def mdc_opps(monkeypatch, fixtures_dir):
    html = (fixtures_dir / "mdc_bid_posting.html").read_text()

    class _Resp:
        text = html

    monkeypatch.setattr("src.sources.mdc_college.get", lambda *a, **k: _Resp())
    return MdcCollegeAdapter(MDC_CFG).fetch()


def test_announcement_rows_collapse_to_one_per_solicitation(mdc_opps, fixtures_dir):
    soup = BeautifulSoup((fixtures_dir / "mdc_bid_posting.html").read_text(), "lxml")
    raw_rows = sum(len(t.find_all("tr")) - 1 for t in soup.find_all("table"))
    assert len(mdc_opps) < raw_rows, "one solicitation must not yield one row per announcement"


def test_no_duplicate_references(mdc_opps):
    refs = [o.external_id for o in mdc_opps if o.external_id]
    assert len(refs) == len(set(refs))


def test_archived_solicitations_are_not_open(mdc_opps):
    cutoff = date.today() - timedelta(days=365)
    stale_open = [
        o for o in mdc_opps if o.status == "open" and o.posted_date and o.posted_date < cutoff
    ]
    assert not stale_open, f"year-old bids reported open: {[o.title for o in stale_open]}"


def test_awarded_solicitations_are_closed(mdc_opps):
    awarded = [o for o in mdc_opps if "award" in (o.description or "").lower()]
    assert all(o.status == "closed" for o in awarded)


def test_single_source_notices_are_tagged(mdc_opps):
    nssp = [o for o in mdc_opps if "single_source" in o.categories]
    assert nssp, "the NSSP table should be picked up"
    assert all(o.status in {"upcoming", "closed"} for o in nssp)


@pytest.mark.parametrize(
    "title, expected",
    [
        ("RFQ-2024-NL-07- PREQUALIFICATION OF MECHANICAL CONTRACTORS", "2024-NL-07"),
        ("2024-NL-07 - Prequalification Mechanical Contractors", "2024-NL-07"),
        ("2024-NL-07- Prequalification of Mechanical Contractors", "2024-NL-07"),
        ("ITN 2025-RM1-01 Managed Security Operations Center", "2025-RM1-01"),
        ("RFQ‐2025-RM-09 –Signs and Banners", "2025-RM-09"),
    ],
)
def test_reference_variants_normalize_to_one_key(title, expected):
    """These five spellings are all the same solicitation on the live page."""
    assert _extract_ref(title) == expected


@pytest.mark.parametrize(
    "title", ["OPPORTUNITY FOR VENDORS IN SOUTH FLORIDA", "NC3 Certification Kits", ""]
)
def test_titles_without_a_reference_return_none(title):
    assert _extract_ref(title) is None


# ---------------------------------------------------------------------------
# SWA — an empty bid board must not become a fake opportunity
# ---------------------------------------------------------------------------


def test_empty_bid_board_returns_nothing(monkeypatch):
    class _Resp:
        text = "<html><body><p>There are no open bid postings at this time.</p></body></html>"

    monkeypatch.setattr("src.sources.swa.get", lambda *a, **k: _Resp())
    assert SwaAdapter(SWA_CFG).fetch() == []


def test_bid_links_are_parsed_when_no_table(monkeypatch):
    class _Resp:
        text = """
        <html><body>
          <a href="/Bids.aspx?bidID=41">Recycling Processing Services Agreement</a>
          <a href="/Bids.aspx?bidID=41">Recycling Processing Services Agreement</a>
          <a href="/about">About us</a>
        </body></html>
        """

    monkeypatch.setattr("src.sources.swa.get", lambda *a, **k: _Resp())
    opps = SwaAdapter(SWA_CFG).fetch()
    assert len(opps) == 1, "the repeated link must not double-count"
    assert opps[0].url.startswith("https://www.swa.org/Bids.aspx?bidID=41")
    assert "waste_recycling" in opps[0].categories
