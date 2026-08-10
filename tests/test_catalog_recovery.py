"""Looking past a platform we are not allowed to read.

`src/terms.py` keeps VendorLink, DemandStar, Vendor Registry and BidNet out of
this build, and their agencies sit as `catalog` pointers. The pointers were
treated as the end of the story, and they are not: most of these agencies post
the same solicitation somewhere else as well — a CivicPlus board at
`/Bids.aspx`, a Bonfire portal, their own page.

The sweep could never find those, for a reason that reads as a feature until
you need it otherwise: `fingerprint_agency` stops at the first strong
signature. The moment a purchasing page said VendorLink the question was
answered, and the CivicPlus board one URL away was never fetched.

`avoid` is the narrow fix. A signature for an avoided platform is still true —
it goes into `also` and is never dropped — but it no longer stops the search.
These tests are the difference between the two behaviours, and the guarantee
that nothing changes for callers that do not pass `avoid`.
"""

from __future__ import annotations

import pytest

from src.pipeline import fingerprint as fp
from src.terms import FORBIDS_ADAPTER, GRANDFATHERED, TERMS


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
VENDORLINK = '<a href="https://www.myvendorlink.com/external/bids?a=70">Bid Opportunities</a>'
CIVICPLUS = '<link rel="stylesheet" href="/Common/Modules/Bids/RWDBids.css">'
BONFIRE = '<a href="https://cityofsebastian.bonfirehub.com/portal">Open Solicitations</a>'
BOARD = (
    "<table>"
    "<tr><td>ITB 26-014 Roof Replacement</td><td>Due 07/23/2026</td></tr>"
    "<tr><td>RFP#2026-01 Auditing Services</td><td>Due 06/30/2026</td></tr>"
    "</table>" + BULK
)

AVOID = frozenset({"vendorlink"})


# -- the filter itself ------------------------------------------------------


def test_usable_drops_the_platforms_we_cannot_read():
    assert fp.usable(["vendorlink", "civicplus"], AVOID) == ["civicplus"]
    assert fp.usable(["vendorlink"], AVOID) == []
    assert fp.usable(["civicplus"], frozenset()) == ["civicplus"]


# -- the behaviour that changes --------------------------------------------


def test_a_vendorlink_homepage_no_longer_ends_the_search(monkeypatch):
    """The case this was built for. A city advertises VendorLink in its nav and
    keeps a CivicPlus board at `/Bids.aspx`; the sweep saw the first and
    stopped."""
    _pages(monkeypatch, {
        "https://www.holly-hill.fl.us": "<h1>City of Holly Hill</h1>" + VENDORLINK + BULK,
        "https://www.holly-hill.fl.us/Bids.aspx": CIVICPLUS + BOARD,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-holly-hill", "City of Holly Hill",
        "https://www.holly-hill.fl.us", avoid=AVOID,
    )

    assert result.platform == "civicplus"
    assert result.confidence == "strong"


def test_the_same_page_without_avoid_still_stops_at_vendorlink(monkeypatch):
    """The regression guard. Every existing caller passes no `avoid`, and for
    them the answer to "what does this agency run" is unchanged."""
    _pages(monkeypatch, {
        "https://www.holly-hill.fl.us": "<h1>City of Holly Hill</h1>" + VENDORLINK + BULK,
        "https://www.holly-hill.fl.us/Bids.aspx": CIVICPLUS + BOARD,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-holly-hill", "City of Holly Hill", "https://www.holly-hill.fl.us")

    assert result.platform == "vendorlink"


def test_the_passed_over_platform_is_recorded_not_dropped(monkeypatch):
    """An agency that posts to both is a fact worth keeping. Recording only
    CivicPlus would read as an agency that never ran VendorLink, and the next
    person to wonder why it is not in the catalog would have to re-read the
    site to find out."""
    _pages(monkeypatch, {
        "https://www.holly-hill.fl.us": "<h1>City of Holly Hill</h1>" + VENDORLINK + BULK,
        "https://www.holly-hill.fl.us/Bids.aspx": CIVICPLUS + BOARD,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-holly-hill", "City of Holly Hill",
        "https://www.holly-hill.fl.us", avoid=AVOID,
    )

    assert "vendorlink" in result.also


def test_a_vendorlink_purchasing_page_spends_the_probe_budget(monkeypatch):
    """The commoner shape: the homepage links a purchasing page, and *that* is
    what names VendorLink. The board is still one known path away."""
    _pages(monkeypatch, {
        "https://www.satellitebeach.org": (
            '<a href="/purchasing">Purchasing</a>' + BULK),
        "https://www.satellitebeach.org/purchasing": (
            "<h1>Purchasing</h1>" + VENDORLINK + BULK),
        "https://www.satellitebeach.org/Bids.aspx": CIVICPLUS + BOARD,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-satellite-beach", "City of Satellite Beach",
        "https://www.satellitebeach.org", avoid=AVOID,
    )

    assert result.platform == "civicplus"
    assert "vendorlink" in result.also


def test_a_self_hosted_board_counts_as_a_recovery(monkeypatch):
    """No platform because there is no platform — the agency keeps the table on
    its own page. That is readable, and it is the answer."""
    _pages(monkeypatch, {
        "https://www.newberryfl.gov": "<h1>City of Newberry</h1>" + VENDORLINK + BULK,
        "https://www.newberryfl.gov/bids": BOARD,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-newberry", "City of Newberry",
        "https://www.newberryfl.gov", avoid=AVOID,
    )

    assert result.platform == "selfhosted"
    assert "vendorlink" in result.also


def test_bonfire_is_found_the_same_way(monkeypatch):
    """Nothing about this is CivicPlus-specific; the probe stops at the first
    platform we are allowed to read, whichever it is."""
    _pages(monkeypatch, {
        "https://www.cityofsebastian.org": "<h1>Sebastian</h1>" + VENDORLINK + BULK,
        "https://www.cityofsebastian.org/purchasing": BONFIRE + BULK,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-sebastian", "City of Sebastian",
        "https://www.cityofsebastian.org", avoid=AVOID,
    )

    assert result.platform == "bonfire"


# -- the behaviour that must not change ------------------------------------


def test_an_agency_with_nowhere_else_to_post_still_reads_vendorlink(monkeypatch):
    """`avoid` is not a licence to invent an alternative. When the probe finds
    nothing, the honest answer is the platform that is demonstrably there — and
    `src/terms.py` keeps it out of the fetcher, which is the correct outcome."""
    _pages(monkeypatch, {
        "https://www.kissimmee.gov": "<h1>Kissimmee</h1>" + VENDORLINK + BULK,
    })

    result = fp.fingerprint_agency(
        "mun-city-of-kissimmee", "City of Kissimmee",
        "https://www.kissimmee.gov", avoid=AVOID,
    )

    assert result.platform == "vendorlink"
    assert result.confidence == "strong"


def test_a_recovered_platform_is_one_the_terms_table_allows():
    """Whatever this recovers has to clear the same bar as anything else. The
    recovery would be worthless — worse, a laundering route — if it could hand
    the generator a platform the terms forbid."""
    from src.terms import may_build_adapter

    for platform in ("civicplus", "bonfire", "ionwave"):
        assert may_build_adapter(platform) is True
    for platform in ("vendorlink", "demandstar", "vendor_registry", "bidnet"):
        assert may_build_adapter(platform) is False
    # `opengov` is UNCHECKED and grandfathered — it already has an adapter and
    # 91 configured sources. Recovery may land on it, and that changes nothing
    # about the debt recorded against it in `src/terms.py`.
    assert may_build_adapter("opengov") is False
    assert "opengov" in GRANDFATHERED


def test_the_avoid_set_is_the_terms_table_not_a_second_list():
    """The recovery script derives `avoid` from `src/terms.py`. A hand-kept
    copy would drift, and the direction it drifts is a platform quietly
    becoming readable."""
    import scripts.recover_catalog_coverage as rec

    from_terms = {p for p, v in TERMS.items() if v.status in FORBIDS_ADAPTER}

    assert {"vendorlink", "demandstar", "vendor_registry", "bidnet"} <= from_terms
    # Everything the terms table forbids, less what already has an adapter.
    assert rec.forbidden_platforms() == from_terms - GRANDFATHERED


def test_a_grandfathered_platform_is_not_swept():
    """`jaggaer` is UNREADABLE and still has an adapter, so its agencies are
    already read. Sweeping them would spend requests to rediscover coverage we
    have, and the debt against it belongs in `src/terms.py`, not here."""
    import scripts.recover_catalog_coverage as rec

    assert "jaggaer" not in rec.forbidden_platforms()


# -- resolving a platform's name for a buyer to the state's ------------------


@pytest.mark.parametrize("catalog_name,expected", [
    ("Brevard County Board of County Commissioners", "brevard county"),
    ("Hernando County BOCC", "hernando county"),
    ("Highlands County FL", "highlands county"),
    ("Collier County Public Schools", "collier county school district"),
    ("Citrus County School Board", "citrus county school district"),
    ("Volusia County School Board Procurement", "volusia county school district"),
    ("Marion County School Board Facilities", "marion county school district"),
    ("Escambia County School District Facilities Department",
     "escambia county school district"),
    ("Glades Electric Cooperative, Inc.", "glades electric cooperative"),
])
def test_the_platforms_name_for_a_buyer_becomes_the_states(catalog_name, expected):
    """The catalog carries the platform's name for a buyer and the roster
    carries the state's. Neither is wrong; they are different registries."""
    import scripts.recover_catalog_coverage as rec

    assert rec.normalise(catalog_name) == expected


def test_a_suffix_class_is_tried_as_a_prefix():
    """"Bal Harbour Village" is the registry's "Village of Bal Harbour"."""
    import scripts.recover_catalog_coverage as rec

    assert "village of bal harbour" in rec.variants("Bal Harbour Village")


def _generator():
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "sff_recovery", root / "scripts" / "sources_from_fingerprints.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sff_recovery"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_an_embed_url_names_no_tenant():
    """`procurement.opengov.com/portal/embed` is the widget endpoint an agency
    drops into its own page. The tenant goes to the widget, not into the path,
    so the `/portal/(...)` pattern comes back with "embed" — which is not an
    agency and whose board 404s."""
    mod = _generator()

    cfg = mod.to_source({
        "entity_id": "sd-central-florida-expressway-authority",
        "name": "Central Florida Expressway Authority",
        "platform": "opengov",
        "portal_url": "https://procurement.opengov.com/portal/embed",
        "confidence": "strong",
    })

    assert cfg is None


def test_a_real_opengov_tenant_still_resolves():
    """The guard must not cost the ordinary case."""
    mod = _generator()

    cfg = mod.to_source({
        "entity_id": "co-hernando-county",
        "name": "Hernando County",
        "platform": "opengov",
        "portal_url": "https://procurement.opengov.com/portal/hernandocounty",
        "confidence": "strong",
    })

    assert cfg is not None
    assert cfg["opengov_code"] == "hernandocounty"


def test_an_embed_url_names_its_tenant_one_segment_deeper():
    """`/portal/embed/pcsb/project-list` *does* carry the tenant — the pattern
    just stopped at the literal `embed`. All five agencies found this way turned
    out to be configured already, so reading it correctly buys no coverage; what
    it buys is a report that says "already configured" instead of "the URL does
    not name the tenant", which is the difference between a closed question and
    an open one."""
    mod = _generator()

    cfg = mod.to_source({
        "entity_id": "sch-pinellas-county-school-district",
        "name": "Pinellas County School District",
        "platform": "opengov",
        "portal_url": "https://procurement.opengov.com/portal/embed/pcsb",
        "confidence": "strong",
    })

    assert cfg is not None
    assert cfg["opengov_code"] == "pcsb"


def test_the_fingerprinter_keeps_the_tenant_off_an_embed_url():
    """The truncation started here: `portal_url_for` recorded
    `.../portal/embed` and threw the tenant away, so nothing downstream could
    recover it however good its own pattern was."""
    html = (
        '<iframe src="https://procurement.opengov.com/portal/embed/pcsb'
        '/project-list?departmentId=all&status=all"></iframe>'
    )

    url = fp.portal_url_for("opengov", html, "https://www.pcsb.org")

    assert url == "https://procurement.opengov.com/portal/embed/pcsb"


def test_a_non_tenant_cannot_claim_an_identity_and_hide_others():
    """The damage was never the bogus source — the probe 404s it and drops it.
    It was that `embed` got *claimed*, so the next agency whose fingerprint
    landed on an embed URL was skipped as "already configured" with no line in
    the report. Two were. This is that, one level down from the host-matching
    bug the module's docstring already records."""
    mod = _generator()

    rows = [
        {"entity_id": f"sd-{n}", "name": f"Agency {n}", "platform": "opengov",
         "portal_url": "https://procurement.opengov.com/portal/embed",
         "confidence": "strong"}
        for n in ("one", "two")
    ]

    assert [mod.to_source(r) for r in rows] == [None, None]


def test_coverage_is_checked_on_identity_as_well_as_on_name():
    """Three of the redundant pointers are invisible to a name match. The
    OpenGov discoverer names its sources after the tenant — `og_pcsb`, not
    "Pinellas County School District" — so a string comparison reports an
    agency we read every day as an uncovered gap. Checking the tenant the
    entity's own fingerprint implies is what catches them."""
    import scripts.recover_catalog_coverage as rec

    entities = {
        "sch-pinellas-county-school-district",
        "sd-central-florida-expressway-authority",
        "co-hernando-county",
    }

    found = rec.covered_tenants(entities)

    assert set(found) == entities, f"missed: {sorted(entities - set(found))}"
    assert found["sch-pinellas-county-school-district"].endswith("#pcsb")


def test_the_identity_check_borrows_the_generator_rather_than_copying_it():
    """Deciding whether two rows are the same agency has been got wrong twice —
    on host alone, and on `/portal/embed`. A second copy of that judgement is
    how it gets got wrong a third time."""
    import scripts.recover_catalog_coverage as rec

    gen = rec._load_generator()

    assert hasattr(gen, "identity") and hasattr(gen, "to_source")
    assert "opengov" in gen.PLATFORM_ADAPTERS


def test_award_readers_do_not_count_as_coverage():
    """Legistar publishes what a commission already decided. It is good
    intelligence and no help at all in finding something to bid on, so an
    agency read only by Legistar still has an open-solicitation gap."""
    import scripts.recover_catalog_coverage as rec

    assert "legistar" not in rec.BID_ADAPTERS
    assert "fdot_letting" not in rec.BID_ADAPTERS
    assert "miami_dade_awards" not in rec.BID_ADAPTERS
    assert "civicplus" in rec.BID_ADAPTERS
