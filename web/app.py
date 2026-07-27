"""SF Procurement Scout — polished pipeline UI (NG-Snapshot inspired)."""

from __future__ import annotations

import html
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.models.opportunity import Opportunity
from src.pipeline.runner import run_fetch
from src.pipeline.store import load_latest, save_snapshot
from src.summarize import apply_briefs, make_brief

# ---------------------------------------------------------------------------
# Page config + CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Procurement Pipeline · SF Scout",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS_PATH = Path(__file__).parent / "styles.css"
st.markdown(f"<style>{_CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COUNTY_LABELS = {
    "miami-dade": "Miami-Dade",
    "broward": "Broward",
    "palm-beach": "Palm Beach",
}
STATUS_ORDER = ["open", "upcoming", "catalog", "closed", "cancelled"]
STATUS_LABELS = {
    "open": "Open",
    "upcoming": "Upcoming",
    "catalog": "Catalog",
    "closed": "Closed",
    "cancelled": "Cancelled",
}
OFFER_COLORS = {
    "construction": "#085d80",
    "professional_services": "#6b4c9a",
    "services": "#04719e",
    "goods": "#157f3d",
    "mixed": "#9a6700",
    "unknown": "#697586",
}


def _init_state() -> None:
    defaults = {
        "stage_tab": "open",
        "county_filter": "All",
        "offer_filter": "All",
        "category_filter": "All",
        "agency_filter": "All",
        "query": "",
        "selected_id": None,
        "view_mode": "board",
        "include_catalog": False,
        "board_group": "county",
        "show_only_urgent": False,
        "do_fetch": False,
        "sort_by": "due_soon",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def esc(s: Optional[str]) -> str:
    return html.escape(str(s) if s is not None else "")


def sol_label(o: Opportunity) -> str:
    s = o.solicitation_type
    if hasattr(s, "value"):
        s = s.value
    s = str(s or "BID")
    return "BID" if s == "UNKNOWN" else s


def offer_key(o: Opportunity) -> str:
    s = o.offer_type
    if hasattr(s, "value"):
        s = s.value
    return str(s or "unknown")


def offer_label(o: Opportunity) -> str:
    return offer_key(o).replace("_", " ").title()


def ensure_brief(o: Opportunity) -> str:
    if o.brief and o.brief.strip():
        return o.brief
    return make_brief(o)


def short_brief(o: Opportunity, n: int = 140) -> str:
    b = ensure_brief(o)
    b = " ".join(b.split())
    return b if len(b) <= n else b[: n - 1] + "…"


def fmt_due(o: Opportunity) -> str:
    if not o.due_date:
        return STATUS_LABELS.get(o.status, o.status).title()
    d = o.due_date.strftime("%b %d, %Y")
    days = o.days_until_due
    if days is None:
        return d
    if days < 0:
        return f"{d} · past due"
    if days == 0:
        return f"{d} · DUE TODAY"
    if days == 1:
        return f"{d} · tomorrow"
    if days <= 7:
        return f"{d} · {days} days left"
    return f"{d} · {days}d left"


def urgency_badge(o: Opportunity) -> Tuple[str, str]:
    """Return (css_class, label)."""
    days = o.days_until_due
    if o.status in {"closed", "cancelled"}:
        return "muted", o.status
    if days is None:
        if o.status == "upcoming":
            return "info", "upcoming"
        return "ok", "open"
    if days < 0:
        return "muted", "past due"
    if days == 0:
        return "danger", "DUE TODAY"
    if days <= 3:
        return "danger", f"{days}d left"
    if days <= 7:
        return "warn", f"{days}d left"
    return "ok", f"{days}d left"


def sort_opps(opps: List[Opportunity]) -> List[Opportunity]:
    mode = st.session_state.sort_by

    def key(o: Opportunity):
        days = o.days_until_due if o.days_until_due is not None else 9999
        if mode == "due_soon":
            return (0 if o.status in {"open", "upcoming"} else 1, days, o.title.lower())
        if mode == "newest":
            pd = o.posted_date.toordinal() if o.posted_date else 0
            return (-pd, o.title.lower())
        if mode == "agency":
            return (o.agency.lower(), days, o.title.lower())
        return (o.title.lower(),)

    return sorted(opps, key=key)


def load_data(force: bool = False):
    if force:
        with st.spinner("Fetching live portals from Miami-Dade, Broward & Palm Beach…"):
            opps, health = run_fetch(
                include_catalog=st.session_state.include_catalog,
                open_only=False,
            )
            apply_briefs(opps)
            save_snapshot(opps, health, tag="dashboard")
            return opps, health
    opps, health = load_latest()
    # Always re-apply briefs so UI never shows blank summaries
    if opps:
        for o in opps:
            if not o.brief:
                o.brief = make_brief(o)
            else:
                # refresh timing language
                o.brief = make_brief(o)
    return opps, health


def apply_filters(opps: List[Opportunity]) -> List[Opportunity]:
    county = st.session_state.county_filter
    offer = st.session_state.offer_filter
    cat = st.session_state.category_filter
    agency = st.session_state.agency_filter
    q = (st.session_state.query or "").strip().lower()
    stage = st.session_state.stage_tab

    out = list(opps)
    if county != "All":
        # map label back to key
        inv = {v: k for k, v in COUNTY_LABELS.items()}
        key = inv.get(county, county.lower().replace(" ", "-"))
        out = [o for o in out if o.county == key]
    if offer != "All":
        ot = offer.lower().replace(" ", "_")
        out = [o for o in out if offer_key(o) == ot]
    if cat != "All":
        ck = cat.lower().replace(" ", "_")
        out = [o for o in out if ck in [c.lower() for c in (o.categories or [])]]
    if agency != "All":
        out = [o for o in out if o.agency == agency]
    if q:
        out = [
            o
            for o in out
            if q in (o.title or "").lower()
            or q in (o.agency or "").lower()
            or q in (o.brief or "").lower()
            or q in (o.external_id or "").lower()
            or q in (o.description or "").lower()
        ]
    if stage == "open":
        out = [o for o in out if o.status in {"open", "upcoming"}]
    elif stage != "all":
        out = [o for o in out if o.status == stage]
    if st.session_state.show_only_urgent:
        out = [
            o
            for o in out
            if o.days_until_due is not None and 0 <= o.days_until_due <= 7
        ]
    return sort_opps(out)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

if st.session_state.do_fetch:
    all_opps, health = load_data(force=True)
    st.session_state.do_fetch = False
    st.session_state.selected_id = None
else:
    all_opps, health = load_data(force=False)

# Sidebar always visible — even when empty
with st.sidebar:
    st.markdown(
        """
        <div class="ng-brand">
          <div class="ng-brand-mark">SF</div>
          <div>
            <div class="ng-brand-name">SF Procure Scout</div>
            <div class="ng-brand-sub">South Florida bids</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ng-nav-section">Actions</div>', unsafe_allow_html=True)
    if st.button("🔄  Fetch live data", type="primary", use_container_width=True):
        st.session_state.do_fetch = True
        st.rerun()
    st.session_state.include_catalog = st.checkbox(
        "Include catalog portals",
        value=st.session_state.include_catalog,
        help="DemandStar / Bidnet / VSS registration entries",
    )
    st.session_state.show_only_urgent = st.checkbox(
        "Urgent only (≤ 7 days)",
        value=st.session_state.show_only_urgent,
    )

    st.markdown('<div class="ng-nav-section">Filters</div>', unsafe_allow_html=True)

    # Stable selectbox menus — never disappear on click
    county_opts = ["All"] + [COUNTY_LABELS[k] for k in COUNTY_LABELS]
    st.session_state.county_filter = st.selectbox(
        "County",
        county_opts,
        index=county_opts.index(st.session_state.county_filter)
        if st.session_state.county_filter in county_opts
        else 0,
    )

    # Build option lists from data
    if all_opps:
        offer_opts = ["All"] + sorted(
            {
                offer_key(o).replace("_", " ").title()
                for o in all_opps
                if offer_key(o) != "unknown"
            }
        )
        cat_opts = ["All"] + sorted(
            {
                c.replace("_", " ").title()
                for o in all_opps
                for c in (o.categories or [])
                if c != "portal_directory"
            }
        )
        agency_opts = ["All"] + sorted({o.agency for o in all_opps if o.agency})
    else:
        offer_opts, cat_opts, agency_opts = ["All"], ["All"], ["All"]

    if st.session_state.offer_filter not in offer_opts:
        st.session_state.offer_filter = "All"
    if st.session_state.category_filter not in cat_opts:
        st.session_state.category_filter = "All"
    if st.session_state.agency_filter not in agency_opts:
        st.session_state.agency_filter = "All"

    st.session_state.offer_filter = st.selectbox(
        "Offer type",
        offer_opts,
        index=offer_opts.index(st.session_state.offer_filter),
    )
    st.session_state.category_filter = st.selectbox(
        "Category",
        cat_opts,
        index=cat_opts.index(st.session_state.category_filter),
    )
    st.session_state.agency_filter = st.selectbox(
        "Agency",
        agency_opts,
        index=agency_opts.index(st.session_state.agency_filter),
    )

    st.session_state.sort_by = st.selectbox(
        "Sort by",
        ["due_soon", "newest", "agency", "title"],
        format_func=lambda x: {
            "due_soon": "Due soonest",
            "newest": "Newest posted",
            "agency": "Agency A–Z",
            "title": "Title A–Z",
        }[x],
        index=["due_soon", "newest", "agency", "title"].index(st.session_state.sort_by),
    )

    st.session_state.board_group = st.selectbox(
        "Board columns",
        ["county", "status", "offer_type"],
        format_func=lambda x: {
            "county": "By county",
            "status": "By status",
            "offer_type": "By offer type",
        }[x],
        index=["county", "status", "offer_type"].index(st.session_state.board_group),
    )

    if st.button("Clear all filters", use_container_width=True):
        st.session_state.county_filter = "All"
        st.session_state.offer_filter = "All"
        st.session_state.category_filter = "All"
        st.session_state.agency_filter = "All"
        st.session_state.query = ""
        st.session_state.stage_tab = "open"
        st.session_state.show_only_urgent = False
        st.session_state.selected_id = None
        st.rerun()

    st.markdown("---")
    st.markdown('<div class="ng-nav-section">View</div>', unsafe_allow_html=True)
    st.session_state.view_mode = st.radio(
        "Layout",
        ["board", "list", "insights"],
        format_func=lambda x: {"board": "🗂  Board", "list": "📋  List + detail", "insights": "📊  Insights"}[x],
        index=["board", "list", "insights"].index(st.session_state.view_mode),
        label_visibility="collapsed",
    )

    if health:
        ok = sum(1 for h in health if h.ok)
        st.caption(f"Sources: {ok}/{len(health)} healthy · {len(all_opps)} deals loaded")
    if os.environ.get("RENDER"):
        st.caption("Render free tier may sleep when idle")

# Empty state
if not all_opps:
    st.markdown(
        """
        <div class="ng-hero">
          <h1>Procurement Pipeline</h1>
          <p>Live government bids across Miami-Dade, Broward &amp; Palm Beach</p>
        </div>
        <div class="ng-empty">
          <div class="ng-empty-icon">📥</div>
          <div class="ng-empty-title">No opportunities loaded</div>
          <div>Use <strong>Fetch live data</strong> in the left menu to pull from county portals.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

visible = apply_filters(all_opps)
open_pool = [o for o in all_opps if o.status in {"open", "upcoming"}]
# filtered open for KPIs
open_vis = [o for o in visible if o.status in {"open", "upcoming"}]
urgent = [o for o in open_vis if o.days_until_due is not None and 0 <= o.days_until_due <= 7]
due_today = [o for o in open_vis if o.days_until_due is not None and o.days_until_due == 0]

# Index for selection
by_id: Dict[str, Opportunity] = {o.opportunity_id: o for o in all_opps}
selected = by_id.get(st.session_state.selected_id) if st.session_state.selected_id else None

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown(
    f"""
    <div class="ng-hero">
      <div class="ng-hero-row">
        <div>
          <h1>Procurement Pipeline</h1>
          <p>Miami-Dade · Broward · Palm Beach &nbsp;·&nbsp;
             <strong>{len(open_vis)}</strong> open in view &nbsp;·&nbsp;
             <strong>{len(visible)}</strong> matching filters</p>
        </div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# KPIs
st.markdown(
    f"""
    <div class="ng-kpi-grid">
      <div class="ng-kpi">
        <div class="ng-kpi-label">Open in view</div>
        <div class="ng-kpi-value">{len(open_vis)}</div>
        <div class="ng-kpi-sub">{len(open_pool)} open system-wide</div>
      </div>
      <div class="ng-kpi {'urgent' if urgent else ''}">
        <div class="ng-kpi-label">Due within 7 days</div>
        <div class="ng-kpi-value">{len(urgent)}</div>
        <div class="ng-kpi-sub">priority response window</div>
      </div>
      <div class="ng-kpi {'urgent' if due_today else ''}">
        <div class="ng-kpi-label">Due today</div>
        <div class="ng-kpi-value">{len(due_today)}</div>
        <div class="ng-kpi-sub">closes end of day</div>
      </div>
      <div class="ng-kpi">
        <div class="ng-kpi-label">Matching filters</div>
        <div class="ng-kpi-value">{len(visible)}</div>
        <div class="ng-kpi-sub">{len(all_opps)} total loaded</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Search + stage tabs
s1, s2 = st.columns([3, 1])
with s1:
    q = st.text_input(
        "Search deals",
        value=st.session_state.query,
        placeholder="Search title, agency, ref #, or summary…",
        label_visibility="collapsed",
    )
    if q != st.session_state.query:
        st.session_state.query = q
        st.rerun()
with s2:
    st.markdown(
        f'<div class="ng-result-pill">{len(visible)} results</div>',
        unsafe_allow_html=True,
    )

# Stage tabs
tab_keys = ["open", "upcoming", "closed", "catalog", "all"]
tab_labels = {
    "open": "All open",
    "upcoming": "Upcoming",
    "closed": "Closed",
    "catalog": "Catalog",
    "all": "Everything",
}
tcols = st.columns(len(tab_keys))
for i, key in enumerate(tab_keys):
    saved = st.session_state.stage_tab
    st.session_state.stage_tab = key
    n = len(apply_filters(all_opps))
    st.session_state.stage_tab = saved
    with tcols[i]:
        active = st.session_state.stage_tab == key
        if st.button(
            f"{tab_labels[key]} ({n})",
            key=f"stage_{key}",
            use_container_width=True,
            type="primary" if active else "secondary",
        ):
            st.session_state.stage_tab = key
            st.rerun()

# Active filter chips (display only)
chips = []
if st.session_state.county_filter != "All":
    chips.append(st.session_state.county_filter)
if st.session_state.offer_filter != "All":
    chips.append(st.session_state.offer_filter)
if st.session_state.category_filter != "All":
    chips.append(st.session_state.category_filter)
if st.session_state.agency_filter != "All":
    chips.append(st.session_state.agency_filter[:36])
if st.session_state.show_only_urgent:
    chips.append("Urgent ≤7d")
if chips:
    st.markdown(
        '<div class="ng-chips">'
        + "".join(f'<span class="ng-chip active">{esc(c)}</span>' for c in chips)
        + "</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Card / list renderers
# ---------------------------------------------------------------------------

def card_html(o: Opportunity, selected: bool = False) -> str:
    ucss, ulabel = urgency_badge(o)
    brief = short_brief(o, 160)
    color = OFFER_COLORS.get(offer_key(o), OFFER_COLORS["unknown"])
    ref = esc(o.external_id) if o.external_id else ""
    return f"""
    <div class="deal-card {'selected' if selected else ''}" style="--accent-bar:{color}">
      <div class="deal-card-top">
        <span class="deal-type">{esc(sol_label(o))}</span>
        <span class="deal-urgency {ucss}">{esc(ulabel)}</span>
      </div>
      <div class="deal-title">{esc(o.title)}</div>
      <div class="deal-agency">{esc(o.agency)}
        · {esc(COUNTY_LABELS.get(o.county, o.county))}
        · {esc(offer_label(o))}
      </div>
      <div class="deal-brief">{esc(brief)}</div>
      <div class="deal-foot">
        <span class="deal-due">📅 {esc(fmt_due(o))}</span>
        {f'<span class="deal-ref">{ref}</span>' if ref else ''}
      </div>
    </div>
    """


def render_deal_actions(o: Opportunity, key: str) -> None:
    """Working portal link + select for summary."""
    c1, c2 = st.columns([1, 1])
    with c1:
        # Native Streamlit link — always works
        st.link_button("🔗 Portal", o.url or "#", use_container_width=True)
    with c2:
        is_sel = st.session_state.selected_id == o.opportunity_id
        if st.button(
            "✓ Selected" if is_sel else "📄 Summary",
            key=key,
            use_container_width=True,
            type="primary" if is_sel else "secondary",
        ):
            st.session_state.selected_id = (
                None if is_sel else o.opportunity_id
            )
            # Prefer list layout so summary is visible
            if st.session_state.view_mode == "board" and not is_sel:
                st.session_state.view_mode = "list"
            st.rerun()


def render_summary_panel(o: Opportunity) -> None:
    ucss, ulabel = urgency_badge(o)
    brief = ensure_brief(o)
    due = fmt_due(o)
    cats = ", ".join(c.replace("_", " ") for c in (o.categories or [])) or "—"
    keywords = ", ".join(o.keywords[:8]) if o.keywords else "—"

    st.markdown(
        f"""
        <div class="summary-panel">
          <div class="summary-eyebrow">Deal summary</div>
          <h2>{esc(o.title)}</h2>
          <div class="summary-tags">
            <span class="ng-card-tag">{esc(sol_label(o))}</span>
            <span class="ng-card-tag">{esc(offer_label(o))}</span>
            <span class="ng-card-tag {ucss}">{esc(ulabel)}</span>
            <span class="ng-card-tag">{esc(STATUS_LABELS.get(o.status, o.status))}</span>
            {f'<span class="ng-card-tag">{esc(o.external_id)}</span>' if o.external_id else ''}
          </div>
          <div class="summary-block">
            <div class="summary-label">Brief</div>
            <div class="summary-text">{esc(brief)}</div>
          </div>
          <div class="summary-grid">
            <div><div class="summary-label">Agency</div><div class="summary-text">{esc(o.agency)}</div></div>
            <div><div class="summary-label">County</div><div class="summary-text">{esc(COUNTY_LABELS.get(o.county, o.county))}</div></div>
            <div><div class="summary-label">Due</div><div class="summary-text">{esc(due)}</div></div>
            <div><div class="summary-label">Posted</div><div class="summary-text">{esc(o.posted_date.isoformat() if o.posted_date else "—")}</div></div>
            <div><div class="summary-label">Department</div><div class="summary-text">{esc(o.department or "—")}</div></div>
            <div><div class="summary-label">Budget</div><div class="summary-text">{esc(o.budget or "—")}</div></div>
            <div><div class="summary-label">Categories</div><div class="summary-text">{esc(cats)}</div></div>
            <div><div class="summary-label">Keywords</div><div class="summary-text">{esc(keywords)}</div></div>
            <div><div class="summary-label">Contact</div><div class="summary-text">{esc(o.contact or "—")}</div></div>
            <div><div class="summary-label">Source</div><div class="summary-text">{esc(o.source_name)}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    a1, a2, a3 = st.columns(3)
    with a1:
        st.link_button("Open official portal ↗", o.url or "#", use_container_width=True, type="primary")
    with a2:
        # mailto share stub
        subject = quote(f"Bid opportunity: {o.title[:80]}")
        body = quote(f"{brief}\n\nPortal: {o.url}")
        st.link_button(
            "Share via email",
            f"mailto:?subject={subject}&body={body}",
            use_container_width=True,
        )
    with a3:
        if st.button("Close summary", use_container_width=True):
            st.session_state.selected_id = None
            st.rerun()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

view = st.session_state.view_mode

if not visible:
    st.markdown(
        """
        <div class="ng-empty">
          <div class="ng-empty-icon">🔎</div>
          <div class="ng-empty-title">No deals match these filters</div>
          <div>Clear filters in the sidebar or switch stage tabs.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
elif view == "insights":
    # Funnel + hot list + category breakdown (preserve stage/urgent toggles)
    saved_stage = st.session_state.stage_tab
    saved_urgent = st.session_state.show_only_urgent
    st.session_state.stage_tab = "all"
    st.session_state.show_only_urgent = False
    all_filtered = apply_filters(all_opps)
    st.session_state.stage_tab = saved_stage
    st.session_state.show_only_urgent = saved_urgent

    left, right = st.columns(2)
    with left:
        stages = ["open", "upcoming", "catalog", "closed"]
        rows = []
        max_n = 1
        for sk in stages:
            n = sum(1 for o in all_filtered if o.status == sk)
            max_n = max(max_n, n)
            rows.append((STATUS_LABELS[sk], n))
        html_rows = []
        for label, n in rows:
            pct = int(100 * n / max_n) if max_n else 0
            html_rows.append(
                f"""
                <div class="ng-funnel-row">
                  <span>{esc(label)}</span>
                  <div class="ng-bar-track"><div class="ng-bar-fill" style="width:{pct}%"></div></div>
                  <span class="ng-bar-value">{n}</span>
                </div>
                """
            )
        st.markdown(
            f"""
            <div class="ng-panel">
              <div class="ng-panel-head">
                <div class="ng-panel-title">Status funnel</div>
                <div class="ng-panel-sub">{len(all_filtered)} filtered</div>
              </div>
              {''.join(html_rows)}
            </div>
            """,
            unsafe_allow_html=True,
        )

        cat_c: Counter = Counter()
        for o in all_filtered:
            for c in o.categories or ["general"]:
                if c != "portal_directory":
                    cat_c[c] += 1
        top_cats = cat_c.most_common(8)
        max_c = top_cats[0][1] if top_cats else 1
        crow = []
        for c, n in top_cats:
            pct = int(100 * n / max_c) if max_c else 0
            crow.append(
                f"""
                <div class="ng-funnel-row">
                  <span>{esc(c.replace('_', ' '))}</span>
                  <div class="ng-bar-track"><div class="ng-bar-fill" style="width:{pct}%"></div></div>
                  <span class="ng-bar-value">{n}</span>
                </div>
                """
            )
        st.markdown(
            f"""
            <div class="ng-panel" style="margin-top:12px">
              <div class="ng-panel-head">
                <div class="ng-panel-title">Top categories</div>
              </div>
              {''.join(crow) if crow else '<div class="ng-empty-title">No categories</div>'}
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right:
        hot = sort_opps(
            [
                o
                for o in all_filtered
                if o.status in {"open", "upcoming"}
                and o.days_until_due is not None
                and 0 <= o.days_until_due <= 14
            ]
        )[:10]
        st.markdown(
            f"""
            <div class="ng-panel">
              <div class="ng-panel-head">
                <div class="ng-panel-title">Hot pipeline (next 14 days)</div>
                <div class="ng-panel-sub">{len(hot)} deals</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if not hot:
            st.info("No open deals due in the next 14 days with current filters.")
        for o in hot:
            st.markdown(card_html(o), unsafe_allow_html=True)
            render_deal_actions(o, key=f"ins_{o.opportunity_id}")

elif view == "board":
    group = st.session_state.board_group
    buckets: Dict[str, List[Opportunity]] = defaultdict(list)
    for o in visible:
        if group == "county":
            k = COUNTY_LABELS.get(o.county, o.county)
        elif group == "offer_type":
            k = offer_label(o)
        else:
            k = STATUS_LABELS.get(o.status, o.status)
        buckets[k].append(o)

    if group == "status":
        order = [STATUS_LABELS[s] for s in STATUS_ORDER if STATUS_LABELS[s] in buckets]
        for k in buckets:
            if k not in order:
                order.append(k)
    elif group == "county":
        order = [COUNTY_LABELS[k] for k in COUNTY_LABELS if COUNTY_LABELS[k] in buckets]
        for k in buckets:
            if k not in order:
                order.append(k)
    else:
        order = sorted(buckets.keys(), key=lambda x: (-len(buckets[x]), x))

    # Show up to 4 columns side by side for readability
    n = min(len(order), 4)
    if n == 0:
        st.info("No columns to show.")
    else:
        cols = st.columns(n)
        for i, name in enumerate(order[:n]):
            items = sort_opps(buckets[name])
            with cols[i]:
                st.markdown(
                    f"""
                    <div class="board-col-head">
                      <span>{esc(name)}</span>
                      <span class="board-count">{len(items)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for o in items[:15]:
                    sel = st.session_state.selected_id == o.opportunity_id
                    st.markdown(card_html(o, selected=sel), unsafe_allow_html=True)
                    render_deal_actions(o, key=f"bd_{i}_{o.opportunity_id}")
                if len(items) > 15:
                    st.caption(f"+ {len(items) - 15} more in this column")
        if len(order) > n:
            with st.expander(f"More columns ({len(order) - n})"):
                for name in order[n:]:
                    st.markdown(f"### {name} ({len(buckets[name])})")
                    for o in sort_opps(buckets[name])[:8]:
                        st.markdown(card_html(o), unsafe_allow_html=True)
                        render_deal_actions(o, key=f"bx_{name}_{o.opportunity_id}")

else:  # list + persistent detail pane
    list_col, detail_col = st.columns([1.15, 1], gap="large")
    with list_col:
        st.markdown(
            f'<div class="list-head">Deals <span class="board-count">{len(visible)}</span></div>',
            unsafe_allow_html=True,
        )
        for o in visible[:80]:
            sel = st.session_state.selected_id == o.opportunity_id
            st.markdown(card_html(o, selected=sel), unsafe_allow_html=True)
            render_deal_actions(o, key=f"ls_{o.opportunity_id}")
        if len(visible) > 80:
            st.caption(f"Showing 80 of {len(visible)} — refine filters to narrow.")

    with detail_col:
        st.markdown('<div class="list-head">Deal summary</div>', unsafe_allow_html=True)
        if selected:
            render_summary_panel(selected)
        else:
            # Auto-preview first urgent or first item
            preview = (urgent or open_vis or visible)
            if preview:
                st.caption("Select **Summary** on a deal, or reviewing top match:")
                render_summary_panel(preview[0])
            else:
                st.markdown(
                    """
                    <div class="ng-empty">
                      <div class="ng-empty-title">Select a deal</div>
                      <div>Click <strong>Summary</strong> on any card to open the full brief here.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

# Floating summary when selected from board/insights
if selected and view in {"board", "insights"}:
    st.markdown("---")
    render_summary_panel(selected)

# Footer sources health (compact)
if health:
    with st.expander("Source health", expanded=False):
        rows = [
            {
                "Source": h.name,
                "Status": "OK" if h.ok else "Error",
                "Deals": h.count,
                "ms": h.elapsed_ms,
                "Error": (h.error or "")[:80],
            }
            for h in health
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
