"""Base source adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..models.opportunity import Opportunity


class SourceAdapter(ABC):
    source_id: str
    name: str
    county: str
    agency: str
    portal_url: str
    live_fetch: bool = True

    #: Set by an adapter that returned results but knows they are incomplete
    #: (portal blocked, fallback path taken). The runner turns this into a
    #: `degraded` health status so partial data is not reported as healthy.
    degraded_reason: Optional[str] = None

    #: Adapters whose portal legitimately lists nothing sometimes return an
    #: empty list. Set False when zero rows always means the parse broke.
    allows_empty: bool = True

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.source_id = cfg["id"]
        self.name = cfg["name"]
        self.county = cfg["county"]
        self.agency = cfg["agency"]
        self.portal_url = cfg["portal_url"]
        self.live_fetch = bool(cfg.get("live_fetch", True))
        self.degraded_reason = None

    @abstractmethod
    def fetch(self) -> List[Opportunity]:
        ...

    def _base_kwargs(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.name,
            "county": self.county,
            "agency": self.agency,
        }
