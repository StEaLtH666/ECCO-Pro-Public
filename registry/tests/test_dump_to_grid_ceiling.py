#!/usr/bin/env python3
"""dtgp1: the configurable Dump-to-Grid command ceiling and the command-relative absolute runaway backstop.

`ecco_dump_controller_max_ceiling_w` stays the ONE source of truth for the highest battery discharge ceiling the closed-loop
controller ever writes to 256-261; its generic default, 3000 W, is the only hardware-proven value. dtgp1 lets a site select up to
8000 W at BUILD time (compile-time checks refuse anything else), re-anchors the absolute runaway backstop to the CURRENT command
above the live-validated 3000 W level, ties the W2 capture warning to the configured ceiling and adds one read-back sensor. The
exact firmware edits are registry/tests/_dtgp1_scope.py; the post-export chain entry is `dtgp1` (right after pex0).

Every behavioural check EXECUTES the real firmware source through registry/tests/_dump_sim.py with the configured ceiling set in
memory to 3000 (the default), 6000 or 8000 W (2000 W for the below-floor case). A C++ compiler (ECCO_CXX, g++, c++, or ESPHome's
xtensa g++) evaluates the compile-time checks and the W2 re-judgement against the real header; those checks FAIL rather than
skip without one.

  [1] the source of truth: one substitution, default 3000 W; no hidden 3000 / 6000 / 8000 in the firmware code
  [2] the compile-time validation (a real compiler, a value matrix): decimal, above the floor, a rounding multiple, no more than
      the site TOU ceiling, no more than the architectural maximum
  [3] the scope module and the chain entry
  [4] the controller at 3000 / 6000 / 8000 W: HIGH through 3 kW, saturation at the ceiling, a request above the ceiling, LOW
      from high commands, the START seed, write pacing - and no command ever above the configured ceiling
  [5] the command-relative absolute backstop: low / mid / 6000 / 8000 W commands, the default (and a below-floor ceiling)
      unchanged, small tracking error, persistent overshoot, isolated spikes, the step-down transition, stale telemetry, the END
      text, the two computations identical
  [6] stop / restore / ownership at 6000 and 8000 W, and every transaction script byte-identical to FB-D1
  [7] the write surface: identical to FB-D1 and across the configured ceilings (tools/analyze_write_surface.py)
  [8] W2 follows the configured ceiling (the REVIEW lambda's re-judgement through a compiler and through the FB harness; the
      W2 header and its Python mirror unchanged)
  [9] the read-back sensor
  [10] Home Assistant / UI: the target ranges accept 6000 / 8000 W, no 3000 W clamp, the card's W2 wording, and the dashboard's
       W2 line (the same wording: dtgp1's declared post-export edit of the pub0-frozen dashboard)
  [11] documentation proof levels

What this proves: the firmware SOURCE does what the design says under simulated conditions, and the build refuses a bad
configuration. It proves NOTHING about how any inverter or battery behaves above 3000 W: that is the staged live proof's job.
No I/O beyond reading the repository and temporary compiler / analyzer files; no hardware, no ESPHome toolchain.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(ROOT / "tools"), str(ROOT / "registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _dtgp1_scope as DP  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _fbb2_drive as FD  # noqa: E402
import _scope_chain as chain  # noqa: E402
import analyze_write_surface as aws  # noqa: E402
import fallback_capture as cap  # noqa: E402
import fallback_profile as fp  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


FW_PATH = ROOT / DP.FIRMWARE_REL
FW_TEXT = FW_PATH.read_text(encoding="utf-8")
PRE_TEXT = DP.pre_dtgp1_firmware(FW_TEXT)
FW_DOC = ds.load_firmware_text(FW_TEXT)
PRE_DOC = ds.load_firmware_text(PRE_TEXT)
SUBS = FW_DOC["_substitutions"]
C_KEY = "ecco_dump_controller_max_ceiling_w"
FLOOR_KEY = DP.SUBSTITUTION[0]
MARGIN = int(SUBS["ecco_dump_runaway_absolute_margin_w"])
FLOOR = int(SUBS[FLOOR_KEY])
TOU = int(SUBS["ecco_inverter_tou_power_ceiling_w"])
# Distinct per register, so a restore write (the ORIGINAL values) is never mistaken for a Dump command (six equal values).
ORIGINAL = {244: 2, 256: 8000, 257: 7900, 258: 7000, 259: 8000, 260: 7500, 261: 5000}
OWNED = sorted(ORIGINAL)
VALID_TAG = "ecco_dump_to_grid_snapshot_valid_v1"

_FW_CACHE: dict = {}


def fw_at(ceiling: int) -> dict:
    """The real firmware with the configured ceiling set to `ceiling` (what `esphome -s ...` does), cached per value."""
    if ceiling not in _FW_CACHE:
        doc = ds.load_firmware_text(FW_TEXT)
        doc["_substitutions"][C_KEY] = str(ceiling)
        doc["_watchdog"] = ds.find_interval(doc, "dump_overpower_samples")
        _FW_CACHE[ceiling] = doc
    return _FW_CACHE[ceiling]


def strip_comments(text: str) -> list[tuple[int, str]]:
    """Firmware lines without YAML comment lines and without C++ `//` comments (no firmware string spells `//`)."""
    out = []
    for i, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("#"):
            continue
        out.append((i, line.split("//", 1)[0]))
    return out


# ---------------------------------------------------------------------------
# A small plant around the real firmware: telemetry every 10 s, the Dump watchdog every 15 s
# ---------------------------------------------------------------------------
class Plant:
    """Battery discharge follows the live 256 ceiling (optionally lagging, with a residual and a deterministic +/- jitter);
    inverter AC output = battery + PV; grid = house - battery - PV (positive = import)."""

    def __init__(self, house=500.0, pv=0.0, residual=0.0, jitter=0.0, tau_s=0.0):
        self.house, self.pv, self.residual, self.jitter, self.tau = house, pv, residual, jitter, tau_s
        self.batt = None
        self.k = 0
        self.override = None          # callable(sim, cmd) -> measured battery W, or None
        self.grid_fixed = None        # a fixed grid reading (W), or None for house - battery - PV

    def step(self, sim, dt_s: float) -> tuple[float, float]:
        cmd = float(sim.bank.get(256, 0))
        if self.batt is None or self.tau <= 0:
            self.batt = cmd
        else:
            self.batt = cmd + (self.batt - cmd) * (2.718281828459045 ** (-dt_s / self.tau))
        self.k += 1
        noise = self.jitter * (1 if self.k % 2 else -1)
        meas = self.batt + self.residual + noise
        if self.override is not None:
            forced = self.override(sim, cmd)
            if forced is not None:
                meas = forced
        return meas, (self.house - meas - self.pv) if self.grid_fixed is None else self.grid_fixed


def config_poll(sim) -> None:
    sim.g["cfg_block_b_dispatch_seq"] += 1
    sim.g["manual_cfg_reg244_raw"] = sim.bank.get(244, 0)
    for r in range(256, 262):
        sim.g[f"manual_cfg_reg{r}_raw"] = sim.bank.get(r, 0)
    sim.g["cfg_block_b_seq"] += 1
    sim.g["cfg_block_b_ok_ms"] = sim.millis()
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


def start(ceiling: int, target: float, plant: Plant, soc=85.0, stop_soc=10.0, duration=240.0) -> ds.Sim:
    sim = ds.Sim(fw_at(ceiling))
    sim.bank.update(ORIGINAL)
    sim.bank[178] = int(plant.house)        # feed-forward capture: native house load
    sim.bank[186] = int(plant.pv)           # feed-forward capture: PV1
    sim.ent("dump_export_power").set(float(target))
    sim.ent("dump_stop_soc").set(float(stop_soc))
    sim.ent("dump_duration_minutes").set(float(duration))
    sim.ent("dump_write_enable").state = True
    sim.ent("dump_recovery_arm").state = False
    sim.ent("configuration_online").state = True
    sim.ent("configuration_polling").state = True
    sim.ent("ecco_battery_voltage").set(52.0)
    sim.g["ntp_synced"] = True
    sim.hour, sim.minute = 14, 0
    for i, t in enumerate([0, 530, 800, 1600, 1900, 2330]):
        sim.g[f"manual_cfg_reg{250 + i}_raw"] = t
    for i, f in enumerate([1, 0, 0, 0, 0, 0]):
        sim.g[f"manual_cfg_reg{274 + i}_raw"] = f
    config_poll(sim)
    sim.soc = soc
    sim.plant = plant
    sim.grid_fresh = True
    sim.t_ms = 0
    sim.next_wd = 15000
    sim.ent("ecco_battery_soc").publish_state(soc)
    sim.ent("ecco_grid_ct_power").publish_state(plant.house - plant.pv)
    sim.execute("start_dump_to_grid_override")
    assert sim.g["dump_active_persisted"], sim.status()
    return sim


def active(sim) -> bool:
    rec = sim.nvs.get(VALID_TAG)
    return bool(sim.g["dump_active_persisted"]) and not sim.g["dump_restore_requested"] and rec is not None and rec.state == 1


def owned(sim) -> dict:
    return {r: sim.bank.get(r) for r in OWNED}


def reason(sim) -> str:
    return str(sim.ent("dump_last_end_reason").state)


def step(sim, n=1, soc_fresh=True) -> None:
    """n telemetry samples (10 s apart); the Dump watchdog runs every 15 s of simulated time."""
    for _ in range(n):
        sim.advance(10000)
        sim.epoch += 10
        sim.t_ms += 10000
        meas, grid = sim.plant.step(sim, 10.0)
        if soc_fresh:
            sim.ent("ecco_battery_soc").publish_state(sim.soc)
        sim.ent("ecco_battery_power").publish_state(meas)
        if sim.grid_fresh:
            sim.ent("ecco_grid_ct_power").publish_state(grid)
        sim.ent("ecco_pv_power").publish_state(sim.plant.pv)
        sim.ent("ecco_inverter_power").publish_state(max(0.0, meas + sim.plant.pv))
        config_poll(sim)
        while sim.t_ms >= sim.next_wd:
            sim.run_actions(sim.fw["_watchdog"])
            sim.next_wd += 15000
        if not active(sim):
            return


def command_writes(sim) -> list[int]:
    """Every Dump COMMAND written to 256-261 (six equal values), in order; restore writes (the distinct ORIGINAL) excluded."""
    return [v[0] for a, v in sim.writes() if a == 256 and len(set(v)) == 1]


def write_times(sim) -> list[int]:
    return [i for i, e in enumerate(sim.modbus_log) if e[0] == "write" and e[1] == 256]


def expected_backstop(ceiling: int, command_ref: float) -> float:
    return max(command_ref, min(ceiling, FLOOR)) + MARGIN


# ===========================================================================
print("[1] the source of truth")
# ===========================================================================
check("ecco_dump_controller_max_ceiling_w is declared exactly once, with the generic default \"3000\"",
      len(re.findall(r"(?m)^  ecco_dump_controller_max_ceiling_w: ", FW_TEXT)) == 1 and SUBS[C_KEY] == "3000", SUBS.get(C_KEY))
check("the runaway backstop floor is one new substitution, \"3000\" (the live-validated level of ceiling + margin)",
      SUBS.get(FLOOR_KEY) == "3000" and FLOOR_KEY not in PRE_DOC["_substitutions"]
      and set(SUBS) - set(PRE_DOC["_substitutions"]) == {FLOOR_KEY})
CODE = strip_comments(FW_TEXT)
bad3000 = [(i, s.strip()[:90]) for i, s in CODE if re.search(r"\b3000\b", s)
           and not re.search(r"timeout: 3000ms|^\s*(ecco_dump_controller_max_ceiling_w|ecco_dump_runaway_backstop_floor_w): \"3000\"$", s)]
check("no hidden 3000 in the firmware code: every bare 3000 is a `timeout: 3000ms` or one of the two substitution values",
      not bad3000, str(bad3000[:5]))
check("no 6000 anywhere in the firmware code (6000 W is only the first live-proof checkpoint, in the docs)",
      not [i for i, s in CODE if re.search(r"\b6000\b", s)])
STRING = re.compile(r'"(?:\\.|[^"\\])*"')
TOU_LINE = re.compile(r'^  ecco_inverter_tou_power_ceiling_w: "8000"$')
hits8000 = [s.strip() for i, s in CODE if not TOU_LINE.match(s) and re.search(r"\b8000\b", STRING.sub('""', s))]
check("the firmware code spells the number 8000 once outside the site TOU ceiling's own value: the architectural-maximum check",
      hits8000 == ["static_assert(${ecco_dump_controller_max_ceiling_w} <= 8000,"]
      and any(TOU_LINE.match(s) for _i, s in CODE), str(hits8000))
uses = FW_TEXT.count("${ecco_dump_controller_max_ceiling_w}")
for label, needle in (
    ("the controller clamp", "if (rounded > ${ecco_dump_controller_max_ceiling_w}.0f) rounded = ${ecco_dump_controller_max_ceiling_w}.0f;"),
    ("SATURATED HIGH", "new_ceiling >= (uint16_t) ${ecco_dump_controller_max_ceiling_w} && error > 0.0f"),
    ("target feasibility HIGH", "ecco_feas_required_w > ${ecco_dump_controller_max_ceiling_w}.0f"),
    ("the START cap (feed-forward)", ": (float) ${ecco_dump_controller_max_ceiling_w};"),
    ("the backstop floor (on_value and END text)", "if (backstop_floor > ${ecco_dump_controller_max_ceiling_w}.0f) backstop_floor = ${ecco_dump_controller_max_ceiling_w}.0f;"),
    ("W2 (the REVIEW final lambda's re-judgement)", "if (w2_uniform && ri.words[1] <= ${ecco_dump_controller_max_ceiling_w})"),
    ("the read-back sensor", "return (float) ${ecco_dump_controller_max_ceiling_w};"),
):
    check(f"the configured ceiling reaches {label} through the substitution", needle in FW_TEXT)
check("the old fixed backstop (configured ceiling + margin) is gone from the code",
      "${ecco_dump_controller_max_ceiling_w}.0f + ${ecco_dump_runaway_absolute_margin_w}.0f" not in FW_TEXT
      and "(${ecco_dump_controller_max_ceiling_w} + ${ecco_dump_runaway_absolute_margin_w})" not in FW_TEXT, str(uses))

# ===========================================================================
print("")
print("[2] the compile-time validation (a real compiler)")
# ===========================================================================


def find_compiler() -> str | None:
    env = os.environ.get("ECCO_CXX")
    if env:
        return env
    for name in ("g++", "c++", "clang++"):
        found = shutil.which(name)
        if found:
            return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        hits = sorted(glob.glob(os.path.join(local, "esphome", "Cache", "idf", "tools", "xtensa-esp-elf", "*",
                                             "xtensa-esp-elf", "bin", "xtensa-esp32-elf-g++*")))
        if hits:
            return hits[-1]
    return None


CXX = find_compiler()
check("a C++ compiler is available (these checks FAIL rather than skip; set ECCO_CXX)", CXX is not None)
CHECK_LAMBDA = FW_DOC["esphome"]["on_boot"]["then"][-1]["lambda"]
check("the checks are the LAST on_boot action, a compile-time-only lambda (static_asserts, nothing else)",
      len(FW_DOC["esphome"]["on_boot"]["then"]) == len(PRE_DOC["esphome"]["on_boot"]["then"]) + 1
      and FW_DOC["esphome"]["on_boot"]["then"][:-1] == PRE_DOC["esphome"]["on_boot"]["then"]
      and all(s.startswith("static_assert(") for s in re.split(r";\s*", CHECK_LAMBDA.strip()) if s.strip()))


def compile_checks(**over) -> tuple[int, str]:
    subs = dict(SUBS)
    subs.update({k: str(v) for k, v in over.items()})
    code = ds.substitute(CHECK_LAMBDA, subs)
    with tempfile.TemporaryDirectory(prefix="dtgp1_cxx_") as d:
        tu = Path(d) / "checks.cpp"
        tu.write_text("int main() {\n" + code + "\n  return 0;\n}\n", encoding="utf-8", newline="\n")
        p = subprocess.run([CXX, "-std=gnu++17", "-fsyntax-only", str(tu)], capture_output=True, text=True, timeout=300)
        return p.returncode, (p.stdout + p.stderr)[-1500:]


if CXX is not None:
    for v in (600, 1000, 3000, 6000, 8000):
        rc, out = compile_checks(ecco_dump_controller_max_ceiling_w=v)
        check(f"a configured ceiling of {v} W compiles", rc == 0, out[-300:])
    for v, why in (("0", "above the controller floor"), ("-1000", "above the controller floor"),
                   ("500", "above the controller floor"), ("450", "above the controller floor"),
                   ("3050", "multiple of ecco_dump_controller_round_w"), ("8100", "architectural maximum"),
                   ("9000", "architectural maximum"), ("06000", "plain decimal integer"), ("6e3", None),
                   ("6000.0", None), ("abc", None), ("", None)):
        rc, out = compile_checks(ecco_dump_controller_max_ceiling_w=v)
        check(f"a configured ceiling of {v!r} is REFUSED at build time" + (f" ({why})" if why else " (does not compile)"),
              rc != 0 and (why is None or why in out), out[-300:])
    rc, out = compile_checks(ecco_dump_controller_max_ceiling_w=6000, ecco_inverter_tou_power_ceiling_w=5000)
    check("a configured ceiling above the site TOU ceiling (6000 W on a 5000 W site) is refused",
          rc != 0 and "site TOU power ceiling" in out, out[-300:])
    rc, out = compile_checks(ecco_dump_controller_max_ceiling_w=8500, ecco_inverter_tou_power_ceiling_w=9000)
    check("even on a site whose TOU ceiling is higher, 8500 W is refused by the architectural maximum",
          rc != 0 and "architectural maximum" in out, out[-300:])
    rc, out = compile_checks(ecco_dump_runaway_backstop_floor_w=400)
    check("a backstop floor at or below the controller floor is refused", rc != 0 and "backstop floor" in out, out[-300:])
    rc, out = compile_checks(ecco_dump_runaway_backstop_floor_w="03000")
    check("a backstop floor that is not a plain decimal integer is refused", rc != 0 and "backstop floor" in out, out[-300:])

# ===========================================================================
print("")
print("[3] the scope module and the chain entry")
# ===========================================================================
check("reverting exactly dtgp1's edits reproduces the FB-D1 firmware (unchanged by lic0, pub0 and pex0) byte for byte",
      DP.sha(PRE_TEXT) == DP.BASE_FW_SHA == chain.CHAIN.entry("fbd1").checkpoints[chain.FIRMWARE])
check("applying the edits to that base reproduces the live firmware (round trip)", DP.add_dtgp1_text(PRE_TEXT) == FW_TEXT)
E = chain.CHAIN.entry("dtgp1")
check("the chain carries dtgp1 right after pex0, with the live firmware as its checkpoint and the exact reverter",
      chain.CHAIN.prev_id("dtgp1") == "pex0" and E.checkpoints == {chain.FIRMWARE: chain.sha(FW_TEXT)}
      and E.reverts.get(chain.FIRMWARE) is DP.pre_dtgp1_firmware)
check("dtgp1 is a post-export (PEX) entry: not one of the closed ENTRIES, right after pex0 in POST_EXPORT_ENTRIES, with a 64-hex "
      "fingerprint (test_pex_transition.py proves its value and its link to pex0)",
      "dtgp1" not in [e.id for e in chain.ENTRIES] and [e.id for e in chain.POST_EXPORT_ENTRIES][:2] == ["pex0", "dtgp1"]
      and re.fullmatch(r"[0-9a-f]{64}", E.fingerprint) is not None)
check("dtgp1 declares exactly +1 sensor, +1 substitution (the backstop floor) and one frozen edit (the dashboard's W2 line), and "
      "nothing else",
      dict(E.deltas) == {"sensors": 1, "substitutions": 1} and dict(E.subst_added) == {FLOOR_KEY: "3000"}
      and not E.subst_changed and not E.subst_removed and not E.includes_added and not E.op_paths_changed
      and E.banned_fw_added == 0 and set(E.frozen_reverts) == set(E.frozen_checkpoints) == {DP.DASHBOARD_REL}
      and E.frozen_reverts[DP.DASHBOARD_REL] is DP.pre_dtgp1_dashboard)
check("every file dtgp1 declares as added exists", all((ROOT / f).is_file() for f in E.added_files), str(sorted(E.added_files)))
older = sorted(f"registry/tests/{p.name}" for p in HERE.glob("*.py") if f"registry/tests/{p.name}" not in DP.ADDED_FILES
               and re.search(r"(?i)dtgp1", p.read_text(encoding="utf-8")))
check("the ledger is complete: the only pre-existing files under registry/tests that mention dtgp1 are the chain (its entry) and "
      "test_fallback_durable_model.py (its declared-substitution list anchored at fbb0, one commented DTGP1: edit, no pin changed); "
      "test_fbd1_liveness.py needs none: pex0 already reads its FB-D1 baseline as of fbd1 through the chain",
      older == ["registry/tests/_scope_chain.py", "registry/tests/test_fallback_durable_model.py"], str(older))

# ===========================================================================
print("")
print("[4] the controller at the configured ceiling")
# ===========================================================================
for C in (3000, 6000, 8000):
    sim = start(C, target=8000, plant=Plant(house=500))
    first = command_writes(sim)[0]
    step(sim, 60)
    w = command_writes(sim)
    check(f"{C} W: START seeds min(feed-forward cap 2000, ceiling) = {min(2000, C)} W", first == min(2000, C), str(w))
    check(f"{C} W: the controller climbs to EXACTLY the configured ceiling and never above it (max {max(w)})",
          max(w) == C and all(500 <= x <= C for x in w) and active(sim), str(w))
    check(f"{C} W: every step is at most 1000 W", all(abs(b - a) <= 1000 for a, b in zip(w, w[1:])), str(w))
    check(f"{C} W: a request above what the ceiling can deliver ends SATURATED HIGH / TARGET INFEASIBLE HIGH, not refused",
          sim.g["dump_controller_state"] in ("SATURATED HIGH", "TARGET INFEASIBLE HIGH") and active(sim), sim.status())
    n = len(sim.writes())
    step(sim, 40)
    check(f"{C} W: 40 more samples at the ceiling add NO write (no windup, no runaway increase)",
          len(sim.writes()) == n and active(sim) and sim.g["dump_controller_ineffective_count"] == 0, sim.status())
    check(f"{C} W: the status text names the configured ceiling",
          f"exceeds the {C}W controller ceiling" in sim.status() or "SATURATED HIGH" in sim.status(), sim.status())

for C in (6000, 8000):
    sim = start(C, target=5000, plant=Plant(house=500))
    step(sim, 60)
    check(f"{C} W: TRACKING above 3 kW - a 5000 W export target with 500 W of house load settles near 5500 W",
          abs(sim.bank[256] - 5500) <= 200 and sim.g["dump_controller_state"] == "TRACKING" and active(sim), sim.status())
    stamps = [i for i in range(len(sim.modbus_log))]
    sim.plant.house, sim.plant.pv = 0.0, 3000.0
    n0 = len(command_writes(sim))
    step(sim, 60)
    w = command_writes(sim)[n0 - 1:]
    check(f"{C} W: LOW from a high command - steps DOWN in <= 1000 W decrements towards the new requirement (~2000 W)",
          all(b < a and a - b <= 1000 for a, b in zip(w, w[1:])) and abs(sim.bank[256] - 2000) <= 200 and active(sim), str(w))
    sim.plant.pv = 9000.0
    step(sim, 50)
    check(f"{C} W: LOW to the floor - natural PV surplus drives the command to the 500 W floor, labelled saturated / infeasible",
          sim.bank[256] == 500 and active(sim) and sim.g["dump_controller_state"] in ("SATURATED LOW", "TARGET INFEASIBLE LOW"),
          sim.status())
    sim = start(C, target=8000, plant=Plant(house=500))
    times = []
    for _ in range(60):
        before = sim.g["dump_last_controller_update_ms"]
        step(sim)
        if sim.g["dump_last_controller_update_ms"] != before:
            times.append(sim.g["dump_last_controller_update_ms"])    # the firmware's own stamp of each verified write
    gaps = [b - a for a, b in zip(times, times[1:])]
    check(f"{C} W: consecutive controller writes stay >= 45 s apart all the way up", all(g >= 45000 for g in gaps), str(gaps))

# ===========================================================================
print("")
print("[5] the command-relative absolute backstop")
# ===========================================================================


def force_command(sim, cmd: int) -> None:
    for r in range(256, 262):
        sim.bank[r] = cmd
    sim.g["dump_target_power"] = cmd
    sim.g["dump_runaway_ceiling_ref"] = float(cmd)


def backstop_run(C: int, cmd: int, samples) -> ds.Sim:
    """A lease commanding `cmd` (forced, so this is about the threshold, not about how the controller got there), grid exactly on
    target (no controller correction), past the 30 s lease grace and the transition window; then `samples` of battery power."""
    plant = Plant(house=0.0)
    sim = start(C, target=cmd, plant=plant)
    force_command(sim, cmd)
    plant.grid_fixed = -float(cmd)        # exactly on target: the controller makes no correction while the samples run
    plant.override = lambda s, c, w=float(cmd): w
    step(sim, 4)
    plant.override = None
    for x in samples:
        plant.override = lambda s, c, v=float(x): v
        step(sim)
        if not active(sim):
            break
    return sim


for C, cmd in ((3000, 1000), (3000, 3000), (2000, 1000), (6000, 2000), (6000, 4500), (6000, 6000), (8000, 1000), (8000, 4000),
               (8000, 6000), (8000, 8000)):
    thr = int(expected_backstop(C, cmd))
    under = backstop_run(C, cmd, [thr - 10, thr - 10])
    over = backstop_run(C, cmd, [thr + 10, thr + 10])
    label = f"ceiling {C} W, command {cmd} W: backstop {thr} W"
    check(f"{label} - two samples 10 W under it do not trip", active(under), reason(under))
    check(f"{label} - two consecutive samples 10 W over it END the lease (ABSOLUTE POWER RUNAWAY, exact restore, threshold named)",
          not active(over) and reason(over).startswith("ABSOLUTE POWER RUNAWAY") and f"above the {thr}W V1.1 absolute backstop"
          in reason(over) and owned(over) == ORIGINAL, f"{reason(over)} {owned(over)}")
check("default 3000 W: the backstop is the fixed 3750 W it always was, whatever the command (identical to before dtgp1)",
      expected_backstop(3000, 500) == expected_backstop(3000, 3000) == 3750)
check("a ceiling below the floor (2000 W): the backstop is the fixed ceiling + margin (2750 W), identical to before dtgp1",
      expected_backstop(2000, 600) == expected_backstop(2000, 2000) == 2750)
check("never looser than the old design: for every configured ceiling and command the threshold is <= ceiling + margin, "
      "and equal only while commanding the configured ceiling",
      all(expected_backstop(C, c) <= C + MARGIN for C in range(600, 8001, 100) for c in range(500, C + 1, 100))
      and all(expected_backstop(C, C) == C + MARGIN for C in range(600, 8001, 100)))

for C in (6000, 8000):
    sim = start(C, target=8000, plant=Plant(house=2500, residual=300, jitter=150))
    step(sim, 80)
    check(f"{C} W: normal tracking error (+300 W residual, +/-150 W jitter) at the ceiling never trips",
          active(sim) and max(command_writes(sim)) == C, f"{reason(sim)} {sim.status()}")
    sim = start(C, target=8000, plant=Plant(house=2500, residual=MARGIN + 50))
    step(sim, 80)
    check(f"{C} W: a PERSISTENT overshoot (+{MARGIN + 50} W above every command) trips the backstop",
          not active(sim) and reason(sim).startswith("ABSOLUTE POWER RUNAWAY") and owned(sim) == ORIGINAL, reason(sim))
    sim = backstop_run(C, 4000, [6000, 4100, 6000, 4100, 6000, 4100])
    check(f"{C} W: isolated single-sample spikes (alternating) never trip", active(sim), reason(sim))

plant = Plant(house=500, residual=300)
sim = start(8000, target=7000, plant=plant)
step(sim, 70)
cmd_before = sim.bank[256]
plant.override = lambda s, c: c + 1000.0
step(sim, 6)
check("8000 W: an overshoot of 1000 W above a ~7.2 kW command is caught (the old ceiling + 750 W backstop, 8750 W, could not)",
      cmd_before >= 7000 and not active(sim) and reason(sim).startswith("ABSOLUTE POWER RUNAWAY")
      and cmd_before + 1000 < 8000 + MARGIN, f"{cmd_before} {reason(sim)}")

# Step-down transition: the reference stays the OLD command for ecco_dump_runaway_transition_ms after a verified write.
TRANS_MS = int(SUBS["ecco_dump_runaway_transition_ms"])


def step_down_run(lag_samples: int) -> ds.Sim:
    plant = Plant(house=0.0)
    sim = start(8000, target=6000, plant=plant)
    force_command(sim, 6000)
    plant.grid_fixed = -6000.0
    plant.override = lambda s, c: 6300.0
    step(sim, 4)
    # what a verified controller step-down write leaves behind: 6000 -> 5000, the transition reference = the old command
    force_command(sim, 5000)
    sim.g["dump_runaway_ceiling_ref"] = 6000.0
    sim.g["dump_last_controller_update_ms"] = sim.millis()
    for k in range(8):
        lagging = k < lag_samples
        plant.override = lambda s, c, v=(6300.0 if lagging else 5300.0): v
        step(sim)
        if not active(sim):
            break
    return sim


sim = step_down_run(lag_samples=2)
check("step-down 6000 -> 5000 W: the battery still at the OLD level inside the transition window does not trip", active(sim), reason(sim))
sim = step_down_run(lag_samples=8)
check("step-down 6000 -> 5000 W: a battery that KEEPS discharging at the old level past the window (the inverter ignoring the step) "
      "trips", not active(sim) and reason(sim).startswith("ABSOLUTE POWER RUNAWAY") and owned(sim) == ORIGINAL, reason(sim))

sim = start(8000, target=7000, plant=Plant(house=500))
step(sim, 40)
sim.grid_fresh = False
step(sim, 12)
check("8000 W: stale grid CT telemetry at a high command still fails closed (GRID TELEMETRY LOST, exact restore)",
      not active(sim) and "GRID TELEMETRY LOST" in reason(sim) and owned(sim) == ORIGINAL, reason(sim))
sim = start(8000, target=7000, plant=Plant(house=500))
step(sim, 40)
step(sim, 12, soc_fresh=False)
check("8000 W: stale battery SOC telemetry at a high command still fails closed (TELEMETRY LOST, exact restore)",
      not active(sim) and "TELEMETRY LOST" in reason(sim) and owned(sim) == ORIGINAL, reason(sim))

on_value = next(s for s in FW_DOC["sensor"] if s.get("id") == "ecco_battery_power")["on_value"]["then"][0]["lambda"]
REF_BLOCK = "\n".join(ln.strip() for ln in DP.BACKSTOP_REF.splitlines())


def flat(code: str) -> str:
    return "\n".join(ln.strip() for ln in code.splitlines())


END_LAMBDAS = [x for x in re.findall(r"reason: !lambda \|-\n((?:                        .*\n)+)", FW_TEXT) if "ABSOLUTE POWER RUNAWAY" in x]
check("the backstop reference is computed by the SAME contiguous lines in the on_value hook and in the END text (verbatim)",
      flat(on_value).count(REF_BLOCK) == 1 and len(END_LAMBDAS) == 1 and flat(END_LAMBDAS[0]).count(REF_BLOCK) == 1, REF_BLOCK[:80])
check("the hook still never reads grid power (the backstop judges battery DISCHARGE only)",
      "grid" not in on_value.lower().replace("grid export", ""))
check("the ordinary ceiling-relative guard is unchanged (requested + max(requested / 2, margin), 3 samples)",
      "float margin = requested / 2.0f;" in on_value and "x > requested + margin" in on_value
      and SUBS["ecco_dump_runaway_samples"] == "3")

# ===========================================================================
print("")
print("[6] stop / restore / ownership at 6000 and 8000 W; the transaction scripts are FB-D1's")
# ===========================================================================
for C in (6000, 8000):
    sim = start(C, target=8000, plant=Plant(house=500), soc=60.0, stop_soc=55.0)
    step(sim, 60)
    assert sim.bank[256] == C, sim.status()
    k = len(sim.modbus_log)
    sim.soc = 55.0
    step(sim, 2)
    restore = [(a, v) for kind, a, v, o in sim.modbus_log[k:] if kind == "write"]
    check(f"{C} W: Stop SOC reached AT the ceiling ends the lease and restores 244 FIRST, then 256-261, exactly",
          reason(sim) == "STOP SOC REACHED" and [a for a, _ in restore] == [244, 256] and owned(sim) == ORIGINAL,
          f"{reason(sim)} {restore}")
    sim = start(C, target=8000, plant=Plant(house=500), duration=20.0)
    step(sim, 60)
    sim.epoch += 1300
    step(sim, 2)
    check(f"{C} W: duration expiry at the ceiling restores exactly", reason(sim) == "DURATION EXPIRED" and owned(sim) == ORIGINAL,
          reason(sim))
    sim = start(C, target=8000, plant=Plant(house=500))
    step(sim, 60)
    sim.execute("request_dump_end", {"reason": ds.CStr("manual End button")})
    step(sim, 2)
    check(f"{C} W: a manual End at the ceiling restores exactly", owned(sim) == ORIGINAL and not active(sim), reason(sim))
    sim = start(C, target=5000, plant=Plant(house=500))
    step(sim, 40)
    sim.bank[257] = 4321
    step(sim, 3)
    check(f"{C} W: an external change to 257 above 3 kW ends the lease (ownership) and restores the exact original",
          not active(sim) and owned(sim) == ORIGINAL and ("CONFIG DRIFT" in reason(sim) or "OWNERSHIP" in reason(sim)), reason(sim))
    sim = start(C, target=8000, plant=Plant(house=500))
    step(sim, 60)
    boot = sim.fw["esphome"]["on_boot"]["then"][0]["lambda"]
    s0 = boot.index("// Manual Dump-to-Grid V1 (2026-09-26) - same fail-closed marker/")
    block = boot[s0:boot.index("}", boot.index('id(dump_status).publish_state("Inactive");', s0)) + 1]
    sim2 = ds.Sim(fw_at(C))
    sim2.nvs = {k_: v.copy() for k_, v in sim.nvs.items()}
    sim2.bank = dict(sim.bank)
    sim2.ent("configuration_online").state = True
    sim2.run_lambda(block)
    sim2.run_actions(fw_at(C)["_watchdog"])
    rec = sim.nvs["ecco_dump_to_grid_snapshot_data_v2"]
    check(f"{C} W: a reboot while ACTIVE at the ceiling ends the lease and restores exactly; durable V/P evidence "
          f"({rec.reg_dump_power_intended}/{rec.reg_dump_power_pending}) above 3000 W is accepted, no lockout",
          reason(sim2).startswith("ESP RESTARTED") and owned(sim2) == ORIGINAL and not sim2.g["dump_recovery_metadata_corrupt"],
          reason(sim2))

same = []
diff = []
pre_scripts = {s["id"]: s for s in PRE_DOC["script"]}
for s in FW_DOC["script"]:
    (same if pre_scripts.get(s["id"]) == s else diff).append(s["id"])
check("every script is byte-identical to FB-D1 except the REVIEW dispatch (the W2 re-judgement): START, the controller, restore, "
      "End, Force Restore, Accept, SG-02 containment, Free Power, manual TOU and RTC included",
      diff == ["fallback_profile_capture_dispatch"] and len(pre_scripts) == len(FW_DOC["script"]), str(diff))
iv_diff = [i for i, (a, b) in enumerate(zip(PRE_DOC["interval"], FW_DOC["interval"])) if a != b]
check("every interval is identical to FB-D1 except the Dump watchdog (the END text only)",
      len(PRE_DOC["interval"]) == len(FW_DOC["interval"]) and len(iv_diff) == 1
      and FW_DOC["interval"][iv_diff[0]]["then"] == fw_at(3000)["_watchdog"], str(iv_diff))
pre_s = {s.get("id"): s for s in PRE_DOC["sensor"]}
live_s = {s.get("id"): s for s in FW_DOC["sensor"]}
check("every sensor is identical to FB-D1 except ecco_battery_power's hook, plus the one new read-back sensor",
      {k for k in live_s if k not in pre_s} == {DP.SENSOR_ID}
      and [k for k in pre_s if pre_s[k] != live_s.get(k)] == ["ecco_battery_power"])
check("globals, numbers, switches, buttons, selects, text sensors and api actions are identical to FB-D1",
      all(PRE_DOC.get(k) == FW_DOC.get(k) for k in ("globals", "number", "switch", "button", "select", "text_sensor", "api")))

# ===========================================================================
print("")
print("[7] the write surface")
# ===========================================================================
ALLOWED = set(range(22, 25)) | {230, 232, 244} | set(range(250, 262)) | set(range(268, 280))


def surface(text: str) -> tuple[dict, list]:
    with tempfile.TemporaryDirectory(prefix="dtgp1_ws_") as d:
        p = Path(d) / "fw.yaml"
        p.write_text(text, encoding="utf-8", newline="\n")
        res = aws.analyze(p)
    ops = sorted((wp.name, tuple((op.kind, op.start_address, op.count, op.value_expr) for op in wp.ops)) for wp in res["paths"])
    return aws.write_surface(res["paths"]), ops


BASE_SURFACE, BASE_OPS = surface(PRE_TEXT)
LIVE_SURFACE, LIVE_OPS = surface(FW_TEXT)
check("the write surface (address -> writers) is identical to FB-D1", LIVE_SURFACE == BASE_SURFACE)
check("every Modbus operation of every path is identical to FB-D1 (no new read, no new write, no new address)", LIVE_OPS == BASE_OPS)
for C in (6000, 8000):
    s, o = surface(FW_TEXT.replace("${ecco_dump_controller_max_ceiling_w}", str(C)))
    check(f"rendered at a {C} W ceiling the write surface and every operation are unchanged", s == BASE_SURFACE and o == BASE_OPS)
check("the firmware writes only the declared registers (22-24, 230, 232, 244, 250-261, 268-279); Dump owns 244 and 256-261",
      set(LIVE_SURFACE) <= ALLOWED and {a for a, w in LIVE_SURFACE.items() if any("dump" in x for x in w)} == {244, *range(256, 262)},
      str(sorted(LIVE_SURFACE)))

# ===========================================================================
print("")
print("[8] W2 follows the configured ceiling")
# ===========================================================================


def golden_words(**over):
    base = dict(magic=fp.PROFILE_MAGIC, schema=1, size=96, generation=7, captured_epoch=1790000000, flags=0, reg244=2,
                reg256_261=[8000, 500, 4000, 3000, 2000, 1000], reg268_273=[100, 20, 0, 50, 100, 30],
                reg274_279=[1, 0, 1, 0, 0, 1], reg232=0x0011, reg243=1, reg248=1, reg250_255=[0, 530, 1000, 1600, 2100, 2330],
                reg230=185, reg245=8000, reg247=1)
    base.update(over)
    return cap.words_of(fp.seal_profile(fp.blank_profile(**base)))


def six(p: int):
    return golden_words(reg256_261=[p] * 6)


# The W2 header (firmware/include/ecco_fallback_capture.h) and its Python mirror are UNCHANGED: test_failback_shadow_ha_contract.py
# (frozen by pub0) pins every git-tracked firmware file except the firmware YAML. The header keeps judging W2 against its generic
# 3000 W; the REVIEW final lambda re-judges that one bit against the configured ceiling (_dtgp1_scope.W2_NEW).
CAP_H = (ROOT / "firmware/include/ecco_fallback_capture.h").read_text(encoding="utf-8")
check("the W2 header is unchanged: its generic 3000 W constant, its one-argument capture_warnings / review_evaluate and its W2 line",
      "constexpr uint16_t DUMP_CONTROLLER_MAX_W = 3000;  // W2: the Dump controller's maximum ceiling" in CAP_H
      and "constexpr uint16_t capture_warnings(const CaptureWords &w) {" in CAP_H
      and "  if (all_equal && w[1] <= DUMP_CONTROLLER_MAX_W)" in CAP_H
      and "constexpr ReviewVerdict review_evaluate(const ReviewInputs &in) {" in CAP_H)
check("...and so is its Python mirror, whose generic default equals the firmware's default ceiling (3000 W)",
      cap.DUMP_CONTROLLER_MAX_W == int(SUBS[C_KEY]) == 3000 and cap.capture_warnings(six(3000)) & 2
      and not cap.capture_warnings(six(3100)) & 2 and cap.capture_warnings(golden_words()) == 0)
calls = re.findall(r"review_evaluate\(([^)]*)\)", "\n".join(s for _i, s in strip_comments(FW_TEXT)))
W2_BLOCK = DP.edit("w2").after
check("the firmware calls review_evaluate exactly once, unchanged, and the W2 re-judgement directly follows it",
      calls == ["ri"] and FW_TEXT.count(W2_BLOCK) == 1 and W2_BLOCK.startswith(DP.W2_OLD), str(calls))
check("the re-judgement replaces bit 1 (W2) only, with the header's own predicate and the configured ceiling",
      "v.warnings = (uint16_t) (v.warnings & ~(1u << 1));" in W2_BLOCK
      and "for (int i=1;i<6;i++) w2_uniform = w2_uniform && ri.words[1 + i] == ri.words[1];" in W2_BLOCK
      and "if (w2_uniform && ri.words[1] <= ${ecco_dump_controller_max_ceiling_w}) v.warnings = (uint16_t) (v.warnings | (1u << 1));"
      in W2_BLOCK and len(re.findall(r"v\.warnings =", W2_BLOCK)) == 2)


def w2_model(words, ceiling: int) -> int:
    """The intended warnings: the header's (the mirror's), with W2 = six equal slot powers at or below the configured ceiling."""
    uniform = all(words[1 + i] == words[1] for i in range(6))
    return (cap.capture_warnings(words) & ~2) | (2 if uniform and words[1] <= ceiling else 0)


W2_CEILINGS = (600, 1000, 3000, 6000, 8000)
W2_VECTORS = [("the golden profile", golden_words()), ("all words 0", [0] * 31), ("all words 0xFFFF", [65535] * 31),
              ("uniform 4500 W with 248 bit0 off (W3 too)", golden_words(reg256_261=[4500] * 6, reg248=0)),
              ("five at 6000 W, one at 5900 W", golden_words(reg256_261=[6000] * 5 + [5900])),
              ("five at 3000 W, one at 3100 W", golden_words(reg256_261=[3100] + [3000] * 5))]
W2_VECTORS += [(f"uniform {p} W", six(p)) for p in (0, 500, 599, 600, 601, 1000, 1001, 2999, 3000, 3001, 4500, 5999, 6000, 6001,
                                                     7999, 8000, 8001, 65535)]
check("the model at the default 3000 W is EXACTLY the header's warnings for every vector (the default is unchanged)",
      all(w2_model(w, 3000) == cap.capture_warnings(w) for _l, w in W2_VECTORS))
check("the model flags Dump residue between 3000 and 6000 W at a 6000 W ceiling (silently missed with a fixed 3000 W)",
      all(w2_model(six(p), 6000) & 2 and not cap.capture_warnings(six(p)) & 2 for p in (3100, 4500, 6000)))
if CXX is not None:
    tu = ['#include "ecco_fallback_capture.h"', ""]
    for C in W2_CEILINGS:
        tu += [f"constexpr uint16_t judged_{C}(const ecco_fbcap::CaptureWords &words) {{", "  ecco_fbcap::ReviewInputs ri{};",
               "  ri.words = words;", ds.substitute(W2_BLOCK, {**SUBS, C_KEY: str(C)}).rstrip("\n"), "  return v.warnings;", "}"]
    for label, words in W2_VECTORS:
        lit = "ecco_fbcap::CaptureWords{{" + ", ".join(str(x) for x in words) + "}}"
        tu += [f'static_assert(judged_{C}({lit}) == {w2_model(words, C)}, "W2 at {C} W: {label}");' for C in W2_CEILINGS]
        tu.append(f'static_assert(judged_3000({lit}) == ecco_fbcap::capture_warnings({lit}), "the default is the header: {label}");')
    tu += ["int main() { return 0; }", ""]
    with tempfile.TemporaryDirectory(prefix="dtgp1_w2_") as d:
        (Path(d) / "tu.cpp").write_text("\n".join(tu), encoding="utf-8", newline="\n")
        p = subprocess.run([CXX, "-std=gnu++17", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware" / "include"),
                            str(Path(d) / "tu.cpp")], capture_output=True, text=True, timeout=1800)
    check(f"the SHIPPED re-judgement over the REAL header (a C++ compiler, -Wall -Wextra -Werror): at {', '.join(map(str, W2_CEILINGS))} W "
          f"every one of {len(W2_VECTORS)} vectors gives the model's warnings, and at 3000 W exactly the header's",
          p.returncode == 0, (p.stdout + p.stderr)[-600:])

# End to end through the FB harness (the transpiled firmware: Review pressed, both passes read, the candidate built): the
# warnings the firmware stores and shows in B3, on builds configured for 3000 / 6000 / 8000 W.


def review_warnings(C: int, p: int) -> tuple[int, str]:
    text = FW_TEXT if C == 3000 else FD.mutate(FW_TEXT, f'  {C_KEY}: "3000"\n', f'  {C_KEY}: "{C}"\n')
    d = FD.Driver(text=text, words=cap.words_of(FD.gold_profile(reg256_261=[p] * 6)))
    d.review(expect="CANDIDATE_READY")
    return d.sim.g["fallback_profile_cand_warnings"], d.b3_field("warn")


for C, p, want in ((3000, 3000, True), (3000, 4500, False), (6000, 4500, True), (6000, 6000, True), (6000, 6100, False),
                   (8000, 8000, True)):
    got, shown = review_warnings(C, p)
    header = cap.capture_warnings(cap.words_of(FD.gold_profile(reg256_261=[p] * 6)))
    check(f"FB harness, a {C} W build reviewing six slots at {p} W: W2 {'raised' if want else 'not raised'} (stored and shown in B3), "
          "every other warning bit the header's", bool(got & 2) == want and (got & ~2) == (header & ~2)
          and (("W2" in shown) == want), f"{got} {shown!r}")

# ===========================================================================
print("")
print("[9] the read-back sensor")
# ===========================================================================
sensor = live_s.get(DP.SENSOR_ID) or {}
check("one diagnostic template sensor reports the configured ceiling, in W, and does nothing else",
      sensor.get("platform") == "template" and sensor.get("name") == DP.SENSOR_NAME and sensor.get("unit_of_measurement") == "W"
      and sensor.get("entity_category") == "diagnostic" and sensor.get("lambda") == "return (float) ${ecco_dump_controller_max_ceiling_w};"
      and set(sensor) == {"platform", "name", "id", "unit_of_measurement", "device_class", "accuracy_decimals", "entity_category",
                          "update_interval", "lambda"}, str(sensor))
for C in (3000, 6000, 8000):
    check(f"it reads {C} W on a build configured for {C} W", ds.Sim(fw_at(C)).run_lambda(sensor["lambda"]) == float(C))

# ===========================================================================
print("")
print("[10] Home Assistant / UI")
# ===========================================================================
pkg_text = (ROOT / "home-assistant/packages/ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
pkg = yaml.safe_load(pkg_text)
pw = pkg["input_number"]["ecco_dump_to_grid_schedule_power"]
check("the scheduled export TARGET helper accepts 6000 and 8000 W (500-8000 W, step 100); 3000 W stays valid",
      pw["min"] == 500 and pw["max"] == 8000 and pw["step"] == 100 and all(pw["min"] <= v <= pw["max"] for v in (3000, 6000, 8000)))
check("the scheduled START and arm validations bound the target at 500-8000 W (no 3000 W limit in the Dump package)",
      pkg_text.count("> 8000") == 2 and "outside safe range 500-8000W" in pkg_text and not re.search(r"\b3000\b", pkg_text))
check("the firmware's export TARGET number accepts up to the site TOU ceiling (500 - ${ecco_inverter_tou_power_ceiling_w} W)",
      next(n for n in FW_DOC["number"] if n["id"] == "dump_export_power")["max_value"] == "${ecco_inverter_tou_power_ceiling_w}")
card = (ROOT / "frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts").read_text(encoding="utf-8")
blocks = [card[m.start():m.start() + 400] for m in re.finditer(r'label: "(Scheduled )?Export Power"', card)]
check("both Energy Actions Dump power controls take min/max from the entity, falling back to 500-8000 W",
      len(blocks) == 2 and all("fallbackMin: 500," in b and "fallbackMax: 8000," in b for b in blocks))
fe = [p for p in (ROOT / "frontend/ecco-energy-actions-card").rglob("*") if p.is_file() and p.suffix in (".ts", ".js")
      and "node_modules" not in p.parts and "test" not in p.parts]
check("no 3000 W clamp anywhere in the Energy Actions card source or bundle",
      not [str(p.relative_to(ROOT)) for p in fe if re.search(r"\b3000\b", p.read_text(encoding="utf-8", errors="replace"))])
recovery = (ROOT / "frontend/ecco-fallback-recovery-card/ecco-fallback-recovery-card.js").read_text(encoding="utf-8")
w2 = re.search(r"  W2: '([^']*)'", recovery)
check("the fallback recovery card's W2 wording names no wattage (it follows the configured ceiling)",
      w2 is not None and "Dump to Grid ceiling" in w2.group(1) and not re.search(r"\d+ ?W\b", w2.group(1)), w2.group(1) if w2 else "")
dash = (ROOT / "home-assistant/dashboards/ecco_pro.yaml").read_text(encoding="utf-8")
check("the dashboard's W2 wording is the recovery card's, exactly once, and names no wattage (dtgp1's declared post-export edit)",
      w2 is not None and dash.count(f"'W2': '{w2.group(1)}'") == 1 and "at most 3000 W" not in dash, w2.group(1) if w2 else "")
try:
    dash0 = DP.pre_dtgp1_dashboard(dash)
except AssertionError as exc:
    dash0 = f"<{exc}>"
check("dtgp1 declares that one dashboard line as its only frozen edit: undone, it is the exported 'at most 3000 W' line again and "
      "the round trip holds (test_pex_transition.py proves the dashboard as of pub0 is the export byte for byte)",
      len(DP.DASHBOARD_EDITS) == 1 and getattr(E.frozen_reverts.get(DP.DASHBOARD_REL), "edits", None) == DP.DASHBOARD_EDITS
      and dash0.count("'W2': 'All six slot powers are equal and at most 3000 W - this resembles Dump to Grid residue; confirm.'") == 1
      and DP.add_dtgp1_dashboard(dash0) == dash, dash0[:120] if dash0.startswith("<") else "")

# ===========================================================================
print("")
print("[11] documentation proof levels")
# ===========================================================================
hw = (ROOT / "SUPPORTED_HARDWARE.md").read_text(encoding="utf-8")
dev = (ROOT / "docs/dev/dump-to-grid-ceiling.md").read_text(encoding="utf-8") if (ROOT / "docs/dev/dump-to-grid-ceiling.md").is_file() else ""
for label, text in (("SUPPORTED_HARDWARE.md", hw), ("docs/dev/dump-to-grid-ceiling.md", dev)):
    check(f"{label}: 3000 W is the hardware-tested default, 6000 W offline only (awaiting the staged proof), 8000 W architectural only",
          "3000 W" in text and "6000 W" in text and "8000 W" in text and re.search(r"(?i)offline only", text)
          and re.search(r"(?i)architectural", text) and re.search(r"(?i)not hardware[- ]proven|not hardware[- ]tested", text))
    check(f"{label}: never claims 6000 or 8000 W as hardware tested",
          not re.search(r"(?i)(6000|8000) W[^.|]*\bhardware tested\b(?! for)", text.replace("not hardware tested", "")))

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All dtgp1 configurable-ceiling checks passed.")
print("These prove the firmware SOURCE and the build checks; they prove nothing about an inverter or battery above 3000 W.")
