"""API endpoints against a demo-seeded database. No network, no React."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    # conftest's autouse fixture already pointed DATABASE_URL at a tmp SQLite.
    from web.server import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def seeded(client):
    resp = client.post("/api/demo")
    assert resp.status_code == 200
    assert resp.json()["seeded_pipeline"] is True
    return client


def first_untracked(client) -> dict:
    data = client.get("/api/opportunities").json()
    return next(o for o in data["opportunities"]
                if not o["tracked"] and o["status"] == "open")


def first_tracked(client) -> dict:
    data = client.get("/api/opportunities").json()
    return next(o for o in data["opportunities"] if o["tracked"])


# ---------------------------------------------------------------------------
# Health & snapshot
# ---------------------------------------------------------------------------


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body == {"status": "ok", "db": "ok"}


def test_opportunities_empty_then_demo(client):
    data = client.get("/api/opportunities").json()
    assert data["count"] == 0 and data["opportunities"] == []

    client.post("/api/demo")
    data = client.get("/api/opportunities").json()
    assert data["count"] > 10
    sample = data["opportunities"][0]
    for key in ("opportunity_id", "title", "county", "status", "budget_amount",
                "tracked", "stage", "has_summary", "detail_score"):
        assert key in sample


def test_opportunity_detail_and_404(seeded):
    opp = first_tracked(seeded)
    detail = seeded.get(f"/api/opportunities/{opp['opportunity_id']}").json()
    assert detail["title"] == opp["title"]
    assert "ai_summary" in detail
    assert seeded.get("/api/opportunities/nope").status_code == 404


def test_export_csv(seeded):
    resp = seeded.get("/api/export.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "opportunity_id" in resp.text.splitlines()[0]


# ---------------------------------------------------------------------------
# Bid workflow
# ---------------------------------------------------------------------------


def test_track_untrack_cycle(seeded):
    opp = first_untracked(seeded)
    oid = opp["opportunity_id"]

    tracked = seeded.post(f"/api/bids/{oid}/track").json()
    assert tracked["tracked"] is True and tracked["stage"] == "watching"

    untracked = seeded.delete(f"/api/bids/{oid}/track").json()
    assert untracked["tracked"] is False and untracked["stage"] is None

    assert seeded.post("/api/bids/bogus/track").status_code == 404


def test_stage_validation_and_move(seeded):
    oid = first_tracked(seeded)["opportunity_id"]
    ok = seeded.put(f"/api/bids/{oid}/stage", json={"stage": "submitted"}).json()
    assert ok["stage"] == "submitted"
    assert seeded.put(f"/api/bids/{oid}/stage",
                      json={"stage": "bogus"}).status_code == 422
    untracked = first_untracked(seeded)["opportunity_id"]
    assert seeded.put(f"/api/bids/{untracked}/stage",
                      json={"stage": "watching"}).status_code == 404


def test_go_decision_advances_stage(seeded):
    opp = first_untracked(seeded)
    oid = opp["opportunity_id"]
    seeded.post(f"/api/bids/{oid}/track")
    out = seeded.put(f"/api/bids/{oid}/decision", json={"decision": "go"}).json()
    assert out["decision"] == "go" and out["stage"] == "preparing"
    out = seeded.put(f"/api/bids/{oid}/decision", json={"decision": None}).json()
    assert out["decision"] is None


def test_checks_notes_result_archive(seeded):
    oid = first_tracked(seeded)["opportunity_id"]

    out = seeded.put(f"/api/bids/{oid}/checks", json={"index": 2, "checked": True}).json()
    assert out["checks"]["2"] is True

    out = seeded.put(f"/api/bids/{oid}/notes", json={"text": "call the buyer"}).json()
    assert out["notes"] == "call the buyer"

    out = seeded.put(f"/api/bids/{oid}/result",
                     json={"outcome": "won", "amount_cents": 1_500_000,
                           "notes": "squeaker"}).json()
    assert out["result"]["outcome"] == "won"
    assert out["result"]["amount_cents"] == 1_500_000
    assert out["stage"] == "result"

    assert seeded.put(f"/api/bids/{oid}/result",
                      json={"outcome": "maybe"}).status_code == 422

    out = seeded.post(f"/api/bids/{oid}/archive").json()
    assert out["archived"] is True
    out = seeded.delete(f"/api/bids/{oid}/archive").json()
    assert out["archived"] is False


def test_stale_v1_brief_is_not_served(seeded):
    """A brief cached under an old prompt version must be invisible to the UI."""
    from src.db import store as db

    oid = first_tracked(seeded)["opportunity_id"]
    db.put_summary(oid, "oldhash", "claude-haiku-4-5", 1,
                   {"what_the_work_is": "x", "red_flags": "<item>not a list</item>"},
                   input_chars=5)

    detail = seeded.get(f"/api/opportunities/{oid}").json()
    assert detail["ai_summary"] is None
    assert detail["has_summary"] is False
    assert seeded.get(f"/api/bids/{oid}/summary").status_code == 404


def test_summarize_without_key_is_503(seeded, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    oid = first_tracked(seeded)["opportunity_id"]
    resp = seeded.post(f"/api/bids/{oid}/summarize")
    assert resp.status_code == 503
    assert resp.json()["detail"]["reason"] == "no_api_key"
    assert seeded.get(f"/api/bids/{oid}/summary").status_code == 404


# ---------------------------------------------------------------------------
# Go Deep
# ---------------------------------------------------------------------------


def _wait_for_deep_dive(client, oid, tries=200):
    import time

    for _ in range(tries):
        body = client.get(f"/api/bids/{oid}/deep-dive").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("deep dive never finished")


def test_deep_dive_without_key_is_503(seeded, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    oid = first_tracked(seeded)["opportunity_id"]
    resp = seeded.post(f"/api/bids/{oid}/deep-dive")
    assert resp.status_code == 503
    assert resp.json()["detail"]["reason"] == "no_api_key"
    assert seeded.get("/api/bids/nope/deep-dive").status_code == 404


def test_deep_dive_lifecycle(seeded, monkeypatch):
    from src.ai import deep_dive

    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    monkeypatch.setattr(deep_dive, "_call_claude", lambda model, text: {
        "overview": "Big roof job.",
        "dollar_amounts": [{"label": "Estimate", "amount": "$2M"}],
        "red_flags": "not-a-list",   # normalizer must coerce
    })
    oid = first_tracked(seeded)["opportunity_id"]

    assert seeded.get(f"/api/bids/{oid}/deep-dive").json() == {"state": "none"}

    resp = seeded.post(f"/api/bids/{oid}/deep-dive")
    assert resp.status_code == 202

    body = _wait_for_deep_dive(seeded, oid)
    assert body["state"] == "done"
    assert body["report"]["overview"] == "Big roof job."
    assert body["report"]["dollar_amounts"] == [{"label": "Estimate", "amount": "$2M"}]
    assert body["report"]["red_flags"] == []
    assert body["docs_read"] == 0


def test_deep_dive_error_is_reported(seeded, monkeypatch):
    from src.ai import deep_dive

    def boom(model, text):
        raise RuntimeError("api exploded")

    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    monkeypatch.setattr(deep_dive, "_call_claude", boom)
    oid = first_untracked(seeded)["opportunity_id"]

    assert seeded.post(f"/api/bids/{oid}/deep-dive").status_code == 202
    body = _wait_for_deep_dive(seeded, oid)
    assert body["state"] == "error"
    assert "api exploded" in body["error"]


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------


def test_watchlists_crud_and_matches(seeded):
    lists = seeded.get("/api/watchlists").json()["watchlists"]
    assert len(lists) == 3  # seeded defaults
    assert all("match_count" in wl and "new_count" in wl for wl in lists)

    created = seeded.post("/api/watchlists", json={
        "name": "Roof work",
        "rules": {"keywords": ["roof"], "counties": ["broward"]},
    }).json()
    assert created["match_count"] >= 1

    renamed = seeded.put(f"/api/watchlists/{created['id']}",
                         json={"name": "Broward roofs", "email_digest": True}).json()
    assert renamed["name"] == "Broward roofs"
    assert renamed["email_digest"] is True

    matches = seeded.get(f"/api/watchlists/{created['id']}/matches").json()
    assert matches["matches"]
    assert all("is_new" in m for m in matches["matches"])
    assert all("roof" in (m["title"] + str(m.get("scope"))).lower()
               or m["county"] == "broward" for m in matches["matches"])

    # Everything is new before /seen; nothing is after.
    assert all(m["is_new"] for m in matches["matches"])
    seeded.post(f"/api/watchlists/{created['id']}/seen")
    matches = seeded.get(f"/api/watchlists/{created['id']}/matches").json()
    assert all(not m["is_new"] for m in matches["matches"])

    assert seeded.delete(f"/api/watchlists/{created['id']}").status_code == 204
    assert seeded.delete(f"/api/watchlists/{created['id']}").status_code == 404


def test_watchlist_value_and_flag_rules(seeded):
    created = seeded.post("/api/watchlists", json={
        "name": "Small no-bond",
        "rules": {"max_value": 200_000, "no_bond": True},
    }).json()
    matches = seeded.get(f"/api/watchlists/{created['id']}/matches").json()["matches"]
    for m in matches:
        assert m["budget_amount"] is None or m["budget_amount"] <= 200_000
        assert not any("bond" in r.lower() for r in m["requirements"])


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def test_sources_list(seeded):
    data = seeded.get("/api/sources").json()
    assert len(data["sources"]) >= 40
    assert data["last_run"]["opp_count"] > 0
    with_health = [s for s in data["sources"] if s["health"]]
    assert with_health, "demo health should attach to at least one source"


def test_source_detect_url_heuristic(client):
    out = client.post("/api/sources/detect",
                      json={"url": "https://www.coopercity.gov/bids.aspx"}).json()
    assert out["detected"] == "civicplus"
    assert out["supported"] is True
    assert out["portal_url"].endswith("bids.aspx")


def test_add_and_delete_custom_source(client, monkeypatch):
    # Never hit the network in tests: stub the adapter's fetch.
    from src.sources import civicplus

    monkeypatch.setattr(civicplus.CivicPlusAdapter, "fetch", lambda self: [])
    out = client.post("/api/sources", json={
        "name": "Town of Example",
        "county": "broward",
        "portal_url": "https://townofexample.gov/bids.aspx",
    }).json()
    assert out["source"]["adapter"] == "civicplus"
    assert out["test"]["ok"] is True

    sources = client.get("/api/sources").json()["sources"]
    added = next(s for s in sources if s["id"] == out["source"]["id"])
    assert added["custom"] is True

    # The registry merges it in for real fetches.
    from src.sources.registry import get_adapters

    ids = {a.source_id for a in get_adapters()}
    assert out["source"]["id"] in ids

    assert client.delete(f"/api/sources/{out['source']['id']}").status_code == 204
    assert client.delete(f"/api/sources/{out['source']['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Stats, notifications, settings
# ---------------------------------------------------------------------------


def test_stats_shape(seeded):
    stats = seeded.get("/api/stats").json()
    assert stats["totals"]["open_count"] > 0
    assert stats["totals"]["won"] == 1 and stats["totals"]["lost"] == 1
    assert stats["totals"]["win_rate"] == 0.5
    assert stats["totals"]["revenue_cents"] == 9_240_000
    assert len(stats["deadline_load"]) == 8
    assert {s["stage"] for s in stats["pipeline"]["stages"]} == {
        "watching", "preparing", "submitted", "result"}
    assert stats["by_county"]
    assert stats["results_by_month"]


def test_notifications_roundtrip(client):
    from src.db import store as db

    db.add_notification("fetch_done", "Fetch finished", "hello")
    data = client.get("/api/notifications").json()
    assert data["unread_count"] == 1
    client.post("/api/notifications/read", json={"ids": "all"})
    assert client.get("/api/notifications").json()["unread_count"] == 0


def test_settings_get_put_and_capabilities(client):
    data = client.get("/api/settings").json()
    assert data["settings"]["auto_fetch"]["mode"] == "off"
    assert "internal" not in data["settings"]
    assert data["capabilities"]["db_backend"] == "sqlite"

    out = client.put("/api/settings", json={
        "auto_fetch": {"mode": "interval", "interval_minutes": 120},
        "ai": {"model": "claude-sonnet-5"},
    }).json()
    assert out["settings"]["auto_fetch"]["mode"] == "interval"
    assert out["settings"]["ai"]["model"] == "claude-sonnet-5"


def test_purge_endpoint(seeded):
    assert seeded.post("/api/settings/data/purge",
                       json={"target": "workflow"}).status_code == 200
    data = seeded.get("/api/opportunities").json()
    assert not any(o["tracked"] for o in data["opportunities"])
    assert seeded.post("/api/settings/data/purge",
                       json={"target": "everything"}).status_code == 422


# ---------------------------------------------------------------------------
# SPA serving
# ---------------------------------------------------------------------------


def test_unknown_api_route_is_404_not_index(client):
    assert client.get("/api/definitely-not-a-route").status_code == 404


def test_spa_fallback_without_build(client):
    resp = client.get("/pipeline")
    assert resp.status_code == 200
    # Without frontend/dist the server explains itself instead of 500ing.
    assert "frontend" in resp.text.lower() or "<div id=\"root\"" in resp.text
