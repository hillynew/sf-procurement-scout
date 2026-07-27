"""Deal brief / summary generation (rule-based, no LLM required)."""

from __future__ import annotations

from typing import Optional

from .models.opportunity import Opportunity


def make_brief(opp: Opportunity) -> str:
    """
    Produce a short deal summary suitable for scan lists and dashboards.
    Format: [TYPE] Agency — Title. Due. Category. Action link cue.
    """
    st = (opp.solicitation_type or "BID").upper()
    if st == "UNKNOWN":
        st = "BID"

    parts = [f"[{st}] {opp.agency}: {opp.title.strip()}"]

    if opp.external_id:
        parts.append(f"Ref {opp.external_id}.")

    if opp.due_date:
        due = opp.due_date.strftime("%b %d, %Y %H:%M")
        days = opp.days_until_due
        if days is not None:
            if days < 0:
                timing = f"CLOSED {abs(days)}d ago"
            elif days == 0:
                timing = "DUE TODAY"
            elif days <= 7:
                timing = f"due in {days}d (URGENT)"
            else:
                timing = f"due in {days}d"
            parts.append(f"Closes {due} ({timing}).")
        else:
            parts.append(f"Closes {due}.")
    elif opp.status == "upcoming":
        parts.append("Upcoming / planned solicitation.")
    elif opp.status == "catalog":
        parts.append("Portal directory entry — register to see live bids.")
    else:
        parts.append("Due date not published on listing.")

    cat_bits = []
    if opp.offer_type and opp.offer_type != "unknown":
        cat_bits.append(opp.offer_type.replace("_", " "))
    if opp.categories:
        cat_bits.append("/".join(opp.categories[:3]))
    if cat_bits:
        parts.append("Category: " + "; ".join(cat_bits) + ".")

    if opp.budget:
        parts.append(f"Budget: {opp.budget}.")

    if opp.department:
        parts.append(f"Dept: {opp.department}.")

    if opp.contact:
        parts.append(f"Contact: {opp.contact}.")

    if opp.description:
        desc = " ".join(opp.description.split())
        if len(desc) > 180:
            desc = desc[:177] + "..."
        if desc and desc.lower() not in opp.title.lower():
            parts.append(desc)

    return " ".join(parts)


def apply_briefs(opportunities: list) -> list:
    for opp in opportunities:
        if not opp.brief:
            opp.brief = make_brief(opp)
    return opportunities
