"""Tests for the stdlib-only URL builder."""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

import urls as urls_mod  # noqa: E402


class TestBuildDataUrl(unittest.TestCase):
    def test_level15_with_email(self):
        now = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)
        url = urls_mod.build_data_url("Madrid", now, level="1.5", email="a@b.c")
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/cgi-bin/print_web_data_v3")
        self.assertEqual(q["site"], ["Madrid"])
        self.assertEqual(q["AOD15"], ["1"])
        self.assertEqual(q["AVG"], ["10"])
        self.assertEqual(q["if_no_html"], ["1"])
        self.assertEqual(q["email"], ["a@b.c"])
        self.assertEqual(q["year"], ["2026"])
        self.assertEqual(q["month"], ["9"])
        self.assertEqual(q["day"], ["10"])  # 7-day window ending 2026-09-16
        self.assertEqual(q["year2"], ["2026"])
        self.assertEqual(q["month2"], ["9"])
        self.assertEqual(q["day2"], ["16"])

    def test_level20_no_email(self):
        url = urls_mod.build_data_url(
            "Barcelona", dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc), level="2.0"
        )
        q = parse_qs(urlparse(url).query)
        self.assertIn("AOD20", q)
        self.assertNotIn("AOD15", q)
        self.assertNotIn("email", q)

    def test_level10(self):
        url = urls_mod.build_data_url(
            "Evora", dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc), level="1.0"
        )
        self.assertIn("AOD10=1", url)

    def test_site_with_spaces_urlencoded(self):
        url = urls_mod.build_data_url(
            "Cart_Site", dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
        )
        self.assertIn("site=Cart_Site", url)

    def test_trailing_space_site_is_stripped(self):
        # Regression: 'Valladolid ' made AERONET ignore the site filter and
        # return every station; the URL must carry the clean name.
        for dirty in ("Valladolid ", " Valladolid", "  Valladolid  "):
            url = urls_mod.build_data_url(
                dirty, dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc)
            )
            q = parse_qs(urlparse(url).query)
            self.assertEqual(q["site"], ["Valladolid"], dirty)
            self.assertNotIn("+", url)
            self.assertNotIn("%20", url)

    def test_bad_level_raises(self):
        with self.assertRaises(ValueError):
            urls_mod.build_data_url(
                "Madrid", dt.datetime(2026, 3, 1, tzinfo=dt.timezone.utc), level="9.9"
            )


if __name__ == "__main__":
    unittest.main()
