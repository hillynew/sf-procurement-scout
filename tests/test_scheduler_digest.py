"""Scheduler ticks and digest building — all offline."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.db import store as db
from src.models.opportunity import Opportunity


def make_opp(title="Roof Replacement", days=3, **kw) -> Opportunity:
    defaults = dict(
        source_id="s", source_name="S", title=title,
        url=f"https://example.gov/{title}", county="broward", agency="Testville",
        status="open", due_date=datetime.utcnow() + timedelta(days=days),
        budget="$150,000",
    )
    defaults.update(kw)
    return Opportunity(**defaults)


@pytest.fixture(autouse=True)
def _bootstrap():
    db.bootstrap()


@pytest.mark.anyio
async def test_deadline_scan_notifies_once_per_day():
    from web.services import scheduler

    opp = make_opp(days=2)
    db.save_snapshot([opp], [])
    db.set_tracked(opp.opportunity_id, True)

    await scheduler.tick()
    unread, items = db.list_notifications()
    deadline = [n for n in items if n["kind"] == "deadline_soon"]
    assert len(deadline) == 1
    assert "2 days" in deadline[0]["title"]

    # Second tick the same day: no duplicate.
    await scheduler.tick()
    _, items = db.list_notifications()
    assert len([n for n in items if n["kind"] == "deadline_soon"]) == 1


@pytest.mark.anyio
async def test_interval_autofetch_triggers_job(monkeypatch):
    from web.services import fetch_job as fj
    from web.services import scheduler

    started = {"n": 0}

    class FakeJob:
        running = False

        async def start(self):
            started["n"] += 1
            return True

    monkeypatch.setattr(scheduler, "job", FakeJob())
    db.update_settings({"auto_fetch": {"mode": "interval", "interval_minutes": 60}})
    await scheduler.tick()
    assert started["n"] == 1  # no runs yet -> fetch immediately

    del fj  # silence unused warning


def test_daily_digest_builds_sections():
    from web.services.digest import build_daily_digest

    roof = make_opp("Roof Replacement at Station 4", days=3)
    other = make_opp("Sidewalk Grinding", days=40)
    db.save_snapshot([roof, other], [])
    db.set_tracked(roof.opportunity_id, True)

    wl = db.create_watchlist("Roofs", {"keywords": ["roof"]})
    db.update_watchlist(wl["id"], email_digest=True)

    built = build_daily_digest([roof, other], db.workflow_state(), db.list_watchlists())
    assert built is not None
    subject, html = built
    assert "1 new match" in subject
    assert "Roof Replacement at Station 4" in html
    assert "Tracked bids due this week" in html

    # Once seen and past-due filtered, an empty digest returns None.
    db.mark_watchlist_seen(wl["id"], [roof.opportunity_id])
    db.set_tracked(roof.opportunity_id, False)
    assert build_daily_digest([other], db.workflow_state(), db.list_watchlists()) is None


def test_send_email_inert_without_key(monkeypatch):
    from web.services import digest

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert digest.enabled() is False
    assert digest.send_email("subject", "<p>hi</p>") is False
