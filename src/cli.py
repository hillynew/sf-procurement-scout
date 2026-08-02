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


@app.command("auth-status")
def auth_status():
    """Show which Bonfire agencies have a signed-in vendor session configured.

    Never prints a credential — only which environment variable, if any, is
    supplying one for each host.
    """
    from .auth import describe_bonfire
    from .sources.registry import load_source_config

    configs = [c for c in load_source_config() if c.get("adapter") == "bonfire"]
    t = Table(title="Bonfire vendor sessions")
    t.add_column("Agency")
    t.add_column("Host")
    t.add_column("Session")
    for c in configs:
        host = c.get("bonfire_host", "")
        source = describe_bonfire(host)
        t.add_row(
            c["name"][:36],
            host,
            f"[green]{source}[/green]" if source != "not set" else "[dim]not set[/dim]",
        )
    console.print(t)
    console.print(
        "\nTo add a session: sign in to the agency's Bonfire portal in a browser, "
        "copy the request's Cookie header (dev tools → Network), and set "
        "SF_SCOUT_BONFIRE_COOKIE (or a host-specific "
        "SF_SCOUT_BONFIRE_COOKIE_<HOST>) in your .env. See README."
    )


@app.command("check-mailbox")
def check_mailbox():
    """Verify the bid-alert mailbox is reachable, without running a full fetch.

    Connects read-only, counts recent messages, and reports how many look
    like bid notices — a quick way to confirm SF_SCOUT_IMAP_* is right before
    trusting it in a scheduled fetch.
    """
    from .sources.email_alerts import (
        MailboxNotConfigured,
        is_configured,
        looks_like_a_bid_notice,
        mailbox_settings,
        read_messages,
    )

    if not is_configured():
        console.print(
            "[yellow]No mailbox configured.[/yellow] Set SF_SCOUT_IMAP_HOST, "
            "SF_SCOUT_IMAP_USER and SF_SCOUT_IMAP_PASSWORD — see .env.example."
        )
        raise typer.Exit(1)

    host, user, _ = mailbox_settings()
    console.print(f"Connecting to [bold]{host}[/bold] as [bold]{user}[/bold] (read-only)…")
    try:
        messages = read_messages()
    except MailboxNotConfigured:
        raise
    except Exception as e:  # noqa: BLE001 — report whatever IMAP raised, plainly
        console.print(f"[red]Connection failed:[/red] {type(e).__name__}: {e}")
        raise typer.Exit(1)

    bid_like = sum(1 for m in messages if looks_like_a_bid_notice(m.get("Subject") or ""))
    console.print(f"[green]Connected.[/green] {len(messages)} messages in the lookback window.")
    console.print(f"{bid_like} look like bid notices by subject.")
    if messages and not bid_like:
        console.print(
            "[yellow]None matched.[/yellow] Confirm the mailbox is actually subscribed "
            "to a city's bid alerts, not just receiving other mail."
        )


@app.command("subscribe-links")
def subscribe_links():
    """List each CivicPlus city's 'Notify Me' bid-alert subscription page.

    Subscribing is manual and per-city — this is the checklist, not an
    automation of it. Work down the list, subscribe the mailbox configured in
    SF_SCOUT_IMAP_*, then `python run.py check-mailbox` to confirm it.
    """
    from urllib.parse import urlsplit, urlunsplit

    configs = [c for c in load_source_config() if c.get("adapter") == "civicplus"]
    t = Table(title="CivicPlus bid-alert subscriptions")
    t.add_column("Agency")
    t.add_column("Subscribe here")
    for c in sorted(configs, key=lambda c: c["name"]):
        parts = urlsplit(c["portal_url"])
        notify_url = urlunsplit(
            (parts.scheme, parts.netloc, "/list.aspx", "Mode=Subscribe", "bids")
        )
        t.add_row(c["name"][:36], notify_url)
    console.print(t)
    console.print(
        f"\n{len(configs)} cities. Each subscription is a manual step on that "
        "city's own site — there is no API for it."
    )


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
def dashboard(port: int = 8000):
    """Launch the web dashboard (uvicorn)."""
    import subprocess
    import sys

    subprocess.run(
        [sys.executable, "-m", "uvicorn", "web.server:app",
         "--host", "0.0.0.0", "--port", str(port)],
        check=False,
    )


@app.command("import-legacy-state")
def import_legacy_state():
    """One-shot: migrate data/user_state.json (pre-database) into the database."""
    import json

    from .db import store as db
    from .pipeline.store import data_dir

    path = data_dir() / "user_state.json"
    if not path.exists():
        console.print("[yellow]No data/user_state.json found — nothing to import.[/yellow]")
        raise typer.Exit(0)
    raw = json.loads(path.read_text(encoding="utf-8"))
    db.bootstrap()

    imported = 0
    for oid in (raw.get("tracked") or {}):
        db.set_tracked(oid, True)
        stage = (raw.get("stages") or {}).get(oid)
        fields = {}
        if stage in db.STAGES:
            fields["stage"] = stage
        decision = (raw.get("decisions") or {}).get(oid)
        if decision in ("go", "nogo"):
            fields["decision"] = decision
        notes = (raw.get("notes") or {}).get(oid)
        if notes:
            fields["notes"] = notes
        checks = (raw.get("checks") or {}).get(oid)
        if checks:
            fields["checks"] = {str(k): bool(v) for k, v in checks.items()}
        if fields:
            db.update_tracked(oid, **fields)
        outcome_line = (raw.get("results") or {}).get(oid, "")
        if outcome_line:
            outcome = "won" if "won" in outcome_line.lower() else "lost"
            digits = "".join(ch for ch in outcome_line if ch.isdigit())
            cents = int(digits) * 100 if digits else None
            db.set_result(oid, outcome, amount_cents=cents)
        imported += 1

    for wl in raw.get("watchlists") or []:
        filters = wl.get("filters") or {}
        rules = {}
        if filters.get("keywords"):
            rules["keywords"] = filters["keywords"]
        if filters.get("counties"):
            rules["counties"] = filters["counties"]
        if filters.get("offers"):
            rules["offers"] = filters["offers"]
        if filters.get("max_value"):
            rules["max_value"] = filters["max_value"]
        if rules and not any(w["rules"] == rules for w in db.list_watchlists()):
            db.create_watchlist(wl.get("name") or "Imported watchlist", rules)

    console.print(f"[green]Imported {imported} tracked bid(s) into the database.[/green]")


def main():
    app()


if __name__ == "__main__":
    main()
