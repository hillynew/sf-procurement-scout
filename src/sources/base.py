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

    #: Why this source returned nothing, when that is an expected state rather
    #: than a fault — an optional integration nobody has switched on, say.
    #: Reported as `empty`, so it never raises a false alarm in the UI.
    empty_note: Optional[str] = None

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.source_id = cfg["id"]
        self.name = cfg["name"]
        self.county = cfg["county"]
        self.agency = cfg["agency"]
        self.portal_url = cfg["portal_url"]
        self.live_fetch = bool(cfg.get("live_fetch", True))
        self.degraded_reason = None
        self.empty_note = None

    #: Extra headers this portal needs when its *documents* are downloaded.
    #: The shared session sends an HTML-first `Accept`, which some portals read
    #: as a request for a page and answer with their SPA shell rather than the
    #: file — the download then looks like a 200 that simply is not a PDF.
    #: Declared here so that quirk lives with the rest of the portal knowledge.
    document_headers: Dict[str, str] = {}

    #: True when the adapter implements `fetch_detail`. List pages carry little
    #: more than a title and a date, so the detail pass is where scope,
    #: documents, requirements and contacts come from.
    supports_detail: bool = False

    @abstractmethod
    def fetch(self) -> List[Opportunity]:
        ...

    def fetch_detail(self, opp: Opportunity) -> None:
        """Enrich one opportunity in place from its own page.

        Default is a no-op so adapters whose portals expose no detail view
        (or block it) need no changes. Implementations should be tolerant:
        a detail page that fails to parse must leave the listing intact.
        """
        return None

    def _base_kwargs(self) -> dict:
        return {
            "source_id": self.source_id,
            "source_name": self.name,
            "county": self.county,
            "agency": self.agency,
        }
