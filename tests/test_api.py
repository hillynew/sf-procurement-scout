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


def test_watchlist_category_rule(seeded):
    """A category rule filters, and unknown slugs never reach storage."""
    created = seeded.post("/api/watchlists", json={
        "name": "Roofs only",
        "rules": {"categories": ["roofing", "not_a_real_category"]},
    }).json()
    # The typo is dropped rather than stored — a bogus slug would match nothing
    # forever and be indistinguishable from an empty watchlist.
    assert created["rules"]["categories"] == ["roofing"]

    matches = seeded.get(f"/api/watchlists/{created['id']}/matches").json()["matches"]
    for m in matches:
        assert "roofing" in m["categories"]


def test_watchlist_rule_of_only_unknown_categories_is_not_a_filter(seeded):
    """Dropping every slug must not silently become "match everything"."""
    created = seeded.post("/api/watchlists", json={
        "name": "Bogus", "rules": {"categories": ["nope_not_real"]},
    }).json()
    assert "categories" not in created["rules"]


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def test_taxonomy_is_complete_regardless_of_data(client):
    """Served before any fetch: the vocabulary is declared, not derived."""
    data = client.get("/api/taxonomy").json()
    assert len(data["categories"]) > 150
    assert len(data["groups"]) > 10
    # All 67 counties plus the pseudo-county buckets, not merely those seen.
    assert len([c for c in data["counties"] if c["region"] != c["slug"]]) >= 67
    assert data["total_open"] == 0
    assert all(c["count"] == 0 for c in data["categories"])


def test_taxonomy_counts_reflect_open_bids(seeded):
    data = seeded.get("/api/taxonomy").json()
    assert data["total_open"] > 0
    assert any(c["count"] > 0 for c in data["categories"]), "demo data should tag something"
    # Anticipatory entries stay listed with a zero count rather than vanishing.
    assert any(c["count"] == 0 for c in data["categories"])
    by_slug = {c["slug"]: c for c in data["categories"]}
    assert "general" not in by_slug
    assert by_slug["roofing"]["group"] == "construction"


def test_taxonomy_categories_are_all_detectable(client):
    data = client.get("/api/taxonomy").json()
    assert all(c["detectable"] for c in data["categories"]), (
        "an offered category that cannot be detected is a dead filter"
    )


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


def test_maintenance_cadence_is_settable_and_its_last_run_is_not(client):
    """A cadence is something you set; a last-run date is something you are
    told. Without the second the UI can only offer to schedule work it cannot
    say has ever happened."""
    data = client.get("/api/settings").json()
    assert data["settings"]["maintenance"]["enabled"] is False
    assert data["maintenance_status"] == {
        "last_contracts_refresh_on": None, "last_platform_check_on": None, "running": None,
    }

    out = client.put("/api/settings", json={
        "maintenance": {"enabled": True, "platform_check_days": 90},
    }).json()
    assert out["settings"]["maintenance"] == {
        "enabled": True, "contracts_enabled": False, "platform_check_enabled": True,
        "contracts_days": 7, "platform_check_days": 90,
    }
    assert "last_platform_check_on" not in out["settings"]["maintenance"]


def test_an_unknown_maintenance_job_is_refused(client):
    assert client.post("/api/settings/maintenance/run", json={"job": "everything"}).status_code == 422


def test_a_maintenance_run_answers_before_the_walk_finishes(client, monkeypatch):
    """Both walks take minutes; a request that waited would time out first."""
    from web.services import maintenance

    ran = []
    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": lambda: ran.append(1)})
    body = client.post("/api/settings/maintenance/run", json={"job": "contracts"}).json()

    assert body == {"started": True, "running": "contracts"}


def test_digest_test_email_without_key(client, monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    body = client.post("/api/settings/digest/test").json()
    assert body["sent"] is False
    assert "RESEND_API_KEY" in body["error"]


def test_digest_test_email_sends(client, monkeypatch):
    import httpx

    from web.services import digest

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    client.put("/api/settings", json={"digest": {"email": "buyer@example.com"}})
    monkeypatch.setattr(
        digest.httpx, "post",
        lambda url, **kw: httpx.Response(200, json={"id": "abc"},
                                         request=httpx.Request("POST", url)),
    )
    body = client.post("/api/settings/digest/test").json()
    assert body == {"sent": True, "error": None, "recipient": "buyer@example.com"}


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


# ---------------------------------------------------------------------------
# Follow-up research
# ---------------------------------------------------------------------------


def test_research_requires_a_key_and_a_question(seeded, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    bid = first_untracked(seeded)
    r = seeded.post(f"/api/bids/{bid['opportunity_id']}/research",
                    json={"question": "What did this cost before?"})
    assert r.status_code == 503

    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    r = seeded.post(f"/api/bids/{bid['opportunity_id']}/research",
                    json={"question": "   "})
    assert r.status_code == 422


def test_research_thread_is_served_with_suggestions(seeded):
    bid = first_untracked(seeded)
    data = seeded.get(f"/api/bids/{bid['opportunity_id']}/research").json()
    assert data["turns"] == []
    assert data["state"] == "idle"
    # Anticipatory prompts — the point is asking what the documents can't say.
    assert any("last time" in q for q in data["suggested_questions"])


def test_research_unknown_bid_is_404(seeded):
    assert seeded.get("/api/bids/nope/research").status_code == 404
    assert seeded.post("/api/bids/nope/research",
                       json={"question": "?"}).status_code == 404


def test_quality_report_endpoint(client):
    r = client.get("/api/quality")
    assert r.status_code == 200
    data = r.json()
    assert "overall" in data and "sources" in data
    if data["overall"]["records"]:
        fields = data["overall"]["fields"]
        assert "due_date" in fields and "award_amount" in fields
        assert 0 <= fields["due_date"]["pct"] <= 100


def test_stats_carries_open_protest_windows(client, monkeypatch):
    """An award notice with a live 72-hour window must reach the dashboard."""
    from datetime import datetime, timedelta

    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    award = Opportunity(
        source_id="mfmp_vbs", source_name="MFMP", title="Intended Award: Moving Services",
        url="https://vendor.myfloridamarketplace.com/ad/1", county="statewide",
        agency="Department of Legal Affairs", status="award",
        awarded_vendor="MoveCo LLC", award_amount=250_000,
        protest_deadline=datetime.now() + timedelta(days=2),
    )
    db.save_snapshot([award], [SourceHealth(source_id="mfmp_vbs", name="MFMP", ok=True, count=1)])

    data = client.get("/api/stats").json()
    windows = data["protest_windows"]
    assert len(windows) == 1
    assert windows[0]["awarded_vendor"] == "MoveCo LLC"
    assert windows[0]["hours_left"] > 0


def test_awards_endpoint_returns_awards_and_expiring_contracts(client):
    from datetime import date, timedelta

    from src.contracts import Contract
    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    award = Opportunity(
        source_id="legistar_broward", source_name="Broward awards",
        title="MOTION TO AWARD to Crown USA, Inc.", url="https://broward.legistar.com/x",
        county="broward", agency="Broward County", status="award",
        awarded_vendor="Crown USA, Inc", award_amount=193_500,
        award_date=date.today() - timedelta(days=3),
    )
    db.save_snapshot([award], [SourceHealth(source_id="legistar_broward", name="B", ok=True, count=1)])
    db.save_contracts([Contract(
        contract_id="C1", agency="Broward County", name="Janitorial",
        source_id="broward_bpro", vendor="CleanCo",
        end_date=date.today() + timedelta(days=90),
    )])

    data = client.get("/api/awards").json()
    assert data["awards"][0]["awarded_vendor"] == "Crown USA, Inc"
    assert data["awards"][0]["award_amount"] == 193_500
    assert data["contracts"][0]["vendor"] == "CleanCo"
    assert 0 <= data["contracts"][0]["days_left"] <= 90


def test_pricing_endpoint_builds_category_medians(client):
    from datetime import date

    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    awards = [
        Opportunity(
            source_id="s", source_name="S", title=f"Janitorial Services {i}",
            url=f"https://x.gov/{i}", county="broward", agency="Broward County",
            status="award", categories=["janitorial_custodial"], award_amount=amount,
            award_date=date.today(),
        )
        for i, amount in enumerate([90_000, 120_000, 150_000, 200_000])
    ]
    db.save_snapshot(awards, [SourceHealth(source_id="s", name="S", ok=True, count=4)])
    # A FACTS-style contract with an amount joins the same category pool.
    from src.contracts import Contract

    db.save_contracts([Contract(
        contract_id="J1", agency="DMS", name="Custodial Services Contract",
        source_id="facts", vendor="CleanCo", amount=110_000.0,
    )])

    data = client.get("/api/pricing").json()
    jan = next(c for c in data["categories"] if c["slug"] == "janitorial_custodial")
    assert jan["count"] == 5
    assert 120_000 <= jan["median"] <= 150_000
    assert jan["by_county"]["broward"]["count"] == 4


def test_thin_samples_stay_out_of_pricing(client):
    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    lonely = Opportunity(
        source_id="s", source_name="S", title="Roof Repair", url="https://x.gov/1",
        county="broward", agency="X", status="award",
        categories=["roofing"], award_amount=50_000,
    )
    db.save_snapshot([lonely], [SourceHealth(source_id="s", name="S", ok=True, count=1)])
    data = client.get("/api/pricing").json()
    assert not any(c["slug"] == "roofing" for c in data["categories"])


def test_vendor_profiles_group_name_variants(client):
    from datetime import date

    from src.contracts import Contract
    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    awards = [
        Opportunity(
            source_id="s", source_name="S", title=f"Paving {i}", url=f"https://x.gov/p{i}",
            county="broward", agency="Broward County", status="award",
            categories=["paving_roadway"], awarded_vendor=name, award_amount=100_000,
            award_date=date(2026, 8, 1),
        )
        for i, name in enumerate(["Apex Paving LLC", "APEX PAVING, INC."])
    ]
    db.save_snapshot(awards, [SourceHealth(source_id="s", name="S", ok=True, count=2)])
    db.save_contracts([Contract(
        contract_id="P1", agency="FDOT", name="Roadway Term Contract",
        source_id="facts", vendor="Apex Paving", amount=1.0,
    )])

    data = client.get("/api/vendors").json()
    apex = next(v for v in data["vendors"] if v["name"].lower().startswith("apex"))
    assert apex["awards"] == 2
    assert apex["contracts"] == 1
    assert apex["awarded_total"] == 200_000
    assert "Broward County" in apex["agencies"]


def test_records_queue_mints_letters_for_ripe_leads(client):
    from datetime import datetime, timedelta

    from src.db import store as db
    from src.models.opportunity import Opportunity, SourceHealth

    stale = Opportunity(
        source_id="s", source_name="S", title="Sidewalk Grinding ITB",
        url="https://x.gov/sg", county="broward", agency="City of Testville",
        status="closed", external_id="ITB-25-77",
        due_date=datetime.now() - timedelta(days=45),
        contact_email="clerk@testville.gov",
    )
    db.save_snapshot([stale], [SourceHealth(source_id="s", name="S", ok=True, count=1)])

    data = client.get("/api/records").json()
    assert data["added"] == 1
    (req,) = [r for r in data["requests"] if r["opportunity_id"] == stale.opportunity_id]
    assert req["status"] == "ready"
    assert "119.01(2)(f)" in req["letter"]
    assert req["contact_email"] == "clerk@testville.gov"

    # Second read must not re-mint.
    again = client.get("/api/records").json()
    assert again["added"] == 0

    # Marking sent stamps the date.
    r = client.put(f"/api/records/{stale.opportunity_id}", json={"status": "sent"})
    assert r.status_code == 200
    assert r.json()["sent_on"] is not None

    r = client.put(f"/api/records/{stale.opportunity_id}", json={"status": "bogus"})
    assert r.status_code == 422
