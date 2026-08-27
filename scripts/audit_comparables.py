from __future__ import annotations

import argparse
import sqlite3

import pandas as pd

from analytics.comparables import ComparableConfig, find_comparables
from analytics.vehicle_semantics import extract_vehicle_semantics
from config.paths import DB_PATH
from normalization.vehicle_fields import normalize_transmission, registration_year


def load_listings_read_only() -> pd.DataFrame:
    path = DB_PATH.resolve()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA query_only = ON")
        return pd.read_sql_query("SELECT * FROM listings", connection)


def _number(value, fallback: str = "—") -> str:
    return fallback if pd.isna(value) else f"{int(value):,}"


def audit_listing(listing_id: str, listings: pd.DataFrame, semantic_v3: bool = False) -> int:
    match = listings.loc[listings["listing_id"].astype(str).eq(str(listing_id))]
    if match.empty:
        print(f"Listing not found: {listing_id}")
        return 1

    target = match.iloc[0]
    result = find_comparables(target, listings)
    old_result = find_comparables(
        target,
        listings,
        ComparableConfig(body_style_guardrails=False),
    ) if semantic_v3 else None
    print("TARGET\n")
    print(f"listing_id: {target['listing_id']}")
    print(f"title: {target.get('title') or '—'}")
    print(f"year: {registration_year(target.get('first_registration')) or '—'}")
    print(f"mileage: {_number(target.get('mileage_km'))} km")
    print(f"transmission: {normalize_transmission(target.get('transmission')).value}")
    print(f"price: €{_number(target.get('price'))}")
    print(f"body style: {extract_vehicle_semantics(target.get('title')).body_style.value}")
    print("\nCOMPARABLE ENGINE\n")
    print(f"active listings: {result.active_count}")
    print(f"clean ELIGIBLE: {result.eligible_count}")
    print(f"ELIGIBLE_WITH_RISK: {result.risk_count}")
    print(f"INELIGIBLE: {result.ineligible_count}")
    print(f"after same transmission: {result.transmission_match_count}")
    print(f"after year threshold: {result.year_match_count}")
    print(f"after mileage threshold: {result.mileage_match_count}")
    if semantic_v3:
        print(f"old candidate count: {old_result.candidate_count}")
        print(f"new candidate count: {result.candidate_count}")
        print(f"known body-style mismatches removed: {result.known_body_style_mismatch_count}")
        print(f"unknown candidates retained: {result.unknown_body_style_count}")
        print(f"same-style candidates retained: {result.same_body_style_count}")
    print(f"candidate_count: {result.candidate_count}")
    print(f"returned: {result.comparable_count}")
    print(f"status: {result.status.value}")
    print("\nTOP COMPARABLES\n")
    print("ID | YEAR | KM | PRICE | BODY | FACTOR | YEAR Δ | KM Δ | WEIGHT | TITLE")
    for _, row in result.comparables.head(10).iterrows():
        print(
            f"{row['listing_id']} | {_number(row['year'])} | {_number(row['mileage_km'])} | "
            f"€{_number(row['price'])} | {row['candidate_body_style']} | "
            f"{row['body_style_factor']:.2f} | {_number(row['year_distance'])} | "
            f"{_number(row['mileage_distance_km'])} | {row['similarity_weight']:.4f} | "
            f"{row.get('title') or '—'}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect clean active comparable listings")
    parser.add_argument("--listing-id", required=True, help="Target Kleinanzeigen listing ID")
    parser.add_argument(
        "--semantic-v3",
        action="store_true",
        help="Include Comparable Engine v2/v3 body-style diagnostics",
    )
    args = parser.parse_args()
    return audit_listing(args.listing_id, load_listings_read_only(), args.semantic_v3)


if __name__ == "__main__":
    raise SystemExit(main())
