#!/usr/bin/env python3
"""Regression tests for the configurable battery reserve (all synthetic, seeded, offline):

  effective_min_soc = max(user_reserve_soc_pct, technical_min_soc_pct [, a run-time HA reserve value])

  [1] defaults: 40 % is the DEFAULT user reserve, not a project-wide constant; the technical minimum is separate
  [2] the user's reserve is honoured (20 / 30 / 40 / 50 %) in the report, the target, the export advice
  [3] the technical minimum raises the effective minimum and says why; below the user reserve it changes nothing
  [4] invalid reserves are refused at construction (negative, > 100, NaN, infinite, bool, str) and impossible ranges too
  [5] advice never crosses the effective minimum (target, pessimistic path, export), at every reserve
  [6] nothing in the package still treats 40 as an immutable floor
  [7] MUTATION: break the effective-minimum logic and prove these tests notice
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def section(title: str) -> None:
    print(f"\n== {title}")


from intelligence.config import DEFAULT_TECHNICAL_MIN_SOC_PCT, DEFAULT_USER_RESERVE_SOC_PCT, EffectiveReserve, SiteConfig
from intelligence.replay import replay
from intelligence.synthetic import make_history, solcast_like
from intelligence.timeutil import local_wall, zone

ROOT = Path(__file__).resolve().parents[2]
cfg = SiteConfig()
tz = zone(cfg.tz)
START = date(2026, 7, 1)
NOW_DAY = date(2026, 9, 9)
NOW = local_wall(NOW_DAY, 21 * 60 + 30, tz)
history = make_history(START, 75, cfg, seed=3)
forecast = {"solcast": solcast_like(history, cfg, over_factor=1.0, noise=0.08)}
ETA = cfg.round_trip_efficiency ** 0.5


def run(c: SiteConfig = cfg, soc: float | None = 75.0, **ov) -> dict:
    return replay(history, c, NOW, forecast, soc_override=soc, **ov)


def reasons(r: dict) -> list[str]:
    return [x["code"] for x in r["recommended"].get("reasons", [])]


def rejected(**kw) -> bool:
    try:
        SiteConfig(**kw)
    except ValueError:
        return True
    return False


def expected_effective(user: float, tech: float, ha: float | None = None) -> float:
    """Independent restatement of the rule (deliberately NOT calling SiteConfig)."""
    cands = [user, tech] + ([min(100.0, ha)] if isinstance(ha, (int, float)) and math.isfinite(ha) else [])
    return max(cands)


def violations(c: SiteConfig, soc: float, ha: float | None = None) -> list[str]:
    """Everything a report must satisfy for this config. Used both as the test and as the mutation detector."""
    r = run(c, soc=soc, ha_reserve_pct=ha)
    rec = r["recommended"]
    bad: list[str] = []
    want = expected_effective(c.user_reserve_soc_pct, c.technical_min_soc_pct, ha)
    if rec["floor_pct"] != want or rec["reserve"]["effective_pct"] != want:
        bad.append(f"effective minimum {rec['floor_pct']} != {want}")
    if rec["desired_min_pct"] != want + c.soc_safety_margin_pct:
        bad.append("comfort line is not effective minimum + margin")
    if rec.get("status") != "OK":
        return bad
    ot = rec["overnight_target"]
    if ot["recommended_target_soc_pct"] < want + c.soc_safety_margin_pct - 1e-9:
        bad.append(f"target {ot['recommended_target_soc_pct']} below effective minimum + margin")
    if ot["feasible_on_pessimistic_path"] and rec["predicted"]["min_soc_after_charge_pessimistic"] < want + c.soc_safety_margin_pct - 1e-6:
        bad.append("pessimistic path crosses the effective minimum although declared feasible")
    ex = rec["safe_export"]["kwh"]
    if ex > max(0.0, (soc - want - c.soc_safety_margin_pct) / 100.0 * c.battery_capacity_kwh * ETA) + 1e-6:
        bad.append(f"export {ex} kWh would take SOC below the effective minimum + margin")
    return bad


# ---------------------------------------------------------------------------------------------------------------
section("[1] defaults: 40 % is a default value, the technical minimum is a separate constraint")
check("default user reserve = 40 %", cfg.user_reserve_soc_pct == 40.0 == DEFAULT_USER_RESERVE_SOC_PCT)
check("the default technical minimum is its own value and does not encode the 40 % preference",
      cfg.technical_min_soc_pct == DEFAULT_TECHNICAL_MIN_SOC_PCT and cfg.technical_min_soc_pct < 40.0)
er = cfg.effective_reserve()
check("default effective minimum = 40 %, bound by the user reserve, no override reason",
      isinstance(er, EffectiveReserve) and er.effective_pct == 40.0 and er.binding == "user_reserve"
      and er.override_code is None and er.override_reason is None and er.ha_reserve_pct is None)
check("the effective reserve is plain JSON-able data (consumable by a UI or a later module)",
      json.dumps(er.as_dict(), allow_nan=False) is not None and set(er.as_dict()) >= {"user_reserve_pct", "technical_min_pct", "effective_pct", "binding"})
try:
    er.effective_pct = 1.0                      # type: ignore[misc]
    frozen = False
except Exception:
    frozen = True
check("the effective reserve is frozen data: it commands nothing and cannot be edited in flight", frozen)
r40 = run()
check("a default report exposes configured / technical / effective reserve",
      r40["recommended"]["reserve"]["user_reserve_pct"] == 40.0 and r40["recommended"]["reserve"]["technical_min_pct"] == DEFAULT_TECHNICAL_MIN_SOC_PCT
      and r40["recommended"]["reserve"]["effective_pct"] == 40.0 and r40["recommended"]["floor_pct"] == 40.0)
check("a different reserve changes the config hash (it is part of the report's provenance)",
      replace(cfg, user_reserve_soc_pct=30.0).config_hash() != cfg.config_hash())

# ---------------------------------------------------------------------------------------------------------------
section("[2] the user's reserve is honoured")
tgts = {}
exports = {}
for res in (20.0, 30.0, 40.0, 50.0):
    c = replace(cfg, user_reserve_soc_pct=res)
    r = run(c)
    rec = r["recommended"]
    tgts[res] = rec["overnight_target"]["recommended_target_soc_pct"]
    exports[res] = rec["safe_export"]["kwh"]
    check(f"user reserve {res:.0f} %: effective minimum is {res:.0f} %, comfort line {res + 5:.0f} %",
          rec["floor_pct"] == res and rec["reserve"]["effective_pct"] == res and rec["desired_min_pct"] == res + 5.0)
    check(f"user reserve {res:.0f} %: no override reason (the user's number applies)", rec["reserve"]["override_reason"] is None
          and not [x for x in reasons(r) if "OVERRIDES" in x or "RAISES" in x])
    check(f"user reserve {res:.0f} %: the target explanation quotes {res:.0f} %",
          any(f"your {res:.0f}% reserve" in x["text"] for x in rec["reasons"] if x["code"] in ("TARGET", "SHORTFALL")))
    check(f"user reserve {res:.0f} %: invariants hold (target, pessimistic path, export)", not violations(c, 75.0), str(violations(c, 75.0)))
check("a lower reserve never asks for a HIGHER overnight target than a higher reserve", tgts[20.0] <= tgts[30.0] <= tgts[40.0] <= tgts[50.0], str(tgts))
check("a lower reserve never allows LESS safe export than a higher reserve", exports[20.0] >= exports[30.0] >= exports[40.0] >= exports[50.0], str(exports))
check("the reserve is an input: 20 % and 50 % give different advice", tgts[20.0] != tgts[50.0] or exports[20.0] != exports[50.0], str((tgts, exports)))

# ---------------------------------------------------------------------------------------------------------------
section("[3] technical minimum vs user reserve")
low_tech = replace(cfg, user_reserve_soc_pct=30.0, technical_min_soc_pct=10.0)
check("technical minimum BELOW the user reserve: the user reserve applies, no override",
      low_tech.effective_reserve().effective_pct == 30.0 and low_tech.effective_reserve().binding == "user_reserve"
      and low_tech.effective_reserve().override_reason is None)
equal = replace(cfg, user_reserve_soc_pct=25.0, technical_min_soc_pct=25.0)
check("technical minimum EQUAL to the user reserve: the user's number is reported as binding, no override",
      equal.effective_reserve().effective_pct == 25.0 and equal.effective_reserve().binding == "user_reserve" and equal.effective_reserve().override_reason is None)
hi_tech = replace(cfg, user_reserve_soc_pct=20.0, technical_min_soc_pct=25.0)
eh = hi_tech.effective_reserve()
check("technical minimum ABOVE the user reserve: it wins", eh.effective_pct == 25.0 and eh.binding == "technical_min")
check("... with a clear, quantified reason", eh.override_code == "TECHNICAL_MIN_OVERRIDES_USER_RESERVE"
      and "20%" in eh.override_reason and "25%" in eh.override_reason, str(eh.override_reason))
rh = run(hi_tech)
check("the report uses the technical minimum (never the lower user reserve)", rh["recommended"]["floor_pct"] == 25.0 and rh["recommended"]["desired_min_pct"] == 30.0)
check("the reason is emitted in the recommendation's reasons and in the reserve block",
      "TECHNICAL_MIN_OVERRIDES_USER_RESERVE" in reasons(rh) and rh["recommended"]["reserve"]["override_reason"] == eh.override_reason
      and rh["recommended"]["reserve"]["user_reserve_pct"] == 20.0 and rh["recommended"]["reserve"]["technical_min_pct"] == 25.0)
check("no override reason when the technical minimum is not binding", "TECHNICAL_MIN_OVERRIDES_USER_RESERVE" not in reasons(run(low_tech)))
check("invariants hold with the technical minimum binding", not violations(hi_tech, 75.0), str(violations(hi_tech, 75.0)))
for ha, want, code in ((15.0, 40.0, None), (40.0, 40.0, None), (55.0, 55.0, "HA_RESERVE_RAISES_USER_RESERVE"), (250.0, 100.0, "HA_RESERVE_RAISES_USER_RESERVE")):
    e = cfg.effective_reserve(ha)
    check(f"run-time HA reserve {ha:g} %: effective {want:g} % (raise-only), override code {code}", e.effective_pct == want and e.override_code == code, str(e))
check("a NaN / infinite / negative / bool / non-numeric HA reserve is ignored, never lowers or breaks the minimum",
      all(cfg.effective_reserve(x).effective_pct == 40.0 for x in (float("nan"), float("inf"), float("-inf"), -5.0, None, "high", True)))

# ---------------------------------------------------------------------------------------------------------------
section("[4] invalid reserves and impossible ranges are refused at construction")
for field in ("user_reserve_soc_pct", "technical_min_soc_pct"):
    for label, val in (("negative", -1.0), ("far negative", -50.0), ("over 100", 100.1), ("200", 200.0), ("NaN", float("nan")),
                       ("+inf", float("inf")), ("-inf", float("-inf")), ("bool", True), ("string", "40"), ("None", None)):
        check(f"{field} = {label} is rejected", rejected(**{field: val}))
check("0 % user reserve is accepted (the technical minimum then applies)",
      SiteConfig(user_reserve_soc_pct=0.0).effective_reserve().effective_pct == DEFAULT_TECHNICAL_MIN_SOC_PCT)
check("max SOC equal to the effective minimum is rejected", rejected(max_soc_pct=40.0) and rejected(user_reserve_soc_pct=60.0, max_soc_pct=60.0))
check("max SOC below the effective minimum is rejected", rejected(max_soc_pct=30.0) and rejected(user_reserve_soc_pct=80.0, max_soc_pct=70.0))
check("max SOC at or below the TECHNICAL minimum is rejected even when the user reserve is lower",
      rejected(user_reserve_soc_pct=10.0, technical_min_soc_pct=60.0, max_soc_pct=60.0) and rejected(user_reserve_soc_pct=10.0, technical_min_soc_pct=70.0, max_soc_pct=60.0))
check("technical minimum above the allowed maximum is rejected", rejected(technical_min_soc_pct=100.0) and rejected(technical_min_soc_pct=95.0, max_soc_pct=90.0))
check("a reserve that leaves no room for the safety margin is rejected (no valid target range)",
      rejected(user_reserve_soc_pct=98.0) and rejected(user_reserve_soc_pct=96.0, max_soc_pct=100.0)
      and rejected(user_reserve_soc_pct=50.0, max_soc_pct=52.0))
check("the highest sensible reserve (95 % with a 5 % margin, max 100 %) is accepted", SiteConfig(user_reserve_soc_pct=95.0).effective_reserve().effective_pct == 95.0)
check("a bad max SOC / margin is still rejected", rejected(max_soc_pct=float("nan")) and rejected(max_soc_pct=120.0) and rejected(soc_safety_margin_pct=-1.0))
try:
    SiteConfig(user_reserve_soc_pct=-3.0)
except ValueError as e:
    check("the refusal message names the offending field and value", "user_reserve_soc_pct" in str(e) and "-3.0" in str(e), str(e))

# ---------------------------------------------------------------------------------------------------------------
section("[5] advice never crosses the effective minimum")
cases = []
for user, tech in ((20.0, 10.0), (30.0, 10.0), (40.0, 10.0), (50.0, 10.0), (20.0, 25.0), (0.0, 10.0), (70.0, 30.0)):
    for soc in (35.0, 62.0, 95.0):
        for ha in (None, 15.0, 60.0):
            cases.append((replace(cfg, user_reserve_soc_pct=user, technical_min_soc_pct=tech), soc, ha))
bad = []
for c, soc, ha in cases:
    v = violations(c, soc, ha)
    if v:
        bad.append((c.user_reserve_soc_pct, c.technical_min_soc_pct, soc, ha, v[:1]))
check(f"{len(cases)} reserve / technical-minimum / SOC / HA-reserve combinations: effective minimum exact, target >= minimum + margin, "
      f"feasible => pessimistic path above it, export never takes SOC below it", not bad, str(bad[:3]))
low = run(replace(cfg, user_reserve_soc_pct=20.0), soc=26.0)
check("SOC just above a 20 % reserve: export is limited by the comfort line (25 %), not by a hidden 40 %",
      low["recommended"]["safe_export"]["kwh"] <= max(0.0, (26.0 - 25.0) / 100.0 * cfg.battery_capacity_kwh * ETA) + 1e-6)
high = run(replace(cfg, user_reserve_soc_pct=50.0), soc=52.0)
check("SOC just above a 50 % reserve: no export advice at all", high["recommended"]["safe_export"]["kwh"] == 0.0)
check("early-return reports (no SOC) still carry the reserve context",
      run(soc=140.0)["recommended"]["status"] == "NO_SOC" and run(soc=140.0)["recommended"]["reserve"]["effective_pct"] == 40.0)

# ---------------------------------------------------------------------------------------------------------------
section("[6] nothing treats 40 as an immutable floor")
src = "\n".join(p.read_text(encoding="utf-8") for p in sorted((ROOT / "intelligence").glob("*.py")))
check("OWNER_POLICY_FLOOR_PCT and hard_min_soc_pct are gone from the package", "OWNER_POLICY_FLOOR" not in src and "hard_min_soc_pct" not in src and "effective_floor_pct" not in src)
cfg_src = (ROOT / "intelligence" / "config.py").read_text(encoding="utf-8")
check("the only 40 in the configuration is the DEFAULT user reserve",
      re.findall(r"=\s*40(?:\.0)?\b", cfg_src) == ["= 40.0"] and "DEFAULT_USER_RESERVE_SOC_PCT = 40.0" in cfg_src)
adv_src = (ROOT / "intelligence" / "advisor.py").read_text(encoding="utf-8")
check("the advisor has no numeric 40 % floor of its own", not re.search(r"\b40(\.0)?\s*%?\s*(floor|reserve)|floor\s*=\s*40", adv_src))
prof = json.loads((ROOT / "intelligence" / "profiles" / "site_profile.example.json").read_text(encoding="utf-8"))["site"]
check("the example profile exposes both settings and builds a valid config",
      SiteConfig(user_reserve_soc_pct=prof["user_reserve_soc_pct"], technical_min_soc_pct=prof["technical_min_soc_pct"]).effective_reserve().effective_pct == 40.0)

# ---------------------------------------------------------------------------------------------------------------
section("[7] mutation: break the effective-minimum logic and the tests above must notice")
orig = SiteConfig.effective_reserve


def mutant(name: str, fn) -> None:
    SiteConfig.effective_reserve = fn
    try:
        found = []
        for c, soc, ha in ((replace(cfg, user_reserve_soc_pct=20.0, technical_min_soc_pct=25.0), 62.0, None),
                           (replace(cfg, user_reserve_soc_pct=30.0), 62.0, None),
                           (replace(cfg, user_reserve_soc_pct=50.0), 75.0, None),
                           (cfg, 62.0, 60.0)):
            found += violations(c, soc, ha)
    finally:
        SiteConfig.effective_reserve = orig
    check(f"mutant '{name}' is caught", bool(found), "no test noticed")


def rebuild(self, eff: float, ha=None):
    return EffectiveReserve(self.user_reserve_soc_pct, self.technical_min_soc_pct, ha, eff, "user_reserve", None, None)


mutant("ignores the technical minimum", lambda self, ha=None: rebuild(self, float(self.user_reserve_soc_pct), ha))
mutant("ignores the user reserve (technical minimum only)", lambda self, ha=None: rebuild(self, float(self.technical_min_soc_pct), ha))
mutant("uses min() instead of max()", lambda self, ha=None: rebuild(self, min(self.user_reserve_soc_pct, self.technical_min_soc_pct), ha))
mutant("hard-codes 40 again", lambda self, ha=None: rebuild(self, 40.0, ha))
mutant("ignores a higher run-time reserve", lambda self, ha=None: rebuild(self, max(self.user_reserve_soc_pct, self.technical_min_soc_pct), None))
mutant("is off by the safety margin", lambda self, ha=None: rebuild(self, max(self.user_reserve_soc_pct, self.technical_min_soc_pct) - 5.0, ha))
check("the real logic is restored after the mutation runs", SiteConfig.effective_reserve is orig and not violations(hi_tech, 75.0))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence reserve:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print("All intelligence reserve checks PASSED.")
