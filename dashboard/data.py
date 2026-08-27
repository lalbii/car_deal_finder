from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

from analytics.comparables import find_comparables
from analytics.market_value import estimate_market_value
from analytics.opportunity import (
    calculate_economic_opportunity,
    calculate_opportunity_score,
)
from analytics.valuation_eligibility import evaluate_valuation_eligibility
from analytics.vehicle_semantics import extract_vehicle_semantics
from normalization.vehicle_fields import registration_year

try:
    from config.paths import DB_PATH
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = PROJECT_ROOT / "data" / "listings.db"

CACHE_TTL_SECONDS = 60
OPPORTUNITY_CACHE_TTL_SECONDS = 3_600


def _connect_read_only() -> sqlite3.Connection:
    db_path = Path(DB_PATH).resolve()
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=5,
    )
    conn.execute("PRAGMA query_only = ON")
    return conn


def dashboard_source_freshness(db_path: str | Path = DB_PATH) -> tuple:
    """Return a cheap cache key tied to persisted dashboard source changes."""
    path = Path(db_path).resolve()
    stat = path.stat()
    latest_run = None
    latest_listing = None
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        try:
            latest_run = conn.execute(
                "SELECT MAX(finished_at) FROM scrape_runs WHERE succeeded = 1"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass
        try:
            latest_listing = conn.execute(
                "SELECT MAX(last_seen) FROM listings"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            pass
    return stat.st_mtime_ns, stat.st_size, latest_run, latest_listing


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _load_listings_cached(freshness: tuple) -> pd.DataFrame:
    with _connect_read_only() as conn:
        return pd.read_sql_query("SELECT * FROM listings", conn)


def load_listings() -> pd.DataFrame:
    return _load_listings_cached(dashboard_source_freshness())


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_history(listing_id: str) -> pd.DataFrame:
    with _connect_read_only() as conn:
        df = pd.read_sql_query(
            '''
            SELECT listing_id, price, mileage_km, view_count, is_active, scraped_at
            FROM listing_history
            WHERE listing_id = ?
            ORDER BY scraped_at ASC
            ''',
            conn,
            params=(listing_id,),
        )
    if "scraped_at" in df.columns:
        df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True, errors="coerce")
    return df


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_all_history_prices() -> pd.DataFrame:
    with _connect_read_only() as conn:
        df = pd.read_sql_query(
            '''
            SELECT listing_id, price, scraped_at
            FROM listing_history
            WHERE price IS NOT NULL
            ORDER BY listing_id, scraped_at
            ''',
            conn,
        )
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], utc=True, errors="coerce")
    return df


def _derive_price_drop_summary(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(
            columns=[
                "listing_id",
                "previous_price",
                "current_history_price",
                "price_drop_abs",
                "price_drop_percent",
                "last_reduction_at",
            ]
        )

    rows = []
    for listing_id, group in history.groupby("listing_id", sort=False):
        g = group.dropna(subset=["price"]).sort_values("scraped_at").copy()
        if len(g) < 2:
            continue

        # Collapse consecutive identical prices for change detection.
        g = g.loc[g["price"].ne(g["price"].shift())]
        if len(g) < 2:
            continue

        reductions = g.loc[g["price"] < g["price"].shift()]
        if reductions.empty:
            continue

        last_idx = reductions.index[-1]
        pos = g.index.get_loc(last_idx)
        current_row = g.iloc[pos]
        previous_row = g.iloc[pos - 1]
        previous = float(previous_row["price"])
        current = float(current_row["price"])
        if previous <= 0:
            continue

        rows.append(
            {
                "listing_id": str(listing_id),
                "previous_price": previous,
                "current_history_price": current,
                "price_drop_abs": previous - current,
                "price_drop_percent": ((previous - current) / previous) * 100.0,
                "last_reduction_at": current_row["scraped_at"],
            }
        )

    return pd.DataFrame(rows)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_price_drop_summary() -> pd.DataFrame:
    return _derive_price_drop_summary(load_all_history_prices())


def build_opportunity_frame(
    listings: pd.DataFrame,
    active_market_only: bool = True,
) -> pd.DataFrame:
    """Build dashboard records exclusively through canonical analytics APIs."""
    if listings.empty:
        return listings.copy()

    listings = listings.copy()
    listings["listing_id"] = listings["listing_id"].astype(str)
    market = listings.copy()
    if active_market_only and "is_active" in market.columns:
        market = market.loc[market["is_active"] == 1].copy()
    rows = []
    for _, target in market.iterrows():
        eligibility = evaluate_valuation_eligibility(target)
        comparable = find_comparables(target, listings)
        market_value = estimate_market_value(comparable)
        economic = calculate_economic_opportunity(target.get("price"), market_value)
        score = calculate_opportunity_score(economic, eligibility.status)
        semantics = extract_vehicle_semantics(target.get("title"))
        row = target.to_dict()
        row.update(
            {
                "year": registration_year(target.get("first_registration")),
                "body_style": semantics.body_style.value,
                "eligibility_status": eligibility.status.value,
                "risk_reasons": ", ".join(reason.value for reason in eligibility.reasons),
                "market_value_status": market_value.status.value,
                "estimated_market_price": market_value.estimated_market_price,
                "valuation_confidence": market_value.confidence.value,
                "comparable_count": market_value.comparable_count,
                "market_gap_eur": economic.market_gap_eur,
                "discount_percent": economic.discount_percent,
                "economic_status": economic.status.value,
                "opportunity_score": score.opportunity_score,
                "score_version": score.score_version,
                "score_status": score.status.value,
                "discount_component": score.discount_component,
                "margin_component": score.margin_component,
                "base_opportunity": score.base_opportunity,
                "confidence_multiplier": score.confidence_multiplier,
                "risk_multiplier": score.risk_multiplier,
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


@st.cache_data(
    ttl=OPPORTUNITY_CACHE_TTL_SECONDS,
    show_spinner="Building opportunity dataset…",
)
def _load_dashboard_frame_cached(
    active_market_only: bool,
    freshness: tuple,
) -> pd.DataFrame:
    return build_opportunity_frame(_load_listings_cached(freshness), active_market_only)


def load_dashboard_frame(active_market_only: bool = True) -> pd.DataFrame:
    freshness = dashboard_source_freshness()
    return _load_dashboard_frame_cached(active_market_only, freshness)


@st.cache_data(ttl=OPPORTUNITY_CACHE_TTL_SECONDS, show_spinner=False)
def _load_listing_analysis_cached(listing_id: str, freshness: tuple) -> dict | None:
    listings = _load_listings_cached(freshness)
    match = listings.loc[listings["listing_id"].astype(str).eq(str(listing_id))]
    if match.empty:
        return None
    target = match.iloc[0]
    eligibility = evaluate_valuation_eligibility(target)
    comparable = find_comparables(target, listings)
    market_value = estimate_market_value(comparable)
    economic = calculate_economic_opportunity(target.get("price"), market_value)
    score = calculate_opportunity_score(economic, eligibility.status)
    semantics = extract_vehicle_semantics(target.get("title"))
    return {
        "listing": target,
        "eligibility": eligibility,
        "semantics": semantics,
        "comparable": comparable,
        "market_value": market_value,
        "economic": economic,
        "score": score,
    }


def load_listing_analysis(listing_id: str) -> dict | None:
    return _load_listing_analysis_cached(str(listing_id), dashboard_source_freshness())


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_overview() -> dict:
    listings = load_listings().copy()
    if listings.empty:
        return {
            "total": 0,
            "active": 0,
            "new_24h": 0,
            "price_drops_24h": 0,
            "latest_search_presence": None,
            "latest_detail_observation": None,
            "latest_lifecycle_check": None,
        }

    now = pd.Timestamp.now(tz="UTC")
    for col in ("first_seen", "last_seen", "last_checked_at"):
        if col in listings.columns:
            listings[col] = pd.to_datetime(listings[col], utc=True, errors="coerce")

    total = len(listings)
    active = int((listings["is_active"] == 1).sum()) if "is_active" in listings.columns else 0
    new_24h = (
        int((listings["first_seen"] >= now - pd.Timedelta(hours=24)).sum())
        if "first_seen" in listings.columns
        else 0
    )

    drops = load_price_drop_summary()
    if not drops.empty:
        recent_drops = pd.to_datetime(drops["last_reduction_at"], utc=True, errors="coerce")
        price_drops_24h = int((recent_drops >= now - pd.Timedelta(hours=24)).sum())
    else:
        price_drops_24h = 0

    with _connect_read_only() as conn:
        row = conn.execute("SELECT MAX(scraped_at) FROM listing_history").fetchone()
        latest_detail = row[0] if row else None

    return {
        "total": total,
        "active": active,
        "new_24h": new_24h,
        "price_drops_24h": price_drops_24h,
        "latest_search_presence": listings["last_seen"].max() if "last_seen" in listings.columns else None,
        "latest_detail_observation": latest_detail,
        "latest_lifecycle_check": listings["last_checked_at"].max() if "last_checked_at" in listings.columns else None,
    }


def get_listing(listing_id: str) -> Optional[pd.Series]:
    listings = load_listings()
    if listings.empty:
        return None
    match = listings.loc[listings["listing_id"].astype(str) == str(listing_id)]
    if match.empty:
        return None
    return match.iloc[0]



@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_collector_run() -> dict | None:
    try:
        with _connect_read_only() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT latest.*,
                       (SELECT MAX(finished_at) FROM scrape_runs WHERE succeeded = 1) AS last_success_at,
                       (SELECT COUNT(*) FROM scrape_runs) AS total_runs
                FROM scrape_runs AS latest ORDER BY finished_at DESC, id DESC LIMIT 1"""
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None

def clear_dashboard_cache() -> None:
    st.cache_data.clear()
