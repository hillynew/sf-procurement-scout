"""The three ways the fingerprinter learned to look past a homepage's links.

635 of the 815 entities swept came back `unknown`, and they were not one
problem. They were four, in different proportions:

    271  link-following failed — the homepage linked nothing we recognised
    151  read a page, no platform signature
    198  could not reach the site at all
     15  robots refused

Only the first two are fingerprinting problems, and each needed a different
answer: a procurement *subdomain* for the institutions that never link
purchasing from a homepage aimed at students, one more *hop* off a landing page
that is only a signpost, and `selfhosted` for the agencies that run no platform
because they keep the table on their own website.

Measured across the 101 unknown counties, school districts and universities —
the entities that certainly run a procurement office — the three together
recover 14, including the four largest universities in the state.
"""

from __future__ import annotations

from src.pipeline import fingerprint as fp


class _Resp:
    def __init__(self, text, url):
        self.text = text
        self.url = url


def _pages(monkeypatch, mapping, *, seen=None):
    """Serve only the URLs in `mapping`; everything else 404s, as in life."""
    def fake_get(url, **kw):
        if seen is not None:
            seen.append(url)
        for key, body in mapping.items():
            if url.rstrip("/") == key.rstrip("/"):
                return _Resp(body, url)
        raise RuntimeError("404")

    monkeypatch.setattr(fp, "get", fake_get)


BULK = "x" * 9000
BOARD = (
    "<table>"
    "<tr><td>ITB 26-014 Roof Replacement</td><td>Due 07/23/2026</td></tr>"
    "<tr><td>RFP#2026-01 Auditing Services</td><td>Due 06/30/2026</td></tr>"
    "<tr><td>RFQ 26-002 Paving</td><td>Due June 25, 2026</td></tr>"
    "</table>" + BULK
)


# -- procurement subdomains ------------------------------------------------


def test_a_procurement_subdomain_is_tried_when_the_homepage_links_nothing(monkeypatch):
    """`procurement.fsu.edu` and `bids.fiu.edu` are both Jaggaer, and both read
    as "no procurement link found" for as long as this only followed links. A
    university homepage is built for students; it does not link purchasing."""
    _pages(monkeypatch, {
        "https://www.fsu.edu": "<h1>Florida State University</h1>" + BULK,
        "https://procurement.fsu.edu": (
            '<a href="https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=FSU">'
            "Current Bids</a>" + BULK
        ),
    })
    result = fp.fingerprint_agency("uni-fsu", "Florida State University", "https://www.fsu.edu")

    assert result.platform == "jaggaer"
    assert result.confidence == "strong"


def test_the_bids_subdomain_is_reached_within_the_probe_budget(monkeypatch):
    """It sits behind four paths, and a budget that stopped short of it was
    why FIU stayed unknown through the first pass of this work."""
    _pages(monkeypatch, {
        "https://www.fiu.edu": "<h1>FIU</h1>" + BULK,
        "https://bids.fiu.edu": '<a href="https://bids.sciquest.com/apps/Router/PublicEvent">B</a>' + BULK,
    })
    result = fp.fingerprint_agency("uni-fiu", "FIU", "https://www.fiu.edu")

    assert result.platform == "jaggaer"


def test_the_common_paths_are_still_tried_first(monkeypatch):
    """A small town's `/Bids.aspx` must not cost four DNS lookups first —
    CivicPlus is the largest platform among Florida municipalities."""
    seen = []
    _pages(monkeypatch, {
        "https://city.gov": "<h1>City</h1>" + BULK,
        "https://city.gov/Bids.aspx": '<link href="/Common/Modules/Bids/RWDBids.css">' + BULK,
    }, seen=seen)
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "civicplus"
    assert seen == ["https://city.gov", "https://city.gov/Bids.aspx"]


def test_a_deep_host_gets_no_subdomain_guesses():
    """`bids.town.windermere.fl.us` is a guess too far, and every Florida
    municipality lives three labels deep."""
    candidates = fp._probe_candidates("https://www.town.windermere.fl.us/")

    assert not any(c.startswith("https://bids.") for c in candidates)


def test_the_probe_reads_the_page_it_found_rather_than_fetching_it_twice(monkeypatch):
    seen = []
    _pages(monkeypatch, {
        "https://city.gov": "<h1>City</h1>" + BULK,
        "https://city.gov/bids": BOARD,
    }, seen=seen)
    fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert seen.count("https://city.gov/bids") == 1


def test_a_page_that_merely_answers_is_a_fallback_not_a_stop(monkeypatch):
    """`/bids` returning a contact page must not stop the probe before the
    subdomain that actually holds the board."""
    _pages(monkeypatch, {
        "https://uni.edu": "<h1>University</h1>" + BULK,
        "https://uni.edu/bids": "<p>Contact purchasing at 555-0100.</p>" + BULK,
        "https://bids.uni.edu": '<a href="https://uni.bonfirehub.com/portal/">Bids</a>' + BULK,
    })
    result = fp.fingerprint_agency("uni-x", "University", "https://uni.edu")

    assert result.platform == "bonfire"


def test_the_fallback_is_used_when_nothing_better_turns_up(monkeypatch):
    """Reading their purchasing page and finding no platform is a different
    miss from finding no page at all, and only one is worth a human minute."""
    _pages(monkeypatch, {
        "https://city.gov": "<h1>City</h1>" + BULK,
        "https://city.gov/purchasing": "<p>Contact purchasing at 555-0100.</p>" + BULK,
    })
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.note == "no platform signature"
    assert result.checked_url == "https://city.gov/purchasing"


# -- one more hop ----------------------------------------------------------


def test_a_signpost_page_is_followed_one_more_hop(monkeypatch):
    """UF and USF are both Jaggaer behind a `procurement.` page that names no
    platform — contacts, terms, and a link to where the bids actually are."""
    _pages(monkeypatch, {
        "https://www.ufl.edu": '<a href="/procurement">Procurement</a>' + BULK,
        "https://www.ufl.edu/procurement": (
            "<h1>Procurement Services</h1>"
            '<a href="/procurement/vendors/schedule-of-bids/">Schedule of Bids</a>' + BULK
        ),
        "https://www.ufl.edu/procurement/vendors/schedule-of-bids/": (
            '<a href="https://bids.sciquest.com/apps/Router/PublicEvent">Open bids</a>' + BULK
        ),
    })
    result = fp.fingerprint_agency("uni-uf", "University of Florida", "https://www.ufl.edu")

    assert result.platform == "jaggaer"
    assert result.checked_url.endswith("/schedule-of-bids/")


def test_the_hop_may_cross_to_the_agencys_own_subdomain(monkeypatch):
    _pages(monkeypatch, {
        "https://www.uni.edu": '<a href="/purchasing">Purchasing</a>' + BULK,
        "https://www.uni.edu/purchasing": '<a href="https://bids.uni.edu/">Current bids</a>' + BULK,
        "https://bids.uni.edu": '<a href="https://uni.bonfirehub.com/portal/">Bids</a>' + BULK,
    })
    result = fp.fingerprint_agency("uni-x", "University", "https://www.uni.edu")

    assert result.platform == "bonfire"


def test_the_hop_will_not_cross_to_another_agency(monkeypatch):
    """New College's procurement page links `unf.edu` — a different university
    entirely. Following that files one agency's platform under another's name.
    """
    _pages(monkeypatch, {
        "https://www.ncf.edu": '<a href="/procurement">Procurement</a>' + BULK,
        "https://www.ncf.edu/procurement": '<a href="https://www.unf.edu/procurement/">Bids</a>' + BULK,
        "https://www.unf.edu/procurement/": (
            '<a href="https://unf.public-portal.us.workdayspend.com">Bids</a>' + BULK
        ),
    })
    result = fp.fingerprint_agency("uni-ncf", "New College of Florida", "https://www.ncf.edu")

    assert result.platform == "unknown"


def test_the_hop_is_taken_at_most_once(monkeypatch):
    """A page linking a page linking a page is a site crawl, which this is not."""
    seen = []
    _pages(monkeypatch, {
        "https://city.gov": '<a href="/purchasing">Purchasing</a>' + BULK,
        "https://city.gov/purchasing": '<a href="/purchasing/bids">Bids</a>' + BULK,
        "https://city.gov/purchasing/bids": '<a href="/purchasing/bids/open">Open</a>' + BULK,
        "https://city.gov/purchasing/bids/open": '<a href="https://x.bonfirehub.com/portal/">B</a>' + BULK,
    }, seen=seen)
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "unknown"
    assert "https://city.gov/purchasing/bids/open" not in seen


def test_a_page_that_already_matched_is_not_hopped_from(monkeypatch):
    seen = []
    _pages(monkeypatch, {
        "https://city.gov": '<a href="/bids">Bids</a>' + BULK,
        "https://city.gov/bids": (
            '<link href="/Common/Modules/Bids/RWDBids.css">'
            '<a href="/bids/archive">Bid archive</a>' + BULK
        ),
    }, seen=seen)
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "civicplus"
    assert "https://city.gov/bids/archive" not in seen


# -- signatures a second vendor also serves --------------------------------


def test_a_records_request_portal_is_not_a_bid_portal():
    """`/PublicPortal/` is where Bonfire's API lives, and it was a strong
    signature until 15 Florida agencies turned up as Bonfire tenants with no
    Bonfire host. They link `<agency>.justfoia.com/publicportal/` — a public
    *records request* portal. A path a second vendor also serves proves
    nothing, and the false positives were unfalsifiable: strong confidence, no
    portal URL, so nothing downstream could ever check them.
    """
    strong, weak = fp.identify(
        '<a href="https://largofl.justfoia.com/publicportal/home/newrequest">'
        "Create Public Records Request</a>"
    )

    assert strong == [] and weak == []


def test_a_real_bonfire_tenant_still_matches():
    strong, _ = fp.identify('<a href="https://swa.bonfirehub.com/portal/">Bids</a>')

    assert strong == ["bonfire"]


# -- boards with no platform behind them -----------------------------------


def test_an_agency_that_runs_no_platform_is_an_answer_not_a_miss(monkeypatch):
    """151 entities read a procurement page and matched nothing. Filing those
    as `unknown` puts a readable bid board in the same bucket as a site that
    timed out, and they are opposite kinds of miss."""
    _pages(monkeypatch, {
        "https://city.gov": '<a href="/bids">Bids</a>' + BULK,
        "https://city.gov/bids": BOARD,
    })
    result = fp.fingerprint_agency("mun-x", "City of X", "https://city.gov")

    assert result.platform == "selfhosted"
    assert result.confidence == "page"
    assert result.portal_url == "https://city.gov/bids"
    assert result.note == "solicitations listed on the agency's own page"


def test_a_platform_still_beats_a_board(monkeypatch):
    """A CivicPlus board also lists numbered solicitations and dates. The
    platform is the more useful answer, and it is checked first."""
    _pages(monkeypatch, {
        "https://city.gov": '<a href="/bids">Bids</a>' + BULK,
        "https://city.gov/bids": '<link href="/Common/Modules/Bids/RWDBids.css">' + BOARD,
    })

    assert fp.fingerprint_agency("mun-x", "City of X", "https://city.gov").platform == "civicplus"


def test_two_numbered_solicitations_and_two_dates_is_a_board():
    """Cape Canaveral, which had exactly two open, is the case that set this."""
    assert fp.looks_like_a_bid_board(
        "<p>BID#2026-05 posted July 23, 2026</p><p>RFP#2026-01 posted June 30, 2026</p>"
    )


def test_one_solicitation_is_a_news_item():
    assert not fp.looks_like_a_bid_board(
        "<p>RFP-2026-02 selection committee meets 08/03/2026, opened 07/28/2026.</p>"
    )


def test_the_same_solicitation_written_twice_is_still_one():
    """`RFP-2026-02` and `RFP2026-02` on one page counted as two, which was
    enough to call Arcadia's single news post a bid board."""
    assert not fp.looks_like_a_bid_board(
        "<p>RFP-2026-02 (RFP2026-02) opens 08/03/2026 and closes 09/01/2026.</p>"
    )


def test_a_policy_page_that_says_bid_constantly_is_not_a_board():
    """The number is what keeps this off a purchasing policy page."""
    assert not fp.looks_like_a_bid_board(
        "<p>All bids over $50,000 require a formal bid. Bid packets are available "
        "from the Purchasing Office. Bid bonds are required on every bid. "
        "Sealed bids are opened publicly. See our bid policy, revised 01/01/2024 "
        "and again on 06/15/2025.</p>"
    )


def test_solicitations_without_dates_are_not_a_live_board():
    """A page of archived numbers with nothing due is a record, not a board."""
    assert not fp.looks_like_a_bid_board("<p>ITB 26-014, RFP 26-002, RFQ 25-113</p>")


def test_a_bid_numbered_in_a_sentence_does_not_count():
    """"Bid 60" is prose. A solicitation number carries a year and a sequence."""
    assert not fp.looks_like_a_bid_board(
        "<p>Bid 60 was awarded 01/02/2026. Bid 61 followed on 02/03/2026. "
        "Bid 62 is pending 03/04/2026.</p>"
    )
