"""Tests for coordinator disk-cache persistence and 30-day widening.

Home Assistant is not installed in the host test env, so minimal module
stubs stand in; coordinators are constructed via __new__ (bypassing the
DataUpdateCoordinator base __init__) and their update paths are driven
directly with scripted fake clients.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import os
import sys
import types
import unittest


# --- Home Assistant module stubs (installed before importing coordinators)
def _install_stubs():
    ha = types.ModuleType("homeassistant")
    core = types.ModuleType("homeassistant.core")

    class HomeAssistant:  # minimal
        def async_create_task(self, coro):
            coro.close()  # never scheduled in tests

    core.HomeAssistant = HomeAssistant

    helpers = types.ModuleType("homeassistant.helpers")
    upd = types.ModuleType("homeassistant.helpers.update_coordinator")

    class DataUpdateCoordinator:
        def __init__(self, hass, logger, name=None, update_interval=None):
            self.hass = hass
            self.data = None
            self.update_interval = update_interval

        async def async_refresh(self):
            pass

    class UpdateFailed(Exception):
        pass

    upd.DataUpdateCoordinator = DataUpdateCoordinator
    upd.UpdateFailed = UpdateFailed

    stor = types.ModuleType("homeassistant.helpers.storage")

    class Store:
        """In-memory fake of the HA storage helper."""
        data: dict = {}

        def __init__(self, hass, version, key, private=False):
            self.key = key

        async def async_load(self):
            return Store.data.get(self.key)

        async def async_save(self, payload):
            Store.data[self.key] = payload

    stor.Store = Store

    aiohttp_mod = types.ModuleType("aiohttp")
    aiohttp_mod.ClientError = Exception
    aiohttp_mod.ClientSession = object
    aiohttp_mod.ClientTimeout = lambda **kw: None

    sys.modules.setdefault("aiohttp", aiohttp_mod)
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = upd
    sys.modules["homeassistant.helpers.storage"] = stor


_install_stubs()

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "custom_components", "aeronet"),
)

import coordinators  # noqa: E402
import parsers  # noqa: E402
import site_cache  # noqa: E402
from homeassistant.helpers.storage import Store  # noqa: E402

URL = "https://example.test/list.txt"


def _data(with_points=True):
    d = parsers.AeronetData(
        meta=parsers.SiteMeta(name="X", latitude=1, longitude=2, elevation=3))
    if with_points:
        d.points.append(parsers.AodPoint(
            time=dt.datetime(2026, 9, 16, tzinfo=dt.timezone.utc),
            aod=0.1, wavelength="AOD_500nm"))
    d.values = {"aod": list(d.points)}
    return d


class FakeClient:
    """Scripted AeronetClient: returns data per (method, days) request."""

    def __init__(self, results):
        self.results = results  # {(method, days): AeronetData | Exception}
        self.calls = []

    def _ret(self, method, days):
        self.calls.append((method, days))
        item = self.results.get((method, days), _data())
        if isinstance(item, Exception):
            raise item
        return item

    async def fetch_data(self, site, now, *, days=7):
        return self._ret("data", days)

    async def fetch_daily(self, site, now, *, days=7):
        return self._ret("daily", days)


class PayloadIsEmptyTests(unittest.TestCase):
    def test_empty(self):
        self.assertTrue(coordinators.payload_is_empty(None))
        self.assertTrue(coordinators.payload_is_empty(_data(False)))

    def test_nonempty(self):
        self.assertFalse(coordinators.payload_is_empty(_data(True)))


class SiteListStorageTests(unittest.TestCase):
    def setUp(self):
        coordinators.reset_site_list_state() if hasattr(
            coordinators, "reset_site_list_state") else None
        coordinators._sites_cache.clear()
        coordinators._sites_saved_at.clear()
        coordinators._sites_coordinators.clear()
        Store.data.clear()

    def _coord(self, url=URL):
        coord = coordinators.SiteListCoordinator.__new__(
            coordinators.SiteListCoordinator)
        coord._url = url
        coord.hass = types.SimpleNamespace(
            async_create_task=lambda coro: coro.close())
        coord.data = None
        return coord

    def test_update_saves_payload_with_date(self):
        coord = self._coord()
        sites = [parsers.Site(name="A", longitude=1.0, latitude=2.0,
                              elevation=3.0)]

        async def fake_fetch(url):
            return sites

        coord._client = types.SimpleNamespace(fetch_site_list=fake_fetch)
        out = asyncio.run(coord._async_update_data())
        self.assertEqual([s.name for s in out], ["A"])
        stored = Store.data[site_cache.storage_key(URL)]
        self.assertEqual(len(stored["sites"]), 1)
        self.assertFalse(site_cache.is_stale(
            stored, dt.datetime.now(dt.timezone.utc)))

    def test_load_storage_hydrates_dropdown(self):
        sites = [parsers.Site(name="B", longitude=1.0, latitude=2.0,
                              elevation=3.0)]
        Store.data[site_cache.storage_key(URL)] = site_cache.sites_to_payload(
            sites, dt.datetime.now(dt.timezone.utc))
        coord = self._coord()
        asyncio.run(coord.async_load_storage())
        self.assertEqual([s.name for s in coord.data], ["B"])

    def test_stale_cache_serves_then_refreshes(self):
        refreshed = []
        sites = [parsers.Site(name="C", longitude=1.0, latitude=2.0,
                              elevation=3.0)]
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10)
        Store.data[site_cache.storage_key(URL)] = site_cache.sites_to_payload(
            sites, old)

        coord = self._coord()

        async def fake_refresh():
            refreshed.append(True)

        coord.async_refresh = fake_refresh
        coord.hass = types.SimpleNamespace(
            async_create_task=lambda coro: asyncio.ensure_future(coro))
        asyncio.run(coord.async_load_storage())
        # dropdown usable immediately from the stale list...
        self.assertEqual([s.name for s in coord.data], ["C"])
        # ...and a background refresh was requested.
        self.assertEqual(refreshed, [True])

    def test_failure_falls_back_to_cache(self):
        sites = [parsers.Site(name="D", longitude=1.0, latitude=2.0,
                              elevation=3.0)]
        coordinators._sites_cache[URL] = sites
        coord = self._coord()

        async def boom(url):
            raise parsers.AeronetError("down")

        coord._client = types.SimpleNamespace(fetch_site_list=boom)
        out = asyncio.run(coord._async_update_data())
        self.assertIs(out, sites)


class WideningTests(unittest.TestCase):
    """30-day auto-widening when the 7-day window comes back empty."""

    def _coord(self, results):
        calls: list[tuple] = []

        class Recording(FakeClient):
            async def fetch_data(self_, site, now, *, days=7):
                calls.append(("data", days))
                return self_._ret("data", days)

            async def fetch_daily(self_, site, now, *, days=7):
                calls.append(("daily", days))
                return self_._ret("daily", days)

        coord = coordinators.AeronetDataCoordinator.__new__(
            coordinators.AeronetDataCoordinator)
        coord._products = ["AOD"]
        coord._email = ""
        coord._level = "1.5"
        coord.site = "Nowhere"
        coord.data = None
        coord._session = None
        coord._session_unused = None
        # The coordinator constructs an AeronetClient internally; inject the
        # scripted recording client instead.
        orig = coordinators.AeronetClient
        coordinators.AeronetClient = lambda *a, **k: Recording(results)
        self.addCleanup(setattr, coordinators, "AeronetClient", orig)
        coord._calls = calls
        return coord

    def test_empty_7d_retries_widened_to_30(self):
        coord = self._coord({
            ("data", 7): _data(False), ("daily", 7): _data(False),
            ("data", 30): _data(True), ("daily", 30): _data(True),
        })
        out = asyncio.run(coord._async_update_data())
        self.assertFalse(coordinators.payload_is_empty(out))
        self.assertIn(("data", 7), coord._calls)
        self.assertIn(("data", 30), coord._calls)

    def test_no_widening_when_data_present(self):
        coord = self._coord({
            ("data", 7): _data(True), ("daily", 7): _data(True),
        })
        out = asyncio.run(coord._async_update_data())
        self.assertFalse(coordinators.payload_is_empty(out))
        self.assertNotIn(("data", 30), coord._calls)

    def test_both_windows_empty_raises(self):
        coord = self._coord({
            ("data", 7): _data(False), ("daily", 7): _data(False),
            ("data", 30): _data(False), ("daily", 30): _data(False),
        })
        with self.assertRaises(coordinators.UpdateFailed) as ctx:
            asyncio.run(coord._async_update_data())
        self.assertIn("30 days", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
