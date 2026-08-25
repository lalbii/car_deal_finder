import re
from bs4 import BeautifulSoup

from models.listing import Listing
from normalization.vehicle_fields import (
    normalize_first_registration,
    normalize_fuel,
    normalize_mileage,
    normalize_price,
    normalize_transmission,
)
from utils.text import clean_text


def parse_from_description(description: str) -> dict:
    text = description or ""

    km_patterns = [
        r"Kilometerstand[:\s\-]*([\d\.\,]+)\s*km",
        r"Laufleistung[:\s\-]*([\d\.\,]+)\s*km",
        r"KM[:\s\-]*([\d\.\,]+)",
        r"([\d\.\,]{2,})\s*km",
    ]

    ez_patterns = [
        r"Erstzulassung[:\s\-]*([0-9]{1,2}/[0-9]{4}|[0-9]{4})",
        r"EZ[:\s\-]*([0-9]{1,2}/[0-9]{4}|[0-9]{4})",
        r"aus\s+([0-9]{1,2}/[0-9]{4}|[0-9]{4})",
        r"BJ[:\s\-]*([0-9]{4})",
        r"Baujahr[:\s\-]*([0-9]{4})",
    ]

    mileage_text = None
    for pattern in km_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            mileage_text = f"{match.group(1)} km"
            break

    first_registration_text = None
    for pattern in ez_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            first_registration_text = match.group(1)
            break

    fuel_match = re.search(r"(Diesel|Benzin|Hybrid|Elektro)", text, re.I)
    transmission_match = re.search(
        r"(Automatikgetriebe|Automatik|Schaltgetriebe|Manuell)",
        text,
        re.I,
    )

    return {
        "mileage_text": mileage_text,
        "first_registration_text": first_registration_text,
        "fuel_text": fuel_match.group(1) if fuel_match else None,
        "transmission_text": transmission_match.group(1) if transmission_match else None,
    }


def parse_details_from_text(soup: BeautifulSoup) -> dict:
    labels = {
        "Marke",
        "Modell",
        "Kilometerstand",
        "Fahrzeugzustand",
        "Erstzulassung",
        "Kraftstoffart",
        "Leistung",
        "Getriebe",
        "Fahrzeugtyp",
        "Anzahl Türen",
        "HU bis",
        "Umweltplakette",
        "Schadstoffklasse",
        "Außenfarbe",
        "Material Innenausstattung",
    }

    lines = [
        clean_text(line)
        for line in soup.get_text("\n", strip=True).split("\n")
        if clean_text(line)
    ]

    details = {}

    for i, line in enumerate(lines):
        if line in labels and i + 1 < len(lines):
            details[line] = lines[i + 1]

    return details


def parse_detail_page(html: str, url: str) -> Listing:
    soup = BeautifulSoup(html, "lxml")

    title_el = soup.select_one("h1")

    if title_el:
        for span in title_el.select("span"):
            span.decompose()

        title = clean_text(title_el.get_text(" ", strip=True))
    else:
        title = None

    price_el = soup.select_one("#viewad-price")
    desc_el = soup.select_one("#viewad-description-text")

    price_text = clean_text(price_el.get_text(" ", strip=True)) if price_el else None
    description = clean_text(desc_el.get_text(" ", strip=True)) if desc_el else ""

    page_text = soup.get_text("\n", strip=True)

    posted_date = None
    view_count = None

    date_match = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", page_text)
    if date_match:
        posted_date = date_match.group(1)

    view_el = soup.select_one("#viewad-cntr-num")

    if view_el:
        view_text = view_el.get_text(strip=True)
        view_count = int(view_text.replace(".", "").replace(",", ""))

    extra_info = soup.select_one("#viewad-extra-info")

    if extra_info:
        for span in extra_info.select("span"):
            text = span.get_text(strip=True)

            if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
                posted_date = text
                break

    raw_fields = parse_from_description(description)
    details = parse_details_from_text(soup)

    if details.get("Kilometerstand"):
        raw_fields["mileage_text"] = details["Kilometerstand"]

    if details.get("Erstzulassung"):
        raw_fields["first_registration_text"] = details["Erstzulassung"]

    if details.get("Kraftstoffart"):
        raw_fields["fuel_text"] = details["Kraftstoffart"]

    if details.get("Getriebe"):
        raw_fields["transmission_text"] = details["Getriebe"]

    is_active = True
    if title:
        bad_words = ["gelöscht", "reserviert"]
        is_active = not any(word in title.lower() for word in bad_words)

    return Listing(
        listing_id=None,
        url=url,
        title=title,
        price=normalize_price(price_text),
        mileage_km=normalize_mileage(raw_fields["mileage_text"]),
        first_registration=normalize_first_registration(
            raw_fields["first_registration_text"]
        ),
        fuel=normalize_fuel(raw_fields["fuel_text"]),
        transmission=normalize_transmission(raw_fields["transmission_text"]),
        posted_date=posted_date,
        view_count=view_count,
        is_active=is_active,
        description=description,
        raw_price=price_text,
        raw_mileage=raw_fields["mileage_text"],
        raw_first_registration=raw_fields["first_registration_text"],
        raw_fuel=raw_fields["fuel_text"],
        raw_transmission=raw_fields["transmission_text"],
    )
