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
    listings_discovered: int = 0
    prior_active_added: int = 0
    details_succeeded: int = 0
    confirmed_inactive: int = 0
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
                "Run completed",
                f"Search: {self.search_name}",
                f"Pages requested: {self.pages_requested}",
                f"Pages fetched: {self.pages_fetched}",
                f"Listings discovered: {self.listings_discovered}",
                f"Prior active listings added: {self.prior_active_added}",
                f"Details succeeded: {self.details_succeeded}",
                f"Confirmed inactive: {self.confirmed_inactive}",
                "Failures:",
                *failure_lines,
                f"Duration: {_duration_text(monotonic() - self.started_at)}",
            ]
        )


@dataclass
class ActiveCheckSummary:
    requested: int
    started_at: float = field(default_factory=monotonic)
    active: int = 0
    inactive: int = 0
    unknown: int = 0
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
                f"Confirmed active: {self.active}",
                f"Confirmed inactive: {self.inactive}",
                f"Unknown: {self.unknown}",
                "Failures:",
                *failure_lines,
                f"Duration: {_duration_text(monotonic() - self.started_at)}",
            ]
        )
