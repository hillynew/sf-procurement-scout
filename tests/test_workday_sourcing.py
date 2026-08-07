"""Workday Strategic Sourcing: the CSRF header, the two hosts, and the test event."""

from __future__ import annotations

import pytest

from src.sources.workday_sourcing import (
    PAGE_SIZE,
    QUERY,
    XSRF_COOKIE,
    XSRF_HEADER,
    WorkdaySourcingAdapter,
)

CFG = {
    "id": "wss_unf",
    "name": "University of North Florida (Workday Strategic Sourcing)",
    "county": "duval",
    "agency": "University of North Florida",
    "portal_url": "https://unf.public-portal.us.workdayspend.com/opportunities",
    "workday_tenant": "unf",
}

TOKEN = "G4DzpwdacLg3cr0SxO2sSCQ1LvQlq1jbjhGVc7Ew1EN7zcs0Qc"


def _event(eid="785", project="162", title="RFQ-27-01 Wellness Center Phase II A&E Services",
           deadline="2026-09-01T18:00:00.000Z", published="2026-07-30T12:18:18.396Z",
           kind="RFQ", state="PUBLISHED", restricted=False, codes=None):
    return {
        "id": eid, "projectId": project, "title": title,
        "bidSubmissionDeadline": deadline, "publishedAt": published,
        "requestType": kind, "state": state, "translatedState": "Open",
        "restricted": restricted, "commodityCodes": codes or [],
        "bidUrl": f"https://unf.us.workdayspend.com/rfps/public/{eid}",
    }


def _adapter(monkeypatch, pages, *, cookie=TOKEN):
    """Serve `pages` as successive GraphQL responses."""
    a = WorkdaySourcingAdapter(CFG)
    seen = {"posts": [], "gets": []}

    class Jar:
        def get(self, name):
            return cookie

    class FakeSession:
        cookies = Jar()

        def post(self, url, json=None, headers=None, timeout=None):
            seen["posts"].append({"url": url, "json": json, "headers": headers})
            i = min(len(seen["posts"]) - 1, len(pages) - 1)
            return type("R", (), {
                "json": lambda self=None, _p=pages[i]: _p,
                "raise_for_status": lambda self=None: None,
                "status_code": 200,
            })()

    def fake_get(url, **kwargs):
        seen["gets"].append(url)
        return type("R", (), {"text": "<html></html>"})()

    monkeypatch.setattr("src.sources.workday_sourcing.get", fake_get)
    monkeypatch.setattr("src.sources.workday_sourcing.check", lambda url: None)
    monkeypatch.setattr(WorkdaySourcingAdapter, "_session", lambda self: FakeSession())
    return a, seen


def _payload(nodes, *, has_next=False, cursor=None):
    return {"data": {"events": {
        "nodes": nodes,
        "pageInfo": {"endCursor": cursor, "hasNextPage": has_next},
        "totalCount": len(nodes),
    }}}


# -- the CSRF handshake ----------------------------------------------------


def test_the_token_goes_in_the_header_the_portal_actually_wants(monkeypatch):
    """`X-CSRF-Token` and `X-Csrf-Token` both return 422 with an empty error
    body, which reads as a malformed query rather than a missing header."""
    a, seen = _adapter(monkeypatch, [_payload([_event()])])
    a.fetch()

    headers = seen["posts"][0]["headers"]
    assert headers[XSRF_HEADER] == TOKEN
    assert "X-CSRF-Token" not in headers


def test_the_token_is_url_decoded(monkeypatch):
    """The cookie is percent-encoded; the header wants the raw value."""
    a, seen = _adapter(monkeypatch, [_payload([])], cookie="abc%2Fdef%3D%3D")
    a.fetch()

    assert seen["posts"][0]["headers"][XSRF_HEADER] == "abc/def=="


def test_the_cookie_is_picked_up_before_the_query(monkeypatch):
    a, seen = _adapter(monkeypatch, [_payload([])])
    a.fetch()

    assert seen["gets"] == ["https://unf.public-portal.us.workdayspend.com/opportunities"]


def test_no_cookie_is_reported_rather_than_queried_anyway(monkeypatch):
    a, seen = _adapter(monkeypatch, [_payload([])], cookie=None)

    assert a.fetch() == []
    assert seen["posts"] == []
    assert a.degraded_reason and "CSRF cookie" in a.degraded_reason


def test_the_cookie_name_is_the_portals(monkeypatch):
    assert XSRF_COOKIE == "_pp_xsrf"


# -- the query -------------------------------------------------------------


def test_the_input_argument_is_sent_even_though_it_is_empty(monkeypatch):
    """`input` is `EventInput!` — non-null — so omitting it is a hard error,
    while an empty object means "no filter"."""
    a, seen = _adapter(monkeypatch, [_payload([_event()])])
    a.fetch()

    variables = seen["posts"][0]["json"]["variables"]
    assert variables["input"] == {}
    assert variables["first"] == PAGE_SIZE
    assert "EventInput!" in QUERY


def test_pages_are_followed(monkeypatch):
    first = _payload([_event(eid="1", project="1")], has_next=True, cursor="CUR")
    second = _payload([_event(eid="2", project="2")])
    a, seen = _adapter(monkeypatch, [first, second])
    opps = a.fetch()

    assert len(seen["posts"]) == 2
    assert seen["posts"][1]["json"]["variables"]["after"] == "CUR"
    assert {o.external_id for o in opps} == {"1", "2"}


def test_paging_stops_when_the_cursor_runs_out(monkeypatch):
    """`hasNextPage` true with no cursor would otherwise loop to the cap."""
    a, seen = _adapter(monkeypatch, [_payload([_event()], has_next=True, cursor=None)])
    a.fetch()

    assert len(seen["posts"]) == 1


def test_a_graphql_error_is_reported_with_its_message(monkeypatch):
    a, _ = _adapter(monkeypatch, [{"errors": [{"message": "Field 'events' is missing required arguments: input"}]}])

    assert a.fetch() == []
    assert a.degraded_reason and "missing required arguments" in a.degraded_reason


def test_an_unreachable_portal_is_reported(monkeypatch):
    a = WorkdaySourcingAdapter(CFG)

    def boom(url, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr("src.sources.workday_sourcing.get", boom)
    monkeypatch.setattr(WorkdaySourcingAdapter, "_session", lambda self: None)
    assert a.fetch() == []
    assert a.degraded_reason and "portal page" in a.degraded_reason


def test_a_missing_tenant_is_a_config_error():
    cfg = {k: v for k, v in CFG.items() if k != "workday_tenant"}
    with pytest.raises(ValueError, match="workday_tenant"):
        WorkdaySourcingAdapter(cfg).fetch()


# -- mapping ---------------------------------------------------------------


def test_a_published_event_becomes_an_open_opportunity(monkeypatch):
    a, _ = _adapter(monkeypatch, [_payload([_event()])])
    (opp,) = a.fetch()

    assert opp.status == "open"
    assert opp.external_id == "162"
    assert opp.due_date is not None and opp.due_date.month == 9
    assert opp.posted_date is not None and opp.posted_date.month == 7
    assert opp.title.startswith("RFQ-27-01")


@pytest.mark.parametrize("state,expected", [
    ("PUBLISHED", "open"),
    ("CLOSED", "closed"),
    ("AWARDED", "award"),
    ("CANCELLED", "cancelled"),
])
def test_every_state_maps(monkeypatch, state, expected):
    a, _ = _adapter(monkeypatch, [_payload([_event(state=state)])])
    opps = a.fetch() if expected == "open" else a.fetch_history()

    assert opps and opps[0].status == expected


def test_an_unknown_state_is_treated_as_closed(monkeypatch):
    """The safe direction: a false alarm on the board is worse than a miss."""
    a, _ = _adapter(monkeypatch, [_payload([_event(state="SOMETHING_NEW")])])

    assert a.fetch() == []
    assert len(a.fetch_history()) == 1


def test_commodity_codes_become_keywords(monkeypatch):
    """A vendor knows their own NIGP classification by its number."""
    a, _ = _adapter(monkeypatch, [_payload([_event(codes=["NIGP - 00500", "NIGP - 00505"])])])
    (opp,) = a.fetch()

    assert "NIGP - 00500" in opp.keywords
    assert "NIGP - 00505" in opp.keywords


def test_an_untitled_event_is_skipped(monkeypatch):
    a, _ = _adapter(monkeypatch, [_payload([_event(title="")])])
    assert a.fetch() == []


# -- what must never reach a board -----------------------------------------


def test_a_test_event_is_not_a_solicitation(monkeypatch):
    """St. Johns County's portal currently holds exactly one record — a TEST
    event from their migration, titled "Testing Solicitation for Suppliers".
    Shipping that to someone's bid board is worse than shipping nothing.
    """
    a, _ = _adapter(monkeypatch, [_payload([
        _event(kind="TEST", title="Testing Solicitation for Suppliers")])])

    assert a.fetch() == []
    assert a.fetch_history() == []


def test_an_invitation_only_event_is_not_an_opportunity(monkeypatch):
    """A bid you cannot respond to is not one."""
    a, _ = _adapter(monkeypatch, [_payload([_event(restricted=True)])])
    assert a.fetch() == []


def test_a_tenant_that_published_only_a_test_says_so(monkeypatch):
    """Distinguishes "this agency is mid-migration" from "this is broken"."""
    a, _ = _adapter(monkeypatch, [_payload([_event(kind="TEST")])])
    a.fetch()

    assert a.empty_note == "the portal published only 1 test event"
    assert a.degraded_reason is None


def test_the_count_is_pluralised(monkeypatch):
    a, _ = _adapter(monkeypatch, [_payload([
        _event(eid="1", kind="TEST"), _event(eid="2", kind="TEST")])])
    a.fetch()

    assert a.empty_note == "the portal published only 2 test events"


def test_a_real_bid_alongside_a_test_leaves_no_note(monkeypatch):
    a, _ = _adapter(monkeypatch, [_payload([_event(eid="1"), _event(eid="2", kind="TEST")])])

    assert len(a.fetch()) == 1
    assert a.empty_note is None


# -- the two hosts ---------------------------------------------------------


def test_only_the_public_portal_host_is_ever_fetched(monkeypatch):
    """`<tenant>.public-portal.us.workdayspend.com` serves no robots.txt.
    `<tenant>.us.workdayspend.com` is the authenticated app and serves
    `Disallow: /`. They are one word apart and opposite in what they permit.
    """
    a, seen = _adapter(monkeypatch, [_payload([_event()])])
    a.fetch()

    for url in seen["gets"] + [p["url"] for p in seen["posts"]]:
        assert ".public-portal.us.workdayspend.com" in url


def test_the_bid_link_points_at_the_host_we_do_not_crawl(monkeypatch):
    """Handing a person a URL their browser opens is not the same act as
    crawling it, so `bidUrl` is carried as a link and never fetched."""
    a, seen = _adapter(monkeypatch, [_payload([_event()])])
    (opp,) = a.fetch()

    assert opp.url == "https://unf.us.workdayspend.com/rfps/public/785"
    assert opp.url not in seen["gets"]
    assert WorkdaySourcingAdapter.supports_detail is False


def test_an_event_without_a_bid_url_falls_back_to_the_public_board(monkeypatch):
    node = _event()
    node["bidUrl"] = ""
    a, _ = _adapter(monkeypatch, [_payload([node])])
    (opp,) = a.fetch()

    assert opp.url.endswith(".public-portal.us.workdayspend.com/opportunities")


def test_the_public_portal_is_not_in_the_override_table():
    """It needs no override — it serves no robots.txt at all. An entry here
    would be an exception taken for a host that never restricted us."""
    from src.netpolicy import ROBOTS_OVERRIDES

    assert not any("workdayspend" in host for host in ROBOTS_OVERRIDES)
