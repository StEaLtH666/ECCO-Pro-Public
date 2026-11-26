#!/usr/bin/env python3
"""HF-07 phantom durable obligation through Home Assistant: a scheduled START whose Phase-B marker commit is a false
negative, the second schedule admitted in the same runtime, a dongle power cut during the second lease, the PR41 dual
lockout, and what FPS1 / DGS1 / SMR1 and the firmware show for the next hour (and, extended, 25 h). Offline assurance lab
V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Tier: CoupledWorld (_lab_ha) - the REAL FPS1 / DGS1 / SMR1 packages in the HA sim, the REAL firmware (FirmwareWorld) through
RealDongle, London time, one UTC-true timeline. Nothing here decides what HA or the firmware does.

  prelude   (V0.1, B5 NVS used-key rule) a completed 1 min scheduled lease of the first domain at 11:52 through its own
            HA schedule (STARTED OK -> lease end -> verified restore RESTORED OK -> durable marker CLEAR, bank back at
            ORIGINAL, SMR1 RESTORED, no notification) stores that domain's marker key before any fault is injected; the
            main first schedule is armed at 11:55 and the fault at 11:55:30 (see PRE_START_LOCAL)
  mirror a  FPS1 Free Power 12:00 (60 min, 3000 W) -> FP Phase-B marker commit false negative (core nvs_policy
            'false_negative': the record lands, commit_record returns False) -> DGS1 Dump 12:30 (30 min, 3000 W, Stop
            SOC 20 %) admitted -> dongle power cut 12:40 -> FULL on_boot -> PR41 + SG-02 containment
  mirror b  DGS1 Dump 12:00 -> Dump Phase-B false negative -> FPS1 Free Power 12:30 admitted (ACTIVE) -> power cut 12:40
  then      owner presses End & Restore (both) and Dump Force Restore (with its arm) via HA, two graceful HA restarts,
            a second dongle reboot, observed until 13:40 (extended: 25 h)
  controls  fault-free twin (no phantom), a reboot AFTER the second lease completed, the phantom alone at a reboot, the
            chain without HA restarts (the notification-clearing assumption is not load-bearing), true START commit
            failures (marker / data not landed: the same FPS1 text, the marker left CLEAR by the prelude's record)
  negative  firmware PR41 disabled; both FP lockout write gates removed (and each alone on the watchdog path: defence in
            depth; the restore-script gate alone with the owner's End press: killed, NC2b-rs-end); SMR1 blocker
  controls  lease / snapshot terms removed; the Dump on_boot marker read forced to CLEAR (INV-BOOT-MIRROR, NC6a); the
            suite's settled-edge INV-HF-WINDOW view (hand-built logs); an altered corpus expectation; the corpus notes'
            dedupe relation
  core      the default firmware invariant set includes INV-BOOT-MIRROR (checked at every boot of both chains) and the
            hardened INV-NO-SILENT-OVERRIDE; neither reports anything in this scenario's chains
  corpus    corpus/HF-07-a .. HF-07-f.json (minimal replay documents, synthetic, each with the same prelude), replayed
            by section [10], which also replays each document's prelude alone up to the main schedule's arm (a real
            lease completed: marker CLEAR, RESTORED OK) and refuses a document with its prelude removed (NVS used-key
            rule)
  runtime   quick about 30 s on the development PC; ECCO_LAB_EXTENDED=1 / --extended adds a 25 h horizon, the measured
            bus, original 244 = 0, a reboot-instant sweep and the mirror twin (about 57 s more; printed as runtime_s)

Classification after the independent verification pass and the registry hardening (table FINDINGS_SPEC; every finding
keeps its 'finding-reproduces:<id>' check, so a fix fails loudly and forces re-classification):
  F-HF07-1  FINDING-NEW, counted: HA diagnostics gap, MEDIUM, in two mirror instances: FPS1 (mirror b) and DGS1 / 'Dump
            to Grid Active' (mirror a, formerly F-HF07-2, merged here: no FINDING line, its reproduction is a
            'finding-reproduces:F-HF07-1 (mirror a ...' pin) keep showing ACTIVE past the window under the PR41 lockout, no
            persistent notification for about 24 h; its firmware consequence (the held override) is F-FW01-2 (FW-01)
  F-HF07-2  FINDING-NEW, MERGED into F-HF07-1 (mirror a; V0.1, brief B6.3: one counted item with two mirror instances;
            precedent F-RT03-1 merged into F-HF08-3), not counted
  F-HF07-3  FINDING-NEW, DUPLICATE of F-FW06-1 (the START commit-failure text cascade; FPS1 copies it by design)
  F-HF07-4  FINDING-KNOWN:PR41-GHOST, DUPLICATE of F-FW01-1 (the Phase-B ghost defeats the other domain's admission gate
            until the next reboot; S4 2.10 blind spot 1 + the firmware PR41 comment)
  F-HF07-5  FINDING-NEW, DUPLICATE of F-FW01-3 (no lockout cause retained; designed, unimplemented S4 FB-B1 retention)
A DUPLICATE is printed 'DUPLICATE of <owner id>, not counted' and is excluded from the LAB-SUMMARY finding count (its
owning suite counts the root once); the pattern is test_lab_fw_durability.py's counted(). A MERGED variant (F-HF07-2)
prints no FINDING line: the run prints 'merged variant: F-HF07-2 -> merged into F-HF07-1 ...' and its reproduction is a
pin of the owner, so reproduced('F-HF07-1') needs both mirror pins.

MODEL dependence (all from the core, nothing new): the injected Phase-B false negative (nvs_policy 'false_negative': the
record lands, commit_record returns False) on a marker key the prelude stored first (the core's NVS USED-KEY RULE refuses
a commit fault on a never-stored key, _lab_fw module docstring; V0 injected on the never-used key, physically impossible
for the only remaining device route, audit 2026-10-19 r1 section 5.3), the dump_plant stand-in (keeps the Dump lease
alive in the main chains; the corpus documents run without it and cut 5 min into the lease), the never-busy bus
(BusModel windows=[]), the HA restart / reconnect / polled-sensor assumptions of _lab_ha, synthetic site values (L.SITE;
none are site values).
Fault realism (source reading, not executed): with the vendored ESPHome 2026.8.2 (anchor fw.min_version) sync() writes
every pending save, clears the whole queue unconditionally and returns failed == 0; commit_record is save() + that global
sync(), and the marker commit immediately follows a successful data commit in the same lambda (fw.fp_phase_b_commits,
fw.dump_phase_b_commits). The unrelated-pending-key route the firmware comment names (fw.unrelated_key_comment) therefore
cannot produce a marker false negative at this commit; only the marker key's own nvs_set_blob returning an error after the
new value landed remains (ESP-IDF ESP_ERR_NVS_REMOVE_FAILED on a flash-operation failure: REPORTED from the IDF API
documentation, no IDF source offline; it needs an earlier stored version of the marker key, which the B5 prelude
models, and only one ESP-IDF fault cell is modelled). Real-world reachability of every finding here is UNKNOWN; for the
PR41-lockout chain (F-HF07-1 / -2 / -4 / -5) it is likely very low.
Core issue worked around here (never edited): _lab_ha's window_overruns closes a lease at the fresh-RAM transient of an
on_boot run (RealDongle._mark during power_on's reboot_from logs act/snap False before the boot lambda reloads the durable
lease), so INV-HF-WINDOW misses an override held across a reboot; settled_events() keeps the last dongle.edge per (dom,
at, boot) before calling the core checker.
NOT covered: home-assistant/packages/ecco_system_health.yaml (its trigger template sensors use states[...] subscripts the
HA sim does not render; it is not one of the CoupledWorld packages) - by reading only (INFERRED) 'ECCO Health Free Power'
would show FAILED in mirror a (FP snapshot on, active off) and WARNING in mirror b (FP active on, the same as a normal
lease); no health check reads the Dump snapshot. Also not modelled (INFERRED by reading): the ECCO Pro dashboard (its
Overview hero turns ATTENTION on a recovery state other than NONE / ACCEPTED, anchor dash.fp_recovery_attention), the
staged Fallback Status package, the Energy Actions card (no button under RECOVERY BLOCKED, card.rule_d), phone push /
mobile notify. The firmware's Recovery State / Last End Reason / Export Containment entities are not in the coupled
world's HA view (the adapter maps only package-read entities); this suite reads them from firmware truth.
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
# V0.1 review (R3-3): HF-07-c and HF-07-e also fail an EXPECTATION under the phase patch, not only the digest
_PS_DIGEST_EXP = _PS_DIGEST + (
    "; in addition the document's 'writes' expectation is timeline-bound: since V0.1 it lists the used-key prelude's "
    "writes (the B5 completed-lease prelude) with their event sequence numbers and instants, which any other phase "
    "changes, so that expectation fails under the phase patch too (in every patched run measured; the directed "
    "checks held)")
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "corpus HF-07-a: id / tier / classification": _PS_DIGEST,
    "corpus HF-07-b: id / tier / classification": _PS_DIGEST,
    "corpus HF-07-c: id / tier / classification": _PS_DIGEST_EXP,
    "corpus HF-07-d: id / tier / classification": _PS_DIGEST,
    "corpus HF-07-e: id / tier / classification": _PS_DIGEST_EXP,
    "corpus HF-07-f: id / tier / classification": _PS_DIGEST,
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (LAB-SUMMARY: points = lines, ids = set)


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
import re  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _dump_sim as ds  # noqa: E402
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_ha as H  # noqa: E402

SUITE = "test_lab_ha_phantom"
FW = L.FW_REL
FPS1, DGS1, SMR1 = H.PACKAGES["fps1"], H.PACKAGES["dgs1"], H.PACKAGES["smr1"]
S4DOC = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
DASH = "home-assistant/dashboards/ecco_pro.yaml"
CARD = "frontend/ecco-energy-actions-card/"
LAB_HA = "registry/tests/assurance_lab/_lab_ha.py"
CORPUS_DIR = HERE / "corpus"

U0 = C.utc_of_local(2026, 10, 21, 11, 50)      # synthetic Wednesday (BST); the worlds start here
ST = C.utc_of_local(2026, 10, 21, 12, 0)       # the first scheduled start
ST2 = ST + 1800                                 # the second scheduled start, 12:30
CUT = ST + 2405                                 # the dongle power cut, 12:40:05 (10 min into the second lease; 7 s
                                                # after a 15 s watchdog slot, outside any projected controller write)
WARMUP = 120                                    # a warm dongle (polled sensors sampled; FPS1 needs the limit)
IDLE = H.BusModel(windows=[])
RR = ds.Durable.MARKER_RESTORE_REQUIRED
ORIG = dict(L.SITE["original"])
E_BLOCKER = "sensor.ecco_schedule_restore_blocker"
NOTIFY = "persistent_notification.create"
MIRRORS = {"a": {"first": "fp", "second": "dump", "tag": "fp.valid", "owner": (S.E_DUR, 40)},
           "b": {"first": "dump", "second": "fp", "tag": "dump.valid", "owner": (D.D_SOC, 30)}}
RUN = {"fp": {"minutes": 60, "power_w": 3000}, "dump": {"minutes": 30, "power_w": 3000, "stop_soc": 20}}
START_LOCAL = ("2026-10-21 12:00:00", "2026-10-21 12:30:00")
# B5 completed-lease prelude (V0.1; the core's NVS USED-KEY RULE, _lab_fw module docstring: an injected commit fault needs
# a key STORED EARLIER IN THIS RUN - for the marker false negative the only device route left, ESP-IDF
# ESP_ERR_NVS_REMOVE_FAILED, needs an earlier version of the key). Every chain first runs one real 1 min scheduled lease of
# the domain whose marker it injects on, through that domain's own HA schedule: START -> durable data + RESTORE_REQUIRED
# marker (fw.fp_phase_b_commits / fw.dump_phase_b_commits) -> override -> lease end -> verified restore -> marker CLEAR,
# then 'RESTORED OK' (FP: Phase D firmware :11225-11254, anchor fw.fp_restored_ok; Dump: clear_ok :20393-20419, anchor
# fw.dump_restored_ok). The main first schedule is armed only after the prelude completed (ARM1, 11:55) and the fault
# after that (POLICY_AT): armed earlier, the policy would hit the prelude's own RESTORE_REQUIRED marker commit.
PRE_START_LOCAL = "2026-10-21 11:52:00"
PRE_RUN = {"fp": {"minutes": 1, "power_w": 3000}, "dump": {"minutes": 1, "power_w": 3000, "stop_soc": 20}}
PRE_ARM = U0 + 60          # the prelude schedule is armed (the V0 first-arm instant)
PRE_DONE = U0 + 290        # the prelude is judged here (lease end 11:53, verified restore and SMR1 restore by about 11:54)
ARM1 = U0 + 300            # the main first schedule is armed (V0: U0 + 60)
POLICY_AT = U0 + 330       # the injected Phase-B fault is armed (V0: U0 + 90)
RESTORED_OK = "RESTORED OK - original inverter settings verified"   # anchors fw.fp_restored_ok / fw.dump_restored_ok
EMAP = H.dongle_entity_map()
HA_OF = {fid: hid for hid, (fid, _k) in EMAP.items()}
END_PRESS = {"fp": HA_OF["end_free_power_button"], "dump": HA_OF["end_dump_to_grid_button"]}
DUMP_RARM, DUMP_FORCE = HA_OF["dump_recovery_arm"], HA_OF["dump_force_restore_button"]
START_FIDS = frozenset(H.START_BUTTON.values())
DOM_TEXT = {"fp": "Free Power", "dump": "Dump to Grid"}
REC_STATE = {"fp": "free_power_recovery_state", "dump": "dump_recovery_state"}   # firmware text sensors (FW ids)
SCHED_NOTE = {"fp": "ecco_free_power_schedule", "dump": "ecco_dump_to_grid_schedule"}

# ---------------------------------------------------------------------------------------------------------------------------
# source anchors (text that must occur exactly once; line numbers are information only, re-derived at run time)
# ---------------------------------------------------------------------------------------------------------------------------
ANCHORS = {
    "fw.fp_start_failed": (FW, 'id(free_power_status).publish_state("START FAILED - could not durably commit the recovery '
                               'snapshot; nothing written");'),
    "fw.fp_activation_failed": (FW, 'id(free_power_status).publish_state("ACTIVATION WRITE FAILED - restoring saved '
                                    'snapshot");'),
    "fw.fp_end_ignored": (FW, 'else if (!id(free_power_snapshot_valid)) id(free_power_status).publish_state("END IGNORED - '
                              'no saved Free Power snapshot");'),
    "fw.dump_start_failed": (FW, 'id(dump_status).publish_state("START FAILED - could not capture/durably commit inverter '
                                 'snapshot; nothing written");'),
    "fw.dump_gate_fp_ram": (FW, "else if (id(free_power_active_persisted) || id(free_power_snapshot_valid) || "
                                "id(free_power_operation_in_progress)) id(dump_status).publish_state(\"REJECTED - Free Power "
                                "override/recovery owns inverter settings\");"),
    "fw.fp_gate_dump_ram": (FW, "else if (id(dump_active_persisted) || id(dump_snapshot_valid)) id(free_power_status)."
                                "publish_state(\"REJECTED - Dump to Grid override/recovery owns inverter settings\");"),
    # the admission conditions themselves (the two anchors above are their rejection texts)
    "fw.fp_gate_dump_ram_cond": (FW, "                !id(dump_active_persisted) &&\n                !id(dump_snapshot_valid) &&\n"
                                     "                // Fail-closed lockout: a durable recovery marker exists"),
    "fw.dump_gate_fp_ram_cond": (FW, "                !id(free_power_active_persisted) &&\n"
                                     "                !id(free_power_snapshot_valid) &&\n"
                                     "                !id(free_power_operation_in_progress) &&\n"
                                     "                // Register 244 standalone proof transaction: Dump also"),
    "fw.fp_phase_b_commits": (FW, "bool data_committed = ecco_durable::commit_record(\n"
                                  "                        ecco_durable::key_for(ecco_durable::FREE_POWER_DATA_TAG), data);\n"
                                  "                      bool marker_committed = false;"),
    "fw.dump_phase_b_commits": (FW, "bool marker_committed = data_committed && ecco_durable::commit_record(\n"
                                    "                        ecco_durable::key_for(ecco_durable::DUMP_TO_GRID_VALID_TAG), "
                                    "marker);"),
    "fw.unrelated_key_comment": (FW, "// UNRELATED pending key even though THIS record's own write"),
    "fw.pr41_preboot": (FW, "// domain's admission gate before the next reboot."),
    "fw.pr41_cause_intent": (FW, "// ESP_LOGE/status text specific to the dual-obligation cause,"),
    "fw.min_version": (FW, "  min_version: 2026.8.2"),
    # the B5 prelude's verified-restore success texts (published only after the durable marker CLEAR commit)
    "fw.fp_restored_ok": (FW, 'id(free_power_status).publish_state("RESTORED OK - original inverter settings verified");'),
    "fw.dump_restored_ok": (FW, 'id(dump_status).publish_state("RESTORED OK - original inverter settings verified");'),
    "fw.pr41_dump_locked": (FW, 'is also owned by Free Power; deliberate operator recovery required");\n'
                                '            id(dump_recovery_state).publish_state("LOCKED - durable recovery metadata '
                                'unavailable");'),
    "fw.fp_locked_neither": (FW, 'if (id(free_power_recovery_metadata_corrupt)) {\n            state_str = "LOCKED_NEITHER";'),
    "fw.dump_end_generic": (FW, 'if (id(dump_recovery_metadata_corrupt)) {\n'
                                '                  id(dump_status).publish_state(\n'
                                '                    "RECOVERY BLOCKED - durable recovery marker exists but its snapshot '
                                'data cannot be trusted"\n                  );'),
    "fw.sg02_contained": (FW, 'ESP_LOGW("dump_to_grid", "SG-02 containment: register 244 verified Zero Export");'),
    "fw.phase_b_comment": (FW, "// a Phase-B commit-helper sync() false negative can leave wrong:"),
    "fw.pr41_log": (FW, "DUAL DURABLE OBLIGATION (Free Power/Dump, 256-261) - Free Power and Dump-to-Grid both hold"),
    "fw.pr41_status": (FW, 'id(dump_status).publish_state("RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, '
                           '256-261): register set 256-261 is also owned by Free Power; deliberate operator recovery '
                           'required");'),
    "fw.fp_lockout_status": (FW, 'id(free_power_status).publish_state("RECOVERY BLOCKED - durable recovery marker exists '
                                 'but its snapshot data cannot be trusted (unreadable or invalid); inverter writes '
                                 'locked");'),
    "fw.dump_active_reload": (FW, "id(dump_active_persisted) = data.active_persisted != 0;"),
    "fw.fp_active_reload": (FW, "id(free_power_active_persisted) = data.active_persisted != 0;"),
    "fw.dump_active_sensor": (FW, "return id(dump_active_persisted);"),
    "fw.fp_active_sensor": (FW, "return id(free_power_active_persisted);"),
    "fw.dump_not_resumed": (FW, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not '
                                'resumed");'),
    "fw.fp_wd_corrupt_gate": (FW, "if (id(free_power_recovery_metadata_corrupt)) return false;"),
    "fw.fp_end_blocked": (FW, "if (id(free_power_recovery_metadata_corrupt)) id(free_power_status).publish_state(\"END "
                              "BLOCKED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data cannot be "
                              "trusted (unreadable or invalid); deliberate recovery required\");"),
    "fw.dump_force_refused": (FW, 'if (!id(dump_operator_needed)) id(dump_status).publish_state("REJECTED - Force Restore is '
                                  'only available while an operator decision is required");'),
    "fps1.failed_text": (FPS1, "FAILED TO START - {{ states('sensor.ecco_clock_dongle_free_power_status')[:120] }}"),
    "fps1.alert_title": (FPS1, 'title: "ECCO: scheduled Free Power did NOT start"'),
    "fps1.alert_retry_advice": (FPS1, "If time remains and the reason is cleared, use Free Power now in Energy Actions."),
    "fps1.alert_check_first": (FPS1, "If a start transaction began or the outcome is unconfirmed, check the Free Power "
                                     "status"),
    "fps1.readiness_dump": (FPS1, "{% if is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') or "
                                  "is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'on') %}{% set "
                                  "r.v = r.v + ['Dump to Grid owns the inverter settings'] %}{% endif %}"),
    "fps1.status_doc": (FPS1, "# ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE. FAILED and COMPLETED describe the"),
    "dgs1.failed_text": (DGS1, "FAILED TO START - {{ states('sensor.ecco_clock_dongle_dump_to_grid_status')[:120] }}"),
    "dgs1.alert_title": (DGS1, 'title: "ECCO: scheduled Dump to Grid did NOT start"'),
    "dgs1.readiness_fp": (DGS1, "{% if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') or "
                                "is_state('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'on') %}{% set r.v = "
                                "r.v + ['Free Power owns the inverter settings'] %}{% endif %}"),
    "dgs1.status_doc": (DGS1, "# ACTIVE / STARTING / ARMED / FAILED / COMPLETED / IDLE. FAILED and COMPLETED describe the"),
    "smr1.blocker_fp_snap": (SMR1, "('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'Free Power snapshot "
                                   "pending restore'),"),
    "smr1.blocker_dump_snap": (SMR1, "('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'Dump to Grid "
                                     "snapshot pending restore'),"),
    "smr1.blocker_fp_active": (SMR1, "('binary_sensor.ecco_clock_dongle_free_power_active', 'Free Power active'),"),
    "smr1.blocker_dump_active": (SMR1, "('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'Dump to Grid lease "
                                       "active'),"),
    "smr1.flags_are_ownership": (SMR1, "the snapshot / transaction / lease flags are the ownership."),
    "smr1.stale_title_fp": (SMR1, 'title: "ECCO - manual Free Power values NOT restored"'),
    "s4.ghost_invisible": (S4DOC, "A Phase-B ghost (commit false negative: NVS holds RR while RAM is clear) is invisible"),
    "s4.permanent": (S4DOC, '"Permanent" means that no assignment to false exists anywhere in the firmware.'),
    "s4.fb_b1_lockout_cause": (S4DOC, "| FB-B1 (retention) | `fp_lockout_cause`, `dump_lockout_cause`, "
                                      "`reg244_lockout_cause` (u8 Cause"),
    "s4.cause_codes": (S4DOC, "5 DUAL_S4, 6 DUAL_FP_DUMP."),
    "dash.fp_recovery_attention": (DASH, "const freeRecoveryAttention = !recoveryUnavailable(freeRecovery) && "
                                         "!recoverySettled(freeRecovery);"),
    "health.fp_state_consistency": ("registry/system_health_checks.yaml", "- id: free_power_state_consistency"),
    "card.rule_d": (CARD + "src/recoveryPresentation.ts", "// Rule D: firmware explicitly says recovery/writes are "
                                                          "blocked and requires"),
    "card.operator_recovery_pattern": (CARD + "src/dumpState.ts", "const OPERATOR_RECOVERY_PATTERN = /OPERATOR DECISION "
                                                                  "REQUIRED|ACCEPT REFUSED|Recovery Arm first/i;"),
    "lab.core_mark": (LAB_HA, "self.mark()   # the stretch before this op ends here"),
    "lab.core_lease_end": (LAB_HA, 'elif r["lease_start"] is not None and r["lease_end"] is None and not dt["act"] and not '
                                   'dt["snap"]:'),
    "lab.core_reboot_run": (LAB_HA, "fw.reboot_from(cap, down_s=0, nvs_fault=nvs_fault)"),
}

# ---------------------------------------------------------------------------------------------------------------------------
# the scenario and its findings (classification vocabulary of _lab_trace; evidence grade VERIFIED = executed here)
# ---------------------------------------------------------------------------------------------------------------------------
SCENARIOS = [{
    "id": "HF-07", "priority": "P1", "tier": "coupled",
    "title": "Phantom obligation through HA: FPS1 / DGS1 START with a Phase-B false negative, the other schedule admitted, "
             "dongle reboot, PR41 dual lockout; what FPS1 / DGS1 / SMR1 and the firmware show (and the mirror)",
    "ownership": "synthetic site (L.SITE ORIGINAL); the owner configures both schedules in HA and sets one manual value "
                 "first (mirror a: Free Power duration 40 min, mirror b: Dump Stop SOC 30 %); HA (FPS1 / DGS1 / SMR1) and "
                 "the dongle firmware are the only writers; no other Modbus master; the injected Phase-B marker false "
                 "negative is the only fault; after the lockout the owner presses End & Restore Now (both) and Dump "
                 "Force Restore (with its recovery arm) via HA",
    "invariant": "INV-HF-WINDOW (settled edges) + INV-LOCKOUT-QUIET + INV-HF-SMR1-QUIET + INV-NO-2ND-RESTORER + the HA "
                 "schedule status and a persistent notification reflect a firmware lockout the firmware will never "
                 "resolve on its own",
    "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high (mechanism); low (real-world occurrence)",
    "anchors": sorted(ANCHORS),
    "failure_outcome": "the second schedule is admitted over the phantom (INV-NO-2ND-RESTORER; documented PR41 pre-boot "
                       "residual); after the reboot PR41 locks both domains by design with an override live (b: Free "
                       "Power grid charge; a: 256-261 at the Dump ceiling, export contained); FPS1 / DGS1 keep showing "
                       "ACTIVE past the window although the firmware's own entities say LOCKED, and no persistent "
                       "notification names the lockout for about 24 h (then only SMR1 STALE about staged values); the "
                       "owner's HA recovery presses refuse (fail-closed) with texts that misstate the cause",
    "corpus": ["HF-07-a", "HF-07-b", "HF-07-c", "HF-07-d", "HF-07-e", "HF-07-f"],
    # the scenario's findings after the registry hardening and V0.1 (brief B6.3): one counted HA diagnostics finding
    # (FINDING-NEW, F-HF07-1) with two mirror instances, its mirror-a instance F-HF07-2 MERGED into it (no FINDING line);
    # three DUPLICATES whose root another suite owns (printed 'DUPLICATE of <owner id>, not counted'; reproduction kept)
    "findings": ["F-HF07-1", "F-HF07-2", "F-HF07-3", "F-HF07-4", "F-HF07-5"],
    "counted": ["F-HF07-1"],
    "merged": {"F-HF07-2": "F-HF07-1"},
    "duplicates": {"F-HF07-3": "F-FW06-1", "F-HF07-4": "F-FW01-1", "F-HF07-5": "F-FW01-3"},
    "cross_references": {"F-HF07-1": "F-FW01-2 (its firmware consequence)"},
}]
_PHANTOM_REACH = ("UNKNOWN, likely very low: needs a Phase-B marker commit that lands but reports failure. With the "
                  "vendored ESPHome 2026.8.2 (fw.min_version) sync() clears its whole pending queue and the marker "
                  "commit immediately follows a successful data commit in the same lambda (fw.fp_phase_b_commits / "
                  "fw.dump_phase_b_commits), so the unrelated-pending-key route of the firmware comment "
                  "(fw.unrelated_key_comment) cannot produce it at this commit; only the marker key's own nvs_set_blob "
                  "returning an error after the value landed remains (ESP-IDF ESP_ERR_NVS_REMOVE_FAILED on a "
                  "flash-operation failure; REPORTED from the IDF documentation, not checked offline; it needs an "
                  "earlier stored version of the marker key, i.e. an earlier lease of that domain - modelled by the B5 "
                  "completed-lease prelude; only one ESP-IDF fault cell is modelled). Then a second schedule in the "
                  "same runtime (likely once a phantom exists, INFERRED) and a dongle reboot inside the second lease "
                  "(30-60 min; power cut, OTA, Wi-Fi reboot timeout: plausible, INFERRED). Every step VERIFIED in this "
                  "harness")
FINDINGS_SPEC = {
    "F-HF07-1": {
        "title": "under the PR41 lockout FPS1 (mirror b) and DGS1 (mirror a; formerly F-HF07-2, merged here) keep showing "
                 "ACTIVE past the window, HA Free Power Active / Dump to Grid Active stay on, and no persistent "
                 "notification names the lockout for about 24 h (then only SMR1 STALE): one HA-side diagnostics gap in "
                 "two mirror instances; the held override itself is the documented fail-closed lockout (FW-01), whose "
                 "firmware consequence is F-FW01-2",
        "classification": "FINDING-NEW", "grade": "VERIFIED", "duplicate_of": None,
        "relation": "counted here (the HA diagnostics gap is this suite's own; its DGS1 mirror instance F-HF07-2 is merged "
                    "here); firmware consequence F-FW01-2 (FW-01: the PR41 dual lockout leaves the live Free Power "
                    "override applied past its end epoch, every operator surface refuses) - this finding is only what HA "
                    "shows of it; precondition F-HF07-4 = F-FW01-1",
        "confidence": "high (mechanism, reproduction, documentation search); low (real-world occurrence)",
        "severity": "diagnostics / operator awareness, MEDIUM: FPS1 ACTIVE past window_end and no lockout notification. "
                    "The held override (battery grid-charged, then held at 100 % with house load from grid until "
                    "out-of-band action; per-day cost bounded, duration unbounded; INFERRED, inverter not modelled) is "
                    "the consequence of the documented fail-closed PR41 lockout (FW-01), which HA neither causes nor can "
                    "end. Not export safety (244 stays 2). Not silent HA-wide: the firmware's Recovery State / status "
                    "texts and the ECCO Pro Overview hero show the lockout (INFERRED for the dashboard)",
        "anchors": ["fw.dump_phase_b_commits", "fw.dump_start_failed", "fw.fp_gate_dump_ram_cond", "fw.fp_active_reload",
                    "fw.pr41_log", "s4.permanent", "fw.fp_wd_corrupt_gate", "fw.fp_active_sensor", "fps1.status_doc",
                    "fw.fp_locked_neither", "dash.fp_recovery_attention", "health.fp_state_consistency"],
        "corpus": "HF-07-b",
    },
    "F-HF07-2": {
        "title": "mirror a: under the PR41 lockout DGS1 shows ACTIVE and HA 'Dump to Grid Active' stays on indefinitely "
                 "although the firmware ended the lease (not resumed) and its own entities report RECOVERY BLOCKED / "
                 "LOCKED; no persistent notification names the lockout for about 24 h",
        "classification": "FINDING-NEW", "grade": "VERIFIED", "duplicate_of": None, "merged_into": "F-HF07-1",
        "relation": "merged into F-HF07-1 (its DGS1 / 'Dump to Grid Active' mirror instance, mirror a; one HA-side repair "
                    "covers both); firmware root FW-01 (precondition F-HF07-4 = F-FW01-1; the lockout itself is "
                    "documented fail-closed behaviour)",
        "confidence": "high (mechanism, reproduction); low-medium (real-world occurrence, the F-HF07-1 precondition)",
        "severity": "diagnostics, LOW-MEDIUM: DGS1's schedule status (and SMR1's blocker text 'Dump to Grid lease "
                    "active') contradict the firmware's own lockout entities; no lockout notification. Not export safety "
                    "(244 = 2, contained). The 256-261 residue at the Dump ceiling (model-dependent value; slot 6 above "
                    "its ORIGINAL) is the documented fail-closed FW-01 outcome, not this finding's harm",
        "anchors": ["fw.dump_gate_fp_ram_cond", "fw.dump_active_reload", "fw.dump_not_resumed", "fw.pr41_status",
                    "fw.pr41_dump_locked", "fw.sg02_contained", "fw.dump_active_sensor", "dgs1.status_doc"],
        "corpus": "HF-07-a",
    },
    "F-HF07-3": {
        "title": "mirror a: FPS1 records and notifies 'FAILED TO START - END IGNORED - no saved Free Power snapshot' for "
                 "the phantom START while a durable RESTORE_REQUIRED marker exists; every surface its advice points to "
                 "says there is nothing to recover (coupled-tier view of F-FW06-1)",
        "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high", "duplicate_of": "F-FW06-1",
        "relation": "DUPLICATE of F-FW06-1 (FW-06, test_lab_fw_durability.py owns the root: the Free Power START "
                    "commit-failure text cascade; same repair locus); FPS1 copies the firmware status by design, so the HA "
                    "side adds no root of its own",
        "severity": "diagnostics (low): no inverter write, no gate / lease / restore decision affected; a manual Free "
                    "Power retry would re-snapshot unchanged registers; the harmful follow-on is F-HF07-4",
        "anchors": ["fw.fp_phase_b_commits", "fw.fp_start_failed", "fw.fp_activation_failed", "fw.fp_end_ignored",
                    "fps1.failed_text", "fps1.alert_retry_advice", "fps1.alert_check_first"],
        "corpus": "HF-07-c",
    },
    "F-HF07-4": {
        "title": "the HA binary sensors and the firmware START gates trust the same RAM mirror: after the phantom HA "
                 "shows the first domain idle, SMR1's blocker reads none, the other schedule's readiness raises nothing "
                 "and the firmware admits its START over the durable RESTORE_REQUIRED obligation (the firmware's "
                 "documented PR41 pre-boot residual; coupled-tier reproduction of F-FW01-1)",
        "classification": "FINDING-KNOWN:PR41-GHOST", "grade": "VERIFIED", "duplicate_of": "F-FW01-1",
        "relation": "DUPLICATE of F-FW01-1 (FW-01, test_lab_fw_obligations.py owns the root: a Phase-B marker false "
                    "negative leaves a ghost RESTORE_REQUIRED that the other domain's admission gate misses until the next "
                    "reboot); registered as PR41-GHOST (S4 2.10 blind spot 1, second reference the firmware on_boot PR41 "
                    "comment); the HA leg (binary sensors mirror the RAM flags) is by design",
        "confidence": "high (mechanism, reproduction, registry-id fit: PR41-GHOST is the exact record)",
        "severity": "latent precondition, no harm of its own: INV-NO-2ND-RESTORER is violated in letter, but the phantom "
                    "START wrote nothing, so both durable snapshots hold the same ORIGINAL; a reboot after the second "
                    "lease resolves the phantom with zero writes (control [7], HF-07-e). The harm needs a reboot inside "
                    "the second lease (the PR41 lockout: F-HF07-1 / -2 / -5, F-FW01-2). Do not double count with F-FW01-1",
        "anchors": ["fw.phase_b_comment", "fw.pr41_preboot", "fw.dump_gate_fp_ram_cond", "fw.fp_gate_dump_ram_cond",
                    "fw.dump_gate_fp_ram", "fw.fp_gate_dump_ram", "dgs1.readiness_fp", "fps1.readiness_dump",
                    "smr1.flags_are_ownership", "s4.ghost_invisible"],
        "corpus": "HF-07-d",
    },
    "F-HF07-5": {
        "title": "under the lockout every operator press reachable from HA refuses (fail-closed, zero writes) but the "
                 "texts misstate the cause: FP 'unreadable or invalid' for a readable record, the PR41 cause text "
                 "replaced (mirror a by SG-02 containment at boot, then by the Dump End refusal; mirror b by the Dump End "
                 "refusal), Force 'only available while an operator decision is required' (HA-reachable extension of "
                 "F-FW01-3)",
        "classification": "FINDING-NEW", "grade": "VERIFIED", "duplicate_of": "F-FW01-3",
        "relation": "DUPLICATE of F-FW01-3 (FW-01, test_lab_fw_obligations.py owns the root: PR41 retains no lockout cause, "
                    "so every refusal text names the wrong one; same repair, the designed S4 FB-B1 retention); this suite "
                    "re-verifies the HA-reachable press sequence (both mirrors)",
        "confidence": "high (text mechanism); medium (owner reachability of the raw presses)",
        "severity": "diagnostics / operator guidance (low): every refusal fails closed, zero writes (mirror a: only the "
                    "by-design SG-02 244 := 2); no gate affected",
        "anchors": ["fw.pr41_status", "fw.pr41_cause_intent", "fw.fp_lockout_status", "fw.fp_end_blocked",
                    "fw.sg02_contained", "fw.dump_end_generic", "fw.dump_force_refused", "s4.fb_b1_lockout_cause",
                    "s4.cause_codes", "card.rule_d", "card.operator_recovery_pattern"],
        "corpus": "HF-07-f",
    },
}
FINDINGS_SPEC["F-HF07-1"].update(
    mechanism="Dump Phase-B marker commit lands but returns False (fw.dump_phase_b_commits) -> 'START FAILED ... nothing "
              "written' (fw.dump_start_failed), RAM dump_snapshot_valid false, NVS RESTORE_REQUIRED -> HA shows Dump idle "
              "-> the FPS1 12:30 START is admitted (the FP gate reads only the Dump RAM mirror, fw.fp_gate_dump_ram_cond) "
              "and the FP override written -> power cut -> on_boot reloads both records (fw.fp_active_reload) -> PR41 "
              "sets both corrupt flags (fw.pr41_log); by design no firmware path clears them and the exit is "
              "out-of-band (s4.permanent); the FP watchdog gate (fw.fp_wd_corrupt_gate) and the restore precondition "
              "never let a restore run -> the override stays (FW-01, documented; its firmware consequence is F-FW01-2). "
              "NEW here is HA's view of it: 'Free "
              "Power Active' = active_persisted (fw.fp_active_sensor) -> FPS1 status ACTIVE with no window check "
              "(fps1.status_doc); FPS1 / DGS1 / SMR1 have no trigger on a firmware lockout, so no persistent "
              "notification names it (the first one after the lockout is SMR1 STALE at about 24 h, about staged "
              "values). The firmware's own entities do say LOCKED (Free Power Recovery State LOCKED_NEITHER, "
              "fw.fp_locked_neither; status RECOVERY BLOCKED), and the ECCO Pro Overview hero turns ATTENTION on that "
              "state (dash.fp_recovery_attention; INFERRED, not modelled). The designed health check "
              "free_power_state_consistency (health.fp_state_consistency) is not implemented. Its mirror-a instance "
              "(DGS1 / Dump to Grid Active after a Free Power Phase-B false negative, formerly F-HF07-2, merged here) is "
              "the same HA-side gap for Dump: see F-HF07-2's mechanism",
    reachability="trigger: nvs false_negative on the used Dump Phase-B marker (dump.valid, mirror b), then a dongle power "
                 "cut inside the admitted Free Power lease; device reachability: UNKNOWN pending the ESP-IDF host NVS "
                 "test. " + _PHANTOM_REACH,
    repair_scope="HA-side, read-only (description only): FPS1 (and DGS1) status templates map a STRUCTURED lockout signal "
                 "- the firmware Recovery State not NONE / ACCEPTED (Free Power Recovery State LOCKED_NEITHER, as the "
                 "Overview hero already does), or Active still on past the run's window_end plus a margin above the "
                 "measured HF-01 lease-tail overrun - to LOCKED, never ACTIVE; one notification-only automation raises "
                 "a persistent notification for that state that says do NOT reboot the dongle and points to the "
                 "out-of-band recovery (no retry advice). Do not key on free-text status prefixes (an End press "
                 "overwrites them, F-HF07-5; repo rule: the free-text status never decides). No new firmware sensor, no "
                 "write path, no gate change, no automatic End / disarm / reboot. Alternative locus: the designed "
                 "free_power_state_consistency health check plus one notification, leaving the schedule packages "
                 "unchanged. The lockout itself (no in-band reconciliation) stays FW-01 scope.",
    model_dependence="the injected nvs_policy false_negative (the only fault; on a marker key a completed prelude lease "
                     "stored first, B5 used-key rule); never-busy bus (the measured bus gives the "
                     "same end state, extended); synthetic site. NOT load-bearing: the HA-restart notification "
                     "clearing (the no-restart variant creates no notification after the lockout either, [3] / [4]). "
                     "Not modelled: the dashboard, the staged Fallback Status package, ecco_system_health.yaml, phone "
                     "push")
FINDINGS_SPEC["F-HF07-2"].update(
    mechanism="FP Phase-B false negative (fw.fp_phase_b_commits), DGS1 Dump admitted (the Dump gate reads only the FP RAM "
              "mirror, fw.dump_gate_fp_ram_cond), power cut during the Dump lease -> on_boot reloads dump_active_persisted "
              "(fw.dump_active_reload), forces the restore request and publishes 'ended, not resumed' "
              "(fw.dump_not_resumed) but does not clear active_persisted; PR41 locks both (fw.pr41_status; Dump to Grid "
              "Recovery State 'LOCKED - ...', fw.pr41_dump_locked) and SG-02 contains 244 := 2 (fw.sg02_contained); "
              "active_persisted is cleared only by a verified restore / marker clear / Accept, all refused under the "
              "lockout -> HA 'Dump to Grid Active' (fw.dump_active_sensor) on and DGS1 status ACTIVE (dgs1.status_doc) "
              "indefinitely. Root cause = FW-01 / F-HF07-4; the HA status mapping and the missing notification are the "
              "new part",
    reachability="trigger: nvs false_negative on the used Free Power Phase-B marker (fp.valid, mirror a), then a dongle "
                 "power cut inside the admitted Dump lease; device reachability: UNKNOWN pending the ESP-IDF host NVS "
                 "test. " + _PHANTOM_REACH + "; in the lab the Dump lease must still be live at the cut (telemetry noise "
                 "on, dump_plant for cuts more than about 5-10 min into the lease); a reboot after the lease completed "
                 "gives no lockout (control [7])",
    repair_scope="HA-side, read-only: the same mapping as F-HF07-1 for DGS1, keyed on Dump to Grid Recovery State "
                 "starting 'LOCKED' (fw.pr41_dump_locked) or Active on past window_end + margin, plus one notification "
                 "per lockout; not on the free-text dump_status (owner presses overwrite it, F-HF07-5). Do NOT change the "
                 "'Dump to Grid Active' binary sensor semantics: DGS1, FPS1, SMR1 and the TOU edit use it as a "
                 "conservative blocker. The 256-261 residue and the lockout itself are FW-01 / F-HF07-4 scope.",
    model_dependence="as F-HF07-1, plus the dump_plant stand-in in the main chain (the corpus runs without it; the 256-261 "
                     "residue value depends on the cut instant and the plant)")
FINDINGS_SPEC["F-HF07-3"].update(
    mechanism="FP data commit lands, marker commit lands but returns False (fw.fp_phase_b_commits) -> 'START FAILED - "
              "could not durably commit ...' (fw.fp_start_failed) -> the separate activation branch's else publishes "
              "'ACTIVATION WRITE FAILED - restoring saved snapshot' (fw.fp_activation_failed) and runs the restore, whose "
              "gate rejects (!snapshot_valid): 'END IGNORED - no saved Free Power snapshot' (fw.fp_end_ignored); "
              "free_power_failures counts 2. FPS1's 'began' branch copies status[:120] into its last result "
              "(fps1.failed_text) and the 'did NOT start' notification. Its advice is conditional - retry if the reason "
              "is cleared (fps1.alert_retry_advice), else check the Free Power status and recovery state first "
              "(fps1.alert_check_first) - and those say END IGNORED, Snapshot Valid off, Recovery State NONE. The "
              "firmware cascade is F-FW06-1 (FW-06); count the root once, the HA copy is by design",
    reachability="trigger: nvs false_negative on the used Free Power Phase-B marker (fp.valid; the phantom START); "
                 "device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                 "two parts: (1) the text cascade follows ANY Free Power START data or marker commit failure, true "
                 "negatives included (VERIFIED here for fp.valid / fp.data not_landed after a completed-lease prelude: "
                 "the same final text, the marker still CLEAR (the failed commit leaves the prelude's record), zero "
                 "writes after the prelude - accurate there, but it hides the commit-failure cause and counts 2 "
                 "failures); "
                 "(2) the contradiction with a durable RESTORE_REQUIRED marker needs the own-key marker false negative: "
                 + _PHANTOM_REACH.split(". Then")[0],
    repair_scope="firmware text-only, the same locus as F-FW06-1: in start_free_power_override make the commit-failure "
                 "branch terminal - the activation block's else does not run (no second failures++, no 'ACTIVATION WRITE "
                 "FAILED'), and restore_free_power_snapshot runs only when free_power_snapshot_valid is true (retry-reset "
                 "/ journal commit failures keep their real restore). The final text must say the commit outcome is "
                 "unconfirmed and a durable marker may exist: 'START FAILED ... nothing written' alone is also false "
                 "after a marker false negative. The root-cause fix is F-HF07-4's fail-closed RAM mirror. HA needs no "
                 "change (FPS1 copies the firmware status by design).",
    model_dependence="nvs_policy false_negative only (the true-failure variants use not_landed)")
FINDINGS_SPEC["F-HF07-4"].update(
    mechanism="a Phase-B marker false negative (fw.fp_phase_b_commits / fw.dump_phase_b_commits) leaves the RAM mirror "
              "clear while NVS holds RESTORE_REQUIRED; every load_record call is in on_boot, so no runtime path re-reads "
              "it. HA's binary sensors are those RAM mirrors; SMR1's blocker reads only them by design "
              "(smr1.flags_are_ownership) and DGS1 / FPS1 readiness read the same (dgs1.readiness_fp, "
              "fps1.readiness_dump); the firmware START gates read the other domain's RAM mirror "
              "(fw.dump_gate_fp_ram_cond, fw.fp_gate_dump_ram_cond) -> the second START writes 256-261 "
              "(INV-NO-2ND-RESTORER). Documented by the firmware itself as the PR41 pre-boot residual (fw.phase_b_comment, "
              "fw.pr41_preboot: the false negative defeats the other domain's admission gate before the next reboot; "
              "boot arbitration is the chosen bound) and by the S4 ghost blind spot (s4.ghost_invisible): the registered "
              "risk PR41-GHOST (anchor = s4.ghost_invisible, second reference = fw.phase_b_comment). N15's stale-ORIGINAL "
              "consequence does not occur here. HA is not wholly silent: the first schedule's 'did NOT start' "
              "notification is raised, but its text hides the obligation (F-HF07-3)",
    reachability="trigger: nvs false_negative on a used Phase-B marker (both mirrors); device reachability: UNKNOWN "
                 "pending the ESP-IDF host NVS test. " + _PHANTOM_REACH.split(". Then")[0]
                 + "; then a second START in the same runtime (likely with two daily schedules once a phantom exists, "
                   "INFERRED)",
    repair_scope="firmware, F-FW01-1's repair: in the FP and Dump START Phase B, when the data record committed but the "
                 "marker commit returns False, treat the marker as possibly landed - set the RAM mirror fail-closed "
                 "(snapshot_valid, marker RESTORE_REQUIRED, restore requested), still abort before any override write, "
                 "and let the domain's own existing restore clear it (FP: a verified no-op skip-write; Dump: its existing "
                 "blind restore of values captured seconds earlier). No runtime NVS read-back (it would be the "
                 "firmware's first runtime NVS probe, S4 2.2 probe collateral, and after REMOVE_FAILED old and new items "
                 "can coexist), and no lockout (that recreates the stranded PR41 state). No new write path, no gate "
                 "weakened; HA then sees the snapshot flag and every gate refuses; PR41 / S4 stay as the boot backstop; "
                 "HA needs no change.",
    model_dependence="nvs_policy false_negative only")
FINDINGS_SPEC["F-HF07-5"].update(
    mechanism="PR41 sets only the generic *_recovery_metadata_corrupt flags, records no cause and republishes only "
              "dump_status (fw.pr41_status), although its own comment wants a cause-specific text "
              "(fw.pr41_cause_intent). Every refusal keys on the flag: the FP boot and END BLOCKED texts say 'unreadable "
              "or invalid' for a record that loaded fine (fw.fp_lockout_status, fw.fp_end_blocked); mirror a: the SG-02 "
              "containment text (fw.sg02_contained) replaces the PR41 text about 13 s after boot with no owner action, "
              "then the Dump End refusal (fw.dump_end_generic) replaces that (CONTAINED stays on the containment "
              "sensor); mirror b: the Dump End refusal replaces the PR41 text directly; the PR41 text returns only at "
              "the next boot. Dump Force needs dump_operator_needed, which PR41 does not set (fw.dump_force_refused), so "
              "it answers 'only available while an operator decision is required' next to 'deliberate operator "
              "recovery required'. That no HA surface resolves the lockout and that the FP operator API is not on HA "
              "are documented by design (out-of-band exit, s4.permanent; the card's Rule D) and not part of the defect",
    reachability="trigger: nvs false_negative on a used Phase-B marker, then a dongle power cut (the PR41 lockout); "
                 "device reachability: UNKNOWN pending the ESP-IDF host NVS test. "
                 "deterministic once the PR41 lockout exists (inherits F-HF07-1 / -2's UNKNOWN, likely very low "
                 "precondition). The FP boot text needs no press. The Energy Actions card offers only Dump End under "
                 "RECOVERY BLOCKED; FP End and Dump Force are hidden by the card (card.rule_d, "
                 "card.operator_recovery_pattern; INFERRED, the card is not modelled) and need raw button-entity "
                 "presses. INFERRED, not executed: after a raw Force press the Dump status matches none of the card's "
                 "attention patterns, so the tile may fall back until the next republish",
    repair_scope="firmware text-only, reusing the designed S4 FB-B1 retention (s4.fb_b1_lockout_cause, cause 6 "
                 "DUAL_FP_DUMP, s4.cause_codes): a RAM-only u8 *_lockout_cause assigned once next to each corrupt-flag "
                 "set site; key the FP boot / START / END BLOCKED texts, the Dump Recovery State, the Dump End refusal "
                 "and the SG-02 containment text on the cause; PR41 also publishes a dual-obligation free_power_status; "
                 "the Force refusal tests the corrupt flag before dump_operator_needed (text only). Keep the 'RECOVERY "
                 "BLOCKED' prefix and the 'deliberate recovery required' / 'inverter writes locked' phrases the card's "
                 "Rule D and FPS1 / DGS1 rely on. No gate change, no Modbus or durable write; the pinned text tests need "
                 "updating. The reconciliation path itself is FW-01 scope (out-of-band by design).",
    model_dependence="none beyond the lockout chain (the texts come from synchronous firmware lambdas)")
# V0.1 merge record (brief B6.3; precedent test_lab_dst_rtc RECLASSIFIED 'F-RT03-1': 'merged into F-HF08-3'): a merged
# variant prints no FINDING line, keeps its ledger entry (merged_into) and is reproduced by its owner's pins
MERGED = {"F-HF07-2": "merged into F-HF07-1 (mirror a, the DGS1 instance of one HA-side diagnostics gap; one repair covers "
                      "both)"}
CORPUS = {"HF-07-a": "F-HF07-2", "HF-07-b": "F-HF07-1", "HF-07-c": "F-HF07-3", "HF-07-d": "F-HF07-4",
          "HF-07-e": None, "HF-07-f": "F-HF07-5"}
FOUND: list[str] = []
NEG: list[tuple] = []       # (id, mutation, target, outcome, detail)


def asc(v, n: int = 0) -> str:
    """ASCII-only, bounded text for printing (the packages' texts contain non-ASCII separators)."""
    s = str(v)
    s = s[:n] if n else s
    return s.encode("ascii", "backslashreplace").decode("ascii")


def finding(fid: str, text: str) -> None:
    """Print one FINDING line (its 'finding-reproduces:<id>' check follows): classification, and for a finding whose root
    another suite owns 'DUPLICATE of <owner id>, not counted' (pattern of test_lab_fw_durability.py's finding()). A MERGED
    variant never prints one (fail loud: its reproduction is a pin of its owner)."""
    if fid in MERGED:
        raise AssertionError(f"finding({fid}): a merged variant prints no FINDING line ({MERGED[fid]})")
    f = FINDINGS_SPEC[fid]
    dup = f"; DUPLICATE of {f['duplicate_of']}, not counted" if f["duplicate_of"] else ""
    print(T.finding_line(fid, asc(f"[{f['classification']}{dup}] {text}")))
    if fid not in FOUND:
        FOUND.append(fid)
        print(f"  info    {fid} relation: {asc(f['relation'])}")


def reproduced(fid: str) -> bool:
    """Every 'finding-reproduces:<fid> ...' check of this run passed (and at least one ran)."""
    pref = f"finding-reproduces:{fid} "
    return any(n.startswith(pref) for n in REPRODUCED) and not any(n.startswith(pref) for n in FAILURES)


def counted() -> list:
    """The findings this suite counts in LAB-SUMMARY: reproduced, not a duplicate of another suite's finding and not a
    merged variant (a merged variant is never in FOUND: it prints no FINDING line)."""
    return [fid for fid in FOUND if reproduced(fid) and not FINDINGS_SPEC[fid]["duplicate_of"] and fid not in MERGED]


def unsupported(uid: str, text: str) -> None:
    """One UNSUPPORTED line per unsupported point met (uid = the catalogue unsupported id); LAB-SUMMARY counts these."""
    UNSUPPORTED_POINTS.append(uid)
    print(T.unsupported_line(uid, asc(text)))


def mutate(text: str, old: str, new: str, what: str) -> str:
    n = text.count(old)
    if n != 1:
        raise L.LabHarnessError(f"mutant {what}: its anchor occurs {n} time(s), exactly 1 required")
    return text.replace(old, new)


# ---------------------------------------------------------------------------------------------------------------------------
# helpers over the merged log
# ---------------------------------------------------------------------------------------------------------------------------
def settled_events(events) -> list:
    """WORKAROUND (core issue, LAB_HA anchors 'lab.core_mark' / 'lab.core_reboot_run' / 'lab.core_lease_end'): an on_boot
    run marks the fresh RAM flags (act False, snap False) before the boot lambda reloads the durable lease, and logs them as
    a dongle.edge at the same projected instant as the reloaded state; window_overruns then closes the lease there. Keep
    only the LAST edge per (dom, at, boot): the firmware state the instant settles to. Everything else is the core's."""
    evs = list(events)
    last = {}
    for i, e in enumerate(evs):
        if e["kind"] == "dongle.edge":
            d = e["data"]
            last[(d["dom"], d["at"], d["boot"])] = i
    return [e for i, e in enumerate(evs) if e["kind"] != "dongle.edge"
            or last[(e["data"]["dom"], e["data"]["at"], e["data"]["boot"])] == i]


def boot_seq(cw, boot: int):
    """seq of the fw.boot event of boot `boot` (before its on_boot publishes), None if that boot never happened."""
    hit = [e["seq"] for e in cw.log.events(kind="fw.boot") if e["data"]["boot"] == boot]
    return hit[0] if hit else None


def owned_diff(fw) -> dict:
    return {a: fw.bank.get(a) for a in L.OWNED if fw.bank.get(a) != ORIG[a]}


def sample(cw) -> dict:
    vis = cw.ha_visible()
    return {"t": cw.t_utc - ST, "fps1": cw.schedule_status("fp"), "dgs1": cw.schedule_status("dump"),
            "smr1_fp": cw.smr1_state("fp"), "smr1_dump": cw.smr1_state("dump"),
            "blocker": cw.ha_state(E_BLOCKER), "notes": sorted(cw.notifications()),
            "fw_fp": cw.fw_status("fp"), "fw_dump": cw.fw_status("dump"),
            "ha": {k: vis[k] for k in ("fp_active", "fp_snapshot_valid", "dump_active", "dump_snapshot_valid")},
            "fw_rec": (str(cw.fw.sim.ent(REC_STATE["fp"]).state), str(cw.fw.sim.ent(REC_STATE["dump"]).state),
                       str(cw.fw.sim.ent("dump_containment_state_sensor").state)),
            "ha_rec": (cw.ha_state("sensor.ecco_clock_dongle_free_power_recovery_state"),
                       cw.ha_state("sensor.ecco_clock_dongle_dump_to_grid_recovery_state"))}


def lab_world(*, bus=IDLE, bank=None, fw_text=None, package_texts=None) -> H.CoupledWorld:
    kw = {"warmup_s": WARMUP}
    if bank:
        kw["bank"] = dict(bank)
    if fw_text is not None:
        kw["fw"] = L.load_fw(fw_text)
    return H.CoupledWorld(U0, bus=bus, fw_world_kwargs=kw, package_texts=package_texts)


def prelude_problem(p: dict, *, physical_only: bool = False) -> str:
    """'' when the B5 prelude `p` (prelude()) completed a real lease of its domain, else why not. PHYSICAL (what makes
    the later injection physically possible): the firmware ran the lease (an 'ACTIVE - VERIFIED OK' status) and then
    published the verified-restore success RESTORED_OK last (anchors fw.fp_restored_ok / fw.dump_restored_ok: published
    only after the durable marker CLEAR commit), the stored marker is CLEAR, the marker and data keys are STORED EARLIER
    (the core's nvs_stored_earlier), the lease wrote and the owned registers are back at their pre-prelude values, the
    RAM mirrors are clear. CLEAN (unless physical_only; asserted for the main chains and the control, not inside a run of
    a package mutant whose own effect may show in the prelude): the HA schedule says COMPLETED after 'STARTED OK', SMR1
    restored the owner's staged values, and nothing was notified or violated."""
    bad = []
    if not any(x.startswith("ACTIVE - VERIFIED OK") for x in p["hist"]) or not p["hist"] or p["hist"][-1] != RESTORED_OK:
        bad.append(f"statuses {p['hist']}")
    if p["marker"] != "CLEAR" or p["stored"] != ["valid", "data"]:
        bad.append(f"marker {p['marker']}, stored earlier {p['stored']}")
    if not p["writes"] or p["bank_after"] != p["bank_before"] or any(p["ram"].values()):
        bad.append(f"writes {p['writes']}, bank {p['bank_after']} vs {p['bank_before']}, RAM {p['ram']}")
    if physical_only:
        return "; ".join(bad)
    if p["sched"] != "COMPLETED" or not p["last"].startswith("STARTED OK") or not p["smr1"].startswith("RESTORED"):
        bad.append(f"HA {p['sched']} / {asc(p['last'], 40)!r} / SMR1 {asc(p['smr1'], 40)!r}")
    if p["notes"] or p["fwv"] or p["hf"]:
        bad.append(f"notifications {p['notes']}, invariants {p['fwv']} {p['hf']}")
    return "; ".join(bad)


def prelude(cw, dom: str) -> dict:
    """The B5 completed-lease prelude (module docstring, PRE_START_LOCAL): arm a 1 min scheduled lease of `dom` through
    its HA schedule at PRE_ARM, run to PRE_DONE and return what it left ('seq' = the last event seq of the prelude).
    Fail loud (LabHarnessError) when it did not complete a real lease (prelude_problem, physical part): the chain's
    injection would then not be physically possible."""
    fw = cw.fw
    before = {a: fw.bank.get(a) for a in L.OWNED}
    cw.arm_schedule(dom, PRE_START_LOCAL, at_utc=PRE_ARM, **PRE_RUN[dom])
    cw.run_until(PRE_DONE)
    view = fw.ha_view()
    p = {"dom": dom, "hist": fw.status_history(dom), "marker": fw.nvs_marker(dom),
         "stored": [k for k in ("valid", "data") if fw.nvs_stored_earlier(f"{dom}.{k}")], "writes": len(fw.writes()),
         "bank_before": before, "bank_after": {a: fw.bank.get(a) for a in L.OWNED},
         "ram": {k: view[f"{dom}_{k}"] for k in ("active", "snapshot_valid", "op")},
         "sched": cw.schedule_status(dom), "last": cw.last_result(dom), "smr1": cw.smr1_state(dom),
         "notes": sorted(cw.notifications()), "fwv": [v["inv"] for v in L.check_invariants(cw.log, world=fw)],
         "hf": [v["inv"] for v in cw.invariants()], "seq": cw.log[-1]["seq"]}
    why = prelude_problem(p, physical_only=True)
    if why:
        raise L.LabHarnessError(f"B5 prelude ({dom} lease {PRE_START_LOCAL}) did not complete a real lease before the "
                                f"injection: {why}")
    return p


def run_chain(m: str, *, fault: bool = True, cut=CUT, horizon_s: float = 3600, presses: bool = True,
              restarts: bool = True, second_reboot: bool = True, plant: bool = True, bus=IDLE, bank=None, fw_text=None,
              package_texts=None) -> dict:
    """One coupled run of mirror m (module docstring); returns the observations (the world is closed)."""
    spec = MIRRORS[m]
    first, second = spec["first"], spec["second"]
    out = {"mirror": m, "first": first, "second": second, "cut": cut,
           "window_end": {first: ST + RUN[first]["minutes"] * 60, second: ST2 + RUN[second]["minutes"] * 60}}
    cw = lab_world(bus=bus, bank=bank, fw_text=fw_text, package_texts=package_texts)
    try:
        if plant:
            cw.dump_plant()
        cw.owner_set(spec["owner"][0], spec["owner"][1], at_utc=U0 + 30)
        out["prelude"] = pre = prelude(cw, first)        # B5: the injected marker key is stored before the fault
        cw.arm_schedule(first, START_LOCAL[0], at_utc=ARM1, **RUN[first])
        if fault:
            cw.fw_action("nvs_policy", at_utc=POLICY_AT, tag=spec["tag"], state=RR, mode="false_negative", times=1)
        cw.run_until(ST + 300)
        fw = cw.fw
        out["first_hist"] = fw.status_history(first)[len(pre["hist"]):]     # the main START's statuses only
        out["first_last"] = cw.last_result(first)
        out["first_marker"] = fw.nvs_marker(first)
        out["first_ram_snap"] = fw.obligations()[first]["snap"]
        out["first_writes"] = len(fw.writes()) - pre["writes"]                # writes after the prelude
        out["fp_failures"] = int(fw.sim.g["free_power_failures"])
        out["notes_first"] = cw.notifications()
        out["first_rec"] = str(fw.sim.ent(REC_STATE[first]).state)          # firmware truth (not in the HA view)
        out["first_ha_snap"] = cw.ha_visible()[f"{first}_snapshot_valid"]
        cw.run_until(ST + 590)
        out["pre_second"] = {"ha": cw.ha_visible(), "blocker": cw.ha_state(E_BLOCKER),
                             "smr1_first": cw.smr1_state(first), "notes": sorted(cw.notifications())}
        cw.arm_schedule(second, START_LOCAL[1], at_utc=ST + 600, **RUN[second])
        cw.run_until(cut - 1)
        out["second_last"] = cw.last_result(second)
        out["pre_cut"] = sample(cw)
        out["second_wrote"] = len(cw.fw.writes()) > pre["writes"] + out["first_writes"]
        cw.reboot_dongle(cut, down_s=5.0)
        if presses:
            cw.owner_press(END_PRESS["fp"], at_utc=cut + 300)
            cw.owner_press(END_PRESS["dump"], at_utc=cut + 320)
            cw.owner_set(DUMP_RARM, True, at_utc=cut + 340)
            cw.owner_press(DUMP_FORCE, at_utc=cut + 345)
        if restarts:
            cw.restart_ha(cut + 600, 30)
            cw.restart_ha(cut + 1800, 30)
        if second_reboot:
            cw.reboot_dongle(cut + 2700, down_s=5.0)
        out["samples"] = []
        for dt in (120, 299, 400, 900, 2400, horizon_s):
            if dt <= horizon_s and cut + dt > cw.w.t:
                cw.run_until(cut + dt)
                out["samples"].append(sample(cw))
        fw, log = cw.fw, cw.log
        out["arms_end"] = (cw.ha_state(S.E_ARM), cw.ha_state(D.D_ARM))
        b1, b2 = boot_seq(cw, 1), boot_seq(cw, 2)
        out["b1"], out["b2"] = b1, b2
        out["writes_after"] = [(w["addr"], list(w["vals"]), w["dom"], w["boot"]) for w in fw.writes() if w["boot"] >= 1]
        out["corrupt"] = (fw.corrupt("fp"), fw.corrupt("dump"))
        out["markers"] = (fw.nvs_marker("fp"), fw.nvs_marker("dump"))
        out["containment"] = int(fw.sim.g["dump_containment_state"])
        out["hist_after"] = {d: [e["data"]["text"] for e in log.events(kind="fw.status")
                                 if e["data"]["dom"] == d and b1 is not None and e["seq"] > b1] for d in ("fp", "dump")}
        out["dump_end_reason"] = fw.status("dump_end")
        out["dump_hist_t"] = [(round(e["t_utc"] - cut, 1), e["data"]["text"]) for e in log.events(kind="fw.status")
                              if e["data"]["dom"] == "dump" and b1 is not None and e["seq"] > b1
                              and (b2 is None or e["seq"] < b2)]
        out["fw_truth"] = {k: str(fw.sim.ent(v).state) for k, v in (("fp_recovery", REC_STATE["fp"]),
                                                                     ("dump_recovery", REC_STATE["dump"]),
                                                                     ("containment", "dump_containment_state_sensor"))}
        out["end_reason_after"] = [e["data"]["text"] for e in log.events(kind="fw.status")
                                   if e["data"]["dom"] == "dump_end" and b1 is not None and e["seq"] > b1]
        out["owned_diff"] = owned_diff(fw)
        out["bank_tou"] = [fw.bank[a] for a in range(256, 262)]
        out["fw_status"] = {d: fw.status(d) for d in ("fp", "dump")}
        out["sched"] = {d: cw.schedule_status(d) for d in ("fp", "dump")}
        out["last"] = {d: cw.last_result(d) for d in ("fp", "dump")}
        out["smr1"] = {d: cw.smr1_state(d) for d in ("fp", "dump")}
        out["blocker"] = cw.ha_state(E_BLOCKER)
        out["notes_end"] = cw.notifications()
        out["ha_end"] = cw.ha_visible()
        truth = fw.ha_view()
        out["ha_matches_truth"] = all(out["ha_end"][k] == ("on" if truth[k] else "off") for k in (
            "fp_active", "fp_snapshot_valid", "dump_active", "dump_snapshot_valid", "fp_op", "dump_op"))
        calls = log.events(kind="ha.call")
        out["notify_before"] = [e["data"]["data"].get("notification_id") for e in calls
                                if e["data"]["svc"] == NOTIFY and (b1 is None or e["seq"] < b1)]
        out["notify_after"] = [(e["t_utc"] - cut, e["data"]["data"].get("notification_id"),
                                e["data"]["data"].get("title")) for e in calls
                               if e["data"]["svc"] == NOTIFY and b1 is not None and e["seq"] > b1]
        cmds = log.events(kind="dongle.cmd")
        out["smr1_cmds_before"] = [(e["data"]["e"], e["data"]["value"]) for e in cmds
                                   if e["data"]["by"] == "smr1" and (b1 is None or e["seq"] < b1)]
        out["smr1_cmds_after"] = [(e["data"]["e"], e["data"]["value"]) for e in cmds
                                  if e["data"]["by"] == "smr1" and b1 is not None and e["seq"] > b1]
        out["start_presses_after"] = [e["data"]["by"] for e in cmds if e["data"]["svc"] == "button.press"
                                      and e["data"]["fid"] in START_FIDS and b1 is not None and e["seq"] > b1]
        out["owner_cmds_after"] = sorted({e["data"]["fid"] for e in cmds if e["data"]["by"] == "owner"
                                          and b1 is not None and e["seq"] > b1})
        settled = settled_events(log)
        out["hf"] = H.check_hf_invariants(settled, world=cw)          # every INV-HF-* on the settled edges
        out["hf_raw"] = cw.invariants()                                # the core view (boot transient included)
        out["hf_window_settled"] = [v for v in out["hf"] if v["inv"] == "INV-HF-WINDOW"]
        out["hf_window_core"] = [v for v in out["hf_raw"] if v["inv"] == "INV-HF-WINDOW"]
        out["overruns_settled"] = H.window_overruns(settled, world=cw)
        fwv = L.check_invariants(log, world=fw)          # the default set (INV-BOOT-MIRROR included)
        out["fwv"] = [(v["inv"], v["seq"], v["detail"]) for v in fwv]
        out["boot_mirror"] = [(v["seq"], v["detail"]) for v in L.check_boot_mirror(log)]
        out["boots"] = [(e["data"]["boot"], e["data"]["obl"]["nvs"]["fp"], e["data"]["obl"]["nvs"]["dump"],
                         {d: [f for f in ("snap", "corrupt") if e["data"]["obl"][d][f]] for d in ("fp", "dump")})
                        for e in log.events(kind="fw.booted")]
        out["t_end"] = cw.t_utc
        out["digest"] = log.digest()
    finally:
        cw.close()
    return out


def viol_after(r: dict, inv: str, seq) -> list:
    return [v for v in r["fwv"] if v[0] == inv and seq is not None and v[1] > seq]


def timeline(r: dict) -> None:
    for s in r["samples"]:
        print(f"  info  {r['mirror']} +{s['t'] - (r['cut'] - ST):>6.0f} s after the cut: FPS1 {s['fps1']}, DGS1 "
              f"{s['dgs1']}; HA {s['ha']}; notifications {s['notes']}")
        print(f"  info       SMR1 fp {asc(s['smr1_fp'], 40)!r} / dump {asc(s['smr1_dump'], 40)!r}; blocker "
              f"{asc(s['blocker'], 70)!r}")
        print(f"  info       firmware fp {asc(s['fw_fp'], 60)!r} / dump {asc(s['fw_dump'], 60)!r}")


# =============================================================================================================================
def section_anchors() -> None:
    print("[0] source anchors (each text exactly once; line numbers are information only)")
    bad = []
    for name, (path, text) in sorted(ANCHORS.items()):
        n, line = T.anchor_count(path, text)
        if n != 1:
            bad.append((name, n))
        else:
            print(f"  info  anchor {name}: {path}:{T.anchor_line(path, text)}")
    check(f"every anchor of the scenario and its findings occurs exactly once ({len(ANCHORS)} anchors)", not bad, str(bad))
    used = {a for f in FINDINGS_SPEC.values() for a in f["anchors"]}
    keys = ("title", "classification", "grade", "confidence", "severity", "anchors", "corpus", "mechanism",
            "reachability", "repair_scope", "model_dependence", "relation")
    check("every finding names only declared anchors, has a corpus document id and states its mechanism, severity, "
          "grade, confidence, reachability, repair scope, model dependence and its relation to other suites' findings",
          used <= set(ANCHORS) and all(f["corpus"] in CORPUS and all(f.get(k) for k in keys) and "duplicate_of" in f
                                       for f in FINDINGS_SPEC.values()))
    for fid, f in FINDINGS_SPEC.items():
        dup = (f"DUPLICATE of {f['duplicate_of']}, not counted" if f["duplicate_of"]
               else f"merged into {f['merged_into']}, not counted" if f.get("merged_into") else "counted")
        print(f"  info  {fid}: {f['classification']} ({dup}); severity {f['severity'][:70]}; confidence "
              f"{f['confidence'][:40]}; corpus {f['corpus']}")
    cls = [T.parse_classification(f["classification"]) for f in FINDINGS_SPEC.values()]
    check("every finding classification is in the lab vocabulary (FINDING-KNOWN names a registered risk)",
          all(k in ("FINDING-NEW", "FINDING-KNOWN") for k, _r in cls)
          and T.parse_classification(SCENARIOS[0]["classification"])[0] in T.CLASSIFICATIONS)
    # dedupe table: a duplicate names another suite's finding (never one of this suite), and its relation says so
    fid_re = re.compile(r"^F-[A-Z]{2}[0-9]{2}-[0-9]+$")
    dups = {fid: f["duplicate_of"] for fid, f in FINDINGS_SPEC.items() if f["duplicate_of"]}
    # V0.1 (brief B6.3): a merged variant names a finding of THIS suite (its counted owner), never a duplicate too
    merged = {fid: f["merged_into"] for fid, f in FINDINGS_SPEC.items() if f.get("merged_into")}
    check("dedupe table: F-HF07-3 / -4 / -5 are DUPLICATES of F-FW06-1 / F-FW01-1 / F-FW01-3 (other suites own the root, "
          "not counted here), F-HF07-1 is counted, F-HF07-2 is merged into it (mirror a; MERGED record, no duplicate); "
          "each relation text states it; F-HF07-1 cross-references its firmware consequence F-FW01-2 and F-HF07-4 is "
          "FINDING-KNOWN:PR41-GHOST",
          dups == {"F-HF07-3": "F-FW06-1", "F-HF07-4": "F-FW01-1", "F-HF07-5": "F-FW01-3"}
          and merged == {"F-HF07-2": "F-HF07-1"} and not set(merged) & set(dups)
          and set(MERGED) == set(merged) and all(MERGED[f].startswith(f"merged into {o} ") for f, o in merged.items())
          and all(fid_re.match(d) and not d.startswith("F-HF07-") for d in dups.values())
          and all(FINDINGS_SPEC[fid]["relation"].startswith(f"DUPLICATE of {d} ") for fid, d in dups.items())
          and all(FINDINGS_SPEC[fid]["relation"].startswith(f"merged into {o} ") for fid, o in merged.items())
          and all(FINDINGS_SPEC[fid]["relation"].startswith("counted here") for fid in FINDINGS_SPEC
                  if fid not in dups and fid not in merged)
          and all(o in FINDINGS_SPEC and not FINDINGS_SPEC[o]["duplicate_of"] and o not in merged
                  for o in merged.values())
          and "F-FW01-2" in FINDINGS_SPEC["F-HF07-1"]["relation"] and "F-FW01-2" in FINDINGS_SPEC["F-HF07-1"]["title"]
          and FINDINGS_SPEC["F-HF07-4"]["classification"] == "FINDING-KNOWN:PR41-GHOST", f"{dups} {merged}")
    sc = SCENARIOS[0]
    check("the SCENARIOS row agrees with the findings table (findings, counted, merged, duplicates, the F-FW01-2 "
          "cross-reference)",
          sc["findings"] == sorted(FINDINGS_SPEC) and sc["duplicates"] == dups and sc["merged"] == merged
          and sc["counted"] == [fid for fid in sorted(FINDINGS_SPEC) if fid not in dups and fid not in merged]
          and sc["cross_references"]["F-HF07-1"].startswith("F-FW01-2 ")
          and all(FINDINGS_SPEC[fid]["corpus"] in sc["corpus"] for fid in FINDINGS_SPEC), str(sc["counted"]))
    st = T.known_risk_status()["PR41-GHOST"]
    g = T.KNOWN_RISKS["PR41-GHOST"]
    refs = T.KNOWN_RISK_REFS.get("PR41-GHOST", ())
    ref_rows = [(p, T.anchor_count(p, t)) for p, t in refs]
    s4_path, s4_text = ANCHORS["s4.ghost_invisible"]
    pb_path, pb_text = ANCHORS["fw.phase_b_comment"]
    pb_line = T.anchor_line(pb_path, pb_text)
    print(f"  info  PR41-GHOST ({g['class']}): {g['path']}:{st['line']}; second references "
          f"{[(p, c[1]) for p, c in ref_rows]}")
    check("F-HF07-4's registered risk PR41-GHOST is anchored exactly once, at the same S4 line as this suite's "
          "s4.ghost_invisible anchor (section 2.10 blind spot 1), and its second references (each exactly once) include "
          "this suite's fw.phase_b_comment line in the firmware", st["count"] == 1 and g["path"] == s4_path
          and s4_text.startswith(g["text"]) and st["line"] == T.anchor_line(s4_path, s4_text)
          and ref_rows and all(c[0] == 1 for _p, c in ref_rows) and (pb_path, (1, pb_line)) in ref_rows,
          f"{st} {ref_rows} {pb_line}")


def section_chain(m: str, r: dict) -> None:
    first, second = r["first"], r["second"]
    print(f"[{'1' if m == 'a' else '2'}] mirror {m}: scheduled {DOM_TEXT[first]} 12:00 with a Phase-B marker false negative, "
          f"scheduled {DOM_TEXT[second]} 12:30, dongle power cut 12:40, +1 h (presses, 2 HA restarts, a second reboot)")
    # -- the B5 completed-lease prelude (precondition of a physically possible injection) -------------------------------
    p = r["prelude"]
    print(f"  info  B5 prelude ({DOM_TEXT[first]} {PRE_START_LOCAL[11:16]}, {PRE_RUN[first]['minutes']} min, its own HA "
          f"schedule): firmware statuses {[asc(x, 48) for x in p['hist']]}; marker {p['marker']}; stored earlier "
          f"{[f'{first}.{k}' for k in p['stored']]}; {p['writes']} write(s); {('FPS1' if first == 'fp' else 'DGS1')} "
          f"{p['sched']} {asc(p['last'], 40)!r}; SMR1 {asc(p['smr1'], 40)!r}")
    check(f"{m}: B5 completed-lease prelude - a real scheduled {DOM_TEXT[first]} lease ran (ACTIVE - VERIFIED OK) and "
          f"ended with a verified restore ('{RESTORED_OK}', published after the durable marker CLEAR commit), marker "
          f"CLEAR, the {MIRRORS[m]['tag']} and {first}.data keys stored earlier, owned registers back at their "
          "pre-prelude values, RAM mirrors clear, the schedule COMPLETED, SMR1 RESTORED, no notification and no "
          "invariant violation - before the main schedule is armed and the fault injected", not prelude_problem(p),
          prelude_problem(p))
    # -- the phantom forms (precondition of the scenario) ---------------------------------------------------------------
    print(f"  info  firmware {first} status sequence after the prelude: {[asc(x, 70) for x in r['first_hist']]}")
    print(f"  info  {('FPS1' if first == 'fp' else 'DGS1')} last result: {asc(r['first_last'], 150)!r}")
    check(f"{m}: the phantom forms - durable {first} marker RESTORE_REQUIRED, RAM snapshot clear, nothing written (after "
          "the prelude)",
          r["first_marker"] == "RESTORE_REQUIRED" and r["first_ram_snap"] is False and r["first_writes"] == 0,
          f"{r['first_marker']} {r['first_ram_snap']} {r['first_writes']}")
    pre = r["pre_second"]
    first_ha = {k: pre["ha"][f"{first}_{k}"] for k in ("active", "snapshot_valid", "op")}
    print(f"  info  12:09:50 HA view of {first}: {first_ha}; SMR1 blocker {asc(pre['blocker'], 80)!r}; SMR1 {first} "
          f"{asc(pre['smr1_first'], 70)!r}; notifications {pre['notes']}")
    # -- F-HF07-4: the admission chain over the phantom (KNOWN: PR41-GHOST; DUPLICATE of F-FW01-1) ---------------------
    sec_pre = [v for v in r["fwv"] if v[0] == "INV-NO-2ND-RESTORER" and (r["b1"] is None or v[1] < r["b1"])]
    print(f"  info  {second} last result before the cut: {asc(r['second_last'], 110)!r}; INV-NO-2ND-RESTORER before the "
          f"reboot: {len(sec_pre)} write(s), first: {asc(sec_pre[0][2], 110) if sec_pre else None}")
    readiness = f"ecco_{'dump_to_grid' if second == 'dump' else 'free_power'}_schedule_readiness"
    adm = (all(v == "off" for v in first_ha.values()) and pre["blocker"] == "none"
           and pre["smr1_first"].startswith("RESTORED") and r["second_last"].startswith("STARTED OK")
           and readiness not in r["notify_before"] and r["second_wrote"] and pre["notes"] == [SCHED_NOTE[first]]
           and sec_pre and all(f"{second} wrote 256x6" in v[2] for v in sec_pre))
    finding("F-HF07-4", f"mirror {m}: HA's binary sensors show {first} idle (snapshot/active/op off), SMR1 blocker 'none' "
                        f"(SMR1 restored the staged {first} values), no readiness blocker, and the firmware admits the "
                        f"{second} START: {len(sec_pre)} write(s) of 256-261 while the {first} durable marker is "
                        "RESTORE_REQUIRED; the only HA alert is the first schedule's 'did NOT start' notice (documented "
                        "PR41 pre-boot residual; latent, the harm needs a reboot inside the second lease)")
    check(f"finding-reproduces:F-HF07-4 (mirror {m}: HA + firmware admission over the phantom; INV-NO-2ND-RESTORER by "
          f"the {second} domain before the reboot; only the {SCHED_NOTE[first]} notice raised)", bool(adm),
          str((first_ha, pre["blocker"], r["second_last"][:40], pre["notes"])))
    # -- the reboot: PR41 + SG-02 (guard decisions) ----------------------------------------------------------------------
    print(f"  info  firmware after boot 1: fp {[asc(x, 70) for x in r['hist_after']['fp']]}")
    print(f"  info                         dump {[asc(x, 70) for x in r['hist_after']['dump']]}")
    print(f"  info  ECCO writes after the lockout boot: {r['writes_after']}; containment state {r['containment']}; "
          f"owned registers off ORIGINAL at the end: {r['owned_diff']}")
    pr41 = any(x.startswith("RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)")
               for x in r["hist_after"]["dump"])
    check(f"{m}: the full on_boot fires PR41 - both domains corrupt-locked, both durable markers still RESTORE_REQUIRED, "
          "the dual-obligation text published (and again at the second reboot)",
          r["corrupt"] == (True, True) and r["markers"] == ("RESTORE_REQUIRED", "RESTORE_REQUIRED") and pr41
          and r["b2"] is not None, f"{r['corrupt']} {r['markers']}")
    want = [(244, [2], "dump", 1)] if m == "a" else []
    check(f"{m}: no ECCO write during the lockout except SG-02 containment ({'exactly one 244 := 2 after the Dump had set 0' if m == 'a' else 'none: 244 already 2'}), through "
          "the End / Force presses, two HA restarts and a second reboot; INV-LOCKOUT-QUIET holds",
          r["writes_after"] == want and not [v for v in r["fwv"] if v[0] == "INV-LOCKOUT-QUIET"], str(r["writes_after"]))
    check(f"{m}: the owner's HA recovery surfaces (End & Restore Now both, Dump recovery arm + Force Restore) reach the "
          "firmware and are refused: zero writes", set(r["owner_cmds_after"]) >= {"end_free_power_button",
                                                                                "end_dump_to_grid_button",
                                                                                "dump_force_restore_button"}
          and r["writes_after"] == want, str(r["owner_cmds_after"]))
    check(f"{m}: SMR1 writes no staged number after the lockout boot (its blocker names the lockout's lease / snapshot "
          "flags); INV-HF-SMR1-QUIET holds over the whole run", not r["smr1_cmds_after"]
          and not [v for v in r["hf"] if v["inv"] == "INV-HF-SMR1-QUIET"] and "snapshot pending restore" in r["blocker"],
          f"{r['smr1_cmds_after']} {asc(r['blocker'], 80)}")
    print(f"  info  SMR1 before the lockout wrote {r['smr1_cmds_before']} (RAM flags clear: the documented ownership "
          "rule, staging values only - no inverter write)")
    check(f"{m}: HA restarts and the second reboot start nothing: no START press after the lockout, both write enables "
          "off, INV-HF-ARM-OFF / INV-HF-OWNER-INTENT / INV-HF-ONE-LEASE hold",
          not r["start_presses_after"] and r["arms_end"] == ("off", "off")
          and not [v for v in r["hf"] if v["inv"] in ("INV-HF-ARM-OFF", "INV-HF-OWNER-INTENT", "INV-HF-ONE-LEASE")],
          f"{r['start_presses_after']} {r['arms_end']} {[v['inv'] for v in r['hf']]}")
    print(f"  info  INV-HF-* on the raw merged log (core view): {[v['inv'] for v in r['hf_raw']]}; on the settled edges: "
          f"{[v['inv'] for v in r['hf']]} (the raw INV-HF-OWNER-INTENT is the second reboot's boot transient read as a "
          "new lease after the owner's End press; the raw INV-HF-WINDOW misses the held override - core issue)")
    other = sorted({v[0] for v in r["fwv"]} - {"INV-NO-2ND-RESTORER"})
    check(f"{m}: the other firmware invariants of the default set hold on the merged log ("
          f"{', '.join(n for n in L.INVARIANTS if n != 'INV-NO-2ND-RESTORER')})",
          not other and "INV-BOOT-MIRROR" in L.INVARIANTS, str(other))
    print(f"  info  boots (boot, stored fp marker, stored dump marker, RAM mirror flags): {r['boots']}")
    locked = [b for b in r["boots"] if b[0] >= 1]
    check(f"{m}: INV-BOOT-MIRROR holds at every boot; the lockout boot and the second reboot each mirror both stored "
          "RESTORE_REQUIRED markers by the corrupt lockout (the same-runtime ghost before them is not judged by design)",
          not r["boot_mirror"] and len(locked) == 2
          and all(b[1] == b[2] == "RESTORE_REQUIRED" and "corrupt" in b[3]["fp"] and "corrupt" in b[3]["dump"]
                  for b in locked), f"{r['boot_mirror'][:2]} {r['boots']}")
    check(f"{m}: at the end the HA-visible binary sensors equal the firmware lambdas", r["ha_matches_truth"],
          str(r["ha_end"]))
    timeline(r)


def section_hidden_lockout(m: str, r: dict, rn: dict) -> None:
    first, second = r["first"], r["second"]
    sched = "FPS1" if second == "fp" else "DGS1"
    print(f"[{'3' if m == 'a' else '4'}] mirror {m}: what HA tells the owner about the lockout ({sched} owns the live "
          f"{DOM_TEXT[second]} override)")
    we = r["window_end"][second]
    held = r["hf_window_settled"]
    ov = [o for o in r["overruns_settled"] if o["dom"] == second]
    print(f"  info  {second} window end {C.iso_local(int(we))}; settled lease: start {ov[0]['lease_start'] if ov else None}, "
          f"end {ov[0]['lease_end'] if ov else None}; settled INV-HF-WINDOW: {[asc(v['detail'], 120) for v in held]}")
    print(f"  info  core INV-HF-WINDOW on the raw log: {[asc(v['detail'], 80) for v in r['hf_window_core']]} (the boot "
          "transient closes the lease at the reboot - core issue, worked around by settled_events)")
    print(f"  info  notifications created before the lockout boot: {r['notify_before']}; after it: {r['notify_after']}")
    s400 = next(x for x in r["samples"] if x["t"] == r["cut"] - ST + 400)     # boot 1, before any HA restart
    ft = r["fw_truth"]
    print(f"  info  firmware truth (not in the coupled world's HA view): at +400 s {s400['fw_rec']}; at the end "
          f"{ft}; HA sim view of the Recovery State entities {s400['ha_rec']}")
    held_end = r["t_end"] - we
    states_active = all(s[("fps1" if second == "fp" else "dgs1")] == "ACTIVE" for s in r["samples"])
    act_on = all(s["ha"][f"{second}_active"] == "on" for s in r["samples"])
    blocked = r["fw_status"]["fp"].startswith(("RECOVERY BLOCKED", "END BLOCKED - RECOVERY BLOCKED"))
    if m == "b":
        live = {a: r["owned_diff"].get(a) for a in (230, 232, 256, 268, 275)}
        ok = (len(held) == 1 and "fp run of 2026-10-21 12:30:00" in held[0]["detail"] and states_active and act_on
              and r["sched"]["fp"] == "ACTIVE" and blocked and r["notes_end"] == {} and r["notify_after"] == []
              and all(v is not None for v in live.values()) and r["owned_diff"].get(244) is None)
        finding("F-HF07-1", f"mirror b: FPS1 status ACTIVE and HA 'Free Power Active' on at every sample, {held_end:.0f} s "
                            f"past the 13:30 window end, while the firmware's own entities report the lockout (Recovery "
                            f"State {ft['fp_recovery']}, RECOVERY BLOCKED); no persistent notification after the lockout; "
                            f"the held Free Power override {live} is the documented fail-closed FW-01 lockout (its "
                            "firmware consequence is F-FW01-2; this finding is the HA diagnostics gap only)")
        check("finding-reproduces:F-HF07-1 (mirror b: under PR41 FPS1 ACTIVE and HA Free Power Active on past the window, "
              "zero notifications after the lockout, settled INV-HF-WINDOW violated, the FP override still live)", ok,
              f"{held} {r['sched']} {r['notes_end']} {r['notify_after']} {live}")
    else:
        same = len(set(r["bank_tou"])) == 1 and r["bank_tou"][0] != ORIG[256]
        ok = (len(held) == 1 and "dump run of 2026-10-21 12:30:00" in held[0]["detail"] and states_active and act_on
              and r["sched"]["dump"] == "ACTIVE" and r["dump_end_reason"] in ("ESP RESTARTED DURING LEASE - ended, not "
                                                                               "resumed", "manual End button")
              and "ESP RESTARTED DURING LEASE - ended, not resumed" in r["end_reason_after"]
              and r["notes_end"] == {} and r["notify_after"] == [] and same and r["owned_diff"].get(244) is None)
        # V0.1 (brief B6.3): mirror a is the DGS1 instance of F-HF07-1's HA diagnostics gap; F-HF07-2 is MERGED into
        # F-HF07-1 (no FINDING line; this pin of the owner reproduces it, so reproduced('F-HF07-1') needs both mirrors)
        print("  info  merged variant: F-HF07-2 -> merged into F-HF07-1 (mirror a): " + asc(
              f"DGS1 status ACTIVE and HA 'Dump to Grid Active' on at every sample for 1 h after the reboot, held "
              f"{held_end:.0f} s past the 13:00 window end, while the firmware's own entities say 'ESP RESTARTED DURING "
              f"LEASE - ended, not resumed', RECOVERY BLOCKED and {asc(ft['dump_recovery'], 48)!r} (export contained, "
              f"244 = 2); no persistent notification after the lockout; 256-261 left at the Dump ceiling "
              f"{r['bank_tou'][0]} W (FW-01 residue)"))
        check("finding-reproduces:F-HF07-1 (mirror a, the DGS1 instance merged from F-HF07-2: DGS1 ACTIVE / Dump Active "
              "on after the lease was ended and locked, zero notifications after the lockout, settled INV-HF-WINDOW "
              "violated, 256-261 at the Dump ceiling)", ok,
              f"{held} {r['sched']} {r['notes_end']} {r['bank_tou']} {r['dump_end_reason']}")
    rec = s400["fw_rec"]
    check(f"{m}: documented behaviour - the firmware's own entities report the lockout (structured signals a repair can "
          "key on; not in the coupled world's HA view): Free Power Recovery State LOCKED_NEITHER, Dump to Grid Recovery "
          f"State 'LOCKED - ...', both statuses RECOVERY BLOCKED at the end, Export Containment "
          f"{'CONTAINED' if m == 'a' else 'NOT_NEEDED'} during boot 1",
          rec[0] == "LOCKED_NEITHER" and rec[1].startswith("LOCKED - ") and ft["fp_recovery"] == "LOCKED_NEITHER"
          and ft["dump_recovery"].startswith("LOCKED - ") and r["fw_status"]["fp"].startswith("RECOVERY BLOCKED")
          and r["fw_status"]["dump"].startswith("RECOVERY BLOCKED")
          and rec[2].startswith("CONTAINED" if m == "a" else "NOT_NEEDED"), f"{rec} {ft}")
    gone = r["samples"][0]["notes"] and not r["samples"][-1]["notes"]
    check(f"{m}: the only HA alert of the whole chain is the START-failure notification of the phantom START, raised "
          "before the lockout and cleared by the first HA restart (HA does not restore persistent notifications)",
          gone and len(set(r["notify_before"])) == 1 and r["notify_after"] == [], f"{r['notify_before']} "
                                                                                  f"{[s['notes'] for s in r['samples']]}")
    check(f"{m}: without the HA restarts (the notification-clearing ASSUMPTION is not load-bearing) no notification is "
          f"created after the lockout either; the only one present at the end is the pre-lockout {SCHED_NOTE[first]} "
          f"alert about the phantom START, and {sched} is still ACTIVE", rn["notify_after"] == []
          and sorted(rn["notes_end"]) == [SCHED_NOTE[first]] and rn["sched"][second] == "ACTIVE"
          and rn["corrupt"] == (True, True), f"{rn['notify_after']} {sorted(rn['notes_end'])} {rn['sched']}")
    check(f"{m}: SMR1 keeps the {second} obligation OWED (waiting on the lockout flags) for the whole hour, never STALE "
          "inside 24 h (documented SMR1-STALE-24H rule)", r["smr1"][second].startswith("OWED")
          and all(s[f"smr1_{second}"].startswith("OWED") for s in r["samples"]), asc(r["smr1"][second], 80))


# The Free Power START's status cascade after the B5 prelude (fw.fp_start_failed, fw.fp_activation_failed,
# fw.fp_end_ignored). V0 compared the whole history from the boot, so its list began with the boot status 'Inactive'; with
# the prelude the statuses before this START are the prelude's own (checked by prelude_problem, ending RESTORED_OK) and
# the comparison starts at this START.
CASCADE = ["STARTING - taking fresh inverter snapshot",
           "START FAILED - could not durably commit the recovery snapshot; nothing written",
           "ACTIVATION WRITE FAILED - restoring saved snapshot", "END IGNORED - no saved Free Power snapshot"]


def first_start(tag: str, state, mode: str) -> dict:
    """Mirror a's scheduled Free Power START alone, after the B5 completed-lease prelude, with one injected NVS outcome
    (core nvs_policy), to 12:05; hist and writes count from the end of the prelude."""
    cw = lab_world()
    try:
        cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)
        pre = prelude(cw, "fp")
        cw.arm_schedule("fp", START_LOCAL[0], at_utc=ARM1, **RUN["fp"])
        cw.fw_action("nvs_policy", at_utc=POLICY_AT, tag=tag, state=state, mode=mode, times=1)
        cw.run_until(ST + 300)
        fw = cw.fw
        return {"hist": fw.status_history("fp")[len(pre["hist"]):], "last": cw.last_result("fp"),
                "marker": fw.nvs_marker("fp"), "writes": len(fw.writes()) - pre["writes"],
                "fails": int(fw.sim.g["free_power_failures"]), "notes": sorted(cw.notifications()),
                "prelude": prelude_problem(pre)}
    finally:
        cw.close()


def section_report_text(r: dict) -> None:
    print("[5] mirror a: the phantom START as FPS1 reports it (coupled-tier view of F-FW06-1)")
    note = r["notes_first"].get("ecco_free_power_schedule", {})
    msg = note.get("message", "")
    ok = (r["first_hist"] == CASCADE and r["first_marker"] == "RESTORE_REQUIRED"
          and r["first_last"].startswith("FAILED TO START - END IGNORED - no saved Free Power snapshot")
          and "END IGNORED - no saved Free Power snapshot" in msg and "use Free Power now in Energy Actions" in msg
          and "check the Free Power status" in msg and r["first_rec"] == "NONE" and r["first_ha_snap"] == "off"
          and r["fp_failures"] == 2)
    print(f"  info  free_power_failures after the one START: {r['fp_failures']}; notification title "
          f"{asc(note.get('title'))!r}; Free Power Recovery State {r['first_rec']!r}; HA Snapshot Valid "
          f"{r['first_ha_snap']}")
    finding("F-HF07-3", "mirror a: FPS1 last result and its 'did NOT start' notification read 'FAILED TO START - END "
                        "IGNORED - no saved Free Power snapshot' while the durable FP marker is RESTORE_REQUIRED; the "
                        "notice's conditional advice points to the status (END IGNORED) and recovery state (NONE), which "
                        "both say nothing to recover; the cascade counts 2 failures for one START (the coupled-tier view "
                        "of F-FW06-1's root)")
    check("finding-reproduces:F-HF07-3 (exact firmware cascade, FPS1 last result and notification text, durable marker "
          "RESTORE_REQUIRED, Recovery State NONE, HA Snapshot Valid off, free_power_failures == 2)", ok,
          f"{r['first_hist']} {asc(r['first_last'], 90)} {r['first_rec']} {r['first_ha_snap']}")
    rows = {}
    for tag, mode in (("fp.valid", "not_landed"), ("fp.data", "not_landed")):
        v = first_start(tag, RR if tag == "fp.valid" else None, mode)
        rows[f"{tag} {mode}"] = (v["hist"] == CASCADE, v["marker"], v["writes"], v["fails"], asc(v["last"], 60),
                                 v["notes"], v["prelude"])
    print(f"  info  true START commit failures (after the B5 prelude): {rows}")
    # B5: both not_landed keys were stored by the prelude (the core refuses a commit fault on a never-stored key), so the
    # durable marker reads the prelude's CLEAR record, not V0's ABSENT: a failed commit leaves the stored record untouched
    # (ecco_durable::commit_record = save() + sync(), returning false without erasing the earlier version,
    # firmware/include/ecco_durable_snapshot.h:93-99; mirrored by registry/tests/_dump_sim.py:284-287), the data-commit
    # failure never attempts the marker (fw.fp_phase_b_commits), and CLEAR, like ABSENT, means no recovery obligation.
    check("control: a TRUE Free Power START commit failure (marker or data record not landed) after the completed-lease "
          "prelude gives the same cascade and the same FPS1 text with the marker still the prelude's CLEAR (no "
          "obligation) and zero writes after the prelude - the text is accurate there (it hides the cause and counts 2 "
          "failures, F-FW06-1); only the marker false negative makes it contradict durable state",
          all(x[0] and x[1] == "CLEAR" and x[2] == 0 and x[3] == 2
              and x[4].startswith("FAILED TO START - END IGNORED - no saved Free Power snapshot")
              and x[5] == ["ecco_free_power_schedule"] and x[6] == "" for x in rows.values()), str(rows))


def _kind(text: str) -> str:
    for k, prefix in (("pr41", "RECOVERY BLOCKED - dual durable obligation (Free Power/Dump, 256-261)"),
                      ("contained", "RECOVERY BLOCKED - Dump to Grid recovery obligation still OUTSTANDING (snapshot "
                                    "cannot be trusted); export CONTAINED"),
                      ("generic", "RECOVERY BLOCKED - durable recovery marker exists but its snapshot data cannot be "
                                  "trusted"),
                      ("deferred", "RESTORE DEFERRED - outstanding Dump to Grid snapshot found at boot"),
                      ("force", "REJECTED - Force Restore is only available while an operator decision is required")):
        if text.startswith(prefix):
            return k
    return "other"


def section_operator_texts(ra: dict, rb: dict) -> None:
    print("[6] the operator presses reachable from HA under the lockout: refused, and what their texts say "
          "(HA-reachable extension of F-FW01-3)")
    fp_end = "END BLOCKED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data cannot be trusted " \
             "(unreadable or invalid); deliberate recovery required"
    force = "REJECTED - Force Restore is only available while an operator decision is required"
    want_before = {"a": ["deferred", "pr41", "contained"], "b": ["deferred", "pr41"]}
    rows = {}
    for r in (ra, rb):
        m, h = r["mirror"], r["hist_after"]
        s = next(x for x in r["samples"] if x["t"] == r["cut"] - ST + 400)     # after the presses, before any restart
        seq = r["dump_hist_t"]                                                 # boot 1 only, (s after the cut, text)
        before = [_kind(x) for t, x in seq if t < 320]                         # the Dump End press is at cut + 320
        after = [_kind(x) for t, x in seq if t >= 320]
        print(f"  info  mirror {m} dump status during boot 1 (s after the cut): {[(t, _kind(x)) for t, x in seq]}")
        print(f"  info  mirror {m} +400 s (after the presses): fp {asc(s['fw_fp'], 90)!r}; dump {asc(s['fw_dump'], 90)!r}")
        print(f"  info  mirror {m} at the end (after the second reboot republished the boot texts): dump "
              f"{asc(r['fw_status']['dump'], 90)!r}")
        rows[m] = (fp_end in h["fp"], before == want_before[m], after == ["generic", "force"], s["fw_dump"] == force,
                   s["fw_fp"] == fp_end, r["fw_status"]["dump"].startswith("RECOVERY BLOCKED - dual durable obligation"))
    ok = all(all(v) for v in rows.values())
    finding("F-HF07-5", "both mirrors: FP End -> 'END BLOCKED ... (unreadable or invalid)' (the record is readable; the "
                        "cause is the dual obligation); the PR41 'dual durable obligation' text is replaced - mirror a by "
                        "the SG-02 containment text with no owner action, then by the Dump End refusal's generic "
                        "'snapshot data cannot be trusted'; mirror b directly by the Dump End refusal - until the next "
                        "boot; Force answers 'only available while an operator decision is required' next to "
                        "'deliberate operator recovery required'")
    check("finding-reproduces:F-HF07-5 (exact refusal texts in both mirrors; the boot-1 Dump status sequence: a = "
          "deferred, PR41, SG-02 containment, then End generic, Force refused; b = deferred, PR41, then End generic, Force "
          "refused; the PR41 text back only after the second reboot)", ok, str(rows))


def section_controls() -> None:
    print("[7] controls: the fault-free twin; a reboot after the second lease completed; the phantom alone at a reboot")
    r = run_chain("a", fault=False, cut=CUT, horizon_s=600, presses=False, restarts=False, second_reboot=False)
    print(f"  info  twin: FPS1 {asc(r['last']['fp'], 60)!r}; DGS1 {asc(r['last']['dump'], 100)!r}; firmware fp "
          f"{asc(r['fw_status']['fp'], 60)!r}")
    check("twin (no fault): FPS1 STARTED OK, DGS1's own arm-time TOU walk REFUSES the Dump (the live FP override shows "
          "every slot as grid charge), the reboot during the FP lease restores it (RESTORED OK, ORIGINAL, markers clear), "
          "no lockout and no invariant violation - the phantom is what lets the second schedule in",
          r["last"]["fp"].startswith("STARTED OK") and r["last"]["dump"].startswith("REJECTED - window overlaps a TOU "
                                                                                    "slot")
          and r["fw_status"]["fp"].startswith("RESTORED OK") and r["owned_diff"] == {} and r["corrupt"] == (False, False)
          and not r["fwv"] and not r["hf"], f"{r['last']} {r['fwv'][:2]}")
    r = run_chain("a", cut=ST + 75 * 60, horizon_s=600, presses=False, restarts=False, second_reboot=False)
    print(f"  info  reboot at 13:15 (Dump lease completed 13:00): firmware fp after boot "
          f"{[asc(x, 60) for x in r['hist_after']['fp']]}; writes after the boot {r['writes_after']}")
    check("reboot AFTER the Dump lease completed: no dual obligation, no lockout; the lone FP phantom is classified at "
          "boot and restored with zero writes (live state equals its ORIGINAL), markers CLEAR, DGS1 COMPLETED",
          r["corrupt"] == (False, False) and r["markers"] == ("CLEAR", "CLEAR") and r["writes_after"] == []
          and r["fw_status"]["fp"].startswith("RESTORED OK") and r["owned_diff"] == {}
          and r["sched"]["dump"] == "COMPLETED", f"{r['markers']} {r['writes_after']} {r['sched']}")


# ---------------------------------------------------------------------------------------------------------------------------
# negative controls (in-memory mutants of real guards; a crashing mutant is MUTANT-INVALID = a negative-control failure)
# ---------------------------------------------------------------------------------------------------------------------------
FW_TEXT = T.read_source_text(FW)
PR41_COND = ("            !id(free_power_recovery_metadata_corrupt) &&\n            !id(dump_recovery_metadata_corrupt) &&\n"
             "            id(free_power_marker_state) == ecco_durable::MARKER_RESTORE_REQUIRED &&\n")
WD_GATE = ("              // Deliberate operator recovery is required first.\n"
           "              if (id(free_power_recovery_metadata_corrupt)) return false;\n")
RS_GATE = ("                id(free_power_snapshot_valid) &&\n                !id(free_power_recovery_metadata_corrupt) &&\n"
           "                !id(free_power_operation_in_progress) &&\n")
# pattern from registry/tests/assurance_lab/test_lab_selftest_firmware.py:1005 (the core's INV-BOOT-MIRROR mutant anchor)
DUMP_RR_ANCHOR = ("uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;\n"
                  "              id(dump_marker_state) = state;")
DUMP_RR_MUTANT = "uint8_t state = (uint8_t) ecco_durable::MARKER_CLEAR;\n              id(dump_marker_state) = state;"
SMR1_TERMS = ("('binary_sensor.ecco_clock_dongle_free_power_snapshot_valid', 'Free Power snapshot pending restore'),",
              "('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'Dump to Grid snapshot pending restore'),",
              "('binary_sensor.ecco_clock_dongle_free_power_active', 'Free Power active'),",
              "('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'Dump to Grid lease active'),")


def run_mutant(build, m: str, presses: bool = False):
    """('ran', observations) or ('invalid', reason): a mutant whose construction or run raises is MUTANT-INVALID.
    presses=True adds the owner's End / Force presses after the reboot (run_chain), the path the watchdog gate is not on."""
    try:
        kw = build()
        return "ran", run_chain(m, horizon_s=900, presses=presses, restarts=False, second_reboot=False, **kw)
    except Exception as exc:  # recorded as MUTANT-INVALID and FAILED below - never a pass
        return "invalid", f"{type(exc).__name__}: {asc(exc, 160)}"


def neg(nid: str, mutation: str, target: str, want: str, res, killed_fn, expect_kill: bool = True) -> None:
    kind, r = res
    if kind == "invalid":
        outcome, detail = "invalid", r
    else:
        hit = killed_fn(r)
        outcome = "killed" if hit else "survived"
        detail = hit if hit else "no violation"
    NEG.append((nid, mutation, target, outcome, asc(detail, 160)))
    print(f"  info  {nid}: {outcome} - {asc(detail, 140)}")
    if expect_kill:
        check(f"negative control {nid}: {mutation} -> {want} (no harness exception, no parse error)",
              outcome == "killed", f"{outcome}: {asc(detail, 160)}")
    else:
        check(f"defence in depth {nid}: {mutation} alone -> the remaining guard still holds (survives, zero writes; "
              "a valid run)", outcome == "survived" and r["writes_after"] == [], f"{outcome}: {asc(detail, 160)}")


def section_negative() -> None:
    print("[8] negative controls: in-memory mutants of the guards this scenario relies on")
    no_pr41 = lambda: {"fw_text": mutate(FW_TEXT, PR41_COND, PR41_COND.replace(  # noqa: E731
        "!id(free_power_recovery_metadata_corrupt) &&", "false && !id(free_power_recovery_metadata_corrupt) &&", 1),
        "PR41 off")}

    def second_restorer(r):
        v = viol_after(r, "INV-NO-2ND-RESTORER", r["b1"])
        return f"{v[0][0]} at seq {v[0][1]} after boot 1: {v[0][2][:90]}" if v and r["corrupt"] == (False, False) else None
    for m in ("a", "b"):
        neg(f"NC1{m}", "firmware PR41 Free Power/Dump check disabled ('false &&')", "INV-NO-2ND-RESTORER after the reboot",
            "a restore writes 256-261 over the other domain's RESTORE_REQUIRED marker after the reboot",
            run_mutant(no_pr41, m), second_restorer)
    both = lambda: {"fw_text": mutate(mutate(FW_TEXT, WD_GATE, WD_GATE.replace("return false;", "{}"), "FP watchdog gate"),  # noqa
                                      RS_GATE, RS_GATE.replace("!id(free_power_recovery_metadata_corrupt) &&", "true &&"),
                                      "FP restore gate")}

    def lockout_write(r):
        v = viol_after(r, "INV-LOCKOUT-QUIET", r["b1"])
        return f"{v[0][0]}: {v[0][2][:90]} ({len(v)} violation(s))" if v and r["corrupt"] == (True, True) else None
    neg("NC2b", "both FP lockout write guards removed (watchdog corrupt gate + restore-script precondition)",
        "INV-LOCKOUT-QUIET", "the FP restore writes its registers while FP is corrupt-locked", run_mutant(both, "b"),
        lockout_write)
    wd_only = lambda: {"fw_text": mutate(FW_TEXT, WD_GATE, WD_GATE.replace("return false;", "{}"), "FP watchdog gate")}  # noqa
    rs_only = lambda: {"fw_text": mutate(FW_TEXT, RS_GATE, RS_GATE.replace(  # noqa: E731
        "!id(free_power_recovery_metadata_corrupt) &&", "true &&"), "FP restore gate")}
    neg("NC2b-wd", "only the FP watchdog corrupt gate removed", "INV-LOCKOUT-QUIET", "", run_mutant(wd_only, "b"),
        lockout_write, expect_kill=False)
    # NC2b-rs survives only on the watchdog path (no owner press): the watchdog's own corrupt gate (firmware :24119) still
    # refuses. On the End path the End & Restore button (:23204) executes restore_free_power_snapshot unconditionally
    # (:23298-23299), so the restore script's precondition (:9993) is the only guard: NC2b-rs-end kills the same mutation
    # there (B3 audit: the 'survived by design' rationale was wrong for the End path).
    neg("NC2b-rs", "only the FP restore-script corrupt precondition removed, watchdog path (no owner press; the End path "
        "is NC2b-rs-end)", "INV-LOCKOUT-QUIET", "", run_mutant(rs_only, "b"), lockout_write, expect_kill=False)

    def lockout_write_any(r):   # the End restore may clear the lockout afterwards: the violation itself is the kill
        v = viol_after(r, "INV-LOCKOUT-QUIET", r["b1"])
        return f"{v[0][0]}: {v[0][2][:90]} ({len(v)} violation(s))" if v else None
    neg("NC2b-rs-end", "only the FP restore-script corrupt precondition removed, with the owner's End / Force presses "
        "after the lockout boot (End & Restore runs the restore script unconditionally, firmware :23298-23299)",
        "INV-LOCKOUT-QUIET", "the owner's FP End press restores registers while FP is corrupt-locked",
        run_mutant(rs_only, "b", presses=True), lockout_write_any)

    def smr1_mut():
        t = H.package_text("smr1")
        for line in SMR1_TERMS:
            t = mutate(t, line, "", "SMR1 blocker term")
        return {"package_texts": {"smr1": t}}

    def smr1_write(r):
        # the scenario's own leases only: the mutant also shows inside the B5 prelude (SMR1 writes the staged Dump value
        # during the 1 min prelude lease), which is not this control's target; counted separately for the record
        pre = [x for x in r["hf"] if x["inv"] == "INV-HF-SMR1-QUIET" and x["seq"] <= r["prelude"]["seq"]]
        v = [x for x in r["hf"] if x["inv"] == "INV-HF-SMR1-QUIET" and x["seq"] > r["prelude"]["seq"]]
        return f"{len(v)} after the prelude ({len(pre)} inside it): {v[0]['inv']}: {v[0]['detail'][:90]}" if v else None
    neg("NC3b", "SMR1 blocker loses its lease-active and snapshot-pending terms (package text)", "INV-HF-SMR1-QUIET",
        "SMR1 writes a staged Free Power number while firmware truth shows the lease / snapshot",
        run_mutant(smr1_mut, "b"), smr1_write)
    dump_ignores = lambda: {"fw_text": mutate(FW_TEXT, DUMP_RR_ANCHOR, DUMP_RR_MUTANT, "Dump on_boot marker read")}  # noqa

    def boot_mirror_hit(r):
        v = r["boot_mirror"]
        ok = len(v) == 1 and v[0][1].startswith("boot 1: the stored dump marker is RESTORE_REQUIRED")
        return f"INV-BOOT-MIRROR at seq {v[0][0]}: {v[0][1][:110]}" if ok else None
    neg("NC6a", "the Dump on_boot reads its stored marker as CLEAR (the stored RESTORE_REQUIRED is ignored)",
        "INV-BOOT-MIRROR at the lockout boot", "exactly one INV-BOOT-MIRROR violation (dump, boot 1) on the coupled chain",
        run_mutant(dump_ignores, "a"), boot_mirror_hit)


def section_detector() -> None:
    print("[9] the suite's settled-edge INV-HF-WINDOW view (hand-built logs; the core checker does the rest)")
    arm = {"seq": 0, "t_utc": U0, "up_ms": None, "boot": None, "src": "lab", "kind": "owner.arm",
           "data": {"dom": "fp", "start_local": "x", "window_end": U0 + 100}}

    def edge(seq, act, snap, at, boot):
        return {"seq": seq, "t_utc": U0 + at, "up_ms": None, "boot": None, "src": "lab", "kind": "dongle.edge",
                "data": {"dom": "fp", "act": act, "snap": snap, "at": U0 + at, "boot": boot}}
    held = [arm, edge(1, True, True, 10, 0), edge(2, False, False, 50, 1), edge(3, True, True, 50, 1)]
    clean = [arm, edge(1, True, True, 10, 0), edge(2, False, False, 110, 0)]
    w = type("W", (), {"t_utc": U0 + 400})()
    core_held = H.check_hf_window(held, world=w)
    ok = (len(H.check_hf_window(settled_events(held), world=w)) == 1 and not core_held
          and not H.check_hf_window(settled_events(clean), world=w) and not H.check_hf_window(clean, world=w))
    NEG.append(("NC4", "hand-built: a boot transient edge followed by the reloaded lease at the same instant",
                "INV-HF-WINDOW (settled view)", "killed" if ok else "survived", "settled view flags the held override; "
                "a clean lease end is not flagged; the core view misses the held one"))
    check("negative control NC4: settled_events keeps the reloaded lease across a boot transient (INV-HF-WINDOW flags "
          "an override held 300 s past its window) and leaves a normal lease end alone; the raw core view misses the "
          "held override (the worked-around core issue)", ok, str(core_held))
    print(f"  info  negative-control outcomes: {[(n, o) for n, _m, _t, o, _d in NEG]}")


def notes_relation_ok(doc: dict, fid) -> bool:
    """A finding document's notes name the finding and its dedupe relation: 'DUPLICATE of <owner id>, not counted' for a
    duplicate, 'merged into <owner id>, not counted' (and no DUPLICATE) for a merged variant (V0.1), 'counted' (and no
    DUPLICATE) for a finding this suite counts, plus the id of its scenario cross-reference (F-HF07-1 -> F-FW01-2); a PASS
    document (fid None) needs nothing."""
    if fid is None:
        return True
    f, notes = FINDINGS_SPEC[fid], doc.get("notes", "")
    xref = SCENARIOS[0]["cross_references"].get(fid)
    if f"Finding {fid} " not in notes or (xref and xref.split()[0] not in notes):
        return False
    if f["duplicate_of"]:
        return f"DUPLICATE of {f['duplicate_of']}, not counted" in notes
    if f.get("merged_into"):
        return f"merged into {f['merged_into']}, not counted" in notes and "DUPLICATE" not in notes
    return "counted" in notes and "DUPLICATE" not in notes


def doc_prelude(doc: dict) -> tuple:
    """(dom, prelude action, main-arm index, injection index) of an HF-07 document: its single nvs_policy fw_action (the
    injection), the domain of the injected tag, and the two arm_schedule actions of that domain before the injection -
    the B5 prelude (the first) and the main schedule (the second). Nones when the document does not have exactly one
    injection and two such arms."""
    inj = [i for i, a in enumerate(doc["actions"]) if a["do"] == "fw_action" and a["args"].get("name") == "nvs_policy"]
    if len(inj) != 1:
        return None, None, None, None
    i = inj[0]
    dom = str(doc["actions"][i]["args"].get("args", {}).get("tag", "")).split(".")[0]
    arms = [j for j, a in enumerate(doc["actions"][:i]) if a["do"] == "arm_schedule" and a["args"].get("dom") == dom]
    if len(arms) != 2:
        return dom, None, None, i
    return dom, doc["actions"][arms[0]], arms[1], i


def prelude_doc(doc: dict, dom: str, j: int) -> dict:
    """The document cut at its main schedule's arm (action j and everything after it replaced by run_for 0 at that
    instant), with the B5 prelude expectations instead of its own: the domain's verified restore RESTORED_OK (anchors
    fw.fp_restored_ok / fw.dump_restored_ok, published after the durable marker CLEAR commit), marker CLEAR, the RAM
    mirrors HA reads off, the schedule COMPLETED after 'STARTED OK', the lease wrote, the owned registers back at the site
    ORIGINAL (L.SITE, the corpus world's bank), no notification and no firmware / coupled invariant violation."""
    ha = {"fp": ("free_power_active", "free_power_snapshot_valid"),
          "dump": ("dump_to_grid_active", "dump_to_grid_snapshot_valid")}[dom]
    exp = [("nvs_marker", {"dom": dom}, "==", "CLEAR"), ("fw_status", {"dom": dom}, "==", RESTORED_OK),
           ("schedule_status", {"dom": dom}, "==", "COMPLETED"), ("last_result", {"dom": dom}, "startswith", "STARTED OK"),
           ("writes", {}, "!=", []), ("bank", {"addrs": list(L.OWNED)}, "==", {str(a): ORIG[a] for a in L.OWNED}),
           ("notifications", {}, "==", {}),
           ("invariants", {"names": sorted(H.HF_INVARIANTS) + sorted(L.INVARIANTS)}, "==", [])]
    exp += [("ha_state", {"entity": f"binary_sensor.ecco_clock_dongle_{e}"}, "==", "off") for e in ha]
    return dict(doc, actions=doc["actions"][:j] + [{"do": "run_for", "at_s": doc["actions"][j]["at_s"],
                                                     "args": {"seconds": 0}}],
                expect=[{"observe": o, "args": a, "op": op, "value": v} for o, a, op, v in exp], trace_digest="0" * 64)


def section_corpus_prelude(cid: str, doc: dict) -> None:
    """The B5 checks of one HF-07 document: its prelude has the suite's form and, replayed alone to the main schedule's
    arm, completed a real lease; HF-07-c / -e: the writes expectation lists only the prelude's writes."""
    dom, pa, j, i = doc_prelude(doc)
    want = {"do": "arm_schedule", "at_s": PRE_ARM - U0,
            "args": {"dom": dom, "start_local": PRE_START_LOCAL, **PRE_RUN.get(dom, {})}}
    shape = (dom in PRE_RUN and pa == want and doc["actions"][j]["at_s"] == ARM1 - U0
             and doc["actions"][i]["at_s"] == POLICY_AT - U0 and C.parse_iso_utc(doc["utc_start"]) == U0)
    res = T.replay(prelude_doc(doc, dom, j)) if shape else None
    fails = [(f["observe"], asc(f["observed"], 80)) for f in res.failed_expectations] if res else "no prelude"
    check(f"corpus {cid} B5 prelude: a 1 min scheduled {DOM_TEXT.get(dom)} lease armed at +{PRE_ARM - U0} s for "
          f"{PRE_START_LOCAL[11:16]}, the main schedule armed at +{ARM1 - U0} s and the injection at +{POLICY_AT - U0} s; "
          f"replayed alone to the main arm: a real lease completed (marker CLEAR, '{RESTORED_OK}', schedule COMPLETED, "
          "writes, owned registers at ORIGINAL, RAM mirrors off, no notification, no invariant violation)",
          shape and not fails, f"shape {shape}; {fails}")
    wx = [e for e in doc["expect"] if e["observe"] == "writes"]
    if wx:
        ws = wx[0]["value"]
        check(f"corpus {cid} B5 writes: the writes expectation lists exactly the prelude's {len(ws)} writes (all boot 0, "
              f"dom {dom}, landed, before 12:00): the phantom START and everything after it wrote nothing (V0: [])",
              wx[0]["op"] == "==" and len(wx) == 1 and ws and all(
                  w["boot"] == 0 and w["dom"] == dom and w["landed"] and w["t_utc"] < ST for w in ws), str(ws)[:300])


def refusal_without_prelude(doc: dict) -> str:
    """Replay the document with its B5 prelude action removed: '' when the core's NVS used-key rule refuses the injection
    (a LabHarnessError naming the never-stored marker key), else what happened instead. Only that exact refusal is
    accepted; any other harness error is reported as the failure detail (never a pass)."""
    dom, pa, _j, _i = doc_prelude(doc)
    if pa is None:
        return "no prelude action"
    stripped = dict(doc, actions=[a for a in doc["actions"] if a is not pa], trace_digest="0" * 64)
    head = (f"'false_negative' on NVS key {L.TAGS[f'{dom}.valid']} ({dom}.valid): refused - the key was never stored "
            "earlier in this run")
    try:
        res = T.replay(stripped)
    except L.LabHarnessError as exc:
        return "" if str(exc).startswith(head) else f"another harness error: {asc(exc, 200)}"
    return f"replayed without a refusal (ok={res.ok})"


def section_corpus() -> None:
    print("[10] replay corpus: every HF-07 document loads, matches the scenario table, and replays ok")
    replayed = {}
    for cid, fid in sorted(CORPUS.items()):
        path = CORPUS_DIR / f"{cid}.json"
        if not path.is_file():
            check(f"corpus {cid}: the file exists", False, str(path.name))
            continue
        doc = T.load_doc(path)
        want = FINDINGS_SPEC[fid]["classification"] if fid else "PASS"
        # V0.1 (brief B6.6): scenario_priority is the HF-07 scenario's priority (finding_priority is the catalogue's
        # root-cause priority of the finding's counted owner, checked by gen_catalogue / test_lab_replay_corpus)
        meta = doc["id"] == cid and doc["tier"] == "coupled" and doc["classification"] == want and doc["synthetic"] \
            and doc["grade"] == "VERIFIED" and notes_relation_ok(doc, fid) \
            and doc.get("scenario_priority") == SCENARIOS[0]["priority"] and "finding_priority" in doc
        res = replayed[cid] = T.replay(doc)
        print(f"  info  {cid}: {doc['classification']} {doc['invariant']}; {len(doc['actions'])} actions, "
              f"{len(doc['expect'])} expectations; replay ok={res.ok} drift={res.drift} digest {res.digest[:12]}")
        check(f"corpus {cid}: id / tier / classification ({want}) match, scenario_priority is the scenario's, synthetic, "
              "VERIFIED, the notes state the finding's dedupe relation; the replay is ok (no source drift: the recorded "
              "trace digest and anchor lines; source drift: the expectations only, the spec's drift rule)", meta and res.ok
              and (res.drift or res.digest == doc["trace_digest"]),
              f"{meta} {res.failed_expectations[:2]} drift={res.drift} {res.anchor_problems[:2]}")
        section_corpus_prelude(cid, doc)
    for cid in ("HF-07-c", "HF-07-f"):      # one document per injected domain (fp.valid, dump.valid)
        path = CORPUS_DIR / f"{cid}.json"
        why = refusal_without_prelude(T.load_doc(path)) if path.is_file() else "file missing"
        check(f"negative control: {cid} with its B5 prelude removed (the V0 injection on a never-stored marker key) is "
              "refused by the core's NVS used-key rule (a LabHarnessError naming the key; the prelude is load-bearing)",
              not why, why)
    path = CORPUS_DIR / "HF-07-c.json"
    if path.is_file():
        doc = T.load_doc(path)
        bad = dict(doc, expect=[dict(doc["expect"][0], value="FAILED TO START - another text")] + doc["expect"][1:])
        res = T.replay(bad)
        # differential against the unaltered replay above (no failed expectation at the lab's own phase): since B5 the
        # document's writes expectation pins the prelude's write instants, which another scheduler phase moves (the
        # document's own replay check is phase-sensitive by its digest already); the altered expectation must be the
        # only additional failure either way
        own = {f["index"] for f in replayed["HF-07-c"].failed_expectations} if "HF-07-c" in replayed else {-1}
        alt = {f["index"]: f["observe"] for f in res.failed_expectations}
        check("negative control: HF-07-c with one altered expectation does NOT replay ok (the failed expectation is the "
              "altered last_result; differential: beyond the unaltered replay's own failed expectations, none at the "
              "lab's phase)", not res.ok and set(alt) == own | {0} and 0 not in own and alt[0] == "last_result",
              str(res.failed_expectations[:2]))
    docs = {c: T.load_doc(CORPUS_DIR / f"{c}.json") for c in ("HF-07-b", "HF-07-d") if (CORPUS_DIR / f"{c}.json").is_file()}
    if len(docs) == 2:
        d, b = docs["HF-07-d"], docs["HF-07-b"]
        cut_dup = dict(d, notes=d["notes"].replace("DUPLICATE of F-FW01-1, not counted", "same root"))
        add_dup = dict(b, notes=b["notes"] + " DUPLICATE of F-FW01-2.")
        no_xref = dict(b, notes=b["notes"].replace("F-FW01-2", "FW-01"))
        check("negative control of the notes relation: HF-07-d without its 'DUPLICATE of F-FW01-1, not counted' clause, "
              "HF-07-b with a DUPLICATE clause added, and HF-07-b without its F-FW01-2 cross-reference are each refused; "
              "the recorded documents pass", notes_relation_ok(d, "F-HF07-4") and notes_relation_ok(b, "F-HF07-1")
              and not notes_relation_ok(cut_dup, "F-HF07-4") and not notes_relation_ok(add_dup, "F-HF07-1")
              and not notes_relation_ok(no_xref, "F-HF07-1"))
    else:
        check("negative control of the notes relation: HF-07-b and HF-07-d exist", False, str(sorted(docs)))


def section_extended(ra: dict, rb: dict) -> None:
    t_ext = time.perf_counter()
    print("[11] EXTENDED: 25 h horizon, the measured bus, original 244 = 0 (mirror b), reboot-instant sweep, twin b")
    for m in ("a", "b"):
        r = run_chain(m, horizon_s=25 * 3600)
        second = r["second"]
        print(f"  info  {m} 25 h: notifications created after the lockout {r['notify_after']}; SMR1 {second} "
              f"{asc(r['smr1'][second], 70)!r}; schedule status {r['sched']}")
        stale = [n for n in r["notify_after"] if n[1] == f"ecco_sched_restore_{second}"]
        owed_age = (r["cut"] + stale[0][0] - ST2) if stale else None     # SMR1's obligation dates from 12:30 (the staging)
        print(f"  info  {m} 25 h: SMR1's STALE notification {owed_age} s after the obligation was recorded")
        check(f"{m} 25 h: the first and only HA notification after the lockout is SMR1's STALE 'manual "
              f"{DOM_TEXT[second]} values NOT restored' 24 h after its obligation (about the staged values, not the "
              f"lockout); {'FPS1' if second == 'fp' else 'DGS1'} still ACTIVE, still no write except containment",
              len(r["notify_after"]) == 1 and stale and 86400 <= owed_age <= 86400 + 600
              and r["sched"][second] == "ACTIVE" and r["writes_after"] == ([(244, [2], "dump", 1)] if m == "a" else [])
              and r["smr1"][second].startswith("STALE"), f"{r['notify_after']} {r['sched']}")
    for m, base in (("a", ra), ("b", rb)):
        r = run_chain(m, bus=H.BusModel())
        # B5: on the measured bus the 1 min prelude lease itself ends a few seconds beyond window end + 30 s - the
        # lease-tail overrun F-HF01-1 pins (HF-01: a start gated after the window start plus a busy end slot), not this
        # scenario's subject; the scenario's own settled INV-HF-WINDOW violations are those after the prelude (V0 had no
        # prelude lease, so this is the V0 count); the prelude's are printed and must be that tail alone
        pre_win = [v for v in r["hf_window_settled"] if v["seq"] <= r["prelude"]["seq"]]
        own_win = [v for v in r["hf_window_settled"] if v["seq"] > r["prelude"]["seq"]]
        print(f"  info  {m} measured bus: the prelude's own settled INV-HF-WINDOW {[asc(v['detail'], 110) for v in pre_win]}"
              f" (F-HF01-1's lease tail); the scenario's {[asc(v['detail'], 90) for v in own_win]}")
        check(f"{m} measured bus (11 Oct windows, phase 0): the same end state - lockout, ACTIVE past the window, no "
              "notification after the lockout, the same post-lockout writes; exactly one settled INV-HF-WINDOW violation "
              "after the B5 prelude (the held second lease), the prelude's own at most its F-HF01-1 lease-tail overrun",
              r["corrupt"] == (True, True) and r["sched"] == base["sched"] and r["notify_after"] == []
              and r["writes_after"] == base["writes_after"] and len(own_win) == 1
              and all(v["detail"].startswith(f"{r['first']} run of {PRE_START_LOCAL}: override ended ") for v in pre_win)
              and not prelude_problem(r["prelude"], physical_only=True),
              f"{r['sched']} {r['writes_after']} {[v['detail'][:80] for v in r['hf_window_settled']]}")
    r = run_chain("b", bank={244: 0})
    print(f"  info  b with original 244 = 0: writes after the lockout {r['writes_after']}; owned diff {r['owned_diff']}")
    check("b with original 244 = 0 (export allowed by the owner): SG-02 containment writes 244 := 2 although the Dump "
          "lease never wrote anything - the documented containment literal over the owner's own value (the FW-01 "
          "mechanism, seen here through HA: still no notification)", r["writes_after"] == [(244, [2], "dump", 1)]
          and r["corrupt"] == (True, True) and r["notify_after"] == [], str(r["writes_after"]))
    rows = []
    for m in ("a", "b"):
        for dt in (65, 305, 1205, 1700):
            r = run_chain(m, cut=ST2 + dt, horizon_s=900, presses=False, restarts=False, second_reboot=False)
            rows.append((m, dt, r["corrupt"], r["sched"][r["second"]], len(r["hf_window_settled"]), r["notify_after"]))
    print(f"  info  reboot-instant sweep (s after the second start): {[(m, dt, c, s, n) for m, dt, c, s, n, _x in rows]}")
    lock = [x for x in rows if x[2] == (True, True)]
    check("reboot-instant sweep: every reboot inside the second lease ends in the PR41 lockout with the schedule ACTIVE "
          "and no notification (mirror b at +1700 s is still inside the 60 min FP lease)",
          all(x[3] == "ACTIVE" and not x[5] for x in lock) and {(x[0], x[1]) for x in lock} >= {
              ("a", 65), ("a", 305), ("a", 1205), ("b", 65), ("b", 305), ("b", 1205), ("b", 1700)}, str(rows))
    r = run_chain("b", fault=False, horizon_s=600, presses=False, restarts=False, second_reboot=False)
    print(f"  info  twin b: DGS1 {asc(r['last']['dump'], 60)!r}; FPS1 {asc(r['last']['fp'], 90)!r} (a refusal at the "
          "Dump lease tail is HF-04's subject, not classified here)")
    check("twin b (no fault): no lockout, no invariant violation, the owned registers back at ORIGINAL",
          r["corrupt"] == (False, False) and not r["fwv"] and r["owned_diff"] == {}, f"{r['last']} {r['fwv'][:2]}")
    print(f"  info  extended sections runtime_s={round(time.perf_counter() - t_ext, 1)}")


# =============================================================================================================================
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")
section_anchors()
RA = run_chain("a")
RB = run_chain("b")
section_chain("a", RA)
section_chain("b", RB)
section_hidden_lockout("a", RA, run_chain("a", restarts=False))
section_hidden_lockout("b", RB, run_chain("b", restarts=False))
section_report_text(RA)
section_operator_texts(RA, RB)
unsupported("HF-07/system-health", "home-assistant/packages/ecco_system_health.yaml is not executable in the coupled world "
            "(states[...] subscripts); its FAILED / WARNING health states for this chain are INFERRED only")
section_controls()
section_negative()
section_detector()
section_corpus()
if EXTENDED:
    section_extended(RA, RB)
check("every finding of the table reproduced in this run (none silently skipped; a merged variant prints no FINDING line "
      "and is reproduced by its owner's pins)",
      sorted(FOUND) == sorted(f for f in FINDINGS_SPEC if f not in MERGED)
      and all(reproduced(fid) for fid in FINDINGS_SPEC if fid not in MERGED) and not set(FOUND) & set(MERGED),
      str(sorted(FOUND)))
check("merge register: F-HF07-2 printed no FINDING line and its mirror-a pin under F-HF07-1 held",
      "F-HF07-2" not in FOUND and any(n.startswith("finding-reproduces:F-HF07-1 (mirror a") for n in REPRODUCED),
      str(sorted(FOUND)))
DUPS = [f"{fid} = {FINDINGS_SPEC[fid]['duplicate_of']}" for fid in FOUND if FINDINGS_SPEC[fid]["duplicate_of"]]
print(f"  info  findings: {len(FOUND)} reproduced, {len(counted())} counted in LAB-SUMMARY ({', '.join(counted())}); "
      f"merged variants: {', '.join(f'{fid} -> {why}' for fid, why in sorted(MERGED.items()))}; not counted, duplicates "
      f"of other suites' findings: {', '.join(DUPS) or 'none'}")
BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME = time.perf_counter() - T0
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=counted(), finding_pins=REPRODUCED,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
