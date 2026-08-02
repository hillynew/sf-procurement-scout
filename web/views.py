"""Scout Classic rendering — pure functions from data to HTML.

Every screen (Calendar · All bids · My Pipeline · Bid Workroom · Watchlists ·
Sources) plus the detail drawer, rendered as classic-styled server-side HTML
(tokens in web/styles.css). No framework templates: the design handoff was
authored in HTML, so HTML-in-Python keeps it pixel-faithful and diffable.

`Page` takes the fetch snapshot, the user's workflow state and the request's
view parameters, precomputes the derived collections every screen shares, and
renders one full document. The server (web/server.py) owns routing, actions
and persistence; nothing in here mutates anything.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode

from src.models.opportunity import Opportunity, SourceHealth
from src.pipeline import user_state as us
from src.scoring import go_no_go

COUNTY_LABELS = {
    "miami-dade": "Miami-Dade",
    "broward": "Broward",
    "palm-beach": "Palm Beach",
}

SCREENS = [
    ("calendar", "Calendar"),
    ("all", "All bids"),
    ("pipeline", "My pipeline"),
    ("workroom", "Bid workroom"),
    ("watchlists", "Watchlists"),
    ("sources", "Sources"),
]

# Shared toolbar filters (county + work type) and sort orders.
TYPE_FILTERS = [
    ("construction", "CONSTRUCTION"),
    ("services", "SERVICES"),
    ("professional_services", "PROF. SERVICES"),
    ("goods", "GOODS"),
]
SORT_OPTIONS = [
    ("due", "DUE SOONEST"),
    ("new", "NEWEST POSTED"),
    ("value", "HIGHEST VALUE"),
    ("title", "TITLE A–Z"),
]
SOURCE_SORTS = [
    ("name", "NAME"),
    ("deals", "MOST DEALS"),
    ("speed", "FASTEST"),
]
SOURCE_STATUS_FILTERS = [
    ("", "ALL"),
    ("ok", "OK"),
    ("empty", "NO LISTINGS"),
    ("degraded", "DEGRADED"),
    ("error", "ERROR"),
]

STAGE_LABELS = {
    "watching": "WATCHING",
    "preparing": "PREPARING BID",
    "submitted": "SUBMITTED",
    "result": "RESULT",
}

STATUS_FILTERS = [
    ("", "ALL"),
    ("open", "OPEN"),
    ("upcoming", "UPCOMING"),
    ("closed", "CLOSED"),
]

# Chip ids double as watchlist filter keys — see Page.wl_matches().
CHIP_DEFS = [
    ("construction", "construction"),
    ("services", "services"),
    ("max500k", "≤ $500k"),
    ("broward", "Broward"),
    ("nobond", "no bond req’d"),
    ("recurring", "recurring only"),
]

# Known portals worth wiring next; anything already configured is hidden.
SUGGESTED_SOURCES = [
    "City of Fort Lauderdale",
    "Palm Beach County VSS",
    "Broward County Schools",
    "City of Miami Beach",
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def esc(s) -> str:
    return html.escape(str(s) if s is not None else "")


def href(**params) -> str:
    return "/?" + urlencode({k: v for k, v in params.items() if v not in (None, "")})


def mon_day(d: Optional[date]) -> str:
    return f"{d.strftime('%b')} {d.day}" if d else ""


def clock(dt: datetime) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d}{'am' if dt.hour < 12 else 'pm'}"


def due_full(dt: Optional[datetime]) -> str:
    """"Aug 4, 2:00pm" — the workroom/drawer date format."""
    if not dt:
        return ""
    return f"{mon_day(dt.date())}, {clock(dt)}"


def budget_amount(o: Opportunity) -> Optional[int]:
    if not o.budget:
        return None
    digits = re.sub(r"[^\d]", "", o.budget.split("-")[0].split("–")[0])
    return int(digits) if digits else None


def budget_short(o: Opportunity) -> Optional[str]:
    n = budget_amount(o)
    if n is None:
        return None
    if n >= 1_000_000:
        return f"${n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"${round(n / 1_000)}k"
    return f"${n}"


def offer_key(o: Opportunity) -> str:
    s = o.offer_type
    return str(s.value if hasattr(s, "value") else s or "unknown")


def sol_label(o: Opportunity) -> str:
    s = o.solicitation_type
    s = str(s.value if hasattr(s, "value") else s or "BID")
    return "BID" if s == "UNKNOWN" else s


def offer_word(o: Opportunity) -> Optional[str]:
    key = offer_key(o)
    return None if key == "unknown" else key.replace("_", " ")


def by_due(opps) -> List[Opportunity]:
    return sorted(
        opps,
        key=lambda o: (
            o.days_until_due if o.days_until_due is not None else 9_999,
            o.title.lower(),
        ),
    )


def doc_kind_label(name: str, kind: str) -> str:
    lowered = name.lower()
    if kind == "addendum":
        return "ADDENDUM"
    if kind == "drawing" or "plan" in lowered:
        return "PLANS"
    if kind == "specification":
        return "SPEC"
    if "package" in lowered or "pkg" in lowered:
        return "PKG"
    if "form" in lowered:
        return "FORM"
    if "submission" in lowered:
        return "OURS"
    if "tab" in lowered:
        return "TAB"
    return "DOC"


def short_title(o: Opportunity, limit: int = 18) -> str:
    head = re.split(r"[—,]", o.title)[0].strip()
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "…"


def meta_line(o: Opportunity, *, with_due: bool = False) -> str:
    parts = [o.agency]
    if offer_word(o):
        parts.append(offer_word(o))
    if budget_short(o):
        parts.append(f"{budget_short(o)} est")
    if with_due and o.due_date:
        parts.append(f"due {mon_day(o.due_date.date())}")
    if o.prior_cycles:
        parts.append(f"rebid · {o.prior_cycles}x before")
    elif o.requirements:
        parts.append(o.requirements[0].lower())
    return " · ".join(parts)


def _status(h: SourceHealth) -> str:
    return str(h.status.value if hasattr(h.status, "value") else h.status)


@dataclass
class ViewParams:
    """Everything the URL says about what to show."""

    screen: str = "calendar"
    drawer: Optional[str] = None
    bid: Optional[str] = None
    scope_open: bool = False
    all_sources: bool = False
    query: str = ""          # All-bids search
    status: str = ""         # status filter (bid status; source status on Sources)
    county: str = ""         # toolbar filter: miami-dade | broward | palm-beach
    otype: str = ""          # toolbar filter: work type
    sort: str = ""           # toolbar sort key (per-screen default when empty)
    cal: str = ""            # calendar month, YYYY-MM
    fetched_now: bool = False
    fetch_count: int = 0
    detect_status: Optional[str] = None  # "ok" | "fail"
    detect_url: str = ""


@dataclass
class Page:
    opps: List[Opportunity]
    health: List[SourceHealth]
    state: dict
    p: ViewParams
    total_sources: int = 0
    snapshot_time: Optional[datetime] = None
    _wl: List[tuple] = field(default_factory=list, init=False)

    # -- derived collections ------------------------------------------------

    def __post_init__(self) -> None:
        if self.p.screen not in dict(SCREENS):
            self.p.screen = "calendar"
        self.by_id: Dict[str, Opportunity] = {o.opportunity_id: o for o in self.opps}
        self.open_opps = [o for o in self.opps if o.status in ("open", "upcoming")]

        baseline = self.state.get("last_today_visit") or (
            date.today() - timedelta(days=1)
        ).isoformat()
        try:
            self.baseline_date = date.fromisoformat(str(baseline)[:10])
        except ValueError:
            self.baseline_date = date.today() - timedelta(days=1)

        self.closing_soon = [
            o for o in self.open_opps
            if o.days_until_due is not None and 0 <= o.days_until_due <= 3
        ]

        self.tracked_ids = [i for i in self.state["tracked"] if i in self.by_id]
        self.active_tracked = [
            i for i in self.tracked_ids if self.state["decisions"].get(i) != "nogo"
        ]

        for wl in self.state["watchlists"]:
            matches = self.wl_matches(wl)
            self._wl.append((wl, matches, self.wl_new_ids(wl, matches)))
        self.selected_wl_id = self.state.get("selected_watchlist")
        if self._wl and not any(w["id"] == self.selected_wl_id for w, _, _ in self._wl):
            self.selected_wl_id = self._wl[0][0]["id"]

        self.attention = [h for h in self.health if _status(h) in ("degraded", "error")]
        self.ok_n = sum(1 for h in self.health if _status(h) == "ok")
        self.empty_n = sum(1 for h in self.health if _status(h) == "empty")
        self.degraded_n = sum(1 for h in self.health if _status(h) == "degraded")
        self.error_n = sum(1 for h in self.health if _status(h) == "error")
        if self.health:
            self.total_sources = max(self.total_sources, len(self.health))

        wl_new_total = sum(len(new) for _, _, new in self._wl)
        self.nav_badges = {
            "calendar": len(self.closing_soon) or None,
            "all": len(self.opps) or None,
            "pipeline": len(self.tracked_ids) or None,
            "workroom": None,
            "watchlists": wl_new_total or None,
            "sources": len(self.attention) or None,
        }

    def stage_ids(self, stage: str) -> List[str]:
        ids = [i for i in self.active_tracked if us.stage_of(self.state, i) == stage]
        today_iso = date.today().isoformat()
        return sorted(
            ids,
            key=lambda i: (
                # Freshly tracked bids lead the Watching column ("tracked today").
                0 if (stage == "watching" and self.state["tracked"].get(i) == today_iso) else 1,
                self.by_id[i].days_until_due
                if self.by_id[i].days_until_due is not None else 9_999,
            ),
        )

    def default_workroom_id(self) -> Optional[str]:
        for pool in (self.stage_ids("preparing"), self.stage_ids("watching"), self.active_tracked):
            live = [i for i in pool if self.by_id[i].status in ("open", "upcoming")]
            if live:
                return live[0]
            if pool:
                return pool[0]
        return None

    def unmet_items(self, oid: str) -> List[str]:
        o = self.by_id[oid]
        checks = self.state["checks"].get(oid, {})
        return [r for i, r in enumerate(o.requirements) if not checks.get(str(i))]

    def wl_matches(self, wl: dict) -> List[Opportunity]:
        f = dict(wl.get("filters") or {})
        for chip in f.pop("chips", []):  # chip-built lists reuse the same keys
            if chip == "construction":
                f.setdefault("offers", []).append("construction")
            elif chip == "services":
                f.setdefault("offers", []).append("services")
            elif chip == "max500k":
                f["max_value"] = 500_000
            elif chip == "broward":
                f.setdefault("counties", []).append("broward")
            elif chip == "nobond":
                f["nobond"] = True
            elif chip == "recurring":
                f["recurring"] = True
        out = []
        for o in self.open_opps:
            if f.get("counties") and o.county not in f["counties"]:
                continue
            if f.get("offers") and offer_key(o) not in f["offers"]:
                continue
            if f.get("max_value"):
                n = budget_amount(o)
                if n is not None and n > f["max_value"]:
                    continue
            if f.get("nobond") and any("bond" in r.lower() for r in o.requirements):
                continue
            if f.get("recurring") and not o.prior_cycles:
                continue
            if f.get("keywords"):
                text = " ".join(
                    [o.title, o.scope or "", o.description or ""] + (o.categories or [])
                ).lower()
                if not any(kw in text for kw in f["keywords"]):
                    continue
            out.append(o)
        return by_due(out)

    def wl_new_ids(self, wl: dict, matches: List[Opportunity]) -> set:
        baseline = wl.get("prev_opened") or wl.get("last_opened")
        try:
            base_date = date.fromisoformat(str(baseline)[:10]) if baseline else self.baseline_date
        except ValueError:
            base_date = self.baseline_date
        return {
            o.opportunity_id for o in matches
            if o.posted_date and o.posted_date >= base_date
        }

    # -- shared fragments ---------------------------------------------------

    def keep(self, **over) -> Dict[str, str]:
        """The current view's URL params, so links preserve filters and sort."""
        base = {
            "screen": self.p.screen,
            "q": self.p.query or None,
            "f": self.p.status or None,
            "c": self.p.county or None,
            "t": self.p.otype or None,
            "sort": self.p.sort or None,
            "cal": self.p.cal or None,
            "bid": self.p.bid,
            "allsrc": "1" if self.p.all_sources else None,
        }
        base.update(over)
        return {k: v for k, v in base.items() if v}

    def filter_opps(self, pool) -> List[Opportunity]:
        out = list(pool)
        if self.p.county:
            out = [o for o in out if o.county == self.p.county]
        if self.p.otype:
            out = [o for o in out if offer_key(o) == self.p.otype]
        return out

    def sort_opps(self, pool, default: str = "due") -> List[Opportunity]:
        s = self.p.sort or default
        if s == "new":
            return sorted(
                pool,
                key=lambda o: (o.posted_date or date.min, o.title.lower()),
                reverse=True,
            )
        if s == "value":
            return sorted(
                pool,
                key=lambda o: (-(budget_amount(o) or -1), o.title.lower()),
            )
        if s == "title":
            return sorted(pool, key=lambda o: o.title.lower())
        return by_due(pool)

    def toolbar(self, *, sort: bool = True) -> str:
        """County / work-type filter chips + sort chips, as one classic row."""
        def chip(label: str, on: bool, **over) -> str:
            return (
                f'<a class="sc-chip {"on" if on else ""}" '
                f'href="{href(**self.keep(drawer=None, **over))}">{esc(label)}</a>'
            )

        parts = ['<div class="sc-toolbar">']
        parts.append('<span class="sc-toolbar-label">COUNTY</span>')
        parts.append(chip("ALL", not self.p.county, c=None))
        for key, label in COUNTY_LABELS.items():
            parts.append(chip(label.upper(), self.p.county == key, c=key))
        parts.append('<span class="sc-toolbar-label">TYPE</span>')
        parts.append(chip("ALL", not self.p.otype, t=None))
        for key, label in TYPE_FILTERS:
            parts.append(chip(label, self.p.otype == key, t=key))
        if sort:
            parts.append('<span class="sc-toolbar-label">SORT</span>')
            current = self.p.sort or "due"
            for key, label in SORT_OPTIONS:
                parts.append(chip(label, current == key, sort=key if key != "due" else None))
        parts.append("</div>")
        return "".join(parts)

    def scan_note(self) -> str:
        ts = self.snapshot_time
        if not ts:
            return "no data yet"
        if ts.date() == date.today():
            return f"today {clock(ts)}"
        if ts.date() == date.today() - timedelta(days=1):
            return f"yesterday {clock(ts)}"
        return f"{mon_day(ts.date())} {clock(ts)}"

    def track_btn(self, oid: str, **keep) -> str:
        on = oid in self.state["tracked"]
        return (
            f'<a class="sc-btn sc-btn-track {"on" if on else ""}" '
            f'href="{href(act="track", id=oid, **keep)}">'
            f'{"TRACKING ✓" if on else "TRACK"}</a>'
        )

    def empty_state(self, title: str, note: str = "") -> str:
        demo = href(act="demo", screen=self.p.screen)
        body = note or "Click <b>FETCH LIVE DATA</b> in the sidebar (30–90s across all portals)"
        return (
            f'<div class="sc-empty"><div class="sc-empty-title">{esc(title)}</div>'
            f'<div class="sc-empty-sub">{body}<br>or <a href="{demo}">load sample data</a>'
            " to explore the screens.</div></div>"
        )

    # -- Calendar -----------------------------------------------------------

    def _cal_month(self):
        try:
            year, month = str(self.p.cal).split("-")
            return int(year), int(month)
        except (ValueError, AttributeError):
            today = date.today()
            return today.year, today.month

    def calendar_html(self) -> str:
        year, month = self._cal_month()
        first = date(year, month, 1)
        # Sunday-start grid, 6 weeks.
        grid_start = first - timedelta(days=(first.weekday() + 1) % 7)
        days = [grid_start + timedelta(days=i) for i in range(42)]

        pool = self.filter_opps(self.opps)
        by_day: Dict[date, List[Opportunity]] = {}
        for o in pool:
            if o.due_date:
                by_day.setdefault(o.due_date.date(), []).append(o)

        month_n = sum(len(v) for d, v in by_day.items() if d.month == month and d.year == year)
        prev_m = (first - timedelta(days=1)).replace(day=1)
        next_m = (first + timedelta(days=31)).replace(day=1)
        nav = (
            f'<a class="sc-chip" href="{href(**self.keep(cal=f"{prev_m.year}-{prev_m.month:02d}"))}">‹ {prev_m.strftime("%b").upper()}</a>'
            f'<span class="sc-cal-month">{first.strftime("%B %Y").upper()}</span>'
            f'<a class="sc-chip" href="{href(**self.keep(cal=f"{next_m.year}-{next_m.month:02d}"))}">{next_m.strftime("%b").upper()} ›</a>'
            f'<a class="sc-chip" href="{href(**self.keep(cal=None))}">TODAY</a>'
        )
        head = f"""
        <div class="sc-head">
          <div>
            <div class="sc-head-title">Calendar</div>
            <div class="sc-head-sub">{month_n} bids due in {esc(first.strftime("%B %Y"))} · last scan {esc(self.scan_note())}</div>
          </div>
          <div class="sc-cal-nav">{nav}</div>
        </div>"""
        if not self.opps:
            return head + self.empty_state("No opportunities loaded")

        weekday_row = "".join(
            f'<div class="sc-cal-weekday">{w}</div>'
            for w in ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
        )
        cells = []
        today = date.today()
        for d in days:
            classes = ["sc-cal-day"]
            if d.month != month:
                classes.append("other")
            if d == today:
                classes.append("today")
            entries = []
            todays = sorted(
                by_day.get(d, []),
                key=lambda o: (o.status not in ("open", "upcoming"), o.title.lower()),
            )
            for o in todays[:4]:
                oid = o.opportunity_id
                if o.status in ("open", "upcoming"):
                    du = o.days_until_due
                    cls = "urgent" if (du is not None and 0 <= du <= 3) else ""
                else:
                    cls = "past"
                entries.append(
                    f'<a class="sc-cal-entry {cls}" title="{esc(o.title)} — {esc(o.agency)}" '
                    f'href="{href(**self.keep(drawer=oid))}">{esc(short_title(o, 22))}</a>'
                )
            if len(todays) > 4:
                entries.append(
                    f'<a class="sc-cal-more" href="{href(screen="all", c=self.p.county or None, t=self.p.otype or None)}">'
                    f"+ {len(todays) - 4} more</a>"
                )
            cells.append(
                f'<div class="{" ".join(classes)}">'
                f'<div class="sc-cal-daynum">{d.day}</div>{"".join(entries)}</div>'
            )
        grid = (
            f'<div class="sc-cal-grid">{weekday_row}{"".join(cells)}</div>'
            '<div class="sc-cal-footnote">bids placed on their due date · '
            '<span class="sc-cal-key urgent">closing ≤ 3 days</span> · '
            '<span class="sc-cal-key past">closed</span> · click any bid for detail</div>'
        )
        return head + self.toolbar(sort=False) + grid

    # -- All bids -----------------------------------------------------------

    def allbids_row(self, o: Opportunity) -> str:
        oid = o.opportunity_id
        d = o.days_until_due
        if o.due_date:
            date_top = mon_day(o.due_date.date())
            if o.status in ("open", "upcoming") and d is not None and d >= 0:
                date_sub, urgent = ("today" if d == 0 else f"{d}d left"), d <= 3
            else:
                date_sub, urgent = o.due_date.strftime("%Y"), False
        else:
            date_top, date_sub, urgent = "—", "no date", False
        if o.status in ("open", "upcoming") and urgent:
            tag = f'<span class="sc-status-tag crimson">{"DUE TODAY" if d == 0 else f"{d}D LEFT"}</span>'
        elif o.status == "open":
            tag = '<span class="sc-status-tag navy">OPEN</span>'
        elif o.status == "upcoming":
            tag = '<span class="sc-status-tag navy">UPCOMING</span>'
        elif o.status == "closed":
            tag = '<span class="sc-status-tag">CLOSED</span>'
        else:
            tag = f'<span class="sc-status-tag">{esc(o.status.upper())}</span>'
        return f"""
        <div class="sc-row {'closing' if urgent else ''}">
          <a class="sc-row-link" href="{href(**self.keep(drawer=oid))}" aria-label="{esc(o.title)}"></a>
          <div class="sc-slot"><div class="sc-slot-day {'crimson' if urgent else ''}">{esc(date_top)}</div>
            <div class="sc-slot-date">{esc(date_sub)}</div></div>
          <div class="sc-row-body">
            <div class="sc-row-title">{esc(o.title)}</div>
            <div class="sc-row-meta">{esc(meta_line(o))}</div>
          </div>
          <div class="sc-row-actions">
            {tag}
            {self.track_btn(oid, **self.keep())}
          </div>
        </div>"""

    def allbids_html(self) -> str:
        pool = self.filter_opps(self.opps)
        if self.p.status:
            pool = [o for o in pool if o.status == self.p.status]
        q = self.p.query.strip().lower()
        if q:
            pool = [
                o for o in pool
                if q in o.title.lower() or q in o.agency.lower()
                or q in (o.external_id or "").lower()
                or q in (o.scope or "").lower()
                or q in (o.description or "").lower()
            ]

        dates = [o.due_date.date() for o in pool if o.due_date]
        if dates:
            span = f"{mon_day(min(dates))} – {mon_day(max(dates))}, {max(dates).year}"
        else:
            span = "no dated bids"
        n_open = sum(1 for o in self.opps if o.status in ("open", "upcoming"))
        head = f"""
        <div class="sc-head">
          <div>
            <div class="sc-head-title">All bids</div>
            <div class="sc-head-sub">{len(self.opps)} bids · {n_open} open · due dates {esc(span)}</div>
          </div>
          <form class="sc-search-form" method="get" action="/">
            <input type="hidden" name="screen" value="all">
            <input type="hidden" name="f" value="{esc(self.p.status)}">
            <input type="hidden" name="c" value="{esc(self.p.county)}">
            <input type="hidden" name="t" value="{esc(self.p.otype)}">
            <input type="hidden" name="sort" value="{esc(self.p.sort)}">
            <input class="sc-search" type="text" name="q" value="{esc(self.p.query)}"
                   placeholder="search title, agency, ref…">
            <button class="sc-detect-btn" type="submit">SEARCH</button>
          </form>
        </div>"""
        if not self.opps:
            return head + self.empty_state("No opportunities loaded")

        chips = []
        for key, label in STATUS_FILTERS:
            n = len(self.opps) if not key else sum(1 for o in self.opps if o.status == key)
            on = self.p.status == key
            chips.append(
                f'<a class="sc-chip {"on" if on else ""}" '
                f'href="{href(**self.keep(drawer=None, f=key or None))}">{label} · {n}</a>'
            )
        filters = (
            f'<div class="sc-chips sc-allbids-filters">{"".join(chips)}</div>'
            + self.toolbar()
        )

        sections = []
        if (self.p.sort or "due") == "due":
            # Due-date order reads best as month groups.
            dated = sorted(
                (o for o in pool if o.due_date),
                key=lambda o: (o.due_date, o.title.lower()),
            )
            undated = sorted(
                (o for o in pool if not o.due_date), key=lambda o: o.title.lower()
            )
            groups: List[Tuple[str, List[Opportunity]]] = []
            for o in dated:
                label = o.due_date.strftime("%B %Y").upper()
                if not groups or groups[-1][0] != label:
                    groups.append((label, []))
                groups[-1][1].append(o)
            if undated:
                groups.append(("NO DUE DATE PUBLISHED", undated))
        else:
            ordered = self.sort_opps(pool)
            groups = [(f"{len(ordered)} BIDS", ordered)] if ordered else []

        for label, items in groups:
            prefix = "DUE " if label[0].isalpha() and "NO DUE" not in label and "BIDS" not in label else ""
            sections.append(
                f'<div class="sc-label sc-month-label">{prefix}{esc(label)} · {len(items)}</div>'
                if prefix else
                f'<div class="sc-label sc-month-label">{esc(label)}</div>'
            )
            sections.append(
                '<div class="sc-rows">' + "".join(self.allbids_row(o) for o in items) + "</div>"
            )
        if not groups:
            sections.append(
                '<div class="sc-empty"><div class="sc-empty-title">No bids match</div>'
                f'<div class="sc-empty-sub"><a href="{href(screen="all")}">clear search and filters</a>'
                "</div></div>"
            )
        return head + filters + "".join(sections)

    # -- Pipeline -----------------------------------------------------------

    def kanban_card(self, oid: str, stage: str) -> str:
        o = self.by_id[oid]
        state = self.state
        days = o.days_until_due
        cls, subs = "", []
        target = href(screen="pipeline", drawer=oid)
        if stage == "preparing" and days is not None and 0 <= days <= 3:
            cls = "urgent"
            target = href(screen="workroom", bid=oid)
            plural = "" if days == 1 else "S"
            label = "DUE TODAY" if days == 0 else f"DUE IN {days} DAY{plural}"
            subs.append(f'<div class="sc-card-sub crimson">{label}</div>')
            nxt = self.unmet_items(oid)
            if nxt:
                subs.append(
                    f'<div class="sc-card-sub tight">next: {esc(nxt[0].lower())} → workroom</div>'
                )
        elif stage == "watching" and state["tracked"].get(oid) == date.today().isoformat():
            cls = "navy"
            subs.append('<div class="sc-card-sub navy">tracked today</div>')
        elif stage == "submitted":
            note = f"opens {o.bid_opening}" if o.bid_opening else "awaiting award"
            subs.append(f'<div class="sc-card-sub">{esc(note)}</div>')
        elif stage == "result":
            outcome = state["results"].get(oid)
            if outcome:
                won = outcome.upper().startswith("WON")
                cls = "won" if won else ""
                label = esc(outcome)
                if won and budget_short(o) and "·" not in outcome:
                    label = f"{esc(outcome)} · {esc(budget_short(o))}"
                subs.append(
                    f'<div class="sc-card-sub {"green" if won else "crimson"}">{label}</div>'
                )
            else:
                subs.append(
                    '<div class="sc-card-sub sc-outcome">record result: '
                    f'<a class="sc-outcome-btn won" href="{href(act="result", id=oid, val="won", screen="pipeline")}">WON</a> '
                    f'<a class="sc-outcome-btn" href="{href(act="result", id=oid, val="lost", screen="pipeline")}">LOST</a>'
                    "</div>"
                )
        if not subs:
            bits = []
            if o.due_date:
                bits.append(f"due {mon_day(o.due_date.date())}")
            if stage == "preparing" and o.pre_bid_meeting:
                bits.append(f"pre-bid {o.pre_bid_meeting}")
            elif budget_short(o):
                bits.append(budget_short(o))
            else:
                bits.append(o.agency)
            subs.append(f'<div class="sc-card-sub">{esc(" · ".join(bits))}</div>')

        idx = us.STAGES.index(stage)
        moves = []
        if idx > 0:
            prev_label = STAGE_LABELS[us.STAGES[idx - 1]].title()
            moves.append(
                f'<a class="sc-move" href="{href(act="stage", id=oid, to="prev", screen="pipeline")}"'
                f' title="Move to {esc(prev_label)}">‹</a>'
            )
        if idx < len(us.STAGES) - 1:
            next_label = STAGE_LABELS[us.STAGES[idx + 1]].title()
            moves.append(
                f'<a class="sc-move" href="{href(act="stage", id=oid, to="next", screen="pipeline")}"'
                f' title="Move to {esc(next_label)}">›</a>'
            )
        return f"""
        <div class="sc-card {cls}">
          <a class="sc-row-link" href="{target}" aria-label="{esc(o.title)}"></a>
          <div class="sc-card-moves">{''.join(moves)}</div>
          <div class="sc-card-title">{esc(o.title)}</div>
          {''.join(subs)}
        </div>"""

    def pipeline_html(self) -> str:
        due_week = sum(
            1 for i in self.active_tracked
            if self.by_id[i].days_until_due is not None
            and 0 <= self.by_id[i].days_until_due <= 7
        )
        head = f"""
        <div class="sc-head">
          <div class="sc-head-title">My Pipeline</div>
          <div class="sc-head-note">{len(self.tracked_ids)} tracked · {due_week} due this week</div>
        </div>"""
        if not self.opps:
            return head + self.empty_state("No opportunities loaded")
        if not self.tracked_ids:
            return head + self.empty_state(
                "Nothing tracked yet",
                f"Hit <b>TRACK</b> on any bid in <a href='{href(screen='all')}'>All bids</a>"
                " to start a pipeline",
            )

        events = []
        for i in self.active_tracked:
            o = self.by_id[i]
            d = o.days_until_due
            if d is not None and 0 <= d <= 14:
                events.append((d, f"{short_title(o)} · {mon_day(o.due_date.date())}", d <= 2))
        events.sort()
        placed = []
        last_left = -100.0
        for d, label, urgent in events[:4]:
            left = max(2 + d * 6, last_left + 17)  # keep clustered chips readable
            left = min(left, 80)
            placed.append((left, label, urgent))
            last_left = left
        chips = "".join(
            f'<div class="sc-tl-chip {"urgent" if urgent else ""}" style="left:{left:g}%">'
            f"<span>{esc(label)}</span></div>"
            for left, label, urgent in placed
        )
        axis = (
            f"<span>{mon_day(date.today())}</span>"
            f"<span>{mon_day(date.today() + timedelta(days=7))}</span>"
            f"<span>{mon_day(date.today() + timedelta(days=14))}</span>"
        )
        timeline = f"""
        <div class="sc-panel">
          <div class="sc-label">NEXT 14 DAYS</div>
          <div class="sc-timeline">{chips or '<div class="sc-tl-chip" style="left:2%"><span>no deadlines in window</span></div>'}</div>
          <div class="sc-tl-axis">{axis}</div>
        </div>"""

        filtered_ids = {
            o.opportunity_id
            for o in self.filter_opps(self.by_id[i] for i in self.active_tracked)
        }
        cols = []
        for stage in ("watching", "preparing", "submitted", "result"):
            ids = [i for i in self.stage_ids(stage) if i in filtered_ids]
            if self.p.sort and self.p.sort != "due":
                ids = [
                    o.opportunity_id
                    for o in self.sort_opps([self.by_id[i] for i in ids])
                ]
            cards = [self.kanban_card(i, stage) for i in ids]
            if stage == "result" and ids:
                wins = sum(
                    1 for i in ids
                    if self.state["results"].get(i, "").upper().startswith("WON")
                )
                cards.append(
                    f'<div class="sc-foot-card">win rate this year: {wins} of {len(ids)} opened</div>'
                )
            cols.append(
                f'<div><div class="sc-col-head">{STAGE_LABELS[stage]} · {len(ids)}</div>'
                f'<div class="sc-cards">{"".join(cards)}</div></div>'
            )
        return (
            head + self.toolbar() + timeline
            + f'<div class="sc-kanban">{"".join(cols)}</div>'
        )

    # -- Workroom -----------------------------------------------------------

    def workroom_html(self) -> str:
        oid = self.p.bid if self.p.bid in self.by_id else self.default_workroom_id()
        bare_head = '<div class="sc-head workroom"><div class="sc-head-title">Bid workroom</div></div>'
        if not self.opps:
            return bare_head + self.empty_state("No opportunities loaded")
        if oid is None:
            return bare_head + self.empty_state(
                "No bid on the bench",
                f"Track a bid in <a href='{href(screen='all')}'>All bids</a>, then open it"
                " from its drawer or the pipeline",
            )
        o = self.by_id[oid]
        state = self.state
        dec = state["decisions"].get(oid)
        stage = us.stage_of(state, oid)
        checks = state["checks"].get(oid, {})

        meta_bits = [o.agency]
        if budget_short(o):
            meta_bits.append(f"{o.budget} est")
        if o.duration_days:
            meta_bits.append(f"{o.duration_days} calendar days")
        if o.liquidated_damages:
            meta_bits.append(f"LD {o.liquidated_damages}")
        meta_bits.append(f"detail {o.detail_score}%")

        if dec == "nogo":
            stage_html = '<div class="sc-stage-badge archived">ARCHIVED</div>'
        elif stage:
            stage_html = f'<div class="sc-stage-badge">{STAGE_LABELS[stage]}</div>'
            next_steps = {
                "watching": ("preparing", "start preparing →"),
                "preparing": ("submitted", "mark submitted →"),
                "submitted": ("result", "record result →"),
            }
            if stage in next_steps:
                to, label = next_steps[stage]
                stage_html += (
                    f'<div><a class="sc-stage-next" '
                    f'href="{href(act="stage", id=oid, to=to, screen="workroom", bid=oid)}">'
                    f"{label}</a></div>"
                )
        else:
            stage_html = '<div class="sc-stage-badge archived">NOT TRACKED</div>'
        crumb_txt = f"← My Pipeline · {sol_label(o)}"
        if offer_word(o):
            crumb_txt += f" · {offer_word(o).upper()}"
        if o.external_id:
            crumb_txt += f" · {o.external_id}"
        head = f"""
        <div class="sc-head workroom">
          <div>
            <a class="sc-crumb" href="{href(screen='pipeline')}">{esc(crumb_txt)}</a>
            <div class="sc-wr-title">{esc(o.title)}</div>
            <div class="sc-wr-meta">{esc(' · '.join(meta_bits))}</div>
          </div>
          <div class="sc-wr-right">
            <div class="sc-wr-due">{'Due ' + esc(due_full(o.due_date)) if o.due_date else esc(o.status)}</div>
            {stage_html}
          </div>
        </div>"""

        banner = ""
        if dec:
            if dec == "go":
                nxt = self.unmet_items(oid)
                detail = f"next: {nxt[0].lower()}" if nxt else "checklist is ready"
                if o.due_date:
                    detail += f"; bid due {due_full(o.due_date)}"
                text = f"MARKED GO — {detail}"
            else:
                text = "MARKED NO-GO — archived; removed from the pipeline board"
            banner = f"""
            <div class="sc-banner {'nogo' if dec == 'nogo' else ''}">
              <span class="sc-banner-text">{esc(text)}</span>
              <a class="sc-undo-link" href="{href(act='cleardec', id=oid, screen='workroom', bid=oid)}">undo</a>
            </div>"""

        scope_text = " ".join((o.scope or o.description or "").split())
        if scope_text:
            cut = scope_text.rfind(". ", 0, 440)
            cut = cut + 1 if cut > 120 else min(len(scope_text), 440)
            lead, rest = scope_text[:cut].strip(), scope_text[cut:].strip()
            more = (
                f'<div class="sc-scope-more">{esc(rest)}</div>'
                if (rest and self.p.scope_open) else ""
            )
            if rest:
                toggle_label = (
                    "collapse ▴" if self.p.scope_open
                    else f"full text, {len(scope_text):,} characters — expand ▾"
                )
                toggle = (
                    f'<a class="sc-scope-toggle" href="'
                    f'{href(screen="workroom", bid=oid, scope=None if self.p.scope_open else "1")}'
                    f'">{toggle_label}</a>'
                )
            else:
                toggle = ""
            scope_card = f'<div class="sc-scope-card">{esc(lead)}{more}{toggle}</div>'
        else:
            scope_card = (
                '<div class="sc-scope-card">No scope text extracted — open the official'
                " portal for the full package.</div>"
            )

        if o.requirements:
            rows = []
            for i, req in enumerate(o.requirements):
                done = bool(checks.get(str(i)))
                urgent = ("site visit" in req.lower() or "mandatory" in req.lower()) and not done
                note = "— NOT SCHEDULED" if urgent else ""
                rows.append(f"""
                <a class="sc-check" href="{href(act='check', id=oid, i=i, screen='workroom', bid=oid)}">
                  <span class="sc-checkbox {'on' if done else ''}">{'✓' if done else ''}</span>
                  <span class="sc-check-label {'done' if done else ''}">{esc(req)}</span>
                  <span class="sc-check-note {'urgent' if urgent else ''}">{note}</span>
                </a>""")
            done_n = sum(1 for i in range(len(o.requirements)) if checks.get(str(i)))
            check_block = f"""
            <div class="sc-check-head">
              <div class="sc-label">REQUIREMENTS → CHECKLIST</div>
              <div class="sc-check-count">{done_n} OF {len(o.requirements)} READY</div>
            </div>
            <div class="sc-checklist">{''.join(rows)}</div>"""
        else:
            check_block = (
                '<div class="sc-label">REQUIREMENTS → CHECKLIST</div>'
                '<div class="sc-checklist"><span class="sc-check-note">no structured'
                " requirements extracted — check the bid documents</span></div>"
            )

        addenda = sum(1 for d in o.documents if d.kind == "addendum")
        doc_rows = []
        for d in o.documents[:4]:
            kind = doc_kind_label(d.name, d.kind)
            add = d.kind == "addendum"
            url = esc(d.url) if d.url and d.url != "#" else ""
            name = (
                f'<a class="sc-doc-name" href="{url}" target="_blank" rel="noopener">{esc(d.name)}</a>'
                if url else f'<span class="sc-doc-name">{esc(d.name)}</span>'
            )
            doc_rows.append(
                f'<div class="sc-doc {"addendum" if add else ""}">{name}'
                f'<span class="sc-doc-kind {"crimson" if add else ""}">{kind}</span></div>'
            )
        if len(o.documents) > 4:
            doc_rows.append(
                f'<div class="sc-doc-more">+ {len(o.documents) - 4} more on the portal</div>'
            )
        if not o.documents:
            doc_rows.append('<div class="sc-doc-more">no documents published yet</div>')
        doc_title = f"BID DOCUMENTS ({len(o.documents)}" + (
            f" · {addenda} ADDENDUM)" if addenda else ")"
        )
        docs_block = (
            f'<div class="sc-label">{doc_title}</div>'
            f'<div class="sc-docs">{"".join(doc_rows)}</div>'
        )

        dates_html = []
        if o.posted_date:
            dates_html.append(
                f'<div class="sc-date-row"><span class="sc-date-dot"></span>'
                f"<div><b>{mon_day(o.posted_date)}</b> — posted</div></div>"
            )
        if o.questions_due:
            dates_html.append(
                f'<div class="sc-date-row"><span class="sc-date-dot"></span>'
                f"<div><b>{mon_day(o.questions_due.date())}</b> — questions closed</div></div>"
            )
        if o.pre_bid_meeting:
            dates_html.append(
                '<div class="sc-date-row"><span class="sc-date-dot"></span>'
                f"<div><b>pre-bid</b> — {esc(o.pre_bid_meeting)}</div></div>"
            )
        if o.due_date:
            where = f", {o.submittal_info}" if o.submittal_info else ""
            dates_html.append(
                '<div class="sc-date-row"><span class="sc-date-dot due"></span>'
                f'<div><b class="due-text">{esc(due_full(o.due_date))}</b> — bids due{esc(where)}</div></div>'
            )
        dates_block = (
            '<div class="sc-label">KEY DATES</div>'
            f'<div class="sc-dates">{"".join(dates_html) or "<span class=sc-doc-more>no dates published</span>"}</div>'
        )

        committed = [
            self.by_id[i] for i in self.active_tracked
            if us.stage_of(state, i) in ("preparing", "submitted")
        ]
        wl_hits = sum(
            1 for _, matches, _ in self._wl
            if any(m.opportunity_id == oid for m in matches)
        )
        meters = go_no_go(
            o,
            tracked=[self.by_id[i] for i in self.tracked_ids],
            committed=committed,
            watchlist_hits=wl_hits,
            results=state["results"],
            tracked_by_id={i: self.by_id[i] for i in self.tracked_ids},
        )
        meter_html = "".join(
            f'<div class="sc-meter-label" title="{esc(m.tooltip)}">{esc(m.label)}</div>'
            f'<div class="sc-meter {"last" if i == len(meters) - 1 else ""}" title="{esc(m.tooltip)}">'
            f'<div style="width:{m.score}%"></div></div>'
            for i, m in enumerate(meters)
        )
        gonogo_block = f"""
        <div class="sc-label">GO / NO-GO</div>
        <div class="sc-gonogo">
          {meter_html}
          <div class="sc-gonogo-btns">
            <a class="sc-btn-go {'chosen' if dec == 'go' else ''}"
               href="{href(act='go', id=oid, screen='workroom', bid=oid)}">GO — BID IT</a>
            <a class="sc-btn-nogo {'chosen' if dec == 'nogo' else ''}"
               href="{href(act='nogo', id=oid, screen='workroom', bid=oid)}">NO-GO</a>
          </div>
        </div>"""

        note_val = esc(state["notes"].get(oid, ""))
        notes_block = f"""
        <div class="sc-label">MY NOTES</div>
        <form class="sc-notes-form" method="get" action="/">
          <input type="hidden" name="screen" value="workroom">
          <input type="hidden" name="bid" value="{esc(oid)}">
          <input type="hidden" name="act" value="notes">
          <input type="hidden" name="id" value="{esc(oid)}">
          <textarea class="sc-notes" name="notes"
            placeholder="call Ray re: crane access on the west apron…">{note_val}</textarea>
          <button class="sc-notes-save" type="submit">SAVE NOTES</button>
        </form>"""

        left = '<div class="sc-label">SCOPE OF WORK</div>' + scope_card + check_block + docs_block
        right = dates_block + gonogo_block + notes_block
        return (
            head + banner
            + f'<div class="sc-wr-grid"><div>{left}</div><div>{right}</div></div>'
        )

    # -- Watchlists ---------------------------------------------------------

    def watchlists_html(self) -> str:
        head = f"""
        <div class="sc-head">
          <div class="sc-head-title">Watchlists</div>
          <a class="sc-btn sc-btn-ink" style="padding:5px 12px"
             href="{href(act='savewl', screen='watchlists')}">+ NEW WATCHLIST</a>
        </div>"""
        if not self.opps:
            return head + self.empty_state("No opportunities loaded")

        cards = []
        current = self._wl[0] if self._wl else None
        for wl, matches, new_ids in self._wl:
            active = wl["id"] == self.selected_wl_id
            if active:
                current = (wl, matches, new_ids)
            n_new = len(new_ids)
            f = wl.get("filters") or {}
            counties = f.get("counties") or (
                ["broward"] if "broward" in f.get("chips", []) else []
            )
            where = (
                " + ".join(COUNTY_LABELS.get(c, c) for c in counties)
                if counties else "all counties"
            )
            cards.append(f"""
            <div class="sc-wl-card {'active' if active else ''}">
              <a class="sc-row-link" href="{href(act='selwl', wl=wl['id'], screen='watchlists')}"></a>
              <div class="sc-wl-head">
                <span class="sc-wl-name">{esc(wl['name'])}</span>
                <span class="sc-wl-new {'zero' if not n_new else ''}">{f'{n_new} NEW' if n_new else '0 new'}</span>
              </div>
              <div class="sc-wl-meta">{esc(where)} · {len(matches)} matches · email: {esc(wl.get('email', 'off'))}</div>
            </div>""")

        chips = []
        for key, label in CHIP_DEFS:
            on = self.state["builder_chips"].get(key, False)
            chips.append(
                f'<a class="sc-chip {"on" if on else ""}" '
                f'href="{href(act="chip", id=key, screen="watchlists")}">{esc(label)}</a>'
            )
        n_chips = sum(1 for k, _ in CHIP_DEFS if self.state["builder_chips"].get(k))
        builder = f"""
        <div class="sc-builder">
          <div class="sc-label">BUILD FROM CHIPS</div>
          <div class="sc-chips">{''.join(chips)}</div>
          <div class="sc-builder-note">{n_chips} filters selected ·
            <a class="sc-builder-save" href="{href(act='savewl', screen='watchlists')}">save as watchlist</a></div>
        </div>"""

        match_rows = []
        wl_title = "MATCHES"
        if current:
            wl, matches, new_ids = current
            wl_title = f"{wl['name'].upper()} — MATCHES"
            matches = self.sort_opps(self.filter_opps(matches))
            for o in matches[:8]:
                oid = o.opportunity_id
                is_new = oid in new_ids
                tag = ' <span class="sc-match-tag">NEW</span>' if is_new else ""
                match_rows.append(f"""
                <div class="sc-match {'new' if is_new else ''}">
                  <a class="sc-row-link" href="{href(screen='watchlists', drawer=oid)}"></a>
                  <div class="sc-match-body">
                    <div class="sc-match-title">{esc(o.title)}{tag}</div>
                    <div class="sc-match-meta">{esc(meta_line(o, with_due=True))}</div>
                  </div>
                  <span class="sc-look">LOOK ›</span>
                </div>""")
            if not matches:
                match_rows.append(
                    '<div class="sc-match"><div class="sc-match-meta">no open bids match'
                    " this watchlist right now</div></div>"
                )

        right = f"""
        <div>
          <div class="sc-label">{esc(wl_title)}</div>
          <div class="sc-wl-col">{''.join(match_rows)}</div>
          <div class="sc-wl-footnote">"new" = posted since this watchlist was last opened
          · email alert sends the same list</div>
        </div>"""
        left = f'<div class="sc-wl-col">{"".join(cards)}{builder}</div>'
        return head + self.toolbar() + f'<div class="sc-wl-grid">{left}{right}</div>'

    # -- Sources ------------------------------------------------------------

    def sources_html(self) -> str:
        from src.sources.registry import load_source_config

        fetch_note = (
            f"fetched just now ({self.p.fetch_count} sources)" if self.p.fetched_now
            else f"last scan {self.scan_note()}"
        )
        head = f"""
        <div class="sc-head">
          <div class="sc-head-title">Sources</div>
          <div class="sc-head-note">{self.total_sources} sources · {len(COUNTY_LABELS)} counties · {esc(fetch_note)}</div>
        </div>"""
        if not self.health:
            return head + self.empty_state(
                "No source health yet",
                "Health is recorded on every fetch — run one from the sidebar",
            )

        kpis = f"""
        <div class="sc-kpis">
          <div class="sc-kpi"><div class="sc-kpi-num green">{self.ok_n}</div><div class="sc-kpi-label">OK</div></div>
          <div class="sc-kpi"><div class="sc-kpi-num">{self.empty_n}</div><div class="sc-kpi-label">NO LISTINGS</div></div>
          <div class="sc-kpi {'alert' if self.degraded_n else ''}"><div class="sc-kpi-num {'crimson' if self.degraded_n else ''}">{self.degraded_n}</div><div class="sc-kpi-label">DEGRADED</div></div>
          <div class="sc-kpi {'alert' if self.error_n else ''}"><div class="sc-kpi-num {'crimson' if self.error_n else ''}">{self.error_n}</div><div class="sc-kpi-label">ERROR</div></div>
        </div>"""

        attn_html = []
        if self.attention:
            attn_html.append('<div class="sc-label crimson">NEEDS ATTENTION</div>')
            shown = self.attention[:6]
            for i, h in enumerate(shown):
                note = h.note or h.error or "degraded"
                attn_html.append(f"""
                <div class="sc-attn {'last' if i == len(shown) - 1 else ''}">
                  <div class="sc-attn-name">{esc(h.name)}</div>
                  <div class="sc-attn-note">{esc(note[:110])}</div>
                </div>""")

        pool = list(self.health)
        if self.p.status in ("ok", "empty", "degraded", "error"):
            pool = [h for h in pool if _status(h) == self.p.status]
        sort_key = self.p.sort or ""
        if sort_key == "name":
            pool.sort(key=lambda h: h.name.lower())
        elif sort_key == "deals":
            pool.sort(key=lambda h: (-h.count, h.name.lower()))
        elif sort_key == "speed":
            pool.sort(key=lambda h: (h.elapsed_ms, h.name.lower()))

        filter_chips = []
        for key, label in SOURCE_STATUS_FILTERS:
            n = len(self.health) if not key else sum(
                1 for h in self.health if _status(h) == key
            )
            on = self.p.status == key
            filter_chips.append(
                f'<a class="sc-chip {"on" if on else ""}" '
                f'href="{href(**self.keep(f=key or None))}">{label} · {n}</a>'
            )
        filter_chips.append('<span class="sc-toolbar-label">SORT</span>')
        current_sort = sort_key or "config"
        for key, label in SOURCE_SORTS:
            on = current_sort == key
            filter_chips.append(
                f'<a class="sc-chip {"on" if on else ""}" '
                f'href="{href(**self.keep(sort=None if on else key))}">{label}</a>'
            )
        src_toolbar = f'<div class="sc-toolbar">{"".join(filter_chips)}</div>'

        limit = len(pool) if (self.p.all_sources or self.p.status or sort_key) else 8
        src_rows = []
        for h in pool[:limit]:
            status = _status(h)
            if status == "ok":
                plural = "" if h.count == 1 else "s"
                dot, stat = "", f"{h.count} deal{plural} · {h.elapsed_ms / 1000:.1f}s"
            elif status == "empty":
                dot, stat = "empty", "no listings"
            else:
                dot, stat = "bad", status
            src_rows.append(f"""
            <div class="sc-src">
              <span class="sc-src-name"><span class="sc-src-dot {dot}"></span>{esc(h.name)}</span>
              <span class="sc-src-stat">{esc(stat)}</span>
            </div>""")
        if len(pool) > limit:
            src_rows.append(
                f'<a class="sc-src-more" href="{href(**self.keep(allsrc="1"))}">'
                f"… {len(pool) - limit} more ▾</a>"
            )
        elif self.p.all_sources and len(pool) > 8:
            src_rows.append(
                f'<a class="sc-src-more" href="{href(**self.keep(allsrc=None))}">collapse ▴</a>'
            )
        if not pool:
            src_rows.append('<div class="sc-src-stat" style="padding:8px 0">no sources match this filter</div>')
        left = (
            "".join(attn_html)
            + '<div class="sc-label">ALL SOURCES</div>'
            + src_toolbar
            + f'<div class="sc-srclist">{"".join(src_rows)}</div>'
        )

        try:
            configured = " ".join(
                str(cfg.get("name", "")).lower() for cfg in load_source_config()
            )
        except Exception:
            configured = ""
        queued_names = {s.get("name") for s in self.state["queued_sources"]}
        gap_rows = []
        for name in SUGGESTED_SOURCES:
            if name.lower() in configured:
                continue
            queued = name in queued_names
            btn = (
                '<a class="sc-add queued">QUEUED ✓</a>' if queued
                else f'<a class="sc-add" href="{href(act="addsrc", name=name, screen="sources")}">+ ADD</a>'
            )
            gap_rows.append(f'<div class="sc-gap"><span>{esc(name)}</span>{btn}</div>')

        if self.p.detect_status == "ok":
            note_cls, note = "ok", "Detected: CivicPlus Bids module — queued as a config entry ✓"
        elif self.p.detect_status == "fail":
            note_cls, note = "fail", "no known bid-board module at that URL — CivicPlus (…/bids.aspx) auto-detects"
        else:
            note_cls, note = "", "CivicPlus boards auto-detect → a config entry, no code"
        n_queued = len(self.state["queued_sources"])
        queued_note = (
            f'<div class="sc-detect-note">{n_queued} queued for config/sources.yaml</div>'
            if n_queued else ""
        )
        right = f"""
        <div>
          <div class="sc-label">COVERAGE GAPS — ADD A SOURCE</div>
          <div class="sc-gaps">
            <div class="sc-gaps-title">Suggested next <span>(known portals, not wired up)</span></div>
            <div class="sc-gap-rows">{''.join(gap_rows) or '<span class="sc-detect-note">all suggested portals are configured</span>'}</div>
          </div>
          <div class="sc-detect-box">
            <div class="sc-detect-label">or paste any bid-board URL:</div>
            <form class="sc-detect-form" method="get" action="/">
              <input type="hidden" name="screen" value="sources">
              <input type="hidden" name="act" value="detect">
              <input class="sc-detect-input" type="text" name="url"
                     value="{esc(self.p.detect_url)}" placeholder="https://…/bids.aspx">
              <button class="sc-detect-btn" type="submit">DETECT</button>
            </form>
            <div class="sc-detect-note {note_cls}">{esc(note)}</div>
            {queued_note}
          </div>
        </div>"""
        return head + kpis + f'<div class="sc-src-grid"><div>{left}</div>{right}</div>'

    # -- Drawer -------------------------------------------------------------

    def drawer_html(self, o: Opportunity) -> str:
        oid = o.opportunity_id
        keep = self.keep(drawer=None)

        tags = [f'<span class="sc-tag">{esc(sol_label(o))}</span>']
        if offer_word(o):
            tags.append(f'<span class="sc-tag">{esc(offer_word(o).upper())}</span>')
        d = o.days_until_due
        if o.status in ("open", "upcoming") and d is not None and 0 <= d <= 3:
            label = "DUE TODAY" if d == 0 else f"DUE IN {d} DAY{'' if d == 1 else 'S'}"
            tags.append(f'<span class="sc-tag crimson">{label}</span>')
        elif o.posted_date == date.today():
            tags.append('<span class="sc-tag">NEW TODAY</span>')
        if o.status == "closed":
            tags.append('<span class="sc-tag">CLOSED</span>')
        if us.stage_of(self.state, oid) == "submitted":
            tags.append('<span class="sc-tag green">SUBMITTED</span>')
        if o.prior_cycles:
            tags.append(f'<span class="sc-tag green">REBID · {o.prior_cycles}X BEFORE</span>')

        facts: List[Tuple[str, str]] = []
        if o.budget:
            facts.append(("ESTIMATED VALUE", o.budget))
        if o.due_date:
            facts.append(("BIDS DUE", due_full(o.due_date)))
        if o.duration_days:
            facts.append(("DURATION", f"{o.duration_days} calendar days"))
        if o.liquidated_damages:
            facts.append(("LIQ. DAMAGES", o.liquidated_damages))
        if o.licenses:
            facts.append(("LICENCE", o.licenses))
        if o.pre_bid_meeting:
            facts.append(("PRE-BID", o.pre_bid_meeting))
        if o.questions_due:
            facts.append(("QUESTIONS DUE", mon_day(o.questions_due.date())))
        if o.project_location:
            facts.append(("LOCATION", o.project_location))
        if o.contact:
            contact = o.contact + (f" · {o.contact_phone}" if o.contact_phone else "")
            facts.append(("CONTACT", contact))
        if o.prior_cycles and o.last_cycle_closed:
            facts.append(
                ("LAST CYCLE", f"closed {mon_day(o.last_cycle_closed)} {o.last_cycle_closed.year}")
            )
        facts_html = "".join(
            f'<div><div class="sc-fact-label">{esc(k)}</div>'
            f'<div class="sc-fact-value">{esc(v)}</div></div>'
            for k, v in facts[:8]
        )

        scope = " ".join((o.scope or o.description or "").split())
        if len(scope) > 420:
            scope = scope[:419].rstrip() + "…"
        scope_html = (
            f'<div class="sc-label">SCOPE</div><div class="sc-drawer-scope">{esc(scope)}</div>'
            if scope else ""
        )

        reqs_html = ""
        if o.requirements:
            chips = "".join(
                f'<span class="sc-req-chip">{esc(r)}</span>' for r in o.requirements[:6]
            )
            reqs_html = (
                '<div class="sc-label">REQUIREMENTS TO BID</div>'
                f'<div class="sc-req-chips">{chips}</div>'
            )

        docs_html = ""
        if o.documents:
            rows = []
            for doc in o.documents[:5]:
                add = doc.kind == "addendum"
                kind = doc_kind_label(doc.name, doc.kind)
                url = esc(doc.url) if doc.url and doc.url != "#" else ""
                name = (
                    f'<a class="sc-doc-name" href="{url}" target="_blank" rel="noopener">{esc(doc.name)}</a>'
                    if url else f'<span class="sc-doc-name">{esc(doc.name)}</span>'
                )
                rows.append(
                    f'<div class="sc-doc">{name}'
                    f'<span class="sc-doc-kind {"crimson" if add else ""}">{kind}</span></div>'
                )
            if len(o.documents) > 5:
                rows.append(
                    f'<div class="sc-doc-more">+ {len(o.documents) - 5} more on the portal</div>'
                )
            docs_html = (
                '<div class="sc-label">DOCUMENTS</div>'
                f'<div class="sc-drawer-docs">{"".join(rows)}</div>'
            )

        workroom_btn = ""
        if oid in self.state["tracked"]:
            workroom_btn = (
                f'<a class="sc-btn sc-btn-primary" href="{href(screen="workroom", bid=oid)}">'
                "OPEN WORKROOM →</a>"
            )
        portal_btn = (
            f'<a class="sc-btn sc-btn-ink" href="{esc(o.url)}" target="_blank" rel="noopener">'
            "OFFICIAL PORTAL ↗</a>"
            if o.url and not o.url.startswith("https://example.com") else ""
        )

        meta_bits = [o.agency]
        if offer_word(o):
            meta_bits.append(offer_word(o))
        meta_bits.append(f"detail {o.detail_score}%")

        return f"""
        <a class="sc-overlay" href="{href(**keep)}" aria-label="Close"></a>
        <div class="sc-drawer">
          <div class="sc-drawer-top">
            <span class="sc-drawer-ref">{esc(o.external_id or o.source_name)}</span>
            <a class="sc-x" href="{href(**keep)}">✕</a>
          </div>
          <div class="sc-drawer-title">{esc(o.title)}</div>
          <div class="sc-drawer-meta">{esc(' · '.join(meta_bits))}</div>
          <div class="sc-tags">{''.join(tags)}</div>
          <div class="sc-facts">{facts_html}</div>
          {scope_html}
          {reqs_html}
          {docs_html}
          <div class="sc-drawer-foot">
            {self.track_btn(oid, **keep, drawer=oid)}
            {workroom_btn}
            {portal_btn}
          </div>
        </div>"""

    # -- Shell --------------------------------------------------------------

    def sidebar_html(self) -> str:
        fetch_cls, fetch_label = ("done", "FETCHED ✓") if self.p.fetched_now else ("", "FETCH LIVE DATA")
        nav = []
        for key, label in SCREENS:
            badge = self.nav_badges.get(key)
            badge_html = f'<span class="sc-nav-badge">{badge}</span>' if badge else ""
            nav.append(
                f'<a class="sc-nav-item {"active" if key == self.p.screen else ""}" '
                f'href="{href(screen=key)}"><span class="sc-nav-label">{esc(label)}</span>'
                f"{badge_html}</a>"
            )
        if self.p.fetched_now:
            foot_note = f"fetched just now ({self.p.fetch_count} sources)"
        elif self.snapshot_time:
            foot_note = f"fetched {self.scan_note()}"
        else:
            foot_note = "no snapshot yet"
        attn_html = (
            f'<div class="crimson">{len(self.attention)} need attention</div>'
            if self.attention else ""
        )
        counts = (
            f"{self.total_sources} sources · {self.ok_n} ok" if self.health
            else f"{self.total_sources} sources configured"
        )
        return f"""
        <div class="sc-side">
          <div class="sc-brand">
            <div class="sc-brand-name">SF Procurement Scout</div>
            <div class="sc-brand-sub">SOUTH FLORIDA BIDS</div>
          </div>
          <a class="sc-fetch {fetch_cls}" href="{href(act='fetch', screen=self.p.screen)}">{fetch_label}</a>
          <div class="sc-side-label">SCREENS</div>
          <div class="sc-nav">{''.join(nav)}</div>
          <div class="sc-side-foot">
            <div>{counts}</div>
            {attn_html}
            <div>{esc(foot_note)}</div>
          </div>
        </div>"""

    def render(self) -> str:
        renderers = {
            "calendar": self.calendar_html,
            "all": self.allbids_html,
            "pipeline": self.pipeline_html,
            "workroom": self.workroom_html,
            "watchlists": self.watchlists_html,
            "sources": self.sources_html,
        }
        main = renderers[self.p.screen]()
        drawer = ""
        if self.p.drawer and self.p.drawer in self.by_id:
            drawer = self.drawer_html(self.by_id[self.p.drawer])
        return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SF Procurement Scout</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>📋</text></svg>">
<link rel="stylesheet" href="/styles.css">
</head>
<body>
<div class="sc-app">{self.sidebar_html()}<div class="sc-main">{main}</div></div>
{drawer}
</body>
</html>"""
