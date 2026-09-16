"""DataUpdateCoordinator wrappers for AERONET site list + per-entry data."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import AeronetClient
from .const import CONF_LEVEL, DOMAIN, SITES_REFRESH_DAYS
from .parsers import AeronetError, AeronetParamError

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
    ) -> None:
        self._session = session
        self._email = email
        self._level = level
        self.site = site.strip()
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{site}",
            update_interval=dt.timedelta(minutes=interval_min),
        )

    def configure(self, *, email: str | None = None, level: str | None = None,
                  interval_min: int | None = None) -> None:
        """Apply options-flow changes without re-creating the coordinator."""
        if email is not None:
            self._email = email
        if level is not None:
            self._level = level
        if interval_min is not None:
            self.update_interval = dt.timedelta(minutes=int(interval_min))

    async def _async_update_data(self):
        now = dt.datetime.now(dt.timezone.utc)
        client = AeronetClient(
            self._session, email=self._email, level=self._level
        )
        try:
            return await client.fetch_data(self.site, now)
        except AeronetParamError as err:
            raise UpdateFailed(
                f"AERONET rejected the request parameters for site '{self.site}': {err}"
            ) from err
        except AeronetError as err:
            raise UpdateFailed(str(err)) from err

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
