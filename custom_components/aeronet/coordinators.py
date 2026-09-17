"""DataUpdateCoordinator wrappers for AERONET site list + per-entry data."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

try:  # package import inside Home Assistant
    from .client import AeronetClient
    from .const import (
        CONF_LEVEL,
        DATA_WINDOW_DAYS,
        DATA_WINDOW_WIDE_DAYS,
        DEFAULT_PRODUCTS,
        DOMAIN,
        PRODUCTS_INVERSION,
        PRODUCT_AOD,
        PRODUCT_SDA,
        SITES_REFRESH_DAYS,
        SITE_LIST_URL,
    )
    from .parsers import (
        AeronetData,
        AeronetError,
        Site,
        normalize_site,
    )
    from .site_cache import (
        STORAGE_VERSION,
        is_stale,
        sites_from_payload,
        sites_to_payload,
        storage_key,
    )
except ImportError:  # flat import in stdlib-only unit tests
    from client import AeronetClient  # type: ignore
    from const import (  # type: ignore
        CONF_LEVEL,
        DATA_WINDOW_DAYS,
        DATA_WINDOW_WIDE_DAYS,
        DEFAULT_PRODUCTS,
        DOMAIN,
        PRODUCTS_INVERSION,
        PRODUCT_AOD,
        PRODUCT_SDA,
        SITES_REFRESH_DAYS,
        SITE_LIST_URL,
    )
    from parsers import (  # type: ignore
        AeronetData,
        AeronetError,
        Site,
        normalize_site,
    )
    from site_cache import (  # type: ignore
        STORAGE_VERSION,
        is_stale,
        sites_from_payload,
        sites_to_payload,
        storage_key,
    )


def _merge(base: AeronetData | None, other: AeronetData) -> AeronetData:
    """Merge one payload's product series/extras into the base payload."""
    if base is None:
        return other
    base.values.update(other.values)
    base.meta.extras.update(other.meta.extras)
    if base.meta.name in ("", "unknown") and other.meta.name not in ("", "unknown"):
        base.meta.name = other.meta.name
        base.meta.latitude = other.meta.latitude
        base.meta.longitude = other.meta.longitude
        base.meta.elevation = other.meta.elevation
    return base


def payload_is_empty(data: AeronetData | None) -> bool:
    """True when a payload carries no usable measurement points at all."""
    if data is None:
        return True
    if data.points:
        return False
    return not any(series for series in data.values.values())


def detected_channels(data: AeronetData | None) -> list[str]:
    """Channel ids with valid data in the current payload (sorted by nm)."""
    if data is None:
        return []
    try:
        from .parsers import detect_channels
    except ImportError:  # flat import in stdlib-only unit tests
        from parsers import detect_channels  # type: ignore
    return detect_channels(data)


def active_channels(data: AeronetData | None,
                    configured: list[str] | None) -> list[str]:
    """Channels to expose: configured ∩ detected, minus the main-sensor
    wavelengths (those already have their own sensor and must not be
    duplicated as channel entities)."""
    try:
        from .parsers import active_channels as _filter
    except ImportError:  # flat import in stdlib-only unit tests
        from parsers import active_channels as _filter  # type: ignore
    if data is None:
        return []
    detected = detected_channels(data)
    chosen = _filter(detected, configured)
    mains = {v for k, v in data.meta.extras.items()
             if k.startswith("main_channel_")}
    return [c for c in chosen if c not in mains]


_LOGGER = logging.getLogger(__name__)

# Module-level cache of the (slow-changing) global site list, keyed by the
# configured source URL so entries using different lists coexist. Freshness
# per key is tracked from the disk payload's saved_at date.
_sites_cache: dict[str, list[Any]] = {}
_sites_saved_at: dict[str, str] = {}
_sites_coordinators: dict[str, "SiteListCoordinator"] = {}
# v0.5.0: refcount of live config entries holding each shared site
# coordinator. Without it the module dict kept coordinators (and their
# weekly poll timers) alive forever after every entry was unloaded.
_sites_refs: dict[str, int] = {}


class SiteListCoordinator(DataUpdateCoordinator):
    """Cache of AERONET stations for one source URL.

    The list is persisted through the Home Assistant storage helper so the
    config-flow dropdown can be populated from disk on the very first boot
    (no live NASA fetch needed when the cached copy is fresh); when the
    on-disk copy is older than SITES_REFRESH_DAYS the refresh runs in the
    background instead of blocking the dropdown.
    """

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession,
                 *, url: str = SITE_LIST_URL) -> None:
        self.url = url
        self._url = url
        self._client = AeronetClient(session)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_sites",
            update_interval=dt.timedelta(days=SITES_REFRESH_DAYS),
        )
        self.data = _sites_cache.get(url)  # serve in-memory cache immediately

    def _store(self) -> Store:
        return Store(self.hass, STORAGE_VERSION, storage_key(self._url),
                     private=True)

    async def async_load_storage(self) -> None:
        """Hydrate the cache from disk (call during setup, before refreshing)."""
        payload = await self._store().async_load()
        sites = sites_from_payload(payload, Site) if payload else None
        if not sites:
            return
        if self._url not in _sites_cache:
            _sites_cache[self._url] = sites
            _sites_saved_at[self._url] = payload.get("saved_at", "")
            self.data = sites
        if is_stale(payload, dt.datetime.now(dt.timezone.utc)):
            _LOGGER.info(
                "AERONET site list cache older than %d days; refreshing in "
                "the background", SITES_REFRESH_DAYS)
            # Dropdown is usable immediately from the stale list; NASA fetch
            # happens off the setup path.
            self.hass.async_create_task(self.async_refresh())

    async def _async_update_data(self):
        try:
            sites = await self._client.fetch_site_list(self._url)
        except AeronetError as err:
            cached = _sites_cache.get(self._url)
            if cached is not None:
                _LOGGER.warning("Site list refresh failed, keeping cache: %s", err)
                return cached
            raise UpdateFailed(f"Could not load AERONET site list: {err}") from err
        _sites_cache[self._url] = sites
        payload = sites_to_payload(sites, dt.datetime.now(dt.timezone.utc))
        _sites_saved_at[self._url] = payload["saved_at"]
        try:
            await self._store().async_save(payload)
        except Exception:  # pragma: no cover - disk problems must not fail HA
            _LOGGER.warning("Could not persist AERONET site list cache",
                            exc_info=True)
        return sites


def get_sites_coordinator(hass: HomeAssistant,
                         session: aiohttp.ClientSession,
                         *, url: str = SITE_LIST_URL) -> SiteListCoordinator:
    coord = _sites_coordinators.get(url)
    # A coordinator HA already shut down (is_shut_down) has dead timers and
    # listeners; never hand it back.
    if coord is None or coord.hass is not hass or getattr(
            coord, "is_shut_down", False):
        coord = SiteListCoordinator(hass, session, url=url)
        _sites_coordinators[url] = coord
    return coord


def hold_sites_coordinator(url: str) -> None:
    """Register one live config entry against the shared coordinator."""
    _sites_refs[url] = _sites_refs.get(url, 0) + 1


def release_sites_coordinator(url: str) -> None:
    """Drop one entry's reference; shut polling down when the last went away."""
    refs = _sites_refs.get(url, 0) - 1
    if refs > 0:
        _sites_refs[url] = refs
        return
    _sites_refs.pop(url, None)
    coord = _sites_coordinators.pop(url, None)
    if coord is not None:
        try:
            coord.async_shutdown()
        except Exception:  # pragma: no cover - defensive
            _LOGGER.warning("AERONET site coordinator shutdown failed",
                            exc_info=True)


class AeronetDataCoordinator(DataUpdateCoordinator):
    """Per-config-entry coordinator pulling AOD data for the selected site."""

    def __init__(
        self,
        hass: HomeAssistant,
        session: aiohttp.ClientSession,
        *,
        email: str,
        level: str,
        interval_min: int,
        site: str,
        products: list[str] | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._level = level
        self._products = list(products) if products else list(DEFAULT_PRODUCTS)
        self.site = site.strip()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{site}",
            update_interval=dt.timedelta(minutes=interval_min),
        )

    @property
    def products(self) -> list[str]:
        return list(self._products)

    def configure(self, *, email: str | None = None, level: str | None = None,
                  interval_min: int | None = None,
                  products: list[str] | None = None) -> None:
        """Apply options-flow changes without re-creating the coordinator."""
        if email is not None:
            self._email = email
        if level is not None:
            self._level = level
        if interval_min is not None:
            self.update_interval = dt.timedelta(minutes=int(interval_min))
        if products is not None:
            self._products = list(products)

    async def _fetch_all(self, client: AeronetClient, site: str,
                        now: dt.datetime, days: int,
                        errors: list[str]) -> AeronetData | None:
        """One pass over the configured products at the given window width."""

        async def _try(label, coro):
            try:
                return await coro
            except AeronetError as err:
                errors.append(f"{label}: {err}")
                _LOGGER.warning("AERONET product %s fetch failed: %s", label, err)
                return None

        # Base payload: whichever all-points fetch runs first provides meta.
        base: AeronetData | None = None
        products = self._products or DEFAULT_PRODUCTS
        if PRODUCT_AOD in products:
            base = await _try("AOD", client.fetch_data(site, now, days=days))
        if base is None and PRODUCT_SDA in products:
            base = await _try("SDA", client.fetch_sda(site, now, days=days))
        for product in products:
            if product not in PRODUCTS_INVERSION:
                continue
            inv = await _try(
                product, client.fetch_inversion(product, site, now, days=days))
            if inv is not None:
                base = _merge(base, inv)
        return base

    async def _async_update_data(self):
        now = dt.datetime.now(dt.timezone.utc)
        client = AeronetClient(
            self._session, email=self._email, level=self._level
        )
        site = self.site
        products = self._products or DEFAULT_PRODUCTS
        errors: list[str] = []

        base = await self._fetch_all(client, site, now, DATA_WINDOW_DAYS,
                                     errors)

        # Some stations report only campaign/monthly data and answer the 7-day
        # window with an empty payload: widen once to DATA_WINDOW_WIDE_DAYS
        # (documented in README). Widening only applies when the requests
        # themselves worked — a request failure retries on the next poll.
        if (base is not None and payload_is_empty(base)
                and not errors):
            _LOGGER.info(
                "AERONET 7-day window empty for '%s'; retrying widened to "
                "%d days", site, DATA_WINDOW_WIDE_DAYS)
            wide_errors: list[str] = []
            widened = await self._fetch_all(client, site, now,
                                            DATA_WINDOW_WIDE_DAYS, wide_errors)
            if widened is not None and not payload_is_empty(widened):
                base = widened
                errors = wide_errors

        if base is None:
            if errors:
                raise UpdateFailed("; ".join(errors))
            raise UpdateFailed("no AERONET products configured")

        # Daily averages only make sense for AOD and are additive: on failure,
        # keep the previously fetched daily series.
        if PRODUCT_AOD in products:
            async def _try_daily():
                try:
                    return await client.fetch_daily(site, now)
                except AeronetError as err:
                    errors.append(f"AOD daily: {err}")
                    _LOGGER.warning("AERONET AOD daily fetch failed: %s", err)
                    return None
            daily = await _try_daily()
            if daily is not None:
                base.values.update(daily.values)
                base.meta.extras.update(daily.meta.extras)
            elif (
                self.data is not None
                and getattr(self.data, "values", None)
                and normalize_site(self.data.meta.name) in (
                    "", normalize_site(site)
                )
            ):
                # Daily fetch failed: keep the previous daily series when it
                # still belongs to this site (set_site clears self.data).
                base.values.update(
                    {k: v for k, v in self.data.values.items()
                     if k not in base.values}
                )

        if errors:
            _LOGGER.info("AERONET partial update for '%s': %s", site, "; ".join(errors))
        if payload_is_empty(base):
            raise UpdateFailed(
                "AERONET returned no data for site '%s' in the last %d days"
                % (site, DATA_WINDOW_WIDE_DAYS)
            )
        return base

    async def set_site(self, site: str) -> None:
        site = (site or "").strip()
        changed = site != self.site
        self.site = site
        if changed:
            # Drop data from the previous station so sensors never render it
            # while the new fetch is in flight.
            self.data = None
        # Force an immediate refresh (not the debounced request_refresh) so
        # the sensors show the new station right away, even if unchanged.
        await self.async_refresh()
