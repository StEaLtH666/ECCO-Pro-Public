#!/usr/bin/env python3
"""PV persistence-skill gate: the PLANNING fix (intelligence/pv.py, engine.py, shadow_cycle.py). SYNTHETIC data only (fictional
numbers; the worlds come from the frozen generators intelligence/tests/_pv_worlds.py and _pv_worlds2.py).

The defect (docs/intelligence/INTELLIGENCE_PV_SKILL_GATE.md, "Limits"): when the gate falls back to persistence, pv_tomorrow can be
HIGHER than the corrected value (a bright spell followed by a dull day) and its p10 far above a widened corrected p10, so the
overnight charge target fell from 80 to 70 percent with the gate ON: the unsafe direction. The fix keeps the PUBLISHED forecast as it
was, caps confidence at LOW, adds a reason code, and protects the charge target in two independent layers: (1) planning sizes on a band
that is never above persistence or the ungated corrected value and keeps the ungated spread below the median (so the Planner's
pessimistic PV p50 - k (p50 - p10) cannot rise, whatever k); (2) a guard computes the advice a second time exactly as the gate-OFF
engine would have and publishes the higher recommended target, so the target is never below the gate-OFF one BY CONSTRUCTION (V1
engine and shadow cycle). Round 1 had only the per-quantile minimum; round 2 added both layers (owner decision of 20 Nov 2026).

  [1]  the 80 -> 70 world (whole engine): the target with the gate ON is not below the target with it OFF; the published forecast
       is persistence (LOW, 0.3), exactly as before
  [2]  the visible trace: LOW cap (<= 0.45), PV_SKILL_GATE_FALLBACK in downgrade_reasons, advice reasons and uncertainty, the plain
       text; absent when the gate is OFF, keeps the corrected forecast, or the forecast is REJECTED
  [3]  the planning values of a PvForecast (model level): per quantile never above persistence or the ungated corrected value, the
       spread below the median kept, sorted; the inflation is the ungated one; equal to the published ones when the gate is OFF or
       keeps; to_dict unchanged
  [4]  conservative_band, the pure function (unsorted inputs, idempotence, never above either input, spread kept, clamp at zero)
  [5]  what the engine hands the Planner (PvDay values, today's remaining PV, the band inflation), by a spy on Planner
  [6]  the switch and the contract: default OFF, no SiteConfig field, PvModel signature, to_dict keys
  [7]  the shadow cycle: V1 target, charge target, plan headroom, morning SOC, published pv_tomorrow, PV credit label
  [8]  published forecasts are unchanged by the fix (digests recorded from the pre-fix tree 54bca39)
  [9]  the property test: 300 worlds (seeds 7000-7299, the round-1 pre-registered range), invariants I1-I8
  [9b] the same on a second range (seeds 8000-8299); both ranges are BURNED for the round-2 decision (they informed it) and stay as regression
  [9c] ROUND 2: 600 unseen worlds (seeds 9000-9599, pre-registered, eight regimes) and 200 shadow-cycle worlds, invariants I1-I9
  [10] mutation: the mutants of the new logic applied in memory, each must be caught
  [11] the planning band keeps the ungated spread (k above 1) and the Planner's pessimistic PV never rises (a hand-built Planner case)
  [12] the by-construction guard of the ENGINE: the advice is computed on the planning values and exactly as the gate-OFF engine would
       have computed it, the higher recommended target is published (a tie keeps the planning run); injected worst-case bands
  [13] the same guard in the SHADOW CYCLE (the charge target), with a lowered planning target injected
  [14] today's remaining PV in the planning run never exceeds the ungated re-anchored value (the 2 kWh threshold), and the pure rule of
       the guard (prefers_ungated)
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import math
import sys
import types
from dataclasses import fields, replace
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _pv_worlds as W  # noqa: E402
import _pv_worlds2 as W2  # noqa: E402
import test_intel_pv_skill_gate as G  # noqa: E402  (its worlds and Rec; importing it runs nothing)
from intelligence import engine as REAL_ENGINE  # noqa: E402
from intelligence import pv as REAL_PV  # noqa: E402
from intelligence import shadow_cycle as REAL_CYCLE  # noqa: E402
from intelligence.advisor import LiveInputs, Planner, PvDay  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.replay import inputs_from_history  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402

PATHS = {"pv": ROOT / "intelligence" / "pv.py", "engine": ROOT / "intelligence" / "engine.py",
         "cycle": ROOT / "intelligence" / "shadow_cycle.py"}
CODE = "PV_SKILL_GATE_FALLBACK"
# The Planner's pessimistic PV path is p50 - k * (p50 - p10) with k = band_kappa x 1.5 (LOW widening) x band inflation: above 1 it
# EXTRAPOLATES below p10, so a planning band whose median was lowered but whose p10 was not (persistence's median below the corrected
# one, the corrected p10 below persistence's) can give a pessimistic PV marginally HIGHER than the ungated one. On the pre-registered
# range this happened in two worlds, each time by one point of the UNROUNDED pessimistic-case target; the recommended target (rounded
# up to the target step) was never lowered in 300 worlds. Pinned here so that it cannot get worse unnoticed; stated in the gate doc.
KNOWN_I3_RESIDUAL: dict[int, float] = {}          # EMPTY since round 2: the spread-preserving planning band closed the residual that the
# round-1 per-quantile rule left (seeds 7213, 7267 and 8055, 8077, 8127, 8187, 8254 of the two burned ranges: a shortfall of 1 to 3 points)
# The same effect moved the RECOMMENDED target once on the second range (80 -> 75 in world 8077). EMPTY since round 2: the spread-preserving
# band closes it and the guard (section [12]) makes the recommended target never lower by construction.
KNOWN_I1_RESIDUAL: dict[int, float] = {}
SEEDS = range(7000, 7300)
SEEDS2 = range(8000, 8300)                    # the second range of round 1 (same generator); BURNED for the round-2 decision, kept as regression
SEEDS3 = range(9000, 9600)                    # ROUND 2, pre-registered before the code under test ran on it: 600 worlds, eight regimes (_pv_worlds2.py)
CYCLE_SEEDS = range(9000, 9600, 3)            # ... and 200 shadow-cycle worlds of the same range
PIN_SEED_80_70 = (643, 120)                  # two worlds in which the old gate turned an 80 percent target into 70
KEPT_SEEDS = (5, 11, 17)                     # a source with skill: the gate keeps the corrected forecast
REJECTED_SEEDS = (23, 74)                    # an implausible raw value: REJECTED by the unchanged guard, the gate is not reached
INFLATION_SEEDS = (16, 28, 82, 86)           # the ungated band was widened (inflation > 1) and the gate fell back
DAYTIME_SEEDS = (8, 6, 9)                    # a daytime run: today's remaining PV is re-anchored; both days fall back
REANCHOR_SEEDS = (4, 8, 12, 24)              # runs at 10:00 and 13:30 (11 to 54 percent of the day's PV already elapsed)
MINI = (643, 120, 5, 23, 16, 28, 8, 6, 9)    # the worlds of the mutation battery's per-world invariants
# the digest of what the PRE-FIX tree (commit 54bca39) published about PV, (gate OFF, gate ON) per world: report["pv"] and the
# scoreable pv_kwh:day records. The fix must leave every one of them as it was.
PINNED = {
    5: ("6e4ff0c25bf23573e88819744793995dae5e2de9c7672dcdc34cdb5afba25c89",
        "6e4ff0c25bf23573e88819744793995dae5e2de9c7672dcdc34cdb5afba25c89"),
    23: ("1f169593522d568bfafc41cfee87059850079f03b4bf0d6c1b0c8c7355e4d0b9",
         "1f169593522d568bfafc41cfee87059850079f03b4bf0d6c1b0c8c7355e4d0b9"),
    120: ("cc82d99a8e4f1916e1262d95821a2bd3bbaf015b77f4f5eaee02a87ceefb5c1c",
          "0c042875510a70147a993baa0d769baef2bd97c27691c35229af6347b5964b9a"),
    643: ("57045b7b80d963bdaa25e3056c4a20cb8a5966f75947d411d503eac64b86bd0a",
          "9282fb467c3c3f08790f370269ec6ceea6f102e929913c0632b1e7da3fe85a71"),
    16: ("927018957ee54139befa1da15549648134495ed40b5815f32bf80138d5795780",
         "9023aff5758f0ec0fbeeda23a1a3892249d2e67abe5f005ba2c78e9c12b373b2"),
    28: ("2e9951b7921a5c8637e96b1a19e2cf76b61a17151b5aa16888720036196335e8",
         "c96b82e30b58a66fa678980c3caa3575a3a46ca325e36c3294ced7205a7a0631"),
    8: ("99307450586383268b058d55e03dadb14ba42f3212b3804310841a4b018fa433",
        "3d900b963a310c7a66a56f873b1bdd5b3c9e4919955a0f100b731dedb52edf30"),
    6: ("16c859f4f8f38b67de923d29fd02a6610d68ef370272d3de8e7f0ed956cb9b23",
        "174e654074057081a0122f34a478e66b655b9616952e8f74e1ad4abf4b7a6989"),
    9: ("b23de95a4a96892aaa55f09cfd4e4a62c732d17335e44ee9cfdd18cd0033e02e",
        "0c3cf5ebc1c313a22c3a3c3edab9f46895d9b4a42868033898511b19b89afa72"),
}
PINNED_RANGE = {"off": "f5f07f0588d52edf0760686917adb3b0e48d24bff80dccb1417c29a043f61a5e",
                "on": "c20ce0e31b12d91bc66f4ac7fe18a9caa0a2f1d2065a891fd11e28793a735b0e"}          # seeds 7000-7299, pre-fix tree
PINNED_RANGE2 = {"off": "c4adc3c2addbe9c5d11e44b8f0551d2328c229fa3484d8fa43ea2446d99a18d0",
                 "on": "0f3be40e12cf7597fa68cb60713e9dd7aababdc404c3c52caf786b4be3a4fdb7"}         # seeds 8000-8299, pre-fix tree
PINNED_RANGE3 = {"off": "54d19a088f2d0081d5a96638aeb49cbf6ee7724f654a91671930593b3a9aeebf",
                 "on": "0c0416817e9396c3e729ea6118fa8d63096143d5deef22c7d851a89393c461e3"}         # seeds 9000-9599 (round 2), pre-fix tree


class Stack:
    """The code under test: the pv module M, the engine module E and the shadow-cycle module C (the real ones, or in-memory variants)."""

    def __init__(self, M, E, C):
        self.M, self.E, self.C = M, E, C
        self.cache: dict = {}

    @property
    def engine_stack(self):
        return (self.E.IntelligenceEngine, self.M.PvModel)


REAL = Stack(REAL_PV, REAL_ENGINE, REAL_CYCLE)

# The repository's offline-suite convention (registry/tests/test_offline_suite_exit_codes.py): check() records every failure in
# FAILURES and main() turns FAILURES into a non-zero exit. The sections below report through `rec`, which calls check() when loud.
FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


class _Loud(G.Rec):
    """The loud recorder of the real run: every result goes through check()."""

    def __init__(self):
        super().__init__(True)

    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        check(name, ok, detail)
        if not ok:
            self.fails.append(name)
_WORLDS: dict[int, dict] = {}


def world(seed: int) -> dict:
    if seed not in _WORLDS:
        _WORLDS[seed] = W.build_world(seed)
    return _WORLDS[seed]


def run(w: dict, gate: bool, S: Stack) -> dict:
    """The engine report (cached per stack for the named development worlds; reports are never modified)."""
    key = (w["seed"], gate)
    if w["seed"] < 1000 and key in S.cache:
        return S.cache[key]
    r = W.run_world(w, gate, S.engine_stack)
    if w["seed"] < 1000:
        S.cache[key] = r
    return r


def model_for(w: dict, gate: bool, S: Stack):
    now = w["now"]
    known = w["hist"].truncated(now)
    d0 = now.astimezone(W.WTZ).date()
    fck = {s: {d: v for d, v in tab.items() if d <= d0} for s, tab in w["fc"].items()}
    return S.M.PvModel(known, W.WCFG, fck, skill_gate=gate)


def raws(w: dict) -> list[tuple]:
    return [(w["today"], {"src": w["fc"]["src"][w["today"]]}), (w["tomorrow"], {"src": w["fc"]["src"][w["tomorrow"]]})]


def days(r: dict) -> list[str]:
    return sorted(k for k in r["pv"] if k != "today_reanchor")


def fb_days(r0: dict, r1: dict) -> list[str]:
    """The days on which the gate (ON) published persistence where the ungated engine (OFF) published the corrected forecast."""
    return [d for d in days(r1) if r1["pv"][d]["source"] == "persistence" and r0["pv"][d]["source"] != "persistence"]


def codes(r: dict, key: str) -> list[str]:
    return [x.get("code") for x in (r.get("recommended") or {}).get(key, [])]


def canon(r: dict) -> str:
    return json.dumps(r, sort_keys=True, default=str)


def band_of(pf) -> tuple:
    return (pf.p10, pf.p50, pf.p90)


def lower_of(a: tuple, b: tuple) -> tuple:
    """The oracle of the planning band (published a, ungated corrected b): per quantile the lower value, p10 additionally moved down by
    the amount the median was lowered below the corrected one (the corrected spread below the median is kept), clamped at zero, sorted."""
    lo = [min(x, y) for x, y in zip(a, b)]
    lo[0] = max(0.0, min(lo[0], b[0] - max(0.0, b[1] - lo[1])))
    return tuple(sorted(lo))


def pess_pv(band: tuple, k: float) -> float:
    """The Planner's pessimistic PV of a day with this band: p50 - k (p50 - p10), floored at zero (advisor.Planner.pv_mult)."""
    return 0.0 if band[1] <= 0 else band[1] * max(0.0, 1.0 - k * (1.0 - band[0] / band[1]))


KS = (0.0, 0.5, 0.7071, 1.0, 1.0607, 1.5, 2.25, 3.375)      # band_kappa (0.5 to 1.5) x LOW widening (1.5) x band inflation (1 to 1.5)


def old_band(published: tuple, corrected: tuple) -> tuple:
    """The round-1 design contract: per quantile the lower of the two, sorted (kept as a test fixture: the defect this fix removes)."""
    return tuple(sorted(min(x, y) for x, y in zip(published, corrected)))


def worst_band(published: tuple, corrected: tuple) -> tuple:
    """The ORIGINAL defect: planning sizes on the published persistence band unchanged (injected to prove the guard on its own)."""
    return tuple(published)


def close3(a, b, tol=1e-9) -> bool:
    return a is not None and b is not None and len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


# ---------------------------------------------------------------------------------------------------------------------
def sec_pinned(S: Stack, rec) -> None:
    rec.section("[1] the 80 -> 70 world (whole engine)")
    for seed in PIN_SEED_80_70:
        w = world(seed)
        r0, r1 = run(w, False, S), run(w, True, S)
        t0, t1 = W.target(r0), W.target(r1)
        rec(f"world {seed} ({w['regime']}): gate OFF recommends 80 percent", t0 == 80.0, f"{t0}")
        rec(f"world {seed}: gate ON does not lower the overnight target (OFF {t0}, ON {t1})", t0 is not None and t1 is not None and t1 >= t0,
            f"the gate ON target is {t1} against {t0} with it OFF")
        tom = days(r1)[-1]
        p = r1["pv"][tom]
        ref = model_for(w, False, S)._persistence(w["tomorrow"], [])
        rec(f"world {seed}: the PUBLISHED forecast is still persistence, LOW, 0.3, with the model's own persistence band",
            p["source"] == "persistence" and p["label"] == "LOW" and p["confidence"] == 0.3
            and (p["p10"], p["p50"], p["p90"]) == (round(ref.p10, 2), round(ref.p50, 2), round(ref.p90, 2)), str(p))
        rec(f"world {seed}: the published tomorrow p50 is above the ungated corrected p50 (this is the world that used to lower the "
            f"target)", p["p50"] > r0["pv"][tom]["p50"], f"{p['p50']} vs {r0['pv'][tom]['p50']}")


def sec_trace(S: Stack, rec) -> None:
    rec.section("[2] the visible trace: LOW cap, reason code, plain text")
    for seed in PIN_SEED_80_70:
        w = world(seed)
        r0, r1 = run(w, False, S), run(w, True, S)
        c = r1["confidence"]
        rec(f"world {seed}: overall confidence is capped at 0.45 and labelled LOW exactly like a rejected forecast",
            c["overall"] <= 0.45 and c["label"] == "LOW", str(c))
        rec(f"world {seed}: {CODE} is in confidence.downgrade_reasons", CODE in c["downgrade_reasons"], str(c["downgrade_reasons"]))
        n_fb = len(fb_days(r0, r1))
        rec(f"world {seed}: one advice reason and one uncertainty entry per fallback day ({n_fb})",
            n_fb >= 1 and codes(r1, "reasons").count(CODE) == n_fb and codes(r1, "uncertainty").count(CODE) == n_fb,
            f"{codes(r1, 'reasons')} {codes(r1, 'uncertainty')}")
        txt = " ".join(x["text"] for x in r1["recommended"].get("reasons", []) if x.get("code") == CODE)
        rec(f"world {seed}: the text says persistence was published and that planning uses the LOWER of persistence and the corrected value",
            "persistence" in txt and "lower" in txt.lower() and "corrected" in txt, txt)
        rec(f"world {seed}: gate OFF carries no trace", CODE not in r0["confidence"]["downgrade_reasons"]
            and CODE not in codes(r0, "reasons") and CODE not in codes(r0, "uncertainty"))
        rec(f"world {seed}: the V1 advice for the same inputs still says it applies nothing (SHADOW, applies_nothing)",
            r1["applies_nothing"] is True and r1["mode"] == "SHADOW")
    for seed in KEPT_SEEDS:
        w = world(seed)
        r0, r1 = run(w, False, S), run(w, True, S)
        rec(f"kept world {seed} (a source with skill): no trace, and the whole report is identical with the gate ON and OFF",
            CODE not in r1["confidence"]["downgrade_reasons"] and CODE not in codes(r1, "reasons") and canon(r0) == canon(r1))
    for seed in REJECTED_SEEDS:
        w = world(seed)
        r0, r1 = run(w, False, S), run(w, True, S)
        rec(f"rejected world {seed}: the unchanged guard rejects (PV_FORECAST_REJECTED), the gate code is absent, report identical ON/OFF",
            "PV_FORECAST_REJECTED" in r1["confidence"]["downgrade_reasons"] and CODE not in r1["confidence"]["downgrade_reasons"]
            and canon(r0) == canon(r1))


def _relations(on, off, T) -> dict:
    """Scan raw values for one raw value per way the persistence band (a) and the ungated corrected band (b) can relate, in a world
    where the gate falls back and the guard does not reject: corrected_lower (b <= a at every quantile), persistence_lower (a <= b
    everywhere), mixed (b has the lower p10, a the lower p50: a wide corrected band around a higher median)."""
    found: dict[str, float] = {}
    r = 1.0
    while r <= 60.0:
        a, b = on.forecast_day(T, {"src": r}), off.forecast_day(T, {"src": r})
        if a.source == "persistence" and b.source == "src" and not b.plausibility.get("rejected"):
            pa, pb = band_of(a), band_of(b)
            if pa != pb:
                if all(y <= x for x, y in zip(pa, pb)):
                    found.setdefault("corrected_lower", r)
                elif all(x <= y for x, y in zip(pa, pb)):
                    found.setdefault("persistence_lower", r)
                elif pb[0] < pa[0] and pa[1] < pb[1]:
                    found.setdefault("mixed", r)
        r += 0.5
    return found


def sec_model(S: Stack, rec) -> None:
    rec.section("[3] the planning values of a PvForecast (model level)")
    Wd = G.SHADED
    on, off = Wd.model(S.M, True), Wd.model(S.M, False)
    kinds = _relations(on, off, Wd.T)
    rec("the scan finds the relations between the persistence band and the ungated corrected band that decide the mutants: the corrected "
        "band lower everywhere, and mixed (a wide corrected band around a higher median)", {"corrected_lower", "mixed"} <= set(kinds), str(kinds))
    for kind in ("corrected_lower", "mixed", "persistence_lower"):
        raw = kinds.get(kind)
        if raw is None:
            continue
        a, b = on.forecast_day(Wd.T, {"src": raw}), off.forecast_day(Wd.T, {"src": raw})
        want = lower_of(band_of(a), band_of(b))
        got = getattr(a, "planning_band", None)
        gf = getattr(a, "gate_fallback", "missing")
        rec(f"[{kind}, raw {raw}] planning band is the per-quantile lower of persistence and the ungated corrected value",
            close3(got, want), f"{got} vs {want}; published {band_of(a)}; ungated {band_of(b)}")
        rec(f"[{kind}] ... and never above either input, sorted, finite, not negative", got is not None and all(
            x <= y + 1e-12 and x <= z + 1e-12 for x, y, z in zip(got, band_of(a), band_of(b)))
            and list(got) == sorted(got) and all(math.isfinite(x) and x >= 0.0 for x in got))
        rec(f"[{kind}] the PUBLISHED band is still persistence's own: source persistence, LOW, 0.3, no raw, no ratio",
            a.source == "persistence" and a.label == "LOW" and a.confidence == 0.3 and a.raw_kwh is None and a.ratio is None
            and band_of(a) == band_of(on._persistence(Wd.T, [])))
        rec(f"[{kind}] the trace names the displaced source, the reason, the ungated band and the ungated inflation",
            gf not in (None, "missing") and getattr(gf, "source", None) == "src" and getattr(gf, "reason", None) == S.M.GATE_REASON_NOT_BEATEN
            and close3(getattr(gf, "corrected", None), band_of(b)) and getattr(gf, "corrected_inflation", None) == b.inflation
            and close3(getattr(gf, "planning", None), want), str(gf))
        rec(f"[{kind}] the planning inflation is the ungated one (the band was widened there, persistence's never is)",
            getattr(a, "planning_inflation", None) == max(a.inflation, b.inflation))
        rec(f"[{kind}] to_dict is exactly the pre-fix key set and is the published persistence forecast",
            set(a.to_dict()) == G.TO_DICT_KEYS and a.to_dict()["p50"] == round(a.p50, 2))
        rec(f"[{kind}] gate OFF: the planning band IS the published band and nothing is recorded",
            getattr(b, "gate_fallback", "missing") is None and getattr(b, "planning_band", None) == band_of(b)
            and getattr(b, "planning_inflation", None) == b.inflation)
    # a mixed world must really be mixed: p10 from the corrected band, p50 or p90 from persistence (kills "min on p50 only")
    raw = kinds.get("mixed")
    if raw is not None:
        a, b = on.forecast_day(Wd.T, {"src": raw}), off.forecast_day(Wd.T, {"src": raw})
        got = getattr(a, "planning_band", (None, None, None))
        rec("the mixed world takes p50 from persistence and a p10 below the corrected p10 by the amount the median was lowered (the ungated "
            "spread is kept; so no single quantile decides)",
            got[1] == a.p50 and b.p10 < a.p10 and a.p50 < b.p50 and abs(got[0] - max(0.0, b.p10 - (b.p50 - a.p50))) < 1e-9
            and (got[0] == 0.0 or got[1] - got[0] >= b.p50 - b.p10 - 1e-9), f"{got} {band_of(a)} {band_of(b)}")
    # kept: the corrected forecast of a source with skill is published, planning equals it, nothing is recorded
    Wk = G.SKILL
    k_on, k_off = Wk.model(S.M, True), Wk.model(S.M, False)
    a, b = k_on.forecast_day(Wk.T, {"src": G.RAW_T["skill"]}), k_off.forecast_day(Wk.T, {"src": G.RAW_T["skill"]})
    rec("kept (a source with skill): planning band == published band == the ungated forecast; no trace; to_dict identical",
        getattr(a, "gate_fallback", "missing") is None and getattr(a, "planning_band", None) == band_of(a) == band_of(b)
        and a.to_dict() == b.to_dict() and getattr(a, "planning_inflation", None) == a.inflation)
    # rejected: the guard decides first, the gate is not reached, no trace
    r_on = k_on.forecast_day(Wk.T, {"src": 100.0})
    rec("REJECTED by the unchanged guard: no gate trace, planning == published", getattr(r_on, "gate_fallback", "missing") is None
        and getattr(r_on, "planning_band", None) == band_of(r_on) and r_on.source == "persistence")
    # too few comparable days: the comparison cannot be made, persistence is published and planning is still the lower value
    Wf = G.World("skill", 12, 11)
    f_on, f_off = Wf.model(S.M, True), Wf.model(S.M, False)
    a, b = f_on.forecast_day(Wf.T, {"src": 14.0}), f_off.forecast_day(Wf.T, {"src": 14.0})
    gf = getattr(a, "gate_fallback", None)
    rec("TOO_FEW_DAYS fallback: the trace says so and planning is the lower of persistence and the ungated corrected value",
        gf is not None and gf.reason == S.M.GATE_REASON_TOO_FEW_DAYS and close3(getattr(a, "planning_band", None), lower_of(band_of(a), band_of(b))),
        str(gf))
    # INSUFFICIENT stays exactly as before (nothing to take the lower of)
    W0 = G.World("skill", 3, 11)
    z_on = W0.model(S.M, True).forecast_day(W0.T, {"src": 14.0})
    rec("fewer than 5 actual days: INSUFFICIENT, no trace, planning == published (zeros)",
        z_on.label == "INSUFFICIENT" and getattr(z_on, "gate_fallback", "missing") is None
        and getattr(z_on, "planning_band", None) == band_of(z_on))


def sec_band(S: Stack, rec) -> None:
    rec.section("[4] conservative_band, the pure function")
    f = getattr(S.M, "conservative_band", None)
    rec("conservative_band exists", callable(f))
    if not callable(f):
        return
    rec("the corrected median is the lower one: per quantile the lower of the two bands (the spread is already the corrected one)",
        f((4.0, 6.0, 8.0), (5.0, 3.0, 9.0)) == (3.0, 4.0, 8.0))
    rec("equal bands: unchanged", f((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)) == (1.0, 2.0, 3.0))
    rec("persistence is lower everywhere: its median and p90, and a p10 that keeps the corrected spread of 2 below the median "
        "(5 - 3 = 2, so 3 - 2 = 1, below persistence's own p10 of 2)", f((2.0, 3.0, 4.0), (3.0, 5.0, 8.0)) == (1.0, 3.0, 4.0))
    rec("the median was lowered below the corrected one: p10 moves down by the same amount (corrected p10 4 - (7 - 6) = 3, below "
        "the per-quantile minimum 4), p50 and p90 are the lower of the two",
        f((5.0, 6.0, 9.0), (4.0, 7.0, 10.0)) == (3.0, 6.0, 9.0))
    rec("the spread below the median is the corrected one or wider (the property the Planner's pessimistic PV needs)", all(
        (lambda r: r[1] - r[0] >= b[1] - b[0] - 1e-12 or r[0] == 0.0)(f(a, b)) for a, b in (
            ((5.0, 6.0, 9.0), (4.0, 7.0, 10.0)), ((5.0, 6.0, 7.0), (2.0, 8.0, 14.0)), ((3.0, 4.0, 5.0), (1.0, 9.0, 10.0)),
            ((6.0, 8.0, 12.0), (3.0, 7.0, 15.0)))))
    rec("p10 is clamped at zero (the corrected p10 minus the lowering would be negative): (3, 4, 5) against (1, 9, 10) gives p10 0",
        f((3.0, 4.0, 5.0), (1.0, 9.0, 10.0)) == (0.0, 4.0, 5.0))
    rec("the result is re-sorted: an unsorted input cannot give p10 > p50", f((4.0, 6.0, 8.0), (7.0, 3.0, 9.0)) == (3.0, 4.0, 8.0))
    rec("never above either input at the same rank, sorted, non-negative; idempotent", all(
        all(x <= y + 1e-12 and x <= z + 1e-12 for x, y, z in zip(f(a, b), a, b)) and list(f(a, b)) == sorted(f(a, b)) and min(f(a, b)) >= 0.0
        and f(f(a, b), b) == f(a, b)
        for a, b in (((1.0, 2.0, 3.0), (2.0, 2.5, 2.7)), ((0.0, 1.0, 5.0), (0.5, 0.6, 0.7)), ((3.0, 4.0, 5.0), (1.0, 9.0, 10.0)),
                     ((5.0, 6.0, 9.0), (4.0, 7.0, 10.0)))))
    rec("a band with zero p10 stays non-negative", f((0.0, 2.0, 4.0), (1.0, 3.0, 5.0))[0] == 0.0)
    # the proof, sampled: p50' <= p50c and spread' >= spread_c give a pessimistic PV at or below the ungated one for every k >= 0
    import random
    rnd = random.Random(20261120)
    worst, n_bad = 0.0, 0
    for _ in range(4000):
        a = tuple(sorted(rnd.uniform(0.0, 30.0) for _i in range(3)))
        b = tuple(sorted(rnd.uniform(0.0, 30.0) for _i in range(3)))
        p = f(a, b)
        for k in KS:
            d = pess_pv(p, k) - pess_pv(b, k)
            if d > 1e-9:
                n_bad += 1
                worst = max(worst, d)
    rec("4000 random sorted band pairs x 8 values of k (0 to 3.375): the pessimistic PV of the planning band never exceeds the ungated one "
        f"(violations {n_bad}, worst {worst:.3f} kWh)", n_bad == 0)


class _Spy:
    """Replaces the engine module's Planner for one run and records what it was handed."""

    def __init__(self, E):
        self.E, self.calls, self.orig = E, [], E.Planner
        spy = self

        class SpyPlanner(Planner):
            def __init__(self, cfg, load_profile, load_rel, pv_by_day, inputs, nowcast, conf_label, pv_inflation=1.0, baseline_profile=None):
                spy.calls.append({"pv_by_day": pv_by_day, "inputs": inputs, "label": conf_label, "pv_inflation": pv_inflation,
                                  "load_profile": load_profile, "load_rel": load_rel, "nowcast": nowcast, "baseline": baseline_profile})
                super().__init__(cfg, load_profile, load_rel, pv_by_day, inputs, nowcast, conf_label, pv_inflation, baseline_profile)
        self.cls = SpyPlanner

    def __enter__(self):
        self.E.Planner = self.cls
        return self

    def __exit__(self, *exc):
        self.E.Planner = self.orig


def _reanchor(p50: float, done_share: float, so_far) -> float:
    """The documented re-anchoring of today's remaining PV (engine._pv_days), recomputed here from the formula."""
    rem = p50 * (1.0 - done_share)
    if so_far is not None and p50 * done_share >= 2.0:
        live = max(0.4, min(1.6, so_far / (p50 * done_share)))
        w = min(0.7, done_share / 0.6)
        rem *= w * live + (1.0 - w)
    return max(0.0, rem)


def sec_plumbing(S: Stack, rec) -> None:
    rec.section("[5] what the engine hands the Planner")
    from intelligence.pv import pv_hour_shape
    for seed in (643, 120) + DAYTIME_SEEDS + INFLATION_SEEDS[:2]:
        w = world(seed)
        with _Spy(S.E) as spy:
            r1 = W.run_world(w, True, S.engine_stack)       # not the cache: the spy must see this run
        r0 = run(w, False, S)
        on = model_for(w, True, S)
        call = spy.calls[0] if spy.calls else None          # the PLANNING Planner (a fallback day set builds a second, ungated one after it)
        if call is None:
            rec(f"world {seed}: the Planner was built", False)
            continue
        ok_band, ok_infl, rem_ok, detail = True, True, True, ""
        infl_want = 1.0
        now = w["now"]
        shape = pv_hour_shape(w["hist"].truncated(now), W.WCFG, w["today"])
        for d, raw in raws(w):
            fc = on.forecast_day(d, raw)
            pvd = call["pv_by_day"].get(d)
            want = getattr(fc, "planning_band", None)
            if pvd is None or want is None or not close3((pvd.p10, pvd.p50, pvd.p90), want):
                ok_band = False
                detail += f" {d}: PvDay {None if pvd is None else (pvd.p10, pvd.p50, pvd.p90)} vs planning {want};"
            infl_want = max(infl_want, getattr(fc, "planning_inflation", float("inf")))
            if d == w["today"]:
                if pvd is None or want is None:
                    rem_ok = False
                    continue
                done = sum(shape[h] for h in range(now.astimezone(W.WTZ).hour))
                gfb = getattr(fc, "gate_fallback", None)
                exp = _reanchor(want[1], done, call["inputs"].pv_actual_so_far_kwh)
                if gfb is not None:                 # never above the re-anchoring on the ungated median (the 2 kWh threshold is not monotone)
                    exp = min(exp, _reanchor(gfb.corrected[1], done, call["inputs"].pv_actual_so_far_kwh))
                if pvd.remaining_p50 is None or abs(pvd.remaining_p50 - exp) > 1e-9:
                    rem_ok = False
                    detail += f" today remaining {pvd.remaining_p50} vs {exp};"
        rec(f"world {seed}: every PvDay holds the planning band (p10 / p50 / p90) of its forecast", ok_band, detail)
        rec(f"world {seed}: today's remaining PV is the lower of the re-anchoring on the PLANNING p50 and on the ungated p50", rem_ok, detail)
        rec(f"world {seed}: the band inflation handed to the Planner is the larger of the published and the ungated one ({infl_want})",
            abs(call["pv_inflation"] - infl_want) < 1e-9, f"{call['pv_inflation']} vs {infl_want}")
        rec(f"world {seed}: the confidence label handed to the Planner is the report's own ({r1['confidence']['label']})",
            call["label"] == r1["confidence"]["label"])
        rec(f"world {seed}: the target is not lowered ({W.target(r0)} -> {W.target(r1)})", W.target(r1) >= W.target(r0),
            f"{W.target(r0)} -> {W.target(r1)}")
        # the published explanation of today's re-anchoring (and the note / status built on it) describes the PUBLISHED forecast
        pub_today = on.forecast_day(w["today"], raws(w)[0][1])
        done = sum(shape[h] for h in range(now.astimezone(W.WTZ).hour))
        so_far = call["inputs"].pv_actual_so_far_kwh
        exp_live = None if (so_far is None or pub_today.p50 * done < 2.0) else round(max(0.4, min(1.6, so_far / (pub_today.p50 * done))), 3)
        ra = r1["pv"].get("today_reanchor")
        rec(f"world {seed}: the published today_reanchor is computed from the PUBLISHED p50, as before the fix",
            (ra is None and exp_live is None) or (ra is not None and ra["live_ratio"] == exp_live), f"{ra} vs {exp_live}")


def sec_contract(S: Stack, rec) -> None:
    rec.section("[6] the switch and the contract")
    rec("PV_SKILL_GATE_DEFAULT is still False", S.M.PV_SKILL_GATE_DEFAULT is False)
    params = list(inspect.signature(S.M.PvModel.__init__).parameters)
    rec("the PvModel constructor still takes exactly (history, cfg, forecasts, skill_gate, recent_envelope)",
        params == ["self", "history", "cfg", "forecasts", "skill_gate", "recent_envelope"], str(params))
    rec("no SiteConfig field mentions the gate (a new field would change every config_hash)",
        not any("gate" in f.name or "skill" in f.name for f in fields(SiteConfig)))
    w = world(643)
    eng = S.E.IntelligenceEngine(w["hist"].truncated(w["now"]), W.WCFG, {})
    rec("an engine built the ordinary way has the gate OFF", eng.pv.skill_gate is False)
    a = model_for(w, True, S).forecast_day(w["tomorrow"], {"src": w["fc"]["src"][w["tomorrow"]]})
    summ = {k: v for k, v in a.to_dict().items() if k in G.PV_TOMORROW_SUMMARY_KEYS}
    rec("the fallback forecast's to_dict keys are exactly PV_TOMORROW_SUMMARY_KEYS and the summary is within 2048 bytes",
        set(a.to_dict()) == set(G.PV_TOMORROW_SUMMARY_KEYS) and len(json.dumps(summ, separators=(",", ":")).encode("utf-8")) <= G.MAX_SUMMARY_BYTES)
    rec("the planning values are not in to_dict()", not any("plan" in k or "gate" in k for k in a.to_dict()))


# ---------------------------------------------------------------------------------------------------------------------
def cycle_world(seed: int, level: float = 0.2, spell: int = 8, bright: float = 0.95, base: float = 0.3, fc_range=(1.0, 6.0)):
    """The shared cycle fixture with its history and forecast series replaced by a bright spell and a source with no skill."""
    import random
    rnd = random.Random(seed)
    now = cf.NOW
    start = (now - timedelta(days=60)).date()
    cfg = SiteConfig(pv_array_kwp=cf.FACTS.pv_array_kwp)
    n = 61
    scale = {start + timedelta(days=k): (bright if n - k <= spell else base) * (1 + 0.07 * rnd.gauss(0, 1)) for k in range(n + 2)}
    hist = make_history(start, n, cfg, seed=seed, level=level, clearness=1.0, pv_scale_by_day=scale).truncated(now)
    fc = {"synthetic_forecast": {start + timedelta(days=k): rnd.uniform(*fc_range) for k in range(n)}}
    return replace(cf.cycle_inputs(synthetic_recorded=True), history=hist, pv_forecast_history=fc)


def run_cycle_gate(S: Stack, ci, gate: bool):
    saved = S.M.PV_SKILL_GATE_DEFAULT
    try:
        S.M.PV_SKILL_GATE_DEFAULT = gate
        return S.C.run_cycle(ci)
    finally:
        S.M.PV_SKILL_GATE_DEFAULT = saved


def _view_digest(v) -> str:
    return hashlib.sha256(json.dumps([v.status.name if hasattr(v.status, "name") else str(v.status), v.value, v.p10, v.p90,
                                      str(v.confidence), sorted(v.reason_codes), json.dumps(dict(v.summary or {}), sort_keys=True, default=str)],
                                     default=str).encode()).hexdigest()


def sec_cycle(S: Stack, rec) -> None:
    rec.section("[7] the shadow cycle")
    for seed, level, rng in ((1, 0.5, (1.0, 6.0)), (2, 0.5, (1.0, 6.0)), (1, 0.2, (1.0, 6.0)), (2, 0.2, (1.0, 6.0)), (5, 0.5, (5.0, 25.0))):
        ci = cycle_world(seed, level=level, fc_range=rng)
        tag = f"cycle world {seed} (load level {level}, forecast history {rng[0]:g}-{rng[1]:g})"
        off, on = run_cycle_gate(S, ci, False), run_cycle_gate(S, ci, True)
        v0, v1 = off.engine_comparison["v1_target_soc_pct"], on.engine_comparison["v1_target_soc_pct"]
        rec(f"{tag}: the V1 target inside the cycle is not lowered by the gate ({v0} -> {v1})", v1 >= v0, f"{v0} -> {v1}")
        c0, c1 = off.item("charge_target"), on.item("charge_target")
        rec(f"{tag}: the V1.1 charge target is not lowered ({c0.value} -> {c1.value})", c0.value is not None and c1.value >= c0.value,
            f"{c0.value} -> {c1.value}")
        h0, h1 = off.plan["headroom_ceiling_pct"], on.plan["headroom_ceiling_pct"]
        rec(f"{tag}: the plan's headroom ceiling is not lowered ({h0} -> {h1}); the gate must not claim PV the corrected path did not",
            h1 >= h0, f"{h0} -> {h1}")
        m0, m1 = off.item("predicted_morning_soc"), on.item("predicted_morning_soc")
        if c0.value == c1.value:       # the morning SOC starts from the charge target: it is a PV statement only at an equal target
            rec(f"{tag}: at the same charge target the predicted morning SOC (p10 / p50 / p90) is not HIGHER with the gate (it assumes "
                f"no more PV than the ungated forecast): {(m0.p10, m0.value, m0.p90)} -> {(m1.p10, m1.value, m1.p90)}",
                m1.p10 <= m0.p10 + 1e-9 and m1.value <= m0.value + 1e-9 and m1.p90 <= m0.p90 + 1e-9)
        else:
            rec(f"{tag}: the charge target differs ({c0.value} -> {c1.value}), so the morning SOC is not compared; the target is higher",
                c1.value > c0.value)
        pv0, pv1 = off.item("pv_tomorrow"), on.item("pv_tomorrow")
        rec(f"{tag}: pv_tomorrow is published as before: OFF the corrected source, ON persistence at LOW, same codes and validity",
            pv0.summary.get("source") == "synthetic_forecast" and pv1.summary.get("source") == "persistence" and pv1.confidence == "LOW"
            and pv0.reason_codes == pv1.reason_codes and pv0.valid_until == pv1.valid_until)
        rec(f"{tag}: the charge target takes no PV credit with the gate ON (LOW)",
            c1.summary.get("pv_credit_used_kwh") == 0.0, str(c1.summary.get("pv_credit_used_kwh")))
        rec(f"{tag}: the envelope still applies nothing (SHADOW)", on.applies_nothing is True and on.mode == "SHADOW")
    # the explicit rule: a gate fallback is LOW for the PV credit even if its label were MEDIUM
    ci = cycle_world(1, level=0.2)
    saved = S.M.PvModel.forecast_day

    def forced_medium(self, day, raw):
        pf = saved(self, day, raw)
        if getattr(pf, "gate_fallback", None) is not None:
            pf.label, pf.confidence = "MEDIUM", 0.6
        return pf
    try:
        S.M.PvModel.forecast_day = forced_medium
        forced = run_cycle_gate(S, ci, True)
    finally:
        S.M.PvModel.forecast_day = saved
    rec("a gate fallback whose label had been MEDIUM still earns NO PV credit in the charge target (the credit label is LOW)",
        forced.item("charge_target").summary.get("pv_credit_used_kwh") == 0.0, str(forced.item("charge_target").summary.get("pv_credit_used_kwh")))
    # sanity: the same stub WITHOUT a fallback (gate OFF) does earn a credit on this world (so the check above is not vacuous)
    rec("... whereas the ungated MEDIUM forecast of the same world does earn a credit",
        (run_cycle_gate(S, ci, False).item("charge_target").summary.get("pv_credit_used_kwh") or 0.0) > 0.0)


# ---------------------------------------------------------------------------------------------------------------------
# ROUND 2: the planning band keeps the spread, the by-construction guard (engine and shadow cycle)
@contextlib.contextmanager
def band_rule(S: Stack, fn):
    """Replace the pv module's conservative_band for a block (fn None: leave the real one). The injected rules model a regression of the
    planning band; the guard must keep the target on its own."""
    saved = S.M.conservative_band
    if fn is not None:
        S.M.conservative_band = fn
    try:
        yield
    finally:
        S.M.conservative_band = saved


class _AdviseTap:
    """Replaces the engine module's advise() for one run and records every answer (the dicts, in call order)."""

    def __init__(self, E):
        self.E, self.answers, self.orig = E, [], E.advise

    def __enter__(self):
        tap = self

        def advise(*a, **kw):
            out = tap.orig(*a, **kw)
            tap.answers.append(out)
            return out
        self.E.advise = advise
        return self

    def __exit__(self, *exc):
        self.E.advise = self.orig

    def targets(self) -> list:
        return [(x.get("overnight_target") or {}).get("recommended_target_soc_pct") for x in self.answers]


def engine_run(w: dict, gate: bool, S: Stack, rule=None):
    """(report, the Planner constructions, the advise() answers) of one engine run, optionally under an injected planning-band rule."""
    with band_rule(S, rule), _Spy(S.E) as sp, _AdviseTap(S.E) as tap:
        r = W.run_world(w, gate, S.engine_stack)
    return r, sp.calls, tap


def same_planner_inputs(a: dict, b: dict) -> bool:
    """Two recorded Planner constructions were handed exactly the same PV days, band inflation, label, load band and nowcast."""
    return all(a[k] == b[k] for k in ("pv_by_day", "label", "pv_inflation", "load_rel", "nowcast", "load_profile", "baseline", "inputs"))


GUARD = "PV_SKILL_GATE_UNGATED_KEPT"
GUARD_WORLDS = (8077, 643, 120, 16, 28, 8, 6, 9, 7, 45, 94, 1, 25)   # 8077 lost 5 points under the round-1 band; 643 to 94 lost 10 to 55 under the original
# defect; worlds 1 and 25 TIE (equal targets) while the ungated advice would export more, so a flipped tie rule is visible
CALM_WORLDS = KEPT_SEEDS[:2] + REJECTED_SEEDS[:1]        # no fallback day: the guard must not even compute a second advice
GUARD_RULES = ((None, "the real planning band", GUARD_WORLDS), (old_band, "the round-1 per-quantile band (injected)", (8077,)),
               (worst_band, "persistence unchanged, the original defect (injected)", GUARD_WORLDS))


def sec_spread(S: Stack, rec) -> None:
    rec.section("[11] the planning band keeps the ungated spread: the Planner's pessimistic PV never rises (k above 1)")
    import datetime as dt
    cfg0 = SiteConfig()
    day0 = dt.date(2030, 1, 15)
    now0 = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)
    pub, cor = (5.0, 6.0, 7.0), (2.0, 8.0, 14.0)          # persistence's median below the corrected one, the corrected p10 below persistence's
    plan = S.M.conservative_band(pub, cor)
    for label, cfg, conf, infl in (("band_kappa 0.707, LOW, no inflation (k 1.06)", cfg0, "LOW", 1.0),
                                   ("band_kappa 1.5, LOW, inflation 1.5 (k 3.375)", replace(cfg0, band_kappa=1.5), "LOW", 1.5),
                                   ("band_kappa 0.707, MEDIUM, no inflation (k 0.71)", cfg0, "MEDIUM", 1.0)):
        out = {}
        for name, band in (("planning", plan), ("ungated", cor), ("round-1 min", old_band(pub, cor))):
            pl = Planner(cfg, [1.0] * 24, (-0.2, 0.2), {}, LiveInputs(now=now0, soc_pct=50.0), [0.0] * 8, conf, infl, None)
            d = PvDay(day0, band[0], band[1], band[2], [1.0 / 24] * 24)
            out[name] = d.p50 * pl.pv_mult(d, "pess")
        rec(f"hand-built Planner case, {label}: the pessimistic PV of the planning band ({out['planning']:.2f} kWh) is not above the ungated one "
            f"({out['ungated']:.2f})", out["planning"] <= out["ungated"] + 1e-9, str(out))
        if "k 1.06" in label:
            rec("... and this case really is the one the round-1 per-quantile band got wrong (its pessimistic PV "
                f"{out['round-1 min']:.2f} kWh is ABOVE the ungated one)", out["round-1 min"] > out["ungated"] + 1e-6, str(out))


def sec_guard(S: Stack, rec) -> None:
    rec.section("[12] the guard of the engine: two advices, the higher recommended target is published, a tie keeps the planning run")
    n_fired = n_tie = 0
    off: dict[int, tuple] = {}

    def off_run(seed: int) -> tuple:
        if seed not in off:
            off[seed] = engine_run(world(seed), False, S)
        return off[seed]
    for rule, label, seeds in GUARD_RULES:
        for seed in seeds:
            w = world(seed)
            r0, calls0, tap0 = off_run(seed)
            r1, calls1, tap1 = engine_run(w, True, S, rule)
            t0, t1 = W.target(r0), W.target(r1)
            tag = f"{label}, world {seed}"
            rec(f"{tag}: the published target is not below the gate-OFF target ({t0} -> {t1})", t0 is not None and t1 is not None and t1 >= t0,
                f"{t0} -> {t1}")
            fb = fb_days(r0, r1)
            if not fb:
                continue
            two = len(calls1) == 2 and len(tap1.answers) == 2
            rec(f"{tag}: a fallback day: two Planners and two advices were computed (planning first, then the ungated one)", two,
                f"{len(calls1)} Planners, {len(tap1.answers)} advices")
            if not two:
                continue
            tp, tu = tap1.targets()
            fired = r1["recommended"] is tap1.answers[1]
            rec(f"{tag}: the published advice is the higher one (planning {tp}, ungated {tu}); a tie keeps the planning run",
                (fired and tu > tp) or (not fired and r1["recommended"] is tap1.answers[0] and tu <= tp), f"{tp} {tu} fired={fired}")
            rec(f"{tag}: the ungated advice IS what the gate-OFF engine answered (overnight target and safe export identical)",
                tap1.answers[1]["overnight_target"] == r0["recommended"]["overnight_target"]
                and tap1.answers[1]["safe_export"] == r0["recommended"]["safe_export"] and tu == t0)
            rec(f"{tag}: the ungated Planner was handed exactly what the gate-OFF engine hands its Planner (PV days incl. today's remaining PV, "
                f"band inflation, confidence label {r0['confidence']['label']}, load band, nowcast)", same_planner_inputs(calls1[1], calls0[0]))
            rec(f"{tag}: the planning Planner is the gate-aware one (label {r1['confidence']['label']})",
                calls1[0]["label"] == r1["confidence"]["label"])
            c = r1["confidence"]
            rec(f"{tag}: the LOW cap, the downgrade reason and one reason and one uncertainty entry per fallback day still apply whichever advice is published",
                c["overall"] <= 0.45 and c["label"] in ("LOW", "INSUFFICIENT") and CODE in c["downgrade_reasons"]
                and codes(r1, "reasons").count(CODE) == len(fb) and codes(r1, "uncertainty").count(CODE) == len(fb))
            rec(f"{tag}: the plain reason {GUARD} is present exactly when the ungated advice was published",
                codes(r1, "reasons").count(GUARD) == (1 if fired else 0) and GUARD not in codes(r1, "uncertainty"), str(codes(r1, "reasons")))
            if fired:
                txt = " ".join(x["text"] for x in r1["recommended"]["reasons"] if x.get("code") == GUARD)
                rec(f"{tag}: the reason names both targets and says the ungated corrected forecast gave the higher one",
                    f"{tp:.0f}" in txt and f"{tu:.0f}" in txt and "ungated" in txt.lower() and "higher" in txt.lower(), txt)
            rec(f"{tag}: SHADOW and applies nothing", r1["applies_nothing"] is True and r1["mode"] == "SHADOW")
            n_fired += 1 if fired else 0
            n_tie += 1 if (not fired and tu == tp) else 0
    rec(f"the injected rules make the guard fire ({n_fired} times: it is exercised, not vacuous)", n_fired >= 8, str(n_fired))
    rec(f"the tie rule is exercised ({n_tie} ties: equal targets, the planning run kept)", n_tie >= 1, str(n_tie))
    for seed in CALM_WORLDS:
        r0, calls0, tap0 = off_run(seed)
        r1, calls1, tap1 = engine_run(world(seed), True, S)
        rec(f"world {seed} (the gate keeps or the guard rejects): ONE Planner, ONE advice, no guard reason, the whole report identical",
            len(calls1) == 1 and len(tap1.answers) == 1 and GUARD not in codes(r1, "reasons") and canon(r0) == canon(r1))
        rec(f"world {seed}: with the gate OFF as well: ONE Planner, ONE advice", len(calls0) == 1 and len(tap0.answers) == 1)


class _CtTap:
    """Replaces the shadow-cycle module's advise_charge_target for one run: records the PV credit it was offered and the target it
    answered; with `lower`, the PLANNING call (no credit, label LOW) answers that target instead (a regression of the planning rule)."""

    def __init__(self, C, lower=None):
        self.C, self.lower, self.calls, self.orig = C, lower, [], C.advise_charge_target

    def __enter__(self):
        tap = self

        def wrapper(cfg, inp):
            a = tap.orig(cfg, inp)
            if tap.lower is not None and inp.pv_credit_kwh is None and inp.pv_credit_label == "LOW" and a.recommendation is not None:
                a = replace(a, recommendation={**a.recommendation, "target_soc_pct": tap.lower})
            tap.calls.append((inp.pv_credit_kwh, inp.pv_credit_label, None if a.recommendation is None else a.recommendation.get("target_soc_pct")))
            return a
        self.C.advise_charge_target = wrapper
        return self

    def __exit__(self, *exc):
        self.C.advise_charge_target = self.orig


def sec_cycle_guard(S: Stack, rec) -> None:
    rec.section("[13] the same guard in the shadow cycle (the V1.1 charge target)")
    ci = cycle_world(1, level=0.2)
    with _CtTap(S.C) as t_off:
        off = run_cycle_gate(S, ci, False)
    rec("gate OFF: one charge-target advice, offered the ungated PV credit (a credit above zero at MEDIUM or HIGH)",
        len(t_off.calls) == 1 and (t_off.calls[0][0] or 0.0) > 0.0 and t_off.calls[0][1] in ("MEDIUM", "HIGH"), str(t_off.calls))
    with _CtTap(S.C) as t_on:
        on = run_cycle_gate(S, ci, True)
    rec("gate ON, fallback: TWO charge-target advices: the planning one (no credit, LOW), then the ungated one (the credit the gate-OFF cycle used)",
        len(t_on.calls) == 2 and t_on.calls[0][:2] == (None, "LOW") and t_on.calls[1][:2] == t_off.calls[0][:2], str(t_on.calls))
    c0, c1 = off.item("charge_target"), on.item("charge_target")
    rec(f"the published charge target is the higher of the two ({c1.value}), not below the gate-OFF one ({c0.value}); no guard reason when the planning one is kept",
        len(t_on.calls) == 2 and c1.value == max(t_on.calls[0][2], t_on.calls[1][2]) and c1.value >= c0.value and GUARD not in c1.reason_codes,
        f"{c1.value} {c0.value} {t_on.calls} {c1.reason_codes}")
    # a regression of the planning rule, injected: the planning call answers a target far below what the gate-OFF cycle gives
    with _CtTap(S.C, lower=10.0) as t_bad:
        bad = run_cycle_gate(S, ci, True)
    cb = bad.item("charge_target")
    rec(f"planning target lowered to 10 by injection: the guard publishes the ungated advice, so the charge target equals the gate-OFF one ({cb.value} vs {c0.value})",
        len(t_bad.calls) == 2 and cb.value == c0.value and cb.value > 10.0, f"{cb.value} {c0.value} {t_bad.calls}")
    rec(f"... it carries the plain reason {GUARD}, the credit of the ungated advice and applies nothing",
        GUARD in cb.reason_codes and cb.summary.get("pv_credit_used_kwh") == c0.summary.get("pv_credit_used_kwh") and bad.applies_nothing is True
        and bad.mode == "SHADOW", f"{cb.reason_codes} {cb.summary.get('pv_credit_used_kwh')} {c0.summary.get('pv_credit_used_kwh')}")
    ck = W2.build_cycle_world(5)
    with _CtTap(S.C) as t_k:
        kept = run_cycle_gate(S, ck, True)
    rec("a world in which the gate does not fall back (the corrected forecast is published): ONE charge-target advice",
        kept.item("pv_tomorrow").summary.get("source") == "synthetic_forecast" and len(t_k.calls) == 1, str(t_k.calls))


def sec_reanchor(S: Stack, rec) -> None:
    rec.section("[14] today's remaining PV in the planning run is never above the ungated one; the pure guard rule")
    for seed in REANCHOR_SEEDS:
        w = world(seed)
        now = w["now"]
        known = w["hist"].truncated(now)
        shape = REAL_PV.pv_hour_shape(known, W.WCFG, w["today"])
        done = sum(shape[h] for h in range(now.astimezone(W.WTZ).hour))
        # (name, ungated median, planning median, published median) in kWh x done-share units: the first scenario sits on the 2 kWh
        # re-anchoring threshold (the ungated median just above it, the planning median just below it), the second well above it
        for name, c50, plan50, pub50 in (("threshold", 2.02 / done, 1.98 / done, 2.6 / done), ("above", 6.0 / done, 3.6 / done, 7.5 / done)):
            corrected = (0.5 * c50, c50, 1.6 * c50)
            published = (0.7 * pub50, pub50, 1.5 * pub50)
            band = (0.4 * c50, plan50, 1.4 * c50)
            pf = S.M.PvForecast(w["today"], "persistence", None, None, *published, 20, None, None, 0.3, "LOW", [], 1.0, {})
            gkw = dict(source="src", reason=S.M.GATE_REASON_NOT_BEATEN, n_days=14, mae_corrected=3.0, mae_persistence=2.0, note="n",
                       corrected=corrected, corrected_inflation=1.0, planning=band)
            if "corrected_label" in {f.name for f in fields(S.M.GateFallback)}:
                gkw.update(corrected_confidence=0.7, corrected_label="MEDIUM")
            pf.gate_fallback = S.M.GateFallback(**gkw)
            tm = S.M.PvForecast(w["tomorrow"], "persistence", None, None, 1.0, 5.0, 9.0, 20, None, None, 0.3, "LOW", [], 1.0, {})

            class Stub:
                def forecast_day(self, d, raw):
                    return pf if d == w["today"] else tm
            eng = S.E.IntelligenceEngine(known, W.WCFG, {})
            eng.pv = Stub()
            inp = replace(inputs_from_history(known, W.WCFG, now, w["fc"], w["soc"]), pv_actual_so_far_kwh=0.0, pv_raw_today={"src": 1.0},
                          pv_raw_tomorrow={"src": 1.0})
            plan = {"inflation": [], "fallbacks": []}
            days_, _info = eng._pv_days(inp, w["today"], now + timedelta(days=2), [], plan)
            ung = (plan.get("ungated") or {}).get("days") or {}
            plain = _reanchor(plan50, done, 0.0)
            anch = _reanchor(c50, done, 0.0)
            tag = f"world {seed} ({name} case)"
            if name == "threshold":
                rec(f"{tag}: premise: re-anchored on the ungated median the remaining PV is LOWER than the plain value of a median just below the "
                    f"threshold ({anch:.3f} < {plain:.3f}), so re-anchoring on the planning median alone would let the planning run assume MORE PV",
                    anch < plain - 1e-9)
            else:
                rec(f"{tag}: premise: the planning median is lower, so re-anchored on it the remaining PV is LOWER than on the ungated median "
                    f"({plain:.3f} < {anch:.3f})", plain < anch - 1e-9)
            rec(f"{tag}: the engine also built the ungated PV days (what the gate-OFF engine would hand its Planner)", w["today"] in ung, str(sorted(ung)))
            if w["today"] in ung:
                got = days_[w["today"]].remaining_p50
                rec(f"{tag}: today's remaining PV in the planning run ({got:.3f}) is the LOWER of the re-anchorings on the planning and on the "
                    f"ungated median ({min(plain, anch):.3f}) and not above the ungated run's ({ung[w['today']].remaining_p50:.3f}), which is the "
                    f"re-anchoring on the ungated median",
                    abs(got - min(plain, anch)) < 1e-9 and got <= ung[w["today"]].remaining_p50 + 1e-9
                    and abs(ung[w["today"]].remaining_p50 - anch) < 1e-9, f"{got} {plain} {anch}")
    f = getattr(S.M, "prefers_ungated", None)
    rec("prefers_ungated exists", callable(f))
    if callable(f):
        rec("a strictly higher ungated target is preferred", f(70.0, 75.0) is True and f(0.0, 5.0) is True)
        rec("a tie keeps the planning run", f(70.0, 70.0) is False)
        rec("a lower ungated target is not preferred", f(75.0, 70.0) is False)
        rec("anything that is not a finite number keeps the planning run (None, NaN, inf, a bool, a string)",
            all(f(a, b) is False for a, b in ((None, 80.0), (70.0, None), (float("nan"), 80.0), (70.0, float("nan")), (70.0, float("inf")),
                                                (True, 80.0), (70.0, True), ("70", 80.0))))


# ---------------------------------------------------------------------------------------------------------------------
def check_world(w: dict, S: Stack) -> dict:
    """The eight invariants of one world. Returns {"seed", "viol": [...], "fb", "t", ..., "dig": (off, on)}."""
    r0 = run(w, False, S)
    r1, _calls1, tap1 = engine_run(w, True, S)
    v: list[str] = []
    t0, t1 = W.target(r0), W.target(r1)
    o0, o1 = r0["recommended"], r1["recommended"]
    if not (t0 is not None and t1 is not None and t1 >= t0):
        v.append("I1")
    mx = W.WCFG.max_soc_pct
    if not (t1 is not None and o1.get("desired_min_pct") is not None and o1["desired_min_pct"] <= t1 <= mx
            and o1.get("floor_pct") == o0.get("floor_pct") and o1.get("desired_min_pct") == o0.get("desired_min_pct")
            and o1.get("reserve") == o0.get("reserve") and r1.get("applies_nothing") is True and r1.get("mode") == "SHADOW"):
        v.append("I2")
    p0 = (o0.get("overnight_target") or {}).get("pessimistic_case_target_soc_pct")
    p1 = (o1.get("overnight_target") or {}).get("pessimistic_case_target_soc_pct")
    short = 0.0 if (p0 is None or p1 is None) else max(0.0, p0 - p1)
    if not (p0 is not None and p1 is not None and p1 >= p0):
        v.append("I3")
    fb = fb_days(r0, r1)
    if not fb and canon(r0) != canon(r1):
        v.append("I5")
    has = CODE in r1["confidence"]["downgrade_reasons"]
    if fb:
        ok6 = (r1["confidence"]["overall"] <= 0.45 and r1["confidence"]["label"] in ("LOW", "INSUFFICIENT") and has
               and codes(r1, "reasons").count(CODE) == len(fb) and codes(r1, "uncertainty").count(CODE) == len(fb))
    else:
        ok6 = not has and CODE not in codes(r1, "reasons") and CODE not in codes(r1, "uncertainty")
    if not ok6 or CODE in r0["confidence"]["downgrade_reasons"]:
        v.append("I6")
    on, off = model_for(w, True, S), model_for(w, False, S)
    for d, raw in raws(w):
        a, b = on.forecast_day(d, raw), off.forecast_day(d, raw)
        pb, pinf = getattr(a, "planning_band", None), getattr(a, "planning_inflation", None)
        ok = pb is not None and pinf is not None and all(math.isfinite(x) and x >= 0.0 for x in pb) and list(pb) == sorted(pb)
        if ok and getattr(a, "gate_fallback", None) is None:
            ok = pb == band_of(a) and pinf == a.inflation and a.to_dict() == b.to_dict()
        elif ok:
            cb = band_of(b)
            ok = (all(x <= y + 1e-12 and x <= z + 1e-12 for x, y, z in zip(pb, band_of(a), cb))
                  and close3(pb, lower_of(band_of(a), cb)) and pinf >= a.inflation and pinf >= b.inflation
                  and (pb[0] == 0.0 or pb[1] - pb[0] >= cb[1] - cb[0] - 1e-9)                     # the ungated spread below the median is kept
                  and all(pess_pv(pb, k) <= pess_pv(cb, k) + 1e-9 for k in KS))                   # the Planner's pessimistic PV never rises
        if not ok or getattr(b, "planning_band", None) != band_of(b) or getattr(b, "gate_fallback", None) is not None:
            v.append("I7")
            break
    # I8: the guard. A fallback day: two advices, the ungated one IS the gate-OFF answer, the higher target is published (a tie keeps the
    # planning run) and the reason code appears exactly when the ungated advice was published; no fallback day: one advice, no code
    fired = False
    if fb:
        if len(tap1.answers) != 2:
            v.append("I8")
        else:
            tp, tu = tap1.targets()
            fired = r1["recommended"] is tap1.answers[1]
            ok8 = (tu == t0 and tap1.answers[1]["overnight_target"] == o0["overnight_target"] and tap1.answers[1]["safe_export"] == o0["safe_export"]
                   and ((fired and tu > tp and codes(r1, "reasons").count(GUARD) == 1)
                        or (not fired and r1["recommended"] is tap1.answers[0] and tu <= tp and GUARD not in codes(r1, "reasons"))))
            if not ok8:
                v.append("I8")
    elif len(tap1.answers) != 1 or GUARD in codes(r1, "reasons"):
        v.append("I8")
    e0 = (o0.get("safe_export") or {}).get("kwh")
    e1 = (o1.get("safe_export") or {}).get("kwh")
    return {"seed": w["seed"], "viol": v, "fb": len(fb), "t": (t0, t1), "i3_short": short, "guard": fired,
            "export_up": bool(e0 is not None and e1 is not None and e1 > e0 + 1e-9), "dig": (W.report_digest(r0), W.report_digest(r1))}


def sec_worlds(S: Stack, rec) -> None:
    rec.section("[8] the mini battery: the invariants and the unchanged published forecast on named worlds")
    for seed in MINI:
        res = check_world(world(seed), S)
        rec(f"world {seed} ({world(seed)['regime']}, {'plausible' if world(seed)['plausible'] else 'implausible'} raw): invariants I1-I7 hold "
            f"(targets {res['t'][0]} -> {res['t'][1]}, {res['fb']} fallback day(s))", not res["viol"], str(res["viol"]))
        if seed in PINNED:
            want = PINNED[seed]
            rec(f"world {seed}: what the engine publishes about PV (report['pv'] and the pv_kwh:day records) is byte-identical to the pre-fix tree, "
                f"gate OFF and ON", res["dig"] == want, f"{res['dig']} vs {want}")


def sec_property(S: Stack, rec, seeds=SEEDS, label: str = "[9] the property test", build=None, pin=None, unseen: bool = False) -> dict:
    """The invariants I1-I8 over a seed range. `build(seed)` makes a world (default the round-1 generator); `pin` is the pre-fix tree's digest
    pair for the range (I4). `unseen`: the range was registered before any run of the code under test (labels only)."""
    build = build or W.build_world
    pin = pin if pin is not None else (PINNED_RANGE if seeds is SEEDS else (PINNED_RANGE2 if seeds is SEEDS2 else None))
    rec.section(f"{label}: {len(seeds)} {'UNSEEN' if unseen else 'regression'} worlds, seeds {seeds[0]}-{seeds[-1]}")
    viol: dict[str, list[int]] = {}
    h_off, h_on = hashlib.sha256(), hashlib.sha256()
    n_fb = n_up = n_exp_up = n_eq = n_guard = 0
    delta: dict[float, int] = {}
    short_seen: dict[int, float] = {}
    tgt_drop: dict[int, float] = {}
    regimes: dict[str, int] = {}
    for s in seeds:
        w = build(s)
        res = check_world(w, S)
        regimes[w["regime"]] = regimes.get(w["regime"], 0) + 1
        if res["i3_short"] > 0:
            short_seen[s] = res["i3_short"]
        if res["t"][0] is not None and res["t"][1] is not None and res["t"][1] < res["t"][0]:
            tgt_drop[s] = res["t"][0] - res["t"][1]
        for k in res["viol"]:
            viol.setdefault(k, []).append(s)
        h_off.update(f"{s}:{res['dig'][0]}\n".encode())
        h_on.update(f"{s}:{res['dig'][1]}\n".encode())
        n_fb += 1 if res["fb"] else 0
        n_guard += 1 if res["guard"] else 0
        t0, t1 = res["t"]
        if t0 is not None and t1 is not None:
            n_up += 1 if t1 > t0 else 0
            n_eq += 1 if t1 == t0 else 0
            delta[t1 - t0] = delta.get(t1 - t0, 0) + 1
        n_exp_up += 1 if res["export_up"] else 0
    i3_raw = viol.get("I3", [])
    viol["I3"] = [s for s in i3_raw if s not in KNOWN_I3_RESIDUAL or short_seen.get(s, 99.0) > KNOWN_I3_RESIDUAL[s] + 1e-9]
    i1_raw = viol.get("I1", [])
    viol["I1"] = [s for s in i1_raw if s not in KNOWN_I1_RESIDUAL or tgt_drop.get(s, 99.0) > KNOWN_I1_RESIDUAL[s] + 1e-9]
    names = {"I1": "recommended overnight target ON >= OFF",
             "I2": "target within [desired minimum, max SOC]; reserve policy and SHADOW unchanged",
             "I3": "pessimistic-case (unrounded) target ON >= OFF",
             "I5": "no fallback day: the whole report is identical ON and OFF",
             "I6": "fallback days: LOW cap, reason code, reason + uncertainty per day; otherwise absent",
             "I7": "model level: planning band <= both bands per quantile, sorted, finite, spread kept, pessimistic PV never above the ungated one",
             "I8": "the guard: two advices on a fallback day (the ungated one IS the gate-OFF answer), the higher target published, the code exactly then"}
    for k, nm in names.items():
        rec(f"{k}: {nm} ({len(seeds)} worlds, {len(viol.get(k, []))} violation(s))", not viol.get(k), f"first seeds {viol.get(k, [])[:8]}")
    if pin is not None:
        rec("I4: what the engine publishes about PV, over all worlds, gate OFF, is byte-identical to the pre-fix tree", h_off.hexdigest() == pin["off"],
            h_off.hexdigest())
        rec("I4: ... and gate ON", h_on.hexdigest() == pin["on"], h_on.hexdigest())
    rec(f"the worlds exercise the fix: the gate fell back in {n_fb} of {len(seeds)} worlds (at least a quarter)", n_fb >= len(seeds) // 4)
    if rec.loud:
        print(f"  info: regimes {dict(sorted(regimes.items()))}")
        print(f"  info: target ON vs OFF: raised in {n_up}, equal in {n_eq}, lowered in {sum(c for d, c in delta.items() if d < 0)} worlds; "
              f"change distribution (points: worlds) {dict(sorted(delta.items()))}")
        print(f"  info: the guard published the ungated advice in {n_guard} of {len(seeds)} worlds (informational)")
        print(f"  info: safe-export advice ON above OFF in {n_exp_up} worlds (informational)")
        if viol.get("I1") or viol.get("I3"):
            print(f"  info: I1 seeds {viol.get('I1')} drops {[tgt_drop.get(s) for s in viol.get('I1', [])]}; "
                  f"I3 seeds {viol.get('I3')} shortfalls {[short_seen.get(s) for s in viol.get('I3', [])]}")
    return {"viol": viol, "n_fb": n_fb, "delta": delta, "export_up": n_exp_up, "guard": n_guard}


def sec_cycle_range(S: Stack, rec, seeds=CYCLE_SEEDS, label: str = "[9d] the shadow-cycle worlds") -> dict:
    """I9a: the V1.1 charge target ON >= OFF; I9b: the V1 target inside the cycle ON >= OFF, over seeded cycle worlds."""
    rec.section(f"{label}: {len(seeds)} UNSEEN shadow-cycle worlds (every third seed of {seeds[0]}-{seeds[-1]})")
    v9a: list[int] = []
    v9b: list[int] = []
    n_fb = n_fired = n_head = n_morn = n_up = 0
    for s in seeds:
        ci = W2.build_cycle_world(s)
        off = run_cycle_gate(S, ci, False)
        with _CtTap(S.C) as tap:
            on = run_cycle_gate(S, ci, True)
        c0, c1 = off.item("charge_target"), on.item("charge_target")
        if not (c0.value is None or (c1.value is not None and c1.value >= c0.value)):
            v9a.append(s)
        a0, a1 = off.engine_comparison, on.engine_comparison
        if a0 is not None and not (a1 is not None and a1["v1_target_soc_pct"] >= a0["v1_target_soc_pct"]):
            v9b.append(s)
        n_fb += 1 if len(tap.calls) == 2 else 0
        n_fired += 1 if GUARD in c1.reason_codes else 0
        n_up += 1 if (c0.value is not None and c1.value is not None and c1.value > c0.value) else 0
        if off.plan is not None and on.plan is not None and on.plan["headroom_ceiling_pct"] < off.plan["headroom_ceiling_pct"] - 1e-9:
            n_head += 1
        m0, m1 = off.item("predicted_morning_soc"), on.item("predicted_morning_soc")
        if (c0.value == c1.value and m0.value is not None and m1.value is not None
                and (m1.p10 > m0.p10 + 1e-9 or m1.value > m0.value + 1e-9 or m1.p90 > m0.p90 + 1e-9)):
            n_morn += 1
    rec(f"I9a: the V1.1 charge target ON >= OFF ({len(seeds)} worlds, {len(v9a)} violation(s))", not v9a, f"first seeds {v9a[:8]}")
    rec(f"I9b: the V1 target inside the cycle ON >= OFF ({len(seeds)} worlds, {len(v9b)} violation(s))", not v9b, f"first seeds {v9b[:8]}")
    rec(f"the worlds exercise the fix: a fallback in {n_fb} of {len(seeds)} cycle worlds (at least a quarter)", n_fb >= len(seeds) // 4)
    if rec.loud:
        print(f"  info: charge target raised ON vs OFF in {n_up}; the guard published the ungated charge-target advice in {n_fired} (informational)")
        print(f"  info: plan headroom ceiling lower with the gate ON in {n_head}; morning SOC higher at an equal target in {n_morn} (informational)")
    return {"v9a": v9a, "v9b": v9b, "n_fb": n_fb}


# ---------------------------------------------------------------------------------------------------------------------
def battery(S: Stack, rec, full: bool = False, first: str | None = None) -> None:
    """The checks. `first` names a section to run before the others (the mutation battery runs the section most likely to catch a mutant first)."""
    secs = [sec_pinned, sec_trace, sec_model, sec_band, sec_spread, sec_plumbing, sec_contract, sec_guard, sec_cycle_guard, sec_reanchor,
            sec_cycle, sec_worlds]
    if first is not None:
        secs.sort(key=lambda f: f.__name__ != first)           # stable: the named section first, the rest in their order
    if full:
        secs.append(sec_property)
        secs.append(lambda S_, r_: sec_property(S_, r_, SEEDS2, "[9b] the same invariants on the second round-1 range"))
        secs.append(lambda S_, r_: sec_property(S_, r_, SEEDS3, "[9c] ROUND 2", W2.build_world2, PINNED_RANGE3, True))
        secs.append(sec_cycle_range)
    for fn in secs:
        try:
            fn(S, rec)
        except Exception as exc:          # a mutant that crashes is as detected as one that answers wrongly
            rec(f"{fn.__name__} raised {type(exc).__name__}: {exc}", False)


# ---------------------------------------------------------------------------------------------------------------------
# mutants of the NEW logic, applied in memory (the files on disk are never touched); each `old` must occur exactly once in its file
# (key: pv = intelligence/pv.py, engine = intelligence/engine.py, cycle = intelligence/shadow_cycle.py)
MUTANTS = [
    # --- the planning band (pv.py): T1 -----------------------------------------------------------------------------------------------
    ("pv", "planning = persistence directly (no lower-of)", "    lo = [min(a, b) for a, b in zip(published, corrected)]\n",
     "    lo = list(published)\n", "sec_band"),
    ("pv", "planning = the ungated corrected band only", "    lo = [min(a, b) for a, b in zip(published, corrected)]\n",
     "    lo = list(corrected)\n", "sec_band"),
    ("pv", "min on p50 only (p10 and p90 stay persistence's)", "    lo = [min(a, b) for a, b in zip(published, corrected)]\n",
     "    lo = [published[0], min(published[1], corrected[1]), published[2]]\n", "sec_band"),
    ("pv", "min on p10 only", "    lo = [min(a, b) for a, b in zip(published, corrected)]\n",
     "    lo = [min(published[0], corrected[0]), published[1], published[2]]\n", "sec_band"),
    ("pv", "wrong direction (max instead of min)", "    lo = [min(a, b) for a, b in zip(published, corrected)]\n",
     "    lo = [max(a, b) for a, b in zip(published, corrected)]\n", "sec_band"),
    ("pv", "no re-sorting", "    return tuple(sorted(lo))\n", "    return tuple(lo)\n", "sec_band"),
    ("pv", "the round-1 per-quantile minimum: the spread below the median is not kept",
     "    lo[0] = max(0.0, min(lo[0], corrected[0] - max(0.0, corrected[1] - lo[1])))\n", "", "sec_band"),
    ("pv", "p10 is not clamped at zero",
     "    lo[0] = max(0.0, min(lo[0], corrected[0] - max(0.0, corrected[1] - lo[1])))\n",
     "    lo[0] = min(lo[0], corrected[0] - max(0.0, corrected[1] - lo[1]))\n", "sec_band"),
    ("pv", "p10 moves down by only half the lowering of the median",
     "    lo[0] = max(0.0, min(lo[0], corrected[0] - max(0.0, corrected[1] - lo[1])))\n",
     "    lo[0] = max(0.0, min(lo[0], corrected[0] - 0.5 * max(0.0, corrected[1] - lo[1])))\n", "sec_band"),
    ("pv", "the conservative value also applied when the gate is OFF or keeps (a trace on every forecast)",
     "        return self._corrected_forecast(day, src, raw, r, n, mae_c, mae_r, notes, verdict)\n",
     "        pf = self._corrected_forecast(day, src, raw, r, n, mae_c, mae_r, notes, verdict)\n"
     "        ps = self._persistence(day, [], default_note=False)\n"
     "        pf.gate_fallback = GateFallback(src, 'x', 0, None, None, '', (pf.p10, pf.p50, pf.p90), pf.inflation,\n"
     "                                        conservative_band((ps.p10, ps.p50, ps.p90), (pf.p10, pf.p50, pf.p90)), pf.confidence, pf.label)\n"
     "        return pf\n", "sec_pinned"),
    ("pv", "the conservative value applied to the PUBLISHED forecast",
     "                                            corrected.confidence, corrected.label)\n",
     "                                            corrected.confidence, corrected.label)\n            pf.p10, pf.p50, pf.p90 = pf.gate_fallback.planning\n",
     "sec_pinned"),
    ("pv", "planning inflation = the published one only (the ungated widening is lost)",
     "return self.inflation if self.gate_fallback is None else max(self.inflation, self.gate_fallback.corrected_inflation)",
     "return self.inflation", "sec_model"),
    ("pv", "the trace does not carry the ungated inflation", "corrected.inflation, conservative_band(", "1.0, conservative_band(", "sec_model"),
    ("pv", "planning band ignores the fallback (always the published band)",
     "return (self.p10, self.p50, self.p90) if self.gate_fallback is None else self.gate_fallback.planning",
     "return (self.p10, self.p50, self.p90)", "sec_pinned"),
    ("pv", "the fallback is never recorded", 'if corrected is not None and pf.label != "INSUFFICIENT":', "if False:", "sec_pinned"),
    ("pv", "the ungated forecast is computed on the live notes (the published notes are polluted)",
     "mae_c, mae_r, list(notes), verdict)", "mae_c, mae_r, notes, verdict)", "sec_pinned"),
    ("pv", "the trace takes persistence as the ungated band", "c_band = (corrected.p10, corrected.p50, corrected.p90)",
     "c_band = (pf.p10, pf.p50, pf.p90)", "sec_model"),
    # --- the guard's rule and the ungated trace (pv.py): T2 ---------------------------------------------------------------------------
    ("pv", "guard picks the LOWER target (prefers_ungated reversed)", "ungated_target > planning_target\n", "ungated_target < planning_target\n",
     "sec_reanchor"),
    ("pv", "tie rule flipped (an equal target publishes the ungated advice)", "ungated_target > planning_target\n", "ungated_target >= planning_target\n",
     "sec_reanchor"),
    ("pv", "prefers_ungated accepts anything as a number", "        return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)\n",
     "        return True\n", "sec_reanchor"),
    ("pv", "the trace does not carry the ungated confidence (the persistence one is used)", "corrected.confidence, corrected.label)\n",
     "pf.confidence, pf.label)\n", "sec_guard"),
    # --- the engine: LOW cap, codes, planning values (round 1) ------------------------------------------------------------------------
    ("engine", "no LOW cap on a gate fallback", "            if gate_cap:\n                o = min(o, 0.45)\n",
     "            if gate_cap:\n                pass\n", "sec_trace"),
    ("engine", "the cap is MEDIUM, not LOW (0.55)", "            if gate_cap:\n                o = min(o, 0.45)\n",
     "            if gate_cap:\n                o = min(o, 0.55)\n", "sec_trace"),
    ("engine", "no code in downgrade_reasons", 'downgrades.append("PV_SKILL_GATE_FALLBACK")', "pass", "sec_trace"),
    ("engine", "no code in the advice reasons", 'advice["reasons"].append({"code": "PV_SKILL_GATE_FALLBACK", "text": txt})', "pass", "sec_trace"),
    ("engine", "no code in the advice uncertainty",
     'advice["uncertainty"].append({"code": "PV_SKILL_GATE_FALLBACK", "severity": "WATCH", "text": txt})', "pass", "sec_trace"),
    ("engine", "the code is misspelled in the advice", '{"code": "PV_SKILL_GATE_FALLBACK", "text": txt}', '{"code": "PV_SKILL_GATE_FALBACK", "text": txt}',
     "sec_trace"),
    ("engine", "the Planner sizes on the PUBLISHED band", "            p10, p50, p90 = fc.planning_band\n",
     "            p10, p50, p90 = fc.p10, fc.p50, fc.p90\n", "sec_plumbing"),
    ("engine", "the Planner gets the published inflation only",
     'pv_infl = max(([pv_info[k].get("inflation", 1.0) for k in pv_info if k != "today_reanchor"] + plan_trace["inflation"]) or [1.0])',
     'pv_infl = max([pv_info[k].get("inflation", 1.0) for k in pv_info if k != "today_reanchor"] or [1.0])', "sec_plumbing"),
    ("engine", "today's remaining PV in the planning run is the ungated one only (the planning median is ignored)",
     "rem = min(_reanchored(p50, done_share, inp.pv_actual_so_far_kwh)[0], urem)", "rem = urem", "sec_plumbing"),
    ("engine", "today's remaining PV in the planning run is no longer the lower of the two re-anchorings",
     "rem = min(_reanchored(p50, done_share, inp.pv_actual_so_far_kwh)[0], urem)",
     "rem = _reanchored(p50, done_share, inp.pv_actual_so_far_kwh)[0]", "sec_reanchor"),
    ("engine", "the published re-anchoring is computed from the planning p50",
     "rem, anchor = _reanchored(fc.p50, done_share, inp.pv_actual_so_far_kwh)", "rem, anchor = _reanchored(p50, done_share, inp.pv_actual_so_far_kwh)",
     "sec_plumbing"),
    ("engine", "a fallback is not collected for the trace", "                if gf is not None:\n                    plan[\"fallbacks\"]",
     "                if False:\n                    plan[\"fallbacks\"]", "sec_trace"),
    # --- the engine: the guard (T2) ---------------------------------------------------------------------------------------------------
    ("engine", "guard missing in the engine path", '        if gate_fallbacks:\n            ung = plan_trace["ungated"]\n',
     '        if False:\n            ung = plan_trace["ungated"]\n', "sec_guard"),
    ("engine", "guard applied with the gate OFF too (a second advice on every run)", '        if gate_fallbacks:\n            ung = plan_trace["ungated"]\n',
     '        if True:\n            ung = plan_trace["ungated"]\n', "sec_guard"),
    ("engine", "guard picks the LOWER target (the arguments reversed)", "            if prefers_ungated(t_plan, t_ung):\n",
     "            if prefers_ungated(t_ung, t_plan):\n", "sec_guard"),
    ("engine", "tie rule flipped (an equal target publishes the ungated advice)", "            if prefers_ungated(t_plan, t_ung):\n",
     "            if t_plan is not None and t_ung is not None and t_ung >= t_plan:\n", "sec_guard"),
    ("engine", "guard compares against the gate-aware run instead of the ungated one",
     'ung_advice = advice_for(ung["days"], ung_label, max(ung["inflation"] or [1.0]))', "ung_advice = advice_for(pv_days, label, pv_infl)", "sec_guard"),
    ("engine", "ungated alternative uses the planning (LOW) label",
     'ung_advice = advice_for(ung["days"], ung_label, max(ung["inflation"] or [1.0]))',
     'ung_advice = advice_for(ung["days"], label, max(ung["inflation"] or [1.0]))', "sec_guard"),
    # (a mutant "the ungated run uses the planning inflation" is EQUIVALENT: the planning inflation is max(published, ungated) and the
    # published persistence inflation is always 1.0, so it equals the ungated one on every path; the band-widening factor is mutated away instead)
    ("engine", "ungated alternative ignores the ungated band inflation (1.0)",
     'ung_advice = advice_for(ung["days"], ung_label, max(ung["inflation"] or [1.0]))',
     'ung_advice = advice_for(ung["days"], ung_label, 1.0)', "sec_guard"),
    ("engine", "ungated label computed AFTER the gate's LOW cap",
     'ung_label = confidence_label(overall_for(min(ung["confidence"] or [1.0]), False))',
     'ung_label = confidence_label(overall_for(min(ung["confidence"] or [1.0]), True))', "sec_guard"),
    ("engine", "ungated label computed from the published (persistence) PV confidence",
     'ung["confidence"].append(round(gf.corrected_confidence if gf is not None else fc.confidence, 3))',
     'ung["confidence"].append(round(fc.confidence, 3))', "sec_guard"),
    ("engine", "ungated PV days are the planning days", "            u10, u50, u90 = gf.corrected if gf is not None else (fc.p10, fc.p50, fc.p90)\n",
     "            u10, u50, u90 = fc.planning_band\n", "sec_guard"),
    ("engine", "ungated band inflation is the published one",
     'ung["inflation"].append(round(gf.corrected_inflation if gf is not None else fc.inflation, 3))',
     'ung["inflation"].append(round(fc.inflation, 3))', "sec_guard"),
    ("engine", "today's re-anchor on the PLANNING p50 in the ungated run", "urem, _anchor = _reanchored(u50, done_share, inp.pv_actual_so_far_kwh)",
     "urem, _anchor = _reanchored(p50, done_share, inp.pv_actual_so_far_kwh)", "sec_guard"),
    ("engine", "guard result without the gate's reason and uncertainty (the fallback loop skips a published ungated advice)",
     "        for g in gate_fallbacks:\n", "        for g in (gate_fallbacks if kept_ungated is None else []):\n", "sec_guard"),
    ("engine", "guard result without the plain reason that the ungated advice was kept", "        if kept_ungated is not None:\n            advice[\"reasons\"].append",
     "        if False:\n            advice[\"reasons\"].append", "sec_guard"),
    ("engine", "the guard's reason code is misspelled", '{"code": UNGATED_KEPT_CODE, "text": (', '{"code": "PV_SKILL_GATE_UNGATED_KEEP", "text": (', "sec_guard"),
    # --- the shadow cycle ---------------------------------------------------------------------------------------------------------------
    ("cycle", "the plan's hourly view uses the published p50", "pv_days = {d: (fc.planning_band[1], shape)", "pv_days = {d: (fc.p50, shape)", "sec_cycle"),
    ("cycle", "the plan's PV band is the published band", "pv_band = tfc.planning_band if tfc",
     "pv_band = (tfc.p10, tfc.p50, tfc.p90) if tfc", "sec_cycle"),
    ("cycle", "the PV credit label rule for a gate fallback is dropped", "        if fc is not None and fc.gate_fallback is not None:\n",
     "        if False:\n", "sec_cycle"),
    ("cycle", "guard missing in the shadow path", "        if ung_credit is not None:\n", "        if False:\n", "sec_cycle_guard"),
    ("cycle", "guard picks the LOWER target in the shadow path", "                                 for a in (target, ung_target))):\n",
     "                                 for a in (ung_target, target))):\n", "sec_cycle_guard"),
    ("cycle", "ungated credit offered at the planning (LOW) label", "ung_credit = (max(0.0, gfb.corrected[0] * share), gfb.corrected_label)",
     'ung_credit = (max(0.0, gfb.corrected[0] * share), "LOW")', "sec_cycle_guard"),
    ("cycle", "ungated credit sized on the planning p10", "ung_credit = (max(0.0, gfb.corrected[0] * share), gfb.corrected_label)",
     "ung_credit = (max(0.0, gfb.planning[0] * share), gfb.corrected_label)", "sec_cycle_guard"),
    ("cycle", "the second charge-target advice is computed with the planning credit", "            ung_target = target_for(*ung_credit)\n",
     "            ung_target = target_for(credit, credit_label)\n", "sec_cycle_guard"),
    ("cycle", "guard result in the shadow path without the plain reason", "target = replace(ung_target, reasons=ung_target.reasons + (Reason(UNGATED_KEPT_CODE, (",
     "target = replace(ung_target, reasons=ung_target.reasons + (Reason('PV_SKILL_GATE_UNGATED_KEEP', (", "sec_cycle_guard"),
]


def load_variant(text: str, name: str, path: Path):
    mod = types.ModuleType("intelligence." + name)
    mod.__package__ = "intelligence"
    mod.__file__ = str(path)
    sys.modules[mod.__name__] = mod
    try:
        exec(compile(text, str(path), "exec"), mod.__dict__)
    except BaseException:
        sys.modules.pop(mod.__name__, None)
        raise
    return mod


def build_stack(tag: str, key: str | None = None, old: str = "", new: str = "") -> Stack:
    """A Stack of in-memory modules compiled from the three source files, one of them mutated (key None: unmodified)."""
    texts = {k: pth.read_text(encoding="utf-8") for k, pth in PATHS.items()}
    if key is not None:
        n = texts[key].count(old)
        if n != 1:
            raise ValueError(f"{n} occurrences of {old!r} in {PATHS[key].name}")
        texts[key] = texts[key].replace(old, new, 1)
    M = load_variant(texts["pv"], f"{tag}_pv", PATHS["pv"])
    E = load_variant(texts["engine"], f"{tag}_engine", PATHS["engine"])
    C = load_variant(texts["cycle"], f"{tag}_cycle", PATHS["cycle"])
    E.PvModel = M.PvModel
    C.PvModel = M.PvModel
    C.IntelligenceEngine = E.IntelligenceEngine
    for mod in (E, C):                       # names the engine and the cycle import from pv: take the variant's, not the real module's
        mod.prefers_ungated = M.prefers_ungated
        mod.UNGATED_KEPT_CODE = M.UNGATED_KEPT_CODE
    return Stack(M, E, C)


def drop_stack(tag: str) -> None:
    for part in ("pv", "engine", "cycle"):
        sys.modules.pop(f"intelligence.{tag}_{part}", None)


class _Dead(BaseException):
    """Raised by the first failing check of a mutated stack: the mutant is caught, no need to run the rest."""


class _StopRec(G.Rec):
    def __call__(self, name: str, ok: bool, detail: str = "") -> None:
        super().__call__(name, ok, detail)
        if not ok:
            raise _Dead(name)


def first_failure(S: Stack, first: str | None = None) -> str | None:
    try:
        battery(S, _StopRec(False), full=False, first=first)
    except _Dead as d:
        return str(d)
    return None


def run_mutants(rec) -> None:
    rec.section(f"[10] mutation: {len(MUTANTS)} mutants of the new logic, applied in memory, each must be caught")
    base = build_stack("base")
    try:
        ff = first_failure(base)
    finally:
        drop_stack("base")
    rec("the unmodified sources, compiled as in-memory modules, pass the whole battery (the mutants' baseline)", ff is None, str(ff))
    killed = 0
    for i, (key, name, old, new, hint) in enumerate(MUTANTS):
        tag = f"mut{i}"
        try:
            S = build_stack(tag, key, old, new)
        except ValueError as exc:
            rec(f"mutant '{name}' applies exactly once", False, str(exc))
            continue
        except Exception as exc:                 # a mutant that does not even compile is detected too
            rec(f"mutant '{name}' is caught (does not load: {type(exc).__name__})", True)
            killed += 1
            continue
        try:
            ff = first_failure(S, hint)          # the section most likely to catch it runs first (the rest still run if it does not)
        except Exception as exc:                 # a mutant that crashes the battery outside a check is detected too
            ff = f"crash {type(exc).__name__}: {exc}"
        finally:
            drop_stack(tag)
        rec(f"mutant '{name}' is caught" + (f" by: {ff[:110]}" if ff else ""), ff is not None, "SURVIVED")
        killed += 1 if ff is not None else 0
    rec(f"{killed} of {len(MUTANTS)} mutants killed, at least 15 (round 1) plus at least 12 of the round-2 band and guard logic",
        killed == len(MUTANTS) and killed >= 27, f"{killed}")


def main() -> int:
    rec = _Loud()
    battery(REAL, rec, full=True)
    if FAILURES:
        print("\nmutation checks skipped: the real code fails the checks above")
    else:
        run_mutants(rec)
    print("")
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("all PV gate planning checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
