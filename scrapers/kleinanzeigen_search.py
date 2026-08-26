import logging
import time
from collections.abc import Callable

from playwright.sync_api import Page
from models.search_config import SearchConfig
from models.runtime_config import RuntimeConfig
from parsers.search_parser import parse_search_page
from scrapers.circuit_breaker import BlockingCircuitBreaker
from scrapers.failures import FetchResult
from scrapers.fetching import navigate_with_retry

def build_search_url(search_config: SearchConfig, page_num: int) -> str:
    region = search_config.region
    query = search_config.query
    category = search_config.category

    if page_num == 1:
        return (
            f"https://www.kleinanzeigen.de/s-autos/{region}/"
            f"sortierung:neuste/{query}/{category}"
        )

    return (
        f"https://www.kleinanzeigen.de/s-autos/{region}/"
        f"sortierung:neuste/seite:{page_num}/{query}/{category}"
    )


def discover_max_pages(
    page: Page,
    search_config: SearchConfig,
    runtime_config: RuntimeConfig,
    logger: logging.Logger,
) -> int:
    low = 1
    high = 100

    while low < high:
        mid = (low + high + 1) // 2

        result = fetch_search_page(
            page, search_config, runtime_config, mid, logger=logger
        )
        listings = parse_search_page(result.html)

        if len(listings) > 0:
            low = mid
        else:
            high = mid - 1

    return low


def fetch_search_page(
    page: Page,
    search_config: SearchConfig,
    runtime_config: RuntimeConfig,
    page_num: int,
    *,
    logger: logging.Logger,
    sleep: Callable[[float], None] = time.sleep,
    circuit_breaker: BlockingCircuitBreaker | None = None,
) -> FetchResult:
    url = build_search_url(search_config, page_num)
    logger.info(
        "search=%s page=%s url=%s opening_search_page=true",
        search_config.name,
        page_num,
        url,
    )
    return navigate_with_retry(
        page,
        url,
        runtime_config,
        logger=logger,
        context={"search": search_config.name, "page": page_num},
        sleep=sleep,
        circuit_breaker=circuit_breaker,
    )
