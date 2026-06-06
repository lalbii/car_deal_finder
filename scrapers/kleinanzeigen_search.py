from playwright.sync_api import Page
from config.settings import SEARCH_CONFIG


def build_search_url(page_num: int) -> str:
    region = SEARCH_CONFIG["region"]
    query = SEARCH_CONFIG["query"]
    category = SEARCH_CONFIG["category"]

    if page_num == 1:
        return f"https://www.kleinanzeigen.de/s-autos/{region}/{query}/{category}"

    return f"https://www.kleinanzeigen.de/s-autos/{region}/seite:{page_num}/{query}/{category}"


def fetch_search_page(page: Page, page_num: int) -> str:
    url = build_search_url(page_num)

    print(f"Opening search page {page_num}: {url}")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(5000)

    return page.content()