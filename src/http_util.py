"""Shared HTTP helpers with polite pacing and bounded retries."""

from __future__ import annotations

import random
import time
from typing import Optional

import requests

from .netpolicy import BROWSER_UA, CRAWLER_UA, RobotsDisallowed
from .netpolicy import check, log_fetch, user_agent_for

# Re-exported so callers keep importing their HTTP vocabulary from one place.
__all__ = [
    "BROWSER_UA", "CHALLENGE_MARKERS", "CRAWLER_UA", "DEFAULT_UA",
    "RobotsDisallowed", "SourceBlocked",
    "get", "get_h2", "get_json", "is_challenge", "session",
]

#: The crawler identifies itself honestly. `src.netpolicy` keeps the browser
#: string for the few WAF-fronted hosts that refuse anything else, chosen per
#: host rather than as a fallback.
DEFAULT_UA = CRAWLER_UA

# Status codes worth a second attempt: transient server/edge failures and
# rate limiting. 403 is excluded on purpose — WAF blocks do not clear on retry.
RETRY_STATUS = {429, 500, 502, 503, 504}
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 1.5

#: Fragments of Cloudflare's managed-challenge interstitial. It arrives with
#: status 429, which reads as "slow down" and is not: the challenge counts
#: requests per session, so waiting does not clear it and retrying only spends
#: another request against the same limit. Ionwave serves this from about the
#: fourth request on one session, at any spacing.
CHALLENGE_MARKERS = ("just a moment", "challenges.cloudflare.com", "cf-chl")


class SourceBlocked(RuntimeError):
    """Portal actively refused the scraper (403/401/WAF challenge).

    Distinct from a transient error: retrying will not help, and the adapter
    should fall back to a registration pointer while health reports 'degraded'.
    """


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": DEFAULT_UA,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return s


def get(
    url: str,
    *,
    s: Optional[requests.Session] = None,
    timeout: int = 40,
    headers: Optional[dict] = None,
    referer: Optional[str] = None,
    retries: int = DEFAULT_RETRIES,
    **kwargs,
) -> requests.Response:
    client = s or session()
    hdrs = dict(headers or {})
    if referer:
        hdrs["Referer"] = referer
        hdrs["Sec-Fetch-Site"] = "same-origin"

    # Identify honestly unless this host is one of the tested exceptions.
    hdrs.setdefault("User-Agent", user_agent_for(url))

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        # Refuses the request outright if robots.txt says so, then holds until
        # this host may be called again. Every fetch in the codebase passes here.
        robots_note = check(url)
        started = time.monotonic()
        try:
            resp = client.get(url, timeout=timeout, headers=hdrs or None, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            log_fetch(url, status=type(e).__name__, robots_note=robots_note,
                      ua=hdrs["User-Agent"])
            if attempt >= retries:
                raise
            _sleep_backoff(attempt)
            continue

        log_fetch(
            url,
            status=resp.status_code,
            robots_note=robots_note,
            ua=hdrs["User-Agent"],
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
        if resp.status_code in (401, 403):
            # A refusal is not retried and not worked around from another angle;
            # continued access after one is the fact pattern worth avoiding.
            raise SourceBlocked(f"{resp.status_code} blocked by portal: {url}")
        if is_challenge(resp):
            # Same rule, different disguise. A bot challenge is the operator
            # asking us to prove we are not a crawler, and we are one, so this
            # is a refusal rather than the backpressure its 429 implies.
            raise SourceBlocked(f"bot challenge served instead of the page: {url}")
        if resp.status_code in RETRY_STATUS and attempt < retries:
            _sleep_backoff(attempt)
            continue
        resp.raise_for_status()
        return resp

    # Only reachable when the final attempt raised a RequestException.
    raise last_exc  # pragma: no cover


def is_challenge(resp) -> bool:
    """True when the response is a bot-challenge interstitial, not the page.

    Checked on the body rather than the status alone: 429 is also honest
    backpressure from portals that mean it, and those are worth retrying.
    Only the head of the body is read — the challenge declares itself in its
    `<title>` and CSP, and a real page can be megabytes.
    """
    try:
        if getattr(resp, "status_code", None) not in (403, 429, 503):
            return False
        head = (resp.text or "")[:4000].lower()
    except Exception:  # noqa: BLE001 — an unreadable body is not a challenge
        return False
    return any(marker in head for marker in CHALLENGE_MARKERS)


def get_json(url: str, **kwargs):
    """GET a JSON endpoint with the XHR headers portals typically require."""
    headers = dict(kwargs.pop("headers", None) or {})
    headers.setdefault("X-Requested-With", "XMLHttpRequest")
    headers.setdefault("Accept", "application/json, text/javascript, */*; q=0.01")
    return get(url, headers=headers, **kwargs).json()


def _sleep_backoff(attempt: int) -> None:
    time.sleep(DEFAULT_BACKOFF**attempt + random.uniform(0, 0.25))


def get_h2(
    url: str,
    *,
    timeout: int = 40,
    headers: Optional[dict] = None,
    retries: int = 3,
):
    """Fetch over HTTP/2 via httpx, for WAF-fronted sites.

    Some portals (e.g. Akamai on wpb.org) 403 every plain HTTP/1.1 library
    client but serve HTTP/2 requests carrying browser-like headers. Denials
    are intermittent, so retry a few times before giving up. Returns an
    httpx.Response (requests-compatible ``.text`` / ``.json()``); raises
    SourceBlocked when every attempt was refused.
    """
    import httpx

    hdrs = {
        # This path exists for WAF-fronted hosts, which is exactly the case the
        # browser string is reserved for — but the host still has to be on the
        # list, so a new caller cannot quietly acquire a disguise.
        "User-Agent": user_agent_for(url),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }
    if headers:
        hdrs.update(headers)

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        robots_note = check(url)
        try:
            with httpx.Client(
                http2=True, headers=hdrs, follow_redirects=True, timeout=timeout
            ) as c:
                resp = c.get(url)
            log_fetch(url, status=resp.status_code, robots_note=robots_note,
                      ua=hdrs["User-Agent"])
            denied = resp.status_code in (401, 403) or (
                "Access Denied" in resp.text[:2000]
            )
            if not denied:
                resp.raise_for_status()
                return resp
            last_err = SourceBlocked(f"WAF denial (status {resp.status_code}): {url}")
        except SourceBlocked:
            raise
        except Exception as e:  # noqa: BLE001
            last_err = e
        _sleep_backoff(attempt)
    raise last_err if last_err else SourceBlocked(f"get_h2 exhausted retries: {url}")
