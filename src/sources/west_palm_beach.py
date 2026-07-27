"""City of West Palm Beach solicitations listing."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin
from dateutil import parser as dateparser
from bs4 import BeautifulSoup

from ..classify import enrich
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter


class WestPalmBeachAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        # City site sometimes blocks bare scrapers (403). Warm homepage first.
        from ..http_util import session

        s = session()
        try:
            get("https://www.wpb.org/", s=s)
            resp = get(self.portal_url, s=s, referer="https://www.wpb.org/")
        except Exception as first_err:
            # Fallback: DemandStar agency page + catalog pointer
            ds = self.cfg.get("demandstar_url")
            if not ds:
                raise first_err
            return [
                Opportunity(
                    **self._base_kwargs(),
                    title="City of West Palm Beach solicitations (portal blocked — use DemandStar)",
                    url=ds,
                    categories=["portal_directory"],
                    status="catalog",
                    description=(
                        f"Direct city page returned an error ({first_err}). "
                        f"Browse/register on DemandStar: {ds}"
                    ),
                    raw={"error": str(first_err)},
                )
            ]

        soup = BeautifulSoup(resp.text, "lxml")
        out: List[Opportunity] = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/Bids/" not in href and "/bids/" not in href.lower():
                continue
            text = a.get_text(" ", strip=True)
            if not text or len(text) < 8:
                continue

            url = urljoin(self.portal_url, href)
            if url in seen:
                continue
            seen.add(url)

            status = _status_from_text(text)
            ref = _extract_ref(text)
            title = _extract_title(text, ref)
            due = _extract_closing(text)
            description = _extract_description(text)

            fields = enrich(title, description or "", external_id=ref)

            ds = self.cfg.get("demandstar_url")
            desc_parts = []
            if description:
                desc_parts.append(description)
            if ds:
                desc_parts.append(f"Documents via DemandStar: {ds}")

            opp = Opportunity(
                **self._base_kwargs(),
                external_id=fields["external_id"] or ref,
                title=title,
                url=url,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"],
                categories=fields["categories"],
                keywords=fields["keywords"],
                due_date=due,
                status=status,
                description=" | ".join(desc_parts) if desc_parts else None,
                raw={"link_text": text[:500]},
            )
            out.append(opp)

        return out


def _status_from_text(text: str) -> str:
    t = text.lower()
    if "cancel" in t:
        return "cancelled"
    if re.search(r"\bclosed\b", t):
        return "closed"
    if re.search(r"\bopen\b", t) or "closing date" in t:
        return "open"
    return "open"


def _extract_ref(text: str) -> Optional[str]:
    m = re.search(
        r"Reference number:\s*((?:ITB|IFB|RFP|RFQ|RFI|ITN)[^\n|]*?)(?:\s+Closed|\s+Closing|\s+Open|$)",
        text,
        re.I,
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    m = re.search(r"\b((?:ITB|IFB|RFP|RFQ|RFI|ITN)\s*(?:No\.?\s*)?[\d][\w./-]{2,})", text, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return None


def _extract_title(text: str, ref: Optional[str]) -> str:
    # Patterns like: "Pest Control... Reference number: ITB ..."
    if "Reference number:" in text:
        title = text.split("Reference number:")[0].strip(" -|")
        if title:
            return re.sub(r"\s+", " ", title)[:200]
    # Or "ITB 25-26-120 MK-Pressure Washing..."
    if ref and ref in text:
        # use whole first line-ish
        first = text.split("Reference number:")[0].strip()
        return re.sub(r"\s+", " ", first)[:200]
    return re.sub(r"\s+", " ", text)[:200]


def _extract_closing(text: str) -> Optional[datetime]:
    m = re.search(
        r"Closing date\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?)",
        text,
        re.I,
    )
    if not m:
        m = re.search(
            r"Closed\s+([A-Za-z]+\s+\d{1,2},\s+\d{4}(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?)",
            text,
            re.I,
        )
    if not m:
        return None
    try:
        return dateparser.parse(m.group(1))
    except Exception:
        return None


def _extract_description(text: str) -> Optional[str]:
    # After closing date block, remaining narrative
    m = re.search(
        r"(?:Closing date|Closed)\s+[A-Za-z]+\s+\d{1,2},\s+\d{4}(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?\s*(.*)$",
        text,
        re.I | re.S,
    )
    if m:
        desc = re.sub(r"\s+", " ", m.group(1)).strip()
        if len(desc) > 20:
            return desc[:400]
    return None
