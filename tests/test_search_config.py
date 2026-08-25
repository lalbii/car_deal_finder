import tempfile
import unittest
from pathlib import Path

from config.search_loader import load_search_configs, select_search_config


class SearchConfigTests(unittest.TestCase):
    def write_config(self, contents: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "searches.yaml"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_valid_yaml_and_multiple_searches_load(self):
        path = self.write_config(
            """
searches:
  first:
    enabled: true
    query: bmw-320d
    region: nordrhein-westfalen
    category: k0c216l928
    max_pages: 20
  second:
    enabled: false
    query: bmw-118d
    region: nordrhein-westfalen
    category: k0c216l928
    max_pages: 10
"""
        )

        configs = load_search_configs(path)

        self.assertEqual(list(configs), ["first", "second"])
        self.assertTrue(configs["first"].enabled)
        self.assertFalse(configs["second"].enabled)
        self.assertEqual(select_search_config(configs).name, "first")

    def test_unknown_requested_search_fails_clearly(self):
        path = self.write_config(
            """
searches:
  first:
    query: bmw-320d
    region: nordrhein-westfalen
    category: k0c216l928
    max_pages: 20
"""
        )
        configs = load_search_configs(path)

        with self.assertRaisesRegex(ValueError, "Unknown search"):
            select_search_config(configs, "missing")

    def test_invalid_max_pages_fails(self):
        path = self.write_config(
            """
searches:
  invalid:
    query: bmw-320d
    region: nordrhein-westfalen
    category: k0c216l928
    max_pages: 0
"""
        )

        with self.assertRaisesRegex(ValueError, "greater than zero"):
            load_search_configs(path)

    def test_missing_query_fails(self):
        path = self.write_config(
            """
searches:
  invalid:
    region: nordrhein-westfalen
    category: k0c216l928
    max_pages: 20
"""
        )

        with self.assertRaisesRegex(ValueError, "missing required configuration"):
            load_search_configs(path)


if __name__ == "__main__":
    unittest.main()
