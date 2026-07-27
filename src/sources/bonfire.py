"""Bonfire / Euna public portal adapter (Broward BPRO, Town of Palm Beach, etc.)."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from dateutil import parser as dateparser

from ..classify import enrich
from ..http_util import get, session
from ..models.opportunity import Opportunity
from .base import SourceAdapter


class BonfireAdapter(SourceAdapter):
    def fetch(self) -> List[Opportunity]:
        host = self.cfg.get("bonfire_host")
        if not host:
            raise ValueError(f"{self.source_id}: bonfire_host required")

        s = session()
        # warm session / cookies
        get(f"https://{host}/portal/", s=s)
        api = f"https://{host}/PublicPortal/getOpenPublicOpportunitiesSectionData"
        resp = get(
            api,
            s=s,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"https://{host}/portal/",
            },
        )
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Bonfire API error: {data}")

        payload = data.get("payload") or {}
        projects = payload.get("projects") or {}
        departments = payload.get("departments") or {}

        out: List[Opportunity] = []
        for _pid, p in projects.items():
            title = (p.get("ProjectName") or "").strip()
            if not title:
                continue
            ref = (p.get("ReferenceID") or "").strip() or None
            project_id = str(p.get("ProjectID") or "")
            url = f"https://{host}/opportunities/{project_id}" if project_id else self.portal_url

            due = _parse_dt(p.get("DateClose"))
            dept_id = str(p.get("DepartmentID") or "")
            dept_name = None
            if dept_id and isinstance(departments, dict):
                d = departments.get(dept_id) or departments.get(int(dept_id) if dept_id.isdigit() else dept_id)
                if isinstance(d, dict):
                    dept_name = d.get("DepartmentName")

            fields = enrich(title, external_id=ref)
            opp = Opportunity(
                **self._base_kwargs(),
                external_id=fields["external_id"] or ref,
                title=title,
                url=url,
                department=dept_name,
                solicitation_type=fields["solicitation_type"],
                offer_type=fields["offer_type"],
                categories=fields["categories"],
                keywords=fields["keywords"],
                due_date=due,
                status="open",
                raw={"project": p},
            )
            out.append(opp)
        return out


def _parse_dt(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        return dateparser.parse(val)
    except Exception:
        return None
