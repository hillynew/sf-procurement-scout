"""SF Procurement Scout — NG-Snapshot-style pipeline UI."""

from __future__ import annotations

import html
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from src.models.opportunity import Opportunity
from src.pipeline.runner import filter_opportunities, run_fetch
from src.pipeline.store import load_latest, save_snapshot

# ---------------------------------------------------------------------------
# Page + styles
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Procurement Pipeline · SF Scout",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

_CSS = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")
st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Session defaults
# ---------------------------------------------------------------------------

def _init_state() -> None:
    defaults = {
        "nav": "pipeline",  # pipeline | sources | health
        "stage_tab": "open",  # open | upcoming | closed | catalog | all
        "county": None,
        "category": None,
        "offer_type": None,
        "agency": None,
        "query": "",
        "selected_id": None,
        "view_mode": "board",  # board | list | insights
        "include_catalog": False,
        "board_group": "status",  # status | county | offer_type
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()

# ---------------------------------------------------------------------------
# Helpers
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


def esc(s: Optional[str]) -> str:
    return html.escape(s or "")


def fmt_due(o: Opportunity) -> str:
    if not o.due_date:
        return STATUS_LABELS.get(o.status, o.status)
    d = o.due_date.strftime("%b %d")
    days = o.days_until_due
    if days is None:
        return d
    if days < 0:
        return f"{d} · closed"
    if days == 0:
        return f"{d} · TODAY"
    if days <= 7:
        return f"{d} · {days}d"
    return f"{d} · {days}d"


def urgency_class(o: Opportunity) -> str:
    days = o.days_until_due
    if days is None:
        return ""
    if 0 <= days <= 3:
        return "danger"
    if 0 <= days <= 7:
        return "warn"
    return "ok"


def sol_label(o: Opportunity) -> str:
    s = o.solicitation_type
    if hasattr(s, "value"):
        s = s.value
    return str(s or "BID")


def offer_label(o: Opportunity) -> str:
    s = o.offer_type
    if hasattr(s, "value"):
        s = s.value
    return str(s or "unknown").replace("_", " ")


def load_data(force_fetch: bool = False, include_catalog: bool = False):
    if force_fetch:
        with st.spinner("Fetching live portals (30–90s)…"):
            opps, health = run_fetch(include_catalog=include_catalog, open_only=False)
            save_snapshot(opps, health, tag="dashboard")
            return opps, health
    opps, health = load_latest()
    return opps, health


def apply_nav_filters(opps: List[Opportunity]) -> List[Opportunity]:
    """Apply session filters (not stage tab — that is separate)."""
    return filter_opportunities(
        opps,
        open_only=False,
        county=st.session_state.county,
        category=st.session_state.category,
        offer_type=st.session_state.offer_type,
        query=st.session_state.query or None,
    )


def apply_stage(opps: List[Opportunity]) -> List[Opportunity]:
    tab = st.session_state.stage_tab
    if tab == "all":
        return opps
    if tab == "open":
        return [o for o in opps if o.status in {"open", "upcoming"}]
    return [o for o in opps if o.status == tab]


def by_agency_filter(opps: List[Opportunity]) -> List[Opportunity]:
    if not st.session_state.agency:
        return opps
    return [o for o in opps if o.agency == st.session_state.agency]


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------

if "do_fetch" not in st.session_state:
    st.session_state.do_fetch = False

all_opps, health = load_data(
    force_fetch=st.session_state.do_fetch,
    include_catalog=st.session_state.include_catalog,
)
if st.session_state.do_fetch:
    st.session_state.do_fetch = False

if not all_opps:
    # Empty state with fetch CTA
    st.markdown(
        """
        <div class="ng-topbar">
          <div>
            <h1>Procurement Pipeline</h1>
            <div class="sub">Miami-Dade · Broward · Palm Beach government bids</div>
          </div>
        </div>
        <div class="ng-empty">
          <div class="ng-empty-title">No opportunities loaded yet</div>
          <div>Click <strong>Fetch live data</strong> in the sidebar to pull from county portals.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.sidebar:
        st.markdown(
            """
            <div class="ng-brand">
              <div class="ng-brand-mark">SF</div>
              <div>
                <div class="ng-brand-name">SF Procure Scout</div>
                <div class="ng-brand-sub">Pipeline</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Fetch live data", type="primary", use_container_width=True):
            st.session_state.do_fetch = True
            st.rerun()
    st.stop()

# Pre-compute counts for nav badges (from full set)
county_counts = Counter(o.county for o in all_opps)
category_counts: Counter = Counter()
for o in all_opps:
    for c in o.categories or ["general"]:
        category_counts[c] += 1
offer_counts = Counter(
    (o.offer_type.value if hasattr(o.offer_type, "value") else str(o.offer_type or "unknown"))
    for o in all_opps
)
agency_counts = Counter(o.agency for o in all_opps)
status_counts = Counter(o.status for o in all_opps)

# Filtered set
base = apply_nav_filters(all_opps)
base = by_agency_filter(base)
visible = apply_stage(base)

open_opps = [o for o in base if o.status in {"open", "upcoming"}]
urgent = [
    o
    for o in open_opps
    if o.days_until_due is not None and 0 <= o.days_until_due <= 7
]
due_today = [
    o for o in open_opps if o.days_until_due is not None and o.days_until_due == 0
]

# ---------------------------------------------------------------------------
# Sidebar — brand + drill-down menus (NG-Snapshot style)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div class="ng-brand">
          <div class="ng-brand-mark">SF</div>
          <div>
            <div class="ng-brand-name">SF Procure Scout</div>
            <div class="ng-brand-sub">Pipeline</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Primary nav
    if st.button(
        "📊  Pipeline",
        use_container_width=True,
        type="primary" if st.session_state.nav == "pipeline" else "secondary",
    ):
        st.session_state.nav = "pipeline"
        st.session_state.selected_id = None
        st.rerun()

    # --- Drill-down: County ---
    with st.expander("County", expanded=bool(st.session_state.county)):
        if st.button(
            f"All counties  ·  {len(all_opps)}",
            key="nav_county_all",
            use_container_width=True,
        ):
            st.session_state.county = None
            st.rerun()
        for ck, label in COUNTY_LABELS.items():
            n = county_counts.get(ck, 0)
            active = st.session_state.county == ck
            if st.button(
                f"{'▸ ' if active else '  '}{label}  ·  {n}",
                key=f"nav_county_{ck}",
                use_container_width=True,
            ):
                st.session_state.county = ck
                st.session_state.nav = "pipeline"
                st.rerun()

    # --- Drill-down: Offer type ---
    with st.expander("Offer type", expanded=bool(st.session_state.offer_type)):
        if st.button("All offer types", key="nav_offer_all", use_container_width=True):
            st.session_state.offer_type = None
            st.rerun()
        for ot, n in offer_counts.most_common():
            if not ot or ot == "unknown":
                continue
            label = ot.replace("_", " ").title()
            active = st.session_state.offer_type == ot
            if st.button(
                f"{'▸ ' if active else '  '}{label}  ·  {n}",
                key=f"nav_offer_{ot}",
                use_container_width=True,
            ):
                st.session_state.offer_type = ot
                st.session_state.nav = "pipeline"
                st.rerun()

    # --- Drill-down: Category ---
    with st.expander("Category", expanded=bool(st.session_state.category)):
        if st.button("All categories", key="nav_cat_all", use_container_width=True):
            st.session_state.category = None
            st.rerun()
        for cat, n in category_counts.most_common(12):
            if cat == "portal_directory":
                continue
            label = cat.replace("_", " ").title()
            active = st.session_state.category == cat
            if st.button(
                f"{'▸ ' if active else '  '}{label}  ·  {n}",
                key=f"nav_cat_{cat}",
                use_container_width=True,
            ):
                st.session_state.category = cat
                st.session_state.nav = "pipeline"
                st.rerun()

    # --- Drill-down: Agency ---
    with st.expander("Agency", expanded=bool(st.session_state.agency)):
        if st.button("All agencies", key="nav_agency_all", use_container_width=True):
            st.session_state.agency = None
            st.rerun()
        for ag, n in agency_counts.most_common(15):
            active = st.session_state.agency == ag
            short = ag if len(ag) <= 28 else ag[:26] + "…"
            if st.button(
                f"{'▸ ' if active else '  '}{short}  ·  {n}",
                key=f"nav_ag_{hash(ag)}",
                use_container_width=True,
            ):
                st.session_state.agency = ag
                st.session_state.nav = "pipeline"
                st.rerun()

    # --- Sources / health ---
    with st.expander("Sources", expanded=st.session_state.nav == "sources"):
        if st.button("Source health", key="nav_health", use_container_width=True):
            st.session_state.nav = "sources"
            st.rerun()
        st.caption("Live adapters + catalog portals")

    st.markdown("---")
    st.session_state.include_catalog = st.checkbox(
        "Include catalog portals",
        value=st.session_state.include_catalog,
    )
    if st.button("Fetch live data", type="primary", use_container_width=True):
        st.session_state.do_fetch = True
        st.rerun()

    if os.environ.get("RENDER"):
        st.caption("Running on Render · free tier sleeps when idle")

# ---------------------------------------------------------------------------
# Main — Pipeline view
# ---------------------------------------------------------------------------

if st.session_state.nav == "sources":
    st.markdown(
        """
        <div class="ng-topbar">
          <div>
            <h1>Sources</h1>
            <div class="sub">Portal health from last fetch</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if health:
        rows = [
            {
                "Source": h.name,
                "OK": "✓" if h.ok else "✗",
                "Count": h.count,
                "ms": h.elapsed_ms,
                "Error": h.error or "",
            }
            for h in health
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No health data yet. Run a live fetch.")
    st.stop()

# --- Topbar ---
view_mode = st.session_state.view_mode
c_title, c_actions = st.columns([3, 2])
with c_title:
    st.markdown(
        f"""
        <div class="ng-topbar" style="border:none;margin:0;padding:0">
          <div>
            <h1>Procurement Pipeline</h1>
            <div class="sub">
              Miami-Dade · Broward · Palm Beach
              · {len(open_opps)} open
              · {len(visible)} shown
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with c_actions:
    m1, m2, m3 = st.columns(3)
    if m1.button("Insights", use_container_width=True, type="primary" if view_mode == "insights" else "secondary"):
        st.session_state.view_mode = "insights"
        st.rerun()
    if m2.button("Board", use_container_width=True, type="primary" if view_mode == "board" else "secondary"):
        st.session_state.view_mode = "board"
        st.rerun()
    if m3.button("List", use_container_width=True, type="primary" if view_mode == "list" else "secondary"):
        st.session_state.view_mode = "list"
        st.rerun()

# --- KPI strip ---
st.markdown(
    f"""
    <div class="ng-kpi-grid">
      <div class="ng-kpi">
        <div class="ng-kpi-label">Open pipeline</div>
        <div class="ng-kpi-value">{len(open_opps)}</div>
        <div class="ng-kpi-sub">{len(base)} after filters</div>
      </div>
      <div class="ng-kpi urgent">
        <div class="ng-kpi-label">Due ≤ 7 days</div>
        <div class="ng-kpi-value">{len(urgent)}</div>
        <div class="ng-kpi-sub">urgent response window</div>
      </div>
      <div class="ng-kpi">
        <div class="ng-kpi-label">Due today</div>
        <div class="ng-kpi-value">{len(due_today)}</div>
        <div class="ng-kpi-sub">closing now</div>
      </div>
      <div class="ng-kpi success">
        <div class="ng-kpi-label">Counties</div>
        <div class="ng-kpi-value">{len({o.county for o in open_opps})}</div>
        <div class="ng-kpi-sub">with open bids</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# --- Insights: funnel + top deals ---
if view_mode == "insights":
    # Funnel by status among filtered base
    funnel_keys = ["open", "upcoming", "catalog", "closed"]
    funnel = []
    for sk in funnel_keys:
        items = [o for o in base if o.status == sk]
        funnel.append((STATUS_LABELS[sk], sk, len(items)))
    max_n = max((n for _, _, n in funnel), default=1) or 1

    left, right = st.columns(2)
    with left:
        rows_html = []
        for label, key, n in funnel:
            pct = int(100 * n / max_n) if max_n else 0
            rows_html.append(
                f"""
                <div class="ng-funnel-row">
                  <span class="muted small">{esc(label)}</span>
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
                <div class="ng-panel-sub">{len(base)} filtered</div>
              </div>
              {''.join(rows_html)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Clickable stage shortcuts under funnel
        fcols = st.columns(len(funnel_keys))
        for i, (label, key, n) in enumerate(funnel):
            if fcols[i].button(f"{label}", key=f"funnel_{key}", use_container_width=True):
                st.session_state.stage_tab = key if key != "open" else "open"
                if key == "open":
                    st.session_state.stage_tab = "open"
                else:
                    st.session_state.stage_tab = key
                st.session_state.view_mode = "board"
                st.rerun()

    with right:
        top = sorted(
            open_opps,
            key=lambda o: (o.days_until_due if o.days_until_due is not None else 9999, o.title),
        )[:8]
        items = []
        for o in top:
            items.append(
                f"""
                <div class="ng-list-row">
                  <span>{esc(o.title[:70])}
                    <span class="muted"> · {esc(o.agency[:28])}</span>
                  </span>
                  <strong class="num">{esc(fmt_due(o))}</strong>
                </div>
                """
            )
        if not items:
            items = ['<div class="ng-empty"><div class="ng-empty-title">No open deals.</div></div>']
        st.markdown(
            f"""
            <div class="ng-panel">
              <div class="ng-panel-head">
                <div class="ng-panel-title">Soonest due</div>
                <div class="ng-panel-sub">by deadline</div>
              </div>
              {''.join(items)}
            </div>
            """,
            unsafe_allow_html=True,
        )
        # Open buttons for top deals
        for o in top[:5]:
            if st.button(f"Open · {o.title[:50]}", key=f"top_{o.opportunity_id}", use_container_width=True):
                st.session_state.selected_id = o.opportunity_id
                st.session_state.view_mode = "list"
                st.rerun()

# --- Filter bar ---
st.markdown('<div class="ng-filter-bar">', unsafe_allow_html=True)
fc1, fc2, fc3 = st.columns([3, 1, 1])
with fc1:
    q = st.text_input(
        "Search",
        value=st.session_state.query,
        placeholder="Find by title, agency, ref #…",
        label_visibility="collapsed",
    )
    if q != st.session_state.query:
        st.session_state.query = q
        st.rerun()
with fc2:
    st.session_state.board_group = st.selectbox(
        "Group board",
        ["status", "county", "offer_type"],
        format_func=lambda x: {"status": "By status", "county": "By county", "offer_type": "By offer type"}[x],
        label_visibility="collapsed",
    )
with fc3:
    if st.button("Clear filters", use_container_width=True):
        st.session_state.county = None
        st.session_state.category = None
        st.session_state.offer_type = None
        st.session_state.agency = None
        st.session_state.query = ""
        st.session_state.stage_tab = "open"
        st.rerun()

# Active chips
chips = []
if st.session_state.county:
    chips.append(f"County: {COUNTY_LABELS.get(st.session_state.county, st.session_state.county)}")
if st.session_state.offer_type:
    chips.append(f"Offer: {st.session_state.offer_type.replace('_', ' ')}")
if st.session_state.category:
    chips.append(f"Category: {st.session_state.category.replace('_', ' ')}")
if st.session_state.agency:
    chips.append(f"Agency: {st.session_state.agency[:40]}")
if st.session_state.query:
    chips.append(f"Search: {st.session_state.query}")
if chips:
    chip_html = "".join(f'<span class="ng-chip active">{esc(c)}</span>' for c in chips)
    st.markdown(f'<div class="ng-chips">{chip_html}</div>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# --- Stage tabs ---
tab_defs = [
    ("open", "All open", len([o for o in base if o.status in {"open", "upcoming"}])),
    ("upcoming", "Upcoming", status_counts.get("upcoming", 0)),
    ("closed", "Closed", len([o for o in base if o.status == "closed"])),
    ("catalog", "Catalog", len([o for o in base if o.status == "catalog"])),
    ("all", "All", len(base)),
]
# Streamlit buttons as tabs
tcols = st.columns(len(tab_defs))
for i, (key, label, n) in enumerate(tab_defs):
    active = st.session_state.stage_tab == key
    with tcols[i]:
        if st.button(
            f"{label} · {n}",
            key=f"stab_{key}",
            use_container_width=True,
            type="primary" if active else "secondary",
        ):
            st.session_state.stage_tab = key
            st.rerun()

# Recompute visible after possible stage change already done
visible = apply_stage(base)
visible = by_agency_filter(visible) if st.session_state.agency else visible
# Re-apply agency already in base path — base already has agency. Good.

# ---------------------------------------------------------------------------
# Board / List body
# ---------------------------------------------------------------------------

def render_card(o: Opportunity, key_prefix: str) -> None:
    selected = st.session_state.selected_id == o.opportunity_id
    tag_class = urgency_class(o)
    title = o.title if len(o.title) <= 90 else o.title[:87] + "…"
    meta_bits = [
        COUNTY_LABELS.get(o.county, o.county),
        sol_label(o),
        offer_label(o),
    ]
    st.markdown(
        f"""
        <div class="ng-kanban-card {'selected' if selected else ''}" id="card-{esc(o.opportunity_id)}">
          <div class="ng-card-title">{esc(title)}</div>
          <div class="ng-card-meta">
            <span class="ng-card-tag">{esc(o.agency[:32])}</span>
            <span class="ng-card-tag {tag_class}">{esc(fmt_due(o))}</span>
          </div>
          <div class="ng-card-meta" style="margin-top:4px">{esc(' · '.join(meta_bits))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("Open", key=f"{key_prefix}_{o.opportunity_id}", use_container_width=True):
        st.session_state.selected_id = o.opportunity_id
        st.rerun()


def render_drill(o: Opportunity) -> None:
    days = o.days_until_due
    due_txt = o.due_date.strftime("%b %d, %Y %H:%M") if o.due_date else "—"
    timing = ""
    if days is not None:
        if days < 0:
            timing = f"closed {abs(days)}d ago"
        elif days == 0:
            timing = "DUE TODAY"
        else:
            timing = f"due in {days}d"
    cats = ", ".join(o.categories) if o.categories else "—"
    st.markdown(
        f"""
        <div class="ng-drill">
          <div class="ng-drill-head">
            <div>
              <div class="ng-drill-eyebrow">{esc(o.agency)} · {esc(COUNTY_LABELS.get(o.county, o.county))}</div>
              <h2>{esc(o.title)}</h2>
            </div>
          </div>
          <div class="ng-drill-meta">
            <span class="ng-card-tag">{esc(sol_label(o))}</span>
            <span class="ng-card-tag">{esc(offer_label(o))}</span>
            <span class="ng-card-tag {urgency_class(o)}">{esc(timing or o.status)}</span>
            {f'<span class="ng-card-tag">{esc(o.external_id)}</span>' if o.external_id else ''}
          </div>
          <div class="ng-drill-section">
            <div class="ng-drill-section-head">Deal brief</div>
            <div class="ng-drill-desc">{esc(o.brief or o.description or 'No summary available.')}</div>
          </div>
          <div class="ng-drill-section">
            <div class="ng-drill-section-head">Details</div>
            <div class="ng-drill-desc">
              <strong>Due:</strong> {esc(due_txt)}<br/>
              <strong>Posted:</strong> {esc(o.posted_date.isoformat() if o.posted_date else "—")}<br/>
              <strong>Categories:</strong> {esc(cats)}<br/>
              <strong>Department:</strong> {esc(o.department or "—")}<br/>
              <strong>Budget:</strong> {esc(o.budget or "—")}<br/>
              <strong>Contact:</strong> {esc(o.contact or "—")}<br/>
              <strong>Source:</strong> {esc(o.source_name)}
            </div>
          </div>
          <div class="ng-drill-section">
            <div class="ng-drill-section-head">Portal</div>
            <div class="ng-drill-desc"><a href="{esc(o.url)}" target="_blank" rel="noopener">Open opportunity ↗</a></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    b1, b2 = st.columns(2)
    with b1:
        st.link_button("Open portal", o.url, use_container_width=True)
    with b2:
        if st.button("Close panel", use_container_width=True):
            st.session_state.selected_id = None
            st.rerun()


selected = next((o for o in all_opps if o.opportunity_id == st.session_state.selected_id), None)

if view_mode == "board":
    group_key = st.session_state.board_group
    groups: Dict[str, List[Opportunity]] = defaultdict(list)
    for o in visible:
        if group_key == "county":
            k = COUNTY_LABELS.get(o.county, o.county)
        elif group_key == "offer_type":
            k = offer_label(o).title()
        else:
            k = STATUS_LABELS.get(o.status, o.status)
        groups[k].append(o)

    # Order columns
    if group_key == "status":
        col_order = [STATUS_LABELS[s] for s in STATUS_ORDER if STATUS_LABELS[s] in groups]
        for k in groups:
            if k not in col_order:
                col_order.append(k)
    else:
        col_order = sorted(groups.keys(), key=lambda x: (-len(groups[x]), x))

    if not col_order:
        st.markdown(
            '<div class="ng-empty"><div class="ng-empty-title">No deals in this stage.</div></div>',
            unsafe_allow_html=True,
        )
    else:
        # Limit columns for layout; use horizontal scroll via flex HTML for heads + streamlit cols
        n = min(len(col_order), 5)
        cols = st.columns(n)
        for i, cname in enumerate(col_order[:n]):
            items = groups[cname]
            # sort soonest due first
            items = sorted(
                items,
                key=lambda o: (o.days_until_due if o.days_until_due is not None else 9999, o.title),
            )
            with cols[i]:
                st.markdown(
                    f"""
                    <div class="ng-kanban-col">
                      <div class="ng-kanban-col-head">
                        <span>{esc(cname)}</span>
                        <span>{len(items)}</span>
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                for o in items[:12]:
                    render_card(o, key_prefix=f"b_{i}")
                if len(items) > 12:
                    st.caption(f"+ {len(items) - 12} more")

    if len(col_order) > 5:
        st.caption(f"Showing first 5 of {len(col_order)} columns. Use filters to narrow.")

elif view_mode == "list":
    if not visible:
        st.markdown(
            '<div class="ng-empty"><div class="ng-empty-title">No open deals.</div></div>',
            unsafe_allow_html=True,
        )
    else:
        items = sorted(
            visible,
            key=lambda o: (o.days_until_due if o.days_until_due is not None else 9999, o.title),
        )
        for o in items[:60]:
            cols = st.columns([6, 2, 1])
            with cols[0]:
                st.markdown(
                    f"**{esc(o.title[:80])}**  \n"
                    f"<span style='color:#697586;font-size:0.82rem'>"
                    f"{esc(o.agency)} · {esc(COUNTY_LABELS.get(o.county, o.county))} · "
                    f"{esc(sol_label(o))} · {esc(offer_label(o))}</span>",
                    unsafe_allow_html=True,
                )
            with cols[1]:
                st.markdown(f"`{fmt_due(o)}`")
            with cols[2]:
                if st.button("Open", key=f"list_{o.opportunity_id}"):
                    st.session_state.selected_id = o.opportunity_id
                    st.rerun()
        if len(items) > 60:
            st.caption(f"Showing 60 of {len(items)}")

# ---------------------------------------------------------------------------
# Drill-down panel
# ---------------------------------------------------------------------------

if selected:
    st.markdown("---")
    render_drill(selected)
