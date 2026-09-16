"""Async HTTP client for the AERONET web service."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import aiohttp

from .const import (
    MAX_RETRIES,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_TOTAL,
    RETRY_BACKOFF,
    SITE_LIST_URL,
    USER_AGENT,
)
from .parsers import AeronetError, AeronetData, parse_data_csv, parse_site_list

_LOGGER = logging.getLogger(__name__)


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
                        raise AeronetError("AERONET rate limit (HTTP 429)")
                    resp.raise_for_status()
                    return await resp.text(errors="replace")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_err = err
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
        raise AeronetError(f"request failed after retries: {last_err}") from last_err

    async def fetch_site_list(self) -> list:
        body = await self._get_text(SITE_LIST_URL)
        return parse_site_list(body)

    def _data_url(self, site: str, now: dt.datetime) -> str:
        from .urls import build_data_url

        return build_data_url(
            site, now, level=self._level, email=self._email
        )

    async def fetch_data(self, site: str, now: dt.datetime) -> AeronetData:
        url = self._data_url(site, now)
        _LOGGER.debug("AERONET fetch: %s", url)
        body = await self._get_text(url)
        data = parse_data_csv(body)  # raises AeronetParamError on help HTML
        return data
