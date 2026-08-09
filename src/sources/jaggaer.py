"""Jaggaer public events — four Florida universities, one of them still posting.

The research files this under "PeopleSoft / Oracle EBS / Jaggaer one-offs" with
`bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=UNF` as the example and
FIU "at `bids.fiu.edu`". The URL template is right. Everything around it needed
checking, and three things came back different:

* **UNF has left.** Its own page carries the notice: *"Beginning July 1, 2026,
  all University of North Florida solicitations will be posted through the
  University's new Bid Portal."* Open and Upcoming both return "No Events". It
  moved to Workday Strategic Sourcing, which is a different platform again.
* **FIU was never on it in the way described.** `bids.fiu.edu` is FIU's own
  procurement page, not a Jaggaer portal. FIU *does* have a Jaggaer tenant, but
  it answers as "myFIUmarket System Administrator" and carries only an archive.
* **FSU is the live one**, and the research never mentions it — seven open
  solicitations on 7 Aug 2026, found by fingerprinting `procurement.fsu.edu`
  rather than by guessing tenant codes.

Probing the twelve state universities' tenant codes gives the real map. Seven
answer `400 System Error` and are simply not tenants (UF, UCF, FGCU, UWF, FAMU,
Florida Poly, New College); USF is a tenant with nothing in any tab, which is a
shell rather than a source.

    FSU   7 open · 20 closed · 20 awarded      <- configured
    FAU   0 open · 20 closed · 20 awarded      <- configured, between solicitations
    FIU   0 open · 16 closed · 20 awarded      <- configured
    UNF   0 open · 20 closed · 20 awarded      <- left the platform; not configured
    USF   0 · 0 · 0                            <- empty tenant; not configured

UNF is deliberately absent. A source that can only ever return zero reads as a
quiet agency rather than a departed one, which is the mistake this project has
made three times already.

## Reading it

Four tabs on one GET-addressable route, no session, no paging parameters:
`?CustomerOrg={org}&tab=PHX_NAV_Sourcing{OpenForBid|Upcoming|Closed|Award}`.
Open and Upcoming are what a bidder acts on; Closed and Award are the archive.

Each row is a nested block rather than a set of cells, so the fields are read
from the portal's own label/value pairs — `Open`, `Close`, `Type`, `Number`,
`Contact` — instead of by column position. There is no column position to rely
on: the whole row lives in one `<td>`.

The archive tabs return twenty rows and stop. That is a page, not a total, and
`fetch_history` says so rather than reporting twenty as the whole archive.

## robots

`bids.sciquest.com` serves `User-agent: * / Disallow: /`, the same blanket file
Bonfire and Ionwave serve. The same reasoning applies and is recorded in the
same table: these are Florida public universities' competitive solicitations,
published because they have to be, and the records belong to the university
rather than to its portal vendor.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..protest import protest_deadline
from ..http_util import get, session
from ..models.opportunity import Opportunity
from .base import SourceAdapter

BASE = "https://bids.sciquest.com/apps/Router/PublicEvent"

#: The portal's four tabs, and what each means here. Open and Upcoming are
#: biddable; the other two are the archive.
TABS: Dict[str, str] = {
    "PHX_NAV_SourcingOpenForBid": "open",
    "PHX_NAV_SourcingUpcoming": "upcoming",
    "PHX_NAV_SourcingClosed": "closed",
    "PHX_NAV_SourcingAward": "award",
}

LIVE_TABS = ("PHX_NAV_SourcingOpenForBid", "PHX_NAV_SourcingUpcoming")
ARCHIVE_TABS = ("PHX_NAV_SourcingClosed", "PHX_NAV_SourcingAward")

#: The event grid. Every row is a single `<td>` holding a nested block, so this
#: identifies the table and the row parsing does the rest.
GRID_CLASS = "table-hover"

#: What the portal prints when a tab is empty. Checked so an empty tab is told
#: apart from a parse that found nothing it recognised.
_EMPTY = "no events have"

#: The archive tabs stop at twenty rows with no pager to follow.
PAGE_SIZE = 20


class JaggaerAdapter(SourceAdapter):
    """One Jaggaer tenant. `jaggaer_org` is its `CustomerOrg` code, e.g. `FSU`."""

    #: The event link goes to `app01.jaggaer.com` behind a per-render AuthToken,
    #: which is a fetch-now URL rather than an address. The list already carries
    #: the number, the type, both dates, the contact and a description.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None
        self._counts: Dict[str, int] = {}

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Open and upcoming solicitations."""
        return self._collect(LIVE_TABS)

    def fetch_history(self) -> List[Opportunity]:
        """Closed and awarded, as far as one page of each goes."""
        opps = self._collect(ARCHIVE_TABS)
        if any(self._counts.get(tab, 0) >= PAGE_SIZE for tab in ARCHIVE_TABS):
            self._note(
                f"the archive tabs stop at {PAGE_SIZE} rows with no pager; "
                "this is the most recent page, not the whole archive"
            )
        return opps

    # -- internals ---------------------------------------------------------

    def _org(self) -> str:
        value = str(self.cfg.get("jaggaer_org") or "").strip()
        if not value:
            raise ValueError(f"{self.source_id}: jaggaer_org required")
        return value

    def _url(self, tab: str) -> str:
        return f"{BASE}?CustomerOrg={self._org()}&tab={tab}"

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _note(self, reason: str) -> None:
        if self.degraded_reason:
            if reason not in self.degraded_reason:
                self.degraded_reason = f"{self.degraded_reason}; {reason}"
        else:
            self.degraded_reason = reason

    def _collect(self, tabs) -> List[Opportunity]:
        self._org()  # a config error must not read as an unreachable portal
        self._counts: Dict[str, int] = {}

        by_key: Dict[str, Opportunity] = {}
        read = 0
        for tab in tabs:
            try:
                html = get(self._url(tab), s=self._session(), timeout=60).text
            except Exception:  # noqa: BLE001 — one tab is not the tenant
                continue
            read += 1
            rows = event_rows(html)
            self._counts[tab] = len(rows)
            if not rows and not is_empty_tab(html):
                self._note(f"the {TABS[tab]} tab had no readable rows")
            for row in rows:
                opp = self._to_opportunity(row, tab)
                if opp is not None:
                    by_key[f"{opp.external_id}|{opp.title}"] = opp

        if read == 0:
            self._note("no tab of the portal could be read")
        return list(by_key.values())

    def _to_opportunity(self, row: Dict[str, str], tab: str) -> Optional[Opportunity]:
        title = (row.get("title") or "").strip()
        if not title:
            return None

        ref = (row.get("number") or "").strip() or None
        fields = enrich(title, external_id=ref)

        status = TABS[tab]
        # An award row starts the 72-hour protest clock like every other
        # adapter's award rows do — mfmp and ionwave already did; this one
        # silently didn't, and the inconsistency read as a missing deadline.
        protest = None
        if status == "award":
            anchor = parse_dt(row.get("close")) or parse_dt(row.get("open"))
            protest = protest_deadline(anchor)

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # The row's own link is an AuthToken URL minted for that render, so
            # this points at the board instead — which is where it lives.
            url=self._url(tab),
            solicitation_type=fields["solicitation_type"] or (row.get("type") or "").strip(),
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            description=(row.get("description") or "").strip() or None,
            contact=(row.get("contact") or "").strip() or None,
            posted_date=_date(row.get("open")),
            due_date=parse_dt(row.get("close")),
            status=status,
            protest_deadline=protest,
            raw={"jaggaer": row},
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def is_empty_tab(html: str) -> bool:
    """True when the portal itself says the tab holds nothing.

    Worth telling apart from a parse that recognised nothing: one is an agency
    between solicitations, the other is markup that changed under us.
    """
    return _EMPTY in " ".join((html or "").split()).lower()


def event_rows(html: str) -> List[Dict[str, str]]:
    """Solicitations as flat dicts, read from the portal's own field labels.

    There is no column position to read by — the entire row is one `<td>`
    holding a nested block — so the label/value pairs the portal renders
    (`Open`, `Close`, `Type`, `Number`, `Contact`) are the only stable handles.
    """
    soup = BeautifulSoup(html or "", "lxml")
    grid = next(
        (t for t in soup.find_all("table") if GRID_CLASS in (t.get("class") or [])),
        None,
    )
    if grid is None:
        return []

    out: List[Dict[str, str]] = []
    for tr in grid.find_all("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue

        row: Dict[str, str] = {}
        link = tr.find("a", class_=re.compile("btn-link-header"))
        if link is not None:
            row["title"] = link.get_text(" ", strip=True)
            row["event_url"] = link.get("href") or ""
        blurb = tr.find("div", class_=re.compile("label-mini"))
        if blurb is not None:
            row["description"] = blurb.get_text(" ", strip=True)
        badge = tr.find("span", class_=re.compile("status-badge"))
        if badge is not None:
            row["status"] = badge.get_text(" ", strip=True)

        for layout in tr.select("div.table-row-layout"):
            pair = layout.select("div.table-cell-layout")
            if len(pair) < 2:
                continue
            label = pair[0].get_text(" ", strip=True).lower()
            value = pair[1].get_text(" ", strip=True)
            if label and value:
                row.setdefault(label, value)

        if row.get("title"):
            out.append(row)
    return out


def _date(value: Optional[str]):
    """The portal writes '8/3/2026, 12:00 AM EDT'; only the day is wanted here."""
    parsed = parse_dt(value)
    return parsed.date() if parsed else None
