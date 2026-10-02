"""v0.5.1 lifecycle behavior tests (review C1).

Drives the REAL ``custom_components.aeronet.async_setup_entry`` /
``async_unload_entry`` end-to-end against fake HA scaffolding, replacing
the old source-grep assertion. Home Assistant is not installed here, so
minimal fakes stand in for hass/config entry and the data coordinator —
but the refcount machinery under test (hold/release, shutdown scheduling,
setup ordering) is the production code.

Covered (review C1 — ghost coordinators on setup retry):
- a failed first refresh must NOT forward platforms (refresh-before-setup
  order),
- a failed first refresh must shut the data coordinator down (no leaked
  refresh timer) and release the site-list hold before re-raising,
- the site-list refcount is idempotent per entry: repeated setup attempts
  hold once, and unload releases exactly once,
- release actually runs the coroutine shutdown HA defines (a bare call
  would leave the weekly poll timer alive).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from homeassistant.const import Platform  # noqa: E402


def _ensure_issue_registry() -> None:
    """coordinators.py imports the issue registry; add a stub if absent."""
    if "homeassistant.helpers.issue_registry" in sys.modules:
        return
    m = types.ModuleType("homeassistant.helpers.issue_registry")
    m.IssueSeverity = types.SimpleNamespace(WARNING="warning")
    m.async_create_issue = lambda *a, **k: None
    m.async_delete_issue = lambda *a, **k: None
    sys.modules["homeassistant.helpers.issue_registry"] = m


_ensure_issue_registry()

from custom_components.aeronet import const  # noqa: E402
import custom_components.aeronet as aeronet  # noqa: E402
import custom_components.aeronet.coordinators as coordinators  # noqa: E402

URL = const.SITE_LIST_URL

ENTRY_DATA = {
    "site": "Madrid",
    "email": "",
    "level": "1.5",
    "interval_min": 60,
    "products": ["AOD"],
}


class ConfigEntryNotReady(Exception):
    """Raised by the fake coordinator's failed first refresh."""


class FakeTask:
    """Records cancellation like a real asyncio.Task would."""

    def __init__(self, coro):
        self.coro = coro
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        if not self.coro.cr_await:
            self.coro.close()

    def done(self):
        return self.coro.cr_await is None and self.coro.cr_frame is None


class FakeConfigEntries:
    def __init__(self):
        self.forwarded = []

    async def async_forward_entry_setups(self, entry, platforms):
        FakeDataCoordinator.order.append("forward")
        self.forwarded.append((entry.entry_id, list(platforms)))
        return True

    async def async_unload_platforms(self, entry, platforms):
        return True


class FakeHass:
    def __init__(self):
        self.data = {}
        self.config_entries = FakeConfigEntries()
        self.created_tasks = []

    def async_create_task(self, coro):
        FakeDataCoordinator.order.append("create_task")
        task = FakeTask(coro)
        self.created_tasks.append(task)
        return task


class FakeEntry:
    def __init__(self, entry_id="E1", data=None, options=None):
        self.entry_id = entry_id
        self.data = dict(data or {})
        self.options = dict(options or {})
        self.unload_hooks = []
        self.update_listeners = []

    def async_on_unload(self, cb):
        self.unload_hooks.append(cb)

        def _remove():
            try:
                self.unload_hooks.remove(cb)
            except ValueError:
                pass

        return _remove

    def add_update_listener(self, cb):
        self.update_listeners.append(cb)

        def _remove():
            try:
                self.update_listeners.remove(cb)
            except ValueError:
                pass

        return _remove


class FakeSitesCoordinator:
    """Stand-in registered in the real module-level coordinator cache."""

    def __init__(self, hass, url=URL):
        self.hass = hass
        self.url = url
        self._url = url
        self.data = [{"name": "Madrid"}]  # non-None: no background refresh
        self.is_shut_down = False
        self.shutdown_runs = 0

    async def async_shutdown(self):
        self.shutdown_runs += 1
        self.is_shut_down = True


class FakeDataCoordinator:
    """Data coordinator double that models HA's refresh-timer semantics.

    Constructing one schedules a refresh timer (``timer``); a failed
    ``async_config_entry_first_refresh`` leaves it armed — only
    ``async_shutdown`` cancels it. That is the ghost-poller property the
    C1 fix must break.
    """

    # Class-level switch so tests can flip it before setup creates one.
    fail_first_refresh = False
    order = None  # shared call-order log
    instances = []

    def __init__(self, hass, session, *, email="", level="", interval_min=60,
                 site="", products=None, entry_id=""):
        self.hass = hass
        self.site = site
        self.entry_id = entry_id
        self.products = products or []
        self.data = None
        self.first_refresh_calls = 0
        self.shutdown_calls = 0
        self.timer = "scheduled-refresh"  # armed on construction
        FakeDataCoordinator.instances.append(self)
        if FakeDataCoordinator.order is not None:
            FakeDataCoordinator.order.append("create_coord")

    async def async_config_entry_first_refresh(self):
        self.first_refresh_calls += 1
        if FakeDataCoordinator.order is not None:
            FakeDataCoordinator.order.append("first_refresh")
        if FakeDataCoordinator.fail_first_refresh:
            raise ConfigEntryNotReady("NASA down")
        self.data = {"ok": True}

    async def async_shutdown(self):
        self.shutdown_calls += 1
        self.timer = None  # refresh timer cancelled


class GhostCoordinatorTests(unittest.TestCase):
    """C1: a setup retry that hits a failed first poll must leave nothing
    behind — no platforms, no armed refresh timer, no site-list hold."""

    def setUp(self):
        coordinators._sites_refs.clear()
        coordinators._sites_coordinators.clear()
        coordinators._shutdown_tasks.clear()
        aeronet._HELD_SITES.clear()
        FakeDataCoordinator.instances = []
        FakeDataCoordinator.order = []
        FakeDataCoordinator.fail_first_refresh = False

    def tearDown(self):
        coordinators._sites_refs.clear()
        coordinators._sites_coordinators.clear()
        coordinators._shutdown_tasks.clear()
        aeronet._HELD_SITES.clear()

    def _env(self):
        hass = FakeHass()
        sites = FakeSitesCoordinator(hass)
        coordinators._sites_coordinators[URL] = sites
        aeronet.AeronetDataCoordinator = FakeDataCoordinator
        entry = FakeEntry(data=dict(ENTRY_DATA))
        return hass, entry, sites

    def _last_coord(self):
        return aeronet.AeronetDataCoordinator.instances[-1]

    def test_failed_first_refresh_leaves_no_ghost(self):
        hass, entry, sites = self._env()
        FakeDataCoordinator.fail_first_refresh = True

        async def scenario():
            with self.assertRaises(ConfigEntryNotReady):
                await aeronet.async_setup_entry(hass, entry)
            await asyncio.sleep(0)  # let scheduled shutdown tasks run

        asyncio.run(scenario())

        coord = self._last_coord()
        # First refresh was attempted exactly once, and platforms were never
        # forwarded: refresh happens BEFORE async_forward_entry_setups.
        self.assertEqual(coord.first_refresh_calls, 1)
        self.assertEqual(hass.config_entries.forwarded, [])
        self.assertEqual(FakeDataCoordinator.order,
                         ["create_coord", "first_refresh"])
        # The failed coordinator was shut down: its refresh timer is gone
        # (without shutdown it would keep polling NASA forever as a ghost).
        self.assertEqual(coord.shutdown_calls, 1)
        self.assertIsNone(coord.timer)
        # The site-list hold was released: refcount back to zero and the
        # shared coordinator's own shutdown actually ran.
        self.assertEqual(coordinators._sites_refs, {})
        self.assertEqual(aeronet._HELD_SITES, {})
        self.assertEqual(sites.shutdown_runs, 1)

    def test_retry_leaves_refcount_at_one_not_n_plus_1(self):
        """N failed retries used to inflate _sites_refs to N+1, so the last
        unload left the shared site coordinator alive. Now every failed
        attempt releases its hold (and shuts its coordinator down), and the
        successful attempt holds exactly once."""
        hass, entry, sites = self._env()
        fakes = [sites]

        async def attempt():
            # Each retry finds an empty coordinator cache and re-creates the
            # shared site coordinator (as get_sites_coordinator does).
            fresh = FakeSitesCoordinator(hass)
            fakes.append(fresh)
            coordinators._sites_coordinators[URL] = fresh
            await aeronet.async_setup_entry(hass, entry)
            await asyncio.sleep(0)

        async def scenario():
            # Two failing attempts (HA retry loop), then a good one.
            FakeDataCoordinator.fail_first_refresh = True
            for _ in range(2):
                with self.assertRaises(ConfigEntryNotReady):
                    await attempt()
            self.assertEqual(coordinators._sites_refs, {})

            FakeDataCoordinator.fail_first_refresh = False
            await attempt()
            self.assertEqual(coordinators._sites_refs[URL], 1)
            self.assertEqual(aeronet._HELD_SITES, {entry.entry_id: URL})

            # Unload: the hold is released exactly once and the shared
            # coordinator is shut down.
            self.assertTrue(await aeronet.async_unload_entry(hass, entry))
            for cb in list(entry.unload_hooks):
                cb()
            await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(coordinators._sites_refs, {})
        self.assertEqual(aeronet._HELD_SITES, {})
        # One shutdown per failed attempt (its own shared coordinator) plus
        # the final unload; the pre-retry placeholder was never used.
        self.assertEqual(sum(f.shutdown_runs for f in fakes), 3)

    def test_hold_is_idempotent_per_entry(self):
        """Re-running setup on the same entry must not double-hold."""
        hass, entry, sites = self._env()

        async def scenario():
            await aeronet.async_setup_entry(hass, entry)
            await aeronet.async_setup_entry(hass, entry)  # re-setup
            self.assertEqual(coordinators._sites_refs[URL], 1)
            self.assertEqual(len(aeronet._HELD_SITES), 1)
            # Unload hooks (the single registered release + none extra) drop
            # the refcount to zero.
            for cb in list(entry.unload_hooks):
                cb()
            self.assertEqual(coordinators._sites_refs, {})
            self.assertEqual(aeronet._HELD_SITES, {})
            await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(sites.shutdown_runs, 1)

    def test_unload_releases_exactly_once(self):
        hass, entry, sites = self._env()

        async def scenario():
            await aeronet.async_setup_entry(hass, entry)
            hooks = list(entry.unload_hooks)
            for cb in hooks:
                cb()
            await asyncio.sleep(0)
            self.assertEqual(coordinators._sites_refs, {})
            self.assertEqual(sites.shutdown_runs, 1)
            # A second unload pass (retry teardown, force_remove) must be a
            # no-op: no negative refcount, no second shutdown.
            for cb in hooks:
                cb()
            await asyncio.sleep(0)

        asyncio.run(scenario())
        self.assertEqual(sites.shutdown_runs, 1)

    def test_coroutine_shutdown_is_actually_scheduled(self):
        """DataUpdateCoordinator.async_shutdown is a coroutine in HA: the
        release path must schedule it, not call-and-discard it."""
        ran = []

        class CoroShutdownCoord:
            def __init__(self):
                self.hass = None

            async def async_shutdown(self):
                ran.append(True)

        coordinators._sites_coordinators[URL] = CoroShutdownCoord()
        coordinators._sites_refs[URL] = 1

        async def scenario():
            coordinators.release_sites_coordinator(URL)
            await asyncio.sleep(0)  # scheduled task needs a loop tick

        asyncio.run(scenario())
        self.assertEqual(ran, [True])

    def test_setup_success_forwards_after_refresh_with_data(self):
        """Happy path sanity: refresh first, then forward platforms."""
        hass, entry, sites = self._env()

        async def scenario():
            self.assertTrue(await aeronet.async_setup_entry(hass, entry))

        asyncio.run(scenario())
        self.assertEqual(
            FakeDataCoordinator.order,
            ["create_coord", "first_refresh", "forward"])
        coord = self._last_coord()
        self.assertEqual(coord.shutdown_calls, 0)
        self.assertIsNotNone(coord.data)
        self.assertEqual(hass.config_entries.forwarded,
                         [(entry.entry_id, [Platform.SENSOR,
                                            Platform.SELECT])])
        # The per-entry store is registered for the platforms/listener.
        store = hass.data[const.DOMAIN][entry.entry_id]
        self.assertIs(store["data"], coord)
        self.assertIs(store["sites"], sites)


if __name__ == "__main__":
    unittest.main()
