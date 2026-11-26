#!/usr/bin/env python3
"""Offline REPLAY of the read-only Gentle rate advice against recorded nights (no Home Assistant, no network, no write to anything but --output).

For every cheap-window night found in a folder of recorded Home Assistant history files it prints, side by side, what the battery actually did (start
and end SOC, power profile, how early the target was reached, the top-of-charge tail) and what the advice (frontend/ecco-plan-core/src/gentleAdvice.ts,
the one implementation, run by Node through frontend/ecco-plan-core/tools/adviseBatch.ts) would have recommended: at the window start, and re-planned
every few minutes on the SOC the battery really had. It also prints a what-if: the time the night's own battery would have needed at the advised rate,
estimated from the energy it took per SOC point on that night.

Input: a folder with files named  hist-<kind>-YYYY-MM-DD.json  in the Home Assistant history JSON shape (a list of series, each a list of objects with
"state" and "last_changed"). Kinds: soc, batt (required); house, pv, grid, maxgrid, batcap (optional). Nothing about any site is built in: the entity
names inside the files are never read, and every number is an argument or comes from the files.

    python tools/gentle_replay_run.py EVIDENCE_DIR [--window 00:30-05:30] [--target auto|N] [--buffer-min 60] [--calibrate loo]
                                                   [--ceiling NAME=WATTS[:BASIS]] [--param NAME=VALUE] [--output FILE]

This module itself starts no process (the authority-separation gate of the Intelligence tools forbids it): it reads the recordings, builds the questions for
the advice (--emit-cases prints them as JSON) and reads the answers (--results FILE, the output of adviseBatch.ts). tools/gentle_replay_run.py is the
one-command driver that runs Node in between. By hand:
    python intelligence/tools/gentle_replay.py EVIDENCE_DIR --emit-cases > cases.json
    node frontend/ecco-plan-core/tools/adviseBatch.ts < cases.json > results.json
    python intelligence/tools/gentle_replay.py EVIDENCE_DIR --results results.json
(every other option must be the same in the first and the last command).

What it is not: the advice is a model, not a command, and nothing is applied. A recorded night has only the charge profile the battery was really given
(usually one fixed rate), so "what would have happened at a lower rate" is an ESTIMATE from that night's energy per SOC point, not a measurement. A state
history holds changes only, so the age of a reading that has not changed is unknown: by default every reading is treated as fresh (--soc-age since-change
treats the time since the last change as its age, which is harsher than the truth). Ordinary days only: a night that crosses a clock change is not handled.
Needs Python 3.10+ (standard library only) and, for the advice itself, Node 22.18 or newer (run by the driver).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from bisect import bisect_left, bisect_right
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / "frontend" / "ecco-plan-core" / "tools" / "adviseBatch.ts"
KINDS_REQUIRED = ("soc", "batt")
KINDS_OPTIONAL = ("house", "pv", "grid", "maxgrid", "batcap")
FILE_RE = re.compile(r"^hist-(?P<kind>[a-z]+)-(?P<day>\d{4}-\d{2}-\d{2})\.json$")
BAD_STATES = {"unavailable", "unknown", "none", ""}
GRID_S = 300  # window edges are rounded to the owner's 5-minute grid
ORDINARY_DAY = {"changeAtMin": 0, "deltaMin": 0}
NOT_A_COMMAND = "model, not a command"


class ToolError(Exception):
    """A problem with the arguments or the recorded files: reported, never guessed around."""


# ----------------------------------------------------------------------------------------------------------------------------------------
# recorded series
# ----------------------------------------------------------------------------------------------------------------------------------------

def parse_ts(text: str) -> float:
    """An ISO time stamp WITH a zone as epoch seconds. A time without a zone is refused (it would be a guess)."""
    s = str(text).strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ToolError(f"not a time stamp: {text!r}") from exc
    if dt.tzinfo is None:
        raise ToolError(f"time stamp without a zone: {text!r}")
    return dt.timestamp()


def load_history(path: Path) -> tuple[list[tuple[float, float]], int]:
    """(points, skipped): the numeric states of one history file as (epoch seconds, value). unavailable / unknown / not a number are skipped and counted."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot read {Path(path).name}: {exc}") from exc
    if not isinstance(data, list) or not all(isinstance(s, list) for s in data):
        raise ToolError(f"{Path(path).name}: not a Home Assistant history file (a list of series was expected)")
    points: list[tuple[float, float]] = []
    skipped = 0
    for series in data:
        for row in series:
            if not isinstance(row, dict) or "state" not in row or not (row.get("last_changed") or row.get("last_updated")):
                raise ToolError(f"{Path(path).name}: a row has no state or no time")
            state = str(row["state"]).strip()
            if state.lower() in BAD_STATES:
                skipped += 1
                continue
            try:
                value = float(state)
            except ValueError:
                skipped += 1
                continue
            if not math.isfinite(value):
                skipped += 1
                continue
            points.append((parse_ts(row.get("last_changed") or row["last_updated"]), value))
    return points, skipped


class Series:
    """A step-hold series: a value holds from its time until the next sample."""

    def __init__(self, points: list[tuple[float, float]]):
        self.points = sorted(set(points))
        self.t = [p[0] for p in self.points]
        self.v = [p[1] for p in self.points]

    def __len__(self) -> int:
        return len(self.points)

    def index_at(self, t: float) -> int:
        return bisect_right(self.t, t) - 1

    def at(self, t: float) -> float | None:
        i = self.index_at(t)
        return self.v[i] if i >= 0 else None

    def last_change(self, t: float) -> float | None:
        i = self.index_at(t)
        return self.t[i] if i >= 0 else None

    def between(self, t0: float, t1: float) -> list[tuple[float, float]]:
        return self.points[bisect_left(self.t, t0):bisect_right(self.t, t1)]

    def integral(self, t0: float, t1: float, f: Callable[[float], float] = lambda x: x) -> float:
        """Integral of f(value) dt over [t0, t1] in value-seconds; the part before the first sample counts as 0."""
        if t1 <= t0 or not self.points:
            return 0.0
        total = 0.0
        n = len(self.t)
        i = max(self.index_at(t0), 0)
        while i < n:
            seg0 = max(self.t[i], t0)
            seg1 = min(self.t[i + 1] if i + 1 < n else t1, t1)
            if seg0 >= t1:
                break
            if seg1 > seg0:
                total += f(self.v[i]) * (seg1 - seg0)
            i += 1
        return total


def discover(folder: Path) -> dict[str, list[Path]]:
    """The history files by kind, oldest day first."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ToolError(f"not a folder: {folder}")
    found: dict[str, list[tuple[str, Path]]] = {}
    for p in sorted(folder.iterdir()):
        m = FILE_RE.match(p.name)
        if m and (m["kind"] in KINDS_REQUIRED or m["kind"] in KINDS_OPTIONAL):
            found.setdefault(m["kind"], []).append((m["day"], p))
    for kind in KINDS_REQUIRED:
        if kind not in found:
            raise ToolError(f"no hist-{kind}-YYYY-MM-DD.json file in {folder}")
    return {k: [p for _, p in sorted(v)] for k, v in found.items()}


def load_all(folder: Path) -> tuple[dict[str, Series], dict[str, int]]:
    files = discover(folder)
    series: dict[str, Series] = {}
    skipped: dict[str, int] = {}
    for kind, paths in files.items():
        pts: list[tuple[float, float]] = []
        n = 0
        for p in paths:
            got, bad = load_history(p)
            pts.extend(got)
            n += bad
        series[kind] = Series(pts)
        skipped[kind] = n
    return series, skipped


# ----------------------------------------------------------------------------------------------------------------------------------------
# nights: sessions, windows
# ----------------------------------------------------------------------------------------------------------------------------------------

def charge_w(value: float, sign: str) -> float:
    """Battery power as a CHARGE power: positive while charging. `sign` says which sign of the recorded value means charging."""
    return -value if sign == "negative" else value


def find_sessions(batt: Series, sign: str, min_w: float = 1000.0, max_gap_s: float = 600.0, min_len_s: float = 1800.0) -> list[tuple[float, float]]:
    """Runs of charging at or above min_w: (start, end). A gap between two such samples above max_gap_s splits a run; a run under min_len_s is dropped."""
    high = [i for i in range(len(batt)) if charge_w(batt.v[i], sign) >= min_w]
    runs: list[list[int]] = []
    for i in high:
        if runs and batt.t[i] - batt.t[runs[-1][-1]] <= max_gap_s:
            runs[-1].append(i)
        else:
            runs.append([i])
    out = []
    for r in runs:
        start = batt.t[r[0]]
        end = batt.t[r[-1] + 1] if r[-1] + 1 < len(batt) else batt.t[r[-1]]
        if end - start >= min_len_s:
            out.append((start, end))
    return out


def is_grid_charge(session: tuple[float, float], batt: Series, grid: Series | None, sign: str) -> bool:
    """A cheap-window charge is fed from the grid: the grid import over the run is at least half of the charge power. Without a grid series: assumed."""
    if grid is None or len(grid) == 0:
        return True
    start, end = session
    charge = batt.integral(start, end, lambda v: max(charge_w(v, sign), 0.0))
    imported = grid.integral(start, end, lambda v: max(v, 0.0))
    return charge > 0 and imported >= 0.5 * charge


def round_grid(t: float, mode: str = "nearest") -> float:
    k = t / GRID_S
    return {"floor": math.floor(k), "nearest": round(k), "ceil": math.ceil(k)}[mode] * GRID_S


def detect_window_end(after: float, batt: Series, grid: Series | None, sign: str, grid_idle_w: float = 100.0, discharge_w: float = 200.0,
                      hold_s: float = 60.0, horizon_s: float = 12 * 3600.0) -> float | None:
    """The first instant after `after` at which the battery supplies the house (it discharges at least discharge_w) while the grid import is idle
    (under grid_idle_w), and stays so for hold_s: the end of the cheap window. None when there is none within the horizon."""
    def supplying(t: float, v: float) -> bool:
        return -charge_w(v, sign) >= discharge_w and (grid is None or (grid.at(t) is not None and grid.at(t) < grid_idle_w))
    pts = batt.between(after, after + horizon_s)
    for k, (t, v) in enumerate(pts):
        if not supplying(t, v):
            continue
        if all(supplying(t2, v2) for t2, v2 in pts[k:] if t2 <= t + hold_s):
            return t
    return None


def parse_window(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", str(text).strip())
    if not m:
        raise ToolError(f"--window must be HH:MM-HH:MM, got {text!r}")
    a, b, c, d = (int(x) for x in m.groups())
    if a > 23 or c > 23 or b > 59 or d > 59:
        raise ToolError(f"--window out of range: {text!r}")
    s, e = a * 60 + b, c * 60 + d
    if s == e:
        raise ToolError("--window has no length")
    return s, e


class Night:
    """One cheap-window night: real window start and end (epoch seconds) and the charge run it contains."""

    def __init__(self, start: float, end: float, session: tuple[float, float], how: str):
        self.start, self.end, self.session, self.how = start, end, session, how

    @property
    def length_min(self) -> float:
        return (self.end - self.start) / 60.0


def local_minute(t: float, tz_min: int) -> int:
    dt = datetime.fromtimestamp(t + tz_min * 60, tz=timezone.utc)
    return dt.hour * 60 + dt.minute


def fmt_local(t: float, tz_min: int) -> str:
    return datetime.fromtimestamp(t + tz_min * 60, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def fmt_hm(t: float, tz_min: int) -> str:
    return datetime.fromtimestamp(t + tz_min * 60, tz=timezone.utc).strftime("%H:%M")


def find_nights(s: dict[str, Series], args: argparse.Namespace) -> tuple[list[Night], list[str]]:
    """The cheap-window nights in the data and a note for every charge run that could not be turned into one (never silently dropped)."""
    batt, grid = s["batt"], s.get("grid")
    sessions = [x for x in find_sessions(batt, args.charge_sign, args.session_min_w) if is_grid_charge(x, batt, grid, args.charge_sign)]
    notes: list[str] = []
    nights: list[Night] = []
    explicit = parse_window(args.window) if args.window else None
    for ses in sessions:
        if nights and ses[0] < nights[-1].end:
            continue  # the same window (a gap in the data split the charge run)
        if explicit is not None:
            s_min, e_min = explicit
            day0 = datetime.fromtimestamp(ses[0] + args.tz_offset_min * 60, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            cand = day0.timestamp() - args.tz_offset_min * 60 + s_min * 60
            if cand > ses[0] + 600:
                cand -= 86400
            span = ((e_min - s_min) % 1440) * 60
            night = Night(cand, cand + span, ses, "explicit window")
            if not (night.start - 600 <= ses[0] < night.end):
                notes.append(f"charge run at {fmt_local(ses[0], args.tz_offset_min)} is outside the window {args.window}: skipped")
                continue
            nights.append(night)
            continue
        end = detect_window_end(ses[1], batt, grid, args.charge_sign)
        if end is None:
            notes.append(f"charge run at {fmt_local(ses[0], args.tz_offset_min)}: no window end found (the battery never took over from the grid in the data): pass --window")
            continue
        nights.append(Night(round_grid(ses[0], "floor"), round_grid(end, "nearest"), ses, "detected"))
    return nights, notes


# ----------------------------------------------------------------------------------------------------------------------------------------
# what the battery actually did
# ----------------------------------------------------------------------------------------------------------------------------------------

class Actual:
    """The measured side of one night. Every field is None when the data cannot say."""

    def __init__(self) -> None:
        self.soc_start: float | None = None
        self.soc_end: float | None = None
        self.target: float | None = None
        self.reach_min: float | None = None
        self.deadline_min: float | None = None
        self.early_vs_deadline_min: float | None = None
        self.early_vs_end_min: float | None = None
        self.typical_w: float | None = None
        self.peak_w: float | None = None
        self.energy_kwh: float | None = None
        self.grid_peak_w: float | None = None
        self.tail_min: float | None = None
        self.tail_w: float | None = None
        self.kwh_per_pct: float | None = None
        self.implied_eff: float | None = None
        self.taper_start: float | None = None
        self.main_end_soc: float | None = None
        self.main_end_min: float | None = None
        self.capacity_kwh: float | None = None
        self.ceiling_w: float | None = None
        self.notes: list[str] = []


def median(xs: list[float]) -> float:
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def measure(night: Night, s: dict[str, Series], args: argparse.Namespace) -> Actual:
    a = Actual()
    soc, batt, grid = s["soc"], s["batt"], s.get("grid")
    ws, we = night.start, night.end
    a.soc_start = soc.at(ws)
    a.soc_end = soc.at(we)
    a.capacity_kwh = args.capacity_kwh if args.capacity_kwh is not None else (s["batcap"].at(ws) if "batcap" in s else None)
    a.ceiling_w = s["maxgrid"].at(ws) if "maxgrid" in s else None
    if a.soc_start is None:
        a.notes.append("no SOC reading at or before the window start")
        return a
    inside = soc.between(ws, we)
    if args.target == "auto":
        a.target = float(round(max([a.soc_start] + [v for _, v in inside])))
    else:
        a.target = float(args.target)
    a.deadline_min = night.length_min - args.buffer_min
    for t, v in inside:
        if v >= a.target - 1e-9:
            a.reach_min = (t - ws) / 60.0
            break
    if a.soc_start >= a.target:
        a.reach_min = 0.0
    if a.reach_min is not None:
        a.early_vs_deadline_min = a.deadline_min - a.reach_min
        a.early_vs_end_min = night.length_min - a.reach_min
    cw = [charge_w(v, args.charge_sign) for _, v in batt.between(ws, we)]
    hi = [w for w in cw if w >= args.session_min_w]
    if hi:
        a.typical_w = median(hi)
        a.peak_w = max(hi)
    a.energy_kwh = batt.integral(ws, we, lambda v: max(charge_w(v, args.charge_sign), 0.0)) / 3.6e6
    if grid is not None:
        end_g = ws + (a.reach_min * 60.0 if a.reach_min is not None else (we - ws))
        gs = [v for _, v in grid.between(ws, end_g)]
        a.grid_peak_w = max(gs) if gs else None
    # the top-of-charge tail: from the first reading at the target until the charge power stays under tail_end_w
    if a.reach_min is not None and a.target >= 100 - 1e-9:
        t0 = ws + a.reach_min * 60.0
        stop = None
        pts = batt.between(t0, we)
        for k, (t, v) in enumerate(pts):
            if charge_w(v, args.charge_sign) < args.tail_end_w and all(charge_w(v2, args.charge_sign) < args.tail_end_w for t2, v2 in pts[k:] if t2 <= t + 300):
                stop = t
                break
        a.tail_min = ((stop if stop is not None else we) - t0) / 60.0
        energy = batt.integral(t0, stop if stop is not None else we, lambda v: max(charge_w(v, args.charge_sign), 0.0))
        a.tail_w = energy / max(a.tail_min * 60.0, 1.0)
    elif a.reach_min is not None:
        a.tail_min = 0.0
    # energy per SOC point on the main phase (the start to one point below the target; the last point is integer-resolution noise)
    main_target = a.target - 1.0 if a.target - 1.0 > a.soc_start + 3.0 else a.target
    t_main = next((t for t, v in inside if v >= main_target - 1e-9), None)
    if t_main is not None and main_target > a.soc_start:
        a.main_end_soc = soc.at(t_main)
        a.main_end_min = (t_main - ws) / 60.0
        delta = (a.main_end_soc or 0.0) - a.soc_start
        if delta >= 3.0:
            e = batt.integral(ws, t_main, lambda v: max(charge_w(v, args.charge_sign), 0.0)) / 3.6e6
            a.kwh_per_pct = e / delta
            if a.capacity_kwh:
                a.implied_eff = (a.capacity_kwh / 100.0) / a.kwh_per_pct
        # where did the charge power start to fall? the first SOC point whose mean power is under 90 % of the typical one
        if a.typical_w:
            upto = ws + a.reach_min * 60.0 if a.reach_min is not None else we
            levels = [(t, v) for t, v in inside if t <= upto and v > a.soc_start]
            a.taper_start = a.target
            for k in range(len(levels) - 1):
                (t0_, v0_), (t1_, v1_) = levels[k], levels[k + 1]
                if t1_ - t0_ < 20:
                    continue
                mean = batt.integral(t0_, t1_, lambda v: max(charge_w(v, args.charge_sign), 0.0)) / (t1_ - t0_)
                if mean < 0.9 * a.typical_w and v0_ < a.target:
                    a.taper_start = v0_
                    break
    return a


# ----------------------------------------------------------------------------------------------------------------------------------------
# the advice, per night and per tick
# ----------------------------------------------------------------------------------------------------------------------------------------

def parse_ceiling(text: str) -> dict:
    m = re.fullmatch(r"([A-Za-z0-9_]+)=([0-9]+(?:\.[0-9]+)?)(?::(GRID_AC|BATTERY_DC))?", text.strip())
    if not m:
        raise ToolError(f"--ceiling must be NAME=WATTS or NAME=WATTS:GRID_AC|BATTERY_DC, got {text!r}")
    c: dict = {"name": m.group(1), "watts": float(m.group(2))}
    if m.group(3):
        c["basis"] = m.group(3)
    return c


def parse_params(items: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for item in items or []:
        m = re.fullmatch(r"([A-Za-z]+)=(-?[0-9]+(?:\.[0-9]+)?)", item.strip())
        if not m:
            raise ToolError(f"--param must be NAME=NUMBER, got {item!r}")
        out[m.group(1)] = float(m.group(2))
    return out


def base_input(night: Night, a: Actual, s: dict[str, Series], args: argparse.Namespace, params: dict[str, float]) -> dict:
    """The advice input for a night, without the reading: the window, the target, the buffer, the capacity, the ceilings, the policy."""
    cap = args.capacity_kwh if args.capacity_kwh is not None else (s["batcap"].at(night.start) if "batcap" in s else None)
    if not cap or cap <= 0:
        raise ToolError("no battery capacity: give --capacity-kwh or a hist-batcap-YYYY-MM-DD.json file")
    ceilings = [parse_ceiling(c) for c in args.ceiling or []]
    if not ceilings and a.ceiling_w is not None:
        c = {"name": "max_grid_charge_power", "watts": a.ceiling_w}
        if args.ceiling_basis != "NONE":
            c["basis"] = args.ceiling_basis
        ceilings.append(c)
    inp: dict = {
        "targetSocPct": a.target, "bufferMin": args.buffer_min,
        "chargeWindow": {"startMin": local_minute(night.start, args.tz_offset_min), "endMin": local_minute(night.end, args.tz_offset_min), "clockDay": dict(ORDINARY_DAY)},
        "capacityKwh": cap, "capacityUpPct": args.capacity_band_pct, "ceilings": ceilings,
        "policy": {"setpointBasis": args.setpoint_basis, "unknownDemandPolicy": args.unknown_demand_policy},
    }
    if params:
        inp["params"] = dict(params)
    return inp


def tick_input(inp: dict, night: Night, s: dict[str, Series], args: argparse.Namespace, elapsed_min: float, prev: tuple[float, float] | None) -> dict:
    """The advice input at a tick: the SOC the battery really had then (None when there was no reading yet), and, with a known grid limit, the house."""
    t = night.start + elapsed_min * 60.0
    soc = s["soc"]
    reading = soc.at(t)
    out = dict(inp)
    out["elapsedMin"] = elapsed_min
    out["socPct"] = reading
    if reading is None:
        out["socAgeMin"] = None
    elif args.soc_age == "fresh":
        out["socAgeMin"] = 0
    else:
        out["socAgeMin"] = (t - (soc.last_change(t) or t)) / 60.0
    if prev is not None:
        out["previousSoc"] = {"socPct": prev[0], "elapsedMin": prev[1]}
    if args.grid_limit_w is not None:
        house = s.get("house")
        demand = house.at(t) if house is not None else None
        hh: dict = {"gridImportLimitW": args.grid_limit_w}
        if demand is not None:
            hh.update({"demandNowW": max(demand, 0.0), "demandAgeMin": 0, "demandProfile": [{"fromInMin": 0, "watts": max(demand, 0.0)}], "demandProfileAgeMin": 0})
        pv = s.get("pv")
        if pv is not None and pv.at(t) is not None:
            hh.update({"solarNowW": max(pv.at(t), 0.0), "solarAgeMin": 0})
        out["household"] = hh
    return out


def calibrate(actuals: list[Actual]) -> tuple[dict[str, float], list[str]]:
    """Parameters read off other recorded nights, the CAUTIOUS value of each: the earliest taper start, the longest top-of-charge tail, the lowest efficiency.
    A value no night can give is left out (the model's default stays)."""
    params: dict[str, float] = {}
    notes: list[str] = []
    tapers = [a.taper_start for a in actuals if a.taper_start is not None and a.target is not None]
    if tapers:
        params["taperStartSocPct"] = float(max(0, min(99, math.floor(min(tapers)))))
        notes.append(f"taperStartSocPct from the earliest observed fall of the charge power ({params['taperStartSocPct']:.0f})")
    tails = [a.tail_min for a in actuals if a.tail_min is not None and a.target is not None and a.target >= 100]
    if tails:
        params["topHoldMin"] = float(min(120, math.ceil(max(tails) / 5.0) * 5))
        notes.append(f"topHoldMin from the longest observed tail after the target reading ({params['topHoldMin']:.0f})")
    effs = [a.implied_eff for a in actuals if a.implied_eff is not None]
    if effs:
        params["chargeEff"] = max(0.5, min(1.0, math.floor(min(effs) * 100) / 100))
        notes.append(f"chargeEff from the lowest observed stored-to-delivered ratio on the nominal capacity, capped at 1 ({params['chargeEff']:.2f})")
    return params, notes


Backend = Callable[[list[dict]], list[dict]]


def results_backend(path: Path) -> Backend:
    """The answers of the advice read from a file: the output of frontend/ecco-plan-core/tools/adviseBatch.ts for the cases of --emit-cases. Every case must be
    answered exactly once and none may have failed: a missing or failed answer is an error, never a guess."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        answers = doc["results"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ToolError(f"cannot read the advice results from {path}: {exc}") from exc
    if not isinstance(answers, list) or not all(isinstance(a, dict) and "id" in a for a in answers):
        raise ToolError(f"{path}: the results must be a list of answers with an id")
    by_id = {a["id"]: a for a in answers}
    if len(by_id) != len(answers):
        raise ToolError(f"{path}: an answer id occurs twice")

    def run(cases: list[dict]) -> list[dict]:
        out = []
        for c in cases:
            a = by_id.get(c["id"])
            if a is None:
                raise ToolError(f"{path}: no answer for case {c['id']} (the options of the two runs must be the same)")
            if "error" in a:
                raise ToolError(f"{path}: the advice failed on case {c['id']}: {a['error']}")
            out.append(a)
        if len(by_id) != len(cases):
            raise ToolError(f"{path}: {len(by_id)} answers for {len(cases)} cases (the options of the two runs must be the same)")
        return out

    return run


class NightResult:
    def __init__(self, night: Night, actual: Actual):
        self.night = night
        self.actual = actual
        self.variants: dict[str, dict] = {}   # variant name -> {"start": advice dict, "ticks": [(elapsed, advice dict)], "params": {...}, "whatif": {...}}


def whatif(actual: Actual, rate_w: float | None, length_min: float, buffer_min: float) -> dict | None:
    """What the night's own battery would have needed at a constant advised rate: the energy per SOC point it took that night, divided by the rate, then the
    last SOC point at the same rate and the observed tail. An ESTIMATE: the response of the battery at a lower rate was not recorded."""
    if rate_w is None or rate_w <= 0 or actual.kwh_per_pct is None or actual.soc_start is None or actual.target is None or actual.main_end_soc is None:
        return None
    main_pct = actual.main_end_soc - actual.soc_start
    kw = rate_w / 1000.0
    main_min = main_pct * actual.kwh_per_pct / kw * 60.0
    top_min = max(actual.target - actual.main_end_soc, 0.0) * actual.kwh_per_pct / kw * 60.0 + (actual.tail_min or 0.0)
    finish = main_min + top_min
    deadline = length_min - buffer_min
    return {"finish_min": finish, "deadline_min": deadline, "margin_min": deadline - finish}


def advice_row(adv: dict) -> tuple[str, str, str]:
    kind = {"RATE": "rate", "BEST_EFFORT": "best effort", "NOTHING_TO_CHARGE": "at target", "NO_ADVICE": "NO ADVICE"}[adv["advice"]]
    rate = "-" if adv["rateW"] is None else f"{adv['rateW']:.0f}"
    return kind, adv["reason"], rate


def plan_variants(nights: list[tuple[Night, Actual]], s: dict[str, Series], args: argparse.Namespace) -> tuple[list[NightResult], list[dict], list[tuple[int, str, float]]]:
    """The questions for the advice: every night, variant and tick, with the bookkeeping to put the answers back."""
    results = [NightResult(n, a) for n, a in nights]
    base_params = parse_params(args.param)
    variants: list[tuple[str, dict[int, tuple[dict[str, float], list[str]]]]] = [("shipped", {i: (dict(base_params), []) for i in range(len(results))})]
    if args.calibrate != "none":
        cal: dict[int, tuple[dict[str, float], list[str]]] = {}
        for i, r in enumerate(results):
            pool = [x.actual for j, x in enumerate(results) if (args.calibrate == "all" or j != i)]
            p, notes = calibrate(pool)
            merged = dict(p)
            merged.update(base_params)   # a parameter the caller sets always wins
            cal[i] = (merged, notes)
        variants.append(("calibrated", cal))
    cases: list[dict] = []
    index: list[tuple[int, str, float]] = []
    for name, per_night in variants:
        for i, r in enumerate(results):
            a = r.actual
            if a.soc_start is None or a.target is None:
                continue
            params = per_night[i][0]
            inp = base_input(r.night, a, s, args, params)
            r.variants.setdefault(name, {})["params"] = params
            r.variants[name]["notes"] = per_night[i][1]
            prev = None
            n_ticks = int(math.ceil(r.night.length_min / args.tick_min))   # the ticks inside the window: 0, tick, 2 x tick, ... below its length
            for k in range(n_ticks):
                el = k * args.tick_min
                ti = tick_input(inp, r.night, s, args, el, prev)
                # the id carries a hash of the question itself: answers computed for other options can never be matched to these questions
                cid = f"{name}/{i}/{k}/" + hashlib.sha256(json.dumps(ti, sort_keys=True).encode("utf-8")).hexdigest()[:12]
                cases.append({"id": cid, "input": ti})
                index.append((i, name, el))
                if ti["socPct"] is not None:
                    prev = (ti["socPct"], el)
    return results, cases, index


def apply_answers(results: list[NightResult], index: list[tuple[int, str, float]], answers: list[dict], args: argparse.Namespace) -> list[NightResult]:
    for (i, name, el), ans in zip(index, answers):
        v = results[i].variants[name]
        v.setdefault("ticks", []).append((el, ans))
        if el == 0:
            v["start"] = ans
    for r in results:
        for name, v in r.variants.items():
            start = v.get("start")
            rate = start["rateW"] if start else None
            v["whatif"] = whatif(r.actual, rate, r.night.length_min, args.buffer_min)
    return results


def run_variants(nights: list[tuple[Night, Actual]], s: dict[str, Series], args: argparse.Namespace, backend: Backend) -> list[NightResult]:
    results, cases, index = plan_variants(nights, s, args)
    return apply_answers(results, index, backend(cases) if cases else [], args)


# ----------------------------------------------------------------------------------------------------------------------------------------
# the report
# ----------------------------------------------------------------------------------------------------------------------------------------

def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    widths = [max(len(str(x)) for x in [h] + [r[i] for r in rows]) for i, h in enumerate(headers)]
    line = lambda cells: "  ".join(str(c).rjust(w) if i else str(c).ljust(w) for i, (c, w) in enumerate(zip(cells, widths))).rstrip()
    return [line(headers), line(["-" * w for w in widths])] + [line(r) for r in rows]


def num(x: float | None, digits: int = 0, unit: str = "") -> str:
    if x is None:
        return "-"
    return f"{x:.{digits}f}{unit}"


def render(results: list[NightResult], args: argparse.Namespace, notes: list[str], skipped: dict[str, int], backend_name: str) -> str:
    tz = args.tz_offset_min
    out: list[str] = []
    out.append("GENTLE RATE ADVICE REPLAY  (read only, offline, " + NOT_A_COMMAND + ")")
    out.append(f"nights: {len(results)}   buffer: {args.buffer_min} min   tick: {args.tick_min} min   target: {args.target}   calibration: {args.calibrate}   soc age: {args.soc_age}")
    out.append(f"charge sign: {args.charge_sign} means charging   setpoint basis: {args.setpoint_basis}   default ceiling basis: {args.ceiling_basis}   advice by: {backend_name}")
    if skipped and any(skipped.values()):
        out.append("skipped states (unavailable, unknown or not a number): " + ", ".join(f"{k} {v}" for k, v in sorted(skipped.items()) if v))
    for n in notes:
        out.append("note: " + n)
    out.append("")
    out.append("[1] WHAT THE BATTERY DID (times are local, window and target as found or given)")
    rows = []
    for r in results:
        a, n = r.actual, r.night
        rows.append([fmt_local(n.start, tz), fmt_hm(n.end, tz) + f" ({n.how})", num(a.soc_start), num(a.soc_end), num(a.target), num(a.reach_min, 0, " min"),
                     num(a.early_vs_deadline_min, 0, " min"), num(a.typical_w), num(a.peak_w), num(a.energy_kwh, 1), num(a.grid_peak_w), num(a.tail_min, 0, " min"),
                     num(a.taper_start, 0, " %")])
    out += table(["night start", "window end", "SOC start", "SOC end", "target", "reached after", "before deadline", "typical W", "peak W", "kWh in", "grid peak W", "tail", "rate fell at"], rows)
    out.append("    typical W = median charge power while charging at pace; tail = minutes the battery kept charging after the first reading at a 100 % target;")
    out.append("    rate fell at = the first SOC point whose mean charge power was under 90 % of the typical one (the target itself: no fall seen before it).")
    out.append("")
    out.append("    what the recorded battery says about the model's assumptions (kWh per SOC point on the main phase; ratio of the nominal capacity to it)")
    rows = [[fmt_local(r.night.start, tz), num(r.actual.kwh_per_pct, 3), num(r.actual.capacity_kwh, 1), num(r.actual.implied_eff, 2), num(r.actual.ceiling_w)] for r in results]
    out += ["    " + x for x in table(["night start", "kWh per SOC point", "nominal kWh", "implied stored/delivered", "configured max W"], rows)]
    out.append("")
    for name in ("shipped", "calibrated"):
        if not any(name in r.variants for r in results):
            continue
        title = "AS SHIPPED (the model's own defaults plus the --param values)" if name == "shipped" else "WITH PARAMETERS READ OFF " + ("THE OTHER NIGHTS (leave one out: a night is never calibrated on itself)" if args.calibrate == "loo" else "ALL NIGHTS (in sample: not an independent test)")
        out.append(f"[{'2' if name == 'shipped' else '3'}] WHAT THE ADVICE WOULD HAVE SAID AT THE WINDOW START, {title}")
        rows = []
        for r in results:
            v = r.variants.get(name)
            if not v or "start" not in v:
                rows.append([fmt_local(r.night.start, tz), "no SOC at the window start"] + [""] * 8)
                continue
            st = v["start"]
            kind, reason, rate = advice_row(st)
            rows.append([fmt_local(r.night.start, tz), kind, reason, rate, num(st["neededW"]), num(st["safeMaxW"]), st["outcome"], num(st["finishInMin"], 0, " min"), num(st["marginMin"], 0, " min"),
                         ("yes" if st["targetWillBeMissed"] else "no")])
        out += table(["night start", "advice", "reason", "advised W", "needed W", "safe max W", "outcome", "projected finish", "margin", "will miss"], rows)
        used = {k: v for r in results for k, v in (r.variants.get(name, {}).get("params") or {}).items()}
        if name == "calibrated":
            for i, r in enumerate(results):
                p = r.variants.get(name, {}).get("params") or {}
                out.append(f"    parameters for {fmt_local(r.night.start, tz)}: " + (", ".join(f"{k}={v:g}" for k, v in sorted(p.items())) or "none (the defaults stay)"))
            first_notes = next((r.variants[name]["notes"] for r in results if r.variants.get(name, {}).get("notes")), [])
            for note in first_notes:
                out.append("    " + note)
        elif used:
            out.append("    parameters: " + ", ".join(f"{k}={v:g}" for k, v in sorted(used.items())))
        out.append("")
    out.append("[4] COMPARISON: the advised rate against what the battery was given, and a what-if (estimate, not a measurement)")
    rows = []
    for r in results:
        a = r.actual
        for name in ("shipped", "calibrated"):
            v = r.variants.get(name)
            if not v or "start" not in v:
                continue
            st = v["start"]
            w = v.get("whatif")
            ratio = "-" if st["rateW"] is None or not a.typical_w else f"{100.0 * st['rateW'] / a.typical_w:.0f} %"
            rows.append([fmt_local(r.night.start, tz), name, num(a.typical_w), num(st["rateW"]), ratio, num(a.reach_min, 0, " min"), num(a.deadline_min, 0, " min"),
                         "-" if w is None else num(w["finish_min"], 0, " min"), "-" if w is None else num(w["margin_min"], 0, " min"),
                         "-" if w is None else ("on time" if w["margin_min"] >= 0 else "LATE")])
    out += table(["night start", "advice", "actual typical W", "advised W", "advised / actual", "actual reached", "deadline", "what-if finish", "what-if margin", "what-if"], rows)
    out.append("    what-if = the night's own energy per SOC point divided by the advised rate, plus the observed tail. The battery was never recorded at that lower rate.")
    out.append("")
    out.append(f"[5] RE-PLAN TRACE: the advice every {args.tick_min} min on the SOC the battery really had (statistics per night)")
    rows = []
    for r in results:
        for name in ("shipped", "calibrated"):
            v = r.variants.get(name)
            if not v or not v.get("ticks"):
                continue
            ticks = v["ticks"]
            rated = [t[1]["rateW"] for t in ticks if t[1]["rateW"] is not None]
            none_reasons: dict[str, int] = {}
            for _, ans in ticks:
                if ans["advice"] == "NO_ADVICE":
                    none_reasons[ans["reason"]] = none_reasons.get(ans["reason"], 0) + 1
            at_target = next((t[0] for t in ticks if t[1]["advice"] == "NOTHING_TO_CHARGE"), None)
            def rate_at(m: int) -> str:
                for el, ans in ticks:
                    if el == m:
                        return "-" if ans["rateW"] is None else f"{ans['rateW']:.0f}"
                return "-"
            rows.append([fmt_local(r.night.start, tz), name, str(len(ticks)), str(len(rated)), ", ".join(f"{k} x{c}" for k, c in sorted(none_reasons.items())) or "none",
                         num(min(rated) if rated else None), num(max(rated) if rated else None), rate_at(0), rate_at(60), rate_at(120), num(at_target, 0, " min"), num(r.actual.reach_min, 0, " min")])
    out += table(["night start", "advice", "ticks", "with a rate", "no advice (reason)", "min W", "max W", "W at +0", "W at +60", "W at +120", "first at target", "actual reached"], rows)
    out.append("    The recorded SOC is the SOC of the fast charge the battery really had, so later ticks show a battery far ahead of a gentle schedule; the trace shows the")
    out.append("    advice is stable on real readings and says nothing when readings are missing, not that the gentle charge would have followed it.")
    out.append("")
    out.append("LIMITS: one site and a few nights; every night is a fixed-rate charge; the response at lower rates is unmeasured; the taper, efficiency and top-of-charge")
    out.append("values are assumptions unless read off the nights above; the advice is a model, not a command, and guarantees nothing; nothing here is applied anywhere.")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------------------------------------------------------------------
# command line
# ----------------------------------------------------------------------------------------------------------------------------------------

def build_parser(driver: bool = False) -> argparse.ArgumentParser:
    """The command line. The driver (tools/gentle_replay_run.py) runs the advice itself; this module only reads its answers from a file."""
    ap = argparse.ArgumentParser(description="Replay the read-only Gentle rate advice against recorded nights (offline).")
    ap.add_argument("evidence", help="folder with hist-<kind>-YYYY-MM-DD.json files (Home Assistant history JSON)")
    ap.add_argument("--window", help="the local cheap window HH:MM-HH:MM (default: detected from the data)")
    ap.add_argument("--tz-offset-min", type=int, default=0, help="local time = UTC + this many minutes (default 0); ordinary days only")
    ap.add_argument("--target", default="auto", help="target SOC in percent, or auto = the highest SOC reached in the window (default)")
    ap.add_argument("--buffer-min", type=int, default=60, help="finish-early buffer in minutes (default 60)")
    ap.add_argument("--tick-min", type=int, default=10, help="re-plan interval in minutes, 5 to 15 (default 10)")
    ap.add_argument("--capacity-kwh", type=float, help="battery capacity (default: the hist-batcap file)")
    ap.add_argument("--capacity-band-pct", type=float, default=6.0, help="capacity band assumed by the plan (default 6)")
    ap.add_argument("--ceiling", action="append", help="a safe power ceiling NAME=WATTS[:GRID_AC|BATTERY_DC] (repeatable; default: the hist-maxgrid file)")
    ap.add_argument("--ceiling-basis", choices=["GRID_AC", "BATTERY_DC", "NONE"], default="GRID_AC", help="what the hist-maxgrid figure is measured on (default GRID_AC)")
    ap.add_argument("--setpoint-basis", choices=["UNSETTLED", "GRID_AC", "BATTERY_DC"], default="UNSETTLED")
    ap.add_argument("--unknown-demand-policy", choices=["FALLBACK", "ASSUME_PROVISIONAL"], default="FALLBACK")
    ap.add_argument("--grid-limit-w", type=float, help="a KNOWN safe grid import limit in W (default: none, so no grid headroom constraint)")
    ap.add_argument("--param", action="append", help="a model parameter NAME=NUMBER (repeatable), for example taperStartSocPct=98")
    ap.add_argument("--calibrate", choices=["none", "loo", "all"], default="loo", help="also run with parameters read off the other nights (loo), all nights, or not (none)")
    ap.add_argument("--charge-sign", choices=["negative", "positive"], default="negative", help="the sign of the battery power that means charging (default negative)")
    ap.add_argument("--soc-age", choices=["fresh", "since-change"], default="fresh", help="age given to a SOC reading (default fresh; see the module text)")
    ap.add_argument("--session-min-w", type=float, default=1000.0, help="charge power that counts as a charge run (default 1000)")
    ap.add_argument("--tail-end-w", type=float, default=200.0, help="charge power under which the top-of-charge tail has ended (default 200)")
    ap.add_argument("--output", help="also write the report to this file")
    if not driver:
        ap.add_argument("--emit-cases", action="store_true", help="print the questions for the advice as JSON and stop (feed them to frontend/ecco-plan-core/tools/adviseBatch.ts)")
        ap.add_argument("--results", help="the advice's answers: the output of adviseBatch.ts for the cases of --emit-cases, run with the same options")
    return ap


def check_args(args: argparse.Namespace) -> None:
    if args.target != "auto":
        try:
            t = float(args.target)
        except ValueError as exc:
            raise ToolError(f"--target must be auto or a number, got {args.target!r}") from exc
        if not 10 <= t <= 100:
            raise ToolError("--target must be 10 to 100")
        args.target = t
    if not 5 <= args.tick_min <= 15:
        raise ToolError("--tick-min must be 5 to 15")
    if not 0 <= args.buffer_min <= 120 or args.buffer_min % 5:
        raise ToolError("--buffer-min must be 0 to 120 in steps of 5")
    if args.capacity_band_pct < 0:
        raise ToolError("--capacity-band-pct must be 0 or more")
    for c in args.ceiling or []:
        parse_ceiling(c)
    parse_params(args.param)
    if args.window:
        parse_window(args.window)


def prepare(args: argparse.Namespace) -> tuple[dict[str, Series], dict[str, int], list[tuple[Night, Actual]], list[str]]:
    check_args(args)
    s, skipped = load_all(Path(args.evidence))
    nights, notes = find_nights(s, args)
    if not nights:
        raise ToolError("no cheap-window night found in the data" + (": " + "; ".join(notes) if notes else ""))
    measured = [(n, measure(n, s, args)) for n in nights]
    for n, a in measured:
        for note in a.notes:
            notes.append(f"{fmt_local(n.start, args.tz_offset_min)}: {note}")
    return s, skipped, measured, notes


def emit_cases(args: argparse.Namespace) -> str:
    """The questions for the advice as one JSON document (the input of adviseBatch.ts)."""
    s, _skipped, measured, _notes = prepare(args)
    _results, cases, _index = plan_variants(measured, s, args)
    return json.dumps({"cases": cases})


def analyse(args: argparse.Namespace, backend: Backend | None = None, backend_name: str | None = None) -> str:
    s, skipped, measured, notes = prepare(args)
    if backend is None:
        if not getattr(args, "results", None):
            raise ToolError("no source for the advice: use --emit-cases and --results FILE, or run tools/gentle_replay_run.py")
        backend = results_backend(Path(args.results))
        backend_name = "the answers in " + Path(args.results).name + " (frontend/ecco-plan-core/src/gentleAdvice.ts through Node)"
    results = run_variants(measured, s, args, backend)
    return render(results, args, notes, skipped, backend_name or "a supplied backend")


def run(args: argparse.Namespace, backend: Backend | None = None, backend_name: str | None = None) -> int:
    emitting = bool(getattr(args, "emit_cases", False))
    try:
        text = emit_cases(args) + "\n" if emitting else analyse(args, backend, backend_name)
    except ToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(text)
    if args.output and not emitting:
        Path(args.output).write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None, backend: Backend | None = None) -> int:
    return run(build_parser().parse_args(argv), backend)


if __name__ == "__main__":
    sys.exit(main())
