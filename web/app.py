"""Streamlit dashboard for SF Procurement Scout (local + Render)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Allow running via `streamlit run web/app.py`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from src.pipeline.runner import filter_opportunities, run_fetch
from src.pipeline.store import load_latest, save_snapshot

st.set_page_config(
    page_title="SF Procurement Scout",
    page_icon="📋",
    layout="wide",
)

st.title("SF Procurement Scout")
st.caption(
    "Live government procurement opportunities across Miami-Dade, Broward, and Palm Beach counties."
)

with st.sidebar:
    st.header("Controls")
    do_fetch = st.button("Fetch live data now", type="primary")
    open_only = st.checkbox("Open / upcoming only", value=True)
    include_catalog = st.checkbox("Include catalog-only portals", value=False)
    county = st.selectbox(
        "County",
        ["(all)", "miami-dade", "broward", "palm-beach"],
    )
    offer_type = st.selectbox(
        "Offer type",
        [
            "(all)",
            "goods",
            "services",
            "construction",
            "professional_services",
            "mixed",
            "unknown",
        ],
    )
    category = st.text_input("Category contains", "")
    query = st.text_input("Search", "")
    st.markdown("---")
    st.markdown(
        "Data is scraped from public county portals. "
        "On Render free tier, disk is ephemeral — re-fetch after restarts."
    )
    if os.environ.get("RENDER"):
        st.info("Running on Render")

if do_fetch:
    with st.spinner("Fetching live portals (30–90s)..."):
        try:
            opps, health = run_fetch(
                include_catalog=include_catalog,
                open_only=False,
            )
            save_snapshot(opps, health, tag="dashboard")
            st.success(
                f"Fetched {len(opps)} opportunities from "
                f"{sum(1 for h in health if h.ok)} sources."
            )
        except Exception as e:
            st.error(f"Fetch failed: {e}")
            opps, health = load_latest()
else:
    opps, health = load_latest()
    if not opps:
        st.info(
            "No saved data yet. Click **Fetch live data now** in the sidebar to pull opportunities."
        )
        st.stop()

# Apply filters
filtered = filter_opportunities(
    opps,
    open_only=open_only,
    county=None if county == "(all)" else county,
    category=category or None,
    offer_type=None if offer_type == "(all)" else offer_type,
    query=query or None,
)

# KPIs
c1, c2, c3, c4 = st.columns(4)
c1.metric("Opportunities", len(filtered))
c2.metric("Open", sum(1 for o in filtered if o.status == "open"))
c3.metric("Counties", len({o.county for o in filtered}))
urgent = sum(
    1 for o in filtered if o.days_until_due is not None and 0 <= o.days_until_due <= 7
)
c4.metric("Due ≤ 7 days", urgent)

# Health
with st.expander("Source health", expanded=False):
    if health:
        st.dataframe(
            pd.DataFrame([h.model_dump() for h in health]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.write("No health data in snapshot.")

# Group tabs
tab_all, tab_county, tab_cat, tab_briefs = st.tabs(
    ["All opportunities", "By county", "By category", "Deal briefs"]
)

rows = [o.to_row() for o in filtered]
df = pd.DataFrame(rows)

with tab_all:
    if df.empty:
        st.warning("No opportunities match filters.")
    else:
        show_cols = [
            "due_date",
            "days_until_due",
            "status",
            "county",
            "agency",
            "solicitation_type",
            "offer_type",
            "categories",
            "title",
            "external_id",
            "url",
            "brief",
        ]
        st.dataframe(
            df[[c for c in show_cols if c in df.columns]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("Link"),
                "days_until_due": st.column_config.NumberColumn("Days left"),
            },
        )
        st.download_button(
            "Download CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="sf_procurement_opportunities.csv",
            mime="text/csv",
        )

with tab_county:
    if df.empty:
        st.warning("No data.")
    else:
        for cty, g in df.groupby("county"):
            st.subheader(cty)
            st.dataframe(
                g[["due_date", "agency", "title", "offer_type", "url"]],
                use_container_width=True,
                hide_index=True,
                column_config={"url": st.column_config.LinkColumn("Link")},
            )

with tab_cat:
    if df.empty:
        st.warning("No data.")
    else:
        exploded = df.assign(
            category=df["categories"].fillna("").str.split(", ")
        ).explode("category")
        exploded["category"] = exploded["category"].replace("", "general")
        counts = exploded["category"].value_counts()
        st.bar_chart(counts)
        pick = st.selectbox("Category detail", ["(all)"] + list(counts.index))
        view = exploded if pick == "(all)" else exploded[exploded["category"] == pick]
        st.dataframe(
            view[["category", "county", "agency", "title", "due_date", "url"]].drop_duplicates(),
            use_container_width=True,
            hide_index=True,
            column_config={"url": st.column_config.LinkColumn("Link")},
        )

with tab_briefs:
    for i, o in enumerate(filtered[:50], 1):
        st.markdown(f"**{i}. [{o.county}] {o.title}**")
        st.write(o.brief or "")
        st.markdown(f"[Open opportunity]({o.url})")
        st.divider()
