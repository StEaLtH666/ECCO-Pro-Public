"""The Intelligence action vocabulary: modes, action kinds, outcomes, preconditions and refusal codes (data only).

This module names things; it does nothing. It has no function that acts, and nothing in Intelligence or the Home Assistant
runtime uses it to act: the SHADOW runtime may run only in a mode of RUNTIME_ALLOWED_MODES (OFF or SHADOW). A later,
separately reviewed action-policy package may use these names for MOCK decisions only.

    Mode            OFF, SHADOW, ASSISTED, AUTONOMOUS. DEFAULT_MODE is SHADOW. The inert Home Assistant automation-mode
                    selector is never reused for this.
    ActionKind      the candidate kinds a policy could ever reason about (TOU slot target SOC / charge power / charge source,
                    notify the owner). Abstract names only: no service, entity or register is named here.
    NEVER_ALLOWED   kinds no mode and no decision can ever permit (protection registers 217-219, arming Free Power or Dump,
                    raw slot or bus writes, the export-mode register 244, firmware changes, writing the reserve helper or
                    the clock, unattended Dump, and automating the ACS1 Review or its typed phrase).
    Outcome         RECOMMENDED, PREPARED, REQUESTED, REFUSED, EXECUTED_MOCK, VERIFIED_MOCK, FAILED, RESTORE_REQUIRED,
                    RESTORED_MOCK. PREPARED is a RECORD ONLY: no Home Assistant write, no Review start, no staging of any
                    ACS1 helper.
    Precondition    the ids every action decision must evaluate (missing or ambiguous input -> refused, never a default).
    RefusalCode     why an action is refused.

DEFAULT_MODE, RUNTIME_ALLOWED_MODES and NEVER_ALLOWED are not open to a contract change request.
"""

from __future__ import annotations

VOCAB_VERSION = "ecco-intel-authority-vocab/1"


class Mode:
    OFF = "OFF"
    SHADOW = "SHADOW"
    ASSISTED = "ASSISTED"
    AUTONOMOUS = "AUTONOMOUS"
    ALL = (OFF, SHADOW, ASSISTED, AUTONOMOUS)


DEFAULT_MODE = Mode.SHADOW
RUNTIME_ALLOWED_MODES = frozenset({Mode.OFF, Mode.SHADOW})


class ActionKind:
    """Candidate kinds only. A candidate is never permitted by being listed here."""
    TOU_SLOT_TARGET_SOC = "TOU_SLOT_TARGET_SOC"
    TOU_SLOT_CHARGE_POWER = "TOU_SLOT_CHARGE_POWER"
    TOU_SLOT_CHARGE_SOURCE = "TOU_SLOT_CHARGE_SOURCE"
    NOTIFY_OWNER = "NOTIFY_OWNER"
    CANDIDATES = (TOU_SLOT_TARGET_SOC, TOU_SLOT_CHARGE_POWER, TOU_SLOT_CHARGE_SOURCE, NOTIFY_OWNER)


NEVER_ALLOWED = frozenset({
    "PROTECTION_REGISTERS_217_219",
    "FREE_POWER_ARM",
    "DUMP_TO_GRID_ARM",
    "RAW_MANUAL_SLOT_WRITE",
    "EXPORT_MODE_REG_244",
    "RAW_BUS_WRITE",
    "FIRMWARE_CHANGE",
    "RESERVE_HELPER_WRITE",
    "CLOCK_WRITE",
    "UNATTENDED_DUMP_A10P",
    "ACS1_REVIEW_OR_PHRASE_AUTOMATION",
})


class Outcome:
    RECOMMENDED = "RECOMMENDED"
    PREPARED = "PREPARED"                 # a journal record only: no HA write, no Review start, no helper staging
    REQUESTED = "REQUESTED"
    REFUSED = "REFUSED"
    EXECUTED_MOCK = "EXECUTED_MOCK"
    VERIFIED_MOCK = "VERIFIED_MOCK"
    FAILED = "FAILED"
    RESTORE_REQUIRED = "RESTORE_REQUIRED"
    RESTORED_MOCK = "RESTORED_MOCK"
    ALL = (RECOMMENDED, PREPARED, REQUESTED, REFUSED, EXECUTED_MOCK, VERIFIED_MOCK, FAILED, RESTORE_REQUIRED, RESTORED_MOCK)
    RECORD_ONLY = frozenset({PREPARED})
    MOCK_ONLY = frozenset({EXECUTED_MOCK, VERIFIED_MOCK, RESTORED_MOCK})
    TERMINAL = frozenset({REFUSED, FAILED, VERIFIED_MOCK, RESTORED_MOCK})


PREPARED_MEANING = ("PREPARED is a record in the decision journal and nothing else: no Home Assistant write, no ACS1 Review "
                    "start, no staging of any ACS1 helper.")


class Precondition:
    """Every id must be evaluated from explicit state; a missing or ambiguous input refuses."""
    MODE_PERMITS = "MODE_PERMITS"
    KIND_ALLOWLISTED = "KIND_ALLOWLISTED"
    DECISIONS_SATISFIED = "DECISIONS_SATISFIED"              # site_decisions.satisfied with OWNER_RECORD provenance only
    OWNER_OPT_IN_RECORDED = "OWNER_OPT_IN_RECORDED"
    SUPERVISION_SUPERVISED_STABLE = "SUPERVISION_SUPERVISED_STABLE"
    SHADOW_IDLE = "SHADOW_IDLE"
    INPUTS_FRESH = "INPUTS_FRESH"
    B10_MATCH = "B10_MATCH"
    CLOCK_WITHIN_LIMITS = "CLOCK_WITHIN_LIMITS"
    INVERTER_HEALTHY = "INVERTER_HEALTHY"
    NO_FREE_POWER_ACTIVE_OR_ARMED = "NO_FREE_POWER_ACTIVE_OR_ARMED"
    NO_DUMP_ACTIVE_OR_ARMED = "NO_DUMP_ACTIVE_OR_ARMED"
    NO_TOU_EDIT_IN_FLIGHT = "NO_TOU_EDIT_IN_FLIGHT"
    NO_SCHEDULE_WITHIN_15_MIN = "NO_SCHEDULE_WITHIN_15_MIN"
    SOC_CERTAIN = "SOC_CERTAIN"
    CAPACITY_CERTAIN = "CAPACITY_CERTAIN"
    TARIFF_VALID = "TARIFF_VALID"
    NO_USER_OVERRIDE = "NO_USER_OVERRIDE"
    NO_RECENT_MANUAL_CHANGE = "NO_RECENT_MANUAL_CHANGE"
    WITHIN_CIRCUIT_LIMITS = "WITHIN_CIRCUIT_LIMITS"
    WITHIN_INVERTER_LIMITS = "WITHIN_INVERTER_LIMITS"
    LEASE_VALID = "LEASE_VALID"
    SCHEDULE_LOCK_FREE = "SCHEDULE_LOCK_FREE"
    NOT_PROTECTED_PERIOD = "NOT_PROTECTED_PERIOD"            # clock-change nights 00:00-03:00 local, slot boundaries, midnight hold
    ALL = (MODE_PERMITS, KIND_ALLOWLISTED, DECISIONS_SATISFIED, OWNER_OPT_IN_RECORDED, SUPERVISION_SUPERVISED_STABLE,
           SHADOW_IDLE, INPUTS_FRESH, B10_MATCH, CLOCK_WITHIN_LIMITS, INVERTER_HEALTHY, NO_FREE_POWER_ACTIVE_OR_ARMED,
           NO_DUMP_ACTIVE_OR_ARMED, NO_TOU_EDIT_IN_FLIGHT, NO_SCHEDULE_WITHIN_15_MIN, SOC_CERTAIN, CAPACITY_CERTAIN,
           TARIFF_VALID, NO_USER_OVERRIDE, NO_RECENT_MANUAL_CHANGE, WITHIN_CIRCUIT_LIMITS, WITHIN_INVERTER_LIMITS,
           LEASE_VALID, SCHEDULE_LOCK_FREE, NOT_PROTECTED_PERIOD)


class RefusalCode:
    NEVER_ALLOWED_KIND = "NEVER_ALLOWED_KIND"
    UNKNOWN_KIND = "UNKNOWN_KIND"
    MODE_NOT_PERMITTED = "MODE_NOT_PERMITTED"
    RUNTIME_MODE_NOT_ALLOWED = "RUNTIME_MODE_NOT_ALLOWED"
    DECISION_NOT_SATISFIED = "DECISION_NOT_SATISFIED"
    OWNER_OPT_IN_MISSING = "OWNER_OPT_IN_MISSING"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    PRECONDITION_UNKNOWN = "PRECONDITION_UNKNOWN"
    INPUT_STALE = "INPUT_STALE"
    INPUT_CONFLICT = "INPUT_CONFLICT"
    PROTECTED_PERIOD = "PROTECTED_PERIOD"
    CORE_AUTHORITY_REFUSED = "CORE_AUTHORITY_REFUSED"         # terminal: no path from a core refusal to any later outcome
    NO_MOCK_AUTHORITY = "NO_MOCK_AUTHORITY"
    RATE_LIMITED = "RATE_LIMITED"
    FROZEN_ON_UNCERTAINTY = "FROZEN_ON_UNCERTAINTY"
    ALL = (NEVER_ALLOWED_KIND, UNKNOWN_KIND, MODE_NOT_PERMITTED, RUNTIME_MODE_NOT_ALLOWED, DECISION_NOT_SATISFIED,
           OWNER_OPT_IN_MISSING, PRECONDITION_FAILED, PRECONDITION_UNKNOWN, INPUT_STALE, INPUT_CONFLICT, PROTECTED_PERIOD,
           CORE_AUTHORITY_REFUSED, NO_MOCK_AUTHORITY, RATE_LIMITED, FROZEN_ON_UNCERTAINTY)


def runtime_mode_allowed(mode: object) -> bool:
    """True only for OFF and SHADOW (what the Home Assistant runtime may ever run in)."""
    return isinstance(mode, str) and mode in RUNTIME_ALLOWED_MODES
