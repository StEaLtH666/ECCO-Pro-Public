#!/usr/bin/env python3
"""Property tier of the assurance lab: PB-01 firmware random sequences (FirmwareWorld), PB-02 coupled random sequences
(CoupledWorld: real FPS1 / DGS1 / SMR1 over the real firmware) and PB-03 time properties (_lab_clock against the two
hand-coded Europe/London oracles and zoneinfo, fold / gap semantics, UTC-monotonic event logs, millis() wrap across the
reboot primitive). Offline assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Everything is seeded with PUBLISHED fixed seeds (printed), bounded, and deterministic: two runs print the same lines except
the runtime. Quick mode (the default) runs PB01_QUICK firmware sequences and PB02_QUICK coupled sequences; ECCO_LAB_EXTENDED=1
or --extended runs the deeper sweeps and prints their estimate and runtime.

PB-01 (P1) model-based random sequences over the real firmware. Alphabet (generator constants WEIGHTS): fp_start, fp_end,
  dump_start (with the Dump telemetry environment first in 80 % of cases), dump_end, run_for (1..900 s, random watchdog order),
  reboot (1..60 s down, boot NVS faults absent / read_error / read_error_all / wrong_size / erase_all, keep_prefs), arm_power_cut
  (a cut at the nth matching commit / write / read / any event), nvs_policy (false_negative / not_landed / false_positive on
  random tags and states, half of them on the FP / Dump RESTORE_REQUIRED marker), modbus_policy (random outcome tables from the
  allow-list; custom_response excluded: it needs a handler), set_link, set_bus_idle, set_register, dump_force_restore,
  dump_accept, fp_operator (Force / Accept), telemetry (SOC, grid, battery), rtc_lock_windows, config_poll. Every sequence ends
  with the fixed quiescence TAIL (faults cleared, link up, bus idle, 120 s). All eight firmware invariants (the default set
  _lab_fw.INVARIANTS, INV-BOOT-MIRROR included) are checked after every action and at quiescence, with the world, so
  INV-NO-SILENT-OVERRIDE is level-based (steady fw.quiet points, each boot's settle point and world.quiet_state() at the
  end of the log; RAM-visible obligations only; one violation per episode per boot). Each violation is classified by a
  precise signature (pb01_classify); an unclassified violation FAILS the suite, is shrunk with _lab_trace.ddmin and printed
  as a replay document (the _lab_trace DSL). INV-BOOT-MIRROR has no known signature: any such violation is UNCLASSIFIED.
  That reporting path (report_unclassified -> fw_doc -> _lab_trace.dumps_doc) is exercised by the negative control
  NC-PB01-a in [2]: its shrunk counterexample is printed as a document (stdout only), passes the validate / dumps / load
  round trip (in memory), replays through _lab_trace.replay on the in-memory mutant (a temporary tier, removed again) with
  the re-execution's digest and the planted violation, and on the real firmware without it.
  Generator constraints (the executor normalises an action to what it executes NOW; the recorded DSL is the normalised form,
  so every printed / corpus document replays exactly):
    - reboot with ('absent', tag) becomes a plain reboot when the tag is not stored (_lab_fw refuses a false ABSENT of nothing);
    - NVS realism (V0.1, brief B5 change 3; _lab_fw's NVS USED-KEY RULE refuses an injected NVS fault on a key never stored
      earlier in the run with a LabHarnessError, which this property must never meet): reboot with ('read_error', tag) or
      ('wrong_size', tag) becomes a plain reboot when the tag holds no record in the NVS image now (the 'absent' rule:
      with nothing stored _dump_sim's load_record_status still reports READ_ERROR (HL-6) and a wrong-size blob would be a
      record created from nothing - both states no device reaches); an nvs_policy (false_negative / not_landed /
      false_positive, all of L.NVS_USED_KEY_MODES) drawn on a tag that holds no record now becomes run_for(0) (the only
      device route the audit leaves for a marker false negative, ESP-IDF ESP_ERR_NVS_REMOVE_FAILED, needs an earlier
      stored version of the key; the other two modes follow the brief's choice). A policy kept here is on a stored key,
      and a key stays stored earlier until an ('erase_all',) boot fault un-stores every key: reboot with ('erase_all',)
      therefore becomes a plain reboot while a kept policy is still armed (its next matching commit would be on a key
      that no longer has an earlier version; the lab refuses that at the faulting commit). Every run checks the result
      in [1] with an event-log fault scan (nvs_fault_scan: every fired commit fault and per-key boot fault hit a key
      holding a record at the injection; its hand-built negative control follows it);
    - rtc_lock_windows are drawn relative to the current instant and recorded absolute (never an empty list: _lab_fw keeps
      correction_in_progress as it is when the list is empty, _lab_fw.py 'if not self._rtc_windows' in _apply_rtc);
    - set_register: actor 'inverter' (foreign) while a domain holds the register (RAM snapshot or a durable marker other than
      CLEAR / ABSENT), else 'owner' (a change made outside any lease is the new baseline the next START snapshots). Reason:
      _lab_fw only un-marks a foreign register when ECCO writes it and keeps the stale ORIGINAL (FirmwareWorld._on_event
      'self.foreign.difference_update'), so a foreign change snapshotted by a later START read as a false override;
    - an operator Accept (dump_accept, fp_operator ACCEPT_CURRENT_STATE) is issued only when it cannot move the lab's ORIGINAL
      (the domain's registers are at ORIGINAL) or when the firmware's own operator-needed flag is set and the other lease
      domain holds nothing; otherwise it is recorded as run_for(0). Reason: _lab_fw._adopt_if_clear adopts the live bank as
      the new ORIGINAL after ANY Accept call, also one the firmware refused, and for the shared 256-261 while the other
      domain's lease holds them (core issue, reported; worked around per instance here, never edited).
PB-02 (P2) coupled random sequences: 1-2 schedule arms (FPS1 / DGS1) on non-DST dates (2026-10-21 BST, 2026-11-04 GMT) and the
  two DST dates (2026-10-25, 2027-03-28; Free Power also inside the 01:00 local hour), owner edits of the staged request
  numbers through Home Assistant (never inside the projected start / end windows: a mutation inside a projected firmware
  transaction is not modelled and would be recorded UNSUPPORTED), HA restarts (graceful, or crash with rollback 0-900 s),
  dongle reboots, API link outages and Modbus bus-busy windows near a start or a window end, random watchdog phase 0..14 s.
  INV-HF-* and the firmware invariants run on the merged log. INV-HF-WINDOW is evaluated against the packages' documented
  contract: the staged duration is min(requested, floor((window end - now + 20 s) / 60 s)) and 'a late start ends within
  about a minute of the window end' (FPS1 / DGS1 headers), so the lease end may pass the window end by up to 20 s by design,
  plus one 15 s watchdog period and the projected restore; PB02_WINDOW_BOUND_S = 90 s. Overruns above the generic 30 s bound
  are counted and reported (HF-01 owns their classification); an injected Modbus bus-busy window or dongle power cut
  overlapping the window end explains an overrun of any size (the lease must still end before the run ends); HA restarts
  and API outages explain nothing (the firmware ends the lease on its own).
PB-03 (P2) time: London tz against _fbd1_harness and tools/fbd1_soak/timeutil (and zoneinfo when importable) every 15 min of
  2026-2027 plus PB03_RANDOM random instants; fold / gap round trips for every minute of the four transition days; aware
  wall-time arithmetic; UTC monotonicity of every PB-01 and PB-02 log and of dedicated DST-night worlds; millis() = the low 32
  bits of the uptime, a Free Power lease across the 2^32 ms wrap ending on its UTC epoch, and the reboot primitive restarting
  millis() at boot_ms with UTC continuous.

MODEL ASSUMPTIONS (beyond the core modules' own, see _lab_fw / _lab_ha / _lab_clock): none new for PB-01 / PB-03. PB-02 runs
  without the dump_plant MODEL (it is not a replay action), so the firmware's own controller ends a Dump lease on a static
  plant (CONTROLLER NO RESPONSE ... failing closed); the Dump window end is then mostly not reached (stated as a gap).
  Fault-model notes that bound the findings' reachability (core behaviour, used as is): _lab_fw's nvs_policy false_negative
  (stored, False) and false_positive (nothing stored, True) are lab triggers. In the pinned ESPHome 2026.8.2 save() / sync()
  that commit_record calls back to back, a True result means nvs_set_blob returned ESP_OK in that call, so that code has no
  false-positive path (a physical one needs a silent flash program failure); the identified single-key false negative is
  ESP-IDF's ESP_ERR_NVS_REMOVE_FAILED (new value written, the old entry's erase failed), which needs an old entry of that
  key. A per-key boot READ_ERROR likewise needs a stored key:
  ds.Sim's load_record_status reports READ_ERROR for an injected per-key load fault also on a key never stored, while the
  firmware's length probe (ecco_durable_snapshot.h classify_load_failure) reports NOT_FOUND = ABSENT there unless the probe
  itself fails. Since V0.1 _lab_fw refuses those forms (NVS USED-KEY RULE) and the normaliser above never draws them; the
  corpus documents PB-01-a, PB-01-b and PB-01-d start with one completed lease of the faulted domain (a verified restore
  committed its marker CLEAR; markers are never deleted), so the faulted key was stored earlier. Consequence for F-PB01-4:
  its V0 never-used variant (false_positive on a never-stored Dump marker: ABSENT at boot) is no longer injected; PB-01-d
  is its used-device form (the previous lease's stale CLEAR), the form FW-06-c and [9] check. Fault cells: false_negative
  is ONE ESP-IDF fault cell ("new copy stored and read at the next boot, store healthy"; ESP-IDF semantics REPORTED); a
  per-key read_error heals at the next plain boot (optimistic for a data-CRC cause); read_error_all keeps the data (in
  ESPHome only after an attempted erase) - the core's disclosures (_lab_fw module docstring), used as is.
NOT MODELLED: everything the core modules list; real-world probabilities of the injected faults. The core blind spot that the
  former draft control NC-PB01-c-draft exposed (a boot that ignores a STORED RESTORE_REQUIRED marker - RAM clear, status
  'Inactive', override live - violated no V0 invariant) is closed by the hardened core: INV-NO-SILENT-OVERRIDE counts only
  RAM-visible obligations and INV-BOOT-MIRROR judges the RAM mirror at every boot. That mutant is now the counted negative
  control NC-PB01-d (killed via INV-BOOT-MIRROR); NC-PB01-c (a durable CLEAR commit) stays the classifier's guard.
Corpus: registry/tests/assurance_lab/corpus/PB-0x-<letter>.json, replayed through _lab_trace.replay in section [8].
Findings (FINDING lines, pinned by 'finding-reproduces:<id>' checks; table PB01_FINDINGS, one entry per signature). Every
  PB-01 class duplicates a finding owned by a directed suite. Each is printed 'DUPLICATE of <id>, not counted' and is NOT
  counted in LAB-SUMMARY, so the catalogue counts each one once (pattern of test_lab_fw_durability.py F-FW05-1):
  F-PB01-1            phantom-admission     = F-FW01-1 (FINDING-KNOWN:PR41-GHOST: S4 2.10 blind spot 1, the firmware's PR41
                                              on_boot comment);
  F-PB01-2            restore-over-corrupt  = F-FW05-2 UNKNOWN form (FINDING-KNOWN:N17, S4 accepted residual; sib. F-FW03-1);
  F-PB01-3            partition-erase       = F-FW04-4 erase form (FINDING-KNOWN:NVS-PARTITION-ERASE: the boot fault is
                                              erase_all; S4 2.10 blind spot 3; Dump and Free Power leases);
  F-PB01-3:single-key false-absent          = F-FW04-2 single key (FINDING-KNOWN:PLATFORM-ABSENT: the boot fault is a
                                              single-key ('absent', <marker>); Dump side F-FW04-1);
  F-PB01-4            false-positive-commit = F-FW06-3 used-device stale-CLEAR form (FINDING-NEW, low; corpus PB-01-d since
                                              V0.1 B5, also checked in [9]; the V0 never-used variant is no longer injected).
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
FINDINGS: dict = {}
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (LAB-SUMMARY: points = lines, ids = set)
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
    "PB-01-a: replay ok (": _PS_DIGEST,
    "PB-01-b: replay ok (": _PS_DIGEST,
    "PB-01-c: replay ok (": _PS_DIGEST,
    "PB-01-d: replay ok (": _PS_DIGEST,
    "PB-01-e: replay ok (": _PS_DIGEST,
    "PB-01-f: replay ok (": _PS_DIGEST,
    "PB-02-a: replay ok (": _PS_DIGEST_EXP,
    "PB-03-a: replay ok (": _PS_DIGEST,
    "PB-03-b: replay ok (": _PS_DIGEST_EXP,
    "finding-reproduces:F-PB01-1 (PB-01-a": (
        "the corpus document's reproduction requires its replay to be ok, which includes the trace-digest pin "
        "(_PS_DIGEST): fails under the phase patch in every run"),
    "finding-reproduces:F-PB01-2 (PB-01-b": (
        "the corpus document's reproduction requires its replay to be ok, which includes the trace-digest pin "
        "(_PS_DIGEST): fails under the phase patch in every run"),
    "finding-reproduces:F-PB01-3 (PB-01-c": (
        "the corpus document's reproduction requires its replay to be ok, which includes the trace-digest pin "
        "(_PS_DIGEST): fails under the phase patch in every run"),
    "finding-reproduces:F-PB01-3:single-key (PB-01-f": (
        "the corpus document's reproduction requires its replay to be ok, which includes the trace-digest pin "
        "(_PS_DIGEST): fails under the phase patch in every run"),
    "finding-reproduces:F-PB01-4 (PB-01-d": (
        "the corpus document's reproduction requires its replay to be ok, which includes the trace-digest pin "
        "(_PS_DIGEST): fails under the phase patch in every run"),
    "every PB-01 finding (and finding variant) of the catalogue reproduced in this run": (
        "aggregate of the PB-01 corpus pins (each phase-sensitive through its digest)"),
    "NC-PB-corpus: the PB-01-a document with one altered expectation": (
        "asserts 'digest still equal' against the recorded trace digest (_PS_DIGEST) - fails at any other phase (since "
        "the V0.1 review it runs under the phase patch: a replay exception of one corpus document, PB-03-b there, is "
        "that document's FAIL and the section continues)"),
    "NC-PB-corpus-summary: the PB-01-c document": (
        "asserts 'digest still equal' against the recorded trace digest (_PS_DIGEST) - fails at any other phase (since "
        "the V0.1 review it runs under the phase patch: a replay exception of one corpus document, PB-03-b there, is "
        "that document's FAIL and the section continues)"),
    "PB-01: every invariant violation in ": (
        "random-sequence property over timed action sequences on the lab scheduler: which violations a seed reaches "
        "depends on the phase - under the phase patch the extended run (2000 sequences) meets an UNCLASSIFIED "
        "INV-NO-SILENT-OVERRIDE at generator seed 366 for every patch seed (its shrunk trace also violates on the "
        "lab phase: an open triage item of the B4 report), the quick run (160 sequences) held in every run"),
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


import collections  # noqa: E402
import copy  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_ha as H  # noqa: E402
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _fbd1_harness as F  # noqa: E402  (london_offset_s / utc_of_local / EspTime oracles only)
from fbd1_soak import timeutil as TU  # noqa: E402
# zoneinfo is a third oracle only when this process can load Europe/London (never required). The probe is
# _lab_clock.zoneinfo_available(), the same value LAB-SUMMARY reports as 'zoneinfo'; without it every zoneinfo comparison
# is printed as SKIPPED and no PASS text names zoneinfo (absence of a tz database is reported, never hidden).
if C.zoneinfo_available():
    from zoneinfo import ZoneInfo
    ZI = ZoneInfo("Europe/London")
else:
    ZI = None


def zi_skipped(what: str) -> None:
    """A zoneinfo comparison that cannot run in this process: printed as SKIPPED, never as (or inside) a PASS."""
    print(f"  info  SKIPPED (zoneinfo unavailable): {what}")

UTC = timezone.utc
SUITE = "test_lab_property"
CORPUS = HERE / "corpus"
FW_REL = L.FW_REL
FPS1_REL, DGS1_REL, SMR1_REL = H.PACKAGES["fps1"], H.PACKAGES["dgs1"], H.PACKAGES["smr1"]
S4_REL = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

# =============================================================================================================================
# published seeds and budgets
# =============================================================================================================================
PB01_SEED0, PB01_QUICK, PB01_EXT, PB01_LEN = 0, 160, 2000, 12
PB02_SEED0, PB02_QUICK, PB02_EXT = 0, 14, 150
PB03_SEED, PB03_RANDOM, PB03_RANDOM_EXT = 20261025, 3000, 60000
PB01_U0 = C.parse_iso_utc("2026-10-21T10:50:00Z")       # a synthetic Wednesday, BST
PB01_WORLD = {"warmup_s": 60}
PB02_WINDOW_BOUND_S = 90.0
MUT_SEEDS = 40                                          # negative controls: the planted violation must be found within these
print(f"  info  seeds: PB-01 {PB01_SEED0}..{PB01_SEED0 + (PB01_EXT if EXTENDED else PB01_QUICK) - 1} x {PB01_LEN} actions "
      f"(+ TAIL); PB-02 {PB02_SEED0}..{PB02_SEED0 + (PB02_EXT if EXTENDED else PB02_QUICK) - 1}; PB-03 random seed {PB03_SEED}")

# =============================================================================================================================
# scenario table (anchors are text snippets that occur exactly once; line numbers are information only)
# =============================================================================================================================
SCENARIOS = {
    "PB-01": {
        "title": "Firmware random sequences: FP / Dump START / END, ticks, reboots at random events, NVS / Modbus faults, bus, "
                 "link, foreign writes, operator actions; all firmware invariants; known residuals by signature",
        "priority": "P1", "tier": "firmware",
        "ownership": "one dongle; Free Power and Dump to Grid leases, register 244 and the manual TOU owner domains as the "
                     "firmware defines them; the synthetic SITE is the owner's ORIGINAL; an owner change outside any lease is "
                     "the new ORIGINAL, a change while a domain holds the register is foreign (excluded until ECCO rewrites it)",
        "anchors": [
            (FW_REL, 'else if (id(free_power_active_persisted) || id(free_power_snapshot_valid) || '
                     'id(free_power_operation_in_progress)) id(dump_status).publish_state("REJECTED - Free Power '
                     'override/recovery owns inverter settings");'),
            (FW_REL, 'else if (id(dump_active_persisted) || id(dump_snapshot_valid)) id(free_power_status).publish_state('
                     '"REJECTED - Dump to Grid override/recovery owns inverter settings");'),
            (FW_REL, '"START FAILED - could not durably commit the recovery snapshot; nothing written"'),
            (FW_REL, "domain's admission gate before the next reboot."),
            (FW_REL, 'ESP_LOGW("free_power", "Free Power was ACTIVE at last shutdown'),
            (FW_REL, "export containment not armed - do NOT reboot: a reboot may make the record read as absent"),
            (S4_REL, "The commit result itself can be a false negative or a false positive"),
            (S4_REL, "| **N17** | P1 restores (FP and Dump) carry no cross-domain terms."),
            (S4_REL, "A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear)"),
            (S4_REL, "An UNKNOWN or corrupt domain counts as holding an unresolved obligation on everything it owns."),
            (S4_REL, "ESPHome erases the partition when `nvs_open` fails"),
            (S4_REL, "Markers are never deleted by firmware"),
            (FW_REL, "an obligation cannot be ruled out; inverter writes locked - do NOT reboot"),
            ("registry/tests/check_fbb_esphome_source_facts.py", "nvs_flash_deinit(); nvs_flash_erase(); nvs_flash_init();"),
            ("firmware/include/ecco_durable_snapshot.h", "Returns true only if BOTH the queue step and the flash sync succeeded"),
            (FW_REL, "Free Power<->Dump dual durable-obligation dead-end (256-261)"),
            (S4_REL, "A partition erase (E04 P10; ESPHome erases the partition when"),
        ],
        "invariant": "INV-WS, INV-ONE-LEASE, INV-NO-2ND-RESTORER, INV-NO-RESUME, INV-LOCKOUT-QUIET, INV-NO-SILENT-OVERRIDE "
                     "(level-based, RAM-visible obligations only), INV-RESTORE-BOUND and INV-BOOT-MIRROR after every action "
                     "and at quiescence; every violation matches a known signature (INV-BOOT-MIRROR has none)",
        "failure_outcome": "an unclassified invariant violation (a new class: printed shrunk replay document, suite FAIL)",
        "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "medium",
        "classification_note": "FINDING-NEW because of F-PB01-4 (= F-FW06-3, low confidence, trigger reachability UNKNOWN); "
                               "the other classes are FINDING-KNOWN:PR41-GHOST (F-PB01-1), N17 (F-PB01-2), "
                               "NVS-PARTITION-ERASE (F-PB01-3, boot fault erase_all) and PLATFORM-ABSENT (F-PB01-3:single-key, "
                               "a single-key false ABSENT); every class duplicates a directed-suite finding (not counted in "
                               "LAB-SUMMARY); no class beyond them in 160 quick / 2000 extended sequences",
        "corpus": ["PB-01-a", "PB-01-b", "PB-01-c", "PB-01-d", "PB-01-e", "PB-01-f"],
    },
    "PB-02": {
        "title": "Coupled random sequences: schedule arms on non-DST and DST dates, owner edits, HA restarts, dongle reboots, "
                 "bus windows, API link outages; INV-HF-* and the firmware invariants on the merged log",
        "priority": "P2", "tier": "coupled",
        "ownership": "Home Assistant's FPS1 / DGS1 own their scheduled runs, SMR1 the owner's staged request numbers, the "
                     "firmware owns the inverter writes; the owner edits only staged numbers, never inside a projected window",
        "anchors": [
            (FPS1_REL, "(((window_end | float(0)) - as_timestamp(now()) + 20) / 60) | round(0, 'floor') | int(0)] | min }}"),
            (FPS1_REL, "its full duration (as before), a late start ends within about a minute of the window end;"),
            (DGS1_REL, "full duration, a late start ends within about a minute of the window end;"),
            (SMR1_REL, "('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'Free Power snapshot pending restore'),"),
            (FW_REL, "if (id(free_power_restore_requested)) return true;"),
        ],
        "invariant": "INV-HF-ONE-LEASE, INV-HF-ARM-OFF, INV-HF-SMR1-QUIET, INV-HF-WINDOW (documented late-start allowance, "
                     "90 s), INV-HF-OWNER-INTENT, INV-HF-NO-FALSE-SUCCESS and the firmware invariants",
        "failure_outcome": "an unexplained coupled or firmware violation, or a harness exception",
        "classification": "PASS", "grade": "VERIFIED", "confidence": "medium", "corpus": ["PB-02-a"],
    },
    "PB-03": {
        "title": "Time properties: London tz vs the two oracles (and zoneinfo) every 15 min of 2026-2027 and at random "
                 "instants; fold / gap round trips; UTC-monotonic logs; millis() wrap across the reboot primitive",
        "priority": "P2", "tier": "firmware",
        "ownership": "the lab clock is the UTC epoch; local time is derived (London rule since 1996); millis() is the "
                     "simulator's 64-bit uptime masked to 32 bits",
        "anchors": [
            ("registry/tests/assurance_lab/_lab_clock.py", "def london_offset_s(utc_s) -> int:"),
            ("registry/tests/_fbd1_harness.py", "def london_offset_s(utc_s: int) -> int:"),
            ("tools/fbd1_soak/timeutil.py", "def local_to_utc(local: datetime, fold: int = 0) -> datetime:"),
            ("registry/tests/_dump_sim.py", "return self.now_ms & 0xFFFFFFFF"),
            (FW_REL, "timezone: Europe/London"),
            (FW_REL, "return (uint32_t) now.timestamp >= id(free_power_end_epoch);"),
        ],
        "invariant": "INV-TZ-ORACLE, INV-TZ-ROUNDTRIP, INV-TZ-FOLD, INV-UTC-MONOTONIC, INV-MILLIS-WRAP",
        "failure_outcome": "a disagreement with an oracle, a lost fold / gap round trip, a UTC regression in a log, or a lease "
                           "that does not end on its UTC epoch across the millis() wrap",
        "classification": "PASS", "grade": "VERIFIED", "confidence": "high", "corpus": ["PB-03-a", "PB-03-b"],
    },
}
# classified PB-01 signatures -> finding (each checked twice, independently, against the source and the classification
# vocabulary; every one duplicates a directed-suite finding, so it is printed and pinned here but counted once, by its
# owning suite). One entry per signature; a 'variant' names a second signature of the same finding whose classification
# differs (its label is '<fid>:<variant>').
PB01_FINDINGS = {
    "phantom-admission": {
        "fid": "F-PB01-1", "classification": "FINDING-KNOWN:PR41-GHOST", "duplicate_of": "F-FW01-1", "corpus": "PB-01-a",
        "confidence": "high (mechanism); real-world occurrence low-medium, rate UNKNOWN",
        "severity": "availability / cost (low-medium) plus diagnostics: an R1 single-owner design-rule breach in the same "
                    "runtime (two durable obligations on 256-261); no unsafe write in any probed chain: the ghost START wrote "
                    "nothing, a reboot inside the admitted lease meets PR41's dual lockout (export contained at 244 = 2, "
                    "operator needed: F-FW01-2), a reboot after it restores or stops at OPERATOR DECISION REQUIRED",
        "title": "Phase-B marker commit false negative leaves a durable RESTORE_REQUIRED ghost with RAM clear; the other "
                 "domain's START is admitted in the same runtime and writes the shared 256-261",
        "relation": "DUPLICATE of F-FW01-1 (FW-01 owns the chain; F-FW05-1 is the same root); known risk PR41-GHOST (S4 "
                    "2.10 blind spot 1; second reference the firmware's on_boot PR41 comment, KNOWN_RISK_REFS), previously "
                    "N15 as the closest id; the reg244 Apply gate also reads only Free Power's RAM flags (source read, not "
                    "executed here: the N10 pair)",
        "reachability": "trigger: nvs false_negative on a used Phase-B marker, drawn by the PB-01 generator; device "
                        "reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                        "INFERRED: a single-key commit false negative on the Phase-B marker itself. ESPHome 2026.8.2 sync() "
                        "clears its whole pending queue and the data commit's sync runs just before in the same lambda, so "
                        "the 'unrelated pending key' route cannot reach this commit; the remaining route is ESP-IDF "
                        "ESP_ERR_NVS_REMOVE_FAILED (the new value is written, the old entry's erase fails), which needs a "
                        "flash-operation failure and an old marker entry (any device that completed a lease before: "
                        "PB-01-a starts with one); then a second START (owner or HA schedule) before any reboot; rate UNKNOWN",
        "repair": "description only (= F-FW01-1): the two START scripts only - when the Phase-B marker commit returns false "
                  "after the data record committed, fill the RAM mirror exactly as the success branch does (snapshot_valid, "
                  "marker_state RESTORE_REQUIRED, end epoch and intended targets, restore_requested), the pattern of the "
                  "existing 'snapshot committed, start aborted' path; the other domain's existing gates then refuse and the "
                  "domain's own watchdog performs the verified no-op restore that commits CLEAR (a true negative then costs "
                  "availability only); no new write path, no NVS read-back, every gate stricter; PR41 / S4 stay the boot "
                  "backstop",
    },
    "restore-over-corrupt-holder": {
        "fid": "F-PB01-2", "classification": "FINDING-KNOWN:N17", "duplicate_of": "F-FW05-2", "corpus": "PB-01-b",
        "confidence": "high (mechanism and classification); reachability low, rate UNKNOWN",
        "severity": "low: an ownership-integrity (R1 policy) residual, not a hazardous write: the restoring domain writes its "
                    "own verified ORIGINAL; in the single-fault form the other domain holds no obligation (UNKNOWN only), "
                    "so the bank ends at the owner's ORIGINAL and Dump stays visibly UNKNOWN-locked ('do NOT reboot'); "
                    "overwriting a genuine obligation needs a second independent fault (a PR41-GHOST phantom: START refuses "
                    "while the other snapshot is valid)",
        "title": "A trusted FP (or Dump) P1 restore writes the shared 256-261 while the other domain is corrupt / UNKNOWN-"
                 "locked, over a possibly-existing (UNKNOWN) or, with a ghost, genuine obligation",
        "relation": "DUPLICATE of F-FW05-2 (its UNKNOWN form: a used Dump whose marker reads READ_ERROR plus an FP lease "
                    "across the reboot); sibling F-FW03-1 (triple / phantom constructions of the same residual); S4 N17 "
                    "accepted residual (registry class OPEN-GAP vs 'Accepted residual' in S4: core metadata note)",
        "reachability": "trigger: boot read_error on a stored marker key, drawn by the PB-01 generator; device "
                        "reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                        "INFERRED: a PER-KEY boot load failure of the other domain's marker on a stored key (READ_ERROR when "
                        "the length probe succeeds but the data read fails, or WRONG_SIZE / MALFORMED) while this domain "
                        "holds a lease across the reboot; a whole-NVS failure makes both domains UNKNOWN and nothing is "
                        "written; rate UNKNOWN",
        "repair": "none required: S4 records N17 as an accepted residual. A bare '!other_corrupt' term is NOT a safe "
                  "standalone change: the gate is the wrapper restore_free_power_snapshot (not the dispatch), shared by "
                  "the automatic watchdog (P1) and the owner's End (P2, always admissible per S4); the term would strand "
                  "the live grid-charge override (FP) or leave 244 = 0 uncontained (Dump) until an operator resolves the "
                  "other domain (FW-03 / FW-05 mutants). The root cause is the boot arbitration being skipped when either "
                  "side is corrupt; any R1 enforcement belongs to the boot lockout under an owner decision. Description only",
    },
    "partition-erase": {
        "fid": "F-PB01-3", "classification": "FINDING-KNOWN:NVS-PARTITION-ERASE", "duplicate_of": "F-FW04-4",
        "corpus": "PB-01-c",
        "confidence": "high (mechanism and classification); reachability low-frequency, INFERRED",
        "severity": "Dump: safety, bounded (244 = 0 and the lease ceiling stay live with no lease end, no Stop SOC "
                    "supervision and no export trip; the inverter's own export limit 245 and battery protections are never "
                    "written by ECCO); Free Power: cost (grid charging on every slot); diagnostics: status 'Inactive', no "
                    "obligation surface (after an erase the factory Dump limits text is the only indirect symptom)",
        "title": "A held marker lost to a whole-partition NVS erase at boot (boot fault erase_all; the preferences are lost "
                 "too) reads ABSENT = CLEAR: the lease override stays live with no visible obligation",
        "relation": "DUPLICATE of F-FW04-4 (the whole-partition erase form, Dump and Free Power leases; PB-01-c is that "
                    "form); known risk NVS-PARTITION-ERASE (S4 2.10 blind spot 3); the single-key form of the "
                    "same signature family is F-PB01-3:single-key (PLATFORM-ABSENT)",
        "reachability": "trigger: boot erase_all, drawn by the PB-01 generator (path VERIFIED, esphome "
                        "components/esp32/preferences.cpp:131-148); device reachability: UNKNOWN pending the ESP-IDF "
                        "host NVS test. "
                        "the code path is VERIFIED from source: ESPHome 2026.8.2 ESP32Preferences::open() erases the "
                        "partition when nvs_open fails (source fact pinned in "
                        "registry/tests/check_fbb_esphome_source_facts.py); what triggers nvs_open to fail is INFERRED; "
                        "rate UNKNOWN",
        "repair": "no firmware-local evidence survives an erase (NVS and every preference are gone); candidates are the FB-D "
                  "witness or a read-only Home Assistant notification when a lease it saw disappears across a dongle "
                  "reboot without a restore completion. Lease-marker provisioning is not minimal (a new durable write and "
                  "an open S4 / FB-D owner decision). Description only",
    },
    "false-absent": {
        "fid": "F-PB01-3", "variant": "single-key", "classification": "FINDING-KNOWN:PLATFORM-ABSENT",
        "duplicate_of": "F-FW04-2", "corpus": "PB-01-f",
        "confidence": "high (mechanism and classification); reachability low-frequency, REPORTED / INFERRED",
        "severity": "as F-PB01-3: Dump safety, bounded (244 = 0 and the ceiling live, unsupervised); Free Power cost; "
                    "diagnostics: status 'Inactive', no obligation surface",
        "title": "A held marker lost at boot to a single-key false ABSENT (boot fault ('absent', <marker>)) reads as CLEAR: "
                 "the lease override stays live with no visible obligation",
        "relation": "DUPLICATE of F-FW04-2 (Free Power single key; PB-01-f is that form); the property's Dump instance is "
                    "F-FW04-1; known risk PLATFORM-ABSENT (the firmware's own 'a reboot may make the record read as "
                    "absent' status text)",
        "reachability": "trigger: boot absent of a held marker, drawn by the PB-01 generator; device reachability: "
                        "PLAUSIBLE-UNDER-ASSUMPTIONS, rate UNKNOWN pending the ESP-IDF host NVS test. "
                        "REPORTED: a CRC-bad entry is erased on read and then reads NOT_FOUND (S4 record), and the "
                        "documented READ_ERROR boot ('do NOT reboot') reads ABSENT after any later reboot, which can come "
                        "without the owner (ESPHome's default no-client reboot_timeout); rate UNKNOWN",
        "repair": "smallest, read-only (= F-FW04-1's cross-check): at boot, a marker that loads ABSENT while the same "
                  "domain's data record loads with active_persisted == 1 (post-activation evidence only, never a bare data "
                  "or retry record) enters the existing READ_ERROR-style UNKNOWN lockout, no commit, no Modbus. "
                  "Description only",
    },
    "false-positive-commit": {
        "fid": "F-PB01-4", "classification": "FINDING-NEW", "duplicate_of": "F-FW06-3", "corpus": "PB-01-d",
        "confidence": "low (trigger); the boot consequence is high (it equals F-FW04-1 on a never-used domain)",
        "severity": "safety, bounded as F-FW04-1 (Dump: 244 = 0 and the ceiling live, unsupervised, status 'Inactive'); "
                    "Free Power twin: cost",
        "title": "A Phase-B marker commit that returns true without storing the record (lab false_positive), then a reboot "
                 "during the lease: the override stays live with no obligation; the marker keeps the previous lease's "
                 "stale CLEAR on a used device (PB-01-d, FW-06-c, checked in [9])",
        "relation": "DUPLICATE of F-FW06-3 (FW-06 owns it; F-FW06-2 is the Free Power twin); PB-01-d is its used-device "
                    "form since V0.1 B5 (a completed Dump lease first); the V0 never-used variant (marker ABSENT, end state "
                    "equal to F-FW04-1) is no longer injected: _lab_fw's NVS USED-KEY RULE refuses a commit fault on a "
                    "key never stored earlier in the run",
        "reachability": "trigger: nvs false_positive on the used Dump Phase-B marker (dump.valid); device reachability: "
                        "UNKNOWN pending the ESP-IDF host NVS test. "
                        "No route at the ESPHome layer: S4 states that a commit result can be a false positive, but in "
                        "ESPHome 2026.8.2 commit_record's save() always queues and sync() returns false when nvs_set_blob "
                        "errors, so True means the write returned ESP_OK in that call; an ESP-IDF route (an INVALID page "
                        "after a reported flash-op failure) was described by the V0 independent audit (medium confidence, "
                        "not executed); trigger UNKNOWN pending the ESP-IDF host NVS test (on a used device the stale "
                        "CLEAR also needs the old entry to stay readable); then a reboot during the lease",
        "repair": "only if such a trigger is confirmed: in the three Phase-B guards (FP, Dump, reg244) read the marker back "
                  "with the existing direct NVS read primitive read_direct_t (not load_record, which can be served from "
                  "the pending-save queue) before the RAM mirror is set and before any override write; require "
                  "RESTORE_REQUIRED, else take the existing commit-failure path (START FAILED, nothing written). No write "
                  "path added. The F-FW04-1 boot cross-check covers only the never-used variant. Description only",
    },
}
def flabel(f: dict) -> str:
    """A finding record's label: its fid, or '<fid>:<variant>' for a variant signature with its own classification."""
    return f["fid"] + (f":{f['variant']}" if f.get("variant") else "")


SIG_BY_LABEL = {flabel(f): s for s, f in PB01_FINDINGS.items()}     # unique: checked in [0]


def counted() -> list:
    """Reported findings that this suite owns (a DUPLICATE is counted by its owning suite)."""
    return [lab for lab in FINDINGS if not PB01_FINDINGS[SIG_BY_LABEL[lab]].get("duplicate_of")]


def report_finding(label: str, corpus_id: str) -> None:
    """Print one FINDING line (and its record) the first time the finding (or finding variant) reproduces."""
    if label in FINDINGS:
        return
    f = PB01_FINDINGS[SIG_BY_LABEL[label]]
    FINDINGS[label] = f["classification"]
    dup = f" DUPLICATE of {f['duplicate_of']}, not counted;" if f.get("duplicate_of") else ""
    print(T.finding_line(label, f"[{f['classification']};{dup} confidence {f['confidence']}] {f['title']} "
                                f"(corpus {corpus_id})"))
    for k in ("severity", "relation", "reachability", "repair"):
        print(f"  info    {label} {k}: {f[k]}")


def section_anchors() -> None:
    print("[0] scenario source anchors occur exactly once (line numbers are information only)")
    bad = []
    for sid, sc in SCENARIOS.items():
        for path, text in sc["anchors"]:
            n, _line = T.anchor_count(path, text)
            if n != 1:
                bad.append((sid, path, n, text[:60]))
            else:     # exactly once: _lab_trace.anchor_line gives its line (information only)
                print(f"  info  {sid} {path}:{T.anchor_line(path, text)} {text[:70]!r}")
    check(f"every scenario anchor occurs exactly once ({sum(len(s['anchors']) for s in SCENARIOS.values())} anchors)",
          not bad, str(bad))
    labels = [flabel(f) for f in PB01_FINDINGS.values()]
    parsed, problems = {}, []
    for sig, f in PB01_FINDINGS.items():
        try:
            parsed[sig] = T.parse_classification(f["classification"])
        except T.LabTraceError as exc:      # recorded as a FAIL of the table check below, never a pass
            problems.append(f"{sig}: {exc}")
    check(f"PB01_FINDINGS: {len(labels)} signatures with unique labels ({', '.join(labels)}), every classification in the "
          "vocabulary (a FINDING-KNOWN names a registered risk), every duplicate names its owner's finding id",
          len(set(labels)) == len(labels) and not problems
          and all(str(f.get("duplicate_of") or "F-").startswith("F-") for f in PB01_FINDINGS.values()), str(problems))
    for rid in sorted({rid for _k, rid in parsed.values() if rid}):
        r = T.known_risk(rid)
        refs = T.KNOWN_RISK_REFS.get(rid, ())
        check(f"known risk {rid} ({r['class']}) is registered and its anchor occurs exactly once ({r['path']}); its "
              f"{len(refs)} secondary reference(s) too", T.anchor_count(r["path"], r["text"])[0] == 1
              and all(T.anchor_count(p, t)[0] == 1 for p, t in refs))


# =============================================================================================================================
# PB-01: generator, executor, classifier
# =============================================================================================================================
TAG_ALIASES = sorted(L.TAGS)
MARKERS = ("fp.valid", "dump.valid", "r244.valid")
RR = L.ds.Durable.MARKER_RESTORE_REQUIRED
HELD = ("RESTORE_REQUIRED", "PENDING_CLEAR")
WEIGHTS = (("fp_start", 10), ("fp_end", 5), ("dump_start", 10), ("dump_end", 5), ("run_for", 22), ("reboot", 7),
           ("arm_power_cut", 4), ("nvs_policy", 7), ("modbus_policy", 4), ("set_link", 3), ("set_bus_idle", 2),
           ("set_register", 3), ("dump_force_restore", 2), ("dump_accept", 2), ("fp_operator", 3), ("telemetry", 5),
           ("rtc_lock_windows", 2), ("config_poll", 1))
TAIL = (("modbus_policy", {"table": None}), ("set_link", {"up": True}), ("set_bus_idle", {"idle": True}),
        ("run_for", {"seconds": 120}))
_SNAP = {"fp": "free_power_snapshot_valid", "dump": "dump_snapshot_valid", "r244": "reg244_snapshot_valid"}
_OPN = {"fp": "free_power_operator_needed", "dump": "dump_operator_needed"}


def pb01_gen(seed: int, n: int = PB01_LEN) -> list:
    """A pure function of the seed: [(action, args)] (args before normalisation)."""
    r = random.Random(seed)
    acts = []
    names, weights = [w[0] for w in WEIGHTS], [w[1] for w in WEIGHTS]
    for _ in range(n):
        a = r.choices(names, weights)[0]
        if a == "fp_start":
            args = {"power_w": r.randrange(500, 8001, 100), "minutes": r.randint(1, 40), "arm": r.random() > 0.1}
        elif a == "dump_start":
            if r.random() < 0.8:
                acts.append(("telemetry", {"grid_w": -1000, "batt_w": 1050}))
            args = {"power_w": r.randrange(500, 8001, 100), "stop_soc": r.randint(10, 60), "minutes": r.randint(1, 40),
                    "arm": r.random() > 0.1}
        elif a == "run_for":
            args = {"seconds": r.randint(1, 900), "wd_order": r.choice([["fp", "dump"], ["dump", "fp"]])}
        elif a == "reboot":
            if r.random() < 0.55:
                nf = None
            else:
                k = r.choice(["absent", "absent", "read_error", "read_error_all", "wrong_size", "erase_all"])
                nf = [k] if k in ("read_error_all", "erase_all") else [
                    k, r.choice(MARKERS) if k == "absent" or r.random() < 0.6 else r.choice(TAG_ALIASES)]
            args = {"down_s": r.randint(1, 60), "nvs_fault": nf, "keep_prefs": r.random() > 0.1}
        elif a == "arm_power_cut":
            kind = r.choice(["fw.commit", "fw.write", "fw.read", None])
            args = {"kind": kind, "nth": r.randint(1, 3), "down_s": r.randint(1, 30)}
            if kind == "fw.commit" and r.random() < 0.6:
                args["key"] = r.choice(TAG_ALIASES)
            if kind == "fw.write" and r.random() < 0.5:
                args["addr"] = r.choice([230, 232, 244, 256, 268, 274])
        elif a == "nvs_policy":
            if r.random() < 0.5:
                tag, st = r.choice(MARKERS[:2]), RR
            else:
                tag = r.choice(TAG_ALIASES)
                st = r.choice([None, 0, 1, 2]) if tag.endswith(".valid") else None
            args = {"tag": tag, "state": st, "mode": r.choice(["false_negative", "false_negative", "not_landed",
                                                              "false_positive"]), "times": r.randint(1, 2)}
        elif a == "modbus_policy":
            if r.random() < 0.25:
                table = None
            else:
                op = r.choice(["read", "write"])
                outs = [o for o in (L.READ_OUTCOMES if op == "read" else L.WRITE_OUTCOMES) if o != "custom_response"]
                key = r.choice([f"{op}:*", f"{op}:244", f"{op}:256", "write:230" if op == "write" else "read:244x12"])
                v = [r.choice(outs) for _ in range(r.randint(1, 3))] if r.random() < 0.5 else r.choice(outs)
                table = {key: v}
            args = {"table": table}
        elif a == "set_link":
            args = {"up": r.random() < 0.5}
        elif a == "set_bus_idle":
            args = {"idle": r.random() < 0.5}
        elif a == "set_register":
            args = {"addr": r.choice(L.OWNED), "value": r.randint(0, 9000), "actor": r.choice(["inverter", "owner"])}
        elif a == "fp_operator":
            args = {"action": r.choice(["FORCE_RESTORE_ORIGINAL", "ACCEPT_CURRENT_STATE"])}
        elif a == "telemetry":
            args = {"soc": r.randint(5, 100), "grid_w": r.choice([-1000, -500, 0, 300]),
                    "batt_w": r.choice([0, 500, 1050, 3000])}
        elif a == "rtc_lock_windows":
            s = r.randint(0, 300)
            args = {"rel": [s, s + r.randint(5, 200)]}
        else:
            args = {}
        acts.append((a, args))
    return acts


def _holds(w, dom: str) -> bool:
    return bool(w.sim.g[_SNAP[dom]]) or w.nvs_marker(dom) not in ("CLEAR", "ABSENT")


def _armed_used_key_policies(w) -> int:
    """The number of nvs_policy entries still armed (not consumed) whose mode the lab's NVS USED-KEY RULE judges when the
    fault fires (L.NVS_USED_KEY_MODES). A read-only view of FirmwareWorld._nvs_policies (the list nvs_policy appends to and
    the commit wrapper consumes, _lab_fw.FirmwareWorld._install_commit); nothing is evaluated or changed."""
    return sum(1 for p in w._nvs_policies
               if p["mode"] in L.NVS_USED_KEY_MODES and (p["left"] is None or p["left"] > 0))


def pb01_normalise(w, a: str, args: dict) -> tuple:
    """The action as executed now (module docstring: generator constraints)."""
    args = copy.deepcopy(args)
    if a == "reboot" and args.get("nvs_fault"):
        kind = args["nvs_fault"][0]
        if kind == "absent" or kind in L.NVS_USED_KEY_BOOT_FAULTS:
            if L.TAGS[args["nvs_fault"][1]] not in w.sim.nvs:      # a per-key boot fault needs a stored record now
                args["nvs_fault"] = None
        elif kind == "erase_all" and _armed_used_key_policies(w):
            args["nvs_fault"] = None     # the erase would un-store an armed policy's key (it would fire on a new key)
    if a == "nvs_policy" and args["mode"] in L.NVS_USED_KEY_MODES and L.TAGS[args["tag"]] not in w.sim.nvs:
        return "run_for", {"seconds": 0}     # an injected commit fault needs an earlier stored version of the key
    if a == "rtc_lock_windows":
        rel = args.pop("rel")
        args = {"windows": [[w.t_utc + rel[0], w.t_utc + rel[1]]]}
    if a == "dump_accept" or (a == "fp_operator" and args.get("action") == "ACCEPT_CURRENT_STATE"):
        dom = "dump" if a == "dump_accept" else "fp"
        other = "fp" if dom == "dump" else "dump"
        harmless = all(w.bank[x] == w.original[x] for x in L.DOMAIN_REGS[dom] if x not in w.foreign)
        if not harmless and not (w.sim.g[_OPN[dom]] and not _holds(w, other)):
            return "run_for", {"seconds": 0}
    if a == "set_register":
        held = any(args["addr"] in L.DOMAIN_REGS[d] and _holds(w, d) for d in ("fp", "dump", "r244"))
        args["actor"] = "inverter" if held else "owner"
    return a, args


def pb01_execute(acts, *, seed: int, fw=None, tail: bool = True) -> tuple:
    """Run the actions exactly as _lab_trace.replay would (same world factory, same replay.action events): (world,
    executed DSL actions, {(inv, seq): (action index, violation)}). Invariants are checked after every action."""
    w = (L.make_world(utc_start=PB01_U0, seed=seed, **PB01_WORLD) if fw is None
         else L.FirmwareWorld(fw, utc_start=PB01_U0, seed=seed, **PB01_WORLD))
    done, viol = [], {}
    for i, (a, args) in enumerate(list(acts) + (list(TAIL) if tail else [])):
        a, args = pb01_normalise(w, a, args)
        at = w.t_utc - PB01_U0
        w.log.append(t_utc=w.t_utc, up_ms=None, boot=None, src="lab", kind="replay.action",
                     data={"i": i, "do": a, "args": args})
        L.ACTIONS[a](w, **copy.deepcopy(args))
        done.append({"at_s": at, "do": a, "args": args})
        for v in L.check_invariants(w.log, world=w):
            viol.setdefault((v["inv"], v["seq"]), (i, v))
    return w, done, viol


def _fp_commit_before(evs, i: int, d: str) -> bool:
    boot_start = max([j for j in range(i) if evs[j]["kind"] == "fw.boot"] or [0])
    return any(e["kind"] == "fault.nvs_commit" and e["data"]["key"] == L.MARKER_TAGS[d]
               and e["data"]["mode"] == "false_positive" and e["data"]["rec"].get("state") == RR
               for e in evs[boot_start:i])


LOSS_CAUSES = ("partition-erase", "false-absent", "false-positive-commit")     # = the three silent-override signatures


def lost_obligations(evs, upto: int) -> dict:
    """{dom: cause} for obligations lost across a boot at or before seq `upto` (the latest loss of a domain wins): the
    domain held a RAM snapshot or a durable marker just before the cut, and either its marker record is not in the NVS image
    the new boot starts from because of an injected boot fault - ('erase_all',): cause 'partition-erase' (known risk
    NVS-PARTITION-ERASE), ('absent', its marker): cause 'false-absent' (a single-key loss, PLATFORM-ABSENT) - or its durable
    marker was not held (ABSENT on a never-used domain, the previous lease's CLEAR on a used one) because its
    RESTORE_REQUIRED commit returned true in that boot without storing the record: cause 'false-positive-commit'."""
    lost, last = {}, None
    for i, e in enumerate(evs[:upto + 1]):
        k = e["kind"]
        if k == "fw.obl":
            last = e["data"]
        elif k == "fw.booted":
            last = e["data"]["obl"]
        elif k == "fw.boot" and last is not None:
            fault, keys = e["data"]["nvs_fault"], set(e["data"]["keys"])
            for d in ("fp", "dump", "r244"):
                if not (last[d]["snap"] or last["nvs"][d] in HELD):
                    continue
                present = L.MARKER_TAGS[d] in keys
                if not present and fault and fault[0] == "erase_all":
                    lost[d] = "partition-erase"
                elif not present and fault and fault[0] == "absent" and fault[1] == L.MARKER_TAGS[d]:
                    lost[d] = "false-absent"
                elif last["nvs"][d] in ("ABSENT", "CLEAR") and _fp_commit_before(evs, i, d):
                    lost[d] = "false-positive-commit"
    return lost


def pb01_classify(v: dict, evs: list) -> tuple:
    """(classification, signature) of one firmware invariant violation, or (None, reason) when no signature matches.
    Signatures (precise, from the event log only):
      phantom-admission           INV-NO-2ND-RESTORER, writer = the other lease domain, the holder's durable marker is
                                  RESTORE_REQUIRED while its RAM snapshot is clear, and in the same boot an injected
                                  false_negative commit of the holder's RESTORE_REQUIRED marker preceded the write;
      restore-over-corrupt-holder INV-NO-2ND-RESTORER tagged N17 by a restore script, or INV-LOCKOUT-QUIET: a restore script of
                                  one lease domain writes only the shared 256-261 while exactly the other lease domain is
                                  corrupt / UNKNOWN-locked (S4 N17);
      partition-erase / false-absent / false-positive-commit   INV-NO-SILENT-OVERRIDE (reported at its fw.quiet record:
                                  the level-based checker anchors a violation there whenever the record holds the reported
                                  state) whose differing registers all belong to domains whose obligation was lost across a
                                  boot (lost_obligations), the domains lost to exactly ONE cause covering the difference:
                                  'partition-erase' (boot fault erase_all -> NVS-PARTITION-ERASE), 'false-absent' (a
                                  single-key ('absent', <marker>) -> PLATFORM-ABSENT) or 'false-positive-commit'. Two causes
                                  that each cover it (ambiguous) or only their union (mixed) match no signature.
      INV-BOOT-MIRROR             no known signature: every violation is UNCLASSIFIED (investigate to root cause).
    The classification is the one of the signature's finding in PB01_FINDINGS."""
    def cls(sig):
        return PB01_FINDINGS[sig]["classification"], sig
    inv, e = v["inv"], evs[v["seq"]]
    if inv in ("INV-NO-2ND-RESTORER", "INV-LOCKOUT-QUIET") and e["kind"] == "fw.write":
        d = e["data"]
        span = set(range(d["addr"], d["addr"] + len(d["vals"])))
        other = {"fp": "dump", "dump": "fp"}.get(d["dom"])
        restore = any("restore" in s for s in d["scripts"])
        if inv == "INV-NO-2ND-RESTORER":
            if "N17" in v["tags"] and restore:
                return cls("restore-over-corrupt-holder")
            if other and d["nvs"][other] == "RESTORE_REQUIRED" and not d["ram"][f"{other}_snap"]:
                boot_start = max(j for j in range(v["seq"] + 1) if evs[j]["kind"] == "fw.boot")
                if any(x["kind"] == "fault.nvs_commit" and x["data"]["key"] == L.MARKER_TAGS[other]
                       and x["data"]["mode"] == "false_negative" and x["data"]["rec"].get("state") == RR
                       for x in evs[boot_start:v["seq"]]):
                    return cls("phantom-admission")
            return None, "2nd-restorer without a known signature"
        locked = [x for x in ("fp", "dump", "r244") if d["ram"][f"{x}_corrupt"] and span & L.DOMAIN_REGS[x]]
        if other and restore and locked == [other] and span <= L.TOU_POWER:
            return cls("restore-over-corrupt-holder")
        return None, f"lockout-quiet: writer {d['dom']} {d['scripts'][-1:]} locked {locked}"
    if inv == "INV-NO-SILENT-OVERRIDE":
        if e["kind"] != "fw.quiet":
            return None, f"silent override evaluated at a {e['kind']} with no fw.quiet record of that state"
        diff = {int(a) for a in e["data"]["diff"]}
        lost = lost_obligations(evs, v["seq"])

        def regs(doms):
            return set().union(*[L.DOMAIN_REGS[x] for x in doms]) if doms else set()
        cover = [c for c in LOSS_CAUSES if diff <= regs([x for x, cx in lost.items() if cx == c])]
        if len(cover) == 1:
            return cls(cover[0])
        if len(cover) > 1:
            return None, f"silent override covered by several loss causes {cover} (ambiguous) {lost}"
        if lost and diff <= regs(lost):
            return None, f"silent override covered only by mixed loss causes {lost}"
        return None, f"silent override with lost obligations {lost}"
    if inv == "INV-BOOT-MIRROR":
        return None, "boot-mirror: a stored marker not reflected in RAM after the full on_boot has no known signature"
    return None, "no signature for this invariant"


def pb01_violations(acts, seed: int, fw=None) -> tuple:
    """(world, done, [(action index, violation, classification, signature)])."""
    w, done, viol = pb01_execute(acts, seed=seed, fw=fw)
    evs = list(w.log)
    out = []
    for (_inv, _seq), (i, v) in sorted(viol.items(), key=lambda kv: kv[0][1]):
        c, sig = pb01_classify(v, evs)
        out.append((i, v, c, sig))
    return w, done, out


def nvs_fault_scan(evs) -> tuple:
    """The V0.1 B5 fault scan of one firmware event log, from the log alone: (fired commit faults of the modes the NVS
    USED-KEY RULE judges, per-key boot faults, [(seq, 'commit' | 'boot', mode, key)] of those whose key held NO record at
    the injection). The record set is the NVS image each fw.boot logs ('keys', after its boot fault) plus every landed
    fw.commit since; a fault.nvs_commit is logged before its commit, a fault.nvs_boot before its fw.boot."""
    present, n_commit, n_boot, bad = set(), 0, 0, []
    for e in evs:
        k, d = e["kind"], e["data"]
        if k == "fw.boot":
            present = set(d["keys"])
        elif k == "fw.commit" and d["landed"]:
            present.add(d["key"])
        elif k == "fault.nvs_commit" and d["mode"] in L.NVS_USED_KEY_MODES:
            n_commit += 1
            if d["key"] not in present:
                bad.append((e["seq"], "commit", d["mode"], d["key"]))
        elif k == "fault.nvs_boot" and len(d["fault"]) == 2:
            n_boot += 1
            if d["fault"][1] not in present:
                bad.append((e["seq"], "boot", d["fault"][0], d["fault"][1]))
    return n_commit, n_boot, bad


def shrink(acts, still_fails) -> list:
    """ddmin with a predicate that treats a sub-sequence the harness refuses as 'not a reproduction' (never a pass of the
    original failure, which is reported on its own)."""
    def pred(sub):
        try:
            return bool(still_fails(sub))
        except L.LabHarnessError:
            return False
    return T.ddmin(list(acts), pred, max_tests=400)


def fw_doc(cid: str, seed: int, done: list, *, title: str, classification: str, invariant: str, expect: list,
           failure_outcome: str, repair: str, digest: str, notes: str = "", scenario_priority: str = "P1") -> dict:
    """A firmware-tier replay document of executed DSL actions (anchors / digests of the live worktree)."""
    anchors = [{"path": FW_REL, "text": t, "line_at_record": T.anchor_line(FW_REL, t)}
               for _p, t in SCENARIOS["PB-01"]["anchors"][:2]]
    paths = sorted({FW_REL, "registry/tests/_dump_sim.py", "registry/tests/assurance_lab/_lab_fw.py"})
    doc = {"schema": T.SCHEMA, "id": cid, "title": title, "tier": "firmware", "seed": seed,
           "utc_start": C.iso_utc(PB01_U0), "synthetic": True, "ownership": SCENARIOS["PB-01"]["ownership"],
           "source_anchors": anchors, "source_digests": {p: T.source_digest(p) for p in paths}, "world": dict(PB01_WORLD),
           "actions": done, "expect": expect, "classification": classification, "invariant": invariant,
           "grade": "VERIFIED", "confidence": "medium", "failure_outcome": failure_outcome,
           "smallest_safe_repair_scope": repair, "trace_digest": digest, "scenario_priority": scenario_priority,
           "finding_priority": None}   # B6.6: an unclassified counterexample is listed by no catalogue finding
    if notes:
        doc["notes"] = notes
    return T.validate_doc(doc)


def report_unclassified(seed: int, acts: list, inv: str, reason: str, fw=None, context: str = "") -> tuple:
    """Shrink an unclassified violation, print the minimal replay document (stdout only); the caller FAILs the check.
    Returns (shrunk generator actions, document, printed text). The document holds the executed (normalised) DSL actions
    plus the TAIL and trace_digest is that execution's EventLog digest, so it replays exactly on the firmware it was found
    on. The negative control NC-PB01-a runs this same path on its in-memory mutant (`fw`, `context` names it in the header
    line) and replays the printed document against the mutant and the real firmware ([2], counterexample_replay)."""
    def fails(sub):
        _w, _d, vs = pb01_violations(sub, seed, fw)
        return any(v["inv"] == inv and c is None for _i, v, c, _s in vs)
    m = shrink(acts, fails)
    w, done, vs = pb01_violations(m, seed, fw)
    print(f"  info  UNCLASSIFIED {inv} ({reason}) seed {seed}{f' [{context}]' if context else ''}: shrunk {len(acts)} -> "
          f"{len(m)} actions; replay document:")
    doc = fw_doc(f"PB-01-u{seed}", seed, done, title=f"unclassified {inv} found by PB-01 seed {seed}",
                 classification="FAIL", invariant=inv, digest=w.log.digest(),
                 expect=[{"observe": "invariants", "args": {"names": [inv]}, "op": "!=", "value": []}],
                 failure_outcome=reason, repair="unknown: investigate (new violation class)")
    text = T.dumps_doc(doc)
    print(text, end="")
    return m, doc, text


# =============================================================================================================================
def section_pb01() -> dict:
    print("[1] PB-01 firmware random sequences: every invariant after every action and at quiescence; known residuals by "
          "signature; unclassified -> FAIL with a shrunk replay document")
    print(f"  info  firmware invariants checked (the default set): {', '.join(L.INVARIANTS)}")
    check("the default firmware invariant set the property checks has all eight invariants, INV-BOOT-MIRROR included",
          list(L.INVARIANTS) == ["INV-WS", "INV-ONE-LEASE", "INV-NO-2ND-RESTORER", "INV-NO-RESUME", "INV-LOCKOUT-QUIET",
                                 "INV-NO-SILENT-OVERRIDE", "INV-RESTORE-BOUND", "INV-BOOT-MIRROR"], str(list(L.INVARIANTS)))
    a, b = pb01_gen(7), pb01_gen(7)
    check("the generator is a pure function of the published seed (two draws of seed 7 are identical; seed 8 differs)",
          a == b and a != pb01_gen(8) and len(a) >= PB01_LEN)
    w1, d1, _v1 = pb01_execute(a, seed=7)
    w2, d2, _v2 = pb01_execute(b, seed=7)
    check("two executions of the same seed give the identical EventLog digest and the identical normalised DSL actions",
          w1.log.digest() == w2.log.digest() and d1 == d2, f"{w1.log.digest()[:12]} vs {w2.log.digest()[:12]}")
    n = PB01_EXT if EXTENDED else PB01_QUICK
    if EXTENDED:
        print(f"  info  EXTENDED: {n} sequences (estimate about {n * 0.15:.0f} s on this PC)")
    classes, first = collections.Counter(), {}
    unclassified, errors, regressions, n_actions, n_events = [], [], [], 0, 0
    kinds = collections.Counter()
    scan = [0, 0, []]                                # B5 fault scan: commit faults, per-key boot faults, offending
    for seed in range(PB01_SEED0, PB01_SEED0 + n):
        acts = pb01_gen(seed)
        try:
            w, done, vs = pb01_violations(acts, seed)
        except Exception as exc:                     # noqa: BLE001 - a harness exception is a FAIL of this sequence
            errors.append((seed, f"{type(exc).__name__}: {exc}"[:200]))
            continue
        n_actions += len(done)
        n_events += len(w.log)
        kinds.update(d["do"] for d in done)
        nc, nb, bad = nvs_fault_scan(w.log)
        scan[0] += nc
        scan[1] += nb
        scan[2] += [(seed,) + b for b in bad]
        if w.log.utc_regressions():
            regressions.append(seed)
        for i, v, c, sig in vs:
            key = (v["inv"], c, sig)
            classes[key] += 1
            first.setdefault(key, (seed, i))
            if c is None:
                unclassified.append((seed, acts, v["inv"], sig))
    print(f"  info  {n} sequences, {n_actions} executed actions, {n_events} events")
    print(f"  info  executed action mix: {dict(sorted(kinds.items()))}")
    for (inv, c, sig), k in sorted(classes.items(), key=lambda kv: (str(kv[0][1]), kv[0][0], kv[0][2])):
        print(f"  info  {k:4d} x {inv:<24} {c or 'UNCLASSIFIED'} [{sig}] first at seed {first[(inv, c, sig)][0]}")
    print(f"  info  INV-BOOT-MIRROR violations in {n} sequences: "
          f"{sum(k for (inv, _c, _s), k in classes.items() if inv == 'INV-BOOT-MIRROR')} (no known signature: any one is "
          "UNCLASSIFIED)")
    check(f"PB-01: no harness exception in {n} sequences", not errors, str(errors[:3]))
    print(f"  info  B5 fault scan: {scan[0]} fired commit faults ({', '.join(L.NVS_USED_KEY_MODES)}) and {scan[1]} per-key "
          f"boot faults in {n} sequences; on a key holding no record at the injection: {len(scan[2])}")
    check(f"PB-01 NVS realism (V0.1 B5): in {n} sequences every fired commit fault and every per-key boot fault hit a key "
          "that held a record at the injection (event-log fault scan; the normaliser's NVS rules)", not scan[2],
          str(scan[2][:5]))
    fv, fd = L.MARKER_TAGS["fp"], L.MARKER_TAGS["dump"]
    hand = [("fw.boot", {"keys": []}), ("fault.nvs_commit", {"mode": "false_negative", "key": fv}),
            ("fw.commit", {"key": fv, "landed": True}), ("fault.nvs_commit", {"mode": "false_negative", "key": fv}),
            ("fw.commit", {"key": fd, "landed": False}), ("fault.nvs_boot", {"fault": ["read_error", fd]}),
            ("fault.nvs_boot", {"fault": ["erase_all"]}), ("fw.boot", {"keys": []}),
            ("fault.nvs_commit", {"mode": "not_landed", "key": fv}), ("fault.nvs_commit", {"mode": "landed", "key": fd})]
    got = nvs_fault_scan([{"seq": i, "kind": k, "data": d} for i, (k, d) in enumerate(hand)])
    check("PB-01 NVS realism negative control (hand-built log): the fault scan flags a commit fault on a never-stored key, "
          "a boot read_error on a key whose only commit did not land and a commit fault after erase_all, and passes the "
          "used-key one and a 'landed' policy", got == (3, 1, [(1, "commit", "false_negative", fv),
                                                           (5, "boot", "read_error", fd),
                                                           (8, "commit", "not_landed", fv)]), str(got))
    for seed, acts, inv, sig in unclassified[:2]:
        report_unclassified(seed, acts, inv, sig)
    check(f"PB-01: every invariant violation in {n} sequences matches a known signature (0 unclassified)",
          not unclassified, str([(s, i, g) for s, _a, i, g in unclassified[:5]]))
    check("PB-01: every firmware event log is UTC-monotonic (also across reboots and power cuts)", not regressions,
          str(regressions[:5]))
    return {"classes": classes, "n": n}


def mutant(text: str, old: str, new: str):
    """(parsed firmware, None) for an exact-count (1) in-memory replace, or (None, reason): MUTANT-INVALID."""
    if text.count(old) != 1:
        return None, f"anchor occurs {text.count(old)} times"
    try:
        return L.load_fw(text.replace(old, new)), None
    except Exception as exc:                         # noqa: BLE001 - a mutant that does not parse is MUTANT-INVALID
        return None, f"{type(exc).__name__}: {exc}"[:200]


NC_XDOM_OLD = ("                !id(dump_active_persisted) &&\n                !id(dump_snapshot_valid) &&\n"
               "                // Fail-closed lockout: a durable recovery marker exists\n"
               "                // whose data ECCO could not trust at boot - refuse any new\n"
               "                // write in this domain until deliberate operator recovery.\n"
               "                !id(free_power_recovery_metadata_corrupt) &&")
NC_S3_OLD = ('                    id(free_power_restore_requested) = true;\n'
             '                    ESP_LOGW("free_power", "Free Power was ACTIVE at last shutdown')
NC_PHASEB_OLD = ("                      marker.state = ecco_durable::MARKER_RESTORE_REQUIRED;\n"
                 "                      bool marker_committed = data_committed && ecco_durable::commit_record(")
# the Dump on_boot marker block (FW:801; its FP / reg244 twins have other next lines): read a stored marker as CLEAR
# pattern from registry/tests/assurance_lab/test_lab_selftest_firmware.py:1005 (DUMP_RR_ANCHOR / DUMP_RR_MUTANT)
NC_BOOTRR_OLD = ("uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;\n"
                 "              id(dump_marker_state) = state;")
NC_BOOTRR_NEW = "uint8_t state = (uint8_t) ecco_durable::MARKER_CLEAR;\n              id(dump_marker_state) = state;"
CX_CONTROL = "NC-PB01-a"        # the control whose shrunk counterexample is printed as a replay document and replayed
CX_TIER = "pb01_mutant"         # temporary replay tier for that document on the in-memory mutant (never left registered)


def load_doc_text(text: str) -> dict:
    """_lab_trace.load_doc for printed text, in memory (this suite writes no file): the same strict JSON parse with
    _lab_trace's own hooks (a duplicate key or NaN / Infinity raises CorpusSchemaError), then _lab_trace.validate_doc."""
    return T.validate_doc(json.loads(text, object_pairs_hook=T._no_dupes, parse_constant=T._no_constant))


def _schema_refused(text: str) -> bool:
    """True when load_doc_text refuses the text with CorpusSchemaError (a negative check of the strict parse)."""
    try:
        load_doc_text(text)
    except T.CorpusSchemaError:
        return True
    return False


def replay_on_mutant(doc: dict, fw):
    """_lab_trace.replay of a firmware-tier document against the in-memory mutant `fw`: a temporary tier (CX_TIER) shares
    the firmware tier's ACTIONS / OBSERVERS and builds FirmwareWorld(fw, ...) exactly as pb01_execute does; it is
    registered here and always removed in finally (never left in place). The document's source digests and anchors still
    name the unchanged worktree files, so the engine's drift / digest / anchor verdicts apply unchanged."""
    # pattern from registry/tests/assurance_lab/test_lab_fw_runtime.py:1883 (replay_on)
    if T.registered(CX_TIER)["factory"]:
        raise L.LabHarnessError(f"replay tier {CX_TIER!r} is already registered")

    def factory(*, utc_start: int, seed: int, **kw):
        if "bank" in kw or "fw" in kw:
            raise L.LabHarnessError("replay_on_mutant: documents with bank / fw world kwargs are not supported here")
        return L.FirmwareWorld(fw, utc_start=utc_start, seed=seed, **kw)

    try:
        T.register_tier(CX_TIER, factory)
        T.register_actions(CX_TIER, L.ACTIONS)
        T.register_observers(CX_TIER, L.OBSERVERS)
        return T.replay(dict(doc, tier=CX_TIER))
    finally:
        T.unregister_tier(CX_TIER)


def counterexample_replay(nid: str, inv: str, fw, m: list, done: list, kept: list, doc: dict, text: str, *,
                          mutant_digest: str, real_digest: str) -> None:
    """The printed counterexample document of one negative control (report_unclassified -> fw_doc -> T.dumps_doc):
    validate / dumps / load round trip, then _lab_trace.replay on the in-memory mutant (twice; it must reproduce the
    planted violation with the re-execution's digest) and on the real firmware (the violation must be absent)."""
    loaded = load_doc_text(text)
    corpus_a = CORPUS / "PB-01-a.json"
    same_parse = (corpus_a.is_file() and load_doc_text(corpus_a.read_bytes().decode("utf-8")) == T.load_doc(corpus_a)
                  and _schema_refused('{"id": "PB-01-dup", ' + text[1:])
                  and _schema_refused(text.replace(f'"seed": {doc["seed"]},', '"seed": NaN,', 1)))
    rt_ok = (loaded == doc and T.validate_doc(loaded) is loaded and T.dumps_doc(loaded) == text and text.isascii()
             and "\r" not in text and loaded["tier"] == L.TIER and loaded["classification"] == "FAIL"
             and loaded["invariant"] == inv and loaded["actions"] == done and len(done) == len(m) + len(TAIL)
             and [x["do"] for x in done[len(m):]] == [a for a, _args in TAIL])
    check(f"{nid} counterexample: the document printed by report_unclassified (fw_doc -> T.dumps_doc) validates and "
          f"survives the dumps / load round trip byte-identically ({doc['id']}: {len(m)} shrunk actions + the "
          f"{len(TAIL)}-action TAIL, tier {L.TIER}, FAIL, {inv}); the in-memory loader is load_doc's strict parse (equal "
          "on corpus PB-01-a, refuses a duplicate key and NaN)", rt_ok and same_parse,
          f"round trip {rt_ok}, strict parse {same_parse}")
    r1 = replay_on_mutant(loaded, fw)
    r2 = replay_on_mutant(loaded, fw)
    tier_gone = T.registered(CX_TIER) == {"factory": False, "actions": [], "observers": []}
    obs = r1.observations[0] if r1.observations else None
    evs = list(r1.log)
    planted = (isinstance(obs, list) and bool(obs) and all(v["inv"] == inv for v in obs)
               and all(pb01_classify(v, evs)[0] is None for v in obs)
               and sorted(v["seq"] for v in obs) == sorted(v["seq"] for v in kept))
    check(f"{nid} counterexample: replayed through _lab_trace.replay on the in-memory MUTANT it reproduces the planted "
          f"unclassified {inv} deterministically (two replays, the recorded trace_digest and a re-execution of the shrunk "
          f"sequence agree on digest {r1.digest[:12]}; no drift, anchors at their lines; the temporary tier is removed)",
          r1.ok and r2.ok and not r1.drift and not r1.anchor_problems and r1.digest == r2.digest
          == loaded["trace_digest"] == mutant_digest and r1.log.canonical() == r2.log.canonical() and planted
          and tier_gone, f"ok {r1.ok}/{r2.ok} drift {r1.drift} digests {r1.digest[:12]} {r2.digest[:12]} "
          f"{loaded['trace_digest'][:12]} {mutant_digest[:12]} planted {planted} tier_gone {tier_gone} "
          f"{str(r1.failed_expectations)[:200]}")
    r0 = T.replay(loaded)
    f0 = r0.failed_expectations
    check(f"{nid} counterexample: the same document replayed on the REAL firmware does not reproduce it (its one "
          f"expectation fails with no {inv} observed, the digest differs from trace_digest, no drift: the counterexample "
          f"is specific to the mutant) and equals the real re-execution of the shrunk sequence (digest {r0.digest[:12]})",
          not r0.ok and not r0.drift and r0.digest_mismatch and len(f0) == 1 and f0[0]["index"] == 0
          and f0[0]["observed"] == [] and r0.digest == real_digest != loaded["trace_digest"],
          f"ok {r0.ok} drift {r0.drift} mismatch {r0.digest_mismatch} {str(f0)[:200]} {r0.digest[:12]} {real_digest[:12]}")


def section_pb01_controls() -> None:
    print("[2] PB-01 negative controls: planted violations (in-memory firmware mutants removing a real guard) are found by "
          "the property within the quick budget, shrunk to a small trace, and the shrunk trace still fails (NC-PB01-a "
          "INV-ONE-LEASE, NC-PB01-b INV-NO-RESUME, NC-PB01-d INV-BOOT-MIRROR); NC-PB01-a also prints its counterexample "
          "through the reporting path as a replay document and replays it on the mutant (reproduces) and the real "
          "firmware (absent); a Phase-B mutant on a fixed trace stays unclassified (NC-PB01-c: the loss signatures need an "
          "injected NVS fault)")
    text = L.fw_text()
    controls = (
        ("NC-PB01-a", "FP START admission without its two cross-domain Dump terms (start_free_power_override)",
         NC_XDOM_OLD, NC_XDOM_OLD.split("\n", 2)[2], "INV-ONE-LEASE"),
        ("NC-PB01-b", "S3 removed: a persisted ACTIVE lease no longer forces restore_requested at boot",
         NC_S3_OLD, NC_S3_OLD.replace("id(free_power_restore_requested) = true;",
                                      "id(free_power_restore_requested) = data.restore_requested != 0;"), "INV-NO-RESUME"),
        ("NC-PB01-d", "Dump on_boot ignores a STORED RESTORE_REQUIRED marker (reads it as CLEAR; formerly the surviving "
         "draft NC-PB01-c-draft)", NC_BOOTRR_OLD, NC_BOOTRR_NEW, "INV-BOOT-MIRROR"),
    )
    for nid, what, old, new, inv in controls:
        fw, why = mutant(text, old, new)
        if fw is None:
            check(f"{nid} ({what}): mutant valid", False, f"MUTANT-INVALID: {why}")
            continue
        hit, err = None, None
        for seed in range(PB01_SEED0, PB01_SEED0 + MUT_SEEDS):
            acts = pb01_gen(seed)
            try:
                _w, _d, vs = pb01_violations(acts, seed, fw)
            except Exception as exc:                 # noqa: BLE001 - a crashing mutant is MUTANT-INVALID (a FAIL)
                err = f"{type(exc).__name__}: {exc}"[:200]
                break
            reasons = [s for _i, v, c, s in vs if v["inv"] == inv and c is None]
            if reasons:
                hit = (seed, acts, reasons[0])
                break
        if hit is None:
            check(f"{nid} ({what}): KILLED - the property finds an unclassified {inv}", False,
                  f"MUTANT-INVALID: {err}" if err else f"survived {MUT_SEEDS} seeds")
            continue
        seed, acts, reason = hit
        cx = None
        if nid == CX_CONTROL:     # the suite's own reporting path end to end (shrink -> fw_doc -> T.dumps_doc -> stdout)
            m, cx_doc, cx_text = report_unclassified(seed, acts, inv, reason, fw,
                                                     context=f"negative control {nid}, in-memory mutant firmware")
            cx = (cx_doc, cx_text)
        else:
            def fails(sub, _fw=fw, _inv=inv, _seed=seed):
                _w2, _d2, vs2 = pb01_violations(sub, _seed, _fw)
                return any(v["inv"] == _inv and c is None for _i, v, c, _s in vs2)
            m = shrink(acts, fails)
        w, done, vs = pb01_violations(m, seed, fw)
        kept = [v for _i, v, c, _s in vs if v["inv"] == inv and c is None]
        print(f"  info  {nid}: found at seed {seed} ({len(acts)} actions), shrunk to {len(m)}: "
              f"{json.dumps([[x['do'], x['args']] for x in done[:len(m)]])}")
        check(f"{nid} ({what}): KILLED - an unclassified {inv} found within {MUT_SEEDS} seeds, no harness exception",
              True)
        check(f"{nid}: ddmin shrinks the failing sequence to <= 3 actions and the shrunk trace still fails with {inv}",
              len(m) <= 3 and bool(kept), f"{len(m)} actions, kept {kept[:1]}")
        w0, _d0, vs0 = pb01_violations(m, seed)
        check(f"{nid}: the same shrunk trace on the REAL firmware holds the invariant (the guard is what prevents it)",
              not any(v["inv"] == inv for _i, v, _c, _s in vs0), str([v for _i, v, _c, _s in vs0][:1]))
        if cx is not None:
            counterexample_replay(nid, inv, fw, m, done, kept, cx[0], cx[1], mutant_digest=w.log.digest(),
                                  real_digest=w0.log.digest())
        if nid == "NC-PB01-d":
            # the exact shape: the boot is judged at its fw.booted, the Dump marker stays RESTORE_REQUIRED in NVS while the
            # RAM is clear and the status 'Inactive' with 244 = 0 live; the level-based silent-override rule also sees it
            # (the stored marker the RAM ignores is named) and the loss signatures do not absorb it (no injected fault)
            bm = [v for v in kept if w.log[v["seq"]]["kind"] == "fw.booted"
                  and "the stored dump marker is RESTORE_REQUIRED" in v["detail"]]
            nso = [(v, c) for _i, v, c, _s in vs if v["inv"] == "INV-NO-SILENT-OVERRIDE"]
            check("NC-PB01-d: the kill is the INTENDED one - INV-BOOT-MIRROR at the boot's fw.booted (dump: stored "
                  "RESTORE_REQUIRED, RAM clear, status 'Inactive', 244 = 0 live), and INV-NO-SILENT-OVERRIDE names the "
                  "ignored marker; both UNCLASSIFIED",
                  len(bm) == len(kept) >= 1 and w.nvs_marker("dump") == "RESTORE_REQUIRED" and w.status("dump") == "Inactive"
                  and w.bank[244] == 0 and not w.sim.g["dump_snapshot_valid"] and bool(nso)
                  and all(c is None and "'dump': 'RESTORE_REQUIRED'" in v["detail"] for v, c in nso),
                  f"{[v['detail'][:90] for v in kept]} {[(v['detail'][-90:], c) for v, c in nso]}")
    # NC-PB01-c guards the classifier itself: a GENUINE firmware loss of an obligation (the Dump START durably commits CLEAR
    # instead of RESTORE_REQUIRED; no injected NVS fault) ends in the stale-CLEAR false positive's state and must stay
    # UNCLASSIFIED, i.e. the false-absent / false-positive-commit signatures cannot absorb it (fixed trace, fast). The boot
    # itself mirrors the stored CLEAR honestly, so INV-BOOT-MIRROR must stay silent here.
    what = "Dump START commits a CLEAR marker instead of RESTORE_REQUIRED"
    fw, why = mutant(text, NC_PHASEB_OLD, NC_PHASEB_OLD.replace("MARKER_RESTORE_REQUIRED", "MARKER_CLEAR"))
    trace = [("dump_start", {"power_w": 1400, "stop_soc": 56, "minutes": 6}), ("reboot", {"down_s": 2})]
    if fw is None:
        check(f"NC-PB01-c ({what}): mutant valid", False, f"MUTANT-INVALID: {why}")
        return
    try:
        wm, _dm, vm = pb01_violations(trace, 0, fw)
        err = None
    except Exception as exc:                         # noqa: BLE001 - a crashing mutant is MUTANT-INVALID (a FAIL)
        wm, vm, err = None, [], f"{type(exc).__name__}: {exc}"[:200]
    hit = [(v["inv"], c) for _i, v, c, _s in vm if v["inv"] == "INV-NO-SILENT-OVERRIDE"]
    check(f"NC-PB01-c ({what}): KILLED - INV-NO-SILENT-OVERRIDE is reported UNCLASSIFIED (the loss signatures need an "
          "injected NVS fault), no harness exception; INV-BOOT-MIRROR stays silent (the boot mirrors the stored CLEAR)",
          err is None and bool(hit) and all(c is None for _inv, c in hit) and wm.nvs_marker("dump") == "CLEAR"
          and not [v for _i, v, _c, _s in vm if v["inv"] == "INV-BOOT-MIRROR"],
          f"MUTANT-INVALID: {err}" if err else str(hit))
    w0, _d0, vs0 = pb01_violations(trace, 0)
    check("NC-PB01-c: the same trace on the REAL firmware restores the ORIGINAL (no violation)", not vs0
          and w0.status("dump").startswith("RESTORED OK"), f"{w0.status('dump')[:50]} {[v['inv'] for _i, v, _c, _s in vs0]}")


# =============================================================================================================================
# PB-02: coupled random sequences
# =============================================================================================================================
DAYS = (("2026-10-21", False), ("2026-11-04", False), ("2026-10-25", True), ("2027-03-28", True))
NUMS = {"fp": ((S.E_PWR, 500, 8000, 100), (S.E_DUR, 1, 240, 1)),
        "dump": ((D.D_PWR, 500, 8000, 100), (D.D_SOC, 10, 90, 1), (D.D_DUR, 1, 240, 1))}


def lstr(u) -> str:
    y, m, d, h, mi, s, _dst = C.local_fields(u)
    return f"{y:04d}-{m:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"


def pb02_gen(seed: int) -> tuple:
    """(utc_start, world kwargs, [DSL actions at_s 0 with absolute at_utc], run_to) - a pure function of the seed."""
    r = random.Random(seed)
    day, dst = r.choice(DAYS)
    y, mo, dd = (int(x) for x in day.split("-"))
    night = dst and r.random() < 0.5
    u0 = C.utc_of_local(y, mo, dd, 0, 20) if night else C.utc_of_local(y, mo, dd, 10, 50)
    acts, wins, busy = [], [], []
    doms = ["fp"] if night else r.choice([["fp"], ["dump"], ["fp", "dump"], ["dump", "fp"]])
    t = u0 + 600
    for dom in doms:
        start = t + r.randint(0, 30) * 60 + r.choice([0, 0, 0, 30])
        if night:
            start = (C.utc_of_local(y, mo, dd, 1, r.randint(5, 50)) if r.random() < 0.7
                     else u0 + 600 + r.randint(0, 40) * 60)
        minutes = r.randint(5, 40)
        a = {"dom": dom, "start_local": lstr(start), "minutes": minutes, "power_w": r.randrange(1000, 8001, 500),
             "at_utc": u0 + 60 + r.randint(0, 200)}
        if dom == "dump":
            a["stop_soc"] = r.randint(10, 40)
        acts.append({"at_s": 0, "do": "arm_schedule", "args": a})
        wins.append((start, start + minutes * 60, dom))
        t = start + minutes * 60 + r.randint(1, 20) * 60
    end = max(x[1] for x in wins)
    quiet = ([(s - 10, s + 90) for s, _e, _d in wins] + [(e - 10, e + 90) for _s, e, _d in wins]
             + [(s, e + 90) for s, e, d in wins if d == "dump"])
    occ = {"ha": [], "dongle": []}

    def free_instant(avoid_quiet: bool, res: tuple):
        for _ in range(60):
            x = round(u0 + 300 + r.random() * (end - u0), 1)
            if avoid_quiet and any(qa <= x <= qb for qa, qb in quiet):
                continue
            if any(oa - 5 <= x <= ob + 5 for k in res for oa, ob in occ[k]):
                continue
            return x
        return None
    for _ in range(r.randint(0, 3)):
        k = r.choice(["owner_set", "owner_set", "restart_ha", "reboot_dongle", "api_outage", "bus"])
        if k == "bus":
            s, e, _d = r.choice(wins)
            x = r.choice([s, e]) + r.randint(-5, 20)
            busy.append([x, x + r.randint(5, 40)])
            continue
        res = {"owner_set": ("ha",), "restart_ha": ("ha",), "reboot_dongle": ("dongle",), "api_outage": ("dongle",)}[k]
        x = free_instant(k in ("owner_set", "reboot_dongle"), res)
        if x is None:
            continue
        if k == "owner_set":
            ent, lo, hi, st = r.choice(NUMS[r.choice(doms)])
            acts.append({"at_s": 0, "do": "owner_set", "args": {"entity": ent, "value": r.randrange(lo, hi + 1, st),
                                                                 "at_utc": x}})
        elif k == "restart_ha":
            down = r.randint(5, 120)
            roll = None if r.random() < 0.5 else round(x - r.randint(0, 900), 1)
            acts.append({"at_s": 0, "do": "restart_ha", "args": {"at_utc": x, "down_s": down, "rollback_to_utc": roll}})
            occ["ha"].append((x, x + down + 15))
        elif k == "reboot_dongle":
            down = r.randint(2, 30)
            acts.append({"at_s": 0, "do": "reboot_dongle", "args": {"at_utc": x, "down_s": down}})
            occ["dongle"].append((x, x + down + 15))
        else:
            down = r.randint(5, 60)
            acts.append({"at_s": 0, "do": "api_outage", "args": {"at_utc": x, "down_s": down}})
            occ["dongle"].append((x, x + down + 1))
    world = {"bus": {"windows": sorted(busy)}, "fw_world_kwargs": {"warmup_s": 120}, "wd_phase_s": float(r.randint(0, 14))}
    return u0, world, acts, end + 1200


def pb02_execute(u0: int, world: dict, acts: list, run_to: float, *, fw=None, package_texts=None):
    """Run as _lab_trace.replay would (replay.action events, then the action): (digest, [violations], summary dict).
    A mutant firmware / package text builds the CoupledWorld directly (the replay factory refuses them)."""
    if fw is None and package_texts is None:
        cw = H.make_world(utc_start=u0, seed=0, **copy.deepcopy(world))
    else:
        kw = copy.deepcopy(world)
        fwk = dict(kw.pop("fw_world_kwargs"))
        if fw is not None:
            fwk["fw"] = fw
        cw = H.CoupledWorld(u0, seed=0, fw_world_kwargs=fwk, bus=H.BusModel(**kw.pop("bus")), package_texts=package_texts,
                            **kw)
    try:
        allacts = list(acts) + [{"at_s": 0, "do": "run_for", "args": {"seconds": run_to - u0}}]
        for i, a in enumerate(allacts):
            cw.log.append(t_utc=cw.t_utc, up_ms=None, boot=None, src="lab", kind="replay.action",
                          data={"i": i, "do": a["do"], "args": a["args"]})
            H.ACTIONS[a["do"]](cw, **copy.deepcopy(a["args"]))
        out = cw.invariants(list(H.HF_INVARIANTS) + list(L.INVARIANTS),
                            params={"INV-HF-WINDOW": {"bound_s": PB02_WINDOW_BOUND_S}})
        info = {"overruns": cw.window_overruns(), "regressions": cw.log.utc_regressions(), "evs": list(cw.log),
                "now": cw.t_utc, "last": {d: cw.last_result(d) for d in H.DOMS}}
        return cw.log.digest(), out, info
    finally:
        cw.close()


def _fault_spans(evs: list, now: float) -> list:
    """[(t_a, t_b)] of the injected faults that can delay the FIRMWARE's own lease end: a Modbus bus-busy window (the
    restore gate defers) and a dongle power cut (the lease ends through the boot path). HA restarts and API link outages
    do not delay it (the firmware ends the lease on its own) and explain nothing here."""
    spans, open_ = [], {}
    for e in evs:
        k, d, t = e["kind"], e["data"], e["t_utc"]
        key = None
        if k == "env.bus":
            key, on = "bus", not d["idle"]
        elif k == "dongle.power_off":
            key, on = k, True
        elif k == "dongle.power_on":
            key, on = "dongle.power_off", False
        if key is None:
            continue
        if on and key not in open_:
            open_[key] = t
        elif not on and key in open_:
            spans.append((open_.pop(key), t))
    spans += [(a, now) for a in open_.values()]
    return spans


def pb02_classify(v: dict, info: dict) -> tuple:
    """(classification, signature) or (None, reason). Only INV-HF-WINDOW has an explanation rule: an injected fault span
    overlapping [window end - 15 s, lease end] explains an overrun of any size, provided the lease ended."""
    if v["inv"] != "INV-HF-WINDOW":
        return None, "no signature"
    run = next((r for r in info["overruns"] if r["seq"] == v["seq"]), None)
    if run is None or run["lease_end"] is None:
        return None, "override never ended in the run"
    lo, hi = run["window_end"] - 15, run["lease_end"]
    if any(a <= hi and b >= lo for a, b in _fault_spans(info["evs"], info["now"])):
        return "PASS", "explained: injected fault at the window end"
    return None, f"overrun {run['overrun_s']} s beyond the documented allowance"


def section_pb02() -> list:
    print("[3] PB-02 coupled random sequences: real FPS1 / DGS1 / SMR1 over the real firmware; HF and firmware invariants")
    n = PB02_EXT if EXTENDED else PB02_QUICK
    if EXTENDED:
        print(f"  info  EXTENDED: {n} coupled sequences (estimate about {n * 1.3:.0f} s on this PC)")
    g1, g2 = pb02_gen(3), pb02_gen(3)
    check("the coupled generator is a pure function of the published seed", g1 == g2 and g1 != pb02_gen(4))
    stats = collections.Counter()
    unexplained, errors, regress, over = [], [], [], []
    digests = {}
    for seed in range(PB02_SEED0, PB02_SEED0 + n):
        u0, world, acts, run_to = pb02_gen(seed)
        try:
            dg, viol, info = pb02_execute(u0, world, acts, run_to)
        except H.LabUnsupported as exc:              # recorded UNSUPPORTED (an interleaving the projection cannot model)
            # one UNSUPPORTED line per point; 'PB-02-UNS' has no catalogue entry (no seed meets one today), so run_lab /
            # gen_catalogue report it as an uncatalogued id until the catalogue lists it (fail loud, never silent)
            UNSUPPORTED_POINTS.append("PB-02-UNS")
            print(T.unsupported_line("PB-02-UNS", f"seed {seed}: {exc}"[:200]))
            stats["unsupported"] += 1
            continue
        except Exception as exc:                     # noqa: BLE001 - a harness exception is a FAIL of this sequence
            errors.append((seed, f"{type(exc).__name__}: {exc}"[:200]))
            continue
        digests[seed] = dg
        stats["runs"] += 1
        stats[f"day {lstr(u0)[:10]}{' night' if lstr(u0)[11:13] == '00' else ''}"] += 1
        stats["leases started"] += sum(1 for r in info["overruns"] if r["lease_start"] is not None)
        stats.update(x["do"] for x in acts)
        for r in info["overruns"]:
            if r["overrun_s"] is not None:
                over.append(r["overrun_s"])
        if info["regressions"]:
            regress.append(seed)
        for v in viol:
            c, sig = pb02_classify(v, info)
            stats[f"{v['inv']} {c or 'UNEXPLAINED'} [{sig}]"] += 1
            if c is None:
                unexplained.append((seed, v["inv"], v["detail"][:120], u0, world, acts, run_to))
    print(f"  info  {n} coupled sequences: {dict(sorted(stats.items()))}")
    if over:
        big = sorted(x for x in over if x > 30)
        print(f"  info  window-end overruns: {len(over)} measured, max {max(over)} s, above the generic 30 s bound: {big} "
              f"(documented late-start allowance, HF-01 owns the classification)")
    check(f"PB-02: no harness exception in {n} coupled sequences", not errors, str(errors[:3]))
    for seed, inv, detail, u0, world, acts, run_to in unexplained[:1]:
        def fails(sub, _u0=u0, _world=world, _run_to=run_to, _inv=inv):
            _dg, vv, ii = pb02_execute(_u0, _world, sub, _run_to)
            return any(x["inv"] == _inv and pb02_classify(x, ii)[0] is None for x in vv)
        m = shrink(acts, fails)
        print(f"  info  UNEXPLAINED {inv} seed {seed} ({detail}); shrunk {len(acts)} -> {len(m)} actions; replay document:")
        dg, _vv, _ii = pb02_execute(u0, world, m, run_to)
        doc = cpl_doc(f"PB-02-u{seed}", u0, world, m + [{"at_s": 0, "do": "run_for", "args": {"seconds": run_to - u0}}],
                      title=f"unexplained {inv} found by PB-02 seed {seed}", classification="FAIL", invariant=inv,
                      expect=[{"observe": "invariants", "args": {"names": [inv]}, "op": "!=", "value": []}],
                      failure_outcome=detail, repair="unknown: investigate", digest=dg)
        print(T.dumps_doc(doc), end="")
    check(f"PB-02: every coupled / firmware violation in {n} sequences is explained (0 unexplained)", not unexplained,
          str([(s, i, d) for s, i, d, *_r in unexplained[:3]]))
    regress_bad = [s for s in regress if s not in DOC_REBOOT_ORDER]
    check("PB-02: every merged log is UTC-monotonic (a dongle-reboot ordering gap would be the documented _lab_ha NOT "
          "MODELLED case)", not regress_bad, str(regress_bad[:5]))
    s0 = PB02_SEED0
    if s0 in digests:
        u0, world, acts, run_to = pb02_gen(s0)
        dg, _v, _i = pb02_execute(u0, world, acts, run_to)
        check("PB-02: rerunning a coupled sequence gives the identical merged-log digest", dg == digests[s0])
    return over


DOC_REBOOT_ORDER: set = set()     # seeds whose only UTC regression is the documented dongle-reboot ordering gap (none so far)


def cpl_doc(cid: str, u0: int, world: dict, actions: list, *, title: str, classification: str, invariant: str,
            expect: list, failure_outcome: str, repair: str, digest: str, notes: str = "") -> dict:
    anchors = [{"path": p, "text": t, "line_at_record": T.anchor_line(p, t)} for p, t in SCENARIOS["PB-02"]["anchors"][:2]]
    paths = sorted({FW_REL, FPS1_REL, DGS1_REL, SMR1_REL, "registry/tests/assurance_lab/_lab_ha.py",
                    "home-assistant/tests/_ha_script_sim.py"})
    doc = {"schema": T.SCHEMA, "id": cid, "title": title, "tier": "coupled", "seed": 0, "utc_start": C.iso_utc(u0),
           "synthetic": True, "ownership": SCENARIOS["PB-02"]["ownership"], "source_anchors": anchors,
           "source_digests": {p: T.source_digest(p) for p in paths}, "world": world, "actions": actions, "expect": expect,
           "classification": classification, "invariant": invariant, "grade": "VERIFIED", "confidence": "medium",
           "failure_outcome": failure_outcome, "smallest_safe_repair_scope": repair, "trace_digest": digest,
           "scenario_priority": SCENARIOS["PB-02"]["priority"], "finding_priority": None}   # B6.6
    if notes:
        doc["notes"] = notes
    return T.validate_doc(doc)


NC_WD_OLD = "return (uint32_t) now.timestamp >= id(free_power_end_epoch);"
NC_SMR_OLD = ("               ('binary_sensor.ecco_clock_dongle_free_power_active', 'Free Power active'),\n",
              "               ('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', "
              "'Free Power snapshot pending restore'),\n")


def section_pb02_controls() -> None:
    print("[4] PB-02 negative controls: an in-memory firmware mutant (FP watchdog end + 300 s) and an in-memory SMR1 package "
          "mutant (its restore blocker no longer reads Free Power Active / Snapshot Valid) are caught by the INTENDED "
          "coupled invariant")
    fw, why = mutant(L.fw_text(), NC_WD_OLD, "return (uint32_t) now.timestamp >= id(free_power_end_epoch) + 300U;")
    smr = H.package_text("smr1")
    smr_mut = smr
    for line in NC_SMR_OLD:
        smr_mut = smr_mut.replace(line, "") if smr_mut.count(line) == 1 else None
        if smr_mut is None:
            break
    controls = (("NC-PB02-a", "FP watchdog ends the lease 300 s after its end epoch", "INV-HF-WINDOW",
                 {"fw": fw}, why, lambda dom: dom == "fp"),
                ("NC-PB02-b", "SMR1's blocker ignores Free Power Active / Snapshot Valid (it restores during the lease)",
                 "INV-HF-SMR1-QUIET", {"package_texts": {"smr1": smr_mut}} if smr_mut else None,
                 None if smr_mut else "SMR1 anchor not unique", lambda dom: dom == "fp"))
    for nid, what, inv, kw, why_bad, wants in controls:
        if kw is None or (kw.get("fw", 0) is None):
            check(f"{nid} ({what}): mutant valid", False, f"MUTANT-INVALID: {why_bad}")
            continue
        hit, err = None, None
        for seed in range(PB02_SEED0, PB02_SEED0 + 12):
            u0, world, acts, run_to = pb02_gen(seed)
            if not any(wants(a["args"]["dom"]) for a in acts if a["do"] == "arm_schedule"):
                continue
            try:
                _dg, viol, info = pb02_execute(u0, world, acts, run_to, **kw)
            except Exception as exc:                 # noqa: BLE001 - a crashing mutant is MUTANT-INVALID (a FAIL)
                err = f"{type(exc).__name__}: {exc}"[:200]
                break
            got = [v for v in viol if v["inv"] == inv and pb02_classify(v, info)[0] is None]
            if got:
                hit = (seed, got[0])
                break
        check(f"{nid} ({what}): KILLED - {inv} reported by the property (seed {hit[0] if hit else '-'}), no harness "
              f"exception", hit is not None, f"MUTANT-INVALID: {err}" if err else "survived")
        if hit:
            print(f"  info  {nid}: {hit[1]['detail'][:150]}")


# =============================================================================================================================
# PB-03: time properties
# =============================================================================================================================
def tz_grid(tu=TU, lab=C, step: int = 900) -> dict:
    """Mismatch counts of the lab clock against every oracle on the 15-min grid of 2026-01-01 .. 2027-12-31."""
    bad = collections.Counter()
    a, b = lab.parse_iso_utc("2026-01-01T00:00:00Z"), lab.parse_iso_utc("2028-01-01T00:00:00Z")
    n = 0
    for u in range(a, b, step):
        n += 1
        off, lf = lab.london_offset_s(u), lab.local_fields(u)
        dt = datetime.fromtimestamp(u, UTC)
        bad["fbd1_harness"] += F.london_offset_s(u) != off
        bad["timeutil"] += int(tu.london_offset(dt).total_seconds()) != off
        loc = tu.to_local(dt)
        bad["timeutil_fields"] += (loc.year, loc.month, loc.day, loc.hour, loc.minute, loc.second) != lf[:6]
        e = F.EspTime(u, True)
        bad["esptime"] += (e.year, e.month, e.day_of_month, e.hour, e.minute, e.second, e.is_dst) != lf
        if ZI is not None:
            zd, ld = datetime.fromtimestamp(u, ZI), datetime.fromtimestamp(u, lab.LONDON)
            bad["zoneinfo"] += (int(zd.utcoffset().total_seconds()) != off or zd.replace(tzinfo=None)
                                != ld.replace(tzinfo=None) or zd.fold != ld.fold)
    bad["n"] = n
    return bad


def tz_random(n: int, seed: int) -> dict:
    """Random instants (incl. sub-second) of 2026-2027: oracle agreement plus the UTC -> local -> UTC round trip."""
    r = random.Random(seed)
    a, b = C.parse_iso_utc("2026-01-01T00:00:00Z"), C.parse_iso_utc("2028-01-01T00:00:00Z")
    bad = collections.Counter()
    for _ in range(n):
        u = r.randrange(a, b) + (r.randrange(1000) / 1000 if r.random() < 0.3 else 0)
        s = math.floor(u)
        off, lf = C.london_offset_s(u), C.local_fields(u)
        bad["fbd1_harness"] += F.london_offset_s(s) != off
        bad["timeutil"] += int(TU.london_offset(datetime.fromtimestamp(s, UTC)).total_seconds()) != off
        fold = datetime.fromtimestamp(s, C.LONDON).fold
        bad["roundtrip"] += C.utc_of_local(*lf[:6], fold=fold) != s
        bad["roundtrip_timeutil"] += int(TU.local_to_utc(datetime(*lf[:6]), fold=fold).timestamp()) != s
        if fold == 0:
            bad["roundtrip_fbd1"] += F.utc_of_local(*lf[:6]) != s
        if ZI is not None:
            bad["zoneinfo"] += int(datetime(*lf[:6], fold=fold, tzinfo=ZI).timestamp()) != s
    return bad


def millis_masked(sim) -> bool:
    """INV-MILLIS-WRAP sample: the firmware's millis() equals the 64-bit uptime modulo 2^32 (ESPHome millis())."""
    return sim.millis() == sim.now_ms % (1 << 32)


TRANSITION_DAYS = ((2026, 3, 29, "gap"), (2026, 10, 25, "ambiguous"), (2027, 3, 28, "gap"), (2027, 10, 31, "ambiguous"))


def tz_fold(lab=C) -> dict:
    """Every minute of the four transition days, both folds: local_kind, the fold / gap offsets (zoneinfo semantics),
    the oracles where they define the wall time, and the round trip back to the wall time."""
    bad = collections.Counter()
    for y, m, d, kind in TRANSITION_DAYS:
        for minute in range(24 * 60):
            h, mi = divmod(minute, 60)
            k = lab.local_kind(y, m, d, h, mi)
            want = kind if h == 1 else "normal"
            bad["kind"] += k != want
            u0, u1 = lab.utc_of_local(y, m, d, h, mi, 0, fold=0), lab.utc_of_local(y, m, d, h, mi, 0, fold=1)
            if k == "ambiguous":
                bad["fold_offsets"] += not (u1 - u0 == 3600 and lab.london_offset_s(u0) == 3600
                                            and lab.london_offset_s(u1) == 0)
                for f, u in ((0, u0), (1, u1)):
                    back = datetime.fromtimestamp(u, lab.LONDON)
                    bad["fold_roundtrip"] += (back.hour, back.minute, back.fold) != (h, mi, f)
                    bad["fold_timeutil"] += int(TU.local_to_utc(datetime(y, m, d, h, mi), fold=f).timestamp()) != u
                bad["fold_fbd1"] += F.utc_of_local(y, m, d, h, mi) != u0
            elif k == "gap":
                bad["gap_semantics"] += not (u0 == u1 + 3600 and lab.london_offset_s(u0) == 3600
                                             and lab.local_fields(u0)[3:5] == (h + 1, mi))
                # the two oracles document a gap wall time as nonexistent (they raise); _lab_clock never raises and
                # exposes it through local_kind(). Only that exact refusal is accepted; anything else propagates.
                try:
                    TU.local_to_utc(datetime(y, m, d, h, mi))
                    bad["gap_timeutil_raises"] += 1
                except TU.TimeParseError as exc:
                    if "does not exist" not in str(exc):
                        raise
                try:
                    F.utc_of_local(y, m, d, h, mi)
                    bad["gap_fbd1_raises"] += 1
                except ValueError as exc:
                    if "does not exist in Europe/London" not in str(exc):
                        raise
            else:
                bad["normal_folds_equal"] += u0 != u1
                back = lab.local_fields(u0)
                bad["normal_roundtrip"] += back[3:5] != (h, mi)
            if ZI is not None:
                for f, u in ((0, u0), (1, u1)):
                    bad["zoneinfo"] += int(datetime(y, m, d, h, mi, fold=f, tzinfo=ZI).timestamp()) != u
    return bad


def section_pb03(pb02_over) -> None:
    print("[5] PB-03 London tz against _fbd1_harness, tools/fbd1_soak/timeutil, ESPTime fields and zoneinfo")
    print(f"  info  zoneinfo Europe/London {'importable: used as a third oracle' if ZI else 'NOT importable: skipped'}")
    g = tz_grid()
    oracles = ["fbd1_harness", "timeutil", "timeutil_fields", "esptime"] + (["zoneinfo"] if ZI else [])
    if ZI is None:
        zi_skipped(f"the zoneinfo oracle of every 15 min of 2026-2027 ({g['n']} instants)")
    check(f"every 15 min of 2026-2027 ({g['n']} instants): offset and local fields agree with every oracle "
          f"({', '.join(oracles)})", all(g[o] == 0 for o in oracles), str(dict(g)))
    n = PB03_RANDOM_EXT if EXTENDED else PB03_RANDOM
    rnd = tz_random(n, PB03_SEED)
    trips = ("_lab_clock, timeutil, _fbd1_harness (fold 0) and zoneinfo" if ZI
             else "_lab_clock, timeutil and _fbd1_harness (fold 0)")
    if ZI is None:
        zi_skipped(f"the zoneinfo round trip of the {n} random instants")
    check(f"{n} random instants (seed {PB03_SEED}, 30 % sub-second): oracles agree and UTC -> London wall time (+fold) -> "
          f"UTC round-trips through {trips}", not any(rnd.values()), str(dict(rnd)))
    fo = tz_fold()
    if ZI is None:
        zi_skipped("the zoneinfo comparison of every minute of the four transition days, both folds")
    check("every minute of 2026-03-29 / 2026-10-25 / 2027-03-28 / 2027-10-31, both folds: kinds, repeated-hour folds "
          "(fold 0 = BST, fold 1 = GMT one hour later), gap semantics (fold 0 = pre-transition GMT reading), oracles and "
          "round trips agree", not any(fo.values()), str(dict(fo)))
    a = datetime(2026, 10, 25, 0, 30, tzinfo=C.LONDON) + timedelta(hours=2)
    real = a.timestamp() - datetime(2026, 10, 25, 0, 30, tzinfo=C.LONDON).timestamp()
    if ZI is None:          # the arithmetic is still checked against the real-time difference; only the comparison is skipped
        zi_skipped("aware wall-time arithmetic compared with zoneinfo (00:30 BST + 2 h on 2026-10-25)")
    zi_ok = ZI is None or (datetime(2026, 10, 25, 0, 30, tzinfo=ZI) + timedelta(hours=2)).timestamp() == a.timestamp()
    check("aware wall-time arithmetic (the HA sim's now() + timedelta): 00:30 BST + 2 h on 2026-10-25 is 02:30 GMT = 3 h "
          "of real time" + (", as zoneinfo" if ZI else ""),
          (a.hour, a.minute, a.tzname()) == (2, 30, "GMT") and real == 3 * 3600 and zi_ok)
    print("[6] PB-03 UTC-monotonic logs and millis() wrap across the reboot primitive")
    w = L.FirmwareWorld(utc_start=C.DST_FALL_2026_UTC - 1200, warmup_s=60)
    w.fp_start(power_w=3000, minutes=30)
    w.run_for(300)
    w.arm_power_cut(kind="fw.read", nth=2, down_s=20)
    w.run_for(600)
    w.reboot(down_s=30)
    w.run_for(1800)
    lf = C.local_fields(w.t_utc)
    restored_ok = any(x.startswith("RESTORED OK") for x in w.status_history("fp"))
    check("INV-UTC-MONOTONIC: a DST-night FirmwareWorld (FP lease across 01:00 UTC, a power cut and a reboot) has a "
          "UTC-monotonic log, restored the ORIGINAL and ends in GMT", not w.log.utc_regressions() and w.cuts_fired == 1
          and w.boot_no == 2 and lf[6] is False and restored_ok and w.nvs_marker("fp") == "CLEAR"
          and all(w.bank[a] == w.original[a] for a in L.OWNED),
          f"{w.log.utc_regressions()[:3]} {w.status_history('fp')[-4:]}")
    bad = T.EventLog()
    for i, e in enumerate(list(w.log)[:50]):
        bad.append(t_utc=e["t_utc"] - (5 if i == 40 else 0), up_ms=e["up_ms"], boot=e["boot"], src=e["src"],
                   kind=e["kind"], data=e["data"])
    check("NC-PB03-c (INV-UTC-MONOTONIC): the same events with one t_utc moved 5 s back are caught "
          "(EventLog.utc_regressions)", bad.utc_regressions() == [40] or bad.utc_regressions() == [40, 41],
          str(bad.utc_regressions()))
    if pb02_over is not None:
        print(f"  info  PB-02 merged logs were checked for UTC monotonicity in [3] ({len(pb02_over)} measured windows)")
    wrap = 1 << 32
    u_start = C.utc_of_local(2026, 12, 9, 11, 0) - (wrap // 1000) + 600
    m = L.FirmwareWorld(utc_start=u_start, warmup_s=60)
    m.advance((wrap - m.sim.now_ms - 600_000) / 1000)
    m.run_for(120)
    before = (m.sim.now_ms, millis_masked(m.sim))
    s = m.fp_start(power_w=3000, minutes=15)
    end = m.obligations()["fp"]["end"]
    m.run_for(end - m.t_utc + 30)
    restored = [e["t_utc"] for e in m.log if e["kind"] == "fw.status" and e["data"]["dom"] == "fp"
                and e["data"]["text"].startswith("RESTORED OK")]
    after = (m.sim.now_ms, millis_masked(m.sim), m.sim.millis())
    check("INV-MILLIS-WRAP: millis() is the low 32 bits of the 64-bit uptime before and after the 2^32 ms wrap",
          before[1] and after[1] and before[0] < wrap < after[0] and after[2] == after[0] - wrap, f"{before} {after}")
    check("INV-MILLIS-WRAP: a 15 min Free Power lease started 8 min before the wrap ends on its UTC epoch (first FP watchdog "
          "slot) and restores the ORIGINAL; every invariant holds", s.startswith("ACTIVE - VERIFIED OK") and len(restored) == 1
          and end <= restored[0] <= end + 15 and not m.invariants(), f"{s} {restored} {end}")
    t_cut = m.t_utc
    m.reboot(down_s=5)
    check("INV-MILLIS-WRAP: the reboot primitive after the wrap restarts millis() at boot_ms (2000) with UTC continuous "
          "(cut + 5 s down + 2 s boot) and a UTC-monotonic log", m.sim.millis() == 2000
          and abs(m.t_utc - t_cut - 7) < 1e-6 and not m.log.utc_regressions() and millis_masked(m.sim),
          f"{m.sim.millis()} {m.t_utc - t_cut}")
    n2 = L.FirmwareWorld(utc_start=u_start, warmup_s=1)
    n2.advance((wrap - n2.sim.now_ms + 5000) / 1000)
    pre = millis_masked(n2.sim)
    n2.sim.millis = lambda _s=n2.sim: _s.now_ms     # NC: per-instance mutation of _dump_sim's 'now_ms & 0xFFFFFFFF'
    check("NC-PB03-d (INV-MILLIS-WRAP): a per-instance millis() without the 32-bit mask (past the wrap) is caught by the "
          "same check (killed)", pre and not millis_masked(n2.sim))
    print("[7] PB-03 negative controls: in-memory oracle / lab-clock mutants are caught by the INTENDED cross-check")
    tu_txt = T.read_source_text("tools/fbd1_soak/timeutil.py")
    old = "    b = _last_sunday(year, 10)\n"
    ok = tu_txt.count(old) == 1
    bad_g = None
    if ok:
        ns: dict = {"__name__": "timeutil_mutant"}
        exec(compile(tu_txt.replace(old, "    b = _last_sunday(year, 10) + timedelta(days=7)\n"), "timeutil_mutant",
                     "exec"), ns)
        bad_g = tz_grid(tu=type("TUm", (), {"london_offset": staticmethod(ns["london_offset"]),
                                             "to_local": staticmethod(ns["to_local"])}))
    check("NC-PB03-a (INV-TZ-ORACLE): timeutil with BST ending one week after the last Sunday of October is caught by the "
          "15-min grid (timeutil mismatches > 0, no exception)", ok and bad_g["timeutil"] > 0 and bad_g["fbd1_harness"] == 0,
          "anchor not unique" if not ok else str(dict(bad_g)))
    lab_txt = T.read_source_text("registry/tests/assurance_lab/_lab_clock.py")
    old = "        return 0 if fold else 3600          # repeated hour"
    ok = lab_txt.count(old) == 1
    fo_m = None
    if ok:
        ns = {"__name__": "lab_clock_mutant"}
        exec(compile(lab_txt.replace(old, "        return 3600 if fold else 0          # repeated hour"), "lab_clock_mutant",
                     "exec"), ns)
        fo_m = tz_fold(lab=type("Cm", (), {k: staticmethod(ns[k]) if callable(ns[k]) else ns[k] for k in (
            "local_kind", "utc_of_local", "london_offset_s", "local_fields", "LONDON")}))
    check("NC-PB03-b (INV-TZ-FOLD): a lab clock with the repeated-hour folds swapped is caught by the fold sweep "
          "(fold mismatches > 0, no exception)", ok and fo_m["fold_offsets"] > 0, "anchor not unique" if not ok else str(dict(fo_m)))


# =============================================================================================================================
# corpus replay
# =============================================================================================================================
CORPUS_EXPECT = {     # corpus id -> (scenario, finding signature or None, invariant the classifier must see)
    "PB-01-a": ("PB-01", "phantom-admission", "INV-NO-2ND-RESTORER"),
    "PB-01-b": ("PB-01", "restore-over-corrupt-holder", "INV-LOCKOUT-QUIET"),
    "PB-01-c": ("PB-01", "partition-erase", "INV-NO-SILENT-OVERRIDE"),
    "PB-01-d": ("PB-01", "false-positive-commit", "INV-NO-SILENT-OVERRIDE"),
    "PB-01-e": ("PB-01", None, "INV-ONE-LEASE"),
    "PB-01-f": ("PB-01", "false-absent", "INV-NO-SILENT-OVERRIDE"),
    "PB-02-a": ("PB-02", None, "INV-HF-WINDOW"),
    "PB-03-a": ("PB-03", None, "INV-MILLIS-WRAP"),
    "PB-03-b": ("PB-03", None, "INV-UTC-MONOTONIC"),
}


def section_corpus() -> None:
    print("[8] corpus: every PB corpus document validates, replays through _lab_trace.replay (digest equal, anchors at "
          "their lines, expectations hold) and FINDING documents reproduce their exact signature")
    for cid, (sid, sig, inv) in CORPUS_EXPECT.items():
        path = CORPUS / f"{cid}.json"
        if not path.is_file():
            check(f"{cid}: corpus file exists", False, str(path.name))
            continue
        doc = T.load_doc(path)
        try:
            res = T.replay(doc)
        except Exception as exc:  # noqa: BLE001 - V0.1 review (R3-7): a replay harness exception is that document's FAIL
            # (never a pass); the section continues so the later documents and controls still run. Under an ESPHome-like
            # phase patch PB-03-b's replay passes an action instant (ReplayDispatchError)
            why = f"replay raised {type(exc).__name__}: {str(exc)[:240]}"
            check(f"{cid}: replay ok ({doc['classification']}, {doc['invariant']}) - not completed: harness exception",
                  False, why)
            if sig is not None:
                check(f"finding-reproduces:{flabel(PB01_FINDINGS[sig])} ({cid}: not run: its replay raised)", False, why)
            continue
        check(f"{cid}: replay ok ({doc['classification']}, {doc['invariant']}), digest {res.digest[:12]}, drift {res.drift}",
              res.ok and doc["id"] == cid and cid in SCENARIOS[sid]["corpus"],
              str(res.failed_expectations)[:300] + (" digest mismatch" if res.digest_mismatch else "")
              + str(res.anchor_problems))
        if sig is None:
            continue
        f = PB01_FINDINGS[sig]
        cls, label = f["classification"], flabel(f)
        evs = list(res.log)
        allv = L.check_invariants(evs)
        got = [pb01_classify(v, evs) for v in allv if v["inv"] == inv]
        rest = sorted({(v["inv"],) + pb01_classify(v, evs) for v in allv if v["inv"] != inv}, key=str)
        ok = (bool(got) and all(g == (cls, sig) for g in got) and all(r[1] is not None for r in rest)
              and doc["classification"] == cls and f["corpus"] == cid and res.ok)
        check(f"finding-reproduces:{label} ({cid}: {inv} with signature {sig} -> {cls}; every other violation of the "
              f"document classified: {[r[0] + ' ' + r[2] for r in rest] or 'none'})", ok, str(got[:3]) + str(rest[:3]))
        if ok:
            report_finding(label, cid)
    path = CORPUS / "PB-01-a.json"
    if path.is_file():
        bad = T.load_doc(path)
        bad["expect"][1]["value"] = "CLEAR"
        res = T.replay(bad)
        check("NC-PB-corpus: the PB-01-a document with one altered expectation (FP marker CLEAR) FAILS its replay (exactly "
              "that expectation, digest still equal)", not res.ok and len(res.failed_expectations) == 1
              and res.failed_expectations[0]["index"] == 1 and not res.digest_mismatch, str(res.failed_expectations)[:200])
    path = CORPUS / "PB-01-c.json"
    if path.is_file():
        bad = T.load_doc(path)
        idx = [i for i, x in enumerate(bad["expect"]) if x["observe"] == "invariants" and x["args"] == {"form": "summary"}]
        for i in idx:
            bad["expect"][i]["value"] = [dict(x, tags=[]) for x in bad["expect"][i]["value"]]
        res = T.replay(bad)
        check("NC-PB-corpus-summary: the PB-01-c document whose seq-free invariant summary drops the PLATFORM-ABSENT tag "
              "FAILS its replay (exactly that expectation, digest still equal)", len(idx) == 1 and not res.ok
              and [x["index"] for x in res.failed_expectations] == idx and not res.digest_mismatch,
              str(res.failed_expectations)[:200])


# fixed variants (verification follow-up): the general form of F-PB01-4 on a used device, and its no-reboot control
PRIOR_DUMP = (("telemetry", {"grid_w": -1000, "batt_w": 1050}),
              ("dump_start", {"power_w": 1400, "stop_soc": 56, "minutes": 1}), ("run_for", {"seconds": 400}))
FPOS_DUMP = (("nvs_policy", {"tag": "dump.valid", "state": RR, "mode": "false_positive", "times": 1}),
             ("telemetry", {"grid_w": -1000, "batt_w": 1050}),
             ("dump_start", {"power_w": 1400, "stop_soc": 56, "minutes": 6}))


DUMP_LEASE = (("telemetry", {"grid_w": -1000, "batt_w": 1050}),
              ("dump_start", {"power_w": 1400, "stop_soc": 56, "minutes": 6}))


def section_variants() -> None:
    print("[9] finding variants: the boot-loss trigger decides the known risk on both lease domains (erase_all -> "
          "NVS-PARTITION-ERASE, single-key absent -> PLATFORM-ABSENT); F-PB01-4 on a used device (the previous lease's stale "
          "CLEAR marker, the FW-06-c form) has the same signature; without the reboot the lease restores normally")
    split = {}
    for fault in (["erase_all"], ["absent", "dump.valid"]):
        w, _d, vs = pb01_violations(list(DUMP_LEASE) + [("reboot", {"down_s": 2, "nvs_fault": fault})], 0)
        split[fault[0]] = (sorted({(v["inv"], c, s) for _i, v, c, s in vs}), w.status("dump"), w.nvs_marker("dump"),
                           w.bank[244])
    want = {k: ([("INV-NO-SILENT-OVERRIDE", PB01_FINDINGS[s]["classification"], s)], "Inactive", "ABSENT", 0)
            for k, s in (("erase_all", "partition-erase"), ("absent", "false-absent"))}
    check("classifier: a Dump lease lost at boot (the F-FW04-4 / F-FW04-1 forms) gives only INV-NO-SILENT-OVERRIDE, "
          "classified by its trigger - erase_all -> FINDING-KNOWN:NVS-PARTITION-ERASE, ('absent', dump marker) -> "
          "FINDING-KNOWN:PLATFORM-ABSENT (status Inactive, marker ABSENT, 244 = 0 live; no INV-BOOT-MIRROR)",
          split == want, str(split))
    # classifier precision on a hand-built two-boot log: the Free Power marker lost to a single-key absent at boot 1, the
    # Dump marker to a partition erase at boot 2 (232 is Free Power's only, 244 Dump's / reg244's, 256 is shared)
    def obl(dom=None):
        o = {d: {"snap": d == dom} for d in ("fp", "dump", "r244")}
        o["nvs"] = {d: "RESTORE_REQUIRED" if d == dom else "ABSENT" for d in ("fp", "dump", "r244")}
        return o
    base = [("fw.obl", obl("fp")), ("fw.boot", {"nvs_fault": ["absent", L.MARKER_TAGS["fp"]], "keys": []}),
            ("fw.booted", {"obl": obl()}), ("fw.obl", obl("dump")), ("fw.boot", {"nvs_fault": ["erase_all"], "keys": []}),
            ("fw.booted", {"obl": obl()})]
    got = {}
    for name, diff in (("dump only", {"244": [2, 0]}), ("fp only", {"232": [0, 1]}),
                       ("mixed", {"232": [0, 1], "244": [2, 0]}), ("ambiguous", {"256": [8000, 1400]})):
        evs = [{"seq": i, "t_utc": i, "up_ms": 0, "boot": 0, "src": "fw", "kind": k, "data": d}
               for i, (k, d) in enumerate(base + [("fw.quiet", {"diff": diff, "visible": []})])]
        c, why = pb01_classify({"inv": "INV-NO-SILENT-OVERRIDE", "seq": len(evs) - 1, "tags": [], "detail": ""}, evs)
        got[name] = (c, why if c else " ".join(why.split(" ")[:5]))
    check("classifier negative control (hand-built log, FP lost to a single-key absent, then Dump to an erase): a "
          "difference one cause covers takes that cause's signature (244 -> partition-erase, 232 -> false-absent); one "
          "only the union covers (mixed) or that both causes cover (ambiguous, 256) is UNCLASSIFIED, never absorbed",
          lost_obligations([{"seq": i, "kind": k, "data": d} for i, (k, d) in enumerate(base)], len(base) - 1)
          == {"fp": "false-absent", "dump": "partition-erase"}
          and got == {"dump only": ("FINDING-KNOWN:NVS-PARTITION-ERASE", "partition-erase"),
                      "fp only": ("FINDING-KNOWN:PLATFORM-ABSENT", "false-absent"),
                      "mixed": (None, "silent override covered only by"),
                      "ambiguous": (None, "silent override covered by several")}, str(got))
    w, _d, vs = pb01_violations(list(PRIOR_DUMP), 0)
    prior_ok = w.nvs_marker("dump") == "CLEAR" and not vs and w.status("dump").startswith("RESTORED OK")
    check("a completed Dump lease leaves a stored CLEAR marker (the used-device precondition) and no violation", prior_ok,
          f"{w.nvs_marker('dump')} {w.status('dump')[:40]} {vs[:1]}")
    w, _d, vs = pb01_violations(list(PRIOR_DUMP + FPOS_DUMP) + [("reboot", {"down_s": 2})], 0)
    got = sorted({(v["inv"], c, s) for _i, v, c, s in vs})
    f = PB01_FINDINGS["false-positive-commit"]
    check(f"finding-reproduces:{f['fid']}:used-device (stale CLEAR marker, status Inactive, 244 = 0, only "
          f"INV-NO-SILENT-OVERRIDE with signature false-positive-commit -> {f['classification']})",
          prior_ok and w.nvs_marker("dump") == "CLEAR" and w.status("dump") == "Inactive" and w.bank[244] == 0
          and got == [("INV-NO-SILENT-OVERRIDE", f["classification"], "false-positive-commit")], str(got))
    w, _d, vs = pb01_violations(list(PRIOR_DUMP + FPOS_DUMP) + [("run_for", {"seconds": 500})], 0)
    check("control: the same false-positive commit without a reboot - the lease restores ('RESTORED OK'), 244 back to its "
          "ORIGINAL, no violation", not vs and w.status("dump").startswith("RESTORED OK")
          and w.bank[244] == w.original[244], f"{w.status('dump')[:40]} {[(v['inv'], s) for _i, v, _c, s in vs][:2]}")


# =============================================================================================================================
# run
# =============================================================================================================================
section_anchors()
pb01 = section_pb01()
section_pb01_controls()
overruns = section_pb02()
section_pb02_controls()
section_pb03(overruns)
section_corpus()
section_variants()
check("every PB-01 finding (and finding variant) of the catalogue reproduced in this run (none silently skipped)",
      sorted(FINDINGS) == sorted(SIG_BY_LABEL), str(sorted(FINDINGS)))
print(f"  info  findings: {len(FINDINGS)} reproduced, {len(counted())} counted in LAB-SUMMARY (not counted, duplicates: "
      + (", ".join(f"{lab} = {PB01_FINDINGS[SIG_BY_LABEL[lab]]['duplicate_of']}" for lab in sorted(FINDINGS)
                   if PB01_FINDINGS[SIG_BY_LABEL[lab]].get("duplicate_of")) or "none") + ")")

BLOCKED = [sid for sid, s in SCENARIOS.items() if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME_S = time.perf_counter() - T0
if EXTENDED:
    print(f"  info  EXTENDED runtime {RUNTIME_S:.1f} s")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=counted(), finding_pins=FINDING_CHECKS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
