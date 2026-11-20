"""Synthetic whole-engine worlds for the PV skill-gate planning checks (tests only). FICTIONAL numbers throughout: a seeded
generator (intelligence.synthetic) builds an hourly history, a day-ahead forecast series and one evening/daytime run, so the
overnight charge target of the SHADOW engine can be compared with the persistence-skill gate OFF and ON.

This module is FROZEN once the property test's seed range is pre-registered (the sha256 of this file is recorded with the
range): it must not depend on the code under test beyond the public engine API (it is also run against the pre-fix tree).

    build_world(seed, regime=None, plausible=None)   one world (a dict)
    run_world(w, gate, stack=None)                   the engine report for the world with the gate switched ON / OFF
    report_digest(report)                            sha256 of what the engine PUBLISHES about PV (report["pv"] and the
                                                     scoreable pv_kwh:day records), used to prove the published forecast unchanged
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence.config import SiteConfig  # noqa: E402
from intelligence.engine import IntelligenceEngine  # noqa: E402
from intelligence.pv import PvModel  # noqa: E402
from intelligence.replay import inputs_from_history  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import local_wall, zone  # noqa: E402

WCFG = SiteConfig(tz="Europe/London", pv_array_kwp=6.0, battery_capacity_kwh=24.0, max_grid_charge_kw=5.0)
WTZ = zone(WCFG.tz)
START = date(2030, 9, 1)
REGIMES = ("shaded", "bright_then_dull", "dull_then_bright", "step", "sparse", "skilled")
NOW_MINUTES = (10 * 60, 13 * 60 + 30, 17 * 60, 21 * 60 + 30)


def build_world(seed: int, regime: str | None = None, plausible: bool | None = None) -> dict:
    """One synthetic world. `regime` defaults to a cycle over REGIMES by seed; `plausible` False makes tomorrow's raw value
    far above anything the array can produce (the plausibility guard REJECTS it, so the gate is never reached for tomorrow)."""
    rnd = random.Random(seed)
    regime = regime or REGIMES[seed % len(REGIMES)]
    if plausible is None:
        plausible = rnd.random() < 0.8
    level = rnd.uniform(0.35, 0.7)
    n = rnd.randrange(14, 24) if regime == "sparse" else rnd.randrange(50, 75)
    scale: dict = {}
    for k in range(n + 2):
        d = START + timedelta(days=k)
        left = n - k                                     # days before "today" (today is day n - 1)
        if regime == "shaded":
            s = 0.28 * (1 + 0.06 * rnd.gauss(0, 1))
        elif regime == "bright_then_dull":
            spell = 5 + (seed // 6) % 8
            s = (0.9 if left <= spell else 0.3) * (1 + 0.07 * rnd.gauss(0, 1))
        elif regime == "dull_then_bright":
            spell = 5 + (seed // 6) % 8
            s = (0.25 if left <= spell else 0.8) * (1 + 0.07 * rnd.gauss(0, 1))
        elif regime == "step":
            up = (seed // 6) % 2 == 0
            lo, hi = 0.3, 0.85
            a, b = (lo, hi) if up else (hi, lo)
            s = (b if left <= 8 else a) * (1 + 0.07 * rnd.gauss(0, 1))
        elif regime == "sparse":
            s = rnd.uniform(0.25, 0.9)
        else:                                            # "skilled": the forecast below tracks these actuals
            s = rnd.uniform(0.2, 0.95)
        scale[d] = max(0.05, s)
    hist = make_history(START, n, WCFG, seed=seed, level=level, clearness=1.0, pv_scale_by_day=scale)
    src: dict = {}
    for k in range(n + 1):
        d = START + timedelta(days=k)
        if regime == "skilled":
            src[d] = max(1.0, scale[d] * 30.0 * 1.3 * (1 + 0.05 * rnd.gauss(0, 1)))
        else:
            src[d] = rnd.uniform(6.0, 28.0)              # independent of the actuals: a source with no skill
    today = START + timedelta(days=n - 1)
    tomorrow = today + timedelta(days=1)
    if regime == "bright_then_dull":
        tom = rnd.uniform(2.0, 9.0)
    elif regime == "dull_then_bright":
        tom = rnd.uniform(16.0, 26.0)
    else:
        tom = rnd.uniform(4.0, 26.0)
    if not plausible:
        tom = tom * rnd.uniform(9.0, 14.0)
    src[tomorrow] = tom
    now = local_wall(today, rnd.choice(NOW_MINUTES), WTZ)
    soc = rnd.uniform(25.0, 95.0)
    return {"seed": seed, "regime": regime, "plausible": plausible, "hist": hist, "fc": {"src": src}, "now": now, "soc": soc,
            "level": level, "n": n, "today": today, "tomorrow": tomorrow}


def run_world(w: dict, gate: bool, stack=None, cfg: SiteConfig = WCFG) -> dict:
    """The engine report of world `w` with the persistence-skill gate switched to `gate`. `stack` = (IntelligenceEngine class,
    PvModel class) to run a variant of the code under test (the mutation battery); default the real ones."""
    eng_cls, pv_cls = stack if stack is not None else (IntelligenceEngine, PvModel)
    now = w["now"]
    known = w["hist"].truncated(now)
    d0 = now.astimezone(WTZ).date()
    fck = {s: {d: v for d, v in tab.items() if d <= d0} for s, tab in w["fc"].items()}
    eng = eng_cls(known, cfg, fck)
    eng.pv = pv_cls(known, cfg, fck, skill_gate=gate)
    return eng.run(inputs_from_history(known, cfg, now, w["fc"], w["soc"]))


def target(report: dict) -> float | None:
    return (report.get("recommended") or {}).get("overnight_target", {}).get("recommended_target_soc_pct")


def report_digest(report: dict) -> str:
    """sha256 of the published PV side of a report: the per-day PV dicts and the scoreable PV records."""
    pv_records = [r for r in report.get("forecast_records", []) if r.get("kind") == "pv_kwh:day"]
    blob = json.dumps({"pv": report.get("pv"), "records": pv_records}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
