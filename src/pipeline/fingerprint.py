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
    # `/PublicPortal/` was a second needle here, because that is the path
    # Bonfire's own API lives under. It is not Bonfire's alone: JustFOIA serves
    # public *records request* portals at `<agency>.justfoia.com/publicportal/`,
    # and 15 Florida agencies linking one were recorded as strong Bonfire
    # tenants with no Bonfire host to show for it. A signature that a second
    # vendor also serves is not a signature.
    ("bonfire", ("bonfirehub.com",), ("bonfire portal",)),
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
    # Where UNF went when it left Jaggaer on 1 July 2026. Added because the
    # move was found by hand and the next one should not have to be.
    ("workday_sourcing", ("public-portal.us.workdayspend.com", "workdayspend.com"),
     ("workday strategic sourcing",)),
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


def usable(hits: List[str], avoid: frozenset) -> List[str]:
    """The matches that answer the question, given platforms we cannot read.

    A fingerprint normally stops at the first strong signature, because the
    question is "what does this agency run". When the answer is a platform whose
    terms forbid reading it, that stop is the wrong one: the agency may also
    post the same solicitations to a board we are allowed to read, and the sweep
    never looked because it already had an answer.

    So `avoid` makes a match true but not final. The avoided platform is still
    recorded — in `also`, never dropped — and the search keeps going.
    """
    return [p for p in hits if p not in avoid]


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
        # `/portal/<tenant>` is the portal; `/portal/embed/<tenant>/project-list`
        # is the iframe an agency drops into its own page. The tenant sits one
        # segment deeper in the second form, and without `embed/` here the
        # match stopped at the literal word and recorded a URL naming nobody.
        "opengov": r"https?://procurement\.opengov\.com/portal/(?:embed/)?[a-z0-9_-]+",
        "vendor_registry": r"https?://vrapp\.vendorregistry\.com/Bids/View/[^\"'\s<>]*",
        # Either the vendor's host or a county-hosted instance.
        "vendorlink": r"https?://[^\"'\s<>]*(?:myvendorlink\.com/external[^\"'\s<>]*|vendorlink\.[a-z0-9.-]+/[^\"'\s<>]*)",
        "publicpurchase": r"https?://[^\"'\s<>]*publicpurchase\.com/gems/[^\"'\s<>]*",
        "jaggaer": r"https?://bids\.sciquest\.com/apps/Router/PublicEvent[^\"'\s<>]*",
        "planetbids": r"https?://[^\"'\s<>]*planetbids\.com/[^\"'\s<>]*",
        "ionwave": r"https?://[a-z0-9-]+\.ionwave\.net[^\"'\s<>]*",
        "workday_sourcing": r"https?://[^\"'\s<>]*workdayspend\.com[^\"'\s<>]*",
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


def _needles_for(platforms: frozenset) -> Tuple[str, ...]:
    """Every strong signature belonging to these platforms."""
    return tuple(
        needle
        for p, strong, _w in PLATFORM_SIGNATURES if p in platforms
        for needle in strong
    )


def procurement_link(html: str, base: str, avoid: frozenset = frozenset()) -> Optional[str]:
    """The most promising procurement link on a homepage.

    Scored rather than first-match: municipal homepages carry a lot of anchors,
    and "Bid Opportunities" is a better bet than a "Vendor Registration" link
    that happens to appear higher up.

    A link into an avoided platform is not followed at all. It would score
    highest of anything on the page — an off-site link to a known platform gets
    +20 precisely because it is usually the answer — and spending the fetch on
    it buys a page we already know we cannot use. Skipping it is what lets the
    probe budget reach the CivicPlus board instead.
    """
    banned = _needles_for(avoid)
    best: Optional[Tuple[int, str]] = None
    for m in re.finditer(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        blob = f"{href} {text}".lower()
        if not _LINK_RE.search(blob):
            continue
        if any(n.lower() in href.lower() for n in banned):
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

#: A solicitation as agencies write it: a type and a *structured* number.
#: `ITB 26-014`, `RFP#2026-01`, `Bid No. 25-1147`. The number is what keeps this
#: off a purchasing policy page, which says "bid" constantly and numbers
#: nothing; requiring a year-and-sequence shape rather than any digits is what
#: keeps "Bid 60" in a sentence from counting as one.
_SOLICITATION_RE = re.compile(
    r"\b(?:ITB|IFB|RFP|RFQ|RFI|ITN|BID|SOLICITATION)\b[\s.#:No-]{0,6}"
    r"(?:\d{2,4}[-/]\d{1,4}|\d{4,})",
    re.I,
)

_DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2}\b",
    re.I,
)

#: Distinct solicitations and dates a page must show before it is called a bid
#: board. Two of each: a page carrying two numbered solicitations and two dates
#: is publishing bids, and Cape Canaveral — which had exactly two open — is the
#: case that set this. One is a news item announcing a single RFP.
_BOARD_MIN = 2


def _refs(text: str) -> set:
    """Distinct solicitation numbers, normalised so one is not counted twice.

    `RFP-2026-02` and `RFP2026-02` on the same page are one solicitation
    written two ways, and counting them as two was enough to call Arcadia's
    single news post a bid board.
    """
    return {
        re.sub(r"[^A-Z0-9]", "", m.group(0).upper())
        for m in _SOLICITATION_RE.finditer(text)
    }


def looks_like_a_bid_board(html: str) -> bool:
    """True when this page is itself a list of live solicitations.

    Some agencies run no platform at all — they keep the table on their own
    website. Filing those as `unknown` puts a real, readable bid board in the
    same bucket as a site that timed out, and they are opposite kinds of miss:
    one needs a page-level reader, the other needs nothing because there is
    nothing there.

    The test is deliberately hard to pass. A page must name at least two
    distinct *numbered* solicitations and carry at least two dates. Measured
    against the 146 readable no-signature pages from the sweep, that calls 17
    of them boards — small towns mostly do not have a board at all, they have a
    purchasing contact and a page that says to call them.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    if len(_refs(text)) < _BOARD_MIN:
        return False
    return len(set(_DATE_RE.findall(text))) >= _BOARD_MIN


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
_KNOWN_PATHS = (
    "/Bids.aspx", "/bids", "/purchasing", "/procurement",
    "/rfp", "/rfps", "/solicitations", "/bid-opportunities",
)

#: Hosts worth trying when a homepage links nothing. Large institutions put
#: procurement on its own subdomain and never link it from the front page —
#: `procurement.fsu.edu` and `bids.fiu.edu` are both Jaggaer, and both read as
#: "no procurement link found" for as long as this only followed links.
_KNOWN_SUBDOMAINS = ("procurement", "purchasing", "bids", "vendors")

#: How many probes one agency is worth, and the order they are spent in: the
#: four paths that answer most often, then the subdomains, then the rest. Order
#: only matters when something answers — a site with no board is going to cost
#: the whole budget whatever the order — so it is set to reach a small town's
#: `/Bids.aspx` in one request and a university's `bids.` host in five.
_PROBE_BUDGET = 12
_PATHS_FIRST = 4


def _probe_candidates(base: str) -> List[str]:
    """URLs to try, best first: the common paths, the subdomains, then the rest."""
    split = urlsplit(base)
    root = f"{split.scheme}://{split.netloc}".rstrip("/")
    paths = [root + path for path in _KNOWN_PATHS]

    host = split.netloc.lower()
    bare = host[4:] if host.startswith("www.") else host
    # Only off the agency's own domain. `bids.fiu.edu` is a fair guess;
    # `bids.town.windermere.fl.us`, hung off a host that is already a
    # subdomain of something else, is a guess too far.
    subs = (
        [f"{split.scheme}://{sub}.{bare}" for sub in _KNOWN_SUBDOMAINS]
        if bare and bare == _domain_of("//" + bare) else []
    )
    return paths[:_PATHS_FIRST] + subs + paths[_PATHS_FIRST:]


def _probe_for_board(base: str, *, timeout: int, avoid: frozenset = frozenset()):
    """Look for a bid board where the homepage linked none.

    Returns the response, not a URL, because the caller needs the body and
    fetching it twice for every probed agency is a request nobody has to spend.

    Stops at the first page that *demonstrates* something — a platform
    signature or a list of live solicitations. A page that merely answers is
    kept as a fallback, so "we read their purchasing page and it named no
    platform" stays distinguishable from "there was nothing to read".

    With `avoid`, a page carrying only an avoided platform's signature does not
    stop the search — it is worth less than the next URL in the budget, but more
    than nothing, so it is kept as a fallback behind any readable page.
    """
    fallback = None
    fallback_has_signature = False
    for url in _probe_candidates(base)[:_PROBE_BUDGET]:
        try:
            resp = get(url, timeout=timeout, retries=0)
        except (RobotsDisallowed, SourceBlocked):
            continue
        except Exception:  # noqa: BLE001 — a 404 here is the expected case
            continue
        html = resp.text or ""
        if len(html) <= _MIN_HTML:
            continue
        strong, _weak = identify(html)
        if usable(strong, avoid) or (not strong and looks_like_a_bid_board(html)):
            return resp
        # Nothing readable here. Keep the best near-miss: a page proving the
        # avoided platform beats a page proving nothing, because it confirms
        # where this agency actually posts when no permitted board turns up.
        if fallback is None or (strong and not fallback_has_signature):
            fallback, fallback_has_signature = resp, bool(strong)
    return fallback


def _normalise(website: str) -> str:
    site = (website or "").strip()
    if not site:
        return ""
    if not site.startswith(("http://", "https://")):
        site = f"https://{site}"
    return site


def fingerprint_agency(
    entity_id: str,
    name: str,
    website: str,
    *,
    timeout: int = 20,
    avoid: frozenset = frozenset(),
) -> Fingerprint:
    """Two fetches, one verdict. Never raises — a failure is a recorded result.

    `avoid` names platforms that are not an acceptable answer — in practice the
    ones whose terms forbid reading them, from `src.terms`. A signature for one
    of those is recorded in `also` and the search continues, so an agency that
    posts to both VendorLink and its own CivicPlus board comes back as CivicPlus
    rather than stopping at whichever the sweep happened to see first.
    """
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
    #: Avoided platforms seen along the way. Carried into `also` on whatever
    #: verdict this ends at, so "we looked past VendorLink" stays on the record
    #: rather than reading as an agency that never ran it.
    passed_over: List[str] = []
    #: The page the avoided platform was proved on, kept so a search that finds
    #: nothing better can still return that evidence rather than `unknown`.
    seen_at: Tuple[str, str] = ("", "")
    if strong:
        good = usable(strong, avoid)
        if good:
            fp.platform, fp.also = good[0], [p for p in strong if p != good[0]]
            fp.confidence = "strong"
            fp.checked_url = str(home.url)
            fp.portal_url = portal_url_for(fp.platform, home_html, str(home.url))
            fp.note = "matched on homepage"
            return fp
        passed_over, seen_at = strong, (home_html, str(home.url))

    def settle(note: str) -> Fingerprint:
        """Give back what we did prove, when the search for better came up dry.

        Without this, looking past VendorLink and finding nothing would report
        `unknown` — which reads as "we could not identify this agency" and would
        undo a fingerprint the sweep had already got right. What is true is that
        they run VendorLink and nothing we can read, and that is a coverage gap
        worth seeing rather than a hole in the survey.
        """
        if not passed_over:
            fp.note = note
            return fp
        fp.platform = passed_over[0]
        fp.also = _merge(fp.also, passed_over[1:])
        fp.confidence = "strong"
        fp.portal_url = portal_url_for(fp.platform, seen_at[0], seen_at[1])
        fp.note = f"{note}; no readable board besides {fp.platform}"
        return fp

    page = None
    link = procurement_link(home_html, str(home.url), avoid)
    if not link:
        # Plenty of homepages never link bids from the front page — the board
        # lives under Business or Departments, two hops down, or on its own
        # subdomain. Rather than crawl the site, try the handful of addresses
        # these platforms and institutions all use. `/Bids.aspx` alone recovers
        # every CivicPlus city; `procurement.<domain>` recovers the
        # universities, which never link procurement from a homepage aimed at
        # students.
        page = _probe_for_board(str(home.url), timeout=timeout, avoid=avoid)
        if page is None:
            fp.checked_url = str(home.url)
            # Distinguish the two misses, because only one of them is worth a
            # human's time: a few kilobytes of homepage is a client-rendered
            # app whose nav we never saw, not a site without a bid board.
            return settle(
                "homepage renders client-side (too small to read)"
                if len(home_html) < _JS_SHELL
                else "no procurement link found"
            )
        link = str(page.url)

    if page is None:
        try:
            page = get(link, timeout=timeout, retries=1)
        except RobotsDisallowed as e:
            fp.checked_url = link
            return settle(f"robots refused: {str(e)[:80]}")
        except SourceBlocked:
            fp.checked_url = link
            return settle("procurement page blocked (WAF)")
        except Exception as e:  # noqa: BLE001
            fp.checked_url = link
            return settle(f"procurement page unreachable ({type(e).__name__})")

    fp.checked_url = str(page.url)
    html = page.text or ""
    if len(html) < _MIN_HTML:
        return settle("procurement page too small to read")

    strong, weak = identify(html)
    if not usable(strong, avoid) and not weak:
        # A procurement landing page is often only a signpost: contacts, terms,
        # and a link to where the bids actually are. One more hop off it is
        # what separates UF and USF — both Jaggaer, both behind a
        # `procurement.` page that names no platform — from a dead end.
        hop = _second_hop(html, str(page.url), timeout=timeout, avoid=avoid)
        if hop is not None:
            page, html = hop, (hop.text or "")
            fp.checked_url = str(page.url)
            strong, weak = identify(html)

    if strong and not usable(strong, avoid):
        # The page proves the avoided platform and nothing else. That is not the
        # end of the search here, only the end of *this* page: the same agency
        # very often keeps a CivicPlus board at `/Bids.aspx` alongside whatever
        # portal its purchasing page advertises. Spend the probe budget before
        # settling for a platform we are not allowed to read.
        passed_over = _merge(strong, passed_over)
        seen_at = (html, str(page.url))
        alt = _probe_for_board(str(home.url), timeout=timeout, avoid=avoid)
        if alt is not None:
            alt_html = alt.text or ""
            alt_strong, alt_weak = identify(alt_html)
            if usable(alt_strong, avoid) or (
                not alt_strong and looks_like_a_bid_board(alt_html)
            ):
                page, html = alt, alt_html
                fp.checked_url = str(page.url)
                strong, weak = alt_strong, alt_weak

    if not strong and not weak:
        if looks_like_a_bid_board(html):
            # No platform because there is no platform: the agency keeps the
            # table on its own website. A real answer, and a different queue
            # from the sites that never answered.
            fp.platform = "selfhosted"
            fp.confidence = "page"
            fp.portal_url = str(page.url)
            fp.also = _merge(fp.also, passed_over)
            fp.note = "solicitations listed on the agency's own page"
            return fp
        fp.also = _merge(fp.also, passed_over)
        fp.note = "no platform signature"
        return fp

    good_strong, good_weak = usable(strong, avoid), usable(weak, avoid)
    if good_strong or (strong and not good_weak):
        # `strong[0]` when nothing survived `avoid`: the honest answer is still
        # the platform that is demonstrably there, recorded as what it is.
        head = (good_strong or strong)[0]
        fp.platform = head
        fp.also = _merge([p for p in strong + weak if p != head], passed_over)
        fp.confidence = "strong"
        fp.note = "matched on procurement page"
    else:
        # Named but not demonstrated: usually "register with us over there".
        head = (good_weak or weak)[0]
        fp.platform = head
        fp.also = _merge([p for p in weak if p != head], passed_over)
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


def _merge(*lists: List[str]) -> List[str]:
    """Concatenate, first occurrence wins, order preserved.

    `also` is read by humans and by the source generator, and a platform listed
    twice because two pages both showed it reads as two findings.
    """
    out: List[str] = []
    for items in lists:
        for item in items or []:
            if item not in out:
                out.append(item)
    return out


def _second_hop(html: str, base: str, *, timeout: int, avoid: frozenset = frozenset()):
    """One more hop from a procurement page that named no platform.

    Bounded to one fetch and guarded on where it goes. A procurement page links
    plenty — vendor forms, the state's own site, sometimes another agency
    entirely — and New College's page links `unf.edu`, which is a different
    university. So a hop is only taken within the agency's own domain (`bids.`
    off `www.` counts; a different institution does not) or to a host that is
    itself a known platform. Anything else would file one agency's platform
    under another's name.
    """
    link = procurement_link(html, base, avoid)
    if not link or link.rstrip("/") == base.rstrip("/"):
        return None
    if _domain_of(link) != _domain_of(base) and not any(
        needle.lower() in link.lower() for needle in _ALL_STRONG
    ):
        return None
    try:
        resp = get(link, timeout=timeout, retries=0)
    except Exception:  # noqa: BLE001 — the first page's verdict stands
        return None
    return resp if len(resp.text or "") > _MIN_HTML else None


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


def _domain_of(url: str) -> str:
    """The agency's domain, so `www.fiu.edu` and `bids.fiu.edu` read as one.

    Two labels, except under `.us`, where Florida governments live three deep —
    `town.windermere.fl.us`. Treating `fl.us` as the domain would make every
    Florida municipality a sibling of every other one.
    """
    parts = host_of(url).split(".")
    keep = 3 if parts[-1] == "us" and len(parts) > 2 else 2
    return ".".join(parts[-keep:])
