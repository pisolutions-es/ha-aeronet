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

    def test_days_widens_window(self):
        # Coordinator widens to DATA_WINDOW_WIDE_DAYS when the 7-day payload
        # comes back empty; the URL start date must move accordingly.
        now = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)
        q7 = parse_qs(urlparse(urls_mod.build_data_url("Madrid", now)).query)
        self.assertEqual(q7["day"], ["10"])  # 7-day window: Sep 10 .. 16
        q30 = parse_qs(urlparse(
            urls_mod.build_data_url("Madrid", now, days=30)).query)
        self.assertEqual(q30["year"], ["2026"])
        self.assertEqual(q30["month"], ["8"])
        self.assertEqual(q30["day"], ["18"])  # 30-day window: Aug 18 .. Sep 16
        # Widening must be consistent across all four URL builders.
        for build in (
            lambda d: urls_mod.build_daily_url("Madrid", now, days=d),
            lambda d: urls_mod.build_sda_url("Madrid", now, days=d),
            lambda d: urls_mod.build_inversion_url(
                "Madrid", now, product="SSA", days=d),
        ):
            q = parse_qs(urlparse(build(30)).query)
            self.assertEqual((q["year"], q["month"], q["day"]),
                             (["2026"], ["8"], ["18"]))
            q_default = parse_qs(urlparse(build(7)).query)
            self.assertEqual(q_default["day"], ["10"])


class TestSiteListUrls(unittest.TestCase):
    def test_default_source_is_active_v3921(self):
        import const
        self.assertEqual(
            const.SITE_LIST_URL,
            "https://aeronet.gsfc.nasa.gov/aeronet_locations_v3921.txt",
        )
        self.assertEqual(const.SITE_LIST_URL_ACTIVE, const.SITE_LIST_URL)
        self.assertIn(
            "aeronet_locations_v3.txt",
            const.SITE_LIST_URL_OPTIONS[const.SITE_LIST_URL_ALL],
        )


if __name__ == "__main__":
    unittest.main()
