#!/usr/bin/env python3
"""FW-04 / FW-05 / FW-06 firmware durability scenarios on the real firmware through FirmwareWorld: a false ABSENT marker at
reboot during an ACTIVE lease (single key, whole-partition erase), power cuts at every durable / Modbus event of a START or
restore while the OTHER domain holds a durable RESTORE_REQUIRED marker (rebooted through the FULL on_boot), and NVS commit
false negatives / false positives at every other commit site, continued through runtime and reboots. Offline assurance lab
V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Scenarios (SCENARIOS table below; findings in FINDINGS; corpus in corpus/FW-0[456]-*.json, replayed in section [R]):
  FW-04 (P1) false ABSENT during an ACTIVE Dump / Free Power lease, the later START that snapshots the residue as ORIGINAL,
        the whole-partition erase variant, the READ_ERROR-then-ABSENT two-boot path, and the guards that do hold (data,
        journal, retry and tombstone loss).
  FW-05 (P1) power-cut sweeps: (A) Dump phantom -> Free Power START and Free Power restore, (B) Free Power phantom -> Dump
        START and Dump restore, (C) the N17 shape (Free Power restore while Dump holds RESTORE_REQUIRED with unreadable
        data); every cut reboots through the FULL on_boot and runs 120 s of real scheduler time.
  FW-06 (P2) every commit site of the firmware is enumerated from its text (47 commit_record sites in 28 component / tag
        groups at this baseline, printed by [FW-06]); every group is reached by the 15 flows (START, natural end, END
        button, reboot during the lease, Force, Accept, clear-only boots, controller, register 244; 40 distinct commit
        signatures; text sites inside one group are not distinguished one by one), with false_negative and
        false_positive at every reachable signature; plus the Free Power START commit-failure status cascade.

Quick mode (default) sweeps the state-changing cut points (commits and writes; a cut after a read leaves the same durable
state as the cut before it) and one injection per distinct commit-site signature; ECCO_LAB_EXTENDED=1 or --extended sweeps
every fw event with both watchdog orders, a nested second cut at every state-changing event of the recovery that
follows each resolving durable-event cut, every commit occurrence of every flow and the not_landed mode as well, and
prints the extended runtime.

Findings: each is reproduced by a 'finding-reproduces:<id>' check and printed as a FINDING line with its classification,
confidence, severity and relation (root / consequence row / variant / duplicate). LAB-SUMMARY 'finding' counts the
reproduced findings that are not duplicates of another suite's root cause; a duplicate is printed 'DUPLICATE of <owner
id>, not counted' and keeps its reproduction check (F-FW05-1 re-verifies F-FW01-1, owned by FW-01). Roots this suite
owns for the whole lab (other suites print their copies as duplicates of these): F-FW04-1 / F-FW04-2 / F-FW04-4
(F-PB01-3), F-FW05-2 (the lab's N17 owner: F-FW03-1, F-PB01-2), F-FW06-1 (F-HF07-3), F-FW06-3 (F-PB01-4).
Independent review verdicts applied: F-FW04-3 is a consequence row (diagnostics), F-FW05-1 a duplicate, F-FW05-2 diagnostics with
no firmware repair, F-FW06-2 / F-FW06-3 FINDING-NEW (the realistic boot state is the previous lease's stale CLEAR).
Registry reclassification (hardened core): F-FW05-1 is FINDING-KNOWN:PR41-GHOST (S4 section 2.10 blind spot 1, second
reference the firmware's on_boot PR41 comment); every whole-partition erase case (F-FW04-4, Dump and Free Power leases) is
FINDING-KNOWN:NVS-PARTITION-ERASE (S4 section 2.10 blind spot 3); the single-key false ABSENT stays PLATFORM-ABSENT. The core
checker still tags both injected boot-time losses PLATFORM-ABSENT; the suite's classification separates them.

Hardened checkers: INV-BOOT-MIRROR (a STORED RESTORE_REQUIRED / PENDING_CLEAR / MALFORMED marker must be mirrored in RAM
after the FULL on_boot) and the level-based INV-NO-SILENT-OVERRIDE (judged only at steady points, RAM-visible obligations
only) are in the default invariant set; the suite pins how they classify every FW-04 / FW-05 / FW-06 case (exact boot,
evaluation point, tags and ignored stored markers) and prints the table. A false ABSENT (the marker deleted) is never an
INV-BOOT-MIRROR violation (nothing stored to mirror) but stays a silent override; the contrast mutant NC-FW04-3 (the stored
marker kept but read as CLEAR) is both.

MODEL dependence: only the core's (_lab_fw module docstring): synthetic SITE, synchronous scripts (a START / restore takes
0 ms, so a power cut lands between two firmware events, never inside a Modbus frame or an NVS write), the per-instance NVS
commit wrapper (false_negative = stored + False, false_positive = nothing stored + True), the boot fault ('absent', tag) =
key deleted before on_boot, ('erase_all',) = NVS and every preference cleared, the ESPHome preference flush model, the
telemetry / config stand-ins. Nothing here decides what the firmware does.

NVS USED-KEY RULE (V0.1, brief B5; _lab_fw MODEL ASSUMPTIONS): an injected commit fault (not_landed / false_negative /
false_positive) and a per-key read_error / wrong_size boot fault need a key STORED EARLIER IN THE RUN (the core refuses one
on a never-stored key with a LabHarnessError). Every scenario here that injects one on a domain's keys therefore first runs
prelude(): a COMPLETED-LEASE PRELUDE for that domain (Free Power / Dump: a real 1-minute lease whose verified restore
commits the marker CLEAR; reg244: the owner's Apply then Restore), checked fail-loud before the injection. Consequences:
the FW-05 phantoms are made on a used domain (setup_a / setup_b), every FW-06 flow runs on a used domain, and the FW-04
repair premise, the FW-06 START-failure cascade / contrast and the Phase-B guard rows are taken on a used device (the
fresh-device honest marker failure is no longer injected); F-FW06-2 / F-FW06-3 now reproduce in the used-device form only
(the previous lease's stale CLEAR): their never-used (ABSENT) variant needs a false positive on a never-stored key, which
the rule refuses.
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
_PS_DIGEST_EXP = _PS_DIGEST + (
    "; in addition the document's expectations are timeline-bound: at some phases under the patch an expectation "
    "fails (or the replay meets a refused interleaving / passes an action instant)")
# V0.1 review (R3-3): the cause of corpus FW-06-a's expectation failure under the phase patch
_PS_PRELUDE_WRITES = (
    "; here the failing expectation is 'writes': since V0.1 it lists the used-key prelude's writes (the B5 "
    "completed-lease prelude) with their event sequence numbers and instants, which any other phase changes (it "
    "failed in every patched run measured; the directed checks held)")
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "corpus FW-04-a: replays ok (": _PS_DIGEST,
    "corpus FW-04-b: replays ok (": _PS_DIGEST,
    "corpus FW-04-c: replays ok (": _PS_DIGEST,
    "corpus FW-04-d: replays ok (": _PS_DIGEST,
    "corpus FW-04-e: replays ok (": _PS_DIGEST,
    "corpus FW-05-a: replays ok (": _PS_DIGEST,
    "corpus FW-05-b: replays ok (": _PS_DIGEST,
    "corpus FW-05-c: replays ok (": _PS_DIGEST,
    "corpus FW-05-d: replays ok (": _PS_DIGEST,
    "corpus FW-05-e: replays ok (": _PS_DIGEST_EXP,
    "corpus FW-06-a: replays ok (": _PS_DIGEST_EXP + _PS_PRELUDE_WRITES,
    "corpus FW-06-b: replays ok (": _PS_DIGEST,
    "corpus FW-06-c: replays ok (": _PS_DIGEST,
    "corpus FW-06-d: replays ok (": _PS_DIGEST,
    "corpus FW-06-e: replays ok (": _PS_DIGEST,
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (none: no construct here is unmodelled)


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


import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
import traceback  # noqa: E402
from collections import Counter  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402

U0 = C.parse_iso_utc("2026-10-21T10:50:00Z")      # a synthetic Wednesday, BST (no DST edge inside any run)
FW = L.load_fw()
INFO = L.fw_info(FW)
ORIG = dict(L.SITE["original"])
D = L.ds.Durable
RR, CLR = D.MARKER_RESTORE_REQUIRED, D.MARKER_CLEAR
TAGN = {v: k for k, v in L.TAGS.items()}
FWREL = L.FW_REL
S4 = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
HDR = "firmware/include/ecco_durable_snapshot.h"
FSH = "docs/FAILED_START_HEALTH.md"
CORPUS = HERE / "corpus"
FW_EV = ("fw.commit", "fw.load", "fw.write", "fw.read")
STATE_EV = ("fw.commit", "fw.write")
SUITE = "test_lab_fw_durability"
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

# =============================================================================================================================
# scenario catalogue (anchors: exact text, verified exactly once at run time; line numbers are printed as information)
# =============================================================================================================================
A_FP_ABSENT = (FWREL, "id(free_power_marker_state) = state;")
A_ABSENT_CLEAR = (FWREL, "uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;\n"
                         "              id(dump_marker_state) = state;")
A_PLATFORM = (FWREL, "export containment not armed - do NOT reboot: a reboot may make the record read as absent")
A_DATA_LOST = (FWREL, "RECOVERY BLOCKED - durable marker is RESTORE_REQUIRED but the snapshot data record is unreadable; "
                      "inverter writes locked")
A_S3 = (FWREL, "Free Power was ACTIVE at last shutdown - ending and restoring on this boot rather than resuming the lease")
A_DUMP_NORESUME = (FWREL, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");')
A_PR41 = (FWREL, "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261) - Free Power and Dump-to-Grid both hold ")
A_PR41_PC = (FWREL, "MARKER_RESTORE_REQUIRED (PENDING_CLEAR is deliberately excluded,")
A_PR41_GATE = (FWREL, "domain's admission gate before the next reboot.")
A_START_FAILED = (FWREL, "START FAILED - could not durably commit the recovery snapshot; nothing written")
A_ACTIVATION = (FWREL, "ACTIVATION WRITE FAILED - restoring saved snapshot")
A_END_IGNORED = (FWREL, 'publish_state("END IGNORED - no saved Free Power snapshot")')
A_PHASE_B = (FWREL, "if (data_committed && marker_committed) {\n                        id(free_power_snapshot_valid) = true;")
A_S4_VANISH = (S4, "- **Vanish rule**: a current ABSENT after any evidence that the key existed")
A_S4_ERASE = (S4, "3. A partition erase (E04 P10; ESPHome erases the partition when `nvs_open` fails, V2 (5)) makes every "
                  "marker ABSENT.")
A_S4_EXIT = (S4, "an NVS loss of the marker (ABSENT reads as CLEAR at boot;")
A_S4_FALSEPOS = (S4, "The commit result itself can be a false negative or a false positive")
A_S4_GHOST = (S4, "1. A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear) is invisible")
A_S4_N15 = (S4, "| N15 | P3 does not exist, so \"Fallback is the final writer\" is not enforced after a write |")
A_S4_N17 = (S4, "| **N17** | P1 restores (FP and Dump) carry no cross-domain terms.")
A_HDR_COMMIT = (HDR, "Returns true only if BOTH the queue step and the flash sync succeeded")
A_FSH = (FSH, "The failures-since-boot counters are **not** used: they also count failed restores, force-restores and "
              "lockouts.")
A_FP_PLATFORM = (FWREL, "an obligation cannot be ruled out; inverter writes locked - do NOT reboot: a reboot may make the "
                        "record read as absent")
A_LOAD_LIMIT = (FWREL, 'case 0: id(ecco_load_limit).publish_state("Allow Export"); break;')
A_DUMP_RETRY_FIRST = (FWREL, "Stop SOC restore. Committed FIRST - before the")
A_EXPORT_UNVERIFIED = (FWREL, "id(dump_export_unverified) = v244 == 0 && id(dump_snapshot_reg244) != 0;")
A_NO_D12_DUMP = (FWREL, "the Dump retry record is not retained at boot: its marker-lost evidence is unavailable")
A_S4_N17_ACCEPTED = (S4, "Accepted residual; FB-D may add `!other_corrupt` terms.")
A_SG01_ROUTE = ("registry/tests/test_sg01_journal_phase1_2.py", "the sibling activation gate's else-branch hands the")

SCENARIOS = [
    {"id": "FW-04", "priority": "P1", "classification": "FINDING-KNOWN:PLATFORM-ABSENT", "grade": "VERIFIED",
     "confidence": "high",
     "title": "NVS false ABSENT at reboot during an ACTIVE lease (Dump; Free Power analogue): single-key loss "
              "(PLATFORM-ABSENT) vs whole-partition erase (NVS-PARTITION-ERASE); the later START snapshots the residue as "
              "ORIGINAL",
     "invariant": "INV-NO-SILENT-OVERRIDE (also INV-BOOT-MIRROR, INV-NO-RESUME for the intact-NVS baseline, "
                  "INV-RESTORE-BOUND)",
     "ownership": "one domain (Dump or Free Power) holds an ACTIVE lease with a durable RESTORE_REQUIRED marker, data, "
                  "retry (and Free Power journal) records; no other obligation; the owner changes nothing; ORIGINAL is the "
                  "synthetic SITE",
     "anchors": [A_ABSENT_CLEAR, A_FP_ABSENT, A_PLATFORM, A_FP_PLATFORM, A_DATA_LOST, A_S3, A_DUMP_NORESUME, A_S4_VANISH,
                 A_S4_ERASE, A_S4_EXIT, A_LOAD_LIMIT, A_DUMP_RETRY_FIRST, A_EXPORT_UNVERIFIED, A_NO_D12_DUMP],
     "failure_outcome": "the lost marker reads CLEAR: the lease override (Dump: 244 = 0 Allow Export + 256-261 ceiling; "
                        "Free Power: 58 A grid charge, all slots 100 % / grid source, 256-261) stays live with no lockout, "
                        "no restore and no obligation, status or alert in HA (live register values are shown only "
                        "informationally), while the domain's data record (active_persisted = 1, true ORIGINAL) is still "
                        "stored and never consulted; a later START captures the residue as ORIGINAL and its verified "
                        "restore overwrites the last stored copy of the true ORIGINAL",
     "corpus": ["FW-04-a", "FW-04-b", "FW-04-c", "FW-04-d", "FW-04-e"],
     "findings": ["F-FW04-1", "F-FW04-2", "F-FW04-3", "F-FW04-4"]},
    {"id": "FW-05", "priority": "P1", "classification": "FINDING-KNOWN:N17", "grade": "VERIFIED", "confidence": "high",
     "title": "Power cut at every durable / Modbus event of a START and a restore while the OTHER domain holds a durable "
              "RESTORE_REQUIRED (phantom) marker, and the N17 shape; every cut reboots through the FULL on_boot",
     "invariant": "INV-NO-2ND-RESTORER, INV-NO-SILENT-OVERRIDE, INV-LOCKOUT-QUIET, INV-NO-RESUME, INV-RESTORE-BOUND, "
                  "INV-BOOT-MIRROR (after every cut); PENDING_CLEAR / RESTORE_REQUIRED mixes resolve",
     "ownership": "the other domain's obligation is a phantom (its Phase-B marker commit landed but returned false, so its "
                  "RAM mirror is clear and the START gate admits this domain) - the only way a START / restore can run "
                  "while the other domain's marker is durably RESTORE_REQUIRED (that precondition is the registered "
                  "PR41-GHOST, F-FW01-1, owned by FW-01, re-verified here as F-FW05-1 and not counted); variant C adds an "
                  "unreadable Dump data record at boot (Dump corrupt-locked); the scenario's own finding F-FW05-2 is the "
                  "lab's N17 owner (FW-03's F-FW03-1 and PB-01's F-PB01-2 are printed as its duplicates)",
     "anchors": [A_PR41, A_PR41_PC, A_PR41_GATE, A_S4_GHOST, A_S4_N15, A_S4_N17, A_S4_N17_ACCEPTED],
     "failure_outcome": "after a cut the FULL on_boot must either lock both domains (PR41, both markers RESTORE_REQUIRED) or "
                        "resolve (PENDING_CLEAR excluded from PR41, clear-only with no Modbus, the other domain restores); "
                        "a second restorer, a silent override, a write under a lockout or a resumed lease would be a "
                        "violation",
     "corpus": ["FW-05-a", "FW-05-b", "FW-05-c", "FW-05-d", "FW-05-e"],
     "findings": ["F-FW05-1", "F-FW05-2"]},
    {"id": "FW-06", "priority": "P2", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "title": "Commit false negatives / false positives at every other commit site (Free Power Phase C/D, Dump pending / "
              "clear, retry records, journal, tombstone, data, Force / Accept, clear-only boots, controller, register "
              "244), continued through runtime and reboots; the START commit-failure status cascade",
     "invariant": "all eight firmware invariants (incl. INV-BOOT-MIRROR) after every injection; INV-STATUS-TRUTH "
                  "(suite-local: a failed START is reported by its real cause and counted once)",
     "ownership": "one domain at a time on the synthetic SITE; the Phase-B marker false NEGATIVE at START is FW-01's "
                  "subject and is not injected here (its false POSITIVE is)",
     "anchors": [A_PHASE_B, A_START_FAILED, A_ACTIVATION, A_END_IGNORED, A_HDR_COMMIT, A_S4_FALSEPOS, A_FSH,
                 A_SG01_ROUTE],
     "failure_outcome": "a RAM / durable divergence that leaves an override live with no visible obligation, a write under a "
                        "lockout, a resumed lease or an unexplained overdue restore; for the cascade: a terminal status "
                        "that names the wrong cause and a double failure count; for a Phase-B marker false positive: a "
                        "lease that runs without a durable marker (stale CLEAR or ABSENT at the next boot)",
     "corpus": ["FW-06-a", "FW-06-b", "FW-06-c", "FW-06-d", "FW-06-e"],
     "findings": ["F-FW06-1", "F-FW06-2", "F-FW06-3"]},
]

CROSS_CHECK = ("on_boot only: when a lease marker loads LOAD_ABSENT and the same domain's current-tag data record (FP V4 / "
               "Dump V2) loads OK with active_persisted == 1 (only the post-activation re-commit writes 1), treat the "
               "domain as UNKNOWN with the existing READ_ERROR-marker lockout (snapshot_valid = true, metadata_corrupt = "
               "true, a 'marker lost' status; no commit, no Modbus at boot). Key it on active_persisted == 1, never on a "
               "bare 'data loads' or 'retry record exists': a START whose marker commit failed honestly leaves "
               "active_persisted = 0 and, for Dump, a retry record (committed before the marker, FW:18505) - both verified "
               "here. Limits: (a) the loss becomes alarmed, not contained - Dump containment stays unarmed as for a "
               "READ_ERROR marker (the N13 shape), so 244 = 0 stays until an operator acts; (b) the data record is never "
               "reset at lease end (verified), so it also locks an idle domain whose CLEAR marker was lost (fail-closed, "
               "consistent with the S4 vanish rule) and the lockout has no in-firmware exit (no '*_recovery_metadata_"
               "corrupt) = false' in the firmware: an availability cost; the exit must stay operator-reviewed, never "
               "automatic); (c) it cannot see a whole-partition erase (F-FW04-4) or a Phase-B false positive on a used "
               "device (stale CLEAR, F-FW06-2 / F-FW06-3)")
READ_BACK = ("after the Phase-B marker commit returns true, read the marker back with a read that cannot be served from "
             "ESPHome's pending-save queue, before *_snapshot_valid is set and before any override write; require "
             "MARKER_RESTORE_REQUIRED, otherwise take the existing commit-failure path ('START FAILED ... nothing "
             "written'). No write path added, no gate weakened; the read itself can trigger the IDF erase of a CRC-bad "
             "entry (S4 section 2.10), acceptable because START then aborts before any write")
FINDINGS = {
    "F-FW04-1": {"scenario": "FW-04", "classification": "FINDING-KNOWN:PLATFORM-ABSENT", "confidence": "high",
                 "severity": "safety (bounded): ECCO's own export trip, Stop SOC supervision and SG-02 path are lost "
                             "silently while 244 = 0 and the lease ceiling stay live; the inverter's own export limit "
                             "(245) and battery protection are untouched",
                 "relation": "root (documented platform limit; the direct-ABSENT end state is not documented as accepted)",
                 "title": "Dump marker lost (single key) at a reboot during an ACTIVE lease: 244 = 0 Allow Export and the "
                          "256-261 lease ceiling stay live and unsupervised, with no obligation, lockout or alert visible",
                 "mechanism": "on_boot Dump block: load_record_status(DUMP_TO_GRID_VALID_TAG) = LOAD_ABSENT -> have_marker "
                              "false -> state = MARKER_CLEAR -> dump_snapshot_valid = false; the data record (active_persisted "
                              "= 1, ORIGINAL 244 / 256-261) and the retry record are never read on this path; containment is "
                              "seeded NOT_APPLICABLE (needs snapshot_valid && corrupt); the watchdog (first gate "
                              "!dump_snapshot_valid), the export trip (needs dump_active_persisted) and the controller are "
                              "off, so nothing writes or supervises; the S4 record's D12 'marker lost' evidence is not "
                              "available for Dump (the firmware does not retain the Dump retry record at boot, FW:25209); "
                              "the live 244 is still published informationally on the load-limit sensor (FW:16641; source "
                              "reading, the lab's config stand-in does not publish it)",
                 "reachability": "trigger: boot absent of the held Dump marker (dump.valid) during an ACTIVE lease "
                                 "(route: ESP-IDF erasure of a corrupt entry, REPORTED); device reachability: "
                                 "PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN pending the ESP-IDF host NVS test. "
                                 "INFERRED: a CRC-bad marker chunk is erased by its read, so the FIRST boot reads "
                                 "READ_ERROR (the fail-closed UNKNOWN lockout, FW:913) and only a further boot reads ABSENT "
                                 "(the read-error-then-absent variant); that further reboot need not be the owner's "
                                 "(ESPHome's default 15 min no-client API reboot, safe mode, a power cut), so the 'do NOT "
                                 "reboot' advice cannot prevent it; an ABSENT on the very first boot needs another IDF "
                                 "self-heal path (an entry erased at page load, a missing chunk erasing the index, "
                                 "collateral page invalidation; S4 section 2.2); key-hash collision loss is ruled out "
                                 "(test_fallback_nvs_keyhash.py); frequency UNKNOWN, probably low",
                 "repair": CROSS_CHECK + ". Description only, not implemented.",
                 "corpus": "FW-04-a"},
    "F-FW04-2": {"scenario": "FW-04", "classification": "FINDING-KNOWN:PLATFORM-ABSENT", "confidence": "high",
                 "severity": "cost (grid import with the battery held at 100 %; 244 untouched, no export) plus "
                             "diagnostics (the status reads 'Inactive')",
                 "relation": "Free Power analogue of F-FW04-1 (same root); its whole-partition erase variant is reproduced "
                             "and classified under F-FW04-4 (NVS-PARTITION-ERASE)",
                 "title": "Free Power marker lost (single key) at a reboot during an ACTIVE lease: the grid-charge "
                          "override stays live with no lease end, no restore and no visible obligation",
                 "mechanism": "on_boot Free Power block: LOAD_ABSENT -> MARKER_CLEAR -> free_power_snapshot_valid = false, "
                              "so S3 never converts the active lease into a restore request and the FP watchdog (first "
                              "gate !free_power_snapshot_valid) never restores; the data, retry and START journal records "
                              "survive unused - and equal those of a cleanly completed lease except for the marker "
                              "(verified), so they prove NVS loss, not an outstanding obligation; the S4 record's planned "
                              "F11.h marker-lost check needs a durable retry operator_needed = 1, which an ACTIVE lease "
                              "does not hold",
                 "reachability": "trigger: boot absent of the held Free Power marker (fp.valid) during an ACTIVE lease "
                                 "(route: ESP-IDF erasure of a corrupt entry, REPORTED); device reachability: "
                                 "PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN pending the ESP-IDF host NVS test. "
                                 "INFERRED, as F-FW04-1 (Free Power UNKNOWN text FW:1183)",
                 "repair": "the F-FW04-1 cross-check as a fail-closed UNKNOWN lockout only, never an automatic restore "
                           "from the data record (it does not end the lease; it makes the stranded override visible and "
                           "blocks F-FW04-3's laundering START and the cross-domain Dump START); the erase variant keeps "
                           "nothing (NVS empty) and is F-FW04-4's scope. Description only.",
                 "corpus": "FW-04-b"},
    "F-FW04-3": {"scenario": "FW-04", "classification": "FINDING-KNOWN:PLATFORM-ABSENT", "confidence": "high",
                 "severity": "diagnostics (incremental): the live state after the second lease equals the state before "
                             "it (the residue's own severity stays with F-FW04-1 safety / F-FW04-2 cost); the added harm is "
                             "a false 'original inverter settings verified' text, the Dump restore clearing "
                             "dump_export_unverified over 244 = 0, and the overwrite of the last stored copy of the true "
                             "ORIGINAL",
                 "relation": "consequence row of F-FW04-1 / F-FW04-2 (not an independent root cause); the dual of N15 "
                             "(a lost marker adopts residue, where N15's ghost marker restores a stale ORIGINAL)",
                 "title": "A later START snapshots the residue as ORIGINAL; its verified restore reports 'original inverter "
                          "settings verified' and overwrites the last stored copy of the true ORIGINAL",
                 "mechanism": "after F-FW04-1/2 every START gate is open (RAM mirrors clear); start_*_override snapshots "
                              "the live residue as ORIGINAL (Dump data_v2: 244 = 0, 256-261 = 1000; FP: 230 = 58, 232 = 1, "
                              "268 = 100); at the lease end the Dump restore pre-read finds live == snapshot (zero restore "
                              "writes at the same power; a controller-moved ceiling is written back), sets "
                              "dump_export_unverified = false (FW:19845), verifies and commits CLEAR; the FP restore writes "
                              "the residue back over its own lease values",
                 "reachability": "trigger: boot absent of the held Dump marker (dump.valid), then a later owner START "
                                 "on the residue; device reachability: PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN "
                                 "pending the ESP-IDF host NVS test. "
                                 "INFERRED and conditional: given the precondition, any later same-domain START (owner "
                                 "press, or an owner-armed DGS1 / FPS1 run whose press gates read the RAM-mirror sensors "
                                 "that are off) reaches it with certainty; the precondition's frequency is UNKNOWN",
                 "repair": "the F-FW04-1 cross-check refuses this START in the single-key case (the domain stays locked); "
                           "not the erase case (F-FW04-4); no START-side residue heuristic as a gate (absence without a "
                           "witness is not evidence, S4 R3) - at most a warning. Description only.",
                 "corpus": "FW-04-c"},
    "F-FW04-4": {"scenario": "FW-04", "classification": "FINDING-KNOWN:NVS-PARTITION-ERASE", "confidence": "high",
                 "severity": "safety (secondary, bounded): the 244 = 0 / 256-261 residue is unsupervised from the erase "
                             "boot itself (same hazard as F-FW04-1, not caused by the Free Power START; export still capped "
                             "by the inverter's own 245); the Free Power capture only adds diagnostics (a false "
                             "'verified'); the Free Power lease analogue is cost (as F-FW04-2)",
                 "relation": "erase variant of F-FW04-1 / F-FW04-2 / F-FW04-3, registered on its own as NVS-PARTITION-ERASE "
                             "(S4 section 2.10 blind spot 3, S4:447): no firmware-local cross-check can close it; the core "
                             "checker tags it PLATFORM-ABSENT like every injected boot-time marker loss, the classification "
                             "is the suite's",
                 "title": "Whole-partition erase during a lease: during a Dump lease the Dump limits fall back to factory "
                          "(Dump START refused) but a Free Power START is admitted and captures the Dump's 256-261 residue "
                          "as ORIGINAL, 244 = 0 stays; during a Free Power lease the grid-charge override stays live",
                 "mechanism": "erase clears every marker, data record and preference: every domain reads CLEAR and "
                              "INV-NO-SILENT-OVERRIDE fires at the erase boot's settle point, before any START (no stored "
                              "marker, so INV-BOOT-MIRROR has nothing to judge); the Dump limits globals read back at "
                              "factory (maximum grid export NOT CONFIGURED - an indirect HA-visible symptom; Dump START "
                              "refused); Free Power START has no such dependency and snapshots the Dump's 256-261 residue; "
                              "244 is outside its register set and stays 0; a Free Power lease erased the same way keeps "
                              "its override (F-FW04-2's end state with nothing left in NVS)",
                 "reachability": "trigger: boot erase_all (ESPHome erase-and-reinit when nvs_open fails: path VERIFIED, "
                                 "esphome components/esp32/preferences.cpp:131-148; trigger INFERRED); device "
                                 "reachability: UNKNOWN pending the ESP-IDF host NVS test. The path is VERIFIED from "
                                 "the local ESPHome 2026.8.2 source (ESP32Preferences::open(): nvs_open fails -> "
                                 "nvs_flash_deinit, nvs_flash_erase, nvs_flash_init); the trigger, an nvs_open failure "
                                 "at a boot inside an ACTIVE Dump lease, is INFERRED and its frequency UNKNOWN; then a "
                                 "later Free Power START",
                 "repair": "no firmware-local cross-check closes it (the data and retry records are erased too). Smallest "
                           "first step, diagnostics only, no firmware gate change: an HA-side 'lease vanished across a "
                           "dongle reboot' alert (dump_active / snapshot_valid on before the reboot; afterwards no end "
                           "reason, or the Dump limits read NOT CONFIGURED). Longer term the S4 record's FB-D lease-marker "
                           "witness, which works only if 'provisioned' is a fact that survives the erase (e.g. a build-time "
                           "requirement: a freshly flashed device boots UNKNOWN until an attended provisioning), is a new "
                           "NVS commit path (not an inverter write) needing FB-D's relaxation of S4 section 5 rule (a), and "
                           "still leaves 244 = 0 (a Dump UNKNOWN lockout does not arm containment, N13). Description only.",
                 "corpus": "FW-04-d"},
    "F-FW05-1": {"scenario": "FW-05", "classification": "FINDING-KNOWN:PR41-GHOST", "confidence": "high",
                 "severity": "availability / cost (precondition, low-medium), as F-FW01-1: in this runtime nothing is left "
                             "wrong (the admitted lease's START and verified restore put back the true ORIGINAL; the "
                             "phantom domain wrote nothing); the harm needs a reboot inside the admitted lease (F-FW01-2)",
                 "relation": "DUPLICATE of F-FW01-1 (FW-01 owns it), re-verified as the FW-05 precondition; adds only the "
                             "restore-side writer; not counted in the summary finding count; registered as PR41-GHOST (S4 "
                             "section 2.10 blind spot 1; second reference the firmware's on_boot PR41 comment), which "
                             "replaces the approximate N15 mapping (N15's stale-ORIGINAL consequence does not occur here)",
                 "duplicate_of": "F-FW01-1",
                 "title": "Under a phantom marker the other domain's START and restore write 256-261 while the phantom's "
                          "durable RESTORE_REQUIRED is outstanding (same runtime); the latent phantom then self-heals at "
                          "the next boot, or stops at OPERATOR DECISION REQUIRED after an owner change",
                 "mechanism": "Phase-B marker commit lands but returns false -> RAM snapshot_valid stays false -> the other "
                              "domain's START gate (RAM mirror only) admits it -> its START and restore write 256-261; "
                              "documented by the firmware's own PR41 rationale and S4 blind spot 1 (PR41-GHOST); the "
                              "runtime ghost is never an INV-BOOT-MIRROR case (only boots are judged) and no silent override "
                              "(the bank ends at ORIGINAL); the next boot mirrors the stored RESTORE_REQUIRED by the phantom "
                              "domain's snapshot_valid (INV-BOOT-MIRROR holds); at that boot "
                              "(verified, both directions): bank unchanged -> the phantom's restore is a zero-write "
                              "verified no-op and commits CLEAR; owner changed 256 first -> OPERATOR DECISION REQUIRED with "
                              "zero writes (the restore drift guard fails closed), so N15's stale-ORIGINAL overwrite does "
                              "not occur here; a reboot inside the admitted lease -> PR41 dual lockout (F-FW01-2)",
                 "reachability": "trigger: nvs false_negative on a used Phase-B marker; device reachability: UNKNOWN "
                                 "pending the ESP-IDF host NVS test. "
                                 "INFERRED: a transient, single-commit false negative on the Phase-B marker itself - a "
                                 "same-key error after the write (ESP_ERR_NVS_REMOVE_FAILED semantics, REPORTED); the "
                                 "firmware comment's 'unrelated pending key' route cannot reach the marker commit (ESPHome "
                                 "2026.8.2 sync() clears its queue and the data commit's sync runs just before in the same "
                                 "lambda); a persistent fault makes the second START abort with nothing written; frequency "
                                 "UNKNOWN",
                 "repair": "F-FW01-1's scope: the two START scripts only - when the Phase-B marker commit returns false "
                           "after the data record committed, keep the RAM mirror fail-closed (snapshot_valid, "
                           "restore_requested, as the success branch sets them), so every existing START, manual and HA gate "
                           "sees the obligation with no gate edit and no new flag, and the domain's own verified restore "
                           "(a zero-write no-op when live equals the snapshot, verified here) commits CLEAR; PR41 / S4 stay "
                           "as the boot backstop. Description only; FW-01 owns the chain.",
                 "corpus": "FW-05-c"},
    "F-FW05-2": {"scenario": "FW-05", "classification": "FINDING-KNOWN:N17", "confidence": "high",
                 "severity": "diagnostics (low): an R1 ownership overlay; the write is the restoring domain's own verified "
                             "ORIGINAL and the bank ends at ORIGINAL in every variant; the other obligation is a phantom "
                             "that wrote nothing, or an UNKNOWN lockout",
                 "relation": "the lab's N17 owner, counted here once for the whole lab: F-FW03-1 (test_lab_fw_obligations: "
                             "the triple-obligation route, and FW-03-a, the same Dump phantom + Dump data READ_ERROR "
                             "construction as FW-05-e) and F-PB01-2 (test_lab_property: the UNKNOWN form) are printed there "
                             "as DUPLICATE of F-FW05-2; this suite adds the mirror (Dump over Free Power) and the UNKNOWN "
                             "form without a phantom; the S4 record's accepted residual N17 (registry class "
                             "ACCEPTED-RESIDUAL, as S4:169 'Accepted residual')",
                 "title": "With the other domain corrupt / UNKNOWN at boot (PR41 skipped), a trusted P1 restore writes "
                          "256-261 over that domain's unresolved obligation: Free Power over a corrupt-locked Dump phantom, "
                          "the mirror (Dump over Free Power), and the UNKNOWN form without a phantom",
                 "mechanism": "Dump RR + data READ_ERROR -> dump_recovery_metadata_corrupt; PR41 requires "
                              "!dump_recovery_metadata_corrupt (deliberate) and does not fire; the FP watchdog / wrapper "
                              "gate has no cross-domain term, so restore_free_power_snapshot_dispatch writes 232, 256-261, "
                              "268-279, 230 to its ORIGINAL and commits CLEAR (INV-NO-2ND-RESTORER tagged N17, "
                              "INV-LOCKOUT-QUIET); mirror: FP phantom + Dump lease + FP data READ_ERROR -> the Dump restore "
                              "writes 244 := 2 and 256-261 to ORIGINAL (tagged N17); UNKNOWN form: a used Dump (stored "
                              "CLEAR) whose marker reads READ_ERROR + an FP lease across the reboot -> only "
                              "INV-LOCKOUT-QUIET",
                 "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker plus a boot read_error on "
                                 "the stored Dump data record (the UNKNOWN form: a READ_ERROR marker); device "
                                 "reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                                 "INFERRED: rare for the N17-tagged forms (a phantom, a live lease and a data READ_ERROR at "
                                 "one boot); the INV-LOCKOUT-QUIET form needs only an FP lease across a reboot and a Dump "
                                 "marker READ_ERROR; benign write direction in all forms",
                 "repair": "none needed: keep N17 as the S4 record's accepted residual (optionally a diagnostics-only "
                           "status note). The S4 note's bare '!other_corrupt' terms are NOT safe (in-memory scratch "
                           "mutants): on the FP gate they leave the 58 A / all-slots-100 % override live and "
                           "RESTORE_REQUIRED (INV-RESTORE-BOUND); on the Dump gate they leave 244 = 0 and 256-261 = 1000 "
                           "with containment NOT_APPLICABLE (export uncontained). An R1 enforcement would go through the "
                           "boot lockout (latch the trusted domain like PR41, arm SG-02 for Dump) under an owner decision "
                           "that accepts the FP overrun - never a bare term on the Dump restore. Description only.",
                 "corpus": "FW-05-e"},
    "F-FW06-1": {"scenario": "FW-06", "classification": "FINDING-NEW", "confidence": "high",
                 "severity": "diagnostics (low)",
                 "relation": "canonical id of the firmware cascade; F-HF07-3 (test_lab_ha_phantom) reports its HA-side copy "
                             "and should cross-reference this id",
                 "title": "Free Power START durable-commit failure: 'START FAILED' is overwritten at once by 'ACTIVATION "
                          "WRITE FAILED - restoring saved snapshot' (no activation write was attempted), failures += 2, and "
                          "the data / marker cases end on 'END IGNORED - no saved Free Power snapshot'",
                 "mechanism": "start_free_power_override: any commit failure (data, marker, retry reset, B1 journal) sets "
                              "free_power_write_failed; the 'if free_power_write_failed' action publishes START FAILED and "
                              "counts a failure, then the separate sibling 'if !free_power_write_failed' action's else "
                              "branch counts again, publishes ACTIVATION WRITE FAILED and runs restore_free_power_snapshot "
                              "(END IGNORED without a RAM snapshot; a full restore cycle with one); the path is fully "
                              "synchronous; partial prior knowledge: test_sg01_journal_phase1_2.py [C] pins the restore "
                              "hand-off for the retry / journal sites as intended but asserts neither the overwritten text, "
                              "the double count nor the data / marker END IGNORED ending",
                 "reachability": "trigger: nvs not_landed / false_negative at a Free Power START commit site (data, "
                                 "marker, retry reset, journal) on a used key (corpus FW-06-a: not_landed on fp.data); "
                                 "device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                                 "INFERRED: any NVS commit failure at an FP START (flash write failure, full partition, "
                                 "the marker false negative of F-FW01-1); certain once a commit fails; impact (source "
                                 "reading, INFERRED): the status text and the cumulative failures counter (FSW1 uses "
                                 "attempts minus successes, unaffected); FPS1's last result reads 'FAILED TO START - END "
                                 "IGNORED ...' (right class, misleading reason); the energy actions card's attention "
                                 "pattern matches the word FAILED but not 'END IGNORED', so the data / marker cases show no "
                                 "attention there",
                 "repair": "start_free_power_override only, no write / gate / durable change: run the sibling activation "
                           "action only after a successful commit phase (move it inside the commit-success else branch) "
                           "and, in the commit-failure branch, run restore_free_power_snapshot only when "
                           "free_power_snapshot_valid is set; result: no ACTIVATION WRITE FAILED after a commit-phase "
                           "failure, failures counted once, final text START FAILED (data / marker) or the restore's own "
                           "result (retry / journal). It must keep the [C] route pinned by test_sg01_journal_phase1_2.py "
                           "(start then restore for B1-journal and retry-reset failures) and the genuine "
                           "activation-failure route (ACTIVATION WRITE FAILED final for B2-B4). Description only.",
                 "corpus": "FW-06-a"},
    "F-FW06-2": {"scenario": "FW-06", "classification": "FINDING-NEW", "confidence": "low",
                 "severity": "cost (grid import, battery held at 100 %; 244 untouched)",
                 "relation": "Free Power twin of F-FW06-3; on a never-used domain the boot state equals F-FW04-2's "
                             "(PLATFORM-ABSENT end state)",
                 "title": "Free Power Phase-B marker commit false POSITIVE: the lease runs on RAM only; a reboot during it "
                          "leaves the override live with no obligation - the marker reads the previous lease's stale CLEAR "
                          "(a used device: the only form injected since V0.1; on a never-used domain it would read "
                          "ABSENT, F-FW04-2's end state)",
                 "mechanism": "commit_record returns true without storing the marker; the Phase-B guard sets the RAM lease "
                              "from the return value alone (no read-back); the RAM obligation and the end-epoch restore work "
                              "while the runtime lasts (verified, natural flow); at a reboot during the lease on_boot loads "
                              "the previous lease's CLEAR marker (LOAD_OK) or ABSENT - both take the 'state = have_marker ? "
                              "marker.state : CLEAR' branch -> no obligation; the durable image (marker CLEAR, data "
                              "active_persisted 1 / restore_requested 0) is field for field the one a completed lease "
                              "leaves (verified), so no boot check on these records can tell them apart",
                 "reachability": "trigger: nvs false_positive on the used Free Power Phase-B marker (fp.valid), then a "
                                 "reboot during the lease; device reachability: UNKNOWN pending the ESP-IDF host NVS "
                                 "test. "
                                 "No route at the ESPHome layer: ESPHome 2026.8.2 sync() returns success only if this "
                                 "key's set_blob and the commit succeeded (REPORTED, checked against the ESPHome source); "
                                 "an ESP-IDF route (an INVALID page after a reported flash-op failure) was described by "
                                 "the V0 independent audit (medium confidence, not executed); trigger UNKNOWN pending the "
                                 "ESP-IDF host NVS test. The S4 record's statement (S4:671, Dump retry-lockout context) is "
                                 "generic; NVS loss after the commit (F-FW04-2) reaches the same boot state by another "
                                 "route; plus an ungated reboot during the lease (power cut, crash, default reboot "
                                 "timeouts)",
                 "repair": "start_free_power_override only: " + READ_BACK + ". The F-FW04-1 boot cross-check closes only "
                           "the never-used (ABSENT) variant. Description only.",
                 "corpus": "FW-06-b"},
    "F-FW06-3": {"scenario": "FW-06", "classification": "FINDING-NEW", "confidence": "low",
                 "severity": "safety (bounded, as F-FW04-1)",
                 "relation": "Dump twin of F-FW06-2; on a never-used domain the boot outcome equals F-FW04-1",
                 "title": "Dump Phase-B marker commit false POSITIVE: a reboot during the lease leaves 244 = 0 and the "
                          "ceiling live and unsupervised with no obligation - the marker reads the previous lease's stale "
                          "CLEAR (a used device; the never-used ABSENT form, F-FW04-1's end state, is no longer injected "
                          "since V0.1)",
                 "mechanism": "as F-FW06-2 for the Dump marker (dump_snapshot_valid is set from the commit result alone); "
                              "after the reboot: Inactive, 244 = 0, 256-261 = 1000, zero writes, containment "
                              "NOT_APPLICABLE; on a used device the durable image differs from a completed Dump lease only "
                              "in data restore_requested (0 here, 1 after a completed lease; untested as a discriminator)",
                 "reachability": "trigger: nvs false_positive on the used Dump Phase-B marker (dump.valid), then a "
                                 "reboot during the lease; device reachability: UNKNOWN pending the ESP-IDF host NVS "
                                 "test. "
                                 "As F-FW06-2: no route at the ESPHome layer; an ESP-IDF route (an INVALID page after a "
                                 "reported flash-op failure) was described by the V0 independent audit (medium "
                                 "confidence, not executed); trigger UNKNOWN pending the ESP-IDF host NVS test",
                 "repair": "start_dump_to_grid_override only: " + READ_BACK + " (before the first inverter write). "
                           "Description only.",
                 "corpus": "FW-06-c"},
}
CORPUS_IDS = [c for s in SCENARIOS for c in s["corpus"]]
REPORTED: list[str] = []
# the registry class each known risk must carry for this suite's classification to hold (a registry change forces review)
RISK_CLASS = {"PLATFORM-ABSENT": "PLATFORM-LIMIT", "NVS-PARTITION-ERASE": "PLATFORM-LIMIT", "PR41-GHOST": "DOCUMENTED-LIMIT",
              "N17": "ACCEPTED-RESIDUAL", "N15": "OPEN-GAP"}


def finding(fid: str, ok: bool, detail: str = "", tag: str = "") -> None:
    """The reproduction check of a finding (a future firmware fix makes it fail loudly and forces re-classification)."""
    name = f"finding-reproduces:{fid}" + (f":{tag}" if tag else "")
    check(name, ok, detail)
    if ok and fid not in REPORTED:
        REPORTED.append(fid)
        f = FINDINGS[fid]
        dup = f" DUPLICATE of {f['duplicate_of']}, not counted;" if f.get("duplicate_of") else ""
        print(T.finding_line(fid, f"[{f['classification']};{dup} confidence {f['confidence']}; {f['severity']}] "
                                  f"{f['title']}"))
        for k in ("relation", "mechanism", "reachability", "repair"):
            print(f"  info    {fid} {k}: {f[k]}")


def counted() -> list:
    """The findings this suite counts in LAB-SUMMARY: reproduced and not a duplicate of another suite's finding."""
    return [fid for fid in REPORTED if not FINDINGS[fid].get("duplicate_of")]


# =============================================================================================================================
# helpers
# =============================================================================================================================
def world(fw=None, warm: float = 60, **kw) -> L.FirmwareWorld:
    return L.FirmwareWorld(fw, utc_start=U0, warmup_s=warm, **kw)


def dump_env(w) -> None:
    w.telemetry(grid_w=L.SITE["dump_grid_w"], batt_w=L.SITE["dump_battery_w"])


def start_lease(w, dom: str, minutes: int) -> str:
    """A synthetic lease START of `dom` (Dump with its environment), returning the START status."""
    if dom == "dump":
        dump_env(w)
        return w.dump_start(power_w=1000, stop_soc=25, minutes=minutes)
    return w.fp_start(power_w=3000, minutes=minutes)


PRELUDE_S = 200     # a 1-minute lease has ended and its verified restore committed CLEAR well inside this
PRELUDE_DONE = {"fp": "RESTORED OK - original inverter settings verified",
                "dump": "RESTORED OK - original inverter settings verified",
                "r244": "RESTORED OK - register 244 confirmed back at "}


def prelude(w, dom: str) -> int:
    """The COMPLETED-LEASE PRELUDE (V0.1, brief B5 change 2; the NVS USED-KEY RULE of _lab_fw's MODEL ASSUMPTIONS): a real
    lease of `dom` before any injected NVS fault on that domain's keys, so every key the fault can hit was stored earlier
    in this run. fp / dump: a 1-minute lease START (start_lease) and PRELUDE_S of scheduler time - the lease ends and its
    verified restore commits the marker CLEAR (restore_free_power_snapshot_dispatch Phase C / D FW:11219 / 11226;
    restore_dump_to_grid_snapshot PENDING_CLEAR / CLEAR FW:20386 / 20393); r244: the owner's Apply then Restore
    (r244_apply / r244_restore; restore_reg244_snapshot Phase C / D FW:17792 / 17799). Fail loud (LabHarnessError, never a
    silent pass) unless the domain ends on its verified-restore status with the marker CLEAR, the bank at ORIGINAL, no
    invariant violation and EVERY NVS key of the domain stored earlier (L.TAGS '<dom>.*'). Returns the seq of the
    prelude's last event: the scenario's own writes / statuses are those after it."""
    if dom == "r244":
        r244_apply(w)
        w.run_for(5)
        r244_restore(w)
        w.run_for(5)
    elif dom in ("fp", "dump"):
        start_lease(w, dom, 1)
        w.run_for(PRELUDE_S)
    else:
        raise L.LabHarnessError(f"prelude: unknown domain {dom!r}")
    keys = [a for a in L.TAGS if a.startswith(dom + ".")]
    unstored = [a for a in keys if not w.nvs_stored_earlier(a)]
    st = w.status(dom)
    if (not st.startswith(PRELUDE_DONE[dom]) or w.nvs_marker(dom) != "CLEAR" or diff(w) or w.invariants() or unstored
            or w.corrupt(dom)):
        raise L.LabHarnessError(f"prelude({dom}): the lease did not complete (status {st!r}, marker {w.nvs_marker(dom)}, "
                                f"diff {diff(w)}, violations {ids(w.invariants())}, keys never stored {unstored})")
    return w.log[-1]["seq"]


def writes_since(w, seq: int) -> list:
    """(addr, vals) of every write after event `seq` (e.g. after the prelude)."""
    return [(x["addr"], x["vals"]) for x in w.writes() if x["seq"] > seq]


def diff(w) -> dict:
    """Owned registers that differ from the lab's ORIGINAL (foreign registers excluded)."""
    return {a: w.bank[a] for a in L.OWNED if a not in w.foreign and w.bank[a] != w.original[a]}


def ids(viol) -> list:
    return sorted({v["inv"] for v in viol})


def after(w, seq) -> list:
    return [e for e in w.log if e["seq"] > seq]


def writes_after(w, boot) -> list:
    return [(x["addr"], x["vals"]) for x in w.writes() if x["boot"] >= boot]


def rec(w, alias):
    r = w.sim.nvs.get(L.TAGS[alias])
    return None if r is None else L._rec_dict(r)


_NSO_WHERE = re.compile(r" \[([^\]]+)\]$")
_NSO_IGNORED = re.compile(r" \(stored markers the RAM ignores: (\{[^}]*\})\)")
_BM_HEAD = re.compile(r"^boot (\d+): the stored (\w+) marker is (\w+) but")
CHECKER_ROWS: list = []


def hardened(w, events=None, case: str | None = None) -> dict:
    """How the hardened core checkers classify a run (over w.log, or the given slice of it, with the world): INV-BOOT-MIRROR
    as [(boot, domain, stored marker)], INV-NO-SILENT-OVERRIDE as [(boot, evaluation point, tags, stored markers the RAM
    ignores or None)], the boots' stored markers {boot: {dom: marker}} and whether the world is silent now (quiet_state).
    A detail text the core no longer formats as parsed here raises (fail loud, never a silent pass). `case` records the
    row for the printed classification table."""
    ev = w.log if events is None else events
    bm = []
    for x in L.check_boot_mirror(ev):
        m = _BM_HEAD.match(x["detail"])
        if m is None or int(m.group(1)) != w.log[x["seq"]]["boot"]:
            raise L.LabHarnessError(f"INV-BOOT-MIRROR detail not in the expected form: {x['detail']!r}")
        bm.append((int(m.group(1)), m.group(2), m.group(3)))
    nso = []
    for x in L.check_no_silent_override(ev, world=w):
        m, ig = _NSO_WHERE.search(x["detail"]), _NSO_IGNORED.search(x["detail"])
        if m is None:
            raise L.LabHarnessError(f"INV-NO-SILENT-OVERRIDE detail has no evaluation-point suffix: {x['detail']!r}")
        nso.append((w.log[x["seq"]]["boot"], m.group(1), tuple(x["tags"]), ig.group(1) if ig else None))
    boots = {e["data"]["boot"]: dict(e["data"]["obl"]["nvs"]) for e in ev if e["kind"] == "fw.booted"}
    out = {"bm": bm, "nso": nso, "boots": boots, "silent": w.quiet_state()["silent"]}
    if case is not None:
        CHECKER_ROWS.append((case, out))
    return out


def booted(w, boot: int) -> dict:
    """The fw.booted record of `boot` (the state the FULL on_boot left; INV-BOOT-MIRROR's evaluation point)."""
    return next(e["data"]["obl"] for e in w.log if e["kind"] == "fw.booted" and e["data"]["boot"] == boot)


PA = ("PLATFORM-ABSENT",)
SETTLE, STEADY = "boot settle point", "steady fw.quiet"


def mutant(old: str, new: str):
    """An in-memory firmware mutant: exact-count (1) replace, through the core's load path; None when the anchor moved."""
    text = FW["_text"]
    if text.count(old) != 1:
        return None
    return L.load_fw(text.replace(old, new, 1))


def section(title: str, fn) -> None:
    """Run one scenario section; a harness exception is a FAIL of that section (never a pass), the suite continues."""
    print(title)
    try:
        fn()
    except Exception as exc:   # noqa: BLE001 - recorded as a FAIL with the traceback, never turned into a pass
        check(f"{title.split()[0]} ran without a harness exception", False,
              f"{type(exc).__name__}: {exc} | " + " / ".join(traceback.format_exc().strip().splitlines()[-3:]))


NC_RESULTS: list = []


def negative_control(nid: str, desc: str, inv: str, run) -> None:
    """Mutant must be valid (loads and runs) and must make the INTENDED invariant check report `inv`."""
    try:
        viol = run()
    except Exception as exc:   # noqa: BLE001 - MUTANT-INVALID is a negative-control FAILURE, recorded as such
        NC_RESULTS.append((nid, "invalid"))
        check(f"negative control {nid}: {desc} -> the mutant runs (MUTANT-INVALID otherwise)", False,
              f"{type(exc).__name__}: {exc}")
        return
    if viol is None:
        NC_RESULTS.append((nid, "invalid"))
        check(f"negative control {nid}: {desc} -> mutant anchor found exactly once", False, "anchor not unique / moved")
        return
    killed = inv in ids(viol)
    NC_RESULTS.append((nid, "killed" if killed else "survived"))
    check(f"negative control {nid}: {desc} -> {inv} reports it (mutant killed, no harness exception)", killed,
          f"violations {ids(viol)}")


# =============================================================================================================================
# [0] catalogue and anchors
# =============================================================================================================================
def sec_catalogue() -> None:
    for s in SCENARIOS:
        lines, bad = [], []
        for path, text in s["anchors"]:
            try:
                lines.append(f"{path.rsplit('/', 1)[-1]}:{T.anchor_line(path, text)}")
            except T.AnchorError as exc:
                bad.append(str(exc))
        print(f"  info  {s['id']} anchors at " + ", ".join(lines))
        check(f"{s['id']}: all {len(s['anchors'])} source anchors occur exactly once", not bad, "; ".join(bad))
        T.parse_classification(s["classification"])
    cls_ok = all(T.parse_classification(f["classification"]) for f in FINDINGS.values())
    check("every scenario / finding classification is in the lab vocabulary and every FINDING-KNOWN id is a registered "
          "known risk", cls_ok and all(f["classification"].split(":", 1)[1] in T.KNOWN_RISKS
                                       for f in FINDINGS.values() if f["classification"].startswith("FINDING-KNOWN:")))
    used = sorted({c.split(":", 1)[1] for c in [f["classification"] for f in FINDINGS.values()]
                   + [s["classification"] for s in SCENARIOS] if c.startswith("FINDING-KNOWN:")})
    st = T.known_risk_status()
    cls_of = {r: T.KNOWN_RISKS[r]["class"] for r in RISK_CLASS}
    print("  info  known risks used: " + ", ".join(f"{r} ({cls_of[r]}, {T.KNOWN_RISKS[r]['path'].rsplit('/', 1)[-1]}:"
                                                   f"{st[r]['line']})" for r in sorted(RISK_CLASS)))
    check(f"the known risks this suite classifies against ({', '.join(used)}) and compares with (N15) are each anchored "
          f"exactly once in their documents and carry the registry class this suite's classification assumes",
          used == sorted(set(RISK_CLASS) - {"N15"}) and all(st[r]["count"] == 1 and cls_of[r] == c
                                                             for r, c in RISK_CLASS.items()),
          f"used {used} status {({r: st[r] for r in RISK_CLASS})} classes {cls_of}")
    g, er = T.KNOWN_RISKS["PR41-GHOST"], T.KNOWN_RISKS["NVS-PARTITION-ERASE"]
    refs = T.KNOWN_RISK_REFS.get("PR41-GHOST", ())
    ref_n = [T.anchor_count(p, t)[0] for p, t in refs]
    check("PR41-GHOST is anchored on the S4 blind-spot-1 sentence this suite cites (A_S4_GHOST) and NVS-PARTITION-ERASE on "
          "the blind-spot-3 sentence (A_S4_ERASE); every PR41-GHOST secondary reference occurs exactly once and one is the "
          "firmware's on_boot PR41 dual-obligation comment",
          g["path"] == A_S4_GHOST[0] and g["text"] in A_S4_GHOST[1] and er["path"] == A_S4_ERASE[0]
          and er["text"] in A_S4_ERASE[1] and bool(refs) and ref_n == [1] * len(refs)
          and any(p == FWREL and "dual durable-obligation dead-end" in t for p, t in refs), f"refs {refs} counts {ref_n}")


# =============================================================================================================================
# [1] FW-04 false ABSENT during an ACTIVE lease
# =============================================================================================================================
def dump_lease(minutes=30, run=60):
    w = world()
    dump_env(w)
    s = w.dump_start(power_w=1000, stop_soc=25, minutes=minutes)
    w.run_for(run)
    return w, s


def fp_lease(minutes=30, run=60, power=3000):
    w = world()
    s = w.fp_start(power_w=power, minutes=minutes)
    w.run_for(run)
    return w, s


DUMP_RESIDUE = {244: 0, **{a: 1000 for a in range(256, 262)}}
FP_RESIDUE = {230: 58, 232: 1, **{a: 3000 for a in range(256, 262)}, **{a: 100 for a in range(268, 274)},
              **{a: 1 for a in range(275, 280)}}


def sec_fw04() -> None:
    # baseline: the same reboot with intact NVS ends the lease and restores (the intended invariant)
    w, s = dump_lease()
    w.reboot()
    w.run_for(120)
    check("FW-04 baseline: a reboot during an ACTIVE Dump lease with intact NVS ends it ('ESP RESTARTED DURING LEASE - "
          "ended, not resumed') and restores the ORIGINAL; every invariant holds",
          s.startswith("ACTIVE") and w.status("dump_end") == "ESP RESTARTED DURING LEASE - ended, not resumed"
          and w.status("dump").startswith("RESTORED OK") and not diff(w) and not w.invariants(), str(w.invariants()))
    f, s = fp_lease()
    f.reboot()
    f.run_for(120)
    check("FW-04 baseline: the Free Power analogue (S3: 'ACTIVE - reboot recovery pending' -> verified restore); every "
          "invariant holds", f.status_history("fp").count("ACTIVE - reboot recovery pending") == 1
          and f.status("fp").startswith("RESTORED OK") and not diff(f) and not f.invariants(), str(f.invariants()))
    hb = {"dump": (hardened(w, case="FW-04 baseline Dump (intact NVS)"), booted(w, 1)),
          "fp": (hardened(f, case="FW-04 baseline Free Power (intact NVS)"), booted(f, 1))}
    check("FW-04 hardened checkers, baseline: the reboot's STORED RESTORE_REQUIRED marker is mirrored by snapshot_valid "
          "after the FULL on_boot (INV-BOOT-MIRROR judged a non-trivial boot and holds); INV-NO-SILENT-OVERRIDE is clean "
          "at every steady point and the end state is not silent (both domains)",
          all(ob["nvs"][d] == "RESTORE_REQUIRED" and ob[d]["snap"] and h["bm"] == [] and h["nso"] == [] and not h["silent"]
              for d, (h, ob) in hb.items()), str({d: (h, ob["nvs"]) for d, (h, ob) in hb.items()}))

    # F-FW04-1: single-key false ABSENT of the Dump marker
    w, _ = dump_lease()
    keys = sorted(w.sim.nvs)
    w.reboot(nvs_fault=("absent", "dump.valid"))
    b1 = w.boot_no
    st, end, hv = w.status("dump"), w.status("dump_end"), w.ha_view()
    w.run_for(600)
    v = w.invariants()
    data = rec(w, "dump.data")
    finding("F-FW04-1", st == "Inactive" and end == "" and w.nvs_marker("dump") == "ABSENT" and not w.corrupt("dump")
            and not hv["dump_active"] and not hv["dump_snapshot_valid"] and writes_after(w, b1) == []
            and diff(w) == DUMP_RESIDUE and ids(v) == ["INV-NO-SILENT-OVERRIDE"]
            and all(x["tags"] == ["PLATFORM-ABSENT"] for x in v) and w.sim.g["dump_containment_state"] == 0
            and data is not None and data["active_persisted"] == 1 and data["reg244"] == ORIG[244]
            and [data[f"reg{a}"] for a in range(256, 262)] == [ORIG[a] for a in range(256, 262)]
            and rec(w, "dump.retry") is not None,
            f"status {st!r} end {end!r} diff {diff(w)} inv {ids(v)} data {data} keys {keys}")
    print("  info  F-FW04-1: after the lost marker the Dump data record still holds active_persisted=1 and the true "
          "ORIGINAL (244=2, 256-261=8000/8000/7000/8000/8000/5000); on_boot never reads it when the marker is ABSENT; "
          "40 Dump watchdog ticks wrote nothing; HA sees dump_active / dump_snapshot_valid off")
    h1 = hardened(w, case="F-FW04-1 Dump single-key false ABSENT")
    check("FW-04 hardened checkers, F-FW04-1: the single-key false ABSENT is NOT an INV-BOOT-MIRROR violation (the boot's "
          "stored Dump marker is ABSENT - deleted, nothing to mirror) but INV-NO-SILENT-OVERRIDE reports exactly one "
          "episode, at the boot settle point of boot 1 (the state after the FULL on_boot, not a transient inside it), "
          "tagged PLATFORM-ABSENT, with no stored marker the RAM ignores; the world is still silent at the end",
          h1["bm"] == [] and h1["boots"][b1]["dump"] == "ABSENT" and h1["nso"] == [(b1, SETTLE, PA, None)]
          and h1["silent"], str(h1))
    check("FW-04: INV-RESTORE-BOUND sees no due period after the false ABSENT (the obligation is invisible to the "
          "restore checker by construction: no RAM snapshot, no marker) - the silent-override checker is what catches it",
          not w.invariants(["INV-RESTORE-BOUND"]))

    # the registry text's own sequence: READ_ERROR boot (fail-closed UNKNOWN), then a further boot reads ABSENT
    r, _ = dump_lease()
    r.reboot(nvs_fault=("read_error", "dump.valid"))
    b1 = r.boot_no
    r.run_for(120)
    unk = r.status("dump")
    check("FW-04: a READ_ERROR marker boot is the fail-closed UNKNOWN lockout with the firmware's own advice ('do NOT "
          "reboot: a reboot may make the record read as absent'), containment NOT armed (state 8), zero writes - "
          "244 = 0 stays (documented residual N13 in the S4 record)",
          A_PLATFORM[1] in unk and r.corrupt("dump") and r.sim.g["dump_containment_state"] == 8
          and writes_after(r, b1) == [] and diff(r) == DUMP_RESIDUE, unk)
    hr = hardened(r, case="FW-04 Dump marker READ_ERROR boot (UNKNOWN lockout)")
    ob = booted(r, b1)
    check("FW-04 hardened checkers, the READ_ERROR boot: the stored RESTORE_REQUIRED marker is mirrored by the UNKNOWN "
          "lockout (snapshot_valid + metadata_corrupt; INV-BOOT-MIRROR holds) and the residue is visible, so "
          "INV-NO-SILENT-OVERRIDE is clean", hr["bm"] == [] and hr["nso"] == [] and ob["nvs"]["dump"] == "RESTORE_REQUIRED"
          and ob["dump"]["snap"] and ob["dump"]["corrupt"] and not hr["silent"], str((hr, ob["dump"])))
    r.reboot(nvs_fault=("absent", "dump.valid"))
    b2 = r.boot_no
    r.run_for(600)
    finding("F-FW04-1", r.status("dump") == "Inactive" and not r.corrupt("dump") and diff(r) == DUMP_RESIDUE
            and "INV-NO-SILENT-OVERRIDE" in ids(r.invariants()), f"{r.status('dump')} {diff(r)}",
            tag="read-error-then-absent")
    hr2 = hardened(r, case="F-FW04-1 read-error-then-absent (second boot)")
    check("FW-04 hardened checkers, read-error-then-absent: the further boot that reads ABSENT is again no INV-BOOT-MIRROR "
          "case; INV-NO-SILENT-OVERRIDE reports exactly one episode, at that boot's settle point (boot 2), tagged "
          "PLATFORM-ABSENT - nothing during the visible UNKNOWN boot",
          hr2["bm"] == [] and hr2["boots"][b2]["dump"] == "ABSENT" and hr2["nso"] == [(b2, SETTLE, PA, None)], str(hr2))

    # F-FW04-2: the Free Power analogue
    f, _ = fp_lease()
    f.reboot(nvs_fault=("absent", "fp.valid"))
    b1 = f.boot_no
    st = f.status("fp")
    f.run_for(600)
    v = f.invariants()
    fd = rec(f, "fp.data")
    finding("F-FW04-2", st == "Inactive" and f.nvs_marker("fp") == "ABSENT" and not f.corrupt("fp")
            and not f.ha_view()["fp_snapshot_valid"] and writes_after(f, b1) == [] and diff(f) == FP_RESIDUE
            and ids(v) == ["INV-NO-SILENT-OVERRIDE"] and all(x["tags"] == ["PLATFORM-ABSENT"] for x in v)
            and fd is not None and fd["active_persisted"] == 1 and fd["restore_requested"] == 0 and fd["reg230"] == ORIG[230]
            and rec(f, "fp.journal") is not None and rec(f, "fp.retry") is not None,
            f"status {st!r} diff {diff(f)} inv {ids(v)} data {fd}")
    hf = hardened(f, case="F-FW04-2 Free Power single-key false ABSENT")
    check("FW-04 hardened checkers, F-FW04-2: as F-FW04-1 - no INV-BOOT-MIRROR case (stored Free Power marker ABSENT), "
          "exactly one silent-override episode at boot 1's settle point, tagged PLATFORM-ABSENT, still silent at the end",
          hf["bm"] == [] and hf["boots"][b1]["fp"] == "ABSENT" and hf["nso"] == [(b1, SETTLE, PA, None)] and hf["silent"],
          str(hf))

    # F-FW04-3: the later START launders the residue (Dump after Dump; Free Power after Free Power)
    dump_env(w)
    eu0, seq_w = w.sim.g["dump_export_unverified"], w.log[-1]["seq"]
    s2 = w.dump_start(power_w=1000, stop_soc=25, minutes=10)
    d2 = rec(w, "dump.data")
    w.run_for(700)
    w2 = [(x["addr"], x["vals"]) for x in w.writes() if x["seq"] > seq_w]
    f.run_for(1)
    seq_f = f.log[-1]["seq"]
    s3 = f.fp_start(power_w=2000, minutes=10)
    f2 = rec(f, "fp.data")
    f.run_for(700)
    f2w = [(x["addr"], x["vals"]) for x in f.writes() if x["seq"] > seq_f]
    finding("F-FW04-3", s2.startswith("ACTIVE") and d2["reg244"] == 0 and d2["reg256"] == 1000
            and w.status("dump") == "RESTORED OK - original inverter settings verified" and w.nvs_marker("dump") == "CLEAR"
            and eu0 is True and w.sim.g["dump_export_unverified"] is False
            and w2 == [(256, [1000] * 6), (244, [0])]
            and diff(w) == DUMP_RESIDUE and "INV-NO-SILENT-OVERRIDE" in ids(w.invariants())
            and s3.startswith("ACTIVE") and f2["reg230"] == 58 and f2["reg232"] == 1 and f2["reg268"] == 100
            and f.status("fp") == "RESTORED OK - original inverter settings verified" and f.nvs_marker("fp") == "CLEAR"
            and f2w[-4:] == [(232, [1]), (256, [3000] * 6), (268, [100] * 6 + [1] * 6), (230, [58])]
            and diff(f) == FP_RESIDUE and "INV-NO-SILENT-OVERRIDE" in ids(f.invariants()),
            f"dump {s2[:40]} data {d2} eu {eu0}->{w.sim.g['dump_export_unverified']} writes {w2} -> {w.status('dump')} "
            f"diff {diff(w)} | fp {s3[:40]} -> {f.status('fp')} {f2w[-4:]} {diff(f)}")
    print("  info  F-FW04-3: the Dump lease's only writes are its START re-applying the residue (256-261 = 1000, 244 = 0); "
          "its restore pre-read finds live == snapshot, writes nothing, clears dump_export_unverified (True -> False) and "
          "reports 'verified'; the Free Power restore writes the residue back over its own lease values")
    h3 = {"dump": hardened(w, case="F-FW04-3 Dump laundering START + verified restore"),
          "fp": hardened(f, case="F-FW04-3 Free Power laundering START + verified restore")}
    check("FW-04 hardened checkers, F-FW04-3: two silent-override episodes in boot 1, both PLATFORM-ABSENT - the residue at "
          "the boot settle point, then again at the steady fw.quiet after the laundering lease's 'verified' "
          "restore (the lease in between made the residue RAM-visible, which ended the first episode); no INV-BOOT-MIRROR "
          "case (both domains)", all(h["bm"] == [] and h["nso"] == [(1, SETTLE, PA, None), (1, STEADY, PA, None)]
                                     and h["silent"] for h in h3.values()), str(h3))

    # F-FW04-4: whole-partition erase (NVS and every preference) during a Dump lease
    e, _ = dump_lease()
    e.reboot(nvs_fault=("erase_all",))
    be = e.boot_no
    erased = e.sim.nvs == {} and e.sim.pref_flushed.get("dump_max_export_w") == INFO.initial["dump_max_export_w"]
    e.run_for(60)
    lim = str(e.sim.ent("dump_limits_status").state)
    pre_start = [(x["inv"], x["tags"]) for x in e.invariants()]      # before any START: the erase boot itself is silent
    he0 = hardened(e, case="F-FW04-4 Dump lease, whole-partition erase (before any START)")
    dump_env(e)
    sd = e.dump_start(power_w=1000, stop_soc=25, minutes=10)
    sf = e.fp_start(power_w=3000, minutes=10)
    fe = rec(e, "fp.data")
    e.run_for(700)
    finding("F-FW04-4", erased and e.nvs_marker("dump") == "ABSENT" and "NOT CONFIGURED" in lim
            and sd == "REJECTED - maximum grid export not configured; set Dump to Grid Max Grid Export first"
            and sf.startswith("ACTIVE") and fe is not None and [fe[f"reg{a}"] for a in range(256, 262)] == [1000] * 6
            and fe["reg244_lease_context_plus1"] == 1 and e.status("fp").startswith("RESTORED OK")
            and pre_start == [("INV-NO-SILENT-OVERRIDE", ["PLATFORM-ABSENT"])]
            and diff(e) == DUMP_RESIDUE and "INV-NO-SILENT-OVERRIDE" in ids(e.invariants()),
            f"limits {lim!r} pre-start {pre_start} dump {sd!r} fp {sf[:40]} data {fe} end {e.status('fp')} diff {diff(e)}")
    he1 = hardened(e, case="F-FW04-4 Dump lease erase, then the Free Power capture")
    g, _ = fp_lease()
    g.reboot(nvs_fault=("erase_all",))
    bg = g.boot_no
    g.run_for(600)
    finding("F-FW04-4", g.status("fp") == "Inactive" and diff(g) == FP_RESIDUE and g.sim.nvs == {}
            and ids(g.invariants()) == ["INV-NO-SILENT-OVERRIDE"], f"{g.status('fp')} {diff(g)} {ids(g.invariants())}",
            tag="fp-lease")
    hg = hardened(g, case="F-FW04-4 Free Power lease, whole-partition erase")
    check("FW-04 hardened checkers, F-FW04-4 (whole-partition erase, classified NVS-PARTITION-ERASE): every stored marker is "
          "ABSENT at the erase boot, so INV-BOOT-MIRROR has nothing to judge; INV-NO-SILENT-OVERRIDE reports the erase "
          "boot's settle point (Dump and Free Power leases) and, after the Free Power capture of the Dump residue, a second "
          "episode at the steady fw.quiet after its 'verified' restore; the core tags every erase episode PLATFORM-ABSENT "
          "(its tag for any injected boot-time marker loss), the NVS-PARTITION-ERASE classification is the suite's",
          all(h["bm"] == [] and set(h["boots"][b].values()) == {"ABSENT"} and h["silent"]
              for h, b in ((he0, be), (he1, be), (hg, bg)))
          and he0["nso"] == [(be, SETTLE, PA, None)] and he1["nso"] == [(be, SETTLE, PA, None), (be, STEADY, PA, None)]
          and hg["nso"] == [(bg, SETTLE, PA, None)], str((he0, he1, hg)))

    # guards that DO hold: a lost data record is a fail-closed lockout; journal / retry / tombstone loss is harmless
    x, _ = dump_lease()
    x.reboot(nvs_fault=("absent", "dump.data"))
    bx = x.boot_no
    x.run_for(120)
    sf = x.fp_start(power_w=3000, minutes=5)
    check("FW-04 guard: a lost Dump DATA record under a present RESTORE_REQUIRED marker is the fail-closed lockout; SG-02 "
          "containment writes only 244 := 2; Free Power START refused; every invariant holds (obligation visible)",
          x.corrupt("dump") and writes_after(x, bx) == [(244, [2])] and sf.startswith("REJECTED")
          and not x.invariants(), f"{x.status('dump')[:60]} {writes_after(x, bx)} {sf[:50]} {ids(x.invariants())}")
    y, _ = fp_lease()
    y.reboot(nvs_fault=("absent", "fp.data"))
    by = y.boot_no
    y.run_for(120)
    dump_env(y)
    sd = y.dump_start(power_w=1000, stop_soc=25, minutes=5)
    check("FW-04 guard: a lost Free Power DATA record -> 'RECOVERY BLOCKED ... snapshot data cannot be trusted' lockout, "
          "zero writes, Dump START refused; every invariant holds", y.corrupt("fp") and writes_after(y, by) == []
          and sd == "REJECTED - Free Power override/recovery owns inverter settings" and not y.invariants(),
          f"{y.status('fp')[:60]} {sd}")
    hx = {"dump": (hardened(x, case="FW-04 guard: Dump DATA record lost"), booted(x, bx)),
          "fp": (hardened(y, case="FW-04 guard: Free Power DATA record lost"), booted(y, by))}
    check("FW-04 hardened checkers, lost DATA record: the stored RESTORE_REQUIRED marker is mirrored by the corrupt lockout "
          "(INV-BOOT-MIRROR holds) and the obligation is RAM-visible (INV-NO-SILENT-OVERRIDE clean) - the marker, not "
          "the data record, is the single silent point",
          all(h["bm"] == [] and h["nso"] == [] and ob["nvs"][d] == "RESTORE_REQUIRED" and ob[d]["corrupt"]
              for d, (h, ob) in hx.items()), str({d: (h, ob[d]) for d, (h, ob) in hx.items()}))
    ok_loss = []
    for make, alias in ((dump_lease, "dump.retry"), (dump_lease, "dump.data_v1"), (fp_lease, "fp.journal"),
                        (fp_lease, "fp.retry")):
        z, _ = make()
        z.reboot(nvs_fault=("absent", alias))
        z.run_for(120)
        dom = alias.split(".")[0]
        ok_loss.append((alias, z.status(dom).startswith("RESTORED OK") and not diff(z) and not z.invariants()))
    check("FW-04 guard: losing only the retry record, the Dump V1 tombstone or the Free Power START journal still ends "
          "and restores the lease (verified ORIGINAL, every invariant holds)", all(o for _a, o in ok_loss), str(ok_loss))

    # premises of the described boot cross-check (CROSS_CHECK): what the durable records look like without an obligation.
    # V0.1 (B5): the honest marker failure is injected after a completed-lease prelude (a not_landed commit on a
    # never-stored key is refused by the NVS USED-KEY RULE), so the premise is taken on a used device: the failed START's
    # commits are read from the log after the prelude - FP: data FW:9154 (active_persisted = 0, FW:9112), then the marker
    # FW:9159 (the retry reset FW:9190 runs only after both landed); Dump: retry reset FIRST FW:18514, V1 tombstone
    # FW:18538, data FW:18541 (active_persisted = 0, FW:18482), then the marker FW:18547. A not_landed commit stores
    # nothing, so the marker stays the prelude's CLEAR.
    prem, got_commits = {}, {}
    want_commits = {"fp": [("fp.data", True), ("fp.valid", False)],
                    "dump": [("dump.retry", True), ("dump.data_v1", True), ("dump.data", True), ("dump.valid", False)]}
    for d in ("fp", "dump"):
        q, c = world(), world()
        p = prelude(q, d)
        q.nvs_policy(f"{d}.valid", RR, mode="not_landed")
        start_lease(q, d, 30)
        start_lease(c, d, 5)
        c.run_for(400)
        qd, cd = rec(q, f"{d}.data"), rec(c, f"{d}.data")
        commits = [(TAGN[e["data"]["key"]], e["data"]["landed"]) for e in after(q, p) if e["kind"] == "fw.commit"]
        got_commits[d] = commits
        prem[d] = (q.nvs_marker(d), qd["active_persisted"], commits == want_commits[d], writes_since(q, p) == [],
                   c.nvs_marker(d), cd["active_persisted"], cd["restore_requested"])
    check("FW-04 repair premise: an honest Phase-B marker failure after a completed lease (used device) keeps the previous "
          "lease's CLEAR marker, resets the data record to active_persisted = 0 (the START's own data commit) and writes "
          "nothing (Dump commits its retry record first); a completed lease leaves active_persisted = 1 beside the CLEAR "
          "marker (the data record is never reset), so the cross-check keys on active_persisted == 1 and also locks an "
          "idle domain whose CLEAR marker was lost",
          prem["fp"] == ("CLEAR", 0, True, True, "CLEAR", 1, 0) and prem["dump"] == ("CLEAR", 0, True, True, "CLEAR",
                                                                                   1, 1), f"{prem} commits {got_commits}")

    # negative controls: the boot no-resume guards (S3 for Free Power, the Dump end-on-boot) are what the baseline needs
    def nc_s3():
        m = mutant("id(free_power_restore_requested) = true;\n                    ESP_LOGW(\"free_power\", \"Free Power was "
                   "ACTIVE at last shutdown", "ESP_LOGW(\"free_power\", \"Free Power was ACTIVE at last shutdown")
        if m is None:
            return None
        q = world(m)
        q.fp_start(power_w=3000, minutes=30)
        q.run_for(60)
        q.reboot()
        q.run_for(30)
        return q.invariants()

    def nc_dump():
        m = mutant("id(dump_restore_requested) = true;\n                    id(dump_last_end_reason)",
                   "id(dump_last_end_reason)")
        if m is None:
            return None
        q = world(m)
        dump_env(q)
        q.dump_start(power_w=1000, stop_soc=25, minutes=30)
        q.run_for(60)
        q.reboot()
        q.run_for(30)
        return q.invariants()
    negative_control("NC-FW04-1", "S3 mutant (boot no longer converts an ACTIVE Free Power lease into a restore request)",
                     "INV-NO-RESUME", nc_s3)
    negative_control("NC-FW04-2", "Dump mutant (boot no longer sets dump_restore_requested for an ACTIVE lease)",
                     "INV-NO-RESUME", nc_dump)

    # contrast mutant for the INV-BOOT-MIRROR / INV-NO-SILENT-OVERRIDE split: the stored Dump marker is KEPT but on_boot
    # reads it as CLEAR (the RAM ignores a stored RESTORE_REQUIRED) - what F-FW04-1's deleted marker is not
    nc_h: dict = {}

    def nc_mirror():
        m = mutant(A_ABSENT_CLEAR[1], "uint8_t state = (uint8_t) ecco_durable::MARKER_CLEAR;\n"
                                      "              id(dump_marker_state) = state;")
        if m is None:
            return None
        q = world(m)
        dump_env(q)
        q.dump_start(power_w=1000, stop_soc=25, minutes=30)
        q.run_for(60)
        q.reboot()
        q.run_for(120)
        nc_h.update(hardened(q, case="NC-FW04-3 mutant: stored Dump RESTORE_REQUIRED read as CLEAR at boot"),
                    marker=q.nvs_marker("dump"), diff=diff(q), boot=q.boot_no)
        return q.invariants()
    negative_control("NC-FW04-3", "Dump on_boot mutant (a stored marker is read as CLEAR: the RAM ignores a stored "
                     "RESTORE_REQUIRED during an ACTIVE lease)", "INV-BOOT-MIRROR", nc_mirror)
    check("FW-04 contrast: the kept-but-ignored stored marker (NC-FW04-3) is exactly one INV-BOOT-MIRROR violation (dump, "
          "RESTORE_REQUIRED, boot 1) plus one untagged silent override that names the ignored stored marker; the deleted "
          "marker of F-FW04-1 is no INV-BOOT-MIRROR case and only the PLATFORM-ABSENT-tagged silent override remains",
          nc_h.get("bm") == [(1, "dump", "RESTORE_REQUIRED")] and nc_h.get("marker") == "RESTORE_REQUIRED"
          and nc_h.get("nso") == [(1, SETTLE, (), "{'dump': 'RESTORE_REQUIRED'}")] and nc_h.get("diff") == DUMP_RESIDUE
          and h1["bm"] == [] and h1["nso"] == [(1, SETTLE, PA, None)], str(nc_h))


# =============================================================================================================================
# [2] FW-05 power-cut sweeps with the other domain's durable RESTORE_REQUIRED
# =============================================================================================================================
def setup_a(fw=None):
    """Dump phantom: the Dump Phase-B marker commit lands but returns false (RAM clear, NVS RESTORE_REQUIRED), on a USED
    Dump domain (V0.1, B5: a completed Dump lease first, so the marker key was stored earlier - the false negative's
    physical precondition)."""
    w = world(fw)
    prelude(w, "dump")
    dump_env(w)
    w.nvs_policy("dump.valid", RR, mode="false_negative")
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(30)
    return w


def setup_b(fw=None):
    """Free Power phantom (on a used Free Power domain: a completed Free Power lease first, V0.1 B5), then the Dump
    environment."""
    w = world(fw)
    prelude(w, "fp")
    w.nvs_policy("fp.valid", RR, mode="false_negative")
    w.fp_start(power_w=3000, minutes=30)
    w.run_for(30)
    dump_env(w)
    return w


def setup_c(fw=None):
    """N17 shape: Free Power lease + Dump phantom, reboot with the Dump data record unreadable (Dump corrupt, PR41 skips)."""
    w = setup_a(fw)
    w.fp_start(power_w=3000, minutes=30)
    w.run_for(60)
    w.reboot(nvs_fault=("read_error", "dump.data"))
    return w


SWEEPS = {   # name: (setup, pre-action, swept action, domain the action belongs to)
    "A-start": (setup_a, None, lambda w: w.fp_start(power_w=3000, minutes=30), "fp"),
    "A-restore": (setup_a, lambda w: (w.fp_start(power_w=3000, minutes=30), w.run_for(60)), lambda w: w.fp_end(), "fp"),
    "B-start": (setup_b, None, lambda w: w.dump_start(power_w=1000, stop_soc=25, minutes=30), "dump"),
    "B-restore": (setup_b, lambda w: (w.dump_start(power_w=1000, stop_soc=25, minutes=30), w.run_for(60)),
                  lambda w: w.dump_end(), "dump"),
    "C-restore": (setup_c, None, lambda w: w.run_for(20), "fp"),
}


def sweep_events(name: str, fw=None) -> tuple:
    """The fw events of the swept action in an uncut run (the cut points), and that uncut world."""
    setup, pre, act, _dom = SWEEPS[name]
    w = setup(fw)
    if pre:
        pre(w)
    n = len(w.log)
    act(w)
    evs = [e for e in w.log[n:] if e["kind"] in FW_EV]
    return evs, w


def classify_end(w) -> str:
    c = (w.corrupt("fp"), w.corrupt("dump"))
    opn = bool(w.sim.g["free_power_operator_needed"] or w.sim.g["dump_operator_needed"])
    if all(c):
        return "DUAL_LOCKOUT"
    if any(c):
        return "LOCKOUT"
    if opn:
        return "OPERATOR_NEEDED"
    if all(w.nvs_marker(d) in ("CLEAR", "ABSENT") for d in ("fp", "dump")) and not diff(w):
        return "RESOLVED"
    return "OTHER"


def cut_run(name: str, k: int, *, fw=None, wd_order=("fp", "dump"), nested: int | None = None) -> dict:
    """Run the sweep's scenario with a power cut right after the k-th fw event of the swept action, FULL on_boot from the
    capture, 120 s of scheduler time (optionally a second cut at the nested-th fw event of that recovery)."""
    setup, pre, act, dom = SWEEPS[name]
    w = setup(fw)
    if pre:
        pre(w)
    w.arm_power_cut(lambda e: True, nth=k + 1)
    act(w)
    cuts = [e for e in w.log if e["kind"] == "cut.fired"]
    if len(cuts) != 1:
        raise L.LabHarnessError(f"{name} cut {k}: {len(cuts)} cuts fired (want exactly 1)")
    cut = cuts[0]
    booted = next(e for e in after(w, cut["seq"]) if e["kind"] == "fw.booted")
    if nested is not None:
        w.arm_power_cut(lambda e: True, nth=nested + 1)
    n_rec = len(w.log)
    w.run_for(120, wd_order=wd_order)
    last_cut = [e for e in w.log if e["kind"] == "cut.fired"][-1]
    if nested is not None and last_cut["seq"] != cut["seq"]:
        w.run_for(120, wd_order=wd_order)
    post = after(w, cut["seq"])
    return {"w": w, "event": w.log[cut["data"]["seq"]], "boot_nvs": booted["data"]["obl"]["nvs"],
            "post": L.check_invariants(post, world=w), "cls": classify_end(w), "dom": dom,
            "silent": w.quiet_state()["silent"],
            "post_writes": [(x["addr"], x["vals"], x["dom"]) for x in w.writes() if x["seq"] > cut["seq"]],
            "recovery_events": [e for e in w.log[n_rec:] if e["kind"] in FW_EV] if nested is None else None,
            "nested_fired": nested is not None and last_cut["seq"] != cut["seq"]}


def label(e) -> str:
    d = e["data"]
    what = TAGN.get(d.get("key"), d.get("key")) if e["kind"] == "fw.commit" else d.get("addr")
    st = (d.get("rec") or {}).get("state")
    return f"{e['kind'][3:]} {what}" + (f" state {st}" if st is not None else "")


SWEEP_TOTAL = Counter()
STORED_JUDGED = set(L.BOOT_MIRROR_RULE)      # the stored marker states INV-BOOT-MIRROR has a rule for


def sec_fw05() -> None:
    other = {"fp": "dump", "dump": "fp"}
    for name in SWEEPS:
        evs, nominal = sweep_events(name)
        points = list(range(len(evs))) if EXTENDED else [i for i, e in enumerate(evs) if e["kind"] in STATE_EV]
        orders = (("fp", "dump"), ("dump", "fp")) if EXTENDED else (("fp", "dump"),)
        res = {(k, o): cut_run(name, k, wd_order=o) for k in points for o in orders}
        SWEEP_TOTAL["cut"] += len(res)
        dom = SWEEPS[name][3]
        bad_post = [(k, label(evs[k]), ids(r["post"])) for (k, _o), r in res.items() if r["post"]]
        hist = Counter(r["cls"] for r in res.values())
        print(f"  info  {name}: {len(evs)} fw events in the swept action; {len(points)} cut point(s) x {len(orders)} "
              f"watchdog order(s) rebooted through the FULL on_boot; outcome classes {dict(sorted(hist.items()))}")
        check(f"FW-05 {name}: no invariant violation after the reboot at any of {len(res)} cut run(s) "
              f"(INV-NO-2ND-RESTORER, INV-NO-SILENT-OVERRIDE, INV-LOCKOUT-QUIET, INV-NO-RESUME, INV-RESTORE-BOUND, "
              f"INV-BOOT-MIRROR, ...)", not bad_post, str(bad_post[:4]))
        SWEEP_TOTAL["bm_judged"] += sum(1 for r in res.values() if set(r["boot_nvs"].values()) & STORED_JUDGED)
        SWEEP_TOTAL["bm_viol"] += sum(1 for r in res.values() for x in r["post"] if x["inv"] == "INV-BOOT-MIRROR")
        SWEEP_TOTAL["nso_viol"] += sum(1 for r in res.values() for x in r["post"] if x["inv"] == "INV-NO-SILENT-OVERRIDE")
        SWEEP_TOTAL["silent_end"] += sum(1 for r in res.values() if r["silent"])
        dual = [(k, r) for (k, _o), r in res.items() if r["boot_nvs"]["fp"] == r["boot_nvs"]["dump"] == "RESTORE_REQUIRED"]
        dual_bad = [(k, label(evs[k]), r["cls"], r["post_writes"]) for k, r in dual
                    if r["cls"] != "DUAL_LOCKOUT" or any(wr[:2] != (244, [2]) for wr in r["post_writes"])]
        check(f"FW-05 {name}: every cut whose capture holds BOTH markers RESTORE_REQUIRED ({len(dual)}) boots into the PR41 "
              f"dual lockout; the only post-cut write is SG-02's literal 244 := 2", bool(dual) and not dual_bad,
              str(dual_bad[:3]))
        mix = [(k, r) for (k, _o), r in res.items() if sorted(r["boot_nvs"][d] for d in ("fp", "dump"))
               == ["PENDING_CLEAR", "RESTORE_REQUIRED"]]
        if name.endswith("restore"):
            pcd = {k: next(d for d in ("fp", "dump") if r["boot_nvs"][d] == "PENDING_CLEAR") for k, r in mix}
            mix_bad = [(k, label(evs[k]), r["cls"], r["post_writes"]) for k, r in mix
                       if r["cls"] != "RESOLVED" or any(wr[2] == pcd[k] for wr in r["post_writes"])
                       or not r["w"].status(pcd[k]).startswith(("RECOVERY RESOLVED OK", "Inactive"))]
            check(f"FW-05 {name}: every PENDING_CLEAR / RESTORE_REQUIRED mix ({len(mix)}) resolves - PR41 excludes "
                  f"PENDING_CLEAR, the PENDING_CLEAR domain clears with ZERO Modbus writes, the other domain restores; "
                  f"both markers CLEAR, bank ORIGINAL", bool(mix) and not mix_bad, str(mix_bad[:3]))
        single = [(k, r) for (k, _o), r in res.items() if (r["boot_nvs"][dom], r["boot_nvs"][other[dom]])
                  in (("ABSENT", "RESTORE_REQUIRED"), ("CLEAR", "RESTORE_REQUIRED"))]
        single_bad = [(k, label(evs[k]), r["cls"]) for k, r in single if r["cls"] not in ("RESOLVED", "LOCKOUT")]
        check(f"FW-05 {name}: every cut that leaves only the other domain's marker RESTORE_REQUIRED ({len(single)}) is "
              f"resolved by that domain's own restore (or held by its own lockout); never a silent state",
              not single_bad, str(single_bad[:3]))
        if EXTENDED:
            eq = [(k, label(evs[k])) for k in points if evs[k]["kind"] not in STATE_EV
                  for p in [max([i for i in points if i < k and evs[i]["kind"] in STATE_EV], default=None)]
                  if p is not None and res[(k, ("fp", "dump"))]["cls"] != res[(p, ("fp", "dump"))]["cls"]]
            check(f"FW-05 {name} (extended): a cut after a read reproduces the outcome of the cut after the preceding "
                  f"state-changing event (the quick sweep's equivalence assumption)", not eq, str(eq[:3]))
            ordd = [k for k in points if res[(k, ("fp", "dump"))]["cls"] != res[(k, ("dump", "fp"))]["cls"]]
            check(f"FW-05 {name} (extended): the outcome class does not depend on the same-tick watchdog order "
                  f"(fp-first vs dump-first)", not ordd, str(ordd[:5]))
            durable = [k for k in points if evs[k]["kind"] == "fw.commit"]
            nested_bad, n_nested = [], 0
            for k in durable:
                base = res[(k, ("fp", "dump"))]
                if base["cls"] != "RESOLVED":
                    continue
                for j, e2 in enumerate(base["recovery_events"]):
                    if e2["kind"] not in STATE_EV:
                        continue
                    r2 = cut_run(name, k, nested=j)
                    n_nested += 1
                    if not r2["nested_fired"] or r2["post"] or r2["cls"] not in ("RESOLVED", "LOCKOUT",
                                                                                 "OPERATOR_NEEDED"):
                        nested_bad.append((k, j, label(e2), r2["nested_fired"], ids(r2["post"]), r2["cls"]))
            SWEEP_TOTAL["nested"] += n_nested
            check(f"FW-05 {name} (extended): a second power cut at every state-changing event of the recovery after each "
                  f"resolving durable-event cut ({n_nested} nested runs) leaves no invariant violation and no silent state",
                  not nested_bad, str(nested_bad[:3]))
        del nominal, res
    check(f"FW-05 hardened checkers: INV-BOOT-MIRROR judged every cut boot ({SWEEP_TOTAL['bm_judged']} of "
          f"{SWEEP_TOTAL['cut']} held a stored RESTORE_REQUIRED / PENDING_CLEAR marker: PR41 dual lockouts, PENDING_CLEAR "
          f"mixes, the other domain's own restore) and found 0 violations; the level-based INV-NO-SILENT-OVERRIDE found 0 "
          f"at every steady point after every cut, the end-of-log quiet state included (no cut run ends silent)",
          SWEEP_TOTAL["bm_judged"] > 0 and SWEEP_TOTAL["bm_viol"] == 0 and SWEEP_TOTAL["nso_viol"] == 0
          and SWEEP_TOTAL["silent_end"] == 0, str(dict(SWEEP_TOTAL)))
    # F-FW05-1: the uncut runs - the phantom-admitted domain writes 256-261 while the phantom's RR is durable
    rows, ghost = {}, {}
    for nm, setup, lease, end in (("A", setup_a, lambda w: w.fp_start(power_w=3000, minutes=30), lambda w: w.fp_end()),
                                  ("B", setup_b, lambda w: w.dump_start(power_w=1000, stop_soc=25, minutes=30),
                                   lambda w: w.dump_end())):
        w = setup()
        lease(w)
        w.run_for(60)
        end(w)
        w.run_for(60)
        v = w.invariants()
        holder = "dump" if nm == "A" else "fp"
        writers = sorted({x["detail"].split("(", 1)[1].split(")", 1)[0] for x in v if x["inv"] == "INV-NO-2ND-RESTORER"})
        rows[nm] = (ids(v), writers, all(x["tags"] == [] for x in v), w.nvs_marker(holder),
                    bool(w.obligations()[holder]["snap"]), diff(w))
        q = w.quiet_state()
        ghost[nm] = (hardened(w, case=f"F-FW05-1 {nm}: PR41-GHOST in its own runtime ({holder} phantom)"), q["nvs"][holder],
                     q["visible"])
    finding("F-FW05-1", rows["A"][:4] == (["INV-NO-2ND-RESTORER"], ["restore_free_power_snapshot_dispatch",
                                                                       "start_free_power_override"], True,
                                          "RESTORE_REQUIRED")
            and rows["B"][:4] == (["INV-NO-2ND-RESTORER"], ["restore_dump_to_grid_snapshot",
                                                             "start_dump_to_grid_override"], True, "RESTORE_REQUIRED")
            and not rows["A"][4] and not rows["B"][4] and rows["A"][5] == {} and rows["B"][5] == {}, str(rows))
    # the latent phantom at the next boot (both directions): unchanged bank -> zero-write verified no-op and CLEAR; an
    # owner change of 256 first -> OPERATOR DECISION REQUIRED with zero writes (no N15 stale-ORIGINAL overwrite)
    lat, nxt = {}, {}
    for nm, setup, lease, end, ph in (("A", setup_a, lambda w: w.fp_start(power_w=3000, minutes=30), lambda w: w.fp_end(),
                                       "dump"),
                                      ("B", setup_b, lambda w: w.dump_start(power_w=1000, stop_soc=25, minutes=30),
                                       lambda w: w.dump_end(), "fp")):
        for owner in (False, True):
            w = setup()
            lease(w)
            w.run_for(60)
            end(w)
            w.run_for(60)
            seq0 = w.log[-1]["seq"]
            if owner:
                w.set_register(256, 6000, actor="owner")
                w.run_for(5)
            w.reboot()
            b = w.boot_no
            w.run_for(120)
            lat[(nm, owner)] = (w.status(ph), w.nvs_marker(ph), writes_after(w, b), ids(L.check_invariants(after(w, seq0),
                                                                                                         world=w)), diff(w))
            ob = booted(w, b)
            nxt[(nm, owner)] = (hardened(w, after(w, seq0), case=f"FW-05 {nm}: PR41-GHOST at its next boot"
                                         + (" (owner changed 256)" if owner else "")), ob["nvs"][ph], ob[ph]["snap"])
    check("FW-05 latent phantom, next boot with the bank unchanged (both directions): the phantom's restore is a "
          "zero-write verified no-op and commits CLEAR; no invariant violation after the reboot",
          all(lat[(nm, False)][0] == "RESTORED OK - original inverter settings verified" and lat[(nm, False)][1:] ==
              ("CLEAR", [], [], {}) for nm in ("A", "B")), str({k: v for k, v in lat.items() if not k[1]}))
    check("FW-05 latent phantom, owner changed 256 before the next boot (both directions): the phantom's restore stops at "
          "OPERATOR DECISION REQUIRED with zero writes and the marker stays RESTORE_REQUIRED (the drift guard fails "
          "closed; N15's stale-ORIGINAL overwrite does not occur)",
          all(lat[(nm, True)][0].startswith("OPERATOR DECISION REQUIRED") and lat[(nm, True)][1:] ==
              ("RESTORE_REQUIRED", [], [], {}) for nm in ("A", "B")), str({k: v for k, v in lat.items() if k[1]}))
    check("FW-05 hardened checkers, PR41-GHOST: in its own runtime the ghost (stored RESTORE_REQUIRED, RAM clear, not "
          "RAM-visible) is never an INV-BOOT-MIRROR case (only boots are judged) and no silent override (the bank ends at "
          "ORIGINAL); at its next boot the stored RESTORE_REQUIRED is mirrored by the phantom domain's snapshot_valid "
          "(INV-BOOT-MIRROR holds, all four variants) and INV-NO-SILENT-OVERRIDE stays clean",
          all(h["bm"] == [] and h["nso"] == [] and not h["silent"] and m == "RESTORE_REQUIRED" and vis == []
              for h, m, vis in ghost.values())
          and all(h["bm"] == [] and h["nso"] == [] and m == "RESTORE_REQUIRED" and snap for h, m, snap in nxt.values()),
          str({"runtime": ghost, "next boot": nxt}))
    # F-FW05-2: the N17 shape, uncut
    w = setup_c()
    boot_seq = [e for e in w.log if e["kind"] == "fw.boot"][-1]["seq"]
    st_boot = (w.corrupt("fp"), w.corrupt("dump"), w.status("fp"))
    w.run_for(120)
    v = L.check_invariants(after(w, boot_seq), world=w)     # the boot with the unreadable Dump data record onwards
    n17 = [x for x in v if x["inv"] == "INV-NO-2ND-RESTORER"]
    finding("F-FW05-2", st_boot[:2] == (False, True) and st_boot[2] == "ACTIVE - reboot recovery pending"
            and ids(v) == ["INV-LOCKOUT-QUIET", "INV-NO-2ND-RESTORER"] and n17 and all(x["tags"] == ["N17"] for x in n17)
            and w.status("fp").startswith("RESTORED OK") and w.nvs_marker("fp") == "CLEAR"
            and w.nvs_marker("dump") == "RESTORE_REQUIRED" and w.corrupt("dump") and not diff(w),
            f"{st_boot} {ids(v)} {w.status('fp')} {w.nvs_marker('dump')}")
    n17h = [("phantom", hardened(w, after(w, boot_seq), case="F-FW05-2 N17: FP restore over a corrupt-locked Dump phantom"),
             booted(w, w.boot_no))]
    # the mirror (Free Power phantom + Dump lease, Free Power data unreadable at boot): the Dump restore over FP's RR
    w = setup_b()
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(60)
    w.reboot(nvs_fault=("read_error", "fp.data"))
    boot_seq, b = [e for e in w.log if e["kind"] == "fw.boot"][-1]["seq"], w.boot_no
    st_boot = (w.corrupt("fp"), w.corrupt("dump"))
    w.run_for(120)
    v = L.check_invariants(after(w, boot_seq), world=w)
    finding("F-FW05-2", st_boot == (True, False) and sorted((x["inv"], tuple(x["tags"])) for x in v)
            == [("INV-LOCKOUT-QUIET", ()), ("INV-NO-2ND-RESTORER", ("N17",))]
            and w.status("dump").startswith("RESTORED OK") and w.nvs_marker("dump") == "CLEAR"
            and w.nvs_marker("fp") == "RESTORE_REQUIRED" and w.corrupt("fp")
            and writes_after(w, b) == [(244, [2]), (256, [ORIG[a] for a in range(256, 262)])] and not diff(w),
            f"{st_boot} {[(x['inv'], x['tags']) for x in v]} {w.status('dump')} {writes_after(w, b)}", tag="mirror")
    n17h.append(("mirror", hardened(w, after(w, boot_seq), case="F-FW05-2 N17 mirror: Dump restore over a corrupt FP "
                                                                "phantom"), booted(w, w.boot_no)))
    # the UNKNOWN form without a phantom: a used Dump (stored CLEAR) whose marker reads READ_ERROR at a boot inside an FP
    # lease -> Dump UNKNOWN lockout, the FP restore writes 256-261 under it (INV-LOCKOUT-QUIET only)
    w = world()
    dump_env(w)
    w.dump_start(power_w=1000, stop_soc=25, minutes=5)
    w.run_for(400)
    w.fp_start(power_w=3000, minutes=30)
    w.run_for(60)
    w.reboot(nvs_fault=("read_error", "dump.valid"))
    boot_seq = [e for e in w.log if e["kind"] == "fw.boot"][-1]["seq"]
    st_boot = (w.corrupt("fp"), w.corrupt("dump"), w.status("dump"))
    w.run_for(120)
    v = L.check_invariants(after(w, boot_seq), world=w)
    finding("F-FW05-2", st_boot[:2] == (False, True) and A_PLATFORM[1] in st_boot[2]
            and [(x["inv"], x["tags"]) for x in v] == [("INV-LOCKOUT-QUIET", [])]
            and w.status("fp").startswith("RESTORED OK") and w.nvs_marker("fp") == "CLEAR" and not diff(w),
            f"{st_boot} {[(x['inv'], x['tags']) for x in v]} {w.status('fp')}", tag="unknown-no-phantom")
    n17h.append(("unknown", hardened(w, after(w, boot_seq), case="F-FW05-2 N17 UNKNOWN form: FP restore under a Dump "
                                                                 "READ_ERROR lockout"), booted(w, w.boot_no)))
    want_boot = {"phantom": ({"fp": "RESTORE_REQUIRED", "dump": "RESTORE_REQUIRED"}, ("fp", "dump")),
                 "mirror": ({"fp": "RESTORE_REQUIRED", "dump": "RESTORE_REQUIRED"}, ("fp", "dump")),
                 "unknown": ({"fp": "RESTORE_REQUIRED", "dump": "CLEAR"}, ("fp",))}
    check("FW-05 hardened checkers, the N17 shapes: every stored RESTORE_REQUIRED at the boot is mirrored (the restoring "
          "domain by snapshot_valid, the locked domain by snapshot_valid + metadata_corrupt; the UNKNOWN form's stored "
          "CLEAR needs nothing) - INV-BOOT-MIRROR holds - and INV-NO-SILENT-OVERRIDE is clean (the locked domain's "
          "obligation is RAM-visible); N17 shows only as INV-NO-2ND-RESTORER / INV-LOCKOUT-QUIET",
          all(h["bm"] == [] and h["nso"] == [] and not h["silent"]
              and {d: ob["nvs"][d] for d in ("fp", "dump")} == want_boot[k][0]
              and all(ob[d]["snap"] for d in want_boot[k][1]) for k, h, ob in n17h),
          str([(k, h["bm"], h["nso"], ob["nvs"]) for k, h, ob in n17h]))
    print(f"  info  FW-05 total: {SWEEP_TOTAL['cut']} cut runs" + (f" + {SWEEP_TOTAL['nested']} nested second-cut runs"
                                                                   if EXTENDED else "") + " rebooted through the FULL on_boot")

    # negative control: PR41 removed -> a cut after the phantom-admitted Free Power START's TOU write reboots into two
    # restorers over 256-261
    def nc_pr41():
        m = mutant("            id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED\n          ) {\n"
                   "            id(free_power_recovery_metadata_corrupt) = true;",
                   "            false\n          ) {\n            id(free_power_recovery_metadata_corrupt) = true;")
        if m is None:
            return None
        evs, _w = sweep_events("A-start", fw=m)
        k = next(i for i, e in enumerate(evs) if e["kind"] == "fw.write" and e["data"]["addr"] == 256)
        return cut_run("A-start", k, fw=m)["post"]
    negative_control("NC-FW05-1", "PR41 mutant (the Free Power / Dump dual-obligation lockout never fires), cut after the "
                     "phantom-admitted START's 256-261 write", "INV-NO-2ND-RESTORER", nc_pr41)


# =============================================================================================================================
# [3] FW-06 commit false negatives / false positives at every other commit site
# =============================================================================================================================
_COMMIT_RE = re.compile(r"commit_record\(\s*ecco_durable::key_for\(ecco_durable::(\w+)\)")
_OWNER_RE = re.compile(r"^(?:  - id: |    id: )(\S+)\s*$")


def static_commit_sites() -> dict:
    """{(script | '(button)', tag alias): [line, ...]} for every commit_record(key_for(TAG)) call in the firmware text."""
    text = FW["_text"]
    lines = text.split("\n")
    out: dict = {}
    for m in _COMMIT_RE.finditer(text):
        ln = text.count("\n", 0, m.start())
        owner = next((mm.group(1) for i in range(ln, -1, -1) for mm in [_OWNER_RE.match(lines[i])] if mm), None)
        if owner in INFO.scripts:
            key = owner
        elif owner in INFO.buttons:
            key = "(button)"
        else:
            raise L.LabHarnessError(f"commit site at line {ln + 1}: enclosing component {owner!r} is neither a script nor "
                                    f"a button")
        out.setdefault((key, TAGN[getattr(D, m.group(1))]), []).append(ln + 1)
    return out


def r244_apply(w) -> None:
    w.press("load_reg244_staging")
    w.set_select("manual_reg244_staged_target", "Allow Export")
    w.set_switch("manual_config_write_enable", True)
    w.press("apply_reg244_settings_button")


def r244_restore(w) -> None:
    w.set_switch("manual_config_write_enable", True)
    w.press("restore_reg244_button")


ACCEPT_FOREIGN = [(230, 100)] + [(a, 4321) for a in range(256, 262)] + [(a, 50) for a in range(268, 274)] + [(232, 0)] + [
    (a, 0) for a in range(275, 280)]


def fl_fp_natural(w):
    w.fp_start(power_w=3000, minutes=5); w.run_for(400); w.reboot(); w.run_for(60)   # noqa: E702


def fl_fp_reboot(w):
    w.fp_start(power_w=3000, minutes=5); w.run_for(60); w.reboot(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_fp_end(w):
    w.fp_start(power_w=3000, minutes=5); w.run_for(60); w.fp_end(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_fp_force(w):
    w.fp_start(power_w=3000, minutes=5)
    w.run_for(30)
    w.set_register(257, 4321, actor="inverter")
    w.run_for(600)
    w.fp_operator("FORCE_RESTORE_ORIGINAL")
    w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_fp_accept(w):
    w.fp_start(power_w=3000, minutes=5)
    w.run_for(30)
    for a, v in ACCEPT_FOREIGN:
        w.set_register(a, v, actor="inverter")
    w.run_for(600)
    w.fp_operator("ACCEPT_CURRENT_STATE")
    w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_fp_clear_only(w):
    w.fp_start(power_w=3000, minutes=5)
    w.nvs_policy("fp.valid", CLR, mode="false_positive")      # the flow's own first fault: durable PENDING_CLEAR stays
    w.run_for(400); w.reboot(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_natural(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(400); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_reboot(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(60)   # noqa: E702
    w.reboot(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_end(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(60)   # noqa: E702
    w.dump_end(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_force(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(60); w.reboot()   # noqa: E702
    w.set_register(257, 4321, actor="inverter")
    w.run_for(60); w.dump_force_restore(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_force_pc(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(60); w.reboot()   # noqa: E702
    w.set_register(257, 4321, actor="inverter")
    w.run_for(60)
    w.nvs_policy("dump.valid", CLR, mode="false_negative")    # the flow's own first fault: the Force's CLEAR reports false
    w.dump_force_restore(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_accept(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5); w.run_for(60); w.reboot()   # noqa: E702
    w.set_register(257, 4321, actor="owner")
    w.run_for(60); w.dump_accept(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_clear_only(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=5)   # noqa: E702
    w.nvs_policy("dump.valid", CLR, mode="false_positive")
    w.run_for(400); w.reboot(); w.run_for(60); w.reboot(); w.run_for(60)   # noqa: E702


def fl_dump_controller(w):
    dump_env(w); w.dump_start(power_w=1000, stop_soc=25, minutes=10)   # noqa: E702
    w.telemetry(grid_w=-500, batt_w=1550)                     # the controller raises the ceiling (data re-commits)
    w.run_for(120); w.reboot(); w.run_for(60)   # noqa: E702


def fl_r244(w):
    r244_apply(w); w.run_for(5); w.reboot(); w.run_for(90)   # noqa: E702
    r244_restore(w); w.run_for(5); w.reboot(); w.run_for(90)   # noqa: E702


FLOWS = {"fp_reboot": fl_fp_reboot, "fp_natural": fl_fp_natural, "fp_end": fl_fp_end, "fp_force": fl_fp_force,
         "fp_accept": fl_fp_accept, "fp_clear_only": fl_fp_clear_only, "dump_reboot": fl_dump_reboot,
         "dump_natural": fl_dump_natural, "dump_end": fl_dump_end, "dump_force": fl_dump_force,
         "dump_force_pc": fl_dump_force_pc, "dump_accept": fl_dump_accept, "dump_clear_only": fl_dump_clear_only,
         "dump_controller": fl_dump_controller, "r244": fl_r244}
REBOOT_FLOWS = ("fp_reboot", "dump_reboot")
FW01_SITES = {("start_free_power_override", "fp.valid", "1"), ("start_dump_to_grid_override", "dump.valid", "1")}


def signature(w, key, r) -> tuple:
    k = r._kind
    extra = (r.state if k == "ValidMarker" else r.operator_needed if k.endswith("RetryState")
             else (r.active_persisted, r.restore_requested) if k.startswith(("DumpToGridSnapshotData",
                                                                             "FreePowerSnapshotData"))
             else r.start_attempted if k == "FreePowerStartJournal" else r.value if k == "Reg244SnapshotData" else None)
    top = w.sim.script_stack[-1] if w.sim.script_stack else "(button)"
    return top, TAGN.get(key, key), str(extra)


def flow_domain(flow: str) -> str:
    """The domain a flow drives (its name prefix: fp_* / dump_* / r244)."""
    d = flow.split("_", 1)[0]
    if d not in ("fp", "dump", "r244"):
        raise L.LabHarnessError(f"flow {flow!r}: no domain prefix")
    return d


def flow_run(flow: str, j: int | None = None, mode: str | None = None) -> tuple:
    """Run a flow with the j-th commit (in order, across boots) given `mode`; also return every commit's signature. Every
    flow runs on a USED domain (V0.1, B5): the completed-lease prelude of the flow's domain comes first, before the commit
    predicate is armed, so commit j is the flow's own j-th commit and every key it can hit was stored earlier."""
    w = world()
    prelude(w, flow_domain(flow))
    seen: list = []

    def pred(key, r):
        seen.append(signature(w, key, r))
        return j is not None and len(seen) == j + 1
    w.nvs_policy(pred, mode=mode or "landed", times=None)
    FLOWS[flow](w)
    return w, seen


def end_class(w) -> str:
    vis = [d for d in ("fp", "dump", "r244") if w.nvs_marker(d) not in ("CLEAR", "ABSENT") or w.corrupt(d)]
    opn = [d for d, p in (("fp", "free_power"), ("dump", "dump")) if w.sim.g[f"{p}_operator_needed"]]
    if not vis and not opn and not diff(w):
        return "resolved"
    return "visible:" + ",".join(sorted(set(vis) | {f"{d}.opn" for d in opn}))


def sec_fw06() -> None:
    sites = static_commit_sites()
    n_text = sum(len(v) for v in sites.values())
    print(f"  info  FW-06 commit-site inventory: {n_text} commit_record(key_for(TAG)) calls in {len(sites)} (component, "
          f"tag) groups")
    for (comp, alias), lns in sorted(sites.items()):
        print(f"  info    {comp} {alias}: line(s) {lns}")
    nominal, covered, clear_only = {}, set(), {}
    for flow in FLOWS:
        w, seen = flow_run(flow)
        nominal[flow] = seen
        check(f"FW-06 flow {flow}: the fault-free run ends resolved with every invariant holding "
              f"({len(seen)} commits)", end_class(w) == "resolved" and not w.invariants(),
              f"{end_class(w)} {ids(w.invariants())}")
        covered |= {(s[0], s[1]) for s in seen}
        if flow.endswith("_clear_only"):
            d = flow.split("_", 1)[0]
            clear_only[d] = (hardened(w, case=f"FW-06 {flow}: stored PENDING_CLEAR at the reboot"), booted(w, 1))
    check("FW-06 hardened checkers, the clear-only flows: the reboot's stored PENDING_CLEAR is mirrored by snapshot_valid "
          "(INV-BOOT-MIRROR's clear-only rule judged and holds; the zero-I/O clear-only branch then completes) and "
          "INV-NO-SILENT-OVERRIDE is clean (both domains)",
          sorted(clear_only) == ["dump", "fp"] and all(h["bm"] == [] and h["nso"] == [] and ob["nvs"][d] == "PENDING_CLEAR"
                                                      and ob[d]["snap"] for d, (h, ob) in clear_only.items()),
          str({d: (h["bm"], h["nso"], ob["nvs"]) for d, (h, ob) in clear_only.items()}))
    missing = sorted(set(sites) - covered)
    extra = sorted(covered - set(sites))
    check(f"FW-06: every (component, tag) commit group of the firmware text is reached by a flow ({len(sites)} groups); "
          f"every dynamic commit maps to a text group", not missing and not extra, f"missing {missing} extra {extra}")
    print(f"  info  FW-06 distinct commit signatures reached: {len({s for v in nominal.values() for s in v})} (a group "
          f"with several text sites is driven through the signatures its records carry; text sites inside one group are "
          f"not distinguished one by one)")
    # injection plan
    plan, seen_sig = [], set()
    modes = ("false_negative", "false_positive", "not_landed") if EXTENDED else ("false_negative", "false_positive")
    for flow, seen in nominal.items():
        local = set()
        for j, s in enumerate(seen):
            if s in local and not EXTENDED:
                continue
            local.add(s)
            if not EXTENDED and s in seen_sig and not (flow in REBOOT_FLOWS and s[0].startswith("start_")) and not (
                    s in FW01_SITES and flow.endswith("_natural")):
                continue
            seen_sig.add(s)
            for mode in modes:
                if mode == "false_negative" and s in FW01_SITES:
                    continue   # FW-01's subject (the phantom); not injected here
                plan.append((flow, j, s, mode))
    print(f"  info  FW-06 injections: {len(plan)} runs ({'every occurrence x 3 modes' if EXTENDED else 'one per distinct '
          'signature per mode, plus every START-time signature under a reboot during the lease'})")
    results = []
    for flow, j, s, mode in plan:
        w, _seen = flow_run(flow, j, mode)
        summary = {"status": {d: w.status(d) for d in ("fp", "dump")}, "marker": {d: w.nvs_marker(d) for d in ("fp", "dump")},
                   "diff": diff(w), "last_boot_writes": writes_after(w, w.boot_no), "h": hardened(w)}
        results.append((flow, j, s, mode, ids(w.invariants()), end_class(w), summary))
        del w
    unexplained = [(f, j, s, m, v) for f, j, s, m, v, _c, _w in results if v and not (
        m == "false_positive" and s in FW01_SITES and v == ["INV-NO-SILENT-OVERRIDE"])]
    check(f"FW-06: no injection at any commit site outside the two Phase-B marker false positives yields an invariant "
          f"violation ({len(results)} runs; RAM / durable divergences are safe by design)", not unexplained,
          str(unexplained[:4]))
    judged = [r for r in results if any(set(nv.values()) & STORED_JUDGED for b, nv in r[6]["h"]["boots"].items() if b)]
    bm_all = [(r[0], r[1], r[2], r[3], r[6]["h"]["bm"]) for r in results if r[6]["h"]["bm"]]
    check(f"FW-06 hardened checkers: INV-BOOT-MIRROR found 0 violations in all {len(results)} injection runs, "
          f"{len(judged)} of which reboot with a stored RESTORE_REQUIRED / PENDING_CLEAR marker (every RAM / durable "
          f"divergence an injection leaves is mirrored at the next boot or resolved before it)",
          bool(judged) and not bm_all, str(bm_all[:4]))
    hist = Counter((m, c.split(":")[0]) for _f, _j, _s, m, _v, c, _w in results)
    print(f"  info  FW-06 outcome classes by mode: {dict(sorted(hist.items()))}")
    vis = sorted({(s, m, c) for _f, _j, s, m, v, c, _w in results if c != "resolved" and not v})
    for s, m, c in vis:
        print(f"  info    fail-closed / visible end state: {s} {m} -> {c}")
    stale = [r for r in results if r[2][0] in ("free_power_recovery_force_restore_dispatch",
                                                "free_power_recovery_accept_current_state_dispatch")
             and r[5] == "visible:fp.opn"]
    restart_ok = False
    if stale:
        w, _seen = flow_run(stale[0][0], stale[0][1], stale[0][3])
        s_new = w.fp_start(power_w=3000, minutes=5)
        w.run_for(400)
        restart_ok = s_new.startswith("ACTIVE") and end_class(w) == "resolved" and not w.invariants()
    check("FW-06: a Force / Accept Phase C or D marker false negative, or their clean-retry commit false positive, leaves "
          "only a stale durable operator_needed beside a CLEAR marker (the S4 record's stale operator-needed case): no "
          "obligation, no lockout, no invariant violation; the next Free Power START resets it and runs a clean lease",
          bool(stale) and all(not r[4] and r[6]["marker"]["fp"] == "CLEAR" for r in stale) and restart_ok,
          str([r[:4] for r in stale]))
    acc = [r for r in results if r[2] == ("dump_accept_current_state", "dump.valid", "0") and r[3] == "false_positive"]
    check("FW-06: a Dump Accept CLEAR false positive undoes the operator's Accept at the next reboot (marker still "
          "RESTORE_REQUIRED -> OPERATOR DECISION REQUIRED again); fail-closed, zero writes after that boot",
          len(acc) >= 1 and all(r[5] == "visible:dump,dump.opn" and not r[4]
                                and r[6]["status"]["dump"].startswith("OPERATOR DECISION REQUIRED")
                                and r[6]["last_boot_writes"] == [] and r[6]["h"]["bm"] == []
                                and r[6]["h"]["boots"][max(r[6]["h"]["boots"])]["dump"] == "RESTORE_REQUIRED" for r in acc),
          str([(r[5], r[6]["status"]["dump"][:40]) for r in acc]))
    fpos = {d: [r for r in results if r[3] == "false_positive" and r[2] in FW01_SITES and r[2][1].startswith(d)]
            for d in ("fp", "dump")}
    # V0.1 (B5): every flow runs after a completed-lease prelude, so the Phase-B marker false positive leaves the
    # prelude's stored CLEAR in place (a false positive stores nothing) and both reboots load it LOAD_OK; on_boot maps it
    # exactly as it maps ABSENT ('state = have_marker ? marker.state : MARKER_CLEAR' -> snapshot_valid = false, FP
    # FW:552-555, Dump FW:801-804). The never-used (ABSENT) variant is no longer injected: a false positive on a
    # never-stored key is refused by the NVS USED-KEY RULE.
    used: dict = {}
    for fid, d in (("F-FW06-2", "fp"), ("F-FW06-3", "dump")):
        rows = fpos[d]
        rb = [r for r in rows if r[0] in REBOOT_FLOWS]
        nat = [r for r in rows if r[0] == f"{d}_natural"]
        residue = FP_RESIDUE if d == "fp" else DUMP_RESIDUE
        finding(fid, bool(rb) and bool(nat) and all(r[4] == ["INV-NO-SILENT-OVERRIDE"] and r[6]["marker"][d] == "CLEAR"
                                                    and r[6]["diff"] == residue and r[6]["status"][d] == "Inactive"
                                                    for r in rb)
                and all(not r[4] and r[5] == "resolved" for r in nat),
                str([(r[0], r[4], r[5], r[6]["marker"][d], r[6]["status"][d][:30]) for r in rows]))
        used[d] = [(r[0], r[6]["h"]) for r in rb]
        for r in rb[:1]:
            CHECKER_ROWS.append((f"{fid} {d} Phase-B marker false positive after a completed-lease prelude (stale CLEAR), "
                                 f"two reboots during the lease ({r[0]})", r[6]["h"]))
    check("FW-06 hardened checkers, Phase-B marker false positive on a used domain (reboot flows, after the completed-lease "
          "prelude): the stored marker is the prelude's stale CLEAR at both reboots, which INV-BOOT-MIRROR does not judge; "
          "INV-NO-SILENT-OVERRIDE reports one UNTAGGED episode per boot (no injected boot fault, so the core's "
          "PLATFORM-ABSENT tag does not apply), at each boot's settle point (boots 1 and 2), and the world ends silent",
          all(used[d] and all(h["bm"] == [] and h["nso"] == [(1, SETTLE, (), None), (2, SETTLE, (), None)]
                              and h["silent"] and h["boots"][1][d] == h["boots"][2][d] == "CLEAR" for _f, h in used[d])
              for d in ("fp", "dump")), str(used))
    # the realistic boot state: one completed lease first (marker CLEAR stored), then the Phase-B false positive
    stale: dict = {}
    for fid, d in (("F-FW06-2", "fp"), ("F-FW06-3", "dump")):
        w = world()
        start_lease(w, d, 5)
        w.run_for(400)
        img0 = (w.nvs_marker(d), {k: rec(w, f"{d}.data")[k] for k in ("active_persisted", "restore_requested")})
        w.nvs_policy(f"{d}.valid", RR, mode="false_positive")
        s = start_lease(w, d, 30)
        w.run_for(60)
        w.reboot()
        b = w.boot_no
        st = w.status(d)
        load = [e["data"]["ok"] for e in w.log if e["kind"] == "fw.load" and e["boot"] == b
                and e["data"].get("key") == L.TAGS[f"{d}.valid"]][:1]
        w.run_for(600)
        v = w.invariants()
        img1 = (w.nvs_marker(d), {k: rec(w, f"{d}.data")[k] for k in ("active_persisted", "restore_requested")})
        stale[d] = (hardened(w, case=f"{fid} {d} Phase-B marker false positive after a completed lease (stale CLEAR)"), b)
        residue = FP_RESIDUE if d == "fp" else DUMP_RESIDUE
        finding(fid, s.startswith("ACTIVE") and st == "Inactive" and load == [True] and img1[0] == "CLEAR"
                and not w.corrupt(d) and writes_after(w, b) == [] and diff(w) == residue
                and [(x["inv"], x["tags"]) for x in v] == [("INV-NO-SILENT-OVERRIDE", [])]
                and img0[0] == "CLEAR" and (img1 == img0 if d == "fp" else img1[1] == {"active_persisted": 1,
                                                                                       "restore_requested": 0}),
                f"{s[:30]} {st} load {load} {img0} -> {img1} diff {diff(w)} inv {[(x['inv'], x['tags']) for x in v]}",
                tag="prior-lease-stale-clear")
        print(f"  info  {fid} (prior lease): the reboot loads the previous lease's CLEAR marker (LOAD_OK); durable image "
              f"after the completed lease {img0}, after the false-positive lease {img1}"
              + (" - identical, so no boot check on these records can tell them apart" if img1 == img0 else
                 " - differs only in restore_requested (untested as a discriminator)"))
    check("FW-06 hardened checkers, Phase-B marker false positive after a completed lease: the boot's stored marker is the "
          "previous lease's stale CLEAR, which INV-BOOT-MIRROR does not judge (CLEAR needs no mirror); INV-NO-SILENT-OVERRIDE "
          "reports exactly one UNTAGGED episode at that boot's settle point and the world ends silent (both domains)",
          sorted(stale) == ["dump", "fp"] and all(h["bm"] == [] and h["boots"][b][d] == "CLEAR"
                                                  and h["nso"] == [(b, SETTLE, (), None)] and h["silent"]
                                                  for d, (h, b) in stale.items()), str(stale))
    print("  info  F-FW06-2/3: with no reboot during the lease the RAM obligation restores normally (Phase C/D land); the "
          "F-FW04-1 boot cross-check (ABSENT + active data) would close only the never-used ABSENT variant; the used-device "
          "stale-CLEAR variant needs the commit-site read-back (repair scope)")

    # F-FW06-1: the Free Power START commit-failure status cascade; Dump START as the contrast. V0.1 (B5): each START
    # runs after a completed-lease prelude of its domain (the NVS USED-KEY RULE); the statuses, writes, failure count and
    # successes are those after the prelude (the prelude's own lease counts one START success and writes its lease)
    rows, ok = [], True
    for alias, st, final in (("fp.data", None, "END IGNORED - no saved Free Power snapshot"),
                             ("fp.valid", RR, "END IGNORED - no saved Free Power snapshot"),
                             ("fp.retry", None, "RESTORED OK - original inverter settings verified"),
                             ("fp.journal", None, "RESTORED OK - original inverter settings verified")):
        for mode in ("not_landed", "false_negative"):
            w = world()
            p = prelude(w, "fp")
            f0, h0, s0 = w.sim.g["free_power_failures"], len(w.status_history("fp")), w.ha_view()["fp_start_successes"]
            w.nvs_policy(alias, st, mode=mode)
            w.fp_start(power_w=3000, minutes=30)
            hist = w.status_history("fp")[h0:]
            i = hist.index(A_START_FAILED[1]) if A_START_FAILED[1] in hist else -1
            good = (i >= 0 and hist[i + 1:i + 2] == [A_ACTIVATION[1]] and hist[-1] == final and writes_since(w, p) == []
                    and w.sim.g["free_power_failures"] - f0 == 2 and w.ha_view()["fp_start_successes"] - s0 == 0)
            ok &= good
            rows.append((alias, mode, w.sim.g["free_power_failures"] - f0, hist[-1][:40]))
    finding("F-FW06-1", ok, str(rows))
    print(f"  info  F-FW06-1 cascade per site/mode (failures delta, final text): {rows}")
    contrast = []
    for alias, st in (("dump.retry", None), ("dump.data_v1", None), ("dump.data", None), ("dump.valid", RR)):
        for mode in ("not_landed", "false_negative"):
            w = world()
            p = prelude(w, "dump")
            dump_env(w)
            h0 = len(w.status_history("dump"))
            w.nvs_policy(alias, st, mode=mode)
            w.dump_start(power_w=1000, stop_soc=25, minutes=30)
            contrast.append(w.status_history("dump")[h0:] == ["STARTING - taking fresh inverter snapshot",
                                                              "START FAILED - could not capture/durably commit inverter "
                                                              "snapshot; nothing written"] and writes_since(w, p) == [])
    check("FW-06 contrast: every Dump START commit failure (retry, tombstone, data, marker; true and false negative) "
          "ends on ONE terminal 'START FAILED' text with nothing written (what the Free Power START should also do)",
          all(contrast), str(contrast))

    # negative control: the Phase-B guard (no START without BOTH commits) is what keeps a marker true negative harmless
    def nc_phase_b():
        m = mutant(A_PHASE_B[1], "if (data_committed) {\n                        id(free_power_snapshot_valid) = true;")
        if m is None:
            return None
        q = world(m)
        prelude(q, "fp")                  # V0.1 (B5): the marker key was stored earlier (the NVS USED-KEY RULE)
        q.nvs_policy("fp.valid", RR, mode="not_landed")
        q.fp_start(power_w=3000, minutes=30)
        q.run_for(60)
        q.reboot()
        q.run_for(120)
        return q.invariants()
    negative_control("NC-FW06-1", "Phase-B guard mutant (START proceeds on the data commit alone) + marker true negative + "
                     "a reboot during the lease", "INV-NO-SILENT-OVERRIDE", nc_phase_b)
    w = world()
    p = prelude(w, "fp")
    w.nvs_policy("fp.valid", RR, mode="not_landed")
    s = w.fp_start(power_w=3000, minutes=30)
    w.run_for(60)
    w.reboot()
    w.run_for(120)
    check("FW-06 guard (the negative control's real-firmware twin): a marker TRUE negative at START (after a completed "
          "lease) aborts before any write; after a reboot nothing is live and every invariant holds",
          writes_since(w, p) == [] and not diff(w) and not w.invariants()
          and "START FAILED" in " ".join(w.status_history("fp")), s)


# =============================================================================================================================
# [R] corpus replay
# =============================================================================================================================
def sec_corpus() -> None:
    missing = [c for c in CORPUS_IDS if not (CORPUS / f"{c}.json").is_file()]
    check(f"corpus: all {len(CORPUS_IDS)} replay documents of this suite exist", not missing, str(missing))
    by_cls = {f["corpus"]: f["classification"] for f in FINDINGS.values()}
    by_dup = {f["corpus"]: f["duplicate_of"] for f in FINDINGS.values() if f.get("duplicate_of")}
    for cid in CORPUS_IDS:
        path = CORPUS / f"{cid}.json"
        if not path.is_file():
            continue
        doc = T.load_doc(path)
        res = T.replay(doc)
        want = by_cls.get(cid, "PASS")
        dup = by_dup.get(cid)
        if dup is not None:
            check(f"corpus {cid}: its notes name the duplicate's owner ('Duplicate of {dup}') and its classification is "
                  f"the finding's ({want})", f"Duplicate of {dup}" in doc.get("notes", "") and doc["classification"] == want,
                  doc.get("notes", "")[:120])
        check(f"corpus {cid}: replays ok ({doc['classification']}; drift={res.drift}; {len(res.log)} events; digest "
              f"{'= trace_digest' if res.digest == doc['trace_digest'] else 'differs'})",
              res.ok and doc["classification"] == want and doc["id"] == cid and doc["synthetic"] is True,
              f"failed {res.failed_expectations} anchors {res.anchor_problems} mismatch {res.digest_mismatch} "
              f"classification {doc['classification']} (want {want})")
    first = CORPUS / f"{CORPUS_IDS[0]}.json"
    if first.is_file():
        bad = T.load_doc(first)
        bad["expect"][0]["value"] = "RESTORED OK - original inverter settings verified"
        res = T.replay(bad)
        check(f"corpus negative control: {CORPUS_IDS[0]} with one altered expectation FAILS its replay (exactly that one)",
              not res.ok and [f["index"] for f in res.failed_expectations] == [0], str(res.failed_expectations))


# =============================================================================================================================
# run
# =============================================================================================================================
section("[0] scenario catalogue: anchors, classification vocabulary, known-risk registry", sec_catalogue)
section("[1] FW-04 false ABSENT at reboot during an ACTIVE lease (single key / whole-partition erase)", sec_fw04)
section("[2] FW-05 power cut at every event of a START / restore while the other domain holds RESTORE_REQUIRED", sec_fw05)
section("[3] FW-06 commit false negatives / false positives at every other commit site; START failure cascade", sec_fw06)
section("[R] corpus replay (corpus/FW-04-*, FW-05-*, FW-06-*)", sec_corpus)
def _fmt_checker(h: dict) -> str:
    bm = "; ".join(f"boot {b} {d} {m}" for b, d, m in h["bm"]) or "none"
    nso = "; ".join(f"boot {b} at the {w}" + (f" tags {list(t)}" if t else " untagged")
                    + (f" ignoring stored {ig}" if ig else "") for b, w, t, ig in h["nso"]) or "none"
    return f"INV-BOOT-MIRROR {bm} | INV-NO-SILENT-OVERRIDE {nso} | silent at the end: {h['silent']}"


print("  info  hardened checker classification per case (INV-BOOT-MIRROR / level-based INV-NO-SILENT-OVERRIDE):")
for case, h in CHECKER_ROWS:
    print(f"  info    {case}: {_fmt_checker(h)}")
print(f"  info    FW-05 sweeps: {SWEEP_TOTAL['cut']} cut runs, {SWEEP_TOTAL['bm_judged']} cut boots with a stored "
      f"RESTORE_REQUIRED / PENDING_CLEAR marker; INV-BOOT-MIRROR {SWEEP_TOTAL['bm_viol']}, INV-NO-SILENT-OVERRIDE "
      f"{SWEEP_TOTAL['nso_viol']} violations; {SWEEP_TOTAL['silent_end']} silent end states")
for s in SCENARIOS:
    found = [f"{f}({FINDINGS[f]['classification'].replace('FINDING-KNOWN:', 'KNOWN:')}"
             + (f", DUPLICATE of {FINDINGS[f]['duplicate_of']}" if FINDINGS[f].get("duplicate_of") else "") + ")"
             for f in s["findings"] if f in REPORTED]
    print(f"  SCENARIO  {s['id']} {s['priority']} {s['classification']} grade={s['grade']} confidence={s['confidence']} "
          f"findings={','.join(found)}")
print("  info  negative controls: " + ", ".join(f"{n} {o}" for n, o in NC_RESULTS))
print(f"  info  findings: {len(REPORTED)} reproduced, {len(counted())} counted in the summary line (not counted: "
      + (", ".join(f"{f} = {FINDINGS[f]['duplicate_of']}" for f in REPORTED if FINDINGS[f].get("duplicate_of")) or "none")
      + ")")
check("every finding of the catalogue reproduced in this run (none silently skipped)", sorted(REPORTED) == sorted(FINDINGS),
      f"reported {sorted(REPORTED)}")
check("every negative control was valid and killed its target invariant", bool(NC_RESULTS)
      and all(o == "killed" for _n, o in NC_RESULTS), str(NC_RESULTS))

BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME_S = time.perf_counter() - T0
if EXTENDED:
    print(f"  info  extended sweeps runtime_s {RUNTIME_S:.1f}")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=counted(), finding_pins=FINDING_CHECKS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
