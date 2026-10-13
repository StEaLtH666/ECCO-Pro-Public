"""fcp2 (full-capability Dump-to-Grid, phase 2: safety hardening) change scope: exactly what fcp2 changes in
firmware/ecco_clock_dongle_stage3_4_free_power.yaml, and its exact inverse.

Same technique as _fcp1_scope.py: the verbatim edits are held HERE as the single source of truth, as exact (before, after) pairs,
and the reverter raises unless every edit is present exactly once. The post-export chain entry `fcp2` (registry/tests/_scope_chain.py
POST_EXPORT_ENTRIES, appended last after fcp1; registry/tests/_pex.py) carries `pre_fcp2_firmware`: the current firmware text with
exactly these edits removed, which reproduces the fcp1 firmware byte for byte (BASE_FW_SHA = the chain's fcp1 checkpoint).

WHAT fcp2 IS (owner decision 2026-10-13: the safety work that must be in the ONE eventual flash before any Dump power above 3000 W).
Every item below is offline-implemented and simulator-tested only.

  SG-40  no controller write after END. Once the write mutex is held, and again in the same synchronous step that issues the
         256-261 write, the controller re-checks that the lease is still live (active, no End/restore requested, no restore running,
         not corrupt, the obligation marker RESTORE_REQUIRED). If not, the write is CANCELLED: never issued, verified, recorded or
         published; the mutex is released and the lease's restore proceeds.
  R-1    windowed, efficiency-aware runaway guard. The consecutive-sample counters are unchanged (never looser than before); an
         8-sample history of VALID battery samples adds k-of-8 decisions against the ordinary threshold, the absolute backstop and
         a gross level, latched at the sample that completes them, so an alternating (50 % duty) overshoot trips. Above
         ecco_dump_runaway_backstop_floor_w (3000 W) the backstop's margin grows by the profile's DC-over-AC allowance
         (ecco_dump_runaway_dc_allowance_pct) of the command above that floor; at or below it the margin is unchanged.

  ZERO new Modbus operation and ZERO new inverter write domain (register 245 untouched); no persisted global, durable record, tag or
  header change (every new global is RAM only).

This module imports no other scope module and not _scope_chain (the chain imports it). No I/O.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

# The accepted fcp1 candidate this change is based on (dev/full-capability-fcp1).
BASE_COMMIT = "db969cb5a7134b44f6791e69a7274aaa94ec9525"
FIRMWARE_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
# sha256 (LF) of the firmware YAML at BASE_COMMIT (= the chain's fcp1 checkpoint): what pre_fcp2_firmware() must reproduce.
BASE_FW_SHA = "3101b8a921c8ac72cf42c8f95ae5b260e65d698f17c087bb5df3cb4510e11003"

ADDED_FILES = frozenset({
    "docs/dev/dump-to-grid-safety-fcp2.md",
    "registry/tests/_fcp2_scope.py",
    "registry/tests/fixtures/dump_lease_residuals_fcp2.json",
    "registry/tests/test_dump_safety_fcp2.py",
})

# The substitutions fcp2 adds (key -> EXACT value).
SUBSTITUTIONS = {
    'ecco_dump_runaway_dc_allowance_pct': '12',
    'ecco_dump_runaway_window_k': '4',
    'ecco_dump_runaway_gross_k': '3',
}

# Every global fcp2 adds (all RAM only: restore_value no).
NEW_GLOBAL_IDS = ('dump_runaway_win_ord', 'dump_runaway_win_abs', 'dump_runaway_win_gross', 'dump_runaway_trip', 'dump_runaway_trip_w', 'dump_runaway_trip_threshold_w', 'dump_runaway_trip_count', 'dump_controller_write_cancelled')


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
        raise AssertionError(f"fcp2 scope: {what} must be {state} exactly once, found {n}x: {find[:70]!r}")
    i = text.index(find)
    return text[:i] + put + text[i + len(find):]


# ---- dc_allowance_subst
DC_ALLOWANCE_SUBST_OLD = _blk(r"""
  ecco_dump_capability_w: "8000"
""")
DC_ALLOWANCE_SUBST_NEW = _blk(r"""
  ecco_dump_capability_w: "8000"
  # fcp2 (R-1): the profile's DC-over-AC allowance for the absolute runaway
  # backstop, in percent of the commanded TOU power. The TOU power registers
  # (256-261) limit the inverter's AC output, while register 190 measures
  # battery DC power including the conversion loss, so a healthy lease draws
  # MORE than its command: the recorded leases on the reference installation
  # show +228..+275 W at 2000 W and +271..+357 W at 3000 W (about 7-12 %).
  # Above ecco_dump_runaway_backstop_floor_w the backstop's margin grows by
  # this share of the command above that floor, so its headroom over a
  # residual of this size is the same at every operating level; at or below
  # the floor the margin is exactly the fixed one it always was. Chosen above
  # every recorded residual. 0..30 (compile-time check).
  ecco_dump_runaway_dc_allowance_pct: "12"
""")

# ---- window_subst
WINDOW_SUBST_OLD = _blk(r"""
  ecco_dump_runaway_backstop_floor_w: "3000"
""")
WINDOW_SUBST_NEW = _blk(r"""
  ecco_dump_runaway_backstop_floor_w: "3000"
  # fcp2 (R-1): WINDOWED runaway detection, IN ADDITION to the consecutive-
  # sample counters above (unchanged, so the guard is never looser than
  # before). Every valid battery-power sample (a published, non-NaN reading
  # after the lease-start grace) is recorded in an 8-sample history against
  # the ordinary threshold, the absolute backstop and a GROSS level (the
  # backstop plus one more absolute margin). The lease ends once
  # ecco_dump_runaway_window_k of the last 8 valid samples are above the
  # ordinary threshold or above the backstop - a sustained 50 %-duty
  # oscillation, which never forms a consecutive run, trips this - or
  # ecco_dump_runaway_gross_k of the last 8 are above the gross level (a
  # large excursion at a lower duty). Two isolated samples never trip it. The consecutive runs of the counters above are
  # read from the same history too. A skipped or NaN sample is never "below":
  # the history simply does not advance. The decision is LATCHED at the
  # sample that completes it, so the 15 s watchdog cannot miss it between two
  # samples; it is cleared only at the next lease START.
  ecco_dump_runaway_window_k: "4"
  ecco_dump_runaway_gross_k: "3"
""")

# ---- window_asserts
WINDOW_ASSERTS_OLD = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
""")
WINDOW_ASSERTS_NEW = _blk(r"""
          static_assert(${ecco_dump_runaway_backstop_floor_w} == (long) ${ecco_dump_runaway_backstop_floor_w}.0f &&
                            ${ecco_dump_controller_min_ceiling_w} < ${ecco_dump_runaway_backstop_floor_w},
                        "Dump runaway backstop floor: a plain decimal integer above the controller floor");
          // fcp2 (R-1): the profile's DC allowance and the runaway windows. k <= 4 of
          // 8 so a sustained 50 %-duty oscillation always trips; gross k >= 3 so two
          // isolated samples never do.
          static_assert(${ecco_dump_runaway_dc_allowance_pct} >= 0 && ${ecco_dump_runaway_dc_allowance_pct} <= 30,
                        "Dump runaway DC allowance: 0 to 30 percent of the command");
          static_assert(${ecco_dump_runaway_window_k} >= 3 && ${ecco_dump_runaway_window_k} <= 4 &&
                            ${ecco_dump_runaway_gross_k} >= 3 && ${ecco_dump_runaway_gross_k} <= ${ecco_dump_runaway_window_k},
                        "Dump runaway windows: k of the last 8 valid samples");
          static_assert(${ecco_dump_runaway_samples} >= 2 && ${ecco_dump_runaway_samples} <= 8 &&
                            ${ecco_dump_runaway_absolute_samples} >= 2 && ${ecco_dump_runaway_absolute_samples} <= 8,
                        "Dump runaway consecutive runs must fit the 8-sample history");
""")

# ---- window_globals
WINDOW_GLOBALS_OLD = _blk(r"""
  - id: dump_absolute_overpower_samples
    type: int
    restore_value: no
    initial_value: '0'
""")
WINDOW_GLOBALS_NEW = _blk(r"""
  - id: dump_absolute_overpower_samples
    type: int
    restore_value: no
    initial_value: '0'
  # fcp2 (R-1): the windowed runaway history - bit 0 the newest VALID battery
  # sample, 8 samples - against the ordinary threshold, the absolute backstop
  # and the gross level (see ecco_dump_runaway_window_k). dump_runaway_trip is
  # the LATCHED decision (0 none, 1 ordinary, 2 backstop, 3 gross) with the
  # sample, the threshold and the window count that completed it. Cleared at
  # every lease START; RAM only.
  - id: dump_runaway_win_ord
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_win_abs
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_win_gross
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_trip
    type: uint8_t
    restore_value: no
    initial_value: '0'
  - id: dump_runaway_trip_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_trip_threshold_w
    type: float
    restore_value: no
    initial_value: '0.0'
  - id: dump_runaway_trip_count
    type: int
    restore_value: no
    initial_value: '0'
""")

# ---- abs_margin
ABS_MARGIN_OLD = _blk(r"""
            if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;
            if (!std::isnan(x) && x > backstop_ref + ${ecco_dump_runaway_absolute_margin_w}.0f) {
""")
ABS_MARGIN_NEW = _blk(r"""
            if (backstop_ref < backstop_floor) backstop_ref = backstop_floor;
            // fcp2 (R-1): efficiency-aware absolute margin - see
            // ecco_dump_runaway_dc_allowance_pct. Exactly the fixed margin at or
            // below ecco_dump_runaway_backstop_floor_w.
            float abs_margin = ${ecco_dump_runaway_absolute_margin_w}.0f;
            if (backstop_ref > ${ecco_dump_runaway_backstop_floor_w}.0f) {
              abs_margin += (backstop_ref - ${ecco_dump_runaway_backstop_floor_w}.0f) * (float) ${ecco_dump_runaway_dc_allowance_pct} / 100.0f;
            }
            if (!std::isnan(x) && x > backstop_ref + abs_margin) {
""")

# ---- window_update
WINDOW_UPDATE_OLD = _blk(r"""
            if (!std::isnan(x) && x > requested + margin) {
              id(dump_overpower_samples)++;
              id(dump_overpower_last_w) = x;
            } else {
              id(dump_overpower_samples) = 0;
            }
""")
WINDOW_UPDATE_NEW = _blk(r"""
            if (!std::isnan(x) && x > requested + margin) {
              id(dump_overpower_samples)++;
              id(dump_overpower_last_w) = x;
            } else {
              id(dump_overpower_samples) = 0;
            }
            // fcp2 (R-1): WINDOWED runaway detection - see ecco_dump_runaway_window_k.
            // Only a valid sample advances the history (a NaN is neither above nor
            // below); the first complete decision is latched until the next START.
            if (!std::isnan(x)) {
              float abs_thr = backstop_ref + abs_margin;
              float gross_thr = abs_thr + abs_margin;
              id(dump_runaway_win_ord) = (uint8_t) (((uint32_t) id(dump_runaway_win_ord) << 1) | (x > requested + margin ? 1u : 0u));
              id(dump_runaway_win_abs) = (uint8_t) (((uint32_t) id(dump_runaway_win_abs) << 1) | (x > abs_thr ? 1u : 0u));
              id(dump_runaway_win_gross) = (uint8_t) (((uint32_t) id(dump_runaway_win_gross) << 1) | (x > gross_thr ? 1u : 0u));
              if (id(dump_runaway_trip) == 0) {
                int n_ord = 0;
                int n_abs = 0;
                int n_gross = 0;
                for (int i = 0; i < 8; i++) {
                  n_ord += (id(dump_runaway_win_ord) >> i) & 1;
                  n_abs += (id(dump_runaway_win_abs) >> i) & 1;
                  n_gross += (id(dump_runaway_win_gross) >> i) & 1;
                }
                uint32_t run_ord = (1u << ${ecco_dump_runaway_samples}) - 1u;
                uint32_t run_abs = (1u << ${ecco_dump_runaway_absolute_samples}) - 1u;
                if (n_gross >= ${ecco_dump_runaway_gross_k}) {
                  id(dump_runaway_trip) = 3;
                  id(dump_runaway_trip_threshold_w) = gross_thr;
                  id(dump_runaway_trip_count) = n_gross;
                } else if (n_abs >= ${ecco_dump_runaway_window_k} || ((uint32_t) id(dump_runaway_win_abs) & run_abs) == run_abs) {
                  id(dump_runaway_trip) = 2;
                  id(dump_runaway_trip_threshold_w) = abs_thr;
                  id(dump_runaway_trip_count) = n_abs;
                } else if (n_ord >= ${ecco_dump_runaway_window_k} || ((uint32_t) id(dump_runaway_win_ord) & run_ord) == run_ord) {
                  id(dump_runaway_trip) = 1;
                  id(dump_runaway_trip_threshold_w) = requested + margin;
                  id(dump_runaway_trip_count) = n_ord;
                }
                if (id(dump_runaway_trip) != 0) id(dump_runaway_trip_w) = x;
              }
            }
""")

# ---- window_start_clear
WINDOW_START_CLEAR_OLD = _blk(r"""
                              id(dump_overpower_samples) = 0;
                              id(dump_absolute_overpower_samples) = 0;
                              // V1.1: the settle window for both the
""")
WINDOW_START_CLEAR_NEW = _blk(r"""
                              id(dump_overpower_samples) = 0;
                              id(dump_absolute_overpower_samples) = 0;
                              // fcp2 (R-1): a fresh runaway history, no latched decision.
                              id(dump_runaway_win_ord) = 0;
                              id(dump_runaway_win_abs) = 0;
                              id(dump_runaway_win_gross) = 0;
                              id(dump_runaway_trip) = 0;
                              // V1.1: the settle window for both the
""")

# ---- window_watchdog
WINDOW_WATCHDOG_OLD = _blk(r"""
                        return std::string(msg);
            # fcp1 (2026-10-13): NET GRID EXPORT guard - independent of the power
""")
WINDOW_WATCHDOG_NEW = _blk(r"""
                        return std::string(msg);
            # fcp2 (R-1): the WINDOWED runaway decision, latched by
            # ecco_battery_power's on_value at the sample that completed it (see
            # ecco_dump_runaway_window_k). Checked after the consecutive guards
            # above, so a lease they end in the same tick keeps their reason.
            - if:
                condition:
                  lambda: 'return id(dump_runaway_trip) != 0;'
                then:
                  - script.execute:
                      id: request_dump_end
                      reason: !lambda |-
                        char msg[200];
                        if (id(dump_runaway_trip) == 3) {
                          snprintf(msg, sizeof(msg), "GROSS POWER RUNAWAY (windowed) - battery discharge above the %.0fW gross level in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        } else if (id(dump_runaway_trip) == 2) {
                          snprintf(msg, sizeof(msg), "ABSOLUTE POWER RUNAWAY (windowed) - battery discharge above the %.0fW absolute backstop in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        } else {
                          snprintf(msg, sizeof(msg), "POWER RUNAWAY (windowed) - battery discharge above the %.0fW lease-ceiling threshold in %d of the last 8 samples (last %.0fW)", id(dump_runaway_trip_threshold_w), id(dump_runaway_trip_count), id(dump_runaway_trip_w));
                        }
                        return std::string(msg);
            # fcp1 (2026-10-13): NET GRID EXPORT guard - independent of the power
""")

# ---- sg40_global
SG40_GLOBAL_OLD = _blk(r"""
  - id: dump_controller_op_terminal
""")
SG40_GLOBAL_NEW = _blk(r"""
  # fcp2 (SG-40): set when the controller's write was CANCELLED because the
  # lease stopped being live (ended, an End/restore requested, a restore
  # running, corrupt) after the tick decided to write - checked once the write
  # mutex is held and again in the same step that issues the write. A
  # cancelled write is never issued, verified or recorded. Reset each time
  # the mutex is taken.
  - id: dump_controller_write_cancelled
    type: bool
    restore_value: no
    initial_value: 'false'
  - id: dump_controller_op_terminal
""")

# ---- sg40_reset
SG40_RESET_OLD = _blk(r"""
                      id(dump_controller_evidence_commit_failed) = false;
                      id(dump_controller_op_terminal) = false;
""")
SG40_RESET_NEW = _blk(r"""
                      id(dump_controller_evidence_commit_failed) = false;
                      id(dump_controller_write_cancelled) = false;
                      id(dump_controller_op_terminal) = false;
""")

# ---- sg40_after_mutex
SG40_AFTER_MUTEX_OLD = _blk(r"""
                  - lambda: |-
                      id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);
                      bool evidence_ok = false;
""")
SG40_AFTER_MUTEX_NEW = _blk(r"""
                  - lambda: |-
                      // fcp2 (SG-40): re-check, now that the write mutex is held, that the
                      // lease is still live and nothing has asked to end it. If not: no
                      // evidence commit, no R3 read, no write - the controller never writes
                      // once a lease is ending, restoring or stopped.
                      if (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                          id(dump_recovery_metadata_corrupt) || !id(dump_snapshot_valid) ||
                          id(dump_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED) {
                        id(dump_controller_write_cancelled) = true;
                        return;
                      }
                      id(dump_evidence_pending_ceiling) = id(dump_controller_pending_ceiling);
                      bool evidence_ok = false;
""")

# ---- sg40_r3_gate
SG40_R3_GATE_OLD = _blk(r"""
                  # R3 runs only once the evidence commit above has succeeded.
                  # The R3 block itself is unchanged - only re-indented under
                  # this gate.
                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_R3_GATE_NEW = _blk(r"""
                  # R3 runs only once the evidence commit above has succeeded.
                  # The R3 block itself is unchanged - only re-indented under
                  # this gate. fcp2 (SG-40): and never for a cancelled write.
                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);'
""")

# ---- sg40_write_gate
SG40_WRITE_GATE_OLD = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Ownership re-read of 256-261 did not reach a terminal state before the controller write");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_WRITE_GATE_NEW = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Ownership re-read of 256-261 did not reach a terminal state before the controller write");
                            }

                  # fcp2 (SG-40): the LAST check before the write, in the same synchronous
                  # step that issues it. An End/restore request - or any other end of the
                  # lease - that arrived while the R3 read was in flight cancels the write:
                  # once a lease is ending, the controller writes nothing.
                  - if:
                      condition:
                        lambda: |-
                          if (!id(dump_controller_write_failed) &&
                              (!id(dump_active_persisted) || id(dump_restore_requested) || id(dump_operation_in_progress) ||
                               id(dump_recovery_metadata_corrupt) || !id(dump_snapshot_valid) ||
                               id(dump_marker_state) != ecco_durable::MARKER_RESTORE_REQUIRED)) {
                            id(dump_controller_write_cancelled) = true;
                          }
                          return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);
""")

# ---- sg40_verify_gate
SG40_VERIFY_GATE_OLD = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Controller write to registers 256-261 did not reach a terminal state");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed);'
""")
SG40_VERIFY_GATE_NEW = _blk(r"""
                              ESP_LOGE("dump_to_grid", "Controller write to registers 256-261 did not reach a terminal state");
                            }

                  - if:
                      condition:
                        lambda: 'return !id(dump_controller_write_failed) && !id(dump_controller_write_cancelled);'
""")

# ---- sg40_cancel_close
SG40_CANCEL_CLOSE_OLD = _blk(r"""
                        - lambda: |-
                            id(manual_write_in_progress) = false;
                            id(dump_target_power) = id(dump_controller_pending_ceiling);
""")
SG40_CANCEL_CLOSE_NEW = _blk(r"""
                        - lambda: |-
                            id(manual_write_in_progress) = false;
                            // fcp2 (SG-40): a cancelled write was never issued - nothing to
                            // record or publish. The lease is already ending; its restore runs
                            // on the next watchdog tick (the mutex is released above).
                            if (id(dump_controller_write_cancelled)) {
                              id(dump_controller_state) = "WRITE CANCELLED - LEASE ENDING";
                              ESP_LOGW("dump_to_grid", "Controller write cancelled - the lease is ending; nothing written");
                              return;
                            }
                            id(dump_target_power) = id(dump_controller_pending_ceiling);
""")

EDITS = (
    Edit('dc_allowance_subst', DC_ALLOWANCE_SUBST_OLD, DC_ALLOWANCE_SUBST_NEW),
    Edit('window_subst', WINDOW_SUBST_OLD, WINDOW_SUBST_NEW),
    Edit('window_asserts', WINDOW_ASSERTS_OLD, WINDOW_ASSERTS_NEW),
    Edit('window_globals', WINDOW_GLOBALS_OLD, WINDOW_GLOBALS_NEW),
    Edit('abs_margin', ABS_MARGIN_OLD, ABS_MARGIN_NEW),
    Edit('window_update', WINDOW_UPDATE_OLD, WINDOW_UPDATE_NEW),
    Edit('window_start_clear', WINDOW_START_CLEAR_OLD, WINDOW_START_CLEAR_NEW),
    Edit('window_watchdog', WINDOW_WATCHDOG_OLD, WINDOW_WATCHDOG_NEW),
    Edit('sg40_global', SG40_GLOBAL_OLD, SG40_GLOBAL_NEW),
    Edit('sg40_reset', SG40_RESET_OLD, SG40_RESET_NEW),
    Edit('sg40_after_mutex', SG40_AFTER_MUTEX_OLD, SG40_AFTER_MUTEX_NEW),
    Edit('sg40_r3_gate', SG40_R3_GATE_OLD, SG40_R3_GATE_NEW),
    Edit('sg40_write_gate', SG40_WRITE_GATE_OLD, SG40_WRITE_GATE_NEW),
    Edit('sg40_verify_gate', SG40_VERIFY_GATE_OLD, SG40_VERIFY_GATE_NEW),
    Edit('sg40_cancel_close', SG40_CANCEL_CLOSE_OLD, SG40_CANCEL_CLOSE_NEW),
)
EDIT_NAMES = tuple(e.name for e in EDITS)


def pre_fcp2_firmware(text: str) -> str:
    """The firmware text with exactly fcp2's edits undone (the exact-match reverter of chain entry fcp2). Every edit must occur
    exactly once, in place, else AssertionError; after the revert every base anchor must again be unique. Reproduces the fcp1
    firmware byte for byte (BASE_FW_SHA)."""
    out = text
    for e in reversed(EDITS):
        out = _swap(out, e.after, e.before, f"{e.name} edit", "present")
    for e in EDITS:
        n = out.count(e.before)
        if n != 1:
            raise AssertionError(f"fcp2 scope: the {e.name} anchor must be unique once the edit is removed, found {n}x")
    return out


def add_fcp2_firmware(text: str) -> str:
    """Applies fcp2's edits, in order, to the fcp1 firmware (the round trip)."""
    out = text
    for e in EDITS:
        if e.after in out:
            raise AssertionError(f"fcp2 scope: {e.name} edit already present")
        out = _swap(out, e.before, e.after, f"{e.name} anchor", "found")
    return out


# fcp2 edits no frozen file.
FROZEN_REVERTERS: dict = {}
