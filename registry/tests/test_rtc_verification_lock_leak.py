#!/usr/bin/env python3
"""Offline tests for the S1 fix (branch `fix/rtc-verification-lock-leak`):
the RTC verification lock leak recorded in
docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md's defect ledger (S1) and
CURRENT_STATE.md's "Separate follow-up prerequisites" list.

Defect: the `read_inverter_clock` button's `on_response` lambda
(firmware/ecco_clock_dongle_stage3_4_free_power.yaml) has three early-return
paths that fire while a post-write verification read is in flight
(`verification_read_active == true`): out-of-range RTC register data, NTP
not (yet) synced, and NTP time not valid. Before this fix, all three
`return;`ed without releasing `verification_read_active` or
`correction_in_progress` - permanently wedging both, which blocks the Free
Power and Dump lease watchdogs' write guards
(`!correction_in_progress` at FW ~17138/17191) and every restore, with no
release path except a reboot or a manually-triggered "Read Inverter Clock"
press that happens to return valid data.

No I/O, no hardware, no ESPHome/C++ toolchain, in the same style as
registry/tests/test_free_power_hardening_2026_09_22.py and
registry/tests/test_recovery_marker_state_machine.py:

  [1]-[3]  Structural/source-anchored checks that the REAL firmware source
           now releases the lock at all three early-return sites (fails on
           pre-fix source, passes on this branch - see [4], the mutation/
           sensitivity check, which proves that directly).
  [5]-[16] A small, explicitly-labelled Python reference-model simulation
           of just the RTC verification/retry state machine (not full
           lambda execution - see the model's own docstring for the exact
           real-firmware behaviour it mirrors and the line ranges it is
           anchored to), used to reproduce the leak, prove the fix bounds
           it, and cover the adversarial scenarios the fix must survive.

These prove the source says what it should, and that a state machine
faithful to the source cannot wedge the lock - they do NOT prove the
compiled firmware behaves this way on hardware.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE_PATH = ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml"

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


if not FIRMWARE_PATH.is_file():
    print(f"  FAIL  firmware not found at {FIRMWARE_PATH}")
    sys.exit(1)

fw = FIRMWARE_PATH.read_text(encoding="utf-8")


def button_body(button_id: str) -> str:
    """Extract one `id: <button_id>` button's body - identical helper to
    test_free_power_hardening_2026_09_22.py / test_reg244_proof_harness_logic.py."""
    marker = f"\n    id: {button_id}\n"
    start = fw.index(marker)
    rest = fw[start + 1:]
    m = re.search(r"\n  - platform:|\n[a-z_]+:\n", rest)
    end = m.start() if m else len(rest)
    return rest[:end]


def guarded_early_return(block: str, log_message: str) -> bool:
    """True iff, within `block`, the early `return;` immediately following
    the literal `log_message` line is preceded (within a short, bounded
    window - so a guard on some unrelated, later return can't produce a
    false pass) by the S1 fix's release-and-requeue idiom: release
    `verification_read_active`, set `comm_failure_pending`, exactly like
    the pre-existing (already-correct) `on_error`/`on_no_response` handlers
    on the same button use."""
    idx = block.find(log_message)
    assert idx != -1, f"could not locate {log_message!r} - firmware source structure changed"
    window = block[idx: idx + 600]
    return_idx = window.find("return;")
    assert return_idx != -1, "no return; found after the log line within window - firmware source structure changed"
    pre_return = window[:return_idx]
    return (
        "id(verification_read_active)" in pre_return
        and "= false;" in pre_return
        and "id(comm_failure_pending) = true;" in pre_return
    )


read_clock_block = button_body("read_inverter_clock")

# ===========================================================================
# [1]-[3] Structural: every early-return in on_response that can fire while
# a verification read is active now releases the lock deterministically.
# ===========================================================================
print("[1] Out-of-range RTC register data no longer leaks the lock")
check(
    "invalid-data early return releases verification_read_active/comm_failure_pending before its return;",
    guarded_early_return(read_clock_block, 'ESP_LOGW("ecco", "Invalid inverter RTC data received");'),
)

print("[2] NTP-not-synced early return no longer leaks the lock")
check(
    "NTP-not-synced early return releases verification_read_active/comm_failure_pending before its return;",
    guarded_early_return(
        read_clock_block,
        'ESP_LOGI("ecco", "Inverter RTC: %s | Waiting for confirmed NTP", buffer);',
    ),
)

print("[3] NTP-currently-invalid early return no longer leaks the lock")
check(
    "NTP-invalid early return releases verification_read_active/comm_failure_pending before its return;",
    guarded_early_return(
        read_clock_block,
        'ESP_LOGW("ecco", "Inverter RTC: %s | NTP currently invalid", buffer);',
    ),
)

on_error_idx = read_clock_block.find("on_error:")
on_no_response_idx = read_clock_block.find("on_no_response:")
assert on_error_idx != -1 and on_no_response_idx != -1 and on_error_idx < on_no_response_idx, \
    "could not locate on_error:/on_no_response: sections in order - firmware source structure changed"
on_error_block = read_clock_block[on_error_idx:on_no_response_idx]
on_no_response_block = read_clock_block[on_no_response_idx:]

check(
    "the existing on_error handler is untouched (still releases verification_read_active/comm_failure_pending - regression guard)",
    "id(verification_read_active) = false;" in on_error_block
    and "id(comm_failure_pending) = true;" in on_error_block
    and "Verification read error - processing retry" in on_error_block,
)
check(
    "the existing on_no_response handler is untouched (still releases verification_read_active/comm_failure_pending - regression guard)",
    "id(verification_read_active) = false;" in on_no_response_block
    and "id(comm_failure_pending) = true;" in on_no_response_block
    and "Verification read timed out - processing retry" in on_no_response_block,
)

# ===========================================================================
# [4] MUTATION CHECK: the same assertion function, run against the verbatim
# pre-fix source (as it existed on main @ d7de449748ada9aa99c39674036cb0f8bf8bc365,
# before this branch), must FAIL - proving [1]-[3] have real discriminating
# power and are not vacuously true. This is the literal "fails on current
# main, passes with the fix" proof, without a git dependency.
# ===========================================================================
PRE_FIX_ON_RESPONSE_SNIPPET = r'''
                  if (
                    year < 2020 || year > 2099 ||
                    month < 1 || month > 12 ||
                    day < 1 || day > 31 ||
                    hour > 23 || minute > 59 || second > 59
                  ) {
                    ESP_LOGW("ecco", "Invalid inverter RTC data received");
                    return;
                  }

                  char buffer[32];
                  snprintf(
                    buffer,
                    sizeof(buffer),
                    "%04d-%02d-%02d %02d:%02d:%02d",
                    year, month, day, hour, minute, second
                  );
                  id(inverter_clock).publish_state(buffer);

                  if (!id(ntp_synced)) {
                    ESP_LOGI("ecco", "Inverter RTC: %s | Waiting for confirmed NTP", buffer);
                    return;
                  }

                  auto now = id(ntp_time).now();
                  if (!now.is_valid()) {
                    ESP_LOGW("ecco", "Inverter RTC: %s | NTP currently invalid", buffer);
                    return;
                  }
'''

print("[4] MUTATION CHECK: the [1]-[3] checks fail against the verbatim pre-fix source")
check(
    "invalid-data check fails against pre-fix source (proves it isn't vacuous)",
    not guarded_early_return(PRE_FIX_ON_RESPONSE_SNIPPET, 'ESP_LOGW("ecco", "Invalid inverter RTC data received");'),
)
check(
    "NTP-not-synced check fails against pre-fix source (proves it isn't vacuous)",
    not guarded_early_return(
        PRE_FIX_ON_RESPONSE_SNIPPET,
        'ESP_LOGI("ecco", "Inverter RTC: %s | Waiting for confirmed NTP", buffer);',
    ),
)
check(
    "NTP-invalid check fails against pre-fix source (proves it isn't vacuous)",
    not guarded_early_return(
        PRE_FIX_ON_RESPONSE_SNIPPET,
        'ESP_LOGW("ecco", "Inverter RTC: %s | NTP currently invalid", buffer);',
    ),
)


# ===========================================================================
# [5]+ Behavioural reference-model simulation.
#
# Hand-written model of just the RTC correction/verification state machine -
# NOT a lambda interpreter (contrast registry/tests/_dump_sim.py /
# _free_power_action_sim.py, which execute parsed firmware action trees; a
# dedicated interpreter was judged disproportionate to a three-site,
# same-file guard fix). Mirrors, by hand, from the real firmware:
#   - globals block (FW ~955-990): correction_in_progress, correction_is_manual,
#     correction_attempt, verification_pending, verification_read_active,
#     comm_failure_pending, have_rtc_baseline, auto_sync_pending - all
#     `restore_value: no` (RAM-only, reset to their initial_value on reboot).
#   - `read_inverter_clock` button on_response/on_error/on_no_response
#     (FW ~16239-16491, this branch's fix).
#   - `write_inverter_rtc` script (FW ~5966-6058): bus-busy deferral, write
#     ack schedules verification, write on_error/on_no_response route
#     through comm_failure_pending exactly like the read side.
#   - the 1s interval (FW ~17398-17497 pre-fix numbering; shifted by this
#     branch's insertions): comm_failure_pending consumer (bounded retry via
#     `correction_attempt < 2`, then fail-closed with a cooldown),
#     auto_sync_pending consumer (re-drives write_inverter_rtc), and the
#     verification-pending-due consumer (arms verification_read_active and
#     presses read_inverter_clock).
#   - the Free Power / Dump lease-watchdog write guards
#     (`!id(correction_in_progress)` at FW ~17138/17191).
#
# Deliberate simplification (documented, not hidden): `verification_due_ms`'s
# 10-second wait collapses to "due on the next tick" once
# `verification_pending` is set - timing value, not control-flow, and not
# relevant to whether the lock is released.
#
# `buggy=True` reproduces the pre-fix on_response (the three early returns
# do not release the lock); `buggy=False` is this branch's fix.
# ===========================================================================
class RTCVerificationSim:
    RETRY_LIMIT = 2  # matches `correction_attempt < 2` in the real firmware

    def __init__(self, buggy: bool):
        self.buggy = buggy
        self.correction_in_progress = False
        self.correction_is_manual = False
        self.correction_attempt = 0
        self.verification_pending = False
        self.verification_read_active = False
        self.comm_failure_pending = False
        self.auto_sync_pending = False
        self.have_rtc_baseline = False
        self.cooldown_active = False
        self.failed_corrections = 0
        self.corrections_since_boot = 0
        self.last_correction_result = ""
        self.ntp_synced = True
        self.ntp_time_valid = True
        self.automatic_clock_sync = True  # substitute for the HA switch entity .state
        self.manual_write_in_progress = False  # another transaction owns the bus
        self.free_power_operation_in_progress = False
        self.dump_operation_in_progress = False

    # -- helpers mirroring FW verbatim ------------------------------------
    def _retry_allowed(self) -> bool:
        return self.correction_attempt < self.RETRY_LIMIT and (
            self.correction_is_manual or self.automatic_clock_sync
        )

    def _release_via_comm_failure(self, message: str) -> None:
        # `if (id(verification_read_active)) { ... }` - idempotent: a
        # no-op when the lock is already released (proves [16] below).
        if self.verification_read_active:
            self.verification_read_active = False
            self.comm_failure_pending = True
            self.last_correction_result = message

    # -- button: read_inverter_clock --------------------------------------
    def on_response(self, *, values_valid: bool = True, ntp_synced: bool | None = None,
                     ntp_time_valid: bool | None = None, verified_ok: bool | None = None) -> None:
        ns = self.ntp_synced if ntp_synced is None else ntp_synced
        ntv = self.ntp_time_valid if ntp_time_valid is None else ntp_time_valid

        if not values_valid:
            if not self.buggy:
                self._release_via_comm_failure("Verification read returned invalid data - processing retry")
            return  # FW: return; at the invalid-data check (the S1 site)

        if not ns:
            if not self.buggy:
                self._release_via_comm_failure("Verification read stalled - NTP unavailable; processing retry")
            return  # FW: return; while waiting for confirmed NTP

        if not ntv:
            if not self.buggy:
                self._release_via_comm_failure("Verification read stalled - NTP invalid; processing retry")
            return  # FW: return; while NTP is momentarily invalid

        self.have_rtc_baseline = True

        if self.verification_read_active:
            self.verification_read_active = False
            if verified_ok:
                self.corrections_since_boot += 1
                self.correction_in_progress = False
                self.correction_is_manual = False
                self.correction_attempt = 0
                self.have_rtc_baseline = False
            else:
                if self._retry_allowed():
                    self.correction_attempt += 1
                    self.auto_sync_pending = True
                else:
                    self.failed_corrections += 1
                    self.correction_in_progress = False
                    self.correction_is_manual = False
                    self.correction_attempt = 0
                    self.verification_pending = False
                    self.have_rtc_baseline = False
                    self.cooldown_active = True

    def on_error(self) -> None:
        # Pre-existing, already-correct handler - unaffected by this fix.
        if self.verification_read_active:
            self.verification_read_active = False
            self.comm_failure_pending = True
            self.last_correction_result = "Verification read error - processing retry"

    def on_no_response(self) -> None:
        # Pre-existing, already-correct handler - unaffected by this fix.
        if self.verification_read_active:
            self.verification_read_active = False
            self.comm_failure_pending = True
            self.last_correction_result = "Verification read timed out - processing retry"

    # -- script: write_inverter_rtc ----------------------------------------
    def _execute_write_inverter_rtc(self) -> None:
        if self.manual_write_in_progress:
            self.correction_in_progress = False
            self.correction_is_manual = False
            self.correction_attempt = 0
            self.verification_pending = False
            self.verification_read_active = False
            self.last_correction_result = "Deferred - inverter write path busy; will retry"
            return
        if self.ntp_synced and self.ntp_time_valid:
            self.verification_pending = True
        # else: aborted/logged only, matching the real firmware (out of S1 scope)

    # -- button: sync_inverter_clock (manual correction) -------------------
    def start_manual_correction(self) -> None:
        self.cooldown_active = False
        self.correction_in_progress = True
        self.correction_is_manual = True
        self.correction_attempt = 1
        self._execute_write_inverter_rtc()

    def arm_verification_directly(self) -> None:
        """Test helper: jump straight to "a verification read is in
        flight" with a correction already queued (attempt 1, matching both
        real queue sites - FW ~16447 automatic, ~16508 manual, which always
        set correction_attempt = 1), skipping the write/ack bookkeeping,
        for the single-shot leak-reproduction scenarios."""
        self.correction_in_progress = True
        self.correction_attempt = 1
        self.verification_read_active = True

    # -- 1s interval --------------------------------------------------------
    def tick_1s(self) -> None:
        if self.comm_failure_pending:
            self.comm_failure_pending = False
            self.verification_pending = False
            self.verification_read_active = False
            if self._retry_allowed():
                self.correction_attempt += 1
                self.auto_sync_pending = True
            else:
                self.failed_corrections += 1
                self.correction_in_progress = False
                self.correction_is_manual = False
                self.correction_attempt = 0
                self.have_rtc_baseline = False
                self.cooldown_active = True

        if self.auto_sync_pending:
            self.auto_sync_pending = False
            if self.ntp_synced and self.ntp_time_valid and (self.correction_is_manual or self.automatic_clock_sync):
                self._execute_write_inverter_rtc()
            else:
                self.correction_in_progress = False
                self.correction_is_manual = False
                self.correction_attempt = 0
                self.verification_pending = False

        if self.verification_pending and not self.verification_read_active:
            self.verification_pending = False
            self.verification_read_active = True

    def reboot(self) -> None:
        # All the flags above are `restore_value: no` with `initial_value:
        # 'false'`/`'0'` in the real firmware globals block - a reboot
        # always clears RAM state, leak or not. This is the PRE-EXISTING
        # (insufficient on its own) recovery path S1 describes.
        self.__init__(buggy=self.buggy)  # type: ignore[misc]

    # -- lease watchdog write guards (FW ~17138/17191) ----------------------
    def free_power_gate_allows_write(self) -> bool:
        return not (self.free_power_operation_in_progress or self.manual_write_in_progress or self.correction_in_progress)

    def dump_gate_allows_write(self) -> bool:
        return not (self.dump_operation_in_progress or self.manual_write_in_progress or self.correction_in_progress)


def drive_until_resolved(sim: RTCVerificationSim, respond, max_iterations: int = 40) -> bool:
    """Advance the model, answering every re-armed verification read with
    `respond(sim)` (simulating the SAME underlying condition recurring on
    every retry - the worst case for proving the fix bounds the leak no
    matter how many times the bad condition repeats), and otherwise
    advancing one 1s interval tick. Returns True once
    `correction_in_progress` clears, False if `max_iterations` is exhausted
    first (used to prove the buggy model never resolves)."""
    for _ in range(max_iterations):
        if not sim.correction_in_progress:
            return True
        if sim.verification_read_active:
            respond(sim)
        else:
            sim.tick_1s()
    return not sim.correction_in_progress


# A generous bound: several full write/verify/retry round trips.
MAX_ITER = 40

print("[5] Reproduces S1: the buggy (pre-fix) model leaks both flags forever on out-of-range data, even across retries")
buggy = RTCVerificationSim(buggy=True)
buggy.arm_verification_directly()
resolved = drive_until_resolved(buggy, lambda s: s.on_response(values_valid=False))
check("buggy model: never resolves within the iteration budget", resolved is False)
check("buggy model: correction_in_progress never releases", buggy.correction_in_progress is True)
check("buggy model: verification_read_active never releases", buggy.verification_read_active is True)
check("buggy model: the Free Power watchdog write guard stays blocked forever", buggy.free_power_gate_allows_write() is False)
check("buggy model: the Dump watchdog write guard stays blocked forever", buggy.dump_gate_allows_write() is False)

print("[6] Fix: out-of-range RTC data on every retry still releases the lock within a bounded number of round trips")
fixed = RTCVerificationSim(buggy=False)
fixed.arm_verification_directly()
resolved = drive_until_resolved(fixed, lambda s: s.on_response(values_valid=False))
check("fixed model: resolves within the bound (not indefinite)", resolved is True, f"MAX_ITER={MAX_ITER}")
check("fixed model: correction_in_progress eventually releases", fixed.correction_in_progress is False)
check("fixed model: verification_read_active is released", fixed.verification_read_active is False)
check(
    "fixed model: failed after the bounded retry, with a cooldown recorded (fail-closed, not silently discarded)",
    fixed.failed_corrections == 1 and fixed.cooldown_active is True,
)

print("[7] Adversarial: a distinct invalid-timestamp value (year underflow) behaves identically")
fixed2 = RTCVerificationSim(buggy=False)
fixed2.arm_verification_directly()
# models year=1999 / month=13 / etc alike - all fail the same range check
resolved = drive_until_resolved(fixed2, lambda s: s.on_response(values_valid=False))
check("year-underflow-style invalid data also releases the lock", resolved is True and fixed2.correction_in_progress is False)

print("[8] Adversarial: NTP desyncs mid-verification (verification_read_active true, ntp_synced false)")
buggy_ntp = RTCVerificationSim(buggy=True)
buggy_ntp.arm_verification_directly()
resolved = drive_until_resolved(buggy_ntp, lambda s: s.on_response(ntp_synced=False))
check("buggy model: NTP-desync-during-verification also leaks forever (same defect class)", resolved is False and buggy_ntp.correction_in_progress is True)

fixed_ntp = RTCVerificationSim(buggy=False)
fixed_ntp.arm_verification_directly()
resolved = drive_until_resolved(fixed_ntp, lambda s: s.on_response(ntp_synced=False))
check("fixed model: NTP-desync-during-verification releases within the bound", resolved is True and fixed_ntp.correction_in_progress is False)

print("[9] Adversarial: NTP time momentarily invalid mid-verification")
fixed_ntv = RTCVerificationSim(buggy=False)
fixed_ntv.arm_verification_directly()
resolved = drive_until_resolved(fixed_ntv, lambda s: s.on_response(ntp_time_valid=False))
check("fixed model: NTP-invalid-during-verification releases within the bound", resolved is True and fixed_ntv.correction_in_progress is False)

print("[10] Regression: Modbus exception (on_error) during verification is unaffected by the fix")
for is_buggy in (True, False):
    sim = RTCVerificationSim(buggy=is_buggy)
    sim.arm_verification_directly()
    resolved = drive_until_resolved(sim, lambda s: s.on_error())
    check(
        f"on_error still releases the lock within the bound (buggy={is_buggy})",
        resolved is True and sim.correction_in_progress is False,
    )

print("[11] Regression: Modbus no-response/timeout during verification is unaffected by the fix")
for is_buggy in (True, False):
    sim = RTCVerificationSim(buggy=is_buggy)
    sim.arm_verification_directly()
    resolved = drive_until_resolved(sim, lambda s: s.on_no_response())
    check(
        f"on_no_response still releases the lock within the bound (buggy={is_buggy})",
        resolved is True and sim.correction_in_progress is False,
    )

print("[12] Adversarial: repeated correction attempts - two consecutive invalid verification reads fail closed deterministically")
fixed_repeat = RTCVerificationSim(buggy=False)
fixed_repeat.start_manual_correction()  # correction_attempt = 1
fixed_repeat.tick_1s()  # verification_pending -> verification_read_active
check("verification armed after the write ack", fixed_repeat.verification_read_active is True)
fixed_repeat.on_response(values_valid=False)  # 1st bad verification read
fixed_repeat.tick_1s()  # comm_failure_pending -> retry (attempt 1<2) -> auto_sync -> write ack -> verification_pending
check("first failure queued a bounded retry rather than failing immediately", fixed_repeat.correction_attempt == 2 and fixed_repeat.correction_in_progress is True)
fixed_repeat.tick_1s()  # verification_pending -> verification_read_active (2nd round)
fixed_repeat.on_response(values_valid=False)  # 2nd bad verification read
drive_until_resolved(fixed_repeat, lambda s: s.on_response(values_valid=False))
check(
    "second consecutive failure fails closed (retry budget exhausted) with a cooldown, not a third silent retry",
    fixed_repeat.correction_in_progress is False and fixed_repeat.failed_corrections == 1 and fixed_repeat.cooldown_active is True,
)
check("no corrections were ever counted as verified during this repeated-failure run", fixed_repeat.corrections_since_boot == 0)

print("[13] Interaction: Free Power lease watchdog write guard is unblocked once the fix releases the lock")
fp_sim = RTCVerificationSim(buggy=False)
fp_sim.arm_verification_directly()
check("Free Power watchdog is blocked while a (legitimate) correction is genuinely in progress", fp_sim.free_power_gate_allows_write() is False)
drive_until_resolved(fp_sim, lambda s: s.on_response(values_valid=False))
check("Free Power watchdog write guard is unblocked after the fix releases the lock", fp_sim.free_power_gate_allows_write() is True)

print("[14] Interaction: Dump lease watchdog write guard is unblocked once the fix releases the lock")
dump_sim = RTCVerificationSim(buggy=False)
dump_sim.arm_verification_directly()
check("Dump watchdog is blocked while a (legitimate) correction is genuinely in progress", dump_sim.dump_gate_allows_write() is False)
drive_until_resolved(dump_sim, lambda s: s.on_response(values_valid=False))
check("Dump watchdog write guard is unblocked after the fix releases the lock", dump_sim.dump_gate_allows_write() is True)

print("[15] Reboot-recovery: a reboot still clears a leaked lock regardless of the fix (pre-existing path, now supplemented not replaced)")
rebooted_buggy = RTCVerificationSim(buggy=True)
rebooted_buggy.arm_verification_directly()
rebooted_buggy.on_response(values_valid=False)  # leaks under the buggy model
check("buggy model is indeed leaked before reboot (sanity check)", rebooted_buggy.correction_in_progress is True)
rebooted_buggy.reboot()
check("reboot clears correction_in_progress even under the buggy model", rebooted_buggy.correction_in_progress is False)
check("reboot clears verification_read_active even under the buggy model", rebooted_buggy.verification_read_active is False)

print("[16] No double-release/double-unlock race: a stray duplicate response after release is a no-op")
dup_sim = RTCVerificationSim(buggy=False)
dup_sim.arm_verification_directly()
dup_sim.on_response(values_valid=False)  # releases: verification_read_active=False, comm_failure_pending=True
attempt_after_first = dup_sim.correction_attempt
pending_after_first = dup_sim.comm_failure_pending
dup_sim.on_response(values_valid=False)  # a second, stray call before the 1s tick consumes comm_failure_pending
check(
    "the guard is idempotent: a duplicate call with the lock already released does not touch comm_failure_pending/attempt again",
    dup_sim.correction_attempt == attempt_after_first and dup_sim.comm_failure_pending == pending_after_first,
)

print("[17] Normal successful verification is unchanged by the fix")
for is_buggy in (True, False):
    sim = RTCVerificationSim(buggy=is_buggy)
    sim.arm_verification_directly()
    sim.on_response(values_valid=True, verified_ok=True)
    check(
        f"a valid, in-range, threshold-passing verification read still clears both flags immediately (buggy={is_buggy})",
        sim.correction_in_progress is False and sim.verification_read_active is False and sim.corrections_since_boot == 1,
    )

print("[18] Ordinary, non-verification RTC reads (e.g. the 60s drift-check poll) are unaffected by the fix")
for is_buggy in (True, False):
    sim = RTCVerificationSim(buggy=is_buggy)
    # verification_read_active is false throughout - matches the periodic
    # poll, which only ever fires while `!correction_in_progress` (FW ~17359-17368).
    sim.on_response(values_valid=False)
    check(
        f"an invalid periodic (non-verification) read never touches comm_failure_pending or correction state (buggy={is_buggy})",
        sim.comm_failure_pending is False and sim.correction_in_progress is False and sim.correction_attempt == 0,
    )
    sim.on_response(ntp_synced=False)
    check(
        f"an NTP-unsynced periodic (non-verification) read never touches comm_failure_pending or correction state (buggy={is_buggy})",
        sim.comm_failure_pending is False and sim.correction_in_progress is False,
    )

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All RTC verification lock-leak (S1) tests PASSED.")

print("")
print("These are STRUCTURAL/source-text checks against the real firmware plus a")
print("hand-written Python reference-model simulation of the RTC correction/")
print("verification state machine - they prove the source and the model agree")
print("with the intended fix, not that the compiled firmware behaves this way on")
print("real hardware. See CURRENT_STATE.md for what remains unverified.")

if FAILURES:
    sys.exit(1)
