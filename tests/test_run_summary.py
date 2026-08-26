import unittest

from models.run_summary import ScrapeRunSummary


class RunSummaryTests(unittest.TestCase):
    def test_request_skip_and_blocking_metrics_are_visible(self):
        summary = ScrapeRunSummary("test", 20)
        summary.search_requests = 20
        summary.detail_requests = 4
        summary.status_requests = 2
        summary.retry_requests = 1
        summary.skipped_recent_details = 450
        summary.skipped_recent_status_checks = 300
        summary.blocking_failures = 3
        summary.stopped_reason = "BLOCKING_SUSPECTED"

        text = summary.format()

        self.assertIn("Search requests: 20", text)
        self.assertIn("Detail requests: 4", text)
        self.assertIn("Status requests: 2", text)
        self.assertIn("Retry requests: 1", text)
        self.assertIn("Skipped recent details: 450", text)
        self.assertIn("Skipped recent status checks: 300", text)
        self.assertIn("Blocking failures: 3", text)
        self.assertIn("Stopped reason: BLOCKING_SUSPECTED", text)


if __name__ == "__main__":
    unittest.main()
