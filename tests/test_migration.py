"""Config-entry migration tests (v0.3.1 defect 1).

HA core calls ``async_migrate_entry`` on the integration *module*
(``custom_components/aeronet/__init__.py``), not on the ConfigFlow class
(homeassistant/config_entries.py: ``hasattr(component, "async_migrate_entry")``).
These tests drive the module-level handler exactly the way core does.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "custom_components"),
)

from tests.ha_stubs import install as _install_ha_stubs  # noqa: E402

_install_ha_stubs()

from custom_components.aeronet import const  # noqa: E402


class FakeEntry:
    """Stand-in for a stored ConfigEntry as core hands it to the handler."""

    def __init__(self, version: int, data: dict):
        self.version = version
        self.data = data
        self.title = "AERONET · Valladolid"


class FakeConfigEntries:
    def __init__(self, owner):
        self._owner = owner

    def async_update_entry(self, entry, *, data=None, version=None):
        self._owner._update(entry, data=data, version=version)


class FakeHass:
    """Captures async_update_entry calls; mimics HA >= 2024.10 semantics."""

    def __init__(self):
        self.updates: list[dict] = []
        self.config_entries = FakeConfigEntries(self)

    def _update(self, entry, *, data=None, version=None):
        if version is not None:
            if version < entry.version:
                raise ValueError("downgrade refused")  # core: downgrades unsupported
            entry.version = version
        if data is not None:
            entry.data = data
        self.updates.append({"data": data, "version": version})


def _run(coro):
    return asyncio.run(coro)


class TestModuleMigrationHandler(unittest.TestCase):
    def _handler(self):
        import custom_components.aeronet as integration_module
        # The handler must live on the integration MODULE: that is what
        # HA core introspects (defect 1 of the v0.2.0 update log).
        migrate = getattr(integration_module, "async_migrate_entry", None)
        self.assertIsNotNone(
            integration_module.async_migrate_entry,
            "async_migrate_entry must be defined in the integration module",
        )
        return integration_module.async_migrate_entry

    def test_module_exposes_handler(self):
        self._handler()

    def test_v1_entry_upgraded_in_place(self):
        migrate = self._handler()
        hass = FakeHass()
        entry = FakeEntry(1, {const.CONF_EMAIL: "a@b.c", const.CONF_SITE: "Valladolid",
                             const.CONF_LEVEL: "1.5", const.CONF_INTERVAL_MIN: 60})
        self.assertTrue(_run(migrate(hass, entry)))
        self.assertEqual(entry.version, const.ENTRY_VERSION)
        self.assertEqual(entry.data[const.CONF_PRODUCTS], list(const.DEFAULT_PRODUCTS))
        # original keys preserved
        self.assertEqual(entry.data[const.CONF_SITE], "Valladolid")
        # exactly one persisted update carrying the new version
        self.assertEqual(len(hass.updates), 1)
        self.assertEqual(hass.updates[0]["version"], const.ENTRY_VERSION)

    def test_current_version_is_noop(self):
        migrate = self._handler()
        hass = FakeHass()
        entry = FakeEntry(const.ENTRY_VERSION, {const.CONF_SITE: "X",
                                                const.CONF_PRODUCTS: ["AOD"]})
        self.assertTrue(_run(migrate(hass, entry)))
        self.assertEqual(hass.updates, [])
        self.assertEqual(entry.data[const.CONF_PRODUCTS], ["AOD"])

    def test_handler_is_idempotent(self):
        migrate = self._handler()
        hass = FakeHass()
        entry = FakeEntry(1, {const.CONF_SITE: "Valladolid"})
        self.assertTrue(_run(migrate(hass, entry)))
        self.assertTrue(_run(migrate(hass, entry)))  # second pass: no-op
        self.assertEqual(len(hass.updates), 1)

    def test_future_version_refused(self):
        migrate = self._handler()
        hass = FakeHass()
        entry = FakeEntry(const.ENTRY_VERSION + 1, {const.CONF_SITE: "X"})
        self.assertFalse(_run(migrate(hass, entry)))
        self.assertEqual(hass.updates, [])

    def test_config_flow_handler_delegates_same_result(self):
        # The ConfigFlow class keeps a complementary handler; both must agree.
        from custom_components.aeronet.config_flow import AeronetConfigFlow
        hass = FakeHass()
        entry = FakeEntry(1, {const.CONF_SITE: "Valladolid"})
        self.assertTrue(_run(AeronetConfigFlow.async_migrate_entry(hass, entry)))
        self.assertEqual(entry.version, const.ENTRY_VERSION)
        self.assertIn(const.CONF_PRODUCTS, entry.data)

    def test_config_flow_version_matches_module_constant(self):
        from custom_components.aeronet.config_flow import AeronetConfigFlow
        self.assertEqual(AeronetConfigFlow.VERSION, const.ENTRY_VERSION)


if __name__ == "__main__":
    unittest.main()
