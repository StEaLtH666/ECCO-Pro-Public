# Incident: scheduled Free Power did not start (11 October 2026)

**Status:** root cause proven; correction (post-export entry `fps1`) validated offline, not yet deployed.
**Impact:** the 11:00-13:00 BST scheduled Free Power session did not start. The owner noticed by looking and started Free Power
manually at 11:03:49 (about 4 minutes of the free window lost); its automatic end was 13:03:53, so the owner ended it by hand
at 12:59:30 (restore verified 12:59:48). No inverter write was made by the failed schedule; no safety interlock or recovery
state was involved.

## Timeline (BST, Home Assistant receive times)

| Time | Event |
|---|---|
| 10 Oct 09:29:58 | Scheduled Free Power armed: 11 Oct 11:00, 120 min, 8000 W |
| 11:00:00.001 | Schedule fires: `STARTING - 8000W for 120 min` |
| 11:00:01.275 | Free Power Write Enable on |
| 11:00:02.012 | START pressed (attempt 1) |
| 11:00:02.708 | Firmware: `REJECTED - Modbus bus busy with another transaction; try again shortly`; Write Enable off. Telemetry block 59-116 data arrives in the same batch (11:00:02.710) |
| 11:00:34.248 | Write Enable on (attempt 2, the one built-in retry after 20 s + 12 s) |
| 11:00:35.026 | START pressed (attempt 2) |
| 11:00:35.176 | Write Enable off (same refusal, identical text, so no new status state). Telemetry block 150-196 data arrives at 11:00:35.169-35.175 |
| 11:00:55.039 | `FAILED TO START - REJECTED - Modbus bus busy ...`; the schedule disarms itself; status `IDLE`. **No alert** |
| 11:02:48-11:03:00 | A routine RTC correction (unrelated; after the failure) |
| 11:03:49-11:03:58 | The owner's manual "Free Power now": accepted, `ACTIVE - VERIFIED OK`, automatic end 13:03:53 |
| 12:59:30-12:59:48 | The owner ends it by hand; Free Power Active off 12:59:36.954; restore success counted 12:59:48 |

Facts (from the Home Assistant history): no RTC correction, manual write or other Free Power / Dump operation was running at
11:00; Start Attempts stayed at 0 for both refusals (the counter only counts presses that pass the gate); Free Power Failures
stayed at 0; nothing was written.

## Root cause

1. **The firmware start gate is fail-closed on a busy bus, by design.** It refuses at once if a Modbus frame is queued or awaiting
   its reply. In ESPHome 2026.8 `tx_blocked()` also stays true for the 600 ms turnaround after each reply.
2. **The routine telemetry poll keeps the bus busy about 20 % of the time.** Every 10 s it reads block 59-116 and, 2.5 s later,
   block 150-196; each makes the bus look busy for about 0.75 s. The configuration poll and the inverter clock read add more once a
   minute. Measured on 11 Oct: busy about 2.38-3.15 s and 4.88-5.62 s into each 10 s cycle, 11.7 s per minute in all.
3. **The schedule's timing was locked to that cycle.** It pressed about 2 s after the start and retried exactly once about 33 s
   later (33 mod 10 = 3). The poll is boot-phased (it drifts about 2.4 s a day), so on a given day every press at HH:00:02 lands at
   the same point of the cycle. On 11 Oct the first press (handled about 0.6 s after it was sent) fell in block 59-116 and the retry
   in block 150-196's turnaround.
4. **The failure was silent.** The package wrote `FAILED TO START` to a text helper and disarmed. No notification, health check
   or status state flagged it; the failed-start health work (fsw1) cannot see a gate refusal either, because nothing is counted.

**Preventable: yes.** Offline, over every poll phase and press-handling delay, the old two-press policy fails about 6 % of
scheduled starts (about one in seventeen); the corrected package fails none.

## Correction (fps1, Home Assistant only)

`home-assistant/packages/ecco_free_power_schedule.yaml`:

- **Bounded retries, only where proven safe.** A refusal AT THE GATE for a transient reason (bus busy, RTC correction active,
  another inverter write active, configuration offline) is retried. A gate refusal has no side effects: one status text and the
  write enable turned off; no Modbus I/O, no counter, no durable write, no lock. Every retry re-arms and the firmware re-checks
  every interlock. Spacing is uneven (about 6-10 s for the first eight attempts, then about 16-21 s), so it never locks to the poll.
- **Never after a transaction began.** If the gate passed (Operation In Progress or Active seen), the package waits for the
  firmware's own verified outcome and never presses again; on failure the firmware restores its saved snapshot itself.
- **Persistent refusals stop at once** (recovery blocked, already active, snapshot pending restore, register 244 proof pending,
  Dump to Grid owns the settings). NTP, live battery voltage and the arm itself are treated as transient (no side effect).
- **Every answer is proven to belong to this press.** The package presses only after it has seen the write enable ON, and
  counts a refusal only when it then sees the firmware turn it OFF (ESPHome does not re-send an identical status text, so the
  text alone cannot prove freshness). A press with no answer is never simply retried: the package disarms, sees the switch
  go off, waits for the firmware's gate-pass counter (`free_power_start_attempts_since_boot`, published every 30 s) and
  retries only if it did not move and nothing is in progress, active or pending restore. Otherwise the outcome is reported
  as unconfirmed.
- **Cancel wins.** A run records when it began; turning the schedule off - or off and on again for another time - after
  that ends the run before the next press (checked at every attempt and again just before the press). A schedule re-armed
  for another time is never disarmed by the run that is ending.
- **The limit on every attempt.** A request above the effective grid charge limit is never staged, even if the limit was
  lowered while the dongle was offline; the press waits until the dongle confirms the arm and both staged values.
- **Nothing is staged into someone else's transaction:** while a Free Power or manual write is in progress, or the dongle or
  the effective-limit sensor is unavailable, the package waits instead of staging or pressing.
- **Never silent:** dongle service calls continue on error, every result text fits the 255-character helper, the write
  enable always ends off, and any run that ends without STARTED / CANCELLED raises the alert.
- **Positive confirmation:** success only when Free Power Active turns on.
- **The authorised window:** no attempt after start + 10 minutes or in the window's last 30 s; the staged duration is
  min(requested, floor((window end - now + 20 s) / 60 s)), so an on-time start keeps its full duration and a late start ends
  within about a minute of the window end. Nothing is ever started after the window. Each run (on time, watchdog or restart
  recovery) retries for at most 10 minutes.
- **Offline dongle:** while telemetry or configuration is offline nothing is pressed; the package waits (bounded).
- **Readiness check** 5 minutes before the start and **missed-trigger watchdog** 3 minutes after it (template triggers on the
  existing fire automation; the helper, script and automation counts are unchanged). The watchdog recovers a start that never ran.
- **Restart recovery** waits (bounded) for the dongle to reconnect before judging, records a session that is already running,
  leaves an on-time start that is already retrying alone, and turns a write enable left on by the restart off.
- The readiness alert has its own notification id and is raised only for a schedule the arm validation accepted; the
  watchdog only counts a schedule that was armed before its start time.
- **Alerts:** a persistent notification for every failure, missed start, restart recovery and not-ready readiness check, naming
  the reason, whether anything was written, and what to do; a later success clears it.
- **Status:** `sensor.ecco_free_power_schedule_status` adds STARTING, FAILED and COMPLETED to ACTIVE / ARMED / IDLE, so the
  Overview "Scheduled sessions" row shows the outcome.

Firmware is unchanged and needs no change: the gate behaved correctly. A bounded wait-for-quiet-bus in the start script is a
possible later defence in depth (offline assessment: safe with `wait_until` before the gate), but it needs an OTA and is not
required by this incident.

## Not covered / follow-ups

- Residual, bounded behaviours found in review and left as they are (each errs on the safe side):
  - a schedule re-armed for a time that arrives while the previous run is still finishing is started by the watchdog, about
    3 minutes late, with a "missed" alert;
  - a plain cancel does not dismiss an open "not ready" alert (re-arming or a later success does);
  - for about 20 s to 3 minutes after a Home Assistant restart, startup recovery turns off a Free Power write enable that the
    owner has just switched on by hand (the safe direction), and if the dongle is still unreachable then, a write enable left on
    across a Wi-Fi-only drop stays on until the next press or reboot (it only permits a START).
- **Dump to Grid has the same latent defect** (`ecco_dump_to_grid_schedule.yaml` is a copy of the old policy). Recommended next,
  with the same pattern.
- Phone push needs a notify service the owner chooses; the persistent notification is HA-UI only.
- The Energy Actions card's Free Power LATER panel does not style `FAILED` as a warning (the Dump panel does); cosmetic.
- The offline proof is a model (`home-assistant/tests/_ha_script_sim.py` with the 11 Oct busy windows); the live proof is the
  next scheduled session, checked from the Home Assistant history and the notification log.

## Deployment

Home Assistant package only: copy `ecco_free_power_schedule.yaml` to `/config/packages/`, then reload automations, scripts and
template entities (the helpers are unchanged), or restart Home Assistant. No firmware flash, no OTA, no dashboard change. Deploy only between sessions, with no schedule armed inside the
next 10 minutes; re-arm and confirm `ARMED` afterwards.
