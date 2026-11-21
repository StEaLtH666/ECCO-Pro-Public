#!/usr/bin/env python3
"""The live power balance with the OPTIONAL inverter conversion site facts (synthetic round numbers only; no site value).

The balance check (intelligence/quality.py: power_balance_verdict, _power_rules) expects house = PV + battery + grid. PV and
battery power are DC-side readings, so a real inverter's conversion loss and own draw make the house power fall short of
that sum. Three optional site facts (inverter_dc_to_ac_factor, inverter_ac_to_dc_factor, inverter_standby_w) let the check
expect the loss. These checks use a synthetic inverter (DC to AC 0.90, AC to DC 0.92, standby 40 W): no number is a site
value.

  [1] the facts: absent = lossless; valid; every invalid form is refused with a reason that never names a value; the bounds
      (factors 0.85 to 1.0, standby 0 to 150 W) are inclusive and one step outside them is refused
  [2] the default is today's behaviour: a literal table of cases and a seeded sweep give exactly the verdict, residual and
      tolerance of the rule as it stood before the facts existed (a verbatim copy below), and a sweep through assess_inputs
      gives identical findings with no facts and with explicit lossless facts
  [3] the loss-aware expectation: both sides, idle, the continuity at zero net DC power, the tolerance floor and fraction
  [4] faults still block under the loss-aware rule: the grid CT reversed, the battery reversed, both, the native-load false
      zero and a negative house load (the rule's own tests and assess_inputs)
  [5] invalid facts are reported (POWER_LOSS_FACTS_INVALID, BLOCK on the items resting on the balance), never loosen the
      check, never name a value, and change nothing else
  [6] a wrong (too generous) conversion cannot hide a sign reversal at the tested powers, and a conversion whose
      expectation is wrong by less than half the tolerance can never hide a reversal of at least the tolerance
  [7] mutants: each deliberately wrong variant of the rule is told apart from the rule by this suite's case table
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _dq_helpers as h  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

FAILURES: list[str] = []
EXPORT = ("export_event", "dump_to_grid")
BALANCE_CODES = {"CT_SIGN_REVERSED", "BATTERY_SIGN_REVERSED", "POWER_BALANCE_INCONSISTENT"}
SIGN_CODES = {"CT_SIGN_REVERSED", "BATTERY_SIGN_REVERSED"}


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


# the synthetic inverter
DC_AC, AC_DC, STANDBY = 0.90, 0.92, 40.0
CONV = sd.InverterConversion(DC_AC, AC_DC, STANDBY)
FACTS = replace(cf.FACTS, inverter_dc_to_ac_factor=DC_AC, inverter_ac_to_dc_factor=AC_DC, inverter_standby_w=STANDBY)


def model_house(pv: float, batt: float, grid: float) -> float:
    """The synthetic inverter's true house power (rounded to a tenth of a watt): the loss-aware expectation, written out."""
    d = pv + batt
    return round(grid + (DC_AC * d if d >= 0 else d / AC_DC) - STANDBY, 1)


def old_rule(hw: float, p: float, b: float, g: float):
    """The balance rule exactly as it stood in intelligence/quality.py before the conversion facts existed (copied verbatim;
    the PROPOSED floor 100 W and fraction 0.05 written out): (code | None, residual, tolerance)."""
    flow = p + b + g
    tol = max(100.0, 0.05 * max(abs(hw), abs(p), abs(b), abs(g)))
    resid = hw - flow
    if abs(resid) <= tol:
        return None, resid, tol
    if abs(hw - (p + b - g)) <= tol and abs(g) > tol / 2.0:
        return "CT_SIGN_REVERSED", resid, tol
    if abs(hw - (p - b + g)) <= tol and abs(b) > tol / 2.0:
        return "BATTERY_SIGN_REVERSED", resid, tol
    return "POWER_BALANCE_INCONSISTENT", resid, tol


def balance_codes(res: q.QualityResult, severity: str = "BLOCK") -> set[str]:
    return h.codes(res, severity) & BALANCE_CODES


base = h.clean()


def assess(inp, signals: dict, facts=None):
    inp = faults.with_signals(inp, signals)
    return q.assess_inputs(inp if facts is None else replace(inp, site_facts=facts))


def sig(hw: float, p: float, b: float, g: float) -> dict:
    return {"house.power": hw, "pv.power": p, "battery.power": b, "grid.power": g}


print("== [1] the facts: absent, valid, invalid, the bounds")
conv0, prob0 = sd.inverter_conversion(cf.FACTS)
check("no inverter facts (all None): lossless and no problem", conv0 == sd.LOSSLESS_CONVERSION and conv0.lossless and prob0 == ())
check("inverter_conversion_stated: False for none, True for any one present (a valid or an invalid value alike)",
      not sd.inverter_conversion_stated(cf.FACTS) and not sd.inverter_conversion_stated(None)
      and all(sd.inverter_conversion_stated(replace(cf.FACTS, **{n: v})) for n in sd.INVERTER_CONVERSION_FACTS for v in (0.9, "x", float("nan"))))
check("the default SiteFacts carries the three facts as None",
      all(getattr(ac.SiteFacts(), n) is None for n in sd.INVERTER_CONVERSION_FACTS)
      and sd.INVERTER_CONVERSION_FACTS == ("inverter_dc_to_ac_factor", "inverter_ac_to_dc_factor", "inverter_standby_w"))
c1, p1 = sd.inverter_conversion(FACTS)
check("three valid facts: that conversion, no problem, not lossless",
      c1 == CONV and p1 == () and not c1.lossless and (c1.dc_to_ac, c1.ac_to_dc, c1.standby_w) == (DC_AC, AC_DC, STANDBY))
check("... integers are accepted (1, 1 and 0 are the lossless values)",
      sd.inverter_conversion(replace(cf.FACTS, inverter_dc_to_ac_factor=1, inverter_ac_to_dc_factor=1, inverter_standby_w=0))
      == (sd.LOSSLESS_CONVERSION, ()))
check("an object without the attributes reads as absent (never raises)",
      sd.inverter_conversion(None) == (sd.LOSSLESS_CONVERSION, ()) and sd.inverter_conversion(object()) == (sd.LOSSLESS_CONVERSION, ()))

LO_F, HI_F = sd.INVERTER_FACTOR_BOUNDS
LO_S, HI_S = sd.INVERTER_STANDBY_BOUNDS_W
check("the bounds are the proposed ones: factors 0.85 to 1.0, standby 0 to 150 W", (LO_F, HI_F, LO_S, HI_S) == (0.85, 1.0, 0.0, 150.0))
at_bounds = [(LO_F, LO_F, LO_S), (HI_F, HI_F, HI_S), (LO_F, HI_F, HI_S), (HI_F, LO_F, LO_S)]
check("every value exactly at a bound is accepted (inclusive)",
      all(sd.inverter_conversion(replace(cf.FACTS, inverter_dc_to_ac_factor=a, inverter_ac_to_dc_factor=b, inverter_standby_w=c))
          == (sd.InverterConversion(a, b, c), ()) for a, b, c in at_bounds))
just_out = {"inverter_dc_to_ac_factor": (math.nextafter(LO_F, 0.0), math.nextafter(HI_F, 2.0)),
            "inverter_ac_to_dc_factor": (math.nextafter(LO_F, 0.0), math.nextafter(HI_F, 2.0)),
            "inverter_standby_w": (-1e-9, math.nextafter(HI_S, 1000.0))}
ok_all = {"inverter_dc_to_ac_factor": 0.9, "inverter_ac_to_dc_factor": 0.9, "inverter_standby_w": 40.0}
for name, outs in just_out.items():
    for v in outs:
        cv, pr = sd.inverter_conversion(replace(cf.FACTS, **{**ok_all, name: v}))
        check(f"{name} one step outside its bound is refused (out_of_bounds), lossless stays",
              cv.lossless and pr == (f"{name}:out_of_bounds",), str(pr))
bad_values = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf"), "a string": "0.9", "true": True, "false": False,
              "a list": [0.9], "negative": -0.9, "zero factor": 0.0, "huge": 1e9}
for label, v in bad_values.items():
    for name in sd.INVERTER_CONVERSION_FACTS:
        cv, pr = sd.inverter_conversion(replace(cf.FACTS, **{**ok_all, name: v}))
        reason = "out_of_bounds" if label in ("negative", "zero factor", "huge") and not (name == "inverter_standby_w" and v == 0.0) else "not_a_number"
        if name == "inverter_standby_w" and label in ("zero factor",):
            ok = cv == sd.InverterConversion(0.9, 0.9, 0.0) and pr == ()      # zero is a valid standby (the bound is inclusive)
        else:
            ok = cv.lossless and pr == (f"{name}:{reason}",)
        check(f"{name} = {label}: " + ("accepted" if (name == "inverter_standby_w" and label == "zero factor") else f"refused ({reason}), lossless stays"),
              ok, str(pr))
for keep in (("inverter_dc_to_ac_factor",), ("inverter_ac_to_dc_factor",), ("inverter_standby_w",),
             ("inverter_dc_to_ac_factor", "inverter_ac_to_dc_factor"), ("inverter_dc_to_ac_factor", "inverter_standby_w")):
    part = replace(cf.FACTS, **{n: ok_all[n] for n in keep})
    cv, pr = sd.inverter_conversion(part)
    want = tuple(f"{n}:missing" for n in sd.INVERTER_CONVERSION_FACTS if n not in keep)
    check(f"a partial set ({len(keep)} of 3) is refused as missing {len(want)}, lossless stays", cv.lossless and pr == want, str(pr))
check("a problem names the fact and the reason and never a value",
      all(":" in x and x.split(":")[0] in sd.INVERTER_CONVERSION_FACTS and x.split(":")[1] in ("missing", "not_a_number", "out_of_bounds")
          for x in sd.inverter_conversion(replace(cf.FACTS, inverter_dc_to_ac_factor=0.123456))[1]))
for args in ((0.84, 0.9, 40.0), (0.9, 1.01, 40.0), (0.9, 0.9, -1.0), (0.9, 0.9, 151.0), (float("nan"), 0.9, 40.0), (0.9, 0.9, True)):
    try:
        sd.InverterConversion(*args)
        refused = False
    except ValueError:
        refused = True
    check(f"InverterConversion{args} cannot be constructed", refused)
try:
    CONV.dc_to_ac = 1.0                                              # type: ignore[misc]
    frozen = False
except Exception:                                                    # noqa: BLE001 - FrozenInstanceError
    frozen = True
check("InverterConversion is frozen", frozen)

print("== [2] the default is today's behaviour")
LITERAL = [
    # (label, house, pv, battery, grid, today's verdict)
    ("balanced", 900.0, 300.0, 500.0, 100.0, None),
    ("the fixture's own set, residual exactly at the 100 W floor", 450.0, 0.0, 400.0, -50.0, None),
    ("residual just over the floor", 451.0, 0.0, 400.0, -50.0, "POWER_BALANCE_INCONSISTENT"),
    ("a discharge that loses a tenth", 2700.0, 0.0, 3000.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
    ("a high-power set exactly at 5 % of the largest magnitude", 3800.0, 4000.0, 0.0, 0.0, None),
    ("a high-power set just over 5 % of the largest magnitude", 3799.0, 4000.0, 0.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
    ("a grid reading too small to name a reversal (under half the tolerance)", 900.0, 300.0, 500.0, -40.0, "POWER_BALANCE_INCONSISTENT"),
    ("grid CT reversed, grid well above half the tolerance", 1800.0, 600.0, 400.0, -800.0, "CT_SIGN_REVERSED"),
    ("battery sign reversed", 900.0, 2400.0, 1500.0, 0.0, "BATTERY_SIGN_REVERSED"),
    ("fits neither way", 3000.0, 0.0, 0.0, 200.0, "POWER_BALANCE_INCONSISTENT"),
    ("both reversed", 3000.0, 1000.0, -1500.0, -500.0, "POWER_BALANCE_INCONSISTENT"),
]
for label, hw, p, b, g, want in LITERAL:
    got = q.power_balance_verdict(hw, p, b, g)[0]
    ref = old_rule(hw, p, b, g)[0]
    check(f"default rule, {label}: {want or 'consistent'}", got == want == ref, f"{got} / {ref}")
rng = random.Random(20261121)
diff = []
for i in range(30000):
    hw = rng.choice((0.0, 0.5, rng.uniform(-300, 400), rng.uniform(0, 12000)))
    p, b, g = rng.uniform(0, 9000), rng.uniform(-6000, 6000), rng.uniform(-6000, 6000)
    if i % 3 == 0:                                                   # sets that balance, so the reversals and edges are hit
        hw = max(0.0, round(p + b + g + rng.choice((0.0, 50.0, -50.0, 100.0, -100.0, 160.0, -400.0)), 1))
    if i % 7 == 0:
        hw = max(0.0, p + b - g + rng.choice((0.0, 30.0)))           # the CT-reversed fit
    if i % 11 == 0:
        hw = max(0.0, p - b + g + rng.choice((0.0, 30.0)))           # the battery-reversed fit
    if q.power_balance_verdict(hw, p, b, g) != old_rule(hw, p, b, g):
        diff.append((hw, p, b, g))
    if q.power_balance_verdict(hw, p, b, g, sd.InverterConversion(1.0, 1.0, 0.0)) != old_rule(hw, p, b, g):
        diff.append(("explicit lossless", hw, p, b, g))
check("30000 seeded sets: the default verdict, residual and tolerance are bit-identical to the rule before the facts existed "
      "(also with explicit lossless facts)", not diff, str(diff[:2]))

sweep_diff = []
rng2 = random.Random(7)
for i in range(300):
    p, b, g = round(rng2.uniform(0, 5000), 1), round(rng2.uniform(-3000, 3000), 1), round(rng2.uniform(-3000, 3000), 1)
    hw = round(max(0.0, p + b + g + rng2.choice((0.0, 80.0, -80.0, -250.0, 250.0))), 1) if i % 2 else round(rng2.uniform(0, 8000), 1)
    s = sig(hw, p, b, g)
    r_none = assess(base, s)
    r_explicit = assess(base, s, replace(cf.FACTS, inverter_dc_to_ac_factor=1.0, inverter_ac_to_dc_factor=1.0,
                                          inverter_standby_w=0.0))
    code = old_rule(hw, p, b, g)[0] if hw >= -0.5 else None
    got = balance_codes(r_none)
    flow = p + b + g
    zero_rule = abs(hw) <= 0.5 and flow > 150.0
    expect = set() if (code is None or zero_rule) else {code}
    if r_none.findings != r_explicit.findings or got != expect:
        sweep_diff.append((s, sorted(got), sorted(expect)))
check("300 sets through assess_inputs: no facts and explicit lossless facts give identical findings, and the balance codes "
      "are the old rule's", not sweep_diff, str(sweep_diff[:2]))
tab = assess(base, sig(2660.0, 0.0, 3000.0, 0.0))
check("a loss-affected discharge BLOCKs export and Dump by default, with the evidence unchanged (residual, tolerance only)",
      all("POWER_BALANCE_INCONSISTENT" in h.item_codes(tab, i) for i in EXPORT)
      and all(dict(f.evidence) == {"residual_w": -340.0, "tolerance_w": 150.0} for f in tab.findings
              if f.code == "POWER_BALANCE_INCONSISTENT"))

print("== [3] the loss-aware expectation")
CASES = [
    # (label, pv, battery, grid)
    ("discharge", 0.0, 3000.0, 0.0),
    ("discharge and import", 0.0, 2000.0, 500.0),
    ("PV-led with export", 4000.0, 0.0, -1500.0),
    ("PV and discharge", 3000.0, 2000.0, 0.0),
    ("PV charging the battery", 5000.0, -2000.0, -500.0),
    ("charging from the grid", 0.0, -2000.0, 2500.0),
    ("PV and grid charging", 500.0, -3000.0, 3000.0),
    ("idle", 0.0, 0.0, 300.0),
    ("idle, small grid", 0.0, 0.0, 100.0),
    ("net DC power exactly zero", 1000.0, -1000.0, 400.0),
    ("net DC power +1 W", 0.0, 1.0, 200.0),
    ("net DC power -1 W", 0.0, -1.0, 200.0),
    ("high power", 6000.0, 4000.0, 2000.0),
]
for label, p, b, g in CASES:
    hw = model_house(p, b, g)
    c_la = q.power_balance_verdict(hw, p, b, g, CONV)
    check(f"loss-aware, {label} (house {hw:g} W): consistent", c_la[0] is None, str(c_la))
big = [(label, p, b, g) for label, p, b, g in CASES if q.power_balance_verdict(model_house(p, b, g), p, b, g)[0] is not None]
check("... and the lossless default blocks the sets whose loss exceeds the tolerance (so the facts are what lets them pass)",
      len(big) >= 8 and {"discharge", "charging from the grid", "high power"} <= {x[0] for x in big}, str([x[0] for x in big]))
check("idle: the house power is the grid less the standby draw (60 W for 100 W of grid), consistent", model_house(0.0, 0.0, 100.0) == 60.0
      and q.power_balance_verdict(60.0, 0.0, 0.0, 100.0, CONV)[0] is None)
check("the expectation is continuous at zero net DC power and the two sides give the values written out",
      CONV.expected_house_w(1000.0, -1000.0, 0.0) == -STANDBY
      and abs(CONV.expected_house_w(0.0, 1e-9, 0.0) - CONV.expected_house_w(0.0, -1e-9, 0.0)) < 1e-6
      and abs(CONV.expected_house_w(0.0, 1000.0, 50.0) - (50.0 + 900.0 - 40.0)) < 1e-9
      and abs(CONV.expected_house_w(0.0, -920.0, 50.0) - (50.0 - 1000.0 - 40.0)) < 1e-9)
check("the lossless conversion returns exactly PV + battery + grid", sd.LOSSLESS_CONVERSION.expected_house_w(1.5, -0.25, 7.0) == 1.5 - 0.25 + 7.0)
# the tolerance: the same rule as today (floor 100 W, 5 % of the largest magnitude), applied to the loss-aware residual
exp_low = CONV.expected_house_w(0.0, 200.0, 0.0)                     # 140 W
check("the tolerance floor: a residual of exactly 100 W passes, one just over blocks (small flows)",
      q.power_balance_verdict(exp_low + 100.0, 0.0, 200.0, 0.0, CONV)[0] is None
      and q.power_balance_verdict(exp_low + 100.5, 0.0, 200.0, 0.0, CONV)[0] == "POWER_BALANCE_INCONSISTENT"
      and q.power_balance_verdict(exp_low - 100.0, 0.0, 200.0, 0.0, CONV)[0] is None
      and q.power_balance_verdict(exp_low - 100.5, 0.0, 200.0, 0.0, CONV)[0] == "POWER_BALANCE_INCONSISTENT")
exp_hi = CONV.expected_house_w(0.0, 4000.0, 0.0)                     # 3560 W; the largest magnitude is the battery, 4000 W
tol_hi = 0.05 * 4000.0
check("the tolerance fraction: at 4000 W the tolerance is 200 W, exact at the bound and blocked beyond it",
      q.power_balance_verdict(exp_hi + tol_hi, 0.0, 4000.0, 0.0, CONV) == (None, tol_hi, tol_hi)
      and q.power_balance_verdict(exp_hi + tol_hi + 1.0, 0.0, 4000.0, 0.0, CONV)[0] == "POWER_BALANCE_INCONSISTENT")
check("the verdict carries the engine's tolerance (PROPOSED floor and fraction)",
      q.power_balance_verdict(0.0, 0.0, 0.0, 0.0, CONV)[2] == max(sd.PROPOSED.power_agree_w, 0.0)
      and q.power_balance_verdict(5000.0, 0.0, 4000.0, 0.0, CONV)[2] == max(sd.PROPOSED.power_agree_w, sd.PROPOSED.power_agree_fraction * 5000.0))

for label, p, b, g in (("discharge", 0.0, 3000.0, 0.0), ("PV and grid charging", 500.0, -3000.0, 3000.0), ("idle", 0.0, 0.0, 300.0)):
    s = sig(model_house(p, b, g), p, b, g)
    la = assess(base, s, FACTS)
    lo = assess(base, s)
    check(f"assess_inputs, {label}: the facts remove the balance finding; without them it stays (when the loss exceeds the "
          "tolerance) and nothing else changes",
          not balance_codes(la) and "POWER_LOSS_FACTS_INVALID" not in h.codes(la)
          and {(f.code, f.subject) for f in la.findings} <= {(f.code, f.subject) for f in lo.findings}
          and ((not balance_codes(lo)) if label == "idle" else bool(balance_codes(lo))), str(balance_codes(lo)))
la_all = assess(base, sig(model_house(0.0, 3000.0, 0.0), 0.0, 3000.0, 0.0), FACTS)
check("... with the facts and a balanced set neither export nor Dump is blocked, and the data quality is the clean base's own",
      la_all.data_quality == q.assess_inputs(base).data_quality and not (set(EXPORT) & la_all.blocked_items)
      and not la_all.blocked_items, f"{la_all.data_quality} {sorted(la_all.blocked_items)}")
env_la = run_cycle(replace(faults.with_signals(base, sig(model_house(0.0, 3000.0, 0.0), 0.0, 3000.0, 0.0)), site_facts=FACTS))
env_lo = run_cycle(faults.with_signals(base, sig(model_house(0.0, 3000.0, 0.0), 0.0, 3000.0, 0.0)))
env_clean = run_cycle(base)


def export_view(env):
    return {it.key: it for it in env.items if it.key in EXPORT}


check("run_cycle: the same set BLOCKs export and Dump on the balance without the facts, and with them both are computed",
      all(v.status == "BLOCKED" and any(b[0] == "POWER_BALANCE_INCONSISTENT" for b in v.blockers) for v in export_view(env_lo).values())
      and all(v.status != "BLOCKED" and not v.blockers for v in export_view(env_la).values()),
      str({k: (v.status, v.blockers) for k, v in {**export_view(env_lo), **export_view(env_la)}.items()}))
check("... and the cycle's data quality is then the clean base's own (the facts add no finding; a WARN such as the charge "
      "window from the TOU table keeps a clean cycle DEGRADED too)", env_la.data_quality == env_clean.data_quality,
      f"{env_la.data_quality} / {env_clean.data_quality}")
ev = [dict(f.evidence) for f in assess(base, sig(model_house(0.0, 3000.0, 0.0) + 400.0, 0.0, 3000.0, 0.0), FACTS).findings
      if f.code == "POWER_BALANCE_INCONSISTENT"]
check("a real inconsistency under the loss-aware rule says so in its evidence (balance: loss_aware)",
      ev and all(e.get("balance") == "loss_aware" for e in ev), str(ev))

print("== [4] faults still block under the loss-aware rule")
ct_bad, bat_bad, both_bad, ct_wrong_code, bat_wrong_code = [], [], [], [], []
n_ct = n_bat = n_both = 0
for label, p, b, g in CASES:
    hw = model_house(p, b, g)
    tol = q.power_balance_verdict(hw, p, b, g, CONV)[2]
    if abs(g) > tol:                                                 # the reversal moves the expectation by 2 |g|
        n_ct += 1
        code = q.power_balance_verdict(hw, p, b, -g, CONV)[0]
        if code is None:
            ct_bad.append(label)
        elif code not in SIGN_CODES:
            ct_wrong_code.append((label, code))
    if abs(b) > tol:
        n_bat += 1
        code = q.power_balance_verdict(hw, p, -b, g, CONV)[0]
        if code is None:
            bat_bad.append(label)
        elif code not in SIGN_CODES:
            bat_wrong_code.append((label, code))
    shift = abs(CONV.expected_house_w(p, b, g) - CONV.expected_house_w(p, -b, -g))
    if shift > 2.0 * tol:                                            # both reversed moves the expectation by more than the band
        n_both += 1
        if q.power_balance_verdict(hw, p, -b, -g, CONV)[0] is None:
            both_bad.append(label)
check(f"the grid CT reversed is blocked, and named a sign fault, on every case where it matters ({n_ct})",
      n_ct >= 8 and not ct_bad and not ct_wrong_code, str((ct_bad, ct_wrong_code)))
check(f"the battery reversed is blocked, and named a sign fault, on every case where it matters ({n_bat})",
      n_bat >= 8 and not bat_bad and not bat_wrong_code, str((bat_bad, bat_wrong_code)))
check(f"both reversed is blocked wherever it moves the expectation by more than twice the tolerance ({n_both}; with the grid "
      "charging the battery the two reversals cancel and nothing can tell them)", n_both >= 6 and not both_bad, str(both_bad))
for label, p, b, g, want in (("CT reversed", 0.0, 3000.0, -2000.0, "CT_SIGN_REVERSED"), ("battery reversed", 4000.0, 2000.0, 0.0, "BATTERY_SIGN_REVERSED")):
    true_h = model_house(p, b, g)
    sx = sig(true_h, p, b, -g) if want == "CT_SIGN_REVERSED" else sig(true_h, p, -b, g)
    r = assess(base, sx, FACTS)
    check(f"assess_inputs with the facts, {label}: {want} on export and Dump, and charge_target is not blocked",
          all(want in h.item_codes(r, i) for i in EXPORT) and "charge_target" not in r.blocked_items
          and all(dict(f.evidence).get("balance") == "loss_aware" for f in r.findings if f.code == want))
r_both = assess(base, sig(model_house(0.0, 3000.0, -2000.0), 0.0, -3000.0, 2000.0), FACTS)
check("assess_inputs with the facts, both reversed: export and Dump BLOCKED",
      all(h.item_codes(r_both, i) & BALANCE_CODES for i in EXPORT), str(h.codes(r_both, "BLOCK")))
fz = assess(base, sig(0.0, 3000.0, 500.0, -1000.0), FACTS)
check("the native-load false zero is unchanged by the facts (house 0 while inverter and grid show a load)",
      all("LOAD_FALSE_ZERO" in h.item_codes(fz, i) for i in EXPORT) and not balance_codes(fz))
fz2 = assess(base, sig(0.0, 0.0, 2000.0, 0.0), FACTS)
check("... also where the loss-aware expectation is far from zero", all("LOAD_FALSE_ZERO" in h.item_codes(fz2, i) for i in EXPORT))
nh = assess(base, sig(-300.0, 0.0, 400.0, -50.0), FACTS)
check("the negative house load is unchanged by the facts: HOUSE_POWER_NEGATIVE on export and Dump, no balance finding",
      all("HOUSE_POWER_NEGATIVE" in h.item_codes(nh, i) for i in EXPORT) and not balance_codes(nh))
nz = assess(base, sig(0.0, 0.0, 60.0, 0.0), FACTS)
check("a true zero load that inverter and grid confirm (below the HD1 threshold) is still not a false zero",
      "LOAD_FALSE_ZERO" not in h.codes(nz))

print("== [5] invalid facts are reported and never loosen the check")
loss_set = sig(model_house(0.0, 3000.0, 0.0), 0.0, 3000.0, 0.0)           # consistent only with the loss-aware rule
bad_facts = {
    "a partial set": replace(cf.FACTS, inverter_dc_to_ac_factor=DC_AC),
    "a factor above 1": replace(FACTS, inverter_dc_to_ac_factor=1.05),
    "a factor below the bound": replace(FACTS, inverter_ac_to_dc_factor=0.5),
    "a standby above the bound": replace(FACTS, inverter_standby_w=500.0),
    "a negative standby": replace(FACTS, inverter_standby_w=-5.0),
    "NaN": replace(FACTS, inverter_dc_to_ac_factor=float("nan")),
    "infinity": replace(FACTS, inverter_standby_w=float("inf")),
    "a string": replace(FACTS, inverter_ac_to_dc_factor="0.92"),
    "a bool": replace(FACTS, inverter_standby_w=True),
}
for label, fx in bad_facts.items():
    r = assess(base, loss_set, fx)
    rows = [f for f in r.findings if f.code == "POWER_LOSS_FACTS_INVALID"]
    ev = [dict(f.evidence) for f in rows]
    leaks = h.text_leaks(r)
    check(f"{label}: POWER_LOSS_FACTS_INVALID BLOCKs export and Dump, the evidence names facts and reasons only",
          sorted(f.subject for f in rows) == sorted(EXPORT) and all(f.severity == "BLOCK" for f in rows)
          and all(set(e) == {"problems"} and e["problems"] and all(x.split(":")[0] in sd.INVERTER_CONVERSION_FACTS for x in e["problems"]) for e in ev)
          and not leaks, str((ev, leaks)))
    check(f"{label}: the check stays lossless (the loss-affected set is still POWER_BALANCE_INCONSISTENT, not loosened), "
          "charge_target is not blocked by it",
          all("POWER_BALANCE_INCONSISTENT" in h.item_codes(r, i) for i in EXPORT) and "charge_target" not in r.blocked_items)
    check(f"{label}: the cycle's data quality is not OK", r.data_quality != "OK")
r_ok_set = assess(base, sig(900.0, 300.0, 500.0, 100.0), bad_facts["a partial set"])
check("invalid facts BLOCK even where the lossless balance holds (the misconfiguration is never silent)",
      all("POWER_LOSS_FACTS_INVALID" in h.item_codes(r_ok_set, i) for i in EXPORT) and not balance_codes(r_ok_set))
r_neg = assess(base, sig(-300.0, 0.0, 400.0, -50.0), bad_facts["NaN"])
check("... and they do not hide the other power rules (a negative house load is still reported alongside)",
      all({"POWER_LOSS_FACTS_INVALID", "HOUSE_POWER_NEGATIVE"} <= h.item_codes(r_neg, i) for i in EXPORT))
check("valid facts raise no POWER_LOSS_FACTS_INVALID; absent facts raise none either",
      "POWER_LOSS_FACTS_INVALID" not in h.codes(assess(base, loss_set, FACTS)) and "POWER_LOSS_FACTS_INVALID" not in h.codes(assess(base, loss_set)))
check("POWER_LOSS_FACTS_INVALID is a declared rule judging the structure, not a live input (so a poll cannot lift it)",
      q.RULE_INPUTS["POWER_LOSS_FACTS_INVALID"] == ("<structure>",))
mal = q.assess_inputs(replace(faults.with_signals(base, loss_set), site_facts="not a SiteFacts"))
check("a site_facts that is not a SiteFacts is read as absent by this rule (never raises), though the zone is then unknown",
      isinstance(mal, q.QualityResult))

print("== [6] a wrong (too generous) conversion cannot hide a sign reversal at the tested powers")
TESTED = [(0.0, 3000.0, 1500.0), (0.0, 3000.0, -2000.0), (0.0, -2000.0, 2500.0), (4000.0, 0.0, 1500.0), (4000.0, 0.0, -1500.0),
          (5000.0, -2000.0, 1000.0), (0.0, 1000.0, 800.0), (0.0, -1000.0, 1200.0), (2000.0, 2000.0, 1200.0), (3000.0, 0.0, 1000.0)]
generous = [sd.InverterConversion(LO_F, LO_F, HI_S), sd.InverterConversion(LO_F, HI_F, 100.0), sd.InverterConversion(0.88, 0.88, 100.0),
            sd.InverterConversion(DC_AC - 0.02, AC_DC - 0.02, STANDBY + 20.0), CONV]
hidden, tested = [], 0
for pv, b, g in TESTED:
    hw = model_house(pv, b, g)
    for rule in generous:
        for fault in ("ct", "batt"):
            gg, bb = (-g, b) if fault == "ct" else (g, -b)
            tol = q.power_balance_verdict(hw, pv, bb, gg, rule)[2]
            if abs(g if fault == "ct" else b) < tol:
                continue
            tested += 1
            if q.power_balance_verdict(hw, pv, bb, gg, rule)[0] is None:
                hidden.append((pv, b, g, fault, rule))
check(f"{tested} tested reversals (10 power sets x 5 rules, from the lowest bounds to the model): every one is blocked", tested >= 60 and not hidden,
      str(hidden[:2]))
margin_hidden, margin_tested = [], 0
rng3 = random.Random(99)
for _ in range(6000):
    pv = rng3.choice((0.0, rng3.uniform(0, 7000)))
    b = rng3.uniform(-4000, 4000)
    g = rng3.uniform(-4000, 4000)
    hw = model_house(pv, b, g)
    if hw < 1.0:
        continue
    rule = sd.InverterConversion(rng3.uniform(LO_F, HI_F), rng3.uniform(LO_F, HI_F), rng3.uniform(LO_S, HI_S))
    for fault in ("ct", "batt"):
        gg, bb = (-g, b) if fault == "ct" else (g, -b)
        _c, _r, tol = q.power_balance_verdict(hw, pv, bb, gg, rule)
        x = abs(g if fault == "ct" else b)
        if x < tol:
            continue
        err = abs(rule.expected_house_w(pv, b, g) - hw)               # how wrong the rule's expectation is at the true set
        if err >= tol / 2.0:
            continue
        margin_tested += 1
        if q.power_balance_verdict(hw, pv, bb, gg, rule)[0] is None:
            margin_hidden.append((pv, b, g, fault))
check(f"{margin_tested} random reversals (>= the tolerance) judged by a rule whose expectation is wrong by less than half the "
      "tolerance: none is hidden (the guarantee in DATA_QUALITY_METHOD.md)", margin_tested > 500 and not margin_hidden, str(margin_hidden[:2]))

print("== [7] mutants of the rule are told apart by this suite's case table")
TOL_FLOOR, TOL_FRAC = sd.PROPOSED.power_agree_w, sd.PROPOSED.power_agree_fraction


def make_verdict(expect, floor=TOL_FLOOR, frac=TOL_FRAC, ct_flip=True, batt_flip=True, guard=0.5):
    """A copy of power_balance_verdict with `expect(p, b, g)` as the expectation and optional deliberate defects."""
    def verdict(hw, p, b, g, _conv=None):
        tol = max(floor, frac * max(abs(hw), abs(p), abs(b), abs(g)))
        resid = hw - expect(p, b, g)
        if abs(resid) <= tol:
            return None, resid, tol
        if abs(hw - expect(p, b, -g if ct_flip else g)) <= tol and abs(g) > tol * guard:
            return "CT_SIGN_REVERSED", resid, tol
        if abs(hw - expect(p, -b if batt_flip else b, g)) <= tol and abs(b) > tol * guard:
            return "BATTERY_SIGN_REVERSED", resid, tol
        return "POWER_BALANCE_INCONSISTENT", resid, tol
    return verdict


def good(p, b, g):
    return CONV.expected_house_w(p, b, g)


def lossless(p, b, g):
    return p + b + g


def swap_factors(p, b, g):
    d = p + b
    return g + (AC_DC * d if d >= 0 else d / DC_AC) - STANDBY


def standby_added(p, b, g):
    d = p + b
    return g + (DC_AC * d if d >= 0 else d / AC_DC) + STANDBY


def standby_dropped(p, b, g):
    d = p + b
    return g + (DC_AC * d if d >= 0 else d / AC_DC)


def charge_multiplied(p, b, g):
    d = p + b
    return g + (DC_AC * d if d >= 0 else d * AC_DC) - STANDBY


def charge_unconverted(p, b, g):
    d = p + b
    return g + (DC_AC * d if d >= 0 else d) - STANDBY


def discharge_unconverted(p, b, g):
    d = p + b
    return g + (d if d >= 0 else d / AC_DC) - STANDBY


def battery_only(p, b, g):
    return g + (DC_AC * b if b >= 0 else b / AC_DC) - STANDBY            # PV left out of the DC-side net


def loss_on_grid(p, b, g):
    d = p + b
    return DC_AC * (g + d) - STANDBY


def sign_flipped_side(p, b, g):
    d = p + b
    return g + (DC_AC * d if d <= 0 else d / AC_DC) - STANDBY


def case_rows():
    rows = []
    for label, p, b, g in CASES:
        rows.append((label, model_house(p, b, g), p, b, g, None))
        tol = q.power_balance_verdict(model_house(p, b, g), p, b, g, CONV)[2]
        # the expected code of a reversal row is the reversal's own; a row is kept only where the other reversal's fit does not
        # also hold by coincidence (the rule tests the grid first), so no expectation is read from the rule's own answer
        hw = model_house(p, b, g)
        if abs(g) > tol and abs(hw - CONV.expected_house_w(p, -b, -g)) > tol:
            rows.append((label + ", CT reversed", hw, p, b, -g, "CT_SIGN_REVERSED"))
        if abs(b) > tol and abs(hw - CONV.expected_house_w(p, -b, -g)) > tol:
            rows.append((label + ", battery reversed", hw, p, -b, g, "BATTERY_SIGN_REVERSED"))
    rows += [("a real inconsistency", model_house(0.0, 3000.0, 0.0) + 500.0, 0.0, 3000.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
             ("just inside the floor", CONV.expected_house_w(0.0, 200.0, 0.0) + 100.0, 0.0, 200.0, 0.0, None),
             ("just outside the floor", CONV.expected_house_w(0.0, 200.0, 0.0) + 100.5, 0.0, 200.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
             ("just inside 5 %", CONV.expected_house_w(0.0, 4000.0, 0.0) + 200.0, 0.0, 4000.0, 0.0, None),
             ("just outside 5 %", CONV.expected_house_w(0.0, 4000.0, 0.0) + 201.0, 0.0, 4000.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
             # the reversal guard (a reversed reading counts only above half the tolerance, here the 100 W floor): a reading of
             # 48 W cannot name a reversal even though the reversed fit holds (house 50 W under the reversed expectation), a
             # reading of 80 W can
             ("grid 48 W: the reversed fit holds but the reading is under half the tolerance", CONV.expected_house_w(0.0, 1500.0, -48.0) - 50.0,
              0.0, 1500.0, 48.0, "POWER_BALANCE_INCONSISTENT"),
             ("grid 80 W, CT reversed: above half the tolerance", CONV.expected_house_w(0.0, 1500.0, -80.0), 0.0, 1500.0, 80.0,
              "CT_SIGN_REVERSED"),
             ("battery 48 W: the reversed fit holds but the reading is under half the tolerance",
              CONV.expected_house_w(1500.0, -48.0, 0.0) - 50.0, 1500.0, 48.0, 0.0, "POWER_BALANCE_INCONSISTENT"),
             ("battery 80 W, battery reversed: above half the tolerance", CONV.expected_house_w(1500.0, -80.0, 0.0), 1500.0, 80.0, 0.0,
              "BATTERY_SIGN_REVERSED")]
    return rows


ROWS = case_rows()


def killed_by_table(verdict) -> bool:
    """True when the table has a case on which the variant's verdict (code) differs from the expected one."""
    for _label, hw, p, b, g, want in ROWS:
        if verdict(hw, p, b, g)[0] != want:
            return True
    return False


check("the table agrees with the real rule on every row (it is a table of its verdicts)",
      all(q.power_balance_verdict(hw, p, b, g, CONV)[0] == want for _l, hw, p, b, g, want in ROWS),
      str([(l, q.power_balance_verdict(hw, p, b, g, CONV)[0], want) for l, hw, p, b, g, want in ROWS
           if q.power_balance_verdict(hw, p, b, g, CONV)[0] != want][:3]))
check(f"... and an identical re-implementation is not killed ({len(ROWS)} rows)", not killed_by_table(make_verdict(good)))
MUTANTS = {
    "lossless expectation": make_verdict(lossless), "factors swapped": make_verdict(swap_factors),
    "standby added instead of subtracted": make_verdict(standby_added), "standby dropped": make_verdict(standby_dropped),
    "charge side multiplied instead of divided": make_verdict(charge_multiplied),
    "charge side unconverted": make_verdict(charge_unconverted), "discharge side unconverted": make_verdict(discharge_unconverted),
    "battery only in the DC-side net": make_verdict(battery_only), "loss applied to the grid": make_verdict(loss_on_grid),
    "sides exchanged": make_verdict(sign_flipped_side),
    "CT test without the flip": make_verdict(good, ct_flip=False), "battery test without the flip": make_verdict(good, batt_flip=False),
    "CT and battery tests lossless": None,
    "tolerance floor halved": make_verdict(good, floor=TOL_FLOOR / 2.0), "tolerance floor doubled": make_verdict(good, floor=TOL_FLOOR * 2.0),
    "tolerance fraction doubled": make_verdict(good, frac=TOL_FRAC * 2.0), "tolerance fraction halved": make_verdict(good, frac=TOL_FRAC / 2.0),
    "reversal guard dropped": make_verdict(good, guard=0.0), "reversal guard doubled": make_verdict(good, guard=1.0),
}


def mixed(hw, p, b, g, _conv=None):
    """The reversal tests judged lossless while the balance is loss-aware (a half-applied conversion)."""
    tol = max(TOL_FLOOR, TOL_FRAC * max(abs(hw), abs(p), abs(b), abs(g)))
    resid = hw - good(p, b, g)
    if abs(resid) <= tol:
        return None, resid, tol
    if abs(hw - (p + b - g)) <= tol and abs(g) > tol / 2.0:
        return "CT_SIGN_REVERSED", resid, tol
    if abs(hw - (p - b + g)) <= tol and abs(b) > tol / 2.0:
        return "BATTERY_SIGN_REVERSED", resid, tol
    return "POWER_BALANCE_INCONSISTENT", resid, tol


MUTANTS["CT and battery tests lossless"] = mixed
alive = [name for name, v in MUTANTS.items() if not killed_by_table(v)]
check(f"every one of the {len(MUTANTS)} mutants is killed by the case table", not alive, str(alive))
# the table is not a tautology of one mutant class: the equivalent change (d >= 0 versus d > 0) is the only one that cannot differ
equiv = make_verdict(lambda p, b, g: g + (DC_AC * (p + b) if (p + b) > 0 else (p + b) / AC_DC) - STANDBY)
check("the one equivalent mutant (d > 0 instead of d >= 0: both sides are equal at d = 0) is correctly NOT killed",
      not killed_by_table(equiv))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all power-balance checks passed")
