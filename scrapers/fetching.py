import logging
import re
import time
from collections.abc import Callable

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from models.runtime_config import RuntimeConfig
from scrapers.circuit_breaker import BlockingCircuitBreaker, CircuitOpenError
from scrapers.failures import FailureCategory, FetchFailure, FetchResult


ANTI_BOT_MARKERS = (
    "captcha",
    "recaptcha",
    "access denied",
    "sicherheitsüberprüfung",
    "ungewöhnliche aktivität",
    "verify you are human",
)
IP_BLOCK_MARKERS = (
    "ip-bereich vorübergehend gesperrt",
    "ip-bereich gesperrt",
)
TRANSIENT_CLIENT_STATUSES = {408, 425}
INACTIVE_STATUSES = {404, 410}
INTERSTITIAL_TITLE_MARKERS = (
    "consent",
    "cookie settings",
    "datenschutzeinstellungen",
    "privacy settings",
    "challenge",
)


def detect_anti_bot_page(html: str) -> bool:
    text = html.casefold()
    return any(marker in text for marker in ANTI_BOT_MARKERS)


def detect_ip_blocked_page(html: str) -> bool:
    text = html.casefold()
    return any(marker in text for marker in IP_BLOCK_MARKERS)


def detect_interstitial_page(html: str) -> bool:
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
    )
    if not title_match:
        return False
    title = re.sub(r"\s+", " ", title_match.group(1)).casefold()
    return any(marker in title for marker in INTERSTITIAL_TITLE_MARKERS)


def detect_challenge_page(html: str) -> bool:
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
    )
    if not title_match:
        return False
    title = re.sub(r"\s+", " ", title_match.group(1)).casefold()
    return "challenge" in title


def _context_text(context: dict[str, object] | None) -> str:
    if not context:
        return ""
    return " ".join(f"{key}={value}" for key, value in context.items()) + " "


def _classify_playwright_error(error: PlaywrightError) -> FetchFailure:
    message = str(error)
    if "invalid url" in message.casefold() or "cannot navigate" in message.casefold():
        return FetchFailure(
            FailureCategory.HTTP_CLIENT_ERROR,
            message,
            retryable=False,
        )
    return FetchFailure(
        FailureCategory.NETWORK_ERROR,
        message,
        retryable=True,
    )


def navigate_with_retry(
    page: Page,
    url: str,
    runtime_config: RuntimeConfig,
    *,
    logger: logging.Logger,
    context: dict[str, object] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    circuit_breaker: BlockingCircuitBreaker | None = None,
) -> FetchResult:
    prefix = _context_text(context)

    for attempt in range(1, runtime_config.max_attempts + 1):
        if circuit_breaker:
            circuit_breaker.ensure_closed()
        failure: FetchFailure | None = None
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=runtime_config.navigation_timeout_ms,
            )
            if response is None:
                raise FetchFailure(
                    FailureCategory.NETWORK_ERROR,
                    "navigation returned no response",
                    retryable=True,
                )

            status_code = response.status
            if status_code in INACTIVE_STATUSES:
                if circuit_breaker:
                    circuit_breaker.record_success()
                return FetchResult(page.content(), status_code, attempt)
            if status_code == 403:
                raise FetchFailure(
                    FailureCategory.ANTI_BOT_SUSPECTED,
                    "HTTP 403 may indicate blocking",
                    retryable=False,
                    status_code=status_code,
                )
            if status_code == 429:
                raise FetchFailure(
                    FailureCategory.RATE_LIMITED,
                    "HTTP 429 rate limit response",
                    retryable=True,
                    status_code=status_code,
                )
            if status_code in TRANSIENT_CLIENT_STATUSES:
                raise FetchFailure(
                    FailureCategory.HTTP_CLIENT_ERROR,
                    f"transient HTTP client response {status_code}",
                    retryable=True,
                    status_code=status_code,
                )
            if 400 <= status_code < 500:
                raise FetchFailure(
                    FailureCategory.HTTP_CLIENT_ERROR,
                    f"HTTP client response {status_code}",
                    retryable=False,
                    status_code=status_code,
                )
            if status_code >= 500:
                raise FetchFailure(
                    FailureCategory.HTTP_SERVER_ERROR,
                    f"HTTP server response {status_code}",
                    retryable=True,
                    status_code=status_code,
                )

            if runtime_config.page_settle_delay_ms:
                page.wait_for_timeout(runtime_config.page_settle_delay_ms)
            html = page.content()
            if not html.strip():
                raise FetchFailure(
                    FailureCategory.UNEXPECTED_PAGE,
                    "retrieved page content is empty",
                    retryable=False,
                    status_code=status_code,
                )
            if detect_ip_blocked_page(html):
                raise FetchFailure(
                    FailureCategory.IP_BLOCKED,
                    "IP range is temporarily blocked",
                    retryable=False,
                    status_code=status_code,
                )
            if detect_anti_bot_page(html):
                raise FetchFailure(
                    FailureCategory.ANTI_BOT_SUSPECTED,
                    "challenge or anti-bot content detected",
                    retryable=False,
                    status_code=status_code,
                )
            if detect_challenge_page(html):
                raise FetchFailure(
                    FailureCategory.ANTI_BOT_SUSPECTED,
                    "challenge page detected",
                    retryable=False,
                    status_code=status_code,
                )
            if detect_interstitial_page(html):
                raise FetchFailure(
                    FailureCategory.UNEXPECTED_PAGE,
                    "consent or interstitial page detected",
                    retryable=False,
                    status_code=status_code,
                )
            if attempt > 1:
                logger.info(
                    "%surl=%s retry_succeeded=true attempt=%s/%s",
                    prefix,
                    url,
                    attempt,
                    runtime_config.max_attempts,
                )
            if circuit_breaker:
                circuit_breaker.record_success()
            return FetchResult(html, status_code, attempt)
        except PlaywrightTimeoutError as exc:
            failure = FetchFailure(
                FailureCategory.TIMEOUT,
                str(exc) or "navigation timed out",
                retryable=True,
            )
        except FetchFailure as exc:
            failure = exc
        except PlaywrightError as exc:
            failure = _classify_playwright_error(exc)
        except Exception as exc:
            failure = FetchFailure(
                FailureCategory.UNKNOWN_ERROR,
                str(exc) or exc.__class__.__name__,
                retryable=False,
            )

        failure.attempts = attempt
        if circuit_breaker and circuit_breaker.record_failure(failure):
            raise CircuitOpenError(failure)

        if not failure.retryable or attempt >= runtime_config.max_attempts:
            raise failure

        delay = runtime_config.retry_base_delay_seconds * (2 ** (attempt - 1))
        logger.warning(
            "%surl=%s failure=%s attempt=%s/%s retry_in_seconds=%s message=%s",
            prefix,
            url,
            failure.category.value,
            attempt,
            runtime_config.max_attempts,
            delay,
            failure,
        )
        sleep(delay)

    raise AssertionError("retry loop exited unexpectedly")
