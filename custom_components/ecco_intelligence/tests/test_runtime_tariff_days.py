#!/usr/bin/env python3
"""A38 Part B (CCR-RT-DAYS) end to end: the import rates read from the tariff integration's day events.

The BUILT kit runs under the stand-in Home Assistant (_fake_ha) with owner-record decisions (synthetic test values), the
harness's fresh synthetic states and the real vendored run_cycle. `tariff.import_rates` maps the day events in day order:
three (previous, current, next) in [1] to [6], the recommended form's two (current, next; A42) in [7]; the runtime merges
their rows (runtime/sources.merge_day_tables) and the engine judges the one list. The synthetic tariff is the round-3
reviewer's N1 shape: 7.5 p from 00:30 to 05:30 local and 30 p otherwise
(fictional GBP/kWh rows, 2030). The next day's rates appear at 16:00 local; before that the next-day event holds an
empty list (published nothing yet). January 2030: Europe/London is UTC.

  [1] N1 through the runtime: the TOU grid-charge window misplaced to the 17:00-19:00 peak. At every half-hour of the
      day (00:00 to 23:30) charge_target is BLOCKED CHARGE_WINDOW_SOURCES_DISAGREE with no number on any charge-window
      item: from 00:30 to 15:30 through the window check's lowest rate (the previous and current days priced, the import
      tariff NOT_VERIFIED for prices), at local midnight and from 16:00 through the named cheap run (the current day
      alone, then the three days, cover the 24 h search period: the tariff VERIFIED)
  [2] the same day with the single current-day event mapped (the form before Part B): the peak window still BLOCKs at
      18:00, but from 19:00 it is OK with the WARN "does not price the whole TOU window" (the accepted residual of A38
      Part A that the three events close), and the published charge-window items (charge target, export, Dump, morning
      SOC) carry INFO CHARGE_WINDOW_NOT_PRICED in their entities' reason_codes (A41: the code passes through the
      runtime); at 18:00 (BLOCKED) none does
  [3] a TOU window equal to the cheap run (00:30-05:30) with the three events: never SOURCES_DISAGREE, charge_target
      OK with a number at every half-hour; CHARGE_WINDOW_NOT_PRICED on its entity exactly from 05:30 to 15:30 (today's
      occurrence has ended, tomorrow's is not priced before the 16:00 publication: the documented residual), never
      beside the named run (00:00 and from 16:00) or while today's occurrence is priced (00:30 to 05:00)
  [4] a merge the runtime refuses (the previous-day event holding the current day with one rate changed): no import
      rate reading reaches the engine (TARIFF_MISSING, provenance NOT_VERIFIED, no price), never a number from it; the
      charge-window items carry CHARGE_WINDOW_NOT_PRICED; the diagnostics download shows the refusal unredacted
      (last_cycle.source_notes holds ["tariff.import_rates", "TABLE_ROWS_OVERLAP"], nothing withheld, A42 RT4-1 (b)) and
      no entity id of the site file anywhere
  [5] the previous-day event not re-reported for 3600 s (over the 900 s limit) while the other two are 300 s old: the
      merged table is as old as its oldest event, so the status entity shows TARIFF_NOT_FRESH in reason_codes and the
      import table's input_ages row 3600 s 'stale', provenance NOT_VERIFIED, and charge_target carries the WARN
      CHARGE_WINDOW_FROM_TOU_TABLE and the charge-window items INFO CHARGE_WINDOW_NOT_PRICED (what INTELLIGENCE_HA_RUNTIME
      risk 8 and the runbook's R5 / T11 / Q6 look for)
  [6] the current-day event unavailable: before 16:00 the previous day alone contributes (no gap: TARIFF_COVERAGE_SHORT);
      from 16:00 the previous and next days merge with the gap kept, never filled, and the engine refuses the table
      (TARIFF_GAP in the status entity's reason_codes, provenance NOT_VERIFIED, the same WARN on charge_target and
      CHARGE_WINDOW_NOT_PRICED on the charge-window items)
  [7] the recommended form (A42): the two day events [current, next]. The peak-placed window BLOCKs
      CHARGE_WINDOW_SOURCES_DISAGREE with no number at every half-hour, as with three events; from the 16:00 publication
      the status entity shows TARIFF_VERIFIED (none of TARIFF_MISSING / NOT_FRESH / GAP / OVERLAP / FUTURE_DATED: what
      the runbook's R5 and T11 read) and the import table's live input_ages row 'fresh' (TARIFF_VERIFIED implies it,
      A45); a window equal to the cheap run is OK at every half-hour and carries CHARGE_WINDOW_NOT_PRICED exactly from
      05:30 to 15:30 (the residual hours)
  [8] A45 (RV9-2), the recommended form with a next-day row the engine cannot use (a null rate; a row that ends before it
      starts): before the 16:00 publication the import tariff code is TARIFF_COVERAGE_SHORT; after it the runtime's
      merge passes the row, the engine refuses the table and the status entity shows TARIFF_RATE_INVALID /
      TARIFF_SLOT_INVALID, never TARIFF_VERIFIED and none of the five codes the rows named before A45 (Q6 counts any
      import tariff code other than TARIFF_VERIFIED), and the diagnostics' source_notes hold no TABLE_* note (R5's
      cause is the status entity's code)
  [9] A45 (RV9-3, RV9-1): with three PV forecast sources of distinctive names, the diagnostics download's
      last_cycle.signals lists them by day and position only (pv.forecast.today.s000, pv.forecast.tomorrow.s000 / s001),
      none withheld, and no source name appears in the download, any entity or any recorder row; the computed cycle's
      recorded status row carries TARIFF_VERIFIED (what T11 reads), and a STALE publication after the next-day
      publication records no tariff code (T11 counts computed cycles only; T3 judges STALE)
  [10] A47 (RV10-1), the recommended form with a verified table that names no cheap run: a flat tariff, a cheap run
      without a clear spread and one cheap half-hour. From the publication every recorded status row carries
      TARIFF_VERIFIED with the cheap-run code beside it (TARIFF_CHEAP_RUN_TOO_LONG, TARIFF_NO_PRICE_SPREAD,
      TARIFF_NO_CHEAP_WINDOW) and no other TARIFF_* code; the runbook's R5 / Q6 rule (TARIFF_VERIFIED present; before the
      publication TARIFF_COVERAGE_SHORT too) finds no fault, although A45's literal rule would have counted every row;
      the flat and no-spread windows stay OK through the A35 spread check, the one-half-hour tariff BLOCKs the window
      (SOURCES_DISAGREE) while the table itself is verified. [7] and [8] apply the same rule: no fault in the healthy
      recommended form, a fault after the publication for an engine-refused next-day row
Every scenario also ends with zero write attempts of any kind, no stand-in violation and the configuration tree unchanged
outside ecco/intelligence/state/. Synthetic data only (2030, test_* ids); no network, no real Home Assistant. Plain script;
exits 1 on any failure.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

import _harness as H  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


UTC = timezone.utc
DAY = datetime(2030, 1, 15, tzinfo=UTC)                  # local midnight of the day swept (Europe/London = UTC in January)
PUBLISH_AT = DAY + timedelta(hours=16)                    # the next day's rates appear at 16:00
SAMPLES = [DAY + timedelta(minutes=30 * i) for i in range(48)]
PREFIX = "ecco_intel_tariff_days_"
PREV, CUR, NEXT = "event.test_previous_day_rates", "event.test_current_day_rates", "event.test_next_day_rates"
DAY_SPEC = [{"entity": PREV, "attribute": "rates"}, {"entity": CUR, "attribute": "rates"},
            {"entity": NEXT, "attribute": "rates"}]
TWO_EVENT_SPEC = DAY_SPEC[1:]                             # the recommended form (A42): [current day, next day]
ONE_EVENT_SPEC = {"entity": CUR, "attribute": "rates"}
WINDOW_ITEMS = ("charge_target", "predicted_morning_soc", "overnight_demand", "export_event", "dump_to_grid")
# A41: the published charge-window items that carry INFO CHARGE_WINDOW_NOT_PRICED (never overnight_demand or a forecast)
NOT_PRICED = "CHARGE_WINDOW_NOT_PRICED"
NP_ITEMS = ("charge_target", "export_event", "dump_to_grid", "predicted_morning_soc")
NP_NEVER = tuple(k for k in ("overnight_demand", "predicted_day_load", "pv_tomorrow") if k not in NP_ITEMS)

root = H.mktemp(PREFIX)
kit = root / "kit"
b = H.build_kit(kit)
if b.returncode != 0:
    print(b.stdout, b.stderr)
    sys.exit(1)
h = H.Harness(kit)
C = h.contract
ITEM_KEYS = C.ADVICE_ITEMS + C.FORECAST_ITEMS
DIAG = importlib.import_module("custom_components.ecco_intelligence.diagnostics")


def day_rows(day: datetime, *, change: tuple[int, float] | None = None) -> list[dict]:
    """The 48 half-hour rows of one local day: 0.075 GBP/kWh from 00:30 to 05:30, 0.30 otherwise (fictional). `change`
    = (row index, rate) replaces one row's rate."""
    rows = []
    for i in range(48):
        t = day + timedelta(minutes=30 * i)
        rows.append({"start": t.isoformat(), "end": (t + timedelta(minutes=30)).isoformat(),
                     "value_inc_vat": 0.075 if 1 <= i < 11 else 0.30})
    if change is not None:
        rows[change[0]] = dict(rows[change[0]], value_inc_vat=change[1])
    return rows


def shaped_rows(cheap: float, other: float, cheap_rows: range = range(1, 11)):
    """A day-rows function for another tariff shape (fictional GBP/kWh): `cheap` in the rows of `cheap_rows` (by default
    00:30 to 05:30), `other` elsewhere. shaped_rows(0.24, 0.24) is a flat tariff."""
    def rows_(day: datetime) -> list[dict]:
        out = []
        for i in range(48):
            t = day + timedelta(minutes=30 * i)
            out.append({"start": t.isoformat(), "end": (t + timedelta(minutes=30)).isoformat(),
                        "value_inc_vat": cheap if i in cheap_rows else other})
        return out
    return rows_


def seed_day_events(states, now: datetime, *, prev_rows=None, prev_age_s: float = 300.0,
                    cur_unavailable: bool = False, next_damage=None, rows_fn=None) -> None:
    """The three day events at `now` (re-reported 5 minutes before now, as the harness's tariff events; the previous-day
    event `prev_age_s` before now): yesterday's, today's and, from PUBLISH_AT local time of the day, tomorrow's rows
    (before it an empty list: not published). `cur_unavailable`: the current-day event's state is 'unavailable'.
    `next_damage`: a function that changes tomorrow's published rows (a row the engine cannot use). `rows_fn`: the
    day-rows function (day_rows, the two-rate tariff, by default)."""
    rows_fn = rows_fn or day_rows
    today = datetime(now.year, now.month, now.day, tzinfo=UTC)
    at = now - timedelta(minutes=5)
    prev_at = now - timedelta(seconds=prev_age_s)
    published = now >= today + (PUBLISH_AT - DAY)
    nxt = rows_fn(today + timedelta(days=1)) if published else []
    if published and next_damage is not None:
        nxt = next_damage(nxt)
    states.seed(PREV, prev_at.isoformat(),
                {"rates": prev_rows if prev_rows is not None else rows_fn(today - timedelta(days=1))}, changed_at=prev_at)
    states.seed(CUR, "unavailable" if cur_unavailable else at.isoformat(), {"rates": rows_fn(today)}, changed_at=at)
    states.seed(NEXT, at.isoformat(), {"rates": nxt}, changed_at=at)


def tou_window(states, starts: list[str], grid_slot: int) -> None:
    """The TOU table with these six starts and exactly one grid slot (the dongle's vocabulary, as the harness)."""
    for i, start in enumerate(starts, start=1):
        grid = i == grid_slot
        states.seed(H.slot_eid(i, "start"), start)
        states.seed(H.slot_eid(i, "target_soc"), "80" if grid else "20", {"unit_of_measurement": "%"})
        states.seed(H.slot_eid(i, "charge_source"), "Grid" if grid else "None")
        states.seed(H.slot_eid(i, "flags_raw"), "1" if grid else "0")


PEAK = (["01:00", "04:30", "12:00", "17:00", "19:00", "22:00"], 4)          # the grid slot at the 17:00-19:00 peak
AGREEING = (["00:30", "05:30", "12:00", "16:00", "19:00", "22:00"], 1)      # the grid slot equal to the cheap run


class Scn:
    """One stand-in Home Assistant with the built integration on a site file mapping the import rates as `import_spec`."""

    def __init__(self, name, import_spec, window, *, prev_rows=None, prev_age_s=300.0, cur_unavailable=False,
                 next_damage=None, pv=None, pv_extra=(), rows_fn=None):
        self.name = name
        self.window = window
        self.prev_rows = prev_rows
        self.prev_age_s = prev_age_s
        self.cur_unavailable = cur_unavailable
        self.next_damage = next_damage
        self.rows_fn = rows_fn
        self.pv_extra = tuple(pv_extra)          # forecast entities the harness does not seed (4.0 kWh, an hour old)
        self.cfg = root / name
        self.cfg.mkdir()
        now = SAMPLES[0] - timedelta(minutes=4)
        self.hass = h.new_hass(self.cfg, now)
        self.hass.states.events = False          # judged at the tick (the poll-driven cadence is test_runtime_poll_phase's)
        prof = H.site_profile(decisions=H.owner_decisions(),
                              readings=dict(H.READING_MAP, **{"tariff.import_rates": import_spec}))
        if pv is not None:                       # the PV forecast sources: {day: {source name: entity id}}
            prof["shadow_runtime"]["pv_forecast_sources"] = pv
        H.write_site(self.cfg, prof)
        self.seed()
        self.before = H.tree_hashes(self.cfg)
        self.entry = h.new_entry()
        h.setup(self.entry)
        self.c = h.coordinator(self.entry)
        self.c.grace_s = 120.0
        for _ in range(3):                       # both liveness memories confirmed, past the grace
            self.step(h.now + timedelta(seconds=60))

    def seed(self):
        H.seed_fresh_states(self.hass.states, h.now)
        tou_window(self.hass.states, *self.window)
        seed_day_events(self.hass.states, h.now, prev_rows=self.prev_rows, prev_age_s=self.prev_age_s,
                        cur_unavailable=self.cur_unavailable, next_damage=self.next_damage, rows_fn=self.rows_fn)
        for eid in self.pv_extra:
            self.hass.states.seed(eid, "4.0", {"unit_of_measurement": "kWh"}, changed_at=h.now - timedelta(hours=1))
        h.recorder().statistics = H.synthetic_statistics(h.now, days=30)

    def step(self, when):
        h.set_now(when)
        self.seed()
        h.tick(0, settle=10.0)

    def at(self, when):
        """The result computed at `when`: (charge_target status, its codes, the numeric charge-window items, the tariff
        provenance, the envelope's reason codes, whether it was computed at `when`)."""
        self.step(when)
        lc = self.c._last_computed  # noqa: SLF001
        if lc is None:
            return None
        v = {x.key: x for x in tuple(lc.items) + tuple(lc.forecasts)}
        ct = v.get("charge_target")
        codes = set() if ct is None else ({c for c, _t in ct.blockers} | set(ct.reason_codes))
        texts = set() if ct is None else {t for _c, t in ct.blockers}
        nums = [k for k in WINDOW_ITEMS if H.numeric_state(h.state(k))]
        st = h.state("status")
        attrs = {} if st is None else dict(st.attributes)
        ages = {str(a.get("name")): dict(a) for a in (attrs.get("input_ages") or ()) if isinstance(a, Mapping)}
        item_reasons = {}
        for k in ITEM_KEYS:                       # what each item entity publishes (its reason_codes attribute)
            ist = h.state(k)
            item_reasons[k] = set() if ist is None else set(dict(ist.attributes).get("reason_codes") or ())
        return {"status": None if ct is None else ct.status, "codes": codes, "texts": texts, "numbers": nums,
                "provenance": (lc.tariff or {}).get("provenance"), "reasons": set(lc.reason_codes),
                "fresh": lc.generated_at == when, "entity_reasons": set(attrs.get("reason_codes") or ()),
                "entity_ages": ages, "item_reasons": item_reasons}

    def close(self):
        if self.c is not None and not self.c.closed:
            h.unload(self.entry)
        after = H.tree_hashes(self.cfg)
        changed = sorted(k for k in set(self.before) | set(after) if self.before.get(k) != after.get(k)
                         and not k.startswith("ecco/intelligence/state/"))
        check(f"{self.name}: zero write attempts", not self.hass.write_attempts, str(self.hass.write_attempts[:3]))
        check(f"{self.name}: no stand-in violation", not self.hass.violations, str(self.hass.violations[:3]))
        check(f"{self.name}: the configuration tree changed only under ecco/intelligence/state/", not changed, str(changed[:3]))


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%M")


DISAGREE = "CHARGE_WINDOW_SOURCES_DISAGREE"
RESIDUAL = "does not price the whole TOU window"
UNUSABLE = ("TARIFF_MISSING", "TARIFF_NOT_FRESH", "TARIFF_GAP", "TARIFF_OVERLAP", "TARIFF_FUTURE_DATED")
# A47 (RV10-1): the cheap-run analysis' codes, which describe a verified table's shape and stand beside TARIFF_VERIFIED
# (the runbook names exactly these; test_install_drill pins them against intelligence/tariff.py's cheap_window)
SHAPE_CODES = frozenset({"TARIFF_NO_CHEAP_WINDOW", "TARIFF_CHEAP_RUN_TOO_LONG", "TARIFF_NO_PRICE_SPREAD",
                         "TARIFF_NO_SLOTS_AHEAD"})


def import_table_fault(codes, published: bool) -> bool:
    """The runbook's R5 / Q6 rule (A47, RV10-1) on one computed cycle's recorded status reason_codes: R5 fails and Q6
    counts the cycle when the import table's own code is not TARIFF_VERIFIED, read as TARIFF_VERIFIED's absence (before
    the next-day publication, the absence of both TARIFF_VERIFIED and TARIFF_COVERAGE_SHORT), as T11 reads it."""
    ok = {"TARIFF_VERIFIED"} | (set() if published else {"TARIFF_COVERAGE_SHORT"})
    return not ok & set(codes)


def last_status_row(scn) -> dict:
    """The attributes of the newest recorder row of the status entity (what the acceptance rows read)."""
    rows_ = [row for row in scn.hass.recorder_rows if row[0] == C.ENTITY_IDS["status"]]
    return dict(rows_[-1][2]) if rows_ else {}


def np_on(r) -> bool:
    """CHARGE_WINDOW_NOT_PRICED on every published charge-window item's entity, and on no other item's."""
    return (r is not None and all(NOT_PRICED in r["item_reasons"][k] for k in NP_ITEMS)
            and not any(NOT_PRICED in r["item_reasons"][k] for k in NP_NEVER) and NOT_PRICED not in r["entity_reasons"])


def np_off(r) -> bool:
    """CHARGE_WINDOW_NOT_PRICED on no item entity and not on the status entity."""
    return (r is not None and not any(NOT_PRICED in v for v in r["item_reasons"].values())
            and NOT_PRICED not in r["entity_reasons"])


def np_summary(rows) -> dict:
    return {k: sorted(x for x, v in r["item_reasons"].items() if NOT_PRICED in v) for k, r in rows.items() if r is not None}

try:
    # -----------------------------------------------------------------------------------------------------------------
    print("== [1] N1 through the runtime: three day events, the next day's rates at 16:00, the TOU window at the peak")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("three_events_peak", DAY_SPEC, PEAK)
    rows = {hhmm(t): s.at(t) for t in SAMPLES}
    check("every half-hour was computed at its own time (48 results)",
          len(rows) == 48 and all(r is not None and r["fresh"] for r in rows.values()),
          str([k for k, r in rows.items() if r is None or not r["fresh"]][:6]))
    bad = {k: (r["status"], sorted(r["codes"])[:5]) for k, r in rows.items()
           if r is None or r["status"] != "BLOCKED" or DISAGREE not in r["codes"]}
    check("the peak-placed window BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE at every half-hour of the day (00:00 to 23:30)",
          not bad, str(dict(list(bad.items())[:6])))
    nums = {k: r["numbers"] for k, r in rows.items() if r is not None and r["numbers"]}
    check("... with no number on any charge-window item (charge target, morning SOC, overnight demand, export, Dump)",
          not nums, str(dict(list(nums.items())[:4])))
    short = {k: r["provenance"] for k, r in rows.items() if "00:00" < k < "16:00"}
    covered = {k: r["provenance"] for k, r in rows.items() if k == "00:00" or k >= "16:00"}
    check("from 00:30 to 15:30 the import tariff is NOT_VERIFIED for prices (the search period is not covered: the window "
          "check's lowest rate BLOCKs); at local midnight (the current day alone covers it) and from 16:00 (the three days "
          "cover it) the tariff is VERIFIED and the named cheap run BLOCKs",
          len(short) == 31 and set(short.values()) == {"NOT_VERIFIED"} and len(covered) == 17
          and set(covered.values()) == {"VERIFIED_FROM_INTEGRATION"}
          and all("TARIFF_COVERAGE_SHORT" in rows[k]["reasons"] for k in short)
          and all("TARIFF_VERIFIED" in rows[k]["reasons"] for k in covered),
          f"{sorted(set(short.values()))} {sorted(set(covered.values()))} {[k for k, v in covered.items() if v != 'VERIFIED_FROM_INTEGRATION']}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [2] the same day with the single current-day event (before Part B): the residual from 19:00")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("one_event_peak", ONE_EVENT_SPEC, PEAK)
    one = {hhmm(t): s.at(t) for t in (DAY + timedelta(hours=18), DAY + timedelta(hours=19), DAY + timedelta(hours=21),
                                      DAY + timedelta(hours=23, minutes=30))}
    check("non-vacuity: with only the current-day event the peak window still BLOCKs at 18:00 (A38 Part A, the look-back)",
          one["18:00"]["status"] == "BLOCKED" and DISAGREE in one["18:00"]["codes"], str(one["18:00"]))
    resid = {k: (r["status"], sorted(r["codes"])[:4]) for k, r in one.items() if k != "18:00"
             and not (r["status"] == "OK" and DISAGREE not in r["codes"] and "CHARGE_WINDOW_FROM_TOU_TABLE" in r["codes"])}
    check("... but from 19:00 (tomorrow's occurrence, which one event does not price) it is OK with the WARN "
          "CHARGE_WINDOW_FROM_TOU_TABLE: the residual the three events close ([1] BLOCKs there)",
          not resid, str(resid))
    np_bad = [k for k, r in one.items() if k != "18:00" and not np_on(r)]
    check("... and there INFO CHARGE_WINDOW_NOT_PRICED passes through the runtime to the entities of exactly the published "
          "charge-window items (charge target, export, Dump, morning SOC), never overnight demand, a forecast or the "
          "status entity's top-level codes (A41)", not np_bad, str({k: np_summary(one)[k] for k in np_bad}))
    check("... while the window BLOCKs (18:00) no entity carries it", np_off(one["18:00"]),
          str(np_summary(one).get("18:00")))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [3] a TOU window equal to the cheap run, with the three day events")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("three_events_agreeing", DAY_SPEC, AGREEING)
    rows = {hhmm(t): s.at(t) for t in SAMPLES}
    dis = [k for k, r in rows.items() if r is None or DISAGREE in r["codes"]]
    check("never CHARGE_WINDOW_SOURCES_DISAGREE at any half-hour", not dis, str(dis[:6]))
    not_ok = {k: (r["status"], sorted(r["codes"])[:5]) for k, r in rows.items()
              if r is None or r["status"] != "OK" or "charge_target" not in r["numbers"]}
    check("charge_target OK with a number at every half-hour", not not_ok, str(dict(list(not_ok.items())[:4])))
    np_hours = sorted(k for k, r in rows.items() if r is not None and NOT_PRICED in r["item_reasons"]["charge_target"])
    expected_np = [k for k in rows if "05:30" <= k < "16:00"]
    check("CHARGE_WINDOW_NOT_PRICED on the charge target's entity exactly from 05:30 to 15:30 (the documented residual: "
          "today's occurrence has ended and tomorrow's is not priced before the 16:00 publication), never beside the "
          "named run (00:00 and from 16:00) or while today's occurrence is priced whole (00:30 to 05:00)",
          np_hours == expected_np, f"{np_hours}")
    check("... and wherever it is shown, on exactly the published charge-window items",
          all(np_on(rows[k]) for k in expected_np) and all(np_off(rows[k]) for k in rows if k not in expected_np),
          str({k: v for k, v in np_summary(rows).items() if v and v != sorted(NP_ITEMS)}))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [4] a merge the runtime refuses: no import rate reading reaches the engine")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("refused_merge", DAY_SPEC, PEAK, prev_rows=day_rows(DAY, change=(20, 0.31)))
    r = s.at(DAY + timedelta(hours=17))
    check("the previous-day event holding the current day with one rate changed: the table is refused, the engine sees no "
          "import rates (TARIFF_MISSING, provenance NOT_VERIFIED), so no price comes from it",
          r is not None and r["fresh"] and r["provenance"] == "NOT_VERIFIED" and "TARIFF_MISSING" in r["reasons"]
          and DISAGREE not in r["codes"], "None" if r is None else f"{r['provenance']} {sorted(r['reasons'])[:6]}")
    check("... the charge-window items carry INFO CHARGE_WINDOW_NOT_PRICED (no price check covered the window, A41)",
          np_on(r), str(np_summary({"17:00": r})))
    dl = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    notes = (dl.get("last_cycle") or {}).get("source_notes")
    check("A42 (RT4-1 (b)): the diagnostics download shows the refusal unredacted: last_cycle.source_notes holds "
          "[tariff.import_rates, TABLE_ROWS_OVERLAP], every note a contract key and a constant code, none withheld",
          isinstance(notes, list) and ["tariff.import_rates", "TABLE_ROWS_OVERLAP"] in notes
          and all(isinstance(n, list) and len(n) == 2 and all(isinstance(x, str) for x in n) for n in notes)
          and dl["last_cycle"].get("source_notes_withheld") == 0, str(notes)[:300])
    site_ids = [e for e in json.dumps(dict(H.READING_MAP, **{"tariff.import_rates": DAY_SPEC}, **H.SIGNAL_MAP)).split('"')
                if "." in e and "test_" in e]
    text = json.dumps(dl, default=str)
    check("... and no entity id of the site file appears anywhere in the download (entities stay redacted)",
          site_ids and not [e for e in site_ids if e in text] and dl.get("entities") == "**REDACTED**",
          str([e for e in site_ids if e in text][:3]))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [5] the previous-day event not re-reported for 3600 s: the merged table is as old as its oldest event")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("previous_day_stale", DAY_SPEC, PEAK, prev_age_s=3600.0)
    stale = {hhmm(t): s.at(t) for t in (DAY + timedelta(hours=12), DAY + timedelta(hours=18))}
    bad = {}
    for k, r in stale.items():
        row = {} if r is None else r["entity_ages"].get("tariff.import_rates", {})
        if not (r is not None and r["fresh"] and r["provenance"] == "NOT_VERIFIED"
                and "TARIFF_NOT_FRESH" in r["entity_reasons"] and row.get("age_s") == 3600.0
                and row.get("status") == "stale"):
            bad[k] = "None" if r is None else f"{r['provenance']} {sorted(r['entity_reasons'])[:6]} {row}"
    check("the previous-day event 3600 s old (the other two 300 s): the status entity shows TARIFF_NOT_FRESH in "
          "reason_codes and the import table's input_ages row 3600 s 'stale' (the oldest event's age), provenance "
          "NOT_VERIFIED, at 12:00 and 18:00", not bad, str(bad))
    warn = [k for k, r in stale.items() if r is None or "CHARGE_WINDOW_FROM_TOU_TABLE" not in r["codes"]]
    check("... and charge_target carries the WARN CHARGE_WINDOW_FROM_TOU_TABLE: no usable import tariff, so no "
          "cross-check (the case INTELLIGENCE_HA_RUNTIME risk 8 describes)", not warn, str(warn))
    check("... with INFO CHARGE_WINDOW_NOT_PRICED on the published charge-window items' entities at both hours (A41: how "
          "the runbook's T11 / Q6 see the missing cross-check)", all(np_on(r) for r in stale.values()),
          str(np_summary(stale)))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [6] the current-day event unavailable: a gap only once the next day is published, and the engine refuses it")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("current_day_unavailable", DAY_SPEC, PEAK, cur_unavailable=True)
    before, after = s.at(DAY + timedelta(hours=12)), s.at(DAY + timedelta(hours=18))
    check("before the next day's rates are published the previous day alone contributes: no gap, the coverage is short "
          "(TARIFF_COVERAGE_SHORT, never TARIFF_GAP)",
          before is not None and before["fresh"] and "TARIFF_COVERAGE_SHORT" in before["entity_reasons"]
          and "TARIFF_GAP" not in before["entity_reasons"],
          "None" if before is None else str(sorted(before["entity_reasons"])[:6]))
    check("from 16:00 the previous and next days merge with the gap kept, never filled, and the engine refuses the "
          "table: TARIFF_GAP in the status entity's reason_codes, provenance NOT_VERIFIED, and the WARN "
          "CHARGE_WINDOW_FROM_TOU_TABLE on charge_target",
          after is not None and after["fresh"] and "TARIFF_GAP" in after["entity_reasons"]
          and after["provenance"] == "NOT_VERIFIED" and "CHARGE_WINDOW_FROM_TOU_TABLE" in after["codes"],
          "None" if after is None else f"{after['provenance']} {sorted(after['entity_reasons'])[:6]}")
    check("... and INFO CHARGE_WINDOW_NOT_PRICED on the published charge-window items' entities (A41)", np_on(after),
          str(np_summary({"18:00": after})))
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [7] the recommended form (A42): the two day events [current, next]")
    # -----------------------------------------------------------------------------------------------------------------
    s = Scn("two_events_peak", TWO_EVENT_SPEC, PEAK)
    rows = {hhmm(t): s.at(t) for t in SAMPLES}
    check("every half-hour was computed at its own time (48 results)",
          len(rows) == 48 and all(r is not None and r["fresh"] for r in rows.values()),
          str([k for k, r in rows.items() if r is None or not r["fresh"]][:6]))
    bad = {k: (r["status"], sorted(r["codes"])[:5]) for k, r in rows.items()
           if r is None or r["status"] != "BLOCKED" or DISAGREE not in r["codes"] or r["numbers"]}
    check("the peak-placed window BLOCKs CHARGE_WINDOW_SOURCES_DISAGREE with no number on any charge-window item at every "
          "half-hour of the day, as with the three events (the current-day event's own cheap slots are the window "
          "check's lowest rate before the publication)", not bad, str(dict(list(bad.items())[:6])))
    r5 = {k: r for k, r in rows.items() if k >= "16:00"}
    r5_bad = {}
    for k, r in r5.items():
        row = r["entity_ages"].get("tariff.import_rates", {})
        if not ("TARIFF_VERIFIED" in r["entity_reasons"] and not set(UNUSABLE) & r["entity_reasons"]
                and row.get("status") == "fresh"):
            r5_bad[k] = f"{sorted(r['entity_reasons'])[:6]} {row}"
    check("from the 16:00 publication the status entity shows TARIFF_VERIFIED and none of TARIFF_MISSING / NOT_FRESH / "
          "GAP / OVERLAP / FUTURE_DATED in every cycle (what the runbook's R5 and T11 read), and the import table's live "
          "input_ages row is 'fresh' beside it (TARIFF_VERIFIED implies it, A45)",
          len(r5) == 16 and not r5_bad, str(dict(list(r5_bad.items())[:3])))
    pre = {k: r for k, r in rows.items() if k < "16:00"}
    check("... and the runbook's R5 / Q6 rule (A47) finds no import table fault in any cycle: TARIFF_VERIFIED from the "
          "publication, TARIFF_COVERAGE_SHORT before it (TARIFF_VERIFIED at local midnight, where the current day alone "
          "covers the period)",
          len(pre) == 32 and not [k for k, r in r5.items() if import_table_fault(r["entity_reasons"], True)]
          and not [k for k, r in pre.items() if import_table_fault(r["entity_reasons"], False)],
          str([k for k, r in pre.items() if import_table_fault(r["entity_reasons"], False)][:4]))
    s.close()
    s = Scn("two_events_agreeing", TWO_EVENT_SPEC, AGREEING)
    rows = {hhmm(t): s.at(t) for t in SAMPLES}
    not_ok = {k: (r["status"], sorted(r["codes"])[:5]) for k, r in rows.items()
              if r is None or r["status"] != "OK" or "charge_target" not in r["numbers"] or DISAGREE in r["codes"]}
    check("a window equal to the cheap run: charge_target OK with a number at every half-hour, never SOURCES_DISAGREE",
          not not_ok, str(dict(list(not_ok.items())[:4])))
    np_hours = sorted(k for k, r in rows.items() if r is not None and NOT_PRICED in r["item_reasons"]["charge_target"])
    expected_np = [k for k in rows if "05:30" <= k < "16:00"]
    check("... CHARGE_WINDOW_NOT_PRICED exactly from 05:30 to 15:30, on exactly the published charge-window items: the "
          "residual is limited to the hours before the next day's rates are published, after today's occurrence ended",
          np_hours == expected_np and all(np_on(rows[k]) for k in expected_np)
          and all(np_off(rows[k]) for k in rows if k not in expected_np), f"{np_hours}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [8] A45 (RV9-2): a next-day row the engine cannot use, in the recommended form")
    # -----------------------------------------------------------------------------------------------------------------
    def null_rate(rows_):
        rows_[20] = dict(rows_[20], value_inc_vat=None)
        return rows_

    def reversed_row(rows_):
        rows_[20] = dict(rows_[20], start=rows_[20]["end"], end=rows_[20]["start"])
        return rows_

    for label, damage, code in (("a null rate", null_rate, "TARIFF_RATE_INVALID"),
                                ("a row that ends before it starts", reversed_row, "TARIFF_SLOT_INVALID")):
        s = Scn(f"engine_refused_{code.lower()}", TWO_EVENT_SPEC, PEAK, next_damage=damage)
        before, after = s.at(DAY + timedelta(hours=15, minutes=30)), s.at(DAY + timedelta(hours=18))
        check(f"{label} in the next-day event: before the publication the import tariff code is TARIFF_COVERAGE_SHORT "
              "(the table prices today only; Q6 does not count it before the publication)",
              before is not None and before["fresh"] and "TARIFF_COVERAGE_SHORT" in before["entity_reasons"]
              and "TARIFF_VERIFIED" not in before["entity_reasons"],
              "None" if before is None else str(sorted(before["entity_reasons"])[:6]))
        check(f"... after it the runtime's merge passes the row and the engine refuses the table: the status entity's "
              f"import tariff code is {code}, not TARIFF_VERIFIED (R5 and T11 fail) and none of TARIFF_MISSING / "
              "NOT_FRESH / GAP / OVERLAP / FUTURE_DATED (so Q6 counts any import tariff code other than "
              "TARIFF_VERIFIED, the listed codes being examples)",
              after is not None and after["fresh"] and code in after["entity_reasons"]
              and "TARIFF_VERIFIED" not in after["entity_reasons"] and not set(UNUSABLE) & after["entity_reasons"],
              "None" if after is None else str(sorted(after["entity_reasons"])[:6]))
        check("... the runbook's R5 / Q6 rule (A47) counts the cycle after the publication as an import table fault and "
              "not the one before it",
              after is not None and before is not None and import_table_fault(after["entity_reasons"], True)
              and not import_table_fault(before["entity_reasons"], False))
        dl = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
        notes = (dl.get("last_cycle") or {}).get("source_notes")
        check("... and the diagnostics' source_notes hold no TABLE_* note (the runtime refused nothing): R5's cause is the "
              "import tariff code in the status entity's reason_codes",
              isinstance(notes, list) and not [n for n in notes if str(n[1]).startswith("TABLE_")]
              and dl["last_cycle"].get("source_notes_withheld") == 0, str(notes)[:300])
        s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [9] A45 (RV9-3, RV9-1): PV forecast observations by day and position only; a STALE status has no tariff code")
    # -----------------------------------------------------------------------------------------------------------------
    LABELS = ("test_pv_label_qa", "test_pv_label_qz", "test_pv_label_qy")    # distinctive source names (site text)
    PV_SECOND = "sensor.test_solar_forecast_tomorrow_second"
    s = Scn("pv_source_names", TWO_EVENT_SPEC, AGREEING, pv_extra=(PV_SECOND,),
            pv={"tomorrow": {LABELS[1]: "sensor.test_solar_forecast_tomorrow", LABELS[0]: PV_SECOND},
                "today": {LABELS[2]: "sensor.test_solar_forecast_today"}})
    r = s.at(DAY + timedelta(hours=18))
    dl = h.run(DIAG.async_get_config_entry_diagnostics(s.hass, s.entry))
    sig = (dl.get("last_cycle") or {}).get("signals")
    check("a computed cycle with three PV forecast sources (two for tomorrow, one for today): the download's "
          "last_cycle.signals lists them as pv.forecast.today.s000, pv.forecast.tomorrow.s000 and "
          "pv.forecast.tomorrow.s001 (the sources in name order), beside the contract signals, none withheld",
          r is not None and r["fresh"] and isinstance(sig, list)
          and [x for x in sig if str(x).startswith("pv.forecast.")]
          == ["pv.forecast.today.s000", "pv.forecast.tomorrow.s000", "pv.forecast.tomorrow.s001"]
          and {"battery.soc", "pv.power", "history.hourly"} <= set(sig)
          and dl["last_cycle"].get("signals_withheld") == 0, str(sig))
    hits = {lab: H.text_anywhere(s.hass, lab, dl) for lab in LABELS}
    check("... and no source name appears anywhere in the download, in any entity's state or attributes or in any "
          "recorder row (a source name is site text)", not any(hits.values()), str(hits))
    st_rows = [row for row in s.hass.recorder_rows if row[0] == C.ENTITY_IDS["status"]]
    computed = [row for row in st_rows if row[1] != "STALE"]
    check("A45 (RV9-1): the computed cycle's recorded status row carries TARIFF_VERIFIED in reason_codes (what T11 "
          "reads from the recorder)", bool(computed) and "TARIFF_VERIFIED" in (computed[-1][2].get("reason_codes") or ()),
          str(computed[-1][2].get("reason_codes") if computed else None))
    s.c.refresh_enabled = False                  # no refresh: the envelope runs past its validity, as after a late poll
    h.set_now(DAY + timedelta(hours=18, minutes=9))
    s.seed()
    h.tick(0, settle=10.0)
    st_rows = [row for row in s.hass.recorder_rows if row[0] == C.ENTITY_IDS["status"]]
    last = st_rows[-1] if st_rows else None
    check("... a STALE publication after the next-day publication records reason_codes with no tariff code (a null "
          "status is judged by T3, not counted by T11)",
          last is not None and last[1] == "STALE" and h.state("status").state == "STALE"
          and not [c_ for c_ in (last[2].get("reason_codes") or ()) if str(c_).startswith("TARIFF_")],
          "None" if last is None else f"{last[1]} {last[2].get('reason_codes')}")
    s.close()

    # -----------------------------------------------------------------------------------------------------------------
    print("== [10] A47 (RV10-1): a verified import table that names no cheap run, in the recommended form")
    # -----------------------------------------------------------------------------------------------------------------
    PUB_HOURS = ("16:00", "18:00", "23:30")
    for label, fn, shape, window_ok in (
            ("a flat tariff (0.24 GBP/kWh all day)", shaped_rows(0.24, 0.24), "TARIFF_CHEAP_RUN_TOO_LONG", True),
            ("a cheap run of 0.20 against 0.21 elsewhere (no clear spread)", shaped_rows(0.20, 0.21),
             "TARIFF_NO_PRICE_SPREAD", True),
            ("one cheap half-hour (0.075 at 02:00, 0.30 elsewhere)", shaped_rows(0.075, 0.30, range(4, 5)),
             "TARIFF_NO_CHEAP_WINDOW", False)):
        s = Scn(f"shape_{shape.lower()}", TWO_EVENT_SPEC, AGREEING, rows_fn=fn)
        got = {}
        for t in (DAY + timedelta(hours=12), DAY + timedelta(hours=16), DAY + timedelta(hours=18),
                  DAY + timedelta(hours=23, minutes=30)):
            r = s.at(t)
            got[hhmm(t)] = (r, set(last_status_row(s).get("reason_codes") or ()))
        after_ = {k: v for k, v in got.items() if k in PUB_HOURS}
        bad = {k: sorted(c_ for c_ in rec if c_.startswith("TARIFF_")) for k, (r, rec) in after_.items()
               if not (r is not None and r["fresh"] and "TARIFF_VERIFIED" in rec and shape in rec
                       and {c_ for c_ in rec if c_.startswith("TARIFF_")} - {"TARIFF_VERIFIED"} <= SHAPE_CODES)}
        check(f"{label}: from the publication every recorded status row carries TARIFF_VERIFIED with {shape} beside it, "
              "and no TARIFF_* code but those two kinds (the cheap-run codes are the tariff's shape, A47)",
              len(after_) == 3 and not bad, str(bad))
        check("... the runbook's R5 / Q6 rule finds no import table fault there (TARIFF_VERIFIED is present), although "
              "the rule A45 wrote ('any import tariff code other than TARIFF_VERIFIED') would have counted every one",
              not [k for k, (_r, rec) in after_.items() if import_table_fault(rec, True)]
              and all({c_ for c_ in rec if c_.startswith("TARIFF_")} - {"TARIFF_VERIFIED"} for _r, rec in after_.values()))
        r12, rec12 = got["12:00"]
        check("... before the publication the import table's own code is TARIFF_COVERAGE_SHORT (no fault before it)",
              r12 is not None and r12["fresh"] and "TARIFF_COVERAGE_SHORT" in rec12 and "TARIFF_VERIFIED" not in rec12
              and not import_table_fault(rec12, False), str(sorted(rec12)))
        if window_ok:
            wbad = {k: (r["status"], sorted(r["codes"])[:4]) for k, (r, _rec) in after_.items()
                    if not (r["status"] == "OK" and "charge_target" in r["numbers"]
                            and "CHARGE_WINDOW_FROM_TOU_TABLE" in r["codes"] and DISAGREE not in r["codes"])}
            check("... and the TOU window equal to the cheap rows stands through the A35 spread check: charge_target OK "
                  "with a number and the WARN CHARGE_WINDOW_FROM_TOU_TABLE", not wbad, str(wbad))
        else:
            wbad = {k: (r["status"], sorted(r["codes"])[:4]) for k, (r, _rec) in after_.items()
                    if not (r["status"] == "BLOCKED" and DISAGREE in r["codes"] and not r["numbers"])}
            check("... and the TOU window priced 2 p or more above the lowest rate BLOCKs SOURCES_DISAGREE with no number: "
                  "the window's own check, while the table itself is verified (R5 passes)", not wbad, str(wbad))
        s.close()
finally:
    H.rmtree_own(root, PREFIX)


print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED in runtime tariff days:")
    for f_ in FAILURES:
        print("  -", f_)
    sys.exit(1)
print("all runtime tariff days checks passed")
