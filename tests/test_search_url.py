import unittest

from models.search_config import SearchConfig
from scrapers.kleinanzeigen_search import build_search_url


class SearchUrlTests(unittest.TestCase):
    def setUp(self):
        self.config = SearchConfig(
            name="bmw_320d_nrw",
            query="bmw-320d",
            region="nordrhein-westfalen",
            category="k0c216l928",
            max_pages=20,
        )

    def test_first_page_url(self):
        self.assertEqual(
            build_search_url(self.config, 1),
            "https://www.kleinanzeigen.de/s-autos/nordrhein-westfalen/"
            "sortierung:neuste/bmw-320d/k0c216l928",
        )

    def test_later_page_includes_page_number(self):
        self.assertIn("/seite:3/", build_search_url(self.config, 3))


if __name__ == "__main__":
    unittest.main()
