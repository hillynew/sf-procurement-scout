"""Source health + a real "add a source" flow for CivicPlus portals."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import store as db
from src.sources.registry import load_source_config

router = APIRouter()


@router.get("/sources")
def list_sources():
    health = {h.source_id: h.model_dump(mode="json") for h in db.latest_health()}
    out = []
    for cfg in load_source_config():
        out.append({
            "id": cfg["id"],
            "name": cfg["name"],
            "county": cfg.get("county", ""),
            "agency": cfg.get("agency", ""),
            "adapter": cfg.get("adapter", ""),
            "portal_url": cfg.get("portal_url", ""),
            "live_fetch": bool(cfg.get("live_fetch", True)),
            "custom": False,
            "health": health.get(cfg["id"]),
        })
    for src in db.list_custom_sources():
        src["health"] = health.get(src["id"])
        src["live_fetch"] = True
        out.append(src)
    run = db.latest_run()
    return {
        "sources": out,
        "last_run": {
            "finished_at": run["finished_at"].isoformat() if run and run["finished_at"] else None,
            "status": run["status"] if run else None,
            "opp_count": run["opp_count"] if run else 0,
        } if run else None,
    }


class DetectBody(BaseModel):
    url: str


CIVICPLUS_MARKERS = ("civicplus", "bids.aspx", "civicengage")


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "custom"


@router.post("/sources/detect")
def detect(body: DetectBody):
    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=422, detail="url required")
    if not url.startswith("http"):
        url = "https://" + url
    lowered = url.lower()
    host = urlparse(url).netloc or url

    detected = "unknown"
    if any(m in lowered for m in CIVICPLUS_MARKERS):
        detected = "civicplus"
    else:
        # Sniff the page itself — many CivicPlus sites have vanity domains.
        try:
            from src.http_util import get

            resp = get(url, timeout=10, retries=0)
            page = (resp.text or "")[:200_000].lower()
            if any(m in page for m in CIVICPLUS_MARKERS):
                detected = "civicplus"
        except Exception:  # noqa: BLE001 — unreachable page is just "unknown"
            pass

    name = host.replace("www.", "").split(".")[0].replace("-", " ").title()
    portal_url = url
    if detected == "civicplus" and "bids.aspx" not in lowered:
        portal_url = f"https://{host}/bids.aspx"
    return {
        "detected": detected,
        "name": name,
        "portal_url": portal_url,
        "suggested_id": f"custom-{_slugify(host)}",
        "supported": detected == "civicplus",
        "message": (
            "CivicPlus portal detected — Scout can fetch this."
            if detected == "civicplus"
            else "Not a CivicPlus portal. Only CivicPlus bid pages are supported "
                 "for now; other platforms need an adapter."
        ),
    }


class AddSourceBody(BaseModel):
    id: Optional[str] = None
    name: str
    county: str = "broward"
    agency: Optional[str] = None
    portal_url: str


@router.post("/sources", status_code=201)
def add_source(body: AddSourceBody):
    source_id = body.id or f"custom-{_slugify(urlparse(body.portal_url).netloc or body.name)}"
    existing = {c["id"] for c in load_source_config()}
    if source_id in existing:
        raise HTTPException(status_code=409, detail="a configured source already has this id")
    src = db.add_custom_source(
        source_id=source_id, name=body.name.strip(), county=body.county,
        agency=(body.agency or body.name).strip(), adapter="civicplus",
        portal_url=body.portal_url.strip(),
    )

    # Immediate test fetch so the user knows right away whether it works.
    test = {"ok": False, "count": 0, "error": None}
    try:
        from src.sources.civicplus import CivicPlusAdapter

        adapter = CivicPlusAdapter({**src, "live_fetch": True})
        opps = adapter.fetch()
        test = {"ok": True, "count": len(opps), "error": None}
    except Exception as exc:  # noqa: BLE001
        test = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {exc}"}

    return {"source": src, "test": test}


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: str):
    if not db.delete_custom_source(source_id):
        raise HTTPException(status_code=404, detail="not a custom source")
