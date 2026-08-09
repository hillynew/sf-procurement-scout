"""Commission award approvals from the Legistar Web API — local award amounts.

No Florida platform publishes local award amounts anonymously (verified across
Bonfire, OpenGov, Ionwave, VendorLink and CivicPlus on 2026-08-09, see
docs/SOURCES.md). The place a county or city award actually becomes public,
with a dollar figure, is the commission agenda — and agencies on Granicus's
Legistar publish those matters through a free JSON API:

    GET https://webapi.legistar.com/v1/{client}/matters?$filter=...&$top=N

The matter *title* carries the whole record: "MOTION TO AWARD open-end
contract to low bidder, Crown USA, Inc., for Runway Acrylic Traffic Paint,
Bid No. OPN2131620B1 ... in the initial one-year estimated amount of
$193,500" (Broward County, live-verified). So this adapter is a title parser:
vendor, dollar amount, and the solicitation reference all come out of prose,
and every extraction is best-effort with the raw title kept.

These rows arrive as ``status="award"`` records. They are approvals by the
governing body, not intended-decision notices, so no protest clock is set —
by the time a commission votes, s. 120.57(3)(b)'s 72 hours from the *posted
notice* has usually run. The value here is the amount and the winner.

Live-verified Florida clients (2026-08-09): broward, fortlauderdale, miamifl,
coralgables, polkcountyfl, jaxcityc. Miami-Dade's instance is dead (frozen
2018) — deliberately not configured.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get_json
from ..models.opportunity import Opportunity
from .base import SourceAdapter

API = "https://webapi.legistar.com/v1"

#: How far back to ask for matters. Awards are useful as intelligence for a
#: year or so; the API pages beyond this are still there when needed.
LOOKBACK_DAYS = 365
PAGE_SIZE = 200
MAX_PAGES = 5

#: Words in a matter title that mark it as an award action. Checked
#: case-insensitively; commission clerks write in every case imaginable.
_AWARD_WORDS = re.compile(r"\baward", re.I)

#: "$193,500", "$2,165,000", "$1,234,567.89" — the largest figure in the title
#: is taken as the award amount; agenda titles often carry an initial-term and
#: a lifetime figure, and the *first* is the term actually awarded, so first
#: wins and the rest stay in the raw title.
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")

#: Solicitation references quoted in titles: "Bid No. OPN2131620B1",
#: "RFP No. 449", "ITB-24-011", "RFQ No. R2113109P1".
_REF = re.compile(
    r"\b(?:(?:Bid|RFP|RFQ|ITB|RLI|ITN|IFB|Solicitation|Contract)\b\s*(?:No\.?|#|Number)?\s*[:.]?\s*)"
    r"([A-Z0-9][A-Z0-9./-]{2,24})",
    re.I,
)

#: The vendor, from the phrasings clerks actually use:
#: "award ... to (low bidder,) Crown USA, Inc., for ..." /
#: "with BCC Engineering, LLC ..." / "to Acme Corp. in the amount of".
#: Corporate forms first — "BCC Engineering, LLC" must not stop at
#: "Engineering" — then descriptive endings as a fallback.
#: "low bidder," / "single bidder," / "lowest responsive bidder," — any short
#: qualifier chain ending in "bidder" is skipped to reach the name.
_LEAD = (
    r"\b(?:to|with)\s+(?:the\s+)?(?:(?:[a-z]+\s+){0,3}bidder,?\s+)?"
)
_VENDOR_CORP = re.compile(
    _LEAD + r"([A-Z][\w&.,'()\- ]{2,80}?(?:Inc|LLC|LLP|Corp|Corporation|Company|"
    r"Ltd|P\.?A|Co)\.?)(?=[,;\s]|$)",
)
_VENDOR_DESC = re.compile(
    _LEAD + r"([A-Z][\w&.,'()\- ]{2,80}?(?:Group|Services|Enterprises|Associates|"
    r"Engineering|Construction|Contracting|Industries|Solutions|Systems)\.?)(?=[,;\s]|$)",
)


class LegistarAwardsAdapter(SourceAdapter):
    """Award matters for one Legistar client (`legistar_client` config key)."""

    #: A quiet quarter is possible for a small city, and the filter is narrow.
    allows_empty = True
    #: Awards, not solicitations — must never supersede a live bid source.
    provides_open_bids = False

    def fetch(self) -> List[Opportunity]:
        client = self._client()
        since = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
        out: List[Opportunity] = []
        skip = 0
        for _ in range(MAX_PAGES):
            rows = get_json(
                f"{API}/{client}/matters",
                params={
                    "$filter": (
                        f"MatterAgendaDate ge datetime'{since}' and "
                        "substringof('ward', MatterTitle)"
                    ),
                    "$orderby": "MatterId desc",
                    "$top": str(PAGE_SIZE),
                    "$skip": str(skip),
                },
            )
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                opp = self._from_matter(row)
                if opp is not None:
                    out.append(opp)
            if len(rows) < PAGE_SIZE:
                break
            skip += PAGE_SIZE
        if not out:
            self.empty_note = "no award matters on recent agendas"
        return out

    def _client(self) -> str:
        client = str(self.cfg.get("legistar_client") or "").strip()
        if not client:
            raise ValueError(f"{self.source_id}: legistar_client required")
        return client

    def _from_matter(self, row: Dict[str, Any]) -> Optional[Opportunity]:
        title = str(row.get("MatterTitle") or "").strip()
        # substringof('ward') also matches "forward"/"Broward"; the real test
        # is the word "award" — applied here where case-folding is easy.
        if not title or not _AWARD_WORDS.search(title):
            return None

        matter_id = row.get("MatterId")
        agenda = parse_dt(str(row.get("MatterAgendaDate") or ""))
        passed = parse_dt(str(row.get("MatterPassedDate") or ""))
        decided = passed or agenda

        amount = _first_amount(title)
        vendor = _vendor_from(title)
        ref = _ref_from(title)

        fields = enrich(title[:160], title, external_id=None)
        file_no = str(row.get("MatterFile") or "").strip() or None
        return Opportunity(
            **self._base_kwargs(),
            external_id=file_no or (str(matter_id) if matter_id else None),
            title=title[:200],
            url=self.portal_url,
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=fields["keywords"],
            status="award",
            posted_date=decided.date() if decided else None,
            award_date=decided.date() if decided else None,
            awarded_vendor=vendor,
            award_amount=amount,
            linked_ref=ref,
            award_linkage="ref" if ref else None,
            description=title[:600],
            raw={"legistar": {k: row.get(k) for k in (
                "MatterId", "MatterFile", "MatterTitle", "MatterTypeName",
                "MatterStatusName", "MatterAgendaDate", "MatterPassedDate",
            )}},
        )


def _first_amount(title: str) -> Optional[int]:
    m = _MONEY.search(title)
    if not m:
        return None
    try:
        return int(round(float(m.group(1).replace(",", ""))))
    except ValueError:
        return None


def _vendor_from(title: str) -> Optional[str]:
    m = _VENDOR_CORP.search(title) or _VENDOR_DESC.search(title)
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip(" ,.")


def _ref_from(title: str) -> Optional[str]:
    m = _REF.search(title)
    if not m:
        return None
    ref = m.group(1).strip(" .,-")
    # A reference has digits in it; prose caught by the pattern does not.
    clean = re.sub(r"[^A-Za-z0-9]", "", ref)
    return ref if len(clean) >= 3 and any(c.isdigit() for c in clean) else None
