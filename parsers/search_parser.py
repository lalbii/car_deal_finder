from enum import Enum
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.settings import BASE_URL, BAD_TITLE_KEYWORDS
from models.listing import SearchListing
from normalization.vehicle_fields import normalize_price
from operations.logging_config import get_logger
from utils.text import clean_text


logger = get_logger("search_parser")


class SearchPageState(str, Enum):
    VALID = "VALID"
    EMPTY = "EMPTY"
    UNEXPECTED = "UNEXPECTED"


def classify_search_page(html: str) -> SearchPageState:
    soup = BeautifulSoup(html, "lxml")
    if soup.select("article.aditem") or soup.select("article[data-adid]"):
        return SearchPageState.VALID

    page_text = soup.get_text(" ", strip=True).casefold()
    empty_markers = ("keine anzeigen gefunden", "keine ergebnisse gefunden")
    if any(marker in page_text for marker in empty_markers):
        return SearchPageState.EMPTY
    return SearchPageState.UNEXPECTED


def parse_search_page(html: str) -> list[SearchListing]:
    soup = BeautifulSoup(html, "lxml")
    legacy_items = soup.select("article.aditem")
    items = legacy_items or soup.select("article[data-adid]")
    layout = "legacy" if legacy_items else "new"

    listings = []
    skipped = {
        "missing_listing_id": 0,
        "missing_title": 0,
        "bad_title_keyword": 0,
        "missing_href": 0,
        "missing_price": 0,
    }

    for item in items:
        listing_id = item.get("data-adid")
        if not listing_id:
            skipped["missing_listing_id"] += 1
            continue

        title_el = item.select_one("a.ellipsis") or item.select_one(
            'h3 a[href^="/s-anzeige/"]'
        )
        price_el = item.select_one(
            "p.aditem-main--middle--price-shipping--price"
        ) or item.select_one("p.text-title3.font-strong.text-secondary")
        location_el = item.select_one(".aditem-main--top--left") or item.select_one(
            'svg[data-title="locationOutline"] + span'
        )

        if not title_el:
            skipped["missing_title"] += 1
            continue

        title = clean_text(title_el.get_text(" ", strip=True))
        title_lower = title.lower()

        if any(keyword in title_lower for keyword in BAD_TITLE_KEYWORDS):
            skipped["bad_title_keyword"] += 1
            continue

        href = title_el.get("href")
        if not href:
            href = item.get("data-href")

        if not href:
            skipped["missing_href"] += 1
            continue

        price_text = clean_text(price_el.get_text(" ", strip=True)) if price_el else None

        if not price_text:
            skipped["missing_price"] += 1
            continue

        listings.append(
            SearchListing(
                listing_id=listing_id,
                title=title,
                raw_price=price_text,
                price=normalize_price(price_text),
                location=(
                    clean_text(location_el.get_text(" ", strip=True))
                    if location_el
                    else None
                ),
                url=urljoin(BASE_URL, href),
            )
        )

    page_title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else None
    logger.debug(
        "Search parser debug: "
        f"html_chars={len(html)}, "
        f"page_title={page_title!r}, "
        f"layout={layout}, "
        f"aditems={len(items)}, "
        f"listings={len(listings)}, "
        f"skipped={skipped}"
    )

    return listings
