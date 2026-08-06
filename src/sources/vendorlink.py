"""VendorLink — 156 Florida agencies from one public dropdown.

Florida-native, and materially bigger in this state than DemandStar or Bid
Express. The whole tenant directory is a `<select>` on any agency's page, which
makes the source list discoverable rather than curated:

    https://www.myvendorlink.com/external/bids?a=<agencyId>

Its `robots.txt` is unusually explicit — `User-agent: * / Allow: /external/` —
so the path this adapter reads is the one the operator published for reading.

Three things shape this adapter:

* **The grid pages, and the page is 22 rows.** Every agency returns exactly 22
  rows on the first request, which looks like a small agency and is not: it is
  an ASP.NET GridView with a pager. Reading one page and reporting 22 would
  under-count an agency with hundreds of solicitations, silently and forever.
  Paging is a `__doPostBack` against the grid, so it needs the ViewState trio
  carried forward from the previous page.
* **The grid is sorted by broadcast date, newest first**, and open
  solicitations therefore cluster on page one. `fetch` walks until a whole page
  contains nothing open, which terminates in two or three requests for a
  routine crawl; `fetch_history` walks the archive properly.
* **Detail is behind a login.** `BidDetail.aspx` redirects to a sign-in page,
  and this project does not create accounts to harvest. So the list is all we
  take, and `supports_detail` stays False rather than pretending otherwise —
  the list is unusually rich anyway, carrying the reference number, both
  deadlines and the pre-bid flag.

Self-hosted instances exist (Osceola runs `vendorlink.osceola.org`), but the
one checked serves a login page rather than a public grid, so only the shared
host is configured here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get, session
from ..models.opportunity import Opportunity
from ..netpolicy import check
from .base import SourceAdapter

BASE = "https://www.myvendorlink.com"
BIDS = f"{BASE}/external/bids"

#: The grid's own id. Also the postback target for paging.
GRID_ID = "ctl00_RegionMiddle_grvSolicitations"
GRID_TARGET = "ctl00$RegionMiddle$grvSolicitations"

#: The agency dropdown — the platform's own tenant directory. Scoping to it
#: matters: the fiscal-year and status selects also carry numeric values.
AGENCY_SELECT_ID = "ctl00_RegionMiddle_ddlAgency"

#: Hidden fields ASP.NET requires on a postback. Missing any of them returns
#: the first page again, which would look like a grid that will not advance.
_VIEWSTATE_FIELDS = (
    "__VIEWSTATE",
    "__VIEWSTATEGENERATOR",
    "__EVENTVALIDATION",
    "__VIEWSTATEENCRYPTED",
)

#: Server-side page size, observed identical across every agency sampled.
PAGE_SIZE = 22

#: Hard stop. At 22 rows a page this is ~1,300 solicitations, past which we are
#: reading an archive nobody asked for.
MAX_PAGES = 60

#: What the portal's status badges mean for us. Anything unrecognised is
#: treated as closed, which is the safe direction: a mislabelled open bid is a
#: missed opportunity, a mislabelled closed one is a false alarm on the board.
_STATUS = {
    "active": "open",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "under evaluation": "closed",
    "awarded": "closed",
    "closed / completed": "closed",
    "closed/completed": "closed",
    "all bids rejected": "closed",
}


class VendorLinkAdapter(SourceAdapter):
    """One VendorLink agency. `vendorlink_agency` is the numeric id from the dropdown."""

    #: Detail is login-gated, and we do not hold credentials for it.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Open solicitations, paging only as far as they go."""
        return self._collect(open_only=True)

    def fetch_history(self) -> List[Opportunity]:
        """The agency's archive — awarded, evaluated, cancelled and completed."""
        return self._collect(open_only=False)

    def agencies(self) -> Dict[str, str]:
        """The whole tenant directory, id -> name, from the agency dropdown.

        Scoped to `ddlAgency` deliberately. The page carries four other selects,
        and two of them — fiscal year and status — have numeric option values
        too, so reading every `<option>` on the page yields a directory
        containing "1998" through "2026" as though they were agencies.
        """
        soup = self._page_one()
        select = soup.find("select", id=AGENCY_SELECT_ID)
        if select is None:
            return {}

        out: Dict[str, str] = {}
        for option in select.find_all("option"):
            value = (option.get("value") or "").strip()
            label = option.get_text(" ", strip=True)
            if value.isdigit() and label:
                out[value] = label
        return out

    # -- internals ---------------------------------------------------------

    def _agency_id(self) -> str:
        value = self.cfg.get("vendorlink_agency")
        if not value:
            raise ValueError(f"{self.source_id}: vendorlink_agency required")
        return str(value)

    def _url(self) -> str:
        return f"{BIDS}?a={self._agency_id()}"

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _page_one(self) -> BeautifulSoup:
        return BeautifulSoup(get(self._url(), s=self._session(), timeout=40).text, "lxml")

    def _next_page(self, soup: BeautifulSoup, page: int) -> Optional[BeautifulSoup]:
        """Post back for `page`, carrying this page's ViewState forward."""
        form = {}
        for name in _VIEWSTATE_FIELDS:
            el = soup.find("input", {"name": name})
            if el is not None:
                form[name] = el.get("value", "")
        if "__VIEWSTATE" not in form:
            return None

        form["__EVENTTARGET"] = GRID_TARGET
        form["__EVENTARGUMENT"] = f"Page${page}"
        url = self._url()
        check(url)
        try:
            resp = self._session().post(url, data=form, timeout=45)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001 — a lost page is not a lost agency
            return None
        return BeautifulSoup(resp.text, "lxml")

    def _collect(self, *, open_only: bool) -> List[Opportunity]:
        soup = self._page_one()
        by_key: Dict[str, Opportunity] = {}
        pages_read = 0

        for page in range(1, MAX_PAGES + 1):
            if page > 1:
                nxt = self._next_page(soup, page)
                if nxt is None:
                    break
                soup = nxt

            rows = _grid_rows(soup)
            if not rows:
                break
            pages_read += 1

            page_open = 0
            for row in rows:
                opp = self._to_opportunity(row)
                if opp is None:
                    continue
                if opp.status == "open":
                    page_open += 1
                if open_only != (opp.status == "open"):
                    continue
                by_key[f"{opp.external_id}|{opp.title}"] = opp

            # The grid is newest-first, so once a whole page holds nothing open
            # there is nothing open further back either.
            if open_only and page_open == 0 and page > 1:
                break
            if len(rows) < PAGE_SIZE:
                break
        else:
            self.degraded_reason = (
                f"stopped at the {MAX_PAGES}-page cap; this agency's archive is "
                "longer than we read"
            )

        if pages_read == 0:
            self.degraded_reason = "the solicitations grid was not found on the page"
        return list(by_key.values())

    def _to_opportunity(self, row: Dict[str, str]) -> Optional[Opportunity]:
        title = (row.get("title") or "").strip()
        if not title:
            return None

        ref = (row.get("number") or "").strip() or None
        fields = enrich(title, external_id=ref)
        status = _STATUS.get((row.get("status") or "").strip().lower(), "closed")
        posted = parse_dt(row.get("broadcast date"))

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # There is no per-solicitation URL without a session, so this points
            # at the agency's public board — where the row genuinely lives.
            url=self._url(),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            posted_date=posted.date() if posted else None,
            due_date=parse_dt(row.get("due date")),
            questions_due=parse_dt(row.get("question end date")),
            pre_bid_meeting="Mandatory pre-bid meeting" if row.get("mandatory pre-bid") else None,
            status=status,
            raw={"vendorlink": row},
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _grid_rows(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Solicitation rows as label -> value, keyed by the grid's own headers.

    Read by header name rather than column position: this is a generated
    GridView, and a column inserted upstream would otherwise shift every field
    one place and quietly file due dates under question deadlines.
    """
    table = soup.find("table", id=GRID_ID)
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
        # The pager is a row too, and has one cell spanning the table.
        if len(cells) < len(headers) - 1:
            continue
        row: Dict[str, str] = {}
        for name, cell in zip(headers, cells):
            box = cell.find("input", {"type": "checkbox"})
            row[name] = "yes" if (box is not None and box.has_attr("checked")) else (
                "" if box is not None else cell.get_text(" ", strip=True)
            )
        if any(row.values()):
            out.append(row)
    return out
