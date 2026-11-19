#!/usr/bin/env python3
"""PV persistence-skill gate (intelligence/pv.py PvModel.skill_gate_verdict / forecast_day). SYNTHETIC data only: seeded
generators with fictional numbers, no site value, no entity id.

  [1] the pure comparison and the constants (the margin boundary, NaN fail closed)
  [2] real skill: the gate keeps the corrected forecast and the result is identical to the ungated one
  [3] no skill (a shade-capped array: flat actuals, random raw): persistence, LOW, an honest finite band, one note line
  [4] graded skill: clearly better keeps, marginally worse / clearly worse persistence (the 0.9 margin, end to end)
  [5] fail closed: fewer than 8 comparable days => persistence (the exact day-count boundary), fewer than 5 actual days =>
      INSUFFICIENT exactly as before
  [6] the plausibility guard is untouched and runs first (REJECTED never reaches the gate)
  [7] raw values that are NaN / inf / negative / bool are ignored, in the call and in the forecast history
  [8] no leakage: the target day's or later actuals / forecasts never change anything
  [9] the contract: to_dict keys, the summary size, the date scoping and valid_until through a whole cycle
  [10] regimes: skill appears (and goes) after three weeks and the gate follows within the window; a summer-like world
  [11] the switch: constructor argument, default, refusal of a non-bool
  [12] mutation: >= 15 mutants of intelligence/pv.py applied in memory, each must be killed by the checks above
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from intelligence import pv as REAL  # noqa: E402
from intelligence import stats  # noqa: E402
from intelligence.advisory_contract import MAX_SUMMARY_BYTES, PV_TOMORROW_SUMMARY_KEYS  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.timeutil import HOUR, day_bounds, ts, zone  # noqa: E402

PV_PATH = ROOT / "intelligence" / "pv.py"
EXPECT_DEFAULT = False                   # the documented default of PV_SKILL_GATE_DEFAULT (docs/intelligence/INTELLIGENCE_PV_SKILL_GATE.md)
CFG = SiteConfig(tz="UTC", pv_array_kwp=6.0)        # a synthetic 6 kWp array: the physical ceiling is 48 kWh/day
D0 = date(2030, 3, 1)
TO_DICT_KEYS = {"inflation", "usable", "day", "source", "raw_kwh", "ratio", "p10", "p50", "p90", "n_pairs", "mae_corrected",
                "mae_raw", "confidence", "label", "notes", "plausibility"}
EXTRA_DAYS = 7                           # days after the target day that exist in a world (they must never be read)


def day(i: int) -> date:
    return D0 + timedelta(days=i)


def history_from(actuals: dict[date, float]) -> History:
    """A complete hourly History whose local-day PV energy is exactly the given actual (all of it in hour 12)."""
    z = zone(CFG.tz)
    recs = []
    for d, a in actuals.items():
        s0 = ts(day_bounds(d, z)[0])
        for h in range(24):
            r = HourRecord(start=s0 + h * HOUR)
            r.e["pv"] = a if h == 12 else 0.0
            recs.append(r)
    return History(recs)


class World:
    """Days 0..n-1 are history; day n is the target day T; days n+1.. exist only to prove they are never read."""

    def __init__(self, kind: str, n: int, seed: int, sigma: float = 0.06, switch: int | None = None):
        rnd = random.Random(seed)
        self.n, self.kind = n, kind
        self.act: dict[date, float] = {}
        self.raws: dict[str, dict[date, float]] = {"src": {}, "src2": {}}
        for i in range(n + 1 + EXTRA_DAYS):
            d = day(i)
            skilled = (kind == "skill") or (kind == "switch_on" and i >= switch) or (kind == "switch_off" and i < switch)
            if kind == "summer":
                a = rnd.uniform(14.0, 36.0)
                f = a * 1.1 * (1.0 + 0.10 * rnd.gauss(0, 1))
                f2 = f
            elif skilled:                        # actuals vary a lot from day to day; the raw forecast tracks them (x1.4)
                a = rnd.uniform(3.0, 20.0)
                f = a * 1.4 * (1.0 + sigma * rnd.gauss(0, 1))
                f2 = f
            elif kind in ("switch_on", "switch_off"):   # the same actuals, a raw forecast unrelated to them
                a = rnd.uniform(3.0, 20.0)
                f = rnd.uniform(3.0, 70.0)
                f2 = f
            else:                                # "shaded": output flat whatever the forecast says
                a = 5.0 + 0.3 * rnd.gauss(0, 1)
                f = rnd.uniform(5.0, 40.0)
                f2 = rnd.uniform(5.0, 40.0)
            self.act[d] = max(0.2, a)
            self.raws["src"][d] = max(1.0, f)
            self.raws["src2"][d] = max(1.0, f2)
        self.T = day(n)

    def model(self, M, gate: bool | None, upto: int | None = None, act_over: dict | None = None,
              raw_over: dict | None = None, sources: tuple[str, ...] = ("src",)):
        up = self.n if upto is None else upto
        act = {d: a for d, a in self.act.items() if (d - D0).days < up}
        act.update(act_over or {})
        fc = {s: {d: v for d, v in self.raws[s].items() if (d - D0).days < up} for s in sources}
        for d, v in (raw_over or {}).items():
            fc["src"][d] = v
        return M.PvModel(history_from(act), CFG, fc, skill_gate=gate)


# the worlds (kind, history days, seed, sigma): fixed, so every check below is deterministic
SKILL = World("skill", 40, 11)
SHADED = World("shaded", 40, 12)
SUMMER = World("summer", 60, 13)
GRADED = {"good": World("skill", 40, 21, sigma=0.25), "edge": World("skill", 40, 21, sigma=0.40),
          "bad": World("skill", 40, 21, sigma=0.60)}
GRADED_RANGE = {"good": (0.50, 0.85), "edge": (0.91, 1.00), "bad": (1.15, 2.50)}     # measured corrected / persistence MAE
RAW_T = {"skill": 14.0, "shaded": 10.0, "summer": 28.0}
SWITCH_AT = 24


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


def oracle(model, src: str, T: date):
    """The verdict recomputed from the public pieces only: forecasts, actual(), ratio() and the persistence recipe."""
    ec, ep = [], []
    f = model.forecasts[src]
    for k in range(1, 15):
        d = T - timedelta(days=k)
        fc, a = f.get(d), model.actual(d)
        if not (isinstance(fc, (int, float)) and not isinstance(fc, bool) and math.isfinite(fc) and fc >= 0.0) or a is None:
            continue
        r, _n = model.ratio(src, d)
        before = [model.actual(d - timedelta(days=j)) for j in range(1, 61)]
        before = [x for x in before if x is not None][:30]
        if r is None or len(before) < 5:
            continue
        est, _ = stats.robust_ewma(list(reversed(before)), 0.3, 3.0, 28, 0.5)
        ec.append(abs(a - fc * r))
        ep.append(abs(a - est))
    return len(ec), (sum(ec) / len(ec) if ec else None), (sum(ep) / len(ep) if ep else None)


def persistence_oracle(W: World, T: date):
    days = [W.act[day(i)] for i in range(W.n)][-30:]
    est, _ = stats.robust_ewma(days, 0.3, 3.0, 28, 0.5)
    sig = max(stats.robust_sigma(days, 1.0), 0.35 * est)
    return max(0.0, est - 1.2816 * sig), est, est + 1.2816 * sig


def close(a, b, tol=0.006) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


# ---------------------------------------------------------------------------------------------------------------------
def sec_pure(M, rec: Rec) -> None:
    rec.section("[1] the comparison and the constants")
    rec("constants: 14 days, 8 comparable days at least, margin 0.9",
        (M.SKILL_GATE_DAYS, M.SKILL_GATE_MIN_DAYS, M.SKILL_GATE_MARGIN) == (14, 8, 0.9))
    rec("exactly at the margin keeps (9.0 against 10.0); a hair above does not",
        M.skill_gate_keeps(9.0, 10.0) is True and M.skill_gate_keeps(9.0000001, 10.0) is False)
    rec("clearly better keeps, equal does not, worse does not", M.skill_gate_keeps(1.0, 10.0) is True
        and M.skill_gate_keeps(10.0, 10.0) is False and M.skill_gate_keeps(20.0, 10.0) is False)
    rec("0 against 0 keeps (perfect and flat); any error against a perfect persistence does not",
        M.skill_gate_keeps(0.0, 0.0) is True and M.skill_gate_keeps(0.1, 0.0) is False)
    nan = float("nan")
    rec("a NaN on either side fails closed", M.skill_gate_keeps(nan, 1.0) is False and M.skill_gate_keeps(1.0, nan) is False)
    # the whole decision pivots exactly on the margin, end to end: set the margin a hair either side of the measured ratio
    W = GRADED["good"]
    gv = W.model(M, True).skill_gate_verdict("src", W.T)
    ratio = gv.mae_corrected / gv.mae_persistence
    saved = M.SKILL_GATE_MARGIN
    try:
        M.SKILL_GATE_MARGIN = ratio * (1.0 + 1e-9)
        up = W.model(M, True).skill_gate_verdict("src", W.T).keep
        M.SKILL_GATE_MARGIN = ratio * (1.0 - 1e-9)
        down = W.model(M, True).skill_gate_verdict("src", W.T).keep
    finally:
        M.SKILL_GATE_MARGIN = saved
    rec("end to end: keep flips exactly where the margin crosses the measured MAE ratio", up is True and down is False,
        f"ratio {ratio:.6f} up={up} down={down}")


def sec_kept(M, rec: Rec) -> None:
    rec.section("[2] real skill: kept, identical to the ungated forecast")
    W = SKILL
    on, off = W.model(M, True), W.model(M, False)
    raw = {"src": RAW_T["skill"]}
    gv = on.skill_gate_verdict("src", W.T)
    rec("the verdict: BEAT_PERSISTENCE over 14 comparable days, corrected MAE below 0.9 x persistence",
        gv.keep and gv.reason == M.GATE_REASON_BEAT and gv.n_days == 14 and gv.mae_corrected < 0.9 * gv.mae_persistence,
        str(gv))
    a, b = on.forecast_day(W.T, raw), off.forecast_day(W.T, raw)
    rec("kept: the published forecast is bit-identical to the ungated one (to_dict and notes)",
        a.to_dict() == b.to_dict() and a.notes == b.notes)
    rec("kept: the source is the forecast source, not persistence; a ratio and a raw value are reported",
        a.source == "src" and a.raw_kwh == raw["src"] and a.ratio is not None and a.label != "INSUFFICIENT")
    rec("kept: no gate note", not any("persistence" in n for n in a.notes), str(a.notes))
    d = a.to_dict()
    rec("kept: p10 < p50 < p90, all finite, and the band is the corrected forecast's own (it holds >= 70 % of the "
        "corrected walk-forward residuals)", all(math.isfinite(d[k]) for k in ("p10", "p50", "p90")) and d["p10"] < d["p50"] < d["p90"]
        and _band_holds(on, W.T, a), str(d))
    rec("the verdict equals an independent recomputation from the public pieces", _oracle_ok(on, "src", W.T))
    lo90, hi90 = band_oracle(on, W.T, a.p50)
    rec("kept: p10 and p90 equal the band recomputed from the corrected walk-forward residuals (not from the raw ones)",
        close(d["p10"], lo90) and close(d["p90"], hi90), f"{d['p10']} {d['p90']} vs {lo90:.3f} {hi90:.3f}")


def _band_holds(model, T: date, pf) -> bool:
    rel = [(ac - c) / c for _d, _f, c, ac in model.walk_forward("src", T, 90) if c > 0.5]
    if not rel:
        return False
    lo, hi = pf.p10 / pf.p50 - 1.0, pf.p90 / pf.p50 - 1.0
    return sum(1 for x in rel if lo <= x <= hi) / len(rel) >= 0.7


def band_oracle(model, T: date, point: float) -> tuple[float, float]:
    """The documented band of the corrected forecast, recomputed from the public walk-forward residuals: the 10 / 90 % quantiles
    of the relative residuals (never narrower than 1.2816 robust sigma, 0.45 sigma prior below 20 residuals), widened when it
    would not have held the last days."""
    wf = model.walk_forward("src", T, 90)
    rel = [(a - c) / c for _d, _f, c, a in wf if c > 0.5]
    if len(rel) >= 20:
        lo, hi = stats.quantile(rel, 0.10), stats.quantile(rel, 0.90)
        sig = stats.robust_sigma(rel, 0.05)
        lo, hi = min(lo, -1.2816 * sig), max(hi, 1.2816 * sig)
    else:
        lo, hi = -1.2816 * 0.45, 1.2816 * 0.45
    recent = [(a - c) / c for _d, _f, c, a in wf[-21:] if c > 0.5]
    if len(recent) >= 10:
        cov = sum(1 for x in recent if lo <= x <= hi) / len(recent)
        if cov < 0.70:
            infl = min(1.5, 0.80 / max(cov, 0.4))
            lo, hi = lo * infl, hi * infl
    return max(0.0, point * (1 + max(lo, -0.95))), point * (1 + hi)


def _oracle_ok(model, src: str, T: date) -> bool:
    n, mc, mp = oracle(model, src, T)
    gv = model.skill_gate_verdict(src, T)
    if n < 8:
        return gv.n_days == n and gv.mae_corrected is None and gv.mae_persistence is None and gv.keep is False
    return gv.n_days == n and abs(gv.mae_corrected - mc) < 1e-9 and abs(gv.mae_persistence - mp) < 1e-9


def sec_shaded(M, rec: Rec) -> None:
    rec.section("[3] no skill (a shade-capped array): persistence, LOW, an honest finite band, one note line")
    W = SHADED
    on, off = W.model(M, True), W.model(M, False)
    raw = {"src": RAW_T["shaded"]}
    gv = on.skill_gate_verdict("src", W.T)
    rec("the verdict: NOT_BEATEN over 14 comparable days (corrected MAE far above persistence)",
        (not gv.keep) and gv.reason == M.GATE_REASON_NOT_BEATEN and gv.n_days == 14 and gv.mae_corrected > gv.mae_persistence, str(gv))
    pf = on.forecast_day(W.T, raw)
    d = pf.to_dict()
    rec("persistence is published: source 'persistence', no raw value, no ratio, LOW confidence, usable",
        pf.source == "persistence" and pf.raw_kwh is None and pf.ratio is None and pf.label == "LOW" and d["usable"] is True
        and pf.confidence == 0.3, f"{pf.source} {pf.label}")
    rec("p10 <= p50 <= p90, all finite, p10 >= 0", all(math.isfinite(d[k]) for k in ("p10", "p50", "p90"))
        and 0.0 <= d["p10"] <= d["p50"] <= d["p90"], str(d))
    p10, p50, p90 = persistence_oracle(W, W.T)
    rec("the band is the persistence estimate's own (recomputed from the actuals)",
        close(d["p10"], p10) and close(d["p50"], p50) and close(d["p90"], p90), f"{d['p10']} {d['p50']} {d['p90']} vs {p10} {p50} {p90}")
    ref = off._persistence(W.T, [])
    rec("... and identical to the model's own persistence output", (pf.p10, pf.p50, pf.p90) == (ref.p10, ref.p50, ref.p90)
        and pf.n_pairs == ref.n_pairs)
    gate_notes = [n for n in pf.notes if "has not beaten persistence" in n]
    rec("exactly one plain note line says the corrected forecast has not beaten persistence recently; the generic "
        "'no forecast correction available' line is not used", len(gate_notes) == 1 and len(pf.notes) == 1
        and "persistence only: no forecast correction available" not in pf.notes and "recently" in gate_notes[0], str(pf.notes))
    rec("the plausibility block is the ordinary one (verdict OK, the ceilings, nothing rejected)",
        d["plausibility"]["verdict"] == "OK" and d["plausibility"]["rejected"] == [] and "history_max" in d["plausibility"]["limits_kwh"])
    o = off.forecast_day(W.T, raw)
    rec("ungated (for contrast) the same inputs publish the corrected forecast from the source", o.source == "src" and o.ratio is not None)
    rec("the verdict equals an independent recomputation", _oracle_ok(on, "src", W.T))


def sec_graded(M, rec: Rec) -> None:
    rec.section("[4] graded skill: the 0.9 margin end to end")
    for name, want_keep in (("good", True), ("edge", False), ("bad", False)):
        W = GRADED[name]
        on = W.model(M, True)
        gv = on.skill_gate_verdict("src", W.T)
        lo, hi = GRADED_RANGE[name]
        ratio = None if gv.mae_persistence in (None, 0) else gv.mae_corrected / gv.mae_persistence
        rec(f"world '{name}' is what it claims: corrected MAE / persistence MAE in [{lo}, {hi}]",
            ratio is not None and lo <= ratio <= hi, f"ratio {ratio}")
        rec(f"world '{name}': keep == {want_keep}", gv.keep is want_keep, str(gv))
        pf = on.forecast_day(W.T, {"src": 14.0})
        rec(f"world '{name}': published source is {'the forecast source' if want_keep else 'persistence (LOW)'}",
            (pf.source == "src") if want_keep else (pf.source == "persistence" and pf.label == "LOW"), pf.source)


def sec_fail_closed(M, rec: Rec) -> None:
    rec.section("[5] fail closed: too few comparable days, too few actual days")
    # the day-count boundary: a ratio needs 5 earlier pairs, so with k history days the comparable days are k - 5
    for n_hist, want_n, want_keep in ((12, 7, False), (13, 8, True)):
        W = World("skill", n_hist, 11)
        on, off = W.model(M, True), W.model(M, False)
        gv = on.skill_gate_verdict("src", W.T)
        rec(f"{n_hist} history days => {want_n} comparable days => keep={want_keep} "
            f"({'TOO_FEW_DAYS' if not want_keep else 'decided on the numbers'})",
            gv.n_days == want_n and gv.keep is want_keep
            and (gv.reason == M.GATE_REASON_TOO_FEW_DAYS if not want_keep else gv.reason == M.GATE_REASON_BEAT), str(gv))
        pf, ref = on.forecast_day(W.T, {"src": 14.0}), off.forecast_day(W.T, {"src": 14.0})
        if want_keep:
            rec(f"{n_hist} history days: the corrected forecast is published, identical to the ungated one",
                pf.source == "src" and pf.to_dict() == ref.to_dict())
        else:
            rec(f"{n_hist} history days: persistence, LOW, one note saying the comparison could not be made; the ungated "
                f"model would have published the corrected forecast",
                pf.source == "persistence" and pf.label == "LOW" and ref.source == "src"
                and len([n for n in pf.notes if "could not be compared" in n]) == 1 and len(pf.notes) == 1
                and f"{want_n} of 8" in pf.notes[0], str(pf.notes))
    for n_hist in (0, 3, 4):
        W = World("skill", n_hist, 11)
        a, b = W.model(M, True).forecast_day(W.T, {"src": 14.0}), W.model(M, False).forecast_day(W.T, {"src": 14.0})
        rec(f"{n_hist} actual days: INSUFFICIENT exactly as without the gate (source none, not usable, same dict)",
            a.label == "INSUFFICIENT" and a.source == "none" and a.to_dict()["usable"] is False and a.to_dict() == b.to_dict(),
            str(a.to_dict()))
    W = World("skill", 9, 11)       # 9 actual days, 4 comparable: persistence (it exists), not INSUFFICIENT
    pf = W.model(M, True).forecast_day(W.T, {"src": 14.0})
    rec("5..12 actual days: persistence is published (it exists), not INSUFFICIENT", pf.source == "persistence" and pf.label == "LOW")


def sec_rejected(M, rec: Rec) -> None:
    rec.section("[6] the plausibility guard is untouched and runs first")
    W = SKILL
    on, off = W.model(M, True), W.model(M, False)
    for what, raw in (("a raw value above the physical ceiling", 100.0), ("a corrected value above the all-time ceiling", 40.0)):
        a, b = on.forecast_day(W.T, {"src": raw}), off.forecast_day(W.T, {"src": raw})
        d = a.to_dict()
        rec(f"{what}: REJECTED, persistence, LOW, identical with and without the gate, no gate note",
            d["plausibility"]["verdict"] == "REJECTED" and a.source == "persistence" and a.label == "LOW"
            and d == b.to_dict() and any("REJECTED" in n for n in a.notes) and not any("has not beaten" in n for n in a.notes),
            str(d["plausibility"]))
    W = SHADED
    on = W.model(M, True, sources=("src", "src2"))
    off = W.model(M, False, sources=("src", "src2"))
    raw = {"src": 40.0, "src2": 4.0}
    a, b = on.forecast_day(W.T, raw), off.forecast_day(W.T, raw)
    d = a.to_dict()
    rej = d["plausibility"]["rejected"]
    rec("two sources, one REJECTED, the other chosen but without skill: persistence with BOTH notes and the REJECTED verdict",
        d["plausibility"]["verdict"] == "REJECTED" and [r["source"] for r in rej] == ["src"] and a.source == "persistence"
        and a.label == "LOW" and any("src forecast REJECTED" in n for n in a.notes)
        and len([n for n in a.notes if "has not beaten persistence" in n]) == 1, str(d))
    rec("... ungated, the same inputs publish the second source's corrected forecast (so the gate did change something)",
        b.source == "src2" and b.to_dict()["plausibility"]["verdict"] == "REJECTED")


def sec_bad_values(M, rec: Rec) -> None:
    rec.section("[7] NaN, inf, negative and bool values are ignored")
    W = SKILL
    bad = {"nan": float("nan"), "inf": float("inf"), "neg": -1.0, "bool": True}
    on, off = W.model(M, True), W.model(M, False)
    a, b = on.forecast_day(W.T, dict(bad)), off.forecast_day(W.T, dict(bad))
    rec("only bad raw values: persistence, one 'ignored' note per bad value, identical with and without the gate",
        a.source == "persistence" and sum(1 for n in a.notes if "ignored" in n) == 4 and a.to_dict() == b.to_dict(), str(a.notes))
    mixed = dict(bad)
    mixed["src"] = RAW_T["skill"]
    a, b = on.forecast_day(W.T, dict(mixed)), off.forecast_day(W.T, dict(mixed))
    rec("bad values next to a good source with skill: the good source is used and kept (identical with and without the gate)",
        a.source == "src" and a.to_dict() == b.to_dict() and sum(1 for n in a.notes if "ignored" in n) == 4)
    W2 = SHADED
    a = W2.model(M, True).forecast_day(W2.T, dict(bad, src=RAW_T["shaded"]))
    rec("bad values next to a good source WITHOUT skill: the gate still applies (persistence, the four ignore notes + one gate note)",
        a.source == "persistence" and sum(1 for n in a.notes if "ignored" in n) == 4
        and sum(1 for n in a.notes if "has not beaten" in n) == 1, str(a.notes))
    # the forecast HISTORY: days whose forecast is NaN / inf / negative / bool / missing are not scored
    T = W.T
    over = {T - timedelta(days=3): float("nan"), T - timedelta(days=4): float("inf"), T - timedelta(days=5): -2.0,
            T - timedelta(days=6): True, T - timedelta(days=7): None}
    gv = W.model(M, True, raw_over=over).skill_gate_verdict("src", T)
    rec("five unusable forecast-history days inside the window are not scored: 9 comparable days, a finite MAE",
        gv.n_days == 9 and gv.mae_corrected is not None and math.isfinite(gv.mae_corrected)
        and math.isfinite(gv.mae_persistence), str(gv))


def sec_leak(M, rec: Rec) -> None:
    rec.section("[8] no leakage from the target day or later")
    for W in (SKILL, SHADED):
        T = W.T
        raw = {"src": RAW_T[W.kind]}
        for gate in (True, False):
            base = W.model(M, gate)
            later_act = {day(W.n + k): v for k, v in zip(range(EXTRA_DAYS), (0.0, 999.0, 0.0, 999.0, 0.0, 999.0, 0.0))}
            later_raw = {day(W.n + k): v for k, v in zip(range(EXTRA_DAYS), (80.0, 0.5, 80.0, 0.5, 80.0, 0.5, 80.0))}
            varied = W.model(M, gate, upto=W.n + EXTRA_DAYS, act_over=later_act, raw_over=later_raw)
            plain = W.model(M, gate, upto=W.n + EXTRA_DAYS)
            a, b, c = base.forecast_day(T, raw), varied.forecast_day(T, raw), plain.forecast_day(T, raw)
            rec(f"{W.kind} world, gate {'on' if gate else 'off'}: the target day's and later actuals and forecasts change nothing "
                f"(forecast and verdict identical)", a.to_dict() == b.to_dict() == c.to_dict()
                and base.skill_gate_verdict("src", T) == varied.skill_gate_verdict("src", T) == plain.skill_gate_verdict("src", T),
                f"{a.to_dict()} vs {b.to_dict()}")
    # ... and a change INSIDE the window does matter (the check above is not vacuous)
    W = SKILL
    T = W.T
    inside = W.model(M, True, act_over={T - timedelta(days=2): 0.1}).skill_gate_verdict("src", T)
    rec("a change inside the window does change the verdict (the leak check is not vacuous)",
        inside != W.model(M, True).skill_gate_verdict("src", T))
    # earlier target days: the verdict for day k reads nothing from k onwards
    ok = True
    full = W.model(M, True, upto=W.n + EXTRA_DAYS)
    for i in (20, 25, 30):
        cut = W.model(M, True, upto=i)
        ok = ok and cut.skill_gate_verdict("src", day(i)) == full.skill_gate_verdict("src", day(i))
    rec("the verdict for an earlier day is the same with or without everything after it", ok)


def sec_contract(M, rec: Rec) -> None:
    rec.section("[9a] the contract: to_dict keys, the summary size, the date")
    for W, raw in ((SKILL, RAW_T["skill"]), (SHADED, RAW_T["shaded"])):
        pf = W.model(M, True).forecast_day(W.T, {"src": raw})
        d = pf.to_dict()
        summ = {k: v for k, v in d.items() if k in PV_TOMORROW_SUMMARY_KEYS}
        import json
        size = len(json.dumps(summ, separators=(",", ":")).encode("utf-8"))
        rec(f"{W.kind}: to_dict keys are exactly the pre-gate set and equal PV_TOMORROW_SUMMARY_KEYS; summary {size} <= "
            f"{MAX_SUMMARY_BYTES} bytes; the day is the requested day", set(d) == TO_DICT_KEYS == set(PV_TOMORROW_SUMMARY_KEYS)
            and size <= MAX_SUMMARY_BYTES and d["day"] == W.T.isoformat() and pf.day == W.T, f"{sorted(d)} {size}")
    rec("PV_TOMORROW_SUMMARY_KEYS is unchanged",
        PV_TOMORROW_SUMMARY_KEYS == frozenset(TO_DICT_KEYS))


def sec_regimes(M, rec: Rec) -> None:
    rec.section("[10] regimes")
    for kind, want_on_after in (("switch_on", True), ("switch_off", False)):
        W = World(kind, 70, 31, switch=SWITCH_AT)
        full = W.model(M, True, upto=W.n)
        keeps = {i: full.skill_gate_verdict("src", day(i)).keep for i in range(16, 64)}
        if want_on_after:
            flip = next((i for i in range(SWITCH_AT, 64) if keeps[i]), None)
            before_ok = not any(keeps[i] for i in range(16, SWITCH_AT + 1))
            rec("skill appears after three weeks: persistence before and at the switch, the corrected forecast again "
                f"within the window (flip {None if flip is None else flip - SWITCH_AT} days after the switch), then it stays",
                before_ok and flip is not None and 4 <= flip - SWITCH_AT <= M.SKILL_GATE_DAYS
                and all(keeps[i] for i in range(flip, 64)), f"flip {flip}")
        else:
            flip = next((i for i in range(SWITCH_AT, 64) if not keeps[i]), None)
            before_ok = all(keeps[i] for i in range(20, SWITCH_AT))
            rec("skill is lost after three weeks: the corrected forecast until the switch, persistence within the window "
                f"(flip {None if flip is None else flip - SWITCH_AT} days after the switch), then it stays",
                before_ok and flip is not None and 1 <= flip - SWITCH_AT <= M.SKILL_GATE_DAYS
                and not any(keeps[i] for i in range(flip, 64)), f"flip {flip}")
    W = SUMMER
    full = W.model(M, True, upto=W.n)
    off = W.model(M, False, upto=W.n)
    days = range(40, W.n)
    verdicts = {i: full.skill_gate_verdict("src", day(i)) for i in days}
    rec("a summer-like world (large, varied output; a steady ratio): the gate keeps the corrected path on every one of 20 days",
        all(v.keep for v in verdicts.values()), str([i for i, v in verdicts.items() if not v.keep]))
    same = all(full.forecast_day(day(i), {"src": 28.0}).to_dict() == off.forecast_day(day(i), {"src": 28.0}).to_dict() for i in days)
    rec("... and those 20 published forecasts are identical to the ungated ones", same)
    W = SHADED
    full = World("shaded", 60, 12).model(M, True, upto=60)
    rec("a shaded world: the gate refuses the corrected path on every one of 20 days",
        not any(full.skill_gate_verdict("src", day(i)).keep for i in range(40, 60)))


def sec_oracle(M, rec: Rec) -> None:
    rec.section("[10b] the verdict is what the public pieces say, on every world")
    ok, bad = True, []
    for name, W in (("skill", SKILL), ("shaded", SHADED), ("good", GRADED["good"]), ("edge", GRADED["edge"]), ("bad", GRADED["bad"])):
        m = W.model(M, True)
        for i in (W.n - 2, W.n):
            if not _oracle_ok(m, "src", day(i)):
                ok = False
                bad.append((name, i))
    rec("skill_gate_verdict equals the recomputation for five worlds and two target days each", ok, str(bad))


def sec_switch(M, rec: Rec) -> None:
    rec.section("[11] the switch")
    h = history_from({day(i): 5.0 for i in range(3)})
    rec("None takes the module default (documented: PV_SKILL_GATE_DEFAULT)", M.PvModel(h, CFG, {}).skill_gate is M.PV_SKILL_GATE_DEFAULT)
    rec("the documented default is " + str(EXPECT_DEFAULT), M.PV_SKILL_GATE_DEFAULT is EXPECT_DEFAULT)
    rec("True and False are taken as given", M.PvModel(h, CFG, {}, skill_gate=True).skill_gate is True
        and M.PvModel(h, CFG, {}, skill_gate=False).skill_gate is False)
    refused = []
    for bad in ("yes", 1, 0, [], "False"):
        try:
            M.PvModel(h, CFG, {}, skill_gate=bad)
            refused.append(bad)
        except ValueError:
            pass
    rec("anything that is not a bool or None is refused (ValueError), never read as truthy", not refused, str(refused))
    saved = M.PV_SKILL_GATE_DEFAULT
    try:
        M.PV_SKILL_GATE_DEFAULT = not saved
        flipped = M.PvModel(h, CFG, {}).skill_gate is (not saved)
    finally:
        M.PV_SKILL_GATE_DEFAULT = saved
    rec("the default is read when the model is built (changing the module constant changes a default-built model)", flipped)
    W = SHADED
    rec("with the gate switched OFF the model publishes exactly what it published before the gate existed (corrected, from the source)",
        W.model(M, False).forecast_day(W.T, {"src": RAW_T["shaded"]}).source == "src")


BATTERY = (sec_pure, sec_kept, sec_shaded, sec_graded, sec_fail_closed, sec_rejected, sec_bad_values, sec_leak, sec_contract,
           sec_regimes, sec_oracle, sec_switch)


def battery(M, rec: Rec) -> None:
    for fn in BATTERY:
        try:
            fn(M, rec)
        except Exception as exc:          # a mutant that crashes is as detected as one that answers wrongly
            rec(f"{fn.__name__} raised {type(exc).__name__}: {exc}", False)


# ---------------------------------------------------------------------------------------------------------------------
# mutants of intelligence/pv.py, applied in memory (the file on disk is never touched); each `old` must occur exactly once
MUTANTS = [
    ("comparison direction flipped", "return mae_corrected <= SKILL_GATE_MARGIN * mae_persistence",
     "return mae_corrected >= SKILL_GATE_MARGIN * mae_persistence"),
    ("strict instead of inclusive comparison", "return mae_corrected <= SKILL_GATE_MARGIN * mae_persistence",
     "return mae_corrected < SKILL_GATE_MARGIN * mae_persistence"),
    ("margin on the wrong side of the inequality", "return mae_corrected <= SKILL_GATE_MARGIN * mae_persistence",
     "return mae_corrected * SKILL_GATE_MARGIN <= mae_persistence"),
    ("margin 0.9 -> 0", "SKILL_GATE_MARGIN = 0.9 ", "SKILL_GATE_MARGIN = 0.0 "),
    ("margin 0.9 -> 2", "SKILL_GATE_MARGIN = 0.9 ", "SKILL_GATE_MARGIN = 2.0 "),
    ("margin 0.9 -> 1.0", "SKILL_GATE_MARGIN = 0.9 ", "SKILL_GATE_MARGIN = 1.0 "),
    ("window one day short", "for k in range(1, SKILL_GATE_DAYS + 1):", "for k in range(1, SKILL_GATE_DAYS):"),
    ("window one day long", "for k in range(1, SKILL_GATE_DAYS + 1):", "for k in range(1, SKILL_GATE_DAYS + 2):"),
    ("window includes the target day (leak)", "for k in range(1, SKILL_GATE_DAYS + 1):", "for k in range(0, SKILL_GATE_DAYS):"),
    ("window reaches past the target day (leak)", "for k in range(1, SKILL_GATE_DAYS + 1):", "for k in range(-1, SKILL_GATE_DAYS - 1):"),
    ("min comparable days 8 -> 0", "SKILL_GATE_MIN_DAYS = 8 ", "SKILL_GATE_MIN_DAYS = 0 "),
    ("min comparable days 8 -> 1", "SKILL_GATE_MIN_DAYS = 8 ", "SKILL_GATE_MIN_DAYS = 1 "),
    ("min comparable days off by one (<=)", "if n < SKILL_GATE_MIN_DAYS:", "if n <= SKILL_GATE_MIN_DAYS:"),
    ("fail-open default (too few days keeps the corrected forecast)",
     "return SkillGateVerdict(source, day, n, None, None, False, GATE_REASON_TOO_FEW_DAYS)",
     "return SkillGateVerdict(source, day, n, None, None, True, GATE_REASON_TOO_FEW_DAYS)"),
    ("comparable-day count is the window length", "n = len(err_c)", "n = SKILL_GATE_DAYS"),
    ("compare against the raw forecast instead of persistence", "err_p.append(abs(act - p))", "err_p.append(abs(act - fc))"),
    ("signed instead of absolute corrected error", "err_c.append(abs(act - fc * r))", "err_c.append(act - fc * r)"),
    ("signed instead of absolute persistence error", "err_p.append(abs(act - p))", "err_p.append(act - p)"),
    ("gate before the REJECTED check",
     "            point_c = raw * r\n",
     "            point_c = raw * r\n            if self.skill_gate and not self.skill_gate_verdict(src, day).keep:\n"
     "                return self._persistence(day, notes + ['gate'], default_note=False)\n"),
    ("MEDIUM confidence kept on the fallback", "        pf.plausibility = verdict\n        return pf\n",
     "        pf.plausibility = verdict\n        pf.confidence, pf.label = 0.6, 'MEDIUM'\n        return pf\n"),
    ("the note line dropped", "notes + [note], default_note=False", "notes, default_note=False"),
    ("the generic persistence note kept as well", "notes + [note], default_note=False", "notes + [note], default_note=True"),
    ("band from the wrong residuals (raw instead of corrected)",
     "rel = [(a - c) / c for _d, _f, c, a in wf if c > 0.5]\n        if len(rel) >= 20:",
     "rel = [(a - f) / f for _d, f, _c, a in wf if f > 0.5]\n        if len(rel) >= 20:"),
    ("persistence band without its 35 % floor", "sig = max(stats.robust_sigma(days, 1.0), 0.35 * est)",
     "sig = stats.robust_sigma(days, 1.0)"),
    ("persistence reads the day it predicts (leak)", "        d = day - timedelta(days=1)\n        while len(days) < 30",
     "        d = day\n        while len(days) < 30"),
    ("gate scores the persistence of the NEXT day (leak)", "p = self._persistence_estimate(d)",
     "p = self._persistence_estimate(d + timedelta(days=1))"),
    ("ratio of the next day in the gate (the day's own pair leaks)", "r, _n = self.ratio(source, d)",
     "r, _n = self.ratio(source, d + timedelta(days=1))"),
    ("ratio known only at the target day (look-ahead)", "r, _n = self.ratio(source, d)", "r, _n = self.ratio(source, day)"),
    ("the gate is never applied", "if self.skill_gate:", "if False:"),
    ("the gate is always applied (the switch is ignored)", "if self.skill_gate:", "if True:"),
    ("an explicit switch is ignored", "self.skill_gate = PV_SKILL_GATE_DEFAULT if skill_gate is None else skill_gate",
     "self.skill_gate = PV_SKILL_GATE_DEFAULT"),
    ("a bool forecast counts as a number", "isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0.0",
     "isinstance(x, (int, float)) and math.isfinite(x) and x >= 0.0"),
    ("an infinite forecast counts as a number", "isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0.0",
     "isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0.0"),
    ("a negative forecast counts as a number", "isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x >= 0.0",
     "isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)"),
    ("the too-few-days note is never used", "if gv.reason == GATE_REASON_TOO_FEW_DAYS:", "if False:"),
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


def run_mutants(rec: Rec) -> None:
    rec.section(f"[12] mutation: {len(MUTANTS)} mutants of intelligence/pv.py, applied in memory, each must be caught")
    src = PV_PATH.read_text(encoding="utf-8")
    rec("the unmodified source, exec'd as a module, passes the whole battery (the mutants' baseline)",
        _battery_fails(load_variant(src, "pv_baseline")) == [])
    killed = 0
    for i, (name, old, new) in enumerate(MUTANTS):
        n = src.count(old)
        if n != 1:
            rec(f"mutant '{name}' applies exactly once in pv.py", False, f"{n} occurrences of {old!r}")
            continue
        try:
            fails = _battery_fails(load_variant(src.replace(old, new, 1), f"pv_mutant_{i}"))
        except Exception as exc:        # a mutant that does not even import is detected too
            fails = [f"import: {type(exc).__name__}"]
        finally:
            sys.modules.pop(f"intelligence.pv_mutant_{i}", None)
        rec(f"mutant '{name}' is caught ({len(fails)} check(s) noticed)", bool(fails), "SURVIVED")
        killed += 1 if fails else 0
    rec(f"{killed} of {len(MUTANTS)} mutants killed, at least 15", killed == len(MUTANTS) and killed >= 15, f"{killed}")
    sys.modules.pop("intelligence.pv_baseline", None)


def _battery_fails(M) -> list[str]:
    r = Rec(False)
    battery(M, r)
    return r.fails


def sec_cycle(rec: Rec) -> None:
    rec.section("[9b] a whole cycle: pv_tomorrow's item, valid_until and summary with the gate on and off")
    import json
    import _cycle_fixtures as cf
    from intelligence.shadow_cycle import run_cycle
    saved = REAL.PV_SKILL_GATE_DEFAULT
    out = {}
    try:
        for gate in (True, False):
            REAL.PV_SKILL_GATE_DEFAULT = gate
            out[gate] = run_cycle(cf.cycle_inputs()).item("pv_tomorrow")
    finally:
        REAL.PV_SKILL_GATE_DEFAULT = saved
    on, off = out[True], out[False]
    rec("pv_tomorrow is an OK numeric forecast with the gate on and off (the item, its status and its reason codes keep their shape)",
        on.status == off.status and on.reason_codes == off.reason_codes and on.value is not None and off.value is not None
        and all(math.isfinite(x) for x in (on.value, on.p10, on.p90)), f"{on.status} {off.status}")
    rec("valid_until (date scoping and freshness) is identical with the gate on and off", on.valid_until == off.valid_until
        and on.valid_until is not None)
    ok = all(set(v.summary) <= PV_TOMORROW_SUMMARY_KEYS and
             len(json.dumps(dict(v.summary), separators=(",", ":")).encode("utf-8")) <= MAX_SUMMARY_BYTES for v in (on, off))
    rec("the summary keys stay inside PV_TOMORROW_SUMMARY_KEYS and the summary stays within 2048 bytes, both ways", ok)
    rec("the day in the summary is the same with the gate on and off", on.summary.get("day") == off.summary.get("day"))
    rec("the gate really is exercised in the cycle: OFF publishes the forecast source, ON the persistence fallback "
        f"(sources: OFF {off.summary.get('source')}, ON {on.summary.get('source')}); both label and confidence are valid",
        off.summary.get("source") == "synthetic_forecast" and on.summary.get("source") == "persistence"
        and on.confidence == "LOW" and off.confidence in ("LOW", "MEDIUM", "HIGH"))


def main() -> int:
    rec = Rec(True)
    battery(REAL, rec)
    sec_cycle(rec)
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
    print("all PV skill-gate checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
