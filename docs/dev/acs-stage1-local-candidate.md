# Advanced Configuration Stage 1: guarded TOU settings editor (local offline candidate)

Status: **OFFLINE CANDIDATE. NOT INSTALLED. NO REGISTER WRITTEN. NO NEW FIRMWARE WRITE SCOPE.**
Branch `dev/acs-stage1-settings` (local), base public main `e7a265b8`.

| File | Role |
|---|---|
| `home-assistant/prototypes/acs-stage1/acs_stage1_transform.py` | the candidate, expressed as exact edits to the installed Stage 0 editor (see section 2) |
| `home-assistant/tests/test_ecco_acs_stage1_prototype.py` | the offline suite (runs the generated package against the firmware model and the real Manual Controls helpers) |
| this document | reuse proof, per-setting matrix, refusal and rollback contract, residual risks, GUI storyboard, deployment plan |
| `docs/dev/smartdeye-retirement-dependencies.md` | what must exist in ECCO before SmartDeye could be retired |

## 1. Can Stage 1 reuse the proven path without new firmware scope? Yes

- The firmware's manual TOU path (`apply_manual_slotN`, `docs/dev/advanced-config/write-surface.md` section 2.1) already writes,
  for slot N, from staging:
  - register 232 bit 0;
  - the start/end pair (250+N-1 and the next slot's start);
  - power 256+N-1;
  - SOC 268+N-1;
  - flags 274+N-1 (cache & 0xFFE0 | source | mode).
- It verifies every one of them by exact readback (232: bit 0 only).
- It is live-proven for all of these registers (`registry/inverter_capabilities.yaml`, `live_proven_write`).
- The Stage 0 editor (ACS0, `home-assistant/packages/ecco_tou_target_soc_edit.yaml`) already drives this path from Home
  Assistant for the SOC field, with the full guard set (`docs/dev/advanced-config/stage0-safety-case.md`).
- Stage 1 drives **the same path, through the same buttons, numbers, selects and switch**, for three more fields. It adds no
  firmware entity, no register and no write path. `registry/tests/test_write_surface_invariants.py` is untouched and still pins
  the firmware's written set.
- The firmware's own gates (arm, staging loaded, cache valid, online, no RTC correction, no write lock, no Free Power / Dump /
  register 244 ownership or corruption, bus quiet, value validation) are unchanged and still decide.

## 2. Why the candidate is a transformation of ACS0, not a new file (owner decision point)

- **The constraint.** The proof chain reserves the fallback/failback entity-id tokens. Four frozen suites scan every file under
  `home-assistant/` and fail on any file that spells them unless a chain entry declares that file. ACS0's fail-closed gate must
  read six of those ids (B10 live match, fallback Review, the three operator "available" sensors and the failback shadow state).
  ACS0 is a declared holder.
- **The rejected options:**
  - a new Stage 1 package file needs a chain entry, which this stage may not create;
  - dropping or obfuscating the fallback gate would be unsafe or evasive.
- **The choice.** The candidate is `PAIRS`, an ordered list of exact `(before, after, count)` edits applied to the installed
  ACS0 package text, the same technique the repository's proof-chain scope modules use.
  - The fallback/failback gate is inherited byte-for-byte; the suite proves it.
  - The two new files spell no reserved token; the suite proves that too.
  - The generated package exists only in memory in the tests.
- **Integration (later, separately approved).** The generated text replaces the ACS0 package file, which is already a declared
  holder, under a reviewed chain entry. Stage 1 is therefore a superset that **replaces** ACS0. The two are never installed
  together, because they share the same helpers, lock, in-flight marker and watchdog.
- **This is not a way around the rule.** The independent review stated both sides:
  - *For:* the installed artefact stays the already-declared file, reading exactly the same six ids with byte-identical gate
    lines.
  - *Against:* the owner's 2026-10-12 token amendment approved those reads for a SOC-only editor, and Stage 1 widens what that
    file does under the same exemption.

  So the integration PR must:
  1. **ask the owner to re-approve** the amendment for the wider editor;
  2. add a new chain entry (for example `acs1`) whose scope module pins the exact replacement text, the unchanged six-id read set
     and the unchanged holder list;
  3. make the ACS0 suite and scope-pin updates declared edits;
  4. commit the generated YAML with a test that it equals `render_stage1(ACS0 at the base commit)`, so the byte-identical gate
     proof survives;
  5. re-run every frozen suite on the committed tree.

## 3. Per-setting safety and ownership matrix

| Setting | Register(s) changed | Staging entity set | Bounds (HA policy / firmware) | Coupling | Fallback B10 after a successful edit | Owners that refuse the edit |
|---|---|---|---|---|---|---|
| Target SOC (unchanged ACS0) | 267+N | `number.…_manual_slot_N_target_soc` | max(shutdown SOC, ECCO reserve)..100 / 0..100 | none | DRIFT | all below |
| Power | 255+N | `number.…_manual_slot_N_power` | **500..8000, step 100** / 0..8000 | its meaning depends on register 244 (load/export mode); Dump to Grid and Free Power overwrite it while they own the slot | DRIFT | all below |
| Start time | 249+N (= slot N-1's end; slot 1's start = slot 6's end) | `number.…_manual_slot_N_start_hhmm` | 5-minute grid; the six starts strictly ascending before and after; new != old; not within 15 minutes of the old or new boundary / HHMM valid, mm%5==0, start != end | moves two slots' window at once; moves the RTC precision-correction and quiet windows (`ecco_rtc_policy.h`) | CONTEXT (slot times are context) | all below |
| Charge source | 273+N bits 0-1 | `select.…_manual_slot_N_charge_source` | **None or Grid only**; refused if the live source is a generator value / firmware: 0-3 | mode bits 2-4 and reserved bits preserved (staged mode == live mode, firmware keeps cache & 0xFFE0) | DRIFT | all below |

**Rejected in Stage 1, with reasons:**
- generator sources: no generator is evidenced, and the fallback profile domain is 0/1;
- power below 500 W: the saved profile's domain is left, the live match becomes OUT_OF_DOMAIN, and the editor's own gate would
  then refuse every further edit, including the undo;
- mode bits;
- end times as a separate control: the end is the next slot's start;
- register 232 as a control;
- everything in Stages 2-3 (`docs/dev/advanced-config-write-assessment.md` section 5).

**Owners and states that refuse an edit** (at Review, at Apply start, after the fresh read and immediately before the press;
inherited from ACS0):
- Free Power or Dump to Grid active, starting or owing a restore;
- the register 244 transaction or its snapshot;
- recovery, containment or corrupt lockouts;
- RTC correction in progress; another manual write;
- any arm on;
- the fallback system armed or in Review/Save, or a live match not MATCH/DRIFT/CONTEXT with `obl` clear, `ca=F`, `eh=0`;
- supervision not stable, or a failback episode;
- a Free Power or Dump schedule starting within 15 minutes, or a scheduled start running;
- the dongle offline or the configuration not fresh (clock-coherent, heartbeat round trip);
- an earlier UNCERTAIN outcome not acknowledged.

**New in Stage 1 (HA policy):**
- refused 00:00-03:00 local on the last Sunday of March and of October (UK clock changes), for every setting;
- the slot's raw flags must be readable before the Load (the charge-source verdict needs them), for every setting;
- start-time edits only:
  - refused if the inverter's own clock and Home Assistant's clock differ by more than 120 s, or the inverter clock is
    unreadable (the inverter runs TOU on its own clock);
  - refused if the change would switch which slot is active right now (the current time lies between the old and new
    boundary);
  - refused if any slot's live start is not a well-formed HH:MM (the firmware publishes `?nnnn` for out-of-range words).

**Different from ACS0 (stated deliberately):** "inverter shutdown SOC unavailable", "ECCO reserve unavailable" and "live slot SOC
unavailable" refuse only target-SOC edits, because they are the SOC bound's inputs. Every other ACS0 refusal applies to every
setting.

**Charge source None is staged with `select.select_first`.** Home Assistant parses even a static service-data value, so
`option: "None"` would reach the select as Python `None` and be rejected. The firmware lists None first on all six charge-source
selects; the suite checks that and renders service data the way Home Assistant does.

## 4. Refusal, outcome and rollback contract

- **One value per request.** The plan record is `slot|setting|value|code|reviewed_at|before`. The review is single-use, expires
  after 10 minutes and is invalidated if the slot's live value of that setting changed.
- **Typed phrases**, each naming the slot, the setting and the value:
  - `SET SLOT n TARGET SOC x REVIEW code` (unchanged from ACS0);
  - `SET SLOT n POWER w W REVIEW code`;
  - `SET SLOT n START HH:MM REVIEW code`;
  - `SET SLOT n CHARGE SOURCE GRID|NONE REVIEW code`.
- **Before arming**, every other staged field must equal the live slot:
  - start, end, power, SOC, source and mode;
  - the grid-charge staging switch;
  - the Manual Controls helpers at a fixed point.

  Only the edited field may differ.
- **One press, never retried, never a compensating write.**
- **Success needs both of these:**
  - the firmware's `VERIFIED OK`;
  - an independent comparison after two later, clock-coherent configuration reads (the first checked for timing, the comparison
    made on the state after the second), in which the edited field equals the request and every other written field equals its
    pre-edit value. For the charge source, the raw flags must equal (old & ~3) | new.
- **"Refused, nothing written" needs all three:**
  - a firmware refusal text;
  - an unchanged gate-pass counter;
  - both later reads at pre-edit values.
- **Anything else is UNCERTAIN:** the editor disarms, alerts with every observed difference and locks until the owner types
  `I HAVE CHECKED THE TOU SLOTS`. An interrupted run (restart, reload) is locked by the watchdog.
- **Rollback is an undo, not an automatic restore.** The success notice gives the exact phrase for the same setting back to its
  old value, through the same guarded flow. No snapshot-backed automatic restore exists for permanent edits; that is
  deliberate, as in ACS0.

## 5. Residual risks (stated, not hidden)

1. **Not per-field atomic.** The firmware rewrites the whole slot (232 bit 0, start/end, power, SOC, flags) as about five
   sequential FC16 transactions with no rollback. The editor makes every value it rewrites equal to the live value, proven
   immediately before arming. So the intended result of a partial write is "old or new edited value, everything else
   unchanged". That depends on three unproven assumptions:
   - the cache equals the inverter at the press;
   - each FC16 is applied atomically;
   - the inverter stores values unchanged.

   Any interrupted or unverifiable write therefore ends UNCERTAIN and locked.
2. **Register 232 bit 0 is global.** Every slot Apply rewrites it from staging. It is proven equal to live, but its other bits are
   not visible to Home Assistant (the firmware preserves them from its cache).
3. **A second Modbus master** (SmartDeye, the inverter panel) changing the slot during the cache window would be overwritten with
   the cached value. The window is bounded by about 30 s and detected by the later reads, except a change reverted to exactly its
   pre-edit value. **Do not use SmartDeye or the inverter panel during an edit.**
4. **Start-time edits move an active window.** The 15-minute guard keeps the edit away from the transitions themselves. The
   inverter's behaviour when the current slot's window changes is not separately proven; the live proof must use a boundary far
   from now.
5. **Time zone.** As ACS0: Home Assistant must be configured for Europe/London; otherwise edits are refused.
6. **The shared write enable** and admin unlock are as documented for ACS0 (stage0-safety-case "Other residual points").
7. **Stale neighbour staging after a start-time edit (new with Stage 1).** Slot N's start is also slot N-1's end. If slot N-1,
   or all slots via Load All, was loaded into Manual Controls staging before the edit, its staged end still holds the old time.
   A later Manual Controls Apply of slot N-1 writes the old boundary back, and the firmware reports `VERIFIED OK` because it
   verifies what it wrote.
   - The success notice tells the owner to press Load Current Slot N-1 (or Load All) before any Manual Controls Apply of that
     slot.
   - An automatic extra Load press is possible (it writes no register) but widens the editor's action set, so it is an owner
     decision.
   - The suite demonstrates the revert in the model.
8. **A FAILED run leaves the reviewed value in staging (inherited from ACS0).** When an Apply stops before its press, slot N's
   staging stays loaded with the edited value. A later Manual Controls Apply of slot N would write it.
9. **Long refusal texts (inherited from ACS0).** One combined FAILED text can exceed the 255-character `input_text` limit;
   Home Assistant then keeps the previous value ("IN PROGRESS") and no FAILED notice fires. Nothing is written in that case.
10. **Firmware line numbers.** `docs/dev/advanced-config/write-surface.md` and the model cite older firmware line numbers
    (for example about 12570 for `apply_manual_slot1`, now about 13666). The behaviour cited is unchanged.

## 6. GUI storyboard (for the later card; no frontend change in this stage)

1. **Slot table (read-only):** six rows, each showing:
   - start-end (the end is the next start);
   - power;
   - target SOC;
   - charge source;
   - mode (read-only).

   Values are the inverter's own read-back from the last configuration poll, with its time, and a fallback badge
   (MATCH / DRIFT / CONTEXT). A row shows "owned by Free Power / Dump" and greys out while either owns it.
2. **Edit:** a pencil on power, start or source (and SOC, as today). The input is bounded:
   - power: 500-8000 W in 100 W steps;
   - start: a 5-minute picker limited to between the neighbours, at least 15 minutes from now, and never switching which slot
     is active now;
   - source: None / Grid.

   An effect line explains the change, for example "Slot 3 starts 09:30 instead of 09:00; slot 2 then ends 09:30". The
   Review button is disabled with the exact reason when any gate refuses.
3. **Review panel:**
   - old -> new;
   - the unchanged fields that will be rewritten with their current values;
   - the couplings;
   - the fallback note (DRIFT / CONTEXT);
   - the allowed range;
   - the 10-minute expiry;
   - the exact phrase to type (not pre-filled into the Apply box).
4. **Apply:** a progress strip:
   - fresh read;
   - Load;
   - staged == live;
   - quiet bus gap;
   - press;
   - firmware verify;
   - later read 1;
   - later read 2.
5. **Outcome:**
   - **success:** the new value, the fallback note and an Undo button that starts a new Review back to the old value;
   - **refused:** "nothing written" with the reason;
   - **UNCERTAIN:** a red banner with every differing field, recovery steps and the acknowledgement box. All edit controls are
     disabled until acknowledged.
6. Manual Controls are visually disabled while an edit is in flight (display-only; the write surface cannot enforce it).

## 7. Offline test results

All offline, local, run as `python -I -B` (no bytecode left behind; stale bytecode can trip the frozen token scans).

| Suite | Result |
|---|---|
| `home-assistant/tests/test_ecco_acs_stage1_prototype.py` | **277 checks passed** (about 210 s) |
| `home-assistant/tests/test_ecco_tou_target_soc_edit.py` (ACS0, unchanged) | 162 checks passed |
| frozen: `registry/tests/test_fallback_profile_schema.py`, `test_fallback_save_scope.py`, `test_fallback_live_match.py`, `test_fallback_recovery_dashboard.py` | all pass |
| `registry/tests/test_write_surface_invariants.py` (the firmware's written registers and paths) | passes: no new write scope |
| suites that scan all of `home-assistant/`: `test_ecco_shadow_check_ux.py`, `test_ecco_fallback_packages.py`, `test_ecco_reserve_default.py` | pass |
| `tools/validate_repo.py` | passes |

What the Stage 1 suite covers:
- **The transformation:** 40 exact pairs. Every one applies exactly as declared. Every ACS0 line that reads a reserved id appears
  byte-identical in the result. Neither new file spells a reserved token. An altered anchor raises.
- **Scope:** only the slot's SOC, power and start staging numbers, its charge-source select (`select_option` Grid,
  `select_first` None), its Load and Apply, and the write enable. Every firmware entity used already exists and is already used
  by the firmware path; the firmware's six charge-source selects list None first.
- **Every slot x every setting** end to end. Only the intended register changes, checked against every model register.
- **SOC parity with the installed ACS0** on shared scenarios.
- **Per-setting validation:** power bounds and step; start grid, order, wrap, neighbours, the 15-minute guard, the active-slot
  rule (a 49-case table), the inverter-clock coherence and malformed live times; charge source words and live generator values;
  the clock-change nights.
- **Review and phrase handling;** the full gate for every setting.
- **Staged == live** against changes to every other field.
- **The fresh read;** firmware refusal; verify failure; partial writes at every step; per-field clamps; disagreeing, missing
  and blipped later reads; dropped press; stuck arm; restart; acknowledgement.
- **Races and the inherited acs0r1 press timing.**
- **Home Assistant service-data parsing:** a test reproduces the original `option: "None"` failure and proves the fix.
- **The stale slot N-1 staging revert (residual 7)** is demonstrated.
- **38 mutants,** each killed by a named behavioural check, never by a crash.

Not provable offline:
- real Home Assistant service schemas and time zone;
- whether the inverter accepts and keeps the written power, start-time and charge-source values;
- register 232's other bits;
- a torn multi-register write.

The live proof in section 8 exists for these.

## 8. Staged deployment plan (every step needs its own owner approval)

1. **Owner decisions** (section 9).
2. **Integration PR** (source only, DCO sign-off after fresh approval):
   - replace `home-assistant/packages/ecco_tou_target_soc_edit.yaml` with the generated text under a declared chain entry
     (the reserved-token holder list is unchanged: same file);
   - move the Stage 1 suite next to or in place of the ACS0 suite;
   - update the ACS0 suite's pins deliberately;
   - decide whether the Stage 0 script ids stay as thin wrappers for existing callers;
   - no firmware, registry or manifest change (same package path).
3. **CI green** on that PR. Merge is a separate decision.
4. **Install preview:**
   - fresh full HA backup;
   - a diff of the package against the installed one;
   - `ha core check`;
   - one script/automation reload, no restart;
   - confirm the old SOC flow still works (Review only).
5. **Supervised live proof, one setting at a time**, each on a slot that is not active and far from its boundaries, each followed
   at once by its undo:
   - power 8000 -> 7900 -> 8000 W;
   - charge source on an inactive slot, None -> Grid -> None, outside any cheap-rate window (this exercises both the
     `select_option` and the `select_first` staging);
   - start time moved by 5 minutes and back, then Load All before any Manual Controls use (residual 7).

   For every step check:
   - `VERIFIED OK`;
   - two later reads;
   - B10 DRIFT/CONTEXT, then MATCH after the undo;
   - no other register changed;
   - health unchanged.

   SmartDeye and the inverter panel are not used during the proof.
6. **Rollback:** reinstall the previous package file from the backup set, one reload, nothing to restore on the inverter.
7. **Only then** consider using Stage 1 in place of SmartDeye for these fields (see the retirement inventory).

## 9. Owner decisions

1. Accept the transformation approach and the "Stage 1 replaces ACS0" integration (section 2).
2. Power floor 500 W, as chosen; or allow lower values knowing the fallback profile then blocks further edits until re-saved.
3. Charge source None/Grid only (generator values refused); confirm no generator is fitted.
4. Start-time policy: strictly ascending starts, 15-minute distance from now, and no edits on the clock-change nights.
5. Whether to keep the Stage 0 script names as wrappers for existing callers.
6. After a verified start-time edit, whether the editor should also press Load Current Slot N-1 (writes no register; closes
   residual 7 automatically) or only tell the owner to do so (as built).
7. Re-approval of the reserved-token amendment for the wider editor (section 2), before any integration PR.
