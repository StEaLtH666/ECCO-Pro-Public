# Safety

ECCO-Pro is **experimental software that can write settings to a battery inverter**. This document explains what it can change, what that can mean in practice, what protections exist, and, just as important, what it cannot protect you from. Please read it before connecting ECCO to real equipment.

ECCO-Pro is provided **without warranty** and is not a certified product. See [No warranty](#no-warranty).

## 1. What ECCO can write

The firmware can write only a small, fixed set of inverter registers. An automated test pins the set, so widening it requires a visible code change and review.

| Registers | What they control | Features that write them |
|---|---|---|
| 22-24 | Inverter real-time clock | Clock (RTC) correction |
| 230, 232 | Grid-charge current and grid-charge enable | Free Power |
| 244 | Load/export mode (allow export, essentials, zero export) | Export-mode policy, Dump-to-Grid containment |
| 250-261 | Time-of-use slot times and power limits | Manual TOU, Free Power, Dump-to-Grid |
| 268-279 | Time-of-use slot target SOC, charge source and mode | Manual TOU, Free Power |

Everything else is **read-only**, including the export-limit register (245), battery protection thresholds, grid-protection settings and anything related to the inverter's safety trips. ECCO does not write installer-level protection settings.

There is **no automatic optimiser** that decides, on its own, to change these. Writes happen when you start an action, or when a schedule that **you configured and armed** starts one. A scheduled action runs unattended once armed, so treat arming a schedule as a decision to let ECCO write while you are not watching.

## 2. What the writes can do in practice

These are consequences of the settings, not hypothetical software faults:

| Change | Possible effect |
|---|---|
| Grid charging on (Free Power) | The inverter imports from the grid to charge the battery, at the power you set, up to the limits of the system. Import can be expensive outside a cheap-rate window, and a high charge power can approach your supply or breaker limits |
| Battery discharge ceilings and slot SOC targets (TOU, Dump-to-Grid) | The battery can discharge faster, slower or to a different level than your usual setup. It can reach low SOC sooner, leaving less energy for the evening or for backup |
| Export / load mode (244) and Dump-to-Grid | The system can export energy to the grid, or stop exporting. Export may be restricted by your connection agreement or tariff (see [Grid operator requirements](#6-grid-operator-and-regulatory-requirements)) |
| Clock correction (22-24) | A wrong inverter clock moves time-of-use slots. A correct clock correction normally helps, but a bad write can shift when charging and discharging happen |
| Anything left half-applied | If an action is interrupted, the inverter can be left with temporary settings until they are restored, by ECCO after recovery, or by you |

ECCO cannot know your tariff, your connection agreement, your installer's limits, or your battery manufacturer's recommended operating range. **You** are responsible for choosing values that suit them.

## 3. Back up the inverter configuration first

Before connecting ECCO to a real inverter:

1. Record **every** inverter setting you can see, using the inverter's own display and/or the manufacturer's own app or the installer's tools (screenshots with your account details cropped out are fine). Keep a dated copy somewhere safe.
2. Pay particular attention to: time-of-use table, grid-charge settings, battery SOC limits and shutdown/low-battery settings, work mode, export/zero-export setting and any installer-set power or export limit.
3. Keep the installer's contact details and the manufacturer's recovery instructions to hand.

ECCO's **fallback profile** saves a user-captured subset of settings in the controller and can show whether the live inverter still matches it. It is **not** a full backup, and ECCO cannot currently apply it for you (see [Restore and fallback behaviour](#8-restore-and-fallback-behaviour)). Your own record is the backup.

## 4. Unsupported models and firmware

- Only the systems in [SUPPORTED_HARDWARE.md](SUPPORTED_HARDWARE.md) have any evidence of working, and at present that evidence covers a single reference system. **No model is listed as supported yet.**
- Register layouts and meanings can differ between models, phases, battery types and **firmware versions**, including within one brand. A register that is a charge current on one model may mean something else on another.
- The firmware targets a single-phase, low-voltage register layout. Three-phase, high-voltage-battery and other layouts are **unsupported**.
- Inverter firmware updates can change behaviour. After an inverter update, re-verify ECCO read-only before allowing writes.
- **If your system is not listed:** run read-only first (leave every write-enable switch off), compare ECCO's displayed values against the inverter's own display, and do not enable writes. A compatibility report is welcome (see [SUPPORT.md](SUPPORT.md)). Register meanings are not independently documented by a vendor reference in this repository.

## 5. Electrical work and installation

- ECCO is software and a low-voltage controller. It does not change your wiring, but the controller connects to the inverter's communications port. Follow the inverter manufacturer's instructions and have a **suitably qualified person** do any work inside or on the inverter, the battery or the mains side.
- Use an RS485 adapter appropriate for the port. The firmware has no direction-control line, so an automatic-direction adapter is needed.
- Never open an enclosure or touch live parts based on anything in this project.
- Do not use ECCO to bypass an installer-set limit, a battery manufacturer's limit, or a protection setting.

## 6. Grid operator and regulatory requirements

- Grid-connected generation and storage are usually subject to local rules and to your connection agreement. In the UK, for example, an export-capable system may need to be notified to or approved by the distribution network operator (DNO) under the applicable engineering recommendation, may have an agreed export limit, and your tariff or export scheme may have its own conditions. Other countries have equivalent rules.
- Features that **allow or increase export** (export mode, Dump-to-Grid) can take you outside those conditions. ECCO does not know your agreed limit and does not read it from your DNO.
- Check with your installer, your DNO/grid operator and your energy supplier **before** enabling any export-related or grid-charging feature, and keep ECCO's power settings within what you are permitted to do.
- Responsibility for compliance rests with the system owner.

## 7. Other Modbus masters and manufacturer cloud apps

- The ECCO controller assumes it is the **only Modbus master** on the RS485 port it uses. Do not connect another logger, gateway or controller to the same bus while ECCO is writing. Two masters can collide, corrupt each other's reads and writes, and produce results neither expects.
- Never run two ECCO controllers with the same identity on one bus or network. The ESP32-S3 variant replaces the classic controller; it does not run beside it.
- The manufacturer's own app, cloud service or logger may also change inverter settings, either directly or through its own communications path. If something else changes a setting while an ECCO action is active:
  - ECCO's restore may overwrite that change or may refuse to proceed (it tries to detect "neither the original nor the intended state" and then stops and waits for a person);
  - register 244 changes during a Free Power action are detected and block automatic restore until a person decides;
  - the safety and fallback views show a mismatch (drift), but **ECCO cannot stop other tools from changing the inverter**.
- When using ECCO, avoid changing the same settings from another tool at the same time.

## 8. Restore and fallback behaviour

**What exists today**

| Behaviour | Status |
|---|---|
| **Snapshot before write.** Free Power, register 244 and Dump-to-Grid take a snapshot of the original values and store it durably in the controller *before* writing | Hardware tested on the reference system |
| **Verify after write.** Writes are read back and compared exactly. A mismatch is a failure, not a success | Hardware tested |
| **Timers and watchdog in the controller.** Free Power and Dump-to-Grid are time-limited. The controller ends and restores them itself, so Home Assistant being unavailable does not stop the restore. If the bus is busy it retries | Hardware tested for the normal paths |
| **Durable records survive reboots.** After a reboot the controller reads its records. An unreadable record is treated as *unknown*, not *clear*, and blocks writes | Offline tested; some paths hardware tested |
| **Bounded retries, then a person decides.** Repeated restore failures or an unrecognised inverter state lock further automatic writes and ask for an operator decision | Offline tested |
| **Operator recovery** (review live state, force restore original, accept current state) | **Offline tested only. Not hardware-tested** |
| **Fallback profile**: save, invalidate and compare a user-captured profile | Hardware tested |
| **Applying the fallback profile / automatic failback if Home Assistant is lost** | **Not implemented. Not enabled.** If Home Assistant is lost, ECCO does **not** put the inverter back to a saved profile |

**What this means for you**

- A temporary action still ends on its timer without Home Assistant. A *manual* TOU apply has **no** automatic rollback; you own it.
- If the controller **loses power, crashes or loses the RS485 link during an active action**, the inverter keeps whatever settings were last written until they are restored, by ECCO after it recovers or by you. Do not assume the inverter has returned to its original state until you have checked it.
- **Firmware upgrades:** flash new firmware only when no durable recovery obligation is open (all recovery markers read *clear*). A different firmware version may not understand an older version's stored record and will treat it as a blocked obligation.
- After a controller is replaced, its stored state does **not** migrate. Re-save the fallback profile and re-enter its stored settings (see the developer docs for the S3 swap).
- Restoring a good state is a **test you should run yourself**: before relying on any feature, do a short, low-power run while watching the inverter and confirm it returns to your recorded settings.

## 9. Battery reserve

What is enforced today, and by which layer:

- **Dump-to-Grid** stops at a stop level you choose. The firmware refuses a stop level below 10% and the Home Assistant scripts
  bound it to 10-90% (default 25%). These are software bounds of this feature, **not** a statement of what is safe for your
  battery. Dump-to-Grid does **not** yet check a separate, user-configured reserve.
- The inverter's own battery protection settings (for example its shutdown / low-battery levels) remain the final protection.
  ECCO does not change them.
- Set the Dump-to-Grid stop level at or above the minimum your inverter / battery configuration permits and the level you want
  to keep for the evening or for backup.

## 10. Reporting a safety problem

If ECCO wrote something unexpected, restored incorrectly, or left your inverter in a changed state:

1. Turn all ECCO write-enable switches off and, if necessary, disconnect the controller from the RS485 bus.
2. Restore your inverter settings from your own record.
3. Report it privately if it could affect others or is a security issue ([SECURITY.md](SECURITY.md)), otherwise through a bug report ([SUPPORT.md](SUPPORT.md)). Describe what happened without secrets, serial numbers, account ids, addresses or household telemetry.

## No warranty

ECCO-Pro is provided "as is", **without warranty of any kind**, express or implied, including fitness for a particular purpose. To the extent the law allows, the authors and contributors are **not liable** for any loss or damage arising from its use, including loss of energy, financial loss, equipment damage, voided manufacturer warranties or consequences under a grid connection agreement. The project's licence (GPL-3.0-or-later) contains the legally operative "Disclaimer of Warranty" (section 15) and "Limitation of Liability" (section 16); this section is a plain-language summary and does not replace them. See [LICENSE](LICENSE).
