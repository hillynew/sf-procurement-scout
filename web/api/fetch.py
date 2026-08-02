"""Background fetch control: start, poll, stream."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from web.services.fetch_job import job

router = APIRouter()


@router.post("/fetch", status_code=202)
async def start_fetch():
    started = await job.start()
    if not started:
        raise HTTPException(status_code=409, detail="a fetch is already running")
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
