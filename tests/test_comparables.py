import unittest
from unittest.mock import patch

import pandas as pd

from analytics.comparables import (
    ComparableConfig,
    ComparableStatus,
    body_style_factor,
    find_comparables,
    prepare_comparable_universe,
)
from analytics.market_value import estimate_market_value
from analytics.opportunity import (
    calculate_economic_opportunity,
    calculate_opportunity_score,
)
from analytics.valuation_eligibility import evaluate_valuation_eligibility
from analytics.vehicle_semantics import BodyStyle, extract_vehicle_semantics
from analytics.valuation_eligibility import ValuationStatus


def row(
    listing_id: str,
    *,
    year: int = 2016,
    mileage: int = 150_000,
    transmission: str = "Automatik",
    price: int = 10_000,
    active: int = 1,
    status: ValuationStatus | None = None,
    title: str | None = None,
) -> dict:
    value = {
        "listing_id": listing_id,
        "title": title or listing_id,
        "price": price,
        "mileage_km": mileage,
        "first_registration": str(year),
        "transmission": transmission,
        "location": "NRW",
        "is_active": active,
    }
    if status is not None:
        value["valuation_status"] = status.value
    return value


class ComparableTests(unittest.TestCase):
    def select(self, candidates, **config):
        target = row("target")
        frame = pd.DataFrame([target, *candidates])
        return find_comparables(target, frame, ComparableConfig(min_comparables=1, **config))

    def test_same_transmission_and_target_exclusion(self):
        result = self.select([row("auto"), row("manual", transmission="Schaltgetriebe")])
        self.assertEqual(result.comparables["listing_id"].tolist(), ["auto"])
        self.assertNotIn("target", result.comparables["listing_id"].tolist())

    def test_year_threshold_is_inclusive(self):
        result = self.select([row(str(year), year=year) for year in (2012, 2013, 2019, 2020)])
        self.assertEqual(set(result.comparables["listing_id"]), {"2013", "2019"})

    def test_mileage_threshold_is_inclusive(self):
        result = self.select([row(str(km), mileage=km) for km in (49_999, 50_000, 250_000, 250_001)])
        self.assertEqual(set(result.comparables["listing_id"]), {"50000", "250000"})

    def test_weight_ordering(self):
        result = self.select([
            row("far", mileage=230_000),
            row("near", mileage=160_000),
            row("exact", mileage=150_000),
        ])
        self.assertEqual(result.comparables["listing_id"].tolist(), ["exact", "near", "far"])
        self.assertTrue((result.comparables["similarity_weight"] > 0).all())

    def test_known_body_style_matches_are_allowed_and_mismatches_excluded(self):
        target = row("target", title="BMW 320d Touring")
        candidates = [
            row("wagon", title="BMW 320d Kombi"),
            row("sedan", title="BMW 320d Limousine"),
            row("coupe", title="BMW 320d Coupé"),
            row("convertible", title="BMW 320d Cabrio"),
        ]
        result = find_comparables(
            target,
            pd.DataFrame([target, *candidates]),
            ComparableConfig(min_comparables=1),
        )
        self.assertEqual(result.comparables["listing_id"].tolist(), ["wagon"])
        self.assertEqual(result.known_body_style_mismatch_count, 3)
        self.assertEqual(result.same_body_style_count, 1)
        self.assertEqual(result.comparables.iloc[0]["body_style_factor"], 1.0)

    def test_unknown_body_styles_remain_usable_with_explicit_penalties(self):
        known_target = row("known-target", title="BMW 320d Touring")
        unknown_target = row("unknown-target", title="BMW 320d Automatik")
        known_candidate = row("known", title="BMW 320d Kombi")
        unknown_candidate = row("unknown", title="BMW 320d Automatik")

        known_result = find_comparables(
            known_target,
            pd.DataFrame([known_target, unknown_candidate]),
            ComparableConfig(min_comparables=1),
        )
        unknown_known_result = find_comparables(
            unknown_target,
            pd.DataFrame([unknown_target, known_candidate]),
            ComparableConfig(min_comparables=1),
        )
        unknown_result = find_comparables(
            unknown_target,
            pd.DataFrame([unknown_target, unknown_candidate]),
            ComparableConfig(min_comparables=1),
        )
        self.assertEqual(known_result.comparables.iloc[0]["body_style_factor"], 0.75)
        self.assertEqual(unknown_known_result.comparables.iloc[0]["body_style_factor"], 0.75)
        self.assertEqual(unknown_result.comparables.iloc[0]["body_style_factor"], 0.65)

    def test_body_style_factor_is_deterministic(self):
        cases = (
            (BodyStyle.WAGON, BodyStyle.WAGON, 1.0),
            (BodyStyle.WAGON, BodyStyle.UNKNOWN, 0.75),
            (BodyStyle.UNKNOWN, BodyStyle.WAGON, 0.75),
            (BodyStyle.UNKNOWN, BodyStyle.UNKNOWN, 0.65),
            (BodyStyle.WAGON, BodyStyle.SEDAN, 0.0),
        )
        for target, candidate, expected in cases:
            with self.subTest(target=target, candidate=candidate):
                self.assertEqual(body_style_factor(target, candidate), expected)
                self.assertEqual(body_style_factor(target, candidate), expected)

    def test_drivetrain_does_not_affect_selection_or_weight(self):
        target = row("target", title="BMW 320d Touring xDrive")
        candidates = [
            row("awd", title="BMW 320d Touring quattro"),
            row("unknown", title="BMW 320d Touring"),
            row("rwd", title="BMW 320d Touring Heckantrieb"),
        ]
        result = find_comparables(
            target,
            pd.DataFrame([target, *candidates]),
            ComparableConfig(min_comparables=1),
        )
        self.assertEqual(result.comparables["listing_id"].tolist(), ["awd", "rwd", "unknown"])
        self.assertEqual(result.comparables["similarity_weight"].nunique(), 1)

    def test_semantic_hard_exclusions_and_soft_risk_are_excluded(self):
        result = self.select([
            row("clean"),
            row(
                "leasing",
                title="BMW 320d Touring M Sport – LEASINGÜBERNAHME",
                status=ValuationStatus.ELIGIBLE,
            ),
            row("parts", title="BMW 320d Teileträger"),
            row("damage", title="BMW 320d Motorschaden"),
            row("placeholder", price=1),
            row(
                "accident",
                title="BMW 320d Unfallfahrzeug",
                status=ValuationStatus.ELIGIBLE,
            ),
            row("inactive", active=0),
        ])
        self.assertEqual(result.comparables["listing_id"].tolist(), ["clean"])

    def test_derived_suspicious_candidate_is_excluded(self):
        result = self.select([row("clean"), row("risk", price=499)])
        self.assertEqual(result.comparables["listing_id"].tolist(), ["clean"])

    def test_insufficient_comparables_returns_available_rows(self):
        target = row("target")
        result = find_comparables(target, pd.DataFrame([target, row("only")]))
        self.assertEqual(result.status, ComparableStatus.INSUFFICIENT_COMPARABLES)
        self.assertEqual(result.comparable_count, 1)

    def test_known_mismatch_can_leave_an_empty_insufficient_result(self):
        target = row("target", title="BMW 320d Touring")
        sedan = row("sedan", title="BMW 320d Limousine")
        result = find_comparables(target, pd.DataFrame([target, sedan]))
        self.assertEqual(result.status, ComparableStatus.INSUFFICIENT_COMPARABLES)
        self.assertEqual(result.comparable_count, 0)
        self.assertEqual(result.known_body_style_mismatch_count, 1)

    def test_target_statuses_are_explicit(self):
        frame = pd.DataFrame([row("other")])
        missing = find_comparables(row("target", transmission="unknown"), frame)
        missing_price = find_comparables(row("target", price=None), frame)
        risk = find_comparables(row("target", title="BMW 320d Unfallfahrzeug"), frame)
        self.assertEqual(missing.status, ComparableStatus.TARGET_MISSING_CORE_DATA)
        self.assertEqual(missing_price.status, ComparableStatus.TARGET_MISSING_CORE_DATA)
        self.assertEqual(risk.status, ComparableStatus.TARGET_INELIGIBLE)

    def test_order_is_deterministic_and_limited(self):
        candidates = [row("c"), row("a"), row("b")]
        first = self.select(candidates, target_comparables=2)
        second = self.select(list(reversed(candidates)), target_comparables=2)
        self.assertEqual(first.candidate_count, 3)
        self.assertEqual(first.comparables["listing_id"].tolist(), ["a", "b"])
        self.assertEqual(first.comparables["listing_id"].tolist(), second.comparables["listing_id"].tolist())

    def test_prepared_universe_is_exactly_equivalent_to_legacy_path(self):
        records = [
            row("target", title="BMW 320d Touring", price=8_000),
            row("exact", title="BMW 320d Kombi", price=10_000),
            row("near", title="BMW 320d Touring", mileage=165_000, price=10_500),
            row("older", title="BMW 320d Touring", year=2014, mileage=180_000, price=9_500),
            row("unknown-body", title="BMW 320d Automatik", price=9_800),
            row("sedan", title="BMW 320d Limousine", price=9_000),
            row("manual", title="BMW 320d Touring", transmission="Schaltgetriebe"),
            row("risk", title="BMW 320d Unfallfahrzeug"),
            row("inactive", title="BMW 320d Touring", active=0),
        ]
        frame = pd.DataFrame(records)
        target = frame.iloc[0]
        config = ComparableConfig(min_comparables=1)
        legacy = find_comparables(target, frame, config)
        prepared = find_comparables(
            target,
            config=config,
            universe=prepare_comparable_universe(frame),
        )

        scalar_fields = (
            "target_listing_id", "active_count", "eligible_count", "candidate_count",
            "comparable_count", "status", "transmission_match_count", "year_match_count",
            "mileage_match_count", "risk_count", "ineligible_count", "target_body_style",
            "body_style_match_count",
            "known_body_style_mismatch_count", "unknown_body_style_count",
            "same_body_style_count",
        )
        for field in scalar_fields:
            self.assertEqual(getattr(legacy, field), getattr(prepared, field), field)
        self.assertEqual(
            legacy.comparables["listing_id"].tolist(),
            prepared.comparables["listing_id"].tolist(),
        )
        pd.testing.assert_series_equal(
            legacy.comparables["similarity_weight"].reset_index(drop=True),
            prepared.comparables["similarity_weight"].reset_index(drop=True),
        )

        legacy_market = estimate_market_value(legacy)
        prepared_market = estimate_market_value(prepared)
        for field in (
            "status", "estimated_market_price", "comparable_count", "confidence",
            "total_similarity_weight", "mean_similarity_weight", "strong_comparable_count",
        ):
            self.assertEqual(getattr(legacy_market, field), getattr(prepared_market, field), field)
        legacy_economic = calculate_economic_opportunity(target["price"], legacy_market)
        prepared_economic = calculate_economic_opportunity(target["price"], prepared_market)
        self.assertEqual(legacy_economic, prepared_economic)
        eligibility = evaluate_valuation_eligibility(target)
        self.assertEqual(
            calculate_opportunity_score(legacy_economic, eligibility.status),
            calculate_opportunity_score(prepared_economic, eligibility.status),
        )

    def test_prepared_universe_computes_canonical_classification_once_per_active_listing(self):
        frame = pd.DataFrame([
            row("target", title="BMW 320d Touring"),
            row("candidate", title="BMW 320d Kombi"),
            row("inactive", active=0),
        ])
        with (
            patch(
                "analytics.comparables.evaluate_valuation_eligibility",
                wraps=evaluate_valuation_eligibility,
            ) as eligibility,
            patch(
                "analytics.comparables.extract_vehicle_semantics",
                wraps=extract_vehicle_semantics,
            ) as semantics,
        ):
            universe = prepare_comparable_universe(frame)
            self.assertEqual(eligibility.call_count, 2)
            self.assertEqual(semantics.call_count, 2)
            find_comparables(frame.iloc[0], universe=universe)
            find_comparables(frame.iloc[1], universe=universe)
            self.assertEqual(eligibility.call_count, 2)
            self.assertEqual(semantics.call_count, 2)


if __name__ == "__main__":
    unittest.main()
