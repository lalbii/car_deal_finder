from dataclasses import dataclass

from scrapers.failures import FailureCategory, FetchFailure


BLOCKING_FAILURE_CATEGORIES = {
    FailureCategory.ANTI_BOT_SUSPECTED,
    FailureCategory.IP_BLOCKED,
    FailureCategory.RATE_LIMITED,
}


class CircuitOpenError(RuntimeError):
    def __init__(self, failure: FetchFailure) -> None:
        super().__init__("blocking failure threshold reached")
        self.failure = failure


@dataclass
class BlockingCircuitBreaker:
    threshold: int
    consecutive_failures: int = 0
    blocking_failures: int = 0
    is_open: bool = False

    def __post_init__(self) -> None:
        if self.threshold < 1:
            raise ValueError("Circuit-breaker threshold must be at least one")

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self, failure: FetchFailure) -> bool:
        if failure.category not in BLOCKING_FAILURE_CATEGORIES:
            self.consecutive_failures = 0
            return False

        self.blocking_failures += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.is_open = True
        return self.is_open

    def ensure_closed(self) -> None:
        if self.is_open:
            raise RuntimeError("circuit breaker is open")
