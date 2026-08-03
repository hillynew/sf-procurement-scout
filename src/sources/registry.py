"""Load source config and map adapter ids to classes."""

from __future__ import annotations

import warnings
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, List, Tuple, Type
import yaml

from .base import SourceAdapter
from .bonfire import BonfireAdapter
from .civicplus import CivicPlusAdapter
from .email_alerts import EmailAlertsAdapter
from .notice_links import NoticeLinksAdapter
from .miami_dade_informs import MiamiDadeInformsAdapter
from .miami_dade_construction import MiamiDadeConstructionAdapter, MiamiDadeFutureAdapter
from .mdc_college import MdcCollegeAdapter
from .mfmp_vbs import MfmpVbsAdapter
from .west_palm_beach import WestPalmBeachAdapter
from .palm_beach_schools import PalmBeachSchoolsAdapter
from .sam_gov import SamGovAdapter
from .catalog import CatalogAdapter

ADAPTERS: Dict[str, Type[SourceAdapter]] = {
    "bonfire": BonfireAdapter,
    "miami_dade_informs": MiamiDadeInformsAdapter,
    "miami_dade_construction": MiamiDadeConstructionAdapter,
    "miami_dade_future": MiamiDadeFutureAdapter,
    "mdc_college": MdcCollegeAdapter,
    "west_palm_beach": WestPalmBeachAdapter,
    "palm_beach_schools": PalmBeachSchoolsAdapter,
    "sam_gov": SamGovAdapter,
    "mfmp_vbs": MfmpVbsAdapter,
    "civicplus": CivicPlusAdapter,
    "notice_links": NoticeLinksAdapter,
    "email_alerts": EmailAlertsAdapter,
    "catalog": CatalogAdapter,
}


@lru_cache(maxsize=None)
def document_headers(source_id: str) -> Tuple[Tuple[str, str], ...]:
    """Extra headers to send when downloading this source's documents.

    Resolved from the adapter *class*, so no portal is contacted and nothing is
    instantiated. Returned as a tuple of pairs to stay hashable for the cache;
    call `dict(...)` on it.
    """
    for cfg in load_source_config():
        if cfg.get("id") == source_id:
            cls = ADAPTERS.get(str(cfg.get("adapter") or ""))
            return tuple(sorted((getattr(cls, "document_headers", None) or {}).items()))
    return ()


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_source_config(path: Path | None = None) -> List[Dict[str, Any]]:
    """Load ``config/sources.yaml`` plus any generated companion files.

    The hand-maintained tri-county config is the base list. Statewide expansion
    is generated (``scripts/discover_fl_agencies.py`` writes
    ``config/sources.florida.yaml``), so it lives in its own file: regenerating
    hundreds of discovered agencies must never clobber a portal someone tuned
    by hand. An explicit ``path`` loads only that file, which is what the tests
    rely on.

    Later files never override earlier ones — the first definition of an id
    wins, so a hand-written entry always beats a discovered one.
    """
    if path is not None:
        return _read_sources(path)

    cfg_dir = project_root() / "config"
    paths = [cfg_dir / "sources.yaml"]
    paths += sorted(p for p in cfg_dir.glob("sources.*.yaml") if p.name != "sources.yaml")

    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for p in paths:
        for entry in _read_sources(p):
            sid = entry.get("id") if isinstance(entry, dict) else None
            if sid and sid in seen:
                continue
            if sid:
                seen.add(sid)
            merged.append(entry)
    return merged


def _read_sources(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        warnings.warn(f"{path.name}: unreadable ({e})", RuntimeWarning, stacklevel=3)
        return []
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
    configs = configs + _custom_source_configs({c.get("id") for c in configs if isinstance(c, dict)})
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


def _custom_source_configs(known_ids: set) -> List[Dict[str, Any]]:
    """User-added portals stored in the database, merged after the yaml list.

    Best-effort: a missing or unreachable database simply contributes nothing,
    so the CLI and tests keep working with yaml alone.
    """
    try:
        from ..db.store import list_custom_sources

        return [
            {
                "id": s["id"],
                "name": s["name"],
                "county": s["county"],
                "agency": s["agency"],
                "adapter": s["adapter"],
                "portal_url": s["portal_url"],
                "live_fetch": True,
            }
            for s in list_custom_sources()
            if s["id"] not in known_ids
        ]
    except Exception:  # noqa: BLE001
        return []


def _reject(strict: bool, message: str) -> None:
    if strict:
        raise KeyError(message)
    warnings.warn(f"sources.yaml: {message}", RuntimeWarning, stacklevel=3)
