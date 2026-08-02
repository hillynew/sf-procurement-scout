"""Opportunity → API JSON, with the user's workflow overlay folded in."""

from __future__ import annotations

from typing import Dict, Optional, Set

from src.models.opportunity import Opportunity


def opp_out(
    o: Opportunity,
    workflow: Dict[str, dict],
    summarized: Optional[Set[str]] = None,
) -> dict:
    data = o.model_dump(mode="json")
    wf = workflow.get(o.opportunity_id)
    data["tracked"] = wf is not None
    data["stage"] = wf["stage"] if wf else None
    data["decision"] = wf["decision"] if wf else None
    data["archived"] = bool(wf and wf["archived"])
    data["tracked_on"] = wf["tracked_on"] if wf else None
    data["checks"] = wf["checks"] if wf else {}
    data["notes"] = wf["notes"] if wf else ""
    data["result"] = wf["result"] if wf else None
    data["has_summary"] = bool(summarized and o.opportunity_id in summarized)
    return data
