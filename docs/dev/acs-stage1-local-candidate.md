# Advanced Configuration Stage 1: guarded TOU settings editor (local offline candidate)

Status: **OFFLINE CANDIDATE, since INTEGRATED AS SOURCE (post-export entry `acs1`; see [acs-stage1-integration.md](acs-stage1-integration.md)).
NOT INSTALLED. NO REGISTER WRITTEN. NO NEW FIRMWARE WRITE SCOPE.**
Branch `dev/acs-stage1-settings` (local), base public main `e7a265b8`.

Integration note: the candidate's package is now the installed source file `home-assistant/packages/ecco_tou_target_soc_edit.yaml`, the
prototype suite became `home-assistant/tests/test_ecco_tou_slot_settings_edit.py` (it tests the installed file and proves the provenance
with `unrender_stage1`, so no git history is needed), and the transform module documents how the installed package was derived. The
sections below are the candidate's reuse proof, matrix, contract, risks and plan, kept as reviewed; where they say "candidate",
"prototype" or "in memory", read the integration document.

| File | Role |
|---|---|
| `home-assistant/prototypes/acs-stage1/acs_stage1_transform.py` | the candidate, expressed as exact, invertible edits to the Stage 0 editor (see section 2); after integration, the record of how the installed package was derived |
| `home-assistant/tests/test_ecco_tou_slot_settings_edit.py` (candidate name: `test_ecco_acs_stage1_prototype.py`) | the offline suite (runs the package against the firmware model and the real Manual Controls helpers) |
| this document | reuse proof, per-setting matrix, refusal and rollback contract, residual risks, GUI storyboard, deployment plan |
| Appendix A of this document | what must exist in ECCO before SmartDeye could be retired |

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
| Power | 255+N | `number.…_manual_slot_N_power` | **500..8000, step 100** (and the LIVE slot power must be a multiple of 100 W, F3) / 0..8000 | its meaning depends on register 244 (load/export mode); Dump to Grid and Free Power overwrite it while they own the slot | DRIFT | all below |
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
- a **power** edit is refused when the LIVE slot power is not a multiple of 100 W (F3; at the Review and at every later gate copy that
  re-reads the live value: the Apply start, after the fresh read and immediately before the press), with the reason "the live slot
  power X W is not a multiple of 100 W; the undo would be refused - align it first in Manual Controls". The requested value stays
  500..8000 W in steps of 100. (Without it the success notice could offer an undo the Review would refuse.)
- start-time edits only:
  - refused if the inverter's own clock and Home Assistant's clock differ by more than 120 s, or the inverter clock is
    unreadable (the inverter runs TOU on its own clock);
  - refused if the change would switch which slot is active right now (the current time lies between the old and new
    boundary);
  - refused if any slot's live start is not a well-formed HH:MM (the firmware publishes `?nnnn` for out-of-range words).

**Added after the owner's review decisions of 2026-10-20 (F1-F4, see section 9):**
- **F1, a start-time edit refreshes slot N-1's Manual Controls staging.** After a VERIFIED SUCCESSFUL start-time edit of slot N the
  editor presses Load Current Slot N-1 once (slot 1 -> slot 6), so that slot's staged end holds the new boundary. It first waits (at
  most 60 s) until the firmware would accept a Load (raw cache valid, no manual write in progress, the write enable off, neither Free
  Power nor Dump to Grid owning the TOU settings, no register 244 transaction), then verifies, within 20 s, that the staged end equals
  the new boundary and that the firmware reported that Load. The Load writes no inverter register; it never arms and never presses an
  Apply; it is never retried. If the Load is refused or the end does not match, the edit STAYS successful (the inverter write was
  verified) and the success notice says plainly that slot N-1's staging could not be refreshed and to press Load Current Slot N-1 (or
  Load All) before any Manual Controls Apply. Only for the start time: SOC, power and charge-source edits press no extra Load.
- **F2, slot N's staging is refreshed after a FAILED run, but only after a PROVEN outcome (corrected by the review).** The editor
  re-presses Load Current Slot N (then verifies that slot N's staging equals the live slot in every field, within a bounded wait) in
  exactly two cases:
  - (a) The run stopped after it staged the value and BEFORE the Apply press was sent ("a safety check changed just before the Apply":
    a changed gate, no quiet Modbus window, a late arm, another actor changing staging) AND that is proven to have written nothing.
    "Nothing pressed" alone is not proof: the Manual Configuration Write Enable is shared and the firmware accepts ANY Apply press
    while it is on, so an Apply by someone else can land while the editor is armed. The editor therefore records the firmware's
    gate-pass counter (`manual_configuration_write_attempts_since_boot`) and clears an "inverter write seen" marker BEFORE it stages
    anything; when it stops before the press it disarms at once, waits 35 s for the counter to publish (every 30 s), and claims
    "nothing written" only if the counter is readable and unchanged, the write-in-progress flag was never seen on since the staging
    (the marker, set by a small automation, and the live flag), and the firmware's last result shows no write.
  - (b) The firmware refused at its gate and the editor's existing verdict holds in full: refusal text AND an unchanged gate-pass counter
    AND both later reads at the pre-edit values.
  In every other case - the counter moved or is unreadable, a write seen, UNCERTAIN, a partial write, verify failure, clamp,
  disagreeing or missing later reads, a dropped press, a press whose outcome is unknown, the write enable not confirmed off, a restart
  or watchdog interruption - the result is UNCERTAIN: the lock is set (or stays), the existing manual-recovery notification is raised
  (for the pre-press case it says an Apply may have run while the editor was armed and lists the counter before and after, the write
  seen, the firmware's last result and the live slot), there is no re-Load, and uncertainty is never cleared automatically. This is a
  deliberate, stricter difference from Stage 0, whose inherited "nothing pressed, nothing written" claim in that window was false
  in the reproduction, and it applies to SOC edits too.
  A run that stopped before it staged anything (no fresh evidence, a refused Apply, the staging not matching the live slot after the
  first Load) is not re-Loaded either: the value was never staged. If a proven re-Load is refused or does not match, the FAILED notice
  says slot N's staging may still hold the reviewed value and to press Load Current Slot N before any Manual Controls Apply.
- **An Apply by someone else inside the armed window** (or while the outcome is judged) is caught by N2 (owner-approved 2026-10-21): the
  success verdict also needs the gate-pass counter to have moved by exactly 1 since before the staging (read at the verdict, at least 37 s
  after the press, after the counter published; only the six slot Apply gates increment it, not the Load buttons). Delta 0, 2 or more, a
  reset or an unreadable counter is UNCERTAIN with the lock and the manual-recovery notification (before F1's Load, no undo offer). The
  documented caveat: another actor's Apply that wrote the reviewed staging while the editor's own press was refused gives delta 1 and stays
  APPLIED AND VERIFIED (the requested value, verified, nothing else changed). It is never reported as "nothing written" and never re-Loads slot N.
- **The write-seen recorder is edge-triggered.** A write already in progress when the staging window begins does not fire it again, but
  the gate-pass counter delta (read after the counter published), the end-of-window write-in-progress sample and the last-result text
  sample still catch it. The proof's "nothing written" is about the manual (armed) path; the RTC clock writes do not use the write
  enable and are outside it.
- **The editor stays "in flight" during the follow-up waits** (F1's Load wait, F2's counter and Load waits, about 80 s at most).
  That is deliberate: a Home Assistant restart in that window gives the watchdog's UNCERTAIN and the lock even after a verified success.
- **F4, the Review notification** (a persistent notification; no input_text value grows, all stay under 255 characters) says: "Do not
  use SmartDeye or the inverter's own panel until this edit is finished." always, and "A slot with a charge source set makes a
  scheduled Dump to Grid whose window overlaps it refuse at start (no health alert counts that refusal)." for charge source -> Grid
  and for a start-time edit on a slot whose live charge source is not None.

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
  `I HAVE CHECKED THE TOU SLOTS`. An interrupted run (restart, reload) is locked by the watchdog. This includes a run that stopped
  before the press while the editor was armed but cannot prove (counter unchanged after it published, no write seen) that no Apply
  ran: "nothing pressed" is not "nothing written" (the write enable is shared).
- **Staging refreshes write nothing** (F1/F2, section 3): at most one Load per case, never an arm, never an Apply, never a retry, and
  never on an UNCERTAIN outcome.
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
   pre-edit value. **Do not use SmartDeye or the inverter panel during an edit.** (F4: the Review notification now says so on every Review. Still advice only: nothing in Home Assistant enforces it.)
4. **Start-time edits move an active window.** The 15-minute guard keeps the edit away from the transitions themselves. The
   inverter's behaviour when the current slot's window changes is not separately proven; the live proof must use a boundary far
   from now.
5. **Time zone.** As ACS0: Home Assistant must be configured for Europe/London; otherwise edits are refused.
6. **The shared write enable** and admin unlock are as documented for ACS0 (stage0-safety-case "Other residual points"). For the armed window
   this is **closed by N2 (owner-approved 2026-10-21)**: the success verdict needs the firmware's gate-pass counter to have moved by exactly 1
   (see the note on an Apply by someone else below); the shared write enable itself is unchanged. This holds within the verdict window: an Apply that someone deliberately arms and presses after the editor has taken its counter sample (after the verdict) is outside the editor's view, as before.
7. **Stale neighbour staging after a start-time edit (new with Stage 1).** Slot N's start is also slot N-1's end. If slot N-1,
   or all slots via Load All, was loaded into Manual Controls staging before the edit, its staged end still holds the old time.
   A later Manual Controls Apply of slot N-1 writes the old boundary back, and the firmware reports `VERIFIED OK` because it
   verifies what it wrote.
   - **Repaired by F1 (owner-approved 2026-10-20):** after a verified start-time edit the editor presses Load Current Slot N-1
     itself and verifies that slot's staged end. The suite shows that a later Manual Controls Apply of slot N-1 no longer reverts
     the boundary.
   - The fallback, when the Load is refused (for example Free Power takes the TOU settings right after the edit) or has no effect:
     the success notice says plainly that the staging could not be refreshed and tells the owner to press Load Current Slot N-1
     (or Load All) before any Manual Controls Apply of that slot. The edit stays successful.
8. **A FAILED run leaves the reviewed value in staging (inherited from ACS0).** When an Apply stops before its press, slot N's
   staging stays loaded with the edited value. A later Manual Controls Apply of slot N would write it, without any of Stage 1's
   guards. **Handled by F2 (owner-approved 2026-10-20, conditional, corrected by the review):** slot N is re-Loaded only after a
   counter-proven "no manual-path write" before the press, or the full proven firmware refusal (section 3); after any UNCERTAIN,
   partial or unproven outcome - including a pre-press stop whose counter moved - the staging is deliberately left alone and the manual
   recovery notice stands. If a proven re-Load is refused the FAILED notice carries the warning.
9. **Long refusal texts (inherited from ACS0).** One combined FAILED text can exceed the 255-character `input_text` limit;
   Home Assistant then keeps the previous value ("IN PROGRESS") and no FAILED notice fires. Nothing is written in that case.
10. **Firmware line numbers.** `docs/dev/advanced-config/write-surface.md` and the model cite older firmware line numbers
    (for example about 12570 for `apply_manual_slot1`, now about 13666). The behaviour cited is unchanged.
11. **The success notice could offer an undo the Review refuses.** The undo phrase names the old value, but the Review applies its own
    rules to it: for example a live power of 2550 W is not a multiple of 100, so the undo back to 2550 W would be refused. **Repaired by
    F3 (owner-approved 2026-10-20):** a power edit is refused up front when the live slot power is not a multiple of 100 W.
12. **Dump to Grid can refuse to start after a charge-source or slot-time edit.** Per the review of the Dump start gate, a Dump to Grid
    whose window overlaps a slot with a charge source set refuses to start; a Grid source, or a Grid slot moved into the window, can
    therefore make a later scheduled Dump refuse at its start, and no health alert counts that refusal. **Warned by F4 (owner-approved 2026-10-20):** the Review
    notification carries the warning for charge source -> Grid and for a start-time edit on a slot with a charge source set; nothing checks
    or blocks it. Verified in the firmware source: Dump to Grid START refuses with "REJECTED - lease window overlaps TOU slot <n>, which has a charge source set" (firmware/ecco_clock_dongle_stage3_4_free_power.yaml, around line 18908; the conflict scan around line 17998).

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
| `home-assistant/tests/test_ecco_tou_slot_settings_edit.py` (candidate name: `test_ecco_acs_stage1_prototype.py`) | **277 checks passed** (about 210 s), as a candidate |
| `home-assistant/tests/test_ecco_tou_target_soc_edit.py` (ACS0; as integrated by acs1 it runs unchanged on the Stage 0 text unrendered from the installed package) | 162 checks passed |
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
   - the Stage 1 suite is a separate file (as built by acs1); the ACS0 suite keeps its name and path and runs unchanged on the ACS0
     text that `unrender_stage1` recovers from the installed package, so no pin is re-hashed;
   - decide whether the Stage 0 script ids stay as thin wrappers for existing callers;
   - no firmware, registry YAML or manifest change (same package path); one chain entry in `registry/tests`.
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
7. **Only then** consider using Stage 1 in place of SmartDeye for these fields (see Appendix A).

## 9. Owner decisions

1. Accept the transformation approach and the "Stage 1 replaces ACS0" integration (section 2).
2. Power floor 500 W, as chosen; or allow lower values knowing the fallback profile then blocks further edits until re-saved.
3. Charge source None/Grid only (generator values refused); confirm no generator is fitted.
4. Start-time policy: strictly ascending starts, 15-minute distance from now, and no edits on the clock-change nights.
5. Whether to keep the Stage 0 script names as wrappers for existing callers.
6. After a verified start-time edit, whether the editor should also press Load Current Slot N-1 (writes no register; closes
   residual 7 automatically) or only tell the owner to do so. **Decided 2026-10-20: the editor presses it (F1, owner-approved),
   with the plain-warning fallback when the Load is refused.**
7. Re-approval of the reserved-token amendment for the wider editor (section 2), before any integration PR.

Owner decisions of 2026-10-20 on the review findings (implemented in the integration branch, offline, not installed):
- **F1 approved:** Load Current Slot N-1 after a verified start-time edit (section 3).
- **F2 approved conditionally:** re-Load slot N only after a PROVEN outcome - a stop before the Apply press with the gate-pass counter
  unchanged since before the staging (after it published) and no write seen, or the firmware refusal proven by text, unchanged counter
  and both later reads; never after an UNCERTAIN, partial or unproven outcome, and uncertainty is never cleared automatically
  (section 3). The review corrected the first implementation, which took "nothing pressed" for "nothing written".
- **F3 approved:** a power edit is refused when the live slot power is not a multiple of 100 W; the requested value stays 500..8000 W
  in steps of 100.
- **F4 approved:** the Review notification carries the Dump to Grid charge-slot warning and the SmartDeye / inverter-panel advice.

## Appendix A. SmartDeye retirement: dependency inventory (offline, 2026-10-20)

This appendix is the requested SmartDeye retirement inventory. It is kept inside this document because the repository's
privacy curation (`tools/tests/test_public_privacy.py`) reserves file names beginning with `smartdeye` for private records
that must never be published; the content below is public-safe.

Status: **INVENTORY ONLY.** Nothing here disconnects, disables or changes SmartDeye, the inverter, Home Assistant or ECCO. It
does not say SmartDeye is safe to remove. Each item is graded:
- **GROUNDED**: stated in this repository (file named);
- **UNKNOWN**: not established anywhere here; the owner must confirm;
- **CANDIDATE**: built offline, not installed, not live-proven.

A Stage 1 settings GUI on its own is **not** a reason to retire SmartDeye.

### A.1. Why this matters

SmartDeye is a second actor on the inverter.
- `docs/dev/advanced-config/stage0-safety-case.md` names it "the documented second master" that must not be used at the same
  time as an ECCO edit.
- The fallback design (`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md` section 14) assumes other Modbus masters may reach
  the inverter, for example through a vendor logger.
- Its writes are invisible to the dongle (`tools/fbd1_soak/safety.py`: "Writes by a second Modbus master (for example a
  SmartDeye reader with writable clock controls) are invisible to the dongle").

Retiring it would remove that uncontrolled writer, which is good. It would also remove whatever the owner currently uses it
for, which must exist in ECCO first.

### A.2. Settings: what ECCO can do today versus SmartDeye

The owner-visible settings are the 165 capability-registry rows in the Advanced Configuration card
(`docs/dev/advanced-config/settings-map.md`).

| Group | Registers | ECCO status | Grade | Can replace SmartDeye for this today? |
|---|---|---|---|---|
| TOU slot target SOC | 268-273 | guarded edit (ACS0, `home-assistant/packages/ecco_tou_target_soc_edit.yaml`, merged); its installation and live-proof status are kept in the owner's project records | GROUNDED (package, `docs/dev/advanced-config/`) | yes, for this field, once installed |
| TOU slot power | 256-261 | firmware path proven (Manual Controls); Stage 1 guarded editor **CANDIDATE** (this branch) | GROUNDED / CANDIDATE | through Manual Controls only, until Stage 1 is integrated and live-proven |
| TOU slot start times | 250-255 | firmware path proven (5-minute grid; slot 6's end is slot 1's start); Stage 1 editor CANDIDATE | GROUNDED / CANDIDATE | as above |
| TOU charge source (None / Grid) | 274-279 bits 0-1 | firmware path proven; Stage 1 editor CANDIDATE (None / Grid only) | GROUNDED / CANDIDATE | as above; generator sources not supported |
| TOU slot mode bits | 274-279 bits 2-4 | partial proof; **not** in Stage 1 | GROUNDED (write assessment) | no |
| Grid-charge enable (global) | 232 bit 0 | rewritten by every slot Apply and by Free Power; no standalone control | GROUNDED | no standalone control |
| Load / export mode | 244 | proof transaction only (apply + restore); value 1 (Essentials) never exercised; no permanent "keep" | GROUNDED | **no** (needs a firmware "keep" step, Stage 2) |
| Global Power / Export Limit | 245 | read-only; owner decision 2026-10-08 | GROUNDED | **no** (Stage 3: firmware path, S3 write proof, hardware maximum, regulatory allowance) |
| Battery max charge / discharge current | 210/211 | read-only | GROUNDED | **no** (Stage 3: BMS evidence) |
| Shutdown / restart / low SOC | 217-219 | read-only, UNSUPPORTED for writing | GROUNDED | **no** |
| Energy pattern, TOU master enable | 243, 248 | read-only | GROUNDED | **no** |
| Grid charge current | 230 | written inside Free Power only; hardware maximum not established | GROUNDED | **no** standalone |
| Battery type / curve / protection, AUX, grid protection 287-290 | - | owner-locked (permanent) | GROUNDED | not intended |
| Generator, smart load, peak shaving | 223-227, 280, 292, 293 | read-only, further proof | GROUNDED | **no** |
| Six "SmartDeye parity" candidates (protocol version, rated power, serial, remote lock, island mode, battery charge voltage) | none found | unproven, no register identified | GROUNDED (settings-map rows 160-165) | **unknown**; not even readable |
| Register 214 (lithium wake-up) | 214 | read-only; ECCO decodes 0 = Enable, and **SmartDeye has displayed the opposite** on this inverter | GROUNDED (firmware ~8473, dashboard) | read-only by design until resolved |

**Which of these the owner actually changes with SmartDeye today: UNKNOWN.** This is the first item of the checklist (A.5).

### A.3. Non-setting dependencies

| Dependency | What is known | Grade | ECCO equivalent |
|---|---|---|---|
| SmartDeye's own **export automation** | ECCO's read-only flight recorder exists "for observing SmartDeye's own export automation" (`tools/ecco-flight-recorder.ps1`) | GROUNDED that it existed; whether it is still in use: UNKNOWN | Dump to Grid (manual, and the scheduled start in `home-assistant/packages/ecco_dump_to_grid_schedule.yaml`); whether unattended scheduled use is approved is an owner decision recorded outside this repository |
| **Inverter clock writes** | a SmartDeye reader may have writable clock controls (`tools/fbd1_soak/safety.py`) | GROUNDED as a possibility | ECCO automatic RTC correction (`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md` section 10); open clock-change items are tracked in the owner's project records |
| **TOU time helpers in Home Assistant** | `input_datetime.timezone*_time` "existing SmartDeye package TOU time helpers" are exported to InfluxDB (`influxdb/ecco_influxdb_options_v1_3.yaml`) | GROUNDED that the helpers exist | ECCO's own TOU sensors and Manual Controls |
| **A second Modbus master's bus traffic** | whether SmartDeye polls the same bus, and whether it causes the RTC stale-image pattern, is unresolved (the root cause of the stale image is UNKNOWN in the project records) | UNKNOWN | retiring SmartDeye would itself be evidence; it does not need to be decided first |
| Remote / cloud monitoring and app access | not recorded | UNKNOWN | ECCO dashboards are local to Home Assistant; no ECCO cloud access exists |
| Inverter firmware updates through the vendor channel | not recorded | UNKNOWN | none in ECCO (ECCO never updates inverter firmware) |
| Vendor data logging and history | not recorded | UNKNOWN | ECCO InfluxDB export (`ecco_raw`, `ecco_5m`, `ecco_daily`) |
| Grid-operator or installer access | not recorded | UNKNOWN | none |
| Fallback and resilience when Home Assistant is down | ECCO's failback is shadow-only; restore and automatic failback are not implemented (`FALLBACK_DESIGN_BASIS.md`) | GROUNDED | without SmartDeye, a Home Assistant outage leaves the inverter on its last settings; that is also true today |

### A.4. What retiring SmartDeye does not need

- It does not need Stage 2 or Stage 3 settings, **unless** the owner uses SmartDeye to change those settings.
- It does not need the whole 165-row catalogue to be writable. Most rows are read-only by design and should stay so.

### A.5. Owner checklist before any retirement (no physical action implied)

1. List what you change in SmartDeye today: each setting, roughly how often, and why. For anything outside the table's "yes"
   rows, ECCO is not ready.
2. Say whether SmartDeye's export automation is still active, and what it does (times, power, conditions). It must be either
   unneeded or replaced by an ECCO schedule you have explicitly approved for that use.
3. Say whether SmartDeye writes the inverter clock (its clock controls), so that ECCO is the only clock writer afterwards.
4. Say whether you use SmartDeye's app, remote access or cloud history, and whether you can live without it or need an
   alternative.
5. Say whether the vendor channel is how the inverter's own firmware would be updated or serviced. If it is, plan how to keep that
   possible (for example a temporary reconnection for service).
6. The editors you will use must be **installed and live-proven**, not just built offline:
   - ACS0 target SOC: check its status in your project records;
   - Stage 1 power, start times and charge source: candidate only.
7. A rollback path: keep SmartDeye available (not destroyed) until ECCO has run for an agreed period without it.
8. Only then plan a supervised, reversible disconnection, as a separate approved job. It needs a before/after check of the bus,
   the RTC stall rate, B10 and health.

### A.6. What this inventory deliberately does not claim

- That SmartDeye is safe to remove.
- That Stage 1 is installed or live-proven.
- That SmartDeye causes any ECCO symptom.
- Anything about SmartDeye features not recorded in this repository.
