# ECCO inverter capability registry

> **Note for readers of the public repository.** This is the registry's design and format record, kept as written during
> development. References to `CURRENT_STATE.md`, `CHANGELOG.md`, task numbers, PR numbers and to design or audit documents that are
> not in this repository point at the private development history, which is not published. The register map's provenance is
> described in [docs/dev/register-provenance.md](dev/register-provenance.md).

Status: **DESIGNED, partially IMPLEMENTED as a static data file. NOT
wired into any runtime code.** `registry/inverter_capabilities.yaml`
exists and validates; nothing in this repository reads it to drive a UI
or perform a write. This document is the format specification for that
file, plus the shared vocabulary (write policies, evidence levels,
lifecycle) used across every Task 005/005A document.

**Schema v2 (Task 005A)** replaced Task 005's original schema after
review: `safety_class` split into two independent axes
(`write_policy` / `current_access`, see below), free-text
`modbus.registers` strings were replaced with a structured,
machine-checkable register/bit-range/sharing declaration, and several
previously-grouped records (six-slot TOU fields, battery
configuration, PV strings, grid protection thresholds, energy
counters) were exploded into one record per independently-addressable
value. The registry grew from 35 to 158 records as a result - this was
expected, not a regression; see "Grouped records" below for what
grouping remains legitimate.

**Task 005B** hardened the schema-v2 validator against edge cases a
second review pass found: the registry file now declares
`schema_version: 2` explicitly and the validator rejects anything
else; every capability must carry a documented minimum set of core
fields rather than silently permitting them to be absent; register
addresses and bit ranges are checked against the physical bounds of a
16-bit Modbus register (0-65535 / 0-15); `shared_with` metadata is
validated against itself (must reference a real capability, not
itself, not be duplicated, and must actually correspond to a
capability claiming the same register - stale sharing metadata is now
an error, not silently ignored); W1/W2 (active write classes) now
require a genuinely machine-checkable bound - a free-text `bounds_note`
alone no longer satisfies them (it remains valid for W3/WX/R0, where
UNKNOWN is preferable to a guessed number); a W3 capability may only
become `current_access: read_write` with `live_proof_status:
live_proven_write` behind it, not merely by someone editing YAML; and
`grid_charge_current`'s `limits.hardware.value` (previously 185A) was
corrected - that figure was an *observed pre-transaction snapshot*,
not an independently-verified hardware maximum, and is now represented
as `transaction_limit` instead (see "Structured limits" below).

## Purpose

Before ECCO can safely offer more manual inverter control, it needs one
authoritative answer to three questions per capability: **what do we
actually know about this register/value, how confident are we, and is
it currently allowed to be written.** The registry is that answer,
kept separate from firmware/HA source so it can be audited, tested, and
referenced without re-deriving it from 6000 lines of ESPHome YAML every
time.

## File location and format

`registry/inverter_capabilities.yaml` - chosen over the task's suggested
`config/inverter_capabilities.yaml` because this repository has no
`config/` directory (Home Assistant runtime config lives under
`home-assistant/`, which this is not); a new top-level `registry/`
directory keeps this distinct from both HA runtime config and the
`docs/` design-note collection, since it is machine-readable data with
its own validator and tests, not prose. `tools/validate_capability_registry.py`
validates it; `registry/tests/` contains offline tests for both the
registry and the transaction architecture.

Top level:

```yaml
schema_version: 2
capabilities:
  - id: <stable snake_case ID, unique>
    name: <friendly name>
    category: <rtc | tou_schedule | grid_charge | free_power | battery | pv | grid | load | inverter_output | generator | aux | energy_management | energy | status | diagnostic>
    description: <free text>
    entity_ha_raw: [<raw HA entity id(s)>] | null
    entity_ha_canonical: [<canonical ECCO entity id(s)>] | null
    esphome_component: [<ESPHome id(s)/component references>] | null
    modbus: <REQUIRED unless physical_register: false - see below>
      registers:
        - address: <decimal register address, REQUIRED, integer 0-65535 - no free-text strings>
          bits: "<e.g. '0-1' or '3', 0-15 only; omit for the whole 16-bit register>"
          shared_with: [<other capability id(s) that also claim this same address - each must exist, must not be this capability's own id, must not repeat, and must itself claim the same address>]
      register_width_words: <int>
      datatype: <uint16 | int16 | bitfield_uint16 | enum_uint16 | packed_uint16_pairs | uint32_dword_lo_hi | bitmask_uint16xN | not_applicable | unknown>
      signed: <true | false | unknown | not_applicable>
      byte_order: <description | unknown | n/a>
      scale: <numeric multiplier | mixed | unknown | not_applicable>
      unit: <unit string | null | mixed>
    physical_register: <false, ONLY for a genuine non-Modbus derived/meta capability - explicitly opts out of the 'modbus' requirement>
    current_access: <read_only | read_write | write_only - REQUIRED>
    write_policy: <see Write policies below - REQUIRED>
    write_policy_reason: <REQUIRED for every W1/W2/W3 - why this class, not a higher or lower one>
    enum_mapping: {<raw value>: <meaning>} | null
    firmware_evidence: <file:line citation and/or description>
    ha_evidence: <file citation> | null
    safe_min / safe_max: <value> | null
    field_bounds: [{field: <name>, min: <number>, max: <number>}, ...] | null - a machine-checkable bound for a multi-field PACKED write (e.g. RTC's packed date/time) where no single safe_min/safe_max pair makes sense
    bounds_note: <free text - valid for W3/WX/R0 (UNKNOWN is preferable to a guessed number), but NEVER by itself sufficient for W1/W2 - see "Machine-checkable bounds" below>
    limits: <structured hardware/operating/effective ceiling - see "Structured limits" below; only used where the three-tier hardware-ceiling model genuinely applies>
    transaction_limit: <structured transaction-scoped cap, distinct from a hardware ceiling - see "Structured limits" below>
    exact_reread_verification_possible: <true | false | unknown | not_applicable>
    verification_tolerance: <exact | description | unknown | not_applicable>
    multi_register_write: <true | false>
    snapshot_required: <true | false>
    restoration_possible: <yes_live_proven | yes_via_cached_raw_registers | yes_via_dedicated_persisted_snapshot | not_applicable | unknown>
    recovery_implementation_status: <see "Recovery implementation status" below - REQUIRED>
    safety_impact: <free text - REQUIRED, must explain the actual consequence, not just restate the value>
    dependencies:
      capabilities: [<other capability id(s), validated to exist>]
      entities: [<HA entity id(s) this depends on, format-checked>]
      flags: [<interlock/state-flag names that are not registry capabilities, e.g. manual_write_in_progress>]
    allow_self_dependency: <true, only if dependencies.capabilities deliberately includes this record's own id>
    implementation_status: <implemented | implemented (read only) | designed | not_implemented - REQUIRED>
    live_proof_status: <see Evidence levels below - REQUIRED>
    notes: <open questions, caveats, or empty/null>
```

Not every field applies to every capability (e.g. `enum_mapping` is
meaningless for a plain numeric register) - omit fields that do not
apply rather than filling them with a placeholder. `name`, `category`,
`current_access`, `write_policy`, `live_proof_status`,
`implementation_status`, `safety_impact`, and `recovery_implementation_status`
are required on every record (`tools/validate_capability_registry.py` rejects
a record missing any of them, including an explicit YAML `null`); for any
W1/W2/W3 record, `write_policy_reason` is additionally required. A
capability record without a real answer to "what happens if this is
wrong" or "why this class" is not finished.

### Recovery implementation status

Added Phase 0b (2026-09-22), after register 244's durable snapshot/write/
verify/restore/clear transaction was hardened (PR #13/#14) and live-proven
end to end (2026-09-22), while Manual TOU still only has a volatile
read-modify-write cache behind the same `snapshot_required: true` flag
(docs/SAFE_TRANSACTION_ENGINE_AUDIT_2026-09-21.md risk R1). `snapshot_required`
and `restoration_possible` state the **safety requirement** and *name* a
recovery mechanism, but do not by themselves say whether that mechanism is a
robust, durable, power-loss-safe implementation or merely a description of
what would be nice. `recovery_implementation_status` is the separate axis
that states the mechanism's actual **implementation status**, using a fixed
vocabulary rather than free prose so it cannot be answered vaguely:

- `not_required` - `snapshot_required` is `false`; there is nothing to
  implement. This is the ONLY valid value when `snapshot_required` is `false`,
  and it is invalid when `snapshot_required` is `true` (enforced by
  `tools/validate_capability_registry.py`).
- `required_not_implemented` - `snapshot_required` is `true` and no recovery
  mechanism exists at all yet.
- `partial` - a recovery mechanism exists but is not the durable,
  power-loss-safe transaction/marker mechanism this class of write needs -
  e.g. the six-slot TOU fields' `restoration_possible: yes_via_cached_raw_registers`
  is a real but volatile (in-RAM, no age bound, does not survive a reboot)
  cache-based restore, not the durable snapshot register 244 now has.
- `implemented_not_live_proven` - the durable mechanism itself has been
  implemented and deployed, but has not had an actual live restore round
  trip performed against real hardware since it was deployed. Free Power's
  registers (`free_power_transaction`, `grid_charge_current`,
  `tou_global_grid_charge_enable`) are here: PR #13/#14 hardened the shared
  durable snapshot/recovery-marker mechanism they use, but no live restore
  round trip has been performed against Free Power specifically since that
  hardening landed - only register 244 has that post-hardening live proof.
- `live_proven` - the durable mechanism has had a live restore round trip
  performed against real hardware since it was implemented. Only
  `grid_export_policy` (register 244) currently qualifies: durable snapshot
  -> write -> verify -> restore -> verified-pending-clear -> durable clear,
  proven live 2026-09-22.

`tools/validate_capability_registry.py` enforces that every record declares
this field with a value from the vocabulary above, and that it is consistent
with `snapshot_required` (a `true` requirement cannot claim `not_required`,
and a `false` requirement cannot claim anything else). Bumping a capability's
status up (e.g. `partial` -> `live_proven`) must be backed by an actual
proof event, not a documentation edit - `registry/tests/test_capability_registry.py`
scenario [40] pins today's known values so an unbacked bump is caught as a
test failure rather than landing silently.

### Structured register declarations

Schema v1 allowed `modbus.registers` to be a free-text string (e.g.
`"251-255 (start), 257-261 (power)..."`) for grouped records, which
`tools/validate_capability_registry.py` then skipped entirely for
duplicate-register checking - a validation blind spot exactly where
shared/complex registers mattered most (Task 005A review finding).
Schema v2 removes that escape hatch: `modbus.registers` is always a
list of `{address, bits?, shared_with?}` entries with a real integer
`address`. Two records may legitimately reference the same `address`
only when **both sides** mutually list each other in `shared_with`,
and even then only in one of two shapes:

- **Identical bits** (including both omitting `bits`, meaning the
  whole register) - the same physical field represented under two
  capability records for a real reason, e.g. `tou_slot_1_end_time` and
  `tou_slot_2_start_time` are the same register (251) under two
  UI-facing labels, or `free_power_transaction`'s claim on register
  230 is identical to `grid_charge_current`'s (the same field, written
  by two different mechanisms/capability "views").
- **Disjoint bits** - genuinely different sub-fields of one register,
  e.g. `tou_slot_1_charge_source` (bits 0-1) and `tou_slot_1_mode`
  (bits 2-4) both live in register 274.

Any other relationship - undeclared sharing, or declared sharing with
bit ranges that partially overlap without being identical - fails
validation. This is enforced by
`tools/validate_capability_registry.py`'s `_validate_register_sharing`
pass; see `registry/tests/test_capability_registry.py` scenarios
[13]-[16] for the exact accept/reject cases.

A register `address` must be `0`-`65535` and a `bits` value/range must
be `0`-`15` (the physical bounds of a 16-bit Modbus register) - both
are enforced independently of the sharing checks above (Task 005B
section 3; see scenario [36]).

**`shared_with` metadata is validated against itself**, not just
pairwise against another record (Task 005B section 4): every id listed
must be a real capability id in this registry, must not be the
declaring capability's own id, must not be listed twice, and must
correspond to a capability that *itself* also claims the same
`address` - a `shared_with` entry pointing at an unrelated capability
on a different register, or at an id that no longer exists, is stale
metadata and fails validation rather than being silently ignored (see
scenario [37]).

### Machine-checkable bounds for W1/W2

`W1`/`W2` mean an **active** write capability - ECCO can and does write
this today. Task 005A's validator accepted a free-text `bounds_note` as
satisfying the "this capability has a documented range" requirement
for any write-candidate class, which was too permissive for W1/W2: a
prose note is not something a transaction can actually check a
requested value against before writing. Task 005B tightens this so
`W1`/`W2` require a genuinely machine-checkable bound - one of
`safe_min`/`safe_max` (numeric), `enum_mapping`, `limits.hardware.value`
(numeric), or `field_bounds`. `bounds_note` alone no longer satisfies
W1/W2 (see scenario [25b]).

`bounds_note` remains valid - and is the *right* answer, not a
shortcut - for `W3`, `WX`, and plain `R0` documentation, where the
class itself already keeps the capability non-actionable and an honest
"not yet established" is preferable to inventing a number.

`field_bounds` exists for capabilities where a single `safe_min`/
`safe_max` pair does not make sense - `rtc_clock` (`W2`) is the
concrete example: it writes a packed date/time across three registers,
so its machine-checkable bound is one `{field, min, max}` entry per
packed sub-field (year offset, month, day, hour, minute, second)
rather than one scalar range.

### W3 read/write proof consistency

A `W3` record's `current_access` normally stays `read_only` (see "Write
policies" below) - that is the entire point of the class. If a future
edit ever sets a `W3` record's `current_access` to `read_write`
(meaning: a write path for a known high-impact capability has actually
been built), the validator requires `live_proof_status:
live_proven_write` specifically - `unknown`,
`repository_inferred_read_only`, `inferred_do_not_write`, and even
`live_proven_read` are all rejected (Task 005B section 6; see scenario
[38]). This keeps a battery-voltage-class control from becoming
actionable merely because someone edits two fields in YAML without the
write actually having been built, exercised, and verified on real
hardware. The current nine `W3` battery records are all pinned
`read_only` in the offline test suite (scenario [39]) specifically so
an accidental flip is caught immediately.

### Two-axis write model: `write_policy` vs `current_access`

Schema v1 conflated "how safe would this be to write" with "can ECCO
write this today," which made `W3` (a known high-impact candidate,
deliberately disabled pending proof) unusable for values that are
currently read-only simply because no write path exists yet - a W3
battery-voltage candidate had to be misclassified as `R0`, discarding
the "high-impact if ever written" distinction (Task 005A review
finding). Schema v2 splits these into two independent fields:

- **`current_access`**: what ECCO can literally do with this register
  *today* - `read_only`, `read_write`, or `write_only`.
- **`write_policy`**: the *safety classification* - see Write policies
  below. A `W3` record commonly has `current_access: read_only` (no
  write path exists) and stays that way until a write path is
  separately designed and proven; only then would `current_access`
  become `read_write`.

`tools/validate_capability_registry.py` enforces the required
relationships between the two fields (R0 must be read_only, WX must
never be read_write, W1/W2 must be read_write since those classes
imply an existing/intended write path, W3 may legitimately be either).

### Structured limits

Where the hardware/site/effective three-tier ceiling model
(`docs/SAFE_WRITE_TRANSACTION_ARCHITECTURE.md`) genuinely applies to a
capability (currently: `grid_charge_current`, all six
`tou_slot_N_power` records, and `free_power_transaction`), `limits` is
a structured mapping rather than free text buried in `hardware_limit`/
`ecco_operating_limit` strings (which the schema v1 validator could not
actually check numerically):

```yaml
limits:
  hardware:
    value: 8000          # numeric, or omit if not statically known
    unit: W
    source: "firmware_substitution (${ecco_inverter_tou_power_ceiling_w}, compile-time)"
  operating:
    value: <numeric, if statically fixed>
    source_entity: input_number.ecco_max_grid_charge_power   # if dynamic, an HA entity supplies it
  effective:
    rule: "min(hardware, operating)" | "hardware_only" | "operating_only" | "not_applicable"
```

The validator enforces, statically: `operating.value <=
hardware.value` when both are numeric; that `effective.rule` is one of
the four allowed values; and that a `min(hardware, operating)` rule
references two tiers that each record at least a value or a source -
it never claims to know what a dynamic entity's *live* value is
(`tools/validate_capability_registry.py` is a static file validator,
not a Home Assistant client). Records without the three-tier model
applying keep using plain `safe_min`/`safe_max`/`bounds_note`.

**`limits.hardware.value` must be an independently-verified physical
ceiling, not an observed operating value.** Task 005B corrected
`grid_charge_current`: its schema-v2-authoring pass had recorded
`limits.hardware.value: 185` (amps), sourced from CURRENT_STATE.md as
"observed live... not independently confirmed as an absolute inverter
maximum, only as the value proven not to be exceeded." That is a real
and important proven fact, but it is a **transaction-scoped snapshot
cap** (Free Power never writes higher than whatever register 230
already held when the transaction began), not a verified hardware
ceiling - conflating the two mislabels an observation as a fact this
registry does not actually have. `grid_charge_current` now represents
this correctly:

```yaml
limits:
  hardware:
    source: "ABSOLUTE HARDWARE MAXIMUM NOT ESTABLISHED - ..."   # no numeric value
  operating:
    note: "derived at runtime from requested watts / live battery voltage..."
  effective:
    rule: not_applicable
transaction_limit:
  rule: min(requested_current, pre_transaction_snapshot)
  pre_transaction_snapshot_observed:
    value: 185
    unit: A
    source: "CURRENT_STATE.md - the register 230 value observed live immediately before a transaction began..."
```

`transaction_limit` is the schema's way of representing "the write
this transaction will perform is capped by something observed at
transaction time" as distinct from `limits`, which represents a
genuinely static (or entity-sourced) ceiling. Contrast with
`free_power_transaction`'s and every `tou_slot_N_power` record's
`limits.hardware.value: 8000` - that one really is the proven,
compile-time-fixed `${ecco_inverter_tou_power_ceiling_w}` firmware
ceiling, not an observation, and correctly stays under `limits`.

### Structured dependencies

Schema v1's `dependencies` was a free-text list mixing capability
references, HA entities, and interlock-flag names in one ambiguous
field. Schema v2 splits it into `dependencies.capabilities` (validated
to exist in this registry; self-reference rejected unless
`allow_self_dependency: true`), `dependencies.entities` (format-checked
HA entity ids), and `dependencies.flags` (free-text interlock/state
names that are not registry capabilities, e.g.
`manual_write_in_progress`).

### Grouped records

Grouping is now reserved for capabilities that are **genuinely
inseparable derived/meta values or a single multi-word bitmask by
firmware design** - not for "many registers that happen to be similar"
(the schema v1 grouping of slots 2-6's writable TOU fields, battery
charge-curve values, PV strings, grid protection thresholds, and energy
counters into single records was reviewed and found to hide distinct
writeable-candidate/differently-addressed values; all were exploded
into one record per independently-addressable value in schema v2 -
this is why the registry grew from 35 to 158 records).

The grouped records that remain, and why each still qualifies:

- `esphome_diagnostic_counters_group` - ESPHome-internal C++ counters
  and WiFi RSSI, not Modbus registers at all; there is no per-register
  concept to explode.
- `inverter_warning_flags` / `inverter_fault_flags` - genuinely single
  multi-word bitmasks formatted as one hex string by firmware design;
  individual bit meanings were not independently traced in this audit
  pass (an open question, not a grouping shortcut).
- The three `system_bits_register_280`-family sub-fields
  (`generator_peak_shaving_enabled`, `grid_peak_shaving_enabled`,
  `on_grid_always_on_enabled`) are individually exploded (they are
  independently meaningful booleans), but correctly declare mutual
  `shared_with` on their common register 280 rather than being grouped
  into one record.

## Full write surface (confirmed by exhaustive audit)

Every `modbus_client.write_multiple_registers` call in
`firmware/ecco_clock_dongle_stage3_4_free_power.yaml` was located by
grepping every `start_address:` in the file (Task 005A audit), and is
now re-derived mechanically on every run of
`tools/analyze_write_surface.py`. The complete, exhaustive set of
registers this firmware ever writes is:

- **22-24** - RTC (`rtc_clock`), written by `write_inverter_rtc`
- **230, 232** - grid charge current and the grid-charge enable bit,
  written by `start_free_power_override` / `restore_free_power_snapshot`
  (register 232's bit 0 is also written by all six TOU slot writers)
- **244** - Load/Export Mode (`grid_export_policy`), written by
  `apply_reg244_settings` / `restore_reg244_snapshot`. **Added
  2026-09-21** by PR #12; live-hardware-proven, see
  `docs/stage3_3-six-slot-hardware-test.md`.
- **250-261, 268-279** - all six TOU slots' start/end/power/soc/
  source/mode fields, written by `apply_manual_slot1`-`6` and (for
  268-279) by both Free Power paths

**Nothing else in this firmware is ever written** - not battery
charge-curve config (201-204, 210-211), not battery protection SOC
(217-219), not generator/AUX/smart-load config (223-227, 235-243), not
the dedicated Export Limit (245), not export-solar/TOU-enable flags
(247-248), not grid protection thresholds (287-290), not register 330.
Every capability record in this registry whose `current_access` is
`read_only` for one of these register ranges cites this audit directly
rather than re-deriving it per record - if a future firmware version
adds a new write call, this claim (and every `R0`/`W3` classification
that depends on it) must be re-audited, not assumed to still hold.

This claim is no longer maintained by hand alone.
`registry/tests/test_write_surface_invariants.py` pins the exact set
above against the firmware source, so a firmware change that widens the
write surface fails an offline test rather than silently invalidating
this section - which is precisely what happened between 2026-09-20 and
2026-09-21, when register 244 gained a write path and this section
continued to assert that 235-245 was never written.

## Evidence / proof levels

Used for `live_proof_status`. Ordered loosely from least to most
trusted, though `unknown` is not "worse" than the others - it is the
**correct** answer when the evidence genuinely does not support more:

| Value | Means |
|---|---|
| `unknown` | Insufficient evidence to say anything stronger. **Valid and preferable to guessing.** |
| `repository_inferred_read_only` | Firmware/HA code clearly reads this and nothing in the repository writes it - inferred read-only from the absence of a write call, not from a positive "this is read-only" statement anywhere. |
| `inferred_do_not_write` | There is a write mechanism in the register's *neighbourhood* (e.g. it is inside a block that has other written registers) but no direct evidence this specific register/field is safe or intended to be written. Treat as non-writable. |
| `documented_not_live_proven` | A design document (this repository's own docs, or an external source) describes the register/behaviour, but no commit/log/test in this repository shows it was ever exercised against real hardware. |
| `live_proven_read` | A read of this value against real hardware is documented as having happened (CURRENT_STATE.md, CHANGELOG.md, or equivalent) or is part of the currently-deployed, hardware-verified firmware (VERSION.yaml `hardware_verified: true`). |
| `live_proven_write` | A write to this register, including its full verify/restore cycle where applicable, is documented as having been exercised against real hardware. |

**An inference is never promoted to a documented fact.** Every TOU
slot 2-6 register offset in this registry (schema v2 exploded these
into individual records - see "Grouped records" above) was directly
re-confirmed against firmware source during the Task 005A audit pass
(write-address greps and the exact `manual_cfg_regNNN_raw` cache
assignments), not assumed from the slot-1 pattern - see
`tou_slot_2_start_time`'s `firmware_evidence` for a concrete example of
a citation that points at the actual write call rather than an
assumed offset. Where a value genuinely could not be re-confirmed this
way, the record says so in `notes` (e.g. `register_330_reserved_bits`
is left `WX`/`unknown` rather than guessed).

## Write policies

`write_policy` is the safety classification axis (see "Two-axis write
model" above for how it relates to `current_access`):

| Policy | Meaning | Typical `current_access` |
|---|---|---|
| **R0** | No ECCO write is intended or considered. | `read_only` (enforced) |
| **W1** | Known low-risk/simple manual write: known register, bounded value, single-setting transaction, exact/tolerance reread verification possible. | `read_write` (enforced - W1 implies a write path exists) |
| **W2** | Coordinated/snapshot write: multiple settings/registers and/or a mandatory snapshot/restore sequence. | `read_write` (enforced) |
| **W3** | Known high-impact configuration candidate, *disabled unless/until an explicit write path is separately proven* - battery charge-curve, battery protection SOC thresholds, and grid-protection-threshold registers are the concrete examples in this registry. | `read_only` today (no write path exists yet) - may legitimately become `read_write` later without changing the meaning of the class |
| **WX** | Unknown, inferred, insufficient evidence, or prohibited from writing. | never `read_write` (enforced) |

**Default is WX or R0 - never automatically writable.** A capability may
only be classified W1/W2/W3 when there is clear register/semantics/range
evidence, and every W1/W2/W3 record must carry a `write_policy_reason`
explaining the classification. `tools/validate_capability_registry.py`
enforces all of this mechanically (see its own doc section below),
including the `current_access` relationships in the table above.

None of R0/W1/W2/W3/WX implies anything is *currently* writable through
any UI or automation ECCO ships today, except the capabilities
(`rtc_clock`, and everything under `free_power_transaction` /
`grid_charge_current` / the TOU slot fields, all `current_access:
read_write`) that are the pre-existing, already-live-proven write paths
this task explicitly was told to audit, not to newly enable. Every W3
record in this registry is `current_access: read_only` today - W3 is
explicitly the class that stays non-actionable by design.

## Capability lifecycle

```
unknown
  -> documented (a design doc or external source describes it, not yet checked against this repo's code)
  -> live-proven read (repository_inferred_read_only or better, confirmed against real hardware)
  -> write candidate (W1/W2/W3 assigned, with write_policy_reason, but current_access still read_only / live_proof_status still documented_not_live_proven for the WRITE specifically)
  -> live-proven write (current_access becomes read_write; the write, including verify and restore/rollback, has actually been exercised on hardware)
```

A capability can regress backward in this list (e.g. a live-proven read
that turns out to have been misinterpreted goes back to `unknown` for
that specific claim) but this registry never silently advances a
capability past a stage it has not actually reached - see the explicit
`IMPLEMENTED / DESIGNED / LIVE-PROVEN / NOT PROVEN / PROHIBITED` wording
convention used throughout every Task 005 document.

## Adding a new register / proving a read / proving a future write

1. **Adding**: find the register in firmware (or a cited external
   source), add a record with a structured `modbus.registers` entry,
   `live_proof_status: documented_not_live_proven` or weaker,
   `write_policy: WX` and `current_access: read_only` unless there is a
   firmware write call already proven, run
   `tools/validate_capability_registry.py`.
2. **Proving a read**: confirm the value against a live installation
   (matches the firmware's decoded value, sane range, stable across a
   poll cycle where expected), then update `live_proof_status` to
   `live_proven_read` and cite the evidence (log line, dashboard
   screenshot reference, CURRENT_STATE.md entry) in `firmware_evidence`
   or `notes`.
3. **Proving a future write**: never done casually. Requires, in order:
   register/datatype/range confirmed from firmware or a trustworthy
   external source; a `write_policy` assigned with a real
   `write_policy_reason` (a currently-read-only high-impact candidate
   should be `W3`, not silently left `R0` - see "Two-axis write
   model"); a transaction built on
   `docs/SAFE_WRITE_TRANSACTION_ARCHITECTURE.md`'s lifecycle
   (snapshot -> stage -> arm -> write -> reread -> verify -> disarm);
   the write exercised on real hardware with the human operator present
   and a working restore path; only then does `current_access` become
   `read_write` and `live_proof_status` become `live_proven_write`.
   This task does not perform step 3 for anything beyond what was
   already proven before this task started.

## Related documents

- [docs/dev/register-provenance.md](dev/register-provenance.md) - where the register meanings come from and how far they are
  verified.
- [SAFETY.md](../SAFETY.md) - the write surface and the safety model in plain language.
- [docs/SYSTEM_HEALTH_ARCHITECTURE.md](SYSTEM_HEALTH_ARCHITECTURE.md) - the health checks that read many of these registers.
