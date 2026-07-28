"""Miami-Dade ISD current + future solicitations.

Both pages render an empty `<table>` shell and populate it client-side from a
DataTables AJAX endpoint, so the HTML-table scrape this adapter used to do
returned zero rows while still reporting success. We hit the JSON endpoints
directly and keep the table parse only as a fallback.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import looks_like_bare_date, parse_dt
from ..http_util import get, get_json, session
from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter

MD_HOST = "https://www.miamidade.gov"
DETAILS_PATH = "/apps/ISD/stratproc/Home/SolicitationDetails"


class MiamiDadeConstructionAdapter(SourceAdapter):
    """Current solicitations (open, with an opening date)."""

    list_path = "/apps/ISD/stratproc/Home/CurrentSolicitationsList"

    def fetch(self) -> List[Opportunity]:
        rows = _fetch_list(self.list_path, self.portal_url)
        if rows:
            return [o for o in (self._from_current(r) for r in rows) if o]
        return _parse_html_fallback(self, self.portal_url, "open", OfferType.CONSTRUCTION)

    def _from_current(self, r: Dict[str, Any]) -> Optional[Opportunity]:
        title = (r.get("title") or "").strip()
        sol_num = (r.get("solicitationNumber") or "").strip() or None
        sol_type = (r.get("solicitationType") or "").strip() or None
        if looks_like_bare_date(title):
            # The portal occasionally files a date in the title column; the
            # solicitation number is the only meaningful label left.
            title = sol_num or ""
        if not title:
            return None
        due = parse_dt(r.get("openingDate"))
        posted = parse_dt(r.get("postedDate"))

        url = self.portal_url
        if sol_num:
            url = f"{MD_HOST}{DETAILS_PATH}?solNumber={quote(sol_num)}"

        fields = enrich(title, sol_type or "", external_id=sol_num)
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or sol_num,
            title=title,
            url=url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            due_date=due,
            posted_date=posted.date() if posted else None,
            status="open",
            description=sol_type,
            raw=r,
        )


class MiamiDadeFutureAdapter(SourceAdapter):
    """Future / planned solicitations (advance notice, no bid date yet)."""

    list_path = "/apps/ISD/stratproc/Home/FutureSolicitationsList"

    def fetch(self) -> List[Opportunity]:
        rows = _fetch_list(self.list_path, self.portal_url)
        if rows:
            return [o for o in (self._from_future(r) for r in rows) if o]
        return _parse_html_fallback(self, self.portal_url, "upcoming", OfferType.UNKNOWN)

    def _from_future(self, r: Dict[str, Any]) -> Optional[Opportunity]:
        title = (r.get("documentTitle") or "").strip().rstrip(". ").strip()
        if not title:
            return None
        posted = parse_dt(r.get("releaseDate"))
        removal = parse_dt(r.get("removalDate"))
        contact_name = (r.get("sendFeedBack") or "").strip()
        email = (r.get("emailAddress") or "").strip()
        contact = " — ".join(x for x in [contact_name, email] if x) or None

        fields = enrich(title)
        # Advance notices carry no solicitation number; the posting counter is
        # the only stable per-row key the portal exposes.
        counter = r.get("webPostingCounter")
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or (f"WP-{counter}" if counter else None),
            title=title,
            url=self.portal_url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            due_date=None,
            posted_date=posted.date() if posted else None,
            status="upcoming",
            contact=contact,
            description=(
                "Advance notice of an upcoming solicitation"
                + (f"; posted through {removal.date().isoformat()}" if removal else "")
            ),
            raw=r,
        )


def _fetch_list(path: str, referer: str) -> List[Dict[str, Any]]:
    """Call the DataTables JSON endpoint. Returns [] when the shape is unexpected."""
    s = session()
    data = get_json(f"{MD_HOST}{path}", s=s, referer=referer)
    if isinstance(data, dict):
        # Some ISD endpoints wrap the array; unwrap the first list value.
        for v in data.values():
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        return []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _parse_html_fallback(
    adapter: SourceAdapter,
    url: str,
    status: str,
    default_offer: OfferType,
) -> List[Opportunity]:
    """Server-rendered table parse, used only if the JSON endpoint changes."""
    resp = get(url)
    soup = BeautifulSoup(resp.text, "lxml")
    out: List[Opportunity] = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])]
        if not headers or not any("title" in h or "solicitation" in h for h in headers):
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

            link = url
            a = tr.find("a", href=True)
            if a:
                href = a["href"]
                if href.startswith("http"):
                    link = href
                elif href.startswith("/"):
                    link = MD_HOST + href

            fields = enrich(title, sol_type, external_id=sol_num or None)
            posted_d = parse_dt(posted)
            out.append(
                Opportunity(
                    **adapter._base_kwargs(),
                    external_id=fields["external_id"] or sol_num or None,
                    title=title,
                    url=link,
                    solicitation_type=fields["solicitation_type"],
                    offer_type=fields["offer_type"]
                    if fields["offer_type"] != "unknown"
                    else default_offer,
                    categories=fields["categories"],
                    keywords=fields["keywords"],
                    due_date=parse_dt(opening),
                    posted_date=posted_d.date() if posted_d else None,
                    status=status,
                    contact=feedback or None,
                    description=sol_type or None,
                    raw={"cells": cells, "headers": headers},
                )
            )
    return out

