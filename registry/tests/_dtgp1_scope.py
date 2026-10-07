"""dtgp1 (configurable Dump-to-Grid command ceiling) change scope: exactly what dtgp1 changes in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fbd1_scope.py / _fbc2_scope.py: the verbatim edits are held HERE as the single source of truth, as exact
(before, after) pairs, and a reverter raises unless every edit is present exactly once. The post-export chain entry `dtgp1`
(registry/tests/_scope_chain.py POST_EXPORT_ENTRIES, right after pex0; registry/tests/_pex.py) carries `pre_dtgp1_firmware`: the
current firmware text with exactly these edits removed, which reproduces the FB-D1 firmware byte for byte (BASE_FW_SHA = the
chain's fbd1 checkpoint; lic0, pub0 and pex0, the entries between fbd1 and dtgp1, edit no firmware). The older suites are anchored
at their own entries and revert dtgp1 FIRST; none of them was re-hashed.

WHAT dtgp1 IS. `ecco_dump_controller_max_ceiling_w` stays the ONE source of truth for the Dump-to-Grid command ceiling (the
highest battery discharge ceiling the closed-loop controller ever writes to 256-261) and keeps its generic default, 3000 W, the
only hardware-proven value. A site may select another value at BUILD time only (`esphome -s ecco_dump_controller_max_ceiling_w
<W> ...`). dtgp1 adds NO Modbus operation (64 reads / 52 writes unchanged), NO script, button, switch, number, select, text sensor,
global, interval or api action, NO durable record and NO new authority. It edits the firmware in seven places:

  ceiling_doc       the source of truth's comment: what it is, how a site selects it, what refuses a bad value
  backstop_floor    one new substitution, ecco_dump_runaway_backstop_floor_w = 3000 (the highest controller ceiling at which
                    the absolute runaway backstop "ceiling + margin" is live-validated)
  backstop          ecco_battery_power's on_value: the ABSOLUTE backstop's threshold becomes
                    max(command reference, min(ceiling, floor)) + ecco_dump_runaway_absolute_margin_w, the command reference
                    being the transition-aware one the ordinary guard already uses. Identical to the old fixed
                    ceiling + margin for every configured ceiling up to the floor; never looser above it
  backstop_text     the watchdog's ABSOLUTE POWER RUNAWAY end reason names the threshold the samples were judged against
                    (the same computation, verbatim; pinned equal by test_dump_to_grid_ceiling.py)
  ceiling_checks    a fifth, compile-time-only on_boot lambda: the configured ceiling must be a plain decimal integer above
                    ecco_dump_controller_min_ceiling_w, a multiple of ecco_dump_controller_round_w, no more than
                    ecco_inverter_tou_power_ceiling_w and no more than the 8000 W architectural maximum (the one place that
                    number is spelled), and the backstop floor a decimal integer above the controller floor - otherwise no
                    firmware is produced (fail closed)
  readback_sensor   a diagnostic template sensor, "Dump to Grid Max Battery Ceiling", that reports the configured ceiling
                    (no Modbus, no write; Home Assistant cannot change it)
  w2                the REVIEW final lambda re-judges the W2 capture warning ("uniform slot powers that resemble Dump
                    residue") against the configured ceiling, right after ecco_fbcap::review_evaluate, instead of the
                    header's hard-coded 3000 W

Nothing in the deployment manifest, the Home Assistant packages, the dashboard (frozen by pub0), the firmware headers or the
firmware's other YAML files changes (test_failback_shadow_ha_contract.py, frozen by pub0, pins every git-tracked firmware file
except this YAML: the W2 header keeps its generic 3000 W constant, and this YAML applies the configured one).

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Public main the change is based on (the post-export edit layer, pex0, squash-merged as PR #4). Its firmware is the chain's fbd1
# checkpoint: lic0, pub0 and pex0 edit no firmware.
BASE_COMMIT = "a95d0b688f9953a8ef22ec81e2be27e4730fd10f"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF text, as Path.read_text returns it) of the firmware YAML at BASE_COMMIT: what pre_dtgp1_firmware() must reproduce.
BASE_FW_SHA = "104033c319d71f4d98ebcf8dc37fa2e4b6838a6597dec1da5eeb93c879a51aa2"

_BANNED = re.compile(r"ecco_fallback|FALLBACK_PROFILE|FAILBACK_STATE|ecco_failback")

ADDED_FILES = frozenset({
    "docs/dev/dump-to-grid-ceiling.md",
    "registry/tests/_dtgp1_scope.py",
    "registry/tests/test_dump_to_grid_ceiling.py",
})

# The one substitution dtgp1 adds (key -> EXACT value).
SUBSTITUTION = ("ecco_dump_runaway_backstop_floor_w", "3000")
# The one sensor dtgp1 adds.
SENSOR_ID = "dump_max_ceiling_sensor"
SENSOR_NAME = "Dump to Grid Max Battery Ceiling"
# The architectural maximum of the configured ceiling (spelled once in the firmware, inside the compile-time check).
ARCHITECTURAL_MAX_W = 8000


def _blk(s: str) -> str:
    """A raw triple-quoted literal that starts on the line after the opening quotes: drops that first newline."""
    assert s.startswith("\n") and s.endswith("\n") and "\r" not in s
    return s[1:]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- 1. the source of truth's comment ------------------------------------------------------------------------------------------
CEILING_OLD = _blk(r"""
  # live proof at higher power. Raise only after a supervised live proof
  # exercises the controller at successively higher targets.
  ecco_dump_controller_max_ceiling_w: "3000"
""")
CEILING_NEW = _blk(r"""
  # live proof at higher power. Raise only after a supervised live proof
  # exercises the controller at successively higher targets.
  # dtgp1 (2026-10-07): THE single source of truth for the Dump-to-Grid command
  # ceiling - the highest battery discharge ceiling ECCO ever writes to
  # 256-261. 3000 W is the generic default and the only hardware-proven value.
  # A site may select another value at BUILD time only, for example
  # `esphome -s ecco_dump_controller_max_ceiling_w 6000 compile <yaml>`; Home
  # Assistant can never change it at run time. on_boot's compile-time checks
  # refuse a value that is not a plain decimal integer, is not above
  # ecco_dump_controller_min_ceiling_w, is not a multiple of
  # ecco_dump_controller_round_w, exceeds ecco_inverter_tou_power_ceiling_w or
  # exceeds the architectural maximum: no firmware is produced. A value above
  # 3000 W is NOT hardware-proven (SUPPORTED_HARDWARE.md); the runaway
  # backstop follows the command above ecco_dump_runaway_backstop_floor_w.
  ecco_dump_controller_max_ceiling_w: "3000"
""")

# ---- 2. the backstop floor substitution ------------------------------------------------------------------------------------------
FLOOR_OLD = _blk(r"""
  ecco_dump_runaway_absolute_margin_w: "750"
  ecco_dump_runaway_absolute_samples: "2"
""")
FLOOR_NEW = _blk(r"""
  ecco_dump_runaway_absolute_margin_w: "750"
  ecco_dump_runaway_absolute_samples: "2"
  # dtgp1 (2026-10-07): the absolute backstop above is anchored to the CURRENT
  # command, not to ecco_dump_controller_max_ceiling_w. Its threshold is
  # max(command, min(ecco_dump_controller_max_ceiling_w, this floor)) +
  # ecco_dump_runaway_absolute_margin_w, where "command" is the commanded
  # battery ceiling (the higher of the old and the new one for
  # ecco_dump_runaway_transition_ms after a verified controller write, exactly
  # like the ordinary guard). 3000 W is the highest controller ceiling at which
  # "ceiling + margin" has been live-validated (2026-09-27), so for every
  # configured ceiling up to it the backstop is exactly the fixed
  # ceiling + margin threshold it always was; above it the threshold follows
  # the command, so a higher configured ceiling never leaves the backstop
  # parked above anything the inverter can actually do. An evidence level of
  # this guard, not a second copy of the configured ceiling.
  ecco_dump_runaway_backstop_floor_w: "3000"
""")

# ---- 3. the command-relative absolute backstop (ecco_battery_power on_value) ------------------------------------------------------
BACKSTOP_OLD = _blk(r"""
            // controller is doing right now.
            if (!std::isnan(x) && x > ${ecco_dump_controller_max_ceiling_w}.0f + ${ecco_dump_runaway_absolute_margin_w}.0f) {
""")
BACKSTOP_REF = _blk(r"""
            float backstop_ref = (float) id(dump_target_power);
            if ((uint32_t) (millis() - id(dump_last_controller_update_ms)) < ${ecco_dump_runaway_transition_ms}UL &&
                id(dump_runaway_ceiling_ref) > backstop_ref) {
              backstop_ref = id(dump_runaway_ceiling_ref);
            }
            float backstop_floor = ${ecco_dump_runaway_backstop_floor_w}.0f;
            if (backstop_floor > ${ecco_dump_controller_max_ceiling_w}.0f) backstop_floor = ${ecco_dump_controller_max_ceiling_w}.0f;
            if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;
""")
BACKSTOP_NEW = _blk(r"""
            // controller is doing right now.
            // dtgp1 (2026-10-07): the threshold is anchored to the CURRENT
            // command, never below min(ecco_dump_controller_max_ceiling_w,
            // ecco_dump_runaway_backstop_floor_w) - see that substitution. For
            // every configured ceiling up to the floor this is exactly the
            // fixed ceiling + margin threshold; above it the threshold follows
            // the command (the higher of the old and the new one during a
            // step-down transition, exactly like the ordinary guard below).
""") + BACKSTOP_REF + _blk(r"""
            if (!std::isnan(x) && x > backstop_ref + ${ecco_dump_runaway_absolute_margin_w}.0f) {
""")

# ---- 4. the END reason names the threshold actually used ------------------------------------------------------------------------
_TEXT_HEAD = _blk(r"""
                        if (id(dump_absolute_overpower_samples) >= ${ecco_dump_runaway_absolute_samples}) {
""")
TEXT_OLD = _TEXT_HEAD + _blk(r"""
                          snprintf(msg, sizeof(msg), "ABSOLUTE POWER RUNAWAY - battery discharge %.0fW sustained above the %uW V1.1 absolute backstop", id(dump_overpower_last_w), (unsigned) (${ecco_dump_controller_max_ceiling_w} + ${ecco_dump_runaway_absolute_margin_w}));
""")
TEXT_NEW = _TEXT_HEAD + _blk(r"""
                          // dtgp1: the backstop these samples were judged against - the same computation as
                          // ecco_battery_power's on_value, verbatim (pinned equal by test_dump_to_grid_ceiling.py).
""") + "".join("              " + line + "\n" for line in BACKSTOP_REF.splitlines()) + _blk(r"""
                          snprintf(msg, sizeof(msg), "ABSOLUTE POWER RUNAWAY - battery discharge %.0fW sustained above the %uW V1.1 absolute backstop", id(dump_overpower_last_w), (unsigned) (backstop_ref + ${ecco_dump_runaway_absolute_margin_w}.0f));
""")

# ---- 5. the compile-time checks (a fifth on_boot lambda) ------------------------------------------------------------------------
CHECKS_OLD = _blk(r"""
          id(fallback_profile_boot_loaded) = true;

esp32:
""")
CHECKS_LAMBDA = _blk(r"""
      - lambda: |-
          static_assert(${ecco_dump_controller_max_ceiling_w} == (long) ${ecco_dump_controller_max_ceiling_w}.0f,
                        "Dump ceiling: ecco_dump_controller_max_ceiling_w must be a plain decimal integer (W)");
          static_assert(${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_controller_max_ceiling_w},
                        "Dump ceiling: must be above the controller floor ecco_dump_controller_min_ceiling_w");
          static_assert(${ecco_dump_controller_max_ceiling_w} % ${ecco_dump_controller_round_w} == 0,
                        "Dump ceiling: must be a multiple of ecco_dump_controller_round_w");
          static_assert(${ecco_dump_controller_max_ceiling_w} <= ${ecco_inverter_tou_power_ceiling_w},
                        "Dump ceiling: must not exceed the site TOU power ceiling ecco_inverter_tou_power_ceiling_w");
          static_assert(${ecco_dump_controller_max_ceiling_w} <= 8000,
                        "Dump ceiling: 8000 W is the architectural maximum");
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
""")
CHECKS_NEW = _blk(r"""
          id(fallback_profile_boot_loaded) = true;
      # dtgp1 (2026-10-07): compile-time validation of the Dump-to-Grid command
      # ceiling, the single source of truth ecco_dump_controller_max_ceiling_w,
      # and of the runaway backstop floor. Kept in its own lambda, like the
      # heartbeat threshold checks above, so the offline simulators never have
      # to model it. A value that fails any check produces no firmware: fail
      # closed.
""") + CHECKS_LAMBDA + _blk(r"""

esp32:
""")

# ---- 6. the read-back sensor -----------------------------------------------------------------------------------------------------
SENSOR_OLD = _blk(r"""
  - platform: template
    name: "Inverter TOU Power Ceiling"
    id: inverter_tou_power_ceiling
    unit_of_measurement: "W"
    device_class: power
    accuracy_decimals: 0
    entity_category: diagnostic
    update_interval: 60s
    lambda: |-
      return (float) ${ecco_inverter_tou_power_ceiling_w};
""")
SENSOR_NEW = SENSOR_OLD + _blk(r"""

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

# ---- 7. W2 follows the configured ceiling ----------------------------------------------------------------------------------------
# In the REVIEW final lambda, right after the header's verdict: the header (firmware/include/ecco_fallback_capture.h) and its
# Python mirror stay byte-identical - test_failback_shadow_ha_contract.py pins every git-tracked firmware file except this YAML.
W2_OLD = "            ecco_fbcap::ReviewVerdict v = ecco_fbcap::review_evaluate(ri);\n"
W2_NEW = W2_OLD + _blk(r"""
            // dtgp1 (2026-10-07): W2 (resembles Dump to Grid residue: all six slot powers equal and at most the Dump
            // controller ceiling) is judged against THIS build's configured ceiling, ecco_dump_controller_max_ceiling_w,
            // instead of the header's generic 3000 W default (ecco_fbcap::DUMP_CONTROLLER_MAX_W). The header's own W2
            // predicate with the configured ceiling; every other warning bit and the rest of the verdict are the header's.
            {
              bool w2_uniform = true;
              for (int i=1;i<6;i++) w2_uniform = w2_uniform && ri.words[1 + i] == ri.words[1];
              v.warnings = (uint16_t) (v.warnings & ~(1u << 1));
              if (w2_uniform && ri.words[1] <= ${ecco_dump_controller_max_ceiling_w}) v.warnings = (uint16_t) (v.warnings | (1u << 1));
            }
""")


@dataclass(frozen=True)
class Edit:
    name: str
    region: str
    before: str
    after: str


EDITS = (
    Edit("ceiling_doc", "substitutions: ecco_dump_controller_max_ceiling_w's comment", CEILING_OLD, CEILING_NEW),
    Edit("backstop_floor", "substitutions: ecco_dump_runaway_backstop_floor_w (after the absolute backstop pair)", FLOOR_OLD,
         FLOOR_NEW),
    Edit("checks", "esphome.on_boot: the appended fifth, compile-time-only lambda", CHECKS_OLD, CHECKS_NEW),
    Edit("readback_sensor", "sensor: Dump to Grid Max Battery Ceiling (after Inverter TOU Power Ceiling)", SENSOR_OLD, SENSOR_NEW),
    Edit("backstop", "sensor ecco_battery_power on_value: the command-relative absolute backstop", BACKSTOP_OLD, BACKSTOP_NEW),
    Edit("w2", "script fallback_profile_capture_dispatch, REVIEW final: W2 re-judged against the configured ceiling", W2_OLD,
         W2_NEW),
    Edit("backstop_text", "interval (15 s Dump watchdog): the ABSOLUTE POWER RUNAWAY end reason", TEXT_OLD, TEXT_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)
assert len(set(EDIT_NAMES)) == len(EDITS) == 7

# The FB-A reserved tokens this change adds to the firmware YAML (expected 0: dtgp1 names none of them).
BANNED_FW_ADDED = sum(len(_BANNED.findall(e.after)) - len(_BANNED.findall(e.before)) for e in EDITS)


def edit(name: str) -> Edit:
    return EDITS[EDIT_NAMES.index(name)]


def _swap(text: str, find: str, put: str, what: str, state: str) -> str:
    n = text.count(find)
    if n != 1:
        raise AssertionError(f"dtgp1 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


def add_dtgp1_text(text: str) -> str:
    """Applies dtgp1 to a firmware text that has none of it (generates the change; the suite's round trip). Every `before` must be
    unique and no `after` may already be present."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"dtgp1 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out


def pre_dtgp1_firmware(text: str) -> str:
    """The firmware text with exactly dtgp1's edits undone (the exact-match reverter of chain entry dtgp1). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the FB-D1
    firmware (public main @ BASE_COMMIT) byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"dtgp1 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out
