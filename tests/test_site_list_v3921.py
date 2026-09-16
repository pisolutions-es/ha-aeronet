"""Tests for the v3921 active site list, disk-cache payload, and dedupe."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

import parsers  # noqa: E402
import site_cache  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


class TestV3921Fixture(unittest.TestCase):
    """Regression guard on the *real* downloaded active station list."""

    @classmethod
    def setUpClass(cls):
        cls.sites = parsers.parse_site_list(
            _read("aeronet_locations_v3921.txt")
        )

    def test_562_active_stations(self):
        self.assertEqual(len(self.sites), 562)

    def test_valladolid_exact_no_spaces(self):
        names = [s.name for s in self.sites]
        self.assertIn("Valladolid", names)
        self.assertTrue(all(n == n.strip() for n in names))
        self.assertFalse(any(" " in n for n in names))

    def test_no_duplicate_names(self):
        # The reason no coordinate suffix shows up in practice for v3921.
        names = [s.name for s in self.sites]
        self.assertEqual(len(names), len(set(names)))

    def test_display_names_under_select_limit(self):
        # HA core suggests <=600 options per select; the active list fits.
        display = parsers.dedupe_display_names(self.sites)
        self.assertLessEqual(len(display), 600)
        self.assertEqual(len(display), 562)

    def test_json_roundtrip_of_payload(self):
        now = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)
        payload = site_cache.sites_to_payload(self.sites, now)
        restored = site_cache.sites_from_payload(
            json.loads(json.dumps(payload)), parsers.Site
        )
        self.assertEqual(len(restored), 562)
        self.assertEqual([s.name for s in restored],
                         [s.name for s in self.sites])


class TestDedupe(unittest.TestCase):
    """Synthetic fixture: one true duplicate row + one genuine name clash."""

    @classmethod
    def setUpClass(cls):
        cls.sites = parsers.parse_site_list(_read("site_list_dupes.txt"))

    def test_same_name_same_coords_collapses(self):
        display = parsers.dedupe_display_names(self.sites)
        self.assertIn("TestStationA (40.00,1.00)", display)
        self.assertIn("TestStationA (43.00,5.00)", display)
        # the exact duplicate row appears once, not twice
        self.assertEqual(sum(d.startswith("TestStationA") for d in display), 2)

    def test_unique_name_unsuffixed(self):
        display = parsers.dedupe_display_names(self.sites)
        self.assertIn("TestStationB", display)

    def test_display_to_site_roundtrip(self):
        self.assertEqual(
            parsers.display_to_site_name("TestStationA (43.00,5.00)"),
            "TestStationA",
        )
        self.assertEqual(parsers.display_to_site_name(" Valladolid "),
                         "Valladolid")
        self.assertEqual(
            parsers.display_to_site_name("TestStationA (-4.71,41.66)"),
            "TestStationA",
        )


class TestSiteCachePayload(unittest.TestCase):
    NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)

    def _sites(self):
        return [parsers.Site(name="X", longitude=1.0, latitude=2.0,
                             elevation=3.0)]

    def test_stale_when_older_than_7_days(self):
        fresh = site_cache.sites_to_payload(
            self._sites(), self.NOW - dt.timedelta(days=6, hours=23))
        stale = site_cache.sites_to_payload(
            self._sites(), self.NOW - dt.timedelta(days=7, minutes=1))
        self.assertFalse(site_cache.is_stale(fresh, self.NOW))
        self.assertTrue(site_cache.is_stale(stale, self.NOW))

    def test_stale_on_missing_or_bad_date(self):
        self.assertTrue(site_cache.is_stale({}, self.NOW))
        self.assertTrue(site_cache.is_stale({"saved_at": "nope"}, self.NOW))

    def test_from_payload_garbage_returns_none(self):
        self.assertIsNone(site_cache.sites_from_payload({}, parsers.Site))
        self.assertIsNone(
            site_cache.sites_from_payload({"sites": [["x"]]}, parsers.Site)
        )

    def test_storage_key_per_url(self):
        k1 = site_cache.storage_key("https://a/x.txt")
        k2 = site_cache.storage_key("https://a/y.txt")
        self.assertNotEqual(k1, k2)
        self.assertTrue(k1.startswith("aeronet_site_list_"))
        self.assertEqual(k1, site_cache.storage_key("https://a/x.txt"))


if __name__ == "__main__":
    unittest.main()
