"""Snapshot reads: the full list, one bid, CSV export."""

from __future__ import annotations

import io
from datetime import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from src.ai.summarizer import PROMPT_VERSION
from src.db import store as db
from web.services.serialize import opp_out

router = APIRouter()


@router.get("/opportunities")
def list_opportunities():
    opps = db.load_opportunities()
    workflow = db.workflow_state()
    summarized = db.summarized_ids(PROMPT_VERSION)
    first_seen = db.first_seen_map()
    run = db.latest_run()
    out = []
    for o in opps:
        data = opp_out(o, workflow, summarized)
        # When the *scout* first saw it — the anchor for "new since my last
        # visit", which posted_date cannot serve (agencies backdate).
        data["first_seen_at"] = first_seen.get(o.opportunity_id)
        out.append(data)
    return {
        "fetched_at": run["finished_at"].isoformat() if run and run["finished_at"] else None,
        "count": len(opps),
        "opportunities": out,
    }


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str):
    opp = db.get_opportunity(opportunity_id)
    if opp is None:
        raise HTTPException(status_code=404, detail="unknown opportunity")
    workflow = db.workflow_state()
    data = opp_out(opp, workflow, db.summarized_ids(PROMPT_VERSION))
    data["ai_summary"] = db.latest_summary(opportunity_id, PROMPT_VERSION)
    return data


@router.get("/export.csv")
def export_csv():
    import pandas as pd

    opps = db.load_opportunities()
    rows = [o.to_row() for o in opps]
    buf = io.StringIO()
    pd.DataFrame(rows).to_csv(buf, index=False)
    stamp = datetime.utcnow().strftime("%Y%m%d")
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="scout-bids-{stamp}.csv"'},
    )
