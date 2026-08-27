import unittest

import pandas as pd

from analytics.market_value import (
    MarketValueResult,
    MarketValueStatus,
    ValuationConfidence,
)
from analytics.opportunity import (
    EconomicOpportunityStatus,
    calculate_economic_opportunity,
)


def market_value(
    estimated=10_000,
    *,
    status=MarketValueStatus.OK,
    confidence=ValuationConfidence.HIGH,
) -> MarketValueResult:
    return MarketValueResult(
        target_listing_id="target",
        status=status,
        estimated_market_price=estimated,
        comparable_count=12,
        weighted_median_price=estimated,
        unweighted_median_price=estimated,
        lower_reference_price=9_000 if estimated is not None else None,
        upper_reference_price=11_000 if estimated is not None else None,
        price_dispersion=0.2 if estimated is not None else None,
        confidence=confidence,
        total_similarity_weight=7.0,
        mean_similarity_weight=0.6,
        strong_comparable_count=8,
        comparables=pd.DataFrame(),
    )


class EconomicOpportunityTests(unittest.TestCase):
    def test_positive_gap_means_below_estimated_market(self):
        result = calculate_economic_opportunity(8_000, market_value())
        self.assertEqual(result.market_gap_eur, 2_000)
        self.assertEqual(result.discount_percent, 20)

    def test_negative_gap_means_above_estimated_market(self):
        result = calculate_economic_opportunity(12_000, market_value())
        self.assertEqual(result.market_gap_eur, -2_000)
        self.assertEqual(result.discount_percent, -20)

    def test_equal_price_has_zero_gap_and_discount(self):
        result = calculate_economic_opportunity(10_000, market_value())
        self.assertEqual(result.market_gap_eur, 0)
        self.assertEqual(result.discount_percent, 0)

    def test_percentage_uses_estimated_market_as_denominator(self):
        result = calculate_economic_opportunity(9_500, market_value(11_400))
        self.assertEqual(result.market_gap_eur, 1_900)
        self.assertAlmostEqual(result.discount_percent, 1_900 / 11_400 * 100)

    def test_unavailable_valuation_propagates_without_metrics(self):
        result = calculate_economic_opportunity(
            8_000,
            market_value(
                None,
                status=MarketValueStatus.INSUFFICIENT_COMPARABLES,
                confidence=ValuationConfidence.UNAVAILABLE,
            ),
        )
        self.assertEqual(result.status, EconomicOpportunityStatus.VALUATION_UNAVAILABLE)
        self.assertEqual(result.market_value_status, MarketValueStatus.INSUFFICIENT_COMPARABLES)
        self.assertEqual(result.valuation_confidence, ValuationConfidence.UNAVAILABLE)
        self.assertIsNone(result.market_gap_eur)
        self.assertIsNone(result.discount_percent)

    def test_missing_invalid_and_suspicious_asking_prices_are_rejected(self):
        for asking in (None, 0, 499):
            with self.subTest(asking=asking):
                result = calculate_economic_opportunity(asking, market_value())
                self.assertEqual(result.status, EconomicOpportunityStatus.INVALID_ASKING_PRICE)
                self.assertIsNone(result.market_gap_eur)

    def test_non_positive_estimate_is_defensively_rejected(self):
        result = calculate_economic_opportunity(8_000, market_value(0))
        self.assertEqual(
            result.status,
            EconomicOpportunityStatus.INVALID_ESTIMATED_MARKET_PRICE,
        )
        self.assertIsNone(result.discount_percent)

    def test_success_propagates_confidence_count_and_market_status(self):
        result = calculate_economic_opportunity(
            9_000, market_value(confidence=ValuationConfidence.MEDIUM)
        )
        self.assertEqual(result.status, EconomicOpportunityStatus.OK)
        self.assertEqual(result.market_value_status, MarketValueStatus.OK)
        self.assertEqual(result.valuation_confidence, ValuationConfidence.MEDIUM)
        self.assertEqual(result.comparable_count, 12)

    def test_result_is_deterministic(self):
        first = calculate_economic_opportunity(8_000, market_value())
        second = calculate_economic_opportunity(8_000, market_value())
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
