# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project uses semantic versioning for releases. Component versions
(firmware stage, dashboard version, Intelligence model version) are listed in `VERSION.yaml`.

Development before the first public release happened in a private repository; see
[docs/project-history/README.md](docs/project-history/README.md).

## [Unreleased]

### Added

- Advanced Configuration Stage 0 (post-export entry `acs0`; offline, NOT live-proven): a guarded owner edit of ONE TOU slot's
  target SOC (register 267+N) through the existing, verified manual TOU firmware path (no firmware change, no new register).
  Review (writes nothing) -> typed confirmation with a one-time review code -> Apply: a fresh configuration read, a Load, the
  Manual Controls helper sync at a fixed point, only the SOC staged, every other staged value proven equal to the live slot,
  one Apply; success only on the firmware's VERIFIED OK plus two later configuration reads (strictly later update times) of
  every written register. The lower
  bound is the greater of the inverter shutdown SOC and the ECCO reserve, read fresh. Refused, fail-closed, in every unsafe
  state (Free Power, Dump to Grid, register 244, recovery, fallback arm / Review / Save, supervision, failback shadow, leases,
  schedules). Any uncertain outcome stops, disarms, alerts and locks further edits until acknowledged; never retried. A run interrupted
  by a restart or reload is caught by a watchdog that locks and alerts at once. The fallback gate parses the live match and the
  Review state exactly (a fresh, trusted, compared verdict; exactly one IDLE Review), so unknown, stale, malformed or incompatible
  fallback state refuses. The owner-approved reserved-token amendment authorises exactly six fallback / failback ids, read only,
  in exactly the editor's three files; five exact allowlist checks are amended (three frozen suites by PEX), nothing else is
  widened. See
  [docs/dev/advanced-config/stage0-safety-case.md](docs/dev/advanced-config/stage0-safety-case.md), the S3 evidence record
  and the supervised live-proof procedure (not executed).
- **Dump to Grid safety hardening, phase 2** (post-export entry `fcp2`; firmware, not yet flashed anywhere;
  [docs/dev/dump-to-grid-safety-fcp2.md](docs/dev/dump-to-grid-safety-fcp2.md)).
  - The closed-loop controller never writes once a lease is ending. An End or restore request that arrives while it is checking
    the inverter before a write now cancels that write (SG-40).
  - The battery runaway guard also judges a window of the last 8 samples. An overshoot that alternates above and below the
    threshold now ends the lease, a skipped or NaN reading no longer resets it, and the decision cannot be missed between two
    watchdog ticks.
  - Above 3000 W the absolute backstop allows for the battery's normal DC conversion loss (a profile value, 12 % for the
    reference profile), so a healthy high-power lease is not ended by mistake. At 3000 W and below it is unchanged.
  - The Dump restore first reads the inverter. It restores only what ECCO still owns and never overwrites a setting someone else
    changed. In that case it keeps the recovery obligation and asks for Force Restore Original or Accept Current State. A repeat
    after a verified restore no longer rewrites anything.
- **Inverter capability profiles and persisted Dump to Grid operating limits** (post-export entry `fcp1`; firmware, not yet
  flashed anywhere; [docs/dev/inverter-capability-profiles.md](docs/dev/inverter-capability-profiles.md)). One firmware image can
  now serve an inverter's full validated capability, with power levels chosen in Home Assistant instead of by rebuilding.
  - The inverter's Dump capability is a **profile** value (`ecco_dump_capability_w`); there is no global maximum. The reference
    profile is 8 kW, and other profiles are listed in `registry/inverter_profiles.yaml`.
  - New run-time settings, stored and enforced **on the dongle**, so Home Assistant being unavailable never lifts them:
    - **Dump to Grid Power Ceiling** (factory 3000 W);
    - **Dump to Grid Max Grid Export** (factory: not configured, so every Dump START is refused until it is set).
    Raising either needs the new **Dump Power Limits Write Enable** arm and Dump idle; lowering works at any time.
  - Each lease locks its ceiling at START. A later raise never reaches a running lease, and a reduction lowers it at once.
  - An export guard ends a lease whose measured net grid export exceeds the configured limit.
  - Settings that are corrupt, out of range or stored for another profile are refused, never replaced by a larger value.
  - No new Modbus operation or inverter write domain (register 245 is never written).
  - The durable records keep their schemas: the previous firmware can still be flashed back.

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

- **Failed-start health warning** (FB-D1 follow-up; offline only, not live-proven). A Free Power or Dump to Grid start that
  fails before it writes anything leaves the recovery state at `NONE`, so the Overview could still say SYSTEMS NOMINAL. The new
  sensor `ECCO Health Start Failures` detects it from four existing firmware counters: the Free Power and Dump to Grid start
  attempts and start successes.
  - **What counts:** a rise of unresolved attempts (attempts minus successes) that is still there after the counters were
    quiet for 240 s. The firmware counts an attempt only after every start gate has passed, so a refusal is never counted.
    240 s outlasts a start in flight (success seen within 57 s) plus a silent Wi-Fi loss (the ESPHome client drops the link
    within 110 s). This timing assumption must be re-checked against the live Home Assistant version before deployment.
    The failures-since-boot counters are not used, because they also count failed restores.
  - **What never counts:** a nonzero count, the first values after a Home Assistant start or a reconnection, a counter
    reset, an inconsistent pair, and the free-text status. These only set the baseline.
  - **What it reports:** WARNING with `FREE_POWER_START_FAILED` and/or `DUMP_TO_GRID_START_FAILED` for 1800 s after the
    failed attempt. Each further failure restarts that feature's window; the two features are independent. Unreadable
    counters report UNKNOWN, never HEALTHY.
  - **Registry:** two checks and two reason codes (Dump to Grid sits in `manual_write_system`, because the registry has no
    dump subsystem).
  - **Overview:** the status hero reads the sensor's `reason_codes` and shows ATTENTION with its own subline and a START
    FAILED pill. Every existing reason keeps its subline and priority, and STATUS PARTIAL still comes first.
  - **Scope:** Home Assistant health package, check and reason-code registries, documentation and the dashboard hero,
    declared as post-export entry `fsw1`. No firmware, frontend or Modbus change.
  - **Compatibility:** the scheduled Free Power (fps1) and scheduled Dump to Grid (dgs1) packages retry only gate refusals, which
    are never counted, so their retries and their own failure alerts coexist with this warning (the suite drives both real
    packages against their dongle models). Firmware gate refusals never increment these counters, so this warning does not report
    them; neither scheduler package is changed here. `docs/FAILED_START_HEALTH.md` records the detection matrix, the timing
    contract, deployment, rollback and the passive live acceptance criteria.

- **ECCO Weather & Solar card** (`frontend/ecco-weather-solar-card`, read-only): current weather, the hourly and five-day Met.no
  forecast, sun times, the ECCO blended solar forecast (today, remaining today, tomorrow) with its Solcast and Forecast.Solar
  inputs, an hourly chart of Solcast's profile against actual PV with cloud cover and rain, forecast freshness, the existing
  accuracy scorecard and explanatory notes. It sends only two read-only websocket messages (the forecast subscription and hourly
  statistics); no service call, no new data provider, the blend weighting unchanged. It has its own dashboard view right after
  Overview, declared as post-export entry `wsc1`.

- **The Advanced / Experimental Configuration card is on the dashboard** (dashboard 7.19.0, staged; 7.19.0 also carries the
  Weather & Solar view). It is section 13 of the Inverter / Advanced view: the read-only catalogue of every capability-registry
  record, with live values, evidence and lock reasons, and the Global Power / Export Limit (register 245) panel. The deployment
  manifest lists its bundle (manual copy and resource registration, like the other cards). Declared as post-export entry `acfg1`;
  two older suites' "exactly two frontend assets" pins now read the export-era manifest, with their values unchanged. The card
  cannot write: no Home Assistant service, no Modbus, no firmware change.

- **Battery time to reserve (FE-1, STAGED / NOT LIVE-PROVEN).** A read-only Home Assistant package,
  `home-assistant/packages/ecco_battery_runtime.yaml`, estimates how long the batteries can keep discharging at recent usage
  before they reach the configured reserve (`input_number.ecco_minimum_reserve_soc`, whatever it is set to).
  - **Method:** one battery-power sample a minute while telemetry is fresh. Freshness comes from the dongle's per-poll
    timestamp, which must actually change, because ESPHome does not re-send an unchanged reading.
  - **Usage:** the winsorized mean of the last 30 minutes. Up to 4 one-minute samples of a load (a kettle) are clipped,
    while a load present in 5 or more minutes of the half hour (an oven or hob switching) counts in full.
  - **Direction:** a sustained 8-minute run decides at once; otherwise the usage decides, with hysteresis.
  - **Discharge:** the usage, raised to a sustained run's level, plus a 3-hour allowance for the energy the clipping removes
    (learned only while discharging). The method and its measured error in both directions (short for long on-phases, long for
    a new or a rarely recurring load) are in the documentation.
  - **Capacity:** the configured capacity until the energy per SOC percent has been measured over 15 points of real discharge.
    Measuring restarts on a capacity change or on two agreeing measurements more than 20 % off.
  - **States:** explicit stale, insufficient-data, charging, holding and at-reserve states.
  - **Display:** the Energy Flow card's battery node shows it through its FE-0 hook (`nodes.battery.time_to_reserve`) as one small
    static line such as "≈5h 20m to reserve", with the likely range and "an estimate, not a guarantee" in the tooltip. The
    Overview's battery estimate card adds the summary. Dashboard 7.21.0 is staged.
  - **Safety:** display only. The package has no service call, script, automation or action. No firmware, registry or Modbus
    change.
  - **Bookkeeping:** declared as post-export entry `fe1`. See [docs/BATTERY_TIME_TO_RESERVE.md](docs/BATTERY_TIME_TO_RESERVE.md)
    for the method and its limitations.

### Changed

- **Overview V2.1 polish and accuracy pass** (dashboard 7.21.1, staged; display only; re-chained after FE-1 and FPS1, keeping FE-1's time to reserve). ECCO Today and Smart Charge Strategy now
  count only the solar that can arrive before their target time (between 00:00 and the 00:30 target the projected SOC had been
  overstated by about 25 points, because the forecast is for the rest of the current day), say which day the target is, and show
  "Battery data unavailable" or "Projection unavailable" instead of NaN or an unsupported number. The Overview's Battery estimate
  becomes Battery outlook (the learned load-only outlook and how accurate it was), with new Today so far and Coming up cards and
  scheduled-session counters built from existing sensors to fill the empty space beside Energy Actions. The dead SOC Model chart
  series (it read an undefined variable, the source of the browser's "states is not defined" warning) is removed, and a data-status
  strip on the Power Flow charts tells a new day from a sensor that is not reporting. The 7-day outlook score reads the entity ids
  that exist, and the static "Suggested 15%" / "15% starting point" texts show the live ECCO reserve setting. Text that was cut off
  (Grid Status unit, Current Plan countdown, Electrical detail on a phone) now wraps. At four columns Coming up fills the right-hand
  column beside the Energy Flow; on narrower pages an identical copy sits under Electrical detail instead (a Home Assistant screen
  condition at 1696 px: the 1440 px of content at which the sections view switches to four columns, plus the 256 px sidebar), so the
  right-hand column does not become taller than the section beside it. No control path,
  firmware, package or automation changed; declared as post-export entry `ovw2`.
- **The Overview is rebuilt** (dashboard 7.20.0, staged) as nine sections: a compact status banner that keeps the hero's state
  machine, pills and vocabulary and now also reads the Dump to Grid lease states and both recovery-state sensors (a recovery
  condition raises ATTENTION even when no lease flag is set); the Weather & Solar card's new solar strip and compact daily layouts;
  the Energy Flow card, its configuration unchanged, beside a slim Grid Status / Current Plan / Tariff column; the Energy Actions card in
  its new presentation-only `layout: tabbed` (one track visible at a time, both tracks' states always classified, a cross-track
  alert for the hidden one) followed directly by the Known-Good Profile bar; decision support from existing entities; the Power
  Flow chart beside an electrical detail list in place of the four gauges; and one merged System Health card. Display only: no
  control path, firmware, package, automation or service call changed. Declared as post-export entry `ovw1`, which enrols the
  Energy Actions card's source and config in the PEX frozen set (owner decision O3, amended 2026-10-09); the historical
  card-folder and licence pins keep their values and skip the two files the entry adds. **Deployment prerequisite:** the Overview
  now uses the Weather & Solar card, which stays a manual Lovelace resource (it is not in the deployment manifest); register its
  bundle and redeploy the rebuilt Energy Actions bundle before the 7.20.0 dashboard, or the two Overview cards show as missing.
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
- **The first-run value of the battery reserve helper is 40 %, not 15 %.** `input_number.ecco_minimum_reserve_soc` is still the
  user's own setting (0-80 %, changeable in Home Assistant at any time) and Home Assistant restores it across restarts and
  updates. Only the one-time defaults automation changed, and it runs once, so an installation that has already been initialised
  keeps its value. 40 % is a starting value, not a limit, and no runtime decision hard-codes it. Declared as post-export entry
  `rsv1` (one line of the export-frozen core package) and pinned by `home-assistant/tests/test_ecco_reserve_default.py`.
  Nothing else changes: no firmware, Dump-to-Grid, Free Power, Intelligence or dashboard change.

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

### Fixed

- Scheduled Free Power now starts reliably and reports every failure (post-export entry `fps1`; incident record
  [docs/incidents/2026-10-11-scheduled-free-power-start.md](docs/incidents/2026-10-11-scheduled-free-power-start.md)). On
  11 Oct 2026 the 11:00 session never started. The firmware start gate correctly refused both presses because a routine telemetry
  read was on the Modbus bus, and the package's fixed timing (+2 s, one retry at +35 s) was locked to the 10 s poll. Nothing was
  written and nobody was told. Home Assistant scheduling layer only:
  - bounded, unevenly spaced retries of a transient start-gate refusal (no side effects), each answer proven to belong to its
    press, never a retry once a start transaction began or when the outcome is unconfirmed, success only on Free Power Active;
  - a cancel (or cancel and re-arm) stops the run before the next press; the limit is checked on every attempt; nothing is
    staged into another transaction;
  - each run retries for at most 10 min and never in the window's last 30 s; a late start is shortened to end with the window;
  - a readiness check 5 min before, a missed-trigger watchdog 3 min after, and a persistent notification for every failure or
    missed start;
  - schedule status STARTING / FAILED / COMPLETED in addition to ACTIVE / ARMED / IDLE.
  No firmware, dashboard or Modbus change.
- Scheduled Dump to Grid gets the same start reliability and failure reporting (post-export entry `dgs1`; review record
  [docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md](docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md)).
  No scheduled Dump to Grid start has failed so far, but its start gate has the same bus-busy refusal and the package used the same
  locked +2 s / +35 s timing (in the offline model it fails to start at about 9 % of poll phases). The old retry also pressed
  again after a start transaction had begun, could leave the write enable on when the firmware dropped a press, stopped for good
  if the dongle read offline at the start instant, and alerted nobody. The fix is in the Home Assistant scheduling layer only and
  mirrors `fps1`:
  - bounded, unevenly spaced retries of a transient start-gate refusal only, each answer proven to belong to its press;
  - never a retry once a start transaction began or when the outcome is unconfirmed;
  - all three staged values (export power, Stop SOC, duration) confirmed before every press; nothing staged into another
    transaction;
  - a start deadline and a duration clamp inside the authorised window;
  - a readiness check (including a battery already at the Stop SOC), a missed-trigger watchdog, restart recovery, persistent
    notifications, and STARTING / FAILED / COMPLETED status.
  No firmware, dashboard or Modbus change.

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

