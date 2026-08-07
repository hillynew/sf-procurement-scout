"""Vendor Registry — an archive worth reading, and a live feed that is gone.

This adapter reads only the past. That is not a limitation of the code, and
working out why took the whole investigation, so it is written down here.

## The current list is empty everywhere, and says so

`/Bids/View/BidsList?BuyerId=<guid>` renders server-side and, for an anonymous
caller, renders the sentence *"Currently, <agency> has no open solicitations."*
Not an empty grid waiting on JavaScript, not a login redirect — a definite
statement that there is nothing.

Fifteen buyers were checked across five states on 7 Aug 2026, including
Williamson County TN, one of the platform's own flagship customers. **Every one
returned zero current rows.** Fifteen agencies do not simultaneously have
nothing out for bid. Whatever that page is, it is not a live feed.

The archives say the same thing from the other side. Every buyer's expired list
stops somewhere between October 2023 and January 2026, clustered at the recent
end — a platform-wide freeze rather than fifteen coincidences.

## Where the tenants went

mdf commerce owns Vendor Registry *and* BidNet Direct, and the Florida tenants
have moved between them or off them entirely. Each one was checked against its
own website rather than assumed:

| Agency | Last on Vendor Registry | Posts now on |
|---|---|---|
| Santa Rosa County | Oct 2023 | OpenGov — 11 open today, live in this build |
| Central Florida Expressway | Jan 2026 | OpenGov — 4 open today, live in this build |
| City of Sebring | Jan 2026 | BidNet Direct — its vendor page links there |
| Okeechobee County | Jul 2025 | unknown; the county's own site refuses us (403) |

So an adapter that fetched the current list would report every tenant healthy
and empty, forever, while their bids appeared elsewhere. This project has been
bitten by exactly that three times — Solid Waste Authority's move to Bonfire,
six CivicPlus cities that had gone to OpenGov, Deerfield Beach's move to
Ionwave — and each time the tell was a page that still resolved and still
returned nothing.

`fetch` therefore returns nothing and *declares why* through `empty_note`,
which the runner reports as `empty` rather than as a fault. A source that
cannot produce open bids should say so in the one place someone will look.

## What is still worth having

The archives are public, complete, unauthenticated and rich — 1,100 past
solicitations across the Florida buyers, each with a type, a reference number,
a deadline, a document count and its own detail page. `src/pipeline/history.py`
exists to answer "does this agency rebid this every three years", and it keys
on agency name rather than source id. So Vendor Registry's archive joins
straight onto the live OpenGov feeds for the same agencies and back-fills
recurrence for years those portals never carried.

That is the whole value here, and it is why this file exists at all.

## Reading it

Plain server-rendered HTML, one table, no paging — Madison County returns 385
rows in a single response. Two archive routes, because the platform splits
them: `ExpiredBidsList` for anything with a deadline that has passed, and
`NoDeadlineList` for standing solicitations. Both are read; every Florida buyer
sampled had zero of the latter, but a list that is empty today is not a list
that stays empty.

Read by header name. The markup reuses `headers="thDeadline"` on *both* the
status and deadline cells, so an attribute-driven read collapses two columns
into one and loses whichever it visits second.

`robots.txt` is unusually narrow — it disallows Zoominfobot and nobody else —
so no override is needed and none is taken.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get, session
from ..models.opportunity import Opportunity
from .base import SourceAdapter

BASE = "https://vrapp.vendorregistry.com"

#: The buyer's public board. Read only to be reported as empty — see the module
#: docstring for why it is not a source of open bids.
CURRENT_ROUTE = "/Bids/View/BidsList"

#: The two archive routes. Expired is everything whose deadline has passed;
#: NoDeadline is standing solicitations that never had one.
ARCHIVE_ROUTES = ("/Bids/View/ExpiredBidsList", "/Bids/View/NoDeadlineList")

#: The one table on the page.
TABLE_ID = "buyer-solicitation-table"

#: Per-solicitation detail pages, which are public and carry the full scope
#: text. Linked from the description cell.
DETAIL_PREFIX = "/Bids/View/Bid/"

#: What the runner reports instead of "portal listed no open solicitations",
#: so an always-empty source explains itself where someone will read it.
EMPTY_NOTE = (
    "archive only — Vendor Registry's current list reports no open solicitations "
    "for any buyer, in any state; these agencies post elsewhere now"
)

#: Portal status text that means the solicitation was pulled rather than run.
_CANCELLED = ("cancel", "withdrawn")


class VendorRegistryAdapter(SourceAdapter):
    """One Vendor Registry buyer. `vendor_registry_buyer` is its GUID."""

    #: Nothing here is open, so this source must not supersede an agency's
    #: catalog pointer. Sebring's says "register at BidNet Direct", which is
    #: where it posts now and the only useful thing we can tell anyone.
    provides_open_bids = False

    #: The detail page is public, but every row this adapter returns is already
    #: closed, so there is nothing a detail pass would change about a decision.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Always empty, and says so.

        Deliberately does not call the portal. The current list is known to
        report nothing for every buyer on the platform, so a request would be
        a round trip whose only possible answer is the one already recorded in
        `empty_note` — and an empty result with no explanation is precisely
        the failure mode this adapter exists to avoid.
        """
        self.empty_note = EMPTY_NOTE
        return []

    def fetch_history(self) -> List[Opportunity]:
        """The buyer's whole archive, across both routes.

        This is what the source is for: `src/pipeline/history.py` joins on
        agency name, so these records back-fill recurrence for agencies whose
        open bids now arrive from OpenGov.
        """
        # Resolved before the fetch loop, which swallows exceptions per route.
        # Left inside it, a missing buyer id would come back as "no archive page
        # could be read" — a plausible-looking outage hiding a typo in config.
        self._buyer()

        by_key: Dict[str, Opportunity] = {}
        read = 0
        for route in ARCHIVE_ROUTES:
            soup = self._page(route)
            if soup is None:
                continue
            read += 1
            for row in archive_rows(soup):
                opp = self._to_opportunity(row, route)
                if opp is not None:
                    by_key[f"{opp.external_id}|{opp.title}"] = opp

        if read == 0:
            self.degraded_reason = "no archive page could be read"
        return list(by_key.values())

    # -- internals ---------------------------------------------------------

    def _buyer(self) -> str:
        value = str(self.cfg.get("vendor_registry_buyer") or "").strip()
        if not value:
            raise ValueError(f"{self.source_id}: vendor_registry_buyer required")
        return value

    def _url(self, route: str) -> str:
        return f"{BASE}{route}?BuyerId={self._buyer()}"

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _page(self, route: str) -> Optional[BeautifulSoup]:
        try:
            html = get(self._url(route), s=self._session(), timeout=60).text
        except Exception:  # noqa: BLE001 — one route missing is not the buyer
            return None
        return BeautifulSoup(html, "lxml")

    def _to_opportunity(self, row: Dict[str, str], route: str) -> Optional[Opportunity]:
        title = (row.get("description") or "").strip()
        if not title:
            return None

        ref = (row.get("id #") or "").strip() or None
        fields = enrich(title, external_id=ref)
        status_text = (row.get("status") or "").lower()
        cancelled = any(word in status_text for word in _CANCELLED)

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # The per-bid page when the row links one, else the board it is on.
            url=row.get("detail_url") or self._url(route),
            solicitation_type=fields["solicitation_type"] or (row.get("type") or "").strip(),
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            due_date=parse_dt(row.get("deadline")),
            pre_bid_meeting=(
                f"Pre-bid meeting {row['pre-bid meeting']}"
                if (row.get("pre-bid meeting") or "").strip()
                else None
            ),
            status="cancelled" if cancelled else "closed",
            raw={"vendor_registry": row},
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def archive_rows(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Solicitation rows as header-label -> value, plus the detail URL.

    Read by header position against the header row, *not* by each cell's
    `headers` attribute: the markup labels both the status cell and the
    deadline cell `thDeadline`, so an attribute-keyed read silently keeps one
    and drops the other.
    """
    table = soup.find("table", id=TABLE_ID)
    if table is None:
        return []

    all_rows = table.find_all("tr")
    if not all_rows:
        return []
    headers = [c.get_text(" ", strip=True).lower() for c in all_rows[0].find_all(["th", "td"])]
    if not headers:
        return []

    out: List[Dict[str, str]] = []
    for tr in all_rows[1:]:
        cells = tr.find_all("td")
        if not cells:
            continue
        row = {name: cell.get_text(" ", strip=True) for name, cell in zip(headers, cells)}
        link = tr.find("a", href=True)
        if link is not None and DETAIL_PREFIX in link["href"]:
            row["detail_url"] = BASE + link["href"]
        if any(v for k, v in row.items() if k != "detail_url"):
            out.append(row)
    return out
