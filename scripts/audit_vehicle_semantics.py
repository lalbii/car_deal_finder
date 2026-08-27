from __future__ import annotations

from collections import Counter
import sqlite3

import pandas as pd

from analytics.vehicle_semantics import BodyStyle, Drivetrain, extract_vehicle_semantics
from config.paths import DB_PATH


def load_active_listings_read_only() -> pd.DataFrame:
    path = DB_PATH.resolve()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        return pd.read_sql_query(
            "SELECT listing_id, title FROM listings WHERE is_active = 1",
            connection,
        )


def _coverage(counts: Counter, unknown, total: int) -> float:
    return 0.0 if total == 0 else (total - counts[unknown]) / total * 100.0


def _print_samples(listings: pd.DataFrame, column: str, value: str) -> None:
    matches = listings.loc[listings[column].eq(value)].sort_values("listing_id", kind="mergesort").head(10)
    if matches.empty:
        return
    print(f"\nSAMPLE {column.upper()} {value}")
    for row in matches.itertuples():
        print(f"{row.listing_id} | {row.title}")


def main() -> int:
    listings = load_active_listings_read_only()
    semantics = listings["title"].apply(extract_vehicle_semantics)
    listings["body_style"] = semantics.apply(lambda result: result.body_style.value)
    listings["drivetrain"] = semantics.apply(lambda result: result.drivetrain.value)
    body_counts = Counter(BodyStyle(value) for value in listings["body_style"])
    drivetrain_counts = Counter(Drivetrain(value) for value in listings["drivetrain"])

    print(f"Active listings: {len(listings)}\n")
    print("BODY STYLE")
    for value in BodyStyle:
        print(f"{value.value}: {body_counts[value]}")
    print("\nDRIVETRAIN")
    for value in Drivetrain:
        print(f"{value.value}: {drivetrain_counts[value]}")
    print(f"\nBody style semantic coverage: {_coverage(body_counts, BodyStyle.UNKNOWN, len(listings)):.1f}%")
    print(f"Drivetrain semantic coverage: {_coverage(drivetrain_counts, Drivetrain.UNKNOWN, len(listings)):.1f}%")

    for value in BodyStyle:
        if value != BodyStyle.UNKNOWN:
            _print_samples(listings, "body_style", value.value)
    _print_samples(listings, "drivetrain", Drivetrain.AWD.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
