"""Executed contracts, and the expiry dates that say when a rebid is coming.

Knowing what is out for bid today tells you about work you are already late to
scope. Knowing that the incumbent's three-year janitorial contract ends in
February tells you about work nobody has advertised yet — which is the only
kind you can prepare for properly.

Bonfire publishes this for free and unauthenticated at
`/PublicPortal/getPublicContractsSectionData`, alongside the opportunity
endpoints the scout already reads. Seven of the twelve Florida tenants sampled
publish it; Hillsborough County alone has 2,039 contracts and 1,518 vendors,
391 of them expiring within a year.

There is no local equivalent to this anywhere else in the system. FACTS covers
state contracts under s. 215.985 and is Phase 3; for county and city work this
endpoint is the only free source of who holds what and until when.

Two shapes to know about:

* **`publicContracts` is an object keyed by ContractID, not an array** — the
  same trap as `projects` on the opportunities endpoint. Iterating it naively
  yields the keys, so a caller that treats it as a list gets a pile of id
  strings rather than contracts, or silently counts nothing.
* **`vendors` is a flat array** that has to be indexed by `VendorID` to turn a
  contract into a name. Without the join a contract says only that *someone*
  holds it, which is the least interesting part.

Expiry is filtered on the date rather than on `ContractStatusID`, whose codes
the portal does not document. Guessing which status means "live" would silently
drop real contracts; an end date in the future is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Sequence

#: Default horizon for "coming up". Long enough to prepare a bid, short enough
#: that the list stays a work queue rather than an archive.
DEFAULT_HORIZON_DAYS = 365

#: Anything ending sooner than this is almost certainly already being rebid
#: without us, but it is still worth seeing.
IMMINENT_DAYS = 90


@dataclass
class Contract:
    """One executed contract, as a portal publishes it."""

    contract_id: str
    agency: str
    name: str
    source_id: str
    vendor: Optional[str] = None
    vendor_id: Optional[str] = None
    status_id: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    url: Optional[str] = None
    #: Total compensation, when the portal publishes it. Bonfire's register does
    #: not; FACTS does, for every state contract.
    amount: Optional[float] = None
    #: Method of procurement, same caveat.
    method: Optional[str] = None
    #: Renewal option remaining, where the register says (Bonfire's
    #: IsExtendable column). None = the register doesn't publish it.
    extendable: Optional[bool] = None

    def days_until_expiry(self, today: Optional[date] = None) -> Optional[int]:
        if self.end_date is None:
            return None
        return (self.end_date - (today or date.today())).days


def parse_date(value: object) -> Optional[date]:
    """Portal dates arrive as 'YYYY-MM-DD HH:MM:SS'; anything else is unusable."""
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def index_vendors(vendors: object) -> Dict[str, str]:
    """VendorID -> organisation name.

    Accepts either shape the portal uses, because the contracts payload keys
    its contracts by id while keeping vendors in a plain array, and there is no
    guarantee that stays true on both.
    """
    rows = list(vendors.values()) if isinstance(vendors, dict) else (vendors or [])
    out: Dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        vid = str(row.get("VendorID") or "").strip()
        name = (row.get("VendorContactOrganizationName") or "").strip()
        if vid and name:
            out[vid] = name
    return out


def expiring_within(
    contracts: Iterable[Contract],
    *,
    days: int = DEFAULT_HORIZON_DAYS,
    today: Optional[date] = None,
) -> List[Contract]:
    """Contracts ending between today and `days` out, soonest first.

    Already-expired contracts are dropped: a rebid you missed is history, and
    the point of this list is lead time.
    """
    today = today or date.today()
    out = []
    for contract in contracts:
        left = contract.days_until_expiry(today)
        if left is None or left < 0 or left > days:
            continue
        out.append(contract)
    out.sort(key=lambda c: (c.end_date or date.max, c.name))
    return out


def by_vendor(contracts: Sequence[Contract]) -> Dict[str, List[Contract]]:
    """Group by incumbent — who holds how much of an agency's work."""
    out: Dict[str, List[Contract]] = {}
    for contract in contracts:
        if contract.vendor:
            out.setdefault(contract.vendor, []).append(contract)
    return out


def summarise(contracts: Sequence[Contract], *, today: Optional[date] = None) -> str:
    """One line for a log or a digest subject."""
    upcoming = expiring_within(contracts, today=today)
    if not upcoming:
        return "no contracts expiring in the next year"
    imminent = [c for c in upcoming if (c.days_until_expiry(today) or 0) <= IMMINENT_DAYS]
    line = f"{len(upcoming)} contract(s) expiring within a year"
    if imminent:
        line += f", {len(imminent)} within {IMMINENT_DAYS} days"
    return line


def refresh(*, only: Optional[Sequence[str]] = None, quiet: bool = True) -> List[Contract]:
    """Re-read every source that publishes a contract register, and store it.

    Runs on its own cadence rather than with the opportunity fetch. Contracts
    change on the timescale of contract terms — a weekly pass is generous —
    and this walks the whole register for each tenant, which is several
    thousand rows nobody needs re-downloaded every four hours.
    """
    from .db.store import save_contracts
    from .sources.registry import get_adapters

    collected: List[Contract] = []
    for adapter in get_adapters(only=list(only) if only else None):
        if not hasattr(adapter, "fetch_contracts"):
            continue
        try:
            rows = adapter.fetch_contracts()
        except Exception as e:  # noqa: BLE001 — one portal must not stop the rest
            if not quiet:
                print(f"  {adapter.source_id}: {type(e).__name__}: {e}")
            continue
        if rows:
            collected.extend(rows)
            if not quiet:
                print(f"  {adapter.source_id}: {len(rows)} contracts")

    if collected:
        try:
            save_contracts(collected)
        except Exception:  # noqa: BLE001 — the register is a bonus, never the run
            pass
    return collected


def load_stored() -> List[Contract]:
    """Everything previously refreshed, or nothing if the store is unavailable."""
    try:
        from .db.store import load_contracts

        return load_contracts()
    except Exception:  # noqa: BLE001
        return []
