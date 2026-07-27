"""Load source config and map adapter ids to classes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Type
import yaml

from .base import SourceAdapter
from .bonfire import BonfireAdapter
from .miami_dade_informs import MiamiDadeInformsAdapter
from .miami_dade_construction import MiamiDadeConstructionAdapter, MiamiDadeFutureAdapter
from .mdc_college import MdcCollegeAdapter
from .west_palm_beach import WestPalmBeachAdapter
from .palm_beach_schools import PalmBeachSchoolsAdapter
from .swa import SwaAdapter
from .catalog import CatalogAdapter

ADAPTERS: Dict[str, Type[SourceAdapter]] = {
    "bonfire": BonfireAdapter,
    "miami_dade_informs": MiamiDadeInformsAdapter,
    "miami_dade_construction": MiamiDadeConstructionAdapter,
    "miami_dade_future": MiamiDadeFutureAdapter,
    "mdc_college": MdcCollegeAdapter,
    "west_palm_beach": WestPalmBeachAdapter,
    "palm_beach_schools": PalmBeachSchoolsAdapter,
    "swa": SwaAdapter,
    "catalog": CatalogAdapter,
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_source_config(path: Path | None = None) -> List[Dict[str, Any]]:
    cfg_path = path or (project_root() / "config" / "sources.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return list(data.get("sources") or [])


def get_adapters(
    *,
    only: List[str] | None = None,
    live_only: bool = False,
    include_catalog: bool = True,
    config_path: Path | None = None,
) -> List[SourceAdapter]:
    configs = load_source_config(config_path)
    adapters: List[SourceAdapter] = []
    for cfg in configs:
        if only and cfg["id"] not in only:
            continue
        if live_only and not cfg.get("live_fetch", True):
            continue
        if not include_catalog and cfg.get("adapter") == "catalog":
            continue
        adapter_key = cfg.get("adapter")
        cls = ADAPTERS.get(adapter_key)
        if not cls:
            raise KeyError(f"Unknown adapter: {adapter_key} for source {cfg.get('id')}")
        adapters.append(cls(cfg))
    return adapters
