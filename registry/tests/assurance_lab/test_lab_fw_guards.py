#!/usr/bin/env python3
"""FW-09 / FW-10 / FW-11 directed guard scenarios on the real firmware (FirmwareWorld): the Dump to Grid restore
verification (register 244 and the 256-261 readback: a write the inverter acknowledges but does not apply, a verify read
that fails after the write landed), the Free Power terms of the Dump to Grid START gate, and the Free Power durable marker
boot faults on a USED NVS key (an NVS read error, a record of the wrong size, a record with a bad magic). Offline assurance
lab V0.1 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Why this suite exists (V0.1 brief B3, mutation coverage). Five in-memory mutants of production guards survived every lab
suite, or were killed only by one random PB-01 property check: M9 (the Dump restore's register-244 readback compare, FW:19982),
C6 (the Dump restore's 256-261 readback compare, FW:20336), M7 (the two Free Power terms of the Dump START gate,
FW:18060-18061), C3 (the Free Power marker READ_ERROR lockout, FW:525) and C7 (the Free Power malformed / wrong-size marker
lockout, FW:526-531). Each scenario below drives the guard directly and every expectation is derived from the cited
firmware lines, never from the simulator's output. Section [4] applies each mutant IN MEMORY (an exact-count text replace,
parsed with _lab_fw.load_fw; nothing on disk changes) and asserts that the INTENDED named checks fail there - a mutant
that does not apply exactly once, does not parse or crashes is MUTANT-INVALID, a negative-control FAILURE, never a kill.

Scenarios (SCENARIOS below; every timeline is a corpus draft, CORPUS_DRAFTS, run by play() exactly as the replay engine
runs it, plus a suite-only continuation where stated):
  FW-09  Dump restore verification (restore_dump_to_grid_snapshot, FW:19741-20560):
         a   the 244 restore write is acknowledged but not applied (every attempt);
         b   the 6-slot 256-261 block write is acknowledged but not applied (every attempt);
         b2  a FOREIGN slot (261, changed by the inverter) makes the 256-261 plan per-slot; the 260 write first fails on
             comms, then every retry is a SINGLE-SLOT write (wmask 0x10) that is acknowledged but not applied;
         b3-256 .. b3-261 (W6-1, the per-slot readback verify; one scenario per slot k): a FOREIGN slot j (the
             inverter's own 4000 W; j = 261 for k = 256..260, j = 256 for k = 261) makes the plan per slot, and every
             single-register write of k is acknowledged but not applied (policy key 'write:<k>x1'). The first attempt
             writes 244 and every other non-FOREIGN slot one by one and fails on k's readback; the retry at the next
             watchdog tick is a SINGLE-SLOT write of k alone (wmask 1 << (k - 256)) and fails on it again;
         b4-ct / b4-cb / b4-co (W6-1b, the containment path): every 244 write is acknowledged but not applied, so 244 is
             not proven and every non-FOREIGN 256-261 slot is written at min(original, 500 W) (FW:20019-20043). ct: a
             FOREIGN 261 makes the containment per slot and slot 258's floor write is acknowledged but not applied; cb:
             nothing FOREIGN, the 6-slot floor block is acknowledged but not applied; co: the inverter puts 256 back to
             its ORIGINAL at the End (the pre-read neither owns it nor finds it FOREIGN), containment still writes it, and
             that write is acknowledged but not applied (the owned mask and the write mask differ). Each fails both
             attempts and never claims the containment ('ECCO's own at 500 W' / 'held at the 500 W floor'): the status
             names 'export may continue' (FW:20372, FW:20447-20459, FW:20535-20550);
         b5-lo (W6-1b, a readback ABOVE the expected value): b3's shape for slot 259 on a site whose 259 ORIGINAL is
             600 W, below the 1000 W lease value, so the unapplied 259 reads 1000 W, above its expected 600 W;
         b6-ok / b6-x257 / b6-x260 (W6-1b, slot cross-wiring; pairwise-distinct 256-261 ORIGINAL 3000 / 8000 / 7000 /
             6000 / 4500 / 5000 W): ok: a fault-free restore of that bank, one verified attempt (each slot's readback is
             compared with its own original); x257 / x260: b3's shape for slot 257 / 260 on that bank with 256's / 259's
             ORIGINAL set to the 1000 W lease value, so the unapplied slot reads its neighbour's expected value;
         b7-rbnr / b7-rber / b7-cmnr / b7-ab / b7-af (W6-1c, the containment CLAIM): rbnr / rber: b4-cb's / b4-ct's
             containment (every 244 write acknowledged but not applied; the 6-slot floor block / slot 258's floor write
             acknowledged but not applied) whose 256-261 readback gets no response / an error: its failure handler sets
             block_failed (FW:20343-20357), so dump_restore_contained stays clear (FW:20372); the 244 mismatch takes the
             mismatch path (FW:20482), both attempts fail, then the operator lockout; cmnr: the comms path in
             containment - 244 lands but its verify read errors (unproven by a comms failure, FW-09 c's shape), the
             6-slot floor block is acknowledged but not applied and its readback gets no response, so the attempt fails
             on the comms path (FW:20508-20519) naming 'export may continue'; the suite continues to the retry after
             the backoff, which restores ORIGINAL and completes; ab: two attempts - the first is a verified containment
             (its status truthfully says 'held at the 500 W floor'), then the inverter puts 258 back to its ORIGINAL and
             the second attempt's floor block is acknowledged but not applied: dump_restore_contained, reset when an
             attempt starts (FW:19819), stays clear and no later status claims the containment; af: every 256-261 slot
             FOREIGN, so the containment plan writes nothing (m == 0): dump_restore_contain stays clear (FW:20043) and
             no status claims the containment (FW:20449-20454);
         c   the 244 verify read returns an error after the 244 write landed;
         c2  the 256-261 verify read gets no response after the block write landed.
         Each must hold: no 'RESTORED OK' (or any verified-restore claim) for a failed attempt, the marker not CLEAR, the
         obligation and its retries kept or the documented operator path taken, no INV-NO-SILENT-OVERRIDE violation, and
         the bank values reported truthfully. a / b / b2 / b3-* / b4-* / b5-lo / b6-x257 / b6-x260 / b7-rbnr / b7-rber /
         b7-ab / b7-af end in the documented operator lockout after the second verify mismatch (FW:20482-20501); b6-ok
         completes in one verified attempt (FW:20378-20419); a continues (suite only) with the operator's Force Restore
         Original; c / c2 / b7-cmnr take the comms path (FW:20508-20519) and the suite continues to the automatic retry
         after the backoff. W6-1c also checks every containment claim of every FW-09 timeline ('ECCO's own at 500 W',
         'held at the 500 W floor'; contain_claims): each must be backed by the bank as it stood when that status was
         published (at least one non-FOREIGN 256-261 slot, every one at min(original, 500 W); FW:20028-20043,
         FW:20372, FW:20449-20456, FW:20538-20544).
  FW-10  The Free Power terms of the Dump START gate (FW:18047-18076; rejection text FW:18890), in three Free Power states
         where every Free Power owned register is already back at ORIGINAL (so the TOU charge-flag walk FW:18041 has no
         conflict and only the Free Power terms can refuse):
         A   RESTORE_REQUIRED, active_persisted and snapshot_valid set: the Free Power End restore's final 256-279 verify
             read (FW:11168) fails (comms path FW:11322-11332, backoff);
         B   PENDING_CLEAR, snapshot_valid set, active_persisted clear: the restore verified but the durable clear (Phase D,
             FW:11226) does not land (FW:11256-11266);
         C   UNKNOWN lockout, snapshot_valid and metadata_corrupt set, active_persisted clear: an NVS read error on the used
             fp.valid key after a completed lease (FW:532-538: 'cross-domain START gates see snapshot_valid').
         Each START must be REJECTED citing Free Power with zero writes, and the same START must be admitted once the Free
         Power state is gone (A, B: the suite lets the Free Power watchdog resolve it; C: a control timeline with a plain
         reboot instead of the fault boot), so only the Free Power terms refused.
  FW-11  Free Power marker boot faults on a USED fp.valid key (a completed lease first), each with the record CLEAR (the
         completed lease) and RESTORE_REQUIRED (a second lease ACTIVE at the cut): NVS read error -> the SG-06 UNKNOWN
         lockout (FW:532-538, status FW:1183); wrong size -> the MALFORMED lockout (FW:526, FW:539-550, status FW:1190);
         bad magic -> the MALFORMED lockout (FW:527). The bad-magic record is seeded WHITE-BOX in this suite only (the
         captured NVS image of a real run gets a ValidMarker whose magic differs from VALID_MARKER_MAGIC, then reboot_from):
         no replay boot-fault mode writes a bad magic, so it has no corpus document.

Negative controls ([4], NC_TABLE): 28 distinct mutations (M9, C6, MC244, MC256, C6k0..C6k5, C6s0, C6s5, C6bf, C6om, C6lt,
C6r1, C6r4, C6v34, C6rh, C6rn, C6rs, C6m0, M7, M7a, M7b, C3, C7, C7ws) in 33 control checks; an identical mutation applied
to several scenarios counts once (the independence rule).
The slot mutants (finding W6-1 of the independent recheck of V0.1): C6k0..C6k5 add 'i != k &&' to the 256-261 readback
compare (FW:20336), so slot 256 + k is never verified; C6s0 / C6s5 move the readback loop's bounds (FW:20335, anchored
together with FW:20336 because the loop line occurs 16 times in the firmware) to 'i = 1' (256 never verified) / 'i < 5'
(261 never verified). Each is killed by the b3 scenario of the slot it skips (C6k4 also by b2). The W6-1b mutants (the six
per-slot verify regressions that survived the W6-1 review): C6bf drops the mismatch branch's block_failed (FW:20337),
C6om checks the owned mask instead of the write mask (FW:20336), C6lt flags only a readback below the expected value
(FW:20336 '<'), C6r1 / C6r4 compare slot 257 / 260 with its lower neighbour's expected value (FW:20336) and C6v34 swaps
slots 259 and 260 in the readback's expected values (FW:20333). C6bf is killed by b4-ct, b4-cb and b4-co, C6om by b4-co,
C6lt by the three b4 scenarios and b5-lo, C6r1 by b6-ok and b6-x257, C6r4 and C6v34 by b6-ok and b6-x260. The W6-1c
mutants (the four containment-claim regressions that survived the W6-1b review): C6rh drops block_failed from the 256-261
readback's four failure handlers (FW:20347, FW:20352, FW:20357, FW:20365), C6rn from its no-response handler only
(FW:20352), C6rs drops the per-attempt reset of dump_restore_contained (FW:19819) and C6m0 drops 'm != 0' from the
containment flag (FW:20043). C6rh is killed by b7-rbnr, b7-rber and b7-cmnr, C6rn by b7-rbnr and b7-cmnr (b7-rber's
error handler is not its edit), C6rs by b7-ab and C6m0 by b7-af. Two outcomes
are expected survivals, each with a source reason: M7a (drop only '!free_power_active_persisted') is an EQUIVALENT mutant - every
reachable state with active_persisted set also has snapshot_valid set ([3] checks the assignment sites); C7ws (drop only
the wrong-size term) keeps the bad-magic term of FW:527, so the bad-magic boot still locks. M7b (drop only
'!free_power_snapshot_valid') is killed by FW-10 B and C and survives FW-10 A (the active term refuses there).
Brief inconsistency (reported): the brief asks every FW-09 scenario to kill M9 or C6, but scenario c cannot - M9 and C6 sit
in the verify reads' on_response lambdas (FW:19982, FW:20336) and c takes on_error / on_no_response (FW:19989-20003,
FW:20343-20357). c and c2 therefore get their own error-branch mutants (MC244: the 244 verify read's on_error no longer
fails the attempt; MC256: the 256-261 verify read's on_no_response no longer fails it), and [1] checks that M9 and C6 leave
the c / c2 outcome unchanged. M1 / M2 (the PR41 dual lockout locking only one domain) are killed by directed checks in
test_lab_fw_obligations, test_lab_fw_durability and test_lab_ha_phantom; this suite adds no scenario for them.

Corpus: FW-09-a, -b, -b2, -b3-256 .. -b3-261, -b4-ct, -b4-cb, -b4-co, -b5-lo, -b6-ok, -b6-x257, -b6-x260, -b7-rbnr,
-b7-rber, -b7-cmnr, -b7-ab, -b7-af, -c, -c2, FW-10-a, -b, -c and FW-11-a..d (CORPUS_DRAFTS; record() fills the digests).
[5] replays each document and replays each against the in-memory mutant of the guard it pins (its key expectation must
FAIL there; each FW-09-b3 document against every slot mutant that skips its slot, each W6-1b / W6-1c document against
every W6-1b / W6-1c mutant that scenario kills).

Phase sensitivity: no scenario check of this suite depends on the lab's scheduler phase: every timing bound holds for
any watchdog phase (a retry at the next 15 s tick, or after the 15 s backoff plus one tick), the END DEFERRED waiting
text - whose presence does depend on the phase - is excluded from every status sequence compared, and each FW-10 Dump
START meets a Free Power state no watchdog tick can change before it (A, B: pressed at the same instant as the Free
Power End that sets it; C: the lockout lasts the whole boot). Extended mode (ECCO_LAB_EXTENDED=1 / --extended) re-runs
every FW-09 and FW-10 timeline with five watchdog phase offsets (phase_ms 1-13 s) and requires every check to hold
unchanged (the six FW-09 b3 timelines, the seven W6-1b timelines b4-*, b5-lo and b6-*, and the five W6-1c timelines b7-*,
each in a check of their own);
in V0.1 an in-memory ESPHome-like phase patch (B4 change 7, scratch only) held every scenario check too (it was not re-run
for the later b3 - b7 scenarios). The only
checks tagged in PHASE_SENSITIVE_TAGS are the corpus replays: each document's trace digest pins its recorded timeline,
the lab's phase. Quick mode takes a few seconds.
"""
from __future__ import annotations
import sys
sys.dont_write_bytecode = True
from pathlib import Path
HERE = Path(__file__).resolve().parent            # registry/tests/assurance_lab
ROOT = HERE.parents[2]                             # worktree root
for p in (HERE, ROOT / "registry" / "tests", ROOT / "registry", ROOT / "home-assistant" / "tests", ROOT / "tools"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
FAILURES: list[str] = []
PASSES: list[str] = []          # held checks, excluding finding pins (LAB-SUMMARY 'pass')
FINDING_CHECKS: list[str] = []  # held 'finding-reproduces:' checks (LAB-SUMMARY 'finding_pins', never in 'pass')
# Phase-sensitivity registry (B4 change 7; HL-10): check-name prefix -> why that check's verdict depends on the lab's
# scheduler phase. The lab runs every firmware interval first at its startup_delay (else one period) after power-on with
# zero offset and reschedules it at due+T; the coupled tier samples the polled template sensors on the uptime grid and
# the RTC rig starts its intervals at the rig boot with a fixed phase. ESPHome 2026.8.2 runs each interval first at
# setup + startup_delay + a random offset in [0, min(T/2, 5 s)) and reschedules it at now+T (scheduler.cpp:105-110,
# 181-184, 540; interval.h; component.cpp:381-391). The tags were found by running every suite under an in-memory
# ESPHome-like phase patch (scratch only, not shipped; quick mode: 8 seeds of the full patch and 3 seeds of each of 3
# narrower variants; extended mode: 3 seeds) plus the audit's list of timing-bound checks. LAB-SUMMARY 'phase_sensitive'
# counts the EXECUTED checks (held or failed) whose name starts with a registered prefix (detected per run, never a
# literal); check_phase_registry() FAILS on a stale prefix (no executed check matches it), a prefix without a reason, or
# an unregistered PHASE_SENSITIVE_EXTENDED_ONLY entry (the prefixes whose checks run only in extended mode: they are
# required to match only there).
_PS_DIGEST = (
    "trace-digest pin of a recorded corpus document: its fixed action timeline replays on the lab scheduler (HL-10: "
    "first run at startup_delay, else one period, after power-on, zero offset, due+T) and the digest covers every "
    "scheduled job's events, so any other phase (ESPHome 2026.8.2: setup + startup_delay + a random offset in [0, "
    "min(T/2, 5 s)), then now+T) changes it - fails under the phase patch by construction")
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "corpus FW-09-a (": _PS_DIGEST,
    "corpus FW-09-b (": _PS_DIGEST,
    "corpus FW-09-b2 (": _PS_DIGEST,
    "corpus FW-09-b3-256 (": _PS_DIGEST,
    "corpus FW-09-b3-257 (": _PS_DIGEST,
    "corpus FW-09-b3-258 (": _PS_DIGEST,
    "corpus FW-09-b3-259 (": _PS_DIGEST,
    "corpus FW-09-b3-260 (": _PS_DIGEST,
    "corpus FW-09-b3-261 (": _PS_DIGEST,
    "corpus FW-09-b4-ct (": _PS_DIGEST,
    "corpus FW-09-b4-cb (": _PS_DIGEST,
    "corpus FW-09-b4-co (": _PS_DIGEST,
    "corpus FW-09-b5-lo (": _PS_DIGEST,
    "corpus FW-09-b6-ok (": _PS_DIGEST,
    "corpus FW-09-b6-x257 (": _PS_DIGEST,
    "corpus FW-09-b6-x260 (": _PS_DIGEST,
    "corpus FW-09-b7-rbnr (": _PS_DIGEST,
    "corpus FW-09-b7-rber (": _PS_DIGEST,
    "corpus FW-09-b7-cmnr (": _PS_DIGEST,
    "corpus FW-09-b7-ab (": _PS_DIGEST,
    "corpus FW-09-b7-af (": _PS_DIGEST,
    "corpus FW-09-c (": _PS_DIGEST,
    "corpus FW-09-c2 (": _PS_DIGEST,
    "corpus FW-10-a (": _PS_DIGEST,
    "corpus FW-10-b (": _PS_DIGEST,
    "corpus FW-10-c (": _PS_DIGEST,
    "corpus FW-11-a (": _PS_DIGEST,
    "corpus FW-11-b (": _PS_DIGEST,
    "corpus FW-11-c (": _PS_DIGEST,
    "corpus FW-11-d (": _PS_DIGEST,
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (FINDING_CHECKS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + FINDING_CHECKS + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import copy  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _dump_sim as ds  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402

SUITE = "test_lab_fw_guards"
FWP = L.FW_REL
HDR = "firmware/include/ecco_durable_snapshot.h"
FW = L.load_fw()
INFO = L.fw_info(FW)
SUBS = FW["_substitutions"]
U0_ISO = "2026-10-21T10:50:00Z"                  # a synthetic Wednesday (BST); no site value
U0 = C.parse_iso_utc(U0_ISO)
ORIG = dict(L.SITE["original"])
DUMP_REGS = (244, 256, 257, 258, 259, 260, 261)
TOU = (256, 257, 258, 259, 260, 261)
FP_REGS = tuple(sorted(L.DOMAIN_REGS["fp"]))
FINDINGS: dict[str, str] = {}                    # none: every scenario of this suite is a PASS scenario
DUPLICATE_OF: dict[str, str] = {}
UNSUPPORTED_POINTS: list[str] = []               # one catalogue id per printed UNSUPPORTED line: none met
NC_RESULTS: list[tuple[str, str, str, str]] = []  # (nid, mutant id, scope, outcome)
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

WD_S = INFO.job["dump_wd"]["period_ms"] / 1000           # 15 s Dump watchdog
FP_WD_S = INFO.job["fp_wd"]["period_ms"] / 1000          # 15 s Free Power watchdog
TEL_S = INFO.job["telemetry"]["period_ms"] / 1000        # 10 s telemetry poll
FLOOR_W = int(SUBS["ecco_dump_controller_min_ceiling_w"])  # 500 W containment floor (FW:314)
_tab = re.search(r"static const uint32_t table_ms\[\] = \{([0-9, ]+)\};", T.read_source_text(HDR))
BACKOFF_S = [int(x) // 1000 for x in _tab.group(1).split(",")] if _tab else []
ORIG_TOU = [ORIG[a] for a in TOU]                         # 8000, 8000, 7000, 8000, 8000, 5000 (synthetic SITE)

# status literals (each must occur in the firmware text: [0])
RESTORING = "RESTORING - writing back original inverter settings"                                        # FW:19793
RESTORED = "RESTORED OK - original inverter settings verified"                                           # FW:20419
MISMATCH_1 = "RESTORE VERIFY FAILED - snapshot retained; watchdog will retry once automatically"         # FW:20504
MISMATCH_2 = ("OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original "
              "or Accept Current State")                                                                  # FW:20499
OP_WAIT = "OPERATOR DECISION REQUIRED - use Force Restore Original or Accept Current State"              # FW:20549
CONTAINED = ("; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor")  # FW:20456
COMMS_FAIL = ("RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically "
              "with backoff")                                                                             # FW:20517
FOREIGN_CLAIM = "restored and verified"           # the FOREIGN lockout text claims ECCO's own slots verified (FW:20477)
VERIFIED_CLAIMS = ("RESTORED OK", "RESTORE VERIFIED", FOREIGN_CLAIM)
# W6-1b: the containment suffix pieces of the failure branch (FW:20447-20459) and of the operator wait (FW:20537-20547;
# the same texts): 244 not proven with FOREIGN slots named (FW:20452-20454), held at the floor (FW:20456), neither
# contained nor a FOREIGN slot named: export may continue (FW:20457-20458)
UNPROVEN_244 = "; 244 NOT proven off"                                                                     # FW:20452
MAY_CONTINUE = "; export may continue"                                                                    # FW:20453
OWN_AT_FLOOR = "; ECCO's own at 500 W"                                                                    # FW:20453
NOT_CONTAINED = "; NOT CONTAINED: "                                                                       # FW:20454
EXPORT_MAY = "; register 244 is NOT proven out of Allow Export - export may continue"                     # FW:20458
CONTAIN_CLAIMS = ("ECCO's own at 500 W", "held at the 500 W floor")   # a containment claimed (FW:20453, FW:20456)
DEFERRED = "END DEFERRED - "                      # the gate's waiting texts (FW:20552-20565): presence is phase-dependent
REJ_FP = "REJECTED - Free Power override/recovery owns inverter settings"                               # FW:18890
DUMP_ACTIVE = "ACTIVE - VERIFIED OK"                                                                      # FW:18840
FP_VERIFY_ERR = "RESTORE VERIFY ERROR - snapshot retained for retry"                                    # FW:11332
FP_PENDING = ("RESTORED OK - original inverter settings verified; durable recovery-marker clear pending, will retry")  # FW:11264
FP_RESTORED = "RESTORED OK - original inverter settings verified"                                       # FW:11254
FP_RESOLVED = "RECOVERY RESOLVED OK - durable recovery marker cleared"                                  # FW:10056
FP_UNKNOWN = ("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation "
              "cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the record read as absent")  # FW:1183
FP_MALFORMED = ("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or "
                "invalid); inverter writes locked")                                                       # FW:1190
LITERALS = (RESTORING, RESTORED, MISMATCH_1, MISMATCH_2, OP_WAIT, CONTAINED, COMMS_FAIL, FOREIGN_CLAIM, DEFERRED, REJ_FP,
            DUMP_ACTIVE, FP_VERIFY_ERR, FP_PENDING, FP_RESTORED, FP_RESOLVED, FP_UNKNOWN, FP_MALFORMED, UNPROVEN_244,
            MAY_CONTINUE, OWN_AT_FLOOR, NOT_CONTAINED, EXPORT_MAY) + CONTAIN_CLAIMS

# =============================================================================================================================
# scenario table (ownership, exact source anchors, invariant, failure outcome, classification, grade, confidence, priority)
# =============================================================================================================================
OWN_DUMP = ("ECCO owns a Dump to Grid lease started by the owner through the real Start button and ended through the real "
            "End & Restore button (synthetic SITE ORIGINAL 244 = 2, 256-261 = 8000/8000/7000/8000/8000/5000; b5-lo: 259 = "
            "600; b6-ok: the pairwise-distinct 3000/8000/7000/6000/4500/5000, b6-x257 / b6-x260 with 256 / 259 = 1000; "
            "lease 1000 W, Stop SOC 25 %); the inverter's Modbus answers come from per-operation outcome policies (an "
            "acknowledged write that is not applied, an error, no response); in b2, b3-256..b3-260, b4-ct, b4-co, b5-lo, "
            "b6-x257, b6-x260 and b7-rber the inverter itself changes 261, in b3-261 it changes 256 (FOREIGN); in b4-co it "
            "also puts 256 back to its ORIGINAL; in b7-ab it puts 258 back to its ORIGINAL after the first restore attempt; "
            "in b7-af it changes all six of 256-261 (FOREIGN)")
OWN_GATE = ("ECCO owns a Free Power lease (owner START 3000 W, 10 min) whose End leaves a Free Power obligation state with "
            "every Free Power owned register back at ORIGINAL; the owner then presses the real Dump to Grid Start (1000 W, "
            "Stop SOC 25 %, 30 min); no foreign actor")
OWN_BOOT = ("ECCO owned a Free Power lease that completed (RESTORED OK, marker CLEAR: the fp.valid key is USED); then either "
            "nothing (record CLEAR) or a second Free Power lease is ACTIVE (record RESTORE_REQUIRED) when the power is cut "
            "and the next boot meets an NVS fault on that key; no foreign actor")
SCENARIOS = {
    "FW-09": {
        "title": "Dump restore verification: a write acknowledged but not applied (244; 256-261 block; a single slot; in "
                 "containment), a verify read that fails after the write landed (244; 256-261) or in containment, and "
                 "every containment claim backed by the bank",
        "priority": "P1", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-NO-SILENT-OVERRIDE, INV-RESTORE-BOUND (lockout / fault explained), INV-WS; directed: no verified-"
                     "restore claim for a failed attempt, marker kept, one automatic retry then the operator lockout "
                     "(mismatch) or backoff retries (comms), truthful status / bank",
        "ownership": OWN_DUMP,
        "anchors": [(FWP, "if (raw != id(dump_snapshot_reg244)) {"),
                    (FWP, "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"),
                    (FWP, "id(dump_restore_244_ok) = id(dump_restore_244_action) != 1 || !id(dump_write_failed);"),
                    (FWP, "if (!contain && id(dump_restore_foreign_mask) == 0 && m != 0) m = 0x3F;"),
                    (FWP, "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"),
                    (FWP, 'id(dump_status).publish_state("RESTORED OK - original inverter settings verified");'),
                    (FWP, "if (id(dump_verify_mismatch_count) >= 2) {"),
                    (FWP, "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"),
                    (FWP, "if (id(dump_restore_pre_ok) && id(dump_force_restore_this_call)) {")],
        "failure_outcome": "the restore reports RESTORED OK (or 'restored and verified'), clears the durable marker and "
                           "drops the obligation while register 244 stays at Allow Export or 256-261 stay at the lease "
                           "power (a silent override), or a failed verify read is taken as success",
        "corpus": ["FW-09-a", "FW-09-b", "FW-09-b2", "FW-09-b3-256", "FW-09-b3-257", "FW-09-b3-258", "FW-09-b3-259",
                   "FW-09-b3-260", "FW-09-b3-261", "FW-09-b4-ct", "FW-09-b4-cb", "FW-09-b4-co", "FW-09-b5-lo",
                   "FW-09-b6-ok", "FW-09-b6-x257", "FW-09-b6-x260", "FW-09-b7-rbnr", "FW-09-b7-rber", "FW-09-b7-cmnr",
                   "FW-09-b7-ab", "FW-09-b7-af", "FW-09-c", "FW-09-c2"], "finding": None,
        "model": "Modbus outcome policies ack_not_applied / error / no_response per operation (synthetic inverter); the "
                 "inverter's own change of 261 (b3-261: 256; b4-co also 256 back to its ORIGINAL; b7-ab 258 back to its "
                 "ORIGINAL after the first attempt; b7-af all six) is set_register(actor='inverter'); synthetic bank "
                 "overrides (world bank) for b5-lo and b6-*; scripts and "
                 "Modbus are synchronous (_dump_sim); multi-register writes are all-or-nothing in the model (one outcome "
                 "per operation), so a single unapplied slot is exercised on the per-slot plan only (a FOREIGN slot "
                 "present, FW:20035, FW:20031); the 6-slot block is exercised whole (b4-cb all six unapplied, b6-ok all "
                 "six applied); a partially applied 256x6 block is not modelled. In b4-co the lab's own foreign set "
                 "includes 256 (set_register(actor='inverter') adds it) although the firmware classifies 256 as neither "
                 "owned nor FOREIGN there, so truthful() and INV-NO-SILENT-OVERRIDE do not cover 256 in b4-co; it rests "
                 "on the directed write, bank and globals checks and the corpus expectations. The W6-1c containment-claim "
                 "helper (contain_claims) does not use the lab's foreign set: it classifies each slot by the firmware's "
                 "own rule at the attempt's ownership pre-read (FW:19856-19867) and judges each claim against the bank "
                 "at that status's publish instant, rebuilt from the event log (landed writes and set_register); the lab "
                 "logs a status only when its text changes, so a claim re-published unchanged after a later bank change "
                 "is judged at its first publication (no FW-09 timeline changes the bank after its last attempt)",
        "notes": "Kills M9 (a) and C6 (b, b2) with named checks; c / c2 cannot kill M9 / C6 by construction (their failure "
                 "path never runs the mutated on_response compares) and get their own error-branch mutants MC244 / MC256. "
                 "b2 is the single-slot partial-mask case: after the first attempt's comms failure on 260, the restored "
                 "256-259 read ORIGINAL and the FOREIGN 261 is excluded, so every retry writes and verifies 260 alone. "
                 "b3-256 .. b3-261 (W6-1) exercise the per-slot readback verify of each slot k on the non-containment "
                 "per-slot plan: with a FOREIGN slot (261, or 256 for b3-261) the plan is per slot (FW:20027-20035); the "
                 "first attempt writes every other slot one by one and fails on slot k's readback, the retry writes k "
                 "alone and fails again (FW:20335-20341), then the operator lockout (FW:20482-20501); they kill the slot "
                 "mutants C6k0..C6k5 (C6k4 also by b2) and the loop-bound mutants C6s0 / C6s5, each of which ends the "
                 "first attempt in the FOREIGN lockout text 'restored and verified' (FW:20373-20377, FW:20460-20481) with "
                 "slot k still at the lease power. W6-1b closes the six per-slot verify regressions that survived the "
                 "W6-1 review. b4-ct / b4-cb / b4-co are the containment path (244 not proven, FW:20019-20020): an "
                 "unapplied floor write (a slot, the whole block, or a slot that reads its ORIGINAL and is written only "
                 "because of the containment, FW:20031) fails the readback, sets block_failed (FW:20337) and so keeps "
                 "dump_restore_contained clear (FW:20372): every status says 'export may continue', never 'ECCO's own at "
                 "500 W' or 'held at the 500 W floor' (FW:20447-20459, FW:20535-20550); they kill C6bf (block_failed "
                 "dropped), C6om (b4-co: the owned mask instead of the write mask) and C6lt ('<': the readback 1000 W or "
                 "8000 W is above the 500 W floor). b5-lo is b3's shape on a site whose 259 ORIGINAL (600 W) is below "
                 "the 1000 W lease value, so the unapplied readback is ABOVE the expected value: it kills C6lt outside "
                 "containment. b6-ok restores pairwise-distinct originals in one verified attempt and kills the "
                 "cross-wiring mutants C6r1, C6r4 and C6v34 by their false mismatch (an extra attempt, 'RESTORE VERIFY "
                 "FAILED'); b6-x257 / b6-x260 set 256's / 259's ORIGINAL to the 1000 W lease value, so the unapplied "
                 "257 / 260 reads its neighbour's expected value: they kill C6r1 (x257) and C6r4 / C6v34 (x260) by the "
                 "missed mismatch ('restored and verified' with the slot at 1000 W). W6-1c closes the four "
                 "containment-claim regressions that survived the W6-1b review. b7-rbnr / b7-rber are b4-cb's / b4-ct's "
                 "containment whose 256-261 readback gets no response / an error: the failure handler sets block_failed "
                 "(FW:20343-20357), so dump_restore_contained stays clear (FW:20372) and every status says 'export may "
                 "continue'; the 244 readback mismatch (FW:19982-19984) routes both to the mismatch path (FW:20482-20507), "
                 "not the comms path. b7-cmnr is the comms path in containment (FW-09 c's shape: 244 lands but its verify "
                 "read errors, FW:19989-19993, no mismatch) with the floor block unapplied and its readback unanswered: "
                 "'RESTORE WRITE FAILED' with 'export may continue' (FW:20447-20459, FW:20508-20519), then the retry "
                 "after the backoff finds 244 ORIGINAL, restores ORIGINAL and completes. They kill C6rh (block_failed "
                 "dropped from every readback failure handler: rbnr, rber, cmnr) and C6rn (the no-response handler only: "
                 "rbnr, cmnr), under which the status claims 'held at the 500 W floor' / \"ECCO's own at 500 W\" with "
                 "the floor writes unapplied. b7-ab has a verified containment attempt (its 'held at the 500 W floor' is "
                 "true then) followed by a failed one (the inverter puts 258 back to its ORIGINAL, the second floor block "
                 "is unapplied): the per-attempt reset (FW:19819) keeps the second attempt's statuses from claiming the "
                 "containment; it kills C6rs (the reset dropped). b7-af has every 256-261 slot FOREIGN, so the "
                 "containment writes nothing (m == 0) and dump_restore_contain stays clear (FW:20043); it kills C6m0 "
                 "('m != 0' dropped), under which the status claims \"ECCO's own at 500 W\" with no ECCO slot. Every "
                 "FW-09 timeline's containment claims are checked against the bank at their publish instant "
                 "(contain_claims; the 'FW-09 claims' check)."},
    "FW-10": {
        "title": "Dump START gate: the Free Power terms refuse alone (Free Power RESTORE_REQUIRED, PENDING_CLEAR, UNKNOWN "
                 "lockout) with every Free Power owned register at ORIGINAL",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-ONE-LEASE, INV-NO-2ND-RESTORER, INV-LOCKOUT-QUIET; directed: REJECTED citing Free Power, zero "
                     "writes, the same START admitted once the Free Power state is resolved",
        "ownership": OWN_GATE,
        "anchors": [(FWP, "// Register 244 standalone proof transaction: Dump also"),
                    (FWP, 'else if (id(free_power_active_persisted) || id(free_power_snapshot_valid) || id(free_power_operation_in_progress)) id(dump_status).publish_state("REJECTED - Free Power override/recovery owns inverter settings");'),
                    (FWP, 'id(free_power_status).publish_state("RESTORE VERIFY ERROR - snapshot retained for retry");'),
                    (FWP, 'id(free_power_status).publish_state("RESTORED OK - original inverter settings verified; durable recovery-marker clear pending, will retry");'),
                    (FWP, "if (id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_VERIFIED_PENDING_CLEAR) return true;"),
                    (FWP, "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;"),
                    (FWP, "id(free_power_active_persisted) = data.active_persisted != 0;")],
        "failure_outcome": "a Dump to Grid lease starts while Free Power holds an unresolved obligation (both leases "
                           "active, or Dump writes 244 / 256-261 while Free Power's durable state is pending or UNKNOWN)",
        "corpus": ["FW-10-a", "FW-10-b", "FW-10-c"], "finding": None,
        "model": "Modbus outcome policy (one failed verify read), NVS commit policy not_landed on the used fp.valid key "
                 "(twice), NVS boot fault read_error on the used fp.valid key",
        "notes": "Kills M7 (A, B, C) and the single-term variant M7b (B, C); M7b survives A (the active term refuses). The "
                 "single-term variant M7a is an equivalent mutant: active_persisted is set only at FW:9762 (after "
                 "snapshot_valid at FW:9164 in the same START) and at FW:573 (right after snapshot_valid at FW:572), and "
                 "every snapshot_valid := false site clears active_persisted in the same lambda or is the CLEAR boot "
                 "branch (FW:555, active_persisted starts false: restore_value no); checked statically in [3]."},
    "FW-11": {
        "title": "Free Power marker boot faults on a USED fp.valid key: NVS read error -> UNKNOWN lockout; wrong size and "
                 "bad magic -> MALFORMED lockout (record CLEAR and RESTORE_REQUIRED)",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-BOOT-MIRROR, INV-NO-SILENT-OVERRIDE, INV-LOCKOUT-QUIET; directed: snapshot_valid + "
                     "metadata_corrupt after the FULL on_boot, the cause-specific status, the record untouched, no Free "
                     "Power write",
        "ownership": OWN_BOOT,
        "anchors": [(FWP, "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;"),
                    (FWP, 'ESP_LOGE("free_power", "RECOVERY BLOCKED - durable recovery marker is malformed (bad magic or unrecognised state); inverter writes locked");'),
                    (FWP, 'id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the record read as absent");'),
                    (FWP, 'id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked");'),
                    (FWP, "if (id(free_power_recovery_metadata_corrupt)) return false;")],
        "failure_outcome": "an unreadable or malformed Free Power marker is read as CLEAR: the boot drops a possible (or "
                           "real) obligation, the live override is left with no visible obligation and no lockout",
        "corpus": ["FW-11-a", "FW-11-b", "FW-11-c", "FW-11-d"], "finding": None,
        "model": "NVS boot faults read_error / wrong_size on the used fp.valid key (replay boot-fault modes); the bad "
                 "magic is a WHITE-BOX edit of the captured NVS image (suite only, no corpus document)",
        "notes": "Kills C3 (read error), C7 (wrong size and bad magic) and C7ws (wrong size); C7ws survives the bad-magic "
                 "boot by design (it keeps the magic term of FW:527). The used-key prelude (a completed lease first) "
                 "keeps every injected fault physically possible (the key holds a stored record)."},
}


# =============================================================================================================================
# corpus drafts (pure literal: the scratch recorder reads it with ast.literal_eval; record() fills source_digests (the three
# placeholder paths plus every anchor path), each anchor's line_at_record and trace_digest from two identical replays). The
# suite RUNS these action lists itself (play()), so every document is exactly the scenario the suite checks.
# =============================================================================================================================
CORPUS_DRAFTS = [
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-a", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore: the register-244 restore write is acknowledged but not applied (every attempt)",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); the inverter "
                  "acknowledges every 244 write without applying it (synthetic Modbus outcome policy); no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (raw != id(dump_snapshot_reg244)) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_verify_mismatch_count) >= 2) {"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 500, "257": 500, "258": 500, "259": 500, "260": 500, "261": 500}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "RESTORED OK with the marker cleared while 244 stays at Allow Export (the M9 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the 244 readback mismatch fails both attempts, 256-261 "
                                   "contained at the 500 W floor, operator lockout after the second mismatch",
     "notes": "Derived from FW:19976-19988 (readback != snapshot -> write_failed, mismatch), FW:20019-20043 (244 not proven "
              "-> contain 256-261 at min(original, 500 W)), FW:20482-20507 (first mismatch: one automatic retry; second: "
              "durable operator lockout) and FW:20455-20456 (the containment named). The M9 mutant (FW:19982 compare "
              "disabled) reports RESTORED OK, clears the marker and leaves 244 = 0 (INV-NO-SILENT-OVERRIDE)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore: the 6-slot 256-261 restore write is acknowledged but not applied (every attempt)",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); the inverter "
                  "acknowledges every 256x6 block write without applying it (synthetic Modbus outcome policy)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (!contain && id(dump_restore_foreign_mask) == 0 && m != 0) m = 0x3F;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:256x6": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 1000, "257": 1000, "258": 1000, "259": 1000, "260": 1000, "261": 1000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": False}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "RESTORED OK with the marker cleared while 256-261 stay at the lease power (the C6 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the 256-261 readback mismatch fails both attempts, "
                                   "operator lockout after the second mismatch",
     "notes": "Derived from FW:20016-20043 (244 proven: no containment; nothing FOREIGN: the full 6-slot write, FW:20035), "
              "FW:20328-20342 (a written slot whose readback differs -> write_failed, mismatch) and FW:20482-20507. The "
              "C6 mutant (FW:20336 compare disabled) reports RESTORED OK, clears the marker and leaves 256-261 = 1000 W "
              "(INV-NO-SILENT-OVERRIDE)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b2", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN slot: per-slot plan, then single-slot (260) retries acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); the 260 write first errors, then every 260 write is "
                  "acknowledged but not applied (synthetic Modbus outcome policy)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:260": ["error", "ack_not_applied", "ack_not_applied"]}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 1000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 1}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the single-slot retry is taken as verified: the FOREIGN lockout claims ECCO's own settings "
                        "'restored and verified' while 260 still holds the lease power (the C6 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the single-slot readback mismatch fails both "
                                   "single-slot retries, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN), FW:20027-20035 "
              "(a FOREIGN slot is never written; with one, the plan is per slot), FW:20087-20314 (per-slot writes; an "
              "error stops the rest: comms path, backoff FW:20508-20519), then the retries: 256-259 read ORIGINAL, so the "
              "plan is 260 alone (wmask 0x10), FW:20335-20341 (its readback mismatch) and FW:20482-20501. Under C6 the "
              "first single-slot retry ends in the FOREIGN lockout text 'restored and verified' (FW:20460-20481)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-256", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261: slot 256 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every single-register write of 256 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:256x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 0) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:256x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 1000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 256's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 256 still holds the lease power (the C6k0 and C6s0 mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 256's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 256 at FW:20089), FW:20316-20341 (the 256x6 "
              "readback: slot 256's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 256 alone (wmask 0x01). Under C6k0 and C6s0 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-257", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261: slot 257 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every single-register write of 257 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:257x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 1) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:257x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 1000, "258": 7000, "259": 8000, "260": 8000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 257's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 257 still holds the lease power (the C6k1 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 257's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 257 at FW:20127), FW:20316-20341 (the 256x6 "
              "readback: slot 257's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 257 alone (wmask 0x02). Under C6k1 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-258", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261: slot 258 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every single-register write of 258 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:258x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 2) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:258x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 1000, "259": 8000, "260": 8000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 258's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 258 still holds the lease power (the C6k2 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 258's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 258 at FW:20165), FW:20316-20341 (the 256x6 "
              "readback: slot 258's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 258 alone (wmask 0x04). Under C6k2 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-259", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261: slot 259 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every single-register write of 259 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:259x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 3) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:259x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 1000, "260": 8000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 259's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 259 still holds the lease power (the C6k3 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 259's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 259 at FW:20203), FW:20316-20341 (the 256x6 "
              "readback: slot 259's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 259 alone (wmask 0x08). Under C6k3 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-260", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261: slot 260 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every single-register write of 260 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:260x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 4) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:260x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 1000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 260's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 260 still holds the lease power (the C6k4 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 260's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 260 at FW:20241), FW:20316-20341 (the 256x6 "
              "readback: slot 260's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 260 alone (wmask 0x10). Under C6k4 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b3-261", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 256: slot 261 acknowledged but not applied in the per-slot plan and its single-slot retry",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 256 to 4000 W (FOREIGN); every single-register write of 261 is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:261x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 5) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 256, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:261x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 256 reads 4000W (original 8000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 4000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 1000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "slot 261's readback is not verified: the FOREIGN lockout claims ECCO's own settings 'restored and "
                        "verified' while 261 still holds the lease power (the C6k5 and C6s5 mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 261's readback mismatch fails the per-slot "
                                   "attempt and its single-slot retry, operator lockout; the FOREIGN 256 is never written",
     "notes": "Derived from FW:19856-19881 (a slot reading neither ORIGINAL nor an ECCO value is FOREIGN; the lease slots at "
              "1000 W are ECCO-owned), FW:20027-20035 (a FOREIGN slot is never written; with one, the plan is per slot), "
              "FW:20087-20314 (per-slot writes in address order; slot 261 at FW:20279), FW:20316-20341 (the 256x6 "
              "readback: slot 261's mismatch -> write_failed, mismatch) and FW:20482-20507 (first mismatch: one automatic "
              "retry; second: the durable operator lockout). The retry finds 244 and the other slots ORIGINAL, so the "
              "plan is 261 alone (wmask 0x20). Under C6k5 and C6s5 the first attempt ends in the FOREIGN lockout "
              "text 'restored and verified' (FW:20373-20377, FW:20460-20481; its detail FW:19864, ceiling and pending "
              "the START ceiling 1000 W, FW:18452, FW:18496)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b4-ct", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven) with a FOREIGN 261: slot 258's floor write acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every 244 write and every single-register write of 258 is "
                  "acknowledged but not applied (synthetic Modbus outcome policies 'write:244x1', 'write:258x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool contain = !id(dump_restore_244_ok);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:258x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; export may continue; NOT CONTAINED: 261=4000W"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 261=4000W"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 500, "257": 500, "258": 1000, "259": 500, "260": 500, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_restore_contained", "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_restore_contained": False, "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed although slot 258's floor write did not land: 'ECCO's own at 500 W' "
                        "while 258 holds the lease power and 244 stays at Allow Export (the C6bf and C6lt mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - slot 258's readback mismatch sets block_failed, so "
                                   "dump_restore_contained stays clear and every status says 'export may continue' and "
                                   "names the FOREIGN 261 NOT CONTAINED; operator lockout after the second mismatch",
     "notes": "Derived from FW:19835-19845 (244 reads ECCO's Allow Export 0: action 1, export unverified), FW:19856-19881 "
              "(261 at 4000 W is FOREIGN and named '261=4000W'; the lease slots at 1000 W are ECCO-owned), FW:19982-19985 "
              "(244's unapplied write fails its readback), FW:20019-20043 (244 not proven: every non-FOREIGN slot is "
              "contained at min(original, 500 W); with a FOREIGN slot wmask is not 0x3F, so the slots are written one by "
              "one, FW:20087-20314), FW:20335-20341 (258 reads 1000 W, not 500 W: block_failed, write_failed, mismatch), "
              "FW:20372 (block_failed: dump_restore_contained stays clear), FW:20449-20454 (the suffix '; 244 NOT proven "
              "off; export may continue; NOT CONTAINED: 261=4000W'), FW:20482-20507 (one automatic retry, then the "
              "operator lockout) and FW:20535-20550 (the operator wait keeps the suffix). Under C6bf (FW:20337 dropped) "
              "and C6lt (1000 < 500 is false) block_failed stays clear: dump_restore_contained is set and the status "
              "claims \"ECCO's own at 500 W\" while 258 holds 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b4-cb", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven), nothing FOREIGN: the 6-slot floor block acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); every 244 write and "
                  "every 256x6 block write is acknowledged but not applied (synthetic Modbus outcome policies "
                  "'write:244x1', 'write:256x6'); no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "contained = \"; register 244 is NOT proven out of Allow Export - export may continue\";"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:256x6": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 is NOT proven out of Allow Export - export may continue"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 1000, "257": 1000, "258": 1000, "259": 1000, "260": 1000, "261": 1000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_restore_contained", "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_restore_contained": False, "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed although the 6-slot floor block did not land: 'held at the 500 W "
                        "floor' while 256-261 hold the lease power and 244 stays at Allow Export (the C6bf and C6lt "
                        "mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the block's readback mismatch sets block_failed, so "
                                   "dump_restore_contained stays clear and every status says 'export may continue'; "
                                   "operator lockout after the second mismatch",
     "notes": "Derived from FW:19835-19845, FW:19856-19881 (every lease slot ECCO-owned, nothing FOREIGN, so no slot is "
              "named NOT CONTAINED: dump_restore_uncontained empty, FW:19879), FW:19982-19985, FW:20019-20043 (244 not "
              "proven: every slot at min(original, 500 W); the containment term of FW:20031 makes wmask 0x3F), "
              "FW:20045-20086 (the 6-slot block write), FW:20335-20341 (every slot reads 1000 W, not 500 W: "
              "block_failed), FW:20372, FW:20457-20458 (the suffix '; register 244 is NOT proven out of Allow Export - "
              "export may continue'), FW:20482-20507 and FW:20535-20550 (FW:20545-20546). Under C6bf and C6lt "
              "dump_restore_contained is set and the status claims 'held at the 500 W floor' (FW:20455-20456) with all "
              "six slots at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b4-co", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven) with a FOREIGN 261: 256 back at its ORIGINAL, its floor write acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has put 256 back to its ORIGINAL 8000 W and changed 261 to 4000 W (FOREIGN); every 244 write and "
                  "every single-register write of 256 is acknowledged but not applied (synthetic Modbus outcome policies "
                  "'write:244x1', 'write:256x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (!is_foreign && (contain || ((id(dump_restore_owned_mask) >> i) & 1) != 0)) m = (uint8_t) (m | (1 << i));"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 256, "value": 8000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:256x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; export may continue; NOT CONTAINED: 261=4000W"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 261=4000W"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 8000, "257": 500, "258": 500, "259": 500, "260": 500, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_restore_contained", "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_restore_contained": False, "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed although 256 (at its ORIGINAL, so not ECCO-owned, but written to the "
                        "floor by the containment) did not take the floor value: 'ECCO's own at 500 W' while 256 holds "
                        "8000 W and 244 stays at Allow Export (the C6om, C6bf and C6lt mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the readback checks every slot written this attempt "
                                   "(the write mask, which in containment includes the ORIGINAL 256), so 256's mismatch "
                                   "sets block_failed and every status says 'export may continue'; operator lockout "
                                   "after the second mismatch",
     "notes": "Derived from FW:19856-19881 (256 reads its ORIGINAL: neither owned nor FOREIGN, so dump_restore_owned_mask "
              "lacks it; 261 FOREIGN), FW:19982-19985, FW:20019-20043 (244 not proven: wmask = every non-FOREIGN slot, "
              "FW:20031, 256 included although not owned), FW:20087-20314, FW:20331-20341 (the compare uses "
              "dump_restore_wmask: 256 reads 8000 W, not 500 W -> block_failed), FW:20372, FW:20449-20454, "
              "FW:20482-20507 and FW:20535-20550. The inverter's change and the End are at the same instant, so no "
              "configuration poll sees it first (the active drift check FW:24396-24424). Under C6om (FW:20336 with the "
              "owned mask) 256 is never compared: dump_restore_contained is set and the status claims \"ECCO's own at "
              "500 W\" while 256 holds 8000 W; C6bf and C6lt give the same."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b5-lo", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261 on a site whose 259 ORIGINAL (600 W) is below the 1000 W lease value: 259 acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL with 259 = 600 W); at the "
                  "End the inverter itself has changed 261 to 4000 W (FOREIGN); every single-register write of 259 is "
                  "acknowledged but not applied (synthetic Modbus outcome policy 'write:259x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 3) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"bank": {"259": 600}},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:259x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 1000, "260": 8000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a readback ABOVE the expected value is not taken as a mismatch: the FOREIGN lockout claims ECCO's "
                        "own settings 'restored and verified' while 259 holds the 1000 W lease power against its 600 W "
                        "original (the C6lt mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - 259's readback (1000 W) differs from its expected "
                                   "600 W, so the per-slot attempt and its single-slot retry fail, operator lockout; the "
                                   "FOREIGN 261 is never written",
     "notes": "Derived from FW:18244-18250 (the START snapshot takes 259's 600 W as its ORIGINAL; no range check on "
              "256-261), FW:18578-18584 (the START writes its 1000 W ceiling, FW:18434-18452, into all six slots), "
              "FW:19856-19881 (259 at 1000 W is ECCO-owned; 261 FOREIGN), FW:20027-20035 (the per-slot plan), "
              "FW:20087-20314 (slot 259 at FW:20203, written 600 W), FW:20335-20341 (259 reads 1000 W, not 600 W: "
              "mismatch) and FW:20482-20507; the retry finds 244 and the other slots ORIGINAL, so the plan is 259 alone "
              "(wmask 0x08). Under C6lt (FW:20336 '<': 1000 < 600 is false) the first attempt ends in the FOREIGN "
              "lockout text 'restored and verified' (FW:20373-20377, FW:20460-20481) with 259 at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b6-ok", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore of pairwise-distinct 256-261 originals (3000/8000/7000/6000/4500/5000 W), nothing FOREIGN, no fault: one verified attempt",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL with pairwise-distinct "
                  "256-261 = 3000/8000/7000/6000/4500/5000 W); no fault, no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (!contain && id(dump_restore_foreign_mask) == 0 && m != 0) m = 0x3F;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_status).publish_state(\"RESTORED OK - original inverter settings verified\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"bank": {"256": 3000, "257": 8000, "258": 7000, "259": 6000, "260": 4500, "261": 5000}},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORE VERIFY FAILED - snapshot retained; watchdog will retry once automatically"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 3000, "257": 8000, "258": 7000, "259": 6000, "260": 4500, "261": 5000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified"]},
                 "op": "==", "value": {"dump_snapshot_valid": False, "dump_operator_needed": False,
                                       "dump_verify_mismatch_count": 0, "dump_export_unverified": False}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a correct restore is reported as a verify mismatch and retried ('RESTORE VERIFY FAILED'): the "
                        "readback compares a slot with another slot's original (the C6r1, C6r4 and C6v34 mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - every slot's readback is compared with its own "
                                   "original, so the fault-free restore verifies in one attempt: RESTORED OK, marker CLEAR",
     "notes": "Derived from FW:18244-18250 (the START snapshot takes the distinct originals), FW:18578-18584 (the lease "
              "writes 1000 W into all six slots), FW:19835-19845 (244 reads ECCO's 0: written and proven, "
              "FW:19925-19988), FW:19856-19881 (every slot reads 1000 W: ECCO-owned, nothing FOREIGN), FW:20027-20043 "
              "(no containment, nothing FOREIGN: wmask 0x3F, FW:20035; v0..v5 the originals in slot order, "
              "FW:20036-20041), FW:20045-20086 (the 6-slot block write), FW:20331-20341 (v[] = v0..v5 in slot order: each "
              "slot compared with its own original, no mismatch) and FW:20378-20419 (RESTORED OK, marker CLEAR). Under "
              "C6r1 / C6r4 (257 / 260 compared with 256's / 259's original) and C6v34 (259 and 260 swapped) the readback "
              "mismatches: 'RESTORE VERIFY FAILED' (FW:20502-20506), then a second attempt at the next watchdog tick "
              "that finds every slot ORIGINAL, writes nothing (FW:20035 needs m != 0; FW:20318) and completes."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b6-x257", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261 on pairwise-distinct originals whose 256 equals the 1000 W lease value: 257 acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL with pairwise-distinct "
                  "256-261 = 1000/8000/7000/6000/4500/5000 W); at the End the inverter itself has changed 261 to 4000 W "
                  "(FOREIGN); every single-register write of 257 is acknowledged but not applied (synthetic Modbus outcome "
                  "policy 'write:257x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 1) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"bank": {"256": 1000, "257": 8000, "258": 7000, "259": 6000, "260": 4500, "261": 5000}},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:257x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 1000, "257": 1000, "258": 7000, "259": 6000, "260": 4500, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "257's readback (1000 W) is compared with 256's expected value (its original 1000 W) instead of "
                        "its own 8000 W: the FOREIGN lockout claims ECCO's own settings 'restored and verified' while 257 "
                        "holds the lease power (the C6r1 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - 257's readback is compared with its own original "
                                   "8000 W: the per-slot attempt and its single-slot retry fail, operator lockout; 256 (at "
                                   "its ORIGINAL) is not written, the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (256 reads its ORIGINAL 1000 W, which equals the lease value: neither owned "
              "nor FOREIGN, FW:19860-19867; 257-260 at 1000 W are ECCO-owned; 261 FOREIGN), FW:20027-20035 (the "
              "per-slot plan 257-260, wmask 0x1E), FW:20087-20314 (slot 257 at FW:20127), FW:20331-20341 (v[] in slot "
              "order: 257 reads 1000 W against its own 8000 W -> mismatch) and FW:20482-20507; the retry finds 244, 256 "
              "and 258-260 ORIGINAL, so the plan is 257 alone (wmask 0x02). Under C6r1 (257 compared with v[0], 256's "
              "1000 W) the first attempt ends in the FOREIGN lockout text 'restored and verified' (FW:20373-20377, "
              "FW:20460-20481) with 257 at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b6-x260", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore with a FOREIGN 261 on pairwise-distinct originals whose 259 equals the 1000 W lease value: 260 acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL with pairwise-distinct "
                  "256-261 = 3000/8000/7000/1000/4500/5000 W); at the End the inverter itself has changed 261 to 4000 W "
                  "(FOREIGN); every single-register write of 260 is acknowledged but not applied (synthetic Modbus outcome "
                  "policy 'write:260x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "bool is_foreign = ((id(dump_restore_foreign_mask) >> i) & 1) != 0;     // a FOREIGN slot is never written"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> 4) & 1) != 0 && !id(dump_restore_block_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"bank": {"256": 3000, "257": 8000, "258": 7000, "259": 1000, "260": 4500, "261": 5000}},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:260x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - ECCO's own settings restored and verified; external change NOT overwritten (register 261 reads 4000W (original 5000W; ECCO's ceiling 1000W, pending 1000W)); use Force Restore Original or Accept Current State"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 3000, "257": 8000, "258": 7000, "259": 1000, "260": 1000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_comms_restore_attempts"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_comms_restore_attempts": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "260's readback (1000 W) is compared with 259's expected value (its original 1000 W) instead of "
                        "its own 4500 W: the FOREIGN lockout claims ECCO's own settings 'restored and verified' while 260 "
                        "holds the lease power (the C6r4 and C6v34 mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - 260's readback is compared with its own original "
                                   "4500 W: the per-slot attempt and its single-slot retry fail, operator lockout; 259 (at "
                                   "its ORIGINAL) is not written, the FOREIGN 261 is never written",
     "notes": "Derived from FW:19856-19881 (259 reads its ORIGINAL 1000 W, which equals the lease value: neither owned "
              "nor FOREIGN, FW:19860-19867; 256-258 and 260 at 1000 W are ECCO-owned; 261 FOREIGN), FW:20027-20035 (the "
              "per-slot plan 256-258 and 260, wmask 0x17), FW:20087-20314 (slot 260 at FW:20241), FW:20331-20341 (v[] "
              "in slot order: 260 reads 1000 W against its own 4500 W -> mismatch) and FW:20482-20507; the retry finds "
              "244, 256-259 ORIGINAL, so the plan is 260 alone (wmask 0x10). Under C6r4 (260 compared with v[3], 259's "
              "1000 W) and C6v34 (v[4] initialised from dump_restore_v3, 259's 1000 W) the first attempt ends in the "
              "FOREIGN lockout text 'restored and verified' (FW:20373-20377, FW:20460-20481) with 260 at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b7-rbnr", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven), nothing FOREIGN: the 6-slot floor block acknowledged but not applied and its 256-261 readback gets no response",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); every 244 write and "
                  "every 256x6 block write is acknowledged but not applied and every 256x6 readback gets no response "
                  "(synthetic Modbus outcome policies 'write:244x1', 'write:256x6', 'read:256x6'); no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "} else if (id(dump_restore_mismatch_this_attempt)) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "contained = \"; register 244 is NOT proven out of Allow Export - export may continue\";"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:256x6": "ack_not_applied", "read:256x6": "no_response"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 is NOT proven out of Allow Export - export may continue"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 1000, "257": 1000, "258": 1000, "259": 1000, "260": 1000, "261": 1000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_comms_restore_attempts", "dump_restore_contained",
                                                          "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_comms_restore_attempts": 0, "dump_restore_contained": False,
                                       "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed although the 256-261 readback never answered: 'held at the 500 W "
                        "floor' while the unapplied floor block leaves 256-261 at the lease power and 244 stays at "
                        "Allow Export (the C6rh and C6rn mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the readback's no-response handler sets "
                                   "block_failed, so dump_restore_contained stays clear and every status says 'export "
                                   "may continue'; the 244 mismatch takes the mismatch path: operator lockout after the "
                                   "second mismatch",
     "notes": "Derived from FW:19835-19845 (244 reads ECCO's Allow Export 0: action 1, export unverified), FW:19856-19881 "
              "(every lease slot ECCO-owned, nothing FOREIGN: dump_restore_uncontained empty, FW:19879), FW:19982-19985 "
              "(244's unapplied write fails its readback: write_failed and dump_restore_mismatch_this_attempt), "
              "FW:20019-20043 (244 not proven: every slot at min(original, 500 W); the containment term of FW:20031 "
              "makes wmask 0x3F; dump_restore_contain set, m != 0), FW:20045-20086 (the 6-slot floor block, "
              "acknowledged: on_response, no block_failed), FW:20316-20325 (the readback runs: wmask != 0, block_failed "
              "clear), FW:20348-20352 (no response: block_failed and write_failed), FW:20372 (block_failed: "
              "dump_restore_contained stays clear), FW:20482-20507 (the 244 mismatch takes the mismatch path: one "
              "automatic retry, then the operator lockout; the comms path FW:20508-20519 is not reached, comms attempts "
              "0), FW:20457-20458 (the suffix '; register 244 is NOT proven out of Allow Export - export may continue') "
              "and FW:20535-20550 (FW:20545-20546). Under C6rh and C6rn (FW:20352 without block_failed) "
              "dump_restore_contained is set and the status claims 'held at the 500 W floor' (FW:20455-20456) with all "
              "six slots at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b7-rber", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven) with a FOREIGN 261: slot 258's floor write acknowledged but not applied and the 256-261 readback errors",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed 261 to 4000 W (FOREIGN); every 244 write and every single-register write of 258 is "
                  "acknowledged but not applied and every 256x6 readback returns a Modbus error (synthetic Modbus outcome "
                  "policies 'write:244x1', 'write:258x1', 'read:256x6')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "} else if (id(dump_restore_mismatch_this_attempt)) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "contained = std::string(\"; 244 NOT proven off\") +"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:258x1": "ack_not_applied", "read:256x6": "error"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; export may continue; NOT CONTAINED: 261=4000W"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 261=4000W"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 500, "257": 500, "258": 1000, "259": 500, "260": 500, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_comms_restore_attempts", "dump_restore_contained",
                                                          "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_comms_restore_attempts": 0, "dump_restore_contained": False,
                                       "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed although the 256-261 readback failed: \"ECCO's own at 500 W\" while "
                        "slot 258's unapplied floor write leaves it at the lease power and 244 stays at Allow Export (the "
                        "C6rh mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the readback's error handler sets block_failed, so "
                                   "dump_restore_contained stays clear and every status says 'export may continue' and "
                                   "names the FOREIGN 261 NOT CONTAINED; operator lockout after the second mismatch",
     "notes": "Derived from FW:19835-19845, FW:19856-19881 (261 at 4000 W is FOREIGN and named '261=4000W'; the lease "
              "slots at 1000 W are ECCO-owned), FW:19982-19985 (244's unapplied write fails its readback: write_failed "
              "and dump_restore_mismatch_this_attempt), FW:20019-20043 (244 not proven: every non-FOREIGN slot "
              "contained at min(original, 500 W); with a FOREIGN slot wmask is 0x1F, written one by one, "
              "FW:20087-20314; every write acknowledged, so no block_failed), FW:20316-20325 (the readback runs), "
              "FW:20343-20347 (an error: block_failed and write_failed), FW:20372 (dump_restore_contained stays clear), "
              "FW:20482-20507 (the 244 mismatch: the mismatch path, one automatic retry, then the operator lockout; "
              "comms attempts 0), FW:20449-20454 (the suffix '; 244 NOT proven off; export may continue; NOT CONTAINED: "
              "261=4000W') and FW:20535-20550 (FW:20538-20542). Under C6rh (FW:20347 without block_failed) "
              "dump_restore_contained is set and the status claims \"ECCO's own at 500 W\" while 258 holds 1000 W; "
              "C6rn edits only the no-response handler (FW:20352), so this error outcome is unchanged under it."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b7-cmnr", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment by a comms failure (the 244 verify read errors after the 244 write landed): the 6-slot floor block acknowledged but not applied and its 256-261 readback gets no response",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); the one verify read of "
                  "244 after the restore write returns a Modbus error, the one 6-slot block write after the End is "
                  "acknowledged but not applied and the one 256x6 readback after the End gets no response (synthetic "
                  "Modbus outcome policies 'read:244x1', 'write:256x6', 'read:256x6'); no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_244_ok) = id(dump_restore_244_action) != 1 || !id(dump_write_failed);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"read:244x1": ["error"], "write:256x6": ["ack_not_applied"], "read:256x6": ["no_response"]}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff; register 244 is NOT proven out of Allow Export - export may continue"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 1000, "257": 1000, "258": 1000, "259": 1000, "260": 1000, "261": 1000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_comms_restore_attempts",
                                                          "dump_export_unverified", "dump_verify_mismatch_count",
                                                          "dump_restore_contained", "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_comms_restore_attempts": 1,
                                       "dump_export_unverified": True, "dump_verify_mismatch_count": 0,
                                       "dump_restore_contained": False, "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the containment is claimed on the comms path although the 256-261 readback never answered: "
                        "'held at the 500 W floor' while the unapplied floor block leaves 256-261 at the lease power (the "
                        "C6rh and C6rn mutants)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the readback's no-response handler sets "
                                   "block_failed, so dump_restore_contained stays clear: the comms-path status says "
                                   "'export may continue'; the retry after the backoff restores ORIGINAL",
     "notes": "Derived from FW:19835-19845 (244 reads ECCO's Allow Export 0: action 1, export unverified), FW:19925-19962 "
              "(the 244 write lands), FW:19989-19993 (the verify read's error sets write_failed and no mismatch flag), "
              "FW:20019-20043 (244 not proven: containment; nothing FOREIGN, the containment term makes wmask 0x3F), "
              "FW:20045-20086 (the 6-slot floor block, acknowledged: no block_failed), FW:20316-20325 (the readback "
              "runs), FW:20348-20352 (no response: block_failed and write_failed), FW:20372 (dump_restore_contained "
              "stays clear), FW:20482 and FW:20508-20519 (no mismatch this attempt: the comms path, comms attempts 1, "
              "backoff 15 s), FW:20457-20458 (the suffix '; register 244 is NOT proven out of Allow Export - export "
              "may continue') and FW:20434-20442 (a comms failure never locks). The document ends 5 s after the End "
              "(before any retry); the suite continues to the automatic retry, whose pre-read finds 244 ORIGINAL "
              "(action 0, export no longer unverified, FW:19835-19845) and 256-261 at 1000 W (ECCO's own), so it "
              "restores ORIGINAL (FW:20019, FW:20035) and completes (FW:20378-20419). Under C6rh and C6rn (FW:20352 "
              "without block_failed) dump_restore_contained is set and the comms-path status claims 'held at the 500 "
              "W floor' (FW:20455-20456) with all six slots at 1000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b7-ab", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven), two attempts: the first contains and verifies, then 258 is back at its ORIGINAL and the second floor block is acknowledged but not applied",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); every 244 write is "
                  "acknowledged but not applied, the first 6-slot block write after the End lands and the second is "
                  "acknowledged but not applied (synthetic Modbus outcome policies 'write:244x1', 'write:256x6'); right "
                  "after the first restore attempt the inverter itself puts 258 back to its ORIGINAL 7000 W",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_contained) = false;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "contained = \"; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor\";"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied", "write:256x6": ["ok", "ack_not_applied"]}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 258, "value": 7000, "actor": "inverter"}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "RESTORE VERIFY FAILED - snapshot retained; watchdog will retry once automatically; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 is NOT proven out of Allow Export - export may continue"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 500, "257": 500, "258": 7000, "259": 500, "260": 500, "261": 500}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_restore_contained", "dump_restore_block_failed"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_restore_contained": False, "dump_restore_block_failed": True}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the first attempt's containment claim is carried into the failed second attempt: 'held at the "
                        "500 W floor' in the operator lockout while 258 holds 7000 W and 244 stays at Allow Export (the "
                        "C6rs mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - dump_restore_contained is reset when each attempt "
                                   "starts, so the second attempt's failed readback leaves it clear and its statuses say "
                                   "'export may continue'; operator lockout after the second mismatch",
     "notes": "Derived from FW:19835-19845 and FW:19856-19881 (attempt 1: 244 at ECCO's 0, every slot ECCO-owned at "
              "1000 W, nothing FOREIGN), FW:19982-19985 (244's unapplied write: write_failed, a mismatch), "
              "FW:20019-20043 (containment: wmask 0x3F, every slot at 500 W), FW:20045-20086 (the first floor block "
              "lands), FW:20316-20342 (its readback verifies: block_failed clear), FW:20372 (dump_restore_contained "
              "set), FW:20455-20456 and FW:20502-20506 (the first mismatch: 'RESTORE VERIFY FAILED ...; register 244 "
              "NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor', true then: 256-261 "
              "at 500 W). The inverter's change follows the End's attempt; the lease is over (dump_restore_requested "
              "set, FW:20606), so the ACTIVE drift check never sees it (FW:24268-24272, FW:24396-24424). Attempt 2 at "
              "the next watchdog tick (FW:24221-24248): FW:19819 resets dump_restore_contained; the pre-read finds 244 "
              "at 0 and 258 at its ORIGINAL (neither owned nor FOREIGN, FW:19860-19867), the others at the 500 W floor "
              "(ECCO's own); the containment writes every non-FOREIGN slot (FW:20031: wmask 0x3F); the floor block is "
              "acknowledged but not applied; the readback finds 258 at 7000 W, not 500 W (FW:20335-20341: "
              "block_failed), so dump_restore_contained stays clear (FW:20372); the second mismatch gives the operator "
              "lockout (FW:20484-20501) with '; register 244 is NOT proven out of Allow Export - export may continue' "
              "(FW:20457-20458), and the operator wait the same (FW:20535-20550). Under C6rs (FW:19819 dropped) "
              "dump_restore_contained keeps attempt 1's value and the lockout and the operator wait claim 'held at the "
              "500 W floor' with 258 at 7000 W."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-b7-af", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore in containment (244 not proven) with every 256-261 slot FOREIGN: nothing to contain",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); at the End the inverter "
                  "itself has changed all six of 256-261 to 4000 W (FOREIGN); every 244 write is acknowledged but not "
                  "applied (synthetic Modbus outcome policy 'write:244x1')",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_contain) = contain && m != 0;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_uncontained) = un.size() <= 52 ? un : un_regs;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(dump_restore_contain) && !id(dump_restore_block_failed)) id(dump_restore_contained) = true;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 256, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 257, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 258, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 259, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 260, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "set_register", "args": {"addr": 261, "value": 4000, "actor": "inverter"}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"write:244x1": "ack_not_applied"}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 180}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; export may continue; NOT CONTAINED: 256 257 258 259 260 261"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "OPERATOR DECISION REQUIRED - repeated verify mismatch restoring Dump to Grid; use Force Restore Original or Accept Current State; 244 NOT proven off; ECCO's own at 500 W; NOT CONTAINED: 256 257 258 259 260 261"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 4000, "257": 4000, "258": 4000, "259": 4000, "260": 4000, "261": 4000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_operator_needed",
                                                          "dump_verify_mismatch_count", "dump_export_unverified",
                                                          "dump_restore_contain", "dump_restore_contained",
                                                          "dump_restore_wmask"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_operator_needed": True,
                                       "dump_verify_mismatch_count": 2, "dump_export_unverified": True,
                                       "dump_restore_contain": False, "dump_restore_contained": False,
                                       "dump_restore_wmask": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a containment is claimed although every slot is FOREIGN and nothing was written: \"ECCO's own at "
                        "500 W\" with no ECCO-owned slot while 244 stays at Allow Export (the C6m0 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - with every slot FOREIGN the containment plan is "
                                   "empty (m == 0), so dump_restore_contain stays clear and every status says 'export "
                                   "may continue' and names all six NOT CONTAINED; operator lockout after the second "
                                   "244 mismatch",
     "notes": "Derived from FW:19835-19845 (244 reads ECCO's Allow Export 0: action 1, export unverified), FW:19856-19881 "
              "(each slot at 4000 W is neither ORIGINAL nor ECCO's 1000 W ceiling / pending nor its 500 W floor: "
              "FOREIGN; the list '256=4000W ... 261=4000W' is 59 characters, over 52, so dump_restore_uncontained "
              "holds the register numbers alone, FW:19879), FW:19982-19985 (244's unapplied write: write_failed, a "
              "mismatch), FW:20019-20043 (244 not proven: contain, but every slot FOREIGN, so m == 0 and "
              "dump_restore_contain stays clear, FW:20043; wmask 0), FW:20045 / FW:20087-20314 (no 256-261 write), "
              "FW:20316-20318 (no readback: wmask 0), FW:20372 (dump_restore_contained stays clear), FW:20373 "
              "(write_failed: no FOREIGN lockout), FW:20449-20454 (the suffix '; 244 NOT proven off; export may "
              "continue; NOT CONTAINED: 256 257 258 259 260 261'), FW:20482-20507 (one automatic retry, the same; then "
              "the operator lockout) and FW:20535-20550 (FW:20538-20542). Under C6m0 (FW:20043 without 'm != 0') "
              "dump_restore_contain and then dump_restore_contained are set (nothing written, nothing read back: "
              "block_failed clear) and the status claims \"ECCO's own at 500 W\" with no ECCO-owned slot."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-c", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore: the register-244 verify read returns an error after the 244 write landed",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); the one verify read "
                  "of 244 after the restore write returns a Modbus error (synthetic outcome policy)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_244_ok) = id(dump_restore_244_action) != 1 || !id(dump_write_failed);"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"read:244x1": ["error"]}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff; register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 500, "257": 500, "258": 500, "259": 500, "260": 500, "261": 500}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_comms_restore_attempts",
                                                          "dump_export_unverified", "dump_verify_mismatch_count"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_comms_restore_attempts": 1,
                                       "dump_export_unverified": True, "dump_verify_mismatch_count": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a failed 244 verify read is taken as success: RESTORED OK and the marker cleared with 244 never "
                        "read back (the MC244 error-branch mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the failed verify read fails the attempt (comms path, "
                                   "backoff), 244 unproven so 256-261 are contained; the retry completes",
     "notes": "Derived from FW:19989-20003 (a verify-read error sets dump_write_failed), FW:20019-20043 (244 not proven -> "
              "contain at the 500 W floor), FW:20508-20519 (comms path: backoff 15 s, retries kept) and FW:20455-20456. "
              "The document ends 5 s after the End (before any retry); the suite continues to the automatic retry. M9 / "
              "C6 cannot change this path (their compares run only on_response)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-09-c2", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P1", "finding_priority": None,
     "title": "Dump restore: the 256-261 verify read gets no response after the block write landed",
     "ownership": "ECCO-owned Dump lease (owner START, owner End & Restore; synthetic SITE ORIGINAL); the one 256-261 "
                  "verify read after the restore write gets no response (synthetic outcome policy)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 120, "do": "modbus_policy", "args": {"table": {"read:256x6": ["no_response"]}}},
                 {"at_s": 120, "do": "dump_end", "args": {}},
                 {"at_s": 120, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "not_contains",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "RESTORE WRITE FAILED - inverter did not respond or refused; snapshot retained; will retry automatically with backoff"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "globals", "args": {"names": ["dump_snapshot_valid", "dump_comms_restore_attempts",
                                                          "dump_export_unverified", "dump_verify_mismatch_count"]},
                 "op": "==", "value": {"dump_snapshot_valid": True, "dump_comms_restore_attempts": 1,
                                       "dump_export_unverified": False, "dump_verify_mismatch_count": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-SILENT-OVERRIDE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a failed 256-261 verify read is taken as success: RESTORED OK and the marker cleared with the "
                        "written values never read back (the MC256 error-branch mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the failed verify read fails the attempt (comms path, "
                                   "backoff); the retry finds ORIGINAL, writes nothing and completes",
     "notes": "Derived from FW:20343-20357 (a verify-read failure sets block_failed and write_failed), FW:20508-20519 (comms "
              "path) and FW:19960-19988 (244 written and proven first: no containment). The values landed but are "
              "unverified; the status claims no success. The document ends 5 s after the End; the suite continues to the "
              "retry (pre-read finds ORIGINAL: owned mask 0, nothing written, FW:20017-20044, then RESTORED OK)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-10-a", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Dump START while Free Power is RESTORE_REQUIRED (final verify read failed) with its registers at ORIGINAL",
     "ownership": "ECCO-owned Free Power lease ended by the owner; its final 256-279 verify read fails (synthetic Modbus "
                  "error) after every restore write landed; the owner presses Dump to Grid Start at the same instant",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "// Register 244 standalone proof transaction: Dump also"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(free_power_status).publish_state(\"RESTORE VERIFY ERROR - snapshot retained for retry\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "modbus_policy", "args": {"table": {"read:256x24": ["ok", "error"]}}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 90, "do": "modbus_policy", "args": {}},
                 {"at_s": 90, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 90, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "REJECTED - Free Power override/recovery owns inverter settings"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "ABSENT"},
                {"observe": "status", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE VERIFY ERROR - snapshot retained for retry"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268, 274, 275]}, "op": "==",
                 "value": {"230": 120, "232": 0, "244": 2, "256": 8000, "261": 5000, "268": 20, "274": 1, "275": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-ONE-LEASE", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the Dump lease starts while the Free Power lease is still active_persisted and RESTORE_REQUIRED "
                        "(two leases; Dump writes 256-261 under Free Power's marker: the M7 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the Free Power terms of the Dump START gate refuse",
     "notes": "Derived from FW:11322-11332 (a failed final 256-279 verify read: comms path, snapshot retained, backoff), "
              "FW:18060-18061 (gate terms) and FW:18890 (rejection text). Every Free Power owned register is back at "
              "ORIGINAL, so the TOU charge-flag walk (FW:18041) has no conflict and only the Free Power terms refuse."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-10-b", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Dump START while Free Power is PENDING_CLEAR (restore verified, durable clear not landed)",
     "ownership": "ECCO-owned Free Power lease ended by the owner; the restore verifies but the durable CLEAR of the used "
                  "fp.valid key does not land (synthetic NVS commit policy, twice); the owner presses Dump to Grid Start at "
                  "the same instant",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "// Register 244 standalone proof transaction: Dump also"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(free_power_status).publish_state(\"RESTORED OK - original inverter settings verified; durable recovery-marker clear pending, will retry\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "nvs_policy", "args": {"tag": "fp.valid", "state": 0, "mode": "not_landed", "times": 2}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 90, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 90, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "REJECTED - Free Power override/recovery owns inverter settings"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "ABSENT"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "PENDING_CLEAR"},
                {"observe": "globals", "args": {"names": ["free_power_snapshot_valid", "free_power_active_persisted"]},
                 "op": "==", "value": {"free_power_snapshot_valid": True, "free_power_active_persisted": False}},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268, 274, 275]}, "op": "==",
                 "value": {"230": 120, "232": 0, "244": 2, "256": 8000, "261": 5000, "268": 20, "274": 1, "275": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-2ND-RESTORER", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the Dump lease starts while Free Power still holds its snapshot and a pending durable clear (the "
                        "M7 mutant and the single-term variant without '!free_power_snapshot_valid')",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the snapshot_valid term of the Dump START gate refuses",
     "notes": "Derived from FW:11200-11206 (verified: active_persisted cleared), FW:11215-11222 (Phase C PENDING_CLEAR), "
              "FW:11256-11266 (Phase D not landed: snapshot_valid and the marker stay), FW:18061 and FW:18890. With "
              "active_persisted clear, only '!free_power_snapshot_valid' refuses: this document kills the M7b variant."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-10-c", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Dump START during the Free Power UNKNOWN lockout (NVS read error on the used fp.valid key at boot)",
     "ownership": "ECCO-owned Free Power lease completed (marker CLEAR); a power cut and a boot whose read of the used "
                  "fp.valid key fails (synthetic NVS boot fault); the owner then presses Dump to Grid Start",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "// Register 244 standalone proof transaction: Dump also"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 120, "do": "reboot", "args": {"nvs_fault": ["read_error", "fp.valid"]}},
                 {"at_s": 240, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 240, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "REJECTED - Free Power override/recovery owns inverter settings"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "ABSENT"},
                {"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268, 274, 275]}, "op": "==",
                 "value": {"230": 120, "232": 0, "244": 2, "256": 8000, "261": 5000, "268": 20, "274": 1, "275": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-LOCKOUT-QUIET", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the Dump lease starts and writes 244 / 256-261 while Free Power's obligation is UNKNOWN and its "
                        "domain locked (the M7 mutant and the single-term variant without '!free_power_snapshot_valid')",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the UNKNOWN lockout sets snapshot_valid and the "
                                   "Dump START gate's snapshot_valid term refuses",
     "notes": "Derived from FW:510-518 and FW:532-538 (read error: snapshot_valid + metadata_corrupt, 'cross-domain START "
              "gates see snapshot_valid'), FW:18061 and FW:18890. active_persisted is clear (restore_value no, not loaded), "
              "so only the snapshot_valid term refuses: this document kills the M7b variant."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-11-a", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Free Power marker NVS read error at boot on the used fp.valid key (record CLEAR): UNKNOWN lockout",
     "ownership": "ECCO-owned Free Power lease completed (marker CLEAR); a power cut and a boot whose read of the used "
                  "fp.valid key fails (synthetic NVS boot fault)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(free_power_status).publish_state(\"RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the record read as absent\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 120, "do": "reboot", "args": {"nvs_fault": ["read_error", "fp.valid"]}},
                 {"at_s": 240, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "globals", "args": {"names": ["free_power_snapshot_valid"]}, "op": "==",
                 "value": {"free_power_snapshot_valid": True}},
                {"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the record read as absent"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 261, 268, 274, 275]}, "op": "==",
                 "value": {"230": 120, "232": 0, "256": 8000, "261": 5000, "268": 20, "274": 1, "275": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-BOOT-MIRROR", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "an unreadable marker is read as CLEAR: no lockout although an obligation cannot be ruled out (the "
                        "C3 mutant)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - LOAD_READ_ERROR -> the SG-06 UNKNOWN lockout",
     "notes": "Derived from FW:507-518 and FW:522-538 (LOAD_READ_ERROR: snapshot_valid + metadata_corrupt, no Modbus, no "
              "commit, the record untouched), FW:1179-1183 (status) and FW:24119 (no restore while corrupt)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-11-b", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Free Power marker NVS read error at boot on the used fp.valid key (record RESTORE_REQUIRED): UNKNOWN lockout",
     "ownership": "ECCO-owned Free Power lease completed (marker CLEAR), then a second Free Power lease ACTIVE (marker "
                  "RESTORE_REQUIRED, override live) when the power is cut; the boot's read of fp.valid fails (synthetic "
                  "NVS boot fault)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(free_power_recovery_metadata_corrupt)) return false;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 120, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 150, "do": "reboot", "args": {"nvs_fault": ["read_error", "fp.valid"]}},
                 {"at_s": 270, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "globals", "args": {"names": ["free_power_snapshot_valid"]}, "op": "==",
                 "value": {"free_power_snapshot_valid": True}},
                {"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery state UNKNOWN (marker could not be read from NVS at boot); an obligation cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the record read as absent"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 261]}, "op": "==",
                 "value": {"230": 58, "232": 1, "256": 3000, "261": 3000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-BOOT-MIRROR", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "an unreadable marker is read as CLEAR while the override is live: the obligation is dropped "
                        "silently (the C3 mutant: INV-NO-SILENT-OVERRIDE, INV-BOOT-MIRROR)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - LOAD_READ_ERROR -> the SG-06 UNKNOWN lockout keeps "
                                   "the override visible and locks the domain",
     "notes": "Derived from FW:522-538, FW:1179-1183 and FW:24119; the live override values come from FW:9094-9097 (230 = "
              "lroundf(3000 W / 52 V) = 58 A) and FW:9108 (256-261 = 3000 W)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-11-c", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Free Power marker of the wrong size at boot on the used fp.valid key (record CLEAR): MALFORMED lockout",
     "ownership": "ECCO-owned Free Power lease completed (marker CLEAR); a power cut and a boot that finds a wrong-size "
                  "record under the used fp.valid key (synthetic NVS boot fault)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker is malformed (bad magic or unrecognised state); inverter writes locked\");"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "id(free_power_status).publish_state(\"RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 120, "do": "reboot", "args": {"nvs_fault": ["wrong_size", "fp.valid"]}},
                 {"at_s": 240, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "globals", "args": {"names": ["free_power_snapshot_valid"]}, "op": "==",
                 "value": {"free_power_snapshot_valid": True}},
                {"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "MALFORMED"},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 261, 268, 274, 275]}, "op": "==",
                 "value": {"230": 120, "232": 0, "256": 8000, "261": 5000, "268": 20, "274": 1, "275": 0}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-BOOT-MIRROR", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a wrong-size marker record is read as CLEAR: no lockout for a stored record that is not a marker "
                        "(the C7 mutant and its wrong-size-only variant C7ws)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - LOAD_WRONG_SIZE -> the MALFORMED lockout",
     "notes": "Derived from FW:515-518 ('A marker record of the wrong SIZE is something stored that is not a marker - "
              "malformed'), FW:526 and FW:539-550 (snapshot_valid + metadata_corrupt, the record left untouched), "
              "FW:1184-1190 (status) and FW:24119."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-11-d", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Free Power marker of the wrong size at boot on the used fp.valid key (record RESTORE_REQUIRED): MALFORMED lockout",
     "ownership": "ECCO-owned Free Power lease completed (marker CLEAR), then a second Free Power lease ACTIVE (override "
                  "live) when the power is cut; the boot finds a wrong-size record under fp.valid (synthetic NVS boot fault)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "ESP_LOGE(\"free_power\", \"RECOVERY BLOCKED - durable recovery marker is malformed (bad magic or unrecognised state); inverter writes locked\");"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "if (id(free_power_recovery_metadata_corrupt)) return false;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 90, "do": "fp_end", "args": {}},
                 {"at_s": 120, "do": "fp_start", "args": {"power_w": 3000, "minutes": 10}},
                 {"at_s": 150, "do": "reboot", "args": {"nvs_fault": ["wrong_size", "fp.valid"]}},
                 {"at_s": 270, "do": "run_for", "args": {"seconds": 5}}],
     "expect": [{"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "globals", "args": {"names": ["free_power_snapshot_valid"]}, "op": "==",
                 "value": {"free_power_snapshot_valid": True}},
                {"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "MALFORMED"},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 261]}, "op": "==",
                 "value": {"230": 58, "232": 1, "256": 3000, "261": 3000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-BOOT-MIRROR", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a wrong-size marker is read as CLEAR while the override is live: the obligation is dropped "
                        "silently (the C7 / C7ws mutants: INV-NO-SILENT-OVERRIDE, INV-BOOT-MIRROR)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - LOAD_WRONG_SIZE -> the MALFORMED lockout keeps the "
                                   "override visible and locks the domain",
     "notes": "Derived from FW:515-518, FW:526, FW:539-550, FW:1184-1190 and FW:24119; the live override values come from "
              "FW:9094-9097 and FW:9108."},
]
DRAFTS = {d["id"]: d for d in CORPUS_DRAFTS}


# =============================================================================================================================
# helpers (environment only; the firmware decides)
# =============================================================================================================================
def run_actions(w, actions: list) -> None:
    """Run action dicts on world w exactly as the replay engine does (advance_to each action's instant - a LIVE run - then
    the firmware tier's action with a deep copy of its args), without the engine's replay.action log events."""
    for i, a in enumerate(actions):
        due = U0 + a["at_s"]
        if due > w.t_utc:
            w.advance_to(due)
        elif due < w.t_utc - 1e-6:
            raise L.LabHarnessError(f"action {i} ({a['do']}) is due at +{a['at_s']} s but the clock is at +{w.t_utc - U0} s")
        L.ACTIONS[a["do"]](w, **copy.deepcopy(a["args"]))


def play(fw, actions: list, phase_ms: dict | None = None, world: dict | None = None) -> L.FirmwareWorld:
    """A fresh world (the replay factory's defaults: utc_start U0, seed 0, full boot) running `actions`; `world` is a corpus
    document's world kwargs (W6-1b: a synthetic bank override), its bank keys converted as the firmware replay factory
    converts them (_lab_fw.make_world: JSON keys are strings)."""
    kw = world_kwargs(world)
    w = L.FirmwareWorld(fw, utc_start=U0, seed=0, phase_ms=phase_ms, **kw)
    run_actions(w, actions)
    return w


def world_kwargs(world: dict | None) -> dict:
    """A document's world kwargs for a FirmwareWorld of the suite's own firmware text: a deep copy, the bank keys converted
    as _lab_fw.make_world does; the keys the engine or the suite pass themselves are refused (fail loud)."""
    kw = copy.deepcopy(world or {})
    bad = [k for k in ("fw", "utc_start", "seed", "phase_ms") if k in kw]
    if bad:
        raise L.LabHarnessError(f"world kwargs {bad} are not supported here")
    if "bank" in kw:
        kw["bank"] = {L._reg(a): v for a, v in kw["bank"].items()}
    return kw


def acts(cid: str) -> list:
    return copy.deepcopy(DRAFTS[cid]["actions"])


def last_seq(w, kind: str) -> int:
    evs = w.log.events(kind=kind)
    if not evs:
        raise L.LabHarnessError(f"no {kind} event in the log")
    return evs[-1]["seq"]


def after(w, seq: int, kind: str) -> list:
    return [e for e in w.log.events(kind=kind) if e["seq"] > seq]


def dump_statuses(w, seq: int) -> list:
    return [e["data"]["text"] for e in after(w, seq, "fw.status") if e["data"]["dom"] == "dump"]


def no_deferred(texts: list) -> list:
    """Status texts without the gate's END DEFERRED waiting texts (their presence depends on the watchdog phase)."""
    return [x for x in texts if not x.startswith(DEFERRED)]


def attempts(w, seq: int) -> list:
    """Every Dump restore attempt after seq starts with its ownership pre-read 244x18 (FW:19823-19827): [(t_utc, seq)]."""
    return [(e["t_utc"], e["seq"]) for e in after(w, seq, "fw.read")
            if e["data"]["addr"] == 244 and e["data"]["count"] == 18]


def attempt_writes(w, seq: int) -> list:
    """The writes of each restore attempt after seq: [[(addr, vals, outcome), ...] per attempt]."""
    starts = [s for _t, s in attempts(w, seq)] + [10 ** 12]
    wr = [x for x in w.writes() if x["seq"] > seq]
    return [[(x["addr"], x["vals"], x["outcome"]) for x in wr if a < x["seq"] < b] for a, b in zip(starts, starts[1:])]


def verified_claims(texts: list) -> list:
    return [x for x in texts if any(c in x for c in VERIFIED_CLAIMS)]


def truthful(w, texts: list) -> tuple[bool, str]:
    """Every verified-restore claim among `texts` must be backed by the bank: 244 and every non-FOREIGN 256-261 slot at
    ORIGINAL (the lab's foreign set = registers last changed by the inverter)."""
    claims = verified_claims(texts)
    off = {a: w.bank[a] for a in DUMP_REGS if a not in w.foreign and w.bank[a] != w.original[a]}
    return (not claims or not off), f"claims {[c[:70] for c in claims]} with ECCO-owned registers off ORIGINAL {off}"


def inv_list(w) -> list:
    return [(v["inv"], v["detail"][:120]) for v in w.invariants()]


def res(out: dict, name: str, ok: bool, detail="") -> None:
    if name in out:
        raise L.LabHarnessError(f"duplicate check name {name!r}")
    out[name] = (bool(ok), str(detail))


G09 = ["dump_snapshot_valid", "dump_operator_needed", "dump_verify_mismatch_count", "dump_export_unverified",
       "dump_comms_restore_attempts", "dump_restore_next_attempt_ms", "dump_restore_contained"]


def obs09(fw, cid: str, tail=None, phase_ms=None) -> dict:
    """Run a FW-09 document's timeline; observe at the document's end (the state its expectations see), then run the
    suite-only tail (fn(w) or None) and observe again."""
    w = play(fw, acts(cid), phase_ms, DRAFTS[cid]["world"])
    seq = last_seq(w, "act.dump_end")
    t_end = U0 + [a["at_s"] for a in DRAFTS[cid]["actions"] if a["do"] == "dump_end"][0]
    o = {"w": w, "t_end": t_end, "statuses": dump_statuses(w, seq), "final": w.status("dump"),
         "att": [t - t_end for t, _s in attempts(w, seq)], "groups": attempt_writes(w, seq),
         "marker": w.nvs_marker("dump"), "bank": {a: w.bank[a] for a in DUMP_REGS}, "g": w.globals_view(G09),
         "inv": inv_list(w)}
    o["truth"] = truthful(w, o["statuses"])
    if tail is not None:
        tail(w)
        o["tail"] = {"statuses": dump_statuses(w, seq), "att": [t - t_end for t, _s in attempts(w, seq)],
                     "groups": attempt_writes(w, seq), "marker": w.nvs_marker("dump"),
                     "bank": {a: w.bank[a] for a in DUMP_REGS}, "inv": inv_list(w), "final": w.status("dump"),
                     "opn": w.globals_view(["dump_operator_needed"])["dump_operator_needed"]}
    return o


def tail_force(w) -> None:
    """Suite-only continuation of FW-09 a: the inverter accepts 244 writes again (policy cleared), the operator arms and
    presses Force Restore Original (the documented operator path, FW:20498-20499), then 30 s."""
    w.modbus_policy(None)
    w.dump_force_restore()
    w.run_for(30)


def tail_retry(w) -> None:
    """Suite-only continuation of FW-09 c / c2: the automatic retry after the comms backoff (no operator action)."""
    w.run_for(BACKOFF_S[0] + WD_S + 10)


# =============================================================================================================================
# [1] FW-09 Dump restore verification
# =============================================================================================================================
def checks_09a(o: dict) -> dict:
    out: dict = {}
    st, g, b, n = o["statuses"], o["g"], o["bank"], "FW-09 a"
    res(out, f"{n}.1: the 244 write acknowledged but not applied fails both attempts on the 244 readback (FW:19982-19985): "
             f"no 'RESTORED OK' or other verified-restore claim after the END, dump_verify_mismatch_count 2",
        not verified_claims(st) and g["dump_verify_mismatch_count"] == 2, f"{st} {g}")
    res(out, f"{n}.2: the obligation is kept - the Dump marker stays RESTORE_REQUIRED and the RAM snapshot valid (the failure "
             f"branch FW:20434-20520 commits no marker)", o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"],
        f"{o['marker']} {g}")
    exp_st = [RESTORING, MISMATCH_1 + CONTAINED, RESTORING, MISMATCH_2 + CONTAINED, OP_WAIT + CONTAINED]
    res(out, f"{n}.3: one automatic retry at the next watchdog tick, then the documented operator path - the durable "
             f"operator lockout after the second mismatch (FW:20482-20501) and no further attempt (gate FW:19761): 2 "
             f"attempts <= {WD_S:.0f} s apart, the status sequence names each step",
        len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S and g["dump_operator_needed"]
        and no_deferred(st) == exp_st, f"att {o['att']} statuses {st}")
    floor = [min(v, FLOOR_W) for v in ORIG_TOU]
    exp_w = [[(244, [ORIG[244]], "ack_not_applied"), (256, floor, "ok")]] * 2
    res(out, f"{n}.4: 244 not proven, so each attempt contains 256-261 at min(original, {FLOOR_W} W) and verifies them "
             f"(FW:20019-20043, FW:20372); the report is truthful: bank 244 = 0 (Allow Export, named NOT proven, "
             f"dump_export_unverified set) and 256-261 = {FLOOR_W} W (named held at the floor)",
        o["groups"] == exp_w and b == {244: 0, **dict(zip(TOU, floor))} and g["dump_export_unverified"]
        and g["dump_restore_contained"] and o["truth"][0], f"{o['groups']} {b} {g} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (INV-NO-SILENT-OVERRIDE: the override stays visible as the snapshot "
             f"mirror and the operator lockout)", not o["inv"], str(o["inv"]))
    t = o.get("tail") or {}
    res(out, f"{n}.6: the operator path completes once the inverter applies 244 again: Force Restore Original rewrites "
             f"244 and the whole 256-261 ORIGINAL (FW:19909-19914), verifies, clears the marker and the lockout "
             f"(FW:20378-20419); bank ORIGINAL, invariants hold",
        bool(t) and t["final"] == RESTORED and t["marker"] == "CLEAR" and not t["opn"]
        and t["bank"] == {a: ORIG[a] for a in DUMP_REGS} and not t["inv"]
        and t["groups"][-1:] == [[(244, [ORIG[244]], "ok"), (256, ORIG_TOU, "ok")]], str(t)[:400])
    return out


def checks_09b(o: dict) -> dict:
    out: dict = {}
    st, g, b, n = o["statuses"], o["g"], o["bank"], "FW-09 b"
    res(out, f"{n}.1: the 6-slot block write acknowledged but not applied fails both attempts on the 256-261 readback "
             f"(FW:20335-20339): no 'RESTORED OK' or other verified-restore claim, dump_verify_mismatch_count 2",
        not verified_claims(st) and g["dump_verify_mismatch_count"] == 2, f"{st} {g}")
    res(out, f"{n}.2: the obligation is kept - the Dump marker stays RESTORE_REQUIRED and the RAM snapshot valid",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"], f"{o['marker']} {g}")
    exp_st = [RESTORING, MISMATCH_1, RESTORING, MISMATCH_2, OP_WAIT]
    res(out, f"{n}.3: one automatic retry, then the durable operator lockout (FW:20482-20501): 2 attempts <= {WD_S:.0f} s "
             f"apart, no 244 suffix in any status (244 proven: dump_export_unverified clear, FW:19987)",
        len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S and g["dump_operator_needed"]
        and no_deferred(st) == exp_st and not g["dump_export_unverified"], f"att {o['att']} statuses {st} {g}")
    exp_w = [[(244, [ORIG[244]], "ok"), (256, ORIG_TOU, "ack_not_applied")], [(256, ORIG_TOU, "ack_not_applied")]]
    res(out, f"{n}.4: 244 proven first (one write, verified), then the full 6-slot write (nothing FOREIGN: wmask 0x3F, "
             f"FW:20035) in each attempt; the second attempt's pre-read finds 244 ORIGINAL (action 0, no 244 write); the "
             f"report is truthful: bank 244 = 2, 256-261 = 1000 W (the lease power, named a repeated verify mismatch)",
        o["groups"] == exp_w and b == {244: ORIG[244], **{a: 1000 for a in TOU}} and o["truth"][0],
        f"{o['groups']} {b} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (INV-NO-SILENT-OVERRIDE: the override stays visible)", not o["inv"],
        str(o["inv"]))
    return out


def checks_09b2(o: dict) -> dict:
    out: dict = {}
    st, g, b, n = o["statuses"], o["g"], o["bank"], "FW-09 b2"
    first = [(244, [ORIG[244]], "ok")] + [(a, [ORIG[a]], "ok") for a in (256, 257, 258, 259)] + [(260, [ORIG[260]], "error")]
    single = [(260, [ORIG[260]], "ack_not_applied")]
    res(out, f"{n}.1: the FOREIGN 261 (the inverter's own 4000 W) makes the plan per slot and is never written "
             f"(FW:20027-20035); the first attempt writes 244, then 256-260 one by one until the 260 write errors "
             f"(comms path FW:20508-20519: dump_comms_restore_attempts 1, backoff)",
        bool(o["groups"]) and o["groups"][0] == first and all(x[0] != 261 for gr in o["groups"] for x in gr)
        and g["dump_comms_restore_attempts"] == 1, str(o["groups"]))
    res(out, f"{n}.2: every retry is a SINGLE-SLOT write: 256-259 now read ORIGINAL and 261 is FOREIGN, so the plan is 260 "
             f"alone (wmask 0x10, FW:19856-19881, FW:20027-20035) - two single-slot attempts, each acknowledged but not "
             f"applied", o["groups"][1:] == [single, single], str(o["groups"][1:]))
    res(out, f"{n}.3: the single-slot readback mismatch fails both single-slot attempts (FW:20335-20339): no 'RESTORED OK' "
             f"and no FOREIGN-lockout claim that ECCO's own settings were 'restored and verified' (FW:20460-20481 is "
             f"reached only when everything attempted verified); mismatch count 2 -> the operator lockout (FW:20482-20501)",
        not verified_claims(st) and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"]
        and no_deferred(st) == [RESTORING, COMMS_FAIL, RESTORING, MISMATCH_1, RESTORING, MISMATCH_2, OP_WAIT],
        f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; bank 260 = "
             f"1000 W (unapplied), 261 = 4000 W (FOREIGN, untouched), 244 and 256-259 ORIGINAL; the final status names "
             f"the repeated mismatch",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and o["truth"][0]
        and b == {**{a: ORIG[a] for a in DUMP_REGS}, 260: 1000, 261: 4000} and o["final"] == OP_WAIT,
        f"{o['marker']} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (the FOREIGN 261 is excluded; 260 stays visible as the snapshot mirror)",
        not o["inv"], str(o["inv"]))
    return out


B3_SLOTS = (256, 257, 258, 259, 260, 261)
B3_KEYS = tuple(f"b3-{k}" for k in B3_SLOTS)
# the per-slot write condition of each 256-261 slot (FW:20087-20314: slot k's own write block, wmask bit k - 256)
B3_SLOT_COND = ("return id(dump_restore_wmask) != 0x3F && ((id(dump_restore_wmask) >> {i}) & 1) != 0 && "
                "!id(dump_restore_block_failed);")


def b3_slot_line(k: int) -> int:
    """The 1-based firmware line of slot k's per-slot write condition, derived from the firmware text at import (the
    FW-09 b3-<k>.1 check name cites it, so it is never a literal). Fail loud unless the condition occurs exactly once."""
    cond, text = B3_SLOT_COND.format(i=k - 256), FW["_text"]
    n = text.count(cond)
    if n != 1:
        raise L.LabHarnessError(f"FW-09 b3-{k}: slot {k}'s per-slot write condition occurs {n} times in {FWP} (want "
                                f"exactly 1): {cond!r}")
    return text[:text.find(cond)].count("\n") + 1


B3_SLOT_LINE = {k: b3_slot_line(k) for k in B3_SLOTS}


def b3_foreign(k: int) -> int:
    """The FOREIGN slot of scenario b3-<k>: 261 for k = 256..260, 256 for k = 261 (the inverter's own 4000 W)."""
    return 261 if k != 261 else 256


def checks_09b3(o: dict, k: int) -> dict:
    """W6-1: slot k's per-slot readback verify. Expected values derived from the firmware (restore_dump_to_grid_snapshot):
    the pre-read classifies the lease slots (1000 W = dump_target_power) ECCO-owned and j FOREIGN (FW:19856-19881). The
    1000 W is the START feed-forward ceiling (FW:18434-18452: house load + export target - PV, rounded and clamped to
    [500 W, min(2000 W, the lease ceiling)]; also the pending ceiling, FW:18496), and it is still 1000 W at the End: the
    controller's grid error is 0 (telemetry grid -1000 W against the -1000 W export target, FW:19073-19075), inside the
    deadband, so it holds without a write (FW:19192); j's 4000 W therefore matches neither ORIGINAL, nor ECCO's ceiling /
    pending 1000 W, nor the 500 W floor. 244 reads ECCO's Allow Export (action 1, FW:19837-19838), is written and proven
    (FW:19925-19988); with a FOREIGN slot the plan is the owned non-FOREIGN slots, never 0x3F (FW:20027-20035), written
    one by one in address order (FW:20087-20314), none failing on comms (an acknowledged write is a response), so the
    256x6 readback runs (FW:20316-20325) and k's mismatch fails the attempt (FW:20335-20341); write_failed keeps the
    FOREIGN lockout away (FW:20373-20377, FW:20460-20481); mismatch 1 -> one automatic retry (FW:20482-20483,
    FW:20502-20506) at the next Dump watchdog tick (FW:24221-24248 via request_dump_end, FW:20571-20624); that pre-read
    finds 244 ORIGINAL (action 0, FW:19835-19836) and every other non-FOREIGN slot ORIGINAL (neither owned nor FOREIGN,
    FW:19860-19867), so the plan is k alone; mismatch 2 -> the durable operator lockout (FW:20484-20501); later ticks
    meet the gate's operator term (FW:19761) and publish the operator wait (FW:20535-20550). 244 proven: no 244 suffix
    (FW:20447-20459)."""
    out: dict = {}
    st, g, b = o["statuses"], o["g"], o["bank"]
    n, j, i = f"FW-09 b3-{k}", b3_foreign(k), k - 256
    first = [(244, [ORIG[244]], "ok")] + [(a, [ORIG[a]], "ack_not_applied" if a == k else "ok") for a in TOU if a != j]
    single = [(k, [ORIG[k]], "ack_not_applied")]
    res(out, f"{n}.1: the FOREIGN {j} (the inverter's own 4000 W: neither ORIGINAL nor an ECCO value, FW:19856-19881) makes "
             f"the plan per slot and is never written (FW:20027-20035); the first attempt writes 244 (ECCO's Allow Export, "
             f"FW:19837-19838; proven, FW:19982-19988), then every other slot one by one in address order "
             f"(FW:20087-20314; slot {k} at FW:{B3_SLOT_LINE[k]}) with {k} acknowledged but not applied; no comms failure",
        bool(o["groups"]) and o["groups"][0] == first and all(x[0] != j for gr in o["groups"] for x in gr)
        and g["dump_comms_restore_attempts"] == 0, f"{o['groups']} {g}")
    res(out, f"{n}.2: the automatic retry at the next watchdog tick (<= {WD_S:.0f} s later) is a SINGLE-SLOT write of {k}: "
             f"244 and the other slots now read ORIGINAL and {j} is FOREIGN, so the plan is {k} alone (wmask "
             f"0x{1 << i:02X}, FW:19835-19836, FW:19860-19867, FW:20027-20035), acknowledged but not applied; exactly "
             f"two attempts", o["groups"][1:] == [single] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S,
        f"att {o['att']} {o['groups'][1:]}")
    res(out, f"{n}.3: the readback of {k} mismatches in both attempts (FW:20335-20341): no 'RESTORED OK' and no FOREIGN-"
             f"lockout claim that ECCO's own settings were 'restored and verified' (FW:20373-20377, FW:20460-20481: only "
             f"when everything attempted verified); dump_verify_mismatch_count 2 -> the durable operator lockout "
             f"(FW:20482-20501), then the operator wait (FW:20535-20550)",
        not verified_claims(st) and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"]
        and no_deferred(st) == [RESTORING, MISMATCH_1, RESTORING, MISMATCH_2, OP_WAIT], f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; bank {k} = "
             f"1000 W (the lease value, unapplied), {j} = 4000 W (FOREIGN, untouched), 244 and the other slots ORIGINAL; "
             f"244 proven (dump_export_unverified clear, no 244 suffix); the final status is the operator wait",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and o["truth"][0]
        and b == {**{a: ORIG[a] for a in DUMP_REGS}, k: 1000, j: 4000} and not g["dump_export_unverified"]
        and o["final"] == OP_WAIT, f"{o['marker']} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: {k} stays visible as the snapshot "
             f"mirror; the FOREIGN {j} is excluded)", not o["inv"], str(o["inv"]))
    return out


# W6-1b: the containment path (b4), a readback above the expected value (b5) and slot cross-wiring on pairwise-distinct
# originals (b6) - the scenario shapes the six per-slot verify regressions that survived the W6-1 review need
LEASE_W = 1000      # the 256-261 lease value at the End: the START ceiling of every scenario here (checks_09b3's derivation)
FOREIGN_W = 4000    # the inverter's own value of the FOREIGN slot: neither ORIGINAL nor an ECCO value (FW:19856-19881)
# key -> (shape, the slot whose single-register writes are acknowledged but not applied (None: the 6-slot block), FOREIGN)
B4_CASES = {"b4-ct": ("CT", 258, 261), "b4-cb": ("CB", None, None), "b4-co": ("CO", 256, 261)}
# key -> (the slot whose single-register writes are acknowledged but not applied, the FOREIGN slot)
PS_CASES = {"b5-lo": (259, 261), "b6-x257": (257, 261), "b6-x260": (260, 261)}
B456_KEYS = tuple(B4_CASES) + ("b5-lo", "b6-ok", "b6-x257", "b6-x260")


def doc_original(cid: str) -> dict:
    """The ORIGINAL the scenario's owner expects (the scenario's input, not an observation): the synthetic SITE ORIGINAL
    with the document's world bank overrides (FirmwareWorld builds the same image, site_bank(bank))."""
    return {**ORIG, **{L._reg(a): v for a, v in DRAFTS[cid]["world"].get("bank", {}).items()}}


def checks_09b4(o: dict, key: str) -> dict:
    """W6-1b, the containment path. Expected values derived from the firmware (restore_dump_to_grid_snapshot): every 244
    write is acknowledged but not applied, so the pre-read finds 244 at ECCO's Allow Export 0 (action 1, FW:19837-19838;
    dump_export_unverified set, FW:19845); the 244 write is answered (FW:19930-19937: no comms failure) and its readback 0
    differs from the ORIGINAL 2 (FW:19982-19985: write_failed, a mismatch), so 244 is not proven (FW:20019) and the attempt
    CONTAINS (FW:20020): every non-FOREIGN slot, owned or not, is written at min(original, 500 W) (FW:20028-20031; 500 W
    for every synthetic ORIGINAL). With a FOREIGN slot (ct, co: 261 at 4000 W, FW:19856-19881, never written) wmask is not
    0x3F and the slots are written one by one in address order (FW:20087-20314); with none (cb) the containment term of
    FW:20031 makes wmask 0x3F and the 6-slot block is written (FW:20045-20086). Every write is answered, so the readback
    runs (FW:20318) and the unapplied slot - ct: 258 at the 1000 W lease value; co: 256, which the inverter put back to its
    ORIGINAL 8000 W at the End, so the pre-read neither owns it nor finds it FOREIGN (FW:19860-19867) and only the
    containment writes it; cb: all six at 1000 W - differs from its 500 W (FW:20335-20341): block_failed, so
    dump_restore_contained stays clear (FW:20372), and write_failed keeps the FOREIGN lockout away (FW:20373). The status
    suffix (FW:20447-20459): with a FOREIGN slot named (dump_restore_uncontained '261=4000W', FW:19868-19879) '; 244 NOT
    proven off; export may continue; NOT CONTAINED: 261=4000W' (FW:20449-20454), with none '; register 244 is NOT proven
    out of Allow Export - export may continue' (FW:20457-20458). Mismatch 1 -> one automatic retry at the next Dump
    watchdog tick (FW:20502-20506, FW:24221-24248 via request_dump_end, FW:20571-20624; the supervision lambda
    FW:24174-24220 returns at FW:24200 here - fresh SOC 70 % above the 25 % Stop SOC, no export trip - and when it fires
    it only zeroes the backoff (FW:24214) or publishes dump_recovery_state (FW:24218), never dump_status); its pre-read
    finds 244 at 0 again (action 1) and
    the written slots at the 500 W floor, ECCO's own value (FW:19858-19861), the unapplied slot as before, so it repeats the
    same containment attempt and fails the same way; mismatch 2 -> the durable operator lockout (FW:20484-20501), then the
    operator wait with the same suffix (FW:20535-20550, FW:20537-20547)."""
    out: dict = {}
    shape, k, j = B4_CASES[key]
    st, g, b, n = o["statuses"], o["g"], o["bank"], f"FW-09 {key}"
    floor = {a: min(ORIG[a], FLOOR_W) for a in TOU}
    w244 = (244, [ORIG[244]], "ack_not_applied")
    if shape == "CB":
        att = [w244, (256, [floor[a] for a in TOU], "ack_not_applied")]
        suffix, sl = EXPORT_MAY, "FW:20457-20458, FW:20545-20546"
        exp_b = {244: 0, **{a: LEASE_W for a in TOU}}
        plan = (f"nothing is FOREIGN, so the containment term makes wmask 0x3F (FW:20031) and the 6-slot floor block "
                f"(FW:20045-20086) is written, acknowledged but not applied")
        held = f"256-261 = {LEASE_W} W (the lease value: the floor block unapplied)"
    else:
        att = [w244] + [(a, [floor[a]], "ack_not_applied" if a == k else "ok") for a in TOU if a != j]
        suffix, sl = UNPROVEN_244 + MAY_CONTINUE + NOT_CONTAINED + f"{j}={FOREIGN_W}W", "FW:20449-20454, FW:20538-20542"
        kv = LEASE_W if shape == "CT" else ORIG[k]
        exp_b = {244: 0, **floor, k: kv, j: FOREIGN_W}
        wm = 0x3F & ~(1 << (j - 256))
        who = (f"{k} (at the {LEASE_W} W lease value, ECCO's own)" if shape == "CT" else
               f"{k} (put back to its ORIGINAL {ORIG[k]} W by the inverter at the End: neither owned nor FOREIGN, "
               f"FW:19860-19867, yet written by the containment)")
        plan = (f"the FOREIGN {j} (the inverter's own {FOREIGN_W} W, FW:19856-19881) is never written and makes the plan "
                f"per slot (wmask 0x{wm:02X}, FW:20087-20314); the floor write of {who} is acknowledged but not applied")
        held = (f"{k} = {kv} W (" + ("the lease value" if shape == "CT" else "its ORIGINAL") + f": its floor write "
                f"unapplied), {j} = {FOREIGN_W} W (FOREIGN, untouched), every other slot {FLOOR_W} W (contained)")
    res(out, f"{n}.1: every 244 write is acknowledged but not applied, so 244's readback (0, ECCO's Allow Export) fails "
             f"(FW:19982-19985) and 244 is not proven: the attempt contains every non-FOREIGN slot at min(original, "
             f"{FLOOR_W} W) (FW:20019-20031); {plan}; no comms failure",
        bool(o["groups"]) and o["groups"][0] == att and (j is None or all(x[0] != j for gr in o["groups"] for x in gr))
        and g["dump_comms_restore_attempts"] == 0, f"{o['groups']} {g}")
    res(out, f"{n}.2: the automatic retry at the next watchdog tick (<= {WD_S:.0f} s later) repeats the same containment "
             f"attempt with the same writes - its pre-read finds 244 at 0 again (action 1, FW:19837-19838) and the floor "
             f"values ECCO's own (FW:19858-19861); exactly two attempts",
        o["groups"] == [att, att] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S,
        f"att {o['att']} {o['groups']}")
    exp_st = [RESTORING, MISMATCH_1 + suffix, RESTORING, MISMATCH_2 + suffix, OP_WAIT + suffix]
    res(out, f"{n}.3: the unapplied floor write fails the readback (FW:20335-20341: block_failed), so the containment is "
             f"NOT claimed (FW:20372): both failure statuses and the operator wait end '{suffix}' ({sl}) and none says "
             f"'ECCO's own at 500 W' or 'held at the 500 W floor'; no verified-restore claim; mismatch count 2 -> the "
             f"durable operator lockout (FW:20482-20501), then the operator wait (FW:20535-20550)",
        not verified_claims(st) and not [x for x in st if any(c in x for c in CONTAIN_CLAIMS)]
        and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"] and no_deferred(st) == exp_st,
        f"{st} {g}")
    bf = o["w"].globals_view(["dump_restore_block_failed"])["dump_restore_block_failed"]
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid, "
             f"dump_restore_block_failed set by the last attempt's readback mismatch (FW:20337; reset only when an attempt "
             f"starts, FW:19820), so dump_restore_contained clear (FW:20372), and dump_export_unverified set (FW:19845); "
             f"bank 244 = 0 (Allow Export, not proven), {held}; the final status is the operator wait naming 'export may "
             f"continue'",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and bf is True and not g["dump_restore_contained"]
        and g["dump_export_unverified"] and b == exp_b and o["final"] == OP_WAIT + suffix and o["truth"][0],
        f"{o['marker']} block_failed {bf} {g} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: the override stays visible as the "
             f"snapshot mirror and the operator lockout)", not o["inv"], str(o["inv"]))
    return out


def checks_09ps(o: dict, key: str) -> dict:
    """W6-1b, b3's per-slot shape on a synthetic bank: b5-lo (259's ORIGINAL 600 W, below the 1000 W lease value) and
    b6-x257 / b6-x260 (pairwise-distinct originals with 256's / 259's ORIGINAL equal to the 1000 W lease value). Expected
    values derived from the firmware as in checks_09b3, plus: the START snapshot takes the bank as the ORIGINAL
    (FW:18244-18250; no range check on 256-261, unlike 244's FW:18196) and writes its 1000 W ceiling into all six slots
    (FW:18578-18584); at the End the pre-read finds every slot whose ORIGINAL differs from 1000 W at 1000 W (ECCO-owned) and
    a slot whose ORIGINAL IS 1000 W at its ORIGINAL - neither owned nor FOREIGN (FW:19860-19867), so it is never written
    (FW:20031) -, and j FOREIGN; the plan is per slot (FW:20027-20035); the readback compares each written slot with its
    OWN expected value, v[] = dump_restore_v0..v5 in slot order (FW:20036-20041, FW:20331-20336): k reads 1000 W against
    its own ORIGINAL (b5-lo: 600 W, so the readback is ABOVE the expected value; b6-x257 / b6-x260: 8000 W / 4500 W, while
    its lower neighbour's expected value is 1000 W) -> a mismatch (FW:20337-20340); one automatic retry of k alone, then
    mismatch 2, the operator lockout and the operator wait (FW:20482-20501, FW:20535-20550)."""
    out: dict = {}
    k, j = PS_CASES[key]
    orig = doc_original(f"FW-09-{key}")
    st, g, b, n, i = o["statuses"], o["g"], o["bank"], f"FW-09 {key}", k - 256
    same = [a for a in TOU if a != j and orig[a] == LEASE_W]      # at their ORIGINAL at the End: never written
    if key.startswith("b6-") and (len(set(orig[a] for a in TOU)) != 6 or len(same) != 1):
        raise L.LabHarnessError(f"FW-09 {key}: the bank must be pairwise distinct with one ORIGINAL at {LEASE_W} W")
    first = [(244, [orig[244]], "ok")] + [(a, [orig[a]], "ack_not_applied" if a == k else "ok") for a in TOU
                                          if a != j and a not in same]
    single = [(k, [orig[k]], "ack_not_applied")]
    site = (f"on pairwise-distinct ORIGINAL 256-261 = {'/'.join(str(orig[a]) for a in TOU)} W, {same[0]}'s equal to the "
            f"{LEASE_W} W lease value ({same[0]} reads its ORIGINAL: neither owned nor FOREIGN, FW:19860-19867, so it is "
            f"never written)" if same else
            f"on a site whose {k} ORIGINAL is {orig[k]} W, below the {LEASE_W} W lease value")
    res(out, f"{n}.1: {site}; the FOREIGN {j} (the inverter's own {FOREIGN_W} W, FW:19856-19881) makes the plan per slot and "
             f"is never written (FW:20027-20035); the first attempt writes 244 (ECCO's Allow Export, proven, "
             f"FW:19982-19988), then every ECCO-owned slot one by one in address order (FW:20087-20314; slot {k} at "
             f"FW:{B3_SLOT_LINE[k]}) with {k} acknowledged but not applied; no comms failure",
        bool(o["groups"]) and o["groups"][0] == first and all(x[0] != j for gr in o["groups"] for x in gr)
        and g["dump_comms_restore_attempts"] == 0, f"{o['groups']} {g}")
    res(out, f"{n}.2: the automatic retry at the next watchdog tick (<= {WD_S:.0f} s later) is a SINGLE-SLOT write of {k}: "
             f"244 and every other slot now read ORIGINAL and {j} is FOREIGN, so the plan is {k} alone (wmask "
             f"0x{1 << i:02X}, FW:19835-19836, FW:19860-19867, FW:20027-20035), acknowledged but not applied; exactly "
             f"two attempts", o["groups"][1:] == [single] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S,
        f"att {o['att']} {o['groups'][1:]}")
    res(out, f"{n}.3: {k}'s readback ({LEASE_W} W, " + ("ABOVE" if orig[k] < LEASE_W else "not") + f" its expected value) "
             f"is compared with its OWN expected {orig[k]} W (v[] = dump_restore_v0..v5 in slot order, FW:20036-20041, "
             f"FW:20331-20336) and mismatches in both attempts (FW:20335-20341): no 'RESTORED OK' and no FOREIGN-lockout "
             f"claim that ECCO's own settings were 'restored and verified' (FW:20373-20377, FW:20460-20481); "
             f"dump_verify_mismatch_count 2 -> the durable operator lockout (FW:20482-20501), then the operator wait "
             f"(FW:20535-20550)",
        not verified_claims(st) and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"]
        and no_deferred(st) == [RESTORING, MISMATCH_1, RESTORING, MISMATCH_2, OP_WAIT], f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; bank {k} = "
             f"{LEASE_W} W (the lease value, unapplied), {j} = {FOREIGN_W} W (FOREIGN, untouched), 244 and every other "
             f"slot at its ORIGINAL ({', '.join(f'{a} = {orig[a]}' for a in TOU if a not in (k, j))} W); 244 proven "
             f"(dump_export_unverified clear, no 244 suffix); the final status is the operator wait",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and o["truth"][0]
        and b == {**{a: orig[a] for a in DUMP_REGS}, k: LEASE_W, j: FOREIGN_W} and not g["dump_export_unverified"]
        and o["final"] == OP_WAIT, f"{o['marker']} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: {k} stays visible as the snapshot "
             f"mirror; the FOREIGN {j} is excluded)", not o["inv"], str(o["inv"]))
    return out


def checks_09b6ok(o: dict) -> dict:
    """W6-1b, a correct restore of pairwise-distinct originals (nothing FOREIGN, no fault). Expected values derived from the
    firmware: the START snapshot and ceiling as in checks_09ps; at the End the pre-read finds 244 at 0 (action 1) and every
    slot at 1000 W (ECCO-owned, nothing FOREIGN: FW:19835-19881); 244 is written and proven (FW:19925-19988); no
    containment and nothing FOREIGN, so wmask 0x3F (FW:20035) and v0..v5 = the ORIGINAL in slot order (FW:20029,
    FW:20036-20041); the 6-slot block write (FW:20045-20086) lands and its readback compares each slot with its own
    expected value (v[] = v0..v5, FW:20331-20336): no mismatch; nothing FOREIGN and 244 not FOREIGN, so no FOREIGN lockout
    (FW:20373-20377); the success branch commits PENDING_CLEAR then CLEAR and publishes RESTORED OK (FW:20378-20419) and
    clears the snapshot (FW:20398), so no later watchdog tick requests a restore (FW:24224)."""
    out: dict = {}
    orig = doc_original("FW-09-b6-ok")
    st, g, b, n = o["statuses"], o["g"], o["bank"], "FW-09 b6-ok"
    vals = [orig[a] for a in TOU]
    if len(set(vals)) != 6 or LEASE_W in vals:
        raise L.LabHarnessError(f"FW-09 b6-ok: the bank must be pairwise distinct and none at {LEASE_W} W: {vals}")
    res(out, f"{n}.1: exactly one attempt: 244 (ECCO's Allow Export) written and proven (FW:19925-19988), then the full "
             f"6-slot write of the pairwise-distinct ORIGINAL {'/'.join(map(str, vals))} W (every slot ECCO's own at "
             f"{LEASE_W} W, nothing FOREIGN: wmask 0x3F, FW:19856-19881, FW:20035), applied; no retry",
        o["groups"] == [[(244, [orig[244]], "ok"), (256, vals, "ok")]] and len(o["att"]) == 1,
        f"att {o['att']} {o['groups']}")
    res(out, f"{n}.2: the readback compares every slot with its OWN original (v[] = dump_restore_v0..v5 in slot order, "
             f"FW:20036-20041, FW:20331-20336) and finds no mismatch: the status sequence is exactly RESTORING, RESTORED "
             f"OK - no 'RESTORE VERIFY FAILED' (FW:20502-20506) - and the mismatch count stays 0",
        no_deferred(st) == [RESTORING, RESTORED] and not [x for x in st if x.startswith(MISMATCH_1)]
        and g["dump_verify_mismatch_count"] == 0, f"{st} {g}")
    res(out, f"{n}.3: the restore completes (FW:20378-20419): RESTORED OK, marker CLEAR, snapshot cleared, no operator "
             f"lockout, 244 proven (dump_export_unverified clear); bank 244 and 256-261 at their ORIGINAL",
        o["final"] == RESTORED and o["marker"] == "CLEAR" and not g["dump_snapshot_valid"]
        and not g["dump_operator_needed"] and not g["dump_export_unverified"] and o["truth"][0]
        and b == {a: orig[a] for a in DUMP_REGS}, f"{o['final']!r} {o['marker']} {g} {b} {o['truth'][1]}")
    res(out, f"{n}.4: every core invariant holds (INV-NO-SILENT-OVERRIDE: the verified restore leaves nothing owed)",
        not o["inv"], str(o["inv"]))
    return out


def checks_09c(o: dict, which: str) -> dict:
    """c: the 244 verify read errors (244 written and landed, unproven -> containment); c2: the 256-261 verify read gets no
    response (244 proven; 256-261 written and landed, unverified)."""
    out: dict = {}
    st, g, b = o["statuses"], o["g"], o["bank"]
    n = f"FW-09 {which}"
    c244 = which == "c"
    floor = [min(v, FLOOR_W) for v in ORIG_TOU]
    exp_st = [RESTORING, COMMS_FAIL + (CONTAINED if c244 else "")]
    res(out, f"{n}.1: the failed verify read fails the attempt (FW:" + ("19989-19993" if c244 else "20348-20352")
        + ") on the comms path (FW:20508-20519): no 'RESTORED OK' or other verified-restore claim, the status names "
          "the failure" + (" and the containment" if c244 else "") + ", the backoff is armed (comms attempts 1)",
        not verified_claims(st) and no_deferred(st) == exp_st and g["dump_comms_restore_attempts"] == 1
        and g["dump_restore_next_attempt_ms"] != 0 and g["dump_verify_mismatch_count"] == 0, f"{st} {g}")
    res(out, f"{n}.2: the obligation and its retries are kept - marker RESTORE_REQUIRED, snapshot valid, no operator "
             f"lockout (a comms failure never locks, FW:20434-20442)",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and not g["dump_operator_needed"],
        f"{o['marker']} {g}")
    if c244:
        exp_w = [[(244, [ORIG[244]], "ok"), (256, floor, "ok")]]
        exp_b = {244: ORIG[244], **dict(zip(TOU, floor))}
        txt = (f"244 landed but unproven (dump_export_unverified set, FW:19845), so 256-261 are contained at min(original, "
               f"{FLOOR_W} W) (FW:20019-20043); the report is truthful: bank 244 = 2, 256-261 = {FLOOR_W} W, the status says "
               f"NOT proven and held at the floor")
        exp_g = g["dump_export_unverified"] and g["dump_restore_contained"]
    else:
        exp_w = [[(244, [ORIG[244]], "ok"), (256, ORIG_TOU, "ok")]]
        exp_b = {a: ORIG[a] for a in DUMP_REGS}
        txt = ("244 written and proven first (dump_export_unverified clear, FW:19987), then the full 6-slot write landed "
               "but is unverified; the report is truthful: no success claimed although the bank happens to be ORIGINAL")
        exp_g = not g["dump_export_unverified"] and not g["dump_restore_contained"]
    res(out, f"{n}.3: {txt}", o["groups"] == exp_w and b == exp_b and exp_g and o["truth"][0],
        f"{o['groups']} {b} {g} {o['truth'][1]}")
    res(out, f"{n}.4: every core invariant holds (INV-NO-SILENT-OVERRIDE: the snapshot mirror stays visible)", not o["inv"],
        str(o["inv"]))
    t = o.get("tail") or {}
    bound = BACKOFF_S[0] + WD_S
    retry = ([(256, ORIG_TOU, "ok")] if c244 else [])
    res(out, f"{n}.5: the automatic retry after the comms backoff ({BACKOFF_S[0]} s, on the {WD_S:.0f} s watchdog grid: "
             f"<= {bound:.0f} s after the END) finds 244 ORIGINAL and " + ("the floor values ECCO's own" if c244 else
                                                                            "256-261 ORIGINAL")
        + ", " + ("rewrites 256-261 ORIGINAL" if c244 else "writes nothing (owned mask 0)")
        + ", verifies and completes: RESTORED OK, marker CLEAR, bank ORIGINAL, invariants hold",
        bool(t) and len(t["att"]) == 2 and BACKOFF_S[0] <= t["att"][1] <= bound and t["groups"][1] == retry
        and t["final"] == RESTORED and t["marker"] == "CLEAR" and t["bank"] == {a: ORIG[a] for a in DUMP_REGS}
        and not t["inv"], str(t)[:400])
    return out


# W6-1c: the containment CLAIM - the scenario shapes the four containment-claim regressions that survived the W6-1b review
# need (the 256-261 readback's failure handlers without block_failed, the per-attempt reset of dump_restore_contained
# dropped, the containment flag without 'm != 0'), and a truthfulness helper for every containment claim
# key -> (shape, the slot whose floor write is acknowledged but not applied (None: the 6-slot floor block), the FOREIGN
# slot (None: none), the outcome of every 256x6 readback)
B7_RB = {"b7-rbnr": ("CB", None, None, "no_response"), "b7-rber": ("CT", 258, 261, "error")}
B7_KEYS = tuple(B7_RB) + ("b7-cmnr", "b7-ab", "b7-af")
G7 = ["dump_restore_contain", "dump_restore_block_failed", "dump_restore_wmask"]
AB_SLOT = 258        # b7-ab: the slot the inverter puts back to its ORIGINAL after the first attempt
ALL_FOREIGN = "256 257 258 259 260 261"   # b7-af: the NOT CONTAINED list, register numbers only (FW:19868-19879)


def readbacks(w, seq: int) -> list:
    """The outcome of every 256-261 restore readback (the 256x6 read, FW:20316-20325) after seq."""
    return [e["data"]["outcome"] for e in after(w, seq, "fw.read")
            if e["data"]["addr"] == 256 and e["data"]["count"] == 6]


def claims_in(texts: list) -> list:
    """The statuses among texts that claim the containment ("ECCO's own at 500 W", FW:20453 / FW:20541; 'held at the
    500 W floor', FW:20456 / FW:20544)."""
    return [x for x in texts if any(c in x for c in CONTAIN_CLAIMS)]


def bank_changes(w) -> list:
    """Every change of the 244 / 256-261 bank in log order, [(seq, addr, value)]: a landed firmware write (fw.write with
    landed set: _dump_sim.py:1568-1570 writes its values from addr on) or the lab's set_register (env.register)."""
    out = []
    for e in w.log.events(kind="fw.write"):
        d = e["data"]
        if d["landed"]:
            out += [(e["seq"], d["addr"] + i, v) for i, v in enumerate(d["vals"]) if d["addr"] + i in DUMP_REGS]
    for e in w.log.events(kind="env.register"):
        if e["data"]["addr"] in DUMP_REGS:
            out.append((e["seq"], e["data"]["addr"], e["data"]["value"]))
    return sorted(out)


def bank_at(base: dict, changes: list, seq: int) -> dict:
    """The 244 / 256-261 bank as it stood just before log event seq: base plus every change logged earlier."""
    b = dict(base)
    for s, a, v in changes:
        if s >= seq:
            break
        b[a] = v
    return b


def contain_claims(w, cid: str) -> dict:
    """W6-1c, the containment-claim truthfulness helper (source-derived; it reads the bank, never the firmware's flags). A
    Dump status claims the containment with "ECCO's own at 500 W" (FW:20453, FW:20541) or 'held at the 500 W floor'
    (FW:20456, FW:20544) only while dump_restore_contained is set (FW:20449-20456, FW:20538-20544): the attempt's
    containment plan - every non-FOREIGN 256-261 slot written at floor_v = min(original, 500 W) (FW:20028-20031), flagged
    only when it writes at least one slot (m != 0, FW:20043) - was written and its readback verified (FW:20372). So each
    claim must be backed by the bank AS IT STOOD WHEN THAT STATUS WAS PUBLISHED (a later change by another actor does not
    falsify an earlier claim): at least one slot is non-FOREIGN at the attempt's ownership pre-read (the last 244x18 read
    before the status, FW:19823-19827; FW:19856-19867: a slot reading its ORIGINAL, ECCO's ceiling / pending ceiling - the
    1000 W START ceiling of every FW-09 timeline, LEASE_W - or its floor value is not FOREIGN) and every such slot reads
    its floor value. ORIGINAL = the scenario's (doc_original). The bank at a log event is rebuilt from the scenario's
    initial bank (site_bank with the document's world bank) plus every landed firmware write and every set_register in
    log order; fail loud unless the rebuilt end state equals the world's bank. Returns {ok, n (claims checked), bad,
    backed (one bool per claim, in publish order)}."""
    orig = doc_original(cid)
    floor = {a: min(orig[a], FLOOR_W) for a in TOU}
    base = {a: v for a, v in L.site_bank(world_kwargs(DRAFTS[cid]["world"]).get("bank")).items() if a in DUMP_REGS}
    changes = bank_changes(w)
    end, live_end = bank_at(base, changes, 10 ** 12), {a: w.bank[a] for a in DUMP_REGS}
    if end != live_end:
        raise L.LabHarnessError(f"{cid}: the bank rebuilt from the log {end} differs from the world's {live_end}")
    seq0 = last_seq(w, "act.dump_end")
    pre = [e["seq"] for e in after(w, seq0, "fw.read")
           if e["data"]["addr"] == 244 and e["data"]["count"] == 18 and e["data"]["outcome"] == "ok"]
    bad, backed = [], []
    for e in after(w, seq0, "fw.status"):
        text = e["data"]["text"]
        if e["data"]["dom"] != "dump" or not claims_in([text]):
            continue
        p = [s for s in pre if s < e["seq"]]
        if not p:
            backed.append(False)
            bad.append((text[:60], "no ownership pre-read before the claim"))
            continue
        live = bank_at(base, changes, p[-1])
        own = [a for a in TOU if live[a] == orig[a] or live[a] in (LEASE_W, floor[a])]
        now = bank_at(base, changes, e["seq"])
        off = {a: now[a] for a in own if now[a] != floor[a]}
        backed.append(bool(own) and not off)
        if not backed[-1]:
            bad.append((text[:60], f"non-FOREIGN slots {own}, off the floor {off}"))
    return {"ok": not bad, "n": len(backed), "bad": bad, "backed": backed}


def obs09b7(fw, key: str, phase_ms=None) -> dict:
    """obs09 for a W6-1c timeline plus, at the document's end, the containment globals G7 and the 256x6 readback outcomes;
    b7-cmnr then runs the suite-only retry tail (tail_retry) and is observed again, as obs09 observes c / c2; finally the
    containment-claim helper over the whole timeline."""
    cid = f"FW-09-{key}"
    o = obs09(fw, cid, None, phase_ms)
    w = o["w"]
    seq = last_seq(w, "act.dump_end")
    o["g7"], o["rb"] = w.globals_view(G7), readbacks(w, seq)
    if key == "b7-cmnr":
        tail_retry(w)
        o["tail"] = {"statuses": dump_statuses(w, seq), "att": [t - o["t_end"] for t, _s in attempts(w, seq)],
                     "groups": attempt_writes(w, seq), "marker": w.nvs_marker("dump"),
                     "bank": {a: w.bank[a] for a in DUMP_REGS}, "inv": inv_list(w), "final": w.status("dump"),
                     "rb": readbacks(w, seq), "g": w.globals_view(G09)}
    o["claims"] = contain_claims(w, cid)
    return o


def checks_09b7rb(o: dict, key: str) -> dict:
    """W6-1c, a failed 256-261 readback in containment. Expected values derived from the firmware
    (restore_dump_to_grid_snapshot) as in checks_09b4 up to the readback: every 244 write is acknowledged but not
    applied, so the pre-read finds 244 at ECCO's Allow Export 0 (action 1, FW:19837-19838; dump_export_unverified set,
    FW:19845), 244's readback 0 differs from the ORIGINAL 2 (FW:19982-19985: write_failed AND
    dump_restore_mismatch_this_attempt), 244 is not proven (FW:20019) and the attempt contains every non-FOREIGN slot at
    min(original, 500 W) (FW:20020-20031; dump_restore_contain set, m != 0, FW:20043): rbnr, nothing FOREIGN - the
    containment term makes wmask 0x3F and the 6-slot floor block (FW:20045-20086) is acknowledged but not applied; rber -
    the FOREIGN 261 (4000 W, FW:19856-19881) is never written and the slots are written one by one (wmask 0x1F,
    FW:20087-20314), slot 258's floor write acknowledged but not applied. An acknowledged write fires on_response, so
    block_failed stays clear and the readback runs (FW:20316-20325: wmask != 0, block_failed clear); it gets no response
    (rbnr) / an error (rber), whose handler sets block_failed and write_failed (FW:20348-20352 / FW:20343-20347), so
    dump_restore_contained - reset when the attempt started (FW:19819) - stays clear (FW:20372), and write_failed keeps
    the FOREIGN lockout away (FW:20373). The 244 mismatch routes the failed attempt to the MISMATCH path (FW:20482), not
    the comms path (FW:20508-20519: dump_comms_restore_attempts stays 0; the comms path in containment is b7-cmnr). The
    suffix (FW:20447-20459): rbnr, nothing FOREIGN (dump_restore_uncontained empty, FW:19879) - '; register 244 is NOT
    proven out of Allow Export - export may continue' (FW:20457-20458); rber - '; 244 NOT proven off; export may
    continue; NOT CONTAINED: 261=4000W' (FW:20449-20454). Mismatch 1 -> one automatic retry at the next Dump watchdog tick
    (FW:20502-20506, FW:24221-24248 via request_dump_end, FW:20571-20624; the supervision lambda returns at FW:24200 as in
    checks_09b4); its pre-read finds 244 at 0 (action 1) and every written slot at an ECCO value (the 500 W floor, or the
    1000 W lease value where the floor write did not land; FW:19858-19861), so it repeats the same attempt, the same
    readback failure and the same suffix; mismatch 2 -> the durable operator lockout (FW:20484-20501), then the operator
    wait with the same suffix (FW:20535-20550)."""
    out: dict = {}
    shape, k, j, rb = B7_RB[key]
    st, g, g7, b, n = o["statuses"], o["g"], o["g7"], o["bank"], f"FW-09 {key}"
    floor = {a: min(ORIG[a], FLOOR_W) for a in TOU}
    w244 = (244, [ORIG[244]], "ack_not_applied")
    if shape == "CB":
        att = [w244, (256, [floor[a] for a in TOU], "ack_not_applied")]
        suffix, sl = EXPORT_MAY, "FW:20457-20458, FW:20545-20546"
        exp_b = {244: 0, **{a: LEASE_W for a in TOU}}
        plan = ("nothing is FOREIGN, so the containment term makes wmask 0x3F (FW:20031) and the 6-slot floor block "
                "(FW:20045-20086) is written, acknowledged but not applied")
        held = f"256-261 = {LEASE_W} W (the lease value: the floor block unapplied)"
        hl = "FW:20348-20352"
    else:
        att = [w244] + [(a, [floor[a]], "ack_not_applied" if a == k else "ok") for a in TOU if a != j]
        suffix, sl = UNPROVEN_244 + MAY_CONTINUE + NOT_CONTAINED + f"{j}={FOREIGN_W}W", "FW:20449-20454, FW:20538-20542"
        exp_b = {244: 0, **floor, k: LEASE_W, j: FOREIGN_W}
        plan = (f"the FOREIGN {j} (the inverter's own {FOREIGN_W} W, FW:19856-19881) is never written and makes the plan "
                f"per slot (wmask 0x{0x3F & ~(1 << (j - 256)):02X}, FW:20087-20314); the floor write of {k} is "
                f"acknowledged but not applied")
        held = (f"{k} = {LEASE_W} W (the lease value: its floor write unapplied), {j} = {FOREIGN_W} W (FOREIGN, "
                f"untouched), every other slot {FLOOR_W} W")
        hl = "FW:20343-20347"
    what = "gets no response" if rb == "no_response" else "returns an error"
    res(out, f"{n}.1: every 244 write is acknowledged but not applied, so 244's readback fails (FW:19982-19985: "
             f"write_failed and a mismatch) and 244 is not proven: the attempt contains every non-FOREIGN slot at "
             f"min(original, {FLOOR_W} W) (FW:20019-20043); {plan}; no comms failure (the 244 mismatch takes the "
             f"mismatch path, FW:20482: dump_comms_restore_attempts 0)",
        bool(o["groups"]) and o["groups"][0] == att and (j is None or all(x[0] != j for gr in o["groups"] for x in gr))
        and g["dump_comms_restore_attempts"] == 0, f"{o['groups']} {g}")
    res(out, f"{n}.2: every write answered, so each attempt's 256-261 readback runs (FW:20316-20325) and {what}; the "
             f"automatic retry at the next watchdog tick (<= {WD_S:.0f} s later) repeats the same containment attempt "
             f"with the same writes; exactly two attempts and two readbacks",
        o["groups"] == [att, att] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S
        and o["rb"] == [rb, rb], f"att {o['att']} {o['groups']} readbacks {o['rb']}")
    exp_st = [RESTORING, MISMATCH_1 + suffix, RESTORING, MISMATCH_2 + suffix, OP_WAIT + suffix]
    res(out, f"{n}.3: the failed readback sets block_failed ({hl}), so the containment is NOT claimed (FW:20372): both "
             f"failure statuses and the operator wait end '{suffix}' ({sl}) and none says 'ECCO's own at 500 W' or "
             f"'held at the 500 W floor'; no verified-restore claim; mismatch count 2 -> the durable operator lockout "
             f"(FW:20482-20501), then the operator wait (FW:20535-20550)",
        not verified_claims(st) and not claims_in(st) and g["dump_verify_mismatch_count"] == 2
        and g["dump_operator_needed"] and no_deferred(st) == exp_st, f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; "
             f"dump_restore_contain set (FW:20043), dump_restore_block_failed set by the last attempt's failed readback "
             f"({hl}; reset only when an attempt starts, FW:19820), so dump_restore_contained clear (FW:20372); "
             f"dump_export_unverified set (FW:19845); bank 244 = 0 (Allow Export, not proven), {held}; the final status "
             f"is the operator wait naming 'export may continue'",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and g7["dump_restore_contain"] is True
        and g7["dump_restore_block_failed"] is True and g["dump_restore_contained"] is False
        and g["dump_export_unverified"] and b == exp_b and o["final"] == OP_WAIT + suffix and o["truth"][0],
        f"{o['marker']} {g7} {g} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: the override stays visible as the "
             f"snapshot mirror and the operator lockout)", not o["inv"], str(o["inv"]))
    c = o["claims"]
    res(out, f"{n}.6: the containment-claim helper (contain_claims): no status of the timeline claims a containment that "
             f"the bank at its publish instant does not back (here: none claims one)", c["ok"] and c["n"] == 0, str(c))
    return out


def checks_09b7cm(o: dict) -> dict:
    """W6-1c, the comms path in containment (FW-09 c's shape with the floor block unapplied and its readback unanswered).
    Expected values derived from the firmware: the pre-read finds 244 at ECCO's Allow Export 0 (action 1, FW:19837-19838;
    dump_export_unverified set, FW:19845) and every slot at the 1000 W lease value (ECCO-owned, nothing FOREIGN,
    FW:19856-19881); the 244 write lands (FW:19925-19962) but its verify read returns an error (FW:19989-19993):
    write_failed is set and dump_restore_mismatch_this_attempt is NOT (only the on_response compare sets it, FW:19984), so
    244 is not proven (FW:20019) and the attempt contains (FW:20020): nothing FOREIGN, so the containment term makes wmask
    0x3F (FW:20031) and the 6-slot floor block (FW:20045-20086) is written, acknowledged but not applied (on_response: no
    block_failed); the readback runs (FW:20316-20325) and gets no response (FW:20348-20352: block_failed and
    write_failed), so dump_restore_contained stays clear (FW:20372) and there is no FOREIGN lockout (FW:20373). No
    mismatch this attempt, so the COMMS path (FW:20482, FW:20508-20519): dump_comms_restore_attempts 1, the backoff armed
    (comms_backoff_ms(1) = 15 s), no lockout (a comms failure never locks, FW:20434-20442); the suffix (FW:20447-20459):
    export unverified, nothing FOREIGN named (dump_restore_uncontained empty, FW:19879), not contained -> '; register 244
    is NOT proven out of Allow Export - export may continue' (FW:20457-20458). The retry (suite tail) runs on the Dump
    watchdog once the backoff has passed (FW:19773-19775, FW:24221-24248): its pre-read finds 244 at its ORIGINAL 2
    (action 0, FW:19835-19836; dump_export_unverified cleared, FW:19845) and 256-261 at 1000 W (ECCO's own), so 244 is not
    written and is proven (FW:20019: action != 1), nothing is contained and the plan is the owned slots, widened to 0x3F
    (FW:20031, FW:20035) with v = ORIGINAL (FW:20029); the block lands, its readback verifies (FW:20335-20342) and the
    restore completes (FW:20378-20419: RESTORED OK, marker CLEAR)."""
    out: dict = {}
    st, g, g7, b, n = o["statuses"], o["g"], o["g7"], o["bank"], "FW-09 b7-cmnr"
    floor = [min(ORIG[a], FLOOR_W) for a in TOU]
    res(out, f"{n}.1: 244 is written and lands (FW:19925-19962) but its verify read errors (FW:19989-19993: write_failed, "
             f"no mismatch flag), so 244 is not proven and the attempt contains (FW:20019-20043): nothing FOREIGN, the "
             f"6-slot floor block (wmask 0x3F, FW:20031) acknowledged but not applied; its readback gets no response "
             f"(FW:20348-20352); the attempt fails on the COMMS path (FW:20508-20519): comms attempts 1, backoff armed, "
             f"mismatch count 0",
        o["groups"] == [[(244, [ORIG[244]], "ok"), (256, floor, "ack_not_applied")]] and o["rb"] == ["no_response"]
        and g["dump_comms_restore_attempts"] == 1 and g["dump_restore_next_attempt_ms"] != 0
        and g["dump_verify_mismatch_count"] == 0, f"{o['groups']} readbacks {o['rb']} {g}")
    res(out, f"{n}.2: the comms-path status names the failure and 'export may continue' (FW:20457-20458, FW:20517), never "
             f"'ECCO's own at 500 W' or 'held at the 500 W floor' (the readback never answered: FW:20372); no "
             f"verified-restore claim; the obligation and its retries are kept: marker RESTORE_REQUIRED, snapshot valid, "
             f"no operator lockout (FW:20434-20442)",
        no_deferred(st) == [RESTORING, COMMS_FAIL + EXPORT_MAY] and not claims_in(st) and not verified_claims(st)
        and o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and not g["dump_operator_needed"],
        f"{st} {o['marker']} {g}")
    res(out, f"{n}.3: the report is truthful at the document's end: dump_restore_contain set (FW:20043), "
             f"dump_restore_block_failed set (FW:20352), so dump_restore_contained clear (FW:20372); "
             f"dump_export_unverified set (FW:19845); bank 244 = {ORIG[244]} (landed, not proven), 256-261 = {LEASE_W} W "
             f"(the floor block unapplied)",
        g7["dump_restore_contain"] is True and g7["dump_restore_block_failed"] is True
        and g["dump_restore_contained"] is False and g["dump_export_unverified"] and o["truth"][0]
        and b == {244: ORIG[244], **{a: LEASE_W for a in TOU}}, f"{g7} {g} {b} {o['truth'][1]}")
    res(out, f"{n}.4: every core invariant holds (INV-NO-SILENT-OVERRIDE: the snapshot mirror stays visible)", not o["inv"],
        str(o["inv"]))
    t = o.get("tail") or {}
    bound = BACKOFF_S[0] + WD_S
    res(out, f"{n}.5: the automatic retry after the comms backoff ({BACKOFF_S[0]} s, on the {WD_S:.0f} s watchdog grid: "
             f"<= {bound:.0f} s after the END) finds 244 ORIGINAL (no 244 write; proven) and 256-261 at {LEASE_W} W (ECCO's "
             f"own), so it does not contain: it writes the ORIGINAL 256-261 block, which lands and verifies, and "
             f"completes - RESTORING, RESTORED OK, marker CLEAR, dump_export_unverified clear, bank ORIGINAL, "
             f"invariants hold",
        bool(t) and len(t["att"]) == 2 and BACKOFF_S[0] <= t["att"][1] <= bound
        and t["groups"][1] == [(256, ORIG_TOU, "ok")] and t["rb"] == ["no_response", "ok"]
        and no_deferred(t["statuses"])[2:] == [RESTORING, RESTORED] and len(no_deferred(t["statuses"])) == 4
        and t["final"] == RESTORED and t["marker"] == "CLEAR" and not t["g"]["dump_export_unverified"]
        and t["bank"] == {a: ORIG[a] for a in DUMP_REGS} and not t["inv"], str(t)[:400])
    c = o["claims"]
    res(out, f"{n}.6: the containment-claim helper (contain_claims) over the whole timeline, the retry included: no "
             f"status claims a containment that the bank at its publish instant does not back (here: none claims one)",
        c["ok"] and c["n"] == 0, str(c))
    return out


def checks_09b7ab(o: dict) -> dict:
    """W6-1c, two containment attempts: the first verified, the second failed. Expected values derived from the firmware:
    attempt 1 (at the End) as FW-09 a's - the pre-read finds 244 at ECCO's 0 (action 1, FW:19837-19845) and every slot at
    the 1000 W lease value (ECCO-owned, nothing FOREIGN, FW:19856-19881); 244's write is acknowledged but not applied
    (FW:19982-19985: write_failed, a mismatch), so 244 is not proven and the attempt contains (FW:20019-20043: wmask 0x3F,
    every slot at 500 W, dump_restore_contain set); this time the floor block lands ('write:256x6' first outcome ok,
    FW:20045-20086) and its readback verifies (FW:20316-20342), so block_failed stays clear and dump_restore_contained is
    set (FW:20372); the mismatch path (FW:20482, FW:20502-20506) publishes 'RESTORE VERIFY FAILED ...; register 244 NOT
    proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor' (FW:20455-20456), true at that
    instant (256-261 at 500 W). Right after it the inverter puts 258 back to its ORIGINAL 7000 W; the lease is over
    (dump_restore_requested set, FW:20606), so the ACTIVE drift check never runs (FW:24268-24272, FW:24396-24424). Attempt
    2 at the next Dump watchdog tick (FW:24221-24248) first resets dump_restore_contained (FW:19819); its pre-read finds
    244 at 0 again, 258 at its ORIGINAL (neither owned nor FOREIGN, FW:19860-19867) and the other slots at the 500 W floor
    (ECCO's own, FW:19858-19861); the containment writes every non-FOREIGN slot (FW:20031: wmask 0x3F) and the floor block
    is acknowledged but not applied (the second outcome); the readback finds 258 at 7000 W, not 500 W (FW:20335-20341:
    block_failed), so dump_restore_contained stays clear (FW:20372); mismatch 2 -> the operator lockout (FW:20484-20501)
    with '; register 244 is NOT proven out of Allow Export - export may continue' (export unverified, not contained,
    nothing FOREIGN: FW:20457-20458), then the operator wait with the same (FW:20535-20550, FW:20545-20546)."""
    out: dict = {}
    st, g, g7, b, n = o["statuses"], o["g"], o["g7"], o["bank"], "FW-09 b7-ab"
    floor = [min(ORIG[a], FLOOR_W) for a in TOU]
    w244 = (244, [ORIG[244]], "ack_not_applied")
    a1, a2 = [w244, (256, floor, "ok")], [w244, (256, floor, "ack_not_applied")]
    c = o["claims"]
    res(out, f"{n}.1: attempt 1 is a VERIFIED containment: 244 acknowledged but not applied (not proven, FW:19982-19985), "
             f"the 6-slot floor block (wmask 0x3F, FW:20031) lands and its readback answers and verifies "
             f"(FW:20316-20342), so its status claims the containment ('held at the 500 W floor', FW:20455-20456), "
             f"backed by the bank at its publish instant (256-261 at {FLOOR_W} W)",
        bool(o["groups"]) and o["groups"][0] == a1 and o["rb"][:1] == ["ok"]
        and no_deferred(st)[:2] == [RESTORING, MISMATCH_1 + CONTAINED] and c["backed"][:1] == [True],
        f"{o['groups'][:1]} readbacks {o['rb']} {st} {c}")
    res(out, f"{n}.2: after attempt 1 the inverter puts {AB_SLOT} back to its ORIGINAL {ORIG[AB_SLOT]} W; the automatic "
             f"retry at the next watchdog tick (<= {WD_S:.0f} s later) contains again - {AB_SLOT} at its ORIGINAL is "
             f"neither owned nor FOREIGN (FW:19860-19867) and is written with the rest (wmask 0x3F, FW:20031) - and its "
             f"floor block is acknowledged but not applied; exactly two attempts, both readbacks answered",
        o["groups"] == [a1, a2] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S
        and o["rb"] == ["ok", "ok"], f"att {o['att']} {o['groups']} readbacks {o['rb']}")
    exp_st = [RESTORING, MISMATCH_1 + CONTAINED, RESTORING, MISMATCH_2 + EXPORT_MAY, OP_WAIT + EXPORT_MAY]
    res(out, f"{n}.3: attempt 2's readback finds {AB_SLOT} at {ORIG[AB_SLOT]} W, not {FLOOR_W} W (FW:20335-20341: "
             f"block_failed), and dump_restore_contained, reset when the attempt started (FW:19819), stays clear "
             f"(FW:20372): the lockout and the operator wait end '{EXPORT_MAY}' (FW:20457-20458, FW:20545-20546) and no "
             f"status published after attempt 2 started claims the containment; no verified-restore claim; mismatch "
             f"count 2 -> the durable operator lockout (FW:20482-20501), then the operator wait (FW:20535-20550)",
        no_deferred(st) == exp_st and not claims_in(no_deferred(st)[2:]) and not verified_claims(st)
        and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"], f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; "
             f"dump_restore_contain set, dump_restore_block_failed set (FW:20337), dump_restore_contained clear "
             f"(FW:19819, FW:20372), dump_export_unverified set; bank 244 = 0, {AB_SLOT} = {ORIG[AB_SLOT]} W (its "
             f"ORIGINAL, the floor block unapplied), every other slot {FLOOR_W} W; the final status is the operator wait "
             f"naming 'export may continue'",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and g7["dump_restore_contain"] is True
        and g7["dump_restore_block_failed"] is True and g["dump_restore_contained"] is False
        and g["dump_export_unverified"] and b == {244: 0, **dict(zip(TOU, floor)), AB_SLOT: ORIG[AB_SLOT]}
        and o["final"] == OP_WAIT + EXPORT_MAY and o["truth"][0],
        f"{o['marker']} {g7} {g} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: the override stays visible as the "
             f"snapshot mirror and the operator lockout)", not o["inv"], str(o["inv"]))
    res(out, f"{n}.6: the containment-claim helper (contain_claims): every containment claim of the timeline is backed by "
             f"the bank at its publish instant - attempt 1's, with 256-261 at {FLOOR_W} W - and there is exactly that one",
        c["ok"] and c["n"] == 1, str(c))
    return out


def checks_09b7af(o: dict) -> dict:
    """W6-1c, containment with every 256-261 slot FOREIGN. Expected values derived from the firmware: the pre-read finds
    244 at ECCO's 0 (action 1, FW:19837-19845) and every slot at 4000 W - neither its ORIGINAL nor ECCO's 1000 W ceiling /
    pending ceiling nor its 500 W floor: FOREIGN (FW:19856-19867; foreign mask 0x3F); the NOT CONTAINED list '256=4000W
    ... 261=4000W' is 59 characters, over 52, so dump_restore_uncontained holds the register numbers alone, '256 257 258
    259 260 261' (FW:19868-19879). 244's write is acknowledged but not applied (FW:19982-19985: write_failed, a mismatch),
    so 244 is not proven and the attempt would contain (FW:20019-20020), but every slot is FOREIGN, so m == 0
    (FW:20027-20032), wmask 0 and dump_restore_contain stays clear (FW:20043: contain && m != 0); nothing is written to
    256-261 (FW:20045, FW:20087-20314) and nothing read back (FW:20316-20318: wmask != 0); dump_restore_contained stays
    clear (FW:20372; block_failed, reset at FW:19820, is never set); write_failed keeps the FOREIGN lockout away
    (FW:20373). The suffix (FW:20449-20454): '; 244 NOT proven off; export may continue; NOT CONTAINED: 256 257 258 259 260
    261'. Mismatch 1 -> one automatic retry at the next Dump watchdog tick (FW:20502-20506), the same; mismatch 2 -> the
    operator lockout (FW:20484-20501), then the operator wait with the same suffix (FW:20535-20550, FW:20538-20542)."""
    out: dict = {}
    st, g, g7, b, n = o["statuses"], o["g"], o["g7"], o["bank"], "FW-09 b7-af"
    suffix = UNPROVEN_244 + MAY_CONTINUE + NOT_CONTAINED + ALL_FOREIGN
    w244 = [(244, [ORIG[244]], "ack_not_applied")]
    res(out, f"{n}.1: every 256-261 slot reads {FOREIGN_W} W (the inverter's own: FOREIGN, FW:19856-19867), so the "
             f"containment plan is empty (m == 0, FW:20027-20032): each attempt writes 244 alone (acknowledged but not "
             f"applied) and no 256-261 slot, and no 256-261 readback runs (FW:20316-20318: wmask 0); no comms failure",
        o["groups"][:1] == [w244] and o["rb"] == [] and g["dump_comms_restore_attempts"] == 0,
        f"{o['groups']} readbacks {o['rb']} {g}")
    res(out, f"{n}.2: the automatic retry at the next watchdog tick (<= {WD_S:.0f} s later) is the same 244-only attempt; "
             f"exactly two attempts",
        o["groups"] == [w244, w244] and len(o["att"]) == 2 and 0 < o["att"][1] - o["att"][0] <= WD_S,
        f"att {o['att']} {o['groups']}")
    exp_st = [RESTORING, MISMATCH_1 + suffix, RESTORING, MISMATCH_2 + suffix, OP_WAIT + suffix]
    res(out, f"{n}.3: nothing was contained, so no status claims it (FW:20043, FW:20372): both failure statuses and the "
             f"operator wait end '{suffix}' (FW:20449-20454, FW:20538-20542; the six FOREIGN slots named by number, the "
             f"59-character list being over 52, FW:19879) and none says 'ECCO's own at 500 W' or 'held at the 500 W "
             f"floor'; no verified-restore claim and no FOREIGN-lockout claim (write_failed, FW:20373); mismatch count 2 "
             f"-> the durable operator lockout (FW:20482-20501), then the operator wait (FW:20535-20550)",
        no_deferred(st) == exp_st and not claims_in(st) and not verified_claims(st)
        and g["dump_verify_mismatch_count"] == 2 and g["dump_operator_needed"], f"{st} {g}")
    res(out, f"{n}.4: the obligation is kept and the report is truthful: marker RESTORE_REQUIRED, snapshot valid; "
             f"dump_restore_contain clear (FW:20043: m == 0), dump_restore_wmask 0, dump_restore_block_failed clear "
             f"(nothing written or read back), dump_restore_contained clear (FW:20372), dump_export_unverified set; bank "
             f"244 = 0 (Allow Export, not proven), 256-261 = {FOREIGN_W} W (FOREIGN, untouched); the final status is the "
             f"operator wait naming every slot NOT CONTAINED",
        o["marker"] == "RESTORE_REQUIRED" and g["dump_snapshot_valid"] and g7["dump_restore_contain"] is False
        and g7["dump_restore_wmask"] == 0 and g7["dump_restore_block_failed"] is False
        and g["dump_restore_contained"] is False and g["dump_export_unverified"]
        and b == {244: 0, **{a: FOREIGN_W for a in TOU}} and o["final"] == OP_WAIT + suffix and o["truth"][0],
        f"{o['marker']} {g7} {g} {b} {o['final']!r} {o['truth'][1]}")
    res(out, f"{n}.5: every core invariant holds (no INV-NO-SILENT-OVERRIDE violation: the FOREIGN slots are excluded, 244 "
             f"stays visible as the snapshot mirror)", not o["inv"], str(o["inv"]))
    c = o["claims"]
    res(out, f"{n}.6: the containment-claim helper (contain_claims): no status claims a containment that the bank at its "
             f"publish instant does not back - a claim needs at least one non-FOREIGN slot (FW:20043) and here every slot "
             f"is FOREIGN (here: none claims one)", c["ok"] and c["n"] == 0, str(c))
    return out


def run_09(fw, key: str, phase_ms=None, claims: dict | None = None) -> dict:
    """The checks of FW-09 timeline `key` on firmware `fw`; `claims` (section [1], plain firmware only): a dict that
    receives the timeline's containment-claim helper result (contain_claims, after any suite tail)."""
    table = {"a": ("FW-09-a", checks_09a, tail_force), "b": ("FW-09-b", checks_09b, None),
             "b2": ("FW-09-b2", checks_09b2, None), "c": ("FW-09-c", lambda o: checks_09c(o, "c"), tail_retry),
             "c2": ("FW-09-c2", lambda o: checks_09c(o, "c2"), tail_retry)}
    table.update({f"b3-{k}": (f"FW-09-b3-{k}", lambda o, k=k: checks_09b3(o, k), None) for k in B3_SLOTS})
    table.update({k: (f"FW-09-{k}", lambda o, k=k: checks_09b4(o, k), None) for k in B4_CASES})
    table.update({k: (f"FW-09-{k}", lambda o, k=k: checks_09ps(o, k), None) for k in PS_CASES})
    table["b6-ok"] = ("FW-09-b6-ok", checks_09b6ok, None)
    b7 = {k: (lambda o, k=k: checks_09b7rb(o, k)) for k in B7_RB}
    b7.update({"b7-cmnr": checks_09b7cm, "b7-ab": checks_09b7ab, "b7-af": checks_09b7af})
    if key in b7:
        o = obs09b7(fw, key, phase_ms)
        if claims is not None:
            claims[key] = o["claims"]
        return b7[key](o)
    cid, fn, tail = table[key]
    o = obs09(fw, cid, tail, phase_ms)
    if claims is not None:
        claims[key] = contain_claims(o["w"], cid)
    return fn(o)


def section_09() -> None:
    print("[1] FW-09 Dump restore verification: 244 / 256-261 writes acknowledged but not applied, verify reads failing")
    timelines = ("a", "b", "b2") + B3_KEYS + B456_KEYS + B7_KEYS + ("c", "c2")
    claims: dict = {}
    for key in timelines:
        for name, (ok, detail) in run_09(FW, key, claims=claims).items():
            check(name, ok, detail)
    # the brief inconsistency, characterised: M9 / C6 cannot reach the c / c2 failure path
    same = []
    for key, cid in (("c", "FW-09-c"), ("c2", "FW-09-c2")):
        base = obs09(FW, cid, tail_retry)
        for mid in ("M9", "C6"):
            fw = mutant(mid)
            if fw is None:
                same.append((key, mid, "mutant invalid"))
                continue
            m = obs09(fw, cid, tail_retry)
            keys = ("statuses", "final", "att", "groups", "marker", "bank", "g", "inv", "tail")
            if {k: m[k] for k in keys} != {k: base[k] for k in keys}:
                same.append((key, mid, "outcome differs"))
    check("FW-09 c-blind: M9 and C6 cannot change c / c2 - their failure path runs the verify reads' on_error / "
          "on_no_response handlers (FW:19989-20003, FW:20343-20357), never the mutated on_response compares (FW:19982, "
          "FW:20336): under M9 and C6 the c / c2 observations equal the baseline's (so c / c2 carry their own error-branch "
          "mutants MC244 / MC256)", not same, str(same))
    # W6-1c: the containment-claim truthfulness helper over EVERY FW-09 timeline (the suite tails of a, c, c2 and b7-cmnr
    # included), on the plain firmware
    seen = ", ".join(f"{k} {c['n']}" for k, c in claims.items() if c["n"])
    print(f"  info  FW-09 containment claims checked against the bank at their publish instant: "
          f"{sum(c['n'] for c in claims.values())} in {len(claims)} timelines ({seen})")
    bad = {k: c["bad"] for k, c in claims.items() if not c["ok"]}
    check("FW-09 claims: on every FW-09 timeline (a, b, b2, b3-*, b4-*, b5-lo, b6-*, b7-*, c, c2; the suite tails "
          "included) every containment claim among the Dump statuses ('ECCO's own at 500 W', 'held at the 500 W floor'; "
          "FW:20449-20456, FW:20538-20544) is backed by the bank as it stood when that status was published: at least "
          "one 256-261 slot non-FOREIGN at the attempt's pre-read (FW:19856-19867, FW:20043 m != 0) and every one at "
          "min(original, 500 W) (FW:20028-20031, FW:20372); at least one claim is checked (contain_claims)",
          not bad and sorted(claims) == sorted(timelines) and sum(c["n"] for c in claims.values()) > 0, str(bad)[:400])


# =============================================================================================================================
# [2] FW-10 the Free Power terms of the Dump START gate
# =============================================================================================================================
G10 = ["free_power_active_persisted", "free_power_snapshot_valid", "free_power_operation_in_progress",
       "free_power_recovery_metadata_corrupt"]
FP_STATE = {"A": ("RESTORE_REQUIRED", {"free_power_active_persisted": True, "free_power_snapshot_valid": True,
                                       "free_power_operation_in_progress": False,
                                       "free_power_recovery_metadata_corrupt": False}),
            "B": ("PENDING_CLEAR", {"free_power_active_persisted": False, "free_power_snapshot_valid": True,
                                    "free_power_operation_in_progress": False,
                                    "free_power_recovery_metadata_corrupt": False}),
            "C": ("CLEAR", {"free_power_active_persisted": False, "free_power_snapshot_valid": True,
                            "free_power_operation_in_progress": False, "free_power_recovery_metadata_corrupt": True})}
FP_STATUS = {"A": FP_VERIFY_ERR, "B": FP_PENDING, "C": FP_UNKNOWN}
FP_WHY = {"A": "RESTORE_REQUIRED (the final 256-279 verify read failed: comms path, backoff, FW:11322-11332)",
          "B": "PENDING_CLEAR (the restore verified, Phase D's durable CLEAR did not land, FW:11256-11266)",
          "C": "in the SG-06 UNKNOWN lockout (its stored CLEAR marker unreadable at boot, FW:532-538)"}


def tail_10(w) -> None:
    """Suite-only continuation of FW-10 A / B: 60 s for the Free Power watchdog to resolve the state (A: the retried
    restore after the comms backoff; B: the retried durable clear, FW:24131), then the same Dump START again."""
    w.run_for(60)
    w.telemetry(grid_w=L.SITE["dump_grid_w"], batt_w=L.SITE["dump_battery_w"])
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)


def control_10c(fw, phase_ms=None):
    """FW-10 C's counterfactual control: the identical timeline with a plain reboot (no NVS boot fault), so the same Dump
    START meets no Free Power lockout. (A control world, not a continuation: it does not rely on how the lab's read_error
    boot fault heals at a later boot.)"""
    a = [dict(x, args={}) if x["do"] == "reboot" else x for x in acts("FW-10-c")]
    return play(fw, a, phase_ms)


def run_10(fw, key: str, phase_ms=None) -> dict:
    a = acts(f"FW-10-{key.lower()}")
    w = play(fw, a[:-1], phase_ms)
    pre = {"marker": w.nvs_marker("fp"), "g": w.globals_view(G10), "bank": {x: w.bank[x] for x in FP_REGS + (244,)},
           "status": w.status("fp")}
    seq0 = len(w.log) - 1
    run_actions(w, a[-1:])
    wr = [x for x in w.writes() if x["seq"] > seq0]
    post = {"status": w.status("dump"), "marker": w.nvs_marker("dump"), "writes": wr,
            "dump": w.globals_view(["dump_active_persisted", "dump_snapshot_valid"]),
            "conflict": w.globals_view(["dump_start_tou_conflict_slot"])["dump_start_tou_conflict_slot"], "inv": inv_list(w)}
    if key == "C":
        w = control_10c(fw, phase_ms)
    else:
        tail_10(w)
    later = {"fp": (w.nvs_marker("fp"), w.status("fp"), w.corrupt("fp")), "dump": w.status("dump"), "inv": inv_list(w)}
    out: dict = {}
    n = f"FW-10 {key}"
    marker, flags = FP_STATE[key]
    res(out, f"{n}.1: when the Dump START is pressed Free Power is {FP_WHY[key]}: its stored marker {marker}, RAM flags "
             f"(active {flags['free_power_active_persisted']}, snapshot {flags['free_power_snapshot_valid']}, corrupt "
             f"{flags['free_power_recovery_metadata_corrupt']}, no transaction) and status, and every Free Power owned "
             f"register and 244 at ORIGINAL - so the TOU charge-flag walk (FW:18041) finds no conflict and only the Free "
             f"Power gate terms (FW:18060-18061) can refuse",
        pre["marker"] == marker and pre["g"] == flags and pre["status"] == FP_STATUS[key]
        and pre["bank"] == {x: ORIG[x] for x in FP_REGS + (244,)} and post["conflict"] == 0, f"{pre} conflict "
                                                                                            f"{post['conflict']}")
    res(out, f"{n}.2: the Dump START is REJECTED citing Free Power (FW:18890) and writes nothing: no inverter write, the "
             f"Dump marker never stored (ABSENT), no Dump lease or snapshot",
        post["status"] == REJ_FP and not post["writes"] and post["marker"] == "ABSENT"
        and post["dump"] == {"dump_active_persisted": False, "dump_snapshot_valid": False},
        f"{post['status']!r} writes {[(x['addr'], x['vals']) for x in post['writes']]} {post['marker']} {post['dump']}")
    res(out, f"{n}.3: every core invariant holds (INV-ONE-LEASE, INV-NO-2ND-RESTORER, INV-LOCKOUT-QUIET)", not post["inv"],
        str(post["inv"]))
    resolved = {"A": FP_RESTORED, "B": FP_RESOLVED, "C": None}[key]
    res(out, f"{n}.4: " + {"A": "once the Free Power watchdog's retry after the comms backoff restored and verified,",
                           "B": "once the Free Power watchdog's retried durable clear landed (FW:24131),",
                           "C": "in the control timeline with a plain reboot instead of the read-error boot,"}[key]
        + " the same Dump START is admitted (ACTIVE - VERIFIED OK) with the Free Power marker CLEAR and no lockout: only "
          "the Free Power state refused it; invariants hold",
        later["fp"][0] == "CLEAR" and not later["fp"][2] and (resolved is None or later["fp"][1] == resolved)
        and later["dump"].startswith(DUMP_ACTIVE) and not later["inv"], str(later))
    return out


def section_10() -> None:
    print("[2] FW-10 Dump START gate: the Free Power terms refuse alone (RESTORE_REQUIRED, PENDING_CLEAR, UNKNOWN lockout)")
    for key in ("A", "B", "C"):
        for name, (ok, detail) in run_10(FW, key).items():
            check(name, ok, detail)


# =============================================================================================================================
# [3] FW-11 Free Power marker boot faults on a used fp.valid key; the M7a equivalence
# =============================================================================================================================
BAD_MAGIC_XOR = 0x00FF00FF
FAULT_DOC = {("read_error", "CLEAR"): "FW-11-a", ("read_error", "RR"): "FW-11-b", ("wrong_size", "CLEAR"): "FW-11-c",
             ("wrong_size", "RR"): "FW-11-d"}


def reboot_bad_magic(w) -> None:
    """WHITE-BOX (suite only, MODEL): run one telemetry period with a capture after every firmware event, take the last
    capture, replace its fp.valid record by a ValidMarker whose magic differs from VALID_MARKER_MAGIC (state kept), and
    boot from it (reboot_from: a power cut at that capture). No replay boot-fault mode writes a bad magic; the edit is not
    logged as fault.nvs_boot."""
    tag = L.MARKER_TAGS["fp"]
    caps = w.capture_points(lambda ww: ww.run_for(TEL_S + 5))
    if not caps:
        raise L.LabHarnessError("bad magic: no firmware event to capture")
    cap = caps[-1]
    rec = cap["nvs"].get(tag)
    if rec is None or rec._kind != "ValidMarker" or rec.magic != ds.Durable.VALID_MARKER_MAGIC:
        raise L.LabHarnessError("bad magic: the fp.valid key holds no valid stored marker (a used key is required)")
    cap["nvs"][tag] = ds.Record("ValidMarker", rec.magic ^ BAD_MAGIC_XOR, rec.state)
    w.reboot_from(cap)


def run_11(fw, fault: str, stored: str) -> dict:
    """One FW-11 timeline: read_error / wrong_size are the corpus documents FW-11-a..d; bad_magic replays the wrong_size
    document's timeline with the reboot replaced by reboot_bad_magic()."""
    a = acts(FAULT_DOC[("wrong_size" if fault == "bad_magic" else fault, stored)])
    i = [k for k, x in enumerate(a) if x["do"] == "reboot"][0]
    w = play(fw, a[:i])
    pre = {"marker": w.nvs_marker("fp"), "status_hist": w.status_history("fp"),
           "bank": {x: w.bank[x] for x in FP_REGS}}
    if fault == "bad_magic":
        reboot_bad_magic(w)
    else:
        run_actions(w, a[i:i + 1])
    boot = w.boot_no
    run_actions(w, a[i + 1:])
    o = w.obligations()["fp"]
    fp_writes = [(x["addr"], x["vals"]) for x in w.writes() if x["boot"] == boot and set(range(x["addr"], x["addr"] + len(
        x["vals"]))) & set(FP_REGS)]
    return {"pre": pre, "corrupt": w.corrupt("fp"), "snap": o["snap"], "status": w.status("fp"), "marker": w.nvs_marker("fp"),
            "bank": {x: w.bank[x] for x in FP_REGS}, "fp_writes": fp_writes, "inv": inv_list(w)}


def checks_11(o: dict, fault: str, stored: str) -> dict:
    out: dict = {}
    n = f"FW-11 {fault} ({'CLEAR' if stored == 'CLEAR' else 'RESTORE_REQUIRED'})"
    exp_pre = "CLEAR" if stored == "CLEAR" else "RESTORE_REQUIRED"
    used = (FP_RESTORED in o["pre"]["status_hist"] and o["pre"]["marker"] == exp_pre)
    unknown = fault == "read_error"
    lines = "FW:522-538" if unknown else ("FW:526, FW:539-550" if fault == "wrong_size" else "FW:527, FW:539-550")
    res(out, f"{n}.1: on the used key (a completed lease first) the FULL on_boot locks Free Power - snapshot_valid and "
             f"recovery_metadata_corrupt set ({lines}) - and the status names the " + ("UNKNOWN obligation (FW:1180-1183)"
                                                                                       if unknown else
                                                                                       "untrusted record (FW:1184-1190)"),
        used and o["corrupt"] and o["snap"] and o["status"] == (FP_UNKNOWN if unknown else FP_MALFORMED),
        f"used {used} {o['pre']['marker']} corrupt {o['corrupt']} snap {o['snap']} {o['status'][:90]!r}")
    exp_marker = exp_pre if unknown else "MALFORMED"
    res(out, f"{n}.2: the stored record is left untouched (reads {exp_marker}; no commit, FW:533-535 / FW:541-543) and no "
             f"Free Power register is written after the boot (the watchdog refuses a corrupt domain, FW:24119); the "
             f"bank keeps the stored state's values",
        o["marker"] == exp_marker and not o["fp_writes"] and o["bank"] == o["pre"]["bank"],
        f"{o['marker']} writes {o['fp_writes']} bank {o['bank']} vs {o['pre']['bank']}")
    res(out, f"{n}.3: every core invariant holds (INV-BOOT-MIRROR, INV-NO-SILENT-OVERRIDE, INV-LOCKOUT-QUIET)",
        not o["inv"], str(o["inv"]))
    return out


def run_11_fault(fw, fault: str) -> dict:
    out: dict = {}
    for stored in ("CLEAR", "RR"):
        out.update(checks_11(run_11(fw, fault, stored), fault, stored))
    return out


def m7a_equivalence() -> tuple[bool, str]:
    """Static: free_power_active_persisted := true only at the boot's data load (right after snapshot_valid := true) and
    at the START's activation verify; every free_power_snapshot_valid := false site clears active_persisted in the same
    lambda (within 25 lines before / 3 after) or is the boot's CLEAR branch; active_persisted is not restore_value."""
    lines = FW["_text"].split("\n")
    act_true = [i for i, x in enumerate(lines) if "id(free_power_active_persisted) = true;" in x]
    act_load = [i for i, x in enumerate(lines) if "id(free_power_active_persisted) = data.active_persisted != 0;" in x]
    snap_false = [i for i, x in enumerate(lines) if "id(free_power_snapshot_valid) = false;" in x]
    bad = []
    if len(act_true) != 1 or len(act_load) != 1 or "id(free_power_snapshot_valid) = true;" not in lines[act_load[0] - 1]:
        bad.append(("act := true sites", [i + 1 for i in act_true + act_load]))
    for i in snap_false:
        near = any("id(free_power_active_persisted) = false;" in x for x in lines[max(0, i - 25):i + 4])
        boot_clear = "if (state == ecco_durable::MARKER_CLEAR) {" in lines[i - 1]
        if not (near or boot_clear):
            bad.append(("snapshot_valid := false without active_persisted := false", i + 1))
    decl = re.search(r"- id: free_power_active_persisted\n\s+type: bool\n\s+restore_value: no\n", FW["_text"])
    if decl is None:
        bad.append(("free_power_active_persisted is restore_value", None))
    return not bad and len(snap_false) >= 1, f"{bad} act:=true {[i + 1 for i in act_true]} load {[i + 1 for i in act_load]}" \
                                             f" snap:=false {[i + 1 for i in snap_false]}"


def section_11() -> None:
    print("[3] FW-11 Free Power marker boot faults on a used fp.valid key (read error, wrong size, bad magic); M7a "
          "equivalence")
    for fault in ("read_error", "wrong_size", "bad_magic"):
        for name, (ok, detail) in run_11_fault(FW, fault).items():
            check(name, ok, detail)
    ok, detail = m7a_equivalence()
    print(f"  info  M7a equivalence sites: {detail}")
    check("FW-10 M7a-equivalence: active_persisted is set only at the boot data load right after snapshot_valid (FW:572-573) "
          "and at the START activation verify (FW:9762, snapshot_valid set at FW:9164 in the same START); every "
          "snapshot_valid := false clears active_persisted in the same lambda or is the CLEAR boot branch (FW:555, "
          "restore_value no): no reachable state has active set with snapshot clear, so dropping only "
          "'!free_power_active_persisted' (M7a) is an equivalent mutant", ok, detail)


# =============================================================================================================================
# [4] negative controls (in-memory exact-count mutants of real guards; each must make its INTENDED checks fail)
# =============================================================================================================================
_FP_GATE = ("                !id(free_power_active_persisted) &&\n                !id(free_power_snapshot_valid) &&\n"
            "                !id(free_power_operation_in_progress) &&\n"
            "                // Register 244 standalone proof transaction: Dump also")
_FP525 = "free_power_marker_unreadable = marker_load == ecco_durable::LOAD_READ_ERROR;\n"
_FP526 = "            bool marker_malformed = marker_load == ecco_durable::LOAD_WRONG_SIZE || (have_marker && ("
_V244 = ("id(dump_export_unverified) = false;   // fcp2: 244 proven back to its original\n"
         "                                  }\n"
         "                          on_error:\n"
         "                            then:\n"
         "                              - lambda: |-\n"
         "                                  id(dump_op_terminal) = true;\n")
_V244_FAIL = "                                  if (id(dump_operation_in_progress)) id(dump_write_failed) = true;\n"
_V256 = ('ESP_LOGE("dump_to_grid", "RESTORE VERIFY FAILED on register %d (raw=%u expected=%u)", 256 + i, values[i], v[i]);\n'
         "                                }\n"
         "                              }\n"
         "                      on_error:\n"
         "                        then:\n"
         "                          - lambda: |-\n"
         "                              id(dump_op_terminal) = true;\n"
         "                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; id(dump_write_failed) = true; }\n"
         "                      on_no_response:\n"
         "                        then:\n"
         "                          - lambda: |-\n"
         "                              id(dump_op_terminal) = true;\n")
_V256_FAIL = ("                              if (id(dump_operation_in_progress)) { id(dump_restore_block_failed) = true; "
              "id(dump_write_failed) = true; }\n")
# W6-1: the 256-261 readback compare (FW:20336, once) and the readback loop with it (FW:20335-20336: the loop line alone
# occurs 16 times in the firmware, the two lines together exactly once)
_V256_IF = "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {"
_V256_LOOP = ("                              for (int i = 0; i < 6; i++) {\n"
              "                                " + _V256_IF)
# W6-1b: the readback's expected-value initialiser, its second row (FW:20333; the same three ids occur once more, at a
# smaller indentation, in the 6-slot block write FW:20057) and the mismatch branch's block_failed (FW:20337; the bare
# statement occurs 33 times, at this 34-space indentation once) - whole lines with their indentation, each exactly once
_V256_V345 = " " * 32 + "id(dump_restore_v3), id(dump_restore_v4), id(dump_restore_v5)"
_V256_BF = " " * 34 + "id(dump_restore_block_failed) = true;"
# W6-1c: the 256-261 readback's failure handlers (FW:20343-20366). The handler line _V256_FAIL occurs 24 times and the
# no-terminal-state fallback _V256_TMO 8 times in the firmware, so C6rh's anchor is the readback's whole failure tail
# FW:20340-20366 (from the 'RESTORE VERIFY FAILED on register %d' log to the 'verify reread of 256-261' log) and C6rn's
# is MC256's FW:20340-20352, each exactly once; the per-attempt reset (FW:19819) and the containment flag (FW:20043) are
# whole lines with their indentation, each exactly once
_V256_NO_BF = "                              if (id(dump_operation_in_progress)) { id(dump_write_failed) = true; }\n"
_V256_TMO = "                        id(dump_restore_block_failed) = true; id(dump_write_failed) = true;\n"
_V256_RB = (_V256 + _V256_FAIL
            + "                      on_not_sent:\n"
              "                        then:\n"
              "                          - lambda: |-\n"
              "                              id(dump_op_terminal) = true;\n"
            + _V256_FAIL
            + "\n"
              "                  - wait_until:\n"
              "                      condition:\n"
              "                        lambda: 'return id(dump_op_terminal);'\n"
              "                      timeout: 3000ms\n"
              "                  - lambda: |-\n"
              "                      if (!id(dump_op_terminal)) {\n"
            + _V256_TMO
            + '                        ESP_LOGE("dump_to_grid", "Restore verify reread of 256-261 did not reach a terminal '
              'state");\n')
_RESET_CONTAINED = " " * 16 + "id(dump_restore_contained) = false;\n"
_CONTAIN_FLAG = " " * 16 + "id(dump_restore_contain) = contain && m != 0;\n"
# id -> (description, [(old, new)]): each old must occur EXACTLY once in the production text
MUTANTS = {
    "M9": ("the Dump restore's register-244 readback compare disabled (FW:19982)",
           [("if (raw != id(dump_snapshot_reg244)) {", "if (false) {")]),
    "C6": ("the Dump restore's 256-261 readback mismatch term disabled (FW:20336)",
           [("if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {",
             "if (((id(dump_restore_wmask) >> i) & 1) && false) {")]),
    "MC244": ("the Dump restore's 244 verify read on_error no longer fails the attempt (FW:19993)",
              [(_V244 + _V244_FAIL, _V244)]),
    "MC256": ("the Dump restore's 256-261 verify read on_no_response no longer fails the attempt (FW:20352)",
              [(_V256 + _V256_FAIL, _V256)]),
    "C6k0": ("the Dump restore's 256-261 readback never verifies slot 256 (FW:20336 gains 'i != 0 &&')",
             [(_V256_IF, "if (i != 0 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6k1": ("the Dump restore's 256-261 readback never verifies slot 257 (FW:20336 gains 'i != 1 &&')",
             [(_V256_IF, "if (i != 1 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6k2": ("the Dump restore's 256-261 readback never verifies slot 258 (FW:20336 gains 'i != 2 &&')",
             [(_V256_IF, "if (i != 2 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6k3": ("the Dump restore's 256-261 readback never verifies slot 259 (FW:20336 gains 'i != 3 &&')",
             [(_V256_IF, "if (i != 3 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6k4": ("the Dump restore's 256-261 readback never verifies slot 260 (FW:20336 gains 'i != 4 &&')",
             [(_V256_IF, "if (i != 4 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6k5": ("the Dump restore's 256-261 readback never verifies slot 261 (FW:20336 gains 'i != 5 &&')",
             [(_V256_IF, "if (i != 5 && ((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6s0": ("the Dump restore's 256-261 readback loop starts at slot 257, so 256 is never verified (FW:20335 'i = 1')",
             [(_V256_LOOP, _V256_LOOP.replace("for (int i = 0; i < 6; i++) {", "for (int i = 1; i < 6; i++) {"))]),
    "C6s5": ("the Dump restore's 256-261 readback loop stops before slot 261, so 261 is never verified (FW:20335 'i < 5')",
             [(_V256_LOOP, _V256_LOOP.replace("for (int i = 0; i < 6; i++) {", "for (int i = 0; i < 5; i++) {"))]),
    "C6bf": ("a 256-261 readback mismatch no longer sets dump_restore_block_failed (FW:20337 commented out), so an "
             "unapplied containment write still counts as contained (FW:20372)",
             [(_V256_BF, " " * 32 + "  // id(dump_restore_block_failed) = true;")]),
    "C6om": ("the Dump restore's 256-261 readback checks the slots ECCO owned at the pre-read instead of the slots written "
             "this attempt (FW:20336 dump_restore_owned_mask instead of dump_restore_wmask)",
             [(_V256_IF, "if (((id(dump_restore_owned_mask) >> i) & 1) && values[i] != v[i]) {")]),
    "C6lt": ("the Dump restore's 256-261 readback flags only a value BELOW the expected one (FW:20336 '<' instead of '!=')",
             [(_V256_IF, "if (((id(dump_restore_wmask) >> i) & 1) && values[i] < v[i]) {")]),
    "C6r1": ("the Dump restore's 256-261 readback compares slot 257 with slot 256's expected value (FW:20336 "
             "'v[i == 1 ? i - 1 : i]')",
             [(_V256_IF, "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i == 1 ? i - 1 : i]) {")]),
    "C6r4": ("the Dump restore's 256-261 readback compares slot 260 with slot 259's expected value (FW:20336 "
             "'v[i == 4 ? i - 1 : i]')",
             [(_V256_IF, "if (((id(dump_restore_wmask) >> i) & 1) && values[i] != v[i == 4 ? i - 1 : i]) {")]),
    "C6v34": ("the Dump restore's 256-261 readback expected values swap slots 259 and 260 (FW:20333 v[] initialiser "
              "'id(dump_restore_v4), id(dump_restore_v3)')",
              [(_V256_V345, " " * 32 + "id(dump_restore_v4), id(dump_restore_v3), id(dump_restore_v5)")]),
    "C6rh": ("the Dump restore's 256-261 readback failure handlers no longer set dump_restore_block_failed (on_error, "
             "on_no_response, on_not_sent and the no-terminal-state fallback, FW:20347, FW:20352, FW:20357, FW:20365), so "
             "a containment whose readback failed still counts as contained (FW:20372)",
             [(_V256_RB, _V256_RB.replace(_V256_FAIL, _V256_NO_BF).replace(
                 _V256_TMO, "                        id(dump_write_failed) = true;\n"))]),
    "C6rn": ("the Dump restore's 256-261 readback no-response handler no longer sets dump_restore_block_failed "
             "(FW:20352), so a containment whose readback got no response still counts as contained (FW:20372)",
             [(_V256 + _V256_FAIL, _V256 + _V256_NO_BF)]),
    "C6rs": ("the Dump restore no longer resets dump_restore_contained when an attempt starts (FW:19819), so a verified "
             "containment attempt's claim survives into a later failed one",
             [(_RESET_CONTAINED, " " * 16 + "// reviewA: dump_restore_contained not reset per attempt\n")]),
    "C6m0": ("the Dump restore flags the containment even when its plan writes nothing ('&& m != 0' dropped, FW:20043), "
             "so a containment with every 256-261 slot FOREIGN counts as contained (FW:20372)",
             [(_CONTAIN_FLAG, " " * 16 + "id(dump_restore_contain) = contain;\n")]),
    "M7": ("both Free Power terms of the Dump START gate removed (FW:18060-18061)",
           [(_FP_GATE, _FP_GATE.replace("                !id(free_power_active_persisted) &&\n"
                                        "                !id(free_power_snapshot_valid) &&\n", ""))]),
    "M7a": ("only '!free_power_active_persisted' removed from the Dump START gate (FW:18060)",
            [(_FP_GATE, _FP_GATE.replace("                !id(free_power_active_persisted) &&\n", ""))]),
    "M7b": ("only '!free_power_snapshot_valid' removed from the Dump START gate (FW:18061)",
            [(_FP_GATE, _FP_GATE.replace("                !id(free_power_snapshot_valid) &&\n", ""))]),
    "C3": ("the Free Power marker READ_ERROR lockout removed: an unreadable marker reads as CLEAR (FW:525)",
           [(_FP525, "free_power_marker_unreadable = false;\n")]),
    "C7": ("the Free Power malformed-marker lockout removed: a wrong-size or bad-magic / bad-state record reads as CLEAR "
           "(FW:526-531)",
           [(_FP525 + _FP526,
             _FP525 + "            bool marker_malformed = false; have_marker = have_marker && !(have_marker && (")]),
    "C7ws": ("only the wrong-size term of the Free Power malformed-marker test removed (FW:526)",
             [(_FP525 + _FP526, _FP525 + "            bool marker_malformed = (have_marker && (")]),
}
EVALUATORS = {
    "FW-09 a": lambda fw: run_09(fw, "a"), "FW-09 b": lambda fw: run_09(fw, "b"), "FW-09 b2": lambda fw: run_09(fw, "b2"),
    "FW-09 c": lambda fw: run_09(fw, "c"), "FW-09 c2": lambda fw: run_09(fw, "c2"),
    "FW-09 b3-256": lambda fw: run_09(fw, "b3-256"), "FW-09 b3-257": lambda fw: run_09(fw, "b3-257"),
    "FW-09 b3-258": lambda fw: run_09(fw, "b3-258"), "FW-09 b3-259": lambda fw: run_09(fw, "b3-259"),
    "FW-09 b3-260": lambda fw: run_09(fw, "b3-260"), "FW-09 b3-261": lambda fw: run_09(fw, "b3-261"),
    "FW-10 A": lambda fw: run_10(fw, "A"), "FW-10 B": lambda fw: run_10(fw, "B"), "FW-10 C": lambda fw: run_10(fw, "C"),
    "FW-11 read_error": lambda fw: run_11_fault(fw, "read_error"),
    "FW-11 wrong_size": lambda fw: run_11_fault(fw, "wrong_size"),
    "FW-11 bad_magic": lambda fw: run_11_fault(fw, "bad_magic"),
}
EVALUATORS.update({f"FW-09 {k}": (lambda fw, k=k: run_09(fw, k)) for k in B456_KEYS})   # W6-1b
EVALUATORS.update({f"FW-09 {k}": (lambda fw, k=k: run_09(fw, k)) for k in B7_KEYS})     # W6-1c
# (nid, mutant id, evaluators, intended check-name prefixes that must FAIL, expected outcome, reason for a survival)
NC_TABLE = [
    ("NC-FW09-1", "M9", ["FW-09 a"], ["FW-09 a.1:", "FW-09 a.2:", "FW-09 a.5:"], "killed", ""),
    ("NC-FW09-2", "C6", ["FW-09 b"], ["FW-09 b.1:", "FW-09 b.2:", "FW-09 b.5:"], "killed", ""),
    ("NC-FW09-3", "C6", ["FW-09 b2"], ["FW-09 b2.3:", "FW-09 b2.4:"], "killed", ""),
    ("NC-FW09-4", "MC244", ["FW-09 c"], ["FW-09 c.1:", "FW-09 c.2:"], "killed", ""),
    ("NC-FW09-5", "MC256", ["FW-09 c2"], ["FW-09 c2.1:", "FW-09 c2.2:"], "killed", ""),
    # W6-1: each slot mutant on the b3 scenario of the slot it skips (C6k4 also on b2, its V0.1 single-slot case)
    ("NC-FW09-6", "C6k0", ["FW-09 b3-256"], ["FW-09 b3-256.2:", "FW-09 b3-256.3:", "FW-09 b3-256.4:"], "killed", ""),
    ("NC-FW09-7", "C6k1", ["FW-09 b3-257"], ["FW-09 b3-257.2:", "FW-09 b3-257.3:", "FW-09 b3-257.4:"], "killed", ""),
    ("NC-FW09-8", "C6k2", ["FW-09 b3-258"], ["FW-09 b3-258.2:", "FW-09 b3-258.3:", "FW-09 b3-258.4:"], "killed", ""),
    ("NC-FW09-9", "C6k3", ["FW-09 b3-259"], ["FW-09 b3-259.2:", "FW-09 b3-259.3:", "FW-09 b3-259.4:"], "killed", ""),
    ("NC-FW09-10", "C6k4", ["FW-09 b2", "FW-09 b3-260"],
     ["FW-09 b2.2:", "FW-09 b2.3:", "FW-09 b2.4:", "FW-09 b3-260.2:", "FW-09 b3-260.3:", "FW-09 b3-260.4:"], "killed", ""),
    ("NC-FW09-11", "C6k5", ["FW-09 b3-261"], ["FW-09 b3-261.2:", "FW-09 b3-261.3:", "FW-09 b3-261.4:"], "killed", ""),
    ("NC-FW09-12", "C6s0", ["FW-09 b3-256"], ["FW-09 b3-256.2:", "FW-09 b3-256.3:", "FW-09 b3-256.4:"], "killed", ""),
    ("NC-FW09-13", "C6s5", ["FW-09 b3-261"], ["FW-09 b3-261.2:", "FW-09 b3-261.3:", "FW-09 b3-261.4:"], "killed", ""),
    # W6-1b: the per-slot verify regressions that survived the W6-1 review, each on every scenario that makes it observable
    ("NC-FW09-14", "C6bf", ["FW-09 b4-ct", "FW-09 b4-cb", "FW-09 b4-co"],
     ["FW-09 b4-ct.3:", "FW-09 b4-ct.4:", "FW-09 b4-cb.3:", "FW-09 b4-cb.4:", "FW-09 b4-co.3:", "FW-09 b4-co.4:"], "killed",
     ""),
    ("NC-FW09-15", "C6om", ["FW-09 b4-co"], ["FW-09 b4-co.3:", "FW-09 b4-co.4:"], "killed", ""),
    ("NC-FW09-16", "C6lt", ["FW-09 b4-ct", "FW-09 b4-cb", "FW-09 b4-co", "FW-09 b5-lo"],
     ["FW-09 b4-ct.3:", "FW-09 b4-ct.4:", "FW-09 b4-cb.3:", "FW-09 b4-cb.4:", "FW-09 b4-co.3:", "FW-09 b4-co.4:",
      "FW-09 b5-lo.2:", "FW-09 b5-lo.3:", "FW-09 b5-lo.4:"], "killed", ""),
    ("NC-FW09-17", "C6r1", ["FW-09 b6-ok", "FW-09 b6-x257"],
     ["FW-09 b6-ok.1:", "FW-09 b6-ok.2:", "FW-09 b6-x257.2:", "FW-09 b6-x257.3:", "FW-09 b6-x257.4:"], "killed", ""),
    ("NC-FW09-18", "C6r4", ["FW-09 b6-ok", "FW-09 b6-x260"],
     ["FW-09 b6-ok.1:", "FW-09 b6-ok.2:", "FW-09 b6-x260.2:", "FW-09 b6-x260.3:", "FW-09 b6-x260.4:"], "killed", ""),
    ("NC-FW09-19", "C6v34", ["FW-09 b6-ok", "FW-09 b6-x260"],
     ["FW-09 b6-ok.1:", "FW-09 b6-ok.2:", "FW-09 b6-x260.2:", "FW-09 b6-x260.3:", "FW-09 b6-x260.4:"], "killed", ""),
    # W6-1c: the containment-claim regressions that survived the W6-1b review, each on every scenario that makes it
    # observable (C6rn edits only the no-response handler, so b7-rber's error outcome does not see it)
    ("NC-FW09-20", "C6rh", ["FW-09 b7-rbnr", "FW-09 b7-rber", "FW-09 b7-cmnr"],
     ["FW-09 b7-rbnr.3:", "FW-09 b7-rbnr.4:", "FW-09 b7-rbnr.6:", "FW-09 b7-rber.3:", "FW-09 b7-rber.4:",
      "FW-09 b7-rber.6:", "FW-09 b7-cmnr.2:", "FW-09 b7-cmnr.3:", "FW-09 b7-cmnr.6:"], "killed", ""),
    ("NC-FW09-21", "C6rn", ["FW-09 b7-rbnr", "FW-09 b7-cmnr"],
     ["FW-09 b7-rbnr.3:", "FW-09 b7-rbnr.4:", "FW-09 b7-rbnr.6:", "FW-09 b7-cmnr.2:", "FW-09 b7-cmnr.3:",
      "FW-09 b7-cmnr.6:"], "killed", ""),
    ("NC-FW09-22", "C6rs", ["FW-09 b7-ab"], ["FW-09 b7-ab.3:", "FW-09 b7-ab.4:", "FW-09 b7-ab.6:"], "killed", ""),
    ("NC-FW09-23", "C6m0", ["FW-09 b7-af"], ["FW-09 b7-af.3:", "FW-09 b7-af.4:", "FW-09 b7-af.6:"], "killed", ""),
    ("NC-FW10-1", "M7", ["FW-10 A"], ["FW-10 A.2:", "FW-10 A.3:"], "killed", ""),
    ("NC-FW10-2", "M7", ["FW-10 B"], ["FW-10 B.2:"], "killed", ""),
    ("NC-FW10-3", "M7b", ["FW-10 B", "FW-10 C"], ["FW-10 B.2:", "FW-10 C.2:", "FW-10 C.3:"], "killed", ""),
    ("NC-FW10-4", "M7b", ["FW-10 A"], [], "survived(expected)",
     "the '!free_power_active_persisted' term still refuses: Free Power is active in A"),
    ("NC-FW10-5", "M7a", ["FW-10 A", "FW-10 B", "FW-10 C"], [], "survived(expected)",
     "equivalent mutant: snapshot_valid is set whenever active_persisted is (FW-10 M7a-equivalence)"),
    ("NC-FW11-1", "C3", ["FW-11 read_error"], ["FW-11 read_error (CLEAR).1:", "FW-11 read_error (RESTORE_REQUIRED).1:",
                                               "FW-11 read_error (RESTORE_REQUIRED).3:"], "killed", ""),
    ("NC-FW11-2", "C7", ["FW-11 wrong_size"], ["FW-11 wrong_size (CLEAR).1:", "FW-11 wrong_size (RESTORE_REQUIRED).1:",
                                               "FW-11 wrong_size (RESTORE_REQUIRED).3:"], "killed", ""),
    ("NC-FW11-3", "C7", ["FW-11 bad_magic"], ["FW-11 bad_magic (CLEAR).1:", "FW-11 bad_magic (RESTORE_REQUIRED).1:",
                                              "FW-11 bad_magic (RESTORE_REQUIRED).3:"], "killed", ""),
    ("NC-FW11-4", "C7ws", ["FW-11 wrong_size"], ["FW-11 wrong_size (CLEAR).1:", "FW-11 wrong_size (RESTORE_REQUIRED).1:"],
     "killed", ""),
    ("NC-FW11-5", "C7ws", ["FW-11 bad_magic"], [], "survived(expected)",
     "C7ws keeps the bad-magic term of FW:527, so the bad-magic record still locks"),
]
_MUT_FW: dict = {}


def mutant(mid: str):
    """The in-memory mutant `mid` (cached): every (old, new) pair must match exactly once, the text must change and parse;
    else a FAIL and None (MUTANT-INVALID)."""
    if mid in _MUT_FW:
        return _MUT_FW[mid]
    text = FW["_text"]
    for old, new in MUTANTS[mid][1]:
        n = text.count(old)
        if n != 1:
            check(f"negative-control mutant {mid}: its anchor is found exactly once in the firmware text", False,
                  f"count {n}: {old[:70]!r}")
            _MUT_FW[mid] = None
            return None
        text = text.replace(old, new)
    try:
        fw = L.load_fw(text) if text != FW["_text"] else None
    except Exception as exc:   # a mutant that does not parse is MUTANT-INVALID (a FAILURE, never a kill)
        check(f"negative-control mutant {mid} parses (MUTANT-INVALID otherwise)", False, f"{type(exc).__name__}: {exc}")
        fw = None
    _MUT_FW[mid] = fw
    return fw


def section_negative() -> None:
    print("[4] negative controls: each in-memory mutant must make its INTENDED named checks fail (killed), not crash; the "
          "expected survivors must leave every check holding")
    for nid, mid, keys, intended, expect, why in NC_TABLE:
        scope = " + ".join(keys)
        fw = mutant(mid)
        if fw is None:
            NC_RESULTS.append((nid, mid, scope, "invalid"))
            check(f"{nid} ({mid}) mutant is valid (applies exactly once and parses)", False, MUTANTS[mid][0])
            continue
        try:
            got: dict = {}
            for k in keys:
                got.update(EVALUATORS[k](fw))
        except Exception as exc:   # a crashing mutant run is MUTANT-INVALID: a negative-control FAILURE (never a kill)
            NC_RESULTS.append((nid, mid, scope, "invalid"))
            check(f"{nid} ({mid}) mutant runs {scope} without a harness exception (MUTANT-INVALID otherwise)", False,
                  f"{type(exc).__name__}: {exc}")
            continue
        failed = [n for n, (ok, _d) in got.items() if not ok]
        print(f"  info  {nid} {mid} on {scope}: failing checks {[n.split(':')[0] for n in failed]}")
        if expect == "killed":
            missing = [p for p in intended if not any(n.startswith(p) and not got[n][0] for n in got)]
            killed = bool(intended) and not missing
            NC_RESULTS.append((nid, mid, scope, "killed" if killed else "survived"))
            check(f"{nid} ({mid}: {MUTANTS[mid][0]}) killed on {scope}: {', '.join(p.rstrip(':') for p in intended)} "
                  f"fail", killed, f"intended checks still holding: {missing}; failing: {failed}")
        else:
            survived = not failed
            NC_RESULTS.append((nid, mid, scope, "survived(expected)" if survived else "killed(unexpected)"))
            check(f"{nid} ({mid}: {MUTANTS[mid][0]}) survives {scope} as expected: {why}", survived,
                  f"unexpectedly failing: {failed}")
    distinct = sorted({mid for _n, mid, *_ in NC_TABLE})
    print(f"  info  negative controls: {len(NC_TABLE)} control checks over {len(distinct)} distinct mutations "
          f"{distinct} (an identical mutation applied to several scenarios counts once)")
    bad = [(n, o) for n, _m, _s, o in NC_RESULTS if o not in ("killed", "survived(expected)")]
    fams = {n[:7] for n, _m, _s, o in NC_RESULTS if o == "killed"}
    check("every scenario (FW-09, FW-10, FW-11) has a killed negative control and no mutant survived unexpectedly or was "
          "invalid", fams == {"NC-FW09", "NC-FW10", "NC-FW11"} and not bad, f"{sorted(fams)} {bad}")


# =============================================================================================================================
# [5] corpus: every document exists, matches its draft, replays OK and FAILS against the mutant of the guard it pins
# =============================================================================================================================
MUTANT_TIER = "fw_guards_mutant"
# (corpus id, mutant id, key expectation (observe, args) that must fail against the mutant)
DISCRIMINATION = [
    ("FW-09-a", "M9", ("nvs_marker", {"dom": "dump"})), ("FW-09-b", "C6", ("nvs_marker", {"dom": "dump"})),
    ("FW-09-b2", "C6", ("globals", None)),
    ("FW-09-b3-256", "C6k0", ("globals", None)), ("FW-09-b3-256", "C6s0", ("globals", None)),
    ("FW-09-b3-257", "C6k1", ("globals", None)), ("FW-09-b3-258", "C6k2", ("globals", None)),
    ("FW-09-b3-259", "C6k3", ("globals", None)), ("FW-09-b3-260", "C6k4", ("globals", None)),
    ("FW-09-b3-261", "C6k5", ("globals", None)), ("FW-09-b3-261", "C6s5", ("globals", None)),
    ("FW-09-b4-ct", "C6bf", ("globals", None)), ("FW-09-b4-ct", "C6lt", ("globals", None)),
    ("FW-09-b4-cb", "C6bf", ("globals", None)), ("FW-09-b4-cb", "C6lt", ("globals", None)),
    ("FW-09-b4-co", "C6bf", ("globals", None)), ("FW-09-b4-co", "C6om", ("globals", None)),
    ("FW-09-b4-co", "C6lt", ("globals", None)), ("FW-09-b5-lo", "C6lt", ("globals", None)),
    ("FW-09-b6-ok", "C6r1", ("status_history", {"dom": "dump"})), ("FW-09-b6-ok", "C6r4", ("status_history", {"dom": "dump"})),
    ("FW-09-b6-ok", "C6v34", ("status_history", {"dom": "dump"})), ("FW-09-b6-x257", "C6r1", ("globals", None)),
    ("FW-09-b6-x260", "C6r4", ("globals", None)), ("FW-09-b6-x260", "C6v34", ("globals", None)),
    ("FW-09-b7-rbnr", "C6rh", ("globals", None)), ("FW-09-b7-rbnr", "C6rn", ("globals", None)),
    ("FW-09-b7-rber", "C6rh", ("globals", None)), ("FW-09-b7-cmnr", "C6rh", ("globals", None)),
    ("FW-09-b7-cmnr", "C6rn", ("globals", None)), ("FW-09-b7-ab", "C6rs", ("globals", None)),
    ("FW-09-b7-af", "C6m0", ("globals", None)),
    ("FW-09-c", "MC244", ("nvs_marker", {"dom": "dump"})),
    ("FW-09-c2", "MC256", ("nvs_marker", {"dom": "dump"})), ("FW-10-a", "M7", ("status", {"dom": "dump"})),
    ("FW-10-b", "M7b", ("status", {"dom": "dump"})), ("FW-10-c", "M7b", ("status", {"dom": "dump"})),
    ("FW-11-a", "C3", ("corrupt", {"dom": "fp"})), ("FW-11-b", "C3", ("corrupt", {"dom": "fp"})),
    ("FW-11-c", "C7", ("corrupt", {"dom": "fp"})), ("FW-11-d", "C7", ("corrupt", {"dom": "fp"})),
    ("FW-11-c", "C7ws", ("corrupt", {"dom": "fp"})), ("FW-11-d", "C7ws", ("corrupt", {"dom": "fp"})),
]


def replay_on(doc: dict, fw) -> list:
    """Replay a corpus document against the firmware `fw` (an in-memory mutant) with the _lab_trace engine, on a temporary
    tier that shares the firmware tier's ACTIONS / OBSERVERS (registered here, always removed in finally; never left in
    place); returns the failed expectations (the replay's own digest / drift verdict is irrelevant against a mutant). A
    document's bank world kwarg (W6-1b) is converted as the firmware replay factory converts it (_lab_fw.make_world)."""
    if T.registered(MUTANT_TIER)["factory"]:
        raise L.LabHarnessError(f"replay tier {MUTANT_TIER!r} is already registered")

    def factory(*, utc_start: int, seed: int, **kw):
        if "fw" in kw:
            raise L.LabHarnessError("replay_on: documents with an fw world kwarg are not supported here")
        if "bank" in kw:
            kw["bank"] = {L._reg(a): v for a, v in kw["bank"].items()}
        return L.FirmwareWorld(fw, utc_start=utc_start, seed=seed, **kw)

    try:
        T.register_tier(MUTANT_TIER, factory)
        T.register_actions(MUTANT_TIER, L.ACTIONS)
        T.register_observers(MUTANT_TIER, L.OBSERVERS)
        return T.replay(dict(doc, tier=MUTANT_TIER)).failed_expectations
    finally:
        T.unregister_tier(MUTANT_TIER)


def section_corpus() -> None:
    print("[5] corpus: every replay document exists, matches its draft, replays OK, and fails against its guard's mutant")
    cdir = HERE / "corpus"
    for d in CORPUS_DRAFTS:
        path = cdir / f"{d['id']}.json"
        if not path.is_file():
            check(f"corpus {d['id']}: file present", False, str(path.name))
            continue
        doc = T.load_doc(path)
        same = (all(doc.get(k) == v for k, v in d.items() if k not in ("source_anchors", "source_digests"))
                and [(a["path"], a["text"]) for a in doc["source_anchors"]] == [(a["path"], a["text"]) for a in d["source_anchors"]]
                and set(doc["source_digests"]) == set(d["source_digests"]) | {a["path"] for a in d["source_anchors"]}
                | set(T.tier_pins(d["tier"])))
        r = T.replay(doc)
        print(f"  info  corpus {d['id']}: ok={r.ok} drift={r.drift} digest_match={r.digest == doc['trace_digest']}")
        check(f"corpus {d['id']} ({doc['classification']}): matches the suite's draft and replays OK"
              + (" (source drift: expectations only)" if r.drift else " (trace digest identical)"),
              same and r.ok and not r.failed_expectations, f"same={same} {r.failed_expectations}")
    ids = sorted(d["id"] for d in CORPUS_DRAFTS)
    tabled = sorted(c for s in SCENARIOS.values() for c in s["corpus"])
    check("the scenario table and the corpus drafts name the same corpus documents", ids == tabled, f"{ids} {tabled}")
    for cid, mid, (obs, args) in DISCRIMINATION:
        path = cdir / f"{cid}.json"
        fw = mutant(mid)
        if fw is None or not path.is_file():
            check(f"corpus {cid} discriminates the {mid} mutant: mutant and document available", False, str(path.name))
            continue
        doc = T.load_doc(path)
        idx = [j for j, e in enumerate(doc["expect"]) if e["observe"] == obs and (args is None or e["args"] == args)]
        try:
            failed = replay_on(doc, fw)
        except Exception as exc:   # a crashing mutant replay is MUTANT-INVALID: a FAILURE of this check (never a kill)
            check(f"corpus {cid} replays against the {mid} mutant without a harness exception", False,
                  f"{type(exc).__name__}: {exc}")
            continue
        print(f"  info  corpus {cid} vs {mid}: failed expectations {[(f['observe'], str(f['observed'])[:60]) for f in failed]}")
        check(f"corpus {cid} discriminates the {mid} mutant ({MUTANTS[mid][0]}): its {obs} expectation fails there",
              len(idx) == 1 and idx[0] in [f["index"] for f in failed], f"{idx} {failed}")


# =============================================================================================================================
# [0] scenario table
# =============================================================================================================================
def section_table() -> None:
    print("[0] scenario table: classification vocabulary, exact source anchors (exactly once), corpus ids, bounds from source")
    for sid, s in SCENARIOS.items():
        kind, rid = T.parse_classification(s["classification"])
        ok_vocab = (s["grade"] in T.GRADES and s["confidence"] in T.CONFIDENCES and s["priority"] in T.PRIORITIES
                    and (rid is None or rid in T.KNOWN_RISKS))
        bad = []
        for path, text in s["anchors"]:
            n, line = T.anchor_count(path, text)
            if n != 1:
                bad.append((path, text[:60], n))
            else:
                print(f"  info  {sid} anchor {path}:{line}")
        check(f"{sid}: classification / grade / confidence / priority in the lab vocabulary and every source anchor found "
              f"exactly once ({len(s['anchors'])})", ok_vocab and not bad, str(bad))
    check("the bounds come from the firmware: Dump and Free Power watchdogs 15 s, telemetry 10 s, the comms backoff table "
          "of ecco_durable_snapshot.h 15/30/60/120/300 s, the containment floor 500 W (ecco_dump_controller_min_ceiling_w)",
          (WD_S, FP_WD_S, TEL_S, FLOOR_W) == (15, 15, 10, 500) and BACKOFF_S == [15, 30, 60, 120, 300],
          f"{(WD_S, FP_WD_S, TEL_S, FLOOR_W)} {BACKOFF_S}")
    check("every status literal this suite compares against occurs in the firmware text (no stale literal)",
          all(FW["_text"].count(x) >= 1 for x in LITERALS), str([x[:50] for x in LITERALS if FW["_text"].count(x) < 1]))
    check("every negative-control mutation's anchor occurs exactly once in the firmware text",
          all(FW["_text"].count(old) == 1 for _d, pairs in MUTANTS.values() for old, _new in pairs),
          str([m for m, (_d, pairs) in MUTANTS.items() if any(FW["_text"].count(o) != 1 for o, _n in pairs)]))


# =============================================================================================================================
# extended: a watchdog phase sweep over every FW-09 / FW-10 timeline
# =============================================================================================================================
def section_extended() -> None:
    t = time.perf_counter()
    print("[6] EXTENDED: every FW-09 / FW-10 timeline with five watchdog phase offsets (phase_ms 1-13 s)")
    bad = []
    for off in (1000, 4000, 7000, 10000, 13000):
        ph = {"dump_wd": off, "fp_wd": off}
        for key in ("a", "b", "b2", "c", "c2"):
            bad += [(off, n.split(":")[0], d[:80]) for n, (ok, d) in run_09(FW, key, ph).items() if not ok]
        for key in ("A", "B", "C"):
            bad += [(off, n.split(":")[0], d[:80]) for n, (ok, d) in run_10(FW, key, ph).items() if not ok]
    check("EXT FW-09 / FW-10: every check holds unchanged with the Dump and Free Power watchdogs' first run shifted by 1, "
          "4, 7, 10 and 13 s (40 runs): no verdict of this suite depends on the watchdog phase", not bad, str(bad[:6]))
    bad3, runs3 = [], 0
    for off in (1000, 4000, 7000, 10000, 13000):
        ph = {"dump_wd": off, "fp_wd": off}
        for key in B3_KEYS:
            runs3 += 1
            bad3 += [(off, n.split(":")[0], d[:80]) for n, (ok, d) in run_09(FW, key, ph).items() if not ok]
    check(f"EXT FW-09 b3: every per-slot check (b3-256 .. b3-261) holds unchanged with the Dump and Free Power watchdogs' "
          f"first run shifted by 1, 4, 7, 10 and 13 s ({runs3} runs): no b3 verdict depends on the watchdog phase",
          not bad3 and runs3 == 5 * len(B3_KEYS), str(bad3[:6]))
    bad4, runs4 = [], 0
    for off in (1000, 4000, 7000, 10000, 13000):
        ph = {"dump_wd": off, "fp_wd": off}
        for key in B456_KEYS:
            runs4 += 1
            bad4 += [(off, n.split(":")[0], d[:80]) for n, (ok, d) in run_09(FW, key, ph).items() if not ok]
    check(f"EXT FW-09 b4 / b5 / b6: every containment, below-lease and distinct-originals check ({', '.join(B456_KEYS)}) "
          f"holds unchanged with the Dump and Free Power watchdogs' first run shifted by 1, 4, 7, 10 and 13 s ({runs4} "
          f"runs): no verdict of these scenarios depends on the watchdog phase",
          not bad4 and runs4 == 5 * len(B456_KEYS), str(bad4[:6]))
    bad7, runs7 = [], 0
    for off in (1000, 4000, 7000, 10000, 13000):
        ph = {"dump_wd": off, "fp_wd": off}
        for key in B7_KEYS:
            runs7 += 1
            bad7 += [(off, n.split(":")[0], d[:80]) for n, (ok, d) in run_09(FW, key, ph).items() if not ok]
    check(f"EXT FW-09 b7: every failed-readback, two-attempt and all-FOREIGN containment-claim check ({', '.join(B7_KEYS)}; "
          f"the containment-claim helper included) holds unchanged with the Dump and Free Power watchdogs' first run "
          f"shifted by 1, 4, 7, 10 and 13 s ({runs7} runs): no verdict of these scenarios depends on the watchdog phase",
          not bad7 and runs7 == 5 * len(B7_KEYS), str(bad7[:6]))
    print(f"  info  EXT sweeps runtime_s {time.perf_counter() - t:.3f}")


# =============================================================================================================================
# run
# =============================================================================================================================
section_table()
section_09()
section_10()
section_11()
section_negative()
section_corpus()
if EXTENDED:
    section_extended()
for nid, mid, scope, outcome in NC_RESULTS:
    print(f"  info  negative control {nid} [{mid}] {outcome}: {scope}")
COUNTED = sorted(f for f in FINDINGS if f not in DUPLICATE_OF)
print(f"  info  findings: {len(FINDINGS)} reproduced, {len(COUNTED)} counted")
BLOCKED = [sid for sid, s in SCENARIOS.items() if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME = time.perf_counter() - T0
print(f"  info  finding-reproduces checks: {len(FINDING_CHECKS)} (not counted as passes)")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=FINDING_CHECKS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
