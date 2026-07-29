"""CLI for SF Procurement Scout."""

from __future__ import annotations

from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from .pipeline.runner import (
    filter_opportunities,
    organize_groups,
    print_briefs,
    print_summary_table,
    run_fetch,
)
from .pipeline.store import load_latest, save_snapshot
from .sources.registry import load_source_config

app = typer.Typer(
    name="sf-procurement-scout",
    help="Live South Florida government procurement opportunity aggregator.",
    add_completion=False,
)
console = Console()


@app.command()
def fetch(
    only: Optional[List[str]] = typer.Option(
        None, "--only", help="Source id(s) to fetch (repeatable)."
    ),
    live_only: bool = typer.Option(False, "--live-only", help="Skip catalog-only portals."),
    no_catalog: bool = typer.Option(False, "--no-catalog", help="Exclude catalog entries."),
    open_only: bool = typer.Option(True, "--open-only/--all-status", help="Keep open/upcoming only."),
    county: Optional[str] = typer.Option(None, help="Filter county: miami-dade|broward|palm-beach"),
    category: Optional[str] = typer.Option(None, help="Filter category keyword, e.g. construction"),
    offer_type: Optional[str] = typer.Option(
        None, help="goods|services|construction|professional_services"
    ),
    query: Optional[str] = typer.Option(None, "-q", help="Search title/brief/agency"),
    limit: int = typer.Option(40, help="Max rows to print"),
    briefs: bool = typer.Option(True, "--briefs/--no-briefs", help="Print deal briefs"),
    save: bool = typer.Option(True, "--save/--no-save", help="Write data/latest.json + csv"),
):
    """Fetch live opportunities from configured portals."""
    console.rule("[bold]SF Procurement Scout — Live Fetch[/bold]")
    # Fetch full set (no view filters) so snapshots stay complete.
    all_opps, health = run_fetch(
        only=only,
        live_only=live_only,
        include_catalog=not no_catalog,
        open_only=False,
    )

    _print_health(health)

    if save:
        json_path, csv_path, latest = save_snapshot(all_opps, health)
        console.print(f"[green]Saved[/green] {latest} and {csv_path.name}")

    opps = filter_opportunities(
        all_opps,
        open_only=open_only,
        county=county,
        category=category,
        offer_type=offer_type,
        query=query,
    )

    print_summary_table(opps, limit=limit)
    if briefs:
        console.rule("Deal Briefs")
        print_briefs(opps, limit=min(limit, 25))

    groups = organize_groups(opps)
    console.rule("Organization")
    for label, mapping in [
        ("By county", groups["by_county"]),
        ("By offer type", groups["by_offer_type"]),
        ("By category", groups["by_category"]),
    ]:
        counts = ", ".join(f"{k}={len(v)}" for k, v in sorted(mapping.items(), key=lambda x: -len(x[1])))
        console.print(f"[bold]{label}:[/bold] {counts}")

    console.print(f"\n[bold]Matching opportunities:[/bold] {len(opps)}  (full snapshot: {len(all_opps)})")


HEALTH_STYLES = {
    "ok": ("[green]OK[/green]", ""),
    "empty": ("[dim]empty[/dim]", "no listings published"),
    "degraded": ("[yellow]DEGRADED[/yellow]", ""),
    "error": ("[red]ERROR[/red]", ""),
}


def _print_health(health) -> None:
    ht = Table(title="Source Health")
    ht.add_column("Source")
    ht.add_column("Status")
    ht.add_column("Count", justify="right")
    ht.add_column("ms", justify="right")
    ht.add_column("Detail", overflow="fold")
    for h in health:
        label, fallback = HEALTH_STYLES.get(h.status, (h.status, ""))
        ht.add_row(
            h.name[:38],
            label,
            str(h.count),
            str(h.elapsed_ms),
            (h.error or h.note or fallback)[:70],
        )
    console.print(ht)

    problems = [h for h in health if h.status in {"degraded", "error"}]
    if problems:
        console.print(
            f"[yellow]{len(problems)} source(s) need attention:[/yellow] "
            + ", ".join(h.source_id for h in problems)
        )


@app.command()
def history(
    only: Optional[List[str]] = typer.Option(None, "--only", help="Source id(s) to refresh."),
):
    """Refresh the archive of closed solicitations used for recurrence.

    Runs on its own cadence — history changes slowly, so there is no reason to
    re-download it on every fetch.
    """
    from .pipeline.history import BidHistory, fetch_history, save_history

    console.rule("[bold]Bid history refresh[/bold]")
    records = fetch_history(only=only)
    if not records:
        console.print("[yellow]No source exposed a closed-solicitation archive.[/yellow]")
        raise typer.Exit(1)

    path = save_history(records)
    index = BidHistory(records)
    t = Table(title="Archive by agency")
    t.add_column("Agency")
    t.add_column("Past solicitations", justify="right")
    counts: dict = {}
    for r in records:
        counts[r.agency] = counts.get(r.agency, 0) + 1
    for agency, n in sorted(counts.items(), key=lambda x: -x[1]):
        t.add_row(agency[:44], str(n))
    console.print(t)
    console.print(f"[green]Saved[/green] {len(records)} records ({len(index)} indexed) to {path}")


@app.command()
def health():
    """Show source health from the last saved snapshot."""
    opps, health_rows = load_latest()
    if not health_rows:
        console.print("[yellow]No snapshot found. Run: python run.py fetch[/yellow]")
        raise typer.Exit(1)
    _print_health(health_rows)
    console.print(f"[bold]Opportunities in snapshot:[/bold] {len(opps)}")


@app.command("list-sources")
def list_sources():
    """List configured procurement sources."""
    configs = load_source_config()
    t = Table(title="Configured Sources")
    t.add_column("ID")
    t.add_column("County")
    t.add_column("Live")
    t.add_column("Name")
    t.add_column("Portal")
    for c in configs:
        t.add_row(
            c["id"],
            c["county"],
            "yes" if c.get("live_fetch") else "catalog",
            c["name"][:40],
            c["portal_url"][:50],
        )
    console.print(t)


@app.command()
def show(
    open_only: bool = typer.Option(True, "--open-only/--all-status"),
    county: Optional[str] = typer.Option(None),
    category: Optional[str] = typer.Option(None),
    offer_type: Optional[str] = typer.Option(None),
    query: Optional[str] = typer.Option(None, "-q"),
    limit: int = typer.Option(40),
    briefs: bool = typer.Option(True, "--briefs/--no-briefs"),
):
    """Show last saved snapshot (no network)."""
    opps, health = load_latest()
    if not opps:
        console.print("[yellow]No snapshot found. Run: python run.py fetch[/yellow]")
        raise typer.Exit(1)
    opps = filter_opportunities(
        opps,
        open_only=open_only,
        county=county,
        category=category,
        offer_type=offer_type,
        query=query,
    )
    print_summary_table(opps, limit=limit)
    if briefs:
        print_briefs(opps, limit=min(limit, 25))


@app.command()
def dashboard():
    """Launch Streamlit dashboard (requires streamlit)."""
    import subprocess
    import sys
    from .sources.registry import project_root

    app_path = project_root() / "web" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=False)


def main():
    app()


if __name__ == "__main__":
    main()
