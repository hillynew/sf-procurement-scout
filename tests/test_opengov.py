"""OpenGov adapter: paging, the open/closed split, documents, tenant discovery."""

from __future__ import annotations

import pytest

from src.sources.opengov import API, OpenGovAdapter, fl_tenants

CFG = {
    "id": "og_orangecountyfl",
    "name": "Orange County (OpenGov)",
    "county": "orange",
    "agency": "Orange County",
    "portal_url": "https://procurement.opengov.com/portal/orangecountyfl",
    "opengov_code": "orangecountyfl",
}


def _row(pid=1, title="Roof Replacement", status="open", ref="ITB-24-001", **extra):
    row = {
        "id": pid,
        "title": title,
        "status": status,
        "financialId": ref,
        "releaseProjectDate": "2026-08-01T04:00:00.000Z",
        "proposalDeadline": "2026-09-15T15:00:00.000Z",
        "summary": "<p>Replace the roof.</p>",
        "department": {"id": 3, "name": "Public Works"},
    }
    row.update(extra)
    return row


def _stub(monkeypatch, *, pages=None, detail=None, addenda=None):
    """Wire the adapter's two transport methods to canned payloads."""
    pages = pages or []
    calls = {"post": [], "get": []}

    def fake_post(self, url, body):
        calls["post"].append((url, body))
        page = body["page"]
        return pages[page] if page < len(pages) else {"count": 0, "rows": []}

    def fake_get(self, url):
        calls["get"].append(url)
        if url.endswith("/addendums"):
            return addenda if addenda is not None else []
        return detail or {}

    monkeypatch.setattr(OpenGovAdapter, "_post", fake_post)
    monkeypatch.setattr(OpenGovAdapter, "_get", fake_get)
    monkeypatch.setattr(OpenGovAdapter, "_pace", lambda self: None)
    return calls


def test_fetch_returns_only_open_projects(monkeypatch):
    _stub(
        monkeypatch,
        pages=[
            {
                "count": 3,
                "rows": [
                    _row(1, "Open Bid", "open"),
                    _row(2, "Being Evaluated", "evaluation"),
                    _row(3, "Long Gone", "closed"),
                ],
            }
        ],
    )
    opps = OpenGovAdapter(CFG).fetch()

    assert [o.title for o in opps] == ["Open Bid"]
    assert opps[0].status == "open"


def test_history_returns_everything_not_open(monkeypatch):
    """Evaluation and award-pending are closed for submissions, so they are history."""
    _stub(
        monkeypatch,
        pages=[
            {
                "count": 3,
                "rows": [
                    _row(1, "Open Bid", "open"),
                    _row(2, "Being Evaluated", "evaluation"),
                    _row(3, "Awarding", "awardPending"),
                ],
            }
        ],
    )
    history = OpenGovAdapter(CFG).fetch_history()

    assert sorted(o.title for o in history) == ["Awarding", "Being Evaluated"]
    assert {o.status for o in history} == {"closed"}


def test_row_maps_onto_the_opportunity_fields(monkeypatch):
    _stub(monkeypatch, pages=[{"count": 1, "rows": [_row()]}])
    (opp,) = OpenGovAdapter(CFG).fetch()

    assert opp.external_id == "ITB-24-001"
    assert opp.agency == "Orange County"
    assert opp.department == "Public Works"
    assert opp.url == "https://procurement.opengov.com/portal/orangecountyfl/projects/1"
    assert opp.due_date is not None and opp.due_date.year == 2026
    assert opp.posted_date is not None
    # The summary is rich text; it must reach the model as prose.
    assert opp.description == "Replace the roof."


def test_paging_walks_until_the_count_is_covered(monkeypatch):
    full = [_row(i, f"Bid {i}") for i in range(100)]
    calls = _stub(
        monkeypatch,
        pages=[
            {"count": 150, "rows": full},
            {"count": 150, "rows": [_row(i, f"Bid {i}") for i in range(100, 150)]},
        ],
    )
    opps = OpenGovAdapter(CFG).fetch()

    assert len(opps) == 150
    assert [body["page"] for _url, body in calls["post"]] == [0, 1]


def test_a_row_repeated_across_pages_is_not_duplicated(monkeypatch):
    """A project published mid-crawl shifts the sort, so pages can overlap."""
    page0 = [_row(i, f"Bid {i}") for i in range(100)]
    page1 = [_row(99, "Bid 99"), _row(100, "Bid 100")]
    _stub(
        monkeypatch,
        pages=[{"count": 101, "rows": page0}, {"count": 101, "rows": page1}],
    )
    opps = OpenGovAdapter(CFG).fetch()

    assert len(opps) == 101
    assert len({o.url for o in opps}) == 101


def test_paging_stops_on_a_short_page(monkeypatch):
    calls = _stub(monkeypatch, pages=[{"count": 999, "rows": [_row()]}])
    OpenGovAdapter(CFG).fetch()

    assert len(calls["post"]) == 1


def test_detail_pulls_scope_contact_and_the_bid_packet(monkeypatch):
    _stub(
        monkeypatch,
        pages=[{"count": 1, "rows": [_row()]}],
        detail={
            "summary": "<p>Full scope of work, at length.</p>",
            "department": {"name": "Utilities, Engineering"},
            "questionDeadline": "2026-08-20T15:00:00.000Z",
            "contact": {"firstName": "Dana", "lastName": "Reyes", "email": "dana@ocfl.net"},
            "documentAttachment": {
                "url": "https://government-project.s3.us-west-2.amazonaws.com/1/packet.pdf?X-Amz-Expires=72000",
                "filename": "packet.pdf",
            },
            "attachments": [
                {"url": "https://government-project.s3.us-west-2.amazonaws.com/1/drawings.pdf", "filename": "drawings.pdf"}
            ],
        },
    )
    adapter = OpenGovAdapter(CFG)
    (opp,) = adapter.fetch()
    adapter.fetch_detail(opp)

    assert opp.detail_fetched
    assert opp.scope == "Full scope of work, at length."
    assert opp.department == "Utilities, Engineering"
    assert opp.contact == "Dana Reyes — dana@ocfl.net"
    assert opp.questions_due is not None
    assert [d.name for d in opp.documents] == ["packet.pdf", "drawings.pdf"]


def test_addenda_are_documents_of_their_own_kind(monkeypatch):
    _stub(
        monkeypatch,
        pages=[{"count": 1, "rows": [_row()]}],
        detail={"summary": "Scope"},
        addenda=[
            {
                "title": "Addendum 1 — revised due date",
                "documentAttachment": {"url": "https://government-project.s3.us-west-2.amazonaws.com/1/add1.pdf"},
            }
        ],
    )
    adapter = OpenGovAdapter(CFG)
    (opp,) = adapter.fetch()
    adapter.fetch_detail(opp)

    (doc,) = opp.documents
    assert doc.kind == "addendum"
    assert doc.is_addendum
    assert doc.name == "Addendum 1 — revised due date"


def test_the_same_object_signed_twice_is_one_document(monkeypatch):
    """Two records can point at one file with different presigned signatures."""
    url = "https://government-project.s3.us-west-2.amazonaws.com/1/packet.pdf"
    _stub(
        monkeypatch,
        pages=[{"count": 1, "rows": [_row()]}],
        detail={
            "documentAttachment": {"url": f"{url}?X-Amz-Date=20260806T160129Z", "filename": "packet.pdf"},
            "attachments": [{"url": f"{url}?X-Amz-Date=20260806T170000Z", "filename": "packet.pdf"}],
        },
    )
    adapter = OpenGovAdapter(CFG)
    (opp,) = adapter.fetch()
    adapter.fetch_detail(opp)

    assert len(opp.documents) == 1


def test_a_failed_detail_leaves_the_listing_intact(monkeypatch):
    _stub(monkeypatch, pages=[{"count": 1, "rows": [_row()]}])

    def boom(self, url):
        raise RuntimeError("500")

    monkeypatch.setattr(OpenGovAdapter, "_get", boom)
    adapter = OpenGovAdapter(CFG)
    (opp,) = adapter.fetch()
    adapter.fetch_detail(opp)

    assert opp.title == "Roof Replacement"
    assert not opp.detail_fetched


def test_missing_tenant_code_is_a_config_error(monkeypatch):
    cfg = dict(CFG)
    cfg.pop("opengov_code")
    with pytest.raises(ValueError, match="opengov_code"):
        OpenGovAdapter(cfg).fetch()


def test_the_list_endpoint_is_posted_not_fetched(monkeypatch):
    """A GET of this path 404s — which is how the platform gets written off."""
    calls = _stub(monkeypatch, pages=[{"count": 1, "rows": [_row()]}])
    OpenGovAdapter(CFG).fetch()

    (url, body), = calls["post"]
    assert url == f"{API}/government/orangecountyfl/project/public"
    assert body["limit"] == 100 and body["sortField"] == "releaseProjectDate"


# -- tenant discovery ------------------------------------------------------


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fl_tenants_filters_to_active_florida_and_reads_the_nested_slug(monkeypatch):
    payload = [
        {"name": "Orange County", "state": "FL", "isActive": True, "city": "Orlando",
         "website": "https://ocfl.net", "government": {"code": "orangecountyfl"}},
        {"name": "Retired City", "state": "FL", "isActive": False,
         "government": {"code": "retired"}},
        {"name": "City of Phoenix", "state": "AZ", "isActive": True,
         "government": {"code": "phoenix"}},
        {"name": "No Slug", "state": "FL", "isActive": True, "government": {}},
    ]

    class _S:
        headers: dict = {}

        def get(self, url, timeout=None):
            assert url.endswith("/government")
            return _Resp(payload)

    monkeypatch.setattr("src.sources.opengov.session", lambda: _S())
    tenants = fl_tenants()

    assert [t["code"] for t in tenants] == ["orangecountyfl"]
    assert tenants[0]["name"] == "Orange County"


def test_fl_tenants_can_include_inactive(monkeypatch):
    payload = [
        {"name": "Retired City", "state": "FL", "isActive": False,
         "government": {"code": "retired"}},
    ]

    class _S:
        headers: dict = {}

        def get(self, url, timeout=None):
            return _Resp(payload)

    monkeypatch.setattr("src.sources.opengov.session", lambda: _S())

    assert fl_tenants() == []
    assert [t["code"] for t in fl_tenants(include_inactive=True)] == ["retired"]


def test_pacing_is_shared_across_adapters_not_per_instance(monkeypatch):
    """Ninety-one tenants share one API host; per-instance pacing would not hold."""
    import src.sources.opengov as og

    slept: list = []
    monkeypatch.setattr(og.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(og, "_last_request", 0.0)

    clock = iter([100.0, 100.0, 100.1, 100.1])
    monkeypatch.setattr(og.time, "monotonic", lambda: next(clock))

    og._pace_host()  # first call sets the clock, no wait
    og._pace_host()  # a *different* caller 0.1s later must still be held back

    assert slept and slept[-1] == pytest.approx(0.9, abs=0.01)
