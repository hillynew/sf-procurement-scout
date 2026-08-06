"""Platform fingerprinting: signatures, confidence, link finding, pointer pages."""

from __future__ import annotations

import pytest

from src.pipeline import fingerprint as fp


# -- signatures ------------------------------------------------------------


def test_a_platform_asset_is_a_strong_match():
    strong, weak = fp.identify('<link href="/Common/Modules/Bids/RWDBids.css">')
    assert strong == ["civicplus"]
    assert weak == []


def test_a_brand_name_in_prose_is_only_a_weak_match():
    """"Register with DemandStar" is a lead, not proof the agency runs it."""
    strong, weak = fp.identify("<p>Our bids are posted on DemandStar. Register today.</p>")
    assert strong == []
    assert weak == ["demandstar"]


def test_a_strong_match_beats_a_weak_one_on_the_same_page():
    html = '<link href="/Common/Modules/Bids/RWDBids.css"> and see DemandStar too'
    strong, weak = fp.identify(html)
    assert strong == ["civicplus"]
    assert "demandstar" not in weak or strong[0] == "civicplus"


def test_a_self_hosted_instance_still_matches():
    """Osceola runs VendorLink on its own subdomain, not the vendor's host."""
    strong, _ = fp.identify('<a href="https://vendorlink.osceola.org/common/default.aspx">Bids</a>')
    assert "vendorlink" in strong


def test_an_unrecognised_page_matches_nothing():
    strong, weak = fp.identify("<html><body>Bids are posted as PDFs below.</body></html>")
    assert strong == [] and weak == []


# -- portal URLs -----------------------------------------------------------


def test_the_bonfire_subdomain_is_extracted():
    html = '<a href="https://talgov.bonfirehub.com/portal/?tab=openOpportunities">Bids</a>'
    assert fp.portal_url_for("bonfire", html, "https://talgov.com") == (
        "https://talgov.bonfirehub.com/portal/?tab=openOpportunities"
    )


def test_the_opengov_slug_is_extracted():
    html = 'see <a href="https://procurement.opengov.com/portal/orangecountyfl">our portal</a>'
    assert fp.portal_url_for("opengov", html, "https://ocfl.net") == (
        "https://procurement.opengov.com/portal/orangecountyfl"
    )


def test_civicplus_reports_the_page_it_was_found_on():
    """The board *is* the URL — there is no separate tenant key to recover."""
    assert fp.portal_url_for("civicplus", "<html>", "https://davie-fl.gov/Bids.aspx") == (
        "https://davie-fl.gov/Bids.aspx"
    )


def test_a_platform_with_no_url_pattern_yields_none():
    assert fp.portal_url_for("peoplesoft", "<html>no url here</html>", "https://x.gov") is None


# -- finding the procurement page ------------------------------------------


def test_the_most_specific_bid_link_wins():
    html = """
      <a href="/vendor-registration">Vendor Registration</a>
      <a href="/business/bid-opportunities">Bid Opportunities</a>
      <a href="/purchasing">Purchasing Division</a>
    """
    assert fp.procurement_link(html, "https://city.gov") == (
        "https://city.gov/business/bid-opportunities"
    )


def test_an_offsite_platform_link_outranks_a_local_page():
    """A link straight at a known platform is the answer, not a step toward it."""
    html = """
      <a href="/purchasing">Purchasing</a>
      <a href="https://city.bonfirehub.com/portal/">Current Solicitations</a>
    """
    assert fp.procurement_link(html, "https://city.gov") == "https://city.bonfirehub.com/portal/"


def test_a_relative_href_is_resolved_against_the_page():
    html = '<a href="Bids.aspx">Bids</a>'
    assert fp.procurement_link(html, "https://city.gov/home/") == "https://city.gov/home/Bids.aspx"


def test_a_page_with_no_procurement_link_returns_none():
    assert fp.procurement_link('<a href="/parks">Parks</a>', "https://city.gov") is None


# -- the whole pass --------------------------------------------------------


class _Resp:
    def __init__(self, text, url):
        self.text = text
        self.url = url


def _pages(monkeypatch, mapping):
    def fake_get(url, **kw):
        for key, body in mapping.items():
            if url.rstrip("/").endswith(key.rstrip("/")) or url == key:
                return _Resp(body, url)
        raise RuntimeError("404")

    monkeypatch.setattr(fp, "get", fake_get)


def test_a_homepage_that_carries_the_signature_needs_no_second_fetch(monkeypatch):
    _pages(monkeypatch, {"https://city.gov": '<a href="https://city.bonfirehub.com/portal/">Bids</a>'})
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "bonfire"
    assert result.confidence == "strong"
    assert result.portal_url == "https://city.bonfirehub.com/portal/"


def test_the_procurement_page_is_followed_and_read(monkeypatch):
    _pages(
        monkeypatch,
        {
            "https://city.gov": '<a href="/purchasing">Purchasing</a>',
            "/purchasing": '<link href="/Common/Modules/Bids/RWDBids.css">' + "x" * 900,
        },
    )
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "civicplus"
    assert result.note == "matched on procurement page"


def test_a_named_but_unlinked_platform_is_recorded_weakly(monkeypatch):
    _pages(
        monkeypatch,
        {
            "https://city.gov": '<a href="/bids">Bids</a>',
            "/bids": "<p>All solicitations are posted on DemandStar.</p>" + "x" * 900,
        },
    )
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "demandstar"
    assert result.confidence == "weak"
    assert "not linked" in result.note


def test_a_client_rendered_homepage_says_so(monkeypatch):
    """Distinct from "no procurement page" — one is fixable by a human, one isn't."""
    _pages(monkeypatch, {"https://city.gov/": "<div id=root></div>"})
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "unknown"
    assert "client-side" in result.note


def test_a_self_hosted_bid_board_is_unknown_not_invented(monkeypatch):
    _pages(
        monkeypatch,
        {
            "https://city.gov": '<a href="/bids">Bids</a>',
            "/bids": "<p>Download the ITB packet:</p><a href='/itb.pdf'>ITB</a>" + "x" * 900,
        },
    )
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "unknown"
    assert result.note == "no platform signature"
    assert result.checked_url is not None, "the miss must be inspectable"


def test_an_unreachable_site_is_a_recorded_result_not_an_exception(monkeypatch):
    def boom(url, **kw):
        raise ConnectionError("nope")

    monkeypatch.setattr(fp, "get", boom)
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "unknown"
    assert "unreachable" in result.note


def test_a_robots_refusal_is_reported_rather_than_worked_around(monkeypatch):
    def refuse(url, **kw):
        raise fp.RobotsDisallowed("disallowed by robots: https://city.gov")

    monkeypatch.setattr(fp, "get", refuse)
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "unknown"
    assert "robots refused" in result.note


def test_an_agency_with_no_website_is_skipped_cleanly():
    result = fp.fingerprint_agency("sd-x", "Some District", "")
    assert result.platform == "unknown"
    assert result.note == "no website"


def test_a_bare_domain_gets_a_scheme(monkeypatch):
    seen = []

    def record(url, **kw):
        seen.append(url)
        return _Resp("<html>" + "x" * 9000 + "</html>", url)

    monkeypatch.setattr(fp, "get", record)
    fp.fingerprint_agency("mun-x", "City of X", "city.gov")

    assert seen[0].startswith("https://")


@pytest.mark.parametrize("platform,needle", [
    ("bonfire", "bonfirehub.com"),
    ("civicplus", "/Common/Modules/Bids/RWDBids.css"),
    ("opengov", "procurement.opengov.com/portal/"),
])
def test_the_signature_table_keeps_the_platforms_we_actually_fetch(platform, needle):
    """These three back live adapters; losing their signature would be silent."""
    table = {name: strong for name, strong, _weak in fp.PLATFORM_SIGNATURES}
    assert needle in table[platform]
