from __future__ import annotations

import pandas as pd

from analytics.comparables import ComparableConfig, find_comparables
from analytics.market_value import MarketValueStatus, estimate_market_value
from analytics.opportunity import calculate_economic_opportunity, calculate_opportunity_score
from analytics.valuation_eligibility import ValuationStatus, evaluate_valuation_eligibility
from analytics.vehicle_semantics import BodyStyle, extract_vehicle_semantics
from scripts.audit_comparables import load_listings_read_only


REPRESENTATIVE_IDS = (
    "3476056500",
    "3493774504",
    "3477028019",
    "3484724297",
    "3481212092",
)


def _evaluate(target: pd.Series, listings: pd.DataFrame, guardrails: bool):
    comparable = find_comparables(
        target,
        listings,
        ComparableConfig(body_style_guardrails=guardrails),
    )
    market = estimate_market_value(comparable)
    economic = calculate_economic_opportunity(target.get("price"), market)
    eligibility = evaluate_valuation_eligibility(target)
    score = calculate_opportunity_score(economic, eligibility.status)
    return comparable, market, economic, score


def _value(value, digits: int = 0) -> str:
    return "—" if value is None or pd.isna(value) else f"{value:.{digits}f}"


def main() -> int:
    listings = load_listings_read_only()
    active = listings.loc[listings["is_active"].eq(1)].copy()
    active["eligibility"] = active.apply(
        lambda row: evaluate_valuation_eligibility(row).status,
        axis=1,
    )
    clean = active.loc[active["eligibility"].eq(ValuationStatus.ELIGIBLE)].copy()
    rows = []
    lost = []
    evaluations = {}
    for _, target in clean.iterrows():
        old = _evaluate(target, listings, False)
        new = _evaluate(target, listings, True)
        listing_id = str(target["listing_id"])
        evaluations[listing_id] = (target, old, new)
        if old[1].status == MarketValueStatus.OK and new[1].status != MarketValueStatus.OK:
            lost.append(listing_id)
        rows.append(
            {
                "listing_id": listing_id,
                "title": target.get("title"),
                "asking": target.get("price"),
                "estimate": new[1].estimated_market_price,
                "gap": new[2].market_gap_eur,
                "discount_pct": new[2].discount_percent,
                "confidence": new[1].confidence.value,
                "comparables": new[1].comparable_count,
                "score": new[3].opportunity_score,
            }
        )

    old_available = sum(
        old[1].status == MarketValueStatus.OK for _, old, _ in evaluations.values()
    )
    new_available = sum(
        new[1].status == MarketValueStatus.OK for _, _, new in evaluations.values()
    )
    print("COVERAGE")
    print(f"active clean listings: {len(clean)}")
    print(f"valuations available before: {old_available}")
    print(f"valuations available after: {new_available}")
    print(f"targets losing valuation: {len(lost)}")
    print(f"lost target IDs: {', '.join(lost) if lost else 'none'}")

    print("\nREPRESENTATIVE TARGETS")
    print("ID | BODY | OLD EST | NEW EST | OLD CONF | NEW CONF | OLD GAP | NEW GAP | OLD SCORE | NEW SCORE")
    for listing_id in REPRESENTATIVE_IDS:
        if listing_id not in evaluations:
            print(f"{listing_id} | unavailable or not clean/active")
            continue
        target, old, new = evaluations[listing_id]
        print(
            f"{listing_id} | {extract_vehicle_semantics(target.get('title')).body_style.value} | "
            f"{_value(old[1].estimated_market_price)} | {_value(new[1].estimated_market_price)} | "
            f"{old[1].confidence.value} | {new[1].confidence.value} | "
            f"{_value(old[2].market_gap_eur)} | {_value(new[2].market_gap_eur)} | "
            f"{_value(old[3].opportunity_score, 1)} | {_value(new[3].opportunity_score, 1)}"
        )
        removed = old[0].comparables.loc[
            ~old[0].comparables["listing_id"].astype(str).isin(
                new[0].comparables["listing_id"].astype(str)
            )
            & old[0].comparables["candidate_body_style"].ne(BodyStyle.UNKNOWN.value)
            & old[0].comparables["candidate_body_style"].ne(old[0].target_body_style.value)
        ]
        for candidate in removed.head(5).itertuples():
            print(
                f"  removed {candidate.listing_id} | "
                f"{candidate.candidate_body_style} | {candidate.title}"
            )

    results = pd.DataFrame(rows).dropna(subset=["score"]).sort_values(
        ["score", "discount_pct", "gap", "listing_id"],
        ascending=[False, False, False, True],
        kind="mergesort",
    )
    print("\nTOP 20 OPPORTUNITY SCORE v2 AFTER COMPARABLE ENGINE v3")
    print(results.head(20).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
