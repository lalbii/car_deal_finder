from pathlib import Path
from urllib.parse import urljoin
import re
import time
import pandas as pd
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


SEARCH_URL = "https://www.kleinanzeigen.de/s-autos/nordrhein-westfalen/bmw-320d/k0c216l928"
BASE_URL = "https://www.kleinanzeigen.de"


def clean_text(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", text).strip()

    
def extract_int(text: str | None) -> int | None:
    if not text:
        return None
    numbers = re.sub(r"[^\d]", "", text)
    return int(numbers) if numbers else None


def parse_price(price_text: str | None) -> int | None:
    return extract_int(price_text)


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

        url = urljoin(BASE_URL, href)
        listing_id = item.get("data-adid")

        listings.append({
            "listing_id": listing_id,
            "search_title": title,
            "search_price_text": clean_text(price_el.get_text(" ", strip=True)) if price_el else None,
            "location": clean_text(location_el.get_text(" ", strip=True)) if location_el else None,
            "url": url,
        })

    return listings

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
    price_el = soup.select_one("#viewad-price")
    desc_el = soup.select_one("#viewad-description-text")

    title = clean_text(title_el.get_text(" ", strip=True)) if title_el else None
    price_text = clean_text(price_el.get_text(" ", strip=True)) if price_el else None
    description = clean_text(desc_el.get_text(" ", strip=True)) if desc_el else ""
    
    details = {}

    # Yöntem 1: Eski yapı
    for row in soup.select(".addetailslist--detail"):
        label_el = row.select_one(".addetailslist--detail--label")
        value_el = row.select_one(".addetailslist--detail--value")

        if label_el and value_el:
            label = clean_text(label_el.get_text(" ", strip=True))
            value = clean_text(value_el.get_text(" ", strip=True))
            details[label] = value

    # Yöntem 2: Sayfadaki label-value çiftlerini genel yakala
    labels = [
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
    ]

    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    for i, line in enumerate(lines):
        if line in labels and i + 1 < len(lines):
            details[line] = lines[i + 1]


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
        "is_active": is_active,
        "url": url,
        **extracted,
    }


def main():
    Path("data").mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print("Opening search page...")
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        search_html = page.content()
        Path("data/search_page.html").write_text(search_html, encoding="utf-8")

        listings = parse_search_page(search_html)
        print(f"Found {len(listings)} listings")

        results = []

        for idx, listing in enumerate(listings, start=1):
            print(f"[{idx}/{len(listings)}] {listing['search_title']}")

            try:
                page.goto(listing["url"], wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                detail_html = page.content()
                detail_data = parse_detail_page(detail_html, listing["url"])

                row = {
                    **listing,
                    **detail_data,
                }

                results.append(row)

                print(
                    f"   price={row.get('price')} "
                    f"km={row.get('mileage_km')} "
                    f"ez={row.get('first_registration')} "
                    f"active={row.get('is_active')}"
                )

                time.sleep(1)

            except Exception as e:
                print(f"   ERROR: {e}")

        browser.close()

    df = pd.DataFrame(results)
    output_path = "data/bmw_320d_nrw_first_page.csv"
    df.to_csv(output_path, index=False)

    print(f"\nSaved {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main()