from __future__ import annotations

import argparse

import pandas as pd

from analytics.comparables import find_comparables
from analytics.market_value import estimate_market_value
from analytics.opportunity import calculate_economic_opportunity
from normalization.vehicle_fields import normalize_transmission, registration_year
from scripts.audit_comparables import load_listings_read_only


def _money(value) -> str:
    return "—" if value is None or pd.isna(value) else f"€{value:,.0f}"


def _signed_money(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:+,.0f} €"


def _signed_percent(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:+.1f}%"


def audit_listing(listing_id: str, listings: pd.DataFrame) -> int:
    match = listings.loc[listings["listing_id"].astype(str).eq(str(listing_id))]
    if match.empty:
        print(f"Listing not found: {listing_id}")
        return 1
    target = match.iloc[0]
    result = estimate_market_value(find_comparables(target, listings))
    asking = float(target["price"]) if pd.notna(target.get("price")) else None
    opportunity = calculate_economic_opportunity(asking, result)

    print("TARGET\n")
    print(f"ID: {target['listing_id']}")
    print(f"Title: {target.get('title') or '—'}")
    print(f"Year: {registration_year(target.get('first_registration')) or '—'}")
    print(f"Mileage: {int(target['mileage_km']):,} km")
    print(f"Transmission: {normalize_transmission(target.get('transmission')).value}")
    print(f"Asking price: {_money(asking)}")
    print("\nVALUATION\n")
    print(f"Status: {result.status.value}")
    print(f"Estimated market price: {_money(result.estimated_market_price)}")
    print(f"Confidence: {result.confidence.value}")
    print(f"Comparable count: {result.comparable_count}")
    print(f"Strong comparables: {result.strong_comparable_count}")
    print(f"Total similarity weight: {result.total_similarity_weight:.4f}")
    print(f"Weighted median: {_money(result.weighted_median_price)}")
    print(f"Unweighted median: {_money(result.unweighted_median_price)}")
    print(f"Q1: {_money(result.lower_reference_price)}")
    print(f"Q3: {_money(result.upper_reference_price)}")
    dispersion = "—" if result.price_dispersion is None else f"{result.price_dispersion:.3f}"
    print(f"Dispersion: {dispersion}")
    print("\nTARGET VS ESTIMATE\n")
    print(f"Asking: {_money(asking)}")
    print(f"Estimated market: {_money(result.estimated_market_price)}")
    print(f"Market gap: {_signed_money(opportunity.market_gap_eur)}")
    print(f"Discount: {_signed_percent(opportunity.discount_percent)}")
    print(f"Opportunity status: {opportunity.status.value}")
    print("\nTOP COMPARABLE PRICES\n")
    print("ID | PRICE | WEIGHT | TITLE")
    for _, row in result.comparables.head(10).iterrows():
        print(
            f"{row['listing_id']} | {_money(row['price'])} | "
            f"{row['similarity_weight']:.4f} | {row.get('title') or '—'}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit observed asking-market valuation")
    parser.add_argument("--listing-id", required=True)
    args = parser.parse_args()
    return audit_listing(args.listing_id, load_listings_read_only())


if __name__ == "__main__":
    raise SystemExit(main())
