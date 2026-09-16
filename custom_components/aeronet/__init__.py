"""Platform factories for the NASA AERONET integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    DEFAULT_LEVEL,
    DEFAULT_PRODUCTS,
    DEFAULT_SITE,
    DOMAIN,
)
from .coordinators import AeronetDataCoordinator, get_sites_coordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    # Kick off (non-blocking) the global station list so the select/flow can use it.
    sites_coord = get_sites_coordinator(hass, session)
    hass.async_create_task(sites_coord.async_refresh())

    data_coord = AeronetDataCoordinator(
        hass,
        session,
        email=entry.data.get(CONF_EMAIL, ""),
        level={**entry.data, **entry.options}.get(CONF_LEVEL, DEFAULT_LEVEL),
        interval_min={**entry.data, **entry.options}.get(CONF_INTERVAL_MIN, 60),
        site=entry.data.get(CONF_SITE, DEFAULT_SITE),
        products=(
            {**entry.data, **entry.options}.get(CONF_PRODUCTS)
            or list(DEFAULT_PRODUCTS)
        ),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "data": data_coord,
        "sites": sites_coord,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await data_coord.async_refresh()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reconfigure email/level/interval when options change.

    A products change requires re-creating entities, so the entry is
    reloaded in that case instead of reconfigured in place.
    """
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not store:
        return
    coord: AeronetDataCoordinator = store["data"]
    merged = {**entry.data, **entry.options}
    new_products = list(merged.get(CONF_PRODUCTS) or DEFAULT_PRODUCTS)
    if sorted(new_products) != sorted(coord.products):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    coord.configure(
        email=merged.get(CONF_EMAIL, ""),
        level=merged.get(CONF_LEVEL, DEFAULT_LEVEL),
        interval_min=int(merged.get(CONF_INTERVAL_MIN, 60)),
    )
    await coord.async_refresh()
