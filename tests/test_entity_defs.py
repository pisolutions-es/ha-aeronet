"""Entity definition tests for the v0.3.1 log-noise fixes (defects 2 and 3).

Asserts on the entity-description/class-attribute surface, which is what
HA validates at add-time:
- latitude/longitude must NOT carry a device class (unit "°" is not a valid
  unit for device class "distance" — HA 2026.9 logs a WARNING otherwise);
- elevation keeps device_class=DISTANCE with unit "m" (valid combo);
- the station select must explicitly mark `options` as unrecorded so the
  recorder never persists the ~1675-entry list (state-object options stay
  untouched: the dropdown UI reads them from state attributes, delivered via
  core capability_attributes).
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from custom_components.aeronet import sensor as sensor_module  # noqa: E402
from custom_components.aeronet import select as select_module  # noqa: E402


def _desc(key):
    for d in sensor_module.SENSORS:
        if d.key == key:
            return d
    raise AssertionError(f"sensor description {key!r} not found")


class TestSensorDescriptions(unittest.TestCase):
    def test_latitude_has_no_device_class(self):
        d = _desc("latitude")
        self.assertIsNone(
            getattr(d, "device_class", None),
            "latitude with unit '°' must not declare a device class "
            "(HA: 'native unit ° is not a valid unit for device class distance')",
        )
        self.assertEqual(d.native_unit_of_measurement, "°")

    def test_longitude_has_no_device_class(self):
        d = _desc("longitude")
        self.assertIsNone(getattr(d, "device_class", None))
        self.assertEqual(d.native_unit_of_measurement, "°")

    def test_elevation_keeps_distance_device_class(self):
        d = _desc("elevation")
        self.assertEqual(
            d.device_class, sensor_module.SensorDeviceClass.DISTANCE
        )
        self.assertEqual(d.native_unit_of_measurement, "m")


class TestSelectRecording(unittest.TestCase):
    def test_options_marked_unrecorded_on_class(self):
        cls = select_module.AeronetSiteSelect
        unrecorded = set(cls._unrecorded_attributes)
        self.assertIn(
            "options", unrecorded,
            "the station select must exclude `options` from recorder storage",
        )

    def test_no_state_attributes_override(self):
        # Core ships options via capability_attributes; overriding
        # state_attributes would NOT strip them from the state machine and
        # overriding capability_attributes would break the UI dropdown.
        self.assertNotIn(
            "state_attributes", vars(select_module.AeronetSiteSelect)
        )
        self.assertNotIn(
            "capability_attributes", vars(select_module.AeronetSiteSelect)
        )


if __name__ == "__main__":
    unittest.main()
