# Dump-to-Grid command ceiling

Dump-to-Grid's closed-loop controller writes a battery discharge ceiling to the TOU power registers 256-261. The highest value it
will ever write is the **command ceiling**, `ecco_dump_controller_max_ceiling_w` in the firmware. It is the one source of truth
for that limit.

## Proof levels

| Configured command ceiling | Proof level |
|---|---|
| **3000 W**, the generic default | Hardware tested on the reference installation (two supervised scenarios, classic ESP32 controller; see [SUPPORTED_HARDWARE.md](../../SUPPORTED_HARDWARE.md)) |
| above 3000 W, up to **6000 W** | **Offline only**: tests, simulation and builds. 6000 W is the first staged live checkpoint. Not hardware tested |
| 7000 W to **8000 W** | **Architectural capability only**: the firmware accepts it, nothing has exercised it. Not hardware proven. It is attempted live only after the 6000 W stage has been reviewed |

Nothing above 3000 W is hardware proven. A build configured above 3000 W says nothing about your inverter, battery, cabling or
export permission.

## Seven separate quantities

| # | Quantity | Where it lives |
|---|---|---|
| 1 | Inverter or site maximum | `ecco_inverter_tou_power_ceiling_w`: the site's TOU power register bound, compiled in. ECCO does not read a rated power from the inverter |
| 2 | Battery / BMS capability | Not known to ECCO. No BMS register is read. You record it |
| 3 | Configured command ceiling | `ecco_dump_controller_max_ceiling_w` (default 3000 W) |
| 4 | Requested export target | *Dump to Grid Export Power*: a **net grid export** target, 500 W up to the site TOU bound. It is not clamped to the command ceiling, because export is battery plus PV minus house load |
| 5 | Commanded battery / TOU power | The controller's ceiling on 256-261 (*Dump to Grid Commanded Battery Ceiling*), always between the 500 W floor and the command ceiling |
| 6 | Measured response | Battery power (register 190) and grid CT power (register 172) |
| 7 | Runaway / implausible-response detection | The two guards described under [Runaway detection](#runaway-detection) |

## Configuring a ceiling

The ceiling is chosen at **build time only**. Home Assistant can never raise it. For example:

```
esphome -s ecco_dump_controller_max_ceiling_w 6000 compile firmware/ecco_clock_dongle_stage3_4_free_power_esp32s3.yaml
```

The diagnostic sensor *Dump to Grid Max Battery Ceiling* reports the value a running build was configured with.

The build refuses a value, and produces no firmware, when it:

- is not a plain decimal integer;
- is not above the 500 W controller floor (`ecco_dump_controller_min_ceiling_w`);
- is not a multiple of 100 W (`ecco_dump_controller_round_w`);
- exceeds the site's TOU power ceiling (`ecco_inverter_tou_power_ceiling_w`);
- exceeds **8000 W**, the architectural maximum.

### Record these first

Before configuring anything above 3000 W, record the following. ECCO cannot read or check any of them:

- the inverter model and its rated discharge and export power;
- the battery / BMS continuous discharge rating at its **lowest** operating voltage. The DC current is power divided by
  voltage: 6000 W at 48 V is 125 A, and 8000 W at 48 V is about 167 A;
- the inverter's own battery maximum discharge current setting (register 211). ECCO never writes it;
- the cable, fuse and isolator ratings on the battery current path;
- your export permission (DNO / connection agreement).

## What does not change

The Dump-to-Grid transaction, ownership, stop and restore model is the same at every configured ceiling:

- the START gates;
- the durable snapshot before any write;
- 256-261 written before 244, each verified by reread;
- controller steps of at most 1000 W, at least 45 s apart;
- the per-lease write budget;
- Stop SOC, duration expiry and End;
- drift and pre-write ownership checks;
- grid and SOC telemetry staleness;
- the Free Power interlock;
- restore with 244 first, then 256-261, exactly.

The firmware's write surface is unchanged and pinned by a test.

## Runaway detection

| Guard | Threshold on battery discharge | Consecutive samples |
|---|---|---|
| Ordinary guard (unchanged) | command + max(command / 2, 750 W) | 3 |
| Absolute backstop (changed) | **max(command, min(configured ceiling, 3000 W)) + 750 W** | 2 |

"Command" is the commanded ceiling: for 30 s after a verified step-down, the higher of the old and new command.

- **Up to 3000 W the backstop is unchanged.** For every configured ceiling of 3000 W or less it is exactly the old fixed
  `ceiling + 750 W` threshold, so default behaviour is identical.
- **Above 3000 W it follows the command.** The old threshold would sit at `ceiling + 750 W`; at 8000 W that is 8750 W, above
  anything the inverter can do and above the 8.6 kW discharge event recorded in 2026. Following the command, an inverter that
  overshoots or ignores a step-down is caught at any command level.
- **The backstop is never looser than before.** It equals the old threshold only while ECCO commands the configured
  ceiling.
- **The threshold is a measurement limit, not a command.** ECCO never commands above the configured ceiling.
- **The values are the existing ones.** The 750 W margin and the 2-sample count are the reviewed values from the
  2026-09-26 hardening. 3000 W is the highest ceiling at which this backstop has been validated live
  (`ecco_dump_runaway_backstop_floor_w`).
- **Known limit: the residual above 3000 W is unknown.** Measured discharge has run up to about 310 W above the command at
  3000 W; nothing above that has been measured. If the residual approaches 750 W at higher ceilings, leases at the ceiling
  end fail-closed. That ending is safe but a nuisance. It is a reason to stop at a stage gate, not to widen the margin
  without evidence.
- **Not covered by the firmware:** inverter warning / fault flags and BMS alarms do not end a lease automatically. During a
  live test they are an operator abort condition.

## The W2 fallback capture warning

When all six slot powers are equal and **no higher than the configured command ceiling**, a fallback profile capture shows
W2 ("resembles Dump to Grid residue; confirm"). The firmware's Review step makes that comparison against the configured
ceiling. Consequences:

- At the default 3000 W, W2 is exactly what it was.
- At an 8000 W ceiling every uniform profile up to 8000 W raises W2. W2 is a confirmation, not a refusal.
- **The same wording everywhere.** The fallback recovery card and the Home Assistant dashboard's Safety view
  (`home-assistant/dashboards/ecco_pro.yaml`) both word W2 without a wattage ("no higher than the Dump to Grid ceiling").
  The dashboard is frozen by the public-export proof, so `dtgp1` changes that one line as a declared post-export edit
  ([post-export-edit-layer.md](post-export-edit-layer.md)); undone, it is the exported "at most 3000 W" line.
- **Known stale header constant.** The capture header `firmware/include/ecco_fallback_capture.h` and its Python test mirror
  `registry/fallback_capture.py` still judge W2 against a fixed 3000 W (`DUMP_CONTROLLER_MAX_W`, commented as the controller's
  maximum ceiling). The firmware re-judges that one warning against the configured ceiling straight after the header's
  verdict; every other warning is the header's. The header is left byte-identical because an exported proof pins it
  (`registry/tests/test_failback_shadow_ha_contract.py` hashes every firmware file except the main YAML), and a firmware header
  is neither frozen nor chain-pinned, so the post-export edit layer cannot route it.

## Live acceptance (staged; to be run by the owner, supervised)

1. 3000 W baseline on the configured build.
2. About 4000 W.
3. About 5000 W.
4. 6000 W. **Stop and review the evidence.**
5. Only if 6000 W was clean: about 7000 W.
6. 8000 W.

**Every stage must:**

- start from fresh CT and telemetry;
- be a new supervised lease;
- show several control-loop corrections;
- show HIGH, TRACKING and LOW behaviour where practical;
- compare the measured response with the command;
- see no BMS or inverter alarm;
- end with an exact restore;
- finish with a check of register and state integrity.

**Abort on any of these:**

- stale CT telemetry;
- comms instability;
- an inverter or BMS alarm;
- a response that materially exceeds plausible command tracking;
- unexpected register state;
- an ownership mismatch;
- restore uncertainty;
- operator cancel.

A successful stage is recorded separately, for the exact installation, controller and firmware tested. It is never
generalised to other inverters or batteries.

## Tests

- `registry/tests/test_dump_to_grid_ceiling.py`
- `registry/tests/_dtgp1_scope.py` (the exact edits; post-export chain entry `dtgp1`, right after `pex0`; see
  [post-export-edit-layer.md](post-export-edit-layer.md))
- the unchanged 3000 W suites, such as `registry/tests/test_dump_to_grid_behaviour.py`
