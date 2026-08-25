from pathlib import Path
import time
from dataclasses import replace
from datetime import datetime
import pandas as pd
from playwright.sync_api import sync_playwright

from models.listing import SearchListing
from models.search_config import SearchConfig
from parsers.search_parser import parse_search_page
from parsers.detail_parser import parse_detail_page
from parsers.status_parser import ListingStatus, interpret_listing_status
from scrapers.kleinanzeigen_search import fetch_search_page
from scrapers.kleinanzeigen_detail import fetch_detail_page
from storage.sqlite import (
    get_active_listings,
    init_db,
    insert_listing_history,
    upsert_listing,
    mark_listing_inactive,
)
from validation.listing_quality import validate_listing, validated_record


def extend_with_active_listings(all_listings: list[SearchListing]) -> int:
    existing_ids = {
        listing.listing_id
        for listing in all_listings
        if listing.listing_id
    }

    missing_active_listings = []

    for listing in get_active_listings():
        listing_id = listing.get("listing_id")

        if not listing_id or listing_id in existing_ids:
            continue

        missing_active_listings.append(
            SearchListing(
                listing_id=listing_id,
                title=listing.get("title") or "",
                price=listing.get("price"),
                raw_price=(
                    str(listing["price"]) if listing.get("price") is not None else None
                ),
                location=listing.get("location"),
                url=listing.get("url") or "",
            )
        )
        existing_ids.add(listing_id)

    all_listings.extend(missing_active_listings)
    return len(missing_active_listings)


def run(search_config: SearchConfig) -> None:
    init_db()
    Path("data").mkdir(exist_ok=True)
    max_pages = search_config.max_pages

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        all_listings = []

        for page_num in range(1, max_pages + 1):
            search_html = fetch_search_page(page, search_config, page_num)
            Path(f"data/search_page_{page_num}.html").write_text(
                search_html, encoding="utf-8"
            )

            listings = parse_search_page(search_html)
            print(f"Found {len(listings)} listings on page {page_num}")

            all_listings.extend(listings)

        extended_count = extend_with_active_listings(all_listings)
        print(f"Added {extended_count} active listings missing from search pages")

        print(f"Total listings found: {len(all_listings)}")
        for idx, listing in enumerate(all_listings, start=1):
            print(f"[{idx}/{len(all_listings)}] {listing.title}")

            try:
                detail_html, status = fetch_detail_page(page, listing.url)
                listing_status = interpret_listing_status(detail_html, status)

                if listing_status == ListingStatus.INACTIVE:
                    if listing.listing_id:
                        mark_listing_inactive(listing.listing_id)
                    print("   inactive")
                    continue
                if listing_status == ListingStatus.UNKNOWN:
                    print("   unknown; database status unchanged")
                    continue

                parsed_listing = parse_detail_page(detail_html, listing.url)
                normalized_listing = replace(
                    parsed_listing,
                    listing_id=listing.listing_id,
                    location=listing.location,
                    title=parsed_listing.title or listing.title,
                    is_active=True,
                )
                quality = validate_listing(normalized_listing)
                row = {
                    **listing.to_record(),
                    **validated_record(normalized_listing, quality),
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

        output_path = f"data/{search_config.name}_first_{max_pages}_pages.csv"
        df.to_csv(output_path, index=False)

        print(f"\nSaved {len(df)} rows to {output_path}")
