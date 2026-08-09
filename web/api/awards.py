"""Awards and incumbent contracts — the decided side of the market."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter

from src.contracts import expiring_within
from src.db import store as db

from ..services.pricing import build_pricing
from ..services.serialize import opp_out

router = APIRouter()


@router.get("/pricing")
def pricing():
    """What similar work has gone for — medians from real awards and contracts."""
    return build_pricing()

#: How far ahead the expiring-contracts list looks. Long enough to prepare a
#: bid, short enough to stay a work queue.
EXPIRY_HORIZON_DAYS = 180


@router.get("/awards")
def awards():
    """Award records newest-first, plus the contracts about to expire.

    Awards are the trailing indicator (who won, for how much); expiring
    incumbent contracts are the leading one (what is coming up for rebid).
    One payload because one screen shows both.
    """
    workflow = db.workflow_state()
    opps = db.load_opportunities()
    award_rows = sorted(
        (o for o in opps if o.status == "award"),
        key=lambda o: (o.award_date or o.posted_date or date.min),
        reverse=True,
    )

    contracts = expiring_within(db.load_contracts(), days=EXPIRY_HORIZON_DAYS)
    today = date.today()
    return {
        "awards": [opp_out(o, workflow) for o in award_rows[:300]],
        "contracts": [
            {
                "contract_id": c.contract_id,
                "agency": c.agency,
                "name": c.name,
                "vendor": c.vendor,
                "end_date": c.end_date.isoformat() if c.end_date else None,
                "days_left": c.days_until_expiry(today),
                "amount": c.amount,
                "method": c.method,
                "extendable": c.extendable,
                "commodity": c.commodity,
                "url": c.url,
            }
            for c in contracts[:300]
        ],
        "contracts_total": len(contracts),
    }
