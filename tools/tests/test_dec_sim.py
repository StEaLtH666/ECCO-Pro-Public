#!/usr/bin/env python3
"""CI hook for the dynamic-energy-control offline simulator (docs/dev/dynamic-energy-control/sim/).

REFERENCE MODEL AND TEST BENCH, NOT PRODUCTION CODE. Test-only, no hardware, no Home Assistant, no network. The simulator's own
self-check (sim/test_sim.py) is a plain script and lives next to the code it proves; the folder is not an offline test root, so this
one-file hook runs it from an existing root (tools/tests) without editing tools/offline_test_roots.txt. If a later change lists the
folder as a root, delete this hook.

  [1] the files are where the hook expects them
  [2] the self-check runs in a fresh isolated interpreter, exits 0 and prints its closing line
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = ROOT / "docs" / "dev" / "dynamic-energy-control" / "sim"
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


print("[1] files")
for f in ("kernel.py", "plant.py", "bench.py", "scenarios.py", "run_sim.py", "test_sim.py", "SIM_README.md"):
    check(f"sim/{f} exists", (SIM / f).is_file())

print("")
print("[2] the simulator's self-check")
r = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(SIM / "test_sim.py")], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                   errors="replace", timeout=900)
tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
check("sim/test_sim.py exits 0", r.returncode == 0, f"rc={r.returncode}\n{tail}")
check("sim/test_sim.py prints its closing line", "All dynamic-energy-control simulator checks passed." in r.stdout, tail[-300:])
rr = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(SIM / "run_sim.py")], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=300)
check("sim/run_sim.py exits 0 (every scenario passes)", rr.returncode == 0 and "All scenarios passed." in rr.stdout, rr.stdout[-300:])

print("")
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("All dynamic-energy-control simulator hook checks passed.")
print("The hook proves that the simulator's own self-check passes; it proves nothing about hardware.")
