import os
import tempfile
import unittest
from pathlib import Path

from config.paths import DB_PATH, PROJECT_ROOT, SEARCH_CONFIG_PATH, VEHICLE_SEMANTICS_PATH
from config.search_loader import load_search_configs


class ProjectPathTests(unittest.TestCase):
    def test_paths_and_config_are_independent_of_working_directory(self):
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                configs = load_search_configs()
            finally:
                os.chdir(original_cwd)

        self.assertIn("bmw_320d_nrw", configs)
        self.assertTrue(DB_PATH.is_absolute())
        self.assertEqual(DB_PATH, PROJECT_ROOT / "data" / "listings.db")
        self.assertEqual(SEARCH_CONFIG_PATH, PROJECT_ROOT / "config" / "searches.yaml")
        self.assertEqual(
            VEHICLE_SEMANTICS_PATH,
            PROJECT_ROOT / "config" / "vehicle_semantics.yaml",
        )


if __name__ == "__main__":
    unittest.main()
