"""Palm Beach County School District current/future construction solicitations."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from dateutil import parser as dateparser
from bs4 import BeautifulSoup

from ..classify import enrich
from ..http_util import get
from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter


class PalmBeachSchoolsAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")
        out: List[Opportunity] = []
        register = self.cfg.get("register_url") or self.portal_url

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if not headers:
                continue
            # Current table has RFP/ITB; future has estimated publish date
            is_current = any("rfp/itb" in h or "firm proposals due" in h for h in headers)
            is_future = any("estimated publish" in h for h in headers)
            if not (is_current or is_future):
                continue

            col = {h: i for i, h in enumerate(headers)}

            def cell(cells, *keys):
                for k in keys:
                    for h, i in col.items():
                        if k in h and i < len(cells):
                            return cells[i]
                return ""

            for tr in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not any(cells):
                    continue
                # skip section header rows
                joined = " ".join(cells)
                if joined.lower().startswith("procurement type:") and len(cells) <= 2:
                    continue

                if is_current:
                    proc_type = cell(cells, "procurement type")
                    project_type = cell(cells, "project type")
                    location = cell(cells, "location")
                    budget = cell(cells, "budget", "advertised construction budget")
                    ref = cell(cells, "rfp/itb")
                    publish = cell(cells, "publish date")
                    due = cell(cells, "firm proposals due", "due")
                    title = " — ".join(
                        x for x in [proc_type, project_type, location] if x
                    ) or joined
                    status = "open"
                    due_dt = _parse_dt(due)
                    posted = _parse_dt(publish)
                else:
                    publish = cell(cells, "estimated publish")
                    proc_type = cell(cells, "procurement type")
                    project_type = cell(cells, "project type")
                    location = cell(cells, "location")
                    budget = cell(cells, "budget", "approximate construction budget")
                    ref = None
                    title = " — ".join(
                        x for x in [proc_type, project_type, location] if x
                    ) or joined
                    status = "upcoming"
                    due_dt = None
                    posted = _parse_dt(publish)

                if len(title) < 5:
                    continue

                desc = f"{project_type or ''} at {location or ''}".strip(" at")
                fields = enrich(title, desc, external_id=ref or None)
                cats = fields["categories"]
                if "construction" not in cats:
                    cats = ["construction"] + cats

                opp = Opportunity(
                    **self._base_kwargs(),
                    external_id=fields["external_id"] or ref,
                    title=title,
                    url=register,
                    solicitation_type=fields["solicitation_type"],
                    offer_type=OfferType.CONSTRUCTION
                    if "design" not in (proc_type or "").lower()
                    else OfferType.PROFESSIONAL_SERVICES,
                    categories=cats,
                    keywords=fields["keywords"],
                    due_date=due_dt,
                    posted_date=posted.date() if posted else None,
                    status=status,
                    budget=budget or None,
                    description=desc or None,
                    raw={"cells": cells, "headers": headers},
                )
                # override offer for design services
                if proc_type and "design" in proc_type.lower():
                    opp.offer_type = OfferType.PROFESSIONAL_SERVICES
                    if "architecture_engineering" not in opp.categories:
                        opp.categories = ["architecture_engineering"] + opp.categories
                out.append(opp)
        return out


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        # "August 2026" -> first of month
        return dateparser.parse(val, default=datetime(2026, 1, 1))
    except Exception:
        return None
