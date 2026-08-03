#!/usr/bin/env python3
"""Enumerate Florida public purchasing agencies and write them to source config.

Going statewide is not a scraping problem so much as a *census* problem: before
you can pull bids from every agency in Florida you have to know they exist and
which platform each one posts on. There is no master list — so this script
builds one from the directories that are public, and probes for the rest.

Four discovery channels, in descending order of reliability:

1. **Public Purchase** publishes a per-state agency directory that needs no
   login (``getAgenciesByRegion``). It is the single best census of Florida
   purchasing entities anywhere — 228 agencies with their own portals.
2. **BidNet Direct** publishes the Florida Purchasing Group's participating
   buyers.
3. **MyFloridaMarketPlace** publishes its posting-organization picklist, which
   is every state agency, university, college and water management district.
4. **Bonfire** publishes no directory at all, so tenants have to be probed.
   Candidates are generated from the place names in :mod:`src.fl_geo` rather
   than guessed by hand, which is what makes the sweep worth running.

Nothing here is scraped from a portal that forbids it — see ``docs/`` for the
per-platform access posture. DemandStar is deliberately absent: its terms of use
prohibit automated collection, so it is reached through a paid subscription and
the bid mailbox instead.

Usage::

    python scripts/discover_fl_agencies.py --all
    python scripts/discover_fl_agencies.py --bonfire --workers 16
    python scripts/discover_fl_agencies.py --all --out config/sources.florida.yaml
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import re
import sys
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.fl_geo import CITY_COUNTY, COUNTY_NAMES, infer_county  # noqa: E402

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

PUBLIC_PURCHASE_DIR = (
    "https://www1.publicpurchase.com/gems/lynx,fl/global/home"
    "/getAgenciesByRegion?region=FL"
)
BIDNET_BUYERS = "https://www.bidnetdirect.com/florida/participating-buyers"
MFMP_ORGS = "https://vendor.myfloridamarketplace.com/mfmp/pub/search/picklistOrg"
BONFIRE_API = (
    "https://{host}.bonfirehub.com/PublicPortal/getOpenPublicOpportunitiesSectionData"
)

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# 1. Public Purchase — the best census of Florida purchasing entities
# ---------------------------------------------------------------------------

def discover_public_purchase() -> List[Dict]:
    """Agencies with their own Public Purchase portal.

    Bids themselves sit behind a free vendor login, so these land as catalog
    entries: the scout knows the agency exists and where to register, and the
    solicitations arrive through the bid mailbox rather than a scrape.
    """
    log("Public Purchase: fetching Florida directory…")
    try:
        html = requests.get(PUBLIC_PURCHASE_DIR, headers=HEADERS, timeout=45).text
    except Exception as e:  # noqa: BLE001
        log(f"  ! failed: {e}")
        return []

    seen: Set[str] = set()
    out: List[Dict] = []
    for slug, name in re.findall(
        r'/gems/([^,"]+),fl/buyer/public/home"[^>]*>([^<]+)</a>', html
    ):
        name = _clean(name)
        if not name or slug in seen or "@" in name:
            continue
        seen.add(slug)
        out.append(
            {
                "id": f"pp_{_slugify(slug)}",
                "name": f"{name} (Public Purchase)",
                "county": infer_county(name),
                "agency": name,
                "live_fetch": False,
                "adapter": "catalog",
                "platform": "public_purchase",
                "portal_url": (
                    f"https://www1.publicpurchase.com/gems/{slug},fl/buyer/public/home"
                ),
                "register_url": "https://www.publicpurchase.com/gems/register/vendor/register",
                "access_note": (
                    "Open bids require a free vendor login; notices arrive by email."
                ),
            }
        )
    log(f"  found {len(out)} agencies")
    return out


# ---------------------------------------------------------------------------
# 2. BidNet Direct — Florida Purchasing Group participating buyers
# ---------------------------------------------------------------------------

def discover_bidnet() -> List[Dict]:
    """Florida Purchasing Group participating buyers — first page only.

    BidNet paginates through a stateful POST form rather than a URL, and its
    robots.txt disallows crawling paged variants, so this deliberately takes
    only the first page and says so. That is a real coverage limit, not a
    complete census: the sanctioned way to see every buyer in the group is the
    free vendor account, whose notices land in the bid mailbox.
    """
    log("BidNet Direct: fetching Florida participating buyers…")
    try:
        html = requests.get(BIDNET_BUYERS, headers=HEADERS, timeout=45).text
    except Exception as e:  # noqa: BLE001
        log(f"  ! failed: {e}")
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    names = [
        _clean(el.get_text(" ", strip=True))
        for el in soup.select(".participatingAgencyGridName")
    ]
    names = [n for n in names if 3 < len(n) < 120]

    seen: Set[str] = set()
    out: List[Dict] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "id": f"bidnet_{_slugify(name)[:40]}",
                "name": f"{name} (BidNet Direct)",
                "county": infer_county(name),
                "agency": name,
                "live_fetch": False,
                "adapter": "catalog",
                "platform": "bidnet",
                "portal_url": "https://www.bidnetdirect.com/florida",
                "register_url": (
                    "https://www.bidnetdirect.com/florida"
                    "?purchasingGroupId=8408751"
                ),
                "access_note": (
                    "Covered live by the florida_purchasing_group source; listed "
                    "here so the agency shows in coverage reporting."
                ),
            }
        )
    log(
        f"  found {len(out)} buyers (first page only — BidNet paginates by POST "
        "and disallows crawling paged URLs; the rest arrive via the vendor account)"
    )
    return out


# ---------------------------------------------------------------------------
# 3. MyFloridaMarketPlace posting organizations
# ---------------------------------------------------------------------------

def discover_mfmp_orgs() -> List[Dict]:
    """State posting organizations.

    These are already covered wholesale by the ``mfmp_vbs`` adapter, so they are
    emitted as reference rows rather than sources — useful for showing which
    state bodies the scout actually reaches.
    """
    log("MyFloridaMarketPlace: fetching posting organizations…")
    try:
        orgs = requests.get(
            MFMP_ORGS,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=45,
        ).json()
    except Exception as e:  # noqa: BLE001
        log(f"  ! failed: {e}")
        return []
    out = [
        {"id": str(o.get("id")), "agency": _clean(o.get("value", "")),
         "county": infer_county(_clean(o.get("value", "")))}
        for o in orgs
        if isinstance(o, dict) and o.get("value")
    ]
    log(f"  found {len(out)} organizations")
    return out


# ---------------------------------------------------------------------------
# 4. Bonfire — no directory, so probe generated candidates
# ---------------------------------------------------------------------------

def bonfire_candidates() -> List[str]:
    """Plausible Bonfire subdomains for Florida agencies.

    Generated from the place names already curated in :mod:`src.fl_geo` and the
    naming conventions Bonfire tenants actually use (``ocoee``,
    ``hillsboroughcounty``, ``pascocountyfl``), rather than a hand-written list.
    """
    out: Set[str] = set()

    def add(base: str) -> None:
        b = re.sub(r"[^a-z0-9]", "", base.lower())
        if len(b) < 3:
            return
        out.update({b, f"cityof{b}", f"{b}fl"})

    for county in COUNTY_NAMES.values():
        c = re.sub(r"[^a-z0-9]", "", county.lower())
        if len(c) < 3:
            continue
        out.update({
            c, f"{c}county", f"{c}countyfl", f"{c}fl",
            f"{c}schools", f"{c}countyschools",
        })

    for city in CITY_COUNTY:
        add(city)

    # Universities, colleges and authorities that follow no place-name pattern.
    out.update({
        "fau", "fiu", "fsu", "usf", "ucf", "uf", "unf", "uwf", "fgcu", "famu",
        "floridapoly", "newcollege", "valenciacollege", "santafecollege",
        "browardcollege", "miamidadecollege", "polkstate", "sfcollege",
        "daytonastate", "eastern florida", "indianriverstate", "pensacolastate",
        "tri-rail", "psta", "hart", "lynx", "votran", "jta", "sunrail",
        "jea", "opd", "swfwmd", "sjrwmd", "sfwmd", "nwfwater", "srwmd",
        "portmiami", "porteverglades", "porttampabay", "portcanaveral",
        "cfxway", "floridasturnpike", "spacecoast", "solidwasteauthority",
    })
    return sorted(out)


def probe_bonfire(hosts: Iterable[str], workers: int = 12) -> List[Dict]:
    hosts = list(hosts)
    log(f"Bonfire: probing {len(hosts)} candidate subdomains ({workers} workers)…")
    found: List[Dict] = []
    checked = 0

    def probe(host: str) -> Optional[Dict]:
        try:
            r = requests.get(
                BONFIRE_API.format(host=host),
                headers={**HEADERS, "Accept": "application/json"},
                timeout=12,
            )
            if r.status_code != 200:
                return None
            if not r.headers.get("content-type", "").startswith("application/json"):
                return None
            data = r.json()
            if not data.get("success"):
                return None
            projects = (data.get("payload") or {}).get("projects") or {}
            return {"host": host, "open": len(projects)}
        except Exception:  # noqa: BLE001 — a miss is the expected case here
            return None

    with futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for result in ex.map(probe, hosts):
            checked += 1
            if checked % 250 == 0:
                log(f"  …{checked}/{len(hosts)} probed, {len(found)} live")
            if result:
                found.append(result)
                log(f"  + {result['host']} ({result['open']} open)")

    out: List[Dict] = []
    for f in sorted(found, key=lambda x: -x["open"]):
        host = f["host"]
        agency = _bonfire_agency_name(host)
        out.append(
            {
                "id": f"bonfire_{_slugify(host)}",
                "name": f"{agency} (Bonfire)",
                "county": infer_county(agency),
                "agency": agency,
                "live_fetch": True,
                "adapter": "bonfire",
                "platform": "bonfire",
                "bonfire_host": f"{host}.bonfirehub.com",
                "portal_url": f"https://{host}.bonfirehub.com/portal/?tab=openOpportunities",
                "register_url": f"https://{host}.bonfirehub.com/",
                "discovered_open": f["open"],
            }
        )
    log(f"  {len(out)} live Bonfire tenants found")
    return out


def _bonfire_agency_name(host: str) -> str:
    """Turn a subdomain back into something a human recognises."""
    known = {
        "fau": "Florida Atlantic University", "fiu": "Florida International University",
        "fsu": "Florida State University", "usf": "University of South Florida",
        "ucf": "University of Central Florida", "uf": "University of Florida",
        "unf": "University of North Florida", "uwf": "University of West Florida",
        "fgcu": "Florida Gulf Coast University", "famu": "Florida A&M University",
        "floridapoly": "Florida Polytechnic University",
        "tri-rail": "South Florida Regional Transportation Authority",
        "psta": "Pinellas Suncoast Transit Authority",
        "hart": "Hillsborough Area Regional Transit",
        "lynx": "Central Florida Regional Transportation Authority (LYNX)",
        "jea": "JEA", "swfwmd": "Southwest Florida Water Management District",
        "sjrwmd": "St. Johns River Water Management District",
        "sfwmd": "South Florida Water Management District",
    }
    if host in known:
        return known[host]

    h = host.replace("-", " ")
    h = re.sub(r"^cityof", "City of ", h)
    h = re.sub(r"fl$", "", h)
    h = re.sub(r"countyschools$", " County Schools", h)
    h = re.sub(r"county$", " County", h)
    h = re.sub(r"schools$", " Schools", h)
    return re.sub(r"\s+", " ", h).strip().title().replace("City Of", "City of")


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_sources(entries: List[Dict], out_path: Path, existing: Path) -> None:
    """Write discovered entries, skipping ids the main config already defines."""
    known: Set[str] = set()
    known_hosts: Set[str] = set()
    if existing.exists():
        data = yaml.safe_load(existing.read_text(encoding="utf-8")) or {}
        for s in data.get("sources") or []:
            if isinstance(s, dict):
                known.add(s.get("id", ""))
                if s.get("bonfire_host"):
                    known_hosts.add(s["bonfire_host"])

    fresh = [
        e for e in entries
        if e["id"] not in known and e.get("bonfire_host") not in known_hosts
    ]

    header = (
        "# Florida statewide sources — GENERATED by scripts/discover_fl_agencies.py\n"
        "# Do not hand-edit: rerun the script instead. Entries already present in\n"
        "# config/sources.yaml are skipped, so the two files never collide.\n"
        "#\n"
        "# live_fetch: true  -> the adapter pulls solicitations directly\n"
        "# live_fetch: false -> catalog entry; bids arrive via the bid mailbox\n"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        header + yaml.safe_dump({"sources": fresh}, sort_keys=False, width=100),
        encoding="utf-8",
    )

    live = sum(1 for e in fresh if e.get("live_fetch"))
    counties = {e["county"] for e in fresh if e["county"] in COUNTY_NAMES}
    log("")
    log(f"Wrote {len(fresh)} new sources to {out_path}")
    log(f"  live-fetch: {live}   catalog: {len(fresh) - live}")
    log(f"  counties represented: {len(counties)}/67")
    log(f"  skipped (already configured): {len(entries) - len(fresh)}")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def _slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="run every discovery channel")
    ap.add_argument("--public-purchase", action="store_true")
    ap.add_argument("--bidnet", action="store_true")
    ap.add_argument("--mfmp", action="store_true")
    ap.add_argument("--bonfire", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=0, help="cap Bonfire probes (testing)")
    ap.add_argument("--out", default="config/sources.florida.yaml")
    ap.add_argument("--json-report", default="", help="also write a raw JSON report")
    args = ap.parse_args()

    if not any([args.all, args.public_purchase, args.bidnet, args.mfmp, args.bonfire]):
        ap.error("choose at least one channel, or --all")

    root = Path(__file__).resolve().parents[1]
    entries: List[Dict] = []
    report: Dict[str, object] = {}

    if args.all or args.public_purchase:
        pp = discover_public_purchase()
        entries += pp
        report["public_purchase"] = len(pp)

    if args.all or args.bidnet:
        bn = discover_bidnet()
        entries += bn
        report["bidnet"] = len(bn)

    if args.all or args.mfmp:
        orgs = discover_mfmp_orgs()
        report["mfmp_organizations"] = orgs

    if args.all or args.bonfire:
        cands = bonfire_candidates()
        if args.limit:
            cands = cands[: args.limit]
        bf = probe_bonfire(cands, workers=args.workers)
        entries += bf
        report["bonfire"] = len(bf)

    write_sources(entries, root / args.out, root / "config" / "sources.yaml")

    if args.json_report:
        Path(root / args.json_report).write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
