"""Load source config and map adapter ids to classes."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Dict, List, Type
import yaml

from .base import SourceAdapter
from .bonfire import BonfireAdapter
from .civicplus import CivicPlusAdapter
from .email_alerts import EmailAlertsAdapter
from .notice_links import NoticeLinksAdapter
from .miami_dade_informs import MiamiDadeInformsAdapter
from .miami_dade_construction import MiamiDadeConstructionAdapter, MiamiDadeFutureAdapter
from .mdc_college import MdcCollegeAdapter
from .west_palm_beach import WestPalmBeachAdapter
from .palm_beach_schools import PalmBeachSchoolsAdapter
from .catalog import CatalogAdapter

ADAPTERS: Dict[str, Type[SourceAdapter]] = {
    "bonfire": BonfireAdapter,
    "miami_dade_informs": MiamiDadeInformsAdapter,
    "miami_dade_construction": MiamiDadeConstructionAdapter,
    "miami_dade_future": MiamiDadeFutureAdapter,
    "mdc_college": MdcCollegeAdapter,
    "west_palm_beach": WestPalmBeachAdapter,
    "palm_beach_schools": PalmBeachSchoolsAdapter,
    "civicplus": CivicPlusAdapter,
    "notice_links": NoticeLinksAdapter,
    "email_alerts": EmailAlertsAdapter,
    "catalog": CatalogAdapter,
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_source_config(path: Path | None = None) -> List[Dict[str, Any]]:
    cfg_path = path or (project_root() / "config" / "sources.yaml")
    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return list(data.get("sources") or [])


REQUIRED_KEYS = ("id", "name", "county", "agency", "portal_url", "adapter")


def get_adapters(
    *,
    only: List[str] | None = None,
    live_only: bool = False,
    include_catalog: bool = True,
    config_path: Path | None = None,
    strict: bool = False,
) -> List[SourceAdapter]:
    """Build adapters from config.

    A malformed or unknown entry is skipped with a warning rather than raising:
    one bad line in sources.yaml should not take down every other portal.
    Pass ``strict=True`` (used by the tests) to surface config errors instead.
    """
    configs = load_source_config(config_path)
    adapters: List[SourceAdapter] = []
    for cfg in configs:
        if not isinstance(cfg, dict):
            _reject(strict, f"Source entry is not a mapping: {cfg!r}")
            continue
        missing = [k for k in REQUIRED_KEYS if not cfg.get(k)]
        if missing:
            _reject(strict, f"Source {cfg.get('id', '?')} missing keys: {', '.join(missing)}")
            continue
        if only and cfg["id"] not in only:
            continue
        if live_only and not cfg.get("live_fetch", True):
            continue
        if not include_catalog and cfg.get("adapter") == "catalog":
            continue

        cls = ADAPTERS.get(cfg["adapter"])
        if not cls:
            _reject(strict, f"Unknown adapter '{cfg['adapter']}' for source {cfg['id']}")
            continue
        adapters.append(cls(cfg))

    if only:
        found = {a.source_id for a in adapters}
        for sid in only:
            if sid not in found:
                _reject(strict, f"No configured source with id '{sid}'")
    return adapters


def _reject(strict: bool, message: str) -> None:
    if strict:
        raise KeyError(message)
    warnings.warn(f"sources.yaml: {message}", RuntimeWarning, stacklevel=3)
