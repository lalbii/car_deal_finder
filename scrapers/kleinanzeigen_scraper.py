import logging
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

import pandas as pd
from playwright.sync_api import sync_playwright

from config.paths import DATA_DIR
from models.listing import SearchListing
from models.run_summary import ScrapeRunSummary
from models.runtime_config import RuntimeConfig
from models.search_config import SearchConfig
from operations.logging_config import get_logger
from parsers.detail_parser import parse_detail_page
from parsers.search_parser import (
    SearchPageState,
    classify_search_page,
    parse_search_page,
)
from parsers.status_parser import ListingStatus, interpret_listing_status
from scrapers.browser import launch_browser
from scrapers.failures import FailureCategory, FetchFailure
from scrapers.kleinanzeigen_detail import fetch_detail_page
from scrapers.kleinanzeigen_search import fetch_search_page
from storage.sqlite import (
    get_active_listings,
    init_db,
    insert_listing_history,
    mark_listing_inactive,
    upsert_listing,
)
from validation.listing_quality import validate_listing, validated_record


class ScrapeRunError(RuntimeError):
    pass


def extend_with_active_listings(all_listings: list[SearchListing]) -> int:
    existing_ids = {
        listing.listing_id for listing in all_listings if listing.listing_id
    }
    missing_active_listings = []

    for listing in get_active_listings():
        listing_id = listing.get("listing_id")
        if not listing_id or listing_id in existing_ids:
            continue

        missing_active_listings.append(
            SearchListing(
                listing_id=listing_id,
                title=listing.get("title") or "",
                price=listing.get("price"),
                raw_price=(
                    str(listing["price"]) if listing.get("price") is not None else None
                ),
                location=listing.get("location"),
                url=listing.get("url") or "",
            )
        )
        existing_ids.add(listing_id)

    all_listings.extend(missing_active_listings)
    return len(missing_active_listings)


def _record_failure(
    summary: ScrapeRunSummary,
    logger: logging.Logger,
    failure: FetchFailure,
    **context: object,
) -> None:
    summary.add_failure(failure.category.value)
    context_text = " ".join(f"{key}={value}" for key, value in context.items())
    logger.warning(
        "%s failure=%s status=%s message=%s",
        context_text,
        failure.category.value,
        failure.status_code,
        failure,
    )


def _export_results(
    results: list[dict], search_config: SearchConfig, logger: logging.Logger
) -> None:
    if not results:
        logger.warning("search=%s no_successful_details_to_export=true", search_config.name)
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
) -> ScrapeRunSummary:
    logger = logger or get_logger("scraper")
    summary = ScrapeRunSummary(search_config.name, search_config.max_pages)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    results: list[dict] = []

    logger.info(
        "search=%s starting_scrape=true pages=%s headless=%s",
        search_config.name,
        search_config.max_pages,
        runtime_config.headless,
    )

    with sync_playwright() as playwright:
        browser = launch_browser(playwright, runtime_config)
        try:
            page = browser.new_page()
            page.set_default_navigation_timeout(runtime_config.navigation_timeout_ms)
            all_listings: list[SearchListing] = []

            for page_num in range(1, search_config.max_pages + 1):
                try:
                    fetch = fetch_search_page(
                        page,
                        search_config,
                        runtime_config,
                        page_num,
                        logger=logger,
                        sleep=sleep,
                    )
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
                all_listings.extend(listings)

            if summary.pages_fetched == 0:
                raise ScrapeRunError("no search pages could be fetched and parsed")

            summary.listings_discovered = len(all_listings)
            summary.prior_active_added = extend_with_active_listings(all_listings)
            logger.info(
                "search=%s listings_discovered=%s prior_active_added=%s "
                "detail_candidates=%s",
                search_config.name,
                summary.listings_discovered,
                summary.prior_active_added,
                len(all_listings),
            )

            for index, listing in enumerate(all_listings, start=1):
                try:
                    try:
                        fetch = fetch_detail_page(
                            page,
                            listing.url,
                            runtime_config,
                            logger=logger,
                            listing_id=listing.listing_id,
                            search_name=search_config.name,
                            sleep=sleep,
                        )
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
                            mark_listing_inactive(listing.listing_id)
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
                        "scraped_at": datetime.now().isoformat(),
                    }
                    upsert_listing(row)
                    insert_listing_history(row)
                    results.append(row)
                    summary.details_succeeded += 1
                    logger.info(
                        "search=%s listing_id=%s progress=%s/%s status=ACTIVE "
                        "price=%s mileage_km=%s quality=%s",
                        search_config.name,
                        listing.listing_id,
                        index,
                        len(all_listings),
                        row.get("price"),
                        row.get("mileage_km"),
                        row.get("data_quality"),
                    )
                finally:
                    if index < len(all_listings) and runtime_config.detail_delay_seconds:
                        sleep(runtime_config.detail_delay_seconds)
        finally:
            browser.close()

    _export_results(results, search_config, logger)
    logger.info("%s", summary.format())
    return summary
