"""Async HTTP client for the AERONET web service."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random

import aiohttp

try:  # when imported as part of the custom_components.aeronet package
  from .const import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_TOTAL,
    RETRY_AFTER_MAX,
    RETRY_BACKOFF,
    SITE_LIST_URL,
    USER_AGENT,
  )
  from .parsers import (
    AOD_COLUMNS,
    AOD_DAILY_SLOT,
    AeronetError,
    AeronetData,
    SDA_COARSE_COLUMNS,
    SDA_COARSE_SLOT,
    SDA_FINE_COLUMNS,
    SDA_FINE_SLOT,
    SSA_COLUMNS,
    SSA_SLOT,
    VOL_COLUMNS,
    VOL_SLOT,
    parse_data_csv,
    parse_site_list,
  )
except ImportError:  # flat import in stdlib-only unit tests
  from const import (  # type: ignore
    MAX_RETRIES,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_TOTAL,
    RETRY_AFTER_MAX,
    RETRY_BACKOFF,
    SITE_LIST_URL,
    USER_AGENT,
  )
  from parsers import (  # type: ignore
    AOD_COLUMNS,
    AOD_DAILY_SLOT,
    AeronetError,
    AeronetData,
    SDA_COARSE_COLUMNS,
    SDA_COARSE_SLOT,
    SDA_FINE_COLUMNS,
    SDA_FINE_SLOT,
    SSA_COLUMNS,
    SSA_SLOT,
    VOL_COLUMNS,
    VOL_SLOT,
    parse_data_csv,
    parse_site_list,
  )
_LOGGER = logging.getLogger(__name__)


def _retry_after_seconds(value: str | None) -> float:
    """Parse a Retry-After header (delta-seconds form) into bounded seconds.

    Only the numeric form matters for AERONET; anything else (missing, HTTP
    date, garbage) falls back to the exponential schedule with jitter.
    """
    try:
        seconds = float(value)  # float(None) raises TypeError -> fallback
    except (TypeError, ValueError):
        seconds = RETRY_BACKOFF * 2 + random.random()
    return max(1.0, min(seconds, RETRY_AFTER_MAX))


class AeronetClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        email: str = "",
        level: str = "1.5",
    ) -> None:
        self._session = session
        self._email = email.strip()
        self._level = level

    async def _get_text(self, url: str) -> str:
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT_TOTAL, connect=REQUEST_TIMEOUT_CONNECT
        )
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                async with self._session.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
                ) as resp:
                    if resp.status == 429:
                        # AERONET rate limit: honor Retry-After (bounded) so
                        # the retry actually helps instead of hammering.
                        if attempt < MAX_RETRIES:
                            await asyncio.sleep(
                                _retry_after_seconds(resp.headers.get("Retry-After"))
                            )
                            continue
                        raise AeronetError("AERONET rate limit (HTTP 429)")
                    resp.raise_for_status()
                    return await resp.text(errors="replace")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_err = err
                if attempt < MAX_RETRIES:
                    # Exponential backoff + jitter: RETRY_BACKOFF * 2^attempt
                    # plus 0..1s of uniform jitter so concurrent entries
                    # (site list + several data coordinators) do not retry in
                    # lockstep.
                    await asyncio.sleep(
                        RETRY_BACKOFF * (2 ** attempt) + random.random()
                    )
        raise AeronetError(f"request failed after retries: {last_err}") from last_err

    async def fetch_site_list(self) -> list:
        body = await self._get_text(SITE_LIST_URL)
        return parse_site_list(body)

    async def _fetch_csv(self, url: str, site: str, column_sets) -> AeronetData:
        _LOGGER.debug("AERONET fetch: %s", url)
        body = await self._get_text(url)
        # expected_site guards against the web service silently ignoring an
        # unmatched site parameter and replying with every station's rows.
        return parse_data_csv(body, expected_site=site, column_sets=column_sets)

    async def fetch_data(self, site: str, now: dt.datetime) -> AeronetData:
        """AOD all-points (AVG=10) for the window."""
        from .urls import build_data_url

        return await self._fetch_csv(
            build_data_url(site, now, level=self._level, email=self._email),
            site,
            {"aod": AOD_COLUMNS},
        )

    async def fetch_daily(self, site: str, now: dt.datetime) -> AeronetData:
        """AOD daily averages (AVG=20): one row per day incl. today's partial."""
        from .urls import build_daily_url

        return await self._fetch_csv(
            build_daily_url(site, now, level=self._level, email=self._email),
            site,
            {AOD_DAILY_SLOT: AOD_COLUMNS},
        )

    async def fetch_sda(self, site: str, now: dt.datetime) -> AeronetData:
        """SDA fine/coarse AOD all-points (separate direct-sun request)."""
        from .urls import build_sda_url

        return await self._fetch_csv(
            build_sda_url(site, now, level=self._level, email=self._email),
            site,
            {SDA_FINE_SLOT: SDA_FINE_COLUMNS, SDA_COARSE_SLOT: SDA_COARSE_COLUMNS},
        )

    async def fetch_inversion(
        self, product: str, site: str, now: dt.datetime
    ) -> AeronetData:
        """SSA/VOL all-points from the inversion web service."""
        from .urls import build_inversion_url

        slot = SSA_SLOT if product == "SSA" else VOL_SLOT
        cols = SSA_COLUMNS if product == "SSA" else VOL_COLUMNS
        return await self._fetch_csv(
            build_inversion_url(
                site, now, product=product, level=self._level,
                email=self._email,
            ),
            site,
            {slot: cols},
        )
