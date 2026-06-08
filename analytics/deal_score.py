import sqlite3
import re
import pandas as pd


DB_PATH = "data/listings.db"


GERMAN_MONTHS = {
    "Januar": 1,
    "Februar": 2,
    "März": 3,
    "April": 4,
    "Mai": 5,
    "Juni": 6,
    "Juli": 7,
    "August": 8,
    "September": 9,
    "Oktober": 10,
    "November": 11,
    "Dezember": 12,
}


def extract_year(first_registration: str | None) -> int | None:
    if not first_registration:
        return None

    match = re.search(r"(19|20)\d{2}", str(first_registration))
    if not match:
        return None

    return int(match.group(0))


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

from datetime import datetime


def parse_posted_date(date_text):
    if not date_text:
        return None

    try:
        return datetime.strptime(str(date_text), "%d.%m.%Y")
    except ValueError:
        return None


def add_time_view_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    now = pd.Timestamp.now()
    df["posted_dt"] = pd.to_datetime(df["posted_date"], format="%d.%m.%Y", errors="coerce")

    df["days_since_posted"] = (
        now.tz_localize(None) - df["posted_dt"]
    ).dt.days

    df["freshness_score"] = 1 - (df["days_since_posted"] / 7)
    df["freshness_score"] = df["freshness_score"].clip(lower=0, upper=1)

    df["view_percentile"] = df["view_count"].rank(pct=True)

    df["low_view_score"] = 1 - df["view_percentile"]
    df["hot_view_score"] = df["view_percentile"]

    return df


def add_deal_scores(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["year"] = df["first_registration"].apply(extract_year)
    df["year_group"] = df["year"].apply(year_group)

    group_stats = (
    df.groupby(["year_group", "transmission"])
    .agg(
        group_median_price=("price", "median"),
        group_median_km=("mileage_km", "median"),
        group_count=("listing_id", "count"),
    )
    .reset_index()
    )

    df = df.merge(
        group_stats,
        on=["year_group", "transmission"],
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

    df["deal_score"] = (
    0.55 * df["price_score"] +
    0.25 * df["km_score"] +
    0.15 * df["freshness_score"] +
    0.05 * df["low_view_score"]
    )

    df["hot_listing_score"] = (
        0.40 * df["freshness_score"] +
        0.40 * df["hot_view_score"] +
        0.20 * df["price_score"]
    )

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
    ]

    #print("\nTOP DEAL CANDIDATES")
    #print(scored[cols].head(10).to_string(index=False))
    #output_path = "data/deal_scores.csv"
    #scored.to_csv(output_path, index=False)

    scored.sort_values("deal_score", ascending=False).to_csv(
    "data/top_deals.csv",
    index=False,
    )

    scored.sort_values("hot_listing_score", ascending=False).to_csv(
        "data/hot_listings.csv",
        index=False,
    )

    print("Saved data/top_deals.csv")
    print("Saved data/hot_listings.csv")
    


if __name__ == "__main__":
    main()