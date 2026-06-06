from urllib.parse import urljoin
from bs4 import BeautifulSoup

from config.settings import BASE_URL
from utils.text import clean_text


def parse_search_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = soup.select("article.aditem")

    listings = []

    for item in items:
        title_el = item.select_one("a.ellipsis")
        price_el = item.select_one("p.aditem-main--middle--price-shipping--price")
        location_el = item.select_one(".aditem-main--top--left")

        if not title_el:
            continue

        title = clean_text(title_el.get_text(" ", strip=True))
        href = title_el.get("href")

        if not href:
            continue

        listings.append({
            "listing_id": item.get("data-adid"),
            "search_title": title,
            "search_price_text": clean_text(price_el.get_text(" ", strip=True)) if price_el else None,
            "location": clean_text(location_el.get_text(" ", strip=True)) if location_el else None,
            "url": urljoin(BASE_URL, href),
        })

    return listings