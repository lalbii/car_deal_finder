import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main


class MainCliTests(unittest.TestCase):
    def test_list_searches(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--list-searches"]):
            with redirect_stdout(output):
                main.main()

        self.assertIn("bmw_320d_nrw (enabled)", output.getvalue())

    def test_default_selects_first_enabled_search(self):
        with patch.object(sys, "argv", ["main.py"]):
            with patch("scrapers.kleinanzeigen_scraper.run") as run:
                main.main()

        self.assertEqual(run.call_args.args[0].name, "bmw_320d_nrw")

    def test_named_search_is_selected(self):
        with patch.object(sys, "argv", ["main.py", "--search", "bmw_320d_nrw"]):
            with patch("scrapers.kleinanzeigen_scraper.run") as run:
                main.main()

        self.assertEqual(run.call_args.args[0].name, "bmw_320d_nrw")


if __name__ == "__main__":
    unittest.main()
