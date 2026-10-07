# Modular architecture: the host-side foundation (`ecco_core`) and its boundaries

Status: **foundation, offline only.** Everything described here is Python that runs in tests and on a developer machine.
This foundation changes **no firmware**, no new write path exists anywhere, and
nothing in this document has been exercised on hardware. Intelligence V1.1 is described in
[`docs/intelligence/INTELLIGENCE_V1_1_FOUNDATION.md`](../intelligence/INTELLIGENCE_V1_1_FOUNDATION.md).

## 1. Why

Before this foundation, the facts a future feature needs were spread across many places with no shared definition:

- **Write authority** lived in 17 writing firmware scripts, each with its own inline gate (ownership flags, arm switch,
  durable record, read-back). No single statement said who may write what, and nothing tied the capability registry's
  `read_write` records mechanically to the firmware's actual write surface.
- **Freshness** had more than ten independent definitions: the controller's Dump-to-Grid gates (90 s / 180 s), the
  Intelligence advisor (15 min SOC, 6 h history), the System Health design registry (60 / 180 / 600 / 1200 s), the
  fallback live-match cache (180 s) and the transaction design model (30 s).
- **Register numbers** appear directly in every layer of the firmware (116 literal start addresses, register-named
  globals, inline bit masks) and in the policy headers.
- **Raw and derived values** sit side by side without a model that keeps them apart. For example, Home Assistant's
  canonical sensors turn an unexpected non-numeric state into a silent `0`.

The firmware is pinned by the proof chain and hardware-verified, so restructuring it would invalidate that evidence and
need new chain entries and new hardware proof. The foundation therefore starts on the **host side**: a small,
evidence-checked model of state, freshness, capability and authority that Intelligence, simulation and future features
can build on. The firmware stays the only authority.

## 2. The layers

```
 Controller firmware (AUTHORITATIVE, unchanged)
   transport   ESPHome modbus_client: FC03 reads (64 sites), FC16 writes (52 sites, single registers as FC16 with one
               value; no FC06). Boundary enforced by tools/analyze_write_surface.py (fails closed on any other bus access)
   features    RTC correction, manual TOU, register-244 policy, Free Power, Dump-to-Grid: each with its own gates
        |  ESPHome API -> Home Assistant entities / statistics
        v
 ecco_core (host side, offline reference model; no transport, cannot write)
   state.py       Observation / Snapshot: raw, normalised, derived kept apart; source and observation time
   freshness.py   one catalogue of limits per signal and purpose, each with its source; unresolved stays unresolved
   capability.py  capabilities from registry/inverter_capabilities.yaml only; one device profile; proof per controller
   authority.py   the write-authority table (checked against the firmware) + a pure reference decision model
   bridge.py      the one crossing into Intelligence: snapshot -> inputs, advice -> non-executable records
        |
        v
 intelligence (ADVISORY, SHADOW)
   V1 engine (unchanged output) + V1.1 advisors (explain, overnight, charge_target, events, dump_advice)
   inputs.py      Intelligence's single reading of state (imports only ecco_core.state)
```

Dependency directions are enforced by `ecco_core/tests/test_core_boundaries.py`:

- `intelligence` (every module, any depth) imports from `ecco_core` only `ecco_core.state`;
- `ecco_core.bridge` never imports `ecco_core.authority`, and no other `ecco_core` module imports the bridge or Intelligence;
- `ecco_core` has no network, serial, process, async or dynamic-execution import, no file write and no callable named
  like an actuation;
- the existing Intelligence authority-separation rules are applied recursively, so a future subpackage cannot escape them.

## 3. Transport

**Firmware.** There is no project-level transport helper. ESPHome's `modbus_client` component (pinned ESPHome
2026.8.x) does framing, CRC, UART I/O, the response timeout and the queue. Each of the 116 call sites inlines its slave
address, a literal start address and its own callbacks. The transport boundary is nevertheless formal and machine-checked:
`tools/analyze_write_surface.py` (run in CI) fails if any bus access appears outside the two modelled `modbus_client`
actions. That includes raw UART writes, `modbus_controller`, the C++ command API and any bus method other than the two
read-only query methods.

**Host side.** There is deliberately **no** transport. Python never talks to the inverter. `ecco_core.capability` can
decode register words that were already captured (simulation, diagnostics), but it cannot read or write a bus.

**Known transport gaps** (recorded, not changed here, because each needs a firmware change and hardware proof):

- The telemetry and configuration polls check the ownership flags but not the bus-quiet predicate.
- The manual "Sync Inverter Clock" button runs the clock write without the quiet-bus check that the automatic path has.
- The 31 manual-TOU write sites have no `on_response` handler.
- There are no transport-level retries; only application-level retries exist.

## 4. Device capability layer (`ecco_core/capability.py`)

Code asks for a **capability**; register addresses, data types and scales stay inside the device profile. Status comes
**only** from the capability registry's evidence:

| Status | Meaning |
|---|---|
| `supported` | every registry record it rests on exists, has the needed access, and is live-proven on the reference installation |
| `unsupported` | a record a control needs is read-only / never-write in this firmware |
| `unknown` | a record is missing, or its proof is unknown or only documented |

Nothing is inferred from a read or write that happened to succeed, and the profile has no API that could upgrade a
status. `proof_on()` reports separately on which controller variant a capability has been exercised (`SUPPORTED_HARDWARE.md`:
H-001 classic ESP32, every write feature hardware tested; H-002 ESP32-S3, write features offline only).

Current statuses (checked by `ecco_core/tests/test_core_capability.py`):

| Capability | Status | Why |
|---|---|---|
| `telemetry.battery_soc` / `battery_power` / `house_power` / `pv_power` / `grid_power` / `inverter_state` | supported | live-proven reads |
| `control.clock`, `control.tou_schedule`, `control.grid_charge`, `control.export_mode` | supported | live-proven writes |
| `control.dump_to_grid` | **unknown** | the registry record `dump_to_grid_transaction` is `documented_not_live_proven` |
| `control.export_limit` (245), `control.battery_protection` (217-219) | unsupported | read-only in this firmware |

The registry is pinned and predates Dump-to-Grid's hardware tests, so `control.dump_to_grid` stays `unknown` even though
`SUPPORTED_HARDWARE.md` records two hardware-tested scenarios. The capability layer follows the registry, the more
conservative source, until a declared chain entry updates the record.

**One profile** is described: the Deye/Sunsynk-family single-phase low-voltage layout of the reference installation.
There is no speculative third-party map. A second layout would be a second profile built from its own evidence (its own
registry records and its own proof), never an edit of this one.

## 5. State model and freshness (`ecco_core/state.py`, `ecco_core/freshness.py`)

An `Observation` carries `value` (canonical unit and sign), `raw` (exactly as the source said it), `kind`
(`raw` / `normalized` / `derived` + `derived_from`), `observed_at` (when the source observed it), `source` and `quality`
flags. Unknown signal names, wrong units, non-finite values, a string or boolean given as a measured reading (an HA state
such as `unavailable` is kept in `raw` with no value), naive times and an underived "derived" value are all refused at
construction. A derived value sits **beside** its inputs, never instead of them. Sign conventions are the repository's
existing ones: battery power positive = discharge, grid power positive = import.

Freshness depends on the **purpose**: `control_gate` (may a controller-side action rely on it), `advisory` (may a
shadow recommendation rely on it) and `health` (is the data path healthy). The catalogue collects the limits the project
already uses. `ecco_core/tests/test_core_freshness.py` reads each one back from its source, so they cannot drift:

| Signal | Purpose | Limit | Standing | Source |
|---|---|---|---|---|
| battery.soc | control_gate | 90 s | controller | firmware `ecco_dump_soc_stale_ms` |
| grid.power | control_gate | 90 s | controller | firmware `ecco_dump_grid_stale_ms` |
| inverter.config_readback | control_gate | 180 s | controller | firmware `ecco_dump_cfg_stale_ms` |
| inverter.config_readback | health | 180 s | controller | `LIVE_CACHE_MAX_AGE_MS` (fallback header and its mirror) |
| battery.soc | advisory | 900 s | intelligence | `intelligence/advisor.py` `STALE_SOC_SECONDS` |
| history.hourly | advisory | 6 h | intelligence | `intelligence/engine.py` |
| controller.telemetry | health | 180 s | design | `registry/system_health_checks.yaml` `telemetry_freshness` |
| controller.configuration | health | 600 s | design | same file, `configuration_freshness` |
| canonical.telemetry | health | 60 s | design | same file, `canonical_stale_raw_fresh` |
| battery_outlook | health | 1200 s | design | same file, `battery_outlook_freshness` (warning) |
| transaction.snapshot | control_gate | 30 s | design | `registry/transaction_state_machine.py` `Snapshot.max_age_seconds` |

Anything the project never defined is explicitly **unresolved** and therefore never fresh. That covers the inverter
status, house / PV / battery / grid power and the HA reserve for advisory use. An installation can resolve an unresolved
limit, or tighten a defined one, with a `FreshnessPolicy` override (per signal or per family such as `controller.owner.*`;
it then carries `site` standing). An override that would **loosen** a defined limit is refused, just as a run-time reserve
can only raise the reserve. Assessment fails closed: no observation, no usable value, an unknown or future observation
time, or an unresolved limit is never `fresh`.

## 6. Write authority (`ecco_core/authority.py`)

One table states every write path the firmware has. `ecco_core/tests/test_core_authority.py` checks it against the
firmware's own write surface (`tools/analyze_write_surface.py`, script by script: registers, ownership flags taken, arm
switch checked, obligation flags opened and closed), against the capability registry's `read_write` records, and
against the conflict declarations of `registry/transaction_state_machine.py`.

| Feature | Capability | Registers | Owner flags | Arm switch | Restore |
|---|---|---|---|---|---|
| clock_correction | control.clock | 22-24 | correction_in_progress | none | not applicable (the corrected clock is the end state) |
| manual_tou | control.tou_schedule | 232, 250-261, 268-279 | manual_write_in_progress | manual_config_write_enable | none: a manual apply is the operator's (SAFETY.md section 8) |
| export_mode_policy | control.export_mode | 244 | manual_write_in_progress, reg244_apply_in_progress | manual_config_write_enable | durable snapshot, verified restore |
| free_power | control.grid_charge | 230, 232, 256-261, 268-279 | free_power_operation_in_progress, manual_write_in_progress | free_power_write_enable | durable snapshot, verified restore |
| dump_to_grid | control.dump_to_grid | 244, 256-261 | dump_operation_in_progress, manual_write_in_progress | dump_write_enable | durable snapshot, verified restore |

`evaluate(intent, snapshot, profile, controller_variant=...)` is a pure **reference** decision model for review,
simulation and future write-capable features. It returns a `Decision` (`permitted`, every refusal reason, and the
obligations a permitted action would carry), and a `Decision` cannot be built as anything that executes. Its rules fail
closed:

- an advisory origin (Intelligence, a dashboard) is always refused, and so is any origin that is not a declared write path;
- the capability must be the feature's own and `supported`, and hardware-tested on the given controller variant;
- the registers must lie inside the feature's authority, the arm switch must be known on, and every ownership flag must
  be known free;
- no restore obligation of any feature may be open or unknown;
- the feature's gate readings must be fresh under the control-gate policy;
- a flag reading (arm switch, ownership, obligation) counts only if it too is fresh under that policy. The project defines
  no limit for those readings, so with the default policy they are unknown and every decision is refused until an
  installation configures one (a `FreshnessPolicy` override, which may name a family such as `controller.owner.*`).

Nothing calls `evaluate` to write. Current authority is exactly the firmware's, unchanged.

## 7. The Intelligence advisory boundary

- **State in:** `ecco_core.bridge.advisory_live_inputs` hands a snapshot to `intelligence.inputs.live_inputs_from_snapshot`.
  It gates only what the engine cannot judge. The inverter status must be fresh under the advisory policy, and its limit
  is unresolved by default, so out of the box the engine sees an unknown status and withholds export advice; an
  installation can configure a limit. The SOC passes with its age (the engine applies its own 15-minute rule), and the HA
  reserve passes whatever its age (it can only raise the reserve).
- **Advice out:** `record()` / `record_report()` produce an `AdvisoryRecord`: frozen, JSON-safe, `mode: SHADOW`,
  `applies_nothing: true`, and nothing else it can do.
- **Advice itself** (`intelligence/explain.py`) cannot express an instruction: a `BLOCKED` advice carries no number, an
  `OK` advice cannot rest on a stale or unknown required input, and construction fails unless it is SHADOW / applies nothing.

## 8. The migrated path (proof)

`intelligence.replay.inputs_from_history` (used by replays, backtests, the CLI, the shipped examples and most Intelligence
tests) now goes History -> `ecco_core` Snapshot (`intelligence.inputs.history_snapshot`) -> LiveInputs
(`live_inputs_from_snapshot`). That is the same single path a live source would use. `intelligence/tests/test_intelligence_v11_migration.py`
compares it with a verbatim copy of the old implementation:

- identical `LiveInputs`, with types and dict order, on 400 randomised synthetic cases;
- byte-identical engine reports on every shipped example scenario and three more.

The only differences are deliberate and tested. A reading that is not a finite number is dropped at the snapshot
boundary rather than in the engine: for NaN or infinity the advice is unchanged and only an "is ignored" note
disappears; a boolean SOC, previously read as 1 %, and a string SOC, previously a crash, now read as no SOC. The SOC's
age is now computed from exact times instead of `now` truncated to whole seconds. Two inputs the type hints already
excluded are now refused loudly: a naive `now`, which would otherwise be read in the machine's own timezone, and a
forecast source name that is not a string.

## 9. What is device-specific, and what is generic

| Device- or firmware-specific (would change for another inverter or controller) | Generic |
|---|---|
| firmware: every register number, register-named global, bit mask and policy header | `state.py`: signals, units, raw / derived model |
| `capability.py`: the capability -> registry-record mapping of this layout, `CONTROLLER_PROOF` | `freshness.py`: purposes, assessment rules (the catalogue's values are this system's) |
| `authority.py`: the script and flag names of this firmware | `authority.evaluate` rules; `Decision` |
| the freshness catalogue's controller values | `bridge.py`; Intelligence V1.1 (no register knowledge at all) |

## 10. Not implemented (on purpose)

- No firmware modularisation: the YAML stays one pinned, hardware-verified file. Splitting it into ESPHome packages
  needs declared chain entries and fresh hardware proof.
- No host-side transport and no host-side write path of any kind.
- No consumer of the V1.1 advice: no runner, no Home Assistant publication, no dashboard. The V1 engine report is unchanged.
- No second device profile and no compatibility claim for any other inverter, firmware or controller.
- Dump-to-Grid still does not use the battery reserve (`SAFETY.md` section 9). `intelligence/dump_advice.py` only computes
  what a reserve-aware stop level would be.

## 11. Extension path

- **A new inverter layout:** add a profile built from that layout's own registry records and its own proof. Do not edit
  the reference profile. Capabilities the new layout cannot evidence stay `unknown`.
- **A future write-capable feature:** declare it in the authority table, and expect `test_core_authority.py` to fail
  until the firmware actually implements it. Gate it in the firmware. Use `evaluate` for review and simulation. Never
  route Intelligence advice to it except through an operator-confirmed, interlocked action.
- **A new freshness limit:** add it to the catalogue with its source, and `test_core_freshness.py` must be able to read
  it back.
- **Showing V1.1 advice in the V1 report:** wire it into `engine.run`, then regenerate the examples with
  `intelligence/tools/make_examples.py` and the mock package.

## 12. Audit findings recorded for later (not changed in this branch)

Each needs a change to a pinned or hardware-verified file, or an owner decision:

- `home-assistant/packages/ecco_canonical_telemetry.yaml`: a non-numeric state outside the sentinel list renders as `0`
  (`float(0)`); `refreshed_at` only advances on a state change, so it measures time since the value changed, not liveness.
- System Health communications checks use the controller's online flags only. The 60 / 180 s age design in
  `registry/system_health_checks.yaml` is not implemented, and a skipped poll leaves the flag on with no timeout.
- `home-assistant/packages/ecco_dump_to_grid_schedule.yaml` bounds the export power to a hard-coded 500-8000 W, not to
  the firmware's TOU power ceiling or a site limit.
- The production dashboard's JavaScript hard-codes a 10 % reserve and ignores `input_number.ecco_minimum_reserve_soc`.
- Free Power derives the register-230 current from the battery voltage reading without an age check (range check only).
- `tools/analyze_write_surface.py`: the `OBLIGATION_FLAGS` comment says the flags are `restore_value: yes`, but the
  firmware states they are RAM-only and rebuilt from the durable record at boot.
- The same calculation is repeated in several places: SOC to energy, five sources of battery capacity, and round-trip
  versus one-way efficiency.
