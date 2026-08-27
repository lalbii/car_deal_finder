import tempfile
import unittest
from pathlib import Path

from analytics.vehicle_semantics import (
    BodyStyle,
    Drivetrain,
    VehicleSemantics,
    extract_vehicle_semantics,
)
from config.vehicle_semantics import load_vehicle_semantics


class VehicleSemanticsTests(unittest.TestCase):
    def setUp(self):
        load_vehicle_semantics.cache_clear()

    def tearDown(self):
        load_vehicle_semantics.cache_clear()

    def test_body_styles(self):
        cases = {
            "BMW 320d Touring": BodyStyle.WAGON,
            "BMW 320d Kombi": BodyStyle.WAGON,
            "BMW 320d Limousine": BodyStyle.SEDAN,
            "BMW 320d Coupé": BodyStyle.COUPE,
            "BMW 320d Cabrio": BodyStyle.CONVERTIBLE,
            "Generic SUV title": BodyStyle.SUV,
            "Compact Hatchback": BodyStyle.HATCHBACK,
            "Family Van": BodyStyle.VAN,
            "BMW 320d Automatik": BodyStyle.UNKNOWN,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(extract_vehicle_semantics(title).body_style, expected)

    def test_drivetrains(self):
        cases = {
            "BMW 320d xDrive": Drivetrain.AWD,
            "Audi A4 quattro": Drivetrain.AWD,
            "Mercedes 4MATIC": Drivetrain.AWD,
            "VW 4Motion": Drivetrain.AWD,
            "Generic AWD": Drivetrain.AWD,
            "BMW 320d Heckantrieb": Drivetrain.RWD,
            "BMW 320d": Drivetrain.UNKNOWN,
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(extract_vehicle_semantics(title).drivetrain, expected)

    def test_normalization_is_case_punctuation_and_whitespace_safe(self):
        result = extract_vehicle_semantics("  BMW, 320D: TOURING / X-DRIVE  ")
        self.assertEqual(result, VehicleSemantics(BodyStyle.WAGON, Drivetrain.AWD))

    def test_conflicts_resolve_to_unknown(self):
        body = extract_vehicle_semantics("BMW Touring Coupe")
        drivetrain = extract_vehicle_semantics("BMW xDrive Heckantrieb")
        self.assertEqual(body.body_style, BodyStyle.UNKNOWN)
        self.assertEqual(drivetrain.drivetrain, Drivetrain.UNKNOWN)

    def test_none_and_sparse_titles_are_unknown(self):
        expected = VehicleSemantics(BodyStyle.UNKNOWN, Drivetrain.UNKNOWN)
        self.assertEqual(extract_vehicle_semantics(None), expected)
        self.assertEqual(extract_vehicle_semantics("BMW BMW 320D zu verkaufen"), expected)

    def test_no_chassis_code_inference(self):
        self.assertEqual(
            extract_vehicle_semantics("BMW E92 320d").body_style,
            BodyStyle.UNKNOWN,
        )

    def test_repeated_calls_are_deterministic(self):
        first = extract_vehicle_semantics("BMW 320d touring xDrive")
        self.assertEqual(first, extract_vehicle_semantics("BMW 320d touring xDrive"))

    def test_default_config_is_typed_and_versioned(self):
        vocabulary = load_vehicle_semantics()
        self.assertEqual(vocabulary.version, 1)
        self.assertEqual(len(vocabulary.body_style[BodyStyle.WAGON]), 3)
        self.assertEqual(len(vocabulary.drivetrain[Drivetrain.AWD]), 7)
        self.assertEqual(vocabulary.drivetrain[Drivetrain.FWD], ())

    def test_invalid_config_fails_clearly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "semantics.yaml"
            path.write_text("version: 2\nbody_style: {}\ndrivetrain: {}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unsupported vehicle semantics version"):
                load_vehicle_semantics(path)


if __name__ == "__main__":
    unittest.main()
