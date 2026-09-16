"""DataUpdateCoordinator wrappers for AERONET site list + per-entry data."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AeronetClient
from .const import (
    CONF_LEVEL,
    DEFAULT_PRODUCTS,
    DOMAIN,
    PRODUCTS_INVERSION,
    PRODUCT_AOD,
    PRODUCT_SDA,
    SITES_REFRESH_DAYS,
)
from .parsers import (
    AeronetData,
    AeronetError,
    normalize_site,
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

_LOGGER = logging.getLogger(__name__)

# Module-level cache of the (slow-changing) global site list, shared by all
# config entries and refreshed weekly.
_sites_cache: list[Any] | None = None
_sites_coordinator: "SiteListCoordinator | None" = None


class SiteListCoordinator(DataUpdateCoordinator):
    """Weekly-refreshing cache of the ~2000 AERONET stations."""

    def __init__(self, hass: HomeAssistant, session: aiohttp.ClientSession) -> None:
        global _sites_cache
        self._client = AeronetClient(session)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_sites",
            update_interval=dt.timedelta(days=SITES_REFRESH_DAYS),
        )
        self.data = _sites_cache  # serve cached list immediately on restart

    async def _async_update_data(self):
        global _sites_cache
        try:
            sites = await self._client.fetch_site_list()
        except AeronetError as err:
            if _sites_cache is not None:
                _LOGGER.warning("Site list refresh failed, keeping cache: %s", err)
                return _sites_cache
            raise UpdateFailed(f"Could not load AERONET site list: {err}") from err
        _sites_cache = sites
        return sites


def get_sites_coordinator(hass: HomeAssistant, session: aiohttp.ClientSession):
    global _sites_coordinator
    if _sites_coordinator is None or _sites_coordinator.hass is not hass:
        _sites_coordinator = SiteListCoordinator(hass, session)
    return _sites_coordinator


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

    async def _async_update_data(self):
        now = dt.datetime.now(dt.timezone.utc)
        client = AeronetClient(
            self._session, email=self._email, level=self._level
        )
        site = self.site
        products = self._products or DEFAULT_PRODUCTS
        errors: list[str] = []

        async def _try(label, coro):
            try:
                return await coro
            except AeronetError as err:
                errors.append(f"{label}: {err}")
                _LOGGER.warning("AERONET product %s fetch failed: %s", label, err)
                return None

        # Base payload: whichever all-points fetch runs first provides meta.
        base: AeronetData | None = None
        if PRODUCT_AOD in products:
            base = await _try("AOD", client.fetch_data(site, now))
        if base is None and PRODUCT_SDA in products:
            base = await _try("SDA", client.fetch_sda(site, now))
        for product in products:
            if product not in PRODUCTS_INVERSION:
                continue
            inv = await _try(product, client.fetch_inversion(product, site, now))
            if inv is not None:
                base = _merge(base, inv)

        if base is None:
            if errors:
                raise UpdateFailed("; ".join(errors))
            raise UpdateFailed("no AERONET products configured")

        # Daily averages only make sense for AOD and are additive: on failure,
        # keep the previously fetched daily series.
        if PRODUCT_AOD in products:
            daily = await _try("AOD daily", client.fetch_daily(site, now))
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
        if not base.points and not any(base.values.values()):
            raise UpdateFailed(
                "AERONET returned no data for site '%s' in the last 7 days" % site
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
