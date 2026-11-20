"""Second synthetic world generator for the PV skill-gate planning checks (round 2; tests only). FICTIONAL numbers throughout.

It extends the frozen generator of round 1 (`_pv_worlds.py`, unchanged: its sha256 pins the earlier ranges) from six to EIGHT regimes
and reuses it for the first six, so those six are the very same worlds a seed would have given there:

    shaded, bright_then_dull, dull_then_bright, step, sparse, skilled      (the round-1 generator, called with the regime named)
    stale_after_dull     a long dull spell, then two to four bright days: persistence (a slow robust average) is stale and LOW while the
                         raw value for tomorrow is bright; the source has no skill
    skilled_kept         a source with real skill and a constant bias, whose forecast anticipates a dull tomorrow after a bright spell:
                         the gate is expected to KEEP the corrected forecast (the whole report must then be identical with the gate ON/OFF)

    build_world2(seed, regime=None, plausible=None)   one world (a dict, same shape as `_pv_worlds.build_world`)
    build_cycle_world(seed)                            one SHADOW-cycle input (the shared cycle fixture with its history and forecast
                                                       series replaced by a seeded bright spell and a source with no skill)

The regime is `REGIMES2[seed % 8]` unless named. Per world, as in round 1: 80 percent a plausible raw value for tomorrow, 20 percent an
implausible one (REJECTED by the unchanged plausibility guard, so the gate is never reached for tomorrow); the run time of day and
the SOC are drawn from the seed. This module is FROZEN once the round-2 seed range is pre-registered (its sha256 is recorded with the
range); it uses the code under test only through the public engine API, so it can also be run against the pre-fix tree.
"""

from __future__ import annotations

import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _pv_worlds as W1  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import local_wall  # noqa: E402

REGIMES2 = W1.REGIMES + ("stale_after_dull", "skilled_kept")
WCFG, WTZ, START, NOW_MINUTES = W1.WCFG, W1.WTZ, W1.START, W1.NOW_MINUTES
run_world, target, report_digest = W1.run_world, W1.target, W1.report_digest


def build_world2(seed: int, regime: str | None = None, plausible: bool | None = None) -> dict:
    regime = regime or REGIMES2[seed % len(REGIMES2)]
    if regime in W1.REGIMES:
        w = W1.build_world(seed, regime, plausible)
        w["regime"] = regime
        return w
    rnd = random.Random(seed)
    if plausible is None:
        plausible = rnd.random() < 0.8
    level = rnd.uniform(0.35, 0.7)
    n = rnd.randrange(50, 75)
    spell = 18 + (seed // len(REGIMES2)) % 13            # a long dull spell: 18 to 30 days (stale_after_dull)
    bright = 2 + (seed // len(REGIMES2)) % 3             # then two to four bright days
    bias = rnd.uniform(0.9, 1.6)                         # skilled_kept: a constant factor between the forecast and the actuals
    scale: dict = {}
    for k in range(n + 2):
        d = START + timedelta(days=k)
        left = n - k                                     # days before "today" (today is day n - 1)
        if regime == "stale_after_dull":
            s = (0.85 if left <= bright else (0.22 if left <= bright + spell else 0.7)) * (1 + 0.07 * rnd.gauss(0, 1))
        else:                                            # skilled_kept: a bright spell, then dull days that the forecast anticipates
            s = (0.35 if left <= 10 else 0.85) * (1 + 0.07 * rnd.gauss(0, 1))
        scale[d] = max(0.05, s)
    hist = make_history(START, n, WCFG, seed=seed, level=level, clearness=1.0, pv_scale_by_day=scale)
    src: dict = {}
    for k in range(n + 1):
        d = START + timedelta(days=k)
        if regime == "skilled_kept":
            src[d] = max(1.0, scale[d] * 30.0 * bias * (1 + 0.03 * rnd.gauss(0, 1)))
        else:
            src[d] = rnd.uniform(6.0, 28.0)              # independent of the actuals: a source with no skill
    today = START + timedelta(days=n - 1)
    tomorrow = today + timedelta(days=1)
    if regime == "stale_after_dull":
        tom = rnd.uniform(14.0, 26.0)
    else:
        tom = max(1.0, scale[tomorrow] * 30.0 * bias * (1 + 0.03 * rnd.gauss(0, 1)))
    if not plausible:
        tom = tom * rnd.uniform(9.0, 14.0)
    src[tomorrow] = tom
    now = local_wall(today, rnd.choice(NOW_MINUTES), WTZ)
    soc = rnd.uniform(25.0, 95.0)
    return {"seed": seed, "regime": regime, "plausible": plausible, "hist": hist, "fc": {"src": src}, "now": now, "soc": soc,
            "level": level, "n": n, "today": today, "tomorrow": tomorrow}


def build_cycle_world(seed: int):
    """The shared cycle fixture (`_cycle_fixtures`, 15 Jan of the fictional year 2030, 21:00 UTC) with its PV history and forecast
    series replaced: a bright spell of 4 to 11 days after a dull base, a source with no skill (raw values drawn independently of the
    actuals), a house of load level 0.2 / 0.35 / 0.5. Everything is drawn from the seed."""
    from dataclasses import replace
    import _cycle_fixtures as cf
    from intelligence.config import SiteConfig
    rnd = random.Random(seed)
    level = rnd.choice((0.2, 0.35, 0.5))
    spell = rnd.randrange(4, 12)
    bright = rnd.uniform(0.85, 1.0)
    base = rnd.uniform(0.2, 0.4)
    lo, hi = rnd.choice(((1.0, 6.0), (3.0, 12.0), (5.0, 25.0)))
    now = cf.NOW
    start = (now - timedelta(days=60)).date()
    cfg = SiteConfig(pv_array_kwp=cf.FACTS.pv_array_kwp)
    n = 61
    scale = {start + timedelta(days=k): (bright if n - k <= spell else base) * (1 + 0.07 * rnd.gauss(0, 1)) for k in range(n + 2)}
    hist = make_history(start, n, cfg, seed=seed, level=level, clearness=1.0, pv_scale_by_day=scale).truncated(now)
    fc = {"synthetic_forecast": {start + timedelta(days=k): rnd.uniform(lo, hi) for k in range(n)}}
    return replace(cf.cycle_inputs(synthetic_recorded=True), history=hist, pv_forecast_history=fc)
