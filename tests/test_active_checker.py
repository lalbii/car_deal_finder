import logging
import unittest
from unittest.mock import Mock, patch

from models.runtime_config import RuntimeConfig
from scrapers.active_checker import run_active_check
from scrapers.failures import FailureCategory, FetchFailure


DETAIL_URL = "https://www.kleinanzeigen.de/s-anzeige/bmw-320d/123-216-1234"


class ActiveCheckerSafetyTests(unittest.TestCase):
    @patch("scrapers.active_checker.mark_listing_inactive")
    @patch("scrapers.active_checker.mark_listing_checked")
    @patch("scrapers.active_checker.fetch_detail_page")
    @patch("scrapers.active_checker.launch_browser")
    @patch("scrapers.active_checker.sync_playwright")
    @patch("scrapers.active_checker.get_active_listings")
    def test_network_and_timeout_failures_leave_database_state_unchanged(
        self,
        get_active_listings,
        sync_playwright,
        launch_browser,
        fetch_detail_page,
        mark_listing_checked,
        mark_listing_inactive,
    ):
        get_active_listings.return_value = [
            {"listing_id": "123", "url": DETAIL_URL}
        ]
        playwright = Mock()
        sync_playwright.return_value.__enter__.return_value = playwright
        browser = Mock()
        launch_browser.return_value = browser
        for category in (FailureCategory.NETWORK_ERROR, FailureCategory.TIMEOUT):
            with self.subTest(category=category):
                fetch_detail_page.side_effect = FetchFailure(
                    category,
                    "transient failure",
                    retryable=True,
                )
                summary = run_active_check(
                    RuntimeConfig(detail_delay_seconds=0),
                    logger=logging.getLogger("test.active_checker"),
                    sleep=lambda delay: None,
                )
                self.assertEqual(summary.unknown, 1)

        mark_listing_checked.assert_not_called()
        mark_listing_inactive.assert_not_called()
        self.assertEqual(browser.close.call_count, 2)


if __name__ == "__main__":
    unittest.main()
