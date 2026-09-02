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
    build_inactive_frame,
    build_opportunity_frame,
    canonical_lifecycle_status,
    dashboard_source_freshness,
)
from dashboard.formatting import (
    format_datetime,
    format_euro,
    format_listing_age,
    format_listing_date,
    format_mileage,
    format_percent,
    format_signed_euro,
    format_signed_percent,
)
from dashboard.views import (
    _collector_health,
    _format_duration,
    _format_observed_duration,
    _inactive_count_label,
    _inactive_filter_argument,
    build_history_series,
    build_inactive_table,
    build_comparables_table,
    build_opportunities_table,
    filter_inactive_listings,
    filter_opportunities,
    render_listing_detail,
    resolve_selected_listing_id,
    sort_inactive_listings,
    sort_opportunities,
)


class DashboardDataTests(unittest.TestCase):
    def test_comparable_table_validates_persisted_urls_without_reordering(self):
        valid = "https://www.kleinanzeigen.de/s-anzeige/bmw-320d/123-216-1"
        source = pd.DataFrame([
            {
                "listing_id": "123", "title": "First", "price": 10000,
                "year": 2016, "mileage_km": 150000,
                "candidate_body_style": "WAGON", "similarity_weight": 0.91,
                "url": valid,
            },
            {
                "listing_id": "456", "title": "Missing", "price": 11000,
                "year": 2017, "mileage_km": 140000,
                "candidate_body_style": "SEDAN", "similarity_weight": 0.82,
                "url": None,
            },
            {
                "listing_id": "789", "title": "Search", "price": 12000,
                "year": 2018, "mileage_km": 130000,
                "candidate_body_style": "SUV", "similarity_weight": 0.73,
                "url": "https://www.kleinanzeigen.de/s-autos/bmw/k0c216",
            },
            {
                "listing_id": "999", "title": "External", "price": 13000,
                "year": 2019, "mileage_km": 120000,
                "candidate_body_style": "COUPE", "similarity_weight": 0.64,
                "url": "https://example.test/s-anzeige/bmw/999-216-1",
            },
        ])

        table = build_comparables_table(source)

        self.assertEqual(
            table.columns.tolist(),
            ["Title", "Price", "Year", "Mileage", "Body Style", "Similarity", "Open Listing"],
        )
        self.assertEqual(table["Title"].tolist(), source["title"].tolist())
        self.assertEqual(table["Similarity"].tolist(), source["similarity_weight"].tolist())
        self.assertEqual(table.iloc[0]["Open Listing"], valid)
        self.assertTrue(all(value is None for value in table["Open Listing"].iloc[1:]))

    @staticmethod
    def inactive_listings_fixture() -> pd.DataFrame:
        return pd.DataFrame([
            {
                "listing_id": "inactive-b", "title": "BMW 320d Touring",
                "price": 8900, "mileage_km": 160000,
                "first_registration": "2016", "transmission": "AUTOMATIC",
                "is_active": 0, "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-13T00:00:00Z",
                "inactive_at": "2026-01-15T00:00:00Z", "url": "https://example.test/b",
            },
            {
                "listing_id": "inactive-a", "title": "BMW 320d Limousine",
                "price": 10000, "mileage_km": 140000,
                "first_registration": "2017", "transmission": "MANUAL",
                "is_active": 0, "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-04T00:00:00Z",
                "inactive_at": "2026-01-15T00:00:00Z", "url": "https://example.test/a",
            },
            {
                "listing_id": "active", "title": "BMW 320d Touring",
                "price": 11000, "mileage_km": 130000,
                "first_registration": "2018", "transmission": "AUTOMATIC",
                "is_active": 1, "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-10T00:00:00Z", "inactive_at": None,
                "url": "https://example.test/active",
            },
            {
                "listing_id": "unknown", "title": "BMW 320d",
                "price": 9000, "mileage_km": 170000,
                "first_registration": "2015", "transmission": "AUTOMATIC",
                "is_active": None, "first_seen": "2026-01-01T00:00:00Z",
                "last_seen": "2026-01-02T00:00:00Z", "inactive_at": None,
                "url": "https://example.test/unknown",
            },
        ])

    def test_inactive_frame_scope_history_duration_and_deterministic_sort(self):
        history = pd.DataFrame([
            {"listing_id": "inactive-b", "price": 8900, "scraped_at": "2026-01-12"},
            {"listing_id": "inactive-b", "price": 9500, "scraped_at": "2026-01-02"},
            {"listing_id": "active", "price": 11000, "scraped_at": "2026-01-03"},
        ])
        with patch("dashboard.data.calculate_opportunity_score") as score:
            result = build_inactive_frame(self.inactive_listings_fixture(), history)
        self.assertEqual(result["listing_id"].tolist(), ["inactive-a", "inactive-b"])
        self.assertNotIn("active", result["listing_id"].tolist())
        self.assertNotIn("unknown", result["listing_id"].tolist())
        b = result.set_index("listing_id").loc["inactive-b"]
        self.assertEqual(b["initial_observed_price"], 9500)
        self.assertEqual(b["last_observed_price"], 8900)
        self.assertEqual(b["price_change_eur"], -600)
        self.assertAlmostEqual(b["price_change_percent"], -600 / 9500 * 100)
        self.assertEqual(b["observed_duration_days"], 12)
        self.assertNotIn("sale_status", result.columns)
        self.assertNotIn("opportunity_score", result.columns)
        score.assert_not_called()

    def test_inactive_frame_missing_history_and_timestamps_are_safe(self):
        listings = self.inactive_listings_fixture().iloc[[0]].copy()
        listings.loc[:, "first_seen"] = None
        result = build_inactive_frame(listings, pd.DataFrame())
        row = result.iloc[0]
        self.assertTrue(pd.isna(row["initial_observed_price"]))
        self.assertTrue(pd.isna(row["last_observed_price"]))
        self.assertTrue(pd.isna(row["price_change_eur"]))
        self.assertTrue(pd.isna(row["price_change_percent"]))
        self.assertTrue(pd.isna(row["observed_duration_days"]))
        self.assertEqual(_format_observed_duration(row["observed_duration_days"]), "—")

    def test_inactive_filters_and_sorting(self):
        frame = build_inactive_frame(
            self.inactive_listings_fixture(),
            pd.DataFrame([
                {"listing_id": "inactive-a", "price": 10000, "scraped_at": "2026-01-01"},
                {"listing_id": "inactive-b", "price": 9500, "scraped_at": "2026-01-01"},
                {"listing_id": "inactive-b", "price": 8900, "scraped_at": "2026-01-02"},
            ]),
        )
        filtered = filter_inactive_listings(
            frame, year_range=(2016, 2016), mileage_max=170000,
            transmissions=("AUTOMATIC",), body_styles=("WAGON",),
            price_range=(8000, 9000), duration_max_days=15,
            price_decreased_only=True,
        )
        self.assertEqual(filtered["listing_id"].tolist(), ["inactive-b"])
        self.assertEqual(
            sort_inactive_listings(frame.sample(frac=1, random_state=3))["listing_id"].tolist(),
            ["inactive-a", "inactive-b"],
        )
        self.assertEqual(_format_observed_duration(1), "1d")
        self.assertEqual(_format_observed_duration(12.9), "12d 22h")

    def test_inactive_neutral_defaults_preserve_all_rows_and_missing_values(self):
        listings = self.inactive_listings_fixture().iloc[:2].copy()
        missing = listings.iloc[0].copy()
        missing["listing_id"] = "inactive-missing"
        missing["title"] = None
        missing["price"] = None
        missing["mileage_km"] = None
        missing["first_registration"] = None
        missing["transmission"] = None
        missing["first_seen"] = None
        missing["last_seen"] = None
        listings = pd.concat([listings, missing.to_frame().T], ignore_index=True)
        frame = build_inactive_frame(listings, pd.DataFrame())

        neutral = filter_inactive_listings(
            frame,
            year_range=_inactive_filter_argument((2016, 2017), (2016, 2017)),
            mileage_max=_inactive_filter_argument(160000, 160000),
            transmissions=_inactive_filter_argument(
                ("AUTOMATIC", "MANUAL", "UNKNOWN"),
                ("AUTOMATIC", "MANUAL", "UNKNOWN"),
            ),
            body_styles=_inactive_filter_argument(
                ("SEDAN", "UNKNOWN", "WAGON"),
                ("SEDAN", "UNKNOWN", "WAGON"),
            ),
            price_range=_inactive_filter_argument((8900.0, 10000.0), (8900.0, 10000.0)),
            duration_max_days=_inactive_filter_argument(12, 12),
        )

        self.assertEqual(len(neutral), 3)
        self.assertIn("inactive-missing", neutral["listing_id"].tolist())

    def test_inactive_restrictive_filters_still_apply(self):
        frame = build_inactive_frame(self.inactive_listings_fixture(), pd.DataFrame())

        self.assertEqual(
            filter_inactive_listings(frame, year_range=(2016, 2016))["listing_id"].tolist(),
            ["inactive-b"],
        )
        self.assertEqual(
            filter_inactive_listings(frame, mileage_max=150000)["listing_id"].tolist(),
            ["inactive-a"],
        )
        self.assertTrue(
            filter_inactive_listings(frame, transmissions=()).empty
        )

    def test_mixed_persisted_timestamps_preserve_duration_semantics(self):
        listings = self.inactive_listings_fixture().iloc[[0]].copy()
        listings.loc[:, "first_seen"] = "2026-01-01T00:00:00.000000"
        listings.loc[:, "last_seen"] = "2026-01-01T18:30:00.000000+00:00"

        result = build_inactive_frame(listings, pd.DataFrame())

        self.assertAlmostEqual(result.iloc[0]["observed_duration_days"], 18.5 / 24)
        self.assertEqual(_format_observed_duration(result.iloc[0]["observed_duration_days"]), "19h")

    def test_inactive_count_label_reports_shown_and_total(self):
        self.assertEqual(
            _inactive_count_label(4, 11),
            "Showing 4 of 11 inactive listings",
        )

    def test_inactive_table_is_selectable_by_hidden_id_without_open_link(self):
        frame = build_inactive_frame(self.inactive_listings_fixture(), pd.DataFrame())
        table = build_inactive_table(frame)

        self.assertIn("listing_id", table.columns)
        self.assertNotIn("Open Listing", table.columns)
        self.assertNotIn("Listing ID", table.columns)
        self.assertEqual(
            resolve_selected_listing_id(table, [1]),
            table.iloc[1]["listing_id"],
        )
        self.assertIsNone(resolve_selected_listing_id(table, []))
        self.assertIsNone(resolve_selected_listing_id(table, [len(table)]))

    def test_history_series_uses_only_persisted_valid_ordered_observations(self):
        history = pd.DataFrame(
            [
                {
                    "scraped_at": "2026-01-02T12:00:00+00:00",
                    "price": 9000,
                    "view_count": 120,
                    "inactive_at": "2026-01-03T00:00:00Z",
                },
                {
                    "scraped_at": "2026-01-01T12:00:00.000000",
                    "price": 9500,
                    "view_count": 100,
                    "inactive_at": None,
                },
                {
                    "scraped_at": "invalid",
                    "price": 8000,
                    "view_count": 999,
                    "inactive_at": None,
                },
                {
                    "scraped_at": "2026-01-02T12:00:00+00:00",
                    "price": 9000,
                    "view_count": None,
                    "inactive_at": None,
                },
                {
                    "scraped_at": "2026-01-03T12:00:00Z",
                    "price": None,
                    "view_count": 140,
                    "inactive_at": None,
                },
            ]
        )

        prices = build_history_series(history, "price")
        views = build_history_series(history, "view_count")

        self.assertEqual(prices["price"].tolist(), [9500, 9000, 9000])
        self.assertEqual(views["view_count"].tolist(), [100, 120, 140])
        self.assertTrue(prices["scraped_at"].is_monotonic_increasing)
        self.assertTrue(views["scraped_at"].is_monotonic_increasing)
        self.assertEqual(len(prices), 3)
        self.assertNotIn("inactive_at", prices.columns)

    def test_missing_history_signal_returns_safe_empty_series(self):
        history = pd.DataFrame(
            [{"scraped_at": "2026-01-01T00:00:00Z", "price": 9000}]
        )

        views = build_history_series(history, "view_count")

        self.assertTrue(views.empty)
        self.assertEqual(views.columns.tolist(), ["scraped_at", "view_count"])

    def test_inactive_navigation_is_separate(self):
        app = Path(__file__).resolve().parents[1].joinpath("dashboard", "app.py").read_text()
        views = Path(__file__).resolve().parents[1].joinpath("dashboard", "views.py").read_text()
        self.assertIn('"Inactive Listings"', app)
        self.assertIn("render_inactive_listings()", app)
        self.assertIn("render_collector_health()", app)
        self.assertIn("INACTIVE does not necessarily mean SOLD", views)

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

    def test_listing_age_uses_posted_date_and_last_check_only(self):
        self.assertEqual(
            format_listing_age("26.08.2026", "2026-09-01T21:00:00Z"), "6d"
        )
        self.assertEqual(format_listing_date("26.08.2026"), "2026-08-26")
        self.assertEqual(format_listing_age(None, "2026-09-01T21:00:00Z"), "—")
        self.assertEqual(format_listing_age("26.08.2026", None), "—")
        self.assertEqual(
            format_listing_age("02.09.2026", "2026-09-01T21:00:00Z"), "—"
        )
        self.assertEqual(
            format_listing_age("invalid", "2026-09-01T21:00:00Z"), "—"
        )
        # A date-only source deliberately never produces hour precision.
        self.assertEqual(
            format_listing_age("01.09.2026", "2026-09-01T23:59:00Z"), "0d"
        )
        # Full timestamps remain robust if a historical value contains one.
        self.assertEqual(
            format_listing_age(
                "2026-08-29T17:00:00Z", "2026-09-01T21:00:00Z"
            ),
            "3d 4h",
        )

    def test_formatting(self):
        self.assertEqual(format_euro(9500), "€9.500")
        self.assertEqual(format_mileage(142000), "142.000 km")
        self.assertEqual(format_percent(-16.72), "-16.7%")
        self.assertEqual(format_signed_euro(1900), "+€1.900")
        self.assertEqual(format_signed_euro(-2000), "-€2.000")
        self.assertEqual(format_signed_euro(None), "—")
        self.assertEqual(format_signed_percent(20), "+20.0%")
        self.assertEqual(format_signed_percent(-20), "-20.0%")
        self.assertEqual(format_datetime("2026-08-28T12:41:59+00:00"), "2026-08-28 12:41")
        self.assertEqual(format_datetime(None), "—")

    def test_opportunity_frame_uses_canonical_analytics_and_not_legacy_score(self):
        listings = pd.DataFrame([{
            "listing_id": "1", "title": "BMW 320d Touring", "price": 8000,
            "mileage_km": 150000, "first_registration": "2016",
            "transmission": "AUTOMATIC", "is_active": 1,
            "first_seen": "2026-08-27T10:00:00Z",
            "last_seen": "2026-08-28T12:41:00Z",
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
        self.assertEqual(result.iloc[0]["last_seen"], "2026-08-28T12:41:00Z")
        self.assertNotIn("deal_score", result.columns)

    def test_opportunity_table_shows_canonical_lifecycle_fields(self):
        frame = pd.DataFrame([
            {
                "listing_id": "a", "opportunity_score": 70.0,
                "title": "BMW 320d Touring", "price": 10000,
                "estimated_market_price": 12000, "market_gap_eur": 2000,
                "discount_percent": 16.67, "valuation_confidence": "HIGH",
                "year": 2016, "mileage_km": 150000,
                "transmission": "AUTOMATIC", "body_style": "WAGON",
                "first_seen": "2026-08-27T10:00:00Z",
                "last_seen": "2026-08-28T12:41:00Z",
                "posted_date": "26.08.2026",
                "last_checked_at": "2026-08-28T13:00:00Z", "is_active": 1,
                "url": "https://example.test/a",
            },
            {
                "listing_id": "b", "opportunity_score": 60.0,
                "title": "BMW 320d", "price": 9000,
                "estimated_market_price": 10000, "market_gap_eur": 1000,
                "discount_percent": 10.0, "valuation_confidence": "MEDIUM",
                "year": 2015, "mileage_km": 170000,
                "transmission": "MANUAL", "body_style": "UNKNOWN",
                "first_seen": "2026-08-27T11:00:00Z",
                "last_seen": None, "posted_date": None,
                "last_checked_at": None, "is_active": 0,
                "url": "https://example.test/b",
            },
            {
                "listing_id": "c", "opportunity_score": 50.0,
                "title": "BMW 320d", "price": 8500,
                "estimated_market_price": 9500, "market_gap_eur": 1000,
                "discount_percent": 10.5, "valuation_confidence": "LOW",
                "year": 2014, "mileage_km": 180000,
                "transmission": "MANUAL", "body_style": "UNKNOWN",
                "first_seen": "2026-08-26T11:00:00Z", "last_seen": None,
                "posted_date": "29.08.2026",
                "last_checked_at": "2026-08-28T13:00:00Z", "is_active": None,
                "url": "https://example.test/c",
            },
        ])
        table = build_opportunities_table(frame)
        self.assertIn("Open Listing", table.columns)
        self.assertNotIn("Last Seen", table.columns)
        self.assertEqual(table["Listing Date"].tolist(), ["2026-08-26", "—", "2026-08-29"])
        self.assertEqual(table["Last Checked"].tolist(), ["2026-08-28 13:00", "—", "2026-08-28 13:00"])
        self.assertEqual(table["Listing Age"].tolist(), ["2d", "—", "—"])
        self.assertNotIn("First Seen", table.columns)
        self.assertNotIn("Last Search Presence", table.columns)
        self.assertEqual(table["Status"].tolist(), ["ACTIVE", "INACTIVE", "UNKNOWN"])
        self.assertLess(table.columns.get_loc("Listing Date"), table.columns.get_loc("Last Checked"))
        self.assertLess(table.columns.get_loc("Last Checked"), table.columns.get_loc("Listing Age"))
        self.assertEqual(table["listing_id"].tolist(), ["a", "b", "c"])
        self.assertEqual(
            table["Open Listing"].tolist(),
            frame["url"].tolist(),
        )
        self.assertEqual(canonical_lifecycle_status("uncertain"), "UNKNOWN")

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
            "last_seen": "2026-01-02T12:41:00Z", "posted_date": "26.12.2025",
            "last_checked_at": "2026-01-02T13:00:00Z", "is_active": 1,
        })
        comparables = pd.DataFrame([{
            "listing_id": "2",
            "url": "https://www.kleinanzeigen.de/s-anzeige/bmw-320d-kombi/2-216-1",
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
            metadata = streamlit.write.call_args_list[0].args[0]
            self.assertEqual(metadata["Listing Date"], "2025-12-26")
            self.assertEqual(metadata["Listing Age"], "7d")
            self.assertNotIn("First Seen", metadata)
            self.assertNotIn("Last Search Presence", metadata)
            self.assertEqual(metadata["Last Checked"], "2026-01-02 13:00")
            self.assertEqual(metadata["Status"], "ACTIVE")
            comparable_tables = [
                call.args[0] for call in streamlit.dataframe.call_args_list
                if call.args and isinstance(call.args[0], pd.DataFrame)
            ]
            comparable_table = next(
                table for table in comparable_tables if "Open Listing" in table
            )
            self.assertEqual(
                comparable_table.iloc[0]["Open Listing"],
                "https://www.kleinanzeigen.de/s-anzeige/bmw-320d-kombi/2-216-1",
            )
            dataframe_call = next(
                call for call in streamlit.dataframe.call_args_list
                if call.args and call.args[0] is comparable_table
            )
            self.assertIn("Open Listing", dataframe_call.kwargs["column_config"])


if __name__ == "__main__":
    unittest.main()
