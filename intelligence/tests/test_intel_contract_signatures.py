#!/usr/bin/env python3
"""Intelligence foundation: the FROZEN interfaces every stream builds on (a contract change request, not an edit, changes them).

  [1] run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope
  [2] assess_inputs(inputs: CycleInputs) -> QualityResult; prepare_history(history, decisions, now, *, accept_provenance)
  [3] the dataclass field sets (CycleInputs, QualityResult, SiteReading, AdvisoryEnvelope, ItemView, ForecastView, Versions,
      SiteFacts, OutcomeMetrics, InputState, GateContext, RequiredInputs, Decision, PeriodProfile) and their frozenness
  [4] ENTITY_IDS, CONTRACT_VERSION, SITE_READING_KEYS (a superset may grow) and the shared function signatures
Streams may not edit this file.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intelligence import advisory_contract as ac  # noqa: E402
from intelligence import periods, quality, shadow_cycle  # noqa: E402
from intelligence import site_decisions as sd  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def sig(fn) -> list[tuple[str, str, str, object]]:
    """[(name, kind, annotation, default)] with annotations as source text (the modules use postponed annotations)."""
    out = []
    for p in inspect.signature(fn).parameters.values():
        out.append((p.name, p.kind.name, p.annotation if isinstance(p.annotation, str) else repr(p.annotation),
                    "<none>" if p.default is inspect.Parameter.empty else p.default))
    return out


def ret(fn) -> str:
    r = inspect.signature(fn).return_annotation
    return r if isinstance(r, str) else repr(r)


def field_names(cls) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def frozen(cls) -> bool:
    return dataclasses.is_dataclass(cls) and cls.__dataclass_params__.frozen


print("== [1] run_cycle")
check("run_cycle(inputs: CycleInputs) -> AdvisoryEnvelope",
      sig(shadow_cycle.run_cycle) == [("inputs", "POSITIONAL_OR_KEYWORD", "CycleInputs", "<none>")]
      and ret(shadow_cycle.run_cycle) == "AdvisoryEnvelope", str(sig(shadow_cycle.run_cycle)))
check("run_cycle satisfies the RunCycle protocol", isinstance(shadow_cycle.run_cycle, ac.RunCycle))

print("== [2] quality seams")
check("assess_inputs(inputs: CycleInputs) -> QualityResult",
      sig(quality.assess_inputs) == [("inputs", "POSITIONAL_OR_KEYWORD", "CycleInputs", "<none>")]
      and ret(quality.assess_inputs) == "QualityResult")
check("prepare_history(history, decisions, now, *, accept_provenance=DEFAULT) -> (History | None, findings)",
      [(n, k) for n, k, _a, _d in sig(quality.prepare_history)] == [("history", "POSITIONAL_OR_KEYWORD"),
                                                                     ("decisions", "POSITIONAL_OR_KEYWORD"),
                                                                     ("now", "POSITIONAL_OR_KEYWORD"),
                                                                     ("accept_provenance", "KEYWORD_ONLY")]
      and sig(quality.prepare_history)[3][3] == sd.DEFAULT_ACCEPT_PROVENANCE
      and ret(quality.prepare_history) == "tuple[History | None, list[Finding]]", str(sig(quality.prepare_history)))

print("== [3] field sets")
FIELDS = {
    ac.CycleInputs: ["now", "snapshot", "live", "caller_assessments", "history", "pv_forecast_history", "base_cfg", "site_facts",
                     "decisions", "accept_provenance", "site_readings", "outcome_metrics", "paused", "previous", "versions"],
    quality.QualityResult: ["findings", "blocked_items", "data_quality", "ages"],
    ac.SiteReading: ["key", "value", "unit", "observed_at", "source"],
    ac.AdvisoryEnvelope: ["status", "generated_at", "versions", "items", "forecasts", "data_quality", "decisions", "provenance_ok",
                          "pause_control", "valid_until", "next_run_at", "blockers", "reason_codes", "self_test", "input_ages",
                          "tariff", "value", "plan", "accuracy", "drift", "calibration", "engine_comparison", "scorecard_report",
                          "last_good", "contract_version", "mode", "applies_nothing"],
    ac.ItemView: ["key", "status", "value", "valid_until", "confidence", "blockers", "reason_codes", "summary"],
    ac.ForecastView: ["key", "status", "value", "p10", "p90", "valid_until", "confidence", "blockers", "reason_codes", "summary"],
    ac.Versions: ["integration_version", "engine_version", "git_sha", "config_hash"],
    ac.SiteFacts: ["pv_array_kwp", "latitude", "longitude", "tz"],
    ac.OutcomeMetrics: ["mae_7d", "coverage_7d", "n"],
    sd.InputState: ["key", "value", "fresh", "age_s", "limit_s"],
    sd.GateContext: ["capacity_sources", "capacity_mismatch_pct", "clock_change_in_scope", "boundary_in_changed_hour"],
    sd.RequiredInputs: ["signals", "readings", "site_facts", "charge_window_sources"],
    sd.Decision: ["id", "status", "value", "provenance", "record_ref", "problems"],
    sd.Finding: ["code", "severity", "subject", "text", "evidence"],
    periods.PeriodProfile: ["day", "start_min", "end_min", "tz", "start_utc", "end_utc", "nominal_h", "actual_h", "factor",
                            "change_kind", "start_boundary", "end_boundary"],
}
for cls, want in FIELDS.items():
    check(f"{cls.__name__}: field set pinned and frozen", field_names(cls) == want and frozen(cls), str(field_names(cls)))

print("== [4] contract constants and shared signatures")
check("CONTRACT_VERSION", ac.CONTRACT_VERSION == "ecco-intel-entities/1")
check("ENTITY_IDS pinned", sorted(ac.ENTITY_IDS.values()) == sorted(
    ["sensor.ecco_intel_status", "sensor.ecco_intel_charge_target", "sensor.ecco_intel_overnight_demand",
     "sensor.ecco_intel_export_event", "sensor.ecco_intel_dump_to_grid", "sensor.ecco_intel_predicted_day_load",
     "sensor.ecco_intel_pv_tomorrow", "sensor.ecco_intel_predicted_morning_soc", "sensor.ecco_intel_accuracy",
     "sensor.ecco_intel_data_quality", "binary_sensor.ecco_intel_fresh", "input_boolean.ecco_intel_paused",
     "binary_sensor.ecco_intel_watchdog_fresh"]))
BASE_READINGS = {"liveness.dongle_poll_changed_at", "supervision.state", "supervision.stable", "supervision.heartbeat_age_s",
                 "battery.soc_raw_pct", "capacity.helper_kwh", "capacity.fe1_wh_per_pct", "capacity.fe1_basis", "capacity.reg204_ah",
                 "efficiency.helper_pct", "protection.shutdown_soc_pct", "stop.dump_soc_pct", "tou.slot_table",
                 "tou.current_target_soc_pct", "limits.max_grid_charge_w", "tariff.import_rates", "tariff.export_rates",
                 "tariff.events", "pv.forecast_today_kwh", "pv.forecast_tomorrow_kwh", "inverter.clock_offset_s",
                 "pref.wear_cost_p_per_kwh", "pref.normal_max_charge_target_pct"}
check("SITE_READING_KEYS is a superset of the frozen keys, with their units unchanged",
      BASE_READINGS <= set(ac.SITE_READING_KEYS) and ac.SITE_READING_KEYS["limits.max_grid_charge_w"] == "W"
      and ac.SITE_READING_KEYS["liveness.dongle_poll_changed_at"] == "datetime")
SHARED = {
    sd.gate: ["item", "decisions", "context", "accept_provenance"],
    sd.apply_to_siteconfig: ["base_cfg", "decisions", "readings", "accept_provenance"],
    sd.freshness_limits: ["decisions", "accept_provenance"],
    sd.required_inputs: ["item", "decisions", "accept_provenance"],
    sd.satisfied: ["decision", "accept_provenance"],
    sd.capacity_sources_context: ["decisions", "readings", "accept_provenance"],
    sd.DecisionSet.from_mapping: ["mapping", "source"],
    periods.period_profile: ["day", "start_min", "end_min", "tz"],
    periods.clock_changes: ["start", "end", "tz"],
    ac.to_entity_payloads: ["env", "now"],
    ac.derive_status: ["paused", "self_test_failed", "stale", "starting", "data_quality", "item_statuses"],
    ac.ItemView.from_advice: ["advice", "key", "valid_until"],
}
for fn, want in SHARED.items():
    got = [n for n, _k, _a, _d in sig(fn)]
    check(f"{fn.__qualname__}({', '.join(want)})", got == want, str(got))
check("the default acceptance is OWNER_RECORD everywhere it appears",
      all(d == sd.DEFAULT_ACCEPT_PROVENANCE for fn in (sd.gate, sd.apply_to_siteconfig, sd.freshness_limits, sd.required_inputs, sd.satisfied,
                                                       sd.capacity_sources_context)
          for n, _k, _a, d in sig(fn) if n == "accept_provenance")
      and dataclasses.fields(ac.CycleInputs)[9].default == frozenset({"OWNER_RECORD"}))
check("CycleInputs.accept_provenance is keyword-only (it can never be passed by position)",
      inspect.signature(ac.CycleInputs).parameters["accept_provenance"].kind == inspect.Parameter.KEYWORD_ONLY
      and dataclasses.fields(ac.CycleInputs)[9].kw_only is True)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("all contract-signature checks passed")
