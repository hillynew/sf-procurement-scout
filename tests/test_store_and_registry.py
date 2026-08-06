"""Snapshot persistence, retention, and source-config loading."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
import yaml

from src.models.opportunity import HealthStatus, SourceHealth
from src.pipeline import store
from src.fl_geo import COUNTY_NAMES, PSEUDO_COUNTIES
from src.sources.registry import (
    ADAPTERS,
    _superseded_catalog_ids,
    get_adapters,
    load_source_config,
)


@pytest.fixture
def temp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def _health(**kw):
    base = dict(source_id="s1", name="Source One", ok=True, count=1)
    base.update(kw)
    return SourceHealth(**base)


def test_snapshot_round_trips(temp_data_dir, opp_factory, monkeypatch):
    opps = [opp_factory(due_date=datetime.now() + timedelta(days=3))]
    store.save_snapshot(opps, [_health()])

    monkeypatch.setattr(store, "data_dir", lambda: temp_data_dir)
    loaded, health = store.load_latest()
    assert len(loaded) == 1
    assert loaded[0].title == opps[0].title
    assert loaded[0].due_date == opps[0].due_date
    assert health[0].source_id == "s1"


def test_health_status_survives_the_round_trip(temp_data_dir, opp_factory):
    store.save_snapshot(
        [opp_factory()],
        [_health(status=HealthStatus.DEGRADED, ok=False, note="portal blocked")],
    )
    _, health = store.load_latest()
    assert health[0].status == HealthStatus.DEGRADED.value
    assert health[0].note == "portal blocked"


def test_missing_snapshot_returns_empty(temp_data_dir):
    assert store.load_latest() == ([], [])


def test_empty_result_set_still_writes_csv(temp_data_dir):
    store.save_snapshot([], [_health(count=0)])
    assert (temp_data_dir / "latest.csv").exists()
    assert json.loads((temp_data_dir / "latest.json").read_text())["count"] == 0


def test_old_snapshots_are_pruned(temp_data_dir, opp_factory):
    """Unbounded snapshot files used to fill the ephemeral disk on Render."""
    for i in range(15):
        (temp_data_dir / f"opportunities_2026010{i:02d}_000000.json").write_text("{}")
        (temp_data_dir / f"opportunities_2026010{i:02d}_000000.csv").write_text("")
        (temp_data_dir / f"health_2026010{i:02d}_000000.json").write_text("[]")

    store.prune_snapshots(keep=5)
    assert len(list(temp_data_dir.glob("opportunities_*.json"))) == 5
    assert len(list(temp_data_dir.glob("health_*.json"))) == 5


def test_pruning_keeps_the_newest(temp_data_dir):
    for stamp in ("20260101_000000", "20260601_000000", "20261201_000000"):
        (temp_data_dir / f"opportunities_{stamp}.json").write_text("{}")
    store.prune_snapshots(keep=1)
    remaining = [p.name for p in temp_data_dir.glob("opportunities_*.json")]
    assert remaining == ["opportunities_20261201_000000.json"]


def test_latest_files_are_never_pruned(temp_data_dir, opp_factory):
    store.save_snapshot([opp_factory()], [_health()], keep=1)
    store.save_snapshot([opp_factory()], [_health()], keep=1)
    assert (temp_data_dir / "latest.json").exists()
    assert (temp_data_dir / "latest.csv").exists()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_shipped_config_is_valid():
    configs = load_source_config()
    assert configs
    # Statewide coverage means county is now any of the 67, plus the buckets
    # for bodies that belong to no single county. Anything else is a typo that
    # would quietly hide a source from every county filter in the UI.
    valid_counties = set(COUNTY_NAMES) | set(PSEUDO_COUNTIES) | {"florida"}
    for cfg in configs:
        assert cfg["adapter"] in ADAPTERS, f"{cfg['id']} references an unknown adapter"
        assert cfg["county"] in valid_counties, (
            f"{cfg['id']} has unrecognised county {cfg['county']!r}"
        )
        assert cfg["portal_url"].startswith("https://")


def test_shipped_config_has_no_duplicate_ids():
    """Generated statewide entries must never collide with hand-tuned ones."""
    ids = [c["id"] for c in load_source_config()]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"duplicate source ids: {sorted(dupes)}"


def test_every_shipped_source_builds():
    """Every configured entry becomes an adapter, bar the superseded pointers."""
    configs = load_source_config()
    built = get_adapters(strict=True)
    assert len(built) == len(configs) - len(_superseded_catalog_ids(configs))


def test_a_catalog_pointer_yields_to_a_live_source_for_the_same_agency(tmp_path):
    """Otherwise "go register at this portal" sits next to that portal's bids."""
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "davie_pointer",
                        "name": "Town of Davie (Public Purchase)",
                        "county": "broward",
                        "agency": "Town of Davie",
                        "adapter": "catalog",
                        "live_fetch": False,
                        "portal_url": "https://publicpurchase.com/davie",
                    },
                    {
                        "id": "og_davie",
                        "name": "Davie (OpenGov)",
                        "county": "broward",
                        "agency": "Davie",
                        "adapter": "opengov",
                        "opengov_code": "davie-fl",
                        "portal_url": "https://procurement.opengov.com/portal/davie-fl",
                    },
                ]
            }
        )
    )
    assert [a.source_id for a in get_adapters(config_path=cfg)] == ["og_davie"]


def test_a_catalog_pointer_survives_when_nothing_else_covers_the_agency(tmp_path):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "lonely_pointer",
                        "name": "City of Nowhere (Public Purchase)",
                        "county": "broward",
                        "agency": "City of Nowhere",
                        "adapter": "catalog",
                        "live_fetch": False,
                        "portal_url": "https://publicpurchase.com/nowhere",
                    },
                    {
                        "id": "og_elsewhere",
                        "name": "Elsewhere (OpenGov)",
                        "county": "broward",
                        "agency": "City of Elsewhere",
                        "adapter": "opengov",
                        "opengov_code": "elsewhere",
                        "portal_url": "https://procurement.opengov.com/portal/elsewhere",
                    },
                ]
            }
        )
    )
    assert {a.source_id for a in get_adapters(config_path=cfg)} == {
        "lonely_pointer",
        "og_elsewhere",
    }


def test_a_disabled_live_source_does_not_supersede_its_pointer(tmp_path):
    """A source someone switched off covers nothing, so the pointer still earns its place."""
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "pointer",
                        "name": "City of Ocoee (Public Purchase)",
                        "county": "orange",
                        "agency": "City of Ocoee",
                        "adapter": "catalog",
                        "live_fetch": False,
                        "portal_url": "https://publicpurchase.com/ocoee",
                    },
                    {
                        "id": "og_ocoee",
                        "name": "Ocoee (OpenGov)",
                        "county": "orange",
                        "agency": "Ocoee",
                        "adapter": "opengov",
                        "live_fetch": False,
                        "opengov_code": "ocoeefl",
                        "portal_url": "https://procurement.opengov.com/portal/ocoeefl",
                    },
                ]
            }
        )
    )
    assert "pointer" in {a.source_id for a in get_adapters(config_path=cfg)}


def test_the_shipped_config_supersedes_only_catalog_entries():
    configs = load_source_config()
    by_id = {c["id"]: c for c in configs if isinstance(c, dict) and c.get("id")}
    for sid in _superseded_catalog_ids(configs):
        assert by_id[sid]["adapter"] == "catalog"


def test_unknown_adapter_is_skipped_not_fatal(tmp_path):
    """One bad config line must not take down every other portal."""
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "sources": [
                    {
                        "id": "good",
                        "name": "Good",
                        "county": "broward",
                        "agency": "A",
                        "portal_url": "https://x.gov",
                        "adapter": "catalog",
                    },
                    {
                        "id": "bad",
                        "name": "Bad",
                        "county": "broward",
                        "agency": "A",
                        "portal_url": "https://x.gov",
                        "adapter": "does_not_exist",
                    },
                ]
            }
        )
    )
    with pytest.warns(RuntimeWarning, match="does_not_exist"):
        adapters = get_adapters(config_path=cfg)
    assert [a.source_id for a in adapters] == ["good"]


def test_incomplete_entry_is_skipped(tmp_path):
    cfg = tmp_path / "sources.yaml"
    cfg.write_text(yaml.safe_dump({"sources": [{"id": "partial", "adapter": "catalog"}]}))
    with pytest.warns(RuntimeWarning, match="missing keys"):
        assert get_adapters(config_path=cfg) == []


def test_strict_mode_raises_for_tests():
    with pytest.raises(KeyError, match="nope"):
        get_adapters(only=["nope"], strict=True)


def test_filters_select_subsets():
    assert all(a.live_fetch for a in get_adapters(live_only=True))
    assert not any(
        a.cfg.get("adapter") == "catalog" for a in get_adapters(include_catalog=False)
    )
    assert [a.source_id for a in get_adapters(only=["broward_bpro"])] == ["broward_bpro"]
