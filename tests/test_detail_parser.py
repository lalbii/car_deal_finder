import unittest
from pathlib import Path

from models.listing import FuelType, TransmissionType
from parsers.detail_parser import parse_detail_page


FIXTURE = Path(__file__).parent / "fixtures" / "detail_page.html"


class DetailParserTests(unittest.TestCase):
    def test_extracts_and_normalizes_vehicle_fields(self):
        listing = parse_detail_page(
            FIXTURE.read_text(encoding="utf-8"),
            "https://www.kleinanzeigen.de/s-anzeige/example/123-216-1",
        )

        self.assertEqual(listing.title, "BMW 320d Touring")
        self.assertEqual(listing.price, 12_500)
        self.assertEqual(listing.mileage_km, 145_000)
        self.assertEqual(listing.first_registration, "2017-09")
        self.assertEqual(listing.fuel, FuelType.DIESEL)
        self.assertEqual(listing.transmission, TransmissionType.AUTOMATIC)
        self.assertEqual(listing.posted_date, "24.08.2026")
        self.assertEqual(listing.view_count, 1_234)


if __name__ == "__main__":
    unittest.main()
