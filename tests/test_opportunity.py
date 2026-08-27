import unittest

import pandas as pd

from analytics.market_value import (
    MarketValueResult,
    MarketValueStatus,
    ValuationConfidence,
)
from analytics.opportunity import (
    EconomicOpportunityStatus,
    OpportunityScoreStatus,
    calculate_economic_opportunity,
    calculate_opportunity_score,
    discount_component,
    margin_component,
)
from analytics.valuation_eligibility import ValuationStatus


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


def score(
    asking,
    estimated,
    *,
    confidence=ValuationConfidence.HIGH,
    eligibility=ValuationStatus.ELIGIBLE,
):
    economic = calculate_economic_opportunity(
        asking, market_value(estimated, confidence=confidence)
    )
    return calculate_opportunity_score(economic, eligibility)


class OpportunityScoreV2Tests(unittest.TestCase):
    def test_discount_component_boundaries_and_saturation(self):
        expected = {
            -20: 0,
            -15: 0,
            0: 40,
            10: 60,
            20: 80,
            30: 100,
            70: 100,
        }
        for value, component in expected.items():
            with self.subTest(value=value):
                self.assertEqual(discount_component(value), component)

    def test_margin_component_boundaries_and_saturation(self):
        expected = {
            -1_000: 0,
            0: 0,
            500: 30,
            1_000: 50,
            2_000: 80,
            3_000: 100,
            10_000: 100,
        }
        for value, component in expected.items():
            with self.subTest(value=value):
                self.assertEqual(margin_component(value), component)

    def test_same_discount_larger_euro_gap_scores_higher(self):
        smaller = score(4_000, 5_000)
        larger = score(12_000, 15_000)
        self.assertGreater(larger.opportunity_score, smaller.opportunity_score)

    def test_same_gap_larger_discount_scores_higher(self):
        larger_discount = score(4_000, 5_000)
        smaller_discount = score(10_000, 11_000)
        self.assertGreater(
            larger_discount.opportunity_score, smaller_discount.opportunity_score
        )

    def test_confidence_ordering(self):
        high = score(8_000, 10_000, confidence=ValuationConfidence.HIGH)
        medium = score(8_000, 10_000, confidence=ValuationConfidence.MEDIUM)
        low = score(8_000, 10_000, confidence=ValuationConfidence.LOW)
        self.assertGreater(high.opportunity_score, medium.opportunity_score)
        self.assertGreater(medium.opportunity_score, low.opportunity_score)
        self.assertEqual(low.status, OpportunityScoreStatus.LOW_CONFIDENCE)

    def test_overpriced_vehicle_scores_low(self):
        result = score(12_000, 10_000)
        self.assertLessEqual(result.opportunity_score, 10)

    def test_neutral_vehicle_is_weak_not_strong(self):
        result = score(10_000, 10_000)
        self.assertEqual(result.opportunity_score, 28)
        self.assertLess(result.opportunity_score, 40)

    def test_extreme_discount_saturates(self):
        saturated = score(7_000, 10_000)
        extreme = score(3_000, 10_000)
        self.assertEqual(saturated.opportunity_score, 100)
        self.assertEqual(extreme.opportunity_score, 100)

    def test_unavailable_valuation_has_no_score(self):
        economic = calculate_economic_opportunity(
            8_000,
            market_value(
                None,
                status=MarketValueStatus.INSUFFICIENT_COMPARABLES,
                confidence=ValuationConfidence.UNAVAILABLE,
            ),
        )
        result = calculate_opportunity_score(economic, ValuationStatus.ELIGIBLE)
        self.assertEqual(result.status, OpportunityScoreStatus.UNAVAILABLE)
        self.assertIsNone(result.opportunity_score)

    def test_ineligible_target_has_no_score(self):
        result = score(8_000, 10_000, eligibility=ValuationStatus.INELIGIBLE)
        self.assertEqual(result.status, OpportunityScoreStatus.INELIGIBLE)
        self.assertIsNone(result.opportunity_score)

    def test_risk_target_is_explicitly_penalized(self):
        clean = score(8_000, 10_000)
        risk = score(
            8_000, 10_000, eligibility=ValuationStatus.ELIGIBLE_WITH_RISK
        )
        self.assertEqual(risk.status, OpportunityScoreStatus.RISK_ADJUSTED)
        self.assertAlmostEqual(risk.opportunity_score, clean.opportunity_score * 0.60)

    def test_score_is_deterministic_clamped_and_components_reconcile(self):
        first = score(8_000, 10_000, confidence=ValuationConfidence.MEDIUM)
        second = score(8_000, 10_000, confidence=ValuationConfidence.MEDIUM)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first.opportunity_score, 0)
        self.assertLessEqual(first.opportunity_score, 100)
        expected_base = 0.70 * first.discount_component + 0.30 * first.margin_component
        self.assertAlmostEqual(first.base_opportunity, expected_base)
        self.assertAlmostEqual(
            first.opportunity_score,
            first.base_opportunity
            * first.confidence_multiplier
            * first.risk_multiplier,
        )


if __name__ == "__main__":
    unittest.main()
