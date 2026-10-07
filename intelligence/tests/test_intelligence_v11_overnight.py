#!/usr/bin/env python3
"""Intelligence V1.1 overnight demand learning on SYNTHETIC nights (fictional year 2030): estimates track the level,
confidence grows with history, one odd night moves little, weak history falls back or refuses, nothing leaks from the
future, and a return from an empty house raises the planning value without touching the expected one."""

from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import stats  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.explain import INSUFFICIENT, OK  # noqa: E402
from intelligence.overnight import NightObservation as N  # noqa: E402
from intelligence.overnight import OvernightSettings, learn_overnight, nightly_totals  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import local_wall, ts, zone  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


T = date(2030, 3, 1)
S = OvernightSettings.from_site(SiteConfig())


def nights(level=9.0, n=40, noise=0.06, seed=1, over: dict | None = None) -> list[N]:
    rnd = random.Random(seed)
    out = []
    for k in range(1, n + 1):
        d = T - timedelta(days=k)
        v = (over or {}).get(k, level * (1.0 + noise * rnd.gauss(0, 1)))
        out.append(N(d, round(v, 4) if type(v) is float else v))       # bools / None / odd values pass through as given
    return out


def rec(obs, s=S, t=T):
    a = learn_overnight(obs, t, s)
    return a, (dict(a.recommendation) if a.recommendation is not None else None)


print("[1] a stable house")
a, r = rec(nights())
check("OK with HIGH confidence on 28 clean nights", a.status == OK and a.confidence.label == "HIGH", a.confidence.label)
check("expected value near the level (9 kWh)", abs(r["expected_kwh"] - 9.0) < 0.6, str(r["expected_kwh"]))
check("planning value above the expected value, within a sensible band",
      r["expected_kwh"] < r["planning_kwh"] < r["expected_kwh"] * 1.5, f"{r['expected_kwh']} {r['planning_kwh']}")
check("uses the 28-night window only", r["nights_used"] == 28 and r["nights_window"] == 28)
check("explains the number", any(x.code == "OVERNIGHT_LEARNED" for x in a.reasons))
check("the learned value is demand only: no reserve or battery quantity in it",
      not any(k for k in r if "reserve" in k or "soc" in k))
check("deterministic and independent of input order",
      learn_overnight(nights(), T, S).to_dict() == learn_overnight(list(reversed(nights())), T, S).to_dict())

print("[2] confidence grows with history")
labels, scores = [], []
for n in (7, 10, 14, 21, 28):
    a_, _ = rec(nights(n=n))
    labels.append(a_.confidence.label)
    scores.append(a_.confidence.score)
check("score never falls as nights are added (7, 10, 14, 21, 28)", all(x <= y + 1e-12 for x, y in zip(scores, scores[1:])),
      str([round(s, 3) for s in scores]))
check("few nights are not HIGH, a full window is", labels[0] != "HIGH" and labels[-1] == "HIGH", str(labels))

print("[3] outliers")
base = rec(nights())[1]
spike = rec(nights(over={1: 30.0}))[1]          # last night 30 kWh (~3x)
sig = stats.robust_sigma([o.kwh for o in nights()[1:29]], 0.1)
check("one 3x night is clipped and named", bool(spike["nights_clipped"]) and spike["nights_clipped"][-1]["kwh"] == 30.0)
check("it moves the expected value by at most alpha x k x sigma (bounded influence)",
      spike["expected_kwh"] - base["expected_kwh"] <= S.alpha * S.winsor_k * sig + 0.05,
      f"{spike['expected_kwh'] - base['expected_kwh']:.3f} vs {S.alpha * S.winsor_k * sig:.3f}")
plain = base["expected_kwh"] + S.alpha * (30.0 - base["expected_kwh"])
check("much less than a plain recency-weighted mean would move", spike["expected_kwh"] < plain - 3.0, f"{spike['expected_kwh']} vs {plain}")

print("[4] weak history: conservative default or refusal, never an invented number")
a0, r0 = rec(nights(n=4))
check("4 nights, no default: INSUFFICIENT_DATA and no number", a0.status == INSUFFICIENT and r0 is None
      and a0.confidence.label == "INSUFFICIENT")
a1, r1 = rec(nights(n=4, level=6.0), OvernightSettings.from_site(SiteConfig(), prior_kwh=12.0))
check("4 nights with a 12 kWh default: flagged conservative fallback", a1.status == INSUFFICIENT and r1["conservative_fallback"])
check("...whose planning value is at least the default", r1["planning_kwh"] >= 12.0)
_, r2 = rec(nights(n=10, level=6.0), OvernightSettings.from_site(SiteConfig(), prior_kwh=12.0))
_, r3 = rec(nights(n=20, level=6.0), OvernightSettings.from_site(SiteConfig(), prior_kwh=12.0))
check("the default's weight shrinks as nights accumulate", r2["prior_weight"] > r3["prior_weight"] > 0.0
      and r3["expected_kwh"] < r2["expected_kwh"], f"{r2['prior_weight']} {r3['prior_weight']}")
_, r4 = rec(nights(n=30, level=6.0), OvernightSettings.from_site(SiteConfig(), prior_kwh=12.0))
check("a full window no longer leans on the default", r4["prior_weight"] == 0.0 and abs(r4["expected_kwh"] - 6.0) < 0.5)

print("[5] data hygiene")
leak = nights() + [N(T, 99.0), N(T + timedelta(days=1), 99.0)]
check("nights on or after the target night change nothing (no leakage)", learn_overnight(leak, T, S).to_dict() == a.to_dict())
dup = nights() + [N(T - timedelta(days=2), 50.0)]
ad, rd = rec(dup)
check("a night supplied twice is ignored, not guessed", rd["nights_used"] == 27 and any(x.code == "DUPLICATE_NIGHTS_IGNORED" for x in ad.reasons))
for bad in (float("nan"), float("inf"), -3.0, True):
    _, rb = rec(nights(over={5: bad}))
    check(f"a night total of {bad!r} is ignored as invalid", rb["nights_invalid"] == 1 and rb["nights_used"] == 27)
exc = [N(o.night, o.kwh, "DECLARED_AWAY") if (T - o.night).days in (3, 4, 5) else o for o in nights()]
ae, re_ = rec(exc)
check("caller-declared away nights are excluded and counted", re_["nights_excluded"] == {"DECLARED_AWAY": 3} and re_["nights_used"] == 25)
gap = [o for o in nights() if (T - o.night).days > 6]
ag, rg = rec(gap)
check("six missing recent nights: stale history lowers confidence and says so",
      any(x.code == "STALE_HISTORY" for x in ag.reasons) and ag.confidence.score < a.confidence.score - 0.2)

print("[6] return from an empty house / unusual period")
away = rec(nights(over={1: 2.0, 2: 1.8, 3: 2.2}))
aa, ra = away
check("three near-empty nights are LOW_RECENT", ra["regime"] == "LOW_RECENT", ra["regime"])
check("the planning value is raised to at least the older baseline's", ra["planning_kwh"] >= base["planning_kwh"] * 0.95
      and ra["planning_kwh"] >= ra["baseline_median_kwh"], f"{ra['planning_kwh']} vs {ra['baseline_median_kwh']}")
check("the expected value is left alone (it does fall with the recent nights)", ra["expected_kwh"] < base["expected_kwh"])
check("confidence drops below HIGH and the reason is stated",
      aa.confidence.label != "HIGH" and any(x.code == "REGIME_LOW_RECENT" for x in aa.reasons))
hi = rec(nights(over={1: 16.0, 2: 15.5, 3: 16.5}))[1]
check("three heavy nights are HIGH_RECENT with planning at least their level", hi["regime"] == "HIGH_RECENT" and hi["planning_kwh"] >= 16.0)
miss = rec(nights(over={1: None, 2: None}))
check("missing recent nights are INSUFFICIENT_RECENT (planning at least the baseline)",
      miss[1]["regime"] == "INSUFFICIENT_RECENT" and miss[1]["planning_kwh"] >= stats.quantile([o.kwh for o in nights()[3:28]], 0.9) - 1e-9)
check("a small dip is STABLE (no false alarm)", rec(nights(over={1: 8.4, 2: 8.5, 3: 8.6}))[1]["regime"] == "STABLE")
zero = rec(nights(level=0.0, noise=0.0, over={1: 8.0, 2: 8.5, 3: 7.5}))[1]
check("a rise from a zero baseline is HIGH_RECENT (not hidden by a zero denominator), ratio reported as None",
      zero["regime"] == "HIGH_RECENT" and zero["planning_kwh"] >= 8.0 and zero["recent_to_baseline_ratio"] is None, str(zero["regime"]))
check("a flat zero house is STABLE", rec(nights(level=0.0, noise=0.0))[1]["regime"] == "STABLE")

print("[7] nightly totals from the canonical history")
cfg = SiteConfig()
h = make_history(date(2030, 1, 1), 40, cfg, seed=3)
tot = nightly_totals(h, cfg, 330, 1440 + 30, date(2030, 1, 2), date(2030, 2, 8))
check("one observation per night, each a positive kWh (05:30 -> 00:30)", len(tot) == 38 and all(o.kwh and o.kwh > 0 for o in tot))
tz = zone(cfg.tz)
g0, g1 = ts(local_wall(date(2030, 1, 4), 330, tz)), ts(local_wall(date(2030, 1, 4), 1440 + 30, tz))
h2 = make_history(date(2030, 1, 1), 10, cfg, seed=3, drop_hours=set(range(g0 - g0 % 3600, g1, 3600)))   # night of 4 Jan gone
t2 = {o.night: o.kwh for o in nightly_totals(h2, cfg, 330, 1440 + 30, date(2030, 1, 2), date(2030, 1, 8))}
check("a night with too little data is None, never invented", t2[date(2030, 1, 4)] is None and t2[date(2030, 1, 6)] is not None)
try:
    nightly_totals(h, cfg, 600, 300, date(2030, 1, 2), date(2030, 1, 3))
    check("a period that ends before it starts is refused", False)
except ValueError:
    check("a period that ends before it starts is refused", True)
bad_settings = 0
for kw in ({"alpha": 0.0}, {"min_nights": 1}, {"prior_kwh": float("nan")}, {"planning_quantile": 1.0}, {"lookback_nights": 3}):
    try:
        OvernightSettings(**kw)
    except ValueError:
        bad_settings += 1
check("nonsense settings are refused at construction", bad_settings == 5)

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in intelligence V1.1 overnight:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll intelligence V1.1 overnight checks passed")
