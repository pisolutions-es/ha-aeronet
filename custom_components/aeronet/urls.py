"""AERONET request URL builder (stdlib-only, unit-testable anywhere)."""
from __future__ import annotations

import datetime as dt
from typing import Any
from urllib.parse import urlencode

try:  # when imported as part of the custom_components.aeronet package
    from .const import DATA_WINDOW_DAYS, LEVELS, WEB_SERVICE_URL
except ImportError:  # flat import in stdlib-only unit tests
    from const import DATA_WINDOW_DAYS, LEVELS, WEB_SERVICE_URL  # type: ignore


def build_data_url(
    site: str, now: dt.datetime, *, level: str = "1.5", email: str = ""
) -> str:
    """URL for the Level 1.x/2.0 all-points AOD web service for a date window.

    Window = last DATA_WINDOW_DAYS days (UTC), inclusive of today, as required
    by the web service's year/month/day .. year2/month2/day2 parameters.
    """
    start = (now - dt.timedelta(days=DATA_WINDOW_DAYS - 1)).date()
    end = now.date()
    if level not in LEVELS:
        raise ValueError(f"unknown AERONET level: {level}")
    params: dict[str, Any] = {
        "site": site,
        "year": start.year,
        "month": start.month,
        "day": start.day,
        "year2": end.year,
        "month2": end.month,
        "day2": end.day,
        LEVELS[level]: 1,
        "AVG": 10,
        "if_no_html": 1,
    }
    if email:
        params["email"] = email
    return f"{WEB_SERVICE_URL}?{urlencode(params)}"
