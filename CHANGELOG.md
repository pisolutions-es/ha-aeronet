# Changelog

All notable changes to this project are documented here.
Releases before v0.5.0 are described in the [GitHub releases](https://github.com/pisolutions-es/ha-aeronet/releases).

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
