import sqlite3
import pandas as pd

from config.paths import DATA_DIR, DB_PATH
from models.listing import TransmissionType
from normalization.vehicle_fields import (
    normalize_first_registration,
    normalize_transmission,
    registration_year,
)
from validation.listing_quality import (
    DataQuality,
    classify_first_registration,
    classify_mileage,
    classify_price,
)

MIN_COMPARABLE_VALUES = 3


def extract_year(first_registration: str | None) -> int | None:
    """Backward-compatible wrapper around canonical registration normalization."""
    return registration_year(first_registration)


def year_group(year: int | None) -> str | None:
    if year is None:
        return None

    if year >= 2020:
        return "2020+"
    if year >= 2016:
        return "2016-2019"
    if year >= 2012:
        return "2012-2015"
    if year >= 2008:
        return "2008-2011"

    return "older"


def load_listings() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)

    df = pd.read_sql_query(
        """
        SELECT
            listing_id,
            title,
            price,
            mileage_km,
            first_registration,
            fuel,
            transmission,
            location,
            url,
            is_active,
            posted_date,
            view_count
        FROM listings
        """,
        conn,
    )

    conn.close()
    return df


def add_time_view_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    now = pd.Timestamp.now()
    df["posted_dt"] = pd.to_datetime(
        df["posted_date"], format="%d.%m.%Y", errors="coerce"
    )

    df["days_since_posted"] = (
        now.tz_localize(None) - df["posted_dt"]
    ).dt.days

    df["freshness_score"] = 1 - (df["days_since_posted"] / 7)
    df["freshness_score"] = df["freshness_score"].clip(lower=0, upper=1)
    df.loc[df["days_since_posted"] < 0, "freshness_score"] = pd.NA

    valid_views = pd.to_numeric(df["view_count"], errors="coerce")
    valid_views = valid_views.where(valid_views >= 0)
    df["view_percentile"] = valid_views.rank(pct=True)

    df["low_view_score"] = 1 - df["view_percentile"]
    df["hot_view_score"] = df["view_percentile"]

    return df


def add_deal_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["normalized_first_registration"] = df["first_registration"].apply(
        lambda value: normalize_first_registration(value) if pd.notna(value) else None
    )
    df["year"] = df["normalized_first_registration"].apply(extract_year)
    df["year_group"] = df["year"].apply(year_group)
    df["transmission_group"] = df["transmission"].apply(
        lambda value: normalize_transmission(value).value
        if pd.notna(value)
        else TransmissionType.UNKNOWN.value
    )

    df["price_quality"] = df["price"].apply(classify_price)
    df["mileage_quality"] = df["mileage_km"].apply(classify_mileage)
    df["registration_quality"] = df["normalized_first_registration"].apply(
        classify_first_registration
    )
    df["price_for_stats"] = df["price"].where(
        df["price_quality"] == DataQuality.VALID.value
    )
    df["mileage_for_stats"] = df["mileage_km"].where(
        df["mileage_quality"] == DataQuality.VALID.value
    )

    valid_group = (
        (df["registration_quality"] == DataQuality.VALID.value)
        & (df["transmission_group"] != TransmissionType.UNKNOWN.value)
    )

    group_stats = (
        df.loc[valid_group]
        .groupby(["year_group", "transmission_group"])
        .agg(
            group_median_price=("price_for_stats", "median"),
            group_median_km=("mileage_for_stats", "median"),
            group_count=("listing_id", "count"),
            group_valid_price_count=("price_for_stats", "count"),
            group_valid_km_count=("mileage_for_stats", "count"),
        )
        .reset_index()
    )

    df = df.merge(
        group_stats,
        on=["year_group", "transmission_group"],
        how="left",
    )

    df["discount_ratio"] = (
        df["group_median_price"] - df["price"]
    ) / df["group_median_price"]

    df["discount_percent"] = df["discount_ratio"] * 100


    df["price_score"] = (
    df["group_median_price"] - df["price"]
    ) / df["group_median_price"]

    df["km_score"] = (
        df["group_median_km"] - df["mileage_km"]
    ) / df["group_median_km"]

    df = add_time_view_scores(df)

    deal_score = (
        0.55 * df["price_score"]
        + 0.25 * df["km_score"]
        + 0.15 * df["freshness_score"]
        + 0.05 * df["low_view_score"]
    )

    hot_listing_score = (
        0.40 * df["freshness_score"] +
        0.40 * df["hot_view_score"] +
        0.20 * df["price_score"]
    )

    valid_core = (
        (df["price_quality"] == DataQuality.VALID.value)
        & (df["mileage_quality"] == DataQuality.VALID.value)
        & (df["registration_quality"] == DataQuality.VALID.value)
        & (df["transmission_group"] != TransmissionType.UNKNOWN.value)
    )
    sufficient_comparables = (
        (df["group_valid_price_count"] >= MIN_COMPARABLE_VALUES)
        & (df["group_valid_km_count"] >= MIN_COMPARABLE_VALUES)
    )
    complete_signals = (
        df[["freshness_score", "low_view_score", "hot_view_score"]]
        .notna()
        .all(axis=1)
    )
    scorable = valid_core & sufficient_comparables & complete_signals

    df["score_status"] = "SCORABLE"
    df.loc[~complete_signals, "score_status"] = "MISSING_RANKING_SIGNALS"
    df.loc[~sufficient_comparables, "score_status"] = "INSUFFICIENT_COMPARABLES"
    df.loc[~valid_core, "score_status"] = "INVALID_OR_MISSING_CORE_DATA"
    df["deal_score"] = deal_score.where(scorable)
    df["hot_listing_score"] = hot_listing_score.where(scorable)

    df = df.sort_values("deal_score", ascending=False)
    return df


def main():
    df = load_listings()
    scored = add_deal_scores(df)

    cols = [
    "title",
    "price",
    "mileage_km",
    "first_registration",
    "year_group",
    "transmission",
    "group_count",
    "group_median_price",
    "group_median_km",
    "price_score",
    "km_score",
    "location",
    "url",
    "posted_date",
    "view_count",
    "days_since_posted",
    "freshness_score",
    "low_view_score",
    "hot_view_score",
    "deal_score",
    "hot_listing_score",
    "score_status",
    ]

    #print("\nTOP DEAL CANDIDATES")
    #print(scored[cols].head(10).to_string(index=False))
    #output_path = "data/deal_scores.csv"
    #scored.to_csv(output_path, index=False)

    scored.sort_values("deal_score", ascending=False).to_csv(
        DATA_DIR / "top_deals.csv",
        index=False,
    )

    scored.sort_values("hot_listing_score", ascending=False).to_csv(
        DATA_DIR / "hot_listings.csv",
        index=False,
    )

    print("Saved data/top_deals.csv")
    print("Saved data/hot_listings.csv")


if __name__ == "__main__":
    main()
