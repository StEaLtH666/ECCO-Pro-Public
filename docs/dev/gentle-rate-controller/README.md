# Guarded charge-rate controller (GRC): offline design, reference model and firmware core

**What it is.** The missing actuator for genuinely adaptive grid charging: a firmware lease that changes the grid-charge
power **during** the cheap window, in bounded, rounded, dwell-limited, read-back steps with an exact restore, so the
battery reaches the target SOC about an hour before the window ends at the gentlest rate that still makes it. Built on
the Dump to Grid V1.1 pattern (save before write, ownership read, readback, write budget, common restore path) and the
pure-core precedent (a firmware core proven against an executable reference model).

**Status: offline only.** Nothing here is wired into the firmware YAML or Home Assistant, nothing is flashed or
installed, no live proof exists. Intelligence stays SHADOW. Specification revision 2 answers an independent review
(one BLOCKER, five MAJOR; SPEC section 15).

## The decision (SPEC section 1)

Shape **one register**: the power of the active grid-charge slot (`256 + slot - 1`), under the GRC's own lease, and
nothing else (not register 230, not the slot times, targets or flags, not the other five slots). It never writes above
the value the slot held before the lease, never below 500 W, always on the 100 W grid. A slot power is also that slot's
discharge ceiling, so a lowered value may cap the battery off grid (NOT ESTABLISHED): a lost grid ends the lease at
once. A Free Power-style re-staged lease was rejected (about twenty registers per change, amps at a drifting voltage,
and a second writer would block Free Power's own restore classifier); so were register 230 alone, a stepped multi-slot
profile, and pacing by the slot target. The **setpoint unit is not established**, so the core never assumes one: the
plan asks for a realised battery power, each change is a relative step `v * wanted / realised` measured after a 45 s
settle, the measured ratio must stay within 50-150 %, and a weak or wrong-way response ends the lease.

## The specification in brief (SPEC.md)

- Authority: START with a one-shot write enable (owner per night, or an owner-armed schedule); one lease per night;
  END at any time; in FAULT the owner's ACK or Restore original. Home Assistant only hands over a plan; the firmware
  decides every write and checks the plan against its own bounds (the window end against the slot's own end, a
  capacity floor, a 95 % maximum knee, the owner ceiling one step per change).
- States IDLE, ARMED, LEASED, ADJUSTING, SETTLING, RESTORING, FAULT. 22 START refusals (clock-change night, RTC
  correction, another lease or write, no grid, stale telemetry or plan, SOC unknown, inverter or BMS fault, slot or
  window mismatch, no running charge, the target already at risk, the write budget, ...).
- Change policy: dwell 30 min, at most 6 changes a lease, 9 writes a night with 3 restores always reserved, 100 W
  grid, 500 W floor, ceiling `min(original, 8000)`, 2000 W per step (the owner ceiling included), 300 W hysteresis,
  600 W against the last direction.
- Every action carries a sequence number the result must echo with its kind; a late or duplicate result is stale.
- Fail-safe: any guard (grid lost, END, deadline, uptime watchdog, plan lost after 20 min = Home Assistant outage,
  stale telemetry or configuration, SOC jump, slot drift, window mismatch, other lease, fault, runaway, charge stopped,
  target reached, the target guard, a failed, unanswered, deferred or timed-out write, a bad response) ends the lease
  and restores the pre-lease value exactly. A restore the inverter does not answer costs no attempt and is retried
  until answered; none is emitted before the inverter answers (at a boot: since that boot). A clamped readback under
  the GRC's own lock is owned and restored over. A foreign value, three answered restore failures, a corrupt record or
  the night ceiling latch FAULT: nothing automatic, a Home Assistant alert, Restore original, the editor never blocked.
- The target guard is the "never worse than today" rule against the slot's own end: it hands the charge back to the
  pre-lease rate as soon as finishing at that rate (pessimistic taper) would no longer leave a margin.
- Durable 32-byte record (version 2, CRC-32, fail-closed decode) committed before every write; the boot restores an open
  lease; Home Assistant keeps a copy of `original`, checks the slot after the window, and a boot without a record warns
  for every slot left below the owner's value.

## Files

| File | What |
|---|---|
| `SPEC.md` | the specification, the ordered live-proof list (section 13) and the review map (section 15) |
| `INTEGRATION_PROPOSAL.md` | what a real integration changes: YAML hooks, analyzers, authority, registry, pins, flash, the Home Assistant side (not applied) |
| `reference_model.py` | the executable decision core (pure Python, integer arithmetic) |
| `make_vectors.py`, `vectors.json` | 150 golden vectors with hand-computed expectations, plus unit vectors |
| `vector_runner.py` | vector expansion (with the result echo, silent inverter, midnight frame), the seeded fuzz generator, serialisation for the C++ harness |
| `simulator.py` | closed-loop nights against an independent truth battery (unknown gain, lag, taper, noise, 1 % SOC, Modbus outages, a clamping inverter, grid loss) and a Home Assistant planner |
| `test_reference_model.py` | the model's proof suite |
| `proposed/ecco_gentle_rate_core.h` | the firmware-ready core (C++17, `<cstddef>`/`<cstdint>` only, no ESP dependency), not included by any YAML and kept outside `firmware/` (the FB-C3 suite hashes every tracked `.h` / `.yaml` / `.md` under `firmware/`, the FB-B2 suite pins the header set of `firmware/include/`); it moves to `firmware/include/` only with the integration's scope-chain entry `grc1` |
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

## Results (25 Nov 2026, revision 2, this tree)

- Model suite: 150 vectors meet their hand-computed expectations (every revision-2 vector that changes behaviour fails
  on the revision-1 model; V152, V156 and V170 pass on both by design: an accepted edge and two coverage vectors for
  paths revision 1 had but never tested); units (classifier with the owned readback, lost-lease warning, every
  single-byte corruption and every truncation of a record rejected, `config_ok`); 300 seeded fuzz sequences with no
  property violated and all seven states reached; 80 normal nights (75 leased, **0** where today's fixed rate reaches
  the target and the GRC does not, mean lease power 0.54 of today's peak) and 29 fault nights each ending with its
  designed reason (Modbus down 2, 5 and 10 min at a guard and at a restart, a rounding and a clamping inverter and a
  grid outage all end IDLE with the slot back at its original value); **106 of 106 mutants killed**, among them the
  two the review found surviving (the restore operation timeout, the midnight wrap).
- Host suite (WSL g++, and the ESP32 cross compiler found under the user profile): the header compiles under gnu++17
  and gnu++20 with `-Wall -Wextra -Wpedantic -Werror`; the model meets every golden expectation (so CI checks them
  too); header trace equals model trace on all vectors (2479 lines), the unit vectors (68 lines) and 600 fuzz sequences
  (182816 lines); clean under address and undefined-behaviour sanitizers; **44 of 44 header mutants caught**; header
  discipline and the durable-tag inventory clean.
- Existing checks run one at a time on this tree, all exit 0: `tools/validate_repo.py`; tools `test_public_privacy`,
  `test_run_offline_tests`, `test_firmware_equivalence`; registry `test_scope_chain`, `test_tag_inventory`,
  `test_fallback_save_scope`, `test_offline_suite_exit_codes`, `test_capability_registry`; ecco_core
  `test_core_boundaries`. (Any new tracked `.h` under `firmware/` breaks the FB-C3 firmware tree pin of
  `test_failback_shadow_ha_contract`, and one in `firmware/include/` also the FB-B2 header-set pin of
  `test_fallback_save_scope`: that is why the header waits in `proposed/` here.)

## Not established (SPEC section 14)

The setpoint unit; the response below 8000 W and whether the inverter clamps or rounds a value; **the off-grid effect of
a lowered slot power** (L3a, before any armed lease); the grid-connected register during a real outage; which limit
binds a low-power charge; live BMS limits; the taper knee and tail; flash wear; the grid import limit; any live
observation of a slot power change during a charge. The simulator's truth battery is a model too: it shows the design
is safe and gentler **if** the response is monotone; only the live proofs L0-L7 can show the inverter behaves that way.
