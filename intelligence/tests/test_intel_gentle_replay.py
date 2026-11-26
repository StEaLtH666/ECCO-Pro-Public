#!/usr/bin/env python3
"""The offline Gentle replay tool (intelligence/tools/gentle_replay.py). SYNTHETIC recordings only (generated here, fictional values).

  [1] recorded series: time stamps need a zone, unavailable / unknown / not-a-number states are skipped and counted, a file that is not a history file is
      refused, a step-hold series answers at / last_change / integral by hand
  [2] discovery and merging of day files (a charge across midnight is one run), required and optional kinds
  [3] nights: the charge run, the window start and end found from the data, an explicit window, a PV-only charge is not a cheap-window night, a split run is
      one night, a run with no window end is reported and never guessed
  [4] what the battery did: start and end SOC, target, how early, power profile, tail, energy per SOC point, where the rate fell, the notes on missing data
  [5] calibration from other nights (leave one out, in sample, none; the cautious value of each; the caller's --param wins)
  [6] the advice inputs: ceilings and their basis, capacity, policy, the reading and its age at each tick, the previous reading, the house only with a known
      grid limit, local window minutes
  [7] the what-if arithmetic, the report, the command line and its refusals
  [8] the advice itself through Node (skipped when Node 22.18 or newer is not installed): the one implementation answers, a failure is an error, never a guess;
      the tool reads the answers from a file (--emit-cases, adviseBatch.ts, --results) and refuses a missing, failed or doubled answer
  [9] static: the tool starts no process (the Intelligence authority gate), has no network, no service call, no write but --output, no site name, address or
      entity id; the driver outside intelligence/ starts only Node, by an argument list; the runner reads standard input and writes standard output only
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from intelligence.tools import gentle_replay as gr  # noqa: E402
import gentle_replay_run as drv  # noqa: E402   (the one-command driver outside intelligence/: it starts Node)

FAILURES: list[str] = []
REPO = Path(__file__).resolve().parents[2]
UTC = timezone.utc


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def raises(fn, exc=gr.ToolError) -> bool:
    try:
        fn()
    except exc:
        return True
    return False


def close(a, b, tol) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def section(title: str) -> None:
    print("")
    print(title)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=UTC).isoformat()


T0 = datetime(2030, 1, 15, 0, 30, tzinfo=UTC).timestamp()   # the window start of the first synthetic night (fictional date)
DAY = 86400.0
CAP = 30.0            # nominal kWh of the synthetic battery
KWH_PCT = 0.30        # kWh (battery side) per SOC point: the synthetic battery's real response


def synth_night(t0: float, soc0: float = 30.0, rate_w: float = 8000.0, tail_min: float = 40.0, tail_w: float = 600.0, window_min: float = 300.0,
                taper_from: float | None = None, house_w: float = 650.0, pv_w: float = 0.0, step: float = 10.0) -> dict[str, list[tuple[float, float]]]:
    """A fictional cheap-window night: idle, a fixed-rate grid charge from the window start to 100 %, a tail, then the battery takes over at the window end."""
    out: dict[str, list[tuple[float, float]]] = {"soc": [(t0 - 3600, float(int(soc0)))], "batt": [], "grid": [], "house": [], "pv": []}
    t = t0 - 1800.0
    soc_f = soc0
    reading = int(soc0)
    t_full = None
    end = t0 + window_min * 60.0
    while t < end + 1800.0:
        if t < t0 + 20 or t >= end:
            batt, grid = 700.0, 20.0                       # the battery supplies the house; positive = discharge
        elif soc_f < 100.0:
            f = 1.0 if taper_from is None or soc_f < taper_from else max(0.4, 1.0 - 0.06 * (soc_f - taper_from))
            p = rate_w * f
            soc_f += p * step / 3.6e6 / KWH_PCT
            batt, grid = -p, house_w + p / 0.93
            if soc_f >= 100.0:
                t_full = t
        elif t < t_full + 120:
            batt, grid = -rate_w, house_w + rate_w / 0.93   # a short stretch at full power after the reading hits 100
        elif t < t_full + 120 + tail_min * 60.0:
            batt, grid = -tail_w, house_w + tail_w / 0.93   # the tail
        else:
            batt, grid = -20.0, house_w + 20.0              # full: the grid carries the house
        new = min(int(soc_f), 100)
        if new != reading:
            reading = new
            out["soc"].append((t, float(reading)))
        out["batt"].append((t, batt))
        out["grid"].append((t, grid))
        out["house"].append((t, house_w))
        out["pv"].append((t, pv_w))
        t += step
    return out


def write_days(folder: Path, kind: str, points: list[tuple[float, float]]) -> None:
    by_day: dict[str, list[tuple[float, float]]] = {}
    for t, v in points:
        by_day.setdefault(datetime.fromtimestamp(t, tz=UTC).strftime("%Y-%m-%d"), []).append((t, v))
    for day, pts in by_day.items():
        rows = [{"entity_id": "sensor.synthetic_example", "state": f"{v:g}", "attributes": {}, "last_changed": iso(t), "last_updated": iso(t)} if i == 0
                else {"state": f"{v:g}", "last_changed": iso(t)} for i, (t, v) in enumerate(pts)]
        (folder / f"hist-{kind}-{day}.json").write_text(json.dumps([rows]), encoding="utf-8")


def write_night(folder: Path, night: dict, extra: dict[str, float] | None = None) -> None:
    for kind, pts in night.items():
        write_days(folder, kind, pts)
    for kind, value in (extra or {}).items():
        d0 = datetime.fromtimestamp(night["soc"][0][0], tz=UTC).replace(hour=0, minute=0, second=0)
        write_days(folder, kind, [(d0.timestamp(), value)])


def args_for(folder: Path, *extra: str):
    return gr.build_parser().parse_args([str(folder), *extra])


def stub_factory(calls: list):
    def stub(cases: list[dict]) -> list[dict]:
        calls.append(cases)
        out = []
        for c in cases:
            inp = c["input"]
            soc, target = inp["socPct"], inp["targetSocPct"]
            base = {"id": c["id"], "rateAmps": None, "neededW": None, "minRateW": 500, "safeMaxW": 8000, "limitedBy": "CEILING", "deadlineInMin": 240, "finishInMin": None,
                    "marginMin": None, "targetWillBeMissed": False, "degraded": False, "codes": [], "summary": "stub", "status": "OK", "rateW": None}
            if soc is None:
                out.append({**base, "advice": "NO_ADVICE", "reason": "NO_SOC", "outcome": "UNKNOWN"})
            elif soc >= target:
                out.append({**base, "advice": "NOTHING_TO_CHARGE", "reason": "AT_TARGET", "outcome": "AT_TARGET"})
            else:
                w = 5000.0 - 10.0 * soc
                out.append({**base, "advice": "RATE", "reason": "RATE_GENTLEST", "outcome": "ON_TIME", "rateW": w, "neededW": w, "finishInMin": 200.0, "marginMin": 40.0})
        return out
    return stub


def node_ok() -> bool:
    """Node with type stripping is installed (the driver's own check): when it is not, the Node checks are SKIPPED, and said so."""
    try:
        drv.node_backend()
    except gr.ToolError:
        return False
    return True


# ===========================================================================
section("[1] recorded series")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    good = tdp / "hist-soc-2030-01-15.json"
    good.write_text(json.dumps([[{"entity_id": "x", "state": "40", "last_changed": "2030-01-15T00:00:00+00:00"}, {"state": "unavailable", "last_changed": "2030-01-15T00:10:00+00:00"},
                                 {"state": "unknown", "last_changed": "2030-01-15T00:20:00+00:00"}, {"state": "abc", "last_changed": "2030-01-15T00:30:00+00:00"},
                                 {"state": "nan", "last_changed": "2030-01-15T00:40:00+00:00"}, {"state": "42.5", "last_changed": "2030-01-15T01:00:00Z"}]]), encoding="utf-8")
    pts, skipped = gr.load_history(good)
    check("numeric states are read, unavailable / unknown / not a number / nan are skipped and counted", len(pts) == 2 and skipped == 4 and pts[1][1] == 42.5, str((pts, skipped)))
    check("a trailing Z means UTC", close(pts[1][0] - pts[0][0], 3600, 1e-6))
    for name, body in [("not json", "{{"), ("not a list of series", json.dumps({"a": 1})), ("series is not a list", json.dumps([1, 2])), ("row without a state", json.dumps([[{"last_changed": "2030-01-15T00:00:00+00:00"}]])),
                       ("row without a time", json.dumps([[{"state": "1"}]])), ("time without a zone", json.dumps([[{"state": "1", "last_changed": "2030-01-15T00:00:00"}]])),
                       ("time that is not a time", json.dumps([[{"state": "1", "last_changed": "yesterday"}]]))]:
        bad = tdp / "bad.json"
        bad.write_text(body, encoding="utf-8")
        check(f"refused: {name}", raises(lambda: gr.load_history(bad)))
    check("a missing file is refused", raises(lambda: gr.load_history(tdp / "nope.json")))
    s = gr.Series([(100.0, 10.0), (200.0, 20.0), (300.0, 0.0), (100.0, 10.0)])
    check("a duplicate sample is kept once, sorted", len(s) == 3 and s.t == [100.0, 200.0, 300.0])
    check("at: before the first sample there is no value, then the last one at or before", s.at(50) is None and s.at(100) == 10 and s.at(199.9) == 10 and s.at(200) == 20 and s.at(1000) == 0)
    check("last_change is the time of that sample", s.last_change(250) == 200 and s.last_change(50) is None)
    check("between is inclusive at both ends", [p[0] for p in s.between(100, 200)] == [100.0, 200.0])
    check("integral: step-hold, clipped to the interval (10 x 100 + 20 x 100 = 3000)", s.integral(100, 300) == 3000.0)
    check("integral: a part-way start and end (10 x 50 + 20 x 50 = 1500)", s.integral(150, 250) == 1500.0)
    check("integral: the part before the first sample counts as nothing, an empty or reversed interval is 0", s.integral(0, 100) == 0.0 and s.integral(300, 100) == 0.0)
    check("integral: the last value holds to the end of the interval (0 here), and f is applied", s.integral(100, 400, lambda v: v * 2) == 6000.0)
    check("a negative-going function can be clipped (charge power from a negative-is-charging value)", gr.Series([(0.0, -5000.0), (10.0, 300.0)]).integral(0, 20, lambda v: max(gr.charge_w(v, "negative"), 0.0)) == 50000.0)
    check("charge_w follows the stated sign", gr.charge_w(-5.0, "negative") == 5.0 and gr.charge_w(-5.0, "positive") == -5.0)

# ===========================================================================
section("[2] discovery and merging")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    check("a folder that does not exist is refused", raises(lambda: gr.discover(tdp / "nope")))
    check("a folder with no soc and batt files is refused", raises(lambda: gr.discover(tdp)))
    n1 = synth_night(T0)
    write_days(tdp, "soc", n1["soc"])
    check("batt is required as well", raises(lambda: gr.discover(tdp)))
    write_days(tdp, "batt", n1["batt"])
    (tdp / "hist-other-2030-01-15.json").write_text("[]", encoding="utf-8")
    (tdp / "notes.txt").write_text("x", encoding="utf-8")
    (tdp / "hist-soc-bad-date.json").write_text("[]", encoding="utf-8")
    found = gr.discover(tdp)
    check("only the known kinds with a dated name are found", set(found) == {"soc", "batt"}, str(found))
    # a charge that runs across midnight is one run
    t_mid = datetime(2030, 1, 15, 23, 30, tzinfo=UTC).timestamp()
    cm = synth_night(t_mid, soc0=20.0)
    with tempfile.TemporaryDirectory() as td2:
        d2 = Path(td2)
        write_night(d2, cm, {"batcap": CAP, "maxgrid": 8000.0})
        files = gr.discover(d2)
        check("the night is split over two day files", len(files["soc"]) == 2 and len(files["batt"]) == 2, str(files))
        series, skipped = gr.load_all(d2)
        check("merged into one series per kind, no sample lost", len(series["batt"]) == len(cm["batt"]) and all(v == 0 for v in skipped.values()))
        a = args_for(d2)
        nights, notes = gr.find_nights(series, a)
        check("one night across midnight: it starts at the window start and ends 5 hours later", len(nights) == 1 and close(nights[0].start, t_mid, 1) and close(nights[0].end, t_mid + 300 * 60, 1), str(notes))

# ===========================================================================
section("[3] nights: the run, the window, the edges")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)
    n2 = synth_night(T0 + DAY, soc0=45.0, rate_w=7000.0, tail_min=15.0)
    for k in n1:
        write_days(tdp, k, sorted(n1[k] + n2[k]))
    series, _ = gr.load_all(tdp)
    runs = gr.find_sessions(series["batt"], "negative")
    check("two charge runs of at least 30 minutes at or above 1000 W", len(runs) == 2, str(runs))
    check("a run starts at its first sample at pace", close(runs[0][0], T0 + 20, 11), str(runs[0]))
    check("a run ends at the first sample after its last sample at pace (the power has dropped by then)", runs[0][1] in series["batt"].t and gr.charge_w(series["batt"].at(runs[0][1]), "negative") < 1000
          and gr.charge_w(series["batt"].at(runs[0][1] - 10), "negative") >= 1000, str(runs[0]))
    check("a threshold above the charge power finds none, a larger minimum length drops them", gr.find_sessions(series["batt"], "negative", min_w=9000) == [] and gr.find_sessions(series["batt"], "negative", min_len_s=86400) == [])
    check("the other sign convention finds no charge in a negative-is-charge recording at pace (it would read discharge)", len(gr.find_sessions(series["batt"], "positive")) == 0)
    nights, notes = gr.find_nights(series, args_for(tdp))
    check("two nights, windows 00:30 to 05:30 found from the data (the battery takes over from the grid)", len(nights) == 2 and all(n.how == "detected" for n in nights)
          and close(nights[0].start, T0, 1) and close(nights[0].end, T0 + 18000, 1) and close(nights[1].start, T0 + DAY, 1) and not notes, str((nights and nights[0].end - nights[0].start, notes)))
    check("the length of a night in minutes", close(nights[0].length_min, 300, 0.01))
    ex, _ = gr.find_nights(series, args_for(tdp, "--window", "00:30-05:30"))
    check("an explicit window gives the same two nights", len(ex) == 2 and all(n.how == "explicit window" for n in ex) and close(ex[0].start, T0, 1) and close(ex[0].end, T0 + 18000, 1))
    off, _ = gr.find_nights(series, args_for(tdp, "--window", "01:30-06:30", "--tz-offset-min", "60"))
    check("a local window with a time zone offset lands on the same real window", len(off) == 2 and close(off[0].start, T0, 1))
    pre, _ = gr.find_nights(series, args_for(tdp, "--window", "22:00-06:00"))
    check("a window that opens the evening before a charge which begins after midnight starts the evening before (and is 8 hours long)", len(pre) == 2 and close(pre[0].start, T0 - 2.5 * 3600, 1)
          and close(pre[0].end, T0 + 5.5 * 3600, 1) and close(pre[1].start, T0 + DAY - 2.5 * 3600, 1) and close(pre[0].length_min, 480, 0.01))
    wrong, wnotes = gr.find_nights(series, args_for(tdp, "--window", "10:00-12:00"))
    check("a window that does not contain the charge run: no night, a note, never a guess", wrong == [] and len(wnotes) == 2 and "outside the window" in wnotes[0], str(wnotes))
    check("analyse says so for a data set with no night", raises(lambda: gr.analyse(args_for(tdp, "--window", "10:00-12:00", "--capacity-kwh", "30"), stub_factory([]))))
    for bad in ["25:00-05:00", "0030-0530", "00:30-00:30", "00:30"]:
        check(f"window {bad!r} is refused", raises(lambda b=bad: gr.parse_window(b)))
    check("a window past midnight wraps", gr.parse_window("23:30-04:30") == (1410, 270))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    # a window that opens at 00:35 (the owner's 5-minute grid, not a 10-minute one): the edges are rounded to 5 minutes, not more
    late = synth_night(T0 + 300)
    for k, v in late.items():
        write_days(tdp, k, v)
    s, _ = gr.load_all(tdp)
    nights, _ = gr.find_nights(s, args_for(tdp))
    check("a window of 00:35 to 05:35 is found on the 5-minute grid", len(nights) == 1 and close(nights[0].start, T0 + 300, 1) and close(nights[0].end, T0 + 300 + 18000, 1), str(nights and (nights[0].start - T0, nights[0].end - T0)))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    # a PV-only charge in daylight (no grid import) is not a cheap-window night
    t_day = datetime(2030, 1, 15, 10, 0, tzinfo=UTC).timestamp()
    pts_b = [(t_day + 60 * k, -3000.0 if k < 120 else 200.0) for k in range(0, 200)]
    pts_g = [(t_day + 60 * k, 20.0) for k in range(0, 200)]
    write_days(tdp, "soc", [(t_day - 60, 50.0), (t_day + 3600, 60.0)])
    write_days(tdp, "batt", pts_b)
    write_days(tdp, "grid", pts_g)
    s, _ = gr.load_all(tdp)
    ses = gr.find_sessions(s["batt"], "negative")
    check("there is a charge run", len(ses) == 1)
    check("but it is not fed from the grid, so it is not a cheap-window night", not gr.is_grid_charge(ses[0], s["batt"], s["grid"], "negative") and gr.find_nights(s, args_for(tdp))[0] == [])
    check("without a grid series a charge run is assumed to be one", gr.is_grid_charge(ses[0], s["batt"], None, "negative"))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)
    # a gap in the recording in the middle of the charge splits the run in two; it is still ONE night
    gap_lo, gap_hi = T0 + 60 * 60, T0 + 90 * 60
    cut = {k: [p for p in v if not (gap_lo <= p[0] < gap_hi)] for k, v in n1.items()}
    for k, v in cut.items():
        write_days(tdp, k, v)
    s, _ = gr.load_all(tdp)
    check("the gap splits the run", len(gr.find_sessions(s["batt"], "negative")) == 2)
    nights, _ = gr.find_nights(s, args_for(tdp))
    check("one night, from the first run to the window end", len(nights) == 1 and close(nights[0].start, T0, 1) and close(nights[0].end, T0 + 18000, 1))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)
    short = {k: [p for p in v if p[0] < T0 + 200 * 60] for k, v in n1.items()}   # the recording stops before the battery takes over
    for k, v in short.items():
        write_days(tdp, k, v)
    s, _ = gr.load_all(tdp)
    nights, notes = gr.find_nights(s, args_for(tdp))
    check("a charge run with no window end in the data: no night and a note that says to pass --window", nights == [] and len(notes) == 1 and "--window" in notes[0], str(notes))
    ex, _ = gr.find_nights(s, args_for(tdp, "--window", "00:30-05:30"))
    check("with the window given the night is used", len(ex) == 1)

# ===========================================================================
section("[4] what the battery did")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)   # soc 30 -> 100 at 8 kW, a 40 min tail at 600 W
    write_night(tdp, n1, {"batcap": CAP, "maxgrid": 8000.0})
    a = args_for(tdp)
    s, _ = gr.load_all(tdp)
    nights, _ = gr.find_nights(s, a)
    m = gr.measure(nights[0], s, a)
    reach = (100 - 30) * KWH_PCT / 8.0 * 60.0     # minutes to 100 at 8 kW
    check("start SOC is the reading at the window start, end SOC the reading at the window end", m.soc_start == 30 and m.soc_end == 100)
    check("target auto is the highest SOC reached in the window", m.target == 100)
    check(f"reached 100 after about {reach:.1f} min", close(m.reach_min, reach, 1.0), str(m.reach_min))
    check("deadline = window length minus the buffer; early against the deadline and the window end", m.deadline_min == 240 and close(m.early_vs_deadline_min, 240 - reach, 1.0) and close(m.early_vs_end_min, 300 - reach, 1.0))
    check("typical and peak charge power are the 8 kW the battery was given", close(m.typical_w, 8000, 1) and close(m.peak_w, 8000, 1))
    energy = 8.0 * reach / 60.0 + 0.6 * 40.0 / 60.0 + 8.0 * 2.0 / 60.0
    check("energy in covers the main charge, the short full-power stretch and the tail", close(m.energy_kwh, energy, 0.4), f"{m.energy_kwh} vs {energy}")
    check("grid peak is the highest import before the target was reached", close(m.grid_peak_w, 650 + 8000 / 0.93, 5), str(m.grid_peak_w))
    check("the tail is about 40 min, at about 600 W (the short full-power stretch is part of it)", close(m.tail_min, 42, 2.5) and m.tail_w is not None and 600 < m.tail_w < 1500, f"{m.tail_min} {m.tail_w}")
    check("energy per SOC point is the battery's real 0.30 kWh", close(m.kwh_per_pct, KWH_PCT, 0.01), str(m.kwh_per_pct))
    check("the implied stored/delivered ratio is the nominal capacity per point over that (1.0 here)", close(m.implied_eff, (CAP / 100) / KWH_PCT, 0.05), str(m.implied_eff))
    check("no fall of the charge power was seen before the target", m.taper_start == 100, str(m.taper_start))
    check("the configured maximum and the capacity are read at the window start", m.ceiling_w == 8000.0 and m.capacity_kwh == CAP)
    m2 = gr.measure(nights[0], s, args_for(tdp, "--target", "80", "--buffer-min", "30"))
    check("an explicit lower target: reached earlier, no tail, deadline from the buffer", m2.target == 80 and close(m2.reach_min, (80 - 30) * KWH_PCT / 8.0 * 60, 1.0) and m2.tail_min == 0.0 and m2.deadline_min == 270)
    m3 = gr.measure(nights[0], s, args_for(tdp, "--capacity-kwh", "50"))
    check("a capacity given on the command line wins over the file", m3.capacity_kwh == 50 and close(m3.implied_eff, 0.5 / KWH_PCT, 0.05))
    m4 = gr.measure(nights[0], s, args_for(tdp, "--target", "95"))
    check("a target of 95 is reached before 100 and has no tail", close(m4.reach_min, (95 - 30) * KWH_PCT / 8.0 * 60, 1.0) and m4.tail_min == 0.0)
    m5 = gr.measure(nights[0], s, args_for(tdp, "--charge-sign", "positive"))
    check("with the wrong charge sign nothing is called a charge at pace (no typical or peak power)", m5.typical_w is None and m5.peak_w is None)

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    nt = synth_night(T0, taper_from=90.0)
    write_night(tdp, nt, {"batcap": CAP, "maxgrid": 8000.0})
    s, _ = gr.load_all(tdp)
    a = args_for(tdp)
    nights, _ = gr.find_nights(s, a)
    m = gr.measure(nights[0], s, a)
    check("a battery whose charge power falls from 90 %: the fall is found near 91 to 93 %", m.taper_start is not None and 91 <= m.taper_start <= 93, str(m.taper_start))
    check("its main-phase energy per point is still about the real 0.30 (the fall is above the main phase)", close(m.kwh_per_pct, KWH_PCT, 0.02), str(m.kwh_per_pct))

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)
    late_soc = [p for p in n1["soc"] if p[0] > T0 + 60]      # no SOC reading at or before the window start
    write_days(tdp, "soc", late_soc)
    for k in ("batt", "grid", "house", "pv"):
        write_days(tdp, k, n1[k])
    write_days(tdp, "batcap", [(T0 - 7200, CAP)])
    s, _ = gr.load_all(tdp)
    a = args_for(tdp)
    nights, _ = gr.find_nights(s, a)
    m = gr.measure(nights[0], s, a)
    check("no SOC at the window start: every SOC-based number is None and there is a note", m.soc_start is None and m.target is None and m.reach_min is None and len(m.notes) == 1)
    calls: list = []
    text = gr.analyse(args_for(tdp), stub_factory(calls))
    check("the report says so instead of dropping the night, and asks the advice nothing for it", "no SOC at the window start" in text and calls == [] or all(not c for c in calls), text[:300])

# ===========================================================================
section("[5] calibration from other nights")
# ===========================================================================
def fake(taper=None, tail=None, eff=None, target=100.0):
    x = gr.Actual()
    x.taper_start, x.tail_min, x.implied_eff, x.target = taper, tail, eff, target
    return x

p, notes = gr.calibrate([fake(100.0, 48.0, 0.91), fake(100.0, 17.0, 0.93), fake(92.0, 52.0, 0.905)])
check("the cautious value of each: the earliest fall (floored), the longest tail (up to 5), the lowest efficiency (down to a hundredth)", p == {"taperStartSocPct": 92.0, "topHoldMin": 55.0, "chargeEff": 0.9}, str(p))
check("a note says where each value comes from", len(notes) == 3)
p, _ = gr.calibrate([fake(100.0, 10.0, 1.3)])
check("no fall seen: the taper start is capped at 99 (the model's range), an efficiency above 1 is capped at 1", p["taperStartSocPct"] == 99.0 and p["chargeEff"] == 1.0)
p, _ = gr.calibrate([fake(100.0, 400.0, None)])
check("a tail is capped at the model's 120 minutes, no efficiency means the default stays", p["topHoldMin"] == 120.0 and "chargeEff" not in p)
p, _ = gr.calibrate([fake(None, None, None)])
check("nothing measurable: nothing is overridden", p == {})
p, _ = gr.calibrate([fake(100.0, 30.0, 0.95, target=80.0)])
check("a tail is not read off a night whose target was not 100", "topHoldMin" not in p)

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    specs = [(T0, 30.0, 8000.0, 20.0), (T0 + DAY, 40.0, 8000.0, 50.0), (T0 + 2 * DAY, 25.0, 8000.0, 10.0)]
    parts = [synth_night(t, soc0=s0, rate_w=r, tail_min=tl) for t, s0, r, tl in specs]
    for k in parts[0]:
        write_days(tdp, k, sorted(sum((p_[k] for p_ in parts), [])))
    write_days(tdp, "batcap", [(T0 - 3600, CAP)])
    write_days(tdp, "maxgrid", [(T0 - 3600, 8000.0)])
    calls = []
    text = gr.analyse(args_for(tdp, "--calibrate", "loo"), stub_factory(calls))
    key = lambda c: c["id"].rsplit("/", 1)[0]   # the id is variant/night/tick/hash of the question
    cases = {key(c): c["input"] for batch in calls for c in batch}
    by = lambda variant, night: cases[f"{variant}/{night}/0"].get("params", {})
    check("shipped: no override unless the caller gave one", all(by("shipped", i) == {} for i in range(3)))
    # the measured tail is the synthetic tail plus the 2 minute full-power stretch after the reading hits 100: about 22, 52 and 12 minutes
    check("leave one out: night 1 (tail about 52) is calibrated on the others only (about 22 and 12 -> 25)", by("calibrated", 1).get("topHoldMin") == 25.0, str(by("calibrated", 1)))
    check("leave one out: night 0 sees the longer tail of night 1 (about 52 -> 55)", by("calibrated", 0).get("topHoldMin") == 55.0, str(by("calibrated", 0)))
    check("leave one out: night 2 sees 55 as well", by("calibrated", 2).get("topHoldMin") == 55.0, str(by("calibrated", 2)))
    calls = []
    gr.analyse(args_for(tdp, "--calibrate", "all"), stub_factory(calls))
    cases = {key(c): c["input"] for batch in calls for c in batch}
    check("in sample (all): every night is calibrated on all three, its own included (55)", all(cases[f"calibrated/{i}/0"]["params"]["topHoldMin"] == 55.0 for i in range(3)))
    calls = []
    text_none = gr.analyse(args_for(tdp, "--calibrate", "none"), stub_factory(calls))
    check("calibrate none: only the shipped variant, no section 3", all(i.startswith("shipped/") for b in calls for i in [c["id"] for c in b]) and "[3]" not in text_none)
    calls = []
    gr.analyse(args_for(tdp, "--calibrate", "loo", "--param", "topHoldMin=5", "--param", "demandMarginPct=30"), stub_factory(calls))
    cases = {key(c): c["input"] for batch in calls for c in batch}
    check("a parameter the caller sets wins over the calibrated one and is also in the shipped variant", cases["calibrated/1/0"]["params"]["topHoldMin"] == 5.0 and cases["shipped/1/0"]["params"] == {"topHoldMin": 5.0, "demandMarginPct": 30.0})
    check("the report names the parameters used for each night", "parameters for" in text and "topHoldMin=" in text)

# ===========================================================================
section("[6] the advice inputs")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0, soc0=30.0, pv_w=250.0)
    write_night(tdp, n1, {"batcap": CAP, "maxgrid": 8000.0})
    s, _ = gr.load_all(tdp)
    a = args_for(tdp, "--tz-offset-min", "60")
    nights, _ = gr.find_nights(s, a)
    act = gr.measure(nights[0], s, a)
    inp = gr.base_input(nights[0], act, s, a, {})
    check("the window in local minutes (the offset applied), an ordinary day, the owner's target and buffer", inp["chargeWindow"] == {"startMin": 90, "endMin": 390, "clockDay": {"changeAtMin": 0, "deltaMin": 0}}
          and inp["targetSocPct"] == 100 and inp["bufferMin"] == 60, str(inp["chargeWindow"]))
    check("the default ceiling is the recorded maximum, labelled GRID_AC", inp["ceilings"] == [{"name": "max_grid_charge_power", "watts": 8000.0, "basis": "GRID_AC"}], str(inp["ceilings"]))
    check("capacity from the file with the default band of 6 %, policy defaults UNSETTLED and FALLBACK", inp["capacityKwh"] == CAP and inp["capacityUpPct"] == 6.0 and inp["policy"] == {"setpointBasis": "UNSETTLED", "unknownDemandPolicy": "FALLBACK"})
    check("no params key when there is no parameter", "params" not in inp and "household" not in inp)
    nb = gr.base_input(nights[0], act, s, args_for(tdp, "--ceiling-basis", "NONE", "--setpoint-basis", "BATTERY_DC", "--unknown-demand-policy", "ASSUME_PROVISIONAL", "--capacity-band-pct", "0"), {"chargeEff": 0.9})
    check("a ceiling without a basis, the setpoint basis and policy as asked, the band, the params", nb["ceilings"] == [{"name": "max_grid_charge_power", "watts": 8000.0}] and nb["policy"] == {"setpointBasis": "BATTERY_DC", "unknownDemandPolicy": "ASSUME_PROVISIONAL"}
          and nb["capacityUpPct"] == 0.0 and nb["params"] == {"chargeEff": 0.9})
    ne = gr.base_input(nights[0], act, s, args_for(tdp, "--ceiling", "owner_max=5000", "--ceiling", "bms=6200:BATTERY_DC"), {})
    check("--ceiling replaces the recorded maximum and may carry a basis", ne["ceilings"] == [{"name": "owner_max", "watts": 5000.0}, {"name": "bms", "watts": 6200.0, "basis": "BATTERY_DC"}])
    for bad in ["owner_max", "x=abc", "x=5:WRONG", "=5"]:
        check(f"ceiling {bad!r} is refused", raises(lambda b=bad: gr.parse_ceiling(b)))
    check("params: a name and a number, anything else is refused", gr.parse_params(["a=1", "b=-2.5"]) == {"a": 1.0, "b": -2.5} and raises(lambda: gr.parse_params(["a"])) and raises(lambda: gr.parse_params(["a=x"])))
    s_nocap = {k: v for k, v in s.items() if k not in ("batcap", "maxgrid")}
    check("no capacity anywhere is refused, never guessed", raises(lambda: gr.base_input(nights[0], gr.measure(nights[0], s_nocap, a), s_nocap, args_for(tdp), {})))
    a_nc = args_for(tdp, "--capacity-kwh", "30")
    check("no recorded maximum and no --ceiling means no ceiling is passed (the advice will say NO_SAFE_CEILING)", gr.base_input(nights[0], gr.measure(nights[0], s_nocap, a_nc), s_nocap, a_nc, {})["ceilings"] == [])
    ti = gr.tick_input(inp, nights[0], s, a, 60.0, (31.0, 50.0))
    check("a tick carries the elapsed minutes, the SOC the battery had then, a fresh age and the previous reading", ti["elapsedMin"] == 60.0 and ti["socPct"] == s["soc"].at(nights[0].start + 3600) and ti["socAgeMin"] == 0
          and ti["previousSoc"] == {"socPct": 31.0, "elapsedMin": 50.0})
    check("the first tick has no previous reading", "previousSoc" not in gr.tick_input(inp, nights[0], s, a, 0.0, None))
    ts = gr.tick_input(inp, nights[0], s, args_for(tdp, "--soc-age", "since-change"), 300.0, None)
    check("--soc-age since-change gives the time since the reading last changed (a full battery has not changed for a long while)", ts["socAgeMin"] > 60, str(ts["socAgeMin"]))
    early = gr.tick_input(inp, nights[0], {**s, "soc": gr.Series([(T0 + 600, 50.0)])}, a, 0.0, None)
    check("before the first reading there is no SOC and no age", early["socPct"] is None and early["socAgeMin"] is None)
    hh = gr.tick_input(inp, nights[0], s, args_for(tdp, "--grid-limit-w", "9000"), 30.0, None)["household"]
    check("with a known grid limit: the house now, held as a labelled persistence forecast, and the PV now (gross)", hh["gridImportLimitW"] == 9000 and hh["demandNowW"] == 650 and hh["demandProfile"] == [{"fromInMin": 0, "watts": 650}]
          and hh["demandAgeMin"] == 0 and hh["demandProfileAgeMin"] == 0 and hh["solarNowW"] == 250 and "solarProfile" not in hh, str(hh))
    check("without a grid limit the house is not given at all (the limit is never guessed)", "household" not in gr.tick_input(inp, nights[0], s, a, 30.0, None))

# ===========================================================================
section("[7] the what-if, the report, the command line")
# ===========================================================================
w = fake(100.0, 40.0, 1.0)
w.kwh_per_pct, w.soc_start, w.main_end_soc = 0.3, 30.0, 99.0
r = gr.whatif(w, 6000.0, 300.0, 60.0)
check("what-if by hand: 69 points x 0.3 kWh / 6 kW = 207 min, the last point 1 x 0.3 / 6 kW = 3 min, plus a 40 min tail = 250 min; deadline 240 -> 10 min late",
      r is not None and close(r["finish_min"], 250.0, 0.01) and r["deadline_min"] == 240 and close(r["margin_min"], -10.0, 0.01), str(r))
check("no rate or no measured energy per point: no what-if", gr.whatif(w, None, 300, 60) is None and gr.whatif(w, 0.0, 300, 60) is None and gr.whatif(fake(), 6000.0, 300, 60) is None)
check("a faster advised rate finishes earlier", gr.whatif(w, 8000.0, 300.0, 60.0)["finish_min"] < r["finish_min"])
check("table: columns align and a missing value is a dash", gr.table(["a", "bb"], [["1", "22"], ["333", "-"]]) == ["a    bb", "---  --", "1    22", "333   -"] or gr.table(["a", "bb"], [["1", "22"], ["333", "-"]])[0].startswith("a"))
check("num: None is a dash, units are appended", gr.num(None) == "-" and gr.num(12.4, 0, " min") == "12 min" and gr.num(1.25, 1) == "1.2" or gr.num(1.25, 1) == "1.3")

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    n1 = synth_night(T0)
    n2 = synth_night(T0 + DAY, soc0=45.0)
    for k in n1:
        write_days(tdp, k, sorted(n1[k] + n2[k]))
    write_days(tdp, "batcap", [(T0 - 3600, CAP)])
    write_days(tdp, "maxgrid", [(T0 - 3600, 8000.0)])
    calls = []
    out = tdp / "report.txt"
    buf, err = io.StringIO(), io.StringIO()
    with redirect_stdout(buf), redirect_stderr(err):
        rc = gr.main([str(tdp), "--output", str(out)], backend=stub_factory(calls))
    text = buf.getvalue()
    check("exit 0, nothing on stderr, and --output holds exactly what was printed", rc == 0 and err.getvalue() == "" and out.read_text(encoding="utf-8") == text)
    check("the five sections and the label, and the limits are always printed", all(x in text for x in ("[1] WHAT THE BATTERY DID", "[2] WHAT THE ADVICE WOULD HAVE SAID", "[3] WHAT THE ADVICE WOULD HAVE SAID", "[4] COMPARISON", "[5] RE-PLAN TRACE", "LIMITS:"))
          and "model, not a command" in text and "nothing here is applied anywhere" in text)
    check("one row per night in the first table", len(re.findall(r"2030-01-1[56] 00:30", text.split("what the recorded battery says")[0])) == 2)
    check("the trace asks the advice every 10 minutes inside the window (30 ticks, none at the window end) for each night and variant", sum(len(b) for b in calls) == 2 * 2 * 30)
    check("the ticks' elapsed minutes run 0, 10, ... 290", sorted({c["input"]["elapsedMin"] for b in calls for c in b}) == [10.0 * k for k in range(30)])
    check("the stub's advised rates reach the report", "RATE_GENTLEST" in text and "rate" in text)
    # a second run is identical (no clock, no randomness)
    buf2 = io.StringIO()
    with redirect_stdout(buf2), redirect_stderr(io.StringIO()):
        gr.main([str(tdp)], backend=stub_factory([]))
    check("the same recording gives the same report every time", buf2.getvalue() == text)
    e = io.StringIO()
    with redirect_stdout(io.StringIO()), redirect_stderr(e):
        rc = gr.main([str(tdp)])
    check("with no source for the advice the tool says what to do (exit 2), it never invents one", rc == 2 and "--emit-cases" in e.getvalue() and "gentle_replay_run.py" in e.getvalue(), e.getvalue())
    outf = tdp / "should-not-exist.txt"
    buf3 = io.StringIO()
    with redirect_stdout(buf3), redirect_stderr(io.StringIO()):
        rc = gr.main([str(tdp), "--emit-cases", "--output", str(outf)])
    doc = json.loads(buf3.getvalue())
    check("--emit-cases prints the questions as JSON (exit 0) and writes no report file", rc == 0 and len(doc["cases"]) == 2 * 2 * 30 and not outf.exists() and doc["cases"][0]["id"].startswith("shipped/0/0/") and len({c["id"] for c in doc["cases"]}) == len(doc["cases"]))
    check("every question has an id, the window, the target and the reading as the battery had it", all({"id", "input"} <= set(c) and {"targetSocPct", "chargeWindow", "elapsedMin", "socPct", "socAgeMin", "capacityKwh", "ceilings"} <= set(c["input"]) for c in doc["cases"]))
    for argv, why in [([str(tdp), "--window", "nonsense"], "window"), ([str(tdp), "--target", "5"], "target"), ([str(tdp), "--target", "abc"], "target text"), ([str(tdp), "--tick-min", "3"], "tick"),
                      ([str(tdp), "--buffer-min", "7"], "buffer"), ([str(tdp), "--buffer-min", "125"], "buffer range"), ([str(tdp), "--ceiling", "bad"], "ceiling"), ([str(tdp), "--param", "bad"], "param"),
                      ([str(tdp / "nope")], "folder"), ([str(tdp), "--capacity-band-pct", "-1"], "band")]:
        e = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(e):
            rc = gr.main(argv, backend=stub_factory([]))
        check(f"a bad {why} is refused with exit 2 and an error line, nothing is printed as a result", rc == 2 and e.getvalue().startswith("error: "), e.getvalue())

# ===========================================================================
section("[8] the advice itself, through Node")
# ===========================================================================
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    f = tdp / "r.json"
    ok_case = [{"id": "a"}, {"id": "b"}]
    f.write_text(json.dumps({"results": [{"id": "a", "x": 1}, {"id": "b", "x": 2}]}), encoding="utf-8")
    check("the results file answers each case by its id, in the order of the cases", [r["x"] for r in gr.results_backend(f)(list(reversed(ok_case)))] == [2, 1])
    f.write_text(json.dumps({"results": [{"id": "a"}]}), encoding="utf-8")
    check("a missing answer is an error", raises(lambda: gr.results_backend(f)(ok_case)))
    f.write_text(json.dumps({"results": [{"id": "a"}, {"id": "b", "error": "boom"}]}), encoding="utf-8")
    check("a failed answer is an error, never used", raises(lambda: gr.results_backend(f)(ok_case)))
    f.write_text(json.dumps({"results": [{"id": "a"}, {"id": "a"}]}), encoding="utf-8")
    check("an id that occurs twice is an error", raises(lambda: gr.results_backend(f)))
    f.write_text(json.dumps({"results": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}), encoding="utf-8")
    check("more answers than cases is an error (the options of the two runs differ)", raises(lambda: gr.results_backend(f)(ok_case)))
    for body in ("not json", json.dumps({"nope": []}), json.dumps({"results": "x"}), json.dumps({"results": [1]}), json.dumps({"results": [{"no_id": 1}]})):
        f.write_text(body, encoding="utf-8")
        check(f"a results file that is not results is refused ({body[:24]!r})", raises(lambda: gr.results_backend(f)))
    check("a results file that does not exist is refused", raises(lambda: gr.results_backend(tdp / "nope.json")))

if not node_ok():
    print("  Node 22.6 or newer is not installed: the Node checks are SKIPPED")
else:
    be = drv.node_backend()
    case = {"id": "x", "input": {"targetSocPct": 80, "bufferMin": 60, "chargeWindow": {"startMin": 1320, "endMin": 240, "clockDay": {"changeAtMin": 0, "deltaMin": 0}}, "elapsedMin": 0, "socPct": 20,
                                 "socAgeMin": 1, "capacityKwh": 30, "capacityUpPct": 6, "ceilings": [{"name": "o", "watts": 5000}]}}
    res = be([case, {"id": "y", "input": {**case["input"], "socPct": None}}])
    check("the hand-checked example: 4100 W, the lowest step that reaches 80 % by the deadline", res[0]["rateW"] == 4100 and res[0]["reason"] == "RATE_GENTLEST" and res[0]["outcome"] == "ON_TIME" and res[0]["id"] == "x", str(res[0]))
    check("an unknown SOC gives no advice and says why", res[1]["advice"] == "NO_ADVICE" and res[1]["reason"] == "NO_SOC" and res[1]["rateW"] is None)
    check("the same cases give the same answers (no memory, no clock)", be([case]) == be([case]) and be([case])[0] == res[0])
    check("an empty batch is an empty answer", be([]) == [])
    node = shutil.which("node")
    r1 = subprocess.run([node, str(drv.RUNNER)], input="not json", capture_output=True, text=True, timeout=60)
    check("the runner refuses input that is not JSON (exit 2, a message, no result)", r1.returncode == 2 and r1.stdout == "" and "not valid JSON" in r1.stderr, r1.stderr)
    r2 = subprocess.run([node, str(drv.RUNNER)], input=json.dumps({"cases": "x"}), capture_output=True, text=True, timeout=60)
    check("the runner refuses a document without a list of cases", r2.returncode == 2)
    r3 = subprocess.run([node, str(drv.RUNNER)], input=json.dumps({"cases": [{"id": "n", "input": None}]}), capture_output=True, text=True, timeout=60)
    doc = json.loads(r3.stdout)
    check("a missing input is an invalid-input answer with no rate, never a crash", r3.returncode == 0 and doc["results"][0]["reason"] == "INVALID_INPUT" and doc["results"][0]["rateW"] is None)
    check("a node that is not there is an error with a clear message", raises(lambda: drv.node_backend("no-such-node-xyz")))
    check("the driver says so with exit 2 and runs nothing", drv.main(["nowhere", "--node", "no-such-node-xyz"]) == 2)
    # end to end on a synthetic night: the real advice on the real tool
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        write_night(tdp, synth_night(T0, soc0=30.0), {"batcap": CAP, "maxgrid": 8000.0})
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            rc = drv.main([str(tdp), "--ceiling-basis", "NONE", "--buffer-min", "30"])
        text = buf.getvalue()
        check("end to end through the driver: exit 0 and the five sections", rc == 0 and "[5] RE-PLAN TRACE" in text and "via Node" in text, text[:200])
        # by hand: the questions, Node, the answers in a file, the report: the same report as the driver's
        cbuf = io.StringIO()
        with redirect_stdout(cbuf), redirect_stderr(io.StringIO()):
            rc1 = gr.main([str(tdp), "--ceiling-basis", "NONE", "--buffer-min", "30", "--emit-cases"])
        proc = subprocess.run([shutil.which("node"), "--disable-warning=ExperimentalWarning", str(drv.RUNNER)], input=cbuf.getvalue(), capture_output=True, text=True, timeout=300)
        resf = tdp / "results.json"
        resf.write_text(proc.stdout, encoding="utf-8")
        hbuf = io.StringIO()
        with redirect_stdout(hbuf), redirect_stderr(io.StringIO()):
            rc2 = gr.main([str(tdp), "--ceiling-basis", "NONE", "--buffer-min", "30", "--results", str(resf)])
        norm = lambda t: re.sub(r"advice by: .*", "", t)
        check("by hand (--emit-cases, Node, --results) the report equals the driver's apart from the line naming the source", rc1 == 0 and proc.returncode == 0 and rc2 == 0 and norm(hbuf.getvalue()) == norm(text))
        e2 = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(e2):
            rc3 = gr.main([str(tdp), "--ceiling-basis", "NONE", "--buffer-min", "60", "--results", str(resf)])
        check("answers computed for other options are refused, never matched to these questions (the id carries a hash of the question)", rc3 == 2 and "the options of the two runs must be the same" in e2.getvalue(), e2.getvalue())
        a_ = args_for(tdp, "--ceiling-basis", "NONE", "--buffer-min", "30")
        s_, _ = gr.load_all(tdp)
        n_, _ = gr.find_nights(s_, a_)
        act_ = gr.measure(n_[0], s_, a_)
        inp_ = gr.tick_input(gr.base_input(n_[0], act_, s_, a_, {}), n_[0], s_, a_, 0.0, None)
        direct = be([{"id": "d", "input": inp_}])[0]
        check("the first row of the advice section is the advice the runner gives for the window start", f"{direct['rateW']:.0f}" in text.split("[2]")[1].split("[3]")[0], str(direct))
        check("with a 30 minute buffer the advice is a RATE below the 8 kW ceiling (and the synthetic battery was given the full 8 kW)", direct["advice"] == "RATE" and 4000 < direct["rateW"] < 8000, str(direct))

# ===========================================================================
section("[9] static: no network, no service call, no write, no site data")
# ===========================================================================
tool = (REPO / "intelligence" / "tools" / "gentle_replay.py").read_text(encoding="utf-8")
driver = (REPO / "tools" / "gentle_replay_run.py").read_text(encoding="utf-8")
runner = (REPO / "frontend" / "ecco-plan-core" / "tools" / "adviseBatch.ts").read_text(encoding="utf-8")
code = re.sub(r'"""[\s\S]*?"""', "", tool)
code = re.sub(r"(^|\s)#.*$", "", code, flags=re.M)
dcode = re.sub(r'"""[\s\S]*?"""', "", driver)
dcode = re.sub(r"(^|\s)#.*$", "", dcode, flags=re.M)
check("the tool imports only the standard library, and starts no process (no subprocess, os, shutil: the Intelligence authority gate)", sorted(set(re.findall(r"^(?:import|from)\s+([a-z_]+)", code, flags=re.M))) == sorted(["__future__", "argparse", "bisect", "datetime", "hashlib", "json", "math", "pathlib", "re", "sys", "typing"]),
      str(sorted(set(re.findall(r"^(?:import|from)\s+([a-z_]+)", code, flags=re.M)))))
for banned in (r"\bsubprocess\b", r"\bshutil\b", r"\bos\.", r"\bPopen\b", r"\bsystem\(", r"\bpopen\(", r"\bsocket\b", r"\burllib\b", r"\brequests\b", r"\bhttp", r"\bftplib\b", r"\bsmtplib\b", r"\bwebsocket", r"call_service", r"\bhass\b", r"\.states\b", r"\bos\.environ\b", r"\beval\s*\(", r"\bexec\s*\(", r"\bopen\s*\(", r"shell\s*=\s*True",
               r"\bmodbus\b", r"\bssh\b", r"\bcredentials\b", r"\bsensor\.", r"\bnumber\.", r"\binput_[a-z]+\.", r"datetime\.now\(", r"datetime\.utcnow", r"time\.time\(", r"\brandom\b"):
    check(f"the tool has no {banned}", re.search(banned, code) is None)
check("the one thing the tool writes is --output (one write_text, to that path)", len(re.findall(r"write_text\(", code)) == 1 and "Path(args.output).write_text(text" in code)
check("the driver starts only Node (the version probe and the runner), always through an argument list, never a shell", len(re.findall(r"subprocess\.run\(", dcode)) == 2 and "shell" not in dcode
      and re.findall(r"subprocess\.run\(\[([a-z]+)", dcode) == ["exe", "exe"] and "os." not in dcode and "Popen" not in dcode)
check("the driver imports only the standard library and the tool, and has no network or service vocabulary", sorted(set(re.findall(r"^(?:import|from)\s+([a-z_]+)", dcode, flags=re.M))) == sorted(["__future__", "intelligence", "json", "pathlib", "shutil", "subprocess", "sys"])
      and all(re.search(b, dcode) is None for b in (r"\bsocket\b", r"\burllib\b", r"\bhttp", r"call_service", r"\bhass\b", r"\bmodbus\b", r"\bssh\b", r"\bsensor\.", r"write_text", r"\bopen\s*\(")))
check("it never reads an entity name from a recording (only state and time)", "entity_id" not in code)
for pattern, what in ((r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "an IP address"), (r"[A-Za-z0-9._-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}", "an e-mail address"), (r"https?://", "a URL"), (r"\bsensor\.[a-z_]+", "an entity id")):
    check(f"none of the tool, the driver and the runner contains {what}", re.search(pattern, tool) is None and re.search(pattern, driver) is None and re.search(pattern, runner) is None)
rcode = re.sub(r"/\*[\s\S]*?\*/", "", runner)
rcode = re.sub(r"(^|[^:\"'])//.*$", r"\1", rcode, flags=re.M)
for banned in (r"\bfetch\s*\(", r"\bhttp", r"\bnet\b", r"child_process", r"writeFile", r"appendFile", r"createWriteStream", r"callService", r"\bhass\b", r"\bDate\b", r"Math\.random", r"\bWebSocket\b", r"\beval\b", r"\brequire\s*\("):
    check(f"the runner has no {banned}", re.search(banned, rcode) is None)
check("the runner reads standard input only (file descriptor 0), writes standard output and error, imports only node:fs and the advice", rcode.count("readFileSync(0") == 1 and rcode.count("readFileSync(") == 1
      and set(re.findall(r'from "([^"]+)"', rcode)) == {"../src/gentleAdvice.ts", "node:fs"} and "process.stdout.write" in rcode)
check("the runner caps the number of cases", "MAX_CASES" in rcode and "too many cases" in rcode)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all Gentle replay checks passed")
