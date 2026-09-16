"""Config flow for the NASA AERONET integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector

from .const import (
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    DEFAULT_INTERVAL_MIN,
    DEFAULT_LEVEL,
    DEFAULT_PRODUCTS,
    DEFAULT_SITE,
    DOMAIN,
    LEVELS,
    PRODUCTS,
)
from .coordinators import get_sites_coordinator

_LOGGER = logging.getLogger(__name__)


def _site_options(hass) -> list[str] | None:
    """Station names from the module cache, or None if not loaded yet."""
    try:
        coord = get_sites_coordinator(hass, async_get_clientsession(hass))
        sites = coord.data
    except Exception:  # pragma: no cover - defensive
        return None
    if sites:
        return sorted({s.name.strip() for s in sites if s.name.strip()})
    return None


class AeronetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    @staticmethod
    async def async_migrate_entry(hass, config_entry) -> bool:
        """Migrate v1 -> v2: add the products list (default ['AOD'])."""
        if config_entry.version > 2:
            return False
        if config_entry.version == 1:
            new_data = {**config_entry.data}
            new_data.setdefault(CONF_PRODUCTS, list(DEFAULT_PRODUCTS))
            try:
                hass.config_entries.async_update_entry(
                    config_entry, data=new_data, version=2
                )
            except AttributeError:  # older HA without version kwarg
                hass.config_entries.async_update_entry(config_entry, data=new_data)
            _LOGGER.info(
                "Migrated AERONET config entry '%s' to version 2 (products=%s)",
                config_entry.title, new_data[CONF_PRODUCTS],
            )
        return True

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            site = (user_input.get(CONF_SITE) or DEFAULT_SITE).strip()
            user_input = {**user_input, CONF_SITE: site}
            if not user_input.get(CONF_PRODUCTS):
                user_input[CONF_PRODUCTS] = list(DEFAULT_PRODUCTS)
            await self.async_set_unique_id(f"aeronet_{site}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"AERONET · {site}", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=self._user_schema(self.hass)
        )

    @staticmethod
    def _user_schema(hass) -> vol.Schema:
        options = _site_options(hass)
        site_field: Any
        if options:
            site_field = selector.SelectSelector(
                selector.SelectSelectorConfig(options=options, sort=True, mode="dropdown")
            )
        else:
            # Site list not fetched yet: plain text (validated in options flow /
            # runtime; an unknown site shows as a parameter error on first poll).
            site_field = selector.TextSelector()
        return vol.Schema(
            {
                vol.Optional(CONF_SITE, default=DEFAULT_SITE): site_field,
                vol.Optional(CONF_EMAIL, default=""): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
                ),
                vol.Required(CONF_LEVEL, default=DEFAULT_LEVEL): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=list(LEVELS.keys()))
                ),
                vol.Required(CONF_INTERVAL_MIN, default=DEFAULT_INTERVAL_MIN): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=1440, step=10, unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_PRODUCTS, default=list(DEFAULT_PRODUCTS)): (
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(PRODUCTS),
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                ),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AeronetOptionsFlow(config_entry)


class AeronetOptionsFlow(config_entries.OptionsFlow):
    """Tweak email/level/interval after setup (station changes via select)."""

    def __init__(self, config_entry) -> None:
        super().__init__()
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        cur = {**self._entry.data, **self._entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_EMAIL, default=cur.get(CONF_EMAIL, "")): str,
                    vol.Required(
                        CONF_LEVEL, default=cur.get(CONF_LEVEL, DEFAULT_LEVEL)
                    ): vol.In(list(LEVELS.keys())),
                    vol.Required(
                        CONF_INTERVAL_MIN,
                        default=cur.get(CONF_INTERVAL_MIN, DEFAULT_INTERVAL_MIN),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=1440)),
                    vol.Optional(
                        CONF_PRODUCTS,
                        default=list(cur.get(CONF_PRODUCTS) or DEFAULT_PRODUCTS),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=list(PRODUCTS),
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )
