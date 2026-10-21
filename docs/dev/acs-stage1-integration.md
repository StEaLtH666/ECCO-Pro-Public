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
| Helpers, acknowledge script, watchdog automation | `ecco_cfg_*` helpers, `script.ecco_cfg_acknowledge_edit_review`, automation `ecco_cfg_edit_interrupted` | Stage 0's ids and definitions are **unchanged** (the suite proves the three text helpers, the two booleans, the acknowledge script and the watchdog are as before, so their state persists across a reload). **New:** the helper `input_boolean.ecco_cfg_edit_write_seen` and the automation `ecco_cfg_edit_write_seen` (the F2 proof below) |
| Staged values the editor sets | the slot's target SOC number | the slot's target SOC, power and start-time numbers; the slot's charge-source select (`select_option` Grid, `select_first` None). Never the end number, the mode select or the grid-charge switch |
| Safety gate | fail-closed, reads six reserved ids | the same lines byte for byte (20 lines), plus the Stage 1 policy refusals (below) |
| Staging refresh after a start-time edit (F1) | the success notice told the owner to press Load Current Slot N-1 | the editor presses Load Current Slot N-1 itself (slot 1 -> slot 6) after the VERIFIED edit and verifies that slot's staged end; if the Load is refused or does not match, the edit stays successful and the notice says plainly that the staging could not be refreshed |
| Staging refresh after a FAILED run (F2) | slot N's staging kept the reviewed value | slot N is re-Loaded, and verified equal to the live slot, ONLY after a PROVEN outcome: (a) the run stopped after staging and before the Apply press AND the firmware's gate-pass counter is unchanged since before the staging (after it had time to publish), with no write-in-progress and no write text seen; or (b) the firmware refused at its gate: refusal text AND unchanged counter AND both later reads at pre-edit values. Everything else is UNCERTAIN with the lock and no re-Load |
| `nothing pressed` is no longer taken to mean `nothing written` (deliberately stricter than Stage 0, SOC edits included) | a run that stopped before the press reported "nothing written" without proof | the write enable is shared and the firmware accepts ANY Apply press while it is on, so an Apply by someone else can land in the armed window; the editor now records the gate-pass counter before staging, disarms at once when it stops, waits 35 s for the counter to publish and claims "nothing written" only with the proof; otherwise UNCERTAIN, locked, with the observed values |
| Live power rule (F3) | - | a power edit is refused when the LIVE slot power is not a multiple of 100 W, at the Review and at every later gate copy |
| Review notification (F4) | - | always "Do not use SmartDeye or the inverter's own panel until this edit is finished."; charge source -> Grid and a start-time edit on a slot whose live source is not None also carry the Dump to Grid charge-slot warning |
| Success verdict (N2, owner-approved 2026-10-21) | APPLIED AND VERIFIED needed the firmware's `VERIFIED OK` and two later reads | additionally the firmware's gate-pass counter must have moved by EXACTLY 1 since before the staging (read at the verdict, at least 37 s after the Apply press, after the counter published); 0, 2 or more, a reset or an unreadable counter is UNCERTAIN with the lock, the manual-recovery notification (counter before and after, the delta, "another Apply - possibly of a different slot - may have run"), no undo offer, no F1 Load and no re-Load. Stricter than Stage 0, SOC edits included |
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
| `home-assistant/prototypes/acs-stage1/acs_stage1_transform.py` | provenance: 62 exact (before, after, count) pairs (the 40 reviewed candidate pairs plus 22 follow-up pairs for F1-F4, the F2 proof and N2), `render_stage1`, and the inverse `unrender_stage1`; pins the Stage 0 base's sha256, the installed package's sha256 and a sha256 over the 40 pairs. No longer a prototype: it documents how the installed package was derived |
| `home-assistant/tests/test_ecco_tou_slot_settings_edit.py` | the Stage 1 suite (renamed from the prototype suite): tests the installed file directly, plus the provenance checks |
| `home-assistant/tests/test_ecco_tou_target_soc_edit.py` | the Stage 0 suite, same name and path (a declared reserved-token holder): it now proves the Stage 0 BASELINE, running unchanged on `unrender_stage1(installed)` (asserted to be the pinned Stage 0 text). The installed editor's own behaviour, SOC parity included, is proven by the Stage 1 suite |
| `registry/tests/_acs1_scope.py`, `_scope_chain.py` | the chain entry `acs1` (declaration, fingerprint) |

## 2. Provenance without git history

CI checks out most jobs with depth 1, so nothing relies on history.

- `unrender_stage1(installed)` applies the pairs in reverse order as (after -> before), each with its exact count, and raises on any
  mismatch. The suite proves: the result is the Stage 0 text, whose sha256 is `9fa32b9bb843cfc7b42bae9ed7c06a50f461e564d7f0609e2536c28968d6affe`
  (pinned in the transform, in the suite and in the scope module); `render_stage1` of it is the installed package, whose sha256 is
  `271beb523bb8c23971eac7d9ed6c953a14b1dbe102a905ba79c0674040e25f0d`; a text that is neither raises, naming the pair.
- To make the inverse exact, the two script-id renames became the first two pairs of the transform (previously the last two).
  The rendered text of the reviewed candidate is unchanged (sha256 `8af4d439...`, the value before F1-F4).
- **Follow-up pairs.** F1-F4 (owner-approved 2026-10-20), the F2 correction (review finding: "nothing pressed" is not "nothing written") and
  N2 (owner-approved 2026-10-21) were added by APPENDING 22 exact pairs (indices 40-61) to the transform; the 40 reviewed pairs are not
  edited or reordered, and `unrender_stage1(installed)` still gives the Stage 0 text, sha256 `9fa32b9b...`. Pins changed in steps
  (transform, Stage 1 suite and `_acs1_scope.py`): the installed package `STAGE1_SHA256` `8af4d439...` (the reviewed candidate) ->
  `271beb52...` (F1-F4) -> `4cafc192...` (F2 proof) -> `2e8813973d133b7bd25fe273af16403af4cea0b8e64b338a015f35412346e9de` (N2), and `PAIRS_SHA256` `1a49696d...` -> `68a7071b...` -> `13ffda0d...` ->
  `9924673e2c512edb4048b897aa073c779727d88aa453c345eac0934f29d75a37`. The chain entry's declared fields and note are unchanged, so its fingerprint is unchanged.
- The Stage 0 text is what a rollback is built from if the previously installed file was not kept (section 6). It is the GENERIC text
  (default device slug `ecco_clock_dongle`); the file on a site is a site render of it.
- The chain entry `acs1` declares **no reverter and no checkpoint**, deliberately: the package is an `added_files` entry of `acs0`,
  neither chain-pinned nor frozen. The chain refuses a reverter for an unpinned artifact and the PEX report a frozen edit to a
  non-frozen file; public PRs #31 and #32 edited the package without a chain entry for the same reason. No chain-pinned or frozen file
  and no reserved-token allowlist is edited. The four reserved-token suites are unchanged and pass.
- **Merge order.** `acs1` is sealed to its parent `hd1` (its fingerprint hashes hd1's). If another post-export entry merges first,
  `acs1` must be re-sealed on top of it: recompute the fingerprint with `_pex.sealed`, then update together the fingerprint literal in
  `registry/tests/_scope_chain.py`, `ACS1_FINGERPRINT` and `HD1_FINGERPRINT` (the new parent's) and the entry-position check in the
  Stage 1 suite, and the position of `ACS1` in `POST_EXPORT_ENTRIES`.
- **Future edits of the package.** The record is exact only while the package is `render_stage1()` of the Stage 0 text. Any later edit
  must APPEND pairs to the transform and update its three pins (the transform's `STAGE1_SHA256` / `PAIRS_SHA256`, the Stage 1 suite's
  `S1_SHA` / `PAIRS_SHA`, and `_acs1_scope.py`'s `STAGE1_PACKAGE_SHA256` / `PAIRS_SHA256`), or deliberately retire the mechanism with a
  new chain entry that says so. An unpinned edit fails the Stage 1 suite.
- The Stage 1 suite also proves that everything of the Stage 0 baseline that no pair touches (834 of its 1003 lines wholly outside
  the 40 reviewed pairs, with the 22 follow-up pairs undone exactly first, and the rest of the text in the same places) is byte-identical in the installed package, so the acs0r1 press timing and
  the fresh-evidence code are proven on the installed file; it kills mutants that alter one such line.

## 3. Install procedure (owner-run; each live step needs its own authorisation)

Nothing here is done by this change. The repository is generic (device slug `ecco_clock_dongle`); a site installs a **site render**,
never the repository file itself.

**Reload or restart: an owner decision.** `deployment/ha-manifest.yaml` lists this package with `restart_required: true` (and its
comment, lines 66-67, still describes the SOC-only Stage 0 editor; that text is **stale** after this change, but rewording it is a
chain-pinned manifest edit and an owner decision, so it is left as it is). The acs0r1 update kit installed the package with script and
automation reloads. Both are possible: a restart is the manifest's stated method; a reload is sufficient: Stage 0's helpers, scripts and watchdog keep their
definitions (the suite proves it), and the one NEW helper (`input_boolean.ecco_cfg_edit_write_seen`) and the one NEW automation
(`ecco_cfg_edit_write_seen`) are created by the `input_boolean` reload and the `automation.reload` of the sequence below. The owner
chooses. The reload sequence below is the one to use if reloading.

**The editor must be IDLE before the swap, and this is mandatory.** Both scripts off (no Review or Apply running),
`input_boolean.ecco_cfg_edit_in_flight` off, and the review-required lock off or acknowledged. The watchdog does NOT protect a swap:
the Apply script's id changes, so the old watchdog sees the old script disappear while the new watchdog's condition is already true
and does not fire. An Apply in flight during the swap leaves the in-flight marker on, and every Review, Apply and Acknowledge then
refuses until a Home Assistant restart.

**New dependencies, to be verified before the swap (read-only).** The Stage 1 gate reads entities the Stage 0 package did not, and an
unavailable one makes even a target-SOC Review refuse. In Developer tools, States, check that each exists, is not unavailable or
unknown, and is numeric or a valid time where applicable. Entity ids below use the default device slug: replace `ecco_clock_dongle`
by your device slug.
- the six `sensor.ecco_clock_dongle_ecco_timezoneN_raw_flags` (the raw flags are a precondition for every setting, the target SOC
  included);
- the six `sensor.ecco_clock_dongle_ecco_timezoneN_time`, each a valid HH:MM;
- `sensor.ecco_clock_dongle_inverter_time`;
- the six `number.ecco_clock_dongle_manual_slot_N_power` and the six `number.ecco_clock_dongle_manual_slot_N_start_hhmm`;
- the six `select.ecco_clock_dongle_manual_slot_N_charge_source` (first option None).

Steps:

1. **Preconditions.** The idle condition above. No Free Power or Dump to Grid session, schedule or recovery active or armed within
   the next 60 minutes; no fallback Review or Save open; not on a UK clock change night.
2. **Record the Stage 0 baseline (read-only).** Run the old *ECCO - Review a TOU slot target SOC edit* (Review writes nothing) for a
   few cases on slot 3 and note each result text: a value in range, the current value (no change), a value below the reserve. Do not
   run any Apply. (A Review leaves a harmless plan record that expires after 10 minutes; do it BEFORE the swap and let the editor
   settle.)
3. **Fresh full Home Assistant backup.**
4. **Keep a byte copy of the package that is installed now** (`/config/packages/ecco_tou_target_soc_edit.yaml`) outside the Home
   Assistant configuration, and record its sha256:

```powershell
cls
Get-FileHash -Algorithm SHA256 "<your kept copy of ecco_tou_target_soc_edit.yaml>"
```

5. **Render the package for your site** with the repository's own tool and your local, git-ignored site file (schema in
   `ecco_site.example.yaml`). From the repository root of the Stage 1 source:

```powershell
cls
python -I -B tools/ecco_site_render.py --site ecco_site.local.yaml --dry-run
python -I -B tools/ecco_site_render.py --site ecco_site.local.yaml
```

   The first command reports and writes nothing; the second writes the rendered copies below `dist/site` (the default `--out`,
   git-ignored), here `dist/site/home-assistant/packages/ecco_tou_target_soc_edit.yaml`. Nothing is rendered in place.
6. **Copy the RENDERED file** (not the repository file) to `/config/packages/ecco_tou_target_soc_edit.yaml` with the project's usual
   method.
7. **`ha core check`** (or Developer tools, Check configuration) must pass.
8. **Reload in this order** (or restart, per the decision above): reload the `input_text` and `input_boolean` helpers (Stage 0's
   definitions are unchanged, so their state persists; the reload creates the NEW helper `input_boolean.ecco_cfg_edit_write_seen`);
   `script.reload`; confirm the two new scripts exist and the two old `_soc` ones are gone; only then `automation.reload`; confirm the
   watchdog automation `ecco_cfg_edit_interrupted` and the new recorder `ecco_cfg_edit_write_seen` exist and are on, and the new helper
   exists and is off.

## 4. Acceptance checks before any live write (all read-only)

- The new scripts exist: `script.ecco_cfg_review_tou_slot_setting` and `script.ecco_cfg_apply_tou_slot_setting`; the two old
  ids are gone; `script.ecco_cfg_acknowledge_edit_review` exists.
- The watchdog automation `ecco_cfg_edit_interrupted` exists and is on; the write recorder `ecco_cfg_edit_write_seen` exists and is on,
  and `input_boolean.ecco_cfg_edit_write_seen` exists and is off.
- Nothing is armed: the Manual Configuration Write Enable is off, the in-flight marker and the review-required lock are off, and
  the plan and last-result helpers kept their values across the reload.
- **The old SOC Review behaves exactly as before.** Run the new Review with `setting: target_soc` on the same slot and values as in
  step 2 of the install: it must be refused or allowed for the same reasons, with the same range text. The one deliberate
  difference is the clock-change-night rule (the target SOC is refused 00:00-03:00 on those nights).
- Review for each other setting on an inactive slot refuses or accepts as the candidate document describes; **never press Apply
  during the acceptance checks.**
- **The follow-up behaviours that a Review shows** (read-only):
  - every Review notification says "Do not use SmartDeye or the inverter's own panel until this edit is finished.";
  - a Review of a charge source -> Grid, and of a start-time edit on a slot whose live charge source is not None, also carries the
    Dump to Grid charge-slot warning; a power or SOC Review does not;
  - a power Review is refused with "the live slot power X W is not a multiple of 100 W; the undo would be refused - align it first in
    Manual Controls" when the live slot power is not a multiple of 100 (check the six slots' live power first; a target-SOC Review on
    such a slot is not affected);
  - every input_text helper value (plan, last result, last owner edit) stays under 255 characters.

## 5. Supervised live proof (one setting at a time; every step needs the owner's approval)

As in candidate document section 8, step 5. Slot not active and far from its boundaries; each step followed at once by its undo;
SmartDeye and the inverter panel not used during the proof; Home Assistant set to Europe/London.

1. Power 8000 -> 7900 -> 8000 W.
2. Charge source on an inactive slot, None -> Grid -> None, outside any cheap-rate window (exercises both `select_option` and
   `select_first`).
3. Start time moved by 5 minutes and back. After each verified start-time edit expect exactly one Load Current Slot N-1 (slot 6 for
   slot 1) pressed by the editor, and in Manual Controls the slot N-1 staged end equal to the new boundary; the success notice says
   the staging was refreshed. (If it says the staging could not be refreshed, press Load Current Slot N-1 or Load All before any
   Manual Controls use.) A SOC, power or charge-source edit presses no extra Load.

For every step check: `VERIFIED OK`; the Manual Configuration Write Attempts Since Boot sensor moved by exactly 1 (read it before the Review and about a minute after the Apply; a different delta means another Apply ran and the editor reports UNCERTAIN); two later reads; the fallback status DRIFT or CONTEXT, then MATCH after the undo; no other
register changed; health unchanged. The target SOC path is re-checked read-only by section 4 (the Stage 0 editor's own live-proof status is kept in the owner's project records, not in this repository).

## 6. Rollback

Rollback is a file restore plus a reload. **No inverter action is needed**: the editor writes nothing by itself, and a completed
edit stays on the inverter exactly as any other TOU change. **ACS0 cannot undo a Stage 1 power, start-time or charge-source edit** (it
edits the target SOC only): if such an edit must go back, undo it with the Stage 1 editor BEFORE the rollback. After any start-time
edit, press Load All (or Load Current Slot N-1) before any Manual Controls Apply (residual risk 7 of the candidate document).

1. **The editor must be idle** (same mandatory condition as the install). If an Apply is running, or
   `input_boolean.ecco_cfg_edit_in_flight` is on, or the lock `input_boolean.ecco_cfg_edit_review_required` is on after an UNCERTAIN
   outcome, do not roll back yet: let the Apply finish, or acknowledge the lock (`script.ecco_cfg_acknowledge_edit_review`) after
   checking the TOU slots. The watchdog does not protect a swap (section 3).
2. **Restore the previously installed file: the byte copy kept at install time** (preferred). Check its sha256 against the one
   recorded at install.
3. **If that copy is lost**, rebuild it: the Stage 0 text is `unrender_stage1(<the repository package>)`, a generic (default slug)
   text which the Stage 1 suite proves equals the pinned Stage 0 package (sha256 `9fa32b9b...`). The file that ran on a site was a site
   render of that text, so render it with the same site file and compare the sha256 with the recorded one, if you have it. In a
   scratch checkout of the Stage 1 source (never your working checkout), in a PowerShell window:

```powershell
cls
python -I -B -c "import sys, hashlib, pathlib; sys.path.insert(0, 'home-assistant/prototypes/acs-stage1'); import acs_stage1_transform as X; p = pathlib.Path('home-assistant/packages/ecco_tou_target_soc_edit.yaml'); u = X.unrender_stage1(p.read_text(encoding='utf-8')); assert hashlib.sha256(u.encode()).hexdigest() == X.ACS0_BASE_SHA256; p.write_text(u, encoding='utf-8', newline='\n')"
python -I -B tools/ecco_site_render.py --site ecco_site.local.yaml
Get-FileHash -Algorithm SHA256 dist/site/home-assistant/packages/ecco_tou_target_soc_edit.yaml
```

   (`ecco_site.local.yaml` is your local site file, copied into the scratch checkout.) Install the rendered file, not the generic one.
4. `ha core check`, then the same reloads (or restart) as at install, in the same order, with the same idle precondition. The helpers
   are unchanged, so their state persists. The rollback leaves the helper `input_boolean.ecco_cfg_edit_write_seen` behind as an orphan
   (restored state without a definition): harmless, nothing references it, and it is gone after the next restart or when it is deleted in the
   entity registry. The recorder automation disappears with the file.
5. Run the same read-only acceptance checks as in section 4, with the old ids: `script.ecco_cfg_review_tou_slot_soc` and
   `script.ecco_cfg_apply_tou_slot_soc` are back, the new ones are gone, the watchdog exists, nothing is armed.

## 7. Verification of this change (offline; `python -I -B`)

The Stage 1 suite, the Stage 0 suite (it runs unchanged on the Stage 0 text unrendered from the installed package), the four frozen reserved-token suites, `registry/tests/test_pex_transition.py`,
`test_scope_chain.py`, `test_pub0_transition.py`, `test_pub0_privacy.py`, `test_write_surface_invariants.py`, the three suites that
scan all of `home-assistant/`, `tools/validate_repo.py`, `tools/tests/test_public_privacy.py` and `tools/run_offline_tests.py`
all run; the results are recorded in the pull request, not here. `tools/analyze_write_surface.py` shows no change.

Not provable offline, and the reason for sections 4 and 5: real Home Assistant service schemas and time zone; whether the inverter
accepts and keeps the written power, start-time and charge-source values; register 232's other bits; a torn multi-register write.

## 8. Residual risks to know about before the live proof

Each is also in the candidate document (section 5). Items marked "decided" were settled by the owner on 2026-10-20 and are implemented
offline in this change; the rest remain documented.

- **A FAILED run after staging leaves the edited value loaded in slot N's Manual Controls staging.** Decided (F2, conditional, as
  corrected by the review): the editor re-Loads slot N, and verifies its staging equals the live slot, only after a PROVEN outcome. (a)
  The run stopped after the staging and before the Apply press, AND the firmware's gate-pass counter is unchanged since before the
  staging (read after the 35 s it needs to publish), AND no write-in-progress and no write text was seen since (the recorder
  automation and the flag), AND the counter was readable. (b) The firmware refused at its gate with the refusal text, an unchanged
  counter and both later reads at pre-edit values. Anything else that stopped before the press - the counter moved, unreadable, a write
  seen - is **UNCERTAIN with the lock, the existing manual-recovery notification (listing the observed values) and no re-Load**, and so
  is every other unproven outcome. This is a deliberate, stricter difference from Stage 0 and applies to SOC edits too: Stage 0 reported
  "nothing pressed, nothing written" for a run that stopped while the editor was armed, although the shared write enable lets the firmware
  accept ANY Apply press in that window (an Apply by someone else wrote the inverter in the reproduction). If a proven re-Load is
  refused, the FAILED notice says slot N's staging may still hold the reviewed value and to press Load Current Slot N before any
  Manual Controls Apply.
- **An Apply by someone else inside the armed window or while the outcome is judged (closed by N2, owner-approved 2026-10-21).** The
  success verdict needs the firmware's gate-pass counter to have moved by EXACTLY 1. The counter is incremented only when an Apply passes
  its gate (the six slot Apply paths in the firmware; the Load buttons and every other flow leave it alone) and publishes every 30 s. It is
  read where the verdict is judged, after the two later configuration reads and a 35 s delay that follow the Apply press, so at least 37 s
  after the press and a delta of 0 cannot arise from a not-yet-published counter. Delta 2 or more (the editor's Apply passed AND another
  actor's Apply, of the same or another slot, passed: before the verdict is judged), 0, a reset or an unreadable counter is UNCERTAIN with
  the lock and the manual-recovery notification, before F1's Load, with no undo offer. The documented caveat: if another actor's Apply of the
  reviewed staging wrote the value and the editor's own press was refused by the firmware (a write was already running), the delta is exactly
  1, the final state is the requested one and verified, and the run stays APPLIED AND VERIFIED (the verdict cannot tell who pressed). If the
  other actor's write-in-progress flag is visible at the editor's last check, the run stops before its press and is UNCERTAIN (above).
  A conservative limit: an Apply that passed just before the staging but whose counter had not yet been published when the counter was
  recorded also reads as delta 2 and gives UNCERTAIN.
- **The write-seen recorder is edge-triggered** (it fires when its condition turns true). A write already in progress when the staging
  window begins therefore does not fire it again, but it is still caught by the three other proofs: the gate-pass counter delta (read
  after the 35 s it needs to publish), the end-of-window sample of the write-in-progress flag, and the sample of the firmware's last
  result text. The "nothing written" claim of this proof is about the manual path (the armed Apply); the automatic RTC clock writes do
  not use the write enable and are outside it.
- **The editor stays "in flight" while the follow-up waits run.** The F1 Load wait (up to 60 s plus 20 s) and the F2 waits (35 s counter
  wait, up to 60 s Load wait) run while `input_boolean.ecco_cfg_edit_in_flight` is still on, deliberately: a Home Assistant restart in
  that window makes the watchdog report UNCERTAIN and lock the editor even after a verified success. That conservative behaviour is kept
  (the marker is not turned off earlier); acknowledge the lock after checking the slots.
- **The success notice could offer an undo the Review refuses** (a live power of 2550 W is not a multiple of 100). Decided (F3): a
  power edit is refused up front when the live power is not a multiple of 100 W.
- **Dump to Grid can refuse to start after a charge-source or slot-time edit.** Per the Dump start gate in the firmware source, a Dump to
  Grid whose window overlaps a slot with a charge source set refuses to start ("REJECTED - lease window overlaps TOU slot <n>, which has
  a charge source set"); a Grid source, or a Grid slot moved into the window, can make a later scheduled Dump refuse at its start, and no
  health alert counts that refusal. Decided (F4): the Review notification warns. Nothing checks or blocks it.
- **Stale neighbour staging after a start-time edit.** Decided (F1): the editor presses Load Current Slot N-1 and verifies that slot's
  staged end; when it cannot, the notice says so and the owner presses Load Current Slot N-1 (or Load All) before any Manual Controls
  Apply of that slot.
- **SmartDeye or the inverter panel during an edit.** A second Modbus master can have its change overwritten with the cached value.
  Do not use either during an edit. F4 puts the advice in every Review notification; nothing in Home Assistant enforces it.
