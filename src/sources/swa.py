"""Solid Waste Authority of Palm Beach County bid postings (CivicPlus module)."""

from __future__ import annotations

import re
from typing import List

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get
from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter


class SwaAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")
        text = soup.get_text(" ", strip=True)

        # An empty bid board is a real answer: return nothing. The previous
        # version emitted a placeholder "No open SWA bid postings" row, which
        # showed up in the dashboard and counts as if it were a live bid.
        if "no open bid postings" in text.lower():
            return []

        out: List[Opportunity] = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
            if not any("bid" in h or "title" in h for h in headers):
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
                title = cell(cells, "title", "bid title", "bid") or cells[0]
                if len(title) < 5:
                    continue

                link = self.portal_url
                a = tr.find("a", href=True)
                if a:
                    link = a["href"] if a["href"].startswith("http") else (
                        "https://www.swa.org" + a["href"]
                    )

                due = parse_dt(cell(cells, "closing", "due", "close date"))
                posted = parse_dt(cell(cells, "published", "posted", "open date"))
                ref = cell(cells, "bid number", "number", "bid no")

                fields = enrich(title, " ".join(cells[1:4]), external_id=ref or None)
                cats = fields["categories"]
                if "waste_recycling" not in cats:
                    cats = ["waste_recycling"] + [c for c in cats if c != "general"]

                out.append(
                    Opportunity(
                        **self._base_kwargs(),
                        external_id=fields["external_id"] or ref or None,
                        title=title,
                        url=link,
                        solicitation_type=fields["solicitation_type"],
                        offer_type=fields["offer_type"]
                        if fields["offer_type"] != "unknown"
                        else OfferType.SERVICES,
                        categories=cats,
                        keywords=fields["keywords"],
                        due_date=due,
                        posted_date=posted.date() if posted else None,
                        status="open",
                        description=" | ".join(c for c in cells[1:4] if c) or None,
                        raw={"cells": cells, "headers": headers},
                    )
                )

        if out:
            return out
        return _parse_bid_links(self, soup)


def _parse_bid_links(adapter: SourceAdapter, soup: BeautifulSoup) -> List[Opportunity]:
    """CivicPlus sometimes renders bids as a link list rather than a table."""
    out: List[Opportunity] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"bids\.aspx\?bidid=", href, re.I):
            continue
        title = a.get_text(" ", strip=True)
        if len(title) < 8:
            continue
        url = href if href.startswith("http") else "https://www.swa.org" + href
        if url in seen:
            continue
        seen.add(url)

        fields = enrich(title)
        cats = ["waste_recycling"] + [c for c in fields["categories"] if c != "general"]
        out.append(
            Opportunity(
                **adapter._base_kwargs(),
                external_id=fields["external_id"],
                title=title,
                url=url,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"]
                if fields["offer_type"] != "unknown"
                else OfferType.SERVICES,
                categories=cats,
                keywords=fields["keywords"],
                status="open",
                raw={"link_text": title},
            )
        )
    return out

