#!/usr/bin/env python3
"""Find every Florida body on the Legistar Web API, by asking it.

There is no directory of Legistar clients, but the client slug is guessable
from the entity's name (`broward`, `fortlauderdale`, `polkcountyfl`) and the
API answers an existence probe cheaply: `/v1/{client}/bodies?$top=1` returns
JSON for a real client and an error page for anything else.

Three-step verification, because a name that resolves is not yet a source:

1. **Exists** — the bodies probe parses as JSON.
2. **Alive** — its newest matter was modified inside the last 18 months.
   Miami-Dade's instance resolves and is frozen at July 2018; a dead client
   configured live would be the quiet-agency failure all over again.
3. **Is actually Florida** — the client's own portal page
   (`https://{client}.legistar.com`) mentions Florida or the entity's name.
   Slugs collide across states; `columbus` is not ours.

Candidates: all 67 counties and the municipalities in `src.fl_geo`, each tried
under the slug patterns observed in the wild (bare, +fl, +county, +countyfl),
stopping at the first hit per entity. ~1 request/second, honest UA.

Usage:
    python scripts/discover_legistar.py             # probe and print
    python scripts/discover_legistar.py --write     # also append to config
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.fl_geo import CITY_COUNTY, COUNTY_NAMES  # noqa: E402

API = "https://webapi.legistar.com/v1"
UA = "sf-procurement-scout (github.com/hillynew/sf-procurement-scout)"
CONFIG = Path(__file__).resolve().parent.parent / "config" / "sources.legistar.yaml"

#: Newest matter must be younger than this to count as a live instance.
STALE_DAYS = 545  # ~18 months

_session = requests.Session()
_session.headers["User-Agent"] = UA


def _get(url: str, **params):
    time.sleep(1.0)
    try:
        return _session.get(url, params=params or None, timeout=20)
    except requests.RequestException:
        return None


def _slugs(name: str, *, is_county: bool) -> list[str]:
    base = re.sub(r"[^a-z]", "", name.lower())
    if is_county:
        return [base, f"{base}county", f"{base}countyfl", f"{base}fl"]
    return [base, f"{base}fl"]


def probe(client: str):
    """None if not a client; else the newest matter-modified ISO date ('' if none)."""
    resp = _get(f"{API}/{client}/bodies", **{"$top": "1"})
    if resp is None or resp.status_code != 200:
        return None
    try:
        rows = resp.json()
    except ValueError:
        return None
    if not isinstance(rows, list):
        return None
    resp = _get(
        f"{API}/{client}/matters",
        **{"$top": "1", "$orderby": "MatterLastModifiedUtc desc"},
    )
    if resp is None or resp.status_code != 200:
        return ""
    try:
        matters = resp.json()
    except ValueError:
        return ""
    if isinstance(matters, list) and matters:
        return str(matters[0].get("MatterLastModifiedUtc") or "")
    return ""


def is_florida(client: str, entity_name: str) -> bool:
    resp = _get(f"https://{client}.legistar.com")
    if resp is None or resp.status_code != 200:
        return False
    text = resp.text[:20000].lower()
    # The entity's own name proves nothing — every city's page carries it,
    # whichever state the city is in (this check shipped with a bare-name
    # fallback and configured Madison, Wisconsin). Florida must be named.
    return "florida" in text or ", fl" in text


def fresh(modified: str) -> bool:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", modified or "")
    if not m:
        return False
    import datetime as dt

    when = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return (dt.date.today() - when).days <= STALE_DAYS


def main() -> None:
    write = "--write" in sys.argv
    # --slice a-m limits the city sweep to a letter range so one run stays
    # inside a tool timeout; counties always run unless --cities-only.
    letter_range = None
    for arg in sys.argv[1:]:
        m = re.match(r"--slice=([a-z])-([a-z])$", arg)
        if m:
            letter_range = (m.group(1), m.group(2))
    counties_only = "--counties-only" in sys.argv
    cities_only = "--cities-only" in sys.argv

    existing: set[str] = set()
    if CONFIG.exists():
        data = yaml.safe_load(CONFIG.read_text()) or {}
        existing = {
            str(e.get("legistar_client"))
            for e in data.get("sources", [])
            if isinstance(e, dict) and e.get("legistar_client")
        }

    candidates: list[tuple[str, str, bool]] = []  # (entity, county_slug, is_county)
    if not cities_only:
        for slug, name in COUNTY_NAMES.items():
            candidates.append((f"{name} County", slug, True))
    if not counties_only:
        for city, county in CITY_COUNTY.items():
            if letter_range and not (letter_range[0] <= city[0].lower() <= letter_range[1]):
                continue
            candidates.append((city.title(), county, False))

    found, skipped_stale, checked = [], [], 0
    for entity, county, is_county in candidates:
        hit = None
        for slug in _slugs(entity, is_county=is_county):
            if slug in existing:
                hit = "configured"
                break
            checked += 1
            modified = probe(slug)
            if modified is None:
                continue
            if not fresh(modified):
                skipped_stale.append((slug, entity, modified[:10] or "no matters"))
                break
            if not is_florida(slug, entity):
                print(f"  ? {slug}: exists and is live but does not look like {entity} FL — skipped")
                break
            hit = slug
            break
        if hit and hit != "configured":
            print(f"  + {hit}: {entity} — live")
            found.append((hit, entity, county))

    print(f"\nprobed {checked} slugs · found {len(found)} new · "
          f"{len(skipped_stale)} stale instances skipped")
    for slug, entity, when in skipped_stale:
        print(f"  stale: {slug} ({entity}) last touched {when}")

    if not write or not found:
        if found:
            print("\nrun again with --write to append these to config")
        return

    data = yaml.safe_load(CONFIG.read_text()) or {"sources": []}
    for slug, entity, county in found:
        source_id = f"legistar_{slug}"
        data["sources"].append({
            "id": source_id,
            "name": f"{entity} commission awards",
            "county": county,
            "agency": entity,
            "live_fetch": True,
            "adapter": "legistar",
            "platform": "legistar",
            "legistar_client": slug,
            "portal_url": f"https://{slug}.legistar.com/Legislation.aspx",
        })
    CONFIG.write_text(
        CONFIG.read_text().split("sources:")[0]
        + yaml.safe_dump({"sources": data["sources"]}, sort_keys=False, width=100)
    )
    print(f"wrote {len(found)} entries to {CONFIG}")


if __name__ == "__main__":
    main()
