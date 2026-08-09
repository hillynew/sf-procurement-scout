"""Chapter 119 records requests — the day-31 queue, managed.

Sealed bids stop being exempt 30 days after opening when no award posts
(s. 119.071(1)(b)2). Each ripe lead gets a stored letter — phrased as a copy
of an existing record, the s. 119.01(2)(f) framing that keeps the agency's
special service charge near zero — and a status the user advances by hand.
Sending is the user's act; nothing here emails anyone.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import store as db

router = APIRouter()


@router.get("/records")
def records_queue():
    """Refresh from the stored snapshot, then the whole queue, newest-ripe first."""
    added = db.refresh_records_queue()
    return {"added": added, "requests": db.list_records_requests()}


class RecordsPatch(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    contact_email: Optional[str] = None


@router.put("/records/{opportunity_id}")
def update_record(opportunity_id: str, patch: RecordsPatch):
    try:
        updated = db.update_records_request(
            opportunity_id,
            **{k: v for k, v in patch.model_dump().items() if v is not None},
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if updated is None:
        raise HTTPException(status_code=404, detail="unknown request")
    return updated
