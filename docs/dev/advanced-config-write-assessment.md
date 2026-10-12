# Advanced Configuration: write-support assessment and staged plan (2026-10-12)

**Status:** assessment; Stage 0 implemented offline as post-export entry `acs0` (see the Stage 0 documents below). Nothing is committed, deployed or written to the inverter. This proves
control flow against models, not live behaviour.
**Base:** public main `fbe03aa`.
**Prototype:**
- `home-assistant/packages/ecco_tou_target_soc_edit.yaml`
- `home-assistant/tests/_manual_tou_sim.py`
- `home-assistant/tests/test_ecco_tou_target_soc_edit.py` (61 checks)
- a one-line extension to `_ha_script_sim.py` (templated `target.entity_id`)

## 1. Summary

- **What the card is.** The Advanced Configuration card (Inverter → Advanced) is read-only by construction:
  - It reads `hass.states` only.
  - Its tests ban every write call.
  - It lists all 165 capability-registry records: Proven 41, Experimental 1, Read only 100, Locked 16, Unsupported 7.
  - Its Global Power / Export Limit panel (register 245) has seven designed-but-disabled future controls.
- **What the firmware can write.** Only the firmware writes the inverter. Its write surface is fixed, and
  `registry/tests/test_write_surface_invariants.py` pins both the paths and the register set:
  - 22-24: clock
  - 230: grid charge current, inside Free Power only
  - 232 bit 0: grid-charge enable
  - 244: load/export mode, through the proof transaction
  - 250-261 and 268-279: the six TOU slots
- **245 cannot be written.** Register 245 (Global Power / Export Limit), the battery current limits 210/211, the battery
  SOC thresholds 217-219, the energy pattern 243 and the TOU master enable 248 have **no write path**. They need new
  firmware and new live proof.
- **The proven, guarded path that HA can already drive.** The firmware's manual TOU slot path (Load → stage → arm → Apply
  → exact readback) is guarded and proven:
  - classic ESP32, 2026-09-15;
  - the owner's four verified slot 1 SOC writes on the live ESP32-S3, 10-11 Oct 2026.
  - It is the only proven path HA can drive today without a firmware change.
- **First feature: a guarded edit of one TOU slot's target SOC (registers 268-273).** It drives that path from Home
  Assistant and proves, before arming, that every other staged field equals the live slot. So even the path's known
  weakness (no rollback after a partial write) can only leave the old or the new SOC. It needs no firmware change and no
  new register.

## 2. Mapping and evidence

The full 165-row table is in `advanced-config/settings-map.md`. For each setting it gives the label, catalogue key,
register(s), scaling, the exact HA entity, the firmware entity and line, the registry access and policy, the evidence code
and the overlay status. The register evidence is in `advanced-config/register-evidence.md`.

| Family | Registers | Write path | Proven write | Notes |
|---|---|---|---|---|
| TOU slot times | 250-255 (HHMM, 5-min grid) | `apply_manual_slotN` | 2026-09-15 (classic); TOU slot proven on S3 via slot 1 SOC writes 10 Oct | ring: slot N end = slot N+1 start, slot 6 end = 250 |
| TOU slot power | 256-261 (W, ≤ site ceiling 8000) | manual slot, Free Power, Dump | yes | the battery charge/discharge ceiling per slot; 244 changes its meaning |
| TOU target SOC | 268-273 (0-100 %) | manual slot, Free Power | yes, on S3 (10 Oct, slot 1) | fallback profile compared value (DRIFT) |
| TOU source/mode | 274-279 bits 0-1 / 2-4 | manual slot, Free Power | bits 0-1 yes; mode bits partial | read-modify-write (reserved bits kept) |
| Grid-charge enable | 232 bit 0 | every slot Apply, Free Power | yes | global: every slot Apply rewrites it |
| Grid charge current | 230 (A) | Free Power only | yes (inside FP) | hardware maximum NOT ESTABLISHED |
| Load/export mode | 244 (0/1/2) | proof transaction (apply/restore) | 2026-09-21/22 (classic); value 1 never exercised | W3 regulatory; a 244 change holds an obligation that blocks FP, Dump and TOU until restored |
| Global Power / Export Limit | 245 (W) | **none** | read-proven only | owner decision 2026-10-08: read-only until a write is proven on the S3; hardware maximum and regulatory allowance unrecorded |
| Battery max charge/discharge current | 210/211 (A) | **none** | no | W3, BMS evidence needed |
| Shutdown / restart / low SOC | 217/218/219 | **none** | no | protection; high impact |
| Energy pattern, TOU master | 243, 248 | **none** | no | highest blast radius |
| Locked by the owner | battery type/curve/protection, AUX port, grid protection 287-290 | — | — | permanent |

None of the recorded live-proof documents covers the ESP32-S3 (`SUPPORTED_HARDWARE.md`). The S3 evidence for the
slot 1 SOC writes, Free Power and RTC (10-11 Oct) exists only in session records and should become an LP record.

## 3. Ownership and conflicts

The full matrix is in `advanced-config/conflict-map.md`.

- **Free Power**
  - It owns 230/232/256-261/268-279 while it is active, starting or restoring.
  - Before restoring, it re-reads the registers. If they match neither its snapshot nor what it wrote, it stops for an
    operator decision. A Force Restore then overwrites the owner's edit.
  - An edit made between sessions is safe: the next session snapshots the edited values.
- **Dump to Grid**
  - It owns 244 and 256-261.
  - Its restore writes the snapshot without checking first, so an edit made while Dump is active would be overwritten.
    The editor must refuse while Dump owns these registers.
- **RTC correction (FB-D1)**
  - Its quiet windows sit around TOU slot start times, so editing a slot time moves them.
  - Every write path checks `correction_in_progress`.
- **Fallback profile (B10)**
  - 244, 256-261, 268-273 and 274-279 are compared values: an edit shows DRIFT (health DEGRADED).
  - 232 bit 0, 243, 248 and 250-255 are context: an edit shows CONTEXT (WARNING).
  - Only the owner can save the profile (Review → Arm → `SAVE <id>`); no script may.
  - So every edit must tell the owner and record the cause. Some values make the profile impossible to capture:
    244 ≠ 2, slot power < 500 W, charge source > 1.
- **Schedules**
  - A scheduled Free Power start retries a "write in progress" refusal for up to 10 minutes (fps1).
  - Dump to Grid's schedule still uses the old two-press policy, so an edit near a Dump start can make that start fail.
- **ecco_core authority**
  - It refuses advisory origins (intelligence, dashboard).
  - A new owner-editor write path needs its own declared origin and conflict domain.

## 4. The workflow: edit → validate → confirm → apply → read-back → restore/recover

1. **Edit (staging only).** Stage one value. Nothing is armed.
2. **Validate (HA, before anything is pressed).** All of the following must hold:
   - the value is in the allowlisted range for this register, tighter than the firmware where the owner's policy is
     stricter (target SOC ≥ the battery shutdown SOC);
   - the value differs from the live value;
   - the dongle is online;
   - no Free Power / Dump lease, transaction or owed restore;
   - no RTC correction and no manual write;
   - the write enable is not already armed;
   - no Free Power or Dump schedule starts within 15 minutes.
3. **Confirm.** The owner types an exact phrase naming the register and the value (`SET SLOT 1 TARGET SOC 40`), as the
   Free Power recovery and fallback Save flows already do.
4. **Apply.**
   1. Wait for a fresh configuration read.
   2. Load (staging = live).
   3. Prove every non-edited staged field equals the live value.
   4. Stage the one value and arm.
   5. Re-prove the staged values and the ownership flags.
   6. Press Apply once.

   The firmware re-checks every interlock (bus quiet, no lease, no RTC correction, arm, staging loaded, value ranges),
   disarms on every outcome, writes, then verifies by exact readback.
5. **Read-back.** Success needs both:
   - the firmware's `VERIFIED OK`;
   - an independent, later configuration read showing the value.

   Anything else is reported. "Nothing written" is claimed only when the firmware refused.
6. **Restore / recover.**
   - The previous value is recorded (`input_text.ecco_cfg_last_owner_edit`). Undo is the same guarded edit back to it.
   - A partial or unverifiable outcome raises a persistent notification. Because only one value differs, the worst case
     is that this value is unknown, and the owner checks it in Manual Controls.
   - Snapshot-backed automatic restore (register 244 style) is for transactions, not permanent edits.

Throughout:
- the write enable always ends off;
- never retried automatically;
- `mode: single`;
- every refusal is explicit;
- a fallback-profile DRIFT notice tells the owner to Review and Save if this is the new normal.

## 5. Classification

| Class | Controls |
|---|---|
| **SAFE FOR DEVELOPMENT** | TOU target SOC 268-273 (the first feature). Then, through the same path and proof: TOU power 256-261 (bounded by the site ceiling, shown with 244), TOU times 250-255 (5-min grid, ring coupling), charge source bits 0-1 of 274-279 |
| **REQUIRES FURTHER PROOF** | TOU mode bits 2-4; 232 bit 0 as a standalone control; 244 as a permanent setting (needs a firmware "keep" step; Essentials = 1 never exercised); 230 (no verified maximum); **245 Global Power** (owner decision: read-only until an S3 write proof, a verified hardware maximum and the regulatory allowance); 210/211 (BMS evidence); 243, 247, 248, 206, 231, generator 223-227, smart load, peak shaving 280/292/293 |
| **UNSUPPORTED** | 217-219 protection SOCs, 200-204, 213/214 (polarity disputed), 235, 262-267 slot voltages, grid protection 287-290, register 330 bits 4-15, every owner-locked or unknown (WX) record |

## 6. Proposed register allowlist (stage-gated)

| Stage | Registers | Value bounds | Path |
|---|---|---|---|
| 0 (prototype) | 268-273 only | integer, battery shutdown SOC … 100 | existing `apply_manual_slotN` |
| 1 | + 256-261 | 0 … site ceiling (8000), step 100; warn below 500 (fallback profile cannot capture) | same |
| 1 | + 250-255 | HHMM, 5-min grid, start ≠ end, ring-consistent | same |
| 1 | + 274-279 bits 0-1 | None/Grid (Generator only if a generator is fitted) | same |
| 2 | 244 | 0/2 (1 after proof) | firmware "keep" step on the proof transaction |
| 3 | 245, 210/211 | verified hardware maximum, regulatory allowance | new firmware path, new LP proof |
| never | everything UNSUPPORTED above | — | — |

This is an HA-side allowlist on top of the firmware's fixed write set. It never widens that set. Stages 2-3 widen it
deliberately, through `test_write_surface_invariants.py`, the registry and a PEX/chain entry.

## 7. Firmware versus HA

- **HA/frontend only (no firmware, no OTA):** Stages 0-1. Everything goes through the existing Load/Apply buttons, staging
  numbers/selects and the Manual Configuration Write Enable.
- **Firmware needed:**
  - Stage 2: a 244 keep step, and a standalone 232.
  - Stage 3: new allowlisted write paths for 245 and 210/211, built like the 244 transaction (fresh pre-read, durable
    snapshot, exact readback, bounded waits, callback guards, `manual_write_attempts`).
  - Live S3 proof for each.
- **Recommended firmware hardening for the TOU path** (not required for Stage 0):
  - a per-field write (no whole-slot rewrite);
  - a bounded lock release;
  - a durable pre-write snapshot or automatic rollback for a partial write;
  - an arm timeout.

## 8. The first feature: guarded TOU target SOC edit (Stage 0)

- **Script:** `script.ecco_cfg_set_tou_slot_soc(slot, target_soc, confirmation)`, following the workflow in section 4.
  It writes nothing itself; it drives the existing firmware path once per request.
- **Offline proof:** `test_ecco_tou_target_soc_edit.py`, 61 checks. It runs the real package against a firmware model.
  - **Every slot 1-6:** exactly one Load and one Apply, and only that slot's SOC register changes. It is verified twice,
    recorded, and the owner gets the DRIFT notice with the undo.
  - **19 refusals, nothing pressed:**
    - inputs: slot range; SOC range and shutdown bound; phrase, including another slot's phrase; no change;
    - state: dongle offline; Free Power or Dump ownership (6 flags); RTC correction; manual write; already armed;
      shutdown SOC unavailable;
    - schedules: a Free Power or Dump to Grid schedule within 15 minutes.
  - **The fresh read** preserves an inverter change made after the last poll.
  - **Faults:**
    - a refusal at the firmware gate is never retried;
    - a failed verify and a partial write at every one of the 6 steps leave everything except the target SOC unchanged;
    - an inverter clamp and a later read that disagrees are both reported.
  - **Races:**
    - Free Power starting before or after the Load;
    - another actor changing staging after the Load (refused by the staged-equals-live proof);
    - a dropped Apply press;
    - a second request.
  - **Mutants:** 7 caught: phrase, shutdown bound, schedule guard, fresh read, RTC guard, staged-power comparison, final
    disarm.
- **Integration still to do:**
  - a PEX entry: a new package with 2 input_text helpers and 1 script. `test_ecco_shadow_check_ux` [14] correctly refuses
    an undeclared new control surface;
  - a manifest `home_assistant_packages` stanza;
  - the card UI, which needs a deliberate, narrow relaxation of the card's no-write test: exactly one script, with the
    typed phrase;
  - an S3 live-proof protocol.
- **Live proof protocol (owner-run, between sessions):**
  1. Slot 3 target SOC 40 → 41, then 41 → 40.
  2. Each step: `VERIFIED OK`, the next configuration read, B10 shows DRIFT then MATCH after the revert, and no other
     register changes (HA history).
  3. Record it as an LP entry.

## 9. Decisions for the owner

1. Approve Stage 0 (TOU target SOC edit) for implementation as a declared post-export entry, with the card UI as Stage 0b.
2. **Lower bound for target SOC:** the battery shutdown SOC (as prototyped), or the configured minimum reserve (owner
   setting)?
3. Whether the editor should refuse while the fallback profile is in Review/Save. Recommended: yes.
4. Record the 10-11 Oct S3 write evidence (slot 1 SOC, Free Power, RTC) as an LP record.
5. Dump to Grid's restore overwrites without checking. Should the next Dump work add Free Power's re-read-before-restore
   guard?

## 10. Stage 0 as implemented (2026-10-12, owner decisions applied)

- Explicit Review → Confirm (phrase + one-time review code) → Apply; the review writes nothing.
- Bound = max(inverter shutdown SOC, ECCO minimum reserve), read fresh at Review, at Apply, on the fresh read and before the
  press; the reserve helper is only read.
- Refused (fail-closed) while the fallback system is armed, in Review or Save, during recovery, and in every other unsafe
  state; all existing firmware interlocks unchanged.
- Uncertain outcomes stop, disarm, alert with observed values and lock further edits until acknowledged.
- Documents: `advanced-config/stage0-safety-case.md`, `advanced-config/s3-tou-slot1-soc-writes-2026-10.md` (evidence record),
  `advanced-config/stage0-live-proof-procedure.md` (not executed), `advanced-config/stage0b-card-plan.md`, and
  `dump-to-grid-restore-conflict-investigation.md`.
