"""AERONET request URL builder (stdlib-only, unit-testable anywhere)."""
from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import urlencode

try:  # when imported as part of the custom_components.aeronet package
    from .const import (
        DATA_WINDOW_DAYS,
        INVERSION_LEVELS,
        INVERSION_WEB_SERVICE_URL,
        LEVELS,
        WEB_SERVICE_URL,
    )
except ImportError:  # flat import in stdlib-only unit tests
    from const import (  # type: ignore
        DATA_WINDOW_DAYS,
        INVERSION_LEVELS,
        INVERSION_WEB_SERVICE_URL,
        LEVELS,
        WEB_SERVICE_URL,
    )


def _window(now: dt.datetime) -> tuple:
    start = (now - dt.timedelta(days=DATA_WINDOW_DAYS - 1)).date()
    return start, now.date()


def _params(site: str, now: dt.datetime, data_type: str, avg: int,
           email: str, endpoint: str) -> dict:
    site = (site or "").strip()
    start, end = _window(now)
    params: dict[str, Any] = {
        "site": site,
        "year": start.year,
        "month": start.month,
        "day": start.day,
        "year2": end.year,
        "month2": end.month,
        "day2": end.day,
        data_type: 1,
        "AVG": avg,
        "if_no_html": 1,
    }
    if email:
        params["email"] = email
    return params


def build_data_url(
    site: str, now: dt.datetime, *, level: str = "1.5", email: str = ""
) -> str:
    """URL for the Level 1.x/2.0 all-points AOD web service for a date window.

    Window = last DATA_WINDOW_DAYS days (UTC), inclusive of today, as required
    by the web service's year/month/day .. year2/month2/day2 parameters.

    The site name is stripped before encoding: AERONET ignores a ``site``
    value that is not an exact station name (a trailing space is enough),
    and the resulting response silently contains *all* stations.
    """
    if level not in LEVELS:
        raise ValueError(f"unknown AERONET level: {level}")
    params = _params(site, now, LEVELS[level], 10, email, WEB_SERVICE_URL)
    return f"{WEB_SERVICE_URL}?{urlencode(params)}"


def build_daily_url(
    site: str, now: dt.datetime, *, level: str = "1.5", email: str = ""
) -> str:
    """URL for AERONET *daily average* AOD (AVG=20), same 7-day window.

    One row per calendar day (Time is 12:00:00), including today's partial
    mean computed from the points available so far (verified live 2026-09-16).
    """
    if level not in LEVELS:
        raise ValueError(f"unknown AERONET level: {level}")
    params = _params(site, now, LEVELS[level], 20, email, WEB_SERVICE_URL)
    return f"{WEB_SERVICE_URL}?{urlencode(params)}"


def build_sda_url(
    site: str, now: dt.datetime, *, level: str = "1.5", email: str = ""
) -> str:
    """URL for SDA (size-dependency AOD split, fine/coarse) all-points.

    Direct-sun data types cannot be combined in a single request (verified:
    ``AOD15=1&SDA15=1`` returns only AOD columns), so SDA is its own GET.
    """
    sda_type = {"1.0": "SDA10", "1.5": "SDA15", "2.0": "SDA20"}[level]
    params = _params(site, now, sda_type, 10, email, WEB_SERVICE_URL)
    return f"{WEB_SERVICE_URL}?{urlencode(params)}"


def build_inversion_url(
    site: str,
    now: dt.datetime,
    *,
    product: str,
    level: str = "1.5",
    email: str = "",
    avg: int = 10,
) -> str:
    """URL for an inversion web-service product (SSA/VOL/...), all points.

    Uses print_web_data_inv_v3 with the ALM retrieval type for the level and
    ``product=<PRODUCT>`` (the help page's parameter name; ``product_id=`` is
    NOT accepted and yields an empty payload).
    """
    if product not in ("SSA", "VOL"):
        raise ValueError(f"unsupported inversion product: {product}")
    params = _params(
        site, now, INVERSION_LEVELS[level], avg, email, INVERSION_WEB_SERVICE_URL
    )
    params["product"] = product
    return f"{INVERSION_WEB_SERVICE_URL}?{urlencode(params)}"
