"""Disk-cache payload helpers for the AERONET site list (stdlib-only).

The Home Assistant storage helper (``homeassistant.helpers.storage.Store``)
persists the parsed station list so the config-flow dropdown is populated
from disk on the very first boot after installation — no live NASA fetch
needed when the cached copy is still fresh. Serialisation lives here so it
is unit-testable without Home Assistant.

Payload format (JSON-serialisable dict):
    {"saved_at": "<UTC ISO-8601>", "sites": [[name, lon, lat, elev], ...]}
"""
from __future__ import annotations

import datetime as dt

try:  # package import inside Home Assistant
    from .const import SITES_REFRESH_DAYS
except ImportError:  # flat import in stdlib-only unit tests
    from const import SITES_REFRESH_DAYS  # type: ignore

STORAGE_VERSION = 1


def storage_key(url: str) -> str:
    """Per-source storage key: one cache per configured site-list URL."""
    import hashlib

    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"aeronet_site_list_{digest}"


def sites_to_payload(sites, saved_at: dt.datetime) -> dict:
    """Serialise Site dataclasses into a JSON-safe dict with a UTC date."""
    return {
        "saved_at": saved_at.astimezone(dt.timezone.utc).isoformat(),
        "sites": [
            [s.name, s.longitude, s.latitude, s.elevation] for s in sites
        ],
    }


def sites_from_payload(payload, site_cls):
    """Rebuild Site objects from a stored payload; None when unusable."""
    try:
        rows = payload["sites"]
        return [
            site_cls(name=r[0], longitude=float(r[1]), latitude=float(r[2]),
                     elevation=float(r[3]))
            for r in rows
        ]
    except (KeyError, TypeError, IndexError, ValueError):
        return None


def is_stale(payload, now: dt.datetime,
            max_age_days: int = SITES_REFRESH_DAYS) -> bool:
    """True when the cached payload must be refreshed (missing or > max_age)."""
    try:
        saved = dt.datetime.fromisoformat(payload["saved_at"])
    except (KeyError, TypeError, ValueError):
        return True
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=dt.timezone.utc)
    return (now - saved) > dt.timedelta(days=max_age_days)
