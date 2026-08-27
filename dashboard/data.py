from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

try:
    from config.paths import DB_PATH
except Exception:
    PROJECT_ROOT = Path(__file__).resolve().parents[1]
    DB_PATH = PROJECT_ROOT / "data" / "listings.db"

try:
    from analytics.deal_score import add_deal_scores
except ImportError:
    add_deal_scores = None


CACHE_TTL_SECONDS = 60


def _connect_read_only() -> sqlite3.Connection:
    db_path = Path(DB_PATH).resolve()
    conn = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=5,
    )
    conn.execute("PRAGMA query_only = ON")
    return conn


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_listings() -> pd.DataFrame:
    with _connect_read_only() as conn:
        return pd.read_sql_query("SELECT * FROM listings", conn)


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


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def load_dashboard_frame(active_market_only: bool = True) -> pd.DataFrame:
    listings = load_listings().copy()

    if listings.empty:
        return listings

    listings["listing_id"] = listings["listing_id"].astype(str)

    market = listings.copy()
    if active_market_only and "is_active" in market.columns:
        market = market.loc[market["is_active"] == 1].copy()

    # Reuse the existing analytics function as the single scoring source of truth.
    if add_deal_scores is not None and not market.empty:
        scored_market = add_deal_scores(market.copy())
    else:
        scored_market = market.copy()

    drops = load_price_drop_summary()
    if not drops.empty:
        drops["listing_id"] = drops["listing_id"].astype(str)
        scored_market = scored_market.merge(drops, on="listing_id", how="left")

    return scored_market


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
