"""Config and options flow against the real HA flow manager.

The flows use HA's own selectors and `OptionsFlowWithConfigEntry`; these
tests prove the schemas validate and the entry is created/updated with the
values the user picked.
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from custom_components.aeronet.const import (
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    DOMAIN,
)

from .test_setup import fake_client  # noqa: F401  (pytest fixture reuse)


async def test_user_flow_creates_the_entry(hass, fake_client):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_SITE: "Valladolid",
            CONF_EMAIL: "",
            CONF_LEVEL: "1.5",
            CONF_INTERVAL_MIN: 60,
            CONF_PRODUCTS: ["AOD"],
        },
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "AERONET · Valladolid"
    assert result["data"][CONF_SITE] == "Valladolid"
    assert result["data"][CONF_PRODUCTS] == ["AOD"]


async def test_the_same_station_cannot_be_added_twice(hass, fake_client):
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    await hass.config_entries.flow.async_configure(
        first["flow_id"],
        {
            CONF_SITE: "Madrid",
            CONF_EMAIL: "",
            CONF_LEVEL: "1.5",
            CONF_INTERVAL_MIN: 60,
            CONF_PRODUCTS: ["AOD"],
        },
    )
    await hass.async_block_till_done()

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        second["flow_id"],
        {
            CONF_SITE: "Madrid",
            CONF_EMAIL: "",
            CONF_LEVEL: "1.5",
            CONF_INTERVAL_MIN: 60,
            CONF_PRODUCTS: ["AOD"],
        },
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_options_flow_updates_the_entry(hass, fake_client):
    from .test_setup import _entry

    entry = _entry()
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_LEVEL: "2.0", CONF_INTERVAL_MIN: 120},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_LEVEL] == "2.0"
    assert entry.options[CONF_INTERVAL_MIN] == 120
