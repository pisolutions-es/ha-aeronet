# Informe de auditoría y mejora — NASA AERONET para Home Assistant, v0.7.0

Fecha: 2026-10-28
Repositorio: `/opt/data/dev-workspace/aeronet-ha`
Base: `master` @ `c92ff4d` (merge v0.5.1 + v0.6.0)
Rama de trabajo: `feat/v0.7.0-audit-viz`
Instancia de referencia: HA 2026.10.4, estación Valladolid

---

## 1. Qué se ha hecho

1. **Auditoría read-only** de toda la integración con `agy`
   (`gemini-4-argon-medium`, `mode=plan`, sin edición de ficheros). El
   informe completo tiene 114.088 caracteres y está en
   `/opt/data/profiles/dev/cache/scratch/agy_review.md`; el brief que se le
   entregó, en `aeronet_review_brief.md`.
2. **Aplicación de los hallazgos** CRÍTICO/ALTO/MEDIO y de los BAJOS de
   riesgo nulo, con un test de comportamiento por hallazgo que antes no lo
   tenía.
3. **Visualización de primera clase**: atributos nuevos para gráficas
   (`spectrum`, `angstrom_440_870`), decimación de series en vez de descarte,
   dashboard Lovelace versionado en el repo y sección de README.
4. **Migración de la glue de HA** a `pytest-homeassistant-custom-component`
   en un venv aparte (`tests_ha/`, 17 tests contra HA 2026.10.4 real),
   conservando la suite rápida de stubs para los parsers y la lógica pura.

---

## 2. Hallazgos de `agy` y estado de cada uno

El informe de `agy` cerró con una lista priorizada. Todos los CRÍTICO y ALTO
se aplicaron; de los MEDIO/BAJO se aplicó todo salvo dos puntos que se
justifican en la sección 5.

### CRÍTICO

| ID | Hallazgo (resumen de `agy`) | Estado |
| --- | --- | --- |
| C1 | «SDA product is never fetched when AOD is enabled» — SDA solo se pedía como *fallback* si fallaba AOD, así que activar AOD+SDA dejaba `sda_fine`/`sda_coarse` vacíos para siempre | **Corregido**. `_fetch_all()` pide **todos** los productos habilitados en cada ciclo |
| C2 | «Wavelength fallback chain (`AOD_COLUMNS`/`SSA_COLUMNS`) is dead code on real AERONET V3 CSVs» — con `AOD_500nm` a `-999` en todas las filas el sensor principal quedaba *unavailable* | **Corregido**. Se promociona la primera columna candidata con datos y se marca como canal principal de la familia (sin entidad de canal duplicada) |

### ALTO

| ID | Hallazgo | Estado |
| --- | --- | --- |
| H1 | `translations/en.json` sin el bloque `issues` → el usuario inglés veía la clave cruda en el repair issue | **Corregido** + test de paridad `strings.json` ↔ `en`/`es` (claves y placeholders) |
| H2 | `_async_update_listener` no actualizaba el snapshot `"config"` tras `configure()` → cada guardado posterior re-aplicaba el mismo cambio y disparaba un refresco multi-producto | **Corregido** + test (guardado idéntico = no-op, cambio real = aplica) |
| H3 | `latest_value(..., hours=...)` era un no-op matemático (ventana anclada al punto más nuevo) → una fila diaria de hace meses se servía como valor actual | **Corregido**. Ventana anclada en `now`; serie obsoleta → `None` (unknown) |
| H4 | `points_today`/`today_series`/`points_recent` anclados a `max(p.time)` en vez de a UTC `now` | **Corregido**. "Hoy" y "24 h" son ahora el día y la ventana del usuario |
| H5 | El `device_info` dinámico no actualizaba el Device Registry al cambiar de estación, y `unique_id`/`title` derivaban de `entry.data[CONF_SITE]` | **Corregido**. `_refresh_device_name()` actualiza el registro vía `dr.async_get()`; `_station_in_use()` compara también la estación guardada |

### MEDIO

| ID | Hallazgo | Estado |
| --- | --- | --- |
| M1 | `_get_text` reintentaba 4xx permanentes y **mantenía la conexión abierta** durante el `sleep` de `Retry-After` (hasta 5 min) | **Corregido**. Espera fuera del contexto `async with`, 4xx (salvo 408) falla rápido, cuerpo limitado a 8 MiB (`MAX_RESPONSE_BYTES`) + 3 tests |
| M2 | La ventana de 30 días no se propagaba a `fetch_daily`, y un fallo parcial de producto descartaba los datos previos | **Corregido**. `days_used` se recuerda y se usa en el diario; los slots que faltan conservan su serie anterior |
| M3 | Coordinador sin `config_entry`, sin `async_shutdown()` en el unload (temporizador siguiendo sondeando NASA) y `_switch_task` de la select sin cancelar | **Corregido** (los tres). El test real de HA comprueba `_unsub_refresh is None` tras el unload |
| M4 | El desplegable de `CONF_SITE_LIST_URL` mostraba las URLs crudas | **Corregido**. `options=[{"value": …, "label": …}]` |
| M5 | `apply_series_budget` descartaba series enteras en vez de decimar | **Corregido**. Decima la serie más grande (hasta 32 puntos) y solo descarta si aún no cabe; `series_limited: true` |
| M6 | `test_lifecycle.py` sustituía la clase del coordinador globalmente sin restaurarla | **Corregido**. Restauración en `tearDown`; además los tests del cliente re-anclan su propio stub de aiohttp |

### BAJO

| ID | Hallazgo | Estado |
| --- | --- | --- |
| L1 | Sensores numéricos sin `suggested_display_precision`; lat/lon con `device_class: distance` y unidad `"°"` (unidad inválida para esa clase) | **Corregido**. Precisión 4 en AOD/SSA/SDA/VOL; lat/lon sin device class |
| L2 | Peticiones por producto serializadas | **Corregido**. `asyncio.gather` concurrente |
| L3 | `entry.runtime_data` vs `hass.data[DOMAIN][entry.entry_id]` | **Aplicado** en la forma mínima que `agy` recomienda: se rellena `entry.runtime_data` manteniendo `hass.data` como alias |
| L4 | `_sites_saved_at` sin lectores, `options` recalculado en cada acceso, `last_24h_mean_with_window` llamado dos veces | **Parcial**. Cacheados `options` y la media 24 h; `_sites_saved_at` se deja (ver §5) |

### Veredicto de estadísticas de `agy` (`STATISTICS VERDICT`)

- HA 2026.10.4 registra estadísticas de largo plazo para un sensor **sin
  unidad** con `state_class: measurement`. La unidad es opcional.
- **No se debe inventar** una unidad sintética (`""`, `"AOD"`): el recorder
  interpretaría un cambio de unidad y rompería el histórico existente.
- La matriz entidad por entidad del informe confirma que todos los sensores
  de medida de la integración son elegibles; el único no elegible es
  `last_data` (timestamp), que no debe serlo.

Se respetó tal cual: **no se añadió ninguna unidad nueva**. El test de HA real
verifica la regla con el predicado propio de HA
(`sensor/recorder.py::_get_sensor_states`: `state_class` parseable como
`SensorStateClass`).

---

## 3. Cambios, por commit

### `8654340` — fix(aeronet): apply v0.7.0 audit findings

Ficheros: `custom_components/aeronet/{__init__,client,config_flow,const,coordinators,parsers,select,sensor}.py`,
`translations/en.json`. 9 ficheros, +393/−64.

- `parsers.py`: ventanas ancladas a `now` (H3/H4), promoción de columna
  primaria (C2), `channel_spectrum()`, `angstrom_440_870()`.
- `coordinators.py`: `config_entry` (M3), `_fetch_all` concurrente
  multi-producto (C1/L2), `days_used` + ventana ensanchada (M2), retención de
  slots previos ante fallo parcial (M2).
- `client.py` + `const.py`: espera fuera del contexto de respuesta, 4xx rápido,
  `MAX_RESPONSE_BYTES = 8 MiB` (M1).
- `sensor.py`: precisión 4 y lat/lon sin device class (L1), decimación (M5),
  `spectrum`/`angstrom_440_870`, caché de la media 24 h (L4).
- `select.py`: `_options_cache`, `_refresh_device_name` (H5/L4), cancelación de
  `_switch_task` (M3).
- `__init__.py`: `config_entry=entry`, `async_shutdown()` en el unload,
  snapshot actualizado tras `configure()`, `entry.runtime_data` (H2/M3/L3).
- `config_flow.py`: `_station_in_use` compara la estación guardada (H5),
  etiquetas legibles en el desplegable (M4).

### `1babb8a` — test(aeronet): cover the v0.7.0 audit findings

`tests/test_audit_v070.py` (nuevo, 16 tests) + ajustes en `test_channels.py`,
`test_client.py`, `test_lifecycle.py`, `test_products.py`.

Cubre: multi-producto, ensanchado de ventana + diario, retención ante fallo
parcial, snapshot del listener, fallback de columna primaria, orden del
espectro y exponente de Ångström, paridad de traducciones, elegibilidad de
estadísticas, decimación bajo 16 KiB, 4xx rápido / 408 reintentado / cuerpo
demasiado grande.

### `43c3b72` — test(ha): add a pytest-homeassistant-custom-component suite

`tests_ha/{__init__,conftest,test_setup,test_config_flow,test_dashboard}.py`,
`pytest.ini`. 17 tests contra HA 2026.10.4 real.

### `3282541` — feat(viz): ship a Lovelace dashboard and document visualization

`dashboards/aeronet.yaml` (nuevo) y sección «Visualización» del `README.md`.

### `55ca338` — chore(release): 0.7.0

`manifest.json` 0.6.0 → 0.7.0, entrada completa de `CHANGELOG.md`.

---

## 4. Tests: antes y después

| Momento | Comando | Resultado |
| --- | --- | --- |
| Antes (base `c92ff4d`) | `.venv/bin/python -m unittest discover -s tests -q` | **184 tests OK** |
| Después | `.venv/bin/python -m unittest discover -s tests` | **Ran 204 tests — OK** |
| Después (HA real) | `.venv-ha/bin/python -m pytest tests_ha` | **17 passed** |

`.venv-ha` es Python 3.14 con `homeassistant==2026.10.4`,
`pytest-homeassistant-custom-component` y `pytest`, instalado con `uv`. La
suite de stubs y la de HA real **no pueden convivir en un mismo proceso**:
`tests/ha_stubs.py` inyecta módulos falsos de `homeassistant` en
`sys.modules`. Por eso `pytest.ini` fija `testpaths = tests_ha`.

Qué añade la suite real que los stubs no podían dar:

- Las entidades se crean de verdad y los `entity_id` publicados en español se
  comprueban uno a uno (`sensor.aeronet_valladolid_aod`, `_aod_media_24h`,
  `_aod_media_diaria`, `_ultimo_dato`, `_aod_440nm`).
- Elegibilidad de estadísticas con la regla de HA, no con una suposición.
- El unload deja `_unsub_refresh is None` (M3 verificado, no solo escrito).
- Los dos flows validan contra los selectores reales y
  `OptionsFlowWithConfigEntry`.
- El dashboard se parsea con PyYAML y solo referencia entidades existentes.

---

## 5. Qué se descartó y por qué

1. **M3, punto 3 — contador de fallos reiniciado en cada reintento de
   arranque.** `agy` señala que durante el bucle de `ConfigEntryNotReady` se
   crea un coordinador nuevo con `_consecutive_failures = 0`, así que un fallo
   de arranque nunca llega al umbral del repair issue. Es cierto, pero
   arreglarlo exige persistir el contador entre intentos (estado en
   `hass.data` o en el propio entry) para un beneficio marginal: durante el
   arranque HA ya reintenta y el usuario ve la entrada como «not ready». Se
   documenta como comportamiento conocido en vez de añadir estado frágil.
2. **L4, punto 1 — `_sites_saved_at` sin lectores.** Es un diccionario que se
   escribe y que los tests limpian, pero nadie lo lee. Eliminarlo obliga a
   tocar varios módulos de test sin ningún beneficio funcional; se deja como
   está y queda anotado.
3. **Migrar `hass.data` → `entry.runtime_data` de forma exclusiva.** `agy`
   advierte de que rompería cuatro ficheros de test que inspeccionan
   `hass.data["aeronet"][entry_id]`. Se aplicó la variante mínima (ambos),
   que es compatible hacia atrás.
4. **Añadir unidad sintética a los sensores AOD/SSA.** Descartado por el
   veredicto de estadísticas: rompería el histórico de largo plazo existente.

Observación colateral (no es una regresión): `select.aeronet_valladolid_station`
existe en la instalación actual porque el `entity_id` se registró cuando la
traducción del nombre aún era inglesa. HA **nunca renombra** un `entity_id` ya
registrado, así que las instalaciones existentes lo conservan; una instalación
nueva en español creará `select.aeronet_valladolid_estacion`. El `unique_id`
(`<entry_id>_site`) sí es estable y es lo que garantiza la continuidad.

---

## 6. Visualización: qué se entrega y cómo se usa

### Atributos nuevos

| Atributo | Entidad | Forma | Para qué |
| --- | --- | --- | --- |
| `spectrum` | `sensor...aod` (y `...ssa`) | `[[340, 0.043], [380, 0.041], …]` ordenado por λ, nm numérico | tarjeta de espectro sin parsear etiquetas |
| `angstrom_440_870` | `sensor...aod` | `float` o `null` | exponente de Ångström α(440–870) derivado |
| `series_limited` | cualquiera con series | `true` cuando se decimó | avisa de que la curva es más gruesa |

`angstrom_440_870` se calcula como `-ln(τ₄₄₀/τ₈₇₀) / ln(440/870)` y devuelve
`null` si falta un canal o el valor no es positivo (el logaritmo no está
definido). Es una magnitud **derivada**, no un producto de NASA; así se
documenta en README y CHANGELOG.

### `dashboards/aeronet.yaml`

Estación de ejemplo: Valladolid (`aeronet_valladolid`). Contiene:

- Cabecera: AOD actual, media 24 h, media diaria, último dato (`glance`), y
  una tarjeta `entities` con el selector de estación, lat/lon/elevación, el
  exponente de Ångström (como atributo) y la entidad `update` de HACS.
- Dos `statistics-graph` nativas (7 días, media horaria): AOD 500 nm y los
  siete canales 340–1640 nm.
- Dos `history-graph` nativas (24 h): canales seleccionados y AOD principal
  con su media 24 h.
- Dos `custom:apexcharts-card` **opcionales**: espectro AOD(λ) desde
  `spectrum` (fallback `channels_latest`) y serie intradía desde
  `recent_points_24h` (fallback `today_series`).
- Comentarios que indican qué atributo alimenta cada tarjeta, cómo sustituir
  la estación y qué borrar si no hay HACS.

### Importarlo

- **Solo UI**: *Ajustes → Paneles → Añadir panel → vacío*, abrirlo, ⋮ →
  *Editar panel* → ⋮ → **Editor de configuración en bruto**, pegar desde la
  línea `title:` y guardar.
- **Modo YAML**: copiar a `<config>/dashboards/aeronet.yaml` y registrar una
  vez con `lovelace/dashboards/create` (`url_path: aeronet`, `mode: yaml`,
  `filename: dashboards/aeronet.yaml`).
- **Otra estación**: sustituir `aeronet_valladolid` por el slug propio.

Requisitos: las tarjetas nativas no necesitan nada (recorder activo por
defecto); ApexCharts exige HACS y `apexcharts-card`, y es opcional.

---

## 7. Compatibilidad

- **No se han cambiado `entity_id` ni `unique_id`.** Verificado en la suite
  de HA real con los ids españoles ya publicados.
- **No se ha cambiado el formato de los estados** (los valores siguen siendo
  números o ISO-8601 como antes). Los atributos nuevos son aditivos.
- **`manifest.json` sigue con `requirements: []`**; no hay dependencias
  nuevas.
- `ENTRY_VERSION` no cambia: no hay migración en esta versión.
- El único cambio de comportamiento visible es deliberado y está documentado:
  una serie obsoleta ahora reporta `unknown` en vez de un valor viejo (H3), y
  las series largas llegan decimadas con `series_limited: true` en vez de
  desaparecer (M5).

---

## 8. Estado de entrega

- Rama `feat/v0.7.0-audit-viz` con cinco commits sobre `master`.
- Suite de stubs: 204 tests OK. Suite de HA real: 17 passed.
- **No se ha hecho push** (lo hace el orquestador).
- El dashboard **no se ha desplegado** en la instancia de HA: eso lo hace el
  orquestador.
