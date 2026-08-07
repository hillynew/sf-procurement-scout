"""Work out which procurement platform an agency runs, from its own website.

This is the piece that makes statewide coverage tractable. The registry ships
133 verified sources against a roster of 2,817 buying entities; the gap is not
closed by writing source rows by hand, it is closed by asking each agency's
website what it runs and matching the answer against a table of signatures.

The method is two fetches per agency. Get the homepage, find the link that
looks like a procurement page (`bid`, `purchasing`, `procurement`,
`solicitation`), fetch that, and look for a platform's fingerprint in either
page. A dozen SaaS platforms host nearly every local solicitation in Florida,
and each leaves an unmistakable trace: CivicPlus ships `RWDBids.css`, Bonfire
lives on `bonfirehub.com`, OpenGov on `procurement.opengov.com/portal/`.

Three things this deliberately does not do:

* **It does not guess.** An agency whose page matches nothing comes back
  `unknown` with the URL it looked at, so the miss is inspectable rather than
  filed as "no procurement". `unknown` is the most useful output here — it is
  the queue of things worth a human minute.
* **It does not fetch fast.** Every request goes through `src.netpolicy`, so
  robots and the per-host limit apply. These are ~2,800 different hosts, so the
  limiter costs almost nothing in wall clock; the concurrency cap is about not
  opening 2,800 sockets.
* **It does not decide what to crawl.** Producing a platform mapping is a
  separate act from turning it into a configured source, and the second one
  should stay deliberate — see `scripts/fingerprint_agencies.py`.

Re-run quarterly. Migrations are frequent: three were observed during a single
week of the original research, and a fourth (Solid Waste Authority) turned up
the day this was written.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit

from ..http_util import SourceBlocked, get
from ..netpolicy import RobotsDisallowed

#: Platform -> (strong signatures, weak signatures). From the research report's
#: table, then widened by what the first sweep actually hit.
#:
#: The two tiers are the point. A **strong** signature is a URL or asset that
#: only that platform serves — the agency demonstrably runs it. A **weak** one
#: is the brand name in prose, which usually means "we post our bids there, go
#: register" and is worth a human minute rather than a source row. Collapsing
#: the two would have recorded Martin County as a confirmed DemandStar tenant
#: on the strength of a "Register with DemandStar" link, and would still have
#: missed Osceola, whose VendorLink runs on the county's own subdomain rather
#: than the vendor's.
PLATFORM_SIGNATURES: List[Tuple[str, Tuple[str, ...], Tuple[str, ...]]] = [
    ("bonfire", ("bonfirehub.com", "/PublicPortal/"), ("bonfire portal",)),
    ("opengov", ("procurement.opengov.com/portal/", "api.procurement.opengov.com"),
     ("opengov procurement",)),
    ("civicplus", ("/Common/Modules/Bids/RWDBids.css",), ()),
    ("vendor_registry", ("vrapp.vendorregistry.com/Bids/View/", "vendorregistry.com/Bids/"),
     ("vendor registry",)),
    # Self-hosted instances are common: Osceola runs vendorlink.osceola.org.
    ("vendorlink", ("myvendorlink.com", "vendorlink."), ("vendorlink",)),
    ("ionwave", (".ionwave.net", "ctl00_mainContent_rgBidList"), ("ionwave",)),
    ("bidsync_periscope", ("BuyspeedBidDetail.xhtml", ".buyspeed.com/bso/", "bidsync.com"),
     ("bidsync", "periscope holdings")),
    ("peoplesoft", ("SCP_PUB_BID_CMP_FL.GBL", "SCP_PUBLIC_MENU_FL"), ()),
    ("oracle_ebs", ("OA_HTML/OA.jsp?OAFunc=PON_",), ()),
    ("infor_fsm", ("inforcloudsuite.com/fsm/SupplyManagementSupplier",), ()),
    ("jaggaer", ("bids.sciquest.com/apps/Router/PublicEvent", "sciquest.com"), ("jaggaer",)),
    ("bids_and_tenders", (".bidsandtenders.net/Module/Tenders/",), ("bids&tenders",)),
    ("planetbids", ("planetbids.com",), ("planetbids",)),
    ("publicpurchase", ("publicpurchase.com/gems/", "publicpurchase.com"), ("public purchase",)),
    ("demandstar", ("demandstar.com",), ("demandstar",)),
    ("bidnet", ("bidnetdirect.com",), ("bidnet direct",)),
    ("bidexpress", ("bidexpress.com", "bidx.com"), ("bid express",)),
    ("questcdn", ("questcdn.com",), ("questcdn",)),
    ("openpurchase", ("openpurchase.io",), ()),
]

#: Flat view for the "does this href point at any known platform" test.
_ALL_STRONG: Tuple[str, ...] = tuple(
    needle for _p, strong, _w in PLATFORM_SIGNATURES for needle in strong
)

#: Anchor text or href worth following from a homepage. Ordered: an explicit
#: "bids" link beats a generic "purchasing" one when a site has both.
_LINK_HINTS = (
    "bid opportunit", "bids", "solicitation", "invitation to bid",
    "procurement", "purchasing", "rfp", "vendor",
)

_LINK_RE = re.compile(r"bid|purchas|procure|solicitat|rfp|vendor", re.I)

#: Pages this size are a redirect stub or an error, not a bid board.
_MIN_HTML = 500


@dataclass
class Fingerprint:
    entity_id: str
    name: str
    website: str
    platform: str = "unknown"
    portal_url: Optional[str] = None
    #: The procurement page we found and read, when we found one.
    checked_url: Optional[str] = None
    note: str = ""
    #: Every platform matched, when a page carries more than one — a CivicPlus
    #: city whose bid board is a pointer to BidSync matches both, and which one
    #: matters depends on the direction of the pointer.
    also: List[str] = field(default_factory=list)
    #: "strong" when the platform's own URL or asset is on the page, "weak"
    #: when only its name is. A weak row is a lead, not a source.
    confidence: str = "none"

    def as_dict(self) -> Dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "website": self.website,
            "platform": self.platform,
            "portal_url": self.portal_url,
            "checked_url": self.checked_url,
            "note": self.note,
            "also": self.also,
            "confidence": self.confidence,
        }


def identify(html: str) -> Tuple[List[str], List[str]]:
    """(strong matches, weak matches) for this page, best first within each.

    Strong beats weak everywhere it appears: a page that both runs CivicPlus and
    tells vendors to register on DemandStar is a CivicPlus site.
    """
    lowered = html.lower()
    strong_hits: List[str] = []
    weak_hits: List[str] = []
    for platform, strong, weak in PLATFORM_SIGNATURES:
        if any(needle.lower() in lowered for needle in strong):
            strong_hits.append(platform)
        elif any(needle.lower() in lowered for needle in weak):
            weak_hits.append(platform)
    return strong_hits, weak_hits


def portal_url_for(platform: str, html: str, base: str) -> Optional[str]:
    """Pull the platform's own URL out of the page, so the row is actionable.

    A platform name alone still leaves someone hunting for the tenant key. The
    URL carries it — the Bonfire subdomain, the OpenGov slug, the VendorLink
    `a=` id — which is the difference between a survey and a source row.
    """
    patterns = {
        "bonfire": r"https?://([a-z0-9-]+)\.bonfirehub\.com[^\"'\s<>]*",
        "demandstar": r"https?://[^\"'\s<>]*demandstar\.com[^\"'\s<>]*",
        "bidnet": r"https?://[^\"'\s<>]*bidnetdirect\.com[^\"'\s<>]*",
        "bidsync_periscope": r"https?://[^\"'\s<>]*(?:bidsync|buyspeed)\.com[^\"'\s<>]*",
        "bidexpress": r"https?://[^\"'\s<>]*bid(?:express|x)\.com[^\"'\s<>]*",
        "questcdn": r"https?://[^\"'\s<>]*questcdn\.com[^\"'\s<>]*",
        "opengov": r"https?://procurement\.opengov\.com/portal/[a-z0-9_-]+",
        "vendor_registry": r"https?://vrapp\.vendorregistry\.com/Bids/View/[^\"'\s<>]*",
        # Either the vendor's host or a county-hosted instance.
        "vendorlink": r"https?://[^\"'\s<>]*(?:myvendorlink\.com/external[^\"'\s<>]*|vendorlink\.[a-z0-9.-]+/[^\"'\s<>]*)",
        "publicpurchase": r"https?://[^\"'\s<>]*publicpurchase\.com/gems/[^\"'\s<>]*",
        "jaggaer": r"https?://bids\.sciquest\.com/apps/Router/PublicEvent[^\"'\s<>]*",
        "planetbids": r"https?://[^\"'\s<>]*planetbids\.com/[^\"'\s<>]*",
        "ionwave": r"https?://[a-z0-9-]+\.ionwave\.net[^\"'\s<>]*",
        "infor_fsm": r"https?://[^\"'\s<>]*inforcloudsuite\.com/fsm/[^\"'\s<>]*",
    }
    pattern = patterns.get(platform)
    if pattern:
        # SharePoint-generated sites write their hrefs entity-encoded —
        # `https&#58;//leegov.ionwave.net/...` — so every one of these patterns
        # misses on them. It cost Lee County's portal URL: the platform was
        # matched, the row went out with `portal_url: null`, and the host had
        # to be read off the page by hand later.
        m = re.search(pattern, unescape(html), re.I)
        if m:
            return m.group(0).rstrip("\"'")
    return base if platform == "civicplus" else None


def procurement_link(html: str, base: str) -> Optional[str]:
    """The most promising procurement link on a homepage.

    Scored rather than first-match: municipal homepages carry a lot of anchors,
    and "Bid Opportunities" is a better bet than a "Vendor Registration" link
    that happens to appear higher up.
    """
    best: Optional[Tuple[int, str]] = None
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        blob = f"{href} {text}".lower()
        if not _LINK_RE.search(blob):
            continue
        score = 0
        for i, hint in enumerate(_LINK_HINTS):
            if hint in blob:
                score = max(score, len(_LINK_HINTS) - i)
        # An off-site link to a known platform is the strongest signal of all:
        # it *is* the answer rather than a step toward it.
        if any(n.lower() in href.lower() for n in _ALL_STRONG):
            score += 20
        if score and (best is None or score > best[0]):
            best = (score, urljoin(base, href))
    return best[1] if best else None


#: Below this, a homepage is a client-rendered shell rather than a page we can
#: read links out of.
_JS_SHELL = 6000


def _fetch_tolerant(url: str, *, timeout: int):
    """Fetch a roster URL, retrying the obvious variants before giving up.

    Roster websites are whatever an agency told a state registry years ago, so
    a third of them are `http://` with a deep path. Two cheap retries recover a
    meaningful share: Columbia County answers 503 over http and 200 over https,
    and a stale deep link often 404s while the site root is fine. Anything that
    still fails is genuinely down, and is recorded as such.
    """
    attempts = [url]
    split = urlsplit(url)
    if split.scheme == "http":
        attempts.append(url.replace("http://", "https://", 1))
    root = f"https://{split.netloc}"
    if split.path not in ("", "/") and root not in attempts:
        attempts.append(root)

    last: Optional[Exception] = None
    for candidate in attempts:
        try:
            return get(candidate, timeout=timeout, retries=1)
        except (RobotsDisallowed, SourceBlocked):
            raise
        except Exception as e:  # noqa: BLE001 — try the next variant
            last = e
    raise last if last else RuntimeError(f"unreachable: {url}")


#: Paths worth trying when a homepage links nothing. `/Bids.aspx` is first
#: because CivicPlus serves it on every site it hosts, and CivicPlus is the
#: most common platform among Florida municipalities.
_KNOWN_PATHS = ("/Bids.aspx", "/bids", "/purchasing", "/procurement")


def _probe_known_paths(base: str, *, timeout: int) -> Optional[str]:
    """The first of the usual paths that answers with a real page, or None."""
    root = base.rstrip("/")
    for path in _KNOWN_PATHS:
        try:
            resp = get(root + path, timeout=timeout, retries=0)
        except (RobotsDisallowed, SourceBlocked):
            return None
        except Exception:  # noqa: BLE001 — a 404 here is the expected case
            continue
        if len(resp.text or "") > _MIN_HTML:
            return str(resp.url)
    return None


def _normalise(website: str) -> str:
    site = (website or "").strip()
    if not site:
        return ""
    if not site.startswith(("http://", "https://")):
        site = f"https://{site}"
    return site


def fingerprint_agency(entity_id: str, name: str, website: str, *, timeout: int = 20) -> Fingerprint:
    """Two fetches, one verdict. Never raises — a failure is a recorded result."""
    site = _normalise(website)
    fp = Fingerprint(entity_id=entity_id, name=name, website=site)
    if not site:
        fp.note = "no website"
        return fp

    try:
        home = _fetch_tolerant(site, timeout=timeout)
    except RobotsDisallowed as e:
        fp.note = f"robots refused: {str(e)[:80]}"
        return fp
    except SourceBlocked:
        fp.note = "blocked (WAF)"
        return fp
    except Exception as e:  # noqa: BLE001 — an unreachable site is a result
        fp.note = f"unreachable ({type(e).__name__})"
        return fp

    home_html = home.text or ""
    # The homepage sometimes *is* the answer, when a city links its portal in
    # the nav or embeds the widget.
    strong, _weak = identify(home_html)
    if strong:
        fp.platform, fp.also = strong[0], strong[1:]
        fp.confidence = "strong"
        fp.checked_url = str(home.url)
        fp.portal_url = portal_url_for(fp.platform, home_html, str(home.url))
        fp.note = "matched on homepage"
        return fp

    link = procurement_link(home_html, str(home.url))
    if not link:
        # Plenty of city homepages never link bids from the front page — the
        # board lives under Business or Departments, two hops down. Rather than
        # crawl the site, try the handful of paths these platforms all use.
        # `/Bids.aspx` alone recovers every CivicPlus city, which is the single
        # largest platform among Florida municipalities.
        probed = _probe_known_paths(str(home.url), timeout=timeout)
        if probed is None:
            fp.checked_url = str(home.url)
            # Distinguish the two misses, because only one of them is worth a
            # human's time: a few kilobytes of homepage is a client-rendered
            # app whose nav we never saw, not a site without a bid board.
            fp.note = (
                "homepage renders client-side (too small to read)"
                if len(home_html) < _JS_SHELL
                else "no procurement link found"
            )
            return fp
        link = probed

    try:
        page = get(link, timeout=timeout, retries=1)
    except RobotsDisallowed as e:
        fp.note = f"robots refused: {str(e)[:80]}"
        fp.checked_url = link
        return fp
    except SourceBlocked:
        fp.note = "procurement page blocked (WAF)"
        fp.checked_url = link
        return fp
    except Exception as e:  # noqa: BLE001
        fp.note = f"procurement page unreachable ({type(e).__name__})"
        fp.checked_url = link
        return fp

    fp.checked_url = str(page.url)
    html = page.text or ""
    if len(html) < _MIN_HTML:
        fp.note = "procurement page too small to read"
        return fp

    strong, weak = identify(html)
    if not strong and not weak:
        fp.note = "no platform signature"
        return fp

    if strong:
        fp.platform, fp.also = strong[0], strong[1:] + weak
        fp.confidence = "strong"
        fp.note = "matched on procurement page"
    else:
        # Named but not demonstrated: usually "register with us over there".
        fp.platform, fp.also = weak[0], weak[1:]
        fp.confidence = "weak"
        fp.note = "platform named in text, not linked"
    fp.portal_url = portal_url_for(fp.platform, html, str(page.url))

    # A CivicPlus bid board whose only content points at another platform is a
    # pointer page, and recording it as CivicPlus would report coverage we do
    # not have. The off-site platform is the real answer.
    if fp.platform == "civicplus" and fp.also:
        offsite = [p for p in fp.also if p != "civicplus"]
        if offsite and _points_offsite(html, offsite[0]):
            fp.platform, fp.also = offsite[0], ["civicplus"] + offsite[1:]
            fp.portal_url = portal_url_for(fp.platform, html, str(page.url))
            fp.note = "CivicPlus pointer page -> " + fp.platform
    return fp


def _points_offsite(html: str, platform: str) -> bool:
    """True when the page's bid list is empty but it links the other platform."""
    has_rows = 'class="bidTitle"' in html or "listItemsRow" in html
    linked = any(
        n.lower() in html.lower()
        for p, strong, _w in PLATFORM_SIGNATURES if p == platform for n in strong
    )
    return linked and not has_rows


def host_of(url: str) -> str:
    return urlsplit(url or "").netloc.lower()
