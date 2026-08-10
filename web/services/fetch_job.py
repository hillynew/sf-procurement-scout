"""Background fetch: one job at a time, live progress, SSE fan-out.

The sync pipeline (ThreadPoolExecutor inside ``run_fetch``) runs unchanged
inside ``asyncio.to_thread``; per-source progress events cross back onto the
event loop via ``call_soon_threadsafe`` into per-subscriber queues.
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Set

from src.db import store as db
from src.models.opportunity import Opportunity
from src.pipeline.runner import run_fetch

from .matching import wl_matches

HEARTBEAT_SECONDS = 15


class FetchJob:
    """Singleton owning fetch state. Thread-safe where the pipeline touches it."""

    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._subscribers: Set[asyncio.Queue] = set()
        self._state: Dict = {"state": "idle"}

    # -- public API ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> Dict:
        with self._state_lock:
            return json.loads(json.dumps(self._state, default=str))

    async def start(self) -> bool:
        """Kick off a fetch. False when one is already running."""
        with self._state_lock:
            if self._running:
                return False
            self._running = True
            self._state = {
                "state": "running",
                "started_at": datetime.utcnow().isoformat(),
                "phase": "sources",
                "sources": [],
                "done_count": 0,
                "total": 0,
            }
        self._loop = asyncio.get_running_loop()
        asyncio.create_task(self._run())
        return True

    async def stream(self) -> AsyncIterator[str]:
        """SSE frames: current status first, then live events, then done/error."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.add(queue)
        try:
            snapshot = self.status()
            yield _frame("status", snapshot)
            if snapshot["state"] not in ("running",):
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keeps Render's proxy from buffering/closing
                    continue
                yield _frame(event.get("event", "message"), event)
                if event.get("event") in ("done", "error"):
                    return
        finally:
            self._subscribers.discard(queue)

    # -- internals ----------------------------------------------------------

    async def _run(self) -> None:
        try:
            await self._run_once()
        finally:
            with self._state_lock:
                self._running = False
            # After the run's locals are unreachable: a completed statewide
            # fetch otherwise leaves the process ~300MB above baseline —
            # the rows are gone but their small-object arenas are fragmented,
            # so glibc keeps them. The next fetch then starts from that
            # plateau and the kernel kills it at 512MB: warm-start fetches
            # died overnight where cold-start ones survived.
            await asyncio.to_thread(_release_memory)

    async def _run_once(self) -> None:
        started = datetime.utcnow()
        run_id: Optional[int] = None
        try:
            # The row goes in before the fetch so an OOM kill mid-run leaves
            # evidence: the next run finds it still 'running' and flags it
            # 'died'. Without this, a killed fetch simply never happened.
            run_id = db.record_run_started(started)
            opps, health = await asyncio.to_thread(
                run_fetch,
                include_catalog=False,
                quiet=True,
                on_progress=self._on_progress_from_thread,
            )
            result = db.save_snapshot(opps, health, started_at=started, run_id=run_id)
            new_matches = self._post_fetch(opps, result.new_ids)
            summary = {
                "event": "done",
                "count": result.count,
                "new_count": len(result.new_ids),
                "new_matches": sum(len(v) for v in new_matches.values()),
                "finished_at": datetime.utcnow().isoformat(),
            }
            with self._state_lock:
                self._state = {"state": "done", **summary}
            self._publish(summary)
            # Auto-summaries run after "done" is announced — they can take a
            # while and the UI shouldn't wait on them.
            await asyncio.to_thread(self._auto_summarize, opps)
        except Exception as exc:  # noqa: BLE001 — surfaced, never crashes the app
            message = f"{type(exc).__name__}: {exc}"
            db.record_failed_run(started, message, run_id=run_id)
            settings = db.get_settings()
            if settings["notifications"].get("fetch_events", True):
                db.add_notification("fetch_failed", "Fetch failed", message)
            with self._state_lock:
                self._state = {"state": "error", "error": message}
            self._publish({"event": "error", "error": message})

    def _on_progress_from_thread(self, event: Dict) -> None:
        """Called by pipeline worker threads."""
        with self._state_lock:
            if event["event"] == "start":
                self._state["total"] = event["total"]
            elif event["event"] == "source":
                self._state["sources"].append(event["source"])
                self._state["done_count"] = event["done"]
                self._state["total"] = event["total"]
            elif event["event"] == "phase":
                self._state["phase"] = event["phase"]
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._publish, event)

    def _publish(self, event: Dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except Exception:  # noqa: BLE001
                pass

    def _post_fetch(self, opps: List[Opportunity],
                    new_ids: List[str]) -> Dict[str, List[Opportunity]]:
        """Notifications + instant digest for freshly-seen bids."""
        settings = db.get_settings()
        new_set = set(new_ids)
        new_by_watchlist: Dict[str, List[Opportunity]] = {}
        digest_by_watchlist: Dict[str, List[Opportunity]] = {}
        for wl in db.list_watchlists():
            matches = wl_matches(wl.get("rules") or {}, opps)
            fresh = [o for o in matches if o.opportunity_id in new_set]
            if fresh:
                new_by_watchlist[wl["name"]] = fresh
                if wl.get("email_digest"):
                    digest_by_watchlist[wl["name"]] = fresh

        if settings["notifications"].get("watchlist", True):
            for name, fresh in new_by_watchlist.items():
                lead = fresh[0].title if fresh else ""
                more = f" (+{len(fresh) - 1} more)" if len(fresh) > 1 else ""
                db.add_notification(
                    "watchlist_match",
                    f"{len(fresh)} new in “{name}”",
                    f"{lead}{more}",
                    opportunity_id=fresh[0].opportunity_id if fresh else None,
                )
        if settings["notifications"].get("fetch_events", True):
            db.add_notification(
                "fetch_done",
                f"Fetch finished — {len(opps)} bids",
                f"{len(new_ids)} new since last fetch",
            )
        if settings["digest"].get("enabled") and settings["digest"].get("cadence") == "instant":
            try:
                from . import digest

                digest.send_instant_digest(digest_by_watchlist)
            except Exception:  # noqa: BLE001
                pass
        return new_by_watchlist

    def _auto_summarize(self, opps: List[Opportunity]) -> None:
        try:
            from src.ai import summarizer

            count = summarizer.auto_summarize_tracked(opps, db.workflow_state())
            if count:
                db.add_notification(
                    "summary_ready",
                    f"{count} AI brief{'s' if count != 1 else ''} ready",
                    "Tracked bids were summarized after the fetch.",
                )
        except Exception:  # noqa: BLE001
            pass


def _release_memory() -> None:
    """Return a finished fetch's memory to the OS.

    gc first (parse trees and payload graphs are cycle-heavy), then
    malloc_trim hands the freed arenas back to the kernel — RSS is what the
    OOM killer judges, and Python never trims it on its own.
    """
    import ctypes
    import gc

    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:  # noqa: BLE001 — not glibc; nothing to trim, nothing to do
        pass


def _frame(event: str, data: Dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# The one instance the app uses.
job = FetchJob()
