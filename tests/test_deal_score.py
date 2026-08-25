import unittest

import pandas as pd

from analytics.deal_score import add_deal_scores


class DealScoreProtectionTests(unittest.TestCase):
    def test_invalid_values_do_not_influence_medians_or_receive_scores(self):
        today = pd.Timestamp.now().strftime("%d.%m.%Y")
        df = pd.DataFrame(
            [
                self.row("a", 10_000, 100_000, today),
                self.row("b", 12_000, 120_000, today),
                self.row("c", 14_000, 140_000, today),
                self.row("bad-price", 0, 110_000, today),
                self.row("bad-registration", 11_000, 110_000, today, "invalid"),
            ]
        )

        scored = add_deal_scores(df).set_index("listing_id")

        self.assertEqual(scored.loc["a", "group_median_price"], 12_000)
        self.assertEqual(scored.loc["a", "group_valid_price_count"], 3)
        self.assertEqual(
            scored.loc["bad-price", "score_status"],
            "INVALID_OR_MISSING_CORE_DATA",
        )
        self.assertTrue(pd.isna(scored.loc["bad-price", "deal_score"]))
        self.assertTrue(pd.isna(scored.loc["bad-registration", "deal_score"]))
        self.assertEqual(scored.loc["a", "score_status"], "SCORABLE")

    @staticmethod
    def row(
        listing_id: str,
        price: int,
        mileage: int,
        posted_date: str,
        registration: str = "2015-06",
    ) -> dict:
        return {
            "listing_id": listing_id,
            "title": listing_id,
            "price": price,
            "mileage_km": mileage,
            "first_registration": registration,
            "fuel": "Diesel",
            "transmission": "Automatik",
            "location": "NRW",
            "url": f"https://example.test/{listing_id}",
            "is_active": 1,
            "posted_date": posted_date,
            "view_count": 10,
        }


if __name__ == "__main__":
    unittest.main()
