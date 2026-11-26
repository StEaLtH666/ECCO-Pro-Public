#!/usr/bin/env python3
"""Planning stream: the leak-free advice backtest (intelligence/backtest_advice.py). SYNTHETIC campaigns only.

  [1] every result is labelled SYNTHETIC; a campaign cannot be labelled otherwise
  [2] leak test: absurd future data (history after the issue time, PV forecasts beyond tomorrow) changes no output
  [3] determinism across two interpreter processes
  [4] reserve violations for OK (feasible) advice == 0 on the synthetic campaigns, with the stated-shortfall nights that
      reach the reserve reported next to it, and a winter campaign with several feasible nights (the zero is not
      vacuous); metrics present and printed; the baselines are the cycle's own (baselines.baselines on the cycle's
      judgement); the cycle's own OK Dump advice is scored (tariff.events is an I-D6 key since CCR-DQ-1 / CCR-PLAN-1,
      and the synthetic decisions give it a limit), with no reserve violation
  [4b] positive controls: an injected unsafe OK charge target IS a violation; a constructed OK Dump advice is scored
      (a breach is a violation, a safe export is not), so both detectors are shown to fire
  [5] no GBP regret without a VERIFIED tariff
"""

from __future__ import annotations

import copy
import json
import math
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _plan_helpers as ph  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import backtest_advice as bt  # noqa: E402
from intelligence import baselines as bl  # noqa: E402
from intelligence.history import History  # noqa: E402
from intelligence.shadow_cycle import judged_reading, run_cycle  # noqa: E402
from intelligence.timeutil import ts  # noqa: E402

FAILURES: list[str] = []
HERE = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def days(start: date, a: int, b: int) -> list[date]:
    return [start + timedelta(days=k) for k in range(a, b)]


WINTER = ph.synthetic_campaign(start=date(2030, 1, 1), days=42)
WINTER_MID = ph.synthetic_campaign(start=date(2030, 1, 1), days=42, level=0.7)     # a medium house: feasible winter nights
SUMMER = ph.synthetic_campaign(start=date(2030, 5, 20), days=42, level=0.45)
win = bt.run_campaign(WINTER, days(date(2030, 1, 1), 30, 40))
wmid = bt.run_campaign(WINTER_MID, days(date(2030, 1, 1), 30, 40))
sumr = bt.run_campaign(SUMMER, days(date(2030, 5, 20), 30, 40))

print("== [1] labelled SYNTHETIC")
check("every summary and row is labelled SYNTHETIC", all(r["summary"]["label"] == "SYNTHETIC" and all(x["label"] == "SYNTHETIC" for x in r["rows"])
                                                        for r in (win, sumr)))
try:
    replace(WINTER, label="REAL")
    relabel = True
except ValueError:
    relabel = False
check("a campaign cannot be labelled anything but SYNTHETIC", relabel is False)
check("the issue time is 21:30 local", bt.issue_time(WINTER, date(2030, 1, 31)).isoformat() == "2030-01-31T21:30:00+00:00"
      and bt.issue_time(SUMMER, date(2030, 6, 20)).isoformat() == "2030-06-20T20:30:00+00:00")

print("== [2] leak test")


def poisoned(c: bt.Campaign, t) -> tuple[History, bt.Campaign]:
    cut = ts(t)
    recs = []
    for s, r in c.history.by_start.items():
        r2 = copy.deepcopy(r)
        if s + 3600 > cut:                              # every hour not completely over at t
            r2.e = {"load": 999.0, "pv": 0.0}
            r2.load_w_mean, r2.pv_w_mean, r2.soc_mean = 999000.0, 0.0, 0.0
        recs.append(r2)
    today = t.date()
    pvf = {src: {d: (v if d <= today + timedelta(days=1) else 999.0) for d, v in s.items()} for src, s in c.pv_forecasts.items()}
    return History(recs), replace(c, pv_forecasts=pvf)


leaks = []
for d in (date(2030, 1, 31), date(2030, 2, 3), date(2030, 6, 22)):
    c = WINTER if d.month < 5 else SUMMER
    t = bt.issue_time(c, d)
    clean = run_cycle(bt.inputs_at(c, t)).to_dict()
    hist2, c2 = poisoned(c, t)
    dirty = run_cycle(bt.inputs_at(c2, t, history=hist2)).to_dict()
    if json.dumps(clean, sort_keys=True) != json.dumps(dirty, sort_keys=True):
        leaks.append(d.isoformat())
    if clean["items"][0]["status"] != "OK":
        leaks.append(f"{d}: charge target not OK, the leak test would be vacuous")
check("absurd load / PV / SOC after the issue time and absurd PV forecasts beyond tomorrow change no envelope byte", leaks == [], str(leaks))
check("... the inputs never carry an hour that had not ended by t", all(max(bt.inputs_at(WINTER, bt.issue_time(WINTER, d)).history.by_start) + 3600
                                                                       <= ts(bt.issue_time(WINTER, d)) for d in days(date(2030, 1, 1), 30, 33)))

print("== [3] determinism across interpreter processes")
script = ("import sys, json\n"
          f"sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(HERE)!r})\n"
          "from datetime import date, timedelta\n"
          "import _plan_helpers as ph\n"
          "from intelligence import backtest_advice as bt\n"
          "c = ph.synthetic_campaign(start=date(2030, 1, 1), days=36)\n"
          "out = bt.run_campaign(c, [date(2030, 1, 31) + timedelta(days=k) for k in range(4)])\n"
          "print(json.dumps(out, sort_keys=True, allow_nan=False))\n")
runs = [subprocess.run([sys.executable, "-I", "-B", "-c", script], capture_output=True, text=True, timeout=600) for _ in range(2)]
here = bt.run_campaign(ph.synthetic_campaign(start=date(2030, 1, 1), days=36), [date(2030, 1, 31) + timedelta(days=k) for k in range(4)])
check("two interpreter processes give byte-identical campaign results", all(r.returncode == 0 for r in runs)
      and runs[0].stdout == runs[1].stdout and len(runs[0].stdout) > 500, " | ".join(r.stderr[-200:] for r in runs))
check("... and the same as this process", runs[0].stdout.strip() == json.dumps(here, sort_keys=True, allow_nan=False))

print("== [4] reserve violations and metrics")
RESERVE_KEYS = ("scored_nights", "feasible_nights", "reserve_violations_ok_advice", "stated_shortfall_nights",
                "stated_shortfall_reached_reserve")
for name, res, camp in (("winter", win, WINTER), ("winter, medium house", wmid, WINTER_MID), ("summer", sumr, SUMMER)):
    s = res["summary"]
    check(f"{name}: every issue scored, the charge target OK on most", s["issues"] == 10 and s["scored_nights"] >= 8
          and s["charge_target_ok"] >= 8, str({k: s[k] for k in ("issues", "scored_nights", "charge_target_ok")}))
    print(f"        SYNTHETIC {name}: " + ", ".join(f"{k} {s[k]}" for k in RESERVE_KEYS))
    check(f"{name}: reserve violations for OK (feasible) advice == 0; the metric counts FEASIBLE OK advice only, and the "
          f"stated-shortfall nights that reach the reserve ({s['stated_shortfall_reached_reserve']}) are reported beside it",
          s["reserve_violations_ok_advice"] == 0 and s["feasible_nights"] + s["stated_shortfall_nights"] == s["scored_nights"]
          and 0 <= s["stated_shortfall_reached_reserve"] <= s["stated_shortfall_nights"], str({k: s[k] for k in RESERVE_KEYS}))
    for k in ("load_tomorrow", "pv_tomorrow", "morning_soc"):
        m = s[k]
        check(f"{name}: {k} MAE and coverage are finite measured figures", m["n"] > 0 and math.isfinite(m["mae"]) and 0.0 <= m["coverage"] <= 1.0, str(m))
    t0 = datetime.fromisoformat(res["rows"][0]["issued"])
    hold_fresh = judged_reading(bt.inputs_at(camp, t0), "tou.current_target_soc_pct").fresh
    want = {bl.ALWAYS_100, bl.V1_CONFIG_WINDOW} | ({bl.HOLD_CURRENT} if hold_fresh else set())
    check(f"{name}: energy regret against exactly the baselines the cycle can have (HOLD_CURRENT only when the cycle "
          f"judges its reading fresh: {hold_fresh})", set(s["energy_regret"]) == want
          and all(v["nights"] > 0 for v in s["energy_regret"].values()), str(list(s["energy_regret"])))
check("the summer and the medium-house winter campaigns have several feasible nights (the zero is not vacuous)",
      sumr["summary"]["feasible_nights"] >= 3 and wmid["summary"]["feasible_nights"] >= 3,
      str((sumr["summary"]["feasible_nights"], wmid["summary"]["feasible_nights"])))
check("stated shortfalls are reported separately", all("stated_shortfall_nights" in r["summary"]
                                                        and "stated_shortfall_reached_reserve" in r["summary"] for r in (win, wmid, sumr)))
check("the totals add up (reserve violations = charge-target violations + Dump violations)",
      all(r["summary"]["reserve_violations_ok_advice"] == r["summary"]["charge_target_violations"] + r["summary"]["dump_violations"]
          for r in (win, wmid, sumr)))
dump_scored = [r["summary"]["dump_ok_scored"] for r in (win, wmid, sumr)]
dump_viol = [r["summary"]["dump_violations"] for r in (win, wmid, sumr)]
print(f"        SYNTHETIC cycle-level OK Dump advice (winter, medium, summer): dump_ok_scored {dump_scored}, "
      f"dump_violations {dump_viol}")
check("the cycle's own OK Dump advice is scored (the event list is judged fresh under its synthetic I-D6 limit), with no "
      "reserve violation", sum(dump_scored) > 0 and all(v == 0 for v in dump_viol), f"{dump_scored} {dump_viol}")

print("== [4b] positive controls: the violation detectors fire")


class _Env:
    """An envelope with some item views replaced (test only): the detectors are scored on constructed advice."""

    def __init__(self, env, **items):
        self._env, self._items = env, items

    def __getattr__(self, name):
        return getattr(self._env, name)

    def item(self, key):
        return self._items.get(key) or self._env.item(key)


T_POS = bt.issue_time(WINTER, date(2030, 1, 31))
INP_POS = bt.inputs_at(WINTER, T_POS)
ENV_POS = run_cycle(INP_POS)
CT_POS = ENV_POS.item("charge_target")
check("the control night has an OK charge target", CT_POS.status == "OK" and CT_POS.summary is not None, CT_POS.status)
if CT_POS.status == "OK":
    floor = float(CT_POS.summary["effective_reserve_pct"])
    unsafe_summary = dict(CT_POS.summary, target_soc_pct=floor + 1.0, binding_constraint="DEMAND")
    unsafe = ac.ItemView("charge_target", "OK", floor + 1.0, CT_POS.valid_until, CT_POS.confidence, (), CT_POS.reason_codes,
                         unsafe_summary)
    row = bt.evaluate(WINTER, T_POS, _Env(ENV_POS, charge_target=unsafe), INP_POS)
    check("an injected unsafe OK target (the reserve plus one point, stated feasible): a reserve violation, counted",
          isinstance(row["reserve"], dict) and row["reserve"]["violation"] is True
          and bt.summarise([row])["reserve_violations_ok_advice"] >= 1, str(row["reserve"]))
    soc_t = bt._last_hour(WINTER.history.truncated(T_POS)).soc_mean  # noqa: SLF001 - the SOC the cycle was given
    refill = CT_POS.summary["window"][0]
    for label, kwh, dfloor, want in (("a breach (most of the battery exported)", 15.0, floor, True),
                                     ("a safe export (a small amount, a low floor)", 0.1, 5.0, False)):
        dump = ac.ItemView("dump_to_grid", "OK", kwh, CT_POS.valid_until, "MEDIUM", (), ("DUMP",),
                           {"export_kwh": kwh, "effective_reserve_pct": dfloor, "refill_at": refill})
        d = bt.evaluate(WINTER, T_POS, _Env(ENV_POS, dump_to_grid=dump), INP_POS)["dump"]
        check(f"a constructed OK Dump advice, {label}: scored, violation {want}",
              isinstance(d, dict) and d.get("scored") is True and d.get("violation") is want
              and (d["min_soc"] < dfloor) is want, str((d, soc_t)))
        if want:
            check("... and the breach counts in the reserve violations of OK advice",
                  bt.summarise([{"dump": d, "charge_target": "OK"}])["reserve_violations_ok_advice"] == 1)

print("== [5] no GBP without a VERIFIED tariff")
nt = bt.run_campaign(ph.synthetic_campaign(start=date(2030, 1, 1), days=36, tariff=False), days(date(2030, 1, 1), 30, 34))
check("no verified tariff: no GBP regret anywhere (NO_VALUE with a reason)", nt["summary"]["gbp_regret"]["status"] == "NO_VALUE"
      and all(r["gbp"] is None for r in nt["rows"]))
check("... the energy regret is still reported", nt["summary"]["energy_regret"] and nt["summary"]["scored_nights"] > 0)
check("with the verified synthetic tariff: GBP regret per baseline", isinstance(win["summary"]["gbp_regret"], dict)
      and "ALWAYS_100" in win["summary"]["gbp_regret"] and all(isinstance(v["regret_gbp_total"], float) for v in win["summary"]["gbp_regret"].values()))

print("")
SUMMARY_KEYS = ("load_tomorrow", "pv_tomorrow", "morning_soc") + RESERVE_KEYS
for name, res in (("winter", win), ("winter, medium house", wmid), ("summer", sumr)):
    print(f"SYNTHETIC summary ({name}):", json.dumps({k: res["summary"][k] for k in SUMMARY_KEYS}, sort_keys=True))
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all backtest checks passed")
