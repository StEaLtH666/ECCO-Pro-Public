#!/usr/bin/env python3
"""READ-ONLY exporter: Home Assistant long-term statistics -> long-format CSV for ECCO Intelligence.

Run it where the HA recorder database lives (for ECCO: copy to the SSH add-on's /tmp, run with the add-on's
python3, copy the output back, delete both). It opens the SQLite database with mode=ro and
PRAGMA query_only, runs at low priority if you prefix `nice -n 15`, never writes to Home Assistant, never
calls the HA API, never touches secrets, and exports ONLY the statistic ids it is told to (no attributes).

    nice -n 15 python3 export_ha_statistics.py --ids ids.txt --out /tmp/hist
    # -> /tmp/hist_hourly.csv.gz  (long-term statistics, kept indefinitely by HA)
    #    /tmp/hist_5m.csv.gz      (short-term 5-minute statistics, ~10 days)

ids.txt: one statistic_id per line (the entity ids in intelligence/profiles/*.json). Columns written:
statistic_id,start_ts,mean,min,max,state,sum  (start_ts = UTC epoch seconds of the bucket start).
Stdlib only, so it runs unchanged on the HA add-on."""

from __future__ import annotations

import argparse
import csv
import gzip
import sqlite3
import sys


def export(db_path: str, ids: list[str], out_prefix: str) -> dict[str, int]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    con.execute("PRAGMA query_only=1")
    meta = {sid: mid for mid, sid in con.execute("SELECT id, statistic_id FROM statistics_meta") if sid in set(ids)}
    counts = {}
    for table, suffix in (("statistics", "hourly"), ("statistics_short_term", "5m")):
        n = 0
        with gzip.open(f"{out_prefix}_{suffix}.csv.gz", "wt", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["statistic_id", "start_ts", "mean", "min", "max", "state", "sum"])
            for sid, mid in sorted(meta.items()):
                q = f"SELECT start_ts, mean, min, max, state, sum FROM {table} WHERE metadata_id=? ORDER BY start_ts"
                for row in con.execute(q, (mid,)):
                    w.writerow([sid, *row])
                    n += 1
        counts[suffix] = n
    con.close()
    counts["ids_requested"] = len(ids)
    counts["ids_found"] = len(meta)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", default="/config/home-assistant_v2.db")
    ap.add_argument("--ids", required=True, help="text file, one statistic_id per line")
    ap.add_argument("--out", required=True, help="output path prefix")
    a = ap.parse_args()
    with open(a.ids, "r", encoding="utf-8") as fh:
        ids = [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    print(export(a.db, ids, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
