"""The two slow walks, on a cadence: contracts weekly, platform check monthly.

Nothing here touches the network — both jobs are stubbed, and what is under
test is the scheduling around them: when they are due, that only one runs, that
they stay off the event loop, and that what they find reaches a person.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from src.db import store as db
from web.services import maintenance


@pytest.fixture(autouse=True)
def _bootstrap():
    db.bootstrap()


def _on(**cfg):
    base = {"enabled": True, "contracts_days": 7, "platform_check_days": 30}
    base.update(cfg)
    db.update_settings({"maintenance": base})
    return db.get_settings()


def _ran_days_ago(job: str, days: int):
    key = {"contracts": "last_contracts_refresh_on", "platforms": "last_platform_check_on"}[job]
    db.update_settings({"internal": {key: (date.today() - timedelta(days=days)).isoformat()}})


# -- when a job is due -----------------------------------------------------


def test_a_job_that_has_never_run_is_due():
    assert maintenance.due(None, 7) is True


def test_a_job_run_today_is_not_due_again():
    assert maintenance.due(date.today().isoformat(), 7) is False


def test_a_job_is_due_the_day_the_interval_elapses():
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    six_days = (date.today() - timedelta(days=6)).isoformat()

    assert maintenance.due(week_ago, 7) is True
    assert maintenance.due(six_days, 7) is False


def test_an_interval_of_zero_means_never():
    """The UI's "Off" per-job, distinct from switching upkeep off entirely."""
    assert maintenance.due(None, 0) is False


def test_an_unreadable_date_does_not_disable_the_job_forever():
    """A settings row written by an older build should not be a permanent stop."""
    assert maintenance.due("last tuesday", 7) is True


# -- which job runs --------------------------------------------------------


def test_nothing_runs_until_upkeep_is_switched_on():
    """Off by default: several hundred requests to agency sites is not
    something this build starts doing on its own."""
    settings = db.get_settings()

    assert settings["maintenance"]["enabled"] is False
    assert maintenance.next_job(settings) is None


def test_contracts_goes_first_when_both_are_due():
    """The cheaper walk, and the one whose findings expire."""
    assert maintenance.next_job(_on()) == "contracts"


def test_the_platform_check_gets_its_turn_once_contracts_is_fresh():
    _on()
    _ran_days_ago("contracts", 1)

    assert maintenance.next_job(db.get_settings()) == "platforms"


def test_neither_runs_when_both_are_fresh():
    _on()
    _ran_days_ago("contracts", 1)
    _ran_days_ago("platforms", 2)

    assert maintenance.next_job(db.get_settings()) is None


def test_a_job_switched_off_individually_never_comes_up():
    _on(contracts_days=0)
    _ran_days_ago("platforms", 1)

    assert maintenance.next_job(db.get_settings()) is None


# -- running one -----------------------------------------------------------


def test_a_run_stamps_the_date_so_it_is_not_due_again(monkeypatch):
    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": lambda: None})

    assert maintenance.run("contracts") == "contracts"
    assert db.get_settings()["internal"]["last_contracts_refresh_on"] == date.today().isoformat()


def test_a_job_that_dies_waits_for_its_next_turn_rather_than_retrying(monkeypatch):
    """Stamped before the work, not after. A job that crashes half way through
    must not be tried again sixty seconds later, and again after that."""
    def boom():
        raise RuntimeError("portal down")

    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": boom})
    maintenance.run("contracts")

    settings = db.get_settings()
    assert settings["internal"]["last_contracts_refresh_on"] == date.today().isoformat()
    assert maintenance.next_job(_on()) != "contracts"


def test_a_failure_is_reported_rather_than_swallowed(monkeypatch):
    def boom():
        raise RuntimeError("portal down")

    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": boom})
    maintenance.run("contracts")

    _, items = db.list_notifications()
    assert any("failed" in n["title"] and "portal down" in n["body"] for n in items)


def test_only_one_job_runs_at_a_time(monkeypatch):
    """A manual "Run now" can land while the scheduler is mid-walk."""
    started = []

    def slow():
        started.append("contracts")
        # Re-entering while this one holds the lock is the case under test.
        assert maintenance.run("platforms") is None

    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": slow, "platforms": lambda: None})
    maintenance.run("contracts")

    assert started == ["contracts"]
    assert db.get_settings()["internal"]["last_platform_check_on"] is None


def test_the_lock_is_released_after_a_failure(monkeypatch):
    def boom():
        raise RuntimeError("nope")

    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": boom})
    maintenance.run("contracts")

    assert maintenance.running() is None


# -- what the jobs report --------------------------------------------------


def test_the_contract_refresh_names_what_is_expiring(monkeypatch):
    from src.contracts import Contract

    soon = date.today() + timedelta(days=30)
    rows = [
        Contract(agency="Hillsborough County", contract_id=f"C{i}",
                 name=f"Janitorial Services Zone {i}", vendor="Acme Facility",
                 end_date=soon, source_id="bonfire_hills")
        for i in range(9)
    ]
    monkeypatch.setattr("src.contracts.refresh", lambda **kw: rows)
    maintenance.refresh_contracts()

    _, items = db.list_notifications()
    (note,) = [n for n in items if n["kind"] == "maintenance"]
    assert "9 expiring within 90 days" in note["body"]
    assert "Janitorial Services Zone 0" in note["body"]
    assert "and 4 more" in note["body"], "five named, the rest counted"


def test_a_register_with_nothing_expiring_still_says_what_it_holds(monkeypatch):
    from src.contracts import Contract

    far = date.today() + timedelta(days=900)
    monkeypatch.setattr("src.contracts.refresh", lambda **kw: [
        Contract(agency="A", contract_id="1", name="Grounds", end_date=far, source_id="s")])
    maintenance.refresh_contracts()

    _, items = db.list_notifications()
    assert "1 contracts on file" in items[0]["body"]


def test_no_register_is_not_an_event(monkeypatch):
    """Not every configured source publishes one. Silence is the right report."""
    monkeypatch.setattr("src.contracts.refresh", lambda **kw: [])
    maintenance.refresh_contracts()

    unread, _ = db.list_notifications()
    assert unread == 0


def test_a_migration_is_reported_with_where_it_went(monkeypatch):
    """The whole point of the check: a moved agency's feed goes quiet rather
    than breaking, so nothing else in the build would ever notice."""
    from src.pipeline.platform_watch import Move, Result

    result = Result(checked=180, unchanged=179, moved=[
        Move(entity_id="mun-city-of-deerfield-beach", name="City of Deerfield Beach",
             was="demandstar", now="ionwave",
             portal_url="https://deerfieldbeach.ionwave.net/Login.aspx")])
    monkeypatch.setattr("src.pipeline.platform_watch.recheck", lambda **kw: result)
    maintenance.check_platforms()

    _, items = db.list_notifications()
    (note,) = [n for n in items if n["kind"] == "platform_move"]
    assert note["title"] == "1 agency changed procurement platform"
    assert "City of Deerfield Beach: demandstar -> ionwave" in note["body"]
    assert "ionwave.net" in note["body"]
    assert "source config needs revisiting" in note["body"]


def test_a_handful_of_unreadable_sites_is_not_worth_a_notification(monkeypatch):
    """Individually these are slow sites and bot walls, not migrations."""
    from src.pipeline.platform_watch import Move, Result

    lost = [Move(entity_id=f"e{i}", name=f"Town {i}", was="civicplus", now="unknown")
            for i in range(4)]
    monkeypatch.setattr("src.pipeline.platform_watch.recheck",
                        lambda **kw: Result(checked=180, unchanged=176, lost=lost))
    maintenance.check_platforms()

    unread, _ = db.list_notifications()
    assert unread == 0


def test_a_sweep_that_mostly_fails_is_worth_knowing(monkeypatch):
    """In bulk it means the sweep itself is being blocked, which is a different
    problem from any one agency moving."""
    from src.pipeline.platform_watch import Move, Result

    lost = [Move(entity_id=f"e{i}", name=f"Town {i}", was="civicplus", now="unknown")
            for i in range(60)]
    monkeypatch.setattr("src.pipeline.platform_watch.recheck",
                        lambda **kw: Result(checked=180, unchanged=120, lost=lost))
    maintenance.check_platforms()

    _, items = db.list_notifications()
    assert any("could not be read" in n["title"] for n in items)
    assert not any(n["kind"] == "platform_move" for n in items)


def test_a_sweep_that_reached_nothing_reports_nothing(monkeypatch):
    """No roster in the image, or no network. Not a migration finding."""
    from src.pipeline.platform_watch import Result

    monkeypatch.setattr("src.pipeline.platform_watch.recheck", lambda **kw: Result())
    maintenance.check_platforms()

    unread, _ = db.list_notifications()
    assert unread == 0


# -- the scheduler ---------------------------------------------------------


@pytest.mark.anyio
async def test_the_tick_runs_a_due_job_off_the_event_loop(monkeypatch):
    """`tick` is on the loop and both walks are minutes of blocking HTTP —
    which is exactly why the register was kept out of the tick to begin with."""
    import asyncio

    from web.services import scheduler

    seen = {}

    def job():
        # A worker thread has no running loop; the event loop's thread does.
        try:
            asyncio.get_running_loop()
            seen["on_loop"] = True
        except RuntimeError:
            seen["on_loop"] = False

    _on()
    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": job})
    await scheduler.tick()

    assert seen["on_loop"] is False, "a maintenance job must not run on the event loop"


@pytest.mark.anyio
async def test_the_tick_leaves_it_alone_when_upkeep_is_off(monkeypatch):
    from web.services import scheduler

    ran = []
    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": lambda: ran.append(1)})
    await scheduler.tick()

    assert ran == []


@pytest.mark.anyio
async def test_maintenance_waits_for_a_fetch_to_finish(monkeypatch):
    """Both walks and a fetch would be competing for the same portals."""
    from web.services import fetch_job as fj
    from web.services import scheduler

    class Busy:
        running = True

        async def start(self):
            return True

    _on()
    ran = []
    monkeypatch.setattr(fj, "job", Busy())
    monkeypatch.setattr(scheduler, "job", Busy())
    monkeypatch.setattr(maintenance, "_JOBS", {"contracts": lambda: ran.append(1)})
    await scheduler.tick()

    assert ran == []


@pytest.mark.anyio
async def test_one_tick_runs_at_most_one_job(monkeypatch):
    """Two multi-minute walks back to back would delay the next tick twice as
    long for no gain — the second is still due tomorrow."""
    from web.services import scheduler

    ran = []
    _on()
    monkeypatch.setattr(maintenance, "_JOBS", {
        "contracts": lambda: ran.append("contracts"),
        "platforms": lambda: ran.append("platforms"),
    })
    await scheduler.tick(datetime.utcnow())

    assert ran == ["contracts"]
