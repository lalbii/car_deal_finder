import unittest
import pandas as pd

from dashboard.data import _derive_price_drop_summary
from dashboard.formatting import format_euro, format_mileage, format_percent
from dashboard.views import _collector_health, _format_duration


class DashboardDataTests(unittest.TestCase):
    def test_unchanged_prices_are_not_drops(self):
        df = pd.DataFrame({
            "listing_id": ["1", "1"],
            "price": [10000, 10000],
            "scraped_at": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        })
        result = _derive_price_drop_summary(df)
        self.assertTrue(result.empty)

    def test_price_drop_detected(self):
        df = pd.DataFrame({
            "listing_id": ["1", "1"],
            "price": [10000, 9000],
            "scraped_at": pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
        })
        result = _derive_price_drop_summary(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["price_drop_abs"], 1000)
        self.assertAlmostEqual(result.iloc[0]["price_drop_percent"], 10.0)

    def test_null_price_does_not_break_drop_detection(self):
        df = pd.DataFrame({
            "listing_id": ["1", "1", "1"],
            "price": [10000, None, 9500],
            "scraped_at": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"], utc=True),
        })
        result = _derive_price_drop_summary(df)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["price_drop_abs"], 500)

    def test_collector_health_states_and_schedule(self):
        now = pd.Timestamp("2026-08-27T10:08:00Z")
        healthy = {"finished_at": "2026-08-27T10:00:00Z", "last_success_at": "2026-08-27T10:00:00Z", "succeeded": 1, "blocking_failures": 0}
        self.assertEqual(_collector_health(healthy, now), {"label": "🟢 HEALTHY", "last": "8m ago", "next": "~52 min"})
        stale = dict(healthy, finished_at="2026-08-27T07:00:00Z", last_success_at="2026-08-27T07:00:00Z")
        self.assertEqual(_collector_health(stale, now)["label"], "🟡 STALE")
        self.assertEqual(_collector_health(dict(healthy, succeeded=0), now)["label"], "🔴 ERROR")
        self.assertEqual(_collector_health(None, now)["label"], "⚪ UNKNOWN")
        self.assertEqual(_format_duration(132), "2m12s")

    def test_formatting(self):
        self.assertEqual(format_euro(9500), "€9.500")
        self.assertEqual(format_mileage(142000), "142.000 km")
        self.assertEqual(format_percent(-16.72), "-16.7%")


if __name__ == "__main__":
    unittest.main()
