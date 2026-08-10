#!/usr/bin/env python3
"""Find a readable board for agencies parked on a platform whose terms forbid it.

`src/terms.py` keeps four platforms out of this build because their terms of
use prohibit automated reading — VendorLink, DemandStar, Vendor Registry, and
BidNet, whose terms cannot even be fetched. Their agencies are kept as
`catalog` pointers so the gap shows in the app as "this agency posts there, go
look" rather than as silence.

A pointer is not the end of the story, though, and this script is the part
nobody had run. **Most of these agencies post the same solicitation in more
than one place.** A city that advertises VendorLink on its purchasing page very
often also keeps a CivicPlus board at `/Bids.aspx`; a school district on
VendorLink may have moved to Bonfire last year and left the old link up. The
original sweep never found those, and could not have: `fingerprint_agency`
stops at the first strong signature, so the moment a page said VendorLink the
question was considered answered.

So this asks a narrower question than the sweep does — *not* "what does this
agency run" but "does this agency also run something we are allowed to read" —
and it asks it with `avoid`, which makes a forbidden platform a match that does
not stop the search. What it finds is written back as an ordinary fingerprint,
carrying the forbidden platform in `also` so the double-posting stays on the
record, and `scripts/sources_from_fingerprints.py` turns those into live
sources under the rules it already enforces.

Nothing here reads a forbidden platform. Every fetch goes to the agency's own
website, which is `AGENCY_SITE` in the terms table — the publisher is the
government body and what is posted is a public record it must publish.

Usage::

    python scripts/recover_catalog_coverage.py --check     # resolve only, no fetches
    python scripts/recover_catalog_coverage.py             # sweep and record
    python scripts/recover_catalog_coverage.py --platform vendorlink
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.fingerprint import fingerprint_agency  # noqa: E402
from src.terms import FORBIDS_ADAPTER, GRANDFATHERED, TERMS  # noqa: E402

ROSTER = Path("data/registry/fl_agencies.csv")
FINGERPRINTS = Path("data/registry/fingerprints.jsonl")
CONFIG_DIR = Path("config")

#: Same reasoning as the main sweep: concurrency is about sockets, not
#: politeness. `src.netpolicy` holds the per-host limit, and these are ~60
#: different hosts.
WORKERS = 8

_write_lock = threading.Lock()

#: Verdicts that close no gap. `unknown` is a site we could not read; the
#: avoided platforms are where we already knew the agency posts.
_NO_GAIN = frozenset({"unknown"})


# -- resolving a catalog entry to the agency's own website -------------------
#
# The catalog carries the *platform's* name for a buyer — "Brevard County Board
# of County Commissioners", "Volusia County School Board Procurement" — and the
# roster carries the state's — "Brevard County", "Volusia County School
# District". Neither is wrong; they are different registries. These rules turn
# one into the other, and they are rules rather than a lookup table because the
# same four shapes cover 48 of the 66 VendorLink entries.

#: Buying *departments* the platform lists separately. Two VendorLink boards for
#: one school district is a purchasing-office detail, not two agencies.
_DEPARTMENT_SUFFIX = re.compile(
    r"\s+(purchasing|procurement|facilities|housing and human services)"
    r"(\s+department)?$", re.I
)

_RULES: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bboard of county commissioners\b", re.I), "county"),
    (re.compile(r"\bbocc\b", re.I), "county"),
    (re.compile(r"\b(public schools|school board)\b", re.I), "school district"),
    (re.compile(r"\bcounty county\b", re.I), "county"),
)

#: A trailing state tag the platform adds and the registry does not:
#: "Highlands County FL".
_STATE_TAG = re.compile(r",?\s+(fl|fla|florida)$", re.I)


def normalise(name: str) -> str:
    n = name.strip().replace("’", "'")
    n = _STATE_TAG.sub("", n)
    n = _DEPARTMENT_SUFFIX.sub("", n)
    for pattern, repl in _RULES:
        n = pattern.sub(repl, n)
    n = re.sub(r",?\s+inc\.?$", "", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip().lower()


#: Municipal classes Florida writes as a prefix and platforms often write as a
#: suffix: "Bal Harbour Village" is the registry's "Village of Bal Harbour".
_CLASSES = ("village", "town", "city")


def variants(name: str) -> List[str]:
    """Every spelling worth trying against the registry, best first.

    Kept as a generated list rather than an alias table because each of these
    rules earns its place across several agencies — the alias table is for the
    ones no rule reaches.
    """
    base = normalise(name)
    out = [base, name.strip().lower()]
    for cls in _CLASSES:
        if base.endswith(f" {cls}"):
            out.append(f"{cls} of {base[: -len(cls) - 1]}")
    # "Central Florida Expressway" is the registry's "... Expressway Authority".
    # Only ever an addition, so it cannot collapse two real agencies into one.
    if not base.endswith(("authority", "district", "county")):
        out.append(f"{base} authority")
    seen, ordered = set(), []
    for v in out:
        if v and v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


#: Bodies the platform lists under a name the state registry does not use at
#: all. Each maps to a roster `entity_id`, so the website still comes from the
#: roster rather than from here — this table decides *which* agency, never
#: where it lives.
ALIASES: Dict[str, str] = {
    "canaveral port authority": "sd-canaveral-port-district",
    "melbourne orlando international airport": "sd-melbourne-airport-authority",
    "city of new smyrna beach utilities commission": "mun-city-of-new-smyrna-beach",
}


def load_roster(path: Path = ROSTER) -> Tuple[Dict[str, Dict], Dict[str, Dict]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    by_id = {r["entity_id"]: r for r in rows}
    by_name: Dict[str, Dict] = {}
    for r in rows:
        by_name.setdefault(r["name"].strip().lower(), r)
    return by_id, by_name


def resolve(agency: str, by_id: Dict, by_name: Dict) -> Optional[Dict]:
    """The roster row for a catalog agency, or None when the state has no such
    entity — which is the honest answer for an electric cooperative or a
    chamber of commerce, neither of which is a government body."""
    for name in variants(agency):
        if name in ALIASES:
            return by_id.get(ALIASES[name])
        if name in by_name:
            return by_name[name]
    return None


# -- what the build already reads for an agency -----------------------------

#: Adapters that yield *open solicitations*. An agency covered by one of these
#: has no gap to close. Deliberately excludes `legistar`, `fdot_letting` and the
#: Miami-Dade award readers: those publish what was already decided, which is
#: useful intelligence and no help at all in finding something to bid on.
BID_ADAPTERS = frozenset({
    "civicplus", "bonfire", "opengov", "ionwave", "jaggaer", "workday_sourcing",
    "mfmp_vbs", "fdot_ads", "sam_gov", "miami_dade_informs",
    "miami_dade_construction", "miami_dade_future", "west_palm_beach",
    "mdc_college", "palm_beach_schools", "notice_links", "email_alerts",
})


def configured_agencies() -> Dict[str, List[str]]:
    """Lower-cased agency name -> the live bid adapters already reading it."""
    out: Dict[str, List[str]] = {}
    for path in sorted(CONFIG_DIR.glob("sources*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for cfg in data.get("sources") or []:
            if not isinstance(cfg, dict) or not cfg.get("live_fetch"):
                continue
            if cfg.get("adapter") not in BID_ADAPTERS:
                continue
            who = (cfg.get("agency") or cfg.get("name") or "").strip().lower()
            if who:
                out.setdefault(who, []).append(cfg["adapter"])
    return out


def forbidden_platforms() -> set:
    """The platforms this sweep looks past, straight from the terms table.

    Derived rather than listed. A hand-kept copy would drift, and the direction
    it drifts is a platform quietly becoming readable.

    Grandfathered platforms are excluded: `jaggaer` is UNREADABLE and still has
    an adapter, so its agencies are already read and there is no gap here to
    close. That is debt recorded in `src/terms.py`, not this script's to pay.
    """
    return {
        p for p, v in TERMS.items()
        if v.status in FORBIDS_ADAPTER and p not in GRANDFATHERED
    }


def catalog_entries(platforms: set) -> List[Dict]:
    """Catalog pointers for the platforms in question, across every config."""
    out = []
    for path in sorted(CONFIG_DIR.glob("sources*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for cfg in data.get("sources") or []:
            if not isinstance(cfg, dict):
                continue
            if cfg.get("adapter") == "catalog" and cfg.get("platform") in platforms:
                out.append(cfg)
    return out


def append(path: Path, payload: Dict) -> None:
    with _write_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--platform", action="append",
        help="restrict to one catalog platform (default: every platform whose "
             "terms forbid an adapter)",
    )
    ap.add_argument("--out", type=Path, default=FINGERPRINTS)
    ap.add_argument("--check", action="store_true",
                    help="resolve and report only; fetch nothing")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()

    platforms = set(args.platform) if args.platform else forbidden_platforms()
    unknown = platforms - set(TERMS)
    if unknown:
        print(f"no terms verdict for: {sorted(unknown)}")
        return 1

    entries = catalog_entries(platforms)
    if not entries:
        print(f"no catalog entries for {sorted(platforms)}")
        return 1

    by_id, by_name = load_roster()
    covered = configured_agencies()

    #: entity_id -> (roster row, the catalog entries that resolved to it). Two
    #: catalog boards for one agency is one website to read, not two.
    targets: Dict[str, Tuple[Dict, List[Dict]]] = {}
    already: List[Tuple[Dict, List[str]]] = []
    unresolved: List[Dict] = []

    for cfg in entries:
        agency = cfg.get("agency") or cfg.get("name") or ""
        live = covered.get(agency.strip().lower())
        if live:
            already.append((cfg, live))
            continue
        row = resolve(agency, by_id, by_name)
        if not row or not (row.get("website") or "").strip():
            unresolved.append(cfg)
            continue
        entry = targets.setdefault(row["entity_id"], (row, []))
        entry[1].append(cfg)

    print(f"catalog entries on {sorted(platforms)}: {len(entries)}")
    print(f"  already read live by a bid adapter : {len(already)}")
    print(f"  no roster entity / no website      : {len(unresolved)}")
    print(f"  agencies to re-read                : {len(targets)}")

    if already:
        print("\nalready covered — the pointer is redundant:")
        for cfg, adapters in sorted(already, key=lambda t: t[0]["id"]):
            print(f"  {cfg['id']:<8} {cfg.get('agency','')[:48]:<48} {','.join(sorted(set(adapters)))}")

    if unresolved:
        print("\nnot in the state roster (no website to read):")
        for cfg in sorted(unresolved, key=lambda c: c["id"]):
            print(f"  {cfg['id']:<8} {cfg.get('agency','')}")

    if args.check:
        return 0

    print(f"\nre-reading {len(targets)} agency websites, looking past {sorted(platforms)}:")
    avoid = frozenset(platforms)
    found: List = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                fingerprint_agency,
                row["entity_id"], row["name"], row["website"],
                timeout=args.timeout, avoid=avoid,
            ): row
            for row, _cfgs in targets.values()
        }
        for future in as_completed(futures):
            row = futures[future]
            try:
                fp = future.result()
            except Exception as e:  # noqa: BLE001 — a failure is a result
                print(f"  !! {row['name'][:44]:<46} {type(e).__name__}")
                continue
            fp.note = f"catalog recovery: {fp.note}" if fp.note else "catalog recovery"
            append(args.out, fp.as_dict())
            found.append(fp)
            mark = "->" if fp.platform not in _NO_GAIN | avoid else "  "
            print(f"  {mark} {fp.name[:42]:<44} {fp.platform:<14} {fp.confidence:<8} {fp.note[:38]}")

    report(found, avoid)
    print(f"\nappended to {args.out}")
    print("next: python scripts/sources_from_fingerprints.py --check")
    return 0


def report(found: List, avoid: frozenset) -> None:
    """Sort the sweep's answers by what can actually be done with each.

    "Found a different platform" and "closed a coverage gap" are not the same
    claim, and reporting the first as the second is how a survey starts
    overstating itself. A city that turns out to run BidSync is a real finding
    and buys nothing today: there is no adapter for it, and no terms verdict
    either, so it is a lead for whoever picks the next platform to support.
    """
    from src.sources.registry import ADAPTERS
    from src.terms import GRANDFATHERED, may_build_adapter

    live, leads, stuck, unread = [], [], [], []
    for f in found:
        if f.platform == "unknown":
            unread.append(f)
        elif f.platform in avoid:
            stuck.append(f)
        elif f.platform == "selfhosted":
            leads.append(f)
        elif f.platform in ADAPTERS and (
            may_build_adapter(f.platform) or f.platform in GRANDFATHERED
        ):
            live.append(f)
        else:
            leads.append(f)

    print(f"\n{len(found)} agencies re-read:")
    print(f"  readable now — adapter exists, terms allow : {len(live)}")
    print(f"  a lead — no adapter, or needs a page reader: {len(leads)}")
    print(f"  nothing but the platform we cannot read    : {len(stuck)}")
    print(f"  site unreadable (WAF, timeout, JS shell)   : {len(unread)}")

    if live:
        print(f"\nreadable now  {dict(Counter(f.platform for f in live))}")
        for f in sorted(live, key=lambda f: f.name):
            print(f"  {f.name[:44]:<46} {f.platform:<12} {(f.portal_url or '')[:60]}")
    if leads:
        print(f"\nleads         {dict(Counter(f.platform for f in leads))}")
        for f in sorted(leads, key=lambda f: f.name):
            print(f"  {f.name[:44]:<46} {f.platform:<12} {(f.portal_url or '')[:60]}")


if __name__ == "__main__":
    raise SystemExit(main())
