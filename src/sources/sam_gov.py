"""Federal opportunities from SAM.gov's public Get Opportunities API.

Official API (https://open.gsa.gov/api/get-opportunities-public-api/):
``GET https://api.sam.gov/opportunities/v2/search`` with a free api.data.gov
key. Inert until ``SF_SCOUT_SAM_KEY`` (or ``SAM_API_KEY``) is set — reported
as ``empty`` with a how-to note, never as an error, matching the email-alerts
pattern.

The query is scoped to active solicitations with a Florida place of
performance, posted in the last ~90 days — the slice a South Florida
contractor can actually bid.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get_json
from ..models.opportunity import Document, Opportunity
from .base import SourceAdapter

ENV_KEYS = ("SF_SCOUT_SAM_KEY", "SAM_API_KEY")

API_URL = "https://api.sam.gov/opportunities/v2/search"

# o = Solicitation, k = Combined Synopsis/Solicitation, p = Pre-solicitation.
PTYPES = "o,k,p"
#: a = Award Notice — fetched separately so each carries its structured
#: `award {amount, date, awardee}` object, the cleanest award feed anywhere
#: in this build.
AWARD_PTYPE = "a"
LOOKBACK_DAYS = 90
PAGE_SIZE = 200
MAX_ROWS = 600
MAX_AWARD_ROWS = 300


def api_key() -> Optional[str]:
    for env in ENV_KEYS:
        value = os.environ.get(env)
        if value:
            return value.strip()
    return None


class SamGovAdapter(SourceAdapter):
    allows_empty = True

    def fetch(self) -> List[Opportunity]:
        key = api_key()
        if not key:
            self.empty_note = "inactive — set SF_SCOUT_SAM_KEY (free at sam.gov) to pull federal bids"
            return []

        today = datetime.utcnow().date()
        params = {
            "api_key": key,
            "postedFrom": (today - timedelta(days=LOOKBACK_DAYS)).strftime("%m/%d/%Y"),
            "postedTo": today.strftime("%m/%d/%Y"),
            "ptype": PTYPES,
            "state": self.cfg.get("pop_state", "FL"),
            "limit": PAGE_SIZE,
            "offset": 0,
        }

        out = self._page(params, MAX_ROWS, status="open")
        # Award notices ride the same query with ptype=a; each carries a
        # structured award object — vendor, dollar amount, date.
        award_params = dict(params, ptype=AWARD_PTYPE, offset=0)
        out += self._page(award_params, MAX_AWARD_ROWS, status="award")
        return out

    def _page(self, params: dict, cap: int, *, status: str) -> List[Opportunity]:
        out: List[Opportunity] = []
        params = dict(params)
        while len(out) < cap:
            data = get_json(API_URL, params=params)
            rows = data.get("opportunitiesData") or []
            for raw in rows:
                opp = self._to_opportunity(raw, status=status)
                if opp is not None:
                    out.append(opp)
            total = int(data.get("totalRecords") or 0)
            params["offset"] += PAGE_SIZE
            if params["offset"] >= total or not rows:
                break
        return out

    def _to_opportunity(self, raw: dict, *, status: str = "open") -> Optional[Opportunity]:
        title = (raw.get("title") or "").strip()
        if not title:
            return None
        if status == "open" and raw.get("active") in ("No", "no", False):
            return None

        url = raw.get("uiLink") or self.portal_url
        agency_path = raw.get("fullParentPathName") or ""
        # "DEPT OF DEFENSE.DEPT OF THE ARMY.…" — the leaf office reads best.
        office = agency_path.split(".")[-1].strip().title() if agency_path else ""

        due = parse_dt(raw.get("responseDeadLine") or "")
        posted = parse_dt(raw.get("postedDate") or "")

        pop = raw.get("placeOfPerformance") or {}
        city = ((pop.get("city") or {}).get("name") or "").title() if isinstance(pop, dict) else ""

        description = raw.get("description") or ""
        if not isinstance(description, str) or description.startswith("http"):
            # v2 returns a description *link*; keep the meta line readable instead.
            description = ""
        set_aside = raw.get("typeOfSetAsideDescription") or ""
        bits = [b for b in (
            f"Federal {raw.get('type') or 'solicitation'}",
            office,
            f"Place of performance: {city}, FL" if city else "Place of performance: FL",
            f"Set-aside: {set_aside}" if set_aside else "",
        ) if b]
        description = description or " · ".join(bits)

        fields = enrich(title, description, raw.get("solicitationNumber"))
        contacts = raw.get("pointOfContact") or []
        email = next((c.get("email") for c in contacts
                      if isinstance(c, dict) and c.get("email")), None)
        name = next((c.get("fullName") for c in contacts
                     if isinstance(c, dict) and c.get("fullName")), None)
        phone = next((c.get("phone") for c in contacts
                      if isinstance(c, dict) and c.get("phone")), None)

        # NAICS is the classifier a federal bidder searches by; PSC rides along.
        codes: List[str] = []
        naics = raw.get("naicsCode")
        for code in naics if isinstance(naics, list) else ([naics] if naics else []):
            codes.append(f"NAICS {code}")
        if raw.get("classificationCode"):
            codes.append(f"PSC {raw['classificationCode']}")

        # The attachment links v2 publishes; without them federal bids showed
        # no documents at all.
        docs = [
            Document(name=f"Attachment {i}", url=link, kind="document")
            for i, link in enumerate(raw.get("resourceLinks") or [], start=1)
            if isinstance(link, str) and link.startswith("http")
        ]

        awarded_vendor = award_amount = award_date = None
        if status == "award":
            award = raw.get("award") or {}
            if isinstance(award, dict):
                awardee = award.get("awardee") or {}
                awarded_vendor = str(awardee.get("name") or "").strip() or None
                award_amount = _dollars(award.get("amount"))
                parsed = parse_dt(str(award.get("date") or ""))
                award_date = parsed.date() if parsed else None

        return Opportunity(
            **self._base_kwargs(),
            title=title,
            url=url,
            department=office or None,
            posted_date=posted.date() if posted else None,
            due_date=due,
            status=status,
            description=description,
            contact=name,
            contact_email=email,
            contact_phone=phone,
            commodity_codes=codes,
            raw_category=set_aside or None,
            documents=docs,
            awarded_vendor=awarded_vendor,
            award_amount=award_amount,
            award_date=award_date,
            linked_ref=(raw.get("solicitationNumber") or None) if status == "award" else None,
            award_linkage="ref" if status == "award" and raw.get("solicitationNumber") else None,
            project_location=f"{city}, FL" if city else None,
            raw={"noticeId": raw.get("noticeId"),
                 "naicsCode": raw.get("naicsCode"),
                 "setAside": set_aside or None},
            **fields,
        )


def _dollars(value) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(round(float(str(value).replace(",", "").replace("$", ""))))
    except (ValueError, TypeError):
        return None
