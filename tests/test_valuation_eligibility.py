import unittest

from analytics.valuation_eligibility import (
    ValuationReason,
    ValuationStatus,
    evaluate_valuation_eligibility,
)


def listing(**overrides) -> dict:
    value = {
        "title": "BMW 320d Touring",
        "description": "Gepflegtes Fahrzeug",
        "price": 12_000,
        "mileage_km": 150_000,
        "first_registration": "2016",
        "transmission": "Automatik",
    }
    value.update(overrides)
    return value


class ValuationEligibilityTests(unittest.TestCase):
    def assert_reason(self, reason, status, **overrides):
        result = evaluate_valuation_eligibility(listing(**overrides))
        self.assertEqual(result.status, status)
        self.assertIn(reason, result.reasons)

    def test_clean_listing_is_eligible(self):
        result = evaluate_valuation_eligibility(listing())
        self.assertEqual(result.status, ValuationStatus.ELIGIBLE)
        self.assertEqual(result.reasons, ())

    def test_semantic_hard_exclusions(self):
        cases = (
            ("BMW 320d – LEASINGÜBERNAHME", ValuationReason.LEASING_TAKEOVER),
            ("BMW 320d Teileträger", ValuationReason.PARTS_ONLY),
            ("BMW 320d Motorschaden", ValuationReason.SEVERE_MECHANICAL_DAMAGE),
            ("BMW 320d Bastlerfahrzeug", ValuationReason.PROJECT_OR_SCRAP),
        )
        for title, reason in cases:
            with self.subTest(reason=reason):
                self.assert_reason(reason, ValuationStatus.INELIGIBLE, title=title)

    def test_kettenschaden_regression_is_severe_mechanical_damage(self):
        self.assert_reason(
            ValuationReason.SEVERE_MECHANICAL_DAMAGE,
            ValuationStatus.INELIGIBLE,
            title="BMW E92 320d M-Paket Shadow Line | TÜV 05/2028 | Kettenschaden",
        )

    def test_new_severe_damage_terms_are_case_and_spacing_normalized(self):
        for title in (
            "BMW 320d KETTENSCHADEN",
            "BMW 320d Steuerkettenschaden",
            "BMW 320d Steuerkette gerissen",
            "BMW 320d Steuerkette   gerissen",
        ):
            with self.subTest(title=title):
                self.assert_reason(
                    ValuationReason.SEVERE_MECHANICAL_DAMAGE,
                    ValuationStatus.INELIGIBLE,
                    title=title,
                )

    def test_placeholder_price_is_hard_exclusion(self):
        self.assert_reason(
            ValuationReason.PLACEHOLDER_PRICE,
            ValuationStatus.INELIGIBLE,
            price=1,
        )

    def test_soft_risks_remain_distinct(self):
        cases = (
            ({"title": "BMW 320d Unfallfahrzeug"}, ValuationReason.ACCIDENT),
            ({"title": "BMW 320d ohne TÜV"}, ValuationReason.NO_TUV),
            ({"mileage_km": 450_000}, ValuationReason.EXTREME_MILEAGE),
            ({"price": 900}, ValuationReason.SUSPICIOUSLY_LOW_PRICE),
        )
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                self.assert_reason(reason, ValuationStatus.ELIGIBLE_WITH_RISK, **overrides)

    def test_missing_core_data_has_detailed_diagnostics(self):
        result = evaluate_valuation_eligibility(
            listing(price=None, first_registration="invalid", transmission="unknown")
        )
        self.assertEqual(result.status, ValuationStatus.INELIGIBLE)
        self.assertIn(ValuationReason.MISSING_CORE_DATA, result.reasons)
        self.assertEqual(
            result.core_data_diagnostics,
            ("price:MISSING", "first_registration:INVALID", "transmission:UNKNOWN"),
        )

    def test_negated_damage_and_safe_accident_language_are_not_adverse(self):
        for title in (
            "BMW 320d kein Motorschaden",
            "BMW 320d ohne Motorschaden",
            "BMW 320d kein Kettenschaden",
            "BMW 320d ohne Kettenschaden",
            "BMW 320d kein Steuerkettenschaden",
            "BMW 320d ohne Steuerkettenschaden",
            "BMW 320d kein Motor defekt",
            "BMW 320d kein Getriebe defekt",
            "BMW 320d kein Unfall",
            "BMW 320d unfallfrei",
        ):
            with self.subTest(title=title):
                result = evaluate_valuation_eligibility(listing(title=title))
                self.assertEqual(result.status, ValuationStatus.ELIGIBLE)
                self.assertEqual(result.reasons, ())

    def test_configured_no_tuv_phrases_remain_soft_risks(self):
        for title in ("BMW 320d kein TÜV", "BMW 320d ohne TÜV"):
            with self.subTest(title=title):
                result = evaluate_valuation_eligibility(listing(title=title))
                self.assertEqual(result.status, ValuationStatus.ELIGIBLE_WITH_RISK)
                self.assertIn(ValuationReason.NO_TUV, result.reasons)


if __name__ == "__main__":
    unittest.main()
