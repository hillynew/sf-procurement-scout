"""Background fetch job: lifecycle, 409 on double-start, SSE framing."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.models.opportunity import Opportunity, SourceHealth


def fake_run_fetch(*, on_progress=None, **kwargs):
    health = SourceHealth(source_id="fake", name="Fake Source", ok=True, count=1)
    if on_progress:
        on_progress({"event": "start", "total": 1})
        on_progress({"event": "source", "source": health.model_dump(mode="json"),
                     "done": 1, "total": 1})
        on_progress({"event": "phase", "phase": "finalize"})
    opp = Opportunity(
        source_id="fake", source_name="Fake Source", title="Fake Bid",
        url="https://example.gov/fake", county="broward", agency="Fakeville",
    )
    return [opp], [health]


def slow_run_fetch(*, on_progress=None, **kwargs):
    time.sleep(0.4)
    return fake_run_fetch(on_progress=on_progress)


@pytest.fixture()
def client(monkeypatch):
    from web.services import fetch_job as fj

    monkeypatch.setattr(fj, "run_fetch", fake_run_fetch)
    # A fresh job per test — the module singleton keeps state otherwise.
    monkeypatch.setattr(fj, "job", fj.FetchJob())
    from web.api import fetch as fetch_api

    monkeypatch.setattr(fetch_api, "job", fj.job)
    from web.server import create_app

    with TestClient(create_app()) as c:
        yield c


def _wait_done(client, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/fetch/status").json()
        if status["state"] in ("done", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError(f"fetch never finished: {status}")


def _wait_idle(client, timeout=5.0):
    """Wait until the job is genuinely finished, not merely reporting "done".

    `_run_once` publishes state "done" and *then* awaits auto-summaries; only
    the outer `finally` clears `running`. So there is a real window where the
    status endpoint says done while a start would still be refused as
    already-running. Polling on status alone makes any follow-up POST a coin
    flip.
    """
    from web.services import fetch_job as fj

    _wait_done(client, timeout=timeout)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not fj.job.running:
            return
        time.sleep(0.05)
    raise AssertionError("job still running after it reported done")


def test_fetch_lifecycle_and_snapshot(client):
    assert client.get("/api/fetch/status").json()["state"] == "idle"
    assert client.post("/api/fetch").status_code == 202

    status = _wait_done(client)
    assert status["state"] == "done"
    assert status["count"] == 1
    assert status["new_count"] == 1

    data = client.get("/api/opportunities").json()
    assert data["count"] == 1
    assert data["opportunities"][0]["title"] == "Fake Bid"

    # fetch_done notification landed.
    notes = client.get("/api/notifications").json()
    assert any(n["kind"] == "fetch_done" for n in notes["items"])


def test_double_start_is_409(monkeypatch):
    from web.services import fetch_job as fj

    monkeypatch.setattr(fj, "run_fetch", slow_run_fetch)
    monkeypatch.setattr(fj, "job", fj.FetchJob())
    from web.api import fetch as fetch_api

    monkeypatch.setattr(fetch_api, "job", fj.job)
    from web.server import create_app

    with TestClient(create_app()) as client:
        assert client.post("/api/fetch").status_code == 202
        assert client.post("/api/fetch").status_code == 409
        _wait_done(client)


def test_failed_fetch_records_run_and_notification(monkeypatch):
    from web.services import fetch_job as fj

    def boom(**kwargs):
        raise RuntimeError("portal exploded")

    monkeypatch.setattr(fj, "run_fetch", boom)
    monkeypatch.setattr(fj, "job", fj.FetchJob())
    from web.api import fetch as fetch_api

    monkeypatch.setattr(fetch_api, "job", fj.job)
    from web.server import create_app

    with TestClient(create_app()) as client:
        client.post("/api/fetch")
        status = _wait_done(client)
        assert status["state"] == "error"
        assert "portal exploded" in status["error"]

        from src.db import store as db

        run = db.latest_run()
        assert run["status"] == "error"
        notes = client.get("/api/notifications").json()
        assert any(n["kind"] == "fetch_failed" for n in notes["items"])


def test_sse_stream_frames(client):
    client.post("/api/fetch")
    _wait_done(client)
    # After completion the stream returns the terminal status immediately.
    with client.stream("GET", "/api/fetch/stream") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        chunk = next(resp.iter_text())
    assert chunk.startswith("event: status")
    assert '"state": "done"' in chunk


def test_watchlist_match_notification_on_new_bids(client):
    # A watchlist matching the fake bid by keyword.
    client.post("/api/watchlists", json={"name": "Fakes",
                                         "rules": {"keywords": ["fake"]}})
    client.post("/api/fetch")
    _wait_done(client)
    notes = client.get("/api/notifications").json()["items"]
    match = [n for n in notes if n["kind"] == "watchlist_match"]
    assert match and "Fakes" in match[0]["title"]


def test_release_memory_is_safe_to_call():
    """gc + malloc_trim; must be a no-op-at-worst on any platform."""
    from web.services import fetch_job as fj

    fj._release_memory()


def test_a_second_fetch_inside_the_gap_is_refused(client):
    """The cron and the "on open" refresh are independent schedules. On
    2026-08-10 they landed 11 minutes apart and the second run peaked at
    502MB against a 512MB limit."""
    assert client.post("/api/fetch").status_code == 202
    _wait_idle(client)

    resp = client.post("/api/fetch")
    assert resp.status_code == 409
    assert "less than" in resp.json()["detail"]


def test_fetch_now_overrides_the_gap(client):
    """The guard is for schedules, not for the human at the keyboard."""
    assert client.post("/api/fetch").status_code == 202
    _wait_idle(client)

    assert client.post("/api/fetch?force=true").status_code == 202
    assert _wait_done(client)["state"] == "done"


def test_the_gap_never_blocks_the_very_first_fetch(client):
    """No prior run means nothing to be too soon after — a fresh deployment
    must not sit idle waiting out a window that never started."""
    assert client.post("/api/fetch").status_code == 202
    assert _wait_done(client)["state"] == "done"
