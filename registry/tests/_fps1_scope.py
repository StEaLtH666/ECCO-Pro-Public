"""fps1 (scheduled Free Power reliability; the 11 Oct 2026 incident) change scope: exactly what fps1 changes in the files the pub0
export froze, and its exact inverse.

Same technique as the earlier post-export scope modules: every verbatim edit is held HERE as the single source of truth, as an exact
(before, after) pair generated from the real diff and round-trip-checked, and each reverter raises unless each of its edits is present
exactly once. The post-export chain entry `fps1` (registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended last after fe1;
registry/tests/_pex.py) carries one frozen reverter for the one edited frozen file.

WHAT fps1 IS. On 11 Oct 2026 the 11:00-13:00 scheduled Free Power session never started: the firmware start gate refuses a press at
once while a Modbus frame is queued or awaiting its reply (the routine 10 s telemetry poll keeps the bus busy about 20 % of the
time), and the package pressed at about +2 s and retried once at about +35 s, a spacing locked to that 10 s cycle. Both presses
landed in telemetry reads; nothing was written; the schedule disarmed itself without any alert. fps1 changes ONLY the Home Assistant
scheduling layer: bounded, unevenly spaced retries of a start-gate refusal for a transient reason (a gate refusal has no side
effect), never a retry once a start transaction began, positive confirmation (Free Power Active), a start deadline and a duration
clamp so nothing starts or runs past the authorised window, a readiness check and a missed-trigger watchdog (template triggers on
the existing fire automation), persistent notifications for every failure or miss, and STARTING / FAILED / COMPLETED status states.
New files (ADDED_FILES): the incident record, the offline Home Assistant script simulator and the reliability suite, and this
module. ZERO firmware, registry, dashboard, Intelligence or ecco_core byte; ZERO Modbus operation; the package's helper, script and
automation counts are unchanged; no new control surface.

FROZEN edit (PEX).
  home-assistant/packages/ecco_free_power_schedule.yaml   the start script, the fire / start-up recovery / arm-validation
                                                          automations and the status sensor's state template

NOT frozen (ordinary edits, nothing to declare): registry/tests/test_pex_transition.py (the PEX ledger), CHANGELOG.md.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

# Public main the change is based on (FE-1 merged, then the offline deployment preflight tools).
BASE_COMMIT = "0203a4683b6536f75932041e9c0dc61fd83ec30a"

ADDED_FILES = frozenset({
    "docs/incidents/2026-10-11-scheduled-free-power-start.md",
    "home-assistant/tests/_ha_script_sim.py",
    "home-assistant/tests/test_ecco_free_power_schedule_reliability.py",
    "registry/tests/_fps1_scope.py",
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
        raise AssertionError(f"fps1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"fps1 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"fps1 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edit) home-assistant/packages/ecco_free_power_schedule.yaml --------------------------------------------------
PACKAGE_REL = "home-assistant/packages/ecco_free_power_schedule.yaml"
PACKAGE_0_OLD = _blk(r"""

input_boolean:
  ecco_free_power_schedule_armed:
    name: ECCO Scheduled Free Power Armed
    icon: mdi:calendar-check

input_datetime:
  ecco_free_power_schedule_start:
    name: ECCO Free Power Schedule Start
    has_date: true
    has_time: true

input_number:
  ecco_free_power_schedule_duration:
    name: ECCO Scheduled Free Power Duration
    min: 1
    max: 240
    step: 1
    unit_of_measurement: min
    mode: slider

  ecco_free_power_schedule_power:
    name: ECCO Scheduled Free Power Power
    min: 500
    max: 8000
    step: 100
    unit_of_measurement: W
    mode: box

input_text:
  ecco_free_power_schedule_last_result:
    name: ECCO Free Power Schedule Last Result
    max: 255

script:
  ecco_free_power_start_scheduled:
    alias: "ECCO - Start scheduled Free Power"
    description: "Stages and starts the proven ESPHome Free Power override with one automatic retry."
    mode: single
    fields:
      duration_minutes:
        description: "Duration to stage into the ESPHome Free Power controller"
      power_w:
        description: "Requested battery charge power in watts"
    sequence:
      - variables:
          requested_duration: "{{ duration_minutes | int(1) }}"
          requested_power: "{{ power_w | int(500) }}"
          effective_limit: "{{ states('sensor.ecco_config_maximum_grid_charge_power') | int(0) }}"
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ (effective_limit | int(0)) <= 0 }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "BLOCKED - effective grid charge power limit unavailable"
          - conditions:
              - condition: template
                value_template: >-
                  {{ (requested_power | int(0)) < 500
                     or (requested_power | int(0)) > (effective_limit | int(0)) }}
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    BLOCKED - requested {{ requested_power }}W outside safe range
                    500-{{ effective_limit }}W
          - conditions:
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "on"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "BLOCKED - Free Power already active"
          - conditions:
              - condition: or
                conditions:
                  - condition: state
                    entity_id: binary_sensor.ecco_clock_dongle_telemetry_online
                    state: "off"
                  - condition: state
                    entity_id: binary_sensor.ecco_clock_dongle_configuration_online
                    state: "off"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "BLOCKED - ECCO telemetry/configuration offline"
        default:
          - action: input_text.set_value
            target:
              entity_id: input_text.ecco_free_power_schedule_last_result
            data:
              value: >-
                STARTING - {{ requested_power }}W for {{ requested_duration }} min

          - action: number.set_value
            target:
              entity_id: number.ecco_clock_dongle_free_power_duration
            data:
              value: "{{ requested_duration }}"

          - action: number.set_value
            target:
              entity_id: number.ecco_clock_dongle_free_power_max_charge_power
            data:
              value: "{{ requested_power }}"

          - delay: "00:00:01"

          - action: switch.turn_on
            target:
              entity_id: switch.ecco_clock_dongle_free_power_write_enable

          - delay: "00:00:01"

          - action: button.press
            target:
              entity_id: button.ecco_clock_dongle_start_free_power_charge_now

          - wait_template: >-
              {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') }}
            timeout: "00:00:20"
            continue_on_timeout: true

          - choose:
              - conditions:
                  - condition: state
                    entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                    state: "on"
                sequence:
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: >-
                        STARTED OK - {{ requested_power }}W for {{ requested_duration }} min
            default:
              # A scheduled start can collide with the independent RTC correction window.
              # Re-arm and retry once after a short wait; the firmware still performs all
              # safety checks, snapshots and verification on the retry.
              - delay: "00:00:12"
              - action: switch.turn_on
                target:
                  entity_id: switch.ecco_clock_dongle_free_power_write_enable
              - delay: "00:00:01"
              - action: button.press
                target:
                  entity_id: button.ecco_clock_dongle_start_free_power_charge_now
              - wait_template: >-
                  {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') }}
                timeout: "00:00:20"
                continue_on_timeout: true
              - choose:
                  - conditions:
                      - condition: state
                        entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                        state: "on"
                    sequence:
                      - action: input_text.set_value
                        target:
                          entity_id: input_text.ecco_free_power_schedule_last_result
                        data:
                          value: >-
                            STARTED OK ON RETRY - {{ requested_power }}W for {{ requested_duration }} min
                default:
                  - action: switch.turn_off
                    target:
                      entity_id: switch.ecco_clock_dongle_free_power_write_enable
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: >-
                        FAILED TO START - {{ states('sensor.ecco_clock_dongle_free_power_status') }}

  ecco_free_power_cancel_schedule:
    alias: "ECCO - Cancel scheduled Free Power"
    description: "Cancels a future scheduled Free Power event. It does not stop an already-active Free Power run."
    mode: single
    sequence:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.ecco_free_power_schedule_armed
      - action: input_text.set_value
        target:
          entity_id: input_text.ecco_free_power_schedule_last_result
        data:
          value: "CANCELLED - scheduled event disarmed"

automation:
  - id: ecco_free_power_schedule_arm_validation
    alias: "ECCO - Validate scheduled Free Power arm"
    mode: restart
    triggers:
      - trigger: state
        entity_id: input_boolean.ecco_free_power_schedule_armed
        to: "on"
    actions:
      - variables:
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          scheduled_power: "{{ states('input_number.ecco_free_power_schedule_power') | int(0) }}"
          effective_limit: "{{ states('sensor.ecco_config_maximum_grid_charge_power') | int(0) }}"
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ (effective_limit | int(0)) <= 0 }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "REJECTED - effective grid charge power limit unavailable"
          - conditions:
              - condition: template
                value_template: >-
                  {{ (scheduled_power | int(0)) < 500
                     or (scheduled_power | int(0)) > (effective_limit | int(0)) }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    REJECTED - scheduled {{ scheduled_power }}W outside safe range
                    500-{{ effective_limit }}W
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "REJECTED - scheduled start must be in the future"
          # 2026-09-26 (Manual Dump-to-Grid V1): additive early UX check only.
          # Refuse to arm when an ARMED Scheduled Dump to Grid window overlaps
          # this one (2-minute buffer either side for start retry / restore).
          # Inert when ecco_dump_to_grid_schedule.yaml is not installed (the
          # helper then never reads "on"). The firmware's own mutual-exclusion
          # gates stay authoritative regardless.
          - conditions:
              - condition: state
                entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
                state: "on"
              - condition: template
                value_template: >-
                  {% set f_start = start_ts | float(0) %}
                  {% set f_end = f_start + (states('input_number.ecco_free_power_schedule_duration') | int(0)) * 60 %}
                  {% set d_start = as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) %}
                  {% set d_end = d_start + (states('input_number.ecco_dump_to_grid_schedule_duration') | int(0)) * 60 %}
                  {{ f_start < d_end + 120 and d_start < f_end + 120 }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    REJECTED - overlaps the armed Scheduled Dump to Grid window
                    ({{ states('input_datetime.ecco_dump_to_grid_schedule_start') }}); cancel it first
        default:
          - action: input_text.set_value
            target:
              entity_id: input_text.ecco_free_power_schedule_last_result
            data:
              value: >-
                ARMED - {{ states('input_datetime.ecco_free_power_schedule_start') }} •
                {{ states('input_number.ecco_free_power_schedule_duration') | int }} min •
                {{ states('input_number.ecco_free_power_schedule_power') | int }}W

  - id: ecco_free_power_schedule_fire
    alias: "ECCO - Fire scheduled Free Power"
    mode: single
    triggers:
      - trigger: time
        at: input_datetime.ecco_free_power_schedule_start
    conditions:
      - condition: state
        entity_id: input_boolean.ecco_free_power_schedule_armed
        state: "on"
    actions:
      - action: script.ecco_free_power_start_scheduled
        data:
          duration_minutes: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.ecco_free_power_schedule_armed

  - id: ecco_free_power_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Free Power after Home Assistant restart"
    mode: single
    triggers:
      - trigger: homeassistant
        event: start
    conditions:
      - condition: state
        entity_id: input_boolean.ecco_free_power_schedule_armed
        state: "on"
    actions:
      - delay: "00:00:20"
      - variables:
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          duration_min: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
          end_ts: "{{ start_ts + (duration_min * 60) }}"
          now_ts: "{{ as_timestamp(now()) }}"
          remaining_min: "{{ [1, (((end_ts - now_ts) / 60) | round(0, 'ceil')) | int] | max }}"
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ now_ts < start_ts }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    ARMED AFTER RESTART - waiting for {{ states('input_datetime.ecco_free_power_schedule_start') }}
          - conditions:
              - condition: template
                value_template: "{{ now_ts >= start_ts and now_ts < end_ts }}"
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "off"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    RECOVERING MISSED START - {{ remaining_min }} min remaining
              - action: script.ecco_free_power_start_scheduled
                data:
                  duration_minutes: "{{ remaining_min }}"
                  power_w: "{{ power_w }}"
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
          - conditions:
              - condition: template
                value_template: "{{ now_ts >= end_ts }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "MISSED - scheduled Free Power window already expired"

template:
  - sensor:
      - name: ECCO Free Power Schedule Status
        unique_id: ecco_free_power_schedule_status
        icon: mdi:calendar-clock
        state: >-
          {% if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') %}
            ACTIVE
          {% elif is_state('input_boolean.ecco_free_power_schedule_armed', 'on') %}
            ARMED
""")
PACKAGE_0_NEW = _blk(r"""
#
# FPS1 (2026-10-11 incident): the firmware start gate refuses a press at once while any Modbus
# frame is queued or awaiting its reply (including the 600 ms turnaround after it). The routine
# 10 s telemetry poll keeps the bus busy for about 20 % of the time. The old fixed timing (press
# at +2 s, one retry at +35 s) is locked to that 10 s cycle, so on 11 Oct both presses were
# refused and the session was abandoned without an alert. Now:
#   - a refusal AT THE GATE for a transient reason is retried, bounded and with uneven spacing.
#     A gate refusal has no side effects: one status text, the write enable turned off, no
#     Modbus I/O, no counter, no durable write. A refusal counts only when the switch was seen ON
#     before THIS press and is then seen OFF (the firmware's answer). Every retry re-arms and the
#     firmware re-checks every interlock;
#   - nothing is retried once a start transaction has begun (the firmware then owns restore), and
#     an outcome that cannot be confirmed is reported, never retried;
#   - nothing is staged or pressed while another Free Power / manual write is in progress, while
#     the dongle is offline, above the effective grid charge limit, or once the schedule has been
#     cancelled (armed off, or disarmed and re-armed since the run began); the press waits for the
#     arm and both staged values to be confirmed;
#   - a start counts only on positive confirmation (Free Power Active on);
#   - each run retries for at most 10 minutes and never in the last 30 s of the window; the staged
#     duration is min(requested, floor((window end - now + 20 s) / 60 s)): an on-time start keeps
#     its full duration (as before), a late start ends within about a minute of the window end;
#   - a readiness check 5 min before, a missed-trigger watchdog 3 min after, restart recovery,
#     and a persistent notification for every failure or miss; the write enable always ends off.

input_boolean:
  ecco_free_power_schedule_armed:
    name: ECCO Scheduled Free Power Armed
    icon: mdi:calendar-check

input_datetime:
  ecco_free_power_schedule_start:
    name: ECCO Free Power Schedule Start
    has_date: true
    has_time: true

input_number:
  ecco_free_power_schedule_duration:
    name: ECCO Scheduled Free Power Duration
    min: 1
    max: 240
    step: 1
    unit_of_measurement: min
    mode: slider

  ecco_free_power_schedule_power:
    name: ECCO Scheduled Free Power Power
    min: 500
    max: 8000
    step: 100
    unit_of_measurement: W
    mode: box

input_text:
  ecco_free_power_schedule_last_result:
    name: ECCO Free Power Schedule Last Result
    max: 255

script:
  ecco_free_power_start_scheduled:
    alias: "ECCO - Start scheduled Free Power"
    description: >-
      Stages and starts the proven ESPHome Free Power override inside its authorised window while
      the schedule stays armed. A start-gate refusal for a transient reason is retried (bounded);
      nothing is retried once a start transaction has begun; a failure raises a persistent notification.
    mode: single
    fields:
      duration_minutes:
        description: "Duration to stage into the ESPHome Free Power controller"
      power_w:
        description: "Requested battery charge power in watts"
      window_end_ts:
        description: "End of the authorised window (epoch seconds); nothing starts or runs after it"
    sequence:
      - variables:
          requested_duration: "{{ duration_minutes | int(1) }}"
          requested_power: "{{ power_w | int(500) }}"
          window_end: >-
            {% set w = window_end_ts | float(0) %}
            {{ w if w > 0 else as_timestamp(now()) + (duration_minutes | int(1)) * 60 }}
          retry_until: "{{ [as_timestamp(now()) + 600, (window_end | float(0)) - 30] | min }}"
          max_attempts: 60
          # A cancel - or a cancel and a re-arm - after this instant ends this run (armed's last_changed moves).
          run_started: "{{ as_timestamp(now()) }}"
      - choose:
          - conditions:
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "on"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "BLOCKED - Free Power already active"
          # A known limit that the request exceeds needs the owner. An UNAVAILABLE limit (the dongle
          # briefly offline) is waited for inside the loop instead.
          - conditions:
              - condition: template
                value_template: >-
                  {% set lim = states('sensor.ecco_config_maximum_grid_charge_power') | int(0) %}
                  {{ (requested_power | int(0)) < 500 or (lim > 0 and (requested_power | int(0)) > lim) }}
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    BLOCKED - requested {{ requested_power }}W outside safe range
                    500-{{ states('sensor.ecco_config_maximum_grid_charge_power') | int(0) }}W
        default:
          - action: input_text.set_value
            target:
              entity_id: input_text.ecco_free_power_schedule_last_result
            data:
              value: >-
                STARTING - {{ requested_power }}W until {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}
          - repeat:
              sequence:
                - variables:
                    duration_now: >-
                      {{ [requested_duration | int(1),
                          (((window_end | float(0)) - as_timestamp(now()) + 20) / 60) | round(0, 'floor') | int(0)] | min }}
                - choose:
                    # Cancelled by the owner (no longer armed, or disarmed and re-armed since this run began):
                    # never press again.
                    - conditions:
                        - condition: template
                          value_template: >-
                            {{ not (is_state('input_boolean.ecco_free_power_schedule_armed', 'on')
                                    and as_timestamp(states.input_boolean.ecco_free_power_schedule_armed.last_changed, 0)
                                        <= (run_started | float(0))) }}
                      sequence:
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_free_power_schedule_last_result
                          data:
                            value: "CANCELLED - scheduled Free Power cancelled before it started"
                    # The authorised window is (nearly) over: never start.
                    - conditions:
                        - condition: template
                          value_template: "{{ (duration_now | int(0)) < 1 or as_timestamp(now()) >= (window_end | float(0)) - 30 }}"
                      sequence:
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_free_power_schedule_last_result
                          data:
                            value: >-
                              FAILED TO START - authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }};
                              not started ({{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }})
                    # The effective grid charge limit is known and the request exceeds it (it may have been lowered
                    # while the dongle was offline): never stage it.
                    - conditions:
                        - condition: template
                          value_template: >-
                            {% set lim = states('sensor.ecco_config_maximum_grid_charge_power') | int(0) %}
                            {{ lim > 0 and (requested_power | int(0)) > lim }}
                      sequence:
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_free_power_schedule_last_result
                          data:
                            value: >-
                              BLOCKED - requested {{ requested_power }}W above the effective grid charge limit
                              {{ states('sensor.ecco_config_maximum_grid_charge_power') | int(0) }}W
                    # Not ready to press: the dongle is offline, the effective limit is unavailable, or
                    # another Free Power / manual write is in progress. Stage nothing, press nothing; look again.
                    - conditions:
                        - condition: template
                          value_template: >-
                            {{ not is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'on')
                               or not is_state('binary_sensor.ecco_clock_dongle_configuration_online', 'on')
                               or states('switch.ecco_clock_dongle_free_power_write_enable') not in ['on', 'off']
                               or states('binary_sensor.ecco_clock_dongle_free_power_active') not in ['on', 'off']
                               or (states('sensor.ecco_config_maximum_grid_charge_power') | int(0)) <= 0
                               or is_state('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'on')
                               or is_state('binary_sensor.ecco_clock_dongle_manual_write_in_progress', 'on') }}
                      sequence:
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_free_power_schedule_last_result
                          data:
                            value: >-
                              STARTING - attempt {{ repeat.index }} waiting: dongle offline, limit unavailable or
                              another write in progress; retrying until {{ (retry_until | float(0)) | timestamp_custom('%H:%M') }}
                        - delay:
                            seconds: 10
                  default:
                    - action: number.set_value
                      continue_on_error: true
                      target:
                        entity_id: number.ecco_clock_dongle_free_power_max_charge_power
                      data:
                        value: "{{ requested_power }}"
                    - action: number.set_value
                      continue_on_error: true
                      target:
                        entity_id: number.ecco_clock_dongle_free_power_duration
                      data:
                        value: "{{ duration_now }}"
                    - action: switch.turn_on
                      continue_on_error: true
                      target:
                        entity_id: switch.ecco_clock_dongle_free_power_write_enable
                    # Press only once the dongle has confirmed the arm and both staged values.
                    - wait_template: >-
                        {{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on')
                           and (states('number.ecco_clock_dongle_free_power_duration') | float(-1)) == (duration_now | float(-2))
                           and (states('number.ecco_clock_dongle_free_power_max_charge_power') | float(-1)) == (requested_power | float(-2)) }}
                      timeout: "00:00:05"
                      continue_on_timeout: true
                    - delay:
                        seconds: 1
                    - if:
                        - condition: template
                          value_template: >-
                            {{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'on')
                               and (states('number.ecco_clock_dongle_free_power_duration') | float(-1)) == (duration_now | float(-2))
                               and (states('number.ecco_clock_dongle_free_power_max_charge_power') | float(-1)) == (requested_power | float(-2))
                               and is_state('input_boolean.ecco_free_power_schedule_armed', 'on')
                               and as_timestamp(states.input_boolean.ecco_free_power_schedule_armed.last_changed, 0) <= (run_started | float(0)) }}
                      then:
                        # The firmware counts a start attempt only when its gate passes (published every 30 s).
                        - variables:
                            attempts_before: "{{ states('sensor.ecco_clock_dongle_free_power_start_attempts_since_boot') }}"
                        - action: button.press
                          continue_on_error: true
                          target:
                            entity_id: button.ecco_clock_dongle_start_free_power_charge_now
                        # The firmware publishes its status and then disarms the switch in BOTH branches of its
                        # gate. The switch was seen ON just before this press, so seeing it OFF now is this
                        # press's answer, and the status already holds its reason (an identical refusal text is
                        # not re-sent by ESPHome, so the text itself cannot prove freshness).
                        - wait_template: >-
                            {{ is_state('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'on')
                               or is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')
                               or is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}
                          timeout: "00:00:15"
                          continue_on_timeout: true
                        - delay:
                            seconds: 2
                        - variables:
                            answered: "{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}"
                            began: >-
                              {{ is_state('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'on')
                                 or is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')
                                 or (is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off')
                                     and not states('sensor.ecco_clock_dongle_free_power_status').startswith('REJECTED')) }}
                            status_now: "{{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }}"
                        - choose:
                            # Refused AT THE GATE (nothing written), answered, for a transient reason: retry.
                            - conditions:
                                - condition: template
                                  value_template: >-
                                    {% set s = states('sensor.ecco_clock_dongle_free_power_status') %}
                                    {{ answered and not began
                                       and is_state('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'off')
                                       and (s.startswith('REJECTED - Modbus bus busy with another transaction')
                                            or s.startswith('REJECTED - RTC correction currently active')
                                            or s.startswith('REJECTED - another inverter write is active')
                                            or s.startswith('REJECTED - inverter configuration offline')
                                            or s.startswith('REJECTED - valid NTP time required')
                                            or s.startswith('REJECTED - plausible live battery voltage required')
                                            or s.startswith('REJECTED - arm Free Power Write Enable first')) }}
                              sequence:
                                - action: input_text.set_value
                                  target:
                                    entity_id: input_text.ecco_free_power_schedule_last_result
                                  data:
                                    value: >-
                                      STARTING - attempt {{ repeat.index }} refused at the start gate ({{ status_now }});
                                      nothing written; retrying until {{ (retry_until | float(0)) | timestamp_custom('%H:%M') }}
                                # Uneven spacing never locks to the 10 s poll: about 6 / 7 / 9 / 10.5 s per attempt
                                # for the first 8, then about 16-21 s. The deadline, not the count, ends the retries.
                                - delay:
                                    seconds: "{{ (2.3 if repeat.index <= 8 else 12.6) + 1.7 * (repeat.index % 4) }}"
                            # Refused at the gate for a reason that needs the owner: stop, no retry.
                            - conditions:
                                - condition: template
                                  value_template: "{{ answered and not began }}"
                              sequence:
                                - action: input_text.set_value
                                  target:
                                    entity_id: input_text.ecco_free_power_schedule_last_result
                                  data:
                                    value: "FAILED TO START - {{ status_now }} (attempt {{ repeat.index }}; nothing written)"
                            # The gate passed: a start transaction began. Wait for its own verified outcome.
                            # Never retried: on failure the firmware restores its saved snapshot itself.
                            - conditions:
                                - condition: template
                                  value_template: "{{ began }}"
                              sequence:
                                - wait_template: >-
                                    {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')
                                       or is_state('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'off') }}
                                  timeout: "00:02:00"
                                  continue_on_timeout: true
                                - if:
                                    - condition: state
                                      entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                                      state: "on"
                                  then:
                                    - action: input_text.set_value
                                      target:
                                        entity_id: input_text.ecco_free_power_schedule_last_result
                                      data:
                                        value: >-
                                          STARTED OK - {{ requested_power }}W for {{ duration_now }} min
                                          (attempt {{ repeat.index }}; ends by {{ (window_end | float(0)) | timestamp_custom('%H:%M') }})
                                  else:
                                    - action: input_text.set_value
                                      target:
                                        entity_id: input_text.ecco_free_power_schedule_last_result
                                      data:
                                        value: >-
                                          FAILED TO START - {{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }}
                                          (start transaction began on attempt {{ repeat.index }}; not retried)
                          # No answer to this press (the switch still reads ON). Either the press never reached the
                          # firmware or Home Assistant's view stopped updating. Prove which before anything else:
                          # disarm and SEE the switch go off (the dongle is answering again), then wait for the
                          # firmware's gate-pass counter. Retry only if it did not move and nothing is in progress,
                          # active or pending restore; otherwise the outcome is unconfirmed and is never retried.
                          default:
                            - action: switch.turn_off
                              continue_on_error: true
                              target:
                                entity_id: switch.ecco_clock_dongle_free_power_write_enable
                            - wait_template: "{{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off') }}"
                              timeout: "00:00:10"
                              continue_on_timeout: true
                            - delay:
                                seconds: 35
                            - if:
                                - condition: template
                                  value_template: >-
                                    {% set now_a = states('sensor.ecco_clock_dongle_free_power_start_attempts_since_boot') | float(-1) %}
                                    {{ is_state('switch.ecco_clock_dongle_free_power_write_enable', 'off')
                                       and now_a >= 0 and now_a == (attempts_before | float(-2))
                                       and is_state('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'off')
                                       and is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'off')
                                       and is_state('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'off') }}
                              then:
                                - action: input_text.set_value
                                  target:
                                    entity_id: input_text.ecco_free_power_schedule_last_result
                                  data:
                                    value: >-
                                      STARTING - attempt {{ repeat.index }} never reached the dongle (no start counted);
                                      retrying until {{ (retry_until | float(0)) | timestamp_custom('%H:%M') }}
                              else:
                                - action: input_text.set_value
                                  target:
                                    entity_id: input_text.ecco_free_power_schedule_last_result
                                  data:
                                    value: >-
                                      FAILED TO START - no answer from the dongle to attempt {{ repeat.index }}; outcome
                                      unconfirmed, not retried (last status: {{ status_now }})
                      else:
                        # The dongle never confirmed the arm or the staged values, or the schedule was cancelled in
                        # the meantime: nothing was pressed. Disarm and look again (the loop top sees a cancel).
                        - action: switch.turn_off
                          continue_on_error: true
                          target:
                            entity_id: switch.ecco_clock_dongle_free_power_write_enable
                        - action: input_text.set_value
                          target:
                            entity_id: input_text.ecco_free_power_schedule_last_result
                          data:
                            value: >-
                              STARTING - attempt {{ repeat.index }}: arm or staged values not confirmed; nothing pressed;
                              retrying until {{ (retry_until | float(0)) | timestamp_custom('%H:%M') }}
                        - delay:
                            seconds: 5
              until:
                - condition: or
                  conditions:
                    - condition: state
                      entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                      state: "on"
                    - condition: template
                      value_template: >-
                        {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                        {{ r.startswith('STARTED') or r.startswith('FAILED') or r.startswith('CANCELLED') or r.startswith('BLOCKED') }}
                    - condition: template
                      value_template: >-
                        {{ repeat.index >= (max_attempts | int(60))
                           or as_timestamp(now()) >= (retry_until | float(0))
                           or not is_state('input_boolean.ecco_free_power_schedule_armed', 'on')
                           or as_timestamp(states.input_boolean.ecco_free_power_schedule_armed.last_changed, 0) > (run_started | float(0)) }}
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                  {{ not is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')
                     and not r.startswith('STARTED') and not r.startswith('FAILED') and not r.startswith('BLOCKED')
                     and not (is_state('input_boolean.ecco_free_power_schedule_armed', 'on')
                              and as_timestamp(states.input_boolean.ecco_free_power_schedule_armed.last_changed, 0)
                                  <= (run_started | float(0))) }}
            then:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "CANCELLED - scheduled Free Power cancelled before it started"
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                  {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and not r.startswith('STARTED') }}
            then:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "STARTED OK - Free Power is active; this run could not confirm the start as its own (check power and end time)"
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                  {{ not is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')
                     and not r.startswith('STARTED') and not r.startswith('FAILED') and not r.startswith('CANCELLED')
                     and not r.startswith('BLOCKED') }}
            then:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    FAILED TO START - retries ended at {{ now().strftime('%H:%M') }}:
                    {{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }}
      # The write enable always ends off (the safe state: it only permits a START).
      - action: switch.turn_off
        continue_on_error: true
        target:
          entity_id: switch.ecco_clock_dongle_free_power_write_enable
      # The owner hears about every failure at once; a later success clears the alert.
      - if:
          - condition: template
            value_template: >-
              {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
              {{ r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)
                 or not (r.startswith('STARTED') or r.startswith('CANCELLED') or r.startswith('BLOCKED')
                         or is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on')) }}
        then:
          - action: persistent_notification.create
            data:
              notification_id: ecco_free_power_schedule
              title: "ECCO: scheduled Free Power did NOT start"
              message: >-
                {{ states('input_text.ecco_free_power_schedule_last_result') }}

                Authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}.
                If time remains and the reason is cleared, use Free Power now in Energy Actions.
                If a start transaction began or the outcome is unconfirmed, check the Free Power status
                and recovery state first.
        else:
          - if:
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "on"
            then:
              - action: persistent_notification.dismiss
                data:
                  notification_id: ecco_free_power_schedule
              - action: persistent_notification.dismiss
                data:
                  notification_id: ecco_free_power_schedule_readiness

  ecco_free_power_cancel_schedule:
    alias: "ECCO - Cancel scheduled Free Power"
    description: "Cancels a future scheduled Free Power event. It does not stop an already-active Free Power run."
    mode: single
    sequence:
      - action: input_boolean.turn_off
        target:
          entity_id: input_boolean.ecco_free_power_schedule_armed
      - action: input_text.set_value
        target:
          entity_id: input_text.ecco_free_power_schedule_last_result
        data:
          value: "CANCELLED - scheduled event disarmed"

automation:
  - id: ecco_free_power_schedule_arm_validation
    alias: "ECCO - Validate scheduled Free Power arm"
    mode: restart
    triggers:
      - trigger: state
        entity_id: input_boolean.ecco_free_power_schedule_armed
        to: "on"
    actions:
      - variables:
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          scheduled_power: "{{ states('input_number.ecco_free_power_schedule_power') | int(0) }}"
          effective_limit: "{{ states('sensor.ecco_config_maximum_grid_charge_power') | int(0) }}"
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ (effective_limit | int(0)) <= 0 }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "REJECTED - effective grid charge power limit unavailable"
          - conditions:
              - condition: template
                value_template: >-
                  {{ (scheduled_power | int(0)) < 500
                     or (scheduled_power | int(0)) > (effective_limit | int(0)) }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    REJECTED - scheduled {{ scheduled_power }}W outside safe range
                    500-{{ effective_limit }}W
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "REJECTED - scheduled start must be in the future"
          # 2026-09-26 (Manual Dump-to-Grid V1): additive early UX check only.
          # Refuse to arm when an ARMED Scheduled Dump to Grid window overlaps
          # this one (2-minute buffer either side for start retry / restore).
          # Inert when ecco_dump_to_grid_schedule.yaml is not installed (the
          # helper then never reads "on"). The firmware's own mutual-exclusion
          # gates stay authoritative regardless.
          - conditions:
              - condition: state
                entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
                state: "on"
              - condition: template
                value_template: >-
                  {% set f_start = start_ts | float(0) %}
                  {% set f_end = f_start + (states('input_number.ecco_free_power_schedule_duration') | int(0)) * 60 %}
                  {% set d_start = as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) %}
                  {% set d_end = d_start + (states('input_number.ecco_dump_to_grid_schedule_duration') | int(0)) * 60 %}
                  {{ f_start < d_end + 120 and d_start < f_end + 120 }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    REJECTED - overlaps the armed Scheduled Dump to Grid window
                    ({{ states('input_datetime.ecco_dump_to_grid_schedule_start') }}); cancel it first
        default:
          - action: input_text.set_value
            target:
              entity_id: input_text.ecco_free_power_schedule_last_result
            data:
              value: >-
                ARMED - {{ states('input_datetime.ecco_free_power_schedule_start') }} •
                {{ states('input_number.ecco_free_power_schedule_duration') | int }} min •
                {{ states('input_number.ecco_free_power_schedule_power') | int }}W
          - action: persistent_notification.dismiss
            data:
              notification_id: ecco_free_power_schedule

  - id: ecco_free_power_schedule_fire
    alias: "ECCO - Fire scheduled Free Power"
    # single + silent: a watchdog tick that arrives while the start is still retrying is dropped.
    mode: single
    max_exceeded: silent
    triggers:
      - trigger: time
        at: input_datetime.ecco_free_power_schedule_start
        id: start
      # Readiness: from 5 minutes before the start (now() templates re-render every minute).
      - trigger: template
        id: readiness
        value_template: >-
          {% set s = as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) %}
          {{ is_state('input_boolean.ecco_free_power_schedule_armed', 'on') and s > 0
             and 0 < s - as_timestamp(now()) <= 300 }}
      # Watchdog: still armed 3 minutes after the start means the start never ran.
      - trigger: template
        id: watchdog
        value_template: >-
          {% set s = as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) %}
          {{ is_state('input_boolean.ecco_free_power_schedule_armed', 'on') and s > 0
             and as_timestamp(now()) - s >= 180
             and as_timestamp(states.input_boolean.ecco_free_power_schedule_armed.last_changed, 0) < s }}
    conditions:
      - condition: state
        entity_id: input_boolean.ecco_free_power_schedule_armed
        state: "on"
    actions:
      - variables:
          fired_for: "{{ states('input_datetime.ecco_free_power_schedule_start') }}"
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          end_ts: "{{ (start_ts | float(0)) + (states('input_number.ecco_free_power_schedule_duration') | int(1)) * 60 }}"
      - choose:
          - conditions:
              - condition: trigger
                id: readiness
            sequence:
              - variables:
                  blockers: >-
                    {% set r = namespace(v=[]) %}
                    {% if not is_state('binary_sensor.ecco_clock_dongle_telemetry_online', 'on') %}{% set r.v = r.v + ['telemetry offline'] %}{% endif %}
                    {% if not is_state('binary_sensor.ecco_clock_dongle_configuration_online', 'on') %}{% set r.v = r.v + ['inverter configuration offline'] %}{% endif %}
                    {% if not is_state('binary_sensor.ecco_clock_dongle_ntp_synced', 'on') %}{% set r.v = r.v + ['dongle NTP time not synced'] %}{% endif %}
                    {% if states('switch.ecco_clock_dongle_free_power_write_enable') not in ['on', 'off'] %}{% set r.v = r.v + ['dongle unavailable'] %}{% endif %}
                    {% if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') %}{% set r.v = r.v + ['Free Power already active'] %}{% endif %}
                    {% if is_state('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'on') %}{% set r.v = r.v + ['a saved Free Power snapshot is pending restore'] %}{% endif %}
                    {% if is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') or is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'on') %}{% set r.v = r.v + ['Dump to Grid owns the inverter settings'] %}{% endif %}
                    {% set lim = states('sensor.ecco_config_maximum_grid_charge_power') | int(0) %}
                    {% set pw = states('input_number.ecco_free_power_schedule_power') | int(0) %}
                    {% if lim <= 0 or pw > lim %}{% set r.v = r.v + ['requested power outside the effective grid charge limit'] %}{% endif %}
                    {{ r.v | join('; ') }}
              # Let the arm validation finish first: a schedule it refuses gets no readiness alert.
              - delay:
                  seconds: 2
              - if:
                  - condition: template
                    value_template: "{{ blockers | length > 0 }}"
                  - condition: state
                    entity_id: input_boolean.ecco_free_power_schedule_armed
                    state: "on"
                then:
                  - action: persistent_notification.create
                    data:
                      notification_id: ecco_free_power_schedule_readiness
                      title: "ECCO: scheduled Free Power is not ready"
                      message: >-
                        Free Power is due at {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} but would be refused now:
                        {{ blockers }}. ECCO will still try at the start time (and retry transient refusals for
                        up to 10 minutes), but clear these first if you can.
          - conditions:
              - condition: trigger
                id: watchdog
              # A start still retrying (for example after a restart recovery) is not a missed start.
              - condition: state
                entity_id: script.ecco_free_power_start_scheduled
                state: "off"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_free_power_schedule
                  title: "ECCO: scheduled Free Power start was missed"
                  message: >-
                    The {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} start never ran (still armed at
                    {{ now().strftime('%H:%M') }}). ECCO is starting it now for the rest of the window, ending by
                    {{ (end_ts | float(0)) | timestamp_custom('%H:%M') }}.
              - action: script.ecco_free_power_start_scheduled
                continue_on_error: true
                data:
                  duration_minutes: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
                  power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
                  window_end_ts: "{{ end_ts }}"
              # Disarm only the schedule this run was for (the owner may have re-armed a new one).
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_free_power_schedule_armed
          # Only the start trigger starts on time; a readiness or watchdog tick never falls through to here.
          - conditions:
              - condition: trigger
                id: start
            sequence:
              - action: script.ecco_free_power_start_scheduled
                continue_on_error: true
                data:
                  duration_minutes: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
                  power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
                  window_end_ts: "{{ end_ts }}"
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_free_power_schedule_armed

  - id: ecco_free_power_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Free Power after Home Assistant restart"
    mode: single
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      - delay: "00:00:20"
      # Give the dongle time to reconnect before judging its state (bounded).
      - wait_template: "{{ states('binary_sensor.ecco_clock_dongle_free_power_active') in ['on', 'off'] }}"
        timeout: "00:03:00"
        continue_on_timeout: true
      # A restart between an arm and its press must not leave the write enable on (unless a start is running).
      - if:
          - condition: state
            entity_id: script.ecco_free_power_start_scheduled
            state: "off"
        then:
          - action: switch.turn_off
            continue_on_error: true
            target:
              entity_id: switch.ecco_clock_dongle_free_power_write_enable
      - variables:
          fired_for: "{{ states('input_datetime.ecco_free_power_schedule_start') }}"
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          duration_min: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
          end_ts: "{{ start_ts + (duration_min * 60) }}"
          now_ts: "{{ as_timestamp(now()) }}"
      - choose:
          # Not armed any more, or the on-time start is already running: nothing to recover.
          - conditions:
              - condition: or
                conditions:
                  - condition: state
                    entity_id: input_boolean.ecco_free_power_schedule_armed
                    state: "off"
                  - condition: state
                    entity_id: script.ecco_free_power_start_scheduled
                    state: "on"
            sequence: []
          - conditions:
              - condition: template
                value_template: "{{ now_ts < start_ts }}"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: >-
                    ARMED AFTER RESTART - waiting for {{ states('input_datetime.ecco_free_power_schedule_start') }}
          # Restarted while the session runs: it started; record it and disarm.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "on"
            sequence:
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "STARTED OK - running (Home Assistant restarted during the session)"
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_free_power_schedule
                  title: "ECCO: scheduled Free Power start was missed"
                  message: >-
                    Home Assistant restarted during the scheduled Free Power window. ECCO is starting it now
                    for the rest of the window, ending by {{ (end_ts | float(0)) | timestamp_custom('%H:%M') }}.
              - action: script.ecco_free_power_start_scheduled
                continue_on_error: true
                data:
                  duration_minutes: "{{ duration_min }}"
                  power_w: "{{ power_w }}"
                  window_end_ts: "{{ end_ts }}"
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_free_power_schedule_armed
        default:
          - action: input_boolean.turn_off
            target:
              entity_id: input_boolean.ecco_free_power_schedule_armed
          - action: input_text.set_value
            target:
              entity_id: input_text.ecco_free_power_schedule_last_result
            data:
              value: "MISSED - scheduled Free Power window already expired"
          - action: persistent_notification.create
            data:
              notification_id: ecco_free_power_schedule
              title: "ECCO: scheduled Free Power was missed"
              message: >-
                Home Assistant was not running for the whole scheduled Free Power window
                (ended {{ (end_ts | float(0)) | timestamp_custom('%H:%M') }}). Nothing was started.

template:
  - sensor:
      - name: ECCO Free Power Schedule Status
        unique_id: ecco_free_power_schedule_status
        icon: mdi:calendar-clock
        # ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE. FAILED and COMPLETED describe the
        # last scheduled run until the schedule is armed again.
        state: >-
          {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
          {% if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') %}
            ACTIVE
          {% elif is_state('script.ecco_free_power_start_scheduled', 'on') %}
            STARTING
          {% elif is_state('input_boolean.ecco_free_power_schedule_armed', 'on') %}
            ARMED
          {% elif r.startswith('FAILED') or r.startswith('MISSED')
                  or (r.startswith('BLOCKED') and 'already active' not in r) %}
            FAILED
          {% elif r.startswith('STARTED') %}
            COMPLETED
""")
PACKAGE_EDITS = (
    (PACKAGE_0_OLD, PACKAGE_0_NEW),
)


def pre_fps1_package(text: str) -> str:
    """home-assistant/packages/ecco_free_power_schedule.yaml with exactly fps1's edits undone (a frozen reverter of chain entry fps1, PEX): its text as of fe1."""
    return _revert(text, PACKAGE_EDITS, "home-assistant/packages/ecco_free_power_schedule.yaml")


pre_fps1_package.edits = PACKAGE_EDITS   # the PEX contract: a reverter exposes its exact (before, after) pairs


def add_fps1_package(text: str) -> str:
    """Applies fps1's home-assistant/packages/ecco_free_power_schedule.yaml edits to the text as of fe1 (the round trip)."""
    return _apply(text, PACKAGE_EDITS, "home-assistant/packages/ecco_free_power_schedule.yaml")


# Every frozen file fps1 edits, with its reverter (the chain entry's frozen_reverts).
FROZEN_REVERTERS = {
    PACKAGE_REL: pre_fps1_package,
}
# fps1 edits no chain-pinned file.
PINNED_REVERTERS: dict = {}
