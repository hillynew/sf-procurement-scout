"""Web server routes: rendering, actions, redirects, and the All-bids screen."""

import pytest
from fastapi.testclient import TestClient

import web.sample_data as sample_data
import web.server as server
from src.pipeline import user_state as us
from src.pipeline.store import save_snapshot


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A TestClient over an isolated data directory with the sample snapshot."""
    import src.pipeline.store as store

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(us, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(server, "data_dir", lambda: tmp_path)
    server._load_snapshot.cache_clear()
    server._flash.clear()

    bids, health = sample_data.build_sample()
    save_snapshot(list(bids.values()), health, tag="test")

    us.save_user_state(us.load_user_state())

    c = TestClient(server.app, follow_redirects=False)
    c.bids = bids
    return c


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_styles_served(client):
    r = client.get("/styles.css")
    assert r.status_code == 200
    assert "Scout Classic" in r.text


@pytest.mark.parametrize("screen", ["today", "all", "pipeline", "workroom", "watchlists", "sources"])
def test_every_screen_renders(client, screen):
    r = client.get(f"/?screen={screen}")
    assert r.status_code == 200
    assert "SF Procurement Scout" in r.text
    assert "sc-app" in r.text


def test_unknown_screen_falls_back_to_today(client):
    r = client.get("/?screen=bogus")
    assert r.status_code == 200
    assert '<div class="sc-head-title">Today</div>' in r.text


def test_all_bids_lists_every_status_and_date(client):
    r = client.get("/?screen=all")
    assert r.status_code == 200
    # Open bids and closed (submitted/awarded) bids both appear.
    assert "Roof repairs — Fire Station 12" in r.text
    assert "Fence repairs, parks pkg B" in r.text
    # Month groupings and the no-date guard exist.
    assert "DUE " in r.text
    assert "CLOSED" in r.text


def test_all_bids_search_filters(client):
    r = client.get("/?screen=all&q=janitorial")
    assert "Janitorial services, citywide" in r.text
    assert "Roof repairs — Fire Station 12" not in r.text


def test_all_bids_status_filter(client):
    r = client.get("/?screen=all&f=closed")
    assert "Fence repairs, parks pkg B" in r.text
    assert "Guardrail replacement, district-wide" not in r.text


def test_track_action_redirects_and_persists(client):
    oid = client.bids["r4"].opportunity_id
    r = client.get(f"/?act=track&id={oid}&screen=today")
    assert r.status_code == 303
    assert r.headers["location"] == "/?screen=today"
    assert oid in us.load_user_state()["tracked"]
    # Rendered page reflects it.
    assert "TRACKING ✓" in client.get("/?screen=today").text


def test_action_urls_are_not_replayed_on_refresh(client):
    oid = client.bids["r4"].opportunity_id
    client.get(f"/?act=track&id={oid}&screen=today")
    # The redirect target carries no act; loading it changes nothing.
    client.get("/?screen=today")
    assert oid in us.load_user_state()["tracked"]


def test_drawer_renders_for_a_bid(client):
    oid = client.bids["r3"].opportunity_id
    r = client.get(f"/?screen=all&drawer={oid}")
    assert "sc-drawer" in r.text
    assert "Sidewalk ADA improvements Ph. 2" in r.text
    assert "OFFICIAL PORTAL" not in r.text  # example.com URLs are suppressed


def test_notes_action_saves(client):
    oid = client.bids["r1"].opportunity_id
    us_state = us.load_user_state()
    us.toggle_tracked(us_state, oid)
    us.save_user_state(us_state)
    r = client.get(f"/?screen=workroom&bid={oid}&act=notes&id={oid}&notes=call+Ray")
    assert r.status_code == 303
    assert us.load_user_state()["notes"][oid] == "call Ray"


def test_detect_flash_shows_once(client):
    r = client.get("/?screen=sources&act=detect&url=https://x.example/bids.aspx")
    assert r.status_code == 303
    page = client.get(r.headers["location"]).text
    assert "Detected: CivicPlus Bids module" in page
    assert any(s["detected"] == "civicplus" for s in us.load_user_state()["queued_sources"])
