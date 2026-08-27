import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from storage import sqlite


class StorageSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "listings.db"
        self.db_patch = patch("storage.sqlite.DB_PATH", self.db_path)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        sqlite.init_db()

    def test_scrape_run_count_comes_from_persisted_rows(self):
        sqlite.record_collector_run(search_name="test", succeeded=True)
        sqlite.record_collector_run(search_name="test", succeeded=False)
        with sqlite.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
        self.assertEqual(count, 2)

    def test_search_presence_updates_lifecycle_without_overwriting_detail_or_history(self):
        observed_at = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
        seen_at = observed_at + timedelta(hours=1)
        row = {
            "listing_id": "123",
            "title": "Detailed BMW title",
            "price": 12_500,
            "mileage_km": 145_000,
            "first_registration": "2017-09",
            "fuel": "DIESEL",
            "transmission": "AUTOMATIC",
            "location": "NRW",
            "url": "https://example.test/123",
            "is_active": True,
            "posted_date": "26.08.2026",
            "view_count": 10,
            "scraped_at": observed_at.isoformat(),
        }
        sqlite.upsert_listing(row)
        sqlite.insert_listing_history(row)

        updated = sqlite.mark_listings_seen(["123"], seen_at=seen_at)
        listing = sqlite.get_known_listings()[0]
        with sqlite.get_connection() as conn:
            history_count = conn.execute(
                "SELECT COUNT(*) FROM listing_history"
            ).fetchone()[0]

        self.assertEqual(updated, 1)
        self.assertEqual(listing["title"], "Detailed BMW title")
        self.assertEqual(listing["price"], 12_500)
        self.assertEqual(listing["last_seen"], seen_at.isoformat())
        self.assertEqual(listing["last_checked_at"], observed_at.isoformat())
        self.assertEqual(listing["last_detail_at"], observed_at.isoformat())
        self.assertEqual(history_count, 1)


if __name__ == "__main__":
    unittest.main()
