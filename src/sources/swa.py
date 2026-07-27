"""Solid Waste Authority of Palm Beach County bid postings."""

from __future__ import annotations

from typing import List
from bs4 import BeautifulSoup

from ..http_util import get
from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter


class SwaAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(" ", strip=True)

        # CivicPlus bid module often shows empty open list
        if "no open bid postings" in text.lower():
            return [
                Opportunity(
                    **self._base_kwargs(),
                    external_id=None,
                    title="No open SWA bid postings at this time",
                    url=self.portal_url,
                    offer_type=OfferType.SERVICES,
                    categories=["waste_recycling"],
                    status="catalog",
                    description="Checked live SWA bid board; no open postings. Subscribe for alerts on the portal.",
                )
            ]

        out: List[Opportunity] = []
        # Try table/list rows if present
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if not any("bid" in h or "title" in h for h in headers):
                continue
            for tr in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if not any(cells):
                    continue
                title = cells[0]
                out.append(
                    Opportunity(
                        **self._base_kwargs(),
                        title=title,
                        url=self.portal_url,
                        offer_type=OfferType.SERVICES,
                        categories=["waste_recycling"],
                        status="open",
                        description=" | ".join(cells[1:4]),
                        raw={"cells": cells},
                    )
                )
        return out
