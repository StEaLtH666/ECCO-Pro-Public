#!/usr/bin/env python3
"""intelligence/tools/power_balance_fit.py: the offline fit of the inverter conversion from a recorded history (synthetic
round-number data only; no site value). The synthetic inverter: DC to AC 0.90, AC to DC 0.92, standby 40 W.

  [1] the engine's own rule judges the history (the tool calls quality.power_balance_verdict), and the tool is stdlib only
      and writes nothing
  [2] the generic CSV: the fit recovers the synthetic inverter (exactly without noise, closely with it), the loss-aware rule
      accepts the history and the lossless rule does not, the fault-injection table, the hold-out, the proposed facts are
      inside the bounds
  [3] the Home Assistant history adapter reads the same history to the same samples as the CSV (a state is held until it
      changes; unavailable states are skipped and counted; a file with a byte-order mark reads)
  [4] fail closed: a missing column, a time without a zone, an unusable state, too many rows, a history that does not vary,
      a side with too few samples, a sign fault in the history, the bounds themselves, and the command line's exit codes
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import random
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.tools import power_balance_fit as fit  # noqa: E402

FAILURES: list[str] = []
TOOL = Path(fit.__file__)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


DC_AC, AC_DC, STANDBY = 0.90, 0.92, 40.0
CONV = sd.InverterConversion(DC_AC, AC_DC, STANDBY)
T0 = datetime(2030, 1, 10, tzinfo=timezone.utc).timestamp()
STEP = 60.0


def synth(days: int = 4, noise_w: float = 0.0, seed: int = 1) -> list[fit.Sample]:
    """days x 1440 one-minute samples of a synthetic house: PV in the day, a grid charge at night, PV charging at midday and an
    evening discharge; the grid reading follows from the synthetic inverter (house = grid + conversion), the house reading
    gets uniform noise of +-noise_w."""
    rng = random.Random(seed)
    out = []
    for i in range(days * 1440):
        hour = (i % 1440) / 60.0
        pv = max(0.0, 4000.0 * math.sin(math.pi * (hour - 7.0) / 10.0)) if 7.0 <= hour <= 17.0 else 0.0
        if 1.0 <= hour < 5.0:
            batt = -2000.0 + 150.0 * (hour - 1.0)                 # a grid charge that tapers, so the charge side varies
        elif 11.0 <= hour < 14.0:
            batt = -1500.0 + 100.0 * (hour - 11.0)
        elif 17.0 <= hour < 23.0:
            batt = 1500.0 + 100.0 * (hour - 17.0)
        else:
            batt = 0.0
        load = 300.0 + 80.0 * (hour % 5.0) + (700.0 if 17.0 <= hour < 22.0 else 0.0)
        d = pv + batt
        grid = load - (DC_AC * d if d >= 0 else d / AC_DC) + STANDBY
        out.append((T0 + i * STEP, load + (rng.uniform(-noise_w, noise_w) if noise_w else 0.0), pv, batt, grid))
    return out


def write_csv(path: Path, samples, header="timestamp,house_w,pv_w,battery_w,grid_w", fmt="z") -> None:
    lines = [header]
    for t, hw, p, b, g in samples:
        stamp = (datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if fmt == "z" else
                 datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") if fmt == "naive" else repr(t))
        lines.append(f"{stamp},{hw!r},{p!r},{b!r},{g!r}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_ha(dirpath: Path, samples, *, bom: bool = False, junk: bool = False) -> dict[str, list[str]]:
    """One Home Assistant history file per role per day (a list holding one series: the first object carries the entity id and
    attributes, the rest state and last_changed), recording only changes, as Home Assistant does."""
    files: dict[str, list[str]] = {r: [] for r in fit.ROLES}
    cols = {"house": 1, "pv": 2, "battery": 3, "grid": 4}
    days = sorted({int((s[0] - T0) // 86400) for s in samples})
    for role, idx in cols.items():
        for day in days:
            rows, last = [], None
            for s in samples:
                if int((s[0] - T0) // 86400) != day:
                    continue
                v = s[idx]
                if v == last:
                    continue
                last = v
                stamp = datetime.fromtimestamp(s[0], timezone.utc).isoformat()
                obj = {"state": repr(v), "last_changed": stamp}
                if not rows:
                    obj = {"entity_id": f"sensor.test_{role}", "state": repr(v), "attributes": {}, "last_changed": stamp,
                           "last_updated": stamp}
                rows.append(obj)
                if junk and len(rows) % 97 == 0:                      # the sensor drops out for ten seconds and comes back as it was
                    rows.append({"state": "unavailable", "last_changed": datetime.fromtimestamp(s[0] + 10.0, timezone.utc).isoformat()})
                    rows.append({"state": repr(v), "last_changed": datetime.fromtimestamp(s[0] + 20.0, timezone.utc).isoformat()})
            body = json.dumps([rows])
            p = dirpath / f"{role}-{day}.json"
            p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))
            files[role].append(str(p))
    return files


def refused_ha(series, needle: str) -> bool:
    try:
        fit.resample(series, 10.0, 100)
    except fit.FitError as exc:
        return needle in str(exc)
    return False


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = fit.main(argv)
    return rc, out.getvalue(), err.getvalue()


print("== [1] the engine's own rule judges the history; the tool is stdlib only and writes nothing")
check("the tool calls quality.power_balance_verdict itself (one rule, never a copy)", fit.power_balance_verdict is q.power_balance_verdict)
src = TOOL.read_text(encoding="utf-8")
tree = ast.parse(src)
mods = {n.module.split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom)) for a in (n.names if isinstance(n, ast.Import) else [None])
        if not (isinstance(n, ast.ImportFrom) and n.level)}
STDLIB = {"__future__", "argparse", "bisect", "csv", "glob", "json", "math", "sys", "datetime", "pathlib"}
check("only the standard library and this repository are imported", mods <= STDLIB | {"intelligence"}, str(sorted(mods - STDLIB)))
writes = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) in
          ("write", "write_text", "write_bytes", "writelines", "mkdir", "unlink", "rename", "remove", "rmdir", "touch")]
opens_w = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "open"
           and any(isinstance(a, ast.Constant) and isinstance(a.value, str) and set(a.value) & set("wax+") for a in
                   list(n.args[1:2]) + [k.value for k in n.keywords if k.arg == "mode"])]
check("it writes nothing (no write call, no file opened for writing)", not writes and not opens_w, str((writes, opens_w)))
check("every loop is bounded: no while loop in the tool", not [n.lineno for n in ast.walk(tree) if isinstance(n, ast.While)])

print("== [2] the generic CSV")
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    clean = synth(4, 0.0)
    write_csv(tdp / "clean.csv", clean)
    rc, out, err = run_main(["csv", "--file", str(tdp / "clean.csv")])
    check("the CSV run exits 0 and prints the four sections (a) to (d)", rc == 0 and not err and all(
        s in out for s in ("(a) FITTED PARAMETERS", "(b) SHARE OF SAMPLES", "(c) FAULT INJECTION", "(d) HOLD-OUT")), err or out[:200])
    samples, info = fit.read_csv(tdp / "clean.csv")
    check("every row is read, none skipped, in time order", len(samples) == len(clean) and info["rows_skipped"] == 0
          and all(samples[i][0] < samples[i + 1][0] for i in range(len(samples) - 1)))
    check("the values read back are the values written (repr round trip)", samples[1234][1:] == clean[1234][1:])
    j = fit.fit_joint(samples)
    pf = fit.proposed_facts(j)
    check("noise-free: the joint fit recovers the synthetic inverter (slopes 0.90 and 1/0.92, constant -40 W)",
          abs(j["a_pos"] - DC_AC) < 1e-9 and abs(j["a_neg"] - 1.0 / AC_DC) < 1e-9 and abs(j["c"] + STANDBY) < 1e-6, str(j))
    check("... and proposes exactly the synthetic facts, rounded as entered, inside the bounds",
          pf["facts"] == {"inverter_dc_to_ac_factor": 0.9, "inverter_ac_to_dc_factor": 0.92, "inverter_standby_w": 40} and not pf["problems"],
          str(pf))
    conv = fit.conversion_from(pf["facts"], pf["problems"])
    check("... a conversion the site facts would accept", conv == CONV and sd.inverter_conversion(type("F", (), pf["facts"])())[0] == CONV)
    la = fit.judge(samples, conv)
    lo = fit.judge(samples, sd.LOSSLESS_CONVERSION)
    check("the loss-aware rule accepts every sample, the lossless rule far fewer", la["ok_share"] == 1.0 and lo["ok_share"] < 0.7,
          f"{la['ok_share']} / {lo['ok_share']}")
    check("... the lossless counts are the engine's codes, and they add up", sum(lo["counts"].values()) == len(samples)
          and set(lo["counts"]) <= {"OK", "CT_SIGN_REVERSED", "BATTERY_SIGN_REVERSED", "POWER_BALANCE_INCONSISTENT"})
    e1 = fit.judge(samples, conv)["resid"]
    check("noise-free residuals are the rounding only (p1 to p99 within a hundredth of a watt)", all(abs(v) < 0.01 for v in e1.values()), str(e1))
    ct = fit.inject(samples, conv, "ct")
    ba = fit.inject(samples, conv, "batt")
    cur_ct = fit.inject(samples, sd.LOSSLESS_CONVERSION, "ct")
    check("fault injection, loss-aware: every reversal that matters is blocked (grid CT and battery), and so among the samples "
          "accepted before the fault", ct["n"] > 500 and ct["blocked"] == ct["n"] and ct["blocked_clean"] == ct["n_clean"] == ct["n"]
          and ba["n"] > 500 and ba["blocked"] == ba["n"] and ba["blocked_clean"] == ba["n_clean"] == ba["n"], str((ct, ba)))
    check("... the lossless rule blocks them too, but only because it blocks most samples anyway: few were accepted before the fault",
          cur_ct["blocked"] == cur_ct["n"] and cur_ct["n_clean"] < cur_ct["n"] * 0.7, str(cur_ct))
    stress = fit.inject(samples, fit.STRESS, "ct")
    check("the report row at the most generous bounds exists and counts the same samples", stress["n"] == ct["n"])
    first, second, how = fit.split_halves(samples)
    check("the hold-out split is by UTC day: the first two of four days first", len(first) == len(second) == 2 * 1440
          and first[-1][0] < second[0][0] and "2 of 4" in how, how)
    j1 = fit.fit_joint(first)
    c1 = fit.conversion_from(**{"facts": fit.proposed_facts(j1)["facts"], "problems": fit.proposed_facts(j1)["problems"]})
    check("fitted on the first part, the second part is accepted in full", c1 is not None and fit.judge(second, c1)["ok_share"] == 1.0)
    check("the printed report shows the proposed facts as the `site` keys and says they are not owner decisions",
          '"inverter_dc_to_ac_factor": 0.9' in out and '"inverter_standby_w": 40' in out and "not owner decisions" in out, out[:1500])
    check("... the loss-aware line reads 100.00 % and the current rule far less", "100.00 %" in out
          and any(line.strip().startswith("current rule (lossless)") and "100.00" not in line for line in out.splitlines()), out[:1500])

    noisy = synth(4, 30.0, seed=5)
    shuffled = ["GRID_W,Timestamp,extra,House_W,PV_W,Battery_W"] + [
        f"{g!r},{datetime.fromtimestamp(t, timezone.utc).isoformat()},x,{hw!r},{p!r},{b!r}" for t, hw, p, b, g in noisy[:500]]
    (tdp / "shuffled.csv").write_text(chr(10).join(shuffled) + chr(10), encoding="utf-8")
    rows_s, _info = fit.read_csv(tdp / "shuffled.csv")
    check("columns in another order, in any case, with an extra column, read to the same samples",
          [r[1:] for r in rows_s] == [s[1:] for s in noisy[:500]] and [r[0] for r in rows_s] == [s[0] for s in noisy[:500]])
    write_csv(tdp / "noisy.csv", noisy)
    sn, _ = fit.read_csv(tdp / "noisy.csv")
    jn = fit.fit_joint(sn)
    pn = fit.proposed_facts(jn)
    cn = fit.conversion_from(pn["facts"], pn["problems"])
    check("with +-30 W of house noise the fit is close (factors within 0.005, standby within 5 W) and the proposed facts are valid",
          abs(pn["facts"]["inverter_dc_to_ac_factor"] - DC_AC) < 0.005 and abs(pn["facts"]["inverter_ac_to_dc_factor"] - AC_DC) < 0.005
          and abs(pn["facts"]["inverter_standby_w"] - STANDBY) < 5 and cn is not None, str(pn))
    check("... the loss-aware rule accepts all of the noisy history (the noise is inside the tolerance) and the lossless rule does not",
          fit.judge(sn, cn)["ok_share"] > 0.999 and fit.judge(sn, sd.LOSSLESS_CONVERSION)["ok_share"] < 0.7)
    hs, hs2, _ = fit.split_halves(sn)
    ch = fit.conversion_from(**{"facts": fit.proposed_facts(fit.fit_joint(hs))["facts"], "problems": fit.proposed_facts(fit.fit_joint(hs))["problems"]})
    check("hold-out on the noisy history: fitted on the first half, the second half is accepted (above 99.9 %)",
          ch is not None and fit.judge(hs2, ch)["ok_share"] > 0.999)
    ctn = fit.inject(sn, cn, "ct")
    ban = fit.inject(sn, cn, "batt")
    check("... and the noisy history's reversals are all blocked", ctn["blocked"] == ctn["n"] > 500 and ban["blocked"] == ban["n"] > 500)
    ps = fit.fit_side([s for s in sn if s[2] + s[3] >= 0.0])
    check("the separate side fit gives the discharge slope too (close to 0.90, intercept near -40 W)",
          abs(ps["slope"] - DC_AC) < 0.005 and abs(ps["intercept"] + STANDBY) < 8, str(ps))

print("== [3] the Home Assistant history adapter")
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    base = synth(3, 25.0, seed=3)
    files = write_ha(tdp, base)
    series = {}
    for role in fit.ROLES:
        pts = []
        for f in files[role]:
            p, skipped = fit.read_ha_series(Path(f))
            pts += p
            check(f"{Path(f).name}: read without skips", skipped == 0)
        series[role] = pts
    grid, dropped = fit.resample(series, STEP, 10_000)
    check("a state is held until it changes: the resampled grid is exactly the samples that were recorded as changes",
          [s[1:] for s in grid] == [s[1:] for s in base] and [s[0] for s in grid] == [s[0] for s in base] and dropped == 0,
          f"{len(grid)} {len(base)} {dropped}")
    rc, out, err = run_main(["ha-history", "--step-s", "60"] + sum(([f"--{r}"] + files[r] for r in fit.ROLES), []))
    write_csv(tdp / "same.csv", base)
    rc2, out2, err2 = run_main(["csv", "--file", str(tdp / "same.csv")])
    body = lambda text: [ln for ln in text.splitlines() if not ln.startswith("source")]            # noqa: E731
    check("the same history through the adapter and through the CSV prints the same report (apart from the source line)",
          rc == rc2 == 0 and body(out) == body(out2) and not err and not err2, (err or err2)[:200])
    check("the adapter's source line counts the files and points", "home assistant history, 12 files" in out and "held on a 60 s grid" in out,
          out.splitlines()[1])
    # globs are expanded by the tool itself (a shell may not)
    rcg, outg, errg = run_main(["ha-history", "--step-s", "60"] + sum(([f"--{r}", str(tdp / f"{r}-*.json")] for r in fit.ROLES), []))
    check("glob patterns are expanded by the tool", rcg == 0 and body(outg) == body(out), errg[:200])

with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    base = synth(2, 0.0)
    files = write_ha(tdp, base, bom=True, junk=True)
    series, skipped_total = {}, 0
    for role in fit.ROLES:
        pts = []
        for f in files[role]:
            p, sk = fit.read_ha_series(Path(f))
            pts += p
            skipped_total += sk
        series[role] = pts
    check("a file with a byte-order mark reads; unavailable states are counted as gaps", skipped_total > 20, str(skipped_total))
    grid, dropped = fit.resample(series, STEP, 10_000)
    check("... a ten-second dropout between two grid points leaves the history as it was (no grid point is lost)",
          [s[1:] for s in grid] == [s[1:] for s in base] and dropped == 0, f"{len(grid)} {len(base)} {dropped}")
    gap = {"house": [(0.0, 1.0), (100.0, None), (200.0, 2.0)], "pv": [(0.0, 5.0)], "battery": [(0.0, 3.0)], "grid": [(0.0, 4.0)]}
    gsamples, gdropped = fit.resample(gap, 50.0, 100)
    check("a gap is not held across: the grid points inside it (100 and 150) are dropped and counted, the others keep their value",
          gdropped == 2 and [(s[0], s[1]) for s in gsamples] == [(0.0, 1.0), (50.0, 1.0), (200.0, 2.0)], str((gsamples, gdropped)))
    check("a series that is only gaps is refused", refused_ha({"house": [(0.0, None)], "pv": [(0.0, 1.0)], "battery": [(0.0, 1.0)],
                                                               "grid": [(0.0, 1.0)]}, needle="no numeric state for house"))

print("== [4] fail closed")
with tempfile.TemporaryDirectory() as td:
    tdp = Path(td)
    good = synth(2, 0.0)

    def refused(fn, *args, needle: str) -> bool:
        try:
            fn(*args)
        except fit.FitError as exc:
            return needle in str(exc)
        return False
    write_csv(tdp / "naive.csv", good, fmt="naive")
    check("times without a time zone are never read (every row skipped: no usable row)", refused(fit.read_csv, tdp / "naive.csv", needle="no usable row"))
    write_csv(tdp / "epoch.csv", good, fmt="epoch")
    check("seconds since the epoch are read", len(fit.read_csv(tdp / "epoch.csv")[0]) == len(good))
    (tdp / "missing.csv").write_text("timestamp,house_w,pv_w,battery_w\n2030-01-10T00:00:00Z,1,2,3\n", encoding="utf-8")
    check("a missing column is refused and named", refused(fit.read_csv, tdp / "missing.csv", needle="grid_w"))
    (tdp / "empty.csv").write_text("", encoding="utf-8")
    check("an empty file is refused", refused(fit.read_csv, tdp / "empty.csv", needle="empty"))
    (tdp / "bad.csv").write_text("timestamp,house_w,pv_w,battery_w,grid_w\n2030-01-10T00:00:00Z,x,2,3,4\n2030-01-10T00:01:00Z,1,nan,3,4\n"
                                 "2030-01-10T00:02:00Z,1,inf,3,4\n2030-01-10T00:03:00Z,1,2,3,4\n2030-01-10T00:04:00Z,5\n", encoding="utf-8")
    rows, info = fit.read_csv(tdp / "bad.csv")
    check("non-numeric, NaN, infinite and short rows are skipped and counted; the good row is read",
          len(rows) == 1 and info == {"rows_read": 5, "rows_skipped": 4}, str((rows, info)))
    check("more rows than the bound are refused, never cut", refused(fit.read_csv, tdp / "epoch.csv", 100, needle="bound"))
    check("a file that is not there is refused", refused(fit.read_csv, tdp / "nothing.csv", needle="not a file"))
    (tdp / "notjson.json").write_text("{not json", encoding="utf-8")
    check("a history file that is not JSON is refused with the exception type only", refused(fit.read_ha_series, tdp / "notjson.json", needle="not valid JSON"))
    (tdp / "obj.json").write_text('{"a": 1}', encoding="utf-8")
    check("a history file that is not a list of series is refused", refused(fit.read_ha_series, tdp / "obj.json", needle="not a list of series"))
    (tdp / "rec.json").write_text('[[1, 2]]', encoding="utf-8")
    check("a state record that is not an object is refused", refused(fit.read_ha_series, tdp / "rec.json", needle="not an object"))
    check("a grid larger than the bound is refused, never silently cut",
          refused(fit.resample, {r: [(0.0, 1.0), (1000.0, 1.0)] for r in fit.ROLES}, 1.0, 100, needle="exceed"))
    check("a step that is not positive is refused", refused(fit.resample, {r: [(0.0, 1.0)] for r in fit.ROLES}, 0.0, 100, needle="step")
          and refused(fit.resample, {r: [(0.0, 1.0)] for r in fit.ROLES}, float("nan"), 100, needle="step"))
    check("a role without a numeric state is refused", refused(fit.resample, {"house": [(0.0, 1.0)], "pv": [], "battery": [(0.0, 1.0)],
                                                                              "grid": [(0.0, 1.0)]}, 10.0, 100, needle="pv"))
    check("a series that starts later bounds the start of the grid: nothing is invented before it",
          fit.resample({"house": [(0.0, 1.0)], "pv": [(20.0, 1.0)], "battery": [(0.0, 1.0)], "grid": [(40.0, 1.0)]}, 10.0, 100)[0][0][0] == 40.0)
    const = [(T0 + i * STEP, 500.0, 0.0, 0.0, 500.0) for i in range(600)]
    check("a history that does not vary (constant net DC power) cannot be fitted and says so",
          refused(fit.fit_joint, const, needle="does not vary") or refused(fit.fit_side, const, needle="does not vary"))
    only_discharge = [s for s in synth(2, 0.0) if s[2] + s[3] >= 0.0]
    write_csv(tdp / "one_side.csv", only_discharge)
    rc, out, err = run_main(["csv", "--file", str(tdp / "one_side.csv")])
    check("a history with no charge side is reported (not fitted) and proposes no facts; the current rule is still judged",
          rc == 0 and "charge side" in out and "not fitted" in out and "no site facts are proposed" in out
          and "(b) SHARE OF SAMPLES" in out and "not evaluated (no usable proposed facts)" in out and '"inverter_' not in out, out[:1200])
    for every, label in ((3, "a third"), (10, "a tenth")):
        faulty = [(t, hw, p, b, -g if i % every == 0 else g) for i, (t, hw, p, b, g) in enumerate(synth(4, 0.0))]
        write_csv(tdp / "faulty.csv", faulty)
        rc, out, err = run_main(["csv", "--file", str(tdp / "faulty.csv")])
        check(f"a history with the grid sign reversed in {label} of its samples: the fit lands outside the bounds, the report says NOT "
              "USABLE, proposes nothing to use and does not evaluate a loss-aware rule",
              rc == 0 and "NOT USABLE as site facts" in out and "not evaluated (no usable proposed facts)" in out, out[:1500])
    faulty = [(t, hw, p, b, -g if i % 50 == 0 else g) for i, (t, hw, p, b, g) in enumerate(synth(4, 0.0))]
    write_csv(tdp / "faulty.csv", faulty)
    rc, out, err = run_main(["csv", "--file", str(tdp / "faulty.csv")])
    check("a history with the grid sign reversed in 2 % of its samples still fits inside the bounds, but the loss-aware rule accepts "
          "under 99 % of it, and the report warns to review the history before using the facts",
          rc == 0 and "WARNING" in out and "review it before using these facts" in out and "NOT USABLE" not in out, out[:1500])
    outside = {"joint": {"a_pos": 0.80, "a_neg": 1.30, "c": -200.0}}
    pf = fit.proposed_facts(outside["joint"])
    check("fitted values outside the bounds are reported as not usable and never turned into facts",
          len(pf["problems"]) == 3 and fit.conversion_from(pf["facts"], pf["problems"]) is None, str(pf))
    pf2 = fit.proposed_facts({"a_pos": -0.1, "a_neg": 0.0, "c": 5.0})
    check("non-positive slopes are reported as not usable", fit.conversion_from(pf2["facts"], pf2["problems"]) is None and len(pf2["problems"]) >= 2)
    check("the bounds the tool uses are the engine's",
          fit.INVERTER_FACTOR_BOUNDS == sd.INVERTER_FACTOR_BOUNDS and fit.INVERTER_STANDBY_BOUNDS_W == sd.INVERTER_STANDBY_BOUNDS_W
          and fit.STRESS == sd.InverterConversion(0.85, 0.85, 150.0))
    rc, out, err = run_main(["csv", "--file", str(tdp / "nothing.csv")])
    check("the command line exits 2 on a refusal, with the reason on stderr and nothing on stdout", rc == 2 and out == "" and "not a file" in err)
    rc, out, err = run_main(["csv", "--file", str(tdp / "epoch.csv"), "--max-samples", "5"])
    check("... and for a bound that is too small to be meaningful", rc == 2 and "at least" in err)
    check("percentiles: the median of 1..5 is 3 and the interpolation is linear", fit.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
          and fit.percentile([0.0, 10.0], 0.25) == 2.5 and math.isnan(fit.percentile([], 0.5)))

    def raises(fn) -> bool:
        try:
            fn()
        except (ValueError, TypeError):
            return True
        return False
    check("parse_time: ISO with a zone, a Z suffix and seconds read; a bare date-time, junk, a bool and NaN do not",
          fit.parse_time("2030-01-10T00:00:00+00:00") == fit.parse_time("2030-01-10T00:00:00Z") == T0 == fit.parse_time(T0)
          and all(raises(lambda x=x: fit.parse_time(x)) for x in ("2030-01-10T00:00:00", "junk", True, float("nan"))))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all power-balance fit checks passed")
