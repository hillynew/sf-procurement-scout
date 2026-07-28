"""Miami-Dade INFORMS public bidding events (PeopleSoft supplier portal)."""

from __future__ import annotations

from typing import List
from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter


class MiamiDadeInformsAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")

        # PeopleSoft nests a header-only table above the data table — pick the
        # largest table whose headers include Event Name.
        candidates = []
        for t in soup.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 2:
                continue
            header_cells = rows[0].find_all(["th", "td"])
            headers = [c.get_text(" ", strip=True).lower() for c in header_cells]
            header_blob = " ".join(headers)
            if "event name" in header_blob and (
                "event id" in header_blob or "end date" in header_blob
            ):
                candidates.append((len(rows), t, headers))
        if not candidates:
            # fallback: any table with many rows
            for t in soup.find_all("table"):
                rows = t.find_all("tr")
                if len(rows) > 2:
                    headers = [
                        c.get_text(" ", strip=True).lower()
                        for c in rows[0].find_all(["th", "td"])
                    ]
                    candidates.append((len(rows), t, headers))
        if not candidates:
            return []
        candidates.sort(key=lambda x: x[0], reverse=True)
        _, table, headers = candidates[0]
        col = {h: i for i, h in enumerate(headers)}

        def cell(cells, *names):
            # Prefer exact header match, then substring (longer names first)
            ordered = sorted(names, key=len, reverse=True)
            for n in ordered:
                for h, i in col.items():
                    if h == n and i < len(cells):
                        return cells[i]
            for n in ordered:
                for h, i in col.items():
                    if n in h and i < len(cells):
                        return cells[i]
            return ""

        out: List[Opportunity] = []
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            title = cell(cells, "event name") or (cells[0] if cells else "")
            if not title or title.lower() in {"event name", "name"}:
                continue
            event_id = cell(cells, "event id")
            event_format = cell(cells, "event format")
            event_type = cell(cells, "event type")
            end_date = cell(cells, "end date")
            start_date = cell(cells, "start date")
            business_unit = cell(cells, "business unit")

            due = parse_dt(end_date)
            desc_bits = [b for b in [event_format, event_type, business_unit] if b]
            fields = enrich(title, " ".join(desc_bits), external_id=event_id or None)

            # Public detail deep-links require session; use portal as canonical url
            url = self.portal_url
            if event_id:
                url = f"{self.portal_url}#event={event_id}"

            opp = Opportunity(
                **self._base_kwargs(),
                external_id=fields["external_id"] or event_id or None,
                title=title,
                url=url,
                department=business_unit or None,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"],
                categories=fields["categories"],
                keywords=fields["keywords"],
                due_date=due,
                posted_date=parse_dt(start_date).date() if parse_dt(start_date) else None,
                status="open",
                description="; ".join(desc_bits) if desc_bits else None,
                raw={"cells": cells, "headers": headers},
            )
            out.append(opp)
        return out

