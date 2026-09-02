from __future__ import annotations

import math
import time

import altair as alt
import pandas as pd
import streamlit as st

from config.search_loader import load_search_configs
from dashboard.data import (
    canonical_lifecycle_status,
    load_collector_run,
    load_dashboard_frame,
    load_history,
    load_inactive_frame,
    load_inactive_score_calibration,
    load_listing_analysis,
    load_listings,
    load_opportunity_snapshots_before_inactivity,
    load_overview,
    load_price_drop_summary,
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
from validation.listing_quality import (
    DataQuality,
    classify_first_registration,
    classify_mileage,
    classify_price,
)


POSITIVE_ONLY_DEFAULT = False
INCLUDE_UNSCORED_LABEL = "Include unscored listings"
INCLUDE_UNSCORED_HELP = (
    "Include active listings that do not currently have an Opportunity Score."
)
REAL_CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW")


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
    include_unscored: bool = False,
    minimum_score: float | None = None,
    minimum_discount: float | None = None,
    minimum_gap: float | None = None,
    positive_only: bool = POSITIVE_ONLY_DEFAULT,
    confidences: tuple[str, ...] | None = None,
    year_range: tuple[int, int] | None = None,
    mileage_max: int | None = None,
    transmissions: tuple[str, ...] | None = None,
    body_styles: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    filtered = df.copy()
    if not include_unscored:
        filtered = filtered.loc[filtered["opportunity_score"].notna()]
    if positive_only:
        discount = pd.to_numeric(filtered["discount_percent"], errors="coerce")
        gap = pd.to_numeric(filtered["market_gap_eur"], errors="coerce")
        filtered = filtered.loc[discount.ge(0) & gap.ge(0)]
    for column, minimum in (
        ("opportunity_score", minimum_score),
        ("discount_percent", minimum_discount),
        ("market_gap_eur", minimum_gap),
    ):
        if minimum is None:
            continue
        values = pd.to_numeric(filtered[column], errors="coerce")
        filtered = filtered.loc[values.ge(minimum)]
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


def build_opportunity_funnel(
    listings: pd.DataFrame,
    active_market: pd.DataFrame,
    shown: pd.DataFrame,
) -> dict[str, int]:
    """Return read-only Opportunity funnel and diagnostic presentation counts."""
    active = listings.loc[listings["is_active"].eq(1)].copy()
    core_issue = pd.Series(False, index=active.index)
    for column, classifier in (
        ("price", classify_price),
        ("mileage_km", classify_mileage),
        ("first_registration", classify_first_registration),
    ):
        qualities = active[column].apply(classifier)
        core_issue |= qualities.isin({DataQuality.MISSING, DataQuality.INVALID})

    accepted_ids = set(active.loc[~core_issue, "listing_id"].astype(str))
    accepted_market = active_market.loc[
        active_market["listing_id"].astype(str).isin(accepted_ids)
    ]
    strict_eligible = active_market["eligibility_status"].eq("ELIGIBLE")
    valued = active_market["market_value_status"].eq("OK")
    scored = active_market["opportunity_score"].notna()
    shown_scored = int(shown["opportunity_score"].notna().sum())
    shown_unscored = int(shown["opportunity_score"].isna().sum())
    ineligible_or_risk = accepted_market["eligibility_status"].ne("ELIGIBLE")
    insufficient = (
        strict_eligible
        & active_market["market_value_status"].eq("INSUFFICIENT_COMPARABLES")
    )
    return {
        "Total DB": len(listings),
        "Active": len(active),
        "Eligible": int(strict_eligible.sum()),
        "Valued": int(valued.sum()),
        "Scored": int(scored.sum()),
        "Shown": len(shown),
        "Shown scored": shown_scored,
        "Shown unscored": shown_unscored,
        "Inactive": int(listings["is_active"].eq(0).sum()),
        "Core data issues": int(core_issue.sum()),
        "Ineligible / risk": int(ineligible_or_risk.sum()),
        "Insufficient comparables": int(insufficient.sum()),
    }


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
    listings = load_listings().copy()
    df = load_dashboard_frame(active_market_only=True).copy()
    if df.empty:
        st.info("No active listings available.")
        return

    year_values = pd.to_numeric(df["year"], errors="coerce").dropna()
    mileage_values = pd.to_numeric(df["mileage_km"], errors="coerce").dropna()
    confidence_values = [
        value for value in REAL_CONFIDENCE_LEVELS
        if df["valuation_confidence"].eq(value).any()
    ]
    transmission_values = sorted(df["transmission"].dropna().astype(str).unique())
    body_values = sorted(df["body_style"].dropna().unique())
    scored = df.loc[df["opportunity_score"].notna()]
    discount_values = pd.to_numeric(scored["discount_percent"], errors="coerce").dropna()
    gap_values = pd.to_numeric(scored["market_gap_eur"], errors="coerce").dropna()
    neutral_discount = float(discount_values.min()) if not discount_values.empty else 0.0
    neutral_gap = float(gap_values.min()) if not gap_values.empty else 0.0
    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4, c5 = st.columns(5)
        minimum_score = c1.number_input("Minimum Opportunity Score", 0.0, 100.0, 0.0, 1.0)
        minimum_discount = c2.number_input(
            "Minimum Discount %", value=neutral_discount, step=1.0
        )
        minimum_gap = c3.number_input(
            "Minimum Market Gap €", value=neutral_gap, step=500.0
        )
        include_unscored = c4.checkbox(
            INCLUDE_UNSCORED_LABEL,
            value=False,
            help=INCLUDE_UNSCORED_HELP,
        )
        positive_only = c5.checkbox(
            "Positive opportunities only",
            value=POSITIVE_ONLY_DEFAULT,
            help="Show only listings with non-negative market gap and discount.",
        )
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
        include_unscored=include_unscored,
        minimum_score=None if minimum_score == 0.0 else minimum_score,
        minimum_discount=(
            None if minimum_discount == neutral_discount else minimum_discount
        ),
        minimum_gap=None if minimum_gap == neutral_gap else minimum_gap,
        positive_only=positive_only,
        confidences=None if confidences == tuple(confidence_values) else confidences,
        year_range=year_range,
        mileage_max=mileage_max,
        transmissions=transmissions,
        body_styles=body_styles,
    )
    funnel = build_opportunity_funnel(listings, df, filtered)
    funnel_columns = st.columns(6)
    for column, label in zip(
        funnel_columns,
        ("Total DB", "Active", "Eligible", "Valued", "Scored", "Shown"),
    ):
        help_text = (
            "Strict valuation ELIGIBLE only; risk listings are excluded."
            if label == "Eligible"
            else None
        )
        column.metric(label, funnel[label], help=help_text)
    with st.expander("Funnel diagnostics", expanded=False):
        st.caption(
            " · ".join(
                f"{label}: {funnel[label]}"
                for label in (
                    "Inactive",
                    "Core data issues",
                    "Ineligible / risk",
                    "Insufficient comparables",
                )
            )
        )
    shown_detail = (
        f"{funnel['Shown scored']} scored"
        + (
            f" · {funnel['Shown unscored']} unscored"
            if funnel["Shown unscored"]
            else ""
        )
    )
    if include_unscored:
        st.write(f"**Showing {funnel['Shown']} active listings**")
        st.caption(shown_detail)
    else:
        st.write(
            f"**Showing {funnel['Shown']} of {funnel['Scored']} "
            "scored listings**"
        )
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


def market_label(name: str) -> str:
    """Return a compact label without inferring vehicle semantics."""
    return " ".join(
        token.upper() if token.casefold() in {"bmw", "nrw"} else token
        for token in name.replace("_", " ").split()
    )


def scope_market_rows(
    frame: pd.DataFrame, selected: str, enabled_markets: tuple[str, ...]
) -> pd.DataFrame:
    """Scope rows only through a persisted search association when required."""
    if len(enabled_markets) == 1:
        return frame.copy()
    if "search_name" not in frame.columns:
        raise ValueError(
            "Multiple searches are configured, but listings have no persisted "
            "search association; markets cannot be mixed safely."
        )
    return frame.loc[frame["search_name"].eq(selected)].copy()


def listing_age_days(frame: pd.DataFrame) -> pd.Series:
    posted = pd.to_datetime(
        frame.get("posted_date"), dayfirst=True, utc=True, errors="coerce"
    )
    checked = pd.to_datetime(
        frame.get("last_checked_at"), utc=True, errors="coerce", format="mixed"
    )
    age = (checked.dt.normalize() - posted.dt.normalize()).dt.days.astype("Float64")
    return age.where(age.ge(0))


def build_market_snapshot(active: pd.DataFrame) -> dict[str, float | int | None]:
    prices = pd.to_numeric(active["price"], errors="coerce")
    mileages = pd.to_numeric(active["mileage_km"], errors="coerce")
    valid_prices = prices.loc[
        active["price"].apply(classify_price).eq(DataQuality.VALID)
    ]
    valid_mileages = mileages.loc[
        active["mileage_km"].apply(classify_mileage).eq(DataQuality.VALID)
    ]
    scored = active.loc[active["opportunity_score"].notna()]
    positive = (
        pd.to_numeric(scored["discount_percent"], errors="coerce").ge(0)
        & pd.to_numeric(scored["market_gap_eur"], errors="coerce").ge(0)
    )
    return {
        "active": len(active),
        "median_price": valid_prices.median() if not valid_prices.empty else None,
        "median_mileage": valid_mileages.median() if not valid_mileages.empty else None,
        "median_age_days": listing_age_days(active).median(),
        "median_discount": pd.to_numeric(
            scored["discount_percent"], errors="coerce"
        ).median(),
        "positive_rate": float(positive.mean() * 100) if len(scored) else None,
    }


def aggregate_price_by_year(active: pd.DataFrame) -> pd.DataFrame:
    rows = active.copy()
    rows["year"] = _year_series(rows)
    rows["price"] = pd.to_numeric(rows["price"], errors="coerce")
    rows = rows.loc[
        rows["year"].notna()
        & rows["price"].notna()
        & rows["price"].apply(classify_price).eq(DataQuality.VALID)
    ]
    result = rows.groupby("year", sort=True)["price"].agg(
        median_asking_price="median", listing_count="size"
    ).reset_index()
    result["year"] = result["year"].astype(int)
    return result


MILEAGE_BUCKETS = (0, 50_000, 100_000, 150_000, 200_000, 250_000, 300_000, float("inf"))
MILEAGE_LABELS = ("0–50k", "50–100k", "100–150k", "150–200k", "200–250k", "250–300k", "300k+")
AGE_BUCKETS = (0, 3, 8, 15, 31, 61, float("inf"))
AGE_LABELS = ("0–2 days", "3–7 days", "8–14 days", "15–30 days", "31–60 days", "60+ days")
SCORE_BUCKETS = (0, 20, 40, 60, 80, 101)
SCORE_LABELS = ("0–20", "20–40", "40–60", "60–80", "80–100")


def aggregate_price_by_mileage(active: pd.DataFrame) -> pd.DataFrame:
    rows = active.copy()
    rows["price"] = pd.to_numeric(rows["price"], errors="coerce")
    rows["mileage_km"] = pd.to_numeric(rows["mileage_km"], errors="coerce")
    rows = rows.loc[
        rows["price"].apply(classify_price).eq(DataQuality.VALID)
        & rows["mileage_km"].apply(classify_mileage).eq(DataQuality.VALID)
    ].copy()
    rows["Mileage bucket"] = pd.cut(
        rows["mileage_km"], MILEAGE_BUCKETS, labels=MILEAGE_LABELS, right=False
    )
    return rows.groupby("Mileage bucket", observed=False)["price"].agg(
        median_asking_price="median", listing_count="size"
    ).reset_index()


def bucket_counts(values: pd.Series, bins: tuple, labels: tuple, name: str) -> pd.DataFrame:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    buckets = pd.cut(numeric, bins, labels=labels, right=False)
    counts = buckets.value_counts(sort=False).reindex(labels, fill_value=0)
    return pd.DataFrame({name: labels, "listing_count": counts.to_numpy()})


def build_score_inactive_calibration(rows: pd.DataFrame) -> pd.DataFrame:
    """Aggregate last persisted pre-inactivity scores by listing lifetime."""
    columns = ["Score bucket", "median_time_to_inactive_days", "sample_count"]
    if rows.empty:
        return pd.DataFrame(columns=columns)
    values = rows.copy()
    posted = pd.to_datetime(
        values["posted_date"], dayfirst=True, utc=True, errors="coerce"
    )
    inactive = pd.to_datetime(
        values["inactive_at"], utc=True, errors="coerce", format="mixed"
    )
    values["time_to_inactive_days"] = (
        inactive.dt.normalize() - posted.dt.normalize()
    ).dt.days
    values["opportunity_score"] = pd.to_numeric(
        values["opportunity_score"], errors="coerce"
    )
    values = values.loc[
        values["time_to_inactive_days"].ge(0)
        & values["opportunity_score"].between(0, 100)
    ].copy()
    values["Score bucket"] = pd.cut(
        values["opportunity_score"],
        SCORE_BUCKETS,
        labels=SCORE_LABELS,
        right=False,
    )
    return (
        values.groupby("Score bucket", observed=False)["time_to_inactive_days"]
        .agg(median_time_to_inactive_days="median", sample_count="size")
        .reset_index()
    )


def build_score_inactive_display_table(calibration: pd.DataFrame) -> pd.DataFrame:
    """Format calibration medians and sample quality without changing results."""
    display = calibration.copy()
    display["Median Time to Inactive"] = display[
        "median_time_to_inactive_days"
    ].map(lambda value: "—" if pd.isna(value) else f"{float(value):.1f}d")
    display["n"] = display["sample_count"].astype(int)
    display["Sample Quality"] = display["n"].map(
        lambda count: "NO DATA" if count == 0 else "LOW SAMPLE" if count < 5 else "OK"
    )
    return display[[
        "Score bucket", "Median Time to Inactive", "n", "Sample Quality"
    ]].rename(columns={"Score bucket": "Score Bucket"})


def build_score_inactive_chart(calibration: pd.DataFrame) -> alt.Chart:
    """Build the ordered, zero-baseline calibration visualization."""
    chart_data = calibration.copy()
    chart_data["sample_label"] = chart_data["sample_count"].map(
        lambda count: f"n={int(count)}"
    )
    base = alt.Chart(chart_data).encode(
        x=alt.X(
            "Score bucket:N",
            sort=list(SCORE_LABELS),
            title="Last Opportunity Score Before Inactivity",
        ),
        y=alt.Y(
            "median_time_to_inactive_days:Q",
            title="Median Time to Inactive (days)",
            scale=alt.Scale(zero=True, domainMin=0),
        ),
        tooltip=[
            alt.Tooltip("Score bucket:N", title="Score bucket"),
            alt.Tooltip(
                "median_time_to_inactive_days:Q",
                title="Median days",
                format=".1f",
            ),
            alt.Tooltip("sample_count:Q", title="n", format="d"),
        ],
    )
    bars = base.mark_bar()
    labels = base.transform_filter(
        "isValid(datum.median_time_to_inactive_days)"
    ).mark_text(dy=-8).encode(text="sample_label:N")
    return (bars + labels).properties(height=300)


def build_confidence_mix(active: pd.DataFrame) -> pd.DataFrame:
    return (
        active.loc[
            active["valuation_confidence"].isin(REAL_CONFIDENCE_LEVELS),
            "valuation_confidence",
        ]
        .value_counts()
        .reindex(REAL_CONFIDENCE_LEVELS, fill_value=0)
        .rename_axis("Confidence")
        .reset_index(name="listing_count")
    )


def build_market_coverage(active: pd.DataFrame) -> dict[str, int]:
    return {
        "Active": len(active),
        "Strictly Eligible": int(active["eligibility_status"].eq("ELIGIBLE").sum()),
        "Valued": int(active["market_value_status"].eq("OK").sum()),
        "Scored": int(active["opportunity_score"].notna().sum()),
        "Unscored": int(active["opportunity_score"].isna().sum()),
        "Missing price": int(active["price"].isna().sum()),
        "Missing mileage": int(active["mileage_km"].isna().sum()),
        "Missing registration": int(active["first_registration"].isna().sum()),
    }


def build_inactive_timeline(
    listings: pd.DataFrame, now: pd.Timestamp | None = None
) -> pd.DataFrame:
    inactive = pd.to_datetime(
        listings.loc[listings["is_active"].eq(0), "inactive_at"],
        utc=True, errors="coerce", format="mixed",
    ).dropna()
    reference = now or pd.Timestamp.now(tz="UTC")
    days = inactive.loc[inactive.between(reference - pd.Timedelta(days=30), reference)].dt.floor("D")
    return days.value_counts().sort_index().rename_axis("date").reset_index(name="listing_count")


def build_views_age_scatter(active: pd.DataFrame) -> pd.DataFrame:
    result = active.copy()
    result["Listing Age (days)"] = listing_age_days(result)
    result["Views"] = pd.to_numeric(result["view_count"], errors="coerce")
    result["Asking Price"] = pd.to_numeric(result["price"], errors="coerce")
    result["Opportunity Score"] = pd.to_numeric(
        result["opportunity_score"], errors="coerce"
    )
    return result.loc[
        result["Listing Age (days)"].notna() & result["Views"].notna(),
        ["Listing Age (days)", "Views", "title", "Asking Price", "Opportunity Score"],
    ].rename(columns={"title": "Title"})


def build_market_top_table(active: pd.DataFrame, limit: int = 5) -> pd.DataFrame:
    top = sort_opportunities(
        active.loc[active["opportunity_score"].notna()]
    ).head(limit)
    links = [
        url if isinstance(url, str) and is_listing_detail_url(url, listing_id) else None
        for url, listing_id in zip(top["url"], top["listing_id"])
    ]
    return pd.DataFrame({
        "Score": top["opportunity_score"],
        "Title": top["title"],
        "Asking": top["price"].map(format_euro),
        "Estimated Market": top["estimated_market_price"].map(format_euro),
        "Market Gap €": top["market_gap_eur"].map(format_signed_euro),
        "Discount %": top["discount_percent"].map(format_signed_percent),
        "Confidence": top["valuation_confidence"],
        "Open Listing": links,
    }, index=top.index)


def render_market_overview() -> None:
    started = time.perf_counter()
    st.title("Market / Overview")
    configs = load_search_configs()
    enabled = tuple(name for name, config in configs.items() if config.enabled)
    if not enabled:
        st.info("No enabled markets are configured.")
        return
    selected = st.selectbox("Market", enabled, format_func=market_label, key="market_overview_search")
    overview = load_overview()
    listings = load_listings().copy()
    market = load_dashboard_frame(active_market_only=True).copy()
    try:
        selected_listings = scope_market_rows(listings, selected, enabled)
        market = scope_market_rows(market, selected, enabled)
    except ValueError as exc:
        st.error(str(exc))
        return
    if market.empty:
        st.info("No active market data available.")
        return

    snapshot = build_market_snapshot(market)
    st.subheader("Market Snapshot")
    columns = st.columns(6)
    values = (
        ("Active Listings", snapshot["active"]),
        ("Median Asking Price", format_euro(snapshot["median_price"])),
        ("Median Mileage", format_mileage(snapshot["median_mileage"])),
        ("Median Listing Age", f"{snapshot['median_age_days']:.0f} days" if pd.notna(snapshot["median_age_days"]) else "—"),
        ("Median Discount", format_percent(snapshot["median_discount"])),
        ("Positive Opportunity Rate", format_percent(snapshot["positive_rate"])),
    )
    for column, (label, value) in zip(columns, values):
        help_text = "Discount relative to estimated asking-market value, not realized sale value." if label == "Median Discount" else None
        column.metric(label, value, help=help_text)

    st.subheader("Market Structure")
    left, right = st.columns(2)
    by_year = aggregate_price_by_year(market)
    with left:
        st.markdown("**Median Asking Price by Year**")
        st.bar_chart(by_year, x="year", y="median_asking_price")
        with st.expander("Year sample counts"):
            st.dataframe(by_year, hide_index=True, use_container_width=True)
    by_mileage = aggregate_price_by_mileage(market)
    with right:
        st.markdown("**Median Asking Price by Mileage**")
        st.bar_chart(by_mileage, x="Mileage bucket", y="median_asking_price")
        with st.expander("Mileage-bucket sample counts"):
            st.dataframe(by_mileage, hide_index=True, use_container_width=True)

    st.subheader("Inventory")
    left, right = st.columns(2)
    age_distribution = bucket_counts(listing_age_days(market), AGE_BUCKETS, AGE_LABELS, "Listing age")
    with left:
        st.markdown("**Listing Age Distribution**")
        st.bar_chart(age_distribution, x="Listing age", y="listing_count")
    score_distribution = bucket_counts(market["opportunity_score"], SCORE_BUCKETS, SCORE_LABELS, "Score")
    with right:
        st.markdown("**Opportunity Score Distribution**")
        st.bar_chart(score_distribution, x="Score", y="listing_count")

    st.subheader("Analysis Quality")
    confidence = build_confidence_mix(market)
    st.bar_chart(confidence, x="Confidence", y="listing_count")

    st.subheader("Market Activity")
    left, right = st.columns(2)
    timeline = build_inactive_timeline(selected_listings)
    with left:
        st.markdown("**Listings Becoming Inactive — Last 30 Days**")
        st.caption("INACTIVE does not mean sold; listings may be deleted, withdrawn, expired, sold, or otherwise unavailable.")
        st.line_chart(timeline, x="date", y="listing_count", x_label="Day")
    selected_ids = set(selected_listings["listing_id"].astype(str))
    drops = load_price_drop_summary()
    drops = drops.loc[drops["listing_id"].astype(str).isin(selected_ids)].copy()
    with right:
        st.markdown("**Price Reduction Activity**")
        d1, d2, d3 = st.columns(3)
        d1.metric("Listings With Observed Price Drop", len(drops))
        d2.metric("Median Observed Price Drop €", format_euro(drops["price_drop_abs"].median() if not drops.empty else None))
        d3.metric("Median Observed Price Drop %", format_percent(drops["price_drop_percent"].median() if not drops.empty else None))
        if not drops.empty:
            drop_timeline = pd.to_datetime(drops["last_reduction_at"], utc=True, errors="coerce").dropna().dt.floor("D").value_counts().sort_index().rename_axis("date").reset_index(name="listing_count")
            st.bar_chart(drop_timeline, x="date", y="listing_count", x_label="Day")

    calibration_rows = load_inactive_score_calibration()
    calibration_rows = calibration_rows.loc[
        calibration_rows["listing_id"].astype(str).isin(selected_ids)
    ] if not calibration_rows.empty else calibration_rows
    calibration = build_score_inactive_calibration(calibration_rows)
    st.markdown("**Opportunity Score vs Time to Inactive**")
    qualifying = int(calibration["sample_count"].sum()) if not calibration.empty else 0
    if qualifying == 0:
        st.info(
            "Not enough historical scored inactive listings yet. This chart "
            "will become more meaningful as snapshot history accumulates."
        )
    else:
        chart = build_score_inactive_chart(calibration)
        st.altair_chart(chart, width="stretch")
        display = build_score_inactive_display_table(calibration)
        st.dataframe(display, hide_index=True, use_container_width=True)
        if display["Sample Quality"].eq("LOW SAMPLE").any():
            st.caption(
                "Buckets with fewer than 5 listings are early-sample estimates "
                "and should not be interpreted as stable calibration. Historical "
                "sample is still small; calibration becomes more meaningful as "
                "more scored listings become inactive."
            )
    st.caption(
        "Lower values mean listings became unavailable sooner after publication. "
        "Score uses the last recorded Opportunity Score before inactivity. "
        "Inactive does not necessarily mean sold."
    )

    st.subheader("Demand Exploration")
    scatter = build_views_age_scatter(market)
    st.markdown("**Views vs Listing Age**")
    st.caption("Kleinanzeigen views are cumulative observed page views.")
    st.scatter_chart(scatter, x="Listing Age (days)", y="Views")

    st.subheader("Top Opportunities")
    top = build_market_top_table(market)
    st.dataframe(top, use_container_width=True, hide_index=True, column_config={"Score": st.column_config.NumberColumn(format="%.1f"), "Open Listing": st.column_config.LinkColumn(display_text="Open ↗")})

    st.subheader("Coverage & Data Quality")
    coverage = build_market_coverage(market)
    coverage_columns = st.columns(5)
    for column, label in zip(coverage_columns, ("Active", "Strictly Eligible", "Valued", "Scored", "Unscored")):
        column.metric(label, coverage[label])
    st.caption(" · ".join(f"{label}: {coverage[label]}" for label in ("Missing price", "Missing mileage", "Missing registration")))
    with st.expander("Data freshness", expanded=False):
        st.caption(
            f"Latest search presence: {format_datetime(overview['latest_search_presence'])} · "
            f"Latest detail observation: {format_datetime(overview['latest_detail_observation'])} · "
            f"Latest lifecycle check: {format_datetime(overview['latest_lifecycle_check'])}"
        )
    st.caption(f"Overview prepared in {time.perf_counter() - started:.2f}s")
