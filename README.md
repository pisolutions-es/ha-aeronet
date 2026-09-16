# NASA AERONET for Home Assistant

Custom integration that surfaces Aerosol Optical Depth (AOD) from NASA's
[AERONET](https://aeronet.gsfc.nasa.gov/) network for a station you pick from a
dropdown of ~1,675 stations worldwide.

## What it creates

Adding the integration creates an "AERONET · <station>" device with:

| Entity | Description |
|---|---|
| `sensor.aeronet_aod` | AOD of the latest valid point. Wavelength: **500 nm** (`AOD_500nm` column); if the station does not publish it, automatic fallback to 551/555/560 nm (reported in the `wavelength` attribute). |
| `sensor.aeronet_aod_24h_mean` | Mean of the points from the last 24 h |
| `sensor.aeronet_last_data` | Timestamp (UTC) of the latest data point |
| `sensor.aeronet_latitude/longitude/elevation` | Station location |
| `select.aeronet_station` | Dropdown to switch stations at runtime |

The main sensor carries attributes designed for history graphing:
- `daily_mean_aod`: daily mean over the last 7 days.
- `recent_points_24h`: hourly `[iso_time, aod]` points from the last 24 h.

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

## Technical details

- A `DataUpdateCoordinator` per station plus one global station-list
  coordinator with in-memory cache and weekly refresh.
- Data window: last 7 days, "all points" format (`AVG=10`), `if_no_html=1`.
- aiohttp client with an identifiable User-Agent (`home-assistant-aeronet/1.0`),
  15 s connect / 60 s total timeout, 2 retries with backoff.
- When AERONET returns its HTML help page (invalid parameters), it is
  translated into a clear coordinator error instead of parsing garbage.

## Tests

```
python3 -m unittest discover -s tests
```

23 tests over real fixtures (station-list CSV, Madrid data CSV, web service
HTML help page). Stdlib only, nothing to install.

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
