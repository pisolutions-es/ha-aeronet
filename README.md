# NASA AERONET for Home Assistant

![AERONET Logo](logo.png)

Custom integration that fetches atmospheric aerosol data from NASA's
[AERONET](https://aeronet.gsfc.nasa.gov/) network, with support for multiple
data products (AOD, SDA, SSA, VOL) and complete time series for analysis.

## What it creates

Adding the integration creates an "AERONET · <station>" device with:

| Entity | Description |
|---|---|
| `sensor.aeronet_<station>_aod` | AOD at latest valid point. Wavelength: **500 nm** (fallback 551/555/560 nm). Includes `today_series` attribute with today's complete time series from 00:00 UTC. |
| `sensor.aeronet_<station>_aod_24h_mean` | Mean AOD from the last 24 hours |
| `sensor.aeronet_<station>_aod_daily` | Today's partial daily average (AERONET AVG=20). Includes `daily_series_7d` attribute with the last 7 daily averages. |
| `sensor.aeronet_<station>_sda_fine` | SDA Fine Mode AOD at 500nm (Fine_Mode_AOD_500nm). Only present if SDA product is enabled. |
| `sensor.aeronet_<station>_sda_coarse` | SDA Coarse Mode AOD at 500nm (Coarse_Mode_AOD_500nm). Includes `fine_mode_fraction` attribute. Only present if SDA product is enabled. |
| `sensor.aeronet_<station>_ssa` | Single Scattering Albedo, preferred wavelength 440nm. Includes `wavelength` attribute. Only present if SSA product is enabled. |
| `sensor.aeronet_<station>_vol` | Volume concentration VolC-T in µm³/cm³. Includes `vol_fine`, `vol_coarse`, `effective_radius` attributes. Only present if VOL product is enabled. |
| `sensor.aeronet_<station>_last_data` | Timestamp (UTC) of the latest data point |
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
- **Initial station**: dropdown once the station list is cached; otherwise a
  text field taking the exact name (list at
  https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt). Change it later via
  the select entity.
- **Email (optional)**: AERONET recommends registering an email for heavy web
  service usage.
- **Data level**: 1.0 (provisional calibration), 1.5 (recommended) or 2.0
  (AERONET-net validated).
- **Update interval**: 10–1440 min (default 60).
- **Products**: Multi-select for AERONET data products to fetch (default: AOD only).

### Available Products
- **AOD** (Aerosol Optical Depth): Direct-sun measurements, all points and daily averages
- **SDA** (Size Distribution Algorithm): Fine/coarse mode aerosol optical depth at 500nm
- **SSA** (Single Scattering Albedo): Inversion product, wavelengths 440-1020nm  
- **VOL** (Volume concentration): Inversion product, µm³/cm³ units

Each enabled product creates its own sensor entities. Products use different AERONET endpoints and update intervals.

## Technical details

### Data intervals and endpoints
- **AOD all-points**: Last 7 days, `AVG=10` (all available measurements)
- **AOD daily averages**: Last 7 days, `AVG=20` (one value per day at solar noon)
- **SDA products**: Last 7 days, `AVG=10`, separate direct-sun endpoint
- **SSA/VOL products**: Last 7 days, `AVG=10`, inversion algorithm endpoint (`print_web_data_inv_v3`)

### Implementation
- A `DataUpdateCoordinator` per station plus one global station-list
  coordinator with in-memory cache and weekly refresh.
- Multi-product fetching with partial failure tolerance (failed products keep
  previous data).
- aiohttp client with identifiable User-Agent (`home-assistant-aeronet/0.2`),
  15s connect / 60s total timeout, 2 retries with backoff.
- Config entry migration: v1→v2 adds products field for existing installs.

## Tests

```
python3 -m unittest discover -s tests
```

60+ tests covering real fixtures (station-list CSV, Valladolid data across all
products, CSV parsing, URL generation, sensor state mapping). Stdlib only.

## Known limitations

- **Select with ~1,675 options**: HA core suggests ≤600 options per select
  entity. The UI allows it but may be slow; if a future build enforces a
  limit, the sensors still work with the station stored in the config entry.
- The station list is cached in memory; after an HA restart it is served from
  the last fetch on refresh (first boot: the config-flow dropdown may appear
  as a text field until the list loads).
- AERONET asks users not to hammer the web service: intervals <30 min with
  many instances can trip rate limits (HTTP 429 → the coordinator retries).
- Data is in UTC (AERONET reports UTC); the timestamp sensor shows it as such.
- Some stations have no data for the last 7 days → sensors stay `unavailable`
  until the next poll returns data.
- Stations with duplicate names in the list appear once in the dropdown.
- All data is public (NASA open data); the integration never writes to NASA.
