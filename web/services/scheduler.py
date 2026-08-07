"""One asyncio loop: interval auto-fetch, daily deadline scan, daily digest.

Runs only while the process is awake — on Render's free tier that means
"while someone is using the app (or an external pinger keeps it warm)".
The Settings UI says so plainly.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from src.db import store as db

from . import maintenance
from .fetch_job import job

TICK_SECONDS = 60


async def loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            await tick()
        except Exception:  # noqa: BLE001 — the scheduler must never die
            pass


async def tick(now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    settings = db.get_settings()

    # Interval auto-fetch.
    auto = settings["auto_fetch"]
    if auto.get("mode") == "interval" and not job.running:
        run = db.latest_run()
        last = run["finished_at"] if run else None
        interval = timedelta(minutes=max(30, int(auto.get("interval_minutes") or 240)))
        if last is None or now - last >= interval:
            await job.start()

    internal = settings["internal"]
    today_iso = date.today().isoformat()

    # Daily deadline scan → notifications.
    if internal.get("last_deadline_scan_on") != today_iso:
        _deadline_scan(settings)
        db.update_settings({"internal": {"last_deadline_scan_on": today_iso}})

    # Daily digest at the configured hour (UTC).
    digest_cfg = settings["digest"]
    if (
        digest_cfg.get("enabled")
        and digest_cfg.get("cadence") == "daily"
        and now.hour >= int(digest_cfg.get("hour") or 7)
        and internal.get("last_digest_on") != today_iso
    ):
        from . import digest

        digest.send_daily_digest(db.load_opportunities(present_only=True))
        db.update_settings({"internal": {"last_digest_on": today_iso}})

    # Last, and off the loop. The slow walks — the contract register weekly, the
    # platform check monthly — are minutes of blocking HTTP each, which is
    # exactly why the register was kept out of this tick when it was written.
    # `maintenance` hands them to a worker thread and runs at most one per tick,
    # so the await here delays only the *next* tick, never the digest or the
    # deadline scan above it, and never the loop itself. Both still run by hand:
    # `python -m src.cli contracts --refresh`,
    # `scripts/fingerprint_agencies.py --recheck`.
    if not job.running:
        await maintenance.maybe_run(settings, now)


def _deadline_scan(settings: dict) -> None:
    window = int(settings["notifications"].get("deadline_days") or 5)
    workflow = db.workflow_state()
    if not workflow:
        return
    by_id = {o.opportunity_id: o for o in db.load_opportunities()}
    for oid, wf in workflow.items():
        if wf["archived"] or wf["stage"] == "result":
            continue
        opp = by_id.get(oid)
        if opp is None or opp.days_until_due is None:
            continue
        if 0 <= opp.days_until_due <= window:
            db.add_notification(
                "deadline_soon",
                f"Due in {opp.days_until_due} day{'s' if opp.days_until_due != 1 else ''}: "
                f"{opp.title}",
                f"{opp.agency} · stage: {wf['stage']}",
                opportunity_id=oid,
            )
