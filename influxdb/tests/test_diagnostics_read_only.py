#!/usr/bin/env python3
"""Offline static checks for influxdb/diagnostics/.

Every diagnostic script must remain read-only and unscheduled:
  - no `option task`
  - no `to(` call

The Task 006 system-health diagnostics additionally carry the explicit
READ-ONLY / MANUAL / AD-HOC header and SYSTEM_HEALTH_ARCHITECTURE.md
reference required by that task.

No I/O beyond reading local files - does not connect to InfluxDB.
"""

from __future__ import annotations

import sys
from pathlib import Path

DIAGNOSTICS_DIR = Path(__file__).resolve().parents[1] / "diagnostics"

FAILURES: list[str] = []

TASK006_DOCUMENTED_SCRIPTS = {
    "history_depth_check.flux",
    "latest_battery_outlook_result.flux",
    "latest_battery_outlook_score.flux",
    "latest_ecco_5m_point.flux",
    "latest_ecco_raw_point.flux",
}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


scripts = sorted(DIAGNOSTICS_DIR.glob("*.flux"))

print(f"[1] influxdb/diagnostics/ contains at least one script")
check("at least one .flux diagnostic script exists", len(scripts) > 0, str(DIAGNOSTICS_DIR))
check(
    "all Task 006 diagnostic scripts are present",
    TASK006_DOCUMENTED_SCRIPTS.issubset({path.name for path in scripts}),
)

for path in scripts:
    print("")
    print(f"[{path.name}]")
    text = path.read_text(encoding="utf-8")

    # `option task`/`to(` are explicitly allowed to appear IN COMMENTS
    # (e.g. this file's own header explaining the prohibition) - only
    # executable (non-comment) lines are checked, per the task's own
    # instruction ("unless merely shown in comments as something
    # explicitly prohibited").
    code_lines = [line for line in text.splitlines() if not line.strip().startswith("//")]
    code_text = "\n".join(code_lines)

    check("does not declare 'option task' outside a comment (would make it a scheduled production task)", "option task" not in code_text)
    check("does not call to( outside a comment (would make it a write)", "to(" not in code_text)
    if path.name in TASK006_DOCUMENTED_SCRIPTS:
        check(
            "header comment states READ-ONLY / MANUAL / AD-HOC",
            "READ-ONLY" in text and "MANUAL" in text and "AD-HOC" in text,
        )
        check(
            "references docs/SYSTEM_HEALTH_ARCHITECTURE.md",
            "docs/SYSTEM_HEALTH_ARCHITECTURE.md" in text,
        )

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All InfluxDB diagnostic read-only checks PASSED.")

if FAILURES:
    sys.exit(1)
