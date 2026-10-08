#!/usr/bin/env python3
"""FB-D1 seven-day soak evidence analyser - command line. Offline and read-only: it reads export files and writes a report.

    python tools/fbd1_soak_analyse.py history.json [more.json|export.csv|dongle.log[@2026-10-04] ...] --out report-dir

Inputs (auto-detected; see tools/fbd1_soak/README.md): Home Assistant history JSON (REST or websocket), CSV (long or wide)
and `esphome logs` output. A clock-only log needs a date: append `@YYYY-MM-DD` (the date of its first line) unless it
contains an `Inverter RTC: <date> <time> | Difference from NTP: <d> s` line to anchor it.

Outputs in --out: fbd1_soak_analysis.json, fbd1_soak_report.md, fbd1_soak_daily.csv, fbd1_soak_events.csv.

Exit status: 0 analysis written (whatever the verdict); 2 bad arguments or unreadable input. With --verdict-exit-code:
0 PASS, 10 WARNING, 20 INSUFFICIENT_EVIDENCE, 30 FAIL.

It never contacts Home Assistant, the dongle or the inverter.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fbd1_soak import ingest  # noqa: E402
from fbd1_soak.analyse import run, summary_line  # noqa: E402
from fbd1_soak.evidence import Evidence  # noqa: E402
from fbd1_soak.model import DEFAULT_SOAK_DAYS, DEFAULT_SOAK_START, Rules  # noqa: E402
from fbd1_soak.report import write_all  # noqa: E402
from fbd1_soak.timeutil import TimeParseError, parse_ts  # noqa: E402

EXIT = {"PASS": 0, "WARNING": 10, "INSUFFICIENT_EVIDENCE": 20, "FAIL": 30}


def _input(spec: str):
    m = re.match(r"^(.*)@(\d{4}-\d{2}-\d{2})$", spec)
    if m and not Path(spec).exists():
        return Path(m.group(1)), date.fromisoformat(m.group(2))
    return Path(spec), None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("inputs", nargs="+", help="evidence files (HA history JSON, CSV, esphome log[@YYYY-MM-DD])")
    ap.add_argument("--out", default="fbd1-soak-report", help="output directory (default ./fbd1-soak-report)")
    ap.add_argument("--start", help="soak start (ISO; naive = Europe/London). Default 2026-10-04 23:14:37 BST")
    ap.add_argument("--days", type=float, default=DEFAULT_SOAK_DAYS, help="soak length in days (default 7)")
    ap.add_argument("--end", help="soak end (ISO); overrides --days")
    ap.add_argument("--as-of", help="analysis instant (ISO; default now, UTC)")
    ap.add_argument("--threshold", type=float, help="Clock Correction Threshold (s) when the export has no setting row")
    ap.add_argument("--entity", action="append", default=[], metavar="KEY=ENTITY_ID",
                    help="map a catalogue key to an entity id (repeatable), e.g. b10=sensor.my_dongle_live_match")
    ap.add_argument("--rules", help="JSON file overriding decision thresholds (keys of the report's `rules` block)")
    ap.add_argument("--format", choices=("ha-json", "csv", "log"), help="force the input format for every input")
    ap.add_argument("--verdict-exit-code", action="store_true", help="exit 0/10/20/30 for PASS/WARNING/INSUFFICIENT/FAIL")
    a = ap.parse_args(argv)
    try:
        start = parse_ts(a.start, naive_is_local=True) if a.start else DEFAULT_SOAK_START
        end = parse_ts(a.end, naive_is_local=True) if a.end else None
        now = parse_ts(a.as_of, naive_is_local=True) if a.as_of else datetime.now(timezone.utc)
    except TimeParseError as exc:
        ap.error(str(exc))
    if end is not None and end <= start:
        ap.error("--end must be after --start")
    overrides = {}
    for spec in a.entity:
        if "=" not in spec:
            ap.error(f"--entity expects KEY=ENTITY_ID, got {spec!r}")
        k, v = spec.split("=", 1)
        overrides[k.strip()] = v.strip()
    rules = Rules()
    if a.rules:
        data = json.loads(Path(a.rules).read_text(encoding="utf-8"))
        for k, v in data.items():
            if not hasattr(rules, k):
                ap.error(f"unknown rule {k!r}")
            setattr(rules, k, tuple(v) if isinstance(getattr(rules, k), tuple) else v)
    if a.threshold is not None:
        rules.threshold_s = a.threshold
    ev = Evidence()
    for spec in a.inputs:
        path, d = _input(spec)
        if not path.is_file():
            print(f"error: input not found: {path}", file=sys.stderr)
            return 2
        info = ingest.load(path, ev, overrides=overrides, fmt=a.format, log_date=d)
        print(f"read {path.name}: {info.fmt}, {info.accepted} accepted, {info.rejected} rejected of {info.rows} rows")
    rep = run(ev, start=start, days=a.days, end=end, rules=rules, now=now)
    files = write_all(rep, a.out)
    print(summary_line(rep))
    for k, v in files.items():
        print(f"  {k}: {v}")
    return EXIT[rep["overall"]["verdict"]] if a.verdict_exit_code else 0


if __name__ == "__main__":
    sys.exit(main())
