"""FDOT construction bid tabs — every bidder and every amount, per letting.

The PDA advertisement feed (`fdot_ads.py`) sees road work being *asked for*;
this host is where the bids are *opened*. Each district posts a Preliminary
Letting Results Report per letting date, and it is the only FDOT surface that
publishes dollar figures: every bidder's name and bid amount, ascending, with
the contract number, financial project number and county.

    GET /LettingResults?districtID={01..07|99}      the district's lettings
    GET /LettingResults/DisplayPreliminaryReport?id={lettingID}&lettingDate={d}

`districtID=99` is the Central Office / Turnpike series (`CTyymmdd` ids), a
separate letting stream from the seven districts.

Two honesty notes carried onto every record:

* The first bidder is the **apparent low bid**, not the winner — the report's
  own header says "Please see the Posting and Award Notices for Official
  Intent to Award". The row is still worth having: FDOT lets by low bid, so
  the apparent low bidder is the presumptive winner, and every competitor's
  number is market intelligence either way.
* These are award-side records (``provides_open_bids = False``); the ask side
  is `fdot_ads`.

Server-rendered HTML, no token, and `bidletting.fdot.gov` serves
`Allow: /` — the polite opposite of most of this codebase's targets.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, List

from bs4 import BeautifulSoup

from ..classify import enrich
from ..dates import parse_dt
from ..fl_geo import infer_county
from ..http_util import get
from ..models.opportunity import Opportunity
from .base import SourceAdapter

BASE = "https://bidletting.fdot.gov"

#: The seven districts plus the Central Office / Turnpike series.
DEFAULT_DISTRICTS = ("01", "02", "03", "04", "05", "06", "07", "99")

#: Only lettings this recent get their report fetched; older results are
#: history, and every report is one request.
RECENT_DAYS = 60
REPORTS_PER_DISTRICT = 1

_LETTING_DIV = re.compile(r"^(?:\d{2}|CT)\d{6}$")
_MONEY = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")


class FdotLettingAdapter(SourceAdapter):
    allows_empty = True
    provides_open_bids = False

    def fetch(self) -> List[Opportunity]:
        districts = self.cfg.get("districts") or list(DEFAULT_DISTRICTS)
        today = date.today()
        cutoff = today - timedelta(days=RECENT_DAYS)

        out: List[Opportunity] = []
        read = 0
        for district in districts:
            try:
                html = get(f"{BASE}/LettingResults?districtID={district}").text
            except Exception:  # noqa: BLE001 — one district is not the source
                continue
            read += 1
            for letting_id, letting_date in self._recent_lettings(html, cutoff, today):
                report_url = (
                    f"{BASE}/LettingResults/DisplayPreliminaryReport"
                    f"?id={letting_id}&lettingDate={letting_date:%m/%d/%Y}"
                )
                try:
                    report = get(report_url).text
                except Exception:  # noqa: BLE001
                    continue
                out.extend(self._contracts(report, report_url, district, letting_date))

        if read == 0:
            self.degraded_reason = "no district letting page could be read"
        elif not out:
            self.empty_note = f"no lettings in the last {RECENT_DAYS} days"
        return out

    def _recent_lettings(self, html: str, cutoff: date, today: date):
        """(lettingID, date) pairs recent enough to fetch, newest first."""
        soup = BeautifulSoup(html, "lxml")
        found = []
        for div in soup.find_all("div", id=_LETTING_DIV):
            link = div.find("a", class_="lettingLink")
            parsed = parse_dt(link.get("id") or link.get_text(strip=True)) if link else None
            if not parsed:
                continue
            when = parsed.date()
            if cutoff <= when <= today:
                found.append((div["id"], when))
        found.sort(key=lambda pair: pair[1], reverse=True)
        return found[:REPORTS_PER_DISTRICT]

    def _contracts(
        self, html: str, report_url: str, district: str, letting_date: date
    ) -> List[Opportunity]:
        soup = BeautifulSoup(html, "lxml")
        out: List[Opportunity] = []
        for header in soup.find_all("div", id="contractHeader"):
            labels: Dict[str, str] = {}
            for cell in header.find_all("div", class_="ContractHeader"):
                span = cell.find("span")
                if span is None:
                    continue
                label = span.get_text(strip=True).rstrip(":").lower()
                value = cell.get_text(" ", strip=True)
                value = value[len(span.get_text(" ", strip=True)):].strip()
                labels[label] = value

            bidders = self._bidders_after(header)
            contract_no = labels.get("contract no") or ""
            if not contract_no or not bidders:
                continue

            county_name = labels.get("county") or ""
            county = infer_county(f"{county_name} County") if county_name else "statewide"
            low_vendor, low_amount = bidders[0]

            title = f"FDOT letting {letting_date:%m/%d/%Y}: contract {contract_no}"
            if county_name:
                title += f" — {county_name.title()} County"
            lines = [f"{name} — ${amount:,.2f}" for name, amount in bidders]
            description = (
                "Preliminary letting results (apparent low bid first; official "
                "Intent to Award posts on FDOT Contracts Administration). "
                f"{len(bidders)} bid(s): " + " · ".join(lines)
            )[:600]

            fields = enrich(title, external_id=contract_no)
            base = self._base_kwargs()
            base["county"] = county
            out.append(
                Opportunity(
                    **base,
                    external_id=contract_no,
                    title=title,
                    url=report_url,
                    department=f"FDOT District {district}" if district != "99" else "FDOT Central Office / Turnpike",
                    solicitation_type=fields["solicitation_type"],
                    offer_type=fields["offer_type"],
                    categories=fields["categories"],
                    keywords=fields["keywords"],
                    status="award",
                    award_date=letting_date,
                    posted_date=letting_date,
                    awarded_vendor=low_vendor,
                    award_amount=int(round(low_amount)),
                    linked_ref=labels.get("fin prj no") or None,
                    award_linkage="ref" if labels.get("fin prj no") else None,
                    description=description,
                    raw={"letting": {
                        "district": district,
                        "letting_id": labels.get("letting_id"),
                        "labels": labels,
                        "bidders": [[n, a] for n, a in bidders],
                    }},
                )
            )
        return out

    @staticmethod
    def _bidders_after(header) -> List[tuple]:
        """(name, amount) pairs between this contract header and the next."""
        out: List[tuple] = []
        for sib in header.find_all_next("div", class_="textLeft"):
            # Stop at the next contract's section.
            prev_header = sib.find_previous("div", id="contractHeader")
            if prev_header is not header:
                break
            name_el = sib.find("div", class_="vendorName")
            amount_el = sib.find("div", class_="bidTotal")
            if name_el is None or amount_el is None:
                continue
            name = re.sub(r"\s+", " ", name_el.get_text(" ", strip=True)).strip()
            m = _MONEY.search(amount_el.get_text(" ", strip=True))
            if not name or not m or name.upper() == "CONTRACTOR'S NAME":
                continue
            try:
                out.append((name, float(m.group(1).replace(",", ""))))
            except ValueError:
                continue
        return out
