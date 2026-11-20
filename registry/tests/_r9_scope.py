"""r9 (no automatic start of a missed scheduled run after a Home Assistant restart) change scope: exactly what r9 changes in the two
frozen schedule packages (and the two frozen suites whose pins they move) and, as comments only, in the chain-pinned deployment manifest,
as exact (before, after) pairs, and their exact inverse.

Same technique as the earlier post-export scope modules (_fps1_scope, _dgs1_scope): every verbatim edit is held HERE as the single source of
truth, round-trip-checked, and each reverter raises unless each of its edits is present exactly once. The post-export chain entry `r9`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, appended after isp1; registry/tests/_pex.py) carries four frozen reverters (the two
packages and the two suites) and one chain-pinned reverter (the deployment manifest).

WHAT r9 IS. The owner's requirement of 12 Nov 2026 (docs/dev/grid-loss-interlock-spec.md, section 5 R9 and 6.4): a missed scheduled Charge Battery
(ecco_free_power_schedule.yaml) or Export to Grid (ecco_dump_to_grid_schedule.yaml) session must not start automatically after a Home Assistant
restart, on either start path (the startup recovery and the schedule watchdog); a future occurrence is kept; the on-time start is unchanged.
Per package: one helper (input_datetime.<pkg>_ha_start, written only by the new capture automation on the `homeassistant` start event), that
capture automation, a guard (`ha_start_known`, `missed_run`) in the fire automation and in the startup recovery, a new watchdog branch that
records, notifies and disarms a missed run, the `not missed_run` condition on the watchdog's start, and in the recovery the start branch
replaced by the same record, notification and disarm (and a branch that leaves a start between the Home Assistant start and the recovery's
evaluation to the normal triggers). Status text `MISSED - not started after a Home Assistant restart` (the status sensor already maps MISSED to
FAILED). It makes starts only more conservative: no new service other than input_datetime.set_datetime on its own helper, no register, no
dongle entity written that was not written before. ZERO firmware, registry data, dashboard or card byte. Offline only; not installed.

THE MANIFEST NOTE (owner decision of 18 Nov 2026: R9 goes first, as its own pull request). The two packages are already listed in
deployment/ha-manifest.yaml (restart_required: true), but nothing there said that R9 needs a FULL Home Assistant restart. The manifest gains
a short YAML comment block above each of the two stanzas (MANIFEST_EDITS): R9 needs a full restart, not a package or YAML reload; after a
reload the captured start is unknown and the watchdog will not rescue a lost start; a restart after the planned start time never starts that
run (it is recorded as missed). Comments only: no key, value, order or indentation of any stanza moves, and no number, entity id, address or
site value is spelled. The manifest is chain-pinned (_scope_chain.PINNED), so the edit is declared here as exact pairs with an exact reverter
(PINNED_REVERTERS) and its result hash is the r9 checkpoint of the manifest in _scope_chain.py; the r9 fingerprint is re-sealed over it.

OWNER DECISION OF 20 NOV 2026 (item 4, before r9 is merged): three more declared edits to the two packages, kept as further exact pairs (the last five
of each tuple), so that r9 stays ONE entry and its reverters still land on the isp1 state. (1) The Charge Battery (Free Power) package's result
integrity: the step after the retry loop and the startup recovery no longer write STARTED OK over a result this schedule did not verify, and the
end-of-run alert says when Free Power is active now (the Export to Grid package's own fix is carried by the stage 3 pull request, not here).
(2) Both packages: arming refuses a start time that is a skipped, a repeated or an unreadable local time (proposal P-A of the clock-change
examination of 19 Nov 2026), before the 'must be in the future' check. (3) The Export to Grid arm-time TOU overlap walk takes each minute of the run
from its real instant (proposal P-B). The firmware is unchanged. The pairs are anchored on text that neither the r9 edits above nor the stage 3
edits touch.

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

# ---- Export to Grid (Dump to Grid): clock changes, P-A (the start label) and P-B (the TOU overlap walk on real instants) ----------
# Owner decision of 20 Nov 2026. The package's own result-integrity defect (the old fallback and recovery) is NOT touched here: the stage 3 pull
# request carries that fix. These pairs are anchored on text the r9 edits above do not touch (and the stage 3 edits do not touch either).
DUMP_6_OLD = _blk(r"""
# NOT LIVE-PROVEN - see docs/DUMP_TO_GRID_V1.md.
#
# DGS1 (2026-10-12 review, after the 11 Oct scheduled Free Power incident, FPS1): the Dump to Grid
""")
DUMP_6_NEW = _blk(r"""
# NOT LIVE-PROVEN - see docs/DUMP_TO_GRID_V1.md.
#
# CLOCK CHANGES (owner decision of 20 Nov 2026; offline, not installed; clock-change examination of 19 Nov 2026, proposals P-A and P-B). Arming
# REFUSES a start time that is a skipped local time (the hour that does not exist when the UK clocks go forward), a repeated one (the hour that
# happens twice when they go back) or one that cannot be read, with "REJECTED - the start time is a skipped, repeated or unreadable local time
# (clock change); pick another time". The check comes BEFORE 'must be in the future', so arming in the second 01:xx hour for a 01:xx start gets this
# text and not a misleading 'must be in the future'. It reads the helper's text, converts it to an instant and back, and refuses when the text does
# not survive the round trip (a skipped time), when the same text one hour away reads the same (a repeated time) or when a conversion fails (fail
# closed). The deadlines in this package were already epoch arithmetic and are exact across a clock change. The check runs when the schedule is
# armed (the card locks the start while it is armed). How Home Assistant's template functions read a naive local time (the first occurrence of a
# repeated time, the offset before the change for a skipped one) and which zone they use is RECALLED, not verified: a supervised read-only template
# check on the real Home Assistant (proposal P-F) is still open. The check refuses a repeated time on either reading.
# The arm-time TOU slot check walks the run window on the REAL INSTANTS: for each minute of the run it takes the local minute of the day of (start +
# that many minutes) through the local timestamp conversion, so a window that crosses a clock change checks the slots it really covers. It used to
# add minutes to the start's wall-clock minute: on the day the clocks go forward it did not see a charge slot that begins after the skipped hour (00:30
# for 120 minutes covers 00:30-01:00 and then 02:00-03:30 local, not 00:30-02:30), and on the day they go back it refused a clear window (00:45 for
# 240 minutes ends at 03:45 local). A minute whose local time cannot be read refuses the arm. The window is bounded by the duration helper (at most
# 240 minutes), and an unreadable slot table still defers to the firmware, as before. The firmware's own START gate walks the window the old way (read
# from its text, not run) and is NOT changed here (a firmware change is a separate flash), so on the day the clocks go forward the arm check is the
# only one that sees a charge slot after the skipped hour.
#
# DGS1 (2026-10-12 review, after the 11 Oct scheduled Free Power incident, FPS1): the Dump to Grid
""")

DUMP_7_OLD = _blk(r"""
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
""")
DUMP_7_NEW = _blk(r"""
          # Clock changes (owner decision of 20 Nov 2026, proposal P-A): a start time that is a skipped, a repeated or an unreadable local time is
          # refused, BEFORE 'must be in the future' (which would be misleading for a 01:xx start armed in the second 01:xx hour). The label is
          # converted to an instant and back: a skipped label does not survive the round trip, a repeated one reads the same one hour away, and
          # every conversion carries a default so that a conversion that fails refuses instead of raising (fail closed).
          - conditions:
              - condition: template
                value_template: >-
                  {%- set s = states('input_datetime.ecco_dump_to_grid_schedule_start') -%}
                  {%- set t = as_timestamp(s, 0) -%}
                  {%- set f = '%Y-%m-%d %H:%M:%S' -%}
                  {{ t <= 0
                     or (t | timestamp_custom(f, true, 'unreadable')) != s
                     or ((t + 3600) | timestamp_custom(f, true, 'unreadable')) == s
                     or ((t - 3600) | timestamp_custom(f, true, 'unreadable')) == s }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result
                data:
                  value: "REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time"
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
""")

DUMP_8_OLD = _blk(r"""
          # anyway. Same slot model as the dashboard's "Current Plan": slot i
          # runs from its time to slot i+1's, slot 6 wrapping to slot 1. Only
          # ever refuses; if the slot sensors are unavailable it defers to the
          # firmware's own check.
          - conditions:
              - condition: template
                value_template: >-
                  {% set ns = namespace(ok=true, starts=[], charges=[], hit=0) %}
""")
DUMP_8_NEW = _blk(r"""
          # anyway. Same slot model as the dashboard's "Current Plan": slot i
          # runs from its time to slot i+1's, slot 6 wrapping to slot 1. Only
          # ever refuses; if the slot sensors are unavailable it defers to the
          # firmware's own check.
          # Clock changes (owner decision of 20 Nov 2026, proposal P-B): the run window is walked on the REAL INSTANTS, not as continuous wall-clock
          # minutes. For each minute k of the run the local minute of the day is taken from the instant (start + k minutes) through the local timestamp
          # conversion, so a window that crosses a clock change checks the slots it really covers (00:30 for 120 minutes on the day the clocks go forward
          # covers 00:30-01:00 and then 02:00-03:30 local; 00:45 for 240 minutes on the day they go back ends at 03:45 local). A minute whose local time
          # cannot be read refuses the arm (fail closed); an unreadable slot table still defers to the firmware. The run is bounded by the duration helper
          # (at most 240 minutes). The firmware's own START gate is not changed by this (a firmware change is a separate flash).
          - conditions:
              - condition: template
                value_template: >-
                  {% set ns = namespace(ok=true, starts=[], charges=[], hit=0, bad=false) %}
""")

DUMP_9_OLD = _blk(r"""
                  {% if ns.ok and (start_ts | float(0)) > 0 %}
                    {% set st = (start_ts | float(0)) | timestamp_local %}
                    {% set m0 = (st[11:13] | int) * 60 + (st[14:16] | int) %}
                    {% set dur = states('input_number.ecco_dump_to_grid_schedule_duration') | int(0) %}
                    {% for k in range(0, dur + 1) %}
                      {% set m = (m0 + k) % 1440 %}
""")
DUMP_9_NEW = _blk(r"""
                  {% if ns.ok and (start_ts | float(0)) > 0 %}
                    {% set dur = states('input_number.ecco_dump_to_grid_schedule_duration') | int(0) %}
                    {% for k in range(0, dur + 1) %}
                      {% set sk = ((start_ts | float(0)) + k * 60) | timestamp_local %}
                      {% set hh = sk[11:13] | int(-1) %}
                      {% set mi = sk[14:16] | int(-1) %}
                      {% if hh < 0 or hh > 23 or mi < 0 or mi > 59 %}
                        {% set ns.bad = true %}
                      {% endif %}
                      {% set m = hh * 60 + mi %}
""")

DUMP_10_OLD = _blk(r"""
                  {{ ns.hit > 0 }}
            sequence:
""")
DUMP_10_NEW = _blk(r"""
                  {{ ns.hit > 0 or ns.bad }}
            sequence:
""")


DUMP_EDITS = (
    (DUMP_0_OLD, DUMP_0_NEW),
    (DUMP_1_OLD, DUMP_1_NEW),
    (DUMP_2_OLD, DUMP_2_NEW),
    (DUMP_3_OLD, DUMP_3_NEW),
    (DUMP_4_OLD, DUMP_4_NEW),
    (DUMP_5_OLD, DUMP_5_NEW),
    # owner decision of 20 Nov 2026: clock changes (P-A, P-B)
    (DUMP_6_OLD, DUMP_6_NEW),
    (DUMP_7_OLD, DUMP_7_NEW),
    (DUMP_8_OLD, DUMP_8_NEW),
    (DUMP_9_OLD, DUMP_9_NEW),
    (DUMP_10_OLD, DUMP_10_NEW),
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

# ---- Charge Battery (Free Power): clock changes (P-A) and result integrity (owner decision of 20 Nov 2026) -------------------------
# These pairs are anchored on text the r9 edits above do not touch, so they apply to (and revert from) the r9 text exactly.
FREE_6_OLD = _blk(r"""
# The ESPHome firmware remains responsible for snapshot, verified writes, timer and exact restore.
#
# FPS1 (2026-10-11 incident): the firmware start gate refuses a press at once while any Modbus
""")
FREE_6_NEW = _blk(r"""
# The ESPHome firmware remains responsible for snapshot, verified writes, timer and exact restore.
#
# CLOCK CHANGES (owner decision of 20 Nov 2026; offline, not installed; clock-change examination of 19 Nov 2026, proposal P-A): arming REFUSES a
# start time that is a skipped local time (the hour that does not exist when the UK clocks go forward), a repeated one (the hour that happens twice
# when they go back) or one that cannot be read, with "REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick
# another time". The check comes BEFORE 'must be in the future', so arming in the second 01:xx hour for a 01:xx start gets this text and not a
# misleading 'must be in the future'. It reads the helper's text, converts it to an instant and back, and refuses when the text does not survive the
# round trip (a skipped time), when the same text one hour away reads the same (a repeated time) or when a conversion fails (fail closed). The
# deadlines in this package were already epoch arithmetic and are exact across a clock change. The check runs when the schedule is armed (the card
# locks the start while it is armed). How Home Assistant's template functions read a naive local time (the first occurrence of a repeated time, the
# offset before the change for a skipped one) and which zone they use is RECALLED, not verified: a supervised read-only template check on the real
# Home Assistant (proposal P-F) is still open. The check refuses a repeated time on either reading.
#
# RESULT INTEGRITY (owner decision of 20 Nov 2026): the steps after the retry loop never turn a result into a success. STARTED OK is written only
# inside the loop, by this run's own verified start (its press, a start transaction that began, then Free Power active). A FAILED, BLOCKED or
# CANCELLED result stays exactly as written even when Free Power is found active (it was started some other way, for example from the dongle's own
# Start button or by hand); a result that is still STARTING when Free Power is found active becomes CANCELLED if the owner cancelled the schedule,
# else "FAILED TO START ... Free Power is active now, but this run did not confirm that it started it", and the end-of-run alert then says so. The
# startup recovery after a Home Assistant restart writes "STARTED OK - running" only over a result that already starts with STARTED; a FAILED,
# BLOCKED or CANCELLED result stays as written; any other result becomes an UNCONFIRMED text. Neither step presses or starts anything, and nothing
# changes while Free Power is not active. A FAILED text can be a false negative (the dongle started late after a start transaction that began); the
# alert flags it.
#
# FPS1 (2026-10-11 incident): the firmware start gate refuses a press at once while any Modbus
""")

FREE_7_OLD = _blk(r"""
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
""")
FREE_7_NEW = _blk(r"""
          # Clock changes (owner decision of 20 Nov 2026, proposal P-A): a start time that is a skipped, a repeated or an unreadable local time is
          # refused, BEFORE 'must be in the future' (which would be misleading for a 01:xx start armed in the second 01:xx hour). The label is
          # converted to an instant and back: a skipped label does not survive the round trip, a repeated one reads the same one hour away, and
          # every conversion carries a default so that a conversion that fails refuses instead of raising (fail closed).
          - conditions:
              - condition: template
                value_template: >-
                  {%- set s = states('input_datetime.ecco_free_power_schedule_start') -%}
                  {%- set t = as_timestamp(s, 0) -%}
                  {%- set f = '%Y-%m-%d %H:%M:%S' -%}
                  {{ t <= 0
                     or (t | timestamp_custom(f, true, 'unreadable')) != s
                     or ((t + 3600) | timestamp_custom(f, true, 'unreadable')) == s
                     or ((t - 3600) | timestamp_custom(f, true, 'unreadable')) == s }}
            sequence:
              - action: input_boolean.turn_off
                target:
                  entity_id: input_boolean.ecco_free_power_schedule_armed
              - action: input_text.set_value
                target:
                  entity_id: input_text.ecco_free_power_schedule_last_result
                data:
                  value: "REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time"
          - conditions:
              - condition: template
                value_template: "{{ start_ts <= as_timestamp(now()) }}"
            sequence:
""")

FREE_8_OLD = _blk(r"""
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
""")
FREE_8_NEW = _blk(r"""
          # Owner decision of 20 Nov 2026 (Free Power result integrity): the steps after the loop never turn a result into a success. STARTED OK is
          # written only inside the loop, by this run's own verified start (its press, a start transaction that began, then Free Power active). A
          # FAILED, CANCELLED or BLOCKED result stays exactly as written, whatever Free Power is doing (started some other way: the dongle's own Start
          # button, or by hand); the alert below then says so. A result that is still STARTING when Free Power is found active was not confirmed by this
          # run: it becomes CANCELLED if the owner cancelled the schedule, else a FAILED TO START text that says Free Power is active now and that this
          # run did not confirm that it started it. A result this script did not write (ARMED, REJECTED, MISSED) is left alone.
          - if:
              - condition: template
                value_template: >-
                  {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                  {{ is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') and r.startswith('STARTING') }}
            then:
              - choose:
                  # Cancelled by the owner (tested as the loop top and the step above test it): the run reads CANCELLED, not failed.
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
                default:
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: >-
                        FAILED TO START - retries ended at {{ now().strftime('%H:%M') }}:
                        {{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }};
                        Free Power is active now, but this run did not confirm that it started it
""")

FREE_9_OLD = _blk(r"""
              message: >-
                {{ states('input_text.ecco_free_power_schedule_last_result') }}

                Authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}.
""")
FREE_9_NEW = _blk(r"""
              # Owner decision of 20 Nov 2026: while Free Power is active at this moment the notice says so. For a BLOCKED result (nothing was pressed) it
              # says this run did not start it; for any other result (a FAILED one) it says only that this run did not CONFIRM that it started it,
              # because an unconfirmed outcome can be a late start of this run's own press. With Free Power not active the message is unchanged.
              message: >-
                {{ states('input_text.ecco_free_power_schedule_last_result') }}
                {%- if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') %}

                {% if states('input_text.ecco_free_power_schedule_last_result').startswith('BLOCKED') -%}
                Free Power is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand).
                Check it before assuming this schedule started it.
                {%- else -%}
                Free Power is active now, but this run did not confirm that it started it (it may have been started from the dongle's own Start button or by hand, or, if a start transaction had begun, late by this run's own press).
                Check it before assuming this schedule started it.
                {%- endif %}
                {%- endif %}

                Authorised window ends {{ (window_end | float(0)) | timestamp_custom('%H:%M') }}.
""")

FREE_10_OLD = _blk(r"""
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
""")
FREE_10_NEW = _blk(r"""
          # Restarted while the session runs and Free Power is active. Owner decision of 20 Nov 2026: the recovery never turns a result into a success that
          # this schedule did not verify. It cannot tell who started Free Power (the dongle's own Start button, a manual start, or this schedule's own
          # press), so it trusts only the record. A last result that already starts with STARTED (this schedule's own verified start, recorded before
          # the restart) keeps the old text. A FAILED, BLOCKED or CANCELLED result is final: it is not written again. Any other result (STARTING, ARMED,
          # empty, REJECTED, MISSED, foreign text) gets a text that says Free Power is active after a restart and that this schedule did not confirm that
          # it started it. Nothing is pressed or started here. The schedule is disarmed in every case, as before, so the watchdog cannot turn a refusal
          # into a MISSED record.
          - conditions:
              - condition: template
                value_template: "{{ now_ts < end_ts }}"
              - condition: state
                entity_id: binary_sensor.ecco_clock_dongle_free_power_active
                state: "on"
            sequence:
              - choose:
                  - conditions:
                      - condition: template
                        value_template: "{{ states('input_text.ecco_free_power_schedule_last_result').startswith('STARTED') }}"
                    sequence:
                      - action: input_text.set_value
                        target:
                          entity_id: input_text.ecco_free_power_schedule_last_result
                        data:
                          value: "STARTED OK - running (Home Assistant restarted during the session)"
                  - conditions:
                      - condition: template
                        value_template: >-
                          {% set r = states('input_text.ecco_free_power_schedule_last_result') %}
                          {{ r.startswith('FAILED') or r.startswith('BLOCKED') or r.startswith('CANCELLED') }}
                    sequence: []
                default:
                  - action: input_text.set_value
                    target:
                      entity_id: input_text.ecco_free_power_schedule_last_result
                    data:
                      value: "UNCONFIRMED - Free Power is active after a Home Assistant restart, but this schedule did not confirm that it started it (it may have been started some other way). Check it in Energy Actions before assuming this schedule started it."
""")


FREE_EDITS = (
    (FREE_0_OLD, FREE_0_NEW),
    (FREE_1_OLD, FREE_1_NEW),
    (FREE_2_OLD, FREE_2_NEW),
    (FREE_3_OLD, FREE_3_NEW),
    (FREE_4_OLD, FREE_4_NEW),
    (FREE_5_OLD, FREE_5_NEW),
    # owner decision of 20 Nov 2026: clock changes (P-A) and result integrity
    (FREE_6_OLD, FREE_6_NEW),
    (FREE_7_OLD, FREE_7_NEW),
    (FREE_8_OLD, FREE_8_NEW),
    (FREE_9_OLD, FREE_9_NEW),
    (FREE_10_OLD, FREE_10_NEW),
)


# ---- (chain-pinned edit) deployment/ha-manifest.yaml: comments only -------------------------------------------------------------
MANIFEST_REL = "deployment/ha-manifest.yaml"
MANIFEST_0_OLD = _blk(r"""
    restart_required: true
  - source: home-assistant/packages/ecco_free_power_schedule.yaml
""")
MANIFEST_0_NEW = _blk(r"""
    restart_required: true
  # R9 (r9; scheduled Charge Battery, not live-proven): a missed scheduled run is never started after a Home Assistant restart.
  # Install this package with a FULL Home Assistant restart, not a package or YAML reload. The captured Home Assistant start time
  # is written only on the start event, so after a reload it is unknown and every guard fails closed: the schedule watchdog then
  # will NOT rescue a lost start. A restart that happens after the planned start time never starts that run; it is recorded as
  # missed (MISSED - not started after a Home Assistant restart), notified and disarmed.
  - source: home-assistant/packages/ecco_free_power_schedule.yaml
""")
MANIFEST_1_OLD = _blk(r"""
  # ecco_free_power_schedule.yaml's helpers for the schedule-overlap check.
  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml
""")
MANIFEST_1_NEW = _blk(r"""
  # ecco_free_power_schedule.yaml's helpers for the schedule-overlap check.
  # R9 (r9; scheduled Export to Grid, not live-proven): a missed scheduled run is never started after a Home Assistant restart.
  # Install this package with a FULL Home Assistant restart, not a package or YAML reload. The captured Home Assistant start time
  # is written only on the start event, so after a reload it is unknown and every guard fails closed: the schedule watchdog then
  # will NOT rescue a lost start. A restart that happens after the planned start time never starts that run; it is recorded as
  # missed (MISSED - not started after a Home Assistant restart), notified and disarmed.
  - source: home-assistant/packages/ecco_dump_to_grid_schedule.yaml
""")

MANIFEST_EDITS = (
    (MANIFEST_0_OLD, MANIFEST_0_NEW),
    (MANIFEST_1_OLD, MANIFEST_1_NEW),
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
pre_r9_manifest = _mk("manifest", MANIFEST_EDITS, "deployment/ha-manifest.yaml")   # the chain reverter of entry r9 for the pinned manifest


def add_r9_dump_package(text: str) -> str:
    return _apply(text, DUMP_EDITS, "Dump package")


def add_r9_free_package(text: str) -> str:
    return _apply(text, FREE_EDITS, "Free Power package")


def add_r9_package_test(text: str) -> str:
    return _apply(text, PKGTEST_EDITS, "Dump package suite")


def add_r9_shadow_test(text: str) -> str:
    return _apply(text, SHADOW_EDITS, "shadow check suite")


def add_r9_manifest(text: str) -> str:
    """Applies r9's deployment/ha-manifest.yaml comment edits to the text as of isp1 (the round trip)."""
    return _apply(text, MANIFEST_EDITS, "deployment/ha-manifest.yaml")


FROZEN_REVERTERS = {
    DUMP_REL: pre_r9_dump_package,
    FREE_REL: pre_r9_free_package,
    PKGTEST_REL: pre_r9_package_test,
    SHADOW_REL: pre_r9_shadow_test,
}
# The chain-pinned file r9 edits (comments only: the FULL-restart note on the two package stanzas), with its reverter (the chain entry's reverts).
PINNED_REVERTERS = {
    MANIFEST_REL: pre_r9_manifest,
}
