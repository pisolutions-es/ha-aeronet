"""v0.4.0 multispectral-channel tests (TDD RED first).

Covers:
- parser keeps EVERY wavelength column of a product family (real Valladolid
  multi-channel fixture: AOD_340nm..AOD_1640nm, -999 skipped, AOD_Empty
  placeholder columns ignored);
- channel detection helpers (dynamic discovery, sorting, options filter);
- config-entry migration v2 -> v3 (version bump; channels live in options);
- entity surface: one description per channel family/channel, the 16 KiB
  attribute budget rule (drop recent_points_24h, then today_series, flag
  series_limited) and channel visibility filtering.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

import parsers  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as f:
        return f.read()


def _run(coro):
    return asyncio.run(coro)


class TestParserKeepsAllChannels(unittest.TestCase):
    def setUp(self):
        self.body = fixture("valladolid_aod_all.csv")
        self.data = parsers.parse_data_csv(
            self.body,
            expected_site="Valladolid",
            column_sets={"aod": parsers.AOD_COLUMNS},
            channel_families=("aod",),
        )

    def test_main_slot_unchanged(self):
        # The preferred-column main slot must still exist (no dashboard break).
        self.assertTrue(self.data.points)
        self.assertTrue(all(p.wavelength.startswith("AOD_") for p in self.data.points))

    def test_every_wavelength_channel_kept(self):
        # Real Valladolid payload carries AOD_340nm .. AOD_1640nm.
        for nm in (340, 380, 440, 443, 490, 500, 510, 531, 532, 551, 555,
                   560, 620, 667, 675, 779, 865, 870, 1020, 1640):
            self.assertIn(f"aod_{nm}nm", self.data.values,
                          f"channel aod_{nm}nm missing from parsed values")

    def test_placeholder_columns_not_channels(self):
        # 'AOD_Empty' columns carry no wavelength and must never become channels.
        self.assertFalse([k for k in self.data.values if "empty" in k.lower()])
        self.assertNotIn("aod_empty", self.data.values)

    def test_channel_values_match_raw_columns(self):
        # Cross-check one channel against the raw CSV first data row.
        lines = self.body.splitlines()
        header_idx = next(
            i for i, line in enumerate(lines) if line.startswith("AERONET_Site,Date")
        )
        header = lines[header_idx].split(",")
        col = header.index("AOD_1020nm")
        raw = float(lines[header_idx + 1].split(",")[col])
        first = self.data.values["aod_1020nm"][0]
        self.assertAlmostEqual(first.aod, round(raw, 6), places=5)

    def test_no_nodata_values_in_channels(self):
        for key, series in self.data.values.items():
            if key.startswith("aod_"):
                self.assertTrue(all(p.aod >= 0 for p in series), key)

    def test_main_channel_recorded_in_extras(self):
        # Which channel the main sensor reads (so channel entities skip the
        # duplicate and channels_latest includes it explicitly).
        self.assertEqual(
            self.data.meta.extras.get("main_channel_aod"), "aod_500nm"
        )

    def test_without_family_only_main_slot(self):
        legacy = parsers.parse_data_csv(
            self.body, expected_site="Valladolid",
            column_sets={"aod": parsers.AOD_COLUMNS},
        )
        self.assertEqual(list(legacy.values), ["aod"])

    def test_ssa_channels(self):
        data = parsers.parse_data_csv(
            fixture("valladolid_ssa.csv"),
            expected_site="Valladolid",
            column_sets={parsers.SSA_SLOT: parsers.SSA_COLUMNS},
            channel_families=("ssa",),
        )
        for nm in (440, 675, 870, 1020):
            self.assertIn(f"ssa_{nm}nm", data.values)
        self.assertEqual(data.meta.extras.get("main_channel_ssa"), "ssa_440nm")


class TestChannelHelpers(unittest.TestCase):
    def setUp(self):
        self.data = parsers.parse_data_csv(
            fixture("valladolid_aod_all.csv"),
            expected_site="Valladolid",
            column_sets={"aod": parsers.AOD_COLUMNS},
            channel_families=("aod",),
        )

    def test_detect_sorted_by_wavelength(self):
        ch = parsers.detect_channels(self.data)
        self.assertGreater(len(ch), 10)
        nms = [parsers.channel_nm(c) for c in ch]
        self.assertEqual(nms, sorted(nms))
        self.assertEqual(ch[0], "aod_340nm")
        self.assertIn("aod_500nm", ch)

    def test_channel_nm_parses_id(self):
        self.assertEqual(parsers.channel_nm("aod_1640nm"), 1640)
        self.assertEqual(parsers.channel_nm("ssa_870nm"), 870)

    def test_active_channels_all_by_default(self):
        detected = parsers.detect_channels(self.data)
        self.assertEqual(parsers.active_channels(detected, None), detected)
        self.assertEqual(parsers.active_channels(detected, []), detected)

    def test_active_channels_filters_configured(self):
        detected = parsers.detect_channels(self.data)
        chosen = ["aod_340nm", "aod_500nm", "aod_1640nm"]
        self.assertEqual(parsers.active_channels(detected, chosen), chosen)
        # configured-but-absent channels are dropped, order follows detection
        self.assertEqual(
            parsers.active_channels(detected, ["aod_999nm", "aod_440nm"]),
            ["aod_440nm"],
        )

    def test_channel_label(self):
        self.assertEqual(parsers.channel_label("aod_1640nm"), "AOD 1640nm")
        self.assertEqual(parsers.channel_label("ssa_440nm"), "SSA 440nm")


class TestMigrationV2ToV3(unittest.TestCase):
    def _handler(self):
        import custom_components.aeronet as integration_module
        return integration_module.async_migrate_entry

    def test_entry_version_is_3(self):
        from custom_components.aeronet import const
        self.assertEqual(const.ENTRY_VERSION, 3)

    def test_v2_entry_upgraded_in_place(self):
        from tests.test_migration import FakeEntry, FakeHass  # reuse stubs
        migrate = self._handler()
        entry = FakeEntry(2, {"email": "", "level": "1.5", "site": "Valladolid",
                              "products": ["AOD"], "interval_min": 60})
        hass = FakeHass()
        ok = _run(migrate(hass, entry))
        self.assertTrue(ok)
        self.assertEqual(entry.version, 3)
        # products survive; no channel data is injected into entry.data
        self.assertEqual(entry.data["products"], ["AOD"])
        self.assertNotIn("channels", entry.data)

    def test_v1_entry_reaches_3(self):
        from tests.test_migration import FakeEntry, FakeHass
        migrate = self._handler()
        entry = FakeEntry(1, {"email": "", "level": "1.5", "site": "Madrid",
                              "interval_min": 60})
        hass = FakeHass()
        ok = _run(migrate(hass, entry))
        self.assertTrue(ok)
        self.assertEqual(entry.version, 3)
        self.assertEqual(entry.data["products"], ["AOD"])

    def test_current_version_is_noop(self):
        from tests.test_migration import FakeEntry, FakeHass
        migrate = self._handler()
        entry = FakeEntry(3, {"site": "Valladolid", "products": ["AOD"]})
        hass = FakeHass()
        ok = _run(migrate(hass, entry))
        self.assertTrue(ok)
        self.assertEqual(hass.updates, [])


class TestChannelEntitySurface(unittest.TestCase):
    def test_description_factory(self):
        from custom_components.aeronet import sensor as sm
        d = sm.channel_description("aod_340nm")
        self.assertEqual(d.key, "aod_340nm")
        self.assertEqual(d.name, "AOD 340nm")
        self.assertEqual(
            d.state_class.value if hasattr(d.state_class, "value") else d.state_class,
            "measurement",
        )
        # AOD is dimensionless: NO device class (v0.3.1 lat/lon lesson).
        self.assertIsNone(getattr(d, "device_class", None))
        # Visible entity, not diagnostic.
        self.assertIsNone(getattr(d, "entity_category", None))

    def test_series_attr_budget_rule(self):
        from custom_components.aeronet import sensor as sm
        # A tiny series keeps both graphs.
        small = [["2026-09-17T08:00:00+00:00", 0.05]]
        attrs = sm.channel_series_attrs(small, small)
        self.assertIn("today_series", attrs)
        self.assertIn("recent_points_24h", attrs)
        self.assertNotIn("series_limited", attrs)
        # A giant series must stay under the recorder's 16 KiB attribute cap:
        # drop recent_points_24h first, then today_series, flag the drop.
        big = [[f"2026-09-{d:02d}T{h:02d}:00:00+00:00", 0.04321]
               for d in range(1, 29) for h in range(24)]
        attrs = sm.channel_series_attrs(big, big)
        blob = json.dumps(attrs)
        self.assertLess(len(blob.encode("utf-8")), 16384)
        self.assertTrue(attrs.get("series_limited"))
        self.assertNotIn("recent_points_24h", attrs)


class TestChannelsOptionWiring(unittest.TestCase):
    def test_conf_channels_constant(self):
        from custom_components.aeronet import const
        self.assertEqual(const.CONF_CHANNELS, "channels")

    def test_options_flow_exposes_channels(self):
        from custom_components.aeronet import config_flow  # noqa: F401
        src = open(config_flow.__file__, encoding="utf-8").read()
        self.assertIn("CONF_CHANNELS", src)


if __name__ == "__main__":
    unittest.main()
