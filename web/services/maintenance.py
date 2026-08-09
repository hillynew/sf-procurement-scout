"""The two jobs that keep the build from rotting, each on its own cadence.

Both were run by hand until now, which meant they were run twice and then
forgotten. Neither belongs in the bid fetch, and for the same reason: they are
slow walks whose answers change on the timescale of weeks, not hours.

**Contract register** (`src.contracts.refresh`, weekly). Several thousand rows
per tenant. It is the only leading indicator in the build — an incumbent's end
date says a rebid is coming months before anyone advertises it — and it decays
quietly, because a stale register looks exactly like a current one.

**Platform check** (`src.pipeline.platform_watch.recheck`, monthly). Asks each
identified agency's own website whether it still runs the platform the registry
says it does. This is the guard against the failure mode that has cost this
project five agencies: a live page returning zero rows reads as a quiet agency,
not a migrated one, and no fetch can tell the difference.

## Why they run here rather than in the tick

`scheduler.tick` runs on the event loop. Both of these are minutes of blocking
HTTP, and running them inline would stall the interval fetch, the deadline scan
and the digest behind them — which is exactly why the contract refresh was
excluded from the tick when it was written. So they run in a worker thread, one
at a time, never while a fetch is running, and never two in one tick.

The date is written *before* the work rather than after. A job that crashes
half way is not retried sixty seconds later; it waits for its next turn. A
maintenance job that hammers on failure is worse than one that misses a week.

Both are **off until switched on**, like auto-fetch and the digest. Between
them they make several hundred requests to agency websites, and nothing here
starts doing that on its own.

## What comes out

Notifications, because the output of both is something a person has to act on:
a contract expiring inside the horizon is a bid to prepare, and a migration is
a source config to revisit. On Render's free tier the container's disk is
ephemeral, so the platform check deliberately does not write its results back
to the JSONL — the committed baseline stays the reference, and the notification
is what survives.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import date, datetime
from typing import Dict, List, Optional

from src.db import store as db

#: How many of a job's findings a single notification will name before it stops
#: listing and starts counting. A notification nobody reads is not a warning.
NAMED = 5

#: One maintenance job at a time, process-wide. The scheduler is a single loop,
#: but a manual trigger can arrive from an HTTP request on the same process.
_lock = threading.Lock()
_running: Optional[str] = None


def running() -> Optional[str]:
    """The job currently running, or None."""
    return _running


def due(last_iso: Optional[str], every_days: int, today: Optional[date] = None) -> bool:
    """True when a job has never run, or last ran `every_days` ago or more."""
    if every_days <= 0:
        return False
    if not last_iso:
        return True
    today = today or date.today()
    try:
        last = date.fromisoformat(str(last_iso))
    except ValueError:
        # An unreadable date is not a reason to never run again.
        return True
    return (today - last).days >= every_days


def next_job(settings: Dict[str, dict], today: Optional[date] = None) -> Optional[str]:
    """Which job is due, or None. Contracts first — it is the cheaper walk.

    Per-job switches, because the two jobs earn different defaults: the
    platform check is what catches an agency migrating off the portal we
    read — the failure that has cost this project five agencies — so it runs
    unless switched off. The contract register stays opt-in; it is hundreds
    of requests nobody asked for yet. The legacy `enabled` flag still means
    "both on" for settings saved before the split.
    """
    cfg = settings.get("maintenance") or {}
    legacy_all = bool(cfg.get("enabled"))
    contracts_on = bool(cfg.get("contracts_enabled")) or legacy_all
    platforms_on = bool(cfg.get("platform_check_enabled", True)) or legacy_all
    internal = settings.get("internal") or {}
    if contracts_on and due(
        internal.get("last_contracts_refresh_on"), int(cfg.get("contracts_days") or 0), today
    ):
        return "contracts"
    if platforms_on and due(
        internal.get("last_platform_check_on"), int(cfg.get("platform_check_days") or 0), today
    ):
        return "platforms"
    return None


async def maybe_run(settings: Dict[str, dict], now: Optional[datetime] = None) -> Optional[str]:
    """Run at most one due job, off the event loop. Returns the job it ran."""
    job = next_job(settings, (now or datetime.utcnow()).date())
    if job is None:
        return None
    return await asyncio.to_thread(run, job)


def run(job: str) -> Optional[str]:
    """Run one job to completion. Blocking — call it from a thread."""
    global _running
    with _lock:
        if _running is not None:
            return None
        _running = job
    try:
        # Stamped before the work: a job that dies half way waits for its next
        # turn rather than retrying every sixty seconds.
        db.update_settings({"internal": {_STAMP[job]: date.today().isoformat()}})
        _JOBS[job]()
        return job
    except Exception as e:  # noqa: BLE001 — maintenance must never kill the loop
        db.add_notification(
            "maintenance",
            f"{_TITLE[job]} failed",
            f"{type(e).__name__}: {e}"[:300],
        )
        return job
    finally:
        with _lock:
            _running = None


# -- the jobs --------------------------------------------------------------


def refresh_contracts() -> None:
    from src.contracts import expiring_within, refresh

    found = refresh(quiet=True)
    if not found:
        # Not an error: no configured source has to publish a register.
        return
    soon = expiring_within(found, days=90)
    body = f"{len(found)} contracts on file."
    if soon:
        names = "; ".join(
            f"{c.name[:60]} ({c.agency[:28]}, ends {c.end_date})" for c in soon[:NAMED]
        )
        if len(soon) > NAMED:
            names += f"; and {len(soon) - NAMED} more"
        body = f"{len(soon)} expiring within 90 days. {names}"
    db.add_notification("maintenance", "Contract register refreshed", body[:1000])


def check_platforms() -> None:
    from src.pipeline.platform_watch import recheck

    result = recheck()
    if not result.checked:
        return

    if result.moved:
        db.add_notification(
            "platform_move",
            f"{len(result.moved)} agenc{'y' if len(result.moved) == 1 else 'ies'} "
            "changed procurement platform",
            _moves_body(result.moved),
        )
    if len(result.lost) >= _lost_threshold(result.checked):
        # Individually these are slow sites and WAFs, not migrations. In bulk
        # they mean the sweep itself is being blocked, which is worth knowing
        # and is a different problem from any one agency moving.
        db.add_notification(
            "maintenance",
            f"{len(result.lost)} of {result.checked} agencies could not be read",
            "Usually a slow site or a bot wall rather than a migration, but at "
            "this share it is worth checking the sweep itself. "
            + "; ".join(m.name for m in result.lost[:NAMED]),
        )


def _moves_body(moves: List) -> str:
    lines = [
        f"{m.describe()}" + (f" — {m.portal_url}" if m.portal_url else "")
        for m in moves[:NAMED]
    ]
    if len(moves) > NAMED:
        lines.append(f"and {len(moves) - NAMED} more")
    lines.append("Their source config needs revisiting.")
    return "\n".join(lines)[:1000]


def _lost_threshold(checked: int) -> int:
    """A quarter of the sweep, and never fewer than five."""
    return max(5, checked // 4)


_JOBS = {"contracts": refresh_contracts, "platforms": check_platforms}
_STAMP = {"contracts": "last_contracts_refresh_on", "platforms": "last_platform_check_on"}
_TITLE = {"contracts": "Contract register refresh", "platforms": "Platform check"}
