#!/usr/bin/env python3
"""Coupled schedule scenarios HF-01, HF-04 and HF-06 of the assurance lab: the REAL FPS1 / DGS1 / SMR1 Home Assistant packages
and the REAL dongle firmware in one CoupledWorld (_lab_ha; London time, UTC-true timeline). Offline assurance lab V0 (test-only:
no network, no Home Assistant, no hardware; writes nothing).

  HF-01 (P1)  A scheduled Free Power on the SYNTHETIC date 2026-10-21, 12:00-13:00 BST, 8000 W / 60 min, and a scheduled Dump to
              Grid 12:00-12:30, 3000 W / Stop SOC 20 % (dump_plant MODEL), each with the owner's synthetic manual values staged
              before: arm -> STARTED OK -> firmware ACTIVE -> lease end on the UTC epoch -> firmware restore verified -> SMR1
              puts the owner's values back. A synthetic bus-busy window at the start (FPS1's transient retry), and the simulated
              window-end overrun over the watchdog phase (quick mode 0, 5 and 10 s; extended 0..14 s) and the bus model,
              against the HA suites' model-only bound (window end + 30 s, asserted against hand models; the packages
              say nothing starts or runs after the window end), in two metrics: the lease-end edge (the core's
              INV-HF-WINDOW: active and snapshot both off, after the verified restore) and the physical override end (the
              end of the first restoring write, 232 FP / 244 Dump, read from this world's own projection of the run).
  HF-04 (P2)  Back-to-back lease tails: a Free Power schedule armed after the Dump schedule started (and disarmed) for the
              Dump window end; the reverse (Dump after Free Power); and the same domain re-armed for its own window end.
  HF-06 (P2)  A failed START that keeps its snapshot (a Modbus verify mismatch through the lab's modbus policy): the
              firmware's own restore (Dump: its next watchdog tick; Free Power: inline), what DGS1 / FPS1 report and what SMR1
              does, against the HA dongle models' premise that the owner must press End & Restore.

Every decision is made by the real package YAML (the _ha_script_sim interpreter) or the real firmware (_dump_sim through
_lab_fw); this suite only arranges the synthetic inputs, observes, and classifies. The SCENARIOS / FINDINGS tables below hold the
ownership assumptions, the exact source anchors (re-counted at run time with _lab_trace.anchor_line), the invariants, the failure
outcomes, the classification, evidence grade, confidence, severity, reachability and the smallest safe repair scope (described,
never implemented). Findings print '  FINDING  <id> ...' and are pinned by 'finding-reproduces:<id>' checks (a firmware or
package fix makes them fail loudly and forces re-classification); they are NOT counted as passes. A finding whose root cause
another suite owns prints 'DUPLICATE of <owner id>, not counted' and is left out of the LAB-SUMMARY finding count
(DUPLICATE_OF; none of the seven is one; RELATED cross-references findings that share a locus but not the root).
The firmware invariants (_lab_fw.INVARIANTS, the default set) are judged over the merged log WITH the FirmwareWorld (fw_inv),
so INV-NO-SILENT-OVERRIDE also judges the state at the end of the log.

Suite-local invariant (an observer over the merged log, not a core checker): INV-HF-NO-PRESS-INTO-LEASE - no scheduled START
press reaches the firmware while firmware truth shows that domain's lease active (FPS1 / DGS1's 'already active' pre-check is
the guard). The finding-only invariants INV-HF-TAIL-RETRY, INV-HF-NO-SILENT-LOSS, INV-HF-ALERT-TRUTH, INV-HF-ARM-INTENT and
INV-HF-MODEL-FIDELITY name the intended behaviour each finding deviates from (see FINDINGS).

MODEL dependence (from _lab_ha / _lab_fw; nothing new is modelled here): the latencies (press 0.117 s, op 0.58 s, publish 0.12 s;
the _lab_ha defaults, sourced from the home-assistant/tests/_ha_dump_sim.py docstring), the bus model (never busy / the
recorded HA-side busy windows BUSY_10S / BUSY_60S of home-assistant/tests/_ha_script_sim.py, the core BusModel's default mode
/ the lab's own poll traffic / explicit synthetic windows), the watchdog phase relative to the HA clock, the dump_plant
stand-in, the TOU slot sensors derived from the firmware's register cache, the polled-sensor sample phase. The overruns and
tail lengths in this suite are simulated values (simulator output, VERIFIED in this harness only, not field measurements);
real-world values are INFERRED. ds.Sim's waits are no-ops, so a firmware end epoch is the gate second here and ~1-2 s later
on the device (after the snapshot reads; INFERRED): the lab is conservative for the HF-01 overrun and the HF-04 tails.

The FINDINGS table states each finding's wording, severity, confidence, reachability and repair scope against its cited source
anchors, which [0] re-counts at run time.

NOT covered: an explicit synthetic busy window at the start combined with the 'polls' bus at the end (BusModel takes one mode;
the recorded-busy-window model gives both a start retry and a busy end slot at some phases, which is swept); the bus
turnaround after a transaction's own reply (one bus_idle flag); interleavings inside a projected firmware transaction (the
core raises LabUnsupported: such sweep points are reported UNSUPPORTED, never PASS); HA restarts and dongle reboots (HF-02 /
HF-03); DST dates (HF-08).

Quick mode (<= 90 s); ECCO_LAB_EXTENDED=1 / --extended adds the full watchdog-phase x bus sweeps, a start-busy x phase grid and
the back-to-back gap x phase grids (runtime printed).
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
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "finding-reproduces:F-HF01-1": (
        "audit-named (the HF-01 >30 s reproductions): pins exact lease-end overruns (busy 34.4 / 30.32 s, FP 52.4 / "
        "48.32 s, Dump 35.93 / 34.17 s, recorded bus phase 0 30.93 / 29.17 s) measured on the lab's 15 s watchdog "
        "grid; where the first watchdog slot after the window end falls is the phase (fails under the phase patch in "
        "every run)"),
    "finding-reproduces:F-HF04-1": (
        "the Free Power start at (or 8 s after) the Dump window end fails only while the Dump restore still runs, "
        "and the 20 s gap starts; both are the Dump watchdog's slot after the window end (fails under the phase "
        "patch at some seeds)"),
    "finding-reproduces:F-HF04-2 [": (
        "pins the first run's own override tail to exactly 19.4 s (FP) / 15.93 s (Dump), the watchdog slot after the "
        "window end on the lab grid (fails under the phase patch in every run)"),
    "negative control NC-HF04-1 (HF-04)": (
        "the mutant's back-to-back run meets, at other phases, an interleaving inside a projected firmware "
        "transaction that the coupled tier refuses (LabUnsupported: outcome invalid) (fails under the phase patch in "
        "every run)"),
    "negative control NC-HF04-2 (HF-04)": (
        "as NC-HF04-1: at some phases the mutant's run meets a refused interleaving inside a projected transaction "
        "(outcome invalid) (fails under the phase patch at some seeds)"),
    "negative control NC-HF06-1 (HF-06)": (
        "at some phases the mutant's run meets a refused interleaving inside a projected transaction (outcome "
        "invalid), at others the blocker mutant survives (fails under the phase patch at some seeds)"),
    "every scenario family has at least one killed negative control and none survived": (
        "aggregate of this suite's negative controls: fails whenever a phase-sensitive control (NC-HF04-1 / "
        "NC-HF04-2 / NC-HF06-1) is invalid or survives"),
    "all 9 corpus documents exist, replay ok": _PS_DIGEST + (
        "; the aggregate of the 9 corpus replays (HF-01-a..c, HF-04-a..d, HF-06-a, b): the HF-01-a..c expectations "
        "and the HF-04-a / HF-06-a replays (refused interleavings) are timeline-bound as well"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
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


import math  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import yaml  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_ha as H  # noqa: E402

SUITE = "test_lab_ha_schedules"
FIXED_LOCAL = S.LOCAL
# ---------------------------------------------------------------------------------------------------------------------------
# synthetic inputs (NONE of these are site values; the date is a synthetic Wednesday in BST)
# ---------------------------------------------------------------------------------------------------------------------------
U0 = C.utc_of_local(2026, 10, 21, 11, 50)          # the worlds start here (the firmware booted WARMUP s earlier)
ST = C.utc_of_local(2026, 10, 21, 12, 0)           # the scheduled start, 12:00 BST = 11:00Z
START_LOCAL = "2026-10-21 12:00:00"
WARMUP = 120                                       # a warm dongle: the polled sensors have their first samples
IDLE = H.BusModel(windows=[])                      # a never-busy bus
BUSES = (("idle", IDLE), ("recorded", H.BusModel()), ("polls", H.BusModel(windows="polls")))   # recorded: BUSY_10S / BUSY_60S
REQ_FP = (8000, 60)                                # scheduled Free Power: W, min
REQ_DUMP = (3000, 30, 20)                          # scheduled Dump to Grid: W, min, Stop SOC %
OWNER = {"fp": (5000, 45), "dump": (1500, 30, 45)}  # the owner's manual request numbers (W, min / W, %, min)
CLAIM_S = 30.0                                     # the HA suites' model-only bound: the session ends by window end + 30 s
                                                   # (not a package claim; test.fps1_30s / test.dgs1_30s)
ORIG = {str(a): v for a, v in L.SITE["original"].items()}
QUICK_PHASES = (0, 5, 10)
FULL_PHASES = tuple(range(15))
END_DUMP_BUTTON = "button.ecco_clock_dongle_end_dump_to_grid_restore_now"
TOU_CHARGE = tuple(f"sensor.{S.P}ecco_timezone{n}_charge" for n in range(1, 7))
FP_STATUS_HA = next(h for h, (fid, _k) in sorted(H.dongle_entity_map().items()) if fid == "free_power_status")
# Sweep points the core cannot represent (never counted as PASS): (catalogue unsupported id, point), one UNSUPPORTED line
# each. The HF-04 lease-tail interleaving points carry the catalogue id HF-04-UNS-EXT (met in extended mode only). An HF-01
# window sweep point the core cannot represent has no catalogue entry (none is met today): it is printed as 'HF-01-UNS',
# which run_lab / gen_catalogue report as an uncatalogued id until the catalogue lists it (fail loud, never silent).
UNSUPPORTED: list[tuple[str, str]] = []
UNSUPPORTED_POINTS: list[str] = []                 # one catalogue id per printed UNSUPPORTED line (LAB-SUMMARY)
FOUND: list[str] = []                              # findings whose reproduction holds in this run

FW, FPS1, DGS1, SMR1 = L.FW_REL, H.PACKAGES["fps1"], H.PACKAGES["dgs1"], H.PACKAGES["smr1"]
FPS1_T = "home-assistant/tests/test_ecco_free_power_schedule_reliability.py"
DGS1_T = "home-assistant/tests/test_ecco_dump_to_grid_schedule_reliability.py"
SMR1_T = "home-assistant/tests/test_ecco_schedule_manual_restore.py"
HSIM, DSIM = "home-assistant/tests/_ha_script_sim.py", "home-assistant/tests/_ha_dump_sim.py"
INC_FP = "docs/incidents/2026-10-11-scheduled-free-power-start.md"
INC_DUMP = "docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md"
CARD = "frontend/ecco-energy-actions-card/README.md"

# exact text snippets, each found exactly once in its file (re-counted in [0]; the line numbers printed are information)
ANCHORS = {
    "fw.fp_end": (FW, "return (uint32_t) now.timestamp >= id(free_power_end_epoch);"),
    "fw.dump_end": (FW, "return (uint32_t) now.timestamp >= id(dump_end_epoch);"),
    "fw.fp_end_epoch": (FW, "uint32_t end_epoch = (uint32_t) now.timestamp + (minutes * 60U);"),
    "fw.dump_end_epoch": (FW, "id(dump_end_epoch) = (uint32_t) id(ntp_time).now().timestamp + duration_s;"),
    "fw.fp_end_deferred": (FW, 'id(free_power_status).publish_state("END DEFERRED - Modbus bus busy with another transaction; '
                               'watchdog will retry");'),
    "fw.dump_end_deferred": (FW, 'id(dump_status).publish_state("END DEFERRED - Modbus bus busy with another transaction; '
                                 'watchdog will retry");'),
    "fw.fp_gate_dump": (FW, '// "Free Power mutual exclusion". This is purely an'),
    "fw.fp_refuse_dump": (FW, 'else if (id(dump_active_persisted) || id(dump_snapshot_valid)) id(free_power_status).'
                              'publish_state("REJECTED - Dump to Grid override/recovery owns inverter settings");'),
    "fw.fp_refuse_active": (FW, 'else if (id(free_power_active_persisted)) id(free_power_status).publish_state("REJECTED - '
                                'Free Power already active");'),
    "fw.fp_verify_failed": (FW, 'id(free_power_status).publish_state("ACTIVATION VERIFY FAILED - restoring saved snapshot");'),
    "fw.fp_write_failed": (FW, 'id(free_power_status).publish_state("ACTIVATION WRITE FAILED - restoring saved snapshot");'),
    "fw.tou_publish": (FW, "id(ecco_tou1_charge).publish_state(charge_source(values[33]));"),
    "fw.dump_start_failed": (FW, '"START FAILED - verify mismatch or write error; snapshot retained - press End & Restore Now"'),
    "fw.dump_auto_text": (FW, '"START FAILED - export was enabled but ECCO could not durably record the lease; restoring '
                              'original settings automatically"'),
    "fw.dump_wd_comment": (FW, "// (The 15s watchdog restores any snapshot_valid &&"),
    "fw.dump_wd_interrupted": (FW, "if (!id(dump_active_persisted)) return true;"),
    "fw.dump_interrupted_reason": (FW, 'if (!id(dump_active_persisted)) return std::string("INTERRUPTED TRANSACTION - '
                                       'restoring original settings");'),
    "fw.dump_end_ignored": (FW, 'id(dump_status).publish_state("END IGNORED - no saved Dump to Grid snapshot");'),
    "fps1.window_doc": (FPS1, 'description: "End of the authorised window (epoch seconds); nothing starts or runs after it"'),
    "dgs1.window_doc": (DGS1, 'description: "End of the authorised window (epoch seconds); nothing starts or runs after it"'),
    "fps1.late_doc": (FPS1, "its full duration (as before), a late start ends within about a minute of the window end;"),
    "dgs1.late_doc": (DGS1, "full duration, a late start ends within about a minute of the window end;"),
    "fps1.duration_now": (FPS1, "(((window_end | float(0)) - as_timestamp(now()) + 20) / 60) | round(0, 'floor') | int(0)] | "
                                "min }}"),
    "fps1.retry_busy": (FPS1, "s.startswith('REJECTED - Modbus bus busy with another transaction')"),
    "fps1.persistent_failed": (FPS1, 'value: "FAILED TO START - {{ status_now }} (attempt {{ repeat.index }}; nothing '
                                     'written)"'),
    "fps1.began_failed": (FPS1, "(start transaction began on attempt {{ repeat.index }}; not retried)"),
    "fps1.blocked_active": (FPS1, 'value: "BLOCKED - Free Power already active"'),
    "fps1.no_alert_active": (FPS1, "{{ r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)"),
    "fps1.dismiss_on_active": (FPS1, '                entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n'
                                     '                state: "on"\n            then:\n'
                                     '              - action: persistent_notification.dismiss\n                data:\n'
                                     '                  notification_id: ecco_free_power_schedule\n'
                                     '              - action: persistent_notification.dismiss\n                data:\n'
                                     '                  notification_id: ecco_free_power_schedule_readiness\n'),
    "fps1.status_blocked": (FPS1, "or (r.startswith('BLOCKED') and 'already active' not in r) %}"),
    "fps1.arm_overlap": (FPS1, "{{ f_start < d_end + 120 and d_start < f_end + 120 }}"),
    "fps1.arm_buffer": (FPS1, "this one (2-minute buffer either side for start retry / restore)."),
    "fps1.ready_active": (FPS1, "{% if is_state('binary_sensor.ecco_clock_dongle_free_power_active', 'on') %}{% set r.v = "
                                "r.v + ['Free Power already active'] %}{% endif %}"),
    "fps1.ready_promise": (FPS1, "{{ blockers }}. ECCO will still try at the start time (and retry transient refusals for"),
    "dgs1.blocked_active": (DGS1, 'value: "BLOCKED - Dump to Grid already active"'),
    "dgs1.no_alert_active": (DGS1, "{{ r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)"),
    "dgs1.dismiss_on_active": (DGS1, '                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n'
                                     '                state: "on"\n            then:\n'
                                     '              - action: persistent_notification.dismiss\n                data:\n'
                                     '                  notification_id: ecco_dump_to_grid_schedule\n'
                                     '              - action: persistent_notification.dismiss\n                data:\n'
                                     '                  notification_id: ecco_dump_to_grid_schedule_readiness\n'),
    "dgs1.status_blocked": (DGS1, "or (r.startswith('BLOCKED') and 'already active' not in r) %}"),
    "dgs1.arm_overlap": (DGS1, "{{ d_start < f_end + 120 and f_start < d_end + 120 }}"),
    "dgs1.tou_walk": (DGS1, "{% set c = states('sensor.ecco_clock_dongle_ecco_timezone' ~ i ~ '_charge') %}"),
    "dgs1.tou_refusal": (DGS1, "REJECTED - window overlaps a TOU slot with a charge source set"),
    "dgs1.check_first": (DGS1, "If a start transaction began or the outcome is unconfirmed, check the Dump to Grid status"),
    "smr1.blocker_dump_snap": (SMR1, "('binary_sensor.ecco_clock_dongle_dump_to_grid_snapshot_valid', 'Dump to Grid snapshot "
                                     "pending restore'),"),
    "smr1.fp_saved": (SMR1, 'saved: "input_number.ecco_sched_restore_fp_{{ trigger.id }}_saved"'),
    "test.fps1_30s": (FPS1_T, 'check("...the session ends within 30 s of the authorised window\'s end (13:00)", r.d.ends_at <= '
                              'r.end_ts + 30,'),
    "test.dgs1_30s": (DGS1_T, 'check("...the session ends within 30 s of the authorised window\'s end", r.d.ends_at <= '
                              'r.end_ts + 30, S.local_str(r.d.ends_at))'),
    "test.fps1_model_write_failed": (FPS1_T, 'for outcome, needle in (("write_failed", "ACTIVATION WRITE FAILED"), '
                                             '("capture_failed", "could not capture")):'),
    "test.smr1_premise_dump": (SMR1_T, '"START FAILED with the snapshot retained: NOT restored while the snapshot is pending '
                                       '(the owner must press End & Restore)",'),
    "test.smr1_premise_fp": (SMR1_T, 'check("Free Power ACTIVATION WRITE FAILED (snapshot kept): not restored while the '
                                     'snapshot is pending",'),
    "model.dump_verify_failed": (DSIM, '"verify_failed": ("START FAILED - verify mismatch or write error; snapshot retained - '
                                       'press End & Restore Now", True),'),
    "model.dump_commit_failed": (DSIM, '"commit_failed": ("START FAILED - export was enabled but ECCO could not durably record '
                                       'the lease; restoring original "'),
    "model.fp_write_failed": (HSIM, 'elif self.outcome == "write_failed":'),
    "doc.fp_window": (INC_FP, "within about a minute of the window end. Nothing is ever started after the window."),
    "doc.d8": (INC_DUMP, "| D8 | A late start (the +35 s retry) runs its full duration past the authorised window end. | Model. | "
                         "Low (about 35 s). |"),
    "safety.watchdog": ("SAFETY.md", "The controller ends and restores them itself, so Home Assistant being unavailable does not "
                                     "stop the restore. If the bus is busy it retries"),
    "doc.fp_persistent": (INC_FP, "Dump to Grid owns the settings). NTP, live battery voltage and the arm itself are treated "
                                  "as transient (no side effect)."),
    "doc.fp_never_silent": (INC_FP, "enable always ends off, and any run that ends without STARTED / CANCELLED raises the alert."),
    "doc.fp_rearm_residual": (INC_FP, "a schedule re-armed for a time that arrives while the previous run is still finishing is "
                                      "started by the watchdog"),
    "doc.fp_restores_itself": (INC_FP, "firmware's own verified outcome and never presses again; on failure the firmware "
                                       "restores its saved snapshot itself."),
    "doc.fp_alert_reason": (INC_FP, "the reason, whether anything was written, and what to do; a later success clears it."),
    "doc.dump_owns_persistent": (INC_DUMP, "| Free Power override/recovery owns inverter settings | persistent | FAILED at "
                                           "once, alert (a Free Power transaction visible beforehand is waited for, never "
                                           "pressed into) |"),
    "doc.dump_already_active": (INC_DUMP, "| Dump to Grid already active | persistent | FAILED, or STARTED if Dump is active |"),
    "doc.dump_every_failure": (INC_DUMP, "a persistent notification `ecco_dump_to_grid_schedule` for every failure, BLOCKED or "
                                         "miss"),
    "doc.dump_snapshot_residual": (INC_DUMP, "A saved Dump snapshot pending restore at the start instant fails the run at once "
                                             "(the firmware's watchdog restores it within"),
    "doc.fp_watchdog_row": ("docs/SYSTEM_HEALTH_ARCHITECTURE.md", "auto-restores if snapshot valid but not active "
                                                                  "(interrupted activation)"),
    "card.no_button": (CARD, "| `START FAILED` / an activation write/verify failure | `false` | **No actionable button** - "
                             "there is no snapshot to restore |"),
}

SCENARIOS = [
    {"id": "HF-01", "priority": "P1", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "medium",
     "title": "Scheduled Free Power 12:00-13:00 BST 8000 W / 60 min and scheduled Dump 3000 W / 30 min / Stop SOC 20 end to "
              "end with the owner's staged values; bus-busy start retries; window-end overrun vs the HA suites' model-only +30 s "
              "check (the packages state 'nothing starts or runs after' the window end)",
     "ownership": "synthetic site (_lab_fw.SITE); the owner stages manual request numbers through HA (FP 5000 W / 45 min; Dump "
                  "1500 W / 30 % / 45 min) and arms one schedule; nothing else writes the inverter; FPS1 / DGS1 own staging "
                  "and the press, the firmware owns snapshot, lease, end epoch and restore, SMR1 owns putting the owner's "
                  "numbers back",
     "invariant": "INV-HF-WINDOW (bound 30 s = the HA suites' model-only check test.fps1_30s / test.dgs1_30s, not a "
                  "package claim; the core's metric is the lease-end edge: active and "
                  "snapshot both off, i.e. after the verified restore and its durable clear); the suite also computes the "
                  "physical override end (the end of the first restoring write: 232 FP grid-charge enable / 244 Dump export "
                  "enable, the core's projection) ~4.1 s (FP) / ~1.8 s (Dump) earlier; INV-HF-NO-FALSE-SUCCESS; "
                  "INV-HF-SMR1-QUIET; INV-HF-ONE-LEASE; INV-HF-ARM-OFF; INV-HF-OWNER-INTENT; firmware INV-* (merged log)",
     "anchors": ["fps1.window_doc", "dgs1.window_doc", "fps1.late_doc", "dgs1.late_doc", "fps1.duration_now",
                 "fps1.retry_busy", "fps1.arm_buffer", "fw.fp_end", "fw.dump_end", "fw.fp_end_epoch", "fw.dump_end_epoch",
                 "fw.fp_end_deferred", "fw.dump_end_deferred", "test.fps1_30s", "test.dgs1_30s", "doc.fp_window", "doc.d8",
                 "safety.watchdog", "smr1.fp_saved"],
     "failure_outcome": "the inverter stays in the scheduled override (grid charge / export) after the authorised window, or "
                        "SMR1 reports RESTORED while the owner's value is not on the number",
     "result": "happy paths PASS (STARTED OK, firmware ACTIVE, end on the UTC epoch, RESTORED OK, SMR1 restores the owner's "
               "values); every start gated within ~20 s of the window start ends after the window end (both metrics > 0 at "
               "every swept point, simulated values), and the physical end exceeds window end + 30 s with a busy end slot "
               "(Dump, on the recorded-busy-window bus model (simulated): 35.93 s lease-end edge / 34.17 s override end) or "
               "start retries plus a busy end slot (FP, same model: 52.4 s lease-end edge / 48.32 s override end); a start "
               "gated more than ~20 s late is shortened and ends before the window (F-HF01-1) (35.93 / 52.4 s are phase-dependent "
               "examples on one recorded-busy-window bus model; idle-bus maxima about 15.9 s Dump / 19.4 s Free Power)",
     "findings": ["F-HF01-1"], "corpus": ["HF-01-a", "HF-01-b", "HF-01-c"]},
    {"id": "HF-04", "priority": "P2", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "title": "Back-to-back lease tails: Dump end tail vs a Free Power schedule armed after the Dump schedule disarmed, Free "
              "Power -> Dump, and the same domain re-armed for its own window end",
     "ownership": "synthetic site; the owner arms the first schedule, then (after it started and disarmed itself) arms the "
                  "second for the first window's end; the firmware's 15 s watchdog ends the first lease and restores; nothing "
                  "else writes",
     "invariant": "INV-HF-ONE-LEASE and INV-HF-NO-PRESS-INTO-LEASE (hold); INV-HF-TAIL-RETRY, INV-HF-NO-SILENT-LOSS, "
                  "INV-HF-ARM-INTENT (the intended behaviour the findings deviate from)",
     "anchors": ["fw.fp_gate_dump", "fw.fp_refuse_dump", "fw.fp_refuse_active", "fw.tou_publish", "fps1.persistent_failed",
                 "fps1.arm_overlap", "fps1.arm_buffer", "fps1.blocked_active", "fps1.no_alert_active",
                 "fps1.dismiss_on_active", "fps1.status_blocked", "fps1.ready_active", "fps1.ready_promise",
                 "dgs1.blocked_active", "dgs1.no_alert_active", "dgs1.dismiss_on_active", "dgs1.status_blocked",
                 "dgs1.arm_overlap", "dgs1.tou_walk", "dgs1.tou_refusal", "doc.fp_persistent", "doc.fp_never_silent",
                 "doc.fp_rearm_residual", "doc.dump_owns_persistent", "doc.dump_already_active", "doc.dump_every_failure",
                 "doc.dump_snapshot_residual"],
     "failure_outcome": "a valid back-to-back plan FAILS with an alert although its blocker clears in seconds; a same-domain "
                        "window is lost with no failure alert; a Dump cannot be armed (for any time) while a Free Power lease "
                        "runs, and the refusal blames the TOU plan",
     "result": "one lease at a time always holds (the firmware gate); Dump -> FP: FAILED + alert, pre-warned by the readiness "
               "alert (F-HF04-1); FP -> Dump: refused at arm time by DGS1's TOU walk reading the Free Power override's own "
               "grid-charge slots, for any Dump window (F-HF04-3), except in the ~1 s between FPS1's disarm and the closing "
               "configuration readback, where the arm is accepted and the Dump then FAILS at the gate (F-HF04-1 mirrored); "
               "same domain at or inside the previous lease: BLOCKED - already active, no failure alert, status IDLE, window "
               "lost (F-HF04-2)",
     "findings": ["F-HF04-1", "F-HF04-2", "F-HF04-3"], "corpus": ["HF-04-a", "HF-04-b", "HF-04-c", "HF-04-d"]},
    {"id": "HF-06", "priority": "P2", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
     "title": "Failed START with a retained snapshot (Modbus verify mismatch) -> firmware auto-restore -> SMR1, vs the HA "
              "model premise (End & Restore required)",
     "ownership": "synthetic site; the owner stages manual values and arms one schedule; the first activation write of the "
                  "START is acknowledged but not applied (synthetic Modbus policy), so the verify read mismatches; the "
                  "firmware owns the retained snapshot and its restore; SMR1 owns the owner's numbers",
     "invariant": "INV-HF-SMR1-QUIET; INV-HF-NO-FALSE-SUCCESS; INV-RESTORE-BOUND (bound 20 s: one watchdog tick + the "
                  "restore); INV-HF-MODEL-FIDELITY and INV-HF-ALERT-TRUTH (the intended behaviour the findings deviate from)",
     "anchors": ["fw.dump_start_failed", "fw.dump_auto_text", "fw.dump_wd_comment", "fw.dump_wd_interrupted",
                 "fw.dump_interrupted_reason", "fw.fp_verify_failed", "fw.fp_write_failed", "fw.dump_end_ignored",
                 "fps1.began_failed", "dgs1.check_first", "smr1.blocker_dump_snap", "test.smr1_premise_dump",
                 "test.smr1_premise_fp", "test.fps1_model_write_failed", "model.dump_verify_failed",
                 "model.dump_commit_failed", "model.fp_write_failed", "doc.fp_restores_itself", "doc.fp_alert_reason",
                 "doc.fp_watchdog_row", "doc.dump_snapshot_residual", "card.no_button"],
     "failure_outcome": "the owner's values are lost or restored while the snapshot is still held; the owner is told to act "
                        "on something already done, or told the wrong reason",
     "result": "in the lab, the real firmware + package chain restores automatically and completely (auto-restore at the "
               "next Dump watchdog tick / inline for FP, SMR1 restores ~5 s after the snapshot clears, never while it is "
               "held); a long-pending snapshot is reachable only when the automatic restore also fails (the firmware "
               "retries with backoff, SMR1 stays OWED; End & Restore is "
               "not what clears it), so the HA models' cause and label are wrong (F-HF06-1); DGS1's alert keeps 'press End & "
               "Restore Now' after the firmware restored (F-HF06-2); FPS1's FAILED text names 'RESTORED OK' instead of the "
               "failure (F-HF06-3)",
     "findings": ["F-HF06-1", "F-HF06-2", "F-HF06-3"], "corpus": ["HF-06-a", "HF-06-b"]},
]

# Each finding states its classification, severity, confidence, reachability and repair scope against its cited anchors
# (re-counted in [0]); timings are simulated values from this harness.
FINDINGS = {
    "F-HF01-1": {
        "scenario": "HF-01", "classification": "FINDING-NEW", "confidence": "medium",
        "severity": "diagnostics / documentation (a model-only test bound and an inaccurate field text), low; cost "
                    "negligible (about 0.1 kWh of 8 kW grid charge or 0.03 kWh of 3 kW export per run at worst); no safety "
                    "or availability effect (the lease stays supervised until its verified restore)",
        "title": "every scheduled start gated within ~20 s of its time ends after the authorised window end; with a busy end "
                 "slot or start retries the override itself (not only the lease-end edge) outlives the window end + 30 s "
                 "that the HA suites assert only against the model's instant end",
        "mechanism": "the firmware fixes its end epoch at the START commit (now + duration: fw.fp_end_epoch / "
                     "fw.dump_end_epoch; the lab takes the gate second, the device ~1-2 s later after the snapshot reads, "
                     "so the lab is conservative); FPS1 / DGS1 stage min(requested, floor((window end - now + 20) / 60)) "
                     "(fps1.duration_now), so a start gated up to ~20 s late keeps the full duration and its end epoch lies "
                     "after the window end; the lease ends only at the next 15 s watchdog slot at or after that epoch "
                     "(fw.fp_end / fw.dump_end), deferred one period per slot that meets a busy bus (fw.fp_end_deferred / "
                     "fw.dump_end_deferred); the restore then takes ~2.9 s (Dump, 5 ops) / ~6.4 s (FP, 11 ops + 2 commits) "
                     "to the lease-end edge, the first restoring write (232 FP / 244 Dump) ending the override itself "
                     "~2.3 s / ~1.2 s into it; the HA suites' 'ends <= window end + 30 s' (test.fps1_30s / test.dgs1_30s) "
                     "runs against hand models whose session ends exactly at start + duration, and the window_end_ts field "
                     "text says 'nothing starts or runs after it' (fps1.window_doc / dgs1.window_doc)",
        "anchors": ["fw.fp_end_epoch", "fw.dump_end_epoch", "fw.fp_end", "fw.dump_end", "fw.fp_end_deferred",
                    "fw.dump_end_deferred", "fps1.duration_now", "fps1.window_doc", "dgs1.window_doc", "test.fps1_30s",
                    "test.dgs1_30s", "fps1.late_doc", "dgs1.late_doc", "doc.fp_window", "doc.d8", "fps1.arm_buffer",
                    "safety.watchdog"],
        "prior_art": "documented only qualitatively: 'a late start ends within about a minute of the window end' (fps1.late_doc, "
                     "dgs1.late_doc, doc.fp_window), the 2-minute arm buffer 'for start retry / restore' (fps1.arm_buffer), "
                     "the controller's own busy-bus retries (safety.watchdog); row D8 of the Dump schedule incident record "
                     "(doc.d8) rates a ~35 s late-start overrun Low and lists it as fixed in the package, but the firmware "
                     "end tail no budget covers remains; "
                     "no KNOWN_RISKS id; the contradicted claims are the window_end_ts text (a script field description that "
                     "could be read as covering only the script's own starts) and the HA suites' +30 s check",
        "reachability": "INFERRED likely in direction (the 15 s watchdog quantum, the end epoch fixed at commit, the +20 s slack "
                        "and the multi-op restore are source facts); above +30 s needs a late watchdog phase plus one busy "
                        "end slot, or a start retried by ~10-20 s, so it plausibly happens on some fraction of real runs; the "
                        "magnitude is UNKNOWN (real watchdog phase, bus traffic at the end slot, Modbus op time); the 55 s "
                        "maximum needs three busy slots in a row from the lab's stand-in polls (phase-specific, MODEL); every "
                        "simulated value stays within the documented 'about a minute'",
        "repair": "documentation / test only: (a, smallest) correct the window_end_ts description in both packages and state "
                  "the firmware end-latency budget (start offset up to ~20 s + up to 15 s to the next watchdog slot + 15 s "
                  "per busy slot + a 3-7 s restore) in the incident docs, noting it fits the existing 2-minute arm buffer; "
                  "(b) label the HA suites' +30 s check as HA-layer / model-only, or add that latency to the models, rather "
                  "than only raising the number; reserving the budget in duration_now's slack would change the documented "
                  "'an on-time start keeps its full duration' contract (a design decision, not part of the smallest repair); "
                  "no firmware change",
        "model_dependence": "Latency.op_s / publish_s / press_s, the BusModel mode and phase (the recorded busy windows "
                            "BUSY_10S / BUSY_60S of home-assistant/tests/_ha_script_sim.py, the lab's own poll traffic, "
                            "explicit synthetic windows), wd_phase_s, the core's projection of "
                            "synchronous firmware runs onto the HA clock (the physical end metric is that projection)",
        "invariant": "INV-HF-WINDOW", "corpus": ["HF-01-b", "HF-01-c"]},
    "F-HF04-1": {
        "scenario": "HF-04", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "availability / diagnostics, low: no safety impact (the gate fails closed, nothing is written, one lease "
                    "at a time holds); the planned Free Power window is lost unless the owner starts it by hand ~16 s "
                    "after the window end; pre-warned (the readiness alert names the Dump) and alerted with a remedy",
        "title": "a Free Power schedule armed after the Dump schedule disarmed, for the Dump window end, FAILS at once with an "
                 "alert although the Dump obligation clears 0-16 s after the window end (by watchdog phase), well inside "
                 "FPS1's own 10-minute retry budget; the same happens mirrored for a Dump armed at a Free Power window end",
        "mechanism": "two package-level gaps combine: FPS1's arm-time +-120 s check, meant as a 2-minute buffer 'for start "
                     "retry / restore' (fps1.arm_buffer), only covers an ARMED Dump schedule (fps1.arm_overlap) and DGS1 "
                     "disarms when its run starts, so an arm made during the Dump lease is accepted; FPS1's not-ready wait "
                     "covers a Free Power / manual write in progress, not a Dump lease, so it presses at ~+1.3 s; the Dump "
                     "end epoch is set inside the START (now + duration, fw.dump_end_epoch, after the window end for an "
                     "on-time start) and its watchdog restores 0-15 s later, so the gate refuses 'REJECTED - Dump to Grid "
                     "override/recovery owns inverter settings' (fw.fp_refuse_dump); FPS1 classifies that text as "
                     "persistent (fps1.persistent_failed) -> 'FAILED TO START', alert, no retry; the readiness alert names "
                     "the blocker but promises ECCO 'will still try ... and retry transient refusals' (fps1.ready_promise), "
                     "which this persistent class never is",
        "anchors": ["fps1.arm_overlap", "fps1.arm_buffer", "fw.fp_refuse_dump", "fw.dump_end_epoch", "fps1.persistent_failed",
                    "fps1.ready_promise", "doc.fp_persistent", "doc.dump_owns_persistent", "doc.dump_snapshot_residual"],
        "prior_art": "the persistent class is documented (doc.fp_persistent, doc.dump_owns_persistent); only the same-domain "
                     "Dump twin is an accepted residual (doc.dump_snapshot_residual); the cross-domain lease-tail "
                     "consequence and the arm-buffer bypass are not documented; no KNOWN_RISKS id",
        "reachability": "INFERRED plausible and economically natural (empty the battery by Dump, then charge in a free-power "
                        "window), but narrow: only when Free Power is armed after the Dump run has started (arming both in "
                        "advance is refused by the buffer); the failing gap is ~0-10 s after the Dump window end on an idle "
                        "bus (watchdog-phase dependent) and up to ~20 s when bus traffic defers the restore; gap 0 fails at "
                        "every supported phase (the lab's early end epoch is conservative; phase 3 at gap 0 is UNSUPPORTED)",
        "repair": "package only, no firmware change (the gate is the safety guard, NC-HF04-1): either extend FPS1's arm-time "
                  "+-120 s check to a RUNNING Dump lease (the Dump schedule's start and duration helpers), or add "
                  "binary_sensor.ecco_clock_dongle_dump_to_grid_active / _snapshot_valid to the stage-nothing / press-nothing "
                  "not-ready wait, bounded by the expected tail or excluding lockout states (an unbounded wait would delay "
                  "the alert for a genuinely stuck Dump obligation by up to 10 min); separately, the readiness text should "
                  "not promise a retry for a persistent blocker; mirroring the wait in DGS1 covers the reverse case (a "
                  "manual Free Power, or a Dump armed in the ~1 s window before the TOU slots read Grid)",
        "model_dependence": "the tail length and the failing gap range (Dump watchdog phase, op_s, bus model); the UNSUPPORTED "
                            "interleave points lie on the FAILED / STARTED boundary; the mirror window (~1 s in the lab) "
                            "depends on the closing Block B readback timing (ds.Sim's no-op waits make it shorter than on the "
                            "device, INFERRED)",
        "invariant": "INV-HF-TAIL-RETRY", "corpus": ["HF-04-a"]},
    "F-HF04-2": {
        "scenario": "HF-04", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "availability / diagnostics, low-medium: no safety impact (nothing written, the firmware restores "
                    "correctly); a whole same-function window is lost with status IDLE and no failure alert, partly "
                    "mitigated (the readiness alert names 'Free Power already active' until the start, then is dismissed; "
                    "last_result keeps the BLOCKED text); row D6 of the Dump schedule incident record "
                    "(docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md) rates the related 'BLOCKED for "
                    "good: no wait, no retry, no alert' Medium",
        "title": "a schedule whose start falls at the end of (or inside) the same function's previous lease records 'BLOCKED - "
                 "... already active', raises no failure alert, dismisses the readiness alert, ends IDLE and loses the "
                 "whole window; at the exact window end this is deterministic because the previous lease's end epoch is "
                 "already after it",
        "mechanism": "an on-time start keeps its full duration and its end epoch is the press time + duration "
                     "(fw.fp_end_epoch), so the previous lease always outlives its window end, and the firmware keeps it "
                     "active until the next watchdog slot plus the verified restore; FPS1 / DGS1 check 'already active' "
                     "once, before the retry loop (fps1.blocked_active / dgs1.blocked_active), and treat any active lease of "
                     "the same function as covering the whole window (no comparison of that lease's end with the window "
                     "end); 'already active' is excluded from the failure alert (fps1.no_alert_active / "
                     "dgs1.no_alert_active); because the lease is on, the run dismisses the readiness alert "
                     "(fps1.dismiss_on_active / dgs1.dismiss_on_active) that had named 'Free Power already active' "
                     "(fps1.ready_active); the fire automation disarms; the status template maps BLOCKED + 'already active' "
                     "to IDLE (fps1.status_blocked / dgs1.status_blocked)",
        "anchors": ["fps1.blocked_active", "fps1.no_alert_active", "fps1.dismiss_on_active", "fps1.status_blocked",
                    "fps1.ready_active", "dgs1.blocked_active", "dgs1.no_alert_active", "dgs1.dismiss_on_active",
                    "dgs1.status_blocked", "fw.fp_refuse_active", "fw.fp_end_epoch", "doc.fp_never_silent",
                    "doc.dump_already_active", "doc.dump_every_failure", "doc.fp_rearm_residual"],
        "prior_art": "contradicts the docs rather than being accepted by them: 'any run that ends without STARTED / CANCELLED "
                     "raises the alert' (doc.fp_never_silent), 'Dump to Grid already active | persistent | FAILED, or "
                     "STARTED' (doc.dump_already_active), a notification 'for every failure, BLOCKED or miss' "
                     "(doc.dump_every_failure); the only back-to-back residual on record (doc.fp_rearm_residual) is a "
                     "different, alerted mechanism; the no-alert choice for an owner's own active session is deliberate "
                     "(FPS1 suite :522); no KNOWN_RISKS id",
        "reachability": "INFERRED, medium-low: an owner who chains two windows of the same function back to back (arming the "
                        "second while the first runs), or whose manual lease of the same function is still running at a "
                        "scheduled start; how often same-function windows are chained in practice is UNKNOWN; the BLOCKED "
                        "zone extends ~5-38 s past the previous window end across phases, latencies and bus models "
                        "(simulated values)",
        "repair": "package only, no firmware change, no new write path; turn the pre-check into a bounded wait inside the "
                  "existing stage-nothing / press-nothing branch (before any number.set_value: the firmware reads the "
                  "staged Dump Stop SOC while a Dump restore is still owed), which also covers snapshot_valid; the loop's "
                  "'active on' success test and the 'could not confirm the start as its own' fix-up must not count a lease "
                  "that was already active when the run began (require an active -> off edge or a moved gate-pass counter), "
                  "otherwise the wait exits at once with a false STARTED OK (NC-HF04-2 shows that failure); whether to alert "
                  "when still active at the deadline is a design decision (it changes the deliberate owner-session "
                  "behaviour); a smaller diagnostics-only fix is to drop the 'already active' exemption from the alert and "
                  "the status (FAILED), which stops the silence but does not recover the window",
        "model_dependence": "none for the gap-0 outcome (the previous end epoch is after the trigger by source); the watchdog "
                            "phase, op_s and the bus model only set how long the BLOCKED zone lasts (~19 s FP / ~16 s Dump "
                            "at phase 0 on an idle bus)",
        "invariant": "INV-HF-NO-SILENT-LOSS", "corpus": ["HF-04-b", "HF-04-c"]},
    "F-HF04-3": {
        "scenario": "HF-04", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "availability / diagnostics, low: the arm validation only refuses (immediately and visibly); the firmware "
                    "START gate stays authoritative; the refusal names the wrong cause",
        "title": "a Dump schedule armed while a Free Power lease runs - for any window, today or later - is REJECTED as "
                 "overlapping 'a TOU slot with a charge source set': the slots are the Free Power override's own temporary "
                 "grid-charge settings",
        "mechanism": "Free Power writes 274-279 = (snapshot & 0xFFFC) | 1 (grid charge on every slot) with an exact readback, "
                     "and its successful START runs the configuration poll whose Block B response publishes the six TOU "
                     "charge text sensors from the live 274-279 (fw.tou_publish); DGS1's FP-overlap check only applies "
                     "while the FP schedule is ARMED (dgs1.arm_overlap) and FPS1 disarms right after its start, so the "
                     "arm-time walk (dgs1.tou_walk) sees Grid on all six slots - all 24 h - for the whole lease plus its "
                     "restore and readback, and refuses (dgs1.tou_refusal); an arm after the FP restore and readback is "
                     "accepted; this narrows the cross-domain gate collision to the ~1 s between FPS1's disarm and the "
                     "closing readback (an arm there is ARMED and FAILS at the gate: F-HF04-1 mirrored), it does not remove "
                     "it; the firmware's own Dump START checks Free Power ownership before TOU, so the package's mirror "
                     "gives a different reason from the firmware it mirrors",
        "anchors": ["fw.tou_publish", "dgs1.tou_walk", "dgs1.tou_refusal", "dgs1.arm_overlap"],
        "prior_art": "none: the Dump schedule incident record "
                     "(docs/incidents/2026-10-12-scheduled-dump-to-grid-start-review.md, 'What was checked and is NOT a "
                     "defect') lists the arm-time TOU check as not a defect without the Free Power overlay case; no "
                     "KNOWN_RISKS id",
        "reachability": "INFERRED, source-traced (FP's all-slot Grid write with mandatory exact readback, the Block B publish "
                        "of values[33..38] = 274-279; the lab's display-sensor MODEL uses the firmware's own format rules and "
                        "the same cache); not proven on hardware; any Dump arm during a Free Power lease",
        "repair": "package only (DGS1 arm validation), refusal only: before the TOU walk, refuse with an explicit 'Free Power "
                  "is active until <end>; arm the Dump after it ends' text while binary_sensor.ecco_clock_dongle_free_power_"
                  "active, _snapshot_valid or _operation_in_progress is on (skipping the walk instead would accept the arm and "
                  "fail at fire time, the mirror of F-HF04-1); a seconds-long gap before the post-restore readback lands "
                  "remains (acceptable, or covered by the same text); no firmware change",
        "model_dependence": "the TOU slot sensors (MODEL: derived from manual_cfg_reg250..255/274..279_raw once Block B has "
                            "landed, with the firmware's own format rules); the width of the arm window before the closing "
                            "readback (ds.Sim's no-op Block A -> B delay)",
        "invariant": "INV-HF-ARM-INTENT", "corpus": ["HF-04-d"]},
    "F-HF06-1": {
        "scenario": "HF-06", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "diagnostics (test-model fidelity and coverage), low; not a product defect: in the lab, the real firmware "
                    "+ package chain restores automatically and completely",
        "title": "the HA dongle models keep a failed START's snapshot pending until End & Restore and SMR1 suite [3] asserts "
                 "it as the nominal case; with the real firmware source in the lab a single failed START restores by itself "
                 "(Dump at its next watchdog tick, Free Power inline) and SMR1 then restores the owner's values with no owner "
                 "action; a long-pending snapshot is reachable only when the automatic restore also fails",
        "mechanism": "D.DumpDongle 'verify_failed' (model.dump_verify_failed) and 'commit_failed' (model.dump_commit_failed, "
                     "despite its own 'restoring ... automatically' text) set the snapshot and never clear it, and the model "
                     "has no End path (the SMR1 suite clears the flag by hand); S.Dongle 'write_failed' "
                     "(model.fp_write_failed) likewise; the firmware's Dump watchdog restores a 'snapshot valid but not "
                     "active' state (fw.dump_wd_comment, fw.dump_wd_interrupted; end reason 'INTERRUPTED TRANSACTION') and "
                     "the Free Power START restores inline after ACTIVATION VERIFY / WRITE FAILED (fw.fp_verify_failed, "
                     "fw.fp_write_failed); End & Restore uses the same restore gate as the watchdog, so it has no power "
                     "the watchdog lacks; SMR1 suite [3] (test.smr1_premise_dump / test.smr1_premise_fp) therefore tests a "
                     "reachable SMR1 input sequence under the wrong cause and label, and the realistic timing and order "
                     "(the snapshot clears in < 15 s, possibly while DGS1's script still runs; the FP inline restore) is "
                     "untested; five more SMR1 checks reuse verify_failed + end_and_restore (test :591, :699, :716, :728, "
                     ":829)",
        "anchors": ["model.dump_verify_failed", "model.dump_commit_failed", "model.fp_write_failed", "fw.dump_wd_comment",
                    "fw.dump_wd_interrupted", "fw.fp_verify_failed", "fw.fp_write_failed", "test.smr1_premise_dump",
                    "test.smr1_premise_fp", "doc.fp_restores_itself", "doc.dump_snapshot_residual", "doc.fp_watchdog_row"],
        "prior_art": "the firmware behaviour is documented (doc.fp_restores_itself, doc.dump_snapshot_residual, the firmware "
                     "comment fw.dump_wd_comment; doc.fp_watchdog_row is the Free Power watchdog row); the test-model "
                     "divergence is not; no KNOWN_RISKS id",
        "reachability": "not a field defect; the HA models' end state (snapshot pending, SMR1 OWED, the schedule's numbers on) "
                        "is reachable when the firmware's own restore keeps failing (VERIFIED here with a compound fault); "
                        "only the model's cause (a single transient START failure) and its 'owner must press End & Restore' "
                        "premise are unreachable",
        "repair": "test only, no product write path: add an opt-in auto-restore to D.DumpDongle / S.Dongle (a constructor flag "
                  "or a new outcome name, leaving the default so the DGS1 / FPS1 / FSW1 suites keep their assertions); in "
                  "SMR1 suite [3] add the realistic chain for both domains (the snapshot clears ~15 s (Dump) or at once (FP) "
                  "after the failure, Operation In Progress pulsed during the restore; no SMR1 write while the snapshot or op "
                  "is on; RESTORED with no End press); keep the retained-snapshot checks but relabel them 'automatic restore "
                  "also failed' and drop the End & Restore premise; fix 'commit_failed' the same way",
        "model_dependence": "none for the real chain (firmware truth); the simulated timings (Dump restore 11.7 s and SMR1 "
                            "RESTORED 17.6 s after the failed gate here; SMR1 9.6-20.6 s across phases on an idle bus, up to "
                            "~33 s on the recorded-busy-window bus model) depend on the watchdog phase, the bus model and "
                            "the 5 s SMR1 settle",
        "invariant": "INV-HF-MODEL-FIDELITY", "corpus": ["HF-06-a", "HF-06-b"]},
    "F-HF06-2": {
        "scenario": "HF-06", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "diagnostics, low: the advice is redundant and never dangerous (the End press is refused with no write; "
                    "the notification itself says to check the status first, which by then reads RESTORED OK)",
        "title": "DGS1's 'did NOT start' alert repeats the firmware's 'snapshot retained - press End & Restore Now', but the "
                 "firmware's watchdog restores at its next tick (here 8.7 s after the alert); the stale advice then persists "
                 "in the result and the notification until a later start or arm, and an End press finds nothing",
        "mechanism": "the Dump START failure text (fw.dump_start_failed) asks for End & Restore although the Dump watchdog's "
                     "'snapshot valid but not active' rule (fw.dump_wd_interrupted) restores at the next tick (the sibling "
                     "branch's text already says 'restoring original settings automatically', fw.dump_auto_text); DGS1 "
                     "copies the status into its result and alert and nothing corrects it later; a later End press gives "
                     "'END IGNORED - no saved Dump to Grid snapshot' (fw.dump_end_ignored); mitigations: the notification "
                     "says to check the status first (dgs1.check_first) and the dashboard card shows no button "
                     "(card.no_button)",
        "anchors": ["fw.dump_start_failed", "fw.dump_auto_text", "fw.dump_wd_interrupted", "fw.dump_end_ignored",
                    "dgs1.check_first", "card.no_button", "doc.dump_snapshot_residual"],
        "prior_art": "none for the stale advice (the fix for row D3 of the Dump schedule incident record surfaced this exact "
                     "text on purpose; the snapshot residual is a different case); no KNOWN_RISKS id",
        "reachability": "INFERRED: a rare trigger (an activation write / verify failure after the durable snapshot; field "
                        "frequency UNKNOWN), deterministic once triggered while the automatic restore succeeds; with a "
                        "persistent fault the restore fails and End gives a deferral instead (the advice is redundant, not "
                        "empty); a minority outcome when a watchdog tick lands between the failure publish and DGS1's read "
                        "carries 'RESTORED OK' / 'END DEFERRED' instead",
        "repair": "text only, no write path, no gate weakened: smallest (package, DGS1's recorded-result template): when the "
                  "copied status contains 'snapshot retained', append 'the dongle restores it automatically at its next "
                  "watchdog check; check the Dump to Grid status before pressing End'; root cause (firmware): use the "
                  "sibling branch's 'restoring original settings automatically' wording - needs a firmware rebuild and an "
                  "OTA update, and the string is pinned in model.dump_verify_failed (change it with F-HF06-1)",
        "model_dependence": "none for the texts; the restore instant is the first Dump watchdog tick after the failure (0-15 s "
                            "by phase, later on a busy bus) and the alternate outcome depends on the read-versus-tick timing",
        "invariant": "INV-HF-ALERT-TRUTH", "corpus": ["HF-06-a"]},
    "F-HF06-3": {
        "scenario": "HF-06", "classification": "FINDING-NEW", "confidence": "high",
        "severity": "diagnostics, low: the failed start is still detected and alerted, the restore is verified, the owner's "
                    "values come back; only the cause text is missing",
        "title": "a scheduled Free Power whose activation write or verify fails is recorded and alerted as 'FAILED TO START - "
                 "RESTORED OK - original inverter settings verified (start transaction began ...)': the failure reason is "
                 "lost from FPS1's result and alert",
        "mechanism": "the firmware publishes 'ACTIVATION VERIFY FAILED - restoring saved snapshot' (fw.fp_verify_failed; "
                     "ACTIVATION WRITE FAILED, fw.fp_write_failed, likewise) and restores inline in the same START, so when "
                     "FPS1 sees Operation In Progress go off the status already reads 'RESTORED OK'; FPS1 records that "
                     "status (fps1.began_failed) and the alert copies it, contrary to the documented 'naming the reason' "
                     "(doc.fp_alert_reason); the HA model publishes ACTIVATION WRITE FAILED and never restores "
                     "(model.fp_write_failed), and the FPS1 suite asserts that text (test.fps1_model_write_failed), so the "
                     "HA suites never saw this outcome",
        "anchors": ["fw.fp_verify_failed", "fw.fp_write_failed", "fps1.began_failed", "doc.fp_alert_reason",
                    "model.fp_write_failed", "test.fps1_model_write_failed"],
        "prior_art": "only the inline restore is documented (doc.fp_restores_itself); the lost reason is not; no KNOWN_RISKS "
                     "id; shares a root with F-HF06-1 (cross-referenced, not merged)",
        "reachability": "INFERRED: a rare trigger (field frequency UNKNOWN), near-certain once it occurs, for every "
                        "failure after the snapshot (write failed; verify failed / error / timeout / refused); not for "
                        "'could not capture complete inverter snapshot' (no restore follows); on hardware the inline "
                        "restore may instead be deferred by the bus turnaround, and FPS1 would record 'END DEFERRED - Modbus "
                        "bus busy ...' - the reason is lost either way; HA's status history may briefly hold the real text "
                        "(the lab shows it; ESPHome's API batching probably merges it on hardware, INFERRED)",
        "repair": "package only (FPS1): base the text on firmware truth (snapshot_valid off -> 'start transaction failed; "
                  "the dongle restored the saved settings'; still on -> 'the dongle holds the settings and restores them "
                  "itself'), keep the 'FAILED' prefix (the loop and alert test r.startswith('FAILED')), stay within the "
                  "255-character helper, drive no logic from the text; this makes the text truthful but cannot recover the "
                  "cause; root cause (firmware): a separate read-only latched last-start-failure text sensor (needs an OTA); "
                  "do not put the cause into the RESTORED OK text (card patterns match words like FAILED); test follow-up "
                  "with F-HF06-1",
        "model_dependence": "the recorded 'RESTORED OK' text comes from the bus-idle restore gate (the bus is sampled at entry; "
                            "the 600 ms turnaround after the START's own reply is not modelled: field variant 'END DEFERRED', "
                            "INFERRED); the lost reason holds in both variants (VERIFIED for the harness variant)",
        "invariant": "INV-HF-ALERT-TRUTH", "corpus": ["HF-06-b"]},
}

# Dedupe against the other lab suites' findings: a finding whose root cause another suite owns is printed 'DUPLICATE of
# <owner id>, not counted' and left out of the LAB-SUMMARY finding count (its finding-reproduces check still runs). Compared
# with every other suite's findings: none of the seven is a duplicate. RELATED names findings that share a code locus or a
# symptom with one of ours but not its root cause (cross-references only; both stay counted in their own suites).
DUPLICATE_OF: dict = {}
RELATED = {
    "F-HF04-3": "F-HF08-3 (test_lab_dst_rtc, FINDING-KNOWN:SG-25) concerns the same DGS1 arm-time TOU walk (dgs1.tou_walk) "
                "with a different root: local-minute arithmetic on a DST change night; here the walk reads the Free Power "
                "override's own grid-charge slots on an ordinary day, and the SG-25 UTC-walk repair leaves this refusal as is",
    "F-HF06-3": "F-FW06-1 (test_lab_fw_durability) and its HA-side copy F-HF07-3 (test_lab_ha_phantom) also end in an FPS1 "
                "result that misstates the cause, with a different root: the firmware START commit-failure cascade (a false "
                "'ACTIVATION WRITE FAILED', then END IGNORED); here every firmware text is true (a genuine activation verify "
                "failure, fw.fp_verify_failed, then the inline restore) and FPS1's read point loses it; the F-FW06-1 repair "
                "(the commit-failure branch) does not touch this branch",
}


# ---------------------------------------------------------------------------------------------------------------------------
# helpers (observers only; no control decision is made here)
# ---------------------------------------------------------------------------------------------------------------------------
def asc(s) -> str:
    """ASCII-safe text for printing (FPS1 / DGS1 ARMED texts contain a bullet)."""
    return str(s).encode("ascii", "replace").decode("ascii")


def finding_line(fid: str, text: str) -> str:
    """T.finding_line, prefixed 'DUPLICATE of <owner id>, not counted' for a finding another suite owns (DUPLICATE_OF)."""
    dup = DUPLICATE_OF.get(fid)
    return T.finding_line(fid, f"DUPLICATE of {dup}, not counted: {text}" if dup else text)


def loc(utc) -> str:
    y, mo, d, h, mi, s, _dst = C.local_fields(int(utc))
    return f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"


def rel(t) -> float:
    return round(t - ST, 3)


def evs(cw, kind, **match) -> list:
    return [e for e in cw.log.events(kind=kind) if all(e["data"].get(k) == v for k, v in match.items())]


def fw_texts(cw, dom, after=-math.inf) -> list:
    return [(e["t_utc"], e["data"]["text"]) for e in evs(cw, "fw.status", dom=dom) if e["t_utc"] > after]


def start_presses(cw, dom, after=-math.inf) -> list:
    return [e for e in evs(cw, "dongle.cmd", svc="button.press", fid=H.START_BUTTON[dom]) if e["t_utc"] > after]


def notif_calls(cw, nid) -> list:
    return [(e["t_utc"], e["data"]["svc"].split(".")[1]) for e in evs(cw, "ha.call")
            if e["data"]["svc"].startswith("persistent_notification.")
            and (e["data"]["data"] or {}).get("notification_id") == nid]


def lease_edges(cw, dom) -> tuple:
    """(projected lease start instants, projected lease end instants: active and snapshot both off)."""
    ed = [e["data"] for e in evs(cw, "dongle.edge", dom=dom)]
    return [d["at"] for d in ed if d["act"]], [d["at"] for d in ed if not d["act"] and not d["snap"]]


def txn_for(cw, eid) -> dict:
    return next(e["data"] for e in evs(cw, "dongle.txn") if (e["data"]["cmd"] or {}).get("e") == eid)


def wd_slots(cw, job) -> list:
    """UTC instants of every run of a firmware job since job_trace was enabled (one boot: uptime and UTC move together)."""
    fw = cw.fw
    return [fw.utc_ms / 1000 - (fw.sim.now_ms - up) / 1000 for up, j in fw.job_trace if j == job]


RESTORE_KEY = {"fp": 232, "dump": 244}            # the enable register whose restoring write ends the override itself


def record_writes(cw) -> list:
    """Observer only: wraps THIS world's ds.Sim event hook (per instance, nothing else is changed) to record each Modbus write
    as (projected end instant, addr, script stack). The instant is the core's own projection of the open run (its recorder:
    t0 + ops * op_s + commits * commit_s, _lab_ha MODEL ASSUMPTIONS 'Projection'); None outside a recorded run."""
    rec, sim, fw = [], cw.fw.sim, cw.fw
    orig = sim.event_hook

    def hook(ev):
        orig(ev)
        if ev[0] == "write":
            run = fw.recorder
            rec.append((None if run is None else run.t0 + run.elapsed(), ev[1], list(sim.script_stack)))
    sim.event_hook = hook
    return rec


def physical_end(rec, dom, window_end):
    """The physical override end relative to the window end: the end of the first write of the domain's enable register
    (RESTORE_KEY) by a restore script after the lease (None if there was none)."""
    return next((round(t - window_end, 3) for t, addr, scripts in rec if addr == RESTORE_KEY[dom] and t is not None
                 and t > window_end - 200 and any("restore" in s for s in scripts)), None)


def fw_numbers(cw, dom) -> tuple:
    return tuple(cw.fw.sim.ent(cw.dongle.entity_map[e][0]).state for e in H.NUMBERS[dom])


def ha_numbers(cw, dom) -> tuple:
    return tuple(cw.ha_state(e) for e in H.NUMBERS[dom])


def owner_strs(dom) -> tuple:
    return tuple(f"{float(v)}" for v in OWNER[dom])


def inv_ids(viol) -> list:
    return [v["inv"] for v in viol]


def fw_inv(cw) -> list:
    """Every firmware invariant (_lab_fw.INVARIANTS, the default set incl. INV-BOOT-MIRROR) over the merged log, judged WITH
    the FirmwareWorld (as CoupledWorld.invariants does), so INV-NO-SILENT-OVERRIDE also evaluates the state at the end of the
    log (world.quiet_state()) and INV-RESTORE-BOUND evaluates up to the world clock."""
    return L.check_invariants(cw.log, world=cw.fw)


def check_no_press_into_lease(events) -> list:
    """Suite-local INV-HF-NO-PRESS-INTO-LEASE (module docstring): every dongle.cmd START press sent by a schedule run while the
    firmware truth (the command's obligation snapshot) shows that domain's lease active."""
    start_dom = {v: k for k, v in H.START_BUTTON.items()}
    out = []
    for e in (events if isinstance(events, list) else list(events)):
        d = e["data"]
        if e["kind"] == "dongle.cmd" and d["svc"] == "button.press" and d["fid"] in start_dom and d["by"] == "schedule":
            dom = start_dom[d["fid"]]
            if d["obl"][dom]["act"]:
                out.append({"inv": "INV-HF-NO-PRESS-INTO-LEASE", "seq": e["seq"], "tags": [],
                            "detail": f"scheduled {dom} START press at {e['t_utc']} while the {dom} lease is active"})
    return out


def new_world(*, bus=IDLE, ph=0.0, fw_text=None, pk=None) -> H.CoupledWorld:
    fwk = {"warmup_s": WARMUP}
    if fw_text is not None:
        fwk["fw"] = L.load_fw(fw_text)     # an in-memory mutant (negative controls only)
    return H.CoupledWorld(U0, bus=bus, wd_phase_s=float(ph), fw_world_kwargs=fwk, package_texts=pk)


def stage_owner(cw, dom, at=U0 + 30) -> None:
    for e, v in zip(H.NUMBERS[dom], OWNER[dom]):
        cw.owner_set(e, v, at_utc=at)


def arm(cw, dom, start_local=START_LOCAL, minutes=None, at=U0 + 60) -> None:
    if dom == "fp":
        cw.arm_schedule("fp", start_local, minutes or REQ_FP[1], REQ_FP[0], at_utc=at)
    else:
        cw.arm_schedule("dump", start_local, minutes or REQ_DUMP[1], REQ_DUMP[0], stop_soc=REQ_DUMP[2], at_utc=at)


def mutate(text: str, old: str, new: str, n: int = 1) -> str:
    """An in-memory exact-count text mutation (negative controls); a wrong count is a harness error (MUTANT-INVALID)."""
    c = text.count(old)
    if c != n or old == new:
        raise L.LabHarnessError(f"mutation anchor found {c}x (expected {n}): {old[:70]!r}")
    return text.replace(old, new)


def scheduled_run(dom, *, bus=IDLE, ph=0.0, minutes=None, owner=True, plant=None, fw_text=None, pk=None) -> dict:
    """One scheduled run (12:00 start) to its window end + 150 s; the observations the sweeps and controls need. Only the
    core's LabUnsupported (an interleaving inside a projected transaction) is turned into an UNSUPPORTED point."""
    minutes = minutes or (REQ_FP[1] if dom == "fp" else REQ_DUMP[1])
    plant = (dom == "dump" and minutes > 5) if plant is None else plant
    cw = new_world(bus=bus, ph=ph, fw_text=fw_text, pk=pk)
    try:
        rec = record_writes(cw)
        if plant:
            cw.dump_plant()
        if owner:
            stage_owner(cw, dom)
        arm(cw, dom, minutes=minutes)
        cw.run_until(ST + minutes * 60 + 150)
        ov = cw.window_overruns()
        return {"ov": ov[0]["overrun_s"] if len(ov) == 1 else None, "last": cw.last_result(dom),
                "phys": physical_end(rec, dom, ST + minutes * 60),
                "fw": cw.fw_status(dom), "smr1": cw.smr1_state(dom), "nums": ha_numbers(cw, dom),
                "presses": len(start_presses(cw, dom)), "hf": inv_ids(cw.invariants()),
                "fwinv": inv_ids(fw_inv(cw)), "window": cw.invariants(["INV-HF-WINDOW"]),
                "nfs": cw.invariants(["INV-HF-NO-FALSE-SUCCESS"]), "status": cw.schedule_status(dom),
                "notes": sorted(cw.notifications())}
    except H.LabUnsupported as exc:
        return {"unsupported": str(exc)[:140]}
    finally:
        cw.close()


def point_ok(dom, r) -> bool:
    """A scheduled run with the owner's values staged: started, restored by the firmware, the owner's values back (SMR1)."""
    return ("unsupported" not in r and r["last"].startswith("STARTED OK") and r["fw"].startswith("RESTORED OK")
            and r["smr1"].startswith("RESTORED") and r["nums"] == owner_strs(dom) and not r["fwinv"])


# ---------------------------------------------------------------------------------------------------------------------------
# [0] static: anchors and the scenario tables
# ---------------------------------------------------------------------------------------------------------------------------
def section_static() -> None:
    print("[0] static: every source anchor occurs exactly once; the SCENARIOS / FINDINGS tables use the lab vocabulary")
    bad = []
    for key, (path, text) in sorted(ANCHORS.items()):
        n, _line = T.anchor_count(path, text)
        if n != 1:
            bad.append((key, n))
            continue
        print(f"  info  anchor {key}: {path}:{T.anchor_line(path, text)}")
    check(f"every scenario / finding source anchor occurs exactly once in its file ({len(ANCHORS)} anchors)", not bad,
          str(bad))
    used = {a for s in SCENARIOS for a in s["anchors"]} | {a for f in FINDINGS.values() for a in f["anchors"]}
    check("every anchor key the tables cite is defined, and every defined anchor is cited", used == set(ANCHORS),
          str(sorted(used ^ set(ANCHORS))))
    probs = []
    for s in SCENARIOS:
        kind, rid = T.parse_classification(s["classification"])
        if s["grade"] not in T.GRADES or s["confidence"] not in T.CONFIDENCES or s["priority"] not in T.PRIORITIES:
            probs.append(s["id"])
        if any(FINDINGS[f]["scenario"] != s["id"] for f in s["findings"]) or (kind == "FINDING-NEW") != bool(s["findings"]):
            probs.append(s["id"] + " findings")
    for fid, f in FINDINGS.items():
        T.parse_classification(f["classification"])
        if f["confidence"] not in T.CONFIDENCES or not set(f["corpus"]) <= {c for s in SCENARIOS for c in s["corpus"]}:
            probs.append(fid)
    for fid, owner in DUPLICATE_OF.items():
        if fid not in FINDINGS or not isinstance(owner, str) or not owner.startswith("F-") or owner in FINDINGS:
            probs.append(f"{fid} duplicate_of")
    probs += [f"{fid} related" for fid in RELATED if fid not in FINDINGS or fid in DUPLICATE_OF]
    check("the tables are well formed (classification / grade / confidence / priority vocabulary, findings belong to their "
          "scenario, finding corpus ids are scenario corpus ids, a DUPLICATE names another suite's finding id)", not probs,
          str(probs))
    hand = [{"seq": 0, "t_utc": ST, "kind": "dongle.cmd", "data": {"svc": "button.press", "fid": H.START_BUTTON["fp"],
                                                                     "by": "schedule", "obl": {"fp": {"act": True},
                                                                                              "dump": {"act": False}}}}]
    clean = [dict(hand[0], data=dict(hand[0]["data"], obl={"fp": {"act": False}, "dump": {"act": False}}))]
    owner = [dict(hand[0], data=dict(hand[0]["data"], by="owner"))]
    check("harness negative control: the suite-local INV-HF-NO-PRESS-INTO-LEASE checker catches a hand-built scheduled press "
          "into an active lease, and not a press with no lease or an owner's press",
          inv_ids(check_no_press_into_lease(hand)) == ["INV-HF-NO-PRESS-INTO-LEASE"]
          and not check_no_press_into_lease(clean) and not check_no_press_into_lease(owner))


def section_fw_inv_control() -> None:
    print("[0b] harness negative control: fw_inv judges the end of the merged log with the FirmwareWorld (a 5-min scheduled "
          "Free Power, then a white-box change of register 244 with no event and no obligation)")
    cw = new_world()
    try:
        arm(cw, "fp", minutes=5)
        cw.run_until(ST + 300 + 150)
        clean, n = fw_inv(cw), len(cw.log)
        cw.fw.bank[244] = 0          # in memory only: the inverter shows Allow Export, nothing logged, nothing in RAM
        v, log_only = fw_inv(cw), L.check_invariants(cw.log)
        check("harness negative control: a clean coupled run gives no firmware invariant violation; after a white-box "
              "register change with no event the log alone passes, fw_inv reports exactly one INV-NO-SILENT-OVERRIDE at "
              "the last event via world.quiet_state(), and nothing is logged by the check",
              clean == [] and log_only == [] and inv_ids(v) == ["INV-NO-SILENT-OVERRIDE"] and v[0]["seq"] == n - 1
              and "world.quiet_state()" in v[0]["detail"] and len(cw.log) == n, str(v)[:200])
    finally:
        cw.close()


# ---------------------------------------------------------------------------------------------------------------------------
# HF-01 scheduled runs end to end and the window-end overrun
# ---------------------------------------------------------------------------------------------------------------------------
def section_hf01_fp() -> dict:
    print("[1] HF-01 scheduled Free Power 2026-10-21 12:00 BST, 8000 W / 60 min (synthetic), owner's 5000 W / 45 min staged "
          "before; never-busy bus, watchdog phase 0")
    cw = new_world()
    try:
        cw.fw.job_trace = []
        rec = record_writes(cw)
        stage_owner(cw, "fp")
        arm(cw, "fp")
        cw.run_until(U0 + 65)
        armed = (cw.last_result("fp"), cw.schedule_status("fp"), fw_numbers(cw, "fp"), ha_numbers(cw, "fp"))
        print(f"  info  after the arm: {asc(armed[0])!r}")
        check("HF-01 FP: the arm is accepted (ARMED for 2026-10-21 12:00:00) and the owner's synthetic manual values 5000 W / "
              "45 min are on the dongle (firmware numbers and HA) before the start",
              armed[0].startswith("ARMED - 2026-10-21 12:00:00") and armed[1] == "ARMED" and armed[2] == (5000.0, 45.0)
              and armed[3] == owner_strs("fp"), str(armed))
        cw.run_until(ST + 1800)
        mid = {"last": cw.last_result("fp"), "status": cw.schedule_status("fp"), "fw": cw.fw_status("fp"),
               "ha": cw.ha_visible(), "smr1": cw.smr1_state("fp"), "nums": fw_numbers(cw, "fp"),
               "end": cw.fw.globals_view(["free_power_end_epoch"])["free_power_end_epoch"],
               "smr1_writes": len([e for e in evs(cw, "dongle.cmd", by="smr1")])}
        print(f"  info  FPS1 last result: {mid['last']!r}; firmware: {mid['fw']!r}")
        check("HF-01 FP: FPS1 records STARTED OK - 8000W for 60 min (attempt 1; ends by 13:00)",
              mid["last"] == "STARTED OK - 8000W for 60 min (attempt 1; ends by 13:00)", mid["last"])
        check("HF-01 FP mid-lease: FPS1 ACTIVE, firmware 'ACTIVE - VERIFIED OK; 120A grid charge; automatic restore armed' "
              "(8000 W at the synthetic 52 V clamps to the synthetic register 230 ORIGINAL 120 A), HA Free Power Active and "
              "Snapshot Valid on, the dongle numbers hold the schedule's 8000 / 60, SMR1 OWED and no SMR1 write yet",
              mid["status"] == "ACTIVE" and mid["fw"] == "ACTIVE - VERIFIED OK; 120A grid charge; automatic restore armed"
              and mid["ha"]["fp_active"] == "on" and mid["ha"]["fp_snapshot_valid"] == "on"
              and mid["nums"] == (8000.0, 60.0) and mid["smr1"].startswith("OWED") and mid["smr1_writes"] == 0, str(mid))
        cw.run_until(ST + 3600 + 150)
        txn = txn_for(cw, S.E_PRESS)
        check("HF-01 FP: the firmware lease end epoch is the START gate second + 60 min on the UTC epoch",
              mid["end"] == int(txn["t0"]) + 3600, f"{mid['end']} vs {int(txn['t0'])} + 3600")
        slot = min(t for t in wd_slots(cw, "fp_wd") if t >= mid["end"] - 1e-6)
        after = fw_texts(cw, "fp", after=txn["until"])
        check("HF-01 FP: the lease ends at its epoch - the firmware's first end action is RESTORING at the first FP watchdog "
              "slot at or after the end epoch, less than one 15 s period after it, nothing earlier",
              bool(after) and abs(after[0][0] - slot) < 1e-6 and after[0][1].startswith("RESTORING")
              and 0 <= slot - mid["end"] < 15, f"{after[:1]} slot {rel(slot)}")
        bank = cw.fw.bank_view(sorted(int(a) for a in ORIG))
        check("HF-01 FP: the firmware restore verifies ('RESTORED OK - original inverter settings verified'), every owned "
              "register back at the synthetic ORIGINAL, durable marker CLEAR",
              cw.fw_status("fp") == "RESTORED OK - original inverter settings verified" and bank == ORIG
              and cw.fw.nvs_marker("fp") == "CLEAR", str(bank))
        smr = cw.smr1_state("fp")
        print(f"  info  SMR1: {smr!r}")
        check("HF-01 FP: SMR1 restores the owner's 5000 W / 45 min (HA and firmware numbers) after the firmware restore and "
              "says so", smr.startswith("RESTORED 2026-10-21 13:00 - restored: charge power 5000 W, duration 45 min")
              and ha_numbers(cw, "fp") == owner_strs("fp") and fw_numbers(cw, "fp") == (5000.0, 45.0), smr)
        check("HF-01 FP: FPS1 ends COMPLETED, disarmed, write enable off, no notification",
              cw.schedule_status("fp") == "COMPLETED" and cw.ha_state(H.ARMED["fp"]) == "off"
              and cw.ha_state(S.E_ARM) == "off" and cw.notifications() == {})
        hf, fwv = cw.invariants(), fw_inv(cw)
        check("HF-01 FP: no coupled INV-HF-* (window bound 30 s) and no firmware invariant violation; UTC-monotonic log",
              not hf and not fwv and cw.log.utc_regressions() == [], str(hf + fwv)[:300])
        ov = cw.window_overruns()[0]
        ends = lease_edges(cw, "fp")[1]
        phys = physical_end(rec, "fp", ST + 3600)
        print(f"  info  lease-end edge {ov['overrun_s']} s = start offset {int(txn['t0']) - ST} s (end epoch 13:00:"
              f"{int(txn['t0']) - ST:02d}) + watchdog latency {round(slot - mid['end'], 3)} s + restore "
              f"{round(ends[0] - slot, 3)} s; physical override end (first restoring write of 232) {phys} s")
        check(f"HF-01 FP nominal: INV-HF-WINDOW holds - the lease ends {ov['overrun_s']} s after the window end (the override "
              f"itself {phys} s), within the HA suites' model-only {CLAIM_S:.0f} s bound",
              ov["overrun_s"] is not None and phys is not None and 0 < phys < ov["overrun_s"] <= CLAIM_S)
        return {"ov": ov["overrun_s"], "phys": phys, "digest": cw.log.digest(), "n": len(cw.log)}
    finally:
        cw.close()


def section_hf01_fp_busy_start() -> dict:
    print("[2] HF-01 the same Free Power run with a synthetic bus-busy window over the first 10 s of the start (explicit "
          "BusModel window): FPS1's transient retry")
    cw = new_world(bus=H.BusModel(windows=[(ST, ST + 10.0)]))
    try:
        rec = record_writes(cw)
        stage_owner(cw, "fp")
        arm(cw, "fp")
        cw.run_until(ST + 3600 + 150)
        pr = start_presses(cw, "fp")
        ts = [rel(e["t_utc"]) for e in pr]
        writes_before = [e for e in evs(cw, "fw.write") if e["t_utc"] < pr[-1]["t_utc"] - 1e-6]
        busy = [x for t, x in fw_texts(cw, "fp") if x.startswith("REJECTED - Modbus bus busy with another transaction")]
        print(f"  info  START presses at {ts} s after 12:00; result {cw.last_result('fp')!r}")
        check("HF-01 FP busy start: the gate refuses the presses inside the busy window ('REJECTED - Modbus bus busy with "
              "another transaction'), nothing is written, FPS1 retries (transient) and the third press starts: STARTED OK "
              "8000W for 60 min (attempt 3) with the full duration kept; the firmware gate-pass counter reads 1",
              len(pr) == 3 and busy and not writes_before
              and cw.last_result("fp") == "STARTED OK - 8000W for 60 min (attempt 3; ends by 13:00)"
              and cw.fw.sim.g["free_power_start_attempts"] == 1, f"{ts} {busy} {len(writes_before)}")
        check("HF-01 FP busy start: SMR1 saved the owner's value once despite three stagings and restores 5000 W / 45 min; "
              "the firmware restore verifies", cw.smr1_state("fp").startswith("RESTORED 2026-10-21 13:00 - restored: charge "
                                                                               "power 5000 W, duration 45 min")
              and ha_numbers(cw, "fp") == owner_strs("fp") and cw.fw_status("fp").startswith("RESTORED OK"))
        hf = cw.invariants([n for n in H.HF_INVARIANTS if n != "INV-HF-WINDOW"])
        check("HF-01 FP busy start: every other INV-HF-* and every firmware invariant holds",
              not hf and not fw_inv(cw), str(hf)[:200])
        win = cw.invariants(["INV-HF-WINDOW"])
        ov, phys = cw.window_overruns()[0]["overrun_s"], physical_end(rec, "fp", ST + 3600)
        print(f"  info  busy start: lease-end edge {ov} s, physical override end {phys} s after the window end")
        return {"ov": ov, "phys": phys, "win": win}
    finally:
        cw.close()


def sweep(dom, phases, buses=BUSES) -> list:
    rows = []
    for name, bus in buses:
        for ph in phases:
            r = scheduled_run(dom, bus=bus, ph=ph)
            if "unsupported" in r:
                UNSUPPORTED.append(("HF-01-UNS", f"{dom} bus {name} phase {ph}: {r['unsupported']}"))
            rows.append((name, ph, r))
    return rows


def report_sweep(label, dom, rows) -> dict:
    by = {}
    for name, ph, r in rows:
        by.setdefault(name, []).append((ph, r.get("ov"), r.get("phys")))
    for name, pts in by.items():
        vals = [o for _p, o, _x in pts if o is not None]
        phys = [x for _p, _o, x in pts if x is not None]
        print(f"  info  {label} {dom} bus {name!r}: (watchdog phase, lease-end edge s, physical end s) {pts}; edge min "
              f"{min(vals)} max {max(vals)}; physical min {min(phys)} max {max(phys)}")
    vals = [r["ov"] for _n, _p, r in rows if r.get("ov") is not None]
    phys = [r["phys"] for _n, _p, r in rows if r.get("phys") is not None]
    bad = [(n, p) for n, p, r in rows if not point_ok(dom, r) or r.get("phys") is None or not r["phys"] < r["ov"]]
    check(f"HF-01 {dom} {label} sweep ({len(rows)} points: watchdog phase x bus model): every point starts, ends, restores "
          "and SMR1 restores the owner's values (no unsupported point); the first restoring write precedes the lease-end "
          "edge", not bad, str(bad))
    return {"min": min(vals), "max": max(vals), "pmin": min(phys), "pmax": max(phys), "rows": rows}


def section_hf01_dump() -> dict:
    print("[4] HF-01 scheduled Dump to Grid 2026-10-21 12:00 BST, 3000 W / 30 min / Stop SOC 20 % (synthetic, dump_plant "
          "MODEL), owner's 1500 W / 30 % / 45 min staged before; never-busy bus, watchdog phase 0")
    cw = new_world()
    try:
        cw.fw.job_trace = []
        rec = record_writes(cw)
        cw.dump_plant()
        stage_owner(cw, "dump")
        arm(cw, "dump")
        cw.run_until(U0 + 65)
        armed = (cw.last_result("dump"), fw_numbers(cw, "dump"))
        check("HF-01 Dump: the arm is accepted (ARMED for 2026-10-21 12:00:00) and the owner's 1500 W / 30 % / 45 min are on "
              "the dongle before the start", armed[0].startswith("ARMED - 2026-10-21 12:00:00")
              and armed[1] == (1500.0, 30.0, 45.0), asc(armed))
        cw.run_until(ST + 900)
        mid = (cw.schedule_status("dump"), cw.fw_status("dump"), cw.ha_visible()["dump_active"], cw.smr1_state("dump"),
               fw_numbers(cw, "dump"), cw.fw.globals_view(["dump_end_epoch"])["dump_end_epoch"])
        cw.run_until(ST + 1800 + 150)
        last = cw.last_result("dump")
        print(f"  info  DGS1 last result: {last!r}")
        check("HF-01 Dump: DGS1 records STARTED OK - 3000W for 30 min, Stop SOC 20% (attempt 1; ends by 12:30)",
              last == "STARTED OK - 3000W for 30 min, Stop SOC 20% (attempt 1; ends by 12:30)", last)
        check("HF-01 Dump mid-lease: DGS1 ACTIVE, firmware 'ACTIVE - VERIFIED OK; target 3000W export - TRACKING', HA Dump "
              "Active on, dongle numbers hold the schedule's 3000 / 20 / 30, SMR1 OWED",
              mid[0] == "ACTIVE" and mid[1].startswith("ACTIVE - VERIFIED OK; target 3000W export - TRACKING")
              and mid[2] == "on" and mid[3].startswith("OWED") and mid[4] == (3000.0, 20.0, 30.0), asc(mid[:4]))
        txn = txn_for(cw, D.D_PRESS)
        slot = min(t for t in wd_slots(cw, "dump_wd") if t >= mid[5] - 1e-6)
        ends = fw_texts(cw, "dump_end")
        check("HF-01 Dump: end epoch = gate second + 30 min (UTC); dump_last_end_reason DURATION EXPIRED at the first Dump "
              "watchdog slot at or after it (< 15 s)", mid[5] == int(txn["t0"]) + 1800 and bool(ends)
              and abs(ends[-1][0] - slot) < 1e-6 and ends[-1][1] == "DURATION EXPIRED" and 0 <= slot - mid[5] < 15,
              f"{mid[5]} {ends[-1:]} {rel(slot)}")
        bank = cw.fw.bank_view(sorted(int(a) for a in ORIG))
        check("HF-01 Dump: RESTORED OK, owned registers at the ORIGINAL, durable marker CLEAR",
              cw.fw_status("dump") == "RESTORED OK - original inverter settings verified" and bank == ORIG
              and cw.fw.nvs_marker("dump") == "CLEAR")
        smr = cw.smr1_state("dump")
        print(f"  info  SMR1: {smr!r}")
        check("HF-01 Dump: SMR1 restores the owner's 1500 W / 30 % / 45 min; DGS1 COMPLETED, disarmed, write enable off, no "
              "notification", smr.startswith("RESTORED 2026-10-21 12:30 - restored: export power 1500 W, Stop SOC 30 %, "
                                             "duration 45 min") and ha_numbers(cw, "dump") == owner_strs("dump")
              and cw.schedule_status("dump") == "COMPLETED" and cw.ha_state(H.ARMED["dump"]) == "off"
              and cw.ha_state(D.D_ARM) == "off" and cw.notifications() == {}, smr)
        hf, fwv = cw.invariants(), fw_inv(cw)
        check("HF-01 Dump: no coupled and no firmware invariant violation; UTC-monotonic log",
              not hf and not fwv and cw.log.utc_regressions() == [], str(hf + fwv)[:300])
        ov, phys = cw.window_overruns()[0]["overrun_s"], physical_end(rec, "dump", ST + 1800)
        check(f"HF-01 Dump nominal: INV-HF-WINDOW holds - the lease ends {ov} s after the window end (the override itself "
              f"{phys} s; <= {CLAIM_S:.0f} s)", ov is not None and phys is not None and 0 < phys < ov <= CLAIM_S)
        return {"ov": ov, "phys": phys}
    finally:
        cw.close()


MEAS_FP = (46.2, 3)        # (recorded-busy-window bus phase, watchdog phase): the start meets a busy slot and so does the end
MEAS_DUMP = (22.9, 5)      # (recorded-busy-window bus phase, watchdog phase): the Dump's first end slot meets a busy window


def section_hf01_corpus_cases(nominal_dump) -> dict:
    print("[3b] HF-01 the corpus cases on the recorded-busy-window bus model (BUSY_10S / BUSY_60S, simulated; MODEL phases: "
          "FP bus 46.2 s / watchdog 3 s, Dump bus 22.9 s / watchdog 5 s), the corpus shrink equivalence, and a start gated "
          "more than 20 s late")
    fp10 = scheduled_run("fp", bus=H.BusModel(phase_s=MEAS_FP[0]), ph=MEAS_FP[1], minutes=10)
    fp60 = scheduled_run("fp", bus=H.BusModel(phase_s=MEAS_FP[0]), ph=MEAS_FP[1])
    d5 = scheduled_run("dump", bus=H.BusModel(phase_s=MEAS_DUMP[0]), ph=MEAS_DUMP[1], minutes=5, plant=False)
    d30 = scheduled_run("dump", bus=H.BusModel(phase_s=MEAS_DUMP[0]), ph=MEAS_DUMP[1])
    d5i = scheduled_run("dump", minutes=5, plant=False)
    pair = lambda r: (r.get("ov"), r.get("phys"))  # noqa: E731
    print(f"  info  (lease-end edge s, physical end s; simulated): FP recorded bus 10 min {pair(fp10)} / 60 min {pair(fp60)}; "
          f"Dump recorded bus 5 min without the plant {pair(d5)} / 30 min plant {pair(d30)}; Dump idle 5 min {pair(d5i)} / 30 "
          f"min plant {pair(nominal_dump)}")
    check("the shrunk corpus runs give the full-length overruns in both metrics and still end by DURATION / restore (10-min "
          "FP = 60-min FP on the recorded-busy-window bus; 5-min Dump without the plant = 30-min Dump with the plant, "
          "recorded and idle bus)",
          pair(fp10) == pair(fp60) and pair(d5) == pair(d30) and pair(d5i) == pair(nominal_dump)
          and all(point_ok(dom, r) for dom, r in (("fp", fp10), ("fp", fp60), ("dump", d5), ("dump", d30), ("dump", d5i))),
          f"{pair(fp10)} {pair(fp60)} {pair(d5)} {pair(d30)} {pair(d5i)}")
    check("HF-01 FP recorded-busy-window bus: the start meets a busy slot, FPS1 retries (transient) and attempt 3 keeps the "
          "full duration: 'STARTED OK - 8000W for 60 min (attempt 3; ends by 13:00)'",
          fp60.get("last") == "STARTED OK - 8000W for 60 min (attempt 3; ends by 13:00)" and fp60.get("presses") == 3,
          str(fp60.get("last")))
    late = scheduled_run("fp", bus=H.BusModel(windows=[(ST, ST + 19.0)]), minutes=10)
    print(f"  info  late start (bus busy for the first 19 s): {late.get('last')!r}; (edge, physical) {pair(late)} s")
    check("HF-01 FP late start: with the bus busy for the first 19 s the gate passes more than 20 s late (attempt 4), "
          "duration_now shortens the session to 9 min and it ends BEFORE the window end (both metrics < 0); the owner's "
          "values come back", late.get("last") == "STARTED OK - 8000W for 9 min (attempt 4; ends by 12:10)"
          and late.get("ov") is not None and late["ov"] < 0 and late.get("phys") is not None and late["phys"] < 0
          and point_ok("fp", late), str(late)[:200])
    return {"fp": fp60, "dump": d30, "late": late}


def finding_hf01(nominal_fp, busy, fp_sw, dump_sw, nominal_dump, cases) -> None:
    rows = {(dom, n, p): r for dom, sw in (("fp", fp_sw), ("dump", dump_sw)) for n, p, r in sw["rows"]}
    fpc, dc, late = cases["fp"], cases["dump"], cases["late"]
    lo = min(fp_sw["min"], dump_sw["min"], nominal_fp["ov"], nominal_dump["ov"], busy["ov"], fpc["ov"], dc["ov"])
    hi = max(fp_sw["max"], dump_sw["max"], busy["ov"], fpc["ov"], dc["ov"])
    plo = min(fp_sw["pmin"], dump_sw["pmin"], nominal_fp["phys"], nominal_dump["phys"], busy["phys"], fpc["phys"],
              dc["phys"])
    phi = max(fp_sw["pmax"], dump_sw["pmax"], busy["phys"], fpc["phys"], dc["phys"])
    ok = ((busy["ov"], busy["phys"]) == (34.4, 30.32) and inv_ids(busy["win"]) == ["INV-HF-WINDOW"]
          and "34.4 s" in busy["win"][0]["detail"] and (fpc["ov"], fpc["phys"]) == (52.4, 48.32)
          and (dc["ov"], dc["phys"]) == (35.93, 34.17) and min(busy["phys"], fpc["phys"], dc["phys"]) > CLAIM_S
          and lo > 0 and plo > 0 and late["ov"] < 0)
    check("finding-reproduces:F-HF01-1", ok, f"busy {busy['ov']}/{busy['phys']} fp {fpc['ov']}/{fpc['phys']} dump "
                                             f"{dc['ov']}/{dc['phys']} edge {lo}..{hi} physical {plo}..{phi} late {late['ov']}")
    d0 = rows[("dump", "recorded", 0)]
    check("finding-reproduces:F-HF01-1 [INV-HF-WINDOW 30 s fires on both corpus-strength recorded-busy-window runs; at "
          "recorded bus phase 0 the Dump lease-end edge (30.93 s, simulated) exceeds 30 s while the physical end (29.17 s) "
          "does not - the core metric is an upper bound]", inv_ids(fpc["window"]) == ["INV-HF-WINDOW"]
          and inv_ids(dc["window"]) == ["INV-HF-WINDOW"] and (d0["ov"], d0["phys"]) == (30.93, 29.17))
    if ok:
        FOUND.append("F-HF01-1")
        print(finding_line("F-HF01-1", f"on-time starts end after the window at every swept point (simulated: lease-end edge "
                                       f"{lo}..{hi} s, physical end {plo}..{phi} s, {'full' if EXTENDED else 'quick'} "
                                       f"sweep); above +{CLAIM_S:.0f} s physically with a busy end slot (Dump, recorded-busy-"
                                       f"window bus {dc['ov']} / {dc['phys']} s) and with start retries (FP, recorded-busy-"
                                       f"window bus {fpc['ov']} / {fpc['phys']} s; synthetic 10 s busy start {busy['ov']} / "
                                       f"{busy['phys']} s); a "
                                       f"start gated > 20 s late ends {-late['ov']} s before the window"))


# ---------------------------------------------------------------------------------------------------------------------------
# HF-04 back-to-back lease tails
# ---------------------------------------------------------------------------------------------------------------------------
def b2b(first, second, *, gap_s=0, ph=0.0, first_min=30, second_min=30, arm2_at=ST + 300, plant=True, fw_text=None, pk=None,
        until=240):
    """The first schedule 12:00 for first_min; the second armed at arm2_at for the first window end + gap_s. Returns the open
    world after the run (the caller closes it)."""
    cw = new_world(ph=ph, fw_text=fw_text, pk=pk)
    try:
        cw.fw.job_trace = []
        if plant and "dump" in (first, second):
            cw.dump_plant()
        arm(cw, first, minutes=first_min)
        arm(cw, second, start_local=loc(ST + first_min * 60 + gap_s), minutes=second_min, at=arm2_at)
        cw.run_until(ST + first_min * 60 + gap_s + until)
    except BaseException:
        cw.close()
        raise
    return cw


def b2b_point(first, second, gap_s, ph) -> dict:
    try:
        cw = b2b(first, second, gap_s=gap_s, ph=ph)
    except H.LabUnsupported as exc:
        UNSUPPORTED.append(("HF-04-UNS-EXT", f"{first}->{second} gap {gap_s} s phase {ph}: {str(exc)[:120]}"))
        return {"unsupported": True, "last": "UNSUPPORTED"}
    try:
        return {"last": cw.last_result(second), "notes": sorted(cw.notifications()), "one": cw.invariants(["INV-HF-ONE-LEASE"]),
                "press": check_no_press_into_lease(cw.log)}
    finally:
        cw.close()


def section_hf04_dump_fp() -> None:
    print("[6] HF-04 Dump to Grid 12:00-12:30 (dump_plant MODEL), then - armed at 12:05 after the Dump schedule started and "
          "disarmed - Free Power for 12:30:00, 30 min (synthetic)")
    cw = b2b("dump", "fp")
    try:
        arm_res = [e["data"]["s"] for e in evs(cw, "ha.state", e=H.LAST_RESULT["fp"]) if e["t_utc"] <= ST + 305]
        pr = start_presses(cw, "fp")
        w_end = ST + 1800
        d_end = lease_edges(cw, "dump")[1]
        last = cw.last_result("fp")
        ready = [x for x in notif_calls(cw, "ecco_free_power_schedule_readiness") if x[1] == "create"]
        fail = [x for x in notif_calls(cw, "ecco_free_power_schedule") if x[0] > ST + 301]
        fp_writes = [e for e in evs(cw, "fw.write") if e["data"]["dom"] == "fp"]
        print(f"  info  FP press at {[rel(e['t_utc']) for e in pr]} s; Dump lease end (snapshot off) "
              f"{[round(t - w_end, 3) for t in d_end]} s after 12:30:00; FPS1: {last!r}")
        print(f"  info  readiness alert {[(rel(t), s) for t, s in ready]}; failure alert {[(rel(t), s) for t, s in fail]}")
        one = cw.invariants(["INV-HF-ONE-LEASE"])
        check("HF-04 Dump->FP: one lease at a time holds (INV-HF-ONE-LEASE, firmware truth and HA view) - the firmware gate "
              "refuses the Free Power START while Dump owns the inverter; nothing is written for Free Power; every firmware "
              "invariant holds", not one and not fp_writes and not fw_inv(cw), str(one)[:200])
        msg = [e["data"]["data"].get("message", "") for e in evs(cw, "ha.call")
               if e["data"]["svc"] == "persistent_notification.create"
               and e["data"]["data"].get("notification_id") == "ecco_free_power_schedule_readiness"]
        check("HF-04 Dump->FP: the Free Power readiness check 5 min before names the blocker ('Dump to Grid owns the inverter "
              "settings') in an alert", len(ready) == 1 and ST + 1500 <= ready[0][0] <= ST + 1505
              and "Dump to Grid owns the inverter settings" in msg[0], str(ready))
        retry_until = ST + 1800 + 600
        ok = (any(x.startswith("ARMED - 2026-10-21 12:30:00") for x in arm_res) and len(pr) == 1
              and pr[0]["data"]["obl"]["dump"]["act"] is True
              and last == "FAILED TO START - REJECTED - Dump to Grid override/recovery owns inverter settings (attempt 1; "
                          "nothing written)"
              and cw.schedule_status("fp") == "FAILED" and fail and fail[-1][1] == "create"
              and "ecco_free_power_schedule" in cw.notifications()
              and len(d_end) == 1 and round(d_end[0] - w_end, 3) == 15.93 and d_end[0] < retry_until - 500
              and "retry transient refusals" in msg[0])
        check("finding-reproduces:F-HF04-1", ok, f"{asc(arm_res)} {len(pr)} {last!r} {d_end}")
        if ok:
            FOUND.append("F-HF04-1")
            print(finding_line("F-HF04-1", f"FP armed after the Dump schedule disarmed, start = Dump window end: pressed at "
                                           f"+{round(pr[0]['t_utc'] - w_end, 3)} s into the Dump tail, refused 'owns inverter "
                                           f"settings', FAILED + alert (pre-warned at T-5 min by a readiness alert that also "
                                           f"promises to retry transient refusals); the Dump obligation cleared "
                                           f"{round(d_end[0] - w_end, 3)} s after 12:30, {round(retry_until - d_end[0], 1)} s "
                                           "before FPS1's own retry deadline"))
    finally:
        cw.close()
    gaps = (0, 4, 8, 12, 16, 20, 30) if EXTENDED else (8, 20)
    phases = (0, 3, 6, 9, 12) if EXTENDED else (0,)
    grid = {(g, p): b2b_point("dump", "fp", g, p) for p in phases for g in gaps}
    for p in phases:
        print(f"  info  Dump->FP phase {p}: FP start = Dump window end + gap: "
              f"{[(g, grid[(g, p)]['last'][:16]) for g in gaps]}")
    if EXTENDED:
        print(f"  info  extended Dump->FP gap x phase grid: {len(grid)} runs")
    sup = {k: v for k, v in grid.items() if not v.get("unsupported")}
    check("HF-04 Dump->FP gap sweep: one lease at a time holds and no scheduled press goes into an active same-domain lease at "
          f"every supported point ({len(sup)} of {len(grid)})", all(not v["one"] and not v["press"] for v in sup.values()))
    check("finding-reproduces:F-HF04-1 [gap sweep: an FP start 8 s after the Dump window end still FAILS; 20 s after (the "
          "Dump restore done) it starts]", grid[(8, 0)]["last"].startswith("FAILED TO START - REJECTED - Dump to Grid")
          and grid[(20, 0)]["last"].startswith("STARTED OK"), str({k: v["last"][:30] for k, v in grid.items()}))


def section_hf04_fp_dump() -> None:
    print("[7] HF-04 Free Power 12:00-12:30, then - armed at 12:05 during the Free Power lease - Dump to Grid for 12:30:00")
    cw = b2b("fp", "dump", until=-1800 + 305)
    try:
        cw.run_until(ST + 306)
        res = cw.last_result("dump")
        charge = [cw.ha_state(e) for e in TOU_CHARGE]
        print(f"  info  DGS1 arm result: {res!r}; HA TOU slot charge sources during the FP lease: {charge}")
        anytime = []
        for start_local in ("2026-10-21 18:00:00", "2026-10-22 14:00:00"):   # no TOU slot of the synthetic plan charges there
            cw.arm_schedule("dump", start_local, 5, REQ_DUMP[0], stop_soc=REQ_DUMP[2])
            cw.run_for(3)
            anytime.append(cw.last_result("dump"))
        print(f"  info  Dump arms during the FP lease for 18:00 today and 14:00 tomorrow: {[x[:62] for x in anytime]}")
        cw.run_until(ST + 1800 + 180)
        after = [cw.ha_state(e) for e in TOU_CHARGE]
        cw.arm_schedule("dump", "2026-10-21 12:40:00", 10, REQ_DUMP[0], stop_soc=REQ_DUMP[2])
        cw.run_for(5)
        later = cw.last_result("dump")
        print(f"  info  after the FP restore: TOU charge {after}; the same Dump arm at 12:33 for 12:40: {asc(later)!r}")
        check("HF-04 FP->Dump: no Dump START reaches the firmware while the Free Power lease or its tail runs; one lease at a "
              "time holds", not start_presses(cw, "dump") and not cw.invariants(["INV-HF-ONE-LEASE"]))
        ok = (res == "REJECTED - window overlaps a TOU slot with a charge source set (e.g. the overnight grid-charge slot); "
                     "Dump V1 will not start there"
              and charge == ["Grid"] * 6 and after == ["Grid"] + ["None"] * 5
              and later.startswith("ARMED - 2026-10-21 12:40:00")
              and all(x.startswith("REJECTED - window overlaps a TOU slot with a charge source set") for x in anytime))
        check("finding-reproduces:F-HF04-3", ok, f"{res!r} {charge} {after} {asc(later)!r} {anytime}")
        if ok:
            FOUND.append("F-HF04-3")
            print(finding_line("F-HF04-3", "a Dump armed during a Free Power lease - for any window (12:30 today, 18:00 "
                                           "today, 14:00 tomorrow) - is REJECTED as overlapping 'a TOU slot with a charge "
                                           "source set': HA shows Grid on all six slots (the FP override's 274-279); the "
                                           "site plan has only slot 1; an arm after the FP restore and readback is ARMED"))
    finally:
        cw.close()
    out = {}
    for at in (8, 9):   # FPS1 has disarmed by +8 s; the closing configuration readback (Block B) lands before +9 s
        cw = new_world()
        try:
            arm(cw, "fp", minutes=5)
            cw.run_until(ST + at)
            tou = [cw.ha_state(e) for e in TOU_CHARGE]
            fp_armed = cw.ha_state(H.ARMED["fp"])
            cw.arm_schedule("dump", "2026-10-21 12:05:00", 5, REQ_DUMP[0], stop_soc=REQ_DUMP[2])
            cw.run_for(3)
            arm_res = cw.last_result("dump")
            cw.run_until(ST + 700)
            pr = start_presses(cw, "dump")
            out[at] = {"tou": tou, "fp_armed": fp_armed, "arm": arm_res, "last": cw.last_result("dump"),
                       "press_obl": [e["data"]["obl"]["fp"]["act"] for e in pr], "press_t": [rel(e["t_utc"]) for e in pr],
                       "notes": sorted(cw.notifications()), "one": cw.invariants(["INV-HF-ONE-LEASE"]),
                       "dump_writes": [e for e in evs(cw, "fw.write") if e["data"]["dom"] == "dump"],
                       "status": cw.schedule_status("dump")}
        finally:
            cw.close()
        print(f"  info  Dump armed at 12:00:{at:02d} for 12:05:00 (FP 12:00-12:05): FP armed {out[at]['fp_armed']}, TOU "
              f"{[x[0] for x in out[at]['tou']]}, arm {asc(out[at]['arm'])[:40]!r}, final {out[at]['last'][:90]!r}, "
              f"press {out[at]['press_t']}")
    check("HF-04 FP->Dump narrow window: one lease at a time holds and nothing is written for the Dump in both arm-time "
          "variants", all(not v["one"] and not v["dump_writes"] for v in out.values()), str({k: v["one"] for k, v in
                                                                                             out.items()}))
    m = out[8]
    ok = (m["fp_armed"] == "off" and m["tou"] == ["Grid"] + ["None"] * 5 and m["arm"].startswith("ARMED - 2026-10-21 12:05:00")
          and m["last"] == "FAILED TO START - REJECTED - Free Power override/recovery owns inverter settings (attempt 1; "
                           "nothing written)" and m["press_obl"] == [True] and m["status"] == "FAILED"
          and "ecco_dump_to_grid_schedule" in m["notes"]
          and out[9]["arm"].startswith("REJECTED - window overlaps a TOU slot with a charge source set")
          and out[9]["tou"] == ["Grid"] * 6)
    check("finding-reproduces:F-HF04-1 [mirror FP->Dump: a Dump armed at 12:00:08, after FPS1 disarmed and before the closing "
          "readback shows the Grid slots, is ARMED; at 12:05 DGS1 presses into the Free Power tail, the gate refuses 'Free "
          "Power override/recovery owns inverter settings', FAILED + alert; armed at 12:00:09 it is refused by the TOU walk]",
          ok, str({k: (v["arm"][:30], v["last"][:60]) for k, v in out.items()}))
    cw = new_world()
    try:
        arm(cw, "fp", minutes=30)
        arm(cw, "dump", start_local="2026-10-21 12:30:00", minutes=10, at=U0 + 90)
        cw.run_until(U0 + 100)
        res = cw.last_result("dump")
        check("HF-04 FP->Dump control: with the Free Power schedule still ARMED, DGS1's +-120 s overlap check refuses the Dump "
              "for 12:30:00 at arm time ('REJECTED - overlaps the armed Scheduled Free Power window')",
              res.startswith("REJECTED - overlaps the armed Scheduled Free Power window")
              and cw.ha_state(H.ARMED["dump"]) == "off", res)
    finally:
        cw.close()


def section_hf04_same(dom) -> dict:
    label = {"fp": "Free Power", "dump": "Dump to Grid"}[dom]
    print(f"[8{'a' if dom == 'fp' else 'b'}] HF-04 same domain: {label} 12:00-12:30, re-armed at 12:05 (after its run "
          "disarmed) for 12:30:00, 30 min")
    cw = b2b(dom, dom)
    try:
        last = cw.last_result(dom)
        w_end = ST + 1800
        starts, ends = lease_edges(cw, dom)
        late_starts = [t for t in starts if t > ST + 300]
        presses2 = start_presses(cw, dom, after=ST + 300)
        nid = "ecco_free_power_schedule" if dom == "fp" else "ecco_dump_to_grid_schedule"
        ready = [x for x in notif_calls(cw, nid + "_readiness") if x[0] > ST + 301]   # after the re-arm's own dismiss
        fail = [x for x in notif_calls(cw, nid) if x[1] == "create"]
        print(f"  info  {label} result {last!r}; first lease end {[round(t - w_end, 3) for t in ends]} s after 12:30:00; "
              f"readiness alert {[(rel(t), s) for t, s in ready]}; status {cw.schedule_status(dom)!r}")
        # Core issue (worked around here): _lab_ha.window_overruns (_lab_ha.py 'def window_overruns') attributes every lease
        # edge to the most recent owner.arm of the domain, so re-arming while the first lease runs hides the first run's
        # lease end and check_hf_window reports 'override still held'. The first run's overrun is computed from dongle.edge.
        core_win = cw.invariants(["INV-HF-WINDOW"])
        print(f"  info  core INV-HF-WINDOW on this log (attribution artefact, not used): {[v['detail'][:70] for v in core_win]}")
        others = cw.invariants([n for n in H.HF_INVARIANTS if n != "INV-HF-WINDOW"])
        own_ov = round(ends[0] - w_end, 3) if len(ends) == 1 else None
        check(f"HF-04 {dom}->{dom}: no scheduled press reaches the firmware while the {label} lease is active "
              "(INV-HF-NO-PRESS-INTO-LEASE, the package's pre-check), every other INV-HF-* except the attribution-affected "
              f"INV-HF-WINDOW holds, the first run's own override ends {own_ov} s after its window (<= {CLAIM_S:.0f} s), "
              "firmware invariants hold", not check_no_press_into_lease(cw.log) and not others
              and own_ov is not None and 0 < own_ov <= CLAIM_S and not fw_inv(cw), str(others)[:200])
        blocked = "BLOCKED - Free Power already active" if dom == "fp" else "BLOCKED - Dump to Grid already active"
        exp_tail = 19.4 if dom == "fp" else 15.93
        epoch = int(txn_for(cw, S.E_PRESS if dom == "fp" else D.D_PRESS)["t0"]) + 1800   # the first lease's end epoch
        print(f"  info  the first lease's end epoch (its gate second + 30 min) is {loc(epoch)}, after the second run's "
              f"12:30:00 trigger by {epoch - w_end} s: the BLOCKED result at the exact window end follows from the source")
        ok = (last == blocked and not fail and nid not in cw.notifications() and not presses2 and not late_starts
              and len(ready) == 2 and ready[0][1] == "create" and ST + 1500 <= ready[0][0] <= ST + 1505
              and ready[1] == (w_end, "dismiss") and own_ov == exp_tail and cw.schedule_status(dom) == "IDLE"
              and cw.ha_state(H.ARMED[dom]) == "off" and epoch > w_end)
        check(f"finding-reproduces:F-HF04-2 [{dom}]", ok, f"{last!r} {fail} {len(presses2)} {late_starts} {ready} {own_ov}")
        out = {"ok": ok, "tail": own_ov, "blocked": blocked}
    finally:
        cw.close()
    if dom == "fp":
        cw = b2b("fp", "fp", gap_s=-600, until=840)   # the second start (12:20) falls INSIDE the first lease
        try:
            starts, _ends = lease_edges(cw, "fp")
            r2 = {"last": cw.last_result("fp"), "fail": [x for x in notif_calls(cw, "ecco_free_power_schedule")
                                                         if x[1] == "create"],
                  "presses": start_presses(cw, "fp", after=ST + 300), "late": [t for t in starts if t > ST + 300],
                  "status": cw.schedule_status("fp"), "armed": cw.ha_state(H.ARMED["fp"]),
                  "press_into": check_no_press_into_lease(cw.log)}
        finally:
            cw.close()
        print(f"  info  FP re-armed at 12:05 for 12:20 (inside the first lease, which ends after 12:30): {r2['last']!r}, "
              f"status {r2['status']!r} at 12:34")
        ok_in = (r2["last"] == "BLOCKED - Free Power already active" and not r2["fail"] and not r2["presses"]
                 and not r2["late"] and r2["status"] == "IDLE" and r2["armed"] == "off" and not r2["press_into"])
        check("finding-reproduces:F-HF04-2 [fp, a start inside the previous lease: BLOCKED, no failure alert, IDLE, no lease "
              "for the rest of the 12:20-12:50 window after the first lease ends]", ok_in, str(r2)[:300])
        out["ok"] = out["ok"] and ok_in
    if dom == "fp":
        gaps = (0, 5, 10, 15, 20, 25) if EXTENDED else (25,)
        phases = (0, 5, 10) if EXTENDED else (0,)
        grid = {(g, p): b2b_point("fp", "fp", g, p) for p in phases for g in gaps}
        for p in phases:
            print(f"  info  FP->FP phase {p}: start = previous window end + gap: {[(g, grid[(g, p)]['last'][:16]) for g in gaps]}")
        sup = [v for v in grid.values() if not v.get("unsupported")]
        check("HF-04 FP->FP gap sweep: no scheduled press goes into an active lease at any supported point, and a start 25 s "
              "after the previous window end (its restore done) starts", all(not v["press"] for v in sup)
              and grid[(25, 0)]["last"].startswith("STARTED OK"), str({k: v["last"][:20] for k, v in grid.items()}))
    return out


def finding_hf04_same(fp, dump) -> None:
    if fp["ok"] and dump["ok"]:
        FOUND.append("F-HF04-2")
        print(finding_line("F-HF04-2", f"re-armed for its own window end: '{fp['blocked']}' / '{dump['blocked']}' at "
                                       "12:30:00, no failure alert, the readiness alert dismissed, status IDLE, no lease for "
                                       f"the 30-min window; the previous lease ended {fp['tail']} s / {dump['tail']} s later "
                                       "(its end epoch is already after the trigger); a start inside the previous lease is "
                                       "lost the same way"))


# ---------------------------------------------------------------------------------------------------------------------------
# HF-06 failed START with a retained snapshot
# ---------------------------------------------------------------------------------------------------------------------------
def model_premise(dom: str, outcome: str) -> dict:
    """The HA-side premise: the REAL DGS1 / FPS1 / SMR1 packages against the two hand-written HA dongle models (D.DumpDongle,
    S.Dongle) exactly as the SMR1 suite builds them (pattern from home-assistant/tests/test_ecco_schedule_manual_restore.py:
    122-174), with the model's failed-START outcome, for 30 min. No CoupledWorld is open (S.LOCAL is the sim's own UTC+1, which
    is the BST offset of the synthetic date)."""
    if H._OPEN or S.LOCAL is not FIXED_LOCAL:
        raise L.LabHarnessError("model_premise needs the sim's own S.LOCAL and no open CoupledWorld")
    w = S.World(S.parse_local("2026-10-21 11:50:00"))
    D.add_ha_filters(w)
    ha = S.HA(w, [yaml.safe_load(H.package_text(n)) for n in ("dgs1", "fps1", "smr1")])
    f = S.Dongle(w, outcome=outcome if dom == "fp" else "ok")
    fph = dict(w.service_handlers)
    d = D.DumpDongle(w, outcome=outcome if dom == "dump" else "ok")
    dh = dict(w.service_handlers)
    route = {D.D_ARM, D.D_PRESS, D.D_DUR, D.D_PWR, D.D_SOC}
    for svc in ("switch.turn_on", "switch.turn_off", "button.press", "number.set_value"):
        w.service_handlers[svc] = (lambda s: lambda e, data: (dh if e in route else fph)[s](e, data))(svc)
    d.power, d.stop_soc, d.duration = OWNER["dump"]
    f.power, f.duration = OWNER["fp"]
    attrs = {D.D_PWR: (500, 8000, 100), D.D_SOC: (10, 90, 1), D.D_DUR: (1, 240, 1), S.E_PWR: (500, 8000, 100),
             S.E_DUR: (1, 240, 1)}                 # the firmware's min / max / step (SMR1 suite ATTRS)
    for e, v in zip(H.NUMBERS["dump"] + H.NUMBERS["fp"], OWNER["dump"] + OWNER["fp"]):
        lo, hi, step = attrs[e]
        w.set(e, f"{float(v)}", {"min": lo, "max": hi, "step": step})
    w.set(f"sensor.{S.P}dump_to_grid_recovery_state", "NONE")
    w.set(f"sensor.{S.P}free_power_recovery_state", "NONE")
    w.set(S.E_LIMIT, "8000")
    for dm in H.DOMS:
        w.set(H.ARMED[dm], "off")
        w.set(H.LAST_RESULT[dm], "")
    w.set(H.START_HELPER[dom], START_LOCAL)
    vals = ((H.DURATION_HELPER, REQ_FP[1]), (H.POWER_HELPER, REQ_FP[0])) if dom == "fp" else (
        (H.DURATION_HELPER, REQ_DUMP[1]), (H.POWER_HELPER, REQ_DUMP[0]), (H.STOP_SOC_HELPER, REQ_DUMP[2]))
    for helper, v in vals:
        w.set(helper[dom], f"{float(v)}")
    ha.start()
    w.run_until(S.parse_local("2026-10-21 11:51:00"))
    w.set(H.ARMED[dom], "on")
    w.run_until(S.parse_local("2026-10-21 12:30:00"))
    return {"last": w.state(H.LAST_RESULT[dom]), "smr1": w.state(H.SMR1_STATE[dom]),
            "nums": tuple(w.state(e) for e in H.NUMBERS[dom]), "blocker": w.state("sensor.ecco_schedule_restore_blocker")}


def hf06_world(dom, *, fw_text=None, pk=None, end_press=False) -> H.CoupledWorld:
    cw = new_world(fw_text=fw_text, pk=pk)
    try:
        cw.fw.job_trace = []
        stage_owner(cw, dom)
        arm(cw, dom)
        cw.fw_action("modbus_policy", at_utc=U0 + 90, table={"write:256": ["ack_not_applied"]})
        if end_press:
            cw.owner_press(END_DUMP_BUTTON, at_utc=ST + 120)
        cw.run_until(ST + 300)
    except BaseException:
        cw.close()
        raise
    return cw


def hf06_compound() -> dict:
    """The reachable long-pending case (the F-HF06-1 counter-probe): the START's write to 256 lands, its verify read errors,
    and every later write to 256 errors, so the firmware's own restore cannot write back (synthetic Modbus policy)."""
    cw = new_world()
    try:
        stage_owner(cw, "dump")
        arm(cw, "dump")
        cw.fw_action("modbus_policy", at_utc=U0 + 90, table={"write:256": ["ok"] + ["error"] * 200,
                                                              "read:256x6": ["ok", "error"]})
        cw.run_until(ST + 1800)
        txs = fw_texts(cw, "dump", after=ST)
        return {"start_failed": any(x.startswith("START FAILED - verify mismatch or write error") for _t, x in txs),
                "restoring": [round(t - ST) for t, x in txs if x.startswith("RESTORING")],
                "write_failed": any(x.startswith("RESTORE WRITE FAILED") for _t, x in txs),
                "snap": cw.ha_state(f"binary_sensor.{S.P}dump_to_grid_snapshot_valid"), "marker": cw.fw.nvs_marker("dump"),
                "smr1": cw.smr1_state("dump"), "blocker": cw.ha_state("sensor.ecco_schedule_restore_blocker"),
                "nums": ha_numbers(cw, "dump"), "smr1_writes": evs(cw, "dongle.cmd", by="smr1"),
                "inv": inv_ids(cw.invariants()), "fwinv": inv_ids(fw_inv(cw))}
    finally:
        cw.close()


def section_hf06_dump() -> dict:
    print("[9] HF-06 scheduled Dump to Grid whose activation write to 256-261 is acknowledged but not applied (synthetic "
          "Modbus policy 'write:256' -> ack_not_applied): verify mismatch, snapshot retained")
    check("the END button id the corpus uses is the dongle's mapped End & Restore Now button",
          H.dongle_entity_map().get(END_DUMP_BUTTON, (None,))[0] == H.END_BUTTON["dump"])
    cw = hf06_world("dump", end_press=True)
    try:
        txs = fw_texts(cw, "dump", after=ST)
        ends = fw_texts(cw, "dump_end", after=ST)
        pr = start_presses(cw, "dump")
        t_gate = pr[0]["t_utc"] if pr else None    # dongle.cmd is logged at the gate instant (press + press_s)
        snap_on = [e["t_utc"] for e in evs(cw, "ha.state", e=f"binary_sensor.{S.P}dump_to_grid_snapshot_valid")
                   if e["data"]["s"] == "on"]
        snap_off = [e["t_utc"] for e in evs(cw, "ha.state", e=f"binary_sensor.{S.P}dump_to_grid_snapshot_valid")
                    if e["data"]["s"] == "off" and e["t_utc"] > ST]
        smr_states = [(e["t_utc"], e["data"]["s"]) for e in evs(cw, "ha.state", e=H.SMR1_STATE["dump"])]
        restored_at = next((t for t, s in smr_states if s.startswith("RESTORED")), None)
        smr_writes = [e for e in evs(cw, "dongle.cmd", by="smr1")]
        presses_end = [e["t_utc"] for e in evs(cw, "owner.press")]
        alert = cw.notifications().get("ecco_dump_to_grid_schedule", {})
        alert_t = [t for t, s in notif_calls(cw, "ecco_dump_to_grid_schedule") if s == "create"]
        slots = [t for t in wd_slots(cw, "dump_wd") if t_gate is not None and t > t_gate]
        print(f"  info  firmware Dump texts: {[(rel(t), x[:60]) for t, x in txs]}")
        print(f"  info  end reasons {[(rel(t), x) for t, x in ends]}; HA snapshot on {[rel(t) for t in snap_on]} off "
              f"{[rel(t) for t in snap_off]}; SMR1 RESTORED at {restored_at and rel(restored_at)}; alert at "
              f"{[rel(t) for t in alert_t]}; owner End press at {[rel(t) for t in presses_end]}")
        last = cw.last_result("dump")
        check("HF-06 Dump: the START fails after its durable snapshot ('START FAILED - verify mismatch or write error; "
              "snapshot retained - press End & Restore Now'), HA sees the snapshot on; DGS1 waits for the begun transaction, "
              "records FAILED TO START (start transaction began on attempt 1; not retried), alerts, and never presses again",
              any(x == "START FAILED - verify mismatch or write error; snapshot retained - press End & Restore Now"
                  for _t, x in txs) and snap_on and len(pr) == 1
              and last == "FAILED TO START - START FAILED - verify mismatch or write error; snapshot retained - press End & "
                          "Restore Now (start transaction began on attempt 1; not retried)" and alert, last)
        first_restore = next((t for t, x in txs if x.startswith("RESTORING")), None)
        check("HF-06 Dump: the firmware restores by itself at its next Dump watchdog tick (< 15 s after the failed gate), end "
              "reason 'INTERRUPTED TRANSACTION - restoring original settings', RESTORED OK; owned registers ORIGINAL and the "
              "marker CLEAR before the owner's End press; INV-RESTORE-BOUND (bound 20 s) holds",
              bool(slots) and first_restore is not None and abs(first_restore - slots[0]) < 1e-6
              and 0 < first_restore - t_gate < 15 and ("INTERRUPTED TRANSACTION - restoring original settings"
                                                        in [x for _t, x in ends])
              and any(x == "RESTORED OK - original inverter settings verified" for _t, x in txs)
              and cw.fw.bank_view(sorted(int(a) for a in ORIG)) == ORIG and cw.fw.nvs_marker("dump") == "CLEAR"
              and not cw.invariants(["INV-RESTORE-BOUND"], bound_s=20), f"{first_restore} {slots[:1]} {ends}")
        check("HF-06 Dump: SMR1 restores the owner's 1500 W / 30 % / 45 min with NO End & Restore press (the only owner press "
              "comes 100 s later), writes only after the snapshot cleared (INV-HF-SMR1-QUIET) and says RESTORED only with "
              "the owner's values on the numbers (INV-HF-NO-FALSE-SUCCESS); all INV-HF-* and firmware invariants hold",
              restored_at is not None and presses_end and restored_at < presses_end[0] and smr_writes
              and all(e["t_utc"] > snap_off[0] for e in smr_writes)
              and cw.smr1_state("dump").startswith("RESTORED 2026-10-21 12:00 - restored: export power 1500 W, Stop SOC "
                                                    "30 %, duration 45 min")
              and ha_numbers(cw, "dump") == owner_strs("dump") and not cw.invariants()
              and not fw_inv(cw), str(smr_states)[:300])
        real = {"restored_after_s": round(restored_at - t_gate, 3) if restored_at else None, "alert_t": alert_t,
                "first_restore": first_restore, "msg": alert.get("message", ""), "end_text": cw.fw_status("dump")}
    finally:
        cw.close()
    model = model_premise("dump", "verify_failed")
    print(f"  info  HA model premise (D.DumpDongle 'verify_failed', 30 min later): SMR1 {model['smr1'][:40]!r}; blocker "
          f"{model['blocker']!r}; numbers {model['nums']}")
    comp = hf06_compound()
    print(f"  info  compound fault (the START write lands, its verify read errors, every later write to 256 errors): "
          f"restore attempts at {comp['restoring']} s after 12:00, 30 min later: SMR1 {comp['smr1'][:20]!r}, blocker "
          f"{comp['blocker']!r}, marker {comp['marker']}, numbers {comp['nums']}")
    check("HF-06 Dump compound fault: a long-pending snapshot IS reachable when the automatic restore also fails - the "
          "firmware retries by itself with a growing backoff ('RESTORE WRITE FAILED - ...'), the marker stays "
          "RESTORE_REQUIRED and the snapshot on for 30 min, SMR1 stays OWED with the blocker 'Dump to Grid snapshot pending "
          "restore' and writes nothing (the HA model's end state, from a different cause); all INV-HF-* and firmware "
          "invariants hold", comp["start_failed"] and len(comp["restoring"]) >= 5
          and all(b - a >= 15 for a, b in zip(comp["restoring"], comp["restoring"][1:]))
          and comp["restoring"][-1] - comp["restoring"][-2] > 15 and comp["write_failed"] and comp["snap"] == "on"
          and comp["marker"] == "RESTORE_REQUIRED" and comp["smr1"].startswith("OWED")
          and comp["blocker"] == "Dump to Grid snapshot pending restore" and comp["nums"] == ("3000.0", "20.0", "30.0")
          and not comp["smr1_writes"] and not comp["inv"] and not comp["fwinv"], str(comp)[:300])
    ok1 = (model["smr1"].startswith("OWED") and model["blocker"] == "Dump to Grid snapshot pending restore"
           and model["nums"] == ("3000.0", "20.0", "30.0") and real["restored_after_s"] is not None
           and real["restored_after_s"] < 30)
    check("finding-reproduces:F-HF06-1 [Dump]", ok1, f"{model} {real['restored_after_s']}")
    ok2 = (bool(real["alert_t"]) and "press End & Restore Now" in real["msg"] and real["first_restore"] is not None
           and 0 < real["first_restore"] - real["alert_t"][0] < 15
           and real["end_text"] == "END IGNORED - no saved Dump to Grid snapshot")
    check("finding-reproduces:F-HF06-2", ok2, f"{real}")
    if ok2:
        FOUND.append("F-HF06-2")
        print(finding_line("F-HF06-2", f"DGS1 alert says 'press End & Restore Now'; the firmware restored at its next "
                                       f"watchdog tick, {round(real['first_restore'] - real['alert_t'][0], 3)} s after the "
                                       f"alert (0-15 s by phase); the advice stays in the result and the alert; the "
                                       f"owner's End press then reads {real['end_text']!r}"))
    return {"ok1": ok1, "nums": model["nums"], "after": real["restored_after_s"]}


def section_hf06_fp(dump) -> None:
    print("[10] HF-06 scheduled Free Power whose activation write to 256-261 is acknowledged but not applied (synthetic "
          "Modbus policy): activation verify mismatch")
    cw = hf06_world("fp")
    try:
        txs = fw_texts(cw, "fp", after=ST)
        pr = start_presses(cw, "fp")
        txn = txn_for(cw, S.E_PRESS)
        smr_writes = [e for e in evs(cw, "dongle.cmd", by="smr1")]
        snap_off = [e["t_utc"] for e in evs(cw, "ha.state", e=S.E_SNAP) if e["data"]["s"] == "off" and e["t_utc"] > ST]
        last = cw.last_result("fp")
        alert = cw.notifications().get("ecco_free_power_schedule", {})
        print(f"  info  firmware FP texts: {[(rel(t), x[:58]) for t, x in txs]}; FPS1: {last!r}")
        verify_t = [t for t, x in txs if x == "ACTIVATION VERIFY FAILED - restoring saved snapshot"]
        restored_t = [t for t, x in txs if x == "RESTORED OK - original inverter settings verified"]
        check("HF-06 FP: the firmware restores inline - 'ACTIVATION VERIFY FAILED - restoring saved snapshot' then 'RESTORED "
              "OK' inside the same START transaction (both at the gate instant); owned registers ORIGINAL, marker CLEAR",
              verify_t and restored_t and abs(verify_t[0] - txn["t0"]) < 1e-3 and abs(restored_t[0] - txn["t0"]) < 1e-3
              and cw.fw.bank_view(sorted(int(a) for a in ORIG)) == ORIG and cw.fw.nvs_marker("fp") == "CLEAR",
              str(txs)[:200])
        check("HF-06 FP: FPS1 never presses again (one press) and alerts; SMR1 restores the owner's 5000 W / 45 min with no "
              "End press, only after the snapshot cleared; all INV-HF-* and firmware invariants hold",
              len(pr) == 1 and alert and smr_writes and snap_off and all(e["t_utc"] > snap_off[0] for e in smr_writes)
              and not evs(cw, "owner.press")
              and cw.smr1_state("fp").startswith("RESTORED 2026-10-21 12:00 - restored: charge power 5000 W, duration 45 "
                                                  "min") and ha_numbers(cw, "fp") == owner_strs("fp")
              and not cw.invariants() and not fw_inv(cw), cw.smr1_state("fp"))
        real_fp = {"last": last, "msg": alert.get("message", ""), "smr1": cw.smr1_state("fp")}
        hist = [(rel(e["t_utc"]), e["data"]["s"][:40]) for e in evs(cw, "ha.state", e=FP_STATUS_HA) if e["t_utc"] > ST]
        print(f"  info  HA's Free Power status history (lab projection; on ESPHome the API batching probably merges the "
              f"quick updates, INFERRED): {hist[:6]}")
    finally:
        cw.close()
    model = model_premise("fp", "write_failed")
    print(f"  info  HA model premise (S.Dongle 'write_failed', 30 min later): FPS1 {model['last'][:70]!r}; SMR1 "
          f"{model['smr1'][:30]!r}; blocker {model['blocker']!r}; numbers {model['nums']}")
    ok3 = (real_fp["last"] == "FAILED TO START - RESTORED OK - original inverter settings verified (start transaction began "
                              "on attempt 1; not retried)"
           and "RESTORED OK" in real_fp["msg"] and "VERIFY FAILED" not in real_fp["msg"]
           and model["last"].startswith("FAILED TO START - ACTIVATION WRITE FAILED - restoring saved snapshot"))
    check("finding-reproduces:F-HF06-3", ok3, f"{real_fp['last']!r} / model {model['last'][:80]!r}")
    if ok3:
        FOUND.append("F-HF06-3")
        print(finding_line("F-HF06-3", "FPS1 records and alerts 'FAILED TO START - RESTORED OK - original inverter settings "
                                       "verified (start transaction began ...)' for an activation verify failure: the "
                                       "reason is lost from the result and the alert (the HA model recorded 'ACTIVATION "
                                       "WRITE FAILED')"))
    ok1 = (model["smr1"].startswith("OWED") and model["blocker"] == "Free Power snapshot pending restore"
           and model["nums"] == ("8000.0", "60.0") and real_fp["smr1"].startswith("RESTORED"))
    check("finding-reproduces:F-HF06-1 [FP]", ok1, str(model))
    if ok1 and dump["ok1"]:
        FOUND.append("F-HF06-1")
        print(finding_line("F-HF06-1", f"the HA models keep a single failed START's snapshot pending (SMR1 OWED 30 min "
                                       f"later, Dump numbers {dump['nums']}, FP {model['nums']}) as if End & Restore were "
                                       f"needed; the real firmware restored by itself and SMR1 RESTORED the owner's values "
                                       f"{dump['after']} s (Dump) after the failed gate with no owner action; that end "
                                       "state is reachable only when the automatic restore also fails"))


# ---------------------------------------------------------------------------------------------------------------------------
# negative controls (in-memory mutants of real guards / source-backed conditions)
# ---------------------------------------------------------------------------------------------------------------------------
NC_RESULTS: list = []


def negative_control(nc_id, family, target, what, run) -> None:
    """run() builds and runs the mutant world and returns its violations. A mutant that raises anything (parse error, harness
    error, unsupported construct) is MUTANT-INVALID: a negative-control FAILURE, never a kill."""
    detail = ""
    try:
        viol = run()
    except Exception as exc:  # noqa: BLE001 - converted into a FAIL (MUTANT-INVALID), never into a pass
        outcome, detail = "invalid", f"{type(exc).__name__}: {str(exc)[:160]}"
    else:
        hit = [v for v in viol if v["inv"] == target]
        outcome = "killed" if hit else "survived"
        detail = hit[0]["detail"][:110] if hit else str(inv_ids(viol))
    NC_RESULTS.append((nc_id, family, target, outcome))
    print(f"  info  {nc_id}: {outcome} ({detail})")
    check(f"negative control {nc_id} ({family}): {what} -> {target} fires on the real run, no harness exception "
          f"(outcome {outcome})", outcome == "killed", detail)


def section_negative_controls() -> None:
    print("[11] negative controls: one in-memory mutation of a real guard per scenario family makes its intended invariant "
          "check fire")
    fw_text = T.read_source_text(FW)
    fps, smr = H.package_text("fps1"), H.package_text("smr1")

    def nc1():
        m = mutate(fw_text, ANCHORS["fw.fp_end"][1], "return (uint32_t) now.timestamp >= id(free_power_end_epoch) + 60U;")
        return scheduled_run("fp", fw_text=m, owner=False).get("window", [{"inv": "UNSUPPORTED", "detail": ""}])
    negative_control("NC-HF01-1", "HF-01", "INV-HF-WINDOW", "firmware FP watchdog end condition shifted +60 s "
                     "(fw.fp_end)", nc1)

    def nc2():
        m = mutate(fw_text, ANCHORS["fw.dump_end"][1], "return (uint32_t) now.timestamp >= id(dump_end_epoch) + 60U;")
        return scheduled_run("dump", minutes=5, plant=False, owner=False, fw_text=m).get("window", [])
    negative_control("NC-HF01-2", "HF-01", "INV-HF-WINDOW", "firmware Dump watchdog end condition shifted +60 s "
                     "(fw.dump_end)", nc2)

    def nc3():
        i = smr.index(ANCHORS["smr1.fp_saved"][1])
        snip = '                      entity_id: "{{ saved }}"\n                    data:\n                      value: "{{ old | float(0) }}"'
        m = smr[:i] + mutate(smr[i:], snip, snip.replace("old | float(0)", "new | float(0)"))
        return scheduled_run("fp", minutes=10, pk={"smr1": m}).get("nfs", [])
    negative_control("NC-HF01-3", "HF-01", "INV-HF-NO-FALSE-SUCCESS", "SMR1's Free Power track saves the schedule's value "
                     "instead of the owner's (smr1.fp_saved region)", nc3)

    def nc4():
        old = ("                !id(dump_active_persisted) &&\n                !id(dump_snapshot_valid) &&\n"
               "                // Fail-closed lockout: a durable recovery marker exists\n")
        m = mutate(fw_text, old, "                // Fail-closed lockout: a durable recovery marker exists\n")
        cw = b2b("dump", "fp", first_min=5, second_min=10, arm2_at=ST + 120, plant=False, fw_text=m)
        try:
            return cw.invariants(["INV-HF-ONE-LEASE"])
        finally:
            cw.close()
    negative_control("NC-HF04-1", "HF-04", "INV-HF-ONE-LEASE", "the Free Power START gate without its Dump ownership "
                     "conjuncts (fw.fp_gate_dump)", nc4)

    def nc5():
        old = ('                entity_id: binary_sensor.ecco_clock_dongle_free_power_active\n                state: "on"\n'
               '            sequence:\n              - action: input_text.set_value\n                target:\n'
               '                  entity_id: input_text.ecco_free_power_schedule_last_result\n                data:\n'
               '                  value: "BLOCKED - Free Power already active"')
        m = mutate(fps, old, old.replace('state: "on"', 'state: "lab-mutant-never"'))
        cw = b2b("fp", "fp", first_min=5, second_min=10, arm2_at=ST + 120, pk={"fps1": m})
        try:
            return check_no_press_into_lease(cw.log)
        finally:
            cw.close()
    negative_control("NC-HF04-2", "HF-04", "INV-HF-NO-PRESS-INTO-LEASE", "FPS1's 'already active' pre-check never matches "
                     "(fps1.blocked_active)", nc5)

    def nc6():
        m = mutate(smr, "               " + ANCHORS["smr1.blocker_dump_snap"][1] + "\n", "")
        cw = hf06_world("dump", pk={"smr1": m})
        try:
            return cw.invariants(["INV-HF-SMR1-QUIET"])
        finally:
            cw.close()
    negative_control("NC-HF06-1", "HF-06", "INV-HF-SMR1-QUIET", "SMR1's restore blocker without the Dump snapshot "
                     "(smr1.blocker_dump_snap)", nc6)

    def nc7():
        m = mutate(fw_text, "              " + ANCHORS["fw.dump_wd_interrupted"][1] + "\n", "")
        cw = hf06_world("dump", fw_text=m)
        try:
            return cw.invariants(["INV-RESTORE-BOUND"], bound_s=20)
        finally:
            cw.close()
    negative_control("NC-HF06-2", "HF-06", "INV-RESTORE-BOUND", "the Dump watchdog's 'snapshot valid but not active' restore "
                     "rule removed (fw.dump_wd_interrupted)", nc7)
    fams = {}
    for _id, fam, _t, out in NC_RESULTS:
        fams.setdefault(fam, []).append(out)
    check("every scenario family has at least one killed negative control and none survived or was invalid",
          set(fams) == {"HF-01", "HF-04", "HF-06"} and all(o == "killed" for v in fams.values() for o in v), str(fams))


# ---------------------------------------------------------------------------------------------------------------------------
# corpus replay and determinism
# ---------------------------------------------------------------------------------------------------------------------------
def section_corpus() -> None:
    print("[12] corpus: every scenario corpus document replays with the _lab_trace engine (digest, anchors, expectations)")
    ids = [c for s in SCENARIOS for c in s["corpus"]]
    cls_of = {}
    for s in SCENARIOS:
        for c in s["corpus"]:
            cls_of[c] = s["id"]
    results = {}
    for cid in ids:
        path = HERE / "corpus" / f"{cid}.json"
        if not path.is_file():
            results[cid] = "missing"
            continue
        doc = T.load_doc(path)
        res = T.replay(doc)
        fid = [f for f, x in FINDINGS.items() if cid in x["corpus"]]
        want = "PASS" if not fid else FINDINGS[fid[0]]["classification"]
        results[cid] = ("ok" if res.ok and doc["id"] == cid and doc["classification"] == want else
                        f"FAILED {res.failed_expectations[:1]} drift={res.drift} mismatch={res.digest_mismatch} "
                        f"anchors={list(res.anchor_problems)[:1]} {doc['classification']}")
        drift = f"SOURCE DRIFT {list(res.drifted_paths)}: expectations only, re-record" if res.drift else "no drift"
        print(f"  info  {cid}: {results[cid][:120]} ({doc['classification']}, {doc['invariant']}, {drift}, trace digest "
              f"{'equal' if res.digest == doc['trace_digest'] else 'DIFFERENT'})")
    # The spec's drift rule decides (_lab_trace.replay ok): with every source digest current, the trace digest and every
    # anchor line must equal the record; with SOURCE DRIFT only the expectations decide (the info line says so).
    check(f"all {len(ids)} corpus documents exist, replay ok (current source digests: trace digest and anchor lines equal "
          "to the record; SOURCE DRIFT: expectations only) and carry the table's classification",
          all(v == "ok" for v in results.values()), str({k: v for k, v in results.items() if v != "ok"}))
    doc = T.load_doc(HERE / "corpus" / "HF-04-d.json")
    bad = dict(doc, expect=[dict(doc["expect"][0], value="ARMED")] + doc["expect"][1:])
    res = T.replay(bad)
    check("negative control: HF-04-d with an altered expectation FAILS its replay", not res.ok and res.failed_expectations
          and res.failed_expectations[0]["observe"] == doc["expect"][0]["observe"])


def section_determinism(first) -> None:
    print("[13] determinism: the nominal Free Power run gives the identical merged EventLog digest on rerun")
    cw = new_world()
    try:
        cw.fw.job_trace = []
        stage_owner(cw, "fp")
        arm(cw, "fp")
        cw.run_until(ST + 3600 + 150)
        d = (cw.log.digest(), len(cw.log))
    finally:
        cw.close()
    check(f"two identical coupled runs give the same digest ({d[1]} events, {d[0][:12]})", d == (first["digest"], first["n"]))


# ---------------------------------------------------------------------------------------------------------------------------
# extended
# ---------------------------------------------------------------------------------------------------------------------------
def section_extended_start_busy() -> None:
    print("[14] EXTENDED: Free Power start-busy width x watchdog phase grid (idle bus after the start)")
    rows = []
    for width in (3, 10, 19):
        for ph in FULL_PHASES:
            r = scheduled_run("fp", bus=H.BusModel(windows=[(ST, ST + float(width))]), ph=ph, minutes=10)
            if "unsupported" in r:
                UNSUPPORTED.append(("HF-01-UNS", f"fp busy start {width} s phase {ph}: {r['unsupported']}"))
            rows.append((width, ph, r))
    for width in (3, 10, 19):
        pts = [(ph, r.get("ov"), r.get("presses")) for w, ph, r in rows if w == width]
        print(f"  info  busy start {width} s: (phase, overrun s, presses) {pts}")
    vals = [r["ov"] for _w, _p, r in rows if r.get("ov") is not None]
    print(f"  info  start-busy grid overrun min {min(vals)} max {max(vals)} s; {len(rows)} runs")
    check(f"EXTENDED start-busy grid ({len(rows)} points): every point starts and restores with the owner's values",
          all(point_ok("fp", r) for _w, _p, r in rows))


# =============================================================================================================================
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")
section_static()
section_fw_inv_control()
NOM_FP = section_hf01_fp()
BUSY = section_hf01_fp_busy_start()
print("[3] HF-01 Free Power window-end overrun sweep (simulated values): watchdog phase x bus model (never busy / the "
      "recorded busy windows BUSY_10S / BUSY_60S / the lab's own poll traffic)")
FP_SW = report_sweep("full" if EXTENDED else "quick", "fp", sweep("fp", FULL_PHASES if EXTENDED else QUICK_PHASES))
NOM_DUMP = section_hf01_dump()
print("[5] HF-01 Dump window-end overrun sweep: watchdog phase x bus model")
DUMP_SW = report_sweep("full" if EXTENDED else "quick", "dump", sweep("dump", FULL_PHASES if EXTENDED else QUICK_PHASES))
if EXTENDED:
    print(f"  info  extended overrun sweeps: {len(FP_SW['rows']) + len(DUMP_SW['rows'])} runs")
CASES = section_hf01_corpus_cases(NOM_DUMP)
finding_hf01(NOM_FP, BUSY, FP_SW, DUMP_SW, NOM_DUMP, CASES)
section_hf04_dump_fp()
section_hf04_fp_dump()
finding_hf04_same(section_hf04_same("fp"), section_hf04_same("dump"))
section_hf06_fp(section_hf06_dump())
section_negative_controls()
section_corpus()
section_determinism(NOM_FP)
if EXTENDED:
    section_extended_start_busy()
print("[15] scenario summary")
for s in SCENARIOS:
    print(f"  info  {s['id']} {s['priority']} {s['classification']} grade {s['grade']} confidence {s['confidence']}: "
          f"findings {s['findings']}; corpus {s['corpus']}")
COUNTED = [fid for fid in FOUND if fid not in DUPLICATE_OF]     # LAB-SUMMARY 'finding' (duplicates are not counted)
for fid, f in FINDINGS.items():
    print(f"  info  {fid} {f['classification']} [{f['severity'].split(':')[0]}] confidence {f['confidence']}: "
          f"{'reproduced' if fid in FOUND else 'NOT reproduced'}; "
          f"{'DUPLICATE of ' + DUPLICATE_OF[fid] + ', not counted' if fid in DUPLICATE_OF else 'counted'}")
print(f"  info  dedupe: {len(DUPLICATE_OF)} of {len(FINDINGS)} findings duplicate another suite's root cause; "
      f"{len(COUNTED)} counted")
for fid, note in RELATED.items():
    print(f"  info  related, not a duplicate: {fid} - {note}")
for uid, point in UNSUPPORTED:
    UNSUPPORTED_POINTS.append(uid)
    print(T.unsupported_line(uid, point))
check("S.LOCAL is the sim's own object and no CoupledWorld is left open at the end", S.LOCAL is FIXED_LOCAL
      and not H._OPEN)
BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME = time.perf_counter() - T0
print(f"  info  runtime {RUNTIME:.1f} s ({'extended' if EXTENDED else 'quick'} mode)")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=REPRODUCED,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
