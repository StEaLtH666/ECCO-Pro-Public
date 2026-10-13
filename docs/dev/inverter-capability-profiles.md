# Inverter capability profiles and Dump to Grid operating limits

Introduced by post-export entry `fcp1`. The dongle carries **one** firmware image for an inverter's full validated capability.
Power levels are then chosen in Home Assistant, as settings stored and enforced on the dongle, never by rebuilding the firmware.

## Four quantities, four separate enforcements

| Quantity | Meaning | Unit | Where it lives | How it is enforced |
|---|---|---|---|---|
| **Inverter capability** | The highest TOU battery-discharge power the Dump controller may ever be configured to command on this inverter | W, AC | the build's **profile**: `ecco_dump_capability_w`, at most the profile's TOU register bound `ecco_inverter_tou_power_ceiling_w` | compile time (the build refuses an inconsistent profile); the run-time settings can never exceed it |
| **Dump power ceiling** | The highest TOU power (registers 256-261) the controller may command during a Dump lease | W, AC | run-time setting **Dump to Grid Power Ceiling**, persisted on the dongle; 500 W up to the capability, 100 W steps; factory value 3000 W | **latched** at START for the whole lease; the controller and the runaway backstop never go above the latched value |
| **Battery discharge** | What the battery actually delivers | W, DC (register 190) | measured | the existing runaway guards, relative to the current command |
| **Net grid export** | Power leaving the site at the grid meter | W, AC (grid CT, register 172; negative = export) | run-time setting **Dump to Grid Max Grid Export**, persisted on the dongle; 0 = not configured; 10 W steps | START refuses unless it is configured and the requested export target is within it; during a lease the dongle ends the lease if 3 of the last 4 fresh CT samples exceed it by more than max(100 W, 3 %) |

The requested **export target** (*Dump to Grid Export Power*) remains a target for the controller, not a limit.

## Factory state after the flash

- Power ceiling **3000 W**, the only hardware-proven value.
- Maximum grid export **not configured**: every Dump to Grid START is refused, with "maximum grid export not configured", until
  the owner sets the permitted export (for example the value in the connection agreement).

## Changing the limits from Home Assistant

- **Raising** a limit, or setting limits that are INVALID, requires turning on **Dump Power Limits Write Enable** first. The arm
  is good for one accepted change within 60 s and turns itself off. The change is accepted only while Dump to Grid is idle.
- **Lowering** a limit needs no arm and is accepted at any time. During a lease:
  - a lower power ceiling lowers that lease's latched ceiling at once, and the controller steps the command down with its normal
    verified write;
  - a lower export limit applies to the export guard at once.
- A running lease is **never** raised: a raise is refused while Dump to Grid is not idle, and a lease only ever reads its own
  latched ceiling.
- Every request, accepted or refused, is reported in **Dump Power Limits Status**. A refused request changes nothing.

## Persistence and validation

The two settings, the profile capability they were stored for, and an integrity value are kept in the dongle's preferences (NVS).
At every boot the firmware checks them: range, step, capability match and integrity. If any check fails, the limits are
**INVALID**; every START is refused until both are set again (armed, idle). The firmware never falls back to a larger or
unlimited value.

These preference keys are new. Older firmware ignores them, and the durable Dump, Free Power and fallback records keep their
schemas, so the previous firmware can still be flashed back.

## Adding another inverter's profile

1. Record the inverter's evidence: its model, its rated power and its TOU power register bound.
2. Add an entry to `registry/inverter_profiles.yaml` with the four substitution values.
3. Build with those values as `-s` overrides. The build refuses an inconsistent profile.
4. A capability above what has been proven live is the profile's configurable range, not a proof. Each higher operating level
   is proven live, supervised, on that installation.

There is no global maximum: a profile's capability is limited only by its own TOU register bound, which must fit a 16-bit
register.

## Not changed

- No new Modbus operation and no new inverter write domain; register 245 is never written.
- The runaway guards, Stop SOC, duration, drift and ownership checks, and the restore path are unchanged.
- At the factory 3000 W ceiling, Dump behaves as before once the export limit is configured.

Tests: `registry/tests/test_dump_capability_limits.py`; scope: `registry/tests/_fcp1_scope.py`.
