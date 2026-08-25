import unittest
from datetime import date

from models.listing import FuelType, Listing, TransmissionType
from validation.listing_quality import DataQuality, validate_listing


def make_listing(**overrides) -> Listing:
    values = {
        "listing_id": "123",
        "url": "https://www.kleinanzeigen.de/s-anzeige/example/123-216-1",
        "title": "BMW 320d",
        "price": 12_500,
        "mileage_km": 145_000,
        "first_registration": "2017-09",
        "fuel": FuelType.DIESEL,
        "transmission": TransmissionType.AUTOMATIC,
        "raw_fuel": "Diesel",
        "raw_transmission": "Automatik",
    }
    values.update(overrides)
    return Listing(**values)


class ListingValidationTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 8, 25)

    def test_normal_listing_is_valid_and_scorable(self):
        report = validate_listing(make_listing(), today=self.today)
        self.assertEqual(report.overall, DataQuality.VALID)
        self.assertTrue(report.is_scorable)

    def test_missing_and_zero_price(self):
        self.assertEqual(
            validate_listing(make_listing(price=None), self.today).fields["price"],
            DataQuality.MISSING,
        )
        self.assertEqual(
            validate_listing(make_listing(price=0), self.today).fields["price"],
            DataQuality.INVALID,
        )

    def test_absurd_price_is_classified_conservatively(self):
        report = validate_listing(make_listing(price=600_000), self.today)
        self.assertEqual(report.fields["price"], DataQuality.SUSPECT)
        self.assertFalse(report.is_scorable)

    def test_missing_and_suspicious_mileage(self):
        self.assertEqual(
            validate_listing(make_listing(mileage_km=None), self.today).fields[
                "mileage_km"
            ],
            DataQuality.MISSING,
        )
        self.assertEqual(
            validate_listing(make_listing(mileage_km=126), self.today).fields[
                "mileage_km"
            ],
            DataQuality.SUSPECT,
        )

    def test_malformed_and_future_registration_are_invalid(self):
        malformed = validate_listing(
            make_listing(first_registration="not-a-date"), self.today
        )
        future = validate_listing(make_listing(first_registration="2027-01"), self.today)
        self.assertEqual(malformed.fields["first_registration"], DataQuality.INVALID)
        self.assertEqual(future.fields["first_registration"], DataQuality.INVALID)


if __name__ == "__main__":
    unittest.main()
