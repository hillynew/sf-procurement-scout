"""City of West Palm Beach solicitations listing.

wpb.org sits behind Akamai, which 403s every plain HTTP/1.1 library client
(warming the homepage does not help). HTTP/2 with browser-like headers gets
through — see http_util.get_h2 — though denials are intermittent, hence its
internal retries.

Parsing note: on the city's bid list, each solicitation renders as a
div.list-item-container whose p.status-list ("Status: Open / Awarded /
Closed / Complete / Cancelled") is the ONLY authoritative status. The word
"Closed" inside p.closing-date is the city's LABEL for the closing
datetime, not a status — a text-level regex on "closed" misclassifies every
open bid.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter


class WestPalmBeachAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        from ..http_util import get_h2, session

        resp = None
        try:
            resp = get_h2(self.portal_url)
        except Exception:
            resp = None

        if resp is None:
            # Legacy path: warm the homepage, then fetch. If that also fails,
            # degrade to the DemandStar pointer and let the runner mark this
            # source degraded rather than silently healthy.
            s = session()
            try:
                get("https://www.wpb.org/", s=s)
                resp = get(self.portal_url, s=s, referer="https://www.wpb.org/")
            except Exception as first_err:
                ds = self.cfg.get("demandstar_url")
                if not ds:
                    raise
                self.degraded_reason = f"city portal unreachable ({_brief_err(first_err)})"
                return [
                    Opportunity(
                        **self._base_kwargs(),
                        title="City of West Palm Beach solicitations (portal blocked — use DemandStar)",
                        url=ds,
                        categories=["portal_directory"],
                        status="catalog",
                        description=(
                            f"Direct city page returned an error ({_brief_err(first_err)}). "
                            f"Browse/register on DemandStar: {ds}"
                        ),
                        raw={"error": str(first_err)},
                    )
                ]

        soup = BeautifulSoup(resp.text, "lxml")
        out: List[Opportunity] = []
        seen = set()

        # Structured path: one div.list-item-container per solicitation, with
        # an explicit Status tag. The page lists years of history, so keep
        # only Status: Open.
        items = soup.select("div.list-item-container")
        if items:
            for it in items:
                a = it.find("a", href=True)
                title_el = it.select_one("h2.list-item-title")
                if not a or not title_el:
                    continue
                url = urljoin(self.portal_url, a["href"])
                if url in seen:
                    continue
                seen.add(url)

                status_el = it.select_one("p.status-list")
                status_txt = (
                    status_el.get_text(" ", strip=True).replace("Status:", "").strip().lower()
                    if status_el
                    else ""
                )
                # Awarded rows are records worth keeping, not noise: they are
                # the only award signal this walled portal publishes.
                if status_txt == "awarded":
                    status = "award"
                elif status_txt == "open":
                    status = "open"
                else:
                    continue

                title = re.sub(r"\s+", " ", title_el.get_text(" ", strip=True))[:200]

                ref = None
                ref_el = it.select_one("p.reference-number")
                if ref_el:
                    ref = (
                        ref_el.get_text(" ", strip=True)
                        .replace("Reference number:", "")
                        .strip()
                        or None
                    )

                due = None
                close_el = it.select_one("p.closing-date")
                if close_el:
                    due = _extract_date(close_el.get_text(" ", strip=True))

                description = None
                for p in it.find_all("p"):
                    cls = " ".join(p.get("class") or [])
                    if any(k in cls for k in ("reference-number", "closing-date", "status-list")):
                        continue
                    txt = p.get_text(" ", strip=True)
                    if txt and len(txt) > 20:
                        description = re.sub(r"\s+", " ", txt)[:400]
                        break

                fields = enrich(title, description or "", external_id=ref)

                ds = self.cfg.get("demandstar_url")
                desc_parts = []
                if description:
                    desc_parts.append(description)
                if ds:
                    desc_parts.append(f"Documents via DemandStar: {ds}")

                out.append(
                    Opportunity(
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
                        raw={"status": status_txt, "ref": ref},
                    )
                )
            return out

        # Legacy fallback: bare /Bids/ links without item containers.
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


def _brief_err(err: Exception) -> str:
    """One-line error text — the raw requests message embeds the whole URL."""
    msg = str(err).split(" for url:")[0].strip()
    return msg[:120] or type(err).__name__


def _extract_date(text: str) -> Optional[datetime]:
    m = re.search(
        r"([A-Za-z]+\s+\d{1,2},\s+\d{4}(?:,\s*\d{1,2}:\d{2}\s*[AP]M)?)", text
    )
    if not m:
        return None
    return parse_dt(m.group(1))


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
    return parse_dt(m.group(1))


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
