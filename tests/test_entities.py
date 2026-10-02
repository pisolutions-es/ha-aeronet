"""Entity behavior tests (v0.6.0, review m4 + M5).

Real entity instances (not source greps): device info must follow the
entry's stored station across select-driven switches, and the select's
option list must map the current station through the same dedupe logic
as the dropdown names.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import types
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from custom_components.aeronet import sensor as sensor_mod  # noqa: E402
from custom_components.aeronet import select as select_mod  # noqa: E402
from custom_components.aeronet import parsers  # noqa: E402


class FakeEntry:
    def __init__(self, entry_id="E1", data=None, options=None):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})

    def async_update_entry_data(self, data):
        self.data = {**self.data, **data}


class FakeDataCoord:
    def __init__(self, site="Old"):
        self.site = site


def _point(minute: int, aod: float = 0.2) -> parsers.AodPoint:
    return parsers.AodPoint(
        time=dt.datetime(2026, 10, 2, 12, minute, tzinfo=dt.timezone.utc),
        aod=aod, wavelength="AOD_500nm")


class DeviceNameFollowsEntryTests(unittest.TestCase):
    """m4: the device name is computed from entry.data, not a constructor
    snapshot — a station switch updates entry.data without a reload."""

    def _sensor(self, coord_site="Old", entry_site="Old"):
        coord = types.SimpleNamespace(
            data=None, last_update_success=True, site=coord_site)
        entry = FakeEntry(data={"site": entry_site})
        desc = sensor_mod.SENSORS[0]  # "aod"
        return sensor_mod.AeronetSensor(coord, entry, desc), coord, entry

    def test_device_name_reflects_entry_station(self):
        ent, _coord, _entry = self._sensor(coord_site="Old",
                                           entry_site="Barajas")
        self.assertEqual(ent.device_info["name"], "AERONET · Barajas")

    def test_device_name_follows_a_station_switch(self):
        ent, coord, entry = self._sensor(coord_site="Old", entry_site="Old")
        self.assertEqual(ent.device_info["name"], "AERONET · Old")
        # Station switch (select): entry.data is persisted, no reload.
        entry.data = {**entry.data, "site": "Valladolid"}
        coord.site = "Valladolid"
        self.assertEqual(ent.device_info["name"], "AERONET · Valladolid")

    def test_channel_sensor_device_name_follows_entry_station(self):
        coord = types.SimpleNamespace(
            data=None, last_update_success=True, site="Old")
        entry = FakeEntry(data={"site": "Old"})
        ent = sensor_mod.AeronetChannelSensor(coord, entry, "aod_340nm")
        entry.data = {**entry.data, "site": "Madrid"}
        self.assertEqual(ent.device_info["name"], "AERONET · Madrid")


class SelectOptionsDedupeTests(unittest.TestCase):
    """m4: the current station must not be appended next to its own
    coordinate-suffixed duplicate-name variants."""

    def _entity(self, sites, coord_site):
        coord = FakeDataCoord(site=coord_site)
        sites_coord = types.SimpleNamespace(data=sites)
        entry = FakeEntry(data={"site": coord_site})
        return select_mod.AeronetSiteSelect(coord, sites_coord, entry)

    def test_current_appended_when_missing(self):
        sites = [parsers.Site(name="Madrid", longitude=1.0, latitude=2.0,
                              elevation=0.0)]
        ent = self._entity(sites, coord_site="Barajas")
        self.assertIn("Barajas", ent.options)

    def test_current_not_duplicated_next_to_suffixed_variant(self):
        # Two genuinely different stations share the name "Twin" ->
        # dedupe_display_names emits coordinate-suffixed labels only.
        sites = [
            parsers.Site(name="Twin", longitude=1.0, latitude=2.0,
                         elevation=0.0),
            parsers.Site(name="Twin", longitude=3.0, latitude=4.0,
                         elevation=0.0),
        ]
        ent = self._entity(sites, coord_site="Twin")
        self.assertNotIn("Twin", ent.options)
        self.assertEqual([o for o in ent.options if o.startswith("Twin")],
                         ["Twin (2.00,1.00)", "Twin (4.00,3.00)"])

    def test_plain_current_stays_listed_once(self):
        sites = [parsers.Site(name="Madrid", longitude=1.0, latitude=2.0,
                              elevation=0.0)]
        ent = self._entity(sites, coord_site="Madrid")
        self.assertEqual(ent.options.count("Madrid"), 1)


class SensorStateTests(unittest.TestCase):
    """M5 follow-up: native_value/attributes read real coordinator data."""

    def _sensor_with_data(self, key):
        data = parsers.AeronetData(
            meta=parsers.SiteMeta(name="X", latitude=1, longitude=2,
                                  elevation=3))
        data.points = [_point(0, 0.1), _point(30, 0.3)]
        data.values = {"aod": list(data.points)}
        coord = types.SimpleNamespace(
            data=data, last_update_success=True, site="X")
        desc = next(d for d in sensor_mod.SENSORS if d.key == key)
        return sensor_mod.AeronetSensor(coord, FakeEntry(data={"site": "X"}),
                                        desc)

    def test_aod_native_value_is_latest_point(self):
        ent = self._sensor_with_data("aod")
        self.assertEqual(ent.native_value, 0.3)

    def test_last_data_is_latest_timestamp(self):
        ent = self._sensor_with_data("last_data")
        self.assertEqual(ent.native_value, _point(30).time)


if __name__ == "__main__":
    unittest.main()
