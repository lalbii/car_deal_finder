import logging
import time
from collections.abc import Callable

from playwright.sync_api import Page

from models.runtime_config import RuntimeConfig
from scrapers.failures import FetchResult
from scrapers.fetching import navigate_with_retry


def fetch_detail_page(
    page: Page,
    url: str,
    runtime_config: RuntimeConfig,
    *,
    logger: logging.Logger,
    listing_id: str | None = None,
    search_name: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    context = {"listing_id": listing_id or "unknown"}
    if search_name:
        context["search"] = search_name
    return navigate_with_retry(
        page,
        url,
        runtime_config,
        logger=logger,
        context=context,
        sleep=sleep,
    )
