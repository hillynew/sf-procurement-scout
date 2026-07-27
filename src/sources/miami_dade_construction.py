"""Miami-Dade construction current + future solicitations HTML tables."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from dateutil import parser as dateparser
from bs4 import BeautifulSoup

from ..classify import enrich
from ..http_util import get
from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter


class MiamiDadeConstructionAdapter(SourceAdapter):
    """Current construction solicitations."""

    def fetch(self) -> List[Opportunity]:
        return _parse_md_table(
            self,
            self.portal_url,
            status="open",
            default_categories=["construction"],
            default_offer=OfferType.CONSTRUCTION,
        )


class MiamiDadeFutureAdapter(SourceAdapter):
    """Future / planned solicitations."""

    def fetch(self) -> List[Opportunity]:
        return _parse_md_table(
            self,
            self.portal_url,
            status="upcoming",
            default_categories=["construction"],
            default_offer=OfferType.CONSTRUCTION,
        )


def _parse_md_table(
    adapter: SourceAdapter,
    url: str,
    status: str,
    default_categories: List[str],
    default_offer: OfferType,
) -> List[Opportunity]:
    resp = get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    out: List[Opportunity] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if not headers:
            continue
        # need a title-like column
        if not any("title" in h or "solicitation" in h for h in headers):
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
            # skip empty data messages
            blob = " ".join(cells).lower()
            if "no data" in blob or "check back" in blob:
                continue

            title = cell(cells, "title") or (cells[2] if len(cells) > 2 else cells[0])
            if not title or len(title) < 3:
                continue
            sol_num = cell(cells, "solicitation number", "number")
            sol_type = cell(cells, "solicitation type", "type")
            opening = cell(cells, "opening date", "opening")
            posted = cell(cells, "posted date", "date posted", "posted")
            feedback = cell(cells, "feedback", "send feedback")

            # link if present
            link = url
            a = tr.find("a", href=True)
            if a:
                href = a["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = "https://www.miamidade.gov" + href

            fields = enrich(title, sol_type, external_id=sol_num or None)
            cats = fields["categories"]
            if default_categories:
                for c in default_categories:
                    if c not in cats:
                        cats = [c] + cats

            due = _parse_dt(opening)
            posted_d = _parse_dt(posted)

            opp = Opportunity(
                **adapter._base_kwargs(),
                external_id=fields["external_id"] or sol_num or None,
                title=title,
                url=link,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"] if fields["offer_type"] != "unknown" else default_offer,
                categories=cats,
                keywords=fields["keywords"],
                due_date=due,
                posted_date=posted_d.date() if posted_d else None,
                status=status,
                contact=feedback or None,
                description=sol_type or None,
                raw={"cells": cells, "headers": headers},
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
