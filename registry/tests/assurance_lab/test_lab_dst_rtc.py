#!/usr/bin/env python3
"""DST and RTC scenarios of the assurance lab: HF-08 (FPS1 / DGS1 schedules and the firmware Dump START TOU gate on the
2026-10-25 fall-back and the 2027-03-28 spring-forward nights, London time, UTC-true timeline), RT-01 (a Free Power lease
across 01:00 UTC on the RTC rig: no-fault baseline, a lost RTC write callback -> 90 s breaker -> 300 s cooldown -> delayed
large correction, lease watchdog deferral, lease end on the UTC epoch, verified restore), RT-02 (a stopped inverter clock with
an outstanding restore obligation, bounded run: documented design case, surfaced by the stall detector) and RT-03 (split model:
lock windows extracted from a DST-night RTC rig replayed into a FirmwareWorld Dump lease; its SG-25 part is a variant of
F-HF08-3). Offline assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Independent review (applied): F-RT02-1 was reclassified to PASS (documented behaviour: the readback contract is met and the stall
detector is the documented RTC hardware signal); F-RT03-1 was merged into F-HF08-3 as its RTC-step variant (same gate, same
root cause, no new failure mode); F-HF08-1 / F-HF08-2 / F-HF08-3 wording, scope and severity were narrowed.

Tiers: CoupledWorld (_lab_ha, london=True), RtcWorld (_lab_rtc, D1Sim with the real RTC lambdas; ecco_rtc:: runs as the Python
mirror registry/rtc_policy.py) and FirmwareWorld (_lab_fw). Nothing here decides what the firmware or Home Assistant does; the
lab checkers only compare their decisions with the expected invariant.

MODEL ASSUMPTIONS (labelled; INFERRED, not measured)
  - HA semantics (ASSUMPTION, UNVERIFIED offline): Home Assistant resolves a naive input_datetime wall time like Python
    zoneinfo with fold=0 (the repeated autumn hour -> the first, BST copy; the skipped spring hour -> the pre-transition
    offset, so 2027-03-28 01:30 -> 01:30Z = 02:30 BST). The HA sim reproduces exactly that through _lab_clock.LONDON.
    Under the other gap convention (fold=1) the spring run would be at 00:30 GMT instead: still an hour from the typed time.
  - RT-02 obligation stand-in: dump_restore_requested is poked true on the RTC rig (the Dump watchdog does not run there), the
    MODEL of a restore that stays owed; a genuine Free Power lease variant and a no-obligation control are run for comparison
    (all three give the same corrections, so the obligation is not load-bearing). The HA health mapping of
    rtc_stall_detected (WARNING RTC_STALL_DETECTED) is source-read through anchors, not executed.
  - RT-03 split model: the RTC lock windows come from a DST-night D1Sim rig (no Dump lease on D1Sim: FbbNotModelled) and are
    injected into a FirmwareWorld with rtc_lock_windows (correction_in_progress inside the windows; the correction itself is
    not executed there). The rig's lease input is made consistent by poking dump_active_persisted over the lease interval.
    The rig's RTC TOU cache is the synthetic slot bank's 250..255 words (checked equal to a GOLD_TOU rig here). The
    inverter's TOU slot behaviour on its own clock is NOT executed anywhere: the overlap of the inverter clock with a charge
    slot is COMPUTED (grade INFERRED) from the rig's InverterRtc offsets, and its seconds depend on the rig's 60 s read phase.
  - Every register value, TOU slot, power, duration and date is SYNTHETIC (the lab SITE plus the TOU images below).
Quick mode (well under 90 s here); ECCO_LAB_EXTENDED=1 / --extended adds the DGS1 arm-walk sweep over both nights, a firmware
gate sweep at 15-min steps, lease-length and watchdog-phase sweeps on the RTC rig, a correction-threshold sweep and an RT-03
rig read-phase sweep (runtime printed).
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
PINS: list[str] = []            # held 'finding-reproduces:' checks (LAB-SUMMARY 'finding_pins', never in 'pass')
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
    "RT-01 fall baseline: one verified large correction": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10) (fails "
        "under the phase patch with the RTC-rig part)"),
    "RT-01 fall lost callback 75 s before the change: the pre-change": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10); the "
        "cooldown span and the +345.12 s correction follow from it (fails under the phase patch with the RTC-rig "
        "part)"),
    "RT-01 fall the DST correction's own callback lost": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10); the "
        "breaker window and the +525.12 s correction follow from it (fails under the phase patch with the RTC-rig "
        "part)"),
    "RT-01 fall 10-min lease": (
        "the restore delay after the lease end epoch (pinned 15.0 s) is the Free Power watchdog's slot phase on the "
        "rig (fails under the phase patch with the RTC-rig part)"),
    "RT-01 fall 11-min lease": (
        "the restore delay after the lease end epoch (pinned 0.0 s) is the Free Power watchdog's slot phase on the "
        "rig (fails under the phase patch with the RTC-rig part)"),
    "RT-01 spring baseline: one verified large correction": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10) (fails "
        "under the phase patch with the RTC-rig part)"),
    "RT-01 spring lost callback 75 s before the change: the pre-change": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10); the "
        "cooldown span and the +345.12 s correction follow from it (fails under the phase patch with the RTC-rig "
        "part)"),
    "RT-01 spring the DST correction's own callback lost": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10); the "
        "breaker window and the +525.12 s correction follow from it (fails under the phase patch with the RTC-rig "
        "part)"),
    "RT-01 spring 10-min lease": (
        "the restore delay after the lease end epoch (pinned 15.0 s) is the Free Power watchdog's slot phase on the "
        "rig (fails under the phase patch with the RTC-rig part)"),
    "RT-01 spring 11-min lease": (
        "the restore delay after the lease end epoch (pinned 0.0 s) is the Free Power watchdog's slot phase on the "
        "rig (fails under the phase patch with the RTC-rig part)"),
    "RT-03 windows: the fall rig gives the DST lock": (
        "the RTC rig's 60 s rtc_read interval (30 s startup_delay) phase sets when the post-change reads come; "
        "+105.12 s and the lock windows are one read phase (audit: the '+345 s' is one read phase; O-10); the corpus "
        "constants are that phase's windows (fails under the phase patch with the RTC-rig part)"),
    "RT-03 a: a Dump lease ending at -8 s inside the lock": (
        "the Dump watchdog slot after the lock release (pinned +25 s) is the FirmwareWorld watchdog phase (fails "
        "under the phase patch in every run)"),
    "finding-reproduces:F-HF08-3 (RT-03 compound": (
        "pins the inverter clock's in-slot time (1694 s 'at this read phase', 1800 s - 346 s with the lost callback) "
        "to one RTC read phase (fails under the phase patch at some seeds)"),
    "negative control NC-RT01-1 (RT-01)": (
        "the kill needs a Free Power watchdog tick inside a lock window; whether one falls there is the watchdog / "
        "RTC read phase (fails under the phase patch at some seeds)"),
    "NC-RT01-1 characterised": (
        "as NC-RT01-1: the deferral it characterises needs a watchdog tick inside the lock (fails under the phase "
        "patch at some seeds)"),
    "negative control NC-RT01-2 (RT-01)": (
        "as NC-RT01-1: the kill needs a restore attempt inside a lock window (fails under the phase patch at some "
        "seeds)"),
    "HF-08-a: replay ok": _PS_DIGEST,
    "HF-08-b: replay ok": _PS_DIGEST,
    "HF-08-c: replay ok": _PS_DIGEST,
    "HF-08-d: replay ok": _PS_DIGEST,
    "RT-01-a: replay ok": _PS_DIGEST_EXP,
    "RT-01-b: replay ok": _PS_DIGEST_EXP,
    "RT-02-a: replay ok": _PS_DIGEST,
    "RT-03-a: replay ok": _PS_DIGEST_EXP,
    "RT-03-b: replay ok": _PS_DIGEST,
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []


def _ascii(text) -> str:
    return str(text).encode("ascii", "replace").decode("ascii")


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (PINS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {_ascii(detail)}" if detail else ""))


def check_phase_registry() -> None:
    """The closing check of the phase-sensitivity registry (fail loud; run after every other check): every
    PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check executed in this run (a stale prefix
    FAILS); a PHASE_SENSITIVE_EXTENDED_ONLY prefix must be registered and is required to match only in extended mode."""
    executed = PASSES + PINS + FAILURES
    hits = {p: sum(1 for n in executed if n.startswith(p)) for p in PHASE_SENSITIVE_TAGS}
    stale = [p for p, n in hits.items() if not n and (EXTENDED or p not in PHASE_SENSITIVE_EXTENDED_ONLY)]
    bad = ([p for p in PHASE_SENSITIVE_EXTENDED_ONLY if p not in PHASE_SENSITIVE_TAGS]
           + [p for p, why in PHASE_SENSITIVE_TAGS.items() if not p.strip() or not isinstance(why, str)
              or not why.strip()])
    check("phase-sensitivity registry: every PHASE_SENSITIVE_TAGS prefix has a reason and matches at least one check "
          "executed in this run (no stale tag; LAB-SUMMARY phase_sensitive = the executed tagged checks)",
          not stale and not bad, f"stale {stale}; malformed {bad}")


import copy  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

T_START = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_rtc as R  # noqa: E402
import _lab_ha as H  # noqa: E402
import _fbd1_harness as X  # noqa: E402 (read-only: GOLD_TOU, the rig's default TOU cache, for a MODEL-consistency check)

SUITE = "test_lab_dst_rtc"
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")

# ---- CORPUS-DRAFTS-BEGIN (self-contained: uses only C and T; the corpus files were recorded from exactly these drafts) ----
# To regenerate a file after a deliberate change: exec this block, doc = T.record(draft) (two identical replays fill
# trace_digest / source_digests / line_at_record), write T.dumps_doc(doc) to corpus/<id>.json, rerun this suite ([5]).
FALL = C.DST_FALL_2026_UTC                 # 2026-10-25T01:00:00Z
SPRING = C.DST_SPRING_2027_UTC             # 2027-03-28T01:00:00Z
FW_REL = "firmware/ecco_clock_dongle_stage3_4_free_power.yaml"
FPS_REL = "home-assistant/packages/ecco_free_power_schedule.yaml"
DGS_REL = "home-assistant/packages/ecco_dump_to_grid_schedule.yaml"
FCP2_REL = "docs/dev/dump-to-grid-safety-fcp2.md"
HDR_REL = "firmware/include/ecco_rtc_policy.h"
# SYNTHETIC TOU slot images (NOT site values): slot i runs from its HHMM start (250..255) to the next; 274..279 charge flags
BANK_FALL = {250: 0, 251: 100, 252: 130, 253: 800, 254: 1300, 255: 1800, 274: 0, 275: 1, 276: 0, 277: 0, 278: 0, 279: 0}
BANK_SPRING = {250: 0, 251: 200, 252: 230, 253: 800, 254: 1300, 255: 1800, 274: 0, 275: 1, 276: 0, 277: 0, 278: 0, 279: 0}
BANK_NOCHARGE = {274: 0, 275: 0, 276: 0, 277: 0, 278: 0, 279: 0}
DUMP_ENV = {"grid_w": -1000, "batt_w": 1050}           # the lab SITE Dump environment (checked against _lab_fw.SITE in [0])
RIG_START = {"fall": C.utc_of_local(2026, 10, 25, 1, 50, 15), "spring": C.utc_of_local(2027, 3, 28, 0, 50, 15)}
STOP_START = C.utc_of_local(2026, 10, 24, 12, 0, 15)    # RT-02: a midday start 14 h before the fall change (no DST in the run)
WIN_DST_FALL = [FALL + 105.12, FALL + 117.12]           # the no-fault DST correction lock of the fall rig (re-derived in [4])
WIN_PRE_FALL = [[FALL - 74.88, FALL + 16.0], [FALL + 345.12, FALL + 357.12]]   # lost callback before the change (rig, [4])
RT03A_BOOT = FALL + 12 - 15 * 130                      # power-on 2 s before: Dump watchdog slots at FALL + 10 + 15 k
RESTORED = "RESTORED OK - original inverter settings verified"
NO_BUS = {"windows": []}


def _bank(b):
    return {str(k): v for k, v in sorted(b.items())}


def _anchor(path, text):
    return {"path": path, "text": text, "line_at_record": 1}


def _act(at_s, do, **args):
    return {"at_s": at_s, "do": do, "args": args}


def _exp(observe, op, value, **args):
    return {"observe": observe, "args": args, "op": op, "value": value}


def _draft(id_, title, tier, utc_start, world, actions, expect, *, anchors, classification, invariant, confidence,
           ownership, failure_outcome, repair, scenario_priority, finding_priority, notes):
    return {"schema": T.SCHEMA, "id": id_, "title": title, "tier": tier, "seed": 0, "utc_start": C.iso_utc(utc_start),
            "synthetic": True, "ownership": ownership, "source_anchors": [_anchor(p, t) for p, t in anchors],
            "source_digests": {}, "world": world, "actions": actions, "expect": expect, "classification": classification,
            "invariant": invariant, "grade": "VERIFIED", "confidence": confidence, "failure_outcome": failure_outcome,
            "smallest_safe_repair_scope": repair, "scenario_priority": scenario_priority,
            "finding_priority": finding_priority, "notes": notes}


A_FPS_FUTURE = (FPS_REL, 'value_template: "{{ start_ts <= as_timestamp(now()) }}"')
A_DGS_FUTURE = (DGS_REL, 'value_template: "{{ start_ts <= as_timestamp(now()) }}"')
A_FPS_TRIGGER = (FPS_REL, "at: input_datetime.ecco_free_power_schedule_start")
A_FPS_ENDS_BY = (FPS_REL, "(attempt {{ repeat.index }}; ends by {{ (window_end | float(0)) | timestamp_custom('%H:%M') }})")
A_DGS_WALK = (DGS_REL, "{% set m0 = (st[11:13] | int) * 60 + (st[14:16] | int) %}")
A_FW_GATE = (FW_REL, "int m0 = now.hour * 60 + now.minute;")
A_FW_DUMP_END = (FW_REL, "id(dump_end_epoch) = (uint32_t) id(ntp_time).now().timestamp + duration_s;")
A_SG25 = (FCP2_REL, "**Operational restriction until SG-25 is implemented:**")
A_FP_WD_SKIP = (FW_REL, "if (id(free_power_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) "
                        "return false;")
A_FP_WD_END = (FW_REL, "return (uint32_t) now.timestamp >= id(free_power_end_epoch);")
A_DUMP_WD_SKIP = (FW_REL, "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) "
                          "return false;")
A_DUMP_REFUSE = (FW_REL, 'else if (id(correction_in_progress)) id(dump_status).publish_state("REJECTED - RTC correction '
                         'currently active");')
A_BREAKER = (FW_REL, "ABORTED - correction exceeded its deadline")
A_HDR_COOLDOWN = (HDR_REL, "if (in.cooldown_active) {")
A_VERIFY = (FW_REL, "bool verified = !date_mismatch && abs_difference <= threshold;")
A_LEASE_IN = (FW_REL, "rp.lease_active = id(free_power_active_persisted) || id(free_power_restore_requested) ||")
A_STALL = (FW_REL, "bool stalled = inverter_elapsed < (ntp_elapsed - 15);")
A_FPS_ARMED = (FPS_REL, "ARMED - {{ states('input_datetime.ecco_free_power_schedule_start') }}")

CORPUS_DRAFTS = [
    _draft("HF-08-a", "FPS1 armed during the second (GMT) 01:xx of 2026-10-25 for 01:40: refused as a past start", "coupled",
           FALL + 300, {"bus": NO_BUS},
           [_act(60, "arm_schedule", dom="fp", start_local="2026-10-25 01:40:00", minutes=20, power_w=3000),
            _act(60, "run_for", seconds=30)],
           [_exp("last_result", "==", "REJECTED - scheduled start must be in the future", dom="fp"),
            _exp("ha_state", "==", "off", entity="input_boolean.ecco_free_power_schedule_armed")],
           anchors=[A_FPS_FUTURE, A_FPS_TRIGGER], classification="FINDING-NEW", invariant="INV-DST-OWNER-START",
           confidence="medium", scenario_priority="P1", finding_priority="P3",
           ownership="owner arms the Free Power schedule in HA at 01:06 GMT (second copy of the repeated hour); FPS1 owns the "
                     "arm validation; synthetic 20 min / 3000 W",
           failure_outcome="the GMT copy of 01:00-02:00 cannot be scheduled (the refusal text blames a past start), and a "
                           "01:xx armed beforehand always runs in the BST copy, one real hour before a GMT-copy intent",
           repair="FPS1 arm validation only (HA templates, refusal only, no firmware change): detect an ambiguous or "
                  "nonexistent local start (both UTC offsets) and refuse it with a DST-specific message; showing the UTC "
                  "offset in result texts is optional (255-character limit); interim, docs only: extend the change-night "
                  "operational restriction to Free Power schedules",
           notes="scope FPS1; the DGS1 half (same arm check) is under the documented SG-25 operational restriction; "
                 "severity availability / diagnostics, low, fail-closed; HA fold=0 semantics are an ASSUMPTION (zoneinfo, "
                 "INFERRED for live HA); stage0-safety-case.md names the schedules' as_timestamp zone dependency, not the "
                 "repeated hour"),
    _draft("HF-08-b", "FPS1 armed for the nonexistent 2027-03-28 01:30: armed silently and run one hour from the typed time",
           "coupled",
           C.utc_of_local(2027, 3, 28, 0, 0), {"bus": NO_BUS},
           [_act(60, "arm_schedule", dom="fp", start_local="2027-03-28 01:30:00", minutes=30, power_w=3000),
            _act(60, "run_for", seconds=5400)],
           [_exp("last_result", "==", "STARTED OK - 3000W for 30 min (attempt 1; ends by 03:00)", dom="fp"),
            _exp("fw_status", "startswith", "ACTIVE - VERIFIED OK", dom="fp")],
           anchors=[A_FPS_TRIGGER, A_FPS_ENDS_BY, A_FPS_ARMED], classification="FINDING-NEW",
           invariant="INV-DST-OWNER-START", confidence="medium", scenario_priority="P1", finding_priority="P3",
           ownership="owner arms the Free Power schedule for a wall time the spring-forward night skips; FPS1 time trigger "
                     "and firmware START; synthetic 30 min / 3000 W",
           failure_outcome="the run happens one hour away from the typed wall time (02:30 BST under fold=0; 00:30 GMT under "
                           "fold=1) with no warning; the ARMED text echoes the typed 01:30",
           repair="FPS1 arm validation only (HA templates, refusal only, no firmware change): refuse a nonexistent local start "
                  "with a DST-specific message, detected by a round trip of the resolved instant against the typed HH:MM, "
                  "which does not depend on the fold convention",
           notes="severity diagnostics / UX, low (no safety or availability impact; cost negligible and tariff-dependent); "
                 "the DGS1 instance is under the SG-25 operational restriction; HA gap semantics are an ASSUMPTION "
                 "(zoneinfo fold=0: pre-transition offset), INFERRED for live HA"),
    _draft("HF-08-c", "DGS1 + firmware admit 01:35 BST + 60 min on 2026-10-25 across a repeated 01:00-01:30 grid slot",
           "coupled", C.utc_of_local(2026, 10, 25, 0, 0), {"bus": NO_BUS, "fw_world_kwargs": {"bank": _bank(BANK_FALL)}},
           [_act(240, "arm_schedule", dom="dump", start_local="2026-10-25 01:35:00", minutes=60, power_w=3000, stop_soc=20),
            _act(240, "run_for", seconds=5760)],
           [_exp("last_result", "==", "STARTED OK - 3000W for 60 min, Stop SOC 20% (attempt 1; ends by 01:35)", dom="dump"),
            _exp("fw_status", "startswith", "ACTIVE - VERIFIED OK", dom="dump")],
           anchors=[A_DGS_WALK, A_FW_GATE, A_SG25], classification="FINDING-KNOWN:SG-25", invariant="INV-DST-TOU-SLOT-CLEAR",
           confidence="high", scenario_priority="P1", finding_priority="P2",
           ownership="owner arms a scheduled Dump in HA; DGS1 arm walk then the firmware START gate decide; synthetic slot 2 "
                     "01:00-01:30 Grid charge",
           failure_outcome="an export lease runs through the repeated 01:00-01:30 GMT, a slot with a charge source set",
           repair="firmware START gate only (the documented SG-25 fix: walk the window in UTC, refuse when either offset "
                  "overlaps); updating the DGS1 UX mirror is optional consistency, a DGS1 change-night refusal an optional "
                  "interim that is not the SG-25 fix",
           notes="SG-25 documents the firmware gate; the DGS1 arm walk is a declared refusal-only UX mirror with the same DST "
                 "blindness, covered by the documented operational restriction (no manual or scheduled Dump 00:00-03:00 "
                 "local on the change nights); the DGS1 start instant uses the fold=0 ASSUMPTION; this file asserts the "
                 "admission only (the 30 min real overlap is asserted in the suite)"),
    _draft("HF-08-d", "Firmware Dump START gate admits 2027-03-28 00:45 GMT + 60 min although the lease runs into a "
           "02:00-02:30 BST grid slot", "firmware", C.utc_of_local(2027, 3, 28, 0, 44), {"bank": _bank(BANK_SPRING)},
           [_act(0, "run_for", seconds=60), _act(60, "telemetry", **DUMP_ENV),
            _act(60, "dump_start", power_w=1000, stop_soc=25, minutes=60), _act(60, "run_for", seconds=5)],
           [_exp("globals", "==", {"dump_end_epoch": C.utc_of_local(2027, 3, 28, 0, 45) + 3600,
                                   "dump_start_tou_conflict_slot": 0},
                 names=["dump_start_tou_conflict_slot", "dump_end_epoch"]),
            _exp("status", "startswith", "ACTIVE - VERIFIED OK", dom="dump")],
           anchors=[A_FW_GATE, A_FW_DUMP_END, A_SG25], classification="FINDING-KNOWN:SG-25",
           invariant="INV-DST-TOU-SLOT-CLEAR", confidence="high", scenario_priority="P1", finding_priority="P2",
           ownership="Dump START pressed on the dongle at 00:45 GMT on the spring-forward night; firmware gate decides; "
                     "synthetic slot 2 02:00-02:30 Grid charge",
           failure_outcome="the gate walks 00:45-01:45 local (minutes that partly never happen) and misses the 02:00-02:30 "
                           "BST slot the lease really covers",
           repair="firmware START gate only (SG-25 as documented: UTC walk, refuse when either offset overlaps)",
           notes="the lease end itself is a UTC epoch (start + 3600 s), as the SG-25 section states; a manual START, so no "
                 "HA fold assumption is involved; severity safety (known, DEFERRED): a precautionary gate misses a case, "
                 "no hazard is demonstrated here (the inverter TOU is not executed)"),
    _draft("RT-01-a", "Fall: lost RTC write callback 75 s before 01:00 UTC under an active Free Power lease: breaker, "
           "cooldown, delayed DST correction, restore deferred out of the lock", "rtc", RIG_START["fall"],
           {"kind": "fall", "fp_lease": True, "fp_minutes": 10},
           [_act(0, "run_for", seconds=FALL - 180 - RIG_START["fall"]),
            _act(FALL - 180 - RIG_START["fall"], "set_outcomes", write=["timeout_lost", "ok"]),
            _act(FALL - 180 - RIG_START["fall"], "rtc_offset", offset_s=-400),
            _act(FALL - 180 - RIG_START["fall"], "run_for", seconds=780)],
           [_exp("lock_windows", "==", WIN_PRE_FALL),
            _exp("n_corrections", "==", 1, after_change=True, reason="large", verified=True),
            _exp("global_value", "==", 1, name="failed_corrections"),
            _exp("fp_status", "==", RESTORED),
            _exp("fp_leases", "==", [{
                "start_utc": RIG_START["fall"] + 0.0, "active_utc": RIG_START["fall"] + 1.2, "end_epoch": FALL + 15,
                "restore_start_utc": FALL + 30.0, "restored_utc": FALL + 31.32, "restored_text": RESTORED,
                "final_status": RESTORED, "statuses": [
                    [RIG_START["fall"] + 0.0, "STARTING - taking fresh inverter snapshot"],
                    [RIG_START["fall"] + 0.36, "SNAPSHOT DURABLY COMMITTED - 6000W at 52.0V -> 115A grid charge target"],
                    [RIG_START["fall"] + 1.2, "ACTIVE - VERIFIED OK; 115A grid charge; automatic restore armed"],
                    [FALL + 30.0, "RESTORING - confirming live inverter state before writing"], [FALL + 31.32, RESTORED]]}]),
            _exp("invariants", "==", {k: 0 for k in ("i1", "i2", "i3", "i6", "audit", "state", "wire", "nvs", "oracle")})],
           anchors=[A_BREAKER, A_HDR_COOLDOWN, A_FP_WD_SKIP], classification="PASS", invariant="INV-RTC-NO-RESTORE-IN-LOCK",
           confidence="high", scenario_priority="P1", finding_priority=None,
           ownership="Free Power lease (real START button) owns 230/232/256-261/268-279; the RTC path owns 22-24; synthetic "
                     "inverter offset -400 s and a lost write callback",
           failure_outcome="a restore started inside the RTC lock, or a DST correction never verified",
           repair="none (documented design: cooldown holds even a large error; the watchdog skips while the lock is held)",
           notes="the 10-min lease ends at +15 s inside the breaker lock (-74.88..+16.0 s); restore at the +30 s watchdog slot"),
    _draft("RT-01-b", "Spring: the DST correction's own write callback is lost under an active Free Power lease: the "
           "inverter stays 1 h off until +537 s", "rtc", RIG_START["spring"],
           {"kind": "spring", "fp_lease": True, "fp_minutes": 40},
           [_act(0, "run_for", seconds=SPRING - 180 - RIG_START["spring"]),
            _act(SPRING - 180 - RIG_START["spring"], "set_outcomes", write=["timeout_lost", "ok"]),
            _act(SPRING - 180 - RIG_START["spring"], "run_for", seconds=2100)],
           [_exp("lock_windows", "==", [[SPRING + 105.12, SPRING + 196.0], [SPRING + 525.12, SPRING + 537.12]]),
            _exp("n_corrections", "==", 1, after_change=True, reason="large", verified=True),
            _exp("global_value", "==", 1, name="failed_corrections"),
            _exp("fp_status", "==", RESTORED)],
           anchors=[A_BREAKER, A_HDR_COOLDOWN, A_FP_WD_END], classification="PASS", invariant="INV-RTC-DST-CORRECTED",
           confidence="high", scenario_priority="P1", finding_priority=None,
           ownership="Free Power lease (real START button); the RTC path owns 22-24; synthetic lost write callback",
           failure_outcome="the DST correction never verifies, or the lease end moves off its UTC epoch",
           repair="none (documented design); diagnostics note: the inverter clock is 1 h off for about 9 min",
           notes="the restore starts at the end epoch (+1815 s) exactly; the large correction is held 300 s by the cooldown"),
    _draft("RT-02-a", "Stopped inverter clock (a documented design case) with an outstanding Dump restore obligation: only "
           "large corrections, each read back 'Verified OK', failed_corrections 0, rtc_stall_count rising", "rtc", STOP_START,
           {"kind": "fall", "rate": -1.0},
           [_act(0, "poke", name="dump_restore_requested", value=True), _act(0, "run_for", seconds=2400)],
           [_exp("n_corrections", "==", 5, reason="large", verified=True),
            _exp("n_corrections", "==", 5),
            _exp("global_value", "==", 0, name="failed_corrections"),
            _exp("global_value", "==", 34, name="rtc_stall_count")],
           anchors=[A_VERIFY, A_LEASE_IN, A_STALL], classification="PASS", invariant="INV-RTC-STALL-SURFACED",
           confidence="high", scenario_priority="P3", finding_priority=None,
           ownership="RTC path owns 22-24; synthetic stopped inverter clock (rate -1.0); a Dump restore obligation stays owed "
                     "(MODEL: poked dump_restore_requested; not load-bearing, the no-obligation control is identical)",
           failure_outcome="a stopped inverter clock with no signal at all (no stall detection) or with unbounded drift",
           repair="none (documented behaviour: the readback contract is met and the stall detector is the documented RTC "
                  "hardware signal); optional, HA health only: hold RTC_STALL_DETECTED for a window after an "
                  "rtc_stall_count rise",
           notes="reclassified from FINDING-NEW to PASS after review; 'Verified OK' means the readback matched the write, not "
                 "that the clock runs; failed_corrections is scoped to retries, comms errors and the breaker; the stall "
                 "entity drops to off for about 108 s after each verified correction; with correction_threshold 10 the "
                 "readback fails instead; a stopped clock is INFERRED, never observed"),
    _draft("RT-03-a", "Split model: rig lock windows injected into a Dump lease: the end inside the lock is deferred, a START "
           "inside the lock is refused", "firmware", RT03A_BOOT, {"bank": _bank(BANK_NOCHARGE)},
           [_act(0, "rtc_lock_windows", windows=WIN_PRE_FALL), _act(0, "run_for", seconds=60),
            _act(60, "telemetry", **DUMP_ENV),
            _act(FALL - 1808 - RT03A_BOOT, "dump_start", power_w=1000, stop_soc=25, minutes=30),
            _act(FALL - 1808 - RT03A_BOOT, "run_for", seconds=2158),
            _act(FALL + 350 - RT03A_BOOT, "dump_start", power_w=1000, stop_soc=25, minutes=30)],
           [_exp("status", "==", "REJECTED - RTC correction currently active", dom="dump"),
            _exp("status", "==", "DURATION EXPIRED", dom="dump_end"),
            _exp("bank", "==", {"244": 2, "256": 8000}, addrs=[244, 256]),
            _exp("invariants", "==", [])],
           anchors=[A_DUMP_WD_SKIP, A_DUMP_REFUSE], classification="PASS", invariant="INV-RTC-NO-RESTORE-IN-LOCK",
           confidence="medium", scenario_priority="P2", finding_priority=None,
           ownership="Dump lease (real START button) owns 244/256-261; the RTC lock windows are a MODEL replay of the fall "
                     "rig's lost-callback run",
           failure_outcome="the Dump end / restore runs inside an RTC correction, or a START is admitted during one",
           repair="none (documented guards hold)",
           notes="MODEL ASSUMPTION (split model): correction_in_progress windows from D1Sim, the correction not executed here"),
    _draft("RT-03-b", "Split model, variant of F-HF08-3 (SG-25): Dump 01:35 BST + 60 min on 2026-10-25 admitted across a "
           "01:00-01:30 grid slot with the rig's DST correction lock mid-lease", "firmware",
           C.utc_of_local(2026, 10, 25, 1, 34),
           {"bank": _bank(BANK_FALL)},
           [_act(0, "rtc_lock_windows", windows=[WIN_DST_FALL]), _act(0, "run_for", seconds=60),
            _act(60, "telemetry", **DUMP_ENV), _act(60, "dump_start", power_w=1000, stop_soc=25, minutes=60),
            _act(60, "run_for", seconds=3630)],
           [_exp("globals", "==", {"dump_start_tou_conflict_slot": 0}, names=["dump_start_tou_conflict_slot"]),
            _exp("status", "==", "DURATION EXPIRED", dom="dump_end"),
            _exp("status", "==", RESTORED, dom="dump")],
           anchors=[A_FW_GATE, A_SG25, A_DUMP_WD_SKIP], classification="FINDING-KNOWN:SG-25",
           invariant="INV-DST-TOU-SLOT-CLEAR", confidence="medium", scenario_priority="P2", finding_priority="P2",
           ownership="Dump lease (real START button); RTC lock window replayed from the fall rig (MODEL); synthetic slot 2 "
                     "01:00-01:30 Grid charge",
           failure_outcome="an export lease admitted across a charge slot (SG-25); after the correction the inverter clock "
                           "matches real local time, so its in-slot time is a subset of the 30 min real overlap",
           repair="firmware START gate only (SG-25 as documented, both offsets); no RTC-side change",
           notes="this replay re-proves the gate admission and a clean epoch end with the window injected; it does not "
                 "discriminate the RTC element (no lease action falls inside the window; RT-03-a does); the inverter-clock "
                 "in-slot time (about 28 min, INFERRED, computed in the suite) depends on the rig's read phase"),
]
# ---- CORPUS-DRAFTS-END ----

IDLE = H.BusModel(windows=[])
FP_STATUS_PREFIX = "RESTORED OK"
DUMP_TOU_REFUSED_FW = "REJECTED - lease window overlaps TOU slot"
DUMP_TOU_REFUSED_HA = "REJECTED - window overlaps a TOU slot with a charge source set"
RTC_REFUSED = "REJECTED - RTC correction currently active"
CORPUS_DIR = HERE / "corpus"

FINDINGS: dict[str, str] = {}
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (none: no construct here is unmodelled)
NC_RESULTS: list[tuple[str, str]] = []


def finding(fid: str, text: str) -> None:
    if fid not in FINDINGS:
        FINDINGS[fid] = text
        print(_ascii(T.finding_line(fid, text)))


def info(text: str) -> None:
    print("  info  " + _ascii(text))


def r3(x):
    return None if x is None else round(float(x), 3)


# =============================================================================================================================
# scenario table (ownership, anchors, invariant, failure outcome, classification, grade, confidence, priority)
# =============================================================================================================================
SCENARIOS = [
    {"id": "HF-08", "priority": "P1", "tier": "coupled + firmware",
     "title": "DST nights through FPS1 / DGS1 and the firmware Dump START TOU gate (London time, UTC-true timeline)",
     "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "medium",
     "grade_note": "VERIFIED in this harness against the real package YAML and firmware; live HA fold / gap handling INFERRED",
     "invariant": "INV-DST-OWNER-START (a local start runs at that wall time or is refused with a DST-specific reason); "
                  "INV-DST-TOU-SLOT-CLEAR (an admitted Dump lease overlaps no charge slot in real local time); "
                  "INV-EPOCH-END (lease end = gate second + duration in UTC); INV-DST-TOU-REFUSE (normal-day control)",
     "ownership": "owner arms FPS1 / DGS1 in HA; FPS1 / DGS1 own arm validation and the press; the firmware owns the START "
                  "gate, the lease and the restore (230/232/244/256-261/268-279)",
     "anchors": [A_FPS_FUTURE, A_DGS_FUTURE, A_FPS_TRIGGER, A_FPS_ENDS_BY, A_FPS_ARMED, A_DGS_WALK, A_FW_GATE, A_FW_DUMP_END,
                 A_SG25, (DGS_REL, "# 2026-09-26 pre-live hardening: early UX mirror of the firmware's"),
                 ("docs/dev/advanced-config/stage0-safety-case.md",
                  "the existing Free Power / Dump schedule checks share this dependency"),
                 ("home-assistant/tests/_ha_script_sim.py", "replace(tzinfo=LOCAL).timestamp()"),
                 ("registry/tests/assurance_lab/_lab_clock.py",
                  "Home Assistant resolves an input_datetime wall time with zoneinfo semantics (fold=0)")],
     "failure_outcome": "an owner schedule silently shifts by an hour or is refused with a misleading text; an export lease "
                        "runs through a charge slot on a clock-change night",
     "findings": ["F-HF08-1", "F-HF08-2", "F-HF08-3"], "corpus": ["HF-08-a", "HF-08-b", "HF-08-c", "HF-08-d"]},
    {"id": "RT-01", "priority": "P1", "tier": "rtc",
     "title": "Free Power lease across 01:00 UTC on both nights: baseline, lost write callback, breaker, cooldown, deferral",
     "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
     "grade_note": "VERIFIED in this harness (ecco_rtc:: as the Python mirror)",
     "invariant": "INV-RTC-DST-CORRECTED (one verified large correction after the change within the design bound); "
                  "INV-RTC-WD-SKIP / INV-RTC-NO-RESTORE-IN-LOCK (no lease-end action / restore inside a lock window); "
                  "INV-EPOCH-END",
     "ownership": "Free Power lease (real START + 15 s watchdog) owns its registers; the RTC path owns 22-24 and the lock",
     "anchors": [A_FP_WD_SKIP, A_FP_WD_END, A_BREAKER, A_HDR_COOLDOWN,
                 (FW_REL, "uint32_t end_epoch = (uint32_t) now.timestamp + (minutes * 60U);")],
     "failure_outcome": "restore inside an RTC transaction, a lease end shifted by the clock change, a DST error never "
                        "corrected",
     "findings": [], "corpus": ["RT-01-a", "RT-01-b"]},
    {"id": "RT-02", "priority": "P3", "tier": "rtc",
     "title": "Stopped inverter clock with an outstanding restore obligation (bounded 40 min run; a documented design case)",
     "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
     "grade_note": "VERIFIED in this harness (the verify decision is pure YAML; the mirror only sets the correction cadence); "
                   "the HA health mapping is source-read (anchors), not executed; a stopped clock is INFERRED, never observed",
     "invariant": "INV-RTC-LEASE-HOLD (only large corrections while the obligation is owed, firmware == mirror); "
                  "INV-RTC-DRIFT-BOUND (|error| <= 600 s); INV-RTC-STALL-SURFACED (the documented RTC hardware signal "
                  "reports the stopped clock: rtc_stall_count rises in every correction cycle, rtc_stall_detected is on for "
                  "at least half of the run after its first detection and never off for more than 150 s)",
     "ownership": "RTC path owns 22-24; the obligation is a MODEL poke of dump_restore_requested (and a genuine FP lease; a "
                  "no-obligation control gives the same corrections)",
     "anchors": [A_VERIFY, A_LEASE_IN, A_STALL, (HDR_REL, "so a truly stopped clock stays bounded"),
                 (HDR_REL, "followed by a verified readback"),
                 ("registry/tests/test_rtc_policy.py",
                  "frozen: a large error on both reads still confirms (a stopped clock stays bounded)"),
                 ("registry/health_reason_codes.yaml", 'safe_diagnostic_step: "Check rtc_stall_count for repeated '
                  'occurrences before treating a single stall as a hardware fault."'),
                 ("home-assistant/packages/ecco_system_health.yaml", "{% set codes = codes + ['RTC_STALL_DETECTED'] %}"),
                 ("docs/SYSTEM_HEALTH_ARCHITECTURE.md", "`rtc_correction_duration`, `rtc_stall_detected`, `rtc_ntp_synced`"),
                 ("docs/SYSTEM_HEALTH_ARCHITECTURE.md", "`rtc_read_freshness`, `rtc_drift_uncorrected`")],
     "failure_outcome": "a stopped inverter clock with no signal (stall detector silent) or with unbounded drift",
     "notes": "reclassified after review: F-RT02-1 (FINDING-NEW) -> PASS, documented behaviour. A stopped clock meets the "
              "documented readback contract ('Verified OK' = the readback matched the write), failed_corrections is scoped "
              "to retries, comms errors and the breaker, and RTC_STALL_DETECTED (WARNING) is the documented signal, with "
              "rtc_stall_count named for repeated occurrences. Undocumented diagnostics residue (OBS-RT02-1): the stall "
              "entity drops to off for about 108 s after each verified correction",
     "findings": [], "corpus": ["RT-02-a"]},
    {"id": "RT-03", "priority": "P2", "tier": "rtc -> firmware (split model)",
     "title": "DST-night lock windows from the RTC rig replayed into a FirmwareWorld Dump lease (London time)",
     "classification": "FINDING-KNOWN:SG-25", "grade": "VERIFIED", "confidence": "medium",
     "grade_note": "VERIFIED in this harness for the lock guards and the gate admission (split MODEL); the inverter-clock "
                   "in-slot seconds are INFERRED (computed from InverterRtc offsets; the inverter TOU is not executed)",
     "invariant": "INV-RTC-WD-SKIP / INV-RTC-NO-RESTORE-IN-LOCK / INV-RTC-START-LOCK (hold); INV-DST-TOU-SLOT-CLEAR "
                  "(violated: SG-25, the RTC-step variant of F-HF08-3)",
     "ownership": "Dump lease owns 244/256-261; the lock windows are a MODEL replay from D1Sim",
     "anchors": [A_DUMP_WD_SKIP, A_DUMP_REFUSE, (FW_REL, "return (uint32_t) now.timestamp >= id(dump_end_epoch);"),
                 ("registry/tests/assurance_lab/_lab_fw.py", "def rtc_lock_windows(self, windows) -> None:"),
                 ("registry/tests/assurance_lab/_lab_rtc.py", "def lock_windows(sim) -> list:"),
                 (HDR_REL, "if (in.lease_active && !large) {"),
                 (FCP2_REL, "**The inverter's own clock** may lag the change until ECCO's RTC correction")],
     "failure_outcome": "Dump end / restore / START during an RTC correction; an export lease admitted across a charge slot "
                        "(the corrected inverter clock inside it)",
     "notes": "reclassified after review: F-RT03-1 merged into F-HF08-3 as its RTC-step variant (same gate, same root cause); "
              "after the correction the inverter clock matches real local time, so its in-slot time is the 30 min real "
              "overlap minus the correction lag (+60..+120 s after the change, by rig read phase)",
     "findings": ["F-HF08-3"], "corpus": ["RT-03-a", "RT-03-b"]},
]

# finding register (descriptions only; repairs are NEVER implemented). Reclassified ids must never print a FINDING line.
FINDINGS_META = {
    "F-HF08-1": {"classification": "FINDING-NEW", "confidence": "medium",
                 "scope": "FPS1 (the DGS1 mirror of the arm check is under the SG-25 operational restriction)",
                 "severity": "availability / diagnostics, low (fail-closed refusal; a 01:xx armed beforehand runs in the BST "
                             "copy)",
                 "reachability": "INFERRED, very low (FPS1 inside 01:00-02:00 local on a fall-back night)",
                 "repair": "FPS1 arm validation: refuse an ambiguous or nonexistent local start with a DST-specific message"},
    "F-HF08-2": {"classification": "FINDING-NEW", "confidence": "medium",
                 "scope": "FPS1 (DGS1 alike, under the SG-25 operational restriction)",
                 "severity": "diagnostics / UX, low (no safety or availability impact; cost negligible, tariff-dependent)",
                 "reachability": "INFERRED, very low (a typed 01:00-01:59 on 2027-03-28)",
                 "repair": "FPS1 arm validation: refuse a nonexistent local start (round trip of the resolved instant)"},
    "F-HF08-3": {"classification": "FINDING-KNOWN:SG-25", "confidence": "high",
                 "scope": "firmware Dump START gate and its DGS1 UX mirror; variant: RT-03 RTC step mid-lease (formerly "
                          "F-RT03-1)",
                 "severity": "safety (known, DEFERRED): a precautionary gate misses a case; no hazard demonstrated here; "
                             "practical impact low",
                 "reachability": "INFERRED, low (a charge-slot boundary inside the shifted hour and a Dump lease on a change "
                                 "night against the documented restriction)",
                 "repair": "firmware START gate only: the documented SG-25 fix (UTC walk, both offsets)"},
}
RECLASSIFIED = {"F-RT02-1": "PASS (documented behaviour; RT-02)", "F-RT03-1": "merged into F-HF08-3 (RT-03 variant)"}


# =============================================================================================================================
# lab invariant checkers (each returns [{inv, seq, detail}]); they compare, they never decide
# =============================================================================================================================
def _v(inv, detail):
    return {"inv": inv, "seq": None, "detail": _ascii(detail)}


def in_window(t, wins) -> bool:
    return any(a <= t < b for a, b in wins)


def release_after(t, wins) -> float:
    """The first instant >= t outside every window."""
    moved = True
    while moved:
        moved = False
        for a, b in wins:
            if a <= t < b:
                t, moved = b, True
    return t


def check_epoch_end(dom, starting_utc, minutes, end_epoch, restore_utc, wins=(), wd_s=15.0, slack_s=0):
    """INV-EPOCH-END: the lease end is the START's UTC second + minutes * 60 (slack_s for the asynchronous rig) and the restore
    starts at the first watchdog slot at / after it that lies outside every RTC lock window (<= release + wd_s)."""
    out = []
    want = math.floor(starting_utc) + minutes * 60
    if end_epoch is None or not 0 <= end_epoch - want <= slack_s:
        out.append(_v("INV-EPOCH-END", f"{dom}: end epoch {end_epoch} != START second {math.floor(starting_utc)} + "
                                        f"{minutes} min (slack {slack_s})"))
    if end_epoch is not None:
        hi = release_after(end_epoch, wins) + wd_s
        if restore_utc is None or not end_epoch <= restore_utc <= hi:
            out.append(_v("INV-EPOCH-END", f"{dom}: restore at {r3(restore_utc)} outside [{end_epoch}, {r3(hi)}]"))
    return out


def check_wd_skip(dom, end_epoch, events, wins, until=None):
    """INV-RTC-WD-SKIP: between the lease end epoch and the completed restore (until), no lease-end action of the domain (a
    status publish) lies inside a lock window (the watchdog skips while correction_in_progress)."""
    return [_v("INV-RTC-WD-SKIP", f"{dom}: '{text[:50]}' at {r3(t)} inside an RTC lock window")
            for t, text in events if end_epoch is not None and end_epoch <= t and (until is None or t <= until)
            and in_window(t, wins)]


def check_no_restore_in_lock(dom, statuses, writes, wins):
    """INV-RTC-NO-RESTORE-IN-LOCK: no RESTORING status and no restore write inside a lock window."""
    out = [_v("INV-RTC-NO-RESTORE-IN-LOCK", f"{dom}: '{text[:40]}' at {r3(t)} inside a lock window")
           for t, text in statuses if text.startswith("RESTORING") and in_window(t, wins)]
    out += [_v("INV-RTC-NO-RESTORE-IN-LOCK", f"{dom}: restore write {addr} at {r3(t)} inside a lock window")
            for t, addr in writes if in_window(t, wins)]
    return out


def check_start_lock(dom, t, status, n_writes, wins):
    """INV-RTC-START-LOCK: a START attempted inside a lock window is refused with the firmware's text and writes nothing."""
    if not in_window(t, wins):
        return [_v("INV-RTC-START-LOCK", f"{dom}: set-up error, the START at {r3(t)} is not inside a lock window")]
    if not (status == RTC_REFUSED and n_writes == 0):
        return [_v("INV-RTC-START-LOCK", f"{dom}: START inside the lock gave '{status[:50]}' with {n_writes} write(s)")]
    return []


def check_dst_corrected(corrections_after, change_utc, aborted_release=None):
    """INV-RTC-DST-CORRECTED: exactly one verified large correction after the change, queued within 180 s of it, or (after an
    aborted transaction) within release + 300 s cooldown + two 60 s confirming reads + 15 s."""
    bound = 180.0 if aborted_release is None else max(180.0, aborted_release - change_utc + 300 + 120 + 15)
    big = [c for c in corrections_after if c["reason"] == "large" and c["verified"]]
    if len(big) != 1:
        return [_v("INV-RTC-DST-CORRECTED", f"{len(big)} verified large corrections after the change")]
    if not 0 < big[0]["queued_utc"] - change_utc <= bound:
        return [_v("INV-RTC-DST-CORRECTED", f"queued at +{r3(big[0]['queued_utc'] - change_utc)} s > bound {bound} s")]
    return []


def check_lease_hold(decisions, mismatches):
    """INV-RTC-LEASE-HOLD: while the obligation is owed every over-threshold read is held ('lease', or a hold that also
    applies to large errors) or corrected only as 'large', and the firmware decided exactly as the mirror (no oracle
    mismatch)."""
    out = [_v("INV-RTC-LEASE-HOLD", f"read at {r3(d['utc'])}: reason {d['reason']} (err {d['err_s']})") for d in decisions
           if d["reason"] in ("background", "boot", "min_gap", "precision", "zone_cross")]
    out += [_v("INV-RTC-LEASE-HOLD", f"firmware != mirror: {m}") for m in mismatches]
    return out


def check_drift_bound(decisions, bound_s=600):
    """INV-RTC-DRIFT-BOUND: |inverter error| seen by every regular read <= bound_s (large 300 s + confirmation and quiet-window
    slack)."""
    worst = max((abs(d["err_s"]) for d in decisions), default=0)
    return [_v("INV-RTC-DRIFT-BOUND", f"max |error| {worst} s > {bound_s} s")] if worst > bound_s else []


def check_tou_refuse(where, result, prefix):
    """INV-DST-TOU-REFUSE (normal-day control): a window that really crosses a charge slot is refused."""
    return [] if str(result).startswith(prefix) else [_v("INV-DST-TOU-REFUSE", f"{where}: admitted ('{str(result)[:60]}')")]


def slots_of(bank: dict) -> list:
    starts = [(bank[250 + i] // 100) * 60 + bank[250 + i] % 100 for i in range(6)]
    return [(starts[i], starts[(i + 1) % 6], (bank[274 + i] & 3) != 0) for i in range(6)]


def in_charge_slot(minute: int, bank: dict) -> bool:
    for s, e, charge in slots_of(bank):
        inside = (e > s and s <= minute < e) or (e < s and (minute >= s or minute < e))
        if inside and charge:
            return True
    return False


def real_overlap_min(start_utc: int, minutes: int, bank: dict) -> int:
    """Oracle (lab arithmetic, not a control decision): minutes k = 0..minutes (inclusive, like the gate's walk) whose REAL
    London wall time lies in a slot with a charge source."""
    n = 0
    for k in range(minutes + 1):
        y, mo, d, h, mi, s, _dst = C.local_fields(start_utc + 60 * k)
        n += in_charge_slot(h * 60 + mi, bank)
    return n


def walked_overlap_min(start_utc: int, minutes: int, bank: dict) -> int:
    """What a local-minute walk from the start's wall time sees (the documented SG-25 behaviour, for comparison only)."""
    y, mo, d, h, mi, s, _dst = C.local_fields(start_utc)
    return sum(in_charge_slot((h * 60 + mi + k) % 1440, bank) for k in range(minutes + 1))


def check_slot_clear(where, start_utc, minutes, bank):
    """INV-DST-TOU-SLOT-CLEAR: an admitted Dump lease overlaps no charge slot in real local time."""
    n = real_overlap_min(start_utc, minutes, bank)
    return [_v("INV-DST-TOU-SLOT-CLEAR", f"{where}: {n} lease minute(s) inside a charge slot in real local time")] if n else []


def invs(viol) -> list:
    return sorted({x["inv"] for x in viol})


# =============================================================================================================================
# world drivers
# =============================================================================================================================
FW_TEXT = T.read_source_text(FW_REL)


def mutate(text: str, pairs) -> str:
    """Exact-count (1) in-memory replacement; a missing or repeated anchor raises (never a silent no-op)."""
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            raise ValueError(f"mutation anchor occurs {n} times (want 1): {old[:70]!r}")
        text = text.replace(old, new)
    return text


def coupled(u0, arms, run_to, *, bank=None, fw=None, package_texts=None, plant=False, mid=None):
    """One CoupledWorld run (london=True, never-busy bus); returns the observations (the world is closed)."""
    kw = {}
    if bank is not None:
        kw["bank"] = dict(bank)
    if fw is not None:
        kw["fw"] = fw
    cw = H.CoupledWorld(u0, bus=IDLE, fw_world_kwargs=kw, package_texts=package_texts)
    out = {}
    try:
        if plant:
            cw.dump_plant()
        for dom, start, minutes, power, stop_soc, at_rel in arms:
            cw.arm_schedule(dom, start, minutes, power, stop_soc=stop_soc, at_utc=u0 + at_rel)
        if mid is not None:
            cw.run_until(mid)
            out["mid"] = cw.fw.globals_view(["free_power_end_epoch", "dump_end_epoch", "dump_start_tou_conflict_slot"])
        cw.run_until(run_to)
        out["last"] = {d: cw.last_result(d) for d in ("fp", "dump")}
        out["status"] = {d: cw.schedule_status(d) for d in ("fp", "dump")}
        out["armed"] = {d: cw.ha_state(H.ARMED[d]) for d in ("fp", "dump")}
        out["arms"] = [e["data"] for e in cw.log.events(kind="owner.arm")]
        out["fw"] = [(e["t_utc"], e["data"]["dom"], e["data"]["text"]) for e in cw.log.events(kind="fw.status")]
        out["overruns"] = cw.window_overruns()
        out["inv"] = cw.invariants()
        out["fw_inv"] = L.check_invariants(cw.log)
        out["digest"] = cw.log.digest()
        out["conflict"] = cw.fw.globals_view(["dump_start_tou_conflict_slot"])["dump_start_tou_conflict_slot"]
    finally:
        cw.close()
    return out


def first_status(obs, dom, prefix):
    return next((t for t, d, x in obs["fw"] if d == dom and x.startswith(prefix)), None)


def fw_dump(boot_utc, bank, start_at, minutes, *, windows=None, fw=None, run_to=None, start_again_at=None):
    """One FirmwareWorld Dump run: optional RTC lock windows, 60 s warm-up, the lab SITE Dump telemetry, a live advance to
    start_at, the real START button; returns observations."""
    w = L.FirmwareWorld(fw=fw, utc_start=boot_utc, bank=dict(bank))
    w.job_trace = []
    if windows:
        w.rtc_lock_windows(windows)
    w.run_for(60)
    w.telemetry(**DUMP_ENV)
    w.advance_to(start_at)
    n0 = len(w.writes())
    status = w.dump_start(power_w=1000, stop_soc=25, minutes=minutes)
    out = {"t_start": w.t_utc, "start_status": status, "start_writes": len(w.writes()) - n0,
           "conflict": w.globals_view(["dump_start_tou_conflict_slot"])["dump_start_tou_conflict_slot"],
           "end": w.obligations()["dump"]["end"] if status.startswith("ACTIVE") else None}
    if run_to is not None:
        w.advance_to(run_to)
    if start_again_at is not None:
        w.advance_to(start_again_at)
        n1 = len(w.writes())
        out["again"] = (w.t_utc, w.dump_start(power_w=1000, stop_soc=25, minutes=minutes), len(w.writes()) - n1)
    ev = list(w.log)
    out["statuses"] = [(e["t_utc"], e["data"]["dom"], e["data"]["text"]) for e in ev if e["kind"] == "fw.status"]
    out["restore_writes"] = [(e["t_utc"], e["data"]["addr"]) for e in ev if e["kind"] == "fw.write"
                             and any("restore" in s for s in e["data"]["scripts"])]
    out["final"] = {d: w.status(d) for d in ("dump", "dump_end")}
    out["bank"] = w.bank_view([244, 256])
    out["inv"] = w.invariants()
    out["wd_slots"] = [boot_utc - w.boot_ms / 1000 + up / 1000 for up, j in w.job_trace if j == "dump_wd"]
    out["digest"] = w.log.digest()
    return out


def dump_end_events(obs):
    return [(t, x) for t, d, x in obs["statuses"] if d in ("dump", "dump_end")]


def rig(kind, minutes=40, *, fault=None, pre_offset=-400, fp_phase_ms=0, text=None, run_s=None, lease=True):
    """One RtcWorld run: fault None | 'pre' (lost write callback on a correction 75 s before the change, inverter offset
    pre_offset) | 'dst' (the DST correction's own callback lost); outcomes bound AFTER the START so the START's writes are
    unaffected (write outcomes apply to every FC16 frame)."""
    w = R.dst_night_rig(kind, fp_lease=lease, fp_minutes=minutes, fp_phase_ms=fp_phase_ms, text=text)
    ch = w.change_utc
    try:
        w.advance_to(ch - 180)
        if fault is not None:
            w.set_outcomes(write=["timeout_lost", "ok"])
            if fault == "pre":
                w.rtc_offset(pre_offset)
        w.advance_to(ch + (run_s if run_s is not None else max(900, minutes * 60 - 600 + 120)))
        out = {"change": ch, "wins": w.lock_windows(), "corr": w.corrections(), "corr_after": w.corrections(after_change=True),
               "dec": w.decisions(), "leases": w.fp_leases(), "statuses": w.fp_statuses(), "inv": w.invariants(),
               "failed": w.sim.g["failed_corrections"], "status": w.fp_status(), "digest": w.log.digest(),
               "restore_writes": [(e["t_utc"], e["data"]["addr"]) for e in w.log.events(kind="mb.write")
                                  if str(e["data"]["issuer"]).startswith("restore_free_power_snapshot")],
               "bank": {a: w.sim.bank[a] for a in R.FP_OWNED}}
    finally:
        w.close()
    return out


def rig_fp_checks(o, minutes):
    ls = o["leases"][0] if o["leases"] else {}
    wins = [(a, b) for a, b in o["wins"] if b is not None]
    v = check_epoch_end("fp", ls.get("start_utc") or 0, minutes, ls.get("end_epoch"), ls.get("restore_start_utc"), wins,
                        slack_s=3)
    v += check_wd_skip("fp", ls.get("end_epoch"), o["statuses"], wins, until=ls.get("restored_utc"))
    v += check_no_restore_in_lock("fp", o["statuses"], o["restore_writes"], wins)
    return ls, v


def nc_report(nc_id, family, mutation, target, viol_fn):
    """Run a negative-control mutant; killed = the intended invariant id is in the violations. A harness exception is
    MUTANT-INVALID (a negative-control FAILURE)."""
    try:
        viol = viol_fn()
    except Exception as exc:  # noqa: BLE001 - a crashing mutant must FAIL loudly, never pass
        NC_RESULTS.append((nc_id, "invalid"))
        check(f"negative control {nc_id} ({family}): {mutation} -> {target} (MUTANT-INVALID)", False,
              f"{type(exc).__name__}: {exc}")
        return None
    killed = target in invs(viol)
    NC_RESULTS.append((nc_id, "killed" if killed else "survived"))
    check(f"negative control {nc_id} ({family}): {mutation} -> the intended {target} check fails (killed)", killed,
          str(viol[:3]))
    return viol


# =============================================================================================================================
# [0] contract
# =============================================================================================================================
def section_contract() -> None:
    print("\n[0] contract: scenario table, vocabulary, source anchors, constants")
    for sc in SCENARIOS:
        kind, rid = T.parse_classification(sc["classification"])
        check(f"{sc['id']}: classification {sc['classification']!r}, grade, confidence and priority are lab vocabulary",
              sc["grade"] in T.GRADES and sc["confidence"] in T.CONFIDENCES and sc["priority"] in T.PRIORITIES
              and (rid is None or rid in T.KNOWN_RISKS))
        for path, text in sc["anchors"]:
            n, line = T.anchor_count(path, text)
            check(f"{sc['id']}: anchor occurs exactly once: {path} {text[:56]!r}", n == 1, f"found {n} time(s)")
            if n == 1:
                info(f"anchor {sc['id']} {path}:{line}")
    check("SG-25 is a KNOWN_RISKS id and its public doc anchor is found exactly once",
          "SG-25" in T.KNOWN_RISKS and T.known_risk_status()["SG-25"]["count"] == 1)
    check("DUMP_ENV equals the lab SITE Dump environment (grid CT / battery power)",
          DUMP_ENV == {"grid_w": L.SITE["dump_grid_w"], "batt_w": L.SITE["dump_battery_w"]})
    check("RIG_START equals _lab_rtc.DEFAULT_START_LOCAL (the sc_dst starts) in UTC",
          RIG_START == {k: C.utc_of_local(*R.DEFAULT_START_LOCAL[k]) for k in R.KINDS})
    check("the synthetic TOU images: fall slot 2 01:00-01:30 Grid, spring slot 2 02:00-02:30 Grid, no-charge image",
          [x for x in slots_of(BANK_FALL) if x[2]] == [(60, 90, True)]
          and [x for x in slots_of(BANK_SPRING) if x[2]] == [(120, 150, True)]
          and not any(x[2] for x in slots_of({**{250 + i: v for i, v in enumerate((0, 400, 800, 1300, 1800, 2100))},
                                               **BANK_NOCHARGE})))
    check("_lab_clock fold / gap semantics used by the HA ASSUMPTION: 2026-10-25 01:30 -> 00:30Z (BST copy), "
          "2027-03-28 01:30 -> 01:30Z (02:30 BST); under fold=1 the gap time is 00:30Z (00:30 GMT), an hour from the typed "
          "time either way",
          C.utc_of_local(2026, 10, 25, 1, 30) == FALL - 1800 and C.local_kind(2026, 10, 25, 1, 30) == "ambiguous"
          and C.utc_of_local(2027, 3, 28, 1, 30) == SPRING + 1800 and C.local_kind(2027, 3, 28, 1, 30) == "gap"
          and C.utc_of_local(2027, 3, 28, 1, 30, fold=1) == SPRING - 1800)
    bad_reg = [f for sc in SCENARIOS for f in sc["findings"] if f not in FINDINGS_META or f in RECLASSIFIED]
    bad_reg += [f for f, m in FINDINGS_META.items() if T.parse_classification(m["classification"])[1] not in
                (None, *T.KNOWN_RISKS) or m["confidence"] not in T.CONFIDENCES]
    check("finding register: every scenario's finding id is registered with lab vocabulary, and no reclassified id "
          f"({sorted(RECLASSIFIED)}) is any scenario's finding", not bad_reg, str(bad_reg))
    info("ASSUMPTION: real Home Assistant input_datetime fold / gap handling is UNVERIFIED offline; the HA sim uses "
         "zoneinfo semantics through _lab_clock.LONDON")


# =============================================================================================================================
# [1] HF-08 coupled DST
# =============================================================================================================================
def section_hf08() -> None:
    print("\n[1] HF-08 FPS1 / DGS1 / firmware on the DST nights (CoupledWorld, london=True)")
    # A: FPS1 01:30 on 2026-10-25 (repeated hour), 60 min
    u0 = C.utc_of_local(2026, 10, 25, 0, 0)
    a = coupled(u0, [("fp", "2026-10-25 01:30:00", 60, 3000, None, 60)], FALL - 1800 + 3600 + 120, mid=FALL - 1800 + 120)
    st = first_status(a, "fp", "STARTING")
    rs = first_status(a, "fp", "RESTORING")
    check("HF-08 A: an armed 2026-10-25 01:30 start resolves to the first (BST) copy, 00:30Z (fold=0), and fires there",
          a["arms"][0]["start_utc"] == FALL - 1800 and st is not None and FALL - 1800 <= st < FALL - 1800 + 10,
          f"{a['arms']} STARTING at {r3(st)}")
    v = check_epoch_end("fp", st or 0, 60, a["mid"]["free_power_end_epoch"], rs)
    check("HF-08 A: INV-EPOCH-END - the lease end is the START second + 3600 s in UTC (01:30 GMT) and the restore starts "
          "at the first watchdog slot after it", not v, str(v))
    check("HF-08 A: the run completes (COMPLETED, RESTORED OK) with no coupled or firmware invariant violation",
          a["status"]["fp"] == "COMPLETED" and any(x.startswith(FP_STATUS_PREFIX) for _t, d, x in a["fw"] if d == "fp")
          and not a["inv"] and not a["fw_inv"], f"{a['status']} {a['inv']} {a['fw_inv'][:2]}")
    info(f"HF-08 A: FPS1 result {a['last']['fp']!r}; window overrun {a['overruns'][0]['overrun_s']} s; digest "
         f"{a['digest'][:16]}")
    # B: arming during the second 01:xx
    b = coupled(FALL + 300, [("fp", "2026-10-25 01:40:00", 20, 3000, None, 60)], FALL + 390)
    b2 = coupled(FALL + 300, [("fp", "2026-10-25 02:10:00", 20, 3000, None, 60)], FALL + 390)
    bd = coupled(FALL + 300, [("dump", "2026-10-25 01:40:00", 20, 3000, 20, 60)], FALL + 390, bank=BANK_NOCHARGE)
    u1 = C.utc_of_local(2026, 10, 18, 1, 5)
    bc = coupled(u1, [("fp", "2026-10-18 01:40:00", 20, 3000, None, 60)], u1 + 90)
    check("HF-08 B control: on a normal day an arm at 01:06 for 01:40 is ARMED",
          bc["last"]["fp"].startswith("ARMED - 2026-10-18 01:40:00") and bc["armed"]["fp"] == "on", bc["last"]["fp"])
    check("HF-08 B control: in the second 01:xx an arm for 02:10 (unambiguous) is ARMED for 02:10Z",
          b2["last"]["fp"].startswith("ARMED - 2026-10-25 02:10:00") and b2["arms"][0]["start_utc"] == FALL + 4200,
          b2["last"]["fp"])
    finding("F-HF08-1", "FINDING-NEW (FPS1, publicly undocumented; the DGS1 mirror is under the SG-25 operational "
            "restriction; availability / diagnostics, low): an input_datetime 01:xx on 2026-10-25 always means the BST copy "
            "(fold=0 ASSUMPTION), so a 01:xx meant as GMT and armed beforehand runs an hour early, armed at 01:06 GMT for "
            "01:40 it is refused 'scheduled start must be in the future', and 60 min from 01:30 BST reports 'ends by 01:30'")
    check("finding-reproduces:F-HF08-1", b["last"]["fp"] == "REJECTED - scheduled start must be in the future"
          and b["armed"]["fp"] == "off" and b["arms"][0]["start_utc"] == FALL - 1200
          and a["last"]["fp"] == "STARTED OK - 3000W for 60 min (attempt 1; ends by 01:30)", f"{b['last']} {a['last']}")
    check("finding-reproduces:F-HF08-1 (DGS1 has the same arm check: the second-copy 01:40 Dump arm is refused alike)",
          bd["last"]["dump"] == "REJECTED - scheduled start must be in the future" and bd["armed"]["dump"] == "off",
          str(bd["last"]))
    # C: a Free Power window spanning 01:00 UTC
    c = coupled(u0, [("fp", "2026-10-25 00:45:00", 120, 3000, None, 60)], FALL + 2700 + 120,
                mid=FALL - 600)
    stc, rsc = first_status(c, "fp", "STARTING"), first_status(c, "fp", "RESTORING")
    vc = check_epoch_end("fp", stc or 0, 120, c["mid"]["free_power_end_epoch"], rsc)
    check("HF-08 C: 00:45 BST + 120 min across 01:00 UTC: INV-EPOCH-END - 7200 s of real time, ending 01:45 GMT, "
          "restore at the first watchdog slot", not vc and c["arms"][0]["window_end"] == FALL + 2700, str(vc))
    check("HF-08 C: INV-HF-WINDOW and every coupled / firmware invariant hold across the change",
          not c["inv"] and not c["fw_inv"] and c["overruns"][0]["overrun_s"] <= 30, f"{c['overruns']} {c['inv']}")
    info(f"HF-08 C: FPS1 result {c['last']['fp']!r} (the bare HH:MM is the GMT wall time)")
    # D: spring-forward nonexistent 01:30
    u2 = C.utc_of_local(2027, 3, 28, 0, 0)
    d = coupled(u2, [("fp", "2027-03-28 01:30:00", 30, 3000, None, 60)], SPRING + 1800 + 1800 + 120, mid=SPRING + 1900)
    std = first_status(d, "fp", "STARTING")
    finding("F-HF08-2", "FINDING-NEW (FPS1, publicly undocumented; diagnostics / UX, low): the nonexistent 2027-03-28 01:30 "
            "is ARMED with no warning and runs one hour from the typed wall time (02:30 BST under the fold=0 gap "
            "ASSUMPTION; 00:30 GMT under fold=1); the ARMED text echoes '01:30', the STARTED text says 'ends by 03:00'")
    check("finding-reproduces:F-HF08-2", d["last"]["fp"] == "STARTED OK - 3000W for 30 min (attempt 1; ends by 03:00)"
          and d["arms"][0]["start_utc"] == SPRING + 1800 and std is not None and SPRING + 1800 <= std < SPRING + 1810,
          f"{d['last']} {d['arms']} {r3(std)}")
    vd = check_epoch_end("fp", std or 0, 30, d["mid"]["free_power_end_epoch"], first_status(d, "fp", "RESTORING"))
    check("HF-08 D: INV-EPOCH-END holds for the shifted run (30 min of real time from 01:30Z) and the run completes",
          not vd and d["status"]["fp"] == "COMPLETED" and not d["inv"], str(vd))
    # E / F: DGS1 arm walk + firmware gate with a synthetic charge slot near the change
    cases = (("fall", u0, "2026-10-25 01:35:00", FALL - 1500, 60, BANK_FALL),
             ("spring", u2, "2027-03-28 00:45:00", SPRING - 900, 60, BANK_SPRING))
    for night, uu, start, start_utc, mins, bank in cases:
        e = coupled(uu, [("dump", start, mins, 3000, 20, 240)], start_utc + mins * 60 + 120, bank=bank, plant=True,
                    mid=start_utc + 600)
        ste, end_r = first_status(e, "dump", "STARTING"), next((t for t, d_, x in e["fw"] if d_ == "dump_end"
                                                                and x == "DURATION EXPIRED"), None)
        ve = check_epoch_end("dump", ste or 0, mins, e["mid"]["dump_end_epoch"], end_r)
        check(f"HF-08 {night}: DGS1 arms {start} + {mins} min, fires at the fold=0 instant, the firmware gate admits it "
              f"(conflict 0) and the lease ends on its UTC epoch (INV-EPOCH-END)",
              e["last"]["dump"].startswith("STARTED OK") and e["mid"]["dump_start_tou_conflict_slot"] == 0 and not ve
              and ste is not None and start_utc <= ste < start_utc + 10, f"{e['last']['dump']} {ve}")
        real, walked = real_overlap_min(start_utc, mins, bank), walked_overlap_min(start_utc, mins, bank)
        info(f"HF-08 {night}: real local overlap with the charge slot {real} min, local-minute walk sees {walked} min; "
             f"result {e['last']['dump']!r}")
        viol = check_slot_clear(f"HF-08 {night}", start_utc, mins, bank)
        finding("F-HF08-3", "FINDING-KNOWN:SG-25: the firmware Dump START gate (and its DGS1 UX mirror) walk local "
                "minutes from the start's wall time; on both change nights they admit a Dump lease that really overlaps a "
                "grid-charge slot for 30 min, and on the fall night they refuse windows whose walked minutes lie outside "
                "the lease's real span (fail-closed); RT-03 shows the RTC-step variant (formerly F-RT03-1)")
        check(f"finding-reproduces:F-HF08-3 ({night})", invs(viol) == ["INV-DST-TOU-SLOT-CLEAR"] and real == 30
              and walked == 0, f"real {real} walked {walked} {viol}")
        check(f"HF-08 {night}: no coupled or firmware invariant violation besides the documented SG-25 overlap",
              not e["inv"] and not e["fw_inv"], f"{e['inv']} {e['fw_inv'][:2]}")
    # normal-day controls for the walk and the gate (INV-DST-TOU-REFUSE)
    for day, uu, start, bank in (("2026-10-18", C.utc_of_local(2026, 10, 18, 0, 0), "2026-10-18 00:50:00", BANK_FALL),
                                 ("2027-03-21", C.utc_of_local(2027, 3, 21, 0, 0), "2027-03-21 01:45:00", BANK_SPRING)):
        n = coupled(uu, [("dump", start, 60, 3000, 20, 240)], uu + 300, bank=bank)
        vn = check_tou_refuse(f"DGS1 {day}", n["last"]["dump"], DUMP_TOU_REFUSED_HA)
        check(f"HF-08 control {day}: DGS1 refuses {start[11:16]} + 60 min crossing the charge slot (INV-DST-TOU-REFUSE)",
              not vn, str(vn))
    # spurious refusal on the fall night: the walked minutes 02:00-02:30 lie outside the real span of 01:35 BST + 60 min (they
    # happen that night, but only after the lease has ended at 01:35 GMT)
    s = coupled(u0, [("dump", "2026-10-25 01:35:00", 60, 3000, 20, 240)], u0 + 300, bank=BANK_SPRING)
    check("HF-08 fall: with a 02:00-02:30 slot DGS1 refuses 01:35 BST + 60 min although the lease ends 01:35 GMT and never "
          "reaches local 02:00 (fail-closed spurious refusal, part of the documented SG-25 behaviour)",
          s["last"]["dump"].startswith(DUMP_TOU_REFUSED_HA) and real_overlap_min(FALL - 1500, 60, BANK_SPRING) == 0,
          s["last"]["dump"])
    # firmware gate alone (FirmwareWorld, London WallClock)
    for night, boot, start_at, bank in (("fall", FALL - 1560, FALL - 1500, BANK_FALL),
                                        ("spring", SPRING - 960, SPRING - 900, BANK_SPRING)):
        g = fw_dump(boot, bank, start_at, 60, run_to=start_at + 3600 + 30)
        ends = [(t, x) for t, x in dump_end_events(g) if x == "DURATION EXPIRED"]
        vg = check_epoch_end("dump", g["t_start"], 60, g["end"], ends[0][0] if ends else None)
        check(f"HF-08 firmware gate {night}: START at {C.iso_local(start_at)} + 60 min admitted (conflict 0); DURATION "
              f"EXPIRED on the UTC epoch; restore verified; firmware invariants hold",
              g["start_status"].startswith("ACTIVE") and g["conflict"] == 0 and not vg and g["final"]["dump"] == RESTORED
              and not g["inv"], f"{g['start_status'][:40]} {vg} {g['inv'][:2]}")
    for day, boot, bank in (("2026-10-18 00:50", C.utc_of_local(2026, 10, 18, 0, 49), BANK_FALL),
                            ("2027-03-21 01:45", C.utc_of_local(2027, 3, 21, 1, 44), BANK_SPRING)):
        g = fw_dump(boot, bank, boot + 60, 60)
        vg = check_tou_refuse(f"firmware {day}", g["start_status"], DUMP_TOU_REFUSED_FW)
        check(f"HF-08 firmware control {day} + 60 min: the gate refuses (slot 2) and writes nothing (INV-DST-TOU-REFUSE)",
              not vg and g["start_writes"] == 0 and g["conflict"] == 2, f"{g['start_status'][:60]} {vg}")
    gate_sweep(EXTENDED)
    if EXTENDED:
        dgs1_sweep()
    # negative controls of the HF-08 family
    mut_walk = mutate(H.package_text("dgs1"), [("{% if ns.hit == 0 and inside and ns.charges[i] != 'None' %}",
                                                "{% if ns.hit == 0 and inside and ns.charges[i] == 'Never' %}")])
    uu = C.utc_of_local(2026, 10, 18, 0, 0)
    nc_report("NC-HF08-1", "HF-08", "DGS1 walk charge test != 'None' -> == 'Never'", "INV-DST-TOU-REFUSE",
              lambda: check_tou_refuse("DGS1 mutant", coupled(uu, [("dump", "2026-10-18 00:50:00", 60, 3000, 20, 240)],
                                                              uu + 300, bank=BANK_FALL,
                                                              package_texts={"dgs1": mut_walk})["last"]["dump"],
                                       DUMP_TOU_REFUSED_HA))
    fw_gate = L.load_fw(mutate(FW_TEXT, [("if (in_slot && (flags[i] & 0x0003) != 0) conflict = i + 1;",
                                          "if (in_slot && (flags[i] & 0x0000) != 0) conflict = i + 1;")]))
    bb = C.utc_of_local(2026, 10, 18, 0, 49)
    nc_report("NC-HF08-2", "HF-08", "firmware gate charge mask 0x0003 -> 0x0000", "INV-DST-TOU-REFUSE",
              lambda: check_tou_refuse("firmware mutant", fw_dump(bb, BANK_FALL, bb + 60, 60, fw=fw_gate)["start_status"],
                                       DUMP_TOU_REFUSED_FW))
    fw_end = L.load_fw(mutate(FW_TEXT, [("uint32_t end_epoch = (uint32_t) now.timestamp + (minutes * 60U);",
                                         "uint32_t end_epoch = (uint32_t) now.timestamp + (minutes * 60U) + 600U;")]))

    def nc3():
        m = coupled(u0, [("fp", "2026-10-25 00:45:00", 120, 3000, None, 60)], FALL + 2700 + 900,
                    mid=FALL - 600, fw=fw_end)
        return check_epoch_end("fp", first_status(m, "fp", "STARTING") or 0, 120, m["mid"]["free_power_end_epoch"],
                               first_status(m, "fp", "RESTORING"))
    nc_report("NC-HF08-3", "HF-08", "Free Power end epoch + 600 s", "INV-EPOCH-END", nc3)


def gate_sweep(full: bool) -> None:
    """The firmware START gate (FirmwareWorld) against the real-local-time oracle across both nights and a normal day."""
    step = 15 if full else 30
    rows = {"fall": [], "spring": [], "normal": []}
    nights = (("fall", 2026, 10, 25, BANK_FALL), ("spring", 2027, 3, 28, BANK_SPRING), ("normal", 2026, 10, 18, BANK_FALL))
    for name, y, mo, dd, bank in nights:
        for mins in ((30, 60) if full else (60,)):
            for m0 in range(0, 180, step):
                if C.local_kind(y, mo, dd, m0 // 60, m0 % 60) == "gap":
                    continue
                start = C.utc_of_local(y, mo, dd, m0 // 60, m0 % 60)
                g = fw_dump(start - 60, bank, start, mins)
                admitted = g["start_status"].startswith("ACTIVE")
                refused_tou = g["start_status"].startswith(DUMP_TOU_REFUSED_FW)
                real = real_overlap_min(start, mins, bank)
                rows[name].append((m0, mins, admitted, refused_tou, real))
    bad_normal = [r for r in rows["normal"] if r[2] == (r[4] > 0) or not (r[2] or r[3])]
    check(f"gate sweep ({'15' if full else '30'}-min steps): on a normal day the gate decision equals the real-time "
          f"oracle at every start ({len(rows['normal'])} starts)", not bad_normal, str(bad_normal[:3]))
    for name in ("fall", "spring"):
        miss = [(f"{r[0] // 60:02d}:{r[0] % 60:02d}", r[1], r[4]) for r in rows[name] if r[2] and r[4] > 0]
        spurious = [(f"{r[0] // 60:02d}:{r[0] % 60:02d}", r[1]) for r in rows[name] if r[3] and r[4] == 0]
        info(f"gate sweep {name}: admitted with a real charge-slot overlap (SG-25 miss) {miss}; refused although no "
             f"real overlap (spurious) {spurious}; a 1-min overlap is an endpoint artefact of the inclusive k <= minutes "
             f"walk that the oracle mirrors")
        check(f"gate sweep {name}: the SG-25 deviation reproduces (at least one admitted lease really overlaps the slot) "
              f"and every decision is either the oracle's or a documented SG-25 miss / spurious refusal",
              bool(miss) and all(r[2] or r[3] for r in rows[name]), str(rows[name][:4]))


def dgs1_sweep() -> None:
    """EXTENDED: the DGS1 arm-time walk (arm only) at 15-min starts 00:00-02:45 on both nights, 30 and 60 min."""
    t0 = time.perf_counter()
    out = {}
    for name, y, mo, dd, bank in (("fall", 2026, 10, 25, BANK_FALL), ("spring", 2027, 3, 28, BANK_SPRING)):
        u = C.utc_of_local(y, mo, dd, 0, 0) - 3600
        rows = []
        for mins in (30, 60):
            for m0 in range(0, 180, 15):
                start = f"{y:04d}-{mo:02d}-{dd:02d} {m0 // 60:02d}:{m0 % 60:02d}:00"
                start_utc = C.utc_of_local(y, mo, dd, m0 // 60, m0 % 60)
                o = coupled(u, [("dump", start, mins, 3000, 20, 240)], u + 300, bank=bank)
                armed = o["last"]["dump"].startswith("ARMED")
                rows.append((start[11:16], mins, armed, real_overlap_min(start_utc, mins, bank)))
        out[name] = rows
        miss = [(r[0], r[1]) for r in rows if r[2] and r[3] > 0]
        info(f"DGS1 sweep {name}: ARMED with a real overlap (SG-25 miss) {miss}")
        check(f"DGS1 sweep {name}: the arm walk misses at least one real overlap (SG-25 reproduces in the HA layer)",
              bool(miss), str(rows[:4]))
    info(f"DGS1 sweep runtime {time.perf_counter() - t0:.1f} s")


# =============================================================================================================================
# [2] RT-01 Free Power lease across 01:00 UTC on the RTC rig
# =============================================================================================================================
def section_rt01() -> None:
    print("\n[2] RT-01 Free Power lease across 01:00 UTC (RtcWorld, real RTC lambdas + FP START / watchdog)")
    delays = {}
    for kind in R.KINDS:
        base = rig(kind, 40)
        ls, v = rig_fp_checks(base, 40)
        vc = check_dst_corrected(base["corr_after"], base["change"])
        check(f"RT-01 {kind} baseline: one verified large correction at +105.12 s (lock 12 s) while the lease is ACTIVE "
              f"(INV-RTC-DST-CORRECTED)", not vc and [r3(c["queued_utc"] - base["change"]) for c in base["corr_after"]]
              == [105.12] and base["corr_after"][0]["held_s"] == 12.0 and ls["active_utc"] < base["corr_after"][0][
                  "queued_utc"] < ls["end_epoch"], f"{vc} {base['corr_after']}")
        check(f"RT-01 {kind} baseline: INV-EPOCH-END / INV-RTC-WD-SKIP / INV-RTC-NO-RESTORE-IN-LOCK hold; RESTORED OK, "
              f"registers at the synthetic originals, FP-scope liveness invariants clean",
              not v and base["status"] == RESTORED and base["bank"] == {a: R.SYNTHETIC_ORIGINAL[a] for a in R.FP_OWNED}
              and all(not x for x in base["inv"].values()), f"{v} {base['status']}")
        delays[(kind, "baseline")] = r3(ls["restore_start_utc"] - ls["end_epoch"])
        pre = rig(kind, 40, fault="pre")
        ls2, v2 = rig_fp_checks(pre, 40)
        wins = [(r3(a - pre["change"]), r3(b - pre["change"])) for a, b in pre["wins"]]
        ab = [c for c in pre["corr"] if (c["result"] or "").startswith("ABORTED")]
        held = [d["reason"] for d in pre["dec"] if ab and ab[0]["released_utc"] < d["utc"] < pre["corr_after"][-1][
            "queued_utc"]]
        vc2 = check_dst_corrected(pre["corr_after"], pre["change"], ab[0]["released_utc"] if ab else None)
        check(f"RT-01 {kind} lost callback 75 s before the change: the pre-change large correction is ABORTED by the 90 s "
              f"breaker (lock -74.88..+16.0 s), every read until +285 s is held by 'cooldown', the DST correction comes at "
              f"+345.12 s verified (INV-RTC-DST-CORRECTED), failed_corrections 1",
              wins == [(-74.88, 16.0), (345.12, 357.12)] and len(ab) == 1 and set(held) == {"cooldown"} and not vc2
              and pre["failed"] == 1, f"{wins} {held} {vc2}")
        check(f"RT-01 {kind} lost callback: the lease stays ACTIVE across, ends on its UTC epoch, restores verified "
              f"(INV-EPOCH-END, INV-RTC-WD-SKIP, INV-RTC-NO-RESTORE-IN-LOCK)", not v2 and pre["status"] == RESTORED, str(v2))
        delays[(kind, "lost-pre")] = r3(ls2["restore_start_utc"] - ls2["end_epoch"])
        dst = rig(kind, 40, fault="dst")
        ls3, v3 = rig_fp_checks(dst, 40)
        wins3 = [(r3(a - dst["change"]), r3(b - dst["change"])) for a, b in dst["wins"]]
        vc3 = check_dst_corrected(dst["corr_after"], dst["change"], dst["change"] + 196.0)
        check(f"RT-01 {kind} the DST correction's own callback lost: lock +105.12..+196.0 s (breaker), cooldown, large "
              f"correction +525.12 s verified; the lease restores on its epoch",
              wins3 == [(105.12, 196.0), (525.12, 537.12)] and not vc3 and not v3 and dst["status"] == RESTORED
              and dst["failed"] == 1, f"{wins3} {vc3} {v3}")
        delays[(kind, "lost-dst")] = r3(ls3["restore_start_utc"] - ls3["end_epoch"])
        info(f"RT-01 {kind}: the inverter clock stays about 1 h off for {wins[1][1]} s (lost callback before) and "
             f"{wins3[1][1]} s (DST write lost) instead of 117.12 s - documented cooldown precedence "
             f"(ecco_rtc_policy.h 'cooldown after a failed correction')")
        for minutes, want in ((10, 15.0), (11, 0.0)):
            o = rig(kind, minutes, fault="pre")
            lsd, vd = rig_fp_checks(o, minutes)
            dly = r3(lsd["restore_start_utc"] - lsd["end_epoch"])
            delays[(kind, f"{minutes}min-pre")] = dly
            check(f"RT-01 {kind} {minutes}-min lease (end +{lsd['end_epoch'] - o['change']} s): restore delay {dly} s "
                  f"(= {want}); no lease-end action or restore inside a lock window; RESTORED OK",
                  not vd and dly == want and o["status"] == RESTORED, f"{vd} {dly}")
    info(f"RT-01 measured restore delays after the end epoch (s): {sorted(delays.items())}")
    if EXTENDED:
        t0 = time.perf_counter()
        bad = []
        for kind in R.KINDS:
            for ph in range(0, 15000, 1000):
                o = rig(kind, 10, fault="pre", fp_phase_ms=ph)
                _ls, vv = rig_fp_checks(o, 10)
                if vv or o["status"] != RESTORED:
                    bad.append((kind, ph, vv[:1]))
            for minutes in range(5, 65, 5):
                o = rig(kind, minutes, fault="pre")
                _ls, vv = rig_fp_checks(o, minutes)
                if vv or o["status"] != RESTORED:
                    bad.append((kind, minutes, vv[:1]))
        check("RT-01 EXTENDED: watchdog phase 0..14 s (10-min lease) and lease lengths 5..60 min with the lost callback on "
              "both nights: no restore inside a lock, every lease ends on its epoch and restores verified", not bad,
              str(bad[:3]))
        info(f"RT-01 extended sweep runtime {time.perf_counter() - t0:.1f} s")
    wd = (A_FP_WD_SKIP[1], "if (id(free_power_operation_in_progress) || id(manual_write_in_progress)) return false;")
    rg = ("!id(correction_in_progress) &&\n                // 2026-09-22 hardening (blocker 4): configuration_online",
          "// 2026-09-22 hardening (blocker 4): configuration_online")
    holder = {}

    def nc1():
        holder["o"] = o = rig("fall", 10, fault="pre", text=mutate(FW_TEXT, [wd]))
        return rig_fp_checks(o, 10)[1]
    viol = nc_report("NC-RT01-1", "RT-01", "FP watchdog lock skip removed", "INV-RTC-WD-SKIP", nc1)
    if viol is not None:
        check("NC-RT01-1 characterised: the restore script's own lock guard still defers ('END DEFERRED - RTC correction "
              "active') - INV-RTC-NO-RESTORE-IN-LOCK still holds (defence in depth)",
              invs(viol) == ["INV-RTC-WD-SKIP"] and any(x.startswith("END DEFERRED - RTC correction active")
                                                        for _t, x in holder["o"]["statuses"]), str(viol))
    nc_report("NC-RT01-2", "RT-01", "FP watchdog lock skip AND the restore's correction_in_progress gate removed",
              "INV-RTC-NO-RESTORE-IN-LOCK", lambda: rig_fp_checks(rig("fall", 10, fault="pre",
                                                                      text=mutate(FW_TEXT, [wd, rg])), 10)[1])


# =============================================================================================================================
# [3] RT-02 stopped inverter clock + outstanding restore obligation
# =============================================================================================================================
def stopped(variant: str, *, threshold=None, text=None, seconds=2400):
    kw = {"fp_lease": True, "fp_minutes": 240} if variant == "fp" else {}
    w = R.dst_night_rig("fall", start_utc=STOP_START, rate=-1.0, text=text, **kw)
    try:
        # per-instance: also time-stamp rtc_stall_detected (not a _lab_rtc publication kind, so the event log and its
        # digest are unchanged; read back below from sim.pub_times only)
        w.sim.pub_timed.add("rtc_stall_detected")
        if threshold is not None:
            w.sim.ent("correction_threshold").set(float(threshold))      # the HA number (owner input)
        if variant == "poke":
            w.poke("dump_restore_requested", True)                        # MODEL: a Dump restore that stays owed
        w.run_for(seconds)
        s = w.sim
        pubs = [(w.t_utc - (s.now_ms - t) / 1000, v) for t, n, v in s.pub_times if n == "rtc_stall_detected"]
        return {"corr": w.corrections(), "dec": w.decisions(), "failed": s.g["failed_corrections"],
                "stall": s.g["rtc_stall_count"], "inv": w.invariants(), "mism": [m for m in s.oracle_mismatches],
                "results": w.results(), "digest": w.log.digest(), "stall_pubs": pubs, "t_end": w.t_utc}
    finally:
        w.close()


def stall_timeline(o) -> dict:
    """The rtc_stall_detected step function after its first True publication: on fraction, longest off span, transitions."""
    pubs = o["stall_pubs"]
    if any(v not in ("True", "False") for _t, v in pubs):
        raise ValueError(f"rtc_stall_detected published a non-bool value: {sorted({v for _t, v in pubs})}")
    seq = [(t, v == "True") for t, v in pubs]
    first = next((i for i, (_t, on) in enumerate(seq) if on), None)
    if first is None:
        return {"first_utc": None, "on_frac": 0.0, "max_off_s": None, "flips": 0, "n_true": 0}
    seq = seq[first:]
    on_s, spans, off_from, flips = 0.0, [], None, 0
    for i, (t, on) in enumerate(seq):
        nxt = seq[i + 1][0] if i + 1 < len(seq) else o["t_end"]
        on_s += (nxt - t) if on else 0.0
        flips += bool(i and on != seq[i - 1][1])
        if not on and off_from is None:
            off_from = t
        if on and off_from is not None:
            spans.append(t - off_from)
            off_from = None
    if off_from is not None:
        spans.append(o["t_end"] - off_from)
    return {"first_utc": seq[0][0], "on_frac": round(on_s / (o["t_end"] - seq[0][0]), 3),
            "max_off_s": r3(max(spans, default=0.0)), "flips": flips, "n_true": sum(on for _t, on in seq)}


def check_stall_surfaced(o, max_off_s=150.0, min_on=0.5):
    """INV-RTC-STALL-SURFACED: the documented RTC hardware signal (RTC_STALL_DETECTED from rtc_stall_detected; rtc_stall_count
    for repeated occurrences) reports a stopped clock: at least one stall detection before the first correction and in every
    correction cycle after it, rtc_stall_count equal to the detections, rtc_stall_detected on for >= min_on of the run after
    its first detection and never off longer than max_off_s (two 60 s reads after a verified correction resets the baseline,
    plus 30 s)."""
    tl = stall_timeline(o)
    trues = [t for t, v in o["stall_pubs"] if v == "True"]
    edges = [STOP_START] + [c["queued_utc"] for c in o["corr"]] + [o["t_end"]]
    empty = [(r3(a - STOP_START), r3(b - STOP_START)) for a, b in zip(edges, edges[1:]) if not any(a <= t < b for t in trues)]
    out = [_v("INV-RTC-STALL-SURFACED", f"no stall detection in cycle {c}") for c in empty]
    if o["stall"] != len(trues):
        out.append(_v("INV-RTC-STALL-SURFACED", f"rtc_stall_count {o['stall']} != {len(trues)} detections"))
    if tl["on_frac"] < min_on:
        out.append(_v("INV-RTC-STALL-SURFACED", f"rtc_stall_detected on for {tl['on_frac']} of the run (< {min_on})"))
    if tl["max_off_s"] is not None and tl["max_off_s"] > max_off_s:
        out.append(_v("INV-RTC-STALL-SURFACED", f"rtc_stall_detected off for {tl['max_off_s']} s (> {max_off_s} s)"))
    return out


def section_rt02() -> None:
    print("\n[3] RT-02 stopped inverter clock (rate -1.0) with an outstanding restore obligation (40 min)")
    runs = {v: stopped(v) for v in ("poke", "fp", "none")}
    for v, o in runs.items():
        times = [r3(c["queued_utc"] - STOP_START) for c in o["corr"]]
        info(f"RT-02 {v}: corrections at {times} s; reasons {sorted({d['reason'] for d in o['dec']})}; failed "
             f"{o['failed']}; stall count {o['stall']}; stall timeline {stall_timeline(o)}; digest {o['digest'][:16]}")
        vd = check_drift_bound(o["dec"])
        check(f"RT-02 {v}: only 'large' corrections (5 in 40 min); INV-RTC-DRIFT-BOUND holds (max |error| "
              f"{max(abs(d['err_s']) for d in o['dec'])} s <= 600 s); liveness invariants clean",
              len(o["corr"]) == 5 and {c["reason"] for c in o["corr"]} == {"large"} and not vd
              and all(not x for x in o["inv"].values()), f"{vd} {o['corr'][:1]}")
    for v in ("poke", "fp"):
        vh = check_lease_hold(runs[v]["dec"], runs[v]["mism"])
        check(f"RT-02 {v}: INV-RTC-LEASE-HOLD - every over-threshold non-large read is held 'lease', the firmware decided "
              f"exactly as the mirror (no oracle mismatch)", not vh and "lease" in {d["reason"] for d in runs[v]["dec"]},
              str(vh[:2]))
    check("RT-02: the MODEL obligation (poked dump_restore_requested) and a genuine Free Power lease give the same RTC "
          "timeline (corrections and decisions)", runs["poke"]["corr"] == runs["fp"]["corr"]
          and runs["poke"]["dec"] == runs["fp"]["dec"])
    check("RT-02 control (no obligation): the same corrections; routine reads held by min-gap / confirmation instead of "
          "'lease' (the stopped image never confirms a routine error) - the obligation is not load-bearing",
          runs["none"]["corr"] == runs["poke"]["corr"] and "lease" not in {d["reason"] for d in runs["none"]["dec"]})
    vs = {v: check_stall_surfaced(o) for v, o in runs.items()}
    check("RT-02: INV-RTC-STALL-SURFACED holds in all three runs - the documented RTC hardware signal reports the stopped "
          "clock (a stall detection before the first correction and in every cycle, rtc_stall_count == detections, "
          "rtc_stall_detected on >= half the run, never off > 150 s)", not any(vs.values()), str(vs))
    o = runs["poke"]
    tl = stall_timeline(o)
    check("RT-02 documented behaviour (formerly F-RT02-1, reclassified PASS): a stopped clock meets the documented readback "
          "contract - every large correction reads back within the threshold ('Verified OK - error now -11 s' x5) and "
          "failed_corrections stays 0 (it counts retries, comms errors and the breaker, not clock hardware)",
          [c["result"] for c in o["corr"]] == ["Verified OK - error now -11 s"] * 5 and o["failed"] == 0
          and o["stall"] == 34 and all(c["verified"] for c in o["corr"]), f"{o['results']} {o['failed']} {o['stall']}")
    info(f"OBS-RT02-1 (diagnostics, undocumented, not a finding): after each verified correction rtc_stall_detected is "
         f"published false and the baseline resets, so the RTC_STALL_DETECTED WARNING drops out for up to "
         f"{tl['max_off_s']} s ({tl['flips']} transitions; on {tl['on_frac']} of the run after the first detection); "
         f"optional HA-only hold after an rtc_stall_count rise")
    p10 = stopped("poke", threshold=10)
    check("RT-02 sensitivity: with correction_threshold 10 (the minimum) the readback FAILS instead (failed_corrections 5), "
          "the clock stays bounded (INV-RTC-DRIFT-BOUND) and the stall signal still holds; every other permitted value "
          "(15..120) reads back within the threshold",
          p10["failed"] == 5 and all((c["result"] or "").startswith("FAILED after retries") for c in p10["corr"])
          and not check_drift_bound(p10["dec"]) and not check_stall_surfaced(p10),
          f"{p10['failed']} {[c['result'] for c in p10['corr']][:2]}")
    info(f"RT-02 threshold 10: max |error| {max(abs(d['err_s']) for d in p10['dec'])} s, RTC writes "
         f"{sum(len(c['writes']) for c in p10['corr'])} (threshold 20: {sum(len(c['writes']) for c in o['corr'])}) - "
         f"counting the readback as a failure does not shorten the drift")
    if EXTENDED:
        t0 = time.perf_counter()
        res = {p: stopped("poke", threshold=p)["failed"] for p in (10, 15, 20, 60, 120)}
        info(f"RT-02 EXTENDED threshold sweep failed_corrections {res} ({time.perf_counter() - t0:.1f} s)")
        check("RT-02 EXTENDED: failed_corrections is 0 for every permitted threshold 15..120 and 5 only at 10",
              res == {10: 5, 15: 0, 20: 0, 60: 0, 120: 0}, str(res))
    lease_mut = mutate(FW_TEXT, [("id(dump_restore_requested) || id(dump_operation_in_progress) ||\n"
                                  "                                    id(reg244_apply_in_progress);",
                                  "id(dump_operation_in_progress) ||\n"
                                  "                                    id(reg244_apply_in_progress);")])

    def nc1():
        m = stopped("poke", text=lease_mut)
        return check_lease_hold(m["dec"], m["mism"])
    nc_report("NC-RT02-1", "RT-02", "rp.lease_active without dump_restore_requested", "INV-RTC-LEASE-HOLD", nc1)
    cool_mut = mutate(FW_TEXT, [("rp.cooldown_active = cooldown_active;", "rp.cooldown_active = true;")])
    nc_report("NC-RT02-2", "RT-02", "policy input cooldown_active forced true", "INV-RTC-DRIFT-BOUND",
              lambda: check_drift_bound(stopped("poke", text=cool_mut)["dec"]))
    stall_mut = mutate(FW_TEXT, [(A_STALL[1], "bool stalled = false;")])
    holder = {}

    def nc3():
        holder["o"] = m = stopped("poke", text=stall_mut)
        return check_stall_surfaced(m)
    viol = nc_report("NC-RT02-3", "RT-02", "stall detector 'bool stalled = ...' forced false", "INV-RTC-STALL-SURFACED", nc3)
    if viol is not None:
        check("NC-RT02-3 characterised: the mutant changes only the stall signal (the same 5 verified large corrections, "
              "rtc_stall_count 0)", holder["o"]["corr"] == o["corr"] and holder["o"]["stall"] == 0,
              f"{holder['o']['stall']} {len(holder['o']['corr'])}")


# =============================================================================================================================
# [4] RT-03 split model: rig lock windows -> FirmwareWorld Dump lease
# =============================================================================================================================
TOU_FALL = tuple(BANK_FALL[250 + i] for i in range(6))        # the rig's RTC TOU cache = the FirmwareWorld slot bank
TOU_SPRING = tuple(BANK_SPRING[250 + i] for i in range(6))


def night_rig(kind: str, variant: str = "none", *, lease=None, sec: int = 15, tou=None, until_s: int = 2800):
    """Lock windows and inverter offsets of a DST-night rig (no FP lease) started at 00:20:<sec>Z (sec 15 = the sc_dst 60 s
    read phase). variant 'pre': lost write callback + inverter offset -400 s at change - 180 s. lease = (utc_a, utc_b):
    dump_active_persisted poked true over it so the rig's policy sees the Dump lease the FirmwareWorld will hold (MODEL
    consistency). tou: the rig's RTC TOU cache (default: the synthetic slot bank of that night)."""
    ch = FALL if kind == "fall" else SPRING
    local = (2026, 10, 25, 1, 20, sec) if kind == "fall" else (2027, 3, 28, 0, 20, sec)
    tou = (TOU_FALL if kind == "fall" else TOU_SPRING) if tou is None else tou
    w = R.dst_night_rig(kind, local, tou=tou)
    try:
        if lease is not None:
            w.advance_to(lease[0])
            w.poke("dump_active_persisted", True)
        w.advance_to(ch - 180)
        if variant == "pre":
            w.set_outcomes(write=["timeout_lost", "ok"])
            w.rtc_offset(-400)
        if lease is not None:
            w.advance_to(lease[1])
            w.poke("dump_active_persisted", False)
        w.advance_to(ch + until_s)
        s = w.sim
        offs = {u: s.rtc.offset_s(s.now_ms - int(round((w.t_utc - u) * 1000))) for u in range(ch - 1800, ch + until_s + 1)}
        return [[r3(a), r3(b)] for a, b in w.lock_windows()], offs, w.invariants()
    finally:
        w.close()


def inverter_slot_seconds(start_utc, end_utc, offs, bank) -> int:
    """Seconds of [start, end) during which the INVERTER's own clock (NTP London local + the rig's InverterRtc offset)
    lies in a charge slot (computed, grade INFERRED; the inverter's TOU execution is not modelled)."""
    n = 0
    for u in range(int(start_utc), int(end_utc)):
        y, mo, d, h, mi, s, _dst = C.local_fields(u)
        sod = int(math.floor(h * 3600 + mi * 60 + s + offs[u])) % 86400
        n += in_charge_slot(sod // 60, bank)
    return n


RT03_NIGHTS = {"fall": (FALL - 1560, FALL - 1500, BANK_FALL), "spring": (SPRING - 960, SPRING - 900, BANK_SPRING)}


def phase_rows(secs) -> list:
    """(night, rig start second, DST lock start after the change, inverter in-slot s, real overlap s - ceil(lock start))."""
    rows = []
    for night, (_boot, start, bank) in RT03_NIGHTS.items():
        ch = FALL if night == "fall" else SPRING
        for sec in secs:
            wins, offs, _inv = night_rig(night, sec=sec)
            lag = wins[0][0] - ch
            rows.append((night, sec, r3(lag), inverter_slot_seconds(start, start + 3600, offs, bank),
                         60 * real_overlap_min(start, 60, bank) - math.ceil(lag)))
    return rows


def section_rt03() -> None:
    print("\n[4] RT-03 split model (MODEL ASSUMPTION): DST-night RTC lock windows replayed into a FirmwareWorld Dump lease")
    w_dst, offs_dst, inv1 = night_rig("fall")
    w_pre, offs_pre, inv2 = night_rig("fall", "pre")
    w_dst_l, _o, _i = night_rig("fall", lease=(FALL - 1500, FALL + 2100))
    w_pre_l, _o2, _i2 = night_rig("fall", "pre", lease=(FALL - 1800, FALL - 8))
    w_gold, _o3, _i3 = night_rig("fall", tou=X.GOLD_TOU)
    check("RT-03 windows: the fall rig gives the DST lock [+105.12, +117.12) and, with the lost callback, [-74.88, +16.0) "
          "and [+345.12, +357.12) - the constants the corpus uses", w_dst == [WIN_DST_FALL] and w_pre == WIN_PRE_FALL
          and all(not x for x in inv1.values()) and all(not x for x in inv2.values()), f"{w_dst} {w_pre}")
    check("RT-03 MODEL consistency: with the rig's lease input set over the Dump lease interval, and with the rig's RTC TOU "
          "cache = GOLD_TOU instead of the synthetic slot bank, the windows are identical (only large corrections are "
          "involved, a lease never holds those, and the synthetic slot starts are half-hour aligned)",
          w_dst_l == w_dst and w_pre_l == w_pre and w_gold == w_dst, f"{w_dst_l} {w_pre_l} {w_gold}")
    wins_pre = [tuple(x) for x in WIN_PRE_FALL]
    a = fw_dump(RT03A_BOOT, BANK_NOCHARGE, FALL - 1808, 30, windows=WIN_PRE_FALL, run_to=FALL + 350 - 1,
                start_again_at=FALL + 350)
    ends = dump_end_events(a)
    end_t = next((t for t, x in ends if x == "DURATION EXPIRED"), None)
    slot = [t for t in a["wd_slots"] if t >= a["end"]] if a["end"] else []
    v = check_epoch_end("dump", a["t_start"], 30, a["end"], end_t, wins_pre)
    done = next((t for t, x in ends if x == RESTORED and a["end"] is not None and t >= a["end"]), None)
    v += check_wd_skip("dump", a["end"], ends, wins_pre, until=done)
    v += check_no_restore_in_lock("dump", [(t, x) for t, d, x in a["statuses"] if d == "dump"], a["restore_writes"],
                                  wins_pre)
    check("RT-03 a: a Dump lease ending at -8 s inside the lock [-74.88, +16.0) is not ended inside it: the first Dump "
          "watchdog slot after the release (+25 s) ends it (DURATION EXPIRED) and restores verified "
          "(INV-EPOCH-END, INV-RTC-WD-SKIP, INV-RTC-NO-RESTORE-IN-LOCK)",
          not v and a["end"] == FALL - 8 and slot[:3] == [FALL - 5, FALL + 10, FALL + 25] and end_t == FALL + 25,
          f"{v} end {a['end']} slots {[r3(x - FALL) for x in slot[:3]]} {r3((end_t or 0) - FALL)}")
    info(f"RT-03 a: Dump end deferred {r3((end_t or 0) - (a['end'] or 0))} s past its end epoch by the RTC lock")
    vs = check_start_lock("dump", a["again"][0], a["again"][1], a["again"][2], wins_pre)
    check("RT-03 a: a Dump START at +350 s inside the DST correction lock is refused with the firmware's text and writes "
          "nothing (INV-RTC-START-LOCK); firmware invariants hold", not vs and not a["inv"], f"{vs} {a['inv'][:2]}")
    # b: SG-25 compound with the RTC step mid-lease (both nights): the RTC-step variant of F-HF08-3
    w_spr, offs_spr, inv3 = night_rig("spring")
    for night, wins, offs in (("fall", [WIN_DST_FALL], offs_dst), ("spring", w_spr, offs_spr)):
        boot, start, bank = RT03_NIGHTS[night]
        ch = FALL if night == "fall" else SPRING
        b = fw_dump(boot, bank, start, 60, windows=wins, run_to=start + 3600 + 30)
        end_t = next((t for t, x in dump_end_events(b) if x == "DURATION EXPIRED"), None)
        vb = check_epoch_end("dump", b["t_start"], 60, b["end"], end_t, [tuple(x) for x in wins])
        check(f"RT-03 b {night}: Dump {C.iso_local(start)} + 60 min admitted (conflict 0) with the rig's DST lock window "
              f"{[[r3(x - ch) for x in w] for w in wins]} inside the lease; DURATION EXPIRED on the epoch; RESTORED OK; "
              f"invariants hold", b["start_status"].startswith("ACTIVE") and b["conflict"] == 0 and not vb
              and b["final"]["dump"] == RESTORED and not b["inv"] and all(not x for x in inv3.values()),
              f"{b['start_status'][:40]} {vb}")
        inv_s = inverter_slot_seconds(start, start + 3600, offs, bank)
        real = real_overlap_min(start, 60, bank)
        lag = wins[0][0] - ch
        info(f"RT-03 b {night} (variant of F-HF08-3): real local overlap {real} min; the inverter's own clock (rig offsets, "
             f"read phase 15 s) inside the charge slot for {inv_s} s (computed, INFERRED) = {60 * real} s minus the "
             f"correction lag {r3(lag)} s rounded up")
        check(f"finding-reproduces:F-HF08-3 (RT-03 compound, {night}): the gate admits a lease with a 30 min real "
              f"charge-slot overlap; once the DST correction lands the inverter clock is in the slot for the rest of it "
              f"(1694 s at this read phase)", real == 30 and inv_s == 1694 and inv_s == 60 * real - math.ceil(lag)
              and check_slot_clear(night, start, 60, bank) != [], f"real {real} inverter {inv_s} lag {lag}")
    inv_pre = inverter_slot_seconds(FALL - 1500, FALL + 2100, offs_pre, BANK_FALL)
    info(f"RT-03 b fall with the lost callback before the change: inverter clock inside the charge slot for {inv_pre} s "
         f"(the cooldown delays the correction to +345.12 s)")
    check("finding-reproduces:F-HF08-3 (RT-03 compound, fall, lost callback: the delayed correction shortens the inverter "
          "clock's in-slot time to 1800 s - 346 s)", inv_pre == 1454, str(inv_pre))
    t0 = time.perf_counter()
    rows = phase_rows(range(0, 60, 5) if EXTENDED else (25, 30))
    if EXTENDED:
        info(f"RT-03 read-phase sweep runtime {time.perf_counter() - t0:.1f} s")
    bad = [r for r in rows if not (60 < r[2] <= 120 and r[3] == r[4] and r[3] <= 1800)]
    span = (min(r[3] for r in rows), max(r[3] for r in rows))
    info(f"RT-03 read-phase sensitivity ({'EXTENDED, 5 s steps' if EXTENDED else 'quick: the two extreme phases'}): "
         f"(night, start s, lock start s, in-slot s) {[(r[0], r[1], r[2], r[3]) for r in rows]}; in-slot range {span} s")
    check("RT-03 read-phase sensitivity: for every rig read phase tried, the DST correction's lock starts +60..+120 s after "
          "the change (the half-hour quiet window) and the inverter clock's in-slot time equals the 30 min real overlap "
          "minus that lag (a subset of F-HF08-3's real overlap; 1684..1739 s over all phases)", not bad, str(bad[:3]))
    # negative controls of the RT-03 family
    wd = (A_DUMP_WD_SKIP[1], "if (id(dump_operation_in_progress) || id(manual_write_in_progress)) return false;")
    rg = ("!id(correction_in_progress) &&\n                // Comms backoff pacing (15s/30s/60s/120s/300s) between",
          "// Comms backoff pacing (15s/30s/60s/120s/300s) between")
    st = ("!id(correction_in_progress) &&\n                // Free Power owns 256-261 during its own lease and reads",
          "// Free Power owns 256-261 during its own lease and reads")

    def run_a(pairs):
        return fw_dump(RT03A_BOOT, BANK_NOCHARGE, FALL - 1808, 30, windows=WIN_PRE_FALL, run_to=FALL + 120,
                       fw=L.load_fw(mutate(FW_TEXT, pairs)))
    holder = {}

    def nc1():
        holder["o"] = o = run_a([wd])
        return check_wd_skip("dump", o["end"], dump_end_events(o), wins_pre) + check_no_restore_in_lock(
            "dump", [(t, x) for t, d, x in o["statuses"] if d == "dump"], o["restore_writes"], wins_pre)
    viol = nc_report("NC-RT03-1", "RT-03", "Dump watchdog lock skip removed", "INV-RTC-WD-SKIP", nc1)
    if viol is not None:
        check("NC-RT03-1 characterised: request_dump_end's own lock guard still defers the restore ('END DEFERRED - RTC "
              "correction active') - INV-RTC-NO-RESTORE-IN-LOCK still holds (defence in depth)",
              invs(viol) == ["INV-RTC-WD-SKIP"] and any(x.startswith("END DEFERRED - RTC correction active")
                                                        for _t, _d, x in holder["o"]["statuses"]), str(viol))

    def nc2():
        o = run_a([wd, rg])
        return check_no_restore_in_lock("dump", [(t, x) for t, d, x in o["statuses"] if d == "dump"], o["restore_writes"],
                                        wins_pre)
    nc_report("NC-RT03-2", "RT-03", "Dump watchdog lock skip AND the restore's correction_in_progress gate removed",
              "INV-RTC-NO-RESTORE-IN-LOCK", nc2)

    def nc3():
        o = fw_dump(FALL - 150, BANK_NOCHARGE, FALL - 60, 30, windows=WIN_PRE_FALL, fw=L.load_fw(mutate(FW_TEXT, [st])))
        return check_start_lock("dump", o["t_start"], o["start_status"], o["start_writes"], wins_pre)
    nc_report("NC-RT03-3", "RT-03", "Dump START gate without !correction_in_progress", "INV-RTC-START-LOCK", nc3)


# =============================================================================================================================
# [5] corpus: every file of this suite's scenarios equals its draft and replays
# =============================================================================================================================
def _strip(doc):
    d = copy.deepcopy(doc)
    d.pop("trace_digest", None)
    d["source_digests"] = sorted(d["source_digests"])
    for a in d["source_anchors"]:
        a.pop("line_at_record", None)
    return d


def section_corpus() -> None:
    print("\n[5] replay corpus (recorded with _lab_trace.record from the drafts above; replayed here)")
    for draft in CORPUS_DRAFTS:
        path = CORPUS_DIR / f"{draft['id']}.json"
        check(f"corpus file {draft['id']}.json exists", path.is_file(), str(path.name))
        if not path.is_file():
            continue
        doc = T.load_doc(path)
        want = _strip(draft)
        want["source_digests"] = sorted({a["path"] for a in draft["source_anchors"]} | set(T.tier_pins(draft["tier"])))
        check(f"{draft['id']}: the corpus file is exactly this suite's draft (actions, expectations, metadata)",
              _strip(doc) == want, "regenerate the corpus file from the draft")
        r = T.replay(doc)
        if r.drift:
            info(f"{draft['id']}: SOURCE DRIFT {r.drifted_paths} - expectations only (spec drift rule)")
        check(f"{draft['id']}: replay ok ({'expectations only, source drift' if r.drift else 'digest equal'}), "
              f"{len(doc['expect'])} expectation(s) hold", r.ok and not r.failed_expectations,
              f"{r.failed_expectations} digest_mismatch={r.digest_mismatch} anchors={r.anchor_problems}")
    neg = CORPUS_DIR / "HF-08-d.json"
    check("corpus negative-control file HF-08-d.json exists", neg.is_file())
    if not neg.is_file():
        return
    bad = copy.deepcopy(T.load_doc(neg))
    bad["expect"][0]["value"] = {"dump_end_epoch": 0, "dump_start_tou_conflict_slot": 0}
    r = T.replay(bad)
    check("corpus negative control: an altered expectation makes the replay FAIL", not r.ok and len(r.failed_expectations)
          == 1, str(r.failed_expectations))


def section_register() -> None:
    print("\n[6] finding register (after the independent review)")
    check("every printed FINDING is a registered finding and every registered finding was reproduced; no reclassified id "
          "printed a FINDING line", sorted(FINDINGS) == sorted(FINDINGS_META) and not set(FINDINGS) & set(RECLASSIFIED),
          f"{sorted(FINDINGS)}")
    for fid, why in sorted(RECLASSIFIED.items()):
        info(f"reclassified after review: {fid} -> {why}")


# =============================================================================================================================
# run
# =============================================================================================================================
section_contract()
section_hf08()
section_rt01()
section_rt02()
section_rt03()
section_corpus()
section_register()

BLOCKED = [s["id"] for s in SCENARIOS if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME_S = time.perf_counter() - T_START
print("")
print("  info  negative controls: " + ", ".join(f"{i} {r}" for i, r in NC_RESULTS))
print("  info  scenarios: " + "; ".join(f"{s['id']} {s['classification']}" for s in SCENARIOS))
print(f"  info  runtime {RUNTIME_S:.1f} s ({'EXTENDED' if EXTENDED else 'quick'})")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=FINDINGS, finding_pins=PINS, unsupported_points=UNSUPPORTED_POINTS,
         blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
