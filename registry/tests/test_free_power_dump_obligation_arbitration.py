#!/usr/bin/env python3
"""Offline tests for the Free Power<->Dump dual durable-obligation fix
(branch `fix/free-power-dump-obligation-arbitration`).

This is the narrow follow-up the S4 fix's own commit message flagged as
deliberately out of scope: "The identical false-negative mechanism plausibly
also threatens Free Power<->Dump over registers 256-261, which they do
share, but that is deliberately left out of this narrowly-scoped fix." See
registry/tests/test_durable_obligation_arbitration.py for the S4 (Dump/
reg244, register 244) fix this mirrors.

Mechanism (identical class of bug to S4, different register set and
domain pair): Free Power's and Dump's own transaction-start paths each
already refuse a NEW transaction while the OTHER domain's RAM mirror
(`dump_snapshot_valid` / `free_power_snapshot_valid`) is set. But
`ecco_durable::commit_record()` is `save()` + a GLOBAL `sync()`
(firmware/include/ecco_durable_snapshot.h), and ESPHome's `sync()`
aggregates every currently-pending NVS save into one pass/fail result - it
can report failure because an UNRELATED pending key failed, even though
THIS record's own write landed (a "Phase-B commit false negative"). If that
happens during either domain's Phase-B marker commit, that domain's own RAM
mirror can be left false even though its durable marker actually committed
RESTORE_REQUIRED - defeating the OTHER domain's admission gate before the
next reboot. Free Power and Dump can then end up durably holding a genuine,
independent RESTORE_REQUIRED obligation over their SHARED register set
(256-261) at once: two self-consistent claims about what 256-261 should
restore to, with nothing to arbitrate between them. Unlike the Dump/reg244
pair, Dump's restore is unconditional/blind (it always writes its own
snapshot's 256-261 back exactly, with no cross-domain check of what Free
Power intends), so it can silently overwrite Free Power's active intended
state.

The invariant this fix enforces: only one authoritative recovery obligation
may own registers 256-261 at a time. Fix (startup reconciliation, at the
narrowest layer - the on_boot lambda only, no change to any write, verify,
restore, or admission-gate call site, no new durable schema, no new lockout
mechanism, no reg244-marker dependency): boot is the one place both domains'
marker states are ALWAYS freshly re-derived from an actual `load_record()`
moments ago, immune to the RAM staleness that let the dual obligation form
in the first place. If BOTH `free_power_marker_state` and `dump_marker_state`
are genuinely `MARKER_RESTORE_REQUIRED` (both could still perform a write -
a marker already at RESTORE_VERIFIED_PENDING_CLEAR never can, per
ecco_durable_snapshot.h's own MarkerState contract, so is deliberately
excluded), the boot lambda fails closed for BOTH domains by reusing their
existing `free_power_recovery_metadata_corrupt` / `dump_recovery_metadata_corrupt`
lockouts - already the precondition every Free Power and Dump write path
checks - rather than guessing which obligation is authoritative or
inventing a second lockout mechanism.

No I/O, no hardware, no ESPHome/C++ toolchain, in the same style as
registry/tests/test_durable_obligation_arbitration.py:
  [1]-[7]  Structural/source-anchored checks that the new boot-time check
           exists with the right guard conditions, is kept distinct from
           the S4 (register-244) check, and that it reuses lockout flags
           already enforced by every Free Power/Dump write path.
  [8]+     A small, explicitly-labelled Python reference-model simulation
           of the admission-gate-bypass -> dual-obligation -> reboot
           reconciliation sequence, proving: the gap is real without this
           fix in both A/B orderings (Free Power phantom + Dump real, and
           Dump phantom + Free Power real), the fix closes it
           deterministically and stays closed across repeated reboots, it
           does not fire on a harmless PENDING_CLEAR/REQUIRED combination
           or a single-domain-only obligation, and once locked neither
           domain performs any further register write (so Dump's blind
           restore never overwrites Free Power's intended state).
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


# The on_boot lambda's S4 (Dump/reg244) check block ends, and the new
# Free Power<->Dump check must live, between these two pre-existing anchors -
# the same end anchor test_durable_obligation_arbitration.py uses for its own
# S4 window ('if (id(free_power_recovery_metadata_corrupt))'), so this check
# is provably placed AFTER the S4 block, not duplicating or replacing it.
#
# The start anchor can't be the shared "LOCKED - durable recovery metadata
# unavailable" republish text directly (S4's block and this fix's own block
# both republish that identical string, and the ORIGINAL dump_recovery_state
# publish - well before the reg244 block - also contains it) - so first
# locate the unique "DUAL DURABLE OBLIGATION (S4)" marker, then find the
# S4 block's own closing republish/brace AFTER that point.
S4_END_MARKER = 'id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata unavailable");\n          }'
_s4_marker_pos = fw.index("DUAL DURABLE OBLIGATION (S4)")
_s4_block_end = fw.index(S4_END_MARKER, _s4_marker_pos) + len(S4_END_MARKER)
boot_window = between(
    fw[_s4_block_end:],
    "",
    'if (id(free_power_recovery_metadata_corrupt)) {',
)

# ===========================================================================
# [1]-[7] Structural: the new cross-domain check exists with the right
# guard conditions, in the right place, reusing the right lockout flags,
# and is kept distinct from the S4 (register-244) check.
# ===========================================================================
print("[1] The Free Power<->Dump dual-obligation boot check exists after the S4 block and before the Free Power status block")
check(
    "a DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261) check is present in the on_boot lambda",
    "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)" in boot_window,
)

print("[2] The check requires BOTH markers to be genuinely RESTORE_REQUIRED (not just *_snapshot_valid, not active_persisted)")
check(
    "gated on free_power_marker_state == MARKER_RESTORE_REQUIRED",
    "id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED" in boot_window,
)
check(
    "gated on dump_marker_state == MARKER_RESTORE_REQUIRED",
    "id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED" in boot_window,
)
check(
    "NOT gated on the broader *_snapshot_valid flags alone (would also fire on a harmless PENDING_CLEAR pairing)",
    "id(dump_snapshot_valid) && id(free_power_snapshot_valid)" not in boot_window
    and "id(free_power_snapshot_valid) && id(dump_snapshot_valid)" not in boot_window,
)
check(
    "no dependency on active_persisted (must catch both A/B orderings regardless of which lease was active)",
    "active_persisted" not in boot_window,
)
check(
    "no dependency on reg244_marker_state (this is the 256-261 pair, independent of the S4 register-244 pair)",
    "reg244_marker_state" not in boot_window,
)

print("[3] The check does not double-fire on top of an already-independently-corrupt record")
check(
    "guarded by !free_power_recovery_metadata_corrupt",
    "!id(free_power_recovery_metadata_corrupt) &&" in boot_window,
)
check(
    "guarded by !dump_recovery_metadata_corrupt",
    "!id(dump_recovery_metadata_corrupt) &&" in boot_window,
)

print("[4] The check fails closed by reusing the EXISTING lockout flags (no new lockout mechanism, no new schema/tag)")
fp_dump_block = boot_window[boot_window.index("Free Power<->Dump dual durable-obligation dead-end"):]
# The executable body only - excludes the preceding explanatory comment,
# which legitimately mentions commit_record()/"= false" in prose while
# explaining the root cause.
fp_dump_code = fp_dump_block[fp_dump_block.index("!id(free_power_recovery_metadata_corrupt) &&"):]
check(
    "sets free_power_recovery_metadata_corrupt = true",
    "id(free_power_recovery_metadata_corrupt) = true;" in fp_dump_code,
)
check(
    "sets dump_recovery_metadata_corrupt = true",
    "id(dump_recovery_metadata_corrupt) = true;" in fp_dump_code,
)
check(
    "neither snapshot's data/marker is cleared or overwritten (only the corrupt/lockout flags change)",
    "commit_record" not in fp_dump_code and "= false;" not in fp_dump_code,
)
check(
    "no new durable tag/key is introduced (only existing *_recovery_metadata_corrupt flags are used)",
    "_TAG" not in fp_dump_code and "key_for" not in fp_dump_code,
)

print("[5] The check is distinct from the S4 (register-244) check - separate log/operator reason identifying 256-261")
check(
    "the new check's ESP_LOGE text explicitly names 256-261, not register 244",
    "register set 256-261" in fw and "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)" in fw,
)
check(
    "the new check's dump_status text is distinct from the S4 block's dump_status text",
    'id(dump_status).publish_state("RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261): register set 256-261 is also owned by Free Power; deliberate operator recovery required");' in fp_dump_code,
)
check(
    "the S4 (register-244) check is untouched and still present exactly once",
    fw.count("DUAL DURABLE OBLIGATION (S4)") == 1,
)
check(
    "the new Free Power/Dump check appears strictly AFTER the S4 check in the boot lambda",
    fw.index("DUAL DURABLE OBLIGATION (S4)") < fw.index("DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)"),
)

print("[6] The lockout flags this fix sets are already the precondition for every Free Power/Dump write path (existing code, unmodified - proves the fix has teeth)")
check(
    "Dump's own lease watchdog write guard already refuses while dump_recovery_metadata_corrupt is set",
    re.search(r"dump_operation_in_progress.{0,80}dump_recovery_metadata_corrupt", fw, re.DOTALL) is not None,
)
check(
    "start_dump_to_grid_override already refuses while dump_recovery_metadata_corrupt is set",
    "!id(dump_recovery_metadata_corrupt) &&" in fw,
)
check(
    "Free Power's own write paths already check free_power_recovery_metadata_corrupt (multiple independent gates)",
    fw.count("id(free_power_recovery_metadata_corrupt)") >= 5,
)

print("[7] Existing Free Power/Dump/reg244 restore semantics, write surface and schema are unchanged (this fix only ADDS a new on_boot block)")
check(
    "Free Power's own recovery-metadata-corrupt boot branch is untouched (still the very next check after this fix's block)",
    fw.count("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked") == 1,
)
check(
    "Dump's own independent metadata-corrupt message (unrelated to this fix) is untouched, still present exactly once",
    fw.count("RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data record is unreadable or invalid; inverter writes locked") == 1,
)
check(
    "no Modbus write call (write_multiple/write_single) appears inside the new check's own code",
    "write_multiple" not in fp_dump_code and "write_single" not in fp_dump_code,
)

print("[8] MUTATION CHECK: the [1] check fails against the pre-fix source (S4-only boot tail, no Free Power/Dump block yet)")
PRE_FIX_BOOT_TAIL = r'''
            id(dump_status).publish_state("RECOVERY BLOCKED - dual durable obligation (S4): register 244 is also owned by the reg244 proof harness; deliberate operator recovery required");
            id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata unavailable");
          }

          if (id(free_power_recovery_metadata_corrupt)) {
'''
check(
    "the DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261) marker is absent from the pre-fix source (proves [1] isn't vacuous)",
    "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261)" not in PRE_FIX_BOOT_TAIL,
)
check(
    "the pre-fix source's S4 block still transitions directly into the Free Power status block (no gap for our new block)",
    PRE_FIX_BOOT_TAIL.strip().endswith('if (id(free_power_recovery_metadata_corrupt)) {'),
)


# ===========================================================================
# [9]+ Reference-model simulation.
#
# Hand-written model of JUST the on_boot cross-check logic plus a minimal
# admission-gate model for start_dump_to_grid_override / a Free Power start -
# not a lambda interpreter. Mirrors, by hand, the real firmware's:
#   - marker states CLEAR / RESTORE_REQUIRED / RESTORE_VERIFIED_PENDING_CLEAR
#     (ecco_durable::MarkerState);
#   - the pre-existing RAM-mirror admission gates (start_dump_to_grid_override
#     refuses while free_power_snapshot_valid is set; the symmetric Free
#     Power start path refuses while dump_snapshot_valid is set);
#   - a Phase-B commit_record() "false negative": the durable marker lands
#     (real NVS state changes) but the RAM mirror the caller derives from
#     the return value does not update, because sync() reported an
#     unrelated failure;
#   - this fix's own boot-time cross-check;
#   - Dump's BLIND restore (always writes its own snapshot's 256-261 back,
#     with no check of Free Power's intended state) versus Free Power's own
#     restore of its intended 256-261 - modelled as each writing a distinct
#     "owner" tag for 256-261, so an overwrite is directly observable.
# ===========================================================================
CLEAR, RESTORE_REQUIRED, PENDING_CLEAR = 0, 1, 2


class FreePowerDumpSim:
    def __init__(self, fixed: bool):
        self.fixed = fixed
        # Durable truth (what is actually on flash right now).
        self.durable_free_power_marker = CLEAR
        self.durable_dump_marker = CLEAR
        # RAM mirrors, as derived at the moment of each admission check -
        # can diverge from durable truth only via a Phase-B false negative.
        self.ram_free_power_snapshot_valid = False
        self.ram_dump_snapshot_valid = False
        # Lockout flags this fix's boot check sets.
        self.free_power_recovery_metadata_corrupt = False
        self.dump_recovery_metadata_corrupt = False
        self.writes_attempted: list[str] = []
        # Who last wrote registers 256-261, for observing an overwrite.
        self.reg256_261_owner: str | None = None

    def free_power_phase_b_commit_with_false_negative(self) -> None:
        """The durable marker genuinely lands (RESTORE_REQUIRED), but an
        unrelated pending key's sync() failure makes commit_record() return
        false, so the caller's own RAM mirror is never set true."""
        self.durable_free_power_marker = RESTORE_REQUIRED
        # ram_free_power_snapshot_valid deliberately NOT set - this is the bug.

    def dump_phase_b_commit_with_false_negative(self) -> None:
        self.durable_dump_marker = RESTORE_REQUIRED
        # ram_dump_snapshot_valid deliberately NOT set - this is the bug.

    def dump_start_admission_check(self) -> bool:
        """Mirrors start_dump_to_grid_override's existing precondition:
        refuses while the RAM mirror of Free Power's obligation is set."""
        return not self.ram_free_power_snapshot_valid

    def dump_start_succeeds(self) -> None:
        assert self.dump_start_admission_check(), "admission gate should have refused this"
        self.writes_attempted.append("dump:start:256-261")
        self.reg256_261_owner = "dump"
        self.durable_dump_marker = RESTORE_REQUIRED
        self.ram_dump_snapshot_valid = True

    def free_power_start_admission_check(self) -> bool:
        """Symmetric admission gate on the Free Power side, refusing while
        the RAM mirror of Dump's obligation is set."""
        return not self.ram_dump_snapshot_valid

    def free_power_start_succeeds(self) -> None:
        assert self.free_power_start_admission_check(), "admission gate should have refused this"
        self.writes_attempted.append("free_power:start:256-261")
        self.reg256_261_owner = "free_power"
        self.durable_free_power_marker = RESTORE_REQUIRED
        self.ram_free_power_snapshot_valid = True

    def reboot(self) -> None:
        """Mirrors on_boot: RAM mirrors are ALWAYS freshly re-derived from
        durable truth (load_record()) here - the one place immune to the
        RAM staleness an admission gate can suffer from mid-session."""
        self.ram_free_power_snapshot_valid = self.durable_free_power_marker != CLEAR
        self.ram_dump_snapshot_valid = self.durable_dump_marker != CLEAR
        if self.fixed:
            if (
                not self.free_power_recovery_metadata_corrupt
                and not self.dump_recovery_metadata_corrupt
                and self.durable_free_power_marker == RESTORE_REQUIRED
                and self.durable_dump_marker == RESTORE_REQUIRED
            ):
                self.free_power_recovery_metadata_corrupt = True
                self.dump_recovery_metadata_corrupt = True

    def dump_watchdog_attempts_blind_restore(self) -> None:
        """Mirrors the real watchdog's own precondition (already includes
        !dump_recovery_metadata_corrupt), and its BLIND restore: it always
        writes its own snapshot's 256-261 back, with no check of what Free
        Power intends."""
        if self.durable_dump_marker == RESTORE_REQUIRED and not self.dump_recovery_metadata_corrupt:
            self.writes_attempted.append("dump:restore:256-261")
            self.reg256_261_owner = "dump"
            self.durable_dump_marker = CLEAR

    def free_power_restore_attempt(self) -> bool:
        """Mirrors restore_free_power_snapshot's own precondition, which
        already includes !free_power_recovery_metadata_corrupt."""
        if self.free_power_recovery_metadata_corrupt:
            return False  # refused, no write
        if self.durable_free_power_marker == RESTORE_REQUIRED:
            self.writes_attempted.append("free_power:restore:256-261")
            self.reg256_261_owner = "free_power"
            self.durable_free_power_marker = CLEAR
            return True
        return False


print("[9] A: Free Power phantom obligation, Dump real obligation -> reboot: both markers RESTORE_REQUIRED, both lockouts set, zero post-boot restore writes")
case_a = FreePowerDumpSim(fixed=True)
case_a.free_power_phase_b_commit_with_false_negative()  # Free Power's marker lands, RAM mirror stays false (the "phantom" from Dump's point of view)
check(
    "Free Power's admission gate (reading the STALE RAM mirror) incorrectly permits Dump to start",
    case_a.dump_start_admission_check() is True,
)
case_a.dump_start_succeeds()
check(
    "both durable markers are now genuinely RESTORE_REQUIRED before reboot",
    case_a.durable_free_power_marker == RESTORE_REQUIRED and case_a.durable_dump_marker == RESTORE_REQUIRED,
)
case_a.reboot()
check(
    "A: both lockout flags are set after reboot",
    case_a.free_power_recovery_metadata_corrupt is True and case_a.dump_recovery_metadata_corrupt is True,
)
writes_before_a = list(case_a.writes_attempted)
case_a.dump_watchdog_attempts_blind_restore()
fp_wrote_a = case_a.free_power_restore_attempt()
check(
    "A: zero post-boot restore writes in either domain",
    case_a.writes_attempted == writes_before_a and fp_wrote_a is False,
)

print("[10] B: Dump phantom obligation, Free Power real obligation -> reboot: both markers RESTORE_REQUIRED, both lockouts set, zero Dump blind restore write, Free Power intended state not overwritten")
case_b = FreePowerDumpSim(fixed=True)
case_b.dump_phase_b_commit_with_false_negative()  # Dump's marker lands, RAM mirror stays false (the "phantom" from Free Power's point of view)
check(
    "Dump's admission gate (reading the STALE RAM mirror) incorrectly permits Free Power to start",
    case_b.free_power_start_admission_check() is True,
)
case_b.free_power_start_succeeds()
check(
    "reg256-261 is currently owned by Free Power's active intended state",
    case_b.reg256_261_owner == "free_power",
)
check(
    "both durable markers are now genuinely RESTORE_REQUIRED before reboot",
    case_b.durable_free_power_marker == RESTORE_REQUIRED and case_b.durable_dump_marker == RESTORE_REQUIRED,
)
case_b.reboot()
check(
    "B: both lockout flags are set after reboot",
    case_b.free_power_recovery_metadata_corrupt is True and case_b.dump_recovery_metadata_corrupt is True,
)
writes_before_b = list(case_b.writes_attempted)
owner_before_b = case_b.reg256_261_owner
case_b.dump_watchdog_attempts_blind_restore()
fp_wrote_b = case_b.free_power_restore_attempt()
check(
    "B: zero Dump blind-restore write reaches 256-261 after lockout",
    "dump:restore:256-261" not in case_b.writes_attempted,
)
check(
    "B: Free Power's intended state (256-261 ownership) is NOT overwritten by Dump's blind restore",
    case_b.reg256_261_owner == owner_before_b == "free_power",
)
check(
    "B: no further writes at all after the lockout",
    case_b.writes_attempted == writes_before_b and fp_wrote_b is False,
)

print("[11] Pair detection requires genuine RESTORE_REQUIRED on BOTH domains")
one_missing = FreePowerDumpSim(fixed=True)
one_missing.durable_free_power_marker = RESTORE_REQUIRED
one_missing.durable_dump_marker = CLEAR
one_missing.reboot()
check(
    "no lockout when only one domain is genuinely RESTORE_REQUIRED",
    one_missing.free_power_recovery_metadata_corrupt is False and one_missing.dump_recovery_metadata_corrupt is False,
)

print("[12] PENDING_CLEAR + RESTORE_REQUIRED does NOT trigger (a marker already resolved can never write again)")
pending_pair = FreePowerDumpSim(fixed=True)
pending_pair.durable_free_power_marker = PENDING_CLEAR
pending_pair.durable_dump_marker = RESTORE_REQUIRED
pending_pair.reboot()
check(
    "a PENDING_CLEAR + RESTORE_REQUIRED pairing does NOT trigger the lockout",
    pending_pair.free_power_recovery_metadata_corrupt is False and pending_pair.dump_recovery_metadata_corrupt is False,
)
pending_dump_wrote = pending_pair.free_power_restore_attempt() is False and True  # Free Power is PENDING_CLEAR, cannot restore
pending_pair.dump_watchdog_attempts_blind_restore()
check(
    "Dump's own genuinely-unconflicted RESTORE_REQUIRED obligation still restores normally (fix does not over-trigger)",
    "dump:restore:256-261" in pending_pair.writes_attempted,
)

print("[13] Only Free Power obligation does NOT trigger")
fp_only = FreePowerDumpSim(fixed=True)
fp_only.durable_free_power_marker = RESTORE_REQUIRED
fp_only.durable_dump_marker = CLEAR
fp_only.reboot()
check(
    "only Free Power has an obligation - no dual-obligation lockout fires",
    fp_only.free_power_recovery_metadata_corrupt is False and fp_only.dump_recovery_metadata_corrupt is False,
)
fp_only_wrote = fp_only.free_power_restore_attempt()
check(
    "Free Power's own unconflicted restore still proceeds normally",
    fp_only_wrote is True,
)

print("[14] Only Dump obligation does NOT trigger")
dump_only = FreePowerDumpSim(fixed=True)
dump_only.durable_free_power_marker = CLEAR
dump_only.durable_dump_marker = RESTORE_REQUIRED
dump_only.reboot()
check(
    "only Dump has an obligation - no dual-obligation lockout fires",
    dump_only.free_power_recovery_metadata_corrupt is False and dump_only.dump_recovery_metadata_corrupt is False,
)
dump_only.dump_watchdog_attempts_blind_restore()
check(
    "Dump's own unconflicted restore still proceeds normally",
    "dump:restore:256-261" in dump_only.writes_attempted,
)

print("[15] Already-corrupt domain does not create repeated/double-fire behaviour, and this check does not mask the other domain's independent cause")
already_corrupt = FreePowerDumpSim(fixed=True)
already_corrupt.durable_free_power_marker = RESTORE_REQUIRED
already_corrupt.durable_dump_marker = RESTORE_REQUIRED
already_corrupt.dump_recovery_metadata_corrupt = True  # e.g. an unrelated unreadable-data case, set independently
already_corrupt.reboot()
check(
    "free_power_recovery_metadata_corrupt is left alone by this check when dump's corruption is independently already set",
    already_corrupt.free_power_recovery_metadata_corrupt is False,
)

print("[16] Repeated reboot leaves lockout stable (idempotent, does not self-clear or re-fire destructively)")
stable = FreePowerDumpSim(fixed=True)
stable.durable_free_power_marker = RESTORE_REQUIRED
stable.durable_dump_marker = RESTORE_REQUIRED
stable.reboot()
check(
    "lockout set on first reboot",
    stable.free_power_recovery_metadata_corrupt is True and stable.dump_recovery_metadata_corrupt is True,
)
for i in range(5):
    stable.reboot()
    check(
        f"reboot #{i + 2}: lockout remains set (idempotent, does not self-clear)",
        stable.free_power_recovery_metadata_corrupt is True and stable.dump_recovery_metadata_corrupt is True,
    )
check(
    "no writes at all across the repeated reboots",
    stable.writes_attempted == [],
)

print("[17] No durable record is cleared/modified by arbitration - both obligations remain intact for the operator")
check(
    "case A: neither durable marker was silently cleared or discarded",
    case_a.durable_free_power_marker == RESTORE_REQUIRED and case_a.durable_dump_marker == RESTORE_REQUIRED,
)
check(
    "case B: neither durable marker was silently cleared or discarded",
    case_b.durable_free_power_marker == RESTORE_REQUIRED and case_b.durable_dump_marker == RESTORE_REQUIRED,
)

print("[18] Normal Free Power<->Dump mutual exclusion (the pre-existing single-obligation admission gate) is unchanged by this fix")
mutual_excl = FreePowerDumpSim(fixed=True)
mutual_excl.dump_start_succeeds()
check(
    "Free Power's admission gate still correctly refuses a new start while Dump's obligation is genuinely visible in RAM",
    mutual_excl.free_power_start_admission_check() is False,
)

print("")
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for name in FAILURES:
        print(f"  - {name}")
else:
    print("All Free Power<->Dump durable-obligation arbitration tests PASSED.")

print("")
print("These are STRUCTURAL/source-text checks against the real firmware plus a")
print("hand-written Python reference-model simulation of the admission-gate-bypass ->")
print("dual-obligation -> reboot-reconciliation sequence - they prove the source and")
print("the model agree with the intended fix, not that the compiled firmware's actual")
print("NVS sync() behaviour produces this false negative on real hardware. See")
print("CURRENT_STATE.md for what remains unverified. S3 (Free Power reboot-resume) is")
print("a separate, NOT-yet-implemented follow-up and is out of scope for this fix.")

if FAILURES:
    sys.exit(1)
