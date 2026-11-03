#!/usr/bin/env python3
"""FW-07 / FW-08 firmware runtime scenarios on the real firmware (FirmwareWorld): a Modbus link loss coupled with telemetry
and configuration staleness during an ACTIVE Dump to Grid lease and during its restore (lease end reasons, a single failed
configuration read, the comms backoff 15/30/60/120/300 s, the SG-39 link-recovery retry and its Free Power analogue),
reboots at realistic early uptime (the 90 s no-fresh-SOC supervision, the 300 s NTP-invalid grace, the persisted owed
Stop SOC dump_owed_stop_soc_rec, the first end reason across a reboot) and transaction-lock contention (a single-op Modbus
outcome sweep for lock leaks, a leaked manual_write_in_progress at lease end, the > 180 s stuck-lock escalation, the
firmware restart, the boot-path restore and its S3 / Dump no-resume interplay, RTC lock windows deferring restores) and
frozen telemetry with the link UP (a grid CT, battery power or SOC reading that keeps arriving but never changes: the SG-15 /
SG-43 frozen-telemetry ends crossed with the restore, a power cut at a restore write and a reboot after a completed restore).
Offline assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing).

Scenarios (SCENARIOS below): FW-07-A..I (P2/P3 link, staleness, frozen telemetry and reboot) and FW-08-A..F (P3 lock
contention). Findings: F-FW07-1 (Free Power has no SG-39 retry), F-FW07-2 (the boot misattributes an already-ended lease's
end to the restart), F-FW07-3 (FINDING-KNOWN:FCP2-R1), F-FW07-4 (one failed configuration read ends a Dump lease; explicit
fail-closed term, intent not stated in the public docs), F-FW07-5 (the frozen-CT battery range is not re-seeded at START: a
CT already repeating at START meets the fast criterion on battery values from outside the repeat window; fail closed,
diagnostics), F-FW08-1 (FINDING-KNOWN:FCP2-F6 restart loop). Each classification, severity and repair scope is stated
against the cited source anchors and the lab vocabulary; the refinements are in the SCENARIOS notes below.

Everything the firmware decides comes from its own lambdas and action trees through _lab_fw (never re-implemented here).
The lab supplies the environment: the synthetic site, the coupled link model (reads no_response, writes timeout_lost, the
real polls failing through their real handlers), per-op Modbus outcomes, RTC lock windows (MODEL) and, for FW-08-B..F, a
white-box RAM lock leak through FirmwareWorld.inject_global (logged as fault.ram; MODEL: no firmware path that leaks a
lock during a lease is known; the FW-08-A sweep finds the one documented leak, which cannot overlap a lease). The owner's
lower configured Stop SOC in FW-07-D is the logged world action owner_set_number (act.set_number). A reproduced deviation
is printed as '  FINDING  <id> ...' and pinned by a 'finding-reproduces:<id>' check (not counted as a pass), so a firmware
fix fails loudly and forces re-classification. A finding that duplicates another suite's root cause would be printed
'DUPLICATE of <owner id>, not counted' (DUPLICATE_OF) and left out of the LAB-SUMMARY finding count; none does today.

FW-07-I needs per-signal control of the meter-noise MODEL, which FirmwareWorld offers only as one world switch: its worlds run
with noise=False and set every 10 s poll slot's grid CT and battery power explicitly (the replay action telemetry with
poll False, 5 s before each slot; [8a] checks the alignment), so one signal repeats exactly while the other keeps moving;
the SOC case keeps the noise MODEL on (the lab has no SOC physics: the SOC changes only when a scenario sets it).

Corpus: FW-07-a..i, FW-07-i2, FW-07-i3 and FW-08-a..f (CORPUS_DRAFTS). FW-07-d lowers the configured Stop SOC with the replay
action set_number; FW-08-c..f replay the lock leaks of FW-08-B, -C, -D and -F with the replay action inject_global;
FW-07-i / -i3 replay the explicit telemetry schedule of FW-07-I (world noise false) and FW-07-i / -i2 a power cut at a
restore write (arm_power_cut). Section [16] replays each document and also replays FW-07-d, FW-07-i, FW-07-i2, FW-07-i3
and FW-08-c..e against in-memory mutants of the guard they pin (each document's expectations must FAIL there).

Quick mode (about 20 s here) runs every scenario once, the lock-leak sweep over Dump START / END, Free Power START / END
and manual TOU slot 2, all negative controls and the corpus replays. ECCO_LAB_EXTENDED=1 / --extended (about 35 s) adds the
link-loss onset and outage sweeps, the leak-offset and watchdog-order sweeps, the Free Power outage sweep, the FW-07-I
frozen-telemetry onset x power-cut point sweep and the lock-leak sweep over all six manual slots, and prints the extended
sweeps' runtime.
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
    "FW-07-A: the recovery restore is the SG-39 path": (
        "which runs first after the link recovery - the first ok telemetry poll (10 s interval) or the Dump "
        "watchdog's restore pre-read (15 s interval) - is the two intervals' relative phase; on the lab grid the "
        "poll wins, under ESPHome-like offsets the watchdog usually runs first (fails under the phase patch)"),
    "NC-FW07-1 (FW-07) mutant killed": (
        "the kill is FW-07-A's rebased INV-RESTORE-BOUND: when the watchdog's pre-read precedes the first fresh "
        "telemetry poll the every-tick supervision restores within the bound without the SG-39 clause, so the mutant "
        "survives at other phases (fails under the phase patch)"),
    "every scenario family has at least one killed negative control and no mutant survived": (
        "aggregate of this suite's negative controls: fails whenever a phase-sensitive control (NC-FW07-1) survives"),
    "FW-07-E dump: the lease STARTed with a valid clock": (
        "pins the boot-path restore to the first Dump watchdog tick at uptime WD_FIRST_S (the 15 s startup_delay "
        "with zero offset, while now() is still invalid); ESPHome's first tick comes at setup + 15 s + [0, 5 s) "
        "(fails under the phase patch)"),
    "FW-07-E fp: the lease STARTed with a valid clock": (
        "pins the boot-path restore to the first Free Power watchdog tick at uptime WD_FIRST_S (the 15 s "
        "startup_delay with zero offset); ESPHome's first tick comes at setup + 15 s + [0, 5 s) (fails under the "
        "phase patch)"),
    "FW-07-I: every explicit telemetry action lies strictly between two poll slots": (
        "audit-named (FW-07-I): places the explicit telemetry actions on the lab's 10 s poll grid; the grid is the "
        "phase (held under the phase patch in every run: the check reads the slots from the trace)"),
    "FW-07-I ct INV-17:": (
        "audit-named (FW-07-I): the frozen-CT end must come 40-65 s (CT_WIN, the 10 s poll / 15 s watchdog grid) "
        "after the first frozen read (held under the phase patch in every run)"),
    "FW-07-I bp INV-17:": (
        "audit-named (FW-07-I): the frozen battery-power end must come 40-65 s (CT_WIN) after the first frozen read "
        "(held under the phase patch in every run)"),
    "FW-07-I soc INV-17:": (
        "audit-named (FW-07-I): the frozen-SOC end must come inside SOC_WIN after START (the poll / watchdog grid) "
        "(held under the phase patch in every run)"),
    "FW-07-I ct: the power cut fired at the Dump restore's write": (
        "audit-named (FW-07-I): the cut must land in the watchdog tick of the frozen end (held under the phase patch "
        "in every run)"),
    "FW-07-I bp: the power cut fired at the Dump restore's write": (
        "audit-named (FW-07-I): the cut must land in the watchdog tick of the frozen end (held under the phase patch "
        "in every run)"),
    "FW-07-I soc: the power cut fired at the Dump restore's write": (
        "audit-named (FW-07-I): the cut must land in the watchdog tick of the frozen end (held under the phase patch "
        "in every run)"),
    "FW-07-I ct INV-RESTORE-BOUND rebased at the boot": (
        "the boot-path restore must complete within WD_FIRST_S = 15 s of the boot: the first Dump watchdog tick "
        "lands at exactly 15 s only with zero offset (ESPHome: setup + 15 s + [0, 5 s)) (fails under the phase patch)"),
    "FW-07-I bp INV-RESTORE-BOUND rebased at the boot": (
        "the boot-path restore must complete within WD_FIRST_S = 15 s of the boot (first watchdog tick at exactly 15 "
        "s only with zero offset) (fails under the phase patch)"),
    "FW-07-I soc INV-RESTORE-BOUND rebased at the boot": (
        "the boot-path restore must complete within WD_FIRST_S = 15 s of the boot (first watchdog tick at exactly 15 "
        "s only with zero offset) (fails under the phase patch)"),
    "FW-07-I soc: corpus FW-07-i2's last action (at_s I_SOC_END_AT) comes after the boot-path restore": (
        "audit-named (FW-07-I): the corpus document's fixed last-action instant must follow a restore whose instant "
        "is the watchdog phase (held under the phase patch in every run)"),
    "FW-07-I after: the frozen end's restore completes in the same watchdog tick": (
        "audit-named (FW-07-I): same-tick completion on the lab's watchdog grid (held under the phase patch in every "
        "run)"),
    "FW-07-I after: the owner's new START on the still-frozen CT is accepted": (
        "FW-07-I window bound: 'GRID CT FROZEN' 70-105 s after START on the poll / watchdog grid (held under the "
        "phase patch in every run)"),
    "F-FW07-5 control (the documented criteria hold when the range is seeded inside the lease)": (
        "counts identical CT reads (FROZEN_LONG_N) between explicit telemetry actions and the watchdog's end: the "
        "count is the telemetry / watchdog phase (fails under the phase patch at some seeds)"),
    "FW-08-B INV-20:": (
        "audit-named (FW-08-B): restart within STUCK_S + 2 * CENSUS_S of the leak (5 s census grid) and the "
        "boot-path restore at the first watchdog tick (fails under the phase patch at some seeds)"),
    "FW-08-C INV-20:": (
        "audit-named (FW-08-C): restart and boot restore within the escalation bound STUCK_S + 2 * CENSUS_S + "
        "RESTART_DOWN_S + WD_FIRST_S + 1 (census / watchdog grid) (fails under the phase patch at some seeds)"),
    "FW-08-D INV-20:": (
        "the FP analogue of FW-08-B: the same escalation bound on the census / watchdog grid (fails under the phase "
        "patch at some seeds)"),
    "corpus FW-07-a (": _PS_DIGEST,
    "corpus FW-07-b (": _PS_DIGEST,
    "corpus FW-07-c (": _PS_DIGEST,
    "corpus FW-07-d (": _PS_DIGEST,
    "corpus FW-07-e (": _PS_DIGEST,
    "corpus FW-07-f (": _PS_DIGEST,
    "corpus FW-07-g (": _PS_DIGEST,
    "corpus FW-07-h (": _PS_DIGEST,
    "corpus FW-07-i (": _PS_DIGEST_EXP,
    "corpus FW-07-i2 (": _PS_DIGEST_EXP,
    "corpus FW-07-i3 (": _PS_DIGEST_EXP,
    "corpus FW-08-a (": _PS_DIGEST,
    "corpus FW-08-b (": _PS_DIGEST,
    "corpus FW-08-c (": _PS_DIGEST_EXP,
    "corpus FW-08-d (": _PS_DIGEST_EXP,
    "corpus FW-08-e (": _PS_DIGEST_EXP,
    "corpus FW-08-f (": _PS_DIGEST,
    "EXT FW-07-I:": (
        "extended FW-07-I sweep (freeze onset across the watchdog phase x power-cut point): the frozen-end windows "
        "and the rebased 15 s boot-restore bound of the quick FW-07-I checks, on the lab grid (fails under the phase "
        "patch)"),
    "EXT FW-08-B:": (
        "extended FW-08-B sweep (leak offsets x both same-tick watchdog orders): the INV-20 escalation bound on the "
        "census / watchdog grid (fails under the phase patch)"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = (
    "EXT FW-07-I:",
    "EXT FW-08-B:",
)
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


import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402

SUITE = "test_lab_fw_runtime"
FWP = L.FW_REL
FCP2 = "docs/dev/dump-to-grid-safety-fcp2.md"
WSURF = "docs/dev/advanced-config/write-surface.md"
S4DOC = "docs/architecture/fallback/design/S4_domains_decisions_final.md"
HDR = "firmware/include/ecco_durable_snapshot.h"
FW = L.load_fw()
INFO = L.fw_info(FW)
SUBS = FW["_substitutions"]
U0_ISO = "2026-10-21T10:50:00Z"                  # a synthetic Wednesday (BST); no site value
U0 = C.parse_iso_utc(U0_ISO)
ORIG = dict(L.SITE["original"])
DUMP_REGS = (244, 256, 257, 258, 259, 260, 261)
FINDINGS: dict[str, str] = {}
# Findings of this suite that duplicate another suite's root cause ({fid: owner finding id}): printed 'DUPLICATE of <owner
# id>, not counted', still reproduced and asserted, left out of the LAB-SUMMARY finding count. Empty: F-FW07-1..5 and
# F-FW08-1 have no counterpart in the other lab suites (F-FW07-2 is reproduced here four times but counted once).
DUPLICATE_OF: dict[str, str] = {}
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (one line per unsupported point met)
NC_RESULTS: list[tuple[str, str, str, str]] = []
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")


def sub_s(name: str) -> float:
    """A firmware substitution in milliseconds, as seconds (the bounds below come from the firmware, never hard-coded)."""
    return int(SUBS[name]) / 1000


SOC_STALE_S = sub_s("ecco_dump_soc_stale_ms")            # 90 s
CFG_STALE_S = sub_s("ecco_dump_cfg_stale_ms")            # 180 s
LINK_DOWN_S = sub_s("ecco_dump_link_down_ms")            # 25 s
STUCK_S = sub_s("ecco_write_lock_stuck_ms")              # 180 s
GRACE_S = sub_s("ecco_free_power_invalid_clock_grace_ms")  # 300 s
WD_S = INFO.job["dump_wd"]["period_ms"] / 1000           # 15 s
WD_FIRST_S = INFO.job["dump_wd"]["startup_ms"] / 1000    # 15 s after power-on
FP_WD_S = INFO.job["fp_wd"]["period_ms"] / 1000
CENSUS_S = INFO.job["census"]["period_ms"] / 1000        # 5 s
CONFIG_S = INFO.job["config"]["period_ms"] / 1000        # 60 s
TEL_S = INFO.job["telemetry"]["period_ms"] / 1000        # 10 s
_tab = re.search(r"static const uint32_t table_ms\[\] = \{([0-9, ]+)\};", T.read_source_text(HDR))
BACKOFF_S = [int(x) // 1000 for x in _tab.group(1).split(",")] if _tab else []
FROZEN_N = int(SUBS["ecco_dump_frozen_samples"])                 # 6 identical reads (battery power; grid CT, fast)
FROZEN_CROSS_W = int(SUBS["ecco_dump_frozen_cross_w"])            # 150 W battery movement for the fast CT criterion
FROZEN_LONG_N = int(SUBS["ecco_dump_frozen_ct_long_samples"])     # 30 identical reads (grid CT, slow)
SOC_FROZEN_WH = int(SUBS["ecco_dump_soc_frozen_wh"])              # 1500 Wh discharged with no SOC change
RUNAWAY_GRACE_S = sub_s("ecco_dump_runaway_grace_ms")            # 30 s lease-start grace (the frozen evidence starts after it)
RESTART_DOWN_S = 3.0                                    # FirmwareWorld default restart_down_s (MODEL)
BOOT_S = 2.0                                            # FirmwareWorld default boot_ms (realistic uptime at on_boot)
SG39_BOUND_S = WD_S + TEL_S + 5                          # one watchdog tick + one telemetry poll + 5 s margin


def q(s: float) -> float:
    """A backoff step as observed: the restore runs only on the watchdog grid."""
    return math.ceil(s / WD_S) * WD_S


TL = "TELEMETRY LOST - failing closed"
CRS = "CONFIG READBACK STALE - failing closed"
ESPR = "ESP RESTARTED DURING LEASE - ended, not resumed"
WLS = ("WRITE LOCK STUCK - an inverter transaction lock was held beyond any transaction's bound; lease ended durably, "
       "restarting so the boot path completes the restore")
DEFER_LOCK = "END DEFERRED - another inverter write is active; watchdog will retry"
REJ_LOCK = "REJECTED - another inverter write is active"
UNPROVEN = "register 244 is NOT proven out of Allow Export - export may continue"
CONTAINED = "register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"
STUCK_NOTHING = ("STUCK LOCK - an inverter transaction lock was held beyond any transaction's bound; nothing is owed, so no "
                 "automatic restart - inverter writes stay blocked until Restart (Restart Override Arm)")
FP_FAILED = "RESTORE WRITE FAILED - snapshot retained; will retry automatically"
DEFER_BACKOFF = "END DEFERRED - previous restore attempt failed; waiting out retry backoff; watchdog will retry automatically"
CTF = "GRID CT FROZEN - "                               # the frozen-telemetry end texts (prefixes of the firmware's snprintf)
BPF = "BATTERY POWER TELEMETRY FROZEN - "
SOCF = "SOC TELEMETRY FROZEN - "
LAT: dict[str, float] = {}                              # measured latencies reused in later FINDING lines

# =============================================================================================================================
# scenario table (ownership, exact source anchors, invariant, failure outcome, classification, grade, confidence, priority)
# =============================================================================================================================
OWN_DUMP = ("ECCO owns a Dump to Grid lease started by the owner through the real Start button (synthetic SITE ORIGINAL 244 = 2, "
            "256-261 = 8000/8000/7000/8000/8000/5000; lease 1000 W, Stop SOC 25 %); no foreign actor; the link outage is the "
            "lab's coupled link MODEL (reads no_response, writes timeout_lost, the real telemetry / configuration polls fail "
            "through their real handlers)")
OWN_FP = ("ECCO owns a Free Power lease started by the owner through the real Start button (synthetic SITE ORIGINAL); no "
          "foreign actor; the outage is the coupled link MODEL")
OWN_LEAK = ("ECCO owns the lease; a transaction lock is leaked by an unidentified code path (white-box RAM injection through "
            "inject_global, logged as fault.ram, MODEL; no leaking path that can overlap a lease is known - see FW-08-A)")
LEAK_MODEL = "white-box RAM lock leak (MODEL): inject_global, logged as fault.ram"
OWN_FROZEN = ("ECCO owns a Dump to Grid lease started by the owner through the real Start button (synthetic SITE ORIGINAL; "
              "lease 1000 W, Stop SOC 25 %); no foreign actor; the link stays UP (every telemetry and configuration read "
              "answers): one reading repeats exactly while the other keeps moving (noise MODEL off, explicit values for "
              "every poll slot), or the SOC never changes while the battery discharges about 1 kW (no SOC physics); the "
              "power cut is the reboot primitive armed at a restore write")
SCENARIOS = {
    "FW-07-A": {
        "title": "Link down during an ACTIVE Dump lease: TELEMETRY LOST end, supervised retries, SG-39 recovery",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-17, INV-RESTORE-BOUND (rebased at link recovery), INV-NO-SILENT-OVERRIDE, INV-WS",
        "ownership": OWN_DUMP,
        "anchors": [(FWP, 'reason: "TELEMETRY LOST - failing closed"'),
                    (FWP, "return !soc_plausible || !soc_fresh || !id(configuration_online).state;"),
                    (FWP, 'reason: "CONFIG READBACK STALE - failing closed"'),
                    (FWP, "(int32_t) (millis() - (id(dump_restore_failed_ms) + ecco_durable::comms_backoff_ms(1))) >= 0)) &&"),
                    (FWP, "(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : millis() > ${ecco_dump_soc_stale_ms}UL);"),
                    (FWP, 'ecco_dump_soc_stale_ms: "90000"'), (FWP, 'ecco_dump_link_down_ms: "25000"'),
                    (FCP2, "**The restore backoff (SG-39).** A restore attempt that failed while the link itself was down"),
                    (FCP2, "Stop SOC's freshness check ends the lease after 90 s;")],
        "failure_outcome": "export continues after the link is lost (no lease end), or the owed restore waits out a backoff "
                           "of up to 300 s after the link is proven to work again, or the override is left silent",
        "corpus": ["FW-07-a"], "finding": None,
        "model": "coupled link MODEL; telemetry noise MODEL; no inverter physics (export / SOC change only via telemetry())",
        "notes": "The recovery restore is the SG-39 path, not the every-tick supervision: the first telemetry read after the "
                 "recovery makes the SOC fresh (above Stop SOC) before the next watchdog tick, so the supervision is off; "
                 "the SG-39-removed mutant (NC-FW07-1) leaves the restore open, the supervision-removed mutant does not "
                 "change it (checked in [1])"},
    "FW-07-B": {
        "title": "Link down during the restore after 244 was proven: comms backoff 15/30/60/120/300 s, SG-39 at recovery",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-14 (bounded backoff), INV-RESTORE-BOUND (rebased at link recovery)",
        "ownership": OWN_DUMP,
        "anchors": [(FWP, "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"),
                    (FWP, "(id(dump_restore_failed_ms) != 0 &&"),
                    (HDR, "static const uint32_t table_ms[] = {15000, 30000, 60000, 120000, 300000};")],
        "failure_outcome": "retries hammer the inverter (no backoff) or the restore sits out up to 300 s after the link is back",
        "corpus": ["FW-07-b"], "finding": None, "model": "coupled link MODEL; a one-shot write timeout_lost on 256 (policy)"},
    "FW-07-C": {
        "title": "Reboot during an ACTIVE lease, link down after boot: no-resume and the 90 s no-fresh-SOC supervision",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-NO-RESUME, INV-16 (missing SOC counts as reached once 90 s have passed since boot)",
        "ownership": OWN_DUMP,
        "anchors": [(FWP, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
                    (FWP, "(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : millis() > ${ecco_dump_soc_stale_ms}UL);"),
                    (FWP, "stop_known = id(dump_end_epoch) != 0 && (rec >> 8) == (id(dump_end_epoch) & 0xFFFFFFu) &&"),
                    (FCP2, "treats a SOC reading that is missing or older than 90 s (once 90 s have passed since boot) as reached.")],
        "failure_outcome": "the lease resumes blind after the reboot, or the owed restore is paced by the backoff with "
                           "export unproven and no fresh SOC beyond 90 s of uptime",
        "corpus": ["FW-07-c"], "finding": None, "model": "power cut 5 s (reboot primitive), boot at uptime 2 s; link MODEL"},
    "FW-07-D": {
        "title": "Reboot, inverter refuses 244 writes, fresh SOC: the persisted owed Stop SOC governs the supervision",
        "priority": "P2", "classification": "FINDING-KNOWN:FCP2-R1", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-16 (owed Stop SOC from dump_owed_stop_soc_rec, bound to the obligation's end epoch)",
        "ownership": OWN_DUMP + "; the owner lowers the configured Stop SOC to 10 % after START; the inverter answers reads "
                                "but refuses every 244 write (Modbus exception, synthetic)",
        "anchors": [(FWP, "id(dump_owed_stop_soc_rec) = ((id(dump_end_epoch) & 0xFFFFFFu) << 8) | ((uint32_t) id(dump_target_stop_soc) & 0xFFu);"),
                    (FWP, "stop_known = id(dump_end_epoch) != 0 && (rec >> 8) == (id(dump_end_epoch) & 0xFFFFFFu) &&"),
                    (FWP, "if (stop_known && !std::isnan(cfg) && (int) lroundf(cfg) > stop) stop = (int) lroundf(cfg);"),
                    (FWP, "(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : millis() > ${ecco_dump_soc_stale_ms}UL);"),
                    (FCP2, "treats a SOC reading that is missing or older than 90 s (once 90 s have passed since boot) as reached.")],
        "failure_outcome": "after a restart the supervision either never fires (Stop SOC forgotten, or the owner's lower "
                           "configured Stop SOC wins) or fires at any SOC (owed Stop SOC unbound); export stays enabled "
                           "while 244 is refused (accepted residual FCP2-R1)",
        "corpus": ["FW-07-d"], "finding": "F-FW07-3",
        "model": "Modbus policy write:244 -> error (the inverter refuses the write); reboot primitive; the owner's Stop "
                 "SOC change is the logged world action owner_set_number (replay action set_number)",
        "notes": "Refinements: the 500 W containment bounds ECCO's own TOU slot power (battery discharge per "
                 "slot), not PV export (the inverter's own register 245) and not FOREIGN slots (FCP2-C1); each failed "
                 "attempt's status names the unproven 244 and the floor, but on this comms path nothing is CRITICAL and "
                 "the END DEFERRED status between backoff attempts does not name 244; the restart is not needed for the "
                 "R1 end state (an END with 244 refused reaches it too), only for the owed Stop SOC supervision, which "
                 "PASSES; an inverter that acknowledges and ignores 244 takes the verify-mismatch path to the operator "
                 "lockout instead (still FCP2-R1, not run here). The record-bound versus configured Stop SOC "
                 "distinction is pinned in the suite ([4], NC-FW07-4, NC-FW07-7) and in corpus FW-07-d (set_number "
                 "to 10 %, the retry count at SOC 24 %; both mutants fail its expectations, [16])"},
    "FW-07-E": {
        "title": "Reboot with NTP invalid at early uptime: the 300 s grace never delays the owed restore (Dump, FP S3)",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-NO-RESUME, INV-RESTORE-BOUND",
        "ownership": OWN_DUMP + "; Free Power analogue: " + OWN_FP,
        "anchors": [(FWP, 'ecco_free_power_invalid_clock_grace_ms: "300000"'),
                    (FWP, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
                    (FWP, 'ESP_LOGW("free_power", "Free Power was ACTIVE at last shutdown - ending and restoring on this boot rather than resuming the lease");')],
        "failure_outcome": "a lease resumes after the reboot and, with the clock invalid, runs on the 300 s grace",
        "corpus": ["FW-07-e"], "finding": None,
        "model": "first NTP sync at uptime 400 s on every boot (FirmwareWorld ntp_after_s); SNTP re-sync not modelled"},
    "FW-07-F": {
        "title": "Free Power analogue: link down during the FP restore; no SG-39 link-recovery retry",
        "priority": "P2", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-RESTORE-BOUND (rebased at link recovery, the SG-39 bound of the Dump analogue)",
        "ownership": OWN_FP,
        "anchors": [(FWP, "if (next_ms != 0 && (int32_t)(now_ms - next_ms) < 0) {"),
                    (S4DOC, "COMMS backoff 15-300 s"), ("SAFETY.md", "by ECCO after it recovers or by you"),
                    (FCP2, "**The restore backoff (SG-39).** A restore attempt that failed while the link itself was down")],
        "failure_outcome": "the Free Power override (232 grid-charge enable, 230 grid-charge current, 256-261 TOU power, "
                           "268-279 SOC targets and flags) stays on the inverter for the rest of the current comms backoff "
                           "window after the link is back (0-300 s on the watchdog grid, depending on the backoff phase)",
        "corpus": ["FW-07-f"], "finding": "F-FW07-1", "model": "coupled link MODEL",
        "notes": "Severity low (cost / availability; Free Power only charges, no export); the status stays accurate "
                 "(RESTORE WRITE FAILED ... will retry automatically) and an owner End press clears the backoff. The "
                 "extra delay is the remaining part of the backoff window, not a fixed 300 s (extended sweep [17])."},
    "FW-07-G": {
        "title": "Reboot while a restore is owed: the boot path misattributes the already-ended lease's end to the restart",
        "priority": "P3", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-FIRST-END-REASON (the firmware's own contract: Last End Reason holds the FIRST reason the "
                     "lease ended, later calls must not overwrite it; the boot comment assumes a mid-restore record has "
                     "active_persisted 0)",
        "ownership": OWN_DUMP,
        "anchors": [(FWP, "# 2026-09-26 pre-live hardening: the FIRST reason the current/last lease"),
                    (FWP, "// 2026-09-26 pre-live hardening: keep the FIRST end reason of a"),
                    (FWP, "if (!id(dump_restore_requested) && (id(dump_snapshot_valid) || id(dump_operation_in_progress))) {"),
                    (FWP, "// (active_persisted == 0), this is already true anyway."),
                    (FWP, 'id(dump_last_end_reason).publish_state("ESP RESTARTED DURING LEASE - ended, not resumed");'),
                    (FWP, 'r = (id(dump_active_persisted) && !id(dump_restore_requested)) ? "a Dump to Grid lease is active"'),
                    (FCP2, "1. **An active Dump lease is ended durably.**")],
        "failure_outcome": "after a reboot between a lease end and its verified restore (and after every stuck-lock "
                           "escalation restart) Last End Reason says ESP RESTARTED DURING LEASE for a lease that had "
                           "already ended; the reason is a RAM-only text sensor, so it cannot survive a reboot anyway - "
                           "the defect is the wrong attribution",
        "corpus": ["FW-07-g"], "finding": "F-FW07-2", "model": "coupled link MODEL; reboot primitive",
        "notes": "Primary specification: the firmware's own comments (Last End Reason sensor, request_dump_end, boot "
                 "block); the census already separates 'lease is active' from 'restore is owed' with the same two "
                 "flags. fcp2 section 6 step 1 promises a durable end request, not a durable reason (context only). "
                 "Diagnostics only (display-only text; no package reads it)."},
    "FW-07-H": {
        "title": "One failed configuration block read during an ACTIVE Dump lease ends it as TELEMETRY LOST",
        "priority": "P3", "classification": "FINDING-NEW", "grade": "VERIFIED", "confidence": "low",
        "invariant": "lab expectation, not a documented requirement: one transient configuration read failure is "
                     "tolerated like a single missed telemetry read (the 90 s SOC freshness bound), and configuration "
                     "evidence is bounded by ecco_dump_cfg_stale_ms 180 s",
        "ownership": OWN_DUMP + "; one non-ok reply (exception / no response / not sent / non-standard) on ONE "
                                "configuration block read, every other operation answered",
        "anchors": [(FWP, "return !soc_plausible || !soc_fresh || !id(configuration_online).state;"),
                    (FWP, 'ESP_LOGW("config", "No response to configuration block 200-240");'),
                    (FWP, "# FB-D1 (D1b): re-check again before Block C (register 330 is display-only; a skipped read is not a failure)."),
                    (FWP, 'post-activation readback is ended as "readback stale".'),
                    (FWP, 'ecco_dump_cfg_stale_ms: "180000"')],
        "failure_outcome": "a single transient configuration read failure ends the lease early, fail closed "
                           "(availability), and the end reason names telemetry (diagnostics); the 180 s configuration "
                           "staleness bound only matters when polls are skipped, not when one fails",
        "corpus": ["FW-07-h"], "finding": "F-FW07-4",
        "model": "Modbus policy: one outcome on one read; the failure handlers are the REAL firmware handlers",
        "notes": "Confidence low that this is unintended: the configuration_online term is explicit fail-closed code and "
                 "no public document states its rationale, so it is NEW only against the public docs and KNOWN_RISKS; "
                 "the mechanism itself is high confidence. Severity low (P3): the lease ends early but fail closed, the "
                 "restore completes, nothing is resumed. The display-only Block C read ending a lease is the clearest "
                 "incidental coupling. Removing only the term moves a real link-loss end from about 28 s to about 88 s "
                 "(SOC freshness) and leaves a persistent Block B failure to CONFIG READBACK STALE (repair probe in [8])."},
    "FW-07-I": {
        "title": "Frozen telemetry with the link up during an ACTIVE Dump lease (grid CT, battery power, SOC): the frozen end "
                 "crossed with the restore, a power cut at a restore write and a reboot",
        "priority": "P2", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-17 (frozen telemetry ends the lease with the firmware's own reason within its sample bound), "
                     "INV-RESTORE-BOUND (rebased at the boot), INV-NO-RESUME, INV-NO-SILENT-OVERRIDE, INV-BOOT-MIRROR",
        "ownership": OWN_FROZEN,
        "anchors": [(FWP, 'ecco_dump_frozen_samples: "6"'), (FWP, 'ecco_dump_frozen_ct_long_samples: "30"'),
                    (FWP, 'ecco_dump_soc_frozen_wh: "1500"'),
                    (FWP, "bool ct_frozen = (id(dump_ct_same_count) >= ${ecco_dump_frozen_samples} - 1 &&"),
                    (FWP, "return ct_frozen || id(dump_bp_same_count) >= ${ecco_dump_frozen_samples} - 1 ||"),
                    (FWP, "id(dump_soc_frozen_wh_acc) > ${ecco_dump_soc_frozen_wh}.0f;"),
                    (FWP, "// fcp2 (SG-15 / SG-43): fresh frozen-telemetry evidence."),
                    (FWP, '// a range seeded empty when there is no battery reading yet (never "moved")'),
                    (FCP2, "| Grid CT, fast | it repeats exactly for `ecco_dump_frozen_samples` reads while the battery "
                           "power moved by more than `ecco_dump_frozen_cross_w`."),
                    (FCP2, "| Grid CT, slow | it repeats exactly for `ecco_dump_frozen_ct_long_samples` reads, whatever "
                           "the battery did."),
                    (FCP2, "**New: readings that keep arriving but never change.**")],
        "failure_outcome": "a lease keeps exporting on a grid CT, battery power or SOC reading that is no longer evidence "
                           "(the controller, the export guard, the runaway guard or Stop SOC deciding on it) although the "
                           "link is up, or the restore after the frozen end is lost at a power cut, or the reboot resumes "
                           "the lease, or a new START after the reboot runs unguarded on the still-frozen reading",
        "corpus": ["FW-07-i", "FW-07-i2", "FW-07-i3"], "finding": "F-FW07-5",
        "model": "noise MODEL off (world noise=False) with explicit grid CT / battery values for every 10 s poll slot "
                 "(replay action telemetry, poll False); no SOC physics; arm_power_cut at the restore's first 244 or "
                 "256-261 write; reboot primitive (power cut 5 s)",
        "notes": "Coverage: registry/tests/test_dump_safety_fcp2.py section [T] already tests each frozen detector's end "
                 "reason inside a lease on hand-fed sensor publishes, so the end reasons here re-verify them through the "
                 "real 10 s poll, decode and watchdog cadence; new here is the crossing: the frozen end followed by the "
                 "restore, a power cut at the restore's 256-261 (grid CT) or 244 (battery power, SOC) write and the "
                 "boot-path restore (INV-BOOT-MIRROR non-vacuous: the stored RESTORE_REQUIRED is mirrored at the boot), a "
                 "reboot after a completed restore, then a new START on the still-frozen CT (the detector re-arms from "
                 "the new lease's evidence; the reboot launders nothing). The F-FW07-2 misattribution (owned by FW-07-G) "
                 "also follows a frozen end cut short by a power cut. Incidental F-FW07-5 ([8b]): the battery range of "
                 "the fast CT criterion is not re-seeded at START or outside a lease. NC-FW07-8 / -9 / -10 remove the "
                 "fast CT term, the frozen-SOC term and the battery-power term of the watchdog's frozen condition."},
    "FW-08-A": {
        "title": "Single-op Modbus outcome sweep over the lock-taking scripts: which outcome leaks a transaction lock",
        "priority": "P3", "classification": "PASS", "grade": "VERIFIED", "confidence": "medium",
        "invariant": "INV-20 (a lock is never released by time; a leaked lock is caught by the lock-age monitor)",
        "ownership": "owner-initiated Dump / Free Power START and END, owner manual TOU slot apply; one non-ok outcome on "
                     "one Modbus op per case (allow-listed outcomes)",
        "anchors": [(WSURF, "The verify read has no bounded `wait_until`: the mutex is released only inside the read callbacks."),
                    (FWP, 'id(manual_config_last_result).publish_state("VERIFY FAILED - Slot 2 verification timed out");'),
                    (FWP, "nothing is owed, so no automatic restart - inverter writes stay blocked until Restart (Restart Override Arm)"),
                    (FWP, "bool held = id(manual_write_in_progress) || id(dump_operation_in_progress) ||")],
        "failure_outcome": "a lock leaks silently and blocks every restore / START until a reboot",
        "corpus": ["FW-08-a"], "finding": None,
        "model": "'timeout' = no callback at all (the firmware's own wait_until timeout case); synchronous ds.Sim Modbus"},
    "FW-08-B": {
        "title": "manual_write_in_progress leaked at Dump lease end: deferral, > 180 s escalation, restart, boot restore",
        "priority": "P3", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-20 (escalation and restore bounded), INV-NO-RESUME, INV-RESTORE-BOUND, INV-WS",
        "ownership": OWN_LEAK,
        "anchors": [(FWP, "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"),
                    (FWP, 'id(dump_status).publish_state("END DEFERRED - another inverter write is active; watchdog will retry");'),
                    (FWP, "return id(live_telemetry).state && !id(correction_in_progress) && !id(manual_write_in_progress);"),
                    (FWP, "if ((uint32_t) (millis() - id(ecco_lock_since_ms)) > ${ecco_write_lock_stuck_ms}UL) id(ecco_lock_stuck) = true;"),
                    (FWP, 'ecco_write_lock_stuck_ms: "180000"'),
                    (FWP, "id(ecco_restart_status).publish_state(\"RESTARTING (stuck lock) - an inverter transaction lock was held beyond any transaction's bound while a lease or restore is owed; the lock is NOT released - the boot path completes the owed restore\");")],
        "failure_outcome": "the owed restore stays deferred behind the leaked lock indefinitely (export left enabled)",
        "corpus": ["FW-08-c"], "finding": None, "model": LEAK_MODEL + "; graceful restart (restart_down_s 3 s)"},
    "FW-08-C": {
        "title": "Leaked Dump operation flag during an ACTIVE lease: WRITE LOCK STUCK end, restart, boot restore",
        "priority": "P3", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-20 (Stop SOC overrun bounded by the escalation), INV-NO-RESUME",
        "ownership": OWN_LEAK,
        "anchors": [(FWP, 'reason: "WRITE LOCK STUCK - an inverter transaction lock was held beyond any transaction\'s bound; lease ended durably, restarting so the boot path completes the restore"'),
                    (FCP2, "1. **An active Dump lease is ended durably.**")],
        "failure_outcome": "a leaked operation flag suspends every lease monitor (Stop SOC, telemetry loss) indefinitely",
        "corpus": ["FW-08-d"], "finding": "F-FW07-2", "model": LEAK_MODEL},
    "FW-08-D": {
        "title": "Free Power analogue: lock leaked during an FP lease: escalation restart, S3, FP restore",
        "priority": "P3", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-20, INV-NO-RESUME",
        "ownership": OWN_LEAK.replace("the lease", "the Free Power lease"),
        "anchors": [(FWP, "if (id(free_power_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"),
                    (FWP, 'ESP_LOGW("free_power", "Free Power was ACTIVE at last shutdown - ending and restoring on this boot rather than resuming the lease");')],
        "failure_outcome": "the FP restore stays deferred behind the leaked lock indefinitely",
        "corpus": ["FW-08-e"], "finding": None, "model": LEAK_MODEL},
    "FW-08-E": {
        "title": "RTC lock windows deferring restores: Dump end inside a window, a window during an ACTIVE lease",
        "priority": "P3", "classification": "PASS", "grade": "VERIFIED", "confidence": "high",
        "invariant": "INV-RTC-EXCL (no restore write inside an RTC lock window), INV-RESTORE-BOUND (lock-explained)",
        "ownership": OWN_DUMP + "; the RTC correction lock comes from a synthetic window (MODEL)",
        "anchors": [(FWP, 'id(dump_status).publish_state("END DEFERRED - RTC correction active; watchdog will retry");'),
                    (FCP2, "| The FB-D1 RTC deadline breaker |"),
                    (FWP, "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;")],
        "failure_outcome": "a restore writes during an RTC correction, or an ordinary correction ends a lease (nuisance)",
        "corpus": ["FW-08-b"], "finding": None, "model": "rtc_lock_windows MODEL (the RTC tick and its 90 s breaker are NOT executed)"},
    "FW-08-F": {
        "title": "A leak that recurs before the first watchdog tick of every boot: unbounded restart loop",
        "priority": "P3", "classification": "FINDING-KNOWN:FCP2-F6", "grade": "VERIFIED", "confidence": "low",
        "invariant": "INV-20 / INV-RESTORE-BOUND (the documented residual: restart at most once per bound)",
        "ownership": OWN_LEAK + "; the leak recurs at uptime 10 s on every boot (any re-leak before that boot's owed "
                                "restore completes would do)",
        "anchors": [(FCP2, "If a code path leaks the lock again after every boot, the device restarts at most once per bound"),
                    (FCP2, "There is no persistent restart counter."),
                    (FWP, "bool held = id(manual_write_in_progress) || id(dump_operation_in_progress) ||"),
                    (FWP, "if ((uint32_t) (millis() - id(ecco_lock_since_ms)) > ${ecco_write_lock_stuck_ms}UL) id(ecco_lock_stuck) = true;"),
                    (FWP, 'the boot path completes the owed restore");'),
                    (FWP, "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"),
                    (FWP, "boot_is_good_after: 1min")],
        "failure_outcome": "the owed Dump restore never completes; 244 stays at Allow Export and 256-261 at the lease power "
                           "(uncontained, no write after the leak, no CRITICAL status) across the restart loop",
        "corpus": ["FW-08-f"], "finding": "F-FW08-1", "model": LEAK_MODEL + ", recurring per boot",
        "notes": "A refinement of the OUTSTANDING FCP2-F6 'restart loop' residual, not a new risk class: the residual's "
                 "'(each boot then completes the owed restore)' and the RESTARTING (stuck lock) text hold only when the "
                 "re-leak comes after that boot's first Dump watchdog tick. Each cycle (about 203 s) outlives "
                 "boot_is_good_after 1 min, so ESPHome safe mode never ends the loop (INFERRED). Severity: safety-adjacent "
                 "(244 at Allow Export, nothing contained; no inverter protection boundary is crossed: register 245 "
                 "and the battery protection stay the inverter's) plus availability (a restart about every 203 s) and "
                 "diagnostics; low overall risk because the trigger is hypothetical (reachability UNKNOWN)."},
}


def finding(fid: str, text: str) -> None:
    if fid not in FINDINGS:
        FINDINGS[fid] = text
        if fid in DUPLICATE_OF:
            text = f"DUPLICATE of {DUPLICATE_OF[fid]}, not counted: {text}"
        print(T.finding_line(fid, text))


def unsupported(uid: str, text: str) -> None:
    """One UNSUPPORTED line per unsupported point met (uid = the catalogue unsupported id; repeats are separate points)."""
    UNSUPPORTED_POINTS.append(uid)
    print(T.unsupported_line(uid, text))


# =============================================================================================================================
# world helpers (environment only; the firmware decides)
# =============================================================================================================================
def world(fw=None, warm: float = 60, **kw) -> L.FirmwareWorld:
    return L.FirmwareWorld(fw, utc_start=U0, warmup_s=warm, **kw)


def dump_lease(w, minutes: int = 60, **telemetry) -> str:
    w.telemetry(grid_w=L.SITE["dump_grid_w"], batt_w=L.SITE["dump_battery_w"], **telemetry)
    return w.dump_start(power_w=1000, stop_soc=25, minutes=minutes)


def evs(w, kind, t0=None, t1=None, boot=None) -> list:
    return [e for e in w.log.events(kind=kind) if (t0 is None or e["t_utc"] >= t0) and (t1 is None or e["t_utc"] <= t1)
            and (boot is None or e["boot"] == boot)]


def dump_attempts(w, t0=None, t1=None, boot=None) -> list:
    """Every Dump restore attempt starts with its ownership pre-read 244x18 (firmware restore_dump_to_grid_snapshot)."""
    return [e for e in evs(w, "fw.read", t0, t1, boot) if e["data"]["addr"] == 244 and e["data"]["count"] == 18]


def fp_attempts(w, t0=None, t1=None) -> list:
    """Free Power restore attempts during an outage: each one fails at its first pre-read 230x3."""
    return [e for e in evs(w, "fw.read", t0, t1) if e["data"]["addr"] == 230 and e["data"]["count"] == 3]


def gaps(ts: list) -> list:
    return [round(b - a, 3) for a, b in zip(ts, ts[1:])]


def statuses(w, dom: str, t0=None) -> list:
    return [(e["t_utc"], e["data"]["text"]) for e in evs(w, "fw.status", t0) if e["data"]["dom"] == dom]


def obl_of(e):
    return e["data"] if e["kind"] == "fw.obl" else e["data"].get("obl") if e["kind"] == "fw.booted" else None


def completion_t(w, dom: str, t0):
    """UTC of the first logged obligation state after t0 with the domain's restore complete (snapshot cleared, marker
    CLEAR / ABSENT); None if it never completed."""
    for e in w.log:
        o = obl_of(e) if e["t_utc"] >= t0 else None
        if o is not None and not o[dom]["snap"] and o["nvs"][dom] in ("CLEAR", "ABSENT"):
            return e["t_utc"]
    return None


def restored(w, dom: str) -> bool:
    """The domain's restore is complete in the firmware's own state (RAM snapshot cleared, durable marker CLEAR)."""
    return not w.sim.g[{"fp": "free_power_snapshot_valid", "dump": "dump_snapshot_valid"}[dom]] and \
        w.nvs_marker(dom) == "CLEAR"


def run_until(w, pred, limit_s: float, step: float = 5) -> None:
    """Live run in small steps until pred() (a firmware restart aborts a run_for; the loop continues on the new boot)."""
    t_lim = w.t_utc + limit_s
    while not pred() and w.t_utc < t_lim:
        w.run_for(min(step, t_lim - w.t_utc))


def last_ok_telemetry_t(w, before):
    ok = [e["t_utc"] for e in evs(w, "fw.read", None, before) if e["data"]["addr"] == 150 and e["data"]["outcome"] == "ok"]
    return ok[-1] if ok else None


def rebased_restore_bound(w, seq_from: int, bound_s: float) -> list:
    """The core INV-RESTORE-BOUND checker applied to the log from the event `seq_from` on (the link recovery), with the
    obligation state at that instant as the opening fw.obl (a re-based window over the REAL log, nothing hand-built): a
    restore owed at the recovery must complete within bound_s unless the core's own explanations apply after it."""
    log = list(w.log)
    base = None
    for e in log[: seq_from + 1]:
        o = obl_of(e)
        if o is not None:
            base = o
    head = dict(log[seq_from], kind="fw.obl", src="fw", data=base)
    return L.check_restore_bound([head] + log[seq_from + 1:], world=w, bound_s=bound_s)


def viol(inv: str, detail: str) -> dict:
    return {"inv": inv, "seq": -1, "detail": detail, "tags": []}


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
    check("the bounds come from the firmware: SOC stale 90 s, config stale 180 s, link-down 25 s, stuck lock 180 s, NTP "
          "grace 300 s, Dump watchdog 15 s (first at 15 s), census 5 s, config poll 60 s, telemetry 10 s; the comms backoff "
          "table of ecco_durable_snapshot.h is 15/30/60/120/300 s",
          (SOC_STALE_S, CFG_STALE_S, LINK_DOWN_S, STUCK_S, GRACE_S, WD_S, WD_FIRST_S, CENSUS_S, CONFIG_S, TEL_S)
          == (90, 180, 25, 180, 300, 15, 15, 5, 60, 10) and BACKOFF_S == [15, 30, 60, 120, 300],
          f"{(SOC_STALE_S, CFG_STALE_S, LINK_DOWN_S, STUCK_S, GRACE_S, WD_S, WD_FIRST_S, CENSUS_S, CONFIG_S, TEL_S)} "
          f"{BACKOFF_S}")
    check("the frozen-telemetry bounds come from the firmware: 6 identical reads (battery power; grid CT while the battery "
          "moved > 150 W), 30 identical CT reads whatever the battery did, 1500 Wh with no SOC change, after the 30 s "
          "lease-start grace", (FROZEN_N, FROZEN_CROSS_W, FROZEN_LONG_N, SOC_FROZEN_WH, RUNAWAY_GRACE_S)
          == (6, 150, 30, 1500, 30), f"{(FROZEN_N, FROZEN_CROSS_W, FROZEN_LONG_N, SOC_FROZEN_WH, RUNAWAY_GRACE_S)}")
    check("every status literal this suite compares against occurs in the firmware text (no stale literal)",
          all(FW["_text"].count(x) >= 1 for x in (TL, CRS, ESPR, WLS, DEFER_LOCK, REJ_LOCK, UNPROVEN, CONTAINED,
                                                  STUCK_NOTHING, FP_FAILED, DEFER_BACKOFF, CTF, BPF, SOCF)))


# =============================================================================================================================
# FW-07-A  link down during an ACTIVE Dump lease
# =============================================================================================================================
def run_07a(fw=None, down_after: float = 120, outage: float = 300, mode: str = "link") -> dict:
    w = world(fw)
    st = dump_lease(w)
    w.run_for(down_after)
    t_down = w.t_utc
    if mode == "link":
        w.set_link(False)
    elif mode == "telemetry_block":   # partial loss: only the telemetry block 150-196 stops answering
        w.modbus_policy({"read:150x47": "no_response"})
    elif mode == "polling_off":       # the owner turns configuration polling off (a RESTORE_DEFAULT_ON switch)
        w.set_switch("configuration_polling", False)
    else:
        raise L.LabHarnessError(f"unknown mode {mode!r}")
    w.run_for(outage)
    t_up = w.t_utc
    unverified = w.sim.g["dump_export_unverified"]
    if mode == "link":
        w.set_link(True)
    elif mode == "telemetry_block":
        w.modbus_policy(None)
    seq_up = len(w.log) - 1
    w.run_for(60)
    return {"w": w, "start": st, "t_down": t_down, "t_up": t_up, "seq_up": seq_up, "unverified": unverified}


def inv17_violations(r, reason=TL, bound_s=CONFIG_S + WD_S) -> list:
    """INV-17: a lost link ends the lease, fail closed, with the reason `reason` within bound_s of the loss."""
    ends = statuses(r["w"], "dump_end", r["t_down"])
    if not ends:
        return [viol("INV-17", "the lease never ended after the link loss")]
    t, text = ends[0]
    if text != reason or t - r["t_down"] > bound_s:
        return [viol("INV-17", f"lease ended {t - r['t_down']:.0f} s after the loss with {text!r} (bound {bound_s} s, "
                               f"expected {reason!r})")]
    return []


def section_07a() -> dict:
    print("[1] FW-07-A link down during an ACTIVE Dump lease (coupled link model), 300 s outage, recovery")
    r = run_07a()
    w = r["w"]
    check("FW-07-A: the lease STARTs ACTIVE (synthetic site, telemetry noise MODEL keeps the frozen-telemetry guards quiet)",
          r["start"].startswith("ACTIVE - VERIFIED OK"), r["start"])
    ends = statuses(w, "dump_end", r["t_down"])
    if ends:
        print(f"  info  FW-07-A lease end {ends[0][0] - r['t_down']:.0f} s after the link loss: {ends[0][1]}")
        LAT["tl_07a"] = round(ends[0][0] - r["t_down"])
    v = inv17_violations(r)
    check(f"FW-07-A INV-17: the lease ends '{TL}' within {CONFIG_S + WD_S:.0f} s of the link loss (the first failing "
          "configuration poll clears configuration_online; the next watchdog tick ends it)", not v, str(v))
    att = dump_attempts(w, r["t_down"], r["t_up"])
    t_soc = last_ok_telemetry_t(w, r["t_down"])
    late = [e["t_utc"] for e in att if e["t_utc"] > t_soc + SOC_STALE_S]
    print(f"  info  FW-07-A {len(att)} restore attempts during the outage; gaps after the SOC went stale: {sorted(set(gaps(late)))}")
    check("FW-07-A INV-16 / SG-04 supervision: with 244 not proven out of Allow Export and the SOC stale (> 90 s), every "
          "watchdog tick retries the owed restore at once (never after a backoff)",
          len(late) >= 10 and late[0] <= t_soc + SOC_STALE_S + WD_S and set(gaps(late)) == {WD_S},
          f"{gaps(late)}")
    wr = [x for x in w.writes() if r["t_down"] < x["t_utc"] < r["t_up"]]
    check("FW-07-A: no inverter write is issued during the outage (a failed pre-read writes nothing)", not wr, str(wr))
    failed = [t for t, s in statuses(w, "dump", r["t_down"]) if s.startswith("RESTORE WRITE FAILED") and t < r["t_up"]]
    named = all(UNPROVEN in s for t, s in statuses(w, "dump", r["t_down"]) if s.startswith("RESTORE WRITE FAILED")
                and t < r["t_up"])
    check("FW-07-A SG-04: every failed-attempt status during the outage names the unproven 244 ('export may continue')",
          failed and named)
    done = completion_t(w, "dump", r["t_up"])
    lat = None if done is None else done - r["t_up"]
    print(f"  info  FW-07-A restore completed {lat} s after the link recovery (backoff then pending: "
          f"{BACKOFF_S[-1]} s)")
    rb = rebased_restore_bound(w, r["seq_up"], SG39_BOUND_S)
    check(f"FW-07-A INV-RESTORE-BOUND rebased at the link recovery (SG-39): the owed restore completes within "
          f"{SG39_BOUND_S:.0f} s although a {BACKOFF_S[-1]} s backoff was pending", lat is not None and not rb, str(rb))
    LAT["dump_07a"] = lat
    tel_up = [e["t_utc"] for e in evs(w, "fw.read", r["t_up"]) if e["data"]["addr"] == 150 and e["data"]["outcome"] == "ok"]
    att_up = [e["t_utc"] for e in dump_attempts(w, r["t_up"])]
    print(f"  info  FW-07-A after the recovery: first ok telemetry read +{tel_up[0] - r['t_up'] if tel_up else None} s, "
          f"first restore pre-read +{att_up[0] - r['t_up'] if att_up else None} s")
    check("FW-07-A: the recovery restore is the SG-39 path, not the no-fresh-SOC supervision: a telemetry read succeeded "
          "after the recovery before the restore pre-read, so the SOC was fresh again (above Stop SOC) and the every-tick "
          "supervision no longer applied (NC-FW07-1 shows the SG-39 clause is what runs it)",
          bool(tel_up) and bool(att_up) and tel_up[0] < att_up[0] and w.sim.ent("ecco_battery_soc").state > 25,
          f"{tel_up[:1]} {att_up[:1]}")
    check("FW-07-A: the restore wrote back the synthetic ORIGINAL and cleared the durable marker",
          w.status("dump").startswith("RESTORED OK") and w.nvs_marker("dump") == "CLEAR"
          and {a: w.bank[a] for a in DUMP_REGS} == {a: ORIG[a] for a in DUMP_REGS}, w.status("dump"))
    inv = w.invariants()
    check("FW-07-A core invariants (INV-WS, INV-ONE-LEASE, INV-NO-2ND-RESTORER, INV-NO-RESUME, INV-LOCKOUT-QUIET, "
          "INV-NO-SILENT-OVERRIDE, INV-RESTORE-BOUND explained by the link down) all hold", not inv, str(inv))
    p = run_07a(mode="telemetry_block", outage=150)
    v = inv17_violations(p, TL, SOC_STALE_S + TEL_S + WD_S)
    check(f"FW-07-A partial loss (only the telemetry block stops answering, configuration stays online): '{TL}' within "
          f"{SOC_STALE_S + TEL_S + WD_S:.0f} s (SOC freshness 90 s)", not v and not p["w"].invariants(),
          f"{v} {p['w'].invariants()}")
    c = run_07a(mode="polling_off", outage=250)
    t_cfg = [e["t_utc"] for e in evs(c["w"], "fw.read", None, c["t_down"]) if e["data"]["addr"] == 241
             and e["data"]["outcome"] == "ok"][-1]
    ends = statuses(c["w"], "dump_end", c["t_down"])
    check(f"FW-07-A configuration polling off during the lease: '{CRS}' within {CFG_STALE_S + WD_S:.0f} s of the last "
          "Block B sample (configuration_online stays true, so only the staleness monitor sees it)",
          bool(ends) and ends[0][1] == CRS and ends[0][0] - t_cfg <= CFG_STALE_S + WD_S and not c["w"].invariants(),
          f"{ends[:1]} last sample {t_cfg}")
    return r


# =============================================================================================================================
# FW-07-B  link down during the restore after 244 was proven
# =============================================================================================================================
def run_07b(fw=None, outage: float = 1000) -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(120)
    w.modbus_policy({"write:256": ["timeout_lost"]})   # 244 restored and verified, then the 256-261 write is lost
    t_end = w.t_utc
    end_status = w.dump_end()
    w.set_link(False)
    w.run_for(outage)
    t_up = w.t_utc
    unverified = w.sim.g["dump_export_unverified"]
    w.set_link(True)
    seq_up = len(w.log) - 1
    w.run_for(60)
    return {"w": w, "t_end": t_end, "t_up": t_up, "seq_up": seq_up, "end_status": end_status, "unverified": unverified}


def section_07b() -> dict:
    print("[2] FW-07-B link down during the restore after 244 was proven: comms backoff, SG-39 at recovery")
    r = run_07b()
    w = r["w"]
    check("FW-07-B: the END restored 244 (verified) and failed on the lost 256-261 write (comms path, obligation kept)",
          r["end_status"].startswith("RESTORE WRITE FAILED") and w.bank[244] == ORIG[244] and r["unverified"] is False,
          r["end_status"])
    ts = [e["t_utc"] for e in dump_attempts(w, r["t_end"], r["t_up"])]
    g = gaps(ts)
    exp = [q(b) for b in BACKOFF_S[1:]] + [q(BACKOFF_S[-1])] * max(0, len(g) - len(BACKOFF_S))
    print(f"  info  FW-07-B attempt gaps during the outage: {g}")
    check("FW-07-B INV-14: with 244 proven out of Allow Export (no supervision), retries follow the comms backoff "
          "15/30/60/120/300 s on the watchdog grid, then stay at 300 s",
          len(g) >= 5 and BACKOFF_S[0] <= g[0] < BACKOFF_S[0] + WD_S and g[1:] == exp[: len(g) - 1], f"{g} vs {exp}")
    done = completion_t(w, "dump", r["t_up"])
    rb = rebased_restore_bound(w, r["seq_up"], SG39_BOUND_S)
    print(f"  info  FW-07-B restore completed {None if done is None else done - r['t_up']} s after the link recovery")
    LAT["dump_07b"] = None if done is None else done - r["t_up"]
    check(f"FW-07-B SG-39: the failure was made while the link was down (no telemetry > {LINK_DOWN_S:.0f} s), so the "
          f"restore runs within {SG39_BOUND_S:.0f} s of the recovery instead of the remaining 300 s backoff",
          done is not None and not rb, str(rb))
    inv = w.invariants()
    check("FW-07-B core invariants hold (the delay is explained by the faults and the link down)", not inv, str(inv))
    return r


# =============================================================================================================================
# FW-07-C  reboot during an ACTIVE lease with the link down after boot
# =============================================================================================================================
def run_07c(fw=None, after_boot: float = 230) -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(120)
    rec_before = w.sim.g["dump_owed_stop_soc_rec"]
    end_epoch = w.sim.g["dump_end_epoch"]
    w.set_link(False)
    w.reboot(down_s=5)
    target_stop = w.sim.g["dump_target_stop_soc"]
    w.run_for(after_boot)
    ups = [e["up_ms"] / 1000 for e in dump_attempts(w, boot=1)]
    w.set_link(True)
    t_up = w.t_utc
    w.run_for(30)
    return {"w": w, "rec": rec_before, "end_epoch": end_epoch, "target_stop": target_stop, "ups": ups, "t_up": t_up}


def cadence_violations(ups: list, bound_up: float = SOC_STALE_S) -> list:
    """INV-16 after a restart with no fresh SOC: before `bound_up` s of uptime the backoff paces the retries; from the
    first watchdog tick after it, every tick retries (missing SOC counts as reached)."""
    early = [u for u in ups if u <= bound_up]
    late = [u for u in ups if u > bound_up]
    out = []
    if gaps(early) != [q(b) for b in BACKOFF_S[: max(0, len(early) - 1)]]:
        out.append(viol("INV-16", f"retries before {bound_up} s of uptime {early} do not follow the backoff"))
    if not late or late[0] > bound_up + WD_S or set(gaps(late)) - {WD_S}:
        out.append(viol("INV-16", f"retries after {bound_up} s of uptime {late[:8]} are not every watchdog tick"))
    return out


def section_07c() -> dict:
    print("[3] FW-07-C reboot during an ACTIVE lease, link down after boot: no-resume, 90 s no-fresh-SOC supervision")
    r = run_07c()
    w = r["w"]
    print(f"  info  FW-07-C restore attempt uptimes after the boot: {r['ups'][:8]} ...")
    check("FW-07-C: the boot ends the lease (not resumed: ESP RESTARTED DURING LEASE) and defers the restore to the watchdog",
          statuses(w, "dump_end")[-1][1] == ESPR and not w.invariants(["INV-NO-RESUME"]), str(statuses(w, "dump_end")))
    rec = r["rec"]
    check("FW-07-C: the lease's Stop SOC is RAM only (lost at the reboot) and the persisted owed record binds it to this "
          "obligation's end epoch ((end & 0xFFFFFF) << 8 | 25)",
          r["target_stop"] == -1 and rec >> 8 == (r["end_epoch"] & 0xFFFFFF) and rec & 0xFF == 25
          and w.sim.g["dump_owed_stop_soc_rec"] == rec, f"{r['target_stop']} {rec}")
    v = cadence_violations(r["ups"])
    check(f"FW-07-C INV-16: before {SOC_STALE_S:.0f} s of uptime the comms backoff paces the retries (15, 30, 60 s ...); "
          "from the first tick after it every watchdog tick retries (no fresh SOC counts as reached)", not v, str(v))
    done = completion_t(w, "dump", r["t_up"])
    check(f"FW-07-C: after the link recovery the owed restore completes within {SG39_BOUND_S:.0f} s and every core "
          "invariant holds", done is not None and done - r["t_up"] <= SG39_BOUND_S and not w.invariants(),
          f"{done} {w.invariants()}")
    return r


# =============================================================================================================================
# FW-07-D  reboot, inverter refuses 244 writes, fresh SOC: the owed Stop SOC governs
# =============================================================================================================================
def run_07d(fw=None) -> dict:
    w = world(fw)
    st = dump_lease(w, soc=50)
    w.run_for(60)
    w.owner_set_number("dump_stop_soc", 10)  # the owner lowers the CONFIGURED Stop SOC; the owed Stop SOC stays 25
    w.run_for(60)
    w.modbus_policy({"write:244": "error"})  # the inverter answers reads but refuses every 244 write
    w.reboot(down_s=5)
    t_boot = w.t_utc
    w.run_for(300)
    quiet = [e["up_ms"] / 1000 for e in dump_attempts(w, boot=1)]
    t_low = w.uptime_s
    w.telemetry(soc=24)
    w.run_for(120)
    low = [e["up_ms"] / 1000 for e in dump_attempts(w, boot=1) if e["up_ms"] / 1000 > t_low]
    return {"w": w, "start": st, "quiet": quiet, "low": low, "t_low": t_low, "cfg": w.sim.ent("dump_stop_soc").state,
            "t_boot": t_boot}


def stop_soc_violations(r) -> list:
    """INV-16 after a restart with a FRESH SOC: above the owed Stop SOC (25 %) the supervision stays quiet (the backoff
    paces the retries); at 24 % every watchdog tick retries (the configured 10 % would not trigger)."""
    out = []
    if gaps(r["quiet"]) != [q(b) for b in BACKOFF_S[: max(0, len(r["quiet"]) - 1)]] or len(r["quiet"]) < 4:
        out.append(viol("INV-16", f"SOC 50 % above the owed Stop SOC: retries {r['quiet']} do not follow the backoff"))
    if len(r["low"]) < 6 or r["low"][0] > r["t_low"] + WD_S or set(gaps(r["low"])) != {WD_S}:
        out.append(viol("INV-16", f"SOC 24 % at the owed Stop SOC 25 %: retries {r['low'][:8]} are not every tick"))
    return out


def section_07d() -> dict:
    print("[4] FW-07-D reboot, the inverter refuses 244 writes, fresh SOC: the persisted owed Stop SOC governs")
    r = run_07d()
    w = r["w"]
    print(f"  info  FW-07-D retries at SOC 50 % (uptime s): {r['quiet']}; at SOC 24 %: {r['low'][:6]} ...")
    v = stop_soc_violations(r)
    check("FW-07-D INV-16: after the restart the supervision uses the owed Stop SOC 25 % from dump_owed_stop_soc_rec "
          "(bound to this obligation), not the configured 10 %: quiet at 50 %, every tick at 24 %",
          r["cfg"] == 10 and not v, f"{r['cfg']} {v}")
    end_state = {a: w.bank[a] for a in DUMP_REGS}
    exp = {244: 0, **{a: 500 for a in range(256, 262)}}
    print(f"  info  FW-07-D end state: {end_state}; status: {w.status('dump')}")
    after = [s for _, s in statuses(w, "dump", r["t_boot"])]
    failed = [s for s in after if s.startswith("RESTORE WRITE FAILED")]
    deferred = [s for s in after if s == DEFER_BACKOFF]
    crit = [s for s in after if "CRITICAL" in s]
    print(f"  info  FW-07-D after the restart: {len(failed)} failed-attempt statuses (all name the 500 W floor: "
          f"{all(CONTAINED in s for s in failed)}), {len(deferred)} END DEFERRED (backoff) statuses, {len(crit)} CRITICAL")
    repro = (end_state == exp and w.nvs_marker("dump") == "RESTORE_REQUIRED" and CONTAINED in w.status("dump")
             and w.sim.g["dump_export_unverified"] is True and bool(failed) and all(CONTAINED in s for s in failed)
             and bool(deferred) and "244" not in DEFER_BACKOFF and not crit)
    if repro:
        finding("F-FW07-3", "FINDING-KNOWN:FCP2-R1 - after a restart, with the inverter refusing every 244 write, export "
                            "stays enabled (244 = 0); ECCO's own 256-261 are contained at the 500 W floor (its battery "
                            "discharge slots, not PV export); each failed attempt's status names it, but nothing is "
                            "CRITICAL on this comms path and the END DEFERRED status between backoff attempts does not "
                            "name 244; the obligation stays RESTORE_REQUIRED and the owed Stop SOC supervision retries "
                            "every tick at or below 25 %")
    check("finding-reproduces:F-FW07-3", repro, f"{end_state} {w.status('dump')} {len(failed)} {len(deferred)} {crit}")
    inv = w.invariants()
    check("FW-07-D core invariants hold (INV-NO-SILENT-OVERRIDE: the obligation stays visible; the delay is explained by "
          "the injected write faults)", not inv, str(inv))
    return r


# =============================================================================================================================
# FW-07-E  reboot with NTP invalid at early uptime
# =============================================================================================================================
def run_07e(fw=None, dom: str = "dump") -> dict:
    w = world(fw, warm=420, ntp_after_s=400)   # MODEL: the first NTP sync of every boot at uptime 400 s
    st = dump_lease(w) if dom == "dump" else w.fp_start(power_w=3000, minutes=30)
    w.run_for(120)
    w.reboot(down_s=5)
    t_boot = w.t_utc
    w.run_for(25)
    valid = w.sim.run_lambda("return id(ntp_time).now().is_valid();")
    return {"w": w, "start": st, "t_boot": t_boot, "valid": valid, "synced": w.sim.g["ntp_synced"]}


def section_07e() -> None:
    print("[5] FW-07-E reboot with NTP invalid at early uptime (first sync at 400 s): Dump no-resume, FP S3")
    for dom in ("dump", "fp"):
        r = run_07e(dom=dom)
        w = r["w"]
        done = completion_t(w, dom, r["t_boot"])
        lat = None if done is None else done - r["t_boot"] + BOOT_S
        print(f"  info  FW-07-E {dom}: restore completed at boot uptime {lat} s with the clock invalid")
        check(f"FW-07-E {dom}: the lease STARTed with a valid clock, then after the reboot the owed restore completes at the "
              f"first watchdog tick (uptime {WD_FIRST_S:.0f} s) while now() is still invalid - the {GRACE_S:.0f} s grace never "
              "applies (no-resume forced restore_requested)",
              r["start"].startswith("ACTIVE - VERIFIED OK") and lat is not None and lat <= WD_FIRST_S + 1
              and r["valid"] is False and r["synced"] is False, f"{r['start']} {lat} {r['valid']}")
        inv = w.invariants()
        check(f"FW-07-E {dom}: INV-NO-RESUME and every core invariant hold", not inv, str(inv))


# =============================================================================================================================
# FW-07-F  Free Power analogue: link down during the FP restore
# =============================================================================================================================
def run_07f(fw=None, outage: float = 1000) -> dict:
    w = world(fw)
    st = w.fp_start(power_w=3000, minutes=5)
    w.run_for(200)
    t_down = w.t_utc
    w.set_link(False)
    w.run_for(outage)
    t_up = w.t_utc
    w.set_link(True)
    seq_up = len(w.log) - 1
    w.run_for(400)
    return {"w": w, "start": st, "t_down": t_down, "t_up": t_up, "seq_up": seq_up}


def section_07f() -> dict:
    print("[6] FW-07-F Free Power analogue: link down during the FP restore, recovery")
    r = run_07f()
    w = r["w"]
    ts = [e["t_utc"] for e in fp_attempts(w, r["t_down"], r["t_up"])]
    g = gaps(ts)
    print(f"  info  FW-07-F FP restore attempt gaps during the outage: {g}")
    check("FW-07-F: FP restore retries during the outage follow the documented comms backoff 15-300 s (S4 row 37)",
          len(g) >= 5 and g[:4] == [q(b) for b in BACKOFF_S[:4]] and set(g[4:]) == {q(BACKOFF_S[-1])}, str(g))
    done = completion_t(w, "fp", r["t_up"])
    lat = None if done is None else done - r["t_up"]
    rb = rebased_restore_bound(w, r["seq_up"], SG39_BOUND_S)
    print(f"  info  FW-07-F FP restore completed {lat} s after the link recovery (Dump analogue: <= {SG39_BOUND_S:.0f} s)")
    repro = (done is not None and SG39_BOUND_S < lat <= q(BACKOFF_S[-1]) + FP_WD_S and len(rb) == 1
             and rb[0]["inv"] == "INV-RESTORE-BOUND" and "fp restore" in rb[0]["detail"])
    if repro:
        finding("F-FW07-1", f"Free Power has no SG-39 link-recovery retry: after a link outage long enough to reach the "
                            f"300 s backoff, the FP restore runs {lat:.0f} s after the link is back - the rest of the "
                            f"current backoff window - while the Dump restore runs within one watchdog tick + one "
                            f"telemetry poll by SG-39 ({LAT.get('dump_07a') or math.nan:.0f} s in FW-07-A, "
                            f"{LAT.get('dump_07b') or math.nan:.0f} s in FW-07-B); the override (232, 230, 256-261, "
                            f"268-279) stays meanwhile, no export")
    check("finding-reproduces:F-FW07-1", repro, f"{lat} {rb}")
    check("FW-07-F: the late FP restore still writes back the synthetic ORIGINAL and clears the marker; core invariants "
          "hold (the delay is explained by the link down)", w.status("fp").startswith("RESTORED OK")
          and w.nvs_marker("fp") == "CLEAR" and not w.invariants(), f"{w.status('fp')} {w.invariants()}")
    return r


# =============================================================================================================================
# FW-07-G  reboot while a restore is owed: the first end reason is overwritten
# =============================================================================================================================
def run_07g(fw=None) -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(120)
    w.set_link(False)
    w.run_for(80)
    before = w.status("dump_end")
    data = [e["data"]["rec"] for e in evs(w, "fw.commit") if e["data"]["key"] == L.TAGS["dump.data"]][-1]
    w.reboot(down_s=5)
    w.run_for(35)
    w.set_link(True)
    w.run_for(40)
    return {"w": w, "before": before, "data": data}


def section_07g() -> dict:
    print("[7] FW-07-G reboot while a restore is owed (the lease already ended): the end reason after the boot")
    r = run_07g()
    w = r["w"]
    hist = w.status_history("dump_end")
    print(f"  info  FW-07-G Last End Reason history: {hist}; durable data at the cut: active_persisted="
          f"{r['data']['active_persisted']} restore_requested={r['data']['restore_requested']}")
    repro = (r["before"] == TL and hist == [TL, ESPR] and r["data"]["active_persisted"] == 1
             and r["data"]["restore_requested"] == 1)
    if repro:
        finding("F-FW07-2", "a reboot while a Dump restore is owed (the lease had already ended: durable restore_requested "
                            "= 1, active_persisted still 1) makes the boot path publish Last End Reason 'ESP RESTARTED "
                            "DURING LEASE' - it misattributes the end of an already-ended lease to the restart (the "
                            "RAM-only first reason, here TELEMETRY LOST, cannot survive the reboot anyway); diagnostics only")
    check("finding-reproduces:F-FW07-2", repro, f"{r['before']} {hist} {r['data']}")
    check("FW-07-G: the owed restore still completes after the link recovery (only the diagnostic attribution is wrong); "
          "core invariants hold", w.status("dump").startswith("RESTORED OK") and not w.invariants(), str(w.invariants()))
    return r


# =============================================================================================================================
# FW-07-H  one failed configuration block read during an ACTIVE lease
# =============================================================================================================================
def run_07h(fw=None, key: str = "read:241x53", outcome: str = "no_response") -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(120)
    w.modbus_policy({key: [outcome]})   # ONE failed reply on ONE read; every other operation answers
    t0 = w.t_utc
    w.run_for(120)
    a, c = (int(x) for x in key[5:].split("x"))
    fail = [e["t_utc"] for e in evs(w, "fw.read", t0) if e["data"]["addr"] == a and e["data"]["count"] == c
            and e["data"]["outcome"] != "ok"]
    return {"w": w, "t0": t0, "ends": statuses(w, "dump_end", t0), "run": w.obligations()["dump"]["run"],
            "online": w.sim.ent("configuration_online").state, "t_fail": fail[0] if fail else None}


def section_07h() -> None:
    print("[8] FW-07-H one failed configuration block read during an ACTIVE Dump lease (every other op answers)")
    ended, kept, delays = [], [], set()
    for key in ("read:200x41", "read:241x53", "read:330x1"):
        for out in ("error", "no_response", "not_sent", "custom_response"):
            r = run_07h(key=key, outcome=out)
            fail_closed = (len(r["ends"]) == 1 and r["ends"][0][1] == TL and r["t_fail"] is not None
                           and 0 <= r["ends"][0][0] - r["t_fail"] <= WD_S
                           and not r["run"] and r["online"] is True and r["w"].status("dump").startswith("RESTORED OK")
                           and not r["w"].invariants())
            if fail_closed:
                ended.append((key, out))
                delays.add(r["ends"][0][0] - r["t_fail"])
            elif not r["ends"] and r["run"] and not r["w"].invariants():
                kept.append((key, out))
            else:
                check(f"FW-07-H {key} {out}: the run is either a fail-closed end or a kept lease", False, str(r["ends"]))
    t = run_07h(key="read:150x47", outcome="no_response")
    n = run_07h(key="read:241x53", outcome="timeout")
    print(f"  info  FW-07-H single failures that end the lease: {ended}; lease end after the failed read: "
          f"{sorted(delays)} s (the policy was installed "
          f"{None if r['t_fail'] is None else round(r['t_fail'] - r['t0'])} s before the failed read)")
    print(f"  info  FW-07-H single failures tolerated: {kept}; a single missed telemetry read: lease running={t['run']}; "
          f"a configuration read with no callback at all: lease running={n['run']}")
    exp = [(k, o) for k in ("read:200x41", "read:241x53") for o in ("error", "no_response", "not_sent", "custom_response")]
    exp += [("read:330x1", "error"), ("read:330x1", "no_response")]
    repro = ended == exp and kept == [("read:330x1", "not_sent"), ("read:330x1", "custom_response")] and t["run"] \
        and not t["ends"]
    if repro:
        finding("F-FW07-4", "one failed reply on ONE configuration read (Block A 200-240 or Block B 241-293: exception, "
                            "no response, not sent or non-standard; display-only Block C 330: exception or no response) "
                            "clears configuration_online, and the next Dump watchdog tick "
                            f"({'/'.join(f'{d:.0f}' for d in sorted(delays))} s after the failed read here) ends the "
                            "ACTIVE lease 'TELEMETRY LOST - failing closed' (configuration_online is back on at the next "
                            "poll); the 180 s configuration staleness bound applies only to skipped polls, and a single "
                            "missed telemetry read is tolerated; fail closed, explicit term, intent not stated publicly")
    check("finding-reproduces:F-FW07-4", repro, f"{ended} {kept} {t['ends']}")
    # Repair-direction probe (info only, no check): the in-memory variant without the configuration_online term, to state
    # the trade-off of repair (b) on measured behaviour rather than on the whole-monitor mutant NC-FW07-2.
    m = mutant([("return !soc_plausible || !soc_fresh || !id(configuration_online).state;",
                 "return !soc_plausible || !soc_fresh;")])
    if m is not None:
        single = run_07h(m)
        pb = world(m)
        dump_lease(pb)
        pb.run_for(120)
        t_b = pb.t_utc
        pb.modbus_policy({"read:241x53": "no_response"})   # persistent Block B failure
        pb.run_for(300)
        lk = run_07a(m)
        e_b = statuses(pb, "dump_end", t_b)
        e_l = statuses(lk["w"], "dump_end", lk["t_down"])
        print(f"  info  FW-07-H repair probe (configuration_online term removed): single Block B failure -> lease running="
              f"{single['run']}; persistent Block B failure -> {[(round(x - t_b), s) for x, s in e_b[:1]]}; link loss -> "
              f"{[(round(x - lk['t_down']), s) for x, s in e_l[:1]]} (original firmware: {TL!r} "
              f"{LAT.get('tl_07a')} s after the link loss, FW-07-A)")
    check("FW-07-H: every single-failure end is fail closed (the restore completes, the lease is not resumed when the "
          "configuration comes back) and every core invariant holds", len(ended) + len(kept) == 12
          and not t["w"].invariants() and not n["w"].invariants())


# =============================================================================================================================
# FW-07-I  frozen telemetry with the link up during an ACTIVE Dump lease, crossed with the restore and a reboot
# =============================================================================================================================
I_LEASE = {"power_w": 1000, "stop_soc": 25, "minutes": 60}
I_SOC_MINUTES = 120             # the 1500 Wh frozen-SOC count needs about 86 min at the synthetic 1050 W discharge
I_T0 = 68                       # first explicit telemetry action (at_s): 5 s before a poll slot (slots at at_s 3, 13, ...)
I_LIVE = 6                      # live slots: the CT changes once more after the 30 s grace (a properly seeded range)
I_FROZEN = 5                    # frozen actions: the last one precedes the earliest possible frozen end (a 5th
                                # identical read when the first frozen value equals the last live one), so a power
                                # cut at the end's restore never runs past a scheduled action
I_SOC_END_AT = 5260             # at_s of FW-07-i2's last action: after the frozen-SOC end, the cut and the boot restore
CT_WIN = ((FROZEN_N - 2) * TEL_S, (FROZEN_N - 1) * TEL_S + WD_S)   # 40-65 s after the first frozen poll read
SOC_T_EXP = SOC_FROZEN_WH * 3600 / L.SITE["dump_battery_w"]       # about 5143 s of 1050 W discharge after START
SOC_WIN = (SOC_T_EXP - TEL_S, SOC_T_EXP + TEL_S + WD_S)            # the count starts at START, one sample gap either way
NEW_LEASE_WIN = (RUNAWAY_GRACE_S + (FROZEN_N - 2) * TEL_S, RUNAWAY_GRACE_S + FROZEN_N * TEL_S + WD_S)  # 70-105 s after START


def frozen_schedule(signal: str, n_live: int, n_frozen: int, t0: int) -> list:
    """Explicit telemetry for consecutive 10 s poll slots of a noise=False world, as replay actions (the corpus form; one
    action 5 s before each slot, checked in [8a]). Before the freeze both readings move like the noise MODEL (grid CT
    -1000 / -1001 W, battery 1049 / 1050 / 1051 W); from slot n_live on the chosen signal repeats exactly while the other
    keeps moving: 'ct' - the CT holds -1000 W while the battery moves 200 W (1050 / 1250 W, inside every runaway, mean and
    cross-check threshold: the plant changed, the meter did not); 'bp' - the battery holds 1050 W while the CT moves 1 W;
    'seed' - the CT holds -1000 W (with n_live 0: the value it has read since the boot) while the battery moves 2 W."""
    out = []
    for k in range(n_live + n_frozen):
        g, b = -1000 - (k % 2), 1050 + (k % 3) - 1
        if k >= n_live:
            if signal == "ct":
                g, b = -1000, 1050 + 200 * (k % 2)
            elif signal == "bp":
                b = 1050
            elif signal == "seed":
                g = -1000
            else:
                raise L.LabHarnessError(f"frozen_schedule: unknown signal {signal!r}")
        out.append({"at_s": t0 + int(TEL_S) * k, "do": "telemetry", "args": {"poll": False, "grid_w": g, "batt_w": b}})
    return out


def i_actions(signal: str, cut: int | None, n_live: int = I_LIVE) -> list:
    """FW-07-I as replay actions (corpus FW-07-i is the ('ct', 256) list verbatim): the owner's START at at_s 60, a power
    cut armed at the next firmware write to `cut` (the restore's 244 or 256-261 write; None: no cut), the explicit
    schedule, then a run through the frozen end, the cut and the boot-path restore (a cut aborts the running action; the
    last action continues across it)."""
    acts = [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
            {"at_s": 60, "do": "dump_start", "args": dict(I_LEASE)}]
    if cut is not None:
        acts.append({"at_s": 60, "do": "arm_power_cut", "args": {"kind": "fw.write", "addr": cut}})
    acts += frozen_schedule(signal, n_live, I_FROZEN, I_T0)
    t_last = acts[-1]["at_s"]
    return acts + [{"at_s": t_last, "do": "run_for", "args": {"seconds": 60}},
                   {"at_s": t_last + 82, "do": "run_for", "args": {"seconds": 0}}]


def i_soc_actions() -> list:
    """FW-07-i2: the SOC never changes (no SOC physics) while the battery discharges about 1050 W (noise MODEL on); a power
    cut armed at the restore's 244 write."""
    return [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
            {"at_s": 60, "do": "dump_start", "args": dict(I_LEASE, minutes=I_SOC_MINUTES)},
            {"at_s": 60, "do": "arm_power_cut", "args": {"kind": "fw.write", "addr": 244}},
            {"at_s": I_SOC_END_AT, "do": "run_for", "args": {"seconds": 0}}]


def i_seed_actions(n_live: int, n_frozen: int) -> list:
    """F-FW07-5 (corpus FW-07-i3 is (0, 10)): the readings are set from at_s 0, so the CT reads -1000 W and the battery
    1050 W from the first poll on (no reading of 0 W ever); the CT then repeats from slot n_live on."""
    acts = [{"at_s": 0, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
            {"at_s": 60, "do": "dump_start", "args": dict(I_LEASE)}]
    acts += frozen_schedule("seed", n_live, n_frozen, I_T0)
    return acts + [{"at_s": acts[-1]["at_s"], "do": "run_for", "args": {"seconds": 30}}]


def play(w, actions: list, t_base: float) -> None:
    """Drive a world through replay-form actions the way the _lab_trace engine does: advance to t_base + at_s, then call
    the firmware tier's own ACTIONS entry (L.ACTIONS; no action is re-implemented here)."""
    for a in actions:
        w.advance_to(t_base + a["at_s"])
        L.ACTIONS[a["do"]](w, **a["args"])


def i_result(w, t_start: float, t_fa: float | None) -> dict:
    """What the FW-07-I checks read: the end statuses from START, the first poll read after the first frozen action
    (t_fa), the event the power cut fired at, and the log index of the first fw.booted after a cut."""
    log = list(w.log)
    reads = [] if t_fa is None else [e["t_utc"] for e in log if e["kind"] == "fw.read" and e["t_utc"] > t_fa
                                     and e["data"]["addr"] == 150 and e["data"]["outcome"] == "ok"]
    cuts = [e for e in log if e["kind"] == "cut.fired"]
    boots = [i for i, e in enumerate(log) if e["kind"] == "fw.booted" and e["boot"] >= 1]
    return {"w": w, "t_start": t_start, "t_freeze": reads[0] if reads else t_start if t_fa is None else None,
            "ends": statuses(w, "dump_end", t_start), "cut": log[cuts[0]["data"]["seq"]] if cuts else None,
            "boot_seq": boots[0] if boots else None,
            "started": any(s.startswith("ACTIVE - VERIFIED OK") for _, s in statuses(w, "dump", t_start))}


def run_07i(fw=None, signal: str = "ct", cut: int | None = 256, n_live: int = I_LIVE) -> dict:
    w = world(fw, noise=False)      # MODEL: the noise MODEL is a world switch; every slot's CT / battery is set explicitly
    acts = i_actions(signal, cut, n_live)
    play(w, acts, U0)
    return dict(i_result(w, U0 + 60, U0 + I_T0 + int(TEL_S) * n_live), actions=acts)


def run_07i_soc(fw=None, cut: int | None = 244) -> dict:
    w = world(fw)                   # the noise MODEL on (CT and battery move 1 W); the SOC stays at the synthetic 70 %
    st = dump_lease(w, minutes=I_SOC_MINUTES)
    t_start = w.t_utc
    if cut is not None:
        w.arm_power_cut(kind="fw.write", addr=cut)
    # whole seconds: run_until compares against a float limit that a ms clock may never reach exactly
    run_until(w, lambda: bool(statuses(w, "dump_end", t_start)), math.ceil(SOC_WIN[1]) + 30, step=60)
    run_until(w, lambda: restored(w, "dump"), 120)
    return dict(i_result(w, t_start, None), start=st)


def run_07i_after(fw=None) -> dict:
    """The frozen end and its restore complete (no cut); a reboot about 60 s later with the CT still frozen; then the owner
    presses START again and the CT keeps repeating -1000 W (the battery moves 200 W)."""
    w = world(fw, noise=False)
    play(w, i_actions("ct", None), U0)
    r1 = i_result(w, U0 + 60, U0 + I_T0 + int(TEL_S) * I_LIVE)
    hist1 = w.status_history("dump_end")
    w.reboot(down_s=5)
    w.run_for(40)
    quiet = {"writes": [x for x in w.writes() if x["boot"] == 1], "attempts": dump_attempts(w, boot=1),
             "hist": w.status_history("dump_end"), "status": w.status("dump"),
             "booted": [e["data"]["obl"] for e in w.log.events(kind="fw.booted") if e["boot"] == 1]}
    t2 = w.t_utc
    st2 = w.dump_start(**I_LEASE)
    slot = [e["t_utc"] for e in evs(w, "fw.read", None, None, boot=1) if e["data"]["addr"] == 150][-1]
    t0 = slot + TEL_S / 2
    while t0 <= w.t_utc:
        t0 += TEL_S
    play(w, frozen_schedule("ct", 0, 12, 0), t0)
    w.run_for(30)
    return {"w": w, "r1": r1, "hist1": hist1, "quiet": quiet, "t2": t2, "st2": st2,
            "r2": {"ends": statuses(w, "dump_end", t2), "t_start": t2}}


def frozen_end_violations(r, prefix: str, lo_s: float, hi_s: float, t_ref: str = "t_freeze") -> list:
    """INV-17 (frozen telemetry, link up): the ACTIVE lease ends with the firmware's frozen-telemetry reason `prefix`
    between lo_s and hi_s after r[t_ref] (the first frozen poll read; the START for the frozen-SOC count)."""
    want = f"{prefix.rstrip(' -')!r} {lo_s:.0f}-{hi_s:.0f} s after {'the freeze' if t_ref == 't_freeze' else 'START'}"
    if not r["ends"]:
        return [viol("INV-17", f"the lease never ended (expected {want})")]
    t, text = r["ends"][0]
    d = None if r.get(t_ref) is None else t - r[t_ref]
    if not text.startswith(prefix) or d is None or not lo_s <= d <= hi_s:
        return [viol("INV-17", f"the lease ended {d} s after the reference with {text[:70]!r} (expected {want})")]
    return []


def misaligned(w, actions: list, t_base: float) -> list:
    """Explicit telemetry actions that share an instant with a poll slot, or that are not followed by exactly one poll
    slot before the next action (either would make the reading depend on the scheduler's same-instant ordering)."""
    reads = [e["t_utc"] for e in w.log if e["kind"] == "fw.read" and e["data"]["addr"] == 150]
    ts = [t_base + a["at_s"] for a in actions if a["do"] == "telemetry" and a["args"].get("poll") is False]
    return [(ta - t_base, n) for ta, tb in zip(ts, ts[1:] + [ts[-1] + TEL_S])
            for n in [sum(1 for x in reads if ta < x < tb)] if ta in reads or n != 1]


def link_failures(w, t0, t1) -> list:
    return [e for e in evs(w, "fw.read", t0, t1) if e["data"]["outcome"] != "ok"]


def crossing_checks(tag: str, r, cut_addr: int) -> None:
    """The restore after a frozen end is cut short by a power cut at its write to cut_addr; the boot mirrors the stored
    obligation, does not resume, and its restore completes at the first watchdog tick with the reading still frozen."""
    w, cut = r["w"], r["cut"]
    pre = [s for t, s in statuses(w, "dump") if cut is not None and t <= cut["t_utc"]]
    check(f"FW-07-I {tag}: the power cut fired at the Dump restore's write to {cut_addr} (status RESTORING, in the "
          "watchdog tick of the frozen end)", cut is not None and cut["kind"] == "fw.write" and cut["boot"] == 0
          and cut["data"]["addr"] == cut_addr and cut["data"]["dom"] == "dump" and bool(pre)
          and pre[-1].startswith("RESTORING") and bool(r["ends"]) and r["ends"][0][0] == cut["t_utc"],
          f"{cut and cut['data'].get('addr')} {pre[-1:]} {r['ends'][:1]}")
    b = r["boot_seq"]
    booted = None if b is None else list(w.log)[b]
    o = None if booted is None else booted["data"]["obl"]
    check(f"FW-07-I {tag} INV-BOOT-MIRROR (non-vacuous) and INV-NO-RESUME: at the boot the stored Dump marker is "
          "RESTORE_REQUIRED, the RAM snapshot mirrors it and the boot requests the restore instead of resuming the lease",
          o is not None and o["nvs"]["dump"] == "RESTORE_REQUIRED" and o["dump"]["snap"] and o["dump"]["req"]
          and not o["dump"]["run"] and not w.invariants(["INV-BOOT-MIRROR"]) and not w.invariants(["INV-NO-RESUME"]),
          f"{o and o['nvs']} {o and o['dump']}")
    done = None if booted is None else completion_t(w, "dump", booted["t_utc"])
    rb = [viol("INV-RESTORE-BOUND", "no boot")] if b is None else rebased_restore_bound(w, b, WD_FIRST_S)
    print(f"  info  FW-07-I {tag}: boot-path restore complete {None if done is None else done - booted['t_utc']} s after "
          f"the boot event")
    check(f"FW-07-I {tag} INV-RESTORE-BOUND rebased at the boot (strict: the power cut lies before the window): the "
          f"boot-path restore completes within {WD_FIRST_S:.0f} s, the frozen reading notwithstanding",
          done is not None and not rb, f"{done} {rb}")
    names = ("INV-RESTORE-BOUND", "INV-NO-RESUME", "INV-NO-SILENT-OVERRIDE", "INV-BOOT-MIRROR")
    bad = {n: w.invariants([n]) for n in names}
    check(f"FW-07-I {tag}: {', '.join(names)} and every other core invariant hold over the whole run; the restore wrote "
          "back the synthetic ORIGINAL and cleared the durable marker", not any(bad.values()) and not w.invariants()
          and w.status("dump").startswith("RESTORED OK") and w.nvs_marker("dump") == "CLEAR" and w.boot_no == 1
          and {a: w.bank[a] for a in DUMP_REGS} == {a: ORIG[a] for a in DUMP_REGS}, f"{bad} {w.status('dump')}")


def moved_w(text: str):
    m = re.search(r"while the battery moved (-?\d+)W", text)
    return None if m is None else int(m.group(1))


def same_reads(text: str):
    m = re.search(r" - (\d+) identical readings of ", text)
    return None if m is None else int(m.group(1))


def section_07i() -> dict:
    print("[8a] FW-07-I frozen telemetry with the link up during an ACTIVE Dump lease: end, restore, power cut, reboot")
    out = {}
    # (1) grid CT frozen while the battery moves 200 W; power cut at the restore's 256-261 write
    r = out["ct"] = run_07i(signal="ct", cut=256)
    w = r["w"]
    bad = misaligned(w, r["actions"], U0)
    check("FW-07-I: every explicit telemetry action lies strictly between two poll slots, with exactly one poll slot "
          "before the next action (no same-instant ordering dependence); the lease STARTs ACTIVE", not bad and r["started"],
          str(bad))
    t_end = r["ends"][0][0] if r["ends"] else None
    if r["ends"]:
        print(f"  info  FW-07-I ct: lease end {t_end - r['t_freeze']:.0f} s after the first frozen read: {r['ends'][0][1]}")
    v = frozen_end_violations(r, CTF, *CT_WIN)
    mv = moved_w(r["ends"][0][1]) if r["ends"] else None
    check(f"FW-07-I ct INV-17: with the link up (every Modbus read from START to the end answered ok) a grid CT repeating "
          f"-1000 W while the battery moves 200 W ends the lease '{CTF.rstrip(' -')}' {CT_WIN[0]:.0f}-{CT_WIN[1]:.0f} s after "
          f"the first frozen read ({FROZEN_N} identical reads; the battery range > {FROZEN_CROSS_W} W comes from the "
          "readings during the repeats: 200 W)", not v and not link_failures(w, r["t_start"], t_end)
          and mv is not None and FROZEN_CROSS_W < mv <= 202, f"{v} {mv}")
    crossing_checks("ct", r, 256)
    check("finding-reproduces:F-FW07-2", w.status_history("dump_end") == [r["ends"][0][1] if r["ends"] else None, ESPR],
          str(w.status_history("dump_end")))
    # (2) battery power frozen while the CT moves 1 W; power cut at the restore's 244 write (landed, not yet verified)
    r = out["bp"] = run_07i(signal="bp", cut=244)
    t_end = r["ends"][0][0] if r["ends"] else None
    if r["ends"]:
        print(f"  info  FW-07-I bp: lease end {t_end - r['t_freeze']:.0f} s after the first frozen read: {r['ends'][0][1]}")
    v = frozen_end_violations(r, BPF, *CT_WIN)
    check(f"FW-07-I bp INV-17: with the link up a battery power reading repeating 1050 W while the CT moves 1 W ends the "
          f"lease '{BPF.rstrip(' -')}' {CT_WIN[0]:.0f}-{CT_WIN[1]:.0f} s after the first frozen read",
          not v and not link_failures(r["w"], r["t_start"], t_end) and r["started"], str(v))
    crossing_checks("bp", r, 244)
    # (3) stale-but-plausible SOC: fresh every 10 s, 70 % (above Stop SOC), never changing while about 1 kW discharges
    r = out["soc"] = run_07i_soc()
    t_end = r["ends"][0][0] if r["ends"] else None
    if r["ends"]:
        print(f"  info  FW-07-I soc: lease end {t_end - r['t_start']:.0f} s after START (expected about {SOC_T_EXP:.0f} s): "
              f"{r['ends'][0][1]}")
    v = frozen_end_violations(r, SOCF, *SOC_WIN, t_ref="t_start")
    check(f"FW-07-I soc INV-17: a SOC that stays fresh and plausible ({L.SITE['soc']} %, above the 25 % Stop SOC: the 90 s "
          f"freshness check cannot see it) but never changes while the battery discharges {L.SITE['dump_battery_w']} W "
          f"ends the lease '{SOCF.rstrip(' -')}' once {SOC_FROZEN_WH} Wh are counted ({SOC_WIN[0]:.0f}-{SOC_WIN[1]:.0f} s "
          "after START; the link up throughout)", not v and r["started"] and not link_failures(r["w"], r["t_start"], t_end)
          and bool(r["ends"]) and f"(still {L.SITE['soc']}%)" in r["ends"][0][1], str(v))
    crossing_checks("soc", r, 244)
    done = completion_t(r["w"], "dump", r["t_start"])
    check("FW-07-I soc: corpus FW-07-i2's last action (at_s I_SOC_END_AT) comes after the boot-path restore",
          done is not None and done < U0 + I_SOC_END_AT, f"{None if done is None else done - U0}")
    # (4) a reboot after the completed restore, then a new START on the still-frozen CT
    a = out["after"] = run_07i_after()
    w, r1, qz = a["w"], a["r1"], a["quiet"]
    e1 = r1["ends"][0][0] if r1["ends"] else None
    d1 = None if e1 is None else completion_t(w, "dump", e1)
    check("FW-07-I after: the frozen end's restore completes in the same watchdog tick (no cut); INV-RESTORE-BOUND holds "
          "unexplained (no fault, link up)", not frozen_end_violations(r1, CTF, *CT_WIN) and d1 is not None
          and d1 - e1 <= 1 and not w.invariants(["INV-RESTORE-BOUND"]), f"{r1['ends'][:1]} {d1}")
    check("FW-07-I after: a reboot after the completed restore (the CT still frozen) owes nothing and resumes nothing: "
          "the stored marker is CLEAR at the boot, no restore attempt and no write follow, the end reason is not "
          "re-attributed (INV-NO-RESUME, INV-BOOT-MIRROR)",
          len(qz["booted"]) == 1 and qz["booted"][0]["nvs"]["dump"] == "CLEAR" and not qz["booted"][0]["dump"]["snap"]
          and not qz["writes"] and not qz["attempts"] and qz["hist"] == a["hist1"]
          and not w.invariants(["INV-NO-RESUME"]) and not w.invariants(["INV-BOOT-MIRROR"]),
          f"{qz['booted']} {len(qz['writes'])} {len(qz['attempts'])} {qz['hist']}")
    v2 = frozen_end_violations(a["r2"], CTF, *NEW_LEASE_WIN, t_ref="t_start")
    if a["r2"]["ends"]:
        print(f"  info  FW-07-I after: the new lease ends {a['r2']['ends'][0][0] - a['t2']:.0f} s after its START: "
              f"{a['r2']['ends'][0][1]}")
    check(f"FW-07-I after: the owner's new START on the still-frozen CT is accepted (START checks freshness, not "
          f"repeats) and the detector re-arms from the new lease's own evidence: '{CTF.rstrip(' -')}' "
          f"{NEW_LEASE_WIN[0]:.0f}-{NEW_LEASE_WIN[1]:.0f} s after START (30 s grace + {FROZEN_N} reads); the reboot "
          "launders nothing; restore complete, every core invariant holds",
          a["st2"].startswith("ACTIVE - VERIFIED OK") and not v2 and w.status("dump").startswith("RESTORED OK")
          and not w.invariants(), f"{a['st2'][:40]} {v2} {w.invariants()}")
    return out


# =============================================================================================================================
# FW-07-I / F-FW07-5  the fast frozen-CT criterion on a battery range from outside the repeat window
# =============================================================================================================================
def run_07i_seed(fw=None, n_live: int = 0, n_frozen: int = 10) -> dict:
    w = world(fw, warm=0, noise=False)
    acts = i_seed_actions(n_live, n_frozen)
    play(w, acts, U0)
    ends = statuses(w, "dump_end", U0 + 60)
    return {"w": w, "ends": ends, "g": w.globals_view(["dump_ct_same_bmin", "dump_ct_same_bmax"]), "actions": acts}


def run_07i_carry(fw=None) -> dict:
    """Lease 1 (1000 W) with a live CT, ended by the owner; lease 2 (2000 W) STARTs while the CT already repeats -2000 W
    and the battery is steady at 2049 / 2050 / 2051 W."""
    w = world(fw, warm=0, noise=False)
    play(w, [{"at_s": 0, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
             {"at_s": 60, "do": "dump_start", "args": dict(I_LEASE)}] + frozen_schedule("ct", I_LIVE, 0, I_T0)
         + [{"at_s": 120, "do": "dump_end", "args": {}},
            {"at_s": 128, "do": "telemetry", "args": {"poll": False, "grid_w": -2000, "batt_w": 2050}},
            {"at_s": 150, "do": "dump_start", "args": dict(I_LEASE, power_w=2000)}], U0)
    lease2 = frozen_schedule("seed", 0, 12, 158)        # the CT repeats -2000 W; the battery 2049 / 2050 / 2051 W
    play(w, [dict(a, args=dict(a["args"], grid_w=-2000, batt_w=a["args"]["batt_w"] + 1000)) for a in lease2], U0)
    w.run_for(30)
    return {"w": w, "ends": statuses(w, "dump_end", U0 + 150), "g": w.globals_view(["dump_ct_same_bmin",
                                                                                     "dump_ct_same_bmax"])}


MUT_CT_RANGE_SEED = [("id(dump_ct_same_count) = 0;\n                              id(dump_bp_same_count) = 0;",
                      "id(dump_ct_same_count) = 0;\n                              id(dump_ct_same_bmin) = 1000000000.0f;\n"
                      "                              id(dump_ct_same_bmax) = -1000000000.0f;\n"
                      "                              id(dump_bp_same_count) = 0;")]


def section_07i_seed() -> None:
    print("[8b] FW-07-I F-FW07-5: a CT already repeating at START, a steady battery: which frozen-CT criterion ends it")
    a = run_07i_seed()
    b = run_07i_seed(n_live=I_LIVE, n_frozen=FROZEN_LONG_N + 2)
    c = run_07i_carry()
    for tag, r in (("CT repeating since the boot", a), ("CT changing after the grace, then repeating", b),
                   ("CT repeating across the second lease's START", c)):
        print(f"  info  F-FW07-5 {tag}: {r['ends'][:1]}; range {r['g']}")
    ta, tb, tc = (r["ends"][0][1] if r["ends"] else "" for r in (a, b, c))
    check("F-FW07-5 control (the documented criteria hold when the range is seeded inside the lease): a CT that changed "
          f"after the grace and then repeats with a steady battery (2 W) ends only by the slow criterion, after "
          f"{FROZEN_LONG_N} identical reads, and the end text names the 2 W the battery really moved",
          tb.startswith(CTF) and same_reads(tb) == FROZEN_LONG_N and moved_w(tb) == 2 and not b["w"].invariants(), tb)
    repro = (ta.startswith(CTF) and same_reads(ta) is not None and same_reads(ta) <= FROZEN_N + 1
             and moved_w(ta) == 1051 and a["g"]["dump_ct_same_bmin"] == 0.0
             and tc.startswith(CTF) and same_reads(tc) is not None and same_reads(tc) <= FROZEN_N + 1
             and moved_w(tc) is not None and moved_w(tc) > FROZEN_CROSS_W and 1049 <= c["g"]["dump_ct_same_bmin"] <= 1051
             and not a["w"].invariants() and not c["w"].invariants())
    if repro:
        finding("F-FW07-5", "the battery range of the fast frozen-CT criterion (dump_ct_same_bmin / bmax) is re-seeded only "
                            "when the CT changes inside a settled lease - never at START ('fresh frozen-telemetry "
                            "evidence' resets only the count) and never outside a lease - so a CT that already repeats at "
                            "START meets '6 identical reads while the battery moved > 150 W' on battery values from "
                            f"outside the repeat window: with a steady battery (2 W) the lease ends after "
                            f"{same_reads(ta)} reads instead of the documented {FROZEN_LONG_N}-read slow criterion, the "
                            f"end text reporting 'the battery moved {moved_w(ta)}W' (the boot value 0 W of the range, never "
                            f"a reading) or {moved_w(tc)} W (the previous lease's readings); fail closed (earlier end), "
                            "diagnostics")
    check("finding-reproduces:F-FW07-5", repro, f"{ta[:80]} {a['g']} | {tc[:80]} {c['g']}")
    # Repair-direction probe (info only, no check): the range seeded empty at START, as the CT hook's own re-seed does.
    m = mutant(MUT_CT_RANGE_SEED)
    if m is not None:
        ra = run_07i_seed(m, n_frozen=FROZEN_LONG_N + 2)
        print(f"  info  F-FW07-5 repair probe (range seeded empty at START): CT repeating since the boot -> "
              f"{ra['ends'][:1]}")


# =============================================================================================================================
# FW-08-A  single-op Modbus outcome sweep for lock leaks
# =============================================================================================================================
def _prep(kind: str):
    w = world()
    if kind.startswith("dump"):
        w.telemetry(grid_w=L.SITE["dump_grid_w"], batt_w=L.SITE["dump_battery_w"])
    if kind == "dump_end":
        w.dump_start(power_w=1000, stop_soc=25, minutes=60)
        w.run_for(30)
    if kind == "fp_end":
        w.fp_start(power_w=3000, minutes=30)
        w.run_for(30)
    return w


def _act(w, kind: str) -> str:
    if kind == "dump_start":
        return w.dump_start(power_w=1000, stop_soc=25, minutes=60)
    if kind == "dump_end":
        return w.dump_end()
    if kind == "fp_start":
        return w.fp_start(power_w=3000, minutes=30)
    if kind == "fp_end":
        return w.fp_end()
    if kind.startswith("manual"):
        return w.manual_slot_apply(int(kind[6:]), soc=55)
    raise L.LabHarnessError(kind)


def held_locks(w) -> list:
    o = w.obligations()
    return [n for n, v in (("manual_write_in_progress", o["mw"]), ("dump_operation_in_progress", o["dump"]["op"]),
                           ("free_power_operation_in_progress", o["fp"]["op"]),
                           ("reg244_apply_in_progress", o["r244"]["op"])) if v]


def leak_sweep(kinds) -> tuple[int, list, dict]:
    n, leaks, ops_by = 0, [], {}
    for kind in kinds:
        w = _prep(kind)
        n0 = len(w.log)
        _act(w, kind)
        ops = [(e["kind"][3:], e["data"]["addr"], e["data"]["count"] if e["kind"] == "fw.read" else len(e["data"]["vals"]))
               for e in list(w.log)[n0:] if e["kind"] in ("fw.read", "fw.write")]
        ops_by[kind] = ops
        for i, (k, a, c) in enumerate(ops):
            prior = sum(1 for o in ops[:i] if o == (k, a, c))
            for out in (L.WRITE_OUTCOMES if k == "write" else L.READ_OUTCOMES):
                if out == "ok":
                    continue
                w = _prep(kind)
                w.modbus_policy({f"{k}:{a}x{c}": ["ok"] * prior + [out]})
                _act(w, kind)
                n += 1
                h = held_locks(w)
                if h:
                    leaks.append((kind, i, f"{k}:{a}x{c}", out, h))
    return n, leaks, ops_by


def section_08a() -> None:
    print("[9] FW-08-A single-op Modbus outcome sweep over the lock-taking scripts (every allow-listed non-ok outcome)")
    kinds = ["dump_start", "dump_end", "fp_start", "fp_end", "manual2"]
    if EXTENDED:
        kinds += ["manual1", "manual3", "manual4", "manual5", "manual6"]
    t_sweep = time.perf_counter()
    n, leaks, ops_by = leak_sweep(kinds)
    if EXTENDED:
        print(f"  info  EXT FW-08-A sweep over {len(kinds)} scripts runtime_s {time.perf_counter() - t_sweep:.3f}")
    for k in kinds:
        print(f"  info  FW-08-A {k}: {len(ops_by[k])} Modbus ops")
    print(f"  info  FW-08-A {n} faulted runs; leaks: {leaks}")
    lease = [x for x in leaks if not x[0].startswith("manual")]
    check("FW-08-A: no single non-ok Modbus outcome on any op of Dump START / END(restore) or Free Power START / "
          "END(restore) leaves a transaction lock held (every step has its bounded wait or a releasing handler)",
          n > 150 and not lease, str(lease))
    man = [x for x in leaks if x[0].startswith("manual")]
    exp = []
    for k in kinds:
        if k.startswith("manual"):
            i = next(j for j, o in enumerate(ops_by[k]) if o[0] == "read" and o[1] == 250 and o[2] >= 25)
            exp.append((k, i, f"read:250x{ops_by[k][i][2]}", "timeout", ["manual_write_in_progress"]))
    check("FW-08-A documented behaviour (write-surface.md: the manual TOU verify read has no bounded wait_until): exactly "
          "one leaking case per slot - the 30-register verify read with no callback at all ('timeout') leaves "
          "manual_write_in_progress held", man == exp, f"{man} vs {exp}")
    w = world()
    w.modbus_policy({"read:250x30": ["timeout"]})
    w.manual_slot_apply(2, soc=55)
    t_leak = w.t_utc
    w.run_for(100)
    refused = dump_lease(w)
    w.run_for(150)
    tel = [e for e in evs(w, "fw.read", t_leak) if e["data"]["addr"] == 150]
    check("FW-08-A: the leaked manual lock is never released by time; the lock-age monitor reports STUCK LOCK (nothing is "
          "owed: the manual apply refuses whenever a lease or restore is owed, so no lease can be under it) without a "
          "restart; a Dump START is refused; the telemetry poll stays paused",
          held_locks(w) == ["manual_write_in_progress"] and w.text_state("ecco_restart_status") == STUCK_NOTHING
          and w.boot_no == 0 and refused == REJ_LOCK and not tel and not w.invariants(),
          f"{held_locks(w)} {w.text_state('ecco_restart_status')} {refused} {len(tel)}")


# =============================================================================================================================
# FW-08-B..F  white-box lock leaks (MODEL)
# =============================================================================================================================
def escalation_violations(w, t_leak, dom: str) -> list:
    """INV-20: a lock held beyond the stuck bound with an owed lease / restore makes the firmware restart within
    STUCK + 2 census periods of the leak, and the boot path completes the owed restore at its first watchdog tick."""
    lim_restart = STUCK_S + 2 * CENSUS_S
    lim_done = lim_restart + RESTART_DOWN_S + WD_FIRST_S + 1
    rs = evs(w, "fw.restart", t_leak)
    done = completion_t(w, dom, t_leak)
    out = []
    if not rs or rs[0]["t_utc"] - t_leak > lim_restart:
        out.append(viol("INV-20", f"no firmware restart within {lim_restart} s of the leak ({[e['t_utc'] for e in rs]})"))
    if done is None or done - t_leak > lim_done:
        out.append(viol("INV-20", f"{dom} restore not complete within {lim_done} s of the leak (done {done})"))
    return out


def run_08b(fw=None, offset_s: float = -5, wd_order=("fp", "dump")) -> dict:
    w = world(fw)
    st = dump_lease(w, minutes=5)
    end = w.obligations()["dump"]["end"]
    w.run_for(end + offset_s - w.t_utc, wd_order=wd_order)
    w.inject_global("manual_write_in_progress", True)  # MODEL: a leaked shared write mutex (logged fault.ram)
    t_leak = w.t_utc
    run_until(w, lambda: restored(w, "dump"), 420)
    w.run_for(30, wd_order=wd_order)
    return {"w": w, "start": st, "end": end, "t_leak": t_leak}


def section_08b() -> dict:
    print("[10] FW-08-B manual_write_in_progress leaked 5 s before the Dump lease end (MODEL leak)")
    r = run_08b()
    w, t_leak = r["w"], r["t_leak"]
    rs = evs(w, "fw.restart", t_leak)
    done = completion_t(w, "dump", t_leak)
    pre = dump_attempts(w, t_leak, rs[0]["t_utc"] if rs else None)
    ends = statuses(w, "dump_end", t_leak)
    print(f"  info  FW-08-B restart {rs[0]['t_utc'] - t_leak if rs else None} s after the leak, restore complete "
          f"{None if done is None else done - t_leak} s after it; end reasons {[x[1][:24] for x in ends]}")
    check("FW-08-B: the leaked lock blocks the DURATION EXPIRED request and every restore attempt (no pre-read before "
          "the restart); the status says END DEFERRED (another inverter write) after the lease monitors end it",
          not pre and ends and ends[0][1] == TL and any(s == DEFER_LOCK for _, s in statuses(w, "dump", t_leak)),
          f"{len(pre)} {ends[:1]}")
    v = escalation_violations(w, t_leak, "dump")
    check(f"FW-08-B INV-20: the stuck lock (> {STUCK_S:.0f} s) escalates on a quiet bus: the firmware presses its own "
          f"restart within {STUCK_S + 2 * CENSUS_S:.0f} s and the boot path restores at its first watchdog tick",
          not v and rs and rs[0]["data"]["button"] == "ecco_restart_internal" and w.boot_no == 1, str(v))
    inv = w.invariants()
    check("FW-08-B core invariants hold: INV-NO-RESUME (the boot ends the lease), INV-RESTORE-BOUND (explained by the held "
          "lock), INV-WS, INV-NO-SILENT-OVERRIDE", not inv, str(inv))
    check("finding-reproduces:F-FW07-2", w.status_history("dump_end")[-2:] == [TL, ESPR],
          str(w.status_history("dump_end")))
    return r


def run_08c(fw=None) -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(30)
    w.inject_global("dump_operation_in_progress", True)  # MODEL: a leaked Dump operation flag (logged fault.ram)
    t_leak = w.t_utc
    w.run_for(20)
    w.telemetry(soc=24)                                 # the SOC falls below the lease's Stop SOC 25 %
    t_low = w.t_utc
    run_until(w, lambda: restored(w, "dump"), 420)
    return {"w": w, "t_leak": t_leak, "t_low": t_low}


def section_08c() -> None:
    print("[11] FW-08-C leaked Dump operation flag during an ACTIVE lease, SOC below Stop SOC (MODEL leak)")
    r = run_08c()
    w, t_leak = r["w"], r["t_leak"]
    ends = statuses(w, "dump_end", t_leak)
    done = completion_t(w, "dump", t_leak)
    print(f"  info  FW-08-C end reasons {[x[1][:24] for x in ends]}; Stop SOC overrun {None if done is None else done - r['t_low']} s")
    check("FW-08-C documented gap bound (fcp2 section 6): the leaked flag suspends the lease monitors (STOP SOC REACHED is "
          "not acted on); the escalation ends the lease durably with WRITE LOCK STUCK (its step 1)",
          bool(ends) and ends[0][1] == WLS, str(ends[:1]))
    v = escalation_violations(w, t_leak, "dump")
    check("FW-08-C INV-20: restart and boot restore within the escalation bound; the Stop SOC overrun is bounded by it",
          not v and done is not None and done - r["t_low"] <= STUCK_S + 2 * CENSUS_S + RESTART_DOWN_S + WD_FIRST_S + 1,
          str(v))
    check("FW-08-C core invariants hold", not w.invariants(), str(w.invariants()))
    check("finding-reproduces:F-FW07-2", w.status_history("dump_end")[-2:] == [WLS, ESPR],
          str(w.status_history("dump_end")))


def run_08d(fw=None) -> dict:
    w = world(fw)
    st = w.fp_start(power_w=3000, minutes=30)
    w.run_for(30)
    w.inject_global("manual_write_in_progress", True)   # MODEL (logged fault.ram)
    t_leak = w.t_utc
    run_until(w, lambda: restored(w, "fp"), 420)
    return {"w": w, "start": st, "t_leak": t_leak}


def section_08d() -> None:
    print("[12] FW-08-D Free Power analogue: lock leaked during an FP lease (MODEL leak)")
    r = run_08d()
    w = r["w"]
    v = escalation_violations(w, r["t_leak"], "fp")
    hist = w.status_history("fp")
    check("FW-08-D INV-20: the FP lease owes a restore, so the stuck lock restarts the device; the boot path's S3 turns the "
          "active lease into a restore request (ACTIVE - reboot recovery pending) and the FP watchdog restores",
          not v and "ACTIVE - reboot recovery pending" in hist and w.status("fp").startswith("RESTORED OK"), f"{v} {hist[-3:]}")
    check("FW-08-D core invariants hold (INV-NO-RESUME)", not w.invariants(), str(w.invariants()))


def run_08e(fw=None, before_s: float = 20, after_s: float = 40) -> dict:
    w = world(fw)
    dump_lease(w, minutes=5)
    end = w.obligations()["dump"]["end"]
    w.rtc_lock_windows([(end - before_s, end + after_s)])
    w.run_for(end + after_s + 30 - w.t_utc)
    return {"w": w, "end": end, "win": (end - before_s, end + after_s)}


def rtc_violations(r) -> list:
    """INV-RTC-EXCL: no restore write lands inside the RTC lock window; the restore follows within one tick after it."""
    a, b = r["win"]
    inside = [x for x in r["w"].writes() if a <= x["t_utc"] < b]
    done = completion_t(r["w"], "dump", r["end"])
    out = [viol("INV-RTC-EXCL", f"write {x['addr']} at {x['t_utc']} inside the RTC lock window") for x in inside]
    if done is None or done > b + WD_S:
        out.append(viol("INV-RESTORE-BOUND", f"restore not complete within one watchdog tick after the window ({done})"))
    return out


def section_08e() -> None:
    print("[13] FW-08-E RTC lock windows (MODEL): Dump end inside a window; a 50 s window during an ACTIVE lease")
    r = run_08e()
    w = r["w"]
    done = completion_t(w, "dump", r["end"])
    print(f"  info  FW-08-E window [{r['win'][0] - r['end']:+.0f}, {r['win'][1] - r['end']:+.0f}] s around the end; "
          f"restore complete {None if done is None else done - r['win'][1]} s after the window")
    v = rtc_violations(r)
    check("FW-08-E INV-RTC-EXCL: the restore is deferred while correction_in_progress holds (no write inside the window) "
          "and completes at the first watchdog tick after it", not v, str(v))
    check("FW-08-E: the RTC lock is not a lock-age lock (no stuck-lock escalation; by design: the FB-D1 breaker bounds it) "
          "and INV-RESTORE-BOUND is explained by the lock held >= one watchdog period",
          w.sim.g["ecco_lock_stuck"] is False and not w.invariants() and w.status("dump_end") == "DURATION EXPIRED",
          f"{w.invariants()} {w.status('dump_end')}")
    m = world()
    dump_lease(m)
    m.run_for(60)
    t = m.t_utc
    m.rtc_lock_windows([(t + 5, t + 55)])
    m.run_for(120)
    check("FW-08-E: an ordinary 50 s RTC correction during an ACTIVE lease pauses the polls without ending the lease (the "
          "SOC freshness bound 90 s exceeds it)", m.obligations()["dump"]["run"] and not statuses(m, "dump_end")
          and not m.invariants(), str(statuses(m, "dump_end")))
    unsupported("FW-08-E-U1", "an RTC lock longer than the FB-D1 90 s deadline breaker: interval [8] (RTC tick, ecco_rtc::) "
                              "is NOT_EXECUTED, so a window beyond it is not a firmware behaviour in this tier")


def run_08f(fw=None, cycles: int = 3) -> dict:
    w = world(fw)
    dump_lease(w)
    w.run_for(60)
    w.inject_global("manual_write_in_progress", True)   # MODEL (logged fault.ram)
    t_leak = w.t_utc
    leaks = [t_leak]
    while w.boot_no < cycles and w.t_utc - t_leak < cycles * 300:
        b = w.boot_no
        w.run_for(5)
        if w.boot_no != b:
            w.run_for(max(0.0, 10 - w.uptime_s))
            w.inject_global("manual_write_in_progress", True)   # MODEL: the leak recurs before the first 15 s watchdog tick
            leaks.append(w.t_utc)
    return {"w": w, "t_leak": t_leak, "leaks": leaks}


def section_08f() -> None:
    print("[14] FW-08-F a leak recurring before the first watchdog tick of every boot (MODEL): the restart loop")
    r = run_08f()
    w = r["w"]
    rs = [e["t_utc"] for e in evs(w, "fw.restart", r["t_leak"])]
    print(f"  info  FW-08-F restarts at {[round(t - r['t_leak']) for t in rs]} s after the first leak; 244 = {w.bank[244]}")
    slots = {a: w.bank[a] for a in range(256, 262)}
    wr = [x for x in w.writes() if x["t_utc"] > r["t_leak"]]
    rstat = w.text_state("ecco_restart_status")
    print(f"  info  FW-08-F 256-261 = {slots}; writes after the first leak: {len(wr)}; Restart Status after the last "
          f"boot: {rstat!r}; Dump status: {w.status('dump')[:60]}")
    repro = (len(rs) == 3 and all(STUCK_S <= g <= STUCK_S + 2 * CENSUS_S + RESTART_DOWN_S + 15 for g in gaps(rs))
             and completion_t(w, "dump", r["t_leak"]) is None and w.bank[244] == 0 and not dump_attempts(w, r["t_leak"])
             and set(slots.values()) == {1000} and not wr and rstat == "")
    if repro:
        finding("F-FW08-1", "FINDING-KNOWN:FCP2-F6 - a lock leak that recurs before the first watchdog tick of every boot "
                            f"gives a restart loop (every {'/'.join(f'{g:.0f}' for g in gaps(rs))} s) in which the owed "
                            "Dump restore never runs: 244 stays at Allow Export and 256-261 at the lease power (1000 W "
                            "synthetic), uncontained, with no write after the leak and a blank Restart Status after each "
                            "boot; the residual's '(each boot then completes the owed restore)' does not hold here")
    check("finding-reproduces:F-FW08-1", repro, f"{gaps(rs)} {w.bank[244]} {slots} {len(wr)} {rstat!r}")
    inv = w.invariants()
    check("FW-08-F: the core checkers explain the open restore by the held lock (INV-RESTORE-BOUND) and see no resume "
          "(INV-NO-RESUME) - the loop is visible only to the scenario's own restart / completion characterisation",
          not inv, str(inv))


# =============================================================================================================================
# negative controls (in-memory exact-count mutants of real guards)
# =============================================================================================================================
def mutant(pairs) -> dict | None:
    text = FW["_text"]
    for old, new in pairs:
        n = text.count(old)
        if n != 1:
            check(f"negative-control anchor found exactly once: {old[:60]!r}", False, f"count {n}")
            return None
        text = text.replace(old, new)
    return L.load_fw(text)


def negative_control(nid: str, family: str, pairs, run, target: str, inv: str) -> None:
    fw = mutant(pairs)
    if fw is None:
        NC_RESULTS.append((nid, family, target, "invalid"))
        return
    try:
        vs = run(fw)
    except Exception as exc:   # a crashing mutant is MUTANT-INVALID: a negative-control FAILURE (never a kill)
        NC_RESULTS.append((nid, family, target, "invalid"))
        check(f"{nid} ({family}) mutant runs without a harness exception (MUTANT-INVALID otherwise)", False,
              f"{type(exc).__name__}: {exc}")
        return
    killed = bool(vs) and all(v["inv"] == inv for v in vs)
    NC_RESULTS.append((nid, family, target, "killed" if killed else "survived"))
    print(f"  info  {nid}: {[v['detail'][:90] for v in vs]}")
    check(f"{nid} ({family}) mutant killed: {target} reports {inv}", killed, str(vs))


# mutations reused by the corpus discrimination checks in [16] (exact-count anchors, applied in memory only)
MUT_STOP_BINDING = [("stop_known = id(dump_end_epoch) != 0 && (rec >> 8)",
                     "stop_known = false && id(dump_end_epoch) != 0 && (rec >> 8)")]
MUT_STOP_CFG = [("if (stop_known && !std::isnan(cfg) && (int) lroundf(cfg) > stop) stop = (int) lroundf(cfg);",
                 "if (stop_known && !std::isnan(cfg)) stop = (int) lroundf(cfg);")]
MUT_NO_ESCALATION = [('the boot path completes the owed restore");\n            - button.press: ecco_restart_internal',
                     "the boot path completes the owed restore\");\n            - lambda: 'return;'")]
MUT_CT_FAST = [("bool ct_frozen = (id(dump_ct_same_count) >= ${ecco_dump_frozen_samples} - 1 &&",
                "bool ct_frozen = (false && id(dump_ct_same_count) >= ${ecco_dump_frozen_samples} - 1 &&")]
MUT_SOC_FROZEN = [("id(dump_soc_frozen_wh_acc) > ${ecco_dump_soc_frozen_wh}.0f;", "false;")]
MUT_BP_FROZEN = [("return ct_frozen || id(dump_bp_same_count) >= ${ecco_dump_frozen_samples} - 1 ||",
                  "return ct_frozen ||")]


def section_negative() -> None:
    print("[15] negative controls: each in-memory mutant must make the intended check fail (killed), not crash")
    negative_control(
        "NC-FW07-1", "FW-07", [("(id(dump_restore_failed_ms) != 0 &&", "(false && id(dump_restore_failed_ms) != 0 &&")],
        lambda fw: (lambda r: rebased_restore_bound(r["w"], r["seq_up"], SG39_BOUND_S))(run_07a(fw)),
        "FW-07-A rebased INV-RESTORE-BOUND (SG-39 clause removed)", "INV-RESTORE-BOUND")
    negative_control(
        "NC-FW07-2", "FW-07", [("return !soc_plausible || !soc_fresh || !id(configuration_online).state;", "return false;")],
        lambda fw: inv17_violations(run_07a(fw)), "FW-07-A INV-17 (TELEMETRY LOST monitor neutered)", "INV-17")
    negative_control(
        "NC-FW07-3", "FW-07",
        [("(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : millis() > ${ecco_dump_soc_stale_ms}UL);",
          "(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : false);")],
        lambda fw: cadence_violations(run_07c(fw)["ups"]), "FW-07-C INV-16 cadence (no-fresh-SOC clause removed)",
        "INV-16")
    negative_control(
        "NC-FW07-4", "FW-07", MUT_STOP_BINDING,
        lambda fw: stop_soc_violations(run_07d(fw)), "FW-07-D INV-16 owed Stop SOC (record binding removed)", "INV-16")
    negative_control(
        "NC-FW07-7", "FW-07", MUT_STOP_CFG,
        lambda fw: stop_soc_violations(run_07d(fw)),
        "FW-07-D INV-16 owed Stop SOC (the owner's lower configured Stop SOC replaces the owed one)", "INV-16")
    negative_control(
        "NC-FW07-5", "FW-07",
        [('id(dump_restore_requested) = true;\n                    id(dump_last_end_reason).publish_state("ESP RESTARTED',
          'id(dump_restore_requested) = id(dump_restore_requested);\n                    '
          'id(dump_last_end_reason).publish_state("ESP RESTARTED')],
        lambda fw: run_07e(fw, "dump")["w"].invariants(["INV-NO-RESUME"]), "FW-07-E INV-NO-RESUME (Dump boot no-resume removed)",
        "INV-NO-RESUME")
    negative_control(
        "NC-FW07-6", "FW-07",
        [('id(free_power_restore_requested) = true;\n                    ESP_LOGW("free_power", "Free Power was ACTIVE',
          'id(free_power_restore_requested) = id(free_power_restore_requested);\n                    '
          'ESP_LOGW("free_power", "Free Power was ACTIVE')],
        lambda fw: run_07e(fw, "fp")["w"].invariants(["INV-NO-RESUME"]), "FW-07-E FP INV-NO-RESUME (S3 removed)",
        "INV-NO-RESUME")
    negative_control(
        "NC-FW07-8", "FW-07", MUT_CT_FAST,
        lambda fw: frozen_end_violations(run_07i(fw, "ct", 256), CTF, *CT_WIN),
        "FW-07-I INV-17 (the fast frozen-CT criterion removed: only the 30-read slow window is left)", "INV-17")
    negative_control(
        "NC-FW07-9", "FW-07", MUT_SOC_FROZEN,
        lambda fw: frozen_end_violations(run_07i_soc(fw, None), SOCF, *SOC_WIN, t_ref="t_start"),
        "FW-07-I INV-17 (the frozen-SOC energy term removed from the watchdog's frozen condition)", "INV-17")
    negative_control(
        "NC-FW07-10", "FW-07", MUT_BP_FROZEN,
        lambda fw: frozen_end_violations(run_07i(fw, "bp", 244), BPF, *CT_WIN),
        "FW-07-I INV-17 (the battery-power repeat term removed from the watchdog's frozen condition)", "INV-17")
    negative_control(
        "NC-FW08-1", "FW-08", MUT_NO_ESCALATION,
        lambda fw: (lambda r: escalation_violations(r["w"], r["t_leak"], "dump"))(run_08b(fw)),
        "FW-08-B INV-20 (escalation restart removed)", "INV-20")
    negative_control(
        "NC-FW08-2", "FW-08",
        [("bool held = id(manual_write_in_progress) || id(dump_operation_in_progress) ||",
          "bool held = id(dump_operation_in_progress) ||")],
        lambda fw: (lambda r: escalation_violations(r["w"], r["t_leak"], "dump"))(run_08b(fw)),
        "FW-08-B INV-20 (lock age ignores the shared write mutex)", "INV-20")
    negative_control(
        "NC-FW08-3", "FW-08",
        [("if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;",
          "if (id(dump_operation_in_progress) || id(manual_write_in_progress)) return false;"),
         ("!id(manual_write_in_progress) &&\n                !id(correction_in_progress) &&\n                // Comms backoff pacing",
          "!id(manual_write_in_progress) &&\n                // Comms backoff pacing")],
        lambda fw: [v for v in rtc_violations(run_08e(fw)) if v["inv"] == "INV-RTC-EXCL"],
        "FW-08-E INV-RTC-EXCL (watchdog trigger and restore gate ignore the RTC lock)", "INV-RTC-EXCL")
    fams = {f for _, f, _, _ in NC_RESULTS}
    check("every scenario family has at least one killed negative control and no mutant survived or was invalid",
          fams == {"FW-07", "FW-08"} and all(o == "killed" for *_, o in NC_RESULTS),
          str([(n, o) for n, _, _, o in NC_RESULTS]))


# =============================================================================================================================
# corpus: minimal replay documents (recorded with _lab_trace.record; replayed here with the _lab_trace engine)
# =============================================================================================================================
# CORPUS_DRAFTS is a pure literal (the recorder reads it with ast.literal_eval); record() fills source_digests (the three
# placeholder paths plus every anchor path), each anchor's line_at_record and trace_digest from two identical replays.
CORPUS_DRAFTS = [
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-a", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Link down 300 s during an ACTIVE Dump lease: TELEMETRY LOST, then the SG-39 retry at link recovery",
     "ownership": "ECCO-owned Dump lease (owner START, synthetic SITE ORIGINAL); coupled link MODEL; no foreign actor",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "reason: \"TELEMETRY LOST - failing closed\""},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "(id(dump_restore_failed_ms) != 0 &&"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 180, "do": "set_link", "args": {"up": False}},
                 {"at_s": 480, "do": "set_link", "args": {"up": True}},
                 {"at_s": 480, "do": "run_for", "args": {"seconds": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump_end"}, "op": "==", "value": "TELEMETRY LOST - failing closed"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-RESTORE-BOUND", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "export continues after the link loss, or the owed restore waits out up to 300 s after the link is back",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - restore completes within 30 s of link recovery",
     "notes": "Key guard decisions: TELEMETRY LOST about 28 s after the loss; supervised retry every 15 s while the SOC is "
              "stale; SG-39 completes the restore about 13 s after recovery although a 300 s backoff was pending (the "
              "first telemetry read after the recovery makes the SOC fresh again, so the supervision is off by then; "
              "the SG-39-removed mutant leaves the restore open)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-b", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Link down during the Dump restore after 244 was proven: comms backoff, SG-39 at recovery",
     "ownership": "ECCO-owned Dump lease ended by the owner; one lost 256-261 write, then the coupled link MODEL outage",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "id(dump_restore_next_attempt_ms) = millis() + ecco_durable::comms_backoff_ms(id(dump_comms_restore_attempts));"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml", "text": "(id(dump_restore_failed_ms) != 0 &&"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 180, "do": "modbus_policy", "args": {"table": {"write:256": ["timeout_lost"]}}},
                 {"at_s": 180, "do": "dump_end", "args": {}},
                 {"at_s": 180, "do": "set_link", "args": {"up": False}},
                 {"at_s": 1180, "do": "set_link", "args": {"up": True}},
                 {"at_s": 1180, "do": "run_for", "args": {"seconds": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-RESTORE-BOUND", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "retries without backoff, or the restore sits out the remaining 300 s backoff after the link is back",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - backoff 15/30/60/120/300 s, then SG-39 within 30 s",
     "notes": "Attempt gaps 28/30/60/120/300/300 s on the watchdog grid; the 300 s backoff was pending until at_s 1318."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-c", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Reboot during an ACTIVE Dump lease with the link down after boot: no-resume, 90 s no-fresh-SOC supervision",
     "ownership": "ECCO-owned Dump lease; power cut 5 s; coupled link MODEL outage across the boot",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "id(dump_last_end_reason).publish_state(\"ESP RESTARTED DURING LEASE - ended, not resumed\");"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "(soc_fresh ? (float) stop >= id(ecco_battery_soc).state : millis() > ${ecco_dump_soc_stale_ms}UL);"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 180, "do": "set_link", "args": {"up": False}},
                 {"at_s": 180, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 420, "do": "set_link", "args": {"up": True}},
                 {"at_s": 420, "do": "run_for", "args": {"seconds": 30}}],
     "expect": [{"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-16", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the lease resumes blind, or the owed restore stays paced by the backoff without fresh SOC",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - retries at uptime 15/30/60 s, then every tick from 105 s",
     "notes": "Restore attempts after the boot at uptime 15, 30, 60, 105, 120, ... s; the link returns at uptime 235 s."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-d", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": "P3",
     "title": "Reboot with the inverter refusing 244 writes: owed Stop SOC supervision, export left enabled (FCP2-R1)",
     "ownership": "ECCO-owned Dump lease; the owner lowers the configured Stop SOC to 10 % after START; the inverter "
                  "answers reads but refuses every 244 write (synthetic Modbus exception)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "stop_known = id(dump_end_epoch) != 0 && (rec >> 8) == (id(dump_end_epoch) & 0xFFFFFFu) &&"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if (stop_known && !std::isnan(cfg) && (int) lroundf(cfg) > stop) stop = (int) lroundf(cfg);"},
                        {"path": "docs/dev/dump-to-grid-safety-fcp2.md",
                         "text": "| R1 SG-04: block never restored when 244 fails; no supervision |"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050, "soc": 50}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 120, "do": "set_number", "args": {"entity": "dump_stop_soc", "value": 10}},
                 {"at_s": 180, "do": "modbus_policy", "args": {"table": {"write:244": "error"}}},
                 {"at_s": 180, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 487, "do": "telemetry", "args": {"soc": 24}},
                 {"at_s": 487, "do": "run_for", "args": {"seconds": 60}}],
     "expect": [{"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 500, "257": 500, "258": 500, "259": 500, "260": 500, "261": 500}},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "contains",
                 "value": "register 244 NOT proven out of Allow Export - ECCO's TOU power registers held at the 500 W floor"},
                {"observe": "globals", "args": {"names": ["dump_target_stop_soc", "dump_comms_restore_attempts"]}, "op": "==",
                 "value": {"dump_target_stop_soc": -1, "dump_comms_restore_attempts": 9}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-KNOWN:FCP2-R1", "invariant": "INV-16", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "export stays enabled while the inverter refuses 244 (documented residual; ECCO's own slots held "
                        "at 500 W and named in each failed attempt's status, not CRITICAL)",
     "smallest_safe_repair_scope": "none in firmware (documented residual FCP2-R1); the owner must clear 244 at the "
                                   "inverter, after which the next attempt restores 256-261 by itself",
     "notes": "F-FW07-3. The owed Stop SOC 25 % comes from dump_owed_stop_soc_rec after the restart; retries follow the "
              "backoff while the SOC is 50 % and run every tick once it is 24 %. The 500 W floor bounds ECCO's own "
              "battery discharge slots, not PV export (inverter register 245) or FOREIGN slots. The owner's set_number "
              "lowers the configured Stop SOC to 10 % before the restart; the lease's own Stop SOC is RAM only "
              "(dump_target_stop_soc -1 after the boot). Retry count 9 = 5 backoff-paced attempts at SOC 50 % (boot "
              "uptime 15/30/60/120/240 s) + 4 supervised every-tick attempts in the 60 s at SOC 24 %, which only the "
              "owed 25 % triggers (the configured 10 % would not). Suite [16] replays this document against two "
              "in-memory mutants and requires its expectations to fail: the record binding removed (NC-FW07-4: every "
              "tick at any SOC) and the lower configured Stop SOC replacing the owed one (NC-FW07-7: no supervised "
              "retry at 24 %)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-e", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Reboot with NTP invalid at early uptime: the owed Dump restore runs at uptime 15 s, the 300 s grace never applies",
     "ownership": "ECCO-owned Dump lease; first NTP sync at uptime 400 s on every boot (MODEL); power cut 5 s",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "ecco_free_power_invalid_clock_grace_ms: \"300000\""},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "id(dump_last_end_reason).publish_state(\"ESP RESTARTED DURING LEASE - ended, not resumed\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"ntp_after_s": 400},
     "actions": [{"at_s": 420, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 420, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 540, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 547, "do": "run_for", "args": {"seconds": 25}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "globals", "args": {"names": ["ntp_synced"]}, "op": "==", "value": {"ntp_synced": False}},
                {"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-NO-RESUME", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the lease resumes after the reboot and, with the clock invalid, runs on the 300 s grace",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - boot no-resume forces the restore request",
     "notes": "The restore completes at boot uptime 15 s while now() is invalid; NTP syncs only at uptime 400 s."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-f", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": "P3",
     "title": "Free Power restore after a long link outage: still not restored 60 s after the link is back (no SG-39 analogue)",
     "ownership": "ECCO-owned Free Power lease (owner START, synthetic SITE ORIGINAL); coupled link MODEL outage",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if (next_ms != 0 && (int32_t)(now_ms - next_ms) < 0) {"},
                        {"path": "docs/dev/dump-to-grid-safety-fcp2.md",
                         "text": "**The restore backoff (SG-39).** A restore attempt that failed while the link itself was down"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 5}},
                 {"at_s": 260, "do": "set_link", "args": {"up": False}},
                 {"at_s": 1260, "do": "set_link", "args": {"up": True}},
                 {"at_s": 1260, "do": "run_for", "args": {"seconds": 60}}],
     "expect": [{"observe": "status", "args": {"dom": "fp"}, "op": "==",
                 "value": "RESTORE WRITE FAILED - snapshot retained; will retry automatically"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "globals", "args": {"names": ["free_power_comms_restore_attempts"]}, "op": "==",
                 "value": {"free_power_comms_restore_attempts": 7}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-NEW", "invariant": "INV-RESTORE-BOUND", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the Free Power override (232, 230, 256-261, 268-279) stays on the inverter for the rest of the "
                        "current backoff window (0-300 s) after recovery",
     "smallest_safe_repair_scope": "Free Power restore pacing only, mirroring the Dump SG-39 clause in three parts: (a) a "
                                   "RAM-only stamp set at the comms-failure sites only when no telemetry read succeeded "
                                   "for the link-down bound; (b) an extra clause in the wrapper's backoff gate, after the "
                                   "operator lockout check, letting the next watchdog tick retry once a telemetry read "
                                   "has succeeded since the stamp and comms_backoff_ms(1) has elapsed; (c) clearing the "
                                   "stamp on a verified restore, at START and on End; no change to the backoff table, "
                                   "the classifier, the lockout or the writes",
     "notes": "F-FW07-1. In this run the FP restore completes about 238 s after the link recovery (Dump, by SG-39: about "
              "13-18 s). Severity low (cost / availability, no export). With Live Inverter Telemetry off the repaired "
              "gate would fall back to today's pacing (fail safe)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-g", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": "P3",
     "title": "Reboot while a Dump restore is owed: Last End Reason misattributes the ended lease to ESP RESTARTED DURING LEASE",
     "ownership": "ECCO-owned Dump lease ended by its own monitor; power cut 5 s during the owed restore; link MODEL",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "// (active_persisted == 0), this is already true anyway."},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "// 2026-09-26 pre-live hardening: keep the FIRST end reason of a"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 180, "do": "set_link", "args": {"up": False}},
                 {"at_s": 260, "do": "reboot", "args": {"down_s": 5}},
                 {"at_s": 300, "do": "set_link", "args": {"up": True}},
                 {"at_s": 300, "do": "run_for", "args": {"seconds": 40}}],
     "expect": [{"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["TELEMETRY LOST - failing closed", "ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-NEW", "invariant": "INV-FIRST-END-REASON", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "Last End Reason after the reboot says the restart ended a lease that had already ended",
     "smallest_safe_repair_scope": "diagnostics only, the Dump boot block: keep restore_requested = true unconditional; "
                                   "publish 'ESP RESTARTED DURING LEASE' only when the loaded record has "
                                   "restore_requested == 0 (the lease really was running); otherwise publish a distinct "
                                   "text (a restore was already owed at the restart; the earlier reason was not "
                                   "retained) or nothing; correct the boot comment; no write path, gate or restore "
                                   "change. Persisting the reason is not part of the minimal scope (the 24-byte data "
                                   "record would need a new layout), so the minimal fix cannot recover WRITE LOCK STUCK "
                                   "after an escalation restart",
     "notes": "F-FW07-2. The durable data record at the cut holds active_persisted 1 and restore_requested 1 (request_dump_end "
              "re-commits the RAM active flag). Last End Reason is RAM-only, so no reboot can keep the first reason; the "
              "defect is the wrong attribution. The same misattribution follows every stuck-lock escalation restart "
              "(FW-08-B/C)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-h", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": "P3",
     "title": "One no-response on the configuration Block B read ends an ACTIVE Dump lease as TELEMETRY LOST",
     "ownership": "ECCO-owned Dump lease; one no_response on one 241x53 configuration read, every other operation answered",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "return !soc_plausible || !soc_fresh || !id(configuration_online).state;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "post-activation readback is ended as \"readback stale\"."}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 180, "do": "modbus_policy", "args": {"table": {"read:241x53": ["no_response"]}}},
                 {"at_s": 180, "do": "run_for", "args": {"seconds": 121}}],
     "expect": [{"observe": "status", "args": {"dom": "dump_end"}, "op": "==", "value": "TELEMETRY LOST - failing closed"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "globals", "args": {"names": ["dump_active_persisted", "dump_snapshot_valid"]}, "op": "==",
                 "value": {"dump_active_persisted": False, "dump_snapshot_valid": False}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-NEW", "invariant": "INV-17", "grade": "VERIFIED", "confidence": "low",
     "failure_outcome": "a single transient configuration read failure ends the lease early (fail closed) and the reason "
                        "names telemetry",
     "smallest_safe_repair_scope": "the Dump watchdog's TELEMETRY LOST condition only: (a) diagnostics, safe - give the "
                                   "configuration-offline case its own end reason; (b) availability, a design decision "
                                   "because it relaxes an explicit fail-closed end - narrow or remove the "
                                   "configuration_online term: Block B (the only block with Dump-owned registers) is "
                                   "already bounded by CONFIG READBACK STALE (a persistent Block B failure then ends at "
                                   "about 148 s), a failure counter is needed only if a persistent Block A-only failure "
                                   "must still end the lease, and a real link loss then ends at about 88 s (SOC "
                                   "freshness) instead of about 28 s; START gate unchanged",
     "notes": "F-FW07-4. The failed read is at at_s 198 and the lease ends at the next watchdog tick, 10 s later; "
              "configuration_online is true again after the next successful poll, and the lease is (correctly) not "
              "resumed. Confidence low that this is unintended: the term is explicit fail-closed code whose rationale "
              "no public document states."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-i", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Grid CT frozen with the link up during an ACTIVE Dump lease: GRID CT FROZEN, power cut at the restore, boot restore",
     "ownership": "ECCO-owned Dump lease (owner START, synthetic SITE ORIGINAL); the link stays up; the CT repeats -1000 W from "
                  "at_s 128 while the battery moves 200 W (world noise false, explicit values 5 s before every poll slot); "
                  "a power cut armed at the restore's 256-261 write",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "bool ct_frozen = (id(dump_ct_same_count) >= ${ecco_dump_frozen_samples} - 1 &&"},
                        {"path": "docs/dev/dump-to-grid-safety-fcp2.md",
                         "text": "| Grid CT, fast | it repeats exactly for `ecco_dump_frozen_samples` reads while the battery power "
                                 "moved by more than `ecco_dump_frozen_cross_w`."}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"noise": False},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 60, "do": "arm_power_cut", "args": {"kind": "fw.write", "addr": 256}},
                 {"at_s": 68, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1049}},
                 {"at_s": 78, "do": "telemetry", "args": {"poll": False, "grid_w": -1001, "batt_w": 1050}},
                 {"at_s": 88, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1051}},
                 {"at_s": 98, "do": "telemetry", "args": {"poll": False, "grid_w": -1001, "batt_w": 1049}},
                 {"at_s": 108, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 118, "do": "telemetry", "args": {"poll": False, "grid_w": -1001, "batt_w": 1051}},
                 {"at_s": 128, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 138, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1250}},
                 {"at_s": 148, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 158, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1250}},
                 {"at_s": 168, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 168, "do": "run_for", "args": {"seconds": 60}},
                 {"at_s": 250, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["GRID CT FROZEN - 6 identical readings of -1000W while the battery moved 200W; the controller and "
                           "the export guard cannot be trusted - failing closed",
                           "ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-17", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the lease keeps exporting on a CT reading that is no longer evidence although the link is up, or the "
                        "restore after the frozen end is lost at the power cut, or the boot resumes the lease",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the fast frozen-CT criterion ends the lease 60 s after "
                                   "the first frozen read; the boot path completes the cut-short restore at its first "
                                   "watchdog tick",
     "notes": "Suite scenario FW-07-I (ct). The CT changes for the last time at at_s 123 (after the 30 s grace), repeats from "
              "the read at at_s 133 (the last explicit values at at_s 168 hold for the read at at_s 183) and the watchdog "
              "ends the lease at at_s 193 (6 identical reads, the battery range 200 W from the readings during the "
              "repeats); the restore verifies 244, the power cut fires at its 256-261 write, the boot (at_s 200) mirrors "
              "the stored RESTORE_REQUIRED and restores at uptime 15 s (at_s 213), the CT still frozen. The end-reason "
              "history also pins F-FW07-2 (owned by FW-07-g). Suite [16] replays this document against the "
              "fast-criterion-removed mutant (NC-FW07-8) and requires its expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-i2", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": None,
     "title": "Stale-but-plausible SOC with the link up: SOC TELEMETRY FROZEN after 1500 Wh, power cut at the restore, boot restore",
     "ownership": "ECCO-owned Dump lease of 120 min (owner START, synthetic SITE ORIGINAL); the link stays up; the SOC stays "
                  "70 % (fresh every 10 s, above the 25 % Stop SOC) while the battery discharges about 1050 W (no SOC "
                  "physics; noise MODEL on); a power cut armed at the restore's 244 write",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "id(dump_soc_frozen_wh_acc) > ${ecco_dump_soc_frozen_wh}.0f;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "ecco_dump_soc_frozen_wh: \"1500\""}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 120}},
                 {"at_s": 60, "do": "arm_power_cut", "args": {"kind": "fw.write", "addr": 244}},
                 {"at_s": 5260, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["SOC TELEMETRY FROZEN - 1503Wh discharged with no SOC change (still 70%); Stop SOC cannot be "
                           "trusted - failing closed", "ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-17", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "Stop SOC is enforced on a SOC reading that is fresh and plausible but no longer changes, so the lease "
                        "discharges past the owner's floor, or the restore after the frozen end is lost at the power cut",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the frozen-SOC count ends the lease once 1500 Wh are "
                                   "discharged with no SOC change; the boot path completes the cut-short restore",
     "notes": "Suite scenario FW-07-I (soc). The lease ends about 5158 s after START (1500 Wh at 1050 W is about 5143 s; the "
              "count starts at START, one 10 s sample gap either way); the power cut fires at the restore's 244 write "
              "(landed, not yet verified), the boot mirrors the stored RESTORE_REQUIRED and restores at uptime 15 s. The "
              "1500 Wh default is site-dependent (fcp2 section 4). Suite [16] replays this document against the "
              "frozen-SOC-term-removed mutant (NC-FW07-9) and requires its expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-07-i3", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P2", "finding_priority": "P3",
     "title": "Grid CT repeating since the boot, battery steady: the fast frozen-CT criterion fires on a battery range from outside "
              "the repeat window",
     "ownership": "ECCO-owned Dump lease (owner START, synthetic SITE ORIGINAL); the link stays up; the CT reads -1000 W from "
                  "the first poll on (a CT stuck before the lease) while the battery reads 1049 / 1050 / 1051 W (world noise "
                  "false, explicit values; no reading of 0 W ever)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "// fcp2 (SG-15 / SG-43): fresh frozen-telemetry evidence."},
                        {"path": "docs/dev/dump-to-grid-safety-fcp2.md",
                         "text": "| Grid CT, slow | it repeats exactly for `ecco_dump_frozen_ct_long_samples` reads, whatever the "
                                 "battery did."}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {"noise": False},
     "actions": [{"at_s": 0, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 68, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1049}},
                 {"at_s": 78, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 88, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1051}},
                 {"at_s": 98, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1049}},
                 {"at_s": 108, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 118, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1051}},
                 {"at_s": 128, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1049}},
                 {"at_s": 138, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 148, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1051}},
                 {"at_s": 158, "do": "telemetry", "args": {"poll": False, "grid_w": -1000, "batt_w": 1049}},
                 {"at_s": 158, "do": "run_for", "args": {"seconds": 30}}],
     "expect": [{"observe": "status", "args": {"dom": "dump_end"}, "op": "==",
                 "value": "GRID CT FROZEN - 7 identical readings of -1000W while the battery moved 1051W; the controller and "
                          "the export guard cannot be trusted - failing closed"},
                {"observe": "globals", "args": {"names": ["dump_ct_same_bmin", "dump_ct_same_bmax"]}, "op": "==",
                 "value": {"dump_ct_same_bmin": 0.0, "dump_ct_same_bmax": 1051.0}},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-NEW", "invariant": "INV-17", "grade": "VERIFIED", "confidence": "medium",
     "failure_outcome": "a CT already repeating at START with a steady battery ends the lease by the fast criterion after 7 "
                        "reads instead of the documented 30-read slow criterion, and the end text names a battery movement "
                        "(1051 W) that no reading during the repeats showed (fail closed; diagnostics)",
     "smallest_safe_repair_scope": "the frozen-CT evidence only: seed dump_ct_same_bmin / dump_ct_same_bmax empty (1e9 / "
                                   "-1e9, as the CT hook's own re-seed does) with dump_ct_same_count in the START block "
                                   "'fresh frozen-telemetry evidence'; no threshold, write path or gate change. A design "
                                   "decision, because it restores the documented slow criterion for a CT already frozen at "
                                   "START with a steady battery (a fail-closed end then comes after about 5 minutes instead "
                                   "of about 1); a diagnostics-only alternative keeps the decision and reports only the "
                                   "battery movement seen during the repeats",
     "notes": "F-FW07-5. The range globals keep their boot value 0.0 (initial_value, not a reading: the battery reads 1049-1051 "
              "W from the first poll on) because the CT never changes inside the lease after the 30 s grace, so the first "
              "post-grace read equals the pre-START value and only the count restarts. The suite also shows the previous "
              "lease's readings carried into a new lease (about 1000 W of phantom movement) and the control: a CT that "
              "changes after the grace and then repeats ends after 30 reads naming the 2 W the battery moved. Suite [16] "
              "replays this document against the repair mutant (the range seeded empty at START) and requires its "
              "expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-a", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": None,
     "title": "Manual TOU verify read with no callback leaks the write mutex: STUCK LOCK report-only, Dump START refused",
     "ownership": "owner manual TOU slot 2 apply (no lease owed, as the apply gate requires); the verify read gets no reply",
     "source_anchors": [{"path": "docs/dev/advanced-config/write-surface.md",
                         "text": "The verify read has no bounded `wait_until`: the mutex is released only inside the read callbacks."},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "nothing is owed, so no automatic restart - inverter writes stay blocked until Restart (Restart Override Arm)"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "modbus_policy", "args": {"table": {"read:250x30": ["timeout"]}}},
                 {"at_s": 60, "do": "manual_slot_apply", "args": {"slot": 2, "soc": 55}},
                 {"at_s": 301, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 301, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "==", "value": "REJECTED - another inverter write is active"},
                {"observe": "globals", "args": {"names": ["manual_write_in_progress", "ecco_lock_stuck", "ecco_lock_escalated"]},
                 "op": "==", "value": {"manual_write_in_progress": True, "ecco_lock_stuck": True, "ecco_lock_escalated": True}},
                {"observe": "text_state", "args": {"entity": "ecco_restart_status"}, "op": "==",
                 "value": "STUCK LOCK - an inverter transaction lock was held beyond any transaction's bound; nothing is "
                          "owed, so no automatic restart - inverter writes stay blocked until Restart (Restart Override Arm)"},
                {"observe": "boot_no", "args": {}, "op": "==", "value": 0},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-20", "grade": "VERIFIED", "confidence": "medium",
     "failure_outcome": "the write mutex stays held until a restart: every START and restore is refused, polls pause",
     "smallest_safe_repair_scope": "none required by this lab (documented behaviour); a hardening option is the reg244 "
                                   "pattern for the manual verify read: an op-terminal flag set in every callback and a "
                                   "bounded wait_until whose timeout path releases the mutex and reports VERIFY FAILED",
     "notes": "Documented in write-surface.md (no bounded wait_until on the verify read); caught by the fcp2 lock-age "
              "monitor, which reports only because nothing is owed. 'timeout' means no callback at all."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-b", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": None,
     "title": "RTC lock window over the Dump end epoch: the restore stays deferred while the lock holds",
     "ownership": "ECCO-owned Dump lease of 5 min; a synthetic RTC correction lock window 20 s before to 40 s after its end (MODEL)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 5}},
                 {"at_s": 60, "do": "rtc_lock_windows", "args": {"windows": [["2026-10-21T10:55:40Z", "2026-10-21T10:56:40Z"]]}},
                 {"at_s": 402, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "ACTIVE - VERIFIED OK"},
                {"observe": "globals", "args": {"names": ["correction_in_progress"]}, "op": "==",
                 "value": {"correction_in_progress": False}},
                {"observe": "invariants", "args": {"names": ["INV-RESTORE-BOUND"], "bound_s": 30}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-RESTORE-BOUND", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a restore writes during an RTC correction",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the watchdog defers the due restore behind the RTC lock",
     "notes": "Lease end at at_s 360, lock until at_s 400: at at_s 402 the lease is still active (deferred, the delay is "
              "explained by the lock); the first watchdog tick after the window (at_s 403) restores (checked in the suite)."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-c", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": None,
     "title": "Write mutex leaked 5 s before the Dump lease end: END DEFERRED, stuck-lock restart, boot-path restore",
     "ownership": "ECCO-owned Dump lease of 5 min; manual_write_in_progress leaked at at_s 355 by an unidentified path "
                  "(white-box RAM injection, replay action inject_global, logged fault.ram; MODEL)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if ((uint32_t) (millis() - id(ecco_lock_since_ms)) > ${ecco_write_lock_stuck_ms}UL) id(ecco_lock_stuck) = true;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "id(dump_status).publish_state(\"END DEFERRED - another inverter write is active; watchdog will retry\");"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 5}},
                 {"at_s": 355, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                 {"at_s": 564, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                 "value": "END DEFERRED - another inverter write is active; watchdog will retry"},
                {"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["TELEMETRY LOST - failing closed", "ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "globals", "args": {"names": ["manual_write_in_progress", "ecco_lock_stuck"]}, "op": "==",
                 "value": {"manual_write_in_progress": False, "ecco_lock_stuck": False}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-20", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the owed restore stays deferred behind the leaked lock indefinitely (export left enabled)",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the lock-age monitor escalates a lock held > 180 s "
                                   "while a restore is owed to a firmware restart; the boot path restores",
     "notes": "Suite scenario FW-08-B. The leak pauses the telemetry poll, so the lease ends TELEMETRY LOST; the restore is "
              "deferred (END DEFERRED - another inverter write); the escalation restarts the dongle 188 s after the leak "
              "(at_s 543) and the boot path restores at its first watchdog tick (at_s 561). at_s 564 is the INV-20 "
              "bound: leak + 180 s stuck bound + 2 census periods (10 s) + restart down 3 s + first watchdog 15 s + 1 s. "
              "The end-reason history also pins F-FW07-2 (owned by FW-07-g: ESP RESTARTED for an already-ended lease). "
              "Suite [16] replays this document against the escalation-removed mutant (NC-FW08-1) and requires its "
              "expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-d", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": None,
     "title": "Dump operation flag leaked during an ACTIVE lease, SOC below Stop SOC: WRITE LOCK STUCK end, restart, restore",
     "ownership": "ECCO-owned Dump lease; dump_operation_in_progress leaked at at_s 90 by an unidentified path "
                  "(white-box RAM injection, replay action inject_global, logged fault.ram; MODEL); SOC 24 % from at_s 110",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "reason: \"WRITE LOCK STUCK - an inverter transaction lock was held beyond any transaction's bound; lease ended durably, restarting so the boot path completes the restore\""},
                        {"path": "docs/dev/dump-to-grid-safety-fcp2.md", "text": "1. **An active Dump lease is ended durably.**"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 90, "do": "inject_global", "args": {"name": "dump_operation_in_progress", "value": True}},
                 {"at_s": 110, "do": "telemetry", "args": {"soc": 24}},
                 {"at_s": 299, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "status_history", "args": {"dom": "dump_end"}, "op": "==",
                 "value": ["WRITE LOCK STUCK - an inverter transaction lock was held beyond any transaction's bound; "
                           "lease ended durably, restarting so the boot path completes the restore",
                           "ESP RESTARTED DURING LEASE - ended, not resumed"]},
                {"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 2, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000, "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-20", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "a leaked operation flag suspends every lease monitor (Stop SOC, telemetry loss) indefinitely",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the escalation ends the lease durably (WRITE LOCK "
                                   "STUCK), restarts, and the boot path restores; the Stop SOC overrun is bounded by it",
     "notes": "Suite scenario FW-08-C. The leaked flag suspends the lease monitors, so STOP SOC REACHED at 24 % is not acted "
              "on; the escalation ends the lease WRITE LOCK STUCK, restarts at at_s 278 and the boot path restores at "
              "at_s 296. at_s 299 is the INV-20 bound (leak + 180 + 10 + 3 + 15 + 1 s). The end-reason history also pins "
              "F-FW07-2 (owned by FW-07-g). Suite [16] replays this document against the escalation-removed mutant "
              "(NC-FW08-1) and requires its expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-e", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": None,
     "title": "Write mutex leaked during a Free Power lease: stuck-lock restart, S3 restore request, Free Power restore",
     "ownership": "ECCO-owned Free Power lease (owner START, synthetic SITE ORIGINAL); manual_write_in_progress leaked at "
                  "at_s 90 by an unidentified path (white-box RAM injection, replay action inject_global; MODEL)",
     "source_anchors": [{"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if (id(free_power_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "Free Power was ACTIVE at last shutdown - ending and restoring on this boot rather than resuming the lease"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                 {"at_s": 90, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                 {"at_s": 299, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                {"observe": "status_history", "args": {"dom": "fp"}, "op": "contains", "value": "ACTIVE - reboot recovery pending"},
                {"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "RESTORED OK"},
                {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                {"observe": "bank", "args": {"addrs": [230, 232, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"230": 120, "232": 0, "256": 8000, "257": 8000, "258": 7000, "259": 8000, "260": 8000,
                           "261": 5000}},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "PASS", "invariant": "INV-20", "grade": "VERIFIED", "confidence": "high",
     "failure_outcome": "the Free Power restore stays deferred behind the leaked lock indefinitely",
     "smallest_safe_repair_scope": "none (PASS): key guard decision - the stuck-lock restart; the boot path's S3 turns the "
                                   "active lease into a restore request and the Free Power watchdog restores",
     "notes": "Suite scenario FW-08-D. Restart at at_s 278, Free Power restore complete at at_s 296; at_s 299 is the INV-20 "
              "bound (leak + 180 + 10 + 3 + 15 + 1 s). Suite [16] replays this document against the escalation-removed "
              "mutant (NC-FW08-1) and requires its expectations to fail."},
    {"schema": "ecco-assurance-lab-replay/v0", "id": "FW-08-f", "tier": "firmware", "seed": 0, "utc_start": "2026-10-21T10:50:00Z",
     "synthetic": True, "scenario_priority": "P3", "finding_priority": "P3",
     "title": "Lock leak recurring before the first watchdog tick of every boot: stuck-lock restart loop, Dump restore never runs",
     "ownership": "ECCO-owned Dump lease; manual_write_in_progress leaked at at_s 120 and again at boot uptime 10 s after "
                  "each stuck-lock restart (at_s 321 and 524) by an unidentified path (inject_global; MODEL)",
     "source_anchors": [{"path": "docs/dev/dump-to-grid-safety-fcp2.md",
                         "text": "If a code path leaks the lock again after every boot, the device restarts at most once per bound"},
                        {"path": "firmware/ecco_clock_dongle_stage3_4_free_power.yaml",
                         "text": "if (id(dump_operation_in_progress) || id(manual_write_in_progress) || id(correction_in_progress)) return false;"}],
     "source_digests": {"firmware/ecco_clock_dongle_stage3_4_free_power.yaml": "", "registry/tests/_dump_sim.py": "",
                        "registry/tests/assurance_lab/_lab_fw.py": ""},
     "world": {},
     "actions": [{"at_s": 60, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                 {"at_s": 60, "do": "dump_start", "args": {"power_w": 1000, "stop_soc": 25, "minutes": 60}},
                 {"at_s": 120, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                 {"at_s": 321, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                 {"at_s": 524, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                 {"at_s": 600, "do": "run_for", "args": {"seconds": 0}}],
     "expect": [{"observe": "boot_no", "args": {}, "op": "==", "value": 2},
                {"observe": "bank", "args": {"addrs": [244, 256, 257, 258, 259, 260, 261]}, "op": "==",
                 "value": {"244": 0, "256": 1000, "257": 1000, "258": 1000, "259": 1000, "260": 1000, "261": 1000}},
                {"observe": "nvs_marker", "args": {"dom": "dump"}, "op": "==", "value": "RESTORE_REQUIRED"},
                {"observe": "status", "args": {"dom": "dump"}, "op": "startswith",
                 "value": "RESTORE DEFERRED - outstanding Dump to Grid snapshot found at boot"},
                {"observe": "text_state", "args": {"entity": "ecco_restart_status"}, "op": "==", "value": ""},
                {"observe": "invariants", "args": {}, "op": "==", "value": []}],
     "classification": "FINDING-KNOWN:FCP2-F6", "invariant": "INV-20", "grade": "VERIFIED", "confidence": "low",
     "failure_outcome": "the owed Dump restore never completes; 244 stays at Allow Export and 256-261 at the lease power "
                        "(uncontained, no CRITICAL status) across the restart loop",
     "smallest_safe_repair_scope": "a design decision (FCP2-F6 restart loop): a stuck-restart counter in ESP32 RTC no-init "
                                   "memory (survives a software restart; no new NVS record), reset when an owed restore "
                                   "completes, plus a CRITICAL status naming 244 at Allow Export and 256-261 uncontained, "
                                   "plus corrected RESTARTING (stuck lock) wording; stopping automatic restarts after N "
                                   "is the separate F6 reboot-policy decision; lock rules and restore path unchanged",
     "notes": "F-FW08-1 (suite scenario FW-08-F). Stuck-lock restarts at at_s 308 and 511 (203 s apart); each boot starts "
              "5 s later (restart down 3 s, on_boot at uptime 2 s) and the leak recurs at uptime 10 s, before the first "
              "15 s Dump watchdog tick, so no restore attempt and no write follow the first leak. The core invariants "
              "explain the open restore by the held lock and see no resume: the loop is visible only to this "
              "characterisation (boot_no, bank, marker, blank Restart Status). Trigger hypothetical (MODEL); "
              "confidence low."},
]


def section_corpus() -> None:
    print("[16] corpus: every minimal replay document exists, matches its draft and replays OK with the _lab_trace engine")
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
        res = T.replay(doc)
        print(f"  info  corpus {d['id']}: ok={res.ok} drift={res.drift} digest_match={res.digest == doc['trace_digest']}")
        check(f"corpus {d['id']} ({doc['classification']}): matches the suite's draft and replays OK"
              + (" (source drift: expectations only)" if res.drift else " (trace digest identical)"),
              same and res.ok and not res.failed_expectations, f"same={same} {res.failed_expectations}")
    ids = sorted(d["id"] for d in CORPUS_DRAFTS)
    tabled = sorted(c for s in SCENARIOS.values() for c in s["corpus"])
    check("the scenario table and the corpus drafts name the same corpus documents", ids == tabled, f"{ids} {tabled}")
    drafts = {d["id"]: d for d in CORPUS_DRAFTS}
    built = {"FW-07-i": i_actions("ct", 256), "FW-07-i2": i_soc_actions(), "FW-07-i3": i_seed_actions(0, 10)}
    check("corpus FW-07-i / -i2 / -i3 carry exactly the action lists the suite's FW-07-I runs build (i_actions('ct', 256), "
          "i_soc_actions(), i_seed_actions(0, 10))", all(drafts.get(k, {}).get("actions") == v for k, v in built.items()),
          str([k for k, v in built.items() if drafts.get(k, {}).get("actions") != v]))
    # discrimination: each document must FAIL against an in-memory mutant of the guard it pins (the key expectation named)
    for cid, nid, pairs, key, why in (
            ("FW-07-d", "NC-FW07-4", MUT_STOP_BINDING, ("globals", "dump_comms_restore_attempts"),
             "record binding removed: every tick retries at any SOC"),
            ("FW-07-d", "NC-FW07-7", MUT_STOP_CFG, ("globals", "dump_comms_restore_attempts"),
             "the lower configured Stop SOC wins: no supervised retry at 24 %"),
            ("FW-07-i", "NC-FW07-8", MUT_CT_FAST, ("status_history", None),
             "the fast frozen-CT criterion removed: no GRID CT FROZEN end"),
            ("FW-07-i2", "NC-FW07-9", MUT_SOC_FROZEN, ("status_history", None),
             "the frozen-SOC term removed: the lease is still running"),
            ("FW-07-i3", "F-FW07-5 repair", MUT_CT_RANGE_SEED, ("globals", "dump_ct_same_bmin"),
             "the range seeded empty at START: no battery movement from outside the repeat window"),
            ("FW-08-c", "NC-FW08-1", MUT_NO_ESCALATION, ("boot_no", None), "no stuck-lock restart"),
            ("FW-08-d", "NC-FW08-1", MUT_NO_ESCALATION, ("boot_no", None), "no stuck-lock restart"),
            ("FW-08-e", "NC-FW08-1", MUT_NO_ESCALATION, ("boot_no", None), "no stuck-lock restart")):
        path = cdir / f"{cid}.json"
        fw = mutant(pairs)
        if fw is None or not path.is_file():
            check(f"corpus {cid} discriminates the {nid} mutant: mutant and document available", False, str(path.name))
            continue
        doc = T.load_doc(path)
        idx = [j for j, e in enumerate(doc["expect"]) if e["observe"] == key[0]
               and (key[1] is None or key[1] in e["args"].get("names", ()))]
        try:
            failed = replay_on(doc, fw)
        except Exception as exc:   # a crashing mutant replay is MUTANT-INVALID: a FAILURE of this check (never a kill)
            check(f"corpus {cid} replays against the {nid} mutant without a harness exception", False,
                  f"{type(exc).__name__}: {exc}")
            continue
        print(f"  info  corpus {cid} vs {nid} mutant ({why}): failed expectations "
              f"{[(f['observe'], f['observed']) for f in failed]}")
        check(f"corpus {cid} discriminates the {nid} mutant ({why}): its {key[0]} expectation fails there",
              len(idx) == 1 and idx[0] in [f["index"] for f in failed], f"{idx} {failed}")


MUTANT_TIER = "fw_runtime_mutant"


def replay_on(doc: dict, fw) -> list:
    """Replay a corpus document against the firmware `fw` (an in-memory mutant) with the _lab_trace engine, on a temporary
    tier that shares the firmware tier's ACTIONS / OBSERVERS (registered here, always removed in finally; never left in
    place); returns the failed expectations (the replay's own digest / drift verdict is irrelevant against a mutant)."""
    if T.registered(MUTANT_TIER)["factory"]:
        raise L.LabHarnessError(f"replay tier {MUTANT_TIER!r} is already registered")

    def factory(*, utc_start: int, seed: int, **kw):
        if "bank" in kw or "fw" in kw:
            raise L.LabHarnessError("replay_on: documents with bank / fw world kwargs are not supported here")
        return L.FirmwareWorld(fw, utc_start=utc_start, seed=seed, **kw)

    try:
        T.register_tier(MUTANT_TIER, factory)
        T.register_actions(MUTANT_TIER, L.ACTIONS)
        T.register_observers(MUTANT_TIER, L.OBSERVERS)
        return T.replay(dict(doc, tier=MUTANT_TIER)).failed_expectations
    finally:
        T.unregister_tier(MUTANT_TIER)


# =============================================================================================================================
# extended sweeps
# =============================================================================================================================
def section_extended() -> None:
    t = time.perf_counter()
    print("[17] EXTENDED: link-loss onset / outage sweeps, leak offset / watchdog order sweeps, FP outage sweep, frozen "
          "telemetry onset x cut point sweep")
    bad = []
    for down_after in range(60, 120, 5):
        r = run_07a(down_after=down_after, outage=200)
        v = inv17_violations(r) + rebased_restore_bound(r["w"], r["seq_up"], SG39_BOUND_S) + r["w"].invariants()
        if v:
            bad.append((down_after, v))
    check("EXT FW-07-A: for 12 link-loss onsets (5 s apart over a configuration-poll period) the lease ends TELEMETRY LOST "
          "within 75 s and the restore completes within the SG-39 bound after recovery", not bad, str(bad))
    bad = []
    for outage in (20, 40, 90, 150, 600, 1200):
        r = run_07a(outage=outage)
        w = r["w"]
        ended = bool(statuses(w, "dump_end", r["t_down"]))
        rb = rebased_restore_bound(w, r["seq_up"], SG39_BOUND_S)
        if (ended and (rb or completion_t(w, "dump", r["t_down"]) is None)) or w.invariants():
            bad.append((outage, ended, rb, w.invariants()))
        print(f"  info  EXT FW-07-A outage {outage} s: lease ended={ended}")
    check("EXT FW-07-A: for outages 20-1200 s, a lease that ended completes its restore within the SG-39 bound after the "
          "recovery and a lease that survived a short outage stays a valid lease; core invariants hold", not bad, str(bad))
    bad = []
    for off in (-60, -30, -14, -5, -1):
        for order in (("fp", "dump"), ("dump", "fp")):
            r = run_08b(offset_s=off, wd_order=order)
            v = escalation_violations(r["w"], r["t_leak"], "dump") + r["w"].invariants()
            if v:
                bad.append((off, order, v))
    check("EXT FW-08-B: a leak from 60 s to 1 s before the end epoch, both watchdog orders: escalation, restart and "
          "boot restore within the INV-20 bound; core invariants hold", not bad, str(bad))
    bad, lats = [], []
    for outage in (120, 300, 420, 700, 1000, 1200, 2000):
        r = run_07f(outage=outage)
        done = completion_t(r["w"], "fp", r["t_up"])
        lat = None if done is None else done - r["t_up"]
        lats.append((outage, lat))
        if lat is None or lat > q(BACKOFF_S[-1]) + FP_WD_S or r["w"].invariants():
            bad.append((outage, lat, r["w"].invariants()))
    print(f"  info  EXT FW-07-F FP restore latency after the recovery by outage (s): {lats}")
    check("EXT FW-07-F: for outages 120-2000 s the FP restore after the recovery completes within the rest of its current "
          "backoff window (<= 300 s + one FP watchdog tick): the F-FW07-1 delay follows the backoff phase, it is bounded; "
          "core invariants hold", not bad, str(bad))
    bad = []
    for signal, prefix in (("ct", CTF), ("bp", BPF)):
        for n_live in range(4, 10):
            for cut in (244, 256):
                r = run_07i(signal=signal, cut=cut, n_live=n_live)
                w, b = r["w"], r["boot_seq"]
                o = None if b is None else list(w.log)[b]["data"]["obl"]
                v = (frozen_end_violations(r, prefix, *CT_WIN) + misaligned(w, r["actions"], U0) + w.invariants()
                     + ([] if b is None else rebased_restore_bound(w, b, WD_FIRST_S)))
                if (v or o is None or o["nvs"]["dump"] != "RESTORE_REQUIRED" or not o["dump"]["snap"] or r["cut"] is None
                        or r["cut"]["data"]["addr"] != cut or not w.status("dump").startswith("RESTORED OK")):
                    bad.append((signal, n_live, cut, v[:2]))
    check("EXT FW-07-I: grid CT or battery power frozen after 4-9 live slots (the freeze onset across the watchdog phase), "
          "a power cut at the restore's 244 or 256-261 write: the frozen end within its window, the boot mirrors the stored "
          "obligation, the boot-path restore within 15 s, every core invariant holds (24 runs)", not bad, str(bad))
    print(f"  info  EXT sweeps runtime_s {time.perf_counter() - t:.3f}")


# =============================================================================================================================
# run
# =============================================================================================================================
section_table()
section_07a()
section_07b()
section_07c()
section_07d()
section_07e()
section_07f()
section_07g()
section_07h()
section_07i()
section_07i_seed()
section_08a()
section_08b()
section_08c()
section_08d()
section_08e()
section_08f()
# V0.1 (brief B6.7): the fallback is an uptime bound, not a grace counted from the loss - FW:59
# ecco_free_power_invalid_clock_grace_ms "300000"; Free Power watchdog FW:24152 and Dump FW:24238
# 'return millis() >= ${ecco_free_power_invalid_clock_grace_ms}UL;'
unsupported("FW-07-U1", "NTP loss after a first sync: only the first SNTP sync per boot is modelled (the firmware's "
                        "invalid-clock fallback ends a lease once THIS boot's uptime reaches 300 s, millis() >= "
                        "ecco_free_power_invalid_clock_grace_ms - an uptime bound, not a grace counted from the loss); after "
                        "a reboot both domains end the lease, so the fallback is unreachable in this tier")
unsupported("FW-08-U2", "a Fallback Review / Save hold or leak of the shared write mutex: the FB scripts and "
                        "interval [10] FB housekeeping do not transpile (NOT_EXECUTED)")
section_negative()
section_corpus()
if EXTENDED:
    section_extended()
for nid, fam, target, outcome in NC_RESULTS:
    print(f"  info  negative control {nid} [{fam}] {outcome}: {target}")
for fid, text in sorted(FINDINGS.items()):
    print(f"  info  finding {fid}: {text[:100]}")
COUNTED = sorted(f for f in FINDINGS if f not in DUPLICATE_OF)
print(f"  info  findings: {len(FINDINGS)} reproduced, {len(FINDINGS) - len(COUNTED)} duplicate(s) of another suite's root "
      f"cause (not counted), {len(COUNTED)} counted: {COUNTED}")
BLOCKED = [sid for sid, s in SCENARIOS.items() if s["classification"] == "BLOCKED"]   # LAB-SUMMARY 'blocked' (detected)
RUNTIME = time.perf_counter() - T0
print(f"  info  finding-reproduces checks: {len(FINDING_CHECKS)} (not counted as passes)")
print("")
check_phase_registry()
T.finish(SUITE, passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=FINDING_CHECKS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
