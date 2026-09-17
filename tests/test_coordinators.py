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
    # Mock issue_registry
    issue_reg = types.ModuleType("homeassistant.helpers.issue_registry")
    
    class IssueSeverity:
        WARNING = "warning"
    
    def async_create_issue(*args, **kwargs):
        pass
    
    def async_delete_issue(*args, **kwargs):
        pass
    
    issue_reg.IssueSeverity = IssueSeverity
    issue_reg.async_create_issue = async_create_issue 
    issue_reg.async_delete_issue = async_delete_issue

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
    sys.modules["homeassistant.helpers.issue_registry"] = issue_reg
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


class SiteListLifecycleTests(unittest.TestCase):
    """v0.5.0 F1: shared site coordinators must stop polling when the last
    config entry using them is unloaded (module dict kept them alive, and
    their timers kept hitting NASA forever)."""

    def setUp(self):
        coordinators._sites_cache.clear()
        coordinators._sites_saved_at.clear()
        coordinators._sites_coordinators.clear()
        coordinators._sites_refs.clear()
        Store.data.clear()

    def _fake_hass(self):
        return types.SimpleNamespace(
            async_create_task=lambda coro: coro.close())

    def test_get_increments_and_release_shuts_down(self):
        fake = coordinators.SiteListCoordinator.__new__(
            coordinators.SiteListCoordinator)
        fake.hass = self._fake_hass()
        fake.data = None
        fake.url = URL
        fake.shutdown_calls = []

        def shutdown():
            fake.shutdown_calls.append(True)
            coordinators._sites_coordinators.pop(URL, None)
            coordinators._sites_refs.pop(URL, None)

        fake.async_shutdown = shutdown
        coordinators._sites_coordinators[URL] = fake

        # get_sites_coordinator is a pure lookup (the config flow calls it
        # too); references are taken explicitly by async_setup_entry.
        self.assertIs(coordinators.get_sites_coordinator(
            fake.hass, None, url=URL), fake)
        self.assertEqual(coordinators._sites_refs.get(URL, 0), 0)

        coordinators.hold_sites_coordinator(URL)
        self.assertEqual(coordinators._sites_refs[URL], 1)
        # A second entry sharing the same URL bumps the refcount.
        coordinators.hold_sites_coordinator(URL)
        self.assertEqual(coordinators._sites_refs[URL], 2)

        # Unloading one entry keeps it alive.
        coordinators.release_sites_coordinator(URL)
        self.assertEqual(fake.shutdown_calls, [])
        # Unloading the last one shuts polling down and forgets it.
        coordinators.release_sites_coordinator(URL)
        self.assertEqual(fake.shutdown_calls, [True])
        self.assertNotIn(URL, coordinators._sites_coordinators)

    def test_release_unknown_url_is_noop(self):
        coordinators.release_sites_coordinator("https://nope.test/x.txt")

    def test_shutdown_coordinator_is_replaced_not_reused(self):
        """A shut-down coordinator must never be handed back (its timer and
        listeners are dead after HA shutdown)."""
        dead = coordinators.SiteListCoordinator.__new__(
            coordinators.SiteListCoordinator)
        dead.hass = self._fake_hass()
        dead.data = None
        dead.is_shut_down = True
        coordinators._sites_coordinators[URL] = dead
        coordinators._sites_refs[URL] = 0

        coord = coordinators.get_sites_coordinator(
            dead.hass, None, url=URL)
        self.assertIsNot(coord, dead)


class FirstRefreshTests(unittest.TestCase):
    """v0.5.0 F2: setup must use async_config_entry_first_refresh so a dead
    first poll raises ConfigEntryNotReady and HA retries setup, instead of
    setting up entities that stay unavailable until the next full interval."""

    def test_setup_uses_first_refresh(self):
        path = os.path.join(
            os.path.dirname(__file__), "..", "custom_components",
            "aeronet", "__init__.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        setup = src.split("async def async_unload_entry")[0]
        self.assertIn(
            "async_config_entry_first_refresh", setup,
            "async_setup_entry must call async_config_entry_first_refresh "
            "on the data coordinator (ConfigEntryNotReady semantics)")


class OptionsListenerRefreshTests(unittest.TestCase):
    """v0.5.0 F3: an options save with unchanged values must not trigger a
    full multi-product fetch burst; only real changes may refresh."""

    def _run(self, entry_data, entry_options, snapshot):
        import tests.ha_stubs as ha_stubs
        ha_stubs.install()
        cc_dir = os.path.join(os.path.dirname(__file__), "..",
                              "custom_components")
        if cc_dir not in sys.path:
            sys.path.insert(0, cc_dir)
        import importlib
        mod = importlib.import_module("custom_components.aeronet")
        calls = []
        coord = types.SimpleNamespace(
            products=["AOD"],
            configure=lambda **kw: calls.append(("configure", kw)),
            async_refresh=lambda: calls.append(("refresh",)) or _noop_coro(),
        )
        hass = types.SimpleNamespace(
            data={"aeronet": {"E1": {
                "data": coord, "sites_url": "u",
                "config": dict(snapshot),
            }}},
            config_entries=types.SimpleNamespace(
                async_reload=lambda eid: calls.append(("reload",))
                or _noop_coro()),
        )
        entry = types.SimpleNamespace(
            entry_id="E1", data=entry_data, options=entry_options)
        asyncio.run(mod._async_update_listener(hass, entry))
        return calls

    def test_noop_options_save_does_not_refresh(self):
        data = {"email": "", "level": "1.5", "interval_min": 60,
                "products": ["AOD"], "site": "Madrid"}
        calls = self._run(data, {}, self._snapshot())
        self.assertEqual(calls, [])

    def _snapshot(self):
        from const import SITE_LIST_URL
        return {"email": "", "level": "1.5", "interval_min": 60,
                "products": ["AOD"], "site_list_url": SITE_LIST_URL}

    def test_changed_level_configures_and_refreshes(self):
        data = {"email": "", "level": "2.0", "interval_min": 60,
                "products": ["AOD"]}
        calls = self._run(data, {}, self._snapshot())
        self.assertEqual(calls[0][0], "configure")
        self.assertIn(("refresh",), calls)

    def test_site_only_change_does_not_refresh_via_listener(self):
        """A station switch persists entry.data (fires this listener) but the
        select entity already refreshes through set_site: the listener must
        stay silent or every station change doubles the NASA requests."""
        data = {"email": "", "level": "1.5", "interval_min": 60,
                "products": ["AOD"], "site": "Valladolid"}
        calls = self._run(data, {}, self._snapshot())
        self.assertEqual(calls, [])


def _noop_coro():
    async def _n():
        return None
    return _n()


class RepairIssueTests(unittest.TestCase):
    """v0.5.0 T5: AeronetDataCoordinator raises issues after consecutive failures."""

    def test_success_after_failure_clears_issue(self):
        import types
        from unittest.mock import MagicMock
        
        # Import directly, not via custom_components
        import coordinators
        
        # Mock hass and session
        hass = types.SimpleNamespace()
        session = types.SimpleNamespace()
        
        coord = coordinators.AeronetDataCoordinator(
            hass, session, email="test@example.com", level="1.5", 
            interval_min=60, site="Madrid", entry_id="test123"
        )
        
        # Simulate 3 failures (threshold), then success
        coord._consecutive_failures = 2  # almost at threshold
        coord._note_failure(Exception("Network timeout"))
        self.assertEqual(coord._consecutive_failures, 3)
        
        coord._note_success()
        self.assertEqual(coord._consecutive_failures, 0)

    def test_issue_id_from_entry_id(self):
        import types
        import coordinators
        
        hass = types.SimpleNamespace()
        session = types.SimpleNamespace()
        
        coord = coordinators.AeronetDataCoordinator(
            hass, session, email="", level="1.5", 
            interval_min=60, site="Madrid", entry_id="entry456"
        )
        
        self.assertEqual(coord._issue_id, "api_failing_entry456")


if __name__ == "__main__":
    unittest.main()
