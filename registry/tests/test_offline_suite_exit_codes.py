#!/usr/bin/env python3
"""Every offline test suite must exit non-zero when any of its checks fails.

2026-09-28 safety-gap audit finding: registry/tests/test_free_power_recovery_force_restore.py
recorded failures in its FAILURES list and printed "FAIL" lines, but never
turned them into an exit status - so CI, which runs each suite as a plain
`python <file>` (.github/workflows/validate-ecco.yml and
validate-free-power-transaction.yml), would have stayed green on a genuine
Force Restore regression.

No I/O beyond reading/running the repo's own test files, no hardware.

  [1] STATIC, every suite CI runs: each file uses the repo's check()/FAILURES
      convention, check() appends to FAILURES on failure, and after the last
      check() call there is an `if FAILURES:` that exits non-zero (at module
      level, or in main() with `sys.exit(main())`). A file in any other
      style is rejected rather than assumed fine.
  [2] DYNAMIC, test_free_power_recovery_force_restore.py (the file the audit
      caught): with one failure injected straight after check() is defined,
      the real file exits non-zero; with its exit block stripped out again,
      the same injected failure exits 0 - reproducing the original bug and
      proving [1] tells the two apart.
  [3] MUTATION: the static checker rejects every real suite with its exit
      block removed.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROOTS_FILE = ROOT / "tools" / "offline_test_roots.txt"


def load_suite_dirs(path: Path = ROOTS_FILE) -> tuple[str, ...]:
    """The single list of offline test roots (tools/offline_test_roots.txt). Fail closed: a missing, empty or
    malformed list raises, it never degrades to 'no suites'."""
    dirs = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("/") or "\\" in line or ".." in line.split("/") or ":" in line:
            raise ValueError(f"bad test root {line!r} in {path}")
        if not (ROOT / line).is_dir():
            raise ValueError(f"test root {line!r} in {path} is not a directory")
        dirs.append(line)
    if not dirs:
        raise ValueError(f"{path} lists no test roots")
    return tuple(dirs)


SUITE_DIRS = load_suite_dirs()
FORCE_RESTORE = ROOT / "registry" / "tests" / "test_free_power_recovery_force_restore.py"
INJECTED = "__offline_suite_exit_code_self_check__"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def discover() -> list[Path]:
    return sorted(p for d in SUITE_DIRS for p in (ROOT / d).rglob("test_*.py"))


def _calls_check(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "check"
        for n in ast.walk(node)
    )


def _mentions_failures(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id == "FAILURES" for n in ast.walk(node))


def _nonzero_const(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, int) and node.value != 0


def _exits_nonzero(stmts: list[ast.stmt]) -> bool:
    """Does this statement list contain sys.exit(N) / raise SystemExit(N), N != 0?"""
    for stmt in stmts:
        for n in ast.walk(stmt):
            if isinstance(n, ast.Call) and len(n.args) == 1 and _nonzero_const(n.args[0]):
                f = n.func
                if (isinstance(f, ast.Attribute) and f.attr == "exit" and isinstance(f.value, ast.Name)
                        and f.value.id == "sys") or (isinstance(f, ast.Name) and f.id == "SystemExit"):
                    return True
    return False


def _returns_nonzero(stmts: list[ast.stmt]) -> bool:
    return any(isinstance(n, ast.Return) and _nonzero_const(n.value) for s in stmts for n in ast.walk(s))


def _failure_gate(body: list[ast.stmt], outcome) -> ast.If | None:
    """The `if FAILURES:` in `body` whose branch satisfies `outcome`, if it
    comes after the last statement in `body` that calls check()."""
    last_check = max((i for i, s in enumerate(body) if _calls_check(s)), default=-1)
    for i, s in enumerate(body):
        if i > last_check and isinstance(s, ast.If) and _mentions_failures(s.test) and outcome(s.body):
            return s
    return None


def exit_wiring_problems(source: str) -> tuple[list[str], ast.stmt | None]:
    """(problems, the statement that carries the non-zero exit)."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"does not parse: {exc}"], None
    body = tree.body
    has_failures = any(
        isinstance(s, (ast.Assign, ast.AnnAssign))
        and any(isinstance(t, ast.Name) and t.id == "FAILURES"
                for t in (s.targets if isinstance(s, ast.Assign) else [s.target]))
        for s in body
    )
    check_def = next((s for s in body if isinstance(s, ast.FunctionDef) and s.name == "check"), None)
    if not has_failures or check_def is None:
        return ["not in the repo's check()/FAILURES style - exit status cannot be proved"], None
    problems = []
    if not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "append"
        and isinstance(n.func.value, ast.Name) and n.func.value.id == "FAILURES"
        for n in ast.walk(check_def)
    ):
        problems.append("check() never appends to FAILURES")
    gate = _failure_gate(body, _exits_nonzero)
    if gate is not None:
        return problems, gate
    main = next((s for s in body if isinstance(s, ast.FunctionDef) and s.name == "main"), None)
    main_gate = _failure_gate(main.body, _returns_nonzero) if main else None
    runner = next(
        (s for s in body if isinstance(s, ast.If) and any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "main"
            and isinstance(p, ast.Call) and n in p.args
            and ((isinstance(p.func, ast.Attribute) and p.func.attr == "exit") or
                 (isinstance(p.func, ast.Name) and p.func.id == "SystemExit"))
            for p in ast.walk(s) for n in ast.walk(p))),
        None,
    )
    if main_gate is not None and runner is not None:
        return problems, runner
    return problems + ["no `if FAILURES:` exiting non-zero after the last check() call"], None


def strip(source: str, stmt: ast.stmt) -> str:
    lines = source.splitlines(keepends=True)
    return "".join(lines[: stmt.lineno - 1] + lines[stmt.end_lineno:])


def inject_failure(source: str) -> str:
    """Record one failure right after check() is defined."""
    tree = ast.parse(source)
    check_def = next(s for s in tree.body if isinstance(s, ast.FunctionDef) and s.name == "check")
    lines = source.splitlines(keepends=True)
    lines.insert(check_def.end_lineno, f"FAILURES.append({INJECTED!r})\n")
    return "".join(lines)


RUNNER = (
    "import os, sys\n"
    "path = sys.argv[1]\n"
    "sys.path.insert(0, os.path.dirname(path))\n"
    "code = compile(sys.stdin.read(), path, 'exec')\n"
    "exec(code, {'__name__': '__main__', '__file__': path})\n"
)


def run_source(path: Path, source: str) -> subprocess.CompletedProcess:
    """Run `source` exactly as if it were `path` (same __file__ and sys.path)."""
    return subprocess.run(
        [sys.executable, "-c", RUNNER, str(path)],
        input=source, capture_output=True, text=True, cwd=ROOT, timeout=600,
    )


# ---------------------------------------------------------------------------
print("[1] Static: every offline suite CI runs turns a recorded failure into a non-zero exit")
# ---------------------------------------------------------------------------
suites = discover()
check("offline suites were discovered", len(suites) > 20, f"{len(suites)} found")
check("this self-check is itself one of the discovered suites", Path(__file__).resolve() in suites)
check("test_free_power_recovery_force_restore.py is one of the discovered suites", FORCE_RESTORE in suites)
SOURCES: dict[Path, str] = {}
GATES: dict[Path, ast.stmt] = {}
for path in suites:
    rel = path.relative_to(ROOT)
    SOURCES[path] = path.read_text(encoding="utf-8")
    problems, gate = exit_wiring_problems(SOURCES[path])
    check(f"{rel}: a failed check makes the process exit non-zero", not problems and gate is not None,
          "; ".join(problems))
    if gate is not None:
        GATES[path] = gate

# ---------------------------------------------------------------------------
print("")
print("[2] Dynamic: Force Restore suite with an injected failure")
# ---------------------------------------------------------------------------
fr_source = SOURCES.get(FORCE_RESTORE, "")
fr_gate = GATES.get(FORCE_RESTORE)
if fr_source and fr_gate is not None:
    fixed = run_source(FORCE_RESTORE, inject_failure(fr_source))
    check("with one injected failure, the real Force Restore suite exits non-zero",
          fixed.returncode != 0, f"returncode={fixed.returncode}")
    check("...and that exit is owed to the injected failure being reported, not a crash",
          INJECTED in fixed.stdout and "Traceback" not in fixed.stderr, fixed.stderr[-300:])
    buggy = run_source(FORCE_RESTORE, inject_failure(strip(fr_source, fr_gate)))
    check("with its exit block stripped (the pre-fix file), the same injected failure exits 0 - the bug reproduces",
          buggy.returncode == 0, f"returncode={buggy.returncode}")
    check("the static checker rejects that stripped file", bool(exit_wiring_problems(strip(fr_source, fr_gate))[0]))
else:
    check("Force Restore suite has a recognised exit block to exercise", False)

# ---------------------------------------------------------------------------
print("")
print("[3] Mutation: every real suite with its exit block removed is rejected")
# ---------------------------------------------------------------------------
for path, gate in GATES.items():
    problems, _ = exit_wiring_problems(strip(SOURCES[path], gate))
    check(f"{path.relative_to(ROOT)}: exit block removed -> rejected", bool(problems))
# A gate placed before later checks does not cover them.
early = "import sys\nFAILURES = []\ndef check(n, c):\n    if not c:\n        FAILURES.append(n)\n" \
        "if FAILURES:\n    sys.exit(1)\ncheck('late', False)\n"
check("an `if FAILURES: sys.exit(1)` placed BEFORE a later check() is rejected", bool(exit_wiring_problems(early)[0]))
zero = "import sys\nFAILURES = []\ndef check(n, c):\n    if not c:\n        FAILURES.append(n)\n" \
       "check('x', False)\nif FAILURES:\n    sys.exit(0)\n"
check("an `if FAILURES:` that exits 0 is rejected", bool(exit_wiring_problems(zero)[0]))
no_append = "import sys\nFAILURES = []\ndef check(n, c):\n    print(n)\n" \
            "check('x', False)\nif FAILURES:\n    sys.exit(1)\n"
check("a check() that never appends to FAILURES is rejected", bool(exit_wiring_problems(no_append)[0]))

# ---------------------------------------------------------------------------
print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All offline suite exit-code checks passed.")
