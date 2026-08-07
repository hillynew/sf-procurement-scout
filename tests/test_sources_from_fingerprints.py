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


# -- platforms that put every agency behind one hostname -------------------


def test_a_jaggaer_match_carries_its_customer_org():
    cfg = mod.to_source(_fp(
        platform="jaggaer", name="University of Florida",
        portal_url="https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=Florida",
    ))

    assert cfg["adapter"] == "jaggaer"
    assert cfg["jaggaer_org"] == "Florida"


def test_two_jaggaer_universities_are_two_sources(workspace, capsys):
    """The bug this table change exists for. Every Jaggaer tenant in Florida
    lives on `bids.sciquest.com`, so matching prior art on the host alone meant
    that once FSU was configured, every other university read as a duplicate —
    the University of Florida included, silently, with no line in the report.
    """
    _config(workspace, "sources.yaml", [{
        "id": "jaggaer_fsu", "name": "FSU", "county": "leon", "agency": "Florida State University",
        "adapter": "jaggaer", "platform": "jaggaer", "jaggaer_org": "FSU",
        "portal_url": "https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=FSU",
    }])
    _write_fps(workspace, [
        _fp(entity_id="uni-fsu", name="Florida State University", platform="jaggaer",
            portal_url="https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=FSU"),
        _fp(entity_id="uni-uf", name="University of Florida", platform="jaggaer",
            portal_url="https://bids.sciquest.com/apps/Router/PublicEvent?CustomerOrg=Florida"),
    ])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    out = capsys.readouterr().out
    assert "candidates on a platform we can fetch: 1" in out, "UF is new; FSU is not"
    assert "already configured (same tenant)" in out


def test_an_ionwave_match_carries_its_host():
    cfg = mod.to_source(_fp(
        platform="ionwave", name="Lee County",
        portal_url="https://leegov.ionwave.net/HomePage.aspx",
    ))

    assert cfg["ionwave_host"] == "leegov.ionwave.net"


def test_a_workday_match_is_pointed_at_the_public_portal():
    """The host a fingerprint lands on is the agency's registration page, on
    `<tenant>.us.workdayspend.com` — the authenticated app, which serves
    `Disallow: /`. Configuring that URL would point a crawler at a host we are
    not allowed to read; the tenant is the same, the host is not.
    """
    cfg = mod.to_source(_fp(
        platform="workday_sourcing", name="Hillsborough Community College",
        portal_url="https://hillsborough-community-college.us.workdayspend.com/supplier_self_registration",
    ))

    assert cfg["workday_tenant"] == "hillsborough-community-college"
    assert cfg["portal_url"] == (
        "https://hillsborough-community-college.public-portal.us.workdayspend.com/opportunities"
    )


def test_a_workday_fingerprint_on_the_public_host_reads_the_same_tenant():
    cfg = mod.to_source(_fp(
        platform="workday_sourcing", name="UNF",
        portal_url="https://unf.public-portal.us.workdayspend.com/opportunities",
    ))

    assert cfg["workday_tenant"] == "unf"


def test_a_shared_host_row_that_names_no_tenant_is_dropped(workspace, capsys):
    """Not one of the 15 VendorLink fingerprints carried the agency id: they
    point at login pages, home pages, and in one case a JavaScript file. A
    signature proves the platform; it does not always name which agency, and
    there is nothing to configure without that."""
    assert mod.to_source(_fp(
        platform="jaggaer", portal_url="https://bids.sciquest.com/apps/Router/Login",
    )) is None


def test_the_platforms_with_their_own_discoverer_are_left_to_it(workspace, capsys):
    """VendorLink's agency ids come from the platform's own dropdown, which
    yields the key directly. Guessing at it from whatever page an agency
    happened to link is worse information about the same thing."""
    _write_fps(workspace, [_fp(platform="vendorlink",
                               portal_url="https://www.myvendorlink.com/external/home")])
    sys.argv = ["x", "--check", "--no-probe"]
    mod.main()

    out = capsys.readouterr().out
    assert "discover_vendorlink.py" in out
    assert "candidates on a platform we can fetch: 0" in out


def test_every_mapped_platform_has_an_adapter_that_exists():
    """The map said "no adapter in this build" for four platforms this build
    had already grown adapters for. A stale map is a silent gap."""
    from src.sources.registry import ADAPTERS

    for platform, (adapter, _key, _pattern) in mod.PLATFORM_ADAPTERS.items():
        assert adapter in ADAPTERS, f"{platform} -> {adapter}"


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
    assert "already configured (same tenant)" in out
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
        assert cfg["adapter"] in {a for a, _k, _p in mod.PLATFORM_ADAPTERS.values()}, cfg["id"]
