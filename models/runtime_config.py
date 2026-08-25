from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeConfig:
    """Small set of operational controls shared by scraper commands."""

    headless: bool = True
    navigation_timeout_seconds: float = 30.0
    page_settle_delay_seconds: float = 3.0
    detail_delay_seconds: float = 1.0
    max_retries: int = 2
    retry_base_delay_seconds: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.headless, bool):
            raise ValueError("Runtime configuration 'headless' must be true or false")

        self._validate_positive("navigation_timeout_seconds")
        self._validate_non_negative("page_settle_delay_seconds")
        self._validate_non_negative("detail_delay_seconds")
        self._validate_non_negative("retry_base_delay_seconds")

        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int):
            raise ValueError("Runtime configuration 'max_retries' must be an integer")
        if not 0 <= self.max_retries <= 10:
            raise ValueError("Runtime configuration 'max_retries' must be between 0 and 10")

    def _validate_positive(self, field_name: str) -> None:
        value = getattr(self, field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(
                f"Runtime configuration {field_name!r} must be greater than zero"
            )

    def _validate_non_negative(self, field_name: str) -> None:
        value = getattr(self, field_name)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(
                f"Runtime configuration {field_name!r} must be zero or greater"
            )

    @property
    def navigation_timeout_ms(self) -> float:
        return self.navigation_timeout_seconds * 1000

    @property
    def page_settle_delay_ms(self) -> float:
        return self.page_settle_delay_seconds * 1000

    @property
    def max_attempts(self) -> int:
        return self.max_retries + 1
