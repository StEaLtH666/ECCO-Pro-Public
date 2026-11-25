# Guarded charge-rate controller (GRC): offline design, reference model and firmware core

**What it is.** The missing actuator for genuinely adaptive grid charging: a firmware lease that changes the grid-charge
power **during** the cheap window, in bounded, rounded, dwell-limited, read-back steps with an exact restore, so the
battery reaches the target SOC about an hour before the window ends at the gentlest rate that still makes it. Built on
the Dump to Grid V1.1 pattern (save before write, ownership read, readback, write budget, common restore path) and the
grid-loss interlock precedent (a pure firmware core proven against an executable reference model).

**Status: offline only.** Nothing here is wired into the firmware YAML or Home Assistant, nothing is flashed or
installed, no live proof exists. Intelligence stays SHADOW.

## The decision (SPEC section 1)

Shape **one register**: the power of the active grid-charge slot (`256 + slot - 1`), under the GRC's own lease, and
nothing else (not register 230, not the slot times, targets or flags, not the other five slots). It is **subtractive**:
never above the value the slot held before the lease, never below 500 W, always on the 100 W grid; every failure
returns exactly the pre-lease value, which is today's behaviour. A Free Power-style re-staged lease was rejected (about
twenty registers per change, amps at a drifting voltage, and a second writer would block Free Power's own restore
classifier); so were register 230 alone, a stepped multi-slot profile, and pacing by the slot target. The **setpoint
unit is not established**, so the core never assumes one: the plan asks for a realised battery power, each change is a
relative step `v * wanted / realised` measured after a 45 s settle, the measured ratio must stay within 50-150 %, and a
weak or wrong-way response ends the lease.

## The specification in brief (SPEC.md)

- Authority: START with a one-shot write enable (owner per night, or an owner-armed schedule); one lease per night;
  END at any time. Home Assistant only hands over a plan; the firmware decides every write.
- States IDLE, ARMED, LEASED, ADJUSTING, SETTLING, RESTORING, FAULT. 21 START refusals (clock-change night, RTC
  correction, another lease or write, stale telemetry or plan, SOC unknown, inverter or BMS fault, slot mismatch, no
  running charge, the target already at risk, the write budget, ...).
- Change policy: dwell 30 min, at most 6 changes a lease, 9 writes a night with 3 restores always reserved, 100 W
  grid, 500 W floor, ceiling `min(original, owner limit, 8000)`, 2000 W per step, 300 W hysteresis, 600 W against the
  last direction.
- Fail-safe: any guard (END, deadline, uptime watchdog, plan lost after 20 min = Home Assistant outage, stale
  telemetry or configuration, SOC jump, slot drift, other lease, fault, runaway, charge stopped, target reached, the
  target guard, a failed or timed-out write, a bad response) ends the lease and restores the pre-lease value exactly;
  a foreign value or three failed restores latch FAULT with nothing written until the owner accepts the current state.
- The target guard is the "never worse than today" rule: it hands the charge back to the pre-lease rate as soon as
  finishing at that rate (pessimistic taper) would no longer leave a margin before the window end.
- Durable 28-byte record (CRC-32, fail-closed decode) committed before every write; the boot restores an open lease.

## Files

| File | What |
|---|---|
| `SPEC.md` | the specification and the ordered live-proof list (section 13) |
| `INTEGRATION_PROPOSAL.md` | what a real integration changes: YAML hooks, analyzers, authority, registry, pins, flash, the Home Assistant side (not applied) |
| `reference_model.py` | the executable decision core (pure Python, integer arithmetic) |
| `make_vectors.py`, `vectors.json` | 112 golden vectors with hand-computed expectations, plus unit vectors |
| `vector_runner.py` | vector expansion, the seeded fuzz generator, serialisation for the C++ harness |
| `simulator.py` | closed-loop nights against an independent truth battery (unknown gain, lag, taper, noise, 1 % SOC) and a Home Assistant planner |
| `test_reference_model.py` | the model's proof suite |
| `../../../firmware/proposed/ecco_gentle_rate_core.h` | the firmware-ready core (C++17, `<cstddef>`/`<cstdint>` only, no ESP dependency), not included by any YAML; it moves to `firmware/include/` only with the integration's scope-chain entry (the FB-B2 suite pins that directory) |
| `../../../registry/tests/test_gentle_rate_core_host.py`, `gentle_rate_harness.cpp` | the host C++ proof that the header equals the model |

## Running the proofs

```powershell
cls
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -I -B -X utf8 docs\dev\gentle-rate-controller\test_reference_model.py
& $py -I -B -X utf8 registry\tests\test_gentle_rate_core_host.py
```

The host suite needs a g++ that can run executables (`ECCO_CXX`, g++ on PATH, or the WSL Ubuntu-24.04 g++); it fails,
never skips, without one. `make_vectors.py` regenerates `vectors.json`; the model suite fails if the two differ.

## Results (25 Nov 2026, this tree)

- Model suite: 112 vectors meet their hand-computed expectations; units (classifier, every single-byte corruption and
  every truncation of a record rejected, `config_ok`); 300 seeded fuzz sequences with no property violated and all
  seven states reached; 80 normal nights (75 leased, **0** where today's fixed rate reaches the target and the GRC
  does not, mean lease power 0.54 of today's peak) and 20 fault nights each ending with its designed reason;
  **66 of 66 mutants killed**.
- Host suite (WSL g++ 13.3, and the ESP32 cross compiler found under the user profile): the header compiles under
  gnu++17 and gnu++20 with `-Wall -Wextra -Wpedantic -Werror`; the model meets every golden expectation (so CI checks
  them too); header trace equals model trace on all vectors (1501 lines), the unit vectors and 600 fuzz sequences
  (182713 lines); clean under address and undefined-behaviour sanitizers; 20 of 20 header mutants caught; header
  discipline and the durable-tag inventory clean.
- Existing checks run one at a time on this tree, all exit 0: `tools/validate_repo.py`; registry
  `test_offline_suite_exit_codes`, `test_fallback_save_scope`, `test_fallback_durable_model`, `test_tag_inventory`,
  `test_fallback_nvs_keyhash`, `test_fallback_profile_capture`, `test_fallback_live_match`,
  `test_fallback_profile_schema`, `test_fallback_save_static_pins`, `test_scope_chain`, `test_esp32s3_variant`,
  `test_dump_to_grid_ceiling`, `test_capability_registry`, `test_pex_transition`, `test_pub0_transition`; tools
  `test_public_privacy`, `test_firmware_equivalence`, `test_run_offline_tests`; ecco_core `test_core_boundaries`,
  `test_core_authority`. (With the header in `firmware/include/`, `test_fallback_save_scope` fails its header-set
  pin; that is why it waits in `firmware/proposed/`.)

## Not established (SPEC section 14)

The setpoint unit; the response below 8000 W; which limit binds a low-power charge; live BMS limits; the taper knee and
tail; flash wear; the grid import limit; any live observation of a slot power change during a charge. The simulator's
truth battery is a model too: it shows the design is safe and gentler **if** the response is monotone; only the live
proofs L0-L7 can show the inverter behaves that way.
