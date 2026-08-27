from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from analytics.market_value import (
    MarketValueResult,
    MarketValueStatus,
    ValuationConfidence,
)
from validation.listing_quality import DataQuality, classify_price


class EconomicOpportunityStatus(str, Enum):
    OK = "OK"
    VALUATION_UNAVAILABLE = "VALUATION_UNAVAILABLE"
    INVALID_ASKING_PRICE = "INVALID_ASKING_PRICE"
    INVALID_ESTIMATED_MARKET_PRICE = "INVALID_ESTIMATED_MARKET_PRICE"


@dataclass(frozen=True)
class EconomicOpportunityResult:
    target_listing_id: str
    status: EconomicOpportunityStatus
    market_value_status: MarketValueStatus
    asking_price: float | None
    estimated_market_price: float | None
    market_gap_eur: float | None
    discount_percent: float | None
    valuation_confidence: ValuationConfidence
    comparable_count: int


def calculate_economic_opportunity(
    asking_price: int | float | None,
    market_value: MarketValueResult,
) -> EconomicOpportunityResult:
    """Calculate a gap to observed asking-market value; positive means below it."""
    if market_value.status != MarketValueStatus.OK or market_value.estimated_market_price is None:
        return EconomicOpportunityResult(
            market_value.target_listing_id,
            EconomicOpportunityStatus.VALUATION_UNAVAILABLE,
            market_value.status,
            float(asking_price) if asking_price is not None else None,
            market_value.estimated_market_price,
            None,
            None,
            market_value.confidence,
            market_value.comparable_count,
        )

    if classify_price(asking_price) != DataQuality.VALID:
        return EconomicOpportunityResult(
            market_value.target_listing_id,
            EconomicOpportunityStatus.INVALID_ASKING_PRICE,
            market_value.status,
            None if asking_price is None else float(asking_price),
            market_value.estimated_market_price,
            None,
            None,
            market_value.confidence,
            market_value.comparable_count,
        )

    estimated = float(market_value.estimated_market_price)
    if not math.isfinite(estimated) or estimated <= 0:
        return EconomicOpportunityResult(
            market_value.target_listing_id,
            EconomicOpportunityStatus.INVALID_ESTIMATED_MARKET_PRICE,
            market_value.status,
            float(asking_price),
            estimated,
            None,
            None,
            market_value.confidence,
            market_value.comparable_count,
        )

    asking = float(asking_price)
    gap = estimated - asking
    return EconomicOpportunityResult(
        market_value.target_listing_id,
        EconomicOpportunityStatus.OK,
        market_value.status,
        asking,
        estimated,
        gap,
        gap / estimated * 100.0,
        market_value.confidence,
        market_value.comparable_count,
    )
