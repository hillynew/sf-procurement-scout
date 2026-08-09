"""Agencies that publish solicitations as a list of public-notice links.

Coral Gables is the reference case: no bid table and no vendor platform, just
anchors like "Public Notice - IFB 2026-021 - Art Cinema Expansion Project
[PDF]" pointing at the notice document. The reference number embedded in the
link text is the only structured field available, so it drives both the
identity and the title.
"""

from __future__ import annotations

import re
from typing import List
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..classify import enrich
from ..http_util import get
from ..models.opportunity import Document, Opportunity
from .base import SourceAdapter

# "IFB 2026-021", "RFP No. 2026-023", "ITB-25-26-120"
_REF = re.compile(
    r"\b(ITB|IFB|RFP|RFQ|RFI|ITN|RPQ|ITQ|RLI)\s*(?:No\.?\s*)?[-–]?\s*"
    r"(\d{2,4}[-–]\d{2,4}(?:[-–]\d{1,4})?)",
    re.I,
)

# Boilerplate that wraps the useful part of the link text.
_STRIP = re.compile(
    r"^\s*(?:public\s+notice|notice|addendum|advertisement)\s*[-–:]*\s*"
    r"|\s*\[?\s*(?:pdf|docx?|revised|\d+(?:st|nd|rd|th)\s+revised)\s*\]?\s*$",
    re.I,
)

# Documents that describe an already-decided procurement.
_NOT_A_SOLICITATION = re.compile(
    r"\b(award|tabulation|intent to award|results|minutes|agenda|archive)\b", re.I
)


class NoticeLinksAdapter(SourceAdapter):
    """Builds one opportunity per distinct solicitation reference on a page.

    Optional config keys:
      link_selector: CSS scope to search within (defaults to the whole page)
      base_url:      origin for relative hrefs (defaults to portal_url's)
    """

    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")

        scope = soup
        if self.cfg.get("link_selector"):
            scope = soup.select_one(str(self.cfg["link_selector"])) or soup

        best: dict[str, Opportunity] = {}
        for anchor in scope.find_all("a", href=True):
            text = _clean(anchor.get_text(" ", strip=True))
            match = _REF.search(text)
            if not match or _NOT_A_SOLICITATION.search(text):
                continue

            ref = f"{match.group(1).upper()} {match.group(2).replace('–', '-')}"
            title = _title(text, match)
            if len(title) < 5:
                continue

            url = urljoin(self.cfg.get("base_url") or self.portal_url, anchor["href"])
            fields = enrich(title, external_id=ref)
            opp = Opportunity(
                **self._base_kwargs(),
                external_id=ref,
                title=title,
                url=url,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"],
                categories=fields["categories"],
                keywords=fields["keywords"],
                status="open",
                description=(
                    "Public notice posted by the agency; open the document for the "
                    "submittal deadline and bid package."
                ),
                # The notice file itself — it was already in hand as the URL,
                # but never recorded as a document, so these rows scored as if
                # they had no package at all.
                documents=[Document(name=title[:160] or "Public notice", url=url)],
                raw={"link_text": text[:300]},
            )

            # A solicitation is often re-posted as "Revised" or with an addendum.
            # Keep the longest title, which is the most descriptive.
            prior = best.get(ref)
            if prior is None or len(opp.title) > len(prior.title):
                best[ref] = opp

        return list(best.values())


def _title(text: str, match: re.Match) -> str:
    """Everything after the reference, minus notice boilerplate."""
    tail = _strip_boilerplate(text[match.end():])
    # Some agencies put the subject before the reference instead.
    if len(tail) < 5:
        tail = _strip_boilerplate(text[: match.start()])
    return _clean(tail)[:200]


def _strip_boilerplate(text: str) -> str:
    """Peel off notice/format wrappers, which stack: '... Revised [PDF]'."""
    prev = None
    out = text.strip(" -–:|")
    while out != prev:
        prev = out
        out = _STRIP.sub("", out).strip(" -–:|")
    return out


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
