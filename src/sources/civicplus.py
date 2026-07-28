"""CivicPlus "Bids" module — the platform most South Florida cities run on.

A single adapter covers every city using it, so adding a municipality is a
config entry rather than a new scraper. The module renders each solicitation as

    <div class="listItemsRow bid">
      <div class="bidTitle">
        <span><a href="bids.aspx?bidID=110">Title</a></span>
        <span><strong>Bid No.</strong> IFB No. 22-25-26</span>
        <span>Scope of work... [<a>Read on</a>]</span>
      </div>
      <div class="bidStatus">
        <div><span>Status:</span><span>Closes:</span></div>
        <div><span>Open</span><span>Upon Contract</span></div>
      </div>
    </div>

with the status labels and their values in two parallel columns.
"""

from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter

# Phrases the module prints when a board has nothing posted.
_EMPTY_MARKERS = (
    "no open bid postings",
    "no bid postings",
    "there are no bids",
    "no current bid",
)

_STATUS_MAP = {
    "open": "open",
    "closed": "closed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "awarded": "closed",
    "intent to award": "closed",
    "pending": "closed",
    "archived": "closed",
    "upcoming": "upcoming",
}

# "Upon Contract", "See Documents" etc. are not dates.
_NON_DATE = re.compile(r"upon|see |n/?a|tbd|until|contract|award", re.I)


class CivicPlusAdapter(SourceAdapter):
    """Parses a CivicPlus /Bids.aspx board.

    Optional config keys:
      default_categories: categories every row from this portal inherits
      base_url:           origin for relative links (defaults to portal_url's)
    """

    def fetch(self) -> List[Opportunity]:
        resp = get(self.portal_url)
        soup = BeautifulSoup(resp.text, "lxml")

        if _looks_empty(soup):
            return []

        rows = _bid_rows(soup)
        out: List[Opportunity] = []
        seen: set[str] = set()
        for row in rows:
            opp = self._from_row(row)
            if opp and opp.url not in seen:
                seen.add(opp.url)
                out.append(opp)
        return out

    # -- internals ---------------------------------------------------------

    def _base(self) -> str:
        if self.cfg.get("base_url"):
            return str(self.cfg["base_url"])
        parts = urlparse(self.portal_url)
        return f"{parts.scheme}://{parts.netloc}"

    def _from_row(self, row) -> Optional[Opportunity]:
        title_el = row.select_one(".bidTitle")
        if title_el is None:
            return None
        link = title_el.find("a", href=True)
        title = _clean(link.get_text(" ", strip=True) if link else title_el.get_text(" ", strip=True))
        # The "Read on : <title>" link duplicates the heading; skip those rows.
        if not title or len(title) < 5 or title.lower().startswith("read on"):
            return None

        url = urljoin(self.portal_url, link["href"]) if link else self.portal_url
        ref = _bid_number(title_el)
        description = _description(title_el)
        status, due = _status_and_due(row)

        fields = enrich(title, description or "", external_id=ref)
        categories = list(fields["categories"])
        for extra in reversed(self.cfg.get("default_categories") or []):
            if extra not in categories:
                categories = [extra] + [c for c in categories if c != "general"]

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            url=url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=categories,
            keywords=fields["keywords"],
            due_date=due,
            status=status,
            description=description,
            raw={"ref": ref},
        )


def _bid_rows(soup: BeautifulSoup) -> list:
    """Every row carrying a bid title, whichever CivicPlus skin is in use."""
    rows = soup.select("div.listItemsRow.bid")
    if rows:
        return rows
    return [el.parent for el in soup.select("div.bidTitle") if el.parent is not None]


def _looks_empty(soup: BeautifulSoup) -> bool:
    if soup.select_one("div.bidTitle"):
        return False
    text = soup.get_text(" ", strip=True).lower()
    return any(marker in text for marker in _EMPTY_MARKERS)


def _bid_number(title_el) -> Optional[str]:
    """The reference follows a bolded 'Bid No.' label."""
    for strong in title_el.find_all("strong"):
        if "bid no" not in strong.get_text(" ", strip=True).lower():
            continue
        span = strong.parent
        ref = _clean(span.get_text(" ", strip=True))
        ref = re.sub(r"^bid\s*no\.?\s*", "", ref, flags=re.I).strip()
        if ref:
            return ref[:80]
    return None


def _description(title_el) -> Optional[str]:
    """The scope blurb, minus CivicPlus's '[Read on : ...]' affordance."""
    spans = title_el.find_all("span", recursive=False)
    if len(spans) < 3:
        return None
    text = _clean(spans[-1].get_text(" ", strip=True))
    text = re.sub(r"\[?\s*Read on\s*:?.*$", "", text, flags=re.I | re.S).strip(" .[]")
    return text[:400] or None


def _status_and_due(row) -> tuple[str, Optional[object]]:
    """Zip the label column against the value column of `.bidStatus`."""
    block = row.select_one(".bidStatus")
    if block is None:
        return "open", None
    columns = block.find_all("div", recursive=False)
    if len(columns) < 2:
        return "open", None

    labels = [_clean(s.get_text(" ", strip=True)).rstrip(":").lower() for s in columns[0].find_all("span")]
    values = [_clean(s.get_text(" ", strip=True)) for s in columns[1].find_all("span")]
    pairs = dict(zip(labels, values))

    status = "open"
    raw_status = (pairs.get("status") or "").lower()
    for key, mapped in _STATUS_MAP.items():
        if key in raw_status:
            status = mapped
            break

    due = None
    closes = pairs.get("closes") or pairs.get("closing") or ""
    if closes and not _NON_DATE.search(closes):
        due = parse_dt(closes)
    return status, due


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()
