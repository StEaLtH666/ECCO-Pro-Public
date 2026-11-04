#!/usr/bin/env python3
"""Planning stream: the tariff adapter (intelligence/tariff.py). SYNTHETIC fixtures only (fictional 2030 prices).

  [1] well-formed integration-shaped payloads (a row list, one event's attributes, the merged events) parse and verify
  [2] missing, stale, unresolved-age, gappy, overlapping, unit-mismatched, foreign-shaped, timezone-naive or future-dated
      payloads give BLOCK / NO_VALUE, never a price
  [3] DST: a 25 h and a 23 h local day are covered by 50 / 46 half-hours, not by 48
  [4] the cheap window, coverage and price range; the cheap band's ceiling (A30): a run in progress starts at the slot
      that holds `now` and a run is cut at the search horizon, so a caller checks slots against the ceiling instead;
      the window check's lowest rate (A35 / A38, horizon_low_p_per_kwh): only slots overlapping [now - 24 h,
      now + 24 h), whatever slots exist there, the slot that holds `now` included (N2), both ends exact and a slot that
      straddles either end counted (R7-E1); the cheap run and its band never look back
  [5] events: Saving Session / free-electricity periods; malformed ones refused
  [6] in the cycle: VERIFIED_FROM_INTEGRATION checks the TOU window (a named run); prices only with an OK charge target;
      all OPEN -> no number
  [7] fixtures: fictional 2030, text only, no 13-digit number on a meter / mpan / octopus / parameters line
  [8] the adapter's words: each way cheap_window names no run gives its own WARN, and neither those texts nor any
      comment or docstring of tariff.py calls the cheap run a charge window (the TOU table is the only window source)
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _cycle_fixtures as cf  # noqa: E402
import _plan_helpers as ph  # noqa: E402
from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import tariff as tf  # noqa: E402
from intelligence.shadow_cycle import run_cycle  # noqa: E402
from intelligence.site_decisions import InputState  # noqa: E402
from intelligence.timeutil import zone  # noqa: E402

FAILURES: list[str] = []
UTC = timezone.utc
NOW = datetime(2030, 1, 15, 21, 0, tzinfo=UTC)
Z = zone("Europe/London")


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def fixture(name: str):
    return json.loads((ph.FIXTURES / name).read_text(encoding="utf-8"))["payload"]


def state(value, fresh=True, age=120.0, limit=300.0, key="tariff.import_rates"):
    return InputState(key, value, fresh, age, limit)


def judged(value, **kw):
    return tf.assess_rates(state(value, **{k: v for k, v in kw.items() if k in ("fresh", "age", "limit")}), NOW,
                           **{k: v for k, v in kw.items() if k in ("observed_at", "need", "kind")})


def no_price(r: tf.TariffResult) -> bool:
    return (not r.verified and r.slots == () and r.rate_at(NOW + timedelta(hours=5)) is None
            and r.price_range(NOW, NOW + timedelta(hours=1)) is None)


print("== [1] well-formed payloads")
go = fixture("import_rates_go_like_2030-01-15.json")
r = judged(go)
check("the merged rate events verify (VERIFIED_FROM_INTEGRATION)", r.verified and r.status == tf.VERIFIED_FROM_INTEGRATION
      and r.provenance == "VERIFIED_FROM_INTEGRATION", r.status)
check("... 96 contiguous half-hours over two local days", len(r.slots) == 96
      and all(a.end == b.start for a, b in zip(r.slots, r.slots[1:])))
check("... GBP/kWh x 100 = p/kWh (0.075 -> 7.5, 0.30 -> 30)",
      r.rate_at(datetime(2030, 1, 16, 2, 0, tzinfo=UTC)) == 7.5 and r.rate_at(datetime(2030, 1, 16, 12, 0, tzinfo=UTC)) == 30.0)
check("... the fixture is exactly what the helper builds (pinned)", go == {"current_day": {"rates": ph.go_like_rates(date(2030, 1, 15), 1)},
                                                                           "next_day": {"rates": ph.go_like_rates(date(2030, 1, 16), 1)}})
flat = go["current_day"]["rates"] + go["next_day"]["rates"]
check("a plain row list verifies the same", judged(flat).slots == r.slots)
check("one event's attributes {rates, unit_of_measurement: GBP/kWh} verify the same",
      judged({"rates": flat, "unit_of_measurement": "GBP/kWh"}).slots == r.slots)
check("rows out of order are sorted", judged(list(reversed(flat))).slots == r.slots)
check("negative rates (a plunge) are kept as stated", judged([dict(x, value_inc_vat=-0.05) for x in flat]).rate_at(NOW) == -5.0)

print("== [2] fail closed: never a price")
cases = {
    "missing reading (None state)": tf.assess_rates(None, NOW),
    "missing value": judged(None),
    "stale reading": judged(go, fresh=False, age=7200.0),
    "unresolved freshness limit": judged(go, limit=None),
    "gappy": judged(fixture("import_rates_gappy_2030-01-15.json")),
    "overlapping (a repeated slot)": judged(flat + flat[:1]),
    "unit-mismatched (p/kWh values)": judged(fixture("import_rates_unit_mismatch_2030-01-15.json")),
    "a stated unit that is not GBP/kWh": judged({"rates": flat, "unit_of_measurement": "p/kWh"}),
    "foreign shape (p_per_kwh rows, as the shared fixture)": judged([{"start": "2030-01-16T01:00:00+00:00",
                                                                      "end": "2030-01-16T04:30:00+00:00", "p_per_kwh": 7.5}]),
    "timezone-naive": judged(fixture("import_rates_naive_2030-01-15.json")),
    "future-dated observation": judged(go, observed_at=NOW + timedelta(hours=2)),
    "empty list": judged([]),
    "not a list or mapping": judged("7.5"),
    "a non-finite rate": judged([dict(flat[0], value_inc_vat=float("nan"))]),
    "an inverted slot": judged([dict(flat[0], end=flat[0]["start"])]),
    "unknown top-level keys": judged({"tomorrow": flat}),
}
for name, res in cases.items():
    check(f"{name}: {res.status} with no price", res.status in (tf.BLOCK, tf.NO_VALUE) and no_price(res)
          and res.findings and res.findings[0].severity in ("BLOCK", "WARN"), f"{res.status} {[f.code for f in res.findings]}")
codes = {k: v.findings[0].code for k, v in cases.items()}
check("the reasons are specific", codes["gappy"] == "TARIFF_GAP" and codes["unit-mismatched (p/kWh values)"] == "TARIFF_UNIT_MISMATCH"
      and codes["timezone-naive"] == "TARIFF_TIMEZONE_NAIVE" and codes["future-dated observation"] == "TARIFF_FUTURE_DATED"
      and codes["stale reading"] == "TARIFF_NOT_FRESH" and codes["missing reading (None state)"] == "TARIFF_MISSING"
      and codes["foreign shape (p_per_kwh rows, as the shared fixture)"] == "TARIFF_SHAPE_NOT_INTEGRATION"
      and codes["overlapping (a repeated slot)"] == "TARIFF_OVERLAP", str(codes))
check("missing / stale is NO_VALUE; malformed is BLOCK",
      cases["missing value"].status == tf.NO_VALUE and cases["stale reading"].status == tf.NO_VALUE
      and cases["gappy"].status == tf.BLOCK and cases["timezone-naive"].status == tf.BLOCK)
raised = []
for junk in (object(), {"rates": object()}, [None], [[1, 2]], {"current_day": "x"}, b"\x00", 10 ** 15, float("inf")):
    try:
        res = judged(junk)
        if res.verified:
            raised.append(("verified", repr(junk)[:20]))
    except Exception as exc:  # noqa: BLE001 - the invariant under test
        raised.append((type(exc).__name__, repr(junk)[:20]))
check("junk payloads never raise and never verify", raised == [], str(raised))
try:
    tf.TariffResult("import", tf.NO_VALUE, r.slots)
    carried = True
except ValueError:
    carried = False
check("a TariffResult that is not verified cannot carry slots (construction refused)", carried is False)

print("== [3] DST-day coverage")
aut = judged(fixture("import_rates_autumn_change_2030-10-27.json"))
spr = judged(fixture("import_rates_spring_change_2030-03-31.json"))
check("27 Oct 2030 (clocks back): 50 half-hours verify and cover the 25 h local day",
      aut.verified and len(aut.slots) == 50 and aut.covers_local_day(date(2030, 10, 27), Z))
check("... 48 half-hours do not cover it", not judged(fixture("import_rates_autumn_change_2030-10-27.json")[:48]).covers_local_day(date(2030, 10, 27), Z))
check("31 Mar 2030 (clocks forward): 46 half-hours verify and cover the 23 h local day",
      spr.verified and len(spr.slots) == 46 and spr.covers_local_day(date(2030, 3, 31), Z))
check("... and an ordinary day needs 48", judged(ph.go_like_rates(date(2030, 1, 15), 1)).covers_local_day(date(2030, 1, 15), Z)
      and len(ph.go_like_rates(date(2030, 1, 15), 1)) == 48)
check("the autumn day's cheap run spans the repeated hour (4.5 h elapsed from 01:00 BST to 04:30 GMT), searched from the "
      "start of the payload (local midnight, 23:00 UTC) so the rates cover the search period",
      (lambda w: w is not None and (w.end - w.start) == timedelta(hours=4, minutes=30))(tf.cheap_window(aut, datetime(2030, 10, 26, 23, tzinfo=UTC))[0]))
check("... searched from an hour earlier the one-day payload does not cover the search period: no window",
      tf.cheap_window(aut, datetime(2030, 10, 26, 22, tzinfo=UTC))[0] is None
      and tf.cheap_window(aut, datetime(2030, 10, 26, 22, tzinfo=UTC))[1][0].code == "TARIFF_COVERAGE_SHORT")

print("== [4] cheap window, coverage and price range")
cw, _n = tf.cheap_window(r, NOW)
check("the cheap window is tomorrow 01:00-04:30 (local = UTC in January) at 7.5 p/kWh",
      cw is not None and cw.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC) and cw.end == datetime(2030, 1, 16, 4, 30, tzinfo=UTC)
      and cw.p_per_kwh == 7.5 and cw.slots == 7, str(cw))
summer = judged(ph.go_like_rates(date(2030, 7, 1), 2))
sw, _n = tf.cheap_window(summer, datetime(2030, 7, 1, 20, 30, tzinfo=UTC))
check("in summer the same local window is 00:00-03:30 UTC (BST)", sw is not None and sw.start == datetime(2030, 7, 2, 0, 0, tzinfo=UTC)
      and sw.end == datetime(2030, 7, 2, 3, 30, tzinfo=UTC), str(sw))
check("... with the cheap band's ceiling: the lowest candidate rate plus PROPOSED_CHEAP_BAND_P_PER_KWH (8.0 p), and "
      "in_band is the same test the run was built with",
      cw is not None and cw.ceiling_p_per_kwh == 7.5 + tf.PROPOSED_CHEAP_BAND_P_PER_KWH
      and all(cw.in_band(x) == (x.p_per_kwh <= 8.0) for x in r.slots)
      and sum(cw.in_band(x) for x in r.overlapping(cw.start, cw.end)) == 7, str(cw))
mid = datetime(2030, 1, 16, 2, 0, tzinfo=UTC)
r3 = judged(ph.go_like_rates(date(2030, 1, 15), 3))
cw_mid, _n = tf.cheap_window(r3, mid)
check("A30: inside the run (02:00) the run found starts at the slot that holds now (02:00), not at its own start "
      "(01:00), so its boundaries are not the tariff's; the ceiling is unchanged", cw_mid is not None
      and cw_mid.start == mid and cw_mid.end == datetime(2030, 1, 16, 4, 30, tzinfo=UTC)
      and cw_mid.ceiling_p_per_kwh == 8.0, str(cw_mid))
_ov = r.overlapping(datetime(2030, 1, 16, 1, 15, tzinfo=UTC), datetime(2030, 1, 16, 2, 0, tzinfo=UTC))
check("overlapping(a, b): the slots that overlap [a, b)",
      [x.start for x in _ov] == [datetime(2030, 1, 16, 1, 0, tzinfo=UTC), datetime(2030, 1, 16, 1, 30, tzinfo=UTC)])
short = judged(ph.go_like_rates(date(2030, 1, 15), 2, cheap=(60, 90)))
check("a cheap run shorter than the PROPOSED minimum is not a named cheap run", tf.cheap_window(short, NOW)[0] is None)
check("an unverified tariff gives no window", tf.cheap_window(cases["gappy"], NOW)[0] is None)
check("coverage of a needed period: inside -> VERIFIED, beyond the rates -> NO_VALUE TARIFF_COVERAGE_SHORT",
      judged(go, need=(NOW, NOW + timedelta(hours=20))).verified
      and judged(go, need=(NOW, NOW + timedelta(hours=40))).findings[0].code == "TARIFF_COVERAGE_SHORT")
check("price range over the next day is (7.5, 30.0); beyond coverage None",
      r.price_range(NOW, NOW + timedelta(hours=24)) == (7.5, 30.0) and r.price_range(NOW, NOW + timedelta(days=3)) is None)
check("hh:mm labels", tf.hhmm(60) == "01:00" and tf.hhmm(270) == "04:30" and tf.hhmm(1440) == "24:00")

# A35 / A38: the window check's lowest rate, the base of the no-run check (daily_plan): the slots that overlap
# [now - 24 h, now + 24 h), whatever slots exist there
check("A35 / A38: on a tariff priced the same every day, horizon_low_p_per_kwh (7.5 p) is the rate the cheap band starts "
      "from (the ceiling minus PROPOSED_CHEAP_BAND_P_PER_KWH), at 21:00 and inside the run (02:00)",
      tf.horizon_low_p_per_kwh(r, NOW) == 7.5 and cw is not None
      and tf.horizon_low_p_per_kwh(r, NOW) + tf.PROPOSED_CHEAP_BAND_P_PER_KWH == cw.ceiling_p_per_kwh
      and cw_mid is not None and tf.horizon_low_p_per_kwh(r3, mid) + tf.PROPOSED_CHEAP_BAND_P_PER_KWH
      == cw_mid.ceiling_p_per_kwh, str(tf.horizon_low_p_per_kwh(r, NOW)))


def flat20(overrides=None, day=date(2030, 1, 14), days=4):
    """20 p half-hours over `days` local days from `day` (local = UTC in January); `overrides` {'YYYY-MM-DDTHH:MM': GBP}."""
    return [dict(x, value_inc_vat=(overrides or {}).get(x["start"][:16], x["value_inc_vat"]))
            for x in ph.go_like_rates(day, days, cheap=(0, 0), cheap_gbp=0.20, peak_gbp=0.20)]


def low_of(rows, now=NOW):
    return tf.horizon_low_p_per_kwh(judged(rows), now)


_EDGES = {"2030-01-14T20:30": 0.04,      # 4 p, ends exactly at now - 24 h (21:00 on the 14th): outside the look-back
          "2030-01-14T21:00": 0.14,      # 14 p, starts exactly at now - 24 h: the first slot of the look-back, in it
          "2030-01-16T21:00": 0.06,      # 6 p, starts exactly at now + 24 h: outside the search period
          "2030-01-16T20:30": 0.15}      # 15 p, the last slot of the search period: in it
check("A38: the period is [now - 24 h, now + 24 h): a cheaper slot that ends exactly at now - 24 h (4 p) and one that "
      "starts exactly at now + 24 h (6 p) do not count; the first slot of the look-back (14 p, starting at now - 24 h) "
      "does and is the lowest",
      low_of(flat20(_EDGES)) == 14.0, str(low_of(flat20(_EDGES))))
check("... with that first look-back slot at 20 p, the last slot of the search period (15 p) is the lowest",
      low_of(flat20({**_EDGES, "2030-01-14T21:00": 0.20})) == 15.0, str(low_of(flat20({**_EDGES, "2030-01-14T21:00": 0.20}))))
_straddle_now = NOW + timedelta(minutes=10)                    # now - 24 h = 21:10 on the 14th, inside the 21:00 slot
_straddle = flat20({"2030-01-14T20:30": 0.04, "2030-01-14T21:00": 0.14})
check("... a slot that straddles now - 24 h (21:00-21:30 on the 14th at 14 p, now 21:10) is just inside the look-back "
      "and counts; the 4 p slot, ended 10 min before now - 24 h, does not",
      low_of(_straddle, _straddle_now) == 14.0, str(low_of(_straddle, _straddle_now)))
# R7-E1: the far end. With now at 21:10 on the 15th, now + 24 h (21:10 on the 16th) lies inside the 21:00-21:30 slot
_far = flat20({"2030-01-16T21:00": 0.06, "2030-01-16T21:30": 0.04})
check("R7-E1: a slot that straddles now + 24 h (21:00-21:30 on the 16th at 6 p, now 21:10) starts inside the search "
      "period and counts; the 4 p slot after it starts past now + 24 h and does not (a rule that kept only slots ending "
      "by now + 24 h would give 20 p)",
      low_of(_far, _straddle_now) == 6.0, str(low_of(_far, _straddle_now)))
check("... a cheaper slot that has just ended (5 p, 20:30-21:00 today, ending exactly at now) counts: the look-back (A38; "
      "A35 alone read only [now, now + 24 h))", low_of(flat20({"2030-01-15T20:30": 0.05})) == 5.0,
      str(low_of(flat20({"2030-01-15T20:30": 0.05}))))
# N2: the slot that holds now (started before now, ends after it) counts
_n2 = [x for x in flat20() if x["start"][:16] not in ("2030-01-15T20:30", "2030-01-15T21:00")]
_n2.append({"start": "2030-01-15T20:30:00+00:00", "end": "2030-01-15T21:30:00+00:00", "value_inc_vat": 0.075})
_n2.sort(key=lambda x: x["start"])
check("N2: the slot that holds now (one 7.5 p slot 20:30-21:30, now 21:00, 20 p elsewhere) counts: the lowest rate is "
      "7.5 p (a rule that kept only slots starting at or after now would give 20 p)",
      judged(_n2).verified and judged(_n2).rate_at(NOW) == 7.5 and low_of(_n2) == 7.5, str(low_of(_n2)))
_band_rows = ph.go_like_rates(date(2030, 1, 15), 3)
_band_rows = [dict(x, value_inc_vat=0.05) if x["start"][:16] == "2030-01-15T02:00" else x for x in _band_rows]
_band, _bn = tf.cheap_window(judged(_band_rows), NOW)
check("... only the window check's lowest rate looks back: a 5 p slot at 02:00 today (inside the look-back) gives "
      "horizon_low 5 p, while cheap_window still names tomorrow's 01:00-04:30 run with its ceiling from the slots still "
      "running (7.5 + 0.5 = 8 p; A30's named-run path unchanged)",
      low_of(_band_rows) == 5.0 and _band is not None and _band.ceiling_p_per_kwh == 8.0
      and _band.start == datetime(2030, 1, 16, 1, 0, tzinfo=UTC), f"{low_of(_band_rows)} {_band}")
_part = judged([x for x in flat20({"2030-01-16T00:30": 0.18}) if "2030-01-15T20:00" <= x["start"] < "2030-01-16T02:00"])
check("... whatever slots exist: rates that cover only part of the period give their own lowest rate (no coverage is "
      "needed); rates that end before now but inside the look-back count (yesterday's 21:00-24:00 at 30 p, its cheap "
      "slots 24 h old and more do not); rates wholly before the look-back, an unverified tariff and a naive now give "
      "None",
      _part.verified and not _part.covers(NOW, NOW + timedelta(hours=24)) and tf.horizon_low_p_per_kwh(_part, NOW) == 18.0
      and low_of(ph.go_like_rates(date(2030, 1, 14), 1)) == 30.0
      and low_of(ph.go_like_rates(date(2030, 1, 13), 1)) is None
      and tf.horizon_low_p_per_kwh(cases["gappy"], NOW) is None
      and tf.horizon_low_p_per_kwh(r, NOW.replace(tzinfo=None)) is None,
      f"{tf.horizon_low_p_per_kwh(_part, NOW)} {low_of(ph.go_like_rates(date(2030, 1, 14), 1))}")


def window_code(payload, now=NOW):
    w, n = tf.cheap_window(judged(payload), now)
    return None if w is not None else (n[0].code if n else "NONE")


D = date(2030, 1, 15)
check("the cheap window needs rates covering the whole search period: today's rates only -> TARIFF_COVERAGE_SHORT",
      window_code(ph.go_like_rates(D, 1)) == "TARIFF_COVERAGE_SHORT")
check("... only tomorrow's peak rows (16:00-19:00) -> TARIFF_COVERAGE_SHORT (never a peak-hour window)",
      window_code([x for x in ph.go_like_rates(D, 2) if x["start"][:13] in ("2030-01-16T16", "2030-01-16T17", "2030-01-16T18")])
      == "TARIFF_COVERAGE_SHORT")
check("a flat tariff names no window (one run longer than PROPOSED_MAX_CHEAP_WINDOW_MIN): TARIFF_CHEAP_RUN_TOO_LONG",
      window_code(ph.go_like_rates(D, 2, cheap=(0, 0), cheap_gbp=0.25, peak_gbp=0.25)) == "TARIFF_CHEAP_RUN_TOO_LONG")
check("... nor a near-flat one (25.0 / 25.4 p: every slot in the cheap band)",
      window_code(ph.go_like_rates(D, 2, cheap_gbp=0.250, peak_gbp=0.254)) == "TARIFF_CHEAP_RUN_TOO_LONG")
check("... nor one whose cheap run is less than PROPOSED_MIN_CHEAP_SPREAD_P_PER_KWH below every other slot (25 / 26 p)",
      window_code(ph.go_like_rates(D, 2, cheap_gbp=0.250, peak_gbp=0.260)) == "TARIFF_NO_PRICE_SPREAD")
check("... a cheap run of 13 h is too long; 12 h is a window", window_code(ph.go_like_rates(D, 2, cheap=(0, 780))) == "TARIFF_CHEAP_RUN_TOO_LONG"
      and window_code(ph.go_like_rates(D, 2, cheap=(0, 720))) is None)
check("... the Go-like spread (7.5 / 30 p) names its 3.5 h window", window_code(go) is None)
med = [dict(x, value_inc_vat=0.9) for x in flat]
check("a payload whose every rate is 0.9 (a pence figure where GBP/kWh is expected, below the per-row guard): its median "
      "is implausible, BLOCK TARIFF_UNIT_IMPLAUSIBLE, no price", judged(med).status == tf.BLOCK
      and judged(med).findings[0].code == "TARIFF_UNIT_IMPLAUSIBLE" and no_price(judged(med)))
check("... a few high slots (an Agile-style peak at 0.9) with a plausible median still verify",
      judged([dict(x, value_inc_vat=0.9) if i % 8 == 0 else x for i, x in enumerate(flat)]).verified)

print("== [5] events")
ev, en = tf.parse_events(fixture("events_2030-01-16.json"))
check("a Saving Session and a free-electricity period parse (rewards ignored)",
      [e.kind for e in ev] == ["saving_session", "free_electricity"] and not en
      and ev[0].start == datetime(2030, 1, 16, 17, 30, tzinfo=UTC), str(ev))
check("an empty list is a valid 'no events'", tf.parse_events([]) == ((), []))
check("a row list with a kind parses", len(tf.parse_events([{"start": "2030-01-16T17:30:00+00:00", "end": "2030-01-16T18:30:00+00:00",
                                                             "kind": "saving_session"}])[0]) == 1)
bad_ev = [{"saving_sessions": {"joined_events": [{"start": "2030-01-16T17:30:00", "end": "2030-01-16T18:30:00"}]}},
          {"saving_sessions": [{"start": "2030-01-16T18:30:00+00:00", "end": "2030-01-16T17:30:00+00:00"}]},
          {"unknown": []}, "x", [{"kind": "mystery", "start": "2030-01-16T17:30:00+00:00", "end": "2030-01-16T18:30:00+00:00"}]]
check("naive, inverted, unknown-key, non-list and unknown-kind events are refused (BLOCK, no period)",
      all(tf.parse_events(b)[0] == () and tf.parse_events(b)[1] and tf.parse_events(b)[1][0].severity == "BLOCK" for b in bad_ev))

print("== [6] in the SHADOW cycle")
syn = run_cycle(ph.verified_inputs(synthetic_recorded=True))
check("decisions accepted + a verified tariff: provenance VERIFIED_FROM_INTEGRATION, the TOU window checked by its named "
      "run (CHARGE_WINDOW_FROM_TARIFF)",
      syn.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION"
      and syn.tariff["window"] == {"start": "2030-01-16T01:00:00+00:00", "end": "2030-01-16T04:30:00+00:00"}
      and "CHARGE_WINDOW_FROM_TARIFF" in syn.reason_codes, str(syn.tariff) + str(syn.reason_codes))
check("... with an OK charge target the price range is published from the verified rates only",
      syn.item("charge_target").status == "OK" and syn.tariff["price_range"] == [7.5, 30.0], str(syn.tariff))
opn = run_cycle(ph.verified_inputs())
st_rec = ac.to_entity_payloads(opn)[ac.ENTITY_IDS["status"]][1]
check("all OPEN + an integration-shaped tariff: its age limit is unresolved (I-D6 OPEN), so NOT_VERIFIED, no price, no value",
      opn.tariff["provenance"] == "NOT_VERIFIED" and opn.tariff["price_range"] is None and opn.value is None
      and opn.plan is None and not re.search(r"\d", json.dumps({"t": st_rec["tariff"], "v": st_rec["value"], "p": st_rec["plan"]})),
      str(st_rec["tariff"]))
only6 = ph.verified_inputs(decisions=cf.synthetic_decisions().without("D1").without("D3"), accept_provenance=cf.SYNTHETIC_ACCEPT)
o6 = run_cycle(only6)
check("a verified tariff while the charge target is BLOCKED (I-D1, I-D3 OPEN): provenance VERIFIED, no price, no value",
      o6.tariff["provenance"] == "VERIFIED_FROM_INTEGRATION" and o6.item("charge_target").status == "BLOCKED"
      and o6.tariff["price_range"] is None and o6.value is None and o6.plan is None, str(o6.tariff))
fx = run_cycle(cf.cycle_inputs(synthetic_recorded=True))
check("the shared fixture's p_per_kwh rows are not integration-shaped: NOT_VERIFIED, the TOU table sets the window (WARN)",
      fx.tariff["provenance"] == "NOT_VERIFIED" and fx.tariff["price_range"] is None
      and "CHARGE_WINDOW_FROM_TOU_TABLE" in fx.reason_codes and "TARIFF_SHAPE_NOT_INTEGRATION" in fx.reason_codes)
stale = run_cycle(ph.with_reading(ph.verified_inputs(synthetic_recorded=True), "tariff.import_rates", ph.rates_payload(NOW), age_s=3600.0))
check("a stale verified-shape tariff is NOT_VERIFIED: no price, the TOU window stands without a tariff check",
      stale.tariff["provenance"] == "NOT_VERIFIED" and stale.tariff["price_range"] is None and stale.value is None
      and "CHARGE_WINDOW_FROM_TOU_TABLE" in stale.reason_codes, str(stale.tariff))

print("== [7] fixtures and privacy")
texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(ph.FIXTURES.glob("*"))}
check("fixtures/plan holds text JSON only", texts and all(n.endswith(".json") for n in texts) and all(json.loads(t) for t in texts.values()))
years = {int(y) for t in texts.values() for y in re.findall(r"\b(20\d\d)-\d\d-\d\dT", t)}
check("every fixture date is in the fictional year 2030", years == {2030}, str(years))
own = [Path(__file__), Path(__file__).with_name("_plan_helpers.py")] + sorted(ph.FIXTURES.glob("*"))
bad13 = [(p.name, i) for p in own for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
         if re.search(r"meter|mpan|octopus|parameters", line, re.IGNORECASE) and re.search(r"(?<!\d)\d{13}(?!\d)", line)]
check("no 13-digit number on a meter / mpan / octopus / parameters line", bad13 == [], str(bad13))
check("every fixture says it is SYNTHETIC", all("SYNTHETIC" in json.loads(t)["_note"] for t in texts.values()))

print("== [8] the adapter names a cheap run, never a charge window (A30; R10D-4 (c))")
# the TOU table is the only charge-window source; a VERIFIED tariff names a cheap run that only cross-checks it
_why = {
    "TARIFF_NOT_VERIFIED": cases["gappy"],
    "TARIFF_COVERAGE_SHORT": judged(ph.go_like_rates(date(2030, 1, 15), 1)),
    "TARIFF_NO_CHEAP_WINDOW": short,
    "TARIFF_CHEAP_RUN_TOO_LONG": judged(flat20()),
    "TARIFF_NO_PRICE_SPREAD": judged(ph.go_like_rates(date(2030, 1, 15), 2, cheap_gbp=0.075, peak_gbp=0.09)),
}
_said = {want: tf.cheap_window(res, NOW) for want, res in _why.items()}
check("each way cheap_window names no run gives its own WARN, and none of those texts calls the run a charge window",
      all(cw_ is None and [f.code for f in fs_] == [want] and all(f.severity == "WARN" for f in fs_)
          for want, (cw_, fs_) in _said.items())
      and not [f.text for _cw, fs_ in _said.values() for f in fs_ if re.search(r"charge[ -]window", f.text, re.I)],
      str({w: [(f.code, f.text) for f in fs_] for w, (_cw, fs_) in _said.items()}))
_src_tf = Path(tf.__file__).read_text(encoding="utf-8")
check("... nor does any comment, docstring or text of the adapter (tariff.py speaks of the cheap run it names)",
      not re.search(r"charge[ -]window", _src_tf, re.I)
      and '"""The cheap run a VERIFIED import tariff names:' in _src_tf,
      str(re.findall(r".{0,40}charge[ -]window.{0,40}", _src_tf, re.I)[:3]))

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all tariff checks passed")
