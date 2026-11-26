# Dynamic energy control: the offline kernel, plant simulator and replay bench (N4)

Status: **reference model and test bench, offline, 26 Nov 2026. NOT PRODUCTION CODE.** Nothing in this folder is wired to Home Assistant,
the dongle, the inverter or any register; it imports only the Python standard library, reads no file and contacts nothing (the self-check
proves the imports and the absence of file and process calls by parsing the sources); it writes nothing but its own table on standard
output. Intelligence stays SHADOW. No firmware is flashed, no setpoint is changed, no closed-loop actuation is enabled by anything here:
those remain separate approvals (owner messages A, B and C of 25 Nov 2026).

Why it exists: the architecture reconciliation (item N4, layer L3) needs ONE shared kernel (freshness, progress, feasibility, ramp,
hysteresis, explanation) with thin policies (Charge Fixed, Gentle, Export), and a PLANT SIMULATOR and replay, so that every later
controller (the export coordinator, the Gentle lease, anything in Geek Mode) is tested against the same adversarial scenarios BEFORE any
live use. The consequence of the owner's rule "one controller owns the setpoint" is that the three policies share one kernel and one set
of invariants; the lease engine of the dongle is modelled once, in the bench.

**The simulator is not the inverter.** It proves a kernel against its own model and the bench's invariants. Section "What this does not
prove" says what that leaves open.

## Files

| File | What it is |
|---|---|
| [kernel.py](kernel.py) | the shared kernel: pure functions only (freshness, time trust, the pessimistic battery world and the feasibility maths ported from the Gentle planner, the guard order, ramp limiting and hysteresis inside the real budgets, the Dump loop law, the three policies, one explanation sentence per decision) |
| [plant.py](plant.py) | the discrete-time plant: battery, charge plateau / cliff / trickle, discharge, house, solar, grid, the unmeasured parameters as parameters (the setpoint unit among them); the parameter table below is generated from it. Command delay and loss, telemetry gaps, restart, dead dongle, outage and untrusted time are in the bench, because they belong to the channels and the two hosts, not to the physics |
| [bench.py](bench.py) | the closed-loop bench: telemetry and command channels (delay, loss, gaps, staleness), a MODEL of the dongle lease engine (one owner, snapshot, readback, 15 s guards, restore, restart, dead dongle) and of the Home Assistant planner host (plan ticks, outage) around the plant and ONE kernel module |
| [scenarios.py](scenarios.py) | the named scenarios, the invariants, the expectations, the property-sweep generator, the generated scenario table |
| [run_sim.py](run_sim.py) | runs every scenario and prints one table row each; exit status 1 on any failure |
| [test_sim.py](test_sim.py) | the self-check: statements and static shape, pins, unit tables, closed lists, scenarios, plant replay, README tables, seeded property sweep, in-memory mutants of the kernel |

Run (Python 3.12, standard library only; no Node, no network):

```powershell
cls
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\sim\run_sim.py          # the table; add -v for invariants and explanations, a name for one scenario
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\sim\test_sim.py         # the self-check (about 30 seconds)
```

**Where it lives, and why.** `docs/dev/dynamic-energy-control/sim/`, next to `evidence_replay.py` (the precedent): no registry test, pin
chain, manifest or privacy scan reads a Python file under `docs/` as a pinned artifact, so nothing existing had to change (the only edit
to an existing file is the "Covered by" column of [../REQUIREMENTS.md](../REQUIREMENTS.md)). The repository's checks that look at a new
Python file are: `tools/validate_repo.py` (it must parse; UTF-8, no control characters), the public privacy scan (tracked text: no private
address, e-mail address or token shape; none here, and the self-check repeats the scan), and, only under an offline test root,
`registry/tests/test_offline_suite_exit_codes.py` (the `check()` / `FAILURES` style with a non-zero exit after the last check, which
`test_sim.py` has). The folder is not an offline test root, so CI would not run it by itself; `tools/tests/test_dec_sim.py` is a
one-file hook that runs the self-check from an existing root without touching `tools/offline_test_roots.txt`. A later pull request may
list the folder as a root instead and delete the hook. No manifest or pin-chain entry is needed: those exist for deployable Home
Assistant packages and pinned firmware artifacts (the sgt1 and ttr1 precedent), and nothing here is deployable; one CHANGELOG bullet
records the addition.

## What it models

```
L4 objectives  ->  L3 KERNEL (this folder, kernel.py)  ->  L2 hard limits / L1 leases (modelled in bench.py)  ->  L0 inverter (plant.py)
```

* **Home Assistant plans, the firmware lease closes the loop.** The kernel's `plan_*` functions are the planning step (a plan tick every
  1 to 10 minutes); its `charge_guards`, `export_guards`, `export_tick`, `judge_response` and `runaway_check` are what the dongle's 15 s
  guard tick runs, so they keep running with Home Assistant gone. Home Assistant never writes a register in the bench either.
* **One setpoint owner at a time.** The dongle model refuses a second start while a lease is open (`authority_busy`), snapshots the
  registers before its first write, verifies every write by readback, restores the snapshot (never a computed value) at every end, and
  at a restart ends and restores any open lease instead of resuming it. A Gentle lease happens once a night; a Charge Fixed session may
  be started again after the dwell.
* **The reason code is one of six** (`increase`, `reduce`, `hold`, `stop`, `unreachable`, `blocked`), each with a detail from a closed list
  and a plain sentence with the numbers it used (REQ-B10). A scenario fails if a decision has no sentence or an unfilled number.
* **The guard order is pinned** (REQ-B21): grid lost, owner end, untrusted time, stale telemetry, reserve floor, hard ceilings, measured
  power runaway, write budget, deadline, target guard; only then the optimisation.
* **Feasibility is the Gentle planner's own maths**: the pessimistic world (capacity band, efficiency 0.90, knee 90 %, tail 0.125) ported to
  Python and checked against the planner's golden vectors; `lowest_feasible` is its binary search over 100 W steps from 500 W.
* **The export loop is the proven Dump V1.1 law** as modelled from the firmware source: error = grid - target, step = error x 0.5 clamped to
  1000 W, rounded half away from zero to 100 W, floor 500 W, ceiling the lease's, 150 W deadband, 45 s settle, 120 writes a lease, the
  anti-windup counters, the one bounded retry, the stale-grid, Max Grid Export and runaway guards.
* **Measured solar enters only the loop**, never the energy plan: the export duration is sized from house + target with no solar credit
  (REQ-B15), and the floor, not the duration, is what protects the reserve.

## MEASURED versus ASSUMED: every plant parameter

Generated from `plant.PARAMETERS` (`run_sim.py --params`); the self-check fails if this table and the code differ. The grades:
MEASURED_REPLAY (computed from saved real telemetry, aggregates only), VERIFIED_LIVE (observed in a recorded live test), ASSUMED (a
placeholder with a stated reason), UNMEASURED (no data either way: the default is a documented choice and the plant flags it).

<!-- params:begin -->
| Parameter | Default | Unit | Grade | Source |
|---|---|---|---|---|
| `capacity_kwh` | 35.0 | kWh | MEASURED_REPLAY | usable energy per 100 % of the SOC reading: DC energy over SOC points on four saved nights (34.7 to 35.2); a site value, override it |
| `soc_resolution_pct` | 1.0 | % | MEASURED_REPLAY | the SOC reading steps in whole percent (2 % per 5 min at the plateau) |
| `soc_bias_pct` | 0.0 | % | ASSUMED | sensor scale or offset error added to the true SOC; the planner allows 3 % scale error, the default is none |
| `charge_eff` | 0.945 | DC per AC | MEASURED_REPLAY | 0.94 to 0.95 W reaches the battery per W of AC drawn (four nights, power-balance fit) |
| `discharge_eff` | 0.924 | AC per DC | MEASURED_REPLAY | AC delivered per DC drawn, power-balance fit over 32 497 samples |
| `standby_w` | 50.0 | W | MEASURED_REPLAY | the fixed part of the discharge-side loss in the same fit |
| `ac_input_cap_w` | 8980.0 | W | MEASURED_REPLAY | the inverter's own AC input held constant at 8.982 to 8.987 kW on every saved night with the slot at 8000 W; what sets it is NOT ESTABLISHED |
| `knee_soc_pct` | 98.0 | % | MEASURED_REPLAY | the plateau is flat to SOC 98 to 99 %, then the cliff (top rate only) |
| `cliff_width_pct` | 0.85 | % | MEASURED_REPLAY | SOC span over which the power falls to the tail: 2.5 to 4.8 min at about 8.4 kW is about 0.3 kWh (0.85 %); the 30 to 50 min trickle at 0.6 kW then covers the last 1.15 % |
| `tail_dc_w` | 600.0 | W | MEASURED_REPLAY | the trickle after the cliff: 0.55 to 0.65 kW for 30 to 50+ min (top rate) |
| `taper_below_top_measured` | False | flag | UNMEASURED | FLAG: no night was saved below the top rate, so the two gentle-rate values below are choices, not data |
| `knee_soc_gentle_pct` | 98.0 | % | UNMEASURED | default = the top-rate figure carried over; the cell-voltage cliff may arrive later at a gentle rate |
| `tail_gentle_dc_w` | 600.0 | W | UNMEASURED | default = the top-rate trickle carried over, capped by the commanded power |
| `charge_response` | scaled | enum | UNMEASURED | what a slot power below 8000 W does to a charge: 'scaled' (H1: AC input = setpoint x unit_scale), 'unbound' (H2/H3: the setpoint does not bind, the AC input stays at its cap) |
| `charge_min_ac_w` | None | W | UNMEASURED | a floor under the AC input in 'scaled' mode (a charger that cannot throttle below this); None = no floor; a scenario sets one to give a WEAK response |
| `unit_scale` | 1.1225 | AC per setpoint W | UNMEASURED | measured at ONE point only (8000 W gave 8.98 kW AC); alternatives the study lists: 1.0 (AC grid watts), 1.06 (DC battery watts), 1.1225 (the one point), 10x (a wrong unit) |
| `fp_dc_per_request` | 0.94 | DC per request W | MEASURED_REPLAY | Free Power: the battery took about 0.94 of the register-230 request (one event, 11 Oct) |
| `ac_output_cap_w` | 7890.0 | W | VERIFIED_LIVE | the inverter delivered 7.89 kW AC at an 8000 W slot-power ceiling |
| `discharge_unit_scale` | 1.0 | AC per setpoint W | VERIFIED_LIVE | a slot power is an AC-output ceiling, held from 500 to 7000 W |
| `shutdown_soc_pct` | 10.0 | % | ASSUMED | the inverter's own last-resort low-SOC cutoff (registers 217 to 219 are read-only and site-specific); a placeholder |
| `ignore_ceiling_w` | None | W | VERIFIED_LIVE | fault injection: the 22 Sept 2026 anomaly, the battery discharged about 8.6 kW against a 1000 W ceiling (cause UNKNOWN); None = off |
| `tau_charge_s` | 5.0 | s | MEASURED_REPLAY | the battery reached 98 % of its plateau within 17 s of a verified Free Power start |
| `tau_discharge_s` | 15.0 | s | MEASURED_REPLAY | telemetry needs about 45 s to settle after a slot-power change (the firmware's settle) |
| `pv_eff` | 0.97 | AC per DC | ASSUMED | PV DC to inverter AC; the firmware's feed-forward ignores it and the loop corrects |
| `island_ac_cap_w` | 8000.0 | W | ASSUMED | the most AC the inverter can supply to the house off grid |
| `slot_caps_offgrid_discharge` | False | flag | UNMEASURED | UNKNOWN until proof rung R3: does a lowered slot power also cap the battery's supply to the house off grid? default no; a scenario sets yes |
<!-- params:end -->

The charge response below the top rate is the central unknown. `plant.UNIT_ALTERNATIVES` lists the alternatives of the control-authority
study (AC grid watts, DC battery watts, the one measured point, H2 / H3 "the slot power does not bind", a unit wrong by 10x either way);
scenarios `g11` to `g15b` run them. The plant also takes `taper_below_top_measured=False`, which says in the data itself that the gentle-rate
knee and tail are the top-rate figures carried over.

**Calibration (replay).** `test_sim.py` replays the plant at the top rate against the aggregates of the four saved nights and of the
staged discharge commissioning: 27 to 98 percent in about 175 minutes; DC plateau 8.3 to 8.6 kW at a constant 8.98 kW AC input; 2.5 to
10 minutes from above 7 kW to below 2 kW; a 0.6 kW trickle for 30 to 50 minutes; grid import = charge + house; the discharge DC-over-AC
residual of the recorded leases; 7.89 kW AC at an 8000 W ceiling. The numbers are copied into the test as constants with their source
(the raw files are offline evidence and never enter this repository).

## What is pinned

A constant that is also written somewhere else is compared with that place, so a drift fails the self-check instead of passing silently.

| Kernel constant | Pinned to | How |
|---|---|---|
| export loop: settle 45 s, deadband 150 W, gain 0.5, step 1000 W, round 100 W, floor 500 W, 120 writes a lease, feed-forward start 2000 W, response samples 3, response margin 100 W, wrong direction 300 W, recovery hold 60 s and one attempt, grid and SOC stale 90 s, runaway margin 750 W / 3 samples / 30 s grace, absolute backstop 750 W / 2 samples / 3000 W floor, export trip 500 W / 100 W, reboot timeout 15 min, setpoint bound 8000 W | `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` (the substitutions block) | parsed; each value compared |
| the 15 s guard tick and the 1 s export trip | the same file's `interval:` blocks | the block that runs `dump_controller_tick` and the one that acts on `dump_export_trip` |
| the loop law and the Stop SOC rule (`reading <= latched stop` ends the lease) | the same file's `dump_controller_tick` and watchdog text | the lines the model copies must still be present |
| charge: step 100 W, minimum 500 W, dwell 30 min, 6 changes, decrease hysteresis 500 W, slack 15 min, pessimistic efficiency 0.90, capacity band 6 %, scale error 3 %, SOC resolution and noise, knee 90 %, tail 0.125, drop 5 min, demand margin 20 %, efficiency maximum 0.97, buffer 60 min, the 500 W and 8000 W limits | `frontend/ecco-plan-core/src/gentleNight.ts` (`DEFAULT_NIGHT_PARAMS`, the buffer default) and `settings.ts` | parsed; each value compared |
| the feasibility maths (plateau, knee, fall, tail, the lowest feasible rate) | the planner's golden probe `frontend/ecco-plan-core/test/gentleNightProbe.golden.json` | the Python port reproduces the planner's needed rate, its feasibility and its pessimistic finish for cases A, A60, B, C, C93, D (charging past the knee), E and F, without Node |
| GRC budgets: 10 writes a night with 4 reserved for restores, largest step 2000 W, change under 300 W refused and 600 W against the last direction, plan lost after 20 min, lease ends 10 min before the slot end, gain 50 to 150 percent, second weak response ends it, a running charge of 1000 W needed, runaway 115 percent + 500 W | the guarded charge-rate controller design (GRC SPEC revision 3, section 5; branch `dev/gentle-rate-controller`) | **by value only**: that design is not in this tree. The planner states the same dwell and change count and is parsed; if the SPEC file appears in a tree the self-check also looks for its numbers |
| the ASSUMED kernel constants (the 90 s control bound as one number, the 45 s hold on a stale reading, the 5 percent import margin, the 30 minute house peak and its 5 minute mean, the NTP age bound, the 120 s reaction bound, the progress tracker's 30 min / 8 points / 7 percent) | nothing: they are listed in `kernel.py` under ASSUMED | not pinned; each is a named constant a later review can change |

## How a later controller plugs in (the policy interface)

A controller is a function of the kernel's inputs that returns one `Decision`. Everything it may use arrives in the arguments; nothing is
read from a clock, a file or a global.

```python
d = policy(inp, obj, lim, st)          # kernel.Inputs, ChargeObjective or ExportObjective, kernel.Limits, kernel.State
# d.reason  in kernel.REASONS            increase | reduce | hold | stop | unreachable | blocked
# d.detail  in kernel.DETAILS[d.reason]  a closed list; every pair has one sentence in kernel.EXPLAIN
# d.write_w                              the setpoint to write now, or None
# d.end                                  True = end the session now (the dongle restores the snapshot)
# d.unreachable                          the objective cannot be met; the target is never lowered to hide it
# d.explanation                          always present, with the numbers it used
```

* `Inputs` carries the telemetry **with its age** (`Frame.age_s`; unavailable is stale), the grid state, the trust of the clock the decision
  depends on, Hold, the effective reserve and the readback of the setpoint in force. `Limits` carries the power ceiling, the owner's import
  ceiling (None = none applied, and the plan says so) and the Max Grid Export.
* Budgets are not the policy's job: a wanted setpoint goes through `ramp_charge` (dwell, deadband, reversal, step, change count, write
  count; a forced safety reduction is the only way past the dwell) or `export_step` (the Dump law); the dongle model refuses anything that
  would break a budget and the `BUDGETS` invariant counts the refusal as a failure of the policy.
* Register the policy in `kernel.POLICIES`, give the bench a stack for it (a `START` payload, the lease it creates, the guards it runs; see
  `Bench.ha_charge`, `Bench.ha_export`, `Bench.charge_tick`, `Bench.export_tick`) and run every existing scenario against it with
  `scenarios.run_spec(spec, kernel_module)`. The kernel is passed in as a module, which is also how the mutation test replaces it.
* A policy may not read a forecast: the kernel's inputs contain none, so "never rely on an optimistic forecast" holds by construction
  (REQ-B15). It may not use a limit as a target (REQ-B16): in the kernel a limit only caps a wanted power or trips a guard.

## How to add a scenario

1. Build a `bench.Scenario` with `gentle(...)`, `fixed(...)` or `export(...)` in `scenarios.py`: the plant parameters (`P.PlantParams(...)`),
   the house and solar series (`P.Series`), the window and target or the export target and Stop SOC, the channels (`cmd_delay_s`,
   `cmd_loss`, `tel_gaps`, `trust`), and `events` such as `grid_loss`, `hold`, `reserve`, `import_ceiling`, `plant` (change a plant
   parameter mid-run), `dongle_restart`, `dongle_dead`, `ha_down`, `plan_stop`, `ignore_writes`, `second_start`. Set `react_s` to the
   reaction bound the scenario can honestly claim (plan period + command delay + a few ticks).
2. Add it with `add(scenario, expectations..., covers=("REQ-...",))`. The expectation helpers (`X_reached`, `X_saw`, `X_lease_ended`,
   `X_no_writes`, `X_alert`, ...) return `(ok, detail)`. A scenario that demonstrates a gap lists it in `known_gap`: that invariant MUST
   fail, and the backstop that applies is shown in the table.
3. Run `run_sim.py name -v`. Then regenerate the two tables (`--covers`, `--params`), paste them between their markers in this file and
   add the scenario name to the row of each requirement it covers in [../REQUIREMENTS.md](../REQUIREMENTS.md) (the self-check names any
   pair that is missing).
4. If it can be broken by a code change the existing scenarios do not notice, add a mutant to `test_sim.py` (a line of `kernel.py`, its
   mutated text; both must occur exactly once).

## The invariants, and the scenarios with the requirements they cover

Every run is judged by `scenarios.check_invariants` with the REAL kernel's constants, never those of a mutated copy:

| Invariant | Holds when |
|---|---|
| RESERVE_FLOOR | an export never discharges below the larger of the Stop SOC and the effective reserve in force one reaction time earlier |
| IMPORT_CEILING | with an import ceiling configured, no breach the charger causes lasts longer than the reaction bound while ECCO holds the session |
| POWER_CEILING | every setpoint written is inside 500 W and the ceiling and, for a lease, never above the pre-session value |
| BUDGETS | dwell, change count, write count (charge), settle and write count (export) are never exceeded, and the dongle never has to refuse a request |
| REACHES_OR_REPORTS | the SOC reading reached the target by the deadline, or 'unreachable' was reported at least 15 minutes before it |
| NEVER_WORSE_THAN_TODAY | (Gentle, REQ-A12) the same night is run beside it with no ECCO at all; whenever today's fixed rate reaches the target 25 minutes before the window end, the Gentle night reaches it by the window end |
| NO_UNTRUSTED_ACTUATION | no start, change or loop write while the clock it depends on is untrusted |
| ONE_WRITER | at most one lease at a time and every write belongs to the lease that is open |
| EXPLAINED | every decision has a reason from the closed list, a detail from its list and a complete sentence |
| RESTORED_OR_ALERTED | at the end no lowered or overriding value is left silently: the owner's values are back or an alert was raised |
| PHYSICAL | the battery stays between 0 and 100 percent and every number is finite |

### Scenarios

Generated from `scenarios.SPECS` (`run_sim.py --covers`); the self-check fails if this table and the code differ, and if the
`Covered by` column of [../REQUIREMENTS.md](../REQUIREMENTS.md) does not name the same pairs.

<!-- covers:begin -->
| Scenario | Policy | What it does | Requirements (REQUIREMENTS.md) |
|---|---|---|---|
| `g01_nominal` | gentle | Nominal night: 25 to 90 percent, light house load; the lowest practical rate, re-planned from the measured SOC. | REQ-A1, REQ-A2, REQ-A5, REQ-A8, REQ-A12, REQ-B4, REQ-B7, REQ-B8, REQ-B10, REQ-B11, REQ-C9 |
| `g02_heavy_overnight_load` | gentle | A heavy overnight house load (4.5 kW for 90 minutes) with no import ceiling: the grid carries it, progress is unaffected, so the rate is held. | REQ-A3, REQ-A10, REQ-B5 |
| `g03_heavy_load_import_ceiling` | gentle | The same load with an 11 kW import ceiling: import would pass it, so the setpoint is lowered at once and the target reported at risk. | REQ-A4, REQ-A7, REQ-A9, REQ-B5, REQ-C10, REQ-D2 |
| `g04_load_removal` | gentle | A heavy load for 30 minutes then sudden removal, with an import ceiling: the forced reduction is undone only after the dwell and hysteresis. | REQ-A6, REQ-A10 |
| `g05_kettle_spikes` | gentle | Kettle-sized bursts (3 kW for 3 minutes every 25 minutes) with a roomy import ceiling: no rate change follows a burst. | REQ-A6 |
| `g06_high_start_soc` | gentle | High starting SOC: 80 to 95 percent, so the plan is gentle and short. | REQ-A5, REQ-A10 |
| `g07_low_start_soc_tight` | gentle | Low starting SOC and a short window: 8 to 100 percent in four hours cannot make a 60 minute buffer; 'unreachable' is said at the first plan tick. | REQ-A9, REQ-A10, REQ-B8 |
| `g08_efficiency_drop` | gentle | Charging efficiency falls from 0.945 to 0.70 after 30 minutes: the SOC lags the pessimistic projection, the progress tracker flags it and the rate is raised in bounded steps; any shortfall is reported. | REQ-A3, REQ-A4, REQ-A10 |
| `g09_efficiency_gain` | gentle | Efficiency better than assumed (0.97) and a smaller battery (30 kWh): ahead of the plan, the rate is lowered. | REQ-A5, REQ-A10 |
| `g10_taper_cliff_98` | gentle | Charge to 100 percent through the measured plateau, the cliff at 98 percent and the trickle: the planner's pessimistic knee (90) says 'at risk' where the real knee (98) lets the night reach, so the plan is conservative and never optimistic. | REQ-A7, REQ-A12, REQ-B6 |
| `g11_unit_ac_watts` | gentle | Unit alternative: the setpoint is AC grid watts (scale 1.0). The plan measures the gain; it never assumes it. | REQ-A7, REQ-B18 |
| `g12_unit_dc_watts` | gentle | Unit alternative: the setpoint is DC battery watts (scale 1/0.945). | REQ-A7, REQ-B18 |
| `g13_unit_wrong_x10` | gentle | Unit wrong by 10x (every setpoint above 800 W hits the AC cap): the first lowered setpoint changes nothing, the gain is implausible, the lease ends and the original rate stands. | REQ-B18, REQ-D3 |
| `g14_unit_wrong_div10` | gentle | Unit wrong by 10x the other way (the charge at the original setpoint is under 1 kW): nothing is started, the owner is told no charge is running. | REQ-B18 |
| `g15_unbound_response` | gentle | H2/H3: the slot power does not bind the charge. The first change shows no response, the lease ends, today's rate stands. | REQ-A7, REQ-B17, REQ-B18, REQ-D3 |
| `g15b_charge_floor_weak_response` | gentle | The charger cannot throttle below 8.7 kW: a lowered setpoint moves the power by less than a third of what it should; the measured gain leaves its band at the next change, the lease ends and today's rate stands. | REQ-A7, REQ-B17, REQ-B18, REQ-D3 |
| `g16_target_already_reached` | gentle | The battery is already above the target: nothing is started and the plan says why. | REQ-A10, REQ-B4 |
| `g17_delayed_commands` | gentle | Every command takes 90 seconds to reach the dongle: budgets and dwell still hold. | REQ-B22, REQ-C5 |
| `g18_start_command_lost` | gentle | The first command (the start) is lost in transit: Home Assistant sees no lease and sends it again. | REQ-B22, REQ-C12 |
| `g19_inverter_ignores_write` | gentle | From 10 minutes in the inverter takes no new value: the next change fails its readback, the restore fails three times and the owner is alerted (FAULT). | REQ-C7, REQ-C12, REQ-D5 |
| `g20_telemetry_short_gap` | gentle | A 60 second telemetry gap (under the 90 second bound): nothing stops, nothing is raised on stale data. | REQ-B3 |
| `g21_telemetry_long_gap` | gentle | A 5 minute telemetry gap: beyond the bound the lease ends and today's rate takes over. | REQ-B3, REQ-B9 |
| `g22_soc_unavailable_at_start` | gentle | No telemetry for the first 12 minutes: nothing is started on missing data. | REQ-B3 |
| `g23_restart_in_lease` | gentle | The dongle restarts in the middle of the lease: the snapshot is restored at boot and the lease is never resumed. | REQ-B9, REQ-B22, REQ-C7, REQ-C12 |
| `g24_dead_dongle_charge` | gentle | The dongle dies for good during the lease: no guard runs, the lowered value stays; the owner is alerted. (The backstop is the alert and the after-window check.) | REQ-D4 |
| `g25_ha_outage` | gentle | Home Assistant is gone for an hour: after 15 minutes without an API client the dongle restarts, which restores the lease. | REQ-B9, REQ-C7, REQ-D4 |
| `g26_plan_lost` | gentle | Home Assistant stays connected but stops handing over plans: after 20 minutes the lease ends (plan lost). | REQ-B9, REQ-C7 |
| `g27_rtc_untrusted_mid_lease` | gentle | The inverter clock becomes untrusted mid-lease: time-dependent actuation fails safe, the lease ends, nothing is raised. | REQ-D1, REQ-B21 |
| `g27b_stale_and_untrusted_together` | gentle | The telemetry goes stale and the inverter clock becomes untrusted on the same tick: the guard order decides, and time comes before staleness. | REQ-B21, REQ-D1 |
| `g28_rtc_untrusted_at_start` | gentle | The inverter clock is untrusted for the first 15 minutes: no start until it is trusted. | REQ-D1, REQ-B21 |
| `g29_grid_loss_in_lease` | gentle | Grid lost mid-lease (and a lowered slot may cap the battery off grid): the lease ends first and the original value is restored at once. | REQ-B21, REQ-D7 |
| `g30_import_ceiling_drop` | gentle | The owner's import ceiling is applied mid-lease (9 kW) with 2 kW of house load: the forced reduction does not wait for the dwell. | REQ-B21, REQ-C10, REQ-D2 |
| `g31_two_policies` | gentle | Another controller tries to start an export while the Gentle lease owns the setpoint: refused, one writer per setting. | REQ-B19, REQ-B20, REQ-C11 |
| `g32_hold_pressed_charge` | gentle | The owner presses Hold mid-lease: the session ends, the pre-session values are back, nothing restarts while Hold is on. | REQ-C12, REQ-B21 |
| `g33_target_guard` | gentle | The real battery is far larger than the plan (46 kWh against 35): the plan falls behind and the target is handed back to today's rate in time. | REQ-A12, REQ-B21 |
| `f01_fixed_nominal` | charge_fixed | Charge Fixed at 8 kW from 30 to 90 percent: one rate, ended at the target (two writes: start and restore). | REQ-B2, REQ-B11, REQ-B12 |
| `f02_fixed_import_breach` | charge_fixed | Charge Fixed with an 11 kW import ceiling and a 4 kW house load: import would pass it, so the session ends at once; a later start uses the headroom rate. | REQ-B12, REQ-C10, REQ-D2 |
| `f03_fixed_unreachable` | charge_fixed | Charge Fixed at only 2 kW from 10 to 100 percent: the start says at once that this rate cannot make the target. | REQ-A9, REQ-B8 |
| `e01_nominal` | export | Nominal export: 2 kW net export from 80 percent, house 1 kW, no solar; the loop settles inside the deadband and the lease ends at its planned end. | REQ-B13, REQ-B14, REQ-C9 |
| `e02_house_step_up` | export | House load jumps from 1 to 3.5 kW with a 6 kW ceiling: the ceiling is raised in 1 kW steps at least 45 s apart and the export recovers. | REQ-B5, REQ-B13, REQ-B16 |
| `e02b_house_step_infeasible` | export | The same step with the proven 3 kW ceiling: the target is infeasible high, said plainly; the export is never forced by importing. | REQ-B13, REQ-B16 |
| `e03_house_step_down` | export | House load falls from 3 kW to 0.5 kW: the export jumps, the loop steps the ceiling down by at most 1 kW per 45 s and returns inside the band. | REQ-B13 |
| `e04_kettle_spikes` | export | Kettle-sized bursts (3 kW for 2 minutes): settle and deadband keep the number of writes small. | REQ-B7, REQ-B13 |
| `e05_pv_cloud` | export | Solar drops from 1.5 kW to 0.3 kW for ten minutes: the loop follows the measured grid, never a forecast. | REQ-B13, REQ-B15 |
| `e06_pv_evening_drop` | export | Solar falls away to nothing over 90 minutes: the energy plan credited no solar, the floor (not the duration) is the safety, the SOC stays above it. | REQ-B14, REQ-B15 |
| `e07_infeasible_low` | export | Solar alone (3.5 kW) already exports more than the 1 kW target: nothing is started, the plan says so, the battery is never charged to absorb it. | REQ-B13, REQ-B15, REQ-B16 |
| `e07b_pv_rises_during_export` | export | Solar rises during a running export: the ceiling falls to the 500 W floor and no further, the export is reported infeasible low, the battery never charges. | REQ-B13, REQ-B15, REQ-B16 |
| `e08_stale_grid_gap` | export | A 3 minute telemetry gap during the lease: past 90 seconds the lease fails closed and is restored. | REQ-B3, REQ-B9 |
| `e09_stop_soc_reached` | export | A rising house load drains the battery faster than planned: the Stop SOC (staged above the effective reserve) ends the lease before the reserve. | REQ-B14 |
| `e10_reserve_rises` | export | The effective reserve rises from 20 to 60 percent during the export: Home Assistant asks for a raise-only Stop SOC and the lease ends above the new reserve. | REQ-B14, REQ-B21 |
| `e10b_reserve_above_soc` | export | The reserve jumps above the battery's own SOC: the discharge stops within the declared reaction time. | REQ-B14, REQ-B21 |
| `e11_hold_pressed` | export | The owner presses Hold during the export: Home Assistant ends the session within a plan tick and the pre-session values are restored. | REQ-B21, REQ-C12 |
| `e11b_hold_end_command_lost` | export | Hold is pressed and the first End command is lost in transit: Home Assistant sends it again at the next plan tick and the session still ends. | REQ-B22, REQ-C12 |
| `e12_restart_in_lease` | export | The dongle restarts during the export: the lease is ended and restored at boot, never resumed. | REQ-B9, REQ-B22, REQ-C7 |
| `e13_dead_dongle` | export | The dongle dies mid-export: no firmware guard runs, the last ceiling stays in force, ECCO's reserve is NOT protected. The backstops are the inverter's own shutdown SOC and the owner alert. | REQ-D4 |
| `e14_unit_wrong_x10` | export | Export unit wrong by 10x with no Max Grid Export set: the measured-power guard ends the lease within a few samples. | REQ-B18, REQ-D3 |
| `e15_runaway_anomaly` | export | The 22 Sept 2026 anomaly: the battery ignores its ceiling mid-lease. The runaway guard ends the lease. | REQ-D3 |
| `e16_export_time_untrusted` | export | The dongle's NTP time is untrusted for the first 10 minutes: no start until it is trusted. | REQ-D1, REQ-B21 |
| `e17_grid_loss_export` | export | Grid lost during the export: the session ends first and the pre-session values are restored. | REQ-B21 |
| `e18_export_over_limit` | export | The house load falls away under a 2.5 kW Max Grid Export: one sample far over ends the lease at once. | REQ-B21, REQ-C10 |
| `e19_second_policy_export` | export | A Gentle start is attempted while the export owns the setpoint: refused. | REQ-B19, REQ-B20, REQ-C11 |
| `e20_delayed_commands_export` | export | Commands take 90 seconds: a reserve rise is acted on late but inside the declared reaction time. | REQ-B14, REQ-B22 |
<!-- covers:end -->

## What the bench found about the designs (read before relying on any of it)

These are results of the model, not observations of the inverter; each has a scenario.

1. **The proven Dump loop can end a lease in a slow solar decline** (`e06_pv_evening_drop`). Its corrections are 100 W steps against a 100 W
   response margin; when the error drifts while a correction settles, a correct small step is judged ineffective, three in a row hold the
   loop for 60 s, the one retry fails the same way and the lease fails closed (restored, safe). In the scenario it ends after about half an
   hour of a 90 minute decline. The export coordinator (N3) should treat that end as a prompt for one guarded re-start; the bench does not
   model the re-start.
2. **The GRC design has no way to step the setpoint down quickly.** Every guard ends through the restore of `original`, which writes the
   HIGHER pre-lease value; an import breach caused by a heavy house load would be made worse by that restore. The kernel's forced reduction
   (`g03`, `g04`, `g30`: it ignores the dwell and the change count, moves at most 2000 W, and always leaves one write for the restore)
   needs a counterpart in the firmware design; today none exists. This is a design decision for the owner and the independent review.
3. **A configured import ceiling is only enforced while ECCO holds the session.** With no lease the owner's own table charges at the owner's
   own rate; the kernel starts a session only to lower it (the safety start of `plan_gentle`), so the reaction is the plan period plus the
   command and one dongle tick (about 5 to 10 minutes in the sweep), a soft gate. A firmware import guard (N6) would cut that to one tick.
   After a session has ended the restore writes the owner's value back; the invariant does not count a breach from that value as ECCO's.
4. **"Never worse than today" yields to the import ceiling.** The target guard hands the charge back to the pre-session rate only when that
   rate fits under the ceiling; otherwise the lease continues at the limited rate and the shortfall is reported (`unreachable`).
5. **A dead dongle leaves ECCO's reserve unprotected** (`e13_dead_dongle`, a documented gap): the export continues at the last ceiling
   until the inverter's own shutdown SOC (assumed 10 percent; the register is read-only and site-specific), and only the Home Assistant
   alert (about two minutes plus a plan tick, assumed) tells the owner. For a charge (`g24`) the lowered value stays every night; the alert
   is the backstop, and the after-window check of the GRC design is not modelled.
6. **A wrong or non-binding setpoint unit is caught by the measured gain, not by the unit** (`g13`, `g15`, `g15b`): after the first lowered
   write the realised AC power does not follow, the gain leaves 50 to 150 percent of the assumed unit and the lease ends within a tick or
   two of the 45 s settle; today's rate carries the night (never worse than today). A unit too small (`g14`) is "no charge of 1 kW is running":
   nothing starts and the owner is told.
7. **The progress tracker needs time.** It judges the SOC points per AC kWh against the pessimistic world over at least 30 minutes and 8
   points (a one-point reading error is then at most 12 percent), so a collapse of the charging efficiency is flagged about an hour after it
   starts at the rates used here (`g08`); a shortfall beyond the pessimistic envelope is reported when the projection at the highest allowed
   rate says so (`g33`), not before.

## What this does not prove

* **It is not the inverter.** Every behaviour of the plant that is not MEASURED_REPLAY or VERIFIED_LIVE in the table above is a choice. The
  charge response below the top rate, the knee and tail at gentle rates, the off-grid effect of a lowered slot power (proof rung R3), the
  meaning and unit of the setpoint, flash wear, the BMS limits and derating, usable capacity, the import limit of the installation and the
  22 Sept 2026 anomaly's cause remain NOT ESTABLISHED. A kernel that passes here still needs rungs R3 to R10 of the live-proof ladder.
* **The dongle and Home Assistant are models.** The Dump loop is modelled from the firmware source; the charge lease from the GRC design (a
  design, not firmware); the one-owner arbiter, the raise-only Stop SOC, the import guard and the plan hand-over are the proposed N6 behaviour.
  Nothing here shows the firmware does, or will do, any of this. The bench's tick is 15 s and its telemetry arrives once a tick (the real
  cadence is 10 s); the write latency is one tick.
* **The invariants are bounded claims.** The sweep draws plants inside the declared envelope of the pessimistic world (capacity up to 9
  percent above what the kernel is told, efficiency not below 0.90, knee at or above 90 percent, exogenous events in the first 40 percent
  of the window); outside it a scenario shows what is reported and when, and the guarantee is "reported", not "reached". The SOC reading,
  with its one-point resolution, is the unit of "reached" and of the reserve floor; a sensor scale error outside the planner's band is not
  modelled for exports.
* **Mutants test the kernel's tests, not the kernel's correctness.** The mutants are single-line in-memory edits of `kernel.py`; killing all
  of them shows the suite notices those edits, not that no other defect exists. Measured when this was written: the unit tables kill all of
  them, the scenarios alone kill about a quarter (the rest are boundary edits, one epsilon or one count, that a whole night does not
  resolve): a scenario is an end-to-end witness, the tables are the sharp instrument.
* **Three open items stay with the owner.** The installation's grid import limit (a value only the owner can supply; the plan runs "none
  applied" and says so), the Q8 decision for the interlock, and the unattended-export approval; this folder decides none of them.
