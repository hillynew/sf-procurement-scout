"""DemandStar — the largest platform in Florida this build could not read.

36 agencies fingerprinted strong, and the research said not to bother:
*"DemandStar and BidNet are not required for coverage. They are useful as
fingerprinting oracles, not as data sources"*, on the reading that "agency
names and titles are public SEO surface, documents are the paid product."

Half right. The documents are indeed the paid product — and so is every detail
view, which is why this adapter is list-only. But the *list* is a public,
unauthenticated JSON API, and it carries more than a title: identifier, agency,
advertisement date, due date, city, and a status specific enough to tell an
open solicitation from one under evaluation from an intended award.

## The route

`www.demandstar.com/app/...` is a 2.6 KB React shell; the data comes from
`api.demandstar.com`. The app's own compiled bundle names its endpoints, and
one field in it is the whole map — `urlNoAuth`, the base it uses for the calls
that need no login:

    GET https://api.demandstar.com/contents/agency/search?id=<guid>

That returns up to 100 of an agency's solicitations as JSON, no key, no cookie,
no handshake. `<guid>` is the agency identifier out of its own landing-page URL,
which is why it lives in config as `demandstar_agency` — the same shape as
`bonfire_host` or `jaggaer_org`.

## Where the line is, and why the adapter stops there

Three neighbouring endpoints answer `401`:

* `/bid/summary` — the detail view, so scope, documents and contacts are out of
  reach. `supports_detail` is False and the row's URL points at the public
  `/app/limited/bids/<id>/details` page, which a person's browser renders and
  this crawler never fetches.
* `/common/getAgencies` — the agency directory. There is no public way to
  enumerate Florida's DemandStar tenants, so the GUIDs come from fingerprinting
  each agency's own website, one at a time.
* The statewide browse (`POST /agency/bids` with `{"state": "FL"}`) *is* public
  but returns 20 rows across 10 agencies, all already awarded. It is an SEO
  surface, not a feed, and it is not used here.

Nothing in this file tries to get past any of those. A 401 is an answer.

## The 100-row window

`total` never exceeds 100 and the endpoint ignores every paging parameter tried
(`page`, `pageNumber`, `pageSize`). So this is the most recent 100 per agency,
which is generous for open bids — the busiest Florida tenant had 6 — and a
partial archive for history. `fetch_history` says so rather than implying the
archive is complete.

## Status

Four values appear across the 16 Florida agencies measured, and they are not
all "open or closed":

* `AC` Active — biddable.
* `OP` Under Evaluation — bidding closed, agency deciding.
* `RA` Recommendation of Award — a notice of intended decision, which starts
  the 72-hour protest clock under s. 120.57(3)(b).
* `AW` Awarded — decided.

`RA` and `AW` both map to `award`, the status this build keeps out of every
open-bid view precisely because the thing to do with one is protest it, not
respond to it. No protest deadline is computed: the only date on the row is the
*advertisement* date, and a protest clock runs from the posting of the
intended decision. A deadline derived from the wrong date would be worse than
none, because it would look authoritative.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter

#: The unauthenticated base. Named `urlNoAuth` in the app's own config, which
#: is as clear a statement as a vendor makes about which half is public.
API = "https://api.demandstar.com/contents"

#: One GET per agency per cycle.
LIST = API + "/agency/search?id={guid}"

#: What a person opens. Rendered client-side, so it is a link, never a fetch.
BID_PAGE = "https://www.demandstar.com/app/limited/bids/{bid_id}/details"

#: `statusType` -> this build's status. `internalStatus` is a second, coarser
#: code ("BR") that does not distinguish these, so the mapping keys on the one
#: that does.
STATUS = {
    "AC": "open",
    "OP": "closed",
    "RA": "award",
    "AW": "award",
    "CP": "closed",
    "CA": "cancelled",
}

#: The endpoint's ceiling. Not a page size — a window: paging parameters are
#: accepted and ignored.
WINDOW = 100


class DemandStarAdapter(SourceAdapter):
    """One DemandStar agency. `demandstar_agency` is the GUID from its landing URL."""

    #: Every detail endpoint answers 401. The listing is the whole public
    #: surface, and pretending otherwise would mean holding credentials.
    supports_detail = False

    def fetch(self) -> List[Opportunity]:
        """Solicitations open for response."""
        return [o for o in self._all() if o.status == "open"]

    def fetch_history(self) -> List[Opportunity]:
        """Closed, awarded and cancelled, as far as the window reaches."""
        rows = self._rows()
        if len(rows) >= WINDOW:
            self._note(
                f"the agency list stops at {WINDOW} rows with no pager; "
                "this is the most recent page, not the whole archive"
            )
        out = [o for o in (self._to_opportunity(r) for r in rows) if o is not None]
        return [o for o in out if o.status != "open"]

    # -- internals ---------------------------------------------------------

    def _guid(self) -> str:
        value = str(self.cfg.get("demandstar_agency") or "").strip()
        if not value:
            raise ValueError(f"{self.source_id}: demandstar_agency required")
        return value

    def _rows(self) -> List[Dict[str, Any]]:
        # Resolved before the tolerant fetch below, so a config mistake raises
        # instead of being reported as an unreachable portal.
        url = LIST.format(guid=self._guid())
        try:
            body = get(url, timeout=45).json()
        except Exception:  # noqa: BLE001 — one agency is not the run
            self.degraded_reason = "the agency listing did not answer"
            return []
        if not isinstance(body, dict):
            self.degraded_reason = "the agency listing was not the JSON expected"
            return []
        return [r for r in (body.get("result") or []) if isinstance(r, dict)]

    def _all(self) -> List[Opportunity]:
        return [o for o in (self._to_opportunity(r) for r in self._rows()) if o is not None]

    def _note(self, reason: str) -> None:
        if self.degraded_reason:
            if reason not in self.degraded_reason:
                self.degraded_reason = f"{self.degraded_reason}; {reason}"
        else:
            self.degraded_reason = reason

    def _to_opportunity(self, row: Dict[str, Any]) -> Optional[Opportunity]:
        title = str(row.get("bidName") or "").strip()
        bid_id = str(row.get("bidId") or "").strip()
        if not title or not bid_id:
            return None

        # `bidIdentifier` is the agency's own number, which is what a vendor
        # searches by and what matches this bid to its past cycles. It arrives
        # with the type doubled on some rows — "ITN-ITN-25-044-DR-0-2026/DR" —
        # so `enrich` reads the title for the type and this stays as written.
        ref = str(row.get("bidIdentifier") or "").strip() or bid_id
        fields = enrich(title, external_id=ref)
        posted = parse_dt(row.get("broadCastDate"))
        status = STATUS.get(str(row.get("statusType") or "").strip().upper(), "closed")

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            url=BID_PAGE.format(bid_id=bid_id),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            posted_date=posted.date() if posted else None,
            due_date=parse_dt(row.get("dueDate")),
            status=status,
            # No protest deadline: see the module docstring. The only date here
            # is the advertisement, and the clock runs from the intended
            # decision.
            raw={"demandstar": row},
        )
