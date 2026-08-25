import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from config.search_loader import load_runtime_config
from models.runtime_config import RuntimeConfig
from scrapers.browser import launch_browser


class RuntimeConfigTests(unittest.TestCase):
    def write_config(self, runtime: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "searches.yaml"
        path.write_text(
            """
searches:
  test:
    query: test
    region: region
    category: category
    max_pages: 1
runtime:
"""
            + runtime,
            encoding="utf-8",
        )
        return path

    def test_browser_channel_loads_and_controls_browser_launch(self):
        config = load_runtime_config(
            self.write_config("  headless: true\n  browser_channel: chrome\n")
        )
        playwright = Mock()

        launch_browser(playwright, config)

        playwright.chromium.launch.assert_called_once_with(
            headless=True,
            channel="chrome",
        )

    def test_no_browser_channel_uses_playwright_managed_chromium(self):
        config = load_runtime_config(self.write_config("  headless: false\n"))
        playwright = Mock()

        launch_browser(playwright, config)

        self.assertIsNone(config.browser_channel)
        playwright.chromium.launch.assert_called_once_with(headless=False)

    def test_null_or_empty_browser_channel_uses_playwright_managed_chromium(self):
        for value in ("null", '"   "'):
            with self.subTest(value=value):
                config = load_runtime_config(
                    self.write_config(f"  browser_channel: {value}\n")
                )
                playwright = Mock()

                launch_browser(playwright, config)

                self.assertIsNone(config.browser_channel)
                playwright.chromium.launch.assert_called_once_with(headless=True)

    def test_browser_channel_rejects_non_string_values(self):
        with self.assertRaisesRegex(ValueError, "must be a string or null"):
            load_runtime_config(self.write_config("  browser_channel: 123\n"))

    def test_navigation_timeout_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            load_runtime_config(
                self.write_config("  navigation_timeout_seconds: 0\n")
            )

    def test_retry_count_is_bounded_and_non_negative(self):
        for retries in (-1, 11):
            with self.subTest(retries=retries):
                with self.assertRaisesRegex(ValueError, "between 0 and 10"):
                    RuntimeConfig(max_retries=retries)


if __name__ == "__main__":
    unittest.main()
