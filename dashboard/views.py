from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.data import (
    get_listing,
    load_dashboard_frame,
    load_history,
    load_listings,
    load_overview,
    load_price_drop_summary,
)
from dashboard.formatting import (
    format_euro,
    format_mileage,
    format_percent,
    format_score,
    relative_time,
)


def _year_series(df: pd.DataFrame) -> pd.Series:
    if "year" in df.columns:
        return pd.to_numeric(df["year"], errors="coerce")
    if "first_registration" not in df.columns:
        return pd.Series(index=df.index, dtype=float)
    return pd.to_numeric(
        df["first_registration"].astype(str).str.extract(r"(\d{4})")[0],
        errors="coerce",
    )


def render_opportunities() -> None:
    st.title("Opportunities")
    st.caption("Experimental ranking — relative market signal, not profit or a buying recommendation.")

    df = load_dashboard_frame(active_market_only=True).copy()
    if df.empty:
        st.info("No active listings available.")
        return

    df["year_display"] = _year_series(df)
    now = pd.Timestamp.now(tz="UTC")
    if "first_seen" in df.columns:
        df["first_seen_dt"] = pd.to_datetime(df["first_seen"], utc=True, errors="coerce")

    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)

        price_values = pd.to_numeric(df.get("price"), errors="coerce").dropna()
        if not price_values.empty:
            price_range = c1.slider(
                "Price (€)",
                int(price_values.min()),
                int(price_values.max()),
                (int(price_values.min()), int(price_values.max())),
            )
        else:
            price_range = None

        mileage_values = pd.to_numeric(df.get("mileage_km"), errors="coerce").dropna()
        if not mileage_values.empty:
            mileage_range = c2.slider(
                "Mileage (km)",
                int(mileage_values.min()),
                int(mileage_values.max()),
                (int(mileage_values.min()), int(mileage_values.max())),
            )
        else:
            mileage_range = None

        year_values = df["year_display"].dropna()
        if not year_values.empty:
            year_range = c3.slider(
                "Registration year",
                int(year_values.min()),
                int(year_values.max()),
                (int(year_values.min()), int(year_values.max())),
            )
        else:
            year_range = None

        c4, c5, c6 = st.columns(3)
        transmissions = sorted([str(x) for x in df.get("transmission", pd.Series(dtype=str)).dropna().unique()])
        selected_transmissions = c4.multiselect("Transmission", transmissions, default=transmissions)

        fuels = sorted([str(x) for x in df.get("fuel", pd.Series(dtype=str)).dropna().unique()])
        selected_fuels = c5.multiselect("Fuel", fuels, default=fuels)

        location_query = c6.text_input("Location contains", "")

        c7, c8, c9 = st.columns(3)
        score_values = pd.to_numeric(df.get("deal_score"), errors="coerce").dropna()
        min_score = (
            c7.number_input(
                "Minimum experimental score",
                value=float(score_values.min()) if not score_values.empty else 0.0,
                step=0.01,
                format="%.3f",
            )
            if not score_values.empty
            else None
        )
        discovered = c8.selectbox("Discovered", ["Any time", "Last 24h", "Last 7 days"])
        price_reductions_only = c9.checkbox("Price reductions only", value=False)

    filtered = df.copy()

    if "score_status" in filtered.columns:
        filtered = filtered.loc[filtered["score_status"] == "SCORABLE"]

    if price_range is not None:
        filtered = filtered.loc[pd.to_numeric(filtered["price"], errors="coerce").between(*price_range)]
    if mileage_range is not None:
        filtered = filtered.loc[pd.to_numeric(filtered["mileage_km"], errors="coerce").between(*mileage_range)]
    if year_range is not None:
        filtered = filtered.loc[filtered["year_display"].between(*year_range)]
    if selected_transmissions and "transmission" in filtered.columns:
        filtered = filtered.loc[filtered["transmission"].astype(str).isin(selected_transmissions)]
    if selected_fuels and "fuel" in filtered.columns:
        filtered = filtered.loc[filtered["fuel"].astype(str).isin(selected_fuels)]
    if location_query and "location" in filtered.columns:
        filtered = filtered.loc[
            filtered["location"].fillna("").astype(str).str.contains(location_query, case=False, regex=False)
        ]
    if min_score is not None and "deal_score" in filtered.columns:
        filtered = filtered.loc[pd.to_numeric(filtered["deal_score"], errors="coerce") >= min_score]
    if discovered != "Any time" and "first_seen_dt" in filtered.columns:
        hours = 24 if discovered == "Last 24h" else 24 * 7
        filtered = filtered.loc[filtered["first_seen_dt"] >= now - pd.Timedelta(hours=hours)]
    if price_reductions_only:
        filtered = filtered.loc[filtered.get("price_drop_abs", pd.Series(index=filtered.index)).notna()]

    if "deal_score" in filtered.columns:
        filtered = filtered.sort_values("deal_score", ascending=False, na_position="last")

    st.write(f"**{len(filtered)} listings**")

    show_cols = [
        "listing_id",
        "deal_score",
        "price",
        "discount_percent",
        "group_median_price",
        "year_display",
        "mileage_km",
        "transmission",
        "fuel",
        "title",
        "location",
        "first_seen",
        "view_count",
        "group_count",
        "url",
    ]
    show_cols = [c for c in show_cols if c in filtered.columns]
    table = filtered[show_cols].copy()

    rename = {
        "deal_score": "Score",
        "price": "Price",
        "discount_percent": "Δ Median %",
        "group_median_price": "Median",
        "year_display": "Year",
        "mileage_km": "Mileage",
        "first_seen": "First Seen",
        "view_count": "Views",
        "group_count": "Comparables",
        "url": "Kleinanzeigen",
        "title": "Title",
        "location": "Location",
        "transmission": "Transmission",
        "fuel": "Fuel",
    }
    table = table.rename(columns=rename)

    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Price": st.column_config.NumberColumn(format="€%d"),
            "Median": st.column_config.NumberColumn(format="€%d"),
            "Δ Median %": st.column_config.NumberColumn(format="%.1f%%"),
            "Mileage": st.column_config.NumberColumn(format="%d km"),
            "Score": st.column_config.NumberColumn(format="%.3f"),
            "Kleinanzeigen": st.column_config.LinkColumn(display_text="Open ↗"),
            "listing_id": None,
        },
    )

    selected_rows = getattr(event.selection, "rows", []) if event else []
    if selected_rows:
        row_idx = selected_rows[0]
        selected_id = str(table.iloc[row_idx]["listing_id"])
        st.session_state["selected_listing_id"] = selected_id
        st.success("Listing selected. Open **Listing Detail** from the sidebar.")


def render_listing_detail() -> None:
    st.title("Listing Detail")

    listing_id = st.session_state.get("selected_listing_id")
    if not listing_id:
        st.info("Select a listing from Opportunities first.")
        return

    current = get_listing(listing_id)
    if current is None:
        st.error("Selected listing was not found.")
        return

    scored = load_dashboard_frame(active_market_only=True)
    scored_match = scored.loc[scored["listing_id"].astype(str) == str(listing_id)] if not scored.empty else pd.DataFrame()
    score_row = scored_match.iloc[0] if not scored_match.empty else None

    title = current.get("title") or f"Listing {listing_id}"
    st.subheader(title)

    status = "ACTIVE" if int(current.get("is_active", 0) or 0) == 1 else "INACTIVE"
    st.caption(
        f"{status} · first seen {relative_time(current.get('first_seen'))} · "
        f"last seen {relative_time(current.get('last_seen'))}"
    )

    if current.get("url"):
        st.link_button("Open on Kleinanzeigen ↗", current["url"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Price", format_euro(current.get("price")))
    c2.metric("Mileage", format_mileage(current.get("mileage_km")))
    c3.metric("Registration", str(current.get("first_registration") or "—"))
    c4.metric("Fuel", str(current.get("fuel") or "—"))
    c5.metric("Transmission", str(current.get("transmission") or "—"))

    st.write(
        {
            "Location": current.get("location"),
            "Posted date": current.get("posted_date"),
            "Views": current.get("view_count"),
            "First seen": current.get("first_seen"),
            "Last seen": current.get("last_seen"),
            "Last checked": current.get("last_checked_at"),
        }
    )

    st.divider()
    st.subheader("Comparable / Score")

    if score_row is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Experimental Deal Score", format_score(score_row.get("deal_score")))
        c2.metric("Comparable Median", format_euro(score_row.get("group_median_price")))
        c3.metric("Difference", format_percent(score_row.get("discount_percent")))
        comp_count = score_row.get("group_count", score_row.get("valid_price_count", "—"))
        c4.metric("Comparables", str(comp_count if pd.notna(comp_count) else "—"))
        st.caption(
            f"Score status: {score_row.get('score_status', '—')} · "
            f"Median mileage: {format_mileage(score_row.get('group_median_km'))}"
        )
    else:
        st.warning("This listing is not part of the active current-market scoring universe.")

    history = load_history(listing_id)
    st.divider()
    st.subheader("History")

    if history.empty:
        st.info("No history observations available.")
        return

    price_history = history.dropna(subset=["price"]).copy()
    if not price_history.empty:
        price_history = price_history.loc[price_history["price"].ne(price_history["price"].shift())]
        st.markdown("**Price history**")
        st.line_chart(price_history.set_index("scraped_at")[["price"]])

        if len(price_history) >= 2:
            first_price = float(price_history.iloc[0]["price"])
            last_price = float(price_history.iloc[-1]["price"])
            if first_price > 0 and last_price < first_price:
                st.info(
                    f"Observed price: {format_euro(first_price)} → {format_euro(last_price)} "
                    f"({format_euro(first_price - last_price)} reduction)"
                )

    view_history = history.dropna(subset=["view_count"]).copy()
    if len(view_history) >= 2:
        st.markdown("**View-count history**")
        st.line_chart(view_history.set_index("scraped_at")[["view_count"]])

    with st.expander("Observation history"):
        st.dataframe(history, use_container_width=True, hide_index=True)


def render_market_overview() -> None:
    st.title("Market / Overview")

    overview = load_overview()
    market = load_dashboard_frame(active_market_only=True).copy()

    scorable = (
        int((market.get("score_status") == "SCORABLE").sum())
        if not market.empty and "score_status" in market.columns
        else 0
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Active", overview["active"])
    c2.metric("Total", overview["total"])
    c3.metric("New 24h", overview["new_24h"])
    c4.metric("Drops 24h", overview["price_drops_24h"])
    c5.metric("Scorable", scorable)

    st.caption(
        "Freshness proxies — these are observation timestamps, not proof of a completed successful scrape."
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Latest search presence", str(overview["latest_search_presence"] or "—"))
    c2.metric("Latest detail observation", str(overview["latest_detail_observation"] or "—"))
    c3.metric("Latest lifecycle check", str(overview["latest_lifecycle_check"] or "—"))

    if market.empty:
        st.info("No active market data available.")
        return

    market["year_display"] = _year_series(market)

    valid_scatter = market.dropna(subset=[c for c in ["mileage_km", "price"] if c in market.columns]).copy()
    if {"mileage_km", "price"}.issubset(valid_scatter.columns) and not valid_scatter.empty:
        st.subheader("Price vs Mileage")
        st.scatter_chart(valid_scatter, x="mileage_km", y="price")

    if "year_group" in market.columns and "price" in market.columns:
        groups = (
            market.dropna(subset=["year_group", "price"])
            .groupby("year_group", as_index=False)
            .agg(median_price=("price", "median"), listings=("listing_id", "count"))
        )
        if not groups.empty:
            st.subheader("Median Asking Price by Year Group")
            st.bar_chart(groups.set_index("year_group")[["median_price"]])
            st.dataframe(groups, use_container_width=True, hide_index=True)

    listings = load_listings().copy()
    if "first_seen" in listings.columns:
        listings["first_seen_dt"] = pd.to_datetime(listings["first_seen"], utc=True, errors="coerce")
        daily = (
            listings.dropna(subset=["first_seen_dt"])
            .assign(day=lambda x: x["first_seen_dt"].dt.date)
            .groupby("day", as_index=False)
            .size()
            .rename(columns={"size": "new_listings"})
        )
        if not daily.empty:
            st.subheader("New Listings Over Time")
            st.line_chart(daily.set_index("day")[["new_listings"]])

    st.subheader("Top Opportunities")
    if "score_status" in market.columns:
        top = market.loc[market["score_status"] == "SCORABLE"].copy()
    else:
        top = market.copy()
    if "deal_score" in top.columns:
        top = top.sort_values("deal_score", ascending=False).head(5)
    cols = [c for c in ["deal_score", "price", "discount_percent", "title", "mileage_km", "url"] if c in top.columns]
    st.dataframe(top[cols], use_container_width=True, hide_index=True)

    st.subheader("Data Quality")
    quality_items = {}
    for label, col in [
        ("Missing price", "price"),
        ("Missing mileage", "mileage_km"),
        ("Missing registration", "first_registration"),
    ]:
        if col in listings.columns:
            quality_items[label] = int(listings[col].isna().sum())

    if "transmission" in listings.columns:
        quality_items["Unknown transmission"] = int(
            listings["transmission"].fillna("").astype(str).str.upper().eq("UNKNOWN").sum()
        )
    if "score_status" in market.columns:
        quality_items["Unscorable active"] = int((market["score_status"] != "SCORABLE").sum())

    st.write(quality_items)
