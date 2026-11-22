#!/usr/bin/env python3
"""Fit the inverter conversion of the live power balance from a recorded history (OFFLINE, stdlib only, read-only).

The live balance check (intelligence/quality.py, power_balance_verdict) expects house = PV + battery + grid. PV and battery
power are DC-side readings and the house power is the inverter's AC output plus the grid CT, so on a real inverter the
house power falls short of that sum by the conversion loss and the inverter's own draw. The check can allow for it through
three OPTIONAL site facts (site_decisions.InverterConversion): inverter_dc_to_ac_factor, inverter_ac_to_dc_factor and
inverter_standby_w, each bounded (factors 0.90 to 1.0, standby 0 to 100 W). This tool fits them from a history, so they
can be recalibrated for a site and a season. It reads files you name, prints a report and writes nothing, calls nothing and
needs no network or Home Assistant access. The values it prints are PROPOSED engineering parameters of one site, not owner
decisions: keep its output with the site's offline evidence, never in a repository.

    python intelligence/tools/power_balance_fit.py csv --file power.csv
    python intelligence/tools/power_balance_fit.py ha-history --house H.json [H2.json ...] --pv P.json ... \\
                                                   --battery B.json ... --grid G.json ... [--step-s 10]

INPUT FORMATS
  csv         one header row and one row per time-aligned sample: timestamp, house_w, pv_w, battery_w, grid_w. The timestamp
              is ISO 8601 WITH a time zone (a bare date-time is refused) or seconds since the epoch. Header names are
              case-insensitive and may come in any order; extra columns are ignored. Power is in watts; battery_w is
              positive while DISCHARGING and negative while charging; grid_w is positive while IMPORTING and negative while
              exporting (the engine's sign conventions). A row with a missing or non-numeric value is skipped and counted.
  ha-history  the Home Assistant history JSON: a list of series, each a list of objects with `state` and `last_changed`
              (the first object of a series also carries entity_id and attributes, which are ignored), one file per entity
              per period; give several files per role (they are joined in time order). Each series is held at its last
              value until it changes and read on a regular grid (--step-s, default 10) from the moment every series has
              started to the last change of any series (Home Assistant records only changes, so a value that stays the same is
              held, however long). A state that is not a finite number (unavailable, unknown) is a GAP: it is counted, the
              value before it is not held across it, and every grid point at which any series is in a gap is dropped (and
              counted).

WHAT IT PRINTS
  (a) the fitted parameters of the two sides (net DC-side power d = PV + battery: d >= 0 is the discharge / PV side, d < 0 the
      charge side) fitted separately, and jointly with one shared standby draw (the form the site facts take), with the
      proposed site facts rounded as they would be entered and whether they lie inside the bounds;
  (b) the share of samples the engine's rule accepts under the CURRENT lossless rule and under the loss-aware rule (the
      proposed facts, rounded), with the residual spread and the blocked codes;
  (c) a fault-injection table: the grid CT sign reversed and the battery sign reversed, on the samples where the reversal
      matters (the reversed reading is at least the tolerance), for the current rule, the loss-aware rule and the loss-aware
      rule at the most generous bounds; and, because a rule that blocks most samples anyway detects nothing, the same rates
      restricted to the samples the rule accepted before the fault;
  (d) a hold-out check: the parameters fitted on the first half of the days, judged on the second half.

The fit is ordinary least squares and assumes the history holds no sign fault (a reversed CT or battery sign would be fitted
as a loss, and a few such samples already bias it): fitted values outside the bounds are reported as not usable, and a
loss-aware share below 99 % of the fitting samples is reported as a warning to review the history (the residual tails are
printed) before the facts are used. All loops are bounded (--max-samples); a history larger than the bound is refused,
never silently cut.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import glob
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.quality import power_balance_verdict  # noqa: E402
from intelligence.site_decisions import (INVERTER_FACTOR_BOUNDS, INVERTER_STANDBY_BOUNDS_W, LOSSLESS_CONVERSION,  # noqa: E402
                                         InverterConversion)

TOOL_VERSION = "intel-power-balance-fit-0.1.0"
ROLES = ("house", "pv", "battery", "grid")
CSV_COLUMNS = ("timestamp", "house_w", "pv_w", "battery_w", "grid_w")
DEFAULT_STEP_S = 10.0
DEFAULT_MAX_SAMPLES = 5_000_000
DEFAULT_MIN_SIDE_SAMPLES = 200
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_FILES_PER_ROLE = 4000
CLEAN_SHARE_WARN = 0.99
# the most generous conversion the bounds allow: the lowest factors and the largest standby draw
STRESS = InverterConversion(INVERTER_FACTOR_BOUNDS[0], INVERTER_FACTOR_BOUNDS[0], INVERTER_STANDBY_BOUNDS_W[1])

Sample = tuple[float, float, float, float, float]       # (epoch seconds, house, pv, battery, grid)


class FitError(Exception):
    """The input cannot be fitted honestly (no usable rows, too large, too few samples on a side): nothing is invented."""


# ---------------------------------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------------------------------

def parse_time(text: object) -> float:
    """Epoch seconds from an ISO 8601 time with a zone, or from seconds since the epoch. A bare date-time is refused."""
    if isinstance(text, bool):
        raise ValueError("not a time")
    if isinstance(text, (int, float)):
        v = float(text)
        if not math.isfinite(v):
            raise ValueError("not a finite time")
        return v
    s = str(text).strip()
    try:
        v = float(s)
    except ValueError:
        v = None
    if v is not None:
        if not math.isfinite(v):
            raise ValueError("not a finite time")
        return v
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    d = datetime.fromisoformat(s)
    if d.tzinfo is None or d.tzinfo.utcoffset(d) is None:
        raise ValueError("a time without a time zone")
    return d.astimezone(timezone.utc).timestamp()


def _finite(text: object) -> float | None:
    try:
        v = float(text)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _check_file(path: Path) -> None:
    if not path.is_file():
        raise FitError(f"{path.name}: not a file")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise FitError(f"{path.name}: larger than the {MAX_FILE_BYTES // (1024 * 1024)} MiB bound")


def read_csv(path: Path, max_samples: int = DEFAULT_MAX_SAMPLES) -> tuple[list[Sample], dict]:
    """The samples of a generic CSV (time order) and the skip counts."""
    _check_file(path)
    out: list[Sample] = []
    skipped = 0
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd, None)
        if header is None:
            raise FitError(f"{path.name}: empty file")
        names = [h.strip().lower() for h in header]
        missing = [c for c in CSV_COLUMNS if c not in names]
        if missing:
            raise FitError(f"{path.name}: missing column(s) {', '.join(missing)} (expected {', '.join(CSV_COLUMNS)})")
        idx = [names.index(c) for c in CSV_COLUMNS]
        for row in rd:
            if len(out) + skipped >= max_samples:
                raise FitError(f"{path.name}: more than the {max_samples} rows bound")
            try:
                t = parse_time(row[idx[0]])
            except (ValueError, IndexError):
                skipped += 1
                continue
            vals = [_finite(row[i]) if i < len(row) else None for i in idx[1:]]
            if any(v is None for v in vals):
                skipped += 1
                continue
            out.append((t, vals[0], vals[1], vals[2], vals[3]))
    out.sort(key=lambda r: r[0])
    if not out:
        raise FitError(f"{path.name}: no usable row")
    return out, {"rows_read": len(out) + skipped, "rows_skipped": skipped}


def read_ha_series(path: Path, max_points: int = DEFAULT_MAX_SAMPLES) -> tuple[list[tuple[float, float | None]], int]:
    """(time, value) points of one Home Assistant history file (every series in it joined) and the count of states that are
    not a finite number (their value is None: a gap) or have no usable time (left out)."""
    _check_file(path)
    with open(path, encoding="utf-8-sig") as fh:
        try:
            raw = json.load(fh)
        except ValueError as exc:
            raise FitError(f"{path.name}: not valid JSON ({type(exc).__name__})") from None
    if not isinstance(raw, list):
        raise FitError(f"{path.name}: not a list of series")
    pts: list[tuple[float, float | None]] = []
    skipped = 0
    for series in raw:
        if not isinstance(series, list):
            raise FitError(f"{path.name}: a series is not a list of state objects")
        for obj in series:
            if not isinstance(obj, dict):
                raise FitError(f"{path.name}: a state record is not an object")
            if len(pts) + skipped >= max_points:
                raise FitError(f"{path.name}: more than the {max_points} points bound")
            v = _finite(obj.get("state"))
            try:
                t = parse_time(obj.get("last_changed") or obj.get("last_updated"))
            except (ValueError, TypeError):
                t = None
            if t is None:
                skipped += 1
                continue
            skipped += v is None
            pts.append((t, v))
    return pts, skipped


def expand(patterns: list[str]) -> list[Path]:
    """The files named by paths or glob patterns (sorted, de-duplicated, bounded)."""
    out: list[Path] = []
    for pat in patterns:
        hits = sorted(glob.glob(pat)) or [pat]
        out += [Path(h) for h in hits]
    uniq = sorted(dict.fromkeys(out))
    if len(uniq) > MAX_FILES_PER_ROLE:
        raise FitError(f"more than {MAX_FILES_PER_ROLE} files for one role")
    return uniq


def resample(series: dict[str, list[tuple[float, float | None]]], step_s: float,
             max_samples: int) -> tuple[list[Sample], int]:
    """(the samples, the grid points dropped): hold each series at its last value and read all four on a regular grid from the
    moment every series has started to the last change of any series. A value of None (a state that was not a number) is a
    gap: no value is held across it, and a grid point at which any series is in a gap is dropped."""
    if not (math.isfinite(step_s) and step_s > 0):
        raise FitError("the step must be a positive number of seconds")
    cols: dict[str, tuple[list[float], list[float | None]]] = {}
    for role in ROLES:
        pts = sorted(series.get(role, []), key=lambda p: p[0])
        if not any(p[1] is not None for p in pts):
            raise FitError(f"no numeric state for {role}")
        cols[role] = ([p[0] for p in pts], [p[1] for p in pts])
    t0 = max(cols[r][0][0] for r in ROLES)
    t1 = max(cols[r][0][-1] for r in ROLES)                    # never before t0: the latest-starting series ends at or after it
    n = int((t1 - t0) // step_s) + 1
    if n > max_samples:
        raise FitError(f"{n} grid points exceed the {max_samples} bound: raise --step-s or --max-samples")
    out: list[Sample] = []
    dropped = 0
    for i in range(n):
        t = t0 + i * step_s
        vals = []
        for role in ROLES:
            ts, vs = cols[role]
            vals.append(vs[bisect.bisect_right(ts, t) - 1])
        if any(v is None for v in vals):
            dropped += 1
            continue
        out.append((t, vals[0], vals[1], vals[2], vals[3]))
    if not out:
        raise FitError("no grid point has all four series present")
    return out, dropped


# ---------------------------------------------------------------------------------------------------------------------
# fitting
# ---------------------------------------------------------------------------------------------------------------------

def _solve3(m: list[list[float]], v: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting on a 3 x 3 system; FitError when it is singular."""
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    scale = max(abs(x) for row in m for x in row) or 1.0
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) <= 1e-12 * scale:
            raise FitError("the history does not vary enough to fit the conversion")
        a[col], a[piv] = a[piv], a[col]
        for r in range(col + 1, 3):
            f = a[r][col] / a[col][col]
            for c in range(col, 4):
                a[r][c] -= f * a[col][c]
    x = [0.0] * 3
    for r in (2, 1, 0):
        x[r] = (a[r][3] - sum(a[r][c] * x[c] for c in range(r + 1, 3))) / a[r][r]
    return x


def fit_side(samples: list[Sample]) -> dict:
    """Ordinary least squares of (house - grid) on the net DC-side power (PV + battery) for one side."""
    n = len(samples)
    if n < 2:
        raise FitError("too few samples on a side")
    sx = sy = sxx = sxy = 0.0
    for _t, h, p, b, g in samples:
        x, y = p + b, h - g
        sx += x
        sy += y
        sxx += x * x
        sxy += x * y
    den = n * sxx - sx * sx
    if abs(den) <= 1e-9 * max(1.0, n * sxx):
        raise FitError("the net DC-side power does not vary enough on a side to fit it")
    slope = (n * sxy - sx * sy) / den
    return {"n": n, "slope": slope, "intercept": (sy - slope * sx) / n}


def fit_joint(samples: list[Sample]) -> dict:
    """(house - grid) = a_pos x max(d, 0) + a_neg x min(d, 0) + c, with one shared constant c, by least squares."""
    m = [[0.0] * 3 for _ in range(3)]
    v = [0.0] * 3
    for _t, h, p, b, g in samples:
        d, y = p + b, h - g
        u = (d if d >= 0.0 else 0.0, d if d < 0.0 else 0.0, 1.0)
        for i in range(3):
            v[i] += u[i] * y
            for j in range(3):
                m[i][j] += u[i] * u[j]
    a_pos, a_neg, c = _solve3(m, v)
    return {"a_pos": a_pos, "a_neg": a_neg, "c": c}


def proposed_facts(joint: dict) -> dict:
    """The site facts the joint fit implies, rounded as they would be entered, and what is wrong with them (if anything)."""
    facts = {}
    problems = []
    if joint["a_pos"] > 0:
        facts["inverter_dc_to_ac_factor"] = round(joint["a_pos"], 3)
    else:
        problems.append("the discharge-side slope is not positive")
    if joint["a_neg"] > 0:
        facts["inverter_ac_to_dc_factor"] = round(1.0 / joint["a_neg"], 3)
    else:
        problems.append("the charge-side slope is not positive")
    facts["inverter_standby_w"] = round(-joint["c"])
    lo, hi = INVERTER_FACTOR_BOUNDS
    slo, shi = INVERTER_STANDBY_BOUNDS_W
    for k in ("inverter_dc_to_ac_factor", "inverter_ac_to_dc_factor"):
        if k in facts and not lo <= facts[k] <= hi:
            problems.append(f"{k} is outside {lo} to {hi}")
    if not slo <= facts["inverter_standby_w"] <= shi:
        problems.append(f"inverter_standby_w is outside {slo} to {shi}")
    return {"facts": facts, "problems": problems}


def conversion_from(facts: dict, problems: list[str]) -> InverterConversion | None:
    if problems or len(facts) != 3:
        return None
    return InverterConversion(facts["inverter_dc_to_ac_factor"], facts["inverter_ac_to_dc_factor"],
                              facts["inverter_standby_w"])


# ---------------------------------------------------------------------------------------------------------------------
# judging
# ---------------------------------------------------------------------------------------------------------------------

def percentile(sorted_xs: list[float], q: float) -> float:
    if not sorted_xs:
        return float("nan")
    k = (len(sorted_xs) - 1) * q
    lo = math.floor(k)
    hi = math.ceil(k)
    return sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (k - lo)


def judge(samples: list[Sample], conv: InverterConversion) -> dict:
    """The engine's verdict on every sample: counts per code and the residual percentiles."""
    counts: dict[str, int] = {}
    resid: list[float] = []
    for _t, h, p, b, g in samples:
        code, r, _tol = power_balance_verdict(h, p, b, g, conv)
        counts["OK" if code is None else code] = counts.get("OK" if code is None else code, 0) + 1
        resid.append(r)
    resid.sort()
    return {"n": len(samples), "counts": counts,
            "ok_share": counts.get("OK", 0) / len(samples) if samples else float("nan"),
            "resid": {q: percentile(resid, q) for q in (0.01, 0.05, 0.5, 0.95, 0.99)}}


def inject(samples: list[Sample], conv: InverterConversion, fault: str) -> dict:
    """Reverse the grid (ct) or the battery (batt) sign on every sample and count how many the engine blocks, among the
    samples where the reversal matters (the reversed reading is at least the sample's tolerance) and among those of them
    the rule accepted before the fault."""
    n = blocked = n_clean = blocked_clean = 0
    for _t, h, p, b, g in samples:
        x = g if fault == "ct" else b
        _code, _r, tol = power_balance_verdict(h, p, b, g, conv)
        if abs(x) < tol:
            continue
        clean = _code is None
        bad = power_balance_verdict(h, p, b, -g, conv)[0] if fault == "ct" else power_balance_verdict(h, p, -b, g, conv)[0]
        n += 1
        blocked += bad is not None
        if clean:
            n_clean += 1
            blocked_clean += bad is not None
    return {"n": n, "blocked": blocked, "n_clean": n_clean, "blocked_clean": blocked_clean}


def split_halves(samples: list[Sample]) -> tuple[list[Sample], list[Sample], str]:
    """The first and second half by UTC calendar day (two or more days), else by time (the middle sample)."""
    days = sorted({datetime.fromtimestamp(s[0], timezone.utc).date() for s in samples})
    if len(days) >= 2:
        cut = days[len(days) // 2]
        first = [s for s in samples if datetime.fromtimestamp(s[0], timezone.utc).date() < cut]
        second = [s for s in samples if datetime.fromtimestamp(s[0], timezone.utc).date() >= cut]
        return first, second, f"{len(days) // 2} of {len(days)} UTC days first, the rest second"
    mid = len(samples) // 2
    return samples[:mid], samples[mid:], "one UTC day: split at the middle sample"


# ---------------------------------------------------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------------------------------------------------

def _pct(x: float) -> str:
    return "n/a" if x != x else f"{100.0 * x:6.2f} %"


def _fault_row(label: str, r: dict) -> str:
    share = f"{_pct(r['blocked'] / r['n'])} ({r['blocked']}/{r['n']})" if r["n"] else "no sample where it matters"
    clean = (f"{_pct(r['blocked_clean'] / r['n_clean'])} ({r['blocked_clean']}/{r['n_clean']})" if r["n_clean"]
             else "no accepted sample where it matters")
    return f"    {label:<38} all: {share:<28} accepted before the fault: {clean}"


def report(samples: list[Sample], *, min_side: int, source_note: str) -> list[str]:
    out = [f"ECCO Intelligence power-balance fit ({TOOL_VERSION}); offline, read-only; PROPOSED site parameters, not owner "
           f"decisions; keep this output offline", source_note,
           f"samples      : {len(samples)}  from {datetime.fromtimestamp(samples[0][0], timezone.utc):%Y-%m-%d %H:%M} to "
           f"{datetime.fromtimestamp(samples[-1][0], timezone.utc):%Y-%m-%d %H:%M} UTC"]
    pos = [s for s in samples if s[2] + s[3] >= 0.0]
    neg = [s for s in samples if s[2] + s[3] < 0.0]
    out.append(f"sides        : {len(pos)} samples with PV + battery >= 0 (discharge / PV side), {len(neg)} below 0 (charge side)")
    out.append("")
    out.append("(a) FITTED PARAMETERS   (house - grid) = slope x (PV + battery) + intercept")
    for name, side in (("discharge / PV side", pos), ("charge side", neg)):
        if len(side) < min_side:
            out.append(f"    {name:<20}: {len(side)} samples, fewer than {min_side}: not fitted")
            continue
        try:
            f = fit_side(side)
            out.append(f"    {name:<20}: slope {f['slope']:.4f}  intercept {f['intercept']:+.1f} W  (n = {f['n']})")
        except FitError as exc:
            out.append(f"    {name:<20}: {exc}")
    joint = None
    conv: InverterConversion | None = None
    prop: dict = {"facts": {}, "problems": []}
    if len(pos) >= min_side and len(neg) >= min_side:
        try:
            joint = fit_joint(samples)
            prop = proposed_facts(joint)
            out.append(f"    joint fit (one shared standby): discharge slope {joint['a_pos']:.4f}, charge slope "
                       f"{joint['a_neg']:.4f}, constant {joint['c']:+.1f} W")
            out.append("    proposed site facts (the `site` block of the site file), rounded as entered:")
            out.append("      " + json.dumps(prop["facts"], sort_keys=True))
            conv = conversion_from(prop["facts"], prop["problems"])
            if conv is None:
                out.append("    NOT USABLE as site facts: " + "; ".join(prop["problems"]))
        except FitError as exc:
            out.append(f"    joint fit: {exc}")
    else:
        out.append(f"    joint fit: needs at least {min_side} samples on each side; no site facts are proposed")
    out.append("")
    cur = judge(samples, LOSSLESS_CONVERSION)
    out.append("(b) SHARE OF SAMPLES THE ENGINE ACCEPTS")
    out.append(f"    current rule (lossless)            : {_pct(cur['ok_share'])}   blocked codes: "
               + ", ".join(f"{k} {v}" for k, v in sorted(cur["counts"].items()) if k != "OK"))
    la = None
    if conv is not None:
        la = judge(samples, conv)
        r = la["resid"]
        out.append(f"    loss-aware rule (proposed facts)   : {_pct(la['ok_share'])}   blocked codes: "
                   + (", ".join(f"{k} {v}" for k, v in sorted(la["counts"].items()) if k != "OK") or "none")
                   + f"   residual p1/p5/p50/p95/p99 [W]: " + " / ".join(f"{r[q]:+.0f}" for q in (0.01, 0.05, 0.5, 0.95, 0.99)))
        if la["ok_share"] < CLEAN_SHARE_WARN:
            out.append(f"    WARNING: the loss-aware rule accepts under {int(CLEAN_SHARE_WARN * 100)} % of the fitting samples: the "
                       "history probably holds a sign fault, a mixed regime or a reading problem: review it before using these facts")
    else:
        out.append("    loss-aware rule                    : not evaluated (no usable proposed facts)")
    out.append("")
    out.append("(c) FAULT INJECTION   (reverse one sign on every sample; a block is a detection)")
    out.append("    (the bounds row uses the most generous values the bounds allow, not a fit: it shows what the bounds alone could hide)")
    rules = [("current rule (lossless)", LOSSLESS_CONVERSION)]
    if conv is not None:
        rules.append(("loss-aware rule (proposed facts)", conv))
    rules.append(("loss-aware at the bounds (not a fit)", STRESS))
    for fault, title in (("ct", "grid CT sign reversed"), ("batt", "battery sign reversed")):
        out.append(f"  {title}:")
        for label, c in rules:
            out.append(_fault_row(label, inject(samples, c, fault)))
    out.append("")
    out.append("(d) HOLD-OUT   (parameters fitted on the first part, judged on the second)")
    first, second, how = split_halves(samples)
    out.append(f"    split: {how}; first {len(first)} samples, second {len(second)} samples")
    try:
        if min(len(s) for s in (first, second)) < 2 * min_side:
            raise FitError("a half holds too few samples to fit and judge")
        fpos = sum(1 for s in first if s[2] + s[3] >= 0.0)
        if fpos < min_side or len(first) - fpos < min_side:
            raise FitError(f"the first part holds fewer than {min_side} samples on one side")
        j1 = fit_joint(first)
        p1 = proposed_facts(j1)
        c1 = conversion_from(p1["facts"], p1["problems"])
        out.append("    facts fitted on the first part: " + json.dumps(p1["facts"], sort_keys=True))
        if c1 is None:
            out.append("    NOT USABLE as site facts: " + "; ".join(p1["problems"]))
        else:
            cur2 = judge(second, LOSSLESS_CONVERSION)
            la2 = judge(second, c1)
            out.append(f"    second part, current rule  : {_pct(cur2['ok_share'])} accepted")
            out.append(f"    second part, loss-aware    : {_pct(la2['ok_share'])} accepted"
                       + "   blocked codes: " + (", ".join(f"{k} {v}" for k, v in sorted(la2["counts"].items()) if k != "OK") or "none"))
            for fault, title in (("ct", "CT sign reversed"), ("batt", "battery sign reversed")):
                r = inject(second, c1, fault)
                out.append(f"    second part, {title:<22}: " + (f"{_pct(r['blocked'] / r['n'])} blocked ({r['blocked']}/{r['n']})"
                                                                if r["n"] else "no sample where it matters"))
    except FitError as exc:
        out.append(f"    not run: {exc}")
    return out


# ---------------------------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fit the inverter conversion of the power balance from a recorded history.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("csv", help="a time-aligned CSV: timestamp, house_w, pv_w, battery_w, grid_w")
    c.add_argument("--file", required=True)
    h = sub.add_parser("ha-history", help="Home Assistant history JSON, one file per entity per period")
    for role in ROLES:
        h.add_argument(f"--{role}", nargs="+", required=True, metavar="FILE", help=f"history file(s) of the {role} power")
    h.add_argument("--step-s", type=float, default=DEFAULT_STEP_S, help="grid step in seconds (default 10)")
    for p in (c, h):
        p.add_argument("--min-side-samples", type=int, default=DEFAULT_MIN_SIDE_SAMPLES,
                       help="samples needed on each side to fit it (default 200)")
        p.add_argument("--max-samples", type=int, default=DEFAULT_MAX_SAMPLES, help="hard bound on rows / grid points")
    a = ap.parse_args(argv)
    try:
        if a.min_side_samples < 3 or a.max_samples < 10:
            raise FitError("--min-side-samples must be at least 3 and --max-samples at least 10")
        if a.cmd == "csv":
            samples, info = read_csv(Path(a.file), a.max_samples)
            note = f"source       : csv, {info['rows_read']} rows read, {info['rows_skipped']} skipped"
        else:
            series: dict[str, list[tuple[float, float | None]]] = {}
            skipped = files = 0
            for role in ROLES:
                pts: list[tuple[float, float | None]] = []
                for path in expand(getattr(a, role)):
                    p, s = read_ha_series(path, a.max_samples)
                    pts += p
                    skipped += s
                    files += 1
                series[role] = pts
            samples, dropped = resample(series, a.step_s, a.max_samples)
            note = (f"source       : home assistant history, {files} files, {sum(len(v) for v in series.values())} points, "
                    f"{skipped} gap or unusable states, held on a {a.step_s:g} s grid, {dropped} grid points dropped (a gap)")
        print("\n".join(report(samples, min_side=a.min_side_samples, source_note=note)))
        return 0
    except FitError as exc:
        print(f"power_balance_fit: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
