import time
from playwright.sync_api import sync_playwright

from scrapers.kleinanzeigen_detail import fetch_detail_page
from parsers.status_parser import ListingStatus, interpret_listing_status
from storage.sqlite import (
    get_active_listings,
    mark_listing_checked,
    mark_listing_inactive,
)


def run_active_check(limit: int | None = None):
    active_listings = get_active_listings(limit=limit)

    print(f"Checking {len(active_listings)} active listings...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        for idx, listing in enumerate(active_listings, start=1):
            listing_id = listing["listing_id"]
            url = listing["url"]

            print(f"[{idx}/{len(active_listings)}] Checking {listing_id}")

            try:
                html, status = fetch_detail_page(page, url)
                print("Status:", status)

                listing_status = interpret_listing_status(html, status)
                if listing_status == ListingStatus.INACTIVE:
                    mark_listing_inactive(listing_id)
                    print("   inactive")
                elif listing_status == ListingStatus.ACTIVE:
                    mark_listing_checked(listing_id)
                    print("   active")
                else:
                    print("   unknown; database status unchanged")

                time.sleep(1)

            except Exception as e:
                print(f"   ERROR: {e}")

        browser.close()
