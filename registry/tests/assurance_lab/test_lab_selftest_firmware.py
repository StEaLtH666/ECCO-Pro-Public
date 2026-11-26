#!/usr/bin/env python3
"""Harness self-tests of the assurance lab FirmwareWorld (_lab_fw): content-marker discovery of the firmware's intervals and
on_boot items, the strict simulator (outcome allow-list, sealed entity registry, explicit bool switch / binary_sensor
states, per-instance select options, unseeded-register reads), the true UTC / Europe/London clock and realistic uptime,
the FULL-boot reboot primitive, the ESPHome preference (flash) model, the scheduler cadence, the real poll trees with their
MODEL handlers, the NVS / Modbus / link / bus / RTC-window fault policies ([8] each NVS commit mode on a USED key after a
completed-lease prelude; [8b] the B5 NVS USED-KEY RULE: every refused commit mode and per-key boot fault on a never-stored
key raises LabHarnessError naming the physical precondition, the same fault on a used key is accepted, a policy armed
before the first store fires after it, erase_all un-stores and a false ABSENT does not), power-cut capture, determinism,
the replay tier and every invariant checker with a hand-built negative control (INV-RESTORE-BOUND also with real-run
controls from two in-memory FP watchdog mutants). [16b] INV-NO-SILENT-OVERRIDE's hardened semantics (RAM-visible
obligations only, never judged inside a boot, level-based slices with world.quiet_state(), one violation per episode;
real-run controls incl. the in-memory mutant 'Dump on_boot reads a stored RESTORE_REQUIRED as CLEAR'); [16c] INV-BOOT-MIRROR (hand-built rule table,
the same mutant -> exactly one violation, a clean reboot during a lease and a same-runtime PR41 ghost -> none, the boot-fault
lockouts -> none); [16d] the HL-1 rule (V0.1 root fix): the lab ORIGINAL adopts the live bank only after an operator Accept
whose last published text is a firmware SUCCESS text and that cleared an obligation its domain held before, never for
registers another domain holds (hand-built rule table; real positive controls for FP and Dump; refused Accepts; the X-2
PB-01 seed 929 continuation and its masked direction, each with the V0 rule in memory as the negative control); [17b] the
replay additions (set_number, inject_global, r244_apply actions; text_state, quiet_state observers; the invariants filters
boot_from / tags / untagged / form) with refusal controls and two recorded documents.
Offline assurance lab V0 (test-only: no network, no Home Assistant, no hardware; writes nothing). These are HARNESS
capability checks: the firmware behaviours they drive (phantom marker, PR41 lockout, false ABSENT) are the Phase C
scenarios' subject and are not classified here.
Quick mode (about 7 s here) reboots from the four write captures of an FP START; ECCO_LAB_EXTENDED=1 / --extended reboots
from every capture point of it (about 8 s).
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
PINS: list[str] = []            # held 'finding-reproduces:' checks (none in a self-test; LAB-SUMMARY 'finding_pins')
COUNTED: list[str] = []         # counted findings (a self-test reproduces none)
UNSUPPORTED_POINTS: list[str] = []   # one catalogue id per printed UNSUPPORTED line (a self-test prints none)
BLOCKED: list[str] = []         # blocked scenarios (no scenario runs here)
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
PHASE_SENSITIVE_TAGS: dict[str, str] = {
    "export_trip: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "supervision: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "manual_tou: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "census: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "fp_wd: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "dump_wd: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "telemetry: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "config: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "owed_config: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "evidence_expiry: runs at uptime": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "1 s jobs whose first slot (1 s) precedes on_boot (2 s) run once": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "same tick, default wd_order ('fp', 'dump')": (
        "scheduler-model self-test of the same-tick watchdog tie (both 15 s watchdogs at uptime 15 s, ordered by "
        "wd_order): ESPHome draws independent offsets, so there is no shared tick (under the phase patch no watchdog "
        "runs at uptime 15 s and the check FAILS; guarded since the V0.1 review, formerly a ValueError that stopped "
        "the suite)"),
    "...wd_order=('dump', 'fp') runs the Dump watchdog first on the shared tick": (
        "scheduler-model self-test of the same-tick watchdog tie (both 15 s watchdogs at uptime 15 s, ordered by "
        "wd_order): ESPHome draws independent offsets, so there is no shared tick (under the phase patch no watchdog "
        "runs at uptime 15 s and the check FAILS; guarded since the V0.1 review, formerly a ValueError that stopped "
        "the suite)"),
    "phase_ms shifts a job's first run (FP watchdog at 22 s, 37 s)": (
        "scheduler-model self-test: pins the lab's own cadence (first run at startup_delay, else one period, after "
        "power-on, zero offset, due+T; HL-10) - fails under any ESPHome-like phase patch by design"),
    "pref_poll / pref_sync run on the 1 s grid from the first instant after boot": (
        "scheduler-model self-test of the two ESPHome framework jobs (PREF_JOBS) anchored at power-on with zero "
        "offset; ESPHome's RestoringGlobalsComponent (1000 ms) and IntervalSyncer are set_interval pollers with "
        "their own random first offset (fails under the phase patch with the PREF_JOBS part)"),
    "in-memory mutant flash_write_interval: 5s -> the sync runs every 5 s": (
        "pins the 5 s sync slots of the preferences syncer on the lab grid (PREF_JOBS: zero offset, anchored at "
        "power-on; fails under the phase patch with the PREF_JOBS part)"),
}
PHASE_SENSITIVE_EXTENDED_ONLY: tuple[str, ...] = ()
PHASE_SENSITIVE: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if any(name.startswith(p) for p in PHASE_SENSITIVE_TAGS):
        PHASE_SENSITIVE.append(name)
    if ok:
        (PINS if name.startswith("finding-reproduces:") else PASSES).append(name)
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


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
import re  # noqa: E402
import time  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _dump_sim as ds  # noqa: E402

U0 = C.parse_iso_utc("2026-10-21T10:50:00Z")    # a synthetic Wednesday, BST
FW = L.load_fw()
INFO = L.fw_info(FW)
ORIG = dict(L.SITE["original"])
FP_ARM_TEXT = "REJECTED - arm Free Power Write Enable first"
DUMP_ARM_TEXT = "REJECTED - arm Dump to Grid Write Enable first"
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")


def raises(exc_type, fn, *args, **kwargs) -> tuple[bool, str]:
    """(fn raised exc_type, its message). Any other exception propagates: a crash is a FAIL, never a pass."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return True, str(exc)
    return False, "no exception"


def world(warm: float = 60, **kw) -> L.FirmwareWorld:
    w = L.FirmwareWorld(utc_start=U0, **kw)
    if warm:
        w.run_for(warm)
    return w


def owned_bank(w) -> dict:
    return {a: w.bank[a] for a in L.OWNED}


def fw_count(text: str) -> int:
    return FW["_text"].count(text)


def dump_env(w) -> None:
    w.telemetry(grid_w=L.SITE["dump_grid_w"], batt_w=L.SITE["dump_battery_w"])


def ev(log, kind):
    return [e for e in log if e["kind"] == kind]


# =============================================================================================================================
def section_discovery() -> None:
    print("[0] firmware discovery by content markers; NOT_EXECUTED / PARTIAL / MODEL lists; source anchors")
    names = [j["name"] for j in INFO.jobs]
    check("every firmware interval is matched by exactly one content marker and every marker by exactly one interval",
          len(INFO.jobs) == len(FW["interval"]) == len(L.INTERVAL_SPECS) and sorted(names) == sorted(s[0] for s in L.INTERVAL_SPECS))
    for j in INFO.jobs:
        print(f"  info  interval [{j['index']:2}] {j['name']:<16} {j['period_ms'] / 1000:>4.0f} s startup "
              f"{'-' if j['startup_ms'] is None else str(j['startup_ms'] / 1000) + ' s':<7} "
              f"{'EXECUTED' if j['executed'] else 'NOT EXECUTED'}{' (partial: see PARTIAL)' if j['name'] in L.PARTIAL else ''}")
    for name, why in L.NOT_EXECUTED.items():
        print(f"  info  NOT_EXECUTED {name}: {why}")
    for name, why in L.PARTIAL.items():
        print(f"  info  PARTIAL {name}: {why}")
    for (sid, a, c), why in L.MODEL_HANDLERS.items():
        print(f"  info  MODEL handler {sid} {a}x{c}: {why}")
    for name, why in L.NOT_EXECUTED_BOOT.items():
        print(f"  info  NOT_EXECUTED_BOOT {name}: {why}")
    check("NOT_EXECUTED lists exactly the non-executed intervals (clock read, RTC tick, FB housekeeping, shadow), each with a "
          "reason", set(L.NOT_EXECUTED) == {j["name"] for j in INFO.jobs if not j["executed"]}
          == {"clock_read", "rtc", "fb_housekeeping", "shadow"} and all(len(v) > 30 for v in L.NOT_EXECUTED.values()))
    check("the executed jobs are [0] census, [1] export trip, [2] FP watchdog, [3] Dump watchdog, [5] telemetry, [6] config, "
          "[7] owed config, [9] evidence expiry, [12] supervision, [13] manual TOU",
          [(j["index"], j["name"]) for j in INFO.jobs if j["executed"]] == [
              (0, "census"), (1, "export_trip"), (2, "fp_wd"), (3, "dump_wd"), (5, "telemetry"), (6, "config"),
              (7, "owed_config"), (9, "evidence_expiry"), (12, "supervision"), (13, "manual_tou")])
    check("on_boot: items 0 (main), 2 (supervision nonce), 5 (Dump limits validation) execute; 1, 4 (static_assert) and 3 "
          "(FB durable read) are listed in NOT_EXECUTED_BOOT",
          [(b["index"], b["name"], b["executed"]) for b in INFO.boot_items] == [
              (0, "main", True), (1, "static_supervision", False), (2, "supervision_nonce", True),
              (3, "fb_boot_read", False), (4, "static_dump", False), (5, "dump_limits", True)]
          and set(L.NOT_EXECUTED_BOOT) == {"static_supervision", "static_dump", "fb_boot_read"})
    nonexec = [b for b in INFO.boot_items if not b["executed"]]
    check("...and each NOT_EXECUTED_BOOT item really does not transpile in a plain ds.Sim (the reason is true)",
          all(raises(ds.Unsupported, ds.Sim(FW).run_lambda, b["lambda"])[0] for b in nonexec))
    # negative control: a mutant that removes the FP watchdog's marker makes discovery fail loud
    marker = "if (id(free_power_restore_requested)) return true;"
    ok_anchor = fw_count(marker) == 1
    mutant = FW["_text"].replace(marker, "if (id(free_power_restore_requested)) { return true; }")
    hit, msg = raises(L.LabHarnessError, L.fw_info, L.load_fw(mutant)) if ok_anchor else (False, "anchor not unique")
    check("negative control: an in-memory mutant without the FP watchdog marker is REJECTED by discovery (no guess by index)",
          hit and "interval [2] matches 0 content markers" in msg, msg)
    check("the Block A / Block B MODEL handlers are built from the real lambdas' own statements (232 / 244, 250-261, "
          "268-279 caches and the freshness stamps found exactly once)",
          "id(cfg_block_b_seq)++;" in INFO.block_code[241] and INFO.block_code[241].count("manual_cfg_reg") == 25
          and INFO.block_code[200].count("manual_cfg_reg232_raw") == 1)
    tel = [b for b in L._reads(INFO.scripts["poll_inverter_telemetry"]["then"]) if int(b["start_address"]) == 150][0]
    raw = tel["on_response"]["then"][0]["lambda"]
    check("telemetry 150x47: every static_cast<int16_t>(values[k]) of the real decode is rewritten (28 of 28, none left)",
          raw.count("static_cast<") == 28 == len(L._CAST_RE.findall(raw)) and "static_cast" not in INFO.block_code[150])
    hit, msg = raises(L.LabUnsupported, L.rewrite_static_casts, "int x = static_cast<uint32_t>(values[1]);")
    check("...and any other static_cast form raises LabUnsupported (no silent partial rewrite)", hit, msg)
    text = FW["_text"]
    lambdas = []

    def walk(n):
        if isinstance(n, dict):
            for k, v in n.items():
                if k == "lambda" and isinstance(v, str):
                    lambdas.append(v)
                else:
                    walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk({k: v for k, v in FW.items() if not k.startswith("_")})
    refs = set()
    for code in lambdas:
        code = re.sub(r"//[^\n]*", "", code)
        refs |= set(re.findall(r"\bid\((\w+)\)", code))
    missing = sorted(refs - set(INFO.globals) - set(INFO.entities))
    check(f"every id() referenced in the firmware's {len(lambdas)} lambdas is a global or a sealed-registry entity",
          not missing and len(text) > 0, str(missing[:6]))
    counts = {(p, t): T.anchor_count(p, t) for p, t in L.SOURCE_ANCHORS}
    check("every SOURCE_ANCHORS snippet occurs exactly once in its file",
          all(c == 1 for c, _line in counts.values()), str({t[:40]: c for (p, t), (c, _l) in counts.items() if c != 1}))
    for (p, t), (_c, line) in counts.items():
        print(f"  info  anchor {p}:{line}  {t[:70]}")


# =============================================================================================================================
def section_strict() -> None:
    print("[1] StrictSim: outcome allow-list, sealed registry, bool switches / binary sensors, selects, unseeded reads")
    check("allow-lists are exactly the spec's write / read outcome vocabularies",
          L.WRITE_OUTCOMES == ("ok", "ack_not_applied", "error", "not_sent", "no_response_landed", "no_response_lost",
                               "timeout_landed", "timeout_lost", "custom_response")
          and L.READ_OUTCOMES == ("ok", "error", "not_sent", "no_response", "custom_response", "timeout"))
    w = world()
    w.modbus_policy(lambda kind, addr, count: "timout")
    hit, msg = raises(L.LabHarnessError, w.fp_start, power_w=3000, minutes=30)
    check("an outcome typo ('timout') returned by a policy RAISES at the first Modbus op (never a silent timeout)",
          hit and "timout" in msg and not w.writes(), msg)
    hit, msg = raises(L.LabHarnessError, w.modbus_policy, {"write:256": ["eror"]})
    check("...and a typo in a policy table is rejected when the table is installed", hit and "eror" in msg, msg)
    hit2, msg2 = raises(L.LabHarnessError, w.modbus_policy, {"*": "no_response"})
    check("...a '*' table entry must be valid for reads AND writes ('no_response' is read-only)", hit2, msg2)
    w = world()
    hit, msg = raises(L.LabHarnessError, w.sim.ent, "free_power_write_enabel")
    check("an unknown entity id (typo) RAISES: the registry is sealed (never a new NaN entity)", hit and "sealed" in msg, msg)
    check("the registry holds every firmware entity id (sensor, binary_sensor, switch, number, text_sensor, button, select, "
          "script, time, modbus, uart)", set(INFO.entities) <= set(w.sim.entities) and {k for k, _n in INFO.entities.values()}
          == {"sensor", "binary_sensor", "switch", "number", "text_sensor", "button", "select", "script", "time", "modbus",
              "uart"})
    sw = {eid: n for eid, (k, n) in INFO.entities.items() if k == "switch"}
    off = [eid for eid, n in sw.items() if n["restore_mode"] == "ALWAYS_OFF"]
    on = [eid for eid, n in sw.items() if n["restore_mode"] == "RESTORE_DEFAULT_ON"]
    check(f"after a FULL boot every unset ALWAYS_OFF switch ({len(off)}, the write enables and arms) reads exactly False",
          all(w.sim.ent(e).state is False for e in off) and {"free_power_write_enable", "dump_write_enable",
                                                              "dump_recovery_arm", "manual_config_write_enable"} <= set(off))
    check(f"...and every RESTORE_DEFAULT_ON switch ({len(on)}) reads True on a first boot",
          all(w.sim.ent(e).state is True for e in on) and len(on) == len(sw) - len(off))
    plain = ds.Sim(FW)
    check("contrast: in a plain ds.Sim the same unset arm is NaN and TRUTHY (the hazard the lab removes)",
          isinstance(plain.ent("dump_write_enable").state, float) and bool(plain.ent("dump_write_enable").state))
    bs = [eid for eid, (k, _n) in INFO.entities.items() if k == "binary_sensor"]
    check("every binary_sensor is a bool by construction (False until published)",
          all(isinstance(w.sim.ent(e).state, bool) for e in bs))
    hit, msg = raises(L.LabHarnessError, setattr, w.sim.ent("dump_write_enable"), "state", float("nan"))
    check("assigning NaN to a switch RAISES (NaN-truthy guard)", hit and "NaN-truthy" in msg, msg)
    hit, msg = raises(L.LabHarnessError, w.sim.ent("configuration_online").publish_state, "yes")
    check("publishing a non-bool to a binary_sensor RAISES", hit, msg)
    sel = w.sim.ent("manual_slot1_charge_source")
    check("selects answer current_option() per instance; ds.Entity itself has no current_option (no class-wide patch)",
          sel.current_option() == "None" and not hasattr(ds.Entity, "current_option")
          and w.sim.ent("manual_reg244_staged_target").current_option() == "Allow Export")
    hit, msg = raises(AttributeError, w.sim.ent("dump_status").current_option)
    check("...and a non-select has no current_option() (AttributeError, as on the base Sim)", hit)
    check("text sensors start '' and sensors NaN (ESPHome defaults)",
          w.sim.ent("ecco_restart_status").state == "" and math.isnan(w.sim.ent("ecco_pv1_voltage").state))
    w = world()
    w.bank.pop(244)
    hit, msg = raises(L.LabHarnessError, w.fp_start, power_w=3000, minutes=30)
    check("a read of a register the bank does not hold RAISES (never a silent 0 = Allow Export)",
          hit and "not seeded" in msg, msg)
    w = world()
    hit, msg = raises(L.LabHarnessError, w.set_number, "free_power_max_power", 9000)
    check("set_number refuses a value outside the firmware number's [min, max] loudly", hit and "outside" in msg, msg)
    hit, msg = raises(L.LabHarnessError, w.telemetry, soc=70.5)
    check("telemetry refuses a fractional SOC (register 184 holds an integer percent)", hit, msg)
    w2 = L.FirmwareWorld(utc_start=U0)
    hit, msg = raises(L.LabHarnessError, w2.run_for, 1, wd_order=("fp", "fp"))
    check("run_for refuses an invalid wd_order", hit, msg)


# =============================================================================================================================
def section_clock_boot() -> None:
    print("[2] clock and boot: UTC timeline, London local fields, realistic uptime, NTP via the real lambda, FULL on_boot")
    w = L.FirmwareWorld(utc_start=U0)
    check("a booted world starts at uptime boot_ms = 2 s (not the ds.Sim default 1000 s) at UTC utc_start",
          w.uptime_s == 2.0 and w.t_utc == U0 and w.sim.millis() == 2000 and w.boot_no == 0)
    now = w.sim.ent("ntp_time").now()
    check("id(ntp_time).now() derives Europe/London local fields from the UTC epoch (10:50Z on 2026-10-21 = 11:50 BST)",
          (now.hour, now.minute, now.is_dst, now.timestamp) == (11, 50, True, U0) and not now.is_valid())
    check("before the first NTP sync the clock is invalid and ntp_synced is false (boot published the sensor false)",
          w.sim.g["ntp_synced"] is False and w.sim.ent("ntp_synced_sensor").state is False)
    w.run_for(2.9)
    pre = w.sim.g["ntp_synced"]
    w.run_for(0.2)
    check("the real time: on_time_sync lambda runs at uptime ntp_after_s = 5 s (ntp_synced, sensor published, clock valid)",
          pre is False and w.sim.g["ntp_synced"] is True and w.sim.ent("ntp_synced_sensor").state is True
          and w.sim.ent("ntp_time").now().is_valid() and len(ev(w.log, "fw.ntp_sync")) == 1)
    w.run_for(3600)
    now = w.sim.ent("ntp_time").now()
    check("uptime and UTC move together through run_for (one hour later: 12:50 BST, uptime 3605.1 s = UTC + 2 s boot)",
          w.t_utc == U0 + 3603.1 and (now.hour, now.minute) == (12, 50) and abs(w.uptime_s - 3605.1) < 1e-9)
    counts = dict(w.job_counts)
    w.advance(30)
    check("advance() is raw: uptime and UTC move together and nothing runs (job counts unchanged)",
          w.t_utc == U0 + 3633.1 and abs(w.uptime_s - 3635.1) < 1e-9 and dict(w.job_counts) == counts)
    g = L.FirmwareWorld(utc_start=C.parse_iso_utc("2026-11-02T10:50:00Z"), ntp_after_s=None)
    n2 = g.sim.ent("ntp_time").now()
    check("in GMT the local hour equals the UTC hour (2026-11-02 10:50Z = 10:50 GMT); ntp_after_s=None never syncs",
          (n2.hour, n2.is_dst) == (10, False) and (g.run_for(60) or True) and g.sim.g["ntp_synced"] is False)
    boot = ev(w.log, "fw.boot")[0]
    loads = {e["data"]["key"] for e in w.log if e["kind"] == "fw.load" and e["boot"] == 0}
    check("the FULL on_boot ran: Free Power, Dump AND register 244 durable records were loaded in boot 0 (the FP-only slice "
          "never loads the Dump / reg244 tags)", {L.TAGS["fp.valid"], L.TAGS["dump.valid"], L.TAGS["r244.valid"]} <= loads
          and boot["data"]["reason"] == "first boot")
    check("...items 2 and 5 ran too: a supervision challenge and the Dump limits status were published",
          str(w.sim.ent("supervision_state_text").state) != "" and
          str(w.sim.ent("dump_limits_status").state).startswith("VALID - power ceiling 8000 W; maximum grid export 8000 W"))
    f = L.FirmwareWorld(utc_start=U0, dump_limits="factory")
    check("dump_limits='factory': the real boot validation reports the factory state (maximum grid export NOT CONFIGURED)",
          "NOT CONFIGURED" in str(f.sim.ent("dump_limits_status").state))
    d = L.FirmwareWorld(utc_start=U0, boot=None)
    hit, msg = raises(L.LabHarnessError, d.run_for, 10)
    check("boot=None defers the boot: actions refuse until world.boot()", hit and "not booted" in msg, msg)
    d.boot()
    hit2, _m = raises(L.LabHarnessError, d.boot)
    check("...world.boot() boots once; a second call refuses (use reboot)", d.boot_no == 0 and hit2)


# =============================================================================================================================
def section_cadence() -> None:
    print("[3] scheduler cadence: periods and startup delays from the firmware, same-tick watchdog order, phase, skips")
    declared = {j["name"]: (j["period_ms"], j["startup_ms"]) for j in INFO.jobs if j["executed"]}
    check("declared periods / startup delays (read from the firmware) are the ones this test expects",
          declared == {"census": (5000, None), "export_trip": (1000, None), "fp_wd": (15000, 15000),
                       "dump_wd": (15000, 15000), "telemetry": (10000, 5000), "config": (60000, 20000),
                       "owed_config": (2000, 30000), "evidence_expiry": (10000, None), "supervision": (1000, None),
                       "manual_tou": (1000, None)}, str(declared))
    w = L.FirmwareWorld(utc_start=U0)
    w.job_trace = []
    w.run_for(130)
    end = 132000
    got = {}
    for t, name in w.job_trace:
        got.setdefault(name, []).append(t)
    want = {"export_trip": list(range(2000, end + 1, 1000)), "supervision": list(range(2000, end + 1, 1000)),
            "manual_tou": list(range(2000, end + 1, 1000)), "census": list(range(5000, end + 1, 5000)),
            "fp_wd": list(range(15000, end + 1, 15000)), "dump_wd": list(range(15000, end + 1, 15000)),
            "telemetry": list(range(5000, end + 1, 10000)), "config": list(range(20000, end + 1, 60000)),
            "owed_config": list(range(30000, end + 1, 2000)), "evidence_expiry": list(range(10000, end + 1, 10000))}
    for name, times in want.items():
        check(f"{name}: runs at uptime {times[0] / 1000:g} s, then every {declared[name][0] / 1000:g} s "
              f"({len(times)} runs in the first {end / 1000:g} s)", got.get(name) == times,
              f"{(got.get(name) or [])[:5]}... {len(got.get(name) or [])} runs")
    check("1 s jobs whose first slot (1 s) precedes on_boot (2 s) run once at the first instant after boot, then on the grid",
          got.get("export_trip", [])[:2] == [2000, 3000], str(got.get("export_trip", [])[:2]))
    # V0.1 review (R3-6): a watchdog missing from the 15 s tick is this check's FAIL (never a ValueError crash)
    at15 = [n for t, n in w.job_trace if t == 15000]
    check("same tick, default wd_order ('fp', 'dump'): the FP watchdog runs before the Dump watchdog",
          "fp_wd" in at15 and "dump_wd" in at15 and at15.index("fp_wd") < at15.index("dump_wd"), f"jobs at 15 s: {at15}")
    w = L.FirmwareWorld(utc_start=U0)
    w.job_trace = []
    w.run_for(14, wd_order=("dump", "fp"))
    w.run_for(1, wd_order=("dump", "fp"))
    at15 = [n for t, n in w.job_trace if t == 15000]
    check("...wd_order=('dump', 'fp') runs the Dump watchdog first on the shared tick",
          "fp_wd" in at15 and "dump_wd" in at15 and at15.index("dump_wd") < at15.index("fp_wd"), f"jobs at 15 s: {at15}")
    w = L.FirmwareWorld(utc_start=U0, phase_ms={"fp_wd": 7000})
    w.job_trace = []
    w.run_for(40)
    fpw = [t for t, n in w.job_trace if n == "fp_wd"]
    check("phase_ms shifts a job's first run (FP watchdog at 22 s, 37 s)", fpw == [22000, 37000], str(fpw))
    w = L.FirmwareWorld(utc_start=U0)
    w.run_for(100, telemetry=False, config=False)
    check("telemetry=False / config=False suppress the telemetry, config and owed-config jobs (their slots pass)",
          w.job_counts["telemetry"] == 0 and w.job_counts["config"] == 0 and w.job_counts["owed_config"] == 0
          and w.job_counts["fp_wd"] == 6)
    w.run_for(10)
    check("...and the next run_for resumes them on their grid", w.job_counts["telemetry"] == 1)


# =============================================================================================================================
def section_fp_happy() -> L.FirmwareWorld:
    print("[4] Free Power happy path on the synthetic SITE: START -> lease -> watchdog end on the UTC epoch -> verified restore")
    w = world()
    t_start = w.t_utc
    status = w.fp_start(power_w=3000, minutes=30)
    obl = w.obligations()["fp"]
    check("START: the firmware's own ACTIVE text, lease active + durable snapshot + NVS marker RESTORE_REQUIRED",
          status.startswith("ACTIVE - VERIFIED OK; 58A grid charge") and obl["act"] and obl["snap"]
          and w.nvs_marker("fp") == "RESTORE_REQUIRED", status)
    check("START wrote B1 232, B2 230 (58 A = 3000 W / 52 V), B3 268-279, B4 256-261 (each attributed to fp)",
          [(x["addr"], x["vals"][0], x["dom"]) for x in w.writes()] == [(232, 1, "fp"), (230, 58, "fp"), (268, 100, "fp"),
                                                                        (256, 3000, "fp")])
    check("the lease end is the UTC epoch START + 30 min", obl["end"] == t_start + 1800, f"{obl['end']} vs {t_start + 1800}")
    hv = w.ha_view()
    check("ha_view (real template lambdas): fp_active, fp_snapshot_valid on, fp_op off, start attempts / successes 1",
          hv["fp_active"] and hv["fp_snapshot_valid"] and not hv["fp_op"] and hv["fp_start_attempts"] == 1
          and hv["fp_start_successes"] == 1 and not hv["dump_active"], str(hv))
    w.run_for(obl["end"] - w.t_utc - 1)
    check("one second before the end epoch the lease is still ACTIVE", w.obligations()["fp"]["act"], w.status("fp"))
    w.run_for(20)
    restored = [e for e in w.log if e["kind"] == "fw.status" and e["data"]["text"].startswith("RESTORED OK")]
    t_r = restored[0]["t_utc"] if restored else None
    check("the first FP watchdog tick at/after the end epoch restores: 'RESTORED OK - original inverter settings verified'",
          w.status("fp") == "RESTORED OK - original inverter settings verified" and t_r is not None
          and obl["end"] <= t_r <= obl["end"] + 15, f"restored at {t_r}, end {obl['end']}")
    check("...the bank is the synthetic ORIGINAL again, the marker CLEAR, RAM snapshot clear",
          owned_bank(w) == {a: ORIG[a] for a in L.OWNED} and w.nvs_marker("fp") == "CLEAR"
          and not w.obligations()["fp"]["snap"])
    check("status_history records the firmware's own sequence (STARTING ... ACTIVE ... RESTORING ... RESTORED OK)",
          w.status_history("fp")[:2] == ["Inactive", "STARTING - taking fresh inverter snapshot"]
          and "RESTORING - confirming live inverter state before writing" in w.status_history("fp"))
    check("every invariant holds on the clean FP run", not w.invariants(), str(w.invariants()))
    return w


def section_dump_happy() -> L.FirmwareWorld:
    print("[5] Dump to Grid happy path: START -> lease -> DURATION EXPIRED on the UTC epoch -> verified restore; manual END")
    w = world()
    dump_env(w)
    t_start = w.t_utc
    status = w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    obl = w.obligations()["dump"]
    check("START: the firmware's ACTIVE text, writes 256-261 (feed-forward ceiling) then 244 = 0 (Allow Export)",
          status.startswith("ACTIVE - VERIFIED OK; target 1000W export") and
          [(x["addr"], x["vals"]) for x in w.writes()] == [(256, [1000] * 6), (244, [0])], status)
    check("the Dump lease end is the UTC epoch START + 30 min", obl["end"] == t_start + 1800)
    w.run_for(obl["end"] - w.t_utc - 1)
    check("one second before the end epoch the Dump lease is still active", w.obligations()["dump"]["act"])
    w.run_for(20)
    check("the Dump watchdog ends it (DURATION EXPIRED) and restores 244 then 256-261, verified",
          w.status("dump_end") == "DURATION EXPIRED" and w.status("dump") == "RESTORED OK - original inverter settings verified"
          and owned_bank(w) == {a: ORIG[a] for a in L.OWNED} and w.nvs_marker("dump") == "CLEAR", w.status("dump"))
    check("every invariant holds on the clean Dump run", not w.invariants(), str(w.invariants()))
    m = world()
    dump_env(m)
    m.dump_start(power_w=1000, stop_soc=25, minutes=30)
    m.run_for(120)
    m.dump_end()
    check("a manual Dump END (the real End button) restores at once, verified", m.status("dump").startswith("RESTORED OK")
          and m.bank[244] == 2 and m.nvs_marker("dump") == "CLEAR", m.status("dump"))
    return w


def section_arms() -> None:
    print("[6] arms: an unset ALWAYS_OFF arm reads OFF and a START without arming is refused with the firmware's arm text")
    w = world()
    s = w.fp_start(power_w=3000, minutes=30, arm=False)
    check("FP START without the arm: refused with the firmware's own text, nothing written",
          s == FP_ARM_TEXT and fw_count(f'publish_state("{FP_ARM_TEXT}")') == 1 and not w.writes(), s)
    dump_env(w)
    s = w.dump_start(power_w=1000, stop_soc=25, minutes=30, arm=False)
    check("Dump START without the arm: refused with the firmware's own text, nothing written",
          s == DUMP_ARM_TEXT and fw_count(f'publish_state("{DUMP_ARM_TEXT}")') == 1 and not w.writes(), s)
    s = w.fp_start(power_w=3000, minutes=30)
    check("...the same START with the arm turned on is admitted and the firmware turns the arm off again",
          s.startswith("ACTIVE") and w.sim.ent("free_power_write_enable").state is False, s)


# =============================================================================================================================
def section_reboot() -> None:
    print("[7] the reboot primitive: FULL on_boot, carried NVS / bank / prefs / restore numbers, arms OFF, hooks re-bound")
    w = world()
    dump_env(w)
    w.dump_start(power_w=1500, stop_soc=25, minutes=30)
    w.run_for(60)
    n_log, t_cut = len(w.log), w.t_utc
    old_sim = w.sim
    w.reboot(down_s=5)
    obl = w.obligations()["dump"]
    check("reboot during an ACTIVE Dump lease ENDS it: 'ESP RESTARTED DURING LEASE - ended, not resumed', restore requested",
          w.status("dump_end") == "ESP RESTARTED DURING LEASE - ended, not resumed" and obl["req"] and not obl["run"])
    check("boot counter incremented, EventLog kept and continued, UTC continuous (cut + 5 s down + 2 s boot), uptime 2 s",
          w.boot_no == 1 and len(w.log) > n_log and w.log[n_log - 1]["seq"] == n_log - 1 and w.t_utc == t_cut + 7
          and w.uptime_s == 2.0 and not w.log.utc_regressions())
    check("a NEW StrictSim with fresh RAM: arms OFF (ALWAYS_OFF), NTP not yet synced, configuration_online false",
          w.sim is not old_sim and w.sim.ent("dump_write_enable").state is False and w.sim.g["ntp_synced"] is False
          and w.sim.ent("configuration_online").state is False and w.sim.g["dump_start_attempts"] == 0)
    check("staged restore_value numbers survive (dump_export_power 1500), NVS and the bank carried, prefs restored",
          w.sim.ent("dump_export_power").state == 1500.0 and w.nvs_marker("dump") == "RESTORE_REQUIRED"
          and w.bank[244] == 0 and w.sim.g["dump_max_export_w"] == 8000 and w.sim.g["dump_limits_valid"] is True)
    check("hooks re-bound to the new sim (outcome policy, event hook, publish hook, per-instance commit wrapper)",
          w.sim._policy == w._outcome and w.sim.event_hook == w._on_event and w.sim.publish_hook == w._on_publish
          and "commit_record" in vars(w.sim.D) and w.sim.D.commit_record is not old_sim.D.commit_record)
    w.run_for(20)
    check("the first Dump watchdog after boot (uptime 15 s) restores, verified; no lease resumed",
          w.status("dump") == "RESTORED OK - original inverter settings verified" and owned_bank(w) == {
              a: ORIG[a] for a in L.OWNED} and not w.invariants(["INV-NO-RESUME"]), w.status("dump"))
    f = world()
    f.fp_start(power_w=3000, minutes=60)
    f.run_for(300)
    f.reboot()
    o = f.obligations()["fp"]
    check("FP reboot (S3): restore_requested set, 'ACTIVE - reboot recovery pending', the lease is NOT running",
          o["act"] and o["req"] and not o["run"] and f.status("fp") == "ACTIVE - reboot recovery pending", f.status("fp"))
    f.run_for(20)
    check("...the first FP watchdog (uptime 15 s) restores the ORIGINAL; every invariant holds",
          f.status("fp").startswith("RESTORED OK") and owned_bank(f) == {a: ORIG[a] for a in L.OWNED}
          and not f.invariants(), str(f.invariants()))
    k = world()
    k.sim.ent("configuration_polling").publish_state(False)
    k.set_number("dump_export_power", 2000)
    k.reboot(keep_prefs=False)
    check("keep_prefs=False: restore_value numbers back to initial_value, RESTORE_DEFAULT_ON switches back ON",
          k.sim.ent("dump_export_power").state == 1000.0 and k.sim.ent("configuration_polling").state is True)
    k2 = world()
    k2.sim.ent("configuration_polling").publish_state(False)
    k2.run_for(1)
    k2.reboot()
    check("keep_prefs=True: a RESTORE_DEFAULT_ON switch keeps its last state (OFF) once it was flushed (1 s later)",
          k2.sim.ent("configuration_polling").state is False)


def r244_apply(w) -> str:
    """The owner's register 244 Apply through the real buttons (Load staging, target Allow Export, arm, Apply)."""
    w.press("load_reg244_staging")
    w.set_select("manual_reg244_staged_target", "Allow Export")
    w.set_switch("manual_config_write_enable", True)
    w.press("apply_reg244_settings_button")
    return w.status("r244")


def section_prefs() -> None:
    print("[7b] preferences (ESPHome flash): 1000 ms global poll + flash_write_interval sync; only flushed values survive")
    G = ["reg244_last_applied_valid", "reg244_last_applied_value"]
    check("flash_write_interval is parsed from the firmware's preferences: section (1s -> 1000 ms), not hard-coded",
          FW["preferences"]["flash_write_interval"] == "1s" and INFO.flash_write_ms == 1000
          and L.PREF_JOBS == ("pref_poll", "pref_sync") and L._GLOBALS_POLL_MS == 1000)
    w = L.FirmwareWorld(utc_start=U0)
    w.job_trace = []
    w.run_for(10)
    by = {}
    for t, n in w.job_trace:
        by.setdefault(t, []).append(n)
    polls = [t for t, n in w.job_trace if n == "pref_poll"]
    check("pref_poll / pref_sync run on the 1 s grid from the first instant after boot, after every firmware job of their "
          "instant (the poll before the sync)", polls == [t for t, n in w.job_trace if n == "pref_sync"]
          == list(range(2000, 12001, 1000)) and all(by[t][-2:] == ["pref_poll", "pref_sync"] for t in polls))
    w = world()
    s = r244_apply(w)
    ram, flushed = w.globals_view(G), {n: w.sim.pref_flushed[n] for n in G}
    check("reg244 Apply: the firmware sets reg244_last_applied_valid in RAM with no ->update(): nothing is flushed at "
          "once", s.startswith("VERIFIED OK - register 244 now 0") and ram["reg244_last_applied_valid"] is True
          and flushed["reg244_last_applied_valid"] is False, f"{s} {ram} {flushed}")
    w.reboot()
    check("...a power cut 0 ms after the assignment keeps the PREVIOUS flushed value (False) - the device would too",
          w.globals_view(G)["reg244_last_applied_valid"] is False and w.nvs_marker("r244") == "RESTORE_REQUIRED")
    w = world()
    r244_apply(w)
    w.run_for((L._GLOBALS_POLL_MS + INFO.flash_write_ms) / 1000)
    ok_flush = w.sim.pref_flushed["reg244_last_applied_valid"] is True
    w.reboot()
    check("...after poll + flash_write_interval (2 s) the global's own poll has queued it and the sync flushed it: it "
          "survives the reboot (True, value 0) beside the RESTORE_REQUIRED marker",
          ok_flush and w.globals_view(G) == {"reg244_last_applied_valid": True, "reg244_last_applied_value": 0}
          and w.nvs_marker("r244") == "RESTORE_REQUIRED", str(w.globals_view(G)))
    g = world()
    with g._acting("selftest_restart", {}):   # white-box: the apply and the owner's override restart at one instant
        r244_apply(g)
        g.set_switch("ecco_restart_arm", True)
        g.press("ecco_restart_button")
    check("a graceful restart at the same instant (the real gated Restart with its override arm) stores every restoring "
          "global and syncs first (on_shutdown): the value survives", g.boot_no == 1 and len(ev(g.log, "fw.restart")) == 1
          and g.globals_view(G)["reg244_last_applied_valid"] is True
          and g.status_history("r244")[-1].startswith("RECOVERY REQUIRED"), str(g.globals_view(G)))
    marker = "preferences:\n  flash_write_interval: 1s\n"
    m5 = FW["_text"].replace(marker, "preferences:\n  flash_write_interval: 5s\n") if fw_count(marker) == 1 else None
    f = world(fw=L.load_fw(m5)) if m5 else None
    if f is not None:
        f.job_trace = []
        r244_apply(f)
        f.run_for(1)
        at1 = f.sim.pref_flushed["reg244_last_applied_valid"]
        f.run_for(2)
        syncs = [t for t, n in f.job_trace if n == "pref_sync"]
    check("in-memory mutant flash_write_interval: 5s -> the sync runs every 5 s (the poll still every 1 s) and the "
          "applied value reaches flash only at the 5 s slot", f is not None and syncs == [65000] and at1 is False
          and f.sim.pref_flushed["reg244_last_applied_valid"] is True and f.info.flash_write_ms == 5000,
          "marker not unique" if f is None else f"syncs {syncs}")
    hit, msg = (raises(L.LabUnsupported, L.fw_info, L.load_fw(FW["_text"].replace(marker, "")))
                if fw_count(marker) == 1 else (False, "marker not unique"))
    check("...and a mutant without preferences: flash_write_interval is refused (the lab never guesses the default)",
          hit and "flash_write_interval" in msg, msg)
    n = world()
    n.set_number("dump_export_power", 2000)
    n.reboot()
    n2 = world()
    n2.set_number("dump_export_power", 2000)
    n2.run_for(1)
    n2.reboot()
    check("restore_value numbers share the flash model: a cut 0 ms after the owner's set loses it (1000, initial), 1 s "
          "later it survives (2000)", n.sim.ent("dump_export_power").state == 1000.0
          and n2.sim.ent("dump_export_power").state == 2000.0)
    k = world()
    k.sim.ent("configuration_polling").publish_state(False)
    k.reboot()
    check("...as do restoring switches: a publish 0 ms before the cut is lost (back to the default ON)",
          k.sim.ent("configuration_polling").state is True)
    hit, msg = raises(L.LabUnsupported, k.sim.ent("configuration_polling").turn_off)
    k.sim.ent("dump_write_enable").turn_off()
    check("turn_off() of a restoring switch (whose save the lab would miss) raises LabUnsupported; a non-restoring "
          "switch's turn_off() still works", hit and "restoring switch" in msg
          and k.sim.ent("dump_write_enable").state is False, msg)


def used_key_world(dom: str = "fp", fw=None) -> L.FirmwareWorld:
    """B5 completed-lease prelude (the corpus PB-01-a pattern: fp_start(minutes=1), run_for(200)): one 1-minute lease of
    `dom` ('fp' / 'dump') ended by its own watchdog with a verified restore, which commits the marker CLEAR (FP restore
    Phase D, firmware :10049-10051 'ecco_durable::ValidMarker cleared{...MARKER_CLEAR}'; Dump :20392-20397), so the
    domain's marker key is USED (stored earlier in this run) before any fault is injected on it. The prelude's result
    is checked once in [8] (the same deterministic world every time)."""
    w = world(fw=fw)
    if dom == "fp":
        w.fp_start(power_w=3000, minutes=1)
    else:
        dump_env(w)
        w.dump_start(power_w=1000, stop_soc=25, minutes=1)
    w.run_for(200)
    return w


def section_nvs() -> None:
    print("[8] NVS commit policy: landed / not_landed / false_negative / false_positive (per-instance commit wrapper), each "
          "on a USED key (B5: a completed-lease prelude first)")
    w = used_key_world("fp")
    d = used_key_world("dump")
    check("B5 used-key prelude (one completed 1-minute lease, the corpus PB-01-a pattern): FP and Dump each end 'RESTORED "
          "OK' with the stored marker CLEAR, so the marker key was stored earlier in the run (nvs_stored_earlier); on a "
          "fresh world it was not", w.status("fp").startswith("RESTORED OK") and w.nvs_marker("fp") == "CLEAR"
          and d.status("dump").startswith("RESTORED OK") and d.nvs_marker("dump") == "CLEAR"
          and w.nvs_stored_earlier("fp.valid") and d.nvs_stored_earlier("dump.valid")
          and not world().nvs_stored_earlier("fp.valid") and not world().nvs_stored_earlier("dump.valid"),
          f"{w.status('fp')} {w.nvs_marker('fp')} / {d.status('dump')} {d.nvs_marker('dump')}")
    n0 = len(w.writes())
    w.nvs_policy("fp.valid", L.ds.Durable.MARKER_RESTORE_REQUIRED, mode="false_negative")
    s = w.fp_start(power_w=3000, minutes=30)
    check("capability: false_negative on the FP Phase-B marker reproduces RAM snapshot_valid False while the durable "
          "marker is RESTORE_REQUIRED, with zero inverter writes",
          w.sim.g["free_power_snapshot_valid"] is False and w.nvs_marker("fp") == "RESTORE_REQUIRED"
          and len(w.writes()) == n0, s)
    fl = ev(w.log, "fault.nvs_commit")
    check("...the injected fault is logged (key, mode, record, what the firmware was told)",
          len(fl) == 1 and fl[0]["data"]["mode"] == "false_negative" and fl[0]["data"]["returned"] is False
          and fl[0]["data"]["rec"]["state"] == 1)
    # not_landed / false_positive store nothing: the key keeps its earlier record, the CLEAR of the prelude (a failed
    # commit leaves the stored record untouched: ecco_durable::commit_record firmware/include/ecco_durable_snapshot.h:93,
    # mirrored by _dump_sim.py:284-287; the lab's not_landed / false_positive branch writes nothing to sim.nvs)
    w = used_key_world("fp")
    n0 = len(w.writes())
    w.nvs_policy("fp.valid", 1, mode="not_landed")
    w.fp_start(power_w=3000, minutes=30)
    check("not_landed (used key): nothing stored - the earlier CLEAR record stays - firmware told False, nothing written",
          w.nvs_marker("fp") == "CLEAR" and not w.sim.g["free_power_snapshot_valid"] and len(w.writes()) == n0)
    w = used_key_world("fp")
    w.nvs_policy("fp.valid", 1, mode="false_positive")
    s = w.fp_start(power_w=3000, minutes=30)
    check("false_positive (used key): the firmware believes the marker committed (lease ACTIVE) but NVS still holds the "
          "earlier CLEAR record", s.startswith("ACTIVE") and w.nvs_marker("fp") == "CLEAR"
          and w.sim.g["free_power_snapshot_valid"] is True, s)
    w = world()
    fresh = not w.nvs_stored_earlier("fp.valid")
    w.nvs_policy("fp.valid", 1, mode="landed")
    w.nvs_policy("fp.valid", 1, mode="false_negative")
    s1 = w.fp_start(power_w=3000, minutes=1)
    w.run_for(100)
    s2 = w.fp_start(power_w=3000, minutes=30)
    fl = ev(w.log, "fault.nvs_commit")
    check("policies apply in order and are consumed: the 1st RR commit lands, the 2nd is a false negative",
          s1.startswith("ACTIVE") and not s2.startswith("ACTIVE") and w.nvs_marker("fp") == "RESTORE_REQUIRED"
          and len(fl) == 2, f"{s1} / {s2}")
    check("B5 used-key rule is judged when the fault FIRES, not when it is armed: that false_negative was armed on a key "
          "never stored yet and fired after the 1st RR commit landed - accepted",
          fresh and [x["data"]["mode"] for x in fl] == ["landed", "false_negative"], str([x["data"] for x in fl]))
    hit, msg = raises(L.LabHarnessError, w.nvs_policy, "fp.valid", 1, mode="lost")
    check("an unknown NVS mode is rejected", hit, msg)
    hit, msg = raises(L.LabHarnessError, w.nvs_policy, "fp.valdi", 1)
    check("an unknown NVS tag alias is rejected", hit, msg)


NEVER_STORED = "never stored earlier in this run"
REMOVE_FAILED = "ESP_ERR_NVS_REMOVE_FAILED"


def section_nvs_used_key() -> None:
    print("[8b] B5 NVS USED-KEY RULE (negative self-tests): not_landed / false_negative / false_positive commits and "
          "read_error / wrong_size boot faults on a key never stored earlier in the run raise LabHarnessError naming the "
          "physical precondition; the same fault on a used key (completed lease first) is accepted")
    check("the refused sets are exactly the three injected commit modes and the two per-key boot faults (landed and "
          "absent / read_error_all / erase_all keep their own rules)",
          L.NVS_USED_KEY_MODES == ("not_landed", "false_negative", "false_positive")
          and L.NVS_USED_KEY_BOOT_FAULTS == ("read_error", "wrong_size"))
    for mode in L.NVS_USED_KEY_MODES:
        w = world()
        armed, amsg = raises(L.LabHarnessError, w.nvs_policy, "fp.valid", 1, mode=mode)
        n_log = len(w.log)
        hit, msg = raises(L.LabHarnessError, w.fp_start, power_w=3000, minutes=30)
        fired = [x for x in w.log if x["seq"] >= n_log and x["kind"] == "fault.nvs_commit"]
        check(f"{mode} on the never-stored FP marker: arming is accepted, the faulting commit (the START's Phase-B RR "
              f"commit) raises LabHarnessError naming the key, the used-key precondition and ESP-IDF {REMOVE_FAILED}; "
              "the fault is neither logged nor consumed",
              not armed and hit and NEVER_STORED in msg and REMOVE_FAILED in msg and repr(mode) in msg
              and L.TAGS["fp.valid"] in msg and "earlier stored version of the key" in msg and not fired
              and w._nvs_policies[-1]["left"] == 1, f"{amsg} / {msg[:300]}")
        u = used_key_world("fp")
        n_log = len(u.log)
        hit, msg = raises(L.LabHarnessError, u.nvs_policy, "fp.valid", 1, mode=mode)
        if not hit:
            hit, msg = raises(L.LabHarnessError, u.fp_start, power_w=3000, minutes=30)
        fired = [x["data"]["mode"] for x in u.log if x["seq"] >= n_log and x["kind"] == "fault.nvs_commit"]
        check(f"...the same {mode} on the USED FP marker (completed lease first) is accepted and fires once",
              not hit and fired == [mode], f"{msg[:200]} {fired}")
    w = world()
    dump_env(w)
    w.nvs_policy(lambda k, r: k == L.TAGS["dump.valid"], None, mode="false_negative")
    hit, msg = raises(L.LabHarnessError, w.dump_start, power_w=1000, stop_soc=25, minutes=30)
    check("a key PREDICATE (fn) is judged on the actual key at the faulting commit: false_negative on the never-stored "
          "Dump marker raises", hit and NEVER_STORED in msg and L.TAGS["dump.valid"] in msg, msg[:300])
    d = used_key_world("dump")
    dump_env(d)
    n_log = len(d.log)
    d.nvs_policy(lambda k, r: k == L.TAGS["dump.valid"], None, mode="false_negative")
    hit, msg = raises(L.LabHarnessError, d.dump_start, power_w=1000, stop_soc=25, minutes=30)
    fired = [x["data"]["mode"] for x in d.log if x["seq"] >= n_log and x["kind"] == "fault.nvs_commit"]
    check("...and on the USED Dump marker (completed Dump lease first) it is accepted",
          not hit and fired == ["false_negative"], f"{msg[:200]} {fired}")
    e = used_key_world("fp")
    e.reboot(nvs_fault=("erase_all",))
    e.run_for(60)   # the configuration poll first (a START right after a boot is REJECTED - configuration offline)
    gone = not e.nvs_stored_earlier("fp.valid")
    e.nvs_policy("fp.valid", 1, mode="false_negative")
    hit, msg = raises(L.LabHarnessError, e.fp_start, power_w=3000, minutes=30)
    check("('erase_all',) un-stores every key: after a partition erase the used FP marker counts as never stored and a "
          "false_negative on it is refused", gone and hit and NEVER_STORED in msg, msg[:300])
    a = used_key_world("fp")
    a.reboot(nvs_fault=("absent", "fp.valid"))
    a.run_for(60)
    kept = a.nvs_marker("fp") == "ABSENT" and a.nvs_stored_earlier("fp.valid")
    n_log = len(a.log)
    a.nvs_policy("fp.valid", 1, mode="false_negative")
    hit, msg = raises(L.LabHarnessError, a.fp_start, power_w=3000, minutes=30)
    fired = [x["data"]["mode"] for x in a.log if x["seq"] >= n_log and x["kind"] == "fault.nvs_commit"]
    check("a false ABSENT does not un-store a key (a landed commit of it is in the EventLog): the record reads ABSENT yet "
          "a false_negative on it is accepted", kept and not hit and fired == ["false_negative"], f"{msg[:200]} {fired}")
    for kind in L.NVS_USED_KEY_BOOT_FAULTS:
        w = world()
        hit, msg = raises(L.LabHarnessError, w.reboot, nvs_fault=(kind, "dump.valid"))
        check(f"boot fault ('{kind}', dump.valid) on the never-stored Dump marker is refused (LabHarnessError naming the "
              "key, the used-key precondition and HL-6), as a false ABSENT of a missing record already is",
              hit and NEVER_STORED in msg and L.TAGS["dump.valid"] in msg and "HL-6" in msg and repr(kind) in msg,
              msg[:300])
        u = used_key_world("dump")
        hit, msg = raises(L.LabHarnessError, u.reboot, nvs_fault=(kind, "dump.valid"))
        fault = ev(u.log, "fault.nvs_boot")
        check(f"...the same ('{kind}', dump.valid) on the USED Dump marker (completed Dump lease first) is accepted: "
              "logged as fault.nvs_boot, boot 1 completes", not hit and u.boot_no == 1 and len(fault) == 1
              and fault[0]["data"]["fault"] == [kind, L.TAGS["dump.valid"]] and u.log.last(kind="fw.booted") is not None,
              msg[:200])
    e = used_key_world("dump")
    e.reboot(nvs_fault=("erase_all",))
    hit, msg = raises(L.LabHarnessError, e.reboot, nvs_fault=("read_error", "dump.valid"))
    check("...and after a partition erase the used Dump marker is never-stored again: a read_error on it is refused",
          hit and NEVER_STORED in msg, msg[:300])


def section_boot_faults() -> None:
    print("[9] boot NVS faults: absent (false ABSENT), read_error, read_error_all, wrong_size, erase_all")
    res = {}
    for fault in (("absent", "dump.valid"), ("read_error", "dump.valid"), ("read_error_all",), ("wrong_size", "dump.valid"),
                  ("erase_all",)):
        w = world()
        dump_env(w)
        w.dump_start(power_w=1000, stop_soc=25, minutes=30)
        w.run_for(30)
        w.reboot(nvs_fault=fault)
        res[fault[0]] = (w.nvs_marker("dump"), w.corrupt("dump"), w.obligations()["dump"]["snap"], w.status("dump"),
                         ev(w.log, "fault.nvs_boot")[-1]["data"]["fault"], w)
    a = res["absent"]
    check("('absent', tag): the marker reads ABSENT -> the firmware treats it as CLEAR ('Inactive', no snapshot, no lock)",
          a[0] == "ABSENT" and not a[1] and not a[2] and a[3] == "Inactive" and a[4] == ["absent", L.TAGS["dump.valid"]])
    v = a[5].invariants(["INV-NO-SILENT-OVERRIDE"])
    check("...the checker sees the live override with no visible obligation and tags it PLATFORM-ABSENT (harness "
          "capability; classifying it is the Phase C scenario's job)", len(v) >= 1 and all(x["tags"] == ["PLATFORM-ABSENT"]
                                                                                            for x in v), str(v[:1]))
    r = res["read_error"]
    check("('read_error', tag): UNKNOWN fail-closed lockout with the firmware's 'do NOT reboot' warning",
          r[1] and r[2] and "a reboot may make the record read as absent" in r[3], r[3])
    check("('read_error_all',): every load fails -> the same UNKNOWN lockout", res["read_error_all"][1]
          and "UNKNOWN" in res["read_error_all"][3])
    ws = res["wrong_size"]
    check("('wrong_size', tag): a malformed marker -> lockout (MALFORMED)", ws[0] == "MALFORMED" and ws[1], ws[3])
    e = res["erase_all"][5]
    check("('erase_all',): NVS and every preference lost -> Dump limits back to factory (maximum grid export NOT "
          "CONFIGURED), marker ABSENT", res["erase_all"][0] == "ABSENT" and e.sim.g["dump_max_export_w"] == 0
          and "NOT CONFIGURED" in str(e.sim.ent("dump_limits_status").state))
    w = world()
    hit, msg = raises(L.LabHarnessError, w.reboot, nvs_fault=("absent", "dump.valid"))
    check("a false ABSENT of a record that is not stored is refused (it needs a record to lose)", hit, msg)
    hit, msg = raises(L.LabHarnessError, w.reboot, nvs_fault=("flip", "dump.valid"))
    check("an unknown boot fault is refused", hit, msg)


# =============================================================================================================================
def section_power_cut() -> None:
    print("[10] power cut: arm_power_cut captures at the event, aborts the action, reboots from the capture; capture_points")
    w = world()
    w.arm_power_cut(kind="fw.commit", key="fp.valid", state=1)
    s = w.fp_start(power_w=3000, minutes=30)
    check("a cut at the FP marker commit: the START is aborted there (no inverter write at all), boot 1 from the capture",
          w.boot_no == 1 and w.cuts_fired == 1 and not w.writes() and len(ev(w.log, "cut.fired")) == 1, s)
    check("...the capture holds the landed marker: the new boot finds 'RECOVERY REQUIRED - saved snapshot found'",
          w.nvs_marker("fp") == "RESTORE_REQUIRED" and s == "RECOVERY REQUIRED - saved snapshot found", s)
    w.run_for(20)
    check("...and the boot path's restore clears it (nothing to undo: bank ORIGINAL)", w.nvs_marker("fp") == "CLEAR"
          and owned_bank(w) == {a: ORIG[a] for a in L.OWNED} and not w.invariants(), str(w.invariants()))
    w = world()
    w.arm_power_cut(kind="fw.write", addr=230)
    w.fp_start(power_w=3000, minutes=30)
    check("a cut right after the B2 write: B1 232 and B2 230 have landed in the captured bank, B3 / B4 never happen",
          w.bank[232] == 1 and w.bank[230] == 58 and w.bank[268] == 20 and [x["addr"] for x in w.writes()] == [232, 230])
    w.run_for(20)
    check("...after reboot the real restore puts the ORIGINAL back (marker CLEAR)", owned_bank(w) == {
        a: ORIG[a] for a in L.OWNED} and w.nvs_marker("fp") == "CLEAR", w.status("fp"))
    w = world()
    w.arm_power_cut(kind="fw.write")
    w.press("free_power_recovery_review_button")
    check("a cut never fires outside a world action (a bare press() leaves it armed)", w.boot_no == 0 and w._cut is not None)
    w = world()
    caps = w.capture_points(lambda x: x.fp_start(power_w=3000, minutes=30))
    kinds = [c["event"]["kind"] for c in caps]
    check("capture_points: one capture after EVERY fw event of the START (reads, commits, writes), in order",
          len(caps) == len([e for e in w.log if e["kind"] in ("fw.read", "fw.write", "fw.commit", "fw.load")
                            and e["seq"] >= caps[0]["seq"]]) and kinds.count("fw.write") == 4 and kinds.count("fw.commit") >= 5)
    points = list(range(len(caps))) if EXTENDED else [i for i, k in enumerate(kinds) if k == "fw.write"]
    bad = []
    for i in points:
        v = world()
        v.reboot_from(caps[i])
        v.run_for(20)
        if owned_bank(v) != {a: ORIG[a] for a in L.OWNED} or v.nvs_marker("fp") not in ("CLEAR", "ABSENT"):
            bad.append((i, kinds[i], v.status("fp")))
    check(f"reboot_from every {'capture' if EXTENDED else 'write capture'} ({len(points)}) of a fresh world restores the "
          f"ORIGINAL within one watchdog tick", not bad, str(bad[:3]))


def section_modbus_link() -> None:
    print("[11] Modbus policy, coupled link model, bus idle, foreign register writes")
    w = world()
    w.modbus_policy({"read:230x3": ["error"]})
    s = w.fp_start(power_w=3000, minutes=30)
    fm = ev(w.log, "fault.modbus")
    check("a table entry is consumed once (the START's first 230x3 read errors) and logged as fault.modbus",
          len(fm) == 1 and fm[0]["data"]["outcome"] == "error" and not s.startswith("ACTIVE"), s)
    w = world()
    w.modbus_policy({"read:230x3": ["error"], "read:*": "timeout"})
    outs = [w._outcome("read", 230, 3) for _ in range(3)] + [w._outcome("read", 244, 12)]
    check("the most specific key present decides: an exhausted one-shot list yields 'ok', never the wildcard's outcome "
          "(other reads still get the wildcard)", outs == ["error", "ok", "ok", "timeout"], str(outs))
    w = world()
    w.set_link(False)
    w.run_for(70)
    stamp = w.sim.g["dump_soc_last_update_ms"]
    check("link down: telemetry and configuration polls fail through their REAL handlers (telemetry_online and "
          "configuration_online false); no fresh SOC stamp", w.sim.ent("telemetry_online").state is False
          and w.sim.ent("configuration_online").state is False and stamp < w.sim.millis() - 60000)
    s = w.fp_start(power_w=3000, minutes=30)
    check("...and a START is refused with the firmware's own text (configuration offline), nothing written",
          s == "REJECTED - inverter configuration offline" and not w.writes(), s)
    w.set_link(True)
    w.run_for(70)
    check("link up again: both polls succeed and the online sensors recover", w.sim.ent("telemetry_online").state is True
          and w.sim.ent("configuration_online").state is True)
    w = world()
    w.set_bus_idle(False)
    s = w.fp_start(power_w=3000, minutes=30)
    check("bus not idle: START refused with the firmware's bus-busy text", s.startswith("REJECTED - Modbus bus busy"), s)
    w.reboot()
    check("the bus state is the world's and survives a reboot (new sim bus_idle False)", w.sim.bus_idle is False)
    w = world()
    w.set_register(257, 4321, actor="inverter")
    q = ev(w.log, "fw.quiet")[-1]["data"]
    check("set_register(actor='inverter') changes the bank and marks the register foreign (excluded from the ORIGINAL diff)",
          w.bank[257] == 4321 and 257 in w.foreign and q["diff"] == {} and w.original[257] == ORIG[257])
    w.set_register(258, 1234, actor="owner")
    check("set_register(actor='owner') updates the expected ORIGINAL", w.original[258] == 1234 and 258 not in w.foreign)


def section_polls() -> None:
    print("[12] telemetry and configuration: real poll trees, real 150-196 decode, MODEL Block A / B handlers")
    w = world()
    w.telemetry(soc=64, batt_v=51.5, batt_w=-800, grid_w=-250, pv_w=1200, house_w=400)
    st = {e: w.sim.ent(e).state for e in ("ecco_battery_soc", "ecco_battery_voltage", "ecco_battery_power",
                                          "ecco_grid_ct_power", "ecco_pv_power", "ecco_load_power")}
    check("the real decode publishes the env through registers 150-196 (SOC 64, 51.5 V, signed battery / grid powers "
          "within the 1 W noise, PV 1200, load 400)",
          st["ecco_battery_soc"] == 64 and abs(st["ecco_battery_voltage"] - 51.5) < 1e-9 and abs(st["ecco_battery_power"] + 800) <= 1
          and abs(st["ecco_grid_ct_power"] + 250) <= 1 and st["ecco_pv_power"] == 1200 and st["ecco_load_power"] == 400, str(st))
    check("...through the real sensor on_value hooks (the SOC and grid freshness stamps are this poll's millis())",
          w.sim.g["dump_soc_last_update_ms"] == w.sim.millis() == w.sim.g["dump_grid_last_update_ms"])
    w.set_register(251, 430, actor="owner")
    w.set_register(269, 33, actor="owner")
    seq0, disp0 = w.sim.g["cfg_block_b_seq"], w.sim.g["cfg_block_b_dispatch_seq"]
    w.config_poll()
    check("config_poll: the real dispatch stamps the dispatch generation; MODEL Block B caches 244 / 250-261 / 268-279 "
          "from the bank and bumps cfg_block_b_seq / ok_ms / response_dispatch_seq",
          w.sim.g["manual_cfg_reg251_raw"] == 430 and w.sim.g["manual_cfg_reg269_raw"] == 33
          and w.sim.g["manual_cfg_reg244_raw"] == 2 and w.sim.g["cfg_block_b_seq"] == seq0 + 1
          and w.sim.g["cfg_block_b_dispatch_seq"] == disp0 + 1 == w.sim.g["cfg_block_b_response_dispatch_seq"]
          and w.sim.g["cfg_block_b_ok_ms"] == w.sim.millis() and w.sim.g["manual_config_raw_cache_valid"] is True)
    q = world(noise=False)
    dump_env(q)
    q.dump_start(power_w=1000, stop_soc=25, minutes=30)
    q.run_for(1900)
    check("why the noise MODEL exists: with noise=False the firmware's own frozen-battery detector (real on_value hook) "
          "ends the lease on exact repeats", q.status("dump_end").startswith("BATTERY POWER TELEMETRY FROZEN"),
          q.status("dump_end"))
    t = w.t_utc
    w.rtc_lock_windows([(t, t + 30)])
    seq1 = w.sim.g["cfg_block_b_seq"]
    w.config_poll()
    check("the firmware's own skip conditions gate the stand-ins: inside an RTC lock window the dispatch is refused "
          "(nothing stamped)", w.sim.g["correction_in_progress"] is True and w.sim.g["cfg_block_b_seq"] == seq1)
    w.run_for(31)
    check("...and the lock clears at the window's end (MODEL edge)", w.sim.g["correction_in_progress"] is False)


def section_rtc_window() -> None:
    print("[13] RTC lock windows (MODEL): correction_in_progress inside [utc_a, utc_b); FP watchdog defers")
    w = world()
    w.fp_start(power_w=3000, minutes=2)
    end = w.obligations()["fp"]["end"]
    w.rtc_lock_windows([(end - 20, end + 80)])
    w.run_for(end - w.t_utc + 60)
    check("the FP restore is deferred past the end epoch while the window holds the lock",
          w.sim.g["correction_in_progress"] is True and w.obligations()["fp"]["act"], w.status("fp"))
    w.run_for(40)
    check("after the window the watchdog restores; INV-RESTORE-BOUND is explained by the lock (no violation)",
          w.status("fp").startswith("RESTORED OK") and not w.invariants(), str(w.invariants()))
    locks = [e["data"]["locked"] for e in ev(w.log, "env.rtc_lock")]
    check("the window model's state is logged at install (free), at its start (locked) and at its end (free)",
          locks == [False, True, False], str(locks))


def section_operators() -> None:
    print("[14] operator paths, manual slot apply, restart button")
    w = world()
    w.fp_start(power_w=3000, minutes=10)
    w.run_for(30)
    w.set_register(257, 4321, actor="inverter")
    w.run_for(600)
    check("FP restore that sees a foreign 257 ends in the firmware's OPERATOR DECISION REQUIRED lockout",
          w.status("fp").startswith("OPERATOR DECISION REQUIRED") and w.sim.g["free_power_operator_needed"])
    s = w.fp_operator("FORCE_RESTORE_ORIGINAL")
    check("fp_operator FORCE (Review, arm, the real API action with the confirmation phrase) restores and clears",
          s.startswith("FORCE RESTORE ORIGINAL SUCCESS") and w.nvs_marker("fp") == "CLEAR" and w.bank[257] == ORIG[257], s)
    w = world()
    dump_env(w)
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(60)
    w.reboot()
    w.set_register(257, 4321, actor="owner")
    w.run_for(30)
    check("a Dump register changed while the dongle was down is KEPT: operator decision required",
          w.sim.g["dump_operator_needed"] and w.bank[257] == 4321 and w.nvs_marker("dump") == "RESTORE_REQUIRED")
    s = w.dump_force_restore()
    check("dump_force_restore (arm + the real Force button) restores the snapshot ORIGINAL",
          s.startswith("RESTORED OK") and w.bank[257] == ORIG[257] and w.nvs_marker("dump") == "CLEAR", s)
    w = world()
    s = w.manual_slot_apply(2, soc=55)
    check("manual_slot_apply: the real Load / Apply buttons verify slot 2; the owner's value becomes the ORIGINAL; "
          "invariants hold", s.startswith("VERIFIED OK") and w.bank[269] == 55 and w.original[269] == 55
          and not w.invariants(), f"{s} {w.invariants()}")
    w = world()
    dump_env(w)
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(30)
    w.sim.g["manual_write_in_progress"] = True   # a leaked transaction lock
    w.run_for(240)
    check("a leaked lock escalates (>180 s) and the firmware presses its restart button: the world performs the restart "
          "(graceful reboot) and the boot path takes over", w.boot_no == 1 and len(ev(w.log, "fw.restart")) == 1
          and w.status("dump_end") == "ESP RESTARTED DURING LEASE - ended, not resumed")
    w.run_for(30)
    check("...after the restart the owed Dump restore completes", w.status("dump").startswith("RESTORED OK")
          and w.nvs_marker("dump") == "CLEAR")


# =============================================================================================================================
def run_det(minutes=30, seed=3):
    w = world(seed=seed)
    w.fp_start(power_w=3000, minutes=minutes)
    w.run_for(1900)
    w.reboot()
    dump_env(w)
    w.dump_start(power_w=1000, stop_soc=25, minutes=10)
    w.run_for(700)
    return w.log.digest(), len(w.log)


def section_determinism() -> None:
    print("[15] determinism: same seed and actions -> identical EventLog digest")
    a, b = run_det(), run_det()
    check(f"two identical runs give the identical EventLog ({a[1]} events, digest {a[0][:12]})", a == b)
    c = run_det(minutes=31)
    check("a one-minute change in an action changes the digest", c[0] != a[0])


# =============================================================================================================================
def _ev(seq, kind, data, src="fw", t=0, boot=0):
    return {"seq": seq, "t_utc": U0 + t, "up_ms": 1000 * t, "boot": boot, "src": src, "kind": kind, "data": data}


def _obl(**over):
    base = {"act": False, "snap": False, "op": False, "req": False, "corrupt": False, "opn": False, "end": 0, "marker": 0,
            "run": False, "due": False}
    o = {"fp": dict(base), "dump": dict(base), "r244": {"snap": False, "corrupt": False, "op": False}, "mw": False,
         "cip": False, "nvs": {"fp": "CLEAR", "dump": "CLEAR", "r244": "CLEAR"}}
    for k, v in over.items():
        if k in ("mw", "cip"):
            o[k] = v
            continue
        dom, f = k.split("_", 1)
        if dom == "nvs":
            o["nvs"][f] = v
        else:
            o[dom][f] = v
    return o


def _write(seq, addr, vals, dom, nvs=None, ram=None, t=0, boot=0):
    r = {"fp_act": False, "fp_snap": False, "fp_corrupt": False, "dump_act": False, "dump_snap": False,
         "dump_corrupt": False, "r244_snap": False, "r244_corrupt": False, **(ram or {})}
    return _ev(seq, "fw.write", {"addr": addr, "vals": vals, "outcome": "ok", "landed": True, "scripts": [f"x_{dom}"],
                                 "dom": dom, "nvs": {"fp": "CLEAR", "dump": "CLEAR", "r244": "CLEAR", **(nvs or {})},
                                 "ram": r}, t=t, boot=boot)


def section_invariants(clean_worlds) -> None:
    print("[16] invariant checkers: each catches a hand-built violation and passes clean runs")
    for name, fn in L.INVARIANTS.items():
        bad = [v for cw in clean_worlds for v in fn(list(cw.log)) + fn(cw.log, world=cw)]
        check(f"{name}: no violation on the clean FP / Dump / reboot runs (with and without the world)", not bad,
              str(bad[:2]))
    v = L.check_write_surface([_write(0, 245, [1], "dump")])
    check("INV-WS catches a write to 245 (outside the surface)", len(v) == 1 and v[0]["inv"] == "INV-WS")
    check("INV-WS passes a write to 244 / 256-261", not L.check_write_surface([_write(0, 244, [0], "dump"),
                                                                                 _write(1, 256, [1] * 6, "dump")]))
    v = L.check_one_lease([_ev(0, "fw.obl", _obl(fp_act=True, dump_act=True))])
    check("INV-ONE-LEASE catches FP and Dump both active", len(v) == 1 and v[0]["inv"] == "INV-ONE-LEASE")
    lg = [_write(0, 256, [1000] * 6, "dump", nvs={"fp": "RESTORE_REQUIRED"})]
    v = L.check_no_second_restorer(lg)
    check("INV-NO-2ND-RESTORER catches a Dump write to 256-261 while FP holds a durable RESTORE_REQUIRED marker (writer "
          "recorded, no N17 tag while FP is not corrupt)", len(v) == 1 and "dump wrote 256" in v[0]["detail"]
          and v[0]["tags"] == [])
    v = L.check_no_second_restorer([_write(0, 256, [8000] * 6, "fp", nvs={"dump": "RESTORE_REQUIRED"},
                                           ram={"dump_corrupt": True})])
    check("...and tags the known residual N17 when the holder (Dump) is corrupt-locked", len(v) == 1 and v[0]["tags"] == ["N17"])
    check("...but not the holder's own restore", not L.check_no_second_restorer(
        [_write(0, 256, [8000] * 6, "fp", nvs={"fp": "RESTORE_REQUIRED"})]))
    lg = [_ev(0, "fw.booted", {"boot": 1, "obl": _obl(dump_act=True, dump_run=True, dump_snap=True)}, boot=1)]
    v = L.check_no_resume(lg)
    check("INV-NO-RESUME catches a lease running after a reboot without a new START", len(v) == 1)
    lg = [_ev(0, "fw.booted", {"boot": 1, "obl": _obl()}, boot=1), _ev(1, "fw.start", {"dom": "dump"}, boot=1),
          _ev(2, "fw.obl", _obl(dump_act=True, dump_run=True), boot=1)]
    check("...but not one after a new START", not L.check_no_resume(lg))
    v = L.check_lockout_quiet([_write(0, 256, [3000] * 6, "fp", ram={"fp_corrupt": True})])
    check("INV-LOCKOUT-QUIET catches a write to a corrupt-locked domain's registers", len(v) == 1)
    check("...and exempts the SG-02 literal 244 = 2", not L.check_lockout_quiet([_write(0, 244, [2], "dump",
                                                                                      ram={"dump_corrupt": True})]))
    lg = [_ev(0, "fw.quiet", {"diff": {"244": [2, 0]}, "visible": []})]
    v = L.check_no_silent_override(lg)
    check("INV-NO-SILENT-OVERRIDE catches an owned-register override with no visible obligation", len(v) == 1
          and v[0]["tags"] == [])
    lg = [_ev(0, "fault.nvs_boot", {"fault": ["absent", L.TAGS["dump.valid"]]}, src="lab"), lg[0] | {"seq": 1}]
    v = L.check_no_silent_override(lg)
    check("...and tags PLATFORM-ABSENT when an injected false ABSENT preceded it", len(v) == 1
          and v[0]["tags"] == ["PLATFORM-ABSENT"])
    check("...an override WITH a visible obligation is not a violation",
          not L.check_no_silent_override([_ev(0, "fw.quiet", {"diff": {"244": [2, 0]}, "visible": ["dump.snap"]})]))
    due = _obl(fp_snap=True, fp_act=True, fp_due=True, nvs_fp="RESTORE_REQUIRED")
    lg = [_ev(0, "fw.obl", due, t=0), _ev(1, "fw.obl", _obl(), t=200)]
    v = L.check_restore_bound(lg)
    check("INV-RESTORE-BOUND catches a due restore that took 200 s (> 60 s) with nothing to explain it", len(v) == 1)
    lg2 = [lg[0], _ev(1, "fault.modbus", {"op": "read"}, src="lab", t=10), _ev(2, "fw.obl", _obl(), t=200)]
    check("...but not when a Modbus fault inside the due period explains it", not L.check_restore_bound(lg2))
    check("...nor a restore within the bound", not L.check_restore_bound([lg[0], _ev(1, "fw.obl", _obl(), t=20)]))
    check("...an open due period older than the bound at the end of the log is caught",
          len(L.check_restore_bound([lg[0], _ev(1, "lab.x", {}, src="lab", t=300)])) == 1)
    rr = {"nvs_fp": "RESTORE_REQUIRED"}
    start = [_ev(0, "fw.obl", _obl(fp_snap=True, fp_due=True, fp_op=True, mw=True, **rr)),       # mid-START: due, locked
             _ev(1, "fw.obl", _obl(fp_snap=True, fp_act=True, fp_op=True, mw=True, **rr)),
             _ev(2, "fw.obl", _obl(fp_snap=True, fp_act=True, **rr))]                            # the lease runs
    late = [_ev(3, "fw.obl", _obl(fp_snap=True, fp_act=True, fp_due=True, **rr), t=1800),         # end epoch reached
            _ev(4, "fw.obl", _obl(fp_snap=True, fp_act=True, fp_due=True, fp_op=True, mw=True, **rr), t=2413),
            _ev(5, "fw.obl", _obl(fp_op=True, mw=True), t=2413),          # completed INSIDE the restore's own lock
            _ev(6, "fw.obl", _obl(), t=2413)]
    v = L.check_restore_bound(start + late)
    check("INV-RESTORE-BOUND: the START's mid-transaction due period is discarded once the lease runs, and the late "
          "restore's own 0 s lock does not explain it (exactly one violation, at the end-epoch due event)",
          len(v) == 1 and v[0]["seq"] == 3 and "613 s" in v[0]["detail"], str(v))
    check("...the same START followed by a running lease to the end of the log is no obligation (no violation)",
          not L.check_restore_bound(start + [_ev(3, "lab.x", {}, src="lab", t=5000)]))
    due = _obl(fp_snap=True, fp_act=True, fp_due=True, **rr)

    def lock_run(name, on_t, off_t, done_t=200):
        on = dict(due, **{name: True}) if name in ("mw", "cip") else _obl(fp_snap=True, fp_act=True, fp_due=True,
                                                                          **{name: True}, **rr)
        return [_ev(0, "fw.obl", due), _ev(1, "fw.obl", on, t=on_t), _ev(2, "fw.obl", due, t=off_t),
                _ev(3, "fw.obl", _obl(), t=done_t)]
    check("...a manual-write lock held >= one watchdog period (30 s) inside the due period explains a 200 s restore",
          not L.check_restore_bound(lock_run("mw", 10, 40)))
    check("...a lock held < one watchdog period (2 s) does not", len(L.check_restore_bound(lock_run("mw", 10, 12))) == 1)
    check("...another domain's transaction held 30 s explains; the domain's OWN transaction held 90 s never does",
          not L.check_restore_bound(lock_run("dump_op", 10, 40))
          and len(L.check_restore_bound(lock_run("fp_op", 10, 100))) == 1)
    pre = [_ev(0, "fw.obl", _obl(cip=True), t=-50), _ev(1, "fw.obl", dict(due, cip=True), t=0),
           _ev(2, "fw.obl", due, t=10), _ev(3, "fw.obl", _obl(), t=200)]
    check("...a lock taken before the due period counts only from its opening (10 s inside: not an explanation)",
          len(L.check_restore_bound(pre)) == 1)
    link = [_ev(0, "env.link", {"up": False}, src="lab", t=-30), _ev(1, "fw.obl", due), _ev(2, "fw.obl", _obl(), t=200)]
    check("...a link that went down BEFORE the due period and stays down explains it (state, not only the edge)",
          not L.check_restore_bound(link))
    gone = [_ev(0, "fw.obl", due), _ev(1, "fw.obl", _obl(**rr), t=5), _ev(2, "lab.x", {}, src="lab", t=300)]
    v = L.check_restore_bound(gone)
    check("...a RAM snapshot cleared while the durable marker is still RESTORE_REQUIRED is NOT a completion (still open)",
          len(v) == 1 and "still open" in v[0]["detail"], str(v))
    anchor = "return (uint32_t) now.timestamp >= id(free_power_end_epoch);"
    real = {}
    for tag, rep in (("never", "return false;"),
                     ("late600", "return (uint32_t) now.timestamp >= id(free_power_end_epoch) + 600U;")):
        if fw_count(anchor) != 1:
            break
        m = world(fw=L.load_fw(FW["_text"].replace(anchor, rep)))
        m.fp_start(power_w=3000, minutes=30)
        end = m.obligations()["fp"]["end"]
        m.run_for(5400)
        ok_t = [e["t_utc"] for e in m.log if e["kind"] == "fw.status" and e["data"]["dom"] == "fp"
                and e["data"]["text"].startswith("RESTORED OK")]
        real[tag] = (L.check_restore_bound(m.log, world=m), end, ok_t, m.obligations()["fp"]["act"],
                     {e["seq"]: e["t_utc"] for e in m.log})
    nv = real.get("never")
    check("real-run negative control: in-memory FP watchdog mutant 'return false;' (exact-count anchor) - the lease never "
          "ends - yields exactly ONE INV-RESTORE-BOUND violation, opened at the end epoch (not at START)",
          nv is not None and nv[2] == [] and nv[3] and len(nv[0]) == 1 and nv[0][0]["inv"] == "INV-RESTORE-BOUND"
          and "still open" in nv[0][0]["detail"] and nv[1] <= nv[4][nv[0][0]["seq"]] <= nv[1] + 1,
          "anchor not unique" if nv is None else str(nv[0]))
    lt = real.get("late600")
    check("real-run negative control: mutant '>= end + 600U' restores 613 s late (RESTORED OK) -> exactly ONE "
          "INV-RESTORE-BOUND violation although the completing restore holds its own lock",
          lt is not None and len(lt[2]) == 1 and lt[2][0] - lt[1] >= 600 and len(lt[0]) == 1
          and lt[0][0]["inv"] == "INV-RESTORE-BOUND" and "completed only after" in lt[0][0]["detail"],
          "anchor not unique" if lt is None else str(lt[0]))
    cl = [L.check_restore_bound(cw.log, world=cw) for cw in clean_worlds[:2]]
    check("...and the clean FP and Dump leases (restored within one watchdog tick of the end epoch) yield none",
          cl == [[], []] and clean_worlds[0].status("fp").startswith("RESTORED OK")
          and clean_worlds[1].status("dump").startswith("RESTORED OK"), str(cl))
    hit, msg = raises(L.LabHarnessError, L.check_invariants, [], names=["INV-XX"])
    check("check_invariants rejects an unknown invariant id", hit, msg)


# =============================================================================================================================
def _q(seq, diff, visible, t=0, boot=0):
    return _ev(seq, "fw.quiet", {"diff": diff, "visible": visible}, t=t, boot=boot)


def _booted(seq, boot=1, t=0, **over):
    return _ev(seq, "fw.booted", {"boot": boot, "obl": _obl(**over)}, t=t, boot=boot)


DUMP_RR_ANCHOR = ("uint8_t state = have_marker ? marker.state : (uint8_t) ecco_durable::MARKER_CLEAR;\n"
                  "              id(dump_marker_state) = state;")
DUMP_RR_MUTANT = "uint8_t state = (uint8_t) ecco_durable::MARKER_CLEAR;\n              id(dump_marker_state) = state;"


def dump_lease_reboot(fw=None, after_s=120) -> L.FirmwareWorld:
    w = world(fw=fw)
    dump_env(w)
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(60)
    w.reboot()
    w.run_for(after_s)
    return w


def section_silent_override() -> None:
    print("[16b] INV-NO-SILENT-OVERRIDE: RAM-visible obligations, never inside a boot, level-based slices, one per episode")
    D = {"244": [2, 0]}
    D2 = {"244": [2, 0], "256": [8000, 1000]}
    nso = L.check_no_silent_override
    v = nso([_q(0, D, ["nvs.dump"])])
    check("(c) a stored marker the RAM ignores ('nvs.dump' alone in the fw.quiet record) is NOT a visible obligation: "
          "exactly one violation (the V0 rule counted it as visible and passed)", len(v) == 1, str(v))
    check("...while a RAM snapshot mirror or a corrupt lockout still is", not nso([_q(0, D, ["dump.snap", "nvs.dump"])])
          and not nso([_q(0, D, ["r244.corrupt"])]))
    transient = [_ev(0, "fw.boot", {"boot": 1}, t=10, boot=1), _q(1, D, ["nvs.dump"], t=10, boot=1),
                 _ev(2, "fw.load", {"key": "x", "ok": True}, t=10, boot=1), _q(3, D, ["dump.snap", "nvs.dump"], t=10, boot=1),
                 _booted(4, t=10, dump_snap=True, nvs_dump="RESTORE_REQUIRED")]
    check("(a) a silent fw.quiet INSIDE a boot (marker loaded, RAM mirror not derived yet) is never judged: the state after "
          "the full on_boot is visible -> no violation", not nso(transient), str(nso(transient)))
    still = [transient[0], transient[1], _booted(2, t=10, nvs_dump="RESTORE_REQUIRED")]
    v = nso(still)
    check("...but a boot whose SETTLED state is silent gives exactly one violation, found at the boot settle point and "
          "anchored at the record holding that state", len(v) == 1 and v[0]["seq"] == 1 and "boot settle point" in
          v[0]["detail"] and "stored markers the RAM ignores: {'dump': 'RESTORE_REQUIRED'}" in v[0]["detail"], str(v))
    merged = [transient[0], transient[1], _booted(2, t=10, nvs_dump="RESTORE_REQUIRED"),
              _ev(3, "fw.obl", _obl(dump_snap=True, nvs_dump="RESTORE_REQUIRED"), t=10, boot=1),
              _q(4, D, ["dump.snap", "nvs.dump"], t=10, boot=1)]
    check("...the post-boot note's fw.obl / fw.quiet at the boot instant belong to the settle point (no violation)",
          not nso(merged), str(nso(merged)))
    ep = [_q(0, D, [], t=0), _q(1, D, ["nvs.fp"], t=1), _q(2, D, ["dump.snap"], t=2), _q(3, D, [], t=3),
          _q(4, D2, [], t=4)]
    v = nso(ep)
    check("one violation per episode: the same silent diff twice is one, a visible state ends the episode, a changed "
          "diff is a new one (3 violations at seq 0, 3, 4)", [x["seq"] for x in v] == [0, 3, 4], str(v))
    same = [_q(0, D, [], t=7), _ev(1, "fw.obl", _obl(dump_snap=True), t=7), _q(2, D, ["dump.snap"], t=7)]
    check("...consecutive fw.obl / fw.quiet records of ONE instant are one steady point (the state between them lasted "
          "0 ms): a silent record superseded at the same instant is not a violation", not nso(same), str(nso(same)))
    boots = [_q(0, D, []), _ev(1, "fw.boot", {"boot": 1}, t=5, boot=1), _q(2, D, [], t=5, boot=1), _booted(3, t=5)]
    v = nso(boots)
    check("...and a silent override that persists across a reboot is reported again for the new boot (2)",
          [x["seq"] for x in v] == [0, 2], str(v))
    # (b) level-based slices on a real run: erase_all at a reboot during a Dump lease (partition erase: NVS-PARTITION-ERASE)
    e = world()
    dump_env(e)
    e.dump_start(power_w=1000, stop_soc=25, minutes=30)
    e.run_for(30)
    e.reboot(nvs_fault=("erase_all",))
    e.run_for(30)
    last_q = max(x["seq"] for x in e.log if x["kind"] == "fw.quiet")
    sl = [x for x in e.log if x["seq"] > last_q]
    full = nso(e.log, world=e)
    check("real run, erase_all during a Dump lease: the whole log gives exactly one violation, tagged PLATFORM-ABSENT",
          len(full) == 1 and full[0]["tags"] == ["PLATFORM-ABSENT"] and e.quiet_state()["silent"], str(full))
    v_w, v_n, v_e = nso(sl, world=e), nso(sl), nso([], world=e)
    check("(b) a slice that starts after the last fw.quiet (the V0 edge-triggered check saw nothing) is level-based with "
          "the world: pre-filled from world.log, it reports the persistent override (tagged PLATFORM-ABSENT)",
          len(sl) > 0 and len(v_w) == 1 and v_w[0]["tags"] == ["PLATFORM-ABSENT"] and v_w[0]["seq"] >= sl[0]["seq"],
          str(v_w))
    check("...an empty slice with the world judges world.quiet_state() (the state now); without a world a slice with no "
          "fw.quiet cannot be judged (documented: no violation)", len(v_e) == 1 and "world.quiet_state()" in v_e[0]["detail"]
          and v_e[0]["tags"] == ["PLATFORM-ABSENT"] and v_n == [], f"{v_e} / {v_n}")
    c = world()
    clean_end = nso(c.log, world=c)
    c.bank[244] = 0   # white-box: the inverter shows Allow Export with no event logged and nothing in RAM
    v = nso(c.log, world=c)
    check("negative control of the end point: a clean world, then a white-box bank change (no event): the log alone "
          "passes, world.quiet_state() at the end of the log reports it (seq = the last event)",
          clean_end == [] and nso(c.log) == [] and len(v) == 1 and v[0]["seq"] == len(c.log) - 1
          and "world.quiet_state()" in v[0]["detail"], str(v))
    qs = c.quiet_state()
    check("quiet_state() is read-only and reports {booting, locked, diff, visible, nvs, silent}",
          set(qs) == {"booting", "locked", "diff", "visible", "nvs", "silent"} and qs["diff"] == {"244": [2, 0]}
          and qs["silent"] is True and len(c.log) == v[0]["seq"] + 1)
    # (a) on a real run: a clean reboot during a Dump lease
    r = dump_lease_reboot()
    trans, inside = [], False
    for x in r.log:
        if x["kind"] == "fw.boot":
            inside = True
        elif x["kind"] == "fw.booted":
            inside = False
        elif inside and x["kind"] == "fw.quiet" and x["data"]["diff"] and not [
                s for s in x["data"]["visible"] if not s.startswith("nvs.")]:
            trans.append(x["seq"])
    check("(a) real run, clean reboot during a Dump lease: the boot logs a transient fw.quiet whose RAM part is empty "
          "(before the on_boot derives the mirror), yet INV-NO-SILENT-OVERRIDE reports nothing (the settled state is "
          "visible)", len(trans) >= 1 and nso(r.log, world=r) == [] and r.status("dump").startswith("RESTORED OK"),
          f"{trans} {nso(r.log, world=r)}")
    if fw_count(DUMP_RR_ANCHOR) == 1:
        m = dump_lease_reboot(fw=L.load_fw(FW["_text"].replace(DUMP_RR_ANCHOR, DUMP_RR_MUTANT)))
        v = nso(m.log, world=m)
        check("real-run negative control: in-memory mutant 'Dump on_boot reads a stored RESTORE_REQUIRED as CLEAR' "
              "(exact-count anchor; RAM clear, status 'Inactive', 244 = 0 live) -> exactly one INV-NO-SILENT-OVERRIDE "
              "violation naming the ignored marker (the V0 rule passed it)", len(v) == 1 and m.status("dump") == "Inactive"
              and m.bank[244] == 0 and "'dump': 'RESTORE_REQUIRED'" in v[0]["detail"], str(v))
    else:
        check("real-run negative control: the Dump on_boot mutant anchor occurs exactly once", False, "MUTANT-INVALID")


def section_boot_mirror() -> None:
    print("[16c] INV-BOOT-MIRROR: a stored RESTORE_REQUIRED / PENDING_CLEAR / MALFORMED marker is reflected in RAM at every "
          "boot")
    bm = L.check_boot_mirror
    cases = [("RESTORE_REQUIRED, RAM clear", dict(nvs_dump="RESTORE_REQUIRED"), 1),
             ("RESTORE_REQUIRED + snapshot_valid", dict(nvs_dump="RESTORE_REQUIRED", dump_snap=True), 0),
             ("RESTORE_REQUIRED + corrupt lockout", dict(nvs_dump="RESTORE_REQUIRED", dump_corrupt=True), 0),
             ("PENDING_CLEAR, RAM clear", dict(nvs_fp="PENDING_CLEAR"), 1),
             ("PENDING_CLEAR + snapshot_valid (the zero-I/O clear branch)", dict(nvs_fp="PENDING_CLEAR", fp_snap=True), 0),
             ("MALFORMED with only snapshot_valid", dict(nvs_r244="MALFORMED", r244_snap=True), 1),
             ("MALFORMED + corrupt lockout", dict(nvs_r244="MALFORMED", r244_snap=True, r244_corrupt=True), 0),
             ("ABSENT", dict(nvs_fp="ABSENT"), 0), ("reg244 RESTORE_REQUIRED, RAM clear", dict(nvs_r244="RESTORE_REQUIRED"), 1)]
    wrong = [(n, len(bm([_booted(0, **o)]))) for n, o, want in cases if len(bm([_booted(0, **o)])) != want]
    check(f"BOOT_MIRROR_RULE on {len(cases)} hand-built boots (RR / PENDING_CLEAR need snapshot_valid or the lockout, "
          "MALFORMED the lockout, CLEAR / ABSENT nothing)", not wrong and L.BOOT_MIRROR_RULE == {
              "RESTORE_REQUIRED": ("snap", "corrupt"), "PENDING_CLEAR": ("snap", "corrupt"), "MALFORMED": ("corrupt",)},
          str(wrong))
    v = bm([_ev(0, "fw.status", {"dom": "dump", "text": "Inactive"}),
            _booted(1, nvs_dump="RESTORE_REQUIRED", nvs_fp="RESTORE_REQUIRED")])
    check("one violation per domain per boot, at the fw.booted, naming the domain's status",
          [(x["inv"], x["seq"]) for x in v] == [("INV-BOOT-MIRROR", 1)] * 2 and "'Inactive'" in v[1]["detail"]
          and "fp marker" in v[0]["detail"] and "dump marker" in v[1]["detail"], str(v))
    check("a runtime state (fw.obl: NVS RESTORE_REQUIRED, RAM clear - a ghost) is never judged by INV-BOOT-MIRROR",
          not bm([_ev(0, "fw.obl", _obl(nvs_dump="RESTORE_REQUIRED"))]))
    check("INV-BOOT-MIRROR is in the default invariant set (check_invariants / world.invariants() / the replay observer)",
          "INV-BOOT-MIRROR" in L.INVARIANTS and list(L.INVARIANTS)[-1] == "INV-BOOT-MIRROR")
    anchor_ok = fw_count(DUMP_RR_ANCHOR) == 1
    m = dump_lease_reboot(fw=L.load_fw(FW["_text"].replace(DUMP_RR_ANCHOR, DUMP_RR_MUTANT))) if anchor_ok else None
    v = [] if m is None else m.invariants(["INV-BOOT-MIRROR"])
    check("negative control (the property suite's NC-PB01-c-draft blind spot): mutant 'Dump on_boot reads a stored "
          "RESTORE_REQUIRED as CLEAR' -> exactly ONE INV-BOOT-MIRROR violation (dump, boot 1), no harness exception, and "
          "the default set reports it", m is not None and len(v) == 1 and m.nvs_marker("dump") == "RESTORE_REQUIRED"
          and m.status("dump") == "Inactive" and "boot 1: the stored dump marker" in v[0]["detail"]
          and m.log[v[0]["seq"]]["kind"] == "fw.booted" and "INV-BOOT-MIRROR" in [x["inv"] for x in m.invariants()],
          "MUTANT-INVALID: anchor not unique" if m is None else str(v))
    r = dump_lease_reboot()
    check("...the same trace on the real firmware (a clean reboot during a Dump lease): no INV-BOOT-MIRROR violation and "
          "no violation at all", r.invariants() == [] and r.status("dump").startswith("RESTORED OK"), str(r.invariants()))
    p = used_key_world("fp")   # B5: the false_negative needs a used FP marker key (completed-lease prelude)
    p.nvs_policy("fp.valid", ds.Durable.MARKER_RESTORE_REQUIRED, mode="false_negative")
    p.fp_start(power_w=3000, minutes=30)
    dump_env(p)
    s = p.dump_start(power_w=1000, stop_soc=25, minutes=30)
    p.run_for(30)
    ghost = (p.nvs_marker("fp") == "RESTORE_REQUIRED" and p.sim.g["free_power_snapshot_valid"] is False
             and s.startswith("ACTIVE"))
    rt = p.invariants(["INV-BOOT-MIRROR"])
    p.reboot()
    p.run_for(60)
    check("a phantom (PR41-GHOST) in the SAME runtime is not an INV-BOOT-MIRROR violation (NVS RR, RAM clear, the Dump START "
          "admitted); the next boot's dual-obligation arbitration locks BOTH domains, which reflects both markers",
          ghost and rt == [] and p.corrupt("fp") and p.corrupt("dump") and p.invariants(["INV-BOOT-MIRROR"]) == [],
          f"ghost {ghost} {rt} {p.invariants(['INV-BOOT-MIRROR'])}")
    res = {}
    for fault in (("read_error", "dump.valid"), ("read_error_all",), ("wrong_size", "dump.valid")):
        f = world()
        dump_env(f)
        f.dump_start(power_w=1000, stop_soc=25, minutes=30)
        f.run_for(30)
        f.reboot(nvs_fault=fault)
        res[fault[0]] = (f.corrupt("dump"), f.invariants(["INV-BOOT-MIRROR"]))
    check("boot faults read_error / read_error_all / wrong_size: the UNKNOWN / malformed lockouts reflect the stored marker "
          "(no INV-BOOT-MIRROR violation)", all(c and not v for c, v in res.values()), str(res))


# =============================================================================================================================
# [16d] the HL-1 rule (V0.1 root fix, brief B4 change 6): _lab_fw.accept_adoption decides what the lab ORIGINAL adopts after
# an operator Accept. Expected texts and states come from the firmware's Accept scripts (lines at writing, file
# firmware/ecco_clock_dongle_stage3_4_free_power.yaml): FP free_power_recovery_accept_current_state (:13045, its gate
# refusals publish no status) and _dispatch (:13195; SUCCESS :13644 marker CLEAR, :13649 durable clear pending; refusals
# 'ACCEPT REFUSED - ' :13378-13656); Dump dump_accept_current_state (:20833; SUCCESS :20936 / :20942-20943 after
# 'if (clear_ok) {' :20919, which sets marker CLEAR and snapshot_valid false :20924-20925; refusals :20949, :20954-20959).
FP_ACCEPT_FOREIGN = ([(230, 100)] + [(a, 4321) for a in range(256, 262)] + [(a, 50) for a in range(268, 274)]
                     + [(232, 0)] + [(a, 0) for a in range(275, 280)])
# ^ pattern from test_lab_fw_durability.py ACCEPT_FOREIGN (fl_fp_accept): every register the FP START wrote moved off both
#   ORIGINAL and INTENDED, so the dispatch classifies NEITHER with no FP residue and Accept succeeds
# PB-01 seed 929 (test_lab_property pb01_gen + pb01_normalise at b7f2fe7, executed as pb01_execute: the normalised DSL with
# the TAIL), the X-2 trace of the audit (step 0 B4, x2_seed929 / x2_continuation). Action 2's boot fault ('read_error',
# 'r244.valid') hits the never-stored reg244 marker; it is dropped here (B5: no injected fault on a never-stored key, and
# B5's PB-01 normaliser makes the same rewrite). The X-2 state does not depend on it: VERIFIED at writing, both variants
# end the sequence with ORIGINAL 258 adopted as 8365 under the V0 rule and give the same false INV-NO-SILENT-OVERRIDE on
# the continuation, and none under the HL-1 rule.
X2_SEED929 = (("telemetry", {"grid_w": -1000, "batt_w": 1050}),
              ("dump_start", {"power_w": 4200, "stop_soc": 14, "minutes": 39, "arm": True}),
              ("reboot", {"down_s": 24, "nvs_fault": None, "keep_prefs": True}),
              ("config_poll", {}), ("set_register", {"addr": 258, "value": 8365, "actor": "inverter"}),
              ("dump_end", {}), ("dump_start", {"power_w": 2300, "stop_soc": 16, "minutes": 5, "arm": False}),
              ("arm_power_cut", {"kind": "fw.commit", "nth": 1, "down_s": 9}), ("dump_end", {}),
              ("fp_operator", {"action": "ACCEPT_CURRENT_STATE"}),
              ("arm_power_cut", {"kind": None, "nth": 3, "down_s": 15}),
              ("fp_operator", {"action": "ACCEPT_CURRENT_STATE"}),
              ("run_for", {"seconds": 731, "wd_order": ["dump", "fp"]}),
              ("modbus_policy", {"table": None}), ("set_link", {"up": True}), ("set_bus_idle", {"idle": True}),
              ("run_for", {"seconds": 120}))
X2_CONTINUATION = (("dump_force_restore", {}), ("run_for", {"seconds": 120}))


def _v0_adoption(dom, pre, post, texts):
    """The V0 rule (bca82cc _lab_fw.py:1746-1751), for in-memory negative controls only: after ANY Accept call, adopt
    every register of the domain when its stored marker reads CLEAR / ABSENT and its RAM snapshot is not valid."""
    cleared = post["nvs"][dom] in ("CLEAR", "ABSENT") and not post[dom]["snap"]
    return {"result": texts[-1] if texts else None, "success": None, "held": None, "cleared": cleared,
            "adopt": sorted(L.DOMAIN_REGS[dom]) if cleared else [], "kept": {}, "reason": "V0 rule (negative control)"}


def with_v0_rule(fn):
    """fn() with _lab_fw.accept_adoption replaced by the V0 rule, restored afterwards (process-global state untouched)."""
    real = L.accept_adoption
    L.accept_adoption = _v0_adoption
    try:
        return fn()
    finally:
        L.accept_adoption = real


def x2_seed929():
    """The X-2 sequence then its continuation, each action logged as replay.action like pb01_execute; returns the world,
    the accept_log after the sequence and the sequence-end state."""
    w = L.make_world(utc_start=U0, seed=929, warmup_s=60)
    for i, (a, args) in enumerate(X2_SEED929):
        w.log.append(t_utc=w.t_utc, up_ms=None, boot=None, src="lab", kind="replay.action",
                     data={"i": i, "do": a, "args": args})
        L.ACTIONS[a](w, **copy.deepcopy(args))
    mid = {"orig258": w.original[258], "bank258": w.bank[258], "foreign": sorted(w.foreign),
           "dump": w.status("dump"), "dump_marker": w.nvs_marker("dump"), "fp_marker": w.nvs_marker("fp"),
           "accepts": [dict(x) for x in w.accept_log], "viol": L.check_invariants(w.log, world=w)}
    for a, args in X2_CONTINUATION:
        L.ACTIONS[a](w, **copy.deepcopy(args))
    return w, mid


def fp_accept_lockout() -> L.FirmwareWorld:
    """An FP lease whose registers all moved to foreign values: the restore stops at OPERATOR DECISION REQUIRED."""
    w = world()
    w.fp_start(power_w=3000, minutes=5)
    w.run_for(30)
    for a, v in FP_ACCEPT_FOREIGN:
        w.set_register(a, v, actor="inverter")
    w.run_for(600)
    return w


def masked_direction(accept: bool):
    """X-2 masked direction (step 0 B4 x2_masked): a no-op FP Accept during an ACTIVE Dump lease, then a silent loss of the
    Dump obligation (false ABSENT of dump.valid at a reboot)."""
    w = world()
    w.telemetry(grid_w=-1000, batt_w=1050, soc=70)
    w.dump_start(power_w=1000, stop_soc=25, minutes=30)
    w.run_for(20)
    s = w.fp_operator("ACCEPT_CURRENT_STATE") if accept else None
    w.reboot(down_s=5, nvs_fault=("absent", "dump.valid"))
    w.run_for(60)
    return w, s, w.invariants(["INV-NO-SILENT-OVERRIDE"])


def section_hl1() -> None:
    print("[16d] HL-1 rule: the lab ORIGINAL adopts the live bank only after a SUCCESSFUL Accept that cleared the domain's "
          "own obligation, never for registers another domain holds")
    FP_OK, FP_PENDING = L.ACCEPT_SUCCESS_TEXTS["fp"]
    DUMP_OK, = L.ACCEPT_SUCCESS_TEXTS["dump"]
    R_PRE, R_SUF = L.DUMP_ACCEPT_RESIDUE_FORM
    DUMP_RESIDUE = R_PRE + "registers 256-261 read 1000W (original snapshot was 8000W)" + R_SUF   # FW :20885 note form
    FPR, DR = sorted(L.DOMAIN_REGS["fp"]), sorted(L.DOMAIN_REGS["dump"])
    SHARED = sorted(L.DOMAIN_REGS["fp"] & L.DOMAIN_REGS["dump"])
    anchors = {t for _p, t in L.SOURCE_ANCHORS}
    check("the SUCCESS texts are the firmware's own Accept publishes, each occurring exactly once in the firmware and "
          "listed in SOURCE_ANCHORS (FP :13644 / :13649, Dump :20936 and the residue form :20942-20943)",
          set(L.ACCEPT_SUCCESS_TEXTS["fp"] + L.ACCEPT_SUCCESS_TEXTS["dump"]) <= anchors and f'"{R_SUF}"' in anchors
          and all(fw_count(t) == 1 for t in L.ACCEPT_SUCCESS_TEXTS["fp"] + L.ACCEPT_SUCCESS_TEXTS["dump"])
          and fw_count(f'std::string("{R_PRE}") + id(dump_accept_residue_note) +') == 1 and fw_count(f'"{R_SUF}"') == 1)
    texts = [("fp", FP_OK, True), ("fp", FP_PENDING, True), ("dump", DUMP_OK, True), ("dump", DUMP_RESIDUE, True),
             ("dump", R_PRE + R_SUF, False), ("fp", DUMP_OK, False), ("dump", FP_OK, False), ("fp", DUMP_RESIDUE, False),
             ("fp", "ACCEPT REFUSED - Phase C durable commit failed; recovery obligation retained for a safe retry", False),
             ("fp", "ACCEPT REFUSED - state is INTENDED, not NEITHER - use Force Restore Original or Review again", False),
             ("dump", "ACCEPT FAILED - durable clear commit failed; obligation retained, try again", False),
             ("dump", "ACCEPT REFUSED - register 244 reads an unknown mode - cannot confirm export is off", False),
             ("dump", "REJECTED - arm Dump to Grid Recovery Arm first", False), ("fp", "Inactive", False),
             ("fp", None, False)]
    wrong = [(d, t, want) for d, t, want in texts if L.accept_succeeded(d, t) != want]
    check(f"accept_succeeded on {len(texts)} texts: the four firmware SUCCESS forms of their own domain only; the "
          "residue form needs a non-empty note; every refusal / failure text (:13656, :13494, :20949, :20959, :20957) and "
          "a missing text are not a success", not wrong, str(wrong))
    held_fp = dict(fp_snap=True, fp_opn=True, nvs_fp="RESTORE_REQUIRED")
    held_dump = dict(dump_snap=True, dump_opn=True, nvs_dump="RESTORE_REQUIRED")
    cases = [
        ("Dump SUCCESS (:20936), held, cleared, nobody else holds -> every Dump register", "dump", held_dump, {},
         [DUMP_OK], DR, {}),
        ("Dump SUCCESS with the residue note (:20942-20943) -> every Dump register", "dump", held_dump, {},
         [DUMP_RESIDUE], DR, {}),
        ("FP SUCCESS (:13644), held, cleared -> every FP register", "fp", held_fp, {}, [FP_OK], FPR, {}),
        ("refused: the Accept's last text is a refusal (:20957) -> nothing", "dump", held_dump, held_dump,
         ["REJECTED - arm Dump to Grid Recovery Arm first"], [], {}),
        ("refused with no text: an FP gate refusal publishes no status (:13045 branch) -> nothing", "fp", held_fp,
         held_fp, [], [], {}),
        ("the LAST published text decides: a SUCCESS followed by a refusal in the same action -> nothing", "dump",
         held_dump, {}, [DUMP_OK, "REJECTED - arm Dump to Grid Recovery Arm first"], [], {}),
        ("no-op: a SUCCESS text but the domain held no obligation before the Accept -> nothing", "dump", {}, {},
         [DUMP_OK], [], {}),
        ("not cleared: FP SUCCESS whose durable clear is pending (:13649; marker PENDING_CLEAR, snapshot still valid) -> "
         "nothing", "fp", held_fp, dict(fp_snap=True, nvs_fp="PENDING_CLEAR"), [FP_PENDING], [], {}),
        ("not cleared: the RAM snapshot cleared but the stored marker still RESTORE_REQUIRED (a false-positive CLEAR "
         "commit, FW-06-e) -> nothing", "dump", held_dump, dict(nvs_dump="RESTORE_REQUIRED"), [DUMP_RESIDUE], [], {}),
        ("Dump SUCCESS while FP holds a snapshot -> 244 only, 256-261 kept for FP", "dump", held_dump,
         dict(fp_snap=True, nvs_fp="RESTORE_REQUIRED"), [DUMP_OK], [244], {"fp": SHARED}),
        ("Dump SUCCESS while reg244 holds only a stored RESTORE_REQUIRED marker -> 256-261 only, 244 kept", "dump",
         held_dump, dict(nvs_r244="RESTORE_REQUIRED"), [DUMP_OK], SHARED, {"r244": [244]}),
        ("FP SUCCESS while a Dump lease is active (active_persisted only) -> 256-261 kept for Dump", "fp", held_fp,
         dict(dump_act=True), [FP_OK], sorted(set(FPR) - set(SHARED)), {"dump": SHARED}),
        ("FP SUCCESS while Dump is corrupt-locked -> 256-261 kept", "fp", held_fp, dict(dump_corrupt=True), [FP_OK],
         sorted(set(FPR) - set(SHARED)), {"dump": SHARED}),
        ("FP SUCCESS while a Dump transaction is in progress -> 256-261 kept", "fp", held_fp, dict(dump_op=True),
         [FP_OK], sorted(set(FPR) - set(SHARED)), {"dump": SHARED}),
        ("FP SUCCESS while the other domains' markers read ABSENT with nothing in RAM -> every FP register", "fp",
         held_fp, dict(nvs_dump="ABSENT", nvs_r244="ABSENT"), [FP_OK], FPR, {}),
        ("reg244 holding 244 does not touch an FP Accept (no shared register)", "fp", held_fp,
         dict(r244_snap=True, nvs_r244="RESTORE_REQUIRED"), [FP_OK], FPR, {}),
    ]
    wrong = []
    for name, dom, pre, post, txt, want_adopt, want_kept in cases:
        r = L.accept_adoption(dom, _obl(**pre), _obl(**post), txt)
        if r["adopt"] != want_adopt or r["kept"] != want_kept:
            wrong.append((name, r["adopt"], r["kept"], r["reason"]))
    check(f"accept_adoption on {len(cases)} hand-built Accepts: SUCCESS AND held before AND cleared, minus the registers "
          "another domain holds (snapshot, lockout, transaction, stored marker other than CLEAR / ABSENT, active lease)",
          not wrong, str(wrong))
    hit, msg = raises(L.LabHarnessError, L.accept_adoption, "r244", _obl(), _obl(), [])
    check("accept_adoption refuses a domain without an operator Accept (reg244)", hit, msg)

    # genuine SUCCESSFUL Accepts still adopt (positive controls)
    w = fp_accept_lockout()
    lock = w.status("fp").startswith("OPERATOR DECISION REQUIRED") and w.nvs_marker("fp") == "RESTORE_REQUIRED"
    s = w.fp_operator("ACCEPT_CURRENT_STATE")
    rec = w.accept_log[-1] if w.accept_log else {}
    check("positive control, FP: a real Accept on the FP lockout publishes the SUCCESS text (:13644), clears the marker and "
          "adopts every FP register as ORIGINAL (foreign marks cleared, no diff, no violation)",
          lock and s == FP_OK and w.nvs_marker("fp") == "CLEAR" and rec.get("adopt") == FPR and rec.get("kept") == {}
          and all(w.original[a] == w.bank[a] for a in FPR) and not set(FPR) & w.foreign and w.quiet_state()["diff"] == {}
          and w.invariants() == [], f"{s!r} {rec} {w.invariants()}")
    d = world()
    dump_env(d)
    d.dump_start(power_w=1000, stop_soc=25, minutes=5)
    d.run_for(60)
    d.reboot()
    d.set_register(257, 4321, actor="owner")
    d.run_for(60)
    s1 = d.dump_accept(arm=False)
    r1 = dict(d.accept_log[-1]) if d.accept_log else {}
    check("refused while held: a Dump Accept without the recovery arm is REJECTED (:20957), keeps RESTORE_REQUIRED and "
          "adopts nothing", s1 == "REJECTED - arm Dump to Grid Recovery Arm first" and r1.get("adopt") == []
          and r1.get("held") is True and d.nvs_marker("dump") == "RESTORE_REQUIRED" and d.original[257] == 4321
          and d.original[256] == ORIG[256], f"{s1!r} {r1}")
    s2 = d.dump_accept()
    r2 = d.accept_log[-1] if d.accept_log else {}
    check("positive control, Dump: the armed Accept succeeds with the residue form (:20942-20943), clears the marker and "
          "adopts 244 and 256-261 (no diff, no violation)", L.accept_succeeded("dump", s2) and s2.startswith(R_PRE)
          and s2 != DUMP_OK and d.nvs_marker("dump") == "CLEAR" and r2.get("adopt") == DR
          and all(d.original[a] == d.bank[a] for a in DR) and d.quiet_state()["diff"] == {} and d.invariants() == [],
          f"{s2!r} {r2} {d.invariants()}")

    # a refused Accept adopts nothing
    r = world()
    r.set_register(257, 4321, actor="inverter")
    s = r.dump_accept()
    rec = r.accept_log[-1] if r.accept_log else {}
    v0 = world()
    v0.set_register(257, 4321, actor="inverter")
    with_v0_rule(v0.dump_accept)
    check("a refused Dump Accept while Dump holds nothing ('REJECTED - Accept Current State is only available while an "
          "operator decision is required', :20955) adopts nothing: 257 keeps ORIGINAL 8000 and stays foreign (the V0 rule, "
          "in memory, adopted the inverter's 4321 and un-marked it)", s.startswith("REJECTED - Accept Current State is "
          "only available") and rec.get("adopt") == [] and rec.get("success") is False and r.original[257] == ORIG[257]
          and 257 in r.foreign and v0.original[257] == 4321 and 257 not in v0.foreign, f"{s!r} {rec}")
    g = fp_accept_lockout()
    s = g.fp_operator("ACCEPT_CURRENT_STATE", phrase="ACCEPT CURRENT STATE WRONG")
    rec = g.accept_log[-1] if g.accept_log else {}
    check("an FP Accept refused at the gate (confirmation mismatch :13126; the refusal branch of :13045 publishes no "
          "status) adopts nothing; the obligation and the foreign marks stay", rec.get("result") is None
          and rec.get("adopt") == []
          and g.nvs_marker("fp") == "RESTORE_REQUIRED" and set(FPR) - {274} <= g.foreign
          and s.startswith("OPERATOR DECISION REQUIRED"), f"{s!r} {rec}")

    # X-2: PB-01 seed 929 and its continuation
    x, mid = x2_seed929()
    vx = x.invariants()
    sig = (mid["orig258"] == ORIG[258] and mid["bank258"] == 8365 and 258 in mid["foreign"]
           and mid["dump"].startswith("OPERATOR DECISION REQUIRED") and mid["dump_marker"] == "RESTORE_REQUIRED"
           and mid["fp_marker"] in ("CLEAR", "ABSENT") and len(mid["accepts"]) == 2
           and all(a["dom"] == "fp" and a["adopt"] == [] and not a["success"] and not a["held"] for a in mid["accepts"])
           and mid["viol"] == [])
    check("X-2 (PB-01 seed 929): both FP Accepts are no-ops (FP holds nothing, no SUCCESS text) and adopt nothing; 258 stays "
          "foreign with ORIGINAL 7000 while Dump holds 256-261 (RESTORE_REQUIRED, OPERATOR DECISION REQUIRED)", sig,
          str({k: v for k, v in mid.items() if k != "viol"}))
    check("X-2 continuation [dump_force_restore, run_for 120]: the verified Force Restore puts 258 back to 7000 and NO "
          "INV-NO-SILENT-OVERRIDE (no violation at all) follows", x.status("dump").startswith("RESTORED OK")
          and x.bank[258] == ORIG[258] and x.original[258] == ORIG[258] and vx == [], str(vx))
    xv, mid_v = with_v0_rule(x2_seed929)
    vv = xv.invariants()
    check("negative control: the same trace under the V0 rule (in memory) adopts 8365 at the first no-op Accept and "
          "reports exactly the false INV-NO-SILENT-OVERRIDE {'258': [8365, 7000]} after the Force Restore",
          mid_v["orig258"] == 8365 and [v["inv"] for v in vv] == ["INV-NO-SILENT-OVERRIDE"]
          and "{'258': [8365, 7000]}" in vv[0]["detail"], str(vv))

    # the masked direction
    m0, _s, base = masked_direction(False)
    m1, s, acc = masked_direction(True)
    rec = m1.accept_log[-1] if m1.accept_log else {}
    mv0, _s, v0m = with_v0_rule(lambda: masked_direction(True))
    check("masked direction: a no-op FP Accept during an ACTIVE Dump lease adopts nothing (status stays Inactive), so the "
          "later silent loss of the Dump obligation is reported with its full diff (244 and 256-261), exactly as "
          "without the Accept", s == "Inactive" and rec.get("adopt") == [] and len(base) == len(acc) == 1
          and base[0]["detail"] == acc[0]["detail"] and all(f"'{a}'" in acc[0]["detail"] for a in [244] + SHARED)
          and acc[0]["tags"] == ["PLATFORM-ABSENT"], f"{rec} {acc} / {base}")
    check("negative control: under the V0 rule (in memory) the same no-op Accept adopts Dump's 256-261 and the report "
          "names 244 only (the 256-261 part masked)", len(v0m) == 1 and "'244'" in v0m[0]["detail"]
          and not any(f"'{a}'" in v0m[0]["detail"] for a in SHARED), str(v0m))

    # never for registers another domain holds, on a real Accept (white-box: a lab RAM fault makes Dump hold a snapshot)
    k = fp_accept_lockout()
    k.inject_global("dump_snapshot_valid", True)
    s = k.fp_operator("ACCEPT_CURRENT_STATE")
    rec = k.accept_log[-1] if k.accept_log else {}
    check("a SUCCESSFUL FP Accept (:13644) while Dump holds a snapshot (white-box fault.ram) adopts FP's own registers but "
          "keeps 256-261: their ORIGINAL is unchanged and they stay foreign", s == FP_OK and rec.get("kept") == {"dump": SHARED}
          and rec.get("adopt") == sorted(set(FPR) - set(SHARED)) and all(k.original[a] == ORIG[a] for a in SHARED)
          and set(SHARED) <= k.foreign and all(k.original[a] == k.bank[a] for a in rec.get("adopt") or []),
          f"{s!r} {rec}")


def recorded(draft: dict, name: str):
    """T.record(draft); when the recording itself fails (record()'s LabTraceError family: expectations that no longer hold
    after a production behaviour change, an anchor or schema problem) the check `name` FAILS with the error text and None
    is returned, so the suite still reaches its FAILED / LAB-SUMMARY lines instead of crashing at module level (B7.4).
    Only those record / replay errors are caught; a failure is never turned into a pass."""
    try:
        return T.record(draft)
    except T.LabTraceError as exc:
        check(name, False, f"record() raised {type(exc).__name__}: {exc}")
        return None


def section_replay_additions() -> None:
    print("[17b] replay additions: set_number, inject_global, r244_apply; text_state, quiet_state; invariants filters")
    reg = T.registered(L.TIER)
    check("tier 'firmware' registers the actions set_number / inject_global / r244_apply and the observers text_state / "
          "quiet_state", {"set_number", "inject_global", "r244_apply"} <= set(reg["actions"])
          and {"text_state", "quiet_state", "invariants"} <= set(reg["observers"]), str(reg))
    w = world()
    s = w.r244_apply("Allow Export")
    acts = [e for e in w.log if e["kind"] == "act.r244_apply"]
    check("r244_apply: the real Load / select / arm / Apply buttons (one logged world action); the firmware verifies "
          "244 = 0 and holds a RESTORE_REQUIRED reg244 obligation", s.startswith("VERIFIED OK - register 244 now 0")
          and w.bank[244] == 0 and w.nvs_marker("r244") == "RESTORE_REQUIRED" and len(acts) == 1
          and acts[0]["data"] == {"target": "Allow Export", "arm": True} and w.sim.ent("manual_config_write_enable").state
          is False, s)
    n = len(w.log)
    bad = [raises(L.LabHarnessError, w.r244_apply, "Export All")[0], raises(L.LabHarnessError, w.owner_set_number,
                                                                           "dump_stop_soc", 95)[0],
           raises(L.LabHarnessError, w.owner_set_number, "dump_status", 1)[0]]
    check("r244_apply refuses an unknown target and set_number an out-of-range value / a non-number BEFORE anything is "
          "logged", all(bad) and len(w.log) == n, str(bad))
    check("text_state reads any firmware text_sensor and refuses anything else",
          w.text_state("reg244_last_result") == s and w.text_state("dump_recovery_state") == "NONE"
          and raises(L.LabHarnessError, w.text_state, "dump_stop_soc")[0]
          and raises(L.LabHarnessError, w.text_state, "dump_write_enable")[0])
    w.owner_set_number("dump_stop_soc", 30)
    check("set_number: one logged action (act.set_number {entity, value}) through the real number path",
          w.sim.ent("dump_stop_soc").state == 30.0 and w.log.last(kind="act.set_number")["data"] == {
              "entity": "dump_stop_soc", "value": 30})
    g = world()
    n = len(g.log)
    arr = next(x["id"] for x in FW["globals"] if x["type"].startswith("std::array"))
    refused = [raises(L.LabHarnessError, g.inject_global, "manual_write_in_progress", 1)[0],
               raises(L.LabHarnessError, g.inject_global, "dump_marker_state", 256)[0],
               raises(L.LabHarnessError, g.inject_global, "dump_marker_state", -1)[0],
               raises(L.LabHarnessError, g.inject_global, "dump_target_power", 1.5)[0],
               raises(L.LabHarnessError, g.inject_global, "no_such_global", True)[0],
               raises(L.LabUnsupported, g.inject_global, arr, 1)[0]]
    check("inject_global refuses a value that does not fit the C type exactly (int for bool, out of range, float for an "
          "int), an unknown global, and an array global (LabUnsupported) - nothing logged",
          all(refused) and len(g.log) == n, str(refused))
    dump_env(g)
    g.dump_start(power_w=1000, stop_soc=25, minutes=30)
    g.run_for(30)
    g.inject_global("manual_write_in_progress", True)
    fr = g.log.last(kind="fault.ram")
    check("inject_global logs a lab fault (fault.ram {name, type, value, old}) and notes the new state (fw.obl shows "
          "the leaked lock)", fr["data"] == {"name": "manual_write_in_progress", "type": "bool", "value": True,
                                             "old": False} and g.log.last(kind="fw.obl")["data"]["mw"] is True
          and g.quiet_state()["locked"] is True, str(fr))
    g.run_for(240)   # the firmware's restart aborts this run_for at the restart (the power-cut boundary)
    g.run_for(60)
    check("...the leaked lock then escalates and the firmware's restart takes over (boot 1), the owed restore completes; "
          "every default invariant holds", g.boot_no == 1 and g.status("dump").startswith("RESTORED OK")
          and g.invariants() == [] and g.invariants(form="count") == 0, str(g.invariants()))
    viols = [{"inv": "INV-A", "seq": 0, "detail": "x", "tags": []}, {"inv": "INV-B", "seq": 2, "detail": "y", "tags": ["N17"]},
             {"inv": "INV-B", "seq": 3, "detail": "z", "tags": ["N17", "PLATFORM-ABSENT"]}]
    evs = [_ev(0, "lab.x", {}, src="lab", boot=0), _ev(1, "fw.boot", {}, boot=1), _ev(2, "fw.write", {}, boot=1),
           _ev(3, "fw.write", {}, boot=2)]
    fv = L.filter_violations
    check("filter_violations: boot_from / tags (all of) / untagged / count / summary (seq-free, in seq order)",
          fv(viols, evs, boot_from=1, form="count") == 2 and fv(viols, evs, boot_from=2) == [viols[2]]
          and fv(viols, evs, tags=["N17"], form="count") == 2 and fv(viols, evs, tags=["N17", "PLATFORM-ABSENT"]) == [viols[2]]
          and fv(viols, evs, untagged=True) == [viols[0]] and fv(viols, evs) == viols
          and fv(viols, evs, form="summary") == [{"inv": "INV-A", "tags": [], "boot": 0}, {"inv": "INV-B", "tags": ["N17"],
                                                                                            "boot": 1},
                                                  {"inv": "INV-B", "tags": ["N17", "PLATFORM-ABSENT"], "boot": 2}])
    badf = [raises(L.LabHarnessError, fv, viols, evs, **kw)[0] for kw in (
        {"form": "table"}, {"boot_from": -1}, {"boot_from": True}, {"tags": []}, {"tags": "N17"},
        {"tags": ["N17"], "untagged": True})]
    check("...and refuses a bad form, boot_from, tags, or tags combined with untagged", all(badf), str(badf))
    base = {"schema": T.SCHEMA, "tier": "firmware", "seed": 1, "utc_start": "2026-10-21T10:50:00Z", "synthetic": True,
            "ownership": "lab self-test (synthetic SITE)", "source_anchors": [
                {"path": L.FW_REL, "text": "Free Power<->Dump dual durable-obligation dead-end (256-261)",
                 "line_at_record": 0}], "source_digests": {L.FW_REL: "0" * 64}, "world": {}, "grade": "VERIFIED",
            "confidence": "high", "failure_outcome": "harness self-test", "smallest_safe_repair_scope": "none (harness self-test)"}
    # B5: the Phase-B ghost's false_negative needs a used FP marker key - the completed-lease prelude of corpus PB-01-a
    # (fp_start minutes 1, run_for 200) comes first and every later action moves by 200 s
    ghost = dict(base, id="FW-00-selftest-ghost", title="lab self-test: a completed FP lease, then a Phase-B ghost, a Dump "
                 "START at a staged Stop SOC, a reboot into the dual-obligation lockout", classification="PASS",
                 invariant="INV-BOOT-MIRROR",
                 actions=[{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 1}},
                          {"at_s": 60, "do": "run_for", "args": {"seconds": 200}},
                          {"at_s": 260, "do": "nvs_policy", "args": {"tag": "fp.valid", "state": 1,
                                                                     "mode": "false_negative"}},
                          {"at_s": 260, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                          {"at_s": 261, "do": "telemetry", "args": {"grid_w": -1000, "batt_w": 1050}},
                          {"at_s": 262, "do": "set_number", "args": {"entity": "dump_stop_soc", "value": 30}},
                          {"at_s": 262, "do": "dump_start", "args": {"power_w": 1000, "minutes": 30}},
                          {"at_s": 320, "do": "reboot", "args": {"down_s": 5}},
                          {"at_s": 400, "do": "run_for", "args": {"seconds": 60}}],
                 expect=[{"observe": "invariants", "args": {"names": ["INV-BOOT-MIRROR"]}, "op": "==", "value": []},
                         {"observe": "invariants", "args": {"names": ["INV-NO-2ND-RESTORER"], "form": "count"}, "op": ">=",
                          "value": 1},
                         {"observe": "invariants", "args": {"names": ["INV-NO-2ND-RESTORER"], "boot_from": 1,
                                                            "form": "count"}, "op": "==", "value": 0},
                         {"observe": "invariants", "args": {"names": ["INV-NO-2ND-RESTORER"], "form": "summary"},
                          "op": "contains", "value": {"inv": "INV-NO-2ND-RESTORER", "tags": [], "boot": 0}},
                         {"observe": "status_history", "args": {"dom": "dump"}, "op": "contains",
                          "value": "ACTIVE - VERIFIED OK; target 1000W export - SETTLING - battery ceiling 1000W "
                                   "(feed-forward start: house 0W, PV 0W); Stop SOC 30%"},
                         {"observe": "corrupt", "args": {"dom": "fp"}, "op": "==", "value": True},
                         {"observe": "corrupt", "args": {"dom": "dump"}, "op": "==", "value": True},
                         {"observe": "text_state", "args": {"entity": "dump_recovery_state"}, "op": "startswith",
                          "value": "LOCKED"}])
    leak = dict(base, id="FW-00-selftest-leak", title="lab self-test: a reg244 Apply, then an injected leaked lock "
                "escalates to the firmware restart; the reg244 obligation survives it", classification="PASS",
                invariant="INV-RESTORE-BOUND",
                actions=[{"at_s": 60, "do": "r244_apply", "args": {"target": "Allow Export"}},
                         {"at_s": 70, "do": "inject_global", "args": {"name": "manual_write_in_progress", "value": True}},
                         {"at_s": 71, "do": "run_for", "args": {"seconds": 240}},
                         {"at_s": 400, "do": "run_for", "args": {"seconds": 1}}],
                expect=[{"observe": "boot_no", "args": {}, "op": "==", "value": 1},
                        {"observe": "nvs_marker", "args": {"dom": "r244"}, "op": "==", "value": "RESTORE_REQUIRED"},
                        {"observe": "text_state", "args": {"entity": "reg244_last_result"}, "op": "startswith",
                         "value": "RECOVERY REQUIRED"},
                        {"observe": "invariants", "args": {}, "op": "==", "value": []},
                        {"observe": "invariants", "args": {"form": "count"}, "op": "==", "value": 0},
                        {"observe": "quiet_state", "args": {}, "op": "==", "value": {
                            "booting": False, "locked": False, "diff": {}, "visible": ["r244.snap"],
                            "nvs": {"dump": "ABSENT", "fp": "ABSENT", "r244": "RESTORE_REQUIRED"}, "silent": False}}])
    for draft in (ghost, leak):
        name = f"{draft['id']}: record() then replay() with the new actions / observers / filters: ok, no drift, digest equal"
        doc = recorded(draft, name)
        if doc is None:
            continue
        res = T.replay(doc)
        check(name, res.ok and not res.drift and res.digest == doc["trace_digest"] and not res.failed_expectations,
              str(res.failed_expectations)[:400])
        alt = copy.deepcopy(doc)
        alt["expect"][0]["value"] = [] if alt["expect"][0]["value"] != [] else [{"inv": "X"}]
        check(f"{draft['id']}: negative control - an altered first expectation FAILS the replay",
              not T.replay(alt).ok)


def section_replay() -> None:
    print("[17] replay tier 'firmware': registered actions / observers, record -> replay, altered expectation fails")
    reg = T.registered(L.TIER)
    check("tier 'firmware' has its factory, every spec action and every spec observer registered",
          reg["factory"] and {"fp_start", "fp_end", "dump_start", "dump_end", "dump_force_restore", "dump_accept",
                              "fp_operator", "manual_slot_apply", "run_for", "reboot", "nvs_policy", "modbus_policy",
                              "set_link", "set_bus_idle", "set_register", "telemetry", "config_poll", "rtc_lock_windows",
                              "arm_power_cut"} <= set(reg["actions"])
          and {"status", "status_history", "ha_view", "nvs_marker", "corrupt", "bank", "writes", "globals",
               "invariants"} <= set(reg["observers"]), str(reg))
    draft = {"schema": T.SCHEMA, "id": "FW-00-selftest", "title": "lab self-test: a 30 min Free Power lease ends on its "
             "UTC epoch", "tier": "firmware", "seed": 1, "utc_start": "2026-10-21T10:50:00Z", "synthetic": True,
             "ownership": "Free Power only; no other obligation", "source_anchors": [
                 {"path": L.FW_REL, "text": 'id(free_power_status).publish_state("ACTIVE - reboot recovery pending");',
                  "line_at_record": 0}],
             "source_digests": {L.FW_REL: "0" * 64}, "world": {},
             "actions": [{"at_s": 60, "do": "fp_start", "args": {"power_w": 3000, "minutes": 30}},
                         {"at_s": 60, "do": "nvs_policy", "args": {"tag": "dump.valid", "state": 1,
                                                                   "mode": "not_landed"}},
                         {"at_s": 1300, "do": "reboot", "args": {"down_s": 5}},
                         {"at_s": 1400, "do": "run_for", "args": {"seconds": 60}}],
             "expect": [{"observe": "status", "args": {"dom": "fp"}, "op": "startswith", "value": "RESTORED OK"},
                        {"observe": "nvs_marker", "args": {"dom": "fp"}, "op": "==", "value": "CLEAR"},
                        {"observe": "invariants", "args": {}, "op": "==", "value": []},
                        {"observe": "bank", "args": {"addrs": [230, 256]}, "op": "==", "value": {"230": 120, "256": 8000}}],
             "classification": "PASS", "invariant": "INV-NO-RESUME", "grade": "VERIFIED", "confidence": "high",
             "failure_outcome": "a rebooted lease would resume", "smallest_safe_repair_scope": "none (harness self-test)"}
    name = "record() then replay(): ok, no drift, digest equal to trace_digest, every expectation holds"
    doc = recorded(draft, name)
    if doc is not None:
        res = T.replay(doc)
        check(name, res.ok and not res.drift and res.digest == doc["trace_digest"] and not res.failed_expectations,
              str(res.failed_expectations))
        bad = copy.deepcopy(doc)
        bad["expect"][1]["value"] = "RESTORE_REQUIRED"
        res2 = T.replay(bad)
        check("negative control: the same corpus document with an altered expectation FAILS", not res2.ok
              and len(res2.failed_expectations) == 1)
    w = L.make_world(utc_start=U0, seed=0, bank={"257": 7000}, dump_limits=[8000, 8000])
    check("make_world converts JSON world kwargs (string bank keys, list dump_limits)",
          w.bank[257] == 7000 and w.original[257] == 7000 and w.dump_limits == (8000, 8000))
    hit, msg = raises(L.LabHarnessError, L.make_world, utc_start=U0, seed=0, fw={})
    check("replay worlds refuse a non-worktree firmware", hit, msg)


# =============================================================================================================================
# run
# =============================================================================================================================
section_discovery()
section_strict()
section_clock_boot()
section_cadence()
fp_world = section_fp_happy()
dump_world = section_dump_happy()
section_arms()
section_reboot()
section_prefs()
section_nvs()
section_nvs_used_key()
section_boot_faults()
section_power_cut()
section_modbus_link()
section_polls()
section_rtc_window()
section_operators()
section_determinism()
rb = world()
rb.fp_start(power_w=3000, minutes=60)
rb.run_for(120)
rb.reboot()
rb.run_for(60)
section_invariants([fp_world, dump_world, rb])
section_silent_override()
section_boot_mirror()
section_hl1()
section_replay()
section_replay_additions()
check("process-global state untouched: ds.Entity has no lab attribute, ds.Sim.outcome_fn is not a property",
      not hasattr(ds.Entity, "current_option") and not isinstance(ds.Sim.__dict__.get("outcome_fn"), property))

RUNTIME_S = time.perf_counter() - T0
print("")
check_phase_registry()
T.finish("test_lab_selftest_firmware", passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=PINS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME_S)
if FAILURES:
    sys.exit(1)
