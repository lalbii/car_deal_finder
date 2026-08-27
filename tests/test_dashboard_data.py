import unittest
import sqlite3
import tempfile
import tomllib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from dashboard.data import (
    _connect_read_only,
    _derive_price_drop_summary,
    build_opportunity_frame,
    dashboard_source_freshness,
)
from dashboard.formatting import (
    format_euro,
    format_mileage,
    format_percent,
    format_signed_euro,
    format_signed_percent,
)
from dashboard.views import (
    _collector_health,
    _format_duration,
    filter_opportunities,
    render_listing_detail,
    sort_opportunities,
)


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
        self.assertEqual(format_signed_euro(1900), "+€1.900")
        self.assertEqual(format_signed_euro(-2000), "-€2.000")
        self.assertEqual(format_signed_euro(None), "—")
        self.assertEqual(format_signed_percent(20), "+20.0%")
        self.assertEqual(format_signed_percent(-20), "-20.0%")

    def test_opportunity_frame_uses_canonical_analytics_and_not_legacy_score(self):
        listings = pd.DataFrame([{
            "listing_id": "1", "title": "BMW 320d Touring", "price": 8000,
            "mileage_km": 150000, "first_registration": "2016",
            "transmission": "AUTOMATIC", "is_active": 1,
        }])
        eligibility = SimpleNamespace(
            status=SimpleNamespace(value="ELIGIBLE"), reasons=()
        )
        comparable = object()
        market = SimpleNamespace(
            status=SimpleNamespace(value="OK"), estimated_market_price=10000,
            confidence=SimpleNamespace(value="HIGH"), comparable_count=10,
        )
        economic = SimpleNamespace(
            status=SimpleNamespace(value="OK"), market_gap_eur=2000,
            discount_percent=20,
        )
        score = SimpleNamespace(
            opportunity_score=75.0, score_version="2.1",
            status=SimpleNamespace(value="OK"), discount_component=72.0,
            margin_component=55.0, base_opportunity=66.9,
            confidence_multiplier=1.0, risk_multiplier=1.0,
        )
        semantics = SimpleNamespace(body_style=SimpleNamespace(value="WAGON"))
        universe = SimpleNamespace(
            eligibility_by_id={"1": eligibility},
            semantics_by_id={"1": semantics},
        )
        with (
            patch("dashboard.data.prepare_comparable_universe", return_value=universe) as prepare,
            patch("dashboard.data.find_comparables", return_value=comparable) as find,
            patch("dashboard.data.estimate_market_value", return_value=market) as estimate,
            patch("dashboard.data.calculate_economic_opportunity", return_value=economic) as economics,
            patch("dashboard.data.calculate_opportunity_score", return_value=score) as scoring,
            patch("dashboard.data.extract_vehicle_semantics", return_value=semantics),
        ):
            result = build_opportunity_frame(listings)
        prepare.assert_called_once()
        find.assert_called_once()
        estimate.assert_called_once_with(comparable)
        economics.assert_called_once_with(8000, market)
        scoring.assert_called_once_with(economic, eligibility.status)
        self.assertEqual(result.iloc[0]["opportunity_score"], 75.0)
        self.assertEqual(result.iloc[0]["body_style"], "WAGON")
        self.assertNotIn("deal_score", result.columns)

    def test_filters_and_default_sort_are_deterministic(self):
        frame = pd.DataFrame([
            {"listing_id": "b", "opportunity_score": 70.0, "discount_percent": 20.0,
             "market_gap_eur": 2000.0, "valuation_confidence": "HIGH", "year": 2016,
             "mileage_km": 150000, "transmission": "AUTOMATIC", "body_style": "WAGON"},
            {"listing_id": "a", "opportunity_score": 70.0, "discount_percent": 20.0,
             "market_gap_eur": 2000.0, "valuation_confidence": "HIGH", "year": 2016,
             "mileage_km": 140000, "transmission": "AUTOMATIC", "body_style": "WAGON"},
            {"listing_id": "c", "opportunity_score": 60.0, "discount_percent": -5.0,
             "market_gap_eur": -500.0, "valuation_confidence": "LOW", "year": 2010,
             "mileage_km": 250000, "transmission": "MANUAL", "body_style": "SEDAN"},
            {"listing_id": "u", "opportunity_score": None, "discount_percent": None,
             "market_gap_eur": None, "valuation_confidence": "UNAVAILABLE", "year": 2015,
             "mileage_km": 100000, "transmission": "AUTOMATIC", "body_style": "UNKNOWN"},
        ])
        default = filter_opportunities(frame)
        self.assertEqual(default["listing_id"].tolist(), ["a", "b"])
        selected = filter_opportunities(
            frame,
            minimum_score=65,
            confidences=("HIGH",),
            year_range=(2015, 2020),
            mileage_max=145000,
            transmissions=("AUTOMATIC",),
            body_styles=("WAGON",),
        )
        self.assertEqual(selected["listing_id"].tolist(), ["a"])
        with_unavailable = filter_opportunities(frame, include_unavailable=True)
        self.assertIn("u", with_unavailable["listing_id"].tolist())
        self.assertEqual(sort_opportunities(frame).iloc[0]["listing_id"], "a")

    def test_sqlite_connection_is_query_only(self):
        with _connect_read_only() as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)

    def test_cache_freshness_key_changes_with_persisted_source_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dashboard.db"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE listings (last_seen TEXT)")
                connection.execute(
                    "CREATE TABLE scrape_runs (finished_at TEXT, succeeded INTEGER)"
                )
                connection.execute("INSERT INTO listings VALUES ('2026-01-01')")
                connection.execute("INSERT INTO scrape_runs VALUES ('2026-01-01', 1)")
            first = dashboard_source_freshness(path)
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT INTO listings VALUES ('2026-01-02')")
                connection.execute("INSERT INTO scrape_runs VALUES ('2026-01-02', 1)")
            second = dashboard_source_freshness(path)
        self.assertNotEqual(first, second)
        self.assertEqual(second[-2:], ("2026-01-02", "2026-01-02"))

    def test_streamlit_remains_bound_to_localhost(self):
        config_path = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["server"]["address"], "127.0.0.1")

    def test_listing_detail_exposes_score_components_and_canonical_comparables(self):
        listing = pd.Series({
            "listing_id": "1", "title": "BMW 320d Touring", "url": "https://example.test/1",
            "price": 8000, "first_registration": "2016", "mileage_km": 150000,
            "transmission": "AUTOMATIC", "first_seen": "2026-01-01",
        })
        comparables = pd.DataFrame([{
            "title": "BMW 320d Kombi", "price": 10000, "year": 2016,
            "mileage_km": 155000, "candidate_body_style": "WAGON",
            "similarity_weight": 0.9,
        }])
        analysis = {
            "listing": listing,
            "eligibility": SimpleNamespace(status=SimpleNamespace(value="ELIGIBLE"), reasons=()),
            "semantics": SimpleNamespace(body_style=SimpleNamespace(value="WAGON")),
            "market_value": SimpleNamespace(
                estimated_market_price=10000, confidence=SimpleNamespace(value="HIGH"),
                comparable_count=1, comparables=comparables,
            ),
            "economic": SimpleNamespace(market_gap_eur=2000, discount_percent=20),
            "score": SimpleNamespace(
                score_version="2.1", discount_component=72, margin_component=55,
                base_opportunity=66.9, confidence_multiplier=1,
                risk_multiplier=1, opportunity_score=66.9,
            ),
        }
        metric_columns = []

        def columns(count):
            values = [MagicMock() for _ in range(count)]
            metric_columns.extend(values)
            return values

        with (
            patch("dashboard.views.load_listing_analysis", return_value=analysis),
            patch("dashboard.views.load_history", return_value=pd.DataFrame()),
            patch("dashboard.views.st") as streamlit,
        ):
            streamlit.session_state = {"selected_listing_id": "1"}
            streamlit.columns.side_effect = columns
            render_listing_detail()
            labels = {
                call.args[0]
                for column in metric_columns
                for call in column.metric.call_args_list
            }
            self.assertTrue({
                "Discount component", "Margin component", "Base opportunity",
                "Confidence multiplier", "Risk multiplier", "Final score",
            }.issubset(labels))
            comparable_tables = [
                call.args[0] for call in streamlit.dataframe.call_args_list
                if call.args and isinstance(call.args[0], pd.DataFrame)
            ]
            self.assertTrue(any("similarity_weight" in table for table in comparable_tables))


if __name__ == "__main__":
    unittest.main()
