from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from dashboard.data import (
    canonical_lifecycle_status,
    load_collector_run,
    load_dashboard_frame,
    load_history,
    load_inactive_frame,
    load_listing_analysis,
    load_listings,
    load_opportunity_snapshots_before_inactivity,
    load_overview,
)
from dashboard.formatting import (
    format_datetime,
    format_euro,
    format_listing_age,
    format_listing_date,
    format_mileage,
    format_percent,
    format_score,
    format_signed_euro,
    format_signed_percent,
    relative_time,
)
from parsers.status_parser import is_listing_detail_url


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


def build_opportunities_table(filtered: pd.DataFrame) -> pd.DataFrame:
    """Build the visible opportunity table without changing analytics ordering."""
    last_checked = (
        filtered["last_checked_at"]
        if "last_checked_at" in filtered.columns
        else pd.Series(None, index=filtered.index, dtype=object)
    )
    posted_date = (
        filtered["posted_date"]
        if "posted_date" in filtered.columns
        else pd.Series(None, index=filtered.index, dtype=object)
    )
    is_active = (
        filtered["is_active"]
        if "is_active" in filtered.columns
        else pd.Series(None, index=filtered.index, dtype=object)
    )
    return pd.DataFrame(
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
            "Listing Date": posted_date.map(format_listing_date),
            "Last Checked": last_checked.map(format_datetime),
            "Listing Age": pd.Series(
                (format_listing_age(published, checked)
                 for published, checked in zip(posted_date, last_checked)),
                index=filtered.index,
            ),
            "Status": is_active.map(canonical_lifecycle_status),
            "Open Listing": filtered["url"],
        }
    )



def build_comparables_table(comparables: pd.DataFrame) -> pd.DataFrame:
    """Build Listing Detail rows with validated persisted URLs as metadata."""
    rows = comparables.head(10).copy()
    listing_ids = (
        rows["listing_id"]
        if "listing_id" in rows
        else pd.Series(None, index=rows.index, dtype=object)
    )
    urls = (
        rows["url"]
        if "url" in rows
        else pd.Series(None, index=rows.index, dtype=object)
    )
    open_listing = pd.Series(
        (
            url if isinstance(url, str) and is_listing_detail_url(url, listing_id) else None
            for url, listing_id in zip(urls, listing_ids)
        ),
        index=rows.index,
        dtype=object,
    )

    def column(name: str) -> pd.Series:
        return (
            rows[name]
            if name in rows
            else pd.Series(None, index=rows.index, dtype=object)
        )

    return pd.DataFrame(
        {
            "Title": column("title"),
            "Price": column("price"),
            "Year": column("year"),
            "Mileage": column("mileage_km"),
            "Body Style": column("candidate_body_style"),
            "Similarity": column("similarity_weight"),
            "Open Listing": open_listing,
        },
        index=rows.index,
    )


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
    if transmissions is not None:
        filtered = filtered.loc[
            filtered["transmission"].fillna("UNKNOWN").astype(str).isin(transmissions)
        ]
    if body_styles is not None:
        filtered = filtered.loc[
            filtered["body_style"].fillna("UNKNOWN").astype(str).isin(body_styles)
        ]
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


def _inactive_filter_argument(selected: object, neutral_default: object) -> object:
    """Disable a filter until its widget differs from the full-dataset default."""
    return None if selected == neutral_default else selected


def _inactive_count_label(shown: int, total: int) -> str:
    return f"Showing {shown} of {total} inactive listings"


def build_inactive_table(filtered: pd.DataFrame) -> pd.DataFrame:
    """Build the selectable inactive table with its stable ID hidden by the UI."""
    return pd.DataFrame(
        {
            "listing_id": filtered["listing_id"].astype(str),
            "Title": filtered["title"].fillna("—"),
            "Last Asking Price": filtered["last_asking_price"].map(format_euro),
            "Initial Observed Price": filtered["initial_observed_price"].map(
                format_euro
            ),
            "Last Observed Price": filtered["last_observed_price"].map(format_euro),
            "Price Change €": filtered["price_change_eur"].map(format_signed_euro),
            "Price Change %": filtered["price_change_percent"].map(
                format_signed_percent
            ),
            "Year": filtered["year"],
            "Mileage": filtered["mileage_km"].map(format_mileage),
            "Transmission": filtered["transmission"].fillna("UNKNOWN"),
            "Body Style": filtered["body_style"].fillna("UNKNOWN"),
            "First Seen": filtered["first_seen"].map(_format_date),
            "Last Search Presence": filtered["last_seen"].map(_format_date),
            "Observed Duration": filtered["observed_duration_days"].map(
                _format_observed_duration
            ),
        }
    )


def resolve_selected_listing_id(
    table: pd.DataFrame, selected_rows: list[int] | tuple[int, ...]
) -> str | None:
    """Resolve a selection immediately to its stable listing ID."""
    if not selected_rows:
        return None
    row_position = selected_rows[0]
    if row_position < 0 or row_position >= len(table):
        return None
    return str(table.iloc[row_position]["listing_id"])


def build_history_series(history: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """Return valid persisted observations in deterministic chronological order."""
    columns = ["scraped_at", value_column]
    if history.empty or not set(columns).issubset(history.columns):
        return pd.DataFrame(columns=columns)
    series = history[columns].copy()
    series["scraped_at"] = pd.to_datetime(
        series["scraped_at"], utc=True, errors="coerce", format="mixed"
    )
    series[value_column] = pd.to_numeric(series[value_column], errors="coerce")
    series = series.dropna(subset=columns)
    return series.sort_values("scraped_at", kind="mergesort").reset_index(drop=True)


def _render_selected_inactive_history(listing: pd.Series) -> None:
    listing_id = str(listing["listing_id"])
    title = listing.get("title")
    title = None if title is None or pd.isna(title) else str(title)
    transmission = listing.get("transmission")
    transmission = (
        "UNKNOWN"
        if transmission is None or pd.isna(transmission)
        else str(transmission)
    )
    body_style = listing.get("body_style")
    body_style = (
        "UNKNOWN" if body_style is None or pd.isna(body_style) else str(body_style)
    )
    st.subheader("Selected Listing")
    st.markdown(f"**{title or f'Listing {listing_id}'}**")
    metadata = {
        "Listing ID": listing_id,
        "Last Asking Price": format_euro(listing.get("last_asking_price")),
        "Year": str(int(listing["year"])) if pd.notna(listing.get("year")) else "—",
        "Mileage": format_mileage(listing.get("mileage_km")),
        "Transmission": transmission,
        "Body Style": body_style,
        "First Seen": format_datetime(listing.get("first_seen")),
        "Last Search Presence": format_datetime(listing.get("last_seen")),
        "Inactive At": format_datetime(listing.get("inactive_at")),
        "Observed Duration": _format_observed_duration(
            listing.get("observed_duration_days")
        ),
    }
    st.write(metadata)
    st.caption(f"Confirmed inactive: {format_datetime(listing.get('inactive_at'))}")

    snapshots = load_opportunity_snapshots_before_inactivity(listing_id)
    st.subheader("Historical Opportunity Score")
    if snapshots.empty:
        st.info("Historical Opportunity Score unavailable")
    else:
        latest = snapshots.iloc[-1]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Last Opportunity Score", format_score(latest["opportunity_score"]))
        c2.metric("Confidence", str(latest["valuation_confidence"]))
        c3.metric("Estimated Market", format_euro(latest["estimated_market_price"]))
        c4.metric("Market Gap €", format_signed_euro(latest["market_gap_eur"]))
        c5.metric("Discount %", format_signed_percent(latest["discount_percent"]))
        st.write(
            {
                "Comparable Count": int(latest["comparable_count"]),
                "Strong Comparables": int(latest["strong_comparable_count"]),
                "Score Version": str(latest["score_version"]),
                "Snapshot Time": format_datetime(latest["observed_at"]),
                "Inactive At": format_datetime(listing.get("inactive_at")),
            }
        )
        if len(snapshots) > 1:
            score_history = build_history_series(
                snapshots.rename(columns={"observed_at": "scraped_at"}),
                "opportunity_score",
            ).rename(columns={"scraped_at": "observed_at"})
            st.subheader("Opportunity Score Over Time")
            st.line_chart(
                score_history,
                x="observed_at",
                y="opportunity_score",
                x_label="Snapshot time",
                y_label="Opportunity Score",
            )

    history = load_history(listing_id)
    invalid_timestamps = 0
    if "scraped_at" in history.columns:
        invalid_timestamps = int(history["scraped_at"].isna().sum())
    price_history = build_history_series(history, "price")
    view_history = build_history_series(history, "view_count")

    st.subheader("Price History")
    if price_history.empty:
        st.info("Price history is not available for this listing.")
    else:
        prices = price_history["price"]
        initial = float(prices.iloc[0])
        last = float(prices.iloc[-1])
        change = last - initial
        change_percent = (change / initial * 100.0) if initial > 0 else None
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Initial observed price", format_euro(initial))
        c2.metric("Last observed price", format_euro(last))
        c3.metric("Lowest observed price", format_euro(prices.min()))
        c4.metric("Price change €", format_signed_euro(change))
        c5.metric("Price change %", format_signed_percent(change_percent))
        c6.metric("Price observations", len(price_history))
        st.line_chart(
            price_history,
            x="scraped_at",
            y="price",
            x_label="Observation time",
            y_label="Price (€)",
        )

    st.subheader("Views Over Time")
    if view_history.empty:
        st.info("View history is not available for this listing.")
    else:
        views = view_history["view_count"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("First observed views", f"{int(views.iloc[0]):,}")
        c2.metric("Last observed views", f"{int(views.iloc[-1]):,}")
        c3.metric("View increase", f"{int(views.iloc[-1] - views.iloc[0]):+,}")
        c4.metric("View observations", len(view_history))
        st.caption("View counts are cumulative values reported by Kleinanzeigen.")
        st.line_chart(
            view_history,
            x="scraped_at",
            y="view_count",
            x_label="Observation time",
            y_label="Views",
        )
    if invalid_timestamps:
        st.caption(
            f"Excluded {invalid_timestamps} historical observation(s) with an "
            "invalid timestamp."
        )


def _format_observed_duration(days: object) -> str:
    value = pd.to_numeric(pd.Series([days]), errors="coerce").iloc[0]
    if pd.isna(value) or value < 0:
        return "—"
    total_minutes = int(round(float(value) * 24 * 60))
    if total_minutes == 0:
        return "0h"
    if total_minutes < 60:
        return f"{total_minutes}m"
    total_hours = (total_minutes + 30) // 60
    whole_days, hours = divmod(total_hours, 24)
    if whole_days == 0:
        return f"{hours}h"
    return f"{whole_days}d {hours}h" if hours else f"{whole_days}d"


def _reset_inactive_filters() -> None:
    for key in (
        "inactive_year_range",
        "inactive_mileage_max",
        "inactive_duration_max",
        "inactive_transmissions",
        "inactive_body_styles",
        "inactive_price_decreased_only",
        "inactive_price_range",
    ):
        st.session_state.pop(key, None)


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
    table = build_opportunities_table(filtered)
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Opportunity Score": st.column_config.NumberColumn(format="%.1f", help=OPPORTUNITY_HELP),
            "Listing Date": st.column_config.TextColumn(
                help="Actual publication date reported by Kleinanzeigen."
            ),
            "Last Checked": st.column_config.TextColumn(
                help="Latest persisted conclusive lifecycle/detail check."
            ),
            "Listing Age": st.column_config.TextColumn(
                help="Whole calendar days from the Kleinanzeigen publication date to the latest direct check."
            ),
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
    years = pd.to_numeric(df["year"], errors="coerce").dropna()
    mileages = pd.to_numeric(df["mileage_km"], errors="coerce").dropna()
    valid_prices = prices.dropna()
    valid_durations = durations.dropna()
    transmission_values = sorted(df["transmission"].fillna("UNKNOWN").astype(str).unique())
    body_values = sorted(df["body_style"].fillna("UNKNOWN").astype(str).unique())
    neutral_year_range = (
        (int(years.min()), int(years.max())) if not years.empty else None
    )
    neutral_mileage_max = int(mileages.max()) if not mileages.empty else None
    neutral_duration_max = (
        max(0, math.ceil(float(valid_durations.max())))
        if not valid_durations.empty
        else None
    )
    neutral_transmissions = tuple(transmission_values)
    neutral_body_styles = tuple(body_values)
    neutral_price_range = (
        (float(valid_prices.min()), float(valid_prices.max()))
        if len(valid_prices) and valid_prices.min() < valid_prices.max()
        else None
    )
    with st.expander("Filters", expanded=True):
        st.button("Reset filters", on_click=_reset_inactive_filters)
        c1, c2, c3 = st.columns(3)
        year_range = (
            c1.slider(
                "Year range",
                neutral_year_range[0],
                neutral_year_range[1],
                neutral_year_range,
                key="inactive_year_range",
            )
            if neutral_year_range is not None
            else None
        )
        mileage_max = (
            c2.number_input(
                "Maximum mileage",
                0,
                neutral_mileage_max,
                neutral_mileage_max,
                10_000,
                key="inactive_mileage_max",
            )
            if neutral_mileage_max is not None
            else None
        )
        duration_max = (
            c3.number_input(
                "Maximum observed duration (days)",
                0,
                neutral_duration_max,
                neutral_duration_max,
                1,
                key="inactive_duration_max",
            )
            if neutral_duration_max is not None
            else None
        )
        c4, c5, c6 = st.columns(3)
        transmissions = tuple(
            c4.multiselect(
                "Transmission",
                transmission_values,
                transmission_values,
                key="inactive_transmissions",
            )
        )
        body_styles = tuple(
            c5.multiselect(
                "Body Style",
                body_values,
                body_values,
                key="inactive_body_styles",
            )
        )
        price_decreased_only = c6.checkbox(
            "Price decreased only",
            value=False,
            key="inactive_price_decreased_only",
        )
        price_range = (
            st.slider(
                "Last Asking Price range",
                neutral_price_range[0],
                neutral_price_range[1],
                neutral_price_range,
                step=500.0,
                key="inactive_price_range",
            )
            if neutral_price_range is not None
            else None
        )

    filtered = filter_inactive_listings(
        df,
        year_range=_inactive_filter_argument(year_range, neutral_year_range),
        mileage_max=_inactive_filter_argument(mileage_max, neutral_mileage_max),
        transmissions=_inactive_filter_argument(
            transmissions, neutral_transmissions
        ),
        body_styles=_inactive_filter_argument(body_styles, neutral_body_styles),
        price_range=_inactive_filter_argument(price_range, neutral_price_range),
        duration_max_days=_inactive_filter_argument(
            duration_max, neutral_duration_max
        ),
        price_decreased_only=price_decreased_only,
    )
    filtered_prices = pd.to_numeric(filtered["last_asking_price"], errors="coerce")
    filtered_durations = pd.to_numeric(
        filtered["observed_duration_days"], errors="coerce"
    )
    filtered_drops = pd.to_numeric(
        filtered["price_change_eur"], errors="coerce"
    ).lt(0)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Shown Inactive Listings", len(filtered))
    c2.metric("Median Last Asking Price", format_euro(filtered_prices.median()))
    c3.metric(
        "Median Observed Duration",
        _format_observed_duration(filtered_durations.median()),
    )
    c4.metric("Listings With Price Drops", int(filtered_drops.sum()))
    st.write(f"**{_inactive_count_label(len(filtered), len(df))}**")
    table = build_inactive_table(filtered)
    event = st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="inactive_listings_table",
        column_config={
            "listing_id": None,
        },
    )
    selected_rows = getattr(event.selection, "rows", []) if event else []
    selected_id = resolve_selected_listing_id(table, selected_rows)
    if selected_id is None:
        st.info("Select an inactive listing to inspect its history.")
        return
    selected = filtered.loc[filtered["listing_id"].astype(str).eq(selected_id)]
    if selected.empty:
        st.info("Select an inactive listing to inspect its history.")
        return
    _render_selected_inactive_history(selected.iloc[0])


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
        "Listing Date": format_listing_date(listing.get("posted_date")),
        "Last Checked": format_datetime(listing.get("last_checked_at")),
        "Listing Age": format_listing_age(
            listing.get("posted_date"), listing.get("last_checked_at")
        ),
        "Status": canonical_lifecycle_status(listing.get("is_active")),
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
        comparables = build_comparables_table(market.comparables)
        st.dataframe(
            comparables,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Open Listing": st.column_config.LinkColumn(display_text="Open ↗"),
            },
        )

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
