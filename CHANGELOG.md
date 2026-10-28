# Changelog

All notable changes to this project are documented here.
Releases before v0.5.0 are described in the [GitHub releases](https://github.com/pisolutions-es/ha-aeronet/releases).

## [0.7.0] - 2026-10-28

Audit of the whole integration (read-only review) plus the first-class
visualization deliverable. Entity ids, unique_ids and the published state
format are unchanged; no migration is needed and `requirements` stays
empty.

### Added

- **`dashboards/aeronet.yaml`**: a ready-to-use Lovelace dashboard for the
  example station Valladolid — header with live values, station picker and
  metadata, two native `statistics-graph` cards (7-day hourly statistics of
  the main AOD and of every wavelength channel), two native `history-graph`
  cards (24 h) and two optional `custom:apexcharts-card` cards for the
  AOD(λ) spectrum and the 24 h intraday series. Every card is commented
  with the attribute that feeds it, how to substitute the station and what
  to delete without HACS.
- **`spectrum` attribute** on the main `aod` (and `ssa`) sensor: the
  wavelength-ordered, numeric `[[nm, value], ...]` form of the spectrum, so
  a chart does not have to parse `channels_latest` labels.
- **`angstrom_440_870` attribute**: the Ångström exponent α(440–870 nm)
  derived from the two channels (`-ln(τ₄₄₀/τ₈₇₀)/ln(440/870)`), `null`
  when either channel is missing or non-positive. Documented as a derived
  quantity, not a NASA product.
- **`tests_ha/`**: a pytest-homeassistant-custom-component suite (17 tests)
  running the integration inside real Home Assistant 2026.10.4 — setup,
  statistics eligibility, channel entities, select options, unload, stable
  entity ids, both flows and the shipped dashboard.
- **README "Visualización" section** and updated test counts.

### Changed

- **Series attributes are decimated, not dropped (M5).** The largest raw
  series is halved repeatedly (down to 32 points) until the payload fits
  the 14 KiB budget, so a dense station still renders a curve;
  `series_limited: true` marks any trim. Compact aggregates are untouched.
- **Concurrent product fetches (L2)**: all enabled products are requested
  in parallel instead of one after another.
- **Cached option list and 24 h mean (L4)**: the station dropdown and the
  `aod_24h` window are computed once per payload instead of on every state
  write.
- **`entry.runtime_data`** is populated alongside `hass.data` (L3).

### Fixed

- **SDA was never fetched when AOD was enabled (C1).** SDA used to be a
  fallback used only when the AOD request failed, so enabling AOD+SDA left
  `sda_fine`/`sda_coarse` empty forever. Every enabled product is now
  fetched on every poll.
- **All-`-999` preferred column emptied the main sensor (C2).** When a
  station reports `AOD_500nm` as `-999` on every row while another
  wavelength carries data, the first populated candidate is promoted and
  marked as the family's main channel (no duplicate channel entity).
- **Missing English translation for the repair issue (H1)**:
  `translations/en.json` lacked `issues.api_failing`, so English users saw
  the raw translation key. A parity test now guards `strings.json`
  against both translation files.
- **Options snapshot never refreshed (H2).** After `configure()`, the
  stored snapshot kept the old values, so every later options save
  re-applied the same change and triggered a full multi-product refresh.
- **`latest_value(hours=...)` was a no-op (H3).** The window anchored on the
  newest point, which every point trivially satisfies; a months-old daily
  row was served as a current value. It anchors on `now` and returns
  unknown for a stale series.
- **"Today" and "last 24 h" were anchored on the newest point (H4)**, so
  they could describe a different day than the user's. Both are anchored
  on UTC `now`.
- **Station switch left the device registry and duplicate check stale
  (H5)**: the Device Registry entry is now renamed on switch and the
  config flow also compares the stored station, not only the unique_id.
- **HTTP retries held the connection open and retried permanent errors
  (M1)**: the 429/backoff sleep is scheduled outside the response context,
  4xx (except 408) fails fast, and response bodies are capped at 8 MiB.
- **Widened window was forgotten and partial failures dropped data (M2)**:
  the daily-average fetch now follows the widened window, and a failed
  product keeps its previous series instead of going unavailable.
- **Coordinator lifecycle (M3)**: the coordinator receives its
  `config_entry`, `async_shutdown()` runs on unload (its timer no longer
  keeps polling NASA), and the station-switch task is cancelled when the
  select entity is removed.
- **Options dropdown showed raw URLs (M4)**: it now lists the
  human-readable source labels while storing the URL values.
- **`suggested_display_precision` added and lat/lon device class removed
  (L1)**: latitude/longitude no longer claim `device_class: distance` with
  a `"°"` unit, which HA rejects for that class.

### Internal

- Test hygiene: the global coordinator-class swap in `test_lifecycle.py`
  is restored after each test (M6), and the client tests rebind their own
  aiohttp stub so retry semantics are not masked by another module's
  permissive stub.
- New `tests/test_audit_v070.py` (16 tests) covering the findings that had
  no behavioural test.
- `pytest.ini` pins `testpaths = tests_ha` so the stub suite is never
  collected into the real-HA run.
- Test counts: 184 → 204 (stub suite) + 17 (real-HA suite).

## [0.6.0] - 2026-10-02

Second pass over the 2026-10-02 critical review (M3–M5 and the MINOR
findings; C1/M1/M2 were fixed in v0.5.1).

### Fixed

- **`aod_24h` no longer silently reports stale data (M4).** When no points
  fall inside the last 24 h (campaign or monthly-reporting stations), the
  mean used to fall back to "the last calendar day with data" — possibly
  weeks old — without saying so. The mean is still the best available
  estimate, but the sensor now always carries a `window` attribute:
  `last_24h` (fresh), `last_day_with_data` + `window_date` (stale), or
  `no_data`. Automations that assume recency can key on `window`.
- **Device name followed a stale station (m4).** The device advertised
  `AERONET · <station>` frozen at entity creation; a select-driven
  station switch (which does not reload the entry) kept the old name in
  the device registry until the next restart. The device name is now
  computed from the entry's stored station, which the switch updates.
- **Select dropdown could show the same station twice (m4).** When a
  station appears under coordinate-suffixed labels (duplicate station
  names), the plain current name was appended next to them; the current
  station is now mapped through the same dedupe logic first.
- **Config-flow unique_id was case-sensitive (m6).** `aeronet_Madrid` and
  `aeronet_MADRID` could be created as separate entries and would poll
  the identical station in parallel, while AERONET matching is
  case/underscore-insensitive. New entries get a canonical unique_id
  (`aeronet_<canonical site>`), and a case-insensitive duplicate check
  blocks legacy-cased duplicates at flow time. **No migration needed:**
  existing entries keep their unique_id (the duplicate check compares
  canonically), so no stored data changes in this release.
- **Deprecated OptionsFlow pattern (m7).** The options flow now extends
  `OptionsFlowWithConfigEntry` (HA 2024.11+) instead of overriding the
  deprecated `OptionsFlow.__init__(config_entry)`; the deprecation
  warning on current HA is gone.
- **README documented attributes and behavior the code does not have
  (M3).** The VOL sensor lists its real attributes (`column`,
  `daily_mean`) instead of the nonexistent `vol_fine`/`vol_coarse`/
  `effective_radius`; the 14 KiB series budget is documented as applying
  to the main sensors too (since v0.5.0); the false "products use
  different update intervals" claim is corrected (one shared coordinator
  and interval; only endpoints differ); AVG=20 rows are stamped 12:00
  UTC, not "solar noon".

### Changed

- **User-Agent no longer drifts or misattributes (m1).** The version is
  read from `manifest.json` at import (it was hardcoded `0.4` while the
  integration shipped 0.5.x) and the repository URL points at
  `pisolutions-es/ha-aeronet` instead of `home-assistant/core`.
- **No more `try/except ImportError` flat-import fallbacks (m2).** All
  integration modules import their siblings as a package; the duplicate
  fallback blocks silently masked packaging breakage. Tests import the
  integration as a package through a single shared HA stub module.

### Added

- **manifest metadata (m9).** `issue_tracker` (links HA repair issues)
  and a real `codeowners` entry.

### Tests

- **No test asserts on source text anymore (M5).** The remaining
  source-grep and counter-poke tests were replaced with behavior tests:
  real setup/unload lifecycle (v0.5.1), repair issues asserted through a
  recording issue registry (translated `api_failing` issue created after
  3 failed polls, deleted on success, nothing below threshold), entity
  state/device-info behavior, options-flow save semantics and
  config-flow unique-id/duplicate behavior. The dead
  `reset_site_list_state` hasattr trick is gone. Suite: 184 tests.

### Not addressed (documented decisions)

- **m8** (sync CSV parsing on the event loop): payloads today are
  ms-scale; `async_add_executor_job` only pays off for the site-list
  path and is left for a dedicated change.
- **m10** (internal working docs and one-off scripts in the repo):
  repo-layout/HACS packaging decision, out of scope for a fix pass.
- **m5** (unload KeyError) was already fixed in v0.5.1; this release
  only adds the behavior test that locks it.

## [0.5.1] - 2026-10-02

### Fixed

- **Setup retries no longer leak "ghost" coordinators (critical).** When
  the first poll after a (re)start failed, every HA setup retry used to
  construct a new data coordinator without shutting the previous one
  down — and `DataUpdateCoordinator` reschedules itself in all paths, so
  each failed attempt left a permanently polling ghost that duplicated
  every request against NASA with zero listeners, unbounded over a long
  outage. Setup is now ordered per HA's documentation (first refresh
  BEFORE forwarding platforms) and a failed first refresh shuts its
  coordinator down and releases the shared site-list hold before
  re-raising, leaving no timers behind. The site-list refcount is also
  idempotent per entry (repeated retries no longer inflate it past 1),
  and releasing a shared coordinator now actually runs HA's coroutine
  `async_shutdown()` (the old call-and-discard left the weekly poll
  timer armed).
- **Options flow: a first save no longer freezes the channel set.** The
  dialog used to prefill every channel detected in the current payload
  for entries without an explicit selection; saving untouched then
  silently changed "absent = all channels" into "the set I saw that
  day" (new wavelengths never appeared) and triggered a full entry
  reload + fetch burst, breaking the "save without changes does not
  refetch" guarantee. The dialog now preselects an explicit "All
  channels (default)" sentinel that normalizes back to an absent
  selection on save; explicit selections are unchanged.
- **Station switch no longer blocks for minutes.** The
  `select.select_option` service call awaited a full multi-product fetch
  (worst case ~13 minutes with timeouts, backoff and Retry-After
  waits). The re-poll now runs in the background; the switch is
  persisted immediately and a rapid re-selection cancels the previous
  in-flight fetch instead of stacking duplicate bursts.

## [0.5.0] - 2026-09-18

### Fixed

- **Email as query param broke every poll.** The optional *Email* config
  field was sent as an `email` query parameter on every AERONET request.
  The version-3 web service rejects any request carrying an `email`
  parameter with its HTML help page ("Error: Not enough parameters"), so
  users who filled the field saw every poll fail with
  `AeronetParamError`. Contact info now travels in a sanitized
  `User-Agent` header instead (NASA's own recommendation); no `email`
  parameter is ever appended again. Config storage and flows are
  unchanged. Verified live: the same request returns 924 Madrid points.
- **Email no longer leaks into logs.** Request URLs embed the configured
  email; HA debug logs routinely end up in public issue reports. Debug
  logs and retry-error strings now pass through a query-param sanitizer.
- **Recorder attribute budget on the main sensors.** v0.4.0 capped the
  *channel* sensors at ~14 KiB but the main `aod`/`ssa`/`sda` sensors
  still shipped `today_series` + `recent_points_24h` +
  `*_series_24h` unbounded. A dense station (1-min cadence, widened
  window) serializes >100 KiB and the recorder silently refuses the
  whole state: the sensor looks fine in the UI but has no history.
  `apply_series_budget` now trims `recent_points_24h`, then
  `today_series`, then product `*_series_24h` until the payload fits,
  flagging `series_limited: true`.
- **Coordinator lifecycle discipline.**
  - Shared site-list coordinators are refcounted and shut down when the
    last config entry using them unloads (the module-level dict used to
    keep poll timers alive forever); a shut-down coordinator is never
    handed back.
  - Setup uses `async_config_entry_first_refresh`, so a failed first
    poll raises `ConfigEntryNotReady` and HA retries instead of leaving
    entities unavailable for a full interval.
  - The update listener compares against the setup snapshot: saving the
    options dialog unchanged no longer triggers a fetch burst, and a
    station-only change no longer doubles the NASA request burst per
    switch.

### Added

- **Repair issues for consecutive API failures.** After 3 consecutive
  coordinator failures the integration raises a translated repair issue
  in the HA UI naming the station and the last error; it clears
  automatically when the next poll succeeds.

### Tests

- `Retry-After` edge cases asserted against the real contract: numeric
  values clamp to `[1, RETRY_AFTER_MAX]` (300 s — not the backoff), and
  HTTP-date/garbage headers fall back to `RETRY_BACKOFF * 2` plus
  uniform jitter (~10–11 s).
- New parser coverage: a station whose every `AOD_*nm` column is `-999`
  detects zero channels with `channel_families=("aod",)`, and
  malformed rows interleaved with valid ones (truncated rows, bad
  dates, empty site cell, non-numeric values) are skipped while the
  valid rows survive in order.
- Suite: 140 unit tests green (`python -m unittest discover -s tests`).
