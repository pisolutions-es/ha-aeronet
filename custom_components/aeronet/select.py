"""Select platform: AERONET station picker (~1675 options)."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SITE, DOMAIN
from .coordinators import AeronetDataCoordinator, SiteListCoordinator
from .parsers import dedupe_display_names, display_to_site_name

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AeronetSiteSelect(store["data"], store["sites"], entry)])


class AeronetSiteSelect(CoordinatorEntity, SelectEntity):
    """Dropdown of AERONET stations, backed by the weekly site-list cache.

    Note: HA *core* suggests <=600 options per select entity; the full AERONET
    list has ~1675 names. Custom integrations may exceed the suggestion; see
    README for the known limitation.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "site"

    def __init__(
        self,
        data_coord: AeronetDataCoordinator,
        sites_coord: SiteListCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(sites_coord)
        self._data_coord = data_coord
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_site"
        self._attr_current_option = data_coord.site
        self._attr_name = "Station"
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"AERONET · {data_coord.site}",
            manufacturer="NASA AERONET",
            configuration_url="https://aeronet.gsfc.nasa.gov/",
        )

    @property
    def options(self) -> list[str]:
        sites = self.coordinator.data or []
        names = dedupe_display_names(sites)
        current = self._data_coord.site.strip()
        if current and current not in names:
            names.append(current)
        return names

    async def async_select_option(self, option: str) -> None:
        # Display labels may carry a dedupe coordinate suffix, and names must
        # be exact for AERONET (stray whitespace makes the service ignore the
        # site filter and return *all* stations), so recover the real station
        # name before persisting or requesting.
        option = display_to_site_name(option)
        self._attr_current_option = option
        self.async_write_ha_state()
        # Persist so the choice survives restarts, then re-poll the new site.
        self.hass.config_entries.async_update_entry(
            self._entry, data={**self._entry.data, CONF_SITE: option}
        )
        await self._data_coord.set_site(option)
