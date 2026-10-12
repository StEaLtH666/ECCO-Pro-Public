# Advanced Configuration: register write-evidence audit (read-only)

Worktree: `(private scratch path removed)` @ fbe03aa (public main). Audit date 2026-10-12.
No repository file modified; nothing contacted. Abbreviations: REG = `registry/inverter_capabilities.yaml`,
FW = `firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, OVL = `registry/advanced_config_overlay.yaml`,
SH = `SUPPORTED_HARDWARE.md`, ICR = `docs/INVERTER_CAPABILITY_REGISTRY.md`.

## 0. Ground truth that frames everything

- **Repo register numbers differ from the brief's guesses.** 108 = `day_pv_energy`, 109 = `pv1_voltage` (telemetry, not settings).
  128/130/141-143/148-171 are not settings in this map (150-196 is telemetry). Settings live in 200-248 and TOU 250-279.
- **Pinned firmware write surface** = {22-24, 230, 232, 244, 250-261, 268-279} and nothing else
  (`registry/tests/test_write_surface_invariants.py:129-134`; 245 explicitly asserted never written, :155-156;
  243/245/248 forbidden, :166-183). Re-derived today with `python -I tools/analyze_write_surface.py` (16 writer scripts, identical set).
- **Live write proofs are all on the classic ESP32 (H-001).** H-002 (ESP32-S3, live controller) row: "No write feature has
  been separately re-proven on this controller ... treat them as *offline only* on an S3" (SH:23). Code mirrors it:
  `ecco_core/capability.py:48-51` (`esp32s3: CONTROL: OFFLINE_ONLY`); OVL:22-24.
- **Discrepancy found:** `docs/incidents/2026-10-11-scheduled-free-power-start.md:4-6` and timeline rows (11:03:49 "ACTIVE - VERIFIED OK",
  restore verified 12:59:48; 11:02:48 routine RTC correction) record an **operational** 8000 W Free Power start/restore and
  an RTC correction on 2026-10-11, when the S3 was the live controller (SH:23). That is real S3 write evidence for
  230/232/256-261/268-279 and 22-24, but it is not recorded as a proof anywhere (SH, `CONTROLLER_PROOF` unchanged).
- The primary live-proof records cited by REG (`docs/stage3_3-six-slot-hardware-test.md`, `CURRENT_STATE.md`,
  `docs/FREE_POWER_LIVE_PROOF_2026-09-24.md`, `docs/research/export-control-register-audit-2026-09-20.md`) are **not in the public
  tree** (private archive); public evidence is the REG fields plus SH/SAFETY summaries.

## 1. Per-family evidence

| Register(s) | Meaning / scaling / range | REG access, evidence, policy | FW writer? | Write proven on THIS inverter? |
|---|---|---|---|---|
| **245** Export Limit ("Global Power") | uint16, W, scale 1 (REG:3816-3822). No range documented. | read_only, live_proven_read, R0 (REG:3823,3834-3835) | **No** (REG:3824-3825; invariant test :155) | **Never.** Read only. |
| **244** Load Limit / export policy | enum 0 Allow Export, 1 Essentials, 2 Zero Export (REG:3770-3773) | read_write, live_proven_write, **W3**, recovery live_proven (REG:3759,3779,3786-3787) | Yes: `apply_reg244_settings`, `restore_reg244_snapshot`, Dump start/restore, `dump_lockout_containment` (ICR:416-420) | **Yes, classic ESP32, 2026-09-21**: 2->0->2 round trip exact-reread VERIFIED, behaviour change confirmed (REG:3765-3769). Durable restore round trip 2026-09-22 (ICR:168-170). Value **1 (Essentials) never exercised**. Not re-proven on S3. |
| 243 Energy mgmt model | enum 0 Battery First, 1 Load First (REG:3717-3719) | read_only, live_proven_read, R0 | No (REG:3715-3716) | No |
| 247 Export solar | bit0 (REG:3841) | read_only, live_proven_read, R0 | No | No |
| 248 TOU master enable | bit0 (REG:3871) | read_only, live_proven_read, R0 | No (Dump-forbidden) | No |
| 206 Zero-export trickle | int16 W, signed on some FW, FW takes abs (REG:3035-3046) | read_only, live_proven_read, R0 | No | No |
| **210** Battery max charge current | uint16 A, scale 1 (REG:3242-3248); no bounds ("No live-calibrated safe write bounds", REG:3271) | read_only, live_proven_read, **W3** (REG:3249,3264-3265) | No (REG:3250-3252) | No |
| **211** Battery max discharge current | uint16 A (REG:3285-3291); no bounds | read_only, live_proven_read, **W3** (REG:3307-3308) | No | No |
| 201-204 Equalise/absorb/float V (0.01 V), capacity Ah | REG:3061-3232 | read_only, live_proven_read, W3 | No | No |
| **217/218/219** shutdown/restart/low-warning SOC | uint16 %, 0-100 trivial range only (REG:3351-3352) | read_only, live_proven_read, W3 (REG:3346-3348) | No | No |
| 200, 213, 214 battery type / basis / lithium wake bit | enums; 214 polarity disputed (REG:3005-3006) | read_only, live_proven_read, R0 | No | No |
| **230** Grid charge current | uint16 A (REG:2222-2230); safe_min 1; **hardware max NOT ESTABLISHED** (REG:2237-2247); 185 A is a transaction snapshot, not a ceiling (REG:2255-2262) | read_write, live_proven_write, W2 (REG:2231,2277-2278) | Yes, only Free Power (3 writers) | **Yes, classic, Free Power 2026-09-22 (500 W / 9 A, REG:2284-2286) and 2026-09-24 V4 (REG:2544-2549)**; operational on S3 2026-10-11 (incident doc). Never as a standalone setting. |
| **232** bit0 Grid charge enable | bitfield (REG:2115) | read_write, live_proven_write, W1 (REG:2130,2159-2160) | Yes: Free Power (standalone change) + 6 slot scripts (rewrite unchanged) (REG:2131-2134) | Yes, classic, via Free Power (REG:2161-2169). No standalone control exists (REG:2157-2158). |
| 231 Generator charge enable | bit0 | read_only, live_proven_read, R0 (REG:2186,2199-2200) | No | No |
| **250-255** TOU slot times | uint16 HHMM, 0-2359, minute multiple of 5 (REG:156-158; FW:4762-4768). **Ring: 250 is slot1 start AND slot6 end** (REG:165-168) | read_write, live_proven_write, W1 | Yes, `apply_manual_slotN` only | Yes, classic, Stage 3.3 path re-verified 2026-09-15 (REG:151-154). |
| **256-261** TOU slot power | uint16 W, 0..`${ecco_inverter_tou_power_ceiling_w}`=8000 (FW:13, 4788-4790); 8000 is a **compile-time site value**, not a verified hardware max | read_write, live_proven_write, W1 (REG:241,277-278) | Yes: manual slots, Free Power, Dump start/restore/controller tick | Yes, classic (2026-09-15; Free Power ownership 2026-09-24; Dump at 3000 W, two scenarios, SH:41). |
| **268-273** TOU target SOC | uint16 %, 0-100 (REG:306-307) | read_write, live_proven_write, W1 | Yes: manual slots, Free Power | Yes, classic 2026-09-15 |
| **274-279** TOU source (bits 0-1) / mode (bits 2-4) | source enum 0-3; mode 0x04 General, 0x08 Backup, 0x10 Charge (REG:398-450); other bits preserved by RMW (FW:12829) | read_write, live_proven_write, W1 | Yes: manual slots (whole word, RMW), Free Power (bits 0-1 only, REG:2460-2461) | Yes, classic 2026-09-15 |
| 262-267 TOU slot voltage | 0.01 V | read_only, R0 (REG:340-355) | No | No |
| 223/224/226/227 generator run/down time, start SOC, charge current | REG:3427-3546 | read_only, live_proven_read, R0 | No | No |
| 235/237/239/241 AUX function, smart-load thresholds/power | units of 237/239 "not independently confirmed" (REG:3583,3613) | read_only, R0 | No | No |
| 280 bits 4-7/8-11/12 gen/grid peak shaving, on-grid always-on; 292/293 peak-shaving W | REG:3899-4054 | read_only, live_proven_read, R0 | No | No |
| 287-290 grid protection thresholds | REG:4055-4170 | read_only, R0; OVL LOCKED (OVL:159-174) | No | No |
| 330 bits 4-15; signal_island_mode, protocol version, rated power, serial, remote_lock; smartdeye parity | no register / unknown meaning | unknown, WX (REG:6154-6488) | No | No |

## 2. Hazards and owner decisions

1. **244 changes what TOU Power means** (FW:7738; REG:2335-2336). 256-261 is the inverter's native battery charge/discharge
   ceiling in both Zero Export and Allow Export modes (REG:262-265) - so a TOU "power" edit is a battery-rate edit, and its effect
   depends on 244. Free Power captures 244 context and refuses automatic restore if it moved (REG:2334-2348).
2. **245 semantics unproven:** "Two published descriptions of this field disagree on whether it caps only export to the grid or
   the inverter's combined Load and Grid output; that has not been proven on this installation" (OVL:119-121). Units/sign only
   read-decoded (uint16 W).
3. **Owner decision 2026-10-08:** "Export Limit" (245) is Global Power (OVL:292-296). Read-only blockers (OVL:306-311): no FW write
   path; not proven on the S3; hardware maximum not verified (`hardware_maximum_w: null`, OVL:297-301); regulatory allowance
   separate and not recorded (`regulatory_allowance_w: null`, OVL:302-305). The generator refuses a PROVEN Global Power
   (`tools/build_advanced_config_catalogue.py:724-725`); `ecco_core` treats `control.export_limit` as UNSUPPORTED
   (`ecco_core/capability.py:83-84`).
4. **No hardware maxima anywhere:** 230 "ABSOLUTE HARDWARE MAXIMUM NOT ESTABLISHED" (REG:2242); 8000 W TOU bound is a site
   substitution; rated power has no register (OVL:271-275). Dump measured discharge ran ~310 W over command at 3000 W; an 8.6 kW
   discharge event recorded (`docs/dev/dump-to-grid-ceiling.md:88,96`); nothing above 3000 W hardware tested (SH:41).
5. **Shared registers / ownership:** 256-261 shared by manual TOU, Free Power, Dump; 268-279 by manual TOU and Free Power;
   232 by all slot scripts and Free Power; 250-255 shared between adjacent slots (ring); 274-279 mixes source and mode bits
   (RMW required). Any editor write must take the same mutexes/ownership gates (Free Power/Dump/reg244 refusals, REG:2650-2657).
6. **Free Power ceiling/floor invariant:** a raised TOU ceiling is only harmless while all six SOC floors are 100 (FW:8481-8495).
   Editing 256-261 or 268-273 independently can break that invariant.
7. **Manual TOU recovery is volatile:** `recovery_implementation_status: partial` - RAM cache, no reboot survival (REG:164; ICR:153-157);
   SH:37 "No automatic rollback of a manual apply".
8. **214 polarity** reported differently by another tool (REG:3005-3006). **Essentials (244=1)** never exercised.
9. **Inverter clamp/reject behaviour:** no repository record of the inverter clamping or rejecting an in-range value; firmware
   only treats Modbus exceptions/non-standard replies as failures (FW:12825). Not characterised.
10. **Persistence/EEPROM wear:** no evidence in the repository either way (no "EEPROM"/"wear" mentions). Whether these inverter
    settings are flash-persisted per write is undocumented - Dump's controller tick rewrites 256-261 up to every 45 s
    (dump-to-grid-ceiling.md, "controller steps ... at least 45 s apart") with a per-lease write budget; an editor should still
    rate-limit and never loop.
11. Grid-protection and battery-protection/type registers are **owner-LOCKED permanently** (OVL:159-216); 210/211 need
    "battery / BMS evidence, a dedicated design and hardware proof first" (OVL:217-226).

## 3. Classification proposal

**SAFE FOR DEVELOPMENT** (proven write path, clear semantics, bounded) - develop as editor features that *reuse the existing
guarded firmware scripts*, offline/mock first; live use on the S3 still needs a recorded S3 re-proof (formal), which the
2026-10-11 operational run makes low-risk to obtain:
- 250-255 slot times, 268-273 target SOC, 274-279 charge source (bits 0-1) - via `apply_manual_slotN` (W1, live_proven_write 2026-09-15).
- 256-261 slot power - via `apply_manual_slotN`, bounded 0..site ceiling, **only with 244 shown alongside** and ownership refusals.
- 22-24 RTC - already automated; no editor control needed.

**REQUIRES FURTHER PROOF**
- 274-279 mode bits 2-4 (live_proven_write via the same script but mode-change semantics per 244 context not characterised; Backup/Charge effects not documented).
- 244 export policy - proven (classic, 2026-09-21) but W3, D3 regulatory, value 1 never exercised; keep behind the existing reg244 harness, not a plain editor field.
- 232 standalone grid-charge enable - only proven inside Free Power/slot writes; no standalone path exists.
- 230 grid charge current - proven only as a Free Power transaction field; hardware max unknown.
- **245 Global Power / Export Limit** - no write path, semantics disputed, no hardware max, no regulatory allowance; stays READ ONLY until a write is proven on the S3 (owner decision).
- 243, 247, 248, 206, 231, 223-227, 237/239/241, 280 peak-shaving bits, 292/293 - read-proven only, no write path; 248 is highest blast radius (OVL:149-150).
- 210/211 battery max charge/discharge current - W3, no path, no bounds, needs BMS evidence.

**UNSUPPORTED** (never offer as editable)
- 217-219 battery protection SOC, 200/201-204/213/214 battery type/curve/basis, 235 AUX function, 280 bit 12, 287-290 grid protection (owner LOCKED).
- 330 bits 4-15, `signal_island_mode`, `inverter_protocol_version`, `inverter_rated_power`, `inverter_serial_number`, `remote_lock`, SmartDeye parity (unknown/WX).
- 262-267 slot voltage (inverter-reported, R0).
