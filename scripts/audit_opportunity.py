from __future__ import annotations

import argparse

import pandas as pd

from analytics.comparables import find_comparables
from analytics.market_value import MarketValueStatus, estimate_market_value
from analytics.opportunity import (
    calculate_economic_opportunity,
    calculate_opportunity_score,
)
from analytics.valuation_eligibility import (
    ValuationStatus,
    evaluate_valuation_eligibility,
)
from normalization.vehicle_fields import registration_year
from scripts.audit_comparables import load_listings_read_only


def _money(value) -> str:
    return "—" if value is None or pd.isna(value) else f"€{value:,.0f}"


def _signed_money(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:+,.0f} €"


def _signed_percent(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:+.1f}%"


def _evaluate(target: pd.Series, listings: pd.DataFrame):
    eligibility = evaluate_valuation_eligibility(target)
    market_value = estimate_market_value(find_comparables(target, listings))
    economic = calculate_economic_opportunity(target.get("price"), market_value)
    score = calculate_opportunity_score(economic, eligibility.status)
    return eligibility, market_value, economic, score


def audit_listing(listing_id: str, listings: pd.DataFrame) -> int:
    match = listings.loc[listings["listing_id"].astype(str).eq(str(listing_id))]
    if match.empty:
        print(f"Listing not found: {listing_id}")
        return 1
    target = match.iloc[0]
    eligibility, market_value, economic, score = _evaluate(target, listings)
    print("TARGET\n")
    print(f"ID: {target['listing_id']}")
    print(f"Title: {target.get('title') or '—'}")
    print(f"Year: {registration_year(target.get('first_registration')) or '—'}")
    print(f"Mileage: {int(target['mileage_km']):,} km")
    print(f"Eligibility: {eligibility.status.value}")
    print("\nVALUATION\n")
    print(f"Estimated market: {_money(market_value.estimated_market_price)}")
    print(f"Confidence: {market_value.confidence.value}")
    print(f"Comparables: {market_value.comparable_count}")
    print("\nECONOMICS\n")
    print(f"Asking: {_money(economic.asking_price)}")
    print(f"Market gap: {_signed_money(economic.market_gap_eur)}")
    print(f"Discount: {_signed_percent(economic.discount_percent)}")
    print("\nOPPORTUNITY SCORE v2\n")
    print(f"Status: {score.status.value}")
    print(f"Discount component: {score.discount_component if score.discount_component is not None else '—'}")
    print(f"Margin component: {score.margin_component if score.margin_component is not None else '—'}")
    print(f"Base score: {score.base_opportunity if score.base_opportunity is not None else '—'}")
    print(f"Confidence multiplier: {score.confidence_multiplier if score.confidence_multiplier is not None else '—'}")
    print(f"Risk multiplier: {score.risk_multiplier if score.risk_multiplier is not None else '—'}")
    final = "—" if score.opportunity_score is None else f"{score.opportunity_score:.1f}"
    print(f"Final Opportunity Score: {final}")
    return 0


def audit_all(listings: pd.DataFrame, top: int) -> int:
    active = listings.loc[listings["is_active"].eq(1)].copy()
    active["eligibility"] = active.apply(
        lambda row: evaluate_valuation_eligibility(row).status, axis=1
    )
    clean = active.loc[active["eligibility"].eq(ValuationStatus.ELIGIBLE)].copy()
    rows = []
    valued = 0
    scored = 0
    for _, target in clean.iterrows():
        _, market_value, economic, score = _evaluate(target, listings)
        if market_value.status == MarketValueStatus.OK:
            valued += 1
        if score.opportunity_score is not None:
            scored += 1
        rows.append(
            {
                "listing_id": str(target["listing_id"]),
                "title": target.get("title"),
                "year": registration_year(target.get("first_registration")),
                "mileage_km": target.get("mileage_km"),
                "asking_price": economic.asking_price,
                "estimated_market_price": economic.estimated_market_price,
                "market_gap_eur": economic.market_gap_eur,
                "discount_percent": economic.discount_percent,
                "confidence": economic.valuation_confidence.value,
                "opportunity_score": score.opportunity_score,
                "score_status": score.status.value,
            }
        )
    results = pd.DataFrame(rows)
    available = results.dropna(subset=["opportunity_score"]).sort_values(
        ["opportunity_score", "discount_percent", "market_gap_eur", "listing_id"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    print("DATASET AUDIT\n")
    print(f"Active listings: {len(active)}")
    print(f"Active clean listings: {len(clean)}")
    print(f"Valued listings: {valued}")
    print(f"Opportunity score available: {scored}")
    print(f"Unavailable valuations: {len(clean) - valued}")
    print(f"\nTOP {min(top, len(available))} OPPORTUNITIES\n")
    columns = [
        "listing_id", "title", "year", "mileage_km", "asking_price",
        "estimated_market_price", "market_gap_eur", "discount_percent",
        "confidence", "opportunity_score",
    ]
    if available.empty:
        print("No scores available.")
    else:
        print(available[columns].head(top).to_string(index=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Opportunity Score v2")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--listing-id")
    group.add_argument("--all", action="store_true", help="Score all active clean listings")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    if args.top < 1:
        parser.error("--top must be positive")
    listings = load_listings_read_only()
    return audit_all(listings, args.top) if args.all else audit_listing(args.listing_id, listings)


if __name__ == "__main__":
    raise SystemExit(main())
