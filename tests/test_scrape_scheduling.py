import logging
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from models.runtime_config import RuntimeConfig
from models.search_config import SearchConfig
from scrapers.failures import FetchResult
from scrapers.kleinanzeigen_scraper import run


FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status: int):
        self.status = status


class BlockingPage:
    def __init__(self, statuses: list[int]):
        self.statuses = list(statuses)
        self.goto_calls = 0

    def set_default_navigation_timeout(self, timeout):
        self.timeout = timeout

    def goto(self, url, **kwargs):
        self.goto_calls += 1
        return FakeResponse(self.statuses.pop(0))


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class ScrapeSchedulingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        self.search_config = SearchConfig(
            name="test_search",
            query="bmw-320d",
            region="nordrhein-westfalen",
            category="k0c216l928",
            max_pages=1,
        )
        self.runtime = RuntimeConfig(
            page_settle_delay_seconds=0,
            detail_delay_seconds=0,
            max_retries=0,
        )
        self.search_html = (FIXTURES / "search_page.html").read_text(
            encoding="utf-8"
        )
        self.detail_html = (FIXTURES / "detail_page.html").read_text(
            encoding="utf-8"
        )
        self.logger = logging.getLogger("test.scrape_scheduling")

    def _browser_patches(self, stack: ExitStack, browser: object | None = None):
        playwright = Mock()
        sync_playwright = stack.enter_context(
            patch("scrapers.kleinanzeigen_scraper.sync_playwright")
        )
        sync_playwright.return_value.__enter__.return_value = playwright
        if browser is None:
            browser = Mock()
        stack.enter_context(
            patch("scrapers.kleinanzeigen_scraper.launch_browser", return_value=browser)
        )
        return browser

    def _common_patches(self, stack: ExitStack, known_listings: list[dict]):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        stack.enter_context(
            patch("scrapers.kleinanzeigen_scraper.DATA_DIR", Path(temp_dir.name))
        )
        stack.enter_context(patch("scrapers.kleinanzeigen_scraper.init_db"))
        stack.enter_context(
            patch(
                "scrapers.kleinanzeigen_scraper.get_known_listings",
                return_value=known_listings,
            )
        )
        stack.enter_context(patch("scrapers.kleinanzeigen_scraper._export_results"))

    def test_recent_known_search_result_updates_presence_without_detail_or_history(self):
        known = {
            "listing_id": "1234567890",
            "url": "https://example.test/1234567890",
            "is_active": 1,
            "last_detail_at": (self.now - timedelta(hours=1)).isoformat(),
            "last_checked_at": (self.now - timedelta(hours=1)).isoformat(),
        }
        with ExitStack() as stack:
            self._common_patches(stack, [known])
            self._browser_patches(stack)
            fetch_search = stack.enter_context(
                patch(
                    "scrapers.kleinanzeigen_scraper.fetch_search_page",
                    return_value=FetchResult(self.search_html, 200, 1),
                )
            )
            fetch_detail = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.fetch_detail_page")
            )
            mark_seen = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.mark_listings_seen")
            )
            upsert = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.upsert_listing")
            )
            history = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.insert_listing_history")
            )

            summary = run(
                self.search_config,
                self.runtime,
                logger=self.logger,
                now=self.now,
            )

        self.assertEqual(fetch_search.call_count, 1)
        fetch_detail.assert_not_called()
        mark_seen.assert_called_once_with({"1234567890"}, seen_at=self.now)
        upsert.assert_not_called()
        history.assert_not_called()
        self.assertEqual(summary.search_requests, 1)
        self.assertEqual(summary.detail_requests, 0)
        self.assertEqual(summary.skipped_recent_details, 1)

    def test_new_listing_fetches_detail_and_writes_one_history_observation(self):
        with ExitStack() as stack:
            self._common_patches(stack, [])
            self._browser_patches(stack)
            stack.enter_context(
                patch(
                    "scrapers.kleinanzeigen_scraper.fetch_search_page",
                    return_value=FetchResult(self.search_html, 200, 1),
                )
            )
            fetch_detail = stack.enter_context(
                patch(
                    "scrapers.kleinanzeigen_scraper.fetch_detail_page",
                    return_value=FetchResult(self.detail_html, 200, 1),
                )
            )
            upsert = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.upsert_listing")
            )
            history = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.insert_listing_history")
            )

            summary = run(
                self.search_config,
                self.runtime,
                logger=self.logger,
                now=self.now,
            )

        fetch_detail.assert_called_once()
        upsert.assert_called_once()
        history.assert_called_once()
        self.assertEqual(summary.new_listings, 1)
        self.assertEqual(summary.detail_requests, 1)
        self.assertEqual(summary.details_succeeded, 1)

    def test_recent_missing_listing_skips_status_request(self):
        known = {
            "listing_id": "missing",
            "url": "https://example.test/missing",
            "is_active": 1,
            "last_detail_at": (self.now - timedelta(hours=1)).isoformat(),
            "last_checked_at": (self.now - timedelta(hours=1)).isoformat(),
        }
        empty_search = "<html><p>Keine Anzeigen gefunden</p></html>"
        with ExitStack() as stack:
            self._common_patches(stack, [known])
            self._browser_patches(stack)
            stack.enter_context(
                patch(
                    "scrapers.kleinanzeigen_scraper.fetch_search_page",
                    return_value=FetchResult(empty_search, 200, 1),
                )
            )
            fetch_detail = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.fetch_detail_page")
            )

            summary = run(
                self.search_config,
                self.runtime,
                logger=self.logger,
                now=self.now,
            )

        fetch_detail.assert_not_called()
        self.assertEqual(summary.missing_active_candidates, 1)
        self.assertEqual(summary.status_requests, 0)
        self.assertEqual(summary.skipped_recent_status_checks, 1)

    def test_circuit_open_stops_search_and_does_not_modify_lifecycle(self):
        search_config = SearchConfig(
            name="test_search",
            query="bmw-320d",
            region="nordrhein-westfalen",
            category="k0c216l928",
            max_pages=3,
        )
        runtime = RuntimeConfig(
            page_settle_delay_seconds=0,
            detail_delay_seconds=0,
            max_retries=0,
            blocking_failure_threshold=2,
        )
        page = BlockingPage([403, 403, 200])
        browser = FakeBrowser(page)
        known = {
            "listing_id": "existing",
            "url": "https://example.test/existing",
            "is_active": 1,
            "last_detail_at": (self.now - timedelta(days=2)).isoformat(),
            "last_checked_at": (self.now - timedelta(days=2)).isoformat(),
        }
        with ExitStack() as stack:
            self._common_patches(stack, [known])
            self._browser_patches(stack, browser)
            fetch_detail = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.fetch_detail_page")
            )
            mark_inactive = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.mark_listing_inactive")
            )
            mark_checked = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.mark_listing_checked")
            )
            upsert = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.upsert_listing")
            )
            history = stack.enter_context(
                patch("scrapers.kleinanzeigen_scraper.insert_listing_history")
            )

            summary = run(
                search_config,
                runtime,
                logger=self.logger,
                now=self.now,
            )

        self.assertEqual(page.goto_calls, 2)
        self.assertTrue(browser.closed)
        fetch_detail.assert_not_called()
        mark_inactive.assert_not_called()
        mark_checked.assert_not_called()
        upsert.assert_not_called()
        history.assert_not_called()
        self.assertEqual(summary.search_requests, 2)
        self.assertEqual(summary.blocking_failures, 2)
        self.assertEqual(summary.stopped_reason, "BLOCKING_SUSPECTED")


if __name__ == "__main__":
    unittest.main()
