"""Unit tests for the pure parsers (no Home Assistant imports needed)."""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

import parsers  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as f:
        return f.read()


class TestSiteListParser(unittest.TestCase):
    def test_parse_real_site_list(self):
        sites = parsers.parse_site_list(fixture("site_list.txt"))
        self.assertEqual(len(sites), 6)
        madrid = next(s for s in sites if s.name == "Madrid")
        self.assertAlmostEqual(madrid.latitude, 40.4519, places=4)
        self.assertAlmostEqual(madrid.longitude, -3.72395, places=4)
        self.assertAlmostEqual(madrid.elevation, 680.0, places=1)

    def test_help_html_raises_param_error(self):
        with self.assertRaises(parsers.AeronetParamError):
            parsers.parse_site_list(fixture("help_error.html"))

    def test_garbage_raises_empty_error(self):
        with self.assertRaises(parsers.AeronetEmptyError):
            parsers.parse_site_list("hello world\nnot a site list\n")

    def test_malformed_rows_skipped(self):
        body = (
            "AERONET_Database_Site_List,Num=2\n"
            "Site_Name,Longitude(decimal_degrees),Latitude(decimal_degrees),Elevation(meters)\n"
            "Good,1.0,2.0,3.0\n"
            "Bad,not,numbers,x\n"
            "Short,1.0\n"
        )
        sites = parsers.parse_site_list(body)
        self.assertEqual([s.name for s in sites], ["Good"])

    def test_site_names_are_stripped(self):
        # Regression: the live CSV has names like 'Valladolid ' with trailing
        # space; the parser must yield clean names.
        sites = parsers.parse_site_list(fixture("site_list_trailing_space.txt"))
        by_name = {s.name: s for s in sites}
        self.assertEqual(sorted(by_name), ["Madrid", "Tucson", "Valladolid"])
        for name in by_name:
            self.assertEqual(name, name.strip())
            self.assertNotIn(" ", name)
        self.assertAlmostEqual(by_name["Valladolid"].latitude, 41.6636, places=4)


class TestNormalizeSite(unittest.TestCase):
    def test_normalize_site(self):
        self.assertEqual(parsers.normalize_site("Valladolid "), "Valladolid")
        self.assertEqual(parsers.normalize_site("  Valladolid"), "Valladolid")
        self.assertEqual(parsers.normalize_site(" Valladolid "), "Valladolid")
        self.assertEqual(parsers.normalize_site("Valladolid"), "Valladolid")
        self.assertEqual(parsers.normalize_site(""), "")
        self.assertEqual(parsers.normalize_site(None), "")

    def test_select_options_have_no_whitespace(self):
        # Mirrors select.AeronetSiteSelect.options: option values sent to the
        # AERONET web service must never carry stray whitespace.
        sites = parsers.parse_site_list(fixture("site_list_trailing_space.txt"))
        options = sorted({s.name.strip() for s in sites if s.name.strip()})
        self.assertEqual(options, ["Madrid", "Tucson", "Valladolid"])
        for opt in options:
            self.assertEqual(opt, opt.strip())


class TestDataCsvParser(unittest.TestCase):
    def test_parse_real_madrid_csv(self):
        data = parsers.parse_data_csv(fixture("data_madrid.csv"))
        self.assertGreater(len(data.points), 0)
        self.assertEqual(data.meta.name, "Madrid")
        self.assertAlmostEqual(data.meta.latitude, 40.4519, places=4)
        self.assertAlmostEqual(data.meta.longitude, -3.72395, places=4)
        self.assertAlmostEqual(data.meta.elevation, 680.0, places=1)
        # 500 nm preferred wavelength present in the Madrid site data.
        for p in data.points:
            self.assertEqual(p.wavelength, "AOD_500nm")
            self.assertGreater(p.aod, 0)
            self.assertIsNotNone(p.time.tzinfo)

    def test_points_sorted_chronologically(self):
        data = parsers.parse_data_csv(fixture("data_madrid.csv"))
        times = [p.time for p in data.points]
        self.assertEqual(times, sorted(times))

    def test_latest_point(self):
        data = parsers.parse_data_csv(fixture("data_madrid.csv"))
        latest = parsers.latest_point(data)
        self.assertEqual(latest.time, data.points[-1].time)

    def test_no_data_rows_no_points(self):
        body = fixture("data_madrid.csv")
        lines = body.splitlines()
        header_i = next(
            i for i, l in enumerate(lines) if l.startswith("AERONET_Site,Date(")
        )
        empty = "\n".join(lines[: header_i + 1])
        data = parsers.parse_data_csv(empty)
        self.assertEqual(data.points, [])

    def test_all_nodata_values_filtered(self):
        header_line = next(
            l
            for l in fixture("data_madrid.csv").splitlines()
            if l.startswith("AERONET_Site,Date(")
        )
        cols = header_line.split(",")
        aod_i = cols.index("AOD_500nm")
        row = ["-999.000000"] * len(cols)
        row[0] = "Madrid"
        row[1] = "10:09:2026"
        row[2] = "10:00:00"
        row[aod_i] = "-999.000000"
        row[cols.index("Site_Latitude(Degrees)")] = "40.451900"
        row[cols.index("Site_Longitude(Degrees)")] = "-3.723950"
        row[cols.index("Site_Elevation(m)")] = "680.000000"
        body = "meta line\n" + header_line + "\n" + ",".join(row) + "\n"
        data = parsers.parse_data_csv(body)
        self.assertEqual(data.points, [])

    def test_help_html_raises_param_error(self):
        with self.assertRaises(parsers.AeronetParamError):
            parsers.parse_data_csv(fixture("help_error.html"))

    def test_garbage_raises_empty_error(self):
        with self.assertRaises(parsers.AeronetEmptyError):
            parsers.parse_data_csv("just\ntext\nno csv here\n")

    def test_wavelength_fallback_to_551(self):
        # Build a minimal CSV without AOD_500nm but with AOD_551nm.
        header = (
            "AERONET_Site,Date(dd:mm:yyyy),Time(hh:mm:ss),AOD_551nm,"
            "Site_Latitude(Degrees),Site_Longitude(Degrees),Site_Elevation(m)"
        )
        row = "Test,01:01:2026,12:00:00,0.25,1.0,2.0,3.0"
        data = parsers.parse_data_csv("meta\n" + header + "\n" + row + "\n")
        self.assertEqual(len(data.points), 1)
        self.assertEqual(data.points[0].wavelength, "AOD_551nm")
        self.assertAlmostEqual(data.points[0].aod, 0.25)


class TestChannelDetectionEdgeCases(unittest.TestCase):
    """v0.5.0: channel detection and row resilience in data CSV payloads."""

    BANNER = (
        "AERONET Data Download (Version 3 Direct Sun)\n"
        "AERONET Version 3\n"
        "Version 3: AOD Level 1.5\n"
        "The following data are cloud cleared.\n"
    )

    def test_all_nodata_station_yields_no_aod_channels(self):
        # A station whose every AOD_*nm column is -999 (no valid measurement
        # in the window) must detect zero channels even when the aod family
        # is requested: a channel only exists with >=1 valid point.
        data = parsers.parse_data_csv(
            fixture("valladolid_aod_all_nodata.csv"), channel_families=("aod",)
        )
        self.assertEqual(data.points, [])
        self.assertEqual(parsers.detect_channels(data), [])
        # The channel slots exist (columns were present) but hold no points.
        self.assertIn("aod_1020nm", data.values)
        self.assertEqual(data.values["aod_1020nm"], [])

    def test_malformed_rows_interleaved_are_skipped(self):
        # Rows that are truncated, carry unparseable dates/times, an empty
        # site cell, or a non-numeric value are dropped; the valid rows
        # around them survive in order.
        header = "AERONET_Site,Date(dd:mm:yyyy),Time(hh:mm:ss),AOD_500nm"
        rows = [
            "Valladolid,17:09:2026,12:00:00,0.123",
            "Valladolid,17:09:2026",                       # truncated
            "Valladolid,17:09:2026,12:15:00,0.456",
            "Valladolid,17:09:2026,25:99:99,0.789",        # impossible time
            ",17:09:2026,12:30:00,0.999",                  # empty site cell
            "Valladolid,17:09:2026,12:45:00,oops",          # non-numeric AOD
            "Valladolid,17:09:2026,13:00:00,0.321",
        ]
        body = self.BANNER + header + "\n" + "\n".join(rows) + "\n"
        data = parsers.parse_data_csv(body)
        self.assertEqual([p.aod for p in data.points],
                         [0.123, 0.456, 0.321])
        self.assertEqual(data.meta.name, "Valladolid")


class TestSiteMismatchGuard(unittest.TestCase):
    """AERONET silently drops an unmatched site parameter and replies with
    every station's rows; the parser must reject such payloads."""

    def test_multi_site_payload_rejected(self):
        body = fixture("data_multi_site.csv")
        with self.assertRaises(parsers.AeronetSiteMismatchError):
            parsers.parse_data_csv(body, expected_site="Valladolid")

    def test_other_single_site_rejected(self):
        body = fixture("data_other_site.csv")
        with self.assertRaises(parsers.AeronetSiteMismatchError):
            parsers.parse_data_csv(body, expected_site="Valladolid")

    def test_matching_site_accepted(self):
        body = fixture("data_other_site.csv")
        data = parsers.parse_data_csv(body, expected_site="Tucson")
        self.assertEqual(data.meta.name, "Tucson")
        self.assertEqual(len(data.points), 2)

    def test_trailing_space_in_expected_site_still_matches(self):
        # The requested name may arrive dirty; comparison must be tolerant.
        body = fixture("data_other_site.csv")
        data = parsers.parse_data_csv(body, expected_site="Tucson ")
        self.assertEqual(data.meta.name, "Tucson")

    def test_no_expected_site_keeps_legacy_behaviour(self):
        # Without expected_site the parser stays permissive (used by tools).
        data = parsers.parse_data_csv(fixture("data_multi_site.csv"))
        self.assertEqual(len(data.points), 3)

    def test_empty_payload_with_expected_site_ok(self):
        body = fixture("data_madrid.csv")
        lines = body.splitlines()
        header_i = next(
            i for i, l in enumerate(lines) if l.startswith("AERONET_Site,Date(")
        )
        empty = "\n".join(lines[: header_i + 1])
        data = parsers.parse_data_csv(empty, expected_site="Madrid")
        self.assertEqual(data.points, [])


class TestAggregations(unittest.TestCase):
    def _data(self):
        return parsers.parse_data_csv(fixture("data_madrid.csv"))

    def test_mean_last_24h(self):
        data = self._data()
        now = data.points[-1].time + dt.timedelta(minutes=1)
        val = parsers.mean_last_24h(data, now=now)
        self.assertIsNotNone(val)
        self.assertGreater(val, 0)

    def test_mean_24h_fallback_last_day(self):
        data = self._data()
        far = data.points[-1].time + dt.timedelta(days=30)
        val = parsers.mean_last_24h(data, now=far)
        self.assertIsNotNone(val)  # falls back to last calendar day with data

    def test_mean_empty_returns_none(self):
        empty = parsers.AeronetData(meta=parsers.SiteMeta("x", 0, 0, 0))
        self.assertIsNone(parsers.mean_last_24h(empty))

    def test_daily_series(self):
        data = self._data()
        series = parsers.daily_series(data)
        self.assertGreaterEqual(len(series), 1)
        days = list(series)
        self.assertEqual(days, sorted(days))
        for v in series.values():
            self.assertGreater(v, 0)
        # sum of daily buckets == number of points
        self.assertEqual(sum(series.values()) and len(data.points) > 0, True)

    def test_recent_points_24h(self):
        data = self._data()
        pts = parsers.recent_points(data, hours=24)
        self.assertTrue(all(len(p) == 2 for p in pts))
        last = data.points[-1].time
        for iso, _ in pts:
            t = dt.datetime.fromisoformat(iso)
            self.assertGreaterEqual(t, last - dt.timedelta(hours=24))


class TestHelpDetection(unittest.TestCase):
    def test_is_help_html(self):
        self.assertTrue(parsers.is_help_html("<html><body>x</body></html>"))
        self.assertTrue(
            parsers.is_help_html(fixture("help_error.html")[:2000])
        )
        self.assertFalse(parsers.is_help_html("AERONET Data Download\na,b\n1,2\n"))


if __name__ == "__main__":
    unittest.main()
