#!/usr/bin/env python3
"""Intelligence value ledger (intelligence/net_value.py) on SYNTHETIC slots (fictional year 2030), pinned by hand calculation:

  [1] energy balance per slot (derive, residual, unbalanced series reported / refused when strict)
  [2] sign conventions (every line is a positive magnitude; the net is the formula; the bill is import minus export)
  [3] solar that could be exported costs the export price; solar that could not (not permitted, limit, curtailment, negative
      price) costs nothing
  [4] losses in kWh and pence
  [5] the well-mixed composition: discharge is valued by the real mix; the closing composition is reported
  [6] unknown wear is never silently the full net; known wear uses the throughput
  [7] opening stock and unattributed discharge are flagged; per-day split; reproducibility; no write path
"""

from __future__ import annotations

import ast
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence.config import SiteConfig  # noqa: E402
from intelligence.net_value import (SRC_GRID, SRC_SOLAR_N, SRC_SOLAR_X, Slot, Tariff, by_day, value_run)  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def near(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


UTC = timezone.utc
T0 = datetime(2030, 3, 4, 0, 0, tzinfo=UTC)
CFG = SiteConfig(round_trip_efficiency=0.81, battery_capacity_kwh=10.0)     # one-way efficiency exactly 0.9
ETA = 0.9


def S(i: int, pv=0.0, load=0.0, chg=0.0, dis=0.0, curtailed=0.0, hours=1.0) -> Slot:
    return Slot.derive(T0 + timedelta(hours=i * hours), hours, pv, load, chg, dis, curtailed)


def tar(n, imp=30.0, exp=10.0, ok=True, limit=None) -> Tariff:
    return Tariff.make(n, imp, exp, ok, limit)


print("== [1] energy balance")
sl = S(0, pv=4, load=1, chg=3)
check("derive: surplus fully stored -> no import, no export", sl.imp == 0 and sl.exp == 0 and near(sl.residual, 0))
sl = S(0, pv=1, load=2, dis=0.5)
check("derive: a deficit is imported", near(sl.imp, 0.5) and sl.exp == 0 and near(sl.residual, 0))
sl = S(0, pv=5, load=1, chg=1)
check("derive: a surplus beyond the battery is exported", near(sl.exp, 3.0) and sl.imp == 0 and near(sl.residual, 0))
sl = S(0, pv=5, load=1, chg=1, curtailed=1.0)
check("derive: curtailment is part of the balance", near(sl.exp, 2.0) and near(sl.residual, 0))
slots = [S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2), S(2, pv=1, load=3, dis=1)]
res = value_run(slots, tar(3), CFG)
check("every slot balances (max residual 0)", res.max_abs_residual_kwh < 1e-9 and res.unbalanced_slots == 0)
broken = [Slot(T0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.5)]            # 0.5 kWh of discharge appears from nowhere
check("an unbalanced slot is reported, not hidden", value_run(broken, tar(1), CFG).unbalanced_slots == 1
      and any("UNBALANCED" in f for f in value_run(broken, tar(1), CFG).total.flags))
try:
    value_run(broken, tar(1), CFG, strict=True)
    check("strict refuses an unbalanced slot", False)
except ValueError:
    check("strict refuses an unbalanced slot", True)
for bad in (lambda: Slot(T0, 1.0, -1.0, 0, 0, 0, 0, 0), lambda: Slot(T0, 1.0, float("nan"), 0, 0, 0, 0, 0),
            lambda: Slot(datetime(2030, 1, 1), 1.0, 0, 0, 0, 0, 0, 0), lambda: Tariff.make(2, [1.0], 1.0),
            lambda: value_run(slots, tar(2), CFG), lambda: value_run(slots, tar(3), CFG, wear_p_per_kwh=-1.0)):
    try:
        bad()
        check("malformed input is refused", False)
    except ValueError:
        check("malformed input is refused", True)

print("== [3,4] the hand-calculated day: 3 kWh of exportable solar stored (10 p export), 2 kWh served at night (30 p import)")
slots = [S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2)]
r = value_run(slots, tar(2), CFG)
t = r.total
check("exportable stored solar is tagged exportable", near(t.solar_stored_exportable_kwh, 3.0) and t.solar_stored_not_exportable_kwh == 0)
check("gross avoided import = 2 kWh x 30 p = 60 p", near(t.gross_avoided_import_p, 60.0))
check("solar opportunity cost = 2 kWh x 10 p = 20 p (face, no loss)", near(t.solar_opportunity_cost_p, 20.0))
drawn_cost = 10.0 * (2.0 / ETA) / ETA                                 # price / eta per stored kWh x stored kWh drawn
check("losses in pence = cost of what was drawn minus the face value", near(t.losses_p, drawn_cost - 20.0, 1e-6), str(t.losses_p))
check("losses in kWh = 0.3 on charge + (2/0.9 - 2) on discharge", near(t.losses_kwh, 0.3 + (2 / ETA - 2)), str(t.losses_kwh))
check("net before wear = 60 - 20 - losses", near(t.net_before_wear_p, 60.0 - drawn_cost, 1e-6))
check("the stored energy left is 2.7 - 2/0.9 kWh", near(t.closing_stored_kwh, 2.7 - 2 / ETA))
check("closing composition says it is all exportable solar", set(t.closing_composition) == {SRC_SOLAR_X}
      and near(t.closing_composition[SRC_SOLAR_X]["share"], 1.0))

r = value_run(slots, tar(2, ok=[False, True]), CFG)
t = r.total
check("export not permitted: the stored solar costs nothing", t.solar_opportunity_cost_p == 0 and t.losses_p == 0
      and near(t.net_before_wear_p, 60.0) and near(t.solar_stored_not_exportable_kwh, 3.0))
r = value_run(slots, tar(2, limit=1.0), CFG)
t = r.total
check("export limit 1 kW: only 1 of the 3 kWh could have been exported", near(t.solar_stored_exportable_kwh, 1.0)
      and near(t.solar_stored_not_exportable_kwh, 2.0) and near(t.solar_opportunity_cost_p, 2.0 * 10.0 / 3.0))
slots_x = [S(0, pv=5, load=1, chg=2), S(1, load=2, dis=2)]            # 2 kWh already exported in slot 0 (5-1-2)
r = value_run(slots_x, tar(2, limit=2.0), CFG)
check("headroom is the limit minus what was exported: none left, so none of the stored solar was exportable",
      r.total.solar_stored_exportable_kwh == 0.0 and near(r.total.solar_stored_not_exportable_kwh, 2.0))
r = value_run(slots_x, tar(2, limit=3.0), CFG)
check("with 1 kWh of headroom left, 1 of the 2 kWh was exportable", near(r.total.solar_stored_exportable_kwh, 1.0))
r = value_run([S(0, pv=4, load=1, chg=3, curtailed=0.0), S(1, load=2, dis=2)], tar(2), CFG)
slots_c = [S(0, pv=6, load=1, chg=3, curtailed=2.0), S(1, load=2, dis=2)]
r = value_run(slots_c, tar(2), CFG)
check("a curtailed slot: nothing stored could have been exported", r.total.solar_stored_exportable_kwh == 0.0
      and near(r.total.solar_stored_not_exportable_kwh, 3.0))
r = value_run(slots, tar(2, exp=-5.0), CFG)
check("a negative export price never makes stored solar a gain", r.total.solar_opportunity_cost_p == 0.0)
r = value_run([S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2)], tar(2, exp=0.0), CFG)
check("export at 0 p: solar really is free", r.total.solar_opportunity_cost_p == 0.0 and near(r.total.gross_avoided_import_p, 60.0))
r = value_run([S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2)], tar(2, exp=30.0), CFG)
check("solar worth the full export tariff is not free: the stored kWh earns nothing net (it is a loss after losses)",
      r.total.net_before_wear_p < 0 and near(r.total.gross_avoided_import_p, 60.0))

print("== [2] sign conventions")
slots = [S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2), S(2, pv=0, load=1, chg=0.5, dis=0), S(3, pv=0, load=1, dis=0.5)]
tt = Tariff.make(4, [30.0, 30.0, 7.0, 30.0], [10.0] * 4)
t = value_run(slots, tt, CFG).total
parts = (t.gross_avoided_import_p, t.export_revenue_battery_p, t.grid_energy_cost_p, t.solar_opportunity_cost_p,
         t.opening_stock_cost_p, t.losses_p, t.throughput_kwh)
check("every ledger line is a non-negative magnitude", all(p >= -1e-12 for p in parts), str(parts))
check("net before wear = avoided + export - grid - solar - opening - losses",
      near(t.net_before_wear_p, t.gross_avoided_import_p + t.export_revenue_battery_p - t.grid_energy_cost_p
           - t.solar_opportunity_cost_p - t.opening_stock_cost_p - t.losses_p))
check("the bill is import cost minus export income (import positive)", near(t.bill_p, 1.5 * 7.0 + 0.5 * 30.0), str(t.bill_p))
exp_slot = [S(0, pv=3, load=1)]                                      # 2 kWh exported at 10 p, nothing else
check("export income makes the bill negative", near(value_run(exp_slot, tar(1), CFG).total.bill_p, -20.0))

print("== [5] the well-mixed tank: 2 kWh grid-charged at 8 p, 3 kWh exportable solar at 10 p, then a mixed discharge")
slots = [S(0, load=0.5, chg=2.0), S(1, pv=4, load=1, chg=3)]            # slot 0 imports 2.5, slot 1 stores solar
slots.append(S(2, load=0.81, dis=0.81))                               # draws 0.9 stored kWh: 1/5 of the 4.5 stored
t = value_run(slots, Tariff.make(3, [8.0, 8.0, 30.0], [10.0] * 3), CFG)
tot = t.total
comp = tot.closing_composition
check("closing composition after the mixed draw: 40 % grid / 60 % solar", near(comp[SRC_GRID]["share"], 0.4)
      and near(comp[SRC_SOLAR_X]["share"], 0.6), str(comp))
check("closing stock = 4.5 - 0.9 kWh", near(tot.closing_stored_kwh, 3.6) and near(comp[SRC_GRID]["kwh"], 1.44))
check("the discharge is costed at the real mix: grid face 0.81 x 0.4 x 8, solar face 0.81 x 0.6 x 10",
      near(tot.grid_energy_cost_p, 0.81 * 0.4 * 8.0) and near(tot.solar_opportunity_cost_p, 0.81 * 0.6 * 10.0), str(tot.to_dict()))
check("grid energy charged in total is priced separately from what was realised", near(tot.grid_charged_total_p, 2.0 * 8.0))
check("cost basis of the closing stock follows the mix", near(comp[SRC_GRID]["cost_p"], 16.0 * 0.8) and near(comp[SRC_SOLAR_X]["cost_p"], 30.0 * 0.8))
mixed = value_run(slots, Tariff.make(3, [8.0, 8.0, 30.0], [10.0] * 3), CFG).total
grid_only = value_run([S(0, load=0.5, chg=2.0), S(2, load=0.81, dis=0.81)], Tariff.make(2, [8.0, 30.0], [10.0] * 2), CFG).total
check("a discharge of pure grid energy is costed at the grid price alone", near(grid_only.solar_opportunity_cost_p, 0.0)
      and near(grid_only.grid_energy_cost_p, 0.81 * 8.0))
check("a unit of solar is not priced as grid energy and vice versa (mix changes the cost)",
      mixed.net_before_wear_p != grid_only.net_before_wear_p)

print("== [6] wear")
slots = [S(0, pv=4, load=1, chg=3), S(1, load=2, dis=2)]
t = value_run(slots, tar(2), CFG).total
check("unknown wear: no net benefit is reported", t.net_benefit_p is None and t.wear_p is None and not t.wear_known)
check("unknown wear: the headline is the net BEFORE wear and says so", near(t.headline_p, t.net_before_wear_p)
      and "before_wear" in t.headline_basis and any(f.startswith("WEAR_UNKNOWN") for f in t.flags))
check("unknown wear stays unknown in the dict form", t.to_dict()["net_benefit_p"] is None)
tw = value_run(slots, tar(2), CFG, wear_p_per_kwh=2.0).total
thr = (3 * ETA + 2 / ETA) / 2
check("throughput = mean of stored energy in and out", near(tw.throughput_kwh, thr))
check("known wear: net = net before wear - wear price x throughput", near(tw.wear_p, 2.0 * thr)
      and near(tw.net_benefit_p, tw.net_before_wear_p - 2.0 * thr) and near(tw.headline_p, tw.net_benefit_p)
      and tw.headline_basis == "net_after_wear")
check("zero wear is known, not unknown", value_run(slots, tar(2), CFG, wear_p_per_kwh=0.0).total.net_benefit_p is not None)

print("== [7] opening stock, unattributed discharge, days, reproducibility")
night = [S(0, load=2, dis=2)]
t = value_run(night, tar(1), CFG).total
check("a discharge with an empty tank is flagged unattributed at cost 0", any("UNATTRIBUTED" in f for f in t.flags)
      and near(t.net_before_wear_p, 60.0) and near(t.closing_stored_kwh, 0.0))
t = value_run(night, tar(1), CFG, opening_stored_kwh=5.0).total
check("opening stock with no stated price is flagged and costs 0", any("OPENING_STOCK_UNPRICED" in f for f in t.flags)
      and near(t.net_before_wear_p, 60.0))
t = value_run(night, tar(1), CFG, opening_stored_kwh=5.0, opening_cost_p_per_kwh=6.0).total
check("a stated opening price is charged, with its losses", near(t.opening_stock_cost_p, 12.0)
      and near(t.net_before_wear_p, 60.0 - 12.0 - (2 / ETA * 6.0 / ETA - 12.0)) and near(t.closing_stored_kwh, 5 - 2 / ETA)
      and "opening" in t.closing_composition)
two_days = [S(i, hours=1.0, load=0.2) for i in range(48)]
two_days[2] = S(2, load=2.0, chg=2.0)                                 # grid charge on day 1 ...
two_days[30] = S(30, load=2.0, dis=1.5)                               # ... used on day 2 (06:00)
r = value_run(two_days, tar(48), CFG)
days = by_day(r, "UTC")
check("two local days", len(days) == 2 and all(d.slots == 24 for d in days.values()))
d1, d2 = list(days.values())
check("the tank runs across midnight: day 2 discharges what day 1 charged", d1.discharge_kwh == 0 and near(d2.discharge_kwh, 1.5)
      and d2.grid_energy_cost_p > 0 and d1.grid_energy_cost_p == 0 and d1.grid_charged_total_p > 0)
check("day sums equal the total", near(d1.net_before_wear_p + d2.net_before_wear_p, r.total.net_before_wear_p)
      and near(d1.gross_avoided_import_p + d2.gross_avoided_import_p, r.total.gross_avoided_import_p))
check("a day's closing composition is the tank at its end", near(d1.closing_stored_kwh, 2 * ETA) and near(d2.closing_stored_kwh, 2 * ETA - 1.5 / ETA))
a = value_run(slots, tar(2), CFG, wear_p_per_kwh=1.0).total.to_dict()
b = value_run(slots, tar(2), CFG, wear_p_per_kwh=1.0).total.to_dict()
check("reproducible: the same input gives the same output", a == b)
half = [Slot.derive(T0 + timedelta(minutes=30 * i), 0.5, 0.5, 0.25, 0.0, 0.0) for i in range(4)]
check("any fixed step works (half hours)", near(value_run(half, tar(4), CFG).total.export_kwh, 1.0))

t = value_run(night, tar(1), CFG).total
check("unattributed energy: the net excluding it is 0 (the whole discharge was unattributed), the headline basis says it is included",
      near(t.net_before_wear_excl_unattributed_p, 0.0) and near(t.unattributed_value_p, 60.0) and "INCLUDES unattributed" in t.headline_basis)
t = value_run([S(0, load=2, dis=2)], tar(1), CFG, opening_stored_kwh=1.0, opening_cost_p_per_kwh=0.0).total
check("a partly unattributed discharge removes only its share of the income", near(t.unattributed_value_p, 60.0 * (1 - 1.0 / (2 / ETA))) and
      0 < t.net_before_wear_excl_unattributed_p < t.net_before_wear_p)
check("nothing unattributed: both nets agree and the basis is plain", near(value_run(slots, tar(2), CFG).total.net_before_wear_excl_unattributed_p,
      value_run(slots, tar(2), CFG).total.net_before_wear_p) and "INCLUDES" not in value_run(slots, tar(2), CFG).total.headline_basis)

print("== no write path (static)")
pkg = ROOT / "intelligence"
bad_imports = {"socket", "requests", "urllib", "http", "ftplib", "smtplib", "asyncio", "aiohttp", "serial", "pymodbus", "paho",
               "ssl", "ctypes", "importlib", "multiprocessing", "webbrowser", "telnetlib", "xmlrpc", "subprocess", "os", "pty", "shutil"}
vocab = ("write_register", "modbus", "esphome.", "supervisor_token", "api/services", "call_service", "mqtt")
viol = []
for path in (pkg / "net_value.py", pkg / "ghost.py", pkg / "tools" / "ghost_report.py"):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        mods = [a.name.split(".")[0] for a in node.names] if isinstance(node, ast.Import) else (
            [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module and node.level == 0 else [])
        viol += [(path.name, m) for m in mods if m in bad_imports]
        if isinstance(node, ast.Call):
            nm = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if nm in ("system", "popen", "Popen", "exec", "eval", "__import__", "spawn", "open", "write_text", "write_bytes"):
                viol.append((path.name, "call", nm))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 200:
            viol += [(path.name, "word", v) for v in vocab if v in node.value.lower()]
check("net_value.py, ghost.py and ghost_report.py import nothing networked/process-like, write nothing, hold no control vocabulary",
      not viol, str(viol))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence value:")
    for _n in FAILURES:
        print(f"  - {_n}")
    sys.exit(1)
print("All intelligence value checks PASSED.")
