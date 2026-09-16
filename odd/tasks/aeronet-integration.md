# AERONET custom integration for Home Assistant

## Objective
Custom component `custom_components/aeronet/` (HACS-friendly) que muestra AOD de NASA AERONET
para una estación elegida por el usuario vía select entity, config flow UI, DataUpdateCoordinator.

## Evidence from exploration (verified 2026-09-16)
- Site list: aeronet_locations_v3.txt — banner + cabecera + ~1675 filas (Site_Name,Lon,Lat,Elev).
- Web service print_web_data_v3: obligatorios year,month,day,AVG(10|20),AODxx=1; opcionales
  year2/month2/day2, site exact, if_no_html=1. Sin parámetros → HTML de ayuda (detected as error).
- CSV datos: 5+ líneas meta, cabecera "AERONET_Site,Date(dd:mm:yyyy),Time(hh:mm:ss)...", -999=no data, UTC.

## Tasks
- [x] T1 Estructura repo + manifest + const + parsers stdlib (parsers.py, urls.py)
- [x] T2 client/coordinators aiohttp (UA, timeouts, 2 reintentos; sites semanal, datos configurable)
- [x] T3 config flow UI + options flow (email, level, frecuencia; site selector si lista cacheada)
- [x] T4 select estación (persistido en entry data) + 6 sensors (AOD 500nm, 24h media, lat/lon/elev,
      last data, attrs daily_mean_aod + recent_points_24h)
- [x] T5 strings.json + translations en/es
- [x] T6 23 unittest sobre fixtures reales (site list, Madrid CSV, help HTML) — OK en python3 stdlib
- [x] T7 README + .hacs.json + commit git (09a1275)

## Verification
- `python3 -m unittest discover -s tests`: 23 OK.
- `python3 scripts/live_check.py` contra NASA real (Madrid, L1.5): 914 puntos, latest
  2026-09-16T17:08Z AOD_500nm 0.1214, serie 7 días correcta. LIVE OK.

## Known limits (documented in README)
- Select con ~1675 opciones vs sugerencia core ≤600.
- Dropdown del config flow como texto hasta que cargue la lista en el primer arranque.
