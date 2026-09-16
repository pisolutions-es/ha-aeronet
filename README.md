# NASA AERONET para Home Assistant

Integración custom que muestra la Profundidad Óptica de Aerosoles (AOD) de la
red [AERONET](https://aeronet.gsfc.nasa.gov/) de la NASA para la estación que
eligas de un dropdown con las ~1675 estaciones mundiales.

## Qué crea

Al añadir la integración se crea un dispositivo "AERONET · <estación>" con:

| Entidad | Descripción |
|---|---|
| `sensor.aeronet_aod` | AOD del último punto válido. Longitud de onda: **500 nm** (columna `AOD_500nm`); si la estación no la publica, fallback automático a 551/555/560 nm (se indica en el atributo `wavelength`). |
| `sensor.aeronet_aod_24h_mean` | Media de los puntos de las últimas 24 h |
| `sensor.aeronet_last_data` | Timestamp (UTC) del último dato |
| `sensor.aeronet_latitude/longitude/elevation` | Ubicación de la estación |
| `select.aeronet_station` | Dropdown para cambiar de estación en caliente |

El sensor principal lleva attributes pensados para graficar con history:
- `daily_mean_aod`: media por día de los últimos 7 días.
- `recent_points_24h`: puntos horarios `[iso_time, aod]` de las últimas 24 h.

## Instalación

### Manual
1. Copia `custom_components/aeronet/` a `<config>/custom_components/aeronet/`.
2. Reinicia Home Assistant.
3. Configuración → Dispositivos y servicios → Añadir integración → "NASA AERONET".

### HACS
Añade este repo como *custom repository* (tipo "Integration") y espérala en el
buscador de HACS. (Una vez publicado, se puede declarar `homeassistant`
category en `.hacs.json`.)

### Config flow
- **Estación inicial**: dropdown si la lista ya está cacheada; si no, campo de
  texto con el nombre exacto (lista en
  https://aeronet.gsfc.nasa.gov/aeronet_locations_v3.txt). Luego se cambia con
  la entidad select.
- **Email (opcional)**: AERONET recomienda registrar un email para el web
  service de uso intensivo.
- **Nivel de datos**: 1.0 (calibrado provisional), 1.5 (recomendado) o 2.0
  (validado con AERONET-Net).
- **Frecuencia**: 10–1440 min (por defecto 60).

## Detalles técnicos

- `DataUpdateCoordinator` por estación + un coordinador global de la lista de
  estaciones con caché en memoria y refresco semanal.
- Ventana de datos: últimos 7 días, formato "all points" (`AVG=10`), `if_no_html=1`.
- Cliente aiohttp con User-Agent identificable (`home-assistant-aeronet/1.0`),
  timeout de conexión 15 s / total 60 s, 2 reintentos con backoff.
- Si AERONET devuelve su página HTML de ayuda (parámetros inválidos), se
  traduce a un error claro en el coordinador en vez de parsear basura.

## Tests

```
python3 -m unittest discover -s tests
```

23 tests sobre fixtures reales (CSV de estaciones, CSV de datos de Madrid,
página HTML de ayuda del web service). Solo stdlib, sin instalar nada.

## Límites conocidos

- **El select con ~1675 opciones**: HA core sugiere ≤600 opciones por entidad
  select. La UI lo permite pero puede ir lento; si tu build lo limita, el
  sensor igualmente funciona con la estación guardada en el config entry.
- La lista de estaciones se cachea en memoria; tras reiniciar HA se sirve del
  disco/último fetch al refrescar (primer arranque: el dropdown del config
  flow puede aparecer como campo de texto hasta que cargue la lista).
- AERONET pide no abusar del web service: intervalos <30 min con muchas
  instancias pueden disparar el límite (HTTP 429 → el coordinador reintenta).
- Datos en UTC (AERONET reporta UTC); el sensor de timestamp lo muestra así.
- Algunas estaciones no tienen datos de los últimos 7 días → sensores
  `unavailable` hasta el siguiente polling con datos.
- Estaciones con nombres duplicados en la lista se muestran una sola vez en el
  dropdown.
- La integración no pide permiso de escritura en el repo NASA; los datos son
  públicos (NASA open data).
