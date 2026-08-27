from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic


def _duration_text(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))


@dataclass
class ScrapeRunSummary:
    search_name: str
    pages_requested: int
    started_at: float = field(default_factory=monotonic)
    pages_fetched: int = 0
    search_requests: int = 0
    detail_requests: int = 0
    status_requests: int = 0
    retry_requests: int = 0
    listings_discovered: int = 0
    new_listings: int = 0
    missing_active_candidates: int = 0
    skipped_recent_details: int = 0
    skipped_recent_status_checks: int = 0
    details_succeeded: int = 0
    confirmed_inactive: int = 0
    blocking_failures: int = 0
    stopped_reason: str | None = None
    failures: Counter[str] = field(default_factory=Counter)

    def elapsed_seconds(self) -> float:
        return max(0.0, monotonic() - self.started_at)

    def add_failure(self, category: str) -> None:
        self.failures[category] += 1

    def format(self) -> str:
        failure_lines = (
            [f"  {category}: {count}" for category, count in sorted(self.failures.items())]
            or ["  none"]
        )
        return "\n".join(
            [
                "Run completed",
                f"Search: {self.search_name}",
                f"Pages requested: {self.pages_requested}",
                f"Pages fetched: {self.pages_fetched}",
                f"Search requests: {self.search_requests}",
                f"Detail requests: {self.detail_requests}",
                f"Status requests: {self.status_requests}",
                f"Retry requests: {self.retry_requests}",
                f"Listings discovered: {self.listings_discovered}",
                f"New listings: {self.new_listings}",
                f"Missing active candidates: {self.missing_active_candidates}",
                f"Skipped recent details: {self.skipped_recent_details}",
                f"Skipped recent status checks: {self.skipped_recent_status_checks}",
                f"Details succeeded: {self.details_succeeded}",
                f"Confirmed inactive: {self.confirmed_inactive}",
                f"Blocking failures: {self.blocking_failures}",
                f"Stopped reason: {self.stopped_reason or 'none'}",
                "Failures:",
                *failure_lines,
                f"Duration: {_duration_text(self.elapsed_seconds())}",
            ]
        )


@dataclass
class ActiveCheckSummary:
    requested: int
    started_at: float = field(default_factory=monotonic)
    active: int = 0
    inactive: int = 0
    unknown: int = 0
    status_requests: int = 0
    retry_requests: int = 0
    blocking_failures: int = 0
    stopped_reason: str | None = None
    failures: Counter[str] = field(default_factory=Counter)

    def add_failure(self, category: str) -> None:
        self.failures[category] += 1

    def format(self) -> str:
        failure_lines = (
            [f"  {category}: {count}" for category, count in sorted(self.failures.items())]
            or ["  none"]
        )
        return "\n".join(
            [
                "Active check completed",
                f"Listings requested: {self.requested}",
                f"Status requests: {self.status_requests}",
                f"Retry requests: {self.retry_requests}",
                f"Confirmed active: {self.active}",
                f"Confirmed inactive: {self.inactive}",
                f"Unknown: {self.unknown}",
                f"Blocking failures: {self.blocking_failures}",
                f"Stopped reason: {self.stopped_reason or 'none'}",
                "Failures:",
                *failure_lines,
                f"Duration: {_duration_text(monotonic() - self.started_at)}",
            ]
        )
