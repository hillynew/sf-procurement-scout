"""Fetch all sources, classify, summarize."""

from __future__ import annotations

import time
from datetime import datetime
from typing import List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from ..models.opportunity import Opportunity, SourceHealth
from ..sources.registry import get_adapters
from ..summarize import apply_briefs

console = Console()


def _normalize_status(opps: List[Opportunity]) -> None:
    """Mark open items past due as closed (when a due date is known)."""
    now = datetime.now()
    for o in opps:
        if o.status != "open" or not o.due_date:
            continue
        due = o.due_date
        # Compare naive-to-naive to avoid tz mismatches from parsers
        if due.tzinfo is not None:
            due = due.replace(tzinfo=None)
        if due < now:
            o.status = "closed"


def run_fetch(
    *,
    only: Optional[List[str]] = None,
    live_only: bool = False,
    include_catalog: bool = True,
    open_only: bool = False,
    county: Optional[str] = None,
    category: Optional[str] = None,
    offer_type: Optional[str] = None,
    query: Optional[str] = None,
) -> Tuple[List[Opportunity], List[SourceHealth]]:
    adapters = get_adapters(
        only=only,
        live_only=live_only,
        include_catalog=include_catalog,
    )
    all_opps: List[Opportunity] = []
    health: List[SourceHealth] = []

    for adapter in adapters:
        t0 = time.time()
        try:
            opps = adapter.fetch()
            elapsed = int((time.time() - t0) * 1000)
            health.append(
                SourceHealth(
                    source_id=adapter.source_id,
                    name=adapter.name,
                    ok=True,
                    count=len(opps),
                    elapsed_ms=elapsed,
                )
            )
            all_opps.extend(opps)
            console.print(
                f"[green]✓[/green] {adapter.name}: {len(opps)} opportunities ({elapsed} ms)"
            )
        except Exception as e:
            elapsed = int((time.time() - t0) * 1000)
            health.append(
                SourceHealth(
                    source_id=adapter.source_id,
                    name=adapter.name,
                    ok=False,
                    count=0,
                    error=str(e),
                    elapsed_ms=elapsed,
                )
            )
            console.print(f"[red]✗[/red] {adapter.name}: {e}")

    _normalize_status(all_opps)
    apply_briefs(all_opps)
    filtered = filter_opportunities(
        all_opps,
        open_only=open_only,
        county=county,
        category=category,
        offer_type=offer_type,
        query=query,
    )
    return filtered, health


def filter_opportunities(
    opps: List[Opportunity],
    *,
    open_only: bool = False,
    county: Optional[str] = None,
    category: Optional[str] = None,
    offer_type: Optional[str] = None,
    query: Optional[str] = None,
) -> List[Opportunity]:
    out = opps
    if open_only:
        out = [o for o in out if o.status in {"open", "upcoming"}]
    if county:
        c = county.lower().replace(" ", "-")
        out = [o for o in out if o.county == c or c in o.county]
    if category:
        cat = category.lower()
        out = [
            o
            for o in out
            if cat in [x.lower() for x in o.categories]
            or cat in (o.offer_type or "").lower()
        ]
    if offer_type:
        ot = offer_type.lower()
        out = [o for o in out if (o.offer_type or "").lower() == ot]
    if query:
        q = query.lower()
        out = [
            o
            for o in out
            if q in (o.title or "").lower()
            or q in (o.brief or "").lower()
            or q in (o.description or "").lower()
            or q in (o.agency or "").lower()
            or q in (o.external_id or "").lower()
        ]
    # sort: open first, soonest due
    def sort_key(o: Opportunity):
        status_rank = {"open": 0, "upcoming": 1, "catalog": 2, "closed": 3, "cancelled": 4}
        due = o.due_date.timestamp() if o.due_date else float("inf")
        return (status_rank.get(o.status, 9), due, o.county, o.agency, o.title)

    return sorted(out, key=sort_key)


def print_summary_table(opps: List[Opportunity], limit: int = 40) -> None:
    table = Table(title=f"Procurement Opportunities ({len(opps)} shown up to {limit})")
    table.add_column("Due", style="cyan", no_wrap=True)
    table.add_column("County", style="magenta")
    table.add_column("Type", style="yellow")
    table.add_column("Offer")
    table.add_column("Agency")
    table.add_column("Title", overflow="fold")
    table.add_column("URL", overflow="fold")

    for o in opps[:limit]:
        due = o.due_date.strftime("%Y-%m-%d") if o.due_date else o.status
        if o.days_until_due is not None and o.status == "open":
            due = f"{due} ({o.days_until_due}d)"
        sol = o.solicitation_type.value if hasattr(o.solicitation_type, "value") else str(o.solicitation_type)
        offer = o.offer_type.value if hasattr(o.offer_type, "value") else str(o.offer_type)
        table.add_row(
            due,
            o.county,
            sol,
            offer,
            o.agency[:28],
            o.title[:80],
            o.url[:60],
        )
    console.print(table)


def print_briefs(opps: List[Opportunity], limit: int = 25) -> None:
    for i, o in enumerate(opps[:limit], 1):
        console.print(f"\n[bold]{i}.[/bold] {o.brief}")
        console.print(f"   [link={o.url}]{o.url}[/link]")


def organize_groups(opps: List[Opportunity]) -> dict:
    """Group opportunities for reporting."""
    by_county: dict = {}
    by_category: dict = {}
    by_offer: dict = {}
    by_agency: dict = {}
    for o in opps:
        by_county.setdefault(o.county, []).append(o)
        by_offer.setdefault(o.offer_type or "unknown", []).append(o)
        by_agency.setdefault(o.agency, []).append(o)
        for c in o.categories or ["general"]:
            by_category.setdefault(c, []).append(o)
    return {
        "by_county": by_county,
        "by_category": by_category,
        "by_offer_type": by_offer,
        "by_agency": by_agency,
    }
