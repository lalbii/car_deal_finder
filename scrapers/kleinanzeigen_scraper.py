import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta

import pandas as pd
from playwright.sync_api import sync_playwright

from config.paths import DATA_DIR
from models.listing import SearchListing
from models.run_summary import ScrapeRunSummary
from models.runtime_config import RuntimeConfig
from models.search_config import SearchConfig
from operations.logging_config import get_logger
from operations.request_scheduling import (
    should_check_status,
    should_refresh_detail,
    utc_now,
)
from parsers.detail_parser import parse_detail_page
from parsers.search_parser import (
    SearchPageState,
    classify_search_page,
    parse_search_page,
)
from parsers.status_parser import ListingStatus, interpret_listing_status
from scrapers.browser import launch_browser
from scrapers.circuit_breaker import BlockingCircuitBreaker, CircuitOpenError
from scrapers.failures import FailureCategory, FetchFailure, FetchResult
from scrapers.kleinanzeigen_detail import fetch_detail_page
from scrapers.kleinanzeigen_search import fetch_search_page
from storage.sqlite import (
    get_known_listings,
    init_db,
    insert_listing_history,
    mark_listing_checked,
    mark_listing_inactive,
    mark_listings_seen,
    upsert_listing,
)
from validation.listing_quality import validate_listing, validated_record


class ScrapeRunError(RuntimeError):
    pass


def _deduplicate_listings(listings: list[SearchListing]) -> list[SearchListing]:
    unique: dict[str, SearchListing] = {}
    for listing in listings:
        if listing.listing_id and listing.listing_id not in unique:
            unique[listing.listing_id] = listing
    return list(unique.values())


def _record_fetch_result(summary: ScrapeRunSummary, fetch: FetchResult) -> None:
    summary.retry_requests += max(0, fetch.attempts - 1)


def _record_failure(
    summary: ScrapeRunSummary,
    logger: logging.Logger,
    failure: FetchFailure,
    **context: object,
) -> None:
    summary.add_failure(failure.category.value)
    summary.retry_requests += max(0, failure.attempts - 1)
    context_text = " ".join(f"{key}={value}" for key, value in context.items())
    logger.warning(
        "%s failure=%s status=%s attempts=%s message=%s",
        context_text,
        failure.category.value,
        failure.status_code,
        failure.attempts,
        failure,
    )


def _open_circuit(
    summary: ScrapeRunSummary,
    logger: logging.Logger,
    breaker: BlockingCircuitBreaker,
    error: CircuitOpenError,
    **context: object,
) -> None:
    _record_failure(summary, logger, error.failure, **context)
    summary.blocking_failures = breaker.blocking_failures
    summary.stopped_reason = "BLOCKING_SUSPECTED"
    logger.error(
        "circuit_breaker=OPEN blocking_failures=%s threshold=%s "
        "stopped_reason=%s",
        breaker.blocking_failures,
        breaker.threshold,
        summary.stopped_reason,
    )


def _export_results(
    results: list[dict], search_config: SearchConfig, logger: logging.Logger
) -> None:
    if not results:
        logger.info("search=%s no_refreshed_details_to_export=true", search_config.name)
        return

    df = pd.DataFrame(results)
    before = len(df)
    df = df.drop_duplicates(subset=["listing_id"])
    logger.info(
        "search=%s duplicate_rows_removed=%s", search_config.name, before - len(df)
    )

    for column in (
        "price",
        "mileage_km",
        "first_registration",
        "fuel",
        "transmission",
    ):
        logger.info(
            "search=%s data_quality_column=%s missing=%s",
            search_config.name,
            column,
            int(df[column].isna().sum()),
        )

    output_path = DATA_DIR / (
        f"{search_config.name}_first_{search_config.max_pages}_pages.csv"
    )
    df.to_csv(output_path, index=False)
    logger.info("search=%s rows=%s csv=%s", search_config.name, len(df), output_path)


def run(
    search_config: SearchConfig,
    runtime_config: RuntimeConfig,
    *,
    logger: logging.Logger | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
) -> ScrapeRunSummary:
    logger = logger or get_logger("scraper")
    run_now = now or utc_now()
    if run_now.tzinfo is None:
        raise ValueError("Scrape run timestamp must be timezone-aware")

    summary = ScrapeRunSummary(search_config.name, search_config.max_pages)
    breaker = BlockingCircuitBreaker(runtime_config.blocking_failure_threshold)
    detail_interval = timedelta(hours=runtime_config.detail_refresh_interval_hours)
    status_interval = timedelta(hours=runtime_config.inactive_check_interval_hours)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    results: list[dict] = []

    logger.info(
        "search=%s starting_scrape=true pages=%s headless=%s "
        "detail_refresh_hours=%s inactive_check_hours=%s blocking_threshold=%s",
        search_config.name,
        search_config.max_pages,
        runtime_config.headless,
        runtime_config.detail_refresh_interval_hours,
        runtime_config.inactive_check_interval_hours,
        runtime_config.blocking_failure_threshold,
    )

    with sync_playwright() as playwright:
        browser = launch_browser(playwright, runtime_config)
        try:
            page = browser.new_page()
            page.set_default_navigation_timeout(runtime_config.navigation_timeout_ms)
            discovered_listings: list[SearchListing] = []

            for page_num in range(1, search_config.max_pages + 1):
                summary.search_requests += 1
                try:
                    fetch = fetch_search_page(
                        page,
                        search_config,
                        runtime_config,
                        page_num,
                        logger=logger,
                        sleep=sleep,
                        circuit_breaker=breaker,
                    )
                    _record_fetch_result(summary, fetch)
                except CircuitOpenError as error:
                    _open_circuit(
                        summary,
                        logger,
                        breaker,
                        error,
                        search=search_config.name,
                        page=page_num,
                    )
                    break
                except FetchFailure as failure:
                    _record_failure(
                        summary,
                        logger,
                        failure,
                        search=search_config.name,
                        page=page_num,
                    )
                    continue

                try:
                    page_state = classify_search_page(fetch.html)
                except Exception as exc:
                    summary.add_failure(FailureCategory.PARSER_ERROR.value)
                    logger.warning(
                        "search=%s page=%s failure=%s message=%s",
                        search_config.name,
                        page_num,
                        FailureCategory.PARSER_ERROR.value,
                        exc,
                    )
                    continue

                if page_state == SearchPageState.UNEXPECTED:
                    summary.add_failure(FailureCategory.UNEXPECTED_PAGE.value)
                    logger.warning(
                        "search=%s page=%s failure=%s message=unexpected search layout",
                        search_config.name,
                        page_num,
                        FailureCategory.UNEXPECTED_PAGE.value,
                    )
                    continue

                try:
                    listings = parse_search_page(fetch.html)
                except Exception as exc:
                    summary.add_failure(FailureCategory.PARSER_ERROR.value)
                    logger.warning(
                        "search=%s page=%s failure=%s message=%s",
                        search_config.name,
                        page_num,
                        FailureCategory.PARSER_ERROR.value,
                        exc,
                    )
                    continue

                summary.pages_fetched += 1
                (DATA_DIR / f"search_page_{page_num}.html").write_text(
                    fetch.html, encoding="utf-8"
                )
                if page_state == SearchPageState.EMPTY:
                    logger.warning(
                        "search=%s page=%s valid_empty_result=true listings=0",
                        search_config.name,
                        page_num,
                    )
                elif not listings:
                    logger.warning(
                        "search=%s page=%s known_layout=true accepted_listings=0 "
                        "message=all cards were rejected or malformed",
                        search_config.name,
                        page_num,
                    )
                else:
                    logger.info(
                        "search=%s page=%s listings=%s",
                        search_config.name,
                        page_num,
                        len(listings),
                    )
                discovered_listings.extend(listings)

            discovered_listings = _deduplicate_listings(discovered_listings)
            summary.listings_discovered = len(discovered_listings)

            if summary.pages_fetched == 0 and summary.stopped_reason is None:
                raise ScrapeRunError("no search pages could be fetched and parsed")

            known_listings = {
                listing["listing_id"]: listing for listing in get_known_listings()
            }
            visible_ids = {
                listing.listing_id
                for listing in discovered_listings
                if listing.listing_id
            }
            mark_listings_seen(visible_ids, seen_at=run_now)

            detail_candidates: list[SearchListing] = []
            for listing in discovered_listings:
                known = known_listings.get(listing.listing_id)
                if known is None:
                    summary.new_listings += 1
                if should_refresh_detail(known, run_now, detail_interval):
                    detail_candidates.append(listing)
                else:
                    summary.skipped_recent_details += 1
                    logger.debug(
                        "listing_id=%s action=skip_detail reason=recent_detail",
                        listing.listing_id,
                    )

            missing_active = [
                listing
                for listing in known_listings.values()
                if listing.get("is_active") and listing["listing_id"] not in visible_ids
            ]
            summary.missing_active_candidates = len(missing_active)
            status_candidates: list[dict] = []
            complete_search_coverage = (
                summary.pages_fetched == search_config.max_pages
                and summary.stopped_reason is None
            )
            if complete_search_coverage:
                for listing in missing_active:
                    if should_check_status(listing, run_now, status_interval):
                        status_candidates.append(listing)
                    else:
                        summary.skipped_recent_status_checks += 1
            elif missing_active:
                logger.warning(
                    "search=%s status_checks_deferred=true reason=incomplete_search_coverage "
                    "missing_active=%s pages_fetched=%s/%s",
                    search_config.name,
                    len(missing_active),
                    summary.pages_fetched,
                    search_config.max_pages,
                )

            logger.info(
                "search=%s schedule_new=%s detail_refreshes=%s "
                "skipped_recent_details=%s status_checks=%s "
                "skipped_recent_status_checks=%s",
                search_config.name,
                summary.new_listings,
                len(detail_candidates),
                summary.skipped_recent_details,
                len(status_candidates),
                summary.skipped_recent_status_checks,
            )

            prior_detail_or_status_request = False

            for index, listing in enumerate(detail_candidates, start=1):
                if summary.stopped_reason:
                    break
                if prior_detail_or_status_request and runtime_config.detail_delay_seconds:
                    sleep(runtime_config.detail_delay_seconds)
                prior_detail_or_status_request = True
                summary.detail_requests += 1
                try:
                    fetch = fetch_detail_page(
                        page,
                        listing.url,
                        runtime_config,
                        logger=logger,
                        listing_id=listing.listing_id,
                        search_name=search_config.name,
                        sleep=sleep,
                        circuit_breaker=breaker,
                    )
                    _record_fetch_result(summary, fetch)
                except CircuitOpenError as error:
                    _open_circuit(
                        summary,
                        logger,
                        breaker,
                        error,
                        search=search_config.name,
                        listing_id=listing.listing_id,
                    )
                    break
                except FetchFailure as failure:
                    _record_failure(
                        summary,
                        logger,
                        failure,
                        search=search_config.name,
                        listing_id=listing.listing_id,
                    )
                    continue

                try:
                    status_decision = interpret_listing_status(
                        fetch.html, fetch.status_code
                    )
                except Exception as exc:
                    summary.add_failure(FailureCategory.PARSER_ERROR.value)
                    logger.warning(
                        "search=%s listing_id=%s failure=%s message=%s",
                        search_config.name,
                        listing.listing_id,
                        FailureCategory.PARSER_ERROR.value,
                        exc,
                    )
                    continue

                if status_decision.status == ListingStatus.INACTIVE:
                    if listing.listing_id:
                        mark_listing_inactive(listing.listing_id, checked_at=run_now)
                    summary.confirmed_inactive += 1
                    logger.info(
                        "search=%s listing_id=%s status=INACTIVE reason=%s marker=%r",
                        search_config.name,
                        listing.listing_id,
                        status_decision.reason,
                        status_decision.marker,
                    )
                    continue
                if status_decision.status == ListingStatus.UNKNOWN:
                    summary.add_failure(FailureCategory.UNEXPECTED_PAGE.value)
                    logger.warning(
                        "search=%s listing_id=%s status=UNKNOWN reason=%s marker=%r "
                        "database_unchanged=true",
                        search_config.name,
                        listing.listing_id,
                        status_decision.reason,
                        status_decision.marker,
                    )
                    continue

                try:
                    parsed_listing = parse_detail_page(fetch.html, listing.url)
                    normalized_listing = replace(
                        parsed_listing,
                        listing_id=listing.listing_id,
                        location=listing.location,
                        title=parsed_listing.title or listing.title,
                        is_active=True,
                    )
                    quality = validate_listing(normalized_listing)
                except Exception as exc:
                    summary.add_failure(FailureCategory.PARSER_ERROR.value)
                    logger.warning(
                        "search=%s listing_id=%s failure=%s message=%s",
                        search_config.name,
                        listing.listing_id,
                        FailureCategory.PARSER_ERROR.value,
                        exc,
                    )
                    continue

                row = {
                    **listing.to_record(),
                    **validated_record(normalized_listing, quality),
                    "scraped_at": run_now.isoformat(),
                }
                upsert_listing(row)
                insert_listing_history(row)
                results.append(row)
                summary.details_succeeded += 1
                logger.info(
                    "search=%s listing_id=%s detail_progress=%s/%s status=ACTIVE "
                    "price=%s mileage_km=%s quality=%s",
                    search_config.name,
                    listing.listing_id,
                    index,
                    len(detail_candidates),
                    row.get("price"),
                    row.get("mileage_km"),
                    row.get("data_quality"),
                )

            for index, listing in enumerate(status_candidates, start=1):
                if summary.stopped_reason:
                    break
                if prior_detail_or_status_request and runtime_config.detail_delay_seconds:
                    sleep(runtime_config.detail_delay_seconds)
                prior_detail_or_status_request = True
                summary.status_requests += 1
                try:
                    fetch = fetch_detail_page(
                        page,
                        listing["url"],
                        runtime_config,
                        logger=logger,
                        listing_id=listing["listing_id"],
                        search_name=search_config.name,
                        sleep=sleep,
                        circuit_breaker=breaker,
                    )
                    _record_fetch_result(summary, fetch)
                except CircuitOpenError as error:
                    _open_circuit(
                        summary,
                        logger,
                        breaker,
                        error,
                        search=search_config.name,
                        listing_id=listing["listing_id"],
                    )
                    break
                except FetchFailure as failure:
                    _record_failure(
                        summary,
                        logger,
                        failure,
                        search=search_config.name,
                        listing_id=listing["listing_id"],
                    )
                    continue

                try:
                    status_decision = interpret_listing_status(
                        fetch.html, fetch.status_code
                    )
                except Exception as exc:
                    summary.add_failure(FailureCategory.PARSER_ERROR.value)
                    logger.warning(
                        "search=%s listing_id=%s status=UNKNOWN failure=%s "
                        "database_unchanged=true message=%s",
                        search_config.name,
                        listing["listing_id"],
                        FailureCategory.PARSER_ERROR.value,
                        exc,
                    )
                    continue

                if status_decision.status == ListingStatus.INACTIVE:
                    mark_listing_inactive(listing["listing_id"], checked_at=run_now)
                    summary.confirmed_inactive += 1
                elif status_decision.status == ListingStatus.ACTIVE:
                    mark_listing_checked(listing["listing_id"], checked_at=run_now)
                else:
                    summary.add_failure(FailureCategory.UNEXPECTED_PAGE.value)

                logger.info(
                    "search=%s listing_id=%s status_progress=%s/%s status=%s "
                    "reason=%s marker=%r",
                    search_config.name,
                    listing["listing_id"],
                    index,
                    len(status_candidates),
                    status_decision.status.value,
                    status_decision.reason,
                    status_decision.marker,
                )
        finally:
            browser.close()

    summary.blocking_failures = breaker.blocking_failures
    _export_results(results, search_config, logger)
    logger.info("%s", summary.format())
    return summary
