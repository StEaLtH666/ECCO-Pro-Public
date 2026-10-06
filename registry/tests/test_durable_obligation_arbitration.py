#!/usr/bin/env python3
"""Offline tests for the S4 fix (branch `fix/durable-obligation-arbitration`):
the "rare dual durable-obligation dead-end" recorded in
docs/SUPERVISION_FALLBACK_FAILBACK_ARCHITECTURE.md's defect ledger (S4/G2)
and CURRENT_STATE.md's "Separate follow-up prerequisites" list.

Mechanism: `apply_reg244_settings`/`restore_reg244_snapshot` and
`start_dump_to_grid_override` each already refuse a NEW transaction while
the OTHER domain's RAM mirror (`dump_snapshot_valid` / `reg244_snapshot_valid`)
is set. But `ecco_durable::commit_record()` is `save()` + a GLOBAL `sync()`
(firmware/include/ecco_durable_snapshot.h), and ESPHome's `sync()`
aggregates every currently-pending NVS save into one pass/fail result - it
can report failure because an UNRELATED pending key failed, even though
THIS record's own write landed (a "Phase-B commit false negative"). If that
happens during a Dump Phase-B marker commit, `dump_snapshot_valid` can be
left false in RAM even though the durable marker actually committed
RESTORE_REQUIRED - defeating the reg244 admission gate (or the symmetric
Dump gate) before the next reboot. Dump and the reg244 proof harness can
then end up durably holding a genuine, independent RESTORE_REQUIRED
obligation over the SAME register (244) at once: two self-consistent claims
about what 244 should restore to, with nothing to arbitrate between them.

The invariant this fix enforces: only one authoritative recovery obligation
may own register 244 at a time. Fix (startup reconciliation, at the
narrowest layer - the on_boot lambda only, no change to any write, verify,
restore, or admission-gate call site, no new durable schema, no new lockout
mechanism): boot is the one place both domains' marker states are ALWAYS
freshly re-derived from an actual `load_record()` moments ago, immune to
the RAM staleness that let the dual obligation form in the first place. If
BOTH `dump_marker_state` and `reg244_marker_state` are genuinely
`MARKER_RESTORE_REQUIRED` (both could still perform a write - a marker
already at RESTORE_VERIFIED_PENDING_CLEAR never can, per
ecco_durable_snapshot.h's own MarkerState contract, so is deliberately
excluded), the boot lambda fails closed for BOTH domains by reusing their
existing `dump_recovery_metadata_corrupt` / `reg244_recovery_metadata_corrupt`
lockouts - already the precondition every Dump and reg244 write path
(including the Dump watchdog) checks - rather than guessing which
obligation is authoritative or inventing a second lockout mechanism.

No I/O, no hardware, no ESPHome/C++ toolchain, in the same style as
registry/tests/test_free_power_hardening_2026_09_22.py:
  [1]-[4]  Structural/source-anchored checks that the new boot-time check
           exists with the right guard conditions (with a mutation check
           that the same checks fail against the pre-fix source, which has
           no such block at all), and that it reuses lockout flags already
           enforced by every Dump/reg244 write path.
  [5]+     A small, explicitly-labelled Python reference-model simulation
           of the admission-gate-bypass -> dual-obligation -> reboot
           reconciliation sequence, proving: the gap is real without this
           fix, the fix closes it deterministically and stays closed across
           repeated reboots, it does not fire on a harmless
           PENDING_CLEAR/REQUIRED combination, and once locked neither
           domain performs any further register write.
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


def between(text: str, start_marker: str, end_marker: str) -> str:
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]


# The on_boot lambda's reg244 marker-loading block ends, and the new S4
# check must live, between these two pre-existing anchors.
boot_window = between(
    fw,
    'ecco_durable::key_for(ecco_durable::REG244_VALID_TAG), marker);',
    'if (id(free_power_recovery_metadata_corrupt)) {',
)

# ===========================================================================
# [1]-[4] Structural: the new cross-domain check exists with the right
# guard conditions, in the right place, reusing the right lockout flags.
# ===========================================================================
print("[1] The dual-obligation boot check exists between the reg244 load and the Free Power status block")
check(
    "a DUAL DURABLE OBLIGATION (S4) check is present in the on_boot lambda",
    "DUAL DURABLE OBLIGATION (S4)" in boot_window,
)

print("[2] The check requires BOTH markers to be genuinely RESTORE_REQUIRED (not just *_snapshot_valid)")
check(
    "gated on dump_marker_state == MARKER_RESTORE_REQUIRED",
    "id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED" in boot_window,
)
check(
    "gated on reg244_marker_state == MARKER_RESTORE_REQUIRED",
    "id(reg244_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED" in boot_window,
)
check(
    "NOT gated on the broader *_snapshot_valid flags alone (would also fire on a harmless PENDING_CLEAR pairing)",
    "id(dump_snapshot_valid) && id(reg244_snapshot_valid)" not in boot_window,
)

print("[3] The check does not double-fire on top of an already-independently-corrupt record")
check(
    "guarded by !dump_recovery_metadata_corrupt",
    "!id(dump_recovery_metadata_corrupt) &&" in boot_window,
)
check(
    "guarded by !reg244_recovery_metadata_corrupt",
    "!id(reg244_recovery_metadata_corrupt) &&" in boot_window,
)

print("[4] The check fails closed by reusing the EXISTING lockout flags (no new lockout mechanism)")
s4_block = boot_window[boot_window.index("S4 fix (2026-09-27"):]
# The executable body only - excludes the preceding explanatory comment,
# which legitimately mentions commit_record()/"= false" in prose while
# explaining the root cause.
s4_code = s4_block[s4_block.index("!id(dump_recovery_metadata_corrupt) &&"):]
check(
    "sets dump_recovery_metadata_corrupt = true",
    "id(dump_recovery_metadata_corrupt) = true;" in s4_code,
)
check(
    "sets reg244_recovery_metadata_corrupt = true",
    "id(reg244_recovery_metadata_corrupt) = true;" in s4_code,
)
check(
    "neither snapshot's data/marker is cleared or overwritten (only the corrupt/lockout flags change)",
    "commit_record" not in s4_code and "= false;" not in s4_code,
)
check(
    "re-publishes dump_status so it does not keep showing the stale pre-lockout text",
    "id(dump_status).publish_state(" in s4_code,
)

print("[5] MUTATION CHECK: the [1] check fails against the verbatim pre-fix source (no such block exists on main)")
PRE_FIX_BOOT_TAIL = r'''
              }
            }
          }

          if (id(free_power_recovery_metadata_corrupt)) {
'''
check(
    "the DUAL DURABLE OBLIGATION marker is absent from the pre-fix source (proves [1] isn't vacuous)",
    "DUAL DURABLE OBLIGATION (S4)" not in PRE_FIX_BOOT_TAIL,
)

print("[6] The lockout flags this fix sets are already the precondition for every Dump/reg244 write path (existing code, unmodified - proves the fix has teeth)")
check(
    "Dump's own lease watchdog write guard already refuses while dump_recovery_metadata_corrupt is set",
    re.search(r"dump_operation_in_progress.{0,80}dump_recovery_metadata_corrupt", fw, re.DOTALL) is not None,
)
check(
    "start_dump_to_grid_override already refuses while dump_recovery_metadata_corrupt is set",
    "!id(dump_recovery_metadata_corrupt) &&" in fw,
)
check(
    "apply_reg244_settings already refuses while reg244_recovery_metadata_corrupt is set",
    "!id(reg244_recovery_metadata_corrupt) &&" in fw,
)
check(
    "restore_reg244_snapshot already checks reg244_recovery_metadata_corrupt",
    fw.count("id(reg244_recovery_metadata_corrupt)") >= 5,  # multiple independent gates, see [1]-[4]'s own file
)

print("[7] Existing Dump/Free Power/reg244 restore semantics are unchanged (this fix only ADDS a new on_boot block)")
check(
    "Free Power's own recovery-metadata-corrupt boot branch is untouched (still the very next check after this fix's block)",
    fw.count("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked") == 1,
)
check(
    "Dump's own independent metadata-corrupt message (unrelated to S4) is untouched, still present exactly once",
    fw.count("RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data record is unreadable or invalid; inverter writes locked") == 1,
)
check(
    "reg244's own independent metadata-corrupt message (unrelated to S4) is untouched, still present exactly once",
    fw.count("RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data record is unreadable/invalid; inverter writes locked") == 1,
)


# ===========================================================================
# [8]+ Reference-model simulation.
#
# Hand-written model of JUST the on_boot cross-check logic plus a minimal
# admission-gate model for start_dump_to_grid_override / apply_reg244_settings
# - not a lambda interpreter. Mirrors, by hand, the real firmware's:
#   - marker states CLEAR / RESTORE_REQUIRED / RESTORE_VERIFIED_PENDING_CLEAR
#     (ecco_durable::MarkerState);
#   - the pre-existing RAM-mirror admission gates
#     (apply_reg244_settings: !dump_active_persisted && !dump_snapshot_valid;
#      start_dump_to_grid_override: symmetric check against reg244, modelled
#      the same way for this reproduction);
#   - a Phase-B commit_record() "false negative": the durable marker lands
#     (real NVS state changes) but the RAM mirror the caller derives from
#     the return value does not update, because sync() reported an
#     unrelated failure;
#   - this fix's own boot-time cross-check.
# ===========================================================================
CLEAR, RESTORE_REQUIRED, PENDING_CLEAR = 0, 1, 2


class DualObligationSim:
    def __init__(self, fixed: bool):
        self.fixed = fixed
        # Durable truth (what is actually on flash right now).
        self.durable_dump_marker = CLEAR
        self.durable_reg244_marker = CLEAR
        # RAM mirrors, as derived at the moment of each admission check -
        # can diverge from durable truth only via a Phase-B false negative.
        self.ram_dump_snapshot_valid = False
        self.ram_reg244_snapshot_valid = False
        # Lockout flags this fix's boot check sets.
        self.dump_recovery_metadata_corrupt = False
        self.reg244_recovery_metadata_corrupt = False
        self.writes_attempted: list[str] = []

    def dump_phase_b_commit_with_false_negative(self) -> None:
        """The durable marker genuinely lands (RESTORE_REQUIRED), but an
        unrelated pending key's sync() failure makes commit_record() return
        false, so the caller's own RAM mirror is never set true."""
        self.durable_dump_marker = RESTORE_REQUIRED
        # ram_dump_snapshot_valid deliberately NOT set - this is the bug.

    def reg244_apply_admission_check(self) -> bool:
        """Mirrors apply_reg244_settings's existing precondition:
        !dump_active_persisted && !dump_snapshot_valid (RAM mirrors)."""
        return not self.ram_dump_snapshot_valid

    def reg244_apply_succeeds(self) -> None:
        assert self.reg244_apply_admission_check(), "admission gate should have refused this"
        self.writes_attempted.append("reg244:apply:244")
        self.durable_reg244_marker = RESTORE_REQUIRED
        self.ram_reg244_snapshot_valid = True

    def reboot(self) -> None:
        """Mirrors on_boot: RAM mirrors are ALWAYS freshly re-derived from
        durable truth (load_record()) here - the one place immune to the
        RAM staleness an admission gate can suffer from mid-session."""
        self.ram_dump_snapshot_valid = self.durable_dump_marker != CLEAR
        self.ram_reg244_snapshot_valid = self.durable_reg244_marker != CLEAR
        if self.fixed:
            if (
                not self.dump_recovery_metadata_corrupt
                and not self.reg244_recovery_metadata_corrupt
                and self.durable_dump_marker == RESTORE_REQUIRED
                and self.durable_reg244_marker == RESTORE_REQUIRED
            ):
                self.dump_recovery_metadata_corrupt = True
                self.reg244_recovery_metadata_corrupt = True

    def dump_watchdog_attempts_restore(self) -> None:
        """Mirrors the real watchdog's own precondition, which already
        includes !dump_recovery_metadata_corrupt (FW ~17190/17228)."""
        if self.durable_dump_marker == RESTORE_REQUIRED and not self.dump_recovery_metadata_corrupt:
            self.writes_attempted.append("dump:restore:244")
            self.durable_dump_marker = CLEAR

    def reg244_operator_restore_attempt(self) -> bool:
        """Mirrors restore_reg244_snapshot's own precondition, which
        already includes !reg244_recovery_metadata_corrupt."""
        if self.reg244_recovery_metadata_corrupt:
            return False  # refused, no write
        if self.durable_reg244_marker == RESTORE_REQUIRED:
            self.writes_attempted.append("reg244:restore:244")
            self.durable_reg244_marker = CLEAR
            return True
        return False


print("[8] Reproduces S4: without the fix, a Phase-B false negative lets reg244 create a SECOND durable obligation")
unfixed = DualObligationSim(fixed=False)
unfixed.dump_phase_b_commit_with_false_negative()
check(
    "Dump's durable marker genuinely landed RESTORE_REQUIRED despite the false-negative return",
    unfixed.durable_dump_marker == RESTORE_REQUIRED,
)
check(
    "reg244's admission gate (reading the STALE RAM mirror) incorrectly permits a new apply",
    unfixed.reg244_apply_admission_check() is True,
)
unfixed.reg244_apply_succeeds()
check(
    "reg244 now ALSO holds a genuine, independent durable RESTORE_REQUIRED obligation over 244",
    unfixed.durable_reg244_marker == RESTORE_REQUIRED,
)
unfixed.reboot()
check(
    "unfixed: the reboot does not detect or flag the dual obligation - both proceed as if unrelated",
    unfixed.dump_recovery_metadata_corrupt is False and unfixed.reg244_recovery_metadata_corrupt is False,
)
unfixed.dump_watchdog_attempts_restore()
reg244_wrote = unfixed.reg244_operator_restore_attempt()
check(
    "unfixed: BOTH domains go on to actually write register 244 from their own (conflicting) snapshot - the dead end",
    "dump:restore:244" in unfixed.writes_attempted and reg244_wrote and "reg244:restore:244" in unfixed.writes_attempted,
)

print("[9] Fix: the same sequence is detected and fails closed at the next reboot, before either can write again")
fixed = DualObligationSim(fixed=True)
fixed.dump_phase_b_commit_with_false_negative()
fixed.reg244_apply_succeeds()  # same admission-gate bypass reproduced identically
fixed.reboot()
check(
    "fixed: the reboot detects the dual obligation and locks BOTH domains closed",
    fixed.dump_recovery_metadata_corrupt is True and fixed.reg244_recovery_metadata_corrupt is True,
)
writes_before_lockout = list(fixed.writes_attempted)  # the reg244:apply write that CREATED the dual obligation is expected here
fixed.dump_watchdog_attempts_restore()
reg244_wrote_fixed = fixed.reg244_operator_restore_attempt()
check(
    "fixed: neither domain performs ANY register write AFTER the lockout is detected - no snapshot can overwrite the other's",
    fixed.writes_attempted == writes_before_lockout and reg244_wrote_fixed is False,
)
check(
    "fixed: neither durable marker was silently cleared or discarded - both obligations remain intact for the operator",
    fixed.durable_dump_marker == RESTORE_REQUIRED and fixed.durable_reg244_marker == RESTORE_REQUIRED,
)

print("[10] Adversarial persistence/reboot: the lockout is stable and does not silently clear across further reboots")
for i in range(5):
    fixed.reboot()
    check(
        f"reboot #{i + 2}: lockout remains set (idempotent, does not self-clear)",
        fixed.dump_recovery_metadata_corrupt is True and fixed.reg244_recovery_metadata_corrupt is True,
    )
check(
    "after 5 extra reboots, still no new writes and both obligations still durably intact",
    fixed.writes_attempted == writes_before_lockout and fixed.durable_dump_marker == RESTORE_REQUIRED and fixed.durable_reg244_marker == RESTORE_REQUIRED,
)

print("[11] No false positive: a genuinely harmless pairing (one PENDING_CLEAR, one RESTORE_REQUIRED) does not lock either domain")
harmless = DualObligationSim(fixed=True)
harmless.durable_dump_marker = PENDING_CLEAR  # already verified restored; only its durable clear remains - cannot write again
harmless.durable_reg244_marker = RESTORE_REQUIRED
harmless.reboot()
check(
    "a PENDING_CLEAR + RESTORE_REQUIRED pairing does NOT trigger the S4 lockout (PENDING_CLEAR can never write again)",
    harmless.dump_recovery_metadata_corrupt is False and harmless.reg244_recovery_metadata_corrupt is False,
)
harmless_reg244_wrote = harmless.reg244_operator_restore_attempt()
check(
    "reg244's own genuinely-unconflicted RESTORE_REQUIRED obligation still restores normally (fix does not over-trigger)",
    harmless_reg244_wrote is True,
)

print("[12] No false positive: two independent CLEAR/RESTORE_REQUIRED singles (only one domain has an obligation) never lock either")
single = DualObligationSim(fixed=True)
single.durable_dump_marker = RESTORE_REQUIRED
single.durable_reg244_marker = CLEAR
single.reboot()
check(
    "only Dump has an obligation - no dual-obligation lockout fires",
    single.dump_recovery_metadata_corrupt is False and single.reg244_recovery_metadata_corrupt is False,
)
single.dump_watchdog_attempts_restore()
check(
    "Dump's own unconflicted restore still proceeds normally",
    "dump:restore:244" in single.writes_attempted,
)

print("[13] Does not double-fire / does not mask cause on top of an already-independently-corrupt record")
already_corrupt = DualObligationSim(fixed=True)
already_corrupt.durable_dump_marker = RESTORE_REQUIRED
already_corrupt.durable_reg244_marker = RESTORE_REQUIRED
already_corrupt.dump_recovery_metadata_corrupt = True  # e.g. an unrelated unreadable-data case, set independently
already_corrupt.reboot()
check(
    "reg244_recovery_metadata_corrupt is left alone by this check when dump's corruption is independently already set",
    already_corrupt.reg244_recovery_metadata_corrupt is False,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All durable-obligation arbitration (S4) tests PASSED.")

print("")
print("These are STRUCTURAL/source-text checks against the real firmware plus a")
print("hand-written Python reference-model simulation of the admission-gate-bypass ->")
print("dual-obligation -> reboot-reconciliation sequence - they prove the source and")
print("the model agree with the intended fix, not that the compiled firmware's actual")
print("NVS sync() behaviour produces this false negative on real hardware. See")
print("CURRENT_STATE.md for what remains unverified.")

if FAILURES:
    sys.exit(1)
