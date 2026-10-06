#!/usr/bin/env python3
"""Manual TOU Phase 1 - script-level ownership gates, staging safety and
send-failure handling.

Defects closed (main @ 004040b):
  1. apply_manual_slotN did not itself refuse during Free Power / Dump to
     Grid ownership - only the dashboard/Apply BUTTON did, so any other
     caller of the script bypassed it.
  2. Load could run during a Free Power / Dump lease and stage the temporary
     overlay, which then survived the lease and could be applied afterwards.
  3. Staging was never invalidated when temporary ownership started/ended.
  4. No Manual TOU Modbus action handled on_not_sent (or on_custom_response,
     finding S6): a queue refusal let the script keep writing and left the
     verify read as the first indication - or, on the final verify read,
     leaked manual_write_in_progress for good.

No I/O, no hardware, no ESPHome/C++ toolchain. Layers:

  [0] CHANGE SCOPE: reverting exactly this PR's edits (_mtou1_scope.py)
      reproduces main @ 004040b byte-for-byte; nothing else moved; no new
      durable tag / commit / load site; the two new globals are RAM-only.
  [1] APPLY GATE STRUCTURE, from the parsed action tree: in every
      apply_manual_slotN the admission `if:` is the first action, nothing
      outside its then: reaches the bus, its lambda has exactly one top-level
      `return` of a pure && conjunction, and every required ownership term
      is a top-level conjunct.
  [2] MUTATION SELF-TEST: each required term removed / commented out /
      weakened / joined with ||, every && turned into ||, an early
      `return true;`, a side effect in the preamble, and a Modbus action
      hoisted in front of the gate - every mutant is rejected.
  [3] REFERENCE MODEL driven by the extracted conjuncts: every Free Power /
      Dump / reg244 / SG-06 UNKNOWN / bus-busy state refuses; idle admits.
  [4]-[7] BEHAVIOUR: the REAL firmware scripts, buttons and the new interval
      executed through registry/tests/_dump_sim.py, compared against main @
      004040b executed the same way (Load, Apply, on_not_sent /
      on_custom_response at every Modbus step, staging invalidation across
      Free Power and Dump leases, the stale-overlay cache fence).
  [8] WRITE SURFACE: unchanged registers, writers and per-path op lists.

These prove what the firmware SOURCE says and how it executes under the
simulator - never how the compiled firmware behaves on hardware.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools"))
import _dump_sim as ds  # noqa: E402
import _dump_v2_scope as dv2s  # noqa: E402 - Dump V2 (ownership evidence) landed after this PR's base
import _free_power_action_sim as fpsim  # noqa: E402
import _mtou1_scope as mtou1  # noqa: E402
import _scope_chain as chain  # noqa: E402 - FB-T0: the two ABSOLUTE pins ([0] base hash, [8] op-list hashes) are evaluated as of chain entry "dump_v2"
import analyze_write_surface as aws  # noqa: E402
from analyze_write_surface import _strip_cpp_comments_and_literals  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# Selects (charge source / mode) are read through current_option(); the
# shared simulator's Entity keeps a select's option in `.state`.
ds.Entity.current_option = lambda self: self.state

FW_TEXT = FIRMWARE_PATH.read_text(encoding="utf-8")
BASE_TEXT = mtou1.pre_mtou1_text(FW_TEXT)
FW = ds.load_firmware_text(FW_TEXT)
BASE_FW = ds.load_firmware_text(BASE_TEXT)
SCRIPTS = {s["id"]: s for s in FW["script"]}
BUTTONS = {b["id"]: b for b in FW["button"] if "id" in b}
SLOTS = list(mtou1.SLOTS)
FP_FLAGS = ("free_power_active_persisted", "free_power_snapshot_valid", "free_power_operation_in_progress")
DUMP_FLAGS = ("dump_active_persisted", "dump_snapshot_valid", "dump_operation_in_progress")
BUS_BUSY = "<bus busy>"

# ===========================================================================
print("[0] change scope vs main @ 004040b")
# ===========================================================================
# Dump V2 (ownership evidence) edits three Dump scripts, on_boot-adjacent globals
# and the durable header - none of the Manual TOU regions. BASE_TEXT here is
# therefore "main @ 004040b + Dump V2's own edits"; Dump V2's exact edits are
# reverted too (_dump_v2_scope.py) before the byte-for-byte pin, in EITHER order.
# FB-T0: the ABSOLUTE pins below reconstruct main @ 004040b from the firmware AS OF chain entry "dump_v2" (main @ ca7474e):
# every LATER chain entry is undone by its exact-match reverter first (registry/tests/_scope_chain.py), then this PR's and
# Dump V2's own exact reverters run exactly as before. A later PR's declared edits therefore never re-hash the base pin and
# an undeclared edit still breaks it. Today nothing follows "dump_v2": SCOPE_FW_TEXT is byte-for-byte FW_TEXT. The relative
# checks (only-these-scripts-changed, intervals, globals, every-other-section ...) keep comparing LIVE to LIVE-minus-this-PR.
SCOPE_FW_TEXT = chain.CHAIN.as_of(chain.FIRMWARE, "dump_v2", FW_TEXT)
SCOPE_BASE_TEXT = mtou1.pre_mtou1_text(SCOPE_FW_TEXT)
check("reverting exactly this PR's edits (_mtou1_scope.pre_mtou1_text), and Dump V2's own later edits "
      "(_dump_v2_scope.pre_dump_v2_firmware), reproduces main @ 004040b byte-for-byte",
      mtou1.sha(dv2s.pre_dump_v2_firmware(SCOPE_BASE_TEXT)) == mtou1.BASE_FW_SHA,
      mtou1.sha(dv2s.pre_dump_v2_firmware(SCOPE_BASE_TEXT)))
check("...and the two reverts commute (Dump V2 reverted first, then this PR's edits, gives the same bytes)",
      mtou1.pre_mtou1_text(dv2s.pre_dump_v2_firmware(SCOPE_FW_TEXT)) == dv2s.pre_dump_v2_firmware(SCOPE_BASE_TEXT))
_ids = [s["id"] for s in FW["script"]]
check("same script set as main (no script added or removed)", _ids == [s["id"] for s in BASE_FW["script"]])
_changed = sorted(sid for sid in _ids if fpsim.script_body(FW_TEXT, sid) != fpsim.script_body(BASE_TEXT, sid))
check("the ONLY scripts changed are the six apply_manual_slotN scripts - every Free Power, Dump, reg244, RTC, "
      "recovery and poll script is byte-identical", _changed == mtou1.APPLY_SCRIPTS, str(_changed))
_btn_changed = sorted(bid for bid, b in BUTTONS.items()
                      if json.dumps(b, sort_keys=True, default=str) != json.dumps(
                          next(x for x in BASE_FW["button"] if x.get("id") == bid), sort_keys=True, default=str))
check("the ONLY buttons changed are the seven Manual TOU Load buttons (the Apply buttons, reg244, Free Power and "
      "Dump buttons are unchanged)", _btn_changed == sorted(mtou1.LOAD_BUTTONS), str(_btn_changed))
check("intervals: main's intervals unchanged, plus exactly one appended (the staging invalidation tick)",
      FW["interval"][:-1] == BASE_FW["interval"] and len(FW["interval"]) == len(BASE_FW["interval"]) + 1)
_new_globals = [g for g in FW["globals"] if g["id"] not in {x["id"] for x in BASE_FW["globals"]}]
check("globals: main's globals unchanged, plus exactly manual_tou_owner_seen / manual_tou_staging_min_cfg_seq, "
      "both restore_value: no (RAM only - no new durable key)",
      [g for g in FW["globals"] if g["id"] not in mtou1.NEW_GLOBAL_IDS] == BASE_FW["globals"]
      and tuple(g["id"] for g in _new_globals) == mtou1.NEW_GLOBAL_IDS
      and all(g.get("restore_value") in (False, "no") for g in _new_globals))
_other = {k for k in set(FW) | set(BASE_FW) if k not in ("script", "button", "interval", "globals", "_text")}
check("every other top-level section (esphome/on_boot, api, sensors, switches, numbers, selects, modbus, "
      "substitutions...) is identical", all(FW.get(k) == BASE_FW.get(k) for k in _other),
      str(sorted(k for k in _other if FW.get(k) != BASE_FW.get(k))))
_DURABLE = (r"ecco_durable::commit_record\s*\(", r"ecco_durable::load_record\s*\(", r"ecco_durable::load_record_status\s*\(",
            r"make_preference", r"global_preferences", r"restore_value:\s*yes", r"restore_value:\s*true")
check("no new durable commit / load site, preference object or persisted global anywhere in the file",
      all(len(re.findall(p, FW_TEXT)) == len(re.findall(p, BASE_TEXT)) for p in _DURABLE)
      and set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", FW_TEXT))
      == set(re.findall(r"ecco_durable::([A-Za-z0-9_]+_TAG)\b", BASE_TEXT)))
IV = FW["interval"][-1]
_iv_code = _strip_cpp_comments_and_literals(IV["then"][0]["lambda"]) if len(IV["then"]) == 1 and "lambda" in IV["then"][0] else ""
check("the new interval is one RAM-only lambda: no Modbus action, no script dispatch, no durable call, and it "
      "assigns ONLY the six staging flags and the two new RAM globals (it reads, never writes, Free Power / "
      "Dump state - no dependency added from those transactions to Manual TOU)",
      IV.get("interval") == "1s" and _iv_code != ""
      and not re.search(r"modbus|execute|commit_record|load_record|preferences|turn_on|turn_off", _iv_code)
      and set(re.findall(r"id\((\w+)\)\s*=(?!=)", _iv_code)) == set(mtou1.STAGING_FLAGS) | set(mtou1.NEW_GLOBAL_IDS),
      str(set(re.findall(r"id\((\w+)\)\s*=(?!=)", _iv_code))))


# ---------------------------------------------------------------------------
# Structural helpers (same conventions as test_cross_domain_start_gates.py)
# ---------------------------------------------------------------------------
def _reaches_bus(node) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(k, str) and (k.startswith("modbus_client.") or k == "script.execute"):
                found.append(k)
            found += _reaches_bus(v)
    elif isinstance(node, list):
        for item in node:
            found += _reaches_bus(item)
    elif isinstance(node, str) and re.search(r"\.execute\s*\(|->\s*execute\s*\(", node):
        found.append("lambda execute()")
    return found


def _split_top_level(expr: str, op: str) -> list[str]:
    parts, depth, i, start = [], 0, 0, 0
    while i < len(expr):
        ch = expr[i]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and expr.startswith(op, i):
            parts.append(expr[start:i])
            i += len(op)
            start = i
            continue
        i += 1
    parts.append(expr[start:])
    return [p.strip() for p in parts]


def _is_wrapped(expr: str) -> bool:
    if not (expr.startswith("(") and expr.endswith(")")):
        return False
    depth = 0
    for i, ch in enumerate(expr):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and i != len(expr) - 1:
            return False
    return True


def conjuncts(expr: str) -> list[str] | None:
    """Top-level `&&` conjuncts, whitespace-free; None if not a pure conjunction."""
    expr = expr.strip()
    while _is_wrapped(expr):
        expr = expr[1:-1].strip()
    for bad in ("||", "?"):
        if len(_split_top_level(expr, bad)) > 1:
            return None
    out: list[str] = []
    for part in _split_top_level(expr, "&&"):
        if _is_wrapped(part):
            inner = conjuncts(part)
            out += [re.sub(r"\s+", "", part)] if inner is None else inner
        else:
            out.append(re.sub(r"\s+", "", part))
    return out


def _top_level_returns(code: str) -> list[int]:
    depth, out = 0, []
    for m in re.finditer(r"[{}]|\breturn\b", code):
        tok = m.group(0)
        if tok == "{":
            depth += 1
        elif tok == "}":
            depth -= 1
        elif depth == 0:
            out.append(m.start())
    return out


def gate_problems(script: dict, required: list[str]) -> tuple[list[str], list[str]]:
    """(problems, conjuncts) for an apply_manual_slotN admission gate."""
    problems: list[str] = []
    actions = script.get("then")
    if not isinstance(actions, list) or not actions:
        return ["script has no `then:` action list"], []
    if not (isinstance(actions[0], dict) and "if" in actions[0]):
        problems.append("the admission `if:` is not the script's FIRST action")
    gate_idx = next((i for i, a in enumerate(actions) if isinstance(a, dict) and "if" in a), None)
    if gate_idx is None:
        return problems + ["no admission `if:`"], []
    for a in actions[:gate_idx] + actions[gate_idx + 1:]:
        if _reaches_bus(a):
            problems.append(f"bus access/dispatch outside the admission gate: {_reaches_bus(a)}")
    gate = actions[gate_idx]["if"]
    if _reaches_bus(gate.get("else")):
        problems.append("the admission gate's else: branch reaches the bus")
    then = gate.get("then") or []
    if not _reaches_bus(then):
        problems.append("the admission gate's then: branch never reaches the bus")
    first = then[0] if then else None
    first_code = _strip_cpp_comments_and_literals(first["lambda"]) if isinstance(first, dict) and "lambda" in first else ""
    if not re.search(r"\bid\(manual_write_in_progress\)\s*=\s*true\s*;", first_code):
        problems.append("the gate's first then: action does not claim manual_write_in_progress before any Modbus")
    cond = gate.get("condition")
    if not (isinstance(cond, dict) and set(cond) == {"lambda"} and isinstance(cond["lambda"], str)):
        return problems + ["admission condition is not a single lambda"], []
    code = _strip_cpp_comments_and_literals(cond["lambda"])
    rets = _top_level_returns(code)
    if len(rets) != 1:
        return problems + [f"admission lambda has {len(rets)} top-level `return`s (exactly one required)"], []
    preamble, tail = code[:rets[0]], code[rets[0]:]
    m = re.fullmatch(r"return\b(.*);\s*", tail, re.S)
    if not m:
        return problems + ["the admission lambda's top-level return is not its final statement"], []
    if re.search(r"\bid\(\w+\)(?:\.\w+)?\s*=(?!=)|\+\+|--|execute|publish_state|turn_on|turn_off|modbus", preamble):
        problems.append("the admission lambda's preamble has a side effect")
    terms = conjuncts(m.group(1))
    if terms is None:
        return problems + ["admission condition is not a pure && conjunction (top-level || or ?:)"], []
    for term in required:
        if term not in terms:
            problems.append(f"required conjunct {term} missing")
    return problems, terms


def admits(terms: list[str], state: set[str]) -> bool:
    """Reference model: every `!id(flag)` conjunct needs `flag` clear, the bus
    quiescence conjuncts need the bus idle; every other conjunct (arm, staging,
    ranges...) is taken as satisfied - the most permissive environment."""
    for t in terms:
        m = re.fullmatch(r"!id\((\w+)\)", t)
        if m and m.group(1) in state:
            return False
        if t in ("id(inverter_modbus)->tx_buffer_empty()", "!id(inverter_modbus)->tx_blocked()") and BUS_BUSY in state:
            return False
    return True


FP_PHASES = {
    "START in flight (before durable snapshot)": {"free_power_operation_in_progress", "manual_write_in_progress"},
    "snapshot committed, writes in flight": {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"},
    "ACTIVE lease": {"free_power_snapshot_valid", "free_power_active_persisted"},
    "restore owed": {"free_power_snapshot_valid"},
    "Review / Force / Accept in flight": {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"},
    "corrupt-marker lockout": {"free_power_snapshot_valid", "free_power_recovery_metadata_corrupt"},
    **{f"only {f}": {f} for f in FP_FLAGS},
}
DUMP_PHASES = {
    "START in flight (before durable snapshot)": {"dump_operation_in_progress", "manual_write_in_progress"},
    "ACTIVE lease": {"dump_snapshot_valid", "dump_active_persisted"},
    "restore owed": {"dump_snapshot_valid"},
    "SG-02 containment in flight": {"dump_operation_in_progress", "manual_write_in_progress", "dump_snapshot_valid", "dump_recovery_metadata_corrupt"},
    **{f"only {f}": {f} for f in DUMP_FLAGS + ("dump_recovery_metadata_corrupt",)},
}
REG244_PHASES = {
    "proof apply in flight": {"reg244_apply_in_progress", "manual_write_in_progress"},
    "only reg244_apply_in_progress": {"reg244_apply_in_progress"},
    "proof snapshot owed": {"reg244_snapshot_valid"},
    "corrupt-marker lockout": {"reg244_snapshot_valid", "reg244_recovery_metadata_corrupt"},
}
# SG-06: an unreadable durable marker at boot is UNKNOWN - it manifests only
# through the existing lockout flags (see _sg06_scope.py's on_boot edits).
SG06_UNKNOWN = {
    "Free Power marker UNKNOWN": {"free_power_snapshot_valid", "free_power_recovery_metadata_corrupt"},
    "Dump marker UNKNOWN": {"dump_snapshot_valid", "dump_recovery_metadata_corrupt"},
    "reg244 marker UNKNOWN": {"reg244_snapshot_valid", "reg244_recovery_metadata_corrupt"},
}
OTHER_PHASES = {"RTC correction": {"correction_in_progress"}, "another manual write": {"manual_write_in_progress"},
                "Modbus bus busy (tx queue not empty / blocked)": {BUS_BUSY}}
ALL_REFUSE = {**{f"Free Power: {k}": v for k, v in FP_PHASES.items()}, **{f"Dump: {k}": v for k, v in DUMP_PHASES.items()},
              **{f"reg244: {k}": v for k, v in REG244_PHASES.items()}, **{f"SG-06: {k}": v for k, v in SG06_UNKNOWN.items()},
              **OTHER_PHASES}


def model_problems(terms: list[str]) -> list[str]:
    out = [] if admits(terms, set()) else ["refused in the all-idle state"]
    out += [f"ADMITTED while {label}" for label, st in ALL_REFUSE.items() if admits(terms, st)]
    return out


# ===========================================================================
print("")
print("[1] apply_manual_slotN: the script itself carries the ownership gate, first, as a pure conjunction")
# ===========================================================================
GATE_TERMS: dict[str, list[str]] = {}
for sid in mtou1.APPLY_SCRIPTS:
    problems, terms = gate_problems(SCRIPTS[sid], mtou1.APPLY_REQUIRED_TERMS)
    GATE_TERMS[sid] = terms
    structural = [p for p in problems if "required conjunct" not in p]
    check(f"{sid}: the admission if: is the FIRST action, nothing outside its then: reaches the bus, it claims the "
          "write mutex before any Modbus, and its lambda is one side-effect-free `return <pure && conjunction>;`",
          not structural, "; ".join(structural))
    for term in mtou1.APPLY_REQUIRED_TERMS:
        check(f"{sid}: gate requires {term}", term in terms)
    base_problems, base_terms = gate_problems(next(s for s in BASE_FW["script"] if s["id"] == sid), mtou1.APPLY_REQUIRED_TERMS)
    check(f"{sid}: on main @ 004040b the script's own gate lacked Free Power / Dump / reg244-in-flight / bus terms "
          "(the defect this PR closes - pins that this suite is not vacuous)",
          all(t not in base_terms for t in mtou1.APPLY_ADDED_TERMS))

# ===========================================================================
print("")
print("[2] mutation self-test: every weakening of an apply gate is rejected")
# ===========================================================================


def _mutant(script: dict, code: str) -> dict:
    actions = list(script["then"])
    gate = dict(actions[0]["if"])
    gate["condition"] = {"lambda": code}
    actions[0] = {"if": gate}
    return {**script, "then": actions}


def _caught(mutant: dict) -> bool:
    problems, terms = gate_problems(mutant, mtou1.APPLY_REQUIRED_TERMS)
    return bool(problems) or bool(model_problems(terms))


_n_mutants = 0
for sid in mtou1.APPLY_SCRIPTS:
    script = SCRIPTS[sid]
    original = script["then"][0]["if"]["condition"]["lambda"]
    check(f"{sid}: the unmutated gate is accepted (baseline)", not _caught(script))
    bad = []
    for term in mtou1.APPLY_REQUIRED_TERMS:
        anchor = re.compile(re.escape(term) + r"\s*&&")
        if len(anchor.findall(original)) != 1:
            bad.append(f"{term}: anchor found {len(anchor.findall(original))}x")
            continue
        for label, repl in (("removed", ""), ("commented out", f"/* {term} && */"),
                            ("weakened to (t || true)", f"({term} || true) &&"), ("joined with ||", f"{term} ||")):
            _n_mutants += 1
            if not _caught(_mutant(script, anchor.sub(lambda _m, r=repl: r, original))):
                bad.append(f"{term} {label}")
    check(f"{sid}: every required term appears once as `term &&`, and removing / commenting out / weakening / "
          "OR-joining any one of them is rejected", not bad, str(bad[:4]))
    ret = original.index("return")
    all_or = original[:ret] + original[ret:].replace("&&", "||")
    extra = {
        "every && of the return turned into ||": all_or,
        "an early `return true;`": "return true;\n" + original,
        "a side effect in the preamble (claims the mutex inside the condition)": "id(manual_write_in_progress) = true;\n" + original,
    }
    for label, code in extra.items():
        _n_mutants += 1
        check(f"{sid}: mutant with {label} is rejected", _caught(_mutant(script, code)))
    _n_mutants += 2
    check(f"{sid}: mutant with a Modbus write hoisted BEFORE the gate is rejected",
          _caught({**script, "then": [{"modbus_client.write_multiple_registers": {"start_address": 232}}] + list(script["then"])}))
    check(f"{sid}: mutant whose gate is not the first action (a lambda in front) is rejected",
          _caught({**script, "then": [{"lambda": "id(manual_write_attempts)++;"}] + list(script["then"])}))
check(f"mutation self-test ran {_n_mutants} mutants", _n_mutants >= 6 * (4 * len(mtou1.APPLY_REQUIRED_TERMS) + 5))

# ===========================================================================
print("")
print("[3] reference model driven by the real gate conjuncts")
# ===========================================================================
for sid, terms in GATE_TERMS.items():
    probs = model_problems(terms)
    check(f"{sid}: admitted when idle; refused in every Free Power / Dump / reg244 / SG-06 UNKNOWN / RTC / "
          f"bus-busy state ({len(ALL_REFUSE)} states)", not probs, "; ".join(probs[:4]))


# ===========================================================================
# Behavioural harness: the REAL scripts / buttons / interval through the sim
# ===========================================================================
BANK = {232: 0x0010, **{a: 0 for a in range(233, 300)},
        250: 100, 251: 500, 252: 900, 253: 1300, 254: 1700, 255: 2100,
        **{256 + i: 1000 + 100 * i for i in range(6)}, **{268 + i: 20 + i for i in range(6)},
        **{274 + i: (0x0004, 0x0008, 0x0010, 0x0004, 0x0005, 0x0104)[i] for i in range(6)}}
SLOT_REGS = {n: {"start": 249 + n, "end": 250 + n if n < 6 else 250, "power": 255 + n, "soc": 267 + n, "flag": 273 + n}
             for n in SLOTS}
LOAD_ACTIONS = {bid: BUTTONS[bid]["on_press"] for bid in mtou1.LOAD_BUTTONS}
BASE_BUTTONS = {b["id"]: b for b in BASE_FW["button"] if "id" in b}
STAGE_ENT = ("start_hhmm", "end_hhmm", "power", "soc", "charge_source", "mode")


def device(fw: dict) -> "ds.Sim":
    sim = ds.Sim(fw)
    # The verified apply ends by dispatching the ordinary configuration poll
    # (a long read-only script outside this PR); its dispatch is recorded in
    # sim.executed, its body is not needed here.
    sim.scripts["poll_inverter_configuration"] = {"id": "poll_inverter_configuration", "then": []}
    sim.bank = dict(BANK)
    sim.g["manual_config_raw_cache_valid"] = True
    for r in [232, *range(250, 262), *range(268, 280)]:
        sim.g[f"manual_cfg_reg{r}_raw"] = BANK[r]
    sim.ent("configuration_online").set(True)
    return sim


def load(sim, n: int, fw_buttons=None) -> None:
    sim.run_actions((fw_buttons or BUTTONS)[f"load_manual_slot{n}_staging"]["on_press"])


def result(sim) -> str:
    return str(sim.ent("manual_config_last_result").state)


def staged_publishes(sim, n: int) -> int:
    return sum(len(sim.ent(f"manual_slot{n}_{e}").published) for e in STAGE_ENT)


def arm_and_apply(sim, n: int, *, power: int | None = None) -> None:
    if power is not None:
        sim.ent(f"manual_slot{n}_power").set(power)
    sim.ent("manual_config_write_enable").set(True)
    sim.execute(f"apply_manual_slot{n}")


def set_flags(sim, flags) -> None:
    for f in flags:
        if f == BUS_BUSY:
            sim.bus_idle = False
        else:
            sim.g[f] = True


def tick(sim) -> None:
    sim.run_actions(FW["interval"][-1]["then"])


def poll(sim, overrides: dict | None = None) -> None:
    """One ordinary configuration poll as seen by the TOU cache: Block B is
    dispatched (dispatch seq++), then its response refreshes the cache."""
    sim.g["cfg_block_b_dispatch_seq"] += 1
    for r, v in (overrides or {}).items():
        sim.g[f"manual_cfg_reg{r}_raw"] = v
    sim.g["cfg_block_b_response_dispatch_seq"] = sim.g["cfg_block_b_dispatch_seq"]


OWNERSHIP_STATES = {**{f"Free Power: {k}": v for k, v in FP_PHASES.items()},
                    **{f"Dump: {k}": v for k, v in DUMP_PHASES.items()},
                    **{f"SG-06: {k}": v for k, v in SG06_UNKNOWN.items()}}
REG244_STATES = {f"reg244: {k}": v for k, v in REG244_PHASES.items()}

# ===========================================================================
print("")
print("[4] Load: refused - and stages nothing - under Free Power / Dump / reg244 / SG-06 ownership; clean Load works")
# ===========================================================================
for n in SLOTS:
    sim = device(FW)
    load(sim, n)
    regs = SLOT_REGS[n]
    check(f"slot {n}: clean-state Load stages the cached live values exactly as main did",
          sim.g[f"manual_slot{n}_staging_loaded"]
          and sim.ent(f"manual_slot{n}_start_hhmm").state == BANK[regs["start"]]
          and sim.ent(f"manual_slot{n}_power").state == BANK[regs["power"]]
          and sim.ent(f"manual_slot{n}_soc").state == BANK[regs["soc"]]
          and result(sim).startswith("Manual staging loaded from current inverter Slot"))
    base = device(BASE_FW)
    load(base, n, BASE_BUTTONS)
    check(f"slot {n}: ...and publishes the same staging entities and result text as main @ 004040b",
          all(sim.ent(f"manual_slot{n}_{e}").published == base.ent(f"manual_slot{n}_{e}").published for e in STAGE_ENT)
          and result(sim) == result(base))
    for group, states in (("Free Power / Dump / SG-06", OWNERSHIP_STATES), ("register 244", REG244_STATES)):
        bad, base_admitted = [], 0
        for label, st in states.items():
            sim = device(FW)
            sim.g[f"manual_slot{n}_staging_loaded"] = True  # a stale earlier staging must not survive a refusal
            set_flags(sim, st)
            load(sim, n)
            if sim.g[f"manual_slot{n}_staging_loaded"] or staged_publishes(sim, n) or not result(sim).startswith("REJECTED"):
                bad.append(label)
            b = device(BASE_FW)
            set_flags(b, st)
            load(b, n, BASE_BUTTONS)
            base_admitted += bool(b.g[f"manual_slot{n}_staging_loaded"])
        check(f"slot {n}: Load refused in every {group} ownership state ({len(states)}) - no staging entity "
              "published, staging flag cleared, REJECTED reason shown", not bad, str(bad[:4]))
        exposed = sum(1 for st in states.values() if "manual_write_in_progress" not in st)
        check(f"slot {n}: ...where main @ 004040b staged the (possibly overlaid) values in {base_admitted} of them - "
              "every one not already excluded by its manual_write_in_progress check (the defect)",
              base_admitted == exposed and exposed > 0, f"{base_admitted} vs {exposed}")

_la = BUTTONS["load_all_manual_tou_staging"]["on_press"][0]["if"]
_la_terms = conjuncts(re.fullmatch(r"\s*return\b(.*);\s*", _strip_cpp_comments_and_literals(_la["condition"]["lambda"]), re.S).group(1))
check("Load All: its own gate is the same pure conjunction as each per-slot Load (and each pressed child re-checks)",
      _la_terms is not None and all(t in _la_terms for t in mtou1.LOAD_REQUIRED_TERMS)
      and [a for a in _la["then"] if "button.press" in a] == [{"button.press": f"load_manual_slot{n}_staging"} for n in SLOTS])
for bid in mtou1.LOAD_BUTTONS:
    cond = BUTTONS[bid]["on_press"][0]["if"]["condition"]["lambda"]
    terms = conjuncts(re.fullmatch(r"\s*return\b(.*);\s*", _strip_cpp_comments_and_literals(cond), re.S).group(1))
    missing = [t for t in mtou1.LOAD_REQUIRED_TERMS if t not in (terms or [])]
    check(f"{bid}: the Load gate is a pure conjunction with every ownership / fence term", terms is not None and not missing,
          str(missing))
    bad = []
    for term in mtou1.LOAD_REQUIRED_TERMS[2:]:
        m = re.search(r"(?<![\w!])" + re.escape(term).replace(r">=", r"\s*>=\s*"), cond)
        mut = cond[:m.start()] + "true" + cond[m.end():] if m else cond
        mt = conjuncts(re.fullmatch(r"\s*return\b(.*);\s*", _strip_cpp_comments_and_literals(mut), re.S).group(1))
        if not m or all(t in (mt or []) for t in mtou1.LOAD_REQUIRED_TERMS):
            bad.append(term)
    check(f"{bid}: replacing any one ownership / fence term by `true` is caught", not bad, str(bad[:3]))

# ===========================================================================
print("")
print("[5] Apply: the SCRIPT refuses under ownership (no Modbus at all); clean Apply is unchanged vs main")
# ===========================================================================
for n in SLOTS:
    sim, base = device(FW), device(BASE_FW)
    for s, btns in ((sim, BUTTONS), (base, BASE_BUTTONS)):
        load(s, n, btns)
        arm_and_apply(s, n, power=2500)
    check(f"slot {n}: clean-state Apply performs exactly main's Modbus sequence (same writes, same values, same "
          "verify reads, same order) and ends VERIFIED OK, lock released, disarmed",
          sim.modbus_log == base.modbus_log and len([e for e in sim.modbus_log if e[0] == "write"]) == (6 if n == 6 else 5)
          and result(sim) == result(base) and result(sim).startswith("VERIFIED OK")
          and not sim.g["manual_write_in_progress"] and sim.ent("manual_config_write_enable").state is False,
          f"{sim.modbus_log} vs {base.modbus_log}")
    bad, base_wrote = [], 0
    for label, st in {**OWNERSHIP_STATES, **REG244_STATES, **OTHER_PHASES}.items():
        s = device(FW)
        load(s, n)
        set_flags(s, st)
        was_lock = s.g["manual_write_in_progress"]
        arm_and_apply(s, n, power=2500)
        if s.modbus_log or not result(s).startswith("REJECTED") or s.ent("manual_config_write_enable").state is not False \
                or s.g["manual_write_in_progress"] != was_lock or s.g["manual_write_attempts"] != 0:
            bad.append(label)
        if label.startswith(("Free Power", "Dump", "SG-06")) or label == "reg244: only reg244_apply_in_progress" \
                or label.startswith("Modbus"):
            b = device(BASE_FW)
            load(b, n, BASE_BUTTONS)
            set_flags(b, st)
            arm_and_apply(b, n, power=2500)
            base_wrote += any(e[0] == "write" for e in b.modbus_log)
    check(f"slot {n}: apply_manual_slot{n} called DIRECTLY (no button) refuses before any Modbus in every ownership "
          "/ reg244 / SG-06 / RTC / bus-busy state - REJECTED, disarmed, mutex untouched", not bad, str(bad[:4]))
    check(f"slot {n}: ...where the same direct call on main @ 004040b wrote the inverter in {base_wrote} of those "
          "states (the script-level layering gap)", base_wrote > 0)
    s = device(FW)
    load(s, n)
    set_flags(s, {"free_power_snapshot_valid"})
    arm_and_apply(s, n)
    check(f"slot {n}: the ownership refusal names the owner",
          result(s) == "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings")

# ===========================================================================
print("")
print("[6] on_not_sent / on_custom_response at EVERY Modbus step fail the apply - no silent success, no lock leak")
# ===========================================================================


def fault_at(k: int, outcome: str):
    count = {"i": 0}

    def fn(kind, addr, cnt):
        count["i"] += 1
        return outcome if count["i"] == k else "ok"
    return fn


for sid in mtou1.APPLY_SCRIPTS:
    acts = [kind for kind, _g, _b in fpsim.flatten(SCRIPTS[sid]["then"]) if kind in (fpsim.WRITE, fpsim.READ)]
    handlers_ok = all("on_not_sent" in b and "on_custom_response" in b
                      for kind, _g, b in fpsim.flatten(SCRIPTS[sid]["then"]) if kind in (fpsim.WRITE, fpsim.READ))
    check(f"{sid}: every one of its {len(acts)} Modbus actions declares on_not_sent AND on_custom_response",
          handlers_ok and len(acts) >= 7)

for n in SLOTS:
    n_writes = 6 if n == 6 else 5
    for outcome in ("not_sent", "custom_response"):
        bad, base_bad = [], []
        for k in range(1, n_writes + 3):  # every write, then the reg232 verify read, then the final verify read
            s = device(FW)
            load(s, n)
            s.outcome_fn = fault_at(k, outcome)
            arm_and_apply(s, n, power=2500)
            ops = s.modbus_log
            failed_i = next(i for i, e in enumerate(ops) if e[3] == outcome)
            is_write = ops[failed_i][0] == "write"
            ok = (s.g["manual_write_successes"] == 0 and s.g["manual_write_failures"] == 1
                  and not s.g["manual_write_in_progress"] and s.ent("manual_config_write_enable").state is False
                  and result(s).startswith(("FAILED", "VERIFY FAILED")) and "VERIFIED OK" not in result(s))
            if is_write:
                # fail fast: nothing after the refused write - no further write and no verification read
                ok = ok and len(ops) == failed_i + 1 and result(s).startswith("FAILED")
            if not ok:
                bad.append((k, ops[failed_i][:2], result(s), s.g["manual_write_in_progress"]))
            if outcome == "not_sent":
                b = device(BASE_FW)
                load(b, n, BASE_BUTTONS)
                b.outcome_fn = fault_at(k, outcome)
                arm_and_apply(b, n, power=2500)
                bops = b.modbus_log
                leaked = b.g["manual_write_in_progress"]
                verify_first = is_write and any(e[0] == "read" for e in bops)
                if leaked or verify_first:
                    base_bad.append(k)
        check(f"slot {n}: {outcome} at each of the {n_writes + 2} Modbus steps -> apply FAILED (failure counted, no "
              "success), write mutex released, disarmed; after a refused WRITE nothing further is sent and no "
              "verification read runs", not bad, str(bad[:3]))
        if outcome == "not_sent":
            check(f"slot {n}: ...where main @ 004040b either kept writing and let the verify read be the first "
                  "indication, or (final verify read refused) leaked manual_write_in_progress for good - in "
                  f"{len(base_bad)} of {n_writes + 2} steps",
                  len(base_bad) == n_writes + 1, str(base_bad))

# ===========================================================================
print("")
print("[7] staging invalidation across Free Power / Dump leases, and the post-lease cache fence")
# ===========================================================================


def load_all(sim) -> None:
    for n in SLOTS:
        load(sim, n)


def all_staged(sim) -> bool:
    return all(sim.g[f] for f in mtou1.STAGING_FLAGS)


def none_staged(sim) -> bool:
    return not any(sim.g[f] for f in mtou1.STAGING_FLAGS)


s = device(FW)
load_all(s)
seq0 = s.g["manual_tou_staging_min_cfg_seq"]
pubs = len(s.ent("manual_config_last_result").published)
for _ in range(5):
    tick(s)
check("idle ticks change nothing: staging kept, no fence, no message", all_staged(s)
      and s.g["manual_tou_staging_min_cfg_seq"] == seq0 and len(s.ent("manual_config_last_result").published) == pubs)

LEASES = {
    "Free Power lease": [{"free_power_operation_in_progress", "manual_write_in_progress"},
                         {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"},
                         {"free_power_snapshot_valid", "free_power_active_persisted"},
                         {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"}],
    "Dump to Grid lease": [{"dump_operation_in_progress", "manual_write_in_progress"},
                           {"dump_snapshot_valid", "dump_active_persisted"},
                           {"dump_operation_in_progress", "manual_write_in_progress", "dump_snapshot_valid"}],
    **{f"only {f}": [{f}] for f in mtou1.FP_DUMP_OWNERSHIP_FLAGS},
}
OVERLAY = {256: 3000, 257: 3000, 258: 3000, 259: 3000, 260: 3000, 261: 3000, 232: 0x0011}
for label, phases in LEASES.items():
    s = device(FW)
    load_all(s)
    set_flags(s, phases[0])
    tick(s)
    started = none_staged(s) and s.g["manual_tou_owner_seen"]
    for ph in phases:  # the lease runs; its overlay lands in the ordinary poll cache
        for f in set().union(*phases):
            s.g[f] = f in ph
        tick(s)
        poll(s, OVERLAY)
    loads_during = []
    for n in SLOTS:
        load(s, n)
        loads_during.append(s.g[f"manual_slot{n}_staging_loaded"])
    for f in set().union(*phases):  # restore verified, ownership released
        s.g[f] = False
    load(s, 1)
    gap_refused = not s.g["manual_slot1_staging_loaded"]  # released but not yet seen by the tick
    tick(s)
    ended = none_staged(s) and not s.g["manual_tou_owner_seen"] and result(s).startswith("Manual TOU staging invalidated")
    applied = []
    for n in SLOTS:
        arm_and_apply(s, n)
        applied.append(bool(s.modbus_log))
    load(s, 2)
    fenced_0 = not s.g["manual_slot2_staging_loaded"] and s.ent("manual_slot2_power").state != 3000
    poll(s, OVERLAY)  # a poll already in flight when the lease ended: Block A may predate the restore
    load(s, 2)
    fenced_1 = not s.g["manual_slot2_staging_loaded"]
    poll(s, {r: BANK[r] for r in OVERLAY})  # the first poll that STARTED after the release: restored values
    load(s, 2)
    reopened = s.g["manual_slot2_staging_loaded"] and s.ent("manual_slot2_power").state == BANK[257]
    check(f"{label}: start clears all six stagings; Load refused throughout; the release is seen within one tick; "
          "no pre-lease staging can be applied afterwards; Load stays fenced until a poll that started after the "
          "release has refreshed the cache (never stages the overlay), then works again",
          started and not any(loads_during) and gap_refused and ended and not any(applied)
          and fenced_0 and fenced_1 and reopened,
          f"started={started} during={loads_during} gap={gap_refused} ended={ended} applied={applied} "
          f"fence={fenced_0},{fenced_1} reopened={reopened}")

# On main the same sequence left the pre-lease staging armed and let Load stage the overlay.
b = device(BASE_FW)
for n in SLOTS:
    load(b, n, BASE_BUTTONS)
b.g["free_power_snapshot_valid"] = b.g["free_power_active_persisted"] = True
for r, v in OVERLAY.items():
    b.g[f"manual_cfg_reg{r}_raw"] = v
load(b, 2, BASE_BUTTONS)
check("main @ 004040b (the defect): pre-lease staging survived the lease, and a Load during it staged the overlay",
      all(b.g[f] for f in mtou1.STAGING_FLAGS) and b.ent("manual_slot2_power").state == 3000)

# Mutation: the invalidation tick must watch every ownership flag.
_iv_lambda = FW["interval"][-1]["then"][0]["lambda"]
bad = []
for f in mtou1.FP_DUMP_OWNERSHIP_FLAGS:
    mut = re.sub(r"id\(" + f + r"\)\s*\|\|\s*", "", _iv_lambda, count=1)
    if mut == _iv_lambda:
        mut = re.sub(r"\s*\|\|\s*id\(" + f + r"\)", "", _iv_lambda, count=1)
    ms = device(FW)
    load_all(ms)
    ms.g[f] = True
    ms.run_actions([{"lambda": mut}])
    if none_staged(ms):
        bad.append(f)
check("mutation: dropping any one ownership flag from the tick's `owned` test leaves a staging armed through that "
      "flag's lease (every flag is load-bearing)", not bad, str(bad))

# ===========================================================================
print("")
print("[8] write surface unchanged: registers, writers, per-path Modbus op lists")
# ===========================================================================
WS = aws.analyze(FIRMWARE_PATH)
paths = {p.name: p for p in WS["paths"]}
EXPECTED_WRITES = {n: [(232, 1), (SLOT_REGS[n]["start"], 2 if n < 6 else 1)] + ([(250, 1)] if n == 6 else [])
                   + [(SLOT_REGS[n]["power"], 1), (SLOT_REGS[n]["soc"], 1), (SLOT_REGS[n]["flag"], 1)] for n in SLOTS}
for n in SLOTS:
    p = paths[f"apply_manual_slot{n}"]
    check(f"apply_manual_slot{n}: writes exactly {EXPECTED_WRITES[n]} and reads exactly [(232, 1), (250, 25|30)] - "
          "no new register", [(o.start_address, o.count) for o in p.ops if o.kind == "write"] == EXPECTED_WRITES[n]
          and [(o.start_address, o.count) for o in p.ops if o.kind == "read"] == [(232, 1), (250, 25 if n == 1 else 30)])
surface = aws.write_surface(WS["paths"])
check("Manual TOU's written register set is exactly 232, 250-261, 268-279",
      {r for r, w in surface.items() if any(x.startswith("apply_manual_slot") for x in w)}
      == {232, *range(250, 262), *range(268, 280)})
# FB-T0: the two hash pins run the analyzer on the firmware AS OF chain entry "dump_v2" (see [0]); the property checks
# around them keep using the LIVE analysis.
SCOPE_WS = chain.CHAIN.analyze_as_of("dump_v2", FW_TEXT)
check("register -> writers map identical to main (the pinned SG-01 hash)",
      mtou1.sha(json.dumps({str(k): v for k, v in aws.write_surface(SCOPE_WS["paths"]).items()}, sort_keys=True))
      == "70036acf5e1855e8bd07dbadec090c8a55be4aac7f94373bd342fd49c52699d3")
check("every path's ordered Modbus op list identical to main (the pinned SG-01 hash)",
      mtou1.sha(json.dumps({p.name: [(o.kind, o.start_address, o.count) for o in p.ops] for p in SCOPE_WS["paths"]},
                           sort_keys=True)) == "16d3f2d61b8deb4c4536b7b2e4ad046a558fba4979db576a0d2c45d66f71da7f")
check("no Load button and not the new interval touches the bus (no new unattended writer)",
      not any(p.ops for name, p in paths.items() if name in mtou1.LOAD_BUTTONS)
      and not _reaches_bus(FW["interval"][-1]))
check("zero unknown-extent writes and zero hidden bus-access findings", WS["unknown_extent_writes"] == []
      and WS["bus_access_findings"] == [])
check("blueprint item 5 NOT done in Phase 1 (recorded, not silently changed): Manual TOU and the register 244 "
      "proof still share the manual_config_write_enable arm",
      "manual_config_write_enable" in paths["apply_reg244_settings"].arms_checked
      and all("manual_config_write_enable" in paths[s].arms_checked for s in mtou1.APPLY_SCRIPTS))

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All Manual TOU Phase 1 ownership-gate checks passed.")
print("These pin what the firmware SOURCE says and how it executes in the simulator; they prove nothing about hardware.")
