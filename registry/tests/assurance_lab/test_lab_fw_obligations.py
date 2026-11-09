#!/usr/bin/env python3
"""FW-01 / FW-02 / FW-03: durable-obligation scenarios on the real firmware (Phase-B commit false negatives that leave a
phantom RESTORE_REQUIRED marker, cross-domain admission in the same runtime, PR41 / S4 boot arbitration through the FULL
on_boot, SG-02 containment, repeated reboots and watchdog ticks, operator surfaces, manual TOU slot apply under a phantom,
the triple obligation order and the same-tick watchdog order). Offline assurance lab V0 (test-only: no network, no Home
Assistant, no hardware; writes nothing).

Tier: FirmwareWorld (registry/tests/assurance_lab/_lab_fw.py) - one real firmware, both START scripts, both 15 s watchdogs,
the real restore / recovery / containment scripts, the real manual slot Load / Apply buttons. Nothing here decides what the
firmware does; every outcome below is the firmware's own. Findings are printed as '  FINDING  <id> ...' lines and pinned
by 'finding-reproduces:<id>' checks (so a firmware fix fails loudly and forces re-classification); they are not counted as
passes. The SCENARIOS / FINDINGS tables below carry ownership, anchors (text, verified exactly once at run time; line
numbers are information only), invariant, failure outcome, classification, grade, confidence and repair scope.

MODEL ASSUMPTIONS used here (beyond the core's own, see _lab_fw.py MODEL ASSUMPTIONS):
  - A Phase-B commit false negative is injected with the core's nvs_policy(mode='false_negative'): the record lands and
    commit_record returns False. The firmware's PR41 / S4 comments name ESPHome's global sync() failing for an UNRELATED
    pending key; read offline in ESPHome 2026.8.2 (the firmware's min_version, components/esp32/preferences.cpp), sync()
    clears its queue on every call, and at both START marker sites the data commit's own sync() runs immediately before
    in the same synchronous lambda, so that route cannot reach these marker commits. The remaining physical route is the
    marker's own nvs_set_blob reporting an error after the new value was written (ESP-IDF ESP_ERR_NVS_REMOVE_FAILED
    semantics: REPORTED from the ESP-IDF API documentation, not verifiable offline here). Reachability INFERRED, rate
    UNKNOWN, likely very low.
  - B5 used-key prelude (V0.1, brief B5 change 2; audit 2026-10-19 r1 section 5.3): that route needs an EARLIER stored
    version of the marker key, and the core refuses a false negative on a key never stored earlier in the run (the NVS
    USED-KEY RULE, _lab_fw.py module docstring). So every phantom here, directed and corpus, is preceded by a
    COMPLETED LEASE of the injected domain (prelude()): FP / Dump a 1-minute lease ended by its own watchdog with a
    verified restore
    (Phase C VERIFIED_PENDING_CLEAR, then Phase D CLEAR: FP restore_free_power_snapshot_dispatch, firmware :11215-11226;
    Dump :20383-20394); reg244 the owner's Apply then Restore through the real buttons (restore_reg244_snapshot Phase
    C / D :17788-17799). The prelude must end RESTORED OK with the marker CLEAR, every owned register at its ORIGINAL and
    no invariant violation, or the run raises (fail loud). It takes PRELUDE_S = 200 s, so every scenario's own actions
    start at +260 s instead of +60 s (the corpus documents' actions moved by +200 s); absolute epochs follow (the FP end
    epoch is the START time + minutes * 60, firmware :9092). Measurements of 'writes since the phantom' start after the
    prelude (wlist(..., since=...)).
  - The FP / Dump watchdogs share period and startup delay. ESPHome 2026.8.2 (core/scheduler.cpp
    calculate_interval_offset_) gives every interval's first run a random offset in [0, min(period / 2, 5 s)), seeded per
    boot, so on hardware the two watchdogs essentially never share a tick and their order is random per boot: BOTH orders
    are reachable. The lab's tie with an explicit wd_order, and the extended phase sweep, cover both.
  - The owner's register 244 Apply is the core world action FirmwareWorld.r244_apply (real Load button, staged target
    select, master arm, real Apply button; replay action 'r244_apply'), so the triple-obligation case has a corpus file
    (FW-03-c, which also pins F-FW03-3).
Quick mode runs every scenario once per variant (about 10 s here); ECCO_LAB_EXTENDED=1 / --extended adds reboot-offset,
reboot-count, slot / value and watchdog-phase sweeps (about 34 s here) and prints their runtime. The FP START status
cascade after a commit failure ('START FAILED ... END IGNORED') is printed for context only: it is FW-06's subject.
Classifications, severities and repair scopes were revised after an independent two-part check (source fidelity,
classification) and again in the hardening pass (F-FW01-1 -> FINDING-KNOWN:PR41-GHOST; F-FW01-2 -> FINDING-NEW, scoped to
the consequence); the FINDINGS notes say what changed and why.
COUNTING (LAB-SUMMARY 'finding'): each root cause is counted once across the lab. Every reproduced finding prints one
'  FINDING  <id> [<classification>; counted | DUPLICATE of <owner id>, not counted; root ...; xref <ids>] <title>' line.
A finding whose root cause (and repair) is already owned by another finding - in another suite, or a sibling in this
one - is 'DUPLICATE of <owner id>, not counted'; its finding-reproduces check still runs and still fails loudly on a
change. Cross-suite owner / xref ids are verified to exist in the named suite files (read as text, never imported).
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
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "finding-reproduces:F-FW03-1": (
        "order-dependent by design (audit): which watchdog runs first on the tick after the boot decides; the lab "
        "ties the FP and Dump watchdogs (same 15 s period and startup_delay, zero offset) and orders them by "
        "wd_order, ESPHome draws an independent offset for each, so the order is the phase (fails under the phase "
        "patch at some seeds)"),
    "finding-reproduces:F-FW03-2": (
        "a COMPOSITE pin (audit order-dependence): one run must give both explicit wd_order outcomes of the tied "
        "same-tick watchdogs - the Dump-first context hold with its operator exits (wd_order dump first) and the "
        "FP-first N17 contrast (wd_order fp first). Under an ESPHome-like phase patch each watchdog draws its own "
        "random offset, so both wd_order runs realise the same order and the composite pin fails by construction "
        "(17 of 17 patched quick configurations); the Dump-first context-hold signature itself reproduces whenever "
        "the Dump watchdog's random offset is the smaller (the context hold with its exits held in 10 of those 17; "
        "V0.1 review probe, the triple (FW-03-c) and unreadable-data (FW-03-a / -b) constructions, both orders: "
        "setup-anchored seeds 1, 3, 4, 8 of 1-8, power-on-anchored seeds 1 and 3 of 1-3)"),
    "FW-03 order sweep: FP first with ORIGINAL 244 = 0": (
        "the FP-first order of the same-tick watchdog sweep is a phase on the device (see "
        "finding-reproduces:F-FW03-1) (fails under the phase patch at some seeds)"),
    "every finding in the table was reproduced exactly once in this run": (
        "aggregate of the finding pins: fails whenever a phase-sensitive pin (F-FW03-1 / F-FW03-2) does not reproduce"),
    "corpus FW-01-a: replay ok (": _PS_DIGEST,
    "corpus FW-01-b: replay ok (": _PS_DIGEST,
    "corpus FW-01-c: replay ok (": _PS_DIGEST,
    "corpus FW-01-d: replay ok (": _PS_DIGEST,
    "corpus FW-02-a: replay ok (": _PS_DIGEST,
    "corpus FW-02-b: replay ok (": _PS_DIGEST,
    "corpus FW-03-a: replay ok (": _PS_DIGEST,
    "corpus FW-03-b: replay ok (": _PS_DIGEST_EXP,
    "corpus FW-03-c: replay ok (": _PS_DIGEST,
    "EXT FW-03 watchdog phase sweep (de-aligned watchdogs)": (
        "extended sweep of the FW-03 watchdog order on the lab grid (de-aligned by phase_ms): which watchdog runs "
        "first after the boot is the phase (ESPHome: an independent random offset per watchdog per boot), and the "
        "sweep pins the outcome of each lab order (fails under the phase patch)"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = (
    "EXT FW-03 watchdog phase sweep (de-aligned watchdogs)",
)
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


import copy  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402

SUITE = "test_lab_fw_obligations"
U0_ISO = "2026-10-21T10:50:00Z"     # a synthetic Wednesday (BST); no site value
U0 = C.parse_iso_utc(U0_ISO)
RR = L.ds.Durable.MARKER_RESTORE_REQUIRED
FW_TEXT = L.fw_text()
ORIG = dict(L.SITE["original"])
CORPUS_DIR = HERE / "corpus"
FP_OVERRIDE = {"230": 58, "232": 1, "256": 3000, "261": 3000, "268": 100, "273": 100, "274": 1, "279": 1}
FP_OVERRIDE_ADDRS = [230, 232, 256, 261, 268, 273, 274, 279]
PRELUDE_S = 200                    # B5 completed-lease prelude run time (the corpus PB-01-a pattern: run_for(200))
PRELUDE_R244_TARGET = "Essentials"  # the reg244 prelude's Apply target: 1, unlike every ORIGINAL 244 used here (2 or 0)
# every scenario starts its 30 min leases after the warm-up (60 s) and the B5 prelude (PRELUDE_S): the FP end epoch is
# the START time + minutes * 60 (firmware :9092 'end_epoch = (uint32_t) now.timestamp + (minutes * 60U)')
FP_END = U0 + 60 + PRELUDE_S + 1800
STRAND_HORIZON_S = 6 * 3600        # F-FW01-2: the stranded override is still applied this long after the operator sweep
# the firmware invariants the corpus pins by exact seq-free summary (form 'summary'); named explicitly so that a later core
# invariant cannot silently change a recorded expectation (section [0] checks they are all registered in _lab_fw)
CORPUS_INVARIANTS = ["INV-WS", "INV-ONE-LEASE", "INV-NO-2ND-RESTORER", "INV-NO-RESUME", "INV-LOCKOUT-QUIET",
                     "INV-NO-SILENT-OVERRIDE", "INV-RESTORE-BOUND", "INV-BOOT-MIRROR"]
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

# =============================================================================================================================
# source anchors (text snippets; each must occur exactly once in its file - verified below; line numbers are info only)
# =============================================================================================================================
PATHS = {"fw": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
         "s4": "docs/architecture/fallback/design/S4_domains_decisions_final.md",
         "fcp2": "docs/dev/dump-to-grid-safety-fcp2.md",
         "safety": "SAFETY.md",
         "card": "frontend/ecco-energy-actions-card/README.md"}
ANCHORS = {
    "fp_phase_b": ["fw", "marker_committed = ecco_durable::commit_record(\n"
                         "                          ecco_durable::key_for(ecco_durable::FREE_POWER_VALID_TAG), marker);"],
    "dump_phase_b": ["fw", "bool marker_committed = data_committed && ecco_durable::commit_record(\n"
                           "                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), marker);"],
    "fp_start_dump_gate": ["fw", "// \"Free Power mutual exclusion\". This is purely an"],
    "dump_start_fp_gate": ["fw", "// Free Power owns 256-261 during its own lease and reads"],
    "pr41_mechanism": ["fw", "domain's admission gate before the next reboot."],
    "pr41_guard": ["fw", "            !id(free_power_recovery_metadata_corrupt) &&\n"
                         "            !id(dump_recovery_metadata_corrupt) &&\n"
                         "            id(free_power_marker_state) =="],
    "pr41_log": ["fw", "\"DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261) - Free Power and Dump-to-Grid both hold \""],
    "pr41_dump_status": ["fw", "\"RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)"],
    "pr41_reconcile": ["fw", "// must reconcile which one is genuine."],
    "pr41_fp_status_claim": ["fw", "reflect free_power_recovery_metadata_corrupt correctly."],
    "fp_status_corrupt": ["fw", "id(free_power_status).publish_state(\"RECOVERY BLOCKED - durable recovery marker exists "
                                "but its snapshot data cannot be trusted (unreadable or invalid); inverter writes locked\");"],
    "s4_guard": ["fw", "            !id(dump_recovery_metadata_corrupt) &&\n"
                       "            !id(reg244_recovery_metadata_corrupt) &&\n"
                       "            id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED &&\n"
                       "            id(reg244_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED"],
    "containment_seed": ["fw", "if (id(dump_snapshot_valid) && id(dump_recovery_metadata_corrupt)) {"],
    "sg02_trigger": ["fw", "# Free Power/Dump 256-261 dual obligation), every restore/recovery path"],
    "sg02_d5": ["fw", "#   3. D5: if this boot loaded a TRUSTED data record whose original 244"],
    "sg02_write": ["fw", "ESP_LOGW(\"dump_to_grid\", \"SG-02 containment: register 244 is Allow Export under a blocked Dump "
                         "recovery - writing literal 2 (Zero Export)\");"],
    "sg02_literal": ["fw", "values: !lambda 'return std::vector<uint16_t>{2};'"],
    "fp_wd_corrupt_gate": ["fw", "if (id(free_power_recovery_metadata_corrupt)) return false;"],
    "fp_wd_never_indefinite": ["fw", "never let Free Power run indefinitely"],
    "fp_restore_corrupt_gate": ["fw", "id(free_power_snapshot_valid) &&\n"
                                      "                !id(free_power_recovery_metadata_corrupt) &&\n"
                                      "                !id(free_power_operation_in_progress) &&"],
    "fp_start_reject_corrupt": ["fw", "if (id(free_power_recovery_metadata_corrupt)) id(free_power_status).publish_state("
                                      "\"REJECTED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data "
                                      "cannot be trusted (unreadable or invalid); deliberate recovery required\");"],
    "slot2_gate": ["fw", "return id(manual_config_write_enable).state &&\n"
                         "                     id(manual_slot2_staging_loaded) &&"],
    "dump_ecco_value": ["fw", "bool ecco_value = live == id(dump_target_power) || live == id(dump_evidence_pending_ceiling)"
                              " || live == floor_v;"],
    "fp_ctx_gate": ["fw", "return !id(free_power_write_failed) && id(free_power_restore_context_read_ok) &&\n"
                          "                      id(free_power_lease_context_reg244) >= 0 &&\n"
                          "                      id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);"],
    "fp_ctx_hold_text": ["fw", "snprintf(msg, sizeof(msg), \"RESTORE BLOCKED - register 244 context changed since this lease "
                               "started (%s)\", id(free_power_context_hold_reason).c_str());"],
    "pr41_r1_rule": ["fw", "// Invariant: only one authoritative recovery obligation may own"],
    "pr41_s4_republish_claim": ["fw", "(and may already have been republished by the S4 check, just"],
    "fp_wd_corrupt_rationale": ["fw", "// let the watchdog attempt a restore with zero/default values."],
    "fp_boot_ends_lease": ["fw", "ending and restoring on this boot rather than resuming the lease"],
    "fp_marker_unreadable_local": ["fw", "bool free_power_marker_unreadable = false;"],
    "fp_r4_wording_note": ["fw", "\"snapshot data is unreadable\" was not accurate for"],
    "s4_dump_status": ["fw", "\"RECOVERY BLOCKED - dual durable obligation (S4)"],
    "s4_r244_status_claim": ["fw", "// reg244_recovery_metadata_corrupt correctly."],
    "r244_status_corrupt": ["fw", "snapshot data is unreadable; inverter writes locked"],
    "sg02_d5_loaded": ["fw", "id(dump_snapshot_data_loaded) && id(dump_snapshot_reg244) == 0;"],
    "s4doc_dual_exit": ["s4", "Out-of-band NVS handling (never \"just reboot\"; rule c)"],
    "s4doc_cause_status_only": ["s4", "UNKNOWN vs CORRUPT and the cause exist only in locals and status text"],
    "s4doc_ghost_blind_spot": ["s4", "A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear) is invisible"],
    "s4doc_permanent": ["s4", "\"Permanent\" means that no assignment to false exists anywhere in the firmware."],
    "s4doc_r5_n16": ["s4", "Known residual: P0 does not check other domains' obligations (N16)."],
    "s4doc_n17_residual": ["s4", "Accepted residual; FB-D may add `!other_corrupt` terms."],
    "fcp2_residue_ok": ["fcp2", "ECCO residue at or below the original, such as the 500 W containment, only limits "
                                "discharge and stays acceptable."],
    "fcp2_ownership": ["fcp2", "the verified ceiling, the possibly-landed pending ceiling (the Dump V2 evidence) or the "
                               "containment value min(original, 500 W)"],
    "fcp2_repeat_noop": ["fcp2", "**A repeat run after a verified restore finds ORIGINAL and writes nothing.**"],
    "safety_settings_kept": ["safety", "the inverter keeps whatever settings were last written until they are restored"],
    "card_no_action": ["card", "**No actionable button at all** - a neutral explanation is shown instead; this will not "
                               "clear on its own"],
}

# =============================================================================================================================
# scenario and finding tables (specification; the checks below verify every claim that is marked VERIFIED)
# =============================================================================================================================
SCENARIOS = [
    {"id": "FW-01", "priority": "P1",
     "title": "Phase-B marker commit false negative (phantom), the OTHER domain's START admitted in the same runtime, "
              "reboot through the FULL on_boot: PR41 dual lockout, SG-02 containment, repeated reboots, 40+ watchdog "
              "ticks, operator surfaces",
     "ownership": "B5 prelude first: one completed 1-minute lease of the phantom's domain (verified restore, marker "
                  "CLEAR), so its marker key was stored earlier; (a) FP START whose RESTORE_REQUIRED marker lands but "
                  "commit_record returns False (durable RR, RAM "
                  "mirror CLEAR, nothing written), then a genuine Dump lease (writes 256-261 = 1000, 244 = 0); (b) Dump "
                  "START with the same false negative (durable RR, nothing written), then a genuine ACTIVE FP lease "
                  "(232, 230, 256-261, 268-279); synthetic ORIGINAL 244 = 2 (and 244 = 0 for the SG-02 variant); the "
                  "owner does nothing else",
     "anchors": ["fp_phase_b", "dump_phase_b", "fp_start_dump_gate", "dump_start_fp_gate", "pr41_mechanism", "pr41_guard",
                 "pr41_r1_rule", "pr41_log", "pr41_dump_status", "pr41_reconcile", "containment_seed", "sg02_trigger",
                 "sg02_d5", "sg02_write", "fp_wd_corrupt_gate", "fp_wd_corrupt_rationale", "fp_wd_never_indefinite",
                 "fp_boot_ends_lease", "fp_restore_corrupt_gate", "fp_start_reject_corrupt", "pr41_fp_status_claim",
                 "fp_status_corrupt", "fp_marker_unreadable_local", "s4doc_dual_exit", "s4doc_permanent",
                 "s4doc_ghost_blind_spot", "s4doc_cause_status_only", "fcp2_residue_ok", "safety_settings_kept",
                 "card_no_action"],
     "invariant": "INV-LOCKOUT-QUIET (holds: only the SG-02 literal 244 = 2 is written under the dual lockout); also "
                  "INV-NO-RESUME / INV-WS / INV-ONE-LEASE / INV-BOOT-MIRROR hold; INV-NO-2ND-RESTORER (the firmware's "
                  "own R1 rule pr41_r1_rule) is violated by the admitted START's 256-261 writes (F-FW01-1); "
                  "INV-RESTORE-BOUND holds only through its lockout clause (F-FW01-2); scenario-local INV-STATUS-CAUSE "
                  "(an operator-facing lockout text names its cause) is violated by the FP status (F-FW01-3)",
     "failure_outcome": "a write to a corrupt-locked domain's registers other than 244 = 2; or (finding) a live FP "
                        "override that no in-firmware path ends and no time bound limits (documented out-of-band exit "
                        "only); or a lockout text that names the wrong cause",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "classification_note": "FINDING-NEW because of F-FW01-2 (the stranded-override consequence, cost / availability "
                            "medium) and F-FW01-3 (diagnostics, low); its root-cause finding F-FW01-1 is "
                            "FINDING-KNOWN:PR41-GHOST",
     "findings": ["F-FW01-1", "F-FW01-2", "F-FW01-3"], "corpus": ["FW-01-a", "FW-01-b", "FW-01-c", "FW-01-d"]},
    {"id": "FW-02", "priority": "P2",
     "title": "Phantom obligation (FP, then Dump) plus an owner manual TOU slot apply (real Load + Apply) in the same "
              "runtime, then reboot: restore classification / operator lockout",
     "ownership": "B5 prelude first (one completed 1-minute lease of the phantom's domain, marker CLEAR); a phantom FP "
                  "or Dump RESTORE_REQUIRED marker (Phase-B false negative, nothing written); the owner then "
                  "applies one manual TOU slot (slot 2: SOC 55, or power 1000 / 500 / 4000, or a start time) through the "
                  "real buttons; the owner's applied values are the owner's intent (lab ORIGINAL follows them)",
     "anchors": ["slot2_gate", "fp_phase_b", "dump_phase_b", "dump_ecco_value", "fcp2_ownership", "fcp2_repeat_noop",
                 "s4doc_ghost_blind_spot"],
     "invariant": "INV-NO-SILENT-OVERRIDE (the next boot's restore never silently replaces the owner's applied value); "
                  "INV-NO-2ND-RESTORER records the admitted manual write (a lab label: the manual writer is not a "
                  "restorer, but it writes 256-261 while the other domain holds a durable RESTORE_REQUIRED)",
     "failure_outcome": "after the reboot a restore rewrites the owner's slot value to the stale snapshot ORIGINAL and "
                        "reports RESTORED OK with the marker cleared (no visible obligation)",
     "classification": "FINDING-KNOWN:N15", "grade": "VERIFIED", "confidence": "high",
     "classification_note": "both findings map to N15 (ghost marker, a later P4 write, stale ORIGINAL at the next boot); "
                            "one root cause, counted once as F-FW02-2 (F-FW02-1 is its fail-closed FP sibling); the "
                            "ghost itself is F-FW01-1 (PR41-GHOST)",
     "findings": ["F-FW02-1", "F-FW02-2"], "corpus": ["FW-02-a", "FW-02-b"]},
    {"id": "FW-03", "priority": "P2",
     "title": "Multi-obligation boot order: FP + Dump + reg244 RESTORE_REQUIRED readable (S4 before PR41) and FP RR + "
              "Dump unreadable data; same-tick watchdog order sweep with SG-02 containment vs the FP register-244 lease "
              "context gate",
     "ownership": "B5 prelude first (the owner's reg244 Apply then Restore, and one completed 1-minute Dump lease, "
                  "both markers CLEAR; the unreadable-data case: the Dump lease only); "
                  "phantom reg244 and Dump markers (Phase-B false negatives, nothing written) plus a genuine ACTIVE FP "
                  "lease; or a phantom Dump marker plus an ACTIVE FP lease and a Dump data record unreadable at the "
                  "next boot; synthetic ORIGINAL 244 = 2 and the variant 244 = 0 (the owner's own Allow Export, which "
                  "is then also the FP lease context)",
     "anchors": ["s4_guard", "pr41_guard", "pr41_s4_republish_claim", "fp_ctx_gate", "fp_ctx_hold_text",
                 "containment_seed", "sg02_d5", "sg02_d5_loaded", "sg02_write", "s4_dump_status", "s4_r244_status_claim",
                 "r244_status_corrupt", "fp_r4_wording_note", "s4doc_r5_n16", "s4doc_n17_residual",
                 "s4doc_cause_status_only", "fcp2_repeat_noop"],
     "invariant": "INV-NO-2ND-RESTORER / INV-LOCKOUT-QUIET (violated: FP's automatic restore writes 256-261 over the "
                  "corrupt-locked Dump obligation, known N17); INV-RESTORE-BOUND (FP restore held by the 244 context "
                  "gate after containment ran first, explained by the operator lockout); INV-BOOT-MIRROR holds; "
                  "scenario-local INV-STATUS-CAUSE (violated by the reg244 result text under S4, F-FW03-3)",
     "failure_outcome": "FP writes the shared 256-261 while Dump still holds a durable RESTORE_REQUIRED obligation; or, "
                        "with the other watchdog order, FP's override stays live behind an operator lockout; or the "
                        "reg244 lockout text names the wrong cause",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "classification_note": "FINDING-NEW because of F-FW03-3 (diagnostics, low; added after the verification pass, "
                            "the sibling one independent check read in the source); its control findings are FINDING-KNOWN:N17 "
                            "(F-FW03-1) and FINDING-KNOWN:N16 (F-FW03-2); counted here: F-FW03-2 only (F-FW03-1 is "
                            "DUPLICATE of F-FW05-2, the lab's N17 owner; F-FW03-3 is DUPLICATE of F-FW01-3, same root)",
     "findings": ["F-FW03-1", "F-FW03-2", "F-FW03-3"], "corpus": ["FW-03-a", "FW-03-b", "FW-03-c"]},
]

FALSE_NEG_REACH = ("a Phase-B marker false negative, whose only physical route is the marker's own nvs_set_blob error "
                   "after the write (ESP_ERR_NVS_REMOVE_FAILED semantics, REPORTED; it needs an earlier stored version "
                   "of the marker key, i.e. an earlier lease of that domain - modelled by the B5 completed-lease "
                   "prelude; only one ESP-IDF fault cell is modelled); the firmware's 'unrelated pending "
                   "key' route cannot reach the FP / Dump / reg244 marker commits, because ESPHome 2026.8.2 sync() "
                   "clears its queue and the data commit's sync runs just before in the same lambda; rate UNKNOWN, "
                   "likely very low")
FINDINGS = [
    {"fid": "F-FW01-1", "scenario": "FW-01", "classification": "FINDING-KNOWN:PR41-GHOST", "grade": "VERIFIED",
     "confidence": "high (mechanism, and the registry fit: PR41-GHOST is S4 decisions section 2.10 blind spot 1 plus the "
                   "firmware's PR41 on_boot comment)",
     "root": "PR41-GHOST: a Phase-B marker commit false negative leaves a durable RESTORE_REQUIRED with the RAM mirror "
             "clear, so the OTHER domain's START gate is defeated until the next reboot",
     "duplicate_of": None,
     "xref": ["F-FW01-2", "F-FW02-1", "F-FW02-2", "F-FW03-1", "F-FW03-2", "F-FW03-3", "F-FW05-1", "F-PB01-1",
              "F-HF07-4"],
     "severity": "availability / cost precondition (low-medium): breaks the firmware's own R1 single-owner rule in the "
                 "same runtime, but nothing is written in an unsafe direction until a third event",
     "title": "A Phase-B marker false negative leaves a phantom RESTORE_REQUIRED that every other domain's admission gate "
              "and Home Assistant's snapshot sensors miss: the other domain's START is admitted in the same runtime",
     "mechanism": "START Phase B (fp_phase_b / dump_phase_b) sets the RAM mirror only when both commits return true; a "
                  "false negative leaves *_snapshot_valid false with the durable marker RESTORE_REQUIRED; the other "
                  "START's gate reads only the RAM mirror (fp_start_dump_gate / dump_start_fp_gate) and is admitted; "
                  "only its 256-261 writes are INV-NO-2ND-RESTORER violations (the Dump 244 = 0 write and FP's 232 / "
                  "230 / 268-279 writes are outside that invariant); the HA view (snapshot_valid / active sensors) "
                  "shows no obligation; the firmware's PR41 comment describes exactly this (pr41_mechanism) and relies "
                  "on the next boot's arbitration",
     "reachability": "trigger: nvs false_negative on a used Phase-B marker (fp.valid; dump.valid in the mirror order); "
                     "device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED: " + FALSE_NEG_REACH + "; then any second START before a reboot (owner, or an HA "
                     "FPS1 / DGS1 schedule that sees no snapshot)",
     "repair_scope": "the two START scripts only: when the Phase-B marker commit returns false after the data record "
                     "committed, keep the RAM mirror fail-closed (fill it exactly as the success branch does: "
                     "snapshot_valid, marker_state RESTORE_REQUIRED, end epoch and intended targets, restore_requested) "
                     "so the domain's own watchdog performs the existing verified no-op restore and commits CLEAR (a true "
                     "negative is then also harmless); no new write path, every gate stricter; PR41 / S4 stay as the "
                     "boot backstop; the reg244 Apply's analogous Phase B is a separate optional item (N10 / S4)",
     "notes": "RECLASSIFIED in the hardening pass from FINDING-KNOWN:N15 (then the closest registered id; both "
              "independent checks had confirmed it) to FINDING-KNOWN:PR41-GHOST, the registry id added for exactly this "
              "documented limit: its anchor is S4 decisions section 2.10 blind spot 1 (s4doc_ghost_blind_spot), its "
              "second references the firmware's on_boot PR41 comment (pr41_mechanism; _lab_trace KNOWN_RISK_REFS), which "
              "documents the same-runtime admission; N15 stays the class of the later-P4-write consequence (F-FW02-*); "
              "this is the ROOT CAUSE of F-FW01-2, F-FW02-* and F-FW03-* (their precondition), counted once here; the "
              "re-verifications in other suites point here: F-FW05-1 (test_lab_fw_durability), F-PB01-1 "
              "(test_lab_property), F-HF07-4 (test_lab_ha_phantom, coupled tier); severity lowered from 'safety "
              "(precondition)' after the independent classification check (the failed START wrote nothing, so the "
              "phantom ORIGINAL equals live state)"},
    {"fid": "F-FW01-2", "scenario": "FW-01", "classification": "FINDING-NEW", "grade": "VERIFIED",
     "confidence": "high (mechanism, reproduced on the real on_boot / watchdogs / operator scripts); the classification is "
                   "scoped to the CONSEQUENCE (its root cause PR41-GHOST is documented, F-FW01-1)",
     "root": "consequence of the PR41 dual lockout (DUAL_FP_DUMP) over a genuine live FP lease: no in-firmware exit and no "
             "time bound for the stranded override",
     "duplicate_of": None,
     "xref": ["F-FW01-1", "F-FW01-3", "F-HF07-1", "F-HF07-2"],
     "severity": "cost / availability MEDIUM; safety LOW: a normal FP override (grid charge to 100 % SOC, then the battery "
                 "is held full and house load comes from the grid) stays applied past its end epoch with no in-firmware "
                 "exit and no time bound, until the owner acts out of band; visible (RECOVERY BLOCKED), restrictive on "
                 "export",
     "title": "Dump phantom + genuine ACTIVE Free Power lease + a reboot inside it: under the PR41 dual lockout the live FP "
              "override (grid charge, 58 A, all six slots 100 % SOC / grid source, 256-261 = 3000) stays applied past its "
              "end epoch with no in-firmware exit and no time bound (every operator surface refuses; still applied 6 h "
              "later); only out-of-band handling ends it",
     "mechanism": "boot re-derives both RR markers; PR41 (pr41_guard) sets both corrupt flags; the FP watchdog and "
                  "restore stop at the corrupt gate (fp_wd_corrupt_gate, fp_restore_corrupt_gate), whose stated "
                  "rationale (fp_wd_corrupt_rationale: no restore 'with zero/default values') does not fit "
                  "DUAL_FP_DUMP, where the FP data record loaded; the lease that the boot converts into a restore "
                  "(fp_boot_ends_lease) is therefore never restored; FP START / End / Force / Accept / Review, Dump "
                  "START / End / Force / Accept and manual slot applies all refuse; no "
                  "'*_recovery_metadata_corrupt) = false' exists (s4doc_permanent), so neither a watchdog tick, a "
                  "reboot nor elapsed time ends it; the Dump obligation that causes it never wrote a register",
     "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker (dump.valid), then a reboot inside "
                     "the admitted Free Power lease; device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED (needs a hardware commit false negative, unproven): " + FALSE_NEG_REACH + " (on the Dump "
                     "marker); an FP START in the same runtime (owner or the FPS1 schedule, plausible after 'START "
                     "FAILED ... nothing written'); and a reboot inside the FP lease (power cut, OTA, restart "
                     "escalation); a reboot after the lease ended strands nothing (extended contrast)",
     "repair_scope": "options only (described, never implemented; any firmware change needs owner design review): "
                     "(1) diagnostics + procedure, no control change: an operator-visible LOCKED alert that names the "
                     "explicit cause (DUAL_FP_DUMP, the S4 decisions' planned lockout cause; see F-FW01-3) and the "
                     "stranded live override, plus a documented out-of-band exit procedure (restore the inverter from "
                     "the owner's own record, then out-of-band NVS handling, s4doc_dual_exit) in S4 decisions section 5 "
                     "/ SAFETY; (2) a bounded, restrictive-direction automatic exit for a domain whose OWN lease has "
                     "expired (e.g. after the FP end epoch, at most one verified FP restore of its own trusted ORIGINAL, "
                     "never an export-raising write, the other domain kept locked) - this opens a write path under a "
                     "lockout that S4 limits to out-of-band handling and trades against R1 / N17 (identical ORIGINALs do "
                     "not prove the other side never wrote), so it is an owner design decision; removing the trigger is "
                     "F-FW01-1's scope (fail-closed RAM mirror on a Phase-B false return: the FP START is then refused "
                     "and this state is unreachable)",
     "notes": "RECLASSIFIED in the hardening pass from FINDING-KNOWN:N15 (the closest id then) to FINDING-NEW, scoped to "
              "the CONSEQUENCE: the root cause PR41-GHOST is documented (pr41_mechanism, s4doc_ghost_blind_spot; "
              "F-FW01-1, which counts it), and the lockout, its permanence and its out-of-band exit are by design "
              "(pr41_reconcile, s4doc_permanent, S4 'Out-of-band NVS handling' s4doc_dual_exit), the card offers no "
              "action (card_no_action) and the inverter keeps the last-written settings (safety_settings_kept); NOT "
              "stated anywhere as an accepted consequence: a genuine live override stranded past its end epoch, with "
              "no in-firmware exit or time bound (KNOWN_RISKS has no id for it: N10 is FP / R244, N15 a ghost "
              "stale-ORIGINAL restore); the earlier source-fidelity check already preferred FINDING-NEW (scoped); 'never let "
              "Free Power run indefinitely' (fp_wd_never_indefinite) is the NTP-grace fallback's intent, not a general "
              "invariant; with ORIGINAL 244 = 0 SG-02 also switches the owner's Allow Export to Zero Export (FW-01-c, "
              "by design); the HA-side views of the held override are F-HF07-1 / F-HF07-2 (test_lab_ha_phantom)"},
    {"fid": "F-FW01-3", "scenario": "FW-01", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "root": "a dual-lockout branch (PR41 or S4) republishes only dump_status and the lockout cause is not retained, so "
             "the partner domain's status block prints its generic corrupt text (two sites: PR41 / Free Power, "
             "F-FW01-3; S4 / reg244, F-FW03-3)",
     "duplicate_of": None,
     "xref": ["F-FW03-3", "F-FW01-2", "F-HF07-5"],
     "severity": "diagnostics (low): the lockout itself is reported correctly; only its stated cause is wrong, which "
                 "points the operator at NVS data repair instead of reconciling two obligations",
     "title": "Under the PR41 dual lockout the Free Power status names the wrong cause ('snapshot data cannot be "
              "trusted (unreadable or invalid)') although its data record loaded fine; the dual-obligation text in "
              "dump_status lasts only until a Dump START / Accept / End press; Review refuses as 'metadata'",
     "mechanism": "PR41 republishes only dump_status; its comment (pr41_fp_status_claim) relies on the FP status block, "
                  "whose corrupt branch has one generic text (fp_status_corrupt) and no dual-obligation case; PR41 "
                  "fires only when the FP marker and data record loaded and validated, so every PR41 lockout publishes "
                  "the wrong FP cause; any Dump START / Accept / End press then republishes dump_status with the "
                  "generic text, after which no HA-visible text names the cause (only the boot ESP_LOGE); the lockout "
                  "cause is not retained (s4doc_cause_status_only)",
     "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker (dump.valid), then a reboot (the PR41 "
                     "lockout precondition); device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED for the precondition (F-FW01-1 / F-FW01-2); given a PR41 lockout the wrong text is "
                     "certain (it follows from the on_boot structure)",
     "repair_scope": "status text only, no control change: a lambda-local flag set in the PR41 branch (the "
                     "fp_marker_unreadable_local pattern) and a dual-obligation sub-branch in the FP status block's "
                     "corrupt case; a free_power_status publish inside the PR41 branch alone does NOT work (the FP "
                     "status block runs later in the same lambda and overwrites it - shown by the repair-scope check "
                     "below); the runtime refusals (FP End / START / Force / Accept) rebuild their text from the bare "
                     "corrupt flag, so a complete fix needs a RAM cause global they read (the S4 decisions' planned "
                     "fp_lockout_cause = DUAL_FP_DUMP); texts within the HB1 240-character limit; one repair item for "
                     "both dual-lockout sites: the same pattern in the S4 branch and the reg244 status block (or the "
                     "planned reg244_lockout_cause), F-FW03-3",
     "notes": "both independent checks confirmed FINDING-NEW: S4 decisions row 'UNKNOWN vs CORRUPT and the cause exist only in "
              "locals and status text' plans cause retention but does not document the wrong FP text; repair scope "
              "corrected after verification (the original 'republish in the PR41 branch' would be overwritten); the "
              "S4 sibling F-FW03-3 has the same root cause and repair item and is counted here (once); the HA-reachable "
              "extension is F-HF07-5 (test_lab_ha_phantom)"},
    {"fid": "F-FW02-1", "scenario": "FW-02", "classification": "FINDING-KNOWN:N15", "grade": "VERIFIED",
     "root": "N15: a ghost marker (PR41-GHOST) plus a later P4 write, so the next boot restores from a stale ORIGINAL "
             "record (no final-writer latch)",
     "duplicate_of": "F-FW02-2",
     "relation": "same root cause and repair as F-FW02-2 (N15, this suite): here FP's classifier fails closed, so the "
                 "N15 stale-ORIGINAL overwrite itself does not happen; counted once as F-FW02-2",
     "xref": ["F-FW02-2", "F-FW01-1", "F-FW05-1"],
     "confidence": "high", "severity": "availability (low): fail-closed with zero automatic writes, the owner's value "
                                       "stays; FP stays locked until an operator Accept or Force",
     "title": "FP phantom + an owner manual slot apply in the same runtime: the apply is admitted; after a reboot FP's "
              "classifier finds NEITHER and locks out (OPERATOR DECISION REQUIRED), zero writes; Accept keeps the "
              "owner's value, Force (operator-authorised, after Review) reverts it to the stale snapshot",
     "mechanism": "the slot Apply gate (slot2_gate) reads only RAM mirrors; the phantom's durable FP record still holds "
                  "the pre-apply ORIGINAL; the boot restores the FP obligation and its classifier sees an owner change "
                  "in FP's registers (neither ORIGINAL nor INTENDED), so it keeps the marker, sets operator_needed and "
                  "writes nothing",
     "reachability": "trigger: nvs false_negative on the used Free Power Phase-B marker (fp.valid), an owner apply, "
                     "then a reboot; device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED: " + FALSE_NEG_REACH + "; then any edit to FP-owned registers (232, 230, 256-261, "
                     "268-279) before a reboot - the manual TOU path, the HA ACS0 target-SOC path (its refusal chain "
                     "reads the same RAM-mirror sensor; not executed here), or an edit from outside ECCO",
     "repair_scope": "root cause as F-FW01-1 (no phantom in RAM; it also cuts the phantom's life to one watchdog "
                     "cycle); the fail-closed classifier needs no change",
     "notes": "both independent checks confirmed KNOWN:N15 (N15: 'a later P4/P5 can overwrite'); the observed outcome is milder "
              "than N15's stated consequence because FP's classifier fails closed; 'owner intent' dropped from the "
              "severity after verification (Force is an operator-authorised exit, Accept keeps the owner's value); "
              "hardening: kept FINDING-KNOWN:N15 (ghost + a later P4 write matches the N15 row), printed as DUPLICATE "
              "of F-FW02-2 (one N15 root cause, counted once); F-FW05-1 (test_lab_fw_durability) observed the same "
              "fail-closed outcome after an owner change"},
    {"fid": "F-FW02-2", "scenario": "FW-02", "classification": "FINDING-KNOWN:N15", "grade": "VERIFIED",
     "root": "N15: a ghost marker (PR41-GHOST) plus a later P4 write, so the next boot restores from a stale ORIGINAL "
             "record (no final-writer latch)",
     "duplicate_of": None,
     "xref": ["F-FW02-1", "F-FW01-1"],
     "confidence": "high", "severity": "owner intent / cost (low), with a diagnostics part (a misleading 'RESTORED "
                                       "OK'): one slot's lower cap reverts to the owner's own earlier 8000 W",
     "title": "Dump phantom + an owner slot power equal to a value the Dump V2 evidence counts as ECCO's (the phantom's "
              "never-applied feed-forward START ceiling, 1000 W under the lab's synthetic telemetry, or the 500 W "
              "floor): after a reboot the Dump restore silently writes the stale ORIGINAL back, reports RESTORED OK "
              "and clears the marker",
     "mechanism": "the phantom Dump data record carries the intended / pending ceiling (the feed-forward START "
                  "ceiling: round(house + export target - PV), clamped between the controller minimum and the start "
                  "cap) although nothing was written; the restore pre-read classifies a slot as ECCO-owned when it "
                  "equals target / pending / floor (dump_ecco_value, the fcp2 ownership table fcp2_ownership); the "
                  "owner's coinciding value is indistinguishable, so the single six-register ORIGINAL write (only 257 "
                  "changes value) runs, verifies and commits CLEAR",
     "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker (dump.valid), an owner write equal to "
                     "an ECCO value (the phantom ceiling or the 500 W floor), then a reboot; device reachability: "
                     "UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED: " + FALSE_NEG_REACH + " (on the Dump marker); then an owner change (firmware Apply, "
                     "the inverter app or the front panel) to exactly the phantom's ceiling or the 500 W floor before "
                     "a reboot, with no successful Dump START retry in between (a retry replaces the phantom)",
     "repair_scope": "root cause as F-FW01-1 (no phantom outlives its runtime; the existing restore then finds ORIGINAL "
                     "and writes nothing, fcp2_repeat_noop); the classifier must NOT change (treating the floor or "
                     "pending value as FOREIGN would weaken recognition of the containment residue); optional "
                     "documentation: an fcp2 limit line that an external change equal to ECCO's ceiling, pending value "
                     "or 500 W floor is taken as ECCO's",
     "notes": "both independent checks confirmed KNOWN:N15; severity lowered from medium (bounded, reversible revert to the "
              "owner's own earlier configuration; 244 back at its ORIGINAL); the coincidence set follows the "
              "phantom's telemetry-dependent ceiling (checked: synthetic house 430 / PV 120 gives 1300, then owner "
              "1300 is silent and owner 1000 FOREIGN); anchor moved from the fcp2 Accept-residue text to the fcp2 "
              "ownership table; MODEL: the lab ORIGINAL follows the owner's landed apply; hardening: kept "
              "FINDING-KNOWN:N15 (the exact N15 consequence: a stale-ORIGINAL restore that undoes a later P4 write); the "
              "suite's N15 owner (F-FW02-1 is its fail-closed FP sibling); the ghost precondition is F-FW01-1"},
    {"fid": "F-FW03-1", "scenario": "FW-03", "classification": "FINDING-KNOWN:N17", "grade": "VERIFIED",
     "confidence": "high (mechanism and classification); reachability low, rate UNKNOWN",
     "root": "N17: P1 restores carry no cross-domain terms; with the other domain corrupt / UNKNOWN at boot (PR41 "
             "skipped) a trusted restore writes the shared 256-261 over its unresolved obligation",
     "duplicate_of": "F-FW05-2",
     "relation": "same root cause as F-FW05-2 (test_lab_fw_durability, the lab's N17 owner: its variant C is this "
                 "suite's unreadable-Dump-data construction, plus the mirror and the UNKNOWN form; test_lab_property's "
                 "F-PB01-2 also names F-FW05-2); this suite adds a second route into the same residual (the triple "
                 "obligation, S4 evaluated before PR41) and keeps both reproductions",
     "xref": ["F-FW05-2", "F-PB01-2", "F-FW03-2", "F-FW01-1"],
     "severity": "safety-rule (low): an R1 breach in a documented accepted residual; the value written is FP's own "
                 "verified pre-lease ORIGINAL (in both constructions equal to the phantom's, which never wrote); "
                 "availability by design (Dump / reg244 stay fail-closed)",
     "title": "Triple obligation (FP + Dump + reg244 RR readable): S4 runs first and corrupt-locks Dump, PR41's "
              "'!dump corrupt' guard then skips, and FP's automatic restore writes 256-261 over Dump's still-open "
              "obligation; same for FP RR + Dump unreadable data",
     "mechanism": "s4_guard fires (Dump + reg244 RR), so pr41_guard's '!id(dump_recovery_metadata_corrupt)' is false; FP "
                  "stays trusted and its P1 restore has no other-domain term; it restores the FP ORIGINAL and clears "
                  "the FP marker; in the triple Dump and reg244 stay locked on every boot (S4 re-fires); with an "
                  "unreadable Dump data record the lock lasts only while the fault persists: the next clean boot "
                  "trusts Dump, whose restore finds 256-261 at its ORIGINAL and writes nothing (checked below)",
     "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker (and on reg244 in the triple form) "
                     "plus a boot read_error on the stored Dump data record; device reachability: UNKNOWN pending the "
                     "ESP-IDF host NVS test. "
                     "INFERRED: two Phase-B false negatives (reg244 and Dump) plus an FP START in one runtime and a "
                     "reboot inside the lease, or one Dump false negative, an FP START, a reboot inside the lease and a "
                     "Dump data read error at that boot (" + FALSE_NEG_REACH + ")",
     "repair_scope": "documented accepted residual (N17, s4doc_n17_residual); the root-cause repair is F-FW01-1's "
                     "(neither construction is then reachable); an '!other_corrupt' term on FP's restore alone is NOT a "
                     "safe standalone change: it strands the live FP override (mutant NC-FW03-2 shows the same "
                     "trade-off for PR41 without its guard), so any such term is FB-D work with an operator exit",
     "notes": "both independent checks confirmed KNOWN:N17 (severity lowered from 'safety (medium)'); the triple case is an "
              "evaluation-order effect (S4 before PR41) covered by N17's generic 'other domain corrupt/unknown' "
              "wording; comment nit (diagnostics, no new id): the PR41 comment pr41_s4_republish_claim says "
              "dump_status may already have been republished by S4 'if that ALSO independently fired', which the "
              "'!dump corrupt' guard makes impossible; hardening: classification unchanged, printed as DUPLICATE of "
              "F-FW05-2 (one N17 root cause across the lab, counted by its owner); the triple route is corpus-pinned "
              "now (FW-03-c, the core r244_apply action)"},
    {"fid": "F-FW03-2", "scenario": "FW-03", "classification": "FINDING-KNOWN:N16", "grade": "VERIFIED",
     "confidence": "high (mechanism); reachability low, rate UNKNOWN",
     "root": "N16 / R5: the SG-02 containment (P0) gate has no other-domain obligation term, so it overlays the FP "
             "lease's register-244 context",
     "duplicate_of": None,
     "xref": ["F-FW03-1", "F-FW05-2", "F-FW01-1"],
     "severity": "availability / cost (low): restrictive direction (Zero Export; a non-exporting grid-charge override), "
                 "alarmed ('OPERATOR DECISION REQUIRED'), with an in-band Force exit",
     "title": "Watchdog order decides the outcome when the FP lease context is 244 = 0: Dump first -> SG-02 writes 244 "
              ":= 2, FP's restore then hits its register-244 context gate and the FP override stays live behind "
              "OPERATOR DECISION REQUIRED (Force resolves, Accept refuses); FP first -> FP restores (N17)",
     "mechanism": "containment's gate has no FP obligation term (containment_seed, sg02_write); in the triple, D5 does "
                  "not apply because FP rewrote 256-261, with unreadable Dump data because no trusted record loaded "
                  "(sg02_d5_loaded); the FP restore refuses unless live 244 equals its lease context (fp_ctx_gate / "
                  "fp_ctx_hold_text); whichever watchdog takes the write mutex first after the boot decides",
     "reachability": "trigger: nvs false_negative on the used Dump Phase-B marker (and on reg244 in the suite's triple "
                     "form) plus a boot read_error on the stored Dump data record; device reachability: UNKNOWN pending "
                     "the ESP-IDF host NVS test. "
                     "INFERRED: F-FW03-1's construction with the owner's own Allow Export (244 = 0) as ORIGINAL; on "
                     "hardware the two watchdogs' first runs get independent random offsets (ESPHome 2026.8.2 "
                     "scheduler), so the order is random per boot and BOTH outcomes are reachable; the lab's tie is an "
                     "artefact, its phase sweep the realistic model",
     "repair_scope": "root cause as F-FW01-1 (the dual-obligation construction becomes unreachable; admission only, no "
                     "write path); optionally a diagnostics-only change: the FP context-hold text names ECCO's own "
                     "SG-02 containment as the 244 writer when containment wrote; NOT the originally proposed SG-02 "
                     "deferral while a trusted FP restore is due - it can defer P0 without bound (FP operator_needed, "
                     "comms backoff), against R5 (s4doc_r5_n16), and would leave an unproven 244 = 0 uncontained; any "
                     "sequencing of SG-02 after FP must be bounded (never while FP operator_needed, at most one "
                     "terminal FP attempt or a fixed timeout) and is an owner decision that trades against N17",
     "notes": "both independent checks confirmed KNOWN:N16 (R5 generalises N16: 'P0 does not check other domains' "
              "obligations'); the FP-first branch and the Force exit are N17; severity lowered from medium; "
              "reachability and repair scope corrected after verification (ESPHome interval offsets read offline; "
              "the original deferral proposal weakened P0)"},
    {"fid": "F-FW03-3", "scenario": "FW-03", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "root": "a dual-lockout branch (PR41 or S4) republishes only dump_status and the lockout cause is not retained, so "
             "the partner domain's status block prints its generic corrupt text (two sites: PR41 / Free Power, "
             "F-FW01-3; S4 / reg244, F-FW03-3)",
     "duplicate_of": "F-FW01-3",
     "relation": "same root cause and repair item as F-FW01-3 (this suite): its second site (S4 / reg244); counted once "
                 "as F-FW01-3, whose repair scope covers both dual lockouts",
     "xref": ["F-FW01-3", "F-HF07-5"],
     "severity": "diagnostics (low): the S4 lockout itself is reported correctly; the reg244 result names the wrong cause",
     "title": "Under the S4 dual lockout (Dump + reg244) the reg244 result text says 'snapshot data is unreadable' "
              "although the reg244 data record loaded; only dump_status names S4 (sibling of F-FW01-3)",
     "mechanism": "the S4 branch republishes only dump_status (s4_dump_status); its comment (s4_r244_status_claim) "
                  "relies on the reg244 status block, whose corrupt branch has one generic text (r244_status_corrupt), "
                  "the 'unreadable' wording the firmware already corrected for FP in another case (fp_r4_wording_note); "
                  "S4 fires only when the reg244 marker and data record loaded (the boot's fw.load events report ok, "
                  "reg244_snapshot_value holds the record's original), so every S4 lockout publishes the wrong reg244 "
                  "cause",
     "reachability": "trigger: nvs false_negative on the used reg244 and Dump Phase-B markers; device reachability: "
                     "UNKNOWN pending the ESP-IDF host NVS test. "
                     "INFERRED: two Phase-B false negatives (reg244 and Dump) in one runtime (" + FALSE_NEG_REACH +
                     "); given an S4 lockout the wrong text is certain",
     "repair_scope": "status text only, no control change: the same pattern as F-FW01-3 - a lambda-local flag set in "
                     "the S4 branch and an S4 sub-branch in the reg244 status block's corrupt case (or the planned "
                     "reg244_lockout_cause RAM global read by the runtime refusal texts); any repair should cover both "
                     "dual lockouts",
     "notes": "added after the verification pass (the F-FW01-3 independent checks read this sibling in the source only; it is "
              "reproduced here on the real on_boot); no independent verification of this entry yet; searched docs/, "
              "SAFETY.md, ARCHITECTURE.md, docs/dev/advanced-config/write-surface.md (lists reg244 result texts, not "
              "this one), the S4 decisions (plans reg244_lockout_cause, s4doc_cause_status_only) and KNOWN_RISKS: "
              "not documented; hardening: classification unchanged, printed as DUPLICATE of F-FW01-3 (one root cause, "
              "one repair item, counted once); now corpus-pinned (FW-03-c, the core r244_apply action)"},
]
# the other suites' finding ids this table names (owner / xref); section [0] verifies each occurs in that suite's file
# (read as text, never imported)
EXTERNAL_FINDINGS = {"F-FW05-1": "test_lab_fw_durability.py", "F-FW05-2": "test_lab_fw_durability.py",
                     "F-PB01-1": "test_lab_property.py", "F-PB01-2": "test_lab_property.py",
                     "F-HF07-1": "test_lab_ha_phantom.py", "F-HF07-2": "test_lab_ha_phantom.py",
                     "F-HF07-4": "test_lab_ha_phantom.py", "F-HF07-5": "test_lab_ha_phantom.py"}

# =============================================================================================================================
# minimal replay corpus (drafts; the files under corpus/ are T.record() of these - the suite verifies both agree and
# replays every file). Only registered 'firmware' tier actions / observers; synthetic values only.
# =============================================================================================================================
CORPUS_COMMON = {"schema": "ecco-assurance-lab-replay/v0", "tier": "firmware", "seed": 1,
                 "utc_start": "2026-10-21T10:50:00Z", "synthetic": True, "grade": "VERIFIED"}
B5_EPOCH_NOTE = ("; the FP START is therefore at +260 s and its end epoch 1792581860 (START + 30 min, firmware :9092) "
                 "instead of 1792581660")


def _b5_note(dom: str, extra: str = "") -> str:
    """The B5 used-key prelude sentence appended to a corpus draft's notes (V0.1, brief B5 change 2)."""
    return ("; B5 (V0.1 used-key prelude): first a completed " + dom + " lease (+60 s, 1 minute, ended by its own watchdog "
            "with a verified restore that commits the marker CLEAR; run_for 200 s), so the injected marker key was stored "
            "earlier in the run (the only physical false-negative route, ESP_ERR_NVS_REMOVE_FAILED, needs an earlier "
            "version; the core refuses a fault on a never-stored key); the scenario's own actions moved from +60 s to "
            "+260 s" + extra)


CORPUS_DRAFTS = [
    {"id": "FW-01-a", "scenario_priority": "P1", "finding_priority": "P2",
     "classification": "FINDING-KNOWN:PR41-GHOST", "invariant": "INV-NO-2ND-RESTORER",
     "confidence": "high",
     "title": "FP marker Phase-B false negative, then a Dump START admitted in the same runtime, reboot: PR41 dual "
              "lockout, SG-02 contains 244, only 244 = 2 written over 40 watchdog ticks",
     "ownership": "after one completed 1-minute FP lease (B5 prelude, marker CLEAR): phantom FP RESTORE_REQUIRED "
                  "(nothing written); genuine Dump lease 1000 W target (its controller raises the ceiling to 1500 W with "
                  "the default zero grid reading); synthetic ORIGINAL 244 = 2",
     "anchors": ["fp_phase_b", "dump_start_fp_gate", "pr41_mechanism", "s4doc_ghost_blind_spot", "pr41_guard",
                 "sg02_write"],
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 1}},     # B5 prelude: FP lease
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},                  # ... restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "fp.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 320, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 330, "do": "run_for", "args": {"seconds": 600}}],
     "expect": [{"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                {"observe": "status", "args": {"dom": "dump"}, "op": "contains", "value": "export CONTAINED"},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268]}, "op": "==",
                 "value": {"230": 120, "232": 0, "244": 2, "256": 1500, "261": 1500, "268": 20}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0},
                           {"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}]}],
     "failure_outcome": "the Dump START is admitted over a durable FP obligation; after the reboot both domains are "
                        "locked until out-of-band handling and only SG-02's 244 = 2 is written",
     "smallest_safe_repair_scope": "START Phase B: keep the RAM mirror fail-closed when the marker commit returns false "
                                   "(F-FW01-1)",
     "notes": "F-FW01-1 (FINDING-KNOWN:PR41-GHOST, reclassified from N15 in the hardening pass; counted once there, the "
              "root of F-FW01-2 / F-FW02-* / F-FW03-*; severity availability / cost precondition, low-medium); the "
              "invariants summary pins all eight firmware invariants: exactly the two pre-boot Dump 256x6 writes (START "
              "and the controller raise) are INV-NO-2ND-RESTORER violations, nothing after the boot (INV-LOCKOUT-QUIET "
              "and INV-BOOT-MIRROR hold); MODEL: nvs_policy false_negative (record lands, commit_record returns False; "
              "physically only a marker write that errors after landing fits, rate UNKNOWN)" + _b5_note("FP")},
    {"id": "FW-01-b", "scenario_priority": "P1", "finding_priority": "P2",
     "classification": "FINDING-NEW", "invariant": "INV-RESTORE-BOUND",
     "confidence": "high",
     "title": "Dump marker Phase-B false negative, then a genuine FP lease, reboot inside it: the dual lockout strands "
              "the FP override past its end epoch; Force, Dump Force and FP START refuse; still applied 6 h later",
     "ownership": "after one completed 1-minute Dump lease (B5 prelude, marker CLEAR): "
                  "phantom Dump RESTORE_REQUIRED (nothing written); genuine ACTIVE FP lease 3000 W / 30 min; synthetic "
                  "ORIGINAL 244 = 2",
     "anchors": ["dump_phase_b", "fp_start_dump_gate", "pr41_guard", "fp_wd_corrupt_gate", "fp_wd_corrupt_rationale",
                 "s4doc_dual_exit", "s4doc_permanent"],
     "world": {},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 2790, "do": "fp_operator", "args": {"action": "FORCE_RESTORE_ORIGINAL"}},
                 {"at_s": 2790, "do": "dump_force_restore", "args": {}},
                 {"at_s": 2790, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 2800, "do": "run_for", "args": {"seconds": 21600}}],
     "expect": [{"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268, 273, 274, 279]}, "op": "==",
                 "value": {"230": 58, "232": 1, "244": 2, "256": 3000, "261": 3000, "268": 100, "273": 100, "274": 1,
                           "279": 1}},
                {"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "globals", "args": {"names": ["free_power_end_epoch"]}, "op": "==",
                 "value": {"free_power_end_epoch": 1792581860}},    # FP START at +260 s + 30 min (firmware :9092)
                {"observe": "t_utc", "args": {}, "op": ">=", "value": 1792603460},  # that end epoch + 6 h
                {"observe": "globals", "args": {"names": ["free_power_recovery_review_refusal_count",
                                                          "free_power_recovery_force_refusal_count"]}, "op": "==",
                 "value": {"free_power_recovery_review_refusal_count": 1, "free_power_recovery_force_refusal_count": 1}},
                {"observe": "text_state", "args": {"entity": "free_power_recovery_last_action"}, "op": "==",
                 "value": "refused: metadata invalid"},
                {"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "REJECTED - RECOVERY BLOCKED"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "REJECTED - Force Restore is only available while an operator decision is required"},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}]}],
     "failure_outcome": "the FP grid-charge override stays applied more than 6 hours past its end epoch (until "
                        "out-of-band handling: no in-firmware path ends it and no time bound limits it) with every "
                        "operator surface refusing; INV-RESTORE-BOUND is satisfied only by its lockout clause",
     "smallest_safe_repair_scope": "options only, owner design review: an operator-visible LOCKED alert naming the "
                                   "cause (DUAL_FP_DUMP) with a documented out-of-band exit procedure, or a bounded, "
                                   "restrictive-direction automatic exit for a domain whose own lease has expired; the "
                                   "trigger is removed by F-FW01-1's fail-closed RAM mirror",
     "notes": "F-FW01-2 (FINDING-NEW, reclassified from N15 in the hardening pass, scoped to the consequence: the root "
              "cause PR41-GHOST is F-FW01-1, the lockout and its out-of-band exit are by design, the stranded live "
              "override with no in-firmware exit or time bound is stated nowhere as accepted); severity cost / "
              "availability MEDIUM, safety LOW; reachability INFERRED (a hardware commit false negative, unproven); "
              "MODEL: nvs_policy false_negative; the reboot primitive (FULL on_boot, arms OFF); the replay engine's live "
              "advance to +2590 s runs every watchdog tick in between (about 160 after the reboot), the final run_for "
              "another 1440; the invariants summary pins all eight firmware invariants (only the pre-boot FP 256x6 "
              "write over the Dump phantom; INV-RESTORE-BOUND, INV-LOCKOUT-QUIET, INV-NO-SILENT-OVERRIDE and "
              "INV-BOOT-MIRROR hold)" + _b5_note("Dump", B5_EPOCH_NOTE + " and the t_utc bound that end epoch + 6 h "
                                                  "(1792603460 instead of 1792603260)")},
    {"id": "FW-01-c", "scenario_priority": "P1", "finding_priority": None,
     "classification": "PASS", "invariant": "INV-LOCKOUT-QUIET",
     "confidence": "high",
     "title": "Same as FW-01-b with the owner's ORIGINAL 244 = 0: SG-02 contains (244 := 2) although Dump never wrote; "
              "INV-LOCKOUT-QUIET holds (documented containment design)",
     "ownership": "after one completed 1-minute Dump lease (B5 prelude, marker CLEAR): "
                  "phantom Dump RESTORE_REQUIRED whose trusted record holds original 244 = 0; genuine FP lease rewrote "
                  "256-261, so the D5 exemption (244 and 256-261 equal the trusted original) does not apply",
     "anchors": ["sg02_trigger", "sg02_d5", "sg02_write", "containment_seed"],
     "world": {"bank": {"244": 0}},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60}}],
     "expect": [{"observe": "bank", "args": {"addrs": [244, 256]}, "op": "==", "value": {"244": 2, "256": 3000}},
                {"observe": "status", "args": {"dom": "dump"}, "op": "contains", "value": "export CONTAINED"},
                {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}]}],
     "failure_outcome": "a containment write other than the literal 244 = 2, or a write to 256-261 under the lockout",
     "smallest_safe_repair_scope": "none (documented SG-02 behaviour; restrictive direction)",
     "notes": "key guard decision for FW-01 (SG-02 + D5); the owner's Allow Export becomes Zero Export; the invariants "
              "summary pins all eight firmware invariants: INV-LOCKOUT-QUIET and INV-BOOT-MIRROR hold after the boot, "
              "the only violation is F-FW01-1's pre-boot admission" + _b5_note("Dump")},
    {"id": "FW-01-d", "scenario_priority": "P1", "finding_priority": "P3",
     "classification": "FINDING-NEW", "invariant": "INV-STATUS-CAUSE",
     "confidence": "high",
     "title": "PR41 dual lockout: the Free Power status reports untrusted snapshot data although the FP data record "
              "loaded (end epoch and ORIGINALs present); only dump_status names the dual obligation",
     "ownership": "after one completed 1-minute Dump lease (B5 prelude, marker CLEAR): "
                  "phantom Dump RESTORE_REQUIRED; genuine FP lease; both durable records readable",
     "anchors": ["pr41_fp_status_claim", "fp_status_corrupt", "pr41_dump_status"],
     "world": {},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}}],
     "expect": [{"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted "
                          "(unreadable or invalid); inverter writes locked"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith",
                 "value": "RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)"},
                {"observe": "globals", "args": {"names": ["free_power_end_epoch", "free_power_snapshot_reg257",
                                                          "free_power_recovery_metadata_corrupt"]}, "op": "==",
                 "value": {"free_power_end_epoch": 1792581860, "free_power_snapshot_reg257": 8000,   # START +260 s
                           "free_power_recovery_metadata_corrupt": True}}],                    # + 30 min (:9092)
     "failure_outcome": "the operator is told the FP snapshot data is unreadable / invalid; the real cause (two "
                        "obligations over 256-261) appears only in the Dump status",
     "smallest_safe_repair_scope": "status text only: a lambda-local flag set in the PR41 branch and a dual-obligation "
                                   "sub-branch in the FP status block (a publish inside the PR41 branch alone is "
                                   "overwritten later in the same lambda); a RAM cause global for the runtime refusal "
                                   "texts",
     "notes": "F-FW01-3 (counted; one root cause with its S4 / reg244 site F-FW03-3, corpus FW-03-c); scenario-local "
              "invariant INV-STATUS-CAUSE: an operator-facing lockout text names its cause; dump_status names the dual "
              "obligation only until a Dump START / Accept / End press" + _b5_note("Dump", B5_EPOCH_NOTE)},
    {"id": "FW-02-a", "scenario_priority": "P2", "finding_priority": "P2",
     "classification": "FINDING-KNOWN:N15", "invariant": "INV-NO-2ND-RESTORER",
     "confidence": "high",
     "title": "FP phantom, then an owner manual slot 2 apply (SOC 55) is admitted; after a reboot the FP classifier "
              "locks out (OPERATOR DECISION REQUIRED), zero writes, the owner's value kept",
     "ownership": "after one completed 1-minute FP lease (B5 prelude, marker CLEAR): "
                  "phantom FP RESTORE_REQUIRED (nothing written); owner applies slot 2 SOC 55 through the real buttons",
     "anchors": ["slot2_gate", "fp_phase_b"],
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 1}},     # B5 prelude: FP lease
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},                  # ... restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "fp.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 260, "do": "manual_slot_apply", "args": {"slot": 2, "soc": 55}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60}}],
     "expect": [{"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "OPERATOR DECISION REQUIRED"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "bank", "args": {"addrs": [269]}, "op": "==", "value": {"269": 55}},
                {"observe": "globals", "args": {"names": ["free_power_operator_needed"]}, "op": "==",
                 "value": {"free_power_operator_needed": True}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}]}],
     "failure_outcome": "an unrelated owner edit turns a latent phantom into an FP operator lockout at the next boot",
     "smallest_safe_repair_scope": "START Phase B fail-closed RAM mirror (F-FW01-1)",
     "notes": "F-FW02-1 (N15; availability, low; DUPLICATE of F-FW02-2, one N15 root cause, not counted); the single "
              "pre-boot INV-NO-2ND-RESTORER entry is the lab's label for the admitted manual write over the durable FP "
              "obligation; the invariants summary pins all eight firmware invariants (no silent override after the boot)"
              + _b5_note("FP")},
    {"id": "FW-02-b", "scenario_priority": "P2", "finding_priority": "P2",
     "classification": "FINDING-KNOWN:N15", "invariant": "INV-NO-SILENT-OVERRIDE",
     "confidence": "high",
     "title": "Dump phantom, then the owner applies slot 2 power 1000 W (= the phantom's never-applied ceiling): after a "
              "reboot the Dump restore silently writes the stale 256-261 ORIGINAL and reports RESTORED OK",
     "ownership": "after one completed 1-minute Dump lease (B5 prelude, marker CLEAR): "
                  "phantom Dump RESTORE_REQUIRED whose record holds intended / pending ceiling 1000 W; owner applies "
                  "slot 2 power 1000 W through the real buttons (the owner's new intent)",
     "anchors": ["slot2_gate", "dump_phase_b", "dump_ecco_value", "fcp2_ownership"],
     "world": {},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "manual_slot_apply", "args": {"slot": 2, "power_w": 1000}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==",
                 "value": "RESTORED OK - original inverter settings verified"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [257]}, "op": "==", "value": {"257": 8000}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0},
                           {"inv": "INV-NO-SILENT-OVERRIDE", "tags": [], "boot": 1}]}],
     "failure_outcome": "the owner's applied 1000 W slot power is replaced by the stale 8000 W (one six-register "
                        "ORIGINAL write in which only 257 changes) with no visible obligation left",
     "smallest_safe_repair_scope": "START Phase B fail-closed RAM mirror (F-FW01-1); the ownership classifier stays "
                                   "unchanged",
     "notes": "F-FW02-2 (N15; owner intent / cost, low; counted, the suite's N15 owner); 1000 W is the phantom's "
              "feed-forward ceiling under the lab's synthetic zero telemetry; the invariants summary pins all eight "
              "firmware invariants: one INV-NO-SILENT-OVERRIDE violation after the boot (the silent stale rewrite) and "
              "the pre-boot manual write over the durable Dump obligation; MODEL: the lab ORIGINAL follows the owner's "
              "landed manual apply" + _b5_note("Dump")},
    {"id": "FW-03-a", "scenario_priority": "P2", "finding_priority": "P3",
     "classification": "FINDING-KNOWN:N17", "invariant": "INV-LOCKOUT-QUIET",
     "confidence": "high",
     "title": "Dump phantom + FP lease, reboot with the Dump data record unreadable: Dump corrupt-locked, PR41 skipped, "
              "FP's automatic restore writes 256-261 over Dump's open obligation (FP watchdog first)",
     "ownership": "after one completed 1-minute Dump lease (B5 prelude, marker CLEAR): "
                  "phantom Dump RESTORE_REQUIRED whose data record reads with an error at the next boot; genuine FP "
                  "lease; synthetic ORIGINAL 244 = 2",
     "anchors": ["pr41_guard", "fp_restore_corrupt_gate"],
     "world": {},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5, "nvs_fault": ["read_error", "dump.data"]}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60, "wd_order": ["fp", "dump"]}}],
     "expect": [{"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 261]}, "op": "==",
                 "value": {"230": 120, "232": 0, "256": 8000, "261": 5000}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0},
                           {"inv": "INV-NO-2ND-RESTORER", "tags": ["N17"], "boot": 1},
                           {"inv": "INV-LOCKOUT-QUIET", "tags": [], "boot": 1}]}],
     "failure_outcome": "FP writes the shared 256-261 while Dump holds a durable RESTORE_REQUIRED obligation",
     "smallest_safe_repair_scope": "documented accepted residual N17; root cause F-FW01-1 (a standalone '!other_corrupt' "
                                   "term would strand the FP override)",
     "notes": "F-FW03-1 (N17; safety-rule, low; DUPLICATE of F-FW05-2 in test_lab_fw_durability, the lab's N17 owner, "
              "not counted here); the invariants summary (boot-resolved, seq-free) pins the post-boot N17-tagged "
              "INV-NO-2ND-RESTORER entry and the INV-LOCKOUT-QUIET write, besides the admitted pre-boot START; MODEL: "
              "nvs boot fault read_error on the Dump data record for that boot (a later clean boot heals)"
              + _b5_note("Dump")},
    {"id": "FW-03-b", "scenario_priority": "P2", "finding_priority": "P3",
     "classification": "FINDING-KNOWN:N16", "invariant": "INV-RESTORE-BOUND",
     "confidence": "high",
     "title": "Same as FW-03-a with the owner's ORIGINAL 244 = 0 and the Dump watchdog first: SG-02 writes 244 := 2, "
              "FP's restore hits its register-244 context gate, the FP override stays live behind an operator lockout",
     "ownership": "as FW-03-a; ORIGINAL 244 = 0 is also the FP lease context",
     "anchors": ["fp_ctx_gate", "fp_ctx_hold_text", "sg02_write", "s4doc_r5_n16"],
     "world": {"bank": {"244": 0}},
     "actions": [{"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # B5
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # prelude: Dump lease restored, marker CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5, "nvs_fault": ["read_error", "dump.data"]}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60, "wd_order": ["dump", "fp"]}}],
     "expect": [{"observe": "status_history", "args": {"dom": "fp"}, "op": "contains",
                 "value": "RESTORE BLOCKED - register 244 context changed since this lease started (lease=0 live=2)"},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256]}, "op": "==",
                 "value": {"230": 58, "232": 1, "244": 2, "256": 3000}},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "globals", "args": {"names": ["free_power_operator_needed",
                                                          "free_power_recovery_metadata_corrupt"]}, "op": "==",
                 "value": {"free_power_operator_needed": True, "free_power_recovery_metadata_corrupt": False}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}]}],
     "failure_outcome": "the FP override stays applied until an operator Force; the owner's Allow Export is now Zero "
                        "Export",
     "smallest_safe_repair_scope": "root cause F-FW01-1 (fail-closed RAM mirror); optionally the FP context-hold text "
                                   "names ECCO's own SG-02 containment as the 244 writer; no unbounded SG-02 deferral",
     "notes": "F-FW03-2 (N16, R5; availability / cost, low; counted); which watchdog runs first after the boot decides; "
              "on hardware the first-run offsets are random per boot (ESPHome scheduler), so both outcomes are "
              "reachable; the invariants summary pins all eight firmware invariants (after the boot only the SG-02 "
              "literal is written: INV-LOCKOUT-QUIET holds; INV-RESTORE-BOUND is explained by the operator lockout)"
              + _b5_note("Dump")},
    {"id": "FW-03-c", "scenario_priority": "P2", "finding_priority": "P3",
     "classification": "FINDING-NEW", "invariant": "INV-STATUS-CAUSE",
     "confidence": "high",
     "title": "Triple obligation (reg244 + Dump phantoms, genuine FP lease), reboot: S4 fires first, PR41 is skipped, "
              "FP restores over Dump's open obligation (N17 route), and the reg244 result names the wrong cause "
              "('snapshot data is unreadable') although its data record loaded",
     "ownership": "after the owner's reg244 Apply (Essentials) then Restore and one completed 1-minute Dump lease (B5 "
                  "prelude, both markers CLEAR): "
                  "phantom reg244 RESTORE_REQUIRED (the owner's register 244 Apply to Allow Export through the real "
                  "buttons, marker false negative, nothing written); phantom Dump RESTORE_REQUIRED (nothing written); "
                  "genuine ACTIVE FP lease; synthetic ORIGINAL 244 = 2",
     "anchors": ["s4_guard", "pr41_guard", "s4_dump_status", "s4_r244_status_claim", "r244_status_corrupt"],
     "world": {},
     "actions": [{"at_s": 60, "do": "r244_apply", "args": {"target": "Essentials"}},           # B5 prelude: reg244
                 {"at_s": 60, "do": "r244_restore", "args": {}},                               # Apply -> Restore,
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 1}},  # Dump
                 {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},   # lease restored; both markers CLEAR
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "r244.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "r244_apply", "args": {"target": "Allow Export"}},
                 {"at_s": 260, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1, "mode": "false_negative",
                                                           "times": 1}},
                 {"at_s": 260, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 30}},
                 {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 380, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 390, "do": "run_for", "args": {"seconds": 60, "wd_order": ["fp", "dump"]}}],
     "expect": [{"observe": "status", "args": {"dom": "r244"}, "op": "==",
                 "value": "RECOVERY BLOCKED - durable recovery marker exists but snapshot data is unreadable; inverter "
                          "writes locked"},
                {"observe": "globals", "args": {"names": ["reg244_snapshot_value", "reg244_snapshot_valid"]}, "op": "==",
                 "value": {"reg244_snapshot_value": 2, "reg244_snapshot_valid": True}},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith",
                 "value": "RECOVERY BLOCKED - dual durable obligation (S4)"},
                {"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": False},
                {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                {"observe": "corrupt", "args": {"dom": "r244"}, "op": "==", "value": True},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "nvs_marker", "args": {"dom": "r244"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [230, 232, 244, 256, 261, 268]}, "op": "==",
                 "value": {"230": 120, "232": 0, "244": 2, "256": 8000, "261": 5000, "268": 20}},
                {"observe": "invariants", "args": {"names": CORPUS_INVARIANTS, "form": "summary"}, "op": "==",
                 "value": [{"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0},
                           {"inv": "INV-NO-2ND-RESTORER", "tags": ["N17"], "boot": 1},
                           {"inv": "INV-LOCKOUT-QUIET", "tags": [], "boot": 1}]}],
     "failure_outcome": "the operator is told the reg244 snapshot data is unreadable although the record loaded (the "
                        "real cause, the S4 dual obligation, appears only in the Dump status); FP writes the shared "
                        "256-261 while Dump holds a durable RESTORE_REQUIRED obligation",
     "smallest_safe_repair_scope": "status text only for the reg244 text (the F-FW01-3 pattern in the S4 branch and the "
                                   "reg244 status block, or the planned reg244_lockout_cause); the N17 overlay is the "
                                   "documented accepted residual, root cause F-FW01-1",
     "notes": "F-FW03-3 (FINDING-NEW, diagnostics low; DUPLICATE of F-FW01-3, same root cause, not counted) and the "
              "triple route of F-FW03-1 (N17; DUPLICATE of F-FW05-2, not counted); recorded with the core's r244_apply "
              "action (real Load / select / arm / Apply); reg244_snapshot_value 2 is the record's original (the global's "
              "initial value is 0), so the reg244 data record did load; the invariants summary pins all eight firmware "
              "invariants (INV-BOOT-MIRROR holds at the S4 boot)"
              + _b5_note("reg244 Apply -> Restore (r244_restore) and a Dump", "; both injected marker keys (r244.valid, "
                         "dump.valid) were stored earlier")},
]
RECORD_FILLED = ("source_digests", "trace_digest")


def draft_doc(d: dict, common: dict, anchors: dict, paths: dict) -> dict:
    """The replay draft of one CORPUS_DRAFTS entry (pure; also used by the scratch recorder via ast)."""
    doc = dict(common)
    for k, v in d.items():
        if k != "anchors":
            doc[k] = v
    doc["source_anchors"] = [{"path": paths[anchors[a][0]], "text": anchors[a][1], "line_at_record": 1}
                             for a in d["anchors"]]
    doc["source_digests"] = {paths["fw"]: "0" * 64}
    return doc


# =============================================================================================================================
# helpers
# =============================================================================================================================
def world(bank=None, fw=None, warm: float = 60, **kw) -> L.FirmwareWorld:
    w = L.FirmwareWorld(fw=fw, utc_start=U0, bank=bank, **kw)
    if warm:
        w.run_for(warm)
    return w


def phantom(w, dom: str) -> None:
    """The next RESTORE_REQUIRED commit of `dom`'s marker lands but returns False (Phase-B false negative). The core
    refuses it at that commit unless the marker key was stored earlier in the run (NVS USED-KEY RULE): run prelude()
    for `dom` first."""
    w.nvs_policy(f"{dom}.valid", RR, mode="false_negative")


PRELUDES: list = []   # one (domains, t_end - U0, ok) per prelude() run (the [B5] summary check)


def prelude(w, doms) -> int:
    """B5 completed-lease prelude (V0.1, brief B5 change 2): before a phantom is armed on `doms` ('fp' / 'dump' /
    'r244', executed in the order given), each domain completes one real lease, so its marker key was STORED EARLIER IN
    THE RUN (the core's NVS USED-KEY RULE; the device route of a marker false negative, ESP-IDF
    ESP_ERR_NVS_REMOVE_FAILED, needs an earlier version of the key):
      - 'r244': the owner's register 244 Apply (FirmwareWorld.r244_apply, PRELUDE_R244_TARGET) then the owner's Restore
        through the real 'Restore Original Reg244' button under the master arm (FirmwareWorld.r244_restore, replay
        action 'r244_restore': restore_reg244_button -> restore_reg244_snapshot, Phase C VERIFIED_PENDING_CLEAR then
        Phase D CLEAR, firmware :17788-17799);
      - 'fp': a 1-minute FP lease (3000 W), ended by the FP watchdog with a verified restore (Phase C / D,
        restore_free_power_snapshot_dispatch, firmware :11215-11226);
      - 'dump': a 1-minute Dump lease (1000 W, Stop SOC 25), ended by the Dump watchdog with a verified restore (Phase C /
        D, firmware :20383-20394);
    then run_for(PRELUDE_S) (the corpus PB-01-a pattern). Raises LabHarnessError (fail loud) unless every domain ends
    RESTORED OK with its stored marker CLEAR, its marker key stored earlier (FirmwareWorld.nvs_stored_earlier), not
    corrupt, every owned register back at its ORIGINAL and no invariant violation. Returns the write count after the
    prelude (the 'since' index of wlist: the scenario's own writes start there)."""
    for dom in doms:
        if dom == "r244":
            w.r244_apply(PRELUDE_R244_TARGET)
            w.r244_restore()          # master arm + the real 'Restore Original Reg244' button (core world action)
        elif dom == "fp":
            w.fp_start(power_w=3000, minutes=1)
        elif dom == "dump":
            w.dump_start(power_w=1000, stop_soc=25, minutes=1)
        else:
            raise L.LabHarnessError(f"prelude: unknown domain {dom!r}")
    w.run_for(PRELUDE_S)
    st = {d: (w.status(d)[:60], w.nvs_marker(d), w.nvs_stored_earlier(f"{d}.valid"), w.corrupt(d)) for d in doms}
    off = {a: (w.bank[a], w.original[a]) for a in L.OWNED if w.bank[a] != w.original[a]}
    inv = w.invariants()
    ok = (all(s.startswith("RESTORED OK") and m == "CLEAR" and used and not bad for s, m, used, bad in st.values())
          and not off and not inv)
    PRELUDES.append((tuple(doms), w.t_utc - U0, ok))
    if not ok:
        raise L.LabHarnessError(f"B5 prelude {doms} did not complete a verified lease: {st} off-ORIGINAL {off} "
                                f"invariants {inv[:2]}")
    return len(w.writes())


def wlist(w, boot_from: int = 0, since: int = 0) -> list:
    """(addr, vals, dom) of the writes from index `since` (prelude()'s return value) in boots >= boot_from."""
    return [(x["addr"], x["vals"], x["dom"]) for x in w.writes()[since:] if x["boot"] >= boot_from]


def last_boot_seq(w) -> int:
    return [e["seq"] for e in w.log if e["kind"] == "fw.booted"][-1]


def viol(w, inv: str, after_seq: int = -1) -> list:
    return [v for v in w.invariants([inv]) if v["seq"] > after_seq]


def bank_of(w, addrs) -> dict:
    return w.bank_view(addrs)


def text(w, eid: str) -> str:
    return str(w.sim.ent(eid).state)


def r244_apply(w, target: str) -> str:
    """The owner's register 244 Apply through the real buttons: the core world action FirmwareWorld.r244_apply (Load,
    staged target select, master arm, Apply; one logged act.r244_apply)."""
    return w.r244_apply(target)


def finding(fid: str) -> dict:
    return next(f for f in FINDINGS if f["fid"] == fid)


def classification_backed(f: dict) -> tuple[bool, str]:
    """A FINDING-KNOWN:<id> claim needs its registry anchor (and every secondary reference) exactly once in the public
    tree; FINDING-NEW needs nothing here. (A moved or deleted anchor forces re-classification.)"""
    kind, rid = T.parse_classification(f["classification"])
    if kind != "FINDING-KNOWN":
        return True, kind
    st = T.known_risk_status()[rid]
    refs = [T.anchor_count(p, txt)[0] for p, txt in T.KNOWN_RISK_REFS.get(rid, ())]
    return st["count"] == 1 and all(n == 1 for n in refs), f"{rid}: anchor {st['count']}x, refs {refs}"


def finding_tag(f: dict) -> str:
    """The FINDING line's bracket: classification; 'counted' or 'DUPLICATE of <owner id>, not counted'; cross-refs."""
    dup = f.get("duplicate_of")
    count = f"DUPLICATE of {dup}, not counted" if dup else "counted"
    return f"{f['classification']}; {count}; xref {', '.join(f['xref'])}"


def report_finding(fid: str, reproduced: bool, detail: str) -> None:
    """The reproduction check of a finding (a firmware fix makes it fail loudly and forces re-classification); a
    FINDING-KNOWN classification must also be backed by the registry (classification_backed). A DUPLICATE keeps its
    check; it is only left out of the LAB-SUMMARY count (counted())."""
    f = finding(fid)
    backed, why = classification_backed(f)
    check(f"finding-reproduces:{fid}", reproduced and backed, f"{detail} | classification backed={backed} ({why})")
    if reproduced and backed:
        REPRODUCED.append(fid)
        print(T.finding_line(fid, f"[{finding_tag(f)}] {f['title']}"))
        print(f"  info    {fid} root: {f['root']}")
        if f.get("duplicate_of"):
            print(f"  info    {fid} relation: {f['relation']}")


def counted() -> list:
    """The findings this suite counts in LAB-SUMMARY: reproduced and not a DUPLICATE of another finding (each root
    cause counted once across the lab)."""
    return [fid for fid in REPRODUCED if not finding(fid).get("duplicate_of")]


REPRODUCED: list[str] = []


# =============================================================================================================================
# scenario runners (each returns the world; the checks are in the section functions)
# =============================================================================================================================
def run_fw01a(fw=None, bank=None, order=("fp", "dump"), ticks=40, reboots=1, pre_s=60) -> dict:
    w = world(bank=bank, fw=fw)
    n0 = prelude(w, ("fp",))
    phantom(w, "fp")
    s_fp = w.fp_start(power_w=3000, minutes=30)
    pre = {"fp_marker": w.nvs_marker("fp"), "fp_ram_snap": w.sim.g["free_power_snapshot_valid"],
           "writes": wlist(w, since=n0), "ha": w.ha_view(), "fp_status": s_fp}
    s_dump = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    pre["dump_status"], pre["writes_after_dump"] = s_dump, wlist(w, since=n0)
    w.run_for(pre_s, wd_order=order)
    pre_viol = viol(w, "INV-NO-2ND-RESTORER")
    boots = []
    for _ in range(reboots):
        w.reboot()
        o = w.obligations()
        boots.append({"corrupt": (o["fp"]["corrupt"], o["dump"]["corrupt"]), "nvs": dict(o["nvs"]),
                      "dump_status": w.status("dump"), "fp_status": w.status("fp"),
                      "containment": w.sim.g["dump_containment_state"], "seq": last_boot_seq(w)})
        w.run_for(ticks * 15, wd_order=order)
    return {"w": w, "pre": pre, "pre_viol": pre_viol, "boots": boots}


def run_fw01b(fw=None, bank=None, order=("fp", "dump"), ticks=40, reboots=1, pre_s=120, tail_s=0) -> dict:
    w = world(bank=bank, fw=fw)
    n0 = prelude(w, ("dump",))
    phantom(w, "dump")
    s_dump = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    pre = {"dump_marker": w.nvs_marker("dump"), "dump_ram_snap": w.sim.g["dump_snapshot_valid"],
           "writes": wlist(w, since=n0), "ha": w.ha_view(), "dump_status": s_dump}
    s_fp = w.fp_start(power_w=3000, minutes=30)
    pre["fp_status"], pre["writes_after_fp"] = s_fp, wlist(w, since=n0)
    pre["fp_end"] = w.obligations()["fp"]["end"]
    w.run_for(pre_s, wd_order=order)
    pre_viol = viol(w, "INV-NO-2ND-RESTORER")
    boots = []
    first_boot = w.boot_no + 1
    for _ in range(reboots):
        w.reboot()
        o = w.obligations()
        boots.append({"corrupt": (o["fp"]["corrupt"], o["dump"]["corrupt"]), "nvs": dict(o["nvs"]),
                      "dump_status": w.status("dump"), "fp_status": w.status("fp"),
                      "containment": w.sim.g["dump_containment_state"], "seq": last_boot_seq(w)})
        w.run_for(ticks * 15, wd_order=order)
    if tail_s:
        w.run_for(tail_s, wd_order=order)
    return {"w": w, "pre": pre, "pre_viol": pre_viol, "boots": boots, "first_boot": first_boot}


def operator_sweep(w) -> dict:
    """Every operator / owner surface against the FW-01 (b) end state; returns {surface: text} plus the writes."""
    n0 = len(w.writes())
    out = {}
    out["fp_end"] = w.fp_end()
    w.fp_operator("FORCE_RESTORE_ORIGINAL")
    out["fp_force"] = text(w, "free_power_recovery_last_action")
    out["review_state"] = text(w, "free_power_recovery_state")
    out["review_evidence"] = text(w, "free_power_recovery_evidence_id")
    w.fp_operator("ACCEPT_CURRENT_STATE")
    out["fp_accept"] = text(w, "free_power_recovery_last_action")
    out["fp_start"] = w.fp_start(power_w=3000, minutes=30)
    out["dump_start"] = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    out["dump_force"] = w.dump_force_restore()
    out["dump_accept"] = w.dump_accept()
    out["dump_end"] = w.dump_end()
    out["slot2"] = w.manual_slot_apply(2, soc=55)
    w.run_for(300)
    out["writes"] = [(x["addr"], x["vals"]) for x in w.writes()[n0:]]
    return out


def run_fw02(dom: str, slot: int = 2, fw=None, telem=None, **apply_kw) -> dict:
    w = world(fw=fw)
    n0 = prelude(w, (dom,))
    if telem:
        w.telemetry(**telem)          # synthetic feed-forward inputs (house / PV) before the phantom START
    phantom(w, dom)
    if dom == "fp":
        s = w.fp_start(power_w=3000, minutes=30)
    else:
        s = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    phantom_ceiling = w.sim.g["dump_target_power"]
    applied = w.manual_slot_apply(slot, **apply_kw)
    pre_writes = wlist(w, since=n0)
    w.run_for(120)
    pre_viol = viol(w, "INV-NO-2ND-RESTORER")
    w.reboot()
    boot_seq = last_boot_seq(w)
    w.run_for(60)
    return {"w": w, "start": s, "applied": applied, "pre_writes": pre_writes, "pre_viol": pre_viol,
            "boot_seq": boot_seq, "post_writes": wlist(w, boot_from=1), "phantom_ceiling": phantom_ceiling}


def run_fw03_triple(bank=None, order=("fp", "dump"), fw=None, target="Allow Export", tail_s=630, phase_ms=None) -> dict:
    w = world(bank=bank, fw=fw, phase_ms=phase_ms)
    n0 = prelude(w, ("r244", "dump"))
    phantom(w, "r244")
    s_r = r244_apply(w, target)
    phantom(w, "dump")
    s_d = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    s_f = w.fp_start(power_w=3000, minutes=30)
    pre_writes = wlist(w, since=n0)
    w.run_for(120, wd_order=order)
    w.reboot()
    o = w.obligations()
    boot = {"corrupt": (o["fp"]["corrupt"], o["dump"]["corrupt"], o["r244"]["corrupt"]), "nvs": dict(o["nvs"]),
            "dump_status": w.status("dump"), "seq": last_boot_seq(w), "r244_status": w.status("r244"),
            "r244_value": w.sim.g["reg244_snapshot_value"],
            "loads": {e["data"]["key"]: e["data"]["ok"] for e in w.log if e["kind"] == "fw.load"
                      and e["boot"] == w.boot_no}}
    w.run_for(tail_s, wd_order=order)
    return {"w": w, "starts": (s_r, s_d, s_f), "pre_writes": pre_writes, "boot": boot, "post_writes": wlist(w, 1)}


def run_fw03_unreadable(bank=None, order=("fp", "dump"), fw=None, tail_s=630, phase_ms=None) -> dict:
    w = world(bank=bank, fw=fw, phase_ms=phase_ms)
    prelude(w, ("dump",))
    phantom(w, "dump")
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    s_f = w.fp_start(power_w=3000, minutes=30)
    w.run_for(120, wd_order=order)
    w.reboot(nvs_fault=("read_error", "dump.data"))
    o = w.obligations()
    boot = {"corrupt": (o["fp"]["corrupt"], o["dump"]["corrupt"]), "nvs": dict(o["nvs"]),
            "dump_status": w.status("dump"), "seq": last_boot_seq(w)}
    w.run_for(tail_s, wd_order=order)
    return {"w": w, "start": s_f, "boot": boot, "post_writes": wlist(w, 1)}


def n17_overlay(r: dict) -> bool:
    """F-FW03-1's signature after the boot: FP restored over the corrupt-locked Dump obligation."""
    w, seq = r["w"], r["boot"]["seq"]
    v2 = viol(w, "INV-NO-2ND-RESTORER", seq)
    lq = viol(w, "INV-LOCKOUT-QUIET", seq)
    return (w.status("fp").startswith("RESTORED OK") and w.nvs_marker("fp") == "CLEAR"
            and w.nvs_marker("dump") == "RESTORE_REQUIRED" and w.corrupt("dump")
            and len(v2) == 1 and v2[0]["tags"] == ["N17"] and "restore_free_power_snapshot" in v2[0]["detail"]
            and len(lq) >= 1 and all("while dump is corrupt-locked" in x["detail"] for x in lq)
            and [a for a, _v, d in r["post_writes"] if d == "fp"] == [232, 256, 268, 230])


def ctx_hold(r: dict) -> bool:
    """F-FW03-2's dump-first signature: containment first, FP held by its 244 context gate, override live."""
    w = r["w"]
    return (r["post_writes"] == [(244, [2], "dump")]
            and "RESTORE BLOCKED - register 244 context changed since this lease started (lease=0 live=2)"
            in w.status_history("fp") and w.sim.g["free_power_operator_needed"] and w.nvs_marker("fp") == "RESTORE_REQUIRED"
            and bank_of(w, [230, 232, 244, 256]) == {"230": 58, "232": 1, "244": 2, "256": 3000})


PR41_DUMP_TEXT = "RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)"
S4_DUMP_TEXT = "RECOVERY BLOCKED - dual durable obligation (S4)"
FP_GENERIC_BLOCKED = ("RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted "
                      "(unreadable or invalid); inverter writes locked")
DUMP_GENERIC_BLOCKED = "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be trusted"
R244_GENERIC_BLOCKED = ("RECOVERY BLOCKED - durable recovery marker exists but snapshot data is unreadable; inverter "
                        "writes locked")
# status-only repair-shaped mutants for F-FW01-3 (in memory only; the repair itself is never implemented)
DUAL_FP_TEXT = "RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261); inverter writes locked"
_PR41_TAIL = ('            id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata unavailable");\n'
              '          }\n\n          // SG-02 (RAM-only): every way this boot can set')
_FP_GENERIC_PUBLISH = ('              id(free_power_status).publish_state("' + FP_GENERIC_BLOCKED + '");\n')
NAIVE_FP_STATUS_REPAIR = [
    [_PR41_TAIL, _PR41_TAIL.replace('unavailable");\n          }', 'unavailable");\n'
                                    '            id(free_power_status).publish_state("' + DUAL_FP_TEXT + '");\n'
                                    '          }'), 1]]
FLAG_FP_STATUS_REPAIR = [
    ["bool free_power_marker_unreadable = false;\n",
     "bool free_power_marker_unreadable = false;\n          bool free_power_dual_lockout = false;\n", 1],
    [_PR41_TAIL, _PR41_TAIL.replace('unavailable");\n          }', 'unavailable");\n'
                                    '            free_power_dual_lockout = true;\n          }'), 1],
    [_FP_GENERIC_PUBLISH, '              if (free_power_dual_lockout) id(free_power_status).publish_state("'
                          + DUAL_FP_TEXT + '"); else\n' + _FP_GENERIC_PUBLISH, 1]]


def fp_wrong_cause(r: dict) -> bool:
    """F-FW01-3's boot signature on a FW-01 (b) run: generic FP text, PR41 dump text, FP data record loaded."""
    b0 = r["boots"][0]
    g = r["w"].globals_view(["free_power_end_epoch", "free_power_snapshot_reg257"])
    return (b0["fp_status"] == FP_GENERIC_BLOCKED and b0["dump_status"].startswith(PR41_DUMP_TEXT)
            and g == {"free_power_end_epoch": FP_END, "free_power_snapshot_reg257": ORIG[257]})


def r244_wrong_cause(r: dict) -> bool:
    """F-FW03-3's boot signature on a triple run: S4 dump text, generic reg244 text, both reg244 records loaded."""
    b = r["boot"]
    r244_loads = [ok for k, ok in sorted(b["loads"].items()) if "reg244" in k]
    return (b["dump_status"].startswith(S4_DUMP_TEXT) and b["r244_status"] == R244_GENERIC_BLOCKED
            and len(r244_loads) == 2 and all(x is True for x in r244_loads)
            and r["w"].status("r244") == R244_GENERIC_BLOCKED and "S4" not in r["w"].status("r244"))


# =============================================================================================================================
# [0] anchors and tables
# =============================================================================================================================
def section_tables() -> None:
    print("[0] scenario / finding tables and source anchors (each exactly once; line numbers are info only)")
    bad = []
    for key, (pk, txt) in sorted(ANCHORS.items()):
        n, line = T.anchor_count(PATHS[pk], txt)
        if n != 1:
            bad.append(f"{key}: {n}x")
        else:
            print(f"  info  anchor {key:<26} {PATHS[pk]}:{line}")
    check("every source anchor occurs exactly once in its file (verified with _lab_trace at run time)", not bad, str(bad))
    used = {a for s in SCENARIOS for a in s["anchors"]} | {a for d in CORPUS_DRAFTS for a in d["anchors"]}
    check("every anchor key named by a scenario or corpus draft exists", used <= set(ANCHORS), str(used - set(ANCHORS)))
    vocab_ok = all(T.parse_classification(x["classification"]) for x in SCENARIOS + FINDINGS + CORPUS_DRAFTS)
    check("every classification is in the lab vocabulary (FINDING-KNOWN ids are registered KNOWN_RISKS)", bool(vocab_ok))
    fids = [f["fid"] for f in FINDINGS]
    check("findings are uniquely named and each belongs to one scenario that lists it",
          len(set(fids)) == len(fids) and all(f["fid"] in next(s for s in SCENARIOS if s["id"] == f["scenario"])
                                              ["findings"] for f in FINDINGS))
    fields = ("fid", "scenario", "classification", "grade", "confidence", "severity", "title", "mechanism",
              "reachability", "repair_scope", "notes")
    check("every finding states classification, grade, confidence, severity, mechanism, reachability, repair scope and "
          "notes (no empty field)", all(isinstance(f.get(k), str) and f[k] for f in FINDINGS for k in fields)
          and all(f["grade"] == "VERIFIED" for f in FINDINGS))
    check("the repo has no assignment that clears a *_recovery_metadata_corrupt flag (only boot re-derives them)",
          FW_TEXT.count("recovery_metadata_corrupt) = false") == 0)
    # registry backing of every FINDING-KNOWN id this suite uses (anchor and secondary references exactly once)
    used_ids = sorted({T.parse_classification(x["classification"])[1] for x in SCENARIOS + FINDINGS + CORPUS_DRAFTS}
                      - {None})
    st = T.known_risk_status()
    for rid in used_ids:
        refs = T.KNOWN_RISK_REFS.get(rid, ())
        print(f"  info  known risk {rid:<11} {T.KNOWN_RISKS[rid]['class']:<17} {T.KNOWN_RISKS[rid]['path']}:{st[rid]['line']}"
              f" (+{len(refs)} secondary reference(s))")
    check(f"every FINDING-KNOWN id used here ({', '.join(used_ids)}) has its registry anchor and secondary references "
          "exactly once", all(classification_backed({"classification": f"FINDING-KNOWN:{r}"})[0] for r in used_ids)
          and "PR41-GHOST" in used_ids, str([classification_backed({"classification": f"FINDING-KNOWN:{r}"}) for r in
                                             used_ids]))
    # counting / dedupe consistency (each root cause counted once; owners and cross-references exist)
    by_id = {f["fid"]: f for f in FINDINGS}
    ext_ok = {}
    for xid, suite_file in sorted(EXTERNAL_FINDINGS.items()):
        p = HERE / suite_file
        ext_ok[xid] = p.is_file() and f'"{xid}"' in p.read_text(encoding="utf-8")
    struct = all(isinstance(f.get("root"), str) and f["root"] and "duplicate_of" in f and isinstance(f.get("xref"), list)
                 and f["xref"] for f in FINDINGS)
    owners_ok = all(f["duplicate_of"] is None
                    or (f["duplicate_of"] in by_id and by_id[f["duplicate_of"]]["duplicate_of"] is None
                        and f["duplicate_of"] != f["fid"] and by_id[f["duplicate_of"]]["root"] == f["root"])
                    or f["duplicate_of"] in EXTERNAL_FINDINGS for f in FINDINGS)
    rel_ok = all(bool(f.get("relation")) == bool(f["duplicate_of"]) and (not f["duplicate_of"]
                 or f["duplicate_of"] in f["relation"] or f["duplicate_of"] in f["xref"]) for f in FINDINGS)
    xref_ok = all(x in by_id or x in EXTERNAL_FINDINGS for f in FINDINGS for x in f["xref"])
    roots = [f["root"] for f in FINDINGS if f["duplicate_of"] is None]
    check("counting: every finding names its root, its owner (None = counted here) and cross-references; a DUPLICATE's "
          "owner is a counted finding with the same root here or a listed finding of another suite; counted roots are "
          "unique", struct and owners_ok and rel_ok and xref_ok and len(roots) == len(set(roots)),
          f"struct={struct} owners={owners_ok} relation={rel_ok} xref={xref_ok} roots={len(roots)}/{len(set(roots))}")
    check("counting: every other suite's finding id named as owner / xref occurs in that suite's file (read as text)",
          all(ext_ok.values()), str({k: v for k, v in ext_ok.items() if not v}))
    check("corpus: the invariants pinned by summary are all registered firmware invariants (default set)",
          set(CORPUS_INVARIANTS) <= set(L.INVARIANTS) and len(set(CORPUS_INVARIANTS)) == len(CORPUS_INVARIANTS),
          f"{CORPUS_INVARIANTS} vs {list(L.INVARIANTS)}")
    unpinned = sorted(set(L.INVARIANTS) - set(CORPUS_INVARIANTS))
    if unpinned:
        print(f"  info  core invariants not pinned by the corpus summaries: {unpinned}")


# =============================================================================================================================
# FW-01
# =============================================================================================================================
def section_fw01() -> dict:
    print("[FW-01] phantom marker -> the other domain's START admitted -> reboot -> PR41 dual lockout (FULL on_boot)")
    a = run_fw01a()
    b = run_fw01b(reboots=3, tail_s=600)
    wa, wb = a["w"], b["w"]
    pa, pb = a["pre"], b["pre"]
    print(f"  info  (a) FP phantom START final status (cascade: FW-06 scope, not classified here): {pa['fp_status']}")
    print(f"  info  (a) Dump START status: {pa['dump_status'][:90]}")
    print(f"  info  (b) Dump phantom START status: {pb['dump_status']}")
    print(f"  info  (b) FP START status: {pb['fp_status']}")
    # F-FW01-1: admission under the phantom, both orders
    va, vb = a["pre_viol"], b["pre_viol"]
    rep1 = (pa["fp_marker"] == "RESTORE_REQUIRED" and pa["fp_ram_snap"] is False and pa["writes"] == []
            and pa["ha"]["fp_snapshot_valid"] is False and pa["ha"]["fp_active"] is False
            and pa["dump_status"].startswith("ACTIVE - VERIFIED OK")
            and pa["writes_after_dump"] == [(256, [1000] * 6, "dump"), (244, [0], "dump")]
            and len(va) >= 1 and "dump wrote 256x6 (start_dump_to_grid_override) while fp holds" in va[0]["detail"]
            and all(x["detail"].startswith("dump wrote 256x6 (") and "while fp holds" in x["detail"] for x in va)
            and pb["dump_marker"] == "RESTORE_REQUIRED" and pb["dump_ram_snap"] is False and pb["writes"] == []
            and pb["ha"]["dump_snapshot_valid"] is False and pb["fp_status"].startswith("ACTIVE - VERIFIED OK")
            and len(vb) == 1 and "fp wrote 256x6 (start_free_power_override) while dump holds" in vb[0]["detail"])
    report_finding("F-FW01-1", rep1, f"a={va} b={vb} pa={pa} pb={pb}")
    # PR41 with the FULL on_boot
    pr41 = PR41_DUMP_TEXT
    ok_boot = all(x["corrupt"] == (True, True) and x["nvs"]["fp"] == x["nvs"]["dump"] == "RESTORE_REQUIRED"
                  and x["dump_status"].startswith(pr41) for x in a["boots"] + b["boots"])
    check("FW-01: the FULL on_boot's PR41 check locks BOTH domains at every boot (a: 1, b: 3 reboots), markers kept",
          ok_boot, str([(x["corrupt"], x["nvs"], x["dump_status"][:60]) for x in a["boots"] + b["boots"]]))
    last_ceiling = [v for a_, v, d_ in wlist(wa) if a_ == 256][-1]
    check("FW-01 (a): containment is armed at boot (state 1) and its only write over 40 watchdog ticks is the SG-02 "
          "literal 244 = 2; the Dump lease's last 256-261 ceiling stays (below the ORIGINAL: restrictive, documented)",
          a["boots"][0]["containment"] == 1 and wlist(wa, 1) == [(244, [2], "dump")]
          and "export CONTAINED" in wa.status("dump") and bank_of(wa, range(256, 262)) == {
              str(256 + i): last_ceiling[i] for i in range(6)} and all(last_ceiling[i] <= ORIG[256 + i] for i in range(6))
          and wa.bank[244] == 2, f"{wlist(wa, 1)} {bank_of(wa, range(256, 262))} {wa.status('dump')[:80]}")
    for tag, w in (("a", wa), ("b", wb)):
        bad = w.invariants(["INV-LOCKOUT-QUIET", "INV-NO-RESUME", "INV-WS", "INV-ONE-LEASE", "INV-NO-SILENT-OVERRIDE",
                            "INV-BOOT-MIRROR"])
        check(f"FW-01 ({tag}): INV-LOCKOUT-QUIET, INV-NO-RESUME, INV-WS, INV-ONE-LEASE, INV-NO-SILENT-OVERRIDE, "
              "INV-BOOT-MIRROR hold (lockouts visible, every boot's RAM mirror matches its stored markers)", not bad,
              str(bad[:2]))
    check("FW-01 (b): no write at all after any of the 3 reboots (ORIGINAL 244 = 2: containment NOT_NEEDED)",
          wlist(wb, b["first_boot"]) == [] and all(x["containment"] == 1 for x in b["boots"])
          and text(wb, "dump_containment_state_sensor").startswith("NOT_NEEDED"), str(wlist(wb, b["first_boot"])))
    # F-FW01-2: the stranded FP override
    o = wb.obligations()["fp"]
    end = pb["fp_end"]
    strand = (bank_of(wb, FP_OVERRIDE_ADDRS) == FP_OVERRIDE and o["corrupt"] and o["snap"] and o["due"] and o["act"]
              and wb.t_utc >= end + 600 and end == FP_END and wb.boot_no == 3
              and wb.invariants(["INV-RESTORE-BOUND"]) == [] and wb.corrupt("dump"))
    print(f"  info  (b) after 3 reboots x 40 ticks: t - FP end epoch = {wb.t_utc - end} s, bank "
          f"{bank_of(wb, FP_OVERRIDE_ADDRS)}")
    ops = operator_sweep(wb)
    for k in sorted(ops):
        if k != "writes":
            print(f"  info  (b) surface {k:<16} -> {str(ops[k])[:120]}")
    refused = (ops["writes"] == [] and ops["fp_end"].startswith("END BLOCKED - RECOVERY BLOCKED")
               and ops["fp_force"].startswith("refused: metadata") and ops["fp_accept"].startswith("refused: metadata")
               and ops["review_state"] == "LOCKED_NEITHER" and ops["review_evidence"] == "-"
               and ops["fp_start"].startswith("REJECTED - RECOVERY BLOCKED")
               and ops["dump_start"].startswith("REJECTED - RECOVERY BLOCKED")
               and ops["dump_force"] == "REJECTED - Force Restore is only available while an operator decision is required"
               and ops["dump_accept"].startswith("REJECTED - RECOVERY BLOCKED")
               and ops["dump_end"].startswith("RECOVERY BLOCKED")
               and ops["slot2"] == "REJECTED - Free Power or Dump to Grid override/recovery owns TOU settings"
               and bank_of(wb, FP_OVERRIDE_ADDRS) == FP_OVERRIDE)
    check("FW-01 (b): every operator / owner surface refuses with zero writes (FP End / Force / Accept / Review / START, "
          "Dump START / Force / Accept / End, manual slot apply)", refused, str(ops))
    # F-FW01-3's texts are read right after the sweep (its Dump START / Accept / End presses), before the horizon run
    after = {"fp": wb.status("fp"), "dump": wb.status("dump"), "dump_state": wb.text_state("dump_recovery_state")}
    print(f"  info  (b) after the sweep: dump_status {after['dump'][:70]} | dump_recovery_state {after['dump_state']}")
    # F-FW01-2 is scoped to the consequence: no in-firmware exit (every surface refused; no corrupt-clearing assignment
    # exists) and no time bound (still stranded STRAND_HORIZON_S later, every watchdog tick in between, zero writes)
    wb.run_for(STRAND_HORIZON_S)
    unbounded = (bank_of(wb, FP_OVERRIDE_ADDRS) == FP_OVERRIDE and wlist(wb, b["first_boot"]) == []
                 and wb.corrupt("fp") and wb.corrupt("dump") and wb.nvs_marker("fp") == "RESTORE_REQUIRED"
                 and wb.t_utc >= end + STRAND_HORIZON_S and FW_TEXT.count("recovery_metadata_corrupt) = false") == 0
                 and wb.invariants(["INV-RESTORE-BOUND", "INV-LOCKOUT-QUIET", "INV-BOOT-MIRROR"]) == [])
    print(f"  info  (b) {STRAND_HORIZON_S // 3600} h after the sweep: t - FP end epoch = {wb.t_utc - end} s, bank "
          f"{bank_of(wb, FP_OVERRIDE_ADDRS)}, post-boot writes {wlist(wb, b['first_boot'])}")
    report_finding("F-FW01-2", strand and refused and unbounded,
                   f"strand={strand} refused={refused} unbounded={unbounded} obl={o} t-end={wb.t_utc - end}")
    # F-FW01-3: the wrong FP cause text (data record readable); after the operator sweep's Dump START / Accept / End
    # presses no HA-visible text names the dual obligation any more (texts captured above, right after the sweep)
    rep3 =(fp_wrong_cause(b) and ops["dump_end"].startswith(DUMP_GENERIC_BLOCKED)
            and not any("dual durable obligation" in v for v in after.values())
            and after["dump_state"] == "LOCKED - durable recovery metadata unavailable")
    report_finding("F-FW01-3", rep3, f"{b['boots'][0]['fp_status']} / {after}")
    naive = run_fw01b(fw=mutant_fw(NAIVE_FP_STATUS_REPAIR))
    check("F-FW01-3 repair scope: a free_power_status publish inside the PR41 branch alone does not fix it - the FP "
          "status block later in the same boot lambda overwrites it (published, then replaced by the generic text)",
          fp_wrong_cause(naive) and DUAL_FP_TEXT in naive["w"].status_history("fp"),
          naive["boots"][0]["fp_status"])
    # SG-02 variant: original 244 = 0
    c = run_fw01b(bank={244: 0}, ticks=40)
    wc = c["w"]
    check("FW-01 SG-02 variant ORIGINAL 244 = 0 (documented behaviour): the D5 exemption does not apply (FP rewrote "
          "256-261), containment writes exactly the literal 244 = 2 once, CONTAINED; INV-LOCKOUT-QUIET holds",
          wlist(wc, 1) == [(244, [2], "dump")] and wc.original[244] == 0
          and text(wc, "dump_containment_state_sensor").startswith("CONTAINED")
          and wc.invariants(["INV-LOCKOUT-QUIET"]) == [] and wc.sim.g["dump_snapshot_data_loaded"],
          f"{wlist(wc, 1)} {text(wc, 'dump_containment_state_sensor')}")
    # wd order independence
    d = run_fw01b(order=("dump", "fp"), reboots=3, tail_s=600)
    check("FW-01 (b): the stranded end state is the same with the Dump watchdog first (same-tick order sweep)",
          bank_of(d["w"], FP_OVERRIDE_ADDRS) == FP_OVERRIDE and wlist(d["w"], 1) == [] and d["w"].corrupt("fp"))
    e = run_fw01a(order=("dump", "fp"))
    check("FW-01 (a): the same end state with the Dump watchdog first",
          wlist(e["w"], 1) == [(244, [2], "dump")] and e["w"].corrupt("fp") and e["w"].corrupt("dump"))
    return {"a": a, "b": b, "c": c}


# =============================================================================================================================
# FW-02
# =============================================================================================================================
def section_fw02() -> dict:
    print("[FW-02] phantom obligation + owner manual TOU slot apply (real Load + Apply) in the same runtime, reboot")
    out = {}
    for key, dom, kw in (("fp_soc", "fp", {"soc": 55}), ("fp_time", "fp", {"start_hhmm": 500}),
                         ("dump_p1000", "dump", {"power_w": 1000}), ("dump_p500", "dump", {"power_w": 500}),
                         ("dump_p4000", "dump", {"power_w": 4000}), ("dump_soc", "dump", {"soc": 55})):
        r = run_fw02(dom, **kw)
        out[key] = r
        w = r["w"]
        print(f"  info  {key:<11} apply: {r['applied'][:60]} | after reboot {dom}: {w.status(dom)[:70]} | post-boot "
              f"writes {r['post_writes']}")
    admitted = all(r["applied"].startswith("VERIFIED OK") and len(r["pre_viol"]) == 1
                   and "manual wrote 257x1 (apply_manual_slot2)" in r["pre_viol"][0]["detail"] for r in out.values())
    check("FW-02: the slot 2 Apply (its gate reads RAM mirrors only) is admitted under every phantom and is recorded as "
          "INV-NO-2ND-RESTORER (manual writer while the other domain holds RESTORE_REQUIRED)", admitted,
          str({k: (r["applied"][:30], r["pre_viol"]) for k, r in out.items()}))
    f = out["fp_soc"]
    wf = f["w"]
    fp_lock = (wf.status("fp").startswith("OPERATOR DECISION REQUIRED") and f["post_writes"] == []
               and wf.nvs_marker("fp") == "RESTORE_REQUIRED" and wf.sim.g["free_power_operator_needed"]
               and wf.bank[269] == 55 and not viol(wf, "INV-NO-SILENT-OVERRIDE"))
    check("FW-02 FP: the FP classifier fails closed - OPERATOR DECISION REQUIRED, zero writes, the owner's SOC 55 kept, "
          "no silent override", fp_lock, wf.status("fp"))
    report_finding("F-FW02-1", admitted and fp_lock, wf.status("fp"))
    t = out["fp_time"]
    check("FW-02 FP: an owner change outside FP's registers (slot 2 start time, 251) restores as ORIGINAL with zero "
          "writes and keeps the owner's time", t["w"].status("fp").startswith("RESTORED OK") and t["post_writes"] == []
          and t["w"].bank[251] == 500 and not viol(t["w"], "INV-NO-SILENT-OVERRIDE"), t["w"].status("fp"))
    # operator exits on the FP lockout (documented P2 behaviour)
    acc = run_fw02("fp", soc=55)
    s_acc = acc["w"].fp_operator("ACCEPT_CURRENT_STATE")
    frc = run_fw02("fp", soc=55)
    s_frc = frc["w"].fp_operator("FORCE_RESTORE_ORIGINAL")
    check("FW-02 FP operator exits (documented P2): Accept keeps the owner's 55 and clears the marker; Force restores "
          "the stale snapshot ORIGINAL (269 back to 20) and clears - an operator-authorised revert",
          s_acc.startswith("ACCEPT CURRENT STATE SUCCESS") and acc["w"].bank[269] == 55 and acc["w"].nvs_marker("fp") ==
          "CLEAR" and s_frc.startswith("FORCE RESTORE ORIGINAL SUCCESS") and frc["w"].bank[269] == ORIG[269]
          and frc["w"].nvs_marker("fp") == "CLEAR", f"{s_acc} / {s_frc}")
    def silent_rewrite(r) -> bool:
        w = r["w"]
        v = viol(w, "INV-NO-SILENT-OVERRIDE", r["boot_seq"])
        return (w.status("dump") == "RESTORED OK - original inverter settings verified"
                and w.nvs_marker("dump") == "CLEAR" and w.bank[257] == ORIG[257]
                and r["post_writes"] == [(256, [ORIG[a] for a in range(256, 262)], "dump")]
                and len(v) >= 1 and "'257'" in v[0]["detail"])
    silent = [silent_rewrite(out[key]) and out[key]["phantom_ceiling"] == 1000 for key in ("dump_p1000", "dump_p500")]
    # the coincidence set follows the phantom's feed-forward START ceiling (synthetic house 430 W / PV 120 W -> 1300 W)
    ff = {"house_w": 430, "pv_w": 120}
    ff_hit = run_fw02("dump", telem=ff, power_w=1300)
    ff_miss = run_fw02("dump", telem=ff, power_w=1000)
    ff_ok = (ff_hit["phantom_ceiling"] == 1300 and silent_rewrite(ff_hit)
             and ff_miss["w"].status("dump").startswith("OPERATOR DECISION REQUIRED") and ff_miss["post_writes"] == []
             and ff_miss["w"].bank[257] == 1000)
    print(f"  info  F-FW02-2 coincidence set: lab telemetry ceiling {out['dump_p1000']['phantom_ceiling']} W; with "
          f"house 430 / PV 120 the phantom ceiling is {ff_hit['phantom_ceiling']} W -> owner 1300 "
          f"{ff_hit['w'].status('dump')[:20]}, owner 1000 {ff_miss['w'].status('dump')[:26]}")
    report_finding("F-FW02-2", all(silent) and ff_ok, f"{silent} ff={ff_ok}")
    fo = out["dump_p4000"]
    check("FW-02 Dump: an owner value that is not one of ECCO's (4000 W) is FOREIGN - never written, OPERATOR DECISION "
          "REQUIRED, no silent override", fo["w"].status("dump").startswith("OPERATOR DECISION REQUIRED")
          and fo["post_writes"] == [] and fo["w"].bank[257] == 4000 and not viol(fo["w"], "INV-NO-SILENT-OVERRIDE"),
          fo["w"].status("dump"))
    ds_ = out["dump_soc"]
    check("FW-02 Dump: an owner change outside Dump's registers (slot 2 SOC) restores as ORIGINAL with zero writes",
          ds_["w"].status("dump").startswith("RESTORED OK") and ds_["post_writes"] == [] and ds_["w"].bank[269] == 55
          and not viol(ds_["w"], "INV-NO-SILENT-OVERRIDE"), ds_["w"].status("dump"))
    runs = dict(out, ff_hit=ff_hit, ff_miss=ff_miss, fp_accept=acc, fp_force=frc)
    bad = [(k, v["inv"], v["detail"][:80]) for k, r in sorted(runs.items())
           for v in r["w"].invariants(["INV-WS", "INV-ONE-LEASE", "INV-NO-RESUME", "INV-LOCKOUT-QUIET", "INV-BOOT-MIRROR"])]
    check(f"FW-02: INV-WS, INV-ONE-LEASE, INV-NO-RESUME, INV-LOCKOUT-QUIET and INV-BOOT-MIRROR hold in all {len(runs)} "
          "runs (the phantom's next boot mirrors its stored marker into RAM)", not bad, str(bad[:2]))
    return out


# =============================================================================================================================
# FW-03
# =============================================================================================================================
def section_fw03() -> dict:
    print("[FW-03] triple obligation (S4 before PR41), FP RR + Dump unreadable data, same-tick watchdog order sweep")
    s4 = S4_DUMP_TEXT
    out = {}
    for o244 in (2, 0):
        for order in (("fp", "dump"), ("dump", "fp")):
            tag = f"{o244}-{order[0]}"
            out["triple", tag] = run_fw03_triple(bank={244: o244}, order=order)
            out["unread", tag] = run_fw03_unreadable(bank={244: o244}, order=order)
    for (kind, tag), r in sorted(out.items()):
        print(f"  info  {kind:<6} 244={tag[0]} {tag[2:]:<4}-first: fp {r['w'].status('fp')[:56]} | post-boot writes "
              f"{[(a, v[:2], d) for a, v, d in r['post_writes']]}")
    tr = out["triple", "2-fp"]
    check("FW-03 triple: the reg244 and Dump phantom STARTs wrote nothing; the FP START is admitted (RAM mirrors CLEAR)",
          tr["starts"][0].startswith("FAILED - could not durably commit") and tr["starts"][1].startswith("START FAILED")
          and tr["starts"][2].startswith("ACTIVE - VERIFIED OK")
          and [a for a, _v, _d in tr["pre_writes"]] == [232, 230, 268, 256], str(tr["starts"]))
    check("FW-03 triple: at boot S4 fires FIRST (Dump + reg244 corrupt, dump_status the S4 text) and PR41 is skipped by "
          "its '!dump corrupt' guard (FP NOT corrupt) - in every variant",
          all(r["boot"]["corrupt"] == (False, True, True) and r["boot"]["dump_status"].startswith(s4)
              and r["boot"]["nvs"] == {"fp": "RESTORE_REQUIRED", "dump": "RESTORE_REQUIRED", "r244": "RESTORE_REQUIRED"}
              for (k, _t), r in out.items() if k == "triple"))
    check("FW-03 unreadable Dump data: Dump corrupt (DATA_UNTRUSTED), FP not corrupt, containment armed (state 1)",
          all(r["boot"]["corrupt"] == (False, True) and r["w"].nvs_marker("dump") == "RESTORE_REQUIRED"
              for (k, _t), r in out.items() if k == "unread"))
    n17 = [n17_overlay(out[k, t]) for k in ("triple", "unread") for t in ("2-fp", "2-dump", "0-fp")]
    report_finding("F-FW03-1", all(n17), str(n17))
    ctx = [ctx_hold(out[k, "0-dump"]) for k in ("triple", "unread")]
    contrast = (n17_overlay(out["triple", "0-fp"]) and out["triple", "0-fp"]["w"].bank[244] == 0
                and [x for x in out["triple", "0-fp"]["post_writes"] if x[0] == 244] == []
                and out["unread", "0-fp"]["post_writes"][-1] == (244, [2], "dump"))
    w = out["unread", "0-dump"]["w"]
    s_acc = w.fp_operator("ACCEPT_CURRENT_STATE")
    n0 = len(w.writes())
    s_frc = w.fp_operator("FORCE_RESTORE_ORIGINAL")
    forced = [x for x in w.invariants(["INV-NO-2ND-RESTORER"]) if x["seq"] > out["unread", "0-dump"]["boot"]["seq"]]
    exits = (s_acc.startswith("ACCEPT REFUSED - state is INTENDED") and s_frc.startswith("FORCE RESTORE ORIGINAL SUCCESS")
             and [x["addr"] for x in w.writes()[n0:]] == [232, 256, 268, 230] and len(forced) == 1
             and forced[0]["tags"] == ["N17"] and "free_power_recovery_force_restore_dispatch" in forced[0]["detail"])
    print(f"  info  dump-first operator exits: Accept -> {s_acc[:70]} | Force -> {s_frc[:60]}")
    report_finding("F-FW03-2", all(ctx) and contrast and exits, f"ctx={ctx} contrast={contrast} exits={exits}")
    check("FW-03 order sweep: FP first with ORIGINAL 244 = 0 - triple: containment then finds 244 / 256-261 equal to the "
          "trusted Dump original (D5) and writes nothing; unreadable data: containment writes 244 := 2 after FP",
          contrast)
    bad = [x for r in out.values() for x in r["w"].invariants(["INV-WS", "INV-NO-RESUME", "INV-ONE-LEASE",
                                                                  "INV-BOOT-MIRROR"])]
    check("FW-03: INV-WS, INV-NO-RESUME, INV-ONE-LEASE and INV-BOOT-MIRROR hold in every variant (S4 and unreadable-data "
          "boots: every stored RESTORE_REQUIRED has its RAM snapshot or lockout)", not bad, str(bad[:2]))
    check("FW-03: Dump and reg244 stay locked with their markers set after the FP restore, for the rest of that boot",
          all(r["w"].corrupt("dump") and r["w"].nvs_marker("dump") == "RESTORE_REQUIRED" for r in out.values())
          and all(r["w"].corrupt("r244") for (k, _t), r in out.items() if k == "triple"))
    # F-FW03-3: the S4 sibling of F-FW01-3 (reg244 result text names the wrong cause; reg244 records loaded)
    tri = [out["triple", t] for t in ("2-fp", "2-dump", "0-fp", "0-dump")]
    print(f"  info  triple boot reg244 result: {tri[0]['boot']['r244_status']} | reg244 loads "
          f"{[ok for k, ok in sorted(tri[0]['boot']['loads'].items()) if 'reg244' in k]} | value "
          f"{tri[0]['boot']['r244_value']}")
    report_finding("F-FW03-3", all(r244_wrong_cause(r) for r in tri)
                   and tri[0]["boot"]["r244_value"] == 2,    # the 244 = 2 variant's original, loaded (initial value 0)
                   str([(r["boot"]["r244_status"][:60], r["boot"]["loads"]) for r in tri[:1]]))
    # documented behaviour (fcp2 repeat-run rule): with a TRANSIENT data read error the next clean boot trusts Dump again,
    # its restore finds 256-261 already at the ORIGINAL FP wrote back and writes nothing (F-FW03-1's lock is not permanent
    # in the unreadable-data construction); the triple re-locks on every boot (S4 re-fires)
    hw = out["unread", "2-fp"]["w"]
    hw.reboot()
    healed_boot = hw.boot_no
    hw.run_for(120)
    tw = out["triple", "2-fp"]["w"]
    tw.reboot()
    check("FW-03 unreadable data, later clean boot (documented repeat-run rule): Dump trusted again, RESTORED OK with "
          "zero writes, both markers CLEAR; the triple instead re-locks Dump and reg244 at the next boot",
          hw.status("dump").startswith("RESTORED OK") and wlist(hw, healed_boot) == [] and not hw.corrupt("dump")
          and hw.nvs_marker("dump") == "CLEAR" and hw.nvs_marker("fp") == "CLEAR"
          and tw.corrupt("dump") and tw.corrupt("r244") and tw.status("dump").startswith(S4_DUMP_TEXT),
          f"{hw.status('dump')[:60]} {wlist(hw, healed_boot)} triple {tw.status('dump')[:50]}")
    return out


# =============================================================================================================================
# negative controls (in-memory firmware mutants; exact-count replace; the core's text-loading path)
# =============================================================================================================================
MUTANTS = [
    {"id": "NC-FW01-1", "family": "FW-01", "target": "INV-NO-2ND-RESTORER",
     "what": "PR41 condition replaced by false (no Free Power/Dump dual-obligation lockout)",
     "pairs": [["id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED &&\n"
                "            id(dump_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED\n", "false\n", 1]]},
    {"id": "NC-FW01-2", "family": "FW-01", "target": "INV-LOCKOUT-QUIET",
     "what": "FP corrupt gates removed from the FP watchdog and the restore precondition",
     "pairs": [["if (id(free_power_recovery_metadata_corrupt)) return false;", "", 1],
               ["id(free_power_snapshot_valid) &&\n                !id(free_power_recovery_metadata_corrupt) &&\n"
                "                !id(free_power_operation_in_progress) &&",
                "id(free_power_snapshot_valid) &&\n                !id(free_power_operation_in_progress) &&", 1]]},
    {"id": "NC-FW01-3", "family": "FW-01", "target": "INV-LOCKOUT-QUIET",
     "what": "SG-02 containment literal 2 (Zero Export) changed to 1 (Essentials)",
     "pairs": [["values: !lambda 'return std::vector<uint16_t>{2};'", "values: !lambda 'return std::vector<uint16_t>{1};'",
                1]]},
    {"id": "NC-FW02-1", "family": "FW-02", "target": "INV-NO-SILENT-OVERRIDE",
     "what": "Dump restore pre-read treats every changed slot as ECCO-owned",
     "pairs": [["bool ecco_value = live == id(dump_target_power) || live == id(dump_evidence_pending_ceiling) || "
                "live == floor_v;", "bool ecco_value = true;", 1]]},
    {"id": "NC-FW03-1", "family": "FW-03", "target": "INV-NO-2ND-RESTORER",
     "what": "FP restore register-244 lease-context comparison replaced by true (both pre-write gates)",
     "pairs": [["id(free_power_restore_live_reg244) == id(free_power_lease_context_reg244);", "true;", 2]]},
    {"id": "NC-FW01-4", "family": "FW-01", "target": "finding-reproduces:F-FW01-3",
     "what": "status-only repair-shaped mutant (lambda-local dual flag set in PR41, dual sub-branch in the FP status "
             "block): the wrong-cause signature must disappear with no control change (finding sensitivity)",
     "pairs": FLAG_FP_STATUS_REPAIR},
    {"id": "NC-FW03-2", "family": "FW-03", "target": "finding-reproduces:F-FW03-1",
     "what": "PR41 guard without '!dump_recovery_metadata_corrupt' (PR41 also fires after S4): the N17 overlay must "
             "disappear (finding sensitivity)",
     "pairs": [["            !id(free_power_recovery_metadata_corrupt) &&\n            !id(dump_recovery_metadata_corrupt) &&"
                "\n            id(free_power_marker_state) ==",
                "            !id(free_power_recovery_metadata_corrupt) &&\n            id(free_power_marker_state) ==", 1]]},
]
NC_RESULTS: list = []


def mutant_fw(pairs):
    t = FW_TEXT
    for old, new, n in pairs:
        c = t.count(old)
        if c != n:
            raise L.LabHarnessError(f"mutant anchor found {c}x (need {n}): {old[:60]!r}")
        t = t.replace(old, new)
    return L.load_fw(t)


def nc_outcome(m: dict) -> tuple[bool, str]:
    """(violation of the target reproduced, detail) on the mutant firmware. Raises on a harness / parse error."""
    fw = mutant_fw(m["pairs"])
    mid = m["id"]
    if mid == "NC-FW01-1":
        r = run_fw01b(fw=fw)
        v = viol(r["w"], "INV-NO-2ND-RESTORER", r["boots"][0]["seq"])
        return bool(v) and v[0]["inv"] == m["target"] and not r["w"].corrupt("fp"), str(v[:1])
    if mid == "NC-FW01-2":
        r = run_fw01b(fw=fw)
        v = viol(r["w"], "INV-LOCKOUT-QUIET", r["boots"][0]["seq"])
        return bool(v) and v[0]["inv"] == m["target"] and any("while fp is corrupt-locked" in x["detail"] for x in v), \
            str(v[:1])
    if mid == "NC-FW01-3":
        r = run_fw01b(fw=fw, bank={244: 0})
        v = viol(r["w"], "INV-LOCKOUT-QUIET", r["boots"][0]["seq"])
        return bool(v) and v[0]["inv"] == m["target"] and "wrote 244 [1]" in v[0]["detail"], str(v[:1])
    if mid == "NC-FW01-4":
        r = run_fw01b(fw=fw)
        same_control = (wlist(r["w"], r["first_boot"]) == [] and r["w"].corrupt("fp") and r["w"].corrupt("dump")
                        and bank_of(r["w"], FP_OVERRIDE_ADDRS) == FP_OVERRIDE)
        return (not fp_wrong_cause(r) and r["boots"][0]["fp_status"] == DUAL_FP_TEXT and same_control,
                f"fp_status={r['boots'][0]['fp_status'][:70]} same control outcome={same_control}")
    if mid == "NC-FW02-1":
        r = run_fw02("dump", fw=fw, power_w=4000)
        v = viol(r["w"], "INV-NO-SILENT-OVERRIDE", r["boot_seq"])
        return bool(v) and v[0]["inv"] == m["target"], str(v[:1])
    if mid == "NC-FW03-1":
        r = run_fw03_unreadable(bank={244: 0}, order=("dump", "fp"), fw=fw)
        v = viol(r["w"], "INV-NO-2ND-RESTORER", r["boot"]["seq"])
        return bool(v) and v[0]["inv"] == m["target"] and v[0]["tags"] == ["N17"], str(v[:1])
    if mid == "NC-FW03-2":
        r1 = run_fw03_triple(bank={244: 2}, order=("fp", "dump"), fw=fw)
        r2 = run_fw03_unreadable(bank={244: 2}, order=("fp", "dump"), fw=fw)
        gone = not n17_overlay(r1) and not n17_overlay(r2)
        locked = all(r["w"].corrupt("fp") and r["post_writes"] == [] for r in (r1, r2))
        return gone and locked, f"overlay gone={gone} fp locked, no writes={locked}"
    raise L.LabHarnessError(f"unknown mutant {mid}")


def section_negative_controls() -> None:
    print("[NC] negative controls: one in-memory guard mutation per family must make its intended check fail")
    for m in MUTANTS:
        try:
            killed, detail = nc_outcome(m)
            outcome = "killed" if killed else "survived"
        except Exception as exc:  # a crashing / unparsable mutant is MUTANT-INVALID: a negative-control FAILURE
            killed, detail, outcome = False, f"{type(exc).__name__}: {exc}", "invalid"
        NC_RESULTS.append((m["id"], outcome))
        print(f"  info  {m['id']} [{m['family']}] {m['what']} -> {outcome}: {detail[:140]}")
        check(f"{m['id']}: mutant '{m['what']}' is killed by {m['target']} (no harness exception, no parse error)",
              killed, f"{outcome}: {detail}")


# =============================================================================================================================
# corpus: the files must be T.record() of the drafts above, and every file must replay
# =============================================================================================================================
def _strip(doc: dict) -> dict:
    d = copy.deepcopy(doc)
    for k in RECORD_FILLED:
        d.pop(k, None)
    for a in d.get("source_anchors", []):
        a.pop("line_at_record", None)
    return d


_TAG_ALIAS = {tag: alias for alias, tag in L.TAGS.items()}               # durable tag -> lab alias ('dump.valid', ...)
_TAG_DOM = {tag: alias.split(".")[0] for tag, alias in _TAG_ALIAS.items()}   # durable tag -> 'fp' / 'dump' / 'r244'
_LEASE_MARKERS = (RR, L.ds.Durable.MARKER_RESTORE_VERIFIED_PENDING_CLEAR, L.ds.Durable.MARKER_CLEAR)


def prelude_in_log(log) -> tuple[bool, list]:
    """B5 check on one replay's EventLog (read-only): every injected NVS fault the core's NVS USED-KEY RULE governs
    (fault.nvs_commit of a not_landed / false_negative / false_positive policy; fault.nvs_boot read_error / wrong_size)
    must fire only after its key's domain COMPLETED A LEASE in this run - landed commits of the domain's marker key
    RESTORE_REQUIRED, then RESTORE_VERIFIED_PENDING_CLEAR, then CLEAR (the verified-restore Phase C / D) and, after that
    RESTORE_REQUIRED, a 'RESTORED OK' status of the domain - and after a landed commit of the faulted key itself.
    Returns (at least one governed fault and every one preceded so, [(key, fault, ok), ...])."""
    step: dict = {}            # domain -> index into _LEASE_MARKERS reached by its landed marker commits
    restored: set = set()      # domains with a 'RESTORED OK' status after their first landed RESTORE_REQUIRED
    stored: set = set()        # keys with a landed commit
    faults = []
    for e in log:
        kind, dat = e["kind"], e["data"]
        if kind == "fw.commit" and dat["landed"]:
            stored.add(dat["key"])
            dom = _TAG_DOM.get(dat["key"])
            if dom and dat["key"] == L.TAGS[f"{dom}.valid"]:
                i = step.get(dom, 0)
                if i < len(_LEASE_MARKERS) and dat["rec"].get("state") == _LEASE_MARKERS[i]:
                    step[dom] = i + 1
        elif (kind == "fw.status" and dat.get("dom") in ("fp", "dump", "r244") and step.get(dat["dom"], 0) >= 1
              and str(dat.get("text")).startswith("RESTORED OK")):
            restored.add(dat["dom"])
        elif ((kind == "fault.nvs_commit" and dat["mode"] in L.NVS_USED_KEY_MODES)
              or (kind == "fault.nvs_boot" and dat["fault"][0] in L.NVS_USED_KEY_BOOT_FAULTS)):
            key = dat["key"] if kind == "fault.nvs_commit" else dat["fault"][1]
            dom = _TAG_DOM.get(key)
            ok = (dom is not None and step.get(dom, 0) == len(_LEASE_MARKERS) and dom in restored and key in stored)
            what = dat["mode"] if kind == "fault.nvs_commit" else dat["fault"][0]
            faults.append((_TAG_ALIAS.get(key, key), what, ok))
    return bool(faults) and all(f[2] for f in faults), faults


def section_corpus() -> None:
    print("[CORPUS] minimal replay files: equal to the drafts, replayed by the _lab_trace engine")
    logs = {}
    for d in CORPUS_DRAFTS:
        path = CORPUS_DIR / f"{d['id']}.json"
        if not path.is_file():
            check(f"corpus {d['id']}: file exists", False, str(path.relative_to(ROOT)))
            continue
        doc = T.load_doc(path)
        same = _strip(doc) == _strip(draft_doc(d, CORPUS_COMMON, ANCHORS, PATHS))
        check(f"corpus {d['id']}: the file is the recorded form of its draft (actions, expectations, metadata)", same)
        # The verdict is the replay only: T.load_doc parses the file (CR is JSON whitespace), so a CRLF checkout
        # (core.autocrlf=true) replays identically. The corpus files' LF / canonical-form hygiene is checked after CRLF
        # normalisation by test_lab_replay_corpus (canonical_ok, NC-RC-13) and by tools/validate_repo.py, not here.
        try:
            res = T.replay(doc)
        except Exception as exc:   # a harness refusal (e.g. the core's NVS USED-KEY RULE) is a loud FAIL, never a pass
            check(f"corpus {d['id']}: replay ok (the replay raised; the firmware source is pinned)", False,
                  f"{type(exc).__name__}: {str(exc)[:400]}")
            continue
        check(f"corpus {d['id']}: replay ok (every expectation holds; digest {res.digest[:12]} equals trace_digest "
              "unless the source drifted; the firmware source is pinned)", res.ok and PATHS["fw"] in doc["source_digests"],
              f"failed={res.failed_expectations} drift={res.drift} mismatch={res.digest_mismatch} "
              f"anchors={res.anchor_problems}")
        ok, faults = prelude_in_log(res.log)
        logs[d["id"]] = res.log
        check(f"corpus {d['id']}: B5 used-key prelude - every injected NVS fault fires after its domain completed a "
              "lease in this replay (marker RESTORE_REQUIRED -> VERIFIED_PENDING_CLEAR -> CLEAR landed, then RESTORED OK) "
              "and after a landed commit of the faulted key", ok, str(faults))
    if "FW-01-b" in logs:
        clear = L.ds.Durable.MARKER_CLEAR
        cut = [e for e in logs["FW-01-b"] if not (e["kind"] == "fw.commit" and e["data"]["key"] == L.TAGS["dump.valid"]
                                                   and e["data"]["rec"].get("state") == clear)]
        check("B5 prelude check negative control: the FW-01-b replay log with the Dump marker's CLEAR commits removed "
              "(no completed lease) is rejected by the prelude check", not prelude_in_log(cut)[0]
              and prelude_in_log(logs["FW-01-b"])[0])
    bdoc = CORPUS_DIR / "FW-01-b.json"
    if bdoc.is_file():
        bad = T.load_doc(bdoc)
        bad["expect"][0]["value"] = dict(bad["expect"][0]["value"], **{"256": ORIG[256]})
        res = T.replay(bad)
        check("corpus negative control: FW-01-b with its stranded-bank expectation altered to the ORIGINAL 256 FAILS "
              "(exactly that expectation)", not res.ok and [f["index"] for f in res.failed_expectations] == [0])
    adoc = CORPUS_DIR / "FW-03-a.json"
    if adoc.is_file():
        bad = T.load_doc(adoc)
        k = next(i for i, e in enumerate(bad["expect"]) if e["observe"] == "invariants")
        bad["expect"][k]["value"] = [dict(v, tags=[]) for v in bad["expect"][k]["value"]]   # drop the N17 tag
        res = T.replay(bad)
        check("corpus negative control: FW-03-a with the N17 tag dropped from its invariants summary FAILS (exactly that "
              "expectation; the seq-free summary still resolves tags and boots)",
              not res.ok and [f["index"] for f in res.failed_expectations] == [k])


# =============================================================================================================================
# extended sweeps
# =============================================================================================================================
def section_extended() -> None:
    t0 = time.perf_counter()
    print("[EXT] extended sweeps: reboot offsets / counts, slot x value table, watchdog phase")
    rows = []
    for pre_s in (30, 300, 900, 1700):
        for order in (("fp", "dump"), ("dump", "fp")):
            r = run_fw01b(pre_s=pre_s, order=order, reboots=10, ticks=200)
            w = r["w"]
            rows.append(bank_of(w, FP_OVERRIDE_ADDRS) == FP_OVERRIDE and wlist(w, 1) == [] and w.corrupt("fp")
                        and not w.invariants(["INV-LOCKOUT-QUIET", "INV-NO-RESUME", "INV-BOOT-MIRROR"]))
    check("EXT FW-01 (b): reboot at +30 / +300 / +900 / +1700 s into the FP lease, both watchdog orders, 10 reboots x "
          "200 ticks each - always the same stranded override, zero writes, INV-LOCKOUT-QUIET and INV-BOOT-MIRROR hold",
          all(rows), str(rows))
    late = run_fw01b(pre_s=1900, reboots=1, ticks=40)
    lw = late["w"]
    check("EXT FW-01 (b) contrast: a reboot only after the FP lease ended (+1900 s) finds FP CLEAR; the latent Dump "
          "phantom then restores as ORIGINAL with zero writes (no lockout, no stranded override)",
          lw.nvs_marker("fp") == "CLEAR" and lw.nvs_marker("dump") == "CLEAR" and wlist(lw, 1) == []
          and not lw.corrupt("fp") and lw.status("dump").startswith("RESTORED OK"), lw.status("dump"))
    for o244 in (0, 2):
        r = run_fw01a(bank={244: o244}, reboots=5, ticks=100)
        check(f"EXT FW-01 (a) ORIGINAL 244 = {o244}, 5 reboots x 100 ticks: only SG-02's 244 = 2 (once per boot at "
              "most), INV-LOCKOUT-QUIET holds", all(x == (244, [2], "dump") for x in wlist(r["w"], 1))
              and len(wlist(r["w"], 1)) <= 5 and not r["w"].invariants(["INV-LOCKOUT-QUIET", "INV-BOOT-MIRROR"]),
              str(wlist(r["w"], 1)))
    table, wrong = {}, []
    values = {"soc": (55, 100), "power_w": (1000, 500, 4000, 7999)}
    for dom in ("fp", "dump"):
        for slot in range(1, 7):
            for field, vals in values.items():
                for v in vals:
                    r = run_fw02(dom, slot=slot, **{field: v})
                    w = r["w"]
                    silent = bool(viol(w, "INV-NO-SILENT-OVERRIDE", r["boot_seq"]))
                    expect_silent = dom == "dump" and field == "power_w" and v in (1000, 500)
                    table[dom, slot, field, v] = silent
                    if silent != expect_silent or not r["applied"].startswith("VERIFIED OK"):
                        wrong.append((dom, slot, field, v, silent, r["applied"][:30], w.status(dom)[:40]))
    check(f"EXT FW-02: {len(table)} phantom x slot x value cases - a silent stale-ORIGINAL rewrite happens exactly when a "
          "Dump phantom meets an owner slot power equal to ECCO's ceiling (1000 under the lab telemetry) or floor (500); "
          "FP phantoms never",
          not wrong, str(wrong[:4]))
    w = world()
    prelude(w, ("fp",))
    phantom(w, "fp")
    w.fp_start(power_w=3000, minutes=30)
    for k in range(1, 7):
        w.manual_slot_apply(k, power_w=3000)
    w.run_for(60)
    w.reboot()
    w.run_for(60)
    check("EXT FW-02 FP: all six slot powers set to FP's intended 3000 W - the FP classifier still fails closed "
          "(operator decision, no silent override)", w.status("fp").startswith("OPERATOR DECISION")
          and not viol(w, "INV-NO-SILENT-OVERRIDE"), w.status("fp"))
    res = []
    for ph in ({"dump_wd": 1}, {"dump_wd": 7000}, {"dump_wd": 14999}, {"fp_wd": 1}, {"fp_wd": 7000}):
        r = run_fw03_unreadable(bank={244: 0}, order=("fp", "dump"), phase_ms=ph)
        first = "fp" if "dump_wd" in ph else "dump"
        res.append((ph, first, n17_overlay(r) if first == "fp" else ctx_hold(r)))
    check("EXT FW-03 watchdog phase sweep (de-aligned watchdogs): whichever watchdog runs first after the boot decides "
          "- FP first gives the N17 overlay, Dump first the context hold", all(x[2] for x in res), str(res))
    for target in ("Zero Export", "Essentials"):
        r = run_fw03_triple(bank={244: 2}, target=target)
        check(f"EXT FW-03 triple with reg244 target {target}: same S4-first outcome (N17 overlay)", n17_overlay(r))
    print(f"  info  extended sweeps runtime_s {time.perf_counter() - t0:.1f}")


# =============================================================================================================================
# run
# =============================================================================================================================
section_tables()
section_fw01()
section_fw02()
section_fw03()
section_negative_controls()
section_corpus()
if EXTENDED:
    section_extended()
_PRE_KINDS = sorted({"+".join(d) for d, _t, _ok in PRELUDES})
check(f"B5 used-key prelude: every directed phantom in this run was armed only after prelude() completed a verified "
      f"lease of its domain ({len(PRELUDES)} preludes, kinds {', '.join(_PRE_KINDS)}; each ended RESTORED OK with the "
      "marker CLEAR, owned registers at ORIGINAL and no invariant violation, else the run raised)",
      bool(PRELUDES) and all(ok for _d, _t, ok in PRELUDES), str([p for p in PRELUDES if not p[2]][:3]))
print("")
print("[SUMMARY] scenarios")
for s in SCENARIOS:
    print(f"  info  {s['id']} {s['priority']} {s['classification']} ({s['grade']}, {s['confidence']}) findings "
          f"{','.join(s['findings'])} corpus {','.join(s['corpus'])}")
for fid in REPRODUCED:
    f = finding(fid)
    print(f"  info  {fid} {f['classification']} [{'DUPLICATE of ' + f['duplicate_of'] if f['duplicate_of'] else 'counted'}]"
          f" severity {f['severity']}")
print("  info  negative controls: " + ", ".join(f"{i} {o}" for i, o in NC_RESULTS))
print(f"  info  finding-reproduces checks: {len(FINDING_CHECKS)} (not counted as passes)")
COUNTED = counted()
DUPS = [f"{fid} -> {finding(fid)['duplicate_of']}" for fid in REPRODUCED if finding(fid)["duplicate_of"]]
print(f"  info  findings: {len(REPRODUCED)} reproduced, {len(COUNTED)} counted ({', '.join(COUNTED)}); "
      f"{len(DUPS)} DUPLICATE, not counted ({'; '.join(DUPS)})")
check("every finding in the table was reproduced exactly once in this run",
      sorted(REPRODUCED) == sorted(f["fid"] for f in FINDINGS), str(REPRODUCED))
BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME_S = time.perf_counter() - T0
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=FINDING_CHECKS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
