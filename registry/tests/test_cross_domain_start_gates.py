#!/usr/bin/env python3
"""Cross-domain START admission gates: Dump to Grid and Free Power.

2026-09-28 safety-gap audit finding: deleting any one of the cross-domain
terms from `start_dump_to_grid_override`'s admission `if:` (the Free Power
obligation/in-flight flags, the register 244 proof transaction flags, the
RTC-correction flag), or Dump's own flags from `start_free_power_override`'s
admission `if:`, left the entire offline suite green. Only the shared
`manual_write_in_progress` term was pinned (indirectly, by
test_write_surface_invariants.py). This file closes that gap. It changes
no firmware; it pins what the firmware already does.

No I/O, no hardware, no ESPHome/C++ toolchain. Three layers:

  [1]-[3] STRUCTURE, from the real parsed ESPHome action tree (not text
          offsets or comments): each start script's admission gate is the
          first `if:` in the script, nothing before or after it (and
          nothing in its `else:`) can reach the Modbus bus or dispatch a
          script, and its condition lambda is a single
          `return a && b && ...;` whose top-level conjuncts include every
          required `!id(flag)` term. C++ comments are stripped first, so a
          commented-out term does not count, and a term that is only
          reachable through `||` or `?:` is not accepted as a conjunct.
  [4]     REFERENCE MODEL, driven by the conjuncts extracted from the real
          source: the other domain's every in-flight / durable-obligation
          phase (and each such flag on its own) must make the start
          refuse, and the all-idle state must admit it. This is the Free
          Power <-> Dump mutual exclusion: neither domain can start while
          the other holds an outstanding obligation over their shared
          registers 256-261 (and 244 for Dump).
  [5]     MUTATION SELF-TEST: every required term is removed from the real
          gate lambda (and separately commented out, and separately turned
          into an `||` alternative) in memory, and the checker above is
          shown to reject every mutant. So this file cannot silently turn
          vacuous.

These prove what the firmware SOURCE says, never how the compiled firmware
behaves on hardware.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"
sys.path.insert(0, str(ROOT / "tools"))

from analyze_write_surface import (  # noqa: E402
    _load_firmware_yaml,
    _strip_cpp_comments_and_literals,
)

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not FIRMWARE_PATH.is_file():
    print(f"  FAIL  firmware not found at {FIRMWARE_PATH}")
    sys.exit(1)

fw_doc = _load_firmware_yaml(FIRMWARE_PATH.read_text(encoding="utf-8"))
SCRIPTS = {s["id"]: s for s in fw_doc["script"] if isinstance(s, dict) and "id" in s}

DUMP_START = "start_dump_to_grid_override"
FREE_POWER_START = "start_free_power_override"

# Free Power's in-flight flag and durable obligation flags (RAM mirrors of
# its durable marker): any one of them set means Free Power owns, or is
# about to own, registers 230/232/256-261/268-279.
FREE_POWER_FLAGS = ("free_power_operation_in_progress", "free_power_snapshot_valid", "free_power_active_persisted")
# Dump's equivalents over 244/256-261.
DUMP_FLAGS = ("dump_operation_in_progress", "dump_snapshot_valid", "dump_active_persisted")
# The register 244 proof transaction (Dump also writes 244).
REG244_FLAGS = ("reg244_apply_in_progress", "reg244_snapshot_valid")
# Other bus owners: the shared write mutex and the RTC correction.
BUS_FLAGS = ("manual_write_in_progress", "correction_in_progress")

REQUIRED_TERMS = {
    DUMP_START: {
        "cross-domain: Free Power": [f"!id({f})" for f in FREE_POWER_FLAGS],
        "cross-domain: register 244 proof transaction": [f"!id({f})" for f in REG244_FLAGS],
        "shared bus": [f"!id({f})" for f in BUS_FLAGS],
        "own domain": [f"!id({f})" for f in DUMP_FLAGS] + ["!id(dump_recovery_metadata_corrupt)"],
    },
    FREE_POWER_START: {
        # Free Power does not name dump_operation_in_progress directly: an
        # in-flight Dump start is excluded through manual_write_in_progress,
        # which Dump sets in the same lambda (proved in [3]).
        "cross-domain: Dump to Grid": ["!id(dump_active_persisted)", "!id(dump_snapshot_valid)"],
        "cross-domain: register 244 proof transaction": ["!id(reg244_snapshot_valid)"],
        "shared bus": [f"!id({f})" for f in BUS_FLAGS],
        "own domain": [f"!id({f})" for f in FREE_POWER_FLAGS] + ["!id(free_power_recovery_metadata_corrupt)"],
    },
}

# What each start sets true, in its first then-branch action, before any
# Modbus traffic - its in-flight claim other gates test.
START_ACQUIRES = {
    DUMP_START: ("dump_operation_in_progress", "manual_write_in_progress"),
    FREE_POWER_START: ("free_power_operation_in_progress", "manual_write_in_progress"),
}


# ---------------------------------------------------------------------------
# Structural helpers over the real ESPHome action tree
# ---------------------------------------------------------------------------
def _reaches_bus(node) -> list[str]:
    """Every Modbus action / script dispatch anywhere inside `node`."""
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
            if inner is None:  # a parenthesised non-conjunction is one opaque term
                out.append(re.sub(r"\s+", "", part))
            else:
                out += inner
        else:
            out.append(re.sub(r"\s+", "", part))
    return out


def gate_problems(script: dict, required: list[str]) -> tuple[list[str], list[str]]:
    """(problems, conjuncts) for a start script's admission gate."""
    problems: list[str] = []
    actions = script.get("then")
    if not isinstance(actions, list):
        return ["script has no `then:` action list"], []
    gate_idx = next((i for i, a in enumerate(actions) if isinstance(a, dict) and "if" in a), None)
    if gate_idx is None:
        return ["no admission `if:` in the script"], []
    for a in actions[:gate_idx]:
        if _reaches_bus(a):
            problems.append(f"bus access/dispatch BEFORE the admission gate: {_reaches_bus(a)}")
    for a in actions[gate_idx + 1 :]:
        if _reaches_bus(a):
            problems.append(f"bus access/dispatch AFTER (outside) the admission gate: {_reaches_bus(a)}")
    gate = actions[gate_idx]["if"]
    if _reaches_bus(gate.get("else")):
        problems.append("the admission gate's else: branch reaches the bus")
    if not _reaches_bus(gate.get("then")):
        problems.append("the admission gate's then: branch never reaches the bus (wrong if: picked?)")
    cond = gate.get("condition")
    if not (isinstance(cond, dict) and set(cond) == {"lambda"} and isinstance(cond["lambda"], str)):
        return problems + ["admission condition is not a single lambda"], []
    code = _strip_cpp_comments_and_literals(cond["lambda"])
    m = re.fullmatch(r"\s*return\b(.*);\s*", code, re.S)
    if not m or re.search(r"\breturn\b", m.group(1)):
        return problems + ["admission lambda is not a single `return <expr>;`"], []
    terms = conjuncts(m.group(1))
    if terms is None:
        return problems + ["admission condition is not a pure && conjunction (top-level || or ?:)"], []
    for term in required:
        if term not in terms:
            problems.append(f"required conjunct {term} missing")
    return problems, terms


def admits(terms: list[str], state: set[str]) -> bool:
    """Reference model: evaluate the extracted gate for a flag state.

    Every `!id(flag)` conjunct requires `flag` false. Every other conjunct
    (sensor ranges, arm switch, bus quiescence...) is taken as satisfied -
    the most permissive environment, so a refusal here is owed to the
    ownership flags alone.
    """
    for t in terms:
        m = re.fullmatch(r"!id\((\w+)\)", t)
        if m and m.group(1) in state:
            return False
    return True


# ---------------------------------------------------------------------------
print("[1] Both start scripts exist and have a single structural admission gate")
# ---------------------------------------------------------------------------
GATE_TERMS: dict[str, list[str]] = {}
for name, groups in REQUIRED_TERMS.items():
    script = SCRIPTS.get(name)
    check(f"{name}: script exists", script is not None)
    if script is None:
        continue
    required = [t for ts in groups.values() for t in ts]
    problems, terms = gate_problems(script, required)
    GATE_TERMS[name] = terms
    structural = [p for p in problems if "required conjunct" not in p]
    check(
        f"{name}: every Modbus action and script dispatch sits inside the admission gate's then: branch, "
        "and the gate is a single pure && conjunction",
        not structural,
        "; ".join(structural),
    )

# ---------------------------------------------------------------------------
print("")
print("[2] Every required cross-domain / shared-bus / own-domain term is a top-level conjunct")
# ---------------------------------------------------------------------------
for name, groups in REQUIRED_TERMS.items():
    terms = GATE_TERMS.get(name, [])
    for group, required in groups.items():
        for term in required:
            check(f"{name} [{group}]: gate requires {term}", term in terms)

# ---------------------------------------------------------------------------
print("")
print("[3] Each start claims its in-flight flags before any Modbus traffic")
# ---------------------------------------------------------------------------
for name, flags in START_ACQUIRES.items():
    script = SCRIPTS.get(name)
    if script is None:
        continue
    gate_then = next(a["if"]["then"] for a in script["then"] if isinstance(a, dict) and "if" in a)
    first = gate_then[0] if gate_then else None
    first_code = _strip_cpp_comments_and_literals(first.get("lambda", "")) if isinstance(first, dict) else ""
    for flag in flags:
        check(
            f"{name}: the gate's first then: action (a lambda, before any Modbus action) sets id({flag}) = true",
            re.search(rf"\bid\({flag}\)\s*=\s*true\s*;", first_code) is not None,
        )

# ---------------------------------------------------------------------------
print("")
print("[4] Reference model driven by the real gate: Free Power <-> Dump mutual exclusion")
# ---------------------------------------------------------------------------
# Realistic phases of each domain, as the set of flags true in that phase,
# plus every flag on its own (so each term is proved individually needed -
# e.g. a post-reboot RAM mirror left with only one flag set).
FREE_POWER_PHASES = {
    "start in flight (before durable snapshot)": {"free_power_operation_in_progress", "manual_write_in_progress"},
    "snapshot committed, writes in flight": {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"},
    "active lease": {"free_power_snapshot_valid", "free_power_active_persisted"},
    "restore owed (end/restore not yet verified)": {"free_power_snapshot_valid"},
    "restore in flight": {"free_power_operation_in_progress", "manual_write_in_progress", "free_power_snapshot_valid"},
    **{f"only {f}": {f} for f in FREE_POWER_FLAGS},
}
DUMP_PHASES = {
    "start in flight (before durable snapshot)": {"dump_operation_in_progress", "manual_write_in_progress"},
    "snapshot committed, writes in flight": {"dump_operation_in_progress", "manual_write_in_progress", "dump_snapshot_valid"},
    "active lease": {"dump_snapshot_valid", "dump_active_persisted"},
    "restore owed (end/restore not yet verified)": {"dump_snapshot_valid"},
    "restore in flight": {"dump_operation_in_progress", "manual_write_in_progress", "dump_snapshot_valid"},
    "only dump_active_persisted": {"dump_active_persisted"},
    "only dump_snapshot_valid": {"dump_snapshot_valid"},
}
REG244_PHASES = {
    "proof apply in flight": {"reg244_apply_in_progress", "manual_write_in_progress"},
    "proof snapshot owed": {"reg244_snapshot_valid"},
    **{f"only {f}": {f} for f in REG244_FLAGS},
}
OTHER_BUS_PHASES = {f"only {f}": {f} for f in BUS_FLAGS}


def mutual_exclusion_problems(dump_terms: list[str], fp_terms: list[str]) -> list[str]:
    problems = []
    if not admits(dump_terms, set()):
        problems.append("Dump start refused in the all-idle state")
    if not admits(fp_terms, set()):
        problems.append("Free Power start refused in the all-idle state")
    for label, state in {**FREE_POWER_PHASES, **REG244_PHASES, **OTHER_BUS_PHASES}.items():
        if admits(dump_terms, state):
            problems.append(f"Dump start ADMITTED while {label}")
    for label, state in {**DUMP_PHASES, **OTHER_BUS_PHASES}.items():
        if admits(fp_terms, state):
            problems.append(f"Free Power start ADMITTED while Dump {label}")
    if admits(fp_terms, {"reg244_snapshot_valid"}):
        problems.append("Free Power start ADMITTED while a register 244 proof snapshot is owed")
    return problems


DUMP_TERMS = GATE_TERMS.get(DUMP_START, [])
FP_TERMS = GATE_TERMS.get(FREE_POWER_START, [])
check("both domains are admitted when every flag is clear (the model is not vacuously refusing)",
      admits(DUMP_TERMS, set()) and admits(FP_TERMS, set()))
for label, state in FREE_POWER_PHASES.items():
    check(f"Dump START refused while Free Power: {label}", not admits(DUMP_TERMS, state))
for label, state in REG244_PHASES.items():
    check(f"Dump START refused while register 244: {label}", not admits(DUMP_TERMS, state))
for label, state in DUMP_PHASES.items():
    check(f"Free Power START refused while Dump: {label}", not admits(FP_TERMS, state))
for label, state in OTHER_BUS_PHASES.items():
    check(f"both STARTs refused while {label}", not admits(DUMP_TERMS, state) and not admits(FP_TERMS, state))
check("Free Power START refused while a register 244 proof snapshot is owed",
      not admits(FP_TERMS, {"reg244_snapshot_valid"}))
# Sequential composition: whichever domain wins the race, its own start
# acquisition (proved in [3]) is enough to refuse the other.
check("a Dump start that has claimed its flags refuses a Free Power start",
      not admits(FP_TERMS, set(START_ACQUIRES[DUMP_START])))
check("a Free Power start that has claimed its flags refuses a Dump start",
      not admits(DUMP_TERMS, set(START_ACQUIRES[FREE_POWER_START])))
check("the combined mutual-exclusion checker reports no problem on the real firmware",
      not mutual_exclusion_problems(DUMP_TERMS, FP_TERMS),
      "; ".join(mutual_exclusion_problems(DUMP_TERMS, FP_TERMS)))

# ---------------------------------------------------------------------------
print("")
print("[5] Mutation self-test: removing / commenting out / weakening any required term is caught")
# ---------------------------------------------------------------------------


def _mutant(script: dict, code: str) -> dict:
    """A shallow copy of `script` whose admission lambda is `code`."""
    actions = list(script["then"])
    idx = next(i for i, a in enumerate(actions) if isinstance(a, dict) and "if" in a)
    gate = dict(actions[idx]["if"])
    gate["condition"] = {"lambda": code}
    actions[idx] = {"if": gate}
    return {**script, "then": actions}


def _caught(name: str, mutant: dict) -> bool:
    required = [t for ts in REQUIRED_TERMS[name].values() for t in ts]
    problems, terms = gate_problems(mutant, required)
    other = FP_TERMS if name == DUMP_START else DUMP_TERMS
    pair = (terms, other) if name == DUMP_START else (other, terms)
    return bool(problems) or bool(mutual_exclusion_problems(*pair))


for name, groups in REQUIRED_TERMS.items():
    script = SCRIPTS.get(name)
    if script is None:
        continue
    original = next(a["if"]["condition"]["lambda"] for a in script["then"] if isinstance(a, dict) and "if" in a)
    check(f"{name}: the unmutated gate is accepted (baseline for the mutants below)", not _caught(name, script))
    for term in (t for ts in groups.values() for t in ts):
        anchor = re.compile(re.escape(term) + r"\s*&&")
        matches = anchor.findall(original)
        check(f"{name}: {term} appears exactly once as `{term} &&` (mutation anchor)", len(matches) == 1,
              f"found {len(matches)}")
        if len(matches) != 1:
            continue
        removed = anchor.sub("", original)
        commented = anchor.sub(lambda m: f"/* {term} && */", original)
        weakened = anchor.sub(lambda m: f"({term} || true) &&", original)
        or_chain = anchor.sub(lambda m: f"{term} ||", original)
        check(f"{name}: mutant with {term} REMOVED is rejected", _caught(name, _mutant(script, removed)))
        check(f"{name}: mutant with {term} COMMENTED OUT is rejected", _caught(name, _mutant(script, commented)))
        check(f"{name}: mutant with {term} weakened to ({term} || true) is rejected",
              _caught(name, _mutant(script, weakened)))
        check(f"{name}: mutant joining {term} with || is rejected", _caught(name, _mutant(script, or_chain)))

    # A Modbus action hoisted in front of the gate must be caught too.
    hoisted = {**script, "then": [{"modbus_client.read_holding_registers": {"start_address": 244, "count": 1}}]
               + list(script["then"])}
    check(f"{name}: mutant with a Modbus action BEFORE the admission gate is rejected", _caught(name, hoisted))
    early_return = "return true;\n" + original
    check(f"{name}: mutant with an early `return true;` is rejected", _caught(name, _mutant(script, early_return)))

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All cross-domain START admission gate checks passed.")
print("These pin what the firmware SOURCE says; they prove nothing about hardware behaviour.")
