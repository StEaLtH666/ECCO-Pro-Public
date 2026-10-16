# Restoring the manual Dump to Grid / Free Power values after a scheduled start (smr1)

Package: `home-assistant/packages/ecco_schedule_manual_restore.yaml`. Tests: `home-assistant/tests/test_ecco_schedule_manual_restore.py`.
Post-export entry: `smr1` (`registry/tests/_smr1_scope.py`).

## The problem

The dongle has one set of request numbers per function. The owner's manual controls and the schedules share them:

| Function | Request numbers |
|---|---|
| Dump to Grid | `number.ecco_clock_dongle_dump_to_grid_export_power`, `number.ecco_clock_dongle_dump_to_grid_stop_soc`, `number.ecco_clock_dongle_dump_to_grid_duration` |
| Free Power | `number.ecco_clock_dongle_free_power_max_charge_power`, `number.ecco_clock_dongle_free_power_duration` |

- A scheduled start (`script.ecco_dump_to_grid_start_scheduled`, `script.ecco_free_power_start_scheduled`) stages the schedule's own values into these numbers, then arms and presses START.
- Nothing put the owner's values back. Example: an owner keeps a manual Stop SOC of 10 % and schedules Dump to Grid with Stop SOC 15 %. After the scheduled run, the manual control reads 15 %.
- The numbers are staging values held on the dongle (`restore_value`, no Modbus); the firmware never publishes them itself.
  It reads them at START. It also reads the Dump Stop SOC while a Dump restore is still owed after END (a higher Stop SOC also
  applies then). That is while the Dump snapshot is pending, when smr1 never writes.

## What smr1 does

Home Assistant only. There is no firmware change, and the two schedule packages are unchanged. smr1 never starts, ends, arms or presses anything, and never writes to the inverter.

1. **Track** (one automation per function, `mode: queued`).
   - A request number may change while that function's scheduled start script is running, to the schedule's own request. (The duration may be clamped to the window, but never above the schedule's duration.) That change is the schedule's write:
     - the value it replaced is saved (`input_number.ecco_sched_restore_<fn>_<field>_saved`), the first time in an episode only. A retry that re-stages a shorter duration keeps the owner's value.
     - the value written is remembered (`..._written`).
     - the function becomes `OWED <epoch>` (`input_text.ecco_sched_restore_<fn>_state`).
   - Any other change while the function is owed is the owner's, or another tool's. That field is dropped, because the owner's choice wins. If every field is dropped, the state becomes `KEPT`.
   - A change from or to a non-numeric state (a dongle reconnect, a Home Assistant start) is not a change.
   - The triggers use `to: ~`, and the condition requires two different values. An attribute-only update (a rename, a
     customisation) is therefore never taken for the owner's change.
2. **Restore** (one automation per function, `mode: single`).
   - It runs only while the function is owed and `sensor.ecco_schedule_restore_blocker` reads `none`. That means:
     - no Dump to Grid or Free Power lease, start transaction, pending snapshot, or armed write enable;
     - no manual inverter write;
     - neither scheduled start script running;
     - all five request numbers readable.
   - Anything that is not exactly `off` (including `unknown` or `unavailable`) blocks.
   - The firmware's Dump / Free Power Recovery State texts are deliberately not read. They are diagnostic mirrors that keep
     their last text (PENDING, FOREIGN, ACCEPTED, ...) until the dongle reboots. A pending restore shows as the snapshot flag.
   - After a 5 s settle delay it checks again, then marks `RESTORING`.
   - It writes a field back only when both hold:
     - the saved value is valid for that number (the dongle's own `min` / `max` / `step`);
     - the number still holds exactly the value the schedule wrote.
   - It verifies for up to 15 s, then records one result:
     - `RESTORED`: everything owed is back. Any change the owner made while Home Assistant could not see it is kept and named.
     - `PARTIAL` / `FAILED`: something was not restored (an invalid saved value, or a write the dongle did not apply). A persistent notification says what to set by hand.
     - `STALE`: the obligation is older than 24 h, or its time cannot be read. Nothing is written, and a notification lists
       the saved values. A separate trigger, re-rendered every minute, makes this happen even while something still blocks
       the restore, so a blocked obligation never waits silently forever.
   - **One attempt.** The written values are cleared afterwards, so nothing is retried and nothing loops. The track ignores the restore's own writes (`RESTORING`).
   - **A race with a new start.** A scheduled start of the same function may begin during the restore. The function then
     stays owed, and the rest is restored after that start's lease:
     - the restore clears only what it planned with, and only while no start of that function runs;
     - one templated action sets OWED whenever anything is still written;
     - the track re-reads the live state before deciding whether to set OWED.
   - **Triggers:**
     - the obligation becoming restorable (a template trigger);
     - the obligation reaching 24 h (a template trigger on `now()`);
     - the Home Assistant start event, so an obligation survives a restart (a restore cut short by a restart resumes);
     - `automation_reloaded`, because a reload sets the template trigger up already true, and it would not fire.

`sensor.ecco_schedule_manual_restore` reads `CLEAR`, or `OWED - <functions>; waiting: <blocker>` / `; restoring`.

## Limits and choices

- **Owner change during a scheduled start.** The owner might change a request number during a scheduled start's own staging or retry window (seconds, at most the bounded 10 minutes of retries), to exactly the schedule's value (any value up to the schedule's duration, for a duration). That change is taken for the schedule's write. Its consequence is that the owner's pre-schedule value is restored.
- **Owner change during the restore.** An owner change inside the few seconds of a restore (`RESTORING`) is not seen as the owner's. The restore's verification then reports it as not restored (`PARTIAL` / `FAILED`, notified).
- **Unclean shutdown.** Home Assistant saves restored helper states every 15 minutes and at a clean stop. A crash or power
  cut within 15 minutes of a scheduled start can lose the obligation. The manual values then stay at the schedule's, as
  without smr1.
- **The per-field blocker re-check.** It is defence in depth for the instant between the plan and the write; the offline
  model cannot interleave anything there, so it is not mutation-tested.
- **Changes Home Assistant cannot see.** A change made on the dongle while Home Assistant is down is not seen as it happens. It is kept anyway, because the restore writes only a number that still holds the schedule's value.
- **What does not change.** The schedules' scheduling, clock-change, overlap and charging-slot rules are unchanged. smr1 writes only staging values, while nothing owns control, and never starts anything.

## Deploying

Copy the package to `/config/packages/ecco_schedule_manual_restore.yaml` (`deployment/ha-manifest.yaml`). Then reload
`input_number`, `input_text`, `template` and `automation`. The manifest marks it `restart_required` like every package; the
reloads load it without a restart. Deploy it while nothing is owed and both schedules are idle.

The helpers have no `initial`. On first install the numbers start at 0 (nothing saved) and the state texts are `unknown` or
empty (nothing owed). After that, Home Assistant restores them.
