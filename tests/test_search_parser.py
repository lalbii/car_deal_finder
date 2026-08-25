import unittest
from pathlib import Path

from parsers.search_parser import parse_search_page


FIXTURE = Path(__file__).parent / "fixtures" / "search_page.html"


class SearchParserTests(unittest.TestCase):
    def test_extracts_listing_and_rejects_parts(self):
        listings = parse_search_page(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.listing_id, "1234567890")
        self.assertEqual(listing.title, "BMW 320d Touring")
        self.assertEqual(listing.price, 12_500)
        self.assertEqual(
            listing.url,
            "https://www.kleinanzeigen.de/s-anzeige/bmw-320d-touring/1234567890-216-1",
        )


if __name__ == "__main__":
    unittest.main()
