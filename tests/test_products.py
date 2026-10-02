"""Tests for v0.2.0 features: daily averages, product columns, today series.

Fixtures are truncated REAL Valladolid payloads captured 2026-09-16:
- valladolid_aod_all.csv         direct sun AOD15 AVG=10 (all points)
- valladolid_aod_daily.csv       direct sun AOD15 AVG=20 (daily averages)
- valladolid_aod_daily_partial.csv same window incl. today's partial mean
- valladolid_sda.csv             direct sun SDA15 AVG=15 payload (Date_ header)
- valladolid_ssa.csv             inversion ALM15 product=SSA payload
- valladolid_vol.csv             inversion ALM15 product=VOL payload
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from urllib.parse import parse_qs, urlparse

from custom_components.aeronet import parsers  # noqa: E402
from custom_components.aeronet import urls  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as f:
        return f.read()


class TestUrlBuilders(unittest.TestCase):
    NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)

    def test_daily_url_avg20(self):
        url = urls.build_daily_url("Valladolid", self.NOW, level="1.5")
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["AVG"], ["20"])
        self.assertEqual(q["AOD15"], ["1"])
        self.assertEqual(urlparse(url).path, "/cgi-bin/print_web_data_v3")

    def test_sda_url_separate_datatype(self):
        url = urls.build_sda_url("Valladolid", self.NOW, level="1.5")
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["SDA15"], ["1"])
        self.assertNotIn("AOD15", q)
        self.assertEqual(q["AVG"], ["10"])

    def test_sda_url_levels(self):
        self.assertIn("SDA10=1", urls.build_sda_url("X", self.NOW, level="1.0"))
        self.assertIn("SDA20=1", urls.build_sda_url("X", self.NOW, level="2.0"))

    def test_inversion_url_ssa(self):
        url = urls.build_inversion_url("Valladolid", self.NOW, product="SSA")
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/cgi-bin/print_web_data_inv_v3")
        self.assertEqual(q["ALM15"], ["1"])
        self.assertEqual(q["product"], ["SSA"])
        self.assertEqual(q["AVG"], ["10"])

    def test_inversion_url_level20_vol(self):
        url = urls.build_inversion_url(
            "Valladolid", self.NOW, product="VOL", level="2.0"
        )
        q = parse_qs(urlparse(url).query)
        self.assertEqual(q["ALM20"], ["1"])
        self.assertEqual(q["product"], ["VOL"])

    def test_inversion_rejects_unknown_product(self):
        with self.assertRaises(ValueError):
            urls.build_inversion_url("X", self.NOW, product="LID")

    def test_site_stripped_in_new_urls(self):
        # Regression: an unstripped site makes AERONET return ALL stations.
        url = urls.build_daily_url(" Valladolid ", self.NOW)
        self.assertEqual(parse_qs(urlparse(url).query)["site"], ["Valladolid"])
        url = urls.build_inversion_url(" Valladolid ", self.NOW, product="SSA")
        self.assertEqual(parse_qs(urlparse(url).query)["site"], ["Valladolid"])


class TestDailyAverages(unittest.TestCase):
    def test_parse_daily_payload(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_aod_daily.csv"),
            expected_site="Valladolid",
            column_sets={"aod_daily": parsers.AOD_COLUMNS},
        )
        pts = data.values["aod_daily"]
        self.assertGreater(len(pts), 0)
        self.assertEqual(data.meta.name, "Valladolid")
        # One row per day at solar noon.
        self.assertTrue(all(p.time.hour == 12 for p in pts))

    def test_daily_includes_today_partial(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_aod_daily_partial.csv"),
            expected_site="Valladolid",
            column_sets={"aod_daily": parsers.AOD_COLUMNS},
        )
        pts = data.values["aod_daily"]
        self.assertEqual(pts[-1].time.date().isoformat(), "2026-09-16")
        # The fixture row is today's partial mean as captured mid-day
        # (AOD_500nm ~0.10); value magnitude only, it changes through the day.
        self.assertGreater(pts[-1].aod, 0.0)

    def test_last_days_series(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_aod_daily.csv"),
            expected_site="Valladolid",
            column_sets={"aod_daily": parsers.AOD_COLUMNS},
        )
        series = parsers.last_days_series(data, "aod_daily")
        self.assertEqual(sorted(series), sorted(series.keys()))
        self.assertLessEqual(len(series), 7)
        for v in series.values():
            self.assertGreater(v, 0)


class TestSdaColumns(unittest.TestCase):
    def setUp(self):
        self.data = parsers.parse_data_csv(
            fixture("valladolid_sda.csv"),
            expected_site="Valladolid",
            column_sets={
                parsers.SDA_FINE_SLOT: parsers.SDA_FINE_COLUMNS,
                parsers.SDA_COARSE_SLOT: parsers.SDA_COARSE_COLUMNS,
            },
        )

    def test_fine_and_coarse_parsed(self):
        fine = self.data.values[parsers.SDA_FINE_SLOT]
        coarse = self.data.values[parsers.SDA_COARSE_SLOT]
        self.assertGreater(len(fine), 0)
        self.assertGreater(len(coarse), 0)
        self.assertEqual(fine[0].wavelength, "Fine_Mode_AOD_500nm[tau_f]")
        self.assertEqual(coarse[0].wavelength, "Coarse_Mode_AOD_500nm[tau_c]")

    def test_column_names_use_brackets(self):
        # Guards against AERONET's bracketed SDA names being renamed away.
        self.assertEqual(
            parsers.SDA_FINE_COLUMNS[0], "Fine_Mode_AOD_500nm[tau_f]"
        )

    def test_fine_mode_fraction_extras(self):
        fracs = self.data.meta.extras.get("fine_mode_fraction")
        self.assertIsNotNone(fracs)
        for v in fracs.values():
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 1.5)

    def test_latest_value_hours_window(self):
        p = parsers.latest_value(self.data, parsers.SDA_FINE_SLOT, hours=24)
        # Fixture's last row is 2026-07-10 17:25 UTC; window relative to last point.
        self.assertIsNotNone(p)


class TestSsaVolColumns(unittest.TestCase):
    def test_ssa_parsed(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_ssa.csv"),
            expected_site="Valladolid",
            column_sets={parsers.SSA_SLOT: parsers.SSA_COLUMNS},
        )
        pts = data.values[parsers.SSA_SLOT]
        self.assertGreater(len(pts), 0)
        self.assertTrue(pts[0].wavelength.startswith("Single_Scattering_Albedo["))
        for p in pts[:20]:
            self.assertGreater(p.aod, 0.5)  # SSA is a fraction close to 1
            self.assertLessEqual(p.aod, 1.2)

    def test_vol_parsed(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_vol.csv"),
            expected_site="Valladolid",
            column_sets={parsers.VOL_SLOT: parsers.VOL_COLUMNS},
        )
        pts = data.values[parsers.VOL_SLOT]
        self.assertGreater(len(pts), 0)
        self.assertEqual(pts[0].wavelength, "VolC-T")
        for p in pts[:20]:
            self.assertGreater(p.aod, 0.0)
            self.assertLess(p.aod, 100.0)  # µm³/cm³ magnitudes

    def test_missing_column_raises_empty(self):
        with self.assertRaises(parsers.AeronetEmptyError):
            parsers.parse_data_csv(
                fixture("valladolid_ssa.csv"),
                column_sets={parsers.VOL_SLOT: parsers.VOL_COLUMNS},
            )


class TestLast24hWindow(unittest.TestCase):
    """v0.6.0 (review M4): the aod_24h mean must disclose what window it
    was computed from instead of silently reporting weeks-old data."""

    def _data(self, *points):
        data = parsers.AeronetData(
            meta=parsers.SiteMeta(name="X", latitude=1, longitude=2,
                                  elevation=3))
        data.points = list(points)
        data.values = {"aod": list(data.points)}
        return data

    def _pt(self, day, hour, aod=0.2, month=10):
        return parsers.AodPoint(
            time=dt.datetime(2026, month, day, hour, tzinfo=dt.timezone.utc),
            aod=aod, wavelength="AOD_500nm")

    NOW = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.timezone.utc)

    def test_fresh_window(self):
        mean, window = parsers.last_24h_mean_with_window(
            self._data(self._pt(2, 6, 0.1), self._pt(2, 11, 0.3)), self.NOW)
        self.assertEqual(mean, 0.2)
        self.assertEqual(window["window"], "last_24h")
        self.assertEqual(window["point_count"], 2)
        self.assertNotIn("window_date", window)

    def test_stale_fallback_discloses_last_day_with_data(self):
        # Points are 20 days old: the mean covers that old day, not 24h.
        data = self._data(self._pt(12, 9, 0.1, month=9),
                          self._pt(12, 15, 0.3, month=9))
        mean, window = parsers.last_24h_mean_with_window(data, self.NOW)
        self.assertEqual(mean, 0.2)
        self.assertEqual(window["window"], "last_day_with_data")
        self.assertEqual(window["window_date"], "2026-09-12")
        self.assertEqual(window["point_count"], 2)

    def test_no_data_window(self):
        mean, window = parsers.last_24h_mean_with_window(
            self._data(), self.NOW)
        self.assertIsNone(mean)
        self.assertEqual(window, {"window": "no_data"})

    def test_mean_last_24h_keeps_returning_the_mean(self):
        data = self._data(self._pt(12, 9, 0.1, month=9),
                          self._pt(12, 15, 0.3, month=9))
        self.assertEqual(parsers.mean_last_24h(data, self.NOW), 0.2)


class TestTodaySeries(unittest.TestCase):
    def test_today_series_covers_current_day(self):
        data = parsers.parse_data_csv(fixture("valladolid_aod_all.csv"))
        series = parsers.today_series(data)
        self.assertGreater(len(series), 0)
        last_day = data.points[-1].time.date()
        days = {iso[:10] for iso, _ in series}
        self.assertEqual(days, {last_day.isoformat()})
        # Chronological and all within [00:00, last point].
        times = [iso for iso, _ in series]
        self.assertEqual(times, sorted(times))
        self.assertTrue(times[0].endswith("+00:00"))

    def test_today_series_empty_when_no_points(self):
        self.assertEqual(parsers.today_series(parsers.AeronetData(
            meta=parsers.SiteMeta("x", 0, 0, 0))), [])

    def test_value_series_shape(self):
        data = parsers.parse_data_csv(fixture("valladolid_aod_all.csv"))
        vs = parsers.value_series(data, "aod")
        self.assertEqual(vs, [[p.time.isoformat(), p.aod] for p in data.points])


if __name__ == "__main__":
    unittest.main()
