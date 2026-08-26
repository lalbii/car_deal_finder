import unittest
from datetime import datetime, timedelta, timezone

from operations.request_scheduling import should_check_status, should_refresh_detail


class RequestSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        self.detail_interval = timedelta(hours=6)
        self.status_interval = timedelta(hours=24)

    def test_new_listing_refreshes_immediately(self):
        self.assertTrue(
            should_refresh_detail(None, self.now, self.detail_interval)
        )

    def test_recent_listing_skips_detail_refresh(self):
        listing = {
            "is_active": 1,
            "last_detail_at": (self.now - timedelta(minutes=20)).isoformat(),
        }

        self.assertFalse(
            should_refresh_detail(listing, self.now, self.detail_interval)
        )

    def test_stale_listing_refreshes_detail(self):
        listing = {
            "is_active": 1,
            "last_detail_at": (self.now - timedelta(hours=8)).isoformat(),
        }

        self.assertTrue(
            should_refresh_detail(listing, self.now, self.detail_interval)
        )

    def test_detail_refreshes_at_exact_threshold(self):
        listing = {
            "is_active": 1,
            "last_detail_at": (self.now - self.detail_interval).isoformat(),
        }

        self.assertTrue(
            should_refresh_detail(listing, self.now, self.detail_interval)
        )

    def test_recent_missing_listing_skips_status_check(self):
        listing = {
            "last_checked_at": (self.now - timedelta(hours=2)).isoformat()
        }

        self.assertFalse(
            should_check_status(listing, self.now, self.status_interval)
        )

    def test_stale_missing_listing_gets_status_check(self):
        listing = {
            "last_checked_at": (self.now - timedelta(hours=25)).isoformat()
        }

        self.assertTrue(
            should_check_status(listing, self.now, self.status_interval)
        )

    def test_naive_current_time_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            should_refresh_detail(
                {"last_detail_at": self.now.isoformat()},
                self.now.replace(tzinfo=None),
                self.detail_interval,
            )


if __name__ == "__main__":
    unittest.main()
