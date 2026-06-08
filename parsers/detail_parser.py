import re
from bs4 import BeautifulSoup

from utils.text import clean_text, extract_int, parse_price


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

    mileage_km = None
    for pattern in km_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            mileage_km = extract_int(match.group(1))
            break

    first_registration = None
    for pattern in ez_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            first_registration = match.group(1)
            break

    fuel_match = re.search(r"(Diesel|Benzin|Hybrid|Elektro)", text, re.I)
    transmission_match = re.search(
        r"(Automatikgetriebe|Automatik|Schaltgetriebe|Manuell)",
        text,
        re.I,
    )

    return {
        "mileage_km": mileage_km,
        "first_registration": first_registration,
        "fuel": fuel_match.group(1) if fuel_match else None,
        "transmission": transmission_match.group(1) if transmission_match else None,
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


def parse_detail_page(html: str, url: str) -> dict:
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

    view_match = re.search(r"\b(\d+)\s*(?:Aufrufe|views)?\b", page_text)

    lines = [
    clean_text(line)
    for line in page_text.split("\n")
        if clean_text(line)
    ]

    for i, line in enumerate(lines):
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", line):
            posted_date = line

        if re.fullmatch(r"\d+", line):
            # tarih satırından sonra gelen küçük sayı çoğu zaman görüntülenme
            if i > 0 and re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", lines[i - 1]):
                view_count = int(line)

    extracted = parse_from_description(description)
    details = parse_details_from_text(soup)

    if details.get("Kilometerstand"):
        extracted["mileage_km"] = extract_int(details["Kilometerstand"])

    if details.get("Erstzulassung"):
        extracted["first_registration"] = details["Erstzulassung"]

    if details.get("Kraftstoffart"):
        extracted["fuel"] = details["Kraftstoffart"]

    if details.get("Getriebe"):
        extracted["transmission"] = details["Getriebe"]

    is_active = True
    if title:
        bad_words = ["gelöscht", "reserviert"]
        is_active = not any(word in title.lower() for word in bad_words)

    return {
    "title": title,
    "price_text": price_text,
    "price": parse_price(price_text),
    "description": description,
    "posted_date": posted_date,
    "view_count": view_count,
    "is_active": is_active,
    "url": url,
    **extracted,
    }