#!/usr/bin/env python3
"""ECCO Pro - pure offline system health reference engine (Task 006,
hardened in Task 006A after safety review).

Zero I/O: no Home Assistant API, no network, no Modbus, no InfluxDB, no
file mutation beyond reading the two YAML registries this module loads
check definitions from. Every function that needs "the current time"
takes it as an explicit `now: datetime` parameter - nothing in this
module calls `datetime.now()`/`utcnow()` itself, so callers (including
tests) always control time explicitly.

This is a REFERENCE/TEST engine proving the design in
docs/SYSTEM_HEALTH_ARCHITECTURE.md is internally consistent - it is
not the production Home Assistant implementation (see
docs/SYSTEM_HEALTH_HA_DESIGN.md for that). Nothing here writes
anything, recovers anything, or contacts anything.

Caller contract: the caller (a human, a test, or eventually a future
HA integration) supplies a `dict[check_id, CheckInput]` snapshot of
current signal values - this module never fetches signals itself.

TASK 006A SAFETY RULE - FAIL CLOSED: manual_control_ready is computed
from the COMPLETE set of checks the registry declares capable of
blocking manual control (any check with at least one blocking
outcome), not merely from whichever checks happen to be present in a
given signal snapshot. A required check that is missing, UNKNOWN, or
SUPPRESSED-without-an-explicit-safety-declaration makes readiness
FALSE, never TRUE. See evaluate_control_readiness().
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKS_PATH = ROOT / "registry" / "system_health_checks.yaml"
DEFAULT_REASON_CODES_PATH = ROOT / "registry" / "health_reason_codes.yaml"

# --- health state model (docs/SYSTEM_HEALTH_ARCHITECTURE.md section 2) ----

HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
WARNING = "WARNING"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
SUPPRESSED = "SUPPRESSED"

VALID_STATES = {HEALTHY, DEGRADED, WARNING, FAILED, UNKNOWN, SUPPRESSED}

# HEALTHY == SUPPRESSED == 0 < DEGRADED == 1 < WARNING == UNKNOWN == 2 < FAILED == 3
#
# Task 006A fix: WARNING and UNKNOWN share a numeric rank (both "requires
# attention, not yet a confirmed FAILED-level problem") for THRESHOLD/CAP
# comparison purposes only. They are NEVER collapsed into a single label
# when reporting a state - see _resolve_flavor_at_rank(), which is the
# ONLY place a rank is turned back into a displayed state, and which
# always prefers a real/definite finding (WARNING) over an absence of
# evidence (UNKNOWN) at the same rank, and never silently picks
# "whichever happened to be evaluated first".
SEVERITY_RANK = {
    HEALTHY: 0,
    SUPPRESSED: 0,
    DEGRADED: 1,
    WARNING: 2,
    UNKNOWN: 2,
    FAILED: 3,
}
_DEFINITE_STATE_AT_RANK = {0: HEALTHY, 1: DEGRADED, 2: WARNING, 3: FAILED}


def _resolve_flavor_at_rank(flavors: list[str], rank: int) -> str:
    """Deterministically resolves which STATE to report for a group of
    results that all share the same numeric severity rank. Never
    "whichever happens to appear first in registry/evaluation order":

    - the rank's own "definite" state (a real, positive finding) always
      wins if present, e.g. a real WARNING beats an UNKNOWN at rank 2,
      a real FAILED is the only possibility at rank 3.
    - otherwise UNKNOWN wins if present (absence of evidence is still
      reported, never silently downgraded to HEALTHY).
    - otherwise (rank 0 only, no HEALTHY and no UNKNOWN present) every
      contributor is SUPPRESSED.
    """
    definite = _DEFINITE_STATE_AT_RANK[rank]
    if definite in flavors:
        return definite
    if UNKNOWN in flavors:
        return UNKNOWN
    return SUPPRESSED if rank == 0 else definite


# --- subsystem criticality tiers (docs/SYSTEM_HEALTH_ARCHITECTURE.md section 3) --

CRITICAL = "CRITICAL"
STANDARD = "STANDARD"
INFORMATIONAL = "INFORMATIONAL"

TIER_CAP = {CRITICAL: 3, STANDARD: 2, INFORMATIONAL: 1}

SUBSYSTEM_TIER: dict[str, str] = {
    "communications": CRITICAL,
    "inverter_telemetry": CRITICAL,
    "inverter_configuration": CRITICAL,
    "rtc_time": CRITICAL,
    "manual_write_system": CRITICAL,
    "free_power": CRITICAL,
    "runtime_configuration": CRITICAL,
    "home_assistant": STANDARD,
    "canonical_telemetry": STANDARD,
    "influx_raw": STANDARD,
    "influx_5m": STANDARD,
    "deployment_consistency": STANDARD,
    "supervision": STANDARD,
    "fallback": STANDARD,
    "battery_outlook": INFORMATIONAL,
    "battery_outlook_scorer": INFORMATIONAL,
}

# --- rollup participation (Task 006A section 3) ----------------------------
#
# Not every check can be continuously/automatically evaluated. A check
# whose only real signal source is a manual/ad-hoc diagnostic with no
# fixed threshold (e.g. an Influx script with no evidenced cadence), or
# whose nature is a PERMANENT repository-level limitation (e.g. "no live
# entity exists to verify this"), is not a transient problem that should
# make ECCO's automatic overall health permanently WARNING/UNKNOWN. Such
# checks are still evaluated and still visible (see
# SubsystemResult.diagnostic_results) but are excluded from
# evaluate_subsystem()/evaluate_overall()'s automatic rollup.
ROLLUP_AUTOMATIC = "automatic"
ROLLUP_DIAGNOSTIC_ONLY = "diagnostic_only"
ROLLUP_MANUAL_ONLY = "manual_only"
VALID_ROLLUP_PARTICIPATION = {ROLLUP_AUTOMATIC, ROLLUP_DIAGNOSTIC_ONLY, ROLLUP_MANUAL_ONLY}


# ============================================================================
# Check/reason-code definitions (loaded from the YAML registries)
# ============================================================================

@dataclass(frozen=True)
class ReasonCode:
    code: str
    subsystem: str
    severity: str
    meaning: str
    blocks_manual_control: bool
    affects_forecast: bool


@dataclass(frozen=True)
class Outcome:
    reason_code: str
    condition: str


@dataclass(frozen=True)
class CheckDef:
    id: str
    subsystem: str
    description: str
    check_type: str
    parameters: dict
    applicability_condition: str | None
    outcomes: list[Outcome]
    dependencies: list[str]
    rollup_participation: str = ROLLUP_AUTOMATIC
    suppressed_is_safe_for_control: bool = False


def load_reason_codes(path: Path = DEFAULT_REASON_CODES_PATH) -> dict[str, ReasonCode]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result = {}
    for rc in data.get("reason_codes", []):
        result[rc["code"]] = ReasonCode(
            code=rc["code"],
            subsystem=rc["subsystem"],
            severity=rc["severity"],
            meaning=rc["meaning"],
            blocks_manual_control=bool(rc["blocks_manual_control"]),
            affects_forecast=bool(rc["affects_forecast"]),
        )
    return result


def load_check_registry(path: Path = DEFAULT_CHECKS_PATH) -> dict[str, CheckDef]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    result = {}
    for chk in data.get("checks", []):
        outcomes = [Outcome(o["reason_code"], o["condition"]) for o in chk.get("outcomes", [])]
        result[chk["id"]] = CheckDef(
            id=chk["id"],
            subsystem=chk["subsystem"],
            description=chk.get("description", ""),
            check_type=chk["check_type"],
            parameters=chk.get("parameters") or {},
            applicability_condition=chk.get("applicability_condition"),
            outcomes=outcomes,
            dependencies=list(chk.get("dependencies") or []),
            rollup_participation=chk.get("rollup_participation") or ROLLUP_AUTOMATIC,
            suppressed_is_safe_for_control=bool(chk.get("suppressed_is_safe_for_control", False)),
        )
    return result


# ============================================================================
# Caller-supplied signal input
# ============================================================================

@dataclass
class CheckInput:
    """Plain snapshot of whatever a single check needs. Most fields are
    unused by any given check_type - the caller only fills in what that
    check's check_type actually reads (see evaluate_check).

    Task 006B review note on `ever_observed`'s default (item 6): kept as
    `True`, deliberately NOT flipped to `False`. The two fields serve
    different roles: `ever_observed` answers "has this entity ever
    reported anything, historically" while `available` answers "what is
    its CURRENT state." A caller that explicitly sets `available=False`
    (or `True`) has, by definition, observed something - flipping
    `ever_observed`'s default to `False` would make that explicit,
    real evidence get silently overridden back into UNKNOWN by the
    now-also-failing `ever_observed` check evaluated first, which is a
    *regression* (discarding real evidence), not an improvement. The
    actual fail-open bug (`available is None` falling through to
    HEALTHY) is fixed directly in `evaluate_check`'s `entity_available`
    branch instead, which is the correct place for it: a fully-default
    `CheckInput()` now correctly evaluates UNKNOWN for
    `entity_available` (via `available is None`, independent of
    `ever_observed`), `transaction_state` (via `active is None`), and
    `conditional_presence` (via `checkpoint_passed is None`) - see
    `health/tests/test_system_health.py`'s "[11] Defensive fail-closed
    inputs" section, which asserts this directly for every required
    check type against a bare `CheckInput()`."""

    applicable: bool = True

    # entity_available / boolean_expected / numeric_range / text_state
    ever_observed: bool = True
    available: bool | None = None
    value: Any = None

    # freshness / timestamp_age / canonical_stale_raw_fresh
    last_updated: datetime | None = None

    # transaction_state
    active: bool | None = None
    active_since: datetime | None = None

    # failure_counter_delta
    counter_value: int | None = None
    baseline_counter_value: int | None = None
    baseline_observed_at: datetime | None = None
    recovered: bool = False

    # cross_source_agreement
    value_a: Any = None
    value_b: Any = None
    timestamp_a: datetime | None = None
    timestamp_b: datetime | None = None

    # history_depth
    depth_value: float | None = None

    # conditional_presence (2-outcome scorer-style checks)
    checkpoint_passed: bool | None = None
    scored_since_checkpoint: bool | None = None


@dataclass
class CheckResult:
    check_id: str
    subsystem: str
    state: str
    reason_codes: list[str]
    human_reason: str
    age_seconds: float | None = None
    rollup_participation: str = ROLLUP_AUTOMATIC


@dataclass
class SubsystemResult:
    subsystem: str
    tier: str
    state: str
    severity_rank: int
    reason_codes: list[str]
    human_reason: str
    check_results: list[CheckResult]
    diagnostic_results: list[CheckResult] = field(default_factory=list)
    contributes_to_overall: bool = True


@dataclass
class OverallHealthResult:
    state: str
    severity_rank: int
    contributing_subsystems: list[str]
    reason_codes: list[str]


@dataclass
class ControlReadinessResult:
    ready: bool
    blocking_reason_codes: list[str]
    blocking_checks: list[str]
    missing_required_checks: list[str] = field(default_factory=list)
    insufficient_evidence_checks: list[str] = field(default_factory=list)


# ============================================================================
# Single-check evaluation
# ============================================================================

def _pick_by_threshold(outcomes: list[Outcome], params: dict, warn_key: str, fail_key: str, measured: float) -> Outcome | None:
    """Given up to two ordered outcomes and their (possibly partial)
    threshold pair, returns the worst outcome whose threshold the
    measured value has reached, or None if below every threshold."""
    warn_thr = params.get(warn_key)
    fail_thr = params.get(fail_key)

    if len(outcomes) == 1:
        # A single-outcome check should declare exactly one of the two
        # threshold fields (see registry/system_health_checks.yaml's
        # header and tools/validate_system_health_checks.py, which
        # rejects a single-outcome check declaring both). Defensively
        # prefer the lower/earlier threshold if both are somehow set,
        # since with only one outcome the earlier trigger point is the
        # meaningful one.
        thr = warn_thr if warn_thr is not None else fail_thr
        if thr is not None and measured >= thr:
            return outcomes[0]
        return None

    candidates: list[tuple[float, Outcome]] = []
    if warn_thr is not None:
        candidates.append((warn_thr, outcomes[0]))
    if fail_thr is not None and len(outcomes) > 1:
        candidates.append((fail_thr, outcomes[1]))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    for threshold, outcome in candidates:
        if measured >= threshold:
            return outcome
    return None


def evaluate_check(check: CheckDef, signal: CheckInput, reason_codes: dict[str, ReasonCode], now: datetime) -> CheckResult:
    """Evaluates one check against one signal snapshot. Never raises on
    missing/None data - missing evidence maps to UNKNOWN, never to a
    guessed HEALTHY or FAILED."""

    def result(state: str, outcome: Outcome | None, human_reason: str, age_seconds: float | None = None) -> CheckResult:
        codes = [outcome.reason_code] if outcome else []
        return CheckResult(check.id, check.subsystem, state, codes, human_reason, age_seconds, check.rollup_participation)

    if not signal.applicable:
        return result(SUPPRESSED, None, f"Not applicable: {check.applicability_condition}")

    ct = check.check_type
    params = check.parameters

    if ct == "entity_available":
        # Task 006B fix: `available is None` (evidence simply not supplied)
        # must never fall through to the HEALTHY return below, regardless
        # of `ever_observed` - only an explicit `available is True` may
        # report HEALTHY, and only an explicit `available is False` may
        # report the configured unavailable outcome. Truthiness is never
        # relied upon (bool(None) and bool(False) are both falsy, but
        # they are not the same evidence state).
        if not signal.ever_observed:
            unk = next((o for o in check.outcomes if reason_codes[o.reason_code].severity == UNKNOWN), None)
            return result(UNKNOWN, unk, "Never observed - insufficient evidence.")
        if signal.available is None:
            unk = next((o for o in check.outcomes if reason_codes[o.reason_code].severity == UNKNOWN), None)
            return result(UNKNOWN, unk, "Observed before, but current availability is unknown - insufficient evidence.")
        if signal.available is False:
            bad = next((o for o in check.outcomes if reason_codes[o.reason_code].severity != UNKNOWN), check.outcomes[0])
            return result(reason_codes[bad.reason_code].severity, bad, reason_codes[bad.reason_code].meaning)
        # signal.available is True
        return result(HEALTHY, None, "Available.")

    if ct in ("freshness", "timestamp_age"):
        if params.get("thresholds_unresolved"):
            return result(UNKNOWN, check.outcomes[0], "No evidence-based threshold exists for this check - manual/ad-hoc evaluation only.")
        if signal.last_updated is None:
            return result(UNKNOWN, None, "Never updated - insufficient evidence.")
        age = (now - signal.last_updated).total_seconds()
        outcome = _pick_by_threshold(check.outcomes, params, "warning_threshold_seconds", "failure_threshold_seconds", age)
        if outcome is None:
            return result(HEALTHY, None, f"Fresh (age {age:.0f}s).", age)
        return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning, age)

    if ct == "transaction_state":
        # Task 006B fix: `active is None` (we do not know whether a
        # transaction is running at all) must never be treated the same
        # as an explicit `active is False` ("confirmed not active" ->
        # HEALTHY). `not None` and `not False` are both truthy in
        # Python, which is exactly the trap - so this checks identity,
        # not truthiness.
        if signal.active is None:
            return result(UNKNOWN, None, "Whether a transaction is active is unknown - insufficient evidence.")
        if signal.active is False:
            return result(HEALTHY, None, "Not active.")
        # signal.active is True
        if signal.active_since is None:
            # Task 006A fix: an active transaction whose start time is
            # unknown must NEVER be treated as "just started" (duration
            # 0s -> HEALTHY). We know something is active and do not
            # know for how long - that is insufficient evidence, not a
            # clean bill of health, and (via evaluate_control_readiness)
            # must block a new manual action exactly as a known-stuck
            # transaction would.
            return result(UNKNOWN, None, "Active, but its start time is unknown - insufficient evidence to judge duration.")
        duration = (now - signal.active_since).total_seconds()
        outcome = _pick_by_threshold(check.outcomes, params, "warning_threshold_seconds", "failure_threshold_seconds", duration)
        if outcome is None:
            return result(HEALTHY, None, f"Active but below the reporting threshold ({duration:.0f}s).", duration)
        return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning, duration)

    if ct == "boolean_expected":
        if signal.value is None:
            return result(UNKNOWN, None, "No value observed.")
        if bool(signal.value) != bool(params.get("expected_value", True)):
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        return result(HEALTHY, None, "As expected.")

    if ct == "numeric_range":
        if signal.value is None:
            return result(UNKNOWN, None, "No value observed.")
        lo, hi = params.get("min"), params.get("max")
        if (lo is not None and signal.value < lo) or (hi is not None and signal.value > hi):
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        return result(HEALTHY, None, "In range.")

    if ct == "failure_counter_delta":
        return evaluate_counter_delta(check, signal, reason_codes, now)

    if ct == "text_state":
        if signal.value is None:
            return result(UNKNOWN, None, "No value observed.")
        if signal.value in (params.get("failure_values") or []):
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        return result(HEALTHY, None, "Normal state.")

    if ct == "cross_source_agreement":
        value_tolerance = params.get("value_tolerance")
        timestamp_tolerance = params.get("timestamp_tolerance_seconds")
        outcome = check.outcomes[0]
        if value_tolerance is not None:
            if signal.value_a is None or signal.value_b is None:
                return result(UNKNOWN, None, "Cannot compare - one or both values are unavailable.")
            if isinstance(signal.value_a, (int, float)) and isinstance(signal.value_b, (int, float)):
                diff = abs(signal.value_a - signal.value_b)
                if diff > value_tolerance:
                    return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
            else:
                if signal.value_a != signal.value_b:
                    return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
            return result(HEALTHY, None, "Values agree within tolerance.")
        if timestamp_tolerance is not None:
            if signal.timestamp_a is None or signal.timestamp_b is None:
                return result(UNKNOWN, None, "Cannot compare - one or both timestamps are unavailable.")
            diff = abs((signal.timestamp_a - signal.timestamp_b).total_seconds())
            if diff > timestamp_tolerance:
                return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning, diff)
            return result(HEALTHY, None, "Timestamps agree within tolerance.", diff)
        return result(UNKNOWN, None, "No comparison rule configured.")

    if ct == "history_depth":
        if signal.depth_value is None:
            return result(UNKNOWN, None, "No history-depth value observed.")
        if signal.depth_value < params.get("minimum_value", 0):
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        return result(HEALTHY, None, "Sufficient history.")

    if ct == "version_match":
        if signal.value is None:
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        if signal.value is False:
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        return result(HEALTHY, None, "Matches.")

    if ct == "conditional_presence":
        if len(check.outcomes) == 1:
            outcome = check.outcomes[0]
            return result(reason_codes[outcome.reason_code].severity, outcome, reason_codes[outcome.reason_code].meaning)
        not_yet_due, stale = check.outcomes[0], check.outcomes[1]
        # Task 006B fix: "we don't know whether the checkpoint has passed"
        # is a different fact from "the checkpoint has definitely not
        # passed yet" - `checkpoint_passed is None` must not silently
        # become the NOT_YET_DUE/SUPPRESSED outcome. Same for
        # `scored_since_checkpoint is None` once the checkpoint state
        # itself is known.
        if signal.checkpoint_passed is None:
            return result(UNKNOWN, None, "Whether today's checkpoint has passed is unknown - insufficient evidence.")
        if signal.checkpoint_passed is False:
            return result(reason_codes[not_yet_due.reason_code].severity, not_yet_due, reason_codes[not_yet_due.reason_code].meaning)
        # signal.checkpoint_passed is True
        if signal.scored_since_checkpoint is None:
            return result(UNKNOWN, None, "Checkpoint has passed, but whether scoring occurred since then is unknown - insufficient evidence.")
        if signal.scored_since_checkpoint is False:
            return result(reason_codes[stale.reason_code].severity, stale, reason_codes[stale.reason_code].meaning)
        return result(HEALTHY, None, "Scored since the checkpoint.")

    raise ValueError(f"Unhandled check_type {ct!r} for check {check.id!r}")


def evaluate_counter_delta(check: CheckDef, signal: CheckInput, reason_codes: dict[str, ReasonCode], now: datetime) -> CheckResult:
    """Section 6: recent-vs-historical counter delta. A baseline younger
    than the check's window is insufficient evidence (UNKNOWN), not a
    guessed HEALTHY. delta==0 is HEALTHY regardless of the absolute
    counter value. A 'recovered' signal is reflected in the human text
    but never used to escalate severity beyond what the delta itself
    warrants.

    Task 006A fix: a NEGATIVE delta (current < baseline) means the
    cumulative since-boot counter went backwards - almost always an
    ESP32 reboot/reset invalidating the old baseline, not "no new
    failures". This must never be reported as a false HEALTHY; it is
    UNKNOWN pending a fresh baseline captured after the reset."""
    params = check.parameters
    window = params.get("window_seconds", 0)

    if signal.baseline_observed_at is None or signal.baseline_counter_value is None or signal.counter_value is None:
        return CheckResult(check.id, check.subsystem, UNKNOWN, [], "No baseline available yet - insufficient evidence for a delta.", rollup_participation=check.rollup_participation)

    elapsed = (now - signal.baseline_observed_at).total_seconds()
    if elapsed < window:
        return CheckResult(check.id, check.subsystem, UNKNOWN, [], f"Baseline is only {elapsed:.0f}s old (window is {window}s) - not enough evidence yet.", rollup_participation=check.rollup_participation)

    delta = signal.counter_value - signal.baseline_counter_value

    if delta < 0:
        return CheckResult(
            check.id, check.subsystem, UNKNOWN, [],
            f"Counter went backwards (baseline={signal.baseline_counter_value}, current={signal.counter_value}) - "
            f"the device almost certainly rebooted/reset since the baseline was captured; the old baseline is "
            f"invalid and a fresh one is required before this check can report anything but UNKNOWN.",
            rollup_participation=check.rollup_participation,
        )

    if delta == 0:
        return CheckResult(check.id, check.subsystem, HEALTHY, [], "No new failures in the window.", rollup_participation=check.rollup_participation)

    outcome = _pick_by_threshold(check.outcomes, params, "warning_delta", "failure_delta", delta)
    if outcome is None:
        return CheckResult(check.id, check.subsystem, HEALTHY, [], f"Delta {delta} below the reporting threshold.", rollup_participation=check.rollup_participation)

    rc = reason_codes[outcome.reason_code]
    suffix = " (recovered - most recent attempt succeeded)" if signal.recovered else " (ongoing)"
    return CheckResult(check.id, check.subsystem, rc.severity, [outcome.reason_code], rc.meaning + suffix, rollup_participation=check.rollup_participation)


# ============================================================================
# Subsystem / overall / control-readiness aggregation (sections 12-13)
# ============================================================================

def evaluate_subsystem(subsystem: str, check_results: list[CheckResult]) -> SubsystemResult:
    tier = SUBSYSTEM_TIER.get(subsystem)
    if tier is None:
        raise ValueError(f"Unknown subsystem {subsystem!r}")

    relevant = [r for r in check_results if r.subsystem == subsystem]
    automatic = [r for r in relevant if r.rollup_participation == ROLLUP_AUTOMATIC]
    diagnostic = [r for r in relevant if r.rollup_participation != ROLLUP_AUTOMATIC]

    if not automatic:
        if diagnostic:
            # Task 006A fix: this subsystem has no automatically-evaluable
            # checks at all (e.g. influx_raw/influx_5m today, whose only
            # signals are manual Flux diagnostics or a permanently
            # unverifiable claim) - it must NOT contribute an UNKNOWN rank
            # into the automatic overall rollup forever. It is still fully
            # visible (diagnostic_results) for a human/UI to inspect.
            return SubsystemResult(
                subsystem, tier, UNKNOWN, SEVERITY_RANK[UNKNOWN], [],
                f"No automatically-evaluable checks for this subsystem; {len(diagnostic)} diagnostic-only/manual-only "
                f"result(s) available separately and excluded from automatic health.",
                relevant, diagnostic_results=diagnostic, contributes_to_overall=False,
            )
        return SubsystemResult(
            subsystem, tier, UNKNOWN, SEVERITY_RANK[UNKNOWN], [],
            "No checks evaluated for this subsystem.", relevant, diagnostic_results=[], contributes_to_overall=True,
        )

    worst_rank = max(SEVERITY_RANK[r.state] for r in automatic)
    worst_results = [r for r in automatic if SEVERITY_RANK[r.state] == worst_rank]

    if worst_rank == 0:
        if any(r.state == HEALTHY for r in worst_results):
            state, human, reason_codes_out = HEALTHY, "All checks healthy.", []
        else:
            state, human, reason_codes_out = SUPPRESSED, "All checks suppressed (not currently applicable).", []
    else:
        state = _resolve_flavor_at_rank([r.state for r in worst_results], worst_rank)
        matching = [r for r in worst_results if r.state == state]
        human = "; ".join(r.human_reason for r in matching)
        reason_codes_out = [code for r in matching for code in r.reason_codes]

    return SubsystemResult(subsystem, tier, state, worst_rank, reason_codes_out, human, relevant, diagnostic_results=diagnostic, contributes_to_overall=True)


def evaluate_overall(subsystem_results: list[SubsystemResult]) -> OverallHealthResult:
    contributing_candidates = [sr for sr in subsystem_results if sr.contributes_to_overall]
    if not contributing_candidates:
        # Every subsystem is either absent or diagnostic-only-excluded -
        # there is no automatic evidence anywhere. Report UNKNOWN, never
        # a fabricated HEALTHY.
        return OverallHealthResult(UNKNOWN, SEVERITY_RANK[UNKNOWN], [], [])

    capped = [(min(sr.severity_rank, TIER_CAP[sr.tier]), sr) for sr in contributing_candidates]
    overall_rank = max(rank for rank, _ in capped)
    at_max = [sr for rank, sr in capped if rank == overall_rank]

    flavors = []
    for rank, sr in capped:
        if rank != overall_rank:
            continue
        if sr.state == UNKNOWN:
            # Uncertainty stays uncertainty regardless of tier capping -
            # capping only changes which RANK a subsystem's uncertainty
            # counts at, never promotes "we don't know" into a definite
            # claim of degradation.
            flavors.append(UNKNOWN)
        elif sr.severity_rank == overall_rank:
            # Not capped (or capped-to-its-own-rank) - use the real state.
            flavors.append(sr.state)
        else:
            # A real, definite finding that was capped DOWN in severity
            # by tier policy (e.g. a STANDARD-tier FAILED capped to the
            # WARNING band) - still a real/definite finding at the capped
            # rank, not an unknown.
            flavors.append(_DEFINITE_STATE_AT_RANK[overall_rank])

    state = _resolve_flavor_at_rank(flavors, overall_rank)
    contributing = [sr.subsystem for sr in at_max]
    reason_codes: list[str] = []
    for sr in at_max:
        reason_codes.extend(sr.reason_codes)

    return OverallHealthResult(state, overall_rank, contributing, reason_codes)


def required_control_checks(checks: dict[str, CheckDef], reason_codes: dict[str, ReasonCode]) -> set[str]:
    """Every check capable of blocking manual control (has at least one
    outcome whose reason code declares blocks_manual_control: true).
    This is the authoritative "required" set for
    evaluate_control_readiness()'s fail-closed logic - it is computed
    from the registry, never from whatever happens to be present in a
    given signal snapshot."""
    return {
        cid for cid, chk in checks.items()
        if any(reason_codes[o.reason_code].blocks_manual_control for o in chk.outcomes)
    }


def evaluate_control_readiness(
    checks: dict[str, CheckDef],
    check_results: list[CheckResult],
    reason_codes: dict[str, ReasonCode],
) -> ControlReadinessResult:
    """Task 006A FAIL-CLOSED rule: UNKNOWN / not-evaluated / a missing
    safety precondition NEVER means ready. Readiness is computed from
    the COMPLETE set of checks the registry declares capable of
    blocking manual control (required_control_checks()), not merely
    from whichever checks happen to appear in `check_results`.

    For every required check:
      - not evaluated (absent from check_results)               -> FALSE, missing_required_checks
      - evaluated SUPPRESSED, no explicit safety declaration      -> FALSE, insufficient_evidence_checks
      - evaluated SUPPRESSED, suppressed_is_safe_for_control=True -> does not block
      - evaluated UNKNOWN, no explicit non-blocking UNKNOWN outcome
        declared for this check                                  -> FALSE, insufficient_evidence_checks
      - evaluated UNKNOWN via a declared non-blocking outcome      -> does not block
      - evaluated with an active blocking reason code              -> FALSE, blocking_checks
      - evaluated HEALTHY/DEGRADED/WARNING/FAILED with no active
        blocking reason code attached                              -> does not block

    Only when every required check clears its own check above is
    `ready` True. No reason code is manufactured for a missing/unknown
    check - the distinct missing_required_checks/
    insufficient_evidence_checks lists are the honest signal instead."""
    required = required_control_checks(checks, reason_codes)
    results_by_id = {r.check_id: r for r in check_results}

    blocking_checks: list[str] = []
    missing_required_checks: list[str] = []
    insufficient_evidence_checks: list[str] = []
    blocking_reason_codes: list[str] = []

    for cid in sorted(required):
        chk = checks[cid]
        r = results_by_id.get(cid)

        if r is None:
            missing_required_checks.append(cid)
            continue

        if r.state == SUPPRESSED:
            if chk.suppressed_is_safe_for_control:
                continue
            insufficient_evidence_checks.append(cid)
            continue

        if r.state == UNKNOWN:
            declared_non_blocking_unknown = any(
                reason_codes[o.reason_code].severity == UNKNOWN and not reason_codes[o.reason_code].blocks_manual_control
                for o in chk.outcomes
            )
            triggered_a_declared_non_blocking_outcome = bool(r.reason_codes) and all(
                not reason_codes[c].blocks_manual_control for c in r.reason_codes
            )
            if declared_non_blocking_unknown and triggered_a_declared_non_blocking_outcome:
                continue
            insufficient_evidence_checks.append(cid)
            continue

        active_blocking = [c for c in r.reason_codes if reason_codes[c].blocks_manual_control]
        if active_blocking:
            blocking_checks.append(cid)
            blocking_reason_codes.extend(active_blocking)
            continue

        # HEALTHY/DEGRADED/WARNING/FAILED with no currently-active blocking
        # reason code (e.g. telemetry merely DEGRADED, not yet STALE) -
        # this required check does not itself block readiness right now.

    ready = not (blocking_checks or missing_required_checks or insufficient_evidence_checks)
    return ControlReadinessResult(
        ready=ready,
        blocking_reason_codes=blocking_reason_codes,
        blocking_checks=blocking_checks,
        missing_required_checks=missing_required_checks,
        insufficient_evidence_checks=insufficient_evidence_checks,
    )


def evaluate_all(
    checks: dict[str, CheckDef],
    reason_codes: dict[str, ReasonCode],
    signals: dict[str, CheckInput],
    now: datetime,
) -> tuple[list[CheckResult], list[SubsystemResult], OverallHealthResult, ControlReadinessResult]:
    """Convenience wrapper: evaluates every check present in `signals`,
    rolls up every subsystem the registry defines, computes overall
    health and control readiness. Checks with no supplied signal are
    simply not evaluated (not fabricated as UNKNOWN input) -
    evaluate_control_readiness() independently detects and fails closed
    on any REQUIRED check missing this way; evaluate_subsystem()/
    evaluate_overall() will show a subsystem with zero results as
    UNKNOWN."""
    check_results = [evaluate_check(chk, signals[cid], reason_codes, now) for cid, chk in checks.items() if cid in signals]
    subsystems = sorted({chk.subsystem for chk in checks.values()})
    subsystem_results = [evaluate_subsystem(s, check_results) for s in subsystems]
    overall = evaluate_overall(subsystem_results)
    control = evaluate_control_readiness(checks, check_results, reason_codes)
    return check_results, subsystem_results, overall, control
