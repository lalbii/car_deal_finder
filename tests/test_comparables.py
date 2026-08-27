import unittest

import pandas as pd

from analytics.comparables import ComparableConfig, ComparableStatus, find_comparables
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


if __name__ == "__main__":
    unittest.main()
