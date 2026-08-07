"""Crawl policy: who we say we are, where we are allowed, how fast, and the log.

The scout reads public procurement postings from government servers. Nothing
here is legally binding — robots.txt is not a contract and *hiQ* says scraping
public pages is unlikely to be a CFAA problem. The reason this module exists
anyway is the shape of the actual risk: what scrapers lose on is contract and
posture, not access. A violated robots.txt in front of a judge costs far more
than the requests it would have saved.

So four things, enforced in the HTTP layer rather than left to each adapter,
because a guardrail an adapter can forget is not a guardrail:

1. **We say who we are.** An honest User-Agent with a contact URL. The browser
   string stays available for the handful of WAF-fronted hosts that refuse
   everything else, and using it is a per-host decision recorded below, not a
   default.
2. **We honor robots.txt**, including Crawl-delay.
3. **We rate-limit per host**, one request per second unless robots asks for
   longer. Per *host*, not per adapter: 91 OpenGov tenants and 30 Bonfire
   tenants each share one server, and a limiter on the adapter would let a
   dozen workers hit it a dozen times a second while each felt polite.
4. **We log every fetch** — URL, time, status, and what robots.txt said at the
   time. That log is the defense file, and it is only worth having if it is
   written before anyone needs it.

What this module deliberately does not do is manufacture access. It has no
credential store and no retry-through-a-block: a 401/403 raises `SourceBlocked`
and the source is reported degraded rather than re-attempted from another angle.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

#: Where an administrator can reach a human about this crawler. Override with
#: SF_SCOUT_CONTACT so a deployment can point at a real inbox.
CONTACT = os.getenv(
    "SF_SCOUT_CONTACT", "https://github.com/hillynew/sf-procurement-scout"
)

CRAWLER_UA = f"sf-procurement-scout/1.0 (+{CONTACT}; Florida public procurement aggregator)"

#: Kept for hosts whose WAF refuses anything that does not look like a browser.
#: Verified 2026-08-06: every portal the scout reads except the Akamai-fronted
#: ones answers the honest string identically, so this is the exception.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: Hosts that only answer a browser string. Each entry is a deliberate, tested
#: exception rather than a blanket fallback — presenting as a browser to a site
#: that would have served us honestly is the thing worth avoiding.
BROWSER_UA_HOSTS = frozenset({"www.wpb.org", "wpb.org"})

#: Floor between requests to one host, in seconds. robots.txt Crawl-delay wins
#: when it asks for more; nothing lowers it.
MIN_INTERVAL = 1.0

#: Hosts we refuse outright regardless of what any adapter asks for. The data
#: DMS publishes is on VIP, which serves no robots.txt at all, so honoring this
#: costs nothing — which is exactly why there is no excuse for not honoring it.
DENY_HOSTS = frozenset({"dms.myflorida.com", "www.dms.myflorida.com"})


class RobotsDisallowed(RuntimeError):
    """robots.txt forbids this path for our User-Agent.

    Distinct from `SourceBlocked`: the server did not refuse us, we refused
    ourselves. Retrying cannot help and must not be attempted.
    """


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


@dataclass
class _Robots:
    parser: Optional[RobotFileParser]
    fetched_at: float
    #: What the file said, in a form worth writing to the log.
    summary: str
    crawl_delay: Optional[float] = None


#: Re-read a host's robots.txt no more often than this. Long enough that a
#: crawl does not re-fetch it constantly, short enough that a site which adds a
#: Disallow is respected the same day.
ROBOTS_TTL = 3600.0

_robots_cache: Dict[str, _Robots] = {}
_robots_lock = threading.Lock()


def _fetch_robots(host: str) -> _Robots:
    """Read and parse one host's robots.txt.

    A missing or unreadable file means unrestricted — that is what the standard
    says, and treating a 404 as a prohibition would refuse most of the state.
    A *failed* fetch is treated the same way rather than blocking the crawl on
    an unrelated outage, and the log records which it was.
    """
    import requests

    url = f"https://{host}/robots.txt"
    try:
        resp = requests.get(
            url, headers={"User-Agent": CRAWLER_UA}, timeout=15, allow_redirects=True
        )
    except Exception as e:  # noqa: BLE001 — an unreachable robots.txt is not a verdict
        return _Robots(None, time.monotonic(), f"unreachable ({type(e).__name__})")

    if resp.status_code != 200:
        return _Robots(None, time.monotonic(), f"none (HTTP {resp.status_code})")

    body = resp.text or ""
    # Some hosts answer /robots.txt with their SPA shell or a 200 error page.
    if "<html" in body[:400].lower():
        return _Robots(None, time.monotonic(), "none (HTML, not robots)")

    parser = RobotFileParser()
    parser.parse(body.splitlines())
    delay = parser.crawl_delay(CRAWLER_UA)
    try:
        delay = float(delay) if delay is not None else None
    except (TypeError, ValueError):
        delay = None
    return _Robots(parser, time.monotonic(), f"present ({len(body)}b)", delay)


def robots_for(host: str) -> _Robots:
    with _robots_lock:
        cached = _robots_cache.get(host)
        if cached and (time.monotonic() - cached.fetched_at) < ROBOTS_TTL:
            return cached
    fresh = _fetch_robots(host)
    with _robots_lock:
        _robots_cache[host] = fresh
    return fresh


def robots_allows(url: str) -> tuple[bool, str]:
    """(allowed, why) for one URL under the crawler's own User-Agent."""
    host = urlsplit(url).netloc.lower()
    if host in DENY_HOSTS:
        return False, "host on the deny list"

    reason = _override_reason(host)
    if reason:
        return True, f"override: {reason}"

    robots = robots_for(host)
    if robots.parser is None:
        return True, robots.summary
    allowed = robots.parser.can_fetch(CRAWLER_UA, url)
    return allowed, ("allowed by robots" if allowed else "disallowed by robots")


# ---------------------------------------------------------------------------
# Documented exceptions
# ---------------------------------------------------------------------------

#: Hosts crawled despite a robots.txt that forbids it, each with the reason
#: standing behind the decision. This is a deliberately uncomfortable list: it
#: is in code, in one place, and every entry has to say why out loud.
#:
#: Set SF_SCOUT_STRICT_ROBOTS=1 to ignore this table and obey robots
#: everywhere — which is what a cautious deployment should do.
ROBOTS_OVERRIDES: Dict[str, str] = {
    # Bonfire serves `User-agent: * / Disallow: /` across every tenant
    # subdomain. That single file would remove 30 Florida agencies including
    # Broward County, Hillsborough, Tallahassee and Monroe. The argument for
    # continuing is that these are public solicitations the agency is
    # statutorily required to publish, the records belong to the agency rather
    # than to its portal vendor, and we read a handful of rows per tenant at
    # one request per second. It remains a judgement call, not a settled one —
    # see docs/statewide-coverage.md.
    "*.bonfirehub.com": "public agency postings; agency's records, not the vendor's",
    # Ionwave — same vendor family as Bonfire (both Euna), and the same
    # blanket `Disallow: /` on every tenant subdomain. Same reasoning applies,
    # and two further facts specific to it: the tenant's own login page links
    # these lists to the public unauthenticated, and its site terms bind on
    # registration rather than on reading, with no clause about automated
    # access at all — checked 2026-08-07 against Coconut Creek's SiteTerms.
    # The adapter reads one page per agency per cycle, and stops rather than
    # working around the bot challenge that sits behind it.
    "*.ionwave.net": "public agency postings; agency's records, not the vendor's",
}


def _expand_overrides() -> Dict[str, str]:
    if os.getenv("SF_SCOUT_STRICT_ROBOTS", "").strip() in ("1", "true", "yes"):
        return {}
    return dict(ROBOTS_OVERRIDES)


def _override_reason(host: str) -> Optional[str]:
    overrides = _expand_overrides()
    if host in overrides:
        return overrides[host]
    for pattern, reason in overrides.items():
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return reason
    return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@dataclass
class _HostState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    last: float = 0.0


_hosts: Dict[str, _HostState] = {}
_hosts_lock = threading.Lock()


def _host_state(host: str) -> _HostState:
    with _hosts_lock:
        state = _hosts.get(host)
        if state is None:
            state = _HostState()
            _hosts[host] = state
        return state


def interval_for(host: str) -> float:
    """Seconds to leave between requests to this host."""
    robots = robots_for(host)
    if robots.crawl_delay:
        return max(MIN_INTERVAL, robots.crawl_delay)
    return MIN_INTERVAL


def pace(url: str) -> None:
    """Block until this host may be called again.

    Held across threads, so concurrent adapters against one host queue behind
    each other instead of each keeping its own polite-looking interval.
    """
    host = urlsplit(url).netloc.lower()
    state = _host_state(host)
    interval = interval_for(host)
    with state.lock:
        wait = interval - (time.monotonic() - state.last)
        if wait > 0:
            time.sleep(wait)
        state.last = time.monotonic()


# ---------------------------------------------------------------------------
# The fetch log
# ---------------------------------------------------------------------------

#: Unset disables logging. A path turns it on; the crawl appends one JSON
#: object per request.
FETCH_LOG = os.getenv("SF_SCOUT_FETCH_LOG", "").strip()

_log_lock = threading.Lock()


def log_fetch(url: str, *, status, robots_note: str, ua: str, elapsed_ms: int = 0) -> None:
    """Append one line to the defense file. Never raises into a crawl."""
    if not FETCH_LOG:
        return
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "url": url,
        "status": status,
        "robots": robots_note,
        "ua": ua,
        "elapsed_ms": elapsed_ms,
    }
    try:
        with _log_lock:
            with open(FETCH_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 — logging must never break a fetch
        pass


def user_agent_for(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return BROWSER_UA if host in BROWSER_UA_HOSTS else CRAWLER_UA


def check(url: str) -> str:
    """Enforce robots, then pace. Returns the robots note for the log.

    Every request in the codebase goes through here.
    """
    allowed, note = robots_allows(url)
    if not allowed:
        log_fetch(url, status="refused", robots_note=note, ua=CRAWLER_UA)
        raise RobotsDisallowed(f"{note}: {url}")
    pace(url)
    return note


def reset_for_tests() -> None:
    """Drop cached robots and host timings."""
    with _robots_lock:
        _robots_cache.clear()
    with _hosts_lock:
        _hosts.clear()
