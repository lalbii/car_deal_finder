import unittest

from parsers.status_parser import ListingStatus, interpret_listing_status


def live_listing_html(description: str = "Gepflegtes Fahrzeug") -> str:
    return f"""
    <html>
      <head><title>BMW 320d | Kleinanzeigen</title></head>
      <body>
        <h1 id="viewad-title">
          BMW 320d Touring
          <span class="pvap-reserved-title is-hidden">Gelöscht •</span>
          <span class="pvap-reserved-title is-hidden">Reserviert •</span>
        </h1>
        <div class="pvap-reserved-veil-text">Gelöscht</div>
        <div class="pvap-reserved-veil-text">Reserviert</div>
        <div id="viewad-price">12.500 EUR</div>
        <div id="viewad-description-text">{description}</div>
      </body>
    </html>
    """


class ListingStatusTests(unittest.TestCase):
    def test_missing_response_is_unknown_with_reason(self):
        decision = interpret_listing_status("", None)

        self.assertEqual(decision.status, ListingStatus.UNKNOWN)
        self.assertEqual(decision.reason, "missing_http_status")

    def test_transient_and_blocking_errors_are_unknown(self):
        for status in (403, 429, 500):
            with self.subTest(status=status):
                decision = interpret_listing_status("<html></html>", status)

                self.assertEqual(decision.status, ListingStatus.UNKNOWN)
                self.assertEqual(decision.reason, f"http_{status}")

    def test_not_found_is_inactive_with_http_reason(self):
        decision = interpret_listing_status("<html></html>", 404)

        self.assertEqual(decision.status, ListingStatus.INACTIVE)
        self.assertEqual(decision.reason, "http_404")
        self.assertIsNone(decision.marker)

    def test_confirmed_unavailable_page_is_inactive_with_marker(self):
        html = "<html><main><h1>Diese Anzeige wurde gelöscht</h1></main></html>"

        decision = interpret_listing_status(html, 200)

        self.assertEqual(decision.status, ListingStatus.INACTIVE)
        self.assertEqual(decision.reason, "matched_inactive_page_marker")
        self.assertEqual(decision.marker, "diese anzeige wurde gelöscht")

    def test_unrelated_inactive_words_on_live_listing_do_not_make_it_inactive(self):
        decision = interpret_listing_status(
            live_listing_html(
                "Unverschämte Angebote werden gelöscht. Das Auto war reserviert, "
                "ist aber wieder verfügbar."
            ),
            200,
        )

        self.assertEqual(decision.status, ListingStatus.ACTIVE)
        self.assertEqual(decision.reason, "live_listing_content")

    def test_hidden_reserved_and_deleted_state_labels_do_not_make_it_inactive(self):
        decision = interpret_listing_status(live_listing_html(), 200)

        self.assertEqual(decision.status, ListingStatus.ACTIVE)

    def test_consent_and_challenge_pages_are_unknown(self):
        pages = (
            (
                "<html><title>Datenschutzeinstellungen</title></html>",
                "datenschutzeinstellungen",
            ),
            (
                "<html><h1>Verify you are human</h1></html>",
                "verify you are human",
            ),
            (
                "<html><h1>IP-Bereich vorübergehend gesperrt.</h1></html>",
                "ip-bereich vorübergehend gesperrt",
            ),
        )
        for html, marker in pages:
            with self.subTest(marker=marker):
                decision = interpret_listing_status(html, 200)

                self.assertEqual(decision.status, ListingStatus.UNKNOWN)
                self.assertEqual(decision.reason, "matched_uncertain_page_marker")
                self.assertEqual(decision.marker, marker)

    def test_malformed_or_unrecognized_page_is_unknown(self):
        decision = interpret_listing_status(
            "<html><h1>Generic page heading</h1></html>",
            200,
        )

        self.assertEqual(decision.status, ListingStatus.UNKNOWN)
        self.assertEqual(decision.reason, "missing_live_listing_content")


if __name__ == "__main__":
    unittest.main()
