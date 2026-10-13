# Review: scheduled Dump to Grid start reliability (12 October 2026)

**Status:** latent defects proven from the code and in the offline model; correction (post-export entry `dgs1`) validated offline,
not deployed. No scheduled Dump to Grid start has failed in practice: the one scheduled start in recorder history (6 Oct 18:00 BST)
started on its first press.
**Trigger:** the 11 Oct scheduled Free Power incident (`2026-10-11-scheduled-free-power-start.md`, fixed by `fps1`). This review
checks whether Dump to Grid has the same latent problem rather than assuming it.

## What was examined

- The firmware start procedure: script `start_dump_to_grid_override` in `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`
  (its gate condition, its refusal branch, its `mode: single`), the `START DUMP TO GRID - NOW` button and the `Dump to Grid Write
  Enable` switch (`restore_mode: ALWAYS_OFF`; turned off ONLY by the start gate, in both of its branches).
- The Home Assistant scheduling layer: `home-assistant/packages/ecco_dump_to_grid_schedule.yaml` as of `fps1`.
- Recorder history of the one scheduled start since 4 Oct (read-only Home Assistant history GET).

## Evidence: the real scheduled start, 6 Oct 2026 18:00 BST (Home Assistant receive times, UTC)

| Time | Event |
|---|---|
| 17:00:00.005 | Schedule fires: `STARTING - 8000W for 60 min, Stop SOC 50%` |
| 17:00:01.164 | Dump to Grid Write Enable on |
| 17:00:02.019 | START pressed (the package's first press, about +2 s: the same instant the old Free Power package pressed) |
| 17:00:02.136 | Gate passed: write enable off; 02.137 `STARTING - taking fresh inverter snapshot`; 02.140 operation in progress on |
| 17:00:06.207 | `ACTIVE - VERIFIED OK`; operation in progress off; 06.210 `STARTED OK` recorded |

The gate answered 0.117 s after the press and the start transaction took 4.07 s; the simulator uses both figures. The press
happened to miss the telemetry poll that day: the poll is boot-phased and drifts about 2.4 s a day, so the same HH:MM:02 press lands
at a different point of the 10 s cycle on different days.

## Findings

The Dump to Grid start gate is the same shape as Free Power's: ONE condition. Its refusal branch publishes exactly one `REJECTED`
text (the first matching reason, in a fixed order) and turns the write enable off; it performs no Modbus I/O, counts nothing and
writes nothing durable. Its LAST test is the bus: it refuses while any Modbus frame is queued or awaiting its reply (in ESPHome
2026.8 also during the 600 ms turnaround). So a refusal is always safe to retry, and the bus refusal can only be seen when every
other interlock passes.

| # | Defect in the package as of fps1 | How established | Severity |
|---|---|---|---|
| D1 | Press at about +2 s and one retry at about +35 s: the timing fps1 proved locked to the 10 s telemetry poll. Both presses refused (bus busy), nothing written, the schedule disarms itself, no alert. | Offline model, every poll phase x three press delays: the old package fails to start in **8.6 %** of 360 runs (31 of 360). | **High** (the 11 Oct Free Power failure mode; silent). |
| D2 | The retry fires after ANY non-start, including a start transaction that began and failed with nothing written: a second full start transaction (a second snapshot capture) runs. | Code + model (`capture_failed`). The firmware's own interlocks still hold (each transaction is complete and fail-closed). | Medium (violates "never retry after a begun transaction"). |
| D3 | After a begun transaction failed with its snapshot retained, the retry is refused (`saved snapshot pending`) and the recorded result names that refusal, hiding the real `START FAILED - verify mismatch ...` reason. No alert. | Code + model (`verify_failed`). | Medium (misleading record; the snapshot itself is safe). |
| D4 | If a start transaction is still running at +35 s, the retry re-arms the write enable and presses; the firmware's single-mode script DROPS the press (no status, the write enable is left as it is). The write enable then stays ON after the session and a later stray START press starts an unplanned session without any arm step. | Code + model with an assumed 40 s transaction. **Theoretical**: the measured transaction is 4 s and any Modbus operation that times out (3 s) aborts the transaction, so a transaction longer than ~33 s is very unlikely. | Low probability, safety-relevant (arm protection bypassed). |
| D5 | The dongle offline at the start instant: Home Assistant shows `unavailable`, not `off`, so the offline check does not match; the run stages into an unavailable dongle, Home Assistant raises, the run and the fire automation abort; the schedule stays ARMED showing `STARTING`, nothing starts, no alert. | Model. **Assumption** (stated in the model): the ESPHome integration raises a service error for a call to a disconnected device. | Medium. |
| D6 | A momentary `off` of telemetry / configuration online at the start instant gives `BLOCKED` for good: no wait, no retry, no alert. | Code + model. | Medium. |
| D7 | No missed-trigger watchdog and no alert anywhere (a lost start trigger, a restart during the window, a failed start: all silent). | Code + model. | Medium. |
| D8 | A late start (the +35 s retry) runs its full duration past the authorised window end. | Model. | Low (about 35 s). |

What was checked and is NOT a defect: the firmware gate itself (fail-closed, correct order, no side effect on refusal); the
arm validation (power, Stop SOC, future start, overlap with an armed Free Power schedule, TOU charging slots); the cancel script.

## Start-refusal classes (the firmware gate's own texts, verbatim, in its order)

| Refusal | Class | Correction's behaviour |
|---|---|---|
| RECOVERY BLOCKED (recovery marker untrusted) | persistent | FAILED at once, alert |
| Dump to Grid already active | persistent | FAILED, or STARTED if Dump is active |
| saved snapshot pending restore/recovery | persistent | FAILED at once, alert |
| another inverter write is active | transient | retried |
| RTC correction currently active | transient | retried (the 90 s breaker bounds it) |
| Free Power override/recovery owns inverter settings | persistent | FAILED at once, alert (a Free Power transaction visible beforehand is waited for, never pressed into) |
| Register 244 proof transaction awaiting restoration | persistent | FAILED at once, alert |
| inverter configuration offline | transient | retried |
| valid NTP time required for automatic end | transient | retried |
| plausible live battery voltage required | transient | retried |
| plausible live battery SOC required | transient | retried |
| battery SOC telemetry is stale | transient | retried (an RTC correction pauses the poll for up to about 50 s) |
| Read-Only Configuration Polling must be on | persistent (owner setting) | FAILED at once, alert |
| no fresh inverter configuration readback yet | transient | retried |
| grid CT telemetry is not fresh/plausible | transient | retried |
| TOU slot schedule unreadable | persistent | FAILED at once, alert |
| lease window overlaps TOU slot N (charge source set) | persistent | FAILED at once, alert |
| battery SOC already at or below the requested Stop SOC | persistent | FAILED at once, alert (also named by the readiness check) |
| export power / Stop SOC / duration outside the safe range | persistent | FAILED at once, alert (cannot occur: all three are confirmed before the press) |
| arm Dump to Grid Write Enable first | transient | retried |
| Modbus bus busy with another transaction | transient | retried |
| safety precondition failed (generic) | persistent | FAILED at once, alert |

A refusal is only ever believed when this press was ANSWERED: the switch was seen ON just before the press and is then seen OFF.
Every other outcome is either a begun transaction (operation in progress, active, or the switch off with a non-REJECTED status) or
no answer at all.

## The correction (`dgs1`): Home Assistant scheduling layer only

The same design as `fps1`, adapted to Dump to Grid's three staged values and its larger set of refusals:

- **Bounded, uneven retries of transient gate refusals only.** About 6 / 7 / 9 / 10.5 s apart for the first eight attempts, then
  16-21 s; never a multiple of the 10 s poll. Each run retries for at most 10 minutes and never in the last 30 s of the window.
- **Never a retry once a start transaction began.** Its own outcome is awaited (up to 2 min); a failure is reported with the
  firmware's text and alerted; the firmware owns the snapshot and restore.
- **No retry after an ambiguous outcome.** If a press gets no answer, the write enable is turned off and SEEN off, and the gate-pass
  counter is compared 35 s later; only an unchanged counter with nothing in progress, active or pending restore allows a retry.
- **Nothing staged or pressed while another write is in progress** (Dump, Free Power or manual), while the dongle is offline, or
  after a cancel (or a cancel and re-arm). The press waits until the dongle confirms the arm and all three staged values (export
  power, Stop SOC, duration).
- **The write enable always ends off**, also after a restart between an arm and its press.
- **The authorised window is kept:** the staged duration is min(requested, floor((window end - now + 20 s) / 60 s)); an on-time
  start keeps its full duration; a late start ends within about a minute of the window end.
- **Visible failure reporting:** a persistent notification `ecco_dump_to_grid_schedule` for every failure, BLOCKED or miss (cleared
  by a later start or a new arm); a readiness alert `ecco_dump_to_grid_schedule_readiness` 5 minutes before naming each blocker
  (offline, NTP, Dump active or snapshot pending, Free Power owning the inverter, battery SOC at or below the Stop SOC).
- **Missed-start detection:** a watchdog trigger 3 minutes after the start (still armed, armed before the start, no run in
  progress) starts the rest of the window and alerts; restart recovery waits for the dongle and either records a running session,
  recovers the rest of the window with an alert, or records MISSED with an alert.
- **Status:** ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE.
- Unchanged: helpers, the cancel script, the arm validation (apart from clearing the two alerts on a successful arm), the status
  sensor's attributes, every control entity used, and the absence of any register, Modbus or ESPHome-action service.

Residual behaviours (accepted, documented):

- A Free Power transaction that begins in the second between the readiness look and the press is refused with the same text as an
  active Free Power lease and is reported FAILED (not retried): conservative.
- If Home Assistant's view stalls after a press that passed, the run may stage the same values again into the running transaction
  before it learns the outcome; the press that follows is dropped by the firmware and the run reports the start once the view
  recovers (`STARTED OK - ... could not confirm the start as its own`). Never two transactions.
- A saved Dump snapshot pending restore at the start instant fails the run at once (the firmware's watchdog restores it within
  seconds, but the schedule does not wait on recovery).

## Firmware

**No ESP32 firmware change is required.** The gate is correct and fail-closed; every defect is in the Home Assistant scheduling
layer. Two optional firmware improvements were considered and NOT made: publishing an explicit `REJECTED - start already running`
when the single-mode script drops a press (the package now detects a dropped press without it), and turning the write enable off
when a lease ends (the package now always ends with it off).

## Validation (offline)

`home-assistant/tests/test_ecco_dump_to_grid_schedule_reliability.py` runs the REAL package YAML (and the package as of `fps1`, undone
exactly by the PEX layer) under the FPS1 interpreter with the Dump to Grid model (`home-assistant/tests/_ha_dump_sim.py`): the static
shape and firmware cross-checks, D1-D8 reproduced on the old package, the fix on the same inputs, every poll phase, transient and
persistent refusals, begun transactions, the window, the watchdog, readiness, restarts, status, review cases (cancel, re-arm, stalls,
races with the owner's own START, slow transactions, Free Power transactions, service errors, the longest texts) and a mutation
battery. It proves the package's control flow against a model; it proves nothing about a live Home Assistant, the dongle or the
inverter.

## Deployment

Package-only (one file), like `fps1`: `automation.reload` + `script.reload` load the new start script and automations; the
status sensor's new STARTING / FAILED / COMPLETED states need a template reload or the next restart. No firmware, no inverter
write, no dashboard change. A live test needs separate authorisation (a short low-power scheduled session whose first press is
timed into a telemetry read).
