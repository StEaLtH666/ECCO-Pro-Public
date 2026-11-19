#!/usr/bin/env python3
"""PV recent-output envelope (intelligence/pv.py, optional, OFF by default). SYNTHETIC data only (fictional numbers).

The loose `recent_max` ceiling (2.5 x the best actual of the last 30 days) lets an out-of-season value through when the last 30
days still contain much better days. With `recent_envelope=True` that ceiling becomes 1.25 x the best actual of the last 14 days
(needs at least 7 actual days in them; otherwise the legacy ceiling stays), and a corrected value above it is REJECTED exactly like
any other ceiling breach (persistence, LOW, the source and the reason in `plausibility`).

  [1] the envelope ceiling: value, window, headroom, the minimum number of observed days, the fallback to the legacy ceiling
  [2] a corrected value above it is REJECTED (persistence, LOW, the reason named); one below it is untouched
  [3] OFF (the default) changes nothing: the legacy ceiling, limits_kwh and the verdict are exactly as before
  [4] it composes with the skill gate (the guard runs first; the gate still sees only a surviving source)
  [5] mutation: mutants of the implementation applied in memory, each must be caught
"""

from __future__ import annotations

import math
import random
import sys
import types
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import pv as REAL  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.timeutil import HOUR, day_bounds, ts, zone  # noqa: E402

PV_PATH = ROOT / "intelligence" / "pv.py"
CFG = SiteConfig(tz="UTC", pv_array_kwp=None)
D0 = date(2030, 3, 1)


def day(i: int) -> date:
    return D0 + timedelta(days=i)


def history_from(actuals: dict[date, float]) -> History:
    z = zone(CFG.tz)
    recs = []
    for d, a in actuals.items():
        s0 = ts(day_bounds(d, z)[0])
        for h in range(24):
            r = HourRecord(start=s0 + h * HOUR)
            r.e["pv"] = a if h == 12 else 0.0
            recs.append(r)
    return History(recs)


def world(n_summer: int, n_dull: int, seed: int = 5):
    """n_summer large varied days, then n_dull dull ones (the raw forecast tracks the actual x1.4)."""
    rnd = random.Random(seed)
    act, raw = {}, {}
    for i in range(n_summer + n_dull):
        a = rnd.uniform(28.0, 40.0) if i < n_summer else rnd.uniform(3.0, 8.0)
        act[day(i)] = a
        raw[day(i)] = a * 1.4 * (1.0 + 0.05 * rnd.gauss(0, 1))
    return act, raw


def model(M, act, raw, env, gate=False, upto=None):
    k = (max((d - D0).days for d in act) + 1 if act else 0) if upto is None else upto
    a = {d: v for d, v in act.items() if (d - D0).days < k}
    f = {"src": {d: v for d, v in raw.items() if (d - D0).days < k}}
    return M.PvModel(history_from(a), CFG, f, skill_gate=gate, recent_envelope=env)


class Rec:
    def __init__(self, loud: bool):
        self.loud, self.fails = loud, []

    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        if ok:
            if self.loud:
                print(f"  PASS  {name}")
        else:
            self.fails.append(name)
            if self.loud:
                print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))

    def section(self, title: str) -> None:
        if self.loud:
            print(f"== {title}")


ACT, RAW = world(70, 20)        # 70 summer-like days, then 20 dull days (best of the last 14 stays well under 8.0)
T = day(90)
BEST14 = max(ACT[day(i)] for i in range(90 - 14, 90))
BEST30 = max(ACT[day(i)] for i in range(90 - 30, 90))


def sec_ceiling(M, rec: Rec) -> None:
    rec.section("[1] the envelope ceiling")
    on, off = model(M, ACT, RAW, True), model(M, ACT, RAW, False)
    lim_on, lim_off = on.plausibility_limits(T), off.plausibility_limits(T)
    rec("ON: recent_max = 1.25 x the best actual of the last 14 days (not the 30-day 2.5x)",
        abs(lim_on["recent_max"] - round(1.25 * BEST14, 2)) < 1e-9 and BEST14 < BEST30, f"{lim_on} {BEST14} {BEST30}")
    rec("OFF: recent_max is the legacy 2.5 x the best of the last 30 days", abs(lim_off["recent_max"] - round(2.5 * BEST30, 2)) < 1e-9, str(lim_off))
    rec("the other ceilings are identical ON and OFF", {k: v for k, v in lim_on.items() if k != "recent_max"} ==
        {k: v for k, v in lim_off.items() if k != "recent_max"})
    # the window: day T-14 counts, day T-15 does not; the headroom is exactly 1.25
    a2 = dict(ACT)
    a2[day(90 - 14)] = 9.5
    a2[day(90 - 15)] = 31.0
    lim = model(M, a2, RAW, True).plausibility_limits(T)
    rec("the 14-day window includes T-14 and excludes T-15", abs(lim["recent_max"] - round(1.25 * max(9.5, max(ACT[day(i)] for i in range(90 - 13, 90))), 2)) < 1e-9, str(lim))
    # too few observed days in the window: the legacy ceiling stays
    sparse = {d: v for d, v in ACT.items() if not (90 - 14 <= (d - D0).days < 90 - 6)}      # 8 of the last 14 days missing: 6 observed
    lim_s = model(M, sparse, RAW, True).plausibility_limits(T)
    rec("fewer than 7 observed days in the window: the legacy ceiling is kept (enabling never removes a guard)",
        abs(lim_s["recent_max"] - round(2.5 * max(v for d, v in sparse.items() if 0 < (T - d).days <= 30), 2)) < 1e-9, str(lim_s))
    seven = {d: v for d, v in ACT.items() if not (90 - 14 <= (d - D0).days < 90 - 7)}        # exactly 7 observed days left in the window
    lim7 = model(M, seven, RAW, True).plausibility_limits(T)
    rec("exactly 7 observed days in the window: the envelope applies",
        abs(lim7["recent_max"] - round(1.25 * max(v for d, v in seven.items() if 0 < (T - d).days <= 14), 2)) < 1e-9, str(lim7))


def sec_reject(M, rec: Rec) -> None:
    rec.section("[2] a corrected value above the envelope is REJECTED")
    on, off = model(M, ACT, RAW, True), model(M, ACT, RAW, False)
    ratio_hint = 1.0 / 1.4
    ceiling = round(1.25 * BEST14, 2)
    hi_raw = (ceiling * 1.5) / ratio_hint            # corrected about 1.5 x the ceiling
    lo_raw = (ceiling * 0.5) / ratio_hint            # corrected about half of it
    a, b = on.forecast_day(T, {"src": hi_raw}), off.forecast_day(T, {"src": hi_raw})
    d = a.to_dict()
    rec("above the envelope: REJECTED as recent_max, persistence, LOW, the ceiling named in the note",
        d["plausibility"]["verdict"] == "REJECTED" and d["plausibility"]["rejected"][0]["limit"] == "recent_max"
        and a.source == "persistence" and a.label == "LOW" and any("recent observed-output ceiling" in n for n in a.notes), str(d["plausibility"]))
    rec("the same inputs without the envelope are accepted (the legacy ceiling let them through)", b.source == "src"
        and b.to_dict()["plausibility"]["verdict"] == "OK", str(b.to_dict()["plausibility"]))
    a2, b2 = on.forecast_day(T, {"src": lo_raw}), off.forecast_day(T, {"src": lo_raw})
    rec("below the envelope: untouched (identical with and without it, apart from the ceiling value itself)",
        a2.source == "src" and a2.p50 == b2.p50 and (a2.p10, a2.p90) == (b2.p10, b2.p90) and a2.notes == b2.notes
        and a2.to_dict()["plausibility"]["verdict"] == "OK")
    rec("the persistence published on a rejection is the model's own", (a.p10, a.p50, a.p90) == (lambda p: (p.p10, p.p50, p.p90))(off._persistence(T, [])))
    # exactly at the ceiling is not a breach (the guard compares with '>')
    pf = on.forecast_day(T, {"src": ceiling / on.ratio("src", T)[0]})
    rec("a corrected value equal to the ceiling is not rejected", pf.to_dict()["plausibility"]["verdict"] == "OK", str(pf.to_dict()["plausibility"]))


def sec_off_default(M, rec: Rec) -> None:
    rec.section("[3] OFF is the default and changes nothing")
    h = history_from({day(i): 5.0 for i in range(3)})
    rec("the module default is OFF", M.PV_RECENT_ENVELOPE_DEFAULT is False and M.PvModel(h, CFG, {}).recent_envelope is False)
    rec("True and False are taken as given", M.PvModel(h, CFG, {}, recent_envelope=True).recent_envelope is True
        and M.PvModel(h, CFG, {}, recent_envelope=False).recent_envelope is False)
    bad = []
    for v in ("yes", 1, 0, [], "False"):
        try:
            M.PvModel(h, CFG, {}, recent_envelope=v)
            bad.append(v)
        except ValueError:
            pass
    rec("anything but a bool or None is refused (ValueError)", not bad, str(bad))
    rec("the constants are 14 days, 1.25 x, 7 observed days", (M.RECENT_ENVELOPE_DAYS, M.RECENT_ENVELOPE_HEADROOM, M.RECENT_ENVELOPE_MIN_OBS) == (14, 1.25, 7))
    default = M.PvModel(history_from(ACT), CFG, {"src": RAW})
    explicit = model(M, ACT, RAW, False)
    rec("a default-built model has exactly the legacy limits", default.plausibility_limits(T) == explicit.plausibility_limits(T))


def sec_gate(M, rec: Rec) -> None:
    rec.section("[4] with the skill gate")
    on = model(M, ACT, RAW, True, gate=True)
    pf = on.forecast_day(T, {"src": 200.0})
    rec("a value far above the envelope with both switches on: REJECTED first (the verdict says so, no gate note)",
        pf.to_dict()["plausibility"]["verdict"] == "REJECTED" and not any("beaten" in n for n in pf.notes))
    ok = model(M, ACT, RAW, True, gate=True).forecast_day(T, {"src": 6.0})
    rec("a plausible value with both switches on gets a normal forecast or the gate's persistence, never an error",
        ok.label in ("LOW", "MEDIUM", "HIGH") and math.isfinite(ok.p50) and ok.p10 <= ok.p50 <= ok.p90)


BATTERY = (sec_ceiling, sec_reject, sec_off_default, sec_gate)


def battery(M, rec: Rec) -> None:
    for fn in BATTERY:
        try:
            fn(M, rec)
        except Exception as exc:
            rec(f"{fn.__name__} raised {type(exc).__name__}: {exc}", False)


MUTANTS = [
    ("headroom 1.25 -> 2.5", "RECENT_ENVELOPE_HEADROOM = 1.25 ", "RECENT_ENVELOPE_HEADROOM = 2.5 "),
    ("headroom 1.25 -> 1.0", "RECENT_ENVELOPE_HEADROOM = 1.25 ", "RECENT_ENVELOPE_HEADROOM = 1.0 "),
    ("window 14 -> 30 days", "RECENT_ENVELOPE_DAYS = 14 ", "RECENT_ENVELOPE_DAYS = 30 "),
    ("window 14 -> 13 days", "RECENT_ENVELOPE_DAYS = 14 ", "RECENT_ENVELOPE_DAYS = 13 "),
    ("window one day long (< instead of <=)", "if (day - d).days <= RECENT_ENVELOPE_DAYS]", "if (day - d).days <= RECENT_ENVELOPE_DAYS + 1]"),
    ("min observed days 7 -> 0", "RECENT_ENVELOPE_MIN_OBS = 7 ", "RECENT_ENVELOPE_MIN_OBS = 0 "),
    ("min observed days off by one", "if len(env) >= RECENT_ENVELOPE_MIN_OBS:", "if len(env) > RECENT_ENVELOPE_MIN_OBS:"),
    ("best of the window replaced by its minimum", "RECENT_ENVELOPE_HEADROOM * max(env)", "RECENT_ENVELOPE_HEADROOM * min(env)"),
    ("best of the window replaced by its mean", "RECENT_ENVELOPE_HEADROOM * max(env)", "RECENT_ENVELOPE_HEADROOM * (sum(env) / len(env))"),
    ("the switch is ignored (always on)", "if self.recent_envelope:", "if True:"),
    ("the switch is ignored (never on)", "if self.recent_envelope:", "if False:"),
    ("an explicit switch is ignored", "self.recent_envelope = PV_RECENT_ENVELOPE_DEFAULT if recent_envelope is None else recent_envelope",
     "self.recent_envelope = PV_RECENT_ENVELOPE_DEFAULT"),
    ("the envelope replaces the ceiling even without enough days", "if len(env) >= RECENT_ENVELOPE_MIN_OBS:", "if len(env) >= 0 and env:"),
    ("the legacy ceiling is removed when the envelope is on", "caps[\"recent_max\"] = round(RECENT_ENVELOPE_HEADROOM * max(env), 2)",
     "caps.pop(\"recent_max\", None)"),
    ("the ceiling is not rounded the engine's way", "caps[\"recent_max\"] = round(RECENT_ENVELOPE_HEADROOM * max(env), 2)",
     "caps[\"recent_max\"] = round(RECENT_ENVELOPE_HEADROOM * max(env), 0)"),
]


def load_variant(text: str, name: str):
    mod = types.ModuleType("intelligence." + name)
    mod.__package__ = "intelligence"
    mod.__file__ = str(PV_PATH)
    sys.modules[mod.__name__] = mod
    try:
        exec(compile(text, str(PV_PATH), "exec"), mod.__dict__)
    except BaseException:
        sys.modules.pop(mod.__name__, None)
        raise
    return mod


def _fails(M) -> list[str]:
    r = Rec(False)
    battery(M, r)
    return r.fails


def run_mutants(rec: Rec) -> None:
    rec.section(f"[5] mutation: {len(MUTANTS)} mutants of intelligence/pv.py applied in memory")
    src = PV_PATH.read_text(encoding="utf-8")
    rec("the unmodified source, exec'd as a module, passes the battery", _fails(load_variant(src, "pv_env_baseline")) == [])
    killed = 0
    for i, (name, old, new) in enumerate(MUTANTS):
        n = src.count(old)
        if n != 1:
            rec(f"mutant '{name}' applies exactly once", False, f"{n} occurrences of {old!r}")
            continue
        try:
            fails = _fails(load_variant(src.replace(old, new, 1), f"pv_env_mutant_{i}"))
        except Exception as exc:
            fails = [f"import: {type(exc).__name__}"]
        finally:
            sys.modules.pop(f"intelligence.pv_env_mutant_{i}", None)
        rec(f"mutant '{name}' is caught ({len(fails)} check(s) noticed)", bool(fails), "SURVIVED")
        killed += 1 if fails else 0
    rec(f"{killed} of {len(MUTANTS)} mutants killed", killed == len(MUTANTS), str(killed))
    sys.modules.pop("intelligence.pv_env_baseline", None)


def main() -> int:
    rec = Rec(True)
    battery(REAL, rec)
    if rec.fails:
        print("\nmutation checks skipped: the real code fails the checks above")
    else:
        run_mutants(rec)
    print("")
    if rec.fails:
        print(f"{len(rec.fails)} check(s) FAILED:")
        for f in rec.fails:
            print("  -", f)
        return 1
    print("all PV recent-envelope checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
