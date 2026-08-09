"""Join award records to the solicitations they decide.

Awards and open solicitations are two record types from two kinds of feed: the
bid board announces the ask, and the award arrives later as a notice, an
agenda item, or a contract. Linking them is what turns "something was awarded"
into "this bid went for this much".

Two joins, tried in order, and the method is always recorded so a bad match
can be traced:

* ``ref`` — the award names the solicitation outright (MFMP's
  ``linkedAdNumber``, a bid number quoted in an agenda title, SAM's
  ``solicitationNumber``). Matched on normalised reference within the agency.
* ``fuzzy`` — agency + title-token containment at the same 0.7 threshold the
  recurrence matcher uses (`src/pipeline/history.py`), which was tuned on
  real Florida titles.

This pass runs over one snapshot, so it links awards to solicitations the
same fetch can see. Awards for solicitations that have already left the
portals link on the next pass over the stored archive — which is why vanished
rows are retained rather than deleted.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..models.opportunity import Opportunity
from .history import MATCH_THRESHOLD, significant_tokens, similarity

_REF_NOISE = re.compile(r"[^a-z0-9]+")


def _norm_ref(ref: Optional[str]) -> Optional[str]:
    if not ref:
        return None
    out = _REF_NOISE.sub("", str(ref).lower())
    return out or None


def link_awards(opps: List[Opportunity]) -> int:
    """Stamp linkage between award rows and solicitation rows, both ways.

    The award row gets ``award_linkage`` (how the join was made); the
    solicitation row inherits the award facts it lacks — vendor, amount,
    date. Returns the number of awards linked.
    """
    awards = [o for o in opps if o.status == "award"]
    if not awards:
        return 0
    solicitations = [o for o in opps if o.status != "award"]

    by_ref: Dict[str, Opportunity] = {}
    by_agency: Dict[str, List[Opportunity]] = {}
    for s in solicitations:
        agency = s.agency.lower()
        ref = _norm_ref(s.external_id)
        if ref:
            by_ref.setdefault(f"{agency}|{ref}", s)
            # MFMP awards link by advertisement id, which has no agency prefix
            # ambiguity, so a bare-ref index is kept as a fallback.
            by_ref.setdefault(ref, s)
        by_agency.setdefault(agency, []).append(s)

    linked = 0
    for award in awards:
        target = None
        agency = award.agency.lower()

        for candidate in (award.linked_ref, award.external_id):
            ref = _norm_ref(candidate)
            if not ref:
                continue
            target = by_ref.get(f"{agency}|{ref}") or by_ref.get(ref)
            if target is not None:
                award.award_linkage = "ref"
                break

        if target is None:
            tokens = significant_tokens(award.title)
            best = 0.0
            for s in by_agency.get(agency, []):
                score = similarity(tokens, significant_tokens(s.title))
                if score >= MATCH_THRESHOLD and score > best:
                    best, target = score, s
            if target is not None:
                award.award_linkage = "fuzzy"
                if not award.linked_ref:
                    award.linked_ref = target.external_id

        if target is None:
            continue
        linked += 1
        # The solicitation inherits what the award knows; existing values win.
        target.awarded_vendor = target.awarded_vendor or award.awarded_vendor
        if target.award_amount is None:
            target.award_amount = award.award_amount
        target.award_date = target.award_date or award.award_date or award.posted_date
    return linked
