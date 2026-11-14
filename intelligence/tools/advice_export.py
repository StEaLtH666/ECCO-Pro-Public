#!/usr/bin/env python3
"""Read-only bridge from the scorecard store to the Ghost: print the `advice` list of the ghost export format.

    python intelligence/tools/advice_export.py scorecard.db --from 2026-11-01 --to 2026-11-15 [--kind charge_target]

Opens the database read-only (SQLite URI mode=ro; it never creates, alters or writes anything), reads `advice_log` for rows
issued in [from, to) (UTC; dates or ISO times; both optional) and prints a JSON list of AdviceRecord objects (the `advice`
member of the export described in tools/ghost_report.py) to stdout. A database without the table gives []. Exit 0 on
success, 2 on an unreadable database or bad arguments."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def _utc(text: str) -> str:
    d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def read_advice(db_path: str, start: str | None = None, end: str | None = None, kind: str | None = None) -> list[dict]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='advice_log'").fetchone() is None:
            return []
        sql, args = "SELECT * FROM advice_log WHERE 1=1", []
        if start:
            sql, args = sql + " AND issued_utc >= ?", args + [_utc(start)]
        if end:
            sql, args = sql + " AND issued_utc < ?", args + [_utc(end)]
        if kind:
            sql, args = sql + " AND kind = ?", args + [kind]
        out = []
        for r in db.execute(sql + " ORDER BY issued_utc, advice_id", args):
            out.append({
                "kind": r["kind"], "status": r["status"], "issued_at": r["issued_utc"],
                "window_start": r["window_start_utc"], "window_end": r["window_end_utc"],
                "target_soc_pct": r["target_soc_pct"], "export_kwh": r["export_kwh"], "export_kw": r["export_kw_avg"],
                "effective_reserve_pct": r["effective_reserve_pct"], "conservative_fallback": bool(r["conservative_fallback"]),
                "dump_advisable": True if r["dump_advisable"] is None else bool(r["dump_advisable"]),
                "advice_id": f"advice_log:{r['advice_id']}"})
        return out
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("db")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--kind", choices=("charge_target", "dump_to_grid"))
    a = ap.parse_args(argv)
    try:
        rows = read_advice(a.db, a.start, a.end, a.kind)
    except (sqlite3.Error, ValueError) as e:
        print(f"advice_export: {e}", file=sys.stderr)
        return 2
    json.dump(rows, sys.stdout, indent=1)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
