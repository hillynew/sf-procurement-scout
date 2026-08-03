"""Email digests via Resend. Inert without RESEND_API_KEY."""

from __future__ import annotations

import os
from datetime import date
from typing import Dict, List, Optional, Tuple

import httpx

from src.db import store as db
from src.models.opportunity import Opportunity

RESEND_URL = "https://api.resend.com/emails"

COUNTY_LABEL = {"miami-dade": "Miami-Dade", "broward": "Broward",
                "palm-beach": "Palm Beach"}


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


def build_daily_digest(
    opps: List[Opportunity],
    workflow: Dict[str, dict],
    watchlists: List[dict],
) -> Optional[Tuple[str, str]]:
    """(subject, html) for today's digest, or None when there is nothing to say."""
    from .matching import wl_matches

    sections: List[str] = []
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
