"""Ionwave — four Florida agencies whose public bid list needs no account.

`docs/statewide-coverage.md` filed Ionwave under *"free but needs a vendor
account"* and Phase 3, "needs a session-cookie handshake". Both halves are
wrong, and in a way worth writing down because it is the same mistake OpenGov
got: the route that was checked is not the route that is public.

`/` and `/CurrentSourcingEvents.aspx` do redirect to `Login.aspx`. But the
login page itself links, unauthenticated, to five public lists:

    SourcingEvents.aspx?SourceType=1   Current Bids
    SourcingEvents.aspx?SourceType=2   Closed Bids
    SourcingEvents.aspx?SourceType=3   Awarded Bids
    SourcingEvents.aspx?SourceType=4   Non Awarded Bids
    ActiveContractList.aspx            Active Contracts

Fetched cold, on a session with no cookies at all, every one of them returns a
populated grid. There is no handshake. Verified 2026-08-07 on all four Florida
tenants: Coconut Creek 2 current bids, Deerfield Beach 6, Lee County 9, Pasco
County Schools 1.

## The three-request ceiling, and what is not done about it

Cloudflare sits in front of every tenant and serves a managed challenge — the
"Just a moment..." interstitial, carrying status **429** — from roughly the
fourth request on one session. It is not a rate limit: pacing does not move it.
At five seconds between requests the fourth request is challenged just the same
as at one and a half.

A *fresh* session is served immediately, challenge or no challenge. So the
challenge counts requests per cookie jar, and rotating sessions would walk
straight through it. This adapter deliberately does not do that. `netpolicy`
says a refusal is not worked around from another angle, and a challenge is a
refusal — the operator saying "prove you are not a bot", to which the honest
answer here is "I am a bot" and the honest response is to stop.

What that leaves is a budget of `REQUEST_BUDGET` requests per session, spent
deliberately:

* **`fetch` costs exactly one request** and is never at risk. The page holds 20
  rows and no Florida tenant currently posts close to that, so the routine
  crawl never provokes the challenge at all.
* **`fetch_history` walks the archive** and will usually be cut short. It is
  ordered awarded-first because that list is the one that feeds something —
  the protest clock and the records trigger — and it reports what it did not
  reach rather than presenting a partial archive as the whole one.
* **The contract register is not read.** `ActiveContractList.aspx` is real and
  substantial (Lee County alone publishes **1,671 active contracts** with
  supplier names and end dates), but it pages at 25 rows: 67 requests for one
  tenant, against a budget of three. Storing the 25 rows that fit would put a
  1.5% sample into the same table as Bonfire's complete registers, where
  `expiring_within` cannot tell the difference. An absent register is honest;
  a register that is silently 1.5% of itself is not.

## Reading the grid

A Telerik RadGrid, `ctl00_mainContent_rgBidList`. Two things about it:

* **The columns change with the source type.** Current and Closed end with Bid
  Issue Date and Bid Close Date/Time; Awarded ends with Bid Award Date and
  Non Awarded with Bid Non Award Date — and both drop a column doing it. Read
  positionally, an award date lands in the issue-date field on two lists out of
  four. Everything here is read by header name.
* **The pager states its own arithmetic**: "68 items in 4 pages". That is the
  paging oracle, so the walk knows before it starts whether one page is the
  whole list — which, with three requests to spend, is the difference between
  spending them and not needing to.

Status comes from the list rather than from a column, because there is no
status column: the source type *is* the status. Awarded rows carry a real award
date, so they arrive as `award` with a protest deadline, which is what puts an
Ionwave award on the 72-hour clock in `src/protest.py`. That date renders at
01:00 ET — a date-only value with a placeholder time — so the computed deadline
runs slightly early. That is the safe direction for a deadline and the reason
it is used rather than dropped.

Detail is genuinely login-gated: the "View Bid" cell is a `<span>` with no
href, and the row click needs a session. `supports_detail` stays False.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import SourceBlocked, get, is_challenge, session
from ..models.opportunity import Opportunity
from ..netpolicy import check
from ..protest import protest_deadline
from .base import SourceAdapter

#: The grid Ionwave renders every list into. The `_ctl00` suffix is RadGrid's
#: inner table; the outer div carries the id without it.
GRID_ID = "ctl00_mainContent_rgBidList_ctl00"

#: RadGrid marks data rows with these classes and nothing else with them, which
#: is how the filter row, the pager and the page-size combo stay out of the data.
_ROW_CLASSES = ("rgRow", "rgAltRow")

#: The public lists, and what each one means for `Opportunity.status`.
#: 4 is "Non Awarded" — closed with no award made — which is `cancelled`
#: rather than `closed`: nothing was bought, and it is likely to come back.
SOURCE_TYPES: Dict[int, tuple] = {
    1: ("Current Bids", "open"),
    2: ("Closed Bids", "closed"),
    3: ("Awarded Bids", "award"),
    4: ("Non Awarded Bids", "cancelled"),
}

#: Archive lists, in the order they are worth spending requests on. Awarded
#: first: it is the only one that feeds anything (the protest clock and the
#: day-31 records trigger), and it is the one most likely to be cut off.
HISTORY_TYPES = (3, 2, 4)

#: Requests one session gets before Cloudflare challenges it. Measured, not
#: guessed: the fourth request is challenged at 1.5s, 3s and 5s spacing alike.
#: Held one below the observed threshold so a redirect never spends the margin.
REQUEST_BUDGET = 3

#: Server-side page size on every list.
PAGE_SIZE = 20

#: Zone labels the grid appends to its times, e.g. "8/21/2026 10:00:00 AM (ET)".
#: `parse_dt` returns naive Eastern wall-clock and cannot read the suffix, so
#: every close date on every list parses to None with it left on. Only Eastern
#: labels are stripped: they agree with what `parse_dt` already assumes, and a
#: tenant labelled "(CT)" should read as no date rather than as an hour wrong.
_EASTERN_LABELS = ("(ET)", "(EST)", "(EDT)")

#: ASP.NET's hidden fields. There is no `__EVENTVALIDATION` on these pages —
#: unusually — so a postback carrying only the ViewState pair is accepted.
_VIEWSTATE_FIELDS = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__VIEWSTATEENCRYPTED")

#: What the fetch layer reports when the challenge is served. `http_util.get`
#: raises `SourceBlocked` for it rather than retrying into it, so the adapter
#: only has to tell that case apart from an ordinary refusal.
_CHALLENGE_NOTE = "Cloudflare challenged the session; the rest was not read"


class IonwaveAdapter(SourceAdapter):
    """One Ionwave tenant. `ionwave_host` is its subdomain, e.g. `leegov.ionwave.net`."""

    #: The row click that opens a bid needs a signed-in session, and this
    #: project does not create accounts to harvest.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None
        self._spent = 0
        self._blocked = False

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Current bids. One request, which is why this path never gets challenged."""
        return self._collect(1)

    def fetch_history(self) -> List[Opportunity]:
        """The archive, as far as the request budget reaches.

        Walks awarded, then closed, then non-awarded, and names the lists it
        never got to in `degraded_reason` rather than returning a partial
        archive that looks complete.
        """
        out: List[Opportunity] = []
        unreached: List[str] = []
        for source_type in HISTORY_TYPES:
            if self._exhausted():
                unreached.append(SOURCE_TYPES[source_type][0])
                continue
            out.extend(self._collect(source_type))
        if unreached:
            self._note(f"did not reach {', '.join(unreached)} within the request budget")
        return out

    # -- internals ---------------------------------------------------------

    def _host(self) -> str:
        value = str(self.cfg.get("ionwave_host") or "").strip()
        if not value:
            raise ValueError(f"{self.source_id}: ionwave_host required")
        return value

    def _list_url(self, source_type: int) -> str:
        return f"https://{self._host()}/SourcingEvents.aspx?SourceType={source_type}"

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _exhausted(self) -> bool:
        return self._blocked or self._spent >= REQUEST_BUDGET

    def _challenged(self) -> None:
        """Record the refusal and stop, rather than seeing what still answers.

        The challenge is soft: a later request on the same session is sometimes
        served anyway. Taking it would be working around a refusal by waiting
        for a gap in it, which is the same move as rotating the session and
        wrong for the same reason.
        """
        self._blocked = True
        self._note(_CHALLENGE_NOTE)

    def _note(self, reason: str) -> None:
        """Record a degradation without discarding one already recorded."""
        if self.degraded_reason:
            if reason not in self.degraded_reason:
                self.degraded_reason = f"{self.degraded_reason}; {reason}"
        else:
            self.degraded_reason = reason

    def _get(self, source_type: int) -> Optional[BeautifulSoup]:
        """Page one of a list, or None if the budget or the challenge stops us."""
        if self._exhausted():
            return None
        url = self._list_url(source_type)
        self._spent += 1
        try:
            # No retries: every 429 this host serves is the challenge, and a
            # retry would spend a second request against the limit that caused
            # it while reporting one.
            html = get(url, s=self._session(), timeout=45, retries=0).text
        except SourceBlocked as e:
            if "challenge" in str(e):
                self._challenged()
            else:
                self._note("the portal refused the request")
            return None
        except Exception:  # noqa: BLE001 — one tenant's outage is not the crawl's
            self._note("the list page could not be read")
            return None
        return BeautifulSoup(html, "lxml")

    def _next_page(self, soup: BeautifulSoup, source_type: int, page: int):
        """Post back for `page`, targeting the pager's own numbered link.

        The target is read off the anchor rather than computed. RadGrid names
        its pager controls `ctl05`, `ctl07`, `ctl09`… and renumbers them as the
        window of visible page numbers slides, so a computed id is right on
        page two and wrong by page twelve.
        """
        if self._exhausted():
            return None
        target = _page_target(soup, page)
        if target is None:
            return None

        form = {}
        for name in _VIEWSTATE_FIELDS:
            el = soup.find("input", {"name": name})
            if el is not None:
                form[name] = el.get("value", "")
        if "__VIEWSTATE" not in form:
            return None
        form["__EVENTTARGET"] = target
        form["__EVENTARGUMENT"] = ""

        url = self._list_url(source_type)
        check(url)
        self._spent += 1
        try:
            resp = self._session().post(url, data=form, timeout=60)
        except Exception:  # noqa: BLE001 — a lost page is not a lost agency
            self._note("a page of the archive could not be read")
            return None
        # Posts bypass `get`, so the challenge is checked for here directly.
        if is_challenge(resp):
            self._challenged()
            return None
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "lxml")

    def _collect(self, source_type: int) -> List[Opportunity]:
        soup = self._get(source_type)
        if soup is None:
            return []

        label, status = SOURCE_TYPES[source_type]
        total_pages = _total_pages(soup)
        by_key: Dict[str, Opportunity] = {}
        read = 0

        for page in range(1, (total_pages or 1) + 1):
            if page > 1:
                nxt = self._next_page(soup, source_type, page)
                if nxt is None:
                    break
                soup = nxt

            rows = grid_rows(soup)
            if not rows:
                break
            read = page
            for row in rows:
                opp = self._to_opportunity(row, source_type, status)
                if opp is not None:
                    by_key[f"{opp.external_id}|{opp.title}"] = opp
            if len(rows) < PAGE_SIZE:
                break

        if read == 0:
            self._note(f"the {label} grid was not found on the page")
        elif total_pages and read < total_pages:
            self._note(f"read {read} of {total_pages} pages of {label}")
        return list(by_key.values())

    def _to_opportunity(
        self, row: Dict[str, str], source_type: int, status: str
    ) -> Optional[Opportunity]:
        title = (row.get("bid title") or "").strip()
        if not title:
            return None

        ref = (row.get("bid number") or "").strip() or None
        fields = enrich(title, external_id=ref)

        posted = _when(row.get("bid issue date"))
        # Awarded and non-awarded lists carry a decision date instead of an
        # issue date, and dropping it would lose the only date those rows have.
        decided = _when(row.get("bid award date") or row.get("bid non award date"))

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # No per-bid URL exists without a session, so this points at the
            # public list the row was actually read from.
            url=self._list_url(source_type),
            solicitation_type=fields["solicitation_type"] or (row.get("bid type") or "").strip(),
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            department=(row.get("organization") or "").strip() or None,
            award_date=decided.date() if decided and status == "award" else None,
            posted_date=(posted or decided).date() if (posted or decided) else None,
            due_date=_when(row.get("bid close date/time")),
            # An award with no clock cannot be acted on; one with a clock goes
            # straight onto the 72-hour protest window in the digest.
            protest_deadline=protest_deadline(decided) if status == "award" else None,
            status=status,
            raw={"ionwave": row, "ionwave_list": SOURCE_TYPES[source_type][0]},
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _when(value: Optional[str]):
    """Parse a grid timestamp, dropping the Eastern zone label it carries."""
    text = (value or "").strip()
    for label in _EASTERN_LABELS:
        if text.upper().endswith(label):
            text = text[: -len(label)].strip()
            break
    return parse_dt(text)


def grid_rows(soup: BeautifulSoup) -> List[Dict[str, str]]:
    """Bid rows as header-label -> value.

    By header name, not position: the awarded and non-awarded lists carry one
    column fewer and end with a decision date where the others end with a close
    date/time, so a positional read files award dates as issue dates on half
    the lists.
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
    for tr in all_rows:
        classes = tr.get("class") or []
        if not classes or classes[0] not in _ROW_CLASSES:
            continue
        cells = tr.find_all("td")
        row = {
            name: cell.get_text(" ", strip=True)
            for name, cell in zip(headers, cells)
            if name
        }
        if any(row.values()):
            out.append(row)
    return out


def _total_pages(soup: BeautifulSoup) -> Optional[int]:
    """Pages in this list, from the pager's own "68 items in 4 pages".

    Worth reading rather than inferring from row count: with three requests to
    spend, knowing page one is the whole list is what keeps `fetch` from
    posting back to discover the same thing.
    """
    part = soup.find(class_="rgInfoPart")
    if part is None:
        return None
    words = part.get_text(" ", strip=True).split()
    for i, word in enumerate(words):
        if word.startswith("page") and i and words[i - 1].isdigit():
            return int(words[i - 1])
    return None


def _page_target(soup: BeautifulSoup, page: int) -> Optional[str]:
    """The postback target behind the pager link numbered `page`."""
    part = soup.find(class_="rgNumPart")
    if part is None:
        return None
    for a in part.find_all("a", href=True):
        if a.get_text(strip=True) == str(page) and "__doPostBack" in a["href"]:
            pieces = a["href"].split("'")
            if len(pieces) > 1:
                return pieces[1]
    return None
