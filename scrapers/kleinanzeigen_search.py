from playwright.sync_api import Page
from models.search_config import SearchConfig
from parsers.search_parser import parse_search_page

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


def discover_max_pages(page: Page, search_config: SearchConfig) -> int:
    low = 1
    high = 100

    while low < high:
        mid = (low + high + 1) // 2

        html = fetch_search_page(page, search_config, mid)
        listings = parse_search_page(html)

        if len(listings) > 0:
            low = mid
        else:
            high = mid - 1

    return low


def fetch_search_page(
    page: Page, search_config: SearchConfig, page_num: int
) -> str:
    url = build_search_url(search_config, page_num)

    print(f"Opening search page {page_num}: {url}")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    return page.content()
