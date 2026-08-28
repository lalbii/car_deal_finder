from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.data import (
    load_collector_run,
    load_dashboard_frame,
    load_history,
    load_inactive_frame,
    load_listing_analysis,
    load_listings,
    load_overview,
)
from dashboard.formatting import (
    format_euro,
    format_mileage,
    format_percent,
    format_score,
    format_signed_euro,
    format_signed_percent,
    relative_time,
)


OPPORTUNITY_HELP = (
    "Ranking heuristic based on observed asking-market discount, absolute market "
    "gap, valuation confidence, and eligibility risk. It is not expected profit "
    "or sale probability."
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


def sort_opportunities(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["opportunity_score", "discount_percent", "market_gap_eur", "listing_id"],
        ascending=[False, False, False, True],
        na_position="last",
        kind="mergesort",
    )


def filter_opportunities(
    df: pd.DataFrame,
    *,
    include_unavailable: bool = False,
    minimum_score: float = 0.0,
    minimum_discount: float = 0.0,
    minimum_gap: float = 0.0,
    confidences: tuple[str, ...] | None = None,
    year_range: tuple[int, int] | None = None,
    mileage_max: int | None = None,
    transmissions: tuple[str, ...] | None = None,
    body_styles: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    filtered = df.copy()
    if not include_unavailable:
        filtered = filtered.loc[filtered["opportunity_score"].notna()]
    for column, minimum in (
        ("opportunity_score", minimum_score),
        ("discount_percent", minimum_discount),
        ("market_gap_eur", minimum_gap),
    ):
        values = pd.to_numeric(filtered[column], errors="coerce")
        filtered = filtered.loc[values.ge(minimum) | (include_unavailable & values.isna())]
    if confidences:
        filtered = filtered.loc[filtered["valuation_confidence"].isin(confidences)]
    if year_range is not None:
        years = pd.to_numeric(filtered["year"], errors="coerce")
        filtered = filtered.loc[years.between(*year_range)]
    if mileage_max is not None:
        mileage = pd.to_numeric(filtered["mileage_km"], errors="coerce")
        filtered = filtered.loc[mileage.le(mileage_max)]
    if transmissions:
        filtered = filtered.loc[filtered["transmission"].astype(str).isin(transmissions)]
    if body_styles:
        filtered = filtered.loc[filtered["body_style"].isin(body_styles)]
    return sort_opportunities(filtered)


def sort_inactive_listings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    return df.sort_values(
        ["inactive_at", "listing_id"],
        ascending=[False, True],
        na_position="last",
        kind="mergesort",
    )


def filter_inactive_listings(
    df: pd.DataFrame,
    *,
    year_range: tuple[int, int] | None = None,
    mileage_max: int | None = None,
    transmissions: tuple[str, ...] | None = None,
    body_styles: tuple[str, ...] | None = None,
    price_range: tuple[float, float] | None = None,
    duration_max_days: int | None = None,
    price_decreased_only: bool = False,
) -> pd.DataFrame:
    filtered = df.copy()
    if year_range is not None:
        filtered = filtered.loc[pd.to_numeric(filtered["year"], errors="coerce").between(*year_range)]
    if mileage_max is not None:
        filtered = filtered.loc[
            pd.to_numeric(filtered["mileage_km"], errors="coerce").le(mileage_max)
        ]
    if transmissions:
        filtered = filtered.loc[filtered["transmission"].astype(str).isin(transmissions)]
    if body_styles:
        filtered = filtered.loc[filtered["body_style"].isin(body_styles)]
    if price_range is not None:
        filtered = filtered.loc[
            pd.to_numeric(filtered["last_asking_price"], errors="coerce").between(*price_range)
        ]
    if duration_max_days is not None:
        filtered = filtered.loc[
            pd.to_numeric(filtered["observed_duration_days"], errors="coerce").le(duration_max_days)
        ]
    if price_decreased_only:
        filtered = filtered.loc[
            pd.to_numeric(filtered["price_change_eur"], errors="coerce").lt(0)
        ]
    return sort_inactive_listings(filtered)


def _format_observed_duration(days: object) -> str:
    value = pd.to_numeric(pd.Series([days]), errors="coerce").iloc[0]
    if pd.isna(value) or value < 0:
        return "—"
    whole_days = int(value)
    return f"{whole_days} day" if whole_days == 1 else f"{whole_days} days"


def _format_date(value: object) -> str:
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    return "—" if pd.isna(timestamp) else timestamp.strftime("%Y-%m-%d")


def _collector_health(run: dict | None, now: pd.Timestamp | None = None) -> dict:
    now = now or pd.Timestamp.now(tz="UTC")
    if not run:
        return {"label": "⚪ UNKNOWN", "last": "—", "next": "—"}
    finished = pd.to_datetime(run.get("finished_at"), utc=True, errors="coerce")
    last_success = pd.to_datetime(run.get("last_success_at"), utc=True, errors="coerce")
    if pd.isna(finished):
        return {"label": "⚪ UNKNOWN", "last": "—", "next": "—"}
    if not bool(run.get("succeeded")) or int(run.get("blocking_failures") or 0) > 0:
        label = "🔴 ERROR"
    elif pd.isna(last_success) or now - last_success > pd.Timedelta(hours=2):
        label = "🟡 STALE"
    else:
        label = "🟢 HEALTHY"
    next_hour = now.floor("h") + pd.Timedelta(hours=1)
    minutes = max(0, int((next_hour - now).total_seconds() // 60))
    return {"label": label, "last": relative_time(last_success, now), "next": f"~{minutes} min"}


def _format_duration(seconds: object) -> str:
    total = max(0, int(float(seconds or 0)))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


def render_collector_health() -> None:
    run = load_collector_run()
    health = _collector_health(run)
    values = run or {}
    status_line = (
        f"<strong>{health['label']}</strong>&nbsp;&nbsp; Last success: {health['last']}"
        f"&nbsp;&nbsp; Next run: {health['next']} <span style=opacity:.65>(approx.)</span>"
        f"&nbsp;&nbsp; Runs: {int(values.get('total_runs') or 0)}"
    )
    metrics = (
        f"{int(values.get('listings_discovered') or 0)} seen │ "
        f"{int(values.get('new_listings') or 0)} new │ "
        f"{int(values.get('detail_requests') or 0)} details "
        f"({int(values.get('details_succeeded') or 0)} ok) │ "
        f"{int(values.get('retry_requests') or 0)} retries │ "
        f"{int(values.get('blocking_failures') or 0)} blocking │ "
        f"{_format_duration(values.get('duration_seconds'))}"
    )
    st.markdown(
        f'<div style="border:1px solid rgba(128,128,128,.35);border-radius:.45rem;'
        f'padding:.55rem .8rem;margin-bottom:.8rem;line-height:1.35">'
        f'<div style="font-size:.7rem;font-weight:700;letter-spacing:.12em;opacity:.7">'
        f'COLLECTOR</div><div style="font-size:.9rem">{status_line}</div>'
        f'<div style="font-size:.78rem;opacity:.82">{metrics}</div></div>',
        unsafe_allow_html=True,
    )


def render_opportunities() -> None:
    st.title("Opportunities")
    st.caption(OPPORTUNITY_HELP)
    df = load_dashboard_frame(active_market_only=True).copy()
    if df.empty:
        st.info("No active listings available.")
        return

    year_values = pd.to_numeric(df["year"], errors="coerce").dropna()
    mileage_values = pd.to_numeric(df["mileage_km"], errors="coerce").dropna()
    confidence_values = sorted(df["valuation_confidence"].dropna().unique())
    transmission_values = sorted(df["transmission"].dropna().astype(str).unique())
    body_values = sorted(df["body_style"].dropna().unique())
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        minimum_score = c1.number_input("Minimum Opportunity Score", 0.0, 100.0, 0.0, 1.0)
        minimum_discount = c2.number_input("Minimum Discount %", value=0.0, step=1.0)
        minimum_gap = c3.number_input("Minimum Market Gap €", value=0.0, step=500.0)
        include_unavailable = c4.checkbox("Include unavailable", value=False)
        c5, c6, c7, c8 = st.columns(4)
        confidences = tuple(c5.multiselect("Confidence", confidence_values, confidence_values))
        year_range = (
            c6.slider("Year range", int(year_values.min()), int(year_values.max()),
                      (int(year_values.min()), int(year_values.max())))
            if not year_values.empty else None
        )
        mileage_max = (
            c7.number_input("Maximum mileage", 0, int(mileage_values.max()), int(mileage_values.max()), 10_000)
            if not mileage_values.empty else None
        )
        transmissions = tuple(c8.multiselect("Transmission", transmission_values, transmission_values))
        body_styles = tuple(st.multiselect("Body Style", body_values, body_values))

    filtered = filter_opportunities(
        df,
        include_unavailable=include_unavailable,
        minimum_score=minimum_score,
        minimum_discount=minimum_discount,
        minimum_gap=minimum_gap,
        confidences=confidences,
        year_range=year_range,
        mileage_max=mileage_max,
        transmissions=transmissions,
        body_styles=body_styles,
    )
    st.write(f"**{len(filtered)} listings**")
    table = pd.DataFrame(
        {
            "listing_id": filtered["listing_id"],
            "Opportunity Score": filtered["opportunity_score"],
            "Title": filtered["title"],
            "Asking Price": filtered["price"].map(format_euro),
            "Estimated Market": filtered["estimated_market_price"].map(format_euro),
            "Market Gap €": filtered["market_gap_eur"].map(format_signed_euro),
            "Discount %": filtered["discount_percent"].map(format_signed_percent),
            "Confidence": filtered["valuation_confidence"],
            "Year": filtered["year"],
            "Mileage": filtered["mileage_km"].map(format_mileage),
            "Transmission": filtered["transmission"],
            "Body Style": filtered["body_style"],
            "First Seen": filtered["first_seen"].map(relative_time),
            "Open Listing": filtered["url"],
        }
    )
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Opportunity Score": st.column_config.NumberColumn(format="%.1f", help=OPPORTUNITY_HELP),
            "Open Listing": st.column_config.LinkColumn(display_text="Open ↗"),
            "listing_id": None,
        },
    )
    selected_rows = getattr(event.selection, "rows", []) if event else []
    if selected_rows:
        st.session_state["selected_listing_id"] = str(table.iloc[selected_rows[0]]["listing_id"])
        st.success("Listing selected. Open **Listing Detail** from the sidebar.")


def render_inactive_listings() -> None:
    st.title("Inactive Listings")
    st.warning(
        "INACTIVE does not necessarily mean SOLD. A listing may have been sold, "
        "deleted, expired, withdrawn, or otherwise become unavailable."
    )
    df = load_inactive_frame().copy()
    if df.empty:
        st.info("No canonically inactive listings available.")
        return

    prices = pd.to_numeric(df["last_asking_price"], errors="coerce")
    durations = pd.to_numeric(df["observed_duration_days"], errors="coerce")
    drops = pd.to_numeric(df["price_change_eur"], errors="coerce").lt(0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inactive Listings", len(df))
    c2.metric("Median Last Asking Price", format_euro(prices.median()))
    c3.metric("Median Observed Duration", _format_observed_duration(durations.median()))
    c4.metric("Listings With Price Drops", int(drops.sum()))

    years = pd.to_numeric(df["year"], errors="coerce").dropna()
    mileages = pd.to_numeric(df["mileage_km"], errors="coerce").dropna()
    valid_prices = prices.dropna()
    valid_durations = durations.dropna()
    transmission_values = sorted(df["transmission"].dropna().astype(str).unique())
    body_values = sorted(df["body_style"].dropna().astype(str).unique())
    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        year_range = (
            c1.slider("Year range", int(years.min()), int(years.max()),
                      (int(years.min()), int(years.max())))
            if not years.empty else None
        )
        mileage_max = (
            c2.number_input("Maximum mileage", 0, int(mileages.max()),
                            int(mileages.max()), 10_000)
            if not mileages.empty else None
        )
        duration_max = (
            c3.number_input("Maximum observed duration (days)", 0,
                            max(0, int(valid_durations.max())),
                            max(0, int(valid_durations.max())), 1)
            if not valid_durations.empty else None
        )
        c4, c5, c6 = st.columns(3)
        transmissions = tuple(c4.multiselect(
            "Transmission", transmission_values, transmission_values
        ))
        body_styles = tuple(c5.multiselect("Body Style", body_values, body_values))
        price_decreased_only = c6.checkbox("Price decreased only", value=False)
        price_range = (
            st.slider("Last Asking Price range", float(valid_prices.min()),
                      float(valid_prices.max()),
                      (float(valid_prices.min()), float(valid_prices.max())), step=500.0)
            if len(valid_prices) and valid_prices.min() < valid_prices.max() else None
        )

    filtered = filter_inactive_listings(
        df,
        year_range=year_range,
        mileage_max=mileage_max,
        transmissions=transmissions,
        body_styles=body_styles,
        price_range=price_range,
        duration_max_days=duration_max,
        price_decreased_only=price_decreased_only,
    )
    st.write(f"**{len(filtered)} listings**")
    table = pd.DataFrame({
        "Title": filtered["title"].fillna("—"),
        "Last Asking Price": filtered["last_asking_price"].map(format_euro),
        "Initial Observed Price": filtered["initial_observed_price"].map(format_euro),
        "Last Observed Price": filtered["last_observed_price"].map(format_euro),
        "Price Change €": filtered["price_change_eur"].map(format_signed_euro),
        "Price Change %": filtered["price_change_percent"].map(format_signed_percent),
        "Year": filtered["year"],
        "Mileage": filtered["mileage_km"].map(format_mileage),
        "Transmission": filtered["transmission"].fillna("—"),
        "Body Style": filtered["body_style"],
        "First Seen": filtered["first_seen"].map(_format_date),
        "Last Seen": filtered["last_seen"].map(_format_date),
        "Observed Duration": filtered["observed_duration_days"].map(_format_observed_duration),
        "Listing ID": filtered["listing_id"],
        "Open Listing": filtered["url"],
    })
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Open Listing": st.column_config.LinkColumn(display_text="Open ↗"),
        },
    )


def render_listing_detail() -> None:
    st.title("Listing Detail")
    listing_id = st.session_state.get("selected_listing_id")
    if not listing_id:
        st.info("Select a listing from Opportunities first.")
        return
    analysis = load_listing_analysis(listing_id)
    if analysis is None:
        st.error("Selected listing was not found.")
        return
    listing = analysis["listing"]
    eligibility = analysis["eligibility"]
    semantics = analysis["semantics"]
    market = analysis["market_value"]
    economic = analysis["economic"]
    score = analysis["score"]
    st.subheader(listing.get("title") or f"Listing {listing_id}")
    if listing.get("url"):
        st.link_button("Open listing ↗", listing["url"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Asking price", format_euro(listing.get("price")))
    year = _year_series(pd.DataFrame([listing])).iloc[0]
    c2.metric("Year", str(int(year)) if pd.notna(year) else "—")
    c3.metric("Mileage", format_mileage(listing.get("mileage_km")))
    c4.metric("Transmission", str(listing.get("transmission") or "—"))
    c5.metric("Body Style", semantics.body_style.value)
    st.write({
        "Eligibility": eligibility.status.value,
        "Risk reasons": [reason.value for reason in eligibility.reasons] or ["—"],
        "First seen": listing.get("first_seen"),
        "Listing age": relative_time(listing.get("first_seen")),
    })

    st.subheader("Valuation and economics")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Estimated market", format_euro(market.estimated_market_price))
    c2.metric("Confidence", market.confidence.value)
    c3.metric("Comparables", str(market.comparable_count))
    c4.metric("Market gap €", format_signed_euro(economic.market_gap_eur))
    c5.metric("Discount %", format_signed_percent(economic.discount_percent))

    st.subheader(f"Opportunity Score v{score.score_version}")
    st.caption(OPPORTUNITY_HELP)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Discount component", format_score(score.discount_component))
    c2.metric("Margin component", format_score(score.margin_component))
    c3.metric("Base opportunity", format_score(score.base_opportunity))
    c4.metric("Confidence multiplier", format_score(score.confidence_multiplier))
    c5.metric("Risk multiplier", format_score(score.risk_multiplier))
    c6.metric("Final score", format_score(score.opportunity_score))

    with st.expander("Top comparables used", expanded=False):
        comparables = market.comparables.head(10).copy()
        columns = [
            "title", "price", "year", "mileage_km", "candidate_body_style",
            "similarity_weight",
        ]
        columns = [column for column in columns if column in comparables]
        st.dataframe(comparables[columns], use_container_width=True, hide_index=True)

    history = load_history(listing_id)
    with st.expander("Observation history", expanded=False):
        if history.empty:
            st.info("No history observations available.")
        else:
            st.dataframe(history, use_container_width=True, hide_index=True)


def render_market_overview() -> None:
    st.title("Market / Overview")
    overview = load_overview()
    market = load_dashboard_frame(active_market_only=True).copy()
    if market.empty:
        st.info("No active market data available.")
        return
    clean = int(market["eligibility_status"].eq("ELIGIBLE").sum())
    valued = int(market["estimated_market_price"].notna().sum())
    scored = int(market["opportunity_score"].notna().sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active listings", overview["active"])
    c2.metric("Clean eligible", clean)
    c3.metric("Valuations available", valued)
    c4.metric("Opportunity scores", scored)
    c1, c2, c3 = st.columns(3)
    c1.metric("Median asking price", format_euro(pd.to_numeric(market["price"], errors="coerce").median()))
    c2.metric("Median estimated market", format_euro(pd.to_numeric(market["estimated_market_price"], errors="coerce").median()))
    c3.metric("Median discount", format_percent(pd.to_numeric(market["discount_percent"], errors="coerce").median()))

    st.caption(
        f"Latest search presence: {overview['latest_search_presence'] or '—'} · "
        f"Latest detail observation: {overview['latest_detail_observation'] or '—'} · "
        f"Latest lifecycle check: {overview['latest_lifecycle_check'] or '—'}"
    )
    st.subheader("Top Opportunities")
    top = sort_opportunities(market.loc[market["opportunity_score"].notna()]).head(5)
    st.dataframe(
        top[["opportunity_score", "title", "price", "estimated_market_price", "discount_percent", "url"]],
        use_container_width=True,
        hide_index=True,
    )
    st.subheader("Data Quality")
    listings = load_listings()
    st.write({
        "Missing price": int(listings["price"].isna().sum()),
        "Missing mileage": int(listings["mileage_km"].isna().sum()),
        "Missing registration": int(listings["first_registration"].isna().sum()),
        "Unvalued active": len(market) - valued,
    })
