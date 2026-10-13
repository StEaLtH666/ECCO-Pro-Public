"""fcp1 (full-capability Dump-to-Grid foundation: inverter capability profile + persisted operating limits) change scope: exactly
what fcp1 changes in firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _dtgp1_scope.py: the verbatim edits are held HERE as the single source of truth, as exact (before, after) pairs,
and the reverter raises unless every edit is present exactly once. The post-export chain entry `fcp1` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES, appended last after fsw1; registry/tests/_pex.py) carries `pre_fcp1_firmware`: the current firmware text with
exactly these edits removed, which reproduces the dtgp1 firmware byte for byte (BASE_FW_SHA = the chain's dtgp1 checkpoint; every
entry between dtgp1 and fcp1 edits no firmware). Older suites read the firmware as of their own entry through the chain.

WHAT fcp1 IS (owner decision 2026-10-13: ONE eventual firmware flash supporting the installed inverter's full validated capability;
power-level testing through Home Assistant settings, never by reflashing).

  Four quantities, each enforced independently on the dongle:
    inverter capability   ecco_dump_capability_w (W AC): a PROFILE value - the highest TOU battery-discharge power the Dump
                          controller may ever be configured to command on this inverter (<= the profile's TOU register bound,
                          ecco_inverter_tou_power_ceiling_w). No global maximum: the 8000 W of the reference profile is that
                          profile's value. Other inverters: registry/inverter_profiles.yaml, applied as build-time overrides.
    Dump power ceiling    the persisted run-time setting dump_op_ceiling_w (W AC, 500 .. capability, 100 W steps, factory default
                          ecco_dump_controller_max_ceiling_w = 3000): the highest TOU power (256-261) the controller may command
                          in a lease. LATCHED per lease at START (dump_lease_ceiling_w); a later raise never reaches a running
                          lease; a reduction lowers it at once (the controller steps down through its own verified write).
    battery discharge     measured (W DC, register 190); guarded by the existing runaway guards relative to the command.
    net grid export       the persisted run-time setting dump_max_export_w (W AC at the grid CT, register 172; 0 = NOT CONFIGURED):
                          START refuses unless it is configured and the requested export target is within it; an in-lease guard
                          ends the lease once 3 of the last 4 fresh CT samples exceed it by max(100 W, 3 %).

  Persistence and validation: the two settings, the capability they were stored for and an integrity value are restore_value globals
  (NVS); on_boot validates them (range, step, capability match, integrity) and otherwise leaves them INVALID - every START refused
  until Home Assistant sets them again. A raise (or leaving INVALID) needs the new "Dump Power Limits Write Enable" arm (one change,
  60 s) and Dump idle; a reduction is always accepted. Nothing is ever replaced by a larger or unlimited value.

  ZERO new Modbus operation and ZERO new inverter write domain (register 245 untouched; the write surface 22-24, 230, 232, 244,
  250-261, 268-279 is unchanged); no durable record, tag or header changes (the durable NVS records keep their schemas; the new
  settings are separate ESPHome preference keys that older firmware ignores).

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# Public main the change is based on (FSW1 merged).
BASE_COMMIT = "2afe6c3ffdec51ec808cb03a84a8471e503677d5"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF) of the firmware YAML at BASE_COMMIT (= the chain's dtgp1 checkpoint): what pre_fcp1_firmware() must reproduce.
BASE_FW_SHA = "9e49b229b31568e059da353ef30fd7a3b8d8cf9af1068c3edb19b7cb0d044c55"

ADDED_FILES = frozenset({
    "docs/dev/inverter-capability-profiles.md",
    "registry/inverter_profiles.yaml",
    "registry/tests/_fcp1_scope.py",
    "registry/tests/test_dump_capability_limits.py",
})

# The substitutions fcp1 adds (key -> EXACT value).
SUBSTITUTIONS = {
    'ecco_inverter_profile_id': 'deye_1ph_lv_8kw',
    'ecco_inverter_profile_name': '8 kW single-phase low-voltage Deye-family hybrid (reference installation H-001)',
    'ecco_dump_capability_w': '8000',
    'ecco_dump_limits_arm_window_ms': '60000',
    'ecco_dump_export_margin_min_w': '100',
    'ecco_dump_export_guard_samples': '3',
    'ecco_dump_limits_default_check': '71345',
}

NEW_GLOBAL_IDS = ("dump_op_ceiling_w", "dump_max_export_w", "dump_limits_cap_w", "dump_limits_check", "dump_limits_valid",
                  "dump_lease_ceiling_w", "dump_limits_arm_ms", "dump_export_window", "dump_export_last_w")
PERSISTED_GLOBAL_IDS = ("dump_op_ceiling_w", "dump_max_export_w", "dump_limits_cap_w", "dump_limits_check")


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Edit:
    name: str
    before: str
    after: str


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"fcp1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


# ---- profile
PROFILE_OLD = _blk(r"""
# Inverter hardware profile.
# This is the verified TOU power ceiling for the inverter this firmware is built for.
# Do not raise this value without verifying the target inverter model/profile.
substitutions:
  ecco_inverter_tou_power_ceiling_w: "8000"
""")
PROFILE_NEW = _blk(r"""
# Inverter hardware profile.
# This is the verified TOU power ceiling for the inverter this firmware is built for.
# Do not raise this value without verifying the target inverter model/profile.
#
# fcp1 (2026-10-13): the INVERTER CAPABILITY PROFILE. The four values below
# describe the inverter this build is for and nothing else: they are a
# profile's values, never a global ECCO maximum. Another inverter is
# supported by building with that inverter's profile values (see
# registry/inverter_profiles.yaml and docs/dev/inverter-capability-profiles.md:
# `esphome -s <key> <value> ...` for each profile key); on_boot's compile-time
# checks refuse an inconsistent profile. The OPERATING limits (the Dump to
# Grid power ceiling and the maximum net grid export) are NOT profile values:
# they are run-time settings persisted on the dongle - see dump_op_ceiling_w.
substitutions:
  # fcp1: profile identity, published by the "Inverter Capability Profile"
  # text sensor so Home Assistant and a pre-flight can see what a build is for.
  ecco_inverter_profile_id: "deye_1ph_lv_8kw"
  ecco_inverter_profile_name: "8 kW single-phase low-voltage Deye-family hybrid (reference installation H-001)"
  # AC power bound of the inverter's TOU power registers (256-261), W.
  ecco_inverter_tou_power_ceiling_w: "8000"
  # fcp1: the profile's validated Dump-to-Grid CAPABILITY, W AC: the highest
  # TOU battery-discharge power the Dump controller may ever be configured to
  # command on this inverter. It bounds the run-time "Dump to Grid Power
  # Ceiling" setting; it is not a default and not a recommendation. Must be
  # <= ecco_inverter_tou_power_ceiling_w (checked at compile time).
  ecco_dump_capability_w: "8000"
""")

# ---- default_ceiling_doc
DEFAULT_CEILING_DOC_OLD = _blk(r"""
  # backstop follows the command above ecco_dump_runaway_backstop_floor_w.
  ecco_dump_controller_max_ceiling_w: "3000"
""")
DEFAULT_CEILING_DOC_NEW = _blk(r"""
  # backstop follows the command above ecco_dump_runaway_backstop_floor_w.
  # fcp1 (2026-10-13): this is now the FACTORY DEFAULT of the run-time
  # "Dump to Grid Power Ceiling" setting (dump_op_ceiling_w), the value a
  # dongle starts with when nothing has been stored yet. The ceiling the
  # controller actually uses is that persisted run-time setting, latched per
  # lease (dump_lease_ceiling_w) and bounded by the profile capability
  # ecco_dump_capability_w. It must not exceed the capability (compile-time
  # check). 3000 W remains the only hardware-proven value.
  ecco_dump_controller_max_ceiling_w: "3000"
  # fcp1: how long, in ms, the "Dump Power Limits Write Enable" arm stays
  # valid for ONE raise of a Dump operating limit (it turns itself off after
  # an accepted change or after this window).
  ecco_dump_limits_arm_window_ms: "60000"
  # fcp1: the in-lease net grid export guard. Measured export (register 172,
  # negative = export) above the configured maximum grid export plus a margin
  # of max(this many W, 3 % of the limit) in this many of the last four fresh
  # CT samples ends the lease (common restore path).
  ecco_dump_export_margin_min_w: "100"
  ecco_dump_export_guard_samples: "3"
  # fcp1: dump_limits_check's factory value, i.e. the integrity value of the
  # factory limits (ceiling = ecco_dump_controller_max_ceiling_w, export 0,
  # capability ecco_dump_capability_w): ceiling + 3*export + 7*capability +
  # 12345. Compile-time checked against those values in on_boot.
  ecco_dump_limits_default_check: "71345"
""")

# ---- compile_checks
COMPILE_CHECKS_OLD = _blk(r"""
          static_assert(${ecco_dump_controller_max_ceiling_w} <= 8000,
                        "Dump ceiling: 8000 W is the architectural maximum");
""")
COMPILE_CHECKS_NEW = _blk(r"""
          // fcp1 (2026-10-13): no global maximum. The default operating ceiling
          // must not exceed this profile's validated Dump capability, and the
          // profile must be self-consistent; a 16-bit TOU power register is the
          // only representation bound.
          static_assert(${ecco_dump_controller_max_ceiling_w} <= ${ecco_dump_capability_w},
                        "Dump ceiling: the default operating ceiling must not exceed the profile capability ecco_dump_capability_w");
          static_assert(${ecco_dump_capability_w} == (long) ${ecco_dump_capability_w}.0f &&
                            ${ecco_dump_capability_w} % ${ecco_dump_controller_round_w} == 0 &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_capability_w},
                        "Dump capability: a plain decimal integer, a multiple of the rounding step, above the controller floor");
          static_assert(${ecco_dump_capability_w} <= ${ecco_inverter_tou_power_ceiling_w},
                        "Dump capability: must not exceed the profile's TOU power register bound");
          static_assert(${ecco_inverter_tou_power_ceiling_w} <= 65535,
                        "Profile: the TOU power registers are 16-bit");
          static_assert(${ecco_dump_limits_default_check} ==
                            ${ecco_dump_controller_max_ceiling_w} + 3 * 0 + 7 * ${ecco_dump_capability_w} + 12345,
                        "fcp1: ecco_dump_limits_default_check must be the integrity value of the factory limits");
""")

# ---- boot_limits
BOOT_LIMITS_OLD = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
""")
BOOT_LIMITS_NEW = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
      # fcp1 (2026-10-13): validate the PERSISTED Dump operating limits before
      # anything can use them. A value that is out of range, was stored for a
      # different capability profile, or fails the integrity check (an
      # incomplete or corrupt save) leaves the limits INVALID: every Dump START
      # is refused until Home Assistant sets them again (armed, idle). Nothing
      # is ever silently replaced by a larger or unlimited value.
      - lambda: |-
          int op = id(dump_op_ceiling_w);
          int ex = id(dump_max_export_w);
          uint32_t want = (uint32_t) op + 3u * (uint32_t) ex + 7u * (uint32_t) id(dump_limits_cap_w) + 12345u;
          int why = 0;
          if (id(dump_limits_cap_w) != ${ecco_dump_capability_w}) why = 1;
          else if (id(dump_limits_check) != want) why = 2;
          else if (op < ${ecco_dump_controller_min_ceiling_w} || op > ${ecco_dump_capability_w} || op % ${ecco_dump_controller_round_w} != 0) why = 3;
          else if (ex < 0 || ex > ${ecco_dump_capability_w} || ex % 10 != 0) why = 4;
          id(dump_limits_valid) = (why == 0);
          id(dump_lease_ceiling_w) = ${ecco_dump_controller_min_ceiling_w};
          char msg[160];
          if (why == 0 && ex == 0) {
            snprintf(msg, sizeof(msg), "VALID - power ceiling %d W; maximum grid export NOT CONFIGURED (Dump START refused until set)", op);
          } else if (why == 0) {
            snprintf(msg, sizeof(msg), "VALID - power ceiling %d W; maximum grid export %d W", op, ex);
          } else {
            const char* r = why == 1 ? "stored for a different inverter capability profile" :
                            why == 2 ? "integrity check failed (incomplete or corrupt save)" :
                            why == 3 ? "stored power ceiling out of range" : "stored maximum grid export out of range";
            snprintf(msg, sizeof(msg), "INVALID - %s; Dump START refused until both limits are set again (arm, idle)", r);
          }
          id(dump_limits_status).publish_state(msg);
""")

# ---- globals
GLOBALS_OLD = _blk(r"""
  - id: dump_target_power
    type: uint16_t
    restore_value: no
    initial_value: '0'
""")
GLOBALS_NEW = _blk(r"""
  # fcp1 (2026-10-13): the Dump operating limits, PERSISTED on the dongle
  # (ESPHome preferences / NVS) so they are enforced without Home Assistant.
  # dump_op_ceiling_w: the Dump to Grid Power Ceiling, W AC - the highest TOU
  # battery-discharge power the controller may command (500 W .. the profile
  # capability, 100 W steps; factory default ecco_dump_controller_max_ceiling_w).
  # dump_max_export_w: the maximum NET grid export, W AC at the grid CT
  # (register 172) - 0 means NOT CONFIGURED and refuses every Dump START.
  # dump_limits_cap_w: the profile capability the limits were stored for.
  # dump_limits_check: an integrity value over the three, written with them;
  # a mismatch at boot (an incomplete or corrupt save) leaves the limits
  # INVALID. Written ONLY by the two number entities' validated set_actions.
  - id: dump_op_ceiling_w
    type: int
    restore_value: yes
    initial_value: '${ecco_dump_controller_max_ceiling_w}'
  - id: dump_max_export_w
    type: int
    restore_value: yes
    initial_value: '0'
  - id: dump_limits_cap_w
    type: int
    restore_value: yes
    initial_value: '${ecco_dump_capability_w}'
  - id: dump_limits_check
    type: uint32_t
    restore_value: yes
    initial_value: '${ecco_dump_limits_default_check}'
  # fcp1: RAM state. dump_limits_valid is decided at boot and by each accepted
  # change; dump_lease_ceiling_w is the ceiling LATCHED at START for the
  # current lease (only ever lowered during it); dump_limits_arm_ms is when
  # the limits arm was turned on; dump_export_window holds the last four
  # export-guard samples (bit 0 newest).
  - id: dump_limits_valid
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_lease_ceiling_w
    type: int
    restore_value: no
    initial_value: '${ecco_dump_controller_min_ceiling_w}'
  - id: dump_limits_arm_ms
    type: uint32_t
    restore_value: no
    initial_value: '0'
  - id: dump_export_window
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_export_last_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_target_power
    type: uint16_t
    restore_value: no
    initial_value: '0'
""")

# ---- readback_sensor
READBACK_SENSOR_OLD = _blk(r"""
  # dtgp1 (2026-10-07): read-back of the configured Dump-to-Grid command ceiling
  # (ecco_dump_controller_max_ceiling_w, compile-time; generic default 3000 W).
  # Diagnostic only - no Modbus, no write, and Home Assistant cannot change it;
  # it lets Home Assistant and a live-proof pre-flight confirm what a build was
  # configured with.
  - platform: template
    name: "Dump to Grid Max Battery Ceiling"
    id: dump_max_ceiling_sensor
    unit_of_measurement: "W"
    device_class: power
    accuracy_decimals: 0
    entity_category: diagnostic
    update_interval: 60s
    lambda: |-
      return (float) ${ecco_dump_controller_max_ceiling_w};
""")
READBACK_SENSOR_NEW = _blk(r"""
  # dtgp1 (2026-10-07): read-back of the configured Dump-to-Grid command ceiling.
  # fcp1 (2026-10-13): the configured ceiling is now the persisted run-time
  # Dump to Grid Power Ceiling (dump_op_ceiling_w); this read-back reports it.
  # Diagnostic only - no Modbus, no write.
  - platform: template
    name: "Dump to Grid Max Battery Ceiling"
    id: dump_max_ceiling_sensor
    unit_of_measurement: "W"
    device_class: power
    accuracy_decimals: 0
    entity_category: diagnostic
    update_interval: 10s
    lambda: |-
      return (float) id(dump_op_ceiling_w);

  # fcp1: the profile's Dump capability (compile-time; read-only).
  - platform: template
    name: "Dump to Grid Capability"
    id: dump_capability_sensor
    unit_of_measurement: "W"
    device_class: power
    accuracy_decimals: 0
    entity_category: diagnostic
    update_interval: 60s
    lambda: |-
      return (float) ${ecco_dump_capability_w};

  # fcp1: the ceiling LATCHED for the current lease (unavailable when idle).
  - platform: template
    name: "Dump to Grid Lease Ceiling"
    id: dump_lease_ceiling_sensor
    unit_of_measurement: "W"
    device_class: power
    accuracy_decimals: 0
    entity_category: diagnostic
    update_interval: 10s
    lambda: |-
      if (!id(dump_active_persisted)) return NAN;
      return (float) id(dump_lease_ceiling_w);
""")

# ---- numbers
NUMBERS_OLD = _blk(r"""
  - platform: template
    name: "Dump to Grid Duration"
    id: dump_duration_minutes
""")
NUMBERS_NEW = _blk(r"""
  # fcp1 (2026-10-13): the two Dump OPERATING limits. Their values live in the
  # persisted globals dump_op_ceiling_w / dump_max_export_w; these entities
  # only display them and validate a change request. A RAISE (or leaving an
  # INVALID state) needs the "Dump Power Limits Write Enable" arm (valid for
  # ecco_dump_limits_arm_window_ms, one change) and Dump to Grid idle. A
  # REDUCTION is always accepted, also during a lease, and never raises the
  # lease's latched ceiling. A refused request changes nothing and says why in
  # "Dump Power Limits Status". No Modbus I/O here.
  - platform: template
    name: "Dump to Grid Power Ceiling"
    id: dump_op_ceiling_number
    min_value: ${ecco_dump_controller_min_ceiling_w}
    max_value: ${ecco_dump_capability_w}
    step: ${ecco_dump_controller_round_w}
    mode: box
    unit_of_measurement: "W"
    icon: "mdi:battery-arrow-down-outline"
    update_interval: 10s
    lambda: |-
      return (float) id(dump_op_ceiling_w);
    set_action:
      - lambda: |-
          // NaN is refused before any conversion (lroundf(NaN) is undefined).
          int req = std::isnan(x) ? -1 : (int) lroundf(x);
          int cur = id(dump_op_ceiling_w);
          bool idle = !id(dump_active_persisted) && !id(dump_operation_in_progress) && !id(dump_snapshot_valid);
          bool armed = id(dump_limits_arm).state &&
                       (uint32_t) (millis() - id(dump_limits_arm_ms)) <= ${ecco_dump_limits_arm_window_ms}UL;
          int why = 0;
          if (std::isnan(x) || req < ${ecco_dump_controller_min_ceiling_w} || req > ${ecco_dump_capability_w} ||
              req % ${ecco_dump_controller_round_w} != 0) why = 1;
          else if (req > cur || !id(dump_limits_valid)) {
            if (!armed) why = 2;
            else if (!idle) why = 3;
          }
          char msg[160];
          if (why != 0) {
            const char* r = why == 1 ? "outside the allowed range and step" :
                            why == 2 ? "arm Dump Power Limits Write Enable first" :
                                       "a raise is only accepted while Dump to Grid is idle";
            snprintf(msg, sizeof(msg), "REFUSED - power ceiling %d W: %s; kept %d W", req, r, cur);
            id(dump_limits_status).publish_state(msg);
            id(dump_op_ceiling_number).publish_state((float) cur);
            return;
          }
          int ex = id(dump_max_export_w);
          id(dump_op_ceiling_w) = req;
          id(dump_limits_cap_w) = ${ecco_dump_capability_w};
          id(dump_limits_check) = (uint32_t) req + 3u * (uint32_t) ex + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
          id(dump_limits_valid) = ex >= 0 && ex <= ${ecco_dump_capability_w} && ex % 10 == 0;
          // A reduction during a lease lowers that lease's latched ceiling at once; nothing ever raises it.
          if (id(dump_active_persisted) && id(dump_lease_ceiling_w) > req) id(dump_lease_ceiling_w) = req;
          if (req > cur || !id(dump_limits_valid)) id(dump_limits_arm).turn_off();
          snprintf(msg, sizeof(msg), "%s - power ceiling %d W (was %d W); maximum grid export %d W%s",
                   id(dump_limits_valid) ? "VALID" : "INVALID", req, cur, ex, ex == 0 ? " (NOT CONFIGURED)" : "");
          id(dump_limits_status).publish_state(msg);
          id(dump_op_ceiling_number).publish_state((float) req);

  - platform: template
    name: "Dump to Grid Max Grid Export"
    id: dump_max_export_number
    min_value: 0
    max_value: ${ecco_dump_capability_w}
    step: 10
    mode: box
    unit_of_measurement: "W"
    icon: "mdi:transmission-tower-export"
    update_interval: 10s
    lambda: |-
      return (float) id(dump_max_export_w);
    set_action:
      - lambda: |-
          // NaN is refused before any conversion (lroundf(NaN) is undefined).
          int req = std::isnan(x) ? -1 : (int) lroundf(x);
          int cur = id(dump_max_export_w);
          bool idle = !id(dump_active_persisted) && !id(dump_operation_in_progress) && !id(dump_snapshot_valid);
          bool armed = id(dump_limits_arm).state &&
                       (uint32_t) (millis() - id(dump_limits_arm_ms)) <= ${ecco_dump_limits_arm_window_ms}UL;
          int why = 0;
          if (std::isnan(x) || req < 0 || req > ${ecco_dump_capability_w} || req % 10 != 0) why = 1;
          else if (req > cur || !id(dump_limits_valid)) {
            if (!armed) why = 2;
            else if (!idle) why = 3;
          }
          char msg[160];
          if (why != 0) {
            const char* r = why == 1 ? "outside the allowed range and step" :
                            why == 2 ? "arm Dump Power Limits Write Enable first" :
                                       "a raise is only accepted while Dump to Grid is idle";
            snprintf(msg, sizeof(msg), "REFUSED - maximum grid export %d W: %s; kept %d W", req, r, cur);
            id(dump_limits_status).publish_state(msg);
            id(dump_max_export_number).publish_state((float) cur);
            return;
          }
          int op = id(dump_op_ceiling_w);
          id(dump_max_export_w) = req;
          id(dump_limits_cap_w) = ${ecco_dump_capability_w};
          id(dump_limits_check) = (uint32_t) op + 3u * (uint32_t) req + 7u * (uint32_t) ${ecco_dump_capability_w} + 12345u;
          id(dump_limits_valid) = op >= ${ecco_dump_controller_min_ceiling_w} && op <= ${ecco_dump_capability_w} &&
                                  op % ${ecco_dump_controller_round_w} == 0;
          if (req > cur || !id(dump_limits_valid)) id(dump_limits_arm).turn_off();
          snprintf(msg, sizeof(msg), "%s - power ceiling %d W; maximum grid export %d W (was %d W)%s",
                   id(dump_limits_valid) ? "VALID" : "INVALID", op, req, cur, req == 0 ? " (NOT CONFIGURED)" : "");
          id(dump_limits_status).publish_state(msg);
          id(dump_max_export_number).publish_state((float) req);

  - platform: template
    name: "Dump to Grid Duration"
    id: dump_duration_minutes
""")

# ---- switch
SWITCH_OLD = _blk(r"""
  - platform: template
    name: "Dump to Grid Write Enable"
    id: dump_write_enable
    optimistic: true
    restore_mode: ALWAYS_OFF
    icon: "mdi:shield-key-outline"
""")
SWITCH_NEW = _blk(r"""
  - platform: template
    name: "Dump to Grid Write Enable"
    id: dump_write_enable
    optimistic: true
    restore_mode: ALWAYS_OFF
    icon: "mdi:shield-key-outline"

  # fcp1 (2026-10-13): the arm for RAISING a Dump operating limit (the power
  # ceiling or the maximum grid export) or re-setting INVALID limits. Valid
  # for one accepted change within ecco_dump_limits_arm_window_ms; never
  # needed to LOWER a limit. Writes nothing to the inverter.
  - platform: template
    name: "Dump Power Limits Write Enable"
    id: dump_limits_arm
    optimistic: true
    restore_mode: ALWAYS_OFF
    icon: "mdi:shield-key-outline"
    turn_on_action:
      - lambda: 'id(dump_limits_arm_ms) = millis();'
""")

# ---- text_sensors
TEXT_SENSORS_OLD = _blk(r"""
  - platform: template
    name: "Dump to Grid Status"
    id: dump_status
    update_interval: never
    icon: "mdi:transmission-tower-export"
""")
TEXT_SENSORS_NEW = _blk(r"""
  - platform: template
    name: "Dump to Grid Status"
    id: dump_status
    update_interval: never
    icon: "mdi:transmission-tower-export"

  # fcp1 (2026-10-13): which inverter capability profile this build is for.
  - platform: template
    name: "Inverter Capability Profile"
    id: inverter_capability_profile
    entity_category: diagnostic
    update_interval: 3600s
    lambda: |-
      return std::string("${ecco_inverter_profile_id} - ${ecco_inverter_profile_name}");

  # fcp1: VALID / INVALID state of the persisted Dump operating limits and the
  # outcome of the last change request (published on boot and on each request).
  - platform: template
    name: "Dump Power Limits Status"
    id: dump_limits_status
    update_interval: never
    icon: "mdi:shield-check-outline"
""")

# ---- arm_interval
ARM_INTERVAL_OLD = _blk(r"""
interval:
  - interval: 15s
    startup_delay: 15s
""")
ARM_INTERVAL_NEW = _blk(r"""
interval:
  # fcp1 (2026-10-13): the limits arm turns itself off once its window has
  # passed (a refused or unused arm never lingers). RAM only, no Modbus I/O.
  - interval: 5s
    then:
      - lambda: |-
          if (id(dump_limits_arm).state &&
              (uint32_t) (millis() - id(dump_limits_arm_ms)) > ${ecco_dump_limits_arm_window_ms}UL) {
            id(dump_limits_arm).turn_off();
          }
  - interval: 15s
    startup_delay: 15s
""")

# ---- start_gate
START_GATE_OLD = _blk(r"""
                id(dump_duration_minutes).state >= 1.0f &&
                id(dump_duration_minutes).state <= 240.0f &&
                // Bus quiescence gate - see start_free_power_override's own
""")
START_GATE_NEW = _blk(r"""
                id(dump_duration_minutes).state >= 1.0f &&
                id(dump_duration_minutes).state <= 240.0f &&
                // fcp1 (2026-10-13): the persisted operating limits must be
                // VALID, the maximum net grid export CONFIGURED, and the
                // requested export target within it.
                id(dump_limits_valid) &&
                id(dump_max_export_w) > 0 &&
                id(dump_export_power).state <= (float) id(dump_max_export_w) &&
                // Bus quiescence gate - see start_free_power_override's own
""")

# ---- start_latch
START_LATCH_OLD = _blk(r"""
                id(dump_target_stop_soc) = (int) lroundf(id(dump_stop_soc).state);
""")
START_LATCH_NEW = _blk(r"""
                id(dump_target_stop_soc) = (int) lroundf(id(dump_stop_soc).state);
                // fcp1: LATCH this lease's ceiling - the persisted power ceiling,
                // bounded by the profile capability. A later raise of the setting
                // never reaches this lease; a reduction lowers it (set_action).
                id(dump_lease_ceiling_w) = id(dump_op_ceiling_w) < ${ecco_dump_capability_w} ? id(dump_op_ceiling_w) : ${ecco_dump_capability_w};
""")

# ---- start_refusals
START_REFUSALS_OLD = _blk(r"""
                else if (!armed) id(dump_status).publish_state("REJECTED - arm Dump to Grid Write Enable first");
""")
START_REFUSALS_NEW = _blk(r"""
                else if (!id(dump_limits_valid)) id(dump_status).publish_state("REJECTED - Dump power limits are invalid; set them again (see Dump Power Limits Status)");
                else if (id(dump_max_export_w) <= 0) id(dump_status).publish_state("REJECTED - maximum grid export not configured; set Dump to Grid Max Grid Export first");
                else if (id(dump_export_power).state > (float) id(dump_max_export_w)) id(dump_status).publish_state("REJECTED - requested export is above the configured maximum grid export");
                else if (!armed) id(dump_status).publish_state("REJECTED - arm Dump to Grid Write Enable first");
""")

# ---- ff_cap
FF_CAP_OLD = _blk(r"""
                        float start_cap =
                          ((float) ${ecco_dump_feedforward_max_start_ceiling_w} < (float) ${ecco_dump_controller_max_ceiling_w})
                            ? (float) ${ecco_dump_feedforward_max_start_ceiling_w}
                            : (float) ${ecco_dump_controller_max_ceiling_w};
""")
FF_CAP_NEW = _blk(r"""
                        // fcp1: bounded by this lease's latched ceiling.
                        float start_cap =
                          ((float) ${ecco_dump_feedforward_max_start_ceiling_w} < (float) id(dump_lease_ceiling_w))
                            ? (float) ${ecco_dump_feedforward_max_start_ceiling_w}
                            : (float) id(dump_lease_ceiling_w);
""")

# ---- feasibility
FEASIBILITY_OLD = _blk(r"""
            } else if (ecco_feas_required_w > ${ecco_dump_controller_max_ceiling_w}.0f) {
""")
FEASIBILITY_NEW = _blk(r"""
            } else if (ecco_feas_required_w > (float) id(dump_lease_ceiling_w)) {
""")

# ---- forced_reduction
FORCED_REDUCTION_OLD = _blk(r"""
          if (id(correction_in_progress)) return;
""")
FORCED_REDUCTION_NEW = _blk(r"""
          if (id(correction_in_progress)) return;
          // fcp1 (2026-10-13): a mid-lease REDUCTION of the power ceiling. If the
          // commanded ceiling is above this lease's latched ceiling, step it down
          // to that ceiling now - through the same verified controller write -
          // without waiting for the deadband, the settle time or a new grid error.
          // A zero pending error means the next response judgement starts fresh.
          if ((int) id(dump_target_power) > id(dump_lease_ceiling_w)) {
            id(dump_controller_state) = "CEILING REDUCED";
            id(dump_controller_pending_prior_ceiling) = id(dump_target_power);
            id(dump_controller_pending_ceiling) = (uint16_t) id(dump_lease_ceiling_w);
            id(dump_controller_pending_error) = 0.0f;
            id(dump_controller_needs_write) = true;
            return;
          }
""")

# ---- controller_clamp
CONTROLLER_CLAMP_OLD = _blk(r"""
          if (rounded > ${ecco_dump_controller_max_ceiling_w}.0f) rounded = ${ecco_dump_controller_max_ceiling_w}.0f;
""")
CONTROLLER_CLAMP_NEW = _blk(r"""
          if (rounded > (float) id(dump_lease_ceiling_w)) rounded = (float) id(dump_lease_ceiling_w);
""")

# ---- saturated_high
SATURATED_HIGH_OLD = _blk(r"""
          } else if (new_ceiling >= (uint16_t) ${ecco_dump_controller_max_ceiling_w} && error > 0.0f) {
""")
SATURATED_HIGH_NEW = _blk(r"""
          } else if (new_ceiling >= (uint16_t) id(dump_lease_ceiling_w) && error > 0.0f) {
""")

# ---- infeasible_text_a
INFEASIBLE_TEXT_A_OLD = _blk(r"""
                              } else if (id(dump_controller_state) == "TARGET INFEASIBLE HIGH") {
                                snprintf(msg, sizeof(msg), "ACTIVE - VERIFIED OK; target %uW export - TARGET INFEASIBLE HIGH - battery ceiling %uW (required discharge ~%.0fW exceeds the %uW controller ceiling); Stop SOC %d%%", (unsigned) id(dump_target_export_power), (unsigned) id(dump_target_power), id(dump_feasibility_required_w), (unsigned) ${ecco_dump_controller_max_ceiling_w}, id(dump_target_stop_soc));
""")
INFEASIBLE_TEXT_A_NEW = _blk(r"""
                              } else if (id(dump_controller_state) == "TARGET INFEASIBLE HIGH") {
                                snprintf(msg, sizeof(msg), "ACTIVE - VERIFIED OK; target %uW export - TARGET INFEASIBLE HIGH - battery ceiling %uW (required discharge ~%.0fW exceeds the %uW controller ceiling); Stop SOC %d%%", (unsigned) id(dump_target_export_power), (unsigned) id(dump_target_power), id(dump_feasibility_required_w), (unsigned) id(dump_lease_ceiling_w), id(dump_target_stop_soc));
""")

# ---- infeasible_text_b
INFEASIBLE_TEXT_B_OLD = _blk(r"""
                } else if (id(dump_controller_state) == "TARGET INFEASIBLE HIGH") {
                  snprintf(msg, sizeof(msg), "ACTIVE - VERIFIED OK; target %uW export - TARGET INFEASIBLE HIGH - battery ceiling %uW (required discharge ~%.0fW exceeds the %uW controller ceiling); Stop SOC %d%%", (unsigned) id(dump_target_export_power), (unsigned) id(dump_target_power), id(dump_feasibility_required_w), (unsigned) ${ecco_dump_controller_max_ceiling_w}, id(dump_target_stop_soc));
""")
INFEASIBLE_TEXT_B_NEW = _blk(r"""
                } else if (id(dump_controller_state) == "TARGET INFEASIBLE HIGH") {
                  snprintf(msg, sizeof(msg), "ACTIVE - VERIFIED OK; target %uW export - TARGET INFEASIBLE HIGH - battery ceiling %uW (required discharge ~%.0fW exceeds the %uW controller ceiling); Stop SOC %d%%", (unsigned) id(dump_target_export_power), (unsigned) id(dump_target_power), id(dump_feasibility_required_w), (unsigned) id(dump_lease_ceiling_w), id(dump_target_stop_soc));
""")

# ---- backstop_onvalue
BACKSTOP_ONVALUE_OLD = _blk(r"""
            float backstop_floor = ${ecco_dump_runaway_backstop_floor_w}.0f;
            if (backstop_floor > ${ecco_dump_controller_max_ceiling_w}.0f) backstop_floor = ${ecco_dump_controller_max_ceiling_w}.0f;
""")
BACKSTOP_ONVALUE_NEW = _blk(r"""
            float backstop_floor = ${ecco_dump_runaway_backstop_floor_w}.0f;
            if (backstop_floor > (float) id(dump_lease_ceiling_w)) backstop_floor = (float) id(dump_lease_ceiling_w);
""")

# ---- backstop_watchdog
BACKSTOP_WATCHDOG_OLD = _blk(r"""
                          float backstop_floor = ${ecco_dump_runaway_backstop_floor_w}.0f;
                          if (backstop_floor > ${ecco_dump_controller_max_ceiling_w}.0f) backstop_floor = ${ecco_dump_controller_max_ceiling_w}.0f;
""")
BACKSTOP_WATCHDOG_NEW = _blk(r"""
                          float backstop_floor = ${ecco_dump_runaway_backstop_floor_w}.0f;
                          if (backstop_floor > (float) id(dump_lease_ceiling_w)) backstop_floor = (float) id(dump_lease_ceiling_w);
""")

# ---- w2
W2_OLD = _blk(r"""
              if (w2_uniform && ri.words[1] <= ${ecco_dump_controller_max_ceiling_w}) v.warnings = (uint16_t) (v.warnings | (1u << 1));
""")
W2_NEW = _blk(r"""
              if (w2_uniform && ri.words[1] <= id(dump_op_ceiling_w)) v.warnings = (uint16_t) (v.warnings | (1u << 1));
""")

# ---- export_sample
EXPORT_SAMPLE_OLD = _blk(r"""
    on_value:
      then:
        - lambda: 'id(dump_grid_last_update_ms) = millis();'
""")
EXPORT_SAMPLE_NEW = _blk(r"""
    on_value:
      then:
        - lambda: 'id(dump_grid_last_update_ms) = millis();'
        # fcp1 (2026-10-13): the in-lease NET GRID EXPORT guard's sample window.
        # Export = -register 172. A fresh sample is "over" when export exceeds
        # the configured maximum grid export plus max(ecco_dump_export_margin_min_w,
        # 3 %). Outside a settled lease the window is cleared. The 15 s watchdog
        # ends the lease once ecco_dump_export_guard_samples of the last four
        # samples are over. RAM only, no Modbus I/O.
        - lambda: |-
            if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                (uint32_t) (millis() - id(dump_active_since_ms)) < ${ecco_dump_runaway_grace_ms}UL) {
              id(dump_export_window) = 0;
              return;
            }
            float limit = (float) id(dump_max_export_w);
            float margin = limit * 0.03f;
            if (margin < ${ecco_dump_export_margin_min_w}.0f) margin = ${ecco_dump_export_margin_min_w}.0f;
            bool over = !std::isnan(x) && -x > limit + margin;
            id(dump_export_window) = (uint8_t) (((id(dump_export_window) << 1) | (over ? 1 : 0)) & 15);
            if (over) id(dump_export_last_w) = -x;
""")

# ---- export_guard
EXPORT_GUARD_OLD = _blk(r"""
                        return std::string(msg);
            # 2026-09-26 pre-live hardening - ACTIVE lease drift check. Uses
""")
EXPORT_GUARD_NEW = _blk(r"""
                        return std::string(msg);
            # fcp1 (2026-10-13): NET GRID EXPORT guard - independent of the power
            # ceiling and of the runaway guards. See ecco_grid_ct_power's on_value.
            - if:
                condition:
                  lambda: |-
                    uint8_t w = id(dump_export_window);
                    int over = (w & 1) + ((w >> 1) & 1) + ((w >> 2) & 1) + ((w >> 3) & 1);
                    return over >= ${ecco_dump_export_guard_samples};
                then:
                  - script.execute:
                      id: request_dump_end
                      reason: !lambda |-
                        char msg[160];
                        snprintf(msg, sizeof(msg), "MAXIMUM GRID EXPORT EXCEEDED - net export %.0fW above the configured %dW limit", id(dump_export_last_w), id(dump_max_export_w));
                        return std::string(msg);
            # 2026-09-26 pre-live hardening - ACTIVE lease drift check. Uses
""")

EDITS = (
    Edit('profile', PROFILE_OLD, PROFILE_NEW),
    Edit('default_ceiling_doc', DEFAULT_CEILING_DOC_OLD, DEFAULT_CEILING_DOC_NEW),
    Edit('compile_checks', COMPILE_CHECKS_OLD, COMPILE_CHECKS_NEW),
    Edit('boot_limits', BOOT_LIMITS_OLD, BOOT_LIMITS_NEW),
    Edit('globals', GLOBALS_OLD, GLOBALS_NEW),
    Edit('readback_sensor', READBACK_SENSOR_OLD, READBACK_SENSOR_NEW),
    Edit('numbers', NUMBERS_OLD, NUMBERS_NEW),
    Edit('switch', SWITCH_OLD, SWITCH_NEW),
    Edit('text_sensors', TEXT_SENSORS_OLD, TEXT_SENSORS_NEW),
    Edit('arm_interval', ARM_INTERVAL_OLD, ARM_INTERVAL_NEW),
    Edit('start_gate', START_GATE_OLD, START_GATE_NEW),
    Edit('start_latch', START_LATCH_OLD, START_LATCH_NEW),
    Edit('start_refusals', START_REFUSALS_OLD, START_REFUSALS_NEW),
    Edit('ff_cap', FF_CAP_OLD, FF_CAP_NEW),
    Edit('feasibility', FEASIBILITY_OLD, FEASIBILITY_NEW),
    Edit('forced_reduction', FORCED_REDUCTION_OLD, FORCED_REDUCTION_NEW),
    Edit('controller_clamp', CONTROLLER_CLAMP_OLD, CONTROLLER_CLAMP_NEW),
    Edit('saturated_high', SATURATED_HIGH_OLD, SATURATED_HIGH_NEW),
    Edit('infeasible_text_a', INFEASIBLE_TEXT_A_OLD, INFEASIBLE_TEXT_A_NEW),
    Edit('infeasible_text_b', INFEASIBLE_TEXT_B_OLD, INFEASIBLE_TEXT_B_NEW),
    Edit('backstop_onvalue', BACKSTOP_ONVALUE_OLD, BACKSTOP_ONVALUE_NEW),
    Edit('backstop_watchdog', BACKSTOP_WATCHDOG_OLD, BACKSTOP_WATCHDOG_NEW),
    Edit('w2', W2_OLD, W2_NEW),
    Edit('export_sample', EXPORT_SAMPLE_OLD, EXPORT_SAMPLE_NEW),
    Edit('export_guard', EXPORT_GUARD_OLD, EXPORT_GUARD_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)


def pre_fcp1_firmware(text: str) -> str:
    """The firmware text with exactly fcp1's edits undone (the exact-match reverter of chain entry fcp1). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the dtgp1
    firmware (public main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"fcp1 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out


def add_fcp1_firmware(text: str) -> str:
    """Applies fcp1's edits, in order, to the dtgp1 firmware (the round trip)."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"fcp1 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out
