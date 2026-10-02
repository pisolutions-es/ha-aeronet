# Changelog

All notable changes to this project are documented here.
Releases before v0.5.0 are described in the [GitHub releases](https://github.com/pisolutions-es/ha-aeronet/releases).

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
