#!/usr/bin/env python3
"""Intelligence V1.1 explanation model: an Advice cannot express an instruction, a BLOCKED advice carries no number, an
OK advice cannot rest on a stale or unknown required input, and confidence always names its factors. Pure, offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import explain as ex  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def refuses(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


C = ex.Confidence.combine([ex.ConfidenceFactor("x", 0.9, "x")])
FRESH_SOC = ex.InputAge.assess("soc", 30.0, 900.0)

print("[1] input ages fail closed")
for bad in (None, float("nan"), float("inf"), -1.0, True, "30"):
    check(f"age {bad!r} of a required input is UNKNOWN", ex.InputAge.assess("soc", bad, 900.0).status == ex.UNKNOWN)
check("a required input with no defined limit is UNKNOWN (cannot be shown fresh)",
      ex.InputAge.assess("soc", 1.0, None).status == ex.UNKNOWN)
check("within the limit is FRESH, beyond it STALE", FRESH_SOC.status == ex.FRESH and ex.InputAge.assess("soc", 901.0, 900.0).status == ex.STALE)
check("an optional input is NOT_REQUIRED and never blocks", not ex.InputAge.assess("x", None, None, required=False).blocks)
check("stale / unknown required inputs block", ex.InputAge.assess("soc", 901.0, 900.0).blocks and ex.InputAge.assess("soc", None, 900.0).blocks)
bl = ex.input_blockers([ex.InputAge.assess("soc", 1800.0, 900.0), ex.InputAge.assess("status", None, 60.0), FRESH_SOC])
check("one blocker per blocking input, with a reason", [b.code for b in bl] == ["STALE_SOC", "UNKNOWN_STATUS"])

print("[2] an Advice cannot express an instruction")
check("mode must be SHADOW", refuses(lambda: ex.Advice("k", ex.OK, {"a": 1}, C, mode="LIVE")))
check("applies_nothing must be True", refuses(lambda: ex.Advice("k", ex.OK, {"a": 1}, C, applies_nothing=False)))
check("BLOCKED needs a blocker", refuses(lambda: ex.Advice("k", ex.BLOCKED, None, C)))
check("BLOCKED carries no recommendation",
      refuses(lambda: ex.Advice("k", ex.BLOCKED, {"a": 1}, C, blocking=(ex.Blocker("B", "b"),))))
check("blockers force BLOCKED", refuses(lambda: ex.Advice("k", ex.OK, {"a": 1}, C, blocking=(ex.Blocker("B", "b"),))))
check("OK cannot rest on a stale required input",
      refuses(lambda: ex.Advice("k", ex.OK, {"a": 1}, C, inputs=(ex.InputAge.assess("soc", 1000.0, 900.0),))))
check("OK carries a recommendation", refuses(lambda: ex.Advice("k", ex.OK, None, C)))
check("an unknown status is refused", refuses(lambda: ex.Advice("k", "MAYBE", None, C)))
check("non-finite numbers cannot be recommended", refuses(lambda: ex.Advice("k", ex.OK, {"kwh": float("nan")}, C)))
a = ex.Advice("k", ex.OK, {"target": 80.0, "drivers": [{"x": 1}]}, C, (ex.Reason("R", "r"),), ("assume",), (), (FRESH_SOC,))
def assign(m, k, v) -> None:
    m[k] = v


mutated = []
for attempt in (lambda: assign(a.recommendation, "target", 10.0), lambda: assign(a.recommendation["drivers"][0], "x", 2)):
    try:
        attempt()
        mutated.append(True)
    except TypeError:
        pass
check("the recommendation is deeply immutable", not mutated)
d = a.to_dict()
check("to_dict is strict JSON and states SHADOW / applies_nothing",
      json.loads(json.dumps(d, allow_nan=False))["applies_nothing"] is True and d["mode"] == "SHADOW"
      and d["recommendation"]["drivers"] == [{"x": 1}])
re_embed = ex.Advice("k", ex.OK, {"prev": a.recommendation, "drivers": a.recommendation["drivers"]}, C)
check("already-frozen advice data can be embedded in a new advice", re_embed.to_dict()["recommendation"]["prev"]["target"] == 80.0)
check("non-JSON data is refused with ValueError (never a TypeError from inside json)",
      refuses(lambda: ex.Advice("k", ex.OK, {"s": {1, 2}}, C)) and refuses(lambda: ex.Advice("k", ex.OK, {"o": object()}, C)))
b = ex.blocked("k", [ex.Blocker("NO_SOC", "no SOC")])
check("blocked() gives INSUFFICIENT confidence and no number", b.status == ex.BLOCKED and b.recommendation is None
      and b.confidence.label == "INSUFFICIENT")

print("[3] confidence is a product of named factors on the V1 scale")
c2 = ex.Confidence.combine([ex.ConfidenceFactor("a", 0.9, "a"), ex.ConfidenceFactor("b", 0.5, "b")])
check("score is the product", abs(c2.score - 0.45) < 1e-12 and c2.label == "LOW")
check("labels follow usage.confidence_label (0.75 / 0.50 / 0.25)",
      [ex.Confidence.combine([ex.ConfidenceFactor("f", v, "")]).label for v in (0.8, 0.6, 0.3, 0.1)]
      == ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"])
check("a cap lowers the label, never raises it",
      ex.Confidence.combine([ex.ConfidenceFactor("f", 0.9, "")], cap_label="LOW").label == "LOW"
      and ex.Confidence.combine([ex.ConfidenceFactor("f", 0.1, "")], cap_label="HIGH").label == "INSUFFICIENT")
check("a non-finite factor counts as zero", ex.Confidence.combine([ex.ConfidenceFactor("f", float("nan"), "")]).score == 0.0)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in intelligence V1.1 explain:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll intelligence V1.1 explain checks passed")
