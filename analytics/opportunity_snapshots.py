from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from analytics.comparables import (
    COMPARABLE_ENGINE_VERSION,
    find_comparables,
    prepare_comparable_universe,
)
from analytics.market_value import MarketValueStatus, estimate_market_value
from analytics.opportunity import (
    calculate_economic_opportunity,
    calculate_opportunity_score,
)
from config.valuation_vocabulary import load_valuation_vocabulary
from config.vehicle_semantics import load_vehicle_semantics


SNAPSHOT_COLUMNS = (
    "listing_id",
    "observed_at",
    "asking_price",
    "estimated_market_price",
    "market_gap_eur",
    "discount_percent",
    "opportunity_score",
    "score_version",
    "opportunity_status",
    "valuation_status",
    "valuation_confidence",
    "market_value_status",
    "comparable_count",
    "strong_comparable_count",
    "discount_component",
    "margin_component",
    "base_opportunity",
    "confidence_multiplier",
    "risk_multiplier",
    "valuation_vocabulary_version",
    "vehicle_semantics_version",
    "comparable_version",
)


def _observation_timestamp(observed_at: datetime) -> str:
    if observed_at.tzinfo is None:
        raise ValueError("Snapshot observation time must be timezone-aware")
    return observed_at.astimezone(timezone.utc).isoformat()


def build_opportunity_snapshot_records(
    listings: pd.DataFrame,
    observed_at: datetime,
) -> list[dict]:
    """Calculate one canonical snapshot for every currently scorable ACTIVE row."""
    if listings.empty:
        return []
    timestamp = _observation_timestamp(observed_at)
    source = listings.copy()
    source["listing_id"] = source["listing_id"].astype(str)
    active = source.loc[
        pd.to_numeric(source["is_active"], errors="coerce").eq(1)
    ].copy()
    if active.empty:
        return []

    universe = prepare_comparable_universe(source)
    vocabulary_version = load_valuation_vocabulary().version
    semantics_version = load_vehicle_semantics().version
    records: list[dict] = []
    for _, target in active.iterrows():
        listing_id = str(target["listing_id"])
        eligibility = universe.eligibility_by_id[listing_id]
        comparable = find_comparables(target, universe=universe)
        market_value = estimate_market_value(comparable)
        economic = calculate_economic_opportunity(target.get("price"), market_value)
        score = calculate_opportunity_score(economic, eligibility.status)
        if (
            market_value.status != MarketValueStatus.OK
            or market_value.estimated_market_price is None
            or score.opportunity_score is None
        ):
            continue
        records.append(
            {
                "listing_id": listing_id,
                "observed_at": timestamp,
                "asking_price": economic.asking_price,
                "estimated_market_price": market_value.estimated_market_price,
                "market_gap_eur": economic.market_gap_eur,
                "discount_percent": economic.discount_percent,
                "opportunity_score": score.opportunity_score,
                "score_version": score.score_version,
                "opportunity_status": score.status.value,
                "valuation_status": eligibility.status.value,
                "valuation_confidence": market_value.confidence.value,
                "market_value_status": market_value.status.value,
                "comparable_count": market_value.comparable_count,
                "strong_comparable_count": market_value.strong_comparable_count,
                "discount_component": score.discount_component,
                "margin_component": score.margin_component,
                "base_opportunity": score.base_opportunity,
                "confidence_multiplier": score.confidence_multiplier,
                "risk_multiplier": score.risk_multiplier,
                "valuation_vocabulary_version": vocabulary_version,
                "vehicle_semantics_version": semantics_version,
                "comparable_version": COMPARABLE_ENGINE_VERSION,
            }
        )
    return records
