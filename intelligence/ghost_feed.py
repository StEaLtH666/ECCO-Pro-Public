"""The Ghost's input from the integration's own data, and a compact summary (read-only; pure: no clock, file, network or store).

THE GHOST IS A SIMULATION. Intelligence controlled nothing: the real battery did what it did, and every ghost figure is
arithmetic on the recorded hourly energies and prices (ghost.py). It is evidence for the owner's decision about assisted mode,
never a decision, and nothing here can write, arm or change anything.

    build_ghost_feed(history, advice_rows, cfg, import_tariff=..., export_tariff=..., now=...) -> a JSON-safe dict (<= ~8 KB)

Inputs (all supplied by the caller; nothing is read here):
  history        the runtime's canonical hourly table (history.History): per hour pv, load, imp, exp, chg, dis (kWh) and the
                 hourly mean SOC. An hour is USABLE when all six energies and the SOC are present, finite, not negative and
                 carry no stalled / implausible / counter-reset flag; the period is the longest (ties: latest) run of
                 consecutive usable hours in the last `days` local days, so a gap never gets invented flows.
  advice_rows    the durable advice log (Scorecard.advice_records: the dicts of ghost.AdviceRecord.from_dict).
  cfg            the SiteConfig: capacity, round-trip efficiency, reserves, power limit, time zone.
  tariffs        tariff.TariffResult. MONEY needs a VERIFIED import tariff covering the period (an hour with no verified rate
                 makes the period end there: the longest run of usable hours that the rates cover is used, at least 24 h).
                 Without one there is NO MONEY: no pence figure appears anywhere, only the behaviour comparison (energy
                 flows, SOC, reserve) and the advice followed / not followed; the plan-value module insists on the same.
                 An unverified export tariff counts export income as 0 in BOTH runs and says so: where the ghost exports a different
                 amount than reality, that export income difference is missing from every pence figure, so the advice effect can be
                 too high (the ghost exports less) or too low (it exports more). ghost_compare gives no verdict where the exports differ.

What the hourly slots cost (stated, not hidden):
  * the recorded SOC is an hourly MEAN; the SOC at the end of an hour is estimated as the mean of this and the next hour's
    means (the last hour: its own), and the SOC at the start from the hour before the period when there is one;
  * advice windows are matched to the hourly slots: a slot is in a window when at least half of it is (a window shorter than
    half an hour reaches no slot and is reported as not followed);
  * PV the inverter spilled is unknown here (taken as 0), so the ghost cannot use it for extra charge.

The advice log holds one row per kind per slot cycle (the same advice again every hour), so `advice.records_in_period` and
`not_followed` count LOG ROWS, `followed_log_rows` the followed rows, and `advice.followed` (and each day's `advice_followed`) the
DISTINCT (kind, window, target) among them. A row that is followable but was withdrawn by a later BLOCKED row before it took effect
is still counted as followed; what the simulation really acted on is `advice_in_force_hours`.

The summary carries, per local day (newest `days` at most), the actual and the ghost net before wear, the realised and the
stock-adjusted deltas, the no-advice baseline, each run's minimum SOC, the ghost's reserve breach and the advice followed or
not (with reasons); the period, the data-quality flags, the `ready_for_assisted_evidence` block (evidence only; it decides
nothing) and the uncertainty block: the two closing-stock rules, the model baseline and a sensitivity to the round-trip
efficiency plus or minus 3 percentage points. If it would exceed the size bound, the oldest days are dropped (stated).
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Mapping, Sequence

from . import ghost
from .config import SiteConfig
from .ghost import ActualPeriod, AdviceRecord, run_ghost
from .history import (ENERGY_FIELDS, F_IMPLAUSIBLE, F_RESET, F_STALLED, History, HourRecord)
from .net_value import Slot, Tariff
from .tariff import TariffResult
from .timeutil import HOUR, ts, utc_from_ts, zone

FEED_SCHEMA = "ecco-intel-ghost-feed/1"
DEFAULT_DAYS = 14
MIN_PERIOD_HOURS = 24
MAX_BYTES = 8192
EFFICIENCY_STEP = 0.03                        # sensitivity: round-trip efficiency +/- 3 percentage points
UNUSABLE_FLAGS = (F_STALLED, F_IMPLAUSIBLE, F_RESET)
STATUS_OK = "OK"
STATUS_INSUFFICIENT = "INSUFFICIENT_HISTORY"
TARIFF_VERIFIED_LABEL = "VERIFIED_FROM_INTEGRATION"       # the feed's `tariff.import` / `tariff.export` when the rates are verified
LABEL = ("SIMULATION: arithmetic on recorded hourly data. Intelligence controlled nothing; the real battery did what it did. "
         "Evidence for the owner's decision, never a decision.")
STOCK_RULES = ("closing stock difference valued two ways, the one less favourable to the ghost used: (a) each run's mixed-tank "
               "cost basis; (b) deliverable kWh at the period's mean import price")


def _num(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def _usable(rec: HourRecord | None) -> tuple[bool, str | None]:
    """(usable, why not)."""
    if rec is None:
        return False, "missing_hour"
    for f in ENERGY_FIELDS:
        v = rec.e.get(f)
        if not _num(v):
            return False, "missing_energy"
        if v < 0:
            return False, "negative_energy"
        if any(fl in UNUSABLE_FLAGS for fl in rec.flags.get(f, ())):
            return False, "flagged_energy"
    if not _num(rec.soc_mean):
        return False, "missing_soc"
    return True, None


def _price(result: TariffResult | None, start: datetime) -> float | None:
    """The verified rate for [start, start + 1 h): the overlap-weighted mean of the rate slots; None unless they cover it."""
    if not (isinstance(result, TariffResult) and result.verified):
        return None
    end = start + timedelta(hours=1)
    got, acc = 0.0, 0.0
    for s in result.overlapping(start, end):
        sec = (min(s.end, end) - max(s.start, start)).total_seconds()
        got += sec
        acc += sec * s.p_per_kwh
    return acc / got if abs(got - HOUR) < 1e-6 else None


def _runs(starts: Sequence[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for s in sorted(starts):
        if out and out[-1][-1] + HOUR == s:
            out[-1].append(s)
        else:
            out.append([s])
    return out


def _pick(runs: list[list[int]]) -> list[int] | None:
    runs = [r for r in runs if len(r) >= MIN_PERIOD_HOURS]
    return max(runs, key=lambda r: (len(r), r[-1])) if runs else None


def _snap(a: AdviceRecord, slots: tuple[Slot, ...]) -> tuple[AdviceRecord, str | None]:
    """Match the advice window to the hourly slots (a slot is in when at least half of it is)."""
    if a.window_start is None or a.window_end is None:
        return a, None
    inside = [s for s in slots if (min(s.start + timedelta(hours=s.hours), a.window_end) - max(s.start, a.window_start))
              .total_seconds() >= 0.5 * s.hours * 3600.0 - 1e-6]
    if not inside:
        return replace(a, window_start=None, window_end=None), "WINDOW_SHORTER_THAN_SLOT"
    return replace(a, window_start=inside[0].start, window_end=inside[-1].start + timedelta(hours=inside[-1].hours)), None


def _advice_key(a: AdviceRecord) -> tuple:
    """One piece of advice, whatever the number of log rows that repeat it (the slot cycles log it every hour): kind, window, target."""
    return (a.kind, a.window_start, a.window_end, a.target_soc_pct)


def _empty(status: str, reason: str, notes: list[str], **extra) -> dict:
    out = {"schema": FEED_SCHEMA, "model_version": ghost.MODEL_VERSION, "simulated": True, "intelligence_controlled_nothing": True,
           "label": LABEL, "status": status, "reason": reason, "money_available": False, "data_quality": {"notes": notes}}
    out.update(extra)
    return out


def build_ghost_feed(history: History, advice_rows: Sequence[Mapping], cfg: SiteConfig, *,
                     import_tariff: TariffResult | None = None, export_tariff: TariffResult | None = None,
                     now: datetime | None = None, days: int = DEFAULT_DAYS, ha_reserve_pct: float | None = None,
                     max_bytes: int = MAX_BYTES, detail: dict | None = None) -> dict:
    """The compact Ghost summary (see the module docstring). Never raises for a data problem: it returns status
    INSUFFICIENT_HISTORY with the reason; only a programming error (a wrong argument type) raises.

    `detail` (default None: no effect on the result): a dict the caller passes to receive the run's internals for a richer
    reading of the same run (ghost_compare.py): the base report `rep`, the two efficiency runs `sens`, `money`, the
    period's `starts` and the parsed advice records `advice`. It is filled only when the status is OK."""
    if not isinstance(history, History):
        raise TypeError("history must be a History")
    if not (isinstance(days, int) and 1 <= days <= 60):
        raise ValueError("days must be a whole number between 1 and 60")
    tz = zone(cfg.tz)
    hist = history.truncated(now) if now is not None else history
    span = hist.first_last()
    notes: list[str] = []
    if span is None:
        return _empty(STATUS_INSUFFICIENT, "no_history", notes)
    last_start = ts(span[1])                                    # newest complete hour
    day1 = (utc_from_ts(last_start).astimezone(tz).date())
    first_day = day1 - timedelta(days=days - 1)
    lo = ts(datetime.combine(first_day, datetime.min.time(), tzinfo=tz))
    window = [s for s in range(lo - (lo % HOUR), last_start + HOUR, HOUR)]
    why: dict[str, int] = {}
    usable: list[int] = []
    for s in window:
        ok, reason = _usable(hist.get(s))
        if ok:
            usable.append(s)
        else:
            why[reason] = why.get(reason, 0) + 1
    imp_verified = isinstance(import_tariff, TariffResult) and import_tariff.verified
    priced = [s for s in usable if _price(import_tariff, utc_from_ts(s)) is not None] if imp_verified else []
    block = _pick(_runs(priced)) if imp_verified else None
    longest_data = _pick(_runs(usable))
    money = block is not None
    if not money:
        block = longest_data
        if imp_verified:
            notes.append("TARIFF_COVERS_TOO_LITTLE: verified import rates cover under 24 usable hours: no money figure")
        else:
            notes.append("NO_VERIFIED_TARIFF: no money figure; behaviour comparison only")
    if block is None:
        return _empty(STATUS_INSUFFICIENT, "no_24h_run_of_usable_hours", notes,
                      data_quality={"window_hours": len(window), "usable_hours": len(usable), "unusable_by_reason": why,
                                    "notes": notes})
    n = len(block)
    starts = [utc_from_ts(s) for s in block]
    recs = [hist.get(s) for s in block]
    prev = hist.get(block[0] - HOUR)
    nxt_ok = [hist.get(block[i + 1]) if i + 1 < n else None for i in range(n)]

    def socv(r: HourRecord | None) -> float | None:
        return min(100.0, max(0.0, float(r.soc_mean))) if r is not None and _num(r.soc_mean) else None
    soc_end = []
    for i, r in enumerate(recs):
        a, b = socv(r), socv(nxt_ok[i])
        soc_end.append(a if b is None else (a + b) / 2.0)
    p0 = socv(prev)
    soc0 = socv(recs[0]) if p0 is None else (p0 + socv(recs[0])) / 2.0
    slots = tuple(Slot(starts[i], 1.0, r.e["pv"], r.e["load"], r.e["imp"], r.e["exp"], r.e["chg"], r.e["dis"], 0.0)
                  for i, r in enumerate(recs))
    flagged = sum(1 for r in recs for f in ENERGY_FIELDS if r.flags.get(f))
    interp = sum(1 for r in recs if any(r.flags.get(f) for f in ENERGY_FIELDS))
    export_priced = money and isinstance(export_tariff, TariffResult) and export_tariff.verified and all(
        _price(export_tariff, t) is not None for t in starts)
    if money:
        imp_p = tuple(_price(import_tariff, t) for t in starts)
        exp_p = tuple(_price(export_tariff, t) for t in starts) if export_priced else tuple(0.0 for _ in starts)
        if not export_priced:
            notes.append("EXPORT_TARIFF_NOT_VERIFIED: export income counted as 0 in both runs, so where the advice run exports a "
                         "different amount its export income difference is missing from every pence figure (the advice effect can "
                         "be too high or too low there); no ahead or behind verdict is given where the exports differ")
    else:                                                       # a stand-in price series so the simulation runs; never shown
        imp_p, exp_p = tuple(1.0 for _ in starts), tuple(0.0 for _ in starts)
    tariff = Tariff.make(n, list(imp_p), list(exp_p), True)
    period = ActualPeriod(slots, tariff, soc0, tuple(soc_end))

    # --- the advice: parsed, matched to the hourly slots, counted per local day
    p_start, p_end = starts[0], starts[-1] + timedelta(hours=1)
    recs_adv: list[AdviceRecord] = []
    invalid = 0
    for row in advice_rows:
        try:
            a = AdviceRecord.from_dict(row)
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        if a.issued_at >= p_end or (a.window_end is not None and a.window_end <= p_start):
            continue
        recs_adv.append(a)
    snapped: list[AdviceRecord] = []
    snap_reason: dict[int, str] = {}
    for a in sorted(recs_adv, key=lambda x: (x.issued_at, x.kind)):
        b, rs = _snap(a, slots)
        snapped.append(b)
        if rs:
            snap_reason[id(b)] = rs
    dump_no_window = sum(1 for a in recs_adv if a.kind == ghost.KIND_DUMP and a.status == ghost.OK and
                         (a.window_start is None or a.window_end is None))

    def reason(a: AdviceRecord) -> str | None:
        return snap_reason.get(id(a)) or a.not_followed_reason(False)

    wear = None
    rep = run_ghost(period, snapped, cfg, wear_p_per_kwh=wear, ha_reserve_pct=ha_reserve_pct)
    sens = {}
    for tag, delta in (("minus", -EFFICIENCY_STEP), ("plus", EFFICIENCY_STEP)):
        eff = min(1.0, max(0.5, cfg.round_trip_efficiency + delta))
        sens[tag] = (eff, run_ghost(period, snapped, replace(cfg, round_trip_efficiency=eff), wear_p_per_kwh=wear,
                                    ha_reserve_pct=ha_reserve_pct))

    # --- per local day
    in_period = [a for a in snapped if p_start <= a.issued_at < p_end]
    per_day_adv: dict[str, dict] = {}
    for a in in_period:
        d = a.issued_at.astimezone(tz).date().isoformat()
        cell = per_day_adv.setdefault(d, {"followed": set(), "not_followed": {}})
        rs = reason(a)
        if rs is None:
            cell["followed"].add(_advice_key(a))
        else:
            cell["not_followed"][rs] = cell["not_followed"].get(rs, 0) + 1
    ready = rep["ready_for_assisted_evidence"]
    breach_dates = set(ready["ghost_below_reserve_dates"])
    day_out = []
    for d in rep["days"]:
        cell = per_day_adv.get(d["date"], {"followed": set(), "not_followed": {}})
        row = {"date": d["date"]}
        if d["slots"] != 24:
            row["hours"] = d["slots"]
        if money:
            row.update({"actual_net_before_wear_p": _r(d["actual_net_before_wear_p"]),
                        "ghost_net_before_wear_p": _r(d["ghost_net_before_wear_p"]),
                        "delta_realised_p": _r(d["delta_realised_p"]), "delta_stock_adjusted_p": _r(d["delta_p"]),
                        "model_baseline_delta_p": _r(d["model_baseline_delta_p"]), "advice_effect_p": _r(d["advice_effect_p"])})
        row.update({"actual_min_soc_pct": _r(d["actual_min_soc_pct"], 1), "ghost_min_soc_pct": _r(d["ghost_min_soc_pct"], 1),
                    "ghost_below_reserve": d["date"] in breach_dates, "advice_in_force_hours": d["advice_in_force_slots"],
                    "advice_followed": len(cell["followed"]),
                    "extra_import_kwh_in_ghost": _r(d["extra_import_kwh_in_ghost"])})
        if cell["not_followed"]:
            row["advice_not_followed"] = cell["not_followed"]
        day_out.append(row)

    tot = rep["totals"]
    ready_out = {"evidence_only": True, "decision": None, "days_compared": ready["days_compared"],
                 "days_diverged": ready["days_diverged"], "ghost_below_reserve_slots": ready["ghost_below_reserve_slots"],
                 "ghost_below_reserve_days": ready["ghost_below_reserve_days"],
                 "ghost_below_reserve_dates": ready["ghost_below_reserve_dates"], "effective_reserve_pct": _r(ready["reserve_pct"], 1)}
    uncertainty = {"closing_stock_rules": STOCK_RULES,
                   "round_trip_efficiency_pct": {"base": _r(cfg.round_trip_efficiency * 100, 1),
                                                 "minus": _r(sens["minus"][0] * 100, 1), "plus": _r(sens["plus"][0] * 100, 1)},
                   "model_baseline": "the no-advice ghost against reality: 0 when the recorded flows replay exactly; subtracted "
                                     "out of the advice effect"}
    if money:
        ready_out.update({"days_ghost_ahead": ready["days_ghost_ahead"], "days_ghost_behind": ready["days_ghost_behind"],
                          "days_level": ready["days_level"], "worst_ghost_day": ready["worst_ghost_day"],
                          "delta_realised_p": _r(ready["delta_realised_p"]),
                          "delta_stock_adjusted_p": _r(ready["delta_stock_adjusted_p"]),
                          "model_baseline_delta_p": _r(ready["model_baseline_delta_p"]),
                          "advice_effect_p": _r(ready["advice_effect_p"]), "basis": "net before wear (wear price unknown), stock-adjusted"})
        uncertainty["model_baseline_delta_p"] = _r(ready["model_baseline_delta_p"])
        uncertainty["stock_rules_p"] = {"cost_basis": _r(tot["stock_adjustment_cost_basis_rule_p"]),
                                        "mean_import_price": _r(tot["stock_adjustment_mean_import_rule_p"])}
        uncertainty["sensitivity"] = {tag: {"delta_stock_adjusted_p": _r(r["totals"]["delta_headline_p"]),
                                            "advice_effect_p": _r(r["totals"]["advice_effect_p"])}
                                      for tag, (_e, r) in sens.items()}
        uncertainty["sensitivity"]["base"] = {"delta_stock_adjusted_p": _r(tot["delta_headline_p"]),
                                              "advice_effect_p": _r(tot["advice_effect_p"])}
    else:
        uncertainty["sensitivity"] = {tag: {"ghost_below_reserve_slots": r["ready_for_assisted_evidence"]["ghost_below_reserve_slots"],
                                            "closing_stored_difference_kwh": _r(r["totals"]["closing_stored_difference_kwh"])}
                                      for tag, (_e, r) in sens.items()}
        uncertainty["sensitivity"]["base"] = {"ghost_below_reserve_slots": ready["ghost_below_reserve_slots"],
                                              "closing_stored_difference_kwh": _r(tot["closing_stored_difference_kwh"])}
    totals = {"actual_min_soc_pct": _r(tot["actual_min_soc_pct"], 1), "ghost_min_soc_pct": _r(tot["ghost_min_soc_pct"], 1),
              "closing_stored_difference_kwh": _r(tot["closing_stored_difference_kwh"]),
              "actual_throughput_kwh": _r(tot["actual_throughput_kwh"]), "ghost_throughput_kwh": _r(tot["ghost_throughput_kwh"])}
    if money:
        totals.update({"delta_realised_p": _r(tot["delta_realised_p"]), "stock_adjustment_p": _r(tot["stock_adjustment_p"]),
                       "delta_stock_adjusted_p": _r(tot["delta_headline_p"]), "model_baseline_delta_p": _r(tot["model_baseline_delta_p"]),
                       "advice_effect_p": _r(tot["advice_effect_p"]),
                       "actual_net_before_wear_p": _r(tot["actual"]["net_before_wear_p"]),
                       "ghost_net_before_wear_p": _r(tot["ghost"]["net_before_wear_p"])})
    followed_rows = [a for a in in_period if reason(a) is None]
    followed = len({_advice_key(a) for a in followed_rows})
    nf: dict[str, int] = {}
    for a in in_period:
        rs = reason(a)
        if rs is not None:
            nf[rs] = nf.get(rs, 0) + 1
    dq = rep["ready_for_assisted_evidence"]["data_quality"]
    quality = {"window_hours": len(window), "usable_hours": len(usable), "period_hours": n,
               "unusable_by_reason": why, "hours_with_repaired_or_flagged_energy": interp,
               "approximations": ["SOC: hourly means, end of hour estimated", "advice windows matched to hourly slots (half a slot "
                                  "in = in)", "spilled PV unknown, taken as 0"], "advice_rows_invalid": invalid,
               "dump_advice_without_window": dump_no_window,
               "ghost_model_flags": sorted({f.split(":")[0] for f in
                                            dq["actual_flags"] + dq["ghost_flags"] + dq["model_baseline_flags"]}),
               "unattributed_energy_excluded": dq["unattributed_energy_excluded"], "notes": notes}
    if dump_no_window:
        quality["notes"] = notes + ["DUMP_ADVICE_HAS_NO_WINDOW: no intended Dump-to-Grid duration is recorded, so dump advice "
                                    "cannot be simulated (counted as not followed)"]
    out = {"schema": FEED_SCHEMA, "model_version": ghost.MODEL_VERSION, "simulated": True, "intelligence_controlled_nothing": True,
           "label": LABEL, "status": STATUS_OK, "reason": None, "money_available": money,
           "tariff": {"import": TARIFF_VERIFIED_LABEL if imp_verified else "NOT_VERIFIED",
                      "export": TARIFF_VERIFIED_LABEL if export_priced else "NOT_VERIFIED"},
           "period": {"start": p_start.isoformat(), "end": p_end.isoformat(), "hours": n, "timezone": cfg.tz,
                      "slot_minutes": 60, "longest_usable_run_hours": 0 if longest_data is None else len(longest_data),
                      "soc_start_pct": _r(soc0, 1)},
           "advice": {"records_in_period": len(in_period), "followed": followed, "followed_log_rows": len(followed_rows),
                      "not_followed": nf},
           "totals": totals, "days": day_out, "ready_for_assisted_evidence": ready_out, "uncertainty": uncertainty,
           "data_quality": quality}
    if detail is not None:
        detail.update({"rep": rep, "sens": sens, "money": money, "starts": starts, "advice": in_period, "reason": reason,
                       "soc_start_pct": soc0})
    return _fit(out, max_bytes)


def _size(d: dict) -> int:
    return len(json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _fit(out: dict, max_bytes: int) -> dict:
    """The size bound: drop the OLDEST days (stated in `days_dropped`) until the summary fits; the texts are never cut."""
    dropped = 0
    out["days_dropped"] = 0
    while _size(out) > max_bytes and len(out["days"]) > 1:
        out["days"] = out["days"][1:]
        dropped += 1
        out["days_dropped"] = dropped
    return out


def to_entity_payload(feed: Mapping) -> tuple[str, dict]:
    """UNWIRED helper: (state, attributes) a read-only Ghost entity would publish for `feed` (build_ghost_feed's result).

    Nothing calls this: the entity contract (advisory_contract.ENTITY_IDS, the self-test, the frozen fixtures, the card and
    package defaults) lists exactly the eleven integration entities and the integration has no options mechanism, so a twelfth
    entity cannot be added off-by-default without an owner decision. The state is the feed's
    status ("OK" or "INSUFFICIENT_HISTORY"); the attributes are the feed itself plus the SHADOW markers, JSON-safe, one flat
    mapping, and carry no contract_version (they are not part of the frozen contract)."""
    if not isinstance(feed, Mapping) or feed.get("schema") != FEED_SCHEMA:
        raise ValueError("not a ghost feed")
    attrs = {**feed, "mode": "SHADOW", "applies_nothing": True, "kind": "ghost"}
    json.dumps(attrs, allow_nan=False)
    return str(feed["status"]), attrs
