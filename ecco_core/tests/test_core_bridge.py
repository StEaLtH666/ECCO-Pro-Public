#!/usr/bin/env python3
"""ecco_core.bridge: the one crossing into Intelligence gates what the engine cannot judge (inverter status freshness),
passes the SOC with its age, and turns advice into frozen SHADOW records; end to end on a synthetic house. Offline."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ecco_core.bridge import AdvisoryRecord, advisory_live_inputs, record, record_report  # noqa: E402
from ecco_core.freshness import ADVISORY, CONTROL_GATE, FreshnessPolicy  # noqa: E402
from ecco_core.state import DERIVED, NORMALIZED, Observation, Snapshot  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.engine import IntelligenceEngine  # noqa: E402
from intelligence.overnight import NightObservation, OvernightSettings, learn_overnight  # noqa: E402
from intelligence.synthetic import make_history  # noqa: E402
from intelligence.timeutil import local_wall, zone  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


cfg = SiteConfig()
tz = zone(cfg.tz)
NOW = local_wall(date(2030, 6, 20), 19 * 60, tz)


def ob(sig: str, v, age: float | None = 5.0, kind=NORMALIZED, **kw) -> Observation:
    return Observation(sig, v, None if age is None else NOW - timedelta(seconds=age), "controller", kind, **kw)


base = [ob("battery.soc", 81.0, 30.0), ob("house.power", 640.0), ob("pv.power", 1500.0),
        ob("inverter.healthy", True, 20.0, DERIVED, derived_from=("inverter.state",)), ob("reserve.ha_minimum_soc", 50.0, 3600.0)]
snap = Snapshot.of(NOW, base)

print("[1] state -> advice: what passes and what is gated")
inp, ass = advisory_live_inputs(snap)
check("SOC passes with its age (the engine applies its own 15-minute rule)", inp.soc_pct == 81.0 and inp.soc_age_s == 30.0)
check("by default the inverter status is withheld: its advisory limit is UNRESOLVED", inp.inverter_ok is None
      and {a.signal: a.status for a in ass}["inverter.healthy"] == "unknown")
check("the HA reserve passes whatever its age (it can only raise the reserve)", inp.ha_reserve_pct == 50.0)
check("display readings pass through", inp.load_w == 640.0 and inp.pv_w == 1500.0)
site = FreshnessPolicy(ADVISORY, {"inverter.healthy": 180.0})
check("with a site limit, a fresh healthy status passes", advisory_live_inputs(snap, policy=site)[0].inverter_ok is True)
stale = Snapshot.of(NOW, [o if o.signal != "inverter.healthy" else
                          ob("inverter.healthy", True, 600.0, DERIVED, derived_from=("inverter.state",)) for o in base])
check("with a site limit, a stale healthy status is withheld", advisory_live_inputs(stale, policy=site)[0].inverter_ok is None)
check("the original snapshot is untouched by gating", snap.value("inverter.healthy") is True)
try:
    advisory_live_inputs(snap, policy=FreshnessPolicy(CONTROL_GATE))
    check("advisory inputs refuse a non-advisory policy", False)
except ValueError:
    check("advisory inputs refuse a non-advisory policy", True)
check("a missing SOC reaches the engine as unknown", advisory_live_inputs(Snapshot.of(NOW, []))[0].soc_pct is None
      and advisory_live_inputs(Snapshot.of(NOW, []))[0].soc_age_s is None)

print("[2] end to end: snapshot -> engine -> record")
hist = make_history(date(2030, 5, 1), 51, cfg, seed=11)        # up to and including NOW's day, so history is not stale
eng = IntelligenceEngine(hist.truncated(NOW), cfg)
rep = eng.run(inp)
check("the engine report is SHADOW and applies nothing", rep["mode"] == "SHADOW" and rep["applies_nothing"] is True)
check("with the status withheld, export advice is withheld",
      rep["recommended"].get("safe_export", {}).get("kwh", 0.0) == 0.0
      and "inverter" in rep["recommended"].get("safe_export", {}).get("withheld_because", ""))
rep2 = IntelligenceEngine(hist.truncated(NOW), cfg).run(advisory_live_inputs(snap, policy=site)[0])
check("with a fresh status (site limit) the engine advises export (above the 50 % HA reserve)",
      "withheld_because" not in rep2["recommended"]["safe_export"] and rep2["recommended"]["safe_export"]["kwh"] > 0.0,
      str(rep2["recommended"]["safe_export"]))
r1 = record_report(rep)
check("a V1 report becomes a SHADOW record", r1.mode == "SHADOW" and r1.applies_nothing and r1.as_dict()["applies_nothing"] is True)
for bad in ({**rep, "mode": "LIVE"}, {**rep, "applies_nothing": False}):
    try:
        record_report(bad)
        check("a report that is not SHADOW / applies-nothing cannot become a record", False)
    except ValueError:
        check("a report that is not SHADOW / applies-nothing cannot become a record", True)
adv = learn_overnight([NightObservation(date(2030, 6, 19) - timedelta(days=k), 9.0 + 0.1 * (k % 3)) for k in range(30)],
                      date(2030, 6, 20), OvernightSettings.from_site(cfg))
r2 = record(adv, NOW)
check("a V1.1 advice becomes a frozen SHADOW record", r2.kind == "overnight_demand" and r2.as_dict()["mode"] == "SHADOW")
attrs = r2.display_attributes()
check("display attributes are strict JSON and state SHADOW / applies_nothing",
      json.loads(json.dumps(attrs, allow_nan=False))["applies_nothing"] is True and attrs["mode"] == "SHADOW")
frozen = False
try:
    r2.payload = "{}"                                         # type: ignore[misc]
except Exception:  # noqa: BLE001 - FrozenInstanceError
    frozen = True
check("a record cannot be altered after creation", frozen)
try:
    AdvisoryRecord("x", "OK", "t", json.dumps({"mode": "SHADOW", "applies_nothing": True}), mode="LIVE")
    check("a record cannot claim a non-SHADOW mode", False)
except ValueError:
    check("a record cannot claim a non-SHADOW mode", True)
check("a record exposes no behaviour beyond reading itself",
      sorted(n for n in dir(AdvisoryRecord) if not n.startswith("_") and callable(getattr(AdvisoryRecord, n)))
      == ["as_dict", "display_attributes"])

if FAILURES:
    print(f"\n{len(FAILURES)} check(s) FAILED in ecco_core bridge:")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("\nAll ecco_core bridge checks passed")
