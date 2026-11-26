#!/usr/bin/env python3
"""Planning stream: the SHADOW cycle body (intelligence/shadow_cycle.py) on the shared fixtures. SYNTHETIC data only.

  [1] SYNTHETIC_TEST decisions accepted explicitly: charge_target, overnight_demand, predicted_day_load,
      predicted_morning_soc (and pv_tomorrow) OK, with a confidence and reasons, valid for a bounded time; an item
      resting on a dongle input never valid past the quality layer's liveness bound, whatever I-D6 allows; nor is
      overnight_demand, which rests on the dongle only through its charge window (the TOU slot table)
  [2] the same decisions under the default acceptance: every gated item BLOCKED (provenance cannot unblock)
  [3] engine_comparison only when charge_target is OK; scorecard_report never contains 'recommended'
  [4] the charge window: a missing TOU slot table and no verified tariff -> charge_target BLOCKED; never the example
      window; two grid runs or a v1 table -> BLOCKED; a verified tariff and no fresh TOU slot table -> charge_target
      BLOCKED CHARGE_WINDOW_UNKNOWN, no number, and no window at all (a verified tariff alone is never a window); the
      grid-charge limit only from limits.max_grid_charge_w (missing -> BLOCKED)
  [5] no example battery value: apply_to_siteconfig None -> every battery-derived item and predicted_morning_soc BLOCKED;
      the V1 comparison runs on the decided configuration; HA reserve helper as the I-D1 floor
  [6] DST (fictional 2030): the fixed rule; a target period across a clock change scaled as I-D9 records
  [7] an INVALID decision: no advice at all, pv_tomorrow unaffected
  [8] a partial or flat tariff is never a window source: current-day-only, peak-only, flat, near-flat and low-spread
      payloads name no cheap run, so the TOU window stands without a named-run check; a whole-day window never
      crashes the cycle
  [9] the TOU window checked against the verified tariff's rate slots (A30): inside the cheap band -> the TOU window
      with INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF; partly or wholly outside -> BLOCK CHARGE_WINDOW_SOURCES_DISAGREE (the
      overlap rule is gone), also when the tariff's cheap run crosses local midnight (ENG-1); inside the window the items
      stay OK (ENG-2: no false disagreement from a cut cheap run); A35: a verified tariff that names no cheap run (one
      shoulder slot, an Agile-like day) BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE when a slot of the TOU window is at least
      the minimum cheap spread above its lowest rate, and leaves the TOU window OK with its WARN otherwise; ENG6-1: import
      rates short of the search period are still checked end to end (judged without the coverage need for the window
      check only: a partly priced window with a conflicting slot BLOCKs, without one it stands with the 'does not price
      the whole TOU window' WARN, a stale payload checks nothing, prices and value keep the need), one day-rates event
      pinned with the TOU slot at the peak (BLOCK whenever the payload prices the window: A38's look-back keeps the
      passed cheap slots; the unpriced-occurrence residual otherwise) and equal to the cheap run (never
      SOURCES_DISAGREE); A38 / N1 end to end over a whole day, N2 (the slot that holds now counts) end to end, R7-E1
      (a slot that straddles now + 24 h counts; one that starts exactly there does not) end to end; A41 (R7-E3): INFO
      CHARGE_WINDOW_NOT_PRICED on exactly the published charge-window items while the window stands without a price
      check of its whole occurrence, absent within the spread, beside INSIDE and on a refused window, also on a
      charge_target BLOCKED for another reason (ENG8-1), and the envelope without it equal in every other respect;
      ENG6-3: the quality layer's WARN code stays beside the BLOCK;
      provenance codes do not contradict; the morning SOC is never below the effective reserve
  [10] apply_to_siteconfig None while the quality layer passes (HA helper 150 %; a 60 kW limit with 60 kW slots): battery items
       BLOCKED, no example value; the TOU power cap lowers the limit; the HA helper raise-only whatever the I-D1 source;
       a malformed pause value
  [11] the event list: not fresh (missing, stale, or UNRESOLVED: a satisfied I-D6 with no limit for it) -> export / Dump
       BLOCKED; with a defined limit (the synthetic I-D6's, tightened in process to a site's stricter one): stale
       vs fresh, validity bounded by the event list (and INPUT_EXPIRING below the refresh margin), the Saving Session
       after the refill starts from the planned window-end SOC (never a level below empty)
  [12] date-scoped validity of predicted_day_load
  [13] published texts: no redaction on the suite's inputs; a value-shaped text is replaced whole and visibly
  [14] a fresh history with an entry the quality layer ignores (junk, None, a record filed under another hour, a record
       with a malformed field): the same published payloads as the same history without that entry, never
       SELF_TEST_FAILED, with the synthetic decisions and with all decisions OPEN (where the PV model learns from the
       unprepared history)
  [15] the grid-charge classification in the cycle (FOUNDATION CONTRACT section 13.5): an unknown slot (a flags bit
       outside 0x1F included, TOU_FLAGS_UNDECODED_BITS), either enable off or unknown, an overlay active or unknown, a
       v1 table, two runs, a run across midnight (also by one slot edge, 23:30-00:30 and 23:55-00:05: PR2-3) or a zero
       slot power
       BLOCK every item that rests on the window (overnight_demand too), pv_tomorrow and predicted_day_load stay OK;
       Grid + Generator and adjacent grid slots are one window; the power cap equals the same limit read directly
  [16] INPUT_EXPIRING and REFRESH_MARGIN_S (section 13.4): an OK item valid for less than 125 s is BLOCKED, items on
       slow inputs stay OK, the envelope is valid for at least the margin whenever an item is OK
  [16b] A31 (section 13.4): the inverter clock offset bounds the validity of the charge-window items (a short I-D6 limit
       gives exactly that validity, or INPUT_EXPIRING below the margin), never overnight_demand's; the supervision
       readings stay out of every item's validity BY DESIGN (their 90 s bound is below the 125 s margin), enforced at
       every compute instead: the worst-case exposure of an OK export / Dump item after a supervision lapse is the time
       to the next compute (while polls arrive about one telemetry poll plus the settle delay plus the compute time, the
       runtime's poll-driven refresh, A23; when the polls stop, the first tick after the last poll plus
       PROPOSED_POLL_ACTIVE_S, at most about 150 s after it; never past the item's own validity)
  [17] the TOU claim (section 13.6): exactly one INFO code on an OK charge_target and predicted_morning_soc, none
       elsewhere; capped at UNCERTAIN; with the cap lifted (test only) CONFIGURED, NOT_EXPECTED and UNCERTAIN by their
       conditions; MORNING_SOC_ASSUMES_CHARGE while not CONFIGURED
  [18] the raise-only reserve preference (section 13.7): a raise to 55 over I-D1 40 gives 55 and PREF_RESERVE_RAISE, 20
       or none leaves 40; mapped but unusable BLOCKs PREF_RESERVE_RAISE_UNKNOWN; DECISION_VALUE_FROM_HELPER for an
       I-D1 taken from the HA helper; ENG-5: the published reserve breakdown keeps the HA helper's own value and names
       the raise as itself (binding reserve_raise, PREF_RESERVE_RAISE), HA_RESERVE_RAISES_USER_RESERVE only when the
       helper binds; every number equals the helper route to the same floor (target, plan, Dump, export, value, V1)
  [19] GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED on the grid-charge items only
  [20] configuration-poll freshness (section 13.3, the planning half): a configuration-poll reading is aged by both
       liveness readings, a stale or missing configuration liveness BLOCKs the TOU items, and the validity takes both
       liveness keys
  [21] published texts of the new cases: none redacted
  [22] register 217 (protection.shutdown_soc_pct) at a finite 0 % (the finite 0 % boundary case: finite but
       uninformative), with I-D2 read from it: I-D2 satisfied (no PHYSICAL_PROTECTION_UNKNOWN), nothing lowered (the
       technical minimum stays the 10 %
       placeholder, the 40 % advisory reserve binds unchanged), 12 % does raise the technical minimum, and the BMS limit
       stays UNKNOWN (nothing claims one)
  [23] R9D-1: no published blocker text says 'tariff window' or 'from a verified tariff' (a verified tariff only
       cross-checks the TOU window): every blocker text of the suite's cases (the no-Grid-slot table among them) and
       every text literal of the engine modules the cycle loads (docstrings aside), so a fallback no case reaches is
       covered too

WP-1 (configuration-poll freshness) is merged: [0] checks that the two WP-1 outputs the planning layer reads are the real
ones (the three TOU readings are I-D6 keys; the quality layer judges the configuration liveness with the fixed 300 s
bound), and the suite runs on the real rules only (the in-process simulation WP-2 used before the merge is removed).
"""

from __future__ import annotations

import ast
import copy
import json
import math
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import daily_plan as dp  # noqa: E402
from intelligence import quality as q  # noqa: E402
from intelligence import shadow_cycle as sc  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.history import History  # noqa: E402
from intelligence.shadow_cycle import judged_reading, run_cycle  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402
from intelligence.timeutil import local_date, local_wall, zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
GATED = ac.ADVICE_ITEMS + ("predicted_morning_soc", "predicted_day_load")
WANT_OK = ("charge_target", "overnight_demand", "predicted_day_load", "predicted_morning_soc", "pv_tomorrow")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def has_key(v, key) -> bool:
    if isinstance(v, dict):
        return key in v or any(has_key(x, key) for x in v.values())
    if isinstance(v, list):
        return any(has_key(x, key) for x in v)
    return False


def codes(env, k) -> set:
    return {c for c, _t in env.item(k).blockers}


# ---------------------------------------------------------------------------------------------------------------------
# the WP-1 outputs the planning layer reads (merged; no simulation)
# ---------------------------------------------------------------------------------------------------------------------
WP1_TOU_KEYS = ("tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state")
CONFIG_LIVENESS_BOUND_S = 300.0          # FOUNDATION CONTRACT section 13.3 (A4)
TOU_ITEMS = ("overnight_demand", "charge_target", "export_event", "dump_to_grid", "predicted_morning_soc")
print("== [0] the WP-1 outputs the planning layer reads are the real ones")
_cl = q.assess_inputs(cf.cycle_inputs(synthetic_recorded=True)).ages.get(sd.CONFIG_LIVENESS_KEY)
check("the three TOU readings are I-D6 keys, and the quality layer judges the configuration-poll liveness in every "
      "assessment with the fixed 300 s bound (no in-process simulation)",
      all(k in sd.FRESHNESS_OVERRIDE_KEYS for k in WP1_TOU_KEYS) and isinstance(_cl, InputState) and _cl.fresh
      and _cl.limit_s == CONFIG_LIVENESS_BOUND_S == q.DQ_PROPOSED.config_liveness_max_age_s
      and sc.freshness_limits is sd.freshness_limits and sc.assess_inputs is q.assess_inputs, str(_cl))
STARTS = ["00:00", "01:00", "04:30", "08:00", "16:00", "19:00"]


def v2(starts=STARTS, sources=("None", "Grid", "None", "None", "None", "None"), targets=None, powers=None, mode="None"):
    """A schema v2 TOU table: six rows from six start times and six source texts, flags agreeing with the texts."""
    targets = targets or [80.0 if s in ("Grid", "Grid + Generator") else 20.0 for s in sources]
    powers = powers or [cf.GRID_CHARGE_LIMIT_W] * 6
    return [{"slot": i + 1, "start": starts[i], "end": starts[(i + 1) % 6], "target_soc_pct": targets[i],
             "charge_source": sources[i], "flags_raw": ac.TOU_CHARGE_SOURCE_BITS.get(sources[i], 0) | ac.TOU_MODE_BITS[mode],
             "mode": mode, "power_w": powers[i]} for i in range(6)]


def with_table(inputs, table):
    return ph.with_reading(inputs, "tou.slot_table", table, age_s=cf.POLL_AGE_S)


print("== [1] synthetic decisions accepted explicitly")
inp = cf.cycle_inputs(synthetic_recorded=True)
env = run_cycle(inp)
check("the cycle status is OK and SHADOW", env.status == "OK" and env.mode == "SHADOW" and env.applies_nothing is True, env.status)
for k in WANT_OK:
    v = env.item(k)
    check(f"{k}: OK with a finite value, a confidence and reasons", v.status == "OK" and isinstance(v.value, float)
          and v.confidence in ("LOW", "MEDIUM", "HIGH") and len(v.reason_codes) >= 1, f"{v.status} {v.value} {v.confidence} {v.reason_codes}")
ok_views = [v for v in env.items + env.forecasts if v.status == "OK"]
check("every OK item is valid from now for at most the PROPOSED 900 s", all(inp.now <= v.valid_until <= inp.now + timedelta(seconds=900)
                                                                           for v in ok_views))
check("the envelope is valid until its first OK item expires", env.valid_until == min(v.valid_until for v in ok_views))
# the dongle liveness bound: the quality layer judges every dongle input stale once the poll text is older than its bound,
# so an item resting on a dongle input is never valid longer than that bound minus the liveness age (whatever I-D6 allows)
LIVE_LEFT_S = q.DQ_PROPOSED.liveness_max_age_s - cf.POLL_AGE_S


def dongle_ok(e, i) -> list:
    """The OK items and forecasts of `e` that rest on a dongle input (their required inputs carry the liveness reading)."""
    return [v for v in e.items + e.forecasts if v.status == "OK"
            and sd.LIVENESS_KEY in sd.required_inputs(v.key, i.decisions, i.accept_provenance).readings]


dk = dongle_ok(env, inp)
check("an OK item resting on a dongle input is valid for at most the liveness bound minus the liveness age",
      bool(dk) and all(v.valid_until <= inp.now + timedelta(seconds=LIVE_LEFT_S) for v in dk),
      str({v.key: (v.valid_until - inp.now).total_seconds() for v in dk}))
long_d6 = cf.synthetic_decisions().with_decision("D6", sd.FreshnessOverrides(
    {k: 900.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None}), sd.Provenance.SYNTHETIC_TEST)
inp9 = cf.cycle_inputs(decisions=long_d6, accept_provenance=cf.SYNTHETIC_ACCEPT)
env9 = run_cycle(inp9)
dk9 = dongle_ok(env9, inp9)
ct9 = env9.item("charge_target")
check("... also when I-D6 gives the dongle inputs the 900 s ceiling: the liveness bound binds (charge_target valid for exactly "
      "the bound minus the liveness age)",
      bool(dk9) and ct9.status == "OK" and ct9.valid_until == inp9.now + timedelta(seconds=LIVE_LEFT_S)
      and all(v.valid_until <= inp9.now + timedelta(seconds=LIVE_LEFT_S) for v in dk9),
      str({v.key: (v.valid_until - inp9.now).total_seconds() for v in dk9}))
t_late = inp9.now + timedelta(seconds=LIVE_LEFT_S + 10.0)
live0 = next(r for r in inp9.site_readings if r.key == sd.LIVENESS_KEY)
late = cf.cycle_inputs(decisions=long_d6, accept_provenance=cf.SYNTHETIC_ACCEPT, now=t_late)
late_env = run_cycle(replace(late, site_readings=tuple(live0 if r.key == sd.LIVENESS_KEY else r for r in late.site_readings)))
check("... and by the time a cycle on the same frozen poll text refuses charge_target (INPUT_NOT_FRESH), the earlier result "
      "is no longer valid", late_env.item("charge_target").status == "BLOCKED"
      and "INPUT_NOT_FRESH" in codes(late_env, "charge_target") and ct9.valid_until < t_late,
      f"{late_env.item('charge_target').status} {sorted(codes(late_env, 'charge_target'))[:4]} {ct9.valid_until}")
# overnight_demand's period is the charge window, so it rests on the window's source readings; read from the TOU slot table
# (a dongle reading) the window binds it to the liveness bound too, although its own required inputs name no dongle input
od, od9 = env.item("overnight_demand"), env9.item("overnight_demand")
check("overnight_demand rests on the charge window: on the TOU fixture it is valid for at most the liveness bound minus the "
      "liveness age", od.status == "OK" and od.valid_until <= inp.now + timedelta(seconds=LIVE_LEFT_S),
      f"{od.status} {(od.valid_until - inp.now).total_seconds()}")
ver_inp = ph.verified_inputs(synthetic_recorded=True)               # the same TOU window, checked by a named run
odv = run_cycle(ver_inp).item("overnight_demand")
imp_st = judged_reading(ver_inp, "tariff.import_rates")
check("... and with the window checked by a verified tariff's named run, at most the import rates' remaining freshness",
      odv.status == "OK" and imp_st.fresh
      and odv.valid_until <= ver_inp.now + timedelta(seconds=imp_st.limit_s - imp_st.age_s),
      f"{odv.status} {(odv.valid_until - ver_inp.now).total_seconds()} {imp_st.limit_s} {imp_st.age_s}")
check("... also when I-D6 gives the dongle inputs the 900 s ceiling: overnight_demand valid for exactly the bound minus the "
      "liveness age", od9.status == "OK" and od9.valid_until == inp9.now + timedelta(seconds=LIVE_LEFT_S),
      f"{od9.status} {(od9.valid_until - inp9.now).total_seconds()}")
od_late = {}
for dt in (LIVE_LEFT_S + 1.0, LIVE_LEFT_S + 10.0):
    lt = cf.cycle_inputs(decisions=long_d6, accept_provenance=cf.SYNTHETIC_ACCEPT, now=inp9.now + timedelta(seconds=dt))
    od_late[dt] = run_cycle(replace(lt, site_readings=tuple(live0 if r.key == sd.LIVENESS_KEY else r
                                                            for r in lt.site_readings))).item("overnight_demand")
check("... and by the time a cycle on the same frozen poll text refuses overnight_demand (1 s and 10 s past the bound), the "
      "earlier result is no longer valid",
      all(v.status == "BLOCKED" and od9.valid_until < inp9.now + timedelta(seconds=dt) for dt, v in od_late.items()),
      str({dt: v.status for dt, v in od_late.items()}) + f" {od9.valid_until}")
ct = env.item("charge_target")
check("charge_target rests on the V1.1 advisor (its summary is the V1.1 recommendation)",
      ct.summary["inputs_used"]["battery_capacity_kwh"] == 20.0 and ct.summary["reserve"]["effective_pct"] == 30.0
      and ct.value == ct.summary["target_soc_pct"], str(ct.summary.get("inputs_used")))
check("the charge window comes from the TOU slot table (01:00-04:30), with a WARN reason code, not the example window",
      ct.summary["window"] == ["2030-01-16T01:00:00+00:00", "2030-01-16T04:30:00+00:00"]
      and "CHARGE_WINDOW_FROM_TOU_TABLE" in ct.reason_codes
      and env.tariff["window"] == {"start": "2030-01-16T01:00:00+00:00", "end": "2030-01-16T04:30:00+00:00"}, str(env.tariff))
check("the planned SOC is never below the effective reserve plus margin (morning SOC p10 <= p50 <= p90)",
      (lambda m: m.p10 <= m.value <= m.p90)(env.item("predicted_morning_soc")))
check("the plan block is published with an OK charge target", env.plan is not None
      and set(env.plan) == {"precharge_by", "headroom_ceiling_pct", "reserve_runout_at"}
      and env.plan["headroom_ceiling_pct"] >= 35.0, str(env.plan))
check("drift and calibration stay None", env.drift is None and env.calibration is None)
check("accuracy comes from outcome_metrics", env.accuracy == {"mae_7d": 1.1, "coverage_7d": 0.8, "n": 7})
check("export advice is never OK without an event ahead (BLOCKED or NO_ADVICE)", env.item("export_event").status in ("BLOCKED", "NO_ADVICE"))
nev = run_cycle(cf.cycle_inputs(synthetic_recorded=True, missing_key="tariff.events"))
check("a missing event list: export and Dump advice BLOCKED (TARIFF_EVENTS_NOT_FRESH), the charge target unaffected",
      all(nev.item(k).status == "BLOCKED" and "TARIFF_EVENTS_NOT_FRESH" in codes(nev, k) for k in ("export_event", "dump_to_grid"))
      and nev.item("charge_target").status == "OK")
pay = ac.to_entity_payloads(env)
check("the payloads are strict JSON within the byte budget", json.dumps({k: list(v) for k, v in pay.items()}, allow_nan=False)
      and all(ac.entity_json_bytes(*v) <= ac.MAX_ENTITY_JSON_BYTES for v in pay.values()))

print("== [2] the default acceptance")
dflt = run_cycle(cf.cycle_inputs(decisions=cf.synthetic_decisions(), accept_provenance=sd.DEFAULT_ACCEPT_PROVENANCE))
check("the same SYNTHETIC_TEST decisions under the default acceptance: every gated item BLOCKED with DECISION_*_OPEN",
      all(dflt.item(k).status == "BLOCKED" and any(c.startswith("DECISION_") for c in codes(dflt, k)) for k in GATED),
      str({k: dflt.item(k).status for k in GATED}))
check("... no plan, value, engine comparison or price; provenance_ok False", dflt.plan is None and dflt.value is None
      and dflt.engine_comparison is None and dflt.tariff["price_range"] is None and dflt.provenance_ok is False)

print("== [3] engine_comparison and scorecard_report")
variants = {
    "all OPEN": cf.cycle_inputs(),
    "synthetic": inp,
    "synthetic, no grid limit": cf.cycle_inputs(synthetic_recorded=True, missing_key="limits.max_grid_charge_w"),
    "synthetic, no TOU table": cf.cycle_inputs(synthetic_recorded=True, missing_key="tou.slot_table"),
    "synthetic + verified tariff": ph.verified_inputs(synthetic_recorded=True),
    "synthetic, stale liveness": cf.cycle_inputs(synthetic_recorded=True, stale_liveness=True),
    "synthetic, no history": cf.cycle_inputs(synthetic_recorded=True, missing_key="history"),
}
envs = {n: run_cycle(x) for n, x in variants.items()}
check("engine_comparison appears exactly when charge_target is OK",
      all((e.engine_comparison is not None) == (e.item("charge_target").status == "OK") for e in envs.values()),
      str({n: (e.item("charge_target").status, e.engine_comparison is not None) for n, e in envs.items()}))
check("... and it names the V1.1 charge target as the authority",
      envs["synthetic"].engine_comparison["authority"] == "V1.1 charge_target"
      and envs["synthetic"].engine_comparison["v11_target_soc_pct"] == envs["synthetic"].item("charge_target").value)
check("scorecard_report never contains 'recommended' (any depth)", all(not has_key(e.scorecard_report, "recommended") for e in envs.values()))
sr = envs["synthetic"].scorecard_report
check("scorecard_report is the V1 report shape (forecast records, feature hash) from the decided configuration",
      isinstance(sr, dict) and sr.get("mode") == "SHADOW" and sr.get("feature_hash") and sr.get("forecast_records")
      and sr.get("shadow_scope") == "decided configuration")
check("... and is not published in any entity payload", all("scorecard_report" not in json.dumps(v) for v in ac.to_entity_payloads(envs["synthetic"]).values()))
check("with all OPEN there is no V1 report at all (no learning history without I-D8)", envs["all OPEN"].scorecard_report is None)

print("== [4] the charge window and the grid-charge limit")
nt = envs["synthetic, no TOU table"]
check("a missing TOU slot table and no verified tariff: charge_target BLOCKED (no window), never the example window",
      nt.item("charge_target").status == "BLOCKED" and codes(nt, "charge_target") & {"CHARGE_WINDOW_UNKNOWN"}
      and nt.tariff["window"] is None, str(codes(nt, "charge_target")))
check("... and so are predicted_morning_soc, export_event and dump_to_grid",
      all(nt.item(k).status == "BLOCKED" for k in ("predicted_morning_soc", "export_event", "dump_to_grid")))
ng = envs["synthetic, no grid limit"]
check("a missing limits.max_grid_charge_w: charge_target BLOCKED", ng.item("charge_target").status == "BLOCKED"
      and codes(ng, "charge_target") & {"INPUT_NOT_FRESH", "GRID_CHARGE_LIMIT_UNKNOWN"}, str(codes(ng, "charge_target")))
amb = run_cycle(with_table(cf.cycle_inputs(synthetic_recorded=True), v2(sources=("None", "Grid", "None", "Grid", "None", "None"))))
check("two separate TOU grid-charge runs: BLOCKED TOU_MULTIPLE_GRID_WINDOWS (never a guess)",
      amb.item("charge_target").status == "BLOCKED" and "TOU_MULTIPLE_GRID_WINDOWS" in codes(amb, "charge_target"),
      str(amb.item("charge_target").reason_codes))
v1t = run_cycle(with_table(cf.cycle_inputs(synthetic_recorded=True), [{"slot": 1, "start": "01:00", "end": "04:30",
                                                                       "target_soc_pct": 80}]))
check("a v1 table (start / end / target only, the old fixture): BLOCKED TOU_TABLE_LEGACY_SCHEMA, never a window",
      v1t.item("charge_target").status == "BLOCKED" and "TOU_TABLE_LEGACY_SCHEMA" in codes(v1t, "charge_target")
      and v1t.tariff["window"] is None, str(codes(v1t, "charge_target")))
flag = run_cycle(with_table(cf.cycle_inputs(synthetic_recorded=True), v2(["00:00", "02:00", "05:00", "08:00", "16:00", "19:00"])))
check("... the one grid-charge slot is the window", flag.item("charge_target").status == "OK"
      and flag.tariff["window"] == {"start": "2030-01-16T02:00:00+00:00", "end": "2030-01-16T05:00:00+00:00"}, str(flag.tariff))
vt = envs["synthetic + verified tariff"]
check("a verified tariff's named run checks the TOU window (CHARGE_WINDOW_FROM_TARIFF) and the tariff block",
      vt.item("charge_target").status == "OK"
      and "CHARGE_WINDOW_FROM_TARIFF" in vt.item("charge_target").reason_codes and vt.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION")
# fail closed for now (CCR-DQ-2 / CCR-PLAN-2 deferred): a charge-window item needs a fresh TOU table also beside a verified
# tariff, which only checks the TOU window, and its blocker text says so (never "no verified tariff" beside a VERIFIED one)
vnt = run_cycle(ph.without(ph.verified_inputs(synthetic_recorded=True), "tou.slot_table"))
vct = vnt.item("charge_target")
vtext = dict(vct.blockers).get("CHARGE_WINDOW_UNKNOWN", "")
# changed on purpose (WP-2): a verified tariff alone is never a charge window, so the tariff block shows no window either
check("a verified tariff and no fresh TOU slot table: charge_target BLOCKED CHARGE_WINDOW_UNKNOWN with no number, and no "
      "window at all (a verified tariff alone is never a window; the tariff block keeps its provenance); the blocker text "
      "says a fresh TOU table is needed also with a verified tariff",
      vct.status == "BLOCKED" and "CHARGE_WINDOW_UNKNOWN" in codes(vnt, "charge_target") and vct.value is None
      and vct.summary is None and vnt.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION" and vnt.tariff["window"] is None
      and vnt.item("overnight_demand").status == "BLOCKED"
      and "verified tariff" in vtext and "no verified tariff" not in vtext and not any(ch.isdigit() for ch in vtext),
      f"{vct.status} {sorted(codes(vnt, 'charge_target'))[:4]} {vct.value} {vtext!r} {vnt.tariff}")
lim = run_cycle(ph.with_reading(cf.cycle_inputs(synthetic_recorded=True), "limits.max_grid_charge_w", 2000.0))
check("the grid-charge limit comes from the reading (a lower limit lowers what the window can reach)",
      lim.item("charge_target").summary["achievable_soc_pct"] <= envs["synthetic"].item("charge_target").summary["achievable_soc_pct"]
      and lim.item("charge_target").summary["achievable_soc_pct"] < 100.0, str(lim.item("charge_target").summary["achievable_soc_pct"]))

print("== [5] no example battery value")
snap = cf.synthetic_decisions().with_decision("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT), sd.Provenance.SYNTHETIC_TEST)
p_none = run_cycle(cf.cycle_inputs(decisions=snap, accept_provenance=cf.SYNTHETIC_ACCEPT, missing_key="protection.shutdown_soc_pct"))
check("apply_to_siteconfig gives None (I-D2 from a sensor that is missing): every battery-derived item and "
      "predicted_morning_soc BLOCKED, no plan / value / comparison",
      all(p_none.item(k).status == "BLOCKED" for k in ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc"))
      and p_none.plan is None and p_none.value is None and p_none.engine_comparison is None,
      str({k: sorted(codes(p_none, k))[:3] for k in ("charge_target", "predicted_morning_soc")}))
check("... while overnight_demand and predicted_day_load (no battery value) stay OK",
      p_none.item("overnight_demand").status == "OK" and p_none.item("predicted_day_load").status == "OK")
check("the V1 comparison ran on the decided configuration (capacity 20, not the example 31.7)",
      envs["synthetic"].scorecard_report["config_hash"] != inp.base_cfg.config_hash())
ha = cf.synthetic_decisions().with_decision("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), sd.Provenance.SYNTHETIC_TEST)
hr = run_cycle(cf.cycle_inputs(decisions=ha, accept_provenance=cf.SYNTHETIC_ACCEPT))
check("I-D1 = the HA reserve helper (fresh 20 %): the effective reserve is the helper, raise-only above the technical minimum",
      hr.item("charge_target").status == "OK" and hr.item("charge_target").summary["reserve"]["effective_pct"] == 20.0
      and hr.item("charge_target").summary["reserve"]["binding"] == "ha_reserve", str(hr.item("charge_target").summary.get("reserve")))
hm = run_cycle(cf.cycle_inputs(decisions=ha, accept_provenance=cf.SYNTHETIC_ACCEPT, missing_key="reserve.ha_minimum_soc"))
check("... and without a fresh helper value the battery items BLOCK (never the example 40 or the placeholder)",
      all(hm.item(k).status == "BLOCKED" for k in ("charge_target", "predicted_morning_soc")))

print("== [6] DST (fictional 2030)")
EVE_A = datetime(2030, 10, 26, 20, 0, tzinfo=UTC)
d9r = run_cycle(cf.cycle_inputs(now=EVE_A, synthetic_recorded=True))
check("eve of 27 Oct 2030 with I-D9 recorded: a window starting in the repeated hour (01:00) BLOCKs (fixed rule)",
      all("DST_BOUNDARY_IN_CHANGED_HOUR" in codes(d9r, k) for k in ("charge_target", "overnight_demand", "predicted_morning_soc")))
d9o = run_cycle(cf.cycle_inputs(now=EVE_A, decisions=cf.synthetic_decisions().without("D9"), accept_provenance=cf.SYNTHETIC_ACCEPT))
check("... and with I-D9 OPEN: DECISION_D9_OPEN", all("DECISION_D9_OPEN" in codes(d9o, k) for k in ("charge_target", "overnight_demand")))
W35 = v2(["00:00", "03:00", "05:00", "08:00", "16:00", "19:00"])         # one Grid slot 03:00-05:00


def dst_case(now, rule):
    ds = cf.synthetic_decisions().with_decision("D9", sd.DSTPolicy(sd.NORMALISE_TO_NOMINAL, rule), sd.Provenance.SYNTHETIC_TEST)
    return run_cycle(ph.with_reading(cf.cycle_inputs(now=now, decisions=ds, accept_provenance=cf.SYNTHETIC_ACCEPT), "tou.slot_table",
                                     W35, age_s=20.0))


AUT = datetime(2030, 10, 26, 0, 30, tzinfo=UTC)       # the coming period 05:00 BST 26 Oct -> 03:00 GMT 27 Oct lasts 23 h
SPR = datetime(2030, 3, 30, 0, 30, tzinfo=UTC)        # 05:00 GMT 30 Mar -> 03:00 BST 31 Mar lasts 21 h
for label, now, rule, want in (("autumn, SCALE_UP_ONLY", AUT, sd.SCALE_UP_ONLY, 23 / 22), ("autumn, SCALE_TO_ACTUAL", AUT, sd.SCALE_TO_ACTUAL, 23 / 22),
                               ("spring, SCALE_UP_ONLY", SPR, sd.SCALE_UP_ONLY, 1.0), ("spring, SCALE_TO_ACTUAL", SPR, sd.SCALE_TO_ACTUAL, 21 / 22)):
    e = dst_case(now, rule)
    od = e.item("overnight_demand")
    f = (od.summary or {}).get("dst_target_factor")
    check(f"{label}: overnight demand scaled by {want:.4f} (DST_TARGET_SCALED), the charge target still OK",
          od.status == "OK" and f is not None and abs(f - want) < 1e-3 and "DST_TARGET_SCALED" in od.reason_codes
          and e.item("charge_target").status == "OK", f"{od.status} {f} {od.reason_codes[:4]} {e.item('charge_target').status}")

print("== [7] an INVALID decision")
bad = sd.DecisionSet({**cf.synthetic_decisions().decisions,
                      "D4": sd.DecisionSet.from_mapping({"D4": {"provenance": "SYNTHETIC_TEST", "value": {"pct": 99}}}, source="test").get("D4")})
inv = run_cycle(cf.cycle_inputs(decisions=bad, accept_provenance=cf.SYNTHETIC_ACCEPT))
check("an INVALID I-D4: status BLOCKED, every advice item and gated forecast BLOCKED (SITE_DECISIONS_INVALID)",
      inv.status == "BLOCKED" and all(inv.item(k).status == "BLOCKED" and "SITE_DECISIONS_INVALID" in codes(inv, k) for k in GATED))
check("... pv_tomorrow (no decision) stays OK; no plan, value or comparison", inv.item("pv_tomorrow").status == "OK"
      and inv.plan is None and inv.value is None and inv.engine_comparison is None)

print("== [8] a partial or flat tariff is never a window source")
D15 = datetime(2030, 1, 15).date()
TOU_W = ["2030-01-16T01:00:00+00:00", "2030-01-16T04:30:00+00:00"]
TOU_WINDOW = {"start": TOU_W[0], "end": TOU_W[1]}          # the same window in the tariff block's {start, end} shape


def tariff_case(now, payload):
    return run_cycle(ph.with_reading(cf.cycle_inputs(now=now, synthetic_recorded=True), "tariff.import_rates", payload))


def falls_back(e, code):
    ct = e.item("charge_target")
    return (e.tariff["provenance"] == "NOT_VERIFIED" or code != "TARIFF_COVERAGE_SHORT") and e.tariff["window"] == TOU_WINDOW \
        and ct.status == "OK" and ct.summary["window"] == TOU_W and "CHARGE_WINDOW_FROM_TOU_TABLE" in ct.reason_codes \
        and "CHARGE_WINDOW_FROM_TARIFF" not in ct.reason_codes and code in e.reason_codes


cur_day = ph.go_like_rates(D15, 1)                         # today's rates only: the next-day event not yet published
for hh, mm in ((18, 0), (21, 0), (22, 30)):
    e = tariff_case(datetime(2030, 1, 15, hh, mm, tzinfo=UTC), cur_day)
    check(f"current-day rates only at {hh:02d}:{mm:02d}: not verified (TARIFF_COVERAGE_SHORT), no price, no value; the window "
          "is the TOU slot, never a run that ends at midnight", falls_back(e, "TARIFF_COVERAGE_SHORT")
          and e.tariff["price_range"] is None and e.value is None, f"{e.tariff} {e.item('charge_target').reason_codes[:6]}")
peak = [r for r in ph.go_like_rates(D15, 2) if r["start"][:13] in ("2030-01-16T16", "2030-01-16T17", "2030-01-16T18")]
e = tariff_case(cf.NOW, peak)
check("only tomorrow's 16:00-19:00 peak rows: not verified (coverage), the window is the TOU slot", falls_back(e, "TARIFF_COVERAGE_SHORT"),
      f"{e.tariff} {e.item('charge_target').reason_codes[:6]}")
flat = ph.go_like_rates(D15, 2, cheap=(0, 0), cheap_gbp=0.25, peak_gbp=0.25)
e = tariff_case(cf.NOW, flat)
check("a flat verified tariff names no cheap run (TARIFF_CHEAP_RUN_TOO_LONG): the TOU slot; the price range is honest",
      falls_back(e, "TARIFF_CHEAP_RUN_TOO_LONG") and e.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION"
      and e.tariff["price_range"] == [25.0, 25.0], f"{e.tariff} {list(e.reason_codes)[:6]}")
near = ph.go_like_rates(D15, 2, cheap_gbp=0.250, peak_gbp=0.254)
e = tariff_case(cf.NOW, near)
check("a near-flat two-rate tariff (25.0 / 25.4 p): one run of the whole period, too long: the TOU slot",
      falls_back(e, "TARIFF_CHEAP_RUN_TOO_LONG"), f"{e.tariff} {list(e.reason_codes)[:6]}")
low = ph.go_like_rates(D15, 2, cheap_gbp=0.250, peak_gbp=0.260)
e = tariff_case(cf.NOW, low)
check("a two-rate tariff 1 p apart (below the PROPOSED spread): TARIFF_NO_PRICE_SPREAD, the TOU slot",
      falls_back(e, "TARIFF_NO_PRICE_SPREAD"), f"{e.tariff} {list(e.reason_codes)[:6]}")
for hh, mm in ((0, 10), (0, 40)):
    now = datetime(2030, 1, 16, hh, mm, tzinfo=UTC)
    e = tariff_case(now, ph.go_like_rates(D15, 3, cheap=(0, 0), cheap_gbp=0.25, peak_gbp=0.25))
    check(f"a flat tariff just after midnight ({hh:02d}:{mm:02d}): no whole-day window, no internal error, pv_tomorrow unaffected",
          e.status not in ("SELF_TEST_FAILED",) and "CYCLE_INTERNAL_ERROR" not in [c for c, _t in e.blockers]
          and e.item("charge_target").status == "OK" and e.tariff["window"] == TOU_WINDOW, f"{e.status} {e.tariff}")
whole = run_cycle(with_table(cf.cycle_inputs(synthetic_recorded=True), v2(sources=("Grid",) * 6)))
check("a whole-day TOU grid run (every slot Grid) is refused (CHARGE_WINDOW_NOT_REPRESENTABLE), never a crash; pv_tomorrow OK",
      whole.status != "SELF_TEST_FAILED" and whole.item("charge_target").status == "BLOCKED"
      and "CHARGE_WINDOW_NOT_REPRESENTABLE" in whole.item("charge_target").reason_codes
      and whole.item("pv_tomorrow").status == "OK", f"{whole.status} {whole.item('charge_target').reason_codes[:6]}")
_orig_choose = dp.choose_charge_window


def _whole_day(now, tz, *a, **kw):
    s = local_wall(local_date(now, tz), 0, tz)
    return dp.ChargeWindow(dp.SOURCE_TOU_TABLE, s, s + timedelta(days=1), (0, 1440),
                           sd.InputState(sd.CHARGE_WINDOW_KEY, (0, 1440), True, 20.0, 300.0)), []


dp.choose_charge_window = _whole_day                     # defence in depth: a whole-day window that slipped through
try:
    wd = run_cycle(cf.cycle_inputs(synthetic_recorded=True))
finally:
    dp.choose_charge_window = _orig_choose
check("... and if a whole-day window ever reached the overnight demand, only that item and what rests on it block "
      "(OVERNIGHT_PERIOD_INVALID); no SELF_TEST_FAILED, pv_tomorrow OK",
      wd.status != "SELF_TEST_FAILED" and wd.item("overnight_demand").status == "BLOCKED"
      and "OVERNIGHT_PERIOD_INVALID" in codes(wd, "overnight_demand") and wd.item("charge_target").status == "BLOCKED"
      and wd.item("pv_tomorrow").status == "OK", f"{wd.status} {codes(wd, 'overnight_demand')}")

print("== [9] the TOU window checked against the verified tariff's rate slots")
VER = ph.verified_inputs(synthetic_recorded=True)
same = run_cycle(VER)
sct = same.item("charge_target")
check("the same window from both: CHARGE_WINDOW_FROM_TARIFF only (the quality layer's TOU-table code is dropped), no "
      "disagreement", "CHARGE_WINDOW_FROM_TARIFF" in sct.reason_codes and "CHARGE_WINDOW_FROM_TOU_TABLE" not in sct.reason_codes
      and "CHARGE_WINDOW_SOURCES_DISAGREE" not in same.reason_codes, str(sct.reason_codes))
check("... and the window is checked against the tariff: INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF on the charge-window items",
      all("CHARGE_WINDOW_TOU_INSIDE_TARIFF" in same.item(k).reason_codes for k in ("charge_target", "predicted_morning_soc"))
      and "CHARGE_WINDOW_TOU_INSIDE_TARIFF" not in same.item("pv_tomorrow").reason_codes)
narrow_slot = v2(["00:00", "02:00", "03:00", "08:00", "16:00", "19:00"])        # one Grid slot 02:00-03:00
mis = run_cycle(with_table(VER, narrow_slot))
tou_only = run_cycle(with_table(cf.cycle_inputs(synthetic_recorded=True), narrow_slot))
mct, tct = mis.item("charge_target"), tou_only.item("charge_target")
# The expectation here changed on purpose (WP-2, FOUNDATION CONTRACT 13.5): the TOU window 02:00-03:00 lies inside the
# verified cheap run 01:00-04:30, so the window IS the TOU window, confirmed by the tariff (INFO
# CHARGE_WINDOW_TOU_INSIDE_TARIFF). It was "their overlap with a WARN CHARGE_WINDOW_SOURCES_DISAGREE": the overlap rule
# is deleted, and CHARGE_WINDOW_SOURCES_DISAGREE is now always a BLOCK (next two checks).
check("a verified tariff (01:00-04:30) and a TOU grid slot 02:00-03:00 inside it: the window is the TOU window with INFO "
      "CHARGE_WINDOW_TOU_INSIDE_TARIFF, no disagreement, so the reachable SOC is never more than the inverter's slot allows",
      mct.status == "OK" and mct.summary["window"] == ["2030-01-16T02:00:00+00:00", "2030-01-16T03:00:00+00:00"]
      and "CHARGE_WINDOW_TOU_INSIDE_TARIFF" in mct.reason_codes and "CHARGE_WINDOW_SOURCES_DISAGREE" not in mct.reason_codes
      and "CHARGE_WINDOW_SOURCES_DISAGREE" not in mis.reason_codes
      and mct.summary["achievable_soc_pct"] == (tct.summary or {}).get("achievable_soc_pct"),
      f"{mct.summary and mct.summary['window']} {mct.reason_codes[:6]} {mct.summary and mct.summary['achievable_soc_pct']}")
partial = run_cycle(with_table(VER, v2(["00:00", "00:30", "02:00", "08:00", "16:00", "19:00"])))   # Grid 00:30-02:00
check("a TOU grid slot 00:30-02:00 that extends outside the cheap run 01:00-04:30: BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE "
      "(it used to be the overlap 01:00-02:00 with a WARN)",
      all(partial.item(k).status == "BLOCKED" and "CHARGE_WINDOW_SOURCES_DISAGREE" in codes(partial, k) for k in TOU_ITEMS)
      and partial.tariff["window"] is None and partial.item("pv_tomorrow").status == "OK",
      str({k: sorted(codes(partial, k))[:3] for k in ("charge_target", "overnight_demand")}))
apart = run_cycle(with_table(VER, v2(["00:00", "13:00", "15:00", "16:00", "17:00", "19:00"])))     # Grid 13:00-15:00
check("... a TOU grid slot that does not overlap the cheap run: BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE (no window assumed)",
      apart.item("charge_target").status == "BLOCKED" and "CHARGE_WINDOW_SOURCES_DISAGREE" in codes(apart, "charge_target")
      and apart.item("predicted_morning_soc").status == "BLOCKED", str(codes(apart, "charge_target")))
# A30 (ENG-1): a verified cheap run across local midnight (23:30-05:30) and a TOU grid slot at peak price (06:00-08:00)
CROSS_RATES = ph.go_like_rates(D15 - timedelta(days=1), 3, cheap=(0, 0))
for r in CROSS_RATES:
    _m = int(r["start"][11:13]) * 60 + int(r["start"][14:16])
    if _m >= 1410 or _m < 330:
        r["value_inc_vat"] = ph.CHEAP_GBP
cross_in = run_cycle(ph.with_reading(VER, "tariff.import_rates", CROSS_RATES))
cross_out = run_cycle(ph.with_reading(with_table(VER, v2(["00:00", "06:00", "08:00", "10:00", "16:00", "19:00"])),
                                      "tariff.import_rates", CROSS_RATES))
check("a verified cheap run across local midnight (23:30-05:30) holding the TOU window 01:00-04:30: OK, INFO "
      "CHARGE_WINDOW_TOU_INSIDE_TARIFF, no CHARGE_WINDOW_CROSSES_MIDNIGHT anywhere",
      cross_in.item("charge_target").status == "OK" and cross_in.tariff["window"] == TOU_WINDOW
      and "CHARGE_WINDOW_TOU_INSIDE_TARIFF" in cross_in.item("charge_target").reason_codes
      and "CHARGE_WINDOW_CROSSES_MIDNIGHT" not in cross_in.reason_codes, str(cross_in.item("charge_target").reason_codes[:8]))
check("... the same tariff with the TOU grid slot 06:00-08:00 at peak price: every item on the window BLOCKED "
      "CHARGE_WINDOW_SOURCES_DISAGREE with no number, no value block (ENG-1: it was OK at 100 % with a value projected)",
      all(cross_out.item(k).status == "BLOCKED" and cross_out.item(k).value is None
          and "CHARGE_WINDOW_SOURCES_DISAGREE" in codes(cross_out, k) for k in TOU_ITEMS)
      and cross_out.value is None and cross_out.tariff["window"] is None
      and "CHARGE_WINDOW_FROM_TOU_TABLE" not in cross_out.reason_codes
      and "CHARGE_WINDOW_CROSSES_MIDNIGHT" not in cross_out.reason_codes,
      str({k: sorted(codes(cross_out, k))[:3] for k in ("charge_target", "dump_to_grid")}))
# A30 (ENG-2): inside the window the tariff's cheap run as cheap_window finds it is cut (to the slots still running, then
# to tomorrow's run cut by the 24 h horizon); the check uses the rate slots, so the items never disagree there
in_bad = []
for _k in range(8):
    _now = datetime(2030, 1, 16, 0, 30, tzinfo=UTC) + timedelta(minutes=30 * _k)
    _x = ph.with_reading(cf.cycle_inputs(synthetic_recorded=True, now=_now), "tariff.import_rates",
                         ph.go_like_rates(D15, 3))
    _e = run_cycle(ph.with_reading(_x, "tariff.export_rates", ph.flat_export(D15, 3)))
    _ct = _e.item("charge_target")
    if _ct.status != "OK" or _ct.summary["window"] != TOU_W or "CHARGE_WINDOW_SOURCES_DISAGREE" in _e.reason_codes \
            or "CHARGE_WINDOW_TOU_INSIDE_TARIFF" not in _ct.reason_codes:
        in_bad.append((_now.strftime("%H:%M"), _ct.status, sorted(codes(_e, "charge_target"))[:2]))
check("tariff and TOU both 01:00-04:30, from 00:30 to 04:00 every 30 min (in the window too): charge_target OK on today's "
      "TOU window, checked against the tariff, never CHARGE_WINDOW_SOURCES_DISAGREE (ENG-2: BLOCKED 01:30-04:00)",
      in_bad == [], str(in_bad))
# A35 (R1-ENG-1 / F1): a verified tariff that names no cheap run still checks the TOU window's priced slots, end to end
PEAK_TABLE = v2(["00:00", "17:00", "19:00", "20:00", "21:00", "22:00"])         # Grid 17:00-19:00, at the evening peak
SHOULDER_RATES = [dict(r, value_inc_vat=0.09) if r["start"][11:16] == "05:30" else r
                  for r in ph.go_like_rates(D15 - timedelta(days=1), 4, cheap=(30, 330))]     # 7.5 / 30 p, 9 p at 05:30
AGILE_RATES = [dict(r, value_inc_vat=round((22.5 - 12.5 * math.cos(2 * math.pi * (int(r["start"][11:13]) * 60
                                                                                   + int(r["start"][14:16]) - 180) / 1440.0))
                                           / 100.0, 4)) for r in ph.go_like_rates(D15 - timedelta(days=1), 4)]
sh_peak = run_cycle(ph.with_reading(with_table(VER, PEAK_TABLE), "tariff.import_rates", SHOULDER_RATES))
sh_tou = run_cycle(ph.with_reading(VER, "tariff.import_rates", SHOULDER_RATES))
ag_peak = run_cycle(ph.with_reading(with_table(VER, PEAK_TABLE), "tariff.import_rates", AGILE_RATES))
ag_tou = run_cycle(ph.with_reading(VER, "tariff.import_rates", AGILE_RATES))
for name, e in (("a two-rate tariff with one shoulder slot (9 p at 05:30)", sh_peak), ("a smooth Agile-like tariff", ag_peak)):
    check(f"A35: {name} names no cheap run (TARIFF_NO_PRICE_SPREAD) and the TOU grid slot is at the 17:00-19:00 peak: "
          "every item on the window BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE with no number, no value block, no tariff "
          "window (R1-ENG-1 / F1: charge_target was OK at 100 % with a value projected); pv_tomorrow OK",
          e.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION" and "TARIFF_NO_PRICE_SPREAD" in e.reason_codes
          and all(e.item(k).status == "BLOCKED" and e.item(k).value is None
                  and "CHARGE_WINDOW_SOURCES_DISAGREE" in codes(e, k) for k in TOU_ITEMS)
          and e.value is None and e.tariff["window"] is None and e.item("pv_tomorrow").status == "OK",
          str({k: sorted(codes(e, k))[:3] for k in ("charge_target", "predicted_morning_soc")}))
for name, e in (("the shoulder-slot tariff", sh_tou), ("the Agile-like tariff", ag_tou)):
    check(f"... {name} with the TOU grid slot 01:00-04:30 within 2 p of its lowest rate: charge_target and the morning "
          "SOC OK on the TOU window with WARN CHARGE_WINDOW_FROM_TOU_TABLE, never SOURCES_DISAGREE",
          all(e.item(k).status == "OK" and "CHARGE_WINDOW_FROM_TOU_TABLE" in e.item(k).reason_codes
              for k in ("charge_target", "predicted_morning_soc"))
          and e.item("charge_target").summary["window"] == TOU_W and e.tariff["window"] == TOU_WINDOW
          and "CHARGE_WINDOW_SOURCES_DISAGREE" not in e.reason_codes and "TARIFF_NO_PRICE_SPREAD" in e.reason_codes,
          str(e.item("charge_target").reason_codes[:8]))
# ENG6-1 (A30 step 4, A35, contract 13.5): import rates that do not cover the 24 h search period name no cheap run, yet
# the window check reads the slots they price, end to end. The cycle used to judge such a payload NOT_VERIFIED before
# the window check, so the TOU window stood OK ('no verified tariff') whatever its priced slots said. Prices, the tariff
# block and the value keep the coverage need: provenance NOT_VERIFIED, no price range, no value.
_SEEN_WINDOW: list = []


def window_judged(inputs):
    """run_cycle with a spy on the window choice: (the envelope, the status of the import tariff the window check was
    given, that check's findings as (code, severity, text))."""
    def spy(now, tz, imp, *a, **kw):
        cw_, n_ = _orig_choose(now, tz, imp, *a, **kw)
        _SEEN_WINDOW.append((getattr(imp, "status", None), [(f.code, f.severity, f.text) for f in n_]))
        return cw_, n_

    _SEEN_WINDOW.clear()
    dp.choose_charge_window = spy
    try:
        e_ = run_cycle(inputs)
    finally:
        dp.choose_charge_window = _orig_choose
    st_, notes_ = _SEEN_WINDOW[-1] if _SEEN_WINDOW else (None, [])
    return e_, st_, notes_


def tou_warn_texts(notes_) -> list[str]:
    return [t for c, s, t in notes_ if c == "CHARGE_WINDOW_FROM_TOU_TABLE" and s == "WARN"]


def short_case(now, rows, table=None):
    x = ph.with_reading(cf.cycle_inputs(synthetic_recorded=True, now=now), "tariff.import_rates", rows)
    x = ph.with_reading(x, "tariff.export_rates", ph.flat_export(D15 - timedelta(days=1), 4))
    return window_judged(with_table(x, table) if table is not None else x)


def blocked_disagree(e_) -> bool:
    return all(e_.item(k).status == "BLOCKED" and e_.item(k).value is None and "CHARGE_WINDOW_SOURCES_DISAGREE"
               in codes(e_, k) for k in TOU_ITEMS) and e_.value is None and e_.tariff["window"] is None


def unpriced_tariff(e_) -> bool:
    """The coverage need still holds for prices: not verified, no price range, no value, TARIFF_COVERAGE_SHORT shown."""
    return e_.tariff["provenance"] == "NOT_VERIFIED" and e_.tariff["price_range"] is None and e_.value is None \
        and "TARIFF_COVERAGE_SHORT" in e_.reason_codes


D16 = D15 + timedelta(days=1)
PART_RATES = [r for r in ph.go_like_rates(D15, 2) if r["start"] < "2030-01-16T02:00"]   # tomorrow 01:00-02:00 priced
PART_DEAR = [dict(r, value_inc_vat=ph.PEAK_GBP) if r["start"] == "2030-01-16T01:30:00+00:00" else r for r in PART_RATES]
pd_e, pd_st, pd_n = short_case(cf.NOW, PART_DEAR)
check("ENG6-1: rates ending 02:00 tomorrow (short of the search period) whose 01:30 slot inside the TOU window "
      "01:00-04:30 is 30 p beside 7.5 p: every item on the window BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE with no number, "
      "no value, no window in the tariff block (it was OK at 100 % with 'no verified tariff'); the window check was given "
      "the payload "
      "judged without the coverage need (VERIFIED), prices kept it (NOT_VERIFIED, TARIFF_COVERAGE_SHORT); pv_tomorrow OK",
      blocked_disagree(pd_e) and unpriced_tariff(pd_e) and pd_st == "VERIFIED_FROM_INTEGRATION"
      and pd_e.item("pv_tomorrow").status == "OK",
      f"{pd_st} {pd_e.tariff} {({k: sorted(codes(pd_e, k))[:4] for k in ('charge_target', 'predicted_morning_soc')})}")
check("... ENG6-3 (contract 13.8): the quality layer's WARN CHARGE_WINDOW_FROM_TOU_TABLE stays among the reason codes "
      "beside the BLOCK of the refused window (no number; it is dropped only when a named run accepts the window), and "
      "the planning layer adds no WARN of its own there",
      all("CHARGE_WINDOW_FROM_TOU_TABLE" in pd_e.item(k).reason_codes and pd_e.item(k).value is None
          for k in ("charge_target", "predicted_morning_soc"))
      and tou_warn_texts(pd_n) == [], str(pd_e.item("charge_target").reason_codes[:8]))
pr_e, pr_st, pr_n = short_case(cf.NOW, PART_RATES)
pr_ct = pr_e.item("charge_target")
pr_text = tou_warn_texts(pr_n)
check("... the same partly priced rates with every priced slot of the window cheap: charge_target and the morning SOC OK "
      "on the TOU window with WARN CHARGE_WINDOW_FROM_TOU_TABLE, whose text says the verified tariff names no cheap run "
      "and does not price the whole TOU window (never 'no verified tariff'); the tariff never sets the window; no price",
      all(pr_e.item(k).status == "OK" and "CHARGE_WINDOW_FROM_TOU_TABLE" in pr_e.item(k).reason_codes
          for k in ("charge_target", "predicted_morning_soc"))
      and pr_ct.summary["window"] == TOU_W and pr_e.tariff["window"] == TOU_WINDOW and unpriced_tariff(pr_e)
      and "CHARGE_WINDOW_FROM_TARIFF" not in pr_ct.reason_codes and "CHARGE_WINDOW_TOU_INSIDE_TARIFF" not in pr_ct.reason_codes
      and "CHARGE_WINDOW_SOURCES_DISAGREE" not in pr_e.reason_codes and pr_st == "VERIFIED_FROM_INTEGRATION"
      and len(pr_text) == 1 and "names no cheap run" in pr_text[0] and "does not price the whole TOU window" in pr_text[0]
      and "no verified tariff" not in pr_text[0], f"{pr_st} {pr_text} {pr_ct.reason_codes[:8]}")
st_e, st_st, st_n = window_judged(ph.with_reading(VER, "tariff.import_rates", PART_DEAR, age_s=7200.0))
st_text = tou_warn_texts(st_n)
check("... the conflicting rates observed 2 h ago (stale): the window check keeps the freshness gate, so they are no "
      "verified tariff and check nothing: the TOU window OK with WARN 'no verified tariff' (a stale payload is not read)",
      st_st != "VERIFIED_FROM_INTEGRATION" and st_e.item("charge_target").status == "OK"
      and st_e.item("charge_target").summary["window"] == TOU_W and "CHARGE_WINDOW_SOURCES_DISAGREE" not in st_e.reason_codes
      and len(st_text) == 1 and st_text[0].startswith("no verified tariff"), f"{st_st} {st_text}")
# one day-rates event (the single form: the runtime maps one entity attribute for the key; contract section 3), TOU grid
# slot misconfigured to the 17:00-19:00 peak. The check's lowest rate reads the payload's slots from 24 h before now to
# 24 h after it (A38), so it BLOCKs whenever the payload prices the window, also after the night's cheap run has passed;
# an occurrence the payload does not price at all keeps the accepted residual (contract 13.5): the TOU window with its
# WARN 'does not price the whole TOU window'
CUR16 = ph.go_like_rates(D16, 1)                           # 2030-01-16 only: cheap 01:00-04:30, 30 p elsewhere
NEXT17 = ph.go_like_rates(D16 + timedelta(days=1), 1)      # 2030-01-17 only
TWO_SHORT = [r for r in ph.go_like_rates(D15, 2) if r["start"] < "2030-01-16T20:30"]   # two days, the last row missing
SITE_SHAPES = (
    ("today's rates only at 00:30 (the cheap run ahead)", datetime(2030, 1, 16, 0, 30, tzinfo=UTC), CUR16, True),
    ("today's rates only at 04:00 (its last cheap slot ahead)", datetime(2030, 1, 16, 4, 0, tzinfo=UTC), CUR16, True),
    ("today's rates only at 04:30 (the cheap run passed, in the look-back)", datetime(2030, 1, 16, 4, 30, tzinfo=UTC), CUR16, True),
    ("today's rates only at 12:00 (the cheap run in the look-back)", datetime(2030, 1, 16, 12, 0, tzinfo=UTC), CUR16, True),
    ("tomorrow's rates only at 18:30 (today's window not priced: residual)", datetime(2030, 1, 16, 18, 30, tzinfo=UTC), NEXT17, False),
    ("tomorrow's rates only at 19:00 (tomorrow's window priced)", datetime(2030, 1, 16, 19, 0, tzinfo=UTC), NEXT17, True),
    ("two days of rates one row short at 21:00", cf.NOW, TWO_SHORT, True),
)
site_bad = []
for label, now, rows, want_block in SITE_SHAPES:
    e_, st_, n_ = short_case(now, rows, PEAK_TABLE)
    ok_tou = e_.item("charge_target").status == "OK" and "CHARGE_WINDOW_FROM_TOU_TABLE" in e_.item("charge_target").reason_codes \
        and "CHARGE_WINDOW_SOURCES_DISAGREE" not in e_.reason_codes and len(tou_warn_texts(n_)) == 1 \
        and "names no cheap run" in tou_warn_texts(n_)[0]
    if st_ != "VERIFIED_FROM_INTEGRATION" or not unpriced_tariff(e_) or (blocked_disagree(e_) if want_block else ok_tou) is False:
        site_bad.append((label, st_, e_.item("charge_target").status, sorted(codes(e_, "charge_target"))[:3]))
check("ENG6-1 / A38 on one day-rates event, TOU grid slot at the 17:00-19:00 peak: BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE "
      "whenever the payload prices the window (today's rates also after the cheap run has passed: it is in the look-back; "
      "tomorrow's once the window is tomorrow's; two days one row short); a window the payload does not price stands "
      "with its WARN ('names no cheap run'), the accepted residual; prices never",
      site_bad == [], str(site_bad))
# N1 (A38), end to end: the current-day event only, two-rate 7.5 p 00:30-05:30 / 30 p, TOU grid slot at the peak
N1_CUR = ph.go_like_rates(D16, 1, cheap=(30, 330))
n1_bad = []
for _k in range(48):
    _now = datetime(2030, 1, 16, 0, 0, tzinfo=UTC) + timedelta(minutes=30 * _k)
    _e, _st, _n = short_case(_now, N1_CUR, PEAK_TABLE)
    if _now < datetime(2030, 1, 16, 19, 0, tzinfo=UTC):
        _good = blocked_disagree(_e) and (_k == 0 or unpriced_tariff(_e))
    else:
        _ct = _e.item("charge_target")
        _t = tou_warn_texts(_n)
        _good = _ct.status == "OK" and _ct.summary["window"][0] == "2030-01-17T17:00:00+00:00" and unpriced_tariff(_e) \
            and "CHARGE_WINDOW_SOURCES_DISAGREE" not in _e.reason_codes and len(_t) == 1 \
            and "does not price the whole TOU window" in _t[0]
    if not _good or _st != "VERIFIED_FROM_INTEGRATION":
        n1_bad.append((_now.strftime("%H:%M"), _st, _e.item("charge_target").status, sorted(codes(_e, "charge_target"))[:3]))
check("N1 (A38) end to end: the current-day event only (7.5 p 00:30-05:30, 30 p otherwise), TOU grid slot at the "
      "17:00-19:00 peak, every half-hour of the day (48 cycles): every item on the window BLOCKED "
      "CHARGE_WINDOW_SOURCES_DISAGREE with no number until the window ends at 19:00 (before A38 it was OK from 05:30); "
      "then the next occurrence is not priced: the accepted residual, OK on tomorrow's window with the WARN 'does not "
      "price the whole TOU window'; prices never (NOT_VERIFIED) after 00:00", n1_bad == [], str(n1_bad[:4]))
n2_e, n2_st, _n2n = short_case(datetime(2030, 1, 16, 5, 10, tzinfo=UTC),
                               [dict(r, value_inc_vat=ph.CHEAP_GBP if r["start"][11:16] == "05:00" else ph.PEAK_GBP)
                                for r in ph.go_like_rates(D16, 1)], PEAK_TABLE)
check("N2 end to end: the current-day event whose only cheap slot (7.5 p 05:00-05:30) holds now (05:10), TOU grid slot "
      "at the 30 p peak: every item on the window BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE (the slot that holds now counts)",
      blocked_disagree(n2_e) and unpriced_tariff(n2_e) and n2_st == "VERIFIED_FROM_INTEGRATION",
      f"{n2_st} {sorted(codes(n2_e, 'charge_target'))[:4]}")
# R7-E1 end to end, the far end of the look-back period: the next-day event only (the 17th: 12 p, one 5 p slot
# 16:00-16:30), the TOU grid slot 02:00-04:00 (12 p on the 17th). At 16:10 and 16:29 on the 16th, now + 24 h lies inside
# the 5 p slot, which counts toward `low` (7 p below the window): BLOCK. At 16:00 the slot starts exactly at now + 24 h
# and does not count: the whole occurrence is priced at the lowest rate, so the window stands (within the spread)
FAR_TABLE = v2(["00:00", "01:55", "02:00", "04:00", "12:00", "18:00"], ("None", "None", "Grid", "None", "None", "None"))
FAR17 = [{"start": (datetime(2030, 1, 17, tzinfo=UTC) + timedelta(minutes=30 * _i)).isoformat(),
          "end": (datetime(2030, 1, 17, tzinfo=UTC) + timedelta(minutes=30 * (_i + 1))).isoformat(),
          "value_inc_vat": 0.05 if _i == 32 else 0.12} for _i in range(48)]
far_bad = []
for _hm in ((16, 10), (16, 29)):
    _e, _st, _n = short_case(datetime(2030, 1, 16, *_hm, tzinfo=UTC), FAR17, FAR_TABLE)
    if not (blocked_disagree(_e) and _st == "VERIFIED_FROM_INTEGRATION"):
        far_bad.append((_hm, _st, _e.item("charge_target").status, sorted(codes(_e, "charge_target"))[:3]))
far_e, far_st, far_n = short_case(datetime(2030, 1, 16, 16, 0, tzinfo=UTC), FAR17, FAR_TABLE)
check("R7-E1 end to end: a 5 p slot that straddles now + 24 h (16:00-16:30 on the 17th, now 16:10 and 16:29 on the "
      "16th) counts toward the window check's lowest rate: every item on the TOU window 02:00-04:00 (12 p) BLOCKED "
      "CHARGE_WINDOW_SOURCES_DISAGREE with no number; at 16:00 the slot starts exactly at now + 24 h and does not count: "
      "the window stands, every priced slot within the spread",
      far_bad == [] and far_e.item("charge_target").status == "OK" and far_st == "VERIFIED_FROM_INTEGRATION"
      and len(tou_warn_texts(far_n)) == 1 and "within the minimum cheap spread" in tou_warn_texts(far_n)[0],
      f"{far_bad} {far_e.item('charge_target').status} {tou_warn_texts(far_n)}")
# A41 (R7-E3) end to end: the published items carry codes only, so the residual (a window that stands on the TOU table
# without a price check of its whole occurrence) is told apart from a checked window by INFO CHARGE_WINDOW_NOT_PRICED,
# on every published charge-window item and nowhere else. It blocks nothing and changes no status or number.
NP = sc.CHARGE_WINDOW_NOT_PRICED
CW_PUBLISHED = tuple(k for k in sd.CHARGE_WINDOW_ITEMS if k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS)


def np_items(e_) -> set:
    return {v.key for v in tuple(e_.items) + tuple(e_.forecasts) if NP in v.reason_codes}


def residual_inputs(now, rows, table):
    x = ph.with_reading(cf.cycle_inputs(synthetic_recorded=True, now=now), "tariff.import_rates", rows)
    x = ph.with_reading(x, "tariff.export_rates", ph.flat_export(D15 - timedelta(days=1), 4))
    return with_table(x, table)


NP_RESIDUAL = residual_inputs(datetime(2030, 1, 16, 19, 30, tzinfo=UTC), N1_CUR, PEAK_TABLE)
np_res = run_cycle(NP_RESIDUAL)
np_none = run_cycle(ph.without(cf.cycle_inputs(synthetic_recorded=True), "tariff.import_rates"))
check("A41: the N1 residual (the current-day event at 19:30, tomorrow's 17:00-19:00 occurrence not priced) and no import "
      "tariff at all: INFO CHARGE_WINDOW_NOT_PRICED on exactly the published charge-window items (charge_target, "
      "export_event, dump_to_grid, predicted_morning_soc), never on overnight_demand or the forecasts on history; "
      "charge_target OK",
      CW_PUBLISHED == ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc")
      and np_items(np_res) == set(CW_PUBLISHED) and np_items(np_none) == set(CW_PUBLISHED)
      and np_res.item("charge_target").status == "OK" and np_none.item("charge_target").status == "OK",
      f"{sorted(np_items(np_res))} {sorted(np_items(np_none))} {np_res.item('charge_target').status}")
check("... absent where a check priced the whole occurrence: within the spread (the far-edge case at 16:00), a named run "
      "INSIDE (the verified fixture), and on a refused window (SOURCES_DISAGREE, ENG6-1's partly priced conflict)",
      np_items(far_e) == set() and np_items(same) == set() and np_items(pd_e) == set()
      and "CHARGE_WINDOW_TOU_INSIDE_TARIFF" in same.item("charge_target").reason_codes,
      f"{sorted(np_items(far_e))} {sorted(np_items(same))} {sorted(np_items(pd_e))}")
np_blk = run_cycle(ph.with_reading(ph.without(cf.cycle_inputs(synthetic_recorded=True), "tariff.import_rates"),
                                   sc.RESERVE_RAISE_KEY, 150.0, age_s=3600.0))
check("... and on a charge_target BLOCKED for another reason (no import tariff and a mapped raise preference above 100: "
      "PREF_RESERVE_RAISE_UNKNOWN) it is still on every published charge-window item: there it says only that the window "
      "was not price-checked, so the acceptance counts it only on an OK charge_target (contract 13.5, ENG8-1)",
      np_blk.item("charge_target").status == "BLOCKED" and np_blk.item("charge_target").value is None
      and "PREF_RESERVE_RAISE_UNKNOWN" in codes(np_blk, "charge_target") and np_items(np_blk) == set(CW_PUBLISHED),
      f"{np_blk.item('charge_target').status} {sorted(codes(np_blk, 'charge_target'))} {sorted(np_items(np_blk))}")


def _strip_np(now, tz, *a, **kw):
    cw_, n_ = _orig_choose(now, tz, *a, **kw)
    return cw_, [f for f in n_ if f.code != NP]


def _drop_np(v):
    if isinstance(v, dict):
        return {k: _drop_np(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_drop_np(x) for x in v if x != NP]
    return v


dp.choose_charge_window = _strip_np
try:
    np_off = run_cycle(NP_RESIDUAL)
finally:
    dp.choose_charge_window = _orig_choose
check("... INFO only: the same cycle without the code is the same envelope in every status, number, blocker, validity "
      "and code but this one; it is never a blocker and, like CHARGE_WINDOW_TOU_INSIDE_TARIFF, an item code only (not "
      "a top-level code); the OK charge_target keeps its TOU claim and every item stays within MAX_REASON_CODES",
      _drop_np(np_res.to_dict()) == _drop_np(np_off.to_dict()) and np_items(np_off) == set()
      and not any(NP in [c for c, _t in v.blockers] for v in tuple(np_res.items) + tuple(np_res.forecasts))
      and NP not in [c for c, _t in np_res.blockers] and NP not in np_res.reason_codes
      and any(c.startswith("TOU_CLAIM_") for c in np_res.item("charge_target").reason_codes)
      and all(len(v.reason_codes) < ac.MAX_REASON_CODES for v in tuple(np_res.items) + tuple(np_res.forecasts)),
      str(np_res.item("charge_target").reason_codes))
eq_bad = []
for _k in range(48):
    _now = datetime(2030, 1, 16, 0, 0, tzinfo=UTC) + timedelta(minutes=30 * _k)
    for _name, _rows in (("today", CUR16), ("tomorrow", NEXT17)):
        _e, _st, _n = short_case(_now, _rows)
        _ct = _e.item("charge_target")
        if _ct.status != "OK" or "CHARGE_WINDOW_SOURCES_DISAGREE" in _e.reason_codes or _ct.summary["window"][0][11:16] != "01:00" \
                or (_e.tariff["provenance"] == "NOT_VERIFIED" and "CHARGE_WINDOW_FROM_TARIFF" in _ct.reason_codes):
            eq_bad.append((_name, _now.strftime("%H:%M"), _ct.status, sorted(codes(_e, "charge_target"))[:3]))
check("ENG6-1: one day-rates event (today's or tomorrow's) and the TOU grid slot equal to its cheap run 01:00-04:30, every "
      "30 min over 24 h (96 cycles): charge_target always OK on the TOU window, never CHARGE_WINDOW_SOURCES_DISAGREE, and "
      "a payload short of the search period never sets the window", eq_bad == [], str(eq_bad[:6]))
for name, e in (("the narrow-slot case", mis), ("the TOU-only narrow slot", tou_only), ("the synthetic case", env), ("the verified case", same)):
    m = e.item("predicted_morning_soc")
    floor = e.item("charge_target").summary["reserve"]["effective_pct"] if e.item("charge_target").summary else None
    check(f"{name}: the morning SOC band is never below the effective reserve (the reserve-held account)",
          m.status == "OK" and floor is not None and m.p10 >= floor - dp.MORNING_ROUNDING_PCT - 1e-9
          and (("MORNING_SOC_AT_RESERVE" in m.reason_codes) == (m.p10 <= floor + dp.MORNING_ROUNDING_PCT)), f"{m.p10} {m.value} {m.p90} floor {floor} {m.reason_codes[:4]}")

print("== [10] apply_to_siteconfig None while quality passes; the HA helper; the pause value")
ha_dec = cf.synthetic_decisions().with_decision("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), sd.Provenance.SYNTHETIC_TEST)
h150 = run_cycle(ph.with_signal(cf.cycle_inputs(decisions=ha_dec, accept_provenance=cf.SYNTHETIC_ACCEPT), "reserve.ha_minimum_soc", 150.0))
BATTERY = ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc")
# The quality layer refuses a helper outside 0..100 itself (the reading is unusable, so not fresh), before the decided
# configuration is built: RESERVE_HELPER_OUT_OF_RANGE is then never reached through the cycle (site_decisions' own suite
# pins it). The path "apply_to_siteconfig is None while quality passes" is reached with a grid-charge limit that quality
# accepts (within its plausible range) and SiteConfig refuses (above its 50 kW bound): SITECONFIG_INVALID.
check("I-D1 = the HA helper reading 150: the quality layer refuses it (data quality BLOCKED); every battery item and "
      "predicted_morning_soc is BLOCKED (INPUT_NOT_FRESH) with no number",
      all(h150.item(k).status == "BLOCKED" and "INPUT_NOT_FRESH" in codes(h150, k) and h150.item(k).summary is None for k in BATTERY)
      and h150.data_quality == "BLOCKED", str({k: sorted(codes(h150, k))[:3] for k in BATTERY}))
# the TOU power cap would lower a 60 kW limit to the fixture's 5 kW slot power, so the slots say 60 kW too here
g60 = run_cycle(ph.with_reading(with_table(cf.cycle_inputs(synthetic_recorded=True), v2(powers=[60000.0] * 6)),
                                "limits.max_grid_charge_w", 60000.0))
g60c = run_cycle(ph.with_reading(cf.cycle_inputs(synthetic_recorded=True), "limits.max_grid_charge_w", 60000.0))
check("the TOU power cap: a 60 kW limit with 5 kW slots is lowered to 5 kW (min of the two), so the configuration is valid",
      g60c.item("charge_target").status == "OK"
      and g60c.item("charge_target").summary == envs["synthetic"].item("charge_target").summary,
      f"{g60c.item('charge_target').status} {sorted(codes(g60c, 'charge_target'))[:3]}")
check("a grid-charge limit quality accepts but SiteConfig refuses (60 kW, slots at 60 kW): apply_to_siteconfig is None while "
      "quality passes, and every battery item and predicted_morning_soc is BLOCKED with SITECONFIG_INVALID (its fixed text)",
      all(g60.item(k).status == "BLOCKED" and "SITECONFIG_INVALID" in codes(g60, k)
          and dict(g60.item(k).blockers).get("SITECONFIG_INVALID") == "the decided values do not form a valid site configuration"
          for k in BATTERY)
      and "INPUT_NOT_FRESH" not in codes(g60, "charge_target") and g60.data_quality != "BLOCKED",
      str({k: sorted(codes(g60, k))[:3] for k in BATTERY}))
leak = json.dumps({k: list(v) for k, v in ac.to_entity_payloads(g60).items()}, default=str)
check("... no example battery value anywhere (no 31.7, no 40 % reserve), no plan, value or comparison; the forecasts "
      "without a battery value stay OK", "31.7" not in leak and "60000" not in leak and g60.plan is None and g60.value is None
      and g60.engine_comparison is None and g60.item("overnight_demand").status == "OK"
      and g60.item("predicted_day_load").status == "OK" and all(g60.item(k).summary is None for k in BATTERY))
hi60 = run_cycle(ph.with_signal(cf.cycle_inputs(synthetic_recorded=True), "reserve.ha_minimum_soc", 60.0))
r60 = (hi60.item("charge_target").summary or {}).get("reserve") or {}
check("I-D1 = the Intelligence user reserve (30 %) and a fresh HA helper at 60: the helper raises the effective reserve "
      "(raise-only, HA_RESERVE_HELPER_RAISE_ONLY)", r60.get("effective_pct") == 60.0 and r60.get("binding") == "ha_reserve"
      and "HA_RESERVE_HELPER_RAISE_ONLY" in hi60.item("charge_target").reason_codes, str(r60))
r20 = (env.item("charge_target").summary or {}).get("reserve") or {}
check("... a helper below the floor (the fixture's 20) never lowers it", r20.get("effective_pct") == 30.0 and r20.get("binding") == "user_reserve", str(r20))
for bad_pause in (1, 0, "on", "paused", 1.0):
    pz = run_cycle(replace(cf.cycle_inputs(synthetic_recorded=True), paused=bad_pause))
    check(f"a malformed pause value {bad_pause!r}: SELF_TEST_FAILED (PAUSE_CONTROL_INVALID), every item withheld",
          pz.status == "SELF_TEST_FAILED" and "PAUSE_CONTROL_INVALID" in (pz.self_test or {})
          and all(pz.item(k).value is None for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS), f"{pz.status} {pz.self_test}")

print("== [11] the event list and the Saving Session plan")
# an event list the cycle cannot judge fresh, built: tariff.events is an I-D6 key with no default limit (CCR-DQ-1 /
# CCR-PLAN-1), so a satisfied I-D6 that records no limit for it leaves the present list (observed 120 s ago) UNRESOLVED
no_ev_d6 = cf.synthetic_decisions().with_decision("D6", sd.FreshnessOverrides(
    {k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None and k != "tariff.events"}),
    sd.Provenance.SYNTHETIC_TEST)
unres_inp = cf.cycle_inputs(decisions=no_ev_d6, accept_provenance=cf.SYNTHETIC_ACCEPT)
unres_ev = judged_reading(unres_inp, "tariff.events")
unres = run_cycle(unres_inp)
check("an event list the cycle cannot judge fresh (present, observed 120 s ago, but the satisfied I-D6 records no limit "
      "for it: UNRESOLVED): export and Dump advice BLOCKED TARIFF_EVENTS_NOT_FRESH, the charge target unaffected",
      no_ev_d6.satisfied("D6", cf.SYNTHETIC_ACCEPT) and unres_ev.value is not None and not unres_ev.fresh
      and unres_ev.limit_s is None and unres.item("charge_target").status == "OK"
      and all(unres.item(k).status == "BLOCKED" and "TARIFF_EVENTS_NOT_FRESH" in codes(unres, k)
              for k in ("export_event", "dump_to_grid")),
      f"{unres_ev} {({k: (unres.item(k).status, sorted(codes(unres, k))[:3]) for k in ('export_event', 'dump_to_grid')})}")
old_ev = run_cycle(ph.with_reading(cf.cycle_inputs(synthetic_recorded=True), "tariff.events", [], age_s=7200.0))
check("an event list observed 2 h ago (above the 900 s ceiling, stale under any limit): export and Dump BLOCKED "
      "TARIFF_EVENTS_NOT_FRESH", all(old_ev.item(k).status == "BLOCKED" and "TARIFF_EVENTS_NOT_FRESH" in codes(old_ev, k)
                                     for k in ("export_event", "dump_to_grid")), str({k: codes(old_ev, k) for k in ("export_event", "dump_to_grid")}))


def ev_case(events, age_s=120.0, base=None, soc=None):
    x = ph.with_reading(base if base is not None else ph.verified_inputs(synthetic_recorded=True), "tariff.events", events, age_s=age_s)
    if soc is not None:
        x = ph.with_reading(ph.with_signal(x, "battery.soc", soc), "battery.soc_raw_pct", soc, age_s=20.0)
    return run_cycle(x)


SESSION_TOMORROW = [{"start": "2030-01-16T17:00:00+00:00", "end": "2030-01-16T18:00:00+00:00", "kind": "saving_session"}]
SESSION_TONIGHT = [{"start": "2030-01-15T22:00:00+00:00", "end": "2030-01-15T23:00:00+00:00"}]
SESSION_IN_WINDOW = [{"start": "2030-01-16T02:00:00+00:00", "end": "2030-01-16T03:00:00+00:00"}]
_limits_before = sc.freshness_limits
with ph.simulated_ccr_plan_1(300.0):
    fresh_ev = ev_case([])
    stale_ev = ev_case([], age_s=400.0)
    near_end = ev_case([], age_s=290.0)
    mid_end = ev_case([], age_s=150.0)
    after = {soc: ev_case(SESSION_TOMORROW, soc=soc) for soc in (55.0, 95.0)}
    tonight = ev_case(SESSION_TONIGHT)
    inside = ev_case(SESSION_IN_WINDOW)
    dflt_acc = run_cycle(ph.with_reading(ph.verified_inputs(decisions=cf.synthetic_decisions(), accept_provenance=sd.DEFAULT_ACCEPT_PROVENANCE),
                                         "tariff.events", SESSION_TOMORROW))
check("a defined limit (a site's 300 s, simulated in process): a fresh empty list gives export NO_ADVICE (no event ahead) and Dump advice not blocked by the list",
      fresh_ev.item("export_event").status == "NO_ADVICE" and "TARIFF_EVENTS_NOT_FRESH" not in codes(fresh_ev, "dump_to_grid")
      and fresh_ev.item("dump_to_grid").status in ("OK", "NO_ADVICE"), str({k: fresh_ev.item(k).status for k in ("export_event", "dump_to_grid")}))
check("... a list older than its limit (400 s against 300 s): export and Dump BLOCKED TARIFF_EVENTS_NOT_FRESH",
      all(stale_ev.item(k).status == "BLOCKED" and "TARIFF_EVENTS_NOT_FRESH" in codes(stale_ev, k) for k in ("export_event", "dump_to_grid")))
dv, dm = near_end.item("dump_to_grid"), mid_end.item("dump_to_grid")
check("... a list with 150 s of freshness left: an OK Dump advice is valid for at most those 150 s (its validity rests on the list)",
      dm.status == "OK" and dm.valid_until <= cf.NOW + timedelta(seconds=150.0 + 1e-6), f"{dm.status} {dm.valid_until}")
# changed on purpose (WP-2, section 13.4): below the refresh margin an OK item is withheld instead of shortening the envelope
check("... a list with 10 s of freshness left (below REFRESH_MARGIN_S): the Dump advice is BLOCKED INPUT_EXPIRING with no number",
      dv.status == "BLOCKED" and "INPUT_EXPIRING" in codes(near_end, "dump_to_grid") and dv.value is None and dv.summary is None,
      f"{dv.status} {sorted(codes(near_end, 'dump_to_grid'))[:3]}")
for soc, e in after.items():
    x = e.item("export_event")
    s = x.summary or {}
    floor = (e.item("charge_target").summary or {}).get("effective_reserve_pct")
    check(f"a Saving Session tomorrow 17:00-18:00 after the 01:00-04:30 refill, SOC now {soc:.0f}: it starts from the planned "
          "window-end SOC (EVENT_START_FROM_PLANNED_WINDOW_END), drained on the reserve-held account: never below the "
          "reserve, never outside 0..100", x.status == "OK" and "EVENT_START_FROM_PLANNED_WINDOW_END" in x.reason_codes
          and floor is not None and floor - 1e-9 <= s.get("soc_at_start_pct", -1) <= 100.0
          and 0.0 <= s.get("soc_at_end_expected_pct", -1) <= 100.0
          and x.valid_until <= e.item("charge_target").valid_until, f"{x.status} {x.reason_codes[:6]} {s.get('soc_at_start_pct')}")
check("... the start SOC does not depend on the SOC now (the refill comes first)",
      (after[55.0].item("export_event").summary or {}).get("soc_at_start_pct", -1)
      == (after[95.0].item("export_event").summary or {}).get("soc_at_start_pct", -2))
tx = tonight.item("export_event")
check("a Saving Session tonight (no window before it): from the SOC now, no planned-window code",
      tx.status == "OK" and "EVENT_START_FROM_PLANNED_WINDOW_END" not in tx.reason_codes
      and 0.0 < (tx.summary or {}).get("soc_at_start_pct", -1) < 55.0, f"{tx.status} {tx.summary and tx.summary.get('soc_at_start_pct')}")
check("a Saving Session inside the charge window: not modelled, BLOCKED EVENT_AFTER_REFILL_NOT_MODELLED",
      inside.item("export_event").status == "BLOCKED" and "EVENT_AFTER_REFILL_NOT_MODELLED" in codes(inside, "export_event"))
check("... and under the default acceptance the same inputs give BLOCKED export and Dump advice",
      all(dflt_acc.item(k).status == "BLOCKED" for k in ("export_event", "dump_to_grid")))
check("the in-process simulation is restored (the view before it again)", sc.freshness_limits is _limits_before)

print("== [12] date-scoped validity")
late = run_cycle(cf.cycle_inputs(now=datetime(2030, 1, 15, 23, 55, tzinfo=UTC), synthetic_recorded=True))
pdl = late.item("predicted_day_load")
check("predicted_day_load ('tomorrow') at 23:55 is valid until local midnight at the latest (then it would describe today)",
      pdl.status == "OK" and pdl.valid_until <= datetime(2030, 1, 16, 0, 0, tzinfo=UTC), f"{pdl.status} {pdl.valid_until}")

print("== [13] published texts")
ENVS = dict(envs, **{"default acceptance": dflt, "INVALID I-D4": inv, "DST eve": d9r, "HA helper 150": h150,
                     "narrow TOU slot": mis, "no overlap": apart, "current-day tariff": tariff_case(cf.NOW, cur_day),
                     "Saving Session (site limit simulated)": after[55.0], "stale event list": old_ev,
                     "UNRESOLVED event list": unres, "missing SOC":
                     run_cycle(cf.cycle_inputs(synthetic_recorded=True, missing_key="battery.soc"))})
redacted = []
for n, e in ENVS.items():
    views = tuple(e.items) + tuple(e.forecasts)
    texts = [t for v in views for _c, t in v.blockers] + [t for _c, t in e.blockers]
    if sc.REDACTED_CODE in e.reason_codes or any(sc.REDACTED_CODE in v.reason_codes for v in views) \
            or any(t == sc.REDACTED_TEXT or sc._pub(t)[1] for t in texts):  # noqa: SLF001
        redacted.append(n)
check(f"{len(ENVS)} representative inputs: every published blocker text is a fixed phrase (no text redacted, no "
      "PUBLISHED_TEXT_REDACTED)", redacted == [], str(redacted))
blk = sc._Blocks()  # noqa: SLF001 - the guard itself
blk.block("charge_target", "SOME_CODE", "a level of 31.7 kWh between 00:30 and 05:30")
bl_, rc_ = blk.parts("charge_target")
check("a value-shaped text is replaced WHOLE by a fixed sentence and the item says so (PUBLISHED_TEXT_REDACTED first)",
      bl_ == (("SOME_CODE", sc.REDACTED_TEXT),) and rc_[0] == sc.REDACTED_CODE and "31" not in sc.REDACTED_TEXT, str((bl_, rc_)))
check("... codes and plain words pass unchanged (I-D labels are not values)",
      sc._pub("I-D1 (planning floor) is OPEN") == ("I-D1 (planning floor) is OPEN", False))  # noqa: SLF001
d5 = sd.DecisionSet.from_mapping({"D5": {"provenance": "SYNTHETIC_TEST", "value": {"value": 0.3, "unit": "fraction",
                                                                                 "basis": "ROUND_TRIP"}}}, source="test").get("D5")
e5 = run_cycle(cf.cycle_inputs(decisions=sd.DecisionSet({**cf.synthetic_decisions().decisions, "D5": d5}),
                               accept_provenance=cf.SYNTHETIC_ACCEPT))
top5 = dict(e5.blockers)
_d5_text = str(top5.get("DECISION_D5_INVALID", ""))
check("an INVALID I-D5 (0.3, outside the plausible range): since CCR-PLAN-4 its upstream text states no value, so it is "
      "published as it is (no PUBLISHED_TEXT_REDACTED anywhere); the code stays and no bound reaches any payload",
      _d5_text and _d5_text != sc.REDACTED_TEXT and not any(ch.isdigit() for ch in _d5_text.replace("I-D5", ""))
      and "EFFICIENCY_OUT_OF_RANGE" in _d5_text and sc.REDACTED_CODE not in e5.reason_codes
      and sc.REDACTED_CODE not in e5.item("charge_target").reason_codes and "DECISION_D5_INVALID" in codes(e5, "charge_target")
      and "0.5" not in json.dumps({k: list(v) for k, v in ac.to_entity_payloads(e5).items()}, default=str),
      str((e5.blockers, e5.reason_codes[:3])))
ng_env = envs["synthetic, no grid limit"]
ng_texts = dict(ng_env.item("charge_target").blockers)
check("a known upstream text that states a value (GRID_CHARGE_LIMIT_UNKNOWN: the example limit) is published as the "
      "plan's fixed phrase, without the value",
      ng_texts.get("GRID_CHARGE_LIMIT_UNKNOWN") == sc._FIXED_TEXTS["GRID_CHARGE_LIMIT_UNKNOWN"]  # noqa: SLF001
      and "8 kW" not in json.dumps({k: list(v) for k, v in ac.to_entity_payloads(ng_env).items()}, default=str), str(ng_texts))

print("== [14] a fresh history with an entry the quality layer ignores")
_h0 = cf.history(cf.NOW)
_ks = sorted(_h0.by_start)
_mid, _newest = _ks[len(_ks) // 2], _ks[-1]


def _without(key) -> History:
    hh = History()
    hh.by_start = {k: copy.deepcopy(r) for k, r in _h0.by_start.items() if k != key}
    return hh


def _with(key, entry) -> History:
    hh = _without(key)
    hh.by_start[key] = entry
    return hh


def _published(e) -> str:
    """everything the cycle publishes (every entity's state and attributes), as one comparable text"""
    return json.dumps({k: list(v) for k, v in ac.to_entity_payloads(e).items()}, sort_keys=True, default=str)


_rec = _h0.by_start[_mid]
_bad = (("a junk string", _mid, "junk"), ("None", _mid, None),
        ("a record filed under another hour", _mid, replace(copy.deepcopy(_rec), start=_mid - 7 * 3600)),
        ("a record whose energies are None", _mid, replace(copy.deepcopy(_rec), e=None)),
        ("a record whose flags are None", _mid, replace(copy.deepcopy(_rec), flags=None)),
        ("a junk string under the newest key", _newest, "junk"))
for _mode, _base, _want in (("synthetic decisions", cf.cycle_inputs(synthetic_recorded=True), "OK"),
                            ("all decisions OPEN", cf.cycle_inputs(), "BLOCKED")):
    _refs = {k: run_cycle(replace(_base, history=_without(k))) for k in (_mid, _newest)}
    check(f"{_mode}: the references without the entry are normal cycles (status {_want}, pv_tomorrow OK)",
          all(r.status == _want and r.item("pv_tomorrow").status == "OK" for r in _refs.values()),
          str({k: (r.status, r.item("pv_tomorrow").status) for k, r in _refs.items()}))
    for _label, _key, _entry in _bad:
        _jh = _with(_key, _entry)
        _je = run_cycle(replace(_base, history=_jh))
        _jq = q.assess_inputs(replace(_base, history=_jh))
        check(f"{_mode}, {_label}: the quality layer counts it (HISTORY_RECORD_MALFORMED, WARN), the cycle never fails "
              "its self-test, and it publishes exactly what the same history without that entry gives",
              any(f.code == "HISTORY_RECORD_MALFORMED" and f.severity == sd.WARN for f in _jq.findings)
              and _je.status != "SELF_TEST_FAILED" and "CYCLE_INTERNAL_ERROR" not in [c for c, _t in _je.blockers]
              and _published(_je) == _published(_refs[_key]),
              f"{_je.status} {[c for c, _t in _je.blockers][:3]}")

print("== [15] the grid-charge classification in the cycle")
BASE = cf.cycle_inputs(synthetic_recorded=True)
BASE_ENV = run_cycle(BASE)
check("the shared fixture (one Grid slot 01:00-04:30, both enables on, no overlay): every TOU item computed, the window "
      "from the table", all(BASE_ENV.item(k).status in ("OK", "NO_ADVICE") for k in TOU_ITEMS)
      and BASE_ENV.tariff["window"] == TOU_WINDOW, str({k: BASE_ENV.item(k).status for k in TOU_ITEMS}))


def blocks_window(e, code) -> bool:
    """`code` BLOCKs every item that rests on the TOU window (overnight_demand too); the history-only items stay OK."""
    return all(e.item(k).status == "BLOCKED" and code in codes(e, k) for k in TOU_ITEMS) \
        and e.item("pv_tomorrow").status == "OK" and e.item("predicted_day_load").status == "OK" and e.tariff["window"] is None


def slot3(**fields):
    t = v2()
    t[2].update(fields)
    return t


CLASS_CASES = {
    "slot 3's source, mode and flags unknown (unavailable)": (with_table(BASE, slot3(charge_source=None, flags_raw=None,
                                                                                     mode=None)), "TOU_SLOT_SOURCE_UNKNOWN"),
    "slot 3's mode Unknown 0x14": (with_table(BASE, slot3(mode="Unknown 0x14")), "TOU_SLOT_SOURCE_UNKNOWN"),
    "slot 3's flags disagree with its texts": (with_table(BASE, slot3(flags_raw=1)), "TOU_SOURCE_DECODE_CONFLICT"),
    "the Grid slot's flags word with bit 5 set (undecoded, ENG-4)": (with_table(BASE, [
        dict(r, flags_raw=r["flags_raw"] | 0x20) if r["charge_source"] == "Grid" else r for r in v2()]),
        "TOU_FLAGS_UNDECODED_BITS"),
    "slot 3 (None) with bit 15 of its flags set (undecoded, ENG-4)": (with_table(BASE, slot3(flags_raw=0x8000)),
                                                                     "TOU_FLAGS_UNDECODED_BITS"),
    "slot 3's target unknown": (with_table(BASE, slot3(target_soc_pct=None)), "TOU_SLOT_TARGET_UNKNOWN"),
    "slot 3's power unknown": (with_table(BASE, slot3(power_w=None)), "TOU_SLOT_POWER_UNKNOWN"),
    "the TOU enable off": (ph.with_reading(BASE, "tou.enabled", False, age_s=cf.POLL_AGE_S), "TOU_DISABLED"),
    "the TOU enable missing": (ph.without(BASE, "tou.enabled"), "TOU_ENABLE_UNKNOWN"),
    "the grid-charge enable off": (ph.with_reading(BASE, "tou.grid_charge_enabled", False, age_s=cf.POLL_AGE_S),
                                   "TOU_GRID_CHARGE_DISABLED"),
    "the grid-charge enable missing": (ph.without(BASE, "tou.grid_charge_enabled"), "TOU_GRID_CHARGE_ENABLE_UNKNOWN"),
    "an overlay active": (ph.with_reading(BASE, "tou.overlay_state", "ACTIVE", age_s=cf.POLL_AGE_S), "TOU_OVERLAY_ACTIVE"),
    "the overlay state missing": (ph.without(BASE, "tou.overlay_state"), "TOU_OVERLAY_STATE_UNKNOWN"),
    "the overlay state not a known state": (ph.with_reading(BASE, "tou.overlay_state", "PAUSED", age_s=cf.POLL_AGE_S),
                                            "TOU_OVERLAY_STATE_UNKNOWN"),
    "a v1 table": (with_table(BASE, [{"slot": 1, "start": "01:00", "end": "04:30", "target_soc_pct": 80}]),
                   "TOU_TABLE_LEGACY_SCHEMA"),
    "five rows": (with_table(BASE, v2()[:5]), "TOU_RING_INVALID"),
    "no Grid slot": (with_table(BASE, v2(sources=("None",) * 6)), "TOU_NO_GRID_SLOT"),
    "two Grid runs": (with_table(BASE, v2(sources=("None", "Grid", "None", "Grid", "None", "None"))), "TOU_MULTIPLE_GRID_WINDOWS"),
    "a Grid run across midnight": (with_table(BASE, v2(["00:00", "02:00", "07:00", "12:00", "17:00", "23:00"],
                                                       ("Grid", "None", "None", "None", "None", "Grid"))),
                                   "CHARGE_WINDOW_CROSSES_MIDNIGHT"),
    "a Grid run across midnight by one slot edge, 23:30-00:30 (PR2-3)": (
        with_table(BASE, v2(["00:00", "00:30", "06:00", "12:00", "18:00", "23:30"],
                            ("Grid", "None", "None", "None", "None", "Grid"))), "CHARGE_WINDOW_CROSSES_MIDNIGHT"),
    "a Grid run across midnight by one short slot each side, 23:55-00:05 (PR2-3)": (
        with_table(BASE, v2(["00:00", "00:05", "06:00", "12:00", "18:00", "23:55"],
                            ("Grid", "None", "None", "None", "None", "Grid"))), "CHARGE_WINDOW_CROSSES_MIDNIGHT"),
    "a zero power in the Grid slot": (with_table(BASE, v2(powers=[5000.0, 0.0, 5000.0, 5000.0, 5000.0, 5000.0])),
                                      "TOU_SLOT_POWER_ZERO"),
}
CLASS_ENVS = {}
for label, (x, code) in CLASS_CASES.items():
    e = CLASS_ENVS[label] = run_cycle(x)
    check(f"{label}: BLOCKED {code} on every TOU item (overnight_demand too), no window, the forecasts on history only "
          "stay OK", blocks_window(e, code), str({k: sorted(codes(e, k))[:3] for k in ("charge_target", "overnight_demand")}))
gg = run_cycle(with_table(BASE, v2(sources=("None", "Grid + Generator", "None", "None", "None", "None"))))
check("Grid + Generator counts as GRID: the same window and the same charge target",
      gg.item("charge_target").status == "OK" and gg.tariff["window"] == TOU_WINDOW
      and gg.item("charge_target").value == BASE_ENV.item("charge_target").value, str(gg.tariff))
adj = run_cycle(with_table(BASE, v2(["00:00", "01:00", "02:30", "04:30", "16:00", "19:00"],
                                    ("None", "Grid", "Grid", "None", "None", "None"))))
check("two adjacent Grid slots (01:00-02:30, 02:30-04:30) are one window 01:00-04:30",
      adj.item("charge_target").status == "OK" and adj.tariff["window"] == TOU_WINDOW, str(adj.tariff))
cap_slot = run_cycle(with_table(BASE, v2(powers=[5000.0, 2000.0, 5000.0, 5000.0, 5000.0, 5000.0])))
cap_lim = run_cycle(ph.with_reading(BASE, "limits.max_grid_charge_w", 2000.0))
check("the power cap: a 2 kW Grid slot under a 5 kW limit gives exactly the charge target of a 2 kW limit (min of the two)",
      cap_slot.item("charge_target").status == "OK"
      and cap_slot.item("charge_target").summary == cap_lim.item("charge_target").summary
      and cap_slot.item("charge_target").summary["achievable_soc_pct"]
      < BASE_ENV.item("charge_target").summary["achievable_soc_pct"],
      str((cap_slot.item("charge_target").summary or {}).get("achievable_soc_pct")))
cap_hi = run_cycle(with_table(BASE, v2(powers=[9000.0] * 6)))
check("... a slot power above the limit never raises it", cap_hi.item("charge_target").summary == BASE_ENV.item("charge_target").summary)
unch = run_cycle(ph.with_reading(VER, "tou.enabled", False, age_s=cf.POLL_AGE_S))
check("a verified tariff beside a table that does not classify (TOU disabled): BLOCKED CHARGE_WINDOW_TOU_UNCHECKED and "
      "TOU_DISABLED (the tariff alone never sets a window)", blocks_window(unch, "CHARGE_WINDOW_TOU_UNCHECKED")
      and all("TOU_DISABLED" in codes(unch, k) for k in TOU_ITEMS), str(sorted(codes(unch, "charge_target"))))

print("== [16] INPUT_EXPIRING and the refresh margin")
check("REFRESH_MARGIN_S is the engine constant 125 (two 60 s ticks plus 5 s)", sc.REFRESH_MARGIN_S == 125.0)


def with_config_age(inputs, age_s):
    at = inputs.now - timedelta(seconds=age_s)
    return ph.with_reading(inputs, sd.CONFIG_LIVENESS_KEY, at, observed_at=at)


edge, past = run_cycle(with_config_age(BASE, 175.0)), run_cycle(with_config_age(BASE, 176.0))
check("configuration liveness 175 s old: 125 s of validity left, so the charge target is OK and valid for exactly 125 s",
      edge.item("charge_target").status == "OK"
      and edge.item("charge_target").valid_until == cf.NOW + timedelta(seconds=125.0),
      f"{edge.item('charge_target').status} {edge.item('charge_target').valid_until}")
check("176 s old (124 s left, below the margin): the TOU items computed first are BLOCKED INPUT_EXPIRING with no number "
      "(overnight_demand, dump_to_grid), and what rests on them is withheld too (charge_target: DEMAND_NOT_AVAILABLE; "
      "predicted_morning_soc: no number); no TOU item is OK",
      all(past.item(k).status == "BLOCKED" and "INPUT_EXPIRING" in codes(past, k) for k in ("overnight_demand", "dump_to_grid"))
      and "DEMAND_NOT_AVAILABLE" in codes(past, "charge_target")
      and all(past.item(k).status != "OK" and past.item(k).value is None for k in TOU_ITEMS),
      str({k: (past.item(k).status, sorted(codes(past, k))[:2]) for k in TOU_ITEMS}))
check("... while pv_tomorrow and predicted_day_load stay numeric and the envelope is valid for at least the margin (no "
      "STALE at the next tick), never shortened by the expiring items",
      past.item("pv_tomorrow").status == "OK" and isinstance(past.item("pv_tomorrow").value, float)
      and past.item("predicted_day_load").status == "OK"
      and past.valid_until >= cf.NOW + timedelta(seconds=sc.REFRESH_MARGIN_S), f"{past.valid_until}")
check("... and no plan, value or comparison rests on the withheld charge target", past.plan is None
      and past.engine_comparison is None and past.item("export_event").status in ("BLOCKED", "NO_ADVICE"))
live60 = cf.NOW - timedelta(seconds=60.0)
tl = run_cycle(ph.with_reading(BASE, sd.LIVENESS_KEY, live60, observed_at=live60))
check("the telemetry poll text 60 s old (120 s of the 180 s bound left): the dongle items are BLOCKED INPUT_EXPIRING (none "
      "OK), the history-only items stay OK", all("INPUT_EXPIRING" in codes(tl, k) for k in ("overnight_demand", "dump_to_grid"))
      and all(tl.item(k).status != "OK" for k in TOU_ITEMS)
      and tl.item("pv_tomorrow").status == "OK" and tl.item("predicted_day_load").status == "OK",
      str({k: tl.item(k).status for k in TOU_ITEMS}))
INPUT_EXPIRING_TEXTS = {t for e in (past, tl) for v in tuple(e.items) + tuple(e.forecasts) for c, t in v.blockers
                        if c == "INPUT_EXPIRING"}
check("its blocker text is one fixed phrase with no number", INPUT_EXPIRING_TEXTS == {sc.INPUT_EXPIRING_TEXT}
      and not any(ch.isdigit() for ch in sc.INPUT_EXPIRING_TEXT), str(INPUT_EXPIRING_TEXTS))

print("== [16b] A31: the validity of the quality-gate inputs")


def d6_inputs(over, base_kw=None):
    lim = {k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None}
    lim.update(over)
    ds = cf.synthetic_decisions().with_decision("D6", sd.FreshnessOverrides(lim), sd.Provenance.SYNTHETIC_TEST)
    return cf.cycle_inputs(decisions=ds, accept_provenance=cf.SYNTHETIC_ACCEPT, **(base_kw or {}))


CW_OK_ITEMS = ("charge_target", "dump_to_grid", "predicted_morning_soc")
off150 = run_cycle(d6_inputs({"inverter.clock_offset_s": 150.0}))       # clock offset 20 s old: 130 s left
off140 = run_cycle(d6_inputs({"inverter.clock_offset_s": 140.0}))       # 120 s left: below the 125 s margin
check("I-D6 gives the inverter clock offset 150 s (its age 20 s): the charge-window items are valid for exactly the 130 s "
      "it has left (the liveness bound alone would give 160 s), while overnight_demand (no clock gate) keeps 160 s",
      all(off150.item(k).status == "OK" and off150.item(k).valid_until == cf.NOW + timedelta(seconds=130.0)
          for k in CW_OK_ITEMS)
      and off150.item("overnight_demand").status == "OK"
      and off150.item("overnight_demand").valid_until == cf.NOW + timedelta(seconds=LIVE_LEFT_S),
      str({k: (off150.item(k).status, off150.item(k).valid_until) for k in CW_OK_ITEMS + ("overnight_demand",)}))
check("... at 140 s (120 s left, below the margin) charge_target and dump_to_grid are BLOCKED INPUT_EXPIRING with no "
      "number and predicted_morning_soc has none, though the quality gate still judges the offset fresh; overnight_demand "
      "stays OK", all(off140.item(k).status == "BLOCKED" and "INPUT_EXPIRING" in codes(off140, k)
                      for k in ("charge_target", "dump_to_grid"))
      and off140.item("predicted_morning_soc").value is None and off140.item("overnight_demand").status == "OK"
      and judged_reading(d6_inputs({"inverter.clock_offset_s": 140.0}), "inverter.clock_offset_s").fresh,
      str({k: (off140.item(k).status, sorted(codes(off140, k))[:2]) for k in CW_OK_ITEMS}))
check("the validity gate readings: the clock offset for every charge-window item, and no supervision reading anywhere (the "
      "documented exemption)", dict(sc.VALIDITY_GATE_READINGS) == {k: ("inverter.clock_offset_s",) for k in sd.CHARGE_WINDOW_ITEMS}
      and not {k for ks in sc.VALIDITY_GATE_READINGS.values() for k in ks} & set(q.SUPERVISION_KEYS))
at5 = cf.NOW - timedelta(seconds=5.0)
sup_in = ph.with_reading(BASE, sd.LIVENESS_KEY, at5, observed_at=at5)  # the telemetry poll text 5 s old
sup_env = run_cycle(sup_in)
sup_ages = q.assess_inputs(sup_in).ages
hb = sup_ages["supervision.heartbeat_age_s"]
sup_left = min(hb.limit_s - hb.age_s, q.DQ_PROPOSED.supervision_reading_max_age_s - 5.0)
sd_view = sup_env.item("dump_to_grid")
lapse = run_cycle(replace(sup_in, now=cf.NOW + timedelta(seconds=sup_left + 1.0)))
check("supervision is exempt from validity BY DESIGN: dump_to_grid is OK and valid for the 175 s the liveness bound leaves, "
      "longer than the supervision gate has left (heartbeat and state each at most 90 s); in the fixture that is 48 s",
      sd_view.status == "OK" and sd_view.valid_until == cf.NOW + timedelta(seconds=q.DQ_PROPOSED.liveness_max_age_s - 5.0)
      and sup_left == 48.0 and (sd_view.valid_until - cf.NOW).total_seconds() > sup_left,
      f"{sd_view.status} {sd_view.valid_until} left {sup_left}")
check("... and enforced at every compute instead: the same inputs computed just after the lapse BLOCK dump_to_grid "
      "SUPERVISION_NOT_STABLE with no number; the worst-case exposure of the published OK item is the time to that next "
      "compute (with the runtime's poll-driven refresh, about one telemetry poll plus the settle delay plus the compute "
      "time while polls arrive; when the polls stop, the first tick after the last poll plus PROPOSED_POLL_ACTIVE_S, "
      "at most about 150 s after it; never past the item's own validity)",
      lapse.item("dump_to_grid").status == "BLOCKED" and lapse.item("dump_to_grid").value is None
      and "SUPERVISION_NOT_STABLE" in codes(lapse, "dump_to_grid"), str(sorted(codes(lapse, "dump_to_grid"))))

print("== [17] the TOU claim")
CLAIMS = set(sc.TOU_CLAIM_CODES)


def claims_of(v) -> list[str]:
    return [c for c in v.reason_codes if c in CLAIMS]


ct0, mk0 = BASE_ENV.item("charge_target"), BASE_ENV.item("predicted_morning_soc")
check("the cap is on by default (register 248 bits 1-15 undecoded)", sc.TOU_CLAIM_CAPPED is True)
check("an OK charge_target and an OK predicted_morning_soc carry exactly one claim code: UNCERTAIN under the cap",
      ct0.status == "OK" and mk0.status == "OK" and claims_of(ct0) == ["TOU_CLAIM_UNCERTAIN"]
      and claims_of(mk0) == ["TOU_CLAIM_UNCERTAIN"], f"{claims_of(ct0)} {claims_of(mk0)}")
check("... no other item carries a claim code, and the predicted morning SOC says it assumes the charge "
      "(MORNING_SOC_ASSUMES_CHARGE)", all(not claims_of(BASE_ENV.item(k)) for k in ac.ADVICE_ITEMS + ac.FORECAST_ITEMS
                                          if k not in ("charge_target", "predicted_morning_soc"))
      and "MORNING_SOC_ASSUMES_CHARGE" in mk0.reason_codes and "MORNING_SOC_ASSUMES_CHARGE" not in ct0.reason_codes)
NOT_OK = [e for e in list(CLASS_ENVS.values()) + [dflt, inv, past] for v in tuple(e.items) + tuple(e.forecasts)
          if v.status != "OK" and claims_of(v)]
check("a claim code never appears on an item that is not OK (blocked, default acceptance, INVALID, expiring)", NOT_OK == [])
sc.TOU_CLAIM_CAPPED = False                      # TEST ONLY: the cap lifted in process, always restored
try:
    lifted = run_cycle(BASE)
    no_health = run_cycle(cf.cycle_inputs(synthetic_recorded=True, missing_key="inverter.healthy"))
    low_target = run_cycle(with_table(BASE, v2(targets=[20.0] * 6)))
    two_targets = run_cycle(with_table(BASE, v2(["00:00", "01:00", "02:30", "04:30", "16:00", "19:00"],
                                                ("None", "Grid", "Grid", "None", "None", "None"),
                                                targets=[20.0, 80.0, 90.0, 20.0, 20.0, 20.0])))
finally:
    sc.TOU_CLAIM_CAPPED = True
check("cap lifted (test only): the fixture is CONFIGURED on both items (one target 80 above the highest plausible start SOC, "
      "power and limit above 0, inverter healthy, clock offset small) and the morning SOC no longer says it assumes it",
      claims_of(lifted.item("charge_target")) == ["TOU_CLAIM_CONFIGURED"]
      and claims_of(lifted.item("predicted_morning_soc")) == ["TOU_CLAIM_CONFIGURED"]
      and "MORNING_SOC_ASSUMES_CHARGE" not in lifted.item("predicted_morning_soc").reason_codes,
      f"{claims_of(lifted.item('charge_target'))} {lifted.item('predicted_morning_soc').reason_codes[:4]}")
check("... inverter.healthy not fresh: never CONFIGURED (UNCERTAIN), while the charge target itself stays OK (health "
      "gates only the claim)", no_health.item("charge_target").status == "OK"
      and claims_of(no_health.item("charge_target")) == ["TOU_CLAIM_UNCERTAIN"], str(no_health.item("charge_target").reason_codes))
check("... every slot target 20, at or below the lowest plausible start SOC: NOT_EXPECTED, and the morning SOC still says "
      "it assumes the charge", claims_of(low_target.item("charge_target")) == ["TOU_CLAIM_NOT_EXPECTED"]
      and "MORNING_SOC_ASSUMES_CHARGE" in low_target.item("predicted_morning_soc").reason_codes,
      str(low_target.item("charge_target").reason_codes))
check("... a run of two slots with different targets: UNCERTAIN", claims_of(two_targets.item("charge_target")) == ["TOU_CLAIM_UNCERTAIN"])
check("the cap is restored", sc.TOU_CLAIM_CAPPED is True and claims_of(run_cycle(BASE).item("charge_target")) == ["TOU_CLAIM_UNCERTAIN"])
ZC = zone(cf.TZ)
CCFG = SiteConfig(battery_capacity_kwh=20.0, round_trip_efficiency=0.92, user_reserve_soc_pct=30.0, technical_min_soc_pct=12.0,
                  max_grid_charge_kw=5.0, cheap_window_start_min=60, cheap_window_end_min=270)
CVIEW = dp.hourly_view([0.5] * 24, {}, ZC, dp.Band(4.0, 5.0, 7.0, "MEDIUM"), None)
CAGES = {"limits.max_grid_charge_w": InputState("limits.max_grid_charge_w", 5000.0, True, 120.0, 300.0),
         "inverter.clock_offset_s": InputState("inverter.clock_offset_s", 2.0, True, 20.0, 300.0)}


def claim_cw(table, now=cf.NOW):
    def s(k, v):
        return InputState(k, v, True, 30.0, 300.0)
    return dp.choose_charge_window(now, ZC, None, None, s("tou.slot_table", table), tou_enabled=s("tou.enabled", True),
                                   grid_charge_enabled=s("tou.grid_charge_enabled", True),
                                   tou_overlay=s("tou.overlay_state", "NONE"))[0]


def claim(capped=False, **kw):
    a = dict(cw=claim_cw(v2()), cfg=CCFG, now=cf.NOW, soc=55.0, view=CVIEW, ha=None, ages=CAGES, inverter_ok=True)
    a.update(kw)
    sc.TOU_CLAIM_CAPPED = capped
    try:
        return sc.tou_claim(a["cw"], a["cfg"], a["now"], a["soc"], a["view"], a["ha"], a["ages"], a["inverter_ok"])
    finally:
        sc.TOU_CLAIM_CAPPED = True


IN_WINDOW = datetime(2030, 1, 16, 2, 0, tzinfo=UTC)
OFF_BIG = q.DQ_PROPOSED.clock_offset_block_s + 10.0
for label, kw, want in (
        ("all conditions met (cap lifted)", {}, "TOU_CLAIM_CONFIGURED"),
        ("all conditions met, capped", {"capped": True}, "TOU_CLAIM_UNCERTAIN"),
        ("target 20, at or below the lowest plausible start SOC", {"cw": claim_cw(v2(targets=[20.0] * 6))}, "TOU_CLAIM_NOT_EXPECTED"),
        ("... also capped", {"cw": claim_cw(v2(targets=[20.0] * 6)), "capped": True}, "TOU_CLAIM_NOT_EXPECTED"),
        ("target 45, between the plausible start SOCs", {"cw": claim_cw(v2(targets=[45.0] * 6))}, "TOU_CLAIM_UNCERTAIN"),
        ("inverter health unknown", {"inverter_ok": None}, "TOU_CLAIM_UNCERTAIN"),
        ("the clock offset above its bound", {"ages": {**CAGES, "inverter.clock_offset_s": InputState(
            "inverter.clock_offset_s", OFF_BIG, True, 20.0, 300.0)}}, "TOU_CLAIM_UNCERTAIN"),
        ("the clock offset stale", {"ages": {**CAGES, "inverter.clock_offset_s": InputState(
            "inverter.clock_offset_s", 2.0, False, 900.0, 300.0)}}, "TOU_CLAIM_UNCERTAIN"),
        ("no fresh grid-charge limit", {"ages": {"inverter.clock_offset_s": CAGES["inverter.clock_offset_s"]}}, "TOU_CLAIM_UNCERTAIN"),
        ("no hourly view (the start SOC cannot be bounded)", {"view": None}, "TOU_CLAIM_UNCERTAIN"),
        ("no SOC", {"soc": None}, "TOU_CLAIM_UNCERTAIN"),
        ("no window", {"cw": None}, "TOU_CLAIM_UNCERTAIN"),
        ("inside the window, SOC 50 below the target", {"cw": claim_cw(v2(), IN_WINDOW), "now": IN_WINDOW, "soc": 50.0},
         "TOU_CLAIM_CONFIGURED"),
        ("inside the window, SOC 90 above the target", {"cw": claim_cw(v2(), IN_WINDOW), "now": IN_WINDOW, "soc": 90.0},
         "TOU_CLAIM_NOT_EXPECTED")):
    got = claim(**kw)
    check(f"tou_claim: {label} -> {want}", got == want, got)

print("== [18] the raise-only reserve preference")
D40 = cf.synthetic_decisions().with_decision("D1", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 40.0, True),
                                             sd.Provenance.SYNTHETIC_TEST)
B40 = cf.cycle_inputs(decisions=D40, accept_provenance=cf.SYNTHETIC_ACCEPT)
D1_ITEMS = tuple(k for k in sd.items_gated_by("D1") if k != "v1_summary")


def raised(value, base=B40, **kw):
    return run_cycle(ph.with_reading(base, sc.RESERVE_RAISE_KEY, value, age_s=3600.0, **kw))


def eff(e):
    return ((e.item("charge_target").summary or {}).get("reserve") or {}).get("effective_pct")


r55, r20, r0, rnone = raised(55.0), raised(20.0), run_cycle(B40), run_cycle(ph.without(B40, sc.RESERVE_RAISE_KEY))
check("I-D1 40 and a raise to 55: the floor is 55, with PREF_RESERVE_RAISE on the items I-D1 gates",
      eff(r55) == 55.0 and all("PREF_RESERVE_RAISE" in r55.item(k).reason_codes for k in ("charge_target", "dump_to_grid",
                                                                                         "predicted_morning_soc")),
      f"{eff(r55)} {r55.item('charge_target').reason_codes[:8]}")
check("... the plan holds it: the morning SOC band is never below 55", r55.item("predicted_morning_soc").status == "OK"
      and r55.item("predicted_morning_soc").p10 >= 55.0 - dp.MORNING_ROUNDING_PCT - 1e-9, str(r55.item("predicted_morning_soc").p10))
check("a raise to 20, the fixture's 0 and an unmapped preference all leave the floor at 40, with no raise code and nothing "
      "blocked", all(eff(e) == 40.0 and "PREF_RESERVE_RAISE" not in e.item("charge_target").reason_codes
                     and e.item("charge_target").status == "OK" for e in (r20, r0, rnone)), str([eff(e) for e in (r20, r0, rnone)]))
UNUSABLE = {"unavailable (value null)": raised(None), "above 100": raised(150.0), "negative": raised(-1.0),
            "not finite": raised(float("nan")), "text": raised("55"), "a bool": raised(True),
            "observed in the future": raised(55.0, observed_at=cf.NOW + timedelta(seconds=60)),
            "in the wrong unit": run_cycle(replace(B40, site_readings=tuple(r for r in B40.site_readings if r.key != sc.RESERVE_RAISE_KEY)
                                                   + (ac.SiteReading(sc.RESERVE_RAISE_KEY, 55.0, "W", cf.NOW, "synthetic:raise"),))),
            "given twice": run_cycle(replace(B40, site_readings=B40.site_readings
                                             + (ac.SiteReading(sc.RESERVE_RAISE_KEY, 55.0, "%", cf.NOW, "synthetic:raise"),)))}
for label, e in UNUSABLE.items():
    check(f"a mapped raise preference that is {label}: BLOCKED PREF_RESERVE_RAISE_UNKNOWN on every item I-D1 gates (never "
          "back to 40 silently), the items I-D1 does not gate unaffected",
          all(e.item(k).status == "BLOCKED" and "PREF_RESERVE_RAISE_UNKNOWN" in codes(e, k) for k in D1_ITEMS)
          and all(e.item(k).status == "OK" for k in ("overnight_demand", "pv_tomorrow", "predicted_day_load")),
          str({k: e.item(k).status for k in D1_ITEMS + ("overnight_demand",)}))
helper_d1 = cf.synthetic_decisions().with_decision("D1", sd.PlanningFloor(sd.HA_RESERVE_HELPER, None, True), sd.Provenance.SYNTHETIC_TEST)
hd = run_cycle(cf.cycle_inputs(decisions=helper_d1, accept_provenance=cf.SYNTHETIC_ACCEPT))
check("I-D1 taken from the HA reserve helper: WARN DECISION_VALUE_FROM_HELPER on the items I-D1 gates (a reason code, not "
      "a blocker), so a helper never acts as a decision unseen",
      hd.item("charge_target").status == "OK" and all("DECISION_VALUE_FROM_HELPER" in hd.item(k).reason_codes
                                                      and "DECISION_VALUE_FROM_HELPER" not in codes(hd, k) for k in D1_ITEMS)
      and "DECISION_VALUE_FROM_HELPER" not in hd.item("overnight_demand").reason_codes, str(hd.item("charge_target").reason_codes))
check("... and never with an I-D1 recorded value", all("DECISION_VALUE_FROM_HELPER" not in BASE_ENV.item(k).reason_codes
                                                      for k in D1_ITEMS))
check("... the helper floor (20) is never lowered by a lower raise preference (the fixture's 0)", eff(hd) == 20.0, str(eff(hd)))
hr55 = run_cycle(ph.with_reading(cf.cycle_inputs(decisions=helper_d1, accept_provenance=cf.SYNTHETIC_ACCEPT),
                                 sc.RESERVE_RAISE_KEY, 55.0, age_s=3600.0))
check("... the raise also lifts a helper floor (helper 20, raise 55: 55)", eff(hr55) == 55.0, str(eff(hr55)))

# A33 ENG-5: the raise preference is never reported as the HA reserve helper


def res_of(e, k="charge_target"):
    return (e.item(k).summary or {}).get("reserve") or {}


def all_codes(e) -> set:
    return {c for v in tuple(e.items) + tuple(e.forecasts) for c in v.reason_codes}


rr = res_of(r55)
check("ENG-5: I-D1 40, the HA helper at the fixture's 20 and a raise preference of 55: the charge_target and dump_to_grid "
      "breakdowns keep the helper's own 20 and name the raise (reserve_raise_pct 55, binding reserve_raise, override "
      "PREF_RESERVE_RAISE); no item says the Home Assistant reserve raised the user reserve",
      all(res_of(r55, k).get("ha_reserve_pct") == 20.0 and res_of(r55, k).get("reserve_raise_pct") == 55.0
          and res_of(r55, k).get("binding") == "reserve_raise" and res_of(r55, k).get("override_code") == "PREF_RESERVE_RAISE"
          and res_of(r55, k).get("effective_pct") == 55.0 for k in ("charge_target", "dump_to_grid"))
      and "Home Assistant (" not in str(rr.get("override_reason")) and "preference" in str(rr.get("override_reason"))
      and "HA_RESERVE_RAISES_USER_RESERVE" not in all_codes(r55), f"{rr} {sorted(all_codes(r55))[:12]}")
h60 = run_cycle(ph.with_signal(B40, "reserve.ha_minimum_soc", 60.0))
h60r70 = run_cycle(ph.with_reading(ph.with_signal(B40, "reserve.ha_minimum_soc", 60.0), sc.RESERVE_RAISE_KEY, 70.0,
                                   age_s=3600.0))
check("... the helper itself binding (60 over 40, the preference at the fixture's 0): binding ha_reserve with "
      "HA_RESERVE_RAISES_USER_RESERVE, the preference listed at 0 and no PREF_RESERVE_RAISE",
      res_of(h60).get("binding") == "ha_reserve" and res_of(h60).get("ha_reserve_pct") == 60.0
      and res_of(h60).get("reserve_raise_pct") == 0.0 and res_of(h60).get("effective_pct") == 60.0
      and "HA_RESERVE_RAISES_USER_RESERVE" in h60.item("charge_target").reason_codes
      and "PREF_RESERVE_RAISE" not in all_codes(h60), str(res_of(h60)))
check("... helper 60 and preference 70: the preference binds at 70 while the breakdown keeps the helper's 60, and "
      "HA_RESERVE_RAISES_USER_RESERVE is suppressed", res_of(h60r70).get("binding") == "reserve_raise"
      and res_of(h60r70).get("ha_reserve_pct") == 60.0 and res_of(h60r70).get("effective_pct") == 70.0
      and "PREF_RESERVE_RAISE" in h60r70.item("charge_target").reason_codes
      and "HA_RESERVE_RAISES_USER_RESERVE" not in all_codes(h60r70), str(res_of(h60r70)))
check("... an unmapped preference leaves no reserve_raise_pct in the breakdown (the V1 shape)",
      "reserve_raise_pct" not in res_of(rnone) and res_of(rnone).get("effective_pct") == 40.0, str(res_of(rnone)))
VB40 = ph.verified_inputs(decisions=D40, accept_provenance=cf.SYNTHETIC_ACCEPT)
ROUTES = {}
with ph.simulated_ccr_plan_1(300.0):
    for _ev_name, _ev in (("a Saving Session tonight", SESSION_TONIGHT), ("no event", [])):
        ROUTES[_ev_name] = (
            run_cycle(ph.with_reading(ph.with_reading(VB40, sc.RESERVE_RAISE_KEY, 55.0, age_s=3600.0), "tariff.events", _ev)),
            run_cycle(ph.with_reading(ph.with_signal(VB40, "reserve.ha_minimum_soc", 55.0), "tariff.events", _ev)),
            run_cycle(ph.with_reading(VB40, "tariff.events", _ev)))


def numbers(e):
    """Every published number that rests on the effective reserve, without the breakdown that names its source."""
    out = {}
    for v in tuple(e.items) + tuple(e.forecasts):
        summ = {k: x for k, x in (v.summary or {}).items() if k != "reserve"}
        out[v.key] = (v.status, v.value, getattr(v, "p10", None), getattr(v, "p90", None), json.dumps(summ, sort_keys=True,
                                                                                                     default=str))
    return out, e.plan, e.value, e.engine_comparison, json.dumps(e.scorecard_report, sort_keys=True, default=str)


for _ev_name, (_pref, _help, _none) in ROUTES.items():
    _np, _nh, _nn = numbers(_pref), numbers(_help), numbers(_none)
    check(f"ENG-5 changes no number ({_ev_name}): a raise preference of 55 gives exactly what the HA helper at 55 gives on "
          "every item and block that rests on the reserve (charge target, plan and morning SOC, Dump stop level, the "
          "Saving Session plan, the value block, the V1 run), and differs from no raise at all (non-vacuous)",
          _np == _nh and _np[0] != _nn[0] and res_of(_pref).get("binding") == "reserve_raise"
          and res_of(_help).get("binding") == "ha_reserve" and _pref.value is not None and _pref.engine_comparison is not None,
          str([k for k in _np[0] if _np[0][k] != _nh[0][k]] + [i for i in range(1, 5) if _np[i] != _nh[i]]))
# the two consumers whose output the synthetic fixture cannot move (the V1 target is capped at 100 % and the value range is
# zero either way): the inputs they are handed, and the V1 run's own reserve breakdown
_seen: dict = {}
_orig_run, _orig_value = sc.IntelligenceEngine.run, sc.vl.project_value


def _capture_run(self, live):
    rep = _orig_run(self, live)
    _seen["live"] = (live.ha_reserve_pct, live.reserve_raise_pct)
    _seen["v1"] = ((rep.get("recommended") or {}).get("reserve") or {}) if isinstance(rep, dict) else {}
    return rep


def _capture_value(**kw):
    _seen["floor"] = kw.get("floor_pct")
    return _orig_value(**kw)


sc.IntelligenceEngine.run, sc.vl.project_value = _capture_run, _capture_value      # TEST ONLY, always restored
try:
    run_cycle(ph.with_reading(VB40, sc.RESERVE_RAISE_KEY, 55.0, age_s=3600.0))
finally:
    sc.IntelligenceEngine.run, sc.vl.project_value = _orig_run, _orig_value
check("... the V1 run and the value projection get the preference too: the V1 inputs carry the helper's own 20 and the "
      "preference 55, the V1 run's breakdown binds reserve_raise at 55, and the value projection's floor is 55",
      _seen.get("live") == (20.0, 55.0) and _seen.get("v1", {}).get("binding") == "reserve_raise"
      and _seen.get("v1", {}).get("effective_pct") == 55.0 and _seen.get("floor") == 55.0
      and sc.IntelligenceEngine.run is _orig_run and sc.vl.project_value is _orig_value, str(_seen))
check("... with export advice OK in the first and Dump advice OK in the second, so both are compared",
      ROUTES["a Saving Session tonight"][0].item("export_event").status == "OK"
      and ROUTES["no event"][0].item("dump_to_grid").status == "OK",
      str({k: (r[0].item("export_event").status, r[0].item("dump_to_grid").status) for k, r in ROUTES.items()}))

print("== [19] the register-230 grid-charge current limit is not modelled")
check("GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED on the OK charge_target and predicted_morning_soc only",
      all(sc.GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED in BASE_ENV.item(k).reason_codes for k in ("charge_target", "predicted_morning_soc"))
      and all(sc.GRID_CHARGE_CURRENT_LIMIT_NOT_MODELLED not in BASE_ENV.item(k).reason_codes
              for k in ("overnight_demand", "export_event", "dump_to_grid", "pv_tomorrow", "predicted_day_load")))

print("== [20] configuration-poll freshness (the planning half)")
je, jt, jo = (judged_reading(BASE, k) for k in ("tou.enabled", "tou.slot_table", "tou.overlay_state"))
check("a configuration-poll reading is aged by the larger of the two liveness ages (telemetry 20 s, configuration 30 s)",
      je.fresh and je.age_s == cf.CONFIG_POLL_AGE_S and jt.fresh and jt.age_s == cf.CONFIG_POLL_AGE_S, f"{je} {jt}")
check("... the overlay is telemetry, not a configuration-poll reading", jo.fresh and jo.age_s == cf.POLL_AGE_S, str(jo))
c150 = run_cycle(with_config_age(inp9, 150.0))           # I-D6 at the 900 s ceiling: only the liveness bounds bind
check("configuration liveness 150 s old, I-D6 at the 900 s ceiling: the TOU items are valid for exactly 150 s (the "
      "configuration liveness bound binds; the telemetry bound leaves 160 s, the readings' own limits 750 s)",
      all(c150.item(k).valid_until == cf.NOW + timedelta(seconds=150.0)
          for k in ("charge_target", "overnight_demand", "predicted_morning_soc")),
      str({k: c150.item(k).valid_until for k in ("charge_target", "overnight_demand")}))
prot_d6 = {k: 300.0 for k in sd.FRESHNESS_OVERRIDE_KEYS if sd.ADVISORY_LIMITS_S.get(k) is None}
prot_d6["protection.shutdown_soc_pct"] = 160.0           # a site limit between the two configuration ages below
prot_ds = snap.with_decision("D6", sd.FreshnessOverrides(prot_d6), sd.Provenance.SYNTHETIC_TEST)
prot_ok = run_cycle(with_config_age(cf.cycle_inputs(decisions=prot_ds, accept_provenance=cf.SYNTHETIC_ACCEPT), 30.0))
prot = run_cycle(with_config_age(cf.cycle_inputs(decisions=prot_ds, accept_provenance=cf.SYNTHETIC_ACCEPT), 170.0))
check("I-D2 read from the shutdown-level sensor (a configuration-poll reading) with a 160 s limit: fresh at a configuration "
      "age of 30 s (charge target OK); at 170 s it is older than its limit although the telemetry poll is 20 s old, so the "
      "charge target is BLOCKED (never the reading taken as fresh from the telemetry poll alone)",
      prot_ok.item("charge_target").status == "OK" and prot.item("charge_target").status == "BLOCKED"
      and prot.item("charge_target").value is None,
      f"{prot_ok.item('charge_target').status} {prot.item('charge_target').status} {sorted(codes(prot, 'charge_target'))[:3]}")
CFG_BAD = {"400 s old (stale)": with_config_age(BASE, 400.0), "missing": ph.without(BASE, sd.CONFIG_LIVENESS_KEY),
           "in the future": with_config_age(BASE, -60.0)}
for label, x in CFG_BAD.items():
    e = run_cycle(x)
    check(f"configuration liveness {label}, telemetry fresh: every TOU item BLOCKED, pv_tomorrow OK",
          all(e.item(k).status == "BLOCKED" for k in TOU_ITEMS) and e.item("pv_tomorrow").status == "OK"
          and not math.isnan(e.item("pv_tomorrow").value), str({k: sorted(codes(e, k))[:2] for k in ("charge_target",)}))
    check(f"... ({label}) and no configuration-poll reading is judged fresh",
          not any(judged_reading(x, k).fresh for k in sd.CONFIG_POLL_READINGS if k != "capacity.reg204_ah"))

print("== [21] published texts of the new cases")
NEW_ENVS = dict(CLASS_ENVS, **{"expiring": past, "telemetry expiring": tl, "raise unknown": UNUSABLE["text"],
                               "helper floor": hd, "partial": partial, "unchecked": unch, "low target": low_target,
                               "A35 shoulder peak": sh_peak, "A35 Agile peak": ag_peak, "A35 Agile trough": ag_tou})
red = [n for n, e in NEW_ENVS.items() if sc.REDACTED_CODE in e.reason_codes
       or any(sc.REDACTED_CODE in v.reason_codes for v in tuple(e.items) + tuple(e.forecasts))]
check(f"{len(NEW_ENVS)} new cases: no published text redacted (every new text is a fixed phrase)", red == [], str(red))

print("== [22] register 217 (protection.shutdown_soc_pct): the finite 0 % boundary case")
D217 = (cf.synthetic_decisions()
        .with_decision("D2", sd.Protection(sd.READ_ONLY_SENSOR_SNAPSHOT), sd.Provenance.SYNTHETIC_TEST)
        .with_decision("D1", sd.PlanningFloor(sd.INTELLIGENCE_USER_RESERVE, 40.0, True), sd.Provenance.SYNTHETIC_TEST))
B217 = cf.cycle_inputs(decisions=D217, accept_provenance=cf.SYNTHETIC_ACCEPT)


def at217(value):
    return ph.with_reading(B217, "protection.shutdown_soc_pct", value, age_s=cf.POLL_AGE_S)


def reserve217(e):
    return (e.item("charge_target").summary or {}).get("reserve") or {}


z217, r217_12 = run_cycle(at217(0.0)), run_cycle(at217(12.0))
zr = reserve217(z217)
z_codes = {c for v in tuple(z217.items) + tuple(z217.forecasts) for c in set(v.reason_codes) | {b for b, _t in v.blockers}}
check("register 217 at 0 % with I-D2 read from it (READ_ONLY_SENSOR_SNAPSHOT): I-D2 is satisfied from the reading (a "
      "finite 0 is a reading, never unknown): no PHYSICAL_PROTECTION_UNKNOWN, PROTECTION_LEVEL_UNKNOWN or DECISION_D2_* "
      "code anywhere, and charge_target and predicted_morning_soc are OK with numbers",
      D217.satisfied("D2", cf.SYNTHETIC_ACCEPT) and D217.value("D2").supplied_by == sd.READ_ONLY_SENSOR_SNAPSHOT
      and judged_reading(at217(0.0), "protection.shutdown_soc_pct").fresh
      and not {c for c in z_codes if c in ("PHYSICAL_PROTECTION_UNKNOWN", "PROTECTION_LEVEL_UNKNOWN")
               or c.startswith("DECISION_D2")}
      and all(z217.item(k).status == "OK" and z217.item(k).value is not None for k in ("charge_target", "predicted_morning_soc")),
      f"{sorted(z_codes)[:12]} {z217.item('charge_target').status}")
check("... nothing is lowered: the technical minimum stays the 10 % placeholder (raise-only, so 0 % never takes it below), "
      "the 40 % advisory reserve (I-D1) is unchanged and binds, with no override",
      zr.get("technical_min_pct") == sd.DEFAULT_TECHNICAL_MIN_SOC_PCT == 10.0 and zr.get("user_reserve_pct") == 40.0
      and zr.get("effective_pct") == 40.0 and zr.get("binding") == "user_reserve" and zr.get("override_code") is None, str(zr))
check("... non-vacuity of raise-only: the same route at 12 % raises the technical minimum to 12 while the 40 % reserve "
      "still binds", reserve217(r217_12).get("technical_min_pct") == 12.0 and reserve217(r217_12).get("effective_pct") == 40.0,
      str(reserve217(r217_12)))
z_text = json.dumps([z217.item("charge_target").summary] + [[list(b) for b in v.blockers] + list(v.reason_codes)
                                                            for v in tuple(z217.items) + tuple(z217.forecasts)],
                    default=str).lower()
check("... the BMS limit stays UNKNOWN: no decision, reading or published item text claims one (register 217 is the "
      "inverter's own shutdown setting, I-D2, never a BMS value), and the reserve block carries no 0 % protection figure",
      "bms" not in z_text and not any("bms" in k.lower() for k in ac.SITE_READING_KEYS)
      and not any("bms" in str(t).lower() for t in sd.DECISION_TITLES.values())
      and 0.0 not in (zr.get("technical_min_pct"), zr.get("effective_pct"), zr.get("user_reserve_pct")), z_text[:200])

print("== [23] published blocker texts never make a verified tariff a window source (R9D-1)")
BAD_WINDOW_PHRASES = ("tariff window", "from a verified tariff")


def blocker_texts(e) -> list:
    """Every blocker text an envelope publishes: its items', its forecasts' and its own."""
    return [t for v in tuple(e.items) + tuple(e.forecasts) for _c, t in v.blockers] + [t for _c, t in e.blockers]


def text_literals(path) -> list:
    """Every str constant of a module except its docstrings (module, class and function)."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


PUB_TEXTS = {t for e in list(ENVS.values()) + list(NEW_ENVS.values()) for t in blocker_texts(e)}
bad_pub = sorted(t for t in PUB_TEXTS if any(p in str(t).lower() for p in BAD_WINDOW_PHRASES))
ng_text = dict(CLASS_ENVS["no Grid slot"].item("overnight_demand").blockers).get("CHARGE_WINDOW_UNKNOWN", "")
check(f"{len(PUB_TEXTS)} distinct published blocker texts of the suite's cases: none says 'tariff window' or 'from a "
      "verified tariff' (a verified tariff only cross-checks the TOU window); the no-Grid-slot table publishes the "
      "planning layer's CHARGE_WINDOW_UNKNOWN text, which names the TOU table as the only window source",
      bad_pub == [] and len(PUB_TEXTS) > 20 and ng_text.startswith("no classified TOU grid-charge window")
      and "only cross-checks" in ng_text, f"{bad_pub[:3]} {ng_text!r}")
ENGINE_FILES = sorted({m.__file__ for n, m in sys.modules.items()
                       if (n == "intelligence" or n.startswith("intelligence.")) and ".prototypes" not in n
                       and ".tests" not in n and getattr(m, "__file__", None)})
bad_lit = [(Path(f).name, s) for f in ENGINE_FILES for s in text_literals(f)
           if any(p in s.lower() for p in BAD_WINDOW_PHRASES)]
check(f"... nor does any text literal of the {len(ENGINE_FILES)} engine modules the cycle loads (docstrings aside), so "
      "every blocker text is covered, also a fallback no case reaches (the cycle's own CHARGE_WINDOW_UNKNOWN)",
      bad_lit == [] and len(ENGINE_FILES) > 10
      and {"shadow_cycle.py", "daily_plan.py", "tariff.py", "tou_table.py"} <= {Path(f).name for f in ENGINE_FILES},
      str(bad_lit[:3]))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all cycle-planning checks passed")
