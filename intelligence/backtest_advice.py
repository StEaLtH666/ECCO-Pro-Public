"""Leak-free walk-forward backtest of the SHADOW cycle's advice (planning stream). SYNTHETIC campaigns only: every
figure it produces is labelled SYNTHETIC and is never a real-data accuracy claim.

For each issue day the cycle (shadow_cycle.run_cycle) is run at ISSUE_LOCAL_MIN local time on `History.truncated(t)` with
inputs built the way the shared test fixtures build them (every reading fresh and consistent, observed shortly before
t); nothing the cycle sees is later than t except the day-ahead PV forecast as issued that day. The advice is then
scored against the campaign's own (synthetic) future:

  * forecast accuracy: predicted_day_load and pv_tomorrow against the next local day's actual energy (MAE and the share
    inside p10..p90), predicted_morning_soc against the replayed SOC at its anchor time;
  * reserve violations: a FEASIBLE OK charge target (binding constraint not MAX_SOC / CHARGE_WINDOW, which state that the
    reserve may be reached) whose replay on the actual load and PV goes below the effective reserve after the window,
    and an OK Dump-to-Grid advice whose export, replayed, takes the battery below it before the refill. The acceptance
    metric counts FEASIBLE OK advice only: an OK target with a stated shortfall that reaches the reserve is counted
    separately (stated_shortfall_reached_reserve) and is always reported next to it;
  * conservative energy regret: the import of the advice minus the import of each baseline, replayed on the same actual
    load and PV by the one energy account (baselines.replay); positive = the advice imported more. The baselines are
    baselines.baselines() on the judgement the cycle itself made at t (shadow_cycle.judged_reading), so the backtest
    compares with exactly the baselines the cycle could have shown;
  * GBP regret only when the campaign's tariff verified (VERIFIED_FROM_INTEGRATION) at the issue time; otherwise None
    with the reason.

Pure: no clock read, no file or network access; deterministic for a given campaign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Mapping

from ecco_core.state import NORMALIZED, RAW, Observation, Snapshot

from . import stats
from .advisory_contract import CycleInputs, ItemStatus, OutcomeMetrics, SiteFacts, SiteReading, SITE_READING_KEYS, Versions
from .baselines import baselines as make_baselines, cost_p, replay
from .config import SiteConfig
from .explain import finite_number
from .history import History
from .inputs import live_inputs_from_snapshot
from .shadow_cycle import judged_reading, run_cycle
from .site_decisions import DEFAULT_ACCEPT_PROVENANCE, DecisionSet, InputState, freshness_limits
from .tariff import VERIFIED_FROM_INTEGRATION, assess_rates
from .timeutil import HOUR, day_bounds, local_date, local_wall, ts, utc_from_ts, zone

BACKTEST_VERSION = "intel-backtest-advice-0.1.0"
LABEL = "SYNTHETIC"
ISSUE_LOCAL_MIN = 21 * 60 + 30          # 21:30 local: the evening issue time
POLL_AGE_S = 20.0                       # the dongle poll text changed this long before the issue time
CONFIG_POLL_AGE_S = 30.0                # the configuration-poll text changed this long before it (the shared fixture)
READING_AGE_S = 120.0                   # other readings were observed this long before it
PV_FORECAST_AGE_S = 7200.0              # the day-ahead PV forecast was issued this long before it (same local date)
# per-reading observation ages, as the shared test fixtures give them (supervision is recent; preferences older)
READING_AGES_S = {"supervision.state": 30.0, "supervision.stable": 30.0, "supervision.heartbeat_age_s": 30.0,
                  "pref.wear_cost_p_per_kwh": 3600.0, "pref.normal_max_charge_target_pct": 3600.0}
ADVISORY_SIGNALS = ("battery.soc", "inverter.healthy", "house.power", "pv.power", "reserve.ha_minimum_soc")


@dataclass(frozen=True)
class Campaign:
    """A synthetic campaign: the full synthetic truth and everything the cycle is given at each issue time."""
    history: History                                    # hourly load, PV and SOC: the synthetic truth
    base_cfg: SiteConfig                                # site facts only (the cycle replaces every battery field)
    facts: SiteFacts
    decisions: DecisionSet
    readings: Mapping[str, object]                      # static reading values (key -> value), as the fixtures give
    pv_forecasts: Mapping[str, Mapping[date, float]]    # {source: {local date: day-ahead kWh as issued}}
    import_payload: Callable[[datetime], object] | None = None   # the import rates payload as published at t
    export_payload: Callable[[datetime], object] | None = None
    events_payload: Callable[[datetime], object] | None = None
    accept_provenance: frozenset = field(default=DEFAULT_ACCEPT_PROVENANCE, kw_only=True)
    label: str = LABEL

    def __post_init__(self) -> None:
        if self.label != LABEL:
            raise ValueError("a backtest campaign is SYNTHETIC only")


def issue_time(c: Campaign, day: date) -> datetime:
    return local_wall(day, ISSUE_LOCAL_MIN, zone(c.facts.tz))


def _last_hour(hist: History) -> object:
    return hist.by_start[max(hist.by_start)] if len(hist) else None


def inputs_at(c: Campaign, t: datetime, history: History | None = None) -> CycleInputs:
    """The cycle inputs at issue time t, from the campaign's truth truncated at t (or from `history`, for the leak test:
    only its hours before t are ever used)."""
    tz = zone(c.facts.tz)
    hist = (history if history is not None else c.history).truncated(t)
    last = _last_hour(hist)
    poll_at = t - timedelta(seconds=POLL_AGE_S)
    soc = getattr(last, "soc_mean", None)
    house = getattr(last, "load_w_mean", None) if last is not None else None
    pvw = getattr(last, "pv_w_mean", None) if last is not None else None
    # a balanced snapshot (house = PV + battery + grid, battery idle): the last hour's means, nothing later than t
    grid = None if not (finite_number(house) and finite_number(pvw)) else float(house) - float(pvw)
    sig = {"battery.soc": soc if finite_number(soc) else None, "battery.power": 0.0 if grid is not None else None,
           "grid.power": grid, "house.power": house, "pv.power": pvw, "inverter.healthy": True}
    obs = []
    for name, v in sig.items():
        if v is None:
            continue
        obs.append(Observation(name, v, poll_at, f"synthetic:{name}", RAW if name != "inverter.healthy" else NORMALIZED))
    if last is not None:
        obs.append(Observation("history.hourly", True, utc_from_ts(last.start + HOUR), "synthetic:history", NORMALIZED))
    snap = Snapshot.of(t, obs)
    today = local_date(t, tz)
    readings = []
    for key in sorted(SITE_READING_KEYS):
        if key in ("liveness.dongle_poll_changed_at", "liveness.config_poll_changed_at"):
            at = poll_at if key == "liveness.dongle_poll_changed_at" else t - timedelta(seconds=CONFIG_POLL_AGE_S)
            readings.append(SiteReading(key, at, SITE_READING_KEYS[key], at, f"synthetic:{key}"))
            continue
        if key in ("pv.forecast_today_kwh", "pv.forecast_tomorrow_kwh"):
            d = today if key.endswith("today_kwh") else today + timedelta(days=1)
            src = next(iter(sorted(c.pv_forecasts)), None)
            v = None if src is None else c.pv_forecasts[src].get(d)
            at = t - timedelta(seconds=min(PV_FORECAST_AGE_S, (t - local_wall(today, 0, tz)).total_seconds() / 2))
        elif key == "tariff.import_rates":
            v, at = (c.import_payload(t) if c.import_payload else c.readings.get(key)), t - timedelta(seconds=READING_AGE_S)
        elif key == "tariff.export_rates":
            v, at = (c.export_payload(t) if c.export_payload else c.readings.get(key)), t - timedelta(seconds=READING_AGE_S)
        elif key == "tariff.events":
            v, at = (c.events_payload(t) if c.events_payload else c.readings.get(key)), t - timedelta(seconds=READING_AGE_S)
        elif key == "battery.soc_raw_pct":
            v, at = (float(soc) if finite_number(soc) else None), poll_at        # the raw SOC agrees with the SOC
        else:
            v = c.readings.get(key)
            at = t - timedelta(seconds=READING_AGES_S.get(key, READING_AGE_S))
        if v is None:
            continue
        readings.append(SiteReading(key, v, SITE_READING_KEYS[key], at, f"synthetic:{key}"))
    limits, _ = freshness_limits(c.decisions, c.accept_provenance)
    caller = []
    for name in ADVISORY_SIGNALS:
        o = snap.get(name)
        age = None if o is None else o.age_s(t)
        lim = limits.get(name)
        caller.append((name, bool(o is not None and o.value is not None and age is not None and lim is not None
                                  and age <= lim), age))
    pvh = {s: {d: v for d, v in series.items() if d < today} for s, series in sorted(c.pv_forecasts.items())}
    return CycleInputs(now=t, snapshot=snap, live=live_inputs_from_snapshot(snap), caller_assessments=tuple(caller),
                       history=hist, pv_forecast_history=pvh, base_cfg=c.base_cfg, site_facts=c.facts,
                       decisions=c.decisions, accept_provenance=c.accept_provenance, site_readings=tuple(readings),
                       outcome_metrics=OutcomeMetrics(), paused=False, previous=None,
                       versions=Versions("backtest", BACKTEST_VERSION, None, None))


def _actual_fn(hist: History, fieldname: str) -> Callable[[datetime], float]:
    def fn(h0: datetime) -> float:
        r = hist.get(ts(h0))
        v = None if r is None else r.e.get(fieldname)
        return float(v) if finite_number(v) and v >= 0 else 0.0
    return fn


def _complete(hist: History, a: datetime, b: datetime) -> bool:
    s = ts(a) - ts(a) % HOUR
    while s < ts(b):
        r = hist.get(s)
        if r is None or "load" not in r.e or "pv" not in r.e:
            return False
        s += HOUR
    return True


def _replay_cfg(c: Campaign, summary: Mapping) -> tuple[SiteConfig, float] | None:
    """The battery configuration the advice used (its own inputs_used), the grid-charge limit from the campaign reading,
    and the effective reserve: nothing that was not known at the issue time."""
    used = summary.get("inputs_used") or {}
    cap, eta = used.get("battery_capacity_kwh"), used.get("eta_one_way")
    gw = c.readings.get("limits.max_grid_charge_w")
    floor = summary.get("effective_reserve_pct")
    if not all(finite_number(x) and x > 0 for x in (cap, eta, gw)) or not finite_number(floor):
        return None
    tech = (summary.get("reserve") or {}).get("technical_min_pct")
    try:
        cfg = SiteConfig(tz=c.facts.tz, battery_capacity_kwh=float(cap), round_trip_efficiency=min(1.0, float(eta) ** 2),
                         max_grid_charge_kw=float(gw) / 1000.0, user_reserve_soc_pct=float(floor),
                         technical_min_soc_pct=float(tech) if finite_number(tech) else 0.0)
    except ValueError:
        return None
    return cfg, float(floor)


def _band(fv) -> tuple[float, float, float] | None:
    if fv.status != ItemStatus.OK or not all(finite_number(x) for x in (fv.p10, fv.value, fv.p90)):
        return None
    return float(fv.p10), float(fv.value), float(fv.p90)


def evaluate(c: Campaign, t: datetime, env, inputs: CycleInputs | None = None) -> dict:
    """One issue time scored against the campaign's future (see the module docstring). `inputs`: the cycle inputs the
    envelope was computed from (rebuilt with inputs_at when not given); the baselines rest on the cycle's judgement of
    them, exactly as in the cycle."""
    tz = zone(c.facts.tz)
    today = local_date(t, tz)
    tomorrow = today + timedelta(days=1)
    row: dict = {"issued": t.isoformat(), "status": env.status, "label": LABEL,
                 "charge_target": env.item("charge_target").status}
    t0, t1 = day_bounds(tomorrow, tz)
    for key, fieldname in (("predicted_day_load", "load"), ("pv_tomorrow", "pv")):
        b = _band(env.item(key))
        actual = c.history.energy_scaled(fieldname, t0, t1, 0.9)
        row[key] = None if b is None or actual is None else {"p10": b[0], "p50": b[1], "p90": b[2], "actual": round(actual, 3),
                                                             "error": round(actual - b[1], 3), "inside": b[0] <= actual <= b[2]}
    ct = env.item("charge_target")
    row["morning_soc"] = row["reserve"] = None
    row["dump"] = _score_dump(c, t, env)
    row["energy"] = {}
    row["gbp"] = None
    if ct.status != ItemStatus.OK or ct.summary is None:
        return row
    summ = dict(ct.summary)
    rc = _replay_cfg(c, summ)
    w = summ.get("window") or []
    if rc is None or len(w) != 2:
        return row
    cfg, floor = rc
    w0, w1 = datetime.fromisoformat(w[0]), datetime.fromisoformat(w[1])
    lw0 = w0.astimezone(tz)
    start_min = lw0.hour * 60 + lw0.minute
    horizon = local_wall(local_date(w1, tz), start_min, tz)
    if horizon <= w1:
        horizon = local_wall(local_date(w1, tz) + timedelta(days=1), start_min, tz)
    if not _complete(c.history, t, horizon):
        return row
    inp_soc = summ.get("window_start_soc_pct")
    soc_t = getattr(_last_hour(c.history.truncated(t)), "soc_mean", None)     # the SOC the cycle was given at t
    if not finite_number(soc_t):
        return row
    soc0 = float(soc_t)
    load, pv = _actual_fn(c.history, "load"), _actual_fn(c.history, "pv")
    target = float(ct.value)
    adv = replay(cfg, floor, target, soc0, t, horizon, (w0, w1), load, pv)
    binding = summ.get("binding_constraint")
    feasible = binding not in ("MAX_SOC", "CHARGE_WINDOW")
    below = adv.min_soc_after_window < floor - 1e-9
    row["reserve"] = {"feasible": feasible, "min_soc_after_window": round(adv.min_soc_after_window, 2), "floor": floor,
                      "violation": bool(feasible and below), "reached_with_stated_shortfall": bool(not feasible and below),
                      "binding": binding, "start_soc_predicted": inp_soc}
    ms = env.item("predicted_morning_soc")
    mb = _band(ms)
    if mb is not None and ms.summary is not None and ms.summary.get("at"):
        at = datetime.fromisoformat(ms.summary["at"])
        actual = adv.soc_at(at)
        if actual is not None:
            row["morning_soc"] = {"p10": mb[0], "p50": mb[1], "p90": mb[2], "actual": round(actual, 2),
                                  "error": round(actual - mb[1], 2), "inside": mb[0] - 1e-9 <= actual <= mb[2] + 1e-9}
    # the ONE baseline definition (baselines.baselines), on the judgement the cycle made at t: HOLD_CURRENT only when the
    # cycle judged the current TOU target fresh, V1_CONFIG_WINDOW only when the cycle published its V1 comparison
    ec = env.engine_comparison
    inp = inputs if inputs is not None else inputs_at(c, t)
    bls, _bn = make_baselines(max_soc_pct=float(cfg.max_soc_pct),
                              tou_current=judged_reading(inp, "tou.current_target_soc_pct"),
                              v1_target_pct=ec.get("v1_target_soc_pct") if isinstance(ec, Mapping) else None,
                              decisions_satisfied=isinstance(ec, Mapping))
    base_targets = {k: b.target_soc_pct for k, b in bls.items()}
    runs = {k: replay(cfg, floor, v, soc0, t, horizon, (w0, w1), load, pv) for k, v in base_targets.items()}
    for k, o in runs.items():
        row["energy"][k] = {"advice_import_kwh": round(adv.import_kwh, 3), "baseline_import_kwh": round(o.import_kwh, 3),
                            "regret_kwh": round(adv.import_kwh - o.import_kwh, 3),
                            "peak_regret_kwh": round(adv.peak_import_kwh - o.peak_import_kwh, 3)}
    verified = isinstance(env.tariff, Mapping) and env.tariff.get("provenance") == VERIFIED_FROM_INTEGRATION
    if verified and c.import_payload is not None:
        imp = _realised(c.import_payload, t, horizon, "import")
        ex = _realised(c.export_payload, t, horizon, "export") if c.export_payload is not None else None
        if imp.verified:
            exp_rate = ex.rate_at if ex is not None and ex.verified else None
            ca = cost_p(adv, imp.rate_at, exp_rate)
            g = {}
            for k, o in runs.items():
                cb = cost_p(o, imp.rate_at, exp_rate)
                if ca is not None and cb is not None:
                    g[k] = round((ca - cb) / 100.0, 2)
            row["gbp"] = g or None
    return row


def _realised(payload: Callable[[datetime], object], t: datetime, horizon: datetime, kind: str):
    """The rates that applied over [t, horizon) (scoring is ex post): the payload published at t joined with the one
    published a day later, judged by the same adapter."""
    rows = []
    for at in (t, t + timedelta(days=1)):
        p = payload(at)
        groups = [p] if isinstance(p, list) else ([p.get(k) for k in ("previous_day", "current_day", "next_day") if k in p]
                                                  if isinstance(p, Mapping) else [])
        for g in groups:
            rs = g.get("rates") if isinstance(g, Mapping) else g
            rows += [r for r in rs or [] if isinstance(r, Mapping)]
    uniq = {(str(r.get("start")), str(r.get("end"))): r for r in rows}
    st = InputState(f"tariff.{kind}_rates", list(uniq.values()), True, READING_AGE_S, 300.0)
    return assess_rates(st, t, kind=kind, need=(t, horizon))


def _score_dump(c: Campaign, t: datetime, env) -> dict | None:
    """An OK Dump-to-Grid advice replayed: its export taken at t, then no grid charge until its refill time, on the actual
    load and PV. A violation is the battery going below the effective reserve before the refill."""
    dv = env.item("dump_to_grid")
    if dv.status != ItemStatus.OK or dv.summary is None:
        return None
    s = dict(dv.summary)
    kwh, floor, refill = s.get("export_kwh"), s.get("effective_reserve_pct"), s.get("refill_at")
    ct = env.item("charge_target")
    rc = _replay_cfg(c, dict(ct.summary)) if ct.status == ItemStatus.OK and ct.summary is not None else None
    soc_t = getattr(_last_hour(c.history.truncated(t)), "soc_mean", None)
    if rc is None or not (finite_number(kwh) and finite_number(floor) and finite_number(soc_t)) or not refill:
        return {"scored": False}
    cfg, _f = rc
    end = datetime.fromisoformat(refill)
    if not _complete(c.history, t, end):
        return {"scored": False}
    drop = float(kwh) / max(1e-9, (cfg.round_trip_efficiency ** 0.5)) / cfg.battery_capacity_kwh * 100.0
    o = replay(cfg, float(floor), None, float(soc_t) - drop, t, end, None, _actual_fn(c.history, "load"),
               _actual_fn(c.history, "pv"))
    return {"scored": True, "export_kwh": float(kwh), "min_soc": round(o.min_soc_unconstrained, 2), "floor": float(floor),
            "violation": bool(o.min_soc_unconstrained < float(floor) - 1e-9)}


def _mae_cov(rows: list[dict], key: str) -> dict:
    xs = [r[key] for r in rows if isinstance(r.get(key), dict)]
    if not xs:
        return {"n": 0, "mae": None, "coverage": None}
    return {"n": len(xs), "mae": round(stats.mae([x["error"] for x in xs]), 3),
            "coverage": round(sum(1 for x in xs if x["inside"]) / len(xs), 3)}


def summarise(rows: list[dict]) -> dict:
    """Aggregate metrics, labelled SYNTHETIC."""
    res = [r["reserve"] for r in rows if isinstance(r.get("reserve"), dict)]
    energy: dict[str, dict] = {}
    for r in rows:
        for k, e in (r.get("energy") or {}).items():
            agg = energy.setdefault(k, {"nights": 0, "advice_import_kwh": 0.0, "baseline_import_kwh": 0.0,
                                        "regret_kwh_total": 0.0, "peak_regret_kwh_total": 0.0, "regret_kwh_max": None})
            agg["nights"] += 1
            agg["advice_import_kwh"] += e["advice_import_kwh"]
            agg["baseline_import_kwh"] += e["baseline_import_kwh"]
            agg["regret_kwh_total"] += e["regret_kwh"]
            agg["peak_regret_kwh_total"] += e["peak_regret_kwh"]
            agg["regret_kwh_max"] = e["regret_kwh"] if agg["regret_kwh_max"] is None else max(agg["regret_kwh_max"], e["regret_kwh"])
    for agg in energy.values():
        for k in ("advice_import_kwh", "baseline_import_kwh", "regret_kwh_total", "peak_regret_kwh_total"):
            agg[k] = round(agg[k], 2)
        agg["regret_kwh_mean"] = round(agg["regret_kwh_total"] / agg["nights"], 3) if agg["nights"] else None
    gbp_rows = [r["gbp"] for r in rows if isinstance(r.get("gbp"), dict)]
    gbp = None
    if gbp_rows:
        gbp = {}
        for g in gbp_rows:
            for k, v in g.items():
                a = gbp.setdefault(k, {"nights": 0, "regret_gbp_total": 0.0})
                a["nights"] += 1
                a["regret_gbp_total"] = round(a["regret_gbp_total"] + v, 2)
    return {"label": LABEL, "version": BACKTEST_VERSION, "issues": len(rows),
            "charge_target_ok": sum(1 for r in rows if r.get("charge_target") == ItemStatus.OK),
            "load_tomorrow": _mae_cov(rows, "predicted_day_load"), "pv_tomorrow": _mae_cov(rows, "pv_tomorrow"),
            "morning_soc": _mae_cov(rows, "morning_soc"),
            "scored_nights": len(res),
            "reserve_violations_ok_advice": sum(1 for x in res if x["violation"]) + sum(
                1 for r in rows if isinstance(r.get("dump"), dict) and r["dump"].get("violation")),
            "charge_target_violations": sum(1 for x in res if x["violation"]),
            "dump_ok_scored": sum(1 for r in rows if isinstance(r.get("dump"), dict) and r["dump"].get("scored")),
            "dump_violations": sum(1 for r in rows if isinstance(r.get("dump"), dict) and r["dump"].get("violation")),
            "feasible_nights": sum(1 for x in res if x["feasible"]),
            "stated_shortfall_nights": sum(1 for x in res if not x["feasible"]),
            "stated_shortfall_reached_reserve": sum(1 for x in res if x["reached_with_stated_shortfall"]),
            "energy_regret": energy,
            "gbp_regret": gbp if gbp is not None else {"status": "NO_VALUE", "reason": "no verified tariff in the campaign"}}


def run_campaign(c: Campaign, days: list[date]) -> dict:
    """Walk forward over `days` (one issue at ISSUE_LOCAL_MIN local each): {summary, rows}. Deterministic."""
    rows = []
    for d in days:
        t = issue_time(c, d)
        inp = inputs_at(c, t)
        rows.append(evaluate(c, t, run_cycle(inp), inp))
    return {"summary": summarise(rows), "rows": rows}
