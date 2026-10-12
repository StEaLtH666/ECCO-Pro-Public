"""fsw1 (the failed-start health warning) change scope: exactly what fsw1 changes in the files the pub0 export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `fsw1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after rsv1;
registry/tests/_pex.py) carries one frozen reverter per edited file.

WHAT fsw1 IS. Home Assistant health, records and the Overview status hero only. A Free Power or Dump to Grid START that fails before it
writes anything leaves the recovery state at NONE, so nothing on the Overview reported it. A new trigger-based health sensor,
sensor.ecco_health_start_failures, detects a genuine new failed start from four EXISTING firmware counters (the Free Power and Dump to
Grid "Start Attempts Since Boot" and "Start Successes Since Boot"): a rise of unresolved attempts (attempts minus successes) that is
still there after the counters were quiet for 90 s. Refusals are never counted; a nonzero count, the first values after a Home
Assistant start, a reconnection and a counter reset only set the baseline. It reports WARNING with FREE_POWER_START_FAILED and/or
DUMP_TO_GRID_START_FAILED for 1800 s after the failed attempt, UNKNOWN (never HEALTHY) for an unreadable counter pair with no open
window. Two registry checks and two reason codes record it; docs/SYSTEM_HEALTH_ARCHITECTURE.md describes it. The Overview hero reads
the sensor's reason_codes (structured, never the free-text status): ATTENTION with its own subline when a failed start is the only
reason, a START FAILED TRANSACTIONS pill, every existing reason keeping its subline and priority, and the sensor deliberately outside
`required`. ZERO firmware, frontend, deployment, Intelligence or ecco_core change; ZERO Modbus operation (64 reads / 52 writes
unchanged); ZERO NVS access; no new control surface (template keys only), automation, script or notification; no manifest or
VERSION.yaml change.

FROZEN edits (PEX). The five files below are pub0 targets: each reverter undoes exactly fsw1's pairs, so as of the previous entry each
file is its declared state, and as of pub0 the export byte for byte.

NOT frozen (ordinary edits, nothing to declare): CHANGELOG.md.
Added: home-assistant/tests/test_ecco_start_failure_alert.py (behaviour, differential, oracle, hero, mutation and fps1-compatibility suite),
docs/FAILED_START_HEALTH.md (detection matrix, timing contract, deployment, rollback, live acceptance) and this module.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (battery reserve first-run default, rsv1).
BASE_COMMIT = "311c129637b78250532503d6cc60c1403010bed1"

ADDED_FILES = frozenset({
    "home-assistant/tests/test_ecco_start_failure_alert.py",
    "docs/FAILED_START_HEALTH.md",
    "registry/tests/_fsw1_scope.py",
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
        raise AssertionError(f"fsw1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"fsw1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"fsw1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/packages/ecco_system_health.yaml ---------------------------------------------------------------
HEALTH_PKG_REL = "home-assistant/packages/ecco_system_health.yaml"
HEALTH_PKG_0_OLD = _blk(r"""
            caveat; NOT proven restart-safe.

  - triggers:
      - trigger: homeassistant
""")
HEALTH_PKG_0_NEW = _blk(r"""
            caveat; NOT proven restart-safe.

  # FAILED STARTS (FB-D1 follow-up: a structured, time-limited warning for a Free Power / Dump to Grid START that failed without entering
  # recovery). The firmware counts start attempts and start successes separately (both since boot, published every 30 s); an attempt is
  # counted only AFTER every start gate has passed, so a refusal (REJECTED - ...) is never counted, and a success only when the START
  # verified ACTIVE. Unresolved attempts = attempts - successes therefore rises by one for every genuine failed START, whether or not it
  # then entered recovery. The failures-since-boot counters are NOT used: they also count failed restores, force-restores and lockouts.
  #
  # A new failed start is detected only as a rise of unresolved attempts that is still there after the counters have been quiet for
  # 240 s. The settle outlasts a start in flight AND a silent link loss: the start scripts reach success within 27 s (Free
  # Power: nine bounded 3 s Modbus waits) / 21 s (Dump to Grid: seven), each counter publishes on its own 30 s timer (so Home
  # Assistant sees the success at most 57 s after the attempt), and a silently lost ESPHome link keeps the counters available with
  # stale values for up to 110 s (aioesphomeapi 45.x: a ping every 20 s, closed 90 s after an unanswered one) before they become
  # unavailable; 57 + 110 = 167 s < 240 s. TIMING ASSUMPTION: re-check both bounds (the firmware start scripts and the live Home
  # Assistant ESPHome client) before deployment. A nonzero since-boot count, the first values seen after a Home Assistant start, a
  # reconnection or a counter
  # reset only set the baseline: they are never a failure. An unreadable or inconsistent counter pair clears the baseline (a failure
  # while it is unreadable is not observed). A LOWER unresolved count (a start's success published before its attempt, or an in-flight
  # start at baseline) moves the baseline only once the counters are quiet, so the publish-order skew never turns into a false failure.
  # The free-text status never decides anything; it is reported as information only.
  # A confirmed failure holds WARNING for 1800 s after the start attempt (the attempts counter's change time); each further failure
  # restarts that window. The window trigger fires exactly when the attempts counter has been unchanged for the whole window; the
  # one-minute refresh is the backstop (it also closes the window after a Home Assistant restart cancelled the timer).
  - triggers:
      - trigger: homeassistant
        event: start
        id: start
      - trigger: state
        id: start_counters_changed
        entity_id:
          - sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
          - sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
          - sensor.ecco_clock_dongle_free_power_start_successes_since_boot
          - sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot
      - trigger: state
        id: start_counters_settled
        entity_id:
          - sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
          - sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
          - sensor.ecco_clock_dongle_free_power_start_successes_since_boot
          - sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot
        for:
          seconds: 240
      - trigger: state
        id: start_failure_window_elapsed
        entity_id:
          - sensor.ecco_clock_dongle_free_power_start_attempts_since_boot
          - sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot
        for:
          minutes: 30
      - trigger: time_pattern
        minutes: "/1"
    sensor:
      - name: "ECCO Health Start Failures"
        unique_id: ecco_health_start_failures
        state: >-
          {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
          {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
          {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
          {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
          {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
          {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
          {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
          {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
          {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
          {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
          {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
          {% set fplfts = as_timestamp(fplf, none) %}
          {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
          {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
          {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
          {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
          {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
          {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
          {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
          {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
          {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
          {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
          {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
          {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
          {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
          {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
          {% set dglfts = as_timestamp(dglf, none) %}
          {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
          {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
          {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
          {% if fpactive or dgactive %}
            WARNING
          {% elif not fpok or not dgok %}
            UNKNOWN
          {% else %}
            HEALTHY
          {% endif %}
        attributes:
          subsystems: "{{ ['free_power', 'manual_write_system'] }}"
          partial_implementation: true
          sufficient_for_control_decision: false
          represented_checks: "{{ ['free_power_start_failed_recent', 'dump_to_grid_start_failed_recent'] }}"
          detection_basis: >-
            A rise of unresolved start attempts (start attempts minus start successes, both since boot) that is still there after the
            counters were quiet for 240 s. Refusals are not counted. Never a nonzero count by itself, never the status text.
          window_seconds: 1800
          settle_seconds: 240
          source_entities: >-
            {{ ['sensor.ecco_clock_dongle_free_power_start_attempts_since_boot',
                'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot',
                'sensor.ecco_clock_dongle_free_power_start_successes_since_boot',
                'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot'] }}
          blocks_manual_control: false
          reason_codes: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {% set codes = [] %}
            {% if fpactive %}{% set codes = codes + ['FREE_POWER_START_FAILED'] %}{% endif %}
            {% if dgactive %}{% set codes = codes + ['DUMP_TO_GRID_START_FAILED'] %}{% endif %}
            {{ codes }}
          failed_features: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {% set feats = [] %}
            {% if fpactive %}{% set feats = feats + ['free_power'] %}{% endif %}
            {% if dgactive %}{% set feats = feats + ['dump_to_grid'] %}{% endif %}
            {{ feats }}
          free_power_unresolved_baseline: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {{ fpnu }}
          free_power_last_failure_at: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {{ fplf }}
          free_power_failures_observed: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {{ fptot }}
          free_power_warning_active: >-
            {% set fpea = 'sensor.ecco_clock_dongle_free_power_start_attempts_since_boot' %}{% set fpes = 'sensor.ecco_clock_dongle_free_power_start_successes_since_boot' %}
            {% set fpa = states(fpea) | float(-1) %}{% set fps = states(fpes) | float(-1) %}
            {% set fpok = fpa >= 0 and fps >= 0 and fpa >= fps and fpa < 1000000000 %}
            {% set fpu = ((fpa - fps) | int(-1)) if fpok else -1 %}
            {% set fppu = ((this.attributes.get('free_power_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set fpstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set fplc = [as_timestamp(states[fpea].last_changed, 0), as_timestamp(states[fpes].last_changed, 0)] | max %}
            {% set fpquiet = fpok and (as_timestamp(now()) - fplc) >= 240 %}
            {% set fpfailed = (fpu - fppu) if (fpok and not fpstart and fppu >= 0 and fpu > fppu and fpquiet) else 0 %}
            {% set fpnu = -1 if not fpok else (fpu if (fpstart or fppu < 0 or (fpu < fppu and fpquiet) or fpfailed > 0) else fppu) %}
            {% set fplf = states[fpea].last_changed.isoformat() if fpfailed > 0 else (this.attributes.get('free_power_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set fplfts = as_timestamp(fplf, none) %}
            {% set fpage = (as_timestamp(now()) - fplfts) if fplfts is not none else none %}
            {% set fpactive = fpage is not none and fpage < 1800 and fpage > -60 %}
            {% set fptot = ((this.attributes.get('free_power_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + fpfailed %}
            {{ fpactive }}
          free_power_start_attempts_since_boot: "{{ states('sensor.ecco_clock_dongle_free_power_start_attempts_since_boot') }}"
          free_power_start_successes_since_boot: "{{ states('sensor.ecco_clock_dongle_free_power_start_successes_since_boot') }}"
          free_power_status_text_informational: "{{ states('sensor.ecco_clock_dongle_free_power_status') }}"
          free_power_recovery_state_informational: "{{ states('sensor.ecco_clock_dongle_free_power_recovery_state') }}"
          dump_to_grid_unresolved_baseline: >-
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {{ dgnu }}
          dump_to_grid_last_failure_at: >-
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {{ dglf }}
          dump_to_grid_failures_observed: >-
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {{ dgtot }}
          dump_to_grid_warning_active: >-
            {% set dgea = 'sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot' %}{% set dges = 'sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot' %}
            {% set dga = states(dgea) | float(-1) %}{% set dgs = states(dges) | float(-1) %}
            {% set dgok = dga >= 0 and dgs >= 0 and dga >= dgs and dga < 1000000000 %}
            {% set dgu = ((dga - dgs) | int(-1)) if dgok else -1 %}
            {% set dgpu = ((this.attributes.get('dump_to_grid_unresolved_baseline', -1) if this is defined and this is not none else -1) | float(-1)) | int(-1) %}
            {% set dgstart = trigger is defined and trigger is not none and trigger.id is defined and trigger.id == 'start' %}
            {% set dglc = [as_timestamp(states[dgea].last_changed, 0), as_timestamp(states[dges].last_changed, 0)] | max %}
            {% set dgquiet = dgok and (as_timestamp(now()) - dglc) >= 240 %}
            {% set dgfailed = (dgu - dgpu) if (dgok and not dgstart and dgpu >= 0 and dgu > dgpu and dgquiet) else 0 %}
            {% set dgnu = -1 if not dgok else (dgu if (dgstart or dgpu < 0 or (dgu < dgpu and dgquiet) or dgfailed > 0) else dgpu) %}
            {% set dglf = states[dgea].last_changed.isoformat() if dgfailed > 0 else (this.attributes.get('dump_to_grid_last_failure_at', 'none') if this is defined and this is not none else 'none') %}
            {% set dglfts = as_timestamp(dglf, none) %}
            {% set dgage = (as_timestamp(now()) - dglfts) if dglfts is not none else none %}
            {% set dgactive = dgage is not none and dgage < 1800 and dgage > -60 %}
            {% set dgtot = ((this.attributes.get('dump_to_grid_failures_observed', 0) if this is defined and this is not none else 0) | int(0)) + dgfailed %}
            {{ dgactive }}
          dump_to_grid_start_attempts_since_boot: "{{ states('sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot') }}"
          dump_to_grid_start_successes_since_boot: "{{ states('sensor.ecco_clock_dongle_dump_to_grid_start_successes_since_boot') }}"
          dump_to_grid_status_text_informational: "{{ states('sensor.ecco_clock_dongle_dump_to_grid_status') }}"
          dump_to_grid_recovery_state_informational: "{{ states('sensor.ecco_clock_dongle_dump_to_grid_recovery_state') }}"

  - triggers:
      - trigger: homeassistant
""")
HEALTH_PKG_EDITS = (
    (HEALTH_PKG_0_OLD, HEALTH_PKG_0_NEW),
)


def pre_fsw1_health_package(text: str) -> str:
    """home-assistant/packages/ecco_system_health.yaml with exactly fsw1's edits undone (a frozen reverter of chain entry fsw1, PEX): its state as of the previous entry."""
    return _revert(text, HEALTH_PKG_EDITS, "home-assistant/packages/ecco_system_health.yaml")


pre_fsw1_health_package.edits = HEALTH_PKG_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fsw1_health_package(text: str) -> str:
    """Applies fsw1's home-assistant/packages/ecco_system_health.yaml edits to the previous state (the round trip)."""
    return _apply(text, HEALTH_PKG_EDITS, "home-assistant/packages/ecco_system_health.yaml")


# ---- (PEX frozen edit) registry/system_health_checks.yaml ----------------------------------------------------------------------------
CHECKS_REL = "registry/system_health_checks.yaml"
CHECKS_0_OLD = _blk(r"""
  live_proof_status: unknown
- id: free_power_active_state
""")
CHECKS_0_NEW = _blk(r"""
  live_proof_status: unknown
- id: dump_to_grid_start_failed_recent
  subsystem: manual_write_system
  description: A Dump to Grid START that failed after every start gate had passed (unresolved start attempts rose and stayed up).
  source:
    entity: dump_start_attempts minus dump_start_successes (derived, settled)
    type: derived
  expected_datatype: counter
  check_type: failure_counter_delta
  parameters:
    window_seconds: 1800
    warning_delta: 1
    failure_delta: null
  applicability_condition: null
  outcomes:
  - reason_code: DUMP_TO_GRID_START_FAILED
    condition: unresolved start attempts (attempts minus successes) rose by 1 or more within the 1800s window
      and stayed up after the counters were quiet for 240s.
  dependencies: []
  evidence: firmware/ecco_clock_dongle_stage3_4_free_power.yaml:17055 (dump_start_attempts++ only after the start gate
    has passed, so a refusal is not counted), 17631 (dump_start_successes++ only on a verified ACTIVE), 17428 / 17699 / 17709
    (the genuine failed-start paths); published as "Dump to Grid Start Attempts / Successes Since Boot"
    (firmware:6300-6318, 30 s, 0 after every ESP boot). The failures-since-boot counter is not used - it also counts failed
    restores. Represented by sensor.ecco_health_start_failures (home-assistant/packages/ecco_system_health.yaml) in Home
    Assistant form - a rise is judged between consecutive observed values, never against a baseline that spans a reboot. A
    nonzero count, the first values after a Home Assistant start, a reconnection or a counter reset only set the baseline;
    the free-text status is information only. The subsystem is manual_write_system because Dump to Grid is a manual inverter
    write transaction and the registry has no dump subsystem. A failure while the counters are unavailable to Home Assistant
    is not observed.
  implementation_status: implemented_offline
  live_proof_status: unknown
- id: free_power_active_state
""")
CHECKS_1_OLD = _blk(r"""
    write/verify blocks.
  implementation_status: designed
  live_proof_status: unknown
- id: free_power_state_consistency
""")
CHECKS_1_NEW = _blk(r"""
    write/verify blocks.
  implementation_status: designed
  live_proof_status: unknown
- id: free_power_start_failed_recent
  subsystem: free_power
  description: A Free Power START that failed after every start gate had passed (unresolved start attempts rose and stayed up).
  source:
    entity: free_power_start_attempts minus free_power_start_successes (derived, settled)
    type: derived
  expected_datatype: counter
  check_type: failure_counter_delta
  parameters:
    window_seconds: 1800
    warning_delta: 1
    failure_delta: null
  applicability_condition: null
  outcomes:
  - reason_code: FREE_POWER_START_FAILED
    condition: unresolved start attempts (attempts minus successes) rose by 1 or more within the 1800s window
      and stayed up after the counters were quiet for 240s.
  dependencies: []
  evidence: firmware/ecco_clock_dongle_stage3_4_free_power.yaml:7797 (free_power_start_attempts++ only after the start gate
    has passed, so a refusal is not counted), 8667 (free_power_start_successes++ only on a verified ACTIVE), 8152 / 8752-8823
    (the genuine failed-start paths); published as "Free Power Start Attempts / Successes Since Boot" (firmware:6260-6277,
    30 s, 0 after every ESP boot). free_power_failures_recent (above) is a different signal - it also counts failed restores.
    Represented by sensor.ecco_health_start_failures (home-assistant/packages/ecco_system_health.yaml) in Home Assistant form -
    a rise is judged between consecutive observed values, never against a baseline that spans a reboot. A nonzero count, the
    first values after a Home Assistant start, a reconnection or a counter reset only set the baseline; the free-text status
    is information only. A failure while the counters are unavailable to Home Assistant is not observed.
  implementation_status: implemented_offline
  live_proof_status: unknown
- id: free_power_state_consistency
""")
CHECKS_EDITS = (
    (CHECKS_0_OLD, CHECKS_0_NEW),
    (CHECKS_1_OLD, CHECKS_1_NEW),
)


def pre_fsw1_checks_registry(text: str) -> str:
    """registry/system_health_checks.yaml with exactly fsw1's edits undone (a frozen reverter of chain entry fsw1, PEX): its state as of the previous entry."""
    return _revert(text, CHECKS_EDITS, "registry/system_health_checks.yaml")


pre_fsw1_checks_registry.edits = CHECKS_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fsw1_checks_registry(text: str) -> str:
    """Applies fsw1's registry/system_health_checks.yaml edits to the previous state (the round trip)."""
    return _apply(text, CHECKS_EDITS, "registry/system_health_checks.yaml")


# ---- (PEX frozen edit) registry/health_reason_codes.yaml -----------------------------------------------------------------------------
REASON_CODES_REL = "registry/health_reason_codes.yaml"
REASON_CODES_0_OLD = _blk(r"""
    affects_forecast: false

  # ===================================================================
  # free_power
""")
REASON_CODES_0_NEW = _blk(r"""
    affects_forecast: false

  - code: DUMP_TO_GRID_START_FAILED
    subsystem: manual_write_system
    severity: WARNING
    meaning: "A Dump to Grid START failed after every start gate had passed: unresolved start attempts (start attempts minus start successes) rose and stayed up. A refusal (REJECTED - ...) is not counted."
    source_signal: "dump_start_attempts and dump_start_successes counter pair (unresolved attempts delta, settled: still up after 240 s with no counter change)"
    likely_cause: "The fresh snapshot could not be taken or durably committed, or the activation write or its verification failed. The start may or may not have entered recovery: check the recovery state and dump_status for the firmware's own explanation."
    safe_diagnostic_step: "Read dump_status and the Dump to Grid recovery state before retrying. The 15 s watchdog restores an outstanding snapshot by itself."
    blocks_manual_control: false
    affects_forecast: false

  # ===================================================================
  # free_power
""")
REASON_CODES_1_OLD = _blk(r"""
    safe_diagnostic_step: "Read free_power_status for the firmware's own explanation before retrying."
    blocks_manual_control: false
""")
REASON_CODES_1_NEW = _blk(r"""
    safe_diagnostic_step: "Read free_power_status for the firmware's own explanation before retrying."
    blocks_manual_control: false
    affects_forecast: false

  - code: FREE_POWER_START_FAILED
    subsystem: free_power
    severity: WARNING
    meaning: "A Free Power START failed after every start gate had passed: unresolved start attempts (start attempts minus start successes) rose and stayed up. A refusal (REJECTED - ...) is not counted."
    source_signal: "free_power_start_attempts and free_power_start_successes counter pair (unresolved attempts delta, settled: still up after 240 s with no counter change)"
    likely_cause: "The fresh snapshot could not be completed or durably committed, or the activation write or its verification failed. The start may or may not have entered recovery: check the recovery state and free_power_status for the firmware's own explanation."
    safe_diagnostic_step: "Read free_power_status and the Free Power recovery state before retrying. Do not press a recovery action unless the recovery state asks for one."
    blocks_manual_control: false
""")
REASON_CODES_EDITS = (
    (REASON_CODES_0_OLD, REASON_CODES_0_NEW),
    (REASON_CODES_1_OLD, REASON_CODES_1_NEW),
)


def pre_fsw1_reason_codes(text: str) -> str:
    """registry/health_reason_codes.yaml with exactly fsw1's edits undone (a frozen reverter of chain entry fsw1, PEX): its state as of the previous entry."""
    return _revert(text, REASON_CODES_EDITS, "registry/health_reason_codes.yaml")


pre_fsw1_reason_codes.edits = REASON_CODES_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fsw1_reason_codes(text: str) -> str:
    """Applies fsw1's registry/health_reason_codes.yaml edits to the previous state (the round trip)."""
    return _apply(text, REASON_CODES_EDITS, "registry/health_reason_codes.yaml")


# ---- (PEX frozen edit) docs/SYSTEM_HEALTH_ARCHITECTURE.md ----------------------------------------------------------------------------
ARCH_DOC_REL = "docs/SYSTEM_HEALTH_ARCHITECTURE.md"
ARCH_DOC_0_OLD = _blk(r"""
| `sensor.ecco_health_free_power` | free_power | `free_power_operation_duration`, `free_power_active_state`, `free_power_snapshot_recovery` | `free_power_failures_recent`, `free_power_state_consistency` |
| `sensor.ecco_health_configuration` | inverter_configuration | `config_cache_valid` | `configuration_freshness`, `configuration_failures_recent` |
""")
ARCH_DOC_0_NEW = _blk(r"""
| `sensor.ecco_health_free_power` | free_power | `free_power_operation_duration`, `free_power_active_state`, `free_power_snapshot_recovery` | `free_power_failures_recent`, `free_power_state_consistency` |
| `sensor.ecco_health_start_failures` | free_power, manual_write_system | `free_power_start_failed_recent`, `dump_to_grid_start_failed_recent` (added later, offline only - see below) | - |
| `sensor.ecco_health_configuration` | inverter_configuration | `config_cache_valid` | `configuration_freshness`, `configuration_failures_recent` |
""")
ARCH_DOC_1_OLD = _blk(r"""
observed.

""")
ARCH_DOC_1_NEW = _blk(r"""
observed.

**Failed starts: `free_power_start_failed_recent` and `dump_to_grid_start_failed_recent` (FB-D1 follow-up, offline only, not
live-proven).** A Free Power or Dump to Grid START that fails before it writes anything leaves the recovery state at `NONE`, so
nothing else on the Overview reported it. `sensor.ecco_health_start_failures` now does, from four existing firmware counters:
the Free Power and Dump to Grid "Start Attempts Since Boot" and "Start Successes Since Boot".

- **What is counted.** The firmware counts an attempt only after every start gate has passed, so a refusal (`REJECTED - ...`) is not
  counted. It counts a success only when the START verified ACTIVE. Unresolved attempts (attempts minus successes) therefore rise by
  one for every genuine failed start, whether or not it then entered recovery. The failures-since-boot counters are not used,
  because they also count failed restores, force-restores and lockouts. The free-text status never decides anything; it is shown as
  information only.
- **When a failure is confirmed.** Only when unresolved attempts have risen and are still up after all four counters were quiet for
  240 s. The settle has to outlast two things. First, a start in flight: the firmware start scripts reach success within 27 s
  (Free Power) or 21 s (Dump to Grid), and each counter publishes on its own 30 s timer, so Home Assistant sees the success at
  most 57 s after the attempt. Second, a silent Wi-Fi loss: the ESPHome client (aioesphomeapi 45.x) pings every 20 s and drops
  the link 90 s after an unanswered ping, so stale counters can stay available for up to 110 s. 57 + 110 = 167 s, below 240 s.
  **Timing assumption:** both bounds must be re-checked against the firmware start scripts and the live Home Assistant ESPHome
  client before deployment.
- **What is never a failure.** A nonzero count, the first values seen after a Home Assistant start, a reconnection, a counter reset
  (the counters restart at 0 on every ESP boot) and an inconsistent pair (successes above attempts) only set the baseline. An
  unreadable counter clears the baseline; a failure while it is unreadable is not observed.
- **What it reports.** WARNING with `FREE_POWER_START_FAILED` and/or `DUMP_TO_GRID_START_FAILED` for 1800 s after the failed start
  attempt, and each further failure restarts that feature's window. The two features are independent, so simultaneous failures report
  both. Nothing unreadable ever reports HEALTHY: with no open window, an unreadable counter pair reports UNKNOWN. The baseline, the
  failure time and the observed failure count are kept as attributes, which Home Assistant restores for a trigger-based template
  entity after a restart. The window trigger fires exactly when the attempts counter has been unchanged for the whole window; the
  one-minute refresh is the backstop. The warning does not clear early when a later start succeeds.
- **Registry.** Dump to Grid has no health subsystem of its own, so its check sits in `manual_write_system` (a manual inverter write
  transaction). The two reason codes are WARNING, do not block manual control and do not affect the forecast.
- **Overview.** The status hero reads the sensor's `reason_codes` (never its state alone) and shows ATTENTION with its own subline
  when a failed start is the only reason; every existing reason keeps its subline and priority. A failure while an input is missing
  still shows STATUS PARTIAL first.

""")
ARCH_DOC_EDITS = (
    (ARCH_DOC_0_OLD, ARCH_DOC_0_NEW),
    (ARCH_DOC_1_OLD, ARCH_DOC_1_NEW),
)


def pre_fsw1_architecture_doc(text: str) -> str:
    """docs/SYSTEM_HEALTH_ARCHITECTURE.md with exactly fsw1's edits undone (a frozen reverter of chain entry fsw1, PEX): its state as of the previous entry."""
    return _revert(text, ARCH_DOC_EDITS, "docs/SYSTEM_HEALTH_ARCHITECTURE.md")


pre_fsw1_architecture_doc.edits = ARCH_DOC_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fsw1_architecture_doc(text: str) -> str:
    """Applies fsw1's docs/SYSTEM_HEALTH_ARCHITECTURE.md edits to the previous state (the round trip)."""
    return _apply(text, ARCH_DOC_EDITS, "docs/SYSTEM_HEALTH_ARCHITECTURE.md")


# ---- (PEX frozen edit) home-assistant/dashboards/ecco_pro.yaml -----------------------------------------------------------------------
DASHBOARD_REL = "home-assistant/dashboards/ecco_pro.yaml"
DASHBOARD_0_OLD = _blk(r"""
                  const fb = get('sensor.ecco_fallback_status');

""")
DASHBOARD_0_NEW = _blk(r"""
                  const fb = get('sensor.ecco_fallback_status');
                  // FSW1: a Free Power / Dump to Grid START that failed before it entered recovery (so both recovery states can still read NONE).
                  // Structured only: the reason_codes of sensor.ecco_health_start_failures, a time-limited WARNING (1800 s after the failed attempt).
                  // Display only. Deliberately NOT in `required`: an unavailable sensor stays quiet (an offline dongle is already COMMS / PARTIAL).
                  const failedStartState = get('sensor.ecco_health_start_failures');
                  const failedStartCodes = states['sensor.ecco_health_start_failures']?.attributes?.reason_codes;
                  const failedStartText = Array.isArray(failedStartCodes) ? failedStartCodes.join(',') : String(failedStartCodes ?? '');
                  const freeStartFailed = failedStartText.includes('FREE_POWER_START_FAILED');
                  const dumpStartFailed = failedStartText.includes('DUMP_TO_GRID_START_FAILED');
                  const startFailed = failedStartState === 'WARNING' && (freeStartFailed || dumpStartFailed);

""")
DASHBOARD_1_OLD = _blk(r"""
                  const busy = manualBusy || rtcBusy || freeBusy || freeActive || dumpBusy || dumpActive;

""")
DASHBOARD_1_NEW = _blk(r"""
                  const busy = manualBusy || rtcBusy || freeBusy || freeActive || dumpBusy || dumpActive;
                  // FSW1: ATTENTION also for a confirmed failed start; every existing reason keeps its subline and its priority.
                  const attention = hardAttention || startFailed;
                  const startFailSubline = freeStartFailed && dumpStartFailed ? 'Free Power and Dump to Grid starts failed recently' : freeStartFailed ? 'A Free Power start failed recently' : 'A Dump to Grid start failed recently';

""")
DASHBOARD_2_OLD = _blk(r"""
                  } else if (hardAttention) {
""")
DASHBOARD_2_NEW = _blk(r"""
                  } else if (attention) {
""")
DASHBOARD_3_OLD = _blk(r"""
                    subline = 'A monitored subsystem needs checking';
""")
DASHBOARD_3_NEW = _blk(r"""
                    subline = hardAttention ? 'A monitored subsystem needs checking' : startFailSubline;
""")
DASHBOARD_4_OLD = _blk(r"""
                  const txChip = chipState(true, manualBusy || freeBusy || freeActive || dumpBusy || dumpActive, txUnknown);
""")
DASHBOARD_4_NEW = _blk(r"""
                  const txChip = startFailed ? ['START FAILED', 'warn'] : chipState(true, manualBusy || freeBusy || freeActive || dumpBusy || dumpActive, txUnknown);
""")
DASHBOARD_EDITS = (
    (DASHBOARD_0_OLD, DASHBOARD_0_NEW),
    (DASHBOARD_1_OLD, DASHBOARD_1_NEW),
    (DASHBOARD_2_OLD, DASHBOARD_2_NEW),
    (DASHBOARD_3_OLD, DASHBOARD_3_NEW),
    (DASHBOARD_4_OLD, DASHBOARD_4_NEW),
)


def pre_fsw1_dashboard(text: str) -> str:
    """home-assistant/dashboards/ecco_pro.yaml with exactly fsw1's edits undone (a frozen reverter of chain entry fsw1, PEX): its state as of the previous entry."""
    return _revert(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


pre_fsw1_dashboard.edits = DASHBOARD_EDITS   # the PEX contract: a frozen reverter exposes its exact (before, after) pairs


def add_fsw1_dashboard(text: str) -> str:
    """Applies fsw1's home-assistant/dashboards/ecco_pro.yaml edits to the previous state (the round trip)."""
    return _apply(text, DASHBOARD_EDITS, "home-assistant/dashboards/ecco_pro.yaml")


# Every frozen file fsw1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    HEALTH_PKG_REL: pre_fsw1_health_package,
    CHECKS_REL: pre_fsw1_checks_registry,
    REASON_CODES_REL: pre_fsw1_reason_codes,
    ARCH_DOC_REL: pre_fsw1_architecture_doc,
    DASHBOARD_REL: pre_fsw1_dashboard,
}
