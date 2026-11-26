#!/usr/bin/env python3
"""Planning stream: the daily plan (intelligence/daily_plan.py). SYNTHETIC values only.

  [1] the charge window: always the TOU table's single grid-charge run (intelligence/tou_table.py); with a verified
      tariff that names a cheap run, every rate slot of the TOU occurrence from now on must lie in the cheap band (INFO
      CHARGE_WINDOW_TOU_INSIDE_TARIFF), partly or wholly outside BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE (no overlap rule),
      a fresh table that does not classify BLOCKs CHARGE_WINDOW_TOU_UNCHECKED, a verified tariff alone is never a window;
      a verified tariff that names no cheap run (checked by [1c]), or none, leaves the TOU window with a WARN that says
      which, else BLOCK; the window rests on the table, both enables and the overlay and carries its run
  [1b] A30 (ENG-1, ENG-2): the check uses the tariff's rate slots, never the cheap run's cut boundaries: a verified cheap
      run across local midnight with the TOU window inside (OK) and outside (BLOCK); a sweep every 15 min over 24 h with
      tariff and TOU equal (00:30-05:30 and 01:00-04:30) never disagrees; one slot of the window above the band's ceiling
      BLOCKs (until `now` has passed it); before the window the analysis may name another run (the slots decide); rate
      slots short of the clipped occurrence BLOCK CHARGE_WINDOW_TOU_UNCHECKED, also when they cover half of it (F3);
      coverage short leaves the TOU window with the corrected WARN text
  [1c] A35 (R1-ENG-1 / F1): a verified tariff that names no cheap run still checks the slots it prices: a slot of the
      clipped occurrence at or above `low` (A38: the lowest rate priced in the 24 h before and after now, [1d]) plus
      PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE (the shoulder-slot case, an
      Agile-like peak, a short and a long cheap run, the boundary, a partly priced occurrence, the clip), otherwise the
      TOU window with a WARN whose text says whether every
      priced slot is within the spread or the window is not wholly priced (no slots ahead included); a 15-min sweep
      over 24 h with tariff and TOU equal never disagrees; F2 (a cheap-rate drop of 2 p or more at midnight) pinned as
      the documented fail-closed BLOCK; no 13.8 code is ever emitted with another severity
  [1d] A38 Part A (N1, N2): the no-run check's lowest rate also reads the 24 h before now: one current-day event with
      the TOU window at the peak BLOCKs at every half-hour until the window ends, then shows the unpriced-occurrence
      residual WARN; the slot that holds now counts; a flat price rise BLOCKs while the old rate is in the look-back,
      then passes (the widened F2); a two-rate rise keeps its named run; agreeing windows on full, current-day and
      next-day payloads never disagree; an occurrence the payload does not price keeps the 'does not price the whole'
      WARN
  [1e] A41 (R7-E3): INFO CHARGE_WINDOW_NOT_PRICED exactly when the window stands on the TOU table without a price check
      of its whole occurrence (no usable verified tariff, or one that does not price the whole occurrence); never when
      the whole occurrence was priced within the spread, never beside a named-run INSIDE result, never on a refused
      window; always INFO (the 13.8 severity check covers it); ENG9-1: the whole-occurrence boundary itself: a table
      that prices more than half but not all of the clipped occurrence carries it, and a table whose first slot starts
      after the window's start but at or before now (now inside the window) prices the clipped occurrence whole and
      does not carry it, nor does one whose first slot starts after now but before the window's start (now before it)
  [2] property sweep (>= 500 seeded cases): an OK plan never plans below the effective reserve + margin; the headroom
      ceiling is never below it; morning SOC bands ordered and in range; a non-OK target gives no plan
  [3] every planning output is BLOCKED when any gating decision is not satisfied (the cycle, on the real WP-1 rules: the
      three TOU readings are I-D6 keys and the quality layer judges the configuration-poll liveness)
  [4] cycling cost only with the wear-cost preference; precharge timing from the V1 PRE_WINDOW reasons
  [5] the Saving Session energy plan (events.advise_event) and the morning anchor
"""

from __future__ import annotations

import math
import random
import sys
from datetime import date, datetime, timedelta, timezone
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
from intelligence import tariff as tf  # noqa: E402
from intelligence.baselines import replay as bl_replay  # noqa: E402
from intelligence.charge_target import ChargeTargetInputs, advise_charge_target  # noqa: E402
from intelligence.config import SiteConfig  # noqa: E402
from intelligence.overnight import NightObservation, OvernightSettings, learn_overnight  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402
from intelligence.timeutil import zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
Z = zone("Europe/London")
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def tou(value, fresh=True):
    return InputState("tou.slot_table", value, fresh, 20.0, 300.0)


print("== [1] the charge window")
TOU_STARTS = ["00:00", "01:00", "04:30", "08:00", "16:00", "19:00"]
TOU_SOURCES = ["None", "Grid", "None", "None", "None", "None"]


def v2(starts=TOU_STARTS, sources=TOU_SOURCES, power=5000.0):
    """A schema v2 TOU table (six rows, flags agreeing with the texts, mode None as the dongle shows it)."""
    return [{"slot": i + 1, "start": starts[i], "end": starts[(i + 1) % 6], "target_soc_pct": 80.0 if sources[i] == "Grid" else 20.0,
             "charge_source": sources[i], "flags_raw": 1 if sources[i] == "Grid" else 0, "mode": "None", "power_w": power}
            for i in range(6)]


def tou_states(enabled=True, grid=True, overlay="NONE"):
    return {"tou_enabled": InputState("tou.enabled", enabled, True, 30.0, 300.0),
            "grid_charge_enabled": InputState("tou.grid_charge_enabled", grid, True, 30.0, 300.0),
            "tou_overlay": InputState("tou.overlay_state", overlay, True, 20.0, 300.0)}


def choose(imp_res, imp_st, table, **over):
    kw = tou_states()
    kw.update(over)
    return dp.choose_charge_window(NOW, Z, imp_res, imp_st, table, **kw)


SLOT = v2()
NARROW = v2(["00:00", "02:00", "03:00", "08:00", "16:00", "19:00"])          # Grid 02:00-03:00
PARTIAL = v2(["00:00", "00:30", "02:00", "08:00", "16:00", "19:00"])         # Grid 00:30-02:00
APART = v2(["00:00", "13:00", "15:00", "16:00", "17:00", "19:00"])           # Grid 13:00-15:00
imp = tf.assess_rates(InputState("tariff.import_rates", ph.rates_payload(NOW), True, 120.0, 300.0), NOW)
imp_state = InputState("tariff.import_rates", ph.rates_payload(NOW), True, 120.0, 300.0)
cw, notes = choose(imp, imp_state, tou(SLOT))
check("a verified tariff whose cheap run holds the TOU window: the TOU window 01:00-04:30, checked against the tariff "
      "(source TARIFF, INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF)", cw is not None and cw.source == dp.SOURCE_TARIFF
      and cw.label == "01:00-04:30" and cw.state.key == sd.CHARGE_WINDOW_KEY and cw.state.value == (60, 270) and cw.state.fresh
      and any(f.code == "CHARGE_WINDOW_TOU_INSIDE_TARIFF" and f.severity == "INFO" for f in notes), str(cw))
check("... its validity rests on the tariff, the table, both enables and the overlay, and it carries the TOU run",
      cw.input_keys == ("tariff.import_rates", "tou.slot_table", "tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state")
      and cw.tou_run is not None and (cw.tou_run.start_min, cw.tou_run.end_min) == (60, 270), str(cw.input_keys))
nv = tf.TariffResult("import", tf.NO_VALUE)
cw2, n2 = choose(nv, None, tou(SLOT))
check("no verified tariff: the TOU window, with a WARN", cw2 is not None and cw2.source == dp.SOURCE_TOU_TABLE
      and any(f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" and f.severity == "WARN" for f in n2)
      and cw2.input_keys == ("tou.slot_table", "tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state"))
check("... its next occurrence is tomorrow 01:00-04:30", cw2.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC)
      and cw2.end == datetime(2030, 1, 16, 4, 30, tzinfo=UTC))
cw3, n3 = choose(nv, None, tou(SLOT, fresh=False))
check("neither: None and a BLOCK CHARGE_WINDOW_UNKNOWN (never the example window)", cw3 is None
      and any(f.code == "CHARGE_WINDOW_UNKNOWN" and f.severity == "BLOCK" for f in n3))
cw_v1, n_v1 = choose(nv, None, tou([{"slot": 1, "start": "01:00", "end": "04:30", "target_soc_pct": 80}]))
check("a one-row v1 table is never a window any more (TOU_TABLE_LEGACY_SCHEMA, CHARGE_WINDOW_UNKNOWN)", cw_v1 is None
      and {"TOU_TABLE_LEGACY_SCHEMA", "CHARGE_WINDOW_UNKNOWN"} <= {f.code for f in n_v1 if f.severity == "BLOCK"},
      str([f.code for f in n_v1]))
check("next_start_after: the first start at or after a time", cw2.next_start_after(cw2.end, Z) == datetime(2030, 1, 17, 1, 0, tzinfo=UTC))
cur_only = InputState("tariff.import_rates", ph.go_like_rates(date(2030, 1, 15), 1), True, 120.0, 300.0)
cur_res = tf.assess_rates(cur_only, NOW)
cwc, nc = choose(cur_res, cur_only, None)
check("current-day rates only and NO TOU table: even a payload judged without a coverage need names no window (the cheap "
      "search period is not covered), so the result is BLOCK, never a run ending at midnight",
      cur_res.verified and cwc is None and any(f.code == "TARIFF_COVERAGE_SHORT" for f in nc)
      and any(f.code == "CHARGE_WINDOW_UNKNOWN" and f.severity == "BLOCK" for f in nc), str([f.code for f in nc]))
mis_cw, mis_n = choose(imp, imp_state, tou(NARROW))
check("a verified tariff 01:00-04:30 and a TOU grid slot 02:00-03:00 inside it: the window is the TOU window (never "
      "more than the inverter's slot), INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF, no disagreement",
      mis_cw is not None and mis_cw.label == "02:00-03:00" and mis_cw.source == dp.SOURCE_TARIFF
      and mis_cw.start == datetime(2030, 1, 16, 2, 0, tzinfo=UTC)
      and any(f.code == "CHARGE_WINDOW_TOU_INSIDE_TARIFF" for f in mis_n)
      and not any(f.code == "CHARGE_WINDOW_SOURCES_DISAGREE" for f in mis_n), str(mis_cw))
par_cw, par_n = choose(imp, imp_state, tou(PARTIAL))
check("a TOU window 00:30-02:00 that extends outside the cheap run 01:00-04:30: None with a BLOCK "
      "CHARGE_WINDOW_SOURCES_DISAGREE (the overlap rule is gone)", par_cw is None
      and any(f.code == "CHARGE_WINDOW_SOURCES_DISAGREE" and f.severity == "BLOCK" for f in par_n), str([f.code for f in par_n]))
far_cw, far_n = choose(imp, imp_state, tou(APART))
check("... no overlap at all: None with a BLOCK CHARGE_WINDOW_SOURCES_DISAGREE", far_cw is None
      and any(f.code == "CHARGE_WINDOW_SOURCES_DISAGREE" and f.severity == "BLOCK" for f in far_n))
for label, table, over, extra in (
        ("an unknown slot", v2(sources=["None", "Grid", "Unknown", "None", "None", "None"]), {}, "TOU_SLOT_SOURCE_UNKNOWN"),
        ("two grid runs", v2(sources=["None", "Grid", "None", "Grid", "None", "None"]), {}, "TOU_MULTIPLE_GRID_WINDOWS"),
        ("the TOU enable off", SLOT, {"tou_enabled": InputState("tou.enabled", False, True, 30.0, 300.0)}, "TOU_DISABLED"),
        ("a v1 table", [{"slot": 1, "start": "01:00", "end": "04:30", "target_soc_pct": 80}], {}, "TOU_TABLE_LEGACY_SCHEMA")):
    u_cw, u_n = choose(imp, imp_state, tou(table), **over)
    check(f"a verified tariff beside a fresh table that does not classify ({label}): None, BLOCK "
          f"CHARGE_WINDOW_TOU_UNCHECKED and {extra} (a WARN before)", u_cw is None
          and {"CHARGE_WINDOW_TOU_UNCHECKED", extra} <= {f.code for f in u_n if f.severity == "BLOCK"}, str([f.code for f in u_n]))
st_cw, st_n = choose(imp, imp_state, tou(SLOT, fresh=False))
check("a verified tariff and a stale table: None, BLOCK CHARGE_WINDOW_UNKNOWN (a verified tariff alone is never a window)",
      st_cw is None and any(f.code == "CHARGE_WINDOW_UNKNOWN" and f.severity == "BLOCK" for f in st_n)
      and not any(f.code == "CHARGE_WINDOW_TOU_UNCHECKED" for f in st_n), str([f.code for f in st_n]))
flat = tf.assess_rates(InputState("tariff.import_rates", ph.go_like_rates(date(2030, 1, 15), 2, cheap=(0, 0), cheap_gbp=0.25,
                                                                          peak_gbp=0.25), True, 120.0, 300.0), NOW)
fl_cw, fl_n = choose(flat, imp_state, tou(SLOT))
check("a verified tariff that names no cheap run (flat): the TOU window with its WARN", fl_cw is not None
      and fl_cw.source == dp.SOURCE_TOU_TABLE and any(f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" for f in fl_n), str(fl_cw))
check("the old TOU readers, the overlap rule and the tariff's own window (A30) are gone", not any(hasattr(dp, n) for n in (
    "tou_window", "tou_slots", "_grid_flag", "_checked_against_tou", "GRID_FLAG_KEYS", "tariff_window",
    "_tou_inside_tariff", "_local_minutes", "_state_for_window")))

print("== [1b] A30: the TOU window against the verified tariff's rate slots")
D15 = date(2030, 1, 15)
BLOCK_CODES_13_8 = {"CHARGE_WINDOW_TOU_UNCHECKED", "CHARGE_WINDOW_CROSSES_MIDNIGHT", "CHARGE_WINDOW_NOT_REPRESENTABLE",
                    "CHARGE_WINDOW_SOURCES_DISAGREE"}
SEEN: list = []                                          # every finding of this section, for the severity check


def rates(day, days, cheap_ranges, overrides=None):
    """Half-hour synthetic rows (fictional 2030 prices) over `days` local days from `day`: CHEAP_GBP where the slot's local
    start minute lies in any of `cheap_ranges`, PEAK_GBP elsewhere; `overrides` {local 'HH:MM': GBP} prices single slots."""
    rows = ph.go_like_rates(day, days, cheap=(0, 0))
    for r in rows:
        m = int(r["start"][11:13]) * 60 + int(r["start"][14:16])
        if any(a <= m < b for a, b in cheap_ranges):
            r["value_inc_vat"] = ph.CHEAP_GBP
        if overrides and r["start"][11:16] in overrides:
            r["value_inc_vat"] = overrides[r["start"][11:16]]
    return rows


def at(now, rows, table, verified=True):
    """choose_charge_window at `now` with a tariff from `rows` (judged fresh, no coverage need) and a fresh TOU table."""
    st = InputState("tariff.import_rates", rows, True, 120.0, 300.0)
    res = tf.assess_rates(st, now) if verified else tf.TariffResult("import", tf.NO_VALUE)
    kw = tou_states()
    cw_, n_ = dp.choose_charge_window(now, Z, res, st if verified else None, tou(table), **kw)
    SEEN.extend(n_)
    return cw_, n_


def found(n_, code, severity=None):
    return any(f.code == code and (severity is None or f.severity == severity) for f in n_)


ACROSS = rates(date(2030, 1, 14), 3, [(1410, 1440), (0, 330)])        # cheap 23:30-05:30, a run across local midnight
INSIDE_T = v2(["00:00", "01:00", "04:30", "08:00", "16:00", "19:00"])  # Grid 01:00-04:30
OUTSIDE_T = v2(["00:00", "06:00", "08:00", "10:00", "16:00", "19:00"])  # Grid 06:00-08:00, at peak price
cw_in, n_in = at(NOW, ACROSS, INSIDE_T)
check("a verified cheap run across local midnight (23:30-05:30) with the TOU window 01:00-04:30 inside it: the TOU window, "
      "source TARIFF, INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF; no CHARGE_WINDOW_CROSSES_MIDNIGHT (the tariff run may cross "
      "midnight, only the TOU window must lie on one date)", cw_in is not None and cw_in.source == dp.SOURCE_TARIFF
      and cw_in.label == "01:00-04:30" and cw_in.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC)
      and found(n_in, "CHARGE_WINDOW_TOU_INSIDE_TARIFF", "INFO") and not found(n_in, "CHARGE_WINDOW_CROSSES_MIDNIGHT")
      and not found(n_in, "CHARGE_WINDOW_FROM_TOU_TABLE"), str([(f.code, f.severity) for f in n_in]))
cw_out, n_out = at(NOW, ACROSS, OUTSIDE_T)
check("... the same tariff with the TOU window 06:00-08:00 (peak price, outside the run): None, BLOCK "
      "CHARGE_WINDOW_SOURCES_DISAGREE (ENG-1: it was the TOU window with a WARN and an OK charge target)", cw_out is None
      and found(n_out, "CHARGE_WINDOW_SOURCES_DISAGREE", "BLOCK") and not found(n_out, "CHARGE_WINDOW_FROM_TOU_TABLE")
      and not found(n_out, "CHARGE_WINDOW_CROSSES_MIDNIGHT"), str([(f.code, f.severity) for f in n_out]))

T_0030_0530 = v2(["00:00", "00:30", "05:30", "08:00", "16:00", "19:00"])    # Grid 00:30-05:30
EQUAL = (("00:30-05:30", T_0030_0530, [(30, 330)], (30, 330)), ("01:00-04:30", INSIDE_T, [(60, 270)], (60, 270)))
for label, table, cheap, minutes in EQUAL:
    rows = rates(date(2030, 1, 15), 3, cheap)
    bad, tou_only = [], []
    for k in range(96):
        now = datetime(2030, 1, 16, 0, 0, tzinfo=UTC) + timedelta(minutes=15 * k)
        cw_k, n_k = at(now, rows, table)
        if cw_k is None or found(n_k, "CHARGE_WINDOW_SOURCES_DISAGREE") or cw_k.local_minutes != minutes \
                or not found(n_k, "CHARGE_WINDOW_TOU_INSIDE_TARIFF") or not cw_k.end > now:
            bad.append((now.strftime("%H:%M"), None if cw_k is None else cw_k.label, [f.code for f in n_k][-2:]))
        if cw_k is not None and cw_k.source != dp.SOURCE_TARIFF:
            tou_only.append(now.strftime("%H:%M"))
    check(f"tariff and TOU both {label}, every 15 min over 24 h (96 times, in and out of the window): always the TOU window "
          "checked against the tariff (INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF), never CHARGE_WINDOW_SOURCES_DISAGREE (ENG-2: "
          "it disagreed for most of every window)", bad == [] and tou_only == [], str(bad[:4] + tou_only[:4]))

ONE_UP = rates(date(2030, 1, 15), 3, [(60, 270)], {"03:00": 0.10})    # 10 p: above the 7.5 + 0.5 ceiling, spread kept
AT_CEIL = rates(date(2030, 1, 15), 3, [(60, 270)], {"03:00": ph.CHEAP_GBP + 0.005})   # 8.0 p: exactly the ceiling
cw_up, n_up = at(NOW, ONE_UP, INSIDE_T)
cw_ceil, n_ceil = at(NOW, AT_CEIL, INSIDE_T)
check("a TOU window 01:00-04:30 with one rate slot (03:00-03:30) priced above the cheap band's ceiling: None, BLOCK "
      "CHARGE_WINDOW_SOURCES_DISAGREE", cw_up is None and found(n_up, "CHARGE_WINDOW_SOURCES_DISAGREE", "BLOCK"),
      str([f.code for f in n_up]))
check("... a slot priced exactly at the ceiling is in the band: the TOU window, INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF",
      cw_ceil is not None and cw_ceil.label == "01:00-04:30" and found(n_ceil, "CHARGE_WINDOW_TOU_INSIDE_TARIFF"),
      str([f.code for f in n_ceil]))
up_in = datetime(2030, 1, 16, 2, 30, tzinfo=UTC)
up_past = datetime(2030, 1, 16, 3, 45, tzinfo=UTC)
cw_ui, n_ui = at(up_in, ONE_UP, INSIDE_T)
cw_up2, n_up2 = at(up_past, ONE_UP, INSIDE_T)
check("... inside the window, before the dear slot (02:30): still BLOCK CHARGE_WINDOW_SOURCES_DISAGREE (the clipped "
      "occurrence 02:30-04:30 holds it)", cw_ui is None and found(n_ui, "CHARGE_WINDOW_SOURCES_DISAGREE", "BLOCK"),
      str([f.code for f in n_ui]))
check("... once `now` (03:45) has passed it, the clipped occurrence 03:45-04:30 is all in the band: the TOU window "
      "(today's occurrence), INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF", cw_up2 is not None
      and cw_up2.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC) and found(n_up2, "CHARGE_WINDOW_TOU_INSIDE_TARIFF"),
      str([f.code for f in n_up2]))

COSY = rates(date(2030, 1, 15), 3, [(60, 270), (780, 960)])          # two cheap runs a day: 01:00-04:30 and 13:00-16:00
AFTERNOON_T = v2(["00:00", "13:00", "16:00", "17:00", "18:00", "19:00"])   # Grid 13:00-16:00
noon = datetime(2030, 1, 16, 12, 0, tzinfo=UTC)
named, _nn = tf.cheap_window(tf.assess_rates(InputState("tariff.import_rates", COSY, True, 120.0, 300.0), noon), noon)
cw_noon, n_noon = at(noon, COSY, AFTERNOON_T)
check("before the window (12:00, TOU 13:00-16:00 today): the cheap-run analysis names tomorrow's longer 01:00-04:30 run, "
      "yet the window's own slots are all in the band, so the TOU window 13:00-16:00 today stands, INFO "
      "CHARGE_WINDOW_TOU_INSIDE_TARIFF (the run's boundaries are never the check)",
      named is not None and named.start == datetime(2030, 1, 17, 1, 0, tzinfo=UTC) and cw_noon is not None
      and cw_noon.start == datetime(2030, 1, 16, 13, 0, tzinfo=UTC) and found(n_noon, "CHARGE_WINDOW_TOU_INSIDE_TARIFF"),
      f"{named} {[f.code for f in n_noon]}")
late = datetime(2030, 1, 16, 3, 0, tzinfo=UTC)
named3, _n3 = tf.cheap_window(tf.assess_rates(InputState("tariff.import_rates", rates(D15, 3, [(60, 270)]), True, 120.0,
                                                         300.0), late), late)
check("... the cut run of ENG-2: at 03:00 the analysis names tomorrow's run cut by its 24 h horizon (01:00-03:00), and "
      "the window is still today's occurrence, checked by its slots (OK)", named3 is not None
      and (named3.start, named3.end) == (datetime(2030, 1, 17, 1, 0, tzinfo=UTC), datetime(2030, 1, 17, 3, 0, tzinfo=UTC))
      and named3.ceiling_p_per_kwh == 100.0 * ph.CHEAP_GBP + tf.PROPOSED_CHEAP_BAND_P_PER_KWH
      and (lambda r: r[0] is not None and r[0].start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC))(
          at(late, rates(D15, 3, [(60, 270)]), INSIDE_T)), str(named3))

# rate slots short of the clipped occurrence: reachable on the long autumn day, when the next TOU occurrence ends more
# than 24 h after `now` (the cheap-run search period, which the slots cover exactly here)
DST_NOW = datetime(2030, 10, 26, 5, 0, tzinfo=UTC)                   # 06:00 BST; the clocks go back on 27 October
DST_T = v2(["00:00", "05:00", "06:00", "08:00", "16:00", "19:00"])     # Grid 05:00-06:00
short_rows = []
t0 = DST_NOW
while t0 < DST_NOW + timedelta(hours=24):
    t1 = t0 + timedelta(minutes=30)
    cheap_slot = datetime(2030, 10, 27, 0, 0, tzinfo=UTC) <= t0 < datetime(2030, 10, 27, 4, 0, tzinfo=UTC)
    short_rows.append({"start": t0.isoformat(), "end": t1.isoformat(),
                       "value_inc_vat": ph.CHEAP_GBP if cheap_slot else ph.PEAK_GBP})
    t0 = t1
cw_sh, n_sh = at(DST_NOW, short_rows, DST_T)
check("rate slots that cover the 24 h search period but not the clipped TOU occurrence (05:00-06:00 on the 25 h autumn "
      "day, which ends 25 h after now): None, BLOCK CHARGE_WINDOW_TOU_UNCHECKED, never INSIDE",
      cw_sh is None and found(n_sh, "CHARGE_WINDOW_TOU_UNCHECKED", "BLOCK")
      and not found(n_sh, "CHARGE_WINDOW_TOU_INSIDE_TARIFF"), str([f.code for f in n_sh]))
# F3: the same day with the clipped occurrence HALF covered: the slots end at now + 24 h (05:00Z), inside the TOU
# occurrence 04:30-05:30 (GMT after the change), and the covered half 04:30-05:00 is cheap, so only the coverage rule can
# refuse it (a check of part of the occurrence, such as its first half, would call it inside the band)
HALF_T = v2(["00:00", "04:30", "05:30", "08:00", "16:00", "19:00"])    # Grid 04:30-05:30
half_rows = [dict(x, value_inc_vat=ph.CHEAP_GBP if datetime(2030, 10, 27, 0, 0, tzinfo=UTC)
                  <= datetime.fromisoformat(x["start"]) < datetime(2030, 10, 27, 5, 0, tzinfo=UTC) else ph.PEAK_GBP)
             for x in short_rows]
half_res = tf.assess_rates(InputState("tariff.import_rates", half_rows, True, 120.0, 300.0), DST_NOW)
half_band, _hn = tf.cheap_window(half_res, DST_NOW)
half_a, half_b = datetime(2030, 10, 27, 4, 30, tzinfo=UTC), datetime(2030, 10, 27, 5, 30, tzinfo=UTC)
cw_half, n_half = at(DST_NOW, half_rows, HALF_T)
check("F3: the clipped TOU occurrence (04:30-05:30Z) only half covered, the covered half in the cheap band of a named "
      "run: None, BLOCK CHARGE_WINDOW_TOU_UNCHECKED, never INSIDE (the whole occurrence must be covered)",
      half_band is not None and half_res.covers(half_a, half_a + (half_b - half_a) / 2)
      and not half_res.covers(half_a, half_b)
      and all(half_band.in_band(s) for s in half_res.overlapping(half_a, half_b))
      and cw_half is None and found(n_half, "CHARGE_WINDOW_TOU_UNCHECKED", "BLOCK")
      and not found(n_half, "CHARGE_WINDOW_TOU_INSIDE_TARIFF"), str([(f.code, f.severity) for f in n_half]))

cur = rates(D15, 1, [(60, 270)])                                      # today's rates only: tomorrow's not published
cw_cs, n_cs = at(NOW, cur, INSIDE_T)
cs_text = [f.text for f in n_cs if f.code == "CHARGE_WINDOW_FROM_TOU_TABLE"]
check("a verified tariff whose rates do not cover the search period (coverage short): the TOU window with WARN "
      "CHARGE_WINDOW_FROM_TOU_TABLE, its text says the verified tariff names no cheap run (never 'no verified tariff'), "
      "and the tariff's own WARN TARIFF_COVERAGE_SHORT stays in the findings", cw_cs is not None
      and cw_cs.source == dp.SOURCE_TOU_TABLE and found(n_cs, "CHARGE_WINDOW_FROM_TOU_TABLE", "WARN")
      and found(n_cs, "TARIFF_COVERAGE_SHORT", "WARN") and len(cs_text) == 1
      and "names no cheap run" in cs_text[0] and "no verified tariff" not in cs_text[0]
      and "does not price the whole TOU window" in cs_text[0], str(cs_text))
flat_rows = ph.go_like_rates(D15, 2, cheap=(0, 0), cheap_gbp=0.25, peak_gbp=0.25)
cw_fl, n_fl = at(NOW, flat_rows, INSIDE_T)
cw_nv, n_nv = at(NOW, ACROSS, INSIDE_T, verified=False)
fl_text = [f.text for f in n_fl if f.code == "CHARGE_WINDOW_FROM_TOU_TABLE"]
nv_text = [f.text for f in n_nv if f.code == "CHARGE_WINDOW_FROM_TOU_TABLE"]
check("... a flat verified tariff the same (TARIFF_CHEAP_RUN_TOO_LONG kept), while no verified tariff says 'no verified "
      "tariff'", cw_fl is not None and found(n_fl, "TARIFF_CHEAP_RUN_TOO_LONG") and len(fl_text) == 1
      and "names no cheap run" in fl_text[0] and cw_nv is not None and len(nv_text) == 1
      and nv_text[0].startswith("no verified tariff"), f"{fl_text} {nv_text}")
print("== [1c] A35: a verified tariff that names no cheap run still checks the slots it prices")
D14 = date(2030, 1, 14)
WITHIN = "every priced slot of the TOU window is within the minimum cheap spread of its lowest rate"
PARTLY = "does not price the whole TOU window"
PEAK_T = v2(["00:00", "17:00", "19:00", "20:00", "21:00", "22:00"])    # Grid 17:00-19:00, at the evening peak
TROUGH_T = v2(["00:00", "02:00", "04:00", "08:00", "16:00", "19:00"])  # Grid 02:00-04:00


def no_run(now, rows):
    """The code cheap_window gives for these rows at `now` (a verified tariff), or None when it names a run."""
    band_, n_ = tf.cheap_window(tf.assess_rates(InputState("tariff.import_rates", rows, True, 120.0, 300.0), now), now)
    return None if band_ is not None else (n_[0].code if n_ else "NONE")


def blocked(res, code="CHARGE_WINDOW_SOURCES_DISAGREE"):
    cw_, n_ = res
    return cw_ is None and found(n_, code, "BLOCK") and not found(n_, "CHARGE_WINDOW_FROM_TOU_TABLE") \
        and not found(n_, "CHARGE_WINDOW_TOU_INSIDE_TARIFF")


def tou_warn(res, text):
    cw_, n_ = res
    t_ = [f.text for f in n_ if f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" and f.severity == "WARN"]
    return cw_ is not None and cw_.source == dp.SOURCE_TOU_TABLE and len(t_) == 1 and text in t_[0] \
        and "names no cheap run" in t_[0] and not found(n_, "CHARGE_WINDOW_SOURCES_DISAGREE")


def desc(res):
    return f"{None if res[0] is None else res[0].label} {[(f.code, f.severity) for f in res[1]]}"


SHOULDER = (("05:30-06:00 at 9 p", rates(D14, 4, [(30, 330)], {"05:30": 0.09})),
            ("12:00-12:30 at 9.4 p", rates(D14, 4, [(30, 330)], {"12:00": 0.094})))
for label, rows in SHOULDER:
    res_sh = at(NOW, rows, PEAK_T)
    check(f"the reviewer's shoulder-slot case (7.5 p 00:30-05:30, 30 p otherwise, one shoulder slot {label}): the "
          "tariff names no cheap run (TARIFF_NO_PRICE_SPREAD, kept), and the TOU window 17:00-19:00 at the 30 p peak "
          "BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE (R1-ENG-1 / F1: it was the TOU window, OK at 100 %)",
          no_run(NOW, rows) == "TARIFF_NO_PRICE_SPREAD" and blocked(res_sh)
          and found(res_sh[1], "TARIFF_NO_PRICE_SPREAD", "WARN"), desc(res_sh))
sh_block = [f for f in at(NOW, SHOULDER[0][1], PEAK_T)[1] if f.code == "CHARGE_WINDOW_SOURCES_DISAGREE"]
check("... its text says a slot of the TOU window is at least the minimum cheap spread above the verified tariff's "
      "lowest rate while the tariff names no cheap run (no number in the text)", len(sh_block) == 1
      and "at least the minimum cheap spread above" in sh_block[0].text and "names no cheap run" in sh_block[0].text
      and not any(ch.isdigit() for ch in sh_block[0].text), str([f.text for f in sh_block]))
res_sh_eq = at(NOW, SHOULDER[0][1], T_0030_0530)
check("... the same shoulder-slot tariff with the TOU window equal to the cheap run (00:30-05:30): the TOU window with "
      "WARN CHARGE_WINDOW_FROM_TOU_TABLE, every priced slot within the spread", tou_warn(res_sh_eq, WITHIN), desc(res_sh_eq))

AGILE = ph.go_like_rates(D14, 4, cheap=(0, 0))
for _r in AGILE:                                     # smooth synthetic prices: 10 p at 03:00 rising to 35 p at 15:00
    _m = int(_r["start"][11:13]) * 60 + int(_r["start"][14:16])
    _r["value_inc_vat"] = round((22.5 - 12.5 * math.cos(2 * math.pi * (_m - 180) / 1440.0)) / 100.0, 4)
res_tr, res_pk, res_5h = at(NOW, AGILE, TROUGH_T), at(NOW, AGILE, PEAK_T), at(NOW, AGILE, T_0030_0530)
check("a smooth Agile-like day names no cheap run (TARIFF_NO_PRICE_SPREAD); a TOU window in the trough (02:00-04:00, "
      "less than 2 p above the lowest rate): the TOU window with WARN, every priced slot within the spread",
      no_run(NOW, AGILE) == "TARIFF_NO_PRICE_SPREAD" and tou_warn(res_tr, WITHIN), desc(res_tr))
check("... a TOU window at the evening peak (17:00-19:00, more than 2 p above the lowest): BLOCK "
      "CHARGE_WINDOW_SOURCES_DISAGREE", blocked(res_pk), desc(res_pk))
check("... a 5 h TOU window 00:30-05:30 reaching more than 2 p above the lowest rate BLOCKs too (fail closed: only a "
      "window within 2 p of the day's lowest rate passes a smooth tariff)", blocked(res_5h), desc(res_5h))

NIGHT = [f"{h:02d}:{m:02d}" for h in range(6) for m in (0, 30) if 30 <= h * 60 + m < 330]
DIP = rates(D14, 4, [], {**{t: 0.085 for t in NIGHT}, "02:00": ph.CHEAP_GBP})   # 8.5 p night, a 30-min 7.5 p dip
DIP10 = rates(D14, 4, [], {**{t: 0.10 for t in NIGHT}, "02:00": ph.CHEAP_GBP})  # the reviewer's 10 p night, same dip
res_dip, res_dip_pk, res_dip10 = at(NOW, DIP, T_0030_0530), at(NOW, DIP, PEAK_T), at(NOW, DIP10, T_0030_0530)
check("a cheap run shorter than 60 min (a 30-min 7.5 p dip in an 8.5 p night: TARIFF_NO_CHEAP_WINDOW) with the TOU "
      "window on that night (00:30-05:30, 1 p above the lowest): the TOU window with WARN, every priced slot within",
      no_run(NOW, DIP) == "TARIFF_NO_CHEAP_WINDOW" and tou_warn(res_dip, WITHIN), desc(res_dip))
check("... the same tariff with the TOU window at the peak: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE", blocked(res_dip_pk),
      desc(res_dip_pk))
check("... a 10 p night with the 30-min dip (2.5 p above the lowest): the night's TOU window BLOCKs (fail closed: a "
      "plunge price elsewhere can BLOCK)", no_run(NOW, DIP10) == "TARIFF_NO_CHEAP_WINDOW" and blocked(res_dip10),
      desc(res_dip10))

LONG = rates(D14, 4, [(0, 780)])                                   # 7.5 p for 13 h (00:00-13:00), 30 p otherwise
FLAT = ph.go_like_rates(D14, 4, cheap=(0, 0), cheap_gbp=0.25, peak_gbp=0.25)
res_long, res_long_pk, res_flat = at(NOW, LONG, INSIDE_T), at(NOW, LONG, PEAK_T), at(NOW, FLAT, PEAK_T)
check("a cheap run longer than 720 min (13 h: TARIFF_CHEAP_RUN_TOO_LONG) with the TOU window inside it: the TOU window "
      "with WARN, every priced slot within the spread", no_run(NOW, LONG) == "TARIFF_CHEAP_RUN_TOO_LONG"
      and tou_warn(res_long, WITHIN), desc(res_long))
check("... the same tariff with the TOU window at the 30 p peak: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE",
      blocked(res_long_pk), desc(res_long_pk))
check("... a flat tariff (TARIFF_CHEAP_RUN_TOO_LONG) passes whatever the window: the TOU window with WARN",
      no_run(NOW, FLAT) == "TARIFF_CHEAP_RUN_TOO_LONG" and tou_warn(res_flat, WITHIN), desc(res_flat))


def edge(low_gbp, slot_gbp):
    """slot_gbp everywhere but a 30-min low_gbp dip at 03:00 (TARIFF_NO_CHEAP_WINDOW)."""
    return rates(D14, 4, [], {**{f"{h:02d}:{m:02d}": slot_gbp for h in range(24) for m in (0, 30)}, "03:00": low_gbp})


EDGE_AT, EDGE_BELOW, EDGE_FP = edge(0.075, 0.095), edge(0.075, 0.094999), edge(0.0603, 0.0803)
res_at, res_below, res_fp = at(NOW, EDGE_AT, PEAK_T), at(NOW, EDGE_BELOW, PEAK_T), at(NOW, EDGE_FP, PEAK_T)
check("the boundary: TOU slots priced exactly the lowest rate plus PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH (7.5 + 2 = 9.5 p) "
      "BLOCK CHARGE_WINDOW_SOURCES_DISAGREE ('at or above')", no_run(NOW, EDGE_AT) == "TARIFF_NO_CHEAP_WINDOW"
      and tf.PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH == 2.0 and blocked(res_at), desc(res_at))
check("... just below it (9.4999 p): the TOU window with WARN, every priced slot within the spread",
      tou_warn(res_below, WITHIN), desc(res_below))
check("... exactly at it where binary rounding falls short (6.03 / 8.03 p, a float difference just under 2): still "
      "BLOCK", (8.03 - 6.03) < 2.0 and blocked(res_fp), desc(res_fp))

PART = [x for x in rates(D15, 2, [(60, 270)]) if x["start"] < "2030-01-16T02:00"]         # priced up to 02:00
PART_DEAR = [x for x in rates(D15, 2, [(60, 270)], {"01:30": ph.PEAK_GBP}) if x["start"] < "2030-01-16T02:00"]
res_part, res_part_dear = at(NOW, PART, INSIDE_T), at(NOW, PART_DEAR, INSIDE_T)
check("a partly priced TOU occurrence (rates to 02:00 of 01:00-04:30, TARIFF_COVERAGE_SHORT) whose priced slots are "
      "cheap: the TOU window with WARN, its text says the tariff does not price the whole TOU window",
      no_run(NOW, PART) == "TARIFF_COVERAGE_SHORT" and tou_warn(res_part, PARTLY) and WITHIN not in desc(res_part),
      desc(res_part))
check("... with one priced slot of it (01:30-02:00) at the 30 p peak: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE (a known "
      "conflicting slot blocks although the occurrence is only partly priced)", blocked(res_part_dear),
      desc(res_part_dear))
PAST = rates(D14, 1, [(60, 270)])                                    # the rates end before now
res_none = at(NOW, PAST, INSIDE_T)
check("no slots ahead (the rates end before now): the TOU window with WARN, the tariff does not price the whole TOU "
      "window", no_run(NOW, PAST) == "TARIFF_COVERAGE_SHORT" and tou_warn(res_none, PARTLY), desc(res_none))

CLIP = rates(D14, 4, [(60, 330)], {"05:30": 0.09})       # 30 p 00:30-01:00, 7.5 p 01:00-05:30, a 9 p shoulder slot
res_clip_before = at(NOW, CLIP, T_0030_0530)
res_clip_in = at(datetime(2030, 1, 16, 0, 45, tzinfo=UTC), CLIP, T_0030_0530)
res_clip_after = at(datetime(2030, 1, 16, 1, 30, tzinfo=UTC), CLIP, T_0030_0530)
check("the occurrence is clipped to [max(now, start), end): a TOU window 00:30-05:30 whose first slot (00:30-01:00) is "
      "at the peak BLOCKs before the window and inside that slot (00:45)", no_run(NOW, CLIP) == "TARIFF_NO_PRICE_SPREAD"
      and blocked(res_clip_before) and blocked(res_clip_in), desc(res_clip_before) + " | " + desc(res_clip_in))
check("... once now (01:30) has passed the dear slot, today's occurrence 01:30-05:30 is all within the spread: the TOU "
      "window (today's 00:30-05:30) with WARN", tou_warn(res_clip_after, WITHIN) and res_clip_after[0] is not None
      and res_clip_after[0].start == datetime(2030, 1, 16, 0, 30, tzinfo=UTC), desc(res_clip_after))

SWEEP = rates(D15, 3, [(30, 330)], {"05:30": 0.09})      # two rates and one shoulder slot; TOU equal to the cheap run
sweep_bad, sweep_runs = [], []
for k in range(96):
    now_k = datetime(2030, 1, 16, 0, 0, tzinfo=UTC) + timedelta(minutes=15 * k)
    res_k = at(now_k, SWEEP, T_0030_0530)
    if no_run(now_k, SWEEP) != "TARIFF_NO_PRICE_SPREAD":
        sweep_runs.append(now_k.strftime("%H:%M"))
    if not tou_warn(res_k, WITHIN) or res_k[0].local_minutes != (30, 330) or not res_k[0].end > now_k:
        sweep_bad.append((now_k.strftime("%H:%M"), desc(res_k)))
check("a two-rate tariff with one shoulder slot (7.5 / 30 p, 9 p at 05:30) and the TOU window equal to its cheap run "
      "(00:30-05:30), every 15 min over 24 h (96 times, in and out of the window): the tariff names no cheap run, and "
      "the result is always the TOU window with WARN, never CHARGE_WINDOW_SOURCES_DISAGREE",
      sweep_runs == [] and sweep_bad == [], str(sweep_runs[:4] + sweep_bad[:3]))

# F2 (documented fail-closed limitation, A35): on the night the cheap rate falls by 2 p or more at local midnight, the
# lowest rate ahead comes from the next night, so tonight's window shows SOURCES_DISAGREE (no number); A38 widens it ([1d])
DROP = [dict(x, value_inc_vat=0.10) if x["value_inc_vat"] == ph.CHEAP_GBP and x["start"] < "2030-01-17" else x
        for x in rates(D14, 5, [(30, 330)])]
res_drop_eve = at(NOW, DROP, T_0030_0530)
res_drop_night = at(datetime(2030, 1, 16, 3, 0, tzinfo=UTC), DROP, T_0030_0530)
check("F2 pinned: tariff and TOU both 00:30-05:30, the cheap rate falling from 10 p to 7.5 p at midnight of the 17th: "
      "at 21:00 on the 15th the window stands; at 03:00 on the 16th, with the next night's 7.5 p in the search period, "
      "it BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE (fail closed, no number; contract 13.5)",
      res_drop_eve[0] is not None and res_drop_eve[0].local_minutes == (30, 330) and blocked(res_drop_night),
      desc(res_drop_eve) + " | " + desc(res_drop_night))

print("== [1d] A38 Part A: the window check's lowest rate also looks back 24 h (N1, N2)")
D16 = date(2030, 1, 16)
TWO = (30, 330)                                          # 7.5 p 00:30-05:30, 30 p otherwise (local = UTC in January)


def half_hours(day, n=48, start=0):
    return [datetime(day.year, day.month, day.day, tzinfo=UTC) + timedelta(minutes=30 * (start + k)) for k in range(n)]


CUR_N1 = rates(D16, 1, [TWO])                            # one day-rates event: the 16th only (the current-day event)
n1_bad = []
for now_k in half_hours(D16):
    res_k = at(now_k, CUR_N1, PEAK_T)
    if now_k < datetime(2030, 1, 16, 19, 0, tzinfo=UTC):
        if not blocked(res_k) or (now_k.hour > 0 and no_run(now_k, CUR_N1) != "TARIFF_COVERAGE_SHORT"):
            n1_bad.append((now_k.strftime("%H:%M"), desc(res_k)))
    elif not (tou_warn(res_k, PARTLY) and res_k[0].start == datetime(2030, 1, 17, 17, 0, tzinfo=UTC)):
        n1_bad.append((now_k.strftime("%H:%M"), desc(res_k)))
check("N1 (A38): the current-day event only (two-rate 7.5 p 00:30-05:30 / 30 p), TOU grid slot misconfigured to the "
      "17:00-19:00 peak: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE at every half-hour from 00:00 until the window ends at "
      "19:00 (A35 alone stood it OK with its WARN from 05:30: the night's cheap slots had passed); from 19:00 the next "
      "occurrence is not priced, so the accepted residual: the TOU window with the WARN 'does not price the whole'",
      n1_bad == [], str(n1_bad[:4]))
N2_ROWS = rates(D16, 1, [], {"05:00": ph.CHEAP_GBP})     # the 16th only: 30 p but one 7.5 p slot 05:00-05:30
res_n2 = at(datetime(2030, 1, 16, 5, 10, tzinfo=UTC), N2_ROWS, PEAK_T)
check("N2: the slot that holds now counts: the current-day event whose only cheap slot (7.5 p, 05:00-05:30) holds now "
      "(05:10), TOU grid slot at the 30 p peak: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE (without that slot the lowest rate "
      "is 30 p and the window would stand)", no_run(datetime(2030, 1, 16, 5, 10, tzinfo=UTC), N2_ROWS)
      == "TARIFF_COVERAGE_SHORT" and blocked(res_n2), desc(res_n2))

FLAT_RISE = [dict(x, value_inc_vat=0.10) if x["start"] >= "2030-01-17" else x     # flat 7.5 p -> 10 p at 00:00 on the 17th
             for x in rates(date(2030, 1, 15), 5, [(0, 1440)])]
rise_bad = []
for now_k in half_hours(date(2030, 1, 17), 60):          # 00:00 on the 17th to 05:30 on the 18th
    res_k = at(now_k, FLAT_RISE, T_0030_0530)
    in_look_back = now_k < datetime(2030, 1, 18, 0, 0, tzinfo=UTC)      # the last 7.5 p slot ends at 00:00 on the 17th
    if no_run(now_k, FLAT_RISE) != "TARIFF_CHEAP_RUN_TOO_LONG" or (blocked(res_k) if in_look_back
                                                                     else tou_warn(res_k, WITHIN)) is False:
        rise_bad.append((now_k.strftime("%d %H:%M"), desc(res_k)))
check("A38 widened F2 (a price rise): a flat 7.5 p tariff rising to 10 p at 00:00 on the 17th, full payload (TARIFF_CHEAP_"
      "RUN_TOO_LONG ahead), TOU 00:30-05:30: BLOCK CHARGE_WINDOW_SOURCES_DISAGREE while the 7.5 p slots are in the "
      "look-back (until 00:00 on the 18th, when the last one is exactly 24 h old), then the TOU window with WARN, every "
      "priced slot within the spread (fail closed, no number; contract 13.5)", rise_bad == [], str(rise_bad[:4]))
TWO_RISE = [dict(x, value_inc_vat=0.10) if x["value_inc_vat"] == ph.CHEAP_GBP and x["start"] >= "2030-01-17" else x
            for x in rates(date(2030, 1, 15), 5, [TWO])]                  # the night rate 7.5 p -> 10 p from the 17th
two_rise_bad = [(t.strftime("%d %H:%M"), desc(at(t, TWO_RISE, T_0030_0530))) for t in half_hours(date(2030, 1, 17), 48)
                if not found(at(t, TWO_RISE, T_0030_0530)[1], "CHARGE_WINDOW_TOU_INSIDE_TARIFF")]
check("... the same rise on a two-rate tariff (night 7.5 -> 10 p, 30 p peak) names a cheap run every half-hour of the "
      "17th, so A30's band decides and the look-back plays no part: always INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF",
      two_rise_bad == [], str(two_rise_bad[:4]))

AGREE_T = (("00:30-05:30", T_0030_0530, (30, 330)), ("01:00-04:30", INSIDE_T, (60, 270)))
PAYLOADS = {"full": lambda d: rates(d - timedelta(days=1), 4, [TWO]), "current-day": lambda d: rates(d, 1, [TWO]),
            "next-day": lambda d: rates(d + timedelta(days=1), 1, [TWO]),
            "full + shoulder": lambda d: rates(d - timedelta(days=1), 4, [TWO], {"05:30": 0.09})}
agree_bad, agree_warn = [], 0
for pname, make in PAYLOADS.items():
    rows_p = make(D16)
    for label, table, minutes in AGREE_T:
        for now_k in half_hours(D16):
            cw_k, n_k = at(now_k, rows_p, table)
            if cw_k is None or cw_k.local_minutes != minutes or found(n_k, "CHARGE_WINDOW_SOURCES_DISAGREE"):
                agree_bad.append((pname, label, now_k.strftime("%H:%M"), desc((cw_k, n_k))))
            agree_warn += found(n_k, "CHARGE_WINDOW_FROM_TOU_TABLE", "WARN")
check("A38: windows that agree with the tariff (TOU 00:30-05:30 and 01:00-04:30 on the two-rate tariff, also with a 9 p "
      "shoulder slot) on full, current-day and next-day payloads, every half-hour of the 16th (384 times): always the "
      "TOU window, never CHARGE_WINDOW_SOURCES_DISAGREE (only `low` looks back; the slots checked are the clipped "
      "occurrence's), with the WARN wherever no run is named", agree_bad == [] and agree_warn > 150,
      f"{agree_bad[:4]} warn={agree_warn}")

NEXT_N1 = rates(D16 + timedelta(days=1), 1, [TWO])        # the next-day event only: the 17th
res_unpriced = at(datetime(2030, 1, 16, 12, 0, tzinfo=UTC), NEXT_N1, PEAK_T)
res_next_priced = at(datetime(2030, 1, 16, 19, 0, tzinfo=UTC), NEXT_N1, PEAK_T)
check("A38 accepted residual: a TOU occurrence the payload does not price at all (the next-day event at 12:00, today's "
      "17:00-19:00 occurrence before its first slot) has nothing to conflict with: the TOU window with WARN 'does not "
      "price the whole' (visible); once the occurrence is tomorrow's (19:00) it is priced and BLOCKs",
      tou_warn(res_unpriced, PARTLY) and res_unpriced[0].start == datetime(2030, 1, 16, 17, 0, tzinfo=UTC)
      and blocked(res_next_priced), desc(res_unpriced) + " | " + desc(res_next_priced))

print("== [1e] A41: INFO CHARGE_WINDOW_NOT_PRICED on a window that no price check covered whole (R7-E3)")
NP = dp.CHARGE_WINDOW_NOT_PRICED


def not_priced(res) -> list:
    """The (code, severity) pairs of CHARGE_WINDOW_NOT_PRICED in one choose_charge_window result."""
    return [(f.code, f.severity) for f in res[1] if f.code == NP]


def within(res) -> bool:
    return any(f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" and WITHIN in f.text for f in res[1])


check("the code is a constant within MAX_CODE_CHARS; its text is value-free (no digit) and names no case",
      NP == "CHARGE_WINDOW_NOT_PRICED" and len(NP) <= ac.MAX_CODE_CHARS
      and not any(ch.isdigit() for ch in dp.CHARGE_WINDOW_NOT_PRICED_TEXT), dp.CHARGE_WINDOW_NOT_PRICED_TEXT)
stale_imp = tf.assess_rates(InputState("tariff.import_rates", ph.rates_payload(NOW), False, 7200.0, 300.0), NOW)
# ENG9-1: the whole-occurrence boundary. Rows 00:00-04:00 (all cheap) price 3 h of the 3.5 h occurrence 01:00-04:30
# clipped at 00:30 (more than half, not all); rows from 02:00 (a payload that starts after the window's start, short of
# the search period, so no named run) price the occurrence clipped at 02:10 whole.
RATES_0004 = [r for r in rates(D16, 1, [(0, 1440)]) if r["start"] < "2030-01-16T04:00"]
RATES_FROM_02 = [r for r in rates(D16, 1, [TWO]) if "2030-01-16T02:00" <= r["start"] < "2030-01-16T12:00"]
MORE_THAN_HALF = "rates 00:00-04:00 at 00:30: more than half of the clipped occurrence 01:00-04:30 priced, not all"
FROM_02 = "rates from 02:00 at 02:10, now inside the window 01:00-04:30: the clipped occurrence priced whole"
RATES_FROM_0030 = [r for r in rates(D16, 1, [TWO]) if "2030-01-16T00:30" <= r["start"] < "2030-01-16T12:00"]
FROM_0030 = "rates from 00:30 at 00:10, now before the window 01:00-04:30: the occurrence priced whole from its start"
UNCHECKED = {"no verified tariff (NO_VALUE)": (cw2, n2), "no tariff at all": choose(None, None, tou(SLOT)),
             "a stale import tariff (NOT_VERIFIED)": choose(stale_imp, imp_state, tou(SLOT)),
             "the next-day event at 12:00, today's occurrence not priced (the A38 residual)": res_unpriced,
             "the current-day event at 19:30, tomorrow's occurrence not priced (the N1 residual)":
                 at(datetime(2030, 1, 16, 19, 30, tzinfo=UTC), CUR_N1, PEAK_T),
             "rates to 02:00 tomorrow, the occurrence 01:00-04:30 priced cheap in part":
                 at(NOW, [r for r in rates(D15, 2, [TWO]) if r["start"] < "2030-01-16T02:00"], INSIDE_T),
             "rates that end before now (no slot ahead)": at(NOW, rates(D14, 1, [TWO]), INSIDE_T),
             MORE_THAN_HALF: at(datetime(2030, 1, 16, 0, 30, tzinfo=UTC), RATES_0004, INSIDE_T)}
np_bad = [(k, desc(r)) for k, r in UNCHECKED.items()
          if r[0] is None or r[0].source != dp.SOURCE_TOU_TABLE or not_priced(r) != [(NP, "INFO")] or within(r)]
check("A41: the window stands on the TOU table without a whole-occurrence price check (no usable verified tariff for the "
      "window check, or one that does not price the whole occurrence): exactly one INFO CHARGE_WINDOW_NOT_PRICED beside "
      "the WARN, the window unchanged", np_bad == [], str(np_bad[:3]))
CHECKED = {"a named run holds the window (INFO CHARGE_WINDOW_TOU_INSIDE_TARIFF)": (cw, notes),
           "a named run holds the narrow TOU slot": (mis_cw, mis_n),
           "a two-rate night-rate rise (always INSIDE)": at(datetime(2030, 1, 17, 12, 0, tzinfo=UTC), TWO_RISE, T_0030_0530),
           "a flat tariff that prices the whole occurrence (within the spread)": (fl_cw, fl_n),
           "a flat 10 p after the rise has left the look-back (within the spread)":
               at(datetime(2030, 1, 18, 1, 0, tzinfo=UTC), FLAT_RISE, T_0030_0530),
           FROM_02: at(datetime(2030, 1, 16, 2, 10, tzinfo=UTC), RATES_FROM_02, INSIDE_T),
           FROM_0030: at(datetime(2030, 1, 16, 0, 10, tzinfo=UTC), RATES_FROM_0030, INSIDE_T)}
np_absent = [(k, desc(r)) for k, r in CHECKED.items() if r[0] is None or not_priced(r)]
check("A41: absent when the whole occurrence was priced and found within the spread, and beside a named-run INSIDE "
      "result", np_absent == [] and within(CHECKED["a flat tariff that prices the whole occurrence (within the spread)"])
      and found(notes, "CHARGE_WINDOW_TOU_INSIDE_TARIFF", "INFO"), str(np_absent[:3]))
check("ENG9-1: a verified table that prices more than half but not all of the clipped occurrence (rows 00:00-04:00, "
      "the TOU run 01:00-04:30, now 00:30; no named run): the TOU window with exactly one INFO "
      "CHARGE_WINDOW_NOT_PRICED and the WARN text 'does not price the whole TOU window', never the 'within the "
      "spread' text (a half-coverage test would call it checked)",
      not_priced(UNCHECKED[MORE_THAN_HALF]) == [(NP, "INFO")] and tou_warn(UNCHECKED[MORE_THAN_HALF], PARTLY)
      and not within(UNCHECKED[MORE_THAN_HALF]), desc(UNCHECKED[MORE_THAN_HALF]))
check("ENG9-1: a verified table whose first slot starts after the TOU window's start but at or before now, now inside "
      "the window (rows from 02:00, now 02:10, the run 01:00-04:30; no named run): the occurrence clipped at now is "
      "priced whole, so no CHARGE_WINDOW_NOT_PRICED and the WARN text 'within the minimum cheap spread' (the "
      "unclipped occurrence would count the 01:00-02:00 hour before now as unpriced)",
      not_priced(CHECKED[FROM_02]) == [] and tou_warn(CHECKED[FROM_02], WITHIN), desc(CHECKED[FROM_02]))
check("ENG9-1: ... and one whose first slot starts after now but before the window's start, now before the window (rows "
      "from 00:30, now 00:10, the run 01:00-04:30; no named run): the occurrence is priced whole from its start, so no "
      "CHARGE_WINDOW_NOT_PRICED and the WARN text 'within the minimum cheap spread' (the time before the window is no "
      "part of it)",
      not_priced(CHECKED[FROM_0030]) == [] and tou_warn(CHECKED[FROM_0030], WITHIN), desc(CHECKED[FROM_0030]))
REFUSED = {"SOURCES_DISAGREE without a named run (N2)": res_n2, "SOURCES_DISAGREE on tomorrow's priced occurrence":
           res_next_priced, "SOURCES_DISAGREE with a named run": (par_cw, par_n), "a stale table": (st_cw, st_n),
           "neither source": (cw3, n3), "a v1 table": (cw_v1, n_v1)}
np_refused = [(k, desc(r)) for k, r in REFUSED.items() if r[0] is not None or not_priced(r)]
check("A41: never on a refused window (no window, no CHARGE_WINDOW_NOT_PRICED)", np_refused == [], str(np_refused[:3]))
np_sweep, np_seen = [], {"present": 0, "within": 0, "inside": 0, "refused": 0}
for pname, make in dict(PAYLOADS, **{"none": lambda d: None}).items():
    rows_p = make(D16)
    for label, table in (("00:30-05:30", T_0030_0530), ("01:00-04:30", INSIDE_T), ("17:00-19:00", PEAK_T)):
        for now_k in half_hours(D16):
            res_k = at(now_k, rows_p, table, verified=rows_p is not None)
            want = res_k[0] is not None and res_k[0].source == dp.SOURCE_TOU_TABLE and not within(res_k)
            np_seen["present" if want else "refused" if res_k[0] is None else "within" if within(res_k) else "inside"] += 1
            if not_priced(res_k) != ([(NP, "INFO")] if want else []):
                np_sweep.append((pname, label, now_k.strftime("%H:%M"), desc(res_k)))
check("A41 sweep (full, current-day, next-day, shoulder and no tariff x three TOU windows x every half-hour of the 16th): "
      "CHARGE_WINDOW_NOT_PRICED exactly when the window stands on the TOU table and no check priced its whole occurrence "
      "within the spread; each case met", np_sweep == [] and all(v > 0 for v in np_seen.values()),
      f"{np_sweep[:3]} {np_seen}")

wrong = sorted({(f.code, f.severity) for f in SEEN + notes + n2 + mis_n + par_n + far_n + st_n + fl_n
                if (f.code in BLOCK_CODES_13_8 and f.severity != "BLOCK")
                or (f.code in ("CHARGE_WINDOW_TOU_INSIDE_TARIFF", NP) and f.severity != "INFO")
                or (f.code == "CHARGE_WINDOW_FROM_TOU_TABLE" and f.severity != "WARN")})
check("no CHARGE_WINDOW_* code of contract 13.8 is ever emitted with another severity (the tariff path emits no "
      "CHARGE_WINDOW_CROSSES_MIDNIGHT / CHARGE_WINDOW_NOT_REPRESENTABLE WARN any more; A35 adds only the BLOCK "
      "CHARGE_WINDOW_SOURCES_DISAGREE and the WARN CHARGE_WINDOW_FROM_TOU_TABLE; A41 the INFO CHARGE_WINDOW_NOT_PRICED)",
      wrong == [] and len(SEEN) > 300 and any(f.code == NP for f in SEEN)
      and any(f.code == "CHARGE_WINDOW_SOURCES_DISAGREE" and "names no cheap run" in f.text for f in SEEN), str(wrong))

print("== [2] property sweep (seeded)")
WINDOW = (datetime(2030, 1, 16, 1, 0, tzinfo=UTC), datetime(2030, 1, 16, 4, 30, tzinfo=UTC))
CW = dp.ChargeWindow(dp.SOURCE_TOU_TABLE, WINDOW[0], WINDOW[1], (60, 270), InputState(sd.CHARGE_WINDOW_KEY, (60, 270), True, 20.0, 300.0))
HORIZON = datetime(2030, 1, 17, 1, 0, tzinfo=UTC)
bad, n_ok, n_cases = [], 0, 0
for i in range(600):
    rnd = random.Random(5000 + i)
    user = rnd.uniform(0, 60)
    tech = rnd.uniform(0, 30)
    margin = rnd.choice([0.0, 2.5, 5.0, 10.0])
    if max(user, tech) + margin > 100:
        continue
    try:
        cfg = SiteConfig(battery_capacity_kwh=rnd.uniform(3, 40), round_trip_efficiency=rnd.uniform(0.75, 0.98),
                         user_reserve_soc_pct=user, technical_min_soc_pct=tech, soc_safety_margin_pct=margin,
                         max_grid_charge_kw=rnd.uniform(0.5, 10), cheap_window_start_min=60, cheap_window_end_min=270)
    except ValueError:
        continue
    n_cases += 1
    ha = rnd.choice([None, rnd.uniform(0, 100)])
    mean = rnd.uniform(1, 40)
    nights = [NightObservation(date(2030, 1, 15) - timedelta(days=k), max(0.0, rnd.gauss(mean, mean * 0.2))) for k in range(1, 29)]
    demand = learn_overnight(nights, date(2030, 1, 16), OvernightSettings.from_site(cfg))
    target = advise_charge_target(cfg, ChargeTargetInputs(
        now=NOW, window=WINDOW, demand=demand, soc_pct=rnd.uniform(0, 100), soc_age_s=20.0, ha_reserve_pct=ha,
        pv_credit_kwh=rnd.choice([None, rnd.uniform(0, 30)]), pv_credit_label=rnd.choice([None, "LOW", "MEDIUM", "HIGH"]),
        window_load_kwh=rnd.uniform(0, 4), soc_at_window_start_pct=rnd.choice([None, rnd.uniform(0, 100)])))
    prof = [rnd.uniform(0.05, 3.0) for _ in range(24)]
    shape = [max(0.0, rnd.random() - 0.5) if 7 <= h <= 17 else 0.0 for h in range(24)]
    s = sum(shape) or 1.0
    shape = [x / s for x in shape]
    pv50 = rnd.uniform(0, 40)
    lb = dp.Band(mean * 0.8, mean, mean * rnd.uniform(1.0, 1.6), "MEDIUM")
    view = dp.hourly_view(prof, {date(2030, 1, 16): (pv50, shape), date(2030, 1, 15): (pv50, shape)}, Z, lb,
                          (pv50 * 0.6, pv50, pv50 * 1.3) if pv50 > 0 else None)
    mb = rnd.choice([None, dp.Band(1.0, 2.0, rnd.uniform(2.0, 5.0), "LOW")])
    plan = dp.build_plan(cfg=cfg, now=NOW, tz=Z, window=CW, horizon_end=HORIZON, target=target, ha_reserve_pct=ha,
                         soc_pct=rnd.uniform(0, 100), view=view, wear_cost_p_per_kwh=rnd.choice([None, 2.0]), morning_band=mb)
    floor = cfg.effective_reserve(ha).effective_pct
    fm = floor + cfg.soc_safety_margin_pct
    ceil_direct = dp.headroom_ceiling(cfg, fm, WINDOW[1], HORIZON, view, reserve_pct=floor)
    if ceil_direct < fm - 1e-9 or ceil_direct < floor:
        bad.append((i, "ceiling below the reserve", ceil_direct, fm))
    if target.status != "OK" and plan.status == dp.PLAN_OK:
        bad.append((i, "plan without an OK target"))
    if plan.status == dp.PLAN_OK:
        n_ok += 1
        if plan.planned_soc_pct < fm - 1e-9:
            bad.append((i, "planned below reserve + margin", plan.planned_soc_pct, fm))
        if plan.headroom_ceiling_pct is None or plan.headroom_ceiling_pct < fm - 1e-9:
            bad.append((i, "headroom below reserve + margin", plan.headroom_ceiling_pct, fm))
        m = plan.morning_soc
        if m is None or not (0.0 <= m[0] <= m[1] <= m[2] <= cfg.max_soc_pct):
            bad.append((i, "morning band", m))
        elif m[0] < floor - dp.MORNING_ROUNDING_PCT - 1e-9:                 # published to 0.1 point
            bad.append((i, "morning SOC below the effective reserve (the plan holds it)", m, floor))
        elif (m[0] <= floor + dp.MORNING_ROUNDING_PCT) != any(f.code == "MORNING_SOC_AT_RESERVE" for f in plan.findings):
            bad.append((i, "MORNING_SOC_AT_RESERVE does not match the band", m, floor))
        if plan.reserve_runout_at is not None and not (NOW <= plan.reserve_runout_at <= HORIZON):
            bad.append((i, "runout outside the horizon", plan.reserve_runout_at))
        if set(plan.plan_block()) != {"precharge_by", "headroom_ceiling_pct", "reserve_runout_at"}:
            bad.append((i, "plan block keys"))
    elif any(f.code == "PLAN_BELOW_RESERVE_MARGIN" for f in plan.findings) and plan.planned_soc_pct is not None:
        bad.append((i, "a refused plan carries a planned SOC"))
check(f"{n_cases} seeded cases (>= 500): no plan below the effective reserve + margin, no headroom ceiling below the reserve, "
      "ordered morning bands never below the effective reserve, no plan without an OK target", n_cases >= 500 and not bad,
      str(bad[:3]))
check(f"... the sweep reached both outcomes ({n_ok} OK plans)", 0 < n_ok < n_cases)
try:
    dp.DailyPlan(dp.PLAN_OK, (), planned_soc_pct=20.0, effective_reserve_pct=30.0, margin_pct=5.0)
    refused = False
except ValueError:
    refused = True
check("an OK DailyPlan below the reserve + margin cannot even be built", refused)

print("== [3] every output BLOCKED when a gating decision is not satisfied")
WP1_TOU_KEYS = ("tou.enabled", "tou.grid_charge_enabled", "tou.overlay_state")
check("the WP-1 outputs the cycle reads are the real ones (no in-process simulation): the three TOU readings are I-D6 keys "
      "and the quality layer judges the configuration-poll liveness",
      all(k in sd.FRESHNESS_OVERRIDE_KEYS for k in WP1_TOU_KEYS)
      and sd.CONFIG_LIVENESS_KEY in q.assess_inputs(cf.cycle_inputs(synthetic_recorded=True)).ages
      and sc.freshness_limits is sd.freshness_limits and sc.assess_inputs is q.assess_inputs)
base = ph.verified_inputs(synthetic_recorded=True)
full = run_cycle(base)
check("the verified, decided case is complete (charge target, plan, value, morning SOC)", full.item("charge_target").status == "OK"
      and full.plan is not None and full.value is not None and full.item("predicted_morning_soc").status == "OK")
fails = []
for did in sd.DECISION_IDS:
    if did == "D7":
        continue
    e = run_cycle(ph.verified_inputs(decisions=cf.synthetic_decisions().without(did), accept_provenance=cf.SYNTHETIC_ACCEPT))
    for item, gates in sd.ITEM_GATES.items():
        if item == "v1_summary" or did not in gates:
            continue
        if e.item(item).status != "BLOCKED":
            fails.append((did, item, e.item(item).status))
    if did in sd.ITEM_GATES["charge_target"] and (e.plan is not None or e.value is not None or e.engine_comparison is not None
                                                  or e.tariff["price_range"] is not None):
        fails.append((did, "plan/value/comparison/price published"))
for seed in range(8):
    rnd = random.Random(900 + seed)
    drop = rnd.sample([d for d in sd.DECISION_IDS if d != "D7"], rnd.randint(1, 4))
    ds = cf.synthetic_decisions()
    for d in drop:
        ds = ds.without(d)
    e = run_cycle(ph.verified_inputs(decisions=ds, accept_provenance=cf.SYNTHETIC_ACCEPT))
    for item, gates in sd.ITEM_GATES.items():
        if item != "v1_summary" and set(gates) & set(drop) and e.item(item).status != "BLOCKED":
            fails.append((tuple(drop), item, e.item(item).status))
check("each gating decision removed (and 8 seeded combinations): every item it gates BLOCKED, and without a charge "
      "target no plan, value, comparison or price", fails == [], str(fails[:4]))

print("== [4] cycling cost and precharge timing")
cfg = SiteConfig(battery_capacity_kwh=20.0, round_trip_efficiency=0.92, user_reserve_soc_pct=30.0, technical_min_soc_pct=12.0,
                 max_grid_charge_kw=5.0, cheap_window_start_min=60, cheap_window_end_min=270)
nights = [NightObservation(date(2030, 1, 15) - timedelta(days=k), 8.0 + 0.1 * (k % 5)) for k in range(1, 29)]
tgt = advise_charge_target(cfg, ChargeTargetInputs(now=NOW, window=WINDOW, demand=learn_overnight(nights, date(2030, 1, 16), OvernightSettings.from_site(cfg)),
                                                   soc_pct=50.0, soc_age_s=20.0, soc_at_window_start_pct=40.0))
v = dp.hourly_view([0.5] * 24, {}, Z, None, None)
p_no = dp.build_plan(cfg=cfg, now=NOW, tz=Z, window=CW, horizon_end=HORIZON, target=tgt, ha_reserve_pct=None, soc_pct=50.0, view=v)
p_yes = dp.build_plan(cfg=cfg, now=NOW, tz=Z, window=CW, horizon_end=HORIZON, target=tgt, ha_reserve_pct=None, soc_pct=50.0, view=v,
                      wear_cost_p_per_kwh=2.0)
check("no wear-cost preference: no cycling cost", p_no.status == "OK" and p_no.cycling_cost_p is None)
check("with it: the preference times the grid charge energy", p_yes.cycling_cost_p == round(2.0 * tgt.recommendation["grid_charge_kwh"], 2),
      str((p_yes.cycling_cost_p, tgt.recommendation["grid_charge_kwh"])))
check("an invalid preference gives no cost", dp.build_plan(cfg=cfg, now=NOW, tz=Z, window=CW, horizon_end=HORIZON, target=tgt,
                                                           ha_reserve_pct=None, soc_pct=50.0, view=v,
                                                           wear_cost_p_per_kwh=float("nan")).cycling_cost_p is None)
traj = [{"t": "2030-01-15T22:00:00+00:00", "soc_median": 40.0, "soc_low": 33.0, "soc_high": 45.0},
        {"t": "2030-01-15T23:00:00+00:00", "soc_median": 34.0, "soc_low": 29.0, "soc_high": 40.0},
        {"t": "2030-01-16T00:00:00+00:00", "soc_median": 29.0, "soc_low": 25.0, "soc_high": 36.0}]
pre, _pn = dp.precharge_from_v1({"reasons": [{"code": "PRE_WINDOW_RISK"}], "trajectory": traj}, 30.0, WINDOW[0])
check("PRE_WINDOW_RISK: the first pessimistic point at or below the reserve before the window", pre == datetime(2030, 1, 15, 23, 0, tzinfo=UTC), str(pre))
pre2, _ = dp.precharge_from_v1({"reasons": [{"code": "PRE_WINDOW_FLOOR"}], "trajectory": traj}, 30.0, WINDOW[0])
check("PRE_WINDOW_FLOOR: the first median point below it", pre2 == datetime(2030, 1, 16, 0, 0, tzinfo=UTC), str(pre2))
check("no PRE_WINDOW reason: no precharge time", dp.precharge_from_v1({"reasons": [{"code": "TARGET"}], "trajectory": traj}, 30.0, WINDOW[0])[0] is None)
check("no V1 run on the decided configuration: not assessed", dp.precharge_from_v1(None, 30.0, WINDOW[0])[1][0].code == "PRECHARGE_NOT_ASSESSED")

print("== [5] Saving Session plan and the morning anchor")
band = dp.Band(1.0, 1.5, 2.0, "MEDIUM")
ss = dp.session_advice(cfg, now=NOW, start=NOW + timedelta(hours=20), end=NOW + timedelta(hours=21), soc_pct=80.0, soc_age_s=20.0,
                       inverter_ok=True, ha_reserve_pct=None, before=band, during=band, after=band)
check("a Saving Session plan on planning (p90) demand: OK, energy only", ss.status == "OK" and ss.kind == "export_event"
      and ss.recommendation["household_during_kwh"] == 2.0, str(ss.recommendation.get("household_during_kwh")))
ss2 = dp.session_advice(cfg, now=NOW, start=NOW + timedelta(hours=20), end=NOW + timedelta(hours=21), soc_pct=80.0, soc_age_s=5000.0,
                        inverter_ok=True, ha_reserve_pct=None, before=band, during=band, after=band)
check("... a stale SOC blocks it", ss2.status == "BLOCKED")
check("the morning anchor is 09:00 local after the window end", dp.morning_anchor(WINDOW[1], Z) == datetime(2030, 1, 16, 9, 0, tzinfo=UTC)
      and dp.morning_anchor(datetime(2030, 1, 16, 10, 0, tzinfo=UTC), Z) == datetime(2030, 1, 17, 9, 0, tzinfo=UTC))
check("in summer it is 09:00 BST (08:00 UTC)", dp.morning_anchor(datetime(2030, 7, 2, 3, 30, tzinfo=UTC), Z) == datetime(2030, 7, 2, 8, 0, tzinfo=UTC))
CWE = dp.ChargeWindow(dp.SOURCE_TOU_TABLE, WINDOW[0], WINDOW[1], (60, 270), InputState(sd.CHARGE_WINDOW_KEY, (60, 270), True, 20.0, 300.0))
for label, start, want in (("tonight, before the window", datetime(2030, 1, 15, 22, 0, tzinfo=UTC), (dp.EVENT_FROM_NOW, None)),
                           ("tomorrow 17:00, after the refill", datetime(2030, 1, 16, 17, 0, tzinfo=UTC), (dp.EVENT_AFTER_WINDOW, WINDOW[1])),
                           ("inside the window", datetime(2030, 1, 16, 2, 0, tzinfo=UTC), (dp.EVENT_NOT_MODELLED, None)),
                           ("after two refills", datetime(2030, 1, 17, 17, 0, tzinfo=UTC), (dp.EVENT_NOT_MODELLED, None))):
    check(f"event_start_basis: an event {label} -> {want[0]}", dp.event_start_basis(NOW, start, CWE, Z) == want,
          str(dp.event_start_basis(NOW, start, CWE, Z)))
check("held_soc_after: a drain is carried down to the reserve, never below it, and never raises a battery already below it",
      dp.held_soc_after(cfg, 50.0, 100.0, 30.0) == 30.0 and dp.held_soc_after(cfg, 20.0, 5.0, 30.0) == 20.0
      and abs(dp.held_soc_after(cfg, 80.0, 2.0, 30.0) - (80.0 - 2.0 / (0.92 ** 0.5) / 20.0 * 100.0)) < 1e-9)
hcfg = SiteConfig(battery_capacity_kwh=10.0, round_trip_efficiency=1.0, user_reserve_soc_pct=40.0, technical_min_soc_pct=10.0,
                  soc_safety_margin_pct=5.0, max_grid_charge_kw=5.0, cheap_window_start_min=60, cheap_window_end_min=270)
h0 = datetime(2030, 6, 1, 4, 30, tzinfo=UTC)
hload = lambda h: 1.0 if h < h0 + timedelta(hours=6) else 0.0  # noqa: E731 - 6 kWh night drain first
hpv = lambda h: 0.0 if h < h0 + timedelta(hours=6) else 1.0    # noqa: E731 - then 8 kWh of PV surplus
hv = dp.HourlyView(hload, hpv)
hc = dp.headroom_ceiling(hcfg, 45.0, h0, h0 + timedelta(hours=14), hv, reserve_pct=40.0)
check("headroom ceiling on the reserve-held account: when the drain reaches the reserve before the PV surplus, clipping "
      "cannot be avoided, so the ceiling is the reserve plus margin (the unconstrained path said 90)", hc == 45.0, str(hc))
hv2 = dp.HourlyView(lambda h: 0.2, lambda h: 1.0 if 10 <= h.hour < 13 else 0.0)
hc2 = dp.headroom_ceiling(hcfg, 45.0, h0, h0 + timedelta(hours=14), hv2, reserve_pct=40.0)
o2 = bl_replay(hcfg, 40.0, None, hc2 - 0.2, h0, h0 + timedelta(hours=14), None, hv2.load, hv2.pv)
o3 = bl_replay(hcfg, 40.0, None, min(100.0, hc2 + 1.0), h0, h0 + timedelta(hours=14), None, hv2.load, hv2.pv)
check("... with room left: just below the ceiling the held replay clips no PV, a point above it does",
      45.0 < hc2 < 100.0 and o2.export_kwh <= 1e-6 and o3.export_kwh > 1e-6, str((hc2, o2.export_kwh, o3.export_kwh)))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all daily-plan checks passed")
