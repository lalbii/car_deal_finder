import logging
import time
from collections.abc import Callable

from playwright.sync_api import sync_playwright

from models.run_summary import ActiveCheckSummary
from models.runtime_config import RuntimeConfig
from operations.logging_config import get_logger
from parsers.status_parser import (
    ListingStatus,
    interpret_listing_status,
    is_listing_detail_url,
)
from scrapers.browser import launch_browser
from scrapers.circuit_breaker import BlockingCircuitBreaker, CircuitOpenError
from scrapers.failures import FailureCategory, FetchFailure
from scrapers.kleinanzeigen_detail import fetch_detail_page
from storage.sqlite import (
    get_active_listings,
    mark_listing_checked,
    mark_listing_inactive,
)


def run_active_check(
    runtime_config: RuntimeConfig,
    limit: int | None = None,
    *,
    logger: logging.Logger | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ActiveCheckSummary:
    logger = logger or get_logger("active_checker")
    active_listings = get_active_listings(limit=limit)
    summary = ActiveCheckSummary(requested=len(active_listings))
    breaker = BlockingCircuitBreaker(runtime_config.blocking_failure_threshold)
    logger.info("active_check_start=true listings=%s limit=%s", len(active_listings), limit)
    if not active_listings:
        logger.info("%s", summary.format())
        return summary

    with sync_playwright() as playwright:
        browser = launch_browser(playwright, runtime_config)
        try:
            page = browser.new_page()
            page.set_default_navigation_timeout(runtime_config.navigation_timeout_ms)

            for index, listing in enumerate(active_listings, start=1):
                listing_id = listing["listing_id"]
                url = listing["url"]
                if not is_listing_detail_url(url, listing_id):
                    summary.unknown += 1
                    summary.add_failure(FailureCategory.UNEXPECTED_PAGE.value)
                    logger.warning(
                        "listing_id=%s url=%s status=UNKNOWN "
                        "reason=invalid_listing_detail_url database_unchanged=true",
                        listing_id,
                        url,
                    )
                    continue
                if index > 1 and runtime_config.detail_delay_seconds:
                    sleep(runtime_config.detail_delay_seconds)
                summary.status_requests += 1
                try:
                    try:
                        fetch = fetch_detail_page(
                            page,
                            url,
                            runtime_config,
                            logger=logger,
                            listing_id=listing_id,
                            sleep=sleep,
                            circuit_breaker=breaker,
                        )
                        summary.retry_requests += max(0, fetch.attempts - 1)
                    except CircuitOpenError as error:
                        failure = error.failure
                        summary.unknown += 1
                        summary.retry_requests += max(0, failure.attempts - 1)
                        summary.add_failure(failure.category.value)
                        summary.blocking_failures = breaker.blocking_failures
                        summary.stopped_reason = "BLOCKING_SUSPECTED"
                        logger.error(
                            "circuit_breaker=OPEN blocking_failures=%s threshold=%s "
                            "stopped_reason=%s",
                            breaker.blocking_failures,
                            breaker.threshold,
                            summary.stopped_reason,
                        )
                        break
                    except FetchFailure as failure:
                        summary.unknown += 1
                        summary.retry_requests += max(0, failure.attempts - 1)
                        summary.add_failure(failure.category.value)
                        logger.warning(
                            "listing_id=%s url=%s status=UNKNOWN failure=%s "
                            "http_status=%s database_unchanged=true message=%s",
                            listing_id,
                            url,
                            failure.category.value,
                            failure.status_code,
                            failure,
                        )
                        continue

                    try:
                        status_decision = interpret_listing_status(
                            fetch.html,
                            fetch.status_code,
                            requested_url=url,
                            final_url=fetch.final_url,
                            listing_id=listing_id,
                        )
                    except Exception as exc:
                        summary.unknown += 1
                        summary.add_failure(FailureCategory.PARSER_ERROR.value)
                        logger.warning(
                            "listing_id=%s status=UNKNOWN failure=%s "
                            "database_unchanged=true message=%s",
                            listing_id,
                            FailureCategory.PARSER_ERROR.value,
                            exc,
                        )
                        continue

                    if status_decision.status == ListingStatus.INACTIVE:
                        mark_listing_inactive(listing_id)
                        summary.inactive += 1
                    elif status_decision.status == ListingStatus.ACTIVE:
                        mark_listing_checked(listing_id)
                        summary.active += 1
                    else:
                        summary.unknown += 1

                    logger.info(
                        "listing_id=%s progress=%s/%s status=%s reason=%s marker=%r",
                        listing_id,
                        index,
                        len(active_listings),
                        status_decision.status.value,
                        status_decision.reason,
                        status_decision.marker,
                    )
                finally:
                    summary.blocking_failures = breaker.blocking_failures
        finally:
            browser.close()

    logger.info("%s", summary.format())
    return summary
