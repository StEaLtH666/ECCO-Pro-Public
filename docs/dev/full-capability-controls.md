# Full-capability controls: the Dump to Grid limits in Home Assistant

Introduced by post-export entry `fcc1`. The firmware entries `fcp1` and `fcp2` store and **enforce** the Dump to Grid limits on
the dongle. `fcc1` adds the Home Assistant side the owner needs to set and watch them. It adds no firmware change, no Modbus
operation and no write from Home Assistant to the dongle.

See [inverter-capability-profiles.md](inverter-capability-profiles.md) for the limits themselves and
[dump-to-grid-safety-fcp2.md](dump-to-grid-safety-fcp2.md) for the restore, containment and readiness states.

## What is added

| File | What it does |
|---|---|
| `home-assistant/packages/ecco_dump_limits.yaml` | Template entities that **describe** the dongle's state, and one notification-only automation |
| `home-assistant/dashboards/ecco_full_capability.yaml` | A separate, admin-only dashboard (built-in cards only) |

### Package entities

| Entity | Meaning |
|---|---|
| `sensor.ecco_dump_limits_state` | `VALID`, `NOT CONFIGURED` (maximum grid export 0), `INVALID`, `AWAITING CONFIRMATION` (one limit confirmed after INVALID), `UNKNOWN` or `UNAVAILABLE`. A refused request changes nothing on the dongle, so it keeps the previous state. Attributes: the dongle's status text, the last refused request, both limits, the profile capability and a plain-language explanation. |
| `sensor.ecco_dump_ceiling_assessment` | The power ceiling against `input_number.ecco_dump_supervised_proven_w`: `AT`, `BELOW` or `ABOVE PROVEN LEVEL`. |
| `input_number.ecco_dump_supervised_proven_w` | The owner's **record** of the highest level proven in a supervised live test. Range 3000-8000 W; the first run is 3000 W, and Home Assistant restores the owner's value after that. Nothing reads it to change the dongle. |
| `binary_sensor.ecco_dump_export_limit_not_configured` | On while the maximum grid export is 0. |
| `binary_sensor.ecco_dump_limits_attention` | On while the limits are not VALID, the ceiling is above the proven level, or the limits write window is open. |
| Automation `ecco_dump_limits_schedule_notice` | While a Dump schedule is armed and the limits are not VALID, shows a persistent notification that the scheduled START would be refused. It dismisses the notification otherwise. No device action. |

### Dashboard

One view, **Dump Limits & Flash**:

- a banner while the maximum grid export is NOT CONFIGURED;
- the limits state with its explanation, both values and the proven level, and a warning while the ceiling is above it;
- the firmware's own **Power ceiling** and **Maximum grid export** boxes and the **Limits write enable** arm;
- how the limits change;
- the capability profile, explicitly labelled as a configurable range and not a proof;
- the restore, containment and operator-lockout states (display only; the recovery decisions stay on the main dashboard);
- firmware readiness: Safe To Flash, Flash Readiness, Restart Status and Build Identity.

No card calls a service.

## How the limits change (enforced by the dongle)

- **Lowering** either limit is accepted at any time, also during a lease. A running lease's ceiling only ever goes down.
- **Raising** a limit, or setting limits while they are INVALID, needs **Dump Power Limits Write Enable** first. The arm is good
  for one accepted change within 60 s and then turns itself off. Dump to Grid must be idle.
- After INVALID, **both** limits must be set again before Dump to Grid can start (`AWAITING CONFIRMATION` in between).
- A refused request changes nothing. The dongle's status line says why.

## After the flash: before any Dump to Grid START

1. Disarm any Dump to Grid schedule.
2. Check **Limits state**: `NOT CONFIGURED`, with the power ceiling at 3000 W (the factory state).
3. Turn on **Limits write enable**, then within 60 s set **Maximum grid export** to the net export the DNO permits for the
   installation (for example the value in the connection agreement). Never use the inverter's rating as that value.
4. Check that **Limits state** reads `VALID`, then re-arm schedules if wanted.

## Raising the power ceiling

Only 3000 W is hardware-proven. The profile capability (8000 W for the reference profile) is the build's configurable range. It is
**not** a proof that the battery, BMS, cabling or connection can export that much.

Raise one supervised stage at a time (for example 3000 → about 4000 → about 5000 → 6000 W, then stop and review). For each stage:

1. Arm, raise the power ceiling while Dump to Grid is idle, and run a supervised lease.
2. Watch the battery, BMS and grid readings, and the runaway, export and containment states.
3. Only then record the stage in **Supervised proven level**.

The dashboard warns while the ceiling is above the recorded proven level.
