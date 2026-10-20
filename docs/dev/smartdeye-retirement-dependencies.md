# SmartDeye retirement: dependency inventory (offline, 2026-10-20)

Status: **INVENTORY ONLY.** Nothing here disconnects, disables or changes SmartDeye, the inverter, Home Assistant or ECCO. It
does not say SmartDeye is safe to remove. Each item is graded:
- **GROUNDED**: stated in this repository (file named);
- **UNKNOWN**: not established anywhere here; the owner must confirm;
- **CANDIDATE**: built offline, not installed, not live-proven.

A Stage 1 settings GUI on its own is **not** a reason to retire SmartDeye.

## 1. Why this matters

SmartDeye is a second actor on the inverter.
- `docs/dev/advanced-config/stage0-safety-case.md` names it "the documented second master" that must not be used at the same
  time as an ECCO edit.
- The fallback design (`docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md` section 14) assumes other Modbus masters may reach
  the inverter, for example through a vendor logger.
- Its writes are invisible to the dongle (`tools/fbd1_soak/safety.py`: "Writes by a second Modbus master (for example a
  SmartDeye reader with writable clock controls) are invisible to the dongle").

Retiring it would remove that uncontrolled writer, which is good. It would also remove whatever the owner currently uses it
for, which must exist in ECCO first.

## 2. Settings: what ECCO can do today versus SmartDeye

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

**Which of these the owner actually changes with SmartDeye today: UNKNOWN.** This is the first item of the checklist (section 5).

## 3. Non-setting dependencies

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

## 4. What retiring SmartDeye does not need

- It does not need Stage 2 or Stage 3 settings, **unless** the owner uses SmartDeye to change those settings.
- It does not need the whole 165-row catalogue to be writable. Most rows are read-only by design and should stay so.

## 5. Owner checklist before any retirement (no physical action implied)

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

## 6. What this inventory deliberately does not claim

- That SmartDeye is safe to remove.
- That Stage 1 is installed or live-proven.
- That SmartDeye causes any ECCO symptom.
- Anything about SmartDeye features not recorded in this repository.
