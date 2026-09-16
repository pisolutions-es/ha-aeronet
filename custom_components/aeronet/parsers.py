"""Pure-stdlib parsers for AERONET CSV/HTML payloads.

Kept free of Home Assistant imports so they can be unit tested anywhere.
All functions are synchronous and operate on already-decoded ``str`` bodies.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field

NODATA = -999.0

# Preferred AOD wavelengths in order (kept local so parsers stay stdlib-only;
# const.py re-exports the same tuple).
AOD_WAVELENGTHS = ("AOD_500nm", "AOD_551nm", "AOD_555nm", "AOD_560nm")


class AeronetError(Exception):
    """Base error for AERONET parsing/fetch problems."""


class AeronetParamError(AeronetError):
    """The web service returned its HTML help page: bad request parameters."""


class AeronetEmptyError(AeronetError):
    """Response is not a recognizable AERONET CSV payload at all."""


@dataclass
class Site:
    name: str
    longitude: float
    latitude: float
    elevation: float


@dataclass
class AodPoint:
    time: dt.datetime  # UTC, AERONET reports UTC
    aod: float
    wavelength: str


@dataclass
class SiteMeta:
    name: str
    latitude: float
    longitude: float
    elevation: float
    last_date_processed: dt.datetime | None = None


@dataclass
class AeronetData:
    meta: SiteMeta
    points: list[AodPoint] = field(default_factory=list)


def is_help_html(body: str) -> bool:
    """Detect the web service HTML help/error page (invalid parameters)."""
    head = body[:2000]
    lowered = head.lower()
    return (
        "<html" in lowered
        or "<!doctype html" in lowered
        or "aeronet version 3 web service help" in lowered
    )


def parse_site_list(body: str) -> list[Site]:
    """Parse aeronet_locations_v3.txt.

    Layout: line 1 'AERONET_Database_Site_List,...' banner, line 2 CSV header
    (Site_Name,Longitude(...),Latitude(...),Elevation(...)), then ~2000 rows.
    """
    if is_help_html(body):
        raise AeronetParamError("site list request returned HTML help page")
    lines = body.splitlines()
    # Locate the header row regardless of banner count.
    header_idx = None
    for i, line in enumerate(lines[:10]):
        if line.lower().startswith("site_name,"):
            header_idx = i
            break
    if header_idx is None:
        raise AeronetEmptyError("site list header not found")
    sites: list[Site] = []
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    header = next(reader)
    cols = {name.lower().split("(")[0]: idx for idx, name in enumerate(header)}
    try:
        i_name = cols["site_name"]
        i_lon = cols["longitude"]
        i_lat = cols["latitude"]
        i_elev = cols["elevation"]
    except KeyError as err:  # pragma: no cover - defensive
        raise AeronetEmptyError(f"site list columns missing: {err}") from err
    for row in reader:
        if len(row) <= max(i_name, i_lon, i_lat, i_elev):
            continue
        try:
            sites.append(
                Site(
                    name=row[i_name].strip(),
                    longitude=float(row[i_lon]),
                    latitude=float(row[i_lat]),
                    elevation=float(row[i_elev]),
                )
            )
        except ValueError:
            continue  # skip malformed rows
    if not sites:
        raise AeronetEmptyError("site list contains no rows")
    return sites


def _header_index(header_row: list[str]) -> dict[str, int]:
    return {name: idx for idx, name in enumerate(header_row)}


def _find_data_header(lines: list[str]) -> int | None:
    for i, line in enumerate(lines[:30]):
        if line.startswith("AERONET_Site,Date("):
            return i
    return None


def parse_data_csv(body: str) -> AeronetData:
    """Parse a Level 1.x/2.0 all-points AOD CSV response.

    Format: 5+ banner lines, a header line starting 'AERONET_Site,Date(...)',
    then one row per measurement. -999.0 means no data.
    """
    if is_help_html(body):
        raise AeronetParamError(
            "web service returned the HTML help page (invalid parameters)"
        )
    lines = body.splitlines()
    header_idx = _find_data_header(lines)
    if header_idx is None:
        raise AeronetEmptyError("data CSV header row not found")

    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])))
    header = next(reader)
    idx = _header_index(header)

    # Which AOD column this site provides (500 nm preferred).
    aod_col = next((w for w in AOD_WAVELENGTHS if w in idx), None)
    if aod_col is None:
        raise AeronetEmptyError("no AOD wavelength column in response")

    meta = SiteMeta(
        name="",
        latitude=NODATA,
        longitude=NODATA,
        elevation=NODATA,
    )
    points: list[AodPoint] = []
    for row in reader:
        if len(row) < len(header) or not row[0].strip():
            continue
        site_name = row[0].strip()
        try:
            d = dt.datetime.strptime(row[idx["Date(dd:mm:yyyy)"]], "%d:%m:%Y")
            t = dt.datetime.strptime(row[idx["Time(hh:mm:ss)"]], "%H:%M:%S")
            when = dt.datetime.combine(
                d.date(), t.time(), tzinfo=dt.timezone.utc
            )
        except (KeyError, ValueError):
            continue
        try:
            aod = float(row[idx[aod_col]])
        except ValueError:
            continue
        if aod < 0:
            continue  # -999 no-data (and noisy negatives)
        points.append(AodPoint(time=when, aod=aod, wavelength=aod_col))
        if meta.name == "":
            meta.name = site_name
            try:
                meta.latitude = float(row[idx["Site_Latitude(Degrees)"]])
                meta.longitude = float(row[idx["Site_Longitude(Degrees)"]])
                meta.elevation = float(row[idx["Site_Elevation(m)"]])
            except (KeyError, ValueError):
                pass
            ldp_col = idx.get("Last_Date_Processed")
            if ldp_col is not None:
                try:
                    ldp = dt.datetime.strptime(row[ldp_col], "%d:%m:%Y")
                    meta.last_date_processed = ldp.replace(
                        hour=0, minute=0, second=0, tzinfo=dt.timezone.utc
                    )
                except ValueError:
                    meta.last_date_processed = None

    if not points and meta.name == "":
        # Header present but zero rows: valid response, no data in window.
        meta.name = "unknown"
    points.sort(key=lambda p: p.time)
    return AeronetData(meta=meta, points=points)


def latest_point(data: AeronetData) -> AodPoint | None:
    return data.points[-1] if data.points else None


def mean_last_24h(data: AeronetData, now: dt.datetime | None = None) -> float | None:
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=24)
    vals = [p.aod for p in data.points if p.time >= cutoff]
    if not vals:
        # Fall back to the last calendar day with data.
        if not data.points:
            return None
        last_day = data.points[-1].time.date()
        vals = [p.aod for p in data.points if p.time.date() == last_day]
    return round(sum(vals) / len(vals), 4)


def daily_series(data: AeronetData) -> dict[str, float]:
    """Mean AOD per calendar day (UTC), for history-friendly attributes."""
    buckets: dict[str, list[float]] = {}
    for p in data.points:
        buckets.setdefault(p.time.date().isoformat(), []).append(p.aod)
    return {day: round(sum(v) / len(v), 4) for day, v in sorted(buckets.items())}


def recent_points(data: AeronetData, hours: int = 24) -> list[list[str | float]]:
    """[iso_time, aod] pairs of the last `hours` for graphing attributes."""
    if not data.points:
        return []
    cutoff = data.points[-1].time - dt.timedelta(hours=hours)
    return [
        [p.time.isoformat(), p.aod] for p in data.points if p.time >= cutoff
    ]
