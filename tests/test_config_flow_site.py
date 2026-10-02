"""Config-flow unique_id behavior tests (v0.6.0, review m6).

AERONET station matching is case-insensitive (parsers._canonical_site);
the unique_id must be normalized the same way, and a legacy cased
unique_id must still block a duplicate entry at flow time.
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

from custom_components.aeronet import config_flow  # noqa: E402


def _entry(uid):
    return types.SimpleNamespace(entry_id="E", unique_id=uid, data={},
                                 options={})


class SiteAlreadyConfiguredTests(unittest.TestCase):
    def _hass(self, entries):
        return types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: entries))

    def test_case_insensitive_match_against_legacy_uid(self):
        hass = self._hass([_entry("aeronet_Madrid")])
        self.assertTrue(config_flow.site_already_configured(hass, "MADRID"))

    def test_underscore_insensitive_match(self):
        hass = self._hass([_entry("aeronet_Mexico_City")])
        self.assertTrue(
            config_flow.site_already_configured(hass, "mexico city"))

    def test_different_station_does_not_match(self):
        hass = self._hass([_entry("aeronet_madrid")])
        self.assertFalse(
            config_flow.site_already_configured(hass, "Valladolid"))

    def test_entries_without_unique_id_are_ignored(self):
        hass = self._hass([_entry("")])
        self.assertFalse(
            config_flow.site_already_configured(hass, "Madrid"))

    def test_hass_without_config_entries_is_not_a_crash(self):
        self.assertFalse(config_flow.site_already_configured(
            types.SimpleNamespace(), "Madrid"))


class FlowUniqueIdNormalizationTests(unittest.TestCase):
    def test_step_user_stores_canonical_unique_id(self):
        flow = config_flow.AeronetConfigFlow()
        flow.hass = types.SimpleNamespace()  # no existing entries
        result = asyncio.run(flow.async_step_user({
            "site": "Valladolid", "products": ["AOD"],
        }))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(flow._unique_id, "aeronet_valladolid")

    def test_step_user_aborts_on_case_insensitive_duplicate(self):
        flow = config_flow.AeronetConfigFlow()
        flow.hass = self._hass_with(_entry("aeronet_VALLADOLID"))
        result = asyncio.run(flow.async_step_user({
            "site": "Valladolid", "products": ["AOD"],
        }))
        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "already_configured")

    @staticmethod
    def _hass_with(entry):
        return types.SimpleNamespace(
            config_entries=types.SimpleNamespace(
                async_entries=lambda _domain: [entry]))


class OptionsFlowEntryBindingTests(unittest.TestCase):
    """m7: the flow uses OptionsFlowWithConfigEntry; the entry is reachable
    via the `config_entry` property (no deprecated __init__ override)."""

    def test_flow_reads_entry_via_config_entry_property(self):
        entry = types.SimpleNamespace(
            entry_id="E1", data={"site": "X"}, options={})
        flow = config_flow.AeronetOptionsFlow(entry)
        flow.hass = types.SimpleNamespace(data={})
        self.assertIs(flow.config_entry, entry)
        result = asyncio.run(flow.async_step_init(None))
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")

    def test_untouched_save_normalizes_and_creates_entry(self):
        entry = types.SimpleNamespace(
            entry_id="E1",
            data={"site": "X", "products": ["AOD"]},
            options={})
        flow = config_flow.AeronetOptionsFlow(entry)
        # A user_input that carries the untouched sentinel normalizes away
        # CONF_CHANNELS (absent = all channels detected).
        result = asyncio.run(flow.async_step_init({
            "email": "", "level": "1.5", "interval_min": 60,
            "products": ["AOD"], "channels": [""],
            "site_list_url": config_flow.SITE_LIST_URL,
        }))
        self.assertEqual(result["type"], "create_entry")
        self.assertNotIn("channels", result["data"])


if __name__ == "__main__":
    unittest.main()
