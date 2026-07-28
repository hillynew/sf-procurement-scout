"""Fetch all sources, classify, dedupe, summarize."""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from rich.console import Console
from rich.table import Table

from ..http_util import SourceBlocked
from ..models.opportunity import HealthStatus, Opportunity, SourceHealth
from ..sources.base import SourceAdapter
from ..sources.registry import get_adapters
from ..summarize import apply_briefs

console = Console()

# Portals are independent, so fetch them concurrently. Kept modest to stay
# polite to public government sites (each adapter also paces its own requests).
MAX_WORKERS = 6

# An "open" listing with no published due date is only credible for so long;
# some portals never retire their rows.
STALE_OPEN_DAYS = 180


def _normalize_status(opps: List[Opportunity]) -> None:
    """Mark open items past due as closed, and age out undated stale rows."""
    now = datetime.now()
    stale_before = (now - timedelta(days=STALE_OPEN_DAYS)).date()
    for o in opps:
        if o.status != "open":
            continue
        if o.due_date:
            due = o.due_date
            # Compare naive-to-naive to avoid tz mismatches from parsers
            if due.tzinfo is not None:
                due = due.replace(tzinfo=None)
            if due < now:
                o.status = "closed"
        elif o.posted_date and o.posted_date < stale_before:
            # No due date and posted long ago — treat as expired rather than
            # advertising a years-old solicitation as currently open.
            o.status = "closed"


def _classify_health(
    adapter: SourceAdapter,
    opps: List[Opportunity],
    elapsed_ms: int,
) -> SourceHealth:
    """Turn a successful fetch into a health record.

    Returning zero rows without raising is the most common way a scraper
    fails, so it gets its own status instead of counting as OK.
    """
    if adapter.degraded_reason:
        status, note = HealthStatus.DEGRADED, adapter.degraded_reason
    elif opps:
        status, note = HealthStatus.OK, None
    elif adapter.allows_empty:
        status, note = HealthStatus.EMPTY, "portal listed no open solicitations"
    else:
        status, note = HealthStatus.DEGRADED, "fetched but parsed zero rows"

    return SourceHealth(
        source_id=adapter.source_id,
        name=adapter.name,
        ok=status in (HealthStatus.OK, HealthStatus.EMPTY),
        count=len(opps),
        elapsed_ms=elapsed_ms,
        status=status,
        note=note,
    )


def _fetch_one(adapter: SourceAdapter) -> Tuple[List[Opportunity], SourceHealth]:
    t0 = time.time()
    try:
        opps = adapter.fetch()
        elapsed = int((time.time() - t0) * 1000)
        return opps, _classify_health(adapter, opps, elapsed)
    except SourceBlocked as e:
        elapsed = int((time.time() - t0) * 1000)
        return [], SourceHealth(
            source_id=adapter.source_id,
            name=adapter.name,
            ok=False,
            count=0,
            error=str(e),
            elapsed_ms=elapsed,
            status=HealthStatus.DEGRADED,
            note="portal blocked this client",
        )
    except Exception as e:  # noqa: BLE001 — one bad portal must not stop the run
        elapsed = int((time.time() - t0) * 1000)
        return [], SourceHealth(
            source_id=adapter.source_id,
            name=adapter.name,
            ok=False,
            count=0,
            error=f"{type(e).__name__}: {e}",
            elapsed_ms=elapsed,
            status=HealthStatus.ERROR,
        )


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
    max_workers: int = MAX_WORKERS,
    quiet: bool = False,
) -> Tuple[List[Opportunity], List[SourceHealth]]:
    adapters = get_adapters(
        only=only,
        live_only=live_only,
        include_catalog=include_catalog,
    )
    all_opps: List[Opportunity] = []
    health: List[SourceHealth] = []

    workers = max(1, min(max_workers, len(adapters))) if adapters else 1
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_one, a): a for a in adapters}
        for fut in as_completed(futures):
            opps, h = fut.result()
            all_opps.extend(opps)
            health.append(h)
            if not quiet:
                console.print(_health_line(h))

    # Preserve config order so output is stable across runs.
    order = {a.source_id: i for i, a in enumerate(adapters)}
    health.sort(key=lambda h: order.get(h.source_id, 99))

    _normalize_status(all_opps)
    all_opps = dedupe(all_opps)
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


def _health_line(h: SourceHealth) -> str:
    mark = {
        HealthStatus.OK.value: "[green]✓[/green]",
        HealthStatus.EMPTY.value: "[dim]○[/dim]",
        HealthStatus.DEGRADED.value: "[yellow]![/yellow]",
        HealthStatus.ERROR.value: "[red]✗[/red]",
    }.get(h.status, "?")
    detail = h.error or h.note or ""
    suffix = f" — {detail}" if detail else ""
    return f"{mark} {h.name}: {h.count} opportunities ({h.elapsed_ms} ms){suffix}"


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

_REF_NOISE = re.compile(r"[^a-z0-9]+")
_TITLE_NOISE = re.compile(r"[^a-z0-9 ]+")


def _ref_key(o: Opportunity) -> Optional[str]:
    if not o.external_id:
        return None
    ref = _REF_NOISE.sub("", o.external_id.lower())
    return f"{o.county}|{ref}" if len(ref) >= 5 else None


def _title_key(o: Opportunity) -> str:
    title = _TITLE_NOISE.sub(" ", (o.title or "").lower())
    title = re.sub(r"\s+", " ", title).strip()
    return f"{o.county}|{o.agency.lower()}|{title}"


def _completeness(o: Opportunity) -> tuple:
    """Rank duplicate records so the richest one survives."""
    return (
        o.status != "catalog",  # a real listing beats a registration pointer
        o.due_date is not None,
        o.posted_date is not None,
        len(o.description or ""),
        len(o.categories or []),
        o.external_id is not None,
        len(o.title or ""),
    )


def dedupe(opps: List[Opportunity]) -> List[Opportunity]:
    """Collapse the same solicitation appearing more than once.

    Portals overlap (a county bid is often mirrored on an aggregator) and some
    pages list one solicitation under several announcement rows. Matching is on
    reference number first, then on agency + normalized title.
    """
    best: Dict[str, Opportunity] = {}
    aliases: Dict[str, str] = {}

    for o in sorted(opps, key=_completeness, reverse=True):
        ref, title = _ref_key(o), _title_key(o)
        keys = [k for k in (ref, title) if k]

        existing = aliases.get(ref) if ref else None
        if existing is None and title in aliases:
            candidate = best[aliases[title]]
            # Same title but a different reference number means two distinct
            # solicitations (e.g. re-bids), so only merge when refs agree or
            # one side has no reference at all.
            other_ref = _ref_key(candidate)
            if ref is None or other_ref is None or ref == other_ref:
                existing = aliases[title]

        if existing is not None:
            kept = best[existing]
            # Merge the few fields a thinner duplicate may still contribute.
            if kept.due_date is None and o.due_date is not None:
                kept.due_date = o.due_date
            if kept.posted_date is None and o.posted_date is not None:
                kept.posted_date = o.posted_date
            if not kept.contact and o.contact:
                kept.contact = o.contact
            if not kept.budget and o.budget:
                kept.budget = o.budget
            for c in o.categories or []:
                if c not in kept.categories:
                    kept.categories.append(c)
            # Remember this record's keys so later duplicates also collapse here.
            for k in keys:
                aliases.setdefault(k, existing)
            continue

        anchor = keys[0]
        best[anchor] = o
        for k in keys:
            aliases.setdefault(k, anchor)

    # Restore input order for records that survived.
    survivors = {id(o) for o in best.values()}
    return [o for o in opps if id(o) in survivors]


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
