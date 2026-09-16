# AERONET custom integration for Home Assistant

## Objective
Custom component `custom_components/aeronet/` (HACS-friendly) que muestra AOD de NASA AERONET
para una estación elegida por el usuario vía select entity, config flow UI, DataUpdateCoordinator.

## Evidence from exploration (verified 2026-09-16)
- Site list: https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt — línea 1 "AERONET_Database_Site_List,...",
  línea 2 cabecera `Site_Name,Longitude(decimal_degrees),Latitude(decimal_degrees),Elevation(meters)`, ~1675 filas.
- Web service: /cgi-bin/print_web_data_v3. Parámetros obligatorios (doc oficial): year,month,day, AVG
  (10=all points, 20=daily), data_type AOD10|AOD15|AOD20=1. Opcionales: year2/month2/day2, site (exact match),
  if_no_html=1. Sin parámetros devuelve HTML de ayuda ("Error: Not enough parameters").
- CSV datos real (Madrid, L1.5, AVG=10): 5 líneas meta, línea 6 = cabecera columnas (`AERONET_Site,
  Date(dd:mm:yyyy),Time(hh:mm:ss),...AOD_500nm(index 18)...Site_Latitude(Degrees),Site_Longitude(Degrees),
  Site_Elevation(m)...Last_Date_Processed,...`). -999.0 = sin dato. Fecha UTC, formato dd:mm:yyyy + hh:mm:ss.
- Ejemplo real validado: site=Madrid&year=2026&month=9&day=10&year2=2026&month2=9&day2=16&AOD15=1&AVG=10&if_no_html=1

## Scope
Wavelength primario: AOD_500nm, fallback AOD_551nm (documentado en README).
Ventana de datos: últimos 7 días (incluye hoy UTC).

## Tasks
- [ ] T1 Estructura repo + manifest + const + parsers (site list, data CSV, help-error) — stdlib puro
- [ ] T2 client/coordinators (aiohttp, UA, timeouts, reintentos; sites semanal, datos configurable)
- [ ] T3 config flow UI (email opcional, level 1.0/1.5/2.0, frecuencia; validación site name)
- [ ] T4 select entity estación + sensors (AOD actual, lat/lon/elev, último dato, media 24h, serie días en attrs)
- [ ] T5 strings/translations en+es
- [ ] T6 tests unittest con fixtures reales extraídos de la exploración
- [ ] T7 README + commit git

## Constraints
- No bloquear event loop (aiohttp, no requests). Sin dependencias extra más allá de aiohttp.
- Attributes ≤ ~16KB (límite event bus HA): serie = medias diarias (7 pts) + puntos horarios 24h (~24 pts).
- Tests solo con stdlib (unittest), sin importar homeassistant.

## Checks
- `python3 -m unittest discover tests` verde.
- `python3 -m py_compile` de todos los módulos con imports HA (sintaxis).
