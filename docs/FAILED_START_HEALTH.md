# Failed-start health warning (FSW1)

`sensor.ecco_health_start_failures` raises a structured, time-limited WARNING when a Free Power or Dump to Grid **start** fails after
the firmware's start gate has passed. It is observational only. It never starts, cancels, restores, arms or stages anything, and it
never writes to the inverter. Status: **offline-validated, not live-proven.**

## Why it exists

A start that fails before it writes anything (for example the fresh snapshot cannot be completed) leaves the recovery state at `NONE`,
so nothing on the Overview reported it and the hero could say SYSTEMS NOMINAL. The recovery-state sensors are published only at boot,
review and accept, so they are not a live signal either.

## What it reads

Four existing firmware counters, each published every 30 s and counted since boot (RAM only, reset to 0 by every dongle boot):

| Feature | Attempts | Successes |
|---|---|---|
| Free Power | `sensor.ecco_clock_dongle_free_power_start_attempts_since_boot` | `sensor.ecco_clock_dongle_free_power_start_successes_since_boot` |
| Dump to Grid | `sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot` | `sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot` |

- An attempt is counted **once, after every start gate has passed** (a refusal `REJECTED - ...` is never counted).
- A success is counted **once, only when the start verified ACTIVE** (Dump to Grid: after the lease is durably active).
- Unresolved starts = attempts - successes. A failed start raises it by one and it stays up.
- The failures-since-boot counters are **not** used: they also count failed restores, force-restores and lockouts.
- The free-text status never decides anything; it is shown as information only.

## Detection rule

A failure is confirmed only when unresolved starts have **risen** above the stored baseline and all four counters have then been
quiet for **240 s**. Then, for 1800 s after the failed attempt (the attempts counter's change time), the sensor is `WARNING` with
`FREE_POWER_START_FAILED` and/or `DUMP_TO_GRID_START_FAILED`. Each feature is independent; each further failure restarts that
feature's window.

A merely nonzero since-boot count is never a failure. These only set the baseline: the first values after a Home Assistant start or
a template reload, a reconnection after unavailable counters, a counter reset (dongle reboot), and an inconsistent pair
(successes above attempts). Unreadable counters are `UNKNOWN`, never `HEALTHY`; an open warning window survives it and still expires on
time.

## What it detects, and what it does not

| Situation | Result |
|---|---|
| Start passed the gate, then failed (snapshot, durable commit, activation write or verification) | **Detected**: WARNING 240 s after the last counter change (240-270 s after the firmware counted the attempt) |
| Same, and it then entered recovery | **Detected** (counts both; it cannot isolate recovery state `NONE`) |
| Start refused at the gate (bus busy, RTC correction, another write, configuration offline, ...) | Not counted, **not detected**. A gate refusal writes nothing. The scheduler's own alert covers it (see below) |
| Failed start while the counters are unreadable (dongle offline, API down, Home Assistant down) | **Not observed**; the reconnection only sets a new baseline, a warning is never fabricated from old data |
| Dongle reboot mid-start | Counters reset to 0: not observed, nothing fabricated. The firmware's boot review and recovery state own this case |
| Owner aborts or cancels a start in flight | Counts as an unresolved attempt: WARNING (the start did not complete) |
| Failed start followed by a successful retry | Still a failure (WARNING for its window) |
| Link silently lost, counters stale but available | No warning if the loss is shorter than the settle (see timing contract) |
| Success published before its attempt (independent 30 s timers) | No false failure |

## Timing contract behind the 240 s settle

The settle must be longer than the longest time a **healthy** start can look unresolved, plus the time Home Assistant needs to notice a
silently lost link.

1. **Firmware.** Between the attempt counter increment and the success counter increment a start script runs only bounded
   `wait_until` steps of 3000 ms: at most 9 for Free Power (27 s) and 7 for Dump to Grid (21 s); no fixed delay, no script call. The
   offline suite checks this against the firmware source and fails if a wait, delay or timeout is added.
2. **Publishing.** Each counter has its own 30 s timer, so Home Assistant sees the success at most 30 s after the firmware counted it:
   a visible attempt to success gap of at most 57 s (Free Power) or 51 s (Dump to Grid).
3. **Silent link loss.** The ESPHome client in Home Assistant (aioesphomeapi 46.2.0 is the version pinned by Home Assistant 2026.9.4;
   the running instance reported 2026.9.4 on 2026-10-13) pings every 20 s and closes the connection 90 s (4.5 x 20 s) after an
   unanswered ping, so counters can stay available but stale for up to 110 s after the last message.
4. **Budget.** 57 + 110 = 167 s, below 240 s (margin 73 s).

**These are assumptions about the firmware and the Home Assistant version, and they must be re-checked before every deployment:**
(a) re-run the firmware timing check (`home-assistant/tests/test_ecco_start_failure_alert.py` section [1]) after any firmware change
to the two start scripts; (b) read the live Home Assistant version and its `aioesphomeapi` pin (`homeassistant/components/esphome/manifest.json`
of that version) and confirm the keep-alive constants `KEEP_ALIVE_FREQUENCY` and `KEEP_ALIVE_TIMEOUT_RATIO`. The link-loss bound is
`KEEP_ALIVE_FREQUENCY x (1 + KEEP_ALIVE_TIMEOUT_RATIO)`; the settle must stay above `visible gap + that bound`.

## Scope boundaries (explicit)

- **Firmware gate refusals never increment these counters.** The attempt counter is incremented only after every start gate has
  passed, so a start refused at the gate (bus busy, RTC correction, another write, configuration offline, snapshot pending, ...)
  changes nothing here. FSW1 neither detects nor reports it; the scheduler's own alert does (Free Power: FPS1).
- **Scheduler reliability is a separate layer.** The scheduled Free Power (fps1) and scheduled Dump to Grid (dgs1) packages retry
  transient gate refusals and raise their own persistent notifications. FSW1 changes neither package; it covers *transactions* that
  passed the gate and then failed, for both features.
- **No reserve or limit is read or changed.** FSW1 does not touch the minimum-reserve helper, Stop SOC, grid charge limits or any
  schedule helper.

## Compatibility with scheduled Free Power (FPS1)

FPS1 retries only transient **gate refusals**, which are not counted, so retries never change the counters. It never retries once a
start transaction began, and it raises its own persistent notification for every failure. The two are complementary: FPS1 alerts at
once, FSW1 raises the health warning 4 minutes later and keeps it visible on the Overview for 30 minutes. FSW1 reads the attempts and
successes counters only; FPS1 reads the attempts counter. Neither writes to the other's entities. The offline suite drives the real FPS1
package against the dongle model (every poll phase, transient and persistent refusals, failed transactions, dongle outages and API
stalls) and evaluates FSW1 on the counters that produce.

**Dump to Grid (dgs1).** The same counters and the same rule apply, and the scheduled Dump to Grid package (dgs1) has the same
shape as fps1: bounded retries of a transient gate refusal only, never a retry once a start transaction began, a persistent
notification for every failure. A gate refusal there is not counted and is reported by dgs1's own alert, never by FSW1. The offline suite
drives the real dgs1 package against its dongle model (every poll phase, transient and persistent refusals, failed transactions with
and without a retained snapshot, dongle outages and API stalls) and evaluates FSW1 on the counters that produce.

## Overview hero

The hero reads the sensor's `reason_codes`, never its text. A confirmed failed start raises ATTENTION with its own subline and a
START FAILED pill. Every existing reason keeps its subline and priority, including STATUS PARTIAL first. The sensor is not
in the hero's `required` list, so a missing or unavailable sensor stays quiet.

## Safety statement

Template only: no service call, no action, no automation, no script, no button, no switch, no number, no notification, no helper. The
frozen package tests reject `service:`, `action:`, `automation:`, `esphome.` and `button.press`. Zero firmware, Modbus or deployment
change. Reading four sensors cannot start, cancel or restore an inverter session.

## Deployment

1. **Package** `home-assistant/packages/ecco_system_health.yaml`: the deployment manifest lists it as `restart_required: true`. A
   template reload (`template.reload`) also loads it, but that reload is global (it re-creates every ECCO template entity) and a
   reload skips the attribute restore, so a reload of an *existing* sensor loses the open warning window and baseline. For the first
   deployment the sensor is new, so nothing is lost. Decide restart or template reload with the owner; never during a live start or
   schedule window.
2. **Dashboard** `home-assistant/dashboards/ecco_pro.yaml`: see "Dashboard re-targeting" below. Deploy after the package; the hero
   tolerates the sensor being absent, so either order is safe.
3. No firmware change, no OTA, no helper change, no automation or script reload.

### Sharing one controlled template reload with FE-1 stage A

FE-1 stage A (the new template package `ecco_battery_runtime.yaml`) also needs `template.reload` (or a restart). FSW1 is template-only
as well, so **one reload loads both**: install both package files first, then reload once. Nothing in FSW1 needs its own reload.

- **One baseline snapshot, taken before anything is installed:** the states and attributes of all ECCO template entities. FE-1's
  published expectation is 109 before and 111 after its two sensors; FSW1 adds one more, so **109 before, 112 after both**.
- **Same acceptance timing:** snapshot before, then +15 s and +90 s after the reload. Natural state churn is expected between
  snapshots; only the three new sensors may appear and none of the existing 109 may disappear or stay `unavailable`.
- **FSW1 specific checks at +15 s and +90 s:** `sensor.ecco_health_start_failures` is `HEALTHY`, `reason_codes` is `[]`, both
  `*_unresolved_baseline` attributes equal the live attempts minus successes, `*_failures_observed` is `0`.
- **Added exposure from FSW1: none.** The reload already re-creates every template entity, including the existing trigger-based
  ones that lose their restored attributes; FSW1 only adds one more entity that starts from a fresh baseline.
- **Rollback is shared too:** back up the live `ecco_system_health.yaml` (and note the FE-1 file's absence) before installing, with the
  same backup folder. Rolling back both = restore the health package, delete the FE-1 package file, reload once. Rolling back
  FSW1 alone = restore the health package, reload once (this re-creates FE-1's sensors as well).
- **Preconditions:** the live `ecco_system_health.yaml` must equal the repository's pre-FSW1 render before it is overwritten (compare
  hashes modulo line endings), no start or schedule window is running or imminent, and the owner supervises the reload.

### Dashboard re-targeting (live Overview V2.1)

The live dashboard is Overview V2.1 (`dev/overview-v2-1-ovw2`, `5f3b885`), which is not public main. **Do not overwrite it with this
repository's dashboard.** The FSW1 hero change is five small edits to the status hero's JavaScript; each edit's "before" text occurs
exactly once in the V2.1 dashboard (checked), so they apply verbatim:

1. after `const fb = get('sensor.ecco_..._status');` (the existing recovery-status read) add the `failedStartState` /
   `failedStartCodes` / `failedStartText` / `freeStartFailed` / `dumpStartFailed` / `startFailed` constants (the sensor is read,
   never added to `required`);
2. after `const busy = manualBusy || rtcBusy || ... || dumpActive;` add `const attention = hardAttention || startFailed;` and
   `startFailSubline`;
3. change `} else if (hardAttention) {` to `} else if (attention) {`;
4. change the subline to `hardAttention ? 'A monitored subsystem needs checking' : startFailSubline`;
5. change `const txChip = chipState(...)` to `startFailed ? ['START FAILED', 'warn'] : chipState(...)`.

The exact pairs are `DASHBOARD_EDITS` in `registry/tests/_fsw1_scope.py`. Applying them to V2.1 is a separate, reviewed change: it needs
V2.1's own PEX re-seal (V2.1 and FE-1 both edit the dashboard and the version file), a dashboard version bump and a hero re-test on
the V2.1 text. Until then the sensor, the registry checks and the reason codes work without the hero change; only the Overview
banner does not show the warning.

## Rollback

Remove the new sensor block (restore the previous `ecco_system_health.yaml`) and reload/restart as for deployment; redeploy the previous
dashboard (or simply leave the live V2.1 dashboard in place, which never contained the hero change). The sensor's registry entry stays
as an orphaned `unavailable` entity until it is deleted in the entity registry. Nothing on the dongle or the inverter changes in either
direction.

## Live acceptance criteria (passive; no failed start is ever provoked)

1. After loading: `sensor.ecco_health_start_failures` exists and is `HEALTHY`; `reason_codes` is `[]`; for each feature
   `*_unresolved_baseline` equals the live attempts minus successes and `*_failures_observed` is `0`.
2. Once the hero change is deployed: the Overview shows no start-failure ATTENTION and no START FAILED pill.
3. After a Home Assistant restart: still `HEALTHY`, `failures_observed` unchanged (a nonzero live count is not a failure).
4. During a natural dongle disconnect or reboot: `UNKNOWN` while the counters are unavailable, then `HEALTHY` with a new baseline and
   no `WARNING`.
5. After a natural successful start (scheduled or manual): attempts +1 and successes +1; record the largest visible attempt to success gap
   from history and confirm it is at most 57 s; no `WARNING`.
6. Re-confirm the live Home Assistant version and its `aioesphomeapi` keep-alive constants against the timing contract.
7. If a genuine failed start ever occurs: `WARNING` with the matching code 240-270 s after its attempt, the hero (once deployed) shows
   ATTENTION and the START FAILED pill, and it clears 1800 s after the attempt. FPS1's own notification arrives first.

Do not inject counter states with the Developer Tools: FPS1 reads the attempts counter.
