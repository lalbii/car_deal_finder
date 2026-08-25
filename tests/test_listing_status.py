import unittest

from parsers.status_parser import ListingStatus, interpret_listing_status


class ListingStatusTests(unittest.TestCase):
    def test_missing_response_is_unknown(self):
        self.assertEqual(
            interpret_listing_status("", None),
            ListingStatus.UNKNOWN,
        )

    def test_transient_and_blocking_errors_are_unknown(self):
        for status in (403, 429, 500):
            with self.subTest(status=status):
                self.assertEqual(
                    interpret_listing_status("<html></html>", status),
                    ListingStatus.UNKNOWN,
                )

    def test_not_found_is_inactive(self):
        self.assertEqual(
            interpret_listing_status("<html></html>", 404),
            ListingStatus.INACTIVE,
        )

    def test_unavailable_text_on_successful_page_is_inactive(self):
        html = "<html><h1>Diese Anzeige wurde gelöscht</h1></html>"
        self.assertEqual(
            interpret_listing_status(html, 200),
            ListingStatus.INACTIVE,
        )

    def test_normal_successful_page_is_active(self):
        html = "<html><h1>BMW 320d Touring</h1></html>"
        self.assertEqual(
            interpret_listing_status(html, 200),
            ListingStatus.ACTIVE,
        )


if __name__ == "__main__":
    unittest.main()
