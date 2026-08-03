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


@router.get("/settings")
def get_settings():
    settings = db.get_settings()
    settings.pop("internal", None)
    return {"settings": settings, "capabilities": _capabilities()}


class SettingsPatch(BaseModel):
    auto_fetch: Optional[dict] = None
    notifications: Optional[dict] = None
    digest: Optional[dict] = None
    ai: Optional[dict] = None


@router.put("/settings")
def put_settings(body: SettingsPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    settings = db.update_settings(patch)
    settings.pop("internal", None)
    return {"settings": settings, "capabilities": _capabilities()}


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
