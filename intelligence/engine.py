"""Shadow intelligence engine: one deterministic `run(inputs)` -> report.

READ -> LEARN -> PREDICT -> RECOMMEND -> (later) SCORE. No I/O, no clock, no
randomness: given the same History, config and LiveInputs it returns the same
report byte for byte (the report carries a feature hash so a stored forecast
can be tied to exactly what produced it).

The report keeps four things visibly apart, because the UI must not blur them:
  actual       what the sensors say now
  predicted    what the model expects, with bands
  recommended  what the shadow advisor would suggest (never applied)
  confidence   how much to trust each
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from . import MODEL_VERSION, stats
from .advisor import LiveInputs, PvDay, Planner, TariffInfo, advise, default_cheap_windows, soc_is_stale
from .anomaly import AnomalyReport, detect, hourly_residuals_today
from .config import SiteConfig
from .history import History
from .pv import UNGATED_KEPT_CODE, PvModel, prefers_ungated, pv_hour_shape, useful_pv_start
from .timeutil import UTC, day_bounds, local_wall, sun_times, ts, zone
from .usage import (NOWCAST_HOURS, UsageForecast, UsageModel, confidence_label, fixed_window, next_hour_forecast,
                    standard_windows, weekday_effect, window_sum, baseline_guard)

OFFSET_DAYS = 14


def _reanchored(p50: float, done_share: float, so_far: float | None) -> tuple[float, tuple[float, float, float] | None]:
    """Today's remaining PV: the not-yet-elapsed share of the day's p50, scaled by how today is actually going (forecast
    re-anchoring). Returns (remaining kWh, (live ratio, weight, factor)), the second None when there is nothing to re-anchor on."""
    rem = p50 * (1.0 - done_share)
    if so_far is not None and p50 * done_share >= 2.0:
        live = max(0.4, min(1.6, so_far / (p50 * done_share)))
        w = min(0.7, done_share / 0.6)
        factor = w * live + (1.0 - w)
        return rem * factor, (live, w, factor)
    return rem, None


def _json_safe(raw: dict) -> dict:
    """A raw forecast map with non-finite / non-numeric values replaced by None, so the feature snapshot stays valid JSON."""
    return {k: (v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None) for k, v in raw.items()}


class IntelligenceEngine:
    def __init__(self, history: History, cfg: SiteConfig, pv_forecast_history: dict[str, dict[date, float]] | None = None):
        self.history = history
        self.cfg = cfg
        self.tz = zone(cfg.tz)
        self.now_ref = datetime.min.replace(tzinfo=UTC)
        self.usage = UsageModel(history, cfg)
        self.pv = PvModel(history, cfg, pv_forecast_history or {})

    # ------------------------------------------------------------------------------------------------------
    def useful_pv_offsets(self, asof: date) -> list[float]:
        """Hours between sunrise and the actual useful-PV start on each of the last OFFSET_DAYS days."""
        out = []
        d = asof - timedelta(days=1)
        while len(out) < OFFSET_DAYS and d >= asof - timedelta(days=OFFSET_DAYS + 14):
            sr, _ss = sun_times(d, self.cfg.latitude, self.cfg.longitude)
            st = useful_pv_start(self.history, self.cfg, d)
            if sr is not None and st is not None and st > sr:
                out.append((st - sr).total_seconds() / 3600.0)
            d -= timedelta(days=1)
        return list(reversed(out))

    def predicted_useful_pv(self, day: date, asof: date) -> tuple[datetime | None, datetime | None, datetime | None]:
        """(p50, early p10, late p90) useful-PV start for `day` from sunrise + learned offsets."""
        sr, _ = sun_times(day, self.cfg.latitude, self.cfg.longitude)
        if sr is None:
            return None, None, None
        offs = self.useful_pv_offsets(asof)
        if len(offs) < 5:
            offs = [2.5] * 5
        return (sr + timedelta(hours=stats.median(offs)), sr + timedelta(hours=stats.quantile(offs, 0.10)),
                sr + timedelta(hours=stats.quantile(offs, 0.90)))

    # ------------------------------------------------------------------------------------------------------
    def _pv_days(self, inp: LiveInputs, asof: date, horizon_end: datetime, notes: list[str], plan: dict | None = None
                 ) -> tuple[dict[date, PvDay], dict]:
        """The PV days the Planner sizes on, and the PUBLISHED per-day forecasts (`info`, unchanged by the skill gate's planning
        rule). The PvDay holds `fc.planning_band`: the published band, or after a gate fallback the planning band (never above
        persistence or the ungated corrected band, the ungated spread kept; `pv.conservative_band`), so the gate can raise a target, not
        lower it. `plan`, when given, collects {"inflation": [...], "fallbacks": [...]} for the engine's confidence cap and reason codes
        and {"ungated": {"days", "inflation", "confidence"}}: the PV days, band inflations and confidences EXACTLY as the gate-OFF engine
        would have built them (the guard in `run` computes the advice a second time on them)."""
        out: dict[date, PvDay] = {}
        info: dict = {}
        ung = plan.setdefault("ungated", {"days": {}, "inflation": [], "confidence": []}) if plan is not None else None
        now = inp.now
        d = asof
        while d <= horizon_end.astimezone(self.tz).date():
            raw = inp.pv_raw_today if d == asof else (inp.pv_raw_tomorrow if d == asof + timedelta(days=1) else {})
            if not raw:
                if d <= asof + timedelta(days=1):
                    notes.append(f"no PV forecast available for {d.isoformat()}: assuming persistence")
                fc = self.pv.forecast_day(d, {}) if d <= asof + timedelta(days=1) else None
            else:
                fc = self.pv.forecast_day(d, raw)
            if fc is None:
                d += timedelta(days=1)
                continue
            shape = pv_hour_shape(self.history, self.cfg, asof)
            gf = fc.gate_fallback
            p10, p50, p90 = fc.planning_band
            pvd = PvDay(d, p10, p50, p90, shape)
            # what the gate-OFF engine would hand its Planner for this day: the ungated corrected band on a fallback day, else the same
            u10, u50, u90 = gf.corrected if gf is not None else (fc.p10, fc.p50, fc.p90)
            upvd = PvDay(d, u10, u50, u90, shape)
            if plan is not None:
                plan["inflation"].append(round(fc.planning_inflation, 3))      # rounded like the published inflation it replaces
                ung["inflation"].append(round(gf.corrected_inflation if gf is not None else fc.inflation, 3))     # as the OFF report rounds it
                ung["confidence"].append(round(gf.corrected_confidence if gf is not None else fc.confidence, 3))
                if gf is not None:
                    plan["fallbacks"].append({"day": d.isoformat(), "published": (fc.p10, fc.p50, fc.p90), "gate": gf})
            if d == asof:
                # re-anchor the rest of today on how today is actually going (forecast re-anchoring); the explanation and the
                # note describe the PUBLISHED forecast, the remaining PV the Planner uses is re-anchored on the PLANNING p50
                done_share = sum(shape[h] for h in range(now.astimezone(self.tz).hour))
                rem, anchor = _reanchored(fc.p50, done_share, inp.pv_actual_so_far_kwh)
                reanchor = None
                if anchor is not None:
                    live, w, factor = anchor
                    reanchor = {"live_ratio": round(live, 3), "weight": round(w, 2), "factor": round(factor, 3)}
                    if live < 0.75 and done_share < 0.85:      # only while there is still PV left to matter
                        notes.append(f"PV is running at {live:.0%} of the corrected forecast so far today")
                urem = rem                                                    # the gate-OFF engine re-anchors on the ungated (published) p50
                if gf is not None:
                    urem, _anchor = _reanchored(u50, done_share, inp.pv_actual_so_far_kwh)
                    # the lower of the re-anchorings on the planning and on the ungated p50: the 2 kWh threshold of the re-anchoring is
                    # not monotone in the median, so a planning median just below it could otherwise assume MORE remaining PV
                    rem = min(_reanchored(p50, done_share, inp.pv_actual_so_far_kwh)[0], urem)
                pvd.remaining_p50 = max(0.0, rem)
                upvd.remaining_p50 = max(0.0, urem)
                pvd.now_local_hour = upvd.now_local_hour = now.astimezone(self.tz).hour
                info["today_reanchor"] = reanchor
            out[d] = pvd
            if ung is not None:
                ung["days"][d] = upvd
            info[d.isoformat()] = fc.to_dict()
            d += timedelta(days=1)
        return out, info

    # ------------------------------------------------------------------------------------------------------
    def run(self, inp: LiveInputs) -> dict:
        cfg, tz, now = self.cfg, self.tz, inp.now
        asof = now.astimezone(tz).date()
        notes: list[str] = []
        fast = self.usage.profile(asof, "fast")
        n_days = fast.n_days
        report: dict = {"model_version": MODEL_VERSION, "config_hash": cfg.config_hash(), "mode": "SHADOW",
                        "generated_for": now.isoformat(), "applies_nothing": True}

        if inp.soc_pct is not None and not (0.0 <= inp.soc_pct <= 100.0):
            notes.append(f"SOC reading {inp.soc_pct} is outside 0-100 and is ignored")
            inp = replace(inp, soc_pct=None)

        # numeric inputs that are not finite (or physically impossible) are dropped, never trusted
        def finite_or_none(name: str, v, lo: float = 0.0):
            if v is None:
                return None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < lo:
                notes.append(f"{name} reading {v!r} is not a valid number and is ignored")
                return None
            return float(v)
        inp = replace(inp, load_w=finite_or_none("load_w", inp.load_w, -1e9), pv_w=finite_or_none("pv_w", inp.pv_w),
                      pv_actual_so_far_kwh=finite_or_none("pv_actual_so_far_kwh", inp.pv_actual_so_far_kwh))

        # ---- ACTUAL ----------------------------------------------------------------------------------------
        report["actual"] = {"soc_pct": inp.soc_pct, "load_w": inp.load_w, "pv_w": inp.pv_w,
                            "soc_age_s": (inp.soc_age_s if isinstance(inp.soc_age_s, (int, float)) and math.isfinite(inp.soc_age_s) else None), "inverter_ok": inp.inverter_ok,
                            "pv_so_far_kwh": inp.pv_actual_so_far_kwh}

        # ---- tariff windows ----------------------------------------------------------------------------------
        tariff = inp.tariff or TariffInfo(default_cheap_windows(cfg, now))
        windows = tariff.cheap_windows or default_cheap_windows(cfg, now)
        if inp.tariff is None or inp.tariff.source == "config_default":
            notes.append("cheap-window times come from site configuration, not from live tariff data")

        # ---- usage forecasts ---------------------------------------------------------------------------------
        recent = hourly_residuals_today(self.usage, now, 3)
        last_res = (recent[-1][1] - recent[-1][2]) if recent else None
        nowcast = [0.0] * NOWCAST_HOURS
        if last_res is not None:
            from .usage import nowcast_adjustments
            nowcast = nowcast_adjustments([last_res])
        wins = standard_windows(cfg)
        forecasts: dict[str, UsageForecast] = {}

        def fixed(kind: str, day: date) -> UsageForecast:
            a, b = wins[kind]
            fn = fixed_window(a, b, tz)
            return self.usage.forecast(kind, fn(day), fn, asof)

        # next cheap window / "to next cheap" planning window relative to now
        forecasts["next_1h"] = next_hour_forecast(self.usage, now, last_res)
        cur_w = next((w for w in sorted(windows) if w[1] > now), None)
        if cur_w is not None:
            # day-ahead energy between the end of this cheap window and the start of the following one
            fn = fixed_window(*wins["to_next_cheap"], tz)
            day_for = cur_w[1].astimezone(tz).date()
            forecasts["to_next_cheap"] = self.usage.forecast("to_next_cheap", fn(day_for), fn, asof)
            forecasts["cheap_window"] = fixed("cheap_window", cur_w[0].astimezone(tz).date())
        forecasts["day"] = fixed("day", asof)
        forecasts["morning"] = fixed("morning", asof + timedelta(days=1) if now.astimezone(tz).hour >= 9 else asof)

        # sunset -> sunrise
        sr_t, ss_t = sun_times(asof, cfg.latitude, cfg.longitude)
        sr_next, _ = sun_times(asof + timedelta(days=1), cfg.latitude, cfg.longitude)
        sr_prev, ss_prev = sun_times(asof - timedelta(days=1), cfg.latitude, cfg.longitude)

        def night_fn(d: date):
            _sr, ss = sun_times(d, cfg.latitude, cfg.longitude)
            sr2, _ = sun_times(d + timedelta(days=1), cfg.latitude, cfg.longitude)
            return (ss, sr2) if ss and sr2 else None
        if sr_t and ss_t and sr_next:
            if now < sr_t:                               # still in last night
                nw = (max(now, ss_prev), sr_t)
                n_anchor = asof - timedelta(days=1)
            elif now < ss_t:                             # daytime: tonight
                nw = (ss_t, sr_next)
                n_anchor = asof
            else:                                        # evening: tonight, already started
                nw = (max(now, ss_t), sr_next)
                n_anchor = asof
            forecasts["overnight"] = self.usage.forecast("overnight", nw, night_fn, asof)
            night_total = None
        else:
            nw = None

        # useful PV
        up_day = asof if now < (self.predicted_useful_pv(asof, asof)[0] or now) else asof + timedelta(days=1)
        up50, up10, up90 = self.predicted_useful_pv(up_day, asof)
        useful_pv = up50
        anchor_end_min = cfg.cheap_window_end_min

        def to_pv_fn(d: date):
            st = useful_pv_start(self.history, cfg, d)
            return (local_wall(d, anchor_end_min, tz), st) if st else None
        if up50 is not None:
            a0 = max(now, local_wall(up_day, anchor_end_min, tz)) if now.astimezone(tz).date() == up_day else now
            if up50 > a0:
                f_pv = self.usage.forecast("to_useful_pv", (a0, up50), to_pv_fn, asof)
                # widen for start-time uncertainty: early start = less energy, late start = more
                if up10 and up90 and up10 > a0:
                    lo_e = window_sum(fast.values, a0, up10, tz)
                    hi_e = window_sum(fast.values, a0, up90, tz)
                    if lo_e is not None and hi_e is not None and f_pv.p50 > 0:
                        f_pv.p10 = min(f_pv.p10, f_pv.p10 * (lo_e / f_pv.p50 if f_pv.p50 else 1.0))
                        f_pv.p90 = max(f_pv.p90, hi_e * (f_pv.p90 / f_pv.p50 if f_pv.p50 else 1.0))
                        f_pv.notes.append("band includes uncertainty in WHEN useful PV starts")
                # a window that starts "now" is a different quantity from the 05:30-anchored one the residuals
                # were learned on, so it is scored under its own kind
                forecasts["to_useful_pv" if a0 != now else "to_useful_pv_from_now"] = f_pv

        report["predicted"] = {k: v.to_dict() for k, v in forecasts.items()}
        so_far, cov = self.history.energy("load", day_bounds(asof, tz)[0], now)
        proj = None
        if cov > 0.7 and "day" in forecasts:
            rem = window_sum(fast.values, now, day_bounds(asof, tz)[1], tz)
            proj = so_far / cov + (rem or 0.0)
        report["predicted"]["day_projection_kwh"] = None if proj is None else round(proj, 2)
        report["predicted"]["day_so_far_kwh"] = round(so_far / cov, 2) if cov > 0.7 else None
        report["predicted"]["useful_pv_start"] = {"p50": up50.isoformat() if up50 else None,
                                                   "early_p10": up10.isoformat() if up10 else None,
                                                   "late_p90": up90.isoformat() if up90 else None,
                                                   "threshold_w": cfg.useful_pv_threshold_w}
        report["predicted"]["sunrise"] = sr_t.isoformat() if sr_t else None
        report["predicted"]["sunset"] = ss_t.isoformat() if ss_t else None
        report["predicted"]["next_sunrise"] = sr_next.isoformat() if sr_next else None   # the one soc_at_sunrise refers to

        # ---- anomalies --------------------------------------------------------------------------------------
        anomalies = detect(self.usage, now, cfg)
        report["anomalies"] = anomalies.to_dict()

        # ---- slow-baseline guard (absence / return-day protection) -------------------------------------------------
        triggers = []
        if anomalies.abnormal_load_now:
            triggers.append("ABNORMAL")
        triggers += [a.code for a in anomalies.anomalies if a.code in ("BEHAVIOUR_SHIFT", "LOW_LOAD") and a.code not in triggers]
        guard, baseline_profile = baseline_guard(self.usage, asof, triggers)
        report["load_baseline_guard"] = guard

        # ---- confidence ---------------------------------------------------------------------------------------
        lead = forecasts.get("to_next_cheap") or forecasts["day"]
        conf = lead.confidence
        last = self.history.first_last()
        data_age_h = None if last is None else (now - last[1]).total_seconds() / 3600.0
        if data_age_h is not None and data_age_h > 6:
            conf = min(conf, 0.3)
            notes.append(f"history is {data_age_h:.0f} h old")
        plan_trace: dict = {"inflation": [], "fallbacks": []}
        pv_days, pv_info = self._pv_days(inp, asof, windows[-1][0] if windows else now + timedelta(days=2), notes, plan_trace)
        report["pv"] = pv_info
        pv_conf = min([pv_info[k]["confidence"] for k in pv_info if k != "today_reanchor"] or [1.0])
        # a PV forecast that had to be rejected as implausible means the PV input was not credible: never above LOW
        pv_rejects = [dict(r, day=k) for k, v in pv_info.items() if k != "today_reanchor"
                      for r in v.get("plausibility", {}).get("rejected", [])]
        gate_fallbacks = plan_trace["fallbacks"]

        def overall_for(pv_c: float, gate_cap: bool) -> float:
            """The overall confidence for a PV confidence `pv_c`; `gate_cap` applies the persistence-skill gate's LOW cap. With
            gate_cap False and the ungated PV confidences it is what the gate-OFF engine computes (the guard needs its label)."""
            o = min(conf, 0.35 + 0.65 * pv_c) if pv_info else conf
            if anomalies.abnormal_load_now:
                o *= 0.8
            if pv_rejects:
                o = min(o, 0.45)
            # the persistence-skill gate published persistence in place of a corrected forecast: planning uses the lower of the two, and
            # the PV input is not credible enough for more than LOW, exactly like a rejected forecast
            if gate_cap:
                o = min(o, 0.45)
            # a load history that does not look representative (empty house, behaviour shift): never HIGH
            if guard["active"] and guard["uplift_day_kwh"] > 0.5:
                o = min(o, 0.70)
            return o
        overall = overall_for(pv_conf, bool(gate_fallbacks))
        downgrades = []
        if pv_rejects:
            downgrades.append("PV_FORECAST_REJECTED")
        if gate_fallbacks:
            downgrades.append("PV_SKILL_GATE_FALLBACK")
        if guard["active"] and guard["uplift_day_kwh"] > 0.5:
            downgrades.append("LOAD_BASELINE_GUARD")
        label = confidence_label(overall)
        report["confidence"] = {"overall": round(overall, 3), "label": label, "usage": round(conf, 3),
                                "pv": round(pv_conf, 3), "history_days": n_days, "downgrade_reasons": downgrades}

        # ---- the shadow advisor -------------------------------------------------------------------------------
        load_rel = (-0.2, 0.2)
        if lead.p50 > 0:
            load_rel = (lead.p10 / lead.p50 - 1.0, lead.p90 / lead.p50 - 1.0)
        # the band-widening factor: the published one, or after a gate fallback the larger of it and the ungated forecast's own
        pv_infl = max(([pv_info[k].get("inflation", 1.0) for k in pv_info if k != "today_reanchor"] + plan_trace["inflation"]) or [1.0])

        def advice_for(pv_by_day: dict[date, PvDay], lab: str, infl: float) -> dict:
            return advise(cfg, Planner(cfg, fast.values, load_rel, pv_by_day, inp, nowcast, lab, infl, baseline_profile), inp, windows, lab,
                          anomalies.abnormal_load_now, (sr_next if (sr_t and now >= sr_t) else sr_t), useful_pv, tariff,
                          data_stale=bool(data_age_h is not None and data_age_h > 6))
        advice = advice_for(pv_days, label, pv_infl)
        # THE GUARD (belt and braces; the planning band already keeps the pessimistic PV at or below the ungated one). On a fallback day
        # set the advice is computed a SECOND time exactly as the gate-OFF engine would have computed it (the ungated PV days, the
        # confidence label before the gate's LOW cap, the ungated band inflation, today re-anchored on the ungated median) and the one
        # with the strictly higher recommended target is published, a tie keeping the planning run: the recommended target is therefore
        # never below the gate-OFF engine's. The gate's LOW cap, its reason and its notes below apply to either.
        kept_ungated = None
        if gate_fallbacks:
            ung = plan_trace["ungated"]
            ung_label = confidence_label(overall_for(min(ung["confidence"] or [1.0]), False))
            ung_advice = advice_for(ung["days"], ung_label, max(ung["inflation"] or [1.0]))
            t_plan = (advice.get("overnight_target") or {}).get("recommended_target_soc_pct")
            t_ung = (ung_advice.get("overnight_target") or {}).get("recommended_target_soc_pct")
            if prefers_ungated(t_plan, t_ung):
                advice, kept_ungated = ung_advice, (t_plan, t_ung)
        # surface the plausibility rejection and the baseline guard in the advice itself (reason codes, not just notes)
        advice.setdefault("reasons", [])
        advice.setdefault("uncertainty", [])
        for r in pv_rejects:
            txt = (f"PV forecast from {r['source']} for {r['day']} was rejected as implausible "
                   f"({r['raw_kwh']:.1f} kWh raw" + (f", {r['corrected_kwh']:.1f} kWh corrected" if r.get("corrected_kwh") is not None else "")
                   + f"; {r['reason']}). Falling back to persistence at LOW confidence; no high-confidence advice is based on it.")
            advice["reasons"].append({"code": "PV_FORECAST_REJECTED", "text": txt})
            advice["uncertainty"].append({"code": "PV_FORECAST_REJECTED", "severity": "HIGH", "text": txt})
        for g in gate_fallbacks:
            gf, pub = g["gate"], g["published"]
            txt = (f"PV forecast for {g['day']}: {gf.note}. The published value is persistence at LOW confidence "
                   f"(p10 {pub[0]:.1f} / p50 {pub[1]:.1f} / p90 {pub[2]:.1f} kWh). For planning the advisor uses the LOWER of persistence and "
                   f"the value the corrected {gf.source} forecast would have given ({gf.corrected[0]:.1f} / {gf.corrected[1]:.1f} / "
                   f"{gf.corrected[2]:.1f} kWh) for the median and the upper value, and a lower value for p10 that keeps the corrected spread, "
                   f"that is {gf.planning[0]:.1f} / {gf.planning[1]:.1f} / {gf.planning[2]:.1f} kWh; it also computes the advice the corrected "
                   f"forecast would have given and publishes the higher overnight target, so the fallback cannot lower the battery "
                   f"target; confidence is capped at LOW.")
            advice["reasons"].append({"code": "PV_SKILL_GATE_FALLBACK", "text": txt})
            advice["uncertainty"].append({"code": "PV_SKILL_GATE_FALLBACK", "severity": "WATCH", "text": txt})
        if kept_ungated is not None:
            advice["reasons"].append({"code": UNGATED_KEPT_CODE, "text": (
                f"The ungated corrected PV forecast would have given a higher overnight target ({kept_ungated[1]:.0f}%) than the planning "
                f"values did ({kept_ungated[0]:.0f}%), so the higher target is kept: this advice is the one the corrected forecast gives, "
                f"and a persistence fallback never lowers the recommended target.")})
        if guard["active"] and guard["uplift_day_kwh"] > 0.5:
            advice["reasons"].append({"code": "LOAD_BASELINE_GUARD", "text": (
                f"Recent demand ({guard['fast_day_kwh']:.0f} kWh/day on the short-memory profile) is below the longer baseline "
                f"({guard['baseline_day_kwh']:.0f} kWh/day) or an unusual-load condition is active ({', '.join(guard['triggers'])}); "
                f"the pessimistic path uses the longer baseline so a return to normal use is not under-reserved. "
                f"The median forecast is unchanged.")})
            advice["uncertainty"].append({"code": "LOAD_BASELINE_GUARD", "severity": "WATCH",
                                          "text": "Short-term demand history looks unrepresentative; the safety path leans on the longer baseline."})
        report["recommended"] = advice

        # ---- status ------------------------------------------------------------------------------------------------
        if n_days < cfg.min_days_for_forecast:
            status = "INSUFFICIENT_HISTORY"
        elif data_age_h is not None and data_age_h > 6 or (inp.soc_age_s is not None and soc_is_stale(inp.soc_age_s)):
            status = "DATA_STALE"
        elif anomalies.abnormal_load_now:
            status = "ABNORMAL_DAY"
        elif any("running at" in n for n in notes):
            status = "PV_UNDERPERFORMING"
        elif n_days < cfg.min_days_for_high_confidence:
            status = "LEARNING"
        else:
            status = "LEARNING_NORMALLY"
        report["status"] = status
        report["notes"] = notes
        report["weekday_effect"] = weekday_effect(self.history, cfg)

        # ---- features snapshot + hash ----------------------------------------------------------------------------
        feats = {"now": now.astimezone(UTC).isoformat(), "soc": inp.soc_pct, "load_w": inp.load_w, "pv_w": inp.pv_w,
                 "pv_raw": [_json_safe(x) for x in (inp.pv_raw_today, inp.pv_raw_tomorrow, inp.pv_raw_remaining_today)],
                 "pv_so_far": inp.pv_actual_so_far_kwh, "windows": [[a.isoformat(), b.isoformat()] for a, b in windows[:4]],
                 "fast_profile": [None if v is None else round(v, 4) for v in fast.values], "n_days": n_days,
                 "history_last": last[1].isoformat() if last else None, "config_hash": cfg.config_hash(),
                 "model_version": MODEL_VERSION, "nowcast": [round(x, 4) for x in nowcast]}
        report["features"] = feats
        report["feature_hash"] = hashlib.sha256(json.dumps(feats, sort_keys=True, default=str).encode()).hexdigest()[:16]
        self.now_ref = now
        report["forecast_records"] = self._records(report, forecasts, pv_info, advice)
        return report

    # ------------------------------------------------------------------------------------------------------
    def _records(self, report: dict, forecasts: dict[str, UsageForecast], pv_info: dict, advice: dict) -> list[dict]:
        """Scoreable forecast records (kinds the scorecard knows how to resolve)."""
        recs = []
        for kind, f in forecasts.items():
            if f.label == "INSUFFICIENT":
                continue          # nothing worth scoring: built on too little data
            recs.append({"kind": f"load_kwh:{kind}", "unit": "kWh", "horizon_start": f.t0.isoformat(),
                         "horizon_end": f.t1.isoformat(), "p10": f.p10, "p50": f.p50, "p90": f.p90,
                         "confidence": f.confidence, "explanation": {"weights": f.weights, "n_days": f.n_days,
                                                                      "notes": f.notes}})
        for k, v in pv_info.items():
            if k == "today_reanchor":
                continue
            d = date.fromisoformat(k)
            t0, t1 = day_bounds(d, self.tz)
            if t0 <= self.now_ref:        # today (already under way) is not a day-ahead forecast
                continue
            recs.append({"kind": "pv_kwh:day", "unit": "kWh", "horizon_start": t0.isoformat(), "horizon_end": t1.isoformat(),
                         "p10": v["p10"], "p50": v["p50"], "p90": v["p90"], "confidence": v["confidence"],
                         "explanation": {"source": v["source"], "ratio": v["ratio"], "raw": v["raw_kwh"]}})
        # SOC just before the cheap window opens: depends only on the usage/PV forecasts and the SOC now, not on
        # any controller decision, so it is a clean, scoreable SOC forecast. Compared on the hour mean so that the
        # hourly statistics the outcome is read from are like-for-like.
        traj = advice.get("trajectory") or []
        ot = advice.get("overnight_target") or {}
        if traj and ot:
            w0 = datetime.fromisoformat(ot["window"][0])
            h1 = w0.replace(minute=0, second=0, microsecond=0)
            h0 = h1 - timedelta(hours=1)
            pts = {datetime.fromisoformat(t["t"]): t for t in traj}
            if h0 in pts and h1 in pts and h0 > self.now_ref + timedelta(minutes=30):
                def mean(key: str) -> float:
                    return 0.5 * (pts[h0][key] + pts[h1][key])
                recs.append({"kind": "soc_pct:pre_window_hour", "unit": "%", "horizon_start": h0.isoformat(),
                             "horizon_end": h1.isoformat(), "p10": mean("soc_low"), "p50": mean("soc_median"),
                             "p90": mean("soc_high"), "confidence": report["confidence"]["overall"],
                             "explanation": {"note": "hour-mean SOC in the last full hour before the cheap window; independent of any charge decision"}})
        return recs
