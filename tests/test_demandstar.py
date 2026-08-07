"""DemandStar: the public half of the API, and where the adapter stops.

The research said this platform was "useful as a fingerprinting oracle, not as
a data source", on the reading that only agency names and titles are public.
Half right — the detail view and the agency directory both answer 401, but the
listing is open JSON carrying identifier, dates and a status specific enough to
separate an open bid from an intended award.

Nothing here touches the network; the payloads are shaped like the real ones,
including the doubled solicitation type DemandStar writes into `bidIdentifier`.
"""

from __future__ import annotations

import pytest

from src.sources.demandstar import API, BID_PAGE, STATUS, WINDOW, DemandStarAdapter

GUID = "f27e1be6-883d-4b92-8fa8-fa0cfcf667b7"

CFG = {
    "id": "ds_mdcps",
    "name": "Miami-Dade County Public Schools (Demandstar)",
    "county": "miami-dade",
    "agency": "Miami-Dade County Public Schools",
    "portal_url": (
        "https://www.demandstar.com/app/agencies/florida/"
        "miami-dade-county-public-schools/procurement-opportunities/" + GUID
    ),
    "demandstar_agency": GUID,
}


def _row(bid_id=542827, name="Districtwide Roof Replacement", status="AC",
         identifier="ITB-ITB-25-044-DR-0-2026/DR", due="09/03/2026",
         posted="07/16/2026"):
    return {
        "bidId": bid_id, "bidName": name, "bidIdentifier": identifier,
        "agency": "Miami-Dade County Public Schools", "broadCastDate": posted,
        "dueDate": due, "city": "Miami", "state": "FL", "postalCode": None,
        "planholders": "37", "watches": "0", "watchStatus": False,
        "internalStatus": "BR", "status": "Active", "statusType": status,
        "mi": 1909722,
    }


def _adapter(monkeypatch, rows, *, cfg=None, boom=None):
    seen = []

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def fake_get(url, **kw):
        seen.append(url)
        if boom is not None:
            raise boom
        return _Resp({"total": len(rows), "result": rows})

    monkeypatch.setattr("src.sources.demandstar.get", fake_get)
    return DemandStarAdapter(cfg or CFG), seen


# -- the public route ------------------------------------------------------


def test_one_get_reads_the_whole_agency(monkeypatch):
    a, seen = _adapter(monkeypatch, [_row()])
    a.fetch()

    assert seen == [f"{API}/agency/search?id={GUID}"]


def test_the_unauthenticated_base_is_the_one_used():
    """`urlNoAuth` in the app's own config — as clear a statement as a vendor
    makes about which half of its API is public."""
    assert API == "https://api.demandstar.com/contents"


def test_a_missing_guid_is_a_config_error_not_a_dead_portal(monkeypatch):
    """Resolved before the tolerant fetch, so a config mistake surfaces as one
    rather than as "the portal did not answer"."""
    cfg = {k: v for k, v in CFG.items() if k != "demandstar_agency"}
    a, _ = _adapter(monkeypatch, [], cfg=cfg)

    with pytest.raises(ValueError, match="demandstar_agency"):
        a.fetch()


def test_a_portal_that_does_not_answer_is_reported(monkeypatch):
    a, _ = _adapter(monkeypatch, [], boom=RuntimeError("timeout"))

    assert a.fetch() == []
    assert a.degraded_reason and "did not answer" in a.degraded_reason


def test_a_body_that_is_not_the_expected_json_is_reported(monkeypatch):
    class _Resp:
        def json(self):
            return ["unexpected"]

    monkeypatch.setattr("src.sources.demandstar.get", lambda url, **kw: _Resp())
    a = DemandStarAdapter(CFG)

    assert a.fetch() == []
    assert a.degraded_reason and "JSON expected" in a.degraded_reason


# -- status ----------------------------------------------------------------


def test_an_active_bid_is_open(monkeypatch):
    a, _ = _adapter(monkeypatch, [_row(status="AC")])
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.due_date is not None and opp.due_date.month == 9
    assert opp.posted_date is not None and opp.posted_date.month == 7


def test_under_evaluation_is_not_biddable(monkeypatch):
    """375 of the 839 rows across the 16 Florida agencies are `OP`. Shown as
    open they would be the majority of the board and none could be bid."""
    a, _ = _adapter(monkeypatch, [_row(status="OP")])

    assert a.fetch() == []
    assert [o.status for o in a.fetch_history()] == ["closed"]


@pytest.mark.parametrize("code,expected", [
    ("AC", "open"), ("OP", "closed"), ("RA", "award"),
    ("AW", "award"), ("CP", "closed"), ("CA", "cancelled"),
])
def test_every_status_seen_in_florida_maps(monkeypatch, code, expected):
    a, _ = _adapter(monkeypatch, [_row(status=code)])
    opps = a.fetch() if expected == "open" else a.fetch_history()

    assert opps and opps[0].status == expected


def test_a_recommendation_of_award_is_an_award_not_an_open_bid(monkeypatch):
    """A notice of intended decision. It stays out of every open-bid view
    because the thing to do with one is protest it, not respond to it."""
    a, _ = _adapter(monkeypatch, [_row(status="RA")])

    assert a.fetch() == []
    assert a.fetch_history()[0].status == "award"


def test_an_award_carries_no_protest_deadline(monkeypatch):
    """The only date on the row is the *advertisement*, and the 72-hour clock
    under s. 120.57(3)(b) runs from the posting of the intended decision. A
    deadline derived from the wrong date is worse than none — it would look
    authoritative."""
    a, _ = _adapter(monkeypatch, [_row(status="RA")])

    assert a.fetch_history()[0].protest_deadline is None


def test_an_unknown_status_is_treated_as_closed(monkeypatch):
    """The safe direction: a false alarm on the board is worse than a miss."""
    a, _ = _adapter(monkeypatch, [_row(status="ZZ")])

    assert a.fetch() == []
    assert len(a.fetch_history()) == 1


# -- mapping ---------------------------------------------------------------


def test_the_agencys_own_number_is_the_reference(monkeypatch):
    """What a vendor searches by, and what matches a bid to its past cycles."""
    a, _ = _adapter(monkeypatch, [_row(identifier="RFQu-RFQu 26-UT050-0-2026/JD")])
    (opp,) = a.fetch()

    assert "26-UT050" in opp.external_id


def test_a_row_with_no_identifier_falls_back_to_the_bid_id(monkeypatch):
    a, _ = _adapter(monkeypatch, [_row(identifier="")])
    (opp,) = a.fetch()

    assert opp.external_id


def test_an_untitled_row_is_skipped(monkeypatch):
    a, _ = _adapter(monkeypatch, [_row(name="")])

    assert a.fetch() == [] and a.fetch_history() == []


def test_the_raw_row_is_kept(monkeypatch):
    a, _ = _adapter(monkeypatch, [_row()])
    (opp,) = a.fetch()

    assert opp.raw["demandstar"]["bidId"] == 542827


# -- what the adapter must not do -----------------------------------------


def test_the_link_is_the_page_a_person_opens(monkeypatch):
    """`/bid/summary` answers 401, so there is no detail pass. The row's URL is
    handed to a browser, which renders it, and is never fetched here."""
    a, seen = _adapter(monkeypatch, [_row()])
    (opp,) = a.fetch()

    assert opp.url == BID_PAGE.format(bid_id=542827)
    assert opp.url not in seen
    assert DemandStarAdapter.supports_detail is False


def test_the_window_is_reported_rather_than_implied(monkeypatch):
    """`total` never exceeds 100 and every paging parameter is accepted and
    ignored, so a full page is the most recent 100 and not the archive."""
    a, _ = _adapter(monkeypatch, [_row(bid_id=i, status="AW") for i in range(WINDOW)])
    a.fetch_history()

    assert a.degraded_reason and "not the whole archive" in a.degraded_reason


def test_a_short_list_is_not_flagged(monkeypatch):
    a, _ = _adapter(monkeypatch, [_row(bid_id=i, status="AW") for i in range(7)])
    a.fetch_history()

    assert a.degraded_reason is None


def test_open_bids_are_never_flagged_as_a_truncated_archive(monkeypatch):
    """The window matters for history. An agency's open bids are a handful."""
    a, _ = _adapter(monkeypatch, [_row(bid_id=i) for i in range(WINDOW)])
    a.fetch()

    assert a.degraded_reason is None


def test_the_status_table_covers_what_florida_serves():
    assert set(STATUS) >= {"AC", "OP", "RA", "AW"}


# -- config ----------------------------------------------------------------


def test_the_generator_can_recover_the_tenant_from_a_landing_url():
    """There is no public agency directory — `/common/getAgencies` is a 401 —
    so a tenant is only ever identified by fingerprinting the agency's own
    site and reading the link it publishes."""
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "sff", root / "scripts" / "sources_from_fingerprints.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sff"] = mod
    spec.loader.exec_module(mod)

    cfg = mod.to_source({
        "entity_id": "sch-mdcps", "name": "Miami-Dade County Public Schools",
        "platform": "demandstar", "confidence": "strong",
        "portal_url": CFG["portal_url"], "checked_url": CFG["portal_url"],
    })

    assert cfg["adapter"] == "demandstar"
    assert cfg["demandstar_agency"] == GUID


def test_every_configured_demandstar_source_carries_a_guid():
    from src.sources.registry import load_source_config

    rows = [c for c in load_source_config()
            if isinstance(c, dict) and c.get("adapter") == "demandstar"]
    for cfg in rows:
        assert len(cfg.get("demandstar_agency") or "") == 36, cfg["id"]
