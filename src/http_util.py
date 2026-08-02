"""Shared HTTP helpers with polite pacing and bounded retries."""

from __future__ import annotations

import random
import time
from typing import Optional

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Status codes worth a second attempt: transient server/edge failures and
# rate limiting. 403 is excluded on purpose — WAF blocks do not clear on retry.
RETRY_STATUS = {429, 500, 502, 503, 504}
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 1.5


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

    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        # polite pacing for public government sites
        time.sleep(0.15)
        try:
            resp = client.get(url, timeout=timeout, headers=hdrs or None, **kwargs)
        except requests.RequestException as e:
            last_exc = e
            if attempt >= retries:
                raise
            _sleep_backoff(attempt)
            continue

        if resp.status_code in (401, 403):
            raise SourceBlocked(f"{resp.status_code} blocked by portal: {url}")
        if resp.status_code in RETRY_STATUS and attempt < retries:
            _sleep_backoff(attempt)
            continue
        resp.raise_for_status()
        return resp

    # Only reachable when the final attempt raised a RequestException.
    raise last_exc  # pragma: no cover


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
        "User-Agent": DEFAULT_UA,
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
        try:
            with httpx.Client(
                http2=True, headers=hdrs, follow_redirects=True, timeout=timeout
            ) as c:
                resp = c.get(url)
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
