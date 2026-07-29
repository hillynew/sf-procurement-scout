"""SF Procurement Scout — permanent left menu + pipeline UI."""

from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.models.opportunity import HealthStatus, Opportunity
from src.pipeline.runner import run_fetch
from src.pipeline.store import data_dir, load_latest, save_snapshot
from src.summarize import apply_briefs, make_brief

# ---------------------------------------------------------------------------
# Page + CSS
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Procurement Pipeline · SF Scout",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",  # native sidebar unused; permanent left menu instead
)

_CSS = (Path(__file__).parent / "styles.css").read_text(encoding="utf-8")
st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)

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
_PROBLEM_STATUSES = {HealthStatus.DEGRADED.value, HealthStatus.ERROR.value}
HEALTH_LABELS = {
    HealthStatus.OK.value: "OK",
    HealthStatus.EMPTY.value: "No listings",
    HealthStatus.DEGRADED.value: "Degraded",
    HealthStatus.ERROR.value: "Error",
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
        "view_mode": "list",
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


def block(markup: str) -> str:
    """Flatten an HTML fragment before handing it to st.markdown.

    Markdown treats any line indented four or more spaces as a code block, so
    an indented f-string template renders as literal tags instead of HTML.
    Collapsing the indentation is what keeps these fragments rendering.
    """
    return " ".join(line.strip() for line in markup.strip().splitlines() if line.strip())


def bar_row(label: str, value: int, peak: int) -> str:
    pct = int(100 * value / peak) if peak else 0
    return block(
        f"""
        <div class="ng-funnel-row">
          <span>{esc(label)}</span>
          <div class="ng-bar-track"><div class="ng-bar-fill" style="width:{pct}%"></div></div>
          <span class="ng-bar-value">{value}</span>
        </div>
        """
    )


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
    return make_brief(o)


def short_brief(o: Opportunity, n: int = 140) -> str:
    b = " ".join(ensure_brief(o).split())
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
    days = o.days_until_due
    if o.status in {"closed", "cancelled"}:
        return "muted", o.status
    if days is None:
        return ("info", "upcoming") if o.status == "upcoming" else ("ok", "open")
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


@st.cache_data(ttl=300, show_spinner=False)
def _load_snapshot(_cache_key: int):
    """Read the saved snapshot once per rerun cycle.

    Briefs were being regenerated for every opportunity on every widget
    interaction; the snapshot only changes when a fetch writes a new one.
    """
    opps, health = load_latest()
    apply_briefs(opps)
    return opps, health


def _snapshot_key() -> int:
    """Mtime of latest.json, so the cache invalidates when a fetch rewrites it."""
    path = data_dir() / "latest.json"
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def load_data(force: bool = False):
    if force:
        with st.spinner("Fetching live portals from Miami-Dade, Broward & Palm Beach…"):
            opps, health = run_fetch(
                include_catalog=st.session_state.include_catalog,
                open_only=False,
                quiet=True,
            )
            apply_briefs(opps)
            save_snapshot(opps, health, tag="dashboard")
            _load_snapshot.clear()
            return opps, health
    return _load_snapshot(_snapshot_key())


def apply_filters(
    opps: List[Opportunity],
    *,
    stage: Optional[str] = None,
    urgent_only: Optional[bool] = None,
) -> List[Opportunity]:
    """Filter by the sidebar selections.

    `stage` and `urgent_only` can be overridden so callers (tab counts, the
    insights view) can ask "what would this look like?" without writing to
    session state and triggering an extra Streamlit rerun.
    """
    county = st.session_state.county_filter
    offer = st.session_state.offer_filter
    cat = st.session_state.category_filter
    agency = st.session_state.agency_filter
    q = (st.session_state.query or "").strip().lower()
    stage = st.session_state.stage_tab if stage is None else stage
    if urgent_only is None:
        urgent_only = st.session_state.show_only_urgent

    out = list(opps)
    if county != "All":
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
    if urgent_only:
        out = [
            o
            for o in out
            if o.days_until_due is not None and 0 <= o.days_until_due <= 7
        ]
    return sort_opps(out)


def card_html(o: Opportunity, selected: bool = False) -> str:
    ucss, ulabel = urgency_badge(o)
    color = OFFER_COLORS.get(offer_key(o), OFFER_COLORS["unknown"])
    ref = esc(o.external_id) if o.external_id else ""
    # Prefer the agency's own scope text over the generated brief — it says
    # what the work actually is.
    blurb = " ".join((o.scope or o.description or ensure_brief(o)).split())
    blurb = blurb if len(blurb) <= 165 else blurb[:164] + "…"

    facts = []
    if o.budget:
        facts.append(f'<span class="deal-fact value">💲 {esc(o.budget)}</span>')
    if o.documents:
        addenda = sum(1 for d in o.documents if d.kind == "addendum")
        label = f"{len(o.documents)} doc" + ("s" if len(o.documents) != 1 else "")
        if addenda:
            label += f" · {addenda} addendum" + ("s" if addenda != 1 else "")
        facts.append(f'<span class="deal-fact">📎 {esc(label)}</span>')
    for req in o.requirements[:2]:
        facts.append(f'<span class="deal-fact req">{esc(req)}</span>')
    if len(o.requirements) > 2:
        facts.append(f'<span class="deal-fact req">+{len(o.requirements) - 2}</span>')

    return block(
        f"""
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
      <div class="deal-brief">{esc(blurb)}</div>
      {f'<div class="deal-facts">{"".join(facts)}</div>' if facts else ''}
      <div class="deal-foot">
        <span class="deal-due">📅 {esc(fmt_due(o))}</span>
        {f'<span class="deal-ref">{ref}</span>' if ref else ''}
      </div>
    </div>
    """
    )


def render_deal_actions(o: Opportunity, key: str) -> None:
    c1, c2 = st.columns(2)
    with c1:
        st.link_button("🔗 Open portal", o.url or "#", width="stretch")
    with c2:
        is_sel = st.session_state.selected_id == o.opportunity_id
        if st.button(
            "✓ Selected" if is_sel else "📄 Summary",
            key=key,
            width="stretch",
            type="primary" if is_sel else "secondary",
        ):
            st.session_state.selected_id = None if is_sel else o.opportunity_id
            if st.session_state.view_mode == "board" and not is_sel:
                st.session_state.view_mode = "list"
            st.rerun()


def _fact_rows(o: Opportunity) -> str:
    """The at-a-glance grid: only fields that actually have a value."""
    rows = [
        ("Reference", o.external_id),
        ("Agency", o.agency),
        ("Department", o.department),
        ("County", COUNTY_LABELS.get(o.county, o.county)),
        ("Solicitation", sol_label(o)),
        # "Unknown" work type is an absence, not a fact worth a grid cell.
        ("Work type", offer_label(o) if offer_key(o) != "unknown" else None),
        ("Estimated value", o.budget),
        ("Bids due", fmt_due(o)),
        ("Questions due", _fmt_dt(o.questions_due)),
        ("Posted", o.posted_date.isoformat() if o.posted_date else None),
        ("Pre-bid meeting", o.pre_bid_meeting),
        ("Bid opening", o.bid_opening),
        ("Submit to", o.submittal_info),
        ("Contact", o.contact),
        ("Email", o.contact_email),
        ("Phone", o.contact_phone),
        ("Categories", ", ".join(c.replace("_", " ") for c in (o.categories or [])) or None),
        ("Source", o.source_name),
    ]
    cells = [
        f'<div class="fact"><div class="fact-label">{esc(label)}</div>'
        f'<div class="fact-value">{esc(value)}</div></div>'
        for label, value in rows
        if value
    ]
    return f'<div class="fact-grid">{"".join(cells)}</div>'


def _fmt_dt(value) -> Optional[str]:
    return value.strftime("%b %d, %Y %H:%M") if value else None


def render_summary_panel(o: Opportunity) -> None:
    ucss, ulabel = urgency_badge(o)
    score = o.detail_score

    tags = [
        f'<span class="ng-card-tag">{esc(sol_label(o))}</span>',
        f'<span class="ng-card-tag">{esc(offer_label(o))}</span>',
        f'<span class="ng-card-tag {ucss}">{esc(ulabel)}</span>',
        f'<span class="ng-card-tag">{esc(STATUS_LABELS.get(o.status, o.status))}</span>',
    ]
    if o.external_id:
        tags.append(f'<span class="ng-card-tag">{esc(o.external_id)}</span>')

    st.markdown(
        block(
            f"""
        <div class="summary-panel">
          <div class="summary-head">
            <div class="summary-eyebrow">Opportunity detail</div>
            <div class="detail-meter" title="How much is known about this bid">
              <span class="detail-meter-label">{score}% detail</span>
              <span class="detail-meter-track">
                <span class="detail-meter-fill" style="width:{score}%"></span>
              </span>
            </div>
          </div>
          <h2>{esc(o.title)}</h2>
          <div class="summary-tags">{"".join(tags)}</div>
          {_fact_rows(o)}
        </div>
        """
        ),
        unsafe_allow_html=True,
    )

    if o.requirements:
        chips = "".join(
            f'<span class="req-chip">{esc(r)}</span>' for r in o.requirements
        )
        st.markdown(
            block(
                f"""
            <div class="detail-section">
              <div class="detail-section-title">Requirements to bid</div>
              <div class="req-chips">{chips}</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )

    if o.scope:
        scope = " ".join(o.scope.split())
        preview, rest = scope[:900], scope[900:]
        st.markdown(
            block(
                f"""
            <div class="detail-section">
              <div class="detail-section-title">Scope of work</div>
              <div class="scope-text">{esc(preview)}{'…' if rest else ''}</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )
        if rest:
            with st.expander(f"Read the full scope ({len(scope):,} characters)"):
                st.write(scope)
    elif o.description:
        st.markdown(
            block(
                f"""
            <div class="detail-section">
              <div class="detail-section-title">Description</div>
              <div class="scope-text">{esc(o.description)}</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )

    if o.documents:
        links = "".join(
            f'<a class="doc-link {esc(d.kind)}" href="{esc(d.url)}" target="_blank" '
            f'rel="noopener">{esc(d.name)}<span class="doc-kind">{esc(d.kind)}</span></a>'
            for d in o.documents[:25]
        )
        more = (
            f'<div class="doc-more">+ {len(o.documents) - 25} more on the portal</div>'
            if len(o.documents) > 25
            else ""
        )
        st.markdown(
            block(
                f"""
            <div class="detail-section">
              <div class="detail-section-title">Bid documents ({len(o.documents)})</div>
              <div class="doc-list">{links}</div>
              {more}
            </div>
            """
            ),
            unsafe_allow_html=True,
        )

    if not o.detail_fetched and o.status in {"open", "upcoming"}:
        st.caption(
            "This portal does not publish a machine-readable detail page — "
            "open the official listing for the full package."
        )

    a1, a2, a3 = st.columns(3)
    with a1:
        st.link_button("Open official portal ↗", o.url or "#", width="stretch", type="primary")
    with a2:
        subject = quote(f"Bid opportunity: {o.title[:80]}")
        body = quote(f"{ensure_brief(o)}\n\nPortal: {o.url}")
        st.link_button("Share via email", f"mailto:?subject={subject}&body={body}", width="stretch")
    with a3:
        if st.button("Close detail", width="stretch", key=f"close_{o.opportunity_id}"):
            st.session_state.selected_id = None
            st.rerun()


def render_export(opps: List[Opportunity]) -> None:
    """Let the user take the *filtered* view away as CSV or JSON."""
    if not opps:
        return
    with st.expander(f"Export these {len(opps)} deals", expanded=False):
        rows = [o.to_row() for o in opps]
        csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
        payload = json.dumps(
            {"count": len(opps), "opportunities": rows}, indent=2, default=str
        ).encode("utf-8")
        stamp = datetime.now().strftime("%Y%m%d")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️  CSV",
                csv,
                file_name=f"sf-procurement-{stamp}.csv",
                mime="text/csv",
                width="stretch",
            )
        with c2:
            st.download_button(
                "⬇️  JSON",
                payload,
                file_name=f"sf-procurement-{stamp}.json",
                mime="application/json",
                width="stretch",
            )


def render_left_menu(all_opps: List[Opportunity], health) -> None:
    """Always-visible left navigation (main layout column — not Streamlit sidebar)."""
    st.markdown(
        block(
            """
        <div class="left-menu-brand">
          <div class="ng-brand-mark">SF</div>
          <div>
            <div class="ng-brand-name">SF Procure Scout</div>
            <div class="ng-brand-sub">South Florida bids</div>
          </div>
        </div>
        """
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<p class="left-menu-label">Actions</p>', unsafe_allow_html=True)
    if st.button("🔄  Fetch live data", type="primary", width="stretch", key="fetch_btn"):
        st.session_state.do_fetch = True
        st.rerun()

    st.checkbox(
        "Include catalog portals",
        key="include_catalog",
        help="DemandStar / Bidnet / VSS registration entries",
    )
    st.checkbox("Urgent only (≤ 7 days)", key="show_only_urgent")

    st.markdown('<p class="left-menu-label">Filters</p>', unsafe_allow_html=True)

    county_opts = ["All"] + list(COUNTY_LABELS.values())
    if st.session_state.county_filter not in county_opts:
        st.session_state.county_filter = "All"
    st.selectbox("County", county_opts, key="county_filter")

    if all_opps:
        offer_opts = ["All"] + sorted(
            {offer_key(o).replace("_", " ").title() for o in all_opps if offer_key(o) != "unknown"}
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

    for key, opts in (
        ("offer_filter", offer_opts),
        ("category_filter", cat_opts),
        ("agency_filter", agency_opts),
    ):
        if st.session_state.get(key) not in opts:
            st.session_state[key] = "All"

    st.selectbox("Offer type", offer_opts, key="offer_filter")
    st.selectbox("Category", cat_opts, key="category_filter")
    st.selectbox("Agency", agency_opts, key="agency_filter")
    st.selectbox(
        "Sort by",
        ["due_soon", "newest", "agency", "title"],
        format_func=lambda x: {
            "due_soon": "Due soonest",
            "newest": "Newest posted",
            "agency": "Agency A–Z",
            "title": "Title A–Z",
        }[x],
        key="sort_by",
    )
    st.selectbox(
        "Board columns",
        ["county", "status", "offer_type"],
        format_func=lambda x: {
            "county": "By county",
            "status": "By status",
            "offer_type": "By offer type",
        }[x],
        key="board_group",
    )

    if st.button("Clear all filters", width="stretch", key="clear_filters"):
        st.session_state.county_filter = "All"
        st.session_state.offer_filter = "All"
        st.session_state.category_filter = "All"
        st.session_state.agency_filter = "All"
        st.session_state.query = ""
        st.session_state.stage_tab = "open"
        st.session_state.show_only_urgent = False
        st.session_state.selected_id = None
        st.rerun()

    st.markdown('<p class="left-menu-label">Layout</p>', unsafe_allow_html=True)
    st.radio(
        "Layout",
        ["list", "board", "insights"],
        format_func=lambda x: {
            "list": "📋  List + detail",
            "board": "🗂  Board",
            "insights": "📊  Insights",
        }[x],
        key="view_mode",
        label_visibility="collapsed",
    )

    st.markdown('<p class="left-menu-label">Quick county</p>', unsafe_allow_html=True)
    if st.button("All counties", width="stretch", key="qc_all"):
        st.session_state.county_filter = "All"
        st.rerun()
    for ck, label in COUNTY_LABELS.items():
        n = sum(1 for o in all_opps if o.county == ck) if all_opps else 0
        active = st.session_state.county_filter == label
        if st.button(
            f"{'● ' if active else ''}{label}  ({n})",
            width="stretch",
            key=f"qc_{ck}",
            type="primary" if active else "secondary",
        ):
            st.session_state.county_filter = label
            st.rerun()

    if health:
        ok = sum(1 for h in health if h.status == HealthStatus.OK.value)
        st.caption(f"Sources: {ok}/{len(health)} reporting · {len(all_opps)} deals")
        broken = [h for h in health if h.status in _PROBLEM_STATUSES]
        if broken:
            st.warning(
                f"{len(broken)} source(s) need attention: "
                + ", ".join(h.name.split("(")[0].strip() for h in broken[:3]),
                icon="⚠️",
            )
    if os.environ.get("RENDER"):
        st.caption("Hosted on Render")


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------

if st.session_state.do_fetch:
    all_opps, health = load_data(force=True)
    st.session_state.do_fetch = False
    st.session_state.selected_id = None
else:
    all_opps, health = load_data(force=False)

# ---------------------------------------------------------------------------
# Layout: permanent left menu | main
# ---------------------------------------------------------------------------

menu_col, main_col = st.columns([1, 3.15], gap="large")

with menu_col:
    render_left_menu(all_opps, health)

with main_col:
    if not all_opps:
        st.markdown(
            block(
                """
            <div class="ng-hero">
              <h1>Procurement Pipeline</h1>
              <p>Live government bids across Miami-Dade, Broward &amp; Palm Beach</p>
            </div>
            <div class="ng-empty">
              <div class="ng-empty-icon">📥</div>
              <div class="ng-empty-title">No opportunities loaded</div>
              <div>Click <strong>Fetch live data</strong> in the <strong>left menu</strong>.</div>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )
    else:
        visible = apply_filters(all_opps)
        open_pool = [o for o in all_opps if o.status in {"open", "upcoming"}]
        open_vis = [o for o in visible if o.status in {"open", "upcoming"}]
        urgent = [
            o for o in open_vis if o.days_until_due is not None and 0 <= o.days_until_due <= 7
        ]
        due_today = [
            o for o in open_vis if o.days_until_due is not None and o.days_until_due == 0
        ]
        by_id: Dict[str, Opportunity] = {o.opportunity_id: o for o in all_opps}
        selected = by_id.get(st.session_state.selected_id) if st.session_state.selected_id else None
        view = st.session_state.view_mode

        st.markdown(
            block(
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
            """
            ),
            unsafe_allow_html=True,
        )

        st.markdown(
            block(
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
            """
            ),
            unsafe_allow_html=True,
        )

        s1, s2 = st.columns([3, 1])
        with s1:
            q = st.text_input(
                "Search deals",
                value=st.session_state.query,
                placeholder="Search title, agency, ref #, or summary…",
                label_visibility="collapsed",
                key="search_input",
            )
            if q != st.session_state.query:
                st.session_state.query = q
                st.rerun()
        with s2:
            st.markdown(
                f'<div class="ng-result-pill">{len(visible)} results</div>',
                unsafe_allow_html=True,
            )

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
            n = len(apply_filters(all_opps, stage=key))
            with tcols[i]:
                active = st.session_state.stage_tab == key
                if st.button(
                    f"{tab_labels[key]} ({n})",
                    key=f"stage_{key}",
                    width="stretch",
                    type="primary" if active else "secondary",
                ):
                    st.session_state.stage_tab = key
                    st.rerun()

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

        # ----- Views -----
        if not visible:
            st.markdown(
                block(
                    """
                <div class="ng-empty">
                  <div class="ng-empty-icon">🔎</div>
                  <div class="ng-empty-title">No deals match these filters</div>
                  <div>Clear filters in the <strong>left menu</strong> or switch stage tabs.</div>
                </div>
                """
                ),
                unsafe_allow_html=True,
            )
        elif view == "insights":
            # Insights always describe the whole pipeline, not the active tab.
            all_filtered = apply_filters(all_opps, stage="all", urgent_only=False)

            left, right = st.columns(2)
            with left:
                stages = ["open", "upcoming", "catalog", "closed"]
                rows = []
                max_n = 1
                for sk in stages:
                    n = sum(1 for o in all_filtered if o.status == sk)
                    max_n = max(max_n, n)
                    rows.append((STATUS_LABELS[sk], n))
                html_rows = [bar_row(label, n, max_n) for label, n in rows]
                st.markdown(
                    block(
                        f"""
                    <div class="ng-panel">
                      <div class="ng-panel-head">
                        <div class="ng-panel-title">Status funnel</div>
                        <div class="ng-panel-sub">{len(all_filtered)} filtered</div>
                      </div>
                      {''.join(html_rows)}
                    </div>
                    """
                    ),
                    unsafe_allow_html=True,
                )
                cat_c: Counter = Counter()
                for o in all_filtered:
                    for c in o.categories or ["general"]:
                        if c != "portal_directory":
                            cat_c[c] += 1
                top_cats = cat_c.most_common(8)
                max_c = top_cats[0][1] if top_cats else 1
                crow = [bar_row(c.replace("_", " "), n, max_c) for c, n in top_cats]
                st.markdown(
                    block(
                        f"""
                    <div class="ng-panel" style="margin-top:12px">
                      <div class="ng-panel-head"><div class="ng-panel-title">Top categories</div></div>
                      {''.join(crow) if crow else '<div class="ng-empty-title">No categories</div>'}
                    </div>
                    """
                    ),
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
                    block(
                        f"""
                    <div class="ng-panel">
                      <div class="ng-panel-head">
                        <div class="ng-panel-title">Hot pipeline (next 14 days)</div>
                        <div class="ng-panel-sub">{len(hot)} deals</div>
                      </div>
                    </div>
                    """
                    ),
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

            n = min(len(order), 4)
            if n == 0:
                st.info("No columns to show.")
            else:
                cols = st.columns(n)
                for i, name in enumerate(order[:n]):
                    items = sort_opps(buckets[name])
                    with cols[i]:
                        st.markdown(
                            block(
                                f"""
                            <div class="board-col-head">
                              <span>{esc(name)}</span>
                              <span class="board-count">{len(items)}</span>
                            </div>
                            """
                            ),
                            unsafe_allow_html=True,
                        )
                        for o in items[:15]:
                            sel = st.session_state.selected_id == o.opportunity_id
                            st.markdown(card_html(o, selected=sel), unsafe_allow_html=True)
                            render_deal_actions(o, key=f"bd_{i}_{o.opportunity_id}")
                        if len(items) > 15:
                            st.caption(f"+ {len(items) - 15} more")
            if selected:
                st.markdown("---")
                render_summary_panel(selected)

        else:  # list + detail (default)
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
                    st.caption(f"Showing 80 of {len(visible)}")

            with detail_col:
                st.markdown('<div class="list-head">Deal summary</div>', unsafe_allow_html=True)
                if selected:
                    render_summary_panel(selected)
                else:
                    preview = urgent or open_vis or visible
                    if preview:
                        st.caption("Auto-preview of top match — click Summary on any card to pin it.")
                        render_summary_panel(preview[0])
                    else:
                        st.markdown(
                            block(
                                """
                            <div class="ng-empty">
                              <div class="ng-empty-title">Select a deal</div>
                              <div>Click <strong>Summary</strong> on any card.</div>
                            </div>
                            """
                            ),
                            unsafe_allow_html=True,
                        )

        render_export(visible)

        if health:
            problems = sum(1 for h in health if h.status in _PROBLEM_STATUSES)
            label = "Source health" + (f" — {problems} need attention" if problems else "")
            with st.expander(label, expanded=bool(problems)):
                st.dataframe(
                    [
                        {
                            "Source": h.name,
                            "Status": HEALTH_LABELS.get(h.status, h.status),
                            "Deals": h.count,
                            "ms": h.elapsed_ms,
                            "Detail": (h.error or h.note or "")[:90],
                        }
                        for h in health
                    ],
                    width="stretch",
                    hide_index=True,
                )
                st.caption(
                    "**Degraded** means the portal blocked us or its layout changed — "
                    "check that agency directly. **No listings** means the portal is "
                    "genuinely empty right now."
                )
