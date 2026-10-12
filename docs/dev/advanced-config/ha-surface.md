# ACW audit: Home Assistant and frontend surface for inverter configuration writes

Worktree `ECCO-Pro-Public-acw` at public main `fbe03aa`. Read-only and offline. FW means
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`. The S3 wrapper (`..._esp32s3.yaml`) only
overrides `esp32:` and `logger:`, so every entity below is identical on the live S3.
Entity ids follow ESPHome's rule `<domain>.ecco_clock_dongle_<slugify(name)>`, using node `ecco-clock-dongle`.
The ids that matter are confirmed by references in the dashboard or packages.

## 1. Dongle write controls visible in HA

### API actions (FW `api: actions:` at L1282-1366), called as `esphome.ecco_clock_dongle_<action>`
| action | vars | effect |
|---|---|---|
| `free_power_recovery_execute` (L1306) | action, evidence_id, confirmation | Copies the arguments to RAM. `ACCEPT_CURRENT_STATE` runs `free_power_recovery_accept_current_state`. Any other token runs `free_power_recovery_force_restore`, which needs the Recovery Arm, a fresh evidence id and the exact phrase `FORCE RESTORE ORIGINAL <id>`. **No HA caller exists anywhere** (pinned, see section 3). |
| `ha_supervision_heartbeat` (L1347) | challenge | RAM-only heartbeat. Its only caller is `packages/ecco_supervision_heartbeat.yaml:60`. |
| `fallback_profile_execute` (L1353) | action, target_id, confirmation | Fallback SAVE / REPLACE CORRUPT / INVALIDATE. It never writes a register. Callers are `packages/ecco_fallback_profile_actions.yaml:36,52,69` and `frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js:56,205`. |

### Switches (FW L5041-5151)
| name | entity | restore | role |
|---|---|---|---|
| Manual Configuration Write Enable | switch.ecco_clock_dongle_manual_configuration_write_enable | ALWAYS_OFF | Master arm for TOU slot 1-6 Apply and the reg244 Apply/Restore. Turned off after every Apply, including the verify-fail and reject paths (L12874, L12967-13001, L13058). |
| Manual Stage Grid Charge Enabled | switch.ecco_clock_dongle_manual_stage_grid_charge_enabled | ALWAYS_OFF | Staged value for reg232 bit0. It is written by **every** slot Apply (L12655-12657). Load Current fills it from reg232 (L21527). |
| Free Power Write Enable | switch.ecco_clock_dongle_free_power_write_enable | ALWAYS_OFF | Single-use arm for START FREE POWER. |
| Free Power Recovery Arm | switch.ecco_clock_dongle_free_power_recovery_arm | ALWAYS_OFF | Extra gate for the API recovery. Disarmed after one attempt. |
| Dump to Grid Write Enable | switch.ecco_clock_dongle_dump_to_grid_write_enable | ALWAYS_OFF | Single-use arm for START DUMP. |
| Dump to Grid Recovery Arm | switch.ecco_clock_dongle_dump_to_grid_recovery_arm | ALWAYS_OFF | Arm for the Dump Force Restore and Accept buttons. No typed phrase. |
| ECCO Fallback Profile Arm | switch.ecco_clock_dongle_ecco_fallback_profile_arm | ALWAYS_OFF | 120 s arm for fallback actions. |
| Automatic Clock Sync / Live Inverter Telemetry / Read-Only Configuration Polling | switch.ecco_clock_dongle_automatic_clock_sync etc. | RESTORE_DEFAULT_ON | Behaviour toggles. Clock sync controls RTC writes. |

### Numbers (FW L4665-5038). All are template, optimistic numbers.
| name pattern | entity | range / step | restore_value |
|---|---|---|---|
| Clock Correction Threshold | number.ecco_clock_dongle_clock_correction_threshold | 10-120 s / 5 | true |
| Free Power Duration / Max Charge Power | number.ecco_clock_dongle_free_power_duration, _free_power_max_charge_power | 1-240 min / 1; 500-8000 W (the `${ecco_inverter_tou_power_ceiling_w}` ceiling) / 100 | true |
| Dump to Grid Export Power / Stop SOC / Duration | number.ecco_clock_dongle_dump_to_grid_export_power, _stop_soc, _duration | 500-8000 W / 100; 10-90 % / 1; 1-240 min / 1 | true |
| Manual Slot N Start HHMM (N=1..6) | number.ecco_clock_dongle_manual_slot_N_start_hhmm | 0-2359 / 5 | **false** |
| Manual Slot N End HHMM | number.ecco_clock_dongle_manual_slot_N_end_hhmm | 0-2359 / 5 | false |
| Manual Slot N Power | number.ecco_clock_dongle_manual_slot_N_power | 0-ceiling / 100 W | false |
| Manual Slot N Target SOC | number.ecco_clock_dongle_manual_slot_N_target_soc | 0-100 / 1 % | false |

### Selects (FW L5153-5310)
- `select.ecco_clock_dongle_manual_slot_N_charge_source`, with options None, Grid, Generator and Grid + Generator.
- `select.ecco_clock_dongle_manual_slot_N_mode`, with options None, General, Backup and Charge.
- `select.ecco_clock_dongle_manual_reg244_staged_load_export_mode`, with options Allow Export, Essentials and Zero Export.

All of these are staging only.

### Buttons (FW L20983-22222)
- **Clock:** Read Inverter Clock and Sync Inverter Clock (RTC writes to regs 22-24).
- **Free Power:** START FREE POWER - CHARGE NOW → `button.ecco_clock_dongle_start_free_power_charge_now`; END FREE POWER - RESTORE NOW; Free Power Recovery: Review Live State (read-only evidence).
- **TOU per slot:** Load Current Slot N To Manual Staging (L21490...) and Apply Manual Slot N Settings (L21566...) → `button.ecco_clock_dongle_apply_manual_slot_N_settings`. There is **no separate Verify button**. Verify is built into `apply_manual_slotN`:
  1. Write 232, then 250-251, 256, 268 and 274 (slot 1 at L12570-12870).
  2. Reread 232 and 250+ (L12878-12924).
  3. Report `VERIFIED OK - manual Slot 1 settings match inverter readback` (L12941) or `VERIFY FAILED ...`.
  4. Disarm.
- **Load All Current TOU Slots To Manual Staging** (L22021).
- **Refresh:** Refresh Inverter Telemetry and Refresh Inverter Configuration.
- **reg244 proof:** Load Current Reg244 To Staging, Apply Staged Reg244 Settings and Restore Original Reg244 (L22103-22175). All three use the Manual Configuration Write Enable arm. The result goes to `sensor.ecco_clock_dongle_reg244_test_last_result`.
- **Dump:** START DUMP TO GRID - NOW, END DUMP TO GRID - RESTORE NOW, Dump to Grid Force Restore Original and Dump to Grid Accept Current State.
- **Fallback:** ECCO Fallback Profile: Review Current Configuration.

### Result and telemetry entities
- Manual Configuration Last Result → `sensor.ecco_clock_dongle_manual_configuration_last_result` (FW L5589).
- Manual Configuration Write Attempts Since Boot (L6233).
- binary_sensor `manual_write_in_progress` and `manual_configuration_raw_cache_valid`.

## 2. Where HA and the frontend expose these controls

- **Manual Controls view** (`dashboards/ecco_pro.yaml:7668`, path `ecco-manual-controls`) is the **only** UI for TOU and reg244 writes:
  - The Arm / Transaction Status entities card (L7776-7789) holds the arm switch and the Load ALL button.
  - The Last Completed Transaction markdown (L7810-7822) shows the last result.
  - The TOU matrix (L7826-8270) has, for each slot:
    - the charge-source select;
    - markdown cells for Power, SOC and Start, whose `tap_action: more-info` opens `input_number.ecco_manual_slot_N_{power,soc}_staged` or `input_datetime.ecco_manual_slot_N_start_time`;
    - a Status cell showing "MATCHES LIVE" or "PENDING";
    - Load and Apply cells (plain `entities` rows, so a press is immediate with **no confirmation dialog**).
  - The reg244 section (L8330-8370) and the Grid Charge staged switch (L8391) follow.
  - Mode selects and End numbers are **not shown**. Apply uses whatever Load Current published.
- **`packages/ecco_manual_controls_helpers.yaml`** keeps the helpers and the firmware numbers in sync in both directions:
  - It holds the `input_datetime` and `input_number` helpers (L62-188).
  - Number → helper automations are at L194-283. Helper → number (`number.set_value`) automations are at L285-391.
  - Times off the 5-minute grid are rejected and reverted (L315-326).
  - Helpers are refreshed at startup and on Load (to L489).
  - The package never presses Apply.
- **Inverter / Advanced view** (L6529): only the read-only `custom:ecco-advanced-config-card` (L7072).
- **Energy Actions card** (Overview, L795):
  - It calls `switch.turn_on/off` to arm, `number.set_value` to stage and `button.press` to start (`ecco-energy-actions-card.ts:404-410, 815, 1154-1186`).
  - End & Restore uses a 4 s double-tap confirm (`CONFIRM_WINDOW_MS`, L73, L1143-1154, L1176-1187).
  - The Dump recovery buttons are enabled only while the recovery arm is on (L1818-1842).
  - The sibling interlock lives in `interlock.ts`.
- **Fallback and Safety:**
  - Button cards use `perform-action script.ecco_fallback_profile_*` with HA `confirmation:` text (L7462-7500, L7662).
  - `ecco-fallback-recovery-card.js` builds the typed phrase `SAVE|INVALIDATE <16hex>[ REPLACE CORRUPT]` (L169-243).
- The Free Power recovery arm, Review button and execute action are **not on any dashboard**. The operator path is the entity pages plus HA Developer Tools → Actions (an inference from the absence of any caller).

**10 Oct 2026 Slot 1 SOC edits.** Memory file `fbd1-soak-analyser-status.md:93-96` records writes 100→40→100→40→100 % on reg 268, each verified. The UI path from the repo is:
1. Open Manual Controls.
2. Turn on Manual Configuration Write Enable.
3. Press Load (slot 1) or Load ALL.
4. Tap the slot 1 SOC cell and edit `input_number.ecco_manual_slot_1_soc_staged`. The automation runs `number.set_value` on `number.ecco_clock_dongle_manual_slot_1_target_soc`.
5. Press Apply.
6. Firmware writes 232/250/251/256/268/274, rereads them and reports VERIFIED OK, then disarms.
7. Read the result in Last Completed Transaction.

The exact taps were not observed.

## 3. Confirmation and safety patterns, and the tests that pin them

- **Firmware:** arms are ALWAYS_OFF and single-use, so they auto-disarm on every attempt. Apply rechecks staging, cache, ownership (FP / Dump / reg244), the bus and value bounds. Every write path rereads and verifies.
- **Frontend:**
  - The Energy Actions card uses an arm toggle, a single-use caption, a 4 s double-tap for End, and buttons disabled until armed.
  - The fallback card builds the exact firmware phrase.
  - HA `confirmation:` dialogs are used on the fallback scripts.
- **Pins:**
  - `registry/tests/test_free_power_recovery_evidence.py:410-447`: FORCE_RESTORE_ORIGINAL, ACCEPT_CURRENT_STATE and FORCE_RUNNING (in either case) are banned anywhere under `home-assistant/`. Only the two exact Dump button entity ids are allowed, and only in dashboards.
  - `home-assistant/tests/test_ecco_dump_to_grid_schedule_package.py:104-125`: the service allowlist; no `modbus.`, `esphome.` or `write_register`; the exact set of firmware entities; no recovery tokens in packages.
  - `frontend/ecco-advanced-config-card/test/static.test.ts:20-101`: the card and its bundle must not contain callService, perform_action, button.press, number.set_value, select.select_option, switch.turn_on/off, hass-more-info, dispatchEvent or setTimeout. Only `hass.states` may be read. The Global Power controls must be `disabled aria-disabled="true"`.
  - Z11 (`registry/tests/test_failback_shadow_evaluator.py:941, 996-1008, 1210-1217`): only the Energy Actions card's `schedule.ts /^BLOCKED/` may match a Verdict name. It scans `ecco-energy-actions-card/src` and all HA yaml.
  - `home-assistant/tests/test_ecco_fallback_packages.py:168-170` and others ban `esphome.`, `button.press`, `switch.turn_on` and `fallback_profile_execute` in display packages.
  - `registry/tests/test_fallback_recovery_dashboard.py:947-1005` pins the view order: Fallback / Recovery, then Safety, then Manual Controls. The pub0 copy also requires Manual Controls to be the last view.

## 4. What HA and frontend alone can do, and what needs new firmware

**No firmware change needed.** The verified, allowlisted write paths cover:
- TOU slots 1-6: Start/End (250-255), Power (256-261), SOC (268-273), source and mode bits (274-279);
- the reg232 grid-charge bit (written with every slot Apply);
- reg244 Load/Export Mode (the proof harness, which has a Restore);
- the Free Power and Dump transactions;
- the RTC sync.

In the registry these are the W1 TOU items (37), plus W2 rtc_clock and the FP/Dump transactions. W3 grid_export_policy (244) is limited to the proof harness.

A new "edit setting" feature could therefore:
- stage values with `number.set_value` / `select.select_option` on the existing manual_slot entities;
- turn on the arm;
- press `apply_manual_slot_N_settings`;
- confirm by watching `manual_configuration_last_result` for `VERIFIED OK`.

It must reproduce the matrix's validation in the UI: the 5-minute grid, start ≠ end, the ring coupling of Start to the previous slot's End, and Load before edit. Caveats:
- Apply always rewrites all slot fields **and reg232 bit0**, so staging must start with Load Current.
- There is no per-field write.
- Mode and End are hidden today.

**Needs new firmware** (a new allowlisted, verified write path, then an FW chain-pinned entry plus capability registry changes):
- reg245 Global Power / Export Limit (the card's disabled controls);
- W3 battery regs 201-204, 210-211 and 217-219;
- reg230 standalone (today written only by FP);
- the TOU voltage fields;
- the TOU master enable;
- every R0/WX item.

**Freeze, PEX and deploy constraints** (`registry/tests/_pex.py:71`):
- FROZEN, so any edit needs a declared post-export chain entry and a reverter: `dashboards/ecco_pro.yaml`, `packages/ecco_manual_controls_helpers.yaml`, `ecco_pro.yaml`, `ecco_tou_schedule.yaml`, `ecco_free_power_schedule.yaml`, `ecco_dump_to_grid_schedule.yaml`, `ecco_fallback_profile_actions.yaml`, the whole Energy Actions card (src/config.ts, the main .ts, dist, package*.json, README, examples, test/schedule.test.ts), `test_free_power_recovery_evidence.py`, `test_failback_shadow_evaluator.py`, `test_ecco_dump_to_grid_schedule_package.py` and `VERSION.yaml`.
- Chain-PINNED: `deployment/ha-manifest.yaml`, the FW yaml and `registry/inverter_capabilities.yaml`.
- **Not frozen:** `frontend/ecco-advanced-config-card/**`, including its static.test.ts (precedent: `_acfg1_scope.py:23-24`). Changing it to write would mean deliberately relaxing that no-write-authority test.
- **Deploy:** in `deployment/ha-manifest.yaml`, the `home_assistant_packages` list (L4-62; `ecco_tou_schedule.yaml` is not listed), `dashboard` (L66) and `frontend_assets` (L76-101: energy-actions, fallback-recovery and advanced-config, with `resource_registration: manual`). A new card or package needs a manifest stanza in a chain entry. `_acfg1_scope.py:168-172` reads the "exactly two assets" fact as of pub0.
