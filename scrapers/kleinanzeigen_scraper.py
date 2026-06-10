from pathlib import Path
import time
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

from parsers.search_parser import parse_search_page
from parsers.detail_parser import parse_detail_page
from scrapers.kleinanzeigen_search import fetch_search_page
from scrapers.kleinanzeigen_detail import fetch_detail_page
from storage.sqlite import (
    get_active_listings,
    init_db,
    insert_listing_history,
    upsert_listing,
     mark_listing_checked,
    mark_listing_inactive,
)
from scrapers.kleinanzeigen_search import discover_max_pages


def extend_with_active_listings(all_listings: list[dict]) -> int:
    existing_ids = {
        listing.get("listing_id")
        for listing in all_listings
        if listing.get("listing_id")
    }

    missing_active_listings = []

    for listing in get_active_listings():
        listing_id = listing.get("listing_id")

        if not listing_id or listing_id in existing_ids:
            continue

        missing_active_listings.append({
            "listing_id": listing_id,
            "search_title": listing.get("title"),
            "search_price_text": str(listing["price"]) if listing.get("price") is not None else None,
            "location": listing.get("location"),
            "url": listing.get("url"),
        })
        existing_ids.add(listing_id)

    all_listings.extend(missing_active_listings)
    return len(missing_active_listings)


def run(max_pages: int | None):
    init_db()
    Path("data").mkdir(exist_ok=True)

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        if max_pages==None:
            print("Discovering max pages...")
            max_pages = discover_max_pages(page)
            print(f"Found {max_pages} pages")


        all_listings = []

        for page_num in range(1, max_pages + 1):
            search_html = fetch_search_page(page, page_num)
            Path(f"data/search_page_{page_num}.html").write_text(search_html, encoding="utf-8")

            listings = parse_search_page(search_html)
            print(f"Found {len(listings)} listings on page {page_num}")

            all_listings.extend(listings)

        extended_count = extend_with_active_listings(all_listings)
        print(f"Added {extended_count} active listings missing from search pages")

        print(f"Total listings found: {len(all_listings)}")
        for idx, listing in enumerate(all_listings, start=1):
            print(f"[{idx}/{len(all_listings)}] {listing['search_title']}")

            try:
                detail_html, status= fetch_detail_page(page, str(listing["url"]))

                if not(status is not None and status < 400):
                    mark_listing_inactive(listing["listing_id"])
                    print("   inactive")
                    continue
                
                    

                detail_data = parse_detail_page(detail_html, listing["url"])

                detail_data["is_active"] = status is not None and status < 400 and detail_data["is_active"]

                row = {**listing, **detail_data,
                        "scraped_at": datetime.now().isoformat(),
                    }
                results.append(row)
                upsert_listing(row)
                insert_listing_history(row)

                print(
                    f"price={row.get('price')} "
                    f"km={row.get('mileage_km')} "
                    f"ez={row.get('first_registration')} "
                    f"active={row.get('is_active')}"
                )

                time.sleep(1)
            except Exception as e:
                print(f"   ERROR: {e}")

        browser.close()
    if results != []:
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
