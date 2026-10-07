# Register map provenance

## Summary

ECCO targets the register layout used by Deye/Sunsynk-family hybrid inverters, specifically the single-phase, low-voltage
layout. The origin of the register map before the project's first commit was not recorded. What the repository does record is
how the meanings were checked: side by side against an existing Home Assistant integration's readings, and through supervised
read and write tests on one reference installation. Selected registers were later cross-checked against an open-source
community project. Register behaviour may vary by model and firmware: treat every register as **unverified** on any other inverter until you have
checked it read-only.

No vendor protocol document is included in, or reproduced by, this repository, and no table or text from one is copied
here. This document makes no claim that the map was developed independently, reverse-engineered, or derived from any particular
document or project: its origin is simply not recorded.

## What the repository records

- `registry/inverter_capabilities.yaml` holds 165 capability records covering 150 register addresses (22-330). The firmware polls
  the blocks 22-24, 59-116, 150-196, 200-240, 241-293 and 330. That is the single-phase low-voltage layout; there is no
  500-700 block (three-phase / high-voltage layouts are not supported).
- Each record carries an evidence status. On the reference installation: 116 records are `live_proven_read`, 41
  `live_proven_write`, 1 `documented_not_live_proven` and 7 `unknown`. "Live proven" means exercised on that one installation,
  nothing more.
- No record cites an external document as its source.

| Family | Addresses | Evidence on the reference installation | Later cross-checks |
|---|---|---|---|
| Real-time clock | 22-24 | write and verify | - |
| Status, faults and flags | 59, 90-106, 280, 292-293, 330 | read only; register 330 bits 4-15 are of unknown meaning | 280 / 292 / 293 compared with an open-source integration |
| Energy counters | 70-108 | read; values matched an existing integration's readings | - |
| PV, grid, load and inverter telemetry | 79, 109-116, 150-194, 287-290 | read; values matched an existing integration's readings | - |
| Generator and AUX / smart load | 166, 195, 223-227, 235-241 | read only | - |
| Battery settings | 182-219 | partly read; register 214 (lithium wake-up bit) polarity is reported differently by another tool | - |
| Grid charge | 230-232 | supervised write test | - |
| Energy management and export | 242-248 | 244 supervised write test | 244 compared with open-source integrations |
| Time-of-use (six slots) | 250-279 | supervised six-slot write test | slot layout compared with an open-source integration |

Records with status `unknown`: `register_330_reserved_bits` (330 bits 4-15), five capabilities for which no register has
been identified (`signal_island_mode`, `inverter_protocol_version`, `inverter_rated_power`, `inverter_serial_number`,
`remote_lock`) and `smartdeye_battery_charge_voltage_parity` (a tracking record for a parity candidate). None of these is
written by ECCO. One record is `documented_not_live_proven`: `dump_to_grid_transaction`, the Dump-to-Grid transaction
record over 244 and 256-261 (a transaction, not a register meaning). Dump-to-Grid does write those registers; the pinned
record predates the feature's two hardware-tested scenarios in [SUPPORTED_HARDWARE.md](../../SUPPORTED_HARDWARE.md), so the
host-side capability model keeps `control.dump_to_grid` at `unknown` until a declared chain entry updates it
([docs/architecture/MODULAR_ARCHITECTURE.md](../architecture/MODULAR_ARCHITECTURE.md)).

## Cross-checks against open-source projects

Some registers (notably 244, the time-of-use slots and a few status bits) were compared, after the map existed, with the
register definitions of the open-source [kellerza/sunsynk](https://github.com/kellerza/sunsynk) project (Apache-2.0). Those
comparisons agreed on the addresses and bitmasks checked. Neither that project nor any other was the documented source of
the map, and no code, tables or text from it are included here. Where ECCO's Home Assistant entity names resemble names used
by other integrations, that is naming continuity for users moving between tools, not a claim about where a meaning came from.

## Wording in pinned files

Some comments inside pinned, hardware-verified files use the shorthand "Deye protocol" for this register layout (for example
the register 214 comment in `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` and the two historical firmware fixtures).
It does not refer to a cited vendor document. Those files are byte-identical to the hardware-verified source on purpose
(changing them means a declared proof-chain entry). The register map's own description of register 214 was reworded by the
declared public-export transition `pub0` (`registry/tests/_pub0_scope.py`, site kind `wording`), and six descriptions of the
SmartDeye parity candidates no longer name the person who listed them (site kind `attribution`). Register facts are unchanged.

## Contributing register information

- Do not add vendor documents, or tables or text copied from them.
- Information from another project needs a compatible licence and attribution in [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md).
- A new or changed register meaning needs its evidence stated (read-only observation, supervised write test, model and every
  firmware string), and a writable register needs agreement in an issue first (see [CONTRIBUTING.md](../../CONTRIBUTING.md)).
