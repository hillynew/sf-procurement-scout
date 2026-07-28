"""Miami Dade College bid posting page.

The page is an *announcement log*, not a bid list: one solicitation produces a
row per announcement (bid opening link, evaluation committee meeting, list of
proposers, award recommendation). Scraping it row-by-row previously emitted
~110 near-duplicate "open" opportunities, most of them years old and already
awarded. We now collapse rows to one record per solicitation reference and
derive status from the announcement trail and recency.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_date
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter

# MDC never publishes a due date on this page, so recency is the only signal
# for whether a solicitation is still live.
STALE_AFTER_DAYS = 150

# Announcement text that proves the solicitation has moved past bidding.
_CLOSED_MARKERS = (
    "award",
    "list of proposer",
    "list of proposal",
    "proposals received",
    "receipt of proposal",
    "evaluation committee",
    "recommendation",
    "bid opening",
    "bid tabulation",
    "intent to",
)

# Solicitation reference, e.g. "RFQ-2024-NL-07", "2025-RM1-04", "ITN 2025-GN-12".
# The leading class prefix is optional because many rows omit it.
_DASH = r"[\s‐-―−_-]*"  # the page mixes ASCII, unicode and non-breaking dashes
_REF_RE = re.compile(
    r"^\s*"
    rf"(?:(?:ITB|IFB|RFP|RFQ|RFI|ITN){_DASH})?"  # optional, inconsistent class prefix
    rf"(\d{{4}}){_DASH}"  # fiscal year
    rf"([A-Z]{{2,3}}\d?){_DASH}"  # buyer code, e.g. NL / RM1
    r"(\d{2})",  # sequence
    re.IGNORECASE,
)


class MdcCollegeAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")

        groups: Dict[str, "_Solicitation"] = {}
        out: List[Opportunity] = []

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [
                c.get_text(" ", strip=True).lower() for c in rows[0].find_all(["th", "td"])
            ]
            if not headers:
                continue

            is_bid_table = any("bid" in h or "solicitation" in h for h in headers)
            is_nssp = (not is_bid_table) and any("description" in h for h in headers)
            if not (is_bid_table or is_nssp):
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
                title = (
                    cell(cells, "bid/solicitation", "bid", "solicitation", "description")
                    or cells[0]
                )
                title = _clean(title)
                if len(title) < 5:
                    continue

                posted = parse_date(cell(cells, "posted", "date posted"))
                contact = cell(cells, "contact") or None
                announcement = cell(cells, "announcement") or None

                link = self.cfg.get("register_url") or self.portal_url
                a = tr.find("a", href=True)
                if a and a["href"]:
                    link = urljoin(self.portal_url, a["href"])

                if is_nssp:
                    # Notices of single-source intent: not competitive bids, but
                    # worth surfacing — they signal upcoming spend in a category.
                    out.append(self._nssp(title, link, posted, contact))
                    continue

                ref = _extract_ref(title)
                key = ref or title.lower()
                grp = groups.get(key)
                if grp is None:
                    groups[key] = _Solicitation(
                        ref=ref, title=title, url=link, posted=posted,
                        contact=contact, announcements=[],
                    )
                    grp = groups[key]
                grp.absorb(title, link, posted, contact, announcement)

        out.extend(self._from_group(g) for g in groups.values())
        return out

    def _from_group(self, g: "_Solicitation") -> Opportunity:
        desc_bits = []
        if g.announcements:
            desc_bits.append("Announcements: " + "; ".join(g.announcements[:6]))
        if len(g.titles) > 1:
            desc_bits.append(f"Also listed as: {'; '.join(sorted(g.titles)[1:3])}")

        fields = enrich(g.title, " ".join(desc_bits), external_id=g.ref)
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or g.ref,
            title=g.title,
            url=g.url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            posted_date=g.posted,
            status=g.status(),
            contact=g.contact,
            description=" | ".join(desc_bits) or None,
            raw={"ref": g.ref, "announcements": g.announcements, "titles": sorted(g.titles)},
        )

    def _nssp(
        self,
        title: str,
        link: str,
        posted: Optional[date],
        contact: Optional[str],
    ) -> Opportunity:
        fields = enrich(title)
        cats = ["single_source"] + [c for c in fields["categories"] if c != "general"]
        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"],
            title=title,
            url=link,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=cats,
            keywords=fields["keywords"],
            posted_date=posted,
            status="upcoming" if _is_recent(posted) else "closed",
            contact=contact,
            description=(
                "Notice of Single Source Procurement — the College intends to buy "
                "without competition. Vendors who can supply an equivalent may object "
                "to the listed contact."
            ),
            raw={"nssp": True},
        )


class _Solicitation:
    """Accumulates the announcement rows that belong to one solicitation."""

    def __init__(
        self,
        ref: Optional[str],
        title: str,
        url: str,
        posted: Optional[date],
        contact: Optional[str],
        announcements: List[str],
    ):
        self.ref = ref
        self.title = title
        self.url = url
        self.posted = posted
        self.contact = contact
        self.announcements = announcements
        self.titles = {title}

    def absorb(
        self,
        title: str,
        url: str,
        posted: Optional[date],
        contact: Optional[str],
        announcement: Optional[str],
    ) -> None:
        self.titles.add(title)
        # Keep the longest title — it is usually the fully spelled-out one.
        if len(title) > len(self.title):
            self.title = title
        # Newest announcement wins for date, link and contact.
        if posted and (self.posted is None or posted > self.posted):
            self.posted = posted
            self.url = url
            if contact:
                self.contact = contact
        if announcement and announcement not in self.announcements:
            self.announcements.append(announcement)

    def status(self) -> str:
        blob = " ".join(self.announcements).lower()
        if any(m in blob for m in _CLOSED_MARKERS):
            return "closed"
        return "open" if _is_recent(self.posted) else "closed"


def _is_recent(d: Optional[date]) -> bool:
    if d is None:
        # Undated rows on an archive page are assumed stale rather than open;
        # calling them open is what produced the false "109 open bids".
        return False
    return (date.today() - d).days <= STALE_AFTER_DAYS


def _clean(text: str) -> str:
    # The page mixes non-breaking spaces and unicode dashes into references.
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _extract_ref(title: str) -> Optional[str]:
    m = _REF_RE.match(title)
    if not m:
        return None
    year, buyer, seq = m.groups()
    # Normalize so "RFQ-2024-NL-07", "2024-NL-07" and "2024-NL-07-" collapse
    # to one key; the class prefix is dropped because it is inconsistent.
    return f"{year}-{buyer.upper()}-{seq}"
