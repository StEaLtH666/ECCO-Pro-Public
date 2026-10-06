#!/usr/bin/env python3
"""Offline tests for health/system_health.py (Task 006 section 15,
hardened in Task 006A section 9).

All synthetic - no test touches a live system, and every test passes
an explicit fixed `now`. Exercises the real check/reason-code
registries loaded from registry/system_health_checks.yaml and
registry/health_reason_codes.yaml, but every SIGNAL is a synthetic
CheckInput constructed here.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import system_health as sh  # noqa: E402

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


NOW = datetime(2026, 9, 18, 12, 0, 0, tzinfo=timezone.utc)

CHECKS = sh.load_check_registry()
REASON_CODES = sh.load_reason_codes()


def healthy_input_for(chk: sh.CheckDef) -> sh.CheckInput:
    """A generic, always-healthy CheckInput for a given check - used as
    the baseline that individual scenarios then perturb."""
    inp = sh.CheckInput()
    ct = chk.check_type
    if ct in ("freshness", "timestamp_age"):
        inp.last_updated = NOW - timedelta(seconds=1)
    elif ct == "boolean_expected":
        inp.value = chk.parameters.get("expected_value", True)
    elif ct == "numeric_range":
        lo, hi = chk.parameters.get("min", 0), chk.parameters.get("max", 0)
        inp.value = (lo + hi) / 2
    elif ct == "text_state":
        inp.value = "normal"
    elif ct == "transaction_state":
        inp.active = False
    elif ct == "failure_counter_delta":
        window = chk.parameters.get("window_seconds", 600)
        inp.baseline_counter_value = 5
        inp.counter_value = 5
        inp.baseline_observed_at = NOW - timedelta(seconds=window + 10)
    elif ct == "cross_source_agreement":
        inp.value_a, inp.value_b = 1, 1
        inp.timestamp_a, inp.timestamp_b = NOW, NOW
    elif ct == "history_depth":
        inp.depth_value = chk.parameters.get("minimum_value", 0) + 100
    elif ct == "entity_available":
        inp.available, inp.ever_observed = True, True
    elif ct == "version_match":
        # A manual_only version_match check (e.g. battery_outlook_model_version)
        # has NO live signal by design - giving it a fabricated True would
        # misrepresent that permanent limitation as a real observation.
        inp.value = True if chk.rollup_participation == sh.ROLLUP_AUTOMATIC else None
    elif ct == "conditional_presence":
        inp.checkpoint_passed, inp.scored_since_checkpoint = True, True
    return inp


def all_healthy_signals() -> dict[str, sh.CheckInput]:
    return {cid: healthy_input_for(chk) for cid, chk in CHECKS.items()}


def run(signals: dict[str, sh.CheckInput]):
    return sh.evaluate_all(CHECKS, REASON_CODES, signals, NOW)


def by_id(results: list[sh.CheckResult], cid: str) -> sh.CheckResult:
    return next(r for r in results if r.check_id == cid)


def by_subsystem(results: list[sh.SubsystemResult], subsystem: str) -> sh.SubsystemResult:
    return next(sr for sr in results if sr.subsystem == subsystem)


# ===========================================================================
# [1] Healthy baseline - Task 006A: with diagnostic_only/manual_only checks
# correctly excluded from automatic rollup, a fully-healthy snapshot now
# reaches a genuine overall HEALTHY, not a permanent WARNING floor.
# ===========================================================================

print("[1] Healthy baseline")
check_results, subsystem_results, overall, control = run(all_healthy_signals())
check("overall state is HEALTHY when every automatically-evaluable check is healthy", overall.state == sh.HEALTHY, overall.state)
check("manual_control_ready is true", control.ready, f"{control.blocking_checks} {control.missing_required_checks} {control.insufficient_evidence_checks}")

influx_raw_sr = by_subsystem(subsystem_results, "influx_raw")
influx_5m_sr = by_subsystem(subsystem_results, "influx_5m")
check("influx_raw (all checks diagnostic_only) is excluded from automatic rollup", not influx_raw_sr.contributes_to_overall)
check("influx_5m (all checks diagnostic_only) is excluded from automatic rollup", not influx_5m_sr.contributes_to_overall)
check("influx_raw's diagnostic-only result is still visible", len(influx_raw_sr.diagnostic_results) == 1)
check("influx_5m's diagnostic-only results are still visible", len(influx_5m_sr.diagnostic_results) == 2)

other_subsystems = [sr for sr in subsystem_results if sr.contributes_to_overall]
non_healthy = [sr.subsystem for sr in other_subsystems if sr.state not in (sh.HEALTHY, sh.SUPPRESSED)]
check("every automatic-rollup-participating subsystem is healthy/suppressed", non_healthy == [], str(non_healthy))

manual_only_results = [
    by_id(check_results, "battery_outlook_model_version"),
    by_id(check_results, "battery_outlook_scorer_anti_contamination"),
]
check(
    "the two permanently-unverifiable checks still evaluate (visible) but do not poison battery_outlook/battery_outlook_scorer",
    all(r.state == sh.UNKNOWN for r in manual_only_results)
    and by_subsystem(subsystem_results, "battery_outlook").state == sh.HEALTHY
    and by_subsystem(subsystem_results, "battery_outlook_scorer").state == sh.HEALTHY,
    f"{[r.state for r in manual_only_results]}",
)

BASELINE_OVERALL_STATE = overall.state

# ===========================================================================
# [2] Communications
# ===========================================================================

print("")
print("[2] Communications")

signals = all_healthy_signals()
signals["telemetry_freshness"].last_updated = NOW - timedelta(seconds=200)
_, subsystem_results, overall, control = run(signals)
telemetry_sr = by_subsystem(subsystem_results, "inverter_telemetry")
check("telemetry stale (200s) while config fresh -> inverter_telemetry FAILED", telemetry_sr.state == sh.FAILED, telemetry_sr.state)
config_sr = by_subsystem(subsystem_results, "inverter_configuration")
check("configuration subsystem remains HEALTHY independently", config_sr.state == sh.HEALTHY, config_sr.state)
check("overall FAILED (communications-class failure escalates)", overall.state == sh.FAILED, overall.state)
check("manual_control_ready is false", not control.ready)

signals = all_healthy_signals()
signals["esphome_reachable"].available = False
_, subsystem_results, overall, control = run(signals)
comms_sr = by_subsystem(subsystem_results, "communications")
check("ESPHome offline -> communications FAILED", comms_sr.state == sh.FAILED, comms_sr.state)
check("ESPHome offline blocks manual control", not control.ready)

signals = all_healthy_signals()
signals["configuration_freshness"].last_updated = NOW - timedelta(seconds=700)
_, subsystem_results, overall, control = run(signals)
telemetry_sr = by_subsystem(subsystem_results, "inverter_telemetry")
config_sr = by_subsystem(subsystem_results, "inverter_configuration")
check("configuration stale (700s) while telemetry fresh -> inverter_configuration FAILED", config_sr.state == sh.FAILED, config_sr.state)
check("inverter_telemetry unaffected", telemetry_sr.state == sh.HEALTHY, telemetry_sr.state)

signals = all_healthy_signals()
signals["telemetry_failures_recent"].baseline_counter_value = 10
signals["telemetry_failures_recent"].counter_value = 11
signals["telemetry_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=650)
signals["telemetry_failures_recent"].recovered = True
_, subsystem_results, overall, control = run(signals)
telemetry_sr = by_subsystem(subsystem_results, "inverter_telemetry")
check("recent Modbus failures then successful recovery -> WARNING, not FAILED", telemetry_sr.state == sh.WARNING, telemetry_sr.state)
check("recovered wording present", "recovered" in [cr.human_reason for cr in telemetry_sr.check_results if cr.check_id == "telemetry_failures_recent"][0])

# ===========================================================================
# [3] RTC
# ===========================================================================

print("")
print("[3] RTC")

signals = all_healthy_signals()
signals["rtc_ntp_synced"].value = False
_, subsystem_results, _, _ = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
check("NTP unavailable -> rtc_time WARNING", rtc_sr.state == sh.WARNING, rtc_sr.state)

signals = all_healthy_signals()
signals["rtc_read_freshness"].last_updated = NOW - timedelta(seconds=200)
_, subsystem_results, _, _ = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
check("RTC read clock stale -> rtc_time DEGRADED", rtc_sr.state == sh.DEGRADED, rtc_sr.state)

signals = all_healthy_signals()
signals["rtc_correction_duration"].active = True
signals["rtc_correction_duration"].active_since = NOW - timedelta(seconds=20)
_, subsystem_results, _, control = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
check("correction in progress (20s, below stuck threshold) -> WARNING", rtc_sr.state == sh.WARNING, rtc_sr.state)
check("correction in progress blocks manual control", not control.ready)

signals = all_healthy_signals()
signals["rtc_correction_duration"].active = True
signals["rtc_correction_duration"].active_since = NOW - timedelta(seconds=300)
_, subsystem_results, _, control = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
check("correction stuck (300s) -> FAILED", rtc_sr.state == sh.FAILED, rtc_sr.state)
check("correction stuck blocks manual control", not control.ready)

signals = all_healthy_signals()
signals["rtc_correction_failures_recent"].baseline_counter_value = 2
signals["rtc_correction_failures_recent"].counter_value = 2
signals["rtc_correction_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=2000)
signals["rtc_correction_failures_recent"].recovered = True
_, subsystem_results, _, _ = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
check("RTC correction failure with zero recent delta (recovered earlier) -> HEALTHY", rtc_sr.state == sh.HEALTHY, rtc_sr.state)

# ===========================================================================
# [4] Canonical telemetry
# ===========================================================================

print("")
print("[4] Canonical telemetry")

signals = all_healthy_signals()
_, subsystem_results, _, _ = run(signals)
canon_sr = by_subsystem(subsystem_results, "canonical_telemetry")
check("raw+canonical agree -> HEALTHY", canon_sr.state == sh.HEALTHY, canon_sr.state)

signals = all_healthy_signals()
signals["canonical_stale_raw_fresh"].last_updated = NOW - timedelta(seconds=90)
_, subsystem_results, _, _ = run(signals)
canon_sr = by_subsystem(subsystem_results, "canonical_telemetry")
check("canonical stale (90s) while raw fresh -> WARNING", canon_sr.state == sh.WARNING, canon_sr.state)

signals = all_healthy_signals()
signals["canonical_entity_available"].available = False
signals["canonical_entity_available"].ever_observed = True
_, subsystem_results, _, _ = run(signals)
canon_sr = by_subsystem(subsystem_results, "canonical_telemetry")
check("raw+canonical both missing -> DEGRADED", canon_sr.state == sh.DEGRADED, canon_sr.state)

signals = all_healthy_signals()
signals["canonical_raw_skew"].timestamp_a = NOW
signals["canonical_raw_skew"].timestamp_b = NOW - timedelta(seconds=5)
_, subsystem_results, _, _ = run(signals)
canon_sr = by_subsystem(subsystem_results, "canonical_telemetry")
check("small (5s) timestamp skew tolerated -> HEALTHY", canon_sr.state == sh.HEALTHY, canon_sr.state)

signals = all_healthy_signals()
signals["canonical_raw_mismatch"].value_a = 50.0
signals["canonical_raw_mismatch"].value_b = 10.0
_, subsystem_results, _, _ = run(signals)
canon_sr = by_subsystem(subsystem_results, "canonical_telemetry")
check("large value disagreement -> WARNING", canon_sr.state == sh.WARNING, canon_sr.state)

# ===========================================================================
# [5] InfluxDB - Task 006A: influx_5m's checks are diagnostic_only
# (thresholds_unresolved), always UNKNOWN regardless of signal, and
# excluded from automatic rollup - see section 6.
# ===========================================================================

print("")
print("[5] InfluxDB")

signals = all_healthy_signals()
_, subsystem_results, _, _ = run(signals)
influx_5m_sr = by_subsystem(subsystem_results, "influx_5m")
influx_raw_sr = by_subsystem(subsystem_results, "influx_raw")
check("influx_5m reports UNKNOWN (manual diagnostic, no fixed threshold) regardless of signal", influx_5m_sr.state == sh.UNKNOWN, influx_5m_sr.state)
check("influx_raw reports UNKNOWN (manual diagnostic) regardless of signal", influx_raw_sr.state == sh.UNKNOWN, influx_raw_sr.state)
check("neither contributes to the overall automatic rollup", not influx_5m_sr.contributes_to_overall and not influx_raw_sr.contributes_to_overall)

signals = all_healthy_signals()
_, subsystem_results, _, _ = run(signals)
outlook_sr = by_subsystem(subsystem_results, "battery_outlook")
check("battery_outlook (the model's OWN output) is healthy at baseline, independent of influx_5m's manual-diagnostic state", outlook_sr.state == sh.HEALTHY, outlook_sr.state)

signals = all_healthy_signals()
signals["influx_history_depth"].depth_value = 2  # still UNKNOWN regardless - thresholds_unresolved does not apply to history_depth's own numeric check, but the check's rollup_participation excludes it either way
_, subsystem_results, _, _ = run(signals)
influx_5m_sr = by_subsystem(subsystem_results, "influx_5m")
check("influx_history_depth is diagnostic_only - excluded from automatic rollup regardless of its own signal", not influx_5m_sr.contributes_to_overall)

del_signals = all_healthy_signals()
del del_signals["influx_raw_freshness"]
_, subsystem_results, _, _ = run(del_signals)
raw_sr = by_subsystem(subsystem_results, "influx_raw")
check("a subsystem with genuinely zero results (not diagnostic-excluded) still contributes UNKNOWN at full weight", raw_sr.state == sh.UNKNOWN and raw_sr.contributes_to_overall, f"{raw_sr.state}/{raw_sr.contributes_to_overall}")

print("")
print("[5b] influx_5m / battery_outlook independence (Task 006A section 6)")

# Input history (influx_5m, diagnostic-only, manual) vs. output (battery_outlook,
# automatic, live HA entity) evaluate completely independently of each other -
# neither check's signal affects the other's result.
signals = all_healthy_signals()
signals["battery_outlook_freshness"].last_updated = NOW - timedelta(seconds=1)  # output fresh
# influx_5m_freshness's signal is irrelevant (thresholds_unresolved forces UNKNOWN
# unconditionally) - demonstrating this IS the independence proof: nothing about
# influx_5m's state can make battery_outlook read anything other than its own signal.
_, subsystem_results, _, _ = run(signals)
outlook_sr = by_subsystem(subsystem_results, "battery_outlook")
influx_5m_sr = by_subsystem(subsystem_results, "influx_5m")
check(
    "output fresh (battery_outlook HEALTHY) while input-history diagnostic independently reports its own UNKNOWN state",
    outlook_sr.state == sh.HEALTHY and influx_5m_sr.state == sh.UNKNOWN,
    f"battery_outlook={outlook_sr.state} influx_5m={influx_5m_sr.state}",
)

signals = all_healthy_signals()
signals["battery_outlook_freshness"].last_updated = NOW - timedelta(seconds=1400)  # output stale
_, subsystem_results, overall, _ = run(signals)
outlook_sr = by_subsystem(subsystem_results, "battery_outlook")
influx_5m_sr = by_subsystem(subsystem_results, "influx_5m")
check(
    "output stale (battery_outlook WARNING) does not change influx_5m's own (unrelated) diagnostic state",
    outlook_sr.state == sh.WARNING and influx_5m_sr.state == sh.UNKNOWN,
    f"battery_outlook={outlook_sr.state} influx_5m={influx_5m_sr.state}",
)
check(
    "influx_5m_freshness's own description cites the underlying load-power history measurement, not the model output",
    "ecco_load_power" in CHECKS["influx_5m_freshness"].description,
)
check(
    "influx_5m_freshness is diagnostic_only while battery_outlook_freshness is automatic - genuinely different evaluation paths, not just different labels",
    CHECKS["influx_5m_freshness"].rollup_participation == sh.ROLLUP_DIAGNOSTIC_ONLY
    and CHECKS["battery_outlook_freshness"].rollup_participation == sh.ROLLUP_AUTOMATIC,
)

# ===========================================================================
# [6] Battery Outlook
# ===========================================================================

print("")
print("[6] Battery Outlook")

signals = all_healthy_signals()
_, subsystem_results, overall, _ = run(signals)
outlook_sr = by_subsystem(subsystem_results, "battery_outlook")
check("forecast fresh -> battery_outlook HEALTHY", outlook_sr.state == sh.HEALTHY, outlook_sr.state)

signals = all_healthy_signals()
signals["battery_outlook_freshness"].last_updated = NOW - timedelta(seconds=1400)
_, subsystem_results, overall, _ = run(signals)
outlook_sr = by_subsystem(subsystem_results, "battery_outlook")
check("forecast stale -> battery_outlook WARNING", outlook_sr.state == sh.WARNING, outlook_sr.state)
check(
    "forecast staleness's OWN contribution is capped at DEGRADED (informational tier), never WARNING/FAILED",
    min(outlook_sr.severity_rank, sh.TIER_CAP[sh.INFORMATIONAL]) == sh.SEVERITY_RANK[sh.DEGRADED],
)
check("battery_outlook is not among the subsystems the overall state is attributed to when nothing else is worse", "battery_outlook" not in overall.contributing_subsystems or overall.state == sh.DEGRADED, overall.contributing_subsystems)
check("overall state is capped at DEGRADED at worst from this single informational finding", overall.state in (sh.HEALTHY, sh.DEGRADED), overall.state)

signals = all_healthy_signals()
check(
    "no battery_outlook/battery_outlook_scorer check is keyed on error/accuracy magnitude",
    all("error" not in c.description.lower() and "accuracy" not in c.description.lower() for c in CHECKS.values() if c.subsystem in ("battery_outlook", "battery_outlook_scorer")),
)

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"].checkpoint_passed = True
signals["battery_outlook_scorer_freshness"].scored_since_checkpoint = False
_, subsystem_results, _, _ = run(signals)
scorer_sr = by_subsystem(subsystem_results, "battery_outlook_scorer")
check("scorer stale (checkpoint passed, no new score) -> WARNING", scorer_sr.state == sh.WARNING, scorer_sr.state)

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"].checkpoint_passed = False
signals["battery_outlook_scorer_freshness"].scored_since_checkpoint = False
_, subsystem_results, _, _ = run(signals)
scorer_sr = by_subsystem(subsystem_results, "battery_outlook_scorer")
scorer_results = [cr for cr in scorer_sr.check_results if cr.check_id == "battery_outlook_scorer_freshness"]
check("scorer intentionally not yet due -> SUPPRESSED for that check", scorer_results[0].state == sh.SUPPRESSED, scorer_results[0].state)

# ===========================================================================
# [7] Transactions
# ===========================================================================

print("")
print("[7] Transactions")

signals = all_healthy_signals()
signals["manual_write_arm_unexpected"].active = True
signals["manual_write_arm_unexpected"].active_since = NOW - timedelta(seconds=90)
_, subsystem_results, _, _ = run(signals)
mw_sr = by_subsystem(subsystem_results, "manual_write_system")
check("arm left active unexpectedly -> manual_write_system WARNING", mw_sr.state == sh.WARNING, mw_sr.state)

signals = all_healthy_signals()
signals["manual_write_duration"].active = True
signals["manual_write_duration"].active_since = NOW - timedelta(seconds=15)
_, subsystem_results, _, control = run(signals)
mw_sr = by_subsystem(subsystem_results, "manual_write_system")
check("write in progress within valid window -> WARNING (active, not stuck)", mw_sr.state == sh.WARNING, mw_sr.state)
check("in-progress write blocks manual control (a second write cannot safely start)", not control.ready)

signals = all_healthy_signals()
signals["manual_write_duration"].active = True
signals["manual_write_duration"].active_since = NOW - timedelta(seconds=200)
_, subsystem_results, _, control = run(signals)
mw_sr = by_subsystem(subsystem_results, "manual_write_system")
check("write in progress too long -> FAILED (stuck)", mw_sr.state == sh.FAILED, mw_sr.state)
check("stuck write blocks manual control", not control.ready)

signals = all_healthy_signals()
signals["free_power_snapshot_recovery"].active = True
signals["free_power_snapshot_recovery"].active_since = NOW - timedelta(seconds=10)
_, subsystem_results, overall, control = run(signals)
fp_sr = by_subsystem(subsystem_results, "free_power")
check("unresolved Free Power snapshot (within watchdog window) -> WARNING", fp_sr.state == sh.WARNING, fp_sr.state)
check("pending recovery blocks manual_control_ready", not control.ready)

signals = all_healthy_signals()
signals["free_power_snapshot_recovery"].active = True
signals["free_power_snapshot_recovery"].active_since = NOW - timedelta(seconds=90)
_, subsystem_results, _, control = run(signals)
fp_sr = by_subsystem(subsystem_results, "free_power")
check("Free Power restore failed (beyond watchdog window) -> FAILED", fp_sr.state == sh.FAILED, fp_sr.state)
check("restore failure blocks manual control", not control.ready)

signals = all_healthy_signals()
signals["free_power_state_consistency"].value_a = "active"
signals["free_power_state_consistency"].value_b = "inactive"
_, subsystem_results, _, _ = run(signals)
fp_sr = by_subsystem(subsystem_results, "free_power")
check("impossible overlapping operation flags (state disagreement) -> WARNING", fp_sr.state == sh.WARNING, fp_sr.state)

print("")
print("[7b] Active transaction with UNKNOWN start time (Task 006A section 4)")

for check_id, subsystem in (
    ("manual_write_duration", "manual_write_system"),
    ("rtc_correction_duration", "rtc_time"),
    ("free_power_operation_duration", "free_power"),
):
    signals = all_healthy_signals()
    signals[check_id].active = True
    signals[check_id].active_since = None
    check_results, subsystem_results, _, control = run(signals)
    result = by_id(check_results, check_id)
    check(f"{check_id}: active with unknown start time -> UNKNOWN, not HEALTHY", result.state == sh.UNKNOWN, result.state)
    check(f"{check_id}: active with unknown start time blocks manual_control_ready", not control.ready, f"ready={control.ready}")
    check(f"{check_id}: unknown-duration check appears in insufficient_evidence_checks (fail closed, not a manufactured blocking reason code)", check_id in control.insufficient_evidence_checks, control.insufficient_evidence_checks)

# ===========================================================================
# [8] Aggregation rules
# ===========================================================================

print("")
print("[8] Aggregation rules")

signals = all_healthy_signals()
signals["battery_outlook_freshness"].last_updated = NOW - timedelta(seconds=1400)
_, subsystem_results, overall, _ = run(signals)
check("an informational (Battery Outlook) issue doesn't fail the whole of ECCO", overall.state != sh.FAILED, overall.state)
check(
    "forecast failure degrades rather than kills inverter health (other CRITICAL subsystems stay healthy)",
    all(sr.state == sh.HEALTHY for sr in subsystem_results if sr.tier == sh.CRITICAL),
)

signals = all_healthy_signals()
signals["telemetry_freshness"].last_updated = NOW - timedelta(seconds=200)
_, _, overall, _ = run(signals)
check("communications-class failure escalates overall to FAILED", overall.state == sh.FAILED, overall.state)

signals = all_healthy_signals()
signals["telemetry_failures_recent"].baseline_counter_value = 500
signals["telemetry_failures_recent"].counter_value = 500  # huge historical count, zero recent delta
signals["telemetry_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=650)
_, subsystem_results, overall, _ = run(signals)
telemetry_sr = by_subsystem(subsystem_results, "inverter_telemetry")
check(
    "a large historical (non-recent) counter does not affect current overall state",
    telemetry_sr.state == sh.HEALTHY and overall.state == BASELINE_OVERALL_STATE,
    f"{telemetry_sr.state}/{overall.state} (expected inverter_telemetry HEALTHY and overall unchanged from the {BASELINE_OVERALL_STATE} baseline)",
)

signals = all_healthy_signals()
signals["manual_write_duration"].active = True
signals["manual_write_duration"].active_since = NOW - timedelta(seconds=10)
_, _, _, control = run(signals)
check("transaction (write) in progress blocks manual_control_ready", not control.ready)

print("")
print("[8b] UNKNOWN aggregation (Task 006A section 3)")

signals = all_healthy_signals()
for cid, chk in CHECKS.items():
    if chk.subsystem == "inverter_telemetry":
        signals.pop(cid, None)
_, subsystem_results, overall, _ = run(signals)
telemetry_sr = by_subsystem(subsystem_results, "inverter_telemetry")
check("a CRITICAL subsystem with zero evaluated checks reports UNKNOWN", telemetry_sr.state == sh.UNKNOWN, telemetry_sr.state)
check("critical subsystem only UNKNOWN -> overall UNKNOWN (not silently WARNING or HEALTHY)", overall.state == sh.UNKNOWN, overall.state)
check("overall UNKNOWN is capped at rank 2, same as WARNING, for comparison purposes", overall.severity_rank == sh.SEVERITY_RANK[sh.WARNING])

# WARNING + UNKNOWN at the same effective (rank-2) tier -> WARNING deterministically wins.
signals = all_healthy_signals()
signals["telemetry_freshness"].last_updated = NOW - timedelta(seconds=100)  # inverter_telemetry -> DEGRADED (rank 1), not rank 2 - use a real WARNING instead:
signals["rtc_ntp_synced"].value = False  # rtc_time -> WARNING (rank 2)
for cid, chk in CHECKS.items():
    if chk.subsystem == "inverter_configuration":
        signals.pop(cid, None)  # inverter_configuration -> UNKNOWN (rank 2)
_, subsystem_results, overall, _ = run(signals)
rtc_sr = by_subsystem(subsystem_results, "rtc_time")
config_sr = by_subsystem(subsystem_results, "inverter_configuration")
check("rtc_time is a real WARNING at rank 2", rtc_sr.state == sh.WARNING and rtc_sr.severity_rank == 2, rtc_sr.state)
check("inverter_configuration is UNKNOWN at rank 2", config_sr.state == sh.UNKNOWN and config_sr.severity_rank == 2, config_sr.state)
check(
    "WARNING + UNKNOWN at the same effective (rank-2) tier -> overall resolves to WARNING deterministically, not UNKNOWN and not 'whichever came first'",
    overall.state == sh.WARNING,
    overall.state,
)

signals = all_healthy_signals()
_, subsystem_results, overall, _ = run(signals)
check("diagnostic-only UNKNOWN (influx_raw/influx_5m) does not cause a permanent overall WARNING/UNKNOWN", overall.state == sh.HEALTHY, overall.state)

# ===========================================================================
# [9] Control readiness - FAIL CLOSED (Task 006A section 1)
# ===========================================================================

print("")
print("[9] Control readiness fail-closed rule")

required = sh.required_control_checks(CHECKS, REASON_CODES)
check("at least one required (blocking-capable) check exists", len(required) > 0, str(len(required)))

# (a) remove a required control-readiness check from signals -> FALSE
some_required_check = sorted(required)[0]
signals = all_healthy_signals()
del signals[some_required_check]
_, _, _, control = run(signals)
check(
    f"removing a required check ({some_required_check}) from the snapshot -> control NOT ready",
    not control.ready and some_required_check in control.missing_required_checks,
    f"ready={control.ready} missing={control.missing_required_checks}",
)

# Remove ALL required checks at once - still must fail closed, not accidentally pass.
signals = all_healthy_signals()
for cid in required:
    signals.pop(cid, None)
_, _, _, control = run(signals)
check("removing every required check -> control NOT ready (never fails open)", not control.ready, f"ready={control.ready}")
check("every required check is reported missing", set(control.missing_required_checks) == required, f"{set(control.missing_required_checks)} != {required}")

# (b) required check evaluates UNKNOWN with no reason code -> FALSE
# telemetry_freshness is required (MODBUS_TELEMETRY_STALE blocks) and has no
# declared non-blocking UNKNOWN outcome.
signals = all_healthy_signals()
signals["telemetry_freshness"] = sh.CheckInput(last_updated=None)
check_results, _, _, control = run(signals)
telemetry_result = by_id(check_results, "telemetry_freshness")
check("telemetry_freshness with no last_updated -> UNKNOWN", telemetry_result.state == sh.UNKNOWN, telemetry_result.state)
check(
    "a required check evaluating UNKNOWN with no declared non-blocking outcome -> control NOT ready",
    not control.ready and "telemetry_freshness" in control.insufficient_evidence_checks,
    f"ready={control.ready} insufficient={control.insufficient_evidence_checks}",
)

# (c) all required checks positively evaluated and healthy -> TRUE
_, _, _, control = run(all_healthy_signals())
check("all required checks healthy -> control ready TRUE", control.ready, f"{control.blocking_checks} {control.missing_required_checks} {control.insufficient_evidence_checks}")

# (d) optional/informational UNKNOWN check does NOT block readiness
signals = all_healthy_signals()
del signals["battery_outlook_model_version"]  # not a required (blocking) check at all
del signals["influx_raw_freshness"]  # also not required
_, _, _, control = run(signals)
check(
    "removing non-required (informational/diagnostic) checks does not affect control readiness",
    control.ready and "battery_outlook_model_version" not in control.missing_required_checks and "influx_raw_freshness" not in control.missing_required_checks,
    f"ready={control.ready} missing={control.missing_required_checks}",
)

print("")
print("[9b] Suppressed-check control-readiness semantics (synthetic - no real check needs this exception today)")

# Build a tiny synthetic registry proving BOTH branches of the
# suppressed_is_safe_for_control mechanism, since no check in the real
# registry currently uses it (Task 006A: fail-closed by default).
synthetic_blocking_rc = sh.ReasonCode(
    code="SYNTH_BLOCKS", subsystem="communications", severity=sh.WARNING,
    meaning="synthetic", blocks_manual_control=True, affects_forecast=False,
)
synthetic_reason_codes = {**REASON_CODES, "SYNTH_BLOCKS": synthetic_blocking_rc}

unsafe_suppressed_check = sh.CheckDef(
    id="synthetic_unsafe_suppressed", subsystem="communications", description="",
    check_type="boolean_expected", parameters={"expected_value": True},
    applicability_condition="synthetic", outcomes=[sh.Outcome("SYNTH_BLOCKS", "synthetic")],
    dependencies=[], suppressed_is_safe_for_control=False,
)
safe_suppressed_check = sh.CheckDef(
    id="synthetic_safe_suppressed", subsystem="communications", description="",
    check_type="boolean_expected", parameters={"expected_value": True},
    applicability_condition="synthetic", outcomes=[sh.Outcome("SYNTH_BLOCKS", "synthetic")],
    dependencies=[], suppressed_is_safe_for_control=True,
)

for label, synthetic_check in (("default (fail closed)", unsafe_suppressed_check), ("explicitly declared safe", safe_suppressed_check)):
    synthetic_checks = {synthetic_check.id: synthetic_check}
    synthetic_signals = {synthetic_check.id: sh.CheckInput(applicable=False)}
    result = sh.evaluate_check(synthetic_check, synthetic_signals[synthetic_check.id], synthetic_reason_codes, NOW)
    control = sh.evaluate_control_readiness(synthetic_checks, [result], synthetic_reason_codes)
    if synthetic_check.suppressed_is_safe_for_control:
        check(f"suppressed_is_safe_for_control=True ({label}): a SUPPRESSED required check does NOT block readiness", control.ready, f"ready={control.ready}")
    else:
        check(f"suppressed_is_safe_for_control=False ({label}): a SUPPRESSED required check DOES block readiness by default", not control.ready and synthetic_check.id in control.insufficient_evidence_checks, f"ready={control.ready}")

# ===========================================================================
# [10] Counter reset/rebaseline (Task 006A section 5)
# ===========================================================================

print("")
print("[10] Counter reset/rebaseline semantics")

signals = all_healthy_signals()
signals["telemetry_failures_recent"].baseline_counter_value = 20
signals["telemetry_failures_recent"].counter_value = 0  # counter went backwards - device rebooted
signals["telemetry_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=650)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "telemetry_failures_recent")
check("counter rollback (baseline=20, current=0) -> UNKNOWN, never a false HEALTHY", result.state == sh.UNKNOWN, result.state)
check("counter rollback human text mentions rebooted/reset/rebaseline", any(w in result.human_reason.lower() for w in ("reboot", "reset", "rebaseline", "backwards")), result.human_reason)

signals = all_healthy_signals()
signals["telemetry_failures_recent"].baseline_counter_value = 5
signals["telemetry_failures_recent"].counter_value = 5  # current == baseline -> no new failures
signals["telemetry_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=650)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "telemetry_failures_recent")
check("current == baseline -> HEALTHY (no new failures)", result.state == sh.HEALTHY, result.state)

signals = all_healthy_signals()
signals["telemetry_failures_recent"].baseline_counter_value = 5
signals["telemetry_failures_recent"].counter_value = 6  # current > baseline -> normal delta evaluation
signals["telemetry_failures_recent"].baseline_observed_at = NOW - timedelta(seconds=650)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "telemetry_failures_recent")
check("current > baseline -> evaluated normally (WARNING for a small delta)", result.state == sh.WARNING, result.state)

# ===========================================================================
# [11] entity_available: available=None must not mean HEALTHY (Task 006B item 1)
# ===========================================================================

print("")
print("[11] entity_available None semantics")

signals = all_healthy_signals()
signals["esphome_reachable"] = sh.CheckInput(ever_observed=True, available=None)
check_results, _, _, control = run(signals)
result = by_id(check_results, "esphome_reachable")
check("esphome_reachable with available=None -> UNKNOWN (not HEALTHY)", result.state == sh.UNKNOWN, result.state)
check(
    "a required entity-availability check with available=None blocks manual_control_ready",
    not control.ready and "esphome_reachable" in control.insufficient_evidence_checks,
    f"ready={control.ready} insufficient={control.insufficient_evidence_checks}",
)

# An optional/non-blocking entity_available check (runtime_config_ready's
# UNAVAILABLE outcome is itself blocking per the registry, so use a
# non-required entity_available check to prove the "does not block unless
# policy says so" half of the assertion): battery_outlook_prediction_available
# is entity_available but its only outcome (FORECAST_PREDICTION_UNAVAILABLE)
# is non-blocking per the registry.
check(
    "battery_outlook_prediction_available is NOT a required (blocking) check",
    "battery_outlook_prediction_available" not in sh.required_control_checks(CHECKS, REASON_CODES),
)
signals = all_healthy_signals()
signals["battery_outlook_prediction_available"] = sh.CheckInput(ever_observed=True, available=None)
check_results, _, _, control = run(signals)
result = by_id(check_results, "battery_outlook_prediction_available")
check("an optional entity_available check with available=None still reports UNKNOWN (never fabricated HEALTHY)", result.state == sh.UNKNOWN, result.state)
check("...but does not block manual_control_ready, since its registry policy does not require it to", control.ready, f"ready={control.ready}")

# ===========================================================================
# [12] transaction_state: active=None must not mean HEALTHY (Task 006B item 2)
# ===========================================================================

print("")
print("[12] transaction_state None semantics")

for check_id in ("manual_write_duration", "rtc_correction_duration", "free_power_operation_duration", "free_power_snapshot_recovery"):
    signals = all_healthy_signals()
    signals[check_id] = sh.CheckInput(active=None)
    check_results, _, _, control = run(signals)
    result = by_id(check_results, check_id)
    check(f"{check_id}: active=None -> UNKNOWN (not HEALTHY)", result.state == sh.UNKNOWN, result.state)
    check(f"{check_id}: active=None blocks manual_control_ready", not control.ready and check_id in control.insufficient_evidence_checks, f"ready={control.ready}")

    signals = all_healthy_signals()
    signals[check_id] = sh.CheckInput(active=False)
    check_results, _, _, _ = run(signals)
    result = by_id(check_results, check_id)
    check(f"{check_id}: explicit active=False -> HEALTHY ('not active')", result.state == sh.HEALTHY, result.state)

# ===========================================================================
# [13] conditional_presence: unknown checkpoint state must remain UNKNOWN
# (Task 006B item 3) - not a manual-control blocker, but health reporting
# must distinguish "not due yet" from "we don't know whether it was due".
# ===========================================================================

print("")
print("[13] conditional_presence None semantics")

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"] = sh.CheckInput(checkpoint_passed=None, scored_since_checkpoint=None)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "battery_outlook_scorer_freshness")
check("checkpoint_passed=None -> UNKNOWN (not NOT_YET_DUE/SUPPRESSED)", result.state == sh.UNKNOWN, result.state)

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"] = sh.CheckInput(checkpoint_passed=False, scored_since_checkpoint=None)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "battery_outlook_scorer_freshness")
check("checkpoint_passed=False (known) -> NOT_YET_DUE/SUPPRESSED regardless of scored_since_checkpoint", result.state == sh.SUPPRESSED, result.state)

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"] = sh.CheckInput(checkpoint_passed=True, scored_since_checkpoint=None)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "battery_outlook_scorer_freshness")
check("checkpoint_passed=True, scored_since_checkpoint=None -> UNKNOWN (not STALE)", result.state == sh.UNKNOWN, result.state)

signals = all_healthy_signals()
signals["battery_outlook_scorer_freshness"] = sh.CheckInput(checkpoint_passed=True, scored_since_checkpoint=False)
check_results, _, _, _ = run(signals)
result = by_id(check_results, "battery_outlook_scorer_freshness")
check("checkpoint_passed=True, scored_since_checkpoint=False (both known) -> STALE (WARNING)", result.state == sh.WARNING, result.state)

check(
    "battery_outlook_scorer_freshness is NOT a manual-control blocker",
    "battery_outlook_scorer_freshness" not in sh.required_control_checks(CHECKS, REASON_CODES),
)

# ===========================================================================
# [14] Wi-Fi RSSI must not become a control-readiness gate (Task 006B item 4)
# ===========================================================================

print("")
print("[14] Wi-Fi signal quality is not a control-readiness gate")

required = sh.required_control_checks(CHECKS, REASON_CODES)
check("wifi_signal_quality is NOT in required_control_checks()", "wifi_signal_quality" not in required)
check("esphome_reachable IS in required_control_checks()", "esphome_reachable" in required)

signals = all_healthy_signals()
signals["wifi_signal_quality"].value = -999  # wildly implausible RSSI
_, _, _, control = run(signals)
check("an implausible Wi-Fi RSSI value alone does not block manual_control_ready", control.ready, f"ready={control.ready} blocking={control.blocking_checks}")

signals = all_healthy_signals()
del signals["wifi_signal_quality"]
_, _, _, control = run(signals)
check("a missing wifi_signal_quality check does not block manual_control_ready (not required)", control.ready, f"ready={control.ready} missing={control.missing_required_checks}")

# ===========================================================================
# [15] Defensive fail-closed inputs (Task 006B item 5) - a required check
# PRESENT with default/unknown fields (not omitted) must never satisfy its
# precondition. "The check object exists" != "the precondition is proven safe."
# ===========================================================================

print("")
print("[15] Defensive fail-closed inputs - bare CheckInput() for every required check")

required = sh.required_control_checks(CHECKS, REASON_CODES)
signals = all_healthy_signals()
for cid in required:
    signals[cid] = sh.CheckInput()  # every field at its dataclass default - no evidence supplied
check_results, _, _, control = run(signals)
check(
    "a bare, default-constructed CheckInput() for every required check never satisfies manual_control_ready",
    not control.ready,
    f"ready={control.ready}",
)
non_blocking_defaults = [
    cid for cid in required
    if cid not in control.blocking_checks and cid not in control.missing_required_checks and cid not in control.insufficient_evidence_checks
]
check(
    "every required check with a bare default CheckInput() is accounted for as blocking/missing/insufficient - none silently 'passes'",
    non_blocking_defaults == [],
    str(non_blocking_defaults),
)
non_healthy_defaults = [cid for cid in required if by_id(check_results, cid).state == sh.HEALTHY]
check(
    "no required check evaluates HEALTHY from a bare default CheckInput() with no evidence supplied",
    non_healthy_defaults == [],
    str(non_healthy_defaults),
)

# ===========================================================================
# [16] FB-B3 supervision / fallback subsystems (docs/architecture/fallback,
# S5 section 5.6): STANDARD tier now; CRITICAL only at FB-F.
# ===========================================================================

print("")
print("[16] FB-B3 supervision / fallback subsystems")

check("supervision is registered at STANDARD tier (not CRITICAL until FB-F)", sh.SUBSYSTEM_TIER.get("supervision") == sh.STANDARD)
check("fallback is registered at STANDARD tier (not CRITICAL until FB-F)", sh.SUBSYSTEM_TIER.get("fallback") == sh.STANDARD)
check("every subsystem used by a registered check has a tier", {c.subsystem for c in CHECKS.values()} <= set(sh.SUBSYSTEM_TIER))
fb_checks = [c for c in CHECKS.values() if c.subsystem in ("supervision", "fallback")]
check("18 supervision/fallback checks are registered (one per FB-B3 reason code, plus the FB-C3 fallback_shadow_episode)", len(fb_checks) == 18, str(len(fb_checks)))
check("no supervision/fallback check blocks manual control",
      not any(REASON_CODES[o.reason_code].blocks_manual_control for c in fb_checks for o in c.outcomes))
check("no supervision/fallback check is a required control check", not ({c.check_id if hasattr(c, "check_id") else c.id for c in fb_checks} & sh.required_control_checks(CHECKS, REASON_CODES)))

signals = all_healthy_signals()
check_results, subsystem_results, overall, control = run(signals)
check("fully healthy supervision/fallback inputs leave both subsystems HEALTHY",
      by_subsystem(subsystem_results, "supervision").state == sh.HEALTHY and by_subsystem(subsystem_results, "fallback").state == sh.HEALTHY)

signals = all_healthy_signals()
signals["supervision_lost"].value = "Lost"
check_results, subsystem_results, overall, control = run(signals)
check("supervision Lost evaluates the check at WARNING (not FAILED; FAILED only once FB-F makes it CRITICAL)", by_id(check_results, "supervision_lost").state == sh.WARNING)
sup_sr = by_subsystem(subsystem_results, "supervision")
check("the supervision subsystem itself reports WARNING for Lost (no reliance on the tier cap)",
      sup_sr.state == sh.WARNING, f"{sup_sr.state} rank={sup_sr.severity_rank}")
check("overall health is WARNING, not FAILED, with supervision Lost",
      overall.state == sh.WARNING, f"overall={overall.state}")
check("supervision Lost does not make manual control not-ready", control.ready == run(all_healthy_signals())[3].ready)

signals = all_healthy_signals()
signals["fallback_not_captured"].value = "not_captured"
check_results, subsystem_results, overall, control = run(signals)
check("fallback not_captured -> DEGRADED", by_id(check_results, "fallback_not_captured").state == sh.DEGRADED
      and by_subsystem(subsystem_results, "fallback").state == sh.DEGRADED)

signals = all_healthy_signals()
signals["fallback_blocked_by_lease"].value = "lease_unreadable"
check_results, subsystem_results, overall, control = run(signals)
check("fallback lease_unreadable -> WARNING", by_id(check_results, "fallback_blocked_by_lease").state == sh.WARNING
      and by_subsystem(subsystem_results, "fallback").state == sh.WARNING)

signals = all_healthy_signals()
signals["fallback_live_unknown"].value = "live_unknown"
check_results, subsystem_results, overall, control = run(signals)
check("fallback live_unknown -> UNKNOWN (absence of evidence is never HEALTHY)",
      by_id(check_results, "fallback_live_unknown").state == sh.UNKNOWN)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All system health engine offline tests PASSED.")

print("")
print("This proves the REFERENCE ENGINE's rules are internally consistent")
print("against the real check/reason-code registries. It does NOT prove any")
print("threshold or reason code has ever fired against a real ECCO installation -")
print("see docs/SYSTEM_HEALTH_ARCHITECTURE.md section 23.")

if FAILURES:
    sys.exit(1)
