#!/usr/bin/env python3
"""Sweep the agency roster and record which procurement platform each one runs.

`data/registry/fl_agencies.csv` lists 2,817 Florida buying entities, 2,724 with
a website. `data/registry/fl_procurement_sources.csv` maps 133 of them to a
platform. This closes that gap by asking the other 2,600 directly.

The sweep is resumable and additive: results append to a JSONL file, and a
re-run skips entities already in it. That matters at this size — a run over the
whole state is thousands of requests, and losing it to one timeout would make
nobody want to run it twice.

Politeness is not this script's job; it is the HTTP layer's. Every fetch goes
through `src.netpolicy`, so robots.txt and the one-request-per-second-per-host
limit apply whether or not this script remembers them. Because these are ~2,700
*different* hosts, the limiter costs almost nothing here.

Usage::

    # A representative sample first — 200 entities is enough to see the shape.
    python scripts/fingerprint_agencies.py --limit 200 --tier county,municipality

    # The whole state, resumable; safe to interrupt and re-run.
    python scripts/fingerprint_agencies.py

    # What did we learn?
    python scripts/fingerprint_agencies.py --report
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.fingerprint import fingerprint_agency  # noqa: E402

ROSTER = Path("data/registry/fl_agencies.csv")
SOURCES = Path("data/registry/fl_procurement_sources.csv")
OUT = Path("data/registry/fingerprints.jsonl")

#: Concurrency is about sockets, not politeness — the per-host limiter handles
#: that. Kept modest so a sweep does not saturate a small container.
WORKERS = 12

_write_lock = threading.Lock()


def load_roster(path: Path) -> List[Dict]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def already_done(path: Path) -> set:
    if not path.exists():
        return set()
    done = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            done.add(json.loads(line)["entity_id"])
        except Exception:  # noqa: BLE001 — a torn last line is not fatal
            continue
    return done


def already_mapped(path: Path) -> set:
    """Entities the verified registry already places on a platform."""
    if not path.exists():
        return set()
    return {
        r["entity_id"]
        for r in csv.DictReader(path.open(encoding="utf-8"))
        if r.get("entity_id")
    }


def report(path: Path) -> int:
    if not path.exists():
        print(f"no results yet at {path}")
        return 1
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    platforms = Counter(r["platform"] for r in rows)
    print(f"{len(rows)} entities fingerprinted\n")
    print(f"{'platform':<22}{'count':>7}")
    for platform, n in platforms.most_common():
        print(f"{platform:<22}{n:>7}")

    identified = sum(n for p, n in platforms.items() if p != "unknown")
    print(f"\nidentified: {identified}/{len(rows)} ({identified * 100 // max(1, len(rows))}%)")

    print("\nwhy the rest came back unknown:")
    for note, n in Counter(r["note"] for r in rows if r["platform"] == "unknown").most_common(10):
        print(f"  {n:>5}  {note}")

    fresh = [r for r in rows if r["platform"] not in ("unknown",) and r.get("portal_url")]
    print(f"\nwith a usable portal URL: {len(fresh)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--roster", type=Path, default=ROSTER)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--limit", type=int, default=0, help="stop after N entities")
    ap.add_argument("--tier", default="", help="comma-separated tiers to include")
    ap.add_argument("--county", default="", help="comma-separated county slugs")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--redo", action="store_true", help="ignore previous results")
    ap.add_argument("--report", action="store_true", help="summarise and exit")
    args = ap.parse_args()

    if args.report:
        return report(args.out)

    if not args.roster.exists():
        print(f"roster not found: {args.roster}", file=sys.stderr)
        return 2

    roster = load_roster(args.roster)
    done = set() if args.redo else already_done(args.out)
    mapped = already_mapped(SOURCES)

    tiers = {t.strip() for t in args.tier.split(",") if t.strip()}
    counties = {c.strip() for c in args.county.split(",") if c.strip()}

    todo = []
    for row in roster:
        if not row.get("website", "").strip():
            continue
        if row["entity_id"] in done or row["entity_id"] in mapped:
            continue
        if tiers and row.get("tier") not in tiers:
            continue
        if counties and row.get("county") not in counties:
            continue
        todo.append(row)

    if args.limit:
        todo = todo[: args.limit]

    print(
        f"roster {len(roster)} · already verified {len(mapped)} · "
        f"already swept {len(done)} · to do now {len(todo)}"
    )
    if not todo:
        return report(args.out)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    counts: Counter = Counter()

    def run(row: Dict):
        return fingerprint_agency(row["entity_id"], row["name"], row["website"])

    with args.out.open("a", encoding="utf-8") as fh:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(run, row): row for row in todo}
            for i, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    fp = future.result()
                except Exception as e:  # noqa: BLE001 — one bad site is a row, not a stop
                    print(f"  !! {row['entity_id']}: {type(e).__name__}: {e}")
                    continue
                counts[fp.platform] += 1
                with _write_lock:
                    fh.write(json.dumps(fp.as_dict()) + "\n")
                    fh.flush()
                if fp.platform != "unknown":
                    print(f"  {fp.platform:<18} {fp.name[:46]}")
                if i % 50 == 0:
                    ident = sum(n for p, n in counts.items() if p != "unknown")
                    print(f"  ... {i}/{len(todo)} swept, {ident} identified")

    print("\nthis run:")
    for platform, n in counts.most_common():
        print(f"  {platform:<20}{n:>6}")
    print()
    return report(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
