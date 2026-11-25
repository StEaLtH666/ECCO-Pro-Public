# Dynamic energy control: the shared foundation (design phase)

Status: **offline design and analysis only, 25 Nov 2026.** Nothing in this folder is wired into the firmware or Home Assistant;
nothing has been flashed, installed or written to an inverter; no live proof exists; Intelligence stays SHADOW. Every live step
named here needs the owner's own separate authorisation.

This folder answers the owner's three requirement messages of 25 Nov 2026: a Gentle Smart Charging closed loop that copes with
household loads (A), one shared closed-loop framework for Gentle Charging, Charge Battery / Free Power and Export to Grid / Dump to
Grid (B), working through the inverter's own TOU controls and import/export limits wherever a verified path exists (C).

| File | What it is |
|---|---|
| [REQUIREMENTS.md](REQUIREMENTS.md) | every statement of the three messages as a numbered, testable requirement (REQ-A, REQ-B, REQ-C), the derived safety requirements (REQ-D), each with its verification method and an empty "covered by" column for traceability |
| [CONTROL_AUTHORITY.md](CONTROL_AUTHORITY.md) | what each Deye / dongle setpoint and limit actually controls, graded by evidence; the six questions of message C; the coordinator's starting facts re-measured; write frequency and wear |
| [ACTUATOR_PATHS.md](ACTUATOR_PATHS.md) | who owns what today, the proposed authority model, the candidate actuator paths, the ranking and recommendation per mode, restore and manual mode, and the read-only-first live-proof ladder |
| [evidence_replay.py](evidence_replay.py) | the offline replay used for the measured numbers; it prints aggregates only |

## What the evidence says, in five lines

1. Export: a slot power is a ceiling on the inverter's AC output from the battery (held from 500 to 7000 W, 7.89 kW at 8000 W);
   the grid receives that minus the house. VERIFIED_LIVE.
2. Charge at the top rate: the inverter held its own AC input at a constant 8.98 kW with the slot at 8000 W; the battery took
   8.36-8.58 kW; the grid supplied the house on top (9.6-10.4 kW). What sets 8.98 kW is not established.
3. Free Power: register 230 (amps) bound the charge, not the slot power; the house rose to 5.5 kW and grid import reached 12.46 kW
   without the charge changing. So the inverter does not protect the supply: ECCO must enforce any grid import limit.
4. A ceiling was once ignored (8.6 kW against 1000 W, 22 Sept 2026): measured-power guards are mandatory.
5. Write endurance is not established; the existing controllers write at most once per 45 s and 120 times a lease.

## The recommendation, in three lines

- **Gentle:** one planned fixed rate a night through the existing editor first; then the guarded charge-rate controller (one
  register, the active slot's power, under a firmware lease), once the off-grid and setpoint-meaning proofs are done.
- **Charge Battery / Free Power:** the existing lease at a rate chosen at START from measured headroom, ended early; later, rate
  steps owned by the Free Power transaction itself.
- **Export:** the existing Dump to Grid closed loop, with an energy objective, reserve-aware feasibility, a raise-only Stop SOC and
  a firmware gate on the dongle's Start button added by the shared framework.

## Relation to existing work

- The guarded charge-rate controller (GRC) design, reference model and proofs: branch `dev/gentle-rate-controller`
  (`docs/dev/gentle-rate-controller/`), not on main. This folder adopts its actuator choice and its proof ladder for Gentle.
- The Gentle night planner: `frontend/ecco-plan-core/src/gentleNight.ts` on branch `dev/gentle-on-card-fixes` (read only, actuates
  nothing).
- Dump to Grid V1.1 (the firmware closed loop), Free Power, the register 244 harness and the TOU editor: the firmware and Home
  Assistant packages on main; their limits in `docs/dev/dump-to-grid-ceiling.md` and `docs/dev/full-capability-controls.md`.
- The energy plan stage 3 overrides and guarded start: branch `dev/stage3-on-r9`, not on main at `04e088e`.
- The fallback profile and supervision: `docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md` (restore and failback are not
  implemented).

## Reproducing the measured numbers

The input files are the owner's offline evidence (site data, never committed). The tool reads only the files it is given and prints
aggregates:

```powershell
cls
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$env:PYTHONDONTWRITEBYTECODE = "1"
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\evidence_replay.py nights <folder with hist-*.json> 2026-11-18 2026-11-19 2026-11-20 2026-11-21
& $py -I -B -X utf8 docs\dev\dynamic-energy-control\evidence_replay.py event <history export .json> 2026-10-11T10:02:30+00:00 2026-10-11T10:15:00+00:00
```

## Next steps (each the owner's decision)

1. Authorise the read-only rungs R0 (configuration census) and R1 (history pulls): they settle the native ceilings in force,
   constant power against constant current at the top rate, and whether the inverter stops at a slot target below 100 %.
2. Supply the installation's grid import limit (main fuse or supply agreement), or confirm that none is to be applied.
3. An independent safety review of this architecture (a different reviewer from its author).
4. Then the shared core and the three mode policies, offline: simulator, replay and fault scenarios of REQ-B22, with the
   requirements' "covered by" column filled in as they are written.
