# Owner "edit an inverter setting" - ownership and conflict map

Read-only audit of public main `fbe03aa` (worktree `ECCO-Pro-Public-acw`). No file modified, no network. Abbreviations:
`FW` = `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`; `AWS` = `python -I tools/analyze_write_surface.py` output
(run offline, stdout only).

## 0. Headline findings

1. **The firmware is the only Modbus writer, and its write surface is pinned.** Writable today: 22-24, 230, 232, 244,
   250-261, 268-279 (SAFETY.md:9-19; `registry/tests/test_write_surface_invariants.py:129-156`, which also asserts
   "register 245 (Export Limit) is never written"). HA, dashboards, cards, Intelligence and `ecco_core` never write
   (`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md:30-31`). An owner editor = **new firmware write path(s)** for anything
   outside that set, plus an `ecco_core/authority.py` row, a `ECCO_CONFLICT_DECLARATIONS` entry and pin updates.
2. **Half the candidate list is not writable at all** and is classed W3/R0: 245 export limit (R0), 210/211 battery
   max charge/discharge current (W3), 217/218/219 shutdown/restart/low SOC (W3), 243 energy pattern (R0), 248 TOU master
   enable (R0) (`registry/inverter_capabilities.yaml:3233,3276,3319,3355,3391,3699,3801,3868`). `ecco_core/capability.py:84-86`
   deliberately models `control.export_limit` and `control.battery_protection` as controls that **fail closed**.
3. **An existing "manual write" model already exists** for TOU slots (`apply_manual_slot1..6`) and 244
   (`apply_reg244_settings`). The new editor should reuse its gate set verbatim (below). But note the asymmetry:
   - Manual TOU apply = **permanent owner edit, no snapshot, no restore** ("a manual apply is owned by the person who applied
     it", `ecco_core/authority.py:32,60-62`; SAFETY.md:96).
   - Register 244 apply = a **proof transaction**: it opens a durable `reg244_snapshot_valid` obligation that only
     "Restore Original Reg244" clears (`FW:16442,16705`; buttons `FW:22139-22161`). While open, Free Power, Dump and every
     Manual TOU apply are refused (`FW:7743`, `FW:12608`, Dump gate `FW:16970`). There is **no "keep as new normal" path**
     for 244 today - a persistent 244 edit needs a new commit/accept semantic.
4. **Dump-to-Grid restore is blind; Free Power restore is classified.** FP's restore re-reads its 20 owned registers and
   refuses (operator lockout) when live matches NEITHER the snapshot NOR its intended overlay (`FW:9976-10012`) and holds on
   a 244 context change (`FW:9902-9973`). Dump's restore writes 244 then 256-261 straight from the snapshot
   (`FW:18578-18712`) - an owner edit to those registers while Dump owns them is **overwritten**, not detected at restore
   (only the active-lease drift check notices and ends the lease, `FW:22371-22421`).
5. **Fallback profile never updates itself.** "Drift only changes what is displayed. Only an operator Save or Invalidate
   changes it" (`FALLBACK_DESIGN_BASIS.md:41,123-124`). Save is operator-only (Review + Arm + `SAVE <id>` phrase); no
   automation/script may call the wrappers (pinned, `home-assistant/packages/ecco_fallback_profile_actions.yaml:5-9`;
   `FALLBACK_DESIGN_BASIS.md:98-112`). So the editor **cannot** auto-recapture; it must hand the owner to Review/Save.
6. **Doc discrepancy:** `docs/DUMP_TO_GRID_V1.md:11` says Dump writes "244 and 250-261"; AWS, `ecco_core/authority.py:80`
   and `registry/transaction_state_machine.py:858-890` say 244 + 256-261 (and 250-255 are forbidden to Dump,
   `test_write_surface_invariants.py:182-183`).

## 1. Register x subsystem matrix

W = writes, R = restores from a durable snapshot, C = compares (drift / classification), r = reads as context or input,
`-` = no interaction. Fallback classes: E1 (compared -> DRIFT), CTX (-> CONTEXT, failback refused), INFO (shown only)
(`registry/fallback_profile.py:119-131`).

| Reg | Meaning | Manual TOU | R244 policy | Free Power | Dump | RTC (FB-D1) | Fallback B10 / shadow | Intelligence / HA |
|---|---|---|---|---|---|---|---|---|
| 22-24 | inverter clock | - | - | - | - | W (no snapshot) | excluded | - |
| 210/211 | batt max chg/dis current | - | - | - | - | - | not in profile | not read |
| 217-219 | shutdown/restart/low SOC | - | - | - | - | - | not in profile | not read (reserve is HA helper, SAFETY.md:106-120) |
| 230 | grid charge current | - | - | W, R, C | - | - | INFO (ix only) | - |
| 232 | grid-charge enable (b0) | W (whole slot apply) | - | W, R, C | - | - | CTX b0 | - |
| 243 | energy pattern / "work mode" | - | - | - | - | - | CTX (capture refuses >1, RF_243X) | - |
| 244 | load/export mode | - | W (+snapshot, R) | r: lease context; restore holds if changed | W, R, C (active drift) | lease input via reg244_apply_in_progress | E1, **must be 2** (0 -> EXPORT, 1 -> OUT_OF_DOMAIN) | - |
| 245 | export limit | - | - | r (recovery ctx, `FW:2540-2548`) | - | - | INFO | - |
| 247 | (info) | - | - | - | - | - | INFO | - |
| 248 | TOU master enable (b0) | - | - | r (recovery ctx) | - | - | CTX b0 | - |
| 250-255 | slot start times (end = next start) | W | - | r (recovery ctx) | r (start TOU-conflict check `FW:16898-16950`) | r (quiet windows, precision, zone-cross `registry/rtc_policy.py:169-214`) | CTX | r (`ecco_tou_schedule.yaml`, Intelligence) |
| 256-261 | slot power (charge/discharge cap) | W | (meaning depends on 244) | W, R, C | W (tick), R, C | - | E1 (500..ceiling) | - |
| 268-273 | slot target SOC | W | - | W, R, C | - (deliberately not owned) | - | E1 (0..100) | - |
| 274-279 | slot source b0-1 / mode b2-4 | W (RMW, mode preserved) | - | W, R, C | r (charge-source bits block start) | - | E1 (compares full word; capture needs source<=1, mode 0) | - |

## 2. Ownership flags and obligations

Ownership (RAM) flags, `ecco_core/authority.py:91-92`, `tools/analyze_write_surface.py:88-94`:

| Flag | Meaning | Set by |
|---|---|---|
| `manual_write_in_progress` | shared bus write mutex; every write path except RTC takes it | all 15 non-RTC writers (AWS) |
| `correction_in_progress` | RTC correction lock (released by breaker after 90 s, `kTxnDeadlineMs`) | RTC path `FW:21258,21359`; does **not** take the mutex, but defers if mutex held (`FW:7578-7600`) |
| `free_power_operation_in_progress` | an FP start/restore is executing | FP scripts |
| `reg244_apply_in_progress` | a 244 apply/restore is executing | 244 scripts |
| `dump_operation_in_progress` | a Dump start/tick/restore is executing | Dump scripts |

Durable obligation flags (survive reboot; "a restore is still owed"): `free_power_snapshot_valid`,
`free_power_active_persisted`, `free_power_restore_requested`, `reg244_snapshot_valid`, `dump_snapshot_valid`,
`dump_active_persisted`, `dump_restore_requested` (`ecco_core/authority.py:67,75-85`). Lockouts: `*_recovery_metadata_corrupt`,
`free_power_operator_needed`, `dump_operator_needed`. Arm switches: `manual_config_write_enable`, `free_power_write_enable`,
`dump_write_enable` (one-shot: the start turns them off, `FW:7770`).

RTC policy "lease" (holds non-large corrections): FP active/restore-requested/in-progress, Dump active/restore-requested/
in-progress, `reg244_apply_in_progress` (`FW:21227-21230`, `rtc_policy.py:258-260`). Quiet windows: +/-60 s around every
half hour and every TOU slot start (`rtc_policy.py:169-182`).

Conflict domains (semantic, beyond registers): `INVERTER_CLOCK`, `TOU_SCHEDULE`, `GRID_CHARGE`, `INVERTER_POWER_POLICY`
(`registry/transaction_state_machine.py:136-181`). 244 declares TOU_SCHEDULE because it changes what 256-261 mean.

## 3. Per-subsystem: what an independent write breaks

- **Free Power** (`start_free_power_override` gate `FW:7725-7767`): snapshots 230, 232, 256-261, 268-279 + 244 lease
  context, overlays all six slots. Edit during lease or while restore owed -> restore classifier sees NEITHER -> durable
  operator lockout, zero writes (`FW:9976-10012`); a 244 edit -> CONTEXT HOLD (`FW:9902-9973`). Operator "Force Restore
  Original" would then **overwrite the owner's edit** with the pre-FP snapshot. Edit **between** leases is safe: the next
  FP snapshots whatever is live and restores to it.
- **Dump** (gate `FW:16954-17016`): owns 244 + 256-261; stop SOC (10-90 %, `FW:17015-17016`) and export power are dongle
  numbers, never inverter registers (`transaction_state_machine.py:869-874`). Edit of 244/256-261 during lease -> CONFIG
  DRIFT ends the lease (`FW:22371-22421`) -> blind restore overwrites the edit. Edits to 250-255 / 274-279 change whether a
  (scheduled) Dump may start at all (TOU-conflict pre-check).
- **RTC (FB-D1):** disjoint registers, but writes outside the mutex and the manual Sync button skips the quiet-bus check
  (`docs/architecture/MODULAR_ARCHITECTURE.md:72-73`). Slot start-time edits move the RTC quiet/precision windows.
- **Fallback B10 / profile:** after any controller write the write fence pauses Live Match for two config polls
  (`FALLBACK_DESIGN_BASIS.md:118-121`), then: E1 change -> `DRIFT` (health DEGRADED), CTX change -> `CONTEXT` (WARNING), 244=0
  -> `EXPORT`, out-of-domain -> `OUT_OF_DOMAIN` (`registry/fallback_capture.py:1639-1683`;
  `home-assistant/packages/ecco_system_health.yaml:942-967`; texts `ecco_fallback_status.yaml:240-242`). This is the 10 Oct
  slot-1 SOC (268) case.
- **Failback shadow** (`registry/failback_shadow.py:710-726`): with HA lost, an un-recaptured E1 edit -> `WOULD_APPLY_PROFILE`
  (a future FB-E/F Restore **would revert the owner's edit**); a CTX edit -> `BLOCKED_CONTEXT_MISMATCH` (failback disabled
  until re-saved); live out of domain -> `BLOCKED_LIVE_OUT_OF_DOMAIN`. A manual write in flight -> `WAIT_WRITE_IN_FLIGHT`.
  Supervision heartbeat is observe-only (`ecco_supervision_heartbeat.yaml:17-27`); no interaction beyond that.
- **Schedules (HA):** FP schedule (fps1) treats "another inverter write active" as transient and retries for <=10 min
  (`docs/incidents/2026-10-11-scheduled-free-power-start.md`, Correction). Dump schedule still has the old two-press policy
  (same doc, Follow-ups) - an edit within ~35 s of a scheduled Dump start makes it fail.
- **Intelligence / ecco_core:** advisory only; `evaluate()` refuses origins `intelligence`, `advisory`, `dashboard`,
  `simulation_advice` and any undeclared origin (`ecco_core/authority.py:94,129-132`). An owner editor is not one of the five
  declared features, so `evaluate()` refuses it until a new `WriteAuthority` row exists. Intelligence reads TOU starts
  (via `ecco_tou_schedule.yaml`) and the HA reserve helper, so edits change its advice only.

## 4. Candidate settings: conflicts and editor rules

Common gate (union of today's manual gates, `FW:12597-12637`, `FW:15920-15952`; plus `ecco_core/authority.py:157-167`):
arm switch on (one-shot); `configuration_online`; staging loaded from a fresh read; `!manual_write_in_progress`,
`!correction_in_progress`, `!reg244_apply_in_progress`, `!free_power_operation_in_progress`, `!dump_operation_in_progress`;
all seven durable obligation flags clear; no `*_recovery_metadata_corrupt`; no `*_operator_needed`; bus quiet
(`tx_buffer_empty && !tx_blocked`); take `manual_write_in_progress` for the whole sequence; verify by exact readback.
Plus (HA side): refuse within ~10 min of an armed FP/Dump schedule start; refuse during a fallback Review/Save.

| Setting | Writable today? | Conflicts | Rule for a safe editor |
|---|---|---|---|
| 245 export limit | **No** (R0; pinned never-written) | FP recovery ctx; profile INFO only; DNO compliance (SAFETY.md:62-67) | New write path + scaling proof + pin change; INFO -> no profile action needed |
| 244 load/export mode | Yes, but only as a proof txn with mandatory restore | FP lease context (hold), Dump owns it, changes meaning of 256-261, profile requires 2 | Refuse unless all leases/obligations clear; needs a new "accept/keep" commit or it blocks FP/Dump/TOU until restored; setting 0/1 makes the profile un-capturable (RF_244X) |
| 210/211 batt current limits | **No** (W3) | none in ECCO today; equipment-safety (D4) | New W3 path, live proof, extra confirmation; not in profile |
| 230 grid charge current | Only inside FP | FP W/R/C | Refuse during FP/obligation; after edit: profile INFO, no re-save needed; next FP restores to the new value |
| 232 grid-charge enable | Via manual slot apply / FP | FP W/R/C; profile CTX b0 | Refuse during FP; after edit -> CONTEXT; prompt Review + Save |
| TOU slot SOC 268-273 | Yes (manual slot) | FP W/R/C; profile E1 | Refuse during FP/obligation; after edit -> DRIFT; prompt Review + Save (else failback would revert it) |
| TOU slot power 256-261 | Yes (manual slot) | FP and Dump W/R/C; meaning set by 244 | Refuse during FP or Dump/obligation; keep 500..ceiling or capture refuses (RF_PWRL/H); prompt Save |
| TOU slot time 250-255 | Yes (manual slot; edits two slots' boundaries) | Dump start check, RTC quiet windows, Intelligence; profile CTX | 5-min grid; refuse during leases; after edit -> CONTEXT (failback blocked) until Save |
| TOU enable/source 274-279 | Yes (RMW in manual slot) | FP W/R/C; Dump start check; profile E1 full word | Preserve mode bits; source must stay <=1 for capture (RF_SRCG); prompt Save |
| 217/218/219 shutdown/restart/low SOC | **No** (W3) | battery protection; Dump stop SOC and HA reserve are independent software floors | New W3 path with dedicated confirmation; enforce ordering vs Dump stop SOC/reserve; not in profile |
| 243 work mode (energy pattern) | **No** (R0) | profile CTX (capture refuses >1) | New path; after edit -> CONTEXT until Save |
| 248 TOU master enable | **No** (R0) | profile CTX b0 | New path; after edit -> CONTEXT until Save |

After every successful edit of an E1 or CTX register: the editor must surface "fallback profile no longer matches - Review
and Save if this is the new normal" (operator-only; it may not press Review/Arm/Save itself). Attribution: today nothing
records "this drift came from an owner edit"; a firmware/HA last-edit record (registers, values, time) shown next to the
DRIFT/CONTEXT text would turn the 10 Oct-style alarm into an explained, acknowledgeable state.
