import unittest

from scrapers.circuit_breaker import BlockingCircuitBreaker
from scrapers.failures import FailureCategory, FetchFailure


def failure(category: FailureCategory) -> FetchFailure:
    return FetchFailure(category, category.value, retryable=False)


class BlockingCircuitBreakerTests(unittest.TestCase):
    def test_isolated_blocking_failure_does_not_open(self):
        breaker = BlockingCircuitBreaker(threshold=3)

        opened = breaker.record_failure(failure(FailureCategory.ANTI_BOT_SUSPECTED))

        self.assertFalse(opened)
        self.assertFalse(breaker.is_open)
        self.assertEqual(breaker.consecutive_failures, 1)

    def test_threshold_consecutive_blocking_failures_opens(self):
        breaker = BlockingCircuitBreaker(threshold=2)

        breaker.record_failure(failure(FailureCategory.RATE_LIMITED))
        opened = breaker.record_failure(failure(FailureCategory.IP_BLOCKED))

        self.assertTrue(opened)
        self.assertTrue(breaker.is_open)
        with self.assertRaisesRegex(RuntimeError, "open"):
            breaker.ensure_closed()

    def test_success_resets_consecutive_blocking_failures(self):
        breaker = BlockingCircuitBreaker(threshold=2)
        breaker.record_failure(failure(FailureCategory.ANTI_BOT_SUSPECTED))

        breaker.record_success()
        opened = breaker.record_failure(failure(FailureCategory.RATE_LIMITED))

        self.assertFalse(opened)
        self.assertEqual(breaker.consecutive_failures, 1)
        self.assertEqual(breaker.blocking_failures, 2)

    def test_non_blocking_failure_resets_consecutive_sequence(self):
        breaker = BlockingCircuitBreaker(threshold=2)
        breaker.record_failure(failure(FailureCategory.ANTI_BOT_SUSPECTED))

        breaker.record_failure(failure(FailureCategory.HTTP_SERVER_ERROR))

        self.assertEqual(breaker.consecutive_failures, 0)
        self.assertFalse(breaker.is_open)


if __name__ == "__main__":
    unittest.main()
