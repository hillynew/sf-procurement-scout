"""MyFloridaMarketPlace adapter — the statewide source.

Two failure modes are worth pinning, because both are silent in production:

* the public API caps results at 100 and ignores ``pageNumber``, so a caller
  that trusts the paging contract truncates and calls it a complete day;
* the rate limiter answers with HTTP 200 carrying the SPA's HTML, which parses
  as "no bids posted" unless you look for it.
"""

from __future__ import annotations

import pytest

from src.http_util import SourceBlocked
from src.models.opportunity import SolicitationType
from src.sources.mfmp_vbs import AWARD_TYPES, BIDDABLE_TYPES, PAGE_SIZE, MfmpVbsAdapter

CFG = {
    "id": "mfmp_vbs",
    "name": "MyFloridaMarketPlace (State of Florida)",
    "county": "statewide",
    "agency": "State of Florida",
    "portal_url": "https://vendor.myfloridamarketplace.com/search/bids",
    "adapter": "mfmp_vbs",
}


def _row(ad_id: int, type_id: str = "4", **kw):
    row = {
        "advertisementId": ad_id,
        "agencyAdNumber": f"REF-{ad_id}",
        "title": f"Advertisement {ad_id}",
        "typeId": type_id,
        "type": "Invitation to Bid",
        "status": "OPEN",
        "closeDate": "2026-09-01T15:00:00.000+00:00",
        "publishDate": "2026-08-01T12:00:00.000+00:00",
        "organization": {"name": "Department of Health (DOH)", "shortName": "DOH"},
        "agency": "Department of Health (DOH)",
    }
    row.update(kw)
    return row


class _FakeAdapter(MfmpVbsAdapter):
    """Adapter with the network replaced by a scripted responder."""

    def __init__(self, cfg, responder):
        super().__init__(cfg)
        self._responder = responder
        self.calls: list[dict] = []

    def _session(self):
        return object()

    def _pace(self):  # no sleeping in tests
        return None

    def _post(self, s, url, body, *, expect_json=True):
        self.calls.append({"url": url, "body": body})
        return self._responder(url, body, expect_json)

    def _get(self, s, url):
        self.calls.append({"url": url, "body": None})
        return self._responder(url, None, True)


def test_slices_by_type_rather_than_paging():
    """One query per advertisement type; pageNumber is never relied on."""
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "3"
        type_id = body["type"][0]["id"]
        return [_row(int(type_id) * 100 + i, type_id) for i in range(3)]

    a = _FakeAdapter(CFG, responder)
    opps = a.fetch()

    searches = [c for c in a.calls if c["url"].endswith("/bids")]
    # One search per type we pull — the six biddable ones plus Agency Decision,
    # each carrying exactly one type filter.
    assert len(searches) == len(BIDDABLE_TYPES) + len(AWARD_TYPES) == 7
    assert all(len(c["body"]["type"]) == 1 for c in searches)
    assert {c["body"]["type"][0]["id"] for c in searches} == BIDDABLE_TYPES | AWARD_TYPES
    # 7 types x 3 rows, all distinct.
    assert len(opps) == 21
    assert len({o.opportunity_id for o in opps}) == 21


def test_a_capped_slice_is_sub_sliced_by_agency():
    """Exactly PAGE_SIZE rows means truncation, not a tidy coincidence."""
    orgs = [{"id": "30000001", "value": "Agency One"},
            {"id": "30000002", "value": "Agency Two"}]

    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "500"
        if url.endswith("picklistOrg"):
            return orgs
        if body["type"][0]["id"] != "4":
            return []
        if not body["agency"]:
            return [_row(i) for i in range(1, PAGE_SIZE + 1)]  # capped
        # Each agency contributes one row the capped page never showed.
        offset = 900 + int(body["agency"][0]["id"][-1])
        return [_row(offset)]

    a = _FakeAdapter(CFG, responder)
    opps = a.fetch()

    ids = {(o.raw or {}).get("advertisementId") for o in opps}
    assert 901 in ids and 902 in ids, "sub-slice results were dropped"
    assert len(ids) == PAGE_SIZE + 2


def test_a_short_slice_is_not_sub_sliced():
    """The expensive per-agency sweep must not run when it is not needed."""
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "5"
        if url.endswith("picklistOrg"):
            pytest.fail("sub-slice ran for an uncapped result")
        return [_row(1)]

    assert len(_FakeAdapter(CFG, responder).fetch()) == 1


def test_notices_are_excluded_unless_asked_for():
    """Meeting and informational notices stay out; intended decisions do not.

    Agency Decision used to sit in this bucket, which meant the highest-value
    event in the system was never fetched by any configuration we ship.
    """
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "0"
        tid = body["type"][0]["id"]
        return [_row(int(tid), tid)]

    default = _FakeAdapter(CFG, responder).fetch()
    assert len(default) == len(BIDDABLE_TYPES) + len(AWARD_TYPES)
    assert any(o.status == "award" for o in default), "intended decisions must always be pulled"

    with_notices = _FakeAdapter({**CFG, "include_notices": True}, responder).fetch()
    assert len(with_notices) == 10


def test_the_portal_stated_type_beats_the_title_guess():
    """The API states the type outright, so we never infer it from wording."""
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "1"
        if body["type"][0]["id"] != "6":
            return []
        # A title that reads like an ITB, posted as an RFP.
        return [_row(7, "6", title="Invitation to Bid for Janitorial Supplies")]

    opps = _FakeAdapter(CFG, responder).fetch()
    assert len(opps) == 1
    assert opps[0].solicitation_type == SolicitationType.RFP.value


def test_html_response_is_treated_as_rate_limiting_not_as_no_results():
    """The failure this guards is silent: HTTP 200 with the SPA shell."""
    class Resp:
        status_code = 200
        text = "<!DOCTYPE html><html><head><title>MFMP</title></head></html>"

        def raise_for_status(self):
            return None

    a = MfmpVbsAdapter(CFG)
    with pytest.raises(SourceBlocked, match="rate limiter"):
        a._decode(Resp(), "https://vendor.myfloridamarketplace.com/x", True)


def test_state_agencies_land_statewide_but_counties_keep_their_county():
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "2"
        if body["type"][0]["id"] != "4":
            return []
        return [
            _row(1, agency="Department of Health (DOH)"),
            _row(2, agency="St. Johns County - Purchasing Department"),
        ]

    by_id = {
        (o.raw or {}).get("advertisementId"): o
        for o in _FakeAdapter(CFG, responder).fetch()
    }
    assert by_id[1].county == "statewide"
    assert by_id[2].county == "st-johns"


def test_zero_rows_is_reported_as_a_fault_not_a_quiet_success():
    """The state always has something open, so empty means something broke."""
    a = MfmpVbsAdapter(CFG)
    assert a.allows_empty is False


def test_pacing_serializes_across_threads():
    """The detail pass shares one adapter across a thread pool.

    Before the lock, every worker read the same `_last_call`, each concluded it
    had waited long enough, and they fired as one burst — which is precisely
    what trips the VIP limiter. The limiter answers 200 with HTML, `_decode`
    raises SourceBlocked, `fetch_detail` swallows it, and the bid ends up with
    no documents at all. So this asserts on the gaps between calls, not on the
    presence of a lock.
    """
    import threading
    import time as _time
    from concurrent.futures import ThreadPoolExecutor

    a = MfmpVbsAdapter(CFG)
    # Keep the test quick; the invariant under test is "serialized", not "2s".
    import src.sources.mfmp_vbs as mod

    original = mod.PACE_SECONDS
    mod.PACE_SECONDS = 0.05
    try:
        stamps: list[float] = []
        guard = threading.Lock()

        def call() -> None:
            a._pace()
            with guard:
                stamps.append(_time.monotonic())

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: call(), range(8)))
    finally:
        mod.PACE_SECONDS = original

    stamps.sort()
    gaps = [b - a_ for a_, b in zip(stamps, stamps[1:])]
    assert len(gaps) == 7
    # Allow scheduler slop, but a burst would show gaps at ~0.
    assert all(g > 0.02 for g in gaps), f"requests bunched up: {gaps}"


def test_session_is_built_once_under_concurrency():
    """Two sessions would double the request rate the pacing exists to hold."""
    from concurrent.futures import ThreadPoolExecutor

    a = MfmpVbsAdapter(CFG)
    with ThreadPoolExecutor(max_workers=8) as pool:
        sessions = list(pool.map(lambda _: a._session(), range(8)))
    assert len({id(s) for s in sessions}) == 1
