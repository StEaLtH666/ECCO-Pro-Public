# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses semantic versioning for releases. Component versions
(firmware stage, dashboard version, Intelligence model version) are listed in `VERSION.yaml`.

Development before the first public release happened in a private repository; see
[docs/project-history/README.md](docs/project-history/README.md).

## [Unreleased]

### Added

- Post-export edit layer (PEX, schema `ecco-pex/1`, foundation entry `pex0`). It is the declared, exact and hash-linked way to change
  files that the `pub0` export froze. The `pub0` proof now runs on the files as of `pub0`, byte for byte. Test and proof
  infrastructure only: no firmware, Home Assistant, dashboard or behaviour change. See
  [docs/dev/post-export-edit-layer.md](docs/dev/post-export-edit-layer.md).
- `ecco_core/` (offline only; no firmware change; no new write path): a host-side reference model with five modules.
  - **State:** raw, normalised and derived observations with source and observation time.
  - **Freshness:** one catalogue of the freshness limits the project already uses, per signal and purpose, each checked
    against its source; limits nobody defined stay unresolved.
  - **Capability:** device capabilities derived only from the capability registry, with unsupported and unknown failing
    closed, plus proof per controller variant.
  - **Authority:** the controller's write authority as one table, checked against the firmware write surface, the
    registry's `read_write` records and the transaction model; plus a pure reference decision model that never
    authorises advisory code.
  - **Bridge:** the single bridge to Intelligence.
- Intelligence V1.1 foundation (shadow, synthetic tests, not yet consumed):
  - the `Advice` explanation format;
  - overnight demand learning with a return-from-away regime check;
  - charge-target advice;
  - Saving Session / export-event advice;
  - reserve-aware Dump-to-Grid stop-level advice.
- New offline test root `ecco_core/tests`.
- Public fallback design basis and stage status,
  [docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md](docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md): the supervision
  model, the durable fallback profile, the Review / Save / Invalidate boundary, Live Match, the zero-authority shadow evaluator
  and its display, the RTC / poll liveness work, what is and is not authoritative, the status of every stage (implemented,
  deployed, live-proven or partially live-proven) and the evidence still owed before operator Restore (FB-E) or automatic
  failback (FB-F), neither of which is implemented. Records and documentation only, declared as post-export entry `fbrp1`:
  no firmware, Home Assistant package, dashboard, frontend or behaviour change.
- **RTC correction-failure health alert** (FB-D1 follow-up; offline only, not live-proven). The `ECCO Health RTC` sensor
  now represents the check `rtc_correction_failures_recent` using the existing firmware sensor "Failed Corrections Since
  Boot". The 90 s RTC deadline breaker increments that same counter.
  - **What triggers it:** an observed increase of the counter.
  - **What it reports:** WARNING with `RTC_CORRECTION_FAILURES_RECENT` for 1800 s. Each further increase restarts the
    window.
  - **What never triggers it:** a reboot reset, the first value after a Home Assistant restart, and an attribute-only
    update.
  - **An unreadable counter** reports UNKNOWN, never HEALTHY.
  - **New attributes:** the failure time, the correction result text at that moment, and the RTC lock max age.
  - **Unchanged:** every other RTC health check and its presentation.
  - **Scope:** Home Assistant health package, check registry and documentation only, declared as post-export entry
    `rtcf1`. No firmware, dashboard, frontend or Modbus change.

- **ECCO Weather & Solar card** (`frontend/ecco-weather-solar-card`, read-only): current weather, the hourly and five-day Met.no
  forecast, sun times, the ECCO blended solar forecast (today, remaining today, tomorrow) with its Solcast and Forecast.Solar
  inputs, an hourly chart of Solcast's profile against actual PV with cloud cover and rain, forecast freshness, the existing
  accuracy scorecard and explanatory notes. It sends only two read-only websocket messages (the forecast subscription and hourly
  statistics); no service call, no new data provider, the blend weighting unchanged. It has its own dashboard view right after
  Overview, declared as post-export entry `wsc1`.

### Changed

- **Dump-to-Grid command ceiling is configurable at build time.** `ecco_dump_controller_max_ceiling_w` stays the single
  source of truth and keeps its 3000 W default, the only hardware-tested value. A build may select up to 8000 W; values that
  are not a decimal multiple of 100 W, not above the 500 W floor, or above the site TOU ceiling or 8000 W are refused at
  compile time. Above 3000 W everything is **offline only**: 6000 W is the first staged live checkpoint, and 7000-8000 W is
  an architectural capability, not hardware proven. A diagnostic sensor reports the configured value. See
  [docs/dev/dump-to-grid-ceiling.md](docs/dev/dump-to-grid-ceiling.md).
- **The absolute runaway backstop follows the current command above 3000 W.** It was `configured ceiling + 750 W`. It is
  unchanged for any ceiling up to 3000 W, and never looser above it.
- **The W2 fallback-capture warning ("resembles Dump to Grid residue") follows the configured ceiling** instead of a fixed
  3000 W. The W2 wording of the recovery card and of the dashboard's Safety view no longer names a wattage; the dashboard
  line is a declared post-export (PEX) edit of the export-frozen file.

The transaction, ownership, stop and restore model and the Modbus write surface are unchanged.

- `intelligence.replay.inputs_from_history` now builds its inputs through an `ecco_core` snapshot. The result is
  identical for every finite input, and byte-identical engine reports are tested. A reading that is not a finite number
  is now dropped at the snapshot boundary.

### Security

- **The Energy Actions card builds with esbuild 0.28.1** (was 0.21.5; advisory GHSA-67mh-4wv8-2f99, an esbuild development-server
  issue fixed in 0.25.0). The card's build never starts that server, so the advisory was not reachable; the upgrade is
  maintenance. The rebuilt bundle's executable code is byte-identical; only its trailing Lit licence block is regrouped, with the
  same notices. Declared as post-export entry `esb1`, which enrols the card's `package.json`, `package-lock.json` and bundle in
  the PEX frozen set (owner decision O3, amended); the historical card-folder and licence pins keep their values. Every tracked
  card now resolves esbuild 0.28.1. No firmware, Home Assistant, dashboard or Modbus change.

### Fixed (documentation)

- `docs/dev/register-provenance.md` swapped the evidence status of two registry records.
- `docs/INVERTER_CAPABILITY_REGISTRY.md` had an out-of-date record count, a statement that no W3 record is writable
  (register 244's policy record is), and an incomplete list of writing scripts.
- Stale fallback status in `VERSION.yaml` (the 7.18.0 dashboard comment), `README.md`, `SUPPORTED_HARDWARE.md` and
  `ARCHITECTURE.md`: the FB-C3 shadow-check display was described as offline only. It is deployed on the reference
  installation and its everyday display path was checked live; its supervision-loss (Shadow Recovery) path is not yet
  live-proven, so `tested_in_home_assistant` stays `false` for dashboard 7.18.0. The RTC policy row now records the FB-D1
  deployment and that its 7-day continuous run is still pending.

## [0.9.0] - first public pre-release

Experimental. One reference installation; per-feature evidence levels are in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md).

### Included

- ESPHome firmware `stage3.4` for a classic ESP32 dongle and an ESP32-S3 (N16R8) hardware wrapper, with the guarded write
  transactions (RTC correction, manual six-slot TOU, Free Power, register 244 export mode, Dump-to-Grid), durable recovery
  records, the fallback profile (save / invalidate / compare) and the supervision heartbeat.
- Home Assistant packages, dashboard 7.18.0 and three custom cards; optional InfluxDB Battery Outlook.
- Intelligence V1: shadow-only advisory engine with a configurable battery reserve (default 40 %) and a site-specific
  technical minimum; synthetic examples only; no write path.
- Offline test suites, the proof chain, the declared public-export transition `pub0`, the declared licence-alignment
  transition `lic0`, the site renderer (`tools/ecco_site_render.py`), the public privacy scan and a simple validation
  workflow with every action pinned to a commit SHA.
- Licence: GPL-3.0-or-later for the whole project, including the three custom cards; Lit's BSD-3-Clause notices ship inside
  the two prebuilt card bundles. Contributions need a Developer Certificate of Origin sign-off; no CLA.

### Known limitations (not in 0.9.0)

- Dump-to-Grid does not use the configured battery reserve: its firmware enforces only its own stop-level bounds. Reserve
  enforcement for Dump-to-Grid is deferred until it can be hardware-proven.
- Fallback restore and automatic failback are not implemented.
- No automatic optimiser control exists; Intelligence is advisory and shadow-only.
- Exact inverter model and firmware strings of the reference installation are not published (not recorded in the evidence).

### Planned after 0.9.0

- Run the card tests (`npm test`, typecheck, build reproducibility) in CI; automated action-pin updates.
- A step-by-step installation guide and concise public specifications (Dump-to-Grid first).
- Moving the InfluxDB tasks' fixed timezone into the installation profile.

