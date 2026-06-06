from pathlib import Path
import time
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

from parsers.search_parser import parse_search_page
from parsers.detail_parser import parse_detail_page
from scrapers.kleinanzeigen_search import fetch_search_page
from scrapers.kleinanzeigen_detail import fetch_detail_page


def run(max_pages: int = 1):
    Path("data").mkdir(exist_ok=True)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        all_listings = []

        for page_num in range(1, max_pages + 1):
            search_html = fetch_search_page(page, page_num)
            Path(f"data/search_page_{page_num}.html").write_text(search_html, encoding="utf-8")

            listings = parse_search_page(search_html)
            print(f"Found {len(listings)} listings on page {page_num}")

            all_listings.extend(listings)

        print(f"Total listings found: {len(all_listings)}")

        for idx, listing in enumerate(all_listings, start=1):
            print(f"[{idx}/{len(all_listings)}] {listing['search_title']}")

            try:
                detail_html = fetch_detail_page(page, listing["url"])
                detail_data = parse_detail_page(detail_html, listing["url"])

                row = {**listing, **detail_data,
                        "scraped_at": datetime.utcnow().isoformat(),
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
    before = len(df)

    df = df.drop_duplicates(subset=["listing_id"])

    after = len(df)

    print(f"Removed {before - after} duplicates")

    print("\nDATA QUALITY")

    for col in [
        "price",
        "mileage_km",
        "first_registration",
        "fuel",
        "transmission",
    ]:
        missing = df[col].isna().sum()
    
        print(f"{col}: {missing}")

    output_path = f"data/bmw_320d_nrw_first_{max_pages}_pages.csv"
    df.to_csv(output_path, index=False)

    print(f"\nSaved {len(df)} rows to {output_path}")