from dataclasses import dataclass
from enum import Enum
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from utils.text import clean_text


INACTIVE_PAGE_MARKERS = (
    "diese anzeige wurde gelöscht",
    "diese anzeige ist nicht mehr verfügbar",
    "die gewünschte anzeige ist nicht mehr verfügbar",
    "anzeige nicht mehr verfügbar",
)
UNCERTAIN_PAGE_MARKERS = (
    "captcha",
    "recaptcha",
    "sicherheitsüberprüfung",
    "verify you are human",
    "ip-bereich vorübergehend gesperrt",
    "consent",
    "cookie settings",
    "datenschutzeinstellungen",
    "privacy settings",
    "challenge",
)
PAGE_LEVEL_SELECTORS = "title, h1, h2, [role='alert']"
KLEINANZEIGEN_HOSTS = {"kleinanzeigen.de", "www.kleinanzeigen.de"}


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ListingStatusDecision:
    status: ListingStatus
    reason: str
    marker: str | None = None


def is_listing_detail_url(url: str | None, listing_id: str | None = None) -> bool:
    """Return whether a URL has the canonical Kleinanzeigen detail-page shape."""
    if not url:
        return False
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.netloc.casefold() not in KLEINANZEIGEN_HOSTS
        or len(parts) != 3
        or parts[0] != "s-anzeige"
    ):
        return False
    suffix = parts[2]
    if listing_id is not None:
        expected_suffix = rf"{re.escape(str(listing_id))}-\d+-\d+"
        return re.fullmatch(expected_suffix, suffix) is not None
    return re.fullmatch(r"\d+-\d+-\d+", suffix) is not None


def _is_search_or_category_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return (
        parsed.netloc.casefold() in KLEINANZEIGEN_HOSTS
        and bool(parts)
        and parts[0].startswith("s-")
        and parts[0] != "s-anzeige"
    )


def _find_page_level_marker(
    soup: BeautifulSoup, markers: tuple[str, ...]
) -> str | None:
    for element in soup.select(PAGE_LEVEL_SELECTORS):
        text = clean_text(element.get_text(" ", strip=True))
        normalized = text.casefold() if text else ""
        for marker in markers:
            if marker in normalized:
                return marker
    return None


def _listing_title(soup: BeautifulSoup) -> str | None:
    title_el = soup.select_one("h1#viewad-title") or soup.select_one("h1")
    if not title_el:
        return None

    title_soup = BeautifulSoup(str(title_el), "lxml")
    title_copy = title_soup.select_one("h1")
    if not title_copy:
        return None
    for span in title_copy.select("span"):
        span.decompose()
    return clean_text(title_copy.get_text(" ", strip=True))


def interpret_listing_status(
    html: str,
    http_status: int | None,
    *,
    requested_url: str | None = None,
    final_url: str | None = None,
    listing_id: str | None = None,
) -> ListingStatusDecision:
    """Return a conservative status plus the evidence behind the decision."""
    if requested_url is not None and not is_listing_detail_url(
        requested_url, listing_id
    ):
        return ListingStatusDecision(
            ListingStatus.UNKNOWN, "invalid_listing_detail_url"
        )
    if http_status is None:
        return ListingStatusDecision(ListingStatus.UNKNOWN, "missing_http_status")
    if http_status in {404, 410}:
        return ListingStatusDecision(ListingStatus.INACTIVE, f"http_{http_status}")
    if http_status < 200 or http_status >= 300:
        return ListingStatusDecision(ListingStatus.UNKNOWN, f"http_{http_status}")
    if not html or not html.strip():
        return ListingStatusDecision(ListingStatus.UNKNOWN, "empty_html")

    soup = BeautifulSoup(html, "lxml")
    inactive_marker = _find_page_level_marker(soup, INACTIVE_PAGE_MARKERS)
    if inactive_marker:
        return ListingStatusDecision(
            ListingStatus.INACTIVE,
            "matched_inactive_page_marker",
            inactive_marker,
        )

    uncertain_marker = _find_page_level_marker(soup, UNCERTAIN_PAGE_MARKERS)
    if uncertain_marker:
        return ListingStatusDecision(
            ListingStatus.UNKNOWN,
            "matched_uncertain_page_marker",
            uncertain_marker,
        )
    if final_url is not None and not is_listing_detail_url(final_url, listing_id):
        if _is_search_or_category_url(final_url):
            return ListingStatusDecision(
                ListingStatus.INACTIVE,
                "redirected_to_search_or_category",
                final_url,
            )
        return ListingStatusDecision(
            ListingStatus.UNKNOWN, "unexpected_redirect", final_url
        )

    title = _listing_title(soup)
    has_live_detail_content = bool(
        soup.select_one("#viewad-price, #viewad-description-text")
    )
    if title and has_live_detail_content:
        return ListingStatusDecision(ListingStatus.ACTIVE, "live_listing_content")
    if not title:
        return ListingStatusDecision(ListingStatus.UNKNOWN, "missing_listing_heading")
    return ListingStatusDecision(ListingStatus.UNKNOWN, "missing_live_listing_content")
