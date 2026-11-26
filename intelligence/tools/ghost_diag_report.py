#!/usr/bin/env python3
"""Read-only report: the existing schedule against Intelligence's advice, from a downloaded diagnostics file. No network, writes
nothing.

    python intelligence/tools/ghost_diag_report.py diagnostics.json [--json]

THE GHOST IS A SIMULATION; Intelligence controlled nothing. The input is the diagnostics download of the ECCO Intelligence
integration (Settings, Devices and services, ECCO Intelligence, Download diagnostics): a whole Home Assistant download (the
block is under data.ghost), a file with a top-level "ghost" key, or the block itself. The report shows, for the period and per
day, the EXISTING SCHEDULE (what the battery really did) against INTELLIGENCE ADVICE (the same flows with the logged advice
applied in a simulation): money in pence when a verified import tariff covers the period (otherwise NO MONEY), the SOC minimum
and end of day, the reserve margin and any breach, the uncertainty and whether the advice effect is beyond it or within the
noise, whether the advice was followed and why not, and the limits. A failure block (not enough history, no advice, an error) is
printed as its status and constant reason; nothing is guessed.

Exit code 0 on a report, 2 on bad input (a one-line message on stderr). --json prints the block instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import ghost_compare  # noqa: E402


def find_block(obj: object) -> dict:
    """The Ghost block of a download (data.ghost), of a file with a `ghost` key, or the block itself."""
    if isinstance(obj, dict):
        if obj.get("schema") == ghost_compare.SCHEMA:
            return obj
        for key in ("ghost", "data"):
            sub = obj.get(key)
            if isinstance(sub, dict):
                try:
                    return find_block(sub)
                except ValueError:
                    pass
    raise ValueError("no Ghost block (schema " + ghost_compare.SCHEMA + ") in the file")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Existing schedule against Intelligence's advice (the Ghost diagnostics block): read-only")
    ap.add_argument("diagnostics", help="the downloaded diagnostics JSON (or the block itself)")
    ap.add_argument("--json", action="store_true", help="print the block as JSON instead of the text report")
    a = ap.parse_args(argv)
    try:
        block = find_block(json.loads(Path(a.diagnostics).read_text(encoding="utf-8")))
        text = json.dumps(block, indent=1, sort_keys=True) if a.json else ghost_compare.render_text(block)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ghost_diag_report: bad input: {type(exc).__name__}: {exc}".splitlines()[0], file=sys.stderr)
        return 2
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
