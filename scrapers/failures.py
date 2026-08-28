from dataclasses import dataclass
from enum import Enum


class FailureCategory(str, Enum):
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    HTTP_CLIENT_ERROR = "HTTP_CLIENT_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_SERVER_ERROR = "HTTP_SERVER_ERROR"
    PARSER_ERROR = "PARSER_ERROR"
    ANTI_BOT_SUSPECTED = "ANTI_BOT_SUSPECTED"
    IP_BLOCKED = "IP_BLOCKED"
    UNEXPECTED_PAGE = "UNEXPECTED_PAGE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass(frozen=True)
class FetchResult:
    html: str
    status_code: int
    attempts: int
    final_url: str | None = None


class FetchFailure(RuntimeError):
    def __init__(
        self,
        category: FailureCategory,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        attempts: int = 1,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts
