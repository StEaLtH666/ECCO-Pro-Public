# Supported and tested hardware

> **Experimental software. No inverter model is listed as supported yet.**
> This page records what has actually been tested, how strongly, and what is unknown. Anything not listed here is **unsupported and unverified**, including other models and other firmware versions of the same brand. Read [SAFETY.md](SAFETY.md) before connecting anything.

## Proof levels

Every tested system and feature is labelled with exactly one of these levels; use the *lowest* level that is true. Rows that were never tested say **Unsupported** (or *unknown*), and features that do not exist say **Not implemented**.

| Level | Meaning | What it does **not** mean |
|---|---|---|
| **Offline only** | Covered by tests, simulation, static analysis and/or a firmware compile. Never run against a real inverter in the stated configuration | Nothing about real behaviour |
| **Hardware tested** | Exercised against at least one real inverter, deliberately and supervised, with the outcome checked (for writes: read back and verified, and restored). The system described in the row, nothing else | Not a general compatibility claim. Not evidence for other models, firmware, batteries or tariffs |
| **Production proven** | Hardware tested **and** in day-to-day use for **at least six months** on **at least two independent installations**, with every automatic action of the feature logged, incidents recorded, and no unexplained write | Still not a guarantee. Not a certification |

**Current claim: no row is labelled production proven.** ECCO has run on one reference installation only, since September 2026, so the threshold above cannot be met in 0.9.0.

## Matrix

| ID | Inverter (make / model) | Topology | Inverter firmware | Controller hardware | ESPHome | Proof level | Features exercised (see matrix below) | Evidence in the repository | Notes |
|---|---|---|---|---|---|---|---|---|---|
| H-001 | Deye/Sunsynk-family hybrid inverter (the reference installation). Exact make and model: **not recorded in the project's evidence, so not published** | Single-phase, low-voltage. The register layout in use is the single-phase layout; the registry describes the reference installation as single-phase | **Not recorded** in the project's evidence. Do not assume any firmware version behaves the same | ESP32 (classic, `variant: esp32`) with an RS485 transceiver; firmware `ecco_clock_dongle_stage3_4_free_power.yaml`. Board product and RS485 adapter model are not recorded; the adapter must be an automatic-direction type (see the wiring section) | 2026.8.x (compiled with 2026.8.2) | Hardware tested | Live monitoring, RTC correction, manual six-slot TOU, Free Power (normal path), register 244 export-mode policy, Dump-to-Grid (two scenarios), fallback profile save/invalidate/compare, supervision heartbeat | Capability registry (`registry/inverter_capabilities.yaml`) proof fields and the live-proof records of the private development archive; the firmware and its offline suites | The reference system is a real household installation in the UK. No site identifiers are published |
| H-002 | Same system as H-001 | Same | Same | **ESP32-S3** (N16R8 module) running the hardware wrapper `ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml`, which includes the H-001 firmware unchanged. PSRAM present but **not** enabled. Board product not recorded | 2026.8.x (compiled with 2026.8.2) | Hardware tested | Boot, reboot and persistence on this controller, and read-only polling, the supervision heartbeat and its observe-only shadow check in normal operation. **No write feature has been separately re-proven on this controller**: for the S3, the H-001 write features rest on the offline equivalence check only (treat them as *offline only* on an S3) | Generated C++ of the wrapper and the classic build differ only in the logger UART, board and variant (checked by an offline equivalence check); live migration record in the private archive | In use as the controller on the reference system. The original classic controller is kept as a spare. **Never run both on one bus** |
| H-003 | Any other Deye, Sunsynk or rebadged model | Unknown | Unknown | Unknown | Unknown | **Unsupported / unknown** | None | None | See "Compatibility reports" in [SUPPORT.md](SUPPORT.md) |
| H-004 | Any three-phase, high-voltage-battery or non-Deye-family inverter | Different register maps are expected | n/a | n/a | n/a | **Unsupported** | None | The firmware polls the single-phase low-voltage register blocks only | Do not attempt |

Battery: the battery make, chemistry and BMS link of the reference installation are not recorded in the project's evidence, and no battery is described as supported. ECCO reads only what the inverter reports; battery capacity and efficiency are site settings in Home Assistant, not tested properties. The minimum state of charge your battery and inverter configuration permit is site-specific: see [SAFETY.md](SAFETY.md#9-battery-reserve).

## Feature proof, per capability

All entries refer to the reference system(s) above only.

| Capability | Proof level | Notes |
|---|---|---|
| Read-only telemetry and configuration polling | Hardware tested | Single-phase low-voltage register blocks 22-24, 59-116, 150-196, 200-240, 241-293 and 330 |
| Inverter clock (RTC, registers 22-24) correction | Hardware tested | Write/verify proven. The current drift-correction policy is deployed on the reference installation; not every one of its automatic correction windows had been observed when 0.9.0 was prepared |
| Manual six-slot TOU (registers 250-261, 268-279) | Hardware tested | No automatic rollback of a manual apply |
| Free Power: normal start → automatic restore | Hardware tested | Grid charge current/enable (230, 232) and the TOU registers |
| Free Power operator recovery (review / force restore / accept current state) | Offline only | Implemented and extensively simulated; not exercised on hardware |
| Register 244 (load/export mode) policy write with durable restore | Hardware tested | Register 245 (export limit) is **read-only** in this firmware |
| Dump-to-Grid | Hardware tested for two scenarios, at the default **3000 W** command ceiling; **offline only** for every other path | Includes the closed-loop export controller. Measured battery discharge ran above the commanded ceiling by a few hundred watts in observations, cause not yet established. The command ceiling is a build-time setting (default 3000 W; [docs/dev/dump-to-grid-ceiling.md](docs/dev/dump-to-grid-ceiling.md)). Up to **6000 W**: **offline only**, the first staged live checkpoint, not hardware tested. 7000 W to **8000 W**: architectural capability only, **not hardware proven** |
| Fallback profile: save, invalidate, live-match display | Hardware tested | |
| Fallback restore / automatic failback | **Not implemented** | Stated here so it is not assumed |
| Supervision heartbeat and shadow check | Hardware tested (observe-only) | Changes nothing on the inverter |
| System Health (Home Assistant checks and reason codes) | Hardware tested | On the reference installation's Home Assistant |
| Intelligence V1 | Offline only | Shadow-only, synthetic data, no write path |
| Battery Outlook via InfluxDB | Hardware tested | On the reference installation's Home Assistant and InfluxDB; a Home Assistant / InfluxDB feature, not an inverter write |
| Automatic optimiser control | Not implemented | |

## What ECCO can write

The complete set of registers the firmware can write, pinned by an automated test:

| Registers | Meaning (summary) | Used by |
|---|---|---|
| 22, 23, 24 | Inverter real-time clock | RTC correction |
| 230, 232 | Grid-charge current and grid-charge enable | Free Power |
| 244 | Load/export mode | Register 244 policy, Dump-to-Grid containment |
| 250-261 | TOU slot times and powers | Manual TOU, Free Power, Dump-to-Grid |
| 268-279 | TOU slot target SOC and source/mode flags | Manual TOU, Free Power |

Every other register is read-only. Meanings are not independently documented by a vendor reference in this repository; see the [register-provenance note](docs/dev/register-provenance.md). The registry marks seven records as unknown meaning and one as documented but not hardware-proven.

## Firmware and software versions

| Component | Tested / required | Notes |
|---|---|---|
| ESPHome | **≥ 2026.8.2 and < 2026.9.0** | Enforced by compile-time checks. A build with ESPHome 2026.9.x is expected to fail by design |
| ESP-IDF framework (via ESPHome) | 5.5.x | Same enforcement |
| Home Assistant | Tested with a 2026.9.x release on the reference installation. **No minimum version is claimed** | The custom cards' `hacs.json` declares 2024.8.0; that value is not a tested minimum |
| Python for repository tests | 3.12 (CI) | |
| Node for card builds/tests | not pinned; tested locally with Node.js 24 | CI does not run the card tests yet (planned after 0.9.0) |

## Wiring and controller requirements (from the firmware)

- Inverter-side UART: TX GPIO17, RX GPIO16, 9600 baud, 8N1 (both controller variants).
- There is **no RS485 direction-control pin** in the firmware. Use an automatic-direction RS485 adapter, or one with DE/RE strapped in hardware.
- The controller must be the **only Modbus master** on the inverter bus while ECCO writes (see [SAFETY.md](SAFETY.md)).
- Two ECCO nodes with the same hostname must never be on the network at once.

## Known unknowns (do not assume)

- Exact inverter models and firmware versions that behave like the reference system.
- Behaviour with other batteries/BMS, other grid codes and other tariffs.
- Behaviour with the inverter vendor's cloud app or another logger active on the same RS485 bus.
- Register 330 bits 4-15 and several other registers whose meaning is recorded as unknown.
- Whether other firmware versions interpret registers 214, 243-248 or the TOU mode bits the same way.

## How to add a row

Open a hardware compatibility report (see [SUPPORT.md](SUPPORT.md)) containing: inverter make/model, **every firmware/version string**, phase type, battery type, controller board and RS485 adapter, ESPHome and ECCO versions, what you exercised, **read-only versus write**, and how you verified it. State the proof level honestly. Maintainers will add the row and may ask for a read-only capture first. Never include serials, MPANs, account ids, IP/MAC addresses or household telemetry.
