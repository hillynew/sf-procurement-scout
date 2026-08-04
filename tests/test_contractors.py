"""Contractor matching: id dedupe, normalization, caching, store, API."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.ai import contractors
from src.models.opportunity import Opportunity


def make_opp(**kw) -> Opportunity:
    defaults = dict(
        source_id="test-src",
        source_name="Test Source",
        title="Roof Replacement — City Hall",
        url="https://example.gov/roof",
        county="broward",
        agency="City of Testville",
        status="open",
        due_date=datetime.utcnow() + timedelta(days=14),
    )
    defaults.update(kw)
    return Opportunity(**defaults)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.db import engine as db_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    db_engine.reset_engine()
    from src.db import store

    store.bootstrap()
    yield store
    db_engine.reset_engine()


def _record_block(payload: dict):
    return SimpleNamespace(type="tool_use", name="record_contractor_matches",
                           input=payload)


def _search_block():
    return SimpleNamespace(type="server_tool_use", name="web_search")


def _response(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


APEX = {
    "name": "Apex Roofing LLC",
    "location": "Pompano Beach, FL",
    "trade": "commercial roofing",
    "website": "https://apexroof.example",
    "phone": "954-555-0100",
    "email": "",
    "gov_experience": "none",
    "why_fit": "Does TPO re-roofs on commercial buildings this size.",
    "pitch_angle": "There's a funded city re-roof near you. We file and keep it compliant; you do the work.",
    "sources": ["https://directory.example/apex"],
}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_contractor_id_ignores_legal_suffixes_and_punctuation():
    a = contractors.contractor_id("Apex Roofing LLC")
    assert a == contractors.contractor_id("Apex Roofing, Inc.")
    assert a == contractors.contractor_id("  APEX ROOFING  ")
    assert a != contractors.contractor_id("Apex Plumbing LLC")


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_matches_survives_junk_shapes():
    out = contractors.normalize_matches({
        "matches": [
            APEX,
            {"name": ""},                       # nameless → dropped
            "not-a-dict",                       # wrong type → dropped
            {"name": "B Co", "trade": None, "gov_experience": "ALWAYS",
             "sources": ["ftp://nope", "https://ok.example", "https://ok.example"]},
        ],
        "market_note": 42,
    })
    assert [m["name"] for m in out["matches"]] == ["Apex Roofing LLC", "B Co"]
    b = out["matches"][1]
    assert b["trade"] == "" and b["gov_experience"] == "unknown"
    assert b["sources"] == ["https://ok.example"]
    assert out["market_note"] == "42"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def test_upsert_fills_blanks_but_never_regresses(db):
    cid = contractors.contractor_id(APEX["name"])
    db.upsert_contractor({"id": cid, "name": APEX["name"], "county": "broward",
                          "phone": "", "profile": {"gov_experience": "none"}})
    db.update_contractor(cid, phone="954-555-9999", status="in_network")

    # A re-run bringing a different phone must not clobber the corrected one.
    db.upsert_contractor({"id": cid, "name": APEX["name"], "phone": "000",
                          "trade": "roofing", "profile": {"sources": ["https://s"]}})
    row = db.get_contractor(cid)
    assert row["phone"] == "954-555-9999"
    assert row["status"] == "in_network"
    assert row["trade"] == "roofing"          # blank got filled
    assert row["profile"] == {"gov_experience": "none", "sources": ["https://s"]}


def test_update_contractor_validates(db):
    cid = contractors.contractor_id("X Co")
    db.upsert_contractor({"id": cid, "name": "X Co"})
    with pytest.raises(ValueError):
        db.update_contractor(cid, status="bogus")
    with pytest.raises(ValueError):
        db.update_contractor(cid, name="renaming is not allowed")
    assert db.update_contractor("missing", status="contacted") is None


def test_match_set_round_trip_and_status(db):
    db.put_contractor_matches("opp1", content_hash="h", model="m",
                              prompt_version=1,
                              matches=[{"contractor_id": "c1", "status": "suggested"}],
                              market_note="thin market", searches=4)
    got = db.get_contractor_matches("opp1", 1)
    assert got["market_note"] == "thin market" and got["searches"] == 4

    assert db.set_match_status("opp1", "c1", "pitched")[0]["status"] == "pitched"
    assert db.get_contractor_matches("opp1")["matches"][0]["status"] == "pitched"
    assert db.set_match_status("opp1", "nope", "pitched") is None
    assert db.set_match_status("missing", "c1", "pitched") is None
    with pytest.raises(ValueError):
        db.set_match_status("opp1", "c1", "bogus")

    # Version gating and pruning, same rules as the other AI caches.
    assert db.get_contractor_matches("opp1", 2) is None
    assert db.prune_contractor_matches(2) == 1
    assert db.get_contractor_matches("opp1") is None


def test_purge_contractors(db):
    db.upsert_contractor({"id": "c1", "name": "X"})
    db.put_contractor_matches("opp1", content_hash="h", model="m",
                              prompt_version=1, matches=[], market_note="",
                              searches=0)
    db.purge("contractors")
    assert db.list_contractors() == []
    assert db.get_contractor_matches("opp1") is None


# ---------------------------------------------------------------------------
# run_match
# ---------------------------------------------------------------------------


def test_run_match_records_and_builds_the_network(db, monkeypatch):
    calls = []

    def fake_call(model, messages, tools, tool_choice=None):
        calls.append({"tools": [t["name"] for t in tools], "choice": tool_choice})
        return _response([_search_block(), _search_block(),
                          _record_block({"matches": [APEX], "market_note": "ok"})])

    monkeypatch.setattr(contractors, "_call_claude", fake_call)
    opp = make_opp()
    result = contractors.run_match(opp)

    assert result["cached"] is False and result["searches"] == 2
    match = result["matches"][0]
    assert match["status"] == "suggested"
    assert match["contractor_id"] == contractors.contractor_id(APEX["name"])
    # The search phase offers both tools without forcing either.
    assert calls[0]["tools"] == ["web_search", "record_contractor_matches"]
    assert calls[0]["choice"] is None
    # The firm landed in the network directory.
    network = db.list_contractors()
    assert len(network) == 1
    assert network[0]["name"] == APEX["name"]
    assert network[0]["county"] == "broward"
    assert network[0]["profile"]["gov_experience"] == "none"


def test_run_match_caches_and_preserves_outreach_status(db, monkeypatch):
    responses = []

    def fake_call(model, messages, tools, tool_choice=None):
        responses.append(1)
        return _response([_record_block({"matches": [APEX]})])

    monkeypatch.setattr(contractors, "_call_claude", fake_call)
    opp = make_opp()
    first = contractors.run_match(opp)
    cid = first["matches"][0]["contractor_id"]

    # Unchanged input + model → served from cache, no new call.
    again = contractors.run_match(opp)
    assert again["cached"] is True and len(responses) == 1

    # A forced re-run keeps the outreach status already set on the match.
    db.set_match_status(opp.opportunity_id, cid, "interested")
    rerun = contractors.run_match(opp, force=True)
    assert rerun["cached"] is False and len(responses) == 2
    assert rerun["matches"][0]["status"] == "interested"


def test_run_match_forces_the_record_when_not_volunteered(db, monkeypatch):
    seq = [
        _response([SimpleNamespace(type="text", text="Found some firms.")]),
        _response([_record_block({"matches": [APEX]})]),
    ]
    calls = []

    def fake_call(model, messages, tools, tool_choice=None):
        calls.append({"tools": [t["name"] for t in tools], "choice": tool_choice,
                      "messages": list(messages)})
        return seq[len(calls) - 1]

    monkeypatch.setattr(contractors, "_call_claude", fake_call)
    result = contractors.run_match(make_opp())
    assert result["matches"][0]["name"] == APEX["name"]
    # Follow-up forces the record tool alone, with the research replayed.
    assert calls[1]["tools"] == ["record_contractor_matches"]
    assert calls[1]["choice"] == {"type": "tool", "name": "record_contractor_matches"}
    assert calls[1]["messages"][1]["role"] == "assistant"


def test_run_match_resumes_pause_turn(db, monkeypatch):
    seq = [
        _response([_search_block()], stop_reason="pause_turn"),
        _response([_search_block(), _record_block({"matches": [APEX]})]),
    ]
    calls = []

    def fake_call(model, messages, tools, tool_choice=None):
        calls.append(list(messages))
        return seq[len(calls) - 1]

    monkeypatch.setattr(contractors, "_call_claude", fake_call)
    result = contractors.run_match(make_opp())
    assert result["searches"] == 2
    # The resume request must end with the paused assistant turn, verbatim.
    assert calls[1][-1]["role"] == "assistant"


def test_run_match_without_key_fails_loudly(db, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="no_api_key"):
        contractors.run_match(make_opp())


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from web.server import create_app

    from fastapi.testclient import TestClient

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture()
def seeded(client):
    resp = client.post("/api/demo")
    assert resp.status_code == 200
    return client


def _first_open(client) -> str:
    data = client.get("/api/opportunities").json()
    return next(o for o in data["opportunities"] if o["status"] == "open")[
        "opportunity_id"]


def _wait_for_matches(client, oid, tries=200):
    import time

    for _ in range(tries):
        body = client.get(f"/api/bids/{oid}/contractors").json()
        if body["state"] != "running":
            return body
        time.sleep(0.02)
    raise AssertionError("matching never finished")


def test_match_without_key_is_503(seeded, monkeypatch):
    monkeypatch.delenv("SF_SCOUT_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    oid = _first_open(seeded)
    resp = seeded.post(f"/api/bids/{oid}/contractors")
    assert resp.status_code == 503
    assert resp.json()["detail"]["reason"] == "no_api_key"
    assert seeded.get("/api/bids/nope/contractors").status_code == 404


def test_match_lifecycle_and_network(seeded, monkeypatch):
    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    monkeypatch.setattr(
        contractors, "_call_claude",
        lambda model, messages, tools, tool_choice=None:
            _response([_record_block({"matches": [APEX], "market_note": "ok"})]),
    )
    oid = _first_open(seeded)

    assert seeded.get(f"/api/bids/{oid}/contractors").json() == {"state": "none"}
    assert seeded.post(f"/api/bids/{oid}/contractors").status_code == 202

    body = _wait_for_matches(seeded, oid)
    assert body["state"] == "done"
    match = body["matches"][0]
    assert match["name"] == APEX["name"]
    assert match["status"] == "suggested"
    assert match["contractor_status"] == "prospect"

    # Move the match through outreach; the join reflects it.
    cid = match["contractor_id"]
    resp = seeded.put(f"/api/bids/{oid}/contractors/{cid}",
                      json={"status": "pitched"})
    assert resp.json()["matches"][0]["status"] == "pitched"
    assert seeded.put(f"/api/bids/{oid}/contractors/{cid}",
                      json={"status": "bogus"}).status_code == 422
    assert seeded.put(f"/api/bids/{oid}/contractors/nope",
                      json={"status": "pitched"}).status_code == 404

    network = seeded.get("/api/contractors").json()
    assert network["count"] == 1
    firm = network["contractors"][0]
    assert firm["matched_bids"][0]["opportunity_id"] == oid
    assert firm["matched_bids"][0]["match_status"] == "pitched"

    # Relationship + notes editing, then removal.
    resp = seeded.put(f"/api/contractors/{cid}",
                      json={"status": "in_network", "notes": "spoke to owner"})
    assert resp.json()["status"] == "in_network"
    assert seeded.put(f"/api/contractors/{cid}",
                      json={"status": "bogus"}).status_code == 422
    assert seeded.delete(f"/api/contractors/{cid}").status_code == 204
    assert seeded.delete(f"/api/contractors/{cid}").status_code == 404
    assert seeded.get("/api/contractors").json()["count"] == 0


def test_match_error_is_reported(seeded, monkeypatch):
    def boom(model, messages, tools, tool_choice=None):
        raise RuntimeError("overloaded")

    monkeypatch.setenv("SF_SCOUT_ANTHROPIC_KEY", "test-key")
    monkeypatch.setattr(contractors, "_call_claude", boom)
    oid = _first_open(seeded)
    assert seeded.post(f"/api/bids/{oid}/contractors").status_code == 202
    body = _wait_for_matches(seeded, oid)
    assert body["state"] == "error"
    assert "overloaded" in body["error"]
