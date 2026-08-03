"""MyFloridaMarketPlace Vendor Information Portal — every state agency, free.

This is the single highest-value source in the scout. Rule 60A-1.021, F.A.C.
makes the VIP the state's mandatory electronic posting point, so one adapter
covers all executive-branch agencies, the twelve state universities, the state
colleges, all five water management districts, and the handful of counties and
cities that post here too. No login, no API key, no subscription.

The portal is an Angular app whose backend lives under ``/mfmp/pub/*`` — the
``pub`` prefix is theirs, and marks the endpoints served without a bearer token.
Three of them matter:

    POST /mfmp/pub/search/bids          paged advertisement list
    POST /mfmp/pub/search/bids/count    total for the same filter
    GET  /mfmp/pub/search/bids/detail   one advertisement, with attachments

Three behaviours drive the shape of this adapter:

* **The search body is all-or-nothing.** Omit any key and the request 500s and
  falls through to the SPA's HTML catch-all, so we always post the full filter.
* **There is no paging.** ``pageNumber`` is accepted and ignored — pages 0, 1, 2
  and 3 all return an identical first page — and ``pageSize`` is capped at 100
  server-side however large a number you send. A caller that trusts the paging
  contract silently truncates at 100 and reports the rest as closed. So we page
  by *slicing the filter* instead: one query per advertisement type, which sums
  exactly to the unsliced total, and an automatic sub-slice by posting
  organization if any single type ever reaches the cap.
* **Rate limiting is silent.** Too many requests too fast returns HTTP 200 with
  ``index.html`` instead of JSON. A naive client reads that as "no bids today"
  and quietly reports an empty state. We detect the HTML and raise, and we pace
  requests well under the threshold that triggers it.

The legacy Vendor Bid System at myflorida.com/apps/vbs is retired and 404s;
nothing should be pointed at it.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..fl_geo import infer_county
from ..http_util import SourceBlocked, session
from ..models.opportunity import Document, Opportunity, SolicitationType
from .base import SourceAdapter

BASE = "https://vendor.myfloridamarketplace.com"
SEARCH = f"{BASE}/mfmp/pub/search/bids"
COUNT = f"{BASE}/mfmp/pub/search/bids/count"
DETAIL = f"{BASE}/mfmp/pub/search/bids/detail"
ORGS = f"{BASE}/mfmp/pub/search/picklistOrg"
ATTACHMENT = f"{BASE}/mfmp/bids/detail/attachment/download"

#: The server's hard ceiling. Sending more is accepted and silently ignored,
#: so we treat a response of exactly this length as "there is more behind this
#: filter" and slice further rather than assuming we saw everything.
PAGE_SIZE = 100
#: Seconds between calls. The limiter trips on rapid bursts and stays tripped
#: for ~45s, so paying a couple of seconds a call is far cheaper than
#: recovering from a block mid-run.
PACE_SECONDS = 2.0

#: Advertisement types that are genuinely biddable work. The portal also
#: carries award notices, meeting notices and informational postings, which
#: would otherwise flood the board with items nobody can respond to.
BIDDABLE_TYPES = {
    "4",  # Invitation to Bid
    "5",  # Invitation to Negotiate
    "6",  # Request for Proposals
    "8",  # Request for Information
    "9",  # Request for Statement of Qualifications
    "2",  # Grant Opportunities
}

#: Kept out of the default pull but useful context: 1 Agency Decision,
#: 3 Informational Notice, 7 Public Meeting Notice, 10 Single Source.
NOTICE_TYPES = {"1", "3", "7", "10"}

_TYPE_NAMES = {
    "1": "Agency Decision", "2": "Grant Opportunities", "3": "Informational Notice",
    "4": "Invitation to Bid", "5": "Invitation to Negotiate", "6": "Request for Proposals",
    "7": "Public Meeting Notice", "8": "Request for Information",
    "9": "Request for Statement of Qualifications", "10": "Single Source",
}

#: The portal states the solicitation type outright, so there is no reason to
#: guess it from the title the way an HTML scrape has to. Types with no
#: equivalent in our enum (grants, single source) stay OTHER rather than being
#: forced into a bid category they are not.
_TYPE_TO_SOLICITATION = {
    "2": SolicitationType.OTHER,
    "4": SolicitationType.ITB,
    "5": SolicitationType.ITN,
    "6": SolicitationType.RFP,
    "8": SolicitationType.RFI,
    "9": SolicitationType.RFQ,
    "10": SolicitationType.OTHER,
}


def _empty_filter() -> Dict[str, Any]:
    """The full filter body. Every key must be present or the endpoint 500s."""
    return {
        "pageSize": PAGE_SIZE,
        "pageNumber": 1,
        "type": [],
        "status": ["OPEN"],
        "agency": [],
        "adNumber": "",
        "agencyAdvertisementNumber": "",
        "title": "",
        "publishedDate": "",
        "openDate": "",
        "endDate": "",
        "commodityCodes": [],
    }


class MfmpVbsAdapter(SourceAdapter):
    """All Florida state-level advertisements from the VIP public API.

    Config keys (all optional):

    ``include_notices``
        Also pull award/meeting/informational postings. Off by default.
    ``agency_ids``
        Restrict to specific posting organizations, e.g. ``["30000021"]`` for
        FDOT. Omit for everything.
    ``status``
        ``OPEN`` (default) or ``CLOSED``. Closed carries ~12,800 rows of
        history, useful for a one-time backfill but not for a routine run.
    """

    supports_detail = True
    #: The state always has something open; zero rows means the parse or the
    #: rate limiter broke, and should be reported as a fault rather than calm.
    allows_empty = False

    #: Verified by bisecting the header set against a live attachment: this
    #: Accept alone is the difference between 1.9 MB of PDF and 1.1 KB of
    #: `index.html`. The portal content-negotiates on Accept, and the shared
    #: session's default prefers `text/html`, so every document download
    #: silently produced the SPA shell — which `fetch_text` correctly rejects
    #: for not starting with %PDF, and then reports as simply having no
    #: documents. That is what made deep dives on state bids listing-only.
    document_headers = {"Accept": "application/json, text/plain, */*"}

    def __init__(self, cfg):
        super().__init__(cfg)
        # Both are shared by every thread in the detail pass, so they are
        # created once here rather than lazily via getattr — a lazily-built
        # lock is itself a race.
        self._pace_lock = threading.Lock()
        self._last_call = 0.0
        self._session_lock = threading.Lock()
        self._s = None

    def fetch(self) -> List[Opportunity]:
        s = self._session()
        base = _empty_filter()
        base["status"] = [str(self.cfg.get("status") or "OPEN").upper()]

        if self.cfg.get("agency_ids"):
            orgs = {o["id"]: o["value"] for o in self._orgs(s)}
            base["agency"] = [
                {"id": str(i), "value": orgs.get(str(i), str(i))}
                for i in self.cfg["agency_ids"]
            ]

        wanted = set(BIDDABLE_TYPES)
        if self.cfg.get("include_notices"):
            wanted |= NOTICE_TYPES

        expected = self._count(s, base)

        rows: Dict[int, Dict[str, Any]] = {}
        for type_id in sorted(wanted):
            for row in self._rows_for_type(s, base, type_id):
                ad_id = row.get("advertisementId")
                if ad_id is not None:
                    rows[ad_id] = row

        out: List[Opportunity] = []
        for row in rows.values():
            opp = self._to_opportunity(row)
            if opp:
                out.append(opp)

        # `expected` counts every advertisement type; we deliberately keep only
        # the biddable ones, so it is an upper bound, not a target. It still
        # catches the failure that matters: a slice silently returning nothing.
        skipped = (NOTICE_TYPES - wanted) or set()
        if expected and not rows and not skipped:
            self.degraded_reason = (
                f"VIP reported {expected} open advertisements but none were "
                "retrieved — the public API is likely rate limiting."
            )
        return out

    def _rows_for_type(
        self, s, base: Dict[str, Any], type_id: str
    ) -> List[Dict[str, Any]]:
        """Every advertisement of one type, sub-sliced by agency if capped.

        A slice that comes back exactly PAGE_SIZE long has almost certainly
        been truncated, since there is no second page to ask for. When that
        happens we re-run the slice once per posting organization, which is
        slow but correct — and in practice never triggers, because the busiest
        type runs well under the cap.
        """
        body = dict(base, type=[{"id": type_id, "value": _TYPE_NAMES.get(type_id, "")}])
        try:
            rows = self._post(s, SEARCH, body)
        except SourceBlocked:
            raise
        except Exception:  # noqa: BLE001 — one bad slice must not lose the rest
            self.degraded_reason = f"advertisement type {type_id} could not be read"
            return []

        if not isinstance(rows, list):
            return []
        if len(rows) < PAGE_SIZE:
            return rows

        collected: Dict[int, Dict[str, Any]] = {
            r["advertisementId"]: r
            for r in rows
            if r.get("advertisementId") is not None
        }
        for org in self._orgs(s):
            sub = dict(body, agency=[{"id": org["id"], "value": org["value"]}])
            try:
                more = self._post(s, SEARCH, sub)
            except Exception:  # noqa: BLE001
                continue
            for r in more if isinstance(more, list) else []:
                if r.get("advertisementId") is not None:
                    collected[r["advertisementId"]] = r
        return list(collected.values())

    # -- detail ------------------------------------------------------------

    def fetch_detail(self, opp: Opportunity) -> None:
        ad_id = (opp.raw or {}).get("advertisementId")
        if not ad_id:
            return
        try:
            data = self._get(self._session(), f"{DETAIL}?id={ad_id}")
        except Exception:  # noqa: BLE001 — a failed detail must not lose the listing
            return
        if not isinstance(data, dict):
            return

        scope = _strip_html(data.get("description") or data.get("adDescription") or "")
        if scope:
            opp.scope = scope
            if not opp.description:
                opp.description = scope[:600]

        docs: List[Document] = []
        for att in data.get("docs") or data.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            name = att.get("fileName") or att.get("name") or "Attachment"
            att_id = att.get("attachmentId") or att.get("id")
            if not att_id:
                continue
            kind = "addendum" if "addend" in str(name).lower() else "document"
            docs.append(
                Document(
                    name=str(name),
                    url=f"{ATTACHMENT}?attachmentId={att_id}",
                    kind=kind,
                )
            )
        if docs:
            opp.documents = docs

        for key in ("contactName", "contactEmail", "contactPhone"):
            val = data.get(key)
            if not val:
                continue
            if key == "contactEmail":
                opp.contact_email = str(val)
            elif key == "contactPhone":
                opp.contact_phone = str(val)
            else:
                opp.contact = str(val)

        opp.detail_fetched = True

    # -- mapping -----------------------------------------------------------

    def _to_opportunity(self, row: Dict[str, Any]) -> Optional[Opportunity]:
        title = (row.get("title") or "").strip()
        if not title:
            return None

        org = row.get("organization") or {}
        agency = (
            row.get("agency")
            or org.get("name")
            or org.get("shortName")
            or "State of Florida"
        )
        ad_id = row.get("advertisementId")
        ref = (row.get("agencyAdNumber") or row.get("uniqueName") or "").strip() or None

        fields = enrich(title, external_id=ref)
        type_id = str(row.get("typeId") or "")
        type_name = row.get("type") or _TYPE_NAMES.get(type_id, "")

        # Everything posted here is a state-level advertisement, so an agency
        # name our matcher cannot place is statewide rather than unknown —
        # but a real county that *did* match (St. Johns, Alachua) keeps it.
        county = infer_county(agency)
        if county == "unknown":
            county = "statewide"

        # Prefer the type the portal states over the one inferred from wording.
        sol_type = _TYPE_TO_SOLICITATION.get(type_id) or fields["solicitation_type"]

        return Opportunity(
            source_id=self.source_id,
            source_name=self.name,
            county=county,
            agency=agency,
            external_id=fields["external_id"] or ref,
            title=title,
            url=f"{BASE}/search/bids/detail?id={ad_id}",
            department=org.get("shortName") or None,
            solicitation_type=sol_type,
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            posted_date=(parse_dt(row.get("publishDate")) or _none()).date()
            if row.get("publishDate")
            else None,
            due_date=parse_dt(row.get("closeDate")),
            status="open" if str(row.get("status")).upper() == "OPEN" else "closed",
            description=type_name or None,
            raw={"advertisementId": ad_id, "typeId": row.get("typeId"), "vbs": row},
        )

    # -- transport ---------------------------------------------------------

    def _session(self):
        # Also guarded: the detail pass calls this from every worker, and two
        # threads each building their own session would quietly double the
        # request rate the pacing above exists to hold down.
        with self._session_lock:
            if self._s is not None:
                return self._s
            s = session()
            s.headers.update(
                {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "Origin": BASE,
                    "Referer": f"{BASE}/search/bids",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-origin",
                }
            )
            self._s = s
        return s

    def _orgs(self, s) -> List[Dict[str, str]]:
        data = self._get(s, ORGS)
        return data if isinstance(data, list) else []

    def _count(self, s, body: Dict[str, Any]) -> int:
        try:
            payload = dict(body, pageNumber=1)
            raw = self._post(s, COUNT, payload, expect_json=False)
            return int(str(raw).strip())
        except Exception:  # noqa: BLE001 — the count is advisory, not required
            return 0

    def _post(self, s, url: str, body: Dict[str, Any], *, expect_json: bool = True):
        self._pace()
        resp = s.post(url, json=body, timeout=45)
        return self._decode(resp, url, expect_json)

    def _get(self, s, url: str):
        self._pace()
        resp = s.get(url, timeout=45)
        return self._decode(resp, url, True)

    def _decode(self, resp, url: str, expect_json: bool):
        if resp.status_code in (401, 403):
            raise SourceBlocked(f"{resp.status_code} from VIP: {url}")
        resp.raise_for_status()

        text = resp.text or ""
        # The tell for a rate-limited response: HTTP 200 carrying the SPA shell.
        if text.lstrip()[:14].lower().startswith("<!doctype html") or "<html" in text[:200].lower():
            raise SourceBlocked(
                "MyFloridaMarketPlace returned its HTML shell instead of JSON — "
                "the public API rate limiter is tripped. Back off and retry."
            )
        if not expect_json:
            return text
        return resp.json()

    def _pace(self) -> None:
        """Serialize calls at PACE_SECONDS apart, across threads.

        The lock is not decoration. The detail pass runs a thread pool against
        one adapter instance, so an unlocked read-modify-write on the last-call
        timestamp lets every worker read the same value, agree it has waited
        long enough, and fire together — a burst is exactly what trips the VIP
        limiter. The limiter answers 200 with HTML, `_decode` raises
        SourceBlocked, `fetch_detail` swallows it, and the bid silently keeps
        zero documents. Holding the lock across the sleep is the point: it
        makes the pacing real rather than advisory.
        """
        with self._pace_lock:
            wait = PACE_SECONDS - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    from bs4 import BeautifulSoup

    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def _none():
    from datetime import datetime

    return datetime.utcnow()
