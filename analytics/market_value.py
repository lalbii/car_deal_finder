from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from analytics.comparables import ComparableResult, ComparableStatus
from validation.listing_quality import DataQuality, classify_price


class MarketValueStatus(str, Enum):
    OK = "OK"
    INSUFFICIENT_COMPARABLES = "INSUFFICIENT_COMPARABLES"
    TARGET_INELIGIBLE = "TARGET_INELIGIBLE"
    TARGET_MISSING_CORE_DATA = "TARGET_MISSING_CORE_DATA"
    INVALID_COMPARABLE_PRICES = "INVALID_COMPARABLE_PRICES"


class ValuationConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class MarketValueConfig:
    min_comparables: int = 5
    strong_weight_threshold: float = 0.5
    high_min_comparables: int = 10
    high_min_strong_comparables: int = 3
    high_min_total_similarity_weight: float = 5.0
    high_max_dispersion: float = 0.20
    medium_min_strong_comparables: int = 1
    medium_min_total_similarity_weight: float = 2.0
    medium_max_dispersion: float = 0.35

    def __post_init__(self) -> None:
        if self.min_comparables < 1 or self.high_min_comparables < self.min_comparables:
            raise ValueError("Comparable count thresholds are inconsistent")
        if not 0 < self.strong_weight_threshold <= 1:
            raise ValueError("Strong comparable weight threshold must be in (0, 1]")
        if self.high_min_strong_comparables < 0 or self.medium_min_strong_comparables < 0:
            raise ValueError("Strong comparable count thresholds must be non-negative")
        if self.high_min_total_similarity_weight <= 0 or self.medium_min_total_similarity_weight <= 0:
            raise ValueError("Similarity coverage thresholds must be positive")
        if self.high_max_dispersion < 0 or self.medium_max_dispersion < self.high_max_dispersion:
            raise ValueError("Dispersion thresholds are inconsistent")


@dataclass(frozen=True)
class MarketValueResult:
    target_listing_id: str
    status: MarketValueStatus
    estimated_market_price: float | None
    comparable_count: int
    weighted_median_price: float | None
    unweighted_median_price: float | None
    lower_reference_price: float | None
    upper_reference_price: float | None
    price_dispersion: float | None
    confidence: ValuationConfidence
    total_similarity_weight: float
    mean_similarity_weight: float | None
    strong_comparable_count: int
    comparables: pd.DataFrame


def weighted_median(prices: pd.Series, weights: pd.Series) -> float:
    """Return the first ascending price whose cumulative weight reaches 50%."""
    values = pd.DataFrame(
        {
            "price": pd.to_numeric(prices, errors="coerce"),
            "weight": pd.to_numeric(weights, errors="coerce"),
        }
    ).sort_values("price", kind="mergesort")
    total_weight = float(values["weight"].sum())
    if values.empty or total_weight <= 0:
        raise ValueError("Weighted median requires values with positive total weight")
    cutoff = total_weight / 2.0
    return float(values.loc[values["weight"].cumsum().ge(cutoff), "price"].iloc[0])


def _unavailable(
    result: ComparableResult,
    status: MarketValueStatus,
    comparables: pd.DataFrame | None = None,
) -> MarketValueResult:
    return MarketValueResult(
        target_listing_id=result.target_listing_id,
        status=status,
        estimated_market_price=None,
        comparable_count=0 if comparables is None else len(comparables),
        weighted_median_price=None,
        unweighted_median_price=None,
        lower_reference_price=None,
        upper_reference_price=None,
        price_dispersion=None,
        confidence=ValuationConfidence.UNAVAILABLE,
        total_similarity_weight=0.0,
        mean_similarity_weight=None,
        strong_comparable_count=0,
        comparables=result.comparables.copy() if comparables is None else comparables,
    )


def _confidence(
    comparable_count: int,
    strong_count: int,
    total_weight: float,
    dispersion: float,
    config: MarketValueConfig,
) -> ValuationConfidence:
    if (
        comparable_count >= config.high_min_comparables
        and strong_count >= config.high_min_strong_comparables
        and total_weight >= config.high_min_total_similarity_weight
        and dispersion <= config.high_max_dispersion
    ):
        return ValuationConfidence.HIGH
    if (
        strong_count >= config.medium_min_strong_comparables
        and total_weight >= config.medium_min_total_similarity_weight
        and dispersion <= config.medium_max_dispersion
    ):
        return ValuationConfidence.MEDIUM
    return ValuationConfidence.LOW


def estimate_market_value(
    comparable_result: ComparableResult,
    config: MarketValueConfig | None = None,
) -> MarketValueResult:
    """Estimate current observed asking-market value from selected comparables."""
    cfg = config or MarketValueConfig()
    status_mapping = {
        ComparableStatus.TARGET_INELIGIBLE: MarketValueStatus.TARGET_INELIGIBLE,
        ComparableStatus.TARGET_MISSING_CORE_DATA: MarketValueStatus.TARGET_MISSING_CORE_DATA,
    }
    if comparable_result.status in status_mapping:
        return _unavailable(comparable_result, status_mapping[comparable_result.status])

    source = comparable_result.comparables.copy()
    if "price" not in source or "similarity_weight" not in source:
        return _unavailable(comparable_result, MarketValueStatus.INVALID_COMPARABLE_PRICES)
    source["price"] = pd.to_numeric(source["price"], errors="coerce")
    source["similarity_weight"] = pd.to_numeric(
        source["similarity_weight"], errors="coerce"
    )
    valid_price = source["price"].apply(classify_price).eq(DataQuality.VALID)
    valid_weight = source["similarity_weight"].gt(0) & source["similarity_weight"].notna()
    comparables = source.loc[valid_price & valid_weight].copy().reset_index(drop=True)

    if comparable_result.status == ComparableStatus.INSUFFICIENT_COMPARABLES:
        return _unavailable(
            comparable_result, MarketValueStatus.INSUFFICIENT_COMPARABLES, comparables
        )
    if len(comparables) < cfg.min_comparables:
        return _unavailable(
            comparable_result, MarketValueStatus.INVALID_COMPARABLE_PRICES, comparables
        )

    prices = comparables["price"]
    weights = comparables["similarity_weight"]
    weighted = weighted_median(prices, weights)
    median = float(prices.median())
    q1 = float(prices.quantile(0.25, interpolation="linear"))
    q3 = float(prices.quantile(0.75, interpolation="linear"))
    dispersion = float((q3 - q1) / median)
    total_weight = float(weights.sum())
    mean_weight = float(weights.mean())
    strong_count = int(weights.ge(cfg.strong_weight_threshold).sum())

    return MarketValueResult(
        target_listing_id=comparable_result.target_listing_id,
        status=MarketValueStatus.OK,
        estimated_market_price=weighted,
        comparable_count=len(comparables),
        weighted_median_price=weighted,
        unweighted_median_price=median,
        lower_reference_price=q1,
        upper_reference_price=q3,
        price_dispersion=dispersion,
        confidence=_confidence(
            len(comparables), strong_count, total_weight, dispersion, cfg
        ),
        total_similarity_weight=total_weight,
        mean_similarity_weight=mean_weight,
        strong_comparable_count=strong_count,
        comparables=comparables,
    )
