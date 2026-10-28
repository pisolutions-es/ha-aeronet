"""v0.7.0 regression suite for the audit findings that had no test.

Every test here is behavioral: it drives the real code paths (parsers,
coordinator update cycle, options listener, translations on disk) instead
of asserting that a string appears in a source file. The HA modules come
from tests/ha_stubs.py, the same shared stub set as the rest of the suite.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import sys
import types
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from custom_components.aeronet import coordinators  # noqa: E402
from custom_components.aeronet import parsers  # noqa: E402

CC_DIR = os.path.join(os.path.dirname(__file__), "..", "custom_components",
                      "aeronet")


def _data(slots=None, with_points=True):
    d = parsers.AeronetData(
        meta=parsers.SiteMeta(name="Nowhere", latitude=1, longitude=2,
                              elevation=3))
    if with_points:
        d.points.append(parsers.AodPoint(
            time=dt.datetime.now(dt.timezone.utc).replace(microsecond=0),
            aod=0.1, wavelength="AOD_500nm"))
    d.values = dict(slots or {"aod": list(d.points)})
    return d


class FakeMultiClient:
    """Scripted client covering every product method."""

    def __init__(self, results):
        self.results = results  # {(method, days): payload | Exception}
        self.calls = []

    def _ret(self, method, days):
        self.calls.append((method, days))
        item = self.results.get((method, days))
        if item is None:
            return _data()
        if isinstance(item, Exception):
            raise item
        return item

    async def fetch_data(self, site, now, *, days=7):
        return self._ret("data", days)

    async def fetch_daily(self, site, now, *, days=7):
        return self._ret("daily", days)

    async def fetch_sda(self, site, now, *, days=7):
        return self._ret("sda", days)

    async def fetch_inversion(self, product, site, now, *, days=7):
        return self._ret(product, days)


def _coordinator(products=("AOD",), site="Nowhere"):
    coord = coordinators.AeronetDataCoordinator.__new__(
        coordinators.AeronetDataCoordinator)
    coord._products = list(products)
    coord._email = ""
    coord._level = "1.5"
    coord.site = site
    coord.data = None
    coord._session = None
    coord._entry_id = "E1"
    coord._consecutive_failures = 0
    coord.hass = types.SimpleNamespace()
    return coord


class _ClientSwap(unittest.TestCase):
    def swap_client(self, results):
        client = FakeMultiClient(results)
        orig = coordinators.AeronetClient
        coordinators.AeronetClient = lambda *a, **k: client
        self.addCleanup(setattr, coordinators, "AeronetClient", orig)
        return client

    def poll(self, coord):
        try:
            return asyncio.run(coord._async_update_data())
        except coordinators.UpdateFailed as err:
            self.fail(f"update unexpectedly failed: {err}")


class MultiProductFetchTests(_ClientSwap):
    """v0.7.0 (review C1): every enabled product is actually requested.

    Before the fix, SDA was only fetched as a *fallback* when the AOD fetch
    failed, so a configuration with AOD+SDA never produced sda_fine/sda_coarse
    values and those sensors stayed empty forever.
    """

    def test_all_configured_products_are_fetched(self):
        sda = _data({"sda_fine": [], "sda_coarse": []}, with_points=False)
        sda.points.append(parsers.AodPoint(
            time=dt.datetime.now(dt.timezone.utc), aod=0.08,
            wavelength="Fine_Mode_AOD_500nm[tau_f]"))
        sda.values = {"sda_fine": list(sda.points), "sda_coarse": []}
        ssa = _data({"ssa": []}, with_points=False)
        ssa.points.append(parsers.AodPoint(
            time=dt.datetime.now(dt.timezone.utc), aod=0.93,
            wavelength="SSA_440nm"))
        ssa.values = {"ssa": list(ssa.points)}
        vol = _data({"vol": []}, with_points=False)
        vol.points.append(parsers.AodPoint(
            time=dt.datetime.now(dt.timezone.utc), aod=0.42,
            wavelength="VolC-T"))
        vol.values = {"vol": list(vol.points)}

        client = self.swap_client({
            ("data", 7): _data(),
            ("daily", 7): _data({"aod_daily": []}, with_points=False),
            ("sda", 7): sda,
            ("SSA", 7): ssa,
            ("VOL", 7): vol,
        })
        coord = _coordinator(products=("AOD", "SDA", "SSA", "VOL"))
        data = self.poll(coord)

        methods = {m for m, _ in client.calls}
        self.assertEqual(methods, {"data", "daily", "sda", "SSA", "VOL"})
        for slot in ("aod", "sda_fine", "ssa", "vol"):
            self.assertTrue(data.values.get(slot),
                            f"slot {slot} missing from the merged payload")


class WindowWideningTests(_ClientSwap):
    """v0.7.0 (review M2): the window width that produced data is reused.

    The widened 30-day window used to be forgotten, so the daily-average
    fetch kept asking for 7 days and a campaign-only station got an empty
    daily series on every poll.
    """

    def test_daily_fetch_follows_the_widened_window(self):
        client = self.swap_client({
            ("data", 7): _data(with_points=False),   # empty at 7 days
            ("data", 30): _data(),                   # data at 30 days
            ("daily", 7): _data(with_points=False),
            ("daily", 30): _data({"aod_daily": []}, with_points=False),
        })
        coord = _coordinator()
        self.poll(coord)
        self.assertIn(("data", 30), client.calls)
        self.assertIn(("daily", 30), client.calls,
                      "daily averages must widen with the all-points window")
        self.assertNotIn(("daily", 7), client.calls)

    def test_no_widening_when_the_seven_day_window_has_data(self):
        client = self.swap_client({("data", 7): _data()})
        coord = _coordinator()
        self.poll(coord)
        self.assertNotIn(("data", 30), client.calls)


class PartialFailureRetentionTests(_ClientSwap):
    """A transient product failure keeps the previous values (README)."""

    def test_failed_product_slot_keeps_previous_values(self):
        good = _data({"ssa": []}, with_points=False)
        good.points.append(parsers.AodPoint(
            time=dt.datetime.now(dt.timezone.utc), aod=0.93,
            wavelength="SSA_440nm"))
        good.values = {"ssa": list(good.points)}

        client = self.swap_client({
            ("data", 7): _data(),
            ("daily", 7): _data({"aod_daily": []}, with_points=False),
            ("SSA", 7): good,
        })
        coord = _coordinator(products=("AOD", "SSA"))
        first = self.poll(coord)
        coord.data = first
        self.assertTrue(first.values.get("ssa"))

        # Second poll: SSA fails, AOD keeps working.
        client.results[("SSA", 7)] = parsers.AeronetError("connection reset")
        second = self.poll(coord)
        self.assertTrue(second.values.get("ssa"),
                        "SSA series dropped on a transient failure")
        self.assertEqual([p.aod for p in second.values["ssa"]],
                         [p.aod for p in first.values["ssa"]])


class UpdateListenerSnapshotTests(unittest.TestCase):
    """v0.7.0 (review H2): the applied-options snapshot must be updated.

    It was left untouched after a successful configure(), so every later
    options save re-applied the same values and triggered a full refresh.
    """

    def _hass(self, store):
        import tests.ha_stubs as ha_stubs
        ha_stubs.install()
        calls = []
        coord = types.SimpleNamespace(
            products=["AOD"],
            configure=lambda **kw: calls.append(("configure", kw)),
            async_refresh=lambda: calls.append(("refresh",))
            or _noop_coro(),
        )
        store["data"] = coord
        hass = types.SimpleNamespace(
            data={"aeronet": {"E1": store}},
            config_entries=types.SimpleNamespace(
                async_reload=lambda eid: calls.append(("reload",))
                or _noop_coro()),
        )
        return hass, calls

    def _store(self):
        from custom_components.aeronet.const import SITE_LIST_URL
        return {
            "sites_url": "u",
            "config": {"email": "", "level": "1.5", "interval_min": 60,
                       "products": ["AOD"], "site_list_url": SITE_LIST_URL},
        }

    def test_repeated_identical_saves_are_noops_after_the_first(self):
        import importlib
        mod = importlib.import_module("custom_components.aeronet")
        store = self._store()
        hass, calls = self._hass(store)
        entry = types.SimpleNamespace(
            entry_id="E1",
            data={"email": "", "level": "2.0", "interval_min": 60,
                  "products": ["AOD"], "site": "Madrid"},
            options={})

        asyncio.run(mod._async_update_listener(hass, entry))
        self.assertEqual(calls[0][0], "configure")
        self.assertEqual(store["config"]["level"], "2.0",
                         "the applied options snapshot was not updated")

        calls.clear()
        asyncio.run(mod._async_update_listener(hass, entry))
        self.assertEqual(calls, [], "an unchanged save re-applied the options")

        # A real change still goes through.
        entry.data["level"] = "1.0"
        asyncio.run(mod._async_update_listener(hass, entry))
        self.assertEqual(calls[0][0], "configure")
        self.assertEqual(calls[0][1]["level"], "1.0")


def _noop_coro():
    async def _n():
        return None
    return _n()


HEADER = (
    "AERONET_Site,Date(dd:mm:yyyy),Time(hh:mm:ss),Day_of_Year,"
    "Day_of_Year(Fraction),AOD_500nm,AOD_551nm,AOD_440nm,AOD_870nm"
)


def _csv(rows):
    banner = "\n".join(["AERONET Data Download (Version 3 Direct Sun)",
                        "AERONET Version 3", "Version 3: AOD Level 1.5",
                        "cloud cleared", "Contact: PI=test"])
    body = "\n".join(",".join(str(c) for c in r) for r in rows)
    return f"{banner}\n{HEADER}\n{body}\n"


class PrimaryColumnFallbackTests(unittest.TestCase):
    """v0.7.0 (review C2): an all -999 primary column must not empty the sensor.

    AOD_500nm is the preferred column; some stations report it as -999 on
    every row while AOD_551nm carries the real values. Before the fix the
    main sensor went unavailable and no channel was promoted.
    """

    def test_falls_back_to_the_first_populated_wavelength(self):
        body = _csv([
            ["Site", "16:09:2026", "08:25:04", 259, 259.35,
             -999.0, 0.251, 0.300, 0.120],
            ["Site", "16:09:2026", "08:55:04", 259, 259.37,
             -999.0, 0.262, 0.310, 0.125],
        ])
        data = parsers.parse_data_csv(body, channel_families=("aod",))
        self.assertEqual(len(data.points), 2)
        self.assertEqual(data.points[0].wavelength, "AOD_551nm")
        self.assertAlmostEqual(data.points[0].aod, 0.251)
        self.assertEqual(data.meta.extras.get("main_channel_aod"),
                         "aod_551nm")
        # The promoted column stays in values (its series is the main one);
        # the main_channel marker is what stops a duplicate channel entity.
        self.assertIn("aod_551nm", data.values)

    def test_preferred_column_wins_when_it_has_data(self):
        body = _csv([
            ["Site", "16:09:2026", "08:25:04", 259, 259.35,
             0.200, 0.251, 0.300, 0.120],
        ])
        data = parsers.parse_data_csv(body, channel_families=("aod",))
        self.assertEqual(data.points[0].wavelength, "AOD_500nm")
        self.assertAlmostEqual(data.points[0].aod, 0.2)
        self.assertEqual(data.meta.extras.get("main_channel_aod"), "aod_500nm")


class SpectrumTests(unittest.TestCase):
    def test_spectrum_is_wavelength_ordered_and_numeric(self):
        now = dt.datetime.now(dt.timezone.utc)
        data = _data(with_points=False)
        data.values = {
            "aod": [parsers.AodPoint(time=now, aod=0.2, wavelength="AOD_500nm")],
            "aod_870nm": [parsers.AodPoint(time=now, aod=0.12,
                                           wavelength="AOD_870nm")],
            "aod_440nm": [parsers.AodPoint(time=now, aod=0.30,
                                           wavelength="AOD_440nm")],
            "ssa": [parsers.AodPoint(time=now, aod=0.9, wavelength="SSA_440nm")],
        }
        spec = parsers.channel_spectrum(data, "aod")
        self.assertEqual([nm for nm, _ in spec], [440, 500, 870])
        self.assertEqual([val for _, val in spec], [0.3, 0.2, 0.12])
        # The ssa family is separate.
        self.assertEqual(parsers.channel_spectrum(data, "ssa"), [])

    def test_angstrom_exponent(self):
        now = dt.datetime.now(dt.timezone.utc)
        data = _data(with_points=False)
        data.values = {
            "aod_440nm": [parsers.AodPoint(time=now, aod=0.30,
                                           wavelength="AOD_440nm")],
            "aod_870nm": [parsers.AodPoint(time=now, aod=0.12,
                                           wavelength="AOD_870nm")],
        }
        # alpha = -ln(0.30/0.12)/ln(440/870) = 1.3438 (rounded to 1.344)
        alpha = parsers.angstrom_440_870(data)
        assert alpha is not None
        self.assertAlmostEqual(alpha, 1.344, delta=0.001)

    def test_angstrom_is_none_without_channels(self):
        data = _data(with_points=False)
        data.values = {"aod": []}
        self.assertIsNone(parsers.angstrom_440_870(data))


def _flatten(obj, prefix=""):
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            out.add(key)
            out |= _flatten(v, key)
    return out


def _placeholders(text):
    import re
    return set(re.findall(r"\{(\w+)\}", text or ""))


class TranslationParityTests(unittest.TestCase):
    """Every string in strings.json must exist in en.json and es.json.

    v0.7.0: the api_failing repair issue was added to strings.json and
    es.json but not to en.json, so English users saw the raw translation key.
    """

    def _load(self, name):
        with open(os.path.join(CC_DIR, name), encoding="utf-8") as fh:
            return json.load(fh)

    def test_translations_cover_strings_json(self):
        base = self._load("strings.json")
        base_keys = _flatten(base)
        for lang in ("en", "es"):
            other = self._load(os.path.join("translations", f"{lang}.json"))
            missing = base_keys - _flatten(other)
            self.assertEqual(missing, set(),
                             f"{lang}.json is missing keys: {sorted(missing)}")

    def test_placeholders_match(self):
        base = self._load("strings.json")

        def walk(node, prefix=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from walk(v, f"{prefix}.{k}" if prefix else k)
            elif isinstance(node, str):
                yield prefix, node

        base_ph = {k: _placeholders(v) for k, v in walk(base)}
        for lang in ("en", "es"):
            other = self._load(os.path.join("translations", f"{lang}.json"))
            for key, text in walk(other):
                self.assertEqual(_placeholders(text), base_ph.get(key, set()),
                                 f"{lang}.json placeholder mismatch at {key}")


class EntityDefinitionTests(unittest.TestCase):
    """Statistics + display metadata must be set on every measurement sensor."""

    def test_every_measurement_sensor_is_statistics_eligible(self):
        from custom_components.aeronet import sensor as sm
        for desc in sm.SENSORS:
            if desc.key in ("last_data", "latitude", "longitude", "elevation"):
                continue
            self.assertEqual(desc.state_class, "measurement",
                             f"{desc.key} has no state_class")
            self.assertIsNotNone(desc.suggested_display_precision,
                                 f"{desc.key} has no display precision")
            self.assertIsNone(getattr(desc, "native_unit_of_measurement",
                                      None),
                              f"{desc.key} carries a unit")

    def test_product_sensors_are_statistics_eligible(self):
        from custom_components.aeronet import sensor as sm
        for product, descs in sm.PRODUCT_SENSORS.items():
            for desc in descs:
                self.assertEqual(desc.state_class, "measurement",
                                 f"{product}/{desc.key} has no state_class")
                self.assertIsNotNone(desc.suggested_display_precision,
                                     f"{product}/{desc.key} has no precision")

    def test_channel_sensors_are_statistics_eligible(self):
        from custom_components.aeronet import sensor as sm
        for channel in ("aod_440nm", "ssa_440nm"):
            desc = sm.channel_description(channel)
            self.assertEqual(desc.state_class, "measurement")
            self.assertIsNotNone(desc.suggested_display_precision)

    def test_latitude_and_longitude_do_not_fake_a_distance_unit(self):
        from custom_components.aeronet import sensor as sm
        for key in ("latitude", "longitude"):
            desc = next(d for d in sm.SENSORS if d.key == key)
            self.assertIsNone(getattr(desc, "device_class", None),
                              f"{key} must not claim device_class distance")


if __name__ == "__main__":
    unittest.main()
