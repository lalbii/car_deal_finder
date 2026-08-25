import unittest
from unittest.mock import patch

import check_active
from models.runtime_config import RuntimeConfig


class ActiveCheckCliTests(unittest.TestCase):
    @patch("check_active.graceful_shutdown_signals")
    @patch("check_active.ProcessLock")
    @patch("check_active.configure_logging")
    @patch("check_active.load_runtime_config", return_value=RuntimeConfig())
    @patch("scrapers.active_checker.run_active_check")
    def test_limit_is_forwarded(
        self,
        run_active_check,
        load_runtime_config,
        configure_logging,
        process_lock,
        graceful_shutdown_signals,
    ):
        exit_code = check_active.main(["--limit", "10"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(run_active_check.call_args.kwargs["limit"], 10)

    def test_limit_must_be_positive(self):
        with self.assertRaises(SystemExit) as raised:
            check_active.main(["--limit", "0"])
        self.assertEqual(raised.exception.code, 2)

    @patch("check_active.graceful_shutdown_signals")
    @patch("check_active.ProcessLock")
    @patch("check_active.configure_logging")
    @patch("check_active.load_runtime_config", return_value=RuntimeConfig())
    @patch("scrapers.active_checker.run_active_check")
    def test_default_checks_all_active_listings(
        self,
        run_active_check,
        load_runtime_config,
        configure_logging,
        process_lock,
        graceful_shutdown_signals,
    ):
        exit_code = check_active.main([])

        self.assertEqual(exit_code, 0)
        self.assertIsNone(run_active_check.call_args.kwargs["limit"])


if __name__ == "__main__":
    unittest.main()
