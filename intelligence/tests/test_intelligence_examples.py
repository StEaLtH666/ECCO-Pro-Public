#!/usr/bin/env python3
"""The shipped examples (docs/intelligence/examples/*.json) are exactly what a fresh run of the synthetic generator produces
(numeric tolerance for platform libm differences; `feature_hash` ignored), they are marked synthetic, and no stray file
(for instance a real-data export) sits next to them. Also pins that the mock sensor package equals the render of the
checked-in live example (the dashboard prototype test covers that too) and that no checked-in example mentions a real year."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "intelligence" / "tools"))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


import make_examples as mx  # noqa: E402

EX = ROOT / "docs" / "intelligence" / "examples"

section("examples are the generator's output")
built = mx.build_all()
problems: list[str] = []
for name, obj in built.items():
    f = EX / name
    if not f.exists():
        problems.append(f"{name}: missing")
        continue
    problems += [f"{name}{p}" for p in mx.close(obj, json.loads(f.read_text(encoding="utf-8")))]
check("every checked-in example equals a fresh synthetic run", not problems, "; ".join(problems[:5]))
extra = sorted(p.name for p in EX.glob("*") if p.name not in built)
check("no file in examples/ other than the generator's outputs", not extra, str(extra))
check("the generator is deterministic in process", mx.dump(mx.build_reports()["cold"]) == mx.dump(mx.build_reports()["cold"]))

section("examples are marked synthetic and carry no real-year dates")
reps = [json.loads(p.read_text(encoding="utf-8")) for p in EX.glob("example_*.json") if p.name != mx.ACC_FILE]
check("six reports, each marked synthetic", len(reps) == 6 and all(r["_example"].get("synthetic") is True for r in reps))
blob = "\n".join(p.read_text(encoding="utf-8") for p in EX.glob("*.json"))
check("no 2024-2026 dates anywhere in the examples (fictional year only)",
      not any(f"{y}-" in blob for y in ("2024", "2025", "2026")))
check("the accuracy history says it is synthetic", "SYNTHETIC" in json.loads((EX / mx.ACC_FILE).read_text(encoding="utf-8"))["_description"])

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence examples:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print("All intelligence examples checks PASSED.")
