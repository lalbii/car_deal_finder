from __future__ import annotations

from pathlib import Path
import sys

# Allow `streamlit run dashboard/app.py` from the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from dashboard.data import clear_dashboard_cache
from dashboard.views import (
    render_collector_health,
    render_inactive_listings,
    render_listing_detail,
    render_market_overview,
    render_opportunities,
)


st.set_page_config(
    page_title="Kleinanzeigen Deal Finder",
    page_icon="🚗",
    layout="wide",
)

if "view" not in st.session_state:
    st.session_state["view"] = "Opportunities"

st.sidebar.title("Kleinanzeigen Deal Finder")

views = ["Opportunities", "Inactive Listings", "Listing Detail", "Market / Overview"]
view = st.sidebar.radio(
    "View",
    views,
    index=views.index(st.session_state["view"]),
)

st.session_state["view"] = view

if st.sidebar.button("Refresh data"):
    clear_dashboard_cache()
    st.rerun()

st.sidebar.caption("Read-only dashboard · current market data")

render_collector_health()

if view == "Opportunities":
    render_opportunities()
elif view == "Inactive Listings":
    render_inactive_listings()
elif view == "Listing Detail":
    render_listing_detail()
else:
    render_market_overview()
