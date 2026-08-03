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
from src.sources.mfmp_vbs import PAGE_SIZE, MfmpVbsAdapter

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
    # One search per biddable type, each carrying exactly one type filter.
    assert len(searches) == 6
    assert all(len(c["body"]["type"]) == 1 for c in searches)
    # 6 types x 3 rows, all distinct.
    assert len(opps) == 18
    assert len({o.opportunity_id for o in opps}) == 18


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
    def responder(url, body, expect_json):
        if url.endswith("/count"):
            return "0"
        tid = body["type"][0]["id"]
        return [_row(int(tid), tid)]

    assert len(_FakeAdapter(CFG, responder).fetch()) == 6
    assert len(_FakeAdapter({**CFG, "include_notices": True}, responder).fetch()) == 10


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
