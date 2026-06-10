from playwright.sync_api import Page


def fetch_detail_page(page: Page, url: str) -> str:
    response = page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    status = response.status if response else None
    html = page.content()

    return html, status