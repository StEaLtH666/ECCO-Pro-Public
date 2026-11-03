#!/usr/bin/env python3
"""HF-02 / HF-03 / HF-05 / HF-09: Home Assistant and dongle lifecycle scenarios on the coupled tier - the REAL FPS1 /
DGS1 / SMR1 packages coupled to the REAL dongle firmware (_lab_ha.CoupledWorld), London time on a UTC-true timeline, the
synthetic site (_lab_fw.SITE) and synthetic schedule values only. Offline assurance lab V0 (test-only: no network, no Home
Assistant, no hardware; writes nothing).

Scope (LAB_SPEC section 3):
  HF-02 (P1) Home Assistant restart in STARTING (the retry loop kept STARTING by bus-busy windows or an RTC lock window) and
        in ACTIVE (graceful); the crash-window rollback of the package helpers (ASSUMPTION, the core's restart_ha: Home
        Assistant saves restore-state every 15 minutes and at a clean stop, docs/dev/schedule-manual-restore.md "Unclean
        shutdown"); ESPHome reconnect-gap variants.
  HF-03 (P1) a dongle reset right after the START gate pass, before the gate's publishes reach Home Assistant (PROXY,
        labelled: the core's arm_power_cut at START's FIRST Modbus read - no write, no commit yet; the coupled tier drops
        every publish of a cut entry and disconnects at the gate instant, which matches only such an early reset), its
        power-back instant swept against the 30 s attempt-counter sample grid (first-sample phase INFERRED in the core);
        cuts LATER inside the projected START transaction are UNSUPPORTED (HF-03-UNS-1: core NOT MODELLED 'A power cut
        between a projected transaction's ops'; Home Assistant would already have seen the gate's answer); a dongle reboot
        during ACTIVE; and a whole-site power cut (Home Assistant crash + dongle reboot at one instant) during a scheduled
        Dump to Grid.
  HF-05 (P2) owner edits of the staged request numbers during STARTING / ACTIVE / RESTORING with the real firmware reading
        them, and an owner manual START racing the schedule (V0.1: a schedule-shaped edit while STARTING is the
        documented limit SMR1-OWNER-STAGING, checked as PASS; formerly F-HF05-1, see RECLASSIFIED).
  HF-09 (P2) unexpected Home Assistant service exceptions against the real firmware coupling: the interpreter's own fault
        hook (World.fail_services, home-assistant/tests/_ha_script_sim.py) makes one stated dongle call raise
        S.ServiceError - FPS1's scheduled START press; DGS1's write-enable turn_on while staging (once, and every call);
        an SMR1 restore write right after the real firmware's restore; the closing post-START write-enable turn_off; the
        no-answer branch's turn_off - and the core's offline_policy='raise' turns every call to the dongle during an
        ESPHome API outage into one. What is NEW against the model suites' fail_services cases
        (home-assistant/tests/test_ecco_free_power_schedule_reliability.py, test_ecco_dump_to_grid_schedule_reliability.py,
        test_ecco_schedule_manual_restore.py) is the REAL firmware on the other side: its START gate, its RAM gate-pass
        counter that the no-answer proof reads, its own write-enable disarm at a press, its restore before SMR1's.

Reading the output: PASS = an invariant that holds (or documented behaviour asserted exactly); '  FINDING  <id>' = a
reproduced deviation, asserted by a 'finding-reproduces:<id>' check (a later fix makes that check FAIL and forces
re-classification; findings are NOT counted as passes); '  UNSUPPORTED  <id>' = an interleaving the harness refuses
(LabUnsupported inside a projected firmware transaction), never a pass. SCENARIOS names, per scenario, the ownership
assumptions, the source anchors (each verified to occur exactly once at run time; line numbers are information), the
invariant, the failure outcome, the classification, the evidence grade and the confidence; FINDINGS gives the mechanism,
the severity, the real-world reachability and the smallest safe repair scope (described only, never implemented).
Negative controls mutate one real guard per family IN MEMORY (exact-count text replace; firmware through _lab_fw.load_fw,
packages through CoupledWorld(package_texts=...)) and must make the intended invariant check fail without a harness error.
'every firmware invariant' means the core's default _lab_fw.INVARIANTS set over the merged log with world = the
FirmwareWorld (INV-BOOT-MIRROR included; the dongle-reboot checks of HF-03.3 / HF-03.4 also assert that it is judged at
a boot whose stored marker is RESTORE_REQUIRED, so it is not vacuous there).

Suite-local invariants (observers over the merged log, not models; each has a hand-built negative control in [1]):
  INV-HF-PRESS-PROOF - within one run of a scheduled start script, no START press follows an earlier press of that run
    whose firmware gate passed. Gate-pass evidence: the firmware's own 'STARTING - taking fresh inverter snapshot' status,
    published right after its gate-pass counter increment ('id(free_power_start_attempts)++;' /
    'id(dump_start_attempts)++;'). It is the packages' own stated guarantee ('nothing is retried once a start transaction
    has begun', ecco_free_power_schedule.yaml header; 'No retry after an ambiguous outcome',
    docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md).
  INV-HF-NO-RESUME - once the dongle's on_boot has ended a lease (FP S3 'ACTIVE - reboot recovery pending', Dump 'ESP
    RESTARTED DURING LEASE - ended, not resumed'), no schedule START press for that domain until the owner arms again:
    the firmware's documented no-resume design carried to the coupled level (a design property, see F-HF03-2).
  INV-HF-NEVER-SILENT - a scheduled run that reached STARTING ends with a terminal result (STARTED / FAILED / CANCELLED /
    BLOCKED / MISSED) or an alert; its result is never overwritten by a non-terminal text after its script stopped:
    the documented claim 'any run that ends without STARTED / CANCELLED raises the alert'
    (docs/incidents/2026-10-11-scheduled-free-power-start.md).

MODEL / ASSUMPTION dependence: everything the core documents (_lab_ha MODEL ASSUMPTIONS: projection, latencies, offline
policy 'silent', restart_ha rollback and last_changed, reconnect gap, polled-sensor first sample one period after power-on;
_lab_fw: synchronous scripts, interval anchoring, preferences). This suite adds no model; its one PROXY (HF-03.1, above)
is an interpretation of the core's existing cut path, stated where it is used. The firmware-truth write-enable sampler
reads the firmware switch state on the World clock (0.25 s grid) and only observes. The owner's via='dongle' edits and
presses (HF-05) are a modelled path: the shipped firmware has no web_server, so only another native-API client could take
it; the via='ha' path is the owner's realistic one.
HF-09 fault model (ASSUMPTIONS, stated where used): S.ServiceError is the interpreter's ONLY modelled exception class
(vol.Invalid, other HomeAssistantError subclasses and a timeout after the command was sent are NOT modelled); World.call
raises it after the ha.call record and BEFORE the handler, so a faulted dongle command never reaches the firmware (a
'raised but delivered' call is NOT modelled); the hook is keyed by service name, so each injection is armed at an instant
where the targeted call is the next call of that service and each check asserts which call raised. No coupled replay
action injects fail_services (the core is frozen): HF-09.1 to HF-09.5 are suite-only; the corpus documents HF-09-a / -b
reach S.ServiceError through the core's offline path (api_outage with offline_policy 'raise', the
home-assistant/tests/_ha_dump_sim.py assumption) instead.

Quick mode (default): about 40 s here. ECCO_LAB_EXTENDED=1 / --extended (about 70 s in total) adds the full early-reset
sweep (Free Power and Dump to Grid x 14 down times), the two remaining in-transaction cut points (UNSUPPORTED basis), the
whole-site power-cut grid (5 x 3), a reconnect-gap variant of the crash finding, the Free Power analogue of the
whole-site cut, a dump_plant (MODEL plant) mid-window variant, the HF-09 analogues of the other domain and an API-outage
length sweep for F-HF09-1, and prints its runtime.
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
REPRODUCED: list[str] = []      # held 'finding-reproduces:' checks (LAB-SUMMARY 'finding_pins', never in 'pass')
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
    "fp early reset down": (
        "audit-named (HF-03 reach): whether an early reset ends in the retry (F-HF03-1) or the safe branch is the "
        "order of Home Assistant's decision against the first sample of the 30 s polled attempt counter, which the "
        "lab takes one period after power-on (ISS-HA-1; ESPHome samples within 5 s of setup); the branch is in the "
        "check name (held under the phase patch in every run; the 35 s point turns into a retry there)"),
    "finding-reproduces:F-HF03-1 (": (
        "audit-named (HF-03 reach): the retry reproductions of the early-reset sweep; which swept points retry is "
        "the polled counter's first-sample phase (4 of 6 on the lab grid, 5 of 6 under the phase patch; held in "
        "every run)"),
    "corpus HF-02-a: replay ok": _PS_DIGEST,
    "corpus HF-02-b: replay ok": _PS_DIGEST,
    "corpus HF-02-c: replay ok": _PS_DIGEST,
    "corpus HF-02-d: replay ok": _PS_DIGEST,
    "corpus HF-03-a: replay ok": _PS_DIGEST_EXP,
    "corpus HF-03-b: replay ok": _PS_DIGEST,
    "corpus HF-03-c: replay ok": _PS_DIGEST,
    "corpus HF-05-a: replay ok": _PS_DIGEST,
    "corpus HF-05-b: replay ok": _PS_DIGEST_EXP,
    "corpus HF-09-a: replay ok": _PS_DIGEST,
    "corpus HF-09-b: replay ok": _PS_DIGEST,
    "dump early reset down": (
        "audit-named (HF-03 reach), the Dump twin of 'fp early reset down': the branch (retry or safe) of each swept "
        "early reset is the polled attempt counter's first-sample phase; quick mode's only Dump point retries (a "
        "pin), so the branch checks run in extended mode only (held under the phase patch)"),
    # V0.1 review: the HF-03.4 whole-site cut grid (R3-1) and the finding register (R3-5)
    "HA down ": (
        "audit-named (HF-03 reach): the whole-site power-cut grid of HF-03.4 (per point the firmware-end check and, on "
        "the no-new-lease branch, the 'Home Assistant read Dump Active before the firmware's boot restore' check; the "
        "branch is in the check name, the new-lease branch is the F-HF03-2 pin). Which grid points start a new Dump "
        "lease depends on whether Home Assistant's post-restart read of the Dump status comes before the firmware's "
        "boot restore, i.e. on the watchdog phase after the dongle boot. Measured under an ESPHome-like phase patch, "
        "17 quick configurations: the section is refused at its first point in 12 (LabUnsupported, an interleaving "
        "inside a projected firmware transaction; the suite stops: setup-anchored seeds 1-5, the fw-only and the "
        "fw/resched/ha variants at seeds 1-3, power-on-anchored seed 1); where it ran (setup seeds 6-8, power-on "
        "seeds 2-3) the 5 s / 5 s point took the no-new-lease branch in 4 of 5 (a new lease at power-on seed 3), the "
        "60 s and 120 s / 5 s points started a new lease and the 60 s / 90 s point did not. Extended grid (15 points) "
        "at those 5 seeds: the 5 s / 5 s and 30 s / 30 s points took the no-new-lease branch in 4 of 5 (a new lease "
        "at 9 of 15 points, 11 of 15 on the lab grid). Every check that ran held"),
    "finding-reproduces:F-HF03-2 (": (
        "the F-HF03-2 reproductions of the whole-site cut grid (see the 'HA down ' tag): a point's pin is absent (the "
        "point takes the held no-new-lease branch instead, no FAIL line) wherever the phase puts Home Assistant's "
        "read before the boot restore - under an ESPHome-like phase patch the 5 s / 5 s pin (and in extended mode "
        "also the 30 s / 30 s pin) in 4 of the 5 patched quick configurations in which the section ran; the 60 s / "
        "5 s and 120 s / 5 s pins held wherever it ran"),
    "finding register: every FINDINGS entry was reproduced": (
        "meta-check over the suite's printed findings: it holds only while every FINDINGS entry prints a FINDING line, "
        "and the reach of F-HF03-1 (the early-reset sweep) and F-HF03-2 (the whole-site cut grid) is phase-dependent "
        "(see 'fp early reset down' and 'HA down '); under an ESPHome-like phase patch it is not reached in the 12 of "
        "17 patched quick configurations that refuse HF-03.4 and it held in the other 5, where F-HF03-2 still "
        "reproduced at 2 or 3 of its 3 quick new-lease grid points"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = (
    "dump early reset down",
)
PHASE_SENSITIVE: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (REPRODUCED if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + REPRODUCED + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import os  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_ha as H  # noqa: E402

SUITE = "test_lab_ha_lifecycle"
FIXED_LOCAL = S.LOCAL
U0 = C.utc_of_local(2026, 10, 21, 11, 50)          # synthetic Wednesday (BST); every world starts here
ST = C.utc_of_local(2026, 10, 21, 12, 0)           # the synthetic scheduled start, 12:00:00 BST
START_LOCAL = "2026-10-21 12:00:00"
IDLE = H.BusModel(windows=[])                      # a never-busy bus (nominal runs)
BUSY_START = H.BusModel(windows=[(ST - 1, ST + 120)])   # bus busy for the first 2 min: the schedule stays STARTING
WARM = {"warmup_s": 120}                           # a warm dongle (polled sensors sampled; effective limit available)
GATE_TEXT = "STARTING - taking fresh inverter snapshot"
EMAP = H.dongle_entity_map()
HA_OF = {fid: hid for hid, (fid, _k) in EMAP.items()}
END_HA = {d: HA_OF[H.END_BUTTON[d]] for d in H.DOMS}
ARM_FID = {d: EMAP[H.ARM[d]][0] for d in H.DOMS}
CORPUS_DIR = HERE / "corpus"
FPS1, DGS1, SMR1 = H.PACKAGES["fps1"], H.PACKAGES["dgs1"], H.PACKAGES["smr1"]
FW = L.FW_REL
SMR1_DOC = "docs/dev/schedule-manual-restore.md"
INC_FP = "docs/incidents/2026-10-11-scheduled-free-power-start.md"
INC_DUMP = "docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md"
FB_BASIS = "docs/architecture/fallback/FALLBACK_DESIGN_BASIS.md"
CARD_TS = "frontend/ecco-energy-actions-card/src/schedule.ts"
SIM = "home-assistant/tests/_ha_script_sim.py"
DUMP_SIM = "home-assistant/tests/_ha_dump_sim.py"
FPS1_MODEL = "home-assistant/tests/test_ecco_free_power_schedule_reliability.py"
DGS1_MODEL = "home-assistant/tests/test_ecco_dump_to_grid_schedule_reliability.py"
SMR1_MODEL = "home-assistant/tests/test_ecco_schedule_manual_restore.py"
PRESS_HA = {"fp": S.E_PRESS, "dump": D.D_PRESS}
WE_HA = {"fp": S.E_ARM, "dump": D.D_ARM}
LABEL = {"fp": "Free Power", "dump": "Dump to Grid"}
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

# =============================================================================================================================
# scenario and finding tables (the result fields are filled by the run and printed at the end)
# =============================================================================================================================
LAB_HA = "registry/tests/assurance_lab/_lab_ha.py"
SCENARIOS = [
    {"id": "HF-02", "priority": "P1",
     "title": "Home Assistant restart in STARTING / ACTIVE, crash-window helper rollback, ESPHome reconnect gaps",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "invariant": "INV-HF-OWNER-INTENT",
     "ownership": ("the owner arms one schedule and may press End & Restore (or move the start helper); Home Assistant "
                   "runs FPS1 / DGS1 / SMR1; the dongle firmware owns every inverter write; nothing else writes the "
                   "inverter; a crash rolls every package helper back to its value at the last restore-state save "
                   "(ASSUMPTION, 15-minute cadence)"),
     "anchors": [(FPS1, "  - id: ecco_free_power_schedule_startup_recovery"),
                 (FPS1, "Home Assistant restarted during the scheduled Free Power window. ECCO is starting it now"),
                 (FPS1, "# Not armed any more, or the on-time start is already running: nothing to recover."),
                 (FPS1, "# Disarm only the schedule this run was for (the owner may have re-armed a new one)."),
                 (FPS1, "# Only the start trigger starts on time; a readiness or watchdog tick never falls through to "
                        "here."),
                 (FPS1, "# A restart between an arm and its press must not leave the write enable on (unless a start "
                        "is running)."),
                 (FPS1, "duration_now: >-"),
                 (DGS1, "Home Assistant restarted during the scheduled Dump to Grid window. ECCO is starting it now"),
                 (SMR1, "# Home Assistant saves restored states every 15 minutes"),
                 (SMR1_DOC, "- **Unclean shutdown.** Home Assistant saves restored helper states every 15"),
                 (INC_FP, "- **Restart recovery** waits (bounded) for the dongle to reconnect before judging, records a "
                          "session that is already running,"),
                 (INC_FP, "for about 20 s to 3 minutes after a Home Assistant restart, startup recovery turns off a Free "
                          "Power write enable that the"),
                 (INC_FP, "a later success clears it."),
                 (FPS1, "ARMED AFTER RESTART - waiting for"),
                 (INC_FP, "any run that ends without STARTED / CANCELLED raises the alert"),
                 (CARD_TS, "* Start/power/duration editing locks while a schedule is armed - cancel,")],
     "failure_outcome": ("an unrequested second energy session (grid charge / battery export) after the owner's End & "
                         "Restore or a firmware early end; a false 'MISSED' alert; a write enable left on after a restart; "
                         "a false SMR1 RESTORED; an in-progress run abandoned silently"),
     "corpus": ["HF-02-a", "HF-02-b", "HF-02-c", "HF-02-d"], "findings": ["F-HF02-1", "F-HF02-2", "F-HF02-3"]},
    {"id": "HF-03", "priority": "P1",
     "title": "Dongle reset right after the START gate pass (early-reset PROXY), during ACTIVE, and a whole-site power cut "
              "during a scheduled Dump",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "medium",
     "invariant": "INV-HF-PRESS-PROOF",
     "ownership": ("the owner arms one schedule; the dongle resets right after the START gate pass (PROXY: the core's "
                   "arm_power_cut at START's first Modbus read; later in-transaction cuts are UNSUPPORTED) or loses "
                   "power through reboot_dongle; the firmware's full on_boot decides recovery; RAM attempt counters "
                   "reset; HA reads the polled counters only from samples ('unknown' before the first sample)"),
     "anchors": [(FPS1, "#   - nothing is retried once a start transaction has begun (the firmware then owns restore), "
                        "and"),
                 (FPS1, "{% set now_a = states('sensor.ecco_clock_dongle_free_power_start_attempts_since_boot') | "
                        "float(-1) %}"),
                 (FPS1, "# No answer to this press (the switch still reads ON). Either the press never reached the"),
                 (DGS1, "{% set now_a = states('sensor.ecco_clock_dongle_dump_to_grid_start_attempts_since_boot') | "
                        "float(-1) %}"),
                 (FW, "  - id: free_power_start_attempts"),
                 (FW, "id(free_power_start_attempts)++;"),
                 (FW, "id(dump_start_attempts)++;"),
                 (FW, 'id(free_power_status).publish_state("STARTING - taking fresh inverter snapshot");'),
                 (FW, "- id: supervision_boot_nonce"),
                 (FW, "// S3: a temporary Free Power lease must never silently"),
                 (FW, "Free Power was ACTIVE at last shutdown - ending and restoring on this boot rather than resuming "
                      "the lease"),
                 (FW, "NEVER resumes a Dump lease (Stop SOC is not persisted"),
                 (FW, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
                 (DGS1, "  - id: ecco_dump_to_grid_schedule_startup_recovery"),
                 (FB_BASIS, "**A reboot never resumes a temporary operation.**"),
                 (INC_DUMP, "- **No retry after an ambiguous outcome.**"),
                 (LAB_HA, "  - A power cut between a projected transaction's ops (use the firmware tier's arm_power_cut "
                          "sweeps), a torn NVS record."),
                 (LAB_HA, "        if rebooted:\n            self._self_reboot()\n            return")],
     "failure_outcome": ("a second START press after a passed START gate ('never reached the dongle'); a lease resumed "
                         "after a reboot; a new Dump lease after the firmware deliberately ended one, its alert dismissed"),
     "corpus": ["HF-03-a", "HF-03-b", "HF-03-c"], "findings": ["F-HF03-1", "F-HF03-2"]},
    {"id": "HF-05", "priority": "P2",
     "title": "Owner edits of the staged values during STARTING / ACTIVE / RESTORING; owner manual START racing the "
              "schedule",
     # V0.1 (brief B6.3): F-HF05-1 (SMR1-OWNER-STAGING) is a documented limit, reclassified PASS and not counted (see
     # RECLASSIFIED); the scenario's remaining counted finding is F-HF05-2, so its label is SMR1-OWNER-RESTORING
     "classification": "FINDING-KNOWN:SMR1-OWNER-RESTORING", "grade": "VERIFIED", "confidence": "high",
     "invariant": "INV-HF-NO-FALSE-SUCCESS",
     "ownership": ("the owner changes the shared Free Power request numbers through Home Assistant (or, modelled, another "
                   "native-API client: via='dongle') while a scheduled run stages, runs or is restored by SMR1; or "
                   "starts Free Power by hand near the schedule; the firmware reads the numbers only at START"),
     "anchors": [(SMR1_DOC, "- **Owner change during a scheduled start.**"),
                 (SMR1_DOC, "- **Owner change during the restore.**"),
                 (SMR1_DOC, "the restore writes only a number that still holds the schedule's value"),
                 (SMR1, "  - id: ecco_sched_restore_fp_track"),
                 (SMR1, "{% else %}{{ 1 <= n <= (states('input_number.ecco_free_power_schedule_duration') | float(0)) }}"
                        "{% endif %}"),
                 (SMR1, "  - id: ecco_sched_restore_fp_restore"),
                 (SMR1, 'value: "RESTORING {{ owed_since }} - putting back the manual Free Power values"'),
                 (SMR1, "{% for e, why in checks if not is_state(e, 'off') %}"),
                 (FPS1, 'value: "BLOCKED - Free Power already active"'),
                 (FPS1, "# Press only once the dongle has confirmed the arm and both staged values."),
                 ("CHANGELOG.md", "change always wins."),
                 (INC_DUMP, "Never two transactions.")],
     "failure_outcome": ("SMR1 reports RESTORED while the owner's latest value is not on the number (the owner's change "
                         "lost silently), outside the documented STARTING limit (a schedule-shaped change is taken for the "
                         "schedule's write); two START transactions"),
     "corpus": ["HF-05-a", "HF-05-b"], "findings": ["F-HF05-2"]},
    {"id": "HF-09", "priority": "P2",
     "title": "Unexpected Home Assistant service exceptions against the real firmware coupling: the scheduled START press, "
              "DGS1's write-enable arm, an SMR1 restore write right after a real firmware restore, the post-START and "
              "no-answer write-enable turn-offs",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "medium",
     "invariant": "INV-HF-ARM-OFF",
     "ownership": ("the owner arms one schedule; Home Assistant runs FPS1 / DGS1 / SMR1; the dongle firmware owns every "
                   "inverter write; nothing else writes the inverter; ONE stated dongle-facing service call (or every "
                   "call during an ESPHome API outage under offline_policy 'raise') raises S.ServiceError before it "
                   "reaches the dongle (ASSUMPTION: the interpreter's only exception class, raised before delivery); "
                   "nothing else fails"),
     "anchors": [(SIM, 'self.fail_services: dict[str, int] = {}     # test hook: "domain.service" -> number of calls that '
                       'raise'),
                 (SIM, "            raise ServiceError(service)"),
                 (SIM, 'self.w.warnings.append(f"{self.w.t:.3f} {service} raised (continue_on_error)")'),
                 (FPS1, "                        - action: button.press\n                          continue_on_error: true\n"),
                 (FPS1, "      # The write enable always ends off (the safe state: it only permits a START)."),
                 (FPS1, "unconfirmed, not retried (last status: {{ status_now }})"),
                 (DGS1, "arm or staged values not confirmed; nothing pressed"),
                 (SMR1, "ONE attempt, verified;"),
                 (INC_FP, "**Never silent:** dongle service calls continue on error"),
                 (INC_DUMP, "the ESPHome integration raises a service error for a call to a disconnected device"),
                 (FW, "# and auto-disarms as soon as Start Free Power is pressed. Ending/restoring never"),
                 (DUMP_SIM, "a call to a dongle entity while the dongle is offline raises in Home Assistant"),
                 (FPS1_MODEL, 'r.w.fail_services["button.press"] = 1'),
                 (FPS1_MODEL, 'r.w.fail_services["switch.turn_on"] = 99'),
                 (DGS1_MODEL, 'r.w.fail_services["button.press"] = 1'),
                 (DGS1_MODEL, 'r.w.fail_services["switch.turn_on"] = 99'),
                 (SMR1_MODEL, 'x.at(300, lambda: x.w.fail_services.__setitem__("number.set_value", 1))')],
     "failure_outcome": ("a run aborted by a service error with its result left open; a START press retried after a "
                         "passed gate; a false RESTORED after a failed restore write; a write enable left ON after the run "
                         "(it permits a START without an arm step) with SMR1's restore blocked"),
     "corpus": ["HF-09-a", "HF-09-b"], "findings": ["F-HF09-1"]},
]
SCEN = {s["id"]: s for s in SCENARIOS}

FINDINGS = {
    "F-HF02-1": {
        "scenario": "HF-02", "classification": "FINDING-NEW", "invariant": "INV-HF-OWNER-INTENT",
        "grade": "VERIFIED", "confidence": "high", "priority": "P2",
        "title": "crash-window rollback restores 'armed' ON after the scheduled run already started: the startup recovery "
                 "starts an unrequested second session after the owner's End & Restore (Free Power, Dump to Grid) or a "
                 "firmware early end, and raises a false 'MISSED - Nothing was started' after a natural end",
        "mechanism": ("root cause: the FPS1 / DGS1 startup recovery decides only from package helpers (armed, start, "
                      "duration) + the clock + Active, and an unclean stop rolls those helpers back together (restore-"
                      "state ASSUMPTION); it reads nothing the dongle holds. The fire automation disarms after its start "
                      "script returns (on-time branch after '# Only the start trigger starts on time ...'; lab: start + "
                      "7.3 s FP / + 5.5 s Dump): a last save before that disarm and a crash before the next save bring "
                      "'armed' back ON. With the lease already ended (owner End, or a firmware end such as CONTROLLER NO "
                      "RESPONSE) and the window open, '# Not armed any more ...' does not apply, Active reads off and the "
                      "'now_ts < end_ts' branch alerts 'start was missed' and starts the rest of the window; the run's "
                      "success dismisses that alert (documented 'a later success clears it.'), so nothing records that "
                      "the End was overridden. After a natural end (window over) the default branch records 'MISSED' "
                      "with a 'Nothing was started' alert for a run that completed"),
        "severity": ("low: owner intent / cost plus diagnostics (lab: FP 3000 W for 13 min after the owner's End, about "
                     "0.65 kWh of grid charge inside the authorised window; Dump 1000 W for 25 min to the schedule's Stop "
                     "SOC 20 %; after a firmware early end a new gated lease; after a natural end a false MISSED alert); "
                     "no electrical-safety impact: the window end, the effective limit, Stop SOC and every firmware START "
                     "gate still apply"),
        "reachability": ("INFERRED, low: an HA-only unclean stop (power loss, OOM kill, a hung core killed by a watchdog) "
                         "after the lease ended; the last restore-state save must precede the fire automation's disarm "
                         "(start + about 3-13 s across latency sets) and the crash must precede the next save, so crash "
                         "<= start + 15 min (for a uniformly random save phase the chance falls linearly from 1 just "
                         "after the start to 0 at start + 15 min); Home Assistant back before the window ends (after it "
                         "for the false MISSED). The 15-minute cadence is the premise of SMR1's documented limit (not "
                         "measured); a whole-site cut is F-HF03-2"),
        "repair": ("FPS1 / DGS1 startup recovery only (read-only checks; the change can only hold back a START): before "
                   "starting the rest of a window, require evidence a crash rollback cannot undo that this window's run "
                   "has not started, else record + alert 'interrupted, not restarted' with a notification the run's own "
                   "success does not dismiss. Evidence and caveats: the dongle's 'Start Successes Since Boot' above an "
                   "arm-time baseline (one new HA helper written with armed, so it rolls back with it; a counter reset "
                   "by a dongle reboot, lower or unavailable, counts as 'cannot prove not started'); for Dump the 'Dump "
                   "to Grid Last End Reason'; Free Power has no end-reason sensor. Simplest conservative option, a "
                   "design decision: after an unclean restart the recovery only records and alerts, never restarts"),
        "anchors": [(FPS1, "# Only the start trigger starts on time; a readiness or watchdog tick never falls through "
                           "to here."),
                    (FPS1, "# Not armed any more, or the on-time start is already running: nothing to recover."),
                    (FPS1, "Home Assistant restarted during the scheduled Free Power window. ECCO is starting it now"),
                    (DGS1, "Home Assistant restarted during the scheduled Dump to Grid window. ECCO is starting it now"),
                    (INC_FP, "a later success clears it."),
                    (SMR1, "# Home Assistant saves restored states every 15 minutes")]},
    "F-HF02-2": {
        "scenario": "HF-02", "classification": "FINDING-KNOWN:SMR1-UNCLEAN-SHUTDOWN", "invariant": "INV-HF-NO-FALSE-SUCCESS",
        "grade": "VERIFIED", "confidence": "high", "priority": "P3",
        "title": "a crash during STARTING loses the SMR1 obligation (documented); the recovery's re-stage then saves a "
                 "schedule-staged duration as the owner's and SMR1 reports a false RESTORED (consequence undocumented: "
                 "the limit text understates it)",
        "mechanism": ("the rollback clears SMR1's saved / written / state helpers (documented: the obligation is lost). "
                      "The recovery run re-stages and its retry clamps the duration again (FPS1 'duration_now: >-', "
                      "min(requested, window remainder)): the first run had staged 19 min on its 4th retry before the "
                      "crash; the recovery stages 19 (no change), then 18 on its retry; the SMR1 track sees old 19 -> "
                      "new 18 while the script runs, a schedule-shaped value and written <= 0 (its only episode marker, "
                      "itself a restore-state helper) and saves the OLD 19 - a schedule value - as the owner's; the "
                      "restore writes 19, verifies it and reports 'RESTORED - restored: duration 19 min' (no "
                      "notification) while the owner's 8000 W / 40 min are lost. The limit text says the values 'then "
                      "stay at the schedule's, as without smr1'; it does not say SMR1 creates a new obligation and "
                      "reports RESTORED"),
        "severity": ("low: diagnostics only - the new harm is the false RESTORED text (losing the owner's 8000 W / 40 min "
                     "without a notification is the documented limit); no inverter write, no gate touched; SMR1's one "
                     "extra write is a staging number back to a schedule value after the lease ended"),
        "reachability": ("INFERRED, low: an unclean HA stop while a scheduled start retries (seconds; minutes only under "
                         "persistent gate refusals - the lab's 2-min bus window is synthetic), the last restore-state "
                         "save between the arm and the first staging, HA back before the window ends, and a recovery "
                         "re-stage that crosses a minute boundary (almost always after about 60 s); a crash in ACTIVE "
                         "gives no re-stage (HF-02.3: the documented outcome exactly); the Dump track has the same save "
                         "condition (Dump analogue INFERRED, not executed)"),
        "repair": ("primary, zero code risk: extend the 'Unclean shutdown' limit text (docs/dev/schedule-manual-restore.md "
                   "and the package header): a recovery re-stage can then record and report RESTORED for a schedule-"
                   "staged duration; re-check the manual values after an unclean restart near a scheduled start. "
                   "Optional SMR1 track hardening: when written <= 0 and the change is a downward duration step with "
                   "OLD <= the schedule's duration, do not save; record 'LOST - obligation lost after an unclean "
                   "restart' with a notification (no new write path; its residual false positive is reported, not "
                   "silent). Not the first suggestion (never save any schedule-shaped OLD value): it would stop saving "
                   "an owner duration at or below the schedule's on every normal run"),
        "anchors": [(SMR1, "  - id: ecco_sched_restore_fp_track"),
                    (FPS1, "duration_now: >-"),
                    (SMR1_DOC, "- **Unclean shutdown.** Home Assistant saves restored helper states every 15")]},
    "F-HF02-3": {
        "scenario": "HF-02", "classification": "FINDING-NEW", "invariant": "INV-HF-NEVER-SILENT",
        "grade": "VERIFIED", "confidence": "high", "priority": "P3",
        "title": "a graceful Home Assistant restart while STARTING, after the owner moved the start helper without "
                 "disarming, abandons today's in-progress run silently ('ARMED AFTER RESTART', no alert, no lease); "
                 "Free Power and Dump to Grid",
        "mechanism": ("the stop kills the running start script before its final result / alert steps (HA stops running "
                      "scripts at shutdown; the sim's S.HA.stop does the same); the startup recovery reads the EDITED "
                      "start helper (tomorrow): 'armed' on and the script off skip its first branch, 'now_ts < "
                      "start_ts' holds and it writes 'ARMED AFTER RESTART - waiting for <tomorrow>' over the open "
                      "'STARTING' result in a branch with no notification; today's watchdog (keyed on the helper) never "
                      "fires. Without the restart the same run continues and starts: a start-helper edit is not a "
                      "cancel ('Cancel wins' in docs/incidents/2026-10-11-scheduled-free-power-start.md; FPS1 '# Disarm "
                      "only the schedule this run was for'). It breaks that record's 'Never silent' and 'Restart "
                      "recovery' claims across the restart"),
        "severity": ("low: diagnostics (the overwritten STARTING record has no 'interrupted' note and no alert); no safety "
                     "impact (no-write direction: no START, the write enable turned off); availability / cost only if "
                     "the owner meant today (moving the start may mean 'not today')"),
        "reachability": ("INFERRED, very low: (a) a run still in STARTING - seconds normally, minutes only under transient "
                         "gate refusals; (b) the owner edits the start helper without disarming inside that window - the "
                         "shipped Energy Actions card locks start / power / duration while armed (schedule.ts "
                         "scheduleFieldsLocked; README 'cancel, edit, then re-arm is the only path'), so only a path "
                         "around that frontend-only lock (the helper's own dialog, developer tools, an automation) "
                         "reaches it; (c) a graceful HA restart inside the same window. A crash can roll the helper back "
                         "(restore-state), which changes the outcome: the finding is graceful-only"),
        "repair": ("FPS1 / DGS1 startup recovery, 'now_ts < start_ts' branch only: when last_result starts with "
                   "'STARTING' (a run cut by the restart), record 'INTERRUPTED by a Home Assistant restart; not resumed; "
                   "schedule now reads <start>' and create the schedule's notification (input_text.set_value + "
                   "persistent_notification.create only; no new write path; the write-enable turn-off and the other "
                   "branches unchanged; a stale STARTING after a crash gives at worst a spurious alert). Not 'recover "
                   "the interrupted window' (its window variables die with the script; it adds an automatic START where "
                   "intent is ambiguous). Smaller still: document it as a residual in the incident's 'Not covered' list"),
        "anchors": [(FPS1, "ARMED AFTER RESTART - waiting for"),
                    (INC_FP, "any run that ends without STARTED / CANCELLED raises the alert"),
                    (INC_FP, "- **Restart recovery** waits (bounded) for the dongle to reconnect before judging, records "
                             "a session that is already running,"),
                    (CARD_TS, "* Start/power/duration editing locks while a schedule is armed - cancel,")]},
    "F-HF03-1": {
        "scenario": "HF-03", "classification": "FINDING-NEW", "invariant": "INV-HF-PRESS-PROOF",
        "grade": "INFERRED", "confidence": "medium", "priority": "P3",
        "title": "a dongle reset right after the START gate pass, before the gate's publishes reach Home Assistant: FPS1 / "
                 "DGS1 conclude 'never reached the dongle (no start counted)' and press START again (the cut START wrote "
                 "nothing; the retry is harmless, the proof text is false)",
        "mechanism": ("the gate-pass counters are RAM-only ('  - id: free_power_start_attempts', restore_value: no; "
                      "'id(free_power_start_attempts)++;' right before the 'STARTING - taking fresh inverter snapshot' "
                      "publish, all before any Modbus I/O). A reset after that increment and before ESPHome delivers the "
                      "gate's publishes (write enable off, STARTING: about the 0.12 s publish latency; the gate answered "
                      "0.117 s after a press, home-assistant/tests/_ha_dump_sim.py) leaves HA without an answer for 15 s "
                      "('# No answer to this press "
                      "...'): it disarms and SEES the switch off (the new boot's default after the reconnect), waits 35 "
                      "s and compares the counter: the new boot's sample 0 equals attempts_before 0 and nothing is in "
                      "progress / active / pending, so 'now_a == attempts_before' passes although the gate had passed, "
                      "and it retries. In that window the cut START had written no register and committed nothing (the "
                      "new boot reports 'Inactive'), so the second START is an ordinary gated START. PROXY: the harness "
                      "cuts at START's first Modbus read (the earliest cut event after the gate) and drops the entry's "
                      "publishes - faithful only for this early reset. A cut LATER in START is not this finding: HA has "
                      "then seen the gate's answer ('began' branch, never retried; a per-instance projection variant of "
                      "the cut path, tried outside this suite, showed 'began' for the data-commit / marker / write-256 / "
                      "active-commit cuts - REPORTED, not run here); in this harness those cuts are UNSUPPORTED "
                      "(HF-03-UNS-1)"),
        "severity": ("low: diagnostics and the letter of the documented claims ('nothing is retried once a start "
                     "transaction has begun', FPS1 header; 'No retry after an ambiguous outcome', docs/incidents/"
                     "2026-10-12-scheduled-dump-to-grid-start-review.md): "
                     "the first, real gate pass is reported as 'never reached the dongle (no start counted)', the run then "
                     "ends STARTED OK and the reset is invisible in HA; no electrical-safety or cost impact (nothing was "
                     "written). INFERRED, not executed: a fault that resets the dongle every time right after the gate "
                     "would repeat the START / reset cycle until the 10-minute retry deadline (each cycle gated, nothing "
                     "written)"),
        "reachability": ("INFERRED, very low: a reset inside the ~0.1-0.2 s between the gate pass and the delivery of its "
                         "publishes, on the first gate pass of that boot (attempts_before 0; with 1.0 the guard holds, "
                         "HF-03.2); HA must see the reconnect and the new boot's first counter sample before its check "
                         "(proxy sweep: retry for power back after 5..31 s, 'began' for 1..4 s, 'unconfirmed' for "
                         "34..40 s; the upper edge comes from the core's INFERRED first-sample phase, one 30 s period "
                         "after power-on - an earlier real first sample would widen it). A power cut sends no TCP close: "
                         "a slow disconnect detection leaves the switch at a stale 'on' at the check, the safe branch"),
        "repair": ("FPS1 / DGS1 no-answer branch only, HA side, read-only, no firmware change: capture, with "
                   "attempts_before, the per-boot nonce prefix of the 'ECCO Supervision Challenge' text sensor (firmware "
                   "'- id: supervision_boot_nonce'; '<8-hex per-boot nonce>-<generation>'; already read by "
                   "ecco_supervision_heartbeat.yaml) and retry only if both values are valid and the nonce is unchanged, "
                   "else 'outcome unconfirmed, not retried' (alerting); the challenge entity must stay enabled, and a "
                   "repeated nonce only falls back to today's behaviour. The first suggestion (the counter's last_changed "
                   "before the press) is more conservative but turns the designed retry after a plain API disconnect / "
                   "reconnect (the realistic lost press) into FAILED"),
        "anchors": [(FPS1, "{% set now_a = states('sensor.ecco_clock_dongle_free_power_start_attempts_since_boot') | "
                           "float(-1) %}"),
                    (FPS1, "# No answer to this press (the switch still reads ON). Either the press never reached the"),
                    (FW, "  - id: free_power_start_attempts"),
                    (FW, "- id: supervision_boot_nonce")]},
    "F-HF03-2": {
        "scenario": "HF-03", "classification": "FINDING-NEW", "invariant": "INV-HF-NO-RESUME",
        "grade": "VERIFIED", "confidence": "medium", "priority": "P2",
        "title": "whole-site power cut during a scheduled Dump: the firmware ends the lease ('ended, not resumed'), then "
                 "DGS1 startup recovery starts a NEW Dump lease whose 'start was missed' alert its own success dismisses "
                 "(or records a false 'STARTED OK - running'); a variant of the F-HF02-1 root cause",
        "mechanism": ("1. the dongle's full on_boot turns the persisted active lease into a restore request ('NEVER "
                      "resumes a Dump lease (Stop SOC is not persisted', end reason 'ESP RESTARTED DURING LEASE - ended, "
                      "not resumed') and the Dump watchdog restores about 15 s after power-on; 2. HA's crash rollback "
                      "restored 'armed' ON (restore-state ASSUMPTION, as in F-HF02-1); 3. its startup recovery reads Dump "
                      "Active 20 s after its start (bounded wait for the dongle) and decides only from armed + clock + "
                      "Active; 4. if the firmware restore already ran it alerts 'start was missed' and starts the rest "
                      "of the window, and the run's success dismisses that alert about 5 s later (documented 'a later "
                      "success clears it.'): the end state is a normal-looking 'STARTED OK ... (attempt 1 ...)' with no "
                      "notification, the firmware's end reason the only trace (overwritten when the new lease ends); "
                      "otherwise it records 'STARTED OK - running' for a lease the firmware has already ended. The "
                      "firmware never resumes (INV-NO-RESUME holds; the new lease is a fresh START); the design-basis "
                      "rule 'A reboot never resumes a temporary operation' is scoped to the firmware's boot path and is "
                      "not carried to the coupled level (suite-local INV-HF-NO-RESUME)"),
        "severity": ("low: diagnostics plus an owner-policy question. The new lease is fresh and fully gated (the firmware "
                     "refuses a START while a snapshot is still pending restore), inside the owner-authorised window, "
                     "power and Stop SOC 20 %, but in effect silent (its alert is dismissed); whether a lease should be "
                     "re-created after a site power cut (battery reserve) is undocumented. The other branch records a "
                     "false 'STARTED OK - running'"),
        "reachability": ("INFERRED, low: Home Assistant and the dongle lose power together (no UPS on them); the cut after "
                         "the disarm and before HA's next restore-state save (0-15 min after the start); HA back before "
                         "the window ends; the inverter's Modbus link up, so that the dongle's boot restore (about 15 s "
                         "after power-on) finishes before DGS1's read - the usual order (HA slower than the dongle) "
                         "gives the new lease, the other order the false 'running' record (sweep by down times)"),
        "repair": ("DGS1 (and FPS1) startup recovery only (it can only hold back a START): honour dongle-held evidence "
                   "before deciding - for Dump the 'Dump to Grid Last End Reason' starting 'ESP RESTARTED DURING LEASE' "
                   "(the firmware keeps a lease's first end reason; it has no timestamp, so on finding it record + alert "
                   "'interrupted, not restarted', never skip silently); do not record 'running' from Dump Active while "
                   "that reason or the restore state shows a reboot end; leave a notification the run's own success "
                   "does not dismiss. The F-HF02-1 counter evidence is NOT enough here (the dongle's counters reset on "
                   "its reboot), and Free Power has no end-reason sensor ('ACTIVE - reboot recovery pending' is "
                   "overwritten by the restore), so a Free Power fix needs another HA-visible signal. A design decision "
                   "whether any resume after a power cut is wanted"),
        "anchors": [(FW, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
                    (FW, "NEVER resumes a Dump lease (Stop SOC is not persisted"),
                    (DGS1, "Home Assistant restarted during the scheduled Dump to Grid window. ECCO is starting it now"),
                    (FB_BASIS, "**A reboot never resumes a temporary operation.**"),
                    (INC_FP, "a later success clears it.")]},
    "F-HF05-2": {
        "scenario": "HF-05", "classification": "FINDING-KNOWN:SMR1-OWNER-RESTORING", "invariant": "INV-HF-NO-FALSE-SUCCESS",
        "grade": "VERIFIED", "confidence": "medium", "priority": "P3",
        "title": "an owner change landing within about one command + publish latency of SMR1's restore write (on the "
                 "Home Assistant path: made while still OWED, seen during RESTORING) is overwritten and SMR1 reports "
                 "RESTORED with no notification - documented limit, documented consequence (PARTIAL / FAILED) wrong",
        "mechanism": ("after its 5 s settle SMR1 marks RESTORING and, from Home Assistant's possibly stale view (the "
                      "per-field 'states(f.number) == states(f.written)' re-check), writes the saved value; the track "
                      "drops a field as the owner's only while OWED ('# Any other change while owed is the owner's ...'), "
                      "so a change HA first sees during RESTORING is ignored; the firmware number is an optimistic "
                      "template number (last command wins), so an owner command that reached the dongle just before "
                      "the restore command is overwritten and the restore's own publish satisfies the verify. Sweep "
                      "(model latencies cmd 0.03 s, publish 0.12 s): via HA lost from RESTORING -0.14 s to +0.00 s (the "
                      "owner acts while OWED), dropped as the owner's at -0.15 s and earlier, kept from +0.02 s (with "
                      "stale RESTORED text); via the modelled dongle path lost -0.10..+0.03 s; the documented PARTIAL / "
                      "FAILED never arises from one owner edit in this model"),
        "severity": ("low: diagnostics / owner intent - a staging number (no inverter write, range-checked) silently goes "
                     "back to the owner's earlier pre-schedule value; HA then shows it, so it is visible before any "
                     "manual START (knock-on only for a later manual Dump started without a look at Stop SOC)"),
        "reachability": ("INFERRED, very low: an owner edit of the field being restored within about cmd + publish (0.15 "
                         "s in the model, not measured; ESPHome API batching could widen it) around SMR1's RESTORING, "
                         "about 5 s after a scheduled lease ends; the realistic path is the HA dashboard (via='ha'); the "
                         "firmware has no web_server, so via='dongle' needs another native-API client"),
        "repair": ("primary, documentation only: correct the limit text (doc 'Owner change during the restore', the doc "
                   "line 'the restore writes only a number that still holds the schedule's value' and CHANGELOG 'always "
                   "wins'): a change landing within the restore write's latency is overwritten and reported RESTORED "
                   "without a notification; re-check the value after a restore. Optional SMR1 track change (helper "
                   "state + notification only): a change seen while RESTORING to a value other than the field's saved "
                   "value marks the field and makes the result PARTIAL (notified) - best effort, it does not prevent "
                   "the loss and needs HA to receive the intermediate publish. A true fix needs a single writer or a "
                   "compare-and-set on the dongle (a firmware change, out of scope); 're-read the number after a "
                   "settle' cannot detect the loss (the number then reads the saved value)"),
        "anchors": [(SMR1_DOC, "- **Owner change during the restore.**"),
                    (SMR1, 'value: "RESTORING {{ owed_since }} - putting back the manual Free Power values"')]},
    "F-HF09-1": {
        "scenario": "HF-09", "classification": "FINDING-NEW", "invariant": "INV-HF-ARM-OFF",
        "grade": "VERIFIED", "confidence": "medium", "priority": "P3",
        "title": "when every write-enable turn-off of a run fails (service errors, or an API outage under either offline "
                 "policy) after an unanswered START press, the write enable stays ON after the run on the real firmware "
                 "(it disarms only at a press or a reboot), SMR1's restore stays blocked and the run's alert does not "
                 "name the armed switch; Free Power and Dump to Grid",
        "mechanism": ("after a START press that never reached the dongle (the call raised before delivery, or the API link "
                      "dropped inside its 0.117 s flight) FPS1 / DGS1 turn the write enable off twice: in the no-answer "
                      "branch ('# No answer to this press ...': one turn_off, a 10 s wait to see 'off', 35 s, then "
                      "'outcome unconfirmed, not retried' because the switch never read 'off') and in the closing step "
                      "'# The write enable always ends off ...'; each is ONE call with continue_on_error, and nothing "
                      "checks the switch after the closing one. If both fail (two switch.turn_off service errors about "
                      "45 s apart, or one API outage that covers both calls, about 62 s from the press), the real "
                      "firmware keeps its template switch ON: restore_mode ALWAYS_OFF and '# and auto-disarms as soon as "
                      "Start Free Power is pressed' are its only disarms (no timeout, no disconnect disarm; only a "
                      "reboot, e.g. ESPHome's 15-minute no-client reboot after a long outage, clears it). The run "
                      "records 'FAILED TO START - no answer ... outcome unconfirmed, not retried' with its alert (not "
                      "silent), nothing turns the switch off afterwards (the startup recovery runs only after a Home "
                      "Assistant restart), and SMR1's blocker reads '<function> write enable armed', so the owner's "
                      "manual values stay at the schedule's (OWED). An outage from just after staging that outlasts the "
                      "10-minute retry window ends the same way ('FAILED TO START - authorised window ends ...')"),
        "severity": ("low: the write enable writes nothing by itself and only permits a START; the end state is the one "
                     "of the fixed D4 defect ('a later stray START press starts an unplanned session without any arm "
                     "step', docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md: low probability, arm "
                     "protection bypassed) plus a blocked SMR1 restore (the owner's manual values not put back, no "
                     "write; shown in sensor.ecco_schedule_manual_restore, notified only as STALE after 24 h); the run's "
                     "FAILED alert is raised but names neither the armed switch nor the blocked restore"),
        "reachability": ("INFERRED, very low: (a) three consecutive ServiceErrors while Home Assistant still sees the "
                         "dongle connected (the press, then the turn-offs about 17 s and 62 s after it; an error pattern "
                         "not measured, in the interpreter's raise-before-delivery model); (b) one ESPHome API outage of "
                         "at least about 62 s that begins inside the 0.117 s between the START call and its delivery "
                         "(model press_s), or one that begins between staging and the press (about 1.1 s) and outlasts "
                         "the 10-minute retry window; offline_policy 'raise' (ServiceError) and 'silent' (dropped) give "
                         "the same end state; an outage longer than ESPHome's default 15-minute no-client reboot_timeout "
                         "(which the firmware's api: block says it relies on) reboots the dongle and clears the switch - "
                         "not modelled by the lab, so (b) is bounded to outages shorter than that. Partly documented: "
                         "docs/incidents/2026-10-11-scheduled-free-power-start.md "
                         "names 'a write enable left on across a Wi-Fi-only drop stays on until the next press or reboot "
                         "(it only permits a START)' for the restart recovery; the unqualified 'the write enable always "
                         "ends off' claims of both incident records and the blocked SMR1 restore are not documented"),
        "repair": ("FPS1 / DGS1 closing step only (Home Assistant side, the safe direction, no new write path): after the "
                   "closing turn_off, wait (bounded, about 10 s) to SEE the write enable 'off'; if it is not seen off, "
                   "add 'the write enable may still be ON - turn it off before anything else' to the run's alert (these "
                   "paths already alert) and optionally send one more bounded turn_off when the dongle is seen again "
                   "inside the run. Documentation alternative: qualify 'the write enable always ends off' (one attempt "
                   "per step; a Wi-Fi drop or repeated service errors can leave it on until the next press or reboot). "
                   "A firmware auto-disarm (timeout or API disconnect) needs an OTA and is out of this scope"),
        "anchors": [(FPS1, "      # The write enable always ends off (the safe state: it only permits a START)."),
                    (FPS1, "unconfirmed, not retried (last status: {{ status_now }})"),
                    (FW, "# and auto-disarms as soon as Start Free Power is pressed. Ending/restoring never"),
                    (SMR1, "('switch.ecco_clock_dongle_free_power_write_enable', 'Free Power write enable armed'),"),
                    (INC_FP, "across a Wi-Fi-only drop stays on until the next press or reboot (it only permits a "
                             "START)."),
                    (INC_DUMP, "- **The write enable always ends off**, also after a restart between an arm and its "
                               "press."),
                    (INC_DUMP, "a later stray START press starts an unplanned session without any arm step"),
                    (FW, "# relies on ESPHome's default reboot_timeout (15 min with no API client).")]},
}
# V0.1 (brief B6.3, precedent F-RT02-1 in test_lab_dst_rtc): F-HF05-1 left the finding ledger. Its behaviour (an owner
# change to a schedule-shaped value while the scheduled script runs is taken for the schedule's write by the SMR1 track's
# schedule-value rule '{% else %}{{ 1 <= n <= (states(...schedule_duration) ...) }}', so SMR1 restores the pre-schedule
# value and reports RESTORED) is exactly the limit docs/dev/schedule-manual-restore.md states ('That change is taken for
# the schedule's write. Its consequence is that the owner's pre-schedule value is restored.'); HF-05.2 keeps checking it
# with a plain check (no FINDING line, no finding pin). Doc nit: CHANGELOG.md 'the owner's own later change always wins'
# is unqualified against it.
RECLASSIFIED = {"F-HF05-1": "PASS (documented limit SMR1-OWNER-STAGING; HF-05.2): docs/dev/schedule-manual-restore.md "
                            "'Owner change during a scheduled start' documents this outcome (the pre-schedule value is "
                            "restored); doc nit: CHANGELOG.md 'the owner's own later change always wins' is unqualified "
                            "against it"}
SUPPORT = {"HF-05-UNS-1": "owner START press / write-enable command inside the schedule's projected START transaction",
           "HF-05-UNS-2": "owner number edit inside the firmware's projected Free Power restore transaction",
           "HF-03-UNS-1": ("dongle power cut inside the projected START transaction after the gate (data commit / marker "
                           "commit / write 256 / active commit): the coupled tier drops every publish of the cut entry "
                           "and disconnects Home Assistant at the gate instant (_lab_ha RealDongle._finish 'if rebooted: "
                           "self._self_reboot(); return' before the publishes; core NOT MODELLED 'A power cut between a "
                           "projected transaction's ops'), so Home Assistant never sees the gate's answer it would have "
                           "seen")}
RESULTS: dict = {sid: [] for sid in SCEN}
FINDING_SEEN: list[str] = []
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (LAB-SUMMARY: points = lines, ids = set)
HF03_TXN_POINTS: list[tuple[str, str]] = []   # every HF-03 in-transaction cut point of this run (quick + extended sweeps)
NC_RESULTS: list[dict] = []


# =============================================================================================================================
# helpers
# =============================================================================================================================
def safe(text) -> str:
    """ASCII-only text for the console (the package texts contain a bullet)."""
    return str(text).encode("ascii", "replace").decode("ascii")


def finding(fid: str, text: str) -> None:
    if fid not in FINDING_SEEN:
        FINDING_SEEN.append(fid)
    print(T.finding_line(fid, safe(text)))


def unsupported(uid: str, text: str) -> None:
    """One UNSUPPORTED line per unsupported point met (uid = the catalogue unsupported id; repeats are separate points)."""
    UNSUPPORTED_POINTS.append(uid)
    print(T.unsupported_line(uid, safe(text)))


def info(text: str) -> None:
    print(f"  info  {safe(text)}")


def result(sid: str, text: str) -> None:
    RESULTS[sid].append(text)


def world(bus=None, fwk=None, **kw) -> H.CoupledWorld:
    return H.CoupledWorld(U0, bus=IDLE if bus is None else bus, fw_world_kwargs={**WARM, **(fwk or {})}, **kw)


def arm(cw, dom: str, minutes: int, power_w: int, stop_soc=None, at=None) -> None:
    cw.arm_schedule(dom, START_LOCAL, minutes, power_w, stop_soc=stop_soc, at_utc=U0 + 60 if at is None else at)


def ev(cw, kind: str, **match) -> list:
    return [e for e in cw.log.events(kind=kind) if all(e["data"].get(k) == v for k, v in match.items())]


def start_presses(cw, dom: str, by=None) -> list:
    return [e for e in ev(cw, "dongle.cmd", svc="button.press", fid=H.START_BUTTON[dom]) if by is None
            or e["data"]["by"] == by]


def results_of(cw, dom: str) -> list:
    return [(e["t_utc"], e["data"]["s"]) for e in ev(cw, "ha.state", e=H.LAST_RESULT[dom])]


def fw_texts(cw, dom: str) -> list:
    return [(e["t_utc"], e["data"]["text"]) for e in ev(cw, "fw.status", dom=dom)]


def lease_starts(cw, dom: str) -> list:
    """Projected instants at which a firmware lease turned active (dongle.edge act False -> True). The flags a new boot
    reloads from NVS (an edge projected at or before that boot's fw.boot instant) are not a new lease."""
    boots = {e["data"]["boot"]: e["t_utc"] for e in ev(cw, "fw.boot")}
    out, act = [], False
    for e in ev(cw, "dongle.edge", dom=dom):
        d = e["data"]
        reload = d["boot"] in boots and d["at"] <= boots[d["boot"]] + 1e-3
        if d["act"] and not act and not reload:
            out.append(d["at"])
        act = d["act"]
    return out


def gate_passes(cw, dom: str, after: float) -> list:
    """Instants of the firmware's START gate passes (GATE_TEXT status) after `after`."""
    return [t for t, x in fw_texts(cw, dom) if t > after and x == GATE_TEXT]


def notes_created(cw, nid: str) -> list:
    return [e for e in ev(cw, "ha.call", svc="persistent_notification.create")
            if (e["data"].get("data") or {}).get("notification_id") == nid]


def hf_inv(cw, names=None, **params) -> list:
    return cw.invariants(names, **params)


def fw_inv(cw, names=None) -> list:
    return L.check_invariants(cw.log, names=names, world=cw.fw)


def invs(viol) -> list:
    return sorted(v["inv"] for v in viol)


def boot_mirror_judged(cw, dom: str) -> bool:
    """The firmware's INV-BOOT-MIRROR is in the default set fw_inv() runs and is NOT vacuous for this reboot: the new
    boot's settle record (fw.booted, boot 1) holds the domain's STORED marker RESTORE_REQUIRED, the state the checker
    judges (RAM snapshot_valid or a lockout required). Observer only."""
    booted = ev(cw, "fw.booted")
    b1 = [e for e in booted if e["boot"] == 1]
    return ("INV-BOOT-MIRROR" in L.INVARIANTS and len(b1) == 1
            and b1[0]["data"]["obl"]["nvs"].get(dom) == "RESTORE_REQUIRED")


def check_press_proof(events) -> list:
    """INV-HF-PRESS-PROOF (suite-local, module docstring): within one run of a scheduled start script, no schedule START
    press after an earlier press of that run whose firmware gate passed (the firmware's GATE_TEXT status after it)."""
    out = []
    st = {d: {"run": False, "pressed": False, "began": False} for d in H.DOMS}
    script_dom = {H.SCRIPT[d]: d for d in H.DOMS}
    start_dom = {H.START_BUTTON[d]: d for d in H.DOMS}
    for e in (events if isinstance(events, list) else list(events)):
        k, dt = e["kind"], e["data"]
        if k == "ha.state" and dt["e"] in script_dom:
            s = st[script_dom[dt["e"]]]
            if dt["s"] == "on":
                s.update(run=True, pressed=False, began=False)
            else:
                s["run"] = False
        elif k == "dongle.cmd" and dt["svc"] == "button.press" and dt["fid"] in start_dom and dt["by"] == "schedule":
            d = start_dom[dt["fid"]]
            if st[d]["began"]:
                out.append({"inv": "INV-HF-PRESS-PROOF", "seq": e["seq"], "tags": [],
                            "detail": f"{d} schedule START press at {e['t_utc']} after an earlier press of the same run "
                                      "whose firmware gate passed"})
            st[d]["pressed"] = True
        elif k == "fw.status" and dt["dom"] in st and dt["text"] == GATE_TEXT:
            s = st[dt["dom"]]
            if s["run"] and s["pressed"]:
                s["began"] = True
    return out


BOOT_END = {"fp": ("fp", "ACTIVE - reboot recovery pending"),
            "dump": ("dump_end", "ESP RESTARTED DURING LEASE - ended, not resumed")}


def check_hf_no_resume(events) -> list:
    """INV-HF-NO-RESUME (suite-local; the firmware's documented no-resume design carried to the coupled level): once the
    dongle's on_boot has ended a lease (FP S3 'ACTIVE - reboot recovery pending', Dump 'ESP RESTARTED DURING LEASE -
    ended, not resumed'), no schedule START press for that domain until the owner arms a schedule again."""
    out = []
    ended = {d: False for d in H.DOMS}
    start_dom = {H.START_BUTTON[d]: d for d in H.DOMS}
    for e in (events if isinstance(events, list) else list(events)):
        k, dt = e["kind"], e["data"]
        if k == "owner.arm":
            ended[dt["dom"]] = False
        elif k == "fw.status":
            for d, (sdom, text) in BOOT_END.items():
                if dt["dom"] == sdom and dt["text"] == text:
                    ended[d] = True
        elif k == "dongle.cmd" and dt["svc"] == "button.press" and dt["fid"] in start_dom and dt["by"] == "schedule":
            d = start_dom[dt["fid"]]
            if ended[d]:
                out.append({"inv": "INV-HF-NO-RESUME", "seq": e["seq"], "tags": [],
                            "detail": f"{d} schedule START press at {e['t_utc']} after the dongle's boot ended that lease"})
    return out


TERMINAL = ("STARTED", "FAILED", "CANCELLED", "BLOCKED", "MISSED")
NOTE_ID = {"fp": "ecco_free_power_schedule", "dump": "ecco_dump_to_grid_schedule"}


def check_never_silent(events) -> list:
    """INV-HF-NEVER-SILENT (suite-local, module docstring): an open scheduled run (a 'STARTING' result) is closed by a
    terminal result or by the domain's alert; a non-terminal result written while its script is off is a violation."""
    out = []
    res_dom = {H.LAST_RESULT[d]: d for d in H.DOMS}
    script_dom = {H.SCRIPT[d]: d for d in H.DOMS}
    open_ = {d: None for d in H.DOMS}
    running = {d: False for d in H.DOMS}
    for e in (events if isinstance(events, list) else list(events)):
        k, dt = e["kind"], e["data"]
        if k == "ha.state" and dt["e"] in script_dom:
            running[script_dom[dt["e"]]] = dt["s"] == "on"
        elif k == "ha.state" and dt["e"] in res_dom:
            d, txt = res_dom[dt["e"]], dt["s"]
            if txt.startswith("STARTING"):
                open_[d] = open_[d] or e
            elif txt.startswith(TERMINAL):
                open_[d] = None
            elif open_[d] is not None and not running[d]:
                out.append({"inv": "INV-HF-NEVER-SILENT", "seq": e["seq"], "tags": [],
                            "detail": f"{d} run open since {open_[d]['t_utc']} silently overwritten by {txt[:40]!r}"})
                open_[d] = None
        elif k == "ha.call" and dt["svc"] == "persistent_notification.create":
            for d in H.DOMS:
                if (dt.get("data") or {}).get("notification_id") == NOTE_ID[d]:
                    open_[d] = None
    return out


def sample_switch(cw, fid: str, t_from: float, t_to: float, step: float = 0.25) -> list:
    """Firmware truth of a dongle switch on the World clock (None while the dongle is unpowered). Observer only."""
    out = []

    def probe(t):
        def f():
            out.append((round(t, 3), None if cw.dongle.off else bool(cw.fw.sim.ent(fid).state)))
        return f
    for i in range(int(round((t_to - t_from) / step)) + 1):
        cw.w.at(t_from + i * step, probe(t_from + i * step))
    return out


def left_on(cw, samples, t_restart: float) -> dict:
    """The Free Power write enable left ON across a restart: from the last turn_on command that reached the firmware
    before t_restart to the first turn_off command after it (exact dongle.cmd instants); 'truth' = every firmware-truth
    sample strictly inside that interval reads ON (the switch really stayed on); 'by' = who turned it off."""
    on = [e for e in ev(cw, "dongle.cmd", svc="switch.turn_on", e=S.E_ARM) if e["t_utc"] <= t_restart]
    off = [e for e in ev(cw, "dongle.cmd", svc="switch.turn_off", e=S.E_ARM) if e["t_utc"] > t_restart]
    if not on or not off:
        return {"s": None, "truth": False, "by": None}
    a, b = on[-1]["t_utc"], off[0]["t_utc"]
    inside = [v for t, v in samples if a < t < b]
    return {"s": round(b - a, 3), "truth": bool(inside) and all(v is True for v in inside), "by": off[0]["data"]["by"]}


def mutate(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        raise H.LabHarnessError(f"mutation anchor for {what} found {n}x (exactly once required)")
    return text.replace(old, new)


def raises_unsupported(fn) -> tuple:
    """(LabUnsupported raised, message). Only LabUnsupported is caught (classified UNSUPPORTED, never a pass); any other
    exception propagates and fails the suite loudly."""
    try:
        fn()
    except H.LabUnsupported as exc:
        return True, str(exc)
    return False, "no LabUnsupported"


def negative_control(nc_id: str, family: str, mutation: str, target: str, run) -> None:
    """run() builds the mutant world(s) and returns its violations; killed = target among them. A mutant that crashes
    (harness or parse error) is MUTANT-INVALID: a negative-control FAILURE, never a kill."""
    try:
        viol = run()
        outcome = "killed" if target in invs(viol) else "survived"
        detail = f"violations {invs(viol)}"
    except Exception as exc:  # noqa: BLE001 - recorded as MUTANT-INVALID and FAILED below, never a pass
        outcome, detail = "invalid", f"{type(exc).__name__}: {exc}"
    NC_RESULTS.append({"id": nc_id, "family": family, "mutation": mutation, "target": target, "outcome": outcome,
                       "detail": detail})
    info(f"negative control {nc_id}: {outcome} ({detail[:160]})")
    check(f"negative control {nc_id} ({family}): {mutation} -> {target} violated, no harness error (mutant killed)",
          outcome == "killed", detail[:300])


# =============================================================================================================================
# [0] anchors and tables
# =============================================================================================================================
def section_anchors() -> None:
    print("[0] scenario table: every source anchor occurs exactly once; classifications / risk ids are valid")
    seen = set()
    for row in SCENARIOS + [dict(f, id=fid) for fid, f in FINDINGS.items()]:
        for path, text in row["anchors"]:
            if (path, text) in seen:
                continue
            seen.add((path, text))
            n, line = T.anchor_count(path, text)
            # V0.1 review (R1-B1-11): the check name is constant (no live line number: an edit above an anchor, e.g. a
            # new CHANGELOG entry, must not rename a check); the line is information only
            check(f"anchor {path.split('/')[-1]} occurs exactly once ({text[:48]!r})", n == 1, f"{n}x")
            if n == 1:
                info(f"anchor {path}:{line} ({text[:48]!r})")
    ok = []
    for row in SCENARIOS + list(FINDINGS.values()):
        kind, rid = T.parse_classification(row["classification"])
        ok.append(kind in T.CLASSIFICATIONS and (rid is None or rid in T.KNOWN_RISKS))
    check("every classification parses with the core vocabulary and every FINDING-KNOWN id is a KNOWN_RISKS id", all(ok))
    check("every scenario and finding grade / confidence / priority is in the core vocabulary",
          all(r["grade"] in T.GRADES and r["confidence"] in T.CONFIDENCES and r["priority"] in T.PRIORITIES
              for r in SCENARIOS + list(FINDINGS.values())))
    check("every scenario lists its corpus documents and findings consistently",
          all(FINDINGS[f]["scenario"] == s["id"] for s in SCENARIOS for f in s["findings"]))


def _he(seq, kind, data, t=0.0, src="lab") -> dict:
    return {"seq": seq, "t_utc": ST + t, "up_ms": None, "boot": None, "src": src, "kind": kind, "data": data}


def section_local_checkers() -> None:
    print("[1] suite-local checkers: hand-built violating logs are caught, clean twins are not")

    def press(seq, t, dom="fp", by="schedule"):
        return _he(seq, "dongle.cmd", {"svc": "button.press", "e": "button.x", "fid": H.START_BUTTON[dom],
                                       "kind": "button", "value": None, "by": by, "obl": {}, "mw": False}, t)

    def script(seq, t, s):
        return _he(seq, "ha.state", {"e": H.SCRIPT["fp"], "s": s}, t, "ha")

    def status(seq, t, dom, text):
        return _he(seq, "fw.status", {"dom": dom, "text": text}, t, "fw")
    bad = [script(0, 0, "on"), press(1, 1), status(2, 1.3, "fp", GATE_TEXT), press(3, 75), script(4, 80, "off")]
    refused = [script(0, 0, "on"), press(1, 1), status(2, 1.3, "fp", "REJECTED - Modbus bus busy with another "
                                                                     "transaction"), press(3, 8), script(4, 80, "off")]
    new_run = [script(0, 0, "on"), press(1, 1), status(2, 1.3, "fp", GATE_TEXT), script(3, 50, "off"),
               script(4, 60, "on"), press(5, 61)]
    check("INV-HF-PRESS-PROOF: a second schedule press after a passed gate in the same run is caught (exactly once); "
          "retries after gate refusals and the first press of a new run are not",
          [v["seq"] for v in check_press_proof(bad)] == [3] and not check_press_proof(refused)
          and not check_press_proof(new_run))
    end = status(1, 100, "dump_end", BOOT_END["dump"][1])
    arm_ev = _he(2, "owner.arm", {"dom": "dump", "start_local": "x", "window_end": ST + 900}, 150)
    check("INV-HF-NO-RESUME: a schedule Dump press after the boot ended its lease is caught; one after a new owner arm, "
          "and one with no boot end, are not", [v["seq"] for v in check_hf_no_resume([end, press(3, 120, "dump")])]
          == [3] and not check_hf_no_resume([end, arm_ev, press(3, 160, "dump")])
          and not check_hf_no_resume([press(3, 120, "dump")]) and not check_hf_no_resume([end, press(3, 120, "fp")]))

    def res(seq, t, text):
        return _he(seq, "ha.state", {"e": H.LAST_RESULT["fp"], "s": text}, t, "ha")
    note = _he(9, "ha.call", {"svc": "persistent_notification.create", "e": [], "by": "ha",
                              "data": {"notification_id": NOTE_ID["fp"]}}, 50, "ha")
    killed = [script(0, 0, "on"), res(1, 0, "STARTING - x"), script(2, 40, "off"), res(3, 90, "ARMED AFTER RESTART - y")]
    rearm = [script(0, 0, "on"), res(1, 0, "STARTING - x"), res(2, 30, "ARMED - y"), res(3, 31, "CANCELLED - z"),
             script(4, 32, "off")]
    alerted = killed[:3] + [note, res(3, 90, "ARMED AFTER RESTART - y")]
    check("INV-HF-NEVER-SILENT: an open STARTING run overwritten after its script stopped is caught; a re-arm while the "
          "script still runs, a terminal result and an alert are not",
          [v["seq"] for v in check_never_silent(killed)] == [3] and not check_never_silent(rearm)
          and not check_never_silent(alerted) and not check_never_silent(killed[:2] + [res(2, 9, "STARTED OK - a")]))


# =============================================================================================================================
# HF-02
# =============================================================================================================================
def first_arm_ons(bus, rtc=None, n=3) -> list:
    """Reference run: the HA-visible instants at which the schedule's Free Power write enable turned on (first n)."""
    cw = world(bus)
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 20, 3000)
        if rtc:
            cw.fw_action("rtc_lock_windows", at_utc=U0 + 200, windows=rtc)
        cw.run_until(ST + 60)
        return [e["t_utc"] for e in ev(cw, "ha.state", e=S.E_ARM, s="on") if e["t_utc"] > ST][:n]
    finally:
        cw.close()


def run_restart_starting(bus, t_restart, down=30.0, gap=10.0, rollback=None, rtc=None, texts=None, until=ST + 1440):
    cw = world(bus, package_texts=texts, reconnect_gap_s=gap)
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 20, 3000)
        if rtc:
            cw.fw_action("rtc_lock_windows", at_utc=U0 + 200, windows=rtc)
        smp = sample_switch(cw, ARM_FID["fp"], t_restart - 2, t_restart + down + 120)
        cw.restart_ha(t_restart, down, rollback_to_utc=rollback, reconnect_gap_s=gap)
        cw.run_until(until)
        return cw, smp
    except BaseException:
        cw.close()
        raise


def section_hf02_starting() -> None:
    print("[HF-02.1] graceful Home Assistant restart while the scheduled Free Power is STARTING (bus-busy retry loop), "
          "at an instant where the schedule has the write enable ON")
    ons = first_arm_ons(BUSY_START)
    t_r = ons[2] + 0.05
    down, gap = 30.0, 10.0
    bound = down + max(20.0, gap) + 2.0
    cw, smp = run_restart_starting(BUSY_START, t_r, down, gap)
    try:
        lo = left_on(cw, smp, t_r)
        span = lo["s"]
        info(f"write enable ON (HA view) at +{ons[2] - ST:.2f} s; restart at +{t_r - ST:.2f} s, down {down} s, reconnect "
             f"gap {gap} s; the write enable stayed ON {span} s until the recovery's turn_off (by {lo['by']}); documented "
             f"bound: down + max(20 s recovery delay, gap) + 2 s latency = {bound} s")
        check("documented: the write enable left ON by a restart between arm and press stays ON across the outage "
              "(firmware truth) and the startup recovery turns it off within down + 20 s (the 'Not covered' residual "
              "of docs/incidents/2026-10-11-scheduled-free-power-start.md)",
              span is not None and down < span <= bound and lo["truth"] and lo["by"] == "ha", str(lo))
        check("INV-HF-ARM-OFF with the documented bound as grace holds (no write enable left on longer)",
              not hf_inv(cw, ["INV-HF-ARM-OFF"], grace_s=bound), str(hf_inv(cw, ["INV-HF-ARM-OFF"], grace_s=bound)))
        missed = notes_created(cw, "ecco_free_power_schedule")
        res = results_of(cw, "fp")
        last = cw.last_result("fp")
        info(f"FPS1 after the restart: {last!r}; 'missed' alerts created {len(missed)}; notifications at the end "
             f"{sorted(cw.notifications())}")
        check("documented recovery: the killed run is recovered for the rest of the window (one 'start was missed' "
              "alert, a fresh run, STARTED OK ending by 12:20, the alert dismissed by the success)",
              len(missed) == 1 and last.startswith("STARTED OK - 3000W for 1") and "ends by 12:20" in last
              and cw.notifications() == {} and any(t > t_r + down and s.startswith("STARTING") for t, s in res), last)
        hf, fwv = hf_inv(cw, params={"INV-HF-ARM-OFF": {"grace_s": bound}}), fw_inv(cw)
        check("no coupled invariant (INV-HF-*, the write-enable grace at the documented bound) and no firmware invariant "
              "violated; one lease; the SMR1 obligation survived the graceful restart (RESTORED with the owner's 40 min)",
              not hf and not fwv
              and len(lease_starts(cw, "fp")) == 1 and cw.smr1_state("fp").startswith("RESTORED")
              and cw.ha_state(S.E_DUR) == "40.0", f"{invs(hf)} {invs(fwv)} {cw.smr1_state('fp')[:60]}")
        check("INV-HF-PRESS-PROOF holds (every retry followed a gate refusal, never a passed gate) and INV-HF-NEVER-SILENT "
              "holds (the killed run was closed by the recovery's 'start was missed' alert)",
              not check_press_proof(cw.log) and not check_never_silent(cw.log))
        result("HF-02", f"STARTING restart (bus): write enable ON {span} s <= bound {bound} s; recovered, one lease")
    finally:
        cw.close()
    print("[HF-02.1r] the same restart while an RTC lock window keeps the gate refusing (REJECTED - RTC correction)")
    rtc = [(ST - 1, ST + 120)]
    ons = first_arm_ons(IDLE, rtc=rtc, n=2)
    cw, smp = run_restart_starting(IDLE, ons[1] + 0.05, down, gap, rtc=rtc, until=ST + 300)
    try:
        res = [s for _t, s in results_of(cw, "fp")]
        check("RTC variant: the gate refused with the RTC text before the restart, the recovery then started the rest of "
              "the window once the lock window ended; one lease, write enable ON within the documented bound",
              any("REJECTED - RTC correction currently active" in s for s in res)
              and cw.last_result("fp").startswith("STARTED OK") and len(lease_starts(cw, "fp")) == 1
              and (left_on(cw, smp, ons[1] + 0.05)["s"] or 1e9) <= bound
              and not hf_inv(cw, ["INV-HF-ARM-OFF"], grace_s=bound), safe(res[-1]))
    finally:
        cw.close()
    print("[HF-02.7] crash rollback to BEFORE the arm while the write enable is ON (armed rolls back to off)")
    ons = first_arm_ons(BUSY_START)
    cw, smp = run_restart_starting(BUSY_START, ons[2] + 0.05, down, gap, rollback=U0 + 50, until=ST + 200)
    try:
        lo = left_on(cw, smp, ons[2] + 0.05)
        check("the recovery's write-enable guard turns the left-over write enable off although nothing is armed any "
              "more (no script runs): firmware truth ON until the recovery's turn_off, OFF at the end, within the "
              "documented bound, no later press", smp[-1][1] is False and lo["truth"] and lo["by"] == "ha"
              and down < lo["s"] <= bound and not hf_inv(cw, ["INV-HF-ARM-OFF"], grace_s=bound)
              and all(e["t_utc"] < ons[2] for e in start_presses(cw, "fp")), str(lo))
        info(f"documented SMR1-UNCLEAN-SHUTDOWN consequence: SMR1 state {cw.smr1_state('fp')!r}, the numbers stay at the "
             f"schedule's ({cw.ha_state(S.E_PWR)} W / {cw.ha_state(S.E_DUR)} min)")
    finally:
        cw.close()


def run_active_restart(gap=10.0, rollback=ST - 120, until=ST + 1320, texts=None, dom="fp"):
    cw = world(reconnect_gap_s=gap, package_texts=texts)
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, dom, 20, 3000)
        cw.restart_ha(ST + 300, 60, rollback_to_utc=rollback, reconnect_gap_s=gap)
        cw.run_until(until)
        return cw
    except BaseException:
        cw.close()
        raise


def section_hf02_active() -> None:
    print("[HF-02.2] graceful Home Assistant restart while the scheduled Free Power is ACTIVE")
    cw = run_active_restart(rollback=None)
    try:
        last = cw.last_result("fp")
        check("graceful: 'armed' stays off (disarmed by the fire automation), the recovery does nothing, one START "
              "press, the lease ends at its own epoch (RESTORED OK), SMR1 RESTORED the owner's 40 min",
              last.startswith("STARTED OK - 3000W for 20 min (attempt 1") and len(start_presses(cw, "fp")) == 1
              and cw.fw_status("fp") == "RESTORED OK - original inverter settings verified"
              and cw.smr1_state("fp").startswith("RESTORED") and cw.ha_state(S.E_DUR) == "40.0"
              and not hf_inv(cw) and not fw_inv(cw), safe(last))
        result("HF-02", "ACTIVE graceful restart: no recovery action, lease ends at its epoch")
    finally:
        cw.close()
    print("[HF-02.3] crash during ACTIVE with the helpers rolled back (armed ON again); ESPHome reconnect gap 10 / 25 / "
          "230 s (230 s > the recovery's 20 s + 180 s bounded wait)")
    expect = {10.0: "STARTED OK - running (Home Assistant restarted during the session)",
              25.0: "STARTED OK - running (Home Assistant restarted during the session)",
              230.0: "STARTED OK - Free Power is active; this run could not confirm the start as its own"}
    for gap, text in expect.items():
        cw = run_active_restart(gap=gap)
        try:
            last = cw.last_result("fp")
            info(f"gap {gap:.0f} s: FPS1 {last[:90]!r}; SMR1 {cw.smr1_state('fp')[:40]!r}; numbers {cw.ha_state(S.E_PWR)} W"
                 f" / {cw.ha_state(S.E_DUR)} min")
            check(f"reconnect gap {gap:.0f} s: the firmware lease is authoritative - no second START press, one lease, "
                  f"'armed' off again, the result {text[:40]!r}...", last.startswith(text)
                  and len(start_presses(cw, "fp")) == 1 and len(lease_starts(cw, "fp")) == 1
                  and cw.ha_state(H.ARMED["fp"]) == "off" and not check_press_proof(cw.log)
                  and not hf_inv(cw, ["INV-HF-ONE-LEASE", "INV-HF-OWNER-INTENT", "INV-HF-NO-FALSE-SUCCESS"]), safe(last))
            check(f"reconnect gap {gap:.0f} s: documented SMR1-UNCLEAN-SHUTDOWN consequence exactly - the obligation is "
                  "lost (no RESTORED, no notification) and the numbers stay at the schedule's 3000 W / 20 min",
                  not cw.smr1_state("fp").startswith("RESTORED") and (cw.ha_state(S.E_PWR), cw.ha_state(S.E_DUR))
                  == ("3000.0", "20.0") and cw.notifications() == {}, cw.smr1_state("fp"))
        finally:
            cw.close()
    result("HF-02", "crash during ACTIVE, gaps 10/25/230 s: never a second START; SMR1 obligation lost as documented")


def run_end_then_restart(dom: str, rollback, texts=None, gap=10.0, until=None, t_end=None, t_crash=None):
    cw = world(package_texts=texts, reconnect_gap_s=gap)
    try:
        if dom == "fp":
            cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
            arm(cw, "fp", 20, 3000)
            t_end, t_crash = t_end or ST + 300, t_crash or ST + 360
        else:
            arm(cw, "dump", 30, 1000, stop_soc=20)
            t_end, t_crash = t_end or ST + 120, t_crash or ST + 240
        cw.owner_press(END_HA[dom], at_utc=t_end)
        cw.restart_ha(t_crash, 60, rollback_to_utc=rollback, reconnect_gap_s=gap)
        cw.run_until(until or (ST + 1320 if dom == "fp" else ST + 400))
        return cw, t_end
    except BaseException:
        cw.close()
        raise


def section_hf02_end_restart() -> None:
    print("[HF-02.4] the owner presses End & Restore, then Home Assistant crashes inside the restore-state window "
          "(helpers rolled back to 11:58: armed ON again)")
    for dom, label in (("fp", "Free Power"), ("dump", "Dump to Grid")):
        cw, t_end = run_end_then_restart(dom, rollback=ST - 120)
        try:
            v = hf_inv(cw, ["INV-HF-OWNER-INTENT"])
            starts = lease_starts(cw, dom)
            after = [e for e in start_presses(cw, dom, "schedule") if e["t_utc"] > t_end]
            last = cw.last_result(dom)
            missed = notes_created(cw, f"ecco_{'free_power' if dom == 'fp' else 'dump_to_grid'}_schedule")
            nid = NOTE_ID[dom]
            finding("F-HF02-1", f"{label}: owner End at +{t_end - ST:.0f} s, crash rollback -> a second lease from "
                                f"+{(starts[-1] - ST) if starts else -1:.0f} s ({last[:60]})")
            info(f"{label}: 'missed' alert created {len(missed)}x and dismissed by the success (notifications at the end "
                 f"{sorted(cw.notifications())}); firmware {cw.fw_status(dom)[:50]!r}")
            check(f"finding-reproduces:F-HF02-1 ({label}): exactly one INV-HF-OWNER-INTENT violation; one schedule "
                  "START press after the owner's End; two firmware leases; the second one fully gated (STARTED OK); "
                  "its 'start was missed' alert created once and dismissed by the run's own success",
                  invs(v) == ["INV-HF-OWNER-INTENT"] and len(after) == 1 and len(starts) == 2
                  and last.startswith("STARTED OK - ") and "(attempt 1;" in last and len(missed) == 1
                  and nid not in cw.notifications(), f"{v} {last} {sorted(cw.notifications())}")
            check(f"{label}: the firmware invariants hold through it (the second session is a new, gated START)",
                  not fw_inv(cw), str(invs(fw_inv(cw))))
        finally:
            cw.close()
    print("[HF-02.4s] the same root cause without an owner End: (a) a scheduled Dump the firmware ended itself "
          "(static telemetry: CONTROLLER NO RESPONSE about 7.5 min in), crash at +500 s; (b) a 10-min Free Power that "
          "ended naturally at its epoch, crash at +640 s (helpers rolled back to 11:58 in both)")
    cw = world()
    try:
        arm(cw, "dump", 30, 1000, stop_soc=20)
        cw.restart_ha(ST + 500, 60, rollback_to_utc=ST - 120)
        cw.run_until(ST + 700)
        starts, last = lease_starts(cw, "dump"), cw.last_result("dump")
        fw_end = [x for t, x in fw_texts(cw, "dump_end") if ST < t < ST + 500]
        missed = notes_created(cw, NOTE_ID["dump"])
        finding("F-HF02-1", f"scope (a): firmware end {safe(fw_end[:1])[:46]}, crash rollback -> a new Dump lease from "
                            f"+{(starts[-1] - ST) if starts else -1:.0f} s")
        check("finding-reproduces:F-HF02-1 (scope a, firmware early end): the firmware ended the lease itself before the "
              "crash; the recovery starts a second, gated lease (STARTED OK) for the rest of the window and its alert is "
              "dismissed by that success; no coupled or firmware invariant flags it (no owner End: INV-HF-OWNER-INTENT "
              "does not apply)", bool(fw_end) and fw_end[0].startswith("CONTROLLER NO RESPONSE") and len(starts) == 2
              and starts[1] > ST + 500 and last.startswith("STARTED OK - 1000W for 2") and len(missed) == 1
              and cw.notifications() == {} and not hf_inv(cw) and not fw_inv(cw), f"{starts} {safe(last)} {fw_end[:1]}")
    finally:
        cw.close()
    cw = world()
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.restart_ha(ST + 640, 30, rollback_to_utc=ST - 120)
        cw.run_until(ST + 900)
        res = [s for t, s in results_of(cw, "fp") if t > ST + 640]
        msgs = [str((e["data"].get("data") or {}).get("message")) for e in notes_created(cw, NOTE_ID["fp"])]
        finding("F-HF02-1", f"scope (b): a completed run, crash rollback -> {safe(res[-1:])[:60]} with a 'Nothing was "
                            "started' alert")
        check("finding-reproduces:F-HF02-1 (scope b, natural end): the run had STARTED OK and ended at its epoch; after "
              "the crash rollback the recovery records 'MISSED - scheduled Free Power window already expired' and alerts "
              "'Nothing was started' (status FAILED) for a run that completed; one lease, no second START",
              res[-1:] == ["MISSED - scheduled Free Power window already expired"] and len(lease_starts(cw, "fp")) == 1
              and len(msgs) == 1 and "Nothing was started." in msgs[0] and cw.schedule_status("fp") == "FAILED"
              and len(start_presses(cw, "fp")) == 1, f"{res[-1:]} {msgs}")
    finally:
        cw.close()
    result("HF-02", "F-HF02-1 reproduced: second session after the owner's End (Free Power, Dump to Grid), second lease "
                    "after a firmware early end, false MISSED after a natural end")
    print("[HF-02.5] End & Restore followed by a GRACEFUL restart (restore-state saved at the clean stop): at +300 / "
          "+360 s, and early (End +120 s, restart +150 s, before the fire automation's 3-min watchdog)")
    for t_end, t_restart in ((ST + 300, ST + 360), (ST + 120, ST + 150)):
        cw, _t = run_end_then_restart("fp", rollback=None, until=ST + 600, t_end=t_end, t_crash=t_restart)
        try:
            check(f"graceful (End +{t_end - ST:.0f} s, restart +{t_restart - ST:.0f} s): 'armed' stays off (the fire "
                  "automation disarmed it after the start), the recovery does nothing - one schedule START press, one "
                  "lease, INV-HF-OWNER-INTENT holds (the guard the crash rollback defeats)",
                  len(start_presses(cw, "fp")) == 1 and len(lease_starts(cw, "fp")) == 1
                  and not hf_inv(cw, ["INV-HF-OWNER-INTENT"]) and cw.ha_state(H.ARMED["fp"]) == "off")
        finally:
            cw.close()
    print("[HF-02.6] crash while STARTING (helpers rolled back to 11:58): the recovery re-stages a clamped duration")
    t_crash = ST + 30
    cw, _smp = run_restart_starting(BUSY_START, t_crash, 30.0, 10.0, rollback=ST - 120)
    try:
        v = hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])
        st = cw.smr1_state("fp")
        staged = sorted({e["data"]["value"] for e in ev(cw, "dongle.cmd", svc="number.set_value", e=S.E_DUR, by="schedule")
                         if e["t_utc"] < t_crash})
        num = float(cw.ha_state(S.E_DUR))
        after = [e["data"]["value"] for e in ev(cw, "dongle.cmd", svc="number.set_value", e=S.E_DUR, by="schedule")
                 if e["t_utc"] > t_crash]
        info(f"durations the schedule staged before the crash {staged}, after it {after}; SMR1 saved the OLD value of "
             f"the first tracked post-crash step as the owner's ({num:g} min)")
        finding("F-HF02-2",f"SMR1 {st[:70]!r} while the owner's 8000 W / 40 min are lost (numbers read "
                            f"{cw.ha_state(S.E_PWR)} W / {num:g} min)")
        check("finding-reproduces:F-HF02-2: SMR1 says RESTORED with no notification while the numbers hold schedule "
              "values (power 3000 W; the 'restored' duration is one the schedule staged before the crash), exactly one "
              "INV-HF-NO-FALSE-SUCCESS violation", st.startswith("RESTORED ") and
              "restored: duration" in st and num in staged and num != 40.0 and cw.ha_state(S.E_PWR) == "3000.0"
              and invs(v) == ["INV-HF-NO-FALSE-SUCCESS"] and cw.notifications() == {}, f"{st} {staged} {v}")
        result("HF-02", "F-HF02-2 reproduced (crash in STARTING -> SMR1 false RESTORED)")
    finally:
        cw.close()
    print("[HF-02.8] the owner moves the start helper to tomorrow (without disarming) while the run retries; with and "
          "without a graceful Home Assistant restart 20 s later (Free Power and Dump to Grid)")
    for dom, label in (("fp", "Free Power"), ("dump", "Dump to Grid")):
        out = {}
        for restart in (False, True):
            cw = world(BUSY_START)
            try:
                if dom == "fp":
                    arm(cw, "fp", 20, 3000)
                else:
                    arm(cw, "dump", 30, 1000, stop_soc=20)
                cw.owner_set(H.START_HELPER[dom], "2026-10-22 12:00:00", at_utc=ST + 20)
                if restart:
                    cw.restart_ha(ST + 40, 30)
                cw.run_until(ST + 600)
                out[restart] = {"last": cw.last_result(dom), "status": cw.schedule_status(dom),
                                "leases": len(lease_starts(cw, dom)), "notes": sorted(cw.notifications()),
                                "ns": invs(check_never_silent(cw.log)), "hf": invs(hf_inv(cw))}
            finally:
                cw.close()
        info(f"{label}: no restart: {out[False]['last'][:60]!r} ({out[False]['status']}); restart: "
             f"{out[True]['last'][:60]!r} ({out[True]['status']})")
        check(f"{label}, no restart: the start-helper edit is not a cancel - today's run continues and starts (STARTED "
              "OK, one lease); INV-HF-NEVER-SILENT holds", out[False]["last"].startswith("STARTED OK")
              and out[False]["leases"] == 1 and not out[False]["ns"] and not out[False]["hf"], str(out[False]))
        finding("F-HF02-3", f"{label} restart: today's run abandoned silently ({out[True]['last'][:58]}), no lease, no "
                            "alert")
        check(f"finding-reproduces:F-HF02-3 ({label}): with the restart the same run is abandoned - 'ARMED AFTER "
              "RESTART', no lease, no notification, exactly one INV-HF-NEVER-SILENT violation", out[True]["last"].startswith(
                  "ARMED AFTER RESTART - waiting for 2026-10-22 12:00:00") and out[True]["leases"] == 0
              and out[True]["notes"] == [] and out[True]["ns"] == ["INV-HF-NEVER-SILENT"], str(out[True]))
    result("HF-02", "F-HF02-3 reproduced for Free Power and Dump to Grid (start helper moved + restart -> run abandoned "
                    "silently)")


# =============================================================================================================================
# HF-03
# =============================================================================================================================
# HF-03.1 cut specs for the core's arm_power_cut (fw_action). EARLY = START's FIRST Modbus read (Free Power 230 x 3, Dump
# 244 x 1): no poll read falls between the arm instant (+0.5 s) and the gate (about +1.27 s), the cut fires only inside a
# firmware action, and nothing has been written or committed yet. PROXY (labelled; see F-HF03-1): the coupled tier drops
# every publish of a cut entry and disconnects Home Assistant at the gate instant (_lab_ha RealDongle._finish 'if
# rebooted: self._self_reboot(); return' before its publishes), which matches a reset after the gate pass and BEFORE the
# gate's publishes reach Home Assistant (about publish_s); the real cut at the end of the first read (+op_s) would come
# after them. IN_TXN = cuts later inside the projected START transaction: Home Assistant would already have seen the
# gate's answer, the coupled tier hides it -> UNSUPPORTED (HF-03-UNS-1; core NOT MODELLED 'A power cut between a
# projected transaction's ops').
EARLY = {"fp": {"kind": "fw.read", "addr": 230}, "dump": {"kind": "fw.read", "addr": 244}}
IN_TXN = {"fp": {"A-data": {"kind": "fw.commit", "key": "fp.data", "nth": 1},
                 "B-marker": {"kind": "fw.commit", "key": "fp.valid", "state": 1},
                 "C-write256": {"kind": "fw.write", "addr": 256},
                 "D-active": {"kind": "fw.commit", "key": "fp.data", "nth": 2}},
          "dump": {"C-write256": {"kind": "fw.write", "addr": 256}}}
STATUS_HA = {"fp": "sensor.ecco_clock_dongle_free_power_status", "dump": "sensor.ecco_clock_dongle_dump_to_grid_status"}
NEVER = "STARTING - attempt 1 never reached the dongle (no start counted)"
NO_ANSWER = "FAILED TO START - no answer from the dongle to attempt 1; outcome unconfirmed, not retried"


def cut_spec(dom: str, cut: str) -> dict:
    return EARLY[dom] if cut == "early" else IN_TXN[dom][cut]


def run_cut(dom: str, spec: dict, down: float, bus=None, prior_attempt=False, texts=None, until=ST + 150):
    cw = world(bus, package_texts=texts)
    try:
        if prior_attempt:      # an owner manual 1-min Free Power earlier in the same boot: the gate-pass counter reads 1
            cw.owner_set(S.E_DUR, 1, at_utc=U0 + 150)
            cw.owner_set(S.E_ARM, True, at_utc=U0 + 151)
            cw.owner_press(S.E_PRESS, at_utc=U0 + 153)
            cw.owner_set(S.E_DUR, 40, at_utc=U0 + 400)
            arm(cw, "fp", 20, 3000, at=U0 + 420)
        elif dom == "fp":
            arm(cw, "fp", 20, 3000)
        else:
            arm(cw, "dump", 30, 1000, stop_soc=20)
        cw.fw_action("arm_power_cut", at_utc=ST + 0.5, down_s=down, **spec)
        cw.run_until(until)
        return cw
    except BaseException:
        cw.close()
        raise


def cut_basis(cw, dom: str) -> dict:
    """Where the cut fell inside the START entry (its instant projected the way the core projects a transaction: ops x
    op_s + commits x commit_s after the gate) and whether Home Assistant saw the gate's answer (write enable 'off' or a
    STARTING status) before the disconnect."""
    if STATUS_HA[dom] not in EMAP:
        raise H.LabHarnessError(f"status entity {STATUS_HA[dom]} not in the dongle entity map")
    start = next(e for e in ev(cw, "fw.start", dom=dom) if e["boot"] == 0 and e["t_utc"] >= ST)
    fired = cw.log.events(kind="cut.fired")
    if len(fired) != 1:
        raise H.LabHarnessError(f"expected one fired cut, got {len(fired)}")
    span = [e for e in cw.log.events() if start["seq"] < e["seq"] <= fired[0]["seq"]]
    ops = sum(1 for e in span if e["kind"] in ("fw.read", "fw.write"))
    commits = sum(1 for e in span if e["kind"] == "fw.commit")
    lat = cw.dongle.lat
    t_off = ev(cw, "dongle.self_restart")[0]["t_utc"]
    saw = [e for e in cw.log.events(kind="ha.state") if start["t_utc"] <= e["t_utc"] <= t_off + lat.publish_s
           and ((e["data"]["e"] == H.ARM[dom] and e["data"]["s"] == "off")
                or (e["data"]["e"] == STATUS_HA[dom] and e["data"]["s"].startswith("STARTING")))]
    return {"el_cut": round(ops * lat.op_s + commits * lat.commit_s, 3), "ops": ops, "commits": commits,
            "saw_answer": bool(saw), "publish_s": lat.publish_s}


def cut_outcome(cw, dom: str) -> dict:
    res = results_of(cw, dom)
    texts = [s for _t, s in res]
    boot = ev(cw, "fw.boot", boot=1)
    on_utc = boot[0]["t_utc"] - boot[0]["up_ms"] / 1000 if boot else None
    dec = next((t for t, s in res if s.startswith(NEVER) or s.startswith("FAILED TO START - no answer")), None)
    counter = S.E_ATTEMPTS if dom == "fp" else D.D_ATTEMPTS
    sample = next((e["t_utc"] for e in ev(cw, "ha.state", e=counter)
                   if on_utc is not None and e["t_utc"] > on_utc and e["data"]["s"] not in ("unknown", "unavailable")),
                  None)
    branch = ("retry" if any(s.startswith(NEVER) for s in texts) else
              "unconfirmed" if any(s.startswith("FAILED TO START - no answer") for s in texts) else
              "began" if any("start transaction began" in s or s.startswith("STARTED OK") for s in texts) else "other")
    return {"branch": branch, "presses": len(start_presses(cw, dom, "schedule")), "boot": cw.fw.boot_no,
            "u_dec": None if dec is None or on_utc is None else round(dec - on_utc, 2),
            "u_sample": None if sample is None or on_utc is None else round(sample - on_utc, 2),
            "pp": check_press_proof(cw.log), "fw": fw_inv(cw), "last": cw.last_result(dom),
            "clean_before_retry": _clean_cut(cw, dom), **cut_basis(cw, dom)}


def _clean_cut(cw, dom: str) -> bool:
    """The cut START wrote no register and committed nothing in its boot, and the new boot reports 'Inactive'."""
    pr = start_presses(cw, dom, "schedule")
    boot = ev(cw, "fw.boot", boot=1)
    if not pr or not boot:
        return False
    wrote = [e for e in ev(cw, "fw.write") if e["boot"] == 0 and e["t_utc"] >= pr[0]["t_utc"] and e["data"]["dom"] == dom]
    commits = [e for e in cw.log.events(kind="fw.commit") if e["boot"] == 0 and e["t_utc"] >= pr[0]["t_utc"]]
    first = next((x for t, x in fw_texts(cw, dom) if t >= boot[0]["t_utc"]), None)
    return not wrote and not commits and first == "Inactive"


def section_hf03_cut(points, label: str = "") -> None:
    print("[HF-03.1] a dongle reset right after the scheduled START's gate pass, before the gate's publishes reach Home "
          "Assistant (PROXY: core arm_power_cut at START's first Modbus read), power back after down_s: swept against the "
          "30 s attempt-counter sample grid; later in-transaction cuts are classified UNSUPPORTED on their evidence")
    rows, txn = [], []
    for dom, cut, down in points:
        cw = run_cut(dom, cut_spec(dom, cut), down)
        try:
            o = cut_outcome(cw, dom)
        finally:
            cw.close()
        (rows if cut == "early" else txn).append((dom, cut, down, o))
        info(f"{dom} cut {cut} (+{o['el_cut']} s after the gate) down {down:>4} s -> branch {o['branch']:<11} presses "
             f"{o['presses']}; uptime at the HA decision {o['u_dec']} s, first counter sample at uptime {o['u_sample']} "
             f"s; {o['last'][:52]!r}")
    for dom, cut, down, o in rows:
        tag = f"{dom} early reset down {down} s"
        if o["branch"] == "retry":
            finding("F-HF03-1", f"{tag}: 'never reached the dongle' -> second START press (the cut START wrote nothing)")
            check(f"finding-reproduces:F-HF03-1 ({tag}): the first START passed its gate and was cut before any write or "
                  "commit (the new boot reports 'Inactive'), Home Assistant never saw its answer, then exactly one "
                  "INV-HF-PRESS-PROOF violation (the second press, an ordinary gated START: STARTED OK); firmware "
                  "invariants hold", o["boot"] == 1 and o["presses"] == 2 and invs(o["pp"]) == ["INV-HF-PRESS-PROOF"]
                  and o["clean_before_retry"] and not o["saw_answer"] and not o["fw"]
                  and o["last"].startswith("STARTED OK"),
                  f"{o['presses']} {invs(o['pp'])} {invs(o['fw'])} {o['clean_before_retry']} {o['saw_answer']}")
        else:
            check(f"{tag}: branch {o['branch']} - no second START press (INV-HF-PRESS-PROOF holds), firmware invariants "
                  "hold", o["presses"] == 1 and not o["pp"] and not o["fw"] and o["branch"] in ("began", "unconfirmed"),
                  f"{o['branch']} {o['presses']} {invs(o['fw'])}")
    retry = [r for r in rows if r[3]["branch"] == "retry"]
    if retry:
        lo = min(r[3]["u_dec"] for r in retry)
        info(f"F-HF03-1 phase margin: in every retry case the HA decision came at new-boot uptime >= {lo} s; the safe "
             f"branch ('unknown' -> -1) would need the first counter sample later than that (core MODEL: one 30 s period "
             f"after power-on, INFERRED)")
    for dom, cut, down, o in txn:
        unsupported("HF-03-UNS-1", f"{dom} cut {cut} at +{o['el_cut']} s after the gate (Home Assistant would have seen "
                                   f"the gate's answer at +{o['publish_s']} s): harness outcome {o['branch']} not "
                                   "classified")
    if txn:
        check("in-transaction cuts are classified UNSUPPORTED on their evidence, never as findings or passes: each lies "
              "after the gate's publishes would have reached Home Assistant (projected cut instant > publish_s) and Home "
              "Assistant saw none of them (the coupled tier drops a cut entry's publishes); a core that projects them "
              "makes this check fail and forces re-classification",
              all(o["el_cut"] > o["publish_s"] and not o["saw_answer"] and o["ops"] >= 3 for _d, _c, _w, o in txn),
              str([(c, o["el_cut"], o["saw_answer"]) for _d, c, _w, o in txn]))
    HF03_TXN_POINTS.extend((dom, cut) for dom, cut, _w, _o in txn)
    if len(HF03_TXN_POINTS) == len(txn):        # the run's first sweep (quick mode's only one)
        uns = f"{len(txn)} in-transaction cut points UNSUPPORTED (HF-03-UNS-1)"
    else:                                       # a later sweep (extended mode) adds its points to the earlier ones
        uns = (f"{len(txn)} more in-transaction cut points UNSUPPORTED (HF-03-UNS-1): {len(HF03_TXN_POINTS)} in this run, "
               "one UNSUPPORTED line each")
    result("HF-03", f"{label}early reset after the gate pass: {len(retry)}/{len(rows)} swept points retry (F-HF03-1, "
                    f"INFERRED proxy); {uns}")


def section_hf03_guards() -> None:
    print("[HF-03.2] the no-answer guard where it holds: a gate pass earlier in the same boot (attempts_before 1.0), the "
          "same early reset")
    cw = run_cut("fp", cut_spec("fp", "early"), 5.0, prior_attempt=True, until=ST + 200)
    try:
        o = cut_outcome(cw, "fp")
        check("attempts_before 1.0: the reset counter reads 0 != 1 -> 'outcome unconfirmed, not retried' with an alert; "
              "one press; INV-HF-PRESS-PROOF holds", o["branch"] == "unconfirmed" and o["presses"] == 1 and not o["pp"]
              and o["last"].startswith(NO_ANSWER) and "ecco_free_power_schedule" in cw.notifications(), safe(o["last"]))
    finally:
        cw.close()
    result("HF-03", "no-answer guard holds with attempts_before > 0 (early reset)")


def run_reboot_active(dom: str, fwd=None, until=ST + 400):
    cw = world(fwk={"fw": fwd} if fwd is not None else None)
    try:
        if dom == "fp":
            cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
            arm(cw, "fp", 20, 3000)
        else:
            arm(cw, "dump", 30, 1000, stop_soc=20)
        cw.reboot_dongle(ST + 180, down_s=5.0)
        cw.run_until(until)
        return cw
    except BaseException:
        cw.close()
        raise


def section_hf03_active() -> None:
    print("[HF-03.3] dongle reboot (power cut 5 s) during the ACTIVE scheduled lease, no Home Assistant restart")
    for dom, label, mark in (("fp", "Free Power", "ACTIVE - reboot recovery pending"),
                             ("dump", "Dump to Grid", "ESP RESTARTED DURING LEASE - ended, not resumed")):
        cw = run_reboot_active(dom)
        try:
            texts = [x for t, x in fw_texts(cw, dom) + fw_texts(cw, "dump_end") if t > ST + 180]
            check(f"{label}: the firmware ends the lease at boot (no resume: '{mark[:34]}...') and restores it; "
                  "INV-NO-RESUME and every firmware invariant hold (INV-BOOT-MIRROR judged at the new boot, whose "
                  "stored marker is RESTORE_REQUIRED)", mark in texts and cw.fw_status(dom) ==
                  "RESTORED OK - original inverter settings verified" and not fw_inv(cw)
                  and boot_mirror_judged(cw, dom), f"{invs(fw_inv(cw))} {boot_mirror_judged(cw, dom)}")
            check(f"{label}: Home Assistant never re-starts it (one START press, one lease), no coupled invariant "
                  "violated, SMR1 restores the owner's values after the early end",
                  len(start_presses(cw, dom)) == 1 and len(lease_starts(cw, dom)) == 1 and not hf_inv(cw)
                  and not check_hf_no_resume(cw.log)
                  and cw.smr1_state(dom).startswith("RESTORED"), safe(cw.smr1_state(dom)[:60]))
            check(f"{label}: documented status semantics - the schedule shows COMPLETED (a run that STARTED) and raises "
                  "no alert, although the rest of the window was lost", cw.schedule_status(dom) == "COMPLETED"
                  and cw.notifications() == {})
            info(f"{label}: observation (not classified): the early end after a dongle reboot is visible only in the "
                 f"firmware's own texts; FPS1 / DGS1 say {cw.last_result(dom)[:50]!r} / COMPLETED")
        finally:
            cw.close()
    result("HF-03", "reboot during ACTIVE: no resume, no HA re-start, early end not alerted (observation)")


def run_site_cut(ha_down: float, dg_down: float, dom="dump", plant=False, cut=None, until=None):
    cw = world()
    try:
        if dom == "dump":
            if plant:
                cw.dump_plant()
            arm(cw, "dump", 30, 1000 if not plant else 3000, stop_soc=20)
        else:
            cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
            arm(cw, "fp", 20, 3000)
        t_cut = cut or ST + 180
        cw.restart_ha(t_cut, ha_down, rollback_to_utc=ST - 120)
        cw.reboot_dongle(t_cut, down_s=dg_down)
        cw.run_until(until or t_cut + 300)
        return cw, t_cut
    except BaseException:
        cw.close()
        raise


def site_outcome(cw, dom: str, t_cut: float) -> dict:
    last = cw.last_result(dom)
    new = [s for s in lease_starts(cw, dom) if s > t_cut]
    return {"new": len(new), "gates": len(gate_passes(cw, dom, t_cut)), "last": last, "fw": fw_inv(cw),
            "running_claim": last.startswith("STARTED OK - running (Home Assistant restarted during the session)"),
            "nr": invs(check_hf_no_resume(cw.log)),
            "false_success": invs(hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])),
            "missed": len([e for e in notes_created(cw, NOTE_ID[dom]) if e["t_utc"] > t_cut]),
            "notes_end": sorted(cw.notifications())}


def section_hf03_site(grid) -> None:
    print("[HF-03.4] whole-site power cut during the ACTIVE scheduled Dump to Grid: Home Assistant crashes (helpers "
          "rolled back to 11:58, armed ON) and the dongle reboots at the same instant (+180 s)")
    rows = []
    for ha_down, dg_down in grid:
        cw, t_cut = run_site_cut(ha_down, dg_down)
        try:
            o = site_outcome(cw, "dump", t_cut)
            ended = any(x == "ESP RESTARTED DURING LEASE - ended, not resumed" for _t, x in fw_texts(cw, "dump_end"))
            soc = cw.fw.sim.ent(EMAP[D.D_SOC][0]).state
            mirror = boot_mirror_judged(cw, "dump")
        finally:
            cw.close()
        rows.append((ha_down, dg_down, o, ended, soc, mirror))
        info(f"HA down {ha_down:>5} s, dongle down {dg_down:>4} s -> new leases {o['new']}, DGS1 {o['last'][:62]!r}, "
             f"SMR1 false success {o['false_success']}")
    for ha_down, dg_down, o, ended, soc, mirror in rows:
        tag = f"HA down {ha_down} s / dongle down {dg_down} s"
        check(f"{tag}: the firmware ended the lease at boot ('ESP RESTARTED DURING LEASE - ended, not resumed') and "
              "never resumed it itself (INV-NO-RESUME and every firmware invariant hold; INV-BOOT-MIRROR judged at the "
              "new boot, stored Dump marker RESTORE_REQUIRED)", ended and not o["fw"] and mirror,
              f"{invs(o['fw'])} {mirror}")
        if o["new"]:
            finding("F-HF03-2", f"{tag}: DGS1 recovery started a new Dump lease ({o['last'][:58]})")
            check(f"finding-reproduces:F-HF03-2 ({tag}): exactly one NEW firmware lease after the cut (one START gate "
                  "pass), a fresh gated START with the schedule's Stop SOC 20 %; its 'start was missed' alert is created "
                  "once and dismissed by the run's own success (no notification at the end: the new lease is silent)",
                  o["new"] == 1 and o["gates"] == 1 and o["nr"] == ["INV-HF-NO-RESUME"]
                  and o["last"].startswith("STARTED OK - 1000W for 2")
                  and "Stop SOC 20%" in o["last"]
                  and float(soc) == 20.0 and o["missed"] == 1 and o["notes_end"] == [], f"{o}")
        else:
            check(f"{tag}: Home Assistant read Dump Active before the firmware's boot restore: no new lease, it records "
                  "'STARTED OK - running' (a claim the firmware has already ended); INV-HF-NO-RESUME holds",
                  o["running_claim"] and o["new"] == 0 and o["gates"] == 0 and not o["nr"], safe(o["last"]))
    n_new = sum(1 for r in rows if r[2]["new"])
    info("related (not counted again): after the new lease ends, SMR1 can report RESTORED with a schedule value - the "
         "F-HF02-2 mechanism of HF-02.6; the end lies beyond this run horizon")
    result("HF-03", f"whole-site cut: new Dump lease at {n_new}/{len(rows)} grid points (F-HF03-2)")


# =============================================================================================================================
# HF-05
# =============================================================================================================================
def run_owner_edit_starting(entity: str, value, until=ST + 800, texts=None):
    cw = world(BUSY_START, package_texts=texts)
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.owner_set(entity, value, at_utc=ST + 20)
        cw.run_until(until)
        return cw
    except BaseException:
        cw.close()
        raise


def section_hf05_starting() -> None:
    print("[HF-05.1] owner edit of a staged Free Power number while the schedule is STARTING (bus-busy retry loop)")
    cw = run_owner_edit_starting(S.E_PWR, 5000)
    try:
        st = cw.smr1_state("fp")
        check("owner power 5000 W (not the schedule's value): the schedule re-stages its 3000 W for the lease, and SMR1 "
              "afterwards restores the owner's LATEST 5000 W (and the pre-schedule 40 min); INV-HF-NO-FALSE-SUCCESS "
              "holds", st.startswith("RESTORED") and "charge power 5000 W" in st and cw.ha_state(S.E_PWR) == "5000.0"
              and not hf_inv(cw) and cw.last_result("fp").startswith("STARTED OK - 3000W"), safe(st))
    finally:
        cw.close()
    print("[HF-05.2] owner edit to a schedule-shaped value (duration 7 min <= the schedule's 10) while STARTING")
    cw = run_owner_edit_starting(S.E_DUR, 7)
    try:
        st = cw.smr1_state("fp")
        v = hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])
        # V0.1 (brief B6.3): a documented limit, not a finding (RECLASSIFIED; precedent F-RT02-1): the SMR1 track's
        # schedule-value rule (anchor '{% else %}{{ 1 <= n <= ...schedule_duration... }}') takes the change for the
        # schedule's write, exactly as docs/dev/schedule-manual-restore.md 'Owner change during a scheduled start' states
        info(f"documented limit SMR1-OWNER-STAGING (formerly F-HF05-1, reclassified, not counted): SMR1 {st[:60]!r}: the "
             "owner's 7 min is replaced by the pre-schedule 40 min")
        check("HF-05 documented limit (formerly F-HF05-1, reclassified PASS, not counted): the change is taken for the "
              "schedule's write as docs/dev/schedule-manual-restore.md states - SMR1 RESTORED with the pre-schedule 40 "
              "min; the lab checker's stricter 'owner's latest value' reading reports exactly one "
              "INV-HF-NO-FALSE-SUCCESS violation, which the documented limit explains",
              st.startswith("RESTORED") and "duration 40 min" in st and cw.ha_state(S.E_DUR) == "40.0"
              and invs(v) == ["INV-HF-NO-FALSE-SUCCESS"], f"{st} {v}")
    finally:
        cw.close()
    result("HF-05", "STARTING: non-schedule owner value kept (PASS); schedule-shaped value replaced as documented "
                    "(SMR1-OWNER-STAGING, formerly F-HF05-1, PASS, not counted)")


def run_owner_edit_active(texts=None, until=ST + 700):
    cw = world(package_texts=texts)
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.run_until(ST + 300)
        end0 = cw.fw.globals_view(["free_power_end_epoch"])["free_power_end_epoch"]
        cw.owner_set(S.E_DUR, 25, at_utc=ST + 300)
        cw.run_until(ST + 360)
        end1 = cw.fw.globals_view(["free_power_end_epoch"])["free_power_end_epoch"]
        cw.run_until(until)
        return cw, (end0, end1)
    except BaseException:
        cw.close()
        raise


def section_hf05_active() -> None:
    print("[HF-05.3] owner edit of the Free Power duration (25 min) during the ACTIVE scheduled lease")
    cw, (end0, end1) = run_owner_edit_active()
    try:
        st = cw.smr1_state("fp")
        check("the firmware reads the staged duration only at START: the lease end epoch is unchanged by the edit and "
              "the lease ends at it", end0 == end1 and cw.fw_status("fp").startswith("RESTORED OK"), f"{end0} {end1}")
        check("SMR1 keeps the owner's 25 min (field dropped) and restores only the power; INV-HF-SMR1-QUIET and "
              "INV-HF-NO-FALSE-SUCCESS hold", st.startswith("RESTORED") and "charge power 8000 W" in st
              and "duration" not in st and cw.ha_state(S.E_DUR) == "25.0" and not hf_inv(cw), safe(st))
    finally:
        cw.close()
    result("HF-05", "ACTIVE: owner edit kept, firmware lease unaffected")


def restoring_reference() -> tuple:
    """(SMR1 RESTORING instant, (t0, until) of the firmware's Free Power restore transaction) of the 10-min run."""
    cw = world()
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.run_until(ST + 700)
        r = next(e["t_utc"] for e in ev(cw, "ha.state", e=H.SMR1_STATE["fp"]) if e["data"]["s"].startswith("RESTORING"))
        txn = next(e["data"] for e in ev(cw, "dongle.txn") if "restore_free_power_snapshot" in e["data"]["scripts"])
        return r, (txn["t0"], txn["until"])
    finally:
        cw.close()


def run_owner_edit_restoring(at: float, via: str, until=ST + 700):
    cw = world()
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.owner_set(S.E_DUR, 25, at_utc=at, via=via)
        cw.run_until(until)
        return cw
    except BaseException:
        cw.close()
        raise


def section_hf05_restoring() -> None:
    print("[HF-05.4] owner edit of the Free Power duration (25 min) around SMR1's RESTORING (sweep of the instant)")
    r, txn = restoring_reference()
    info(f"reference: firmware restore transaction [+{txn[0] - ST:.3f}, +{txn[1] - ST:.3f}] s, SMR1 RESTORING at "
         f"+{r - ST:.3f} s (after its 5 s settle)")
    # via 'ha' is the owner's realistic path (dashboard); via 'dongle' is the modelled other-native-API-client path (the
    # firmware has no web_server). Negative offsets: the owner acts while SMR1 still reads OWED.
    cases = (("ha", -4.0, "dropped"), ("ha", -0.16, "dropped"), ("ha", -0.14, "lost"), ("ha", -0.05, "lost"),
             ("ha", 0.0, "lost"), ("ha", 0.05, "kept"), ("dongle", 0.0, "lost"), ("dongle", 0.02, "lost"))
    for via, off, want in cases:
        cw = run_owner_edit_restoring(r + off, via)
        try:
            st, num = cw.smr1_state("fp"), cw.ha_state(S.E_DUR)
            v = hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])
            tag = f"via {via} at RESTORING {off:+.2f} s"
            info(f"{tag}: SMR1 {st[:76]!r}; the number reads {num}; notifications {sorted(cw.notifications())}")
            if want == "lost":
                finding("F-HF05-2", f"{tag}: the owner's 25 min is overwritten by the restore's 40 min, SMR1 RESTORED")
                check(f"finding-reproduces:F-HF05-2 ({tag}): lost update - the number reads the restored 40 min, SMR1 "
                      "says RESTORED with no notification, exactly one INV-HF-NO-FALSE-SUCCESS violation",
                      st.startswith("RESTORED") and num == "40.0" and cw.notifications() == {}
                      and invs(v) == ["INV-HF-NO-FALSE-SUCCESS"], f"{st} {num} {v}")
            elif want == "kept":
                check(f"{tag}: the owner's change lands after the restore write - kept on the number (25 min); "
                      "INV-HF-NO-FALSE-SUCCESS holds (SMR1's text still names the restored 40 min: stale text, "
                      "observation)", num == "25.0" and not v and "duration 40 min" in st, f"{st} {num}")
            else:
                check(f"{tag}: Home Assistant sees the change while the state is still OWED - the change is the owner's "
                      "(field dropped), only the power is restored; INV-HF-NO-FALSE-SUCCESS holds", num == "25.0"
                      and not v and "duration" not in st and st.startswith("RESTORED"), f"{st} {num}")
        finally:
            cw.close()
    cw = world()
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        arm(cw, "fp", 10, 3000)
        cw.owner_set(S.E_DUR, 25, at_utc=txn[0] + 1.0, via="dongle")
        hit, msg = raises_unsupported(lambda: cw.run_until(ST + 700))
    finally:
        cw.close()
    if hit:
        unsupported("HF-05-UNS-2", f"{SUPPORT['HF-05-UNS-2']}: {msg[:110]}")
    check("an owner edit inside the firmware's projected restore transaction is refused loudly (LabUnsupported, "
          "classified UNSUPPORTED, never applied silently)", hit and "interleaving inside a projected firmware "
          "transaction is not modelled" in msg, msg[:200])
    result("HF-05", "RESTORING: lost update within cmd + publish of the restore write, via HA from -0.14 s (owner acts "
                    "while OWED) to +0.00 s (F-HF05-2); dropped as the owner's earlier; kept after; refused inside the txn")


def section_hf05_race() -> None:
    print("[HF-05.5] owner manual START racing the schedule")
    cw = world()
    try:
        arm(cw, "fp", 10, 3000)
        cw.owner_set(S.E_PWR, 2000, at_utc=ST - 60)
        cw.owner_set(S.E_DUR, 30, at_utc=ST - 60)
        cw.owner_set(S.E_ARM, True, at_utc=ST - 59)
        cw.owner_press(S.E_PRESS, at_utc=ST - 57)
        cw.run_until(ST + 120)
        check("owner START 57 s before the schedule: the schedule records 'BLOCKED - Free Power already active' "
              "silently (documented, no alert), stages and presses nothing, disarms; one lease with the owner's "
              "2000 W / 30 min; SMR1 owes nothing", cw.last_result("fp") == "BLOCKED - Free Power already active"
              and not start_presses(cw, "fp", "schedule") and cw.notifications() == {}
              and cw.ha_state(H.ARMED["fp"]) == "off" and len(lease_starts(cw, "fp")) == 1
              and (cw.ha_state(S.E_PWR), cw.ha_state(S.E_DUR)) == ("2000.0", "30.0") and not cw.smr1_state("fp")
              and not hf_inv(cw) and not fw_inv(cw), safe(cw.last_result("fp")))
    finally:
        cw.close()
    cw = world()
    try:
        arm(cw, "fp", 10, 3000)
        cw.owner_press(S.E_PRESS, at_utc=ST + 1.10, via="dongle")
        cw.run_until(ST + 120)
        dropped = [e["data"]["why"] for e in ev(cw, "dongle.dropped")]
        check("owner START via the modelled other-native-API-client path (via='dongle') 0.17 s before the schedule's "
              "press reaches the gate: the schedule's press is "
              "DROPPED by the running START (ESPHome mode single) - one START transaction, one lease (documented "
              "'Never two transactions'); the schedule reports STARTED OK with its own staged values",
              dropped == ["busy_same_script"] and len(ev(cw, "dongle.txn")) >= 1 and len(lease_starts(cw, "fp")) == 1
              and cw.last_result("fp").startswith("STARTED OK - 3000W for 10 min") and not hf_inv(cw)
              and not fw_inv(cw), f"{dropped} {safe(cw.last_result('fp'))}")
    finally:
        cw.close()
    cw = world()
    try:
        arm(cw, "fp", 10, 3000)
        cw.owner_press(S.E_PRESS, at_utc=ST + 0.6, via="dongle")
        hit, msg = raises_unsupported(lambda: cw.run_until(ST + 120))
    finally:
        cw.close()
    if hit:
        unsupported("HF-05-UNS-1", f"{SUPPORT['HF-05-UNS-1']}: {msg[:110]}")
    check("owner START between the schedule's staging and its press: the schedule's next command (write enable off) "
          "falls inside the owner's projected START transaction and is refused loudly (UNSUPPORTED, never a pass)",
          hit and "switch.turn_off" in msg, msg[:200])
    result("HF-05", "manual START race: BLOCKED already active (PASS); dropped press (PASS); staging interleave UNSUPPORTED")


# =============================================================================================================================
# HF-09
# =============================================================================================================================
# The fault hook is the interpreter's own World.fail_services (the hook of the model suites' service-error cases). Its
# ASSUMPTIONS are in the module docstring: S.ServiceError only, raised before delivery, keyed by service name - so every
# injection below is armed at an instant where the targeted call is the next call of that service, and every check asserts
# which call raised (the interpreter's 'raised (continue_on_error)' warning and the missing dongle.cmd).
COUNTER = {"fp": "free_power_start_attempts", "dump": "dump_start_attempts"}
PKG = {"fp": "FPS1", "dump": "DGS1"}
BLOCKER = "sensor.ecco_schedule_restore_blocker"
WINDOW_FAILED = "FAILED TO START - authorised window ends 12:10; not started"
_REF: dict = {}


def inject(cw, at_utc: float, faults: dict) -> None:
    """Arm the interpreter's fault hook on the World clock: at at_utc, fail_services[svc] += n for each {svc: n}."""
    def go():
        for svc, n in faults.items():
            cw.w.fail_services[svc] = cw.w.fail_services.get(svc, 0) + n
    cw.w.at(at_utc, go)


def raised(cw, svc: str) -> list:
    """Instants (s after ST) of the calls of svc that raised and that continue_on_error contained (interpreter warning)."""
    tail = f" {svc} raised (continue_on_error)"
    return [round(float(w.split(" ", 1)[0]) - ST, 3) for w in cw.w.warnings if w.endswith(tail)]


def aborted(cw) -> list:
    """Script / automation runs that a service error aborted (a raising call without continue_on_error)."""
    return [w for w in cw.w.warnings if "run aborted by a service error" in w]


def calls_of(cw, svc: str, entity: str, by=None) -> list:
    """Instants (s after ST) of Home Assistant's calls of svc on entity (the ha.call record precedes any raise)."""
    return [round(e["t_utc"] - ST, 3) for e in ev(cw, "ha.call", svc=svc)
            if entity in e["data"]["e"] and (by is None or e["data"]["by"] == by)]


def cmds_of(cw, svc: str, entity: str, by=None) -> list:
    """Instants (s after ST) of the commands of svc on entity that reached the firmware."""
    return [round(e["t_utc"] - ST, 3) for e in ev(cw, "dongle.cmd", svc=svc, e=entity)
            if by is None or e["data"]["by"] == by]


def fw_we(cw, dom: str) -> bool:
    """Firmware truth of the domain's write enable (observer only)."""
    return bool(cw.fw.sim.ent(ARM_FID[dom]).state)


def gate_count(cw, dom: str):
    """The firmware's RAM gate-pass counter (what the packages read as '... Start Attempts Since Boot')."""
    return cw.fw.globals_view([COUNTER[dom]])[COUNTER[dom]]


def mutate_after(text: str, section: str, old: str, new: str, what: str) -> str:
    """mutate() inside the part of text after its one `section` anchor (the same old text occurs in another section)."""
    if text.count(section) != 1:
        raise H.LabHarnessError(f"section anchor for {what} found {text.count(section)}x (exactly once required)")
    head, tail = text.split(section)
    return head + section + mutate(tail, old, new, what)


def restoring_ref() -> tuple:
    """restoring_reference() of HF-05.4, computed once."""
    if "ref" not in _REF:
        _REF["ref"] = restoring_reference()
    return _REF["ref"]


def run_fault(dom: str, faults=(), until=None, outage=None, policy="silent", texts=None, fwd=None, sample=None):
    """One scheduled start with service faults: faults [(at_utc, {svc: n})]; outage (at_utc, down_s) of the ESPHome API;
    policy = offline_policy; sample (t_from, t_to, step) = firmware-truth samples of the write enable. -> (cw, samples)."""
    cw = world(fwk={"fw": fwd} if fwd is not None else None, package_texts=texts, offline_policy=policy)
    try:
        if dom == "fp":
            cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
            arm(cw, "fp", 10, 3000)
        else:
            arm(cw, "dump", 30, 1000, stop_soc=20)
        for at, f in faults:
            inject(cw, at, f)
        if outage is not None:
            cw.api_outage(outage[0], outage[1])
        smp = sample_switch(cw, ARM_FID[dom], *sample) if sample else []
        cw.run_until(until or ST + 700)
        return cw, smp
    except BaseException:
        cw.close()
        raise


def report(cw, dom: str, tag: str) -> None:
    """What FPS1 / DGS1 and SMR1 report and which notifications were raised (information)."""
    created = sorted({str((e["data"].get("data") or {}).get("notification_id"))
                      for e in ev(cw, "ha.call", svc="persistent_notification.create")})
    info(f"{tag}: {PKG[dom]} {cw.last_result(dom)[:100]!r}; SMR1 {cw.smr1_state(dom)[:84]!r}; notifications created "
         f"{created}, open at the end {sorted(cw.notifications())}")


def section_hf09_press(doms) -> None:
    print("[HF-09.1] the scheduled START press raises (one S.ServiceError, armed 1 s before the start): the no-answer "
          "proof against the real firmware's gate and RAM gate-pass counter")
    for dom in doms:
        label = LABEL[dom]
        cw, _s = run_fault(dom, [(ST - 1, {"button.press": 1})], until=ST + (700 if dom == "fp" else 200))
        try:
            texts = [s for _t, s in results_of(cw, dom)]
            pc = calls_of(cw, "button.press", PRESS_HA[dom], "schedule")
            pr = cmds_of(cw, "button.press", PRESS_HA[dom], "schedule")
            gp = gate_passes(cw, dom, ST)
            last = cw.last_result(dom)
            report(cw, dom, f"HF-09.1 {label}")
            check(f"{label}: the call that raised is the first scheduled START press and it never reached the dongle (no "
                  "command, no gate pass before the retry's press); the run is not aborted (continue_on_error)",
                  len(pc) == 2 and raised(cw, "button.press") == pc[:1] and len(pr) == 1 and pr[0] > pc[1]
                  and len(gp) == 1 and gp[0] - ST >= pc[1] and not aborted(cw), f"{pc} {pr} {gp}")
            check(f"{label}: {PKG[dom]}'s 'never reached the dongle (no start counted)' is TRUE on the real firmware - its "
                  "RAM gate-pass counter did not move for the raised press (1 at the end: the retry's pass); the retry is "
                  "an ordinary gated START (STARTED OK, attempt 2), one lease; INV-HF-PRESS-PROOF and INV-HF-NEVER-SILENT "
                  "hold", any(s.startswith("STARTING - attempt 1 never reached the dongle (no start counted)")
                              for s in texts)
                  and gate_count(cw, dom) == 1 and last.startswith("STARTED OK") and "(attempt 2;" in last
                  and len(lease_starts(cw, dom)) == 1 and not check_press_proof(cw.log)
                  and not check_never_silent(cw.log), safe(last))
            hf, fwv = hf_inv(cw), fw_inv(cw)
            smr1_ok = dom != "fp" or (cw.smr1_state("fp").startswith("RESTORED") and cw.ha_state(S.E_DUR) == "40.0"
                                      and cw.ha_state(S.E_PWR) == "8000.0")
            check(f"{label}: every coupled invariant (INV-HF-ARM-OFF, -ONE-LEASE, -SMR1-QUIET, -NO-FALSE-SUCCESS, "
                  "-OWNER-INTENT, -WINDOW) and every firmware invariant hold; no notification open at the end (the run "
                  "started)" + ("; SMR1 RESTORED the owner's 8000 W / 40 min" if dom == "fp" else ""),
                  not hf and not fwv and cw.notifications() == {} and smr1_ok, f"{invs(hf)} {invs(fwv)}")
        finally:
            cw.close()
    result("HF-09", f"START press raise ({'/'.join(doms)}): contained; the no-answer proof true on the real counter; one "
                    "retry, one lease")


def section_hf09_arm(doms) -> None:
    print("[HF-09.2] the schedule's write-enable turn_on raises once while staging (armed 1 s before the start)")
    for dom in doms:
        label = LABEL[dom]
        cw, smp = run_fault(dom, [(ST - 1, {"switch.turn_on": 1})], until=ST + (700 if dom == "fp" else 120),
                            sample=(ST, ST + 30, 0.25))
        try:
            on_c = calls_of(cw, "switch.turn_on", WE_HA[dom], "schedule")
            on_d = cmds_of(cw, "switch.turn_on", WE_HA[dom], "schedule")
            pr = cmds_of(cw, "button.press", PRESS_HA[dom], "schedule")
            texts = [s for _t, s in results_of(cw, dom)]
            last = cw.last_result(dom)
            report(cw, dom, f"HF-09.2 {label}")
            first_on = on_d[0] if on_d else 1e9
            check(f"{label}: the call that raised is the first staging turn_on and no command reached the dongle; the "
                  "firmware write enable stays OFF until the retry's turn_on (firmware truth, 0.25 s samples) and nothing "
                  f"is pressed before it; {PKG[dom]} records 'arm or staged values not confirmed; nothing pressed' and "
                  "its retry starts (STARTED OK, attempt 2): one press, one lease, gate-pass counter 1",
                  len(on_c) == 2 and raised(cw, "switch.turn_on") == on_c[:1] and len(on_d) == 1 and on_d[0] > on_c[1]
                  and all(v is False for t, v in smp if t < ST + first_on) and len(pr) == 1 and pr[0] > first_on
                  and any(s.startswith("STARTING - attempt 1: arm or staged values not confirmed; nothing pressed")
                          for s in texts) and last.startswith("STARTED OK") and "(attempt 2;" in last
                  and len(lease_starts(cw, dom)) == 1 and gate_count(cw, dom) == 1 and not aborted(cw),
                  f"{on_c} {on_d} {pr} {safe(last)}")
            hf, fwv = hf_inv(cw), fw_inv(cw)
            check(f"{label}: every coupled and firmware invariant holds; INV-HF-PRESS-PROOF holds; no notification open",
                  not hf and not fwv and not check_press_proof(cw.log) and cw.notifications() == {},
                  f"{invs(hf)} {invs(fwv)}")
        finally:
            cw.close()
    result("HF-09", f"write-enable turn_on raise once ({'/'.join(doms)}): nothing pressed, retried, started")


def section_hf09_arm_always(doms) -> None:
    print("[HF-09.2b] the write-enable turn_on raises on EVERY call (the model suites' 'service error on every arm' case, "
          "here against the real firmware)")
    for dom in doms:
        label = LABEL[dom]
        cw, smp = run_fault(dom, [(ST - 1, {"switch.turn_on": 999})], until=ST + 900, sample=(ST, ST + 620, 1.0))
        try:
            n = len(raised(cw, "switch.turn_on"))
            report(cw, dom, f"HF-09.2b {label}")
            hf, fwv = hf_inv(cw), fw_inv(cw)
            check(f"{label}: documented outcome, now on the real firmware - nothing reaches it (no turn_on command, no "
                  "press, the write enable OFF at every 1 s sample, gate-pass counter 0, status 'Inactive', no lease); "
                  "FAILED at the retry deadline with the schedule's alert open; SMR1 then restores the owner's values "
                  "(RESTORED); every coupled and firmware invariant holds",
                  n >= 40 and n == len(calls_of(cw, "switch.turn_on", WE_HA[dom], "schedule"))
                  and not cmds_of(cw, "switch.turn_on", WE_HA[dom]) and not start_presses(cw, dom)
                  and smp and all(v is False for _t, v in smp) and gate_count(cw, dom) == 0
                  and cw.fw_status(dom) == "Inactive" and not lease_starts(cw, dom)
                  and cw.last_result(dom).startswith("FAILED TO START") and NOTE_ID[dom] in cw.notifications()
                  and cw.smr1_state(dom).startswith("RESTORED") and not hf and not fwv and not aborted(cw),
                  f"{n} {safe(cw.last_result(dom))} {invs(hf)} {invs(fwv)}")
        finally:
            cw.close()
    result("HF-09", f"write-enable turn_on raise on every call ({'/'.join(doms)}): never pressed, FAILED + alert, SMR1 "
                    "RESTORED")


def section_hf09_smr1() -> None:
    print("[HF-09.3] SMR1's first restore write (Free Power charge power) raises right after the REAL firmware's own "
          "restore (armed 0.5 s after the firmware's restore transaction, before SMR1's RESTORING)")
    r, txn = restoring_ref()
    at = txn[1] + 0.5
    cw, _s = run_fault("fp", [(at, {"number.set_value": 1})], until=ST + 1500)
    try:
        st = cw.smr1_state("fp")
        fw_ok = [t for t, x in fw_texts(cw, "fp") if x == "RESTORED OK - original inverter settings verified"]
        pw_c = calls_of(cw, "number.set_value", S.E_PWR, "smr1")
        pw_d = cmds_of(cw, "number.set_value", S.E_PWR, "smr1")
        du_d = [e["data"]["value"] for e in ev(cw, "dongle.cmd", svc="number.set_value", e=S.E_DUR, by="smr1")]
        report(cw, "fp", "HF-09.3 Free Power")
        check("the call that raised is SMR1's first restore write (charge power), after the firmware's verified restore "
              "and before any other number call; no command reached the dongle for it, the duration write did (40 min); "
              "the restore automation is not aborted (continue_on_error)",
              at < r and len(fw_ok) == 1 and fw_ok[0] <= at and raised(cw, "number.set_value") == pw_c
              and len(pw_c) == 1 and abs(pw_c[0] - (r - ST)) < 0.01 and not pw_d and du_d == [40.0] and not aborted(cw),
              f"{at - ST:.2f} {r - ST:.2f} {pw_c} {pw_d} {du_d}")
        check("documented SMR1 outcome, now after a real firmware restore: PARTIAL naming the field to set by hand (the "
              "power reads the schedule's 3000 W in Home Assistant and on the firmware number), one notification created "
              "and kept open, nothing left owed, never retried (no further SMR1 write up to +25 min)",
              st.startswith("PARTIAL ") and "restored: duration 40 min; NOT restored, set by hand: charge power (reads "
              "3000.0, should be 8000 W)" in st and cw.ha_state(S.E_PWR) == "3000.0"
              and float(cw.fw.sim.ent(EMAP[S.E_PWR][0]).state) == 3000.0
              and len(notes_created(cw, "ecco_sched_restore_fp")) == 1 and "ecco_sched_restore_fp" in cw.notifications()
              and cw.ha_state("input_number.ecco_sched_restore_fp_power_written") == "0.0"
              and cw.ha_state("input_number.ecco_sched_restore_fp_duration_written") == "0.0"
              and len(ev(cw, "ha.call", svc="number.set_value", by="smr1")) == 2, safe(st))
        hf, fwv = hf_inv(cw), fw_inv(cw)
        check("INV-HF-SMR1-QUIET (both restore writes after the firmware's restore transaction), INV-HF-NO-FALSE-SUCCESS "
              "(no RESTORED claim) and every other coupled and firmware invariant hold; the firmware stays RESTORED OK",
              not hf and not fwv and cw.fw_status("fp") == "RESTORED OK - original inverter settings verified",
              f"{invs(hf)} {invs(fwv)}")
    finally:
        cw.close()
    result("HF-09", "SMR1 restore-write raise after the real firmware restore: PARTIAL, notified, nothing owed, no retry")


def section_hf09_closing(doms) -> None:
    print("[HF-09.4] the run's closing post-START write-enable turn_off raises (armed at +3 s, after the gate pass)")
    for dom in doms:
        label = LABEL[dom]
        cw, smp = run_fault(dom, [(ST + 3.0, {"switch.turn_off": 1})], until=ST + (700 if dom == "fp" else 120),
                            sample=(ST + 1.5, ST + 60, 0.25))
        try:
            gp = gate_passes(cw, dom, ST)
            off_c = calls_of(cw, "switch.turn_off", WE_HA[dom], "schedule")
            off_d = [t for t in cmds_of(cw, "switch.turn_off", WE_HA[dom]) if t > 0]
            started = next((t for t, s in results_of(cw, dom) if s.startswith("STARTED OK")), None)
            last = cw.last_result(dom)
            report(cw, dom, f"HF-09.4 {label}")
            check(f"{label}: the call that raised is the run's closing turn_off (the only turn_off after the start, issued "
                  "as the result turned STARTED OK) and it never reached the dongle; nothing aborted",
                  started is not None and off_c == [round(started - ST, 3)] and raised(cw, "switch.turn_off") == off_c
                  and not off_d and not aborted(cw), f"{off_c} {off_d} {started}")
            hf, fwv = hf_inv(cw), fw_inv(cw)
            check(f"{label}: firmware truth - the real gate disarmed the write enable itself at the press (one gate pass "
                  "before +1.5 s) and it reads OFF at every 0.25 s sample to +60 s; INV-HF-ARM-OFF and every other "
                  "coupled and firmware invariant hold; STARTED OK on attempt 1, one press, one lease, no notification",
                  len(gp) == 1 and gp[0] < ST + 1.5 and bool(smp) and all(v is False for _t, v in smp) and not hf
                  and not fwv and last.startswith("STARTED OK") and "(attempt 1;" in last
                  and len(start_presses(cw, dom)) == 1 and len(lease_starts(cw, dom)) == 1 and cw.notifications() == {},
                  f"{gp} {invs(hf)} {invs(fwv)} {safe(last)}")
        finally:
            cw.close()
    result("HF-09", f"closing turn_off raise ({'/'.join(doms)}): harmless - the real firmware disarmed at the press")


def section_hf09_noanswer(doms) -> None:
    print("[HF-09.5] the START press AND the no-answer branch's turn_off raise (armed at +1.0 s): the closing turn_off is "
          "the backstop")
    for dom in doms:
        label = LABEL[dom]
        cw, smp = run_fault(dom, [(ST + 1.0, {"button.press": 1, "switch.turn_off": 1})], until=ST + 300,
                            sample=(ST + 18.5, ST + 62.5, 0.5))
        try:
            off_c = calls_of(cw, "switch.turn_off", WE_HA[dom], "schedule")
            off_d = [t for t in cmds_of(cw, "switch.turn_off", WE_HA[dom], "schedule") if t > 0]
            last = cw.last_result(dom)
            report(cw, dom, f"HF-09.5 {label}")
            hf, fwv = hf_inv(cw), fw_inv(cw)
            check(f"{label}: the press and the no-answer turn_off raised (neither reached the dongle); the write enable "
                  "stays ON through the no-answer wait (firmware truth), so the package does not retry ('outcome "
                  "unconfirmed, not retried', alerted; the gate-pass counter shows a retry would have been safe); the "
                  "closing turn_off reaches the dongle and the write enable ends OFF; INV-HF-ARM-OFF (exempt while the "
                  "script runs) and every other coupled and firmware invariant hold; SMR1 RESTORED",
                  len(raised(cw, "button.press")) == 1 and not start_presses(cw, dom) and len(off_c) == 2
                  and raised(cw, "switch.turn_off") == off_c[:1] and len(off_d) == 1 and off_d[0] > off_c[1]
                  and bool(smp) and all(v is True for _t, v in smp) and last.startswith(NO_ANSWER)
                  and gate_count(cw, dom) == 0 and NOTE_ID[dom] in cw.notifications() and fw_we(cw, dom) is False
                  and not hf and not fwv and cw.smr1_state(dom).startswith("RESTORED") and not aborted(cw),
                  f"{off_c} {off_d} {invs(hf)} {invs(fwv)} {safe(last)}")
        finally:
            cw.close()
    result("HF-09", f"press + no-answer turn_off raise ({'/'.join(doms)}): unconfirmed, not retried, alerted; the closing "
                    "turn_off ends it off")


def f09_state(cw, dom: str) -> dict:
    msg = str((cw.notifications().get(NOTE_ID[dom]) or {}).get("message", ""))
    return {"last": cw.last_result(dom), "we_fw": fw_we(cw, dom), "we_ha": cw.ha_state(WE_HA[dom]),
            "smr1": cw.smr1_state(dom), "blocker": cw.ha_state(BLOCKER), "alert": NOTE_ID[dom] in cw.notifications(),
            "alert_names_switch": "write enable" in msg.lower(), "arm_off": invs(hf_inv(cw, ["INV-HF-ARM-OFF"])),
            "other": invs(hf_inv(cw, sorted(set(H.HF_INVARIANTS) - {"INV-HF-ARM-OFF"}))), "fw": invs(fw_inv(cw)),
            "leases": len(lease_starts(cw, dom)), "gate": gate_count(cw, dom), "aborted": len(aborted(cw))}


def f09_left_on(o: dict, dom: str, head: str) -> bool:
    """The F-HF09-1 end state: the run ended with its alert, the write enable ON after it (firmware truth and Home
    Assistant), SMR1 OWED behind '<function> write enable armed', exactly one INV-HF-ARM-OFF violation, nothing else."""
    return (o["last"].startswith(head) and o["we_fw"] is True and o["we_ha"] == "on" and o["smr1"].startswith("OWED")
            and f"{LABEL[dom]} write enable armed" in o["blocker"] and o["alert"] and not o["alert_names_switch"]
            and o["arm_off"] == ["INV-HF-ARM-OFF"] and o["other"] == [] and o["fw"] == [] and o["leases"] == 0
            and o["gate"] == 0 and o["aborted"] == 0)


def section_hf09_left_on(doms, outages) -> None:
    print("[HF-09.6] every turn-off of the run fails after an unanswered press: three service errors while connected "
          "(press + both turn-offs, armed at +1.0 s), or one ESPHome API outage covering both turn-offs")
    for dom in doms:
        cw, _s = run_fault(dom, [(ST + 1.0, {"button.press": 1, "switch.turn_off": 2})], until=ST + 300)
        try:
            o = f09_state(cw, dom)
            r_off = raised(cw, "switch.turn_off")
            off_c = calls_of(cw, "switch.turn_off", WE_HA[dom], "schedule")
            report(cw, dom, f"HF-09.6 {LABEL[dom]}, three service errors")
        finally:
            cw.close()
        finding("F-HF09-1", f"{LABEL[dom]}, three service errors: write enable left ON after the run (firmware truth); "
                            f"SMR1 {o['smr1'].split(' ')[0]} waiting for {o['blocker']!r}; alert {o['last'][:60]!r}")
        check(f"finding-reproduces:F-HF09-1 ({LABEL[dom]}, service errors): the press and BOTH turn-offs of the run "
              "raised (none reached the dongle); the run ends 'outcome unconfirmed, not retried' with its alert, which "
              "does not name the switch; the write enable is ON after the run (firmware truth and Home Assistant); SMR1 "
              "OWED behind 'write enable armed'; exactly one INV-HF-ARM-OFF violation, every other coupled and firmware "
              "invariant holds, no lease", f09_left_on(o, dom, NO_ANSWER) and len(off_c) == 2 and r_off == off_c,
              f"{o} {off_c} {r_off}")
    for pol, at, down, head in outages:
        cw, _s = run_fault("fp", outage=(ST + at, down), policy=pol, until=ST + (300 if down < 100 else 900))
        try:
            o = f09_state(cw, "fp")
            drop = [(round(e["t_utc"] - ST, 2), e["data"]["svc"], e["data"]["why"]) for e in ev(cw, "dongle.dropped")]
            n_raised = len(raised(cw, "switch.turn_off"))
            report(cw, "fp", f"HF-09.6 Free Power, API outage +{at} s / {down:.0f} s ({pol})")
        finally:
            cw.close()
        tag = f"API outage from +{at} s for {down:.0f} s, offline_policy {pol!r}"
        offs = [d for d in drop if d[1] == "switch.turn_off" and d[2] == "offline"]
        finding("F-HF09-1", f"Free Power, {tag}: write enable left ON after the run; SMR1 {o['smr1'].split(' ')[0]} "
                            f"waiting for {o['blocker']!r}")
        check(f"finding-reproduces:F-HF09-1 ({tag}): every turn_off of the run met the offline dongle ("
              + ("each raised S.ServiceError" if pol == "raise" else "each dropped silently") + "); the same end state - "
              "the write enable ON after the run, SMR1 OWED behind it, the alert silent about it, exactly one "
              "INV-HF-ARM-OFF violation", f09_left_on(o, "fp", head) and len(offs) == 2
              and n_raised == (2 if pol == "raise" else 0), f"{o} {drop}")
    result("HF-09", "F-HF09-1 reproduced: write enable left ON after every turn-off of the run failed (service errors; "
                    "an API outage under 'raise' and 'silent')")


def section_hf09_boundary() -> None:
    print("[HF-09.7] boundary twin: the same press-flight API outage, 40 s (offline_policy 'raise'): the dongle is back "
          "before the closing turn_off")
    cw, _s = run_fault("fp", outage=(ST + 1.2, 40.0), policy="raise", until=ST + 300)
    try:
        last = cw.last_result("fp")
        report(cw, "fp", "HF-09.7 Free Power")
        hf, fwv = hf_inv(cw), fw_inv(cw)
        check("the no-answer turn_off raised (offline, contained) and the closing turn_off reached the dongle: the write "
              "enable ends OFF; 'outcome unconfirmed, not retried' with its alert; SMR1 RESTORED; every coupled and "
              "firmware invariant holds", last.startswith(NO_ANSWER) and fw_we(cw, "fp") is False
              and len(raised(cw, "switch.turn_off")) == 1 and cw.smr1_state("fp").startswith("RESTORED")
              and NOTE_ID["fp"] in cw.notifications() and not hf and not fwv and not aborted(cw),
              f"{safe(last)} {invs(hf)} {invs(fwv)}")
    finally:
        cw.close()
    result("HF-09", "boundary twin (outage ends before the closing turn_off): the write enable ends off")


def section_hf09_sweep() -> None:
    print("[EXT-7] F-HF09-1 edge: API outage from inside the press's flight (+1.2 s), down 30..90 s, offline_policy "
          "'raise'")
    rows = []
    for down in range(30, 91, 5):
        cw, _s = run_fault("fp", outage=(ST + 1.2, float(down)), policy="raise", until=ST + 300)
        try:
            off_c = calls_of(cw, "switch.turn_off", WE_HA["fp"], "schedule")
            rows.append((down, fw_we(cw, "fp"), off_c[-1] if off_c else None, invs(hf_inv(cw, ["INV-HF-ARM-OFF"]))))
        finally:
            cw.close()
    info("outage s -> write enable after the run: " + ", ".join(f"{d}:{'ON' if on else 'off'}" for d, on, _c, _v in rows))
    closing = {c for _d, _o, c, _v in rows}
    check("edge: the write enable is left ON exactly when the outage still covers the run's closing turn_off (reconnect "
          "at +1.2 s + down after the closing call), and INV-HF-ARM-OFF flags exactly those points",
          len(closing) == 1 and None not in closing
          and all(on == (1.2 + d > c) and (v == ["INV-HF-ARM-OFF"]) == on for d, on, c, v in rows), str(rows))


# =============================================================================================================================
# negative controls (one or more per family)
# =============================================================================================================================
def section_negative_controls() -> None:
    print("[NC] negative controls: one real guard mutated IN MEMORY per family; the intended invariant must fail")
    fps1, smr1 = H.package_text("fps1"), H.package_text("smr1")
    fwt = T.read_source_text(FW)

    def nc_hf02_1():
        old = ("                id: start\n            sequence:\n              - action: script.ecco_free_power_start_"
               "scheduled\n                continue_on_error: true\n                data:\n                  duration_minutes:"
               " \"{{ states('input_number.ecco_free_power_schedule_duration') | int(1) }}\"\n                  power_w: "
               "\"{{ states('input_number.ecco_free_power_schedule_power') | int(500) }}\"\n                  window_end_ts:"
               " \"{{ end_ts }}\"\n              - if:\n                  - condition: template\n                    "
               "value_template: \"{{ states('input_datetime.ecco_free_power_schedule_start') == fired_for }}\"")
        new = old.replace("== fired_for }}", "== 'lab_never' }}")
        cw, _t = run_end_then_restart("fp", rollback=None, until=ST + 600, t_end=ST + 120, t_crash=ST + 150,
                                      texts={"fps1": mutate(fps1, old, new, "NC-HF02-1")})
        try:
            return hf_inv(cw, ["INV-HF-OWNER-INTENT"])
        finally:
            cw.close()
    negative_control("NC-HF02-1", "HF-02", "FPS1 fire automation: the on-time start never disarms the schedule after "
                     "its run (End +120 s, graceful restart +150 s)", "INV-HF-OWNER-INTENT", nc_hf02_1)
    old_g = ('                  - condition: state\n                    entity_id: input_boolean.ecco_free_power_schedule_'
             'armed\n                    state: "off"')
    cw, _t = run_end_then_restart("fp", rollback=None, until=ST + 600,
                                  texts={"fps1": mutate(fps1, old_g, old_g.replace('"off"', '"lab_never"'), "NC-HF02-1b")})
    try:
        surv = (not hf_inv(cw, ["INV-HF-OWNER-INTENT"]) and len(start_presses(cw, "fp")) == 1
                and cw.last_result("fp") == "CANCELLED - scheduled Free Power cancelled before it started")
    finally:
        cw.close()
    NC_RESULTS.append({"id": "NC-HF02-1b", "family": "HF-02", "mutation": "FPS1 startup recovery armed-off guard never "
                       "matches", "target": "INV-HF-OWNER-INTENT", "outcome": "survived (defence in depth)",
                       "detail": "the start script's own cancel check stops the run"})
    check("defence in depth (NC-HF02-1b, expected to survive): with only the recovery's 'not armed any more' guard "
          "disabled, the start script's own cancel check (armed off) ends the run CANCELLED before any press",
          surv)

    def nc_hf02_2():
        old = ('            entity_id: script.ecco_free_power_start_scheduled\n            state: "off"\n        then:\n'
               '          - action: switch.turn_off')
        ons = first_arm_ons(BUSY_START)
        bound = 30.0 + 20.0 + 2.0
        cw, _s = run_restart_starting(BUSY_START, ons[2] + 0.05, 30.0, 10.0, rollback=U0 + 50, until=ST + 200,
                                      texts={"fps1": mutate(fps1, old, old.replace('"off"', '"lab_never"'),
                                                            "NC-HF02-2")})
        try:
            return hf_inv(cw, ["INV-HF-ARM-OFF"], grace_s=bound)
        finally:
            cw.close()
    negative_control("NC-HF02-2", "HF-02", "FPS1 startup recovery: the write-enable turn-off after a restart never runs",
                     "INV-HF-ARM-OFF", nc_hf02_2)

    def nc_hf03_1():
        old = "and now_a >= 0 and now_a == (attempts_before | float(-2))"
        cw = run_cut("fp", cut_spec("fp", "early"), 5.0, prior_attempt=True, until=ST + 200,
                     texts={"fps1": mutate(fps1, old, "and now_a >= 0", "NC-HF03-1")})
        try:
            return check_press_proof(cw.log)
        finally:
            cw.close()
    negative_control("NC-HF03-1", "HF-03", "FPS1 no-answer proof: the attempt-counter equality is dropped (attempts_before "
                     "1.0, early reset)",
                     "INV-HF-PRESS-PROOF", nc_hf03_1)
    for nc_id, dom, old, what in (
            ("NC-HF03-2", "fp", 'id(free_power_restore_requested) = true;\n                    ESP_LOGW("free_power", '
                                '"Free Power was ACTIVE at last shutdown', "Free Power S3 boot restore request removed"),
            ("NC-HF03-3", "dump", 'id(dump_restore_requested) = true;\n                    id(dump_last_end_reason).'
                                  'publish_state("ESP RESTARTED DURING LEASE',
             "Dump to Grid boot restore request removed")):
        def nc(old=old, dom=dom):
            fwd = L.load_fw(text=mutate(fwt, old, old.split("\n", 1)[1].lstrip(), nc_id))
            cw = run_reboot_active(dom, fwd=fwd)
            try:
                return fw_inv(cw, ["INV-NO-RESUME"])
            finally:
                cw.close()
        negative_control(nc_id, "HF-03", f"firmware on_boot: {what}", "INV-NO-RESUME", nc)

    def nc_hf05_1():
        old = ("               ('binary_sensor.ecco_clock_dongle_free_power_active', 'Free Power active'),\n"
               "               ('binary_sensor.ecco_clock_dongle_free_power_operation_in_progress', 'Free Power "
               "transaction in progress'),\n"
               "               ('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'Free Power snapshot pending "
               "restore'),\n")
        cw, _e = run_owner_edit_active(texts={"smr1": mutate(smr1, old, "", "NC-HF05-1")})
        try:
            return hf_inv(cw, ["INV-HF-SMR1-QUIET"])
        finally:
            cw.close()
    negative_control("NC-HF05-1", "HF-05", "SMR1 restore blocker: the three Free Power ownership entities (active, "
                     "transaction, snapshot) removed", "INV-HF-SMR1-QUIET", nc_hf05_1)

    def nc_hf05_2():
        old = ("changed the manual Free Power values\n                        at {{ now().strftime('%Y-%m-%d %H:%M') }}\n"
               "          # Any other change while owed is the owner's (or another tool's): never restore that field over "
               "it.\n          - conditions:\n              - condition: template\n                value_template: "
               "\"{{ state_now.startswith('OWED') and (states(written) | float(0)) > 0 }}\"")
        new = old.replace("state_now.startswith('OWED') and", "false and")
        cw = run_owner_edit_starting(S.E_PWR, 5000, texts={"smr1": mutate(smr1, old, new, "NC-HF05-2")})
        try:
            return hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])
        finally:
            cw.close()
    negative_control("NC-HF05-2", "HF-05", "SMR1 Free Power track: an owner change while owed is never dropped (owner "
                     "power 5000 W while STARTING)", "INV-HF-NO-FALSE-SUCCESS", nc_hf05_2)

    def nc_hf09_1():
        old = "                        - action: button.press\n                          continue_on_error: true\n"
        cw, _s = run_fault("fp", [(ST - 1, {"button.press": 1})], until=ST + 300,
                           texts={"fps1": mutate(fps1, old, "                        - action: button.press\n",
                                                 "NC-HF09-1")})
        try:
            return hf_inv(cw, ["INV-HF-ARM-OFF"])
        finally:
            cw.close()
    negative_control("NC-HF09-1", "HF-09", "FPS1: continue_on_error removed from the scheduled START press (the press "
                     "raises once)", "INV-HF-ARM-OFF", nc_hf09_1)
    fw_cache: dict = {}

    def no_disarm_fw():
        if "fw" not in fw_cache:
            old = ("                id(free_power_write_enable).turn_off();\n"
                   "                id(free_power_operation_in_progress) = true;\n")
            fw_cache["fw"] = L.load_fw(text=mutate(fwt, old, "                id(free_power_operation_in_progress) = "
                                                              "true;\n", "NC-HF09-2"))
        return fw_cache["fw"]

    def nc_hf09_2():
        cw, _s = run_fault("fp", [(ST + 3.0, {"switch.turn_off": 1})], until=ST + 120, fwd=no_disarm_fw())
        try:
            return hf_inv(cw, ["INV-HF-ARM-OFF"])
        finally:
            cw.close()
    negative_control("NC-HF09-2", "HF-09", "firmware START gate: the pass branch no longer disarms the Free Power write "
                     "enable (the run's closing turn_off raises)", "INV-HF-ARM-OFF", nc_hf09_2)
    cw, _s = run_fault("fp", until=ST + 120, fwd=no_disarm_fw())
    try:
        surv = (not hf_inv(cw, ["INV-HF-ARM-OFF"]) and fw_we(cw, "fp") is False
                and cw.last_result("fp").startswith("STARTED OK - 3000W for 10 min (attempt 1;"))
    finally:
        cw.close()
    # The survival holds on the SCHEDULED path only (run_fault: one scheduled FPS1 start, whose closing turn_off is the
    # backstop). On the owner-armed path (the owner arms and presses START; no package turn_off follows) the same mutation
    # leaves the firmware write enable ON after START (gate :8866-8867); it is killed elsewhere (B3 audit; verified in
    # memory against every lab suite): test_lab_selftest_firmware '...the same START with the arm turned on is admitted
    # and the firmware turns the arm off again' (the owner-armed firmware START), this suite's HF-09.4 'Free Power:
    # firmware truth - the real gate disarmed the write enable itself at the press ...', and the recorded trace digests of
    # every corpus document with a Free Power START (HF-02-a..c, HF-03-a,b, HF-05-a,b, HF-07-a..f, HF-08-b, ...).
    NC_RESULTS.append({"id": "NC-HF09-2b", "family": "HF-09", "mutation": "firmware START gate pass branch without its "
                       "write-enable disarm, no service error, scheduled path", "target": "INV-HF-ARM-OFF",
                       "outcome": "survived (defence in depth, scheduled path only)",
                       "detail": "the package's closing turn_off ends it off; the owner-armed path has no such backstop "
                                 "and is killed elsewhere (selftest_firmware arm-off check, HF-09.4 firmware truth, "
                                 "corpus trace digests)"})
    check("defence in depth (NC-HF09-2b, expected to survive on the scheduled path only): with only the firmware's own "
          "disarm removed and no service error, the package's closing turn_off still ends the write enable off (STARTED "
          "OK, INV-HF-ARM-OFF holds); the owner-armed path is killed elsewhere", surv)

    def nc_hf09_3():
        _r, txn = restoring_ref()
        cw, _s = run_fault("fp", [(txn[1] + 0.5, {"number.set_value": 1})], until=ST + 700,
                           texts={"smr1": mutate_after(smr1, "  - id: ecco_sched_restore_fp_restore\n",
                                                       "{% if k in ['done', 'restore'] and (c | float(-1)) == "
                                                       "(v | float(-2)) %}", "{% if k in ['done', 'restore'] %}",
                                                       "NC-HF09-3")})
        try:
            return hf_inv(cw, ["INV-HF-NO-FALSE-SUCCESS"])
        finally:
            cw.close()
    negative_control("NC-HF09-3", "HF-09", "SMR1 Free Power restore: the per-field read-back check of the result dropped "
                     "(the power restore write raises)", "INV-HF-NO-FALSE-SUCCESS", nc_hf09_3)


# =============================================================================================================================
# corpus replay
# =============================================================================================================================
def section_corpus() -> None:
    print("[corpus] the minimal replay documents of this suite replay OK with the _lab_trace engine")
    # HF-05-a is a PASS document since V0.1 (F-HF05-1 reclassified: RECLASSIFIED); it still pins the documented outcome
    fid_of = {"HF-02-a": "F-HF02-1", "HF-02-c": "F-HF02-2", "HF-02-d": "F-HF02-3", "HF-03-a": "F-HF03-1",
              "HF-03-c": "F-HF03-2",
              "HF-05-b": "F-HF05-2", "HF-09-a": "F-HF09-1"}
    for s in SCENARIOS:
        for cid in s["corpus"]:
            path = CORPUS_DIR / f"{cid}.json"
            if not path.is_file():
                check(f"corpus {cid}.json exists", False, str(path.name))
                continue
            doc = T.load_doc(path)
            res = T.replay(doc)
            check(f"corpus {cid}: replay ok ({'expectations only: SOURCE DRIFT' if res.drift else 'trace digest identical'})",
                  res.ok and S.LOCAL is FIXED_LOCAL and not H._OPEN, str(res.failed_expectations)[:300])
            want = FINDINGS[fid_of[cid]]["classification"] if cid in fid_of else "PASS"
            grade = FINDINGS[fid_of[cid]]["grade"] if cid in fid_of else "VERIFIED"
            # V0.1 (brief B6.6): scenario_priority = the scenario's priority; finding_priority = the finding's priority
            # (its root-cause group's) or null for a PASS document
            fpri = FINDINGS[fid_of[cid]]["priority"] if cid in fid_of else None
            check(f"corpus {cid}: classification {doc['classification']} / grade {doc['grade']} / tier coupled / "
                  "synthetic / scenario_priority / finding_priority match the tables", doc["classification"] == want
                  and doc["grade"] == grade and doc["tier"] == "coupled" and doc["synthetic"] is True
                  and doc.get("scenario_priority") == s["priority"] and doc.get("finding_priority", "?") == fpri,
                  f"{doc['classification']} {doc['grade']} {doc.get('scenario_priority')} {doc.get('finding_priority')}")


# =============================================================================================================================
# extended
# =============================================================================================================================
def section_extended() -> None:
    t_ext = time.perf_counter()
    print("[EXT-1] full early-reset sweep: Free Power and Dump to Grid x 14 down times (1..40 s), plus the two remaining "
          "Free Power in-transaction cut points (UNSUPPORTED basis)")
    section_hf03_cut([(dom, "early", float(d)) for dom in ("fp", "dump") for d in range(1, 41, 3)]
                     + [("fp", "A-data", 5.0), ("fp", "B-marker", 5.0)], label="extended sweep, ")
    print("[EXT-2] whole-site power-cut grid: Home Assistant down 5..180 s x dongle down 5..90 s")
    section_hf03_site([(a, b) for a in (5.0, 30.0, 60.0, 120.0, 180.0) for b in (5.0, 30.0, 90.0)])
    print("[EXT-3] F-HF02-1 with a 230 s ESPHome reconnect gap (the recovery's bounded wait times out)")
    cw, t_end = run_end_then_restart("fp", rollback=ST - 120, gap=230.0)
    try:
        v = hf_inv(cw, ["INV-HF-OWNER-INTENT"])
        finding("F-HF02-1", f"reconnect gap 230 s: second lease {cw.last_result('fp')[:60]}")
        check("finding-reproduces:F-HF02-1 (gap 230 s): the second session still starts once the dongle reconnects",
              invs(v) == ["INV-HF-OWNER-INTENT"] and len(lease_starts(cw, "fp")) == 2, str(v))
    finally:
        cw.close()
    print("[EXT-4] whole-site power cut during a scheduled FREE POWER (the analogue)")
    cw, t_cut = run_site_cut(60.0, 5.0, dom="fp")
    try:
        o = site_outcome(cw, "fp", t_cut)
        if o["new"]:
            finding("F-HF03-2", f"Free Power analogue: FPS1 recovery started a new lease ({o['last'][:58]})")
        check("Free Power analogue (HA down 60 s, dongle down 5 s): the firmware ended the lease (S3) and FPS1 started a "
              "new one for the rest of the window, its alert dismissed by the success; firmware invariants hold",
              o["new"] == 1 and not o["fw"] and o["last"].startswith("STARTED OK - 3000W") and o["missed"] == 1
              and o["notes_end"] == [], f"{o}")
    finally:
        cw.close()
    print("[EXT-5] dump_plant (MODEL plant) variant: a 3000 W scheduled Dump cut mid-window (+15 min)")
    cw, t_cut = run_site_cut(60.0, 5.0, plant=True, cut=ST + 900, until=ST + 1300)
    try:
        o = site_outcome(cw, "dump", t_cut)
        if o["new"]:
            finding("F-HF03-2", f"mid-window with the plant MODEL: {o['last'][:58]}")
        check("plant variant: the same mechanism mid-window - one new gated lease after the firmware's no-resume end",
              o["new"] == 1 and not o["fw"] and o["last"].startswith("STARTED OK - 3000W for 1"), f"{o}")
    finally:
        cw.close()
    print("[EXT-6] HF-09 analogues of the other domain, and the 'silent' policy of the retry-window outage")
    section_hf09_press(("dump",))
    section_hf09_arm(("fp",))
    section_hf09_arm_always(("fp",))
    section_hf09_noanswer(("dump",))
    section_hf09_left_on((), [("silent", 0.5, 700.0, WINDOW_FAILED)])
    section_hf09_sweep()
    info(f"extended sections runtime {time.perf_counter() - t_ext:.1f} s")


# =============================================================================================================================
# run
# =============================================================================================================================
section_anchors()
section_local_checkers()
section_hf02_starting()
section_hf02_active()
section_hf02_end_restart()
section_hf03_cut([("fp", "early", 1.0), ("fp", "early", 5.0), ("fp", "early", 15.0), ("fp", "early", 25.0),
                  ("fp", "early", 35.0), ("dump", "early", 5.0), ("fp", "C-write256", 5.0), ("fp", "D-active", 5.0),
                  ("dump", "C-write256", 5.0)])
section_hf03_guards()
section_hf03_active()
section_hf03_site([(5.0, 5.0), (60.0, 5.0), (120.0, 5.0), (60.0, 90.0)])
section_hf05_starting()
section_hf05_active()
section_hf05_restoring()
section_hf05_race()
section_hf09_press(("fp",))
section_hf09_arm(("dump",))
section_hf09_arm_always(("dump",))
section_hf09_smr1()
section_hf09_closing(("fp", "dump"))
section_hf09_noanswer(("fp",))
section_hf09_left_on(("fp", "dump"), [("raise", 1.2, 70.0, NO_ANSWER), ("silent", 1.2, 70.0, NO_ANSWER),
                                      ("raise", 0.5, 700.0, WINDOW_FAILED)])
section_hf09_boundary()
section_negative_controls()
section_corpus()
if EXTENDED:
    section_extended()
check("S.LOCAL is the sim's own fixed object and no CoupledWorld is left open at the end", S.LOCAL is FIXED_LOCAL
      and not H._OPEN)
# V0.1 finding register (brief B6.3; precedent test_lab_dst_rtc.section_register)
check("finding register: every FINDINGS entry was reproduced and printed, and no reclassified id (F-HF05-1) is a "
      "FINDINGS entry or printed a FINDING line", sorted(FINDING_SEEN) == sorted(FINDINGS)
      and not set(RECLASSIFIED) & (set(FINDINGS) | set(FINDING_SEEN))
      and all(f not in s["findings"] for s in SCENARIOS for f in RECLASSIFIED), str(FINDING_SEEN))
for _fid, _why in sorted(RECLASSIFIED.items()):
    info(f"reclassified: {_fid} -> {_why}")
print("[summary] scenarios")
for s in SCENARIOS:
    print(f"  info  {s['id']} {s['priority']} {s['classification']} grade {s['grade']} confidence {s['confidence']} "
          f"invariant {s['invariant']}: " + "; ".join(RESULTS[s["id"]]))
for fid in FINDING_SEEN:
    f = FINDINGS[fid]
    print(f"  info  {fid} {f['classification']} grade {f['grade']} confidence {f['confidence']} {f['priority']} "
          f"({f['invariant']}) severity: {f['severity'][:70]}")
for nc in NC_RESULTS:
    print(f"  info  {nc['id']} {nc['family']} -> {nc['target']}: {nc['outcome']}")
info("dedupe: no finding of this suite duplicates another suite's root cause (no 'DUPLICATE of' line); F-HF03-2 shares "
     "F-HF02-1's startup-recovery root cause inside this suite and stays its own counted entry (independent classification check: "
     "its evidence requirement and its false 'running' branch differ - the dongle reboot resets the start counters, so "
     "for Dump only the end reason survives); F-HF09-1 reaches the end state of the fixed D4 defect of docs/incidents/"
     "2026-10-12-scheduled-dump-to-grid-start-review.md (a write enable left ON after the run) by a different, "
     "unfixed path (every turn-off of the run fails); no other lab scenario suite injects a service fault (the coupling "
     "self-test checks only the adapter's offline 'raise' path)")
BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME = time.perf_counter() - T0
print(f"  info  runtime {RUNTIME:.1f} s ({'extended' if EXTENDED else 'quick'} mode)")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=FINDING_SEEN, finding_pins=REPRODUCED,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
