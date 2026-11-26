#!/usr/bin/env python3
"""Self-check of the dynamic-energy-control test bench (docs/dev/dynamic-energy-control/sim/).

REFERENCE MODEL AND TEST BENCH. NOT PRODUCTION CODE. Test-only: no hardware, no Home Assistant, no network. I/O: reads the repository's
firmware YAML, the Gentle planner source and its golden probe file (the pins), the requirements file and the README; runs the bench in
memory; writes nothing.

  [1] STATEMENTS AND STATIC SHAPE: every module says what it is; the model modules import only the standard library and each other and
      never open a file, a socket or a process (so the bench "writes nothing outside its own output" is checked, not claimed)
  [2] PINS: the budgets and guards of the kernel are compared with the firmware text (substitutions, the 15 s guard tick, the 1 s export
      trip), the Gentle planner's defaults and limits (gentleNight.ts, settings.ts) and its golden vectors (the Python port of the
      feasibility maths must give the planner's numbers); the GRC design constants are pinned by value (that design is not in this tree)
  [3] UNITS: the kernel's pure functions on boundary tables (also the first line of the mutation test)
  [4] CLOSED LISTS AND EXPLANATIONS: every reason and detail has a sentence, none is dead, every emitted sentence is complete
  [5] SCENARIOS: every named scenario passes (invariants, documented gaps, pinned findings, expectations); the failing (scenario, invariant) pairs
      equal the pinned set exactly; the requirement pointers are in sync
  [5b] THE INVARIANTS THEMSELVES: each judged on hand-made runs, so each is known to be able to fail as well as to pass
  [6] PLANT: the parameter table equals the defaults, every unmeasured or assumed behaviour is a flagged parameter, the replay against the saved
      nights, the charge scenarios once with the slot target not stopping the charge, the README tables are generated from the code
  [7] PROPERTY SWEEPS: thousands of seeded random plants and inputs inside the declared envelope (every applicable invariant holds; findings
      counted, false alarms bounded), a second base seed, and a sweep with the measured knee and trickle outside the envelope
  [8] MUTANTS OF THE KERNEL: in-memory single-line mutants (each limit, comparison, clamp, ordering, availability guard, reason code, and the review's);
      every one must be killed by the units or the scenarios, and those of the review's classes must die in a NAMED scenario or in the sweep alone
  [9] MUTANTS OF THE BENCH (the dongle and Home Assistant models): at least 15, each killed by a scenario or a bench unit
"""

import ast
import json
import re
import subprocess
import sys
import time
import types
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))
import kernel as K          # noqa: E402
import plant as P           # noqa: E402
import bench as B           # noqa: E402
import scenarios as S       # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def notice(text: str) -> None:
    print(f"  SKIP  {text}")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


T0 = time.time()
SIM_FILES = ("kernel.py", "plant.py", "bench.py", "scenarios.py", "run_sim.py", "test_sim.py")

# ===========================================================================
print("[1] statements and static shape")
# ===========================================================================
for f in SIM_FILES:
    head = (HERE / f).read_text(encoding="utf-8")[:2600]
    check(f"{f}: the header says it is a reference model and test bench, not production code", "NOT PRODUCTION CODE" in head)
for f in ("kernel.py", "plant.py", "bench.py", "scenarios.py", "run_sim.py"):
    head = (HERE / f).read_text(encoding="utf-8")[:3200]
    check(f"{f}: the header says it is not wired to Home Assistant, the dongle, the inverter or a register",
          re.search(r"not wired to home assistant", head, re.I) is not None)
STDLIB = set(sys.stdlib_module_names)
LOCAL = {"kernel", "plant", "bench", "scenarios"}
FORBIDDEN_CALLS = {"open", "exec", "eval", "compile", "__import__", "input"}
FORBIDDEN_MODULES = {"os", "socket", "subprocess", "urllib", "http", "requests", "shutil", "pathlib", "sys", "ctypes", "pickle", "sqlite3"}
for f in ("kernel.py", "plant.py", "bench.py", "scenarios.py"):
    tree = ast.parse((HERE / f).read_text(encoding="utf-8"))
    mods = set()
    calls = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            calls.add(n.func.id)
    check(f"{f}: imports only the standard library and the other model modules", all(m in STDLIB or m in LOCAL for m in mods), str(sorted(mods)))
    check(f"{f}: imports no file, socket, process or system module (it cannot write outside its own return value)", not (mods & FORBIDDEN_MODULES),
          str(sorted(mods & FORBIDDEN_MODULES)))
    check(f"{f}: calls no open / exec / eval / compile", not (calls & FORBIDDEN_CALLS), str(sorted(calls & FORBIDDEN_CALLS)))
for f in SIM_FILES + ("SIM_README.md",):
    text = (HERE / f).read_text(encoding="utf-8")
    check(f"{f}: ASCII only", all(ord(c) < 128 for c in text), "non-ASCII character")
    bad = re.findall(r"(?<![0-9.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![0-9.])", text)
    check(f"{f}: no private address, no e-mail address, no key or token shape",
          not bad and not re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", text) and not re.search("gh" + "p_|github" + "_pat_|sk-" + "ant-|BEGIN [A-Z ]*PRI" + "VATE", text),
          str(bad[:2]))

# ===========================================================================
print("")
print("[2] pins: the kernel's numbers against the sources that state them")
# ===========================================================================
FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
fw = read(FW_REL)
subs = dict(re.findall(r'^  (ecco_[a-z0-9_]+): "([^"]*)"', fw.split("\nesphome:")[0], re.M))
FW_PINS = {
    "ecco_dump_controller_settle_ms": K.EXPORT_SETTLE_S * 1000, "ecco_dump_controller_deadband_w": K.EXPORT_DEADBAND_W,
    "ecco_dump_controller_gain": K.EXPORT_GAIN, "ecco_dump_controller_max_step_w": K.EXPORT_MAX_STEP_W,
    "ecco_dump_controller_round_w": K.EXPORT_ROUND_W, "ecco_dump_controller_min_ceiling_w": K.EXPORT_MIN_CEILING_W,
    "ecco_dump_controller_max_writes_per_lease": K.EXPORT_MAX_WRITES, "ecco_dump_feedforward_max_start_ceiling_w": K.EXPORT_FF_MAX_START_W,
    "ecco_dump_controller_response_samples": K.EXPORT_RESPONSE_SAMPLES, "ecco_dump_controller_response_margin_w": K.EXPORT_RESPONSE_MARGIN_W,
    "ecco_dump_controller_wrong_direction_margin_w": K.EXPORT_WRONG_DIRECTION_W, "ecco_dump_controller_recovery_hold_ms": K.EXPORT_RECOVERY_HOLD_S * 1000,
    "ecco_dump_controller_recovery_max_attempts": K.EXPORT_RECOVERY_ATTEMPTS, "ecco_dump_feasibility_confirm_samples": K.EXPORT_FEASIBILITY_CONFIRM,
    "ecco_dump_grid_stale_ms": K.GRID_STALE_S * 1000,
    "ecco_dump_soc_stale_ms": K.SOC_STALE_S * 1000, "ecco_dump_runaway_margin_w": K.RUNAWAY_MARGIN_W, "ecco_dump_runaway_samples": K.RUNAWAY_SAMPLES,
    "ecco_dump_runaway_grace_ms": K.RUNAWAY_GRACE_S * 1000, "ecco_dump_runaway_absolute_margin_w": K.RUNAWAY_ABS_MARGIN_W,
    "ecco_dump_runaway_absolute_samples": K.RUNAWAY_ABS_SAMPLES, "ecco_dump_runaway_backstop_floor_w": K.RUNAWAY_BACKSTOP_FLOOR_W,
    "ecco_dump_export_far_min_w": K.EXPORT_FAR_MIN_W, "ecco_dump_export_margin_min_w": K.EXPORT_MARGIN_MIN_W,
    "ecco_failback_shadow_assumed_reboot_timeout_ms": K.REBOOT_TIMEOUT_S * 1000, "ecco_inverter_tou_power_ceiling_w": K.CHARGE_MAX_W,
    "ecco_dump_runaway_transition_ms": K.RUNAWAY_TRANSITION_S * 1000, "ecco_dump_runaway_dc_allowance_pct": K.RUNAWAY_DC_ALLOWANCE_PCT,
}
check("the firmware substitutions block was found and parsed", len(subs) > 50, str(len(subs)))
for name, want in FW_PINS.items():
    got = subs.get(name)
    check(f"firmware {name} = {want}", got is not None and abs(float(got) - float(want)) < 1e-9, f"firmware has {got!r}")
check("the Dump controller maximum ceiling is 3000 W in the firmware and no kernel constant claims more as the loop's default",
      subs.get("ecco_dump_controller_max_ceiling_w") == "3000" and K.ExportObjective(1.0, 1.0, 1.0, 1.0).lease_ceiling_w == 3000.0)
m15 = re.search(r"\n  - interval: 15s\n(?:(?!\n  - interval:).)*?script\.execute:\s*\n\s*id: dump_controller_tick", fw, re.S)
check(f"the guard tick: an 'interval: 15s' block in the firmware runs dump_controller_tick (kernel GUARD_TICK_S = {K.GUARD_TICK_S})", m15 is not None and K.GUARD_TICK_S == 15)
m1 = re.search(r"\n  - interval: 1s\n(?:(?!\n  - interval:).)*?dump_export_trip", fw, re.S)
check(f"the export trip: an 'interval: 1s' block in the firmware acts on dump_export_trip (kernel EXPORT_TRIP_TICK_S = {K.EXPORT_TRIP_TICK_S})",
      m1 is not None and K.EXPORT_TRIP_TICK_S == 1)
check("the firmware's loop law is still the one the kernel models: error = grid - target, step = error * gain clamped, rounded half away, floored, ceilinged",
      all(s in fw for s in ("float error = grid_w - target_grid_w;", "float step = error * ${ecco_dump_controller_gain}f;", "lroundf(raw / ${ecco_dump_controller_round_w}.0f)",
                            "if (rounded < ${ecco_dump_controller_min_ceiling_w}.0f) rounded = ${ecco_dump_controller_min_ceiling_w}.0f;",
                            "if (error <= ${ecco_dump_controller_deadband_w}.0f && error >= -${ecco_dump_controller_deadband_w}.0f)",
                            "id(dump_controller_writes_this_lease) >= ${ecco_dump_controller_max_writes_per_lease}")))
check("the firmware's measured-power guard is still the one the kernel models (F08): per sample, ONE start grace, the higher of the old and the new ceiling after a write, "
      "the 12 percent DC allowance above the backstop floor, and a grid sample must postdate the last write",
      all(s_ in fw for s_ in ("(uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL",
                              "id(dump_runaway_ceiling_ref) = std::max(", "(float) id(dump_controller_pending_prior_ceiling),",
                              "abs_margin += (backstop_ref - ${ecco_dump_runaway_backstop_floor_w}.0f) * (float) ${ecco_dump_runaway_dc_allowance_pct} / 100.0f;",
                              "if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;",
                              "(int32_t) (id(dump_grid_last_update_ms) - id(dump_last_controller_update_ms)) <= 0",
                              "this window no longer ZEROES the sample", "id(dump_overpower_samples)++;")))
check("the firmware has the windowed (4 of the last 8, gross 3 of 8) and mean criteria the kernel does NOT model; they only ever make the firmware stricter (README, F08)",
      all(s_ in fw for s_ in ("ecco_dump_runaway_window_k", "ecco_dump_runaway_gross_k", "ecco_dump_runaway_mean_margin_w")))
check("the firmware's Stop SOC rule is still 'reading at or below the latched stop ends the lease'",
      "id(ecco_battery_soc).state <= (float) id(dump_target_stop_soc)" in fw)

PLAN_REL = "frontend/ecco-plan-core/src/gentleNight.ts"
plan = read(PLAN_REL)
blk = plan.split("export const DEFAULT_NIGHT_PARAMS", 1)[1].split("});", 1)[0]
planner = {k: float(v) for k, v in re.findall(r"(\w+): (-?\d+(?:\.\d+)?)", blk)}
settings = read("frontend/ecco-plan-core/src/settings.ts")
lim_min = float(re.search(r"chargePowerMin:\s*(\d+)", settings).group(1))
lim_max = float(re.search(r"chargePowerMax:\s*(\d+)", settings).group(1))
PLANNER_PINS = {
    "stepW": K.CHARGE_STEP_W, "dwellMin": K.CHARGE_DWELL_S / 60.0, "maxChanges": K.CHARGE_MAX_CHANGES, "hysteresisW": K.PLANNER_HYSTERESIS_W,
    "decreaseSlackMin": K.PLANNER_SLACK_S / 60.0, "chargeEffMin": K.EFF_PESSIMISTIC, "capacityBandPct": K.CAPACITY_BAND_PCT,
    "socScaleErrPct": K.SOC_SCALE_ERR_PCT, "socResolutionPct": K.SOC_RESOLUTION_PCT, "socNoisePct": K.SOC_NOISE_PCT, "kneeSocPct": K.KNEE_PESSIMISTIC_PCT,
    "tailFraction": K.TAIL_FRACTION, "dropMin": K.DROP_MIN, "demandMarginPct": K.DEMAND_MARGIN_PCT, "chargeEffMax": K.EFF_MAX,
}
check("the planner's DEFAULT_NIGHT_PARAMS block was found and parsed", len(planner) > 25, str(len(planner)))
for k, want in PLANNER_PINS.items():
    check(f"planner {k} = {want}", k in planner and abs(planner[k] - want) < 1e-9, f"planner has {planner.get(k)!r}")
check(f"the lowest and highest setpoint are the planner's LIMITS (chargePowerMin {lim_min:.0f}, chargePowerMax {lim_max:.0f})",
      lim_min == K.CHARGE_MIN_W and lim_max == K.CHARGE_MAX_W)
check("the planner's default finish-early buffer is 60 minutes (kernel BUFFER_S)", "input.bufferMin === undefined ? 60 : input.bufferMin" in plan and K.BUFFER_S == 3600)
check("the planner's pessimistic world is still built as the Python port builds it (capacity, band, scale, offset, drop)",
      all(s in plan for s in ("(capKwh * (1 + band)) / (1 - scale) / 100, P.chargeEffMin, kneeP, P.tailFraction, Math.min(1, P.dropMin), -(P.socResolutionPct / 2 + P.socNoisePct)",
                              "const perMin = (rateW * w.eff) / 1000 / 60 / w.pctKwh;")))

# the golden vectors of the planner, run through the Python port of its feasibility maths (no Node needed)
golden = json.loads(read("frontend/ecco-plan-core/test/gentleNightProbe.golden.json"))
GOLD = {   # key: (soc, target, elapsed_min, in_force_w, ceiling_w, deadline_min_from_window_open)  (capacity 31.7, window 30..330 = 300 min, buffer 60 unless noted)
    "A": (20.0, 80.0, 0.0, None, 8000, 240.0), "A60": (20.0, 60.0, 0.0, None, 8000, 240.0), "B": (40.0, 93.0, 0.0, None, 8000, 240.0),
    "C": (85.0, 95.0, 0.0, 8000.0, 8000, 240.0), "C93": (85.0, 93.0, 0.0, 8000.0, 8000, 240.0), "D": (93.0, 95.0, 60.0, 5200.0, 8000, 240.0),
    "E": (10.0, 100.0, 0.0, None, 3000, 180.0), "F": (40.0, 95.0, 0.0, None, 8000, 240.0),
}
W317 = K.pessimistic_world(31.7)
for key, (soc, target, elapsed, in_force, ceil_w, dl) in GOLD.items():
    g = golden[key] if isinstance(golden[key], dict) else json.loads(golden[key])
    rel_dl = dl - elapsed
    cands = K.candidates(500, ceil_w)
    charging = in_force is not None and elapsed > 0
    since_pct = 0.0
    if in_force is not None and elapsed > 0:
        since_pct = (1.0 * in_force * 1.1 / 60.0 / 1000.0) / (31.7 * (1 - 0.06) / (1 + 0.03) / 100.0)   # the planner's charge-since-reading bound, one minute at the rate in force
    past = charging and K.knee_may_be_passed(W317, target, soc + 1.0 + since_pct)
    need, ok = K.lowest_feasible(W317, target, 0.0, soc, in_force, cands, rel_dl, charging, past)
    check(f"golden {key}: the planner's neededW = {g['now']['neededW']} and neededMeetsDeadline = {g['now']['neededMeetsDeadline']}",
          need == g["now"]["neededW"] and ok == g["now"]["neededMeetsDeadline"], f"port gives {need} {ok}")
    held_rate = g["now"]["setpointW"]
    if held_rate is not None and g["band"] is not None:
        fin = K.pess_finish(W317, target, 0.0, soc, in_force, float(held_rate), 300.0 - elapsed, charging, past)   # judged to the window end, like the planner's band
        want = g["band"][3][0]
        got = None if fin is None else round(fin + elapsed, 2)
        check(f"golden {key}: the pessimistic finish with the first rate held = {want}", (got is None and want is None) or (got is not None and want is not None and abs(got - want) <= 0.011),
              f"port gives {got}")

# the GRC design (branch dev/gentle-rate-controller) is not in this tree. Its numbers are ASSERTED VALUES, not a live pin: vendored in grc_core_constants.txt with
# the source commit named. The kernel is compared with that file; where the commit is present locally the file is compared with the header too.
GRC_FIXTURE = (HERE / "grc_core_constants.txt").read_text(encoding="utf-8")
grc = {k: int(v) for k, v in re.findall(r"^(\w+) = (-?\d+)\s*$", GRC_FIXTURE, re.M)}
grc_commit = re.search(r"^# source commit: ([0-9a-f]{40})\s*$", GRC_FIXTURE, re.M).group(1)
check("the vendored GRC constants say what they are: asserted values, not a live pin, with their source commit named", "NOT A LIVE PIN" in GRC_FIXTURE and len(grc) >= 30)
GRC_KERNEL = {   # the GRC's Config name -> the kernel's constant, in the GRC's unit
    "floor_w": K.CHARGE_MIN_W, "round_w": K.CHARGE_STEP_W, "fw_bound_w": K.CHARGE_MAX_W, "max_step_w": K.CHARGE_MAX_STEP_W, "hyst_w": K.CHARGE_HYST_W,
    "reversal_extra_w": K.CHARGE_REVERSAL_EXTRA_W, "dwell_ms": K.CHARGE_DWELL_S * 1000, "settle_ms": K.GRC_SETTLE_S * 1000, "max_changes": K.CHARGE_MAX_CHANGES,
    "night_write_ceiling": K.CHARGE_NIGHT_WRITES, "plan_max_age_ms": K.PLAN_MAX_AGE_S * 1000, "telemetry_stale_ms": K.TELEMETRY_STALE_S * 1000,
    "clock_skew_max_s": K.CLOCK_SKEW_MAX_S, "end_margin_s": K.END_MARGIN_S, "charging_min_w": K.GRC_CHARGING_MIN_W, "response_min_pct": round(K.GRC_RESPONSE_MIN * 100),
    "wrong_dir_w": K.EXPORT_WRONG_DIRECTION_W, "max_ineffective": K.GRC_MAX_INEFFECTIVE, "gain_min_pct": round(K.GRC_GAIN_MIN * 100), "gain_max_pct": round(K.GRC_GAIN_MAX * 100),
    "runaway_pct": 100 + round(K.CHARGE_RUNAWAY_PCT), "runaway_margin_w": K.CHARGE_RUNAWAY_MARGIN_W, "runaway_samples": K.RUNAWAY_SAMPLES, "guard_margin_s": K.GUARD_MARGIN_S,
}
for name, got in GRC_KERNEL.items():
    check(f"GRC design (asserted value, vendored fixture, not a live pin): {name} = {grc.get(name)} and the kernel has {got}", grc.get(name) == got)
check("GRC design: 3 restore attempts and 1 owner restore are reserved out of the night's writes (the kernel reserves their sum)",
      grc["max_restore_attempts"] + grc["owner_restore_reserve"] == K.CHARGE_RESTORE_RESERVE and B.RESTORE_ATTEMPTS == grc["max_restore_attempts"])
KSRC_HEAD = (HERE / "kernel.py").read_text(encoding="utf-8").split('"""', 2)[1]
GRC_DIFFERENT = ("judge_samples", "week_write_ceiling", "life_write_ceiling", "guard_derate_pct", "guard_tail_pct", "taper_max_pct", "max_changes")
check("every number of the GRC design that the kernel does NOT mirror is named in the kernel's list of deliberate differences (judge frames, week and life ceilings, the guard's derate and tail, START in max_changes)",
      all(n in KSRC_HEAD for n in GRC_DIFFERENT) and "WHERE THIS KERNEL DELIBERATELY DIFFERS FROM THE GRC DESIGN" in KSRC_HEAD and grc["judge_samples"] != 1)
check("the planner agrees with the GRC on the two numbers both state (30 min dwell, 6 changes): the planner is parsed, so this one is live", planner["dwellMin"] * 60000 == grc["dwell_ms"] and planner["maxChanges"] == grc["max_changes"])
try:
    hdr = subprocess.run(["git", "show", f"{grc_commit}:docs/dev/gentle-rate-controller/proposed/ecco_gentle_rate_core.h"], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=30)
except Exception:
    hdr = None
if hdr is not None and hdr.returncode == 0 and "struct Config" in hdr.stdout:
    local = {k: int(v) for k, v in re.findall(r"^\s+u?int32_t\s+(\w+)\s*=\s*(-?\d+);", hdr.stdout, re.M)}
    local.update({k: int(v) for k, v in re.findall(r"^\s+uint32_t\s+(\w+)\s*=\s*(-?\d+);", hdr.stdout, re.M)})
    check(f"the vendored GRC constants equal the header at commit {grc_commit[:8]} (a local check: that commit is not in a clone of this repository)", all(local.get(k) == v for k, v in grc.items()),
          str({k: (v, local.get(k)) for k, v in grc.items() if local.get(k) != v}))
else:
    notice(f"commit {grc_commit[:8]} of dev/gentle-rate-controller is not in this clone: the vendored GRC constants are compared with the kernel only (asserted values, not a live pin)")
GRC_REL = "docs/dev/gentle-rate-controller/SPEC.md"
if (ROOT / GRC_REL).exists():
    spec = read(GRC_REL)
    check("the GRC SPEC in this tree still states 30 min, 6, 10, 2000, 300, 20 min, 600 s", all(s_ in spec for s_ in ("30 min", "2000", "300", "20 min")))
else:
    notice(f"{GRC_REL} is not in this tree (branch dev/gentle-rate-controller)")

# ===========================================================================
print("")
print("[3] units: the kernel's pure functions on boundary tables")
# ===========================================================================
NAN, INFTY = float("nan"), float("inf")


def frame(Km, soc=50.0, age=0.0, grid=0.0, inv=0.0, pv=0.0, batt=0.0):
    return Km.Frame(soc_pct=soc, age_s=age, grid_w=grid, inv_ac_w=inv, pv_w=pv, batt_w=batt)


def inputs(Km, now=1000.0, fr=None, **kw):
    return Km.Inputs(now_s=now, frame=fr if fr is not None else frame(Km), **kw)


def u_fresh(Km):
    assert Km.is_fresh(10.0, 90.0, 90.0) and not Km.is_fresh(10.0, 90.5, 90.0)
    assert not Km.is_fresh(None, 0.0, 90.0) and not Km.is_fresh(NAN, 0.0, 90.0) and not Km.is_fresh(INFTY, 0.0, 90.0)
    assert not Km.is_fresh(1.0, NAN, 90.0) and not Km.is_fresh(1.0, None, 90.0) and not Km.is_fresh(1.0, INFTY, 90.0)
    f = frame(Km, age=10.0)
    assert Km.frame_fresh(f, ("soc", "grid", "ac", "pv", "batt"))
    assert not Km.frame_fresh(replace(f, grid_w=None), ("soc", "grid")) and Km.frame_fresh(replace(f, grid_w=None), ("soc",))
    assert not Km.frame_fresh(replace(f, inv_ac_w=None), ("ac",)) and not Km.frame_fresh(replace(f, age_s=91.0), ("soc",))
    assert not Km.frame_fresh(replace(f, soc_pct=None), ("soc", "grid")) and not Km.frame_fresh(replace(f, batt_w=None), ("soc", "batt"))
    assert not Km.frame_fresh(replace(f, pv_w=None), ("soc", "pv")), "the pv field is checked"


def u_house(Km):
    assert Km.house_w(frame(Km, grid=9000.0, inv=-8000.0)) == 1000.0
    assert Km.house_w(frame(Km, grid=-1000.0, inv=2000.0)) == 1000.0
    assert Km.house_w(frame(Km, grid=100.0, inv=-8000.0)) == 0.0
    assert Km.house_w(replace(frame(Km), grid_w=None)) is None and Km.house_w(replace(frame(Km), inv_ac_w=None)) is None
    assert Km.ac_in_w(frame(Km, inv=-8000.0)) == 8000.0 and Km.ac_in_w(frame(Km, inv=500.0)) == 0.0 and Km.ac_in_w(replace(frame(Km), inv_ac_w=None)) is None


def u_time(Km):
    assert Km.time_trusted(120.0, 3600.0, 3) and Km.time_trusted(-120.0, 0.0, 0)
    assert not Km.time_trusted(120.5, 0.0, 0) and not Km.time_trusted(-121.0, 0.0, 0)
    assert not Km.time_trusted(0.0, 3601.0, 0) and not Km.time_trusted(0.0, 0.0, 4)
    assert not Km.time_trusted(None, 0.0, 0) and not Km.time_trusted(0.0, None, 0) and not Km.time_trusted(0.0, 0.0, None)


def u_margin(Km):
    assert abs(Km.stop_soc_with_margin(20.0, 25.0, 3000.0, 35.0, 120.0) - (25.0 + 1.0 + 3000 * 120 / 3600 / 1000 / 35 * 100)) < 1e-9
    assert abs(Km.stop_soc_with_margin(30.0, 25.0, 3000.0, 35.0, 120.0) - (30.0 + 1.0 + 3000 * 120 / 3600 / 1000 / 35 * 100)) < 1e-9
    assert Km.stop_soc_with_margin(99.9, 20.0, 8000.0, 35.0) == 100.0
    assert Km.stop_soc_with_margin(20.0, 20.0, 8000.0, 35.0, 240.0) > Km.stop_soc_with_margin(20.0, 20.0, 8000.0, 35.0, 120.0)


def u_guard_order(Km):
    order = Km.GUARD_ORDER
    assert order == ("grid_lost", "owner_end", "time_untrusted", "stale", "floor", "ceiling", "runaway", "budget", "deadline", "target_guard")
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            assert Km.first_guard({a: True, b: True}) == a, (a, b)
    assert Km.first_guard({}) is None and Km.first_guard({"stale": False}) is None
    try:
        Km.first_guard({"typo": True})
    except ValueError:
        return
    raise AssertionError("an unknown guard name must raise")


def charge_state(Km, **kw):
    base = dict(phase="active", v_w=6000.0, original_w=8000.0, last_write_s=0.0, changes=0, writes=1, last_dir=0)
    base.update(kw)
    return Km.State(**base)


def u_ramp(Km):
    r, st = Km.ramp_charge, charge_state(Km)
    assert r(st, 1799.0, 5000.0, 8000.0) == (None, "dwell") and r(st, 1800.0, 5000.0, 8000.0) == (5000.0, None)
    assert r(st, 1800.0, 5701.0, 8000.0) == (None, "deadband") and r(st, 1800.0, 5700.0, 8000.0) == (5700.0, None)
    assert r(st, 1800.0, 6000.0, 8000.0) == (None, "no_change_needed") and r(replace(st, v_w=None), 1800.0, 5000.0, 8000.0) == (None, "no_change_needed")
    assert r(st, 1800.0, 2000.0, 8000.0) == (4000.0, None), "no change may move the setpoint by more than 2000 W"
    assert r(st, 1800.0, 9900.0, 8000.0) == (8000.0, None) and r(st, 1800.0, 9900.0, 6500.0) == (6500.0, None)
    assert r(replace(st, original_w=7000.0), 1800.0, 9900.0, 8000.0) == (7000.0, None), "a lease is subtractive: never above the pre-session value"
    assert r(replace(st, v_w=900.0), 1800.0, 100.0, 8000.0) == (500.0, None), "never below 500 W"
    assert r(replace(st, changes=6), 1800.0, 5000.0, 8000.0) == (None, "budget") and r(replace(st, changes=5), 1800.0, 5000.0, 8000.0) == (5000.0, None)
    assert r(replace(st, writes=6), 1800.0, 5000.0, 8000.0) == (None, "budget") and r(replace(st, writes=5), 1800.0, 5000.0, 8000.0) == (5000.0, None)
    assert r(replace(st, last_dir=1), 1800.0, 5401.0, 8000.0) == (None, "reversal") and r(replace(st, last_dir=1), 1800.0, 5400.0, 8000.0) == (5400.0, None)
    assert r(replace(st, last_dir=-1), 1800.0, 5700.0, 8000.0) == (5700.0, None), "the same direction needs only the ordinary deadband"
    f = replace(st, changes=6, last_write_s=1700.0)
    assert r(f, 1750.0, 5900.0, 8000.0, forced=True) == (5900.0, None), "a forced reduction ignores dwell, deadband and the change count"
    assert r(f, 1750.0, 1000.0, 8000.0, forced=True) == (4000.0, None), "but not the step size"
    assert r(replace(f, writes=9), 1750.0, 5900.0, 8000.0, forced=True) == (None, "budget") and r(replace(f, writes=8), 1750.0, 5900.0, 8000.0, forced=True) == (5900.0, None)
    assert Km.writes_left_for_changes(replace(st, writes=2)) == 4


def es(Km, grid, now=1000.0, age=0.0, target=2000.0, v=2000.0, ceil=3000.0, st=None, house=None, pv=None):
    st = st if st is not None else Km.State(phase="active", v_w=v, last_update_s=0.0)
    return Km.export_step(st, now, grid, age, target, v, ceil, house, pv)


def u_export_loop(Km):
    assert es(Km, -1850.0)[:3] == (None, "TRACKING", None) and es(Km, -2150.0)[:3] == (None, "TRACKING", None)
    assert es(Km, -1849.0)[0] == 2100.0 and es(Km, -2151.0)[0] == 1900.0
    assert es(Km, -1700.0, v=1900.0)[0] == 2100.0, "a half is rounded away from zero (as lroundf does), not to even"
    assert es(Km, -1700.0)[0] == 2200.0
    assert es(Km, 1000.0, ceil=8000.0)[0] == 3000.0, "the step is clamped to 1000 W"
    assert es(Km, -4000.0, v=3000.0, ceil=8000.0)[0] == 2000.0
    r = es(Km, -1000.0, v=2900.0)
    assert r[0] == 3000.0 and r[1] == "SATURATED HIGH"
    r = es(Km, -3000.0, v=600.0)
    assert r[0] == 500.0 and r[1] == "SATURATED LOW"
    assert es(Km, -2300.0, v=500.0)[:2] == (None, "SATURATED LOW")
    assert es(Km, -1700.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=970.0))[:2] == (None, "SETTLING")
    assert es(Km, -1700.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=955.0))[0] == 2200.0
    assert es(Km, -1700.0, age=91.0)[1:3] == ("WAITING FOR FRESH GRID", "stale_telemetry") and es(Km, -1700.0, age=90.0)[0] == 2200.0
    assert es(Km, 30000.0)[2] == "stale_telemetry" and es(Km, -30000.0)[2] == "stale_telemetry" and es(Km, 29999.0, ceil=8000.0)[2] is None
    assert es(Km, -1700.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=0.0, writes=120))[1:3] == ("WRITE BUDGET EXHAUSTED", "write_budget")
    assert es(Km, -1700.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=0.0, writes=119))[0] == 2200.0
    pend = dict(phase="active", v_w=2000.0, last_update_s=0.0, response_pending=True, pending_err_w=500.0)
    ok = es(Km, -1620.0, st=Km.State(**pend, ineffective=2))        # error 380: improvement 120
    assert ok[3].ineffective == 0 and ok[3].response_pending is False
    weak = es(Km, -1590.0, st=Km.State(**pend, ineffective=1))      # error 410: improvement 90
    assert weak[3].ineffective == 2 and weak[3].wrong_dir == 0
    edge = es(Km, -1600.0, st=Km.State(**pend, ineffective=1))      # error 400: improvement exactly 100 is a response
    assert edge[3].ineffective == 0
    wrong = es(Km, -1190.0, st=Km.State(**pend, wrong_dir=1))       # error 810: improvement -310
    assert wrong[3].wrong_dir == 2 and wrong[3].ineffective == 1
    assert es(Km, -1190.0, st=Km.State(**pend, wrong_dir=2))[1:3] == ("GRID RESPONSE SANITY FAILED", "response_failed")
    edge2 = es(Km, -1200.0, st=Km.State(**pend, wrong_dir=2))       # error 800: improvement -300 is wrong direction
    assert edge2[1:3] == ("GRID RESPONSE SANITY FAILED", "response_failed")
    assert es(Km, -1700.0, now=1000.0, age=50.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=955.0))[1:3] == ("WAITING FOR FRESH GRID", None), "a grid sample that predates the last write is not used (the firmware's fence, F08)"
    assert es(Km, -1700.0, now=1000.0, age=40.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=955.0))[0] == 2200.0 and \
        es(Km, -1700.0, now=1000.0, age=45.0, st=Km.State(phase="active", v_w=2000.0, last_update_s=955.0))[1] == "WAITING FOR FRESH GRID", "the sample must be strictly newer than the write"
    stuck = es(Km, -1590.0, st=Km.State(**pend, ineffective=2))
    assert stuck[1] == "NO RESPONSE" and stuck[3].no_resp_since_s == 1000.0
    flipped = es(Km, -2100.0, st=Km.State(**pend, ineffective=2))   # the error crossed zero: the counters reset
    assert flipped[3].ineffective == 0
    hold = Km.State(phase="active", v_w=2000.0, last_update_s=0.0, no_resp_since_s=950.0)
    assert es(Km, -1700.0, st=hold)[:2] == (None, "NO RESPONSE")
    retry = es(Km, -1700.0, now=1010.0, st=hold)
    assert retry[0] == 2200.0 and retry[3].recoveries == 1 and retry[3].no_resp_since_s is None
    assert es(Km, -1700.0, now=1010.0, st=replace(hold, recoveries=1))[1:3] == ("NO RESPONSE - RECOVERY EXHAUSTED", "response_failed")
    assert es(Km, -1700.0, house=1000.0, pv=0.0)[3].low_streak == 0
    assert es(Km, -1700.0, house=1000.0, pv=4000.0)[3].low_streak == 1 and es(Km, -1700.0, house=1000.0, pv=3150.0)[3].low_streak == 0
    assert es(Km, -1700.0, house=1000.0, pv=0.0, ceil=2900.0)[3].high_streak == 1 and es(Km, -1700.0, house=1000.0, pv=0.0)[3].high_streak == 0
    nst = Km.note_export_write(Km.State(writes=3), 77.0, 2500.0)
    assert (nst.v_w, nst.last_update_s, nst.writes, nst.response_pending) == (2500.0, 77.0, 4, True)
    assert Km.note_export_write(Km.State(v_w=3400.0), 77.0, 2500.0).ref_w == 3400.0 and Km.note_export_write(Km.State(v_w=2000.0), 77.0, 2500.0).ref_w == 2500.0, \
        "the transition reference is the higher of the old and the new ceiling"


def u_runaway(Km):
    st = Km.State()
    for _ in range(2):
        st, t = Km.runaway_check(st, 3001.0, 2000.0, "export")
        assert not t
    assert Km.runaway_check(st, 3001.0, 2000.0, "export")[1]
    assert not Km.runaway_check(Km.State(over_samples=2), 3000.0, 2000.0, "export")[1]
    assert Km.runaway_check(Km.State(over_samples=0), 1151.0, 400.0, "export")[0].over_samples == 1 and Km.runaway_check(Km.State(), 1150.0, 400.0, "export")[0].over_samples == 0
    assert Km.runaway_check(Km.State(over_samples=2), 5101.0, 4000.0, "charge")[1] and not Km.runaway_check(Km.State(over_samples=2), 5100.0, 4000.0, "charge")[1]
    assert Km.runaway_check(Km.State(over_samples=1), 3001.0, 2000.0, "export")[0].over_samples == 2
    # the two thresholds for one sample as the firmware computes them: ordinary, absolute with the DC allowance above 3000 W, the transition (F08)
    lim_ = lambda st_, ceil_, now_: Km.runaway_limits(st_, ceil_, now_)
    base_ = Km.State(phase="active", v_w=2000.0, last_update_s=0.0, ref_w=2000.0)
    assert lim_(base_, 3000.0, 1000.0) == (2000.0, 3000.0, 3750.0), lim_(base_, 3000.0, 1000.0)
    assert lim_(replace(base_, v_w=5000.0, ref_w=5000.0), 5000.0, 1000.0) == (5000.0, 7500.0, 5990.0), "above 3000 W the 750 W margin grows by 12 percent of the command above it"
    assert lim_(replace(base_, v_w=1000.0, ref_w=1000.0), 2000.0, 1000.0)[2] == 2750.0, "the backstop floor is the lease's own ceiling when that is lower than 3000 W"
    tr = replace(base_, v_w=3400.0, ref_w=4200.0, last_update_s=600.0)
    assert lim_(tr, 8000.0, 629.0)[0] == 4200.0 and lim_(tr, 8000.0, 630.0)[0] == 3400.0, "30 s after a write the higher of the old and the new ceiling is the command"
    assert abs(lim_(tr, 8000.0, 629.0)[2] - (4200.0 + 750.0 + 1200.0 * 0.12)) < 1e-9 and abs(lim_(tr, 8000.0, 630.0)[2] - (3400.0 + 750.0 + 400.0 * 0.12)) < 1e-9
    assert Km.runaway_check(Km.State(), None, 2000.0, "export") == (Km.State(), False)
    assert Km.export_over_limit(-6251.0, 5000.0, False) == (True, True) and Km.export_over_limit(-6250.0, 5000.0, False) == (False, True)
    assert Km.export_over_limit(-5151.0, 5000.0, False) == (False, True) and Km.export_over_limit(-5151.0, 5000.0, True) == (True, True)
    assert Km.export_over_limit(-5150.0, 5000.0, True) == (False, False) and Km.export_over_limit(-4000.0, 5000.0, True) == (False, False)
    assert Km.export_over_limit(-901.0, 400.0, False) == (True, True) and Km.export_over_limit(-900.0, 400.0, False) == (False, True), "the far margin is at least 500 W"
    assert Km.export_over_limit(-3000.0, None, False) == (False, False) and Km.export_over_limit(None, 3000.0, False) == (False, False)


GAIN = 8980.0 / 8000.0
OBJ = None


def cobj(Km, target=90.0, deadline=14400.0, end=18000.0, cap=35.0):
    return Km.ChargeObjective(target, deadline, end, cap)


def cin(Km, now=300.0, soc=25.0, age=0.0, house=800.0, ac=8980.0, inforce=8000.0, **kw):
    return Km.Inputs(now_s=now, frame=Km.Frame(soc_pct=soc, age_s=age, grid_w=house + ac, inv_ac_w=-ac, pv_w=0.0, batt_w=-ac * 0.94), in_force_w=inforce, **kw)


def u_feasibility(Km):
    w = Km.pessimistic_world(31.7)
    c = Km.candidates(500, 8000)
    for soc, target, dl, need, ok in ((20.0, 80.0, 240.0, 5900, True), (20.0, 60.0, 240.0, 4000, True), (40.0, 93.0, 240.0, 7200, True), (85.0, 95.0, 240.0, 4400, True),
                                      (85.0, 93.0, 240.0, 2900, True), (40.0, 95.0, 240.0, 8000, False)):
        assert Km.lowest_feasible(w, target, 0.0, soc, None, c, dl, False, False) == (need, ok), (soc, target)
    assert Km.lowest_feasible(w, 100.0, 0.0, 10.0, None, Km.candidates(500, 3000), 180.0, False, False) == (3000, False)
    assert Km.lowest_feasible(w, 80.0, 0.0, 20.0, None, [], 240.0, False, False) == (None, False)
    f = Km.pess_finish(w, 95.0, 0.0, 93.0, 5200.0, 5200.0, 180.0, True, True)
    assert abs(f - 106.58842) < 1e-4, f
    assert abs(Km.pess_finish(w, 80.0, 0.0, 20.0, None, 5900.0, 240.0, False, False) - 238.7701) < 1e-3
    assert Km.pess_finish(w, 80.0, 0.0, 20.0, None, 5800.0, 240.0, False, False) is None
    assert Km.pess_finish(w, 80.0, 0.0, 90.0, None, 5800.0, 240.0, False, False) == 0.0
    assert Km.knee_may_be_passed(w, 95.0, 90.0) and not Km.knee_may_be_passed(w, 95.0, 89.9) and not Km.knee_may_be_passed(w, 90.0, 95.0)
    assert abs(Km.fall_integral(0.0, 2.0, 0.125, 1.0) - (1.0 - (0.875 * 1.0) / 2.0 + 0.125 * 1.0)) < 1e-12 and Km.fall_integral(0.0, 2.0, 0.5, 0.0) == 1.0
    assert abs(Km.pessimistic_world(35.0).pct_kwh - 35.0 * 1.06 / 0.97 / 100.0) < 1e-12 and Km.pessimistic_world(35.0).offset == -1.0
    assert Km.pessimistic_world(35.0, eff=0.5).eff == 0.5


def u_measure_and_judge(Km):
    st = Km.State()
    assert Km.measure_gain(cin(Km), st) == (8980.0 / 8000.0, None)
    assert Km.measure_gain(cin(Km, ac=999.0), st) == (None, "no_charge_running") and Km.measure_gain(cin(Km, ac=1000.0, inforce=1000.0), st)[1] is None
    assert Km.measure_gain(cin(Km, inforce=None), st) == (None, "no_charge_running") and Km.measure_gain(cin(Km, inforce=0.0), st) == (None, "no_charge_running")
    assert Km.measure_gain(cin(Km, ac=1500.0, inforce=1000.0), st) == (1.5, None) and Km.measure_gain(cin(Km, ac=1510.0, inforce=1000.0), st)[1] == "implausible_gain"
    assert Km.measure_gain(cin(Km, ac=5000.0, inforce=10000.0), st) == (0.5, None) and Km.measure_gain(cin(Km, ac=4900.0, inforce=10000.0), st)[1] == "implausible_gain"
    base = Km.State(phase="active", v_w=4000.0, pre_v_w=6000.0, pre_ac_w=6600.0, gain=1.1, last_write_s=0.0, pending_judge=True)
    assert Km.judge_response(cin(Km, now=44.0, ac=4400.0), base)[1] == "pending" and Km.judge_response(cin(Km, now=45.0, ac=4400.0), base)[1] == "ok"
    assert Km.judge_response(cin(Km, now=45.0, ac=4400.0, age=31.0), base)[1] == "pending"
    assert Km.judge_response(cin(Km, now=60.0, ac=5950.0), base)[1] == "weak" and Km.judge_response(cin(Km, now=60.0, ac=5950.0), base)[0].weak == 1
    assert Km.judge_response(cin(Km, now=60.0, ac=5940.0), base)[1] == "ok" and Km.judge_response(cin(Km, now=60.0, ac=5941.0), base)[1] == "weak"
    assert Km.judge_response(cin(Km, now=60.0, ac=8980.0), base)[1] == "implausible" and Km.judge_response(cin(Km, now=60.0, ac=6001.0), base)[1] == "implausible"
    assert Km.judge_response(cin(Km, now=60.0, ac=1999.0), base)[1] == "implausible" and Km.judge_response(cin(Km, now=60.0, ac=2000.0), base)[1] != "implausible"
    base2 = Km.State(phase="active", v_w=6500.0, pre_v_w=8000.0, pre_ac_w=8800.0, gain=1.1, last_write_s=0.0, pending_judge=True)
    assert Km.judge_response(cin(Km, now=60.0, ac=9101.0), base2)[1] == "wrong" and Km.judge_response(cin(Km, now=60.0, ac=9100.0), base2)[1] == "weak"
    assert Km.judge_response(cin(Km, now=60.0, ac=8300.0), base2)[1] == "ok" and Km.judge_response(cin(Km, now=60.0, ac=8310.0), base2)[1] == "weak"
    assert Km.judge_response(cin(Km, now=60.0, ac=4400.0), replace(base, pending_judge=False))[1] == "none"
    assert Km.judge_response(cin(Km, now=60.0, ac=5800.0), replace(base, v_w=5800.0, pre_v_w=6000.0))[1] == "ok", "a small step is not judged"
    assert abs(Km.judge_response(cin(Km, now=60.0, ac=4400.0), base)[0].gain - 1.1) < 1e-12
    s = Km.note_start(Km.State(), 300.0, 8000.0, 1.1225, 6300.0, pre_ac_w=8980.0)
    assert (s.phase, s.v_w, s.original_w, s.writes, s.changes, s.pending_judge, s.pre_v_w) == ("active", 6300.0, 8000.0, 1, 0, True, 8000.0)
    assert Km.note_start(Km.State(), 300.0, 8000.0, 1.1225, 8000.0).writes == 0
    w = Km.note_write(s, 2000.0, 5800.0, "change", 7000.0)
    assert (w.v_w, w.writes, w.changes, w.last_dir, w.pre_v_w, w.pre_ac_w) == (5800.0, 2, 1, -1, 6300.0, 7000.0)
    fz = Km.note_write(s, 2000.0, 5800.0, "forced", 7000.0)
    assert (fz.writes, fz.changes, fz.last_dir) == (2, 0, 0) and Km.note_write(s, 2000.0, 8000.0, "restore").phase == "ended" and Km.note_end(s).phase == "ended"
    assert Km.note_write(replace(s, last_dir=1), 2000.0, 5800.0, "forced", 7000.0).last_dir == 1, "a forced reduction leaves the reversal memory alone (N17)"


def u_guards(Km):
    ob, lim = cobj(Km), Km.Limits(import_ceiling_w=11000.0)
    act = replace(Km.note_start(Km.State(), 300.0, 8000.0, GAIN, 6300.0), pending_judge=False)
    idle = Km.State()
    g = Km.charge_guards(cin(Km, grid_ok=False, hold=True, age=200.0, time_ok=False), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "grid_lost", True)
    g = Km.charge_guards(cin(Km, grid_ok=False, hold=True), ob, lim, idle, "gentle")
    assert (g.reason, g.detail, g.end) == ("blocked", "grid_lost", False)
    g = Km.charge_guards(cin(Km, hold=True, age=200.0, time_ok=False), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "owner_end", True) and Km.charge_guards(cin(Km, hold=True), ob, lim, idle, "gentle").detail == "owner_hold"
    g = Km.charge_guards(cin(Km, age=200.0, time_ok=False), ob, lim, act, "gentle")
    assert (g.reason, g.detail) == ("stop", "time_untrusted") and Km.charge_guards(cin(Km, time_ok=False), ob, lim, idle, "gentle").detail == "time_untrusted"
    g = Km.charge_guards(cin(Km, age=91.0), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "stale_telemetry", True) and Km.charge_guards(cin(Km, age=91.0), ob, lim, idle, "gentle").reason == "blocked"
    assert Km.charge_guards(cin(Km, age=90.0), ob, lim, act, "gentle") is None
    assert Km.charge_guards(cin(Km, dongle_ok=False), ob, lim, idle, "gentle").detail == "dongle_unavailable"
    g = Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.write_w) == ("reduce", "import_ceiling", 5700.0), g      # import 11070 W: 620 W over the 95 % line, 552 W of setpoint
    assert Km.charge_guards(cin(Km, now=2000.0, house=3930.0, ac=7070.0), ob, lim, act, "gentle") is None, "exactly at the ceiling is not a breach"
    g = Km.charge_guards(cin(Km, now=2000.0, house=3931.0, ac=7070.0), ob, lim, act, "gentle")
    assert g is not None and g.detail == "import_ceiling"
    g = Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, lim, replace(act, v_w=5000.0), "gentle")
    assert (g.reason, g.write_w) == ("reduce", 4400.0), g
    g = Km.charge_guards(cin(Km, now=2000.0, house=10000.0, ac=7070.0), ob, lim, act, "gentle")
    assert g.reason == "stop" and g.detail == "import_ceiling" and g.end, "no setpoint at or above 500 W would fit"
    g = Km.charge_guards(cin(Km, now=2000.0, house=9800.0, ac=7070.0), ob, lim, act, "gentle")
    assert g.reason == "reduce" and g.write_w == 4300.0, "the largest single step is 2000 W"
    g = Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, lim, replace(act, writes=9), "gentle")
    assert (g.reason, g.detail) == ("stop", "write_budget")
    fx = Km.State(phase="active", v_w=8000.0)
    assert Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, lim, fx, "charge_fixed").detail == "import_ceiling" and Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, lim, fx, "charge_fixed").end
    assert Km.charge_guards(cin(Km, now=2000.0, house=4000.0, ac=7070.0), ob, Km.Limits(), act, "gentle") is None, "no ceiling configured, no breach"
    assert Km.lease_end_s(cobj(Km)) == 14400.0 and Km.lease_end_s(cobj(Km, deadline=17900.0)) == 17400.0
    g = Km.charge_guards(cin(Km, now=14400.0), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "deadline", True)
    assert Km.charge_guards(cin(Km, now=14399.0, soc=89.0), ob, lim, act, "gentle") is None
    g = Km.charge_guards(cin(Km, now=14400.0), ob, lim, idle, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "window_end", False)
    g = Km.charge_guards(cin(Km, soc=90.0), ob, lim, act, "gentle")
    assert (g.reason, g.detail, g.end) == ("stop", "target_reached", True) and Km.charge_guards(cin(Km, soc=89.0), ob, lim, act, "gentle") is None
    assert Km.charge_guards(cin(Km, soc=92.0), ob, lim, idle, "gentle").end is False
    late = cin(Km, now=15500.0, soc=40.0, house=800.0, ac=8980.0)
    g = Km.charge_guards(late, cobj(Km, deadline=17400.0), Km.Limits(), act, "gentle")
    assert g is not None and g.detail == "target_guard", "finishing at the pre-session rate no longer fits: hand the charge back"
    assert Km.target_guard_trips(cin(Km, now=500.0, soc=50.0), ob, Km.Limits(), act) is False
    assert Km.target_guard_trips(late, cobj(Km, deadline=17400.0), Km.Limits(import_ceiling_w=9500.0), act) is False, "never hand back into an import breach"
    assert Km.target_guard_trips(late, cobj(Km, deadline=17400.0), Km.Limits(import_ceiling_w=12000.0), act) is True, "with room under the ceiling it does hand back"
    assert Km.target_guard_trips(late, cobj(Km, deadline=17400.0), Km.Limits(), Km.State()) is False
    # the boundary of the guard: it looks at the pessimistic finish at the pre-session rate against 25 minutes before the slot end (the 10 minute
    # end margin plus the 15 minute guard margin); at 80 percent the finish needs about 31 minutes
    ob2, gi = cobj(Km, deadline=17400.0), (lambda now, soc: cin(Km, now=now, soc=soc, house=800.0, ac=7071.0, inforce=6300.0))
    assert Km.target_guard_trips(gi(15000.0, 80.0), ob2, Km.Limits(), act) is True, "25 minutes left, the finish needs 31: hand back"
    assert Km.target_guard_trips(gi(14400.0, 80.0), ob2, Km.Limits(), act) is False, "35 minutes left: the lease goes on"
    assert Km.target_guard_trips(gi(16510.0, 80.0), ob2, Km.Limits(), act) is True, "past the margin and below the target: hand back"
    assert Km.target_guard_trips(gi(16440.0, 90.0), ob2, Km.Limits(), act) is False, "a reading at the target never trips it (no false 'at risk')"
    d = Km.charge_guards(gi(16440.0, 90.0), ob2, Km.Limits(), act, "gentle")
    assert (d.reason, d.detail, d.unreachable) == ("stop", "target_reached", False), d
    d = Km.charge_guards(gi(15000.0, 80.0), ob2, Km.Limits(), act, "gentle")
    assert (d.reason, d.detail, d.end, d.unreachable) == ("stop", "target_guard", True, True), "the hand-back is reported at risk (F02)"


def u_plan_charge(Km):
    ob, lim = cobj(Km), Km.Limits()
    st0 = Km.State()
    d = Km.plan_gentle(cin(Km), ob, lim, st0)
    assert (d.reason, d.detail, d.write_w) == ("increase", "start", 6500.0), d
    t = Km.plan_gentle(cin(Km, soc=8.0), Km.ChargeObjective(100.0, 10800.0, 14400.0, 35.0), lim, st0)
    assert (t.reason, t.detail) == ("unreachable", "deadline") and t.write_w is None and t.unreachable
    assert Km.plan_gentle(cin(Km, ac=500.0), ob, lim, st0).detail == "no_charge_running" and Km.plan_gentle(cin(Km, inforce=500.0), ob, lim, st0).detail == "implausible_gain"
    assert Km.plan_gentle(cin(Km, soc=92.0), ob, lim, st0).detail == "target_reached"
    imp = Km.plan_gentle(cin(Km, house=4000.0, ac=8980.0), ob, Km.Limits(import_ceiling_w=11000.0), st0)
    assert (imp.reason, imp.detail) == ("reduce", "import_ceiling") and imp.write_w == 6000.0, imp
    act = replace(Km.note_start(Km.State(), 300.0, 8000.0, GAIN, 6300.0, pre_ac_w=8980.0), pending_judge=False)
    run_in = lambda now, soc: cin(Km, now=now, soc=soc, house=800.0, ac=7070.0, inforce=6300.0)
    d = Km.plan_gentle(run_in(1000.0, 26.0), ob, lim, act)
    assert (d.reason, d.detail, d.wanted_w) == ("hold", "dwell", 6700.0), d
    d = Km.plan_gentle(run_in(2200.0, 30.0), ob, lim, act)
    assert (d.reason, d.detail, d.write_w) == ("increase", "behind_plan", 6900.0), d
    d = Km.plan_gentle(run_in(9000.0, 70.0), ob, lim, act)
    assert (d.reason, d.detail) == ("hold", "on_plan"), d
    d = Km.plan_gentle(run_in(7000.0, 85.0), ob, lim, act)
    assert (d.reason, d.detail, d.write_w) == ("reduce", "ahead_of_plan", 4300.0), d
    d = Km.plan_gentle(run_in(7000.0, 40.0), ob, lim, act)
    assert (d.reason, d.detail, d.write_w) == ("unreachable", "at_risk", 8000.0), d
    assert Km.plan_gentle(run_in(7000.0, 40.0), ob, lim, replace(act, last_write_s=6500.0)).write_w is None
    d = Km.plan_gentle(run_in(6000.0, 51.5), ob, lim, act)
    assert (d.reason, d.detail, d.write_w) == ("increase", "behind_plan", 6600.0), "a needed raise of under 300 W is made a full 300 W so that the budget's deadband lets it through"
    d = Km.plan_gentle(run_in(6000.0, 59.0), ob, lim, act)
    assert (d.reason, d.detail) == ("hold", "on_plan"), "a lower rate that saves under 500 W is not worth a change"
    d = Km.plan_gentle(run_in(6000.0, 59.5), ob, lim, act)
    assert (d.reason, d.detail, d.write_w) == ("reduce", "ahead_of_plan", 5800.0), d
    d = Km.plan_gentle(run_in(9000.0, 60.0), ob, lim, replace(act, changes=6))
    assert (d.reason, d.detail, d.write_w) == ("hold", "budget", None), d
    d = Km.plan_gentle(cin(Km, now=300.0, soc=25.0, ac=6000.0 * GAIN, inforce=6000.0), ob, lim, st0)
    assert d.unreachable and d.write_w is None, "a pre-session rate that is too low cannot be raised by a lease: the plan says so"
    prog = Km.charge_progress(run_in(2200.0, 30.0), ob, lim, act)
    assert prog["cands"][-1] == prog["ceiling_ac"] == 8980.0 and prog["cands"][-2] == 8900.0, "the exact ceiling is a feasibility candidate (N06)"
    ob95 = cobj(Km, target=95.0)
    d = Km.plan_gentle(run_in(1000.0, 90.0), ob95, lim, act)
    assert (d.reason, d.detail) == ("hold", "past_knee"), "at the knee nothing is lowered: a change there could only slow the charge (N07)"
    assert Km.charge_progress(run_in(7000.0, 89.0), ob95, lim, act)["past"] is True and Km.charge_progress(run_in(7000.0, 88.0), ob95, lim, act)["past"] is False, \
        "the knee test adds half the reading's resolution and its noise (N12)"
    st13 = replace(act, v_w=4900.0, last_write_s=0.0, writes=2, changes=1)
    in13 = cin(Km, now=9000.0, soc=30.0, house=4000.0, ac=4900.0 * GAIN, inforce=4900.0)
    lim13 = Km.Limits(import_ceiling_w=11000.0)
    p13 = Km.charge_progress(in13, ob, lim13, st13)
    assert p13["ceiling_name"] == "import" and p13["ceiling_sp"] == 5000.0
    d = Km.plan_gentle(in13, ob, lim13, st13)
    assert d.write_w is None or d.write_w <= 5000.0, "a raise never goes above what the import ceiling leaves (N13)"
    for why in ("dwell", "budget", "deadband", "reversal", "no_change_needed"):
        h = Km._hold(act, run_in(2000.0, 30.0), why, 6300.0, 6700.0)
        assert (h.reason, h.detail) == ("hold", why) and "?" not in h.explanation, why
    assert Km.plan_gentle(cin(Km, now=2000.0, soc=26.0, age=46.0, ac=7070.0, inforce=6300.0), ob, lim, act).detail == "stale_short"
    assert Km.plan_gentle(cin(Km, now=2000.0, soc=26.0, age=45.0, ac=7070.0, inforce=6300.0), ob, lim, act).detail != "stale_short"
    d = Km.plan_gentle(run_in(7000.0, 70.0), ob, Km.Limits(power_ceiling_w=5000.0), replace(act, last_write_s=0.0))
    assert (d.reason, d.detail, d.write_w) == ("reduce", "power_ceiling", 5000.0), d
    # the watch after a lease (F02): report only, on the rate in force
    wt = lambda now, soc, **kw: Km.plan_watch(cin(Km, now=now, soc=soc, house=800.0, ac=7070.0, inforce=6300.0, **kw), ob, lim, st0)
    d = wt(7000.0, 40.0)
    assert d.unreachable and d.reason == "unreachable" and d.write_w is None and not d.end and d.detail in ("at_risk", "deadline"), d
    d = wt(1000.0, 60.0)
    assert (d.reason, d.detail, d.write_w, d.end) == ("hold", "on_plan", None, False), d
    assert wt(7000.0, 92.0).detail == "target_reached" and wt(14400.0, 60.0).detail == "window_end" and wt(7000.0, 40.0, hold=True).detail == "owner_hold"
    assert Km.plan_watch(cin(Km, now=7000.0, soc=40.0, ac=500.0), ob, lim, st0).detail == "no_charge_running"
    assert wt(7000.0, 40.0, time_ok=False).detail == "time_untrusted" and wt(7000.0, 40.0, age=91.0).detail == "stale_telemetry"
    fx = Km.plan_charge_fixed(Km.Inputs(now_s=300.0, frame=Km.Frame(soc_pct=30.0, age_s=0.0, grid_w=800.0, inv_ac_w=0.0, pv_w=0.0)), ob, lim, st0, owner_rate_w=8000.0)
    assert (fx.reason, fx.detail, fx.write_w) == ("increase", "start", 8000.0), fx
    lo = Km.plan_charge_fixed(Km.Inputs(now_s=300.0, frame=Km.Frame(soc_pct=10.0, age_s=0.0, grid_w=800.0, inv_ac_w=0.0, pv_w=0.0)), cobj(Km, target=100.0), lim, st0, owner_rate_w=2000.0)
    assert (lo.reason, lo.detail, lo.write_w) == ("unreachable", "deadline", 2000.0), lo
    assert Km.plan_charge_fixed(Km.Inputs(now_s=300.0, frame=Km.Frame(soc_pct=30.0, age_s=0.0, grid_w=800.0, inv_ac_w=0.0, pv_w=0.0)), ob, Km.Limits(import_ceiling_w=1000.0), st0).detail == "no_headroom"
    assert Km.plan_charge_fixed(cin(Km), ob, lim, Km.State(phase="active", v_w=8000.0)).detail == "fixed_rate"


def u_export(Km):
    eo = Km.ExportObjective(2000.0, 20.0, 7000.0, 35.0, 3000.0)
    lim = Km.Limits(max_export_w=5000.0)
    fr = lambda soc=80.0, age=0.0, grid=1000.0, pv=0.0, inv=0.0, batt=0.0: Km.Frame(soc_pct=soc, age_s=age, grid_w=grid, inv_ac_w=inv, pv_w=pv, batt_w=batt)
    d = Km.plan_export(inputs(Km, 15.0, fr()), eo, lim, Km.State())
    assert (d.reason, d.detail, d.write_w) == ("increase", "feed_forward", 2000.0) and abs(d.stop_soc_pct - (20.0 + 1.0 + 3000 * 120 / 3600 / 1000 / 35 * 100)) < 1e-9, d
    d = Km.plan_export(inputs(Km, 15.0, fr(grid=1300.0)), Km.ExportObjective(500.0, 20.0, 7000.0, 35.0, 3000.0), lim, Km.State())
    assert d.write_w == 1800.0, d
    d = Km.plan_export(inputs(Km, 15.0, fr(pv=3500.0)), eo, lim, Km.State())
    assert (d.reason, d.detail, d.write_w) == ("unreachable", "infeasible_low", None) and d.unreachable
    d = Km.plan_export(inputs(Km, 15.0, fr(pv=3150.0)), eo, lim, Km.State())
    assert d.detail != "infeasible_low", "exactly 150 W under is the deadband"
    d = Km.plan_export(inputs(Km, 15.0, fr(grid=5000.0)), eo, lim, Km.State())
    assert (d.reason, d.detail, d.write_w) == ("unreachable", "infeasible_high", 2000.0)
    d = Km.plan_export(inputs(Km, 15.0, fr(grid=1000.0)), eo, lim, Km.State())
    assert d.detail == "feed_forward" and d.write_w == 2000.0, "needing exactly the ceiling is feasible"
    d = Km.plan_export(inputs(Km, 15.0, fr(grid=1001.0)), eo, lim, Km.State())
    assert d.detail == "infeasible_high"
    d = Km.plan_export(inputs(Km, 15.0, fr(soc=21.0)), eo, lim, Km.State())
    assert (d.reason, d.detail) == ("blocked", "no_headroom"), "no energy above the floor: nothing starts"
    for kw, want in ((dict(grid_ok=False), "grid_lost"), (dict(hold=True), "owner_hold"), (dict(time_ok=False), "time_untrusted"), (dict(dongle_ok=False), "dongle_unavailable")):
        assert Km.plan_export(inputs(Km, 15.0, fr(), **kw), eo, lim, Km.State()).detail == want, want
    assert Km.plan_export(inputs(Km, 15.0, fr(age=91.0)), eo, lim, Km.State()).detail == "stale_telemetry"
    assert Km.plan_export(inputs(Km, 15.0, fr()), eo, lim, Km.State(), authority_free=False).detail == "authority_busy"
    assert Km.plan_export(inputs(Km, 7000.0, fr()), eo, lim, Km.State()).detail == "no_headroom"
    run = Km.State(phase="active", v_w=2000.0, stop_soc_pct=21.3, last_update_s=0.0)
    d = Km.plan_export(inputs(Km, 600.0, fr(grid=-1900.0, inv=2900.0)), eo, lim, run)
    assert (d.reason, d.detail) == ("hold", "tracking") and d.stop_soc_pct is None
    d = Km.plan_export(inputs(Km, 600.0, fr(grid=-1900.0, inv=2900.0), reserve_pct=40.0), eo, lim, run)
    assert d.stop_soc_pct is not None and d.stop_soc_pct > 40.0, "a higher reserve asks for a raise of the Stop SOC"
    d = Km.plan_export(inputs(Km, 600.0, fr(soc=41.0, grid=-1900.0, inv=2900.0), reserve_pct=60.0), eo, lim, run)
    assert (d.reason, d.detail, d.end) == ("stop", "reserve_rose", True), d
    d = Km.plan_export(inputs(Km, 600.0, fr(soc=21.3, grid=-1900.0, inv=2900.0)), eo, lim, run)
    assert (d.reason, d.detail, d.end) == ("stop", "floor_reached", True) and Km.plan_export(inputs(Km, 600.0, fr(soc=21.4, grid=-1900.0, inv=2900.0)), eo, lim, run).reason == "hold"
    d = Km.plan_export(inputs(Km, 600.0, fr(soc=21.0, grid=-1900.0, inv=2900.0), reserve_pct=60.0), eo, lim, run)
    assert (d.reason, d.detail, d.end) == ("stop", "reserve_rose", True), "the latched Stop SOC trips first but the reserve rose above it: say so (N02)"
    d = Km.plan_export(inputs(Km, 600.0, fr(soc=50.0, grid=3000.0, inv=2900.0), reserve_pct=40.0), eo, lim, run)
    assert d.detail == "infeasible_high" and d.stop_soc_pct is not None and d.stop_soc_pct > 40.0, "a reserve rise is relayed while the target is infeasible too (N03)"
    d = Km.plan_export(inputs(Km, 600.0, fr(pv=3500.0, grid=-1900.0, inv=2900.0)), eo, lim, run)
    assert (d.reason, d.detail) == ("unreachable", "infeasible_low") and d.write_w is None
    assert Km.export_required_w(fr(grid=1000.0, pv=200.0), 2000.0) == 2800.0 and Km.export_required_w(replace(fr(), pv_w=None), 2000.0) is None
    assert abs(Km.export_energy_kwh(50.0, 20.0, 35.0) - 0.3 * 35.0 * 0.94) < 1e-9 and Km.export_energy_kwh(10.0, 20.0, 35.0) == 0.0
    assert abs(Km.export_duration_s(50.0, 20.0, 35.0, 3000.0) - 0.3 * 35.0 * 0.94 * 0.9 * 1000.0 / 3000.0 * 3600.0) < 1e-6 and Km.export_duration_s(50.0, 20.0, 35.0, 0.0) == Km.INF
    eo2 = Km.ExportObjective(2000.0, 20.0, 7000.0, 35.0, 3000.0)
    assert abs(Km.export_floor_pct(eo2, 40.0) - Km.stop_soc_with_margin(40.0, 20.0, 3000.0, 35.0)) < 1e-12


def u_export_tick(Km):
    eo, lim = Km.ExportObjective(2000.0, 20.0, 7000.0, 35.0, 3000.0), Km.Limits(max_export_w=5000.0)
    st = Km.State(phase="active", v_w=2000.0, stop_soc_pct=21.3, last_update_s=0.0)
    f = lambda soc=60.0, age=0.0, grid=-1900.0, batt=2200.0: Km.Frame(soc_pct=soc, age_s=age, grid_w=grid, inv_ac_w=2900.0, pv_w=0.0, batt_w=batt)
    d, _ = Km.export_tick(inputs(Km, 600.0, f()), eo, lim, st)
    assert (d.reason, d.detail) == ("hold", "tracking")
    d, _ = Km.export_tick(inputs(Km, 600.0, f(soc=21.3)), eo, lim, st)
    assert (d.reason, d.detail, d.end) == ("stop", "floor_reached", True) and Km.export_tick(inputs(Km, 600.0, f(soc=21.4)), eo, lim, st)[0].end is False
    d, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-6300.0)), eo, lim, st)
    assert (d.detail, d.end) == ("export_over_limit", True)
    d, st2 = Km.export_tick(inputs(Km, 600.0, f(grid=-5200.0)), eo, lim, st)
    assert d.end is False and st2.export_over is True
    d, _ = Km.export_tick(inputs(Km, 615.0, f(grid=-5200.0)), eo, lim, st2)
    assert (d.detail, d.end) == ("export_over_limit", True)
    d, st3 = Km.export_tick(inputs(Km, 600.0, f(batt=3751.0)), eo, lim, st)
    assert d.end is False and st3.abs_over == 1
    d, _ = Km.export_tick(inputs(Km, 615.0, f(batt=3751.0)), eo, lim, st3)
    assert (d.detail, d.end) == ("runaway", True), "the absolute backstop trips on the second sample, grace or not"
    d, _ = Km.export_tick(inputs(Km, 600.0, f(batt=3750.0)), eo, lim, replace(st3, abs_over=1))
    assert d.end is False
    # one count per NEW reading: the same 3751 W reading seen again 15 s later, in a telemetry gap, is not a second sample (F08)
    d, st4 = Km.export_tick(inputs(Km, 615.0, f(age=15.0, batt=3751.0)), eo, lim, st3)
    assert d.end is False and st4.abs_over == 1, "a repeated reading does not advance the counters"
    d, _ = Km.export_tick(inputs(Km, 630.0, f(age=0.0, batt=3751.0)), eo, lim, st4)
    assert (d.detail, d.end) == ("runaway", True), "the next NEW reading does"
    # the transition window: 4667 W after a step from 4200 to 3400 W is under the old ceiling's threshold for 30 s, over the new one's after it
    wr = Km.State(phase="active", v_w=3400.0, ref_w=4200.0, stop_soc_pct=21.3, last_update_s=600.0, active_since_s=0.0)
    eo8, lim8 = Km.ExportObjective(2000.0, 20.0, 9000.0, 35.0, 8000.0), Km.Limits()
    fb = lambda batt, age=0.0: Km.Frame(soc_pct=60.0, age_s=age, grid_w=-2000.0, inv_ac_w=3000.0, pv_w=0.0, batt_w=batt)
    assert Km.export_tick(inputs(Km, 615.0, fb(4667.0)), eo8, lim8, wr)[1].abs_over == 0, "inside the transition the higher ceiling is the reference"
    assert Km.export_tick(inputs(Km, 645.0, fb(4667.0)), eo8, lim8, wr)[1].abs_over == 1, "after it the new, lower ceiling is"
    # ONE grace, from the lease start: a write does not re-arm it, the start does (F08)
    gr = replace(wr, last_update_s=590.0, ref_w=3400.0, active_since_s=0.0, over_samples=2, abs_over=1)
    st_g = Km.export_tick(inputs(Km, 600.0, fb(9000.0)), eo8, lim8, gr)
    assert st_g[0].detail == "runaway", "a write 10 s ago does not silence the guard"
    st_h = Km.export_tick(inputs(Km, 20.0, fb(9000.0)), eo8, lim8, replace(gr, last_update_s=0.0, active_since_s=0.0))
    assert st_h[0].end is False and st_h[1].over_samples == 0 and st_h[1].abs_over == 0, "inside the 30 s after the START the counters stay at zero"
    d, _ = Km.export_tick(inputs(Km, 615.0, f(age=91.0)), eo, lim, st)
    assert (d.detail, d.end) == ("stale_telemetry", True)
    d, _ = Km.export_tick(inputs(Km, 615.0, f(), time_ok=False), eo, lim, st)
    assert d.detail == "time_untrusted" and Km.export_tick(inputs(Km, 615.0, f(), grid_ok=False), eo, lim, st)[0].detail == "grid_lost"
    d, _ = Km.export_tick(inputs(Km, 7000.0, f()), eo, lim, st)
    assert d.detail == "lease_end"
    d, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-1600.0)), eo, lim, st)
    assert (d.reason, d.detail, d.write_w) == ("increase", "export_short", 2200.0)
    d, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-2400.0)), eo, lim, st)
    assert (d.reason, d.detail, d.write_w) == ("reduce", "export_over", 1800.0)
    d, _ = Km.export_tick(inputs(Km, 620.0, f(grid=-1600.0)), eo, lim, replace(st, last_update_s=600.0))
    assert (d.reason, d.detail) == ("hold", "settling")
    sat, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-2700.0)), eo, lim, replace(st, v_w=500.0))
    assert (sat.reason, sat.detail) == ("hold", "saturated_low")
    sat, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-1000.0)), eo, lim, replace(st, v_w=3000.0))
    assert (sat.reason, sat.detail) == ("hold", "saturated_high")
    low = replace(st, low_streak=1)
    d, _ = Km.export_tick(inputs(Km, 600.0, Km.Frame(soc_pct=60.0, age_s=0.0, grid_w=-3000.0, inv_ac_w=4000.0, pv_w=4000.0, batt_w=600.0)), eo, lim, low)
    assert (d.reason, d.detail) == ("unreachable", "infeasible_low")
    high = replace(st, high_streak=1)
    d, _ = Km.export_tick(inputs(Km, 600.0, Km.Frame(soc_pct=60.0, age_s=0.0, grid_w=0.0, inv_ac_w=2900.0, pv_w=0.0, batt_w=3000.0)), eo, lim, replace(high, v_w=3000.0))
    assert (d.reason, d.detail) == ("unreachable", "infeasible_high")
    d, _ = Km.export_tick(inputs(Km, 600.0, f(grid=-1000.0)), eo, lim, replace(st, no_resp_since_s=590.0))
    assert (d.reason, d.detail) == ("hold", "no_response")


def u_observe(Km):
    st = Km.State()
    load = lambda t, w: Km.Inputs(now_s=t, frame=Km.Frame(soc_pct=50.0, age_s=0.0, grid_w=w, inv_ac_w=0.0, pv_w=0.0))
    for i in range(40):
        st = Km.observe(st, load(15.0 * i, 1000.0))
    assert Km.house_peak_w(st, 585.0) == 1000.0
    for i in range(40, 52):
        st = Km.observe(st, load(15.0 * i, 4000.0))                 # a 3 minute burst
    for i in range(52, 92):
        st = Km.observe(st, load(15.0 * i, 1000.0))
    assert abs(Km.house_peak_w(st, 15.0 * 91) - (12 * 4000.0 + 8 * 1000.0) / 20.0) < 1e-6, "a 3 minute burst is diluted to its 5 minute mean"
    st = Km.State()
    for i in range(120):
        st = Km.observe(st, load(15.0 * i, 4000.0))
    assert Km.house_peak_w(st, 15.0 * 119) == 4000.0, "a sustained load is not diluted"
    assert Km.house_peak_w(st, 15.0 * 119 + 1800.0) is None, "the memory is one dwell long"
    stale = Km.observe(Km.State(), Km.Inputs(now_s=10.0, frame=Km.Frame(soc_pct=50.0, age_s=91.0, grid_w=1000.0, inv_ac_w=0.0)))
    assert stale.house_hist == ()
    ob = cobj(Km)
    st = Km.State()

    def tick(st, now, soc, ac):
        return Km.observe(st, Km.Inputs(now_s=now, frame=Km.Frame(soc_pct=soc, age_s=0.0, grid_w=ac + 800.0, inv_ac_w=-ac, pv_w=0.0)), ob)
    st = tick(st, 0.0, 30.0, 6000.0)
    st = tick(st, 900.0, 34.0, 6000.0)
    assert st.acc_t0 == 0.0 and st.eff_scale == 1.0
    st = tick(st, 1800.0, 38.0, 6000.0)     # 3 kWh AC, 8 points: 2.67 points per kWh against the pessimistic 2.35: fine, the window restarts
    assert st.eff_scale == 1.0 and st.acc_t0 == 1800.0
    st = tick(st, 2700.0, 40.0, 6000.0)
    st = tick(st, 3600.0, 41.0, 6000.0)     # 6 kWh AC for 3 points so far: judged only once 8 points have been seen
    assert st.eff_scale == 1.0, "fewer than 8 points are not judged (one point of reading error would be 12 percent or more)"
    st = tick(st, 4500.0, 44.0, 6000.0)
    st = tick(st, 5400.0, 46.0, 6000.0)     # 8 points for 9 kWh: 0.89 points per kWh against 2.35: the progress is far worse than the pessimistic world
    assert st.eff_scale == 0.6, st.eff_scale
    low = st.eff_scale
    st = tick(st, 6300.0, 56.0, 6000.0)
    st = tick(st, 7200.0, 66.0, 6000.0)
    st = tick(st, 8100.0, 76.0, 6000.0)
    assert st.eff_scale == low, "a better progress is never credited"
    st = tick(st, 5500.0, 63.0, 500.0)
    assert st.acc_t0 is None, "the window restarts when no charge runs"
    st = tick(replace(st, eff_scale=1.0), 6000.0, 91.0, 6000.0)
    assert st.acc_t0 is None, "above the knee the progress is not judged"
    c = Km.carry_memory(Km.State(v_w=5000.0), replace(Km.State(), eff_scale=0.8, house_hist=((1.0, 2.0),), acc_t0=3.0))
    assert (c.v_w, c.eff_scale, c.house_hist, c.acc_t0) == (5000.0, 0.8, ((1.0, 2.0),), 3.0)


def u_lists(Km):
    assert Km.REASONS == ("increase", "reduce", "hold", "stop", "unreachable", "blocked")
    pairs = {(r, d) for r, ds in Km.DETAILS.items() for d in ds}
    assert set(Km.DETAILS) == set(Km.REASONS) and pairs == {k for k in Km.EXPLAIN}, "every (reason, detail) has exactly one sentence"
    d = Km.make("hold", "dwell", v_w=6000.0, since_min=12.0, dwell_min=30.0)
    assert "6000" in d.explanation and "12" in d.explanation and "30" in d.explanation and d.numbers
    assert Km.explain("zzz", "yyy", ()).startswith("No explanation") and Km.make("stop", "grid_lost", end=True).end
    assert Km._fmt(None) == "n/a" and Km._fmt(NAN) == "n/a" and Km._fmt(2.04) == "2" and Km._fmt(2.5) == "2.5" and Km._fmt(1234.56) == "1235" and Km._fmt("x") == "x"


UNITS = [("is_fresh and frame_fresh", u_fresh), ("house load and AC input", u_house), ("time trust", u_time), ("Stop SOC margin", u_margin),
         ("guard order", u_guard_order), ("ramp limit (charge budgets)", u_ramp), ("export loop (the Dump law)", u_export_loop), ("runaway and export trip", u_runaway),
         ("feasibility maths", u_feasibility), ("gain and response", u_measure_and_judge), ("charge guards", u_guards), ("charge policies", u_plan_charge),
         ("export policy", u_export), ("export tick", u_export_tick), ("planner memory and progress tracker", u_observe), ("closed lists", u_lists)]


def first_unit_failure(Km):
    for name, fn in UNITS:
        try:
            fn(Km)
        except BaseException as exc:      # an assertion or any crash of the mutated code is a kill
            return f"{name}: {type(exc).__name__} {str(exc)[:80]}"
    return None


EXERCISED: set = set()
_real_make = K.make


def _recording_make(reason, detail, *a, **kw):
    EXERCISED.add((reason, detail))
    return _real_make(reason, detail, *a, **kw)


K.make = _recording_make       # record every (reason, detail) the kernel builds while the units and the scenarios run
def u_bench_no_response(Bm=B):
    """The second weak response ends a Gentle lease (the dongle model's rule, GRC max_ineffective 2): drive the dongle tick directly."""
    sc = replace(S.SPEC_BY_NAME["g01_nominal"].sc, duration_s=1800.0)
    b = Bm.Bench(sc, K)
    b.go()
    lease = b.lease
    assert lease is not None and lease.kind == "gentle"
    t = 1800.0
    ac = K.ac_in_w(b.frame(t))
    pending = replace(lease.st, weak=1, pending_judge=True, pre_v_w=lease.st.v_w + 1000.0, pre_ac_w=ac + 10.0, last_write_s=t - 100.0)
    lease.st = pending
    inp = K.Inputs(now_s=t, frame=b.frame(t), grid_ok=True, time_ok=True, hold=False, reserve_pct=20.0, in_force_w=lease.st.v_w, dongle_ok=True)
    n = len(b.run.recs)
    b.charge_tick(t, lease, inp)
    last = b.run.recs[n:]
    return b.lease is None and lease.end_reason == "no_response" and any((r.reason, r.detail) == ("blocked", "no_response") and r.end for r in last)


check("bench unit: the second weak response ends the lease through the restore and says blocked / no_response", u_bench_no_response())
for name, fn in UNITS:
    try:
        fn(K)
        check(f"unit: {name}", True)
    except BaseException as exc:
        check(f"unit: {name}", False, f"{type(exc).__name__}: {exc}")

# ===========================================================================
print("")
print("[4] closed lists and explanations")
# ===========================================================================
RUNS = {}
for spec in S.SPECS:
    RUNS[spec.sc.name] = S.run_spec(spec, K)
emitted = set()
for _run, _res in RUNS.values():
    for r in _run.recs:
        emitted.add((r.reason, r.detail))
all_pairs = {(r, d) for r, ds in K.DETAILS.items() for d in ds}
K.make = _real_make        # the recorder is removed: the rest of the suite runs the kernel as it is
check("no (reason, detail) of the closed list is dead: every pair was built at least once by the unit tables or the scenarios",
      all_pairs <= EXERCISED, str(sorted(all_pairs - EXERCISED)))
print(f"  info  the scenario catalogue alone emits {len(emitted & all_pairs)} of the {len(all_pairs)} (reason, detail) pairs; the rest come from the unit tables")
check("no scenario emits a pair outside the closed list", emitted <= all_pairs, str(sorted(emitted - all_pairs)))
check("no explanation emitted by any scenario has an unfilled number or an empty sentence",
      all(r.explanation.strip() and "?" not in r.explanation for run, _ in RUNS.values() for r in run.recs))
check("every closed-list reason is used by some scenario", {r for r, _d in emitted} == set(K.REASONS))

# ===========================================================================
print("")
print("[5] scenarios")
# ===========================================================================
check("the catalogue has at least 30 named scenarios", len(S.SPECS) >= 30, str(len(S.SPECS)))
check("scenario names are unique", len({s.sc.name for s in S.SPECS}) == len(S.SPECS))
for kind in ("gentle", "charge_fixed", "export"):
    check(f"the catalogue has scenarios for the {kind} policy", sum(1 for s in S.SPECS if s.sc.kind == kind) >= 3)
REQUIRED_THEMES = ("heavy_overnight_load", "load_removal", "kettle", "efficiency", "high_start_soc", "low_start_soc", "taper_cliff_98", "unit_wrong_x10",
                   "target_already_reached", "delayed_commands", "start_command_lost", "telemetry", "restart_in_lease", "dead_dongle", "ha_outage", "plan_lost",
                   "rtc_untrusted", "grid_loss", "import_ceiling", "two_policies", "hold_pressed", "reserve_rises", "pv_cloud", "pv_evening_drop", "runaway",
                   "house_step_up", "house_step_down", "infeasible", "inverter_ignores_write", "export_over_limit")
names = " ".join(s.sc.name for s in S.SPECS)
for theme in REQUIRED_THEMES:
    check(f"a scenario covers the theme '{theme}'", theme in names)
for spec in S.SPECS:
    run, res = RUNS[spec.sc.name]
    check(f"scenario {spec.sc.name}: {res.outcome}; {sum(1 for v in res.inv.values() if v[0])} of {sum(1 for v in res.inv.values() if v[0] is not None)} invariants hold", res.ok,
          "; ".join(res.failures)[:300])
check("the dead-dongle export is a DOCUMENTED gap that fails exactly its reserve invariant and shows its backstop",
      S.SPEC_BY_NAME["e13_dead_dongle"].known_gap and RUNS["e13_dead_dongle"][1].inv["RESERVE_FLOOR"][0] is False and RUNS["e13_dead_dongle"][1].ok)
check("determinism: running a scenario twice gives the same rows and writes",
      B.run_scenario(S.SPEC_BY_NAME["g03_heavy_load_import_ceiling"].sc, K).rows == RUNS["g03_heavy_load_import_ceiling"][0].rows
      and B.run_scenario(S.SPEC_BY_NAME["e02_house_step_up"].sc, K).writes == RUNS["e02_house_step_up"][0].writes)
check("the failing (scenario, invariant) pairs of the catalogue equal the pinned set exactly (documented gaps and pinned findings): a fix flips its pin red, a new failure fails",
      S.failing_pairs([r for _run, r in RUNS.values()]) == S.pinned_pairs(S.SPECS), str(sorted(S.failing_pairs([r for _run, r in RUNS.values()]) ^ S.pinned_pairs(S.SPECS))))
FINDINGS = [(sp.sc.name, f) for sp in S.SPECS for f in sp.known_finding]
check("every pinned finding names its invariant, an id and a one-line reason", bool(FINDINGS) and all(len(f) == 3 and f[0] in S.INVARIANTS and f[1] and f[2] and "\n" not in f[2] for _n, f in FINDINGS))
check("the catalogue pins finding F01 (a restore into a breach) on at least two scenarios", sum(1 for _n, f in FINDINGS if f[1] == "F01") >= 2)
req_text = read("docs/dev/dynamic-energy-control/REQUIREMENTS.md")
req_ids = set(re.findall(r"\| (REQ-[A-D]\d+) \|", req_text))
used = {rid for s in S.SPECS for rid in s.covers}
check("every requirement id a scenario names exists in REQUIREMENTS.md", used <= req_ids, str(sorted(used - req_ids)))
rows = {m.group(1): m.group(0) for m in re.finditer(r"^\| (REQ-[A-D]\d+) \|.*$", req_text, re.M)}
missing = []
for s in S.SPECS:
    for rid in s.covers:
        if s.sc.name not in rows.get(rid, ""):
            missing.append((rid, s.sc.name))
check("the 'Covered by' column of REQUIREMENTS.md names every scenario that claims the requirement", not missing, str(missing[:3]))
stale = [rid for rid, row in rows.items() if "sim:" in row and rid not in used]
check("no requirement row points at the simulator without a scenario claiming it", not stale, str(stale[:3]))

# ===========================================================================
print("")
print("[5b] the invariants themselves, judged on hand-made runs: each must be able to fail, and to pass")
# ===========================================================================
def mkrow(t, grid=0.0, house=800.0, ac_in=0.0, lease=0, slot_w=8000.0, fp_w=0.0, dump_w=0.0, batt=0.0, mode="slot_charge", ceil=11000.0, soc=50.0):
    return B.Row(t, soc, round(soc), batt, grid, house, 0.0, -ac_in, mode, slot_w, dump_w, fp_w, lease, 0.0, ac_in, 20.0, ceil, True, True)


def mkrun(sc, rows, leases=(), writes=(), recs=()):
    return types.SimpleNamespace(sc=sc, rows=list(rows), leases=list(leases), writes=list(writes), recs=list(recs), alerts=[], refusals=[], first_unreachable_t=None)


def breach_rows(t0, n, lease=0, ceil=11000.0, grid=12000.0, house=2000.0, ac_in=10000.0, slot_w=8000.0):
    return [mkrow(t0 + i * 15.0, grid=grid, house=house, ac_in=ac_in, lease=lease, ceil=ceil, slot_w=slot_w) for i in range(n)]


def quiet_rows(t0, n, lease=0, ceil=11000.0, slot_w=8000.0):
    return [mkrow(t0 + i * 15.0, grid=3000.0, house=2000.0, ac_in=1000.0, lease=lease, ceil=ceil, slot_w=slot_w) for i in range(n)]


quiet_sc = replace(S.SPEC_BY_NAME["g03_heavy_load_import_ceiling"].sc, house=P.Series([(0.0, 2000.0)]), react_s=120.0, plan_s=300.0, cmd_delay_s=0.0, tel_gaps=())
L1 = dict(id=1, kind="gentle", owner="gentle", start_t=600.0, end_t=3000.0, reason="deadline", soc_start=30.0, soc_end=60.0, writes=1, changes=0, fault=False, planned_end=3000.0)
cls = lambda run: sorted({k for k, _t in S.import_analysis(run)["violations"]})
r_ok = mkrun(quiet_sc, quiet_rows(15, 39) + breach_rows(600, 2, lease=1) + quiet_rows(630, 10, lease=1) + quiet_rows(3000, 5), [L1])
check("IMPORT_CEILING (crafted): a breach the dongle's guard clears in two ticks is fine", S.inv_import_ceiling(r_ok)[0] is True, S.inv_import_ceiling(r_ok)[1])
r_react = mkrun(quiet_sc, breach_rows(15, 30) + quiet_rows(465, 10), [])
check("IMPORT_CEILING (crafted): a breach before any session that outlasts the declared reaction fails (class react)", cls(r_react) == ["react"], str(cls(r_react)))
r_guard = mkrun(quiet_sc, quiet_rows(15, 39) + breach_rows(600, 8, lease=1) + quiet_rows(720, 5, lease=1), [L1])
check("IMPORT_CEILING (crafted): a breach that outlasts the dongle's guard with a session open fails (class guard)", cls(r_guard) == ["guard"], str(cls(r_guard)))
r_gap = mkrun(replace(quiet_sc, tel_gaps=((600.0, 675.0),)), quiet_rows(15, 39) + breach_rows(600, 8, lease=1) + quiet_rows(720, 5, lease=1), [L1])
check("IMPORT_CEILING (crafted): the same breach is forgiven exactly as long as the telemetry gap that blinds the guard", cls(r_gap) == [], str(cls(r_gap)))
r_rest = mkrun(quiet_sc, quiet_rows(15, 39) + quiet_rows(600, 10, lease=1) + breach_rows(3000, 4), [dict(L1, end_t=2985.0)])
check("IMPORT_CEILING (crafted): a breach that starts right after the last END is the restore's and fails (class restore)", cls(r_rest) == ["restore"], str(cls(r_rest)))
r_late = mkrun(quiet_sc, quiet_rows(15, 39) + quiet_rows(600, 10, lease=1) + quiet_rows(3000, 10) + breach_rows(3150, 4), [L1])
check("IMPORT_CEILING (crafted): a breach that starts long after the last END is the owner's own and is not ECCO's", cls(r_late) == [] and S.import_analysis(r_late)["owner_rows"] == 4)
many = []
for k in range(4):
    many += quiet_rows(15 + k * 150, 9, lease=0) + breach_rows(15 + k * 150 + 135, 1)
check("IMPORT_CEILING (crafted): more breach episodes than the night's causes explain fail (class count)", "count" in cls(mkrun(quiet_sc, many, [])), str(cls(mkrun(quiet_sc, many, []))))
rr = quiet_rows(15, 20, lease=1, slot_w=5000.0) + [mkrow(315.0, grid=3000.0, house=2000.0, ac_in=1000.0, lease=1, slot_w=6000.0)]
rr += [mkrow(330.0, grid=12000.0, house=2000.0, ac_in=10000.0, lease=1, slot_w=6000.0)] + quiet_rows(345, 5, lease=1, slot_w=6000.0)
r_raise = mkrun(quiet_sc, rr, [dict(L1, start_t=15.0, end_t=420.0)], [B.Write(315.0, "gentle", 1, "change", "slot_power_w", 6000.0, True)])
check("IMPORT_CEILING (crafted): a breach that opens because ECCO's own change raised the charge power fails (class own_raise)", cls(r_raise) == ["own_raise"], str(cls(r_raise)))
rh = [mkrow(15.0 * i, grid=1800.0, house=800.0, ac_in=1000.0, lease=1, slot_w=5000.0) for i in range(1, 21)] + [mkrow(315.0, grid=1800.0, house=800.0, ac_in=1000.0, lease=1, slot_w=6000.0)]
rh += [mkrow(330.0, grid=13000.0, house=3000.0, ac_in=10000.0, lease=1, slot_w=6000.0)] + quiet_rows(345, 5, lease=1, slot_w=6000.0)
r_house = mkrun(quiet_sc, rh, [dict(L1, start_t=15.0, end_t=420.0)], [B.Write(315.0, "gentle", 1, "change", "slot_power_w", 6000.0, True)])
check("IMPORT_CEILING (crafted): the same raise while the house load stepped up by 2.2 kW is the house's doing, not ECCO's (no own_raise)", cls(r_house) == [], str(cls(r_house)))
check("IMPORT_CEILING (crafted): the owner's ceiling being absent makes the invariant not apply", S.inv_import_ceiling(mkrun(quiet_sc, [mkrow(15.0, ceil=None)], []))[0] is None)

ws = lambda *vals: [B.Write(15.0 * (i + 1), "export", 1, "loop", "dump_ceiling_w", v, True) for i, v in enumerate(vals)]
exp_sc = replace(S.SPEC_BY_NAME["e01_nominal"].sc)
check("NO_REWRITE (crafted): a write that repeats the value in force fails, a changed value passes",
      S.inv_no_rewrite(mkrun(exp_sc, [mkrow(15.0)], writes=ws(1000.0, 1000.0)))[0] is False and S.inv_no_rewrite(mkrun(exp_sc, [mkrow(15.0)], writes=ws(1000.0, 1100.0)))[0] is True)
mkrec = lambda age, detail="behind_plan", write=6000.0, who="ha": B.Rec(900.0, who, "gentle", "increase", detail, write, write, False, False, "x", age, None)
check("NO_STALE_DRIVE (crafted): a plan-driven change on a 60 s old frame fails, on a 40 s old frame and a safety reduction on an old frame pass",
      S.inv_no_stale_drive(mkrun(exp_sc, [mkrow(15.0)], recs=[mkrec(60.0)]))[0] is False and S.inv_no_stale_drive(mkrun(exp_sc, [mkrow(15.0)], recs=[mkrec(40.0)]))[0] is True
      and S.inv_no_stale_drive(mkrun(exp_sc, [mkrow(15.0)], recs=[mkrec(80.0, detail="import_ceiling")]))[0] is True)
exp_rows = lambda n, batt: [mkrow(15.0 * i, lease=1, dump_w=500.0, batt=batt, mode="export") for i in range(1, n + 1)]
check("COMMAND_FOLLOWED (crafted): 2.6 kW against a 500 W command for 150 s fails, for 45 s passes, the command itself passes",
      S.inv_command_followed(mkrun(exp_sc, exp_rows(10, 2600.0)))[0] is False and S.inv_command_followed(mkrun(exp_sc, exp_rows(3, 2600.0) + exp_rows(8, 600.0)))[0] is True
      and S.inv_command_followed(mkrun(exp_sc, exp_rows(10, 600.0)))[0] is True)
pc_sc = replace(S.SPEC_BY_NAME["g35_power_ceiling_lowered"].sc, events=((300.0, "power_ceiling", {"w": 4000.0}),))
pc_rows = lambda n: [mkrow(15.0 * i, lease=1, slot_w=5000.0) for i in range(1, n + 1)]
check("POWER_CEILING (crafted): a setpoint left above a lowered Power Ceiling for longer than a plan period fails (the state, not only the writes)",
      S.inv_power_ceiling(mkrun(pc_sc, pc_rows(60)))[0] is False and S.inv_power_ceiling(mkrun(pc_sc, pc_rows(5)))[0] is True)

# ===========================================================================
print("")
print("[6] plant parameters and the README tables")
# ===========================================================================
dflt = P.PlantParams()
check("every PARAMETERS row is a PlantParams field with the same default, and no field is missing from the table",
      all(getattr(dflt, n) == v for n, v, _u, _g, _s in P.PARAMETERS) and {n for n, *_ in P.PARAMETERS} == set(dflt.__dataclass_fields__))
check("every parameter has a grade from the fixed list and a source", all(g in ("MEASURED_REPLAY", "VERIFIED_LIVE", "ASSUMED", "UNMEASURED") and len(s) > 10 for _n, _v, _u, g, s in P.PARAMETERS))
unmeasured = [n for n, _v, _u, g, _s in P.PARAMETERS if g == "UNMEASURED"]
check("the charge behaviour below the top rate is a flagged, UNMEASURED parameter set (flag, knee, tail, response, unit, off-grid cap, whether the slot target stops a charge: R1)",
      {"taper_below_top_measured", "knee_soc_gentle_pct", "tail_gentle_dc_w", "charge_response", "unit_scale", "slot_caps_offgrid_discharge", "slot_target_stops_charge"} <= set(unmeasured)
      and dflt.taper_below_top_measured is False and dflt.slot_target_stops_charge is True)
assumed = [n for n, _v, _u, g, _s in P.PARAMETERS if g == "ASSUMED"]
check("the choices made without data are flagged ASSUMED parameters: the top-rate switch, the cliff's shape, the discharge lag, the PV efficiency",
      {"top_rate_threshold", "cliff_shape", "tau_discharge_s", "pv_eff"} <= set(assumed) and dflt.top_rate_threshold == 0.9 and dflt.cliff_shape == "linear" and dflt.tau_discharge_s == 15.0)
check("no UNMEASURED or ASSUMED behaviour is hard-coded in the plant: every PlantParams field is a PARAMETERS row (checked above) and the plant reads the three added ones",
      all(("p." + n) in (HERE / "plant.py").read_text(encoding="utf-8") for n in ("top_rate_threshold", "cliff_shape", "slot_target_stops_charge")))
check("the unit alternatives of the study are all parameter sets that run (AC watts, DC watts, the measured point, unbound, x10, /10)",
      set(P.UNIT_ALTERNATIVES) == {"ac_grid_watts", "dc_battery_watts", "h1_measured_point", "h2_h3_unbound", "wrong_x10", "wrong_div10"})
readme = (HERE / "SIM_README.md").read_text(encoding="utf-8")
cov = S.coverage_table_md()
par = P.parameter_table_md()
check("SIM_README.md carries the generated scenario table verbatim (run_sim.py --covers prints it)", cov in readme)
check("SIM_README.md carries the generated parameter table verbatim (run_sim.py --params prints it)", par in readme)
check("SIM_README.md states the size of the catalogue as the code counts it (run_sim.py --counts prints it)", S.catalogue_counts_md() in readme, S.catalogue_counts_md())
check("SIM_README.md names every invariant and every pinned finding id", all(n in readme for n in S.INVARIANTS) and all(f[1] in readme for _n, f in FINDINGS))
check("SIM_README.md names every pinned source file", all(s in readme for s in (FW_REL, PLAN_REL, "gentleNightProbe.golden.json", "GRC")))
check("SIM_README.md has the honest sections (what is pinned, what this does not prove, how a controller plugs in, how to add a scenario)",
      all(s in readme for s in ("What this does not prove", "How a later controller plugs in", "How to add a scenario", "What is pinned", "MEASURED versus ASSUMED")))

# the plant against the aggregates of the saved evidence (four nights at the top rate; one discharge characterisation): a replay of the numbers
def top_rate_night(soc0):
    pl = P.Plant(P.PlantParams(), soc0, regs=P.Regs(slot_power_w=8000.0))
    env = P.Env(house_w=800.0, pv_w=0.0, grid_up=True, window_active=True, slot_target_pct=100.0)
    trace = []
    for i in range(int(10 * 3600 / P.DT_S)):
        m = pl.step(P.DT_S, env)
        trace.append((m.t, m.soc_reading, -m.batt_w, m.ac_in_w, m.grid_w, m.soc_true))
    return trace


night = top_rate_night(27.0)
plateau = [x for x in night if x[2] > 7000.0]
t_98 = next(x[0] for x in night if x[1] >= 98.0)
t_below2 = next(x[0] for x in night if x[0] > plateau[-1][0] and x[2] < 2000.0)
trickle = [x[2] for x in night if x[0] > t_below2 and x[5] < 99.999 and 100.0 < x[2] < 1000.0]   # until the battery is full
check("replay of the 18 Nov night: 27 to 98 percent in 170 to 180 minutes at the top rate (the saved night: 175 minutes)", 170 * 60 <= t_98 <= 180 * 60, f"{t_98 / 60:.0f} min")
check("replay: the plateau's DC power is 8.3 to 8.6 kW and the inverter AC input is 8.98 kW (the saved nights: 8.36 to 8.58 kW and 8.982 to 8.987 kW)",
      all(8300 <= x[2] <= 8620 for x in plateau[8:-8]) and all(abs(x[3] - 8980.0) < 8.0 for x in plateau[8:-8]),
      f"{min(x[2] for x in plateau[8:-8]):.0f} to {max(x[2] for x in plateau[8:-8]):.0f}")
check("replay: from the last sample above 7 kW to the first below 2 kW takes 2.5 to 4.8 minutes (the saved nights, by power: 2.5 to 4.8 minutes)",
      2.5 * 60 <= t_below2 - plateau[-1][0] <= 4.8 * 60, f"{(t_below2 - plateau[-1][0]) / 60:.1f} min")
check("replay: the trickle after the cliff is 0.55 to 0.65 kW for 30 to 50 minutes (2 of the 4 saved nights, 18 and 19 Nov: the other two sessions ended while it ran; the plant's 40 minutes is the slow end)",
      bool(trickle) and 30 * 60 <= len(trickle) * P.DT_S <= 50 * 60 and all(500 <= v <= 700 for v in trickle[6:-2]),
      "no trickle" if not trickle else f"{len(trickle) * P.DT_S / 60:.0f} min, {min(trickle):.0f} to {max(trickle):.0f} W")
pl = P.Plant(P.PlantParams(), 50.0, regs=P.Regs(fp_rate_w=8000.0))
for _ in range(12):
    m = pl.step(P.DT_S, P.Env(house_w=800.0, pv_w=0.0, grid_up=True, window_active=False, slot_target_pct=100.0))
check("replay: a Free Power request of 8000 W gives 7.67 to 7.87 kW DC (the saved event: 7.67 to 7.87 kW at 52.7 to 53.8 V, 0.96 to 0.98 of the request in watts; the 0.94 in the evidence is the current ratio)",
      7670 <= -m.batt_w <= 7870, f"{-m.batt_w:.0f} W")
for shape in ("linear", "step"):
    pk = replace(P.PlantParams(), cliff_shape=shape)
    r_run, r_res = S.run_spec(replace(S.SPEC_BY_NAME["g10_taper_cliff_98"], sc=replace(S.SPEC_BY_NAME["g10_taper_cliff_98"].sc, plant=pk)), K)
    check(f"the cliff's shape is a parameter and the 100 percent night holds with it ('{shape}')", r_res.ok, "; ".join(r_res.failures)[:200])
# F06: the planner's world and the plant's trickle (a finding for the planner owner, pinned by the numbers the review measured)
w_ = K.pessimistic_world(35.0)
world_80_100 = K.pess_finish(w_, 100.0, 0.0, 80.0, None, 8980.0, 10000.0, False, False)
slow = replace(P.PlantParams(), capacity_kwh=33.17325024182597, charge_eff=0.9345697671822305, knee_soc_pct=94.51070324069286, tail_dc_w=357.22058661599397)
pl = P.Plant(slow, 80.0, regs=P.Regs(slot_power_w=8000.0))
tt = 0
while pl.reading() < 100 and tt < 60000:
    pl.step(P.DT_S, P.Env(house_w=800.0, pv_w=0.0, grid_up=True, window_active=True, slot_target_pct=100.0))
    tt += P.DT_S
check(f"FINDING F06 (pinned, for the planner owner): the planner's tail fraction {K.TAIL_FRACTION} is not pessimistic about the measured trickle; a plant with a knee at 94.5 percent and a 357 W trickle needs "
      f"{tt / 60:.0f} min from 80 to 100 percent at the top rate against the world's {world_80_100:.0f} min (the day this flips, the planner's tail was fixed and this pin is removed)",
      tt / 60 > world_80_100, f"{tt / 60:.0f} against {world_80_100:.0f}")
check("the declared envelope can say no: the plant of that finding is outside it, the default plant with a 90 percent target is inside",
      bool(S.envelope_problems(replace(S.SPEC_BY_NAME["g01_nominal"].sc, plant=slow, target_soc_pct=100.0))) and not S.envelope_problems(S.SPEC_BY_NAME["g01_nominal"].sc))
# F10: the Gentle set once with the slot target NOT stopping the charge (rung R1 unknown): every scenario that charges must still hold
r1_diff = []
for spx in S.SPECS:
    if spx.sc.kind == "export":
        continue
    spec_r1 = replace(spx, sc=replace(spx.sc, plant=replace(spx.sc.plant, slot_target_stops_charge=False)))
    r1_run, r1_res = S.run_spec(spec_r1, K)
    check(f"R1 alternative (the slot target does not stop the charge), scenario {spx.sc.name}: it still holds", r1_res.ok, "; ".join(r1_res.failures)[:200])
    if abs(r1_run.rows[-1].soc - RUNS[spx.sc.name][0].rows[-1].soc) > 1.0:
        r1_diff.append(spx.sc.name)
print(f"  info  with R1 = false the only difference is the end of the night: {len(r1_diff)} of the charge scenarios end above their target (the battery goes on to 100 percent, "
      f"and the post-session import, finding F01, lasts longer)")
check("replay: the house load rides on top of the charge (grid import = charge + house, 9.6 to 10.4 kW on the saved nights)",
      all(9300 <= x[4] <= 10300 for x in plateau[8:-8]), f"{min(x[4] for x in plateau[8:-8]):.0f} to {max(x[4] for x in plateau[8:-8]):.0f}")
for ceil_w, lo, hi in ((2000.0, 200.0, 380.0), (3000.0, 250.0, 400.0)):
    pl = P.Plant(P.PlantParams(), 80.0, regs=P.Regs(allow_export=True, dump_ceiling_w=ceil_w))
    m = None
    for _ in range(12):
        m = pl.step(P.DT_S, P.Env(house_w=1000.0, pv_w=0.0, grid_up=True, window_active=False, slot_target_pct=100.0))
    check(f"replay: at a {ceil_w:.0f} W export ceiling the battery's DC power exceeds the AC output by {lo:.0f} to {hi:.0f} W (the recorded leases: 228 to 275 W at 2000 W, 271 to 357 W at 3000 W) and the grid receives the AC output minus the house",
          lo <= m.batt_w - ceil_w <= hi and abs(-m.grid_w - (ceil_w - 1000.0)) < 5.0, f"DC - AC = {m.batt_w - ceil_w:.0f} W, export {-m.grid_w:.0f} W")
pl = P.Plant(P.PlantParams(), 80.0, regs=P.Regs(allow_export=True, dump_ceiling_w=8000.0))
for _ in range(12):
    m = pl.step(P.DT_S, P.Env(house_w=1000.0, pv_w=0.0, grid_up=True, window_active=False, slot_target_pct=100.0))
check("replay: at an 8000 W ceiling the inverter delivers 7.89 kW AC (the staged commissioning) and the grid receives about 6.9 kW", abs(m.batt_ac_out_w - 7890.0) < 5.0 and abs(-m.grid_w - 6890.0) < 10.0,
      f"{m.batt_ac_out_w:.0f} W AC, export {-m.grid_w:.0f} W")

# ===========================================================================
print("")
print("[7] property sweep (seeded)")
# ===========================================================================
SWEEP_N = 700
t1 = time.time()
sweep_stats = {}
bad = S.sweep(K, SWEEP_N, stats=sweep_stats)
check(f"{3 * SWEEP_N} seeded random plants and inputs (gentle, charge fixed, export): every applicable invariant holds ({time.time() - t1:.0f} s)", not bad,
      "; ".join("%s %s" % (n, f[0][:80]) for n, f in bad[:3]))
check(f"no export run of the sweep ends 'runaway' on a healthy plant ({sweep_stats.get('healthy_runaway', 0)} of {SWEEP_N}; the review found 15 of 700 with the first version of the guard model)",
      sweep_stats.get("healthy_runaway", 0) == 0)
ALARM = sweep_stats["alarm"]["below_knee"]
check(f"false alarms are counted: {ALARM[1]} of the {ALARM[0]} nights that reach a target at or below the pessimistic knee with {S.FALSE_ALARM_MARGIN_S / 60:.0f} min to spare carried a report "
      f"({100.0 * ALARM[1] / ALARM[0]:.1f} percent; the stated bound is {100.0 * S.FALSE_ALARM_MAX_RATE:.0f} percent)", ALARM[0] >= 100 and ALARM[1] <= S.FALSE_ALARM_MAX_RATE * ALARM[0])
AB = sweep_stats["alarm"]["above_knee"]
print(f"  info  above the pessimistic knee (a 95 or 100 percent target) {AB[1]} of {AB[0]} nights that reach with a margin carry a report ({100.0 * AB[1] / AB[0]:.0f} percent): "
      f"the planner's knee at 90 percent and its tail make 'at risk' the normal word there (finding F06, README)")
F01_HITS = sweep_stats.get("findings", {}).get(("IMPORT_CEILING", "F01-restore (tolerated in the sweep)"), 0)
check(f"finding F01 is alive in the sweep: {F01_HITS} of the {3 * SWEEP_N} runs end with a restore into a breach (counted, not failed; pinned at 1 or more, so the day the design is fixed this "
      f"check goes red and the tolerance in scenarios.random_spec must be removed)", F01_HITS >= 1)
t1 = time.time()
bad_m = S.sweep(K, 350, base_seed=20261126, kinds=("gentle", "charge_fixed"), envelope="measured")
check(f"a sweep of {2 * 350} nights with the MEASURED knee and trickle (outside the world's envelope, F06): nothing but the tolerated classes fails ({time.time() - t1:.0f} s)", not bad_m,
      "; ".join("%s %s" % (n, f[0][:80]) for n, f in bad_m[:3]))
t1 = time.time()
bad2 = S.sweep(K, 400, base_seed=777001)
check(f"a second seeded sweep from another base seed (777001, the review's), {3 * 400} runs: every applicable invariant holds ({time.time() - t1:.0f} s)", not bad2,
      "; ".join("%s %s" % (n, f[0][:80]) for n, f in bad2[:3]))

# ===========================================================================
print("")
print("[8] mutants of the kernel (each must be killed)")
# ===========================================================================
KSRC = (HERE / "kernel.py").read_text(encoding="utf-8")
MUTANTS = [
    ("M01 dwell lasts one epsilon too long", "now_s - st.last_write_s < CHARGE_DWELL_S - EPS", "now_s - st.last_write_s < CHARGE_DWELL_S + EPS"),
    ("M02 dwell bypassed", "if st.last_write_s is not None and now_s - st.last_write_s < CHARGE_DWELL_S - EPS:", "if False:"),
    ("M03 deadband widened by EPS", "if abs(delta) < CHARGE_HYST_W - EPS:", "if abs(delta) < CHARGE_HYST_W + EPS:"),
    ("M04 reversal extra dropped", "abs(delta) < CHARGE_HYST_W + CHARGE_REVERSAL_EXTRA_W - EPS", "abs(delta) < CHARGE_HYST_W - EPS"),
    ("M05 change count off by one", "if st.changes >= CHARGE_MAX_CHANGES:", "if st.changes > CHARGE_MAX_CHANGES:"),
    ("M06 night write budget off by one", "if writes_left_for_changes(st) <= 0:", "if writes_left_for_changes(st) < 0:"),
    ("M07 step clamp removed", "step = max(-CHARGE_MAX_STEP_W, min(CHARGE_MAX_STEP_W, goal - v))", "step = goal - v"),
    ("M08 setpoint floor removed", (("goal = max(CHARGE_MIN_W, min(cap_w, want_w))", "goal = min(cap_w, want_w)"), ("new_v = max(CHARGE_MIN_W, min(cap_w, new_v))", "new_v = min(cap_w, new_v)")), None),
    ("M09 subtractive cap dropped", "cap_w = min(ceiling_w, st.original_w if st.original_w is not None else ceiling_w)", "cap_w = ceiling_w"),
    ("M10 forced write leaves no restore", "if CHARGE_NIGHT_WRITES - st.writes <= 1:", "if CHARGE_NIGHT_WRITES - st.writes < 1:"),
    ("M11 export settle < to <=", "now_s - st.last_update_s < EXPORT_SETTLE_S", "now_s - st.last_update_s <= EXPORT_SETTLE_S"),
    ("M12 export deadband strict", "if -EXPORT_DEADBAND_W <= error <= EXPORT_DEADBAND_W:", "if -EXPORT_DEADBAND_W < error < EXPORT_DEADBAND_W:"),
    ("M13 export gain dropped", "min(EXPORT_MAX_STEP_W, error * EXPORT_GAIN))", "min(EXPORT_MAX_STEP_W, error))"),
    ("M14 export step clamp dropped", "step = max(-EXPORT_MAX_STEP_W, min(EXPORT_MAX_STEP_W, error * EXPORT_GAIN))", "step = error * EXPORT_GAIN"),
    ("M15 export rounding removed", "rounded = _round_half_away((v_w + step) / EXPORT_ROUND_W) * EXPORT_ROUND_W", "rounded = v_w + step"),
    ("M16 export 500 W floor removed", "rounded = max(EXPORT_MIN_CEILING_W, min(lease_ceiling_w, rounded))", "rounded = min(lease_ceiling_w, rounded)"),
    ("M17 export lease ceiling removed", "rounded = max(EXPORT_MIN_CEILING_W, min(lease_ceiling_w, rounded))", "rounded = max(EXPORT_MIN_CEILING_W, rounded)"),
    ("M18 export write budget off by one", "if st.writes >= EXPORT_MAX_WRITES:", "if st.writes > EXPORT_MAX_WRITES:"),
    ("M19 stale grid ignored in the loop", "if not is_fresh(grid_w, grid_age_s, GRID_STALE_S) or grid_w <= -30000.0", "if grid_w is None or grid_w <= -30000.0"),
    ("M20 response margin < to <=", "elif improvement < EXPORT_RESPONSE_MARGIN_W:", "elif improvement <= EXPORT_RESPONSE_MARGIN_W:"),
    ("M21 wrong direction <= to <", "if improvement <= -EXPORT_WRONG_DIRECTION_W:", "if improvement < -EXPORT_WRONG_DIRECTION_W:"),
    ("M22 response samples off by one", "if ineffective >= EXPORT_RESPONSE_SAMPLES:", "if ineffective > EXPORT_RESPONSE_SAMPLES:"),
    ("M23 recovery attempts off by one", "if st.recoveries >= EXPORT_RECOVERY_ATTEMPTS:", "if st.recoveries > EXPORT_RECOVERY_ATTEMPTS:"),
    ("M24 freshness bound < to <", "    return age_s <= max_age_s\n", "    return age_s < max_age_s\n"),
    ("M25 unavailable counts as fresh", "    if value is None:\n        return False\n    if isinstance(value, float)", "    if isinstance(value, float)"),
    ("M26 frame freshness checks no input", "        if not is_fresh(fields[name], frame.age_s, max_age_s):\n            return False", "        if False:\n            return False"),
    ("M27 clock skew bound > to >=", "if abs(inverter_skew_s) > CLOCK_SKEW_MAX_S:", "if abs(inverter_skew_s) >= CLOCK_SKEW_MAX_S:"),
    ("M28 clock stall count off by one", "if stall_reads >= STALL_READS_MAX:", "if stall_reads > STALL_READS_MAX:"),
    ("M29 NTP age bound > to >=", "if ntp_age_s > NTP_AGE_MAX_S:", "if ntp_age_s >= NTP_AGE_MAX_S:"),
    ("M30 reaction margin dropped from the Stop SOC", "return min(100.0, floor + SOC_RESOLUTION_PCT + overshoot_pct)", "return min(100.0, floor + SOC_RESOLUTION_PCT)"),
    ("M31 house load may go negative", "return max(0.0, frame.inv_ac_w + frame.grid_w)", "return frame.inv_ac_w + frame.grid_w"),
    ("M32 guard order: owner end before grid loss", 'GUARD_ORDER = ("grid_lost", "owner_end",', 'GUARD_ORDER = ("owner_end", "grid_lost",'),
    ("M33 guard order: stale before time trust", '"time_untrusted", "stale", "floor"', '"stale", "time_untrusted", "floor"'),
    ("M34 charge deadline one epsilon late", "inp.now_s >= lease_end_s(obj) - EPS", "inp.now_s >= lease_end_s(obj) + EPS"),
    ("M35 lease end uses the later time", "return min(obj.deadline_s, obj.window_end_s - END_MARGIN_S)", "return max(obj.deadline_s, obj.window_end_s - END_MARGIN_S)"),
    ("M36 import breach > to >=", "import_w is not None and import_w > lim.import_ceiling_w,", "import_w is not None and import_w >= lim.import_ceiling_w,"),
    ("M37 import breach reduction ignores the margin", "excess_ac = import_w - lim.import_ceiling_w * (1.0 - IMPORT_MARGIN_PCT / 100.0)", "excess_ac = import_w - lim.import_ceiling_w"),
    ("M38 grid loss never stops a running session", 'return make("stop", "grid_lost", end=True) if active else make("blocked", "grid_lost")', 'return make("blocked", "grid_lost")'),
    ("M39 owner end does not end the session", 'return make("stop", "owner_end", end=True) if active else make("blocked", "owner_hold")', 'return make("stop", "owner_end", end=False) if active else make("blocked", "owner_hold")'),
    ("M40 feasibility asks for two minutes of margin too many", "return f is not None and f <= deadline_min + EPS", "return f is not None and f <= deadline_min - 2.0"),
    ("M41 capacity band subtracted instead of added", "pct_kwh=capacity_kwh * (1.0 + band) / (1.0 - scale) / 100.0", "pct_kwh=capacity_kwh * (1.0 - band) / (1.0 - scale) / 100.0"),
    ("M42 pessimistic start offset sign", "offset=-(SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT)", "offset=(SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT)"),
    ("M43 efficiency left out of the charge rate", "per_min = rate_w * w.eff / 1000.0 / 60.0 / w.pct_kwh", "per_min = rate_w / 1000.0 / 60.0 / w.pct_kwh"),
    ("M44 fall integral sign", "ramp = (b1 - a1) - ((1.0 - tr) * (b1 * b1 - a1 * a1)) / (2.0 * drop)", "ramp = (b1 - a1) - ((1.0 + tr) * (b1 * b1 - a1 * a1)) / (2.0 * drop)"),
    ("M45 knee test inverted", "return target > w.knee + EPS and opt_pos >= w.knee - EPS", "return target > w.knee + EPS and opt_pos <= w.knee - EPS"),
    ("M46 decrease hysteresis dropped", "if v - low_sp >= PLANNER_HYSTERESIS_W - EPS and low_sp >= CHARGE_MIN_W:", "if v - low_sp >= 0 and low_sp >= CHARGE_MIN_W:"),
    ("M47 raise step ignores the deadband", "raise_to = min(ceiling_sp, max(need_sp, v + CHARGE_HYST_W))", "raise_to = min(ceiling_sp, need_sp)"),
    ("M48 the plan may ask for more than the pre-session value", "        ceiling_sp = min(ceiling_sp, st.original_w)       # a lease is subtractive: it never asks for more than the pre-session value", "        pass"),
    ("M49 weak response never weak", "if moved < GRC_RESPONSE_MIN * expected:", "if moved < 0:"),
    ("M50 a running charge of any size starts", "or ac < GRC_CHARGING_MIN_W:\n        return None, \"no_charge_running\"", "or ac < 0:\n        return None, \"no_charge_running\""),
    ("M51 implausible gain never refused", "if gain < GRC_GAIN_MIN * st.gain0 or gain > GRC_GAIN_MAX * st.gain0:", "if gain < GRC_GAIN_MIN * st.gain0 or gain > 100 * st.gain0:"),
    ("M52 export runaway margin takes the smaller", "limit = expected_w + max(expected_w / 2.0, RUNAWAY_MARGIN_W)", "limit = expected_w + min(expected_w / 2.0, RUNAWAY_MARGIN_W)"),
    ("M53 runaway trips on one sample", "return replace(st, over_samples=over), over >= RUNAWAY_SAMPLES", "return replace(st, over_samples=over), over >= 1"),
    ("M54 export trip margin dropped", "over = export > max_export_w + margin", "over = export > max_export_w"),
    ("M55 feed-forward start not capped", "start_cap = min(EXPORT_FF_MAX_START_W, obj.lease_ceiling_w)", "start_cap = obj.lease_ceiling_w"),
    ("M56 export floor without the margin", "return stop_soc_with_margin(reserve_pct, obj.stop_soc_pct, obj.lease_ceiling_w, obj.capacity_kwh)", "return max(reserve_pct, obj.stop_soc_pct)"),
    ("M57 solar added instead of subtracted", "return h + target_export_w - frame.pv_w", "return h + target_export_w + frame.pv_w"),
    ("M58 Stop SOC <= to <", '"floor": fresh and f.soc_pct <= stop,', '"floor": fresh and f.soc_pct < stop,'),
    ("M59 progress tracker credits better progress", "scale = min(st.eff_scale, max(EFF_SCALE_MIN, k)) if k < EFF_FLAG_BELOW else st.eff_scale", "scale = max(EFF_SCALE_MIN, k) if k < EFF_FLAG_BELOW else k"),
    ("M60 writes not counted", "return replace(st, v_w=value_w, last_write_s=now_s, writes=st.writes + 1, changes=st.changes + (1 if ordinary else 0),", "return replace(st, v_w=value_w, last_write_s=now_s, writes=st.writes, changes=st.changes + (1 if ordinary else 0),"),
    ("M61 house peak takes the minimum", "best = max(best, sum(win) / len(win))", "best = min(best if best else 1e9, sum(win) / len(win))"),
    ("M62 absolute runaway backstop removed", "    tripped = st.over_samples >= RUNAWAY_SAMPLES or st.abs_over >= RUNAWAY_ABS_SAMPLES\n", "    tripped = st.over_samples >= RUNAWAY_SAMPLES\n"),
    ("M63 grid-lost reason code lost on the export path", 'if g == "grid_lost":\n        return make("stop", "grid_lost", end=True)\n    if g == "owner_end":\n        return make("stop", "owner_end", end=True)\n    if g == "time_untrusted":\n        return make("stop", "time_untrusted", end=True)\n    if g == "stale":\n        return make("stop", "stale_telemetry", end=True, **ages)\n    if g == "floor":',
     'if g == "grid_lost":\n        return make("hold", "tracking", wanted_w=st.v_w, v_w=st.v_w, export_w=0.0, target_w=0.0, band_w=0.0)\n    if g == "owner_end":\n        return make("stop", "owner_end", end=True)\n    if g == "time_untrusted":\n        return make("stop", "time_untrusted", end=True)\n    if g == "stale":\n        return make("stop", "stale_telemetry", end=True, **ages)\n    if g == "floor":'),
    ("M64 target guard ignores the import ceiling", "    if headroom is not None and st.original_w * st.gain > headroom:\n        return False", "    if False:\n        return False"),
    ("M66 the target guard never trips", '"target_guard": active and kind == "gentle" and fresh and target_guard_trips(inp, obj, lim, st),', '"target_guard": False,'),
    ("M67 the hand-back is not reported at risk", 'return make("stop", "target_guard", end=True, unreachable=True)', 'return make("stop", "target_guard", end=True)'),
    ("M68 the watch after a lease never reports", 'return make("unreachable", unreach, unreachable=True, want_w=run.v_w, target=obj.target_soc_pct, ceiling_w=prog["ceiling_ac"],\n                late_min=prog["late_min"])', 'return make("hold", "on_plan", wanted_w=run.v_w, v_w=run.v_w, margin_min=prog["margin_min"])'),
    ("M69 the target guard trips with the reading at the target", "    if inp.frame.soc_pct is not None and inp.frame.soc_pct >= obj.target_soc_pct:\n        return False        # the reading is at the target: nothing is at risk (the pessimistic start sits below the reading, which must not trip a false report)\n", ""),
    ("N08 the target guard never trips once its margin has passed", "    if until <= 0:\n        return inp.frame.soc_pct < obj.target_soc_pct\n", "    if until <= 0:\n        return False\n"),
    ("N09 the target guard margin is 5 minutes instead of 15", "GUARD_MARGIN_S = 900 ", "GUARD_MARGIN_S = 300 "),
    ("M70 the backstop ignores the DC allowance above 3000 W", "    margin = RUNAWAY_ABS_MARGIN_W + max(0.0, ref - RUNAWAY_BACKSTOP_FLOOR_W) * RUNAWAY_DC_ALLOWANCE_PCT / 100.0\n", "    margin = RUNAWAY_ABS_MARGIN_W\n"),
    ("M71 no transition window after a write", "    if st.last_update_s is not None and now_s - st.last_update_s < RUNAWAY_TRANSITION_S and st.ref_w is not None and st.ref_w > requested:\n", "    if False:\n"),
    ("M72 a repeated reading counts again", "    if frame_fresh(f, (\"batt\",)) and (st.last_sample_s is None or sample_s > st.last_sample_s + EPS):\n", "    if frame_fresh(f, (\"batt\",)):\n"),
    ("M73 the grid sample need not postdate the write", "    if st.last_update_s is not None and now_s - grid_age_s <= st.last_update_s + EPS:\n        return None, \"WAITING FOR FRESH GRID\", None, st\n", ""),
    ("M74 a write re-arms the lease-start grace", "        began = st.active_since_s if st.active_since_s is not None else st.last_update_s\n", "        began = st.last_update_s\n"),
    ("M75 the transition reference is the new ceiling only", "ref_w=max(prior, value_w))", "ref_w=value_w)"),
    ("M65 forced reduction taken from the planning peak", "write, _why = ramp_charge(st, inp.now_s, want, lim.power_ceiling_w, forced=True)\n    if write is None:\n        return make(\"stop\", \"write_budget\", end=True)", "write, _why = ramp_charge(st, inp.now_s, want, lim.power_ceiling_w, forced=False)\n    if write is None:\n        return make(\"stop\", \"write_budget\", end=True)"),
    # ---- the independent review's mutants (labels BI.. and N.. are the reviewer's), each of which survived the first version ----
    ('BI03 Gentle dongle guard ignores the import ceiling', '        "ceiling": active and lim.import_ceiling_w is not None and import_w is not None and import_w > lim.import_ceiling_w,\n', '        "ceiling": False,\n'),
    ('BI04 Gentle ignores a lowered power ceiling (caps only at the pre-session value)', (('    cap_w = min(ceiling_w, st.original_w if st.original_w is not None else ceiling_w)\n', '    cap_w = st.original_w if st.original_w is not None else ceiling_w\n'), ('    ceiling_sp = lim.power_ceiling_w\n', '    ceiling_sp = CHARGE_MAX_W\n')), None),
    ('BI06a export loop re-writes the same ceiling when saturated (double write)', '    if rounded == v_w:\n        return None, label, None, st\n', ''),
    ('BI06b Gentle hold decisions carry a write (HA re-sends ADJUST on every hold)', '    return make("hold", why or "no_change_needed", wanted_w=want, v_w=v, want_w=want,', '    return make("hold", why or "no_change_needed", wanted_w=want, write_w=want, v_w=v, want_w=want,'),
    ('BI08 a 46-90 s old frame may drive a change (the stale-hold removed)', '    if f.age_s > STALE_HOLD_S:\n', '    if False:\n'),
    ('BI12a feasibility forgets the finish-early buffer (plans to the window end)', '    dl_min = (obj.deadline_s - inp.now_s) / 60.0\n', '    dl_min = (obj.window_end_s - inp.now_s) / 60.0\n'),
    ("BI12b BI12a plus a spurious 'at risk' report at every start (cry wolf)", (('    dl_min = (obj.deadline_s - inp.now_s) / 60.0\n', '    dl_min = (obj.window_end_s - inp.now_s) / 60.0\n'), ('    if starting:\n        goal = max(CHARGE_MIN_W, min(need_sp, st.original_w))', '    if starting:\n        unreach = unreach or "at_risk"\n        goal = max(CHARGE_MIN_W, min(need_sp, st.original_w))')), None),
    ('BI13 import-breach reduction has the wrong sign (raises)', '    want = _floor_step(st.v_w - excess_ac / gain, CHARGE_STEP_W)\n', '    want = _floor_step(st.v_w + excess_ac / gain, CHARGE_STEP_W)\n'),
    ('N01 export_tick never runs the ordinary measured-power runaway guard', '            st, _t = runaway_check(st, f.batt_w, requested, "export")\n', ''),
    ('N02 reserve_rose reported as floor_reached when the latched Stop SOC trips first', '            if g.detail == "floor_reached" and st.stop_soc_pct is not None and floor > st.stop_soc_pct + EPS:\n', '            if False:\n'),
    ('N03 a reserve rise is not relayed (RAISE_STOP) while the export is infeasible high', 'stop_soc_pct=floor if not active else raise_to, house_w=house_w(f)', 'stop_soc_pct=floor if not active else None, house_w=house_w(f)'),
    ('N04 progress tracker keeps judging up to 95 percent (past the pessimistic knee)', 'f.soc_pct >= KNEE_PESSIMISTIC_PCT - 2.0', 'f.soc_pct >= KNEE_PESSIMISTIC_PCT + 5.0'),
    ('N05 the 20 percent demand margin is dropped from the import headroom', '    return lim.import_ceiling_w * (1.0 - IMPORT_MARGIN_PCT / 100.0) - planning_house_w(st, inp) * (1.0 + DEMAND_MARGIN_PCT / 100.0)\n', '    return lim.import_ceiling_w * (1.0 - IMPORT_MARGIN_PCT / 100.0) - planning_house_w(st, inp)\n'),
    ('N06 the exact ceiling is not a feasibility candidate (top candidate a step below)', '    if cands and cands[-1] < ceiling_ac - EPS:\n        cands.append(ceiling_ac)\n', ''),
    ('N07 reductions allowed past the knee (past_knee hold removed)', '    if prog["past"]:\n        return make("hold", "past_knee", wanted_w=v, v_w=v)\n', ''),
    ('N10 no safety start: a session never starts just to lower an import breach', '        if lim.import_ceiling_w is not None and is_fresh(f.grid_w, f.age_s, TELEMETRY_STALE_S) and f.grid_w > lim.import_ceiling_w:\n', '        if False:\n'),
    ("N12 the knee test ignores the reading's resolution and noise", '    past = charging and knee_may_be_passed(w, obj.target_soc_pct, reading + SOC_RESOLUTION_PCT / 2.0 + SOC_NOISE_PCT)\n', '    past = charging and knee_may_be_passed(w, obj.target_soc_pct, reading)\n'),
    ('N13 a raise ignores the import headroom ceiling (only the power ceiling caps it)', '        raise_to = min(ceiling_sp, max(need_sp, v + CHARGE_HYST_W))\n', '        raise_to = max(need_sp, v + CHARGE_HYST_W)\n'),
    ('N14 measured solar half-credited in the export feed-forward', '    return h + target_export_w - frame.pv_w\n', '    return h + target_export_w - 0.5 * frame.pv_w\n'),
    ("N15 the progress tracker's verdict is never used by the plan", '    w = pessimistic_world(obj.capacity_kwh, eff=EFF_PESSIMISTIC * st.eff_scale)\n    reading = inp.frame.soc_pct\n', '    w = pessimistic_world(obj.capacity_kwh, eff=EFF_PESSIMISTIC)\n    reading = inp.frame.soc_pct\n'),
    ('N16 no smoothing: the planning house load is the latest sample only', '        hist = tuple(x for x in hist if x[0] > inp.now_s - HOUSE_PEAK_WINDOW_S) + ((inp.now_s, h),)\n', '        hist = ((inp.now_s, h),)\n'),
    ('N17 a forced reduction clears the reversal memory', 'last_dir=direction if ordinary else st.last_dir', 'last_dir=direction if ordinary else 0'),
    ('N19 the charge lease runs to 10 min before the slot end instead of the deadline', '        "deadline": inp.now_s >= lease_end_s(obj) - EPS,\n', '        "deadline": inp.now_s >= obj.window_end_s - END_MARGIN_S - EPS,\n'),
    ('N20 Charge Fixed ignores the import headroom when it (re)starts', '    prog = charge_progress(inp, obj, lim, replace(st, v_w=None))\n', '    prog = charge_progress(inp, obj, replace(lim, import_ceiling_w=None), replace(st, v_w=None))\n'),
    ('N21 export reserve floor margin computed for 0 s of reaction', '    return stop_soc_with_margin(reserve_pct, obj.stop_soc_pct, obj.lease_ceiling_w, obj.capacity_kwh)\n', '    return stop_soc_with_margin(reserve_pct, obj.stop_soc_pct, obj.lease_ceiling_w, obj.capacity_kwh, react_s=0.0)\n'),
    ('N22 Gentle increases on a stale (46-90 s) frame AND the dongle accepts 120 s old telemetry', (('    if f.age_s > STALE_HOLD_S:\n', '    if False:\n'), ('TELEMETRY_STALE_S = 90 ', 'TELEMETRY_STALE_S = 120 ')), None),
]


def apply_mutation(src, old, new):
    """(old, new) or a tuple of (old, new) pairs; every target must occur exactly once. Returns (new source, problem or None)."""
    pairs = old if isinstance(old, tuple) else ((old, new),)
    for o, n in pairs:
        if src.count(o) != 1:
            return src, f"{src.count(o)} occurrences of {o[:50]!r}"
        src = src.replace(o, n)
    return src, None


def load_mutant(src, name):
    mod = types.ModuleType(name)
    mod.__file__ = name
    sys.modules[name] = mod
    try:
        exec(compile(src, name, "exec"), mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def scenario_failure(Km, name, Bm=None):
    """The first failure text of ONE scenario run with the (mutated) kernel Km and the (mutated) bench Bm; None when it passes."""
    old = S.B
    if Bm is not None:
        S.B = Bm
    try:
        run, res = S.run_spec(S.SPEC_BY_NAME[name], Km)
    except BaseException as exc:
        return f"crashed {type(exc).__name__}"
    finally:
        S.B = old
    return None if res.ok else res.failures[0][:70]


def first_scenario_failure(Km, Bm=None):
    old = S.B
    if Bm is not None:
        S.B = Bm
    try:
        for spec in S.SPECS:
            try:
                run, res = S.run_spec(spec, Km)
            except BaseException as exc:
                return f"{spec.sc.name}: crashed {type(exc).__name__}"
            if not res.ok:
                return f"{spec.sc.name}: {res.failures[0][:70]}"
    finally:
        S.B = old
    return None


# mutants that must die in a NAMED scenario on its own: a scenario, not a unit table (the review's classes F01, F03, F04, F05)
SCENARIO_KILLERS = {
    "BI03": "g03_heavy_load_import_ceiling",          # the dongle's import guard is off: a breach lasts far beyond its guard reaction
    "BI13": "g03_heavy_load_import_ceiling",          # the forced reduction raises: the lease ends in the breach and the restore leaves it
    "M65": "g30b_breach_inside_the_dwell",            # a forced reduction waits for the dwell
    "M66": "g34_target_guard_hands_back",             # the never-worse target guard never trips
    "M67": "g34b_target_guard_reports_missed_target",  # the hand-back is not reported at risk
    "N09": "g34_target_guard_hands_back",             # the guard margin is 5 minutes instead of 15
    "BI04": "g35_power_ceiling_lowered",              # a lowered Power Ceiling is ignored
    "BI06a": "e02b_house_step_infeasible",            # a saturated export loop writes the same ceiling again
    "BI08": "g20b_stale_frame_while_a_raise_is_due",  # a 46-90 s old frame drives a change
    "N22": "g20_telemetry_short_gap",                 # the same, with a wider stale bound
    "N01": "e15b_runaway_between_thresholds",         # the ordinary measured-power guard is missing
    "N15": "g08_efficiency_drop",                     # the progress tracker is never used
    "N16": "g05_kettle_spikes",                       # the planning house load is the latest sample only
    "N20": "f02_fixed_import_breach",                 # Charge Fixed restarts at the full rate into a breach
}
# mutants the SWEEP must catch on its own (no named scenario): the controller that cries wolf and misses the deadline (F07), the guard that is off (F01)
SWEEP_KILLERS = {"BI12b": ("gentle", 250), "BI12a": ("gentle", 150), "BI03": ("charge_fixed", 150)}
BSRC = (HERE / "bench.py").read_text(encoding="utf-8")
BENCH_MUTANTS = [
    # ---- the independent review's bench mutants (its labels), each of which survived the first version ----
    ('BI14 dongle boot resumes the lease instead of restoring it', '            self.restore(t, self.lease, "restart")\n', '            pass\n'),
    ('BI23 export duration sized with measured PV credited', '(hw if hw is not None else 0.0) + sc.target_export_w))\n', '(hw if hw is not None else 0.0) + sc.target_export_w - (inp.frame.pv_w or 0.0)))\n'),
    ('BI26 dongle ignores RAISE_STOP (Stop SOC never raised)', '            if lease.kind == "export" and cmd[1] is not None and cmd[1] > (lease.st.stop_soc_pct or 0.0):\n', '            if False:\n'),
    ('BI27 Home Assistant never alerts on a dead dongle', 'self.run.alerts.append((t, "dongle unavailable', '(lambda x: None)((t, "dongle unavailable'),
    ('NB1 plan-lost bound doubled (40 min)', '        if lease.kind == "gentle" and t - lease.plan_t > K.PLAN_MAX_AGE_S:\n', '        if lease.kind == "gentle" and t - lease.plan_t > 2 * K.PLAN_MAX_AGE_S:\n'),
    ('NB2 readback mismatch not detected', '        if got != value:\n', '        if False:\n'),
    ('NB4 charge runaway guard removed from the dongle tick', '        if since >= K.RUNAWAY_GRACE_S and st.gain is not None and st.v_w is not None:\n', '        if False:\n'),
    ('NB5 a third weak response needed to end the lease', '        elif verdict == "weak" and st.weak >= K.GRC_MAX_INEFFECTIVE:\n', '        elif verdict == "weak" and st.weak >= K.GRC_MAX_INEFFECTIVE + 1:\n'),
    ('NB7 restore retried 30 times before the FAULT alert', 'RESTORE_ATTEMPTS = 3 ', 'RESTORE_ATTEMPTS = 30 '),
    ('NB8 the dongle accepts a START under untrusted time', '        if not self.time_ok(t):\n            return self.refuse(t, kind, "time_untrusted")\n', ''),
    # ---- more mutants of the dongle and Home Assistant models ----
    ("B01 the night's one lease is not remembered (a second Gentle lease may start after the first ended)", "                self.night_used = True      # GRC: one lease a night. A Charge Fixed (Free Power) session may be started again, after the dwell\n", "                pass\n"),
    ("B02 the dongle accepts a START on telemetry it cannot see", "        if not K.frame_fresh(f, (\"soc\", \"grid\")):\n            return self.refuse(t, kind, \"stale_telemetry\")\n", ""),
    ("B03 the dongle accepts a START while the grid is down", "        if not self.grid_up:\n            return self.refuse(t, kind, \"grid_lost\")\n", ""),
    ("B04 the dongle accepts a second START while a lease is open (no single writer)", "        if self.lease is not None:\n            return self.refuse(t, kind, \"authority_busy (the setpoint is owned by %s)\" % self.lease.owner)\n", ""),
    ("B05 a lowered Power Ceiling is not recognised as a safety reduction by the dongle", "            forced = lease.st.v_w is not None and cmd[1] < lease.st.v_w and lease.st.v_w > self.power_ceiling_w + 1e-9\n", "            forced = False\n"),
    ("B06 Home Assistant's silence is noticed after 20 minutes instead of 15 (the API-client timeout is doubled)", "            if self.api_age >= K.REBOOT_TIMEOUT_S:\n", "            if self.api_age >= 2 * K.REBOOT_TIMEOUT_S:\n"),
    ("B07 a dongle that has been dead for 10 minutes still reads as available to Home Assistant", "UNAVAIL_S = 60 ", "UNAVAIL_S = 600 "),
    ("B08 Home Assistant waits 20 minutes before it alerts about a dead dongle", "ALERT_AFTER_S = 120 ", "ALERT_AFTER_S = 1200 "),
    ("B09 an untrusted inverter clock does not stop a charge", "            if t0 <= t < t1 and (which == \"ntp\" or self.sc.kind in KINDS_CHARGE):\n", "            if t0 <= t < t1 and which == \"ntp\":\n"),
    ("B10 telemetry gaps are not honoured (the dongle always gets a sample)", "        if not self.d_up or self.in_gap(t):\n            return\n", "        if not self.d_up:\n            return\n"),
    ("B11 the restore writes a computed value instead of the owner's snapshot", "            if reg in lease.snap and not self.do_write(t, lease, reg, lease.snap[reg], \"restore\"):\n", "            if reg in lease.snap and not self.do_write(t, lease, reg, 0.0, \"restore\"):\n"),
]
BENCH_KILLERS = {   # bench mutant -> the scenario that must fail on its own with it (a bench unit may kill the rest, see BENCH_UNITS)
    "BI26": "e10c_reserve_rise_then_ha_outage", "NB1": "g26_plan_lost", "NB2": "g19_inverter_ignores_write", "NB4": "g36b_charger_runs_away_mid_lease",
    "NB7": "g19_inverter_ignores_write", "NB8": "g28b_start_arrives_after_the_clock_is_untrusted", "BI23": "e21_pv_is_not_credited_in_the_duration",
    "BI14": "g23_restart_in_lease", "BI27": "g24_dead_dongle_charge", "B01": "g21_telemetry_long_gap", "B02": "g22b_start_arrives_after_telemetry_loss",
    "B03": "g29b_start_arrives_after_grid_loss", "B04": "g31_two_policies", "B05": "g35b_power_ceiling_lowered_inside_the_dwell", "B06": "g25_ha_outage",
    "B07": "g24_dead_dongle_charge", "B08": "g24_dead_dongle_charge", "B09": "g27_rtc_untrusted_mid_lease", "B10": "g21_telemetry_long_gap", "B11": "g01_nominal",
}

check("at least 40 mutants are defined", len(MUTANTS) >= 40, str(len(MUTANTS)))
survivors = []
killed_by_units = 0
labels = set()
for name, old, new in MUTANTS:
    msrc, problem = apply_mutation(KSRC, old, new)
    if problem is not None:
        check(f"mutant {name}: its target text occurs exactly once", False, problem)
        continue
    mutant = load_mutant(msrc, "kernel_mutant")
    why = first_unit_failure(mutant)
    if why is not None:
        killed_by_units += 1
    else:
        why = first_scenario_failure(mutant)
    check(f"mutant {name}: killed ({why})", why is not None)
    if why is None:
        survivors.append(name)
    mid = name.split()[0]
    labels.add(mid)
    if mid in SCENARIO_KILLERS:
        sf = scenario_failure(mutant, SCENARIO_KILLERS[mid])
        check(f"mutant {mid} dies in scenario {SCENARIO_KILLERS[mid]} on its own ({sf})", sf is not None)
    if mid in SWEEP_KILLERS:
        sw_kind, sw_n = SWEEP_KILLERS[mid]
        sw_bad = S.sweep(mutant, sw_n, kinds=(sw_kind,))
        check(f"mutant {mid} dies in the seeded sweep on its own ({len(sw_bad)} of {sw_n} {sw_kind} runs fail: {sw_bad[0][1][0][:70] if sw_bad else None})", bool(sw_bad))
check(f"every mutant is killed ({len(MUTANTS) - len(survivors)} of {len(MUTANTS)}; {killed_by_units} by the units, the rest by the scenarios)", not survivors, str(survivors))
check("the scenario killers name mutants that exist and scenarios that exist", set(SCENARIO_KILLERS) <= labels and all(v in S.SPEC_BY_NAME for v in SCENARIO_KILLERS.values()),
      str(sorted(set(SCENARIO_KILLERS) - labels)))
unmutated = load_mutant(KSRC, "kernel_unmutated")
check("an unmutated copy of the kernel passes the units and every scenario (the mutation harness itself is sound)",
      first_unit_failure(unmutated) is None and first_scenario_failure(unmutated) is None)

# ===========================================================================
print("")
print("[9] mutants of the bench (the dongle and Home Assistant models; each must be killed by the scenarios, there are no unit tables for them)")
# ===========================================================================
BENCH_UNITS = [("the second weak response ends a Gentle lease", u_bench_no_response)]


def first_bench_unit_failure(Bm):
    for uname, fn in BENCH_UNITS:
        try:
            if not fn(Bm):
                return f"bench unit '{uname}'"
        except BaseException as exc:
            return f"bench unit '{uname}' crashed {type(exc).__name__}"
    return None


check("at least 15 mutants of the bench (the dongle and Home Assistant models) are defined", len(BENCH_MUTANTS) >= 15, str(len(BENCH_MUTANTS)))
bsurv = []
by_unit = 0
for name, old, new in BENCH_MUTANTS:
    msrc, problem = apply_mutation(BSRC, old, new)
    if problem is not None:
        check(f"bench mutant {name}: its target text occurs exactly once", False, problem)
        continue
    bmut = load_mutant(msrc, "bench_mutant")
    why = first_scenario_failure(K, bmut)
    if why is None:
        why = first_bench_unit_failure(bmut)
        by_unit += 1 if why is not None else 0
    mid = name.split()[0]
    check(f"bench mutant {name}: killed ({why})", why is not None)
    if why is None:
        bsurv.append(name)
    if mid in BENCH_KILLERS:
        sf = scenario_failure(K, BENCH_KILLERS[mid], bmut)
        check(f"bench mutant {mid} dies in scenario {BENCH_KILLERS[mid]} on its own ({sf})", sf is not None)
check(f"every bench mutant is killed ({len(BENCH_MUTANTS) - len(bsurv)} of {len(BENCH_MUTANTS)}; {by_unit} by a bench unit, the rest by the scenarios)", not bsurv, str(bsurv))
check("the bench units pass on the real bench", first_bench_unit_failure(B) is None)
bunmut = load_mutant(BSRC, "bench_unmutated")
check("an unmutated copy of the bench passes every scenario (the bench mutation harness itself is sound)", first_scenario_failure(K, bunmut) is None)

print("")
print(f"  info  total {time.time() - T0:.0f} s")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All dynamic-energy-control simulator checks passed.")
print("These prove the kernel against this model and the bench's own invariants; they do not prove the inverter (see SIM_README.md).")
