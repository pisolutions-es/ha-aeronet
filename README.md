# NASA AERONET for Home Assistant

![AERONET Logo](logo.png)

Custom integration that fetches atmospheric aerosol data from NASA's
[AERONET](https://aeronet.gsfc.nasa.gov/) network, with support for multiple
data products (AOD, SDA, SSA, VOL) and complete time series for analysis.

## What it creates

Adding the integration creates an "AERONET · <station>" device with:

| Entity | Description |
|---|---|
| `sensor.aeronet_<station>_aod` | AOD at latest valid point. Wavelength: **500 nm** (fallback 551/555/560 nm). Includes `today_series` attribute with today's complete time series from 00:00 UTC and `channels_latest` with the last value of every wavelength channel (see *Wavelength channels*). |
| `sensor.aeronet_<station>_aod_<nm>nm` | One sensor per AOD wavelength channel (e.g. `aod_340nm` … `aod_1640nm`), created automatically for every wavelength the station actually reports. Excludes 500 nm (that is the main `aod` sensor). See *Wavelength channels*. |
| `sensor.aeronet_<station>_ssa_<nm>nm` | One sensor per SSA wavelength channel (typically 440/675/870/1020 nm) when the SSA product is enabled; the preferred channel stays in `sensor.aeronet_<station>_ssa`. |
| `sensor.aeronet_<station>_aod_24h_mean` | Mean AOD from the last 24 hours |
| `sensor.aeronet_<station>_aod_daily` | Today's partial daily average (AERONET AVG=20). Includes `daily_series_7d` attribute with the last 7 daily averages. |
| `sensor.aeronet_<station>_sda_fine` | SDA Fine Mode AOD at 500nm (Fine_Mode_AOD_500nm). Only present if SDA product is enabled. |
| `sensor.aeronet_<station>_sda_coarse` | SDA Coarse Mode AOD at 500nm (Coarse_Mode_AOD_500nm). Includes `fine_mode_fraction` attribute. Only present if SDA product is enabled. |
| `sensor.aeronet_<station>_ssa` | Single Scattering Albedo, preferred wavelength 440nm. Includes `wavelength` attribute. Only present if SSA product is enabled. |
| `sensor.aeronet_<station>_vol` | Volume concentration VolC-T in µm³/cm³. Includes `vol_fine`, `vol_coarse`, `effective_radius` attributes. Only present if VOL product is enabled. |
| `sensor.aeronet_<station>_last_data` | Timestamp of the latest data point (UTC internally; shown in your local time via the `timestamp` device class) |
| `sensor.aeronet_<station>_latitude/longitude/elevation` | Station location |
| `select.aeronet_<station>_station` | Dropdown to switch stations at runtime |

Product selection is configured per integration instance. Default: AOD only.

## Installation

### Manual
1. Copy `custom_components/aeronet/` into `<config>/custom_components/aeronet/`.
2. Restart Home Assistant.
3. Settings → Devices & services → Add integration → "NASA AERONET".

### HACS
Add this repository as a *custom repository* (type "Integration") and it will
appear in the HACS explorer.

### Config flow
- **Initial station**: dropdown fed from the active station list
  (`https://aeronet.gsfc.nasa.gov/aeronet_locations_v3921.txt`, loaded from
  disk on first boot), falling back to a text field with the exact name only
  if no list is available yet. Change it later via the select entity.
- **Email (optional)**: AERONET recommends registering an email for heavy web
  service usage.
- **Data level**: 1.0 (provisional calibration), 1.5 (recommended) or 2.0
  (AERONET-net validated).
- **Update interval**: 10–1440 min (default 60).
- **Products**: Multi-select for AERONET data products to fetch (default: AOD only).
- **Station list source** (options dialog): active stations (v3921, default)
  or the full historical list.

### Available Products
- **AOD** (Aerosol Optical Depth): Direct-sun measurements, all points and daily averages
- **SDA** (Size Distribution Algorithm): Fine/coarse mode aerosol optical depth at 500nm
- **SSA** (Single Scattering Albedo): Inversion product, wavelengths 440-1020nm  
- **VOL** (Volume concentration): Inversion product, µm³/cm³ units

Each enabled product creates its own sensor entities. Products use different AERONET endpoints and update intervals.

### Wavelength channels (v0.4.0)

AERONET reports aerosol optical depth at many wavelengths at once (up to
~20 columns, 340–1640 nm, depending on the station's photometer). Instead
of exposing only one preferred wavelength, the integration now keeps **all
channels found in the data**:

- **Automatic detection**: channel sets are discovered from what the
  station actually reports (a column that is always `-999` produces no
  entity), so Valladolid shows `aod_340nm` … `aod_1640nm` while another
  station may show fewer.
- **The product picker is unchanged**: channels appear as soon as the AOD
  product is selected (and SSA channels when SSA is enabled). The main
  `aod` sensor keeps its exact entity_id and behavior, so existing
  dashboards keep working.
- **Configuration**: the options dialog (⋙ on the integration card) has a
  *Wavelength channels* multi-select, pre-filled with the channels detected
  for your station. Deselecting a channel makes its sensor `unavailable`
  (its history is kept). Empty/absent selection = all detected channels,
  which is the default for fresh installs and migrated v0.3.x entries.
- **Attributes**: the main `aod` (and `ssa`) sensor carries
  `channels_latest`, a compact `{ "AOD 340nm": 0.043, ... }` spectrum map
  — a single-entity way to chart AOD(λ) like NASA's official product
  pages. Each channel sensor carries its own `today_series` and
  `recent_points_24h` for per-channel ApexCharts cards.
- **Attribute size limit**: Home Assistant's recorder refuses state
  objects whose attributes exceed **16 KiB**. Channel sensors therefore
  build their attributes under a 14 KiB budget: if a station's series
  would not fit, `recent_points_24h` is dropped first, then
  `today_series`, and the attribute `series_limited: true` marks the
  omission. The complete full-day series always remain on the main 500 nm
  `aod` sensor; `channels_latest` is small and never dropped.
- **VOL has no wavelength channels**: its columns (VolC-T/F/C, REff-T) are
  size-retrieval components, not wavelengths, so the VOL product keeps its
  single sensor with component attributes.

## Technical details

### Data intervals and endpoints
- **AOD all-points**: Last 7 days, `AVG=10` (all available measurements)
- **AOD daily averages**: Last 7 days, `AVG=20` (one value per day at solar noon)
- **SDA products**: Last 7 days, `AVG=10`, separate direct-sun endpoint
- **SSA/VOL products**: Last 7 days, `AVG=10`, inversion algorithm endpoint (`print_web_data_inv_v3`)

### Implementation
- A `DataUpdateCoordinator` per station plus one station-list coordinator
  per configured source URL, with in-memory + disk (HA storage helper)
  cache, weekly refresh and date-stamped payloads.
- Multi-product fetching with partial failure tolerance (failed products keep
  previous data) and automatic 30-day window widening when the 7-day payload
  is empty.
- aiohttp client with identifiable User-Agent (`home-assistant-aeronet/0.4`),
  15s connect / 60s total timeout, 2 retries with exponential backoff +
  jitter and `Retry-After` honored on HTTP 429.
- Config entry migration: v1→v2 adds products, v2→v3 introduces the
  channel layer (selection lives in entry options; a missing selection
  means all channels detected in the data), so existing installs upgrade
  in place and immediately see every channel.

## Tests

```
python3 -m unittest discover -s tests
```

85+ tests covering real fixtures (active v3921 station list, Valladolid data
across all products and all wavelength channels 340–1640 nm, CSV parsing,
URL generation incl. the widened 30-day
window, HTTP retry/Retry-After behaviour, site-list disk persistence and
dedupe, sensor state mapping, config-entry migrations v1→v3 and the
attribute-size budget rule). Stdlib only (aiohttp/Home Assistant stubbed).

## Known limitations

Resolved in v0.3.0 (each item states what the integration does now):

- **Select options**: the station list now defaults to the *active* station
  file (`aeronet_locations_v3921.txt`, 562 stations), which stays under HA
  core's ~600-options-per-select suggestion. The full historical list
  (`aeronet_locations_v3.txt`, ~1,675 stations incl. inactive sites) can be
  selected in the options dialog; if a future HA build enforces the 600
  suggestion, switch the source back to the active list — sensors keep
  working with the station stored in the config entry either way.
- **Station list cache**: the list is persisted to disk through the Home
  Assistant storage helper, tagged with its fetch date. After an install or
  restart the config-flow dropdown is populated from disk immediately; if
  the cached copy is older than 7 days it is served right away and refreshed
  in the background (no live NASA fetch on the critical path).
- **Empty data windows**: if the 7-day request returns no rows at all (some
  stations only publish campaign or monthly data), the coordinator retries
  once automatically with the window widened to **30 days** and logs it. If
  both windows are empty the sensors stay `unavailable` until the next poll
  returns data — this is intentional: it distinguishes "no data published"
  from "request failed".
- **Rate limits (HTTP 429)**: the client waits for the server's
  `Retry-After` header before retrying (bounded to 300 s) and uses
  exponential backoff with jitter on transient errors. AERONET still asks
  users not to hammer the web service: intervals <30 min with many
  instances can trip rate limits; the integration backs off instead of
  hammering.
- **Duplicate station names**: genuinely different stations that share a
  name are shown in the dropdown with a `(lat, lon)` suffix so each is
  selectable, and the exact AERONET name is recovered when you pick one.
  Exact duplicate rows collapse to a single entry. (The active v3921 list
  currently has no duplicate names; the handling is defensive for the full
  list.)
- **Timestamps**: raw AERONET data is UTC and is stored as such. The
  "Last data" sensor uses the `timestamp` device class, so Home Assistant
  renders it in your **local** time in the UI; `today_series`/series
  attributes keep ISO timestamps with an explicit `+00:00` UTC offset, so
  automations can convert them.

Unchanged:

- All data is public (NASA open data); the integration never writes to NASA.
