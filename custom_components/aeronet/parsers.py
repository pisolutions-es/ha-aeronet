"""Pure-stdlib parsers for AERONET CSV/HTML payloads.

Kept free of Home Assistant imports so they can be unit tested anywhere.
All functions are synchronous and operate on already-decoded ``str`` bodies.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

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


class AeronetSiteMismatchError(AeronetError):
    """Rows belong to a different site (or several sites mixed) instead of
    the one requested. AERONET silently drops a malformed/blank ``site``
    parameter and returns *all* stations, so this must be treated as an
    error rather than parsed as data."""


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
    # Per-payload extra attribute series (e.g. SDA fine_mode_fraction keyed by
    # ISO time). Not a sensor value; consumed by entity attributes.
    extras: dict = field(default_factory=dict)


@dataclass
class AeronetData:
    meta: SiteMeta
    points: list[AodPoint] = field(default_factory=list)
    # Extra product series keyed by slot name: "aod_daily", "sda_fine",
    # "sda_coarse", "ssa", "vol". Each is a chronological list of points whose
    # ``wavelength`` field records the CSV column the value came from.
    values: dict[str, list[AodPoint]] = field(default_factory=dict)


# Column candidate sets per product slot (first match in the header wins).
# Names verified against live Valladolid payloads 2026-09-16: the SDA payload
# uses bracketed names (Fine_Mode_AOD_500nm[tau_f]); SSA comes from the
# inversion service (Single_Scattering_Albedo[<nm>], typically 440/675/870/1020);
# VOL total volume concentration is VolC-T [µm³/cm³].
AOD_DAILY_SLOT = "aod_daily"
SDA_FINE_SLOT = "sda_fine"
SDA_COARSE_SLOT = "sda_coarse"
SSA_SLOT = "ssa"
VOL_SLOT = "vol"

AOD_COLUMNS = AOD_WAVELENGTHS
SDA_FINE_COLUMNS = ("Fine_Mode_AOD_500nm[tau_f]", "Fine_Mode_AOD_500nm")
SDA_COARSE_COLUMNS = ("Coarse_Mode_AOD_500nm[tau_c]", "Coarse_Mode_AOD_500nm")
SSA_COLUMNS = (
    "Single_Scattering_Albedo[500nm]",
    "Single_Scattering_Albedo[550nm]",
    "Single_Scattering_Albedo[440nm]",
    "Single_Scattering_Albedo[675nm]",
    "Single_Scattering_Albedo[870nm]",
    "Single_Scattering_Albedo[1020nm]",
)
VOL_COLUMNS = ("VolC-T", "VolC")

# SDA payload also carries the fine-mode fraction per row (attribute data).
SDA_FRACTION_COLUMNS = ("FineModeFraction_500nm[eta]", "FineModeFraction_500nm")


def is_help_html(body: str) -> bool:
    """Detect the web service HTML help/error page (invalid parameters)."""
    head = body[:2000]
    lowered = head.lower()
    return (
        "<html" in lowered
        or "<!doctype html" in lowered
        or "aeronet version 3 web service help" in lowered
    )


def normalize_site(site: str) -> str:
    """Canonical station name: no surrounding whitespace.

    AERONET station names never contain spaces (they use underscores), and
    the web service silently *drops* a ``site`` parameter that does not match
    an exact station name — returning every station's rows mixed together.
    Every boundary that carries a station name must pass it through here.
    """
    return (site or "").strip()


def _canonical_site(site: str) -> str:
    """Comparison form of a station name: case-insensitive, and any run of
    whitespace/underscores collapsed to a single underscore."""
    return "_".join(normalize_site(site).lower().replace(" ", "_").split("_"))


# Suffix pattern for disambiguating genuinely duplicated station names in
# the dropdown (see dedupe_display_names).
import re as _re

_DISPLAY_SUFFIX_RE = _re.compile(r" \(-?\d+\.\d{2}, ?-?\d+\.\d{2}\)$")


def dedupe_display_names(sites) -> list[str]:
    """Sorted, unique display names for the station dropdown/select.

    Plain duplicates (the same station listed twice) collapse to one entry.
    Genuinely *different* stations that share a name are kept apart with a
    coordinate suffix `` (lat, lon)`` so a user can tell them apart and the
    real name can be recovered with ``display_to_site_name``. The active
    v3921 list has no duplicate names (verified 2026-09-16); this is
    defensive for the full historical list.
    """
    by_name: dict[str, set[str]] = {}
    for s in sites:
        name = normalize_site(s.name)
        if name:
            by_name.setdefault(name, set()).add(f"{s.latitude:.2f},{s.longitude:.2f}")
    display: list[str] = []
    for name, coords in by_name.items():
        if len(coords) == 1:
            display.append(name)
        else:
            display.extend(f"{name} ({c})" for c in sorted(coords))
    return sorted(display)


def display_to_site_name(display: str) -> str:
    """Reverse a deduped display label back to the real AERONET station name.

    A coordinate suffix added by ``dedupe_display_names`` is stripped; every
    other label passes through ``normalize_site`` unchanged. Selecting a
    suffixed option therefore still queries AERONET with the exact name the
    web service expects.
    """
    return _DISPLAY_SUFFIX_RE.sub("", normalize_site(display))

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
        # Direct-sun AOD/TOT payloads start 'AERONET_Site,Date(dd:mm:yyyy)';
        # SDA and inversion payloads start 'AERONET_Site,Date_(dd:mm:yyyy)'
        # (note the underscore) — accept both prefixes.
        if line.startswith("AERONET_Site,Date"):
            return i
    return None


_DATE_KEYS = ("Date(dd:mm:yyyy)", "Date_(dd:mm:yyyy)")
_TIME_KEYS = ("Time(hh:mm:ss)", "Time_(hh:mm:ss)")


def _pick(idx: dict[str, int], keys: tuple) -> int | None:
    for k in keys:
        if k in idx:
            return idx[k]
    return None


def parse_data_csv(
    body: str,
    expected_site: str | None = None,
    *,
    column_sets: dict[str, tuple] | None = None,
) -> AeronetData:
    """Parse an AERONET all-points or daily-average CSV response.

    Format: 5+ banner lines, a header line starting 'AERONET_Site,Date...'
    (SDA/inversion payloads use 'Date_'/Time_' with an underscore), then one
    row per measurement or per day. -999.0 means no data.

    ``column_sets`` maps slot name -> candidate column tuple. The slot named
    first (or 'aod' for AOD payloads) fills ``data.points``; every slot also
    lands in ``data.values``. Default is the AOD wavelength fallback chain.

    When ``expected_site`` is given, the parsed rows are checked against it:
    the web service silently ignores an unmatched ``site`` parameter and
    replies with every station's rows, so a multi-site payload or a payload
    from another station raises AeronetSiteMismatchError instead of being
    returned as if it were the requested site's data.
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

    if column_sets is None:
        column_sets = {"aod": AOD_COLUMNS}
    resolved: dict[str, int] = {}
    for slot, candidates in column_sets.items():
        col = _pick(idx, candidates)
        if col is not None:
            resolved[slot] = col
    if not resolved:
        raise AeronetEmptyError(
            "none of the requested columns in response: "
            + ", ".join(sorted(c for cs in column_sets.values() for c in cs))
        )
    primary_slot = next(
        (s for s in column_sets if s in resolved and s == "aod"),
        next(s for s in column_sets if s in resolved),
    )
    value_slots = list(resolved)

    # Fine-mode fraction is attribute data on SDA payloads, not a sensor.
    frac_col = idx.get(SDA_FRACTION_COLUMNS[0])
    if frac_col is None:
        frac_col = idx.get(SDA_FRACTION_COLUMNS[1])

    meta = SiteMeta(
        name="",
        latitude=NODATA,
        longitude=NODATA,
        elevation=NODATA,
    )
    series: dict[str, list[AodPoint]] = {s: [] for s in value_slots}
    fractions: dict[str, float] = {}
    sites_seen: set[str] = set()
    date_col = _pick(idx, _DATE_KEYS)
    time_col = _pick(idx, _TIME_KEYS)
    for row in reader:
        if len(row) < len(header) or not row[0].strip():
            continue
        site_name = row[0].strip()
        sites_seen.add(_canonical_site(site_name))
        if date_col is None or time_col is None:
            continue
        try:
            d = dt.datetime.strptime(row[date_col], "%d:%m:%Y")
            t = dt.datetime.strptime(row[time_col], "%H:%M:%S")
            when = dt.datetime.combine(
                d.date(), t.time(), tzinfo=dt.timezone.utc
            )
        except ValueError:
            continue
        row_ok = False
        for slot in value_slots:
            col = resolved[slot]
            try:
                val = float(row[col])
            except (ValueError, IndexError):
                continue
            if val < 0:
                continue  # -999 no-data (and noisy negatives)
            series[slot].append(
                AodPoint(time=when, aod=val, wavelength=header[col])
            )
            row_ok = True
            if frac_col is not None and slot == SDA_FINE_SLOT:
                try:
                    frac = float(row[frac_col])
                except (ValueError, IndexError):
                    frac = NODATA
                if frac >= 0:
                    fractions[when.isoformat()] = round(frac, 4)
        if row_ok and meta.name == "":
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

    if series.get(primary_slot) is None:
        series[primary_slot] = []
    if not any(series.values()) and meta.name == "":
        # Header present but zero usable rows: valid response, no data in window.
        meta.name = "unknown"
    for lst in series.values():
        lst.sort(key=lambda p: p.time)
    if fractions:
        meta.extras["fine_mode_fraction"] = fractions

    expected = normalize_site(expected_site or "")
    if expected and sites_seen:
        if len(sites_seen) > 1:
            sample = ", ".join(sorted(sites_seen)[:5])
            _LOGGER.warning(
                "AERONET returned %d mixed sites (expected '%s'); sample: %s",
                len(sites_seen), expected, sample,
            )
            raise AeronetSiteMismatchError(
                f"AERONET returned data for {len(sites_seen)} different "
                f"stations instead of the requested '{expected}' — the site "
                "parameter was not matched by the web service"
            )
        returned = next(iter(sites_seen))
        if returned != _canonical_site(expected):
            _LOGGER.warning(
                "AERONET returned site '%s' but '%s' was requested",
                meta.name, expected,
            )
            raise AeronetSiteMismatchError(
                f"AERONET returned data for site '{meta.name}' instead of "
                f"the requested '{expected}' — the site parameter was not "
                "matched by the web service"
            )
    points = series[primary_slot]
    return AeronetData(meta=meta, points=points, values=series)


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


def latest_value(
    data: AeronetData, slot: str, hours: int | None = None
) -> AodPoint | None:
    """Latest point of a product series (optionally within the last `hours`)."""
    pts = data.values.get(slot) or []
    if hours is not None:
        if not pts:
            return None
        cutoff = pts[-1].time - dt.timedelta(hours=hours)
        pts = [p for p in pts if p.time >= cutoff]
    return pts[-1] if pts else None


def value_series(
    data: AeronetData, slot: str, points: list[AodPoint] | None = None
) -> list[list[str | float]]:
    """[iso_time, value] pairs of a product series for graphing attributes."""
    pts = points if points is not None else (data.values.get(slot) or [])
    return [[p.time.isoformat(), p.aod] for p in pts]


def today_series(
    data: AeronetData, now: dt.datetime | None = None
) -> list[list[str | float]]:
    """Full current UTC day [iso_time, aod] series (00:00 -> latest point).

    Sourced from the all-points fetch, so it covers today's measurements
    since midnight regardless of how long the poll window is.
    """
    if not data.points:
        return []
    ref = max(p.time for p in data.points)
    midnight = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        [p.time.isoformat(), p.aod] for p in data.points if p.time >= midnight
    ]


def last_days_series(
    data: AeronetData, slot: str, days: int = 7
) -> dict[str, float]:
    """Latest value per calendar day (UTC) for the last `days`, keyed by ISO day."""
    pts = data.values.get(slot) or []
    buckets: dict[str, AodPoint] = {}
    for p in pts:  # chronological: last valid point of each day wins
        buckets[p.time.date().isoformat()] = p
    return {d: round(b.aod, 4) for d, b in sorted(buckets.items())[-days:]}
