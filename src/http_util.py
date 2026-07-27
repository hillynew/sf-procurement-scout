"""Shared HTTP helpers."""

from __future__ import annotations

import time
from typing import Optional
import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
    **kwargs,
) -> requests.Response:
    client = s or session()
    # polite pacing for public government sites
    time.sleep(0.15)
    hdrs = dict(headers or {})
    if referer:
        hdrs["Referer"] = referer
        hdrs["Sec-Fetch-Site"] = "same-origin"
    resp = client.get(url, timeout=timeout, headers=hdrs or None, **kwargs)
    resp.raise_for_status()
    return resp
