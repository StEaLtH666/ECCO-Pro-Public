#!/usr/bin/env python3
"""Data quality (dq): a positive and a negative case for every rule of intelligence.quality (fictional 2030 data only).

CCR-DQ-1 has landed (at integration): the raw SOC, the inverter clock offset and the event table are I-D6 keys with no
default limit, so the synthetic I-D6 of the fixtures judges them under its own 300 s and the rules that need those readings
fresh are proved on the integrated code. [0b] checks the landed keys. _dq_helpers.simulate_ccr_dq1 does nothing on the
integrated code, and the strict branch of [0b] (written before CCR-DQ-1 landed) is kept as a historical record and never
runs.

  [0] the clean synthetic base; [0b] CCR-DQ-1 has landed: the three readings have I-D6 limits and the clean base raises
      no BLOCK
  [1] age re-verification and the caller's assessments (CALLER_FRESHNESS_DISAGREES and friends; a withheld input)
  [2] missing / UNRESOLVED required inputs (an UNRESOLVED limit always BLOCKs); the history dated by well-formed records
  [3] dongle liveness (missing BLOCKs every dongle-sourced item; stale; future); an old snapshot
  [3b] configuration-poll liveness (contract 13.3): stale (300 s), missing, invalid or future BLOCKs every charge-window
       item with CONFIG_LIVENESS_*; a configuration-poll reading is aged by the larger of the two liveness ages and
       needs both fresh; an I-D6 entry naming it is refused and the fixed bound still applies (A5); an item requiring a
       configuration-poll reading needs it too (A6); the overlay state is exactly NONE or ACTIVE; the TOU readings are
       judged
  [4] SOC: false zero (raw used / BLOCK without raw), zero while discharging, sources disagreeing, out of range
  [5] online flags without a timeout; inverter not healthy or not a bool
  [6] the live power balance: CT sign reversal, battery sign reversal, inconsistent; native-load false zero; negative load
  [7] supervision (the state and stable flag aged by the telemetry poll text: steady supervision is current while the
      poll text moves, old once it is frozen beyond the bound; the heartbeat keeps its own time); tariff and events
      presence and age; the charge window and the inverter clock offset
  [8] the I-D4 capacity band; SOC near protection; live inputs against the snapshot; malformed structure; plausibility;
      the date-scoped PV forecast
  [9] the history rules (flaps, gaps, coverage, stalls, catch-up, CT reversal incl. a recent onset, SOC false zero,
      clock-change nights, zero PV, malformed records)
  [10] prepare_history: I-D8 EXCLUDE / KEEP_NON_EXPORTING_ONLY / KEEP_AFTER_COUNTER_CHECK on a copy; false zeros after the
       cut-over; a reversed CT; the refusal codes; never raises
  [10b] the CT share rule counts only the hours in which import and export can be told apart, on both sides of the share
       and in every window: hours that balance only swapped but cannot be told apart never make a reversal (assess_inputs
       and prepare_history), a genuine reversal still fires in the history, lookback and recent windows with the counts it
       used as evidence, the minimum hours and the minimum share are inclusive, the minimum hours bound the told-apart
       hours that balance only swapped (not the told-apart hours, and never an hour that cannot be told apart), and the
       residual rule still counts every hour that balances only swapped
  [11] contract hygiene over every scenario: no number with a unit in any text, only declared inputs block, valid input-age
       rows, run_cycle never fails its self-test on these inputs; every code quality.py emits is named in this suite
"""

from __future__ import annotations

import ast
import re
import copy as _copy
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _dq_helpers as h  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import faults  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.history import History, HourRecord  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402

FAILURES: list[str] = []
SCENARIOS: list[tuple[str, object]] = []        # every assessed input, for the hygiene checks in [11]


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def A(name: str, inp):
    """assess and remember the scenario"""
    SCENARIOS.append((name, inp))
    return q.assess_inputs(inp)


EXPORT = ("export_event", "dump_to_grid")
SOC_ITEMS = q.SOC_ITEMS
WINDOW = tuple(i for i in sd.ITEMS if i in sd.CHARGE_WINDOW_ITEMS)
SNAP_ITEMS = tuple(i for i in sd.ITEMS if any(s != "history.hourly" for s in sd.REQUIRED_SIGNALS[i]))
HISTORY_ONLY = tuple(i for i in sd.ITEMS if i not in SNAP_ITEMS)
base = h.clean()

print("== [0b] CCR-DQ-1 has landed (I-D6 keys, no default limit)" if h.CCR_DQ1_LANDED
      else "== [0b] strict until CCR-DQ-1 lands (the shipped behaviour)")
h.simulate_ccr_dq1(False)
qs = q.assess_inputs(base)
lim_s = sd.freshness_limits(cf.synthetic_decisions(), h.SYN)[0]
# historical: CCR-DQ-1 landed at integration, so this strict branch never runs on the integrated code (kept as a record)
if not h.CCR_DQ1_LANDED:
    check("the raw SOC, the clock offset and the event table have no limit: UNRESOLVED, never fresh",
          all(lim_s.get(k) is None and not qs.ages[k].fresh and qs.ages[k].limit_s is None for k in q.QUALIFYING_READING_KEYS))
    check("... so the clean base BLOCKs exactly CHARGE_WINDOW_CLOCK_UNKNOWN on every charge-window item and "
          "TARIFF_EVENTS_NOT_FRESH on export_event, and nothing else",
          {(f.code, f.subject) for f in h.blocks(qs)} == {("CHARGE_WINDOW_CLOCK_UNKNOWN", i) for i in WINDOW}
          | {("TARIFF_EVENTS_NOT_FRESH", "export_event")} and qs.blocked_items == frozenset(WINDOW),
          str(sorted({(f.code, f.subject) for f in h.blocks(qs)})))
    check("... the history-only items stay unblocked", not (set(HISTORY_ONLY) & qs.blocked_items))
    fzs = q.assess_inputs(faults.soc_false_zero(base, 1))
    check("... a SOC false zero cannot be resolved by the raw SOC: SOC_FALSE_ZERO_UNRESOLVED on every SOC item",
          all("SOC_FALSE_ZERO_UNRESOLVED" in h.item_codes(fzs, i) for i in SOC_ITEMS)
          and "SOC_FALSE_ZERO_RAW_USED" not in h.codes(fzs))
    cos = q.assess_inputs(faults.with_reading(base, "inverter.clock_offset_s", value=0.0))
    check("... a TOU-derived window BLOCKs even with a zero clock offset (CHARGE_WINDOW_CLOCK_UNKNOWN)",
          all("CHARGE_WINDOW_CLOCK_UNKNOWN" in h.item_codes(cos, i) for i in WINDOW))
    check("... and the strict input-age rows stay valid envelope rows (limit None, status unknown)",
          all(set(x) == ac.INPUT_AGE_KEYS and ac._known_input(x["name"]) for x in qs.input_ages()))
else:
    check("CCR-DQ-1 has landed: the three readings have I-D6 limits and the clean base raises no BLOCK",
          all(lim_s.get(k) is not None for k in q.QUALIFYING_READING_KEYS) and not h.blocks(qs))
h.simulate_ccr_dq1(True)

qb = A("clean", base)
print("== [0] the clean synthetic base" + (" (CCR-DQ-1 landed)" if h.CCR_DQ1_LANDED else " (CCR-DQ-1 simulated)"))
check("clean synthetic fixture: no BLOCK finding at all, nothing blocked", not h.blocks(qb) and not qb.blocked_items,
      str([(f.code, f.subject) for f in h.blocks(qb)][:5]))
check("... the only WARNs are the charge window from the TOU table", h.codes(qb, "WARN") == {"CHARGE_WINDOW_FROM_TOU_TABLE"},
      str(h.codes(qb, "WARN")))
_tou_texts = {f.text for f in qb.findings if f.code == "CHARGE_WINDOW_FROM_TOU_TABLE"}
check("... whose text names the TOU slot table as the window's source and a verified tariff as a cross-check only "
      "(never 'unless a verified tariff checks it', which read as if a tariff could set the window; A30, A50)",
      _tou_texts == {"the charge window comes from the read-only TOU slot table; a verified tariff only cross-checks it"},
      str(_tou_texts))
check("... every required input is fresh", all(qb.ages[k].fresh for i in sd.ITEMS
                                               for k in sd.required_inputs(i, cf.synthetic_decisions(), h.SYN).signals))
check("... and the three CCR-DQ-1 readings are fresh under "
      + ("the synthetic I-D6's own limit (CCR-DQ-1 landed)" if h.CCR_DQ1_LANDED else "the simulated limit"),
      all(qb.ages[k].fresh and qb.ages[k].limit_s == h.CCR_DQ1_LIMIT_S for k in q.QUALIFYING_READING_KEYS),
      str({k: (qb.ages[k].fresh, qb.ages[k].limit_s) for k in q.QUALIFYING_READING_KEYS}))

print("== [1] age re-verification and caller assessments")
sl = A("stale_liveness", cf.cycle_inputs(stale_liveness=True, synthetic_recorded=True))
check("CALLER_FRESHNESS_DISAGREES: caller says battery.soc fresh, liveness stale -> BLOCK, data quality BLOCKED, all blocked",
      "CALLER_FRESHNESS_DISAGREES" in h.codes(sl, "BLOCK") and sl.data_quality == "BLOCKED" and sl.blocked_items == frozenset(sd.ITEMS))
check("... negative: the clean caller agrees -> no disagreement", "CALLER_FRESHNESS_DISAGREES" not in h.codes(qb))
check("... the recomputed age comes from the liveness time, not from the observation (which looks recent)",
      sl.ages["battery.soc"].age_s is not None and sl.ages["battery.soc"].age_s > 7000 and not sl.ages["battery.soc"].fresh)
mal = A("caller_malformed", replace(base, caller_assessments=(("battery.soc", "yes", 3.0),)))
check("CALLER_ASSESSMENT_MALFORMED -> BLOCKED", "CALLER_ASSESSMENT_MALFORMED" in h.codes(mal) and mal.data_quality == "BLOCKED")
inc = A("caller_inconsistent", replace(base, caller_assessments=(("battery.soc", True, None),)))
check("CALLER_ASSESSMENT_INCONSISTENT: fresh without a usable age -> BLOCKED",
      "CALLER_ASSESSMENT_INCONSISTENT" in h.codes(inc) and inc.data_quality == "BLOCKED")
inc2 = A("caller_age_nan", replace(base, caller_assessments=(("battery.soc", True, float("nan")),)))
check("... a NaN caller age as well", "CALLER_ASSESSMENT_INCONSISTENT" in h.codes(inc2))
con = A("caller_conflict", replace(base, caller_assessments=(("battery.soc", True, 20.0), ("battery.soc", False, 20.0))))
check("CALLER_ASSESSMENT_CONFLICT: one input assessed fresh and not fresh -> BLOCKED", "CALLER_ASSESSMENT_CONFLICT" in h.codes(con))
unk = A("caller_unknown", replace(base, caller_assessments=(("pv.string_power.x", True, 1.0),)))
check("a caller-fresh signal quality cannot see -> CALLER_FRESHNESS_DISAGREES, and no unknown name enters the ages",
      "CALLER_FRESHNESS_DISAGREES" in h.codes(unk) and "pv.string_power.x" not in unk.ages)
cons = A("caller_conservative", replace(base, caller_assessments=(("battery.soc", False, 20.0),)))
check("CALLER_JUDGED_NOT_FRESH on a dongle-sourced input (the caller ages it from its last change, the liveness shows "
      "it current): INFO only, no BLOCK", "CALLER_JUDGED_NOT_FRESH" in h.codes(cons, "INFO") and not h.blocks(cons))
wh = A("caller_withheld_history", replace(base, caller_assessments=(("history.hourly", False, 3000.0),)))
check("CALLER_JUDGED_NOT_FRESH on a non-dongle input (the history): WARN, the input is not used, every item requiring it "
      "BLOCKs INPUT_NOT_FRESH (reason caller_withheld)",
      "CALLER_JUDGED_NOT_FRESH" in h.codes(wh, "WARN") and not wh.ages["history.hourly"].fresh
      and all(any(f.code == "INPUT_NOT_FRESH" and f.subject == i and dict(f.evidence).get("reason") == "caller_withheld"
                  for f in wh.findings) for i in q.HISTORY_ITEMS))
d1h = h.decisions_with("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True))
rbase = cf.cycle_inputs(decisions=d1h, accept_provenance=h.SYN)
rw = A("caller_withheld_reserve", replace(rbase, caller_assessments=tuple(
    (s, False if s == "reserve.ha_minimum_soc" else f, a) for s, f, a in rbase.caller_assessments)))
reserve_items = [i for i in sd.ITEMS if "reserve.ha_minimum_soc" in sd.required_inputs(i, d1h, h.SYN).signals]
check("... the reserve helper withheld by the caller under I-D1 HA_RESERVE_HELPER: its items BLOCKED",
      reserve_items and all(i in rw.blocked_items for i in reserve_items) and "CALLER_JUDGED_NOT_FRESH" in h.codes(rw, "WARN"))
rok = A("reserve_helper_clean", rbase)
check("... negative: the same inputs with the caller agreeing raise no BLOCK", not h.blocks(rok), str(h.codes(rok, "BLOCK")))
fut = A("signal_future", faults.with_signals(base, observed_at={"reserve.ha_minimum_soc": base.now + timedelta(hours=1)}))
check("an observation in the future is not fresh (age unknown)", fut.ages.get("reserve.ha_minimum_soc") is None
      or not fut.ages["reserve.ha_minimum_soc"].fresh)
fut2 = A("soc_future", faults.with_signals(base, observed_at={"battery.soc": base.now + timedelta(minutes=5)}))
check("... a dongle signal observed in the future: not fresh, its items BLOCK INPUT_NOT_FRESH with reason future",
      not fut2.ages["battery.soc"].fresh and any(f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("reason") == "future"
                                                 for f in fut2.findings))

print("== [2] missing and UNRESOLVED required inputs")
m = A("missing_limit", faults.with_reading(base, "limits.max_grid_charge_w", drop=True))
check("a missing required reading BLOCKs every item that requires it (INPUT_NOT_FRESH, reason missing)",
      all(i in m.blocked_items and "INPUT_NOT_FRESH" in h.item_codes(m, i)
          for i in sd.ITEMS if "limits.max_grid_charge_w" in sd.REQUIRED_READINGS[i])
      and "pv_tomorrow" not in m.blocked_items)
check("... negative: present and fresh in the clean base", qb.ages["limits.max_grid_charge_w"].fresh)
openq = A("all_open", cf.cycle_inputs())
unresolved = [k for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k, None) is None]
check("all OPEN: every required input with an UNRESOLVED limit BLOCKs its items (reason limit_unresolved)",
      all(any(f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("input") == k
              and dict(f.evidence).get("reason") == "limit_unresolved" for f in openq.findings)
          for i in sd.ITEMS for k in sd.required_inputs(i, sd.DecisionSet()).signals + sd.required_inputs(i, sd.DecisionSet()).readings
          if k in unresolved and k != sd.LIVENESS_KEY))
for key in ("house.power", "inverter.healthy", "tariff.export_rates", "limits.max_grid_charge_w", "stop.dump_soc_pct"):
    lim = {k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None and k != key}
    ds = h.decisions_with("D6", sd.FreshnessOverrides(lim))
    r = A(f"unresolved_{key}", cf.cycle_inputs(decisions=ds, accept_provenance=h.SYN))
    items = [i for i in sd.ITEMS if key in sd.REQUIRED_SIGNALS[i] + sd.REQUIRED_READINGS[i]]
    check(f"an UNRESOLVED limit always BLOCKs: I-D6 without {key} -> {items} BLOCKED",
          items and all(i in r.blocked_items for i in items) and r.ages[key].limit_s is None and not r.ages[key].fresh)
nofact = A("no_pv_kwp", replace(base, site_facts=ac.SiteFacts(pv_array_kwp=None, tz="Europe/London")))
check("SITE_FACT_MISSING: no pv_array_kwp -> pv_tomorrow BLOCKED", "SITE_FACT_MISSING" in h.item_codes(nofact, "pv_tomorrow"))
nohist = A("no_history", replace(base, history=None))
check("no history -> every item BLOCKED (history.hourly missing)", nohist.blocked_items == frozenset(sd.ITEMS))
old = A("old_history", replace(base, history=base.history.truncated(base.now - timedelta(hours=7))))
check("history older than its limit -> every item BLOCKED", old.blocked_items == frozenset(sd.ITEMS)
      and old.ages["history.hourly"].age_s > 6 * 3600)
futh = History(list(base.history.by_start.values()))
last = max(futh.by_start)
futh.by_start[last + 7200] = HourRecord(start=last + 7200, e={"load": 1.0, "pv": 0.0})
fh = A("future_history_hour", replace(base, history=futh))
check("a history hour from the future -> history not trusted, every item BLOCKED", fh.blocked_items == frozenset(sd.ITEMS))
stale_h = base.history.truncated(base.now - timedelta(hours=12))
last_ended = int(base.now.timestamp()) - int(base.now.timestamp()) % 3600 - 3600
for label, junk in (("a junk string", "junk"), ("None", None), ("a record filed under another hour",
                                                                  HourRecord(start=last_ended - 7 * 3600, e={"load": 1.0})),
                    ("a record without a finite energy", HourRecord(start=last_ended, e={"load": float("nan")})),
                    ("a record with malformed flags", HourRecord(start=last_ended, e={"load": 1.0}, flags=None))):
    jh = History()
    jh.by_start = dict(stale_h.by_start)
    jh.by_start[last_ended] = junk
    jr = A(f"stale_history_junk_{label}", replace(base, history=jh))
    check(f"a 12 h old history with {label} filed under the newest key is still 12 h old: every item BLOCKED",
          jr.blocked_items == frozenset(sd.ITEMS) and not jr.ages["history.hourly"].fresh
          and jr.ages["history.hourly"].age_s == 12 * 3600)
    check(f"... and HISTORY_RECORD_MALFORMED (WARN) counts it ({label})",
          ("HISTORY_RECORD_MALFORMED" in h.codes(jr, "WARN")) == (not isinstance(junk, HourRecord) or junk.start != last_ended
                                                                   or junk.flags is None))
check("... negative: the clean history has no malformed record", "HISTORY_RECORD_MALFORMED" not in h.codes(qb))
wf = History()
wf.by_start = dict(stale_h.by_start)
wf.by_start.update({last_ended: "junk", last_ended + 3600: None, last_ended + 7200: HourRecord(start=last_ended, e={"load": 1.0}),
                    last_ended + 10800: HourRecord(start=last_ended + 10800, e={"load": 1.0}, flags=None)})
wfr = q.well_formed_records(wf)
check("well_formed_records (the planner's public view of the history) is exactly the records the rules judge, junk dropped",
      wfr == q._records(wf) and set(wfr) == set(stale_h.by_start) and all(isinstance(r, HourRecord) for r in wfr.values()),
      str(sorted(set(wf.by_start) - set(wfr))))
SCSRC = (h.ROOT / "intelligence" / "shadow_cycle.py").read_text(encoding="utf-8")
priv = sorted(a.name for n in ast.walk(ast.parse(SCSRC)) if isinstance(n, ast.ImportFrom) and (n.module or "").endswith("quality")
              for a in n.names if a.name.startswith("_"))
check("the plan body imports no private name from quality (it uses well_formed_records, review INT-9)", not priv, str(priv))

print("== [3] dongle liveness")
nl = A("no_liveness", replace(faults.with_reading(base, sd.LIVENESS_KEY, drop=True), caller_assessments=()))
nlc = A("no_liveness_caller_fresh", faults.with_reading(base, sd.LIVENESS_KEY, drop=True))
check("a missing liveness reading while the caller still calls the SOC fresh: CALLER_FRESHNESS_DISAGREES, everything BLOCKED",
      "CALLER_FRESHNESS_DISAGREES" in h.codes(nlc) and nlc.blocked_items == frozenset(sd.ITEMS))
dongle_items = [i for i in sd.ITEMS if sd.LIVENESS_KEY in sd.required_inputs(i, cf.synthetic_decisions(), h.SYN).readings]
check("LIVENESS_MISSING BLOCKs every dongle-sourced item", "LIVENESS_MISSING" in h.codes(nl, "BLOCK") and dongle_items
      and all(i in nl.blocked_items for i in dongle_items), str(sorted(nl.blocked_items)))
check("... and only those (history-only items stay unblocked)",
      not ({"overnight_demand", "predicted_day_load", "pv_tomorrow"} & nl.blocked_items))
check("... every dongle-sourced input is then not fresh", all(not nl.ages[s].fresh for s in sd.DONGLE_SIGNALS if s in nl.ages))
st = A("frozen_poll", faults.frozen_poll_text(base, 3))
check("LIVENESS_STALE: poll text older than the PROPOSED bound -> dongle items BLOCKED", "LIVENESS_STALE" in h.codes(st)
      and all(i in st.blocked_items for i in dongle_items))
edge = A("liveness_at_bound", faults.with_reading(base, sd.LIVENESS_KEY, value=base.now - timedelta(seconds=179),
                                                  observed_at=base.now - timedelta(seconds=179)))
check("... negative: a poll text just inside the bound is fresh: no LIVENESS_STALE and no dongle input stale; the only "
      "BLOCK is supervision on export and Dump (the supervision readings are aged by the poll text, beyond their bound)",
      "LIVENESS_STALE" not in h.codes(edge) and all(edge.ages[s].fresh for s in sd.DONGLE_SIGNALS if s in edge.ages)
      and {(f.code, f.subject) for f in h.blocks(edge)} == {("SUPERVISION_NOT_STABLE", i) for i in EXPORT},
      str(sorted({(f.code, f.subject) for f in h.blocks(edge)})))
edge89 = A("liveness_inside_supervision_bound", faults.with_reading(base, sd.LIVENESS_KEY, value=base.now - timedelta(seconds=89),
                                                                    observed_at=base.now - timedelta(seconds=89)))
check("... and a poll text inside the supervision bound as well raises no BLOCK at all", not h.blocks(edge89),
      str(h.codes(edge89, "BLOCK")))
lf = A("liveness_future", faults.with_reading(base, sd.LIVENESS_KEY, value=base.now + timedelta(seconds=30)))
check("LIVENESS_IN_FUTURE: a poll-text time after now -> treated as missing", "LIVENESS_IN_FUTURE" in h.codes(lf)
      and all(i in lf.blocked_items for i in dongle_items))
lnan = A("liveness_junk", faults.with_reading(base, sd.LIVENESS_KEY, value="2030-01-15T20:59:40+00:00"))
check("a liveness value that is not a datetime -> LIVENESS_MISSING", "LIVENESS_MISSING" in h.codes(lnan))
old_snap = faults.shift_snapshot(base, 7200.0)          # taken 2 h ago, the bridge's view rebuilt from it; liveness fresh
os_ = A("snapshot_old", replace(old_snap, caller_assessments=()))
check("SNAPSHOT_STALE: a snapshot taken 2 h before the cycle (fresh liveness) BLOCKs every item resting on it",
      all("SNAPSHOT_STALE" in h.item_codes(os_, i) for i in SNAP_ITEMS) and not (set(HISTORY_ONLY) & os_.blocked_items))
check("... and its dongle signals are as old as the snapshot, not the liveness reading",
      os_.ages["battery.soc"].age_s == 7200.0 and not os_.ages["battery.soc"].fresh)
osc = A("snapshot_old_caller", old_snap)
check("... the caller that judged the old snapshot from its own time disagrees: CALLER_FRESHNESS_DISAGREES, BLOCKED",
      "CALLER_FRESHNESS_DISAGREES" in h.codes(osc) and osc.data_quality == "BLOCKED")
ok_snap = A("snapshot_recent", faults.shift_snapshot(base, 60.0))
check("... negative: a snapshot one minute old (inside the PROPOSED bound) raises no BLOCK", not h.blocks(ok_snap),
      str(h.codes(ok_snap, "BLOCK")))

print("== [3b] configuration-poll liveness (contract 13.3; A4 300 s, A5, A6)")
CFG = sd.CONFIG_LIVENESS_KEY
CFG_POLL_AUX = [k for k in sd.CONFIG_POLL_READINGS if k in qb.ages]
NON_CFG_DONGLE = ("stop.dump_soc_pct", "inverter.clock_offset_s", "tou.overlay_state", "battery.soc_raw_pct")


def cfg_at(inp, age_s: float):
    t = inp.now - timedelta(seconds=age_s)
    return faults.with_reading(inp, CFG, value=t, observed_at=t)


def tele_at(inp, age_s: float):
    t = inp.now - timedelta(seconds=age_s)
    return faults.with_reading(inp, sd.LIVENESS_KEY, value=t, observed_at=t)


check("the bound is the PROPOSED 300 s (five polls: one late poll tolerated), a fixed detection constant",
      q.DQ_PROPOSED.config_liveness_max_age_s == 300.0 and q.DQ_PROPOSED.liveness_max_age_s == 180.0)
check("RULE_INPUTS names each configuration-poll liveness code with the configuration-poll liveness reading only",
      all(q.RULE_INPUTS[c] == (CFG,) for c in ("CONFIG_LIVENESS_MISSING", "CONFIG_LIVENESS_IN_FUTURE", "CONFIG_LIVENESS_STALE")))
check("the clean base: the configuration-poll liveness is judged fresh under its 300 s bound (an input-age row), every "
      "judged configuration-poll reading is aged by the larger of the two liveness ages (the fixture: 30 s against 20 s), "
      "and a dongle reading the configuration poll does not publish keeps the telemetry age",
      qb.ages[CFG].fresh and qb.ages[CFG].limit_s == 300.0 and qb.ages[CFG].age_s == cf.CONFIG_POLL_AGE_S
      and any(r["name"] == CFG and r["status"] == "fresh" for r in qb.input_ages())
      and set(CFG_POLL_AUX) == {"tou.slot_table", "tou.enabled", "tou.grid_charge_enabled", "protection.shutdown_soc_pct",
                                "capacity.reg204_ah"}
      and all(qb.ages[k].fresh and qb.ages[k].age_s == max(cf.POLL_AGE_S, cf.CONFIG_POLL_AGE_S) for k in CFG_POLL_AUX)
      and all(qb.ages[k].fresh and qb.ages[k].age_s == cf.POLL_AGE_S for k in NON_CFG_DONGLE),
      str({k: (qb.ages[k].age_s, qb.ages[k].fresh) for k in CFG_POLL_AUX + list(NON_CFG_DONGLE) if k in qb.ages}))
cst = A("config_poll_stale", cfg_at(base, 301))
check("CONFIG_LIVENESS_STALE: the configuration-poll text 301 s old while the telemetry poll text moves -> every "
      "charge-window item BLOCKED with the code (age and bound in the evidence, not the text)",
      all("CONFIG_LIVENESS_STALE" in h.item_codes(cst, i) for i in WINDOW)
      and all(dict(f.evidence).get("bound_s") == 300.0 and dict(f.evidence).get("age_s") == 301.0
              for f in cst.findings if f.code == "CONFIG_LIVENESS_STALE"),
      str(sorted(h.codes(cst, "BLOCK"))))
check("... the configuration-poll readings are stale (reason config_liveness), so the TOU table gives no window "
      "(CHARGE_WINDOW_UNKNOWN); the telemetry liveness, the dongle signals and the non-configuration dongle readings stay "
      "fresh (no LIVENESS_STALE)",
      all(not cst.ages[k].fresh for k in CFG_POLL_AUX) and all("CHARGE_WINDOW_UNKNOWN" in h.item_codes(cst, i) for i in WINDOW)
      and "LIVENESS_STALE" not in h.codes(cst) and all(cst.ages[k].fresh for k in NON_CFG_DONGLE)
      and all(cst.ages[s].fresh for s in sd.DONGLE_SIGNALS if s in cst.ages))
check("... only the items requiring the configuration-poll liveness are blocked: the history-only items stay unblocked",
      cst.blocked_items == frozenset(WINDOW), str(sorted(cst.blocked_items)))
cst_d2 = A("config_poll_stale_d2_sensor", cfg_at(cf.cycle_inputs(decisions=h.decisions_with(
    "D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT)), accept_provenance=h.SYN), 400))
check("... a required configuration-poll reading (I-D2 from the shutdown sensor) BLOCKs INPUT_NOT_FRESH with reason "
      "config_liveness", any(f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("input") == "protection.shutdown_soc_pct"
                             and dict(f.evidence).get("reason") == "config_liveness" for f in cst_d2.findings))
c299 = A("config_poll_inside_bound", cfg_at(base, 299))
check("... negative: the configuration-poll text 299 s old (inside the bound) raises no BLOCK, and the configuration-poll "
      "readings are aged 299 s", not h.blocks(c299) and all(c299.ages[k].age_s == 299.0 and c299.ages[k].fresh for k in CFG_POLL_AUX),
      str(h.codes(c299, "BLOCK")))
cmis = A("config_poll_missing", faults.with_reading(base, CFG, drop=True))
check("CONFIG_LIVENESS_MISSING: no configuration-poll liveness reading (live telemetry) -> every charge-window item "
      "BLOCKED (reason missing), the configuration-poll readings not fresh, the history-only items unblocked",
      all("CONFIG_LIVENESS_MISSING" in h.item_codes(cmis, i) for i in WINDOW) and cmis.blocked_items == frozenset(WINDOW)
      and all(dict(f.evidence).get("reason") == "missing" for f in cmis.findings if f.code == "CONFIG_LIVENESS_MISSING")
      and all(not cmis.ages[k].fresh and cmis.ages[k].age_s is None for k in CFG_POLL_AUX))
for label, val in (("a text", "2030-01-15T20:59:30+00:00"), ("a naive time", base.now.replace(tzinfo=None)), ("a number", 5.0)):
    cbad = A(f"config_poll_invalid_{label}", faults.with_reading(base, CFG, value=val))
    check(f"... a configuration-poll liveness value that is {label} -> CONFIG_LIVENESS_MISSING (reason invalid)",
          all("CONFIG_LIVENESS_MISSING" in h.item_codes(cbad, i) for i in WINDOW)
          and all(dict(f.evidence).get("reason") == "invalid" for f in cbad.findings if f.code == "CONFIG_LIVENESS_MISSING"))
cfut = A("config_poll_future", faults.with_reading(base, CFG, value=base.now + timedelta(seconds=30),
                                                    observed_at=base.now + timedelta(seconds=30)))
check("CONFIG_LIVENESS_IN_FUTURE: a configuration-poll change time after now -> every charge-window item BLOCKED",
      all("CONFIG_LIVENESS_IN_FUTURE" in h.item_codes(cfut, i) for i in WINDOW) and cfut.blocked_items == frozenset(WINDOW))
cfut2 = A("config_poll_observed_future", faults.with_reading(base, CFG, observed_at=base.now + timedelta(seconds=30)))
check("... also when only its observation time lies in the future", all("CONFIG_LIVENESS_IN_FUTURE" in h.item_codes(cfut2, i)
                                                                         for i in WINDOW))
cmin = A("config_poll_older_of_two", faults.with_reading(base, CFG, value=base.now - timedelta(seconds=310),
                                                          observed_at=base.now - timedelta(seconds=10)))
check("... the older of the change time and its observation counts (a change time 310 s old observed 10 s ago is stale)",
      all("CONFIG_LIVENESS_STALE" in h.item_codes(cmin, i) for i in WINDOW))
tst = A("telemetry_stale_config_fresh", replace(tele_at(cf.cycle_inputs(decisions=h.decisions_with(
    "D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT)), accept_provenance=h.SYN), 200), caller_assessments=()))
check("telemetry liveness stale while the configuration poll is fresh: the configuration-poll readings are not fresh either "
      "(a required one BLOCKs INPUT_NOT_FRESH with reason liveness: the telemetry rule still applies), no CONFIG_LIVENESS_* "
      "code",
      all(not tst.ages[k].fresh for k in CFG_POLL_AUX) and tst.ages[CFG].fresh
      and any(f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("input") == "protection.shutdown_soc_pct"
              and dict(f.evidence).get("reason") == "liveness" for f in tst.findings)
      and not any(c.startswith("CONFIG_LIVENESS_") for c in h.codes(tst)))
d6tou = h.decisions_with("D6", sd.FreshnessOverrides({**{k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS
                                                         if sd.ADVISORY_LIMITS_S.get(k) is None}, "tou.slot_table": 200.0}))
mx1 = A("config_age_max_config_older", cfg_at(cf.cycle_inputs(decisions=d6tou, accept_provenance=h.SYN), 250))
check("the larger of the two ages counts against the reading's own I-D6 limit: a TOU table with a 200 s limit and a "
      "configuration poll 250 s old (inside its own bound) is stale (reason stale) -> CHARGE_WINDOW_UNKNOWN, no "
      "CONFIG_LIVENESS_* code",
      mx1.ages["tou.slot_table"].age_s == 250.0 and not mx1.ages["tou.slot_table"].fresh and mx1.ages[CFG].fresh
      and all("CHARGE_WINDOW_UNKNOWN" in h.item_codes(mx1, i) for i in WINDOW)
      and not any(c.startswith("CONFIG_LIVENESS_") for c in h.codes(mx1)))
mx2 = A("config_age_max_telemetry_older", replace(tele_at(cf.cycle_inputs(decisions=d6tou, accept_provenance=h.SYN), 170),
                                                   caller_assessments=()))
check("... and the other way round: telemetry 170 s, configuration poll 30 s -> the table is aged 170 s (fresh under 200 s)",
      mx2.ages["tou.slot_table"].age_s == 170.0 and mx2.ages["tou.slot_table"].fresh)
mx3 = A("config_age_max_negative", cfg_at(cf.cycle_inputs(decisions=d6tou, accept_provenance=h.SYN), 190))
check("... negative: configuration poll 190 s against the table's 200 s limit: fresh", mx3.ages["tou.slot_table"].fresh
      and "CHARGE_WINDOW_UNKNOWN" not in h.codes(mx3))
d6long = h.decisions_with("D6", sd.FreshnessOverrides({**{k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS
                                                          if sd.ADVISORY_LIMITS_S.get(k) is None},
                                                       "tou.slot_table": 900.0, "protection.shutdown_soc_pct": 900.0}),
                          h.decisions_with("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT)))
lng = A("config_poll_stale_long_id6", cfg_at(cf.cycle_inputs(decisions=d6long, accept_provenance=h.SYN), 400))
check("the configuration-poll bound binds whatever the reading's own I-D6 limit: with 900 s for the TOU table and the "
      "shutdown level, a configuration poll 400 s old leaves both not fresh (a required one BLOCKs with reason "
      "config_liveness) although their age is inside their limit",
      not lng.ages["tou.slot_table"].fresh and not lng.ages["protection.shutdown_soc_pct"].fresh
      and lng.ages["tou.slot_table"].age_s == 400.0
      and any(f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("input") == "protection.shutdown_soc_pct"
              and dict(f.evidence).get("reason") == "config_liveness" for f in lng.findings))
lng_ok = A("config_poll_fresh_long_id6", cfg_at(cf.cycle_inputs(decisions=d6long, accept_provenance=h.SYN), 280))
check("... negative: the same with the configuration poll 280 s old: both fresh, no BLOCK",
      lng_ok.ages["tou.slot_table"].fresh and lng_ok.ages["protection.shutdown_soc_pct"].fresh and not h.blocks(lng_ok),
      str(h.codes(lng_ok, "BLOCK")))
# the cycle's validity rule takes the item's required inputs, so a charge-window item is never valid beyond the
# configuration-poll bound minus the poll text's age (the planning layer's own rule, WP-2, may only shorten it)
vu_fail = []
for cage in (30.0, 150.0, 250.0):
    env_c = run_cycle(cfg_at(base, cage))
    views = {v.key: v for v in tuple(env_c.items) + tuple(env_c.forecasts)}
    for i in WINDOW:
        v = views.get(i)
        if v is not None and v.status == "OK" and (v.valid_until is None
                                                   or (v.valid_until - base.now).total_seconds() > 300.0 - cage + 1e-6):
            vu_fail.append((cage, i, None if v.valid_until is None else (v.valid_until - base.now).total_seconds()))
    if cage == 150.0:
        ct150 = views.get("charge_target")
check("no OK charge-window item is valid beyond the configuration-poll bound minus the poll text's age (30, 150 and 250 s "
      "old), and at 150 s charge_target is OK and valid for exactly the 150 s left (non-vacuous)",
      not vu_fail and ct150 is not None and ct150.status == "OK"
      and (ct150.valid_until - base.now).total_seconds() == 150.0,
      str(vu_fail[:3]) + " " + str(None if ct150 is None else (ct150.status, ct150.valid_until)))
d6cfg = h.decisions_with("D6", sd.FreshnessOverrides({**{k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS
                                                         if sd.ADVISORY_LIMITS_S.get(k) is None}, CFG: 900.0}))
a5 = A("config_liveness_id6_refused", cfg_at(cf.cycle_inputs(decisions=d6cfg, accept_provenance=h.SYN), 400))
check("A5: an I-D6 entry naming the configuration-poll liveness is refused (I-D6 INVALID, nothing applied, BLOCK) and the "
      "fixed 300 s bound still applies (CONFIG_LIVENESS_STALE at 400 s)",
      d6cfg.status("D6") == "INVALID" and "FRESHNESS_OVERRIDE_UNKNOWN_KEY" in h.codes(a5, "BLOCK")
      and "DECISION_D6_INVALID" in h.codes(a5, "BLOCK") and a5.ages[CFG].limit_s == 300.0
      and all("CONFIG_LIVENESS_STALE" in h.item_codes(a5, i) for i in WINDOW))
add7 = h.decisions_with("D7", sd.RequiredInputsOverride({}, {"pv_tomorrow": ("capacity.reg204_ah",)}))
a6 = A("config_reading_required_by_d7", cfg_at(cf.cycle_inputs(decisions=add7, accept_provenance=h.SYN), 400))
check("A6: an item that is not a charge-window item but requires a configuration-poll reading (an I-D7 adds the Ah "
      "register to pv_tomorrow) BLOCKs on a stale configuration poll too",
      "CONFIG_LIVENESS_STALE" in h.item_codes(a6, "pv_tomorrow") and "INPUT_NOT_FRESH" in h.item_codes(a6, "pv_tomorrow"))
a6n = A("config_reading_required_by_d7_fresh", cf.cycle_inputs(decisions=add7, accept_provenance=h.SYN))
check("... negative: the same with the configuration poll fresh leaves pv_tomorrow unblocked", "pv_tomorrow" not in a6n.blocked_items,
      str(h.item_codes(a6n, "pv_tomorrow")))
for v, ok in (("NONE", True), ("ACTIVE", True), ("none", False), ("ON", False), ("", False)):
    ov = A(f"overlay_{v or 'empty'}", faults.with_reading(base, "tou.overlay_state", value=v))
    check(f"tou.overlay_state {v!r}: " + ("a valid reading, judged fresh (telemetry age)" if ok else
                                         "READING_INVALID (exactly NONE or ACTIVE), not used"),
          (ov.ages["tou.overlay_state"].fresh and ov.ages["tou.overlay_state"].value == v
           and ov.ages["tou.overlay_state"].age_s == cf.POLL_AGE_S) if ok else
          ("READING_INVALID" in h.codes(ov, "WARN") and ov.ages["tou.overlay_state"].value is None
           and not ov.ages["tou.overlay_state"].fresh))
check("the TOU readings the grid-charge classification needs are judged whatever the decisions say (input-age rows after "
      "the required inputs): both enables and the overlay are in the ages of the all-OPEN run as well; the current TOU "
      "target stays the planning layer's own judgement (not judged here)",
      all(k in openq.ages and k in qb.ages for k in ("tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state"))
      and "tou.current_target_soc_pct" not in qb.ages)
cst_en = A("config_poll_stale_enables", cfg_at(base, 400))
check("... and judged with the configuration-poll ageing: a configuration poll 400 s old leaves both enables not fresh "
      "while the overlay (telemetry) stays fresh",
      not cst_en.ages["tou.enabled"].fresh and not cst_en.ages["tou.grid_charge_enabled"].fresh
      and cst_en.ages["tou.overlay_state"].fresh)
check("the fault injectors name the contract's configuration-poll liveness key", faults.CONFIG_LIVENESS_KEY == CFG)

print("== [4] SOC")
fz = A("soc_false_zero", faults.soc_false_zero(base, 1))
check("SOC false zero with a fresh raw SOC: WARN SOC_FALSE_ZERO_RAW_USED and the raw value is the judged SOC",
      "SOC_FALSE_ZERO_RAW_USED" in h.codes(fz, "WARN") and fz.ages["battery.soc"].value > 0 and fz.ages["battery.soc"].fresh
      and not (set(SOC_ITEMS) & fz.blocked_items))
fzn = A("soc_false_zero_no_raw", faults.soc_false_zero_no_raw(base, 0))
check("SOC false zero without a usable raw SOC: BLOCK SOC_FALSE_ZERO_UNRESOLVED on every SOC item",
      all("SOC_FALSE_ZERO_UNRESOLVED" in h.item_codes(fzn, i) for i in SOC_ITEMS))
fzn2 = A("soc_false_zero_raw_nan", faults.soc_false_zero_no_raw(base, 1))
check("... also when the raw reading is NaN", all(i in fzn2.blocked_items for i in SOC_ITEMS)
      and "SOC_FALSE_ZERO_UNRESOLVED" in h.codes(fzn2))
z0 = A("soc_true_zero_idle", faults.with_reading(faults.with_signals(base, {"battery.soc": 0.0, "battery.power": 0.0,
                                                                            "grid.power": 450.0}), "battery.soc_raw_pct", value=0.0))
check("negative: canonical and raw both zero with the battery idle -> no false-zero finding",
      not ({"SOC_FALSE_ZERO_UNRESOLVED", "SOC_FALSE_ZERO_RAW_USED", "SOC_ZERO_WHILE_DISCHARGING"} & h.codes(z0)))
zd = A("soc_zero_discharging", faults.with_reading(faults.with_signals(base, {"battery.soc": 0.0}), "battery.soc_raw_pct", value=0.0))
check("SOC zero while the battery discharges -> BLOCK SOC_ZERO_WHILE_DISCHARGING", all(
    "SOC_ZERO_WHILE_DISCHARGING" in h.item_codes(zd, i) for i in SOC_ITEMS))
dis = A("soc_disagree", faults.soc_disagree(base, 2))
check("SOC_SOURCES_DISAGREE: canonical and raw differ beyond the tolerance -> SOC items BLOCKED",
      all("SOC_SOURCES_DISAGREE" in h.item_codes(dis, i) for i in SOC_ITEMS))
agr = A("soc_agree_at_tolerance", faults.with_reading(base, "battery.soc_raw_pct", value=57.0))
check("... negative: a difference of the tolerance (two points) passes", "SOC_SOURCES_DISAGREE" not in h.codes(agr))
oor = A("soc_out_of_range", faults.with_signals(base, {"battery.soc": 140.0}))
check("SOC_OUT_OF_RANGE: a SOC above 100 -> SOC items BLOCKED", all("SOC_OUT_OF_RANGE" in h.item_codes(oor, i) for i in SOC_ITEMS))
oorr = A("soc_raw_out_of_range", faults.with_reading(faults.with_signals(base, {"battery.soc": 0.0}), "battery.soc_raw_pct",
                                                     value=140.0))
check("SOC_OUT_OF_RANGE: canonical zero with a raw SOC of 140 -> every SOC item BLOCKED (the raw value is never used)",
      all("SOC_OUT_OF_RANGE" in h.item_codes(oorr, i) for i in SOC_ITEMS) and "SOC_FALSE_ZERO_RAW_USED" not in h.codes(oorr))
oorr2 = A("soc_raw_out_of_range_mid", faults.with_reading(base, "battery.soc_raw_pct", value=-3.0))
check("... and a negative raw SOC beside a normal canonical one as well",
      all("SOC_OUT_OF_RANGE" in h.item_codes(oorr2, i) for i in SOC_ITEMS))
check("... negative: the fixture's agreeing SOCs are in range", "SOC_OUT_OF_RANGE" not in h.codes(qb))

print("== [5] online flags and inverter health")
of = A("online_flag", faults.online_flag_stale(base, 0))
check("ONLINE_FLAG_UNCONFIRMED: inverter healthy while liveness is stale -> export and Dump BLOCKED",
      all("ONLINE_FLAG_UNCONFIRMED" in h.item_codes(of, i) for i in EXPORT))
tel = A("online_flag_telemetry", h.add_observation(faults.frozen_poll_text(base, 0), "controller.telemetry", True))
check("... a controller telemetry flag reading on while liveness is stale: WARN, treated as stale",
      any(f.code == "ONLINE_FLAG_UNCONFIRMED" and f.subject == "controller.telemetry" and f.severity == "WARN" for f in tel.findings)
      and not tel.ages["controller.telemetry"].fresh)
tel2 = A("online_flag_telemetry_fresh", h.add_observation(base, "controller.telemetry", True))
check("... negative: with fresh liveness the flags raise nothing", "ONLINE_FLAG_UNCONFIRMED" not in h.codes(tel2) and not h.blocks(tel2))
nh = A("inverter_unhealthy", faults.with_signals(base, {"inverter.healthy": False}))
check("INVERTER_NOT_HEALTHY: export and Dump BLOCKED; charge_target not", all("INVERTER_NOT_HEALTHY" in h.item_codes(nh, i) for i in EXPORT)
      and "charge_target" not in nh.blocked_items)
check("... negative: a healthy inverter with fresh liveness passes", "INVERTER_NOT_HEALTHY" not in h.codes(qb))
nb = A("inverter_not_bool", replace(faults.with_signals(base, {"inverter.healthy": "unavailable"}), caller_assessments=()))
check("inverter.healthy that is not a bool ('unavailable'): not fresh (reason invalid), export and Dump BLOCKED, "
      "charge_target not", all(any(f.code == "INPUT_NOT_FRESH" and f.subject == i and dict(f.evidence).get("input") ==
                                   "inverter.healthy" and dict(f.evidence).get("reason") == "invalid" for f in nb.findings)
                               for i in EXPORT) and "charge_target" not in nb.blocked_items)

print("== [6] the live power balance")
ct = A("ct_reversal", faults.ct_reversal(base, 4))
check("CT_SIGN_REVERSED: the balance fits only with the grid sign flipped -> export and Dump BLOCKED",
      all("CT_SIGN_REVERSED" in h.item_codes(ct, i) for i in EXPORT) and "charge_target" not in ct.blocked_items)
bal = A("balanced", faults.with_signals(base, {"house.power": 900.0, "pv.power": 300.0, "battery.power": 500.0, "grid.power": 100.0}))
check("... negative: a balanced set raises no balance finding", not ({"CT_SIGN_REVERSED", "BATTERY_SIGN_REVERSED",
                                                                      "POWER_BALANCE_INCONSISTENT"} & h.codes(bal)))
check("... negative: the fixture's own set (residual at the tolerance) passes", not ({"CT_SIGN_REVERSED", "POWER_BALANCE_INCONSISTENT"}
                                                                                    & h.codes(qb)))
bs = A("battery_sign", faults.with_signals(base, {"house.power": 900.0, "pv.power": 2400.0, "battery.power": 1500.0, "grid.power": 0.0}))
check("BATTERY_SIGN_REVERSED: fits only with the battery sign flipped", "BATTERY_SIGN_REVERSED" in h.codes(bs, "BLOCK"))
inc_ = A("balance_inconsistent", faults.with_signals(base, {"house.power": 3000.0, "pv.power": 0.0, "battery.power": 0.0, "grid.power": 200.0}))
check("POWER_BALANCE_INCONSISTENT: fits neither way", "POWER_BALANCE_INCONSISTENT" in h.codes(inc_, "BLOCK"))
lz = A("load_false_zero", faults.load_false_zero(base, 1))
check("LOAD_FALSE_ZERO: native load zero while inverter + grid show a load -> export and Dump BLOCKED",
      all("LOAD_FALSE_ZERO" in h.item_codes(lz, i) for i in EXPORT))
lz0 = A("load_true_zero", faults.with_signals(base, {"house.power": 0.0, "pv.power": 0.0, "battery.power": 60.0, "grid.power": 0.0}))
check("... negative: a zero load that inverter + grid confirm (below the HD1 threshold) is not a false zero",
      "LOAD_FALSE_ZERO" not in h.codes(lz0))
neg = A("load_negative", faults.with_signals(base, {"house.power": -300.0}))
check("HOUSE_POWER_NEGATIVE: a negative house load is not credible -> export and Dump BLOCKED",
      all("HOUSE_POWER_NEGATIVE" in h.item_codes(neg, i) for i in EXPORT))

print("== [7] supervision, tariff and events, charge window and clock")
for seed in range(4):
    so = A(f"supervision_{seed}", faults.supervisor_outage(base, seed))
    check(f"SUPERVISION_NOT_STABLE (variant {seed}): export and Dump BLOCKED, a WARN for the rest, charge_target not blocked",
          all("SUPERVISION_NOT_STABLE" in h.item_codes(so, i) for i in EXPORT) and "charge_target" not in so.blocked_items
          and any(f.code == "SUPERVISION_NOT_STABLE" and f.severity == "WARN" for f in so.findings))
check("... negative: SUPERVISED, stable and a recent heartbeat raise nothing", "SUPERVISION_NOT_STABLE" not in h.codes(qb))
hb = A("heartbeat_effective", faults.with_reading(base, "supervision.heartbeat_age_s", value=70.0))
check("... the heartbeat's effective age is the reported age plus the reading's own age (here beyond the bound)",
      "SUPERVISION_NOT_STABLE" in h.codes(hb))
hb2 = A("heartbeat_ok", faults.with_reading(base, "supervision.heartbeat_age_s", value=50.0))
check("... and within the bound it passes", "SUPERVISION_NOT_STABLE" not in h.codes(hb2))
for key in ("supervision.state", "supervision.stable"):
    # the pair is published only when it changes (a dongle reading): its age is the telemetry poll text's, so a value
    # that last changed long ago is current while the poll text moves (the INT-2 fix; a loosening against the reading's
    # own time, bounded by the heartbeat rule) and old once the poll text is frozen beyond the supervision bound
    so_steady = A(f"supervision_steady_{key}", faults.with_reading(base, key, observed_at=base.now - timedelta(days=10)))
    check(f"... {key} last changed 10 days ago (SUPERVISED / stable) while the poll text keeps moving: current, export and "
          "Dump not blocked", "SUPERVISION_NOT_STABLE" not in h.codes(so_steady) and not h.blocks(so_steady),
          str(h.codes(so_steady, "BLOCK")))
    so_old = A(f"supervision_old_{key}", faults.with_reading(
        faults.with_reading(base, key, observed_at=base.now - timedelta(days=10)), sd.LIVENESS_KEY,
        value=base.now - timedelta(seconds=95), observed_at=base.now - timedelta(seconds=95)))
    check(f"... the same {key} with the poll text frozen 95 s (beyond the supervision bound, inside the liveness bound): "
          "not current, export and Dump BLOCKED, the rest only warned",
          all("SUPERVISION_NOT_STABLE" in h.item_codes(so_old, i) for i in EXPORT)
          and any(f"{key}:old" in dict(f.evidence).get("why", ()) for f in so_old.findings)
          and not (so_old.blocked_items - set(EXPORT)))
    so_nolive = A(f"supervision_no_liveness_{key}", replace(faults.with_reading(base, sd.LIVENESS_KEY, drop=True),
                                                             caller_assessments=()))
    check(f"... and with no liveness reading at all {key} has no age: old (export and Dump BLOCKED SUPERVISION_NOT_STABLE)",
          any(f"{key}:old" in dict(f.evidence).get("why", ()) for f in so_nolive.findings if f.code == "SUPERVISION_NOT_STABLE")
          and all("SUPERVISION_NOT_STABLE" in h.item_codes(so_nolive, i) for i in EXPORT))
for s in range(25):
    pf_ = A(f"supervision_poll_frozen_{s}", faults.supervision_poll_frozen(base, s))
    if not (all("SUPERVISION_NOT_STABLE" in h.item_codes(pf_, i) for i in EXPORT) and not (pf_.blocked_items - set(EXPORT))
            and "LIVENESS_STALE" not in h.codes(pf_)):
        check(f"supervision_poll_frozen seed {s}: only export and Dump BLOCKED SUPERVISION_NOT_STABLE", False,
              str(sorted({(f.code, f.subject) for f in h.blocks(pf_)})))
        break
else:
    check("the poll text frozen 91 to 179 s (25 seeds): supervision not current, only export and Dump BLOCKED (the dongle "
          "inputs stay fresh inside the liveness bound)", True)
hb_steady = A("heartbeat_frozen_supervision_steady", faults.with_reading(
    faults.with_reading(base, "supervision.state", observed_at=base.now - timedelta(days=10)),
    "supervision.heartbeat_age_s", observed_at=base.now - timedelta(seconds=600)))
check("... the loosening is bounded by the heartbeat: steady state and a heartbeat reading not re-published for 10 min "
      "(its own observation time, not the poll text's): export and Dump BLOCKED",
      all("SUPERVISION_NOT_STABLE" in h.item_codes(hb_steady, i) for i in EXPORT)
      and any("supervision.heartbeat_age_s:old" in dict(f.evidence).get("why", ()) for f in hb_steady.findings))
ev = A("events_missing", faults.with_reading(base, "tariff.events", drop=True))
check("TARIFF_EVENTS_NOT_FRESH: no event table -> export_event BLOCKED, Dump only warned",
      "TARIFF_EVENTS_NOT_FRESH" in h.item_codes(ev, "export_event") and "dump_to_grid" not in ev.blocked_items)
ev2 = A("events_stale", faults.with_reading(base, "tariff.events", observed_at=base.now - timedelta(hours=2)))
check("... a stale event table as well", "export_event" in ev2.blocked_items)
check("... negative: a fresh (empty) event table is present", "TARIFF_EVENTS_NOT_FRESH" not in h.codes(qb))
er = A("export_rates_empty", faults.with_reading(base, "tariff.export_rates", value=[]))
check("an empty export-rate table is not present -> export and Dump BLOCKED", all(i in er.blocked_items for i in EXPORT))
check("TARIFF_IMPORT_RATES_PRESENT (INFO) in the clean base; the content is the planning layer's", "TARIFF_IMPORT_RATES_PRESENT" in h.codes(qb, "INFO"))
ir = A("import_rates_stale", faults.with_reading(base, "tariff.import_rates", observed_at=base.now - timedelta(hours=3)))
check("TARIFF_IMPORT_RATES_NOT_FRESH: stale import rates -> WARN", "TARIFF_IMPORT_RATES_NOT_FRESH" in h.codes(ir, "WARN"))
window = [i for i in sd.ITEMS if i in sd.CHARGE_WINDOW_ITEMS]
nt = A("no_tou", faults.with_reading(base, "tou.slot_table", drop=True))
check("CHARGE_WINDOW_UNKNOWN: no TOU table and no verified tariff -> every charge-window item BLOCKED",
      all("CHARGE_WINDOW_UNKNOWN" in h.item_codes(nt, i) for i in window))
co = A("clock_offset", faults.clock_offset(base, 0))
check("CHARGE_WINDOW_CLOCK_OFFSET: inverter clock far off -> the TOU-derived window BLOCKs its items, with a WARN",
      all("CHARGE_WINDOW_CLOCK_OFFSET" in h.item_codes(co, i) for i in window) and "INVERTER_CLOCK_OFFSET" in h.codes(co, "WARN"))
for off in (31.0, 60.0, -119.9):
    cw = A(f"clock_offset_{off}", faults.with_reading(base, "inverter.clock_offset_s", value=off))
    check(f"INVERTER_CLOCK_OFFSET (WARN) and CHARGE_WINDOW_CLOCK_OFFSET (BLOCK): any offset beyond the warning bound ({off}) "
          "refuses a TOU-derived window", "INVERTER_CLOCK_OFFSET" in h.codes(cw, "WARN")
          and all("CHARGE_WINDOW_CLOCK_OFFSET" in h.item_codes(cw, i) for i in window))
cwn = A("clock_offset_inside", faults.with_reading(base, "inverter.clock_offset_s", value=-29.0))
check("... negative: an offset inside the bound raises nothing", not ({"INVERTER_CLOCK_OFFSET", "CHARGE_WINDOW_CLOCK_OFFSET"}
                                                                     & h.codes(cwn)) and not h.blocks(cwn))
check("... negative: the fixture's small offset raises nothing", "INVERTER_CLOCK_OFFSET" not in h.codes(qb))
cu = A("clock_unknown", faults.with_reading(base, "inverter.clock_offset_s", drop=True))
check("CHARGE_WINDOW_CLOCK_UNKNOWN: a TOU-derived window without a clock offset BLOCKs", all(
    "CHARGE_WINDOW_CLOCK_UNKNOWN" in h.item_codes(cu, i) for i in window))

print("== [8] capacity band, protection, live inputs, structure")
cap = A("capacity_conflict", faults.with_reading(base, "capacity.helper_kwh", value=30.0))
check("CAPACITY_SOURCES_CONFLICT: a helper far from the stated capacity beyond the recorded I-D4 band -> capacity items BLOCKED",
      all("CAPACITY_SOURCES_CONFLICT" in h.item_codes(cap, i) for i in sd.CONDITIONAL_D4_ITEMS))
check("... negative: the fixture's four sources agree within the band", "CAPACITY_SOURCES_CONFLICT" not in h.codes(qb))
d3nv = h.decisions_with("D3", sd.CapacityAuthority("CONFIGURED_HELPER", 20.0, False, None))
cu2 = A("capacity_unknown", cf.cycle_inputs(decisions=d3nv, accept_provenance=h.SYN))
check("CAPACITY_MISMATCH_UNKNOWN: an Ah source without a stated voltage", all(
    "CAPACITY_MISMATCH_UNKNOWN" in h.item_codes(cu2, i) for i in sd.CONDITIONAL_D4_ITEMS))
np_ = A("near_protection", faults.near_protection(base, 5))
check("SOC_NEAR_PROTECTION: SOC within the margin of the protection level -> export and Dump BLOCKED, charge_target not",
      all("SOC_NEAR_PROTECTION" in h.item_codes(np_, i) for i in EXPORT) and "charge_target" not in np_.blocked_items)
far = A("above_protection_margin", faults.with_reading(faults.with_signals(base, {"battery.soc": 23.0}), "battery.soc_raw_pct", value=23.0))
check("... negative: just above protection + margin passes", "SOC_NEAR_PROTECTION" not in h.codes(far))
d2s = h.decisions_with("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT))
pu = A("protection_unknown", faults.with_reading(cf.cycle_inputs(decisions=d2s, accept_provenance=h.SYN),
                                                 "protection.shutdown_soc_pct", drop=True))
check("PROTECTION_LEVEL_UNKNOWN: no protection level known -> export and Dump BLOCKED",
      all("PROTECTION_LEVEL_UNKNOWN" in h.item_codes(pu, i) for i in EXPORT))
li = A("live_disagree", replace(base, live=replace(base.live, soc_pct=80.0)))
check("LIVE_INPUTS_DISAGREE: the LiveInputs SOC differs from the snapshot -> every item resting on the snapshot BLOCKED",
      all("LIVE_INPUTS_DISAGREE" in h.item_codes(li, i) for i in SNAP_ITEMS) and not (set(HISTORY_ONLY) & li.blocked_items))
for attr, v in (("pv_w", 900.0), ("load_w", 10.0), ("inverter_ok", False)):
    lx = A(f"live_disagree_{attr}", replace(base, live=replace(base.live, **{attr: v})))
    check(f"... on {attr} as well (the two do not describe the same moment)",
          all("LIVE_INPUTS_DISAGREE" in h.item_codes(lx, i) for i in SNAP_ITEMS))
lt = A("live_disagree_time", replace(base, live=replace(base.live, now=base.now - timedelta(minutes=10))))
check("... and when the LiveInputs were built at another time than the snapshot",
      all("LIVE_INPUTS_DISAGREE" in h.item_codes(lt, i) for i in SNAP_ITEMS))
lr = A("live_disagree_reserve", replace(rbase, live=replace(rbase.live, ha_reserve_pct=55.0)))
check("... the reserve helper under I-D1 HA_RESERVE_HELPER (LiveInputs 55, snapshot 20): its items BLOCKED, data quality "
      "not OK", reserve_items and all("LIVE_INPUTS_DISAGREE" in h.item_codes(lr, i) for i in reserve_items)
      and lr.data_quality != "OK")
lr0 = A("live_disagree_reserve_unused", replace(base, live=replace(base.live, ha_reserve_pct=55.0)))
check("... and also when no item requires the reserve helper (neither side can be trusted)",
      all("LIVE_INPUTS_DISAGREE" in h.item_codes(lr0, i) for i in SNAP_ITEMS))
li2 = A("live_withheld", replace(base, live=replace(base.live, inverter_ok=None)))
check("... negative: a value the bridge withheld (None) is not a disagreement", "LIVE_INPUTS_DISAGREE" not in h.codes(li2)
      and not h.blocks(li2))
check("... negative: the fixture's LiveInputs agree", "LIVE_INPUTS_DISAGREE" not in h.codes(qb))
for label, junk in (("a dict", {"soc_pct": 0.0}), ("a string", "live"), ("a number", 5)):
    lm = A(f"live_malformed_{label}", replace(base, live=junk))
    check(f"LIVE_INPUTS_MALFORMED: LiveInputs that is {label} BLOCKs every item resting on the snapshot",
          all("LIVE_INPUTS_MALFORMED" in h.item_codes(lm, i) for i in SNAP_ITEMS) and not (set(HISTORY_ONLY) & lm.blocked_items))
ln = A("live_none", replace(base, live=None))
check("... negative: no LiveInputs at all (None) is not malformed", not ({"LIVE_INPUTS_MALFORMED", "LIVE_INPUTS_DISAGREE"}
                                                                      & h.codes(ln)) and not h.blocks(ln))
dup = A("duplicate_reading", replace(base, site_readings=base.site_readings + (base.site_readings[5],)))
check("SITE_READING_DUPLICATE: two readings for one key -> neither used", "SITE_READING_DUPLICATE" in h.codes(dup, "BLOCK"))
bad = A("reading_bad_unit", faults.with_reading(base, "limits.max_grid_charge_w", unit="kW"))
check("READING_INVALID: a wrong unit -> WARN and the reading is unusable (its items BLOCKED)",
      "READING_INVALID" in h.codes(bad, "WARN") and "charge_target" in bad.blocked_items)
rf = A("reading_future", faults.with_reading(base, "limits.max_grid_charge_w", observed_at=base.now + timedelta(hours=1)))
check("READING_IN_FUTURE: WARN and not fresh", "READING_IN_FUTURE" in h.codes(rf) and "charge_target" in rf.blocked_items)
rn = A("reading_nan", faults.with_reading(base, "limits.max_grid_charge_w", value=float("nan")))
check("a NaN reading is unusable", "charge_target" in rn.blocked_items and not rn.ages["limits.max_grid_charge_w"].fresh)
rs_ = A("reading_string", faults.with_reading(base, "limits.max_grid_charge_w", value="5000"))
check("READING_INVALID: a number given as text is unusable (its items BLOCKED)", "READING_INVALID" in h.codes(rs_, "WARN")
      and "charge_target" in rs_.blocked_items)
for key, val, items in (("stop.dump_soc_pct", 150.0, ("dump_to_grid",)), ("stop.dump_soc_pct", -10.0, ("dump_to_grid",)),
                        ("pv.forecast_tomorrow_kwh", -5.0, ("pv_tomorrow",)), ("pv.forecast_tomorrow_kwh", 1e9, ("pv_tomorrow",)),
                        ("limits.max_grid_charge_w", -3000.0, WINDOW), ("limits.max_grid_charge_w", 0.0, WINDOW),
                        ("limits.max_grid_charge_w", 5e6, WINDOW)):
    pr = A(f"implausible_{key}_{val}", faults.with_reading(base, key, value=val))
    check(f"READING_INVALID (plausibility): {key} = {val} is not used, {list(items)} BLOCKED",
          "READING_INVALID" in h.codes(pr, "WARN") and all(i in pr.blocked_items for i in items)
          and not pr.ages[key].fresh)
pf = A("pv_forecast_implausible", faults.with_reading(base, "pv.forecast_tomorrow_kwh", value=70.0))
check("PV_FORECAST_IMPLAUSIBLE: a forecast above the PROPOSED yield per kWp of the array (6 kWp) -> pv_tomorrow BLOCKED",
      "PV_FORECAST_IMPLAUSIBLE" in h.codes(pf, "WARN") and "pv_tomorrow" in pf.blocked_items)
pf2 = A("pv_forecast_plausible", faults.with_reading(base, "pv.forecast_tomorrow_kwh", value=55.0))
check("... negative: a high but possible forecast passes", "PV_FORECAST_IMPLAUSIBLE" not in h.codes(pf2) and not h.blocks(pf2))
check("... negative: every fixture reading is plausible", "READING_INVALID" not in h.codes(qb))
caph = A("capacity_helper_implausible", faults.with_reading(base, "capacity.helper_kwh", value=5000.0))
check("... an implausible capacity helper reading is not counted as a capacity source",
      caph.ages["capacity.helper_kwh"].value is None and "READING_INVALID" in h.codes(caph, "WARN"))
print("== [8b] the date-scoped PV forecast")
midnight = base.now.replace(hour=0, minute=0, second=0)
fy = A("forecast_yesterday", faults.with_reading(base, "pv.forecast_tomorrow_kwh", observed_at=midnight - timedelta(minutes=1)))
check("a forecast observed one minute before local midnight is stale: pv_tomorrow BLOCKED INPUT_NOT_FRESH (reason stale)",
      any(f.code == "INPUT_NOT_FRESH" and f.subject == "pv_tomorrow" and dict(f.evidence).get("reason") == "stale"
          for f in fy.findings))
ft = A("forecast_today", faults.with_reading(base, "pv.forecast_tomorrow_kwh", observed_at=midnight + timedelta(minutes=1)))
check("... negative: one minute after local midnight it is fresh", ft.ages["pv.forecast_tomorrow_kwh"].fresh
      and "pv_tomorrow" not in ft.blocked_items)
summer = datetime(2030, 7, 15, 21, 0, tzinfo=timezone.utc)                # 22:00 BST: local midnight is 23:00 UTC
sbase = cf.cycle_inputs(synthetic_recorded=True, now=summer)
fs1 = A("forecast_bst_same_local_day", faults.with_reading(sbase, "pv.forecast_tomorrow_kwh",
                                                           observed_at=datetime(2030, 7, 14, 23, 30, tzinfo=timezone.utc)))
check("in summer time a forecast observed at 23:30 UTC of the previous UTC day (00:30 local) is from the same local day: fresh",
      fs1.ages["pv.forecast_tomorrow_kwh"].fresh and "pv_tomorrow" not in fs1.blocked_items)
fs2 = A("forecast_bst_previous_local_day", faults.with_reading(sbase, "pv.forecast_tomorrow_kwh",
                                                               observed_at=datetime(2030, 7, 14, 22, 30, tzinfo=timezone.utc)))
check("... and one observed at 22:30 UTC (23:30 local the day before) is stale: pv_tomorrow BLOCKED",
      not fs2.ages["pv.forecast_tomorrow_kwh"].fresh and "pv_tomorrow" in fs2.blocked_items)
print("== [8c] structure: malformed entries and the internal guard")
sm_ = A("site_reading_malformed", replace(base, site_readings=base.site_readings + ("not a reading", None)))
check("SITE_READING_MALFORMED: an entry that is not a SiteReading is ignored with a WARN (nothing else changes)",
      "SITE_READING_MALFORMED" in h.codes(sm_, "WARN") and not h.blocks(sm_))
check("... negative: the clean readings are all SiteReadings", "SITE_READING_MALFORMED" not in h.codes(qb))


class _Exploding:
    """A CycleInputs stand-in whose snapshot cannot even be read."""
    now = base.now
    decisions = base.decisions
    accept_provenance = base.accept_provenance
    site_facts = base.site_facts
    site_readings = base.site_readings

    @property
    def snapshot(self):
        raise RuntimeError("boom")


qi = q.assess_inputs(_Exploding())
check("QUALITY_INTERNAL_ERROR: an unexpected error inside the layer withholds every item (data quality BLOCKED), never raises",
      "QUALITY_INTERNAL_ERROR" in h.codes(qi, "BLOCK") and qi.blocked_items == frozenset(sd.ITEMS) and qi.data_quality == "BLOCKED")
check("... negative: never on the clean base", "QUALITY_INTERNAL_ERROR" not in h.codes(qb))
sf = A("snapshot_future", replace(base, snapshot=type(base.snapshot)(base.now + timedelta(hours=1), base.snapshot.observations)))
check("SNAPSHOT_IN_FUTURE -> BLOCKED", "SNAPSHOT_IN_FUTURE" in h.codes(sf) and sf.data_quality == "BLOCKED")
x = replace(base)
object.__setattr__(x, "snapshot", {"battery.soc": 55})
sm = A("snapshot_malformed", x)
check("SNAPSHOT_MALFORMED: not a Snapshot -> no signal used", "SNAPSHOT_MALFORMED" in h.codes(sm) and "charge_target" in sm.blocked_items)
x = replace(base)
object.__setattr__(x, "decisions", {"D1": "x"})
dm = A("decisions_malformed", x)
check("DECISIONS_MALFORMED: decisions that are not a DecisionSet count as OPEN", "DECISIONS_MALFORMED" in h.codes(dm))
x = replace(base)
object.__setattr__(x, "site_readings", {"a": 1})
rm = A("readings_malformed", x)
check("SITE_READINGS_MALFORMED", "SITE_READINGS_MALFORMED" in h.codes(rm) and "charge_target" in rm.blocked_items)
x = replace(base)
object.__setattr__(x, "now", datetime(2030, 1, 15, 21, 0))
check("NOW_INVALID: a naive now blocks everything", q.assess_inputs(x).blocked_items == frozenset(sd.ITEMS)
      and "NOW_INVALID" in h.codes(q.assess_inputs(x)))
tzq = A("tz_invalid", replace(base, site_facts=ac.SiteFacts(pv_array_kwp=6.0, tz="Nowhere/Invalid_Zone")))
check("TZ_INVALID: an unknown zone blocks everything", tzq.data_quality == "BLOCKED" and "TZ_INVALID" in h.codes(tzq))

print("== [9] history rules (assess_inputs)")
for name, code, sev in (("flaps", "TELEMETRY_FLAPPING", "BLOCK"), ("gaps", "HISTORY_GAP", "WARN"),
                        ("stalls", "HISTORY_COUNTER_STALL", "WARN"), ("catchup", "HISTORY_COUNTER_CATCHUP", "WARN"),
                        ("ct_reversal_history", "HISTORY_CT_REVERSED", "BLOCK"), ("soc_zero_history", "HISTORY_SOC_SUSPECT", "WARN"),
                        ("ct_reversal_recent", "HISTORY_CT_REVERSED", "BLOCK"), ("no_pv", "PV_NO_OUTPUT_VS_FORECAST", "BLOCK")):
    r = A(name, faults.inject(name, base, 1))
    check(f"{code} ({sev}) on the {name} fault", code in h.codes(r, sev), str(sorted(h.codes(r)))[:120])
    check(f"... negative: not on the clean base", code not in h.codes(qb))
fl = A("flaps", faults.flaps(base, 1))
check("TELEMETRY_FLAPPING BLOCKs the dongle items and only WARNs the history-only ones",
      all(i in fl.blocked_items for i in q.DONGLE_ITEMS) and not (set(q.HISTORY_ONLY_ITEMS) & fl.blocked_items))
one = History(list(base.history.by_start.values()))
del one.by_start[max(one.by_start) - 5 * 3600]
o1 = A("one_dropout", replace(base, history=one))
check("... negative: one recovered dropout is not flapping", "TELEMETRY_FLAPPING" not in h.codes(o1))
cov = History(list(base.history.by_start.values()))
for s in sorted(cov.by_start)[-160:-2:2]:
    del cov.by_start[s]
cq = A("coverage_low", replace(base, history=cov))
check("HISTORY_COVERAGE_LOW: half of the last week missing -> every history item BLOCKED",
      all("HISTORY_COVERAGE_LOW" in h.item_codes(cq, i) for i in q.HISTORY_ITEMS))
balanced = A("balanced_counters", replace(base, history=faults.add_balanced_counters(base.history)))
check("... negative: counters that balance raise no balance or CT finding",
      not ({"HISTORY_CT_REVERSED", "HISTORY_BALANCE_RESIDUAL"} & h.codes(balanced)) and not h.blocks(balanced))
ins = q.assess_inputs(faults.no_pv(base, 2))
check("PV_NO_OUTPUT_VS_FORECAST BLOCKs pv_tomorrow (fail closed whether or not the cycle reads insufficient_items) and "
      "marks it INSUFFICIENT_DATA there", "pv_tomorrow" in ins.blocked_items
      and "PV_NO_OUTPUT_VS_FORECAST" in h.item_codes(ins, "pv_tomorrow") and ins.insufficient_items() == frozenset({"pv_tomorrow"}))
check("... charge_target and predicted_morning_soc are only warned", not ({"charge_target", "predicted_morning_soc"}
                                                                          & ins.blocked_items))
ins2 = q.assess_inputs(faults.with_reading(faults.no_pv(base, 2), "pv.forecast_tomorrow_kwh", drop=True))
check("... insufficient_items() leaves out an item another BLOCK also names", "pv_tomorrow" in ins2.blocked_items
      and not ins2.insufficient_items())
check("... negative: the clean base marks nothing insufficient", not qb.insufficient_items())
for days in (1, 2, 3):
    rc = A(f"ct_recent_{days}d", faults.with_reversed_ct(base, days * 24))
    check(f"HISTORY_CT_REVERSED (recent onset): import and export swapped for the last {days} day(s) of a 61-day history "
          "-> every history item BLOCKED", all("HISTORY_CT_REVERSED" in h.item_codes(rc, i) for i in q.HISTORY_ITEMS)
          and any("recent" in dict(f.evidence).get("windows", ()) for f in rc.findings if f.code == "HISTORY_CT_REVERSED"))
rc3h = A("ct_recent_3h", faults.with_reversed_ct(base, 3))
check("... negative: three swapped hours (below the PROPOSED minimum) are not a reversal",
      "HISTORY_CT_REVERSED" not in h.codes(rc3h))
one_day = History(_copy.deepcopy(r) for r in base.history.by_start.values())
y0, y1 = cf.NOW.replace(hour=0) - timedelta(days=1), cf.NOW.replace(hour=0)     # yesterday (UTC = local in January)
for s_ in range(int(y0.timestamp()), int(y1.timestamp()), 3600):
    if s_ in one_day.by_start:
        one_day.by_start[s_].e["pv"] = 0.0
pv1 = A("one_zero_pv_day", replace(base, history=one_day,
                                    pv_forecast_history={"synthetic_forecast": {y0.date(): 5.0, (y0 - timedelta(days=1)).date(): 5.0}}))
check("... negative: a single zero-PV day is not prolonged", "PV_NO_OUTPUT_VS_FORECAST" not in h.codes(pv1))
dn = faults.dst_now(3)
dq_ = A("dst_lookback", cf.cycle_inputs(synthetic_recorded=True, now=dn))
check("DST_NIGHT_IN_LOOKBACK: a clock change within the learning lookback -> WARN (I-D9 governs)",
      "DST_NIGHT_IN_LOOKBACK" in h.codes(dq_, "WARN"))
check("... negative: mid-January 2030 has none", "DST_NIGHT_IN_LOOKBACK" not in h.codes(qb))
nanh = History(_copy.deepcopy(r) for r in base.history.by_start.values())
nanh.by_start[max(nanh.by_start) - 3600].e["pv"] = float("nan")
nv = A("history_nan", replace(base, history=nanh))
check("HISTORY_VALUE_INVALID: a NaN energy in the history -> WARN", "HISTORY_VALUE_INVALID" in h.codes(nv, "WARN"))

print("== [10] prepare_history (I-D8 on a copy)")
hist = cf.history()
before = {s: (r.load_w_mean, dict(r.e)) for s, r in hist.by_start.items()}
cut = datetime(2030, 1, 1, tzinfo=timezone.utc)
cut_ts = int(cut.timestamp())
ref = "REC-20300101-counter-check"


def d8(power, counter, evidence=None):
    return sd.DecisionSet().with_decision("D8", sd.HD1Cutover(cut, power, counter, evidence), sd.Provenance.SYNTHETIC_TEST)


hx, fx = q.prepare_history(hist, d8(sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER), cf.NOW, accept_provenance=h.SYN)
check("EXCLUDE + EXCLUDE_PRE_CUTOVER: no pre-cut-over load power or counter; later hours keep both",
      all(r.load_w_mean is None and "load" not in r.e for s, r in hx.by_start.items() if s < cut_ts)
      and all(r.load_w_mean is not None and "load" in r.e for s, r in hx.by_start.items() if s >= cut_ts))
check("HISTORY_PRE_CUTOVER_LOAD_REMOVED (INFO) counts what the policy removed", any(
    f.code == "HISTORY_PRE_CUTOVER_LOAD_REMOVED" and f.severity == "INFO" and dict(f.evidence)["energy_hours"] > 0 for f in fx))
early = sd.DecisionSet().with_decision("D8", sd.HD1Cutover(datetime(2020, 1, 1, tzinfo=timezone.utc), sd.EXCLUDE,
                                                            sd.EXCLUDE_PRE_CUTOVER), sd.Provenance.SYNTHETIC_TEST)
he, fe = q.prepare_history(hist, early, cf.NOW, accept_provenance=h.SYN)
check("... negative: a cut-over before the history starts removes nothing and says nothing",
      he is not None and "HISTORY_PRE_CUTOVER_LOAD_REMOVED" not in {f.code for f in fe})
hu, fu = q.prepare_history(hist, d8(sd.EXCLUDE, sd.KEEP_AFTER_COUNTER_CHECK, ref), cf.NOW, accept_provenance=h.SYN)
pre_load = [s for s, r in hist.by_start.items() if s < cut_ts and "load" in r.e]
check("HISTORY_COUNTER_CHECK_UNAVAILABLE: KEEP_AFTER_COUNTER_CHECK on a history without import / export / battery "
      "counters keeps no pre-cut-over counter unchecked (all removed, WARN with the count)",
      pre_load and all("load" not in hu.by_start[s].e for s in pre_load if s in hu.by_start)
      and any(f.code == "HISTORY_COUNTER_CHECK_UNAVAILABLE" and f.severity == "WARN" and dict(f.evidence)["hours"] == len(pre_load)
              for f in fu), str([(f.code, dict(f.evidence)) for f in fu])[:300])
cnt = faults.add_balanced_counters(hist)
exp_hours = [s for s, r in cnt.by_start.items() if s < cut_ts and r.e.get("exp", 0) > 0]
zero_hours = [s for s, r in cnt.by_start.items() if s < cut_ts and r.e.get("exp") == 0.0]
hk, fk = q.prepare_history(cnt, d8(sd.KEEP_NON_EXPORTING_ONLY, sd.EXCLUDE_PRE_CUTOVER, ref), cf.NOW, accept_provenance=h.SYN)
check("KEEP_NON_EXPORTING_ONLY: pre-cut-over load power kept only where export was recorded as zero",
      exp_hours and zero_hours and all(hk.by_start[s].load_w_mean is None for s in exp_hours)
      and all(hk.by_start[s].load_w_mean is not None for s in zero_hours))
hk2, _ = q.prepare_history(hist, d8(sd.KEEP_NON_EXPORTING_ONLY, sd.EXCLUDE_PRE_CUTOVER, ref), cf.NOW, accept_provenance=h.SYN)
check("... without an export counter nothing pre-cut-over is kept (no recorded zero export)",
      all(r.load_w_mean is None for s, r in hk2.by_start.items() if s < cut_ts))
bad_cnt = History(_copy.deepcopy(r) for r in cnt.by_start.values())
pre = sorted(s for s in bad_cnt.by_start if s < cut_ts)
fz_s, mm_s = pre[10], pre[30]
bad_cnt.by_start[fz_s].e.update({"load": 0.0, "exp": 1.5, "imp": 0.0})
bad_cnt.by_start[mm_s].e["load"] = bad_cnt.by_start[mm_s].e["load"] + 0.6    # off the balance, below a catch-up
hc, fc = q.prepare_history(bad_cnt, d8(sd.EXCLUDE, sd.KEEP_AFTER_COUNTER_CHECK, ref), cf.NOW, accept_provenance=h.SYN)
kept = [s for s in pre if "load" in hc.by_start[s].e]
check("KEEP_AFTER_COUNTER_CHECK: the pre-cut-over counter is kept, except a zero-while-exporting hour and a counter that "
      "disagrees with the balance-derived load", fz_s not in kept and mm_s not in kept and len(kept) >= len(pre) - 2
      and {"HISTORY_LOAD_FALSE_ZERO_REMOVED", "HISTORY_COUNTER_CHECK_REMOVED"} <= {f.code for f in fc})
check("... and the load power before the cut-over is still excluded (EXCLUDE)",
      all(hc.by_start[s].load_w_mean is None for s in pre))
check("the History passed in is never modified", {s: (r.load_w_mean, dict(r.e)) for s, r in hist.by_start.items()} == before
      and bad_cnt.by_start[fz_s].e["load"] == 0.0)
lfz = faults.load_false_zero_after_cutover(cf.cycle_inputs(synthetic_recorded=True), 2)
hn, fn = q.prepare_history(lfz.history, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER: repeated zero-while-exporting hours after the cut-over -> None with a BLOCK",
      hn is None and any(f.code == "HISTORY_LOAD_FALSE_ZERO_AFTER_CUTOVER" and f.severity == "BLOCK" for f in fn))
one_fz = faults.add_balanced_counters(hist)
s1 = max(s for s in one_fz.by_start if s >= cut_ts) - 10 * 3600
one_fz.by_start[s1].e.update({"load": 0.0, "exp": 0.8})
h1, f1 = q.prepare_history(one_fz, d8(sd.EXCLUDE, sd.EXCLUDE_PRE_CUTOVER), cf.NOW, accept_provenance=h.SYN)
check("... negative: a single such hour is removed with a WARN, the history is still returned",
      h1 is not None and "load" not in h1.by_start[s1].e and any(f.code == "HISTORY_LOAD_FALSE_ZERO_REMOVED" for f in f1))
ctr = faults.ct_reversal_history(cf.cycle_inputs(synthetic_recorded=True), 1)
hr, fr = q.prepare_history(ctr.history, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("HISTORY_CT_REVERSED: a history recorded through a reversed CT -> None with a BLOCK", hr is None
      and any(f.code == "HISTORY_CT_REVERSED" for f in fr))
hb_, fb_ = q.prepare_history(faults.add_balanced_counters(hist), cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("... negative: balanced counters pass", hb_ is not None and not [f for f in fb_ if f.severity == "BLOCK"])
stl = faults.stalls(cf.cycle_inputs(synthetic_recorded=True), 3)
hs, fs = q.prepare_history(stl.history, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
removed = [s for s, r in stl.history.by_start.items() if "load" in r.e and s in hs.by_start and "load" not in hs.by_start[s].e
           and s >= int(datetime(2029, 12, 1, tzinfo=timezone.utc).timestamp())]
check("stalls: the stuck hours and the catch-up hour leave the learning copy (WARN)", len(removed) >= 3
      and {"HISTORY_COUNTER_STALL", "HISTORY_COUNTER_CATCHUP"} <= {f.code for f in fs})
rch = faults.with_reversed_ct(cf.cycle_inputs(synthetic_recorded=True), 48).history
hrc, frc = q.prepare_history(rch, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("HISTORY_CT_REVERSED in prepare_history too for a recent onset (the last two days swapped): None with a BLOCK",
      hrc is None and any(f.code == "HISTORY_CT_REVERSED" and "recent" in dict(f.evidence)["windows"] for f in frc))
d8_invalid = sd.DecisionSet().with_decision("D8", sd.HD1Cutover(cut, sd.KEEP_NON_EXPORTING_ONLY, sd.EXCLUDE_PRE_CUTOVER, None),
                                            sd.Provenance.SYNTHETIC_TEST)
odd = History()
odd.by_start = [1, 2, 3]                                   # not even a mapping: preparing it fails inside the layer
for bad_args, label, code in (((hist, sd.DecisionSet(), cf.NOW), "I-D8 OPEN", "DECISION_D8_OPEN"),
                              ((hist, d8_invalid, cf.NOW), "I-D8 INVALID", "DECISION_D8_INVALID"),
                              ((None, cf.synthetic_decisions(), cf.NOW), "no history", "HISTORY_MISSING"),
                              ((History(), cf.synthetic_decisions(), cf.NOW), "an empty history", "HISTORY_MISSING"),
                              ((hist, None, cf.NOW), "no decisions", "DECISIONS_MISSING"),
                              ((hist, cf.synthetic_decisions(), datetime(2030, 1, 1)), "naive now", "NOW_INVALID"),
                              ((odd, cf.synthetic_decisions(), cf.NOW), "a History whose records are not a mapping",
                               "HISTORY_MALFORMED")):
    hh_, ff_ = q.prepare_history(*bad_args, accept_provenance=h.SYN)
    check(f"prepare_history fails closed: {label} -> None with BLOCK {code}",
          hh_ is None and any(f.severity == "BLOCK" and f.code == code for f in ff_), str([f.code for f in ff_]))
hj, fj = q.prepare_history(hist, cf.synthetic_decisions(), cf.NOW, accept_provenance=5)
check("ACCEPT_PROVENANCE_INVALID: junk accept_provenance -> None with a BLOCK, no exception",
      hj is None and fj and fj[0].severity == "BLOCK" and fj[0].code == "ACCEPT_PROVENANCE_INVALID")
hok, fok = q.prepare_history(faults.add_balanced_counters(hist), cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("... negative: the clean case raises none of the refusal codes", hok is not None and not (
    {f.code for f in fok} & {"DECISION_D8_OPEN", "DECISION_D8_INVALID", "HISTORY_MISSING", "DECISIONS_MISSING", "NOW_INVALID",
                             "HISTORY_MALFORMED", "ACCEPT_PROVENANCE_INVALID", "HISTORY_RECORD_MALFORMED"}))
junk_hist = History(_copy.deepcopy(r) for r in hist.by_start.values())
js = sorted(junk_hist.by_start)
junk_hist.by_start[js[-5]] = "junk"
junk_hist.by_start[js[-6]].flags = None
junk_hist.by_start[js[-7]].e = None
hjr, fjr = q.prepare_history(junk_hist, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("HISTORY_RECORD_MALFORMED: junk entries and records with malformed fields are left out with a WARN, never raise",
      hjr is not None and js[-5] not in hjr.by_start and js[-6] not in hjr.by_start and js[-7] not in hjr.by_start
      and any(f.code == "HISTORY_RECORD_MALFORMED" and dict(f.evidence)["entries"] == 3 for f in fjr))

print("== [10b] the CT share rule: only hours in which import and export can be told apart count")
HR = 3600
END = int(cf.NOW.timestamp())                    # hour aligned
MIN_H, MIN_SHARE = q.DQ_PROPOSED.ct_reversal_min_hours, q.DQ_PROPOSED.ct_reversal_min_share
AT_SHARE = int(round(MIN_H / MIN_SHARE))         # distinguishable hours that put MIN_H swapped ones exactly at MIN_SHARE
CT_EV_KEYS = {f"{w}_{k}" for w in ("history", "lookback", "recent") for k in ("distinguishable", "distinguishable_only_swapped")}


def shaped(rec: HourRecord, kind: str) -> HourRecord:
    """A copy of `rec` with the four grid and battery counters set so the hour's balance class is `kind`; load and PV are
    kept (fictional kWh). flat: balances, import and export both zero (cannot be told apart); isw: balances only with
    import and export swapped, but they are 0.15 kWh apart (cannot be told apart); bal / sw / unb: import and export 1 kWh
    apart (told apart), and the hour balances / balances only swapped (a genuine reversal) / balances neither way."""
    r = _copy.deepcopy(rec)
    L, p = r.e["load"], r.e["pv"]
    if kind == "flat":
        e = {"imp": 0.0, "exp": 0.0, "dis": max(L - p, 0.0), "chg": max(p - L, 0.0)}
    elif kind == "isw":                          # residual 0.25 kWh as recorded, 0.05 kWh swapped
        e = {"imp": 0.0, "exp": 0.15, "dis": max(L - 0.1 - p, 0.0), "chg": max(p - L + 0.1, 0.0)}
    else:
        d = L - p - 1.0
        e = {"imp": 1.0, "exp": 0.0, "dis": max(d, 0.0), "chg": max(-d, 0.0)}
        if kind == "sw":
            e["imp"], e["exp"] = e["exp"], e["imp"]
        elif kind == "unb":
            e["dis"] += 0.8                      # residual -0.8 kWh as recorded, 1.2 kWh swapped
    r.e.update(e)
    return r


def hr(start: int, kind: str) -> HourRecord:
    return shaped(HourRecord(start=start, e={"load": 1.0, "pv": 0.0}), kind)


def run_of(kind: str, n: int, newest: int) -> dict:
    """n consecutive hours of `kind`, the newest beginning at `newest`."""
    return {newest - i * HR: hr(newest - i * HR, kind) for i in range(n)}


CLASS = {"flat": ("balanced", 0), "isw": ("balanced_only_swapped", 0), "bal": ("balanced", 1),
         "sw": ("balanced_only_swapped", 1), "unb": ("unbalanced", 1)}
shape_ok = []
for kind, (cls, dist) in CLASS.items():
    for L, p in ((1.0, 0.0), (0.3, 1.9), (1.9, 0.6), (0.0, 0.0)):
        c = q.balance_counts({0: shaped(HourRecord(start=0, e={"load": L, "pv": p}), kind)})
        shape_ok.append(c.get(cls) == 1 and sum(c.get(k, 0) for k in ("balanced", "balanced_only_swapped", "unbalanced")) == 1
                        and c.get("distinguishable") == dist)
check("the hour shapes of this section have the balance class and distinguishability they are named for (any load and PV "
      "up to about 2 kWh)", all(shape_ok), str(shape_ok))
one_isw = q.balance_counts({0: hr(0, "isw")})
check("balance_counts keeps its keys and their meanings and adds distinguishable_only_swapped: an hour that balances only "
      "swapped but cannot be told apart counts in balanced_only_swapped and in neither distinguishable count",
      one_isw == {"balanced": 0, "balanced_only_swapped": 1, "unbalanced": 0, "distinguishable": 0,
                  "distinguishable_only_swapped": 0}, str(one_isw))
mix = {**run_of("flat", 5, END - 1 * HR), **run_of("isw", 4, END - 10 * HR), **run_of("bal", 3, END - 20 * HR),
       **run_of("sw", 2, END - 30 * HR), **run_of("unb", 1, END - 40 * HR)}
mix[END - 50 * HR] = HourRecord(start=END - 50 * HR, e={"load": 1.0, "pv": 0.0})        # no grid / battery counters
cm = q.balance_counts(mix)
check("... over a mix: balanced + balanced_only_swapped + unbalanced is every hour with all six counters; distinguishable "
      "counts the told-apart hours and distinguishable_only_swapped those of them that balance only swapped",
      cm == {"balanced": 8, "balanced_only_swapped": 6, "unbalanced": 1, "distinguishable": 6,
             "distinguishable_only_swapped": 2}, str(cm))
rm_ = q.recent_balance_counts(mix, END)
check("recent_balance_counts returns the share rule's counts under the same names (distinguishable, "
      "distinguishable_only_swapped) over the most recent told-apart hours", rm_ == {"distinguishable": 6,
                                                                                  "distinguishable_only_swapped": 2}, str(rm_))

# (a) many hours that balance only swapped but cannot be told apart, and one told-apart hour that balances
for n_isw in (MIN_H, 13, 200):
    shp = {**run_of("flat", 300, END - 2 * HR),
           **{END - (24 + 7 * i) * HR: hr(END - (24 + 7 * i) * HR, "isw") for i in range(n_isw)}, END - HR: hr(END - HR, "bal")}
    rv, ev = q.ct_reversal(shp, END, 28)
    check(f"{n_isw} hours that balance only swapped but cannot be told apart, one told-apart hour that balances: no reversal "
          "in any window (the share's numerator counts only told-apart hours: 0 of 1)", rv is False and ev.get("windows") == ()
          and q.balance_counts(shp)["balanced_only_swapped"] == n_isw and ev.get("history_distinguishable") == 1
          and ev.get("history_distinguishable_only_swapped") == 0, str((rv, ev)))
bh = History(_copy.deepcopy(r) for r in base.history.by_start.values())
starts = sorted(bh.by_start)
picked = [s for s in starts[:-24] if max(bh.by_start[s].e["load"], bh.by_start[s].e["pv"] + 0.1) < 2.0][::90][:13]
for s in starts:
    bh.by_start[s] = shaped(bh.by_start[s], "isw" if s in picked else "bal" if s == starts[-1] else "flat")
cb = q.balance_counts(bh.by_start)
check("the shape on the clean synthetic history (61 days, counters on every hour): 13 hours balance only swapped and none "
      "of them is told apart, one told-apart hour balances, every other hour balances and is not told apart",
      len(picked) == 13 and cb == {"balanced": len(starts) - 13, "balanced_only_swapped": 13, "unbalanced": 0,
                                    "distinguishable": 1, "distinguishable_only_swapped": 0}, str(cb))
ab = A("ct_indistinguishable_swapped", replace(base, history=bh))
check("... assess_inputs raises no HISTORY_CT_REVERSED (nor any BLOCK) on it", "HISTORY_CT_REVERSED" not in h.codes(ab)
      and not h.blocks(ab), str(sorted(h.codes(ab))))
pb, fb = q.prepare_history(bh, cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
check("... and prepare_history returns a history (learning goes on) without HISTORY_CT_REVERSED", pb is not None
      and len(pb.by_start) > 0 and "HISTORY_CT_REVERSED" not in {f.code for f in fb}, str([f.code for f in fb]))

# (b) a genuine reversal (told-apart hours that balance only swapped) still fires, in each window on its own, with the
# counts the rule used as evidence; the hours that cannot be told apart are in none of those counts
hist_only = {**run_of("sw", 12, END - 40 * 24 * HR), **run_of("isw", 7, END - 20 * 24 * HR), **run_of("bal", 8, END - HR)}
look_only = {**run_of("bal", 200, END - 50 * 24 * HR), **run_of("sw", 30, END - 10 * 24 * HR),
             **run_of("bal", 10, END - 12 * 24 * HR), **run_of("isw", 9, END - 5 * 24 * HR), **run_of("bal", 12, END - HR)}
recent_seq = ["isw", "sw", "isw", "sw", "sw", "isw", "sw", "sw", "sw", "isw", "sw", "sw", "bal", "bal", "isw", "bal", "bal"]
recent_only = {**{END - (i + 1) * HR: hr(END - (i + 1) * HR, k) for i, k in enumerate(recent_seq)},
               **run_of("bal", 300, END - 4 * 24 * HR)}
for label, recs_, want_w, want in (
        ("history", hist_only, ("history",), {"history": (20, 12), "lookback": (8, 0), "recent": (8, 0)}),
        ("lookback", look_only, ("lookback",), {"history": (252, 30), "lookback": (52, 30), "recent": (12, 0)}),
        ("recent", recent_only, ("recent",), {"history": (312, 8), "lookback": (312, 8), "recent": (12, 8)})):
    rv, ev = q.ct_reversal(recs_, END, 28)
    got = {w: (ev.get(f"{w}_distinguishable"), ev.get(f"{w}_distinguishable_only_swapped")) for w in want}
    check(f"a genuine reversal in the {label} window alone fires there and only there, and the evidence states each "
          "window's two counts (told-apart hours, those of them only swapped)", rv is True and ev.get("windows") == want_w
          and got == want and set(ev) == CT_EV_KEYS | {"windows"}, str((rv, ev)))
rc2 = A("ct_recent_2d_evidence", faults.with_reversed_ct(base, 48))
ev2 = [dict(f.evidence) for f in rc2.findings if f.code == "HISTORY_CT_REVERSED"]
check("assess_inputs' HISTORY_CT_REVERSED carries the counts the rule used (a two-day onset: the most recent told-apart "
      "hours all balance only swapped)", ev2 and all(set(e) == CT_EV_KEYS | {"windows"} and "recent" in e["windows"]
                                                    and e["recent_distinguishable_only_swapped"] == e["recent_distinguishable"]
                                                    == q.DQ_PROPOSED.ct_recent_hours for e in ev2), str(ev2[:1]))
_, fr2 = q.prepare_history(faults.with_reversed_ct(cf.cycle_inputs(synthetic_recorded=True), 48).history,
                           cf.synthetic_decisions(), cf.NOW, accept_provenance=h.SYN)
ev3 = [dict(f.evidence) for f in fr2 if f.code == "HISTORY_CT_REVERSED"]
check("... and so does prepare_history's", ev3 and set(ev3[0]) == CT_EV_KEYS | {"windows"}
      and ev3[0]["recent_distinguishable_only_swapped"] == ev3[0]["recent_distinguishable"] > 0, str(ev3[:1]))

# (c) the boundaries: exactly the PROPOSED minimum hours and exactly the PROPOSED minimum share fire (both inclusive), one
# told-apart hour fewer does not, and hours that cannot be told apart never make up the difference. The minimum hours
# bound the told-apart hours that balance only swapped (the numerator), not the told-apart hours (the denominator), and
# never count hours that cannot be told apart: the share met with one such hour short of the minimum does not fire
check(f"the PROPOSED share rule this section assumes: {MIN_H} hours, a share of {MIN_SHARE} that {MIN_H} of {AT_SHARE} "
      "hours meets exactly", MIN_H / AT_SHARE == MIN_SHARE and AT_SHARE > MIN_H)
check(f"... {MIN_H - 1} of {MIN_H + 2} hours meet that share too, and {MIN_H} of {AT_SHARE - 1} is above it (both with "
      f"more than {MIN_H} hours in the denominator)", (MIN_H - 1) / (MIN_H + 2) >= MIN_SHARE and AT_SHARE - 1 > MIN_H)
for label, recs_, want in (
        (f"{MIN_H} told-apart hours, all only swapped (exactly the minimum hours)", run_of("sw", MIN_H, END - HR), True),
        (f"{MIN_H - 1} told-apart hours, all only swapped", run_of("sw", MIN_H - 1, END - HR), False),
        (f"{MIN_H - 1} told-apart hours only swapped, and 3 that cannot be told apart",
         {**run_of("sw", MIN_H - 1, END - HR), **run_of("isw", 3, END - 20 * HR)}, False),
        (f"{MIN_H - 1} of {MIN_H + 2} told-apart hours only swapped (the share met, the minimum hours not)",
         {**run_of("sw", MIN_H - 1, END - HR), **run_of("bal", 3, END - 20 * HR)}, False),
        (f"{MIN_H - 1} of {MIN_H + 2} told-apart hours only swapped, and 1 that cannot be told apart (the share met, the "
         "minimum hours one short)",
         {**run_of("sw", MIN_H - 1, END - HR), **run_of("bal", 3, END - 20 * HR), **run_of("isw", 1, END - 40 * HR)},
         False),
        (f"{MIN_H} of {AT_SHARE - 1} told-apart hours only swapped (both bounds met, the told-apart hours above both)",
         {**run_of("sw", MIN_H, END - HR), **run_of("bal", AT_SHARE - 1 - MIN_H, END - 20 * HR)}, True),
        (f"{MIN_H} of {AT_SHARE} told-apart hours only swapped (exactly the minimum share)",
         {**run_of("sw", MIN_H, END - HR), **run_of("bal", AT_SHARE - MIN_H, END - 20 * HR)}, True),
        (f"{MIN_H} of {AT_SHARE + 1} told-apart hours only swapped",
         {**run_of("sw", MIN_H, END - HR), **run_of("bal", AT_SHARE + 1 - MIN_H, END - 20 * HR)}, False),
        (f"{MIN_H} of {AT_SHARE + 1} told-apart hours only swapped, and 1 that cannot be told apart",
         {**run_of("sw", MIN_H, END - HR), **run_of("bal", AT_SHARE + 1 - MIN_H, END - 20 * HR),
          **run_of("isw", 1, END - 40 * HR)}, False)):
    c = q.balance_counts(recs_)
    check(f"ct_reversed over balance_counts: {label} -> {'reversed' if want else 'not reversed'}",
          q.ct_reversed(c) is want, str(c))
seq_at = ["sw", "isw", "sw", "bal", "sw", "isw", "bal", "sw", "bal", "sw", "bal", "sw", "bal", "bal"]
seq_below = ["sw", "isw", "sw", "bal", "sw", "isw", "bal", "sw", "bal", "isw", "bal", "sw", "bal", "bal", "bal"]
for label, seq, want in ((f"{MIN_H} of the most recent {AT_SHARE} told-apart hours only swapped", seq_at, ("recent",)),
                         (f"{MIN_H - 1} of them, with hours that cannot be told apart in between", seq_below, ())):
    rr = {**{END - (i + 1) * HR: hr(END - (i + 1) * HR, k) for i, k in enumerate(seq)},
          **run_of("bal", 100, END - 5 * 24 * HR)}
    rv, ev = q.ct_reversal(rr, END, 28)
    check(f"the recent window at its boundary: {label} -> windows {want}", q.DQ_PROPOSED.ct_recent_hours == AT_SHARE
          and ev.get("windows") == want and ev.get("recent_distinguishable") == AT_SHARE, str(ev))
# the recent window holding fewer told-apart hours than it judges: the minimum hours still bound the told-apart hours that
# balance only swapped, not the told-apart hours, and an hour that cannot be told apart does not make up the difference
seq_few = ["sw", "bal", "sw", "sw", "bal", "sw", "bal", "sw"]
for label, seq in ((f"{MIN_H - 1} of its {MIN_H + 2} told-apart hours only swapped (the share met, the minimum hours not)",
                    seq_few),
                   ("... and 1 more hour that balances only swapped but cannot be told apart", seq_few[:3] + ["isw"]
                    + seq_few[3:])):
    rr = {**{END - (i + 1) * HR: hr(END - (i + 1) * HR, k) for i, k in enumerate(seq)},
          **run_of("bal", 100, END - 5 * 24 * HR)}
    rv, ev = q.ct_reversal(rr, END, 28)
    check(f"the recent window short of the minimum hours: {label} -> no window", rv is False and ev.get("windows") == ()
          and seq.count("sw") == MIN_H - 1 and ev.get("recent_distinguishable") == MIN_H + 2
          and ev.get("recent_distinguishable_only_swapped") == MIN_H - 1, str(ev))

# (d) the residual rule still counts every hour that balances only swapped (told apart or not) in its total
def residual_case(n_unb: int, n_flat: int, n_isw: int) -> History:
    """The clean synthetic history with grid and battery counters on n_unb + n_flat + n_isw hours of the lookback only."""
    hh = History(_copy.deepcopy(r) for r in base.history.by_start.values())
    cand = [s for s in sorted(hh.by_start) if s >= END - 27 * 24 * HR
            and max(hh.by_start[s].e["load"], hh.by_start[s].e["pv"] + 0.1) < 2.0][::5]
    kinds = ["unb"] * n_unb + ["flat"] * n_flat + ["isw"] * n_isw
    assert len(cand) >= len(kinds), len(cand)
    for s, k in zip(cand, kinds):
        hh.by_start[s] = shaped(hh.by_start[s], k)
    return hh


r_no = A("residual_total_counts_isw", replace(base, history=residual_case(8, 12, 25)))
check("HISTORY_BALANCE_RESIDUAL: 8 hours that balance neither way among 45 with counters (25 of them balance only swapped "
      "but cannot be told apart) stay under a fifth of the total: no WARN, and no CT reversal",
      not ({"HISTORY_BALANCE_RESIDUAL", "HISTORY_CT_REVERSED"} & h.codes(r_no)), str(sorted(h.codes(r_no))))
r_yes = A("residual_total_counts_isw_warn", replace(base, history=residual_case(8, 12, 10)))
ev_r = [dict(f.evidence) for f in r_yes.findings if f.code == "HISTORY_BALANCE_RESIDUAL"]
check("... the same 8 among 30 (10 only swapped, not told apart) reach a fifth: WARN, whose counts keep their meanings "
      "(balanced_only_swapped counts the 10; no told-apart hour balances only swapped), and no CT reversal",
      "HISTORY_BALANCE_RESIDUAL" in h.codes(r_yes, "WARN") and "HISTORY_CT_REVERSED" not in h.codes(r_yes)
      and ev_r == [{"balanced": 12, "balanced_only_swapped": 10, "unbalanced": 8, "distinguishable": 8,
                    "distinguishable_only_swapped": 0}], str(ev_r))

print("== [11] contract hygiene over every scenario")
leaks, undeclared, bad_rows, self_fail = [], [], [], []
for name, inp in SCENARIOS:
    r = q.assess_inputs(inp)
    leaks += [f"{name}: {x}" for x in h.text_leaks(r)]
    for f in r.findings:
        if f.severity == "BLOCK" and f.code == "INPUT_NOT_FRESH" and dict(f.evidence).get("input") not in h.DECLARED_INPUTS:
            undeclared.append((name, dict(f.evidence).get("input")))
        if f.severity == "BLOCK" and f.code not in q.RULE_INPUTS:
            undeclared.append((name, f.code))
    rows = r.input_ages()
    if len(rows) > ac.MAX_INPUT_AGES or not all(set(x) == ac.INPUT_AGE_KEYS and ac._known_input(x["name"]) for x in rows):
        bad_rows.append(name)
    env = run_cycle(inp)
    if env.status == "SELF_TEST_FAILED" and name not in ("snapshot_malformed", "decisions_malformed", "readings_malformed"):
        self_fail.append((name, dict(env.self_test or {})))
check(f"no finding text carries a number with a unit ({len(SCENARIOS)} scenarios)", not leaks, str(leaks[:3]))
check("every BLOCK code is a declared rule and every INPUT_NOT_FRESH names a declared input", not undeclared, str(undeclared[:5]))
check("every rule's inputs are declared (REQUIRED_SIGNALS / REQUIRED_READINGS / SITE_READING_KEYS) or the structure itself",
      all(set(v) <= h.DECLARED_INPUTS | {"<structure>"} for v in q.RULE_INPUTS.values()),
      str({k: sorted(set(v) - h.DECLARED_INPUTS - {'<structure>'}) for k, v in q.RULE_INPUTS.items()
           if set(v) - h.DECLARED_INPUTS - {'<structure>'}}))
check("the input-age rows are valid envelope rows (known names, at most the cap) in every scenario", not bad_rows, str(bad_rows[:4]))
check("run_cycle never fails its self-test on these inputs (the quality output is always a valid envelope input)",
      not self_fail, str(self_fail[:3]))
# every finding code quality.py can emit (each upper-case string constant with an underscore) is named in this suite, so no
# rule is left without a case; the decision register's own codes, passed through from site_decisions.freshness_limits,
# are proved by test_intel_site_decisions
QSRC = (h.ROOT / "intelligence" / "quality.py").read_text(encoding="utf-8")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
emitted = {n.value for n in ast.walk(ast.parse(QSRC)) if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and CODE_RE.match(n.value)} - {"INSUFFICIENT_DATA"}
passthrough = {c for c in emitted if c.startswith("FRESHNESS_OVERRIDE_")}
own_src = Path(__file__).read_text(encoding="utf-8")
unnamed = sorted(c for c in emitted - passthrough if f'"{c}"' not in own_src)
check(f"every code quality.py emits ({len(emitted - passthrough)}) is named in a case of this suite", not unnamed, str(unnamed))
check("... and every BLOCK code in RULE_INPUTS is one of them", set(q.RULE_INPUTS) <= emitted, str(set(q.RULE_INPUTS) - emitted))
d6bad = cf.synthetic_decisions().with_decision("D6", sd.FreshnessOverrides({"battery.soc": 5000.0}), sd.Provenance.SYNTHETIC_TEST)
r6 = q.assess_inputs(cf.cycle_inputs(decisions=d6bad, accept_provenance=h.SYN))
check("DECISION_D6_INVALID (the register's finding, passed through): an I-D6 that loosens a defined limit BLOCKs",
      "DECISION_D6_INVALID" in h.codes(r6, "BLOCK"))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all data-quality rule checks passed")
