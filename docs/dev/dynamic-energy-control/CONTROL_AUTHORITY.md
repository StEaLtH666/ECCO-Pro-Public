# Dynamic energy control: what each Deye / dongle setpoint actually controls

Status: **offline analysis, 25 Nov 2026**, on branch `dev/dynamic-energy-control` from public main `04e088e`. No Home Assistant,
dongle or inverter access was used; nothing was written anywhere; Intelligence stays SHADOW. This answers the CONTROL AUTHORITY
list of message B and the six questions of message C ([REQUIREMENTS.md](REQUIREMENTS.md) REQ-B17, REQ-C2 to REQ-C7). The ranked
actuator paths and the live-proof ladder are in [ACTUATOR_PATHS.md](ACTUATOR_PATHS.md).

**An 8000 W setpoint is NOT assumed to give 8000 W of grid flow, and the evidence shows it does not:** at an 8000 W discharge
ceiling the grid received 6.93 kW; at an 8000 W charge slot the grid supplied 9.6 to 10.4 kW; during an 8000 W Free Power the grid
supplied 8.2 to 12.5 kW (section 1).

## 0. Evidence grades and sources

| Grade | Meaning |
|---|---|
| VERIFIED_LIVE | observed on the reference installation in a recorded live test or operation, with the numbers in a dated record |
| MEASURED_REPLAY | computed by this analysis from saved real telemetry, offline (aggregates only) |
| FIRMWARE_SOURCE | read in the firmware source: what ECCO writes or checks, never what the inverter does |
| REGISTRY_DOC | stated in a repository document or the capability registry, without raw data in the repository |
| INFERRED | reasoned from the above; plausible, not observed directly |
| UNKNOWN | no evidence either way: NOT ESTABLISHED |

Public sources are cited as file:line at `04e088e`: **REG** `registry/inverter_capabilities.yaml`, **FW**
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml`, **WS** the output of `tools/analyze_write_surface.py`, **DGC**
`docs/dev/dump-to-grid-ceiling.md`, **RE** `docs/dev/advanced-config/register-evidence.md`, **FDB**
`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md`, **SH** `SUPPORTED_HARDWARE.md`, **CFG** `intelligence/config.py`, **GRC**
`docs/dev/gentle-rate-controller/SPEC.md` (branch `dev/gentle-rate-controller` at `ec90232`, not on main).

Private records and offline evidence hold site data and are not published; they are named here only, and only aggregate numbers
are quoted from them:

| Tag | What |
|---|---|
| PR-A9 | commissioning record of the staged Dump to Grid tests A8 and A9 (15 Oct 2026): per-level inverter AC, battery DC, current, voltage, grid export |
| PR-CHAR | post-reboot inverter characterisation (23 Sept 2026): slot power against a kettle load in Zero Export and Allow Export |
| PR-DUMP | the full Dump to Grid design record (private), including "the 8.6 kW anomaly" and "Why 268-279 is untouched" |
| PR-FP | Free Power live-proof records (22 and 24 Sept 2026; 500 W, 1 minute, 9 A) |
| PR-GLA | Gentle limits and authority report (24 Nov 2026), from a saved states dump of that day |
| PR-RTC | RTC stall assessment (25 Nov 2026) |
| EV-N | four saved nights, 18-21 Nov 2026: battery power, grid CT, house, PV at about 10 s (Home Assistant history) |
| EV-SOC | SOC history of the same nights (one read-only pull, 25 Nov 2026) |
| EV-DIAG | the 21 Nov 2026 power-balance diagnosis (loss fits over 32 497 samples) |
| EV-FP | 11 Oct 2026 history around an operational 8000 W Free Power start (battery, voltage, grid CT, house, PV, inverter AC, slot powers, register 230) |
| EV-FR | Sept 2026 flight recordings (2 s sampler): the 22 Sept anomaly, the 23 Sept characterisation, the 26 Sept closed-loop Dump lease |
| EV-RTC | ten days of RTC history (15-25 Nov 2026) and its analysis |

The numbers marked MEASURED_REPLAY can be reproduced with [evidence_replay.py](evidence_replay.py) on the offline files (it prints
aggregates only).

## 1. Headline findings

1. **Export: the slot power is a ceiling on the inverter's AC output from the battery, not on grid flow.** In the staged Dump
   commissioning the inverter held 3.9-4.0, 5.00, 6.00 and 7.00 kW AC at ceilings of 4000, 5000, 6000 and 7000 W and 7.89 kW at
   8000 W; the battery delivered 4.23, 5.43, 6.52, 7.64 and 8.67 kW DC (8-10 % more, the conversion loss) and the grid received
   2.99, 4.20, 5.11, 6.13 and 6.93 kW (the AC output minus the house). VERIFIED_LIVE (PR-A9; FW:40-51).
2. **Charge at the top rate: the inverter held its own AC input constant at 8.98 kW, not 8000 W.** On each of the four saved
   nights the inverter's AC input (grid minus house) stayed at 8.982 to 8.987 kW (p05 to p95) for 161 to 210 minutes with the
   charge slot at 8000 W; the battery received 8.36 to 8.58 kW DC (0.94 to 0.95 W per W of AC, varying by night); the grid supplied
   9.57 to 10.44 kW, the house on top. The slot power value did not bind at 8000 W. What sets 8.98 kW is NOT ESTABLISHED.
   MEASURED_REPLAY (EV-N).
3. **Free Power: register 230 (amps) bound the charge, not the slot power.** At 8000 W requested (230 = 155 A computed at 51.5 V,
   all six slot powers 8000 W) the battery took 7.67 to 7.87 kW DC at 52.7 to 53.8 V, about 146 A by power over voltage (0.94 of
   155 A), while the AC input fell as PV rose (6.91 to 6.84 kW with PV 1.26 to 1.50 kW): the battery-side current was held.
   MEASURED_REPLAY, one event (EV-FP).
4. **The inverter does not reduce the charge for the house and did not limit grid import.** In the same event the house rose to
   5.5 kW: the battery charge stayed at 7.79 to 7.81 kW and grid import reached 12.46 kW. On the saved nights grid import tracked
   the house one to one (slope 0.99 to 1.12) over a constant inverter input. So a heavy household load does **not** slow a
   fixed-setpoint charge; it raises grid import, and any import limit must be enforced by the controller (REQ-D2).
   MEASURED_REPLAY (EV-FP, EV-N).
5. **Latency and settle.** After a verified Free Power START the battery reached 98 % of its plateau within 17 s (one 10 s
   telemetry frame after the first); the Dump controller waits 45 s after every slot power write because "current/telemetry needs
   ~45s to settle after a TOU Power change on this inverter" (FW:285-296). VERIFIED_LIVE (EV-FP) and FIRMWARE_SOURCE.
6. **A written ceiling is not always honoured.** On 22 Sept 2026 the battery discharged about 8.6 kW (7.06 kW to the grid) against
   a 1000 W ceiling, starting under Zero Export; it cleared after an inverter power cycle and has not recurred. Register
   verification proves registers, not behaviour (PR-DUMP; EV-FR). VERIFIED_LIVE, cause UNKNOWN.
7. **Nothing on the inverter reverts a setting when the dongle goes quiet.** No inverter-side communication watchdog is known to
   the repository: a written value stays in force until rewritten, and a slot value applies every night (REG:2774-2775 for the Dump
   case). INFERRED.
8. **Write wear is NOT ESTABLISHED** (RE:81-84); section 7 states what the existing controllers already do and a defensible bound.
9. **The inverter clock is erratic but corrected**: difference median 10 s, p95 38 s, maximum 71 s (77 s since boot); the stall flag
   73 to 93 times a day for 60 s; corrections 2.0 per hour, none failed. The inverter's own slot boundaries can move by about a
   minute. VERIFIED (EV-RTC, PR-RTC).

## 2. Sign conventions and the power balance

| Quantity | Register / source | Sign | Grade |
|---|---|---|---|
| Grid power (CT clamp) | 172 (REG:5466-5499) | + import, - export | REGISTRY_DOC; matches EV-N (charge nights +9.6 to +10.4 kW) and EV-FR (Dump negative) |
| Battery power | 190 (REG:2884-2911), DC side | + discharge, - charge | REGISTRY_DOC; matches all evidence |
| PV power | 186-189 summed, DC side | always >= 0 | REGISTRY_DOC |
| Inverter AC power | 175 total, 173 L1 (REG:5132-5212) | the L1 entity reads negative while the inverter draws from AC (charging) | MEASURED_REPLAY (EV-FP) |
| House load | 178 native (REG:5531-5564), or the HD1 derived value | >= 0 | the native value equals grid + inverter AC by the inverter's own accounting (INFERRED from the exact 1:1 tracking in EV-N); it reads 0 W while exporting (PR-DUMP; `docs/HOUSE_LOAD_HD1.md`), so the firmware derives house = inverter AC + grid CT during a Dump lease (FW:19013-19026) |
| Grid "load" | 169 (REG:5500-5530) | inverter-internal | not the CT; unused by ECCO |

The power balance with the inverter's losses (EV-DIAG, four days, MEASURED_REPLAY): discharge side
`(house - grid) = 0.924 x (PV + battery) - 50 W`; charge side `(house - grid) = 1.0545 x (PV + battery) - 20 W`, so on charge
about 0.95 W reaches the battery per W of AC drawn, and on discharge the battery supplies about 1.08 W DC per W of AC delivered
(plus about 50 W). The firmware's runaway backstop already allows 7-12 % DC over the AC command (FW:40-51).

## 3. The coordinator's starting facts, checked against the data

| Statement | This analysis | Verdict |
|---|---|---|
| Slot power 8000 W gave a battery charge of 8.4 to 8.6 kW (DC, negative), above the setpoint | plateau p05 to p95 8.36 to 8.58 kW (pooled p50 8.52 kW); the first minutes 8.23 to 8.28 kW (EV-N, EV-SOC) | CONFIRMED |
| Grid 9.6 to 10.4 kW including house 0.6 to 1.0 kW | grid p05 9.57, p50 9.74, p95 9.99, max 10.44 kW; house p05 to p95 0.58 to 1.15 kW, max 1.45 kW | CONFIRMED |
| 8000 is neither a strict DC cap nor an AC grid cap; semantics not established | the inverter's AC input was constant at 8.98 kW (p05 to p95 within 5 W) on every night while DC varied by night (1.049 to 1.065 W AC per W DC) and grid followed the house | CONFIRMED and sharpened: an AC-side regulation at about 8.98 kW, neither 8000 W nor any ECCO-written value |
| Flat plateau to SOC 98-99 %, a cliff to 0.6-1.9 kW within 5-10 min, a trickle of about 0.6 kW for 30-50+ min | last sample above 7 kW to the first below 2 kW: 2.5 to 4.8 min; trickle 0.55 to 0.65 kW, ending near 0.3 to 0.45 kW; the plateau rose only 0.4 to 1.2 % from start to end | CONFIRMED (the cliff is faster than stated); the small rise fits a constant AC power with slightly improving efficiency, not a constant current |
| House 0.6 to 1.0 kW (max 1.45); the charge did not fall when the house rose (correlations +0.92, +0.26, +0.08, -0.31) | my correlations +0.89, -0.30, -0.05, +0.01 (a different resampling); the mean charge at the lowest and highest house-load quartile: 8393/8502, 8437/8415, 8538/8537, 8548/8553 W | CONFIRMED: no dependence; night 18's positive correlation is a shared upward drift, not causation |
| Whether a heavier load would reduce the charge is not established | 11 Oct: the house reached 5.5 kW during an 8000 W Free Power; the charge stayed 7.79 to 7.81 kW; grid import reached 12.46 kW (EV-FP) | PARTLY ANSWERED: no reduction up to 12.46 kW of import in that event; larger loads, the main fuse and the peak-shaving settings remain NOT ESTABLISHED |
| The inverter clock is erratic: about 85 stall episodes a day of 60 s, about 2 corrections per hour, error up to about 77 s | 73 to 93 episodes a day on full days (each 60 s, at most 120 s); corrections 2.0 per hour over 245 h, 0 failed; difference median 10 s, p95 38 s, max 71 s, maximum since boot 77 s (EV-RTC) | CONFIRMED |

## 4. The setpoint table

Classes: **OPERATIONAL SETPOINT** (what a controller may move within a session), **HARD SAFETY CEILING** (or floor: a limit that is
enforced, never used as a target), **SCHEDULE** (the owner's window and plan), **MODE** (a switch, not a power), **INFORMATIONAL**.

| # | Setting | Registers | What it controls (evidence) | Class | Changeable during a session | Grade |
|---|---|---|---|---|---|---|
| 1 | TOU slot times | 250-255 | when each slot's power, SOC and source apply, on the inverter's own clock; a ring (250 is slot 1's start and slot 6's end) | SCHEDULE | not by a controller: moves the active slot | VERIFIED_LIVE (write); inverter scheduling at a moved midnight crossing UNKNOWN |
| 2 | Slot power, charging | 256-261 | NOT ESTABLISHED as a charge limit: at 8000 W it did not bind (AC input 8.98 kW, DC 8.36-8.58 kW) | candidate OPERATIONAL SETPOINT only after rungs R3-R5 | never observed during an active charge | MEASURED_REPLAY (not binding at 8000) / UNKNOWN (below) |
| 3 | Slot power, discharging | 256-261 | the inverter's AC output from the battery (held at the ceiling 500-7000 W; 7.89 kW at 8000); grid export = AC + PV - house | OPERATIONAL SETPOINT inside a Dump lease; HARD SAFETY CEILING in the owner's table | yes, every 45 s or more under the Dump lease | VERIFIED_LIVE |
| 4 | Slot target SOC | 268-273 | in a grid-charge slot the SOC at which the inverter's charge ends; in other slots a possible discharge floor (UNKNOWN) | SCHEDULE (planned SOC); candidate native floor | changes start or end a charge; not a rate | VERIFIED_LIVE (write; charge to 100 %); stop below 100 % and floor role UNKNOWN |
| 5 | Slot charge source | 274-279 bits 0-1 | whether the slot may charge from the grid | SCHEDULE | setting Grid starts a charge within about 10-20 s | VERIFIED_LIVE |
| 6 | Slot mode and other flag bits | 274-279 bits 2-15 | General / Backup / Charge and undecoded bits | not used (preserved by read-modify-write) | no | REGISTRY_DOC / UNKNOWN |
| 7 | Slot voltage | 262-267 | reported per slot; ECCO never writes it | INFORMATIONAL | no | FIRMWARE_SOURCE |
| 8 | Grid charge enable | 232 bit 0 | master enable for grid charging in every slot | MODE | only Free Power changes it | VERIFIED_LIVE |
| 9 | TOU master enable | 248 bit 0 | the inverter's TOU feature; bits 1-15 undecoded | MODE (never written) | no | REGISTRY_DOC |
| 10 | Grid charge current | 230 (A) | a battery-side charge current limit for grid charging (about 0.94 of the setting by power/voltage, one event); global; amps at a rising voltage | OPERATIONAL SETPOINT inside Free Power (fixed at START); otherwise the owner's HARD CEILING | Free Power START and restore only; a third value blocks its automatic restore | VERIFIED_LIVE (write) / MEASURED_REPLAY (binding) |
| 11 | Battery max charge current | 210 (A) | the inverter's battery charge current maximum; no write path | HARD SAFETY CEILING (native) | no | REGISTRY_DOC |
| 12 | Battery max discharge current | 211 (A) | the inverter's discharge current maximum; 171.1 A measured at 8 kW against the configured value | HARD SAFETY CEILING (native) | no | VERIFIED_LIVE (headroom) |
| 13 | Load / export policy | 244 | 0 Allow Export, 1 Essentials, 2 Zero Export; changes what slot power means | MODE (W3) | only at a Dump lease's start and end | VERIFIED_LIVE (0 and 2; 1 never exercised) |
| 14 | Export limit ("Global Power") | 245 (W) | disputed: export only, or the inverter's load plus grid output; no write path | HARD SAFETY CEILING (native, read-only) | no | REGISTRY_DOC / UNKNOWN |
| 15 | Energy management model, export solar, zero-export trickle | 243, 247, 206 | operating philosophy, PV export, trickle feed | INFORMATIONAL (never written) | no | REGISTRY_DOC |
| 16 | Grid / generator peak shaving | 280 bits 8-11 and 4-7, 293, 292 (W) | enable and power; behaviour not characterised; no write path | candidate native HARD CEILING for grid import | no | REGISTRY_DOC / UNKNOWN |
| 17 | Battery shutdown, restart, low-warning SOC | 217, 218, 219 | the inverter's battery protection floors; behaviour during a forced export not characterised | HARD SAFETY FLOOR (native) | no | REGISTRY_DOC |
| 18 | Backup reserve (ECCO's effective reserve) | none (software) | max(user reserve, technical minimum, Home Assistant reserve, raise preference) (CFG:140-172); enforced through the Dump Stop SOC | HARD SAFETY FLOOR (software) | the Dump Stop SOC is latched at START | FIRMWARE_SOURCE / REGISTRY_DOC |
| 19 | Free Power transaction | 230, 232, 256-261, 268-279 | a temporary grid charge in every slot to 100 % at a rate fixed at START | lease; its rate an OPERATIONAL SETPOINT fixed at START | no adjustment inside a lease | VERIFIED_LIVE |
| 20 | Dump to Grid transaction and limits | 244, 256-261; dongle settings | net grid export target (closed loop on the CT), Power Ceiling, Max Grid Export, Stop SOC | target: OPERATIONAL SETPOINT; ceiling, max export, Stop SOC: HARD SAFETY | the ceiling every 45 s or more; limits only lowered while active | VERIFIED_LIVE (A8, A9, 26 Sept) / FIRMWARE_SOURCE (guards) |
| 21 | Compile-time bounds | `ecco_inverter_tou_power_ceiling_w`, `ecco_dump_capability_w` | the largest value ECCO may write to 256-261 (8000 W on the reference profile); not a rating, not a grid limit | HARD SAFETY CEILING (on ECCO's writes) | no (build time) | FIRMWARE_SOURCE |
| 22 | Grid charge operating limit helper | `input_number.ecco_max_grid_charge_power` | a Home Assistant planner input and the Free Power request gate; writes nothing to the inverter | HARD CEILING on requests | owner setting | REGISTRY_DOC |
| 23 | Inverter clock | 22-24 | when the inverter's slot boundaries fall | not a power setpoint | automatic corrections about 2 per hour | VERIFIED_LIVE |
| 24 | Grid import limit (main fuse, supply) | none | not known to ECCO; no native limit observed up to 12.46 kW of import | must become an ECCO-enforced HARD SAFETY CEILING (owner value) | n/a | UNKNOWN (value) / MEASURED_REPLAY (no native limit seen) |

### 4.1 Slot times (250-255)

Writable only through the owner's guarded TOU editor (`apply_manual_slotN`, typed Apply; REG:129-178), live-proven 2026-09-15. The
editor holds the midnight crossing where it is (`docs/dev/acs1x-crossing-hold.md`), because the inverter's scheduler has only been
observed with the owner's layout. The boundaries fall on the inverter's clock, which differs from NTP by up to about a minute
(EV-RTC); the clock policy tightens its correction threshold before a TOU zone start (PR-RTC). **A dynamic controller never writes
them** (REQ-C8): they are the owner's window. Persistence: the inverter runs its own schedule every day without the dongle, so the
table is held by the inverter (INFERRED); whether it survives an inverter power loss is not recorded in the evidence (UNKNOWN).

### 4.2 Slot power (256-261) while charging

At 8000 W, with register 230 at its configured value and slot 1 the grid-charge slot (PR-GLA), the inverter's AC input was 8.98
kW on four nights, constant within a few watts while the house varied from 0.58 to 1.45 kW and the DC charge varied by night
(EV-N). A constant power to within 0.05 % across nights with different grid voltages is a power regulation, not a current limit.
It is not the slot power value. Three hypotheses remain open:

| Hypothesis | Predicts at a lower slot power (for example 6000 W, rung R4) |
|---|---|
| H1: the inverter scales the slot power into an AC-side limit (8000 W gave 8.98 kW, x1.12) | AC input about 6.74 kW: the slot power is an actuator with a gain of about 1.12 (AC) or 1.06 (DC) |
| H2: an inverter-internal maximum grid-charge power of about 9 kW binds and the slot power does not limit charging at all (the registry's earlier finding: "TOU Power alone does not regulate grid-charge rate", REG:2206-2214) | AC input unchanged at 8.98 kW: the slot power is not a charge actuator |
| H3: a limit derived from a configured current at a fixed internal voltage (8.98 kW is 185 A x 48.6 V) | unchanged by the slot power; moves with 230 or 210 |

The registry's description of 256-261 as the "native battery charge/discharge power ceiling" (REG:262-271) rests on discharge tests
only (PR-CHAR: three tests at 1000 W, all discharging); for charging it is an extrapolation. No live observation of a slot power
change during an active charge exists (GRC section 14). **Off grid**, a lowered slot power may also cap the battery's discharge to
the house (the discharge ceiling is verified on grid); that is UNKNOWN and is why rung R3 comes before any lowered charge setpoint
is kept (REQ-D7). A written value persists in the inverter's table and applies every night until rewritten (INFERRED), so a
controller that lowers it must hold the original durably and restore it (the GRC's record, section 11 of GRC). Writers today:
the TOU editor, Free Power (all six) and Dump (all six) (WS).

### 4.3 Slot power (256-261) while discharging and exporting

VERIFIED_LIVE as an AC-output ceiling under Allow Export (PR-A9; the 26 Sept lease in EV-FR, where a 1500 W ceiling gave about
1.68 kW DC and 0.47 kW of export against a 500 W target) and under Zero Export with a kettle load (PR-CHAR: battery held at about
1.0 to 1.2 kW with a 1000 W ceiling; the grid carried the rest). At 500 W the battery delivered about 0.59 kW DC and the house
imported (EV-FR). 0 W has never been written on purpose or characterised (FW:304-314). The inverter delivered 7.89 kW at 8000 W: an inverter-side limit
(PR-A9). The DC side runs above the command by +228 to +275 W at 2000 W and +271 to +357 W at 3000 W (FW:40-51); a few hundred watts
in general (SH:41). The exception is the 22 Sept 2026 anomaly (headline 6), which is why every Dump lease carries measured-power
runaway guards (DGC:84-109). Changed during a session by `dump_controller_tick`: at most 1000 W per step, at least 45 s apart,
rounded to 100 W, floor 500 W, deadband 150 W, at most 120 writes a lease (FW:216-230, 285-314, 345-355; DGC:67-80). In the owner's
normal table the same register caps each slot's battery discharge, so it is also a safety ceiling there.

### 4.4 Slot target SOC (268-273)

The owner's manual slot 1 path (`apply_manual_slot1`) wrote 100 -> 40 -> 100 -> 40 -> 100 % (four writes) on 10-11 Oct 2026, each
verified by an independent readback (`docs/dev/advanced-config/s3-tou-slot1-soc-writes-2026-10.md`). The inverter charged to the 100 % target every
saved night (EV-SOC); that it stops at a target **below** 100 % is expected Deye behaviour and is what Free Power's design relies
on, but no measurement of it is in the evidence read for this note (UNKNOWN; rung R1 can read the 10-11 Oct night, whose target
was 40 %). In non-charging slots its role as a discharge floor is UNKNOWN: Free Power's ceiling/floor invariant treats 268-273 as
floors, the registry as charge targets (PR-DUMP, "Why 268-279 is untouched"). If it is a floor, it is the one native mechanism that
could hold the backup reserve even with the dongle dead (rung R6). As a pacing actuator it is rejected (bursts at full rate, GRC
section 1). It is the owner's planned SOC (REQ-C8); the Home Assistant editor refuses a target below the larger of the battery
shutdown SOC and the reserve (`home-assistant/packages/ecco_tou_target_soc_edit.yaml:206`, `:241`).

### 4.5 Charge source (274-279 bits 0-1), mode and other bits

Setting Grid in the active slot starts a grid charge: after Free Power's verified START at 10:03:58 UTC on 11 Oct the battery read
-173 W 7 s later and -7554 W 17 s later (EV-FP). Restoring the original source ends it (PR-FP). The mode bits (2-4) and bits 5-15
are preserved by read-modify-write and are not characterised (REG:410-454; RE:98).

### 4.6 Grid charge enable (232), TOU enable (248), and the other context registers

232 bit 0 is the global grid-charge enable: set by Free Power, rewritten unchanged by every slot Apply (REG:2112-2169). 248 is never
written and is a fallback-profile context field (FDB:77-92). 243, 247 and 206 are read-only (REG:3032-3060, 3699-3731, 3838-3898).
None is an actuator.

### 4.7 Grid charge current (230)

Free Power computes `amps = round(watts / live battery voltage)`, at least 1, never above the pre-lease value (FW:9090-9108). In
EV-FP the battery then charged at about 146 A by power over voltage against 155 A, rising with voltage as a current limit does,
while the AC input fell as PV rose: a battery-side current limit, about 0.94 of the setting (one event; MEASURED_REPLAY). At night,
at its configured value (about 185 A on the reference installation, PR-GLA; REG:2253-2262), it did not bind. Its absolute hardware
maximum is NOT ESTABLISHED (REG:2237-2247). It is global (every slot), it is amps (the power drifts up 2-4 % through a charge as the
voltage rises), it belongs to the Free Power transaction, and a value Free Power did not write makes its restore classifier read
"neither" and block the automatic restore (REG:2492-2498). Its response at low rates is UNKNOWN.

### 4.8 Battery current limits (210, 211) and protection SOC (217-219)

Read-only, W3, no write path (REG:3233-3426); the owner keeps them locked until BMS evidence, a design and a hardware proof exist
(RE:85-86). The configured current limits read about 185 A (PR-GLA); at 8 kW of discharge the battery drew 171.1 A at 50.68 V, 13.9 A
under the limit (PR-A9). The shutdown SOC (217) is the inverter's last-resort low-SOC cutoff, the only floor left if the dongle
dies during an export (PR-DUMP); its behaviour during a forced export is not characterised. They are native hard limits, never
actuators.

### 4.9 Load / export policy (244) and export limit (245)

244 is live-proven writable (2 -> 0 -> 2 round trip, 21 Sept 2026, with the behaviour change confirmed; REG:3732-3800) and is W3:
a policy switch for the whole system that changes what the slot power means (RE:57-59). Dump sets it to Allow Export after the
slot powers and restores it first (REG:2612-2658). A change by anyone else during a lease is drift and ends the lease
(REG:2744-2754). Essentials (1) has never been exercised. 245 has no write path at all (REG:3801-3837; pinned by
`registry/tests/test_write_surface_invariants.py`); two published descriptions disagree on whether it caps export only or the
combined load and grid output (RE:60-62); the owner decided it stays read-only. It is a native hard ceiling of unknown scope and
must never be used as an operational setpoint (REQ-B16). No separate "maximum sell power" register is decoded or polled by this
firmware: 245 is the only export-power limit the repository knows, and whether the inverter has another is UNKNOWN. The
zero-export behaviour is the 244 value 2 (the normal policy on the reference installation) with the trickle-feed magnitude 206
(read-only).

### 4.10 Peak shaving (280, 292, 293)

Read-only R0, no write path, behaviour not characterised (REG:3899-4054). Grid peak shaving is the inverter's own mechanism that
could cap grid import natively (by reducing the grid charge, by discharging the battery, or both: UNKNOWN). Its setting at the time
of the 12.46 kW import is not in the saved data. Rung R0 reads it; any use needs its own characterisation and a write path, neither
of which exists.

### 4.11 The backup reserve

The effective reserve is software: `SiteConfig.effective_reserve()` returns the largest of the user reserve (default 40 %), the
technical minimum (a placeholder default of 10 %), the Home Assistant reserve helper and the raise-only preference (CFG:140-172).
The firmware enforces only the Dump Stop SOC (10-90 %, checked every 15 s against register 184, failing closed on stale SOC after
90 s, never written to the inverter; REG:2636-2642; FW:68). The Energy plan stage 3 change (branch `dev/stage3-on-r9`, not on main
at `04e088e`) stages ECCO's scheduled and guarded Dump starts with a Stop SOC at least the effective reserve, and states that this
does not bind the dongle's own Start button. The inverter's own floors (row 17) are below it. During a lease the Stop SOC is
latched; nothing re-checks it against a reserve that rises mid-lease (a gap, ACTUATOR_PATHS.md section 7).

### 4.12 The Free Power and Dump transactions

Free Power (REG:2287-2611): snapshot of 230/232/256-261/268-279 committed durably before any write; 232, 230, 268-279, readback,
then 256-261 last; exact restore in the reverse protected order; never resumed after a reboot (FW:576-584; FDB:39). Its rate is
fixed at START; there is no in-lease adjustment. Dump (REG:2612-2797): snapshot of 244 and 256-261; 256-261 first, then 244 = 0;
restore 244 first. Its export target is a net grid export, latched at START (FW:197-215); the battery ceiling is the controller's
output; START refuses a target without headroom under the Max Grid Export and a window overlapping a charge slot (FW:18884-18923);
lowering the ceiling mid-lease steps it down at once (FW:18973-18985); the export guard ends a lease on one sample far over, or two
over, the Max Grid Export (FW:270-279). Both are mutually exclusive with each other, the manual TOU editor, the register 244 harness
and an RTC correction (REG:2650-2657; WS).

### 4.13 Compile-time bounds and the Home Assistant limit helper

`ecco_inverter_tou_power_ceiling_w` is the "AC power bound of the inverter's TOU power registers" (FW:32-33), 8000 W for the
reference profile; `ecco_dump_capability_w` bounds the Dump Power Ceiling (FW:34-39). They bound what ECCO writes; they are not a
rating, a BMS limit or a grid limit (PR-GLA). `input_number.ecco_max_grid_charge_power` feeds `min(firmware bound, operating
limit)` in Home Assistant (`home-assistant/packages/ecco_runtime_config.yaml`, "ECCO Config Maximum Grid Charge Power"); it writes
nothing to the inverter.

## 5. The six questions of message C

**Q1. Which TOU settings can safely be updated during an active charging or exporting window?**

- **Exporting:** the slot power (256-261), and only under the existing Dump lease: it is rewritten every 45 s or more with
  readback, a durable latch, an ownership check before each write and a write budget (VERIFIED_LIVE). Register 244 only at the
  lease's start and end.
- **Charging:** only the slot power of the active charge slot is a candidate, and it is **not yet safe**: no live observation of a
  change during a charge exists, at 8000 W it did not bind, and off grid it may cap the battery. It becomes usable only under a
  firmware lease with an exact restore and after rungs R3 to R5. Inside a Free Power lease nothing may change today.
- **Never during a session:** slot times (they move the window), the slot target SOC and the charge source (they are the plan and
  they start or stop the charge, they do not set a rate), 230 from outside Free Power (it breaks Free Power's restore), the mode
  bits, and every register without a write path (245, 210, 211, 217-219, 243, 247, 248, 280-293).

**Q2. Do their power values control battery power, inverter power or actual grid flow?**

None of them controls grid flow; grid flow is the result, which is why a grid-side objective needs a closed loop on the CT (as
Dump V1.1 already does).

| Direction | What the setting limits | Grid flow then is | Grade |
|---|---|---|---|
| Discharge / export, slot power | the inverter's AC output from the battery (battery DC about 8-10 % more) | AC output + PV - house | VERIFIED_LIVE |
| Charge, slot power at 8000 W | nothing: the inverter held its AC input at 8.98 kW | house + 8.98 kW | MEASURED_REPLAY |
| Charge, slot power below 8000 W | UNKNOWN (H1, H2, H3) | house + inverter input | UNKNOWN |
| Charge in Free Power, register 230 | the battery-side charge current (about 0.94 of the setting, one event) | house + inverter input, which falls as PV rises | MEASURED_REPLAY |

**Q3. Which import/export limits are operational setpoints and which are hard safety ceilings?**

| Operational setpoints (a controller moves them) | Hard safety ceilings and floors (enforced, never targets) | Mode switches |
|---|---|---|
| the Dump export target (net grid export, latched at START); the Dump controller's commanded slot power; the Free Power request (230 at START); a future single-slot charge setpoint | Dump Power Ceiling and Max Grid Export (dongle, firmware-enforced); the compile-time TOU bound and profile capability; 245 (native, read-only, scope unknown); 210 and 211; 217-219; the Dump Stop SOC and the effective reserve; 230's pre-lease value (Free Power never exceeds it); the Home Assistant operating limit; the grid import limit (to be supplied and enforced by ECCO) | 244, 232, 248, the slot charge source |

**Q4. How frequently can settings be changed?** See section 7: no wear limit is established; the inverter settles in 10-45 s; the
existing controllers use at least 45 s between writes and at most 120 writes a lease; a defensible bound is proposed there.

**Q5. How should the controller respond to heavy household loads, changing PV, SOC changes and approaching deadlines?** The
evidence fixes the starting point: a heavy load does not slow a fixed-rate charge (the grid carries it); it raises grid import
(headline 4). During export the same load reduces the export at a fixed ceiling, and its removal raises the export at once.
ACTUATOR_PATHS.md section 6 gives the response per mode and path; in short:

- **Heavy load while charging:** hold the rate (progress is unaffected) unless grid import would exceed the import limit; then
  reduce, safety before the deadline, and report the target at risk; when the load ends, return after the dwell and hysteresis.
- **Heavy load while exporting:** raise the battery ceiling up to the Power Ceiling to keep the export target (never import to
  export); when the load drops, step down at once and let the export guard end the lease if the Max Grid Export is exceeded.
- **PV:** only measured PV in the loop. In a current-limited charge PV reduces grid import; during export PV adds to the export
  and the controller lowers the battery ceiling; it never charges from PV to "make room".
- **SOC:** SOC moves in 1 % steps (about 2.5 min each at the top rate); the cliff at 98-99 % is the BMS, not falling behind;
  jumps are faults; the export stop is at least the effective reserve.
- **Deadline:** the required power is recomputed from the measured SOC and a pessimistic taper; it rises in bounded steps up to
  the owner's value; when even that cannot make it, the status says so and the target is never lowered; the session ends before
  the inverter's own slot end with a margin larger than the clock error.

**Q6. How are the TOU schedule and safe limits retained and restored after a restart, lost connection or controller failure?**

| Event | What happens today | Grade |
|---|---|---|
| Dongle restart | Free Power and Dump leases are ended and restored at boot, never resumed (FW:576-584; FDB:39); the durable snapshots survive (two-phase NVS commit) | FIRMWARE_SOURCE (offline-proven); reboot recovery is not live-proven for either (REG: `recovery_implementation_status: implemented_not_live_proven`) |
| Home Assistant restart or loss | firmware leases continue to their own end and the 15 s watchdog restores; missed scheduled runs are never started after a restart (R9, `docs/DUMP_TO_GRID_V1.md:20-26`); after about 15 minutes without an API client ESPHome restarts the dongle (FDB:63-70), which ends any lease | FIRMWARE_SOURCE |
| Dongle dead or offline | the inverter keeps every written value: a Dump override keeps exporting with no ECCO Stop SOC until the dongle returns (REG:2774-2775); a Free Power override keeps grid-charging every slot to 100 %; a lowered slot power would apply every night | INFERRED / REGISTRY_DOC |
| Inverter restart | its settings are its own; the 23 Sept power cycle cleared the anomaly and normal ceiling behaviour returned (PR-CHAR) | INFERRED |
| Grid failure | no grid-loss interlock exists in the base firmware (GRC section 12); the grid-connected register is proven only as a read in normal operation; whether a lowered slot power caps the battery off grid is UNKNOWN | UNKNOWN |
| The owner's table itself | the fallback profile stores the owner's known-good TOU and export settings in the dongle's NVS and Live Match shows drift; **restore and automatic failback are not implemented** (FDB:3-7; SH:43) | VERIFIED_LIVE (save, live match) |

## 6. Message B's CONTROL AUTHORITY bullets, per setting

| Setting | AC / DC / current | Grid flow or inverter output | Changeable in a session | Frequency, latency, persistence | After comms loss / restart / grid failure | Start controls bypass a controller? |
|---|---|---|---|---|---|---|
| Slot power, export | AC output (DC +8-10 %) | inverter output | yes (Dump lease) | >= 45 s per write, settle about 45 s, persists in the table | stays in force if the dongle dies; lease restored at a dongle boot; off-grid effect unknown | yes: the dongle's Dump Start button and any HA user start a lease outside a coordinator; a third-party write is detected as drift |
| Slot power, charge | UNKNOWN (AC regulation at 8.98 kW seen at 8000) | inverter input; grid = house + input | not observed | unknown; persists | a lowered value would persist every night | the editor and Free Power also write it |
| Slot target SOC, source | SOC and enable, not power | starts or stops the charge | yes, but they are the plan | effect in 10-20 s; persists | persists | the editor writes them; Free Power overrides all six |
| 230 | current (battery side) | inverter input | Free Power START / restore only | fixed per lease; persists | stays reduced if the dongle dies in a lease; restored at boot | the Free Power Start button |
| 244 | mode | export allowed or not | lease start and end | persists | a Dump override stays in force if the dongle dies | the reg 244 harness, Dump, containment |
| 245, 210, 211, 217-219, 280-293 | W, A, %, flags | native limits | no write path | inverter-held | unaffected | none from ECCO; the inverter's own app or front panel can change them |

## 7. Register writes: frequency, wear and stability (Q4)

**What is established.** Nothing about endurance: there is no evidence in the repository either way whether the inverter commits
each setting write to non-volatile memory or how many writes a setting tolerates (RE:81-84). No vendor limit is cited anywhere in
the repository, and none is assumed here: **NOT ESTABLISHED**. No record shows the inverter clamping or rejecting an in-range value
(RE:79-80), so ECCO cannot rely on the inverter to refuse a bad one.

**What the plant allows.** A grid-charge change takes effect within about 10-20 s (EV-FP); the firmware waits 45 s after every slot
power write before judging the response (FW:285-296), and the staged commissioning ramped about one step per 60 s (PR-A9). Telemetry
arrives every 10 s and is skipped while any write or RTC correction runs (FW:24527); the configuration readback is every 60 s
(FW:24541). A closed loop therefore cannot usefully act faster than about one change per 45-60 s, and every write also pauses
telemetry for a few seconds.

**What existing controllers already do.**

| Writer | Cadence and budget | Registers per write | Grade |
|---|---|---|---|
| Dump controller (`dump_controller_tick`) | at least 45 s apart, at most 1000 W a step, deadband 150 W, at most 120 writes a lease (a lease is at most 240 min) | six (256-261 in one FC16 write) | FIRMWARE_SOURCE; VERIFIED_LIVE ramp |
| Free Power | four writes at START, four at the restore | 1, 1, 12 and 6 | FIRMWARE_SOURCE |
| TOU editor (`apply_manual_slotN`) | owner-typed, one Apply at a time | six registers (232, the slot's two times, power, SOC, flags) on every Apply, also for a one-field edit | WS; `s3-tou-slot1-soc-writes-2026-10.md` |
| RTC correction | about 2 per hour, continuously; 1528 verified since the last boot (roughly a month at that rate), 0 failed | three (22-24) | VERIFIED_LIVE (EV-RTC) |
| GRC design (not built) | dwell 30 min, at most 6 changes a lease, 10 writes a night (3 restores and 1 owner restore reserved), 42 in 7 nights, 4000 lifetime: stated guesses | one | design (GRC section 5) |

The RTC record shows the inverter absorbing about 50 writes a day to its clock registers for a month without a recorded fault; it is
not evidence for the settings registers, which may be stored differently.

**A defensible bound (proposal for review).**

1. At least 45 s between writes to any setpoint, and a deadband at least the measured noise (150 W for export, 300 W for charge).
2. Per mode: Gentle at most 6 changes a night with a 30 minute dwell (charging gently never needs speed); an adaptive Charge Battery
   at most one change per 5 minutes and 24 a session; export keeps the proven Dump bound (45 s, 120 a lease).
3. A shared daily cap of 150 setpoint writes across all controllers (above one fully used Dump lease plus a Gentle night), and a
   persisted lifetime counter, both published; non-restore writes are refused when a cap is reached; **a restore is never refused**
   (REQ-D5).
4. Prefer one register per decision over six where the semantics allow (a sixth of the register writes per step).

The typical use this implies is a few tens of writes a day. If, as an assumption and not a vendor figure, each write were committed
to a cell rated for 100 000 cycles, 40 writes a day would last about 7 years and the 150 cap about 1.8 years per cell written every
time; at 1 000 000 cycles, 18 to 68 years. That sensitivity is why the bound counts writes, why it prefers single-register writes,
and why the owner may want the installer's or manufacturer's statement on setting endurance before closed-loop control runs daily.

**Instability and side effects.** Each write holds the shared write lock, skips telemetry and configuration polls, and an RTC
correction defers it; a hunting controller is bounded by the anti-windup and wrong-direction counters and the write budget
(DGC:67-80); a written ceiling can be ignored by the inverter in an abnormal state (headline 6), so measured-power guards stay
mandatory.

## 8. The saved-night analysis (method)

EV-N holds Home Assistant history (state changes, about 10 s). Each series was held on a 10 s grid (a value at most 60 s old), the
night 00:00 to 07:00 UTC, the plateau defined as DC charge above 7 kW, the inverter AC input as grid minus house. Per night:

| Night | Plateau | DC charge p05 / p50 / p95 (kW) | Grid p05 / p95 / max (kW) | House p05 / p95 / max (kW) | AC input p05 / p95 (kW) | AC per DC (p50) | Cliff to < 2 kW |
|---|---|---|---|---|---|---|---|
| 18 Nov | 183 min, SOC 27 -> 100 | 8.36 / 8.44 / 8.51 | 9.58 / 10.03 / 10.16 | 0.60 / 1.04 / 1.18 | 8.982 / 8.986 | 1.065 | 2.5 min |
| 19 Nov | 161 min, SOC 36 -> 100 | 8.37 / 8.44 / 8.46 | 9.57 / 9.71 / 10.27 | 0.58 / 0.72 / 1.29 | 8.982 / 8.987 | 1.064 | 2.7 min |
| 20 Nov | 210 min, SOC 16 -> 100 | 8.51 / 8.55 / 8.57 | 9.71 / 10.14 / 10.44 | 0.73 / 1.15 / 1.45 | 8.982 / 8.986 | 1.050 | 4.2 min |
| 21 Nov | 187 min, SOC 25 -> 100 | 8.49 / 8.57 / 8.58 | 9.66 / 9.80 / 9.93 | 0.68 / 0.82 / 0.94 | 8.982 / 8.986 | 1.049 | 4.8 min |

The 11 Oct Free Power (EV-FP, 30 s resampling, 10:04:30 to 10:15:00 UTC): battery -7672 to -7866 W at 52.74 to 53.77 V, inverter AC
input 6910 to 6834 W, PV 1262 to 1496 W, house 1.30 to 5.55 kW, grid import 8.18 to 12.46 kW, register 230 at 155 A, all six slot
powers 8000 W. The staged Dump levels (PR-A9) and the 26 Sept closed-loop lease (EV-FR: ceiling stepped 500 -> 1100 -> 1400 -> 1500
W towards a 500 W export target, export settling near 0.47 kW) complete the picture for export.

## 9. Not established

- What sets the 8.98 kW AC input at the top rate, and whether the slot power limits a charge below 8000 W (H1, H2, H3; rungs R1,
  R4, R5).
- Whether the inverter stores every value it is sent or rounds or clamps some (only 8000 W is observed for charging).
- The off-grid effect of a lowered slot power (rung R3); the grid-connected register during a real outage.
- Whether the slot target SOC stops a charge below 100 % (rung R1) and whether it acts as a discharge floor (rung R6).
- 230's factor at other currents; the response of any setpoint at low power.
- The real BMS limits and derating; the taper below the top rate; usable capacity.
- The scope of 245; the behaviour and settings of peak shaving; the battery shutdown SOC during a forced export.
- The grid import limit of the installation (main fuse, supply agreement): a value only the owner can supply.
- Setting-write endurance and whether settings are flash-committed per write.
- Whether the inverter keeps its settings across a full power loss (inferred, not recorded).
- The cause of the 22 Sept 2026 discharge above the ceiling.
