# Advanced Configuration Stage 1: integration of the guarded TOU settings editor (post-export entry `acs1`)

Status: **SOURCE ONLY. NOT INSTALLED. NOT LIVE-PROVEN. NO REGISTER WRITTEN. NO NEW FIRMWARE WRITE SCOPE.** Offline, local work on
branch `dev/acs-stage1-integration`, based on public main `e7a265b8`. Nothing in this change touches Home Assistant, the dongle,
the inverter or InfluxDB.

**PENDING OWNER RE-APPROVAL.** The 2026-10-12 reserved-token amendment (Option A) was approved for a SOC-only editor. This change
widens what the declared package does (power, start time and charge source) while it reads exactly the same six reserved entity
ids in the same three declared files. It adds no new holder file and amends no frozen allowlist. Whether that is covered by the
amendment is the owner's decision, to be taken before this is merged (candidate document section 9, item 7).

The reuse proof, the per-setting matrix, the refusal and rollback contract, the residual risks and the GUI storyboard are in
[acs-stage1-local-candidate.md](acs-stage1-local-candidate.md); this document covers only what the integration changes and how it is
installed, checked and rolled back.

## 1. What changes

| Area | Before | After |
|---|---|---|
| Package `home-assistant/packages/ecco_tou_target_soc_edit.yaml` | Stage 0 editor: target SOC only | Stage 1 editor: one setting of one slot (target SOC, power, start time, charge source). Same path, so the deployment manifest is unchanged |
| Review script | `script.ecco_cfg_review_tou_slot_soc` (fields `slot`, `target_soc`) | `script.ecco_cfg_review_tou_slot_setting` (fields `slot`, `setting`, `value`) |
| Apply script | `script.ecco_cfg_apply_tou_slot_soc` (field `confirmation`) | `script.ecco_cfg_apply_tou_slot_setting` (field `confirmation`) |
| Plan record `input_text.ecco_cfg_edit_review` | 5 fields: `slot\|want\|code\|time\|before` | 6 fields: `slot\|setting\|want\|code\|time\|before` |
| Typed phrase | `SET SLOT n TARGET SOC x REVIEW code` | the same for the SOC; `SET SLOT n POWER w W REVIEW code`, `SET SLOT n START HH:MM REVIEW code`, `SET SLOT n CHARGE SOURCE GRID\|NONE REVIEW code` |
| Helpers, acknowledge script, watchdog automation | `ecco_cfg_*` helpers, `script.ecco_cfg_acknowledge_edit_review`, automation `ecco_cfg_edit_interrupted` | **unchanged ids and definitions** (the suite proves the helper definitions are identical, so their state persists across a reload) |
| Staged values the editor sets | the slot's target SOC number | the slot's target SOC, power and start-time numbers; the slot's charge-source select (`select_option` Grid, `select_first` None). Never the end number, the mode select or the grid-charge switch |
| Safety gate | fail-closed, reads six reserved ids | the same lines byte for byte (20 lines), plus the Stage 1 policy refusals (below) |
| Firmware, registry, manifest, dashboards, frontend | - | **not changed** |

Policy values integrated **as built, not yet approved by the owner** (candidate document section 9): power 500-8000 W in steps of
100; charge source None or Grid only; start times strictly ascending, on the 5-minute grid, at least 15 minutes from now, never
switching the active slot, inverter clock within 120 s of Home Assistant's; no edit 00:00-03:00 local on the UK clock change nights
(last Sunday of March and of October), for every setting, the target SOC included. The old Stage 0 script ids are **not** kept as
wrappers; nothing in the repository other than documents referred to them.

The files:

| File | Role |
|---|---|
| `home-assistant/packages/ecco_tou_target_soc_edit.yaml` | the installed Stage 1 package (byte for byte `render_stage1` of the Stage 0 text) |
| `home-assistant/prototypes/acs-stage1/acs_stage1_transform.py` | provenance: 40 exact (before, after, count) pairs, `render_stage1`, and the inverse `unrender_stage1`; pins the Stage 0 base's sha256, the installed package's sha256 and a sha256 over the 40 pairs. No longer a prototype: it documents how the installed package was derived |
| `home-assistant/tests/test_ecco_tou_slot_settings_edit.py` | the Stage 1 suite (renamed from the prototype suite): tests the installed file directly, plus the provenance checks |
| `home-assistant/tests/test_ecco_tou_target_soc_edit.py` | the Stage 0 suite, same name and path (a declared reserved-token holder): it now proves the Stage 0 BASELINE, running unchanged on `unrender_stage1(installed)` (asserted to be the pinned Stage 0 text). The installed editor's own behaviour, SOC parity included, is proven by the Stage 1 suite |
| `registry/tests/_acs1_scope.py`, `_scope_chain.py` | the chain entry `acs1` (declaration, fingerprint) |

## 2. Provenance without git history

CI checks out most jobs with depth 1, so nothing relies on history.

- `unrender_stage1(installed)` applies the pairs in reverse order as (after -> before), each with its exact count, and raises on any
  mismatch. The suite proves: the result is the Stage 0 text, whose sha256 is `9fa32b9bb843cfc7b42bae9ed7c06a50f461e564d7f0609e2536c28968d6affe`
  (pinned in the transform, in the suite and in the scope module); `render_stage1` of it is the installed package, whose sha256 is
  `8af4d4392c4f406aef16d9aa76f011da4be964be3085b3a595e4966346beae89`; a text that is neither raises, naming the pair.
- To make the inverse exact, the two script-id renames became the first two pairs of the transform (previously the last two).
  The rendered text is unchanged.
- The Stage 0 text is the file a rollback restores (section 6).
- The chain entry `acs1` declares **no reverter and no checkpoint**, deliberately: the package is an `added_files` entry of `acs0`,
  neither chain-pinned nor frozen. The chain refuses a reverter for an unpinned artifact and the PEX report a frozen edit to a
  non-frozen file; public PRs #31 and #32 edited the package without a chain entry for the same reason. No chain-pinned or frozen file
  and no reserved-token allowlist is edited. The four reserved-token suites are unchanged and pass.

## 3. Install procedure (owner-run; each live step needs its own authorisation)

Nothing here is done by this change.

**Reload or restart: an owner decision.** `deployment/ha-manifest.yaml` lists this package with `restart_required: true` (and its
comment, lines 66-67, still describes the SOC-only Stage 0 editor; that text is **stale** after this change, but rewording it is a
chain-pinned manifest edit and an owner decision, so it is left as it is). The acs0r1 update kit installed the package with script and
automation reloads. For this replacement the helper definitions are byte-identical, so a reload is sufficient and this document
describes it; a restart is the manifest's stated method and is also acceptable when the editor is idle. The owner chooses.

**The editor must be IDLE before the swap.** Both scripts off (no Review or Apply running), `input_boolean.ecco_cfg_edit_in_flight`
off, and the review-required lock off or acknowledged. If an Apply is in flight when the automations are reloaded, the watchdog's
template trigger does not fire again after the reload; the in-flight marker then stays on and every Review, Apply and Acknowledge
refuses until a Home Assistant restart. Do not swap during an edit.

**New dependencies, to be verified before the swap (read-only).** The Stage 1 gate needs entities the Stage 0 package did not read,
and an unavailable one now makes even a target-SOC Review refuse: the six `sensor.ecco_clock_dongle_ecco_timezoneN_raw_flags`
(the raw flags are a precondition for every setting, SOC included), the six `sensor.ecco_clock_dongle_ecco_timezoneN_time` with valid
HH:MM values, `sensor.ecco_clock_dongle_inverter_time`, the six `number.ecco_clock_dongle_manual_slot_N_power` and
`..._start_hhmm`, and the six `select.ecco_clock_dongle_manual_slot_N_charge_source` (first option None). Check that each exists, is
not unavailable or unknown, and is numeric or a valid time where applicable, in Developer tools, States.

1. **Preconditions.** No Free Power or Dump to Grid session, schedule or recovery active or armed within the next 60 minutes; no
   fallback Review or Save open; `input_boolean.ecco_cfg_edit_in_flight` off and `input_boolean.ecco_cfg_edit_review_required`
   off (no edit running, none awaiting acknowledgement); not on a UK clock change night.
2. **Record the Stage 0 baseline (read-only).** Run the old *ECCO - Review a TOU slot target SOC edit* (Review writes nothing) for a
   few cases on slot 3 and note each result text: a value in range, the current value (no change), a value below the reserve. Do not
   run any Apply.
3. **Fresh full Home Assistant backup.**
4. **Copy one file**, `home-assistant/packages/ecco_tou_target_soc_edit.yaml`, to `/config/packages/ecco_tou_target_soc_edit.yaml`
   with the project's usual method. Keep the file it replaces (or the backup) for the rollback.
5. **`ha core check`** (or Developer tools, Check configuration) must pass.
6. **One `script.reload` and one `automation.reload`** (or a restart, per the decision above).

## 4. Acceptance checks before any live write (all read-only)

- The new scripts exist: `script.ecco_cfg_review_tou_slot_setting` and `script.ecco_cfg_apply_tou_slot_setting`; the two old
  ids are gone; `script.ecco_cfg_acknowledge_edit_review` exists.
- The watchdog automation `ecco_cfg_edit_interrupted` exists and is on.
- Nothing is armed: the Manual Configuration Write Enable is off, the in-flight marker and the review-required lock are off, and
  the plan and last-result helpers kept their values across the reload.
- **The old SOC Review behaves exactly as before.** Run the new Review with `setting: target_soc` on the same slot and values as in
  step 2 of the install: it must be refused or allowed for the same reasons, with the same range text. The one deliberate
  difference is the clock-change-night rule (the target SOC is refused 00:00-03:00 on those nights).
- Review for each other setting on an inactive slot refuses or accepts as the candidate document describes; **never press Apply
  during the acceptance checks.**

## 5. Supervised live proof (one setting at a time; every step needs the owner's approval)

As in candidate document section 8, step 5. Slot not active and far from its boundaries; each step followed at once by its undo;
SmartDeye and the inverter panel not used during the proof; Home Assistant set to Europe/London.

1. Power 8000 -> 7900 -> 8000 W.
2. Charge source on an inactive slot, None -> Grid -> None, outside any cheap-rate window (exercises both `select_option` and
   `select_first`).
3. Start time moved by 5 minutes and back, then Load All before any Manual Controls use (residual risk 7).

For every step check: `VERIFIED OK`; two later reads; the fallback status DRIFT or CONTEXT, then MATCH after the undo; no other
register changed; health unchanged. The target SOC path is re-checked read-only by section 4 (the Stage 0 editor's own live-proof status is kept in the owner's project records, not in this repository).

## 6. Rollback

Rollback is a file restore plus a reload. **No inverter action is needed**: the editor writes nothing by itself, and a completed
edit stays on the inverter exactly as any other TOU change. **ACS0 cannot undo a Stage 1 power, start-time or charge-source edit** (it
edits the target SOC only): if such an edit must go back, undo it with the Stage 1 editor BEFORE the rollback. After any start-time
edit, press Load All (or Load Current Slot N-1) before any Manual Controls Apply (residual risk 7 of the candidate document).

1. **Wait for any edit to be judged.** If an Apply is running or `input_boolean.ecco_cfg_edit_in_flight` is on, or the lock
   `input_boolean.ecco_cfg_edit_review_required` is on after an UNCERTAIN outcome, do not roll back yet: let the Apply finish, or
   acknowledge the lock (`script.ecco_cfg_acknowledge_edit_review`) after checking the TOU slots. A reload during an Apply is caught
   by the watchdog and locks the editor, which is safe but leaves an UNCERTAIN record to acknowledge.
2. **Restore the previous package file** to `/config/packages/ecco_tou_target_soc_edit.yaml`: the copy kept at install time, or the
   Stage 0 text rebuilt offline from the installed Stage 1 file (the suite proves it is the old file byte for byte). From a
   checkout of the Stage 1 source, in a PowerShell window:

```powershell
cls
python -I -B -c "import sys, hashlib, pathlib; sys.path.insert(0, 'home-assistant/prototypes/acs-stage1'); import acs_stage1_transform as X; u = X.unrender_stage1(pathlib.Path('home-assistant/packages/ecco_tou_target_soc_edit.yaml').read_text(encoding='utf-8')); assert hashlib.sha256(u.encode()).hexdigest() == X.ACS0_BASE_SHA256; pathlib.Path(sys.argv[1]).write_text(u, encoding='utf-8', newline='\n')" "$env:TEMP\ecco_tou_target_soc_edit.yaml"
```

3. `ha core check`, then the same reloads (or restart) as at install, with the same idle precondition. The helpers are unchanged, so
   their state persists.
4. Run the same read-only acceptance checks as in section 4 with the old ids. Confirm the old ids `script.ecco_cfg_review_tou_slot_soc` and `script.ecco_cfg_apply_tou_slot_soc` are back and the new ones are gone;
   nothing armed.

## 7. Verification of this change (offline; `python -I -B`)

The Stage 1 suite, the adapted Stage 0 suite, the four frozen reserved-token suites, `registry/tests/test_pex_transition.py`,
`test_scope_chain.py`, `test_pub0_transition.py`, `test_pub0_privacy.py`, `test_write_surface_invariants.py`, the three suites that
scan all of `home-assistant/`, `tools/validate_repo.py`, `tools/tests/test_public_privacy.py` and `tools/run_offline_tests.py`
all run; the results are recorded in the pull request, not here. `tools/analyze_write_surface.py` shows no change.

Not provable offline, and the reason for sections 4 and 5: real Home Assistant service schemas and time zone; whether the inverter
accepts and keeps the written power, start-time and charge-source values; register 232's other bits; a torn multi-register write.
