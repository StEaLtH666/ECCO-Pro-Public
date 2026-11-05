#!/usr/bin/env python3
"""Data quality (dq): the offline capture validator intelligence/tools/validate_capture.py, on a synthetic capture
generated in a temporary directory at test time (fictional 2030; nothing is committed as a fixture).

  [1] a synthetic statistics CSV (and the same as .csv.gz) round-trips: hours, clock-change nights, energy balance,
      the I-D8 load-counter check and the replayed quality findings come back as aggregates
  [2] the summary holds aggregates only: its key tree is pinned to the expected schema (no extra key, no dict of more
      than a dozen numbers, no list of numbers), no per-hour series, and its size does not grow with the capture
  [3] --out is refused inside a git tree with a remote (plain .git directory and worktree .git file; any spelling git
      accepts: a capitalised section, the old [remote.<name>] form, config.worktree), inside one whose configuration
      includes other files, through a link or junction into such a tree or into this repository, and inside this
      repository; a git tree without a remote is accepted; nothing is written when refused; the banner is printed
  [4] the validator imports no network or process module and writes only its two summary files
  [5] the generated fixtures are fictional 2030 text, and no dq file carries a 13-digit number on a meter / mpan /
      octopus / parameters line
"""

from __future__ import annotations

import ast
import contextlib
import csv
import gzip
import io
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import validate_capture as vc  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import UTC, zone  # noqa: E402

FAILURES: list[str] = []
ROOT = Path(__file__).resolve().parents[2]
P = "sensor.fict2030_"
ENTS = {"load_energy": "load_energy", "pv_energy": "pv_energy", "imp_energy": "grid_import", "exp_energy": "grid_export",
        "chg_energy": "battery_charge", "dis_energy": "battery_discharge", "load_power": "load_power", "pv_power": "pv_power",
        "batt_power": "battery_power", "grid_power": "grid_power", "soc": "battery_soc"}
CUTOVER = datetime(2030, 10, 1, tzinfo=timezone.utc)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def profile() -> dict:
    return {"_comment": "fictional 2030 test profile", "site": {"pv_array_kwp": 6.0},
            "sources": [{"name": "dongle", "priority": 1, "entities": {k: {"id": P + v} for k, v in ENTS.items()}}],
            "forecasts": {"fict_day": {"id": P + "pv_forecast_today"}}}


def capture_rows(start: date, days: int, seed: int = 11) -> tuple[list[list], int]:
    """Long-format statistics rows (the exporter's columns) for a synthetic house: cumulative counters that balance,
    power means with a spread, SOC, and a day-ahead forecast at 06:00 local. Returns (rows, hours)."""
    cfg = SiteConfig(pv_array_kwp=6.0)
    hist = make_history(start, days, cfg, seed=seed)
    tz = zone(cfg.tz)
    cum = {k: 1000.0 for k in ("load", "pv", "imp", "exp", "chg", "dis")}
    rows = []
    day_pv: dict[date, float] = {}
    for s in sorted(hist.by_start):
        r = hist.by_start[s]
        load, pv = r.e["load"], r.e["pv"]
        e = {"load": load, "pv": pv, "imp": max(load - pv, 0.0), "exp": max(pv - load, 0.0), "chg": 0.0, "dis": 0.0}
        for k, v in e.items():
            cum[k] += v
        for k, name in (("load", "load_energy"), ("pv", "pv_energy"), ("imp", "grid_import"), ("exp", "grid_export"),
                        ("chg", "battery_charge"), ("dis", "battery_discharge")):
            rows.append([P + name, s, "", "", "", round(cum[k], 3), ""])
        for name, mean in (("load_power", load * 1000.0), ("pv_power", pv * 1000.0), ("battery_power", 0.0),
                           ("grid_power", (e["imp"] - e["exp"]) * 1000.0)):
            rows.append([P + name, s, round(mean, 1), round(mean * 0.8 - 1, 1), round(mean * 1.2 + 1, 1), "", ""])
        rows.append([P + "battery_soc", s, round(r.soc_mean or 0.0, 1), round((r.soc_mean or 0.0) - 1, 1),
                     round((r.soc_mean or 0.0) + 1, 1), "", ""])
        d = datetime.fromtimestamp(s, UTC).astimezone(tz).date()
        day_pv[d] = day_pv.get(d, 0.0) + pv
    for d, v in sorted(day_pv.items()):
        t = datetime(d.year, d.month, d.day, 6, tzinfo=tz).astimezone(UTC)
        rows.append([P + "pv_forecast_today", int(t.timestamp()), "", "", "", round(v * 1.1, 2), ""])
    return rows, len(hist)


def write_capture(folder: Path, start: date, days: int, gz: bool = False) -> tuple[Path, Path, int]:
    rows, hours = capture_rows(start, days)
    csv_path = folder / ("hist_hourly.csv.gz" if gz else "hist_hourly.csv")
    opener = (lambda p: gzip.open(p, "wt", newline="")) if gz else (lambda p: open(p, "w", newline="", encoding="utf-8"))
    with opener(csv_path) as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["statistic_id", "start_ts", "mean", "min", "max", "state", "sum"])
        w.writerows(rows)
    prof = folder / "site.local.json"
    prof.write_text(json.dumps(profile(), indent=1) + "\n", encoding="utf-8", newline="\n")
    return csv_path, prof, hours


def run(args: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = vc.main(args)
    return code, buf.getvalue()


CODE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+$")
DIST = {"n": None, "median": None, "p90": None}
SIDE = {"counter_vs_balance": DIST, "share_beyond_tolerance": None, "counter_vs_power_integral": DIST, "exporting_hours": None,
        "share_zero_while_exporting": None}
FIELD = {"hours_with_value": None, "coverage": None, "flags": "flags"}
# the whole summary, key by key: None = a leaf (a number, text, bool or null); a dict = its exact keys (a key may be
# optional only where listed in OPTIONAL); "codes" = finding codes -> {severity, instants}; "fields" = history fields;
# "flags" = history flag names -> counts; "nights" = the clock-change night rows
SCHEMA = {
    "banner": None, "schema": None, "tool_version": None, "quality_version": None, "backtest": None,
    "input": {"sha256": None, "bytes": None, "rows": None, "statistic_ids": None},
    "profile": {"sources": None, "forecast_series": None},
    "audit": {"first_utc": None, "last_utc": None, "hours_expected": None, "hours_present": None, "hours_missing": None,
              "missing_run_count": None, "longest_missing_run_h": None, "fields": "fields", "soc_hours": None,
              "soc_suspect_hours": None, "soc_jump_hours": None, "load_power_stale_hours": None, "days_span": None,
              "hours": None},
    "energy_balance": {"balanced": None, "balanced_only_swapped": None, "unbalanced": None, "distinguishable": None,
                       "distinguishable_only_swapped": None, "ct_reversed": None},
    "counter_faults": {"stall_hours": None, "catchup_hours": None},
    "dropouts": {"runs": None, "longest_h": None, "days_with_repeated_dropouts": None},
    "dst_nights": "nights",
    "load_counter_check": {"status": None, "why": None, "cutover_date": None, "before": SIDE, "after": SIDE},
    "replay": {"instants": None, "step_days": None, "replay_hour_local": None, "decisions": None, "codes": "codes"},
    "thresholds": "thresholds",
}
OPTIONAL = {"audit": set(SCHEMA["audit"]), "load_counter_check": {"why", "cutover_date", "before", "after"},
            "dropouts": {"longest_h", "days_with_repeated_dropouts"}, "replay": {"step_days", "replay_hour_local", "decisions"}}


def schema_problems(v, spec, path="") -> list[str]:
    """Where the summary leaves the pinned schema (an unexpected key, a missing one, a container where a leaf belongs)."""
    out: list[str] = []
    if spec is None:
        if isinstance(v, (dict, list)):
            out.append(f"{path}: a container where a single value belongs")
        return out
    if spec == "thresholds":
        import dataclasses
        names = {f.name for f in dataclasses.fields(vc.DQ_PROPOSED)}
        if not isinstance(v, dict) or set(v) != names or any(isinstance(x, (dict, list)) for x in v.values()):
            out.append(f"{path}: not exactly the PROPOSED thresholds")
        return out
    if spec == "codes":
        if not isinstance(v, dict):
            return [f"{path}: not a mapping"]
        for k, x in v.items():
            if not CODE_KEY.match(k) or not isinstance(x, dict) or set(x) != {"severity", "instants"}:
                out.append(f"{path}.{k}: not a finding-code row")
        return out
    if spec == "fields":
        if not isinstance(v, dict) or not set(v) <= set(vc.ENERGY_FIELDS):
            return [f"{path}: not the history fields"]
        for k, x in v.items():
            out += schema_problems(x, FIELD, f"{path}.{k}")
        return out
    if spec == "flags":
        if not isinstance(v, dict) or len(v) > 12 or any(not isinstance(x, int) for x in v.values()):
            out.append(f"{path}: not a small flag count table")
        return out
    if spec == "nights":
        if not isinstance(v, list) or len(v) > 12 or any(not isinstance(x, dict) or set(x) != {"date", "kind", "hours_expected",
                                                                                              "hours_present"} for x in v):
            out.append(f"{path}: not the clock-change night rows")
        return out
    if not isinstance(v, dict):
        return [f"{path}: not a mapping"]
    opt = OPTIONAL.get(path.lstrip("."), set())
    for k in v:
        if k not in spec:
            out.append(f"{path}.{k}: a key the schema does not have")
    for k in spec:
        if k not in v and k not in opt:
            out.append(f"{path}.{k}: missing")
    for k, x in v.items():
        if k in spec:
            out += schema_problems(x, spec[k], f"{path}.{k}")
    return out


def numeric_dicts(v, path="", skip=("thresholds",)) -> list[tuple[str, int]]:
    """(path, number of numeric values directly inside) of every dict (outside the thresholds)."""
    out = []
    if isinstance(v, dict):
        n = sum(1 for x in v.values() if isinstance(x, (int, float)) and not isinstance(x, bool))
        out.append((path, n))
        for k, x in v.items():
            if k not in skip:
                out += numeric_dicts(x, f"{path}.{k}", skip)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            out += numeric_dicts(x, f"{path}[{i}]", skip)
    return out


def make_link(link: Path, target: Path) -> bool:
    """A directory symlink, or on Windows a junction when symlinks need a privilege. False when neither can be made."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    try:
        import _winapi  # Windows only
        _winapi.CreateJunction(str(target), str(link))
        return True
    except (ImportError, OSError, AttributeError):
        return False


def drop_link(link: Path) -> None:
    """Remove a link or junction, never what it points to."""
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)


def lists_in(v, path="") -> list[tuple[str, int, bool]]:
    """(path, length, all-numeric) of every list inside v."""
    out = []
    if isinstance(v, dict):
        for k, x in v.items():
            out += lists_in(x, f"{path}.{k}")
    elif isinstance(v, list):
        out.append((path, len(v), bool(v) and all(isinstance(x, (int, float)) for x in v)))
        for i, x in enumerate(v):
            out += lists_in(x, f"{path}[{i}]")
    return out


with tempfile.TemporaryDirectory(prefix="ecco_dq_capture_") as td:
    tmp = Path(td)
    print("== [1] round trip on a synthetic capture")
    (tmp / "in").mkdir()
    csv_path, prof_path, hours = write_capture(tmp / "in", date(2030, 9, 15), 60)
    code, out = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(tmp / "out"),
                     "--cutover", CUTOVER.isoformat()])
    check("the validator exits 0 and prints the banner", code == 0 and vc.BANNER in out, out[-300:])
    sj = json.loads((tmp / "out" / vc.SUMMARY_JSON).read_text(encoding="utf-8"))
    st = (tmp / "out" / vc.SUMMARY_TXT).read_text(encoding="utf-8")
    check("the JSON and text summaries carry the banner", sj.get("banner") == vc.BANNER and st.startswith(vc.BANNER)
          and st.rstrip().endswith(vc.BANNER))
    a = sj["audit"]
    check(f"every generated hour comes back ({hours})", a["hours_present"] == hours and a["hours_missing"] == 0, str(a)[:200])
    check("the autumn clock-change night of 2030 is listed with its 25 hours present",
          any(n["date"] == "2030-10-27" and n["kind"] == "AUTUMN_BACK" and n["hours_expected"] == 25 and n["hours_present"] == 25
              for n in sj["dst_nights"]), str(sj["dst_nights"]))
    eb = sj["energy_balance"]
    check("the balanced counters balance, and no CT reversal is reported", eb["balanced"] > 0 and eb["ct_reversed"] is False
          and eb["balanced_only_swapped"] == 0, str(eb))
    check("... the share rule's own counts are reported too: the hours in which import and export can be told apart, and "
          "those of them that balance only swapped (none here), in the JSON and the text summary",
          0 < eb["distinguishable"] <= eb["balanced"] + eb["balanced_only_swapped"] + eb["unbalanced"]
          and eb.get("distinguishable_only_swapped") == 0
          and f"{eb['distinguishable']} with import and export told apart, 0 of them only swapped" in st, str(eb))
    lc = sj["load_counter_check"]
    check("the I-D8 load-counter check runs before and after the cut-over and finds the counter consistent",
          lc["status"] == "RUN" and lc["before"]["counter_vs_balance"]["n"] > 0 and lc["after"]["counter_vs_balance"]["n"] > 0
          and lc["before"]["counter_vs_balance"]["p90"] < 0.05 and lc["after"]["share_beyond_tolerance"] == 0.0, str(lc)[:300])
    rp = sj["replay"]
    check("replayed snapshots are assessed (counts per finding code; decisions all OPEN)", rp["instants"] >= 4
          and "LIVENESS_MISSING" in rp["codes"] and rp["decisions"].startswith("all OPEN"), str(rp)[:200])
    check("the advice backtest is marked PENDING: it needs DP-1, defined where it is used (the owner's decision on the "
          "source of each decided input; OPEN), and a capture with the TOU and tariff readings (A45, R9D-3)",
          sj["backtest"] == "PENDING: needs DP-1 (the owner's decision on the source of each decided input; OPEN) and "
                            "a capture with the TOU and tariff readings at each issue time", sj["backtest"])
    check("the counter-fault and dropout counts are zero on a clean capture", sj["counter_faults"] == {"stall_hours": 0, "catchup_hours": 0}
          and sj["dropouts"]["runs"] == 0)
    (tmp / "gz").mkdir()
    gz_path, gz_prof, _ = write_capture(tmp / "gz", date(2030, 9, 15), 60, gz=True)
    code_gz, _o = run(["--hourly", str(gz_path), "--profile", str(gz_prof), "--out", str(tmp / "out_gz"), "--cutover", CUTOVER.isoformat()])
    sgz = json.loads((tmp / "out_gz" / vc.SUMMARY_JSON).read_text(encoding="utf-8"))
    strip = lambda d: {k: v for k, v in d.items() if k != "input"}  # noqa: E731
    check("the same capture as .csv.gz gives the same summary (apart from the input hash and size)",
          code_gz == 0 and strip(sgz) == strip(sj) and sgz["input"]["rows"] == sj["input"]["rows"])
    code_nc, _o = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(tmp / "out_nc")])
    snc = json.loads((tmp / "out_nc" / vc.SUMMARY_JSON).read_text(encoding="utf-8"))
    check("without --cutover the load-counter check is NOT_RUN", code_nc == 0 and snc["load_counter_check"]["status"] == "NOT_RUN")

    print("== [2] aggregates only")
    probs = schema_problems(sj, SCHEMA) + schema_problems(snc, SCHEMA)
    check("the summary's key tree is exactly the pinned schema (with and without --cutover)", not probs, str(probs[:4]))
    nd = [x for x in numeric_dicts(sj) if x[1] > 12]
    check("no dict outside the thresholds holds more than a dozen numbers (no per-hour series hidden in a mapping)", not nd,
          str(nd[:3]))
    leak = dict(sj)
    leak["recent"] = {f"h{i}": 0.5 + i / 100 for i in range(24)}
    check("... both checks see a per-hour series hidden in a mapping (a planted one is caught)",
          schema_problems(leak, SCHEMA) and [x for x in numeric_dicts(leak) if x[1] > 12])
    ls = lists_in(sj)
    check("no list in the summary is longer than a handful of entries", all(n <= 12 for _p, n, _num in ls), str([x for x in ls if x[1] > 12][:3]))
    check("no numeric list longer than three (no per-hour series)", all(n <= 3 for _p, n, num in ls if num), str([x for x in ls if x[2]][:3]))
    blob = json.dumps(sj)
    check("no hour-resolution timestamp anywhere in the JSON (dates only)", not re.search(r"\d{4}-\d\d-\d\dT\d\d:", blob))
    check("no hour-resolution timestamp in the text summary", not re.search(r"\d{4}-\d\d-\d\dT\d\d:", st))
    check("no per-entity statistic id leaks into the summary", P not in blob and P not in st)
    (tmp / "big").mkdir()
    bp, bprof, bhours = write_capture(tmp / "big", date(2030, 3, 1), 200)
    code_b, _o = run(["--hourly", str(bp), "--profile", str(bprof), "--out", str(tmp / "out_big"), "--cutover", CUTOVER.isoformat()])
    sb = (tmp / "out_big" / vc.SUMMARY_JSON).read_bytes()
    check(f"the summary stays small and does not grow with the capture ({len(blob)} vs {len(sb)} bytes for 60 vs 200 days)",
          code_b == 0 and len(sb) < 16384 and len(sb) < 1.5 * len(blob.encode()) + 2048)

    print("== [3] where the summary may go")
    remote = tmp / "clone"
    (remote / ".git").mkdir(parents=True)
    (remote / ".git" / "config").write_text('[core]\n\tbare = false\n[remote "origin"]\n\turl = https://example.invalid/x.git\n',
                                            encoding="utf-8")
    code_r, out_r = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(remote / "evidence" / "o")])
    check("--out inside a git tree whose config lists a remote: refused (exit 2), nothing written, banner printed",
          code_r == vc.EXIT_REFUSED and "REFUSED" in out_r and vc.BANNER in out_r and not (remote / "evidence").exists())
    common = tmp / "main" / ".git"
    (common / "worktrees" / "wt").mkdir(parents=True)
    (common / "config").write_text('[remote "origin"]\n\turl = https://example.invalid/y.git\n', encoding="utf-8")
    (common / "worktrees" / "wt" / "commondir").write_text("../..\n", encoding="utf-8")
    wt = tmp / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {common / 'worktrees' / 'wt'}\n", encoding="utf-8")
    code_w, _o = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(wt / "o")])
    check("--out inside a worktree whose common config lists a remote: refused", code_w == vc.EXIT_REFUSED and not (wt / "o").exists())
    local = tmp / "offline_like"
    (local / ".git").mkdir(parents=True)
    (local / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    code_l, _o = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(local / "evidence")])
    check("--out inside a local git tree with no remote: accepted", code_l == 0 and (local / "evidence" / vc.SUMMARY_JSON).exists())
    for target in (ROOT / "intelligence" / "_dq_out_never", ROOT):
        code_i, out_i = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(target)])
        check(f"--out inside this repository ({'a subfolder' if target != ROOT else 'its root'}): refused, nothing written",
              code_i == vc.EXIT_REFUSED and "inside this repository" in out_i and not (ROOT / "intelligence" / "_dq_out_never").exists())
    check("out_refusal names the reason for a remote and None for a plain folder",
          "remote" in (vc.out_refusal(remote / "x") or "") and vc.out_refusal(tmp / "plain" / "x") is None)
    spellings = {"a capitalised section": '[Remote "origin"]\n\turl = https://example.invalid/a.git\n',
                 "the old [remote.<name>] form": "[remote.origin]\n\turl = https://example.invalid/b.git\n",
                 "spaces inside the brackets": '[ remote  "origin" ]\n\turl = https://example.invalid/c.git\n',
                 "an include": "[core]\n\tbare = false\n[include]\n\tpath = extra.cfg\n",
                 "a conditional include": '[includeIf "gitdir:/somewhere/"]\n\tpath = extra.cfg\n'}
    for label, text in spellings.items():
        d = tmp / ("cfg_" + re.sub(r"\W+", "_", label))
        (d / ".git").mkdir(parents=True)
        (d / ".git" / "config").write_text(text, encoding="utf-8")
        (d / ".git" / "extra.cfg").write_text('[remote "origin"]\n\turl = https://example.invalid/d.git\n', encoding="utf-8")
        code_s, _o = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(d / "evidence" / "o")])
        check(f"--out inside a git tree whose config has {label}: refused, nothing written",
              code_s == vc.EXIT_REFUSED and not (d / "evidence").exists())
    cw_ = tmp / "cfg_worktree"
    (cw_ / ".git").mkdir(parents=True)
    (cw_ / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    (cw_ / ".git" / "config.worktree").write_text('[remote "origin"]\n\turl = https://example.invalid/e.git\n', encoding="utf-8")
    check("--out inside a git tree whose config.worktree lists a remote: refused",
          "remote" in (vc.out_refusal(cw_ / "evidence" / "o") or ""))
    br = tmp / "cfg_branch_only"
    (br / ".git").mkdir(parents=True)
    (br / ".git" / "config").write_text('[core]\n\tbare = false\n[branch "main"]\n\tremote = .\n[remotes]\n\tnone =\n',
                                        encoding="utf-8")
    check("... negative: a config whose keys merely mention a remote (no remote section) is accepted",
          vc.out_refusal(br / "evidence") is None)
    linkdir = tmp / "links"
    linkdir.mkdir()
    (remote / "sub").mkdir()
    made = make_link(linkdir / "to_clone", remote / "sub")
    made_repo = make_link(linkdir / "to_repo", ROOT / "intelligence")
    check("a directory link (symlink or junction) can be made for the next checks", made and made_repo)
    if made:
        code_j, out_j = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(linkdir / "to_clone" / "o")])
        check("--out through a link or junction into a git tree with a remote: refused, nothing written",
              code_j == vc.EXIT_REFUSED and "remote" in out_j and not (remote / "sub" / "o").exists())
        drop_link(linkdir / "to_clone")
    if made_repo:                      # judged without running the tool, so a regression can never write into the repository
        check("--out through a link or junction into this repository: refused",
              "inside this repository" in (vc.out_refusal(linkdir / "to_repo" / "_dq_out_never_link") or "")
              and not (ROOT / "intelligence" / "_dq_out_never_link").exists())
        drop_link(linkdir / "to_repo")
    check("... and the links are gone again, their targets untouched", not (linkdir / "to_clone").exists()
          and not (linkdir / "to_repo").exists() and (remote / "sub").is_dir() and (ROOT / "intelligence" / "quality.py").is_file())
    fileout = tmp / "afile"
    fileout.write_text("x", encoding="utf-8")
    code_f, _o = run(["--hourly", str(csv_path), "--profile", str(prof_path), "--out", str(fileout)])
    check("--out that is an existing file: refused", code_f == vc.EXIT_REFUSED)
    code_e, out_e = run(["--hourly", str(tmp / "missing.csv"), "--profile", str(prof_path), "--out", str(tmp / "o_err")])
    check("a missing input file is an error (exit 1), not a crash, and writes nothing", code_e == vc.EXIT_ERROR and not (tmp / "o_err").exists())

    print("== [5] the generated fixtures")
    years = {datetime.fromtimestamp(int(r[1]), UTC).year for r in capture_rows(date(2030, 9, 15), 60)[0]}
    check("every generated row lies in the fictional year 2030", years == {2030}, str(years))
    check("the generated files are text (UTF-8, no NUL)", all(b"\x00" not in p.read_bytes() and p.read_bytes().decode("utf-8")
                                                              for p in (csv_path, prof_path)))

print("== [4] the validator's imports and writes")
src = (ROOT / "intelligence" / "tools" / "validate_capture.py").read_text(encoding="utf-8")
tree = ast.parse(src)
mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
       {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
check("imports only argparse, hashlib, json, os, re, sys, dataclasses, datetime, pathlib and intelligence",
      mods <= {"__future__", "argparse", "hashlib", "json", "os", "re", "sys", "dataclasses", "datetime", "pathlib", "intelligence"},
      str(sorted(mods)))
calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
names = {(c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")) for c in calls}
check("no process, network, dynamic-execution or deletion call", not (names & {"system", "popen", "Popen", "run", "exec", "eval",
                                                                             "__import__", "remove", "unlink", "rmtree", "rmdir",
                                                                             "urlopen", "connect", "spawn"}), str(sorted(names))[:200])
writes = [c for c in calls if getattr(c.func, "id", "") == "open" and len(c.args) > 1 and isinstance(c.args[1], ast.Constant)
          and "w" in str(c.args[1].value)]
check("exactly two file writes (the JSON and the text summary), both inside --out",
      len(writes) == 2 and all("a.out" in ast.unparse(c.args[0]) for c in writes)
      and not [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr in ("write_text", "write_bytes")])
check("the validator says what it is on every run: REAL DATA - LOCAL ONLY - DO NOT PUBLISH (A41, PR2-2)",
      vc.BANNER == "REAL DATA - LOCAL ONLY - DO NOT PUBLISH" and vc.BANNER in src.splitlines()[1])
_kit_doc = (ROOT / "docs" / "intelligence" / "REAL_DATA_CAPTURE_KIT.md").read_text(encoding="utf-8")
_kit_flat = re.sub(r"\s+", " ", re.sub(r"\n>\s?", "\n", _kit_doc))
_KIT_GENERIC = ("given **after the owner's release closeout is committed** and **only while no supervised live step is in "
                "progress**",
                "never put the summary on GitHub or any shared or AI coordination channel",
                "- [ ] The owner's release closeout is committed and no supervised live step is in progress.")
check("... the capture runbook quotes the same banner and states the go/no-go and the sharing rule in generic words (no "
      "dated closeout, no named channel; A41, PR2-2)",
      f"`{vc.BANNER}`" in _kit_doc and all(p in _kit_flat for p in _KIT_GENERIC)
      and not re.search(r"\bbridge\b|\d{1,2} [A-Z][a-z]+ closeout|after \d{1,2} [A-Z][a-z]+\b", _kit_doc + src, re.I),
      str([p for p in _KIT_GENERIC if p not in _kit_flat]))
_DP1_DEF = "DP-1 (the owner's decision on the source of each decided input; OPEN)"
_dq_doc = (ROOT / "docs" / "intelligence" / "DATA_QUALITY_METHOD.md").read_text(encoding="utf-8")
_dp_bad, _dp_n = [], 0
for _name, _text in (("the capture kit", _kit_doc), ("the validator", src), ("DATA_QUALITY_METHOD", _dq_doc)):
    _flat = re.sub(r"\s+", " ", _text)
    for _m in re.finditer(r"\bDP-\d", _flat):
        _dp_n += 1
        if not _flat.startswith(_DP1_DEF, _m.start()):
            _dp_bad.append((_name, _flat[_m.start():_m.start() + 80]))
check("the owner-decision id DP-1 is defined where this engine text uses it, as an opaque id with its status (A45, "
      "R9D-3): every use in the capture kit, the validator and DATA_QUALITY_METHOD reads '" + _DP1_DEF + "', and none "
      "of them carries a narrative of the owner's decision process or a dated owner answer",
      _dp_bad == [] and _dp_n >= 5
      and not re.search(r"packet|owner'?s? decision of|decision of \d", _kit_doc + src + _dq_doc, re.I),
      f"{_dp_n} uses; {_dp_bad[:3]}")

print("== [5b] no 13-digit identifier on a meter / mpan / octopus / parameters line in any dq file")
DQ_FILES = [ROOT / p for p in ("intelligence/quality.py", "intelligence/faults.py", "intelligence/tools/validate_capture.py",
                               "intelligence/tests/_dq_helpers.py", "intelligence/tests/test_intel_quality.py",
                               "intelligence/tests/test_intel_quality_fuzz.py", "intelligence/tests/test_intel_faults.py",
                               "intelligence/tests/test_intel_capture_kit.py", "docs/intelligence/REAL_DATA_CAPTURE_KIT.md",
                               "docs/intelligence/DATA_QUALITY_METHOD.md")]
DQ_FILES += sorted((ROOT / "intelligence" / "tests" / "fixtures" / "dq").rglob("*")) if (ROOT / "intelligence" / "tests" / "fixtures" / "dq").exists() else []
hits = []
for p in DQ_FILES:
    if not p.is_file():
        continue
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"meter|mpan|octopus|parameters", line, re.IGNORECASE) and re.search(r"(?<!\d)\d{13}(?!\d)", line):
            hits.append(f"{p.name}:{i}")
check(f"none in {sum(1 for p in DQ_FILES if p.is_file())} files", not hits, str(hits[:3]))
fx = ROOT / "intelligence" / "tests" / "fixtures" / "dq"
check("fixtures/dq holds text only (or does not exist: fixtures are generated at test time)",
      not fx.exists() or all(p.suffix in (".csv", ".json", ".md", ".txt") for p in fx.rglob("*") if p.is_file()))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all capture-kit checks passed")
