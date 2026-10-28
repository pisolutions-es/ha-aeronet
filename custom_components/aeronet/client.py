"""Async HTTP client for the AERONET web service."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random

import aiohttp

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
from .urls import (
    build_data_url,
    build_daily_url,
    build_inversion_url,
    build_sda_url,
)
from .const import (
    DATA_WINDOW_DAYS,
    MAX_RESPONSE_BYTES,
    MAX_RETRIES,
    REQUEST_TIMEOUT_CONNECT,
    REQUEST_TIMEOUT_TOTAL,
    RETRY_AFTER_MAX,
    RETRY_BACKOFF,
    SITE_LIST_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# The request URL carries the user's configured email as a query param;
# debug logs get pasted into issue reports, so the parameter is stripped.
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode  # noqa: E402


def _redacted(url: str) -> str:
    parts = urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k != "email"]
    return urlunsplit(parts._replace(query=urlencode(kept)))


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
        self._user_agent = USER_AGENT
        if self._email:
            # Contact info belongs in the User-Agent: the web service
            # rejects an `email` query param (F9) and NASA asks for an
            # identifiable UA. Sanitize to header-safe chars (no CR/LF,
            # no quotes) — config values are user input.
            safe = "".join(
                ch for ch in self._email
                if ch.isascii() and 0x20 < ord(ch) < 0x7F and ch not in '()"'
            )
            if safe:
                self._user_agent = f"{USER_AGENT}; contact: {safe}"

    async def _get_text(self, url: str) -> str:
        timeout = aiohttp.ClientTimeout(
            total=REQUEST_TIMEOUT_TOTAL, connect=REQUEST_TIMEOUT_CONNECT
        )
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            # v0.7.0 (review M1): the wait for a 429 (or for a backoff) is
            # scheduled *outside* the response context, so the aiohttp
            # connection is released before sleeping — holding it open for
            # up to RETRY_AFTER_MAX (5 min) starved the connection pool.
            retry_delay: float | None = None
            try:
                async with self._session.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": self._user_agent,
                             "Accept": "text/plain"},
                ) as resp:
                    if resp.status == 429:
                        # AERONET rate limit: honor Retry-After (bounded) so
                        # the retry actually helps instead of hammering.
                        if attempt < MAX_RETRIES:
                            retry_delay = _retry_after_seconds(
                                resp.headers.get("Retry-After")
                            )
                        else:
                            raise AeronetError(
                                "AERONET rate limit (HTTP 429)")
                    elif 400 <= resp.status < 500 and resp.status != 408:
                        # v0.7.0 (review M1): a permanent client error (bad
                        # parameters, unknown site, forbidden) will fail the
                        # same way on every retry — fail fast instead of
                        # tripling the request count.
                        raise AeronetError(
                            f"AERONET request rejected (HTTP {resp.status})")
                    else:
                        resp.raise_for_status()
                        # v0.7.0 (review M1): cap the body so a malformed
                        # multi-station response cannot balloon the event
                        # loop's memory before the parser rejects it.
                        raw = await resp.content.read(MAX_RESPONSE_BYTES + 1)
                        if len(raw) > MAX_RESPONSE_BYTES:
                            raise AeronetError(
                                "AERONET response exceeds "
                                f"{MAX_RESPONSE_BYTES} bytes"
                            )
                        return raw.decode("utf-8", errors="replace")
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_err = err
                if attempt < MAX_RETRIES:
                    # Exponential backoff + jitter: RETRY_BACKOFF * 2^attempt
                    # plus 0..1s of uniform jitter so concurrent entries
                    # (site list + several data coordinators) do not retry in
                    # lockstep.
                    retry_delay = RETRY_BACKOFF * (2 ** attempt) + random.random()
            if retry_delay is not None:
                await asyncio.sleep(retry_delay)
        raise AeronetError(
            f"request failed after retries: {_redacted(str(last_err))}"
        ) from last_err

    async def fetch_site_list(self, url: str = SITE_LIST_URL) -> list:
        body = await self._get_text(url)
        return parse_site_list(body)

    async def _fetch_csv(self, url: str, site: str, column_sets,
                         channel_families: tuple = ()) -> AeronetData:
        _LOGGER.debug("AERONET fetch: %s", _redacted(url))
        body = await self._get_text(url)
        # expected_site guards against the web service silently ignoring an
        # unmatched site parameter and replying with every station's rows.
        return parse_data_csv(body, expected_site=site,
                              column_sets=column_sets,
                              channel_families=channel_families)

    async def fetch_data(
        self, site: str, now: dt.datetime, *, days: int = DATA_WINDOW_DAYS
    ) -> AeronetData:
        """AOD all-points (AVG=10) for the window."""
        return await self._fetch_csv(
            build_data_url(site, now, level=self._level, email=self._email,
                           days=days),
            site,
            {"aod": AOD_COLUMNS},
            channel_families=("aod",),
        )

    async def fetch_daily(
        self, site: str, now: dt.datetime, *, days: int = DATA_WINDOW_DAYS
    ) -> AeronetData:
        """AOD daily averages (AVG=20): one row per day incl. today's partial."""
        return await self._fetch_csv(
            build_daily_url(site, now, level=self._level, email=self._email,
                            days=days),
            site,
            {AOD_DAILY_SLOT: AOD_COLUMNS},
        )

    async def fetch_sda(
        self, site: str, now: dt.datetime, *, days: int = DATA_WINDOW_DAYS
    ) -> AeronetData:
        """SDA fine/coarse AOD all-points (separate direct-sun request)."""
        return await self._fetch_csv(
            build_sda_url(site, now, level=self._level, email=self._email,
                          days=days),
            site,
            {SDA_FINE_SLOT: SDA_FINE_COLUMNS, SDA_COARSE_SLOT: SDA_COARSE_COLUMNS},
        )

    async def fetch_inversion(
        self,
        product: str,
        site: str,
        now: dt.datetime,
        *,
        days: int = DATA_WINDOW_DAYS,
    ) -> AeronetData:
        """SSA/VOL all-points from the inversion web service."""
        slot = SSA_SLOT if product == "SSA" else VOL_SLOT
        cols = SSA_COLUMNS if product == "SSA" else VOL_COLUMNS
        return await self._fetch_csv(
            build_inversion_url(
                site, now, product=product, level=self._level,
                email=self._email, days=days,
            ),
            site,
            {slot: cols},
            channel_families=("ssa",) if product == "SSA" else (),
        )
