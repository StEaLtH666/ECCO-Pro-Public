#!/usr/bin/env python3
"""Offline, read-only replay of saved Home Assistant history for the control-authority analysis (CONTROL_AUTHORITY.md).

Prints AGGREGATE numbers only. It never prints an entity id, a site name or a raw row, so its output can be quoted in a
public document. It reads only the files named on the command line; it writes nothing and contacts nothing.

Sign conventions (registry/inverter_capabilities.yaml): battery power (register 190) positive = discharge, negative =
charge, DC side; grid CT (register 172) positive = import, negative = export; PV (186-189) >= 0, DC side; house = the
whole-house consumption entity; inverter AC power = grid - house (the inverter's own AC power by its own accounting).

Usage:
  python -I -B -X utf8 evidence_replay.py nights <folder with hist-<batt|grid|house|pv>-YYYY-MM-DD.json> <day> [<day> ...]
  python -I -B -X utf8 evidence_replay.py event <history.json> <start ISO UTC> <end ISO UTC>

`nights` analyses 00:00-07:00 UTC of each day: the charge plateau (DC charge above 7 kW), the inverter AC input, the
relation between house load and battery charge, the cliff after the plateau and the telemetry cadence.
`event` resamples one saved history export (a dict with a "history" list of per-entity row lists, or a plain list of
them) every 30 s between two instants for the battery, voltage, grid CT, house, PV and inverter AC series, matched by the
END of the entity id only (never by a site prefix).
"""

from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import statistics as st
import sys
from pathlib import Path


def _rows(series: list) -> list[tuple[float, float]]:
    out = []
    for r in series:
        try:
            t = dt.datetime.fromisoformat(r["last_changed"]).timestamp()
            v = float(r["state"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(v):
            out.append((t, v))
    out.sort()
    return out


def _sampler(rows: list[tuple[float, float]], max_age: float = 60.0):
    ts = [t for t, _ in rows]

    def at(t: float):
        i = bisect.bisect_right(ts, t) - 1
        if i < 0 or t - ts[i] > max_age:
            return None
        return rows[i][1]
    return at


def _pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _corr(a, b):
    if len(a) < 3:
        return float("nan")
    ma, mb = st.fmean(a), st.fmean(b)
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return float("nan")
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def _fit(x, y):
    mx, my = st.fmean(x), st.fmean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx == 0:
        return float("nan"), float("nan")
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx
    return b, my - b * mx


def _hhmm(t: float) -> str:
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M")


def nights(folder: Path, days: list[str]) -> None:
    pooled = []
    for day in days:
        def load(kind):
            data = json.load(open(folder / f"hist-{kind}-{day}.json", encoding="utf-8"))
            return _rows([r for ser in data for r in ser])
        braw = load("batt")
        B, G, H, P = _sampler(braw), _sampler(load("grid")), _sampler(load("house")), _sampler(load("pv"))
        t0 = dt.datetime.fromisoformat(day + "T00:00:00+00:00").timestamp()
        pts = []
        t = t0
        while t < t0 + 7 * 3600:
            b, g, h, p = B(t), G(t), H(t), P(t)
            if None not in (b, g, h):
                pts.append((t, b, g, h, 0.0 if p is None else p))
            t += 10
        plateau = [x for x in pts if x[1] < -7000]
        if not plateau:
            print(f"{day}: no charge plateau")
            continue
        ps, pe = plateau[0][0], plateau[-1][0]
        dc = [-x[1] for x in plateau]
        grid = [x[2] for x in plateau]
        house = [x[3] for x in plateau]
        acin = [g - h for g, h in zip(grid, house)]
        ratio = [a / c for a, c in zip(acin, dc)]
        slope, icpt = _fit(house, grid)
        q1, q3 = _pct(house, 0.25), _pct(house, 0.75)
        lo = [c for c, h in zip(dc, house) if h < q1]
        hi = [c for c, h in zip(dc, house) if h > q3]
        first = [-x[1] for x in plateau if ps + 300 < x[0] < ps + 1800]
        last = [-x[1] for x in plateau if pe - 2100 < x[0] < pe - 300]
        below2 = next((x for x in pts if x[0] > pe and -x[1] < 2000), None)
        gaps = [b - a for a, b in zip([t for t, _ in braw if ps <= t <= pe], [t for t, _ in braw if ps <= t <= pe][1:])]
        print(f"{day}: plateau {_hhmm(ps)}-{_hhmm(pe)} UTC ({(pe - ps) / 60:.0f} min, n={len(plateau)})")
        print(f"  DC charge W p05/p50/p95/max {_pct(dc, .05):.0f}/{_pct(dc, .5):.0f}/{_pct(dc, .95):.0f}/{max(dc):.0f}; "
              f"grid import W p05/p50/p95/max {_pct(grid, .05):.0f}/{_pct(grid, .5):.0f}/{_pct(grid, .95):.0f}/{max(grid):.0f}; "
              f"house W p05/p50/p95/max {_pct(house, .05):.0f}/{_pct(house, .5):.0f}/{_pct(house, .95):.0f}/{max(house):.0f}")
        print(f"  inverter AC input (grid - house) W p05/p50/p95 {_pct(acin, .05):.0f}/{_pct(acin, .5):.0f}/{_pct(acin, .95):.0f}; "
              f"AC per DC W p50 {_pct(ratio, .5):.4f}")
        print(f"  corr(house, DC) {_corr(house, dc):+.2f}; grid = {slope:.3f} x house + {icpt:.0f} W; "
              f"DC mean at house lowest / highest quartile {st.fmean(lo):.0f} / {st.fmean(hi):.0f} W")
        if first and last:
            print(f"  plateau DC first 5-30 min {st.fmean(first):.0f} W, last 35-5 min {st.fmean(last):.0f} W "
                  f"({100 * (st.fmean(last) / st.fmean(first) - 1):+.1f} %)")
        if below2:
            print(f"  cliff: last DC > 7 kW to first DC < 2 kW {(below2[0] - pe) / 60:.1f} min")
        if gaps:
            print(f"  battery history cadence s median/p95/max {st.median(gaps):.1f}/{_pct(gaps, .95):.1f}/{max(gaps):.1f}")
        pooled += list(zip(dc, grid, house))
    if pooled:
        dc, grid, house = zip(*pooled)
        print(f"ALL: n={len(pooled)} DC p05/p50/p95 {_pct(dc, .05):.0f}/{_pct(dc, .5):.0f}/{_pct(dc, .95):.0f}; grid "
              f"p05/p50/p95/max {_pct(grid, .05):.0f}/{_pct(grid, .5):.0f}/{_pct(grid, .95):.0f}/{max(grid):.0f}; "
              f"house p50/max {_pct(house, .5):.0f}/{max(house):.0f}")


EVENT_KEYS = (("battery_output_power", "batt W"), ("battery_voltage", "batt V"), ("grid_power_ct_clamp", "grid W"),
              ("ecco_load_power", "house W"), ("ecco_pv_power", "pv W"), ("inverter_output_power_l1", "inv AC W"))


def event(path: Path, start: str, end: str) -> None:
    data = json.load(open(path, encoding="utf-8"))
    hist = data["history"] if isinstance(data, dict) else data
    found = {}
    for ser in hist:
        if not ser:
            continue
        eid = str(ser[0].get("entity_id", ""))
        for key, label in EVENT_KEYS:
            if eid.endswith(key) and label not in found:
                found[label] = _sampler(_rows(ser), max_age=120.0)
    t0 = dt.datetime.fromisoformat(start).timestamp()
    t1 = dt.datetime.fromisoformat(end).timestamp()
    labels = [lab for _, lab in EVENT_KEYS if lab in found]
    print("UTC      | " + " | ".join(labels))
    t = t0
    while t <= t1:
        vals = []
        for lab in labels:
            v = found[lab](t)
            vals.append("-" if v is None else (f"{v:.2f}" if lab == "batt V" else f"{v:.0f}"))
        print(dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%H:%M:%S") + " | " + " | ".join(vals))
        t += 30


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "nights":
        nights(Path(sys.argv[2]), sys.argv[3:])
    elif len(sys.argv) == 5 and sys.argv[1] == "event":
        event(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(2)
