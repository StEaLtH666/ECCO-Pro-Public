"""r9 (no automatic start of a missed scheduled run after a Home Assistant restart) change scope: exactly what r9 changes in the two
frozen schedule packages (and the two frozen suites whose pins they move), as exact (before, after) pairs, and their exact inverse.

Same technique as the earlier post-export scope modules (_fps1_scope, _dgs1_scope): every verbatim edit is held HERE as the single source of
truth, round-trip-checked, and each reverter raises unless each of its edits is present exactly once. The post-export chain entry `r9`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended after isp1; registry/tests/_pex.py) carries two frozen reverters.

WHAT r9 IS. The owner's requirement of 12 Nov 2026 (docs/dev/grid-loss-interlock-spec.md, section 5 R9 and 6.4): a missed scheduled Charge Battery
(ecco_free_power_schedule.yaml) or Export to Grid (ecco_dump_to_grid_schedule.yaml) session must not start automatically after a Home Assistant
restart, on either start path (the startup recovery and the schedule watchdog); a future occurrence is kept; the on-time start is unchanged.
Per package: one helper (input_datetime.<pkg>_ha_start, written only by the new capture automation on the `homeassistant` start event), that
capture automation, a guard (`ha_start_known`, `missed_run`) in the fire automation and in the startup recovery, a new watchdog branch that
records, notifies and disarms a missed run, the `not missed_run` condition on the watchdog's start, and in the recovery the start branch
replaced by the same record, notification and disarm (and a branch that leaves a start between the Home Assistant start and the recovery's
evaluation to the normal triggers). Status text `MISSED - not started after a Home Assistant restart` (the status sensor already maps MISSED to
FAILED). It makes starts only more conservative: no new service other than input_datetime.set_datetime on its own helper, no register, no
dongle entity written that was not written before. ZERO firmware, registry data, manifest (the packages are already deployed), dashboard or
card byte. Offline only; not installed.

This module imports no other scope module, not _scope_chain (the chain imports it) and not _pex. No I/O.
"""

from __future__ import annotations

import hashlib

ADDED_FILES = frozenset({
    "registry/tests/_r9_scope.py",
    "registry/tests/test_ha_r9_missed_runs.py",
})

DUMP_REL = "home-assistant/packages/ecco_dump_to_grid_schedule.yaml"
FREE_REL = "home-assistant/packages/ecco_free_power_schedule.yaml"
PKGTEST_REL = "home-assistant/tests/test_ecco_dump_to_grid_schedule_package.py"
SHADOW_REL = "home-assistant/tests/test_ecco_shadow_check_ux.py"


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"r9 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def _revert(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in reversed(list(enumerate(edits))):
        out = _swap(out, after, before, f"{what} edit {k}", "present")
    for k, (before, _after) in enumerate(edits):
        n = out.count(before)
        if n != 1:
            raise AssertionError(f"r9 scope: {what} anchor {k} must be unique once the edits are removed, found {n}x")
    return out


def _apply(text: str, edits: tuple, what: str) -> str:
    out = text
    for k, (before, after) in enumerate(edits):
        if after in out:
            raise AssertionError(f"r9 scope: {what} edit {k} is already present")
        out = _swap(out, before, after, f"{what} anchor {k}", "found")
    return out


# ---- (PEX frozen edits) the two schedule packages ------------------------------------------------------------------------------
PKGTEST_0_OLD = '           "input_boolean.turn_off", "script.ecco_dump_to_grid_start_scheduled",\n           # dgs1: a failed or missed scheduled start raises (and a later start clears) a persistent notification\n           "persistent_notification.create", "persistent_notification.dismiss"}\ncheck("every service the package calls is staging/arm/press/helper-only", actions <= allowed, f"{sorted(actions - allowed)}")\ncheck("no modbus/esphome raw-write services", not re.search(r"modbus\\.|esphome\\.|write_register", text))\n'
PKGTEST_0_NEW = '           "input_boolean.turn_off", "script.ecco_dump_to_grid_start_scheduled",\n           # dgs1: a failed or missed scheduled start raises (and a later start clears) a persistent notification\n           "persistent_notification.create", "persistent_notification.dismiss",\n           # r9: the capture automation writes the captured Home Assistant start into the package\'s own helper\n           "input_datetime.set_datetime"}\ncheck("every service the package calls is staging/arm/press/helper-only", actions <= allowed, f"{sorted(actions - allowed)}")\ncheck("no modbus/esphome raw-write services", not re.search(r"modbus\\.|esphome\\.|write_register", text))\n'

PKGTEST_EDITS = (
    (PKGTEST_0_OLD, PKGTEST_0_NEW),
)

SHADOW_0_OLD = _blk(r"""
      PKG_SURFACE == {
          "ecco_battery_outlook_influx.yaml": {"sensor": 1}, "ecco_canonical_telemetry.yaml": {},
          "ecco_dump_to_grid_schedule.yaml": {"input_boolean": 1, "input_datetime": 1, "input_number": 3, "input_text": 1, "script": 2, "automation": 3},
          "ecco_fallback_profile_actions.yaml": {"script": 4}, "ecco_fallback_status.yaml": {"input_boolean": 1},
          "ecco_free_power_schedule.yaml": {"input_boolean": 1, "input_datetime": 1, "input_number": 2, "input_text": 1, "script": 2, "automation": 3},
          "ecco_manual_controls_helpers.yaml": {"input_datetime": 6, "input_number": 12, "automation": 8, "script": 1},
          "ecco_pro.yaml": {"input_select": 2, "input_boolean": 8, "input_number": 25, "input_datetime": 2, "automation": 3},
""")
SHADOW_0_NEW = _blk(r"""
      PKG_SURFACE == {
          "ecco_battery_outlook_influx.yaml": {"sensor": 1}, "ecco_canonical_telemetry.yaml": {},
          "ecco_dump_to_grid_schedule.yaml": {"input_boolean": 1, "input_datetime": 2, "input_number": 3, "input_text": 1, "script": 2, "automation": 4},   # r9: +1 captured-start helper, +1 capture automation
          "ecco_fallback_profile_actions.yaml": {"script": 4}, "ecco_fallback_status.yaml": {"input_boolean": 1},
          "ecco_free_power_schedule.yaml": {"input_boolean": 1, "input_datetime": 2, "input_number": 2, "input_text": 1, "script": 2, "automation": 4},   # r9: +1 captured-start helper, +1 capture automation
          "ecco_manual_controls_helpers.yaml": {"input_datetime": 6, "input_number": 12, "automation": 8, "script": 1},
          "ecco_pro.yaml": {"input_select": 2, "input_boolean": 8, "input_number": 25, "input_datetime": 2, "automation": 3},
""")

SHADOW_EDITS = (
    (SHADOW_0_OLD, SHADOW_0_NEW),
)

DUMP_0_OLD = _blk(r"""
#   - a readiness check 5 min before, a missed-trigger watchdog 3 min after, restart recovery, and a
#     persistent notification for every failure or miss; the write enable always ends off.

input_boolean:
  ecco_dump_to_grid_schedule_armed:
    name: ECCO Scheduled Dump to Grid Armed
    icon: mdi:calendar-check

input_datetime:
  ecco_dump_to_grid_schedule_start:
    name: ECCO Dump to Grid Schedule Start
    has_date: true
    has_time: true
""")
DUMP_0_NEW = _blk(r"""
#   - a readiness check 5 min before, a missed-trigger watchdog 3 min after, restart recovery, and a
#     persistent notification for every failure or miss; the write enable always ends off.
#
# R9 (2026-11, owner requirement of 12 Nov): a missed scheduled run is never started after a Home Assistant restart. A start
# time earlier than the captured Home Assistant start (or any start time while that capture is unknown or stale: fail closed)
# is recorded as `MISSED - not started after a Home Assistant restart`, notified and disarmed by BOTH the watchdog and the
# startup recovery; a future occurrence stays armed and starts on time. Header text above predates R9: where it speaks of the
# watchdog or restart recovery starting a late run, read R9.
# DEVIATION (deliberate): the captured Home Assistant start means 'when the clock was first trusted', which can be seconds to
# minutes after the true boot. A start in that gap counts as missed (fail closed): if its on-time trigger fired it runs normally;
# only a LOST on-time trigger is refused by the watchdog. The dongle's NTP Time text carries local time without an offset, so the
# check assumes Home Assistant's time zone is Europe/London (otherwise the capture stays unknown and everything fails closed); an
# unambiguous comparison needs a future firmware change to publish an offset or an epoch.
# DEPLOY: install this change with a FULL Home Assistant restart (not a package reload). The capture runs only on the start
# event, so after a reload the captured start stays unknown and every guard fails closed: the watchdog will NOT rescue a lost
# on-time start until the next full restart. The capture also waits (up to 10 minutes) for the dongle's NTP to be synced and
# for Home Assistant's clock to agree with it; if that never happens the capture stays unknown (fail closed).

input_boolean:
  ecco_dump_to_grid_schedule_armed:
    name: ECCO Scheduled Dump to Grid Armed
    icon: mdi:calendar-check

input_datetime:
  ecco_dump_to_grid_schedule_start:
    name: ECCO Dump to Grid Schedule Start
    has_date: true
    has_time: true

  # R9 (no automatic start of a missed run after a Home Assistant restart): the time Home Assistant last
  # started, written ONLY by ecco_dump_to_grid_ha_start_capture on the `homeassistant` start event. Never edit
  # it by hand. Helpers are restored across a restart, so a value this boot did not write is stale: the guards
  # then treat the start as unknown and fail closed (nothing starts).
  ecco_dump_to_grid_ha_start:
    name: ECCO Dump to Grid HA Start (captured)
    has_date: true
    has_time: true
""")

DUMP_1_OLD = _blk(r"""
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) }}"
          end_ts: "{{ (start_ts | float(0)) + (states('input_number.ecco_dump_to_grid_schedule_duration') | int(1)) * 60 }}"
      - choose:
          - conditions:
""")
DUMP_1_NEW = _blk(r"""
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) }}"
          end_ts: "{{ (start_ts | float(0)) + (states('input_number.ecco_dump_to_grid_schedule_duration') | int(1)) * 60 }}"
          # R9: a start time earlier than the captured Home Assistant start is a missed run, and so is any start
          # time while the capture is unknown or stale (fail closed). Compared directly, never via last_changed.
          ha_start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_ha_start'), 0) }}"
          ha_start_known: >-
            {% set c = states('input_datetime.ecco_dump_to_grid_ha_start') %}
            {% set cs = as_timestamp(c, 0) %}
            {% set o = states.input_datetime.ecco_dump_to_grid_ha_start %}
            {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
            {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
               and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
          missed_run: "{{ not ha_start_known or (start_ts | float(0)) <= (ha_start_ts | float(0)) }}"
      - choose:
          - conditions:
""")

DUMP_2_OLD = _blk(r"""
                        {{ blockers }}. ECCO will still try at the start time (and retry transient refusals for
                        up to 10 minutes), but clear these first if you can.
          - conditions:
              - condition: trigger
                id: watchdog
              # A start still retrying (for example after a restart recovery) is not a missed start.
              - condition: state
                entity_id: script.ecco_dump_to_grid_start_scheduled
                state: "off"
            sequence:
              - action: persistent_notification.create
""")
DUMP_2_NEW = _blk(r"""
                        {{ blockers }}. ECCO will still try at the start time (and retry transient refusals for
                        up to 10 minutes), but clear these first if you can.
          # R9: a start time that fell before Home Assistant started (or while its start is unknown) is a missed
          # run. It is recorded, notified and disarmed, never started. Listed BEFORE the watchdog's start below.
          - conditions:
              - condition: trigger
                id: watchdog
              - condition: state
                entity_id: script.ecco_dump_to_grid_start_scheduled
                state: "off"
              - condition: template
                value_template: "{{ missed_run }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_dump_to_grid_schedule
                  title: "ECCO: scheduled Dump to Grid was missed"
                  message: >-
                    The {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} scheduled Dump to Grid start
                    {{ 'fell before Home Assistant started.' if ha_start_known else
                    'was not started: the Home Assistant start time was unknown, so ECCO could not tell whether it fell before Home Assistant started (failed closed).' }}
                    It was NOT started and the schedule is disarmed. Arm a new schedule if you still want it.
              # Disarm only the schedule this miss was for (the owner may have re-armed a new one).
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_dump_to_grid_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                    data:
                      value: >-
                        {{ 'MISSED - not started after a Home Assistant restart' if ha_start_known else
                        'MISSED - not started: the Home Assistant start time was unknown, so ECCO could not tell whether the start fell before it (failed closed)' }}
          - conditions:
              - condition: trigger
                id: watchdog
              # A start still retrying (for example after a restart recovery) is not a missed start.
              - condition: state
                entity_id: script.ecco_dump_to_grid_start_scheduled
                state: "off"
              # R9 guard: never the start of a missed run (the branch above records it).
              - condition: template
                value_template: "{{ not missed_run }}"
            sequence:
              - action: persistent_notification.create
""")

DUMP_3_OLD = _blk(r"""
                      entity_id: input_boolean.ecco_dump_to_grid_schedule_armed

  - id: ecco_dump_to_grid_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Dump to Grid after Home Assistant restart"
""")
DUMP_3_NEW = _blk(r"""
                      entity_id: input_boolean.ecco_dump_to_grid_schedule_armed

  # R9: capture the time Home Assistant started, once per start, so the two start paths that run after a
  # restart (the startup recovery and the watchdog) can tell a missed run from a start that fell while Home
  # Assistant was running. Written nowhere else; never derived from any entity's last_changed.
  - id: ecco_dump_to_grid_ha_start_capture
    alias: "ECCO - Capture Home Assistant start time (Dump to Grid)"
    mode: single
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      # The clock must be trustworthy before it is captured: a host without an RTC can boot with a clock that is behind, and a capture
      # of that early time would pass the staleness check (last_updated is stamped by the same clock). Wait (bounded) until the dongle's
      # NTP is synced and Home Assistant's time agrees with the dongle's NTP time (published about once a minute, so 120 s is allowed).
      # If that never happens the helper is left alone: unknown or stale, and every guard fails closed.
      - wait_template: >-
          {% set n = states('sensor.ecco_clock_dongle_ntp_time') %}
          {{ is_state('binary_sensor.ecco_clock_dongle_ntp_synced', 'on')
             and (as_timestamp(now()) - as_timestamp(n, 0)) | abs <= 120 }}
        timeout: "00:10:00"
        continue_on_timeout: true
      - if:
          - condition: template
            value_template: "{{ wait.completed }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.ecco_dump_to_grid_ha_start
            data:
              timestamp: "{{ as_timestamp(now()) | int }}"

  - id: ecco_dump_to_grid_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Dump to Grid after Home Assistant restart"
""")

DUMP_4_OLD = _blk(r"""
            target:
              entity_id: switch.ecco_clock_dongle_dump_to_grid_write_enable
      - variables:
          fired_for: "{{ states('input_datetime.ecco_dump_to_grid_schedule_start') }}"
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) }}"
          duration_min: "{{ states('input_number.ecco_dump_to_grid_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_dump_to_grid_schedule_power') | int(500) }}"
          stop_soc: "{{ states('input_number.ecco_dump_to_grid_schedule_stop_soc') | int(25) }}"
          end_ts: "{{ start_ts + (duration_min * 60) }}"
          now_ts: "{{ as_timestamp(now()) }}"
      - choose:
          # Not armed any more, or the on-time start is already running: nothing to recover.
""")
DUMP_4_NEW = _blk(r"""
            target:
              entity_id: switch.ecco_clock_dongle_dump_to_grid_write_enable
      # R9: give the capture (it waits for a trustworthy clock) a bounded time before judging; unknown after that fails closed.
      - wait_template: >-
          {% set c = states('input_datetime.ecco_dump_to_grid_ha_start') %}
          {% set cs = as_timestamp(c, 0) %}
          {% set o = states.input_datetime.ecco_dump_to_grid_ha_start %}
          {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
          {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
             and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
        timeout: "00:03:00"
        continue_on_timeout: true
      - variables:
          fired_for: "{{ states('input_datetime.ecco_dump_to_grid_schedule_start') }}"
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_schedule_start'), 0) }}"
          duration_min: "{{ states('input_number.ecco_dump_to_grid_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_dump_to_grid_schedule_power') | int(500) }}"
          stop_soc: "{{ states('input_number.ecco_dump_to_grid_schedule_stop_soc') | int(25) }}"
          end_ts: "{{ start_ts + (duration_min * 60) }}"
          now_ts: "{{ as_timestamp(now()) }}"
          # R9: same definition as the fire automation's guard (the package test pins them identical).
          ha_start_ts: "{{ as_timestamp(states('input_datetime.ecco_dump_to_grid_ha_start'), 0) }}"
          ha_start_known: >-
            {% set c = states('input_datetime.ecco_dump_to_grid_ha_start') %}
            {% set cs = as_timestamp(c, 0) %}
            {% set o = states.input_datetime.ecco_dump_to_grid_ha_start %}
            {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
            {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
               and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
          missed_run: "{{ not ha_start_known or (start_ts | float(0)) <= (ha_start_ts | float(0)) }}"
      - choose:
          # Not armed any more, or the on-time start is already running: nothing to recover.
""")

DUMP_5_OLD = _blk(r"""
                target:
                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_dump_to_grid_schedule
                  title: "ECCO: scheduled Dump to Grid start was missed"
                  message: >-
                    Home Assistant restarted during the scheduled Dump to Grid window. ECCO is starting it now
                    for the rest of the window, ending by {{ (end_ts | float(0)) | timestamp_custom('%H:%M') }}.
              - action: script.ecco_dump_to_grid_start_scheduled
                continue_on_error: true
                data:
                  duration_minutes: "{{ duration_min }}"
                  power_w: "{{ power_w }}"
                  stop_soc: "{{ stop_soc }}"
                  window_end_ts: "{{ end_ts }}"
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_dump_to_grid_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
        default:
          - action: input_boolean.turn_off
""")
DUMP_5_NEW = _blk(r"""
                target:
                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
          # R9: a start time between the Home Assistant start and this evaluation is not a missed run: the normal
          # triggers own it (the on-time start fired, or is still to fire); this recovery neither starts nor disarms it.
          - conditions:
              - condition: template
                value_template: "{{ not missed_run and now_ts < end_ts }}"
            sequence: []
          # R9: a start time before the Home Assistant start (or an unknown / stale capture: fail closed) with the
          # window still open is a missed run. It is NOT started: recorded, notified, and only it is disarmed.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_dump_to_grid_schedule
                  title: "ECCO: scheduled Dump to Grid was missed"
                  message: >-
                    The {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} scheduled Dump to Grid start
                    {{ 'fell before Home Assistant started.' if ha_start_known else
                    'was not started: the Home Assistant start time was unknown, so ECCO could not tell whether it fell before Home Assistant started (failed closed).' }}
                    It was NOT started and the schedule is disarmed. Arm a new schedule if you still want it.
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_dump_to_grid_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                    data:
                      value: >-
                        {{ 'MISSED - not started after a Home Assistant restart' if ha_start_known else
                        'MISSED - not started: the Home Assistant start time was unknown, so ECCO could not tell whether the start fell before it (failed closed)' }}
        default:
          - action: input_boolean.turn_off
""")

DUMP_EDITS = (
    (DUMP_0_OLD, DUMP_0_NEW),
    (DUMP_1_OLD, DUMP_1_NEW),
    (DUMP_2_OLD, DUMP_2_NEW),
    (DUMP_3_OLD, DUMP_3_NEW),
    (DUMP_4_OLD, DUMP_4_NEW),
    (DUMP_5_OLD, DUMP_5_NEW),
)

FREE_0_OLD = _blk(r"""
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
""")
FREE_0_NEW = _blk(r"""
#   - a readiness check 5 min before, a missed-trigger watchdog 3 min after, restart recovery,
#     and a persistent notification for every failure or miss; the write enable always ends off.
#
# R9 (2026-11, owner requirement of 12 Nov): a missed scheduled run is never started after a Home Assistant restart. A start
# time earlier than the captured Home Assistant start (or any start time while that capture is unknown or stale: fail closed)
# is recorded as `MISSED - not started after a Home Assistant restart`, notified and disarmed by BOTH the watchdog and the
# startup recovery; a future occurrence stays armed and starts on time. Header text above predates R9: where it speaks of the
# watchdog or restart recovery starting a late run, read R9.
# DEVIATION (deliberate): the captured Home Assistant start means 'when the clock was first trusted', which can be seconds to
# minutes after the true boot. A start in that gap counts as missed (fail closed): if its on-time trigger fired it runs normally;
# only a LOST on-time trigger is refused by the watchdog. The dongle's NTP Time text carries local time without an offset, so the
# check assumes Home Assistant's time zone is Europe/London (otherwise the capture stays unknown and everything fails closed); an
# unambiguous comparison needs a future firmware change to publish an offset or an epoch.
# DEPLOY: install this change with a FULL Home Assistant restart (not a package reload). The capture runs only on the start
# event, so after a reload the captured start stays unknown and every guard fails closed: the watchdog will NOT rescue a lost
# on-time start until the next full restart. The capture also waits (up to 10 minutes) for the dongle's NTP to be synced and
# for Home Assistant's clock to agree with it; if that never happens the capture stays unknown (fail closed).

input_boolean:
  ecco_free_power_schedule_armed:
    name: ECCO Scheduled Free Power Armed
    icon: mdi:calendar-check

input_datetime:
  ecco_free_power_schedule_start:
    name: ECCO Free Power Schedule Start
    has_date: true
    has_time: true

  # R9 (no automatic start of a missed run after a Home Assistant restart): the time Home Assistant last
  # started, written ONLY by ecco_free_power_ha_start_capture on the `homeassistant` start event. Never edit
  # it by hand. Helpers are restored across a restart, so a value this boot did not write is stale: the guards
  # then treat the start as unknown and fail closed (nothing starts).
  ecco_free_power_ha_start:
    name: ECCO Free Power HA Start (captured)
    has_date: true
    has_time: true
""")

FREE_1_OLD = _blk(r"""
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          end_ts: "{{ (start_ts | float(0)) + (states('input_number.ecco_free_power_schedule_duration') | int(1)) * 60 }}"
      - choose:
          - conditions:
""")
FREE_1_NEW = _blk(r"""
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          end_ts: "{{ (start_ts | float(0)) + (states('input_number.ecco_free_power_schedule_duration') | int(1)) * 60 }}"
          # R9: a start time earlier than the captured Home Assistant start is a missed run, and so is any start
          # time while the capture is unknown or stale (fail closed). Compared directly, never via last_changed.
          ha_start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_ha_start'), 0) }}"
          ha_start_known: >-
            {% set c = states('input_datetime.ecco_free_power_ha_start') %}
            {% set cs = as_timestamp(c, 0) %}
            {% set o = states.input_datetime.ecco_free_power_ha_start %}
            {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
            {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
               and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
          missed_run: "{{ not ha_start_known or (start_ts | float(0)) <= (ha_start_ts | float(0)) }}"
      - choose:
          - conditions:
""")

FREE_2_OLD = _blk(r"""
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
""")
FREE_2_NEW = _blk(r"""
                        {{ blockers }}. ECCO will still try at the start time (and retry transient refusals for
                        up to 10 minutes), but clear these first if you can.
          # R9: a start time that fell before Home Assistant started (or while its start is unknown) is a missed
          # run. It is recorded, notified and disarmed, never started. Listed BEFORE the watchdog's start below.
          - conditions:
              - condition: trigger
                id: watchdog
              - condition: state
                entity_id: script.ecco_free_power_start_scheduled
                state: "off"
              - condition: template
                value_template: "{{ missed_run }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_free_power_schedule
                  title: "ECCO: scheduled Free Power was missed"
                  message: >-
                    The {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} scheduled Free Power start
                    {{ 'fell before Home Assistant started.' if ha_start_known else
                    'was not started: the Home Assistant start time was unknown, so ECCO could not tell whether it fell before Home Assistant started (failed closed).' }}
                    It was NOT started and the schedule is disarmed. Arm a new schedule if you still want it.
              # Disarm only the schedule this miss was for (the owner may have re-armed a new one).
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_free_power_schedule_armed
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: >-
                        {{ 'MISSED - not started after a Home Assistant restart' if ha_start_known else
                        'MISSED - not started: the Home Assistant start time was unknown, so ECCO could not tell whether the start fell before it (failed closed)' }}
          - conditions:
              - condition: trigger
                id: watchdog
              # A start still retrying (for example after a restart recovery) is not a missed start.
              - condition: state
                entity_id: script.ecco_free_power_start_scheduled
                state: "off"
              # R9 guard: never the start of a missed run (the branch above records it).
              - condition: template
                value_template: "{{ not missed_run }}"
            sequence:
              - action: persistent_notification.create
""")

FREE_3_OLD = _blk(r"""
                      entity_id: input_boolean.ecco_free_power_schedule_armed

  - id: ecco_free_power_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Free Power after Home Assistant restart"
""")
FREE_3_NEW = _blk(r"""
                      entity_id: input_boolean.ecco_free_power_schedule_armed

  # R9: capture the time Home Assistant started, once per start, so the two start paths that run after a
  # restart (the startup recovery and the watchdog) can tell a missed run from a start that fell while Home
  # Assistant was running. Written nowhere else; never derived from any entity's last_changed.
  - id: ecco_free_power_ha_start_capture
    alias: "ECCO - Capture Home Assistant start time (Free Power)"
    mode: single
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      # The clock must be trustworthy before it is captured: a host without an RTC can boot with a clock that is behind, and a capture
      # of that early time would pass the staleness check (last_updated is stamped by the same clock). Wait (bounded) until the dongle's
      # NTP is synced and Home Assistant's time agrees with the dongle's NTP time (published about once a minute, so 120 s is allowed).
      # If that never happens the helper is left alone: unknown or stale, and every guard fails closed.
      - wait_template: >-
          {% set n = states('sensor.ecco_clock_dongle_ntp_time') %}
          {{ is_state('binary_sensor.ecco_clock_dongle_ntp_synced', 'on')
             and (as_timestamp(now()) - as_timestamp(n, 0)) | abs <= 120 }}
        timeout: "00:10:00"
        continue_on_timeout: true
      - if:
          - condition: template
            value_template: "{{ wait.completed }}"
        then:
          - action: input_datetime.set_datetime
            target:
              entity_id: input_datetime.ecco_free_power_ha_start
            data:
              timestamp: "{{ as_timestamp(now()) | int }}"

  - id: ecco_free_power_schedule_startup_recovery
    alias: "ECCO - Recover scheduled Free Power after Home Assistant restart"
""")

FREE_4_OLD = _blk(r"""
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
""")
FREE_4_NEW = _blk(r"""
            target:
              entity_id: switch.ecco_clock_dongle_free_power_write_enable
      # R9: give the capture (it waits for a trustworthy clock) a bounded time before judging; unknown after that fails closed.
      - wait_template: >-
          {% set c = states('input_datetime.ecco_free_power_ha_start') %}
          {% set cs = as_timestamp(c, 0) %}
          {% set o = states.input_datetime.ecco_free_power_ha_start %}
          {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
          {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
             and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
        timeout: "00:03:00"
        continue_on_timeout: true
      - variables:
          fired_for: "{{ states('input_datetime.ecco_free_power_schedule_start') }}"
          start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_schedule_start'), 0) }}"
          duration_min: "{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}"
          power_w: "{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}"
          end_ts: "{{ start_ts + (duration_min * 60) }}"
          now_ts: "{{ as_timestamp(now()) }}"
          # R9: same definition as the fire automation's guard (the package test pins them identical).
          ha_start_ts: "{{ as_timestamp(states('input_datetime.ecco_free_power_ha_start'), 0) }}"
          ha_start_known: >-
            {% set c = states('input_datetime.ecco_free_power_ha_start') %}
            {% set cs = as_timestamp(c, 0) %}
            {% set o = states.input_datetime.ecco_free_power_ha_start %}
            {% set u = as_timestamp(o.last_updated, 0) if o is not none else 0 %}
            {{ o is not none and c not in ['unknown', 'unavailable', ''] and cs > 1000000000
               and cs <= as_timestamp(now()) and u > 0 and (u - cs) | abs <= 10 }}
          missed_run: "{{ not ha_start_known or (start_ts | float(0)) <= (ha_start_ts | float(0)) }}"
      - choose:
          # Not armed any more, or the on-time start is already running: nothing to recover.
""")

FREE_5_OLD = _blk(r"""
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
""")
FREE_5_NEW = _blk(r"""
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
          # R9: a start time between the Home Assistant start and this evaluation is not a missed run: the normal
          # triggers own it (the on-time start fired, or is still to fire); this recovery neither starts nor disarms it.
          - conditions:
              - condition: template
                value_template: "{{ not missed_run and now_ts < end_ts }}"
            sequence: []
          # R9: a start time before the Home Assistant start (or an unknown / stale capture: fail closed) with the
          # window still open is a missed run. It is NOT started: recorded, notified, and only it is disarmed.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
            sequence:
              - action: persistent_notification.create
                data:
                  notification_id: ecco_free_power_schedule
                  title: "ECCO: scheduled Free Power was missed"
                  message: >-
                    The {{ (start_ts | float(0)) | timestamp_custom('%H:%M') }} scheduled Free Power start
                    {{ 'fell before Home Assistant started.' if ha_start_known else
                    'was not started: the Home Assistant start time was unknown, so ECCO could not tell whether it fell before Home Assistant started (failed closed).' }}
                    It was NOT started and the schedule is disarmed. Arm a new schedule if you still want it.
              - if:
                  - condition: template
                    value_template: "{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}"
                then:
                  - action: input_boolean.turn_off
                    target:
                      entity_id: input_boolean.ecco_free_power_schedule_armed
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: >-
                        {{ 'MISSED - not started after a Home Assistant restart' if ha_start_known else
                        'MISSED - not started: the Home Assistant start time was unknown, so ECCO could not tell whether the start fell before it (failed closed)' }}
        default:
          - action: input_boolean.turn_off
""")

FREE_EDITS = (
    (FREE_0_OLD, FREE_0_NEW),
    (FREE_1_OLD, FREE_1_NEW),
    (FREE_2_OLD, FREE_2_NEW),
    (FREE_3_OLD, FREE_3_NEW),
    (FREE_4_OLD, FREE_4_NEW),
    (FREE_5_OLD, FREE_5_NEW),
)


def _mk(name, edits, label):
    def undo(text: str) -> str:
        return _revert(text, edits, label)
    undo.__name__ = "pre_r9_" + name
    undo.edits = edits   # the PEX contract: a reverter exposes its exact (before, after) pairs
    return undo


pre_r9_dump_package = _mk("dump_package", DUMP_EDITS, "Dump package")
pre_r9_free_package = _mk("free_package", FREE_EDITS, "Free Power package")
pre_r9_package_test = _mk("package_test", PKGTEST_EDITS, "Dump package suite")
pre_r9_shadow_test = _mk("shadow_test", SHADOW_EDITS, "shadow check suite")


def add_r9_dump_package(text: str) -> str:
    return _apply(text, DUMP_EDITS, "Dump package")


def add_r9_free_package(text: str) -> str:
    return _apply(text, FREE_EDITS, "Free Power package")


def add_r9_package_test(text: str) -> str:
    return _apply(text, PKGTEST_EDITS, "Dump package suite")


def add_r9_shadow_test(text: str) -> str:
    return _apply(text, SHADOW_EDITS, "shadow check suite")


FROZEN_REVERTERS = {
    DUMP_REL: pre_r9_dump_package,
    FREE_REL: pre_r9_free_package,
    PKGTEST_REL: pre_r9_package_test,
    SHADOW_REL: pre_r9_shadow_test,
}
# r9 edits no chain-pinned file (the packages are already deployed: no manifest stanza).
PINNED_REVERTERS: dict = {}
