#!/usr/bin/env python3
"""Intelligence foundation: intelligence/authority_vocab.py (data only).

  [1] DEFAULT_MODE is SHADOW; RUNTIME_ALLOWED_MODES is a subset of {OFF, SHADOW}
  [2] NEVER_ALLOWED is exactly the contract's set (incl. ACS1_REVIEW_OR_PHRASE_AUTOMATION) and disjoint from the candidates
  [3] Outcome: PREPARED is documented as a record only; mock outcomes are marked
  [4] no string contains modbus or any write / service vocabulary; no entity-id shaped string; nothing callable acts
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import authority_vocab as av  # noqa: E402

FAILURES: list[str] = []
SRC = Path(__file__).resolve().parents[1] / "authority_vocab.py"


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


print("== [1] modes")
check("four modes", av.Mode.ALL == ("OFF", "SHADOW", "ASSISTED", "AUTONOMOUS"))
check("DEFAULT_MODE is SHADOW", av.DEFAULT_MODE == "SHADOW")
check("RUNTIME_ALLOWED_MODES is a subset of {OFF, SHADOW}", av.RUNTIME_ALLOWED_MODES <= {"OFF", "SHADOW"}
      and isinstance(av.RUNTIME_ALLOWED_MODES, frozenset))
check("runtime_mode_allowed refuses ASSISTED, AUTONOMOUS and anything unknown",
      av.runtime_mode_allowed("SHADOW") and av.runtime_mode_allowed("OFF")
      and not any(av.runtime_mode_allowed(m) for m in ("ASSISTED", "AUTONOMOUS", "shadow", None, 1, ("SHADOW",))))

print("== [2] action kinds")
check("the candidates", av.ActionKind.CANDIDATES == ("TOU_SLOT_TARGET_SOC", "TOU_SLOT_CHARGE_POWER", "TOU_SLOT_CHARGE_SOURCE", "NOTIFY_OWNER"))
check("NEVER_ALLOWED is exactly the contract's set",
      av.NEVER_ALLOWED == {"PROTECTION_REGISTERS_217_219", "FREE_POWER_ARM", "DUMP_TO_GRID_ARM", "RAW_MANUAL_SLOT_WRITE",
                           "EXPORT_MODE_REG_244", "RAW_BUS_WRITE", "FIRMWARE_CHANGE", "RESERVE_HELPER_WRITE", "CLOCK_WRITE",
                           "UNATTENDED_DUMP_A10P", "ACS1_REVIEW_OR_PHRASE_AUTOMATION"} and isinstance(av.NEVER_ALLOWED, frozenset))
check("NEVER_ALLOWED includes ACS1_REVIEW_OR_PHRASE_AUTOMATION", "ACS1_REVIEW_OR_PHRASE_AUTOMATION" in av.NEVER_ALLOWED)
check("NEVER_ALLOWED is disjoint from the candidates", not (av.NEVER_ALLOWED & set(av.ActionKind.CANDIDATES)))

print("== [3] outcomes, preconditions, refusals")
check("nine outcomes", av.Outcome.ALL == ("RECOMMENDED", "PREPARED", "REQUESTED", "REFUSED", "EXECUTED_MOCK", "VERIFIED_MOCK",
                                          "FAILED", "RESTORE_REQUIRED", "RESTORED_MOCK"))
check("PREPARED is a record only, and documented so",
      av.Outcome.RECORD_ONLY == {"PREPARED"} and "no Home Assistant write" in av.PREPARED_MEANING
      and "no ACS1 Review" in av.PREPARED_MEANING and "PREPARED is a RECORD ONLY" in (ast.get_docstring(ast.parse(SRC.read_text(encoding="utf-8"))) or ""))
check("every executing outcome is a mock outcome", av.Outcome.MOCK_ONLY == {"EXECUTED_MOCK", "VERIFIED_MOCK", "RESTORED_MOCK"}
      and not [o for o in av.Outcome.ALL if "EXECUTED" in o and o not in av.Outcome.MOCK_ONLY])
check("REFUSED is terminal", "REFUSED" in av.Outcome.TERMINAL)
check("precondition and refusal ids are unique upper-case names",
      len(set(av.Precondition.ALL)) == len(av.Precondition.ALL) and len(set(av.RefusalCode.ALL)) == len(av.RefusalCode.ALL)
      and all(re.fullmatch(r"[A-Z0-9_]+", x) for x in av.Precondition.ALL + av.RefusalCode.ALL))
check("the protected-period, decisions and core-refusal ids exist", "NOT_PROTECTED_PERIOD" in av.Precondition.ALL
      and "DECISIONS_SATISFIED" in av.Precondition.ALL and "CORE_AUTHORITY_REFUSED" in av.RefusalCode.ALL)

print("== [4] words and shape")
tree = ast.parse(SRC.read_text(encoding="utf-8"))
strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
check("no string contains modbus", not [s for s in strings if "modbus" in s.lower()])
bad = ("write_register", "esphome", "supervisor_token", "api/services", "call_service", "mqtt", "async_call")
check("no string contains write / service vocabulary", not [s for s in strings if any(b in s.lower() for b in bad)])
ent = re.compile(r"\b(script|button|switch|number|select|input_[a-z]+|esphome|sensor|binary_sensor)\.[a-z0-9_]+")
check("no entity-id shaped string", not [s for s in strings if ent.search(s)])
check("imports: none beyond __future__", {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} == {"__future__"}
      and not [n for n in ast.walk(tree) if isinstance(n, ast.Import)])
funcs = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
check("the only function is the runtime-mode predicate (nothing acts)", funcs == ["runtime_mode_allowed"], str(funcs))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all authority-vocabulary checks passed")
