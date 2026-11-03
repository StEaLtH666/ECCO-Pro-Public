#!/usr/bin/env python3
"""OFFLINE validator for an exported statistics capture: REAL DATA - LOCAL ONLY - DO NOT PUBLISH.

Reads the long-format statistics CSV that intelligence/tools/export_ha_statistics.py writes (plain .csv or .csv.gz) and a
site-local profile (the shape of intelligence/profiles/site_profile.example.json), builds the canonical hourly History
with the unchanged history builder, and writes ONLY an aggregate summary to --out:

  * the history audit (coverage, gaps, flags), as counts;
  * the data-quality findings of intelligence.quality over replayed snapshots (one instant every --step-days days at
    --replay-hour local time), as counts per finding code;
  * the I-D8 load-counter check: the load counter against the balance-derived load and against the load-power integral,
    before and after a --cutover instant, as medians, upper quantiles and shares;
  * the hourly energy balance (a reversed CT shows as import and export swapped), stalls, catch-up jumps and dropouts;
  * the clock-change nights in the capture, with how complete each one is.

No per-hour household series is written, and nothing is written anywhere but --out. --out is refused inside this
repository and inside any directory tree whose git configuration lists a remote (found by walking up from --out and
reading .git/config, or a worktree's common configuration, with os and pathlib only); an unreadable git configuration is
refused too. No network, no process, no Home Assistant. The advice backtest step stays PENDING: it needs DP-1 (the
owner's decision on the source of each decided input; OPEN), synthetic decisions are never used on real data, and a
capture that carries the TOU and tariff readings at each issue time, which a statistics capture does not.

    python intelligence/tools/validate_capture.py --hourly <OFFLINE_EVIDENCE_DIR>/hist_hourly.csv.gz \
        --profile <OFFLINE_EVIDENCE_DIR>/site.local.json --out <OFFLINE_EVIDENCE_DIR>/capture-summary [--cutover ISO]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import stats  # noqa: E402
from intelligence.advisory_contract import CycleInputs, SiteFacts  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import (ENERGY_FIELDS, History, audit, build_history, forecast_issue_series,  # noqa: E402
                                  iter_stats_csv, load_profile)
from intelligence.inputs import history_snapshot, live_inputs_from_snapshot  # noqa: E402
from intelligence.quality import (DQ_PROPOSED, QUALITY_VERSION, assess_inputs, balance_counts,  # noqa: E402
                                  clock_change_nights, ct_reversed, dropout_runs, stall_hours)
from intelligence.timeutil import HOUR, UTC, day_bounds, local_wall, zone  # noqa: E402

TOOL_VERSION = "intel-validate-capture-0.1.0"
SCHEMA = "ecco-intel-capture-summary/1"
BANNER = "REAL DATA - LOCAL ONLY - DO NOT PUBLISH"
SUMMARY_JSON = "capture_summary.json"
SUMMARY_TXT = "capture_summary.txt"
EXIT_OK, EXIT_ERROR, EXIT_REFUSED = 0, 1, 2
# a remote section in any spelling git accepts: section names are case-insensitive, and the deprecated [remote.<name>]
# form is still read
_REMOTE = re.compile(r'^\s*\[\s*remote\s*(?:"|\.)', re.MULTILINE | re.IGNORECASE)
# an include pulls in configuration this check does not follow: refused (fail closed)
_INCLUDE = re.compile(r'^\s*\[\s*include(?:if)?\s*[\]"]', re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------------------------
# where the summary may go
# ---------------------------------------------------------------------------------------------------------------------

def _git_config_paths(d: Path) -> list[Path] | None:
    """The configuration files of a git work tree rooted at d (none when d is not one): the git dir's `config` and
    `config.worktree`, and for a worktree (a `.git` file pointing at its git dir) those of the shared directory its
    `commondir` names. None = unreadable."""
    g = d / ".git"
    try:
        if g.is_dir():
            return [g / "config", g / "config.worktree"]
        if not g.is_file():
            return []
        text = g.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = (d / gitdir)
    out = [gitdir / "config", gitdir / "config.worktree"]
    try:
        common = gitdir / "commondir"
        if common.is_file():
            cd = Path(common.read_text(encoding="utf-8", errors="replace").strip())
            base = cd if cd.is_absolute() else gitdir / cd
            out += [base / "config", base / "config.worktree"]
    except OSError:
        return None
    return out


def _refusal_for(p: Path, repos: list[Path]) -> str | None:
    if any(p == r or r in p.parents for r in repos):
        return "the output directory is inside this repository"
    for d in [p] + list(p.parents):
        cfgs = _git_config_paths(d)
        if cfgs is None:
            return "the output directory is inside a git work tree whose configuration cannot be read"
        for cfg in cfgs:
            try:
                if not cfg.exists():
                    continue
                text = cfg.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return "the output directory is inside a git work tree whose configuration cannot be read"
            if _REMOTE.search(text):
                return "the output directory is inside a git work tree with a remote (it could be pushed)"
            if _INCLUDE.search(text):
                return "the output directory is inside a git work tree whose configuration includes other files"
    return None


def out_refusal(out: str | os.PathLike) -> str | None:
    """Why --out may not be used (None when it may): inside this repository, or inside a git work tree whose configuration
    lists a remote (any spelling), includes other configuration, or cannot be read. Both the path as given and the path
    with every link and junction resolved are checked, so a link cannot lead the summary into a repository."""
    given = os.fspath(out)
    paths = [Path(os.path.abspath(given)), Path(os.path.realpath(given))]
    repos = [Path(os.path.abspath(ROOT)), Path(os.path.realpath(ROOT))]
    for p in paths:
        why = _refusal_for(p, repos)
        if why is not None:
            return why
    return None


# ---------------------------------------------------------------------------------------------------------------------
# aggregates
# ---------------------------------------------------------------------------------------------------------------------

def _q(xs: list[float], q: float) -> float | None:
    return round(stats.quantile(xs, q), 4) if xs else None


def _dist(xs: list[float]) -> dict:
    """n, median, 90th percentile: the only shape a distribution leaves the tool in."""
    return {"n": len(xs), "median": _q(xs, 0.5), "p90": _q(xs, 0.9)}


def audit_summary(history: History) -> dict:
    a = audit(history)
    runs = a.pop("missing_runs", [])
    a["missing_run_count"] = len(runs)
    a["longest_missing_run_h"] = max((n for _s, n in runs), default=0)
    for k in ("first_utc", "last_utc"):
        if k in a:
            a[k] = a[k][:10]                                    # dates only
    return a


def load_counter_check(history: History, cutover: datetime | None) -> dict:
    """The I-D8 counter check: before and after the cut-over, the load counter against the balance-derived load
    (pv + imp - exp + dis - chg) and against the load-power integral, plus the share of exporting hours whose load reads
    zero. Aggregates only."""
    if cutover is None:
        return {"status": "NOT_RUN", "why": "no --cutover given"}
    cut = int(cutover.timestamp())
    out: dict = {"status": "RUN", "cutover_date": cutover.astimezone(UTC).date().isoformat()}
    for side in ("before", "after"):
        rel_bal: list[float] = []
        rel_pow: list[float] = []
        exporting = zero_while_exporting = 0
        for s, r in history.by_start.items():
            if (s < cut) != (side == "before"):
                continue
            v = {f: r.e.get(f) for f in ENERGY_FIELDS}
            load = v["load"]
            if load is None:
                continue
            if None not in v.values():
                derived = v["pv"] + v["imp"] - v["exp"] + v["dis"] - v["chg"]
                rel_bal.append(abs(load - derived) / max(abs(derived), 0.1))
            if r.load_w_mean is not None and r.sources.get("load") != "power_integral":
                p = max(r.load_w_mean, 0.0) / 1000.0
                rel_pow.append(abs(load - p) / max(p, 0.1))
            if v["exp"] is not None and v["exp"] > DQ_PROPOSED.export_evidence_kwh:
                exporting += 1
                if load <= DQ_PROPOSED.stall_energy_max_kwh:
                    zero_while_exporting += 1
        tol = DQ_PROPOSED.counter_check_tol_fraction
        out[side] = {"counter_vs_balance": _dist(rel_bal),
                     "share_beyond_tolerance": round(sum(1 for x in rel_bal if x > tol) / len(rel_bal), 4) if rel_bal else None,
                     "counter_vs_power_integral": _dist(rel_pow),
                     "exporting_hours": exporting,
                     "share_zero_while_exporting": round(zero_while_exporting / exporting, 4) if exporting else None}
    return out


def dst_summary(history: History, tz_name: str) -> list[dict]:
    fl = history.first_last()
    if fl is None:
        return []
    z = zone(tz_name)
    out = []
    for day_iso, kind in clock_change_nights(fl[0], fl[1] + timedelta(hours=1), tz_name):
        d = date.fromisoformat(day_iso)
        t0, t1 = day_bounds(d, z)
        hours = list(range(int(t0.timestamp()), int(t1.timestamp()), HOUR))
        out.append({"date": day_iso, "kind": kind, "hours_expected": len(hours),
                    "hours_present": sum(1 for s in hours if s in history.by_start)})
    return out


def dropout_summary(history: History) -> dict:
    fl = history.first_last()
    if fl is None:
        return {"runs": 0}
    start, end = int(fl[0].timestamp()), int(fl[1].timestamp()) + HOUR
    runs = dropout_runs(history.by_start, start, end)
    per_day: dict[int, int] = {}
    for s, _n in runs:
        per_day[s // 86400] = per_day.get(s // 86400, 0) + 1
    return {"runs": len(runs), "longest_h": max((n for _s, n in runs), default=0),
            "days_with_repeated_dropouts": sum(1 for n in per_day.values() if n >= DQ_PROPOSED.flap_min_dropouts)}


def replay_summary(history: History, cfg: SiteConfig, tz_name: str, forecasts: dict, step_days: int,
                   replay_hour: int, pv_kwp: float | None) -> dict:
    """assess_inputs over replayed snapshots (every decision OPEN; no live readings exist in a capture, so the live rules
    report missing inputs by design). Returns counts per finding code."""
    fl = history.first_last()
    if fl is None:
        return {"instants": 0, "codes": {}}
    z = zone(tz_name)
    d = (fl[0] + timedelta(days=28)).astimezone(z).date()
    last = fl[1].astimezone(z).date()
    codes: dict[str, dict] = {}
    n = 0
    while d <= last:
        now = local_wall(d, replay_hour * 60, z)
        known = history.truncated(now)
        if len(known):
            snap = history_snapshot(known, cfg, now)
            inp = CycleInputs(now=now, snapshot=snap, live=live_inputs_from_snapshot(snap), history=known,
                              pv_forecast_history=forecasts, site_facts=SiteFacts(pv_array_kwp=pv_kwp, tz=tz_name))
            q = assess_inputs(inp)
            seen = set()
            for f in q.findings:
                key = (f.code, f.severity)
                if key in seen:
                    continue
                seen.add(key)
                row = codes.setdefault(f.code, {"severity": f.severity, "instants": 0})
                row["instants"] += 1
            n += 1
        d += timedelta(days=step_days)
    return {"instants": n, "step_days": step_days, "replay_hour_local": replay_hour,
            "decisions": "all OPEN (a capture records none)", "codes": dict(sorted(codes.items()))}


def build_summary(rows: list[dict], profile: dict, *, tz_name: str, cutover: datetime | None, step_days: int,
                  replay_hour: int, input_sha256: str, input_bytes: int) -> dict:
    cfg = SiteConfig(tz=tz_name)
    history = build_history(rows, profile, cfg)
    forecasts = {}
    for name, spec in (profile.get("forecasts") or {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("id"), str):
            series = forecast_issue_series(rows, spec["id"], tz_name)
            if series:
                forecasts[name] = series
    site = profile.get("site") if isinstance(profile.get("site"), dict) else {}
    pv_kwp = site.get("pv_array_kwp") if isinstance(site.get("pv_array_kwp"), (int, float)) else None
    bc = balance_counts(history.by_start)
    st = stall_hours(history.by_start)
    return {
        "banner": BANNER, "schema": SCHEMA, "tool_version": TOOL_VERSION, "quality_version": QUALITY_VERSION,
        "input": {"sha256": input_sha256, "bytes": input_bytes, "rows": len(rows),
                  "statistic_ids": len({r.get("statistic_id") for r in rows})},
        "profile": {"sources": len(profile.get("sources", [])), "forecast_series": len(forecasts)},
        "audit": audit_summary(history),
        "energy_balance": {**bc, "ct_reversed": ct_reversed(bc)},
        "counter_faults": {"stall_hours": len(st["stall"]), "catchup_hours": len(st["catchup"])},
        "dropouts": dropout_summary(history),
        "dst_nights": dst_summary(history, tz_name),
        "load_counter_check": load_counter_check(history, cutover),
        "replay": replay_summary(history, cfg, tz_name, forecasts, step_days, replay_hour, pv_kwp),
        "backtest": ("PENDING: needs DP-1 (the owner's decision on the source of each decided input; OPEN) and a "
                     "capture with the TOU and tariff readings at each issue time"),
        "thresholds": asdict(DQ_PROPOSED),
    }


def summary_text(s: dict) -> str:
    lines = [BANNER, f"{s['schema']}  {s['tool_version']}  {s['quality_version']}", ""]
    a = s["audit"]
    lines.append(f"input: {s['input']['rows']} rows, {s['input']['statistic_ids']} statistic ids, sha256 {s['input']['sha256']}")
    lines.append(f"history: {a.get('hours_present', 0)} of {a.get('hours_expected', 0)} hours present, "
                 f"{a.get('missing_run_count', 0)} missing runs (longest {a.get('longest_missing_run_h', 0)} h), "
                 f"{a.get('first_utc', '-')} to {a.get('last_utc', '-')}")
    for fld, v in sorted((a.get("fields") or {}).items()):
        lines.append(f"  {fld}: coverage {v['coverage']}, flags {v['flags']}")
    eb = s["energy_balance"]
    lines.append(f"energy balance: {eb['balanced']} balanced, {eb['balanced_only_swapped']} only swapped, "
                 f"{eb['unbalanced']} unbalanced; CT reversed: {eb['ct_reversed']}")
    lines.append(f"counter faults: {s['counter_faults']}")
    lines.append(f"dropouts: {s['dropouts']}")
    lines.append("clock-change nights: " + (", ".join(f"{n['date']} {n['kind']} {n['hours_present']}/{n['hours_expected']}"
                                                      for n in s["dst_nights"]) or "none"))
    lc = s["load_counter_check"]
    lines.append(f"I-D8 load-counter check: {lc.get('status')}")
    for side in ("before", "after"):
        if side in lc:
            lines.append(f"  {side}: {lc[side]}")
    r = s["replay"]
    lines.append(f"replay: {r.get('instants', 0)} instants, every {r.get('step_days', '-')} days")
    for code, row in (r.get("codes") or {}).items():
        lines.append(f"  {row['severity']:5} {code}: {row['instants']}")
    lines.append(f"backtest: {s['backtest']}")
    lines.append("")
    lines.append(BANNER)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------------------------

def _aware_dt(text: str) -> datetime:
    t = datetime.fromisoformat(text)
    if t.tzinfo is None or t.tzinfo.utcoffset(t) is None:
        raise ValueError("an instant with its UTC offset is required")
    return t


def main(argv: list[str] | None = None) -> int:
    print(BANNER)
    ap = argparse.ArgumentParser(description="offline capture validator (aggregate summary only)")
    ap.add_argument("--hourly", required=True, help="the exporter's hourly statistics CSV (.csv or .csv.gz)")
    ap.add_argument("--profile", required=True, help="the site-local profile JSON")
    ap.add_argument("--out", required=True, help="output directory (outside every repository)")
    ap.add_argument("--tz", default="Europe/London")
    ap.add_argument("--cutover", default=None, help="I-D8 cut-over instant, ISO 8601 with offset")
    ap.add_argument("--step-days", type=int, default=7)
    ap.add_argument("--replay-hour", type=int, default=21)
    a = ap.parse_args(argv)
    why = out_refusal(a.out)
    if why is not None:
        print(f"REFUSED: {why}; choose a local evidence directory outside every repository")
        return EXIT_REFUSED
    if Path(a.out).exists() and not Path(a.out).is_dir():
        print("REFUSED: --out exists and is not a directory")
        return EXIT_REFUSED
    try:
        cutover = _aware_dt(a.cutover) if a.cutover else None
        zone(a.tz)
        if not 1 <= a.step_days <= 366 or not 0 <= a.replay_hour <= 23:
            raise ValueError("--step-days must be 1..366 and --replay-hour 0..23")
        raw = Path(a.hourly).read_bytes()
        rows = list(iter_stats_csv(a.hourly))
        profile = load_profile(a.profile)
        if not isinstance(profile, dict) or not isinstance(profile.get("sources"), list):
            raise ValueError("the profile has no sources list")
        summary = build_summary(rows, profile, tz_name=a.tz, cutover=cutover, step_days=a.step_days,
                                replay_hour=a.replay_hour, input_sha256=hashlib.sha256(raw).hexdigest(),
                                input_bytes=len(raw))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return EXIT_ERROR
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, SUMMARY_JSON), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, indent=1, sort_keys=True, allow_nan=False)
        fh.write("\n")
    with open(os.path.join(a.out, SUMMARY_TXT), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(summary_text(summary))
    print(f"wrote {SUMMARY_JSON} and {SUMMARY_TXT} (aggregates only)")
    print(BANNER)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
