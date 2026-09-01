import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from analytics.opportunity_snapshots import build_opportunity_snapshot_records
from dashboard.data import load_opportunity_snapshots_before_inactivity
from storage import sqlite


OBSERVED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def listing(
    listing_id: str,
    *,
    price: int = 10_000,
    transmission: str = "Automatik",
    active: int = 1,
) -> dict:
    return {
        "listing_id": listing_id,
        "title": "BMW 320d Touring",
        "price": price,
        "mileage_km": 150_000,
        "first_registration": "2016",
        "transmission": transmission,
        "location": "NRW",
        "is_active": active,
    }


def snapshot_record(
    listing_id: str,
    observed_at: str,
    score: float = 70.0,
) -> dict:
    return {
        "listing_id": listing_id,
        "observed_at": observed_at,
        "asking_price": 8_000,
        "estimated_market_price": 10_000,
        "market_gap_eur": 2_000,
        "discount_percent": 20.0,
        "opportunity_score": score,
        "score_version": "2.1",
        "opportunity_status": "OK",
        "valuation_status": "ELIGIBLE",
        "valuation_confidence": "HIGH",
        "market_value_status": "OK",
        "comparable_count": 6,
        "strong_comparable_count": 6,
        "discount_component": 72.0,
        "margin_component": 55.0,
        "base_opportunity": 66.9,
        "confidence_multiplier": 1.0,
        "risk_multiplier": 1.0,
        "valuation_vocabulary_version": 2,
        "vehicle_semantics_version": 1,
        "comparable_version": "3",
    }


class OpportunitySnapshotCalculationTests(unittest.TestCase):
    def test_only_active_scorable_listings_create_versioned_snapshots(self):
        records = [listing("target", price=8_000)]
        records.extend(
            listing(f"comparable-{index}", price=10_000 + index * 100)
            for index in range(10)
        )
        records.append(listing("inactive", active=0))
        records.append(listing("unavailable", transmission="Schaltgetriebe"))

        snapshots = build_opportunity_snapshot_records(
            pd.DataFrame(records), OBSERVED_AT
        )
        by_id = {snapshot["listing_id"]: snapshot for snapshot in snapshots}

        self.assertIn("target", by_id)
        self.assertNotIn("inactive", by_id)
        self.assertNotIn("unavailable", by_id)
        target = by_id["target"]
        self.assertIsNotNone(target["opportunity_score"])
        self.assertEqual(target["score_version"], "2.1")
        self.assertEqual(target["valuation_vocabulary_version"], 2)
        self.assertEqual(target["vehicle_semantics_version"], 1)
        self.assertEqual(target["comparable_version"], "3")
        self.assertEqual(target["valuation_confidence"], "HIGH")
        self.assertEqual(target["comparable_count"], 10)
        self.assertEqual(target["observed_at"], OBSERVED_AT.isoformat())

    def test_empty_and_inactive_universe_create_no_snapshots(self):
        self.assertEqual(
            build_opportunity_snapshot_records(pd.DataFrame(), OBSERVED_AT), []
        )
        self.assertEqual(
            build_opportunity_snapshot_records(
                pd.DataFrame([listing("inactive", active=0)]), OBSERVED_AT
            ),
            [],
        )


class OpportunitySnapshotStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "listings.db"
        self.storage_patch = patch("storage.sqlite.DB_PATH", self.db_path)
        self.dashboard_patch = patch("dashboard.data.DB_PATH", self.db_path)
        self.storage_patch.start()
        self.dashboard_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.addCleanup(self.dashboard_patch.stop)
        self.addCleanup(load_opportunity_snapshots_before_inactivity.clear)
        load_opportunity_snapshots_before_inactivity.clear()
        sqlite.init_db()

    def test_migration_is_idempotent_and_preserves_existing_tables(self):
        with sqlite.get_connection() as conn:
            conn.execute(
                "INSERT INTO listings (listing_id, is_active) VALUES (?, ?)",
                ("existing", 1),
            )
            conn.execute(
                "INSERT INTO listing_history (listing_id, scraped_at) VALUES (?, ?)",
                ("existing", OBSERVED_AT.isoformat()),
            )
            conn.execute(
                "INSERT INTO scrape_runs (search_name, finished_at, succeeded) "
                "VALUES (?, ?, ?)",
                ("test", OBSERVED_AT.isoformat(), 1),
            )
            conn.commit()

        sqlite.init_db()
        sqlite.init_db()

        with sqlite.get_connection() as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            counts = tuple(
                conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("listings", "listing_history", "scrape_runs")
            )
        self.assertIn("opportunity_snapshots", tables)
        self.assertEqual(counts, (1, 1, 1))

    def test_duplicate_same_observation_is_prevented(self):
        record = snapshot_record("listing", OBSERVED_AT.isoformat())

        first = sqlite.insert_opportunity_snapshots([record])
        second = sqlite.insert_opportunity_snapshots([record])

        self.assertEqual(first, 1)
        self.assertEqual(second, 0)
        with sqlite.get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM opportunity_snapshots"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_dashboard_selects_latest_snapshot_not_after_inactivity(self):
        with sqlite.get_connection() as conn:
            conn.execute(
                "INSERT INTO listings "
                "(listing_id, is_active, inactive_at) VALUES (?, ?, ?)",
                ("listing", 0, "2026-08-28T13:36:00+00:00"),
            )
            conn.commit()
        sqlite.insert_opportunity_snapshots(
            [
                snapshot_record("listing", "2026-08-28T10:00:00+00:00", 74.2),
                snapshot_record("listing", "2026-08-28T12:00:00+00:00", 76.1),
                snapshot_record("listing", "2026-08-28T14:00:00+00:00", 99.0),
            ]
        )

        snapshots = load_opportunity_snapshots_before_inactivity("listing")

        self.assertEqual(snapshots["opportunity_score"].tolist(), [74.2, 76.1])
        self.assertTrue(snapshots["observed_at"].is_monotonic_increasing)
        self.assertEqual(snapshots.iloc[-1]["valuation_confidence"], "HIGH")

    def test_inactive_without_snapshot_returns_empty_not_zero(self):
        with sqlite.get_connection() as conn:
            conn.execute(
                "INSERT INTO listings "
                "(listing_id, is_active, inactive_at) VALUES (?, ?, ?)",
                ("listing", 0, "2026-08-28T13:36:00+00:00"),
            )
            conn.commit()

        snapshots = load_opportunity_snapshots_before_inactivity("listing")

        self.assertTrue(snapshots.empty)


if __name__ == "__main__":
    unittest.main()
