"""Catalog-only sources (login / SPA portals without public list HTML)."""

from __future__ import annotations

from typing import List

from ..models.opportunity import Opportunity, OfferType
from .base import SourceAdapter


class CatalogAdapter(SourceAdapter):
    """Emits a single portal-directory opportunity with registration link."""

    def fetch(self) -> List[Opportunity]:
        register = self.cfg.get("register_url") or self.portal_url
        return [
            Opportunity(
                **self._base_kwargs(),
                external_id=None,
                title=f"Register / browse: {self.name}",
                url=self.portal_url,
                offer_type=OfferType.UNKNOWN,
                categories=["portal_directory"],
                status="catalog",
                description=(
                    f"This portal requires vendor registration or is a JavaScript SPA "
                    f"without a public list API. Open the portal and register at: {register}"
                ),
                contact=None,
                raw={"register_url": register},
            )
        ]
