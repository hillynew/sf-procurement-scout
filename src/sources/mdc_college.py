"""Miami Dade College bid posting page."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin
from dateutil import parser as dateparser
from bs4 import BeautifulSoup

from ..classify import enrich
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter


class MdcCollegeAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")
        out: List[Opportunity] = []
        seen = set()

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if not any("bid" in h or "solicitation" in h or "description" in h for h in headers):
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
                title = cell(cells, "bid/solicitation", "bid", "solicitation", "description") or cells[0]
                if not title or len(title) < 5:
                    continue
                # Deduplicate by title (page repeats same bid for announcements)
                key = title.lower().strip()
                if key in seen:
                    continue
                seen.add(key)

                posted = cell(cells, "posted", "date posted")
                contact = cell(cells, "contact")
                announcement = cell(cells, "announcement")

                # Prefer first document / announcement link
                link = self.cfg.get("register_url") or self.portal_url
                a = tr.find("a", href=True)
                if a and a["href"]:
                    link = urljoin(self.portal_url, a["href"])

                fields = enrich(title, announcement)
                posted_d = _parse_dt(posted)

                # Heuristic: treat as open if posted within ~18 months and not clearly award-only
                status = "open"
                if announcement and "award" in announcement.lower():
                    status = "closed"

                opp = Opportunity(
                    **self._base_kwargs(),
                    external_id=fields["external_id"],
                    title=title,
                    url=link,
                    solicitation_type=fields["solicitation_type"],
                    offer_type=fields["offer_type"],
                    categories=fields["categories"],
                    keywords=fields["keywords"],
                    posted_date=posted_d.date() if posted_d else None,
                    status=status,
                    contact=contact or None,
                    description=announcement or None,
                    raw={"cells": cells},
                )
                out.append(opp)
        return out


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return dateparser.parse(val)
    except Exception:
        return None
