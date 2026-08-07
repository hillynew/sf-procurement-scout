"""FDOT advertisements — and the host the research pointed at was the wrong one.

`bidletting.fdot.gov/LettingResults`, which the research names, is exactly what
it says: bid openings that have already happened, back to August 2024. There
are no advertisements on it. Open FDOT work is on a different host entirely.

## The route, which takes four hops to find and two to use

Advertisements live in the Procurement Development Application at
`pdaexternal.fdot.gov`, an AngularJS front end. Its ad list is not in the page:
the page is a template, and the data arrives from a separate REST host. Getting
there means reading, in order:

1. `/Home/Config` — publishes `RestApiUrl: https://pdaextapi.fdot.gov/api/`.
2. The Angular bundle, where `AllAdDetailsPublishingController` builds
   `AdvertisementPublic/GetAllNoticeDetails?DistrictCode=&ProcrPathCodeValue=&PageView=`.
3. An HTTP interceptor that copies a page-scoped `akey` into an
   `Authentication` header — without it the API answers 401 with an empty body.
4. The page itself, which mints that `akey` into `window.AllAdInitParams`.

So a fetch is two requests: load the page for a fresh `akey`, then call the API
once. `DistrictCode` empty means statewide, and `PageView=A` returns every
status at once, which is why one call does the work of four.

The `akey` is minted for anonymous callers by the site's own public page and is
sent exactly as the site sends it. Nothing here defeats a control — there is no
robots.txt on either host, `bidletting.fdot.gov` serves `Allow: /`, and the ads
are the s. 287.055 advertisements FDOT is required to publish.

## Two procurement paths, four views

`ProcrPathCodeValue` is `PS` (professional services, selected under the
Consultants' Competitive Negotiation Act) or `D-B` (design-build). They are
separate solicitation streams with separate ad numbers, so they are separate
sources rather than one merged feed. Measured 7 Aug 2026:

    PS    14 current · 124 planned · 111 in selection · 276 all
    D-B    1 current ·   0 planned ·  10 in selection ·  13 all

**The planned ads are the reason to bother.** FDOT publishes a Notice of
Planned Advertisement months before the advertisement itself — 124 of them for
professional services alone. Nothing else in this build sees work that early,
and `Opportunity` already has the `upcoming` status to hold it.

## Geography, which does not fit in one field

Every ad carries a district, and a district is several counties: District 4 is
Broward, Palm Beach, Martin, St. Lucie, Indian River and Okeechobee; District 6
is Miami-Dade and Monroe. `county` holds one value, so it stays `statewide` —
which is what a six-county advertisement honestly is — and the district goes in
`department` where it is visible. The district's counties are added to the
keywords so a text search for "broward" still finds its ads, which is the only
part of the loss that would actually cost someone a bid.
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any, Dict, List, Optional

from ..classify import enrich
from ..dates import parse_dt
from ..http_util import get, get_json, session
from ..models.opportunity import Opportunity
from .base import SourceAdapter

PAGE_HOST = "https://pdaexternal.fdot.gov"
API = "https://pdaextapi.fdot.gov/api/AdvertisementPublic/GetAllNoticeDetails"

#: The page that mints an `akey`, per procurement path. `A` returns every ad
#: status in one response, so the view is fixed here rather than parameterised.
PAGE = PAGE_HOST + "/Pub/AdvertisementPublic/AllAdDetail/{path}/A"

#: Where the page hides the token. Named `InitParams` on the district-selection
#: page and `AllAdInitParams` on this one, so both spellings are accepted.
_AKEY = re.compile(r"window\.(?:AllAd)?InitParams\s*=\s*JSON\.parse\('(.*?)'\);", re.S)

#: What the portal's ad statuses mean here. `Planned` is a Notice of Planned
#: Advertisement — real, dated, and months ahead of anything else this project
#: sees, which is why it is carried rather than dropped.
STATUS = {
    "current": "open",
    "planned": "upcoming",
    "ad closed": "closed",
    "not yet selected": "closed",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

#: FDOT district -> the counties it covers. Used only to seed keywords: a
#: six-county advertisement has no single county, but someone searching their
#: own county should still find it.
DISTRICT_COUNTIES: Dict[str, tuple] = {
    "01": ("charlotte", "collier", "desoto", "glades", "hardee", "hendry",
           "highlands", "lee", "manatee", "okeechobee", "polk", "sarasota"),
    "02": ("alachua", "baker", "bradford", "clay", "columbia", "dixie", "duval",
           "gilchrist", "hamilton", "lafayette", "levy", "madison", "nassau",
           "putnam", "st-johns", "suwannee", "taylor", "union"),
    "03": ("bay", "calhoun", "escambia", "franklin", "gadsden", "gulf", "holmes",
           "jackson", "jefferson", "leon", "liberty", "okaloosa", "santa-rosa",
           "wakulla", "walton", "washington"),
    "04": ("broward", "indian-river", "martin", "okeechobee", "palm-beach",
           "st-lucie"),
    "05": ("brevard", "flagler", "lake", "marion", "orange", "osceola",
           "seminole", "sumter", "volusia"),
    "06": ("miami-dade", "monroe"),
    "07": ("citrus", "hernando", "hillsborough", "pasco", "pinellas"),
    "08": (),  # Florida's Turnpike Enterprise — a road, not a region.
    "99": (),  # Central Office.
}

#: District labels, for `department`.
DISTRICT_NAMES = {
    "08": "Florida's Turnpike Enterprise",
    "99": "Central Office",
}


class FdotAdsAdapter(SourceAdapter):
    """One FDOT procurement path. `fdot_procurement_path` is `PS` or `D-B`."""

    #: The detail view is another Angular page against another API route, and
    #: the list already carries the deadline, the amount and the work types.
    supports_detail = False

    def __init__(self, cfg: Dict[str, Any]):
        super().__init__(cfg)
        self._s = None

    # -- public ------------------------------------------------------------

    def fetch(self) -> List[Opportunity]:
        """Advertised and planned work. Planned is the point — see the docstring."""
        return [o for o in self._collect() if o.status in ("open", "upcoming")]

    def fetch_history(self) -> List[Opportunity]:
        """Ads that have closed or are awaiting selection."""
        return [o for o in self._collect() if o.status not in ("open", "upcoming")]

    # -- internals ---------------------------------------------------------

    def _path(self) -> str:
        value = str(self.cfg.get("fdot_procurement_path") or "").strip()
        if value not in ("PS", "D-B"):
            raise ValueError(f"{self.source_id}: fdot_procurement_path must be PS or D-B")
        return value

    def _session(self):
        if self._s is None:
            self._s = session()
        return self._s

    def _akey(self) -> Optional[str]:
        """A fresh token from the page that mints it."""
        url = PAGE.format(path=self._path())
        try:
            html = get(url, s=self._session(), timeout=60).text
        except Exception:  # noqa: BLE001 — one source's outage is not the run's
            self.degraded_reason = "the advertisement page could not be read"
            return None
        return akey_from(html)

    def _collect(self) -> List[Opportunity]:
        # Resolved before anything tolerant runs. Inside the fetch, a bad
        # `fdot_procurement_path` would be caught by the except and reported as
        # "the advertisement page could not be read" — a plausible outage
        # standing in for a typo in config. Same trap as vendor_registry.
        self._path()

        akey = self._akey()
        if akey is None:
            if not self.degraded_reason:
                self.degraded_reason = "the page carried no token for the ad API"
            return []

        try:
            payload = get_json(
                API,
                s=self._session(),
                timeout=90,
                headers={"Authentication": akey},
                params={
                    "DistrictCode": "",  # empty is statewide
                    "ProcrPathCodeValue": self._path(),
                    "PageView": "A",
                },
            )
        except Exception:  # noqa: BLE001
            self.degraded_reason = "the ad API did not answer"
            return []

        rows = ((payload or {}).get("Model") or {}).get("AdList") or []
        out = [o for o in (self._to_opportunity(r) for r in rows) if o is not None]
        if rows and not out:
            self.degraded_reason = f"the API returned {len(rows)} ads and none parsed"
        return out

    def _to_opportunity(self, row: Dict[str, Any]) -> Optional[Opportunity]:
        title = _text(row.get("AdShortDescription"))
        ref = _text(row.get("AdNumber")) or None
        if not title and not ref:
            return None
        # Some ads carry only a number. A bare id is still actionable when the
        # deadline and the work types are there; an untitled row is not.
        title = title or f"FDOT advertisement {ref}"

        district = _text(row.get("DotAssignedDistrictCode")) or ""
        fields = enrich(title, external_id=ref)
        status = STATUS.get(_text(row.get("AdStatusTypeName")).lower(), "closed")

        keywords = list(fields["keywords"])
        for county in DISTRICT_COUNTIES.get(district, ()):
            if county not in keywords:
                keywords.append(county)

        return Opportunity(
            **self._base_kwargs(),
            external_id=fields["external_id"] or ref,
            title=title,
            # No per-ad public URL exists without the SPA's own routing, so this
            # points at the board the row was read from.
            url=PAGE.format(path=self._path()),
            department=district_label(district),
            solicitation_type=fields["solicitation_type"],
            offer_type=fields["offer_type"],
            categories=fields["categories"],
            keywords=keywords,
            posted_date=_date(row.get("LastDateAdvertised")),
            due_date=parse_dt(_text(row.get("ResponseDeadlineDateTime"))),
            budget=_amount(row.get("AdContractAmount")),
            status=status,
            raw={"fdot": {k: _text(v) for k, v in row.items() if v not in (None, "")}},
        )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def akey_from(html: str) -> Optional[str]:
    """The page-scoped token the ad API requires as an `Authentication` header.

    Minted per page load. Without it the API answers 401 with an empty body,
    which reads as a broken endpoint rather than a missing header — worth
    naming, because that is an afternoon.
    """
    match = _AKEY.search(html or "")
    if match is None:
        return None
    try:
        return (json.loads(match.group(1)) or {}).get("akey") or None
    except (ValueError, TypeError):
        return None


def _text(value: Any) -> str:
    """A field as a person would read it.

    The API returns display HTML inside JSON — work types arrive as
    `' 7.1-Signing &lt;br/&gt; '`, doubly escaped — so entities are resolved and
    the tags that survive become separators rather than being glued together.
    """
    if value is None:
        return ""
    text = unescape(unescape(str(value)))
    text = re.sub(r"<br\s*/?>", " · ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split()).strip(" ·").strip()


def _date(value: Any):
    parsed = parse_dt(_text(value))
    return parsed.date() if parsed else None


def _amount(value: Any) -> Optional[str]:
    """The contract limit, rendered rather than stored raw.

    `budget` is a display string on `Opportunity`, and the API sends
    `'2950000.0'`, which is not what anyone wants to read on a board.
    """
    text = _text(value).replace(",", "").replace("$", "")
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    if amount <= 0:
        return None
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    return f"${amount:,.0f}"


def district_label(code: str) -> Optional[str]:
    """"District 4", or the name for the two districts that are not regions."""
    code = (code or "").strip()
    if not code:
        return None
    if code in DISTRICT_NAMES:
        return f"FDOT {DISTRICT_NAMES[code]}"
    return f"FDOT District {code.lstrip('0') or code}"
