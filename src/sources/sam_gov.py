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
from ..models.opportunity import Opportunity
from .base import SourceAdapter

ENV_KEYS = ("SF_SCOUT_SAM_KEY", "SAM_API_KEY")

API_URL = "https://api.sam.gov/opportunities/v2/search"

# o = Solicitation, k = Combined Synopsis/Solicitation, p = Pre-solicitation.
PTYPES = "o,k,p"
LOOKBACK_DAYS = 90
PAGE_SIZE = 200
MAX_ROWS = 600


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

        out: List[Opportunity] = []
        while len(out) < MAX_ROWS:
            data = get_json(API_URL, params=params)
            rows = data.get("opportunitiesData") or []
            for raw in rows:
                opp = self._to_opportunity(raw)
                if opp is not None:
                    out.append(opp)
            total = int(data.get("totalRecords") or 0)
            params["offset"] += PAGE_SIZE
            if params["offset"] >= total or not rows:
                break
        return out

    def _to_opportunity(self, raw: dict) -> Optional[Opportunity]:
        title = (raw.get("title") or "").strip()
        if not title:
            return None
        if raw.get("active") in ("No", "no", False):
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

        return Opportunity(
            **self._base_kwargs(),
            title=title,
            url=url,
            department=office or None,
            posted_date=posted.date() if posted else None,
            due_date=due,
            status="open",
            description=description,
            contact_email=email,
            project_location=f"{city}, FL" if city else None,
            raw={"noticeId": raw.get("noticeId"),
                 "naicsCode": raw.get("naicsCode"),
                 "setAside": set_aside or None},
            **fields,
        )
