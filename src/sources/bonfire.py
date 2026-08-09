"""Bonfire / Euna public portal adapter (Broward BPRO, Town of Palm Beach, etc.).

The portal is a JSON API in all but name. Alongside the open-opportunities
endpoint it publishes a *past* one — several hundred closed solicitations per
agency — which is how the app knows a contract's re-bid cadence rather than
only what happens to be open today.

A third endpoint, `getMyOpportunitiesSectionData`, returns solicitations this
account has been invited to or is following — but only to a signed-in session.
When a vendor session cookie is configured (see `src/auth.py`), it is merged
into the open list and tagged `personalized`, rather than requiring a second,
separate source per agency.
"""

from __future__ import annotations

from datetime import timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ..auth import bonfire_cookie
from ..classify import enrich
from ..contracts import Contract, index_vendors, parse_date
from ..dates import parse_dt
from ..http_util import get, get_json, session
from ..models.opportunity import Opportunity
from .base import SourceAdapter

_NEW_YORK = ZoneInfo("America/New_York")

OPEN_ENDPOINT = "getOpenPublicOpportunitiesSectionData"
PAST_ENDPOINT = "getPastPublicOpportunitiesSectionData"
MY_ENDPOINT = "getMyOpportunitiesSectionData"
#: Executed contracts with vendor names and end dates — free, unauthenticated,
#: and the only source of local incumbent data in the system. Seven of twelve
#: Florida tenants sampled publish it.
CONTRACTS_ENDPOINT = "getPublicContractsSectionData"


class BonfireAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        payload = self._payload(OPEN_ENDPOINT)
        opps = self._from_payload(payload, status="open")
        self._merge_personalized(opps)
        return opps

    def fetch_history(self) -> List[Opportunity]:
        """Closed solicitations this agency has run before.

        Returned separately from `fetch` — these are not live opportunities and
        must never appear in the pipeline as if they were. They exist to tell
        you that the county has bid janitorial three times and when the last
        cycle closed.
        """
        payload = self._payload(PAST_ENDPOINT)
        return self._from_payload(payload, status="closed")

    def fetch_contracts(self) -> List[Contract]:
        """Executed contracts this agency has published.

        Not solicitations, so deliberately not Opportunities: a contract is
        something already awarded, and its value here is the end date. A
        tenant that does not publish contracts answers `success: 0`, which is
        an absence rather than a fault — five of the twelve sampled do that.
        """
        try:
            payload = self._payload(CONTRACTS_ENDPOINT)
        except RuntimeError:
            return []

        raw = payload.get("publicContracts") or {}
        # Keyed by ContractID, exactly like `projects` on the other endpoint.
        rows = list(raw.values()) if isinstance(raw, dict) else raw
        vendors = index_vendors(payload.get("vendors"))
        host = self._host()

        out: List[Contract] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("Name") or "").strip()
            cid = str(row.get("ContractID") or "").strip()
            if not name or not cid:
                continue
            vid = str(row.get("VendorID") or "").strip() or None
            out.append(
                Contract(
                    contract_id=cid,
                    agency=self.agency,
                    name=name,
                    source_id=self.source_id,
                    vendor=vendors.get(vid or ""),
                    vendor_id=vid,
                    status_id=str(row.get("ContractStatusID") or "") or None,
                    start_date=parse_date(row.get("StartDate")),
                    end_date=parse_date(row.get("EndDate")),
                    url=f"https://{host}/portal/",
                    extendable=_as_bool(row.get("IsExtendable")),
                )
            )
        return out

    # -- internals ---------------------------------------------------------

    def _host(self) -> str:
        host = self.cfg.get("bonfire_host")
        if not host:
            raise ValueError(f"{self.source_id}: bonfire_host required")
        return str(host)

    def _payload(self, endpoint: str, *, cookie: Optional[str] = None) -> Dict[str, Any]:
        host = self._host()
        s = session()
        headers = {}
        if cookie:
            # A real vendor session is presented as-is; skipping the anonymous
            # warm-up matters here, since populating the cookiejar first would
            # give requests two competing sources for the Cookie header.
            headers["Cookie"] = cookie
        else:
            get(f"https://{host}/portal/", s=s)
        data = get_json(
            f"https://{host}/PublicPortal/{endpoint}",
            s=s,
            referer=f"https://{host}/portal/",
            headers=headers or None,
        )
        if not data.get("success"):
            raise RuntimeError(f"Bonfire API error: {data}")
        return data.get("payload") or {}

    def _merge_personalized(self, opps: List[Opportunity]) -> None:
        """Fold in invited/followed opportunities when a session is configured.

        Best-effort: an expired or absent cookie must not disturb the public
        listing that already succeeded.
        """
        cookie = bonfire_cookie(self._host())
        if not cookie:
            return
        try:
            payload = self._payload(MY_ENDPOINT, cookie=cookie)
            mine = self._from_payload(payload, status="open")
        except Exception:  # noqa: BLE001 — a stale session is not a fetch failure
            return

        by_url = {o.url: o for o in opps}
        for o in mine:
            existing = by_url.get(o.url)
            target = existing or o
            target.personalized = True
            if "invited" not in target.categories:
                target.categories = ["invited"] + target.categories
            if existing is None:
                opps.append(o)
                by_url[o.url] = o

    def _from_payload(self, payload: Dict[str, Any], *, status: str) -> List[Opportunity]:
        projects = payload.get("projects") or {}
        departments = payload.get("departments") or {}
        host = self._host()

        out: List[Opportunity] = []
        for _pid, p in projects.items():
            opp = self._from_project(p, departments, host, status)
            if opp:
                out.append(opp)
        return out

    def _from_project(
        self,
        p: Dict[str, Any],
        departments: Any,
        host: str,
        status: str,
    ) -> Optional[Opportunity]:
        title = (p.get("ProjectName") or "").strip()
        if not title:
            return None
        ref = (p.get("ReferenceID") or "").strip() or None
        project_id = str(p.get("ProjectID") or "")
        url = f"https://{host}/opportunities/{project_id}" if project_id else self.portal_url

        # Past rows say how they ended: SubStatus 3 (with IsPublicAward) is an
        # award, SubStatus 2 a cancellation. Flattening both to "closed" hid
        # every award this platform publishes — 224 of Broward's 708 archive
        # rows on the day this was verified.
        if status == "closed":
            sub = str(p.get("ProjectSubStatusID") or "")
            if p.get("IsPublicAward") or sub == "3":
                status = "award"
            elif sub == "2":
                status = "cancelled"

        fields = enrich(title, external_id=ref)
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            url=url,
            department=_department_name(departments, p.get("DepartmentID")),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            due_date=_close_dt(p.get("DateClose")),
            status=status,
            raw={"project": p},
        )


def _as_bool(value: Any):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def _close_dt(value: Any):
    """Bonfire's DateClose is naive **UTC**, not Eastern.

    The portal's own JS parses it as UTC and renders in America/New_York
    (verified live: "2026-08-10 18:00:00" displays as 2:00 PM EDT). `parse_dt`
    treats a bare string as Eastern wall clock, which put every Bonfire
    deadline 4-5 hours late. Converted here with the real zone, DST included,
    then returned naive like every other adapter's dates.
    """
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(_NEW_YORK).replace(tzinfo=None)


def _department_name(departments: Any, dept_id: Any) -> Optional[str]:
    key = str(dept_id or "")
    if not key or not isinstance(departments, dict):
        return None
    d = departments.get(key)
    if d is None and key.isdigit():
        d = departments.get(int(key))
    return d.get("DepartmentName") if isinstance(d, dict) else None
