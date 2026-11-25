# Guarded charge-rate controller (GRC): offline design, reference model and firmware core

**What it is.** The missing actuator for genuinely adaptive grid charging: a firmware lease that changes the grid-charge
power **during** the cheap window, in bounded, rounded, dwell-limited, read-back steps with an exact restore, so the
battery reaches the target SOC about an hour before the window ends at the gentlest rate that still makes it. Built on
the Dump to Grid V1.1 pattern (save before write, ownership read, readback, write budget, common restore path) and the
pure-core precedent (a firmware core proven against an executable reference model).

**Status: offline only.** Nothing here is wired into the firmware YAML or Home Assistant, nothing is flashed or
installed, no live proof exists. Intelligence stays SHADOW. Specification revision 3 answers the confirmation review of
revision 2 (four MAJOR and the open minors; SPEC section 16), after revision 2 answered the first review (one BLOCKER,
five MAJOR; SPEC section 15).

## The decision (SPEC section 1)

Shape **one register**: the power of the active grid-charge slot (`256 + slot - 1`, named by every action), under the
GRC's own lease, and nothing else (not register 230, not the slot times, targets or flags, not the other five slots).
It never writes above the value the slot held before the lease, never below 500 W, always on the 100 W grid, never more
than 2000 W from the present value. A slot power is also that slot's discharge ceiling, so a lowered value may cap the
battery off grid (NOT ESTABLISHED): a lost grid ends the lease at once, and the off-grid effect is the first live proof.
The **setpoint unit is not established**, so the core never assumes one: the plan asks for a realised battery power,
each change is a relative step `v * wanted / realised` measured after a 45 s settle, the measured ratio must stay within
50-150 %, and a weak or wrong-way response ends the lease.

**Candidate C0** (one evening write of a planned fixed slot power through the existing editor, the morning write back)
is kept as the baseline and the safer non-adaptive start: it needs no new firmware, and the simulator finds it nearly
as gentle as the GRC on normal nights. **The GRC's measured added value over C0 is robustness, not gentleness** (REPORT
below).

## The specification in brief (SPEC.md)

- Authority: START with a one-shot write enable (owner per night, or an owner-armed schedule); one lease per night (a
  day number rolling at noon; a number going backwards refuses); END at any time; in FAULT the owner's ACK (the night's
  counts kept) or Restore original (one write of every night reserved for it). Home Assistant only hands over a plan; the
  firmware decides every write and checks the plan against its own bounds (the window end against the slot's own end, a
  mandatory site capacity floor, a 95 % maximum knee, the owner ceiling one step per change).
- States IDLE, ARMED, LEASED, ADJUSTING, SETTLING, RESTORING, FAULT. 25 START refusals (no site capacity floor,
  clock-change night, RTC correction, another lease or write, no grid, stale telemetry or plan, SOC unknown, inverter or
  BMS fault, configuration fields of another slot, slot or window mismatch, no running charge, the target already at
  risk, the night / 7-day / lifetime write ceilings, ...).
- Change policy: dwell 30 min, at most 6 changes a lease; 10 writes a night with 3 lease restores and 1 owner restore
  always reserved, 42 in any 7 nights, 4000 since the record exists (persisted, published, never refusing a restore);
  100 W grid, 500 W floor, ceiling `min(original, 8000)`, step bounds on the grid within 2000 W (the owner ceiling and
  an off-grid original included), 300 W hysteresis, 600 W against the last direction.
- Every action carries a sequence number and its slot; the result must echo the sequence and kind; a late or duplicate
  result is stale, and the late readback of the one operation abandoned at its timeout is owned, once.
- Fail-safe: any guard (grid lost, END, deadline, uptime watchdog, plan lost after 20 min, stale telemetry or
  configuration, SOC jump, slot drift, window mismatch, other lease, fault, runaway, charge stopped, target reached, the
  target guard, a failed, unanswered, deferred or timed-out write, a bad response) ends the lease and restores the
  pre-lease value exactly. A restore the inverter does not answer, or the integration cannot run, costs no attempt, but
  only 10 times a night and only for 10 min of restore-owed time while the inverter answers (a Modbus outage of any
  length counts nothing); then **FAULT RESTORE_STALLED**. A clamped readback under the GRC's own lock is owned, committed
  in that very tick (also when the bus is busy or an RTC correction runs) and restored over, also after a restart. A
  foreign value, three answered restore failures, a stalled restore, a corrupt record or the night ceiling latch FAULT:
  nothing automatic, a Home Assistant alert, Restore original, the editor never blocked.
- The target guard is the "never worse than today" rule against the slot's own end: it hands the charge back to the
  pre-lease rate as soon as finishing at that rate (pessimistic taper) would no longer leave a margin. **It needs the
  site's capacity floor at least the real usable capacity**: the floor has no usable default (the build fails without
  the site substitution and static_asserts it against the site's usable capacity).
- Durable 48-byte record (version 3, CRC-32, fail-closed decode) committed on every tick that sets `Out.commit`, before
  anything else; the boot restores an open lease; Home Assistant keeps a copy of `original`, checks the slot after the
  window, alerts on FAULT and on a restore owed for 15 min, and a boot without a record warns for every slot left below
  the owner's saved fallback-profile value.
- Every firmware writer of 256-261 (seven script families) and the fallback profile operations are gated against a GRC
  lease (SPEC section 12, INTEGRATION H7); the stuck-lock escalation restarts the device while a GRC restore is owed; the
  RTC deadline breaker bounds an RTC correction to 90 s.

## Files

| File | What |
|---|---|
| `SPEC.md` | the specification, the ordered live-proof list (section 13) and the review maps (sections 15, 16) |
| `INTEGRATION_PROPOSAL.md` | what a real integration changes: YAML hooks, the writer table, analyzers, authority, registry, pins, flash, the Home Assistant side (not applied) |
| `reference_model.py` | the executable decision core (pure Python, integer arithmetic) |
| `make_vectors.py`, `vectors.json` | 186 golden vectors with hand-computed expectations, plus unit vectors |
| `vector_runner.py` | vector expansion (with the result echo, the record committed only on `Out.commit`, silent inverter, midnight frame), the seeded fuzz generator, serialisation for the C++ harness |
| `simulator.py` | closed-loop nights against an independent truth battery (unknown gain, lag, taper, noise, 1 % SOC, Modbus outages, a clamping inverter, grid loss, restores that never run or are never answered) and a Home Assistant planner; the site's floor per night; candidate C0 |
| `test_reference_model.py` | the model's proof suite, and the REPORT of the floor sensitivity and C0 |
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

## Results (25 Nov 2026, revision 3, this tree)

- Model suite (`test_reference_model.py`, ALL PASS): 186 vectors meet their hand-computed expectations; units
  (classifier with the owned readback, lost-lease warning, every single-byte corruption and every truncation of a
  record rejected, valid-CRC records with a reserved byte or an old version rejected, `config_ok`: the default without a
  site floor rejected and every structural bound enforced from a valid configuration); 300 seeded fuzz sequences with no
  property violated and all seven states reached (the step cap without exception, the slot of every action, RESTORING
  and the free retries bounded, an owned readback committed the tick it changes, ACK never lowering the night's counts,
  the commits of a night within the bound, the night / 7-day / lifetime ceilings); closed loop: 80 normal nights (75
  leased, **0** where today's fixed rate reaches the target and the GRC does not, mean lease power 0.54 of today's peak),
  **0 worse** in each never-worse family of 40 nights (plans understating the capacity down to 3 %, the review's bad
  plan of 1 kWh with taper 100, taper 100, a plan of 0 W) and in 40 stress nights (lower gain, understated plan), and 36
  fault nights each ending with its designed reason (Modbus down 2 to 60 min at a guard and at a restart, rounding and
  clamping inverters, a grid outage, a restore always deferred or never answered: FAULT RESTORE_STALLED after 10 restore emissions,
  an exception on every fresh read: FAULT RESTORE_FAILED, a clamp whose result tick has the bus busy then a restart and a
  restore readback of 7500 W then a restart: both restored exactly, an RTC correction that never ends: FAULT
  RESTORE_STALLED); **166 of 166 mutants killed**, among them the confirmation reviewer's 22 (the 10 that survived
  revision 2's suites included).
- Host suite (`test_gentle_rate_core_host.py`, ALL PASS; WSL g++ and the ESP32 cross compiler found under the user
  profile): the header compiles under gnu++17 and gnu++20 with `-Wall -Wextra -Wpedantic -Werror` (its
  `static_assert(!config_ok(Config{}))` holds); the model meets every golden expectation; header trace equals model
  trace (with the record on flash modelled as committed) on all vectors (4238 lines), the unit vectors (98 lines) and
  600 fuzz sequences (182727 lines); clean under address and undefined-behaviour sanitizers; **87 of 87 header mutants
  caught**; header discipline and the durable-tag inventory clean.
- The confirmation reviewer's own probes, re-run on copies in a scratch folder: S3 / S3b / S8 / S12 (a clamped or
  differing readback, a busy result tick, a restart) now end with the exact original restored, never FAULT FOREIGN; S4
  (DEFERRED or NO_ANSWER for 24 h) ends in FAULT RESTORE_STALLED after 10 restore emissions and about 20 commits instead
  of 2160 emissions and 4300 commits, S5 (an RTC correction for 24 h) in FAULT RESTORE_STALLED after 10 min; S6 steps 1949 W from 6949 W; S7's Restore original works the same
  night; S9 (25 days silent) restores 1 s after the inverter answers; Z1 is refused (no division); Z2's second lease
  is refused; their edge-heavy differential fuzz (300 sequences, 121464 lines, ASan and UBSan, all seven states): header
  equal to model. Their bad-plan nights (400 each) give 0 worse with the site floor at the real capacity; with the
  revision 2 default of 20 kWh the same nights give their numbers again (118, 296, 0, 160), so the change is the floor.

### REPORT (numbers, not pass/fail: `test_reference_model.py` prints them)

- **The floor below the real battery** (the review's bad plan, 100 nights each, 26-34 kWh): 0 worse at 0.85 and 0.80
  of the real capacity, 1 at 0.75, 3 at 0.70, 15 at 0.65, 32 at 0.60; the revision 2 default of 20 kWh: 18 of 100 (2 of
  100 for merely understated plans). The statement is therefore: **never worse than today in every simulated family
  when the site's floor is at least the real usable capacity; still none down to 0.8 of it; increasingly worse below.**
  Whether the real battery's usable capacity is above its nameplate is NOT ESTABLISHED; the floor should carry the 6 %
  band.
- **Candidate C0 against the GRC** (100 nights each; mean battery power while charging, as a share of today's): on the
  normal nights C0 with an SOC estimate error of up to 5 % is never worse than today and charges at 0.64 (no margin),
  0.69 (10 % margin) or 0.76 (25 % margin) of today's power; **the GRC charges at 0.61: its gentleness gain over C0 is
  small (about 5 % against C0 without a margin)**. On stress nights (a gain of 0.75-0.95, a plan capacity understated by
  up to 15 %, an SOC estimate error of up to 10 %) C0 misses a target that today's rate reaches on 25 (no margin), 12
  (10 %) or 4 (25 %) of 100 nights; the GRC on 0 of 100, at 0.68. **The GRC's added value is robustness (measured
  feedback and the target guard), not a gentler charge.** This is a finding: if the live proofs show the planner's
  inputs are good, C0 through the existing editor may be all that is needed.

## Established, not established, and what the next review must look at

**Established (offline, by the suites above):** the header equals the model on every vector, unit and fuzz sequence,
under sanitizers; every write is bounded (floor, grid, original, owner ceiling, one 2000 W step, no exception), never
emitted on a busy bus, a lost grid or a silent inverter; RESTORING is bounded without spending an answered attempt and
every path that can keep a lowered value ends in an alerted FAULT with the editor free; an owned readback survives any
restart; a Modbus outage of any length restores without a fault; the night, 7-day and lifetime write ceilings and the
commit bound hold in the fuzz; the target guard keeps the simulated nights never worse than today with the site's floor
at least the real capacity; the CI layout defect (a tracked `.h` under `firmware/`) is gone.

**Not established (SPEC section 14):** anything about the real inverter and battery: the setpoint unit, the response
below 8000 W, clamping or rounding, **the off-grid effect of a lowered slot power (L1, the first step)**, the
grid-connected register in a real outage, which limit binds a low-power charge, the BMS limits, the taper knee and
tail, the real usable capacity and its band, flash wear (so every write ceiling is a guess), the grid import limit, a
mid-charge slot change. The truth battery is a model too: it shows the design is safe and robust **if** the response is
monotone; only the live proofs L0-L8 can show the inverter behaves that way. The integration (INTEGRATION_PROPOSAL.md)
is not written; nothing proves the YAML will deliver the input contract (fresh `cfg_slot` fields, `mutex_busy`, the
NO_ANSWER / FAIL split, the commit before anything else).

**The next independent review should look at:** (1) whether the RESTORING bound (10 free retries, 10 min answered,
30 s per tick) and its FAULT are the right trade against an outage that comes and goes (an inverter answering in short
bursts spends free retries); (2) the corrupt-record policy (the boot's night used and the 7-day window taken as full,
the lifetime count restarting); (3) the late-readback rule (only the one abandoned operation, once) against an
integration that could deliver results out of order; (4) the commit bound of 65 a night against the NVS wear budget;
(5) the reordered ladder, in particular L1's procedure and whether L2/L3 need the HA grid-loss automation; (6) the
writer table of SPEC section 12 against the firmware source, and the fallback profile gate; (7) whether C0 should be
the first deliverable and the GRC kept for later, given the REPORT.
