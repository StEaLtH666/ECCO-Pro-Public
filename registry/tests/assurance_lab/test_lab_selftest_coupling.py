#!/usr/bin/env python3
"""Harness self-tests of the assurance lab CoupledWorld (_lab_ha): the REAL FPS1 / DGS1 / SMR1 packages in the HA sim World
coupled to the REAL dongle firmware (FirmwareWorld) through RealDongle - the dongle-entity mapping (every id the packages
use, slug rule, firmware targets), scheduled Free Power and Dump to Grid runs end to end, HA-visible binary sensors versus
the firmware lambdas, the projection of synchronous firmware runs and its fail-loud interleaving rule, unmapped entities,
S.LOCAL restoration, exact time triggers, HA restart / dongle reboot / API outage / offline policy, polled template sensors
('unknown' before a boot's first sample, as FPS1 / DGS1's | float(-1) reads it; warm-up samples), determinism, the coupled
invariant checkers (hand-built negative controls), invariant parameter routing (per invariant, never dropped) and the
'coupled' replay tier. Offline assurance lab V0 (test-only: no
network, no Home Assistant, no hardware; writes nothing). These are HARNESS capability checks; the coupled behaviours they
drive (window overrun, restart recovery) are the Phase C scenarios' subject and are reported here as info, not classified.
Quick mode (about 10 s here); ECCO_LAB_EXTENDED=1 / --extended adds a watchdog-phase sweep (0..14 s) of the Free Power
window-end overrun under the 'measured' and 'polls' bus models (about 25 s more).
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
    "...after the reconnect (new boot uptime 13 s) the polled attempt counter reads 'unknown'": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
    "world start (firmware uptime 2 s): every polled sensor reads 'unknown'": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
    "dongle reboot: the reconnect at new-boot uptime 12 s publishes 'unknown'": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
    "...FPS1 and DGS1's own no-answer condition reads now_a = -1": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
    "warmup_s=100: the warm-up samples on the uptime grid": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
    "warmup_s=20 (uptime 22 s, before any sample)": (
        "coupled-tier model self-test of the polled template sensors' first sample (one period after power-on on the "
        "uptime grid, ISS-HA-1); ESPHome samples a PollingComponent first within min(T/2, 5 s) of setup and then at "
        "now+T, so this pinned model fails under the phase patch with the polled-sensor part"),
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
import os  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

import yaml  # noqa: E402

T0 = time.perf_counter()
EXTENDED = os.environ.get("ECCO_LAB_EXTENDED") == "1" or "--extended" in sys.argv[1:]

import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _dump_sim as ds  # noqa: E402
import _lab_clock as C  # noqa: E402
import _lab_trace as T  # noqa: E402
import _lab_fw as L  # noqa: E402
import _lab_ha as H  # noqa: E402

FIXED_LOCAL = S.LOCAL                              # the sim's own fixed UTC+1 object (identity is checked)
U0 = C.utc_of_local(2026, 10, 21, 11, 50)          # a synthetic Wednesday, BST; the worlds start here
ST = C.utc_of_local(2026, 10, 21, 12, 0)           # the synthetic scheduled start (12:00 BST = 11:00Z)
IDLE = H.BusModel(windows=[])                      # a never-busy bus: the nominal runs
ORIG = dict(L.SITE["original"])
BINARY = ("fp_active", "fp_snapshot_valid", "fp_op", "dump_active", "dump_snapshot_valid", "dump_op",
          "manual_write_in_progress")
print(f"  info  mode: {'EXTENDED' if EXTENDED else 'quick'}")


def raises(exc_type, fn, *args, **kwargs) -> tuple[bool, str]:
    """(fn raised exc_type, its message). Any other exception propagates: a crash is a FAIL, never a pass."""
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return True, str(exc)
    return False, "no exception"


def onoff(v) -> str:
    return "on" if v else "off"


def events(cw, kind, **match) -> list:
    return [e for e in cw.log.events(kind=kind) if all(e["data"].get(k) == v for k, v in match.items())]


def fw_status_events(cw, dom) -> list:
    return [(e["t_utc"], e["data"]["text"]) for e in events(cw, "fw.status", dom=dom)]


class Sampler:
    """At every minute tick where every scheduled HA delivery has landed and no projected transaction is open: the
    HA-visible binary sensors versus the firmware's REAL lambdas (FirmwareWorld.ha_view)."""

    def __init__(self, cw):
        self.cw, self.n, self.bad = cw, 0, []
        cw.w.listeners.append(self.on)

    def on(self, kind) -> None:
        cw = self.cw
        d = cw.dongle
        if kind != "minute" or d.off or not d.connected or cw.w.t <= d.pending_until or cw.w.t < d.busy_until:
            return
        ha, truth = cw.ha_visible(), cw.fw.ha_view()
        self.n += 1
        diff = {k: (ha[k], onoff(truth[k])) for k in BINARY if ha[k] != onoff(truth[k])}
        if diff:
            self.bad.append((round(cw.w.t - ST, 1), diff))


def wd_slots_utc(cw, job: str) -> list:
    """UTC instants of every scheduled run of `job` (FirmwareWorld.job_trace, boot 0: on_boot at utc_start, boot_ms)."""
    fw = cw.fw
    return [U0 + (up - fw.boot_ms) / 1000 for up, j in fw.job_trace if j == job]


def txn_for(cw, eid: str) -> dict:
    return next(e["data"] for e in events(cw, "dongle.txn") if (e["data"]["cmd"] or {}).get("e") == eid)


# =============================================================================================================================
def section_mapping(cw) -> None:
    print("[0] mapping: every dongle entity id the three packages use -> a firmware entity (slug rule); the view; anchors")
    texts = {n: H.package_text(n) for n in H.PACKAGES}
    ids = H.package_dongle_ids(texts.values())
    emap = H.dongle_entity_map()
    info = L.fw_info(L.load_fw())
    print(f"  info  {len(ids)} dongle entity ids used by fps1 + dgs1 + smr1 (12 of them assembled TOU slot ids)")
    check(f"every dongle entity id the packages use maps to a firmware entity ({len(ids)} ids)",
          all(i in emap for i in ids), str([i for i in ids if i not in emap]))
    dom_ok = all(info.entities[emap[i][0]][0] in [k for k, d in H._HA_DOMAIN.items() if d == i.split(".")[0]] for i in ids)
    check("...each mapping target exists in the firmware entity registry with a kind of the id's HA domain", dom_ok)
    tou = [i for i in ids if "ecco_timezone" in i]
    check("DGS1's assembled id 'sensor.ecco_clock_dongle_ecco_timezone' ~ i ~ '_time' / '_charge' expands to the 12 slot "
          "ids, mapped to ecco_tou1..6_time / _charge", len(tou) == 12 and sorted(emap[i][0] for i in tou) == sorted(
              f"ecco_tou{n}_{k}" for n in range(1, 7) for k in ("time", "charge")))
    used_cmd = {i for i in ids if i.split(".")[0] in ("switch", "number", "button")}
    check(f"every switch / number / button id the packages use is a RealDongle command target ({len(used_cmd)} ids)",
          all(i in cw.dongle.commands and cw.dongle.commands[i][1] == i.split(".")[0] for i in used_cmd),
          str(sorted(used_cmd - set(cw.dongle.commands))))
    check("the schedules' START buttons map to the firmware START buttons (start_free_power_button, "
          "start_dump_to_grid_button)", emap[S.E_PRESS][0] == H.START_BUTTON["fp"] and emap[D.D_PRESS][0]
          == H.START_BUTTON["dump"] and cw.dongle.press_scripts(H.START_BUTTON["fp"]) == {"start_free_power_override"})
    srcs = {}
    for h, s in cw.dongle.view.items():
        srcs.setdefault(s["src"], []).append(h)
    print(f"  info  view sources: {', '.join(f'{k} {len(v)}' for k, v in sorted(srcs.items()))}")
    check("the view: 7 template binary sensors through their REAL lambdas, 3 polled template sensors (two attempt "
          "counters 30 s, the TOU power ceiling 60 s), 12 TOU slot sensors (MODEL), the rest from published entity states",
          len(srcs.get("lambda", [])) == 7 and sorted(cw.dongle.view[h]["period_ms"] for h in srcs.get("polled", []))
          == [30000, 30000, 60000] and len(srcs.get("tou", [])) == 12)
    viewed = [i for i in ids if i.split(".")[0] != "button" and i not in tou] + [H.E_CEILING]
    check("every HA-read dongle id except the TOU slot sensors has a state in the HA state machine once the world is "
          "built; the TOU slot sensors are not published before the firmware's first configuration Block B response",
          all(i in cw.w.states for i in viewed) and not any(i in cw.w.states for i in tou),
          str([i for i in viewed if i not in cw.w.states]))
    cw.run_until(U0 + 150)
    slots = [(cw.ha_state(f"sensor.{S.P}ecco_timezone{n}_time"), cw.ha_state(f"sensor.{S.P}ecco_timezone{n}_charge"))
             for n in range(1, 7)]
    check("after the first configuration poll the 12 TOU slot sensors show the synthetic site's slots (slot 1 00:00 Grid, "
          "the rest charge None) in the firmware's own display format", slots == [
              ("00:00", "Grid"), ("04:00", "None"), ("08:00", "None"), ("13:00", "None"), ("18:00", "None"),
              ("21:00", "None")] and cw.fw.sim.g["cfg_block_b_seq"] > 0, str(slots))
    check("numbers carry their firmware min / max / step attributes (what SMR1's validity plan reads)",
          cw.w.states[D.D_SOC][1] == {"min": 10.0, "max": 90.0, "step": 1.0}
          and cw.w.states[S.E_PWR][1] == {"min": 500.0, "max": 8000.0, "step": 100.0}, str(cw.w.states[D.D_SOC]))
    lim = cw.w.state(H.E_LIMIT)
    cw.w.set(H.E_CEILING, "unavailable")
    lim_off = cw.w.state(H.E_LIMIT)
    cw.w.set(H.E_CEILING, "8000.0")
    check("the effective grid charge limit is the REAL ecco_runtime_config template: min(firmware ceiling, synthetic "
          "operating limit) = 8000.0, and 'unavailable' when the dongle's ceiling sensor is", lim == "8000.0"
          and lim_off == "unavailable", f"{lim} / {lim_off}")
    bad = [(p, t, T.anchor_count(p, t)) for p, t in H.SOURCE_ANCHORS if T.anchor_count(p, t)[0] != 1]
    check(f"every SOURCE_ANCHORS text occurs exactly once in its file ({len(H.SOURCE_ANCHORS)} anchors)", not bad, str(bad))
    mutant = texts["dgs1"].replace(H.ASSEMBLED_TOU[0], H.ASSEMBLED_TOU[0].replace("' ~ i ~ '", "' ~ (i) ~ '"))
    hit, _msg = raises(H.LabHarnessError, H.package_dongle_ids, [texts["fps1"], mutant])
    check("negative control: a DGS1 text whose assembled TOU id template changed is REJECTED (no silent partial scan)",
          mutant != texts["dgs1"] and hit)


def section_unmapped(cw) -> None:
    print("[5] unmapped dongle entities raise S.Unsupported")
    calls = (("switch.turn_on", f"switch.{S.P}no_such_switch", {}), ("number.set_value", S.E_ARM, {"value": 1}),
             ("button.press", "button.other_device_start", {}), ("switch.turn_off", S.E_STATUS, {}))
    res = [raises(S.Unsupported, cw.w.call, svc, [e], data) for svc, e, data in calls]
    check("a service call to an unknown dongle id, to a mapped id of the wrong kind (number on a switch, switch on a text "
          "sensor) and to a non-dongle button raises S.Unsupported", all(r[0] for r in res), str(res))
    check("...and owner_press of an unmapped button raises S.Unsupported at the call",
          raises(S.Unsupported, cw.owner_press, f"button.{S.P}no_such_button")[0])


# =============================================================================================================================
def run_fp(bus, wd_phase_s=0.0, until_min=65):
    cw = H.CoupledWorld(U0, bus=bus, wd_phase_s=wd_phase_s)
    cw.fw.job_trace = []
    smp = Sampler(cw)
    probe = {}

    def on_state(kind):   # the first instant HA shows the START transaction: look again 0.5 s later
        if kind == "state" and "t" not in probe and cw.w.states.get(S.E_OP, ("",))[0] == "on":
            probe["t"] = cw.w.t
            cw.w.after(0.5, lambda: probe.update(ha_op=cw.w.state(S.E_OP), fw_op=cw.fw.ha_view()["fp_op"],
                                                 fw_active=cw.fw.ha_view()["fp_active"]))
    cw.w.listeners.append(on_state)
    cw.owner_set(S.E_DUR, 40, at_utc=U0 + 30)      # the owner's manual Free Power duration (SMR1 must put it back)
    cw.arm_schedule("fp", "2026-10-21 12:00:00", 60, 3000, at_utc=U0 + 60)
    cw.run_until(ST + 30 * 60)
    mid = {"status": cw.schedule_status("fp"), "fw": cw.fw_status("fp"), "ha": cw.ha_visible(),
           "end": cw.fw.globals_view(["free_power_end_epoch"])["free_power_end_epoch"]}
    cw.run_until(ST + until_min * 60)
    return cw, smp, probe, mid


def section_fp() -> None:
    print("[1] scheduled Free Power 2026-10-21 12:00 BST, 60 min, 3000 W (synthetic) end to end, never-busy bus")
    cw, smp, probe, mid = run_fp(IDLE)
    try:
        last = cw.last_result("fp")
        print(f"  info  FPS1 last result: {last!r}")
        check("FPS1 shows STARTED OK for the full 60 min", last.startswith("STARTED OK - 3000W for 60 min (attempt 1"), last)
        check("mid-lease: FPS1 status ACTIVE, firmware 'ACTIVE - VERIFIED OK', HA Free Power Active and Snapshot Valid on",
              mid["status"] == "ACTIVE" and mid["fw"].startswith("ACTIVE - VERIFIED OK; 58A grid charge")
              and mid["ha"]["fp_active"] == "on" and mid["ha"]["fp_snapshot_valid"] == "on", str(mid))
        txn = txn_for(cw, S.E_PRESS)
        print(f"  info  START transaction projected [{txn['t0'] - ST:.3f}, {txn['until'] - ST:.3f}] s after 12:00: "
              f"{txn['ops']} Modbus ops, {txn['commits']} commits, scripts {txn['scripts']}")
        check("the firmware lease end epoch is the gate second + 60 min (UTC epoch)", mid["end"] == int(txn["t0"]) + 3600,
              f"{mid['end']} vs {int(txn['t0'])} + 3600")
        slot = min(t for t in wd_slots_utc(cw, "fp_wd") if t >= mid["end"])
        after = [(t, x) for t, x in fw_status_events(cw, "fp") if t > txn["until"]]
        first = after[0] if after else (None, "")
        check("the lease ends at its epoch: the firmware's first end action is RESTORING at the first FP watchdog slot at or "
              "after the end epoch (nothing earlier)", first[0] == slot and first[1].startswith("RESTORING"),
              f"{first} vs slot {slot - ST}")
        bank = cw.fw.bank_view(sorted(ORIG))
        check("the firmware restore verifies: 'RESTORED OK - original inverter settings verified', every owned register at "
              "the synthetic ORIGINAL, durable marker CLEAR", cw.fw_status("fp") == "RESTORED OK - original inverter "
              "settings verified" and bank == {str(a): v for a, v in ORIG.items()} and cw.fw.nvs_marker("fp") == "CLEAR")
        ov = cw.window_overruns()
        print(f"  info  window end 13:00:00 BST; restore at the watchdog slot +{slot - ST - 3600:.1f} s; lease end (HA "
              f"truth: active and snapshot off) overrun {ov[0]['overrun_s']} s")
        restore = next(e["data"] for e in events(cw, "dongle.txn") if e["data"]["t0"] == slot)
        check("window_overruns measures the projected lease end (active and snapshot off, inside the restore transaction "
              "that starts at the watchdog slot) against the window end", len(ov) == 1 and ov[0]["lease_end"] is not None
              and slot < ov[0]["lease_end"] <= restore["until"]
              and ov[0]["overrun_s"] == round(ov[0]["lease_end"] - (ST + 3600), 3), f"{ov} {restore}")
        print(f"  info  FPS1 end: status {cw.schedule_status('fp')!r}; SMR1 Free Power state {cw.smr1_state('fp')!r}")
        check("FPS1 end state: COMPLETED, disarmed, write enable off, no notification",
              cw.schedule_status("fp") == "COMPLETED" and cw.ha_state(H.ARMED["fp"]) == "off"
              and cw.ha_state(S.E_ARM) == "off" and cw.notifications() == {})
        check("SMR1 end state: RESTORED, the owner's manual 8000 W / 40 min back on the dongle (firmware numbers too)",
              cw.smr1_state("fp").startswith("RESTORED") and (cw.ha_state(S.E_PWR), cw.ha_state(S.E_DUR))
              == ("8000.0", "40.0") and (cw.fw.sim.ent("free_power_max_power").state,
                                         cw.fw.sim.ent("free_power_duration_minutes").state) == (8000.0, 40.0))
        check(f"HA-visible binary sensors equal the firmware lambdas after the publish latency ({smp.n} quiescent minute "
              "samples)", smp.n >= 60 and not smp.bad, str(smp.bad[:3]))
        check("projection: 0.5 s into the START transaction HA shows Operation In Progress on while the synchronous firmware "
              "has already finished (truth: op off, active on)", probe.get("ha_op") == "on" and probe.get("fw_op") is False
              and probe.get("fw_active") is True, str(probe))
        check("the attempt counter (polled every 30 s) reads the firmware's 1 in HA", cw.ha_state(S.E_ATTEMPTS) == "1.0")
        hf, fwv = cw.invariants(), L.check_invariants(cw.log)
        check("no coupled (INV-HF-*) and no firmware invariant violation on the merged log", not hf and not fwv,
              str(hf + fwv)[:300])
        check("the merged EventLog is UTC-monotonic", cw.log.utc_regressions() == [], str(cw.log.utc_regressions()[:5]))
        n = len(cw.log)
        print(f"  info  merged log: {n} events ({len(events(cw, 'ha.state'))} HA state changes, "
              f"{len(events(cw, 'ha.call'))} HA service calls, {len(events(cw, 'dongle.cmd'))} dongle commands)")
    finally:
        cw.close()


def section_fp_measured_bus() -> None:
    print("[2] the same Free Power run with the default bus model ('measured' 11 Oct windows, phase 0): report only")
    cw, smp, _probe, mid = run_fp(H.BusModel())
    try:
        after = [(round(t - ST - 3600, 1), x[:60]) for t, x in fw_status_events(cw, "fp") if t > ST + 3000]
        ov = cw.window_overruns()[0]["overrun_s"]
        print(f"  info  firmware end actions (s after 13:00:00): {after}")
        print(f"  info  default bus model: window-end overrun {ov} s (a watchdog slot inside a measured busy window defers "
              "the restore one period; HF-01 owns the classification)")
        check("default bus: the run still ends STARTED OK / COMPLETED / RESTORED OK and SMR1 RESTORED",
              cw.last_result("fp").startswith("STARTED OK") and cw.schedule_status("fp") == "COMPLETED"
              and cw.fw_status("fp").startswith("RESTORED OK") and cw.smr1_state("fp").startswith("RESTORED"))
        check("default bus: INV-HF-WINDOW reports exactly the measured overrun when it exceeds the 30 s bound (checker "
              "consistency)", [v["inv"] for v in cw.invariants()] == (["INV-HF-WINDOW"] if ov > 30 else [])
              and all(str(ov) in v["detail"] for v in cw.invariants()))
        check("default bus: HA-visible binary sensors still equal the firmware lambdas at every quiescent sample",
              smp.n >= 60 and not smp.bad, str(smp.bad[:3]))
    finally:
        cw.close()


def section_dump() -> None:
    print("[3] scheduled Dump to Grid 2026-10-21 12:00 BST, 30 min, 3000 W, Stop SOC 20 % (synthetic) end to end, "
          "never-busy bus, dump_plant MODEL")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw.fw.job_trace = []
        smp = Sampler(cw)
        cw.dump_plant()
        cw.arm_schedule("dump", "2026-10-21 12:00:00", 30, 3000, stop_soc=20, at_utc=U0 + 60)
        cw.run_until(ST + 15 * 60)
        mid = (cw.schedule_status("dump"), cw.fw_status("dump"), cw.ha_visible(),
               cw.fw.globals_view(["dump_end_epoch"])["dump_end_epoch"])
        cw.run_until(ST + 40 * 60)
        last = cw.last_result("dump")
        print(f"  info  DGS1 last result: {last!r}")
        check("DGS1 shows STARTED OK for the full 30 min with Stop SOC 20 %",
              last.startswith("STARTED OK - 3000W for 30 min, Stop SOC 20% (attempt 1"), last)
        check("mid-lease: DGS1 status ACTIVE, firmware ACTIVE - VERIFIED OK (target 3000W, TRACKING), HA Dump Active on",
              mid[0] == "ACTIVE" and mid[1].startswith("ACTIVE - VERIFIED OK; target 3000W export - TRACKING")
              and mid[2]["dump_active"] == "on" and mid[2]["dump_snapshot_valid"] == "on", str(mid[:2]))
        txn = txn_for(cw, D.D_PRESS)
        print(f"  info  START transaction projected [{txn['t0'] - ST:.3f}, {txn['until'] - ST:.3f}] s: {txn['ops']} Modbus "
              f"ops, {txn['commits']} commits")
        check("the firmware lease end epoch is the gate second + 30 min", mid[3] == int(txn["t0"]) + 1800,
              f"{mid[3]} vs {int(txn['t0'])}")
        slot = min(t for t in wd_slots_utc(cw, "dump_wd") if t >= mid[3])
        ends = [(t, x) for t, x in fw_status_events(cw, "dump_end")]
        check("the lease ends at its epoch: dump_last_end_reason DURATION EXPIRED at the first Dump watchdog slot at or "
              "after the end epoch", ends and ends[-1] == (slot, "DURATION EXPIRED"), f"{ends[-1:]} vs slot {slot - ST}")
        bank = cw.fw.bank_view(sorted(ORIG))
        check("the firmware restore verifies: 'RESTORED OK - original inverter settings verified', owned registers at the "
              "ORIGINAL, durable marker CLEAR", cw.fw_status("dump") == "RESTORED OK - original inverter settings verified"
              and bank == {str(a): v for a, v in ORIG.items()} and cw.fw.nvs_marker("dump") == "CLEAR")
        ov = cw.window_overruns()
        print(f"  info  window end 12:30:00 BST; lease end overrun {ov[0]['overrun_s']} s; DGS1 status "
              f"{cw.schedule_status('dump')!r}; SMR1 Dump state {cw.smr1_state('dump')!r}")
        check("DGS1 end state: COMPLETED, disarmed, write enable off, no notification",
              cw.schedule_status("dump") == "COMPLETED" and cw.ha_state(H.ARMED["dump"]) == "off"
              and cw.ha_state(D.D_ARM) == "off" and cw.notifications() == {})
        check("SMR1 end state: RESTORED, the firmware's initial manual values 1000 W / 25 % / 60 min back",
              cw.smr1_state("dump").startswith("RESTORED") and tuple(cw.ha_state(n) for n in H.NUMBERS["dump"])
              == ("1000.0", "25.0", "60.0"))
        check(f"HA-visible binary sensors equal the firmware lambdas ({smp.n} quiescent minute samples)",
              smp.n >= 30 and not smp.bad, str(smp.bad[:3]))
        hf, fwv = cw.invariants(), L.check_invariants(cw.log)
        check("no coupled and no firmware invariant violation; UTC-monotonic log", not hf and not fwv
              and cw.log.utc_regressions() == [], str(hf + fwv)[:300])
        check("the dump_plant MODEL logged its environment (export follows the controller's ceiling)",
              any(e["data"]["batt_w"] > 0 and e["data"]["grid_w"] < 0 for e in events(cw, "env.plant")))
    finally:
        cw.close()


# =============================================================================================================================
def manual_fp_start(cw, at, minutes=30) -> float:
    """The owner's own Free Power start from the dashboard (via HA): stage, arm, press 3 s later; returns the press time."""
    cw.owner_set(S.E_PWR, 3000, at_utc=at)
    cw.owner_set(S.E_DUR, minutes, at_utc=at)
    cw.owner_set(S.E_ARM, True, at_utc=at + 1)
    cw.owner_press(S.E_PRESS, at_utc=at + 3)
    return at + 3


def section_projection() -> None:
    print("[4] projection: the START transaction's busy window; same-script press dropped; any other mutation fails loud")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        press = manual_fp_start(cw, U0 + 240)
        cw.run_until(press + cw.lat.press_s[0] + 0.5)
        d = cw.dongle
        txn = txn_for(cw, S.E_PRESS)
        print(f"  info  window [{txn['t0'] - press:.3f}, {txn['until'] - press:.3f}] s after the press")
        check("inside the window: HA shows Operation In Progress on, the firmware truth is already ACTIVE (op off)",
              cw.w.t < d.busy_until and cw.ha_state(S.E_OP) == "on" and cw.fw.ha_view()["fp_op"] is False
              and cw.fw.ha_view()["fp_active"] is True)
        n0 = len(events(cw, "dongle.dropped"))
        cw.owner_press(S.E_PRESS, via="dongle")
        check("a second press of the same START button inside the window is DROPPED (ESPHome script mode single), logged",
              [e["data"]["why"] for e in events(cw, "dongle.dropped")][n0:] == ["busy_same_script"])
        hit, msg = raises(H.LabUnsupported, cw.owner_set, S.E_DUR, 20, via="dongle")
        check("a number write inside the window raises LabUnsupported('interleaving inside a projected firmware "
              "transaction is not modelled')", hit and "interleaving inside a projected firmware transaction is not "
              "modelled" in msg, msg)
        check("...as do another domain's START press, set_env and a dongle reboot inside the window",
              raises(H.LabUnsupported, cw.owner_press, D.D_PRESS, via="dongle")[0]
              and raises(H.LabUnsupported, cw.set_env, soc=60)[0] and raises(H.LabUnsupported, cw.reboot_dongle, None)[0])
        cw.run_until(d.busy_until + 1)
        cw.owner_set(S.E_DUR, 20, via="dongle")
        check("after the window the same write is applied (firmware number 20, HA shows it after the publish latency)",
              cw.fw.sim.ent("free_power_duration_minutes").state == 20.0 and (cw.run_for(1) or True)
              and cw.ha_state(S.E_DUR) == "20.0")
    finally:
        cw.close()
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        press = manual_fp_start(cw, U0 + 240)
        cw.owner_set(S.E_DUR, 25, at_utc=press + 1.0)    # through HA: applied cmd_s later, inside the window
        hit, msg = raises(H.LabUnsupported, cw.run_until, press + 10)
        check("the same interleaving through Home Assistant fails loud out of the World run (never applied silently)",
              hit and "number.set_value" in msg and cw.fw.sim.ent("free_power_duration_minutes").state == 30.0, msg)
    finally:
        cw.close()


def section_local() -> None:
    print("[6] S.LOCAL: London inside a world, the sim's own object restored after close, also on exception")
    hit = False
    try:
        with H.CoupledWorld(U0, bus=IDLE) as cw:
            inside = S.LOCAL is C.LONDON and abs(S.parse_local("2026-11-04 12:00:00") - C.utc_of_local(2026, 11, 4, 12)) < 1
            raise RuntimeError("scenario body failed")
    except RuntimeError:
        hit = True
    check("inside a London world S.LOCAL is _lab_clock.LONDON (a November wall time parses as GMT)", inside)
    check("...and after the world's body raised, S.LOCAL is the sim's own fixed object again (identity)",
          hit and S.LOCAL is FIXED_LOCAL and cw.closed)
    hit, _m = raises(H.LabHarnessError, H.CoupledWorld, U0, offline_policy="sometimes")
    check("a construction that fails restores S.LOCAL and frees the slot", hit and S.LOCAL is FIXED_LOCAL
          and not H._OPEN)
    a = H.CoupledWorld(U0, bus=IDLE)
    try:
        hit, msg = raises(H.LabHarnessError, H.CoupledWorld, U0)
        check("a second open CoupledWorld is refused (S.LOCAL and the sim modules are process-global)",
              hit and S.LOCAL is C.LONDON, msg)
    finally:
        a.close()
    b = H.CoupledWorld(U0, bus=IDLE, london=False)
    try:
        check("london=False leaves the sim's fixed UTC+1 zone in place", S.LOCAL is FIXED_LOCAL)
    finally:
        b.close()
    check("after every close S.LOCAL is the original object", S.LOCAL is FIXED_LOCAL and not H._OPEN)


def section_time_trigger() -> None:
    print("[7] exact time triggers: a 12:00:30 start fires at that second via schedule_time_triggers")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw.arm_schedule("fp", "2026-10-21 12:00:30", 5, 3000, at_utc=U0 + 60)
        cw.run_until(ST + 120)
        fire = next(a for a in cw.ha.automations if a.id == "ecco_free_power_schedule_fire")
        starts = [t - ST for t, i in fire.fired if i == "start"]
        press = [e["t_utc"] - ST for e in events(cw, "dongle.cmd", svc="button.press")]
        print(f"  info  start trigger at +{starts} s, START press reached the firmware at +{press} s")
        check("the time trigger fires exactly once, at 12:00:30.000, and the run starts", starts == [30.0]
              and press and press[0] > 30 and cw.last_result("fp").startswith("STARTED OK"), str(starts))
    finally:
        cw.close()
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw._schedule_time_triggers = lambda: None       # per instance: the sim's own polling only
        cw.arm_schedule("fp", "2026-10-21 12:00:30", 5, 3000, at_utc=U0 + 60)
        cw.run_until(ST + 300)
        fire = next(a for a in cw.ha.automations if a.id == "ecco_free_power_schedule_fire")
        ids = [i for _t, i in fire.fired]
        check("negative control: without schedule_time_triggers the 12:00:30 start never fires (only the watchdog's "
              "'missed' path at +3 min) - the helper is what makes non-:00 starts exact", "start" not in ids
              and "watchdog" in ids, str(fire.fired))
    finally:
        cw.close()


def section_lifecycle() -> None:
    print("[8] lifecycle: HA restart (graceful / crash rollback), dongle reboot, API outage, offline policy")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw.w.call("persistent_notification.create", [], {"notification_id": "lab_note", "title": "t", "message": "m"})
        cw.restart_ha(U0 + 300, 30, reconnect_gap_s=10)
        cw.run_until(U0 + 335)
        gap = {e: cw.ha_state(e) for e in (S.E_STATUS, S.E_ARM, S.E_OP, H.E_LIMIT)}
        cw.run_until(U0 + 342)
        back = (cw.ha_state(S.E_STATUS), cw.ha_state(S.E_ARM), cw.ha_state(S.E_OP), cw.ha_state(H.E_LIMIT))
        check("graceful restart: inside the reconnect gap the dongle entities read 'unavailable' (the effective limit "
              "too), then the firmware view is republished", set(gap.values()) == {"unavailable"}
              and back == ("Inactive", "off", "off", "8000.0"), f"{gap} {back}")
        check("...persistent notifications are cleared at start and the helpers' last_changed is the start instant",
              cw.notifications() == {} and cw.w.changed_at[H.ARMED["fp"]] == U0 + 330
              and [e["data"]["graceful"] for e in events(cw, "ha.stop")] == [True])
        cw.arm_schedule("fp", "2026-10-21 12:00:00", 60, 3000, at_utc=U0 + 360)
        cw.restart_ha(U0 + 420, 30, rollback_to_utc=U0 + 350)
        cw.run_until(U0 + 470)
        rb = events(cw, "ha.rollback")[0]["data"]["changes"]
        check("crash restart: every package helper rolls back to its value at rollback_to_utc (armed on -> off, the start "
              "helper that did not exist then removed -> unknown)", rb.get(H.ARMED["fp"]) == ["on", "off"]
              and rb.get(H.START_HELPER["fp"], [None, 1])[1] is None and cw.ha_state(H.ARMED["fp"]) == "off"
              and cw.ha_state(H.START_HELPER["fp"]) == "unknown", str(rb))
    finally:
        cw.close()
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        press = manual_fp_start(cw, U0 + 240, minutes=5)
        cw.run_until(press + 60)
        pre = (cw.ha_state(S.E_ATTEMPTS), cw.ha_state(S.E_ACTIVE))
        cw.reboot_dongle(press + 70, down_s=5.0, reconnect_gap_s=10.0)
        cw.run_until(press + 70.5)
        down = {cw.ha_state(e) for e in (S.E_STATUS, S.E_ACTIVE, S.E_ATTEMPTS, S.E_ARM)}
        cw.run_until(press + 70 + 5 + 2 + 10 + 1)
        post = (cw.ha_state(S.E_ATTEMPTS), cw.ha_state(S.E_ARM), cw.ha_state(S.E_STATUS))
        on = events(cw, "dongle.power_on")
        print(f"  info  reboot during an ACTIVE Free Power lease: firmware status after boot {cw.fw_status('fp')!r}")
        check("reboot_dongle: entities unavailable from the cut; the firmware boots at cut + down_s + boot_ms (FULL "
              "boot 1)", pre == ("1.0", "on") and down == {"unavailable"} and cw.fw.boot_no == 1 and len(on) == 1
              and on[0]["t_utc"] == press + 77)
        check("...after the reconnect (new boot uptime 13 s) the polled attempt counter reads 'unknown' (no sample of the "
              "new boot yet, never the live lambda), the ALWAYS_OFF write enable off, and the status is the firmware's own "
              "boot text", post[0] == "unknown" and post[1] == "off" and post[2] == cw.fw_status("fp")
              and post[2] != "unavailable", str(post))
        tou = f"sensor.{S.P}ecco_timezone1_time"
        mid_tou = cw.ha_state(tou)
        cw.run_until(press + 70 + 5 + 2 + 75)
        check("...the TOU slot sensors stay unpublished after the reboot until the new boot's first Block B response, "
              "then show the slots again", mid_tou == "unavailable" and cw.fw.sim.g["cfg_block_b_seq"] > 0
              and cw.ha_state(tou) == "00:00", f"{mid_tou} -> {cw.ha_state(tou)}")
        check("...and the attempt counter shows the new boot's RAM 0 once its first 30 s sample is due",
              cw.ha_state(S.E_ATTEMPTS) == "0.0" and cw.fw.sim.g["free_power_start_attempts"] == 0,
              cw.ha_state(S.E_ATTEMPTS))
    finally:
        cw.close()
    for policy in ("silent", "raise"):
        cw = H.CoupledWorld(U0, bus=IDLE, offline_policy=policy)
        try:
            cw.api_outage(U0 + 200, 20)
            cw.run_until(U0 + 205)
            hit, _m = raises(S.ServiceError, cw.w.call, "switch.turn_on", [S.E_ARM], {})
            dropped = [e["data"]["why"] for e in events(cw, "dongle.dropped")]
            cw.run_until(U0 + 230)
            ok = (hit if policy == "raise" else not hit) and dropped == ["offline"] and cw.ha_state(S.E_ARM) == "off" \
                and cw.fw.sim.ent("free_power_write_enable").state is False and cw.ha_state(S.E_STATUS) == "Inactive"
            check(f"offline_policy={policy!r}: a call during an API outage is "
                  f"{'refused with S.ServiceError' if policy == 'raise' else 'dropped silently'} (logged, never applied); "
                  "the view is republished after it", ok, f"{hit} {dropped}")
        finally:
            cw.close()


NOW_A = {d: "{% set now_a = states('sensor.ecco_clock_dongle_" + k + "_start_attempts_since_boot') | float(-1) %}"
         for d, k in (("fp", "free_power"), ("dump", "dump_to_grid"))}
ATTEMPTS = {"fp": S.E_ATTEMPTS, "dump": D.D_ATTEMPTS}


def no_answer_templates() -> dict:
    """{dom: the FPS1 / DGS1 no-answer retry condition (the one that reads the attempt counter through | float(-1))},
    taken from the parsed package YAML; its NOW_A line occurs exactly once in the package text."""
    def strings(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from strings(v)
        elif isinstance(node, list):
            for v in node:
                yield from strings(v)
        elif isinstance(node, str):
            yield node
    out = {}
    for d, pkg in (("fp", "fps1"), ("dump", "dgs1")):
        hits = [s for s in strings(yaml.safe_load(H.package_text(pkg))) if NOW_A[d] in s]
        if len(hits) != 1 or T.anchor_count(H.PACKAGES[pkg], NOW_A[d])[0] != 1:
            raise H.LabHarnessError(f"{pkg}: the no-answer condition anchor {NOW_A[d]!r} is not unique ({len(hits)})")
        out[d] = hits[0]
    return out


def section_polled() -> None:
    print("[13] polled template sensors: no state before a boot's first sample (world start, reboot reconnect), the "
          "last sample after an API outage, warm-up samples; FPS1 / DGS1 read 'unknown' through | float(-1)")
    pol = sorted((S.E_ATTEMPTS, D.D_ATTEMPTS, H.E_CEILING))
    tpl = no_answer_templates()

    def states(cw) -> list:
        return [cw.ha_state(h) for h in pol]

    def answer(cw, before: str) -> dict:   # {dom: (FPS1 / DGS1 now_a, the no-answer retry condition)} rendered by HA
        return {d: (cw.w.render(NOW_A[d] + "{{ now_a }}"), cw.w.render(t, {"attempts_before": before}).strip())
                for d, t in tpl.items()}
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        check("the three polled sensors are the attempt counters (30 s) and the TOU power ceiling (60 s)",
              sorted(h for h, s in cw.dongle.view.items() if s["src"] == "polled") == pol)
        start = (states(cw), cw.ha_state(H.E_LIMIT))
        cw.run_until(U0 + 27.9)
        pre_sample = states(cw)
        cw.run_until(U0 + 28.2)
        counters = states(cw)
        cw.run_until(U0 + 58.2)
        ceiling = (states(cw), cw.ha_state(H.E_LIMIT))
        check("world start (firmware uptime 2 s): every polled sensor reads 'unknown' and the effective limit "
              "'unavailable' until its first sample at uptime = update_interval (counters at +28 s, ceiling at +58 s)",
              start == (["unknown"] * 3, "unavailable") and pre_sample == ["unknown"] * 3
              and counters == ["0.0", "0.0", "unknown"] and ceiling == (["0.0", "0.0", "8000.0"], "8000.0"),
              f"{start} {pre_sample} {counters} {ceiling}")
        cw.api_outage(U0 + 100, 20)
        cw.run_until(U0 + 120.5)
        check("an API outage (no reboot) republishes the boot's last samples at the reconnect, not 'unknown'",
              states(cw) == ["0.0", "0.0", "8000.0"], str(states(cw)))
        before = cw.ha_state(S.E_ATTEMPTS)
        cw.reboot_dongle(U0 + 150, down_s=5.0)
        cw.run_until(U0 + 167.5)
        on = events(cw, "dongle.power_on")[0]["t_utc"]
        up = [e["t_utc"] for e in events(cw, "dongle.link", up=True, reason="power")]
        recon, ans = states(cw), answer(cw, before)
        early = [e for e in events(cw, "ha.state") if e["data"]["e"] in pol and on <= e["t_utc"] < on - 2 + 30
                 and e["data"]["s"] not in ("unknown", "unavailable")]
        check("dongle reboot: the reconnect at new-boot uptime 12 s publishes 'unknown' for every polled sensor, and no "
              "numeric state reaches HA before the new boot's first sample (the regression: the live lambda's 0.0)",
              on == U0 + 157 and up == [U0 + 167] and recon == ["unknown"] * 3 and not early, f"{recon} {early[:3]}")
        check("...FPS1 and DGS1's own no-answer condition reads now_a = -1 (states 'unknown' | float(-1)), so with "
              f"attempts_before {before!r} it is False: the 'never reached the dongle' retry branch is not taken",
              before == "0.0" and ans == {"fp": ("-1", "False"), "dump": ("-1", "False")}, str(ans))
        cw.run_until(on - 2 + 30 + 0.5)
        ans2 = answer(cw, before)
        check("...after the new boot's first 30 s sample the counters read 0.0 and the same condition is True (write "
              "enable off, nothing in progress): the branch turns on the sample alone",
              states(cw)[:2] == ["0.0", "0.0"] and ans2 == {"fp": ("0.0", "True"), "dump": ("0.0", "True")},
              f"{states(cw)} {ans2}")
    finally:
        cw.close()
    ref = L.FirmwareWorld(utc_start=U0 - 100, warmup_s=100, seed=0)
    cw = H.CoupledWorld(U0, bus=IDLE, fw_world_kwargs={"warmup_s": 100})
    try:
        fw_evs = lambda log: [(e["t_utc"], e["up_ms"], e["boot"], e["kind"], e["data"]) for e in log  # noqa: E731
                              if e["src"] == "fw"]
        nxt = {h: cw.dongle._polled_next[h] for h in pol}
        check("warmup_s=100: the warm-up samples on the uptime grid (counters at 30 / 60 / 90 s, ceiling at 60 s), so the "
              "world starts with 0.0 / 8000.0 and the effective limit, the next samples at uptime 120 s",
              states(cw) == ["0.0", "0.0", "8000.0"] and cw.ha_state(H.E_LIMIT) == "8000.0"
              and nxt == dict.fromkeys(pol, 120000) and cw.fw.sim.now_ms == 102000, f"{states(cw)} {nxt}")
        check("...the piecewise warm-up runs the same firmware as one FirmwareWorld run_for(100) (identical firmware "
              "events)", fw_evs(cw.log) == fw_evs(ref.log) and len(fw_evs(ref.log)) > 10, str(len(fw_evs(cw.log))))
    finally:
        cw.close()
    cw = H.CoupledWorld(U0, bus=IDLE, fw_world_kwargs={"warmup_s": 20})
    try:
        check("warmup_s=20 (uptime 22 s, before any sample): the polled sensors read 'unknown' at the start",
              states(cw) == ["unknown"] * 3, str(states(cw)))
    finally:
        cw.close()


def run_det(arm_at: float) -> tuple:
    cw = H.CoupledWorld(U0)
    try:
        cw.arm_schedule("fp", "2026-10-21 12:00:00", 5, 3000, at_utc=arm_at)
        cw.run_until(ST + 8 * 60)
        return cw.log.digest(), len(cw.log), cw.last_result("fp")
    finally:
        cw.close()


def section_determinism() -> None:
    print("[9] determinism: identical merged EventLog digest on rerun")
    a, b = run_det(U0 + 60), run_det(U0 + 60)
    check(f"two identical coupled runs give the identical merged EventLog ({a[1]} events, digest {a[0][:12]})", a == b)
    c = run_det(U0 + 61)
    check("arming one second later changes the digest", c[0] != a[0])


# =============================================================================================================================
def _e(seq, kind, data, t=0.0, src="lab") -> dict:
    return {"seq": seq, "t_utc": U0 + t, "up_ms": None, "boot": None, "src": src, "kind": kind, "data": data}


def _obl(**over):
    o = {d: {"act": False, "snap": False, "op": False} for d in H.DOMS}
    for k, v in over.items():
        d, f = k.split("_", 1)
        o[d][f] = v
    return o


def _cmd(seq, svc, e, by, t=0.0, value=None, old=None, fid=None, obl=None):
    return _e(seq, "dongle.cmd", {"svc": svc, "e": e, "fid": fid, "kind": svc.split(".")[0], "value": value, "by": by,
                                  "obl": obl or _obl(), "mw": False, "old": old}, t)


def section_checkers() -> None:
    print("[10] coupled invariant checkers: hand-built violating logs are caught, clean twins are not")
    st = lambda seq, e, s, t=0.0: _e(seq, "ha.state", {"e": e, "s": s}, t, "ha")  # noqa: E731
    one = [st(0, S.E_ACTIVE, "on"), st(1, D.D_ACTIVE, "on", 5)]
    check("INV-HF-ONE-LEASE: both Active sensors on in the HA view is caught",
          [v["inv"] for v in H.check_hf_one_lease(one)] == ["INV-HF-ONE-LEASE"] and not H.check_hf_one_lease(one[:1]))
    arm = [st(0, S.E_ARM, "on"), st(1, S.E_ARM, "off", 30)]
    ok_script = [st(0, H.SCRIPT["fp"], "on"), st(1, S.E_ARM, "on", 1), st(2, S.E_ARM, "off", 30), st(3, H.SCRIPT["fp"], "off",
                                                                                                      31)]
    ok_owner = [_cmd(0, "switch.turn_on", S.E_ARM, "owner"), st(1, S.E_ARM, "on", 1), st(2, S.E_ARM, "off", 60)]
    check("INV-HF-ARM-OFF: a write enable on for 30 s with no scheduled start running is caught; on while the script runs, "
          "or armed by the owner, is not", [v["inv"] for v in H.check_hf_arm_off(arm)] == ["INV-HF-ARM-OFF"]
          and not H.check_hf_arm_off(ok_script) and not H.check_hf_arm_off(ok_owner))
    quiet = [_cmd(0, "number.set_value", D.D_SOC, "smr1", value=25.0, obl=_obl(dump_snap=True))]
    check("INV-HF-SMR1-QUIET: an SMR1 write while the Dump snapshot is held is caught; with nothing held it is not",
          [v["inv"] for v in H.check_hf_smr1_quiet(quiet)] == ["INV-HF-SMR1-QUIET"]
          and not H.check_hf_smr1_quiet([_cmd(0, "number.set_value", D.D_SOC, "smr1", value=25.0)]))
    arm_ev = _e(0, "owner.arm", {"dom": "fp", "start_local": "x", "window_end": U0 + 100})
    edge = lambda seq, act, snap, at: _e(seq, "dongle.edge", {"dom": "fp", "act": act, "snap": snap, "at": U0 + at,  # noqa
                                                              "boot": 0}, at)
    late = [arm_ev, edge(1, True, True, 10), edge(2, False, False, 140)]
    fine = [arm_ev, edge(1, True, True, 10), edge(2, False, False, 120)]
    check("INV-HF-WINDOW: an override ending 40 s after the window end is caught (overrun recorded); 20 s is not",
          [v["inv"] for v in H.check_hf_window(late)] == ["INV-HF-WINDOW"] and not H.check_hf_window(fine)
          and H.window_overruns(late)[0]["overrun_s"] == 40.0)
    start = H.START_BUTTON["fp"]
    intent = [_e(0, "owner.arm", {"dom": "fp", "start_local": "x", "window_end": U0 + 900}),
              _cmd(1, "button.press", S.E_PRESS, "schedule", fid=start), edge(2, True, True, 5),
              _e(3, "owner.press", {"e": "button.x", "fid": H.END_BUTTON["fp"], "via": "ha"}, 60), edge(4, False, False, 70),
              _cmd(5, "button.press", S.E_PRESS, "schedule", 100, fid=start), edge(6, True, True, 105)]
    check("INV-HF-OWNER-INTENT: a schedule START lease after the owner's End of that run is caught; the first lease is "
          "not", [v["seq"] for v in H.check_hf_owner_intent(intent)] == [6] and not H.check_hf_owner_intent(intent[:5]))
    fs = [_cmd(0, "number.set_value", S.E_PWR, "schedule", value=500.0, old=3000.0),
          st(1, H.SMR1_STATE["fp"], "RESTORED 2026-10-21 12:00 - restored: charge power 500 W", 600)]
    fs_ok = fs[:1] + [_cmd(1, "number.set_value", S.E_PWR, "smr1", 590, value=3000.0, old=500.0)] + [dict(fs[1], seq=2)]
    check("INV-HF-NO-FALSE-SUCCESS: RESTORED while the number still holds the schedule's 500 (the owner's was 3000) is "
          "caught; after a real restore it is not", [v["inv"] for v in H.check_hf_no_false_success(fs)]
          == ["INV-HF-NO-FALSE-SUCCESS"] and not H.check_hf_no_false_success(fs_ok))
    check("an unknown coupled invariant name is rejected", raises(H.LabHarnessError, H.check_hf_invariants, [],
                                                                  ["INV-HF-NOPE"])[0])


def section_invariant_params() -> None:
    print("[14] invariant parameters: routed to the checker they name (coupled and firmware), never dropped silently")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw.run_until(U0 + 10)
        last = [e for e in cw.log if e["kind"] in ("fw.obl", "fw.booted")][-1]
        idle = last["data"] if last["kind"] == "fw.obl" else last["data"]["obl"]
        t, up = cw.fw.t_utc, cw.fw.sim.now_ms
        due, done = copy.deepcopy(idle), copy.deepcopy(idle)
        due["fp"].update(due=True, snap=True)
        due["nvs"]["fp"] = "RESTORE_REQUIRED"
        done["fp"].update(due=False, snap=False)
        done["nvs"]["fp"] = "CLEAR"
        # hand-built, appended to this throwaway world's log: an FP restore due for 30 s with nothing to explain it, and a
        # scheduled Free Power run whose override ends 40 s after its window end
        for dt, src, kind, data in ((1, "lab", "owner.arm", {"dom": "fp", "start_local": "x", "window_end": t + 1}),
                                    (2, "lab", "dongle.edge", {"dom": "fp", "act": True, "snap": True, "at": t + 2,
                                                               "boot": 0}),
                                    (3, "fw", "fw.obl", due), (33, "fw", "fw.obl", done),
                                    (41, "lab", "dongle.edge", {"dom": "fp", "act": False, "snap": False, "at": t + 41,
                                                                "boot": 0})):
            cw.log.append(t_utc=t + dt, up_ms=up + dt * 1000 if src == "fw" else None, boot=0 if src == "fw" else None,
                          src=src, kind=kind, data=data)
        rb, both = ["INV-RESTORE-BOUND"], ["INV-HF-WINDOW", "INV-RESTORE-BOUND"]
        flat = cw.invariants(rb, bound_s=20)
        print(f"  info  INV-RESTORE-BOUND bound_s=20: {[v['detail'] for v in flat]}")
        check("a firmware invariant's parameter reaches its checker (the reported bug: it was dropped): the 30 s restore "
              "holds INV-RESTORE-BOUND at the default 60 s and at bound_s=120, and bound_s=20 flags it - flat, as "
              "params={'INV-RESTORE-BOUND': {'bound_s': 20}}, through the replay observer, same as L.check_invariants",
              not cw.invariants(rb) and not cw.invariants(rb, bound_s=120) and len(flat) == 1
              and flat[0]["inv"] == "INV-RESTORE-BOUND" and "(bound 20 s)" in flat[0]["detail"]
              and cw.invariants(rb, {"INV-RESTORE-BOUND": {"bound_s": 20}}) == flat
              and H.OBSERVERS["invariants"](cw, names=rb, bound_s=20) == flat
              and L.check_invariants(cw.log, names=rb, world=cw.fw, bound_s=20) == flat, str(flat))
        pair = lambda w_s, r_s: [v["inv"] for v in cw.invariants(both, {"INV-HF-WINDOW": {"bound_s": w_s},  # noqa: E731
                                                                        "INV-RESTORE-BOUND": {"bound_s": r_s}})]
        win, rbo = pair(30, 60), pair(50, 20)
        check("per-invariant params keep two bound_s apart in one call: {INV-HF-WINDOW: 30, INV-RESTORE-BOUND: 60} flags "
              "only the 40 s window overrun, {INV-HF-WINDOW: 50, INV-RESTORE-BOUND: 20} only the 30 s restore",
              win == ["INV-HF-WINDOW"] and rbo == ["INV-RESTORE-BOUND"], f"{win} {rbo}")
        errs = {"ambiguous flat bound_s (two selected checkers take it)": (cw.invariants, (both,), {"bound_s": 45}),
                "flat bound_s that no selected checker takes": (cw.invariants, (["INV-HF-ONE-LEASE"],), {"bound_s": 5}),
                "params for an unselected invariant": (cw.invariants, (None, {"INV-RESTORE-BOUND": {"bound_s": 5}}), {}),
                "a parameter its checker does not take": (cw.invariants, (["INV-HF-WINDOW"],
                                                                          {"INV-HF-WINDOW": {"grace_s": 1}}), {}),
                "one parameter given flat and in params": (cw.invariants, (["INV-HF-WINDOW"],
                                                                           {"INV-HF-WINDOW": {"bound_s": 1}}),
                                                           {"bound_s": 2}),
                "check_hf_invariants with an unused flat parameter": (H.check_hf_invariants,
                                                                      (cw.log, ["INV-HF-ONE-LEASE"]), {"bound_s": 5}),
                "the replay observer with an unused parameter": (H.OBSERVERS["invariants"], (cw,), {"grace": 1}),
                "an unknown invariant id": (cw.invariants, (["INV-NOPE"],), {})}
        res = {k: raises(H.LabHarnessError, fn, *a, **kw)[0] for k, (fn, a, kw) in errs.items()}
        check("invariant parameters are never dropped silently: " + "; ".join(errs) + " - each raises LabHarnessError",
              all(res.values()), str([k for k, ok in res.items() if not ok]))
    finally:
        cw.close()


def recorded(draft: dict, name: str):
    """T.record(draft); when the recording itself fails (record()'s LabTraceError family: expectations that no longer hold
    after a production behaviour change, an anchor or schema problem) the check `name` FAILS with the error text and None
    is returned, so the suite still reaches its FAILED / LAB-SUMMARY lines instead of crashing. Only those record / replay
    errors are caught; a failure is never turned into a pass."""
    try:
        return T.record(draft)
    except T.LabTraceError as exc:
        check(name, False, f"record() raised {type(exc).__name__}: {exc}")
        return None


def section_replay() -> None:
    print("[11] replay tier 'coupled': registered, record -> replay identical, an altered expectation FAILS")
    reg = T.registered("coupled")
    check("tier 'coupled' has a factory, the lifecycle actions and the observers",
          reg["factory"] and {"arm_schedule", "owner_set", "owner_press", "restart_ha", "reboot_dongle", "api_outage",
                              "set_env", "fw_action", "run_for"} <= set(reg["actions"])
          and {"last_result", "schedule_status", "smr1_state", "fw_status", "invariants", "window_overruns"}
          <= set(reg["observers"]), str(reg))
    anchor = "at: input_datetime.ecco_free_power_schedule_start"
    u = C.utc_of_local(2026, 10, 21, 11, 56)
    draft = {"schema": T.SCHEMA, "id": "HF-00-selftest", "title": "lab self-test: a 2-minute scheduled Free Power",
             "tier": "coupled", "seed": 0, "utc_start": C.iso_utc(u), "synthetic": True,
             "ownership": "synthetic site; the owner arms a schedule; nothing else touches the inverter",
             "source_anchors": [{"path": H.PACKAGES["fps1"], "text": anchor, "line_at_record": 0}],
             "source_digests": {}, "world": {"bus": {"windows": []}, "fw_world_kwargs": {"warmup_s": 120}},
             "actions": [{"at_s": 30, "do": "arm_schedule", "args": {"dom": "fp", "start_local": "2026-10-21 12:00:00",
                                                                     "minutes": 2, "power_w": 3000}},
                         {"at_s": 480, "do": "run_for", "args": {"seconds": 0}}],
             "expect": [{"observe": "last_result", "args": {"dom": "fp"}, "op": "startswith", "value": "STARTED OK"},
                        {"observe": "fw_status", "args": {"dom": "fp"}, "op": "startswith", "value": "RESTORED OK"},
                        {"observe": "invariants", "args": {}, "op": "==", "value": []}],
             "classification": "PASS", "invariant": "INV-HF-WINDOW", "grade": "VERIFIED", "confidence": "high",
             "failure_outcome": "none (harness self-test)", "smallest_safe_repair_scope": "none (harness self-test)"}
    check("the replay anchor text occurs exactly once", T.anchor_count(H.PACKAGES["fps1"], anchor)[0] == 1)
    name = "record + replay: the coupled document replays ok with the recorded trace digest"
    doc = recorded(draft, name)
    if doc is None:
        return
    res = T.replay(doc)
    check(name, res.ok and not res.drift
          and res.digest == doc["trace_digest"] and S.LOCAL is FIXED_LOCAL and not H._OPEN, str(res.failed_expectations))
    bad = dict(doc, expect=[dict(doc["expect"][0], value="FAILED")])
    res2 = T.replay(bad)
    check("negative control: the same document with an altered expectation FAILS", not res2.ok
          and res2.failed_expectations and res2.failed_expectations[0]["observe"] == "last_result")


# =============================================================================================================================
# V0.1 fail-loud corrections (brief B4 changes 3-5): projection durations by outcome, the same-script press rule, the
# static and runtime guards against options the interpreter would silently ignore
# =============================================================================================================================
def txn_expected(cw, txn: dict) -> float:
    """The projected length of a logged dongle.txn from its own counts and the world's Latency (MODEL ASSUMPTIONS
    'Projection'): non-fault ops * op_s + no_response ops * no_response_s + timeout ops * timeout_s + commits * commit_s +
    in-lock delays."""
    lat, p = cw.lat, txn.get("projection") or {"no_response": 0, "timeout": 0, "delay_ms": 0}
    return ((txn["ops"] - p["no_response"] - p["timeout"]) * lat.op_s + p["no_response"] * lat.no_response_s
            + p["timeout"] * lat.timeout_s + txn["commits"] * lat.commit_s + p["delay_ms"] / 1000)


def iss_ha_2(outcome: str, dump_dt: float) -> tuple:
    """The step-0 ISS-HA-2 recipe: the owner stages and arms Dump to Grid (via HA), then starts Free Power from the
    dashboard (manual_fp_start) while the FP START's snapshot read 230x3 gets `outcome`; a Dump START is pressed via HA
    dump_dt s after the FP press. -> (cw, LabUnsupported raised, message, FP press instant); the caller closes cw."""
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        at = U0 + 240
        for e, v in ((D.D_PWR, 1000), (D.D_SOC, 20), (D.D_DUR, 30)):
            cw.owner_set(e, v, at_utc=at - 10)
        cw.owner_set(D.D_ARM, True, at_utc=at - 9)
        cw.fw_action("modbus_policy", at_utc=at + 2, table={"read:230x3": [outcome]})
        press = manual_fp_start(cw, at)
        cw.owner_press(D.D_PRESS, at_utc=press + dump_dt)
        hit, msg = raises(H.LabUnsupported, cw.run_until, press + 60)
        return cw, hit, msg, press
    except BaseException:
        cw.close()
        raise


def section_projection_durations() -> None:
    print("[15] projection durations by outcome (ISS-HA-2): a no_response read holds START for no_response_s (2.0 s, the "
          "ESPHome hub send-wait), a timeout read for timeout_s (3.0 s, the firmware's bounded wait_until); a Dump START in "
          "the gap V0 left open fails loud; an in-lock delay: extends the window")
    lat = H.Latency()
    check("Latency defaults: no_response_s 2.0 s (ESPHome 2026.8.2 modbus/__init__.py:56 CONF_SEND_WAIT_TIME default "
          "'2000ms', modbus.cpp:62-65 expiry; the firmware sets no send_wait_time, firmware :1716-1719, :16995), "
          "timeout_s 3.0 s (the firmware's 'timeout: 3000ms' wait_until after each op, e.g. :8937), op_s 0.58 s for every "
          "other outcome", (lat.no_response_s, lat.timeout_s, lat.op_s) == (2.0, 3.0, 0.58), str(lat))
    cw, hit, msg, press = iss_ha_2("no_response", 2.0)
    try:
        txn = txn_for(cw, S.E_PRESS)
        p = txn.get("projection") or {}
        dump_gate = press + 2.0 + cw.lat.press_s[0]
        print(f"  info  FP START window [{txn['t0'] - press:.3f}, {txn['until'] - press:.3f}] s after the press (V0: "
              f"{p.get('v0_until', 0) - press:.3f}); {txn['ops']} ops, projection {p}")
        check("ISS-HA-2 (no_response): the FP START transaction (snapshot read 230x3 no_response, then 256x24 and 244x12 "
              "under its lock, firmware :8867-8868 -> :8901 / :8950 / :9032, START FAILED :9917-9922) is projected with "
              "the no_response op at no_response_s: until - t0 = its own op / commit sum, 1.42 s longer than V0's",
              p.get("no_response") == 1 and p.get("timeout") == 0 and p.get("delay_ms") == 0 and txn["ops"] == 3
              and abs(txn["until"] - txn["t0"] - round(txn_expected(cw, txn), 3)) < 1e-6
              and abs((txn["until"] - p["v0_until"]) - (cw.lat.no_response_s - cw.lat.op_s)) < 1e-6
              and cw.fw_status("fp") == "START FAILED - could not capture complete inverter snapshot", f"{txn}")
        check("ISS-HA-2 (no_response): the Dump START pressed via HA at FP press +2.0 s lands after V0's window and inside "
              "the corrected one, and RAISES LabUnsupported naming the projection gap (V0 applied it silently: an ACTIVE "
              "lease the device refuses); it never reached the firmware; the gap interleaving is counted",
              hit and "interleaving inside a projected firmware transaction is not modelled" in msg
              and "projection gap" in msg and p["v0_until"] <= dump_gate < txn["until"]
              and not [e for e in events(cw, "dongle.cmd") if e["data"]["e"] == D.D_PRESS]
              and not cw.fw.obligations()["dump"]["act"] and cw.dongle.counts["interleaving_in_projection_gap"] == 1
              and cw.dongle.counts["txn_fault_outcome"] == 1, msg[:300])
    finally:
        cw.close()
    cw, hit, msg, press = iss_ha_2("no_response", 3.4)
    try:
        txn = txn_for(cw, S.E_PRESS)
        cmd = [e for e in events(cw, "dongle.cmd") if e["data"]["e"] == D.D_PRESS]
        check("ISS-HA-2 control: the same Dump START at FP press +3.4 s (after the corrected window) is applied (one "
              "dongle command at or after the window end, the firmware Dump lease ACTIVE - VERIFIED OK)",
              not hit and len(cmd) == 1 and cmd[0]["t_utc"] >= txn["until"]
              and cw.fw_status("dump").startswith("ACTIVE - VERIFIED OK"), f"{hit} {msg[:200]} {cw.fw_status('dump')}")
    finally:
        cw.close()
    cw, hit, msg, press = iss_ha_2("timeout", 4.0)
    try:
        txn = txn_for(cw, S.E_PRESS)
        p = txn.get("projection") or {}
        check("ISS-HA-2 (timeout): a timeout read is projected at timeout_s (no callback fires, _dump_sim.py:1589-1590): "
              "until - t0 = its own sum, 2.42 s longer than V0's; a Dump START at FP press +4.0 s RAISES in the gap",
              p.get("timeout") == 1 and p.get("no_response") == 0
              and abs(txn["until"] - txn["t0"] - round(txn_expected(cw, txn), 3)) < 1e-6
              and abs((txn["until"] - p["v0_until"]) - (cw.lat.timeout_s - cw.lat.op_s)) < 1e-6
              and hit and "projection gap" in msg, f"{txn} {msg[:200]}")
    finally:
        cw.close()
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cw.run_until(U0 + 30)
        rd = lambda a, n: {ds.READ: {"modbus_id": "inverter_modbus", "address": 1, "start_address": a,  # noqa: E731
                                     "count": n}}
        locked = [{"lambda": "id(manual_write_in_progress) = true;"}, rd(244, 1), {"delay": "1500ms"}, rd(256, 6),
                  {"lambda": "id(manual_write_in_progress) = false;"}]
        n0 = len(events(cw, "dongle.txn"))
        cw.dongle.entry(fn=lambda: cw.fw.sim.run_actions(locked))
        txn = events(cw, "dongle.txn")[n0]["data"]
        p = txn.get("projection") or {}
        check("explicit delay (synthetic action list, a lambda takes the manual-write lock): a 1500ms delay: between two "
              "locked reads extends the window by 1.5 s (until - t0 = 2 * op_s + 1.5, V0 2 * op_s) and is counted",
              txn["ops"] == 2 and p.get("delay_ms") == 1500 and abs(txn["until"] - txn["t0"] - (2 * cw.lat.op_s + 1.5))
              < 1e-6 and abs(p["v0_until"] - txn["t0"] - 2 * cw.lat.op_s) < 1e-6
              and cw.dongle.counts["txn_in_lock_delay"] == 1, str(txn))
        cw.run_until(cw.dongle.busy_until + 1)
        free0, n1 = cw.dongle.counts["delay_lock_free"], len(events(cw, "dongle.txn"))
        cw.dongle.entry(fn=lambda: cw.fw.sim.run_actions([rd(244, 1), {"delay": "1500ms"}, rd(256, 6)]))
        check("...the same delay lock-free projects nothing (no transaction, zero duration: NOT MODELLED) and is counted",
              len(events(cw, "dongle.txn")) == n1 and cw.dongle.counts["delay_lock_free"] == free0 + 1)
    finally:
        cw.close()


def section_busy_press() -> None:
    print("[16] same-script press inside a window (MISS-HA-1): dropped only while the pressed script's OWN work is pending "
          "(ESPHome SingleScript); busy only through a nested script.execute -> LabUnsupported, never a silent drop")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        at = U0 + 240
        cw.fw_action("modbus_policy", at_utc=at + 2, table={"write:232": ["error"]})
        press = manual_fp_start(cw, at)
        cw.run_until(press + cw.lat.press_s[0] + 0.2)
        d = cw.dongle
        t0, until, own = d.busy_t0, d.busy_until, d.busy_own_end.get("start_free_power_override")
        print(f"  info  START window [0, {until - t0:.3f}] s after the gate; START's own work ends at "
              f"{(own or 0) - t0:.3f} s; busy scripts {sorted(d.busy_scripts)}")
        check("the activation write 232 fails, so START's else branch executes restore_free_power_snapshot as its last "
              "action (firmware :9909-9916): the window holds the nested restore, and START's own work ends inside it",
              own is not None and t0 < own < until - 1 and {"start_free_power_override", "restore_free_power_snapshot"}
              <= set(d.busy_scripts) and cw.fw_status("fp").startswith("RESTOR"), f"{own} {until} {cw.fw_status('fp')}")
        cw.run_until(t0 + 1.0)
        n0 = len(events(cw, "dongle.dropped"))
        cw.owner_press(S.E_PRESS, via="dongle")
        check("a second START press at gate +1.0 s (START's own write still pending) is DROPPED busy_same_script and "
              "counted as an own-op-pending drop (ESPHome script.h:77-87 drops it too)",
              [e["data"]["why"] for e in events(cw, "dongle.dropped")][n0:] == ["busy_same_script"]
              and d.counts["busy_drop_own_op_pending"] == 1)
        cw.run_until((own + until) / 2)
        cmds = len(events(cw, "dongle.cmd", svc="button.press"))
        hit, msg = raises(H.LabUnsupported, cw.owner_press, S.E_PRESS, via="dongle")
        check("MISS-HA-1: a START press after START's own work ended but inside the window (START on the stack only "
              "through the nested restore) RAISES LabUnsupported (the device would run START: script.execute does not "
              "block, core/automation.h:489-493, script.h:239), counted; no command reached the firmware",
              hit and "MISS-HA-1" in msg and d.counts["busy_refused_nested_only"] == 1
              and len(events(cw, "dongle.cmd", svc="button.press")) == cmds
              and len(events(cw, "dongle.dropped")) == n0 + 1, msg[:300])
    finally:
        cw.close()


def _auto(docs, pkg, aid) -> dict:
    return next(a for a in docs[pkg]["automation"] if a["id"] == aid)


GUARD_MUTATIONS = {
    # name: mutate(docs, rc) in place (copies of the parsed real packages / runtime config)
    "enabled: false on a condition": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")["conditions"][0]
    .update(enabled=False),
    "enabled: false on a trigger": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update(enabled=False),
    "state trigger for:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update({"for": "00:05:00"}),
    "state trigger from:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update({"from": "off"}),
    "state trigger not_from:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update(not_from="unavailable"),
    "state trigger not_to:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update(not_to="unavailable"),
    "state trigger attribute:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update(attribute="friendly_name"),
    "state trigger to: list": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .update(to=["on"]),
    "state trigger without to:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")["triggers"][0]
    .pop("to"),
    "state condition for:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")["conditions"][0]
    .update({"for": "00:10:00"}),
    "state condition attribute:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")["conditions"][0]
    .update(attribute="friendly_name"),
    "condition shorthand": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")["conditions"]
    .append("{{ true }}"),
    "template trigger for:": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")["triggers"][1]
    .update({"for": "00:01:00"}),
    "time trigger on a time-only helper": lambda d, rc: d["fps1"]["input_datetime"]["ecco_free_power_schedule_start"]
    .update(has_date=False),
    "homeassistant trigger other than start": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_startup_recovery")[
        "triggers"][0].update(event="shutdown"),
    "automation variables": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire").update(variables={"x": 1}),
    "service target beyond entity_id": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")[
        "actions"][1]["choose"][0]["sequence"][0]["target"].update(device_id="abc"),
    "continue_on_error on a choose": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_arm_validation")[
        "actions"][1].update(continue_on_error=True),
    "script field default": lambda d, rc: d["fps1"]["script"]["ecco_free_power_start_scheduled"]["fields"][
        "duration_minutes"].update(default=30),
    "template sensor availability": lambda d, rc: d["fps1"]["template"][0]["sensor"][0].update(availability="{{ true }}"),
    "template sensor attributes that a package reads": lambda d, rc: _auto(d, "fps1", "ecco_free_power_schedule_fire")[
        "actions"][0]["variables"].update(x="{{ state_attr('sensor.ecco_free_power_schedule_status', 'last_result') }}"),
    "input_text pattern": lambda d, rc: d["fps1"]["input_text"]["ecco_free_power_schedule_last_result"].update(pattern=".*"),
    "runtime config: an automation": lambda d, rc: rc.update(automation=[{"id": "x"}]),
    "runtime config: the limit block's state trigger stops watching an input": lambda d, rc: rc["template"][0][
        "triggers"][2]["entity_id"].remove("input_number.ecco_max_grid_charge_power"),
    "runtime config: limit sensor reads now()": lambda d, rc: next(
        it for it in rc["template"][0]["sensor"] if it["name"] == H.LIMIT_SENSOR_NAME).update(
        state="{{ now().minute }}"),
}


def section_static_guard() -> None:
    print("[17] static guard (ISS-HA-5): a package construct the interpreter would silently ignore fails loud at load")
    texts = {n: H.package_text(n) for n in H.PACKAGES}
    docs = {n: yaml.safe_load(t) for n, t in texts.items()}
    rc = yaml.safe_load(H.package_text(H.RUNTIME_CONFIG_REL))
    clean = H.ignored_options(docs, rc)
    check("positive control: the real FPS1 / DGS1 / SMR1 and ecco_runtime_config.yaml use no ignored construct (the limit "
          "sensor's trigger-based block passes: its templates read only entities its state trigger watches, "
          "ecco_runtime_config.yaml:14-23)", clean == [], str(clean))
    anchor = 'value: "REJECTED - effective grid charge power limit unavailable"'
    mutated = texts["fps1"].replace(anchor, anchor + "\n                enabled: false")
    sim_ok = True
    try:
        S.HA(S.World(0.0), [yaml.safe_load(mutated)])      # the interpreter alone accepts it (drops the key, :486)
    except Exception:  # noqa: BLE001 - recorded as a FAIL of the check below
        sim_ok = False
    hit, msg = raises(H.LabUnsupported, H.CoupledWorld, U0, bus=IDLE, package_texts={"fps1": mutated})
    check("an in-memory FPS1 copy with 'enabled: false' on an action (the interpreter alone loads it and would run the "
          "action) is REFUSED at CoupledWorld load with LabUnsupported naming it; S.LOCAL, S._truthy and the slot are "
          "restored", texts["fps1"].count(anchor) == 1 and sim_ok and hit and "enabled: False on an action" in msg
          and S.LOCAL is FIXED_LOCAL and S._truthy is H._TRUTHY_SIM and not H._OPEN, msg[:300])
    missed = []
    for name, mutate in GUARD_MUTATIONS.items():
        d, r = copy.deepcopy(docs), copy.deepcopy(rc)
        mutate(d, r)
        if not H.ignored_options(d, r):
            missed.append(name)
    check(f"each of {len(GUARD_MUTATIONS)} other ignored constructs injected into a copy of the real packages / runtime "
          "config is flagged: " + "; ".join(GUARD_MUTATIONS), not missed, str(missed))


def section_runtime_guards() -> None:
    print("[18] runtime guards (ISS-HA-5): template truthiness and input_number ranges fail loud where the interpreter and "
          "Home Assistant (REPORTED) disagree")
    cw = H.CoupledWorld(U0, bus=IDLE)
    try:
        cond = lambda tpl: cw.ha.cond([{"condition": "template", "value_template": tpl}], {})  # noqa: E731
        agree = (cond("{{ 1 > 0 }}"), cond("{{ 'abc' }}"), cond("{{ 0 }}"), cond("{{ 'True' }}"))
        refused = [tpl for tpl in ("{{ 'on' }}", "{{ 'yes' }}", "{{ 1 }}", "{{ [1] }}")
                   if raises(H.LabUnsupported, cond, tpl)[0]]
        check("template truthiness: while a world is open S._truthy is the guard; values both rules read alike pass (True, "
              "'abc' False, 0 False, 'True' True); 'on' / 'yes' / 1 / [1] (the sim: true; HA's condition rule: false) "
              "raise LabUnsupported, counted", S._truthy is not H._TRUTHY_SIM and agree == (True, False, False, True)
              and len(refused) == 4 and cw.dongle.counts["truthy_refused"] == 4, f"{agree} {refused}")
        e = H.DURATION_HELPER["fp"]
        before = cw.ha_state(e)
        hit, msg = raises(H.LabUnsupported, cw.w.call, "input_number.set_value", [e], {"value": 241})
        cw.w.call("input_number.set_value", [e], {"value": 240})
        cw.w.call("input_number.set_value", ["input_number.lab_selftest_undeclared"], {"value": 5})
        check("input_number: FPS1's duration helper is declared min 1 / max 240 (ecco_free_power_schedule.yaml:42-46); 241 "
              "RAISES LabUnsupported and is not stored, 240 is stored as the interpreter stores it ('240.0'); an "
              "input_number no loaded package declares is stored unchecked and counted",
              hit and cw.ha_state(e) == "240.0" and before != "241.0"
              and cw.ha_state("input_number.lab_selftest_undeclared") == "5.0"
              and cw.dongle.counts["input_number_refused"] == 1 and cw.dongle.counts["input_number_unranged"] == 1, msg)
    finally:
        cw.close()
    check("after close S._truthy is the interpreter's own function again (identity)", S._truthy is H._TRUTHY_SIM)


def section_extended() -> None:
    print("[12] EXTENDED: watchdog phase sweep 0..14 s, Free Power window-end overrun per bus model (report only)")
    for windows in ("measured", "polls"):
        row = []
        for ph in range(15):
            cw, smp, _p, _m = run_fp(H.BusModel(windows=windows), wd_phase_s=float(ph), until_min=62)
            try:
                ok = (cw.fw_status("fp").startswith("RESTORED OK") and cw.smr1_state("fp").startswith("RESTORED")
                      and not smp.bad)
                row.append((ph, cw.window_overruns()[0]["overrun_s"], ok))
            finally:
                cw.close()
        print(f"  info  bus {windows!r}: overrun s by watchdog phase {[(p, o) for p, o, _ok in row]}; max "
              f"{max(o for _p, o, _ok in row)} s")
        check(f"bus {windows!r}: every phase restores (RESTORED OK, SMR1 RESTORED) with HA view == firmware truth",
              all(ok for _p, _o, ok in row), str([r for r in row if not r[2]]))


# =============================================================================================================================
CW0 = H.CoupledWorld(U0, bus=IDLE)
try:
    section_mapping(CW0)
    section_unmapped(CW0)
finally:
    CW0.close()
section_fp()
section_fp_measured_bus()
section_dump()
section_projection()
section_local()
section_time_trigger()
section_lifecycle()
section_polled()
section_determinism()
section_checkers()
section_invariant_params()
section_replay()
section_projection_durations()
section_busy_press()
section_static_guard()
section_runtime_guards()
if EXTENDED:
    section_extended()
check("S.LOCAL is the sim's own fixed object and no CoupledWorld is left open at the end", S.LOCAL is FIXED_LOCAL
      and not H._OPEN)
print(f"  info  silent-divergence register, this process (_lab_ha.DIVERGENCE_COUNTS): {H.divergence_counts()}")
RUNTIME = time.perf_counter() - T0
print(f"  info  runtime {RUNTIME:.1f} s ({'extended' if EXTENDED else 'quick'} mode)")
print("")
check_phase_registry()
T.finish("test_lab_selftest_coupling", passes=PASSES, failures=FAILURES, finding=COUNTED, finding_pins=PINS,
         unsupported_points=UNSUPPORTED_POINTS, blocked=BLOCKED, phase_sensitive=PHASE_SENSITIVE, runtime_s=RUNTIME)
if FAILURES:
    sys.exit(1)
