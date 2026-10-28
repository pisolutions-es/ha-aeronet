"""Select platform: AERONET station picker (~1675 options)."""
from __future__ import annotations

import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_SITE, DOMAIN
from .coordinators import AeronetDataCoordinator, SiteListCoordinator
from .parsers import (
    dedupe_display_names,
    display_to_site_name,
    normalize_site,
)

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

    # The full station list travels in the state object (core delivers it via
    # capability_attributes so the UI dropdown can render). Keep it OUT of
    # the recorder database: with the historical 1675-station list the
    # attributes exceed HA's 16 KiB per-state limit and the recorder logs
    # "State attributes ... exceed maximum size of 16384 bytes". Core's
    # SelectEntity already marks `options` unrecorded; declaring it here
    # explicitly pins the behavior for our entity across HA versions.
    _unrecorded_attributes = frozenset({"options"})

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
        # v0.6.0 (review m3): no _attr_name — the strings' `site` translation
        # key ("Station") must own the name; a literal here silently
        # shadowed it (and its es.json entry).
        # In-flight station switch (v0.5.1, M2): a rapid re-selection
        # cancels the previous background fetch instead of stacking
        # duplicate request bursts.
        self._switch_task: asyncio.Task | None = None
        # v0.7.0 (review L4): cache the deduped dropdown list per payload.
        # dedupe_display_names() sorts and formats up to ~1675 stations and
        # used to run on every property access (i.e. on every state write).
        self._options_cache: tuple[object, list[str]] | None = None

    @property
    def device_info(self) -> DeviceInfo:
        # v0.6.0 (review m4): the name must follow the *entry's stored
        # station* — a select switch updates entry.data without reloading
        # the entry, and a DeviceInfo frozen at construction kept
        # advertising the previous station until the next restart.
        return DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=f"AERONET · {normalize_site(self._entry.data.get(CONF_SITE) or '')}",
            manufacturer="NASA AERONET",
            configuration_url="https://aeronet.gsfc.nasa.gov/",
        )

    @property
    def options(self) -> list[str]:
        sites = self.coordinator.data or []
        cached = self._options_cache
        if cached is not None and cached[0] is sites:
            return list(cached[1])
        names = dedupe_display_names(sites)
        current = normalize_site(self._data_coord.site)
        # v0.6.0 (review m4): map the current station through the same
        # dedupe logic before appending. If the station appears among the
        # display names under a coordinate suffix (duplicate station name),
        # appending the plain name would show BOTH variants in the
        # dropdown for the same station.
        if current and not any(
                display_to_site_name(n) == current for n in names):
            names.append(current)
        self._options_cache = (sites, names)
        return list(names)

    def _refresh_device_name(self, site: str) -> None:
        """Push the new station name into HA's Device Registry.

        v0.7.0 (review H5): HA core reads ``entity.device_info`` only when
        the entity is added, so the dynamic property alone never updated the
        Device page (nor the integration card's device) after a station
        switch — it kept the old station until the next restart.
        """
        try:
            registry = dr.async_get(self.hass)
            device = registry.async_get_device(
                identifiers={(DOMAIN, self._entry.entry_id)}
            )
            if device is not None:
                registry.async_update_device(
                    device.id, name=f"AERONET · {site}"
                )
        except Exception:  # pragma: no cover - registry must never break a switch
            _LOGGER.debug("AERONET device name update failed", exc_info=True)

    async def async_select_option(self, option: str) -> None:
        # Display labels may carry a dedupe coordinate suffix, and names must
        # be exact for AERONET (stray whitespace makes the service ignore the
        # site filter and return *all* stations), so recover the real station
        # name before persisting or requesting.
        option = display_to_site_name(option)
        self._attr_current_option = option
        self.async_write_ha_state()
        # Persist so the choice survives restarts, then re-poll the new site.
        # v0.7.0 (review H5): the entry title follows the station too, so the
        # Integrations card stops advertising the previous one.
        self.hass.config_entries.async_update_entry(
            self._entry,
            data={**self._entry.data, CONF_SITE: option},
            title=f"AERONET · {option}",
        )
        self._refresh_device_name(option)
        # v0.5.1 (M2): set_site awaits a full fetch (REQUEST_TIMEOUT_TOTAL of
        # 60 s x 3 attempts, plus backoff and Retry-After waits — worst case
        # ~13 minutes). Blocking the select.select_option service call that
        # long hangs the frontend and stacks duplicate bursts on re-clicks.
        # Run the re-poll in the background instead; a newer switch cancels
        # the previous in-flight one.
        if self._switch_task is not None and not self._switch_task.done():
            self._switch_task.cancel()
        self._switch_task = self.hass.async_create_task(
            self._data_coord.set_site(option)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel an in-flight station switch when the entity is unloaded.

        v0.7.0 (review M3): without this, a switch started right before a
        reload/unload finished afterwards and re-armed the poll timer on a
        coordinator whose entry was already gone.
        """
        if self._switch_task is not None and not self._switch_task.done():
            self._switch_task.cancel()
        self._switch_task = None
        await super().async_will_remove_from_hass()
