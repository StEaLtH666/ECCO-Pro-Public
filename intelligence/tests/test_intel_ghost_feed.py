#!/usr/bin/env python3
"""The Ghost's feed from the integration's own data (intelligence/ghost_feed.py) on a SYNTHETIC house (fictional year 2030):

  [1] no advice: the model baseline is 0 and every delta is 0 (the ghost IS reality), with money from a verified tariff
  [2] matching advice: the ghost does what the real battery did, advice followed, no difference
  [3] a losing day: advice to charge at the one expensive night loses that day, is listed and flagged
  [4] no verified tariff (or one that covers too little): no pence figure anywhere, behaviour comparison only
  [5] the summary: simulation label, JSON-safe, size bound (and the oldest days dropped when it is exceeded), determinism,
      ready_for_assisted_evidence and the uncertainty block (stock rules, model baseline, efficiency +/- 3 points)
  [6] data: a gap picks the longest run; too little history is INSUFFICIENT_HISTORY; hourly slot matching of advice windows
  [7] the durable advice log round-trips through Scorecard.record_advice / advice_records into the feed
  [7c] per-slot log rows of the same advice are one advice followed (review finding G5); a later BLOCKED row withdraws (G6)
  [8] no write path (static)
The "actual" house is generated here by an independent simple rule set, not by ghost.py.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from intelligence import ghost_feed as gf  # noqa: E402
from intelligence import synthetic  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import F_STALLED, History, HourRecord  # noqa: E402
from intelligence.scorecard import Scorecard  # noqa: E402
from intelligence.tariff import NOT_VERIFIED, VERIFIED_FROM_INTEGRATION, RateSlot, TariffResult  # noqa: E402
from intelligence.timeutil import HOUR, ts, utc_from_ts  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
CFG = SiteConfig(tz="UTC", round_trip_efficiency=0.81, battery_capacity_kwh=10.0, max_grid_charge_kw=5.0,
                 user_reserve_soc_pct=40.0, technical_min_soc_pct=10.0, max_soc_pct=100.0, pv_array_kwp=None)
ETA = 0.9
START = date(2030, 1, 1)
DAYS = 16
NIGHT = range(1, 6)                                    # local (UTC) hours 01:00-05:59 are the cheap hours


def house(night_target: dict | float = 80.0, drop: set[int] | None = None, days: int = DAYS, flag_hours: set[int] | None = None) -> History:
    """Independent house: charge from the grid in the cheap hours to the night target (a float, or a date -> target dict),
    otherwise self-use between the reserve and full. Hourly mean SOC is the mean of the hour's start and end."""
    base = synthetic.make_history(START, days, CFG, seed=4, with_soc=False)
    cap = CFG.battery_capacity_kwh
    soc = 70.0
    out = []
    for s in sorted(base.by_start):
        b = base.by_start[s]
        t = utc_from_ts(s)
        pv, load = b.e["pv"], b.e["load"]
        tgt = night_target.get(t.date(), 80.0) if isinstance(night_target, dict) else night_target
        stored = soc / 100.0 * cap
        chg = dis = 0.0
        net = pv - load
        if t.hour in NIGHT and soc < tgt - 1e-9:
            chg = min(CFG.max_grid_charge_kw, (tgt / 100.0 * cap - stored) / ETA)
        elif net > 0:
            chg = min(net, (cap - stored) / ETA)
        else:                                           # the night holds the target (the advice's own meaning); else the reserve
            floor = max(0.4 * cap, tgt / 100.0 * cap) if t.hour in NIGHT else 0.4 * cap
            dis = min(-net, max(0.0, stored - floor) * ETA)
        new = stored + chg * ETA - dis / ETA
        grid = load + chg - pv - dis                    # > 0 import, < 0 export
        imp, exp = max(0.0, grid), max(0.0, -grid)
        rec = HourRecord(start=s)
        rec.e.update({"pv": pv, "load": load, "imp": imp, "exp": exp, "chg": chg, "dis": dis})
        rec.soc_mean = (soc + new / cap * 100.0) / 2.0
        if flag_hours and s in flag_hours:
            rec.flag("chg", F_STALLED)
        soc = new / cap * 100.0
        if not (drop and s in drop):
            out.append(rec)
    return History(out)


def tariff(history: History, expensive_nights=(), cover_hours: int | None = None, status=VERIFIED_FROM_INTEGRATION) -> TariffResult:
    """Half-hour rates: 7 p in the cheap hours, 30 p otherwise, 40 p at the `expensive_nights` (dates)."""
    if status != VERIFIED_FROM_INTEGRATION:
        return TariffResult("import", status)
    first, last = history.first_last()
    end = last + timedelta(hours=1) if cover_hours is None else first + timedelta(hours=cover_hours)
    slots, t = [], first
    while t < end:
        night = t.hour in NIGHT
        p = (40.0 if t.date() in expensive_nights else 7.0) if night else 30.0
        slots.append(RateSlot(t, t + timedelta(minutes=30), p))
        t += timedelta(minutes=30)
    return TariffResult("import", VERIFIED_FROM_INTEGRATION, tuple(slots))


def advice_for_every_night(h: History, target: float, only: date | None = None) -> list[dict]:
    """charge_target OK, issued 23:00 the evening before, window 01:00-06:00 (hour aligned), at `target`."""
    first, last = h.first_last()
    rows = []
    d = first.date() + timedelta(days=1)
    while d <= last.date():
        if only is None or d == only:
            issued = datetime(d.year, d.month, d.day, tzinfo=UTC) - timedelta(hours=1)
            rows.append({"kind": "charge_target", "status": "OK", "issued_at": issued.isoformat(),
                         "window_start": (issued + timedelta(hours=2)).isoformat(),
                         "window_end": (issued + timedelta(hours=7)).isoformat(), "target_soc_pct": target,
                         "effective_reserve_pct": 40.0, "advice_id": f"t:{d.isoformat()}"})
        d += timedelta(days=1)
    return rows


def money_keys(obj, path=""):
    """Every key that names money (ends in _p or has _p_ in it), anywhere in the structure."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith("_p") or "_p_" in k:
                out.append(path + "/" + k)
            out += money_keys(v, path + "/" + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += money_keys(v, f"{path}[{i}]")
    return out


def _raised(fn) -> bool:
    try:
        fn()
    except (ValueError, TypeError):
        return True
    return False


H0 = house(80.0)
T0 = tariff(H0)
check("the synthetic house has 16 days of hourly records with the six energies and a SOC",
      len(H0) == 16 * 24 and all({"pv", "load", "imp", "exp", "chg", "dis"} <= set(r.e) and r.soc_mean is not None
                                 for r in H0.by_start.values()))

print("== [1] no advice: the ghost is reality")
f0 = gf.build_ghost_feed(H0, [], CFG, import_tariff=T0)
check("status OK, money available, 14 days, the period is the whole usable run", f0["status"] == "OK" and f0["money_available"]
      and len(f0["days"]) == 14 and f0["period"]["hours"] >= 14 * 24, f"{f0['status']} {len(f0['days'])} {f0['period']}")
check("no advice: the model baseline is 0 and so is every delta, per day and in total",
      f0["totals"]["model_baseline_delta_p"] == 0 and f0["totals"]["delta_stock_adjusted_p"] == 0
      and f0["totals"]["advice_effect_p"] == 0 and all(d["delta_realised_p"] == 0 and d["delta_stock_adjusted_p"] == 0
                                                       and d["advice_effect_p"] == 0 for d in f0["days"]), str(f0["totals"]))
check("no advice: nothing followed, none in force, ghost minimum SOC = actual", f0["advice"]["followed"] == 0
      and all(d["advice_in_force_hours"] == 0 and d["ghost_min_soc_pct"] == d["actual_min_soc_pct"] for d in f0["days"]))
check("the days are the newest local days, oldest first, with their hours",
      [d["date"] for d in f0["days"]] == sorted(d["date"] for d in f0["days"]) and f0["days"][-1]["date"] == "2030-01-16"
      and f0["days"][0]["date"] == "2030-01-03" and all("hours" not in d for d in f0["days"]), str([d["date"] for d in f0["days"]]))

print("== [2] matching advice: the same charging as reality")
rows = advice_for_every_night(H0, 80.0)
f1 = gf.build_ghost_feed(H0, rows, CFG, import_tariff=T0)
p_start = datetime.fromisoformat(f1["period"]["start"])
check("every advice issued in the period is followed (hour-aligned windows)", f1["advice"]["followed"] == len(
    [r for r in rows if datetime.fromisoformat(r["issued_at"]) >= p_start]) > 0 and not f1["advice"]["not_followed"], str(f1["advice"]))
check("the ghost follows the advice and equals reality to within a penny a day and a few pence in total",
      all(abs(d["delta_stock_adjusted_p"]) <= 1.0 for d in f1["days"]) and abs(f1["totals"]["advice_effect_p"]) <= 3.0,
      str([d["delta_stock_adjusted_p"] for d in f1["days"]]))
check("advice was in force on the cheap hours", any(d["advice_in_force_hours"] >= 5 for d in f1["days"]))

print("== [3] a losing day")
bad_day = date(2030, 1, 9)
tb = tariff(H0, expensive_nights=(bad_day,))
rows_bad = advice_for_every_night(H0, 100.0, only=bad_day)
f2 = gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=tb)
day = next(d for d in f2["days"] if d["date"] == bad_day.isoformat())
check("the expensive night's advice to charge to 100 % loses that day (stock-adjusted)", day["delta_stock_adjusted_p"] < -1.0
      and day["advice_effect_p"] < -1.0, str(day))
check("it is counted: ghost behind on that day and the worst ghost day is that date",
      f2["ready_for_assisted_evidence"]["days_ghost_behind"] >= 1
      and f2["ready_for_assisted_evidence"]["worst_ghost_day"]["date"] == bad_day.isoformat(),
      str(f2["ready_for_assisted_evidence"]))
check("the other days are level (no advice on them)", all(abs(d["delta_stock_adjusted_p"]) <= 1.0 for d in f2["days"]
                                                          if d["date"] < bad_day.isoformat()), "")
check("the ghost's minimum SOC is reported next to reality's, and no reserve breach for a charge advice",
      day["ghost_min_soc_pct"] is not None and day["actual_min_soc_pct"] is not None and not any(
          d["ghost_below_reserve"] for d in f2["days"]), str(f2["ready_for_assisted_evidence"]["ghost_below_reserve_dates"]))

print("== [4] no money without a verified tariff")
fn = gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=None)
check("no tariff: status OK, money_available False, tariff NOT_VERIFIED", fn["status"] == "OK" and fn["money_available"] is False
      and fn["tariff"]["import"] == "NOT_VERIFIED", str(fn["tariff"]))
check("no tariff: no money key anywhere in the summary", money_keys(fn) == [], str(money_keys(fn)[:6]))
check("no tariff: the behaviour comparison is there (minimum SOC, imports, stock, reserve, advice followed)",
      all(k in fn["days"][0] for k in ("actual_min_soc_pct", "ghost_min_soc_pct", "ghost_below_reserve",
                                       "extra_import_kwh_in_ghost", "advice_followed")) and "ghost_below_reserve_slots"
      in fn["ready_for_assisted_evidence"] and "NO_VERIFIED_TARIFF" in fn["data_quality"]["notes"][0])
check("no tariff: the advice that was given still changed the ghost's imports on its day",
      any(abs(d["extra_import_kwh_in_ghost"]) > 0.05 for d in fn["days"]))
fb = gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=tariff(H0, status="BLOCK"))
check("a blocked tariff is not verified: no money", fb["money_available"] is False and money_keys(fb) == [])
fs = gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=tariff(H0, cover_hours=12))
check("a verified tariff covering under 24 h gives no money and says why", fs["money_available"] is False
      and money_keys(fs) == [] and any("TARIFF_COVERS_TOO_LITTLE" in n for n in fs["data_quality"]["notes"]),
      str(fs["data_quality"]["notes"]))
check("with money the unverified export tariff is disclosed", any("EXPORT_TARIFF_NOT_VERIFIED" in n for n in f0["data_quality"]["notes"])
      and f0["tariff"]["export"] == "NOT_VERIFIED")

print("== [5] the summary")
txt = json.dumps(f2, allow_nan=False, sort_keys=True)
check("it says plainly that it is a simulation and that Intelligence controlled nothing",
      f2["simulated"] is True and f2["intelligence_controlled_nothing"] is True and "SIMULATION" in f2["label"]
      and "controlled nothing" in f2["label"])
check("JSON-safe (no NaN or infinity) and a round trip is exact", json.loads(txt) == json.loads(json.dumps(f2, sort_keys=True)))
size = len(json.dumps(f2, sort_keys=True, separators=(",", ":")).encode())
check(f"size bound: 14 days with money fit in 8 KB ({size} bytes)", size <= gf.MAX_BYTES and f2["days_dropped"] == 0, str(size))
f_small = gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=tb, max_bytes=3000)
check("a tighter bound drops the oldest days, says so, and keeps the newest", f_small["days_dropped"] > 0
      and f_small["days"][-1]["date"] == f2["days"][-1]["date"] and len(f_small["days"]) == 14 - f_small["days_dropped"]
      and len(json.dumps(f_small, sort_keys=True, separators=(",", ":")).encode()) <= 3000 or len(f_small["days"]) == 1,
      f"{f_small['days_dropped']} {len(f_small['days'])}")
check("deterministic: the same inputs give the identical summary", gf.build_ghost_feed(H0, rows_bad, CFG, import_tariff=tb) == f2)
r = f2["ready_for_assisted_evidence"]
check("ready_for_assisted_evidence is evidence only and decides nothing", r["evidence_only"] is True and r["decision"] is None
      and {"days_compared", "days_ghost_ahead", "days_ghost_behind", "ghost_below_reserve_slots", "effective_reserve_pct",
           "advice_effect_p", "model_baseline_delta_p"} <= set(r))
u = f2["uncertainty"]
check("the uncertainty block: both stock rules, the model baseline, efficiency +/- 3 points",
      {"cost_basis", "mean_import_price"} <= set(u["stock_rules_p"]) and "model_baseline_delta_p" in u
      and u["round_trip_efficiency_pct"] == {"base": 81.0, "minus": 78.0, "plus": 84.0}
      and {"minus", "base", "plus"} <= set(u["sensitivity"]) and "closing_stock_rules" in u, str(u["round_trip_efficiency_pct"]))
check("the sensitivity differs from the base when the efficiency changes (the losing day is efficiency-sensitive)",
      u["sensitivity"]["minus"]["advice_effect_p"] != u["sensitivity"]["plus"]["advice_effect_p"], str(u["sensitivity"]))
check("totals add up: the per-day realised deltas sum to the total", abs(sum(d["delta_realised_p"] for d in f2["days"])
                                                                          - f2["totals"]["delta_realised_p"]) <= 0.05 * 14)

print("== [6] data")
gap = {ts(datetime(2030, 1, 5, 12, tzinfo=UTC)) + k * HOUR for k in range(3)}
hg = house(80.0, drop=gap)
fg = gf.build_ghost_feed(hg, [], CFG, import_tariff=tariff(hg))
check("a gap in the middle: the longest run is used and the gap is counted", fg["status"] == "OK"
      and fg["data_quality"]["unusable_by_reason"].get("missing_hour") == 3 and fg["period"]["start"].startswith("2030-01-05T15"),
      f"{fg['data_quality']['unusable_by_reason']} {fg['period']}")
hf = house(80.0, flag_hours={ts(datetime(2030, 1, 14, 3, tzinfo=UTC))})
ff = gf.build_ghost_feed(hf, [], CFG, import_tariff=tariff(hf))
check("a stalled-counter hour is unusable", ff["data_quality"]["unusable_by_reason"].get("flagged_energy") == 1,
      str(ff["data_quality"]["unusable_by_reason"]))
hs = house(80.0, days=1)
fi = gf.build_ghost_feed(History(list(hs.by_start.values())[:10]), [], CFG, import_tariff=None)
check("too little history is INSUFFICIENT_HISTORY with a reason and no figures", fi["status"] == "INSUFFICIENT_HISTORY"
      and fi["reason"] and "days" not in fi and money_keys(fi) == [], str(fi))
check("an empty history is INSUFFICIENT_HISTORY", gf.build_ghost_feed(History([]), [], CFG)["status"] == "INSUFFICIENT_HISTORY")
check("`now` cuts off the hour still in progress", gf.build_ghost_feed(H0, [], CFG, import_tariff=T0,
                                                                         now=datetime(2030, 1, 16, 20, 30, tzinfo=UTC))["period"]["end"]
      == "2030-01-16T20:00:00+00:00")
# hourly slot matching of the advice window
slots = tuple(gf.Slot(datetime(2030, 1, 1, h, tzinfo=UTC), 1.0, 0, 0, 0, 0, 0, 0) for h in range(24))
a = gf.AdviceRecord("charge_target", "OK", datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, 0, 30, tzinfo=UTC),
                    datetime(2030, 1, 1, 5, 30, tzinfo=UTC), 80.0)
b, why = gf._snap(a, slots)
check("a 00:30-05:30 window covers the hourly slots 00:00-06:00 (a slot is in when half of it is)",
      why is None and b.window_start.hour == 0 and b.window_end.hour == 6, str(b))
a2 = gf.AdviceRecord("charge_target", "OK", datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 1, 1, 0, 5, tzinfo=UTC),
                     datetime(2030, 1, 1, 0, 20, tzinfo=UTC), 80.0)
b2, why2 = gf._snap(a2, slots)
check("a window shorter than half a slot reaches none: not followed, WINDOW_SHORTER_THAN_SLOT",
      why2 == "WINDOW_SHORTER_THAN_SLOT" and b2.window_start is None)
dump = {"kind": "dump_to_grid", "status": "OK", "issued_at": "2030-01-10T10:00:00+00:00", "window_start": None, "window_end": None,
        "target_soc_pct": 50.0, "export_kwh": 4.0, "export_kw": 3.0, "effective_reserve_pct": 40.0, "dump_advisable": True,
        "advice_id": "d1"}
fd = gf.build_ghost_feed(H0, [dump, {"kind": "nonsense"}], CFG, import_tariff=T0)
check("dump advice without a window is not followed, is counted and explained; an invalid row is counted",
      fd["advice"]["not_followed"] == {"NO_WINDOW": 1} and fd["data_quality"]["dump_advice_without_window"] == 1
      and fd["data_quality"]["advice_rows_invalid"] == 1 and any("DUMP_ADVICE_HAS_NO_WINDOW" in n for n in fd["data_quality"]["notes"]),
      str(fd["advice"]))

print("== [7] the advice log round trip")
sc = Scorecard(":memory:", "UTC")
gen = datetime(2030, 1, 9, 0, 0, tzinfo=UTC) - timedelta(hours=1)
payload = {"sensor.t": ("OK", {"kind": "charge_target", "status": "OK", "generated_at": gen.isoformat(),
                              "valid_until": (gen + timedelta(minutes=10)).isoformat(), "reason_codes": [], "confidence": "MEDIUM"},
                        {"advice": {"target_soc_pct": 100.0, "effective_reserve_pct": 40.0,
                                    "window": [(gen + timedelta(hours=2)).isoformat(), (gen + timedelta(hours=7)).isoformat()]}})}
check("record_advice writes one row", sc.record_advice(payload) == 1)
got = sc.advice_records(datetime(2030, 1, 1, tzinfo=UTC), datetime(2030, 2, 1, tzinfo=UTC))
check("advice_records returns the row as an AdviceRecord dict", len(got) == 1 and got[0]["kind"] == "charge_target"
      and got[0]["target_soc_pct"] == 100.0 and got[0]["advice_id"].startswith("advice_log:"), str(got))
check("advice_records filters by time and kind and writes nothing", sc.advice_records(datetime(2030, 2, 1, tzinfo=UTC)) == []
      and sc.advice_records(kind="dump_to_grid") == [] and sc.db.execute("SELECT COUNT(*) FROM advice_log").fetchone()[0] == 1)
fl = gf.build_ghost_feed(H0, got, CFG, import_tariff=tb)
check("the logged advice runs through the feed as the same losing day", fl["advice"]["followed"] == 1
      and next(d for d in fl["days"] if d["date"] == "2030-01-09")["delta_stock_adjusted_p"] < -1.0)

print("== [7c] per-slot log rows are not distinct advice (G5), and a later BLOCKED row withdraws (G6)")
H8 = house(80.0)
T8 = tariff(H8)
base8 = advice_for_every_night(H8, 80.0)
dup8 = []
for r in base8:                                        # the slot cycles log the same advice every hour until its window opens
    t_iss = datetime.fromisoformat(r["issued_at"])
    for k in range(1, 5):
        dup8.append(dict(r, issued_at=(t_iss - timedelta(hours=k)).isoformat(), advice_id=f"{r['advice_id']}-{k}"))
f_dup = gf.build_ghost_feed(H8, base8 + dup8, CFG, import_tariff=T8)
f_one = gf.build_ghost_feed(H8, base8, CFG, import_tariff=T8)
check("non-vacuity: five log rows per night are five times the rows of one",
      f_dup["advice"]["records_in_period"] == 5 * f_one["advice"]["records_in_period"] > 0, str(f_dup["advice"]))
check("'followed' counts distinct (kind, window, target), not log rows: five rows of the same night's advice are one",
      f_dup["advice"]["followed"] == f_one["advice"]["followed"] > 0, f"{f_dup['advice']} {f_one['advice']}")
check("... the raw count of followed log rows is kept next to it", f_dup["advice"].get("followed_log_rows") == f_dup["advice"]["records_in_period"]
      and f_one["advice"].get("followed_log_rows") == f_one["advice"]["followed"], str(f_dup["advice"]))
check("... per day too: one followed advice per night, however many rows", all(d["advice_followed"] <= 1 for d in f_dup["days"])
      and [d["advice_followed"] for d in f_dup["days"]] == [d["advice_followed"] for d in f_one["days"]],
      str([d["advice_followed"] for d in f_dup["days"]]))
check("a different target on the same window is another advice", gf.build_ghost_feed(H8, base8 + [dict(base8[3], target_soc_pct=70.0, advice_id="x",
      issued_at=(datetime.fromisoformat(base8[3]["issued_at"]) - timedelta(minutes=30)).isoformat())], CFG, import_tariff=T8)["advice"]["followed"]
      == f_one["advice"]["followed"] + 1)
BAD8 = date(2030, 1, 9)
H_b = H8                                                # the real house charged to 80 % that night; the advice says 100 %
T_b = tariff(H_b, (BAD8,))
ok_b = advice_for_every_night(H_b, 100.0, only=BAD8)
wd_row = dict(ok_b[0], status="BLOCKED", issued_at=(datetime.fromisoformat(ok_b[0]["issued_at"]) + timedelta(minutes=30)).isoformat(),
              window_start=None, window_end=None, target_soc_pct=None, advice_id="wd")
f_ok = gf.build_ghost_feed(H_b, ok_b, CFG, import_tariff=T_b)
f_wd = gf.build_ghost_feed(H_b, ok_b + [wd_row], CFG, import_tariff=T_b)
day_ok = next(d for d in f_ok["days"] if d["date"] == BAD8.isoformat())
day_wd = next(d for d in f_wd["days"] if d["date"] == BAD8.isoformat())
check("a BLOCKED row issued after the OK one and before its window: the ghost does not follow the withdrawn advice (nothing in force)",
      day_ok["advice_in_force_hours"] > 0 and day_wd["advice_in_force_hours"] == 0 and f_wd["totals"]["advice_effect_p"] == 0.0
      and f_ok["totals"]["advice_effect_p"] != 0.0, f"{day_ok['advice_in_force_hours']} {day_wd['advice_in_force_hours']} {f_wd['totals']['advice_effect_p']}")
check("... and the withdrawn row is still counted as followable, the BLOCKED row as not followed",
      f_wd["advice"]["followed"] == 1 and f_wd["advice"]["not_followed"] == {"BLOCKED": 1}, str(f_wd["advice"]))

print("== [7b] the unwired entity payload helper")
st, at = gf.to_entity_payload(f2)
check("to_entity_payload: state is the feed status, attributes are the feed plus the SHADOW markers, no contract version",
      st == "OK" and at["mode"] == "SHADOW" and at["applies_nothing"] is True and at["days"] == f2["days"]
      and "contract_version" not in at and len(json.dumps(at, sort_keys=True, separators=(",", ":")).encode()) <= gf.MAX_BYTES + 100)
check("to_entity_payload refuses anything that is not a ghost feed", all(
    _raised(lambda x=x: gf.to_entity_payload(x)) for x in ({}, {"schema": "other"}, None)))
check("nothing in the integration or the contract calls it (unwired)", not any(
    "to_entity_payload" in p.read_text(encoding="utf-8") and "ghost_feed" in p.read_text(encoding="utf-8")
    for p in (ROOT / "custom_components" / "ecco_intelligence").rglob("*.py") if "tests" not in p.parts)
      and "ghost_feed" not in (ROOT / "intelligence" / "advisory_contract.py").read_text(encoding="utf-8"))

print("== [8] no write path (static)")
src = (ROOT / "intelligence" / "ghost_feed.py").read_text(encoding="utf-8")
tree = ast.parse(src)
mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | {
    a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
bad_mods = {"socket", "http", "urllib", "requests", "subprocess", "os", "shutil", "sqlite3", "pathlib", "asyncio", "threading"}
calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
check("ghost_feed imports nothing networked, process-like or file-like and calls no open / exec / eval",
      not (mods & bad_mods) and not (calls & {"open", "exec", "eval", "compile", "__import__"}), str(mods))
vocab = ("write_register", "set_state", "async_set", "call_service", "turn_on", "turn_off", "arm_schedule", "mqtt", "modbus")
check("it holds no control vocabulary", not [v for v in vocab if v in src.lower()])

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in intelligence ghost feed:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All intelligence ghost feed checks PASSED.")
