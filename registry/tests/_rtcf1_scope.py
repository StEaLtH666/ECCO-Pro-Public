"""rtcf1 (FB-D1 follow-up: the RTC correction-failure health alert) change scope: exactly what rtcf1 changes in the files the pub0
export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `rtcf1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after fbrp1;
registry/tests/_pex.py) carries one frozen reverter per edited file.

WHAT rtcf1 IS. Home Assistant health and records only. sensor.ecco_health_rtc (home-assistant/packages/ecco_system_health.yaml) gains
the designed registry check rtc_correction_failures_recent from the EXISTING firmware sensor "Failed Corrections Since Boot": WARNING
with the existing reason code RTC_CORRECTION_FAILURES_RECENT for 1800 s after an observed numeric-to-numeric increase of the counter
(a reboot reset, a first value after unknown and an attribute-only event never count; each further increase restarts the window), an
unreadable counter with no failure in the window is UNKNOWN (never HEALTHY), and the attributes last_failure_at / last_result /
last_failure_kind / failure_window_seconds / failed_corrections_since_boot / correction_lock_max_age_seconds. Two new state triggers
(the counter change, and the same entity held for 1800 s so the window closes on time; the one-minute refresh stays the backstop).
Every existing check, rank, tie-break, reason code, threshold and presentation of the row is unchanged. The registry record moves
from designed to implemented_offline with the Home Assistant form of the window in its evidence; docs/SYSTEM_HEALTH_ARCHITECTURE.md
records it. ZERO firmware, frontend, dashboard, deployment, Intelligence or ecco_core change; ZERO Modbus operation (64 reads /
52 writes unchanged); ZERO NVS access; no new HA control surface (template keys only), automation, script or notification.

FROZEN edits (PEX). The three files below are pub0 targets: each reverter undoes exactly rtcf1's pairs, so as of pub0 each file is the
export byte for byte (its manifest result). No earlier post-export entry edits any of them, so each base is its pub0 state.

NOT frozen (ordinary edits, nothing to declare): CHANGELOG.md. Added: home-assistant/tests/test_ecco_rtc_failure_alert.py (the
behaviour, precedence, differential and mutation suite) and this module.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (FBRP1, squash-merged as PR #8).
BASE_COMMIT = "20e06a8dfc43eb7a1e351db867648345b75cd757"

ADDED_FILES = frozenset({
    "home-assistant/tests/test_ecco_rtc_failure_alert.py",
    "registry/tests/_rtcf1_scope.py",
})


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"rtcf1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"rtcf1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"rtcf1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/packages/ecco_system_health.yaml ---------------------------------------------------------------
HEALTH_PKG_REL = "home-assistant/packages/ecco_system_health.yaml"
HEALTH_PKG_0_OLD = _blk(r"""
      - trigger: time_pattern
        minutes: "/1"
    sensor:
      - name: "ECCO Health RTC"
""")
HEALTH_PKG_0_NEW = _blk(r"""
      - trigger: time_pattern
        minutes: "/1"
      # rtc_correction_failures_recent (FB-D1 follow-up): a change of the
      # firmware's cumulative "Failed Corrections Since Boot" counter. Only
      # a numeric-to-numeric INCREASE seen on this trigger is a failure (see
      # the entity comment below); the id is what the templates test.
      - trigger: state
        id: rtc_failed_corrections_changed
        entity_id: sensor.ecco_clock_dongle_failed_corrections_since_boot
      # Re-renders exactly 1800 s after the counter's last change, so the
      # warning window closes on time without waiting for another counter
      # update. The one-minute time_pattern above is the backstop (for
      # example after a Home Assistant restart, which cancels this timer).
      - trigger: state
        id: rtc_failure_window_elapsed
        entity_id: sensor.ecco_clock_dongle_failed_corrections_since_boot
        for:
          seconds: 1800
    sensor:
      - name: "ECCO Health RTC"
""")
HEALTH_PKG_1_OLD = _blk(r"""
        # Implements three registry checks under subsystem rtc_time:
""")
HEALTH_PKG_1_NEW = _blk(r"""
        # Implements four registry checks under subsystem rtc_time:
""")
HEALTH_PKG_2_OLD = _blk(r"""
        # rtc_stall_detected (boolean_expected: false) and rtc_ntp_synced
        # (boolean_expected: true). Aggregates using the same rank/tie-break
        # rule as health/system_health.py's evaluate_subsystem() /
        # _resolve_flavor_at_rank(): the worst severity rank wins, and at a
        # shared rank a real finding (WARNING/FAILED/DEGRADED) always beats
        # UNKNOWN. rtc_read_freshness and rtc_drift_uncorrected (same
        # subsystem) are deliberately NOT represented - see
        # not_yet_implemented_checks. Correction COUNT alone is never
        # evaluated here - only correction_in_progress's CURRENT duration -
        # per Task 007's explicit instruction that frequent successful
        # corrections are expected on this installation and must not be
        # treated as a fault.
""")
HEALTH_PKG_2_NEW = _blk(r"""
        # rtc_stall_detected (boolean_expected: false), rtc_ntp_synced
        # (boolean_expected: true) and rtc_correction_failures_recent
        # (failure_counter_delta, 1800 s window, WARNING). Aggregates using
        # the same rank/tie-break rule as health/system_health.py's
        # evaluate_subsystem() / _resolve_flavor_at_rank(): the worst
        # severity rank wins, and at a shared rank a real finding
        # (WARNING/FAILED/DEGRADED) always beats UNKNOWN. rtc_read_freshness
        # and rtc_drift_uncorrected (same subsystem) are deliberately NOT
        # represented - see not_yet_implemented_checks. Correction COUNT
        # alone is never evaluated here - only correction_in_progress's
        # CURRENT duration and the FAILED-correction counter - per Task
        # 007's explicit instruction that frequent successful corrections
        # are expected on this installation and must not be treated as a
        # fault.
        #
        # rtc_correction_failures_recent: the firmware increments
        # failed_corrections when a correction fails after its retries,
        # fails on communication errors, or is released by the 90 s RTC
        # deadline breaker ("ABORTED - correction exceeded its deadline").
        # Its sensor publishes every 60 s and restarts at 0 on every ESP
        # boot. A failure is ONLY an observed numeric-to-numeric increase
        # on the rtc_failed_corrections_changed trigger: a reboot reset
        # (N -> 0, or N -> unavailable -> 0) and the first value after a
        # Home Assistant restart (from unknown or none) never count. The
        # time Home Assistant saw the increase is kept in last_failure_at
        # (trigger-based template entities restore their state and
        # attributes after a Home Assistant restart), and the check reports
        # WARNING / RTC_CORRECTION_FAILURES_RECENT while less than 1800 s
        # have passed since it; each further increase restarts the window.
        # An unreadable counter with no failure in the window is UNKNOWN,
        # never HEALTHY. Not observable, so never reported: a failure that
        # happens while the counter is unavailable to Home Assistant, or
        # while Home Assistant is down. last_failure_at can trail the
        # firmware event by up to the sensor's 60 s publish interval.
""")
HEALTH_PKG_3_OLD = _blk(r"""
            {% set rank3 = 2 %}{% set state3 = 'WARNING' %}
          {% else %}
            {% set rank3 = 0 %}{% set state3 = 'HEALTHY' %}
          {% endif %}
          {% set max_rank = [rank1, rank2, rank3] | max %}
          {% set definite = {0: 'HEALTHY', 1: 'DEGRADED', 2: 'WARNING', 3: 'FAILED'}[max_rank] %}
          {% set states_at_max = [] %}
          {% if rank1 == max_rank %}{% set states_at_max = states_at_max + [state1] %}{% endif %}
          {% if rank2 == max_rank %}{% set states_at_max = states_at_max + [state2] %}{% endif %}
          {% if rank3 == max_rank %}{% set states_at_max = states_at_max + [state3] %}{% endif %}
          {% if definite in states_at_max %}
            {{ definite }}
          {% elif 'UNKNOWN' in states_at_max %}
            UNKNOWN
          {% else %}
            {{ definite }}
          {% endif %}
        attributes:
          subsystem: rtc_time
""")
HEALTH_PKG_3_NEW = _blk(r"""
            {% set rank3 = 2 %}{% set state3 = 'WARNING' %}
          {% else %}
            {% set rank3 = 0 %}{% set state3 = 'HEALTHY' %}
          {% endif %}
          {% set e4 = 'sensor.ecco_clock_dongle_failed_corrections_since_boot' %}
          {% set s4 = states(e4) %}
          {% set t = trigger if trigger is defined else none %}
          {% set fresh = t is not none and t.id is defined and t.id == 'rtc_failed_corrections_changed' and t.from_state is not none and t.to_state is not none and (t.from_state.state | float(-1)) >= 0 and (t.to_state.state | float(-1)) > (t.from_state.state | float(-1)) %}
          {% set prev = this.attributes.get('last_failure_at') if this is defined else none %}
          {% set lf_ts = as_timestamp(t.to_state.last_changed) if fresh else as_timestamp(prev, none) %}
          {% if lf_ts is not none and as_timestamp(now()) - lf_ts < 1800 %}
            {% set rank4 = 2 %}{% set state4 = 'WARNING' %}
          {% elif (s4 | float(-1)) < 0 %}
            {% set rank4 = 2 %}{% set state4 = 'UNKNOWN' %}
          {% else %}
            {% set rank4 = 0 %}{% set state4 = 'HEALTHY' %}
          {% endif %}
          {% set max_rank = [rank1, rank2, rank3, rank4] | max %}
          {% set definite = {0: 'HEALTHY', 1: 'DEGRADED', 2: 'WARNING', 3: 'FAILED'}[max_rank] %}
          {% set states_at_max = [] %}
          {% if rank1 == max_rank %}{% set states_at_max = states_at_max + [state1] %}{% endif %}
          {% if rank2 == max_rank %}{% set states_at_max = states_at_max + [state2] %}{% endif %}
          {% if rank3 == max_rank %}{% set states_at_max = states_at_max + [state3] %}{% endif %}
          {% if rank4 == max_rank %}{% set states_at_max = states_at_max + [state4] %}{% endif %}
          {% if definite in states_at_max %}
            {{ definite }}
          {% elif 'UNKNOWN' in states_at_max %}
            UNKNOWN
          {% else %}
            {{ definite }}
          {% endif %}
        attributes:
          subsystem: rtc_time
""")
HEALTH_PKG_4_OLD = _blk(r"""
          represented_checks: "{{ ['rtc_correction_duration', 'rtc_stall_detected', 'rtc_ntp_synced'] }}"
""")
HEALTH_PKG_4_NEW = _blk(r"""
          represented_checks: "{{ ['rtc_correction_duration', 'rtc_stall_detected', 'rtc_ntp_synced', 'rtc_correction_failures_recent'] }}"
""")
HEALTH_PKG_5_OLD = _blk(r"""
            age/timestamp entity, not confirmed available);
            rtc_correction_failures_recent (needs a persisted failure-counter
            baseline mechanism across Home Assistant restarts);
            rtc_drift_uncorrected (needs live correction_threshold and
""")
HEALTH_PKG_5_NEW = _blk(r"""
            age/timestamp entity, not confirmed available);
            rtc_drift_uncorrected (needs live correction_threshold and
""")
HEALTH_PKG_6_OLD = _blk(r"""
                'binary_sensor.ecco_clock_dongle_ntp_synced'] }}
          clock_difference_seconds_informational: "{{ states('sensor.ecco_clock_dongle_clock_difference') }}"
          reason_codes: >-
""")
HEALTH_PKG_6_NEW = _blk(r"""
                'binary_sensor.ecco_clock_dongle_ntp_synced',
                'sensor.ecco_clock_dongle_failed_corrections_since_boot'] }}
          clock_difference_seconds_informational: "{{ states('sensor.ecco_clock_dongle_clock_difference') }}"
          # rtc_correction_failures_recent detail. last_failure_at and
          # last_result are captured when an increase is seen and kept
          # (restored after a Home Assistant restart) until the next one;
          # last_result is the firmware's "Last Correction Result" text at
          # that moment (for a deadline-breaker release it begins with
          # ABORTED). The lock max age and the counter are read live.
          last_failure_at: >-
            {% set t = trigger if trigger is defined else none %}
            {% set fresh = t is not none and t.id is defined and t.id == 'rtc_failed_corrections_changed' and t.from_state is not none and t.to_state is not none and (t.from_state.state | float(-1)) >= 0 and (t.to_state.state | float(-1)) > (t.from_state.state | float(-1)) %}
            {% set prev = this.attributes.get('last_failure_at') if this is defined else none %}
            {% if fresh %}
              {{ t.to_state.last_changed.isoformat() }}
            {% elif prev is not none and as_timestamp(prev, none) is not none %}
              {{ prev }}
            {% else %}
              none
            {% endif %}
          last_result: >-
            {% set t = trigger if trigger is defined else none %}
            {% set fresh = t is not none and t.id is defined and t.id == 'rtc_failed_corrections_changed' and t.from_state is not none and t.to_state is not none and (t.from_state.state | float(-1)) >= 0 and (t.to_state.state | float(-1)) > (t.from_state.state | float(-1)) %}
            {% set prev = this.attributes.get('last_result') if this is defined else none %}
            {% if fresh %}
              {{ states('sensor.ecco_clock_dongle_last_correction_result') }}
            {% elif prev is not none %}
              {{ prev }}
            {% else %}
              none
            {% endif %}
          last_failure_kind: >-
            {% set t = trigger if trigger is defined else none %}
            {% set fresh = t is not none and t.id is defined and t.id == 'rtc_failed_corrections_changed' and t.from_state is not none and t.to_state is not none and (t.from_state.state | float(-1)) >= 0 and (t.to_state.state | float(-1)) > (t.from_state.state | float(-1)) %}
            {% set prev = this.attributes.get('last_result') if this is defined else none %}
            {% set r = (states('sensor.ecco_clock_dongle_last_correction_result') if fresh else prev) | string %}
            {% if not fresh and (prev is none or prev == 'none') %}
              none
            {% elif r.startswith('ABORTED') %}
              deadline_abort
            {% elif r.startswith('FAILED') %}
              failed
            {% else %}
              unrecognised
            {% endif %}
          failure_window_seconds: 1800
          failed_corrections_since_boot: "{{ states('sensor.ecco_clock_dongle_failed_corrections_since_boot') }}"
          correction_lock_max_age_seconds: "{{ states('sensor.ecco_clock_dongle_ecco_rtc_correction_lock_max_age_since_boot') }}"
          reason_codes: >-
""")
HEALTH_PKG_7_OLD = _blk(r"""
              {% set codes = codes + ['RTC_NTP_UNSYNCED'] %}
            {% endif %}
""")
HEALTH_PKG_7_NEW = _blk(r"""
              {% set codes = codes + ['RTC_NTP_UNSYNCED'] %}
            {% endif %}
            {% set t = trigger if trigger is defined else none %}
            {% set fresh = t is not none and t.id is defined and t.id == 'rtc_failed_corrections_changed' and t.from_state is not none and t.to_state is not none and (t.from_state.state | float(-1)) >= 0 and (t.to_state.state | float(-1)) > (t.from_state.state | float(-1)) %}
            {% set prev = this.attributes.get('last_failure_at') if this is defined else none %}
            {% set lf_ts = as_timestamp(t.to_state.last_changed) if fresh else as_timestamp(prev, none) %}
            {% if lf_ts is not none and as_timestamp(now()) - lf_ts < 1800 %}
              {% set codes = codes + ['RTC_CORRECTION_FAILURES_RECENT'] %}
            {% endif %}
""")
HEALTH_PKG_EDITS = (
    (HEALTH_PKG_0_OLD, HEALTH_PKG_0_NEW),
    (HEALTH_PKG_1_OLD, HEALTH_PKG_1_NEW),
    (HEALTH_PKG_2_OLD, HEALTH_PKG_2_NEW),
    (HEALTH_PKG_3_OLD, HEALTH_PKG_3_NEW),
    (HEALTH_PKG_4_OLD, HEALTH_PKG_4_NEW),
    (HEALTH_PKG_5_OLD, HEALTH_PKG_5_NEW),
    (HEALTH_PKG_6_OLD, HEALTH_PKG_6_NEW),
    (HEALTH_PKG_7_OLD, HEALTH_PKG_7_NEW),
)


def pre_rtcf1_health_package(text: str) -> str:
    """home-assistant/packages/ecco_system_health.yaml with exactly rtcf1's edits undone (a frozen reverter of chain entry rtcf1, PEX): the pub0 export's text."""
    return _revert(text, HEALTH_PKG_EDITS, "home-assistant/packages/ecco_system_health.yaml")


pre_rtcf1_health_package.edits = HEALTH_PKG_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_rtcf1_health_package(text: str) -> str:
    """Applies rtcf1's home-assistant/packages/ecco_system_health.yaml edits to the exported text (the round trip)."""
    return _apply(text, HEALTH_PKG_EDITS, "home-assistant/packages/ecco_system_health.yaml")


# ---- (PEX frozen edit) registry/system_health_checks.yaml ----------------------------------------------------------------------------
CHECKS_REL = "registry/system_health_checks.yaml"
CHECKS_0_OLD = _blk(r"""
  evidence: firmware/ecco_clock_dongle_stage3_4_free_power.yaml:5476/6101 (increment), 5482/6106 (5-minute
    cooldown_until_ms after failure).
  implementation_status: designed
""")
CHECKS_0_NEW = _blk(r"""
  evidence: firmware/ecco_clock_dongle_stage3_4_free_power.yaml:21144 (verification failed after retries),
    22597 (the 90 s RTC deadline breaker releases a stuck correction - "ABORTED - correction exceeded its
    deadline"), 22647 (failed after communication errors); each also starts the 5-minute cooldown. Published
    as "Failed Corrections Since Boot" (firmware:6186-6193, 60 s, 0 after every ESP boot). Represented by
    sensor.ecco_health_rtc (home-assistant/packages/ecco_system_health.yaml) in Home Assistant form - the delta
    is taken between consecutive observed values, never against a baseline that spans a reboot. An increase
    between two numeric values is a failure; a decrease (reboot reset) or a first value after unknown is not.
    WARNING holds for 1800 s after the last observed increase (its time is kept across a Home Assistant
    restart by the trigger-based entity's state restore). An unreadable counter with no failure in the window
    is UNKNOWN. A failure while the counter is unavailable to Home Assistant is not observed.
  implementation_status: implemented_offline
""")
CHECKS_EDITS = (
    (CHECKS_0_OLD, CHECKS_0_NEW),
)


def pre_rtcf1_checks_registry(text: str) -> str:
    """registry/system_health_checks.yaml with exactly rtcf1's edits undone (a frozen reverter of chain entry rtcf1, PEX): the pub0 export's text."""
    return _revert(text, CHECKS_EDITS, "registry/system_health_checks.yaml")


pre_rtcf1_checks_registry.edits = CHECKS_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_rtcf1_checks_registry(text: str) -> str:
    """Applies rtcf1's registry/system_health_checks.yaml edits to the exported text (the round trip)."""
    return _apply(text, CHECKS_EDITS, "registry/system_health_checks.yaml")


# ---- (PEX frozen edit) docs/SYSTEM_HEALTH_ARCHITECTURE.md ----------------------------------------------------------------------------
ARCH_DOC_REL = "docs/SYSTEM_HEALTH_ARCHITECTURE.md"
ARCH_DOC_0_OLD = _blk(r"""
| `sensor.ecco_health_rtc` | rtc_time | `rtc_correction_duration`, `rtc_stall_detected`, `rtc_ntp_synced` | `rtc_read_freshness`, `rtc_correction_failures_recent`, `rtc_drift_uncorrected` |
""")
ARCH_DOC_0_NEW = _blk(r"""
| `sensor.ecco_health_rtc` | rtc_time | `rtc_correction_duration`, `rtc_stall_detected`, `rtc_ntp_synced`; `rtc_correction_failures_recent` (added later, offline only - see below) | `rtc_read_freshness`, `rtc_drift_uncorrected` |
""")
ARCH_DOC_1_OLD = _blk(r"""
`rtc_correction_failures_recent`, `free_power_failures_recent`,
`telemetry_failures_recent` - see section 6 and the live-validation
checklist item 3, still unverified), or a live HA entity this task's
""")
ARCH_DOC_1_NEW = _blk(r"""
`free_power_failures_recent`, `telemetry_failures_recent` - see section 6
and the live-validation checklist item 3, still unverified), or a live HA entity this task's
""")
ARCH_DOC_2_OLD = _blk(r"""
simplification provides).

""")
ARCH_DOC_2_NEW = _blk(r"""
simplification provides).

**`rtc_correction_failures_recent` (FB-D1 follow-up, offline only, not
live-proven).** `sensor.ecco_health_rtc` now also represents this check, from
the existing firmware sensor "Failed Corrections Since Boot", which counts a
correction that failed after its retries, failed on communication errors or
was released by the 90 s RTC deadline breaker. It needs no persisted baseline:
the delta is taken between consecutive observed values. An increase between
two numeric values is a failure. A decrease (the counter restarts at 0 on every
ESP boot) and the first value after an unknown state (a Home Assistant restart)
are not. The check reports WARNING with `RTC_CORRECTION_FAILURES_RECENT` for
1800 s after the last observed increase, and each further increase restarts the
window. The time of that increase, and the "Last Correction Result" text at that
moment (`ABORTED ...` for a breaker release), are kept as attributes, which
Home Assistant restores for a trigger-based template entity after a restart.
A trigger 1800 s after the counter's last change closes the window on time;
the one-minute refresh is the backstop. An unreadable counter with no failure
in the window reports UNKNOWN, never HEALTHY. A failure while the counter is
unavailable to Home Assistant, or while Home Assistant is down, is not
observed.

""")
ARCH_DOC_EDITS = (
    (ARCH_DOC_0_OLD, ARCH_DOC_0_NEW),
    (ARCH_DOC_1_OLD, ARCH_DOC_1_NEW),
    (ARCH_DOC_2_OLD, ARCH_DOC_2_NEW),
)


def pre_rtcf1_architecture_doc(text: str) -> str:
    """docs/SYSTEM_HEALTH_ARCHITECTURE.md with exactly rtcf1's edits undone (a frozen reverter of chain entry rtcf1, PEX): the pub0 export's text."""
    return _revert(text, ARCH_DOC_EDITS, "docs/SYSTEM_HEALTH_ARCHITECTURE.md")


pre_rtcf1_architecture_doc.edits = ARCH_DOC_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_rtcf1_architecture_doc(text: str) -> str:
    """Applies rtcf1's docs/SYSTEM_HEALTH_ARCHITECTURE.md edits to the exported text (the round trip)."""
    return _apply(text, ARCH_DOC_EDITS, "docs/SYSTEM_HEALTH_ARCHITECTURE.md")


# Every frozen file rtcf1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    HEALTH_PKG_REL: pre_rtcf1_health_package,
    CHECKS_REL: pre_rtcf1_checks_registry,
    ARCH_DOC_REL: pre_rtcf1_architecture_doc,
}
