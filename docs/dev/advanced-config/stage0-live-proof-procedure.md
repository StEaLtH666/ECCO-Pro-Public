# Advanced Configuration Stage 0: supervised live-proof procedure (PREPARED, NOT EXECUTED)

**Purpose:** prove Stage 0 on the live ESP32-S3: slot 3 target SOC 40 → 41 → 40 %.

**Who:** the owner runs every step. A session may watch read-only (HA history and states) but never presses, arms or writes.

**Status:** not executed. It needs the owner's explicit approval after Stage 0 is deployed.

## Preconditions (all must hold, recorded before step 1)

1. **Timing.** No Free Power or Dump to Grid session, schedule or recovery is active or armed within the next 60 minutes,
   and no fallback Review or Save is open.
2. **Package deployed.** Stage 0 (`ecco_tou_target_soc_edit.yaml`) is deployed and reloaded. The three scripts, the five
   helpers and the `ECCO - Configuration edit interrupted` automation exist; `input_boolean.ecco_cfg_edit_review_required`
   and `input_boolean.ecco_cfg_edit_in_flight` are both off.
3. **Fallback profile.** The live match shows MATCH. Note `dx` and `obl`.
4. **Slot 3 baseline.** Record start, end (slot 4 start), power, charge source, mode, raw flags, SOC (expected 40 %) and the
   grid-charge bit. Also record slots 1, 2, 4, 5 and 6 (all fields).
5. **Bounds.** Record the inverter shutdown SOC and the ECCO minimum reserve. The allowed range must include 40 and 41.
6. **Counters.** Record the manual configuration write counters (attempts / successes / failures).
7. **Read-only capture.** Start a dongle log capture (`esphome logs`, bounded, read-only), and note the HA history pull window.

## Step A: 40 → 41 %

1. Run *ECCO - Review a TOU slot target SOC edit*: slot 3, target SOC 41.
   - Check the review notification: register 270, 40 → 41 %, every unchanged value, the allowed range and the phrase.
2. Within 10 minutes, run *ECCO - Apply a reviewed TOU slot target SOC edit* with the exact phrase from the review.
3. Expect:
   - the result moves through `IN PROGRESS`, with `input_boolean.ecco_cfg_edit_in_flight` on;
   - then `APPLIED AND VERIFIED`, within about 3 minutes (it waits for one fresh and two later configuration reads), with the
     in-flight marker back off and the Manual Configuration Write Enable off within seconds of the Apply;
   - the notification reports "TOU slot 3 target SOC changed to 41 %";
   - the live match shows DRIFT;
   - the counters advance by +1 / +1 / 0.
4. **Stop conditions:** any FAILED, REFUSED or UNCERTAIN result, the lock turning on, or any other field of any slot
   changing. Do NOT retry. Follow the notification's recovery steps.

## Step B: 41 → 40 %

Wait at least 2 minutes after step A. Repeat it with target 40, using a new review code. Expect `APPLIED AND VERIFIED`, the
live match returning to MATCH, and the counters advancing by +1 / +1 / 0 again.

## Acceptance (from raw evidence only)

Pull HA history (read-only) for the window and check:
- every slot 3 field other than the SOC, and every field of slots 1, 2, 4, 5 and 6, has no change rows;
- the SOC rows read 40 → 41 → 40;
- each Apply produced exactly one `Writing Slot3 …`, one `VERIFIED OK`, and two later configuration reads (strictly later
  update times) matching the request;
- the dongle log shows exactly the slot 3 write and verify transactions per Apply, no retries, and the write enable disarmed;
- the lock stayed off, and no Free Power, Dump, RTC or fallback state changed except the expected DRIFT / MATCH.

Record the result as an evidence record in the style of `s3-tou-slot1-soc-writes-2026-10.md`, classifying every claim as
RAW, DERIVED or RETROSPECTIVE.

## Rollback

There is no automatic rollback. If anything is unexpected:
1. Stop.
2. Load slot 3 in Manual Controls and compare it with the inverter's own display.
3. Restore 40 % deliberately through the same guarded edit, once the cause is understood.
4. Acknowledge the lock only after checking.
