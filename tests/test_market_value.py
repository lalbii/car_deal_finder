import unittest

import pandas as pd

from analytics.comparables import ComparableResult, ComparableStatus, find_comparables
from analytics.market_value import (
    MarketValueStatus,
    ValuationConfidence,
    estimate_market_value,
    weighted_median,
)


def comparable_result(
    prices,
    weights=None,
    status=ComparableStatus.OK,
) -> ComparableResult:
    if weights is None:
        weights = [1.0] * len(prices)
    frame = pd.DataFrame(
        {
            "listing_id": [f"c{i}" for i in range(len(prices))],
            "price": prices,
            "similarity_weight": weights,
        }
    )
    return ComparableResult("target", frame, len(frame), len(frame), status)


def listing(listing_id, price=10_000, mileage=150_000) -> dict:
    return {
        "listing_id": listing_id,
        "title": listing_id,
        "price": price,
        "mileage_km": mileage,
        "first_registration": "2016",
        "transmission": "Automatik",
        "is_active": 1,
    }


class MarketValueTests(unittest.TestCase):
    def test_weighted_median_uses_lower_value_at_exact_half_boundary(self):
        value = weighted_median(
            pd.Series([30_000, 10_000, 20_000]),
            pd.Series([0.5, 1.0, 0.5]),
        )
        self.assertEqual(value, 10_000)

    def test_weighted_median_respects_similarity_weight(self):
        value = weighted_median(
            pd.Series([10_000, 20_000, 30_000]),
            pd.Series([0.1, 0.2, 0.7]),
        )
        self.assertEqual(value, 30_000)

    def test_outlier_does_not_collapse_estimate(self):
        result = estimate_market_value(
            comparable_result([40_000, 41_000, 39_000, 42_000, 15_000])
        )
        self.assertEqual(result.estimated_market_price, 40_000)
        self.assertIn(15_000, result.comparables["price"].tolist())

    def test_target_price_does_not_influence_estimate(self):
        candidates = [listing(f"c{i}", 10_000 + i * 1_000, 140_000 + i * 2_000) for i in range(6)]
        low_target = listing("target", price=8_000)
        high_target = listing("target", price=40_000)
        low = estimate_market_value(find_comparables(low_target, pd.DataFrame([low_target, *candidates])))
        high = estimate_market_value(find_comparables(high_target, pd.DataFrame([high_target, *candidates])))
        self.assertEqual(low.estimated_market_price, high.estimated_market_price)

    def test_insufficient_comparables_produces_no_estimate(self):
        result = estimate_market_value(
            comparable_result([10_000, 11_000], status=ComparableStatus.INSUFFICIENT_COMPARABLES)
        )
        self.assertEqual(result.status, MarketValueStatus.INSUFFICIENT_COMPARABLES)
        self.assertIsNone(result.estimated_market_price)
        self.assertEqual(result.confidence, ValuationConfidence.UNAVAILABLE)

    def test_invalid_prices_are_excluded_and_can_prevent_valuation(self):
        result = estimate_market_value(
            comparable_result([10_000, 11_000, 12_000, 13_000, 0])
        )
        self.assertEqual(result.status, MarketValueStatus.INVALID_COMPARABLE_PRICES)
        self.assertEqual(result.comparable_count, 4)
        self.assertNotIn(0, result.comparables["price"].tolist())
        self.assertIsNone(result.estimated_market_price)

    def test_reference_range_uses_linear_quartiles(self):
        result = estimate_market_value(
            comparable_result([10_000, 11_000, 12_000, 13_000, 14_000])
        )
        self.assertEqual(result.lower_reference_price, 11_000)
        self.assertEqual(result.upper_reference_price, 13_000)
        self.assertAlmostEqual(result.price_dispersion, 2_000 / 12_000)

    def test_confidence_high_medium_low_and_unavailable(self):
        high = estimate_market_value(
            comparable_result(
                [10_000 + i * 100 for i in range(10)], [0.6] * 10
            )
        )
        medium = estimate_market_value(
            comparable_result([10_000, 10_500, 11_000, 11_500, 12_000], [0.5] * 5)
        )
        low = estimate_market_value(
            comparable_result([1_000, 1_000, 1_000, 5_000, 5_000], [0.5] * 5)
        )
        unavailable = estimate_market_value(
            comparable_result([], status=ComparableStatus.INSUFFICIENT_COMPARABLES)
        )
        self.assertEqual(high.confidence, ValuationConfidence.HIGH)
        self.assertEqual(medium.confidence, ValuationConfidence.MEDIUM)
        self.assertEqual(low.confidence, ValuationConfidence.LOW)
        self.assertEqual(unavailable.confidence, ValuationConfidence.UNAVAILABLE)

    def test_determinism(self):
        first = estimate_market_value(
            comparable_result([12_000, 10_000, 14_000, 11_000, 13_000], [0.6] * 5)
        )
        second = estimate_market_value(
            comparable_result([13_000, 11_000, 14_000, 10_000, 12_000], [0.6] * 5)
        )
        self.assertEqual(first.estimated_market_price, second.estimated_market_price)
        self.assertEqual(first.confidence, second.confidence)
        self.assertEqual(first.price_dispersion, second.price_dispersion)


if __name__ == "__main__":
    unittest.main()
