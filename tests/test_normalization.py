import unittest

from models.listing import FuelType, TransmissionType
from normalization.vehicle_fields import (
    normalize_first_registration,
    normalize_fuel,
    normalize_mileage,
    normalize_price,
    normalize_transmission,
)


class NormalizationTests(unittest.TestCase):
    def test_price(self):
        self.assertEqual(normalize_price("12.500 €"), 12_500)
        self.assertEqual(normalize_price("12.500 EUR"), 12_500)
        self.assertIsNone(normalize_price("call for price"))
        self.assertIsNone(normalize_price(""))

    def test_mileage(self):
        self.assertEqual(normalize_mileage("145.000 km"), 145_000)
        self.assertIsNone(normalize_mileage("many kilometres"))
        self.assertIsNone(normalize_mileage("145000"))

    def test_fuel(self):
        self.assertEqual(normalize_fuel("Diesel"), FuelType.DIESEL)
        self.assertEqual(normalize_fuel("Benzin"), FuelType.PETROL)
        self.assertEqual(normalize_fuel("Plug-in-Hybrid"), FuelType.HYBRID)
        self.assertEqual(normalize_fuel(None), FuelType.UNKNOWN)

    def test_transmission(self):
        self.assertEqual(
            normalize_transmission("- Automatik"), TransmissionType.AUTOMATIC
        )
        self.assertEqual(
            normalize_transmission("Schaltgetriebe"), TransmissionType.MANUAL
        )
        self.assertEqual(normalize_transmission("- 6-Gang"), TransmissionType.UNKNOWN)

    def test_first_registration(self):
        self.assertEqual(normalize_first_registration("September 2017"), "2017-09")
        self.assertEqual(normalize_first_registration("09/2017"), "2017-09")
        self.assertEqual(normalize_first_registration("2017"), "2017")
        self.assertEqual(normalize_first_registration("2017-09"), "2017-09")
        self.assertIsNone(normalize_first_registration("September sometime"))


if __name__ == "__main__":
    unittest.main()
