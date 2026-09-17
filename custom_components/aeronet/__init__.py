"""Platform factories for the NASA AERONET integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_CHANNELS,
    CONF_EMAIL,
    CONF_INTERVAL_MIN,
    CONF_LEVEL,
    CONF_PRODUCTS,
    CONF_SITE,
    CONF_SITE_LIST_URL,
    DEFAULT_LEVEL,
    DEFAULT_PRODUCTS,
    DEFAULT_SITE,
    DOMAIN,
    ENTRY_VERSION,
    SITE_LIST_URL,
)
from .coordinators import (
    AeronetDataCoordinator,
    get_sites_coordinator,
    hold_sites_coordinator,
    release_sites_coordinator,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    # Hydrate the station list from disk first (so the config-flow dropdown
    # is ready on the very first boot), then refresh only when there is no
    # usable cached copy yet.
    sites_url = {**entry.data, **entry.options}.get(
        CONF_SITE_LIST_URL, SITE_LIST_URL
    )
    sites_coord = get_sites_coordinator(hass, session, url=sites_url)
    # v0.5.0: refcount so the shared site coordinator stops polling when the
    # last entry using it is unloaded (memory/timer leak otherwise).
    hold_sites_coordinator(sites_url)
    entry.async_on_unload(lambda: release_sites_coordinator(sites_url))
    if sites_coord.data is None:
        await sites_coord.async_load_storage()
    if sites_coord.data is None:
        hass.async_create_task(sites_coord.async_refresh())

    merged = {**entry.data, **entry.options}
    data_coord = AeronetDataCoordinator(
        hass,
        session,
        email=entry.data.get(CONF_EMAIL, ""),
        level=merged.get(CONF_LEVEL, DEFAULT_LEVEL),
        interval_min=merged.get(CONF_INTERVAL_MIN, 60),
        site=entry.data.get(CONF_SITE, DEFAULT_SITE),
        products=(merged.get(CONF_PRODUCTS) or list(DEFAULT_PRODUCTS)),
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "data": data_coord,
        "sites": sites_coord,
        # v0.5.0 snapshot of every option the update listener compares
        # against, so saving the dialog without changing anything does not
        # trigger a full multi-product fetch burst.
        "config": {
            CONF_EMAIL: merged.get(CONF_EMAIL, ""),
            CONF_LEVEL: merged.get(CONF_LEVEL, DEFAULT_LEVEL),
            CONF_INTERVAL_MIN: int(merged.get(CONF_INTERVAL_MIN, 60)),
            CONF_PRODUCTS: list(merged.get(CONF_PRODUCTS)
                                or DEFAULT_PRODUCTS),
            CONF_CHANNELS: list(merged.get(CONF_CHANNELS) or []),
            CONF_SITE_LIST_URL: sites_url,
            # Station changes are persisted to entry.data by the select
            # entity (which fires this listener) but applied through
            # set_site(); the listener must not fetch a second time.
            CONF_SITE: entry.data.get(CONF_SITE, DEFAULT_SITE),
        },
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    # v0.5.0: first_refresh raises ConfigEntryNotReady when the very first
    # poll fails, so HA retries setup instead of leaving entities
    # unavailable until the next full poll interval.
    await data_coord.async_config_entry_first_refresh()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a stored config entry to the current schema, in place.

    HA core invokes THIS module-level handler (it introspects the
    integration component, not the ConfigFlow class). Missing it caused
    "Migration handler not found for entry ... for aeronet" and aborted
    setup after updating from v0.1.x (schema v1).

    Steps are cumulative (v1 -> v2 -> ... -> ENTRY_VERSION) and the whole
    handler is idempotent: running it on an already-current entry is a
    no-op, and re-running after a partial failure finishes the job.
    """
    if entry.version > ENTRY_VERSION:
        _LOGGER.error(
            "AERONET config entry '%s' has version %s, newer than this"
            " integration supports (%s); not downgrading",
            entry.title, entry.version, ENTRY_VERSION,
        )
        return False

    data = {**entry.data}
    changed = False
    old_version = entry.version

    if entry.version < 2:
        # v1 -> v2 (v0.2.0): products list, default ["AOD"].
        if CONF_PRODUCTS not in data:
            data[CONF_PRODUCTS] = list(DEFAULT_PRODUCTS)
        changed = True

    if entry.version < 3:
        # v2 -> v3 (v0.4.0): multispectral channels. Nothing to add to
        # stored data — the channel selection lives in options, and its
        # absence means "all channels detected in the data". The version
        # bump is the migration; it is idempotent by construction.
        changed = True

    if changed:
        try:
            hass.config_entries.async_update_entry(
                entry, data=data, version=ENTRY_VERSION
            )
        except AttributeError:  # older HA without the version kwarg
            hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.info(
            "Migrated AERONET config entry '%s' from version %s to %s",
            entry.title, old_version, ENTRY_VERSION,
        )
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """React to config-entry updates.

    Compares the new merged options against the snapshot taken at setup:
    a save that changed nothing must not reconfigure, reload, or refresh
    (each refresh is a full multi-product request burst against NASA).
    A products/channels/site-list-source change requires re-creating
    entities, so the entry is reloaded in those cases.
    """
    store = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not store:
        return
    coord: AeronetDataCoordinator = store["data"]
    merged = {**entry.data, **entry.options}
    snap = store.get("config") or {}

    new_products = list(merged.get(CONF_PRODUCTS) or DEFAULT_PRODUCTS)
    if sorted(new_products) != sorted(snap.get(CONF_PRODUCTS)
                                      or DEFAULT_PRODUCTS):
        await hass.config_entries.async_reload(entry.entry_id)
        return
    if sorted(merged.get(CONF_CHANNELS) or []) != \
            sorted(snap.get(CONF_CHANNELS) or []):
        # Channel selection changed: newly selected channels may need
        # entities that do not exist yet, so rebuild the entity set.
        await hass.config_entries.async_reload(entry.entry_id)
        return
    if merged.get(CONF_SITE_LIST_URL, SITE_LIST_URL) != \
            snap.get(CONF_SITE_LIST_URL, SITE_LIST_URL):
        # Station-list source changed: rebind the sites coordinator.
        await hass.config_entries.async_reload(entry.entry_id)
        return

    new_email = merged.get(CONF_EMAIL, "")
    new_level = merged.get(CONF_LEVEL, DEFAULT_LEVEL)
    new_interval = int(merged.get(CONF_INTERVAL_MIN, 60))
    changed = (
        new_email != snap.get(CONF_EMAIL, "")
        or new_level != snap.get(CONF_LEVEL, DEFAULT_LEVEL)
        or new_interval != snap.get(CONF_INTERVAL_MIN, 60)
    )
    # A station-only change fires this listener because the select entity
    # persists entry.data, but the select already re-polls via set_site();
    # refreshing here would double every station-switch's request burst.
    if not changed:
        return
    coord.configure(
        email=new_email,
        level=new_level,
        interval_min=new_interval,
    )
    await coord.async_refresh()
