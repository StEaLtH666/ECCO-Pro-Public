# ECCO system health architecture

Status: **DESIGNED, with an IMPLEMENTED OFFLINE pure-Python reference
engine, a machine-readable check registry, Phase 1 Home Assistant health
LIVE-PROVEN on 2026-09-18, Phase 2 firmware diagnostics LIVE-PROVEN on
2026-09-18, and Phase 3 registration/idle plus normal RTC, manual-write, and
Free-Power transaction cycles LIVE-PROVEN on 2026-09-19.** The full 43-check
architecture is not yet implemented in Home Assistant. The Phase 1 package deliberately exposes only
three non-authoritative entities and never creates the final manual-control
readiness gate. Live proof confirmed the two subsystem sensors and the partial
readiness reference instantiate correctly. The communications timestamp
entities were also live-discovered as
`sensor.ecco_clock_dongle_last_telemetry_update` and
`sensor.ecco_clock_dongle_last_configuration_update`; the initial
`unknown` attributes were caused by using the wrong `text_sensor` domain.
After correction and restart, the communications health entity remained
`HEALTHY` and exposed live timestamp values for both attributes. This document remains the format/behaviour specification;
`docs/SYSTEM_HEALTH_HA_DESIGN.md` covers the staged HA surface and live
validation path, `docs/SYSTEM_HEALTH_DASHBOARD_DESIGN.md` covers the eventual
UI, and `docs/SYSTEM_HEALTH_REASON_CODES.md` is the reason-code catalog.

## Phase 2 live-discovery and proof

The 2026-09-18 live HA audit confirmed five required control-health states were
internal ESPHome globals only and had no Home Assistant entity-registry entry:
`manual_write_in_progress`, `correction_in_progress`,
`free_power_operation_in_progress`, `free_power_snapshot_valid`, and
`manual_config_raw_cache_valid`.

Phase 2 exposed those five booleans as read-only template binary sensors. The
candidate was validated in ESPHome Builder, flashed OTA, the dongle reconnected,
and all five exact HA entities were observed live:

- `binary_sensor.ecco_clock_dongle_manual_write_in_progress` = `off`
- `binary_sensor.ecco_clock_dongle_rtc_correction_in_progress` = `off`
- `binary_sensor.ecco_clock_dongle_free_power_operation_in_progress` = `off`
- `binary_sensor.ecco_clock_dongle_free_power_snapshot_valid` = `off`
- `binary_sensor.ecco_clock_dongle_manual_configuration_raw_cache_valid` = `on`

This exposure does not alter any transaction, RTC-correction, Free Power,
polling, or Modbus write path. ESPHome Builder used version `2026.9.0` for the
live OTA build; the repository Stage 3.4 workflow currently pins `2026.8.2`
and should be aligned separately.

## Phase 3 (Task 007) - live-proven idle/registration path 2026-09-19

**Status: LIVE-PROVEN FOR REGISTRATION, IDLE EVALUATION, AND NORMAL
TRANSACTION CYCLES ON 2026-09-19.**
`home-assistant/packages/ecco_system_health.yaml` contains five read-only
template sensors that consume the five Phase 2 firmware diagnostics above plus
`rtc_stall_detected`, `ntp_synced`, `clock_difference`, and the inverter
system-state/warning/fault text sensors. The package passed live
`ha core check`, restart/registration validation, and normal RTC-correction,
manual-write, and Free-Power start/automatic-restore cycle tests. The deliberate
60 s / 180 s stuck thresholds remain unforced and therefore unproven; see
`docs/SYSTEM_HEALTH_HA_DESIGN.md` for the detailed live evidence and
remaining validation gaps.

Checks now represented (exact ids from `registry/system_health_checks.yaml`,
exact reason codes from `registry/health_reason_codes.yaml` - no new
semantics invented):

| Sensor | Subsystem | Checks represented | Checks still unrepresented in this subsystem |
|---|---|---|---|
| `sensor.ecco_health_manual_write_system` | manual_write_system | `manual_write_duration` | `manual_write_failures_recent`, `manual_write_arm_unexpected` |
| `sensor.ecco_health_rtc` | rtc_time | `rtc_correction_duration`, `rtc_stall_detected`, `rtc_ntp_synced` | `rtc_read_freshness`, `rtc_correction_failures_recent`, `rtc_drift_uncorrected` |
| `sensor.ecco_health_free_power` | free_power | `free_power_operation_duration`, `free_power_active_state`, `free_power_snapshot_recovery` | `free_power_failures_recent`, `free_power_state_consistency` |
| `sensor.ecco_health_configuration` | inverter_configuration | `config_cache_valid` | `configuration_freshness`, `configuration_failures_recent` |
| `sensor.ecco_health_inverter_telemetry` | inverter_telemetry | `inverter_alarm_fault`, `inverter_grid_connected` | `telemetry_freshness`, `telemetry_failures_recent` |

Every excluded check needs one of two things this phase deliberately does
not build: a persisted failure-counter baseline surviving Home Assistant
restarts (`manual_write_failures_recent`, `configuration_failures_recent`,
`rtc_correction_failures_recent`, `free_power_failures_recent`,
`telemetry_failures_recent` - see section 6 and the live-validation
checklist item 3, still unverified), or a live HA entity this task's
live-proven entity list does not include
(`rtc_read_freshness`/`rtc_drift_uncorrected` need
`clock_difference_valid`/`correction_threshold`/`cooldown_until_ms`;
`inverter_grid_connected` is now represented using the live-proven
`binary_sensor.ecco_clock_dongle_ecco_grid_connected` entity;
`configuration_freshness`/`telemetry_freshness`'s full two-tier
60s/180s/180s/600s brackets need per-entity age tracking beyond what the
existing Phase 1 `sensor.ecco_health_communications` online/offline
simplification provides).

**Current-operation duration** (`manual_write_duration`,
`rtc_correction_duration`, `free_power_operation_duration`, and the derived
`free_power_snapshot_recovery` condition) is computed from
`states.<entity>.last_changed` via
`as_timestamp(now()) - as_timestamp(states[entity].last_changed)` -
exactly the mechanism this task was asked to investigate, and no
undocumented history/recorder API. The three duration-based trigger-template
blocks also include a once-per-minute `time_pattern` trigger so their
60s/180s thresholds can advance while an input remains continuously ON;
source state changes still trigger immediate evaluation. For `free_power_snapshot_recovery`
(a derived AND-condition over two entities, not one), the "since" timestamp
is approximated as the *more recent* of the two contributing entities'
`last_changed` values - documented as an approximation, not an exact
measurement, in both the package file and here.

**Restart/reconnect limitation - not proven restart-safe.** If Home
Assistant restarts, or the ESPHome device disconnects and reconnects, while
one of these booleans is already `on`, `last_changed` reflects when the
entity's state was *re-established* after that event, not necessarily the
true original start of the underlying firmware transaction. A duration
computed this way can therefore **under-report** how long a transaction has
actually been running across a restart/reconnect. No claim of restart-safe
control-gating semantics is made anywhere in this phase; every new sensor
carries `sufficient_for_control_decision: false` and
`partial_implementation: true`, and none of them is, feeds, or gates
`binary_sensor.ecco_manual_control_ready`, which remains absent.

**Unknown/unavailable handling.** Every new sensor treats a source entity
reporting `unknown`/`unavailable`/empty state as its own `UNKNOWN` state,
never as HEALTHY - mirroring `health/system_health.py`'s `transaction_state`/
`boolean_expected`/`text_state` `is None`-vs-truthiness fix (Task 006B).
Aggregation across a sensor's multiple represented checks reuses the exact
rank/tie-break rule from `evaluate_subsystem()`/`_resolve_flavor_at_rank()`
(section 2/13): the worst severity rank wins, and at a shared rank a real
finding always beats UNKNOWN.

**What still prevents the final fail-closed gate.** Every check listed as
"still unrepresented" above remains a genuine gap, plus: the counter-delta
baseline mechanism (section 6) is still unimplemented and unverified
against live HA `recorder`/`history` behaviour; normal live transaction
cycles are now proven, but the deliberate 60s/180s stuck-duration failure
brackets have not been forced and therefore remain unproven; no overall rollup
(`sensor.ecco_system_health`) or `binary_sensor.ecco_system_attention_required`
exists yet to aggregate across subsystems; and this phase's own duration
calculation is explicitly not proven restart-safe, above. No additional
firmware diagnostics are believed to be required for the checks this phase
represents - the gap is entirely in HA-side mechanism and live
verification, not missing firmware signals.

## Purpose

ECCO's health information is currently scattered across ESPHome
diagnostic sensors, HA availability templates, InfluxDB freshness, and
several ad-hoc "since boot" counters (see `docs/INVERTER_CAPABILITY_REGISTRY.md`
for the underlying Modbus-level signal inventory, produced by Task
005/005A/005B and reused here as a *source*, not a *dependency* - this
task does not require that branch to exist or be merged). This task
designs one coherent, explainable, **read-only** answer to "is ECCO
healthy right now, and if not, exactly what is wrong" - never an
automatic-recovery system.

## Relationship to Task 005

Task 005's capability registry documents *what registers exist and
whether they may be written*. Task 006's health registry documents *is
the signal current, plausible, and consistent with other signals*.
They are complementary but independent: this branch was created fresh
from `upstream/feature/ha-ssh-deployment` and does not import, require,
or reference any file from the Task 005 branch. Where Task 005's design
work (the transaction lifecycle, evidence-level vocabulary) is a useful
*pattern* to reuse, it is cited as prior art, not as a dependency.

## 1. Health-signal audit

Full inventory of existing repository health/diagnostic signals, by
source file. "Entity/id" is the ESPHome C++ id or, for Home
Assistant packages, the `unique_id`. All firmware citations are against
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml` on this branch's
base commit (`5d7d6b4827fa5d94552bc399bcdfe210e24d590c`).

### ESP32 / ESPHome

| Signal | id/entity | Evidence |
|---|---|---|
| Wi-Fi RSSI | `wifi_signal` sensor (platform `wifi_signal`) | firmware:1430 |
| Telemetry poll failures (cumulative) | `telemetry_failures` | firmware:180, incremented in `poll_inverter_telemetry`'s `on_error`/`on_no_response` |
| Configuration poll failures (cumulative) | `configuration_failures` | firmware:184, incremented in `poll_inverter_configuration`'s `on_error`/`on_no_response` |
| Telemetry online flag | `telemetry_online` | firmware:1147, set true/false around the two telemetry read blocks |
| Configuration online flag | `configuration_online` | firmware:1153, set true/false around the two configuration read blocks |
| Last telemetry update timestamp | `last_telemetry_update` (text) | firmware:1249, formatted NTP timestamp string, "Waiting" until first success |
| Last configuration update timestamp | `last_configuration_update` (text) | firmware:1256, same pattern |
| Live telemetry polling enable switch | `live_telemetry` | firmware:934, user-togglable, default ON |
| Configuration polling enable switch | `configuration_polling` | firmware:944, user-togglable, default ON |
| Write attempts since boot | `write_attempts_since_boot` | firmware:156/1463 |
| ESPHome device availability | *(not a firmware signal - HA-side MQTT/API availability)* | see "Home Assistant" below |

**No firmware uptime/restart-count sensor exists.** Searched exhaustively;
not present. Marked `unresolved` per section 5's instruction rather than
invented (see "Deployment/project" audit below for the only
restart-adjacent evidence that does exist: `deployment.automatic_restart:
false` in `VERSION.yaml`, which is a deployment *policy*, not a runtime
signal).

### Inverter communications

| Signal | id/entity | Evidence |
|---|---|---|
| Telemetry poll cadence | `interval: 10s`, `startup_delay: 5s`, gated on `live_telemetry.state && !correction_in_progress && !manual_write_in_progress` | firmware:6042-6051 |
| Configuration poll cadence | `interval: 60s`, `startup_delay: 20s`, gated on `configuration_polling.state && !correction_in_progress && !manual_write_in_progress` | firmware:6056-6065 |
| Modbus exception vs. no-response | distinguished in every `on_error` (`exception_code`) vs. `on_no_response` handler throughout the firmware | e.g. firmware:5567-5592 |
| Grid-connected state | register 194, `ecco_grid_connected` | (Task 005 registry `grid_connected_status`, cross-checked directly against this firmware) |
| Inverter system state (standby/self-check/normal/alarm/fault) | register 59, `ecco_inverter_system_state` | firmware:4715-4739 |
| Inverter warning/fault text | registers 101-102 / 103-106 | firmware:4796-4810 |

**"ESPHome online" is NOT "inverter communications healthy"** - see
section 7.

### RTC/time

| Signal | id/entity | Evidence |
|---|---|---|
| NTP synced flag | `ntp_synced` / `ntp_synced_sensor` | firmware:100/1124, set on first successful SNTP sync |
| RTC read cadence | `interval: 60s`, `startup_delay: 30s`, gated on `!correction_in_progress && !manual_write_in_progress` | firmware:6031-6040 |
| Clock difference (inverter minus NTP, seconds) | `latest_clock_difference` / `clock_difference_valid` / `clock_difference` sensor | firmware:104/108/5404-5406 |
| Automatic correction trigger | queued when `automatic_clock_sync.state && !correction_in_progress && !cooldown_active && (date_mismatch \|\| abs_difference >= correction_threshold)` | firmware:5542-5566 |
| Correction in progress | `correction_in_progress` | firmware:116 |
| Correction attempt counter (this correction) | `correction_attempt`, max 2 retries | firmware:5454-5459 |
| Post-write verification delay | `verification_due_ms = millis() + 10000` (10s) | firmware:2569 |
| Cooldown after failed correction | `cooldown_until_ms = millis() + 300000` (5 minutes) | firmware:5482/6106 |
| Corrections since boot (success) | `corrections_since_boot` | firmware:5425 |
| Failed corrections (cumulative) | `failed_corrections` | firmware:5476/6101 |
| RTC stall detection | `rtc_stall_detected` / `rtc_stall_count`, compares inverter-vs-NTP elapsed seconds over a 45-90s window, stall = inverter advanced less than (NTP elapsed - 15s) | firmware:5500-5521 |
| Automatic clock sync enable switch | `automatic_clock_sync` | firmware:928, user-togglable, default ON |
| Manual sync button | `sync_inverter_clock` | firmware:5595 |

No DST/timezone-assumption signal exists beyond the fixed
`0.uk.pool.ntp.org` / `1.uk.pool.ntp.org` / `2.uk.pool.ntp.org` SNTP
server list (firmware:72-74) - `docs/PORTABILITY_AUDIT.md` already
flags the fixed `Europe/London` timezone as a known portability gap;
Task 006 does not change it, only notes it is out of scope for a
health *check* (there is no live signal to check against - it is a
compile-time constant).

### Manual writes (TOU staging/apply)

| Signal | id/entity | Evidence |
|---|---|---|
| Master write-enable arm | `manual_config_write_enable` switch, auto-disarms after every Apply attempt | firmware:949-950 (comment) |
| Write in progress | `manual_write_in_progress` | firmware:301 |
| Write attempts/successes/failures (cumulative) | `manual_write_attempts` / `manual_write_successes` / `manual_write_failures` | firmware:442/446/450 |
| Per-slot staging-loaded flags | `manual_slotN_staging_loaded` (one per slot 1-6) | e.g. the `load_manual_slotN_staging` buttons |
| Last write result (text) | `manual_config_last_result` | referenced throughout every apply-slot script's rejection/success messages |
| Raw config cache valid | `manual_config_raw_cache_valid` | set false on any poll failure (firmware:5057/5069), true again once block 241-293 has been read (firmware:5226) |

### Free Power

| Signal | id/entity | Evidence |
|---|---|---|
| Active (persisted across reboot) | `free_power_active_persisted` / `free_power_active_sensor` | firmware:461/1192-1195 |
| Snapshot valid (persisted across reboot) | `free_power_snapshot_valid` | firmware:457, set true once the snapshot phase completes (firmware:2708) |
| Operation in progress | `free_power_operation_in_progress` | referenced throughout the start/end scripts' preconditions |
| Write failed (this attempt) | `free_power_write_failed` | referenced throughout the write/verify blocks |
| Start attempts/successes (cumulative) | `free_power_start_attempts` / `free_power_start_successes` | firmware:587/591 |
| Restore successes (cumulative) | `free_power_restore_successes` | firmware:595 |
| Failures (cumulative, start+restore combined) | `free_power_failures` | firmware:599 |
| Status text | `free_power_status`, includes explicit `REJECTED`/`END DEFERRED`/`END IGNORED` states naming the blocking condition | firmware:2897-2901, 3068-3071 |
| Watchdog cadence | `interval: 15s`, `startup_delay: 15s` - auto-restores if snapshot valid but not active (interrupted activation), or if the end-epoch has passed, or an explicit end was requested | firmware:6011-6029 |

The watchdog logic at firmware:6022 (*"Snapshot valid but not active
means activation/restore was interrupted: fail safe by restoring"*) is
itself evidence that an unresolved-snapshot-after-restart condition is
a firmware-anticipated failure mode, not a hypothetical one - this
directly informs the `free_power_snapshot_pending_recovery` health
check (section 11).

### Home Assistant

| Signal | Evidence |
|---|---|
| Per-entity `availability` templates (many: tariff, solar forecast, canonical telemetry, runtime config) | `home-assistant/packages/ecco_pro.yaml`, `ecco_canonical_telemetry.yaml`, `ecco_runtime_config.yaml` - all follow the pattern `states(x) not in ['unknown','unavailable','none','']` |
| Runtime configuration readiness | `binary_sensor.ecco_runtime_configuration_ready` - already exists, checks battery capacity/round-trip efficiency/charge-start-minute bounds | `home-assistant/packages/ecco_runtime_config.yaml:193-206` |
| Effective grid-charge power limit | `sensor.ecco_config_maximum_grid_charge_power` = `min(hardware_ceiling, operating_limit)`, itself unavailable unless both inputs are | `home-assistant/packages/ecco_runtime_config.yaml:80-100` |
| Canonical telemetry `refreshed_at` attribute | every canonical sensor in `ecco_canonical_telemetry.yaml` stamps `now().isoformat()` on every trigger (raw entity state change or HA start) | `home-assistant/packages/ecco_canonical_telemetry.yaml` |
| Free Power HA scheduling wrapper status | `sensor.ecco_free_power_schedule_status` | `home-assistant/packages/ecco_free_power_schedule.yaml:354` |

No package dependency declarations exist in HA YAML itself (Home
Assistant packages do not have an internal dependency manifest); the
only dependency information is `VERSION.yaml`'s `home_assistant:` block
and `deployment/ha-manifest.yaml`, both audited under "Deployment"
below.

### InfluxDB

| Signal | Evidence |
|---|---|
| `ecco_raw` bucket, 30-day retention | `CURRENT_STATE.md` "Buckets" section |
| `ecco_5m` bucket, 730-day retention | same |
| `ecco_daily` bucket, indefinite retention | same |
| 5-minute Battery Outlook task cadence | `option task = {every: 5m, offset: 2m}` | `influxdb/tasks/ecco_battery_outlook_5m.flux:27-30` |
| Daily scorer task cadence (runs every 5 minutes, but a new *score point* only appears once/day near the scoring checkpoint) | `option task = {every: 5m, offset: 3m}` | `influxdb/tasks/ecco_battery_outlook_score_daily.flux:19-22` |
| HA read-back window for live-model fields | `range_start: "-30m"` (task writes every 5 min - a 30-minute window tolerates up to 5 missed runs before the HA sensor goes unavailable) | `home-assistant/packages/ecco_battery_outlook_influx.yaml:11-13, 28` |
| HA read-back window for daily score fields | `range_start: "-30d"` / `-7d` for the rolling MAE/bias | same file, throughout |

**No InfluxDB history-depth or coverage query exists in the repository
today.** Section 9 designs new, explicitly read-only, ad-hoc Flux
diagnostics to fill this gap - none of it is a production task.

### Battery Outlook

| Signal | Evidence |
|---|---|
| `predicted_soc_0035` (5-minute model output) | `ecco_battery_outlook` measurement, read via `sensor.ecco_predicted_soc_0035` |
| `training_days_equivalent` | same measurement, `sensor.ecco_load_model_training_days` |
| `model_capacity_kwh` / `discharge_efficiency` (model's OWN view of config, for drift comparison against `input_number.ecco_battery_model_capacity`/`ecco_round_trip_efficiency`) | same measurement |
| Daily scorer: `predicted_soc_0035` / `actual_soc_0035` / `error_soc_points` / `absolute_error_points` | `ecco_battery_outlook_score` measurement |
| Model identifiers | `load_only_v1_2` (5-minute model), `load_only_v1_3` (daily scorer) per `VERSION.yaml` |
| Scoring checkpoint | `lead180_to_target` per `CURRENT_STATE.md` - the scorer target derives from the *live* TOU charge-start minute, not a hard-coded time |
| Anti-contamination assumption | `CURRENT_STATE.md`: "daily scorer selects the latest pre-charge actual SOC and no longer contaminates the score with SOC values after grid charging begins" |

### Deployment/project

| Signal | Evidence |
|---|---|
| Expected component versions/paths | `VERSION.yaml` `current:` block (dashboard 7.13.0, firmware stage3.4, HA package paths, Influx task paths) |
| `hardware_verified` / `tested_in_home_assistant` flags | `VERSION.yaml current.firmware.hardware_verified`, `current.dashboard.tested_in_home_assistant` |
| `proven:` flags (15 named capabilities) | `VERSION.yaml proven:` block |
| Deployment manifest (source -> destination -> method -> restart_required) | `deployment/ha-manifest.yaml` |
| Rollback reference | `VERSION.yaml rollback:` block (branch/dashboard/firmware pointers) |
| Safety policy flags | `VERSION.yaml safety:` block (`automatic_live_deployment: false`, `automatic_optimizer_control: false`, etc.) |

No deployed-file-hash or "what is actually live right now" signal
exists anywhere in this repository - by design, this repository only
ever knows what it *intends* to deploy, not what a given installation
*currently has live*. Section 20 designs configuration-drift checks
strictly bounded by this reality (repo-vs-repo and repo-vs-HA-entity
comparisons only, never a live file hash).

## 2. Health state model

Six states, kept intentionally small:

| State | Meaning |
|---|---|
| **HEALTHY** | All required signals for this scope are current and within expected operating bounds. |
| **DEGRADED** | ECCO is functioning, but one or more non-critical inputs are stale, unavailable, or below preferred quality. Does not indicate a safety concern. |
| **WARNING** | A condition requires attention but is not yet a confirmed failure - e.g. a retry is in progress, a threshold was crossed once, or evidence is incomplete for a subsystem that matters. |
| **FAILED** | A critical required subsystem is unavailable, or a safety-relevant transaction/recovery state has genuinely failed (exhausted retries, stuck beyond its maximum legitimate duration, or left in a state the firmware itself treats as needing recovery). |
| **UNKNOWN** | Insufficient evidence to determine health for this scope - e.g. no reading has ever been received. Distinct from FAILED: UNKNOWN says "we don't know," FAILED says "we know, and it's bad." |
| **SUPPRESSED** | An otherwise-attention-worthy condition is intentionally ignored because the relevant subsystem is inactive/not applicable right now (e.g. Free Power checks while Free Power has never been used; `battery_outlook_scorer` "stale" outside its once-daily scoring window). SUPPRESSED is not a euphemism for "still broken but ignored forever" - it only applies while the *applicability condition* documented on the check is false. |

Severity ranking for aggregation purposes (section 13):
`HEALTHY = SUPPRESSED = 0 < DEGRADED = 1 < WARNING = UNKNOWN = 2 < FAILED = 3`.

**Task 006A clarification - UNKNOWN is a distinct, preserved state, never
silently collapsed into WARNING.** The original Task 006 implementation
shared a numeric rank between WARNING and UNKNOWN (both "requires
attention, not yet a confirmed FAILED-level problem") and then mapped
that shared rank straight back to the literal label `WARNING` - meaning
a subsystem or overall result that was purely UNKNOWN (no real finding
at all, just missing evidence) was reported as `WARNING`, which defeats
the point of having UNKNOWN as its own state. Sharing a *rank* for
threshold/capping arithmetic is fine and intentional (both represent
"not yet a definite FAILED-level problem" for capping purposes); silently
choosing whichever *label* happened to be evaluated first at that rank
is not. The fix (`health/system_health.py`'s `_resolve_flavor_at_rank()`)
is a small, explicit, deterministic tie-break applied every time a rank
is turned back into a displayed state, at both subsystem and overall
level:

- if a **real, definite finding** at this rank is present (WARNING at
  rank 2, DEGRADED at rank 1, FAILED at rank 3, HEALTHY at rank 0), it
  always wins - a genuine problem is more informative than an absence
  of evidence and must never be hidden behind it.
- otherwise, if **UNKNOWN** is present at this rank, it wins - absence
  of evidence is reported honestly, never silently promoted to HEALTHY.
- otherwise (rank 0 only, nothing but SUPPRESSED contributors), the
  result is SUPPRESSED.

This is never "whichever check happens to appear first in registry
order" - the tie-break rule is fixed and documented, and
`health/tests/test_system_health.py` asserts it directly (see "pure
UNKNOWN subsystem preserved as UNKNOWN" and "WARNING + UNKNOWN at same
effective tier" in section 15/9).

**No arbitrary severity escalation.** Every check in
`registry/system_health_checks.yaml` declares exactly which state(s)
it can produce and under what condition (`severity` + `check_type` +
thresholds) - there is no code path that lets a check "decide" to
escalate beyond its documented policy.

## 3. Subsystem model

Sixteen subsystems (the original fourteen from the task's explicit minimum
list, plus `supervision` and `fallback` added by FB-B3 - see rationale below):

| Subsystem | Criticality tier | Blocks manual control? | Affects forecast only? |
|---|---|---|---|
| `communications` | CRITICAL | yes | no |
| `inverter_telemetry` | CRITICAL | yes | no |
| `inverter_configuration` | CRITICAL | yes | no |
| `rtc_time` | CRITICAL | yes (correction-stuck only) | no |
| `manual_write_system` | CRITICAL | yes | no |
| `free_power` | CRITICAL | yes | no |
| `runtime_configuration` | CRITICAL | yes | no |
| `home_assistant` | STANDARD | no | no |
| `canonical_telemetry` | STANDARD | no | no |
| `influx_raw` | STANDARD | no | yes |
| `influx_5m` | STANDARD | no | yes |
| `deployment_consistency` | STANDARD | no | no |
| `supervision` | STANDARD | no | no |
| `fallback` | STANDARD | no | no |
| `battery_outlook` | INFORMATIONAL | no | yes |
| `battery_outlook_scorer` | INFORMATIONAL | no | yes |

**`supervision` and `fallback` (FB-B3).** Both are read-only display-layer
subsystems (`home-assistant/packages/ecco_fallback_status.yaml` feeding
`ecco_health_supervision` / `ecco_health_fallback` in
`ecco_system_health.yaml`). `supervision` is separate from `home_assistant`,
which reports HA's own health and cannot report its own absence. Both are
STANDARD tier for now: a supervision `Lost` reports WARNING (not FAILED), and
they become CRITICAL only at FB-F, when supervision becomes authoritative and
`Lost` may then become FAILED.
Neither blocks manual control. Implemented offline only, not live-proven.

**Criticality tiers cap how much a subsystem's internal state can
influence the overall rollup** - see section 13. CRITICAL subsystems
are the ones whose failure means ECCO cannot reliably observe or
safely offer control of the inverter. STANDARD subsystems affect data
quality/consistency without a direct control-safety implication.
INFORMATIONAL subsystems (Battery Outlook forecasting) can be
completely broken without making the *inverter-monitoring* function of
ECCO unsafe or unusable - this is the exact case section 13's example
("stale Battery Outlook may make overall DEGRADED while inverter
monitoring is otherwise healthy") describes.

**Why no `grid`/`battery`/`pv`/`forecast_inputs`/`historical_data`
subsystems**: the task explicitly says to only add them "where
repository evidence supports useful checks." Grid/battery/PV telemetry
freshness is already fully covered by `inverter_telemetry` (they share
the exact same two poll blocks and the exact same `telemetry_online`/
`last_telemetry_update` signals - there is no independent freshness
signal per measurement family, only per poll block). `forecast_inputs`
would duplicate `runtime_configuration` (battery capacity/efficiency)
and `inverter_telemetry` (current SOC/load) rather than adding a new
signal. `historical_data` is exactly `influx_raw`/`influx_5m`. Adding
these as separate subsystems would have created redundant rollup paths
without a single new underlying signal - exactly the kind of
speculative generalisation this project's engineering conventions warn
against (see `docs/INVERTER_CAPABILITY_REGISTRY.md`'s "Grouped
records" section for the same principle applied to the capability
registry).

Each subsystem's evaluated result (`SubsystemResult` in the reference
engine, section 14) exposes: `state`, `severity` (numeric rank),
`reason_codes` (list), `human_reason` (joined summary), `last_good`
(timestamp or None), `age_seconds` (float or None),
`source_signals` (list of the raw inputs consulted),
`blocks_manual_control` (bool), `affects_forecast_only` (bool),
`informational_only` (bool).

**`rollup_participation` - Task 006A section 3.** Not every check can
be continuously/automatically evaluated. `influx_raw_freshness`,
`influx_5m_freshness`, and `influx_history_depth` are inherently
manual/ad-hoc Flux diagnostics with no evidenced fixed threshold
(section 5); `battery_outlook_model_version` and
`battery_outlook_scorer_anti_contamination` are PERMANENT repository
limitations - no live signal exists or can exist to verify them
without re-running production Flux logic. The original Task 006
implementation had no way to exclude these from the automatic
rollup, so the "healthy baseline" test could never reach `HEALTHY` -
two permanently-UNKNOWN checks meant `sensor.ecco_system_health` would
read `WARNING` forever, even with every real signal perfect. Each
check now declares a `rollup_participation`:

- `automatic` (the default) - participates in
  `evaluate_subsystem()`/`evaluate_overall()`'s automatic rollup.
- `diagnostic_only` - a manual/ad-hoc diagnostic with no continuous
  live signal or no evidenced fixed threshold. Still fully evaluated
  and visible (`SubsystemResult.diagnostic_results`), but excluded
  from the automatic state.
- `manual_only` - a permanent repository-level limitation that would
  otherwise poison the automatic overall state forever. Same
  exclusion/visibility treatment as `diagnostic_only`.

A subsystem whose checks are *all* `diagnostic_only`/`manual_only`
(today: `influx_raw`, and `influx_5m` - both of whose only checks are
manual Flux diagnostics, see section 6/7) reports its own state as
`UNKNOWN` for a human/UI to see, but is marked
`contributes_to_overall: False` and is excluded from
`evaluate_overall()`'s `max()` entirely - it cannot drag
`sensor.ecco_system_health` down no matter how long it stays
unresolved. A subsystem with genuinely zero results at all (nothing
evaluated this round) still contributes `UNKNOWN` at full weight - the
exclusion is specifically for "this can never be automatic by design",
not a general escape hatch for "we didn't get around to evaluating
it this time".

## 4. Machine-readable health-check registry

`registry/system_health_checks.yaml` - one record per check. See the
file's own header comment for the full field-by-field schema and
`tools/validate_system_health_checks.py` for what is mechanically
enforced. Summary of check types actually used (only the ones ECCO's
real signals need - see section "Do not build a generic framework" in
the registry file header):

| `check_type` | Used for |
|---|---|
| `entity_available` | e.g. does `binary_sensor.ecco_runtime_configuration_ready` exist/report a real state |
| `freshness` | timestamp-based staleness (telemetry, configuration, RTC read, Influx points, Battery Outlook results) |
| `boolean_expected` | e.g. `ntp_synced` should be true |
| `numeric_range` | e.g. Wi-Fi RSSI plausible range, clock difference plausible range |
| `failure_counter_delta` | recent-vs-historical cumulative counters (section 6) |
| `text_state` | e.g. inverter system state must not be `alarm`/`fault` |
| `transaction_state` | e.g. `manual_write_in_progress`/`free_power_operation_in_progress` stuck-duration checks |
| `timestamp_age` | alias of `freshness` used specifically for "time since last X happened" checks where X is an *event*, not a *periodic poll* (e.g. time since last successful RTC correction is NOT checked this way per section 5 - no proven cadence exists for it) |
| `cross_source_agreement` | canonical-vs-raw value/timestamp comparison |
| `history_depth` | Influx training-history sufficiency |
| `version_match` | `VERSION.yaml` vs. deployment manifest vs. actual file existence |
| `conditional_presence` | e.g. Free Power checks only apply once Free Power has ever been used |

`hash_match` is defined in the enum (the task lists it as a possible
type) but **no check in the registry currently uses it** - there is no
safe, evidenced way to compute a "deployed" hash without live SSH
access, and inventing one would violate the "no live file mutation/no
live access" constraint. It remains available for a future check that
compares two *repository* file hashes (e.g. "does the dashboard file
referenced by `VERSION.yaml` match the one referenced by the deployment
manifest") if that need arises; today `version_match`'s path-existence
checks already cover the evidenced case.

**Task 006B fix - `None` never means HEALTHY, for any check_type, ever.**
A second review pass found three check types whose `evaluate_check`
branch used Python truthiness (`if not signal.available`, `if not
signal.active`, `if not signal.checkpoint_passed`) instead of an
explicit identity check against `None` - and in Python, `not None` and
`not False` are both `True`, so "we were never told" and "we were told
it is false" collapsed into the same code path, which for
`entity_available`/`transaction_state` happened to be the HEALTHY
return. Every affected check_type now checks `is None` first,
explicitly, before checking the real boolean value:

- **`entity_available`**: `available is None` (evidence not supplied,
  regardless of `ever_observed`) -> UNKNOWN. Only `available is False`
  -> the configured unavailable outcome; only `available is True` ->
  HEALTHY.
- **`transaction_state`**: `active is None` -> UNKNOWN ("whether a
  transaction is active is unknown"), distinct from `active is False`
  -> HEALTHY ("confirmed not active"). `active is True` with
  `active_since is None` was already fixed in Task 006A (section 11) -
  now correctly reached only when `active` is unambiguously `True`.
- **`conditional_presence`**: `checkpoint_passed is None` -> UNKNOWN,
  distinct from `checkpoint_passed is False` -> the NOT_YET_DUE/
  SUPPRESSED outcome. Once `checkpoint_passed is True`,
  `scored_since_checkpoint is None` -> UNKNOWN as well, distinct from
  `scored_since_checkpoint is False` -> the STALE outcome.

Because a bare `CheckInput()` leaves every field at its dataclass
default (`available=None`, `active=None`, `checkpoint_passed=None`),
this fix means **a completely untouched, no-evidence-supplied
`CheckInput()` now correctly evaluates UNKNOWN for every one of these
check types** - "the check object exists" never means "the
precondition is proven safe." `health/tests/test_system_health.py`'s
"[11] Defensive fail-closed inputs" section asserts this directly for
every required check capable of blocking manual control, using bare
`CheckInput()` instances rather than the `all_healthy_signals()`
baseline the rest of the test file otherwise uses.

## 5. Freshness/staleness rules and their evidence

Every threshold below cites the firmware/Influx evidence it was
derived from (section 1). Where no cadence evidence exists, the
threshold is marked `unresolved` rather than guessed, per the task's
explicit instruction.

| Signal | Expected interval | Degraded-after | Failed-after | Rationale |
|---|---|---|---|---|
| Inverter telemetry poll | 10s | 60s (6 missed cycles) | 180s (3 min) | Poll pauses legitimately during an active manual write/RTC correction; those complete in low tens of seconds at most (see `manual_write_system`/`rtc_time` evidence below) - 180s is well beyond any legitimate single transaction, covering WiFi reconnect too. |
| Inverter configuration poll | 60s | 180s (3 missed cycles) | 600s (10 min) | Same pause reasoning, scaled to the slower 60s cadence; configuration is explicitly "slow-changing data" per firmware:6053-6055's own comment, so a longer failed-after is appropriate. |
| RTC read (`clock_difference_valid`) | 60s | 180s | 600s | Same poll-block pause reasoning as configuration (RTC read shares the same gating conditions). |
| Last successful RTC *correction* | **unresolved - no cadence evidence** | - | - | Corrections only occur when drift exceeds `correction_threshold`; a well-behaved NTP+RTC pair could legitimately go days between corrections. No repository evidence establishes an expected correction interval - checking for one would be guessing. The evidenced check instead is "drift exceeds threshold but no correction is in progress and none is in cooldown" (see below), which does not require assuming a cadence. |
| `manual_write_in_progress` stuck | n/a (transaction, not poll) | 60s | 180s | Worst-case single-slot Apply: ~5 sequential register writes at 700ms-1200ms delay each (~5s) plus a verification reread; even with a full retry, well under 30s in the firmware's own write sequencing (see e.g. firmware:3479-3546 for the per-write delay pattern). 180s is a 6x margin. |
| `correction_in_progress` stuck | n/a (transaction) | 60s | 180s | Verification delay is a fixed 10s (firmware:2569) with up to 2 retries and 1s-cadence retry processing (firmware:6067) - worst case well under 30s. Same 180s margin as manual writes. |
| Free Power watchdog reaction | 15s | 60s | 180s | The watchdog itself runs every 15s (firmware:6011); if a `free_power_snapshot_valid && !free_power_active_persisted` condition (interrupted activation) persists past several watchdog cycles, the watchdog itself is not resolving it - this is the `free_power_snapshot_pending_recovery` check (section 11), not a poll-freshness check. |
| Battery Outlook 5-minute model result (OUTPUT, `sensor.ecco_predicted_soc_0035`) | 5m (task `every: 5m, offset: 2m`) | 20m | *(single-tier check - see below)* | The task's own 5-minute cadence is proven (`influxdb/tasks/ecco_battery_outlook_5m.flux:27-30`). 20 minutes = 4 elapsed task periods, chosen with margin over a single missed run without claiming a precise "how many misses the HA package's own read-back tolerates" figure - see the correction below. |
| Battery Outlook daily scorer result | **not a fixed interval - see section 10** | - | - | The scorer task itself runs every 5 minutes, but a new *score point* is only expected once per day near the `lead180_to_target` checkpoint relative to the live TOU charge-start. "Stale" here must be evaluated against "was today's scoring window supposed to have happened yet," not a fixed clock - see section 10 and section 6's "recent failure vs. not-yet-due" distinction. |
| InfluxDB `ecco_raw` latest point | *(HA-side polling cadence not evidenced - the export configuration governs write cadence into InfluxDB, not read cadence out)* | Ad-hoc Flux diagnostic only (section 9) - `thresholds_unresolved: true`, `diagnostic_only` (section 3) - no automatic freshness check is defined against a HA entity, since no HA entity currently reads `ecco_raw` directly. | | |
| InfluxDB `ecco_5m` **underlying house-load history** (`sensor.ecco_clock_dongle_ecco_load_power`, NOT the Battery Outlook output - see section 6/7 correction) | *(ecco_5m's own write/downsample cadence is not evidenced anywhere in this repository - distinct from the task's 5-minute READ cadence)* | Ad-hoc Flux diagnostic only (`influxdb/diagnostics/latest_ecco_5m_point.flux`) - `thresholds_unresolved: true`, `diagnostic_only` | | |

**Task 006A correction on the "20-minute/30-minute" commentary.** The
original Task 006 text claimed the 20-minute threshold "brackets the
existing 30-minute HA read-back window from both sides" and cited an
exact "4 missed runs" figure alongside a 35-minute failed-after tier
that this check never actually implements (it is a genuine
single-outcome, single-tier WARNING check - see
`registry/system_health_checks.yaml`'s `battery_outlook_freshness`).
Re-checking precisely: `ecco_battery_outlook_influx.yaml`'s own header
comment says live-model sensors read the latest value from a
`range_start: "-30m"` Flux window so "one missed task run does not
immediately make them unavailable" - that is the point at which the HA
*entity itself* would report `unavailable` (roughly 5 missed
consecutive 5-minute runs before the last good point ages out of a
30-minute lookback, by simple division, though the package's own
comment states this conservatively as "one missed run" rather than an
exact count). This health check's own 20-minute WARNING threshold is a
**separate, independently-chosen** number - it is not mathematically
derived from the HA package's 30-minute window and does not "bracket"
it; it exists purely so this health check raises a finding before the
HA entity itself would go fully unavailable, with a comfortable margin
(4 task periods) over a single missed run. The two numbers are
related in spirit (both exist to tolerate transient misses) but are
not two ends of one calculation - claiming otherwise, as the original
text did, overstated the precision behind the design. Additionally,
because `influx_5m_freshness` now measures the underlying history
directly via a manual Flux diagnostic (`diagnostic_only`, section
3/6/7) rather than the HA output entity, it has no threshold at all
(`thresholds_unresolved: true`) - only `battery_outlook_freshness`
(the output-side check) keeps the 20-minute WARNING threshold.

**Tolerance for HA/ESPHome restart, Wi-Fi interruption, and inverter
response delay** is folded into every threshold above by using
multiples of the expected interval (6x for the communications/RTC
degraded tiers, up to 18x for the 180s failed-after on 10s telemetry)
rather than tight single-miss thresholds - this directly satisfies the
task's explicit instruction to tolerate restarts/interruptions and
avoid flapping (cross-referenced again in section 21).

## 6. Counter-delta health

Every "since boot" counter in the firmware (`telemetry_failures`,
`configuration_failures`, `manual_write_failures`, `free_power_failures`,
`failed_corrections`, `rtc_stall_count`) is monotonically
non-decreasing and **never resets except on device reboot**. A
non-zero value is not itself unhealthy - a device that has been
running for months will accumulate some historical failures from
transient WiFi blips even in a perfectly healthy system today.

**Design**: every counter-delta check requires an explicit **baseline
snapshot** (`{counter_value, observed_at}`) taken by whatever is
running the check, plus the counter's *current* value. The check
computes `delta = current - baseline.counter_value` over
`elapsed = now - baseline.observed_at`, and classifies:

- `elapsed` too short for a meaningful baseline yet (less than the
  check's `window_seconds`) -> **UNKNOWN** for this specific check
  (not FAILED - there is no evidence either way).
- `delta == 0` -> **HEALTHY** (no new failures in the window),
  regardless of how large the absolute counter is.
- **`delta < 0` (current counter value is LOWER than the baseline) ->
  UNKNOWN, "counter reset detected" - never HEALTHY.** Task 006A fix:
  the original implementation's `delta <= 0` test treated a negative
  delta identically to a zero delta ("no new failures"), which is
  wrong - these "since boot" counters are monotonically non-decreasing
  *within one boot* and reset only on an ESP32 reboot (section 1). A
  negative delta is strong evidence the device rebooted (or, far less
  likely, some other counter anomaly) since the baseline was captured,
  which makes the OLD baseline meaningless for judging "how many new
  failures happened" - reporting HEALTHY from a baseline we know is
  invalid would be a false clean bill of health. The check now reports
  UNKNOWN with an explicit "counter went backwards, rebaseline
  required" reason, exactly mirroring the "insufficient evidence yet"
  case above rather than inventing a new severity for it.
  **Implication for a future HA implementation**: the baseline-capture
  mechanism (see below) must detect this condition itself and capture
  a *fresh* baseline immediately (current counter value, observed now)
  whenever it notices `current < previous_baseline`, so the check
  naturally recovers to HEALTHY/WARNING on its next evaluation once a
  real window has elapsed against the new baseline - this task does
  not implement that capture logic (no HA binding exists yet), only
  specifies the requirement.
- `0 < delta <= warning_delta` -> **WARNING** ("recent failure",
  possibly transient/recovering).
- `delta > warning_delta` (or, for some checks, `failure_delta`
  reached) -> **DEGRADED or FAILED** depending on the specific check's
  documented severity (a communications counter climbing this fast is
  more severe than an RTC counter, since it implies non-functioning
  telemetry, whereas isolated RTC retries are an expected part of
  normal correction behaviour).

**Successful recovery** is represented explicitly: if a
`failure_counter_delta` check's window shows failures earlier in the
window but the most recent poll/transaction succeeded (tracked via the
corresponding `_online`/`_in_progress`/`*_successes` companion signal),
the check reports **WARNING, not FAILED**, with a reason code and
human text that says "recovered" - this is what distinguishes
"historical failures," "recent failure," "repeated current failure,"
and "successful recovery" as four different outcomes from the same
counter, exactly as the task requires. The reference engine
(section 14) implements this via the `CounterBaseline` /
`evaluate_counter_delta()` helper, tested explicitly in section 15's
"recent Modbus failures then successful recovery" scenario.

This baseline-tracking is the health engine's own responsibility (it
must be given a prior observation to compare against) - the design
does not assume Home Assistant or any other caller magically knows the
previous counter value. In the eventual HA implementation
(`docs/SYSTEM_HEALTH_HA_DESIGN.md`), this baseline would be an
HA `input_number`/`restored` template value or a `recorder`-backed
history lookback; that binding is design-only in this task.

## 7. Modbus/communications health model

Distinct, independently-evaluated signals for the two poll blocks, so
"ESP32 online but inverter unavailable" is representable and never
collapsed into one flag:

- **`communications`** subsystem = ESPHome device reachability from
  Home Assistant's perspective (API/MQTT connection state - an HA-side
  signal, not a firmware one; there is no firmware self-report of "am
  I connected to HA"). This is deliberately the *outermost* layer: if
  this is down, nothing else can be evaluated at all (every other
  subsystem that depends on an ESPHome-exposed entity becomes
  `UNKNOWN`, not `FAILED`, because there is no evidence, only absence
  of evidence - see the state model's UNKNOWN/FAILED distinction).
- **`inverter_telemetry`** subsystem = `telemetry_online` +
  `last_telemetry_update` freshness + `telemetry_failures` counter-delta.
  Independently evaluated from `configuration_online`.
- **`inverter_configuration`** subsystem = `configuration_online` +
  `last_configuration_update` freshness + `configuration_failures`
  counter-delta. Independently evaluated from `telemetry_online`.

A concrete example the design must support, taken directly from the
task: telemetry stale while configuration is fresh (or vice versa) is
two *different* subsystem results, not a single blended "communications
degraded" flag - each has its own state/reason/age, and the overall
rollup (section 13) sees both independently. "One polling block
degraded while others remain good" is therefore representable by
construction, not a special case.

`register_330` (the communication-board basic-settings block) is
folded into `inverter_configuration`'s failure-counter accounting
since it is read within the wider configuration-poll cadence and has
no independent poll interval of its own in this firmware - see Task
005's registry (`basic_sync_clock_flag`/`basic_beep_flag`) for the
register-level detail, cited here as reference only.

## 8. Canonical telemetry health

`home-assistant/packages/ecco_canonical_telemetry.yaml` already exists
on this branch's base (it is *not* an unmerged Task 004 dependency -
confirmed present at `5d7d6b482`). It defines four canonical sensors
(`ecco_battery_soc`, `ecco_house_power`, `ecco_pv_power`,
`ecco_grid_power`), each:

- triggered on `homeassistant: start` or a `state` change of its
  single raw source entity,
- `availability` mirrors the raw entity's `unknown`/`unavailable`/
  `none`/`''` state directly,
- stamps a `refreshed_at` attribute with `now().isoformat()` on every
  trigger.

Because the canonical sensor updates **synchronously with the raw
entity's own state change** (it is an HA automation-style trigger, not
an independent poll), there is no independent "canonical polling
cadence" to check - the only two failure modes are (a) the trigger
itself did not fire even though the raw entity changed (would require
an HA restart/reload race, extremely tight window) and (b) the raw
entity itself went stale, which is not a canonical-layer problem at
all. The design therefore checks:

- **canonical entity exists / is available** - `entity_available` /
  `boolean_expected` on the availability template's result.
- **raw entity exists / is available** - same, against the raw source.
- **canonical freshness** = age of `refreshed_at` relative to *now*
  (not relative to the raw entity - see below).
- **raw freshness** = the underlying `inverter_telemetry` subsystem's
  own freshness (not duplicated here - `canonical_telemetry` cites it
  as a dependency check rather than re-implementing it).
- **canonical/raw timestamp skew** = `canonical.refreshed_at` minus
  the raw entity's `last_changed`. Given the synchronous-trigger
  design, this should be seconds, not minutes - a tolerance of 30s is
  used (generous margin over normal HA state-processing latency,
  avoiding false positives from HA's own internal scheduling jitter).
- **canonical/raw value agreement** = `abs(canonical.state -
  float(raw.state))` - since canonical is a direct float/round of the
  raw value with no unit conversion, this should be exactly 0 in the
  normal case; a tolerance of `0.5` (in the canonical sensor's own
  unit) absorbs float rounding, not a real disagreement. A "large
  value disagreement" beyond that tolerance would only occur if the
  template itself were broken (wrong source entity, wrong rounding) -
  worth flagging, but explicitly `WARNING`, not `FAILED`, since it
  cannot itself cause a bad inverter write (canonical entities are
  read-only aliases, never a write source).
- **canonical missing while raw survives** / **raw missing while
  canonical stale** / **both missing** - three distinct reason codes
  (`CANONICAL_ENTITY_MISSING`, `CANONICAL_STALE_RAW_FRESH`,
  `RAW_AND_CANONICAL_MISSING`), because they have different likely
  causes (a broken template vs. a genuinely offline device vs. an HA
  package that was never installed).

**HA canonical health is entirely separate from Influx canonical
history health.** No Influx measurement named after the canonical
sensors (`ecco_battery_soc` etc.) is exported anywhere in
`influxdb/ecco_influxdb_options_v1_2.yaml` or any task in
`influxdb/tasks/` - Influx export continues to use the raw
`sensor.ecco_clock_dongle_*` entity-derived measurement names,
exactly as `ecco_canonical_telemetry.yaml`'s own header comment states
("InfluxDB continues to export... unchanged - this file does not touch
that"). The design therefore does **not** assume canonical Influx
history exists just because HA canonical entities exist - there is no
`canonical_telemetry_influx` check in the registry, because there is
nothing to check (this is stated explicitly in the registry file
rather than silently omitted, so a future reader does not assume it
was forgotten).

No production migration/cutover happens in this task - `canonical_telemetry`
is a read-only health *check* of an existing, already-repository-present,
read-only *adapter* package.

## 9. InfluxDB health diagnostics

`influxdb/diagnostics/` (new, this task) contains manual/ad-hoc,
**strictly read-only** Flux scripts - no `option task`, no `to()`, no
scheduling. Each script's header comment states this explicitly and
`registry/tests/test_influx_diagnostics.py` (section 15/16) statically
asserts it for every file in the directory, so the constraint is
machine-enforced, not just documented:

| Script | Purpose |
|---|---|
| `latest_ecco_raw_point.flux` | Most recent point per measurement in `ecco_raw`, with age. |
| `latest_ecco_5m_point.flux` | Most recent point in `ecco_5m` for the Battery Outlook measurement, with age. |
| `latest_battery_outlook_result.flux` | Most recent `ecco_battery_outlook` result plus its `training_days_equivalent`. |
| `latest_battery_outlook_score.flux` | Most recent `ecco_battery_outlook_score` result plus its age. |
| `history_depth_check.flux` | Row count / distinct-day count over a lookback window, for the `battery_outlook` history-depth check (section 10). |

Each script is parameterised by bucket/measurement names already
documented in `CURRENT_STATE.md`/`VERSION.yaml` (`ecco_raw`, `ecco_5m`,
`ecco_battery_outlook`, `ecco_battery_outlook_score`) - nothing is
invented. Where a check would require assuming a bucket/measurement
name not evidenced anywhere in this repository (e.g. an `ecco_daily`
measurement name - the bucket is named in `CURRENT_STATE.md` but no
task or export config in this repository writes to it), the design
**documents the gap explicitly** in the script's own header rather
than guessing a name (see `latest_ecco_raw_point.flux`'s header for
the specific note on `ecco_daily`).

None of these scripts are referenced by `deployment/ha-manifest.yaml`
or any Influx task - they are for a human (or a future health-check
runner with read-only Influx credentials) to run manually, exactly as
the task specifies ("manual/ad-hoc only").

## 10. Battery Outlook health

**Forecast pipeline health** (is the machinery running) is kept
strictly separate from **forecast accuracy** (is the machinery
*right*) - two different subsystems (`battery_outlook` for the
pipeline, `battery_outlook_scorer` for the accuracy/scoring pipeline,
which is itself *also* a pipeline-health question, not a judgement of
whether ECCO is "smart enough").

Pipeline-health checks (`battery_outlook` subsystem):

- current SOC input available/fresh - delegates to `inverter_telemetry`
  (battery SOC is a telemetry-block register), not re-implemented.
- house-load history available - the ACTUAL training input, confirmed
  by reading `influxdb/tasks/ecco_battery_outlook_5m.flux:100-106`
  directly: `sensor.ecco_clock_dongle_ecco_load_power` in the
  `ecco_5m` bucket, NOT a canonical/Task-004 entity (this branch is
  independent of Task 004) and NOT the model's own output. Checked
  under the `influx_5m` subsystem (`influx_5m_freshness`,
  `influx_history_depth` - both `diagnostic_only`, see section 3/6/7),
  deliberately kept separate from `battery_outlook`'s own
  self-reported `training_days_equivalent` (`battery_outlook_history`)
  - see the Task 006A correction below.
- `training_days_equivalent` present and non-decreasing-over-reboots
  is not checkable offline (would require a stored baseline across
  restarts) - the check only asserts *presence and a plausible
  non-negative value*, not a trend.
- capacity/round-trip-efficiency configuration available - delegates
  to `runtime_configuration`.
- live charge-start available - delegates to `runtime_configuration`
  (`sensor.ecco_config_charge_start_minute`).
- latest model result age - `freshness` check per section 5's 20-minute
  WARNING threshold (single-tier; see the Task 006A correction in
  section 5 on why this is not "bracketed" against the HA package's
  30-minute read-back window).
- model version match - `sensor.ecco_load_model_training_days`'s
  measurement carries no explicit version field read by HA today
  (`VERSION.yaml`'s `battery_outlook_model: load_only_v1_2` is a
  *repository* expectation, not something HA currently reads back) -
  the check compares the **repository-expected** model id against
  nothing live, and is therefore a `version_match` check evaluated
  against repository state only, documented as such rather than
  pretending it observes the live task. Marked `rollup_participation:
  manual_only` (section 3) - a permanent limitation, not a transient
  problem.
- predicted target SOC exists - `entity_available` on
  `sensor.ecco_predicted_soc_0035`.

**Task 006A correction: `influx_5m` vs. `battery_outlook` separation
kept real.** The original Task 006 implementation's `influx_5m_freshness`
and `history_depth_check.flux` both used the `ecco_battery_outlook`
OUTPUT measurement as a stand-in for the data layer's health - that
only proves the production task ran, not that the underlying 5-minute
house-load history it reads is itself current or sufficiently deep.
Both `influx_5m` checks now independently query
`sensor.ecco_clock_dongle_ecco_load_power` (the confirmed actual
training input) via dedicated read-only Flux diagnostics
(`influxdb/diagnostics/latest_ecco_5m_point.flux`,
`influxdb/diagnostics/history_depth_check.flux`, the latter reporting
earliest/latest point, distinct-day coverage, and effective span - not
an expensive gap-by-gap scan). `battery_outlook_freshness`/
`battery_outlook_history` remain under the `battery_outlook` subsystem,
reading the model's own OUTPUT entities
(`sensor.ecco_predicted_soc_0035`, `sensor.ecco_load_model_training_days`)
- the independent diagnostic and the model's self-report are never
described as measuring "the same thing", per the task's explicit
instruction.

Accuracy/scoring-pipeline-health checks (`battery_outlook_scorer`
subsystem) - **never a judgement of forecast quality itself**, only
of whether scoring is happening as designed:

- scorer's latest result age, evaluated against **"was a scoring event
  due"**, not a fixed clock: because the scoring checkpoint derives
  from the live TOU charge-start minute (`lead180_to_target` per
  `CURRENT_STATE.md`), the check's `applicability_condition` is
  "current time is past today's expected scoring checkpoint" rather
  than "more than N minutes since midnight." If the checkpoint has not
  yet occurred today, an absent-today score is **SUPPRESSED**
  ("intentionally not yet due"), not WARNING/FAILED - this is the
  exact "no forecast point because model intentionally hasn't run yet
  vs. failed/stale" distinction the task requires. If the checkpoint
  has passed and no new score appeared, that is a genuine staleness
  finding (`FORECAST_SCORER_STALE`, WARNING - informational-only
  subsystem, capped there by the aggregation rule in section 13).
- latest actual-SOC sample validity - delegates to `inverter_telemetry`
  freshness at the time the scorer would have sampled it; not
  re-derivable offline without the scorer's own internal timing, so
  this is marked `documented_not_live_proven` rather than asserted.
- anti-contamination assumption "still satisfied where detectable" -
  **not detectable from outside the Flux task**. The task's own Flux
  source (`influxdb/tasks/ecco_battery_outlook_score_daily.flux`)
  implements the pre-charge-only selection logic; a health check
  cannot independently re-derive "was this specific score point
  actually pre-charge" without re-running the task's own filter logic
  against raw data, which is out of scope for a lightweight health
  check. This is **explicitly documented as undetectable** rather than
  a check that would silently always pass, and is marked
  `rollup_participation: manual_only` (section 3) - a permanent
  limitation that must not permanently poison automatic overall
  health, while remaining visible in diagnostics.
- model-error fields (`error_soc_points`, `absolute_error_points`,
  7-day MAE/bias) - these inform **accuracy monitoring**, which this
  task explicitly does not gate health on ("a forecast can be healthy
  but inaccurate" - no check in the registry ever assigns a
  non-HEALTHY state purely because the error magnitude is large; the
  7-day MAE/bias fields are exposed as informational attributes on the
  `battery_outlook_scorer` subsystem result, never as a triggering
  condition).

No forecast math changes, no production Flux task changes anywhere in
this task.

## 11. Write-system / transaction health

Read-only observation of the exact concepts the task lists, all
sourced from section 1's audited firmware signals - **Task 005's
transaction state machine is cited as design-pattern prior art only**;
this branch does not import `registry/transaction_state_machine.py`
or depend on the Task 005 branch existing.

| Concept | Check | Evidence |
|---|---|---|
| Manual-write arm left on unexpectedly | `manual_config_write_enable` observed `true` for longer than one health-poll interval with no `manual_write_in_progress` transition - the firmware auto-disarms after every Apply attempt (firmware:949-950 comment), so a switch that stays on with no write ever starting is itself unusual, though not dangerous by itself (arming alone never writes) | WARNING |
| `manual_write_in_progress` stuck | freshness/duration check against the 60s/180s brackets from section 5 | WARNING/FAILED |
| RTC correction stuck | `correction_in_progress` duration against the same 60s/180s brackets | WARNING/FAILED |
| Free Power operation stuck | `free_power_operation_in_progress` duration - no fixed evidence-based bracket exists for this one specifically (its firmware duration depends on the same per-write delay pattern as manual writes, ~700ms-1200ms per register across up to 5 writes) - reuses the manual-write 60s/180s brackets since it goes through the same underlying write mechanism | WARNING/FAILED |
| Snapshot pending recovery | `free_power_snapshot_valid && !free_power_active_persisted` - the firmware's own watchdog (firmware:6022) already treats this as "activation/restore was interrupted," so a health check flagging it is corroborating an already-firmware-recognised failure mode, not inventing one | WARNING while the 15s watchdog has had <4 cycles (60s) to resolve it, FAILED beyond that |
| Restore failure | `free_power_failures` counter-delta increasing specifically while `free_power_snapshot_valid` remains true after a restore attempt (i.e. the watchdog tried and the snapshot is *still* unresolved) | FAILED |
| Unresolved snapshot after reboot | Same as "snapshot pending recovery" - the persisted (`_persisted`/`_valid` suffix) flags are explicitly designed to survive a reboot (firmware comment context around `free_power_snapshot_valid`), so this is not a distinct check, just the same one evaluated immediately after a restart | WARNING/FAILED per above |
| Last write verification failed | `manual_write_failures`/`free_power_failures` counter-delta, `manual_config_last_result`/`free_power_status` text containing a failure result | WARNING (recent) / FAILED (repeated, see section 6) |
| Impossible simultaneous operation flags | `correction_in_progress && manual_write_in_progress` both true simultaneously - the firmware's own preconditions treat these as mutually exclusive everywhere (every write/correction path checks `!correction_in_progress && !manual_write_in_progress` before starting); both true at once is either a genuine firmware bug or (far more likely) a stale/torn read across two separate ESPHome API state updates. Reported as `WARNING` with an explicit "transient read inconsistency, re-check" note, never treated as proof of a bug on a single sample. | WARNING |
| Transaction state says active while source mechanism says inactive | e.g. `free_power_active_sensor.state == true` (derived from `free_power_active_persisted`) while `free_power_status` text says something inconsistent - cross-checked as a `cross_source_agreement` check between the boolean and the text-state signal | WARNING |

**No write, no automatic disarm, no automatic restore is ever
performed by any check.** Every check above is read-only by
construction (the reference engine in section 14 has no network/API
access at all, let alone a write path) - a dangerous state is reported
via reason codes and `blocks_manual_control: true`, never acted on.

**Task 006A fix - an active transaction with an unknown start time must
never evaluate HEALTHY.** The original `transaction_state` evaluation
computed `duration = 0s` whenever a transaction was reported `active`
but its start timestamp was unavailable (`active_since == None`),
which meant "something is definitely happening, but we don't know for
how long" was indistinguishable from "it just started" - and a
just-started transaction is HEALTHY by design. A concurrent write
whose age genuinely cannot be judged is exactly the kind of situation
this architecture exists to surface, not hide behind a default of
zero. `manual_write_duration`, `rtc_correction_duration`, and
`free_power_operation_duration` (the three `transaction_state` checks
that can be `active`) now report **UNKNOWN** - not HEALTHY, not a
guessed WARNING/FAILED severity either, since we genuinely do not know
whether it is newly started or badly stuck - whenever `active` is true
and `active_since` is unavailable. Because these three checks are all
in `required_control_checks()` (section 12) and declare no
non-blocking UNKNOWN outcome, this UNKNOWN correctly blocks
`manual_control_ready` by the fail-closed rule below - "we know
something is active but not for how long" must prevent a second
concurrent action exactly as a known-stuck transaction would.

## 12. Safety gate / control-readiness model

`manual_control_ready` is a derived boolean, **not** an arm switch and
**not** itself a health state - it answers "would it currently be
sensible to offer the user a manual inverter write action."

**Task 006A safety fix - FAIL CLOSED.** The original implementation
computed readiness only from whichever checks happened to be present
in a given evaluation's `check_results` - a check capable of blocking
control could simply be *absent* from that evaluation (a caller
bug, a partial signal snapshot, a not-yet-implemented HA entity) and
`manual_control_ready` would read `true` regardless, having never
"seen" the missing precondition at all. That is unacceptable for a
safety gate: **UNKNOWN, not-evaluated, and a missing safety
precondition must never mean READY.**

The fixed rule starts from the *complete, registry-derived* set of
checks capable of blocking control - `required_control_checks()`:
every check in `registry/system_health_checks.yaml` with at least one
outcome whose reason code declares `blocks_manual_control: true` in
`registry/health_reason_codes.yaml` (17 of 46 reason codes, listed in
`docs/SYSTEM_HEALTH_REASON_CODES.md`). This set is fixed by the
registry, never by what a particular signal snapshot happens to
contain. For every required check:

```
for check in required_control_checks:
    result = check_results.get(check.id)

    if result is None:
        -> BLOCKS readiness (missing_required_checks)

    elif result.state == SUPPRESSED:
        if check.suppressed_is_safe_for_control:
            -> does not block
        else:
            -> BLOCKS readiness (insufficient_evidence_checks)   # fail closed default

    elif result.state == UNKNOWN:
        if check declares a non-blocking UNKNOWN outcome
           AND that is the outcome that actually triggered:
            -> does not block                                    # explicit, registry-declared exception
        else:
            -> BLOCKS readiness (insufficient_evidence_checks)    # fail closed default

    elif result has an active outcome with blocks_manual_control: true:
        -> BLOCKS readiness (blocking_checks)

    else:
        -> does not block (HEALTHY, or a non-blocking DEGRADED/WARNING/FAILED tier)

ready = (blocking_checks == [] and missing_required_checks == [] and insufficient_evidence_checks == [])
```

No reason code is manufactured for a missing or UNKNOWN check - the
three distinct result lists (`blocking_checks`,
`missing_required_checks`, `insufficient_evidence_checks`) are the
honest signal instead, each independently inspectable by a caller/UI.
**Today, in the real registry, nothing sets
`suppressed_is_safe_for_control: true` and nothing declares a
non-blocking UNKNOWN outcome among the required checks** - both
exceptions are fully implemented and tested
(`health/tests/test_system_health.py`), but every currently-required
check fails closed with no exception in practice. The mechanism exists
for a future check where "not applicable" or "unknown, but genuinely
irrelevant" can be proven safe, not as a loophole exercised today.

Checks marked `blocks_manual_control: true` on at least one outcome
(every check in the CRITICAL-tier subsystems that represents a genuine
precondition for a safe write - not every CRITICAL-subsystem check
necessarily blocks; e.g. a Wi-Fi RSSI numeric-range warning does not
block control by itself, but `manual_write_in_progress` stuck does).

**Task 006B fix: `wifi_signal_quality` was accidentally required.**
Because `required_control_checks()` derives its required set purely
from reason-code metadata, and `wifi_signal_quality`'s only outcome
originally reused the generic `INSUFFICIENT_EVIDENCE` reason code
(`blocks_manual_control: true`, correctly used by `esphome_reachable`'s
genuine first-observation uncertainty), `wifi_signal_quality` was
silently classified as required - contradicting this very paragraph's
stated design. The fix is a dedicated, non-blocking reason code,
`WIFI_SIGNAL_UNKNOWN` (`registry/health_reason_codes.yaml`, severity
UNKNOWN, `blocks_manual_control: false`): signal-QUALITY information
being incomplete says nothing about whether the device is actually
reachable - `esphome_reachable` is the separate, dedicated check for
that, and remains required. `INSUFFICIENT_EVIDENCE` itself was left
unchanged (still blocking) so `esphome_reachable`'s fail-closed
first-observation behaviour is not weakened.

Preconditions:

- `communications`: ESPHome reachable (an unreachable device cannot
  receive any write).
- `inverter_configuration`: configuration polling healthy (a write
  needs a current raw-register cache to safely read-modify-write
  shared bitfields - see Task 005's registry for exactly which
  TOU fields require this, cited as reference only).
- `inverter_telemetry`: the inverter system state is not `alarm`/`fault`
  (text-state check on `ecco_inverter_system_state`).
- `rtc_time`: correction is not currently stuck (a stuck correction
  already blocks the firmware's own write paths, per the `!correction_in_progress`
  precondition present on every write script - the health check
  mirrors, not invents, this).
- `manual_write_system`: no write is already in progress (the firmware
  itself would reject a second write, but the health check surfaces
  *why* proactively rather than the user only discovering it via the
  `REJECTED` result text after already trying).
- `free_power`: no unresolved snapshot (`free_power_snapshot_pending_recovery`)
  and no operation currently in progress.
- `runtime_configuration`: `binary_sensor.ecco_runtime_configuration_ready`
  is true (an already-existing, pre-Task-006 HA signal, reused
  directly rather than re-implemented).

Every one of these directly mirrors an existing firmware-side
precondition (see section 1's audit and the `REJECTED`/`DEFERRED`
status-text evidence) - `manual_control_ready` is a *proactive,
explainable* surfacing of conditions the firmware already enforces
reactively, not a new safety policy. If all of them clear,
`manual_control_ready = true` - but this still never performs a write;
the eventual HA UI (section 17/18) would use it only to decide whether
to show a control as enabled or disabled/annotated.

## 13. Aggregation rules

Overall `ecco_system_health` is computed by capping each
**automatic-rollup-participating** subsystem's severity rank by its
criticality tier's ceiling, then resolving the state at the resulting
maximum rank deterministically:

```
TIER_CAP = {CRITICAL: FAILED(3), STANDARD: WARNING(2), INFORMATIONAL: DEGRADED(1)}

contributing = [s for s in all_subsystems if s.contributes_to_overall]   # section 3 - excludes
                                                                          # subsystems whose only
                                                                          # checks are diagnostic_only/
                                                                          # manual_only
capped = [(min(s.severity_rank, TIER_CAP[s.tier]), s) for s in contributing]
overall_rank = max(rank for rank, _ in capped)

# Task 006A fix: the state at overall_rank is resolved deterministically,
# never "whichever subsystem happened first" - see section 2's
# _resolve_flavor_at_rank(). A capped-down REAL finding (e.g. a STANDARD
# subsystem's FAILED capped to the WARNING band) is reported at its
# capped severity as a definite finding; a subsystem whose own state is
# UNKNOWN keeps reporting as UNKNOWN even if tier-capped to a lower rank
# - capping changes how much WEIGHT an UNKNOWN carries, never promotes
# "we don't know" into an invented definite claim.
overall_state = resolve_flavor_at_rank(
    [flavor(s) for rank, s in capped if rank == overall_rank],
    overall_rank,
)
```

(A SUPPRESSED subsystem contributes rank 0 like HEALTHY. A subsystem
with zero automatically-evaluable checks - e.g. `influx_raw` and
`influx_5m` today, whose only checks are `diagnostic_only` Flux
diagnostics - is entirely excluded from `contributing`, not merely
capped to rank 0: it cannot drag the overall state down by any amount,
permanently or otherwise, because there is no way it will ever
transition to `automatic` participation without a repository/design
change. This is what makes "all automatically-evaluable checks healthy
-> overall HEALTHY" achievable even though two checks in this registry
are permanently unverifiable - see section 3.)

This directly implements every example in the task:

- **"critical communication failure may make overall FAILED"** -
  `communications` is CRITICAL (cap = FAILED); its own FAILED rank (3)
  passes through uncapped.
- **"stale Battery Outlook may make overall DEGRADED while inverter
  monitoring is otherwise healthy"** - `battery_outlook` is
  INFORMATIONAL (cap = DEGRADED); even an internal WARNING/FAILED rank
  for that subsystem is capped to DEGRADED(1) for the overall rollup.
- **"a historical error counter should not affect current overall
  state"** - enforced one level down, inside each `failure_counter_delta`
  check (section 6): a counter with zero *recent* delta simply
  evaluates HEALTHY for that check, so it never even reaches the
  subsystem/overall rollup as a non-healthy contributor.
- **"a pending snapshot recovery may make overall WARNING/FAILED
  depending on the actual state"** - `free_power` is CRITICAL (cap =
  FAILED), so its actual computed rank (WARNING while the watchdog
  still has cycles left, FAILED once it has exhausted its reasonable
  window per section 11) passes through unmodified - "depending on the
  actual state" is exactly what an uncapped tier means.
- **"an intentionally unavailable optional subsystem may be
  SUPPRESSED"** - a subsystem whose applicability condition is false
  (e.g. `free_power` when it has never been armed/used) reports
  SUPPRESSED, contributing rank 0.
- **a CRITICAL subsystem with only UNKNOWN evidence makes overall
  UNKNOWN, not a silently-invented HEALTHY or WARNING** - e.g. if
  `inverter_telemetry` has never received a single reading (genuinely
  no evidence, distinct from a confirmed-stale reading), its rank is 2
  (UNKNOWN), uncapped for a CRITICAL subsystem, and if nothing else in
  the system has a real WARNING/FAILED at or above that rank, the
  overall state resolves to UNKNOWN via `_resolve_flavor_at_rank()`,
  not WARNING.
- **all automatically-evaluable checks healthy -> overall HEALTHY** -
  the two permanently-unverifiable checks
  (`battery_outlook_model_version`, `battery_outlook_scorer_anti_contamination`)
  and the three manual-Flux-diagnostic checks
  (`influx_raw_freshness`, `influx_5m_freshness`, `influx_history_depth`)
  are excluded from `contributing` entirely (section 3) - a perfectly
  healthy ECCO installation reports `HEALTHY`, not a permanent
  WARNING/UNKNOWN floor from checks that can never be continuously
  evaluated by design.

**Every roll-up is explainable**: the overall result carries the full
list of `(subsystem, state, reason_codes)` for every subsystem whose
rank contributed at the maximum (i.e. every subsystem "responsible"
for the overall state, not just one arbitrarily chosen worst
offender) - see `OverallHealthResult.contributing_subsystems` in
section 14.

## 14. Pure offline health-evaluation reference engine

`health/system_health.py` - zero I/O (no HA API, no network, no
Modbus, no Influx, no file mutation). Inputs are plain Python
dataclasses/dicts representing a snapshot of current signal values
(the caller - a human, a test, or eventually an HA integration -
supplies them; the engine never fetches anything itself). All
timestamps are timezone-aware (`datetime` with `tzinfo`); no function
in the module calls `datetime.now()`/`utcnow()` without an explicit
injected `now` parameter, so tests never depend on wall-clock timing.

Public surface (see the module's own docstrings for full detail):

- `evaluate_check(check_def, signal, reason_codes, now) -> CheckResult`
- `evaluate_subsystem(subsystem_id, check_results) -> SubsystemResult`
- `evaluate_overall(subsystem_results) -> OverallHealthResult`
- `required_control_checks(checks, reason_codes) -> set[str]` (section 12's registry-derived required set)
- `evaluate_control_readiness(checks, check_results, reason_codes) -> ControlReadinessResult`
  (Task 006A: now takes the full `checks` registry, not just the results
  that happen to be present, so it can fail closed on a missing required
  check - see section 12)
- `evaluate_counter_delta(check, signal, reason_codes, now) -> CheckResult` (section 6 helper)
- `evaluate_all(checks, reason_codes, signals, now) -> (check_results, subsystem_results, overall, control)` (convenience wrapper)
- `load_check_registry(path) -> dict[str, CheckDef]` / `load_reason_codes(path) -> dict[str, ReasonCode]` (thin YAML loaders - no network)

This is a **reference/test engine**, not the production HA
implementation - it exists to prove the design's logic is internally
consistent and to give the offline test suite (section 15) something
real to exercise, not to be imported by a live integration as-is.

## 15. Offline tests

`health/tests/test_system_health.py` - see the file itself for the
full scenario list, which matches every bullet in the original Task
006 section 15 (healthy baseline, communications split-block
scenarios, RTC stall/stuck/recovery, canonical agreement/skew/mismatch,
Influx raw/5m/history-depth, Battery Outlook pipeline vs. scorer vs.
not-yet-due, transaction stuck/overlap/impossible-flags, and the
aggregation-rule scenarios from section 13) **plus every Task 006A
safety-review scenario**: missing/UNKNOWN/SUPPRESSED required checks
each independently failing control readiness closed, an active
transaction with an unknown start time for all three transaction-state
checks, counter rollback/reset producing UNKNOWN rather than a false
HEALTHY, a pure-UNKNOWN critical subsystem staying UNKNOWN through
aggregation, WARNING-beats-UNKNOWN at a shared rank, a fully-healthy
automatic baseline reaching real `HEALTHY`, diagnostic-only UNKNOWN
never poisoning that baseline, and the `influx_5m`/`battery_outlook`
independence (input-history-stale-but-output-fresh and vice versa).
All synthetic - no test touches a live system, and every test passes
an explicit fixed `now`.

## 16. Health-check registry validator

`tools/validate_system_health_checks.py` - validates
`registry/system_health_checks.yaml` and
`registry/health_reason_codes.yaml` together (reason codes are their
own small registry, cross-referenced). Integrated into
`tools/validate_repo.py` exactly the way Task 005's capability
registry validator was (cited as precedent, not a dependency - the
integration code is written fresh on this branch). See the validator's
own module docstring for the full enforced-checks list; it mirrors
every bullet in the task's section 16 (duplicate ids, invalid
subsystem/state/severity, unknown check type, missing evidence,
freshness checks with no thresholds, failure-threshold <=
warning-threshold ordering, invalid/circular dependencies,
manual-control-blocking checks without a rationale, duplicate reason
codes).

**This branch validates independently of the Task 005 branch** -
`tools/validate_repo.py` on this branch has no reference to
`registry/inverter_capabilities.yaml` or
`tools/validate_capability_registry.py`; those files do not exist
here. Confirmed by running the full validator suite with only this
branch's files present (see the final report).

## 17-18. HA implementation design and dashboard design

See `docs/SYSTEM_HEALTH_HA_DESIGN.md` and
`docs/SYSTEM_HEALTH_DASHBOARD_DESIGN.md`.

## 19. Reason codes

See `docs/SYSTEM_HEALTH_REASON_CODES.md` and the machine-readable
`registry/health_reason_codes.yaml`.

## 20. Configuration-drift design

All checks are **repository-vs-repository** or
**repository-vs-live-HA-entity** comparisons - never a live file hash,
since no live file access exists in this environment or this task's
constraints.

| Check | Compares | Distinguishes |
|---|---|---|
| `firmware_ceiling_vs_runtime_config` | `VERSION.yaml current.site_profile.inverter_tou_power_ceiling_w` (repo-expected) vs. `sensor.ecco_clock_dongle_inverter_tou_power_ceiling` (live HA entity, itself sourced from the firmware substitution - see Task 005's `inverter_tou_power_ceiling_sensor`, cited as reference) | mismatch = the *deployed* firmware's substitution differs from what the repository currently expects (i.e. firmware hasn't been redeployed after a repo change, or vice versa) - reported as `CONFIGURATION_MISMATCH`, never auto-corrected |
| `charge_start_vs_tou_schedule` | `VERSION.yaml current.site_profile.live_charge_start` vs. `sensor.ecco_config_charge_start_time` | a difference could be an *intentional* live override (the site profile in `VERSION.yaml` is a point-in-time snapshot, not a live-enforced constraint) - reported as `WARNING` with explicit `intentional_override_possible: true`, never assumed to be an error |
| `battery_capacity_config` | `VERSION.yaml current.site_profile.battery_capacity_kwh` vs. `input_number.ecco_battery_model_capacity` | same "could be intentional" framing |
| `round_trip_efficiency_config` | `VERSION.yaml current.site_profile.round_trip_efficiency_percent` vs. `input_number.ecco_round_trip_efficiency` | same |
| `deployment_manifest_paths_exist` | every `source:` path in `deployment/ha-manifest.yaml` and every path-shaped value in `VERSION.yaml`'s `current:` block resolves to a real file in this repository | this is the one check that reuses `tools/validate_repo.py`'s *existing* `validate_version_references()`/`validate_deployment_sources()` logic directly (already implemented, pre-Task-006) rather than re-implementing it - the health registry entry documents this reuse explicitly rather than duplicating the check |

Deployment file hashes and "deployed-vs-repository" comparisons are
explicitly **not implemented** - no safe, live-access-free way exists
to know what is actually running on a given installation. This gap is
documented, not filled with a guess.

## 21. Performance/noise control

- No check requires more than the Influx read-cadence already
  established by the existing HA packages (30-minute/30-day/7-day
  windows) - no new per-second or per-minute Influx query is
  introduced; the ad-hoc diagnostics (section 9) are explicitly
  manual/on-demand, never scheduled.
- Freshness brackets throughout section 5 use multi-cycle margins
  (6x-12x the expected interval) specifically to avoid flapping on a
  single missed poll.
- Counter-delta checks (section 6) require a **window** before
  producing anything other than UNKNOWN, preventing a check from firing
  immediately after a reboot when no baseline yet exists.
- "Recovery confirmation" is built into the counter-delta model
  directly (a WARNING-not-FAILED "recovered" outcome) rather than
  needing a separate hysteresis layer bolted on afterward.
- The reference engine has no polling loop of its own - it evaluates
  a single snapshot when called. Update cadence, hysteresis-across-calls,
  and notification delivery are HA-side implementation concerns,
  design-only in `docs/SYSTEM_HEALTH_HA_DESIGN.md` (no notification
  automation is implemented in this task, per the task's explicit
  scope limit).

## 22. Documentation map

| Document | Covers |
|---|---|
| This file | architecture, state/subsystem model, freshness evidence, aggregation, counter-delta, comms/canonical/Influx/Battery-Outlook/transaction health, control-readiness, config drift, performance |
| `docs/SYSTEM_HEALTH_REASON_CODES.md` | reason-code catalog |
| `docs/SYSTEM_HEALTH_HA_DESIGN.md` | HA entity plan, the inert reference package, live-validation checklist |
| `docs/SYSTEM_HEALTH_DASHBOARD_DESIGN.md` | dashboard/panel design, troubleshooting flow |

## 23. Status legend used throughout

- **IMPLEMENTED OFFLINE**: real code exists in this repository and its
  offline tests pass (`health/system_health.py`,
  `tools/validate_system_health_checks.py`, the two registries).
- **DESIGNED**: specified in prose/tables here or in the companion
  docs, not implemented as runnable code (e.g. the eventual HA
  entities beyond the one inert reference package).
- **PHASE 1 LIVE-CANDIDATE**: the deliberately partial, read-only HA package
  is prepared for controlled deployment and live validation. This status does
  not imply the full 43-check architecture or final control-readiness gate is
  implemented.
- **LIVE-PROVEN**: reserved for a concrete signal/entity/check that has been
  exercised against the real ECCO installation and had its observed result
  recorded.
- **NOT LIVE-PROVEN**: used where a reader might otherwise assume proof exists
  (for example, the full-design freshness thresholds remain evidence-derived
  until they are exercised live).
- **NOT IMPLEMENTED**: explicitly out of scope or deliberately not
  built (automatic recovery, notification automations, any write
  path, the `hash_match` check type, live deployed-file hashing).


### Phase 3 live proof - 2026-09-19

The corrected Phase 3 Home Assistant package was deployed through the proven SSH deployment path. Upload and post-install SHA256 verification passed, `ha core check` passed, Home Assistant was explicitly restarted, and a fresh startup-log search showed no `ecco_system_health` or template errors.

All five Phase 3 subsystem sensors registered and evaluated `HEALTHY` on the live idle installation: `sensor.ecco_health_manual_write_system`, `sensor.ecco_health_rtc`, `sensor.ecco_health_free_power`, `sensor.ecco_health_configuration`, and `sensor.ecco_health_inverter_telemetry`. Their attributes remained explicitly partial and non-authoritative for control.

Developer Tools also confirmed that the reserved final `binary_sensor.ecco_manual_control_ready` does not exist. Only the deliberately verbose PARTIAL / REFERENCE ONLY readiness entity is present.

The first live restart exposed a Home Assistant template-attribute schema issue: literal YAML lists are invalid for template sensor attributes. The list-valued diagnostic attributes were converted to Jinja-rendered list expressions, a regression check was added, and the corrected package then passed live validation.

This proof covers registration, idle evaluation, schema validity, and fail-closed absence of the final gate. It does not yet prove the 60s/180s duration transitions during a real manual-write, RTC-correction, or Free Power operation, and the documented `last_changed` restart/reconnect limitation remains.
