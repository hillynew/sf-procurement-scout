"""Turning fingerprints into sources: what qualifies, and what must not."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "sources_from_fingerprints", ROOT / "scripts" / "sources_from_fingerprints.py"
)
mod = importlib.util.module_from_spec(_spec)
sys.modules["sources_from_fingerprints"] = mod
_spec.loader.exec_module(mod)


def _fp(**kw):
    row = {
        "entity_id": "mun-city-of-alachua",
        "name": "City of Alachua",
        "website": "https://www.cityofalachua.com",
        "platform": "civicplus",
        "portal_url": "https://www.cityofalachua.com/Bids.aspx",
        "checked_url": "https://www.cityofalachua.com/Bids.aspx",
        "note": "matched on procurement page",
        "also": [],
        "confidence": "strong",
    }
    row.update(kw)
    return row


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "registry").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mod, "CONFIG_DIR", Path("config"))
    monkeypatch.setattr(mod, "OUT", Path("config/sources.fingerprinted.yaml"))
    return tmp_path


def _write_fps(tmp_path, rows):
    path = tmp_path / "data" / "registry" / "fingerprints.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    return path


def _config(tmp_path, name, sources):
    (tmp_path / "config" / name).write_text(yaml.safe_dump({"sources": sources}))


# -- what becomes a source -------------------------------------------------


def test_a_strong_civicplus_match_becomes_a_live_source():
    cfg = mod.to_source(_fp())

    assert cfg["adapter"] == "civicplus"
    assert cfg["portal_url"] == "https://www.cityofalachua.com/Bids.aspx"
    assert cfg["county"] == "alachua"
    assert cfg["live_fetch"] is True


def test_a_bonfire_match_carries_its_tenant_host():
    cfg = mod.to_source(_fp(
        platform="bonfire",
        name="City of Tallahassee",
        portal_url="https://talgov.bonfirehub.com/portal/?tab=openOpportunities",
    ))
    assert cfg["bonfire_host"] == "talgov.bonfirehub.com"


def test_an_opengov_match_carries_its_tenant_code():
    cfg = mod.to_source(_fp(
        platform="opengov",
        name="Orange County",
        portal_url="https://procurement.opengov.com/portal/orangecountyfl",
    ))
    assert cfg["opengov_code"] == "orangecountyfl"


def test_a_bonfire_row_without_a_resolvable_host_is_dropped():
    """Better no source than one the adapter will fail on every run."""
    assert mod.to_source(_fp(platform="bonfire", portal_url="https://city.gov/bids")) is None


def test_a_platform_with_no_adapter_yields_nothing():
    assert mod.to_source(_fp(platform="demandstar")) is None


# -- what must not become a source -----------------------------------------


def test_a_weak_match_is_never_configured(workspace, capsys):
    """"We post on DemandStar" is a lead. Configuring it would invent coverage."""
    _write_fps(workspace, [_fp(platform="civicplus", confidence="weak")])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    out = capsys.readouterr().out
    assert "candidates on a platform we can fetch: 0" in out
    assert "weak match" in out


def test_an_unknown_platform_is_skipped(workspace, capsys):
    _write_fps(workspace, [_fp(platform="unknown", portal_url=None, confidence="none")])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    assert "candidates on a platform we can fetch: 0" in capsys.readouterr().out


def test_an_already_configured_host_is_not_duplicated(workspace, capsys):
    _config(workspace, "sources.yaml", [{
        "id": "alachua_hand", "name": "Alachua", "county": "alachua", "agency": "City of Alachua",
        "adapter": "civicplus", "portal_url": "https://www.cityofalachua.com/Bids.aspx",
    }])
    _write_fps(workspace, [_fp()])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    out = capsys.readouterr().out
    assert "already configured (host)" in out
    assert "candidates on a platform we can fetch: 0" in out


def test_two_fingerprints_of_one_portal_yield_one_source(workspace, capsys):
    """Consolidated city-counties appear twice in the roster under both names."""
    _write_fps(workspace, [
        _fp(entity_id="mun-x", name="City of Alachua"),
        _fp(entity_id="co-x", name="Alachua County"),
    ])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    assert "candidates on a platform we can fetch: 1" in capsys.readouterr().out


def test_the_generated_file_is_not_read_as_prior_art(workspace):
    """The output lands in the directory it scans; counting it would empty it."""
    _config(workspace, "sources.fingerprinted.yaml", [{
        "id": "fp_mun_city_of_alachua", "name": "prev", "county": "alachua",
        "agency": "City of Alachua", "adapter": "civicplus",
        "portal_url": "https://www.cityofalachua.com/Bids.aspx",
    }])
    ids, hosts = mod.existing()

    assert "fp_mun_city_of_alachua" not in ids
    assert "www.cityofalachua.com" not in hosts


# -- the probe -------------------------------------------------------------


def test_a_candidate_that_cannot_be_fetched_is_dropped(monkeypatch):
    """A signature proves the platform, not that the board is readable."""
    class _Dead:
        def __init__(self, cfg):
            pass

        def fetch(self):
            raise RuntimeError("pointer page, no rows")

    class _Live:
        def __init__(self, cfg):
            pass

        def fetch(self):
            return [1, 2]

    import src.sources.registry as reg
    monkeypatch.setitem(reg.ADAPTERS, "civicplus", _Dead)

    assert mod.probe([mod.to_source(_fp())]) == []

    monkeypatch.setitem(reg.ADAPTERS, "civicplus", _Live)
    assert len(mod.probe([mod.to_source(_fp())])) == 1


def test_a_plaintext_portal_is_upgraded_to_https():
    """A configured source must never fetch a bid board over http."""
    cfg = mod.to_source(_fp(portal_url="http://www.coab.us/Bids.aspx"))

    assert cfg["portal_url"] == "https://www.coab.us/Bids.aspx"


def test_every_generated_source_satisfies_the_shipped_config_invariants():
    """The same checks tests/test_store_and_registry.py applies to config/."""
    from src.fl_geo import COUNTY_NAMES, PSEUDO_COUNTIES

    valid = set(COUNTY_NAMES) | set(PSEUDO_COUNTIES) | {"florida"}
    path = ROOT / "config" / "sources.fingerprinted.yaml"
    if not path.exists():
        pytest.skip("no fingerprinted config generated yet")

    for cfg in (yaml.safe_load(path.read_text()) or {}).get("sources") or []:
        assert cfg["portal_url"].startswith("https://"), cfg["id"]
        assert cfg["county"] in valid, f"{cfg['id']}: {cfg['county']}"
        assert cfg["adapter"] in {"civicplus", "bonfire", "opengov"}, cfg["id"]
