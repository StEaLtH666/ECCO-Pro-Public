# Advanced Configuration Stage 0: safety case

**Feature:** a guarded owner edit of ONE TOU slot's target SOC (register 267+N), through the existing firmware manual TOU path
(post-export entry `acs0`).

**Files:**
- `home-assistant/packages/ecco_tou_target_soc_edit.yaml`
- tests: `home-assistant/tests/test_ecco_tou_target_soc_edit.py`, run against the models `_manual_tou_sim.py` and
  `_ha_script_sim.py`

**Status:** offline only. Nothing here is live proof (see the live-proof procedure).

This page answers the owner's additional safety review item by item. Each claim is marked:
- **PROVEN-OFFLINE**: by the suite, against the models;
- **BY CONSTRUCTION**: from the package text, pinned by a static check;
- **BOUNDED**: limited, but not eliminated;
- **RESIDUAL**: a known risk that remains, with how it is surfaced.

## The firmware path and its limits (unchanged by Stage 0)

**What `apply_manual_slotN` does:**
- It refuses unless:
  - the write enable is on;
  - the slot's staging was loaded;
  - the raw configuration cache is valid;
  - the configuration is online;
  - no RTC correction, write lock, Free Power / Dump / register 244 ownership or corrupt lockout is present;
  - the Modbus bus is quiet;
  - the staged values are valid.
- On success it writes 232 (bit 0 composed with the cached register 232), the start/end pair, power, SOC and flags (reserved
  bits preserved). These are sequential FC16 transactions about 700 ms apart.
- It then verifies each register by exact readback and reports `VERIFIED OK` or a failure.

**What it lacks:**
- **No durable snapshot and no rollback.** A failure part-way leaves the registers written so far.
- **Load copies the dongle's configuration cache, not a fresh inverter read.** The cache is refreshed every 60 s.

Stage 0 does not change the firmware. It compensates in Home Assistant, as follows.

## 1. Fresh configuration reads and cache age

- **BY CONSTRUCTION:**
  - The Apply waits for `last_configuration_update` to change, which is a new poll after the Apply started. It refuses if
    none arrives within 90 s.
  - It re-runs the full gate on that fresh read, including the shutdown SOC published by the same poll.
  - It refuses unless the Load completes within 30 s of that read.
- **PROVEN-OFFLINE:**
  - An inverter change made after the previous poll (for example on the inverter's own panel) is kept, not reverted.
  - With no fresh read, nothing is written.
  - A late Load is refused.
  - On the happy path the cache age at the Apply press is measured (about 10 s).
- **BOUNDED:**
  - The cache is at most about 30 s plus the settle waits (about 45 s in total) old at the press.
  - Within that window, a change made by another Modbus master to slot N's start/end/power/SOC/flags or register 232 would be
    rewritten with the cached value. The documented second master (SmartDeye) must not be used concurrently.
  - Detection: the independent later read compares every written register with its pre-edit value, but a value reverted to
    exactly its pre-edit state cannot be detected. This is RESIDUAL and documented.

## 2. Other automations changing staged values

- The Manual Controls helper package (`ecco_manual_controls_helpers.yaml`) mirrors the friendly helpers and the firmware's
  staging numbers in both directions, and refreshes all helpers 2 s after any Load.
- **BY CONSTRUCTION:** before staging and again before arming, the edit waits for a FIXED POINT:
  - the refresh script is not running;
  - slot N's start-time, power and SOC helpers equal the staging numbers, so every sync automation would be a no-op;
  - every staged field except the SOC equals the live slot.
- **PROVEN-OFFLINE (with the REAL helper package running in the simulator):**
  - Stale helpers converge.
  - An owner edit of a helper mid-flow, which the sync pushes into staging, stops the edit with nothing pressed.
  - The edit also works without the helper package.
- **BOUNDED:** the last check and the press are consecutive steps of one script. An automation scheduled between them is the
  only window, and is not excluded by construction. Its effect would appear in the independent later read and lock the
  editor.

## 3. Changes between validation, Load, arm and Apply

- **BY CONSTRUCTION:** the full fail-closed gate runs four times:
  1. at Review;
  2. at Apply start;
  3. on the fresh read;
  4. immediately before the press, with the bounds re-read: max(inverter shutdown SOC, ECCO reserve).

  The review is single-use, expires after 10 minutes, and is invalidated if the slot's live SOC changed since.
- **PROVEN-OFFLINE:** every unsafe state was injected:
  - Free Power / Dump active, transaction or restore owed; register 244;
  - recovery arms and evidence; containment;
  - the fallback system armed for an operation (the status package's Save / Replace Corrupt / Invalidate Available sensors),
    and a fallback Review or Save in progress;
  - the `obl=` lease field; supervision and failback shadow;
  - RTC correction; manual write;
  - schedules within 15 minutes;
  - the lock.

  Each was injected both as its unsafe value and as `unavailable`, at Review (82 cases), between Review and Apply, and after
  the Load (RTC, supervision, reserve raised, Free Power). Every case refuses or stops before the press.
- **BOUNDED:** the firmware gate re-checks its own interlocks at the press. A change after the press is the firmware's to
  refuse.

## 4. Partial multi-register writes

- **BY CONSTRUCTION:** the only staged value that differs from the live inverter is the target SOC. The other staged fields
  are proven equal to the live slot at the fresh read.
- **PROVEN-OFFLINE (model only):** a partial write stopping after each of the 6 transactions leaves every register except
  the SOC at its value, and the outcome is UNCERTAIN, locked and alerted.
- **NOT PROVEN, explicitly bounded:** the claim "an interrupted live write can only affect the SOC" depends on assumptions
  that the offline suite cannot prove:
  1. the cache values written back equal the inverter's current values (bounded by section 1);
  2. each FC16 transaction is applied atomically by the inverter or not at all, with no torn multi-register write of the
     start/end pair;
  3. the inverter does not clamp or transform a rewritten value.

  None of these is proven on this inverter. Therefore:
  - Stage 0 never treats an interrupted or unverifiable write as harmless. It always ends UNCERTAIN, locked, with a manual
    review.
  - The live-proof procedure includes checks of every slot register after each step.

## 5. Independent read-back of every affected register

- **BY CONSTRUCTION:** success requires BOTH:
  - the firmware's `VERIFIED OK - manual Slot N` (its own readback);
  - a later configuration poll, after the firmware's own post-Apply poll, in which:
    - the SOC equals the request;
    - slot N's start, end (the next slot's start), power, charge source, mode, raw flags and the grid-charge bit all equal
      their pre-edit values.
- **PROVEN-OFFLINE:**
  - A verified write whose later read shows another register changed is UNCERTAIN, and the alert lists the field.
  - A missing later read is UNCERTAIN.
- **RESIDUAL:** register 232's bits other than bit 0 are not exposed to Home Assistant, so they are not independently read
  back. The firmware preserves them from its cache.

## 6. Ambiguous outcomes

- **BY CONSTRUCTION:**
  - One press per request, never retried, never a compensating write.
  - The write enable always ends off.
  - Any outcome other than "firmware refused at its gate" or "verified twice" is UNCERTAIN. That covers a failed verification,
    a partial write, a clamp, a disagreeing or missing later read, and a dropped or unanswered press.
  - UNCERTAIN sets `input_boolean.ecco_cfg_edit_review_required`, which refuses every later Review and Apply until the owner
    runs `script.ecco_cfg_acknowledge_edit_review` with the exact phrase `I HAVE CHECKED THE TOU SLOTS`.
- **PROVEN-OFFLINE:** each case above locks, and only the exact phrase unlocks.

## 7. Notifications and recovery instructions

**BY CONSTRUCTION:**
- **On UNCERTAIN:** a persistent notification gives:
  - the requested change;
  - the firmware's own result text;
  - the independent read, listing every field that differs with its observed and pre-edit values, or "no new configuration
    read";
  - the recovery steps: do not retry; Load the slot in Manual Controls and compare with the inverter's own display; correct
    deliberately; settle the slot before Free Power or Dump to Grid snapshot it; acknowledge to unlock.
- **On a firmware refusal:** a "nothing written" alert.
- **On success:** a DRIFT notice (Review and Save the fallback profile if this is the new normal) and the undo (the same
  guarded edit back to the old value).

## Scope

**BY CONSTRUCTION, pinned by static checks:**
- `number.set_value` appears exactly once, on the slot's target SOC staging entity.
- `button.press` appears exactly twice: the slot's Load and Apply.
- `switch.turn_on` only on the Manual Configuration Write Enable.
- No ESPHome action, Modbus service, select, input_number write or register path.
- The reserve helper is only read.

The firmware write surface is unchanged.
