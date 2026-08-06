"""Email digests via Resend. Inert without RESEND_API_KEY."""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import httpx

from src.db import store as db
from src.fl_geo import ALL_REGIONS
from src.models.opportunity import Opportunity
from src.protest import RECORDS_RIPE_DAYS, business_hours_left
from src.records import ripe_for_request

RESEND_URL = "https://api.resend.com/emails"

#: Kept as a name for backwards compatibility, but the labels now come from the
#: statewide geography module — a hard-coded tri-county map would print raw
#: slugs like "st-johns" for every agency outside South Florida.
COUNTY_LABEL = ALL_REGIONS


def resend_key() -> Optional[str]:
    return os.environ.get("RESEND_API_KEY") or None


def enabled() -> bool:
    return resend_key() is not None


def _recipient(settings: dict) -> str:
    return (settings["digest"].get("email")
            or os.environ.get("SF_SCOUT_DIGEST_TO", "")).strip()


def _sender() -> str:
    return os.environ.get("SF_SCOUT_DIGEST_FROM", "Scout <onboarding@resend.dev>")


def _fmt_value(o: Opportunity) -> str:
    n = o.budget_amount
    if n is None:
        return ""
    if n >= 1_000_000:
        return f" — ${n / 1_000_000:.1f}M est".replace(".0M", "M")
    if n >= 1_000:
        return f" — ${round(n / 1_000)}k est"
    return f" — ${n} est"


def _bid_line(o: Opportunity) -> str:
    due = f"due in {o.days_until_due}d" if o.days_until_due is not None else "no due date"
    county = COUNTY_LABEL.get(o.county, o.county)
    return (
        f'<li style="margin:0 0 10px"><a href="{o.url}" '
        f'style="color:#6E56F8;font-weight:600;text-decoration:none">{o.title}</a>'
        f'<br><span style="color:#5A6478;font-size:13px">{o.agency} · {county} · '
        f"{due}{_fmt_value(o)}</span></li>"
    )


def _wrap(title: str, inner: str) -> str:
    return (
        '<div style="font-family:system-ui,-apple-system,sans-serif;max-width:640px;'
        'margin:0 auto;padding:24px;color:#1B2437">'
        f'<h2 style="margin:0 0 4px">{title}</h2>'
        '<p style="margin:0 0 20px;color:#5A6478;font-size:13px">SF Procurement Scout</p>'
        f"{inner}</div>"
    )


def _resend_error(resp: httpx.Response) -> str:
    """Resend's JSON error, reduced to one line a human can act on."""
    try:
        body = resp.json()
    except ValueError:
        body = {}
    message = body.get("message") or (resp.text or "").strip()[:200]
    if resp.status_code == 401 or resp.status_code == 403:
        return message or "Resend rejected the API key (401)."
    if resp.status_code == 422:
        return message or "Resend rejected the message (422) — check the sender address."
    if resp.status_code == 429:
        return message or "Resend rate limit reached — try again shortly."
    return f"Resend returned {resp.status_code}" + (f": {message}" if message else "")


def send_email_detailed(subject: str, html: str) -> Tuple[bool, Optional[str]]:
    """One call site for Resend. Returns (accepted, error) — error is None on success.

    Callers in the pipeline use :func:`send_email` and ignore the reason; the
    Settings "send test" path shows it, which is the only way a user can tell a
    bad key from a bad recipient without reading server logs.
    """
    key = resend_key()
    settings = db.get_settings()
    to = _recipient(settings)
    if not key:
        return False, "RESEND_API_KEY is not set in the environment."
    if not to:
        return False, "No recipient — set one in Settings or SF_SCOUT_DIGEST_TO."
    try:
        resp = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {key}"},
            json={"from": _sender(), "to": [to], "subject": subject, "html": html},
            timeout=15,
        )
    except Exception as exc:  # noqa: BLE001 — email must never break the pipeline
        return False, f"Could not reach Resend: {type(exc).__name__}"
    if resp.status_code >= 300:
        return False, _resend_error(resp)
    return True, None


def send_email(subject: str, html: str) -> bool:
    """Returns True when Resend accepted the message."""
    ok, _ = send_email_detailed(subject, html)
    return ok


def send_instant_digest(new_by_watchlist: Dict[str, List[Opportunity]]) -> bool:
    """After a fetch: new matches for digest-enabled watchlists."""
    sections = []
    total = 0
    for name, matches in new_by_watchlist.items():
        if not matches:
            continue
        total += len(matches)
        items = "".join(_bid_line(o) for o in matches[:10])
        sections.append(f'<h3 style="margin:20px 0 8px">{name}</h3>'
                        f'<ul style="padding-left:18px;margin:0">{items}</ul>')
    if not total:
        return False
    subject = f"Scout: {total} new bid{'s' if total != 1 else ''} matching your watchlists"
    return send_email(subject, _wrap("New watchlist matches", "".join(sections)))


def _award_section(opps: List[Opportunity]) -> Optional[Tuple[int, str]]:
    """(count, html) for intended awards whose protest window is still open.

    Expired windows are dropped rather than listed: once the 72 hours are gone
    there is nothing to do with the notice, and carrying it forward would train
    the reader to skim the one section that must never be skimmed.
    """
    live = []
    for o in opps:
        if o.status != "award" or o.protest_deadline is None:
            continue
        left = business_hours_left(o.protest_deadline)
        if left is not None and left > 0:
            live.append((left, o))
    if not live:
        return None

    live.sort(key=lambda pair: pair[0])
    rows = []
    for left, o in live[:10]:
        urgency = "#B42318" if left <= 24 else "#B54708"
        when = f"{left:.0f}h left" if left >= 1 else "under an hour"
        rows.append(
            f'<li style="margin:0 0 8px"><a href="{o.url}" style="color:#1849A9">{o.title}</a>'
            f'<br><span style="color:{urgency};font-weight:600;font-size:13px">'
            f"protest window: {when}</span>"
            f'<span style="color:#5A6478;font-size:13px"> · {o.agency}'
            f" · due {o.protest_deadline:%a %-d %b %-I:%M%p}</span></li>"
        )
    html = (
        '<h3 style="margin:20px 0 8px">Intended awards — 72-hour protest window</h3>'
        '<p style="margin:0 0 8px;color:#5A6478;font-size:13px">'
        "A notice of protest is due within 72 hours of posting, excluding weekends "
        "and state holidays (s. 120.57(3)(b), F.S.).</p>"
        f'<ul style="padding-left:18px;margin:0">{"".join(rows)}</ul>'
    )
    return len(live), html


def _records_section(opps: List[Opportunity]) -> Optional[Tuple[int, str]]:
    """(count, html) for tabulations that crossed day 31 today.

    Only the ones that became requestable *today*. The backlog is real and
    worth working, but a digest that repeats it every morning is a digest
    nobody finishes reading — the daily email's job is to report what changed.
    """
    leads = [lead for lead in ripe_for_request(opps) if lead.ripe_for_days == 0]
    if not leads:
        return None

    rows = "".join(
        f'<li style="margin:0 0 8px"><a href="{lead.opportunity.url}" '
        f'style="color:#1849A9">{lead.opportunity.title}</a>'
        f'<br><span style="color:#5A6478;font-size:13px">{lead.opportunity.agency}'
        f" · opened {lead.ripe_on - timedelta(days=RECORDS_RIPE_DAYS):%-d %b}"
        " · no award posted</span></li>"
        for lead in leads[:10]
    )
    html = (
        '<h3 style="margin:20px 0 8px">Bid tabulations now requestable</h3>'
        '<p style="margin:0 0 8px;color:#5A6478;font-size:13px">'
        "Sealed bids stop being exempt 30 days after opening when no intended "
        "decision has been posted (s. 119.071(1)(b)2, F.S.), so these can be "
        "requested as of today.</p>"
        f'<ul style="padding-left:18px;margin:0">{rows}</ul>'
    )
    return len(leads), html


def build_daily_digest(
    opps: List[Opportunity],
    workflow: Dict[str, dict],
    watchlists: List[dict],
) -> Optional[Tuple[str, str]]:
    """(subject, html) for today's digest, or None when there is nothing to say."""
    from .matching import wl_matches

    sections: List[str] = []

    # Intended awards go first and unconditionally. Everything else in this
    # email keeps until tomorrow; a protest is due within 72 hours of the
    # notice posting, excluding weekends, so a digest that buries one below the
    # watchlists has already wasted a meaningful fraction of the window.
    awards = _award_section(opps)
    if awards:
        sections.append(awards[1])

    records = _records_section(opps)
    if records:
        sections.append(records[1])

    total_new = 0
    for wl in watchlists:
        if not wl.get("email_digest"):
            continue
        matches = wl_matches(wl.get("rules") or {}, opps)
        seen = set(wl.get("seen_ids") or [])
        fresh = [o for o in matches if o.opportunity_id not in seen]
        if fresh:
            total_new += len(fresh)
            items = "".join(_bid_line(o) for o in fresh[:10])
            sections.append(f'<h3 style="margin:20px 0 8px">{wl["name"]}</h3>'
                            f'<ul style="padding-left:18px;margin:0">{items}</ul>')

    by_id = {o.opportunity_id: o for o in opps}
    deadlines = []
    for oid, wf in workflow.items():
        if wf["archived"] or wf["stage"] == "result":
            continue
        opp = by_id.get(oid)
        if opp and opp.days_until_due is not None and 0 <= opp.days_until_due <= 7:
            deadlines.append(opp)
    deadlines.sort(key=lambda o: o.days_until_due or 0)
    if deadlines:
        items = "".join(_bid_line(o) for o in deadlines[:10])
        sections.append('<h3 style="margin:20px 0 8px">Tracked bids due this week</h3>'
                        f'<ul style="padding-left:18px;margin:0">{items}</ul>')

    problems = [h for h in db.latest_health() if str(h.status) in ("degraded", "error")]
    if problems:
        rows = "".join(
            f'<li style="margin:0 0 6px;color:#5A6478;font-size:13px">'
            f"{h.name} — {h.status}{(': ' + h.error) if h.error else ''}</li>"
            for h in problems[:6]
        )
        sections.append('<h3 style="margin:20px 0 8px">Sources needing attention</h3>'
                        f'<ul style="padding-left:18px;margin:0">{rows}</ul>')

    if not sections:
        return None
    bits = []
    if awards:
        bits.append(f"{awards[0]} protest window{'s' if awards[0] != 1 else ''} open")
    if records:
        bits.append(f"{records[0]} tabulation{'s' if records[0] != 1 else ''} requestable")
    if total_new:
        bits.append(f"{total_new} new match{'es' if total_new != 1 else ''}")
    if deadlines:
        bits.append(f"{len(deadlines)} deadline{'s' if len(deadlines) != 1 else ''} this week")
    subject = "Scout daily: " + (", ".join(bits) if bits else "source health")
    return subject, _wrap(f"Daily digest — {date.today():%b %-d}", "".join(sections))


def send_daily_digest(opps: List[Opportunity]) -> bool:
    built = build_daily_digest(opps, db.workflow_state(), db.list_watchlists())
    if built is None:
        return False
    subject, html = built
    return send_email(subject, html)


def send_test_email() -> Tuple[bool, Optional[str], str]:
    """Prove the Resend wiring end to end. Returns (sent, error, recipient)."""
    to = _recipient(db.get_settings())
    body = (
        '<p style="margin:0 0 12px">Email is wired up correctly — digests will '
        "arrive at this address.</p>"
        '<p style="margin:0;color:#5A6478;font-size:13px">Sent from '
        f"<strong>{_sender()}</strong> via Resend. Cadence and recipient are in "
        "Settings → Email digest.</p>"
    )
    sent, error = send_email_detailed(
        "Scout: test email", _wrap("Test email", body)
    )
    return sent, error, to
