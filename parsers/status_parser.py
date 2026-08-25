from enum import Enum

from bs4 import BeautifulSoup
from utils.text import clean_text

INACTIVE_KEYWORDS = [
    "gelöscht",
    "reserviert",
    "nicht mehr verfügbar",
    "anzeige wurde gelöscht",
    "diese anzeige ist nicht mehr verfügbar",
]


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"


def is_listing_active(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1")
    #title = title_el.get_text(" ", strip=True).lower() if title_el else ""
    if title_el:
        for span in title_el.select("span"):
            span.decompose()

        title = clean_text(title_el.get_text(" ", strip=True))
        title = title.lower()
    else:
        title = ""

    page_text = soup.get_text(" ", strip=True).lower()

    for keyword in INACTIVE_KEYWORDS:
        if keyword in title:
            print(f"inactive word in title: {keyword}")
            return False

    for keyword in INACTIVE_KEYWORDS:
        if keyword in page_text:
            print(f"inactive word in text: {keyword}")
            return False

    return True


def interpret_listing_status(html: str, http_status: int | None) -> ListingStatus:
    """Interpret only confirmed outcomes; transport/server failures stay unknown."""
    if http_status is None:
        return ListingStatus.UNKNOWN
    if http_status in {404, 410}:
        return ListingStatus.INACTIVE
    if http_status >= 400:
        return ListingStatus.UNKNOWN
    if http_status < 200 or http_status >= 300:
        return ListingStatus.UNKNOWN
    if not html:
        return ListingStatus.UNKNOWN
    return ListingStatus.ACTIVE if is_listing_active(html) else ListingStatus.INACTIVE
