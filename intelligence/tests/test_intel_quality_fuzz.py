#!/usr/bin/env python3
"""Data quality (dq) fuzz: seeded malformed inputs never raise and never leave an item unblocked that relies on a stale,
missing or disagreeing input (fictional 2030 data only).

  [1] CASES seeded CycleInputs mutations (missing / None / NaN / infinite / implausible / wrongly typed values, wrong
      units, naive / future / ancient times, duplicates, junk entries, a shifted cycle time, liveness changes, an old
      snapshot, inconsistent caller ages and flags, a LiveInputs that disagrees with the snapshot, history gaps / future
      hours / NaN energies / junk records, a stale history with junk, None or a mis-keyed record filed under a newer key,
      junk fields): assess_inputs never raises, and for every item it leaves unblocked an independent oracle confirms each
      required input is present, plausible and fresh (a snapshot signal never younger than its snapshot, a forecast from
      the cycle's local date, the history dated by its well-formed records, a configuration-poll reading aged by the
      larger of the two liveness ages with both liveness readings within their bounds), the liveness readings are fresh
      when required (the configuration-poll liveness for every charge-window item), no caller assessment calls an input
      fresh that the oracle finds stale, the caller withheld no non-dongle input it needs, the LiveInputs agrees with the
      snapshot, the snapshot is recent, a zero SOC is resolved by a fresh raw SOC, a TOU-derived window has a fresh,
      small clock offset, export_event a fresh event table, and export and Dump advice current, stable supervision (the
      state and stable flag aged by the telemetry poll text, the heartbeat by its own reading time). The bases include a
      frozen configuration poll, a telemetry poll beyond the supervision bound only, an aged but valid configuration poll
      and steady supervision
  [1b] SIM_CASES more cases on a second seed, the same oracle. Its CCR-DQ-1 simulation does nothing on the integrated
      code (CCR-DQ-1 has landed: the qualifying readings are I-D6 keys with no default limit), so both [1] and [1b] judge
      them under the contract's own limits, and the charge-window and SOC rules are exercised with those readings fresh
  [2] the property is not vacuous: many cases leave items unblocked and many block; charge-window items are left
      unblocked on an aged but valid configuration poll text and blocked by CONFIG_LIVENESS_*; export or Dump advice is
      left unblocked on steady supervision
  [3] PREPARE_CASES seeded prepare_history calls on corrupted histories (junk energies, flags and sources too) and random
      I-D8 records: never raise, never return an hour that had not ended, never keep what the recorded policy removes
      (under KEEP_AFTER_COUNTER_CHECK only checked, agreeing counters), never modify the input
"""

from __future__ import annotations

import copy
import math
import random
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _dq_helpers as h  # noqa: E402
from ecco_core.state import Observation, Snapshot  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.advisor import LiveInputs  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.inputs import live_inputs_from_snapshot  # noqa: E402
from intelligence.timeutil import local_date, local_wall, zone  # noqa: E402

FAILURES: list[str] = []
CASES = 2400
SIM_CASES = 1600
PREPARE_CASES = 400
NAN, INF = float("nan"), float("inf")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


BASES = [h.clean(), cf.cycle_inputs(), cf.cycle_inputs(stale_liveness=True, synthetic_recorded=True),
         cf.cycle_inputs(synthetic_recorded=True, now=cf.NOW + timedelta(days=3, hours=-2)),
         faults.frozen_config_poll_text(h.clean(), 1),           # the configuration poll frozen, the telemetry poll alive
         faults.supervision_poll_frozen(h.clean(), 2),           # the telemetry poll beyond the supervision bound only
         # the configuration poll text 250 s old (aged but inside its bound), and steady supervision (state and stable last
         # changed 10 min ago while the telemetry poll text moves)
         faults.with_reading(h.clean(), sd.CONFIG_LIVENESS_KEY, value=cf.NOW - timedelta(seconds=250),
                             observed_at=cf.NOW - timedelta(seconds=250)),
         faults.with_reading(faults.with_reading(h.clean(), "supervision.state", observed_at=cf.NOW - timedelta(minutes=10)),
                             "supervision.stable", observed_at=cf.NOW - timedelta(minutes=10)),
         # a synthetic I-D6 of 900 s (the ceiling) for every key without a defined limit, the configuration poll 250 s old:
         # here the configuration-poll bound, not a reading's own limit, decides once the poll text passes 300 s
         faults.with_reading(cf.cycle_inputs(decisions=h.decisions_with("D6", sd.FreshnessOverrides(
             {k: 900.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None})), accept_provenance=h.SYN),
             sd.CONFIG_LIVENESS_KEY, value=cf.NOW - timedelta(seconds=250), observed_at=cf.NOW - timedelta(seconds=250))]
JUNK_VALUES = [None, NAN, INF, -INF, -1.0, 0.0, 1e15, "", "x", "unavailable", [], {}, (), True, False, object(), b"\x00",
               datetime(2030, 1, 15, 20, 0), [{"start": "01:00"}]]
# values on and just beyond the plausibility and clock bounds (DATA_QUALITY_METHOD section 11), per reading
EDGES = {"stop.dump_soc_pct": [-0.1, 0.0, 100.0, 100.1, 150.0], "protection.shutdown_soc_pct": [-0.1, 100.1, 12.0],
         "battery.soc_raw_pct": [-0.1, 0.0, 0.4, 100.1, 140.0, 55.0], "limits.max_grid_charge_w": [0.0, -1.0, 100000.0, 100001.0],
         "pv.forecast_tomorrow_kwh": [-0.01, 0.0, 55.0, 60.0, 60.1, 500.1], "inverter.clock_offset_s": [-30.0, 30.0, 30.1, -31.0, 119.9],
         "supervision.heartbeat_age_s": [-1.0, 0.0, 59.0, 61.0], "capacity.helper_kwh": [0.4, 0.5, 500.1]}


def clone(hist: History) -> History:
    """A deep copy that keeps junk entries as they are (History() would refuse them)."""
    out = History()
    out.by_start = {s: copy.deepcopy(r) for s, r in hist.by_start.items()}
    return out


def jtime(rnd: random.Random, now: datetime):
    return rnd.choice([None, now.replace(tzinfo=None), now + timedelta(seconds=rnd.uniform(1, 86400)),
                       now - timedelta(days=rnd.uniform(1, 400)), now - timedelta(seconds=rnd.uniform(0, 1200)), "2030", 5])


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def mutate(rnd: random.Random, x: ac.CycleInputs) -> ac.CycleInputs:
    now = x.now
    for _ in range(rnd.randint(1, 4)):
        m = rnd.random()
        if m < 0.07 and isinstance(x.site_readings, tuple) and x.site_readings:      # an edge value or a date edge
            key = rnd.choice(sorted(EDGES) + ["pv.forecast_tomorrow_kwh@date"])
            rs = list(x.site_readings)
            for j, r in enumerate(rs):
                if isinstance(r, ac.SiteReading) and r.key == key.split("@")[0] and isinstance(now, datetime) and now.tzinfo:
                    if key.endswith("@date"):         # just before or after the cycle's local midnight
                        mid = local_wall(local_date(now, zone("Europe/London")), 0, zone("Europe/London"))
                        rs[j] = replace(r, observed_at=mid + timedelta(seconds=rnd.choice((-1, 1)) * rnd.uniform(1, 86400)))
                    else:
                        rs[j] = replace(r, value=rnd.choice(EDGES[key]) if rnd.random() < 0.7 else rnd.uniform(-200.0, 200.0))
            object.__setattr__(x, "site_readings", tuple(rs))
        elif m < 0.28 and isinstance(x.site_readings, tuple) and x.site_readings:      # one reading
            rs = list(x.site_readings)
            j = rnd.randrange(len(rs))
            r = rs[j]
            if not isinstance(r, ac.SiteReading):
                continue
            field = rnd.choice(("value", "observed_at", "unit", "source", "key", "drop", "dup", "junk"))
            if field == "value":
                rs[j] = replace(r, value=rnd.choice(JUNK_VALUES + [r.value, 150.0, -10.0, 1e6, 0.4]))
            elif field == "observed_at":
                rs[j] = replace(r, observed_at=jtime(rnd, now))
            elif field == "unit":
                rs[j] = replace(r, unit=rnd.choice([None, "kW", "W", "%", 3]))
            elif field == "source":
                rs[j] = replace(r, source=rnd.choice(["", None, 7, r.source]))
            elif field == "key":
                rs[j] = replace(r, key=rnd.choice(["nope.key", None, 5, sd.LIVENESS_KEY, sd.CONFIG_LIVENESS_KEY,
                                                   "battery.soc_raw_pct", "supervision.state"]))
            elif field == "drop":
                rs.pop(j)
            elif field == "dup":
                rs.append(r)
            else:
                rs[j] = rnd.choice([None, 5, "reading", {"key": r.key}])
            object.__setattr__(x, "site_readings", tuple(rs))
        elif m < 0.38 and isinstance(x.site_readings, tuple):            # one of the two liveness readings
            # the telemetry poll text around its 180 s and the supervision 90 s bounds, the configuration poll text around
            # its 300 s bound
            lkey, span = rnd.choice(((sd.LIVENESS_KEY, 400), (sd.LIVENESS_KEY, 120), (sd.CONFIG_LIVENESS_KEY, 700)))
            t = rnd.choice([now - timedelta(seconds=rnd.uniform(0, span)), now + timedelta(seconds=rnd.uniform(1, 600)),
                            now.replace(tzinfo=None), None])
            rs = [replace(r, value=t, observed_at=rnd.choice([t, now - timedelta(seconds=rnd.uniform(0, span))]))
                  if isinstance(r, ac.SiteReading) and r.key == lkey and t is not None and t.tzinfo is not None
                  else (replace(r, value=t) if isinstance(r, ac.SiteReading) and r.key == lkey else r)
                  for r in x.site_readings]
            object.__setattr__(x, "site_readings", tuple(rs))
        elif m < 0.51 and isinstance(x.snapshot, Snapshot):              # one signal (the LiveInputs usually rebuilt)
            obs = dict(x.snapshot.observations)
            sig = rnd.choice(sorted(obs))
            o = obs[sig]
            k = rnd.random()
            if k < 0.3:
                obs.pop(sig)
            elif k < 0.6:
                t = rnd.choice([None, now + timedelta(seconds=rnd.uniform(1, 86400)), now - timedelta(seconds=rnd.uniform(0, 4000))])
                obs[sig] = replace(o, observed_at=t)
            else:
                v = None if o.unit is None and not isinstance(o.value, bool) else rnd.choice([None, 0.0, -50.0, 55.0, 140.0, 3000.0])
                if sig in ("inverter.healthy", "history.hourly"):
                    v = rnd.choice([None, True, False, "unavailable"])
                obs[sig] = replace(o, value=v)
            new = Snapshot(x.snapshot.as_of, obs)
            object.__setattr__(x, "snapshot", new)
            if isinstance(x.live, LiveInputs) and rnd.random() < 0.7:
                object.__setattr__(x, "live", live_inputs_from_snapshot(new))
        elif m < 0.56 and isinstance(x.live, LiveInputs):                # the LiveInputs disagrees with the snapshot
            attr = rnd.choice(("soc_pct", "load_w", "pv_w", "inverter_ok", "ha_reserve_pct", "now"))
            cur = getattr(x.live, attr)
            if attr == "inverter_ok":
                new_v = (not cur) if isinstance(cur, bool) else True
            elif attr == "now":
                new_v = cur - timedelta(seconds=rnd.uniform(1, 3600)) if isinstance(cur, datetime) else now
            else:
                new_v = (cur if _finite(cur) else 50.0) + rnd.choice((-1, 1)) * rnd.uniform(0.5, 500.0)
            object.__setattr__(x, "live", replace(x.live, **{attr: new_v}))
        elif m < 0.62 and isinstance(x.snapshot, Snapshot):              # an old snapshot, as the bridge would see it
            # inside the bound; past it but inside every signal limit (only SNAPSHOT_STALE can catch that); beyond them
            back = timedelta(seconds=rnd.choice((rnd.uniform(30, 180), rnd.uniform(181, 300), rnd.uniform(181, 300),
                                                 rnd.uniform(301, 900), rnd.uniform(901, 7200))))
            obs = {k: (replace(o, observed_at=o.observed_at - back) if o.observed_at is not None else o)
                   for k, o in x.snapshot.observations.items()}
            new = Snapshot(x.snapshot.as_of - back, obs)
            object.__setattr__(x, "snapshot", new)
            if isinstance(x.live, LiveInputs) and rnd.random() < 0.8:
                object.__setattr__(x, "live", live_inputs_from_snapshot(new))
        elif m < 0.74:                                                    # caller assessments
            a = list(x.caller_assessments) if isinstance(x.caller_assessments, tuple) else []
            k = rnd.random()
            sig = rnd.choice(["battery.soc", "house.power", "pv.power", "inverter.healthy", "reserve.ha_minimum_soc",
                              "history.hourly", "grid.power", "nope.signal"])
            if k < 0.35:
                a.append((sig, rnd.random() < 0.8, rnd.choice([None, NAN, INF, -5.0, 0.0, 1e9, 20.0])))
            elif k < 0.6 and a:
                j = rnd.randrange(len(a))
                if isinstance(a[j], tuple) and len(a[j]) == 3:
                    a[j] = (a[j][0], not a[j][1] if isinstance(a[j][1], bool) else True, a[j][2])
            elif k < 0.8:
                a.append(rnd.choice([("battery.soc", "yes", None), ("battery.soc",), None, 5, ("x", True, 1.0, 2)]))
            else:
                a = [(s, rnd.choice([True, False]), rnd.choice([None, 0.0, 30.0, NAN])) for s, _f, _a in
                     [t for t in a if isinstance(t, tuple) and len(t) == 3]]
            object.__setattr__(x, "caller_assessments", tuple(a) if rnd.random() < 0.9 else a)
        elif m < 0.87 and isinstance(x.history, History) and len(x.history):        # the history
            hh = clone(x.history)
            ks = sorted(s for s in hh.by_start if isinstance(s, int))
            k = rnd.random()
            if k < 0.25:
                for s in rnd.sample(ks, min(len(ks), rnd.randint(1, 40))):
                    hh.by_start.pop(s, None)
            elif k < 0.35:
                s = ks[-1] + rnd.randint(1, 30) * 3600
                hh.by_start[s] = HourRecord(start=s, e={"load": 1.0, "pv": 0.0})
            elif k < 0.45:
                s = rnd.choice(ks)
                if isinstance(hh.by_start[s], HourRecord):
                    hh.by_start[s].e[rnd.choice(("load", "pv", "exp"))] = rnd.choice([NAN, INF, -3.0])
            elif k < 0.53:
                hh.by_start[rnd.choice(ks)] = rnd.choice([None, "rec", 5])
            elif k < 0.90:                    # a stale history plus junk filed under a newer key (it must not date it)
                if rnd.random() < 0.7:
                    cut_ = (now - timedelta(hours=rnd.choice((rnd.uniform(7, 30), rnd.uniform(7, 48))))).timestamp()
                    hh.by_start = {s: r for s, r in hh.by_start.items() if isinstance(s, int) and s + 3600 <= cut_}
                end = int(now.timestamp()) - int(now.timestamp()) % 3600
                s = rnd.choice([end - 3600, ks[-1] + 3600 * rnd.randint(1, 12)])
                hh.by_start[s] = rnd.choice([None, "junk", 5, HourRecord(start=s - 3600 * rnd.randint(1, 30), e={"load": 1.0}),
                                             HourRecord(start=s, e={}), HourRecord(start=s, e={"load": NAN}),
                                             HourRecord(start=s, e={"load": 1.0}, flags=None),
                                             HourRecord(start=s, e={"load": 1.0}, sources=None)])
            else:
                cut_ = (now - timedelta(hours=rnd.uniform(0, 12))).timestamp()
                hh.by_start = {s: r for s, r in hh.by_start.items() if s + 3600 <= cut_}
            object.__setattr__(x, "history", hh)
        elif m < 0.93 and isinstance(now, datetime):                     # the cycle time
            object.__setattr__(x, "now", now + timedelta(seconds=rnd.uniform(-600, 1200)))
            now = x.now
        else:                                                             # one junk field
            name = rnd.choice(("snapshot", "live", "history", "decisions", "accept_provenance", "site_facts", "pv_forecast_history",
                               "site_readings", "caller_assessments"))
            object.__setattr__(x, name, rnd.choice(JUNK_VALUES + [frozenset({"OWNER_RECORD", 1}),
                                                                  ac.SiteFacts(pv_array_kwp=6.0, tz="Nowhere/Invalid_Zone")]))
    return x


DQ_SNAPSHOT_MAX_S = 180.0         # DATA_QUALITY_METHOD section 11: snapshot_max_age_s
DQ_CLOCK_OFFSET_MAX_S = 30.0      # DATA_QUALITY_METHOD section 11: clock_offset_block_s


def violations(x: ac.CycleInputs, r: q.QualityResult) -> list[str]:
    out = []
    if not isinstance(r, q.QualityResult) or r.data_quality not in ac.DataQuality.ALL or not r.blocked_items <= frozenset(sd.ITEMS):
        return ["malformed result"]
    unblocked = [i for i in sd.ITEMS if i not in r.blocked_items]
    if not unblocked:
        return out
    if r.data_quality == ac.DataQuality.BLOCKED:
        out.append("data quality BLOCKED but items unblocked")
    if not (isinstance(x.now, datetime) and x.now.tzinfo is not None):
        return out + ["naive now left items unblocked"]
    decisions = x.decisions if isinstance(x.decisions, sd.DecisionSet) else sd.DecisionSet()
    accept = x.accept_provenance if isinstance(x.accept_provenance, frozenset) else sd.DEFAULT_ACCEPT_PROVENANCE
    limits = h.active_limits(decisions, accept)
    ca = x.caller_assessments
    ca = tuple(ca) if isinstance(ca, list) else ca
    if not isinstance(ca, tuple):
        return out + ["malformed caller assessments left items unblocked"]
    withheld = set()
    for a in ca:
        if not (isinstance(a, tuple) and len(a) == 3 and isinstance(a[0], str) and isinstance(a[1], bool)):
            return out + ["a malformed caller assessment left items unblocked"]
        sig, fresh, age = a
        if fresh and not (isinstance(age, (int, float)) and not isinstance(age, bool) and math.isfinite(age) and age >= 0):
            out.append(f"caller fresh with an unusable age for {sig} left items unblocked")
        if fresh and not h.oracle_fresh(x, sig, limits):
            out.append(f"caller says {sig} fresh, the oracle finds it stale, items unblocked")
        if not fresh and sig not in sd.DONGLE_SIGNALS:
            withheld.add(sig)
    live_bad = h.live_inconsistent(x)
    snap_age = h.snapshot_age(x)
    snap = x.snapshot if isinstance(x.snapshot, Snapshot) else None
    offsets = [rd for rd in (x.site_readings if isinstance(x.site_readings, tuple) else ())
               if isinstance(rd, ac.SiteReading) and rd.key == "inverter.clock_offset_s"]
    for item in unblocked:
        ri = sd.required_inputs(item, decisions, accept)
        for k in ri.signals + ri.readings:
            if not h.oracle_fresh(x, k, limits):
                out.append(f"{item} unblocked but {k} is not fresh")
            if k in withheld:
                out.append(f"{item} unblocked although the caller withheld {k}")
        on_snapshot = any(s != "history.hourly" for s in ri.signals)
        if on_snapshot and live_bad:
            out.append(f"{item} unblocked although the LiveInputs {live_bad}")
        if on_snapshot and snap_age is not None and snap_age > DQ_SNAPSHOT_MAX_S:
            out.append(f"{item} unblocked on an old snapshot")
        if "battery.soc" in ri.signals and snap is not None and snap.get("battery.soc") is not None:
            v = snap.get("battery.soc").value
            if h.finite(v) and v <= 0.5 and not h.oracle_fresh(x, "battery.soc_raw_pct", limits):
                out.append(f"{item} unblocked on a zero SOC with no fresh raw SOC")
        if ri.charge_window_sources:
            if not h.oracle_fresh(x, "tou.slot_table", limits):
                out.append(f"{item} unblocked without a fresh TOU slot table")
            if (not h.oracle_fresh(x, "inverter.clock_offset_s", limits) or len(offsets) != 1
                    or abs(offsets[0].value) > DQ_CLOCK_OFFSET_MAX_S):
                out.append(f"{item} unblocked on a TOU-derived window without a fresh, small clock offset")
        if item == "export_event" and not h.oracle_fresh(x, "tariff.events", limits):
            out.append("export_event unblocked without a fresh event table")
        if item in ("export_event", "dump_to_grid") and not h.oracle_supervision_ok(x):
            out.append(f"{item} unblocked without current, stable supervision (state and stable aged by the poll text)")
    return out


def run_cases(n: int, seed0: int) -> dict:
    raised, bad, leaks, rows_bad = [], [], [], []
    unblocked_cases = blocked_cases = cfg_aged_open = cfg_blocked = sup_steady_open = 0
    for i in range(n):
        rnd = random.Random(seed0 + i)
        x = copy.copy(rnd.choice(BASES))
        x = mutate(rnd, x)
        try:
            r = q.assess_inputs(x)
        except Exception as exc:  # noqa: BLE001 - the invariant under test
            raised.append((i, type(exc).__name__, str(exc)[:80]))
            continue
        v = violations(x, r)
        if v:
            bad.append((i, v[:2]))
        if any(f.code == "QUALITY_INTERNAL_ERROR" for f in r.findings):
            raised.append((i, "QUALITY_INTERNAL_ERROR", dict(r.findings[0].evidence)))
        leaks += [(i, t) for t in h.text_leaks(r)]
        try:
            rows = r.input_ages()
            if len(rows) > ac.MAX_INPUT_AGES or not all(ac._known_input(x_["name"]) for x_ in rows):
                rows_bad.append(i)
        except Exception as exc:  # noqa: BLE001
            rows_bad.append((i, type(exc).__name__))
        if len(r.blocked_items) < len(sd.ITEMS):
            unblocked_cases += 1
        if r.blocked_items:
            blocked_cases += 1
        # the configuration-poll rule and the supervision ageing are exercised both ways
        cfg_age = h.oracle_config_liveness_age(x) if isinstance(x.now, datetime) and x.now.tzinfo else None
        window_open = any(i not in r.blocked_items for i in sd.CHARGE_WINDOW_ITEMS)
        if window_open and cfg_age is not None and cfg_age > 120.0:
            cfg_aged_open += 1
        if any(f.code.startswith("CONFIG_LIVENESS_") for f in r.findings):
            cfg_blocked += 1
        if any(i not in r.blocked_items for i in ("export_event", "dump_to_grid")) and _steady_supervision(x):
            sup_steady_open += 1
    return {"raised": raised, "bad": bad, "leaks": leaks, "rows_bad": rows_bad, "unblocked": unblocked_cases,
            "blocked": blocked_cases, "cfg_aged_open": cfg_aged_open, "cfg_blocked": cfg_blocked,
            "sup_steady_open": sup_steady_open}


def _steady_supervision(x) -> bool:
    """The supervision state reading was last observed more than the supervision bound ago (steady supervision)."""
    rs = [r for r in (x.site_readings if isinstance(x.site_readings, tuple) else ())
          if isinstance(r, ac.SiteReading) and r.key == "supervision.state"]
    return (len(rs) == 1 and isinstance(rs[0].observed_at, datetime) and rs[0].observed_at.tzinfo is not None
            and (x.now - rs[0].observed_at).total_seconds() > h.SUPERVISION_MAX_S)


def report(label: str, n: int, res: dict) -> None:
    check(f"{label}: assess_inputs never raises (and never fails internally) on {n} cases", not res["raised"],
          str(res["raised"][:3]))
    check(f"{label}: no unblocked item relies on a stale, missing, implausible or disagreeing input (independent oracle)",
          not res["bad"], str(res["bad"][:3]))
    check(f"{label}: no finding text carries a number with a unit", not res["leaks"], str(res["leaks"][:3]))
    check(f"{label}: the input-age rows are always valid envelope rows", not res["rows_bad"], str(res["rows_bad"][:3]))


print(f"== [1] {CASES} seeded malformed CycleInputs (the CCR-DQ-1 readings under the contract's own limits)")
h.simulate_ccr_dq1(False)
STRICT = run_cases(CASES, 20301)
report("first seed", CASES, STRICT)

print(f"== [1b] {SIM_CASES} more cases on a second seed (the CCR-DQ-1 simulation does nothing on the integrated code)")
h.simulate_ccr_dq1(True)
SIM = run_cases(SIM_CASES, 70301)
h.simulate_ccr_dq1(False)
report("second seed", SIM_CASES, SIM)

print("== [2] the property is exercised")
check(f"many cases leave some item unblocked ({STRICT['unblocked']} first seed, {SIM['unblocked']} second seed)",
      STRICT["unblocked"] >= CASES // 10 and SIM["unblocked"] >= SIM_CASES // 10)
check(f"many cases block ({STRICT['blocked']} first seed, {SIM['blocked']} second seed)",
      STRICT["blocked"] >= CASES // 2 and SIM["blocked"] >= SIM_CASES // 2)
check(f"the configuration-poll rule is exercised: charge-window items left unblocked on an aged but valid configuration "
      f"poll text ({STRICT['cfg_aged_open']}, {SIM['cfg_aged_open']}) and CONFIG_LIVENESS_* blocks "
      f"({STRICT['cfg_blocked']}, {SIM['cfg_blocked']})",
      min(STRICT["cfg_aged_open"], SIM["cfg_aged_open"]) >= 10 and min(STRICT["cfg_blocked"], SIM["cfg_blocked"]) >= 50)
check(f"the supervision ageing is exercised: export or Dump left unblocked on steady supervision (a state reading older "
      f"than the bound, the poll text current) ({STRICT['sup_steady_open']}, {SIM['sup_steady_open']})",
      min(STRICT["sup_steady_open"], SIM["sup_steady_open"]) >= 5)

print(f"== [3] {PREPARE_CASES} seeded prepare_history calls")
hist = cf.history()
hist_cnt = faults.add_balanced_counters(hist)          # with import / export / battery counters the counter check can run


def fingerprint(hx: History) -> dict:
    return {s: (r.load_w_mean, r.pv_w_mean, r.soc_mean, dict(r.e), repr(r.flags), repr(r.sources)) for s, r in hx.by_start.items()}


prints = {id(hist): fingerprint(hist), id(hist_cnt): fingerprint(hist_cnt)}
ENERGY = ("load", "pv", "imp", "exp", "chg", "dis")


def counter_check_passes(r: HourRecord) -> bool:
    """The I-D8 counter check written out (DATA_QUALITY_METHOD section 10): every counter present and finite, the load
    counter within the larger of 0.1 kWh and 10 % of the balance-derived load (pv + imp - exp + dis - chg)."""
    v = [r.e.get(f) for f in ENERGY]
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
        return False
    load, pv, imp, exp_, chg, dis = v
    derived = pv + imp - exp_ + dis - chg
    return abs(load - derived) <= max(0.1, 0.1 * max(abs(derived), abs(load)))


praised, pbad = [], []
for i in range(PREPARE_CASES):
    rnd = random.Random(90001 + i)
    src = hist_cnt if rnd.random() < 0.5 else hist
    hh = clone(src) if rnd.random() < 0.5 else src
    if hh is not src:
        for _ in range(rnd.randint(0, 6)):
            ks = sorted(hh.by_start)
            s = rnd.choice(ks)
            k = rnd.random()
            if k < 0.25 and isinstance(hh.by_start[s], HourRecord):
                hh.by_start[s].e[rnd.choice(("load", "pv", "exp", "imp"))] = rnd.choice([NAN, INF, -1.0, 0.0, 50.0])
            elif k < 0.4:
                hh.by_start.pop(s, None)
            elif k < 0.52:                     # a record filed under one hour that names another (possibly unended) hour
                hh.by_start[ks[rnd.randrange(len(ks))] if rnd.random() < 0.5 else ks[-1] + 3600 * rnd.randint(1, 50)] = \
                    HourRecord(start=ks[-1] + 3600 * rnd.randint(1, 50), e={"load": 1.0})
            elif k < 0.64 and isinstance(hh.by_start[s], HourRecord):
                hh.by_start[s].soc_mean = rnd.choice([NAN, -5.0, 0.0, 140.0])
                hh.by_start[s].batt_w_mean = rnd.choice([None, 500.0, NAN])
            elif k < 0.82 and isinstance(hh.by_start[s], HourRecord):          # junk inside a record
                fld = rnd.choice(("e", "flags", "sources", "soc_flags", "grid_w_mean"))
                if fld == "soc_flags":
                    hh.by_start[s].flags = {"soc": rnd.choice([None, 5, "x"])}
                elif fld == "grid_w_mean":
                    hh.by_start[s].grid_w_mean = rnd.choice([NAN, "x", None])
                else:
                    setattr(hh.by_start[s], fld, rnd.choice([None, 5, "x", []]))
            else:
                hh.by_start[s] = rnd.choice([None, "junk"])
    cut = datetime(2029, 12, 1, tzinfo=timezone.utc) + timedelta(days=rnd.uniform(-30, 60))
    power = rnd.choice(sd.LOAD_POWER_POLICIES)
    counter = rnd.choice(sd.LOAD_COUNTER_POLICIES)
    ref = "REC-20300101-check" if rnd.random() < 0.8 else None
    ds = sd.DecisionSet().with_decision("D8", sd.HD1Cutover(cut, power, counter, ref), sd.Provenance.SYNTHETIC_TEST)
    acc = rnd.choice([h.SYN, h.SYN, sd.DEFAULT_ACCEPT_PROVENANCE, frozenset(), 5, None])
    now = cf.NOW + timedelta(hours=rnd.uniform(-48, 2))
    try:
        out, findings = q.prepare_history(hh, ds, now, accept_provenance=acc)
    except Exception as exc:  # noqa: BLE001
        praised.append((i, type(exc).__name__, str(exc)[:80]))
        continue
    if out is None:
        continue
    if not (sd.satisfied(ds.get("D8"), acc if isinstance(acc, frozenset) else ())):
        pbad.append((i, "a history returned without a satisfied I-D8"))
        continue
    cut_ts = int(cut.timestamp())
    for s, r in out.by_start.items():
        if s + 3600 > now.timestamp() or r.start + 3600 > now.timestamp() or r.start != s:
            pbad.append((i, "an hour that had not ended"))
            break
        if s < cut_ts and power == sd.EXCLUDE and r.load_w_mean is not None:
            pbad.append((i, "pre-cut-over load power kept under EXCLUDE"))
            break
        if s < cut_ts and counter == sd.EXCLUDE_PRE_CUTOVER and "load" in r.e:
            pbad.append((i, "pre-cut-over load counter kept under EXCLUDE_PRE_CUTOVER"))
            break
        if (s < cut_ts and counter == sd.KEEP_AFTER_COUNTER_CHECK and "load" in r.e
                and r.sources.get("load") != "power_integral" and not counter_check_passes(r)):
            pbad.append((i, "a pre-cut-over load counter kept without a passing counter check"))
            break
        if any(not (isinstance(v, float) or isinstance(v, int)) or not math.isfinite(v) or v < 0 for v in r.e.values()):
            pbad.append((i, "a non-finite or negative energy kept"))
            break
check(f"prepare_history never raises on {PREPARE_CASES} cases (junk energies, flags and sources included)", not praised,
      str(praised[:3]))
check("... never returns an unended hour, never keeps what the recorded I-D8 policy removes (a pre-cut-over counter only "
      "when its check ran and passed), never keeps a bad energy", not pbad, str(pbad[:3]))
check("... and never modifies the History passed in",
      fingerprint(hist) == prints[id(hist)] and fingerprint(hist_cnt) == prints[id(hist_cnt)])

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all data-quality fuzz checks passed")
