import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class MainCliTests(unittest.TestCase):
    def test_list_searches(self):
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main.main(["--list-searches"])

        self.assertEqual(exit_code, 0)
        self.assertIn("bmw_320d_nrw (enabled)", output.getvalue())

    def test_default_selects_first_enabled_search(self):
        with patch("main.configure_logging"), patch("main.ProcessLock"), patch(
            "main.graceful_shutdown_signals"
        ), patch("scrapers.kleinanzeigen_scraper.run") as run:
            exit_code = main.main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_args.args[0].name, "bmw_320d_nrw")

    def test_named_search_is_selected(self):
        with patch("main.configure_logging"), patch("main.ProcessLock"), patch(
            "main.graceful_shutdown_signals"
        ), patch("scrapers.kleinanzeigen_scraper.run") as run:
            exit_code = main.main(["--search", "bmw_320d_nrw"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(run.call_args.args[0].name, "bmw_320d_nrw")

    def test_fatal_scraper_failure_returns_nonzero(self):
        with patch("storage.sqlite.record_collector_run"), patch("main.configure_logging") as configure_logging, patch(
            "main.ProcessLock"
        ), patch("main.graceful_shutdown_signals"), patch(
            "scrapers.kleinanzeigen_scraper.run", side_effect=RuntimeError("boom")
        ):
            exit_code = main.main([])

        self.assertEqual(exit_code, 1)
        configure_logging.return_value.exception.assert_called_once()


if __name__ == "__main__":
    unittest.main()
