from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from analytics.market_value import (
    MarketValueResult,
    MarketValueStatus,
    ValuationConfidence,
)
from analytics.valuation_eligibility import ValuationStatus
from validation.listing_quality import DataQuality, classify_price


OPPORTUNITY_SCORE_VERSION = "2.1"


class EconomicOpportunityStatus(str, Enum):
    OK = "OK"
    VALUATION_UNAVAILABLE = "VALUATION_UNAVAILABLE"
    INVALID_ASKING_PRICE = "INVALID_ASKING_PRICE"
    INVALID_ESTIMATED_MARKET_PRICE = "INVALID_ESTIMATED_MARKET_PRICE"


class OpportunityScoreStatus(str, Enum):
    OK = "OK"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    RISK_ADJUSTED = "RISK_ADJUSTED"
    UNAVAILABLE = "UNAVAILABLE"
    INELIGIBLE = "INELIGIBLE"


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


@dataclass(frozen=True)
class OpportunityScoreResult:
    target_listing_id: str
    score_version: str
    status: OpportunityScoreStatus
    opportunity_score: float | None
    discount_percent: float | None
    market_gap_eur: float | None
    discount_component: float | None
    margin_component: float | None
    base_opportunity: float | None
    confidence_multiplier: float | None
    risk_multiplier: float | None
    valuation_confidence: ValuationConfidence
    valuation_status: ValuationStatus


_DISCOUNT_POINTS = (
    (-15.0, 0.0),
    (0.0, 40.0),
    (10.0, 58.0),
    (20.0, 72.0),
    (30.0, 84.0),
    (45.0, 94.0),
    (60.0, 100.0),
)
_MARGIN_POINTS = (
    (0.0, 0.0),
    (500.0, 20.0),
    (1_000.0, 35.0),
    (2_000.0, 55.0),
    (3_000.0, 68.0),
    (5_000.0, 82.0),
    (8_000.0, 92.0),
    (12_000.0, 100.0),
)
_CONFIDENCE_MULTIPLIERS = {
    ValuationConfidence.HIGH: 1.00,
    ValuationConfidence.MEDIUM: 0.85,
    ValuationConfidence.LOW: 0.65,
}
_RISK_MULTIPLIERS = {
    ValuationStatus.ELIGIBLE: 1.00,
    ValuationStatus.ELIGIBLE_WITH_RISK: 0.60,
}


def _piecewise_linear(value: float, points: tuple[tuple[float, float], ...]) -> float:
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if value <= right_x:
            fraction = (value - left_x) / (right_x - left_x)
            return left_y + fraction * (right_y - left_y)
    raise AssertionError("Piecewise interpolation failed")


def discount_component(discount_percent: float) -> float:
    """Map discount percentage to a bounded 0..100 economic component."""
    return _piecewise_linear(float(discount_percent), _DISCOUNT_POINTS)


def margin_component(market_gap_eur: float) -> float:
    """Map the non-profit market gap to a bounded 0..100 component."""
    return _piecewise_linear(float(market_gap_eur), _MARGIN_POINTS)


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


def calculate_opportunity_score(
    economic: EconomicOpportunityResult,
    valuation_status: ValuationStatus,
) -> OpportunityScoreResult:
    """Return an explainable 0..100 sourcing heuristic, not probability or profit."""
    common = {
        "target_listing_id": economic.target_listing_id,
        "score_version": OPPORTUNITY_SCORE_VERSION,
        "discount_percent": economic.discount_percent,
        "market_gap_eur": economic.market_gap_eur,
        "valuation_confidence": economic.valuation_confidence,
        "valuation_status": valuation_status,
    }
    if valuation_status == ValuationStatus.INELIGIBLE:
        return OpportunityScoreResult(
            status=OpportunityScoreStatus.INELIGIBLE,
            opportunity_score=None,
            discount_component=None,
            margin_component=None,
            base_opportunity=None,
            confidence_multiplier=None,
            risk_multiplier=None,
            **common,
        )
    confidence_multiplier = _CONFIDENCE_MULTIPLIERS.get(economic.valuation_confidence)
    if (
        economic.status != EconomicOpportunityStatus.OK
        or economic.discount_percent is None
        or economic.market_gap_eur is None
        or confidence_multiplier is None
    ):
        return OpportunityScoreResult(
            status=OpportunityScoreStatus.UNAVAILABLE,
            opportunity_score=None,
            discount_component=None,
            margin_component=None,
            base_opportunity=None,
            confidence_multiplier=confidence_multiplier,
            risk_multiplier=_RISK_MULTIPLIERS.get(valuation_status),
            **common,
        )

    risk_multiplier = _RISK_MULTIPLIERS[valuation_status]
    discount_score = discount_component(economic.discount_percent)
    margin_score = margin_component(economic.market_gap_eur)
    base = 0.70 * discount_score + 0.30 * margin_score
    score = max(0.0, min(100.0, base * confidence_multiplier * risk_multiplier))
    if valuation_status == ValuationStatus.ELIGIBLE_WITH_RISK:
        status = OpportunityScoreStatus.RISK_ADJUSTED
    elif economic.valuation_confidence == ValuationConfidence.LOW:
        status = OpportunityScoreStatus.LOW_CONFIDENCE
    else:
        status = OpportunityScoreStatus.OK
    return OpportunityScoreResult(
        status=status,
        opportunity_score=score,
        discount_component=discount_score,
        margin_component=margin_score,
        base_opportunity=base,
        confidence_multiplier=confidence_multiplier,
        risk_multiplier=risk_multiplier,
        **common,
    )
