"""Background fetch control: start, poll, stream."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from web.services.fetch_job import MIN_FETCH_GAP_MINUTES, job

router = APIRouter()


@router.post("/fetch", status_code=202)
async def start_fetch(force: bool = False):
    """Start a fetch. `force=true` is the human pressing "Fetch now".

    Unforced callers — the cron and the app's "on open" refresh — are held to
    `MIN_FETCH_GAP_MINUTES`, so the two schedules cannot stack a second full
    fetch onto a process still carrying the last one's footprint.
    """
    if job.running:
        raise HTTPException(status_code=409, detail="a fetch is already running")
    started = await job.start(force=force)
    if not started:
        raise HTTPException(
            status_code=409,
            detail=(
                f"a fetch finished less than {MIN_FETCH_GAP_MINUTES} minutes ago; "
                "pass force=true to override"
            ),
        )
    return {"state": "running"}


@router.get("/fetch/status")
def fetch_status():
    return job.status()


@router.get("/fetch/stream")
async def fetch_stream():
    return StreamingResponse(
        job.stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Render's proxy buffers by default; this keeps events flowing.
            "X-Accel-Buffering": "no",
        },
    )
