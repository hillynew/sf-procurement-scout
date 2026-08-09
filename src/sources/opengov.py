"""OpenGov Procurement — 91 Florida agencies from one adapter, anonymously.

This portal was written off twice: `docs/statewide-coverage.md` files it under
"free but needs a vendor account", and its phase plan says it needs a headless
browser to get past Cloudflare. Both are true of the wrong host.

`procurement.opengov.com/portal/*` is the Cloudflare-challenged SPA and does
return 403 to a non-browser. The API it calls, `api.procurement.opengov.com`,
sits in front of no challenge at all: no auth, no cookie, no bot check. Scrape
the API host and the whole platform opens up — Orange County, Escambia, Tampa,
Pinellas, Sarasota, Volusia, St. Petersburg, Collier, Orlando, GOAA, JAXPORT,
JTA and several school districts, ~14k projects between them.

Four endpoints matter:

    GET  /api/v1/government                          561 tenants, 93 in Florida
    POST /api/v1/government/{code}/project/public    that tenant's projects
    GET  /api/v1/project/{id}                        ~147 fields, incl. documents
    GET  /api/v1/project/{id}/addendums              amendment history

Three behaviours drive the shape of this adapter:

* **The project list is a POST.** A GET of the same path 404s, which reads as
  "this tenant has no public portal" and is how the platform gets written off.
* **`Origin` is required.** Without the browser `Origin` header the API host
  refuses the cross-origin call, so it is set on the session, not per request.
* **Document URLs are pre-signed and short-lived.** The detail payload hands
  back an S3 URL carrying `X-Amz-Expires=72000` — twenty hours from the moment
  it was minted, not from when it is read. So the URL is a fetch-now token, not
  an address: it is recorded for the same run's package pass and must never be
  persisted and followed the next day.

There is no anonymous cross-tenant search (`/project/search` 401s without a
government code), so coverage is one configured source per tenant. The tenant
list is discovered rather than hand-written — see `fl_tenants` and
`scripts/discover_opengov_tenants.py`.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import CRAWLER_UA, SourceBlocked, session
from ..netpolicy import check, log_fetch
from ..models.opportunity import Document, Opportunity
from .base import SourceAdapter

API = "https://api.procurement.opengov.com/api/v1"
PORTAL = "https://procurement.opengov.com"

#: The API caps a page well below this, but asking for 100 keeps the number of
#: round trips per tenant to single digits even for Escambia's 1,200 projects.
PAGE_SIZE = 100

#: A tenant with more pages than this is a bug in our paging, not a real corpus
#: — stop rather than walking forever.
MAX_PAGES = 60

#: Statuses the platform reports. Only `open` is still biddable; the rest have
#: closed for submissions and belong in history, not in the live pipeline.
OPEN_STATUSES = frozenset({"open"})

# Pacing lives in `src.netpolicy`, keyed by host rather than by adapter
# instance. Ninety-one tenants share one API host and the runner fetches
# sources concurrently, so an interval kept on the instance would let a dozen
# workers hit that host a dozen times a second while each felt polite.


class OpenGovAdapter(SourceAdapter):
    """One OpenGov tenant. `opengov_code` is the portal slug, e.g. `alachuacounty`."""

    supports_detail = True

    #: The pre-signed S3 links are plain object URLs; sending the portal's XHR
    #: headers to AWS gets the request signed differently and rejected.
    document_headers: Dict[str, str] = {"Accept": "*/*"}

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None
        self._session_lock = threading.Lock()

    def fetch(self) -> List[Opportunity]:
        return self._collect(open_only=True)

    def fetch_history(self) -> List[Opportunity]:
        """Everything this tenant has already closed.

        Kept out of `fetch` deliberately: an evaluation-stage or awarded project
        is not something anyone can bid, and the recurrence analysis in
        `src/pipeline/history.py` wants exactly this archive.
        """
        return self._collect(open_only=False)

    # -- listing -----------------------------------------------------------

    def _code(self) -> str:
        code = self.cfg.get("opengov_code")
        if not code:
            raise ValueError(f"{self.source_id}: opengov_code required")
        return str(code)

    def _collect(self, *, open_only: bool) -> List[Opportunity]:
        code = self._code()
        rows = self._rows(code)

        out: List[Opportunity] = []
        for row in rows:
            status = str(row.get("status") or "").strip()
            is_open = status in OPEN_STATUSES
            if open_only != is_open:
                continue
            opp = self._from_row(row, code, is_open=is_open)
            if opp:
                out.append(opp)
        return out

    def _rows(self, code: str) -> List[Dict[str, Any]]:
        """Page the public project list, keyed by id so a shifting sort cannot dupe.

        The list is sorted by release date descending, so a project published
        mid-crawl shifts every later row one place along and a page boundary can
        hand back a row we already have. Collecting into a dict by id makes that
        harmless.
        """
        collected: Dict[Any, Dict[str, Any]] = {}
        expected: Optional[int] = None

        for page in range(MAX_PAGES):
            body = {
                "limit": PAGE_SIZE,
                "page": page,
                "sortField": "releaseProjectDate",
                "sortDirection": "DESC",
            }
            data = self._post(f"{API}/government/{code}/project/public", body)
            if not isinstance(data, dict):
                break
            if expected is None and isinstance(data.get("count"), int):
                expected = data["count"]

            rows = data.get("rows") or []
            if not rows:
                break
            for row in rows:
                if isinstance(row, dict) and row.get("id") is not None:
                    collected[row["id"]] = row

            if len(rows) < PAGE_SIZE:
                break
            if expected is not None and len(collected) >= expected:
                break

        return list(collected.values())

    def _from_row(
        self, row: Dict[str, Any], code: str, *, is_open: bool
    ) -> Optional[Opportunity]:
        title = str(row.get("title") or "").strip()
        if not title:
            return None

        ref = str(row.get("financialId") or "").strip() or None
        project_id = row.get("id")
        fields = enrich(title, external_id=ref)

        summary = _text(row.get("summary"))
        status, award_date = _ended_status(row) if not is_open else ("open", None)
        # Everything except the two bulky, row-identical objects is kept, so a
        # field this mapping missed can still be recovered from `raw` later.
        raw = {k: v for k, v in row.items() if k not in ("government", "summary")}
        raw["project_id"] = project_id
        raw["opengov_status"] = row.get("status")
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            url=f"{PORTAL}/portal/{code}/projects/{project_id}",
            department=_department(row.get("department")),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            posted_date=_as_date(row.get("releaseProjectDate")),
            due_date=parse_dt(row.get("proposalDeadline")),
            status=status,
            award_date=award_date,
            description=summary[:600] or None,
            raw=raw,
        )

    # -- detail ------------------------------------------------------------

    def fetch_detail(self, opp: Opportunity) -> None:
        project_id = (opp.raw or {}).get("project_id")
        if not project_id:
            return
        try:
            data = self._get(f"{API}/project/{project_id}")
        except Exception:  # noqa: BLE001 — a failed detail must not lose the listing
            return
        if not isinstance(data, dict):
            return

        scope = _text(data.get("summary")) or _text(data.get("description"))
        if scope:
            opp.scope = scope
            if not opp.description or len(scope) > len(opp.description):
                opp.description = scope[:600]

        opp.department = _department(data.get("department")) or opp.department
        contact = _contact(data)
        if contact:
            opp.contact = contact
        email = str(data.get("contactEmail") or data.get("procurementContactEmail") or "").strip()
        if email and not opp.contact_email:
            opp.contact_email = email
        phone = str(
            data.get("contactPhoneComplete") or data.get("procurementContactPhoneComplete") or ""
        ).strip()
        if phone and not opp.contact_phone:
            opp.contact_phone = phone

        # The question deadline is `qaDeadline`; `questionDeadline` is kept as
        # a fallback only — reading it alone meant questions_due was never set.
        qa = data.get("qaDeadline") or data.get("questionDeadline")
        if qa and opp.questions_due is None:
            opp.questions_due = parse_dt(qa)

        if not opp.pre_bid_meeting:
            opp.pre_bid_meeting = _pre_bid(data)

        # The portal's own classification: NIGP class-item codes.
        codes = [
            f"NIGP {c.get('code')} {c.get('title') or ''}".strip()
            for c in (data.get("categories") or [])
            if isinstance(c, dict) and c.get("code")
        ]
        if codes:
            opp.commodity_codes = codes
            opp.raw_category = "; ".join(
                str(c.get("title") or c.get("code")) for c in data["categories"] if isinstance(c, dict)
            )

        if not opp.budget:
            opp.budget = _estimated_cost(data)

        docs = _documents(data)
        # The detail payload's own addendum records carry stable attachment
        # URLs; the /addendums endpoint's records carry none at all, so it is
        # only worth a request when the payload had nothing inline.
        addenda = _inline_addenda(data)
        if not addenda:
            addenda = self._addenda(project_id)
        docs += addenda
        if docs:
            opp.documents = docs
        opp.detail_fetched = True

    def _addenda(self, project_id: Any) -> List[Document]:
        """Amendment packets, which the project payload does not carry."""
        try:
            data = self._get(f"{API}/project/{project_id}/addendums")
        except Exception:  # noqa: BLE001 — addenda are a bonus, never the run
            return []

        rows = data if isinstance(data, list) else (data or {}).get("rows") or []
        out: List[Document] = []
        for i, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            for doc in _documents(row):
                doc.kind = "addendum"
                if doc.name == _DEFAULT_DOC_NAME:
                    doc.name = str(row.get("title") or f"Addendum {i}")
                out.append(doc)
        return out

    # -- transport ---------------------------------------------------------

    def _session(self):
        # The detail pass runs this adapter from several worker threads, and two
        # of them each building a session would quietly double the request rate
        # the pacing below exists to hold down.
        with self._session_lock:
            if self._s is not None:
                return self._s
            s = session()
            s.headers.update(
                {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    # Required. Without it the API host refuses the call.
                    "Origin": PORTAL,
                    "Referer": f"{PORTAL}/",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Sec-Fetch-Site": "same-site",
                }
            )
            self._s = s
        return s

    def _pace(self, url: str = f"{API}/") -> str:
        """Robots check plus the shared per-host interval; returns the log note.

        This adapter posts through its own session rather than `http_util.get`,
        so it has to reach the policy layer explicitly — otherwise 91 tenants
        would share one host with no limiter between them, and none of their
        requests would reach the fetch log.
        """
        return check(url)

    def _post(self, url: str, body: Dict[str, Any]):
        note = self._pace(url)
        resp = self._session().post(url, json=body, timeout=45)
        log_fetch(url, status=resp.status_code, robots_note=note, ua=CRAWLER_UA)
        return self._decode(resp, url)

    def _get(self, url: str):
        note = self._pace(url)
        resp = self._session().get(url, timeout=45)
        log_fetch(url, status=resp.status_code, robots_note=note, ua=CRAWLER_UA)
        return self._decode(resp, url)

    def _decode(self, resp, url: str):
        if resp.status_code in (401, 403):
            raise SourceBlocked(f"{resp.status_code} from OpenGov API: {url}")
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Tenant discovery
# ---------------------------------------------------------------------------


def fl_tenants(*, include_inactive: bool = False) -> List[Dict[str, str]]:
    """Every Florida tenant the platform admits to, from its own directory.

    The directory is public and unauthenticated, which is what makes statewide
    OpenGov coverage self-maintaining: agencies that migrate onto the platform
    appear here on their own. Re-run weekly rather than curating a list by hand.
    """
    s = session()
    s.headers.update({"Accept": "application/json, text/plain, */*", "Origin": PORTAL})
    resp = s.get(f"{API}/government", timeout=60)
    if resp.status_code in (401, 403):
        raise SourceBlocked(f"{resp.status_code} from OpenGov directory")
    resp.raise_for_status()

    rows = resp.json()
    if not isinstance(rows, list):
        return []

    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("state") != "FL":
            continue
        if not include_inactive and not row.get("isActive"):
            continue
        code = ((row.get("government") or {}) if isinstance(row.get("government"), dict) else {}).get("code")
        name = str(row.get("name") or "").strip()
        if not code or not name:
            continue
        out.append(
            {
                "code": str(code),
                "name": name,
                "city": str(row.get("city") or "").strip(),
                "website": str(row.get("website") or "").strip(),
            }
        )
    out.sort(key=lambda t: t["name"].lower())
    return out


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

_DEFAULT_DOC_NAME = "Bid package"


def _documents(payload: Dict[str, Any]) -> List[Document]:
    """Pull every downloadable file out of a project or addendum payload.

    The packet usually arrives as a single `documentAttachment` — the compiled
    project PDF — while `attachments` carries anything uploaded alongside it and
    is frequently empty. Both are read, since which one is populated varies by
    how the agency built the solicitation.
    """
    out: List[Document] = []
    seen: set[str] = set()

    def add(url: Any, name: Any, kind: str) -> None:
        if not isinstance(url, str) or not url.startswith("http"):
            return
        # Two records can point at the same object with different signatures.
        key = url.split("?", 1)[0]
        if key in seen:
            return
        seen.add(key)
        label = str(name or "").strip() or _DEFAULT_DOC_NAME
        out.append(Document(name=label, url=url, kind=kind))

    attachment = payload.get("documentAttachment")
    if isinstance(attachment, dict):
        add(attachment.get("url"), attachment.get("filename") or _DEFAULT_DOC_NAME, "document")

    for key in ("attachments", "proposalDocuments"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            nested = item.get("attachment")
            url = item.get("url") or (nested.get("url") if isinstance(nested, dict) else None)
            add(url, item.get("filename") or item.get("name") or item.get("title"), "document")
    return out


def _department(value: Any) -> Optional[str]:
    if isinstance(value, dict):
        name = str(value.get("name") or "").strip()
        return name or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _contact(data: Dict[str, Any]) -> Optional[str]:
    """Best available human.

    The live payload carries contacts as *flat* fields (`contactFullName`,
    `contactTitle`, with a `procurement*` mirror) — the nested shapes tried
    below are kept as fallbacks, but reading only them meant detail contacts
    were effectively never captured.
    """
    for prefix in ("contact", "procurementContact"):
        name = str(
            data.get(f"{prefix}FullName")
            or data.get(f"{prefix}DisplayName")
            or ""
        ).strip()
        if name:
            title = str(data.get(f"{prefix}Title") or "").strip()
            return f"{name} — {title}" if title else name
    for key in ("contact", "contactInfo", "projectContact", "owner"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = " ".join(
                str(value.get(k) or "").strip() for k in ("firstName", "lastName")
            ).strip()
            name = name or str(value.get("name") or "").strip()
            email = str(value.get("email") or "").strip()
            joined = " — ".join(p for p in (name, email) if p)
            if joined:
                return joined
    return None


#: closeOutReason is free text an agent typed: "awarded", "Contract Awarded",
#: "Project Awarded", "Complete", "Closed", "Project will be re-solicited"…
_AWARD_WORDS = ("award",)
_CANCEL_WORDS = ("cancel", "re-solicit", "resolicit", "rejected")


def _ended_status(row: Dict[str, Any]):
    """(status, award_date) for a non-open row.

    The platform's own signals: `closedSubstatus` "canceled", free-text
    `closeOutReason`, and the `awardPending` status. Collapsing all of these
    to "closed" hid every award the platform reports.
    """
    reason = str(row.get("closeOutReason") or "").lower()
    sub = str(row.get("closedSubstatus") or "").lower()
    if any(w in reason for w in _AWARD_WORDS):
        return "award", _as_date(row.get("closedAt") or row.get("solicitationClosedDate"))
    if sub in ("canceled", "cancelled") or any(w in reason for w in _CANCEL_WORDS):
        return "cancelled", None
    return "closed", None


def _pre_bid(data: Dict[str, Any]) -> Optional[str]:
    date = data.get("preProposalDate")
    if not date:
        return None
    parts = [str(parse_dt(date) or date)]
    text = str(data.get("preProposalText") or "").strip()
    if text:
        parts.append(text)
    location = str(data.get("preProposalLocation") or "").strip()
    if location:
        parts.append(location)
    return " · ".join(parts)


def _estimated_cost(data: Dict[str, Any]) -> Optional[str]:
    """Estimated value hides in template variables, when it appears at all."""
    from ..requirements import extract_estimated_value

    for q in data.get("upfrontQuestions") or []:
        if not isinstance(q, dict):
            continue
        title = str(q.get("title") or "").lower()
        if "cost" not in title and "budget" not in title and "value" not in title:
            continue
        value = str(((q.get("inputData") or {}) if isinstance(q.get("inputData"), dict) else {}).get("value") or "")
        found = extract_estimated_value(value)
        if found:
            return found
    return None


def _inline_addenda(data: Dict[str, Any]) -> List[Document]:
    out: List[Document] = []
    for i, row in enumerate(data.get("addendums") or [], start=1):
        if not isinstance(row, dict):
            continue
        for doc in _documents(row):
            doc.kind = "addendum"
            if doc.name == _DEFAULT_DOC_NAME:
                doc.name = str(row.get("titleDisplay") or row.get("title") or f"Addendum {i}")
            out.append(doc)
    return out


def _as_date(value: Any):
    parsed = parse_dt(value)
    return parsed.date() if parsed else None


def _text(html: Any) -> str:
    """Flatten the portal's rich-text HTML, which carries inline SVG icons."""
    if not html or not isinstance(html, str):
        return ""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("svg"):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())
