"""Stats, notifications, settings, demo — the small routers in one module."""

from __future__ import annotations

from typing import List, Optional, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import store as db
from web.services.stats import build_stats

router = APIRouter()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/stats")
def stats():
    return build_stats(db.load_opportunities(), db.workflow_state())


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.get("/notifications")
def notifications():
    unread, items = db.list_notifications()
    return {"unread_count": unread, "items": items}


class ReadBody(BaseModel):
    ids: Union[List[int], str]  # explicit ids, or "all"


@router.post("/notifications/read")
def mark_read(body: ReadBody):
    if body.ids == "all":
        count = db.mark_notifications_read(None)
    elif isinstance(body.ids, list):
        count = db.mark_notifications_read(body.ids)
    else:
        raise HTTPException(status_code=422, detail='ids must be a list or "all"')
    return {"marked": count}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _capabilities() -> dict:
    from src.ai import summarizer
    from src.db.engine import is_postgres
    from web.services import digest

    return {
        "ai_available": summarizer.enabled(),
        "email_available": digest.enabled(),
        "db_backend": "postgres" if is_postgres() else "sqlite",
        "ai_models": list(summarizer.ALLOWED_MODELS),
    }


def _maintenance_status(settings: dict) -> dict:
    """When the slow walks last ran, and whether one is running now.

    Read-only, and separate from the `maintenance` settings section: a cadence
    is something you set, a last-run date is something you are told. Without it
    the UI can only offer to schedule work it cannot say has ever happened.
    """
    from web.services import maintenance

    internal = settings.get("internal") or {}
    return {
        "last_contracts_refresh_on": internal.get("last_contracts_refresh_on"),
        "last_platform_check_on": internal.get("last_platform_check_on"),
        "running": maintenance.running(),
    }


@router.get("/settings")
def get_settings():
    settings = db.get_settings()
    status = _maintenance_status(settings)
    settings.pop("internal", None)
    return {
        "settings": settings,
        "capabilities": _capabilities(),
        "maintenance_status": status,
    }


class SettingsPatch(BaseModel):
    auto_fetch: Optional[dict] = None
    notifications: Optional[dict] = None
    digest: Optional[dict] = None
    ai: Optional[dict] = None
    maintenance: Optional[dict] = None


@router.put("/settings")
def put_settings(body: SettingsPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    settings = db.update_settings(patch)
    status = _maintenance_status(settings)
    settings.pop("internal", None)
    return {
        "settings": settings,
        "capabilities": _capabilities(),
        "maintenance_status": status,
    }


class MaintenanceBody(BaseModel):
    job: str  # contracts | platforms


@router.post("/settings/maintenance/run")
async def run_maintenance(body: MaintenanceBody):
    """Run a maintenance job now, without waiting for its cadence.

    Returns as soon as the job is handed to a worker thread — both jobs take
    minutes, and a request that waited for one would time out long before it
    finished. The result arrives as a notification, the same way the scheduled
    run reports it.
    """
    import asyncio

    from web.services import maintenance

    if body.job not in ("contracts", "platforms"):
        raise HTTPException(status_code=422, detail=f"unknown job: {body.job}")
    if maintenance.running():
        return {"started": False, "running": maintenance.running()}
    asyncio.create_task(asyncio.to_thread(maintenance.run, body.job))
    return {"started": True, "running": body.job}


@router.post("/settings/digest/test")
def test_digest_email():
    """Send a one-off email so the user can confirm the wiring from the UI."""
    from web.services import digest

    sent, error, recipient = digest.send_test_email()
    return {"sent": sent, "error": error, "recipient": recipient}


class PurgeBody(BaseModel):
    target: str  # snapshot | workflow | summaries | notifications | pdf_cache | contractors


@router.post("/settings/data/purge")
def purge(body: PurgeBody):
    try:
        db.purge(body.target)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"purged": body.target}


# ---------------------------------------------------------------------------
# Demo data
# ---------------------------------------------------------------------------


@router.post("/demo")
def load_demo():
    from web.sample_data import load_sample

    result = load_sample()
    return result
