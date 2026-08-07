"""The registry seeder: what it emits, what it skips, and that it is idempotent."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "seed_from_registry", ROOT / "scripts" / "seed_from_registry.py"
)
seed = importlib.util.module_from_spec(_spec)
sys.modules["seed_from_registry"] = seed
_spec.loader.exec_module(seed)


FIELDS = [
    "source_id", "entity_id", "name", "tier", "county", "platform",
    "portal_url", "api_url", "adapter", "docs_anon", "live_fetch",
    "confidence", "notes",
]


def _row(**kw):
    base = {f: "" for f in FIELDS}
    base.update(
        {
            "name": "City of Tallahassee",
            "tier": "municipality",
            "county": "leon",
            "platform": "bonfire",
            "portal_url": "https://talgov.bonfirehub.com/portal/",
            "adapter": "bonfire",
            "live_fetch": "true",
            "confidence": "verified",
        }
    )
    base.update(kw)
    return base


@pytest.fixture
def registry_dir(tmp_path, monkeypatch):
    """Run the seeder against a throwaway config/ so the repo's own is untouched."""
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_config(tmp_path, name, sources):
    (tmp_path / "config" / name).write_text(yaml.safe_dump({"sources": sources}))


def _run(tmp_path, rows, out_name="sources.registry.yaml"):
    out = tmp_path / "config" / out_name
    fresh, skipped = seed.build(rows, out)
    out.write_text(seed.HEADER + yaml.safe_dump({"sources": fresh}, sort_keys=False))
    return fresh, skipped


def test_a_bonfire_row_becomes_a_live_source(registry_dir):
    fresh, _ = _run(registry_dir, [_row()])

    (src,) = fresh
    assert src["id"] == "bf_talgov"
    assert src["adapter"] == "bonfire"
    assert src["bonfire_host"] == "talgov.bonfirehub.com"
    assert src["county"] == "leon"
    assert src["live_fetch"] is True


def test_an_already_configured_tenant_is_not_duplicated(registry_dir):
    _write_config(
        registry_dir,
        "sources.yaml",
        [{"id": "talgov_hand", "name": "Tallahassee", "county": "leon", "agency": "T",
          "adapter": "bonfire", "bonfire_host": "talgov.bonfirehub.com",
          "portal_url": "https://talgov.bonfirehub.com/portal/"}],
    )
    fresh, skipped = _run(registry_dir, [_row()])

    assert fresh == []
    assert skipped["bonfire (already configured)"] == 1


def test_the_seeder_does_not_eat_its_own_output(registry_dir):
    """Re-running must be idempotent, not subtractive.

    The generator's output lands in the same config/ directory it reads to
    decide what already exists. Counting its own file as prior art makes the
    second run emit nothing and overwrite the first run's sources with an
    empty list — a silent loss of every source it had added.
    """
    rows = [_row()]
    first, _ = _run(registry_dir, rows)
    second, _ = _run(registry_dir, rows)

    assert [s["id"] for s in first] == ["bf_talgov"]
    assert [s["id"] for s in second] == ["bf_talgov"]

    written = yaml.safe_load((registry_dir / "config" / "sources.registry.yaml").read_text())
    assert [s["id"] for s in written["sources"]] == ["bf_talgov"]


def test_a_platform_with_no_adapter_is_reported_not_dropped(registry_dir):
    rows = [
        _row(platform="planetbids", adapter="planetbids", name="Bradford County"),
        _row(platform="peoplesoft", adapter="peoplesoft", name="City of St. Petersburg"),
    ]
    fresh, skipped = _run(registry_dir, rows)

    assert fresh == []
    assert skipped["planetbids (no planetbids adapter)"] == 1
    assert skipped["peoplesoft (no peoplesoft adapter)"] == 1


def test_a_platform_that_gains_an_adapter_stops_being_reported_as_missing(registry_dir):
    """This test used to name vendor_registry as its example of "no adapter".

    Building one moved those rows into the hand-configured bucket, which is the
    right answer — the registry's three Vendor Registry rows are archive
    sources with buyer GUIDs the CSV does not carry, so re-emitting them would
    write config the adapter cannot use.
    """
    rows = [_row(platform="vendor_registry", adapter="vendor_registry",
                 name="Okeechobee County"),
            _row(platform="jaggaer", adapter="jaggaer",
                 name="Florida State University")]
    fresh, skipped = _run(registry_dir, rows)

    assert fresh == []
    assert skipped["vendor_registry (already configured by hand)"] == 1
    assert skipped["jaggaer (already configured by hand)"] == 1


def test_opengov_rows_defer_to_the_native_discovery_file(registry_dir):
    """The platform's own directory is fresher than a CSV snapshot of it."""
    rows = [_row(platform="opengov", adapter="opengov", name="Orange County")]
    fresh, skipped = _run(registry_dir, rows)

    assert fresh == []
    assert skipped["opengov (covered by native discovery)"] == 1


def test_the_repos_adapter_names_are_translated(registry_dir):
    """The research named platforms from outside; the repo named them as built."""
    assert seed.ADAPTER_ALIASES["vip"] == "mfmp_vbs"

    rows = [_row(platform="mfmp_vip", adapter="vip", name="MyFloridaMarketPlace")]
    _, skipped = _run(registry_dir, rows)

    # Recognised as one we ship, then skipped as hand-configured — not as a gap.
    assert skipped["mfmp_vip (already configured by hand)"] == 1


def test_an_unparseable_portal_url_is_counted(registry_dir):
    rows = [_row(portal_url="https://example.gov/bids")]
    fresh, skipped = _run(registry_dir, rows)

    assert fresh == []
    assert skipped["bonfire (no subdomain in portal_url)"] == 1


def test_county_falls_back_to_inference_when_the_registry_has_none(registry_dir):
    fresh, _ = _run(registry_dir, [_row(county="", name="Monroe County")])

    assert fresh[0]["county"] == "monroe"


def test_the_shipped_registry_parses_and_matches_its_documented_size():
    rows = list(csv.DictReader((ROOT / "data/registry/fl_procurement_sources.csv").open()))
    agencies = list(csv.DictReader((ROOT / "data/registry/fl_agencies.csv").open()))

    assert len(rows) == 133
    assert len(agencies) == 2817
    assert {r["platform"] for r in rows} >= {"opengov", "bonfire", "mfmp_vip"}
