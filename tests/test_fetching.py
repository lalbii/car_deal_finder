import logging
import unittest

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from models.runtime_config import RuntimeConfig
from scrapers.circuit_breaker import BlockingCircuitBreaker, CircuitOpenError
from scrapers.failures import FailureCategory, FetchFailure
from scrapers.fetching import navigate_with_retry


class FakeResponse:
    def __init__(self, status: int):
        self.status = status


class FakePage:
    def __init__(self, outcomes, html="<html><h1>BMW 320d</h1></html>"):
        self.outcomes = list(outcomes)
        self.html = html
        self.goto_calls = 0
        self.waits = []

    def goto(self, url, **kwargs):
        self.goto_calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)

    def wait_for_timeout(self, milliseconds):
        self.waits.append(milliseconds)

    def content(self):
        return self.html


class FetchRetryTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("test.fetching")
        self.runtime = RuntimeConfig(
            page_settle_delay_seconds=0,
            max_retries=2,
            retry_base_delay_seconds=1,
        )

    def test_timeout_retries_then_succeeds_without_real_sleep(self):
        page = FakePage(
            [
                PlaywrightTimeoutError("timeout one"),
                PlaywrightTimeoutError("timeout two"),
                200,
            ]
        )
        sleeps = []

        result = navigate_with_retry(
            page,
            "https://example.test/listing",
            self.runtime,
            logger=self.logger,
            sleep=sleeps.append,
        )

        self.assertEqual(result.attempts, 3)
        self.assertEqual(page.goto_calls, 3)
        self.assertEqual(sleeps, [1, 2])

    def test_server_errors_stop_at_configured_limit(self):
        page = FakePage([503, 503, 503])
        sleeps = []

        with self.assertRaises(FetchFailure) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=sleeps.append,
            )

        self.assertEqual(raised.exception.category, FailureCategory.HTTP_SERVER_ERROR)
        self.assertEqual(page.goto_calls, 3)
        self.assertEqual(sleeps, [1, 2])

    def test_confirmed_not_found_is_not_retried(self):
        page = FakePage([404])
        sleeps = []

        result = navigate_with_retry(
            page,
            "https://example.test/listing",
            self.runtime,
            logger=self.logger,
            sleep=sleeps.append,
        )

        self.assertEqual(result.status_code, 404)
        self.assertEqual(page.goto_calls, 1)
        self.assertEqual(sleeps, [])

    def test_challenge_page_is_classified_without_retry(self):
        page = FakePage([200], html="<html><title>Captcha</title></html>")

        with self.assertRaises(FetchFailure) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=lambda delay: self.fail("challenge response should not retry"),
            )

        self.assertEqual(
            raised.exception.category, FailureCategory.ANTI_BOT_SUSPECTED
        )

    def test_consent_interstitial_is_uncertain_and_not_retried(self):
        page = FakePage(
            [200],
            html="<html><title>Privacy settings consent</title></html>",
        )

        with self.assertRaises(FetchFailure) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=lambda delay: self.fail("interstitial should not retry"),
            )

        self.assertEqual(raised.exception.category, FailureCategory.UNEXPECTED_PAGE)

    def test_unexpected_navigation_error_is_classified(self):
        page = FakePage([RuntimeError("unexpected browser state")])

        with self.assertRaises(FetchFailure) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=lambda delay: self.fail("unknown error should not retry"),
            )

        self.assertEqual(raised.exception.category, FailureCategory.UNKNOWN_ERROR)

    def test_ip_block_page_is_explicitly_classified(self):
        page = FakePage(
            [200],
            html="<html><h1>IP-Bereich vorübergehend gesperrt.</h1></html>",
        )

        with self.assertRaises(FetchFailure) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=lambda delay: self.fail("IP block should not retry"),
            )

        self.assertEqual(raised.exception.category, FailureCategory.IP_BLOCKED)

    def test_rate_limit_attempts_open_circuit_at_threshold(self):
        page = FakePage([429, 429, 429])
        breaker = BlockingCircuitBreaker(threshold=3)
        sleeps = []

        with self.assertRaises(CircuitOpenError) as raised:
            navigate_with_retry(
                page,
                "https://example.test/listing",
                self.runtime,
                logger=self.logger,
                sleep=sleeps.append,
                circuit_breaker=breaker,
            )

        self.assertEqual(raised.exception.failure.category, FailureCategory.RATE_LIMITED)
        self.assertEqual(raised.exception.failure.attempts, 3)
        self.assertEqual(page.goto_calls, 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertTrue(breaker.is_open)


if __name__ == "__main__":
    unittest.main()
