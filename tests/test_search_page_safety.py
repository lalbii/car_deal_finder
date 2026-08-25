import unittest
from pathlib import Path

from parsers.search_parser import SearchPageState, classify_search_page


FIXTURE = Path(__file__).parent / "fixtures" / "search_page.html"


class SearchPageSafetyTests(unittest.TestCase):
    def test_known_layout_is_valid(self):
        self.assertEqual(
            classify_search_page(FIXTURE.read_text(encoding="utf-8")),
            SearchPageState.VALID,
        )

    def test_explicit_empty_result_is_distinguished(self):
        self.assertEqual(
            classify_search_page("<html><p>Keine Anzeigen gefunden</p></html>"),
            SearchPageState.EMPTY,
        )

    def test_unknown_layout_is_not_treated_as_empty_market(self):
        self.assertEqual(
            classify_search_page("<html><p>Something changed</p></html>"),
            SearchPageState.UNEXPECTED,
        )


if __name__ == "__main__":
    unittest.main()
