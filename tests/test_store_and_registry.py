"""Snapshot persistence, retention, and source-config loading."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
import yaml

from src.models.opportunity import HealthStatus, SourceHealth
from src.pipeline import store
from src.sources.registry import ADAPTERS, get_adapters, load_source_config


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
    for cfg in configs:
        assert cfg["adapter"] in ADAPTERS, f"{cfg['id']} references an unknown adapter"
        assert cfg["county"] in {"miami-dade", "broward", "palm-beach",
                                 "federal", "florida"}
        assert cfg["portal_url"].startswith("https://")


def test_every_shipped_source_builds():
    assert len(get_adapters(strict=True)) == len(load_source_config())


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
