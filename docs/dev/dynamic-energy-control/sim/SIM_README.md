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
| [test_sim.py](test_sim.py) | the self-check: statements and static shape, pins, unit tables, closed lists, scenarios, the invariants judged on hand-made runs, plant replay, README tables, seeded property sweeps, in-memory mutants of the kernel AND of the bench |
| [grc_core_constants.txt](grc_core_constants.txt) | the numbers of the guarded charge-rate controller design the kernel mirrors, vendored with their source commit: asserted values, not a live pin |

Run (Python 3.12, standard library only; no Node, no network):

```powershell
cls
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\sim\run_sim.py          # the table; add -v for invariants and explanations, a name for one scenario
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\sim\test_sim.py         # the self-check (about two minutes)
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
* **A request that raced a write is stale, not refused.** An ordinary change Home Assistant decided BEFORE the lease's last write (a forced
  reduction landed while the command was on its way) is dropped by the dongle model as stale and decided again at the next plan tick; the
  BUDGETS invariant stays strict (any refusal for the budget is the policy's failure), and a bench mutant that executes the stale request
  dies in the seeded sweep.
* **The reason code is one of six** (`increase`, `reduce`, `hold`, `stop`, `unreachable`, `blocked`), each with a detail from a closed list
  and a plain sentence with the numbers it used (REQ-B10). A scenario fails if a decision has no sentence or an unfilled number.
* **The guard order is pinned** (REQ-B21): grid lost, owner end, untrusted time, stale telemetry, reserve floor, hard ceilings, measured
  power runaway, write budget, deadline, target guard; only then the optimisation.
* **Feasibility is the Gentle planner's own maths**: the pessimistic world (capacity band, efficiency 0.90, knee 90 %, tail 0.125) ported to
  Python and checked against the planner's golden vectors; `lowest_feasible` is its binary search over 100 W steps from 500 W.
* **The export loop is the proven Dump V1.1 law** as modelled from the firmware source: error = grid - target, step = error x 0.5 clamped to
  1000 W, rounded half away from zero to 100 W, floor 500 W, ceiling the lease's, 150 W deadband, 45 s settle, 120 writes a lease, the
  anti-windup counters, the one bounded retry, the stale-grid, Max Grid Export and runaway guards.
* **The measured-power guard follows the firmware's per-sample rules** (`runaway_limits`, `export_tick`; finding F08 of the review, which found
  that the first version counted one stale reading twice and ended healthy leases about 2 percent of the time): one count per NEW battery
  power reading (a repeated reading in a telemetry gap is not another sample); ONE settling grace, from the lease start (a write no longer
  re-arms it); for 30 s after a verified write the higher of the old and the new ceiling is the command; above 3000 W the absolute
  backstop's 750 W margin grows by 12 percent of the command above it (the battery's DC power includes the conversion loss); and a grid
  sample used to judge or propose a correction must postdate the last write (the firmware's fence, a soft wait). Pinned to the firmware
  text. NOT modelled, and only ever making the firmware stricter: its windowed criteria (4 of the last 8 samples above the ordinary
  threshold or the backstop, 3 of 8 above the gross level), the 300 W windowed-mean criterion, and its frozen-telemetry and cross-checks;
  a lease that passes here can still be ended by those on the real dongle. The review's night is `e22`.
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
| `cliff_width_pct` | 0.85 | % | MEASURED_REPLAY | SOC span over which the power falls to the tail: 2.5 to 4.8 min at about 8.4 kW is about 0.3 kWh (0.85 %); the trickle at 0.6 kW then covers the last 1.15 % |
| `tail_dc_w` | 600.0 | W | MEASURED_REPLAY | the trickle after the cliff (top rate): 0.55 to 0.65 kW. It ran 30 to 50 min on 2 of the 4 saved nights (18 and 19 Nov); on 20 Nov (0.64 then 0.33 kW) and 21 Nov (0.45 kW) the session ended while it was still running, so its full length is known from two nights only and the plant's 40 min is the slow end |
| `cliff_shape` | linear | enum | ASSUMED | the shape of the power fall at the knee: 'linear' (a straight fall in SOC over cliff_width_pct, the default) or 'step' (the power drops to the tail at the knee); only the SPAN of the fall (2.5 to 4.8 min at the top rate) is measured, not its shape |
| `top_rate_threshold` | 0.9 | fraction | ASSUMED | the share of ac_input_cap_w at or above which the TOP-rate knee and tail apply (knee_soc_pct, tail_dc_w) and below which the gentle-rate ones do: a parameter switch, discontinuous at that rate (with different sets the same battery reads 100 % at 5595 s on a 6000 W lease and at about 16950 s on an 8000 W one) |
| `slot_target_stops_charge` | True | flag | UNMEASURED | rung R1 (CONTROL_AUTHORITY.md 4.4 and section 9): does the inverter stop a grid charge when the SOC reaches the slot's own target below 100 %? True = it stops (expected Deye behaviour, no measurement in the evidence read), False = it keeps charging at the slot power until the battery is full; it shapes every target-below-100 night, the today baseline and the import after a lease |
| `taper_below_top_measured` | False | flag | UNMEASURED | FLAG: no night was saved below the top rate, so the two gentle-rate values below are choices, not data |
| `knee_soc_gentle_pct` | 98.0 | % | UNMEASURED | default = the top-rate figure carried over; the cell-voltage cliff may arrive later at a gentle rate |
| `tail_gentle_dc_w` | 600.0 | W | UNMEASURED | default = the top-rate trickle carried over, capped by the commanded power |
| `charge_response` | scaled | enum | UNMEASURED | what a slot power below 8000 W does to a charge: 'scaled' (H1: AC input = setpoint x unit_scale), 'unbound' (H2/H3: the setpoint does not bind, the AC input stays at its cap) |
| `charge_min_ac_w` | None | W | UNMEASURED | a floor under the AC input in 'scaled' mode (a charger that cannot throttle below this); None = no floor; a scenario sets one to give a WEAK response |
| `unit_scale` | 1.1225 | AC per setpoint W | UNMEASURED | measured at ONE point only (8000 W gave 8.98 kW AC); alternatives the study lists: 1.0 (AC grid watts), 1.06 (DC battery watts), 1.1225 (the one point), 10x (a wrong unit) |
| `fp_dc_per_request` | 0.97 | DC W per request W | MEASURED_REPLAY | Free Power at 8000 W requested (register 230 = 155 A): the battery took 7.67 to 7.87 kW DC at 52.7 to 53.8 V, 0.96 to 0.98 of the request in WATTS (0.97 used; one event, 11 Oct). The 0.94 of the evidence is the CURRENT ratio (146 A of 155 A), not a power ratio |
| `ac_output_cap_w` | 7890.0 | W | VERIFIED_LIVE | the inverter delivered 7.89 kW AC at an 8000 W slot-power ceiling |
| `discharge_unit_scale` | 1.0 | AC per setpoint W | VERIFIED_LIVE | a slot power is an AC-output ceiling, held from 500 to 7000 W |
| `shutdown_soc_pct` | 10.0 | % | ASSUMED | the inverter's own last-resort low-SOC cutoff (registers 217 to 219 are read-only and site-specific); a placeholder |
| `ignore_ceiling_w` | None | W | VERIFIED_LIVE | fault injection: the 22 Sept 2026 anomaly, the battery discharged about 8.6 kW against a 1000 W ceiling (cause UNKNOWN); None = off |
| `tau_charge_s` | 5.0 | s | MEASURED_REPLAY | the battery reached 98 % of its plateau within 17 s of a verified Free Power start |
| `tau_discharge_s` | 15.0 | s | ASSUMED | inferred from the firmware's 45 s settle (telemetry needs about 45 s to settle after a slot-power change, about three time constants); never measured as a lag |
| `pv_eff` | 0.97 | AC per DC | ASSUMED | PV DC to inverter AC; the firmware's feed-forward ignores it and the loop corrects |
| `island_ac_cap_w` | 8000.0 | W | ASSUMED | the most AC the inverter can supply to the house off grid |
| `slot_caps_offgrid_discharge` | False | flag | UNMEASURED | UNKNOWN until proof rung R3: does a lowered slot power also cap the battery's supply to the house off grid? default no; a scenario sets yes |
<!-- params:end -->

Three things are choices made WITHOUT data and are parameters for that reason: whether the slot's own target SOC stops a charge below 100 %
(`slot_target_stops_charge`, rung R1, UNMEASURED), the shape of the power fall at the knee (`cliff_shape`, ASSUMED: only its span is measured)
and the rate at which the top-rate knee and trickle give way to the gentle-rate ones (`top_rate_threshold`, ASSUMED: a discontinuous switch,
so on the same battery a 6000 W lease and an 8000 W one can read 100 % hours apart). The self-check runs every charge scenario once with the
slot target NOT stopping the charge: all of them hold, and the only difference is that the night ends above its target (the battery goes on to
100 %) and that the post-session import of finding F01 lasts longer.

The charge response below the top rate is the central unknown. `plant.UNIT_ALTERNATIVES` lists the alternatives of the control-authority
study (AC grid watts, DC battery watts, the one measured point, H2 / H3 "the slot power does not bind", a unit wrong by 10x either way);
scenarios `g11` to `g15b` run them. The plant also takes `taper_below_top_measured=False`, which says in the data itself that the gentle-rate
knee and tail are the top-rate figures carried over.

**Calibration (replay).** `test_sim.py` replays the plant at the top rate against the aggregates of the four saved nights and of the
staged discharge commissioning: 27 to 98 percent in about 175 minutes; DC plateau 8.3 to 8.6 kW at a constant 8.98 kW AC input; 2.5 to
4.8 minutes from above 7 kW to below 2 kW (the plant sits at 3.0); a 0.6 kW trickle for 30 to 50 minutes (the saved nights show the whole
trickle on **2 of the 4** nights, 18 and 19 Nov: on 20 and 21 Nov the session ended while it was still running, so the plant's 40 minutes is
the slow end of what two nights show); grid import = charge + house; the discharge DC-over-AC residual of the recorded leases; 7.89 kW AC
at an 8000 W ceiling; a Free Power request of 8000 W gives 7.67 to 7.87 kW DC (the evidence's 0.94 is the current ratio, 146 A of 155 A; in
watts it is 0.96 to 0.98, so the plant uses 0.97). The discharge lag `tau_discharge_s` is ASSUMED (inferred from the firmware's 45 s settle),
not measured. The numbers are copied into the test as constants with their source (the raw files are offline evidence and never enter this
repository).

## What is pinned

A constant that is also written somewhere else is compared with that place, so a drift fails the self-check instead of passing silently.

| Kernel constant | Pinned to | How |
|---|---|---|
| export loop: settle 45 s, deadband 150 W, gain 0.5, step 1000 W, round 100 W, floor 500 W, 120 writes a lease, feed-forward start 2000 W, response samples 3, response margin 100 W, wrong direction 300 W, recovery hold 60 s and one attempt, grid and SOC stale 90 s, runaway margin 750 W / 3 samples / 30 s grace, transition window 30 s, DC allowance 12 percent, absolute backstop 750 W / 2 samples / 3000 W floor, export trip 500 W / 100 W, reboot timeout 15 min, setpoint bound 8000 W | `firmware/ecco_clock_dongle_stage3_4_free_power.yaml` (the substitutions block) | parsed; each value compared |
| the 15 s guard tick and the 1 s export trip | the same file's `interval:` blocks | the block that runs `dump_controller_tick` and the one that acts on `dump_export_trip` |
| the loop law and the Stop SOC rule (`reading <= latched stop` ends the lease) | the same file's `dump_controller_tick` and watchdog text | the lines the model copies must still be present |
| charge: step 100 W, minimum 500 W, dwell 30 min, 6 changes, decrease hysteresis 500 W, slack 15 min, pessimistic efficiency 0.90, capacity band 6 %, scale error 3 %, SOC resolution and noise, knee 90 %, tail 0.125, drop 5 min, demand margin 20 %, efficiency maximum 0.97, buffer 60 min, the 500 W and 8000 W limits | `frontend/ecco-plan-core/src/gentleNight.ts` (`DEFAULT_NIGHT_PARAMS`, the buffer default) and `settings.ts` | parsed; each value compared |
| the feasibility maths (plateau, knee, fall, tail, the lowest feasible rate) | the planner's golden probe `frontend/ecco-plan-core/test/gentleNightProbe.golden.json` | the Python port reproduces the planner's needed rate, its feasibility and its pessimistic finish for cases A, A60, B, C, C93, D (charging past the knee), E and F, without Node |
| GRC budgets: 10 writes a night with 4 reserved for restores, largest step 2000 W, change under 300 W refused and 600 W against the last direction, plan lost after 20 min, lease ends 10 min before the slot end, gain 50 to 150 percent, second weak response ends it, a running charge of 1000 W needed, runaway 115 percent + 500 W | the guarded charge-rate controller design (GRC SPEC revision 3, section 5; branch `dev/gentle-rate-controller`) | **ASSERTED VALUES, not a live pin**: that design is not in this tree. The numbers are vendored in [grc_core_constants.txt](grc_core_constants.txt) with the source commit named (struct Config of `ecco_gentle_rate_core.h` at `ec90232`), the self-check compares the kernel with that file and, only where that commit is present in the clone, the file with the header; elsewhere that second check is skipped. The planner states the same dwell and change count and IS parsed |
| the ASSUMED kernel constants (the 90 s control bound as one number, the 45 s hold on a stale reading, the 5 percent import margin, the 30 minute house peak and its 5 minute mean, the NTP age bound, the 120 s reaction bound, the progress tracker's 30 min / 8 points / 7 percent) | nothing: they are listed in `kernel.py` under ASSUMED | not pinned; each is a named constant a later review can change |

## Where the kernel deliberately differs from the GRC design

The kernel mirrors the GRC's budgets, not its code. The differences, each also listed in the header of `kernel.py` and checked there by the
self-check: (1) the GRC counts the START write in `max_changes` ("START write included"), the kernel's `changes` excludes it, with the same
behaviour because the 10 write night budget (4 reserved for restores) binds first; (2) the GRC's target guard derates the REALISED power
(85 percent, a 25 percent tail, the knee at most 95), the kernel's asks the planner's pessimistic world; (3) the GRC judges a change on four
response frames, the kernel on one; (4) the week (42) and life (4000) write ceilings are not modelled; (5) the golden-vector check rebuilds
the planner's "knee may be passed" with a setpointOvershoot 1.1 term that `charge_progress` does not use; (6) the planner's `chargeEffMax`
is pinned to the planner and not used.

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
| IMPORT_CEILING | with an import ceiling configured, ECCO answers for every breach (grid import over the ceiling, charger drawing, house alone under it) that began while it held a session, before its first one, between two, or within two ticks after its last END, and keeps answering until the import falls: at most the dongle's guard reaction while a session is open (3 ticks plus one per 2000 W step the peak excess needs, plus the longest telemetry gap), the declared reaction before a session, NOTHING after the last END (the restore is ECCO's write: finding F01), at most as many episodes as the night has exogenous causes plus one, and no episode opened by ECCO's own start or change raising the charge power |
| POWER_CEILING | every setpoint written is inside 500 W and the ceiling and, for a lease, never above the pre-session value; and with a Gentle session open the setpoint IN FORCE stays above a lowered Power Ceiling for no longer than a plan period plus the command |
| BUDGETS | dwell, change count, write count (charge), settle and write count (export) are never exceeded, and the dongle never has to refuse a request |
| REACHES_OR_REPORTS | the SOC reading reached the target by the deadline, or 'unreachable' was reported at least 15 minutes before it |
| REACHES_DEADLINE | (Gentle) reaching is judged on its own and a report never excuses a miss: on a night that today's fixed rate would reach 30 minutes before the deadline (and the import ceiling does not bind, the owner did not lower the Power Ceiling, the plant is inside the declared envelope) the session reaches the target by the deadline too |
| REPORT_JUSTIFIED | every 'unreachable' report is asked of the REFERENCE kernel again on the very inputs it was decided on; a report it does not stand behind is a false alarm (the cry-wolf that used to pass REACHES_OR_REPORTS); the sweep also counts false alarms on nights that reach with 30 minutes to spare against a stated 10 percent bound |
| NEVER_WORSE_THAN_TODAY | (Gentle, REQ-A12) the same night is run beside it with no ECCO at all; whenever today's fixed rate reaches the target 25 minutes before the window end, the Gentle night reaches it by the window end (strict everywhere; the SWEEP counts, and does not fail on, the one night class the design itself ranks lower: today's rate would breach the owner's import ceiling, and a hard ceiling outranks it, finding 4 below) |
| NO_UNTRUSTED_ACTUATION | no start, change or loop write while the clock it depends on is untrusted |
| NO_REWRITE | no setpoint write repeats the value already in force (a saturated loop that rewrites the same ceiling spends the flash-wear budget on nothing) |
| NO_STALE_DRIVE | no plan-driven change (a raise or a lowering from the plan, not a safety reduction) is decided on a frame older than 45 s (STALE_HOLD_S): an old reading may end a session, never drive a change |
| COMMAND_FOLLOWED | (export) the measured battery power stays within the ordinary runaway bound of the command in force (the higher of the last three commands, command + max(command / 2, 750 W)) for no longer than the lease-start grace, the guard's consecutive samples and two ticks of slack: judged on the plant, so it fails when the measured-power guard is missing |
| ONE_WRITER | **bench sanity check, not a controller property**: at most one lease at a time and every write belongs to the lease that is open (the dongle model's own arbiter enforces it; no kernel edit can break it, so `g31` and `e19` test the bench's arbiter, and only the bench mutants of the self-check can fail it) |
| EXPLAINED | every decision has a reason from the closed list, a detail from its list and a complete sentence |
| RESTORED_OR_ALERTED | at the end no lowered or overriding value is left silently: the owner's values are back or an alert was raised |
| PHYSICAL | **plant sanity check, not a controller property**: the battery stays between 0 and 100 percent and every number is finite (the plant clamps the stored energy, so it cannot fail unless the plant is edited) |

### Scenarios

The catalogue (generated, `run_sim.py --counts`): <!-- counts:begin -->82 scenarios: 50 Gentle, 4 Charge Fixed, 28 Export; 16 invariants (2 of them bench or plant sanity checks)<!-- counts:end -->.

Generated from `scenarios.SPECS` (`run_sim.py --covers`); the self-check fails if this table and the code differ, and if the
`Covered by` column of [../REQUIREMENTS.md](../REQUIREMENTS.md) does not name the same pairs.

<!-- covers:begin -->
| Scenario | Policy | What it does | Requirements (REQUIREMENTS.md) |
|---|---|---|---|
| `g01_nominal` | gentle | Nominal night: 25 to 90 percent, light house load; the lowest practical rate, re-planned from the measured SOC. | REQ-A1, REQ-A2, REQ-A5, REQ-A8, REQ-A12, REQ-B2, REQ-B4, REQ-B7, REQ-B8, REQ-B10, REQ-B11, REQ-C9 |
| `g02_heavy_overnight_load` | gentle | A heavy overnight house load (4.5 kW for 90 minutes) with no import ceiling: the grid carries it, progress is unaffected, so the rate is held. | REQ-A3, REQ-A10, REQ-B5 |
| `g03_heavy_load_import_ceiling` | gentle | The same load with an 11 kW import ceiling: import would pass it, so the setpoint is lowered at once; the ceiling leaves too little for the target, which is reported unreachable for the import headroom from 6000 s (16 reports) and at risk later (11). | REQ-A4, REQ-A7, REQ-A9, REQ-B5, REQ-C10, REQ-D2 |
| `g03b_restore_into_breach` | gentle | FINDING F01 (the review's variant of g03): the house load ramps up to 6 kW and stays; the lease holds the 11 kW import ceiling for hours, ends at its deadline and the restore writes the owner's 8000 W into a 14.98 kW import for the last 14 minutes of the window. The restore is ECCO's write, so the breach is ECCO's; the design does not yet say what an end should write into a known breach. | REQ-A4, REQ-C10, REQ-D2 |
| `g04_load_removal` | gentle | A heavy load for 30 minutes then sudden removal, with an import ceiling: the forced reduction is undone only after the dwell and hysteresis. | REQ-A6, REQ-A10 |
| `g05_kettle_spikes` | gentle | Bursts of 3 kW for 7 minutes every 25 minutes (off the plan grid, so the planner sees each at one plan tick) under a binding 11 kW import ceiling: the planner lowers the rate once and then plans on the half-hour peak, so the later bursts cause no further change and the dongle's guard never has to act; a planner that forgot the peak would change the rate after every burst. | REQ-A6 |
| `g06_high_start_soc` | gentle | High starting SOC: 80 to 95 percent, so the plan is gentle and short. | REQ-A5, REQ-A10 |
| `g07_low_start_soc_tight` | gentle | Low starting SOC and a short window: 8 to 100 percent in four hours cannot make a 60 minute buffer; 'unreachable' is said at the first plan tick. | REQ-A9, REQ-A10, REQ-B8 |
| `g08_efficiency_drop` | gentle | Charging efficiency falls from 0.945 to 0.70 after 30 minutes: the SOC lags the pessimistic projection, the progress tracker flags it, so the plan sees the real shortfall at once and raises by a large step at the first change the 30 minute dwell allows (about 70 minutes in); without the tracker the raises come late and small and the night misses its deadline. | REQ-A3, REQ-A4, REQ-A10 |
| `g09_efficiency_gain` | gentle | Efficiency better than assumed (0.97) and a smaller battery (30 kWh): ahead of the plan, the rate is lowered. | REQ-A5, REQ-A10 |
| `g10_taper_cliff_98` | gentle | Charge to 100 percent through the measured plateau, the cliff at 98 percent and the trickle: the planner's pessimistic knee (90) makes it say 'unreachable' (deadline) 26 times from the first plan tick at 300 s, and 'at risk' once, where the real knee (98) lets the night reach: conservative about the knee, NOT about the tail (finding F06, g36). | REQ-A7, REQ-A12 |
| `g36_slow_tail_outside_the_world` | gentle | FINDING F06 (the review's night, sweep seed 4395984): a plant with its knee at 94.5 percent and a 357 W trickle, a 100 percent target and a heavy house: at the first plan tick the kernel says 'Starting at 8000 W: the lowest rate that still reaches 100%' (the world's trickle is 1.0 kW), the plant needs 17 minutes more than the world says, the deadline is missed and the miss is reported early by the target guard's hand-back; the planner's tail fraction is the planner owner's to review. | REQ-A9, REQ-A12 |
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
| `g20_telemetry_short_gap` | gentle | A 75 second telemetry gap that straddles a plan tick (the plan sees a frame 90 s old, under the 90 second bound): nothing stops, and the plan holds instead of deciding on stale data. | REQ-B3 |
| `g20b_stale_frame_while_a_raise_is_due` | gentle | The first raise of a lagging night is due at the 4200 s plan tick, but the frame the plan sees is 90 s old: the plan holds (stale_short) and raises at the next tick on a fresh frame, never on the old one. | REQ-B3, REQ-A3 |
| `g21_telemetry_long_gap` | gentle | A 5 minute telemetry gap: beyond the bound the lease ends and today's rate takes over. | REQ-B3, REQ-B9 |
| `g22_soc_unavailable_at_start` | gentle | No telemetry for the first 12 minutes: nothing is started on missing data. | REQ-B3 |
| `g22b_start_arrives_after_telemetry_loss` | gentle | The plan starts a session on fresh data, the start command takes 90 seconds, and the telemetry stops just after it was sent: when it arrives the dongle's own frame is older than the 90 s bound and it refuses; nothing is written on data it cannot see. | REQ-B3, REQ-B22 |
| `g23_restart_in_lease` | gentle | The dongle restarts in the middle of the lease: the snapshot is restored at boot and the lease is never resumed. | REQ-B9, REQ-B22, REQ-C7, REQ-C12 |
| `g24_dead_dongle_charge` | gentle | The dongle dies for good during the lease: no guard runs, the lowered value stays; the owner is alerted. (The backstop is the alert and the after-window check.) | REQ-D4 |
| `g25_ha_outage` | gentle | Home Assistant is gone for an hour: after 15 minutes without an API client the dongle restarts, which restores the lease. | REQ-B9, REQ-C7, REQ-D4 |
| `g26_plan_lost` | gentle | Home Assistant stays connected but stops handing over plans: after 20 minutes the lease ends (plan lost). | REQ-B9, REQ-C7 |
| `g27_rtc_untrusted_mid_lease` | gentle | The inverter clock becomes untrusted mid-lease: time-dependent actuation fails safe, the lease ends, nothing is raised. | REQ-D1, REQ-B21 |
| `g27b_stale_and_untrusted_together` | gentle | The telemetry goes stale and the inverter clock becomes untrusted on the same tick: the guard order decides, and time comes before staleness. | REQ-B21, REQ-D1 |
| `g28_rtc_untrusted_at_start` | gentle | The inverter clock is untrusted for the first 15 minutes: no start until it is trusted. | REQ-D1, REQ-B21 |
| `g28b_start_arrives_after_the_clock_is_untrusted` | gentle | The plan starts a session while the inverter clock is trusted, the start command takes 90 seconds and the clock becomes untrusted on the way: the dongle's own check refuses the start, and nothing time-dependent is written. | REQ-D1, REQ-B21 |
| `g29b_start_arrives_after_grid_loss` | gentle | The plan starts a session on a live grid, the start command takes 90 seconds and the grid is lost on the way: the dongle refuses the start and nothing is written while the grid is down. | REQ-B21, REQ-D7 |
| `g29_grid_loss_in_lease` | gentle | Grid lost mid-lease (and a lowered slot may cap the battery off grid): the lease ends first and the original value is restored at once. | REQ-B21, REQ-D7 |
| `g30_import_ceiling_drop` | gentle | The owner's import ceiling is applied mid-lease (9 kW) with 2 kW of house load: the forced reduction does not wait for the dwell. FINDING F01: when the lease ends at the target the restore writes the owner's 8000 W back and the import stays over the ceiling until the inverter's own slot target stops the charge. | REQ-B21, REQ-C10, REQ-D2 |
| `g30b_breach_inside_the_dwell` | gentle | A heavy load arrives 10 minutes into the lease, inside the 30 minute dwell after the start write, under an 11 kW import ceiling: the forced reduction does not wait for the dwell, and neither the session nor the owner's import is left to the restore. | REQ-B21, REQ-C10, REQ-D2 |
| `g35_power_ceiling_lowered` | gentle | The owner lowers the Power Ceiling to 4000 W mid-lease (the setpoint in force is 6300 W): the plan's forced reduction takes the setpoint to the new ceiling within one plan period and every later write stays under it; the shortfall that follows is reported. | REQ-A7, REQ-C10, REQ-B21 |
| `g31_two_policies` | gentle | Another controller tries to start an export while the Gentle lease owns the setpoint: refused, one writer per setting. | REQ-B19, REQ-B20, REQ-C11 |
| `g32_hold_pressed_charge` | gentle | The owner presses Hold mid-lease: the session ends, the pre-session values are back, nothing restarts while Hold is on. | REQ-C12, REQ-B21 |
| `g35b_power_ceiling_lowered_inside_the_dwell` | gentle | The owner lowers the Power Ceiling to 4000 W 11 minutes into the lease, inside the 30 minute dwell after the start write: the lowering is a safety reduction, so the dwell does not hold it back and the setpoint is at the ceiling within one plan period. | REQ-B21, REQ-C10 |
| `g36b_charger_runs_away_mid_lease` | gentle | The inverter stops following the setpoint with no write to blame (the charge response turns unbound at 50 minutes): the realised AC power sits at its 8.98 kW cap against a 6300 W setpoint, past the runaway bound of 115 percent plus 500 W; only the dongle's measured-power guard can see it, and it ends the lease. | REQ-D3 |
| `g33_plan_catches_up_alone` | gentle | The real battery is far larger than the plan (46 kWh against 35): the plan falls behind, raises the rate itself to today's and reaches the target in good time; the target guard has nothing to do and stays quiet. | REQ-A12 |
| `g34_target_guard_hands_back` | gentle | The never-worse target guard decides the night: the charging efficiency collapses to 0.50 at 90 minutes on a 38 kWh battery; the raises are slower than the collapse, so the guard hands the charge back to today's rate at 9015 s and today's rate reaches the target by the window end (a controller without the guard misses it). The target is reported at risk, never lowered. | REQ-A9, REQ-A12, REQ-B21 |
| `g34b_target_guard_reports_missed_target` | gentle | The hand-back that cannot save the night: a 40 kWh battery, efficiency 0.55 from 90 minutes. The guard ends the lease at 8415 s, today's rate does not reach the target either, and the miss is REPORTED (before the end of the lease and again by the watch that goes on after it), never silent. | REQ-A9, REQ-A12 |
| `g21b_stale_end_then_collapse` | gentle | The lease ends on a 5 minute telemetry gap, then the charging efficiency collapses to 0.40: today's rate is back and the plan can no longer write (one lease a night), but it keeps watching and reports that the target will be missed. | REQ-A9, REQ-B3, REQ-B9 |
| `g23b_restart_then_collapse` | gentle | The dongle restarts mid-lease (the lease is restored, never resumed), then the charging efficiency collapses to 0.40: the plan watches the rate in force and reports the miss. | REQ-A9, REQ-B9 |
| `g26b_plan_lost_then_collapse` | gentle | Home Assistant stops handing over plans (the lease ends after 20 minutes) and the charging efficiency collapses to 0.40: the hand-over is stopped, the judging is not, and the miss is still reported. | REQ-A9, REQ-B9 |
| `f01_fixed_nominal` | charge_fixed | Charge Fixed at 8 kW from 30 to 90 percent: one rate, ended at the target (two writes: start and restore). | REQ-B2, REQ-B11, REQ-B12 |
| `f02_fixed_import_breach` | charge_fixed | Charge Fixed with an 11 kW import ceiling and a 4 kW house load: import would pass it, so the session ends at once; a later start uses the headroom rate. | REQ-B12, REQ-C10, REQ-D2 |
| `f04_fixed_power_ceiling_lowered` | charge_fixed | FINDING F14 (found while closing the review, not in it): the owner lowers the Power Ceiling to 4000 W while a Charge Fixed session runs at 8000 W. A fixed-rate session can only be ended, and no guard ends it for this, so it goes on at the old rate until its target: the lowered ceiling is not honoured by the session. | REQ-C10 |
| `f03_fixed_unreachable` | charge_fixed | Charge Fixed at only 2 kW from 10 to 100 percent: the start says at once that this rate cannot make the target. | REQ-A9, REQ-B8 |
| `e01_nominal` | export | Nominal export: 2 kW net export from 80 percent, house 1 kW, no solar; the loop settles inside the deadband and the lease ends at its planned end. | REQ-B2, REQ-B13, REQ-B14, REQ-C9 |
| `e02_house_step_up` | export | House load jumps from 1 to 3.5 kW with a 6 kW ceiling (a closed loop above 3000 W is NOT hardware-proven, the firmware's proven ceiling is 3000 W): the ceiling is raised in 1 kW steps at least 45 s apart and the export recovers. | REQ-B5, REQ-B13, REQ-B16 |
| `e02b_house_step_infeasible` | export | The same step with the proven 3 kW ceiling: the target is infeasible high, said plainly; the export is never forced by importing. | REQ-B13, REQ-B16 |
| `e03_house_step_down` | export | House load falls from 3 kW to 0.5 kW with a 6 kW ceiling (a closed loop above 3000 W is NOT hardware-proven, the firmware's proven ceiling is 3000 W): the export jumps, the loop steps the ceiling down by at most 1 kW per 45 s and returns inside the band. | REQ-B13 |
| `e04_kettle_spikes` | export | Kettle-sized bursts (3 kW for 2 minutes): settle and deadband keep the number of writes small. | REQ-B7, REQ-B13 |
| `e05_pv_cloud` | export | Solar drops from 1.5 kW to 0.3 kW for ten minutes: the loop follows the measured grid, never a forecast. | REQ-B13, REQ-B15 |
| `e06_pv_evening_drop` | export | Solar falls away to nothing over 90 minutes: the energy plan credited no solar, the floor (not the duration) is the safety, the SOC stays above it. | REQ-B14, REQ-B15 |
| `e07_infeasible_low` | export | Solar alone (3.5 kW) already exports more than the 1 kW target: nothing is started, the plan says so, the battery is never charged to absorb it. | REQ-B13, REQ-B15, REQ-B16 |
| `e07b_pv_rises_during_export` | export | Solar rises during a running export: the ceiling falls to the 500 W floor and no further, the export is reported infeasible low, the battery never charges. | REQ-B13, REQ-B15, REQ-B16 |
| `e08_stale_grid_gap` | export | A 3 minute telemetry gap during the lease: past 90 seconds the lease fails closed and is restored. | REQ-B3, REQ-B9 |
| `e09_stop_soc_reached` | export | A rising house load drains the battery faster than planned, with a 5 kW ceiling (a closed loop above 3000 W is NOT hardware-proven, the firmware's proven ceiling is 3000 W): the Stop SOC (staged above the effective reserve) ends the lease before the reserve. | REQ-B14 |
| `e10_reserve_rises` | export | The effective reserve rises from 20 to 60 percent during the export: Home Assistant asks for a raise-only Stop SOC and the lease ends above the new reserve. | REQ-B14, REQ-B21 |
| `e10b_reserve_above_soc` | export | The reserve jumps above the battery's own SOC: the discharge stops within the declared reaction time. | REQ-B14, REQ-B21 |
| `e10c_reserve_rise_then_ha_outage` | export | The reserve rises to 64 percent, Home Assistant relays the raise-only Stop SOC and then goes down for good: the dongle alone ends the export at the raised floor, above the new reserve (its own Stop SOC is the only floor left). | REQ-B14, REQ-B21, REQ-D4 |
| `e11_hold_pressed` | export | The owner presses Hold during the export: Home Assistant ends the session within a plan tick and the pre-session values are restored. | REQ-B21, REQ-C12 |
| `e11b_hold_end_command_lost` | export | Hold is pressed and the first End command is lost in transit: Home Assistant sends it again at the next plan tick and the session still ends. | REQ-B22, REQ-C12 |
| `e12_restart_in_lease` | export | The dongle restarts during the export: the lease is ended and restored at boot, never resumed. | REQ-B9, REQ-B22, REQ-C7 |
| `e13_dead_dongle` | export | The dongle dies mid-export: no firmware guard runs, the last ceiling stays in force, ECCO's reserve is NOT protected. The backstops are the inverter's own shutdown SOC and the owner alert. | REQ-D4 |
| `e14_unit_wrong_x10` | export | Export unit wrong by 10x with no Max Grid Export set: the measured-power guard ends the lease within a few samples. | REQ-B18, REQ-D3 |
| `e15_runaway_anomaly` | export | The 22 Sept 2026 anomaly: the battery ignores its ceiling mid-lease. The runaway guard ends the lease. | REQ-D3 |
| `e15b_runaway_between_thresholds` | export | The battery ignores a 500 W ceiling and gives 2.6 kW: above the ordinary runaway bound (1250 W) and under the absolute backstop (3750 W), so only the ordinary measured-power guard can end the lease, and it does within its samples. | REQ-D3 |
| `e21_pv_is_not_credited_in_the_duration` | export | 1.5 kW of measured solar while the export starts: the loop uses it (the export needs less from the battery), the planned duration does NOT (it is sized from house + target alone), so the lease is planned to end at about 6300 s, not at the 20000 s the credited solar would give. | REQ-B15 |
| `e22_healthy_export_across_a_step_down_and_a_gap` | export | The review's night (sweep seed 23076789): a healthy export whose ceiling is stepped down while the battery is still at the old level and whose telemetry then has a 45 s gap. The first version of the guard counted one 4.7 kW reading twice and ended the healthy lease 'runaway'; the guard counts each NEW reading once and compares with the higher of the old and the new ceiling for 30 s after the write, so the lease runs to its planned end. | REQ-D3, REQ-B13 |
| `e16_export_time_untrusted` | export | The dongle's NTP time is untrusted for the first 10 minutes: no start until it is trusted. | REQ-D1, REQ-B21 |
| `e17_grid_loss_export` | export | Grid lost during the export: the session ends first and the pre-session values are restored. | REQ-B21 |
| `e18_export_over_limit` | export | The house load falls away under a 2.5 kW Max Grid Export with a 6 kW ceiling (a closed loop above 3000 W is NOT hardware-proven, the firmware's proven ceiling is 3000 W): one sample far over ends the lease at once. | REQ-B21, REQ-C10 |
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
3. **A configured import ceiling is only enforced while ECCO holds the session, and the END restores into whatever the import is: FINDING F01**
   (`g03b_restore_into_breach`, `g30_import_ceiling_drop`; pinned, see "Pinned findings"). With no lease the owner's own table charges at the
   owner's own rate; the kernel starts a session only to lower it (the safety start of `plan_gentle`), so the reaction before a session is
   the plan period plus the command and one dongle tick (about 5 to 10 minutes in the sweep), a soft gate. A firmware import guard (N6)
   would cut that to one tick. When the session ENDS (deadline, target, stale telemetry, plan lost, restart, Hold, grid loss) the restore
   writes the owner's pre-session value back (REQ-C12: the exact value, never a computed one), and if the house load is such that this rate
   breaches the owner's ceiling the breach is ECCO's: the restore is its write. The first version of this simulator did not count it; the
   independent review did (F01), and the invariant now counts it until the import falls. In `g03b` the lease holds an 11 kW ceiling for
   hours and the restore at the deadline writes 8000 W into a 14.98 kW import for the last 14 minutes of the window; in `g30` the
   restore at the target leaves 75 s over a 9 kW ceiling until the inverter's own slot target stops the charge; the sweep meets it in
   about 2 percent of the Gentle nights with a ceiling. The kernel is NOT changed to hide it: the options are (a) an END restores
   min(original, headroom) (then the owner's table is lowered after the session: a deviation from REQ-C12's exact restore and a new
   write-ownership question), or (b) the owner accepts that the ceiling ends with the session and the plan says so. That is an owner
   decision (listed in the review hand-over); until it is taken the finding stays pinned.
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

## Pinned findings (defects of the design the bench found)

A scenario may declare `known_finding=((invariant, id, reason),)` in `scenarios.py`: that invariant MUST fail, exactly with the pinned
failure class and no other, and `run_sim.py` prints FINDING for the row. `run_sim.py` exits 0 only when the set of failing (scenario,
invariant) pairs equals the set the catalogue pins (documented gaps and findings), so a fix flips its pin red (the pin must then be
removed) and any NEW failure fails as well. A finding is not a documented physical gap (`known_gap`, a dead dongle: a backstop applies);
it is a place where the design as written does the wrong thing and an owner decision is open.

| Id | Scenarios | What | Open decision |
|---|---|---|---|
| F01 | `g03b_restore_into_breach`, `g30_import_ceiling_drop` (and about 2 percent of the sweep's Gentle nights with a ceiling) | the END of a session restores the owner's pre-session value into a house load that puts it over the owner's import ceiling; the breach lasts until the owner's own table stops charging | an END restores min(original, headroom), or the owner accepts that the ceiling ends with the session |
| F14 | `f04_fixed_power_ceiling_lowered` | found while closing the review (not in it): a Power Ceiling lowered while a Charge Fixed session runs is not honoured: a fixed-rate session can only be ended and no guard ends it for this | whether the session ends, or is re-written at the ceiling, when the owner lowers the Power Ceiling |
| F06 | a pinned number in the self-check (255 against 272 minutes), `g36_slow_tail_outside_the_world` | the planner's tail fraction (0.125) is more optimistic than the measured trickle (7 percent) for a plant with an early knee and a slow trickle; the planner's knee (90) over-corrects for the others | the planner owner: tailFraction and kneeSocPct (not edited here) |

## The independent review of this folder (N4, round 1): where each finding is closed

The first version of this simulator was reviewed independently (13 findings, 7 major) and changed; nothing below widens what the simulator
claims, each change makes it catch more.

| Finding | What it was | Where it is closed |
|---|---|---|
| F01 | the import-ceiling invariant did not count a breach the END's restore causes, and its in-session bound was loose | `import_analysis`: attribution to ECCO until the import falls, the dongle's guard bound, nothing after the last END, the number of episodes, no own raise; the restore case is the pinned finding F01 (`g03b`, `g30`) |
| F02 | after an early Gentle lease end a missed target was never reported | `kernel.plan_watch` (report only, after any end and while the plan hand-over is stopped), the target guard's stop says "at risk"; `g21b`, `g23b`, `g26b`, `g34b` |
| F03 | the never-worse target guard was never exercised | `g34` (the hand-back decides the night), `g33` renamed `g33_plan_catches_up_alone`, boundary units for the guard |
| F04 | seven bug classes no scenario, invariant or sweep run caught | invariants NO_REWRITE, NO_STALE_DRIVE, COMMAND_FOLLOWED and the Power Ceiling state check; scenarios `g20b`, `g30b`, `g35`, `e10c`, `e15b`, `f02` |
| F05 | vacuous scenarios | `g05` (bursts the planner sees, a binding ceiling), `g20` (a gap across a plan tick), `g08` (the tracker's effect), ONE_WRITER and PHYSICAL labelled as sanity checks |
| F06 | the sweep's envelope claim was false, the central unknown never drawn | `envelope_problems`, a generator that draws the gentle-rate knee and trickle and asserts every draw, `top_rate_threshold` as a parameter, the measured-trickle sweep, the planner finding F06 |
| F07 | any early report passed | REACHES_DEADLINE, REPORT_JUSTIFIED (replayed on the reference kernel), the sweep's false-alarm bound |
| F08 | the runaway model counted stale readings and lacked the firmware's rules | per-sample counting, one start grace, the transition window, the 12 percent DC allowance and the fence, pinned to the firmware text; `e22` |
| F09 | calibration claims that overstated the evidence | the trickle is 2 of 4 nights, `tau_discharge_s` is ASSUMED, `fp_dc_per_request` is 0.97 W/W (0.94 is the current ratio), the cliff bound is 2.5 to 4.8 minutes |
| F10 | undecided plant behaviour hard-coded without a flag | `slot_target_stops_charge` (R1), `top_rate_threshold`, `cliff_shape`, and the charge scenarios run once with R1 false |
| F11 | the GRC "pins" compared the kernel with itself | `grc_core_constants.txt` (asserted values with their source commit), the differences listed |
| F12 | the bench was never mutated; survivors among the kernel mutants | 21 bench mutants (each killed), the review's kernel mutants added, named scenario and sweep killers |
| F13 | claims the runs did not support | the counts are generated, the g03, g10 and g33 statements corrected, the Covered-by pointers of REQ-A6, B2, B6, B15 and A12 repaired, closed loops above 3000 W flagged as not hardware-proven |

## What this does not prove

* **It is not the inverter.** Every behaviour of the plant that is not MEASURED_REPLAY or VERIFIED_LIVE in the table above is a choice. The
  charge response below the top rate, the knee and tail at gentle rates, the off-grid effect of a lowered slot power (proof rung R3), the
  meaning and unit of the setpoint, flash wear, the BMS limits and derating, usable capacity, the import limit of the installation and the
  22 Sept 2026 anomaly's cause remain NOT ESTABLISHED. A kernel that passes here still needs rungs R3 to R10 of the live-proof ladder.
* **The dongle and Home Assistant are models.** The Dump loop is modelled from the firmware source; the charge lease from the GRC design (a
  design, not firmware); the one-owner arbiter, the raise-only Stop SOC, the import guard and the plan hand-over are the proposed N6 behaviour.
  Nothing here shows the firmware does, or will do, any of this. The bench's tick is 15 s and its telemetry arrives once a tick (the real
  cadence is 10 s); the write latency is one tick.
* **The invariants are bounded claims.** The sweep draws plants inside the declared envelope of the pessimistic world
  (`scenarios.envelope_problems`: capacity within the band the world adds, efficiency not below 0.90, knee at or above 90 percent, the
  top-rate AND the gentle-rate knee and trickle drawn, and when the target lies above the knee a trickle not slower than the world's;
  exogenous events in the first 40 percent of the window), and the generator ASSERTS that every draw is inside it. Outside it a scenario
  shows what is reported and when, and the guarantee is what the projection can see, not "reached". The SOC reading, with its one-point
  resolution, is the unit of "reached" and of the reserve floor; a sensor scale error outside the planner's band is not modelled for exports.
* **The planner's world is NOT pessimistic about the tail: finding F06, for the planner owner (the planner is not edited here).** The
  world's trickle after the knee is `tailFraction` 0.125 of the rate (1.0 kW DC at the top rate); the measured trickle is 0.55 to 0.65 kW on
  8.5 kW, 7 percent. For a plant with its knee at 94.5 percent and a 357 W trickle (the review's night) the world says 255 minutes from 80 to
  100 percent at the top rate and the plant needs 272; the kernel then says "Starting at 8000 W: the lowest rate that still reaches 100%".
  The claim "the plan is conservative and never optimistic" that an earlier version of `g10` and this file made is therefore WRONG as a
  general statement; it holds for the knee (the world assumes 90 percent, the measured knee is 98) and not for the tail. The two errors point
  opposite ways: for a 95 or 100 percent target the world's knee makes 'at risk' the normal word (about 55 and 97 percent of the nights that
  reach with a margin carry a report), while below the knee the false alarms are 0 to 9 percent (the sweep bound is 10 percent, measured about
  5). The sweep with the measured knee and trickle (outside the envelope) holds the same invariants and misses no night without a report (12000
  runs over four base seeds), because that pessimism and the hand-back absorb it; the finding is a margin, pinned in the self-check by the 255 against 272 minutes, and it flips the day the planner's tail
  is fixed.
* **The feasibility guarantee has two halves, judged apart.** REACHES_DEADLINE: on a night today's fixed rate would reach 30 minutes before the
  deadline (and the import ceiling does not bind, the owner did not lower the Power Ceiling, the plant is inside the envelope) the session
  must reach it; a report never excuses a miss. REPORT_JUSTIFIED: every "unreachable" report is asked of the reference kernel again on the same
  inputs, so a controller that cries wolf at every start (the review's BI12b) fails, and the sweep counts false alarms against the bound above.
* **Mutants test the kernel's tests, not the kernel's correctness.** The mutants are single-line in-memory edits of `kernel.py`; killing all
  of them shows the suite notices those edits, not that no other defect exists. Measured when this was written: the unit tables and the
  scenarios together kill all 103 kernel mutants and all 22 bench mutants; the scenarios alone kill 52 of the kernel's (the rest are boundary edits, one epsilon or one count,
  that a whole night does not resolve), and the mutants of each class the review named (a dwell that a forced reduction waits for, a guard
  that never trips, a stale frame that drives a change, a lowered ceiling that is ignored, a missing measured-power guard, a double write, a
  tracker that is never used, smoothing that is missing, a restart at the full rate into a breach) die in a NAMED scenario or in the sweep on
  their own (`SCENARIO_KILLERS`, `SWEEP_KILLERS` in the self-check): a scenario is an end-to-end witness, the tables are the sharp instrument.
* **Three open items stay with the owner.** The installation's grid import limit (a value only the owner can supply; the plan runs "none
  applied" and says so), the Q8 decision for the interlock, and the unattended-export approval; this folder decides none of them.
