"""Ghost, diagnostics-only: the existing schedule against Intelligence's advice, compactly (read-only; pure: no clock, file,
network, store or write).

THE GHOST IS A SIMULATION. Intelligence controlled nothing: the real battery did what the owner's existing schedule made it do,
and every advice figure is arithmetic on the recorded hourly energies (ghost.py, ghost_feed.py). This module only READS the
feed's own run and lays it out as a comparison; it adds no control authority, no entity and no contract.

    build_ghost_comparison(history, advice_rows, cfg, import_tariff=..., export_tariff=..., now=...) -> a JSON-safe dict
    render_text(block) -> a compact terminal report of such a dict (also read back from a diagnostics download)

The two sides, per local day and for the whole period:
  EXISTING SCHEDULE   what the battery actually did: the real recorded flows.
  INTELLIGENCE ADVICE the same recorded flows with only the advice that was actually logged applied in the simulation.
Differences are advice minus existing; positive money means the advice run is ahead.

What each side shows: (a) money in pence, ONLY with a verified import tariff covering the period (otherwise NO MONEY and the
behaviour only, exactly as ghost_feed); (b) SOC: minimum and end-of-day of both runs and the difference; (c) reserve protection:
the reserve in force, each run's minimum SOC and its margin to it, and whether the advice run would have gone below it (also at
the two altered efficiencies; judged on the hourly mean or end-of-hour SOC against the BASE reserve, so a dip inside an hour, or
below the advice's own higher reserve, can be missed: RESERVE_TEXT, LIMITS); (d) uncertainty and a verdict.

THE VERDICT RULE (derived only from numbers in the feed's run, never from an opinion):
    noise = efficiency spread + closing-stock rule spread + no-advice baseline replay error, summed (not combined in quadrature,
            so deliberately cautious), and never below NOISE_FLOOR_P (the Ghost's own "level day" band, half a penny)
      efficiency spread   the larger change of the advice effect when the round-trip efficiency is moved by 3 points either way
      stock rule spread   the two valuations of the closing stored-energy difference (cost basis, mean import price) differ by it
      baseline error      the no-advice ghost against reality (0 when the recorded flows replay exactly)
    advice effect > noise   ADVICE_AHEAD_BEYOND_NOISE
    advice effect < -noise  ADVICE_BEHIND_BEYOND_NOISE
    otherwise               WITHIN_NOISE   (never read as a win or a loss)
    no followable advice    NO_ADVICE_EFFECT; no verified tariff: NOT_ASSESSED_NO_MONEY (no pence figure exists to judge).
    export price not verified AND the two runs export a different amount (more than EXPORT_DIFF_EPS_KWH): NOT_ASSESSED_EXPORT_UNVERIFIED.
      Export income is counted as 0 in BOTH runs when the export tariff is not verified, so the income the advice run gave up or
      gained by exporting differently is missing from every pence figure and the advice effect can be too high or too low: no
      ahead / behind / within claim is made, and the pence figures stay visible. Where the exports are equal the rule stands.
The same rule is applied per day with that day's own components (and that day's own export difference).

The advice counts: `advice.records_in_period` and `not_followed` are LOG ROWS (the slot cycles log the same advice every hour);
`advice.followed` is the number of DISTINCT (kind, window, target) among the followed rows (ghost_feed).

A failure never raises and never gives a partial figure: a small block with a status and a constant reason code
(INSUFFICIENT_HISTORY, NO_ADVICE_LOGGED, ERROR; the integration adds UNAVAILABLE), no entity id, no site value, no sensor text.
The block is bounded (MAX_BYTES): the oldest days are dropped and the count says so.
"""

from __future__ import annotations

import json
import math
import textwrap
from datetime import datetime
from typing import Mapping, Sequence

from . import ghost_feed
from .config import SiteConfig
from .ghost import LEVEL_BAND_P
from .history import ENERGY_FIELDS, History
from .tariff import TariffResult

SCHEMA = "ecco-intel-ghost-diagnostics/1"
MAX_BYTES = 12288
INTERMEDIATE_BYTES = 1 << 20                  # the feed's own run is never cut before this module has used it
NOISE_FLOOR_P = LEVEL_BAND_P                  # half a penny: the Ghost's "level day" band

OK = "OK"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
NO_ADVICE_LOGGED = "NO_ADVICE_LOGGED"
UNAVAILABLE = "UNAVAILABLE"
ERROR = "ERROR"
STATUSES = (OK, INSUFFICIENT_HISTORY, NO_ADVICE_LOGGED, UNAVAILABLE, ERROR)

R_NO_HISTORY = "NO_HISTORY"
R_NO_24H_RUN = "NO_24H_RUN_OF_USABLE_HOURS"
R_NO_ADVICE = "NO_ADVICE_IN_PERIOD"
R_FEED_EXCEPTION = "FEED_EXCEPTION"
R_SIZE_BOUND = "SIZE_BOUND"
R_OTHER = "OTHER"
FEED_REASONS = {"no_history": R_NO_HISTORY, "no_24h_run_of_usable_hours": R_NO_24H_RUN}
# the reasons the integration adds when it cannot even start the computation (runtime/ghost_link.py, the coordinator)
R_NO_CYCLE = "NO_CYCLE_YET"
R_NO_STATISTICS = "NO_STATISTICS_READ"
R_CONFIG_NOT_DECIDED = "SITE_CONFIG_NOT_DECIDED"
R_ADVICE_LOG = "ADVICE_LOG_UNREADABLE"
R_BUSY = "BUSY"
R_BUDGET = "TIME_BUDGET"
REASONS = (R_NO_HISTORY, R_NO_24H_RUN, R_NO_ADVICE, R_FEED_EXCEPTION, R_SIZE_BOUND, R_OTHER, R_NO_CYCLE, R_NO_STATISTICS,
           R_CONFIG_NOT_DECIDED, R_ADVICE_LOG, R_BUSY, R_BUDGET)

V_AHEAD = "ADVICE_AHEAD_BEYOND_NOISE"
V_BEHIND = "ADVICE_BEHIND_BEYOND_NOISE"
V_WITHIN = "WITHIN_NOISE"
V_NONE = "NO_ADVICE_EFFECT"
V_NO_MONEY = "NOT_ASSESSED_NO_MONEY"
V_NOT_ASSESSED_EXPORT = "NOT_ASSESSED_EXPORT_UNVERIFIED"
VERDICTS = (V_AHEAD, V_BEHIND, V_WITHIN, V_NONE, V_NO_MONEY, V_NOT_ASSESSED_EXPORT)
EXPORT_DIFF_EPS_KWH = 0.001                   # the resolution of the recorded energies: a smaller export difference is arithmetic noise
RESERVE_OK = "NO_BREACH"
RESERVE_BREACH = "BREACH"
RESERVE_SENSITIVE = "BREACH_ONLY_AT_ALTERED_EFFICIENCY"
RESERVE_VERDICTS = (RESERVE_OK, RESERVE_BREACH, RESERVE_SENSITIVE)
RESERVE_BASIS = ("judged on the hourly-mean or end-of-hour SOC against the base reserve (not the advice's own reserve), so a dip "
                 "inside an hour can be missed")
RESERVE_TEXT = {RESERVE_OK: "no hourly SOC of the advice run went below the reserve; " + RESERVE_BASIS,
                RESERVE_BREACH: "the advice run's hourly SOC went below the reserve; " + RESERVE_BASIS,
                RESERVE_SENSITIVE: "below the reserve only at an altered efficiency (+/- 3 points); " + RESERVE_BASIS}

BANNER = ("SIMULATION, read-only. Intelligence controlled nothing; the existing schedule did what it did. The advice run is "
          "arithmetic on recorded hourly data. Evidence for the owner, never a decision.")
BASIS = ("existing = the real recorded flows under the existing schedule; advice = the same flows with only the logged, "
         "followable advice applied in a simulation; differences are advice minus existing (positive money = advice ahead)")
VERDICT_RULE = ("noise = efficiency spread (+/- 3 points) + closing-stock rule spread + no-advice baseline error, summed, at "
                "least 0.5 p; AHEAD or BEHIND only when the advice effect is beyond the noise, otherwise WITHIN_NOISE")
LIMITS = ("hourly data: SOC is an hourly mean and advice windows snap to whole hours",
          "only advice that was actually logged is simulated; dump advice has no logged window and is not simulated",
          "spilled PV is unknown (taken as 0); the real battery's own limits are replayed as recorded",
          "the reserve check judges the hourly-mean or end-of-hour SOC against the base reserve only (not the advice's own reserve), "
          "so a dip below the reserve inside an hour can be missed and the verdict can still read NO_BREACH",
          "money needs a verified import rate table covering the period: it covers only the days the tariff integration "
          "publishes, so a money period can be much shorter than the history",
          "a simulation of one house over a short period: it is evidence, not proof, and decides nothing")
DAY_KEYS = ("date", "hours", "existing_net_p", "advice_net_p", "advice_effect_p", "noise_p", "verdict", "existing_min_soc_pct",
            "advice_min_soc_pct", "min_soc_diff_pct", "existing_end_soc_pct", "advice_end_soc_pct", "end_soc_diff_pct",
            "existing_reserve_margin_pct", "advice_reserve_margin_pct", "advice_breach", "advice_in_force_hours",
            "advice_followed", "advice_not_followed")
SAFE_ERROR_NAME_MAX = 40


def _fin(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _r(x: float | None, nd: int = 2) -> float | None:
    """Rounded; None for a missing or non-finite number; never a negative zero."""
    return None if x is None or not _fin(x) else round(float(x), nd) + 0.0


def _diff(a: float | None, b: float | None, nd: int = 1) -> float | None:
    return None if a is None or b is None else round(float(a) - float(b), nd) + 0.0


def small_block(status: str, reason: str, **extra) -> dict:
    """The block of a failure: a status and a constant reason code, no figure of the comparison."""
    out = {"schema": SCHEMA, "simulated": True, "read_only": True, "intelligence_controlled_nothing": True,
           "banner": BANNER, "status": status, "reason": reason, "money_available": False}
    out.update(extra)
    return out


def error_block(exc: BaseException) -> dict:
    """ERROR / FEED_EXCEPTION with the exception class name only (never its message: it may carry site values)."""
    name = type(exc).__name__
    ok = isinstance(name, str) and 0 < len(name) <= SAFE_ERROR_NAME_MAX and name.replace("_", "").isalnum()
    return small_block(ERROR, R_FEED_EXCEPTION, error_type=name if ok else "UNKNOWN")


def _verdict(effect: float | None, noise: float, in_play: bool) -> str:
    if not in_play:
        return V_NONE
    if effect is None:
        return V_WITHIN
    if effect > noise:
        return V_AHEAD
    if effect < -noise:
        return V_BEHIND
    return V_WITHIN


def _absent_fields(history: object, now: datetime | None) -> list[str]:
    """The hourly fields (the six energies and the SOC) that NO hour of the history carries: the usual cause of a history
    that can never be used (a counter the site file does not map)."""
    try:
        hist = history.truncated(now) if now is not None else history
        recs = list(hist.by_start.values())
        if not recs:
            return []
        absent = [f for f in ENERGY_FIELDS if not any(_fin(r.e.get(f)) for r in recs)]
        if not any(_fin(r.soc_mean) for r in recs):
            absent.append("soc")
        return absent
    except Exception:  # noqa: BLE001 - a hint only; never a reason to fail
        return []


def _insufficient(feed: Mapping, history: object, now: datetime | None) -> dict:
    dq = feed.get("data_quality") or {}
    keep = {k: dq[k] for k in ("window_hours", "usable_hours", "unusable_by_reason", "notes") if k in dq}
    return small_block(INSUFFICIENT_HISTORY, FEED_REASONS.get(feed.get("reason"), R_OTHER), data_quality=keep,
                       history_fields_absent=_absent_fields(history, now))


def _size(d: Mapping) -> int:
    return len(json.dumps(d, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _fit(out: dict, max_bytes: int) -> dict:
    """The size bound: drop the OLDEST days (counted in days_dropped) until the block fits; the summaries are never cut."""
    out["days_dropped"] = 0
    while _size(out) > max_bytes and len(out["days"]) > 1:
        out["days"] = out["days"][1:]
        out["days_dropped"] += 1
    if _size(out) > max_bytes:
        return small_block(ERROR, R_SIZE_BOUND)
    return out


def build_ghost_comparison(history: History, advice_rows: Sequence[Mapping], cfg: SiteConfig, *,
                           import_tariff: TariffResult | None = None, export_tariff: TariffResult | None = None,
                           now: datetime | None = None, days: int = ghost_feed.DEFAULT_DAYS,
                           ha_reserve_pct: float | None = None, max_bytes: int = MAX_BYTES) -> dict:
    """The comparison block (see the module docstring). Never raises: any exception gives the ERROR block with the exception
    class name only."""
    try:
        return _build(history, advice_rows, cfg, import_tariff, export_tariff, now, days, ha_reserve_pct, max_bytes)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never fail the download
        return error_block(exc)


def _build(history, advice_rows, cfg, import_tariff, export_tariff, now, days, ha_reserve_pct, max_bytes) -> dict:
    detail: dict = {}
    feed = ghost_feed.build_ghost_feed(history, advice_rows, cfg, import_tariff=import_tariff, export_tariff=export_tariff,
                                       now=now, days=days, ha_reserve_pct=ha_reserve_pct, max_bytes=INTERMEDIATE_BYTES,
                                       detail=detail)
    if feed.get("status") != ghost_feed.STATUS_OK:
        return _insufficient(feed, history, now)
    adv = feed["advice"]
    dq = feed["data_quality"]
    if adv["records_in_period"] == 0:
        return small_block(NO_ADVICE_LOGGED, R_NO_ADVICE, money_available=bool(feed["money_available"]),
                           period=_period(feed), data_quality={k: dq[k] for k in ("period_hours", "advice_rows_invalid", "notes")
                                                               if k in dq})
    rep, sens, money = detail["rep"], detail["sens"], bool(detail["money"])
    tot = rep["totals"]
    ready = rep["ready_for_assisted_evidence"]
    reserve_pct = float(ready["reserve_pct"])
    followed_n = int(adv["followed"])
    fdays = {d["date"]: d for d in feed["days"]}
    sdays = {tag: {d["date"]: d for d in r["days"]} for tag, (_e, r) in sens.items()}
    breach_dates = set(ready["ghost_below_reserve_dates"])

    export_unverified = money and feed["tariff"]["export"] != ghost_feed.TARIFF_VERIFIED_LABEL
    rows, counts = [], {V_AHEAD: 0, V_BEHIND: 0, V_WITHIN: 0, V_NONE: 0, V_NO_MONEY: 0, V_NOT_ASSESSED_EXPORT: 0}
    for d in rep["days"]:
        fd = fdays.get(d["date"], {})
        a_min, g_min = d["actual_min_soc_pct"], d["ghost_min_soc_pct"]
        a_end, g_end = d["actual_end_soc_pct"], d["ghost_end_soc_pct"]
        row = {"date": d["date"]}
        if d["slots"] != 24:
            row["hours"] = d["slots"]
        if money:
            eff = d["advice_effect_p"]
            e_sp = max(abs(sdays[t][d["date"]]["advice_effect_p"] - eff) for t in ("minus", "plus"))
            s_sp = abs(d["stock_adjustment_cost_basis_rule_p"] - d["stock_adjustment_mean_import_rule_p"])
            noise = max(NOISE_FLOOR_P, e_sp + s_sp + abs(d["model_baseline_delta_p"]))
            in_play = d["advice_in_force_slots"] > 0 or abs(eff) > 1e-9
            v = _verdict(eff, noise, in_play)
            if export_unverified and abs(d["extra_export_kwh_in_ghost"]) > EXPORT_DIFF_EPS_KWH:
                v = V_NOT_ASSESSED_EXPORT          # the export income of this day's different export is unpriced (0 in both runs)
            row.update({"existing_net_p": _r(d["actual_net_before_wear_p"]), "advice_net_p": _r(d["ghost_net_before_wear_p"]),
                        "advice_effect_p": _r(eff), "noise_p": _r(noise), "verdict": v})
        else:
            v = V_NO_MONEY
        counts[v] += 1
        row.update({"existing_min_soc_pct": _r(a_min, 1), "advice_min_soc_pct": _r(g_min, 1), "min_soc_diff_pct": _diff(g_min, a_min),
                    "existing_end_soc_pct": _r(a_end, 1), "advice_end_soc_pct": _r(g_end, 1), "end_soc_diff_pct": _diff(g_end, a_end),
                    "existing_reserve_margin_pct": _diff(a_min, reserve_pct), "advice_reserve_margin_pct": _diff(g_min, reserve_pct),
                    "advice_breach": d["date"] in breach_dates, "advice_in_force_hours": fd.get("advice_in_force_hours", 0),
                    "advice_followed": fd.get("advice_followed", 0)})
        if fd.get("advice_not_followed"):
            row["advice_not_followed"] = fd["advice_not_followed"]
        rows.append(row)

    last = rep["days"][-1]
    totals = {"existing_min_soc_pct": _r(tot["actual_min_soc_pct"], 1), "advice_min_soc_pct": _r(tot["ghost_min_soc_pct"], 1),
              "min_soc_diff_pct": _diff(tot["ghost_min_soc_pct"], tot["actual_min_soc_pct"]),
              "existing_end_soc_pct": _r(last["actual_end_soc_pct"], 1), "advice_end_soc_pct": _r(last["ghost_end_soc_pct"], 1),
              "end_soc_diff_pct": _diff(last["ghost_end_soc_pct"], last["actual_end_soc_pct"]),
              "closing_stored_difference_kwh": _r(tot["closing_stored_difference_kwh"]),
              "extra_import_kwh_in_advice_run": _r(sum(d["extra_import_kwh_in_ghost"] for d in rep["days"])),
              "existing_throughput_kwh": _r(tot["actual_throughput_kwh"]), "advice_throughput_kwh": _r(tot["ghost_throughput_kwh"])}

    eff_pct = feed["uncertainty"]["round_trip_efficiency_pct"]
    unc = {"rule": VERDICT_RULE, "closing_stock_rules": ghost_feed.STOCK_RULES, "round_trip_efficiency_pct": eff_pct}
    if money:
        base = tot["advice_effect_p"]
        eff_m, eff_p = (sens[t][1]["totals"]["advice_effect_p"] for t in ("minus", "plus"))
        e_sp = max(abs(eff_m - base), abs(eff_p - base))
        s_sp = abs(tot["stock_adjustment_cost_basis_rule_p"] - tot["stock_adjustment_mean_import_rule_p"])
        b_err = abs(tot["model_baseline_delta_p"])
        noise = max(NOISE_FLOOR_P, e_sp + s_sp + b_err)
        verdict = _verdict(base, noise, followed_n > 0)
        if export_unverified and sum(abs(d["extra_export_kwh_in_ghost"]) for d in rep["days"]) > EXPORT_DIFF_EPS_KWH:
            verdict = V_NOT_ASSESSED_EXPORT        # unpriced export income that differs between the runs: no claim either way
        totals.update({"existing_net_p": _r(tot["actual"]["net_before_wear_p"]), "advice_net_p": _r(tot["ghost"]["net_before_wear_p"]),
                       "realised_difference_p": _r(tot["delta_realised_p"]), "stock_adjustment_p": _r(tot["stock_adjustment_p"]),
                       "stock_adjusted_difference_p": _r(tot["delta_headline_p"]), "baseline_p": _r(tot["model_baseline_delta_p"]),
                       "advice_effect_p": _r(base)})
        unc.update({"advice_effect_p": _r(base), "noise_p": _r(noise), "noise_floor_p": NOISE_FLOOR_P,
                    "components_p": {"efficiency_spread": _r(e_sp), "stock_rule_spread": _r(s_sp), "baseline_error": _r(b_err)},
                    "effect_at_efficiency_p": {"minus": _r(eff_m), "base": _r(base), "plus": _r(eff_p)},
                    "stock_adjustment_by_rule_p": {"cost_basis": _r(tot["stock_adjustment_cost_basis_rule_p"]),
                                                   "mean_import_price": _r(tot["stock_adjustment_mean_import_rule_p"])},
                    "basis": "net before wear (wear price unknown), stock-adjusted"})
    else:
        verdict = V_NO_MONEY
    unc["verdict"] = verdict
    unc["days"] = {"ahead_beyond_noise": counts[V_AHEAD], "behind_beyond_noise": counts[V_BEHIND], "within_noise": counts[V_WITHIN],
                   "no_advice_effect": counts[V_NONE], "not_assessed": counts[V_NO_MONEY] + counts[V_NOT_ASSESSED_EXPORT]}
    unc["data_quality_flags"] = dq.get("ghost_model_flags", [])

    breach = {t: int(sens[t][1]["ready_for_assisted_evidence"]["ghost_below_reserve_slots"]) for t in ("minus", "plus")}
    base_breach = int(ready["ghost_below_reserve_slots"])
    if base_breach > 0:
        rv = RESERVE_BREACH
    elif breach["minus"] > 0 or breach["plus"] > 0:
        rv = RESERVE_SENSITIVE
    else:
        rv = RESERVE_OK
    recorded = [a.effective_reserve_pct for a in detail["advice"] if a.effective_reserve_pct is not None and detail["reason"](a) is None]
    reserve = {"in_force_pct": _r(reserve_pct, 1), "advice_recorded_max_pct": _r(max(recorded), 1) if recorded else None,
               "existing_min_soc_pct": _r(tot["actual_min_soc_pct"], 1), "advice_min_soc_pct": _r(tot["ghost_min_soc_pct"], 1),
               "existing_margin_pct": _diff(tot["actual_min_soc_pct"], reserve_pct),
               "advice_margin_pct": _diff(tot["ghost_min_soc_pct"], reserve_pct),
               "existing_below_reserve_slots": int(tot["actual_below_reserve_slots"]), "advice_below_reserve_slots": base_breach,
               "advice_below_reserve_days": int(ready["ghost_below_reserve_days"]),
               "advice_below_reserve_dates": list(ready["ghost_below_reserve_dates"]),
               "advice_would_breach": base_breach > 0,
               "advice_below_reserve_slots_at_efficiency": {"minus": breach["minus"], "base": base_breach, "plus": breach["plus"]},
               "verdict": rv}
    adv_out = {"records_in_period": adv["records_in_period"], "followed": followed_n, "not_followed": adv["not_followed"]}
    out = {"schema": SCHEMA, "simulated": True, "read_only": True, "intelligence_controlled_nothing": True, "banner": BANNER,
           "basis": BASIS, "status": OK, "reason": None, "money_available": money, "tariff": feed["tariff"],
           "period": _period(feed), "advice": adv_out, "totals": totals, "reserve": reserve, "uncertainty": unc, "days": rows,
           "data_quality": dq, "limits": list(LIMITS)}
    return _fit(out, max_bytes)


def _period(feed: Mapping) -> dict:
    p = feed["period"]
    return {"start": p["start"], "end": p["end"], "hours": p["hours"], "slot_minutes": p["slot_minutes"],
            "longest_usable_run_hours": p["longest_usable_run_hours"], "soc_start_pct": p["soc_start_pct"]}


# ---------------------------------------------------------------------------------------------------------------------
# the terminal report (also used by tools/ghost_diag_report.py on a downloaded block)
# ---------------------------------------------------------------------------------------------------------------------

def _f(x: object, w: int = 8, nd: int = 1, sign: bool = False) -> str:
    if not _fin(x):
        return "-".rjust(w)
    return format(float(x), f"{'+' if sign else ''}.{nd}f").rjust(w)


def _pair(a: object, b: object, w: int, sign: bool = False) -> str:
    """'existing/advice' of two numbers, whole units, in a field of width w."""
    fa, fb = (_f(v, 0, 0, sign).strip() for v in (a, b))
    return f"{fa}/{fb}".rjust(w)


VERDICT_TEXT = {V_AHEAD: "advice ahead, beyond the noise", V_BEHIND: "advice behind, beyond the noise",
                V_WITHIN: "within the noise: not a win, not a loss", V_NONE: "no advice was followed: the advice run equals the "
                "existing schedule", V_NO_MONEY: "not assessed: no money without a verified tariff",
                V_NOT_ASSESSED_EXPORT: "not assessed: the export price is not verified (export income counted as 0 in both runs) "
                "and the advice run exports a different amount, so the income it gave up or gained is missing from the pence "
                "figures"}
NOT_FOLLOWED_TEXT = {"BLOCKED": "the advice was BLOCKED (it carried no number)",
                     "FALLBACK_EXCLUDED": "a conservative fallback target (INSUFFICIENT_DATA), not followed by default",
                     "NO_WINDOW": "no window was logged (dump advice), so it cannot be simulated",
                     "NO_TARGET": "no target was logged", "NOT_ADVISABLE": "the dump was not advisable",
                     "WINDOW_SHORTER_THAN_SLOT": "its window is shorter than half an hour slot"}
WIDTH = 110


def _wrap(text: str, first: str = "", rest: str = "  ") -> list[str]:
    return textwrap.wrap(text, width=WIDTH, initial_indent=first, subsequent_indent=rest) or [first.rstrip()]


def _hhmm(iso: object) -> str:
    return str(iso)[:16].replace("T", " ") if isinstance(iso, str) else "?"


def render_text(block: Mapping) -> str:
    """A compact plain-text report of a comparison block (any status)."""
    if not isinstance(block, Mapping) or block.get("schema") != SCHEMA:
        raise ValueError("not a ghost diagnostics block")
    L = ["ECCO Intelligence - Ghost diagnostics (SIMULATION, read-only)"] + _wrap(str(block.get("banner", BANNER)), "", "")
    st, rs = block.get("status"), block.get("reason")
    if st != OK:
        L.append(f"Status: {st}" + (f" ({rs})" if rs else ""))
        if block.get("error_type"):
            L.append(f"  exception class: {block['error_type']}")
        if block.get("history_fields_absent"):
            L.append("  hourly fields no hour of the history carries: " + ", ".join(block["history_fields_absent"]))
        if isinstance(block.get("period"), Mapping):
            p = block["period"]
            L.append(f"  period {_hhmm(p.get('start'))} to {_hhmm(p.get('end'))} ({p.get('hours')} h)")
        dq = block.get("data_quality")
        if isinstance(dq, Mapping):
            bits = [f"{k} {dq[k]}" for k in ("window_hours", "usable_hours", "period_hours", "advice_rows_invalid") if k in dq]
            if dq.get("unusable_by_reason"):
                bits.append("unusable " + ", ".join(f"{k} {v}" for k, v in sorted(dq["unusable_by_reason"].items())))
            if bits:
                L.append("  data: " + "; ".join(bits))
            for n in dq.get("notes", []) or []:
                L += _wrap("note: " + str(n), "  ", "    ")
        L.append("No comparison is shown: nothing is guessed.")
        return "\n".join(L)
    money = bool(block.get("money_available"))
    p, a, t, rv, u = block["period"], block["advice"], block["totals"], block["reserve"], block["uncertainty"]
    L.append(f"Period {_hhmm(p['start'])} to {_hhmm(p['end'])} ({p['hours']} h). Tariff: import {block['tariff']['import']}, "
             f"export {block['tariff']['export']}")
    nf = ", ".join(f"{k} x{v}" for k, v in sorted(a["not_followed"].items())) or "none"
    L += _wrap(f"Advice log rows in the period: {a['records_in_period']} (one per kind per slot cycle); followed in the simulation: "
               f"{a['followed']} distinct advice (kind, window, target); rows not followed: {nf}", "", "  ")
    for code in sorted(a["not_followed"]):
        L.append(f"  {code}: {NOT_FOLLOWED_TEXT.get(code, 'not followed')}")
    L += _wrap("EXISTING SCHEDULE = what the battery really did.  INTELLIGENCE ADVICE = the same flows with the logged advice "
               "applied (simulated).", "", "")
    L.append("")
    L.append("WHOLE PERIOD")
    if money:
        L.append("  Money (pence, before wear; + = advice ahead):")
        L.append(f"    existing {_f(t['existing_net_p'], 0, 1, True)}   advice {_f(t['advice_net_p'], 0, 1, True)}   realised diff "
                 f"{_f(t['realised_difference_p'], 0, 1, True)}   stock adjustment {_f(t['stock_adjustment_p'], 0, 1, True)}   "
                 f"baseline {_f(t['baseline_p'], 0, 1, True)}")
        L.append(f"  ADVICE EFFECT {_f(t['advice_effect_p'], 0, 1, True)} p; noise +/-{_f(u['noise_p'], 0, 1)} p (efficiency "
                 f"{_f(u['components_p']['efficiency_spread'], 0, 1)} + stock rules {_f(u['components_p']['stock_rule_spread'], 0, 1)}"
                 f" + baseline {_f(u['components_p']['baseline_error'], 0, 1)}; floor {_f(u['noise_floor_p'], 0, 1)})")
    else:
        L.append("  Money: NO MONEY - no verified import tariff covers the period, so no pence figure exists. Behaviour only.")
    L += _wrap(f"VERDICT: {u['verdict']} ({VERDICT_TEXT.get(u['verdict'], '')})", "  ", "    ")
    L.append(f"  SOC %: minimum existing {_f(t['existing_min_soc_pct'], 0)}, advice {_f(t['advice_min_soc_pct'], 0)} "
             f"({_f(t['min_soc_diff_pct'], 0, 1, True)}); end of the last day existing {_f(t['existing_end_soc_pct'], 0)}, advice "
             f"{_f(t['advice_end_soc_pct'], 0)} ({_f(t['end_soc_diff_pct'], 0, 1, True)})")
    L.append(f"         closing stored energy, advice minus existing: {_f(t['closing_stored_difference_kwh'], 0, 2, True)} kWh")
    L.append(f"  RESERVE {_f(rv['in_force_pct'], 0)} %: margin to it: existing {_f(rv['existing_margin_pct'], 0, 1, True)}, advice "
             f"{_f(rv['advice_margin_pct'], 0, 1, True)}; VERDICT {rv['verdict']}")
    L.append(f"           advice below the reserve: {rv['advice_below_reserve_slots']} slot(s) on {rv['advice_below_reserve_days']} "
             f"day(s); at efficiency -3/+3 points: {rv['advice_below_reserve_slots_at_efficiency']['minus']}/"
             f"{rv['advice_below_reserve_slots_at_efficiency']['plus']}")
    L.append(f"           existing schedule below the reserve: {rv['existing_below_reserve_slots']} slot(s)")
    L += _wrap(f"{rv['verdict']}: {RESERVE_TEXT.get(rv['verdict'], '')}", "           ", "             ")
    d = u["days"]
    L.append(f"  Days: {d['ahead_beyond_noise']} ahead beyond noise, {d['behind_beyond_noise']} behind beyond noise, "
             f"{d['within_noise']} within noise, {d['no_advice_effect']} with no advice effect"
             + (f", {d['not_assessed']} not assessed" if money and d.get("not_assessed") else ""))
    L.append("")
    L.append("PER DAY (existing / advice)")
    if money:
        L.append("  date        existing p  advice p  effect p   noise  verdict       SOC min  SOC end   margin  breach  adv f/n")
    else:
        L.append("  date        SOC min  SOC end   margin  breach  adv f/n")
    for r in block["days"]:
        soc = (f"{_pair(r['existing_min_soc_pct'], r['advice_min_soc_pct'], 7)}  "
               f"{_pair(r['existing_end_soc_pct'], r['advice_end_soc_pct'], 7)}  "
               f"{_pair(r['existing_reserve_margin_pct'], r['advice_reserve_margin_pct'], 7, True)}  "
               f"{'BREACH' if r['advice_breach'] else '-':<6}  "
               f"{r['advice_followed']}/{sum((r.get('advice_not_followed') or {}).values())}")
        if money:
            v = {V_AHEAD: "ahead", V_BEHIND: "behind", V_WITHIN: "within noise", V_NONE: "no effect",
                 V_NOT_ASSESSED_EXPORT: "not assessed"}.get(r["verdict"], r["verdict"])
            L.append(f"  {r['date']}  {_f(r['existing_net_p'], 10)}  {_f(r['advice_net_p'], 8)}  "
                     f"{_f(r['advice_effect_p'], 8, 1, True)}  {_f(r['noise_p'], 6)}  {v:<12}  {soc}")
        else:
            L.append(f"  {r['date']}  {soc}")
    if block.get("days_dropped"):
        L.append(f"  ({block['days_dropped']} older day(s) left out to keep the block small)")
    dq = block.get("data_quality", {})
    L.append("")
    L.append(f"Data: {dq.get('usable_hours', '?')} usable of {dq.get('window_hours', '?')} hours in the window; "
             f"{dq.get('hours_with_repaired_or_flagged_energy', 0)} repaired/flagged; flags: "
             f"{', '.join(u.get('data_quality_flags') or []) or 'none'}")
    for n in dq.get("notes", []) or []:
        L += _wrap("note: " + str(n), "  ", "    ")
    L += _wrap("Closing stock: " + str(u["closing_stock_rules"]), "", "  ")
    L.append("Limits:")
    for lim in block.get("limits", []):
        L += _wrap(str(lim), "  - ", "    ")
    L.append("Read-only simulation. Nothing was changed, deployed or controlled.")
    return "\n".join(L)
