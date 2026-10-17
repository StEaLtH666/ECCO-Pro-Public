#!/usr/bin/env python3
"""smr1 - restore the owner's manual Dump to Grid / Free Power request values after a SCHEDULED start
(home-assistant/packages/ecco_schedule_manual_restore.yaml): offline proofs.

THE PROBLEM (FCC1 A10 readiness, finding F3, 16 Oct 2026). The dongle keeps ONE set of request numbers per function, shared by the
owner's manual controls and the schedules. A scheduled start stages the schedule's values into them (DGS1 / FPS1) and nothing put
the owner's values back: after a scheduled Dump with Stop SOC 15 % the owner's manual Stop SOC (10 %) read 15 %.

The REAL packages run together under _ha_script_sim.py (the FPS1 interpreter: virtual clock, the measured Modbus poll): the Dump
to Grid schedule (DGS1), the Free Power schedule (FPS1) and smr1, against the Dump dongle model (_ha_dump_sim.py) and the Free Power
dongle model, with every service call routed to the dongle that owns the entity.

  [0] static        package shape, services (only this package's helpers, the five request numbers, notifications), no switch /
                    button / script / esphome / Modbus token, every dongle entity exists in the firmware, the device slug only
                    inside entity ids, no `initial` (restored across a restart), the blocker lists every owner of control
  [1] the problem   without smr1 a scheduled Dump leaves the manual Stop SOC and duration at the schedule's values
  [2] normal        scheduled Dump and scheduled Free Power: saved at the first write, restored once after the lease, verified,
                    RESTORED, nothing owed, no notification, never a write while anything owns control
  [3] failed start  a start that fails (no snapshot) restores at once; one that keeps a snapshot waits until End & Restore
  [4] bus busy      a start refused at the gate (bus busy) and retried, and a long transient refusal that re-stages a shorter
                    duration: the owner's original value is kept and restored
  [5] manual End    the owner's End & Restore ends the lease early: restored after it
  [6] restart       Home Assistant restarts during the lease, between the lease and the restore, during the restore, and while
                    the owner changes a value on the dongle (unobserved): the obligation survives, and the owner's change wins
  [7] ownership     a Free Power lease, a manual inverter write, a scheduled start running, a pending snapshot, an armed write
                    enable, an unreadable request number: each blocks the restore until it clears, then exactly one restore;
                    the firmware's Recovery State text (a diagnostic mirror that keeps its last text until a reboot) does not
  [8] owner change  the owner changes a value during the lease (kept, the rest restored), every value (KEPT, no write), back
                    to the schedule's value afterwards (still not overwritten); the same for Free Power
  [9] invalid/stale an invalid saved value is never written (PARTIAL / FAILED, notified); an obligation older than 24 h is STALE
                    (no write, notified) - also while something still blocks it
  [10] no loops     a write the dongle never applies: FAILED once, notified, never retried; the restore's own writes are not
                    taken for the owner's; a service error is contained
  [11] races        a scheduled start that begins while a restore runs keeps the function owed; restored after its lease -
                    also when its write lands before the restore finishes
  [12] collisions   Dump then Free Power back to back; a Free Power schedule while the Dump restore is blocked
  [13] reload       an automation reload while owed and idle restores (the template trigger alone would not fire)
  [14] PEX          the smr1 declaration
  [15] mutation     in-memory mutants of the package are each caught

Writes nothing; no Home Assistant, no network, no hardware. It proves the package's control flow against models, not a live Home
Assistant or the dongle.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "registry" / "tests"))
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402

PKG_REL = "home-assistant/packages/ecco_schedule_manual_restore.yaml"
PKG_TEXT = (ROOT / PKG_REL).read_text(encoding="utf-8")
DUMP_TEXT = (ROOT / "home-assistant/packages/ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
FP_TEXT = (ROOT / "home-assistant/packages/ecco_free_power_schedule.yaml").read_text(encoding="utf-8")
FW_TEXT = (ROOT / "firmware" / "ecco_clock_dongle_stage3_4_free_power.yaml").read_text(encoding="utf-8")

FAILURES: list[str] = []
PASSES = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASSES
    if ok:
        PASSES += 1
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f"\n        {detail}" if detail else ""))


P = S.P
FIVE = (D.D_PWR, D.D_SOC, D.D_DUR, S.E_PWR, S.E_DUR)
DUMP_ROUTE = {D.D_ARM, D.D_PRESS, D.D_DUR, D.D_PWR, D.D_SOC}
DSTATE = "input_text.ecco_sched_restore_dump_state"
FSTATE = "input_text.ecco_sched_restore_fp_state"
BLOCKER = "sensor.ecco_schedule_restore_blocker"
STATUS = "sensor.ecco_schedule_manual_restore"
D_SCRIPT = "script.ecco_dump_to_grid_start_scheduled"
F_SCRIPT = "script.ecco_free_power_start_scheduled"
D_REC = f"sensor.{P}dump_to_grid_recovery_state"
F_REC = f"sensor.{P}free_power_recovery_state"
D_ARMED = "input_boolean.ecco_dump_to_grid_schedule_armed"
F_ARMED = "input_boolean.ecco_free_power_schedule_armed"
ATTRS = {D.D_PWR: (500, 8000, 100), D.D_SOC: (10, 90, 1), D.D_DUR: (1, 240, 1), S.E_PWR: (500, 8000, 100), S.E_DUR: (1, 240, 1)}
DAY = "2026-10-11 "
ST = S.parse_local(DAY + "18:00:00")
MANUAL_DUMP = (3000, 10, 60)     # the owner's manual request (export W, Stop SOC %, duration min) - 16 Oct 2026
MANUAL_FP = (8000, 40)           # the owner's manual Free Power request (W, min)


# Every number write is tagged with the run that sent it: the restore automation (its variables carry `plan`), a scheduled
# start script (`requested_duration`), or the owner (H.owner_set). A test-only wrapper around the interpreter's action step.
SOURCE = [None]
_action = S.HA._action


def _tagged_action(self, act, v):
    if act.get("action") == "number.set_value":
        SOURCE[0] = "restore" if "plan" in v else ("schedule" if "requested_duration" in v else "other")
    return (yield from _action(self, act, v))


S.HA._action = _tagged_action


def helper(fn: str, field: str, kind: str) -> str:
    return f"input_number.ecco_sched_restore_{fn}_{field}_{kind}"


class H:
    """Home Assistant with the two schedule packages (+ smr1 unless `smr` is None) and both dongle models, from 17:50."""

    def __init__(self, smr=PKG_TEXT, dump=None, fp=None, phase=0.0, delays=(0.117,), outcome="ok", fp_outcome="ok",
                 setup=None, manual_dump=MANUAL_DUMP, manual_fp=MANUAL_FP):
        self.texts = [DUMP_TEXT, FP_TEXT] + ([smr] if smr is not None else [])
        w = self.w = S.World(S.parse_local(DAY + "17:50:00"))
        D.add_ha_filters(w)
        self.ha = S.HA(w, [yaml.safe_load(x) for x in self.texts])
        self.f = S.Dongle(w, outcome=fp_outcome)
        fph = dict(w.service_handlers)
        self.d = D.DumpDongle(w, phase=phase, handle_delays=delays, outcome=outcome)
        dh = dict(w.service_handlers)
        self.calls: list = []     # (t, entity, value, source, blocker) for every number write sent to a dongle

        def route(svc):
            def h(e, data):
                if svc == "number.set_value":
                    self.calls.append((w.t, e, int(float(data["value"])), SOURCE[0], w.state(BLOCKER)))
                    SOURCE[0] = None
                return (dh if e in DUMP_ROUTE else fph)[svc](e, data)
            return h
        for svc in ("switch.turn_on", "switch.turn_off", "button.press", "number.set_value"):
            w.service_handlers[svc] = route(svc)
        self.d.power, self.d.stop_soc, self.d.duration = manual_dump
        self.f.power, self.f.duration = manual_fp
        for e, v in zip(FIVE, (*manual_dump, *manual_fp)):
            lo, hi, step = ATTRS[e]
            w.set(e, f"{float(v)}", {"min": lo, "max": hi, "step": step})
        w.set(D_REC, "NONE")
        w.set(F_REC, "NONE")
        w.set(S.E_LIMIT, "8000")
        w.set(D_ARMED, "off")
        w.set(F_ARMED, "off")
        w.set("input_text.ecco_dump_to_grid_schedule_last_result", "")
        w.set("input_text.ecco_free_power_schedule_last_result", "")
        if dump:
            start, dur, power, soc = dump
            w.set("input_datetime.ecco_dump_to_grid_schedule_start", DAY + start)
            w.set("input_number.ecco_dump_to_grid_schedule_duration", f"{float(dur)}")
            w.set("input_number.ecco_dump_to_grid_schedule_power", f"{float(power)}")
            w.set("input_number.ecco_dump_to_grid_schedule_stop_soc", f"{float(soc)}")
        if fp:
            start, dur, power = fp
            w.set("input_datetime.ecco_free_power_schedule_start", DAY + start)
            w.set("input_number.ecco_free_power_schedule_duration", f"{float(dur)}")
            w.set("input_number.ecco_free_power_schedule_power", f"{float(power)}")
        self.ha.start()
        if setup:
            setup(self)
        w.run_until(S.parse_local(DAY + "17:51:00"))
        if dump:
            w.set(D_ARMED, "on")
        if fp:
            w.run_until(S.parse_local(DAY + "17:51:05"))
            w.set(F_ARMED, "on")

    # --- driving -----------------------------------------------------------------------------------------------------------
    def until(self, seconds_after_18: float) -> "H":
        self.w.run_until(ST + seconds_after_18)
        return self

    def at(self, seconds_after_18: float, fn) -> None:
        self.w.at(ST + seconds_after_18, fn)

    def owner_set(self, seconds_after_18: float, entity: str, value) -> None:
        """The owner changes a request number on the dashboard (a number.set_value to the dongle)."""
        def go():
            SOURCE[0] = "owner"
            self.w.call("number.set_value", [entity], {"value": value})
        self.at(seconds_after_18, go)

    def restart(self, down: float, up: float, during=None) -> None:
        """Home Assistant stops at `down` and starts again at `up` (seconds after 18:00); `during` runs while it is down."""
        def stop():
            self.ha.stop()
            if during:
                during(self)

        def start():
            self.ha = S.HA(self.w, [yaml.safe_load(x) for x in self.texts])
            self.ha.start()
        self.at(down, stop)
        self.at(up, start)

    def reload(self, at: float) -> None:
        """An automation reload: the automations are set up again from their current state and automation_reloaded fires."""
        def go():
            self.ha.stop()
            self.ha = S.HA(self.w, [yaml.safe_load(x) for x in self.texts])
            for a in self.ha.automations:
                a.setup()
            self.ha.fire_event("automation_reloaded")
        self.at(at, go)

    # --- observations ------------------------------------------------------------------------------------------------------
    def dump(self):
        return tuple(int(float(self.w.state(e))) for e in FIVE[:3])

    def fpn(self):
        return tuple(int(float(self.w.state(e))) for e in FIVE[3:])

    def ds(self):
        return self.w.state(DSTATE)

    def fs(self):
        return self.w.state(FSTATE)

    def owed(self, fn):
        fields = ("power", "stop_soc", "duration") if fn == "dump" else ("power", "duration")
        return {k: float(self.w.state(helper(fn, k, "written"))) for k in fields if float(self.w.state(helper(fn, k, "written"))) > 0}

    def restore_writes(self):
        """the number writes the restore automations sent: (seconds after 18:00, entity, value, blocker at that moment)"""
        return [(round(t - ST, 2), e, v, b) for t, e, v, s, b in self.calls if s == "restore"]

    def created(self):
        return [n for n in self.w.notification_log if n[1] == "create" and n[2].startswith("ecco_sched_restore")]

    def clean(self):
        """every restore write was sent while nothing owned control; no input_text value was refused; no sim warning"""
        bad = [x for x in self.restore_writes() if x[3] != "none"]
        unknown = [x for x in self.calls if x[3] not in ("restore", "schedule", "owner")]
        warn = [x for x in self.w.warnings if "input_text" in x] + unknown
        return not bad and not warn, f"writes while owned {bad} warnings {warn}"


def lease_dump(start="18:00:00", dur=5, power=3000, soc=15):
    return (start, dur, power, soc)


# ======================================================================================================================
print("[0] static")
PKG = yaml.safe_load(PKG_TEXT)


def firmware_entities() -> set:
    d = yaml.load(FW_TEXT, Loader=_FwLoader)
    out = set()
    for plat, domain in (("sensor", "sensor"), ("binary_sensor", "binary_sensor"), ("text_sensor", "sensor"), ("switch", "switch"),
                         ("number", "number"), ("button", "button"), ("select", "select")):
        for e in d.get(plat) or []:
            if isinstance(e, dict) and e.get("name") and str(e.get("internal")).lower() not in ("true", "yes"):
                slug = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", e["name"].lower())).strip("_")
                out.add(f"{domain}.{P}{slug}")
    return out


class _FwLoader(yaml.SafeLoader):
    pass


_FwLoader.add_multi_constructor("!", lambda loader, suffix, node: None)

check("top-level keys exactly input_number, input_text, template, automation",
      set(PKG) == {"input_number", "input_text", "template", "automation"}, str(sorted(PKG)))
check("ten number helpers (saved / written for the five request numbers) and two state texts, none with `initial` (restored)",
      len(PKG["input_number"]) == 10 and len(PKG["input_text"]) == 2
      and not any("initial" in v for v in list(PKG["input_number"].values()) + list(PKG["input_text"].values()))
      and all(v["min"] == 0 for v in PKG["input_number"].values()) and all(v["max"] == 255 for v in PKG["input_text"].values()))
autos = {a["id"]: a for a in PKG["automation"]}
check("four automations: track (queued) and restore (single, silent when busy) per function",
      sorted(autos) == ["ecco_sched_restore_dump_restore", "ecco_sched_restore_dump_track", "ecco_sched_restore_fp_restore",
                        "ecco_sched_restore_fp_track"]
      and all(autos[k]["mode"] == "queued" for k in autos if k.endswith("track"))
      and all(autos[k]["mode"] == "single" and autos[k]["max_exceeded"] == "silent" for k in autos if k.endswith("restore")))
body = "\n".join(l for l in PKG_TEXT.splitlines() if not l.lstrip().startswith("#"))
actions = set(re.findall(r"^\s*-?\s*(?:action|service):\s*([\w.]+)", body, re.M))
check("its only services: input_number.set_value, input_text.set_value, number.set_value, persistent_notification.create / dismiss",
      actions == {"input_number.set_value", "input_text.set_value", "number.set_value", "persistent_notification.create",
                  "persistent_notification.dismiss"}, str(sorted(actions)))
check("no switch / button / script call, no esphome or Modbus token, no restart, no inverter register",
      not re.search(r"switch\.turn|button\.press|action:\s*script\.|esphome\.|modbus|homeassistant\.restart|register", body, re.I))
numbers = set(re.findall(r"(?<![_a-z])number\.(?!set_value)[a-z0-9_]+", body))
check("the only dongle numbers it names are the five request numbers", numbers == set(FIVE), str(sorted(numbers)))
targets = re.findall(r"(?<![_a-z])number\.set_value[\s\S]*?entity_id:\s*\"([^\"]+)\"", body)
check("every number.set_value targets a field of its function's own list (the five request numbers only)",
      len(targets) == 2 and all(t == "{{ fields[repeat.item].number }}" for t in targets), str(targets))
FW = firmware_entities()
dongle_refs = sorted(set(re.findall(r"\b(?:sensor|binary_sensor|number|switch|button)\.ecco_clock_dongle_[a-z0-9_]+", body)))
check(f"every dongle entity it reads ({len(dongle_refs)}) exists in the firmware under that name and is not internal",
      dongle_refs and all(e in FW for e in dongle_refs), str([e for e in dongle_refs if e not in FW]))
outside = []
for line in PKG_TEXT.splitlines():
    for m in re.finditer(r"ecco_clock_dongle", line):
        if not (re.search(r"(sensor|binary_sensor|number|switch|button)\.$", line[:m.start()]) and line[m.end():m.end() + 1] == "_"):
            outside.append(line.strip()[:90])
check("the device slug appears only inside dongle entity ids (the site renderer's rule)", not outside, str(outside[:3]))
own_ids = ({f"input_number.{k}" for k in PKG["input_number"]} | {f"input_text.{k}" for k in PKG["input_text"]}
           | {BLOCKER, STATUS})
sched_ids = sorted(e for e in set(re.findall(r"\b(?:input_number|input_boolean|script)\.[a-z0-9_]+", body)) - own_ids
                   if not e.endswith(".set_value") and not e.startswith("input_number.ecco_sched_restore_"))
ok_defs = all((e.split(".")[1] in (yaml.safe_load(DUMP_TEXT).get(e.split(".")[0]) or {}))
              or (e.split(".")[1] in (yaml.safe_load(FP_TEXT).get(e.split(".")[0]) or {})) for e in sched_ids)
check(f"every schedule helper / script it reads ({len(sched_ids)}) is defined by the schedule packages", ok_defs and len(sched_ids) == 7,
      str(sched_ids))
blocker_tpl = PKG["template"][0]["sensor"][0]["state"]
OWNERS = {D.D_ACTIVE, D.D_OP, D.D_SNAP, D.D_ARM, S.E_ACTIVE, S.E_OP, S.E_SNAP, S.E_ARM, S.E_MANUAL, D_SCRIPT, F_SCRIPT}
check("the firmware's Recovery State texts are not read (diagnostic mirrors that keep their last text until a reboot)",
      D_REC not in body and F_REC not in body)
tracks_cfg = [a for a in PKG["automation"] if a["id"].endswith("_track")]
check("every track trigger fires on a change of the state only (`to: ~`), and a change needs two different real values",
      all("to" in tr and tr["to"] is None for a in tracks_cfg for tr in a["triggers"])
      and all("(old | float(-1)) != (new | float(-1))" in a["actions"][1]["value_template"] for a in tracks_cfg))
check("the blocker lists every owner of control: both leases, transactions, snapshots and write enables, the manual "
      "write and both scheduled start scripts (and the five numbers' readability)",
      all(f"'{e}'" in blocker_tpl for e in OWNERS | set(FIVE)), str([e for e in OWNERS | set(FIVE) if f"'{e}'" not in blocker_tpl]))
man = (ROOT / "deployment" / "ha-manifest.yaml").read_text(encoding="utf-8")
check("the manifest deploys the package to /config/packages/ecco_schedule_manual_restore.yaml",
      "  - source: home-assistant/packages/ecco_schedule_manual_restore.yaml\n"
      "    destination: /config/packages/ecco_schedule_manual_restore.yaml\n" in man)
check("the schedule packages are not changed by smr1 (they still stage their own values; smr1 only observes them)",
      "number.ecco_clock_dongle_dump_to_grid_stop_soc" in DUMP_TEXT and "ecco_sched_restore" not in DUMP_TEXT + FP_TEXT)

# ======================================================================================================================
print("\n[1] the problem: without smr1 the manual values stay at the schedule's")
x = H(smr=None, dump=lease_dump()).until(900)
check("scheduled Dump 3000 W / Stop SOC 15 % / 5 min with manual 3000 / 10 / 60: afterwards the manual numbers read 3000 / 15 / 5",
      x.dump() == (3000, 15, 5) and x.d.successes == 1, str(x.dump()))

# ======================================================================================================================
print("\n[2] normal completion")
x = H(dump=lease_dump()).until(60)
check("during the lease: the schedule's values staged, the owner's saved once (Stop SOC 10, duration 60; export unchanged = "
      "nothing saved), OWED", x.dump() == (3000, 15, 5) and x.ds().startswith("OWED ")
      and x.owed("dump") == {"stop_soc": 15.0, "duration": 5.0}
      and float(x.w.state(helper("dump", "stop_soc", "saved"))) == 10 and float(x.w.state(helper("dump", "duration", "saved"))) == 60,
      f"{x.dump()} {x.ds()} {x.owed('dump')}")
check("the status sensor reports the obligation and what it waits for",
      x.w.state(STATUS) == "OWED - Dump to Grid; waiting: Dump to Grid lease active", x.w.state(STATUS))
check("nothing is written while the lease runs", x.restore_writes() == [], str(x.restore_writes()))
x.until(900)
rw = x.restore_writes()
check("after the lease: restored to 3000 / 10 / 60 once (two writes, after the lease, nothing owning control), verified",
      x.dump() == (3000, 10, 60) and len(rw) == 2 and all(t > 300 for t, *_ in rw) and x.clean()[0], f"{x.dump()} {rw} {x.clean()}")
check("RESTORED recorded; nothing owed; status CLEAR; no notification",
      x.ds().startswith("RESTORED 2026-10-11 18:05 - restored: Stop SOC 10 %, duration 60 min") and x.owed("dump") == {}
      and x.w.state(STATUS) == "CLEAR" and x.created() == [], f"{x.ds()} {x.created()}")
check("the lease itself ran with the schedule's values (the restore never changed a staged value before START)",
      x.d.gate_values == (3000, 15, 5), str(x.d.gate_values))

x = H(fp=("18:00:00", 2, 500)).until(30)
check("scheduled Free Power 500 W / 2 min with manual 8000 / 40: staged, saved, OWED",
      x.fpn() == (500, 2) and x.fs().startswith("OWED ") and x.owed("fp") == {"power": 500.0, "duration": 2.0}, f"{x.fpn()} {x.fs()}")
x.until(600)
check("after the Free Power lease: restored to 8000 / 40 once, RESTORED, nothing owed, no notification",
      x.fpn() == (8000, 40) and len(x.restore_writes()) == 2 and x.fs().startswith("RESTORED") and x.owed("fp") == {}
      and x.created() == [] and x.f.successes == 1 and x.clean()[0], f"{x.fpn()} {x.fs()} {x.restore_writes()}")

x = H(dump=lease_dump(power=3000, soc=10, dur=60)).until(4000)
check("a schedule whose values equal the manual ones changes nothing: nothing saved, nothing owed, no write",
      x.dump() == MANUAL_DUMP and x.ds() in ("", "unknown") and x.restore_writes() == [], f"{x.ds()!r} {x.restore_writes()}")

# ======================================================================================================================
print("\n[3] failed start")
x = H(dump=lease_dump(), outcome="capture_failed").until(900)
check("START FAILED without a snapshot (nothing written to the inverter): restored once the start script ends",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and x.d.successes == 0 and x.clean()[0], f"{x.dump()} {x.ds()}")
x = H(dump=lease_dump(), outcome="verify_failed").until(1800)
check("START FAILED with the snapshot retained: NOT restored while the snapshot is pending (the owner must press End & Restore)",
      x.dump() == (3000, 15, 5) and x.ds().startswith("OWED") and x.restore_writes() == []
      and "Dump to Grid snapshot pending restore" in x.w.state(STATUS), f"{x.dump()} {x.w.state(STATUS)}")


def end_and_restore(h):
    h.d.flags["snapshot"] = False
    h.d._pub(D.D_SNAP, "off")


x.at(1900, lambda: end_and_restore(x))
x.until(2000)
check("after End & Restore clears the snapshot: restored once", x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED")
      and len(x.restore_writes()) == 2 and x.clean()[0], f"{x.dump()} {x.ds()}")
x = H(fp=("18:00:00", 2, 500), fp_outcome="write_failed").until(900)
check("Free Power ACTIVATION WRITE FAILED (snapshot kept): not restored while the snapshot is pending",
      x.fpn() == (500, 2) and x.fs().startswith("OWED") and x.restore_writes() == [], f"{x.fpn()} {x.fs()}")

# ======================================================================================================================
print("\n[4] bus busy and transient refusals")
found = None
for ph in [k / 10 for k in range(-30, 70)]:
    y = H(dump=lease_dump(), phase=ph).until(120)
    if y.d.presses and y.d.presses[0][1] == D.REJECT["bus"] and any(o == "PASSED" for _, o in y.d.presses):
        found = (ph, y)
        break
check("a poll phase exists where the first press is refused 'bus busy' and the retry starts", found is not None)
if found:
    ph, y = found
    y.until(900)
    check(f"bus busy then retried (phase {ph}): the owner's values saved once and restored after the lease",
          y.dump() == MANUAL_DUMP and y.ds().startswith("RESTORED") and float(y.w.state(helper("dump", "stop_soc", "saved"))) == 10
          and len(y.restore_writes()) == 2 and y.clean()[0], f"{y.dump()} {y.ds()} {y.d.presses}")


def rtc_90s(h):
    h.d.rtc.append((ST, ST + 90))


x = H(dump=lease_dump(start="18:00:00", dur=5), setup=rtc_90s).until(150)
dur_writes = [v for t, e, v, s, b in x.calls if e == D.D_DUR and s == "schedule"]
check("an RTC correction refuses the start for 90 s: the retries re-stage a SHORTER duration (window clamp)",
      len(set(dur_writes)) >= 2 and min(dur_writes) < 5, str(dur_writes))
check("...and the saved duration is still the owner's 60 (saved once per episode), the written one the latest",
      float(x.w.state(helper("dump", "duration", "saved"))) == 60 and x.owed("dump")["duration"] == min(dur_writes),
      f"{x.w.state(helper('dump', 'duration', 'saved'))} {x.owed('dump')}")
x.until(900)
check("...restored to 60 after the lease", x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and x.clean()[0], str(x.dump()))

# ======================================================================================================================
print("\n[5] manual End")
x = H(dump=lease_dump(dur=60))
x.at(120, x.d._end)
x.until(200)
check("the owner ends the lease early (End & Restore): restored right after it",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and all(t < 140 for t, *_ in x.restore_writes()) and x.clean()[0],
      f"{x.dump()} {x.ds()} {x.restore_writes()}")

# ======================================================================================================================
print("\n[6] Home Assistant restart")
x = H(dump=lease_dump(dur=10))
x.restart(120, 240)
x.until(1200)
check("a restart during the lease: the obligation survives (helpers restored), restored once after the lease",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and len(x.restore_writes()) == 2 and x.clean()[0],
      f"{x.dump()} {x.ds()} {x.restore_writes()}")
x = H(dump=lease_dump(dur=5))
x.restart(306.5, 400)      # the lease ends at ~+304.2; HA stops inside the restore's 5 s settle delay
x.until(1200)
check("a restart between the lease's end and the restore: restored at the next start (homeassistant start trigger)",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and all(t >= 400 for t, *_ in x.restore_writes()) and x.clean()[0],
      f"{x.dump()} {x.ds()} {x.restore_writes()}")


def stop_mid_restore(h):
    """Home Assistant stops right after the restore marked RESTORING and wrote the first field."""
    def watch(kind):
        if h.w.state(DSTATE).startswith("RESTORING") and not h.__dict__.get("_stopped"):
            h._stopped = True
            h.w.after(0.0001, lambda: h.ha.stop())
            h.w.after(100, lambda: (setattr(h, "ha", S.HA(h.w, [yaml.safe_load(t) for t in h.texts])), h.ha.start()))
    h.w.listeners.append(watch)


x = H(dump=lease_dump(dur=5), setup=stop_mid_restore).until(1200)
check("a restart DURING the restore (state left RESTORING): resumed at the next start, every field restored, written once each",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and x.owed("dump") == {}
      and sorted(e for _, e, _, _ in x.restore_writes()) == sorted([D.D_SOC, D.D_DUR]) and x.clean()[0],
      f"{x.dump()} {x.ds()} {x.restore_writes()}")


def owner_on_dongle_while_down(h):
    h.d.stop_soc = 20
    h.w.set(D.D_SOC, "20.0")      # changed on the dongle's own web page: Home Assistant does not see it happen


x = H(dump=lease_dump(dur=5))
x.restart(320 - 15, 400, during=owner_on_dongle_while_down)
x.until(1200)
check("the owner changes Stop SOC while Home Assistant is down: their 20 % is kept, the duration restored",
      x.dump() == (3000, 20, 60) and x.ds().startswith("RESTORED") and "kept your change: Stop SOC 20 %" in x.ds()
      and [e for _, e, _, _ in x.restore_writes()] == [D.D_DUR], f"{x.dump()} {x.ds()}")

# ======================================================================================================================
print("\n[7] ownership: the restore waits for every owner of control")


def blocked(name, setup_block, clear_at=900, expect="", begin=200):
    h = H(dump=lease_dump(dur=5))
    h.at(begin, lambda: setup_block(h, True))
    h.at(clear_at, lambda: setup_block(h, False))
    h.until(clear_at - 1)
    waited = (h.d.power, h.d.stop_soc, h.d.duration) == (3000, 15, 5) and h.restore_writes() == [] and h.ds().startswith("OWED")
    status = h.w.state(STATUS)
    h.until(clear_at + 60)
    check(f"{name}: no restore while it lasts (status '{status[:70]}'); exactly one restore after it clears",
          waited and expect in status and h.dump() == MANUAL_DUMP and len(h.restore_writes()) == 2 and h.clean()[0],
          f"waited {waited} {status} {h.dump()} {h.restore_writes()}")


blocked("a Free Power lease (the owner's own Free Power now)",
        lambda h, on: (setattr(h.f, "active", on), h.w.set(S.E_ACTIVE, "on" if on else "off")), expect="Free Power active")
blocked("a manual inverter write in progress", lambda h, on: h.w.set(S.E_MANUAL, "on" if on else "off"),
        expect="manual inverter write in progress")
blocked("the Free Power scheduled start script running", lambda h, on: h.w.set(F_SCRIPT, "on" if on else "off"),
        expect="scheduled Free Power start running")
blocked("the Free Power write enable armed", lambda h, on: h.w.set(S.E_ARM, "on" if on else "off"),
        expect="Free Power write enable armed")
blocked("a Free Power snapshot pending", lambda h, on: h.w.set(S.E_SNAP, "on" if on else "off"),
        expect="Free Power snapshot pending restore")
blocked("the dongle offline (every entity unavailable)",
        lambda h, on: [h.w.set(e, "unavailable") for e in h.d.DONGLE_ENTITIES + FIVE] if on else [
            h.w.set(e, v) for e, v in ((D.D_ARM, "off"), (D.D_ACTIVE, "off"), (D.D_OP, "off"), (D.D_SNAP, "off"),
                                       (S.E_MANUAL, "off"), (S.E_ACTIVE, "off"), (S.E_OP, "off"), (S.E_SNAP, "off"),
                                       (D.D_PWR, "3000.0"), (D.D_SOC, "15.0"), (D.D_DUR, "5.0"), (S.E_PWR, "8000.0"),
                                       (S.E_DUR, "40.0"))],
        expect="unavailable")
blocked("the five request numbers unreadable (the rest of the dongle still reporting)",
        lambda h, on: [h.w.set(e, "unavailable") for e in FIVE] if on else [
            h.w.set(e, v) for e, v in ((D.D_PWR, "3000.0"), (D.D_SOC, "15.0"), (D.D_DUR, "5.0"), (S.E_PWR, "8000.0"),
                                       (S.E_DUR, "40.0"))],
        expect="request number unreadable", begin=306)
blocked("an unknown Dump to Grid active state (fail-safe: only `off` is idle)",
        lambda h, on: h.w.set(D.D_ACTIVE, "unknown" if on else "off"), expect="Dump to Grid lease active (unknown)",
        begin=306)     # after the lease's own `off` (~+304.3), inside the restore's settle delay

x = H(dump=lease_dump(dur=5))
x.at(200, lambda: x.w.set(D_REC, "PENDING - outstanding snapshot found at boot; automatic restore expected"))
x.at(250, lambda: x.w.set(F_REC, "LOCKED_NEITHER"))
x.until(900)
check("a Recovery State text left over from an earlier event (it stays until the dongle reboots) does not block: restored",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED") and x.clean()[0], f"{x.dump()} {x.ds()}")

# ======================================================================================================================
print("\n[8] the owner's own changes win")
x = H(dump=lease_dump(dur=5))
x.owner_set(100, D.D_SOC, 20)
x.until(900)
check("the owner sets Stop SOC 20 % during the lease: that field is dropped at once (20 % kept), the duration restored",
      x.dump() == (3000, 20, 60) and x.ds().startswith("RESTORED") and "Stop SOC" not in x.ds()
      and [e for _, e, _, _ in x.restore_writes()] == [D.D_DUR] and x.created() == [], f"{x.dump()} {x.ds()}")
x = H(dump=lease_dump(dur=5))
x.owner_set(100, D.D_SOC, 25)
x.owner_set(110, D.D_DUR, 30)
x.until(900)
check("the owner changes every owed value: KEPT, nothing owed, no restore write",
      x.dump() == (3000, 25, 30) and x.ds().startswith("KEPT") and x.owed("dump") == {} and x.restore_writes() == [],
      f"{x.dump()} {x.ds()}")
x = H(dump=lease_dump(dur=5))
x.owner_set(100, D.D_SOC, 20)
x.owner_set(150, D.D_SOC, 15)
x.until(900)
check("the owner changes Stop SOC and then back to the schedule's 15 %: still their choice (15 % kept), the duration restored",
      x.dump() == (3000, 15, 60) and x.ds().startswith("RESTORED"), f"{x.dump()} {x.ds()}")

x = H(fp=("18:00:00", 2, 500))
x.owner_set(60, S.E_PWR, 1000)
x.until(900)
check("Free Power: the owner sets the charge power 1000 W during the lease: kept, the duration restored",
      x.fpn() == (1000, 40) and x.fs().startswith("RESTORED") and [e for _, e, _, _ in x.restore_writes()] == [S.E_DUR],
      f"{x.fpn()} {x.fs()}")
x = H(fp=("18:00:00", 2, 500))
x.owner_set(60, S.E_PWR, 1000)
x.owner_set(70, S.E_PWR, 500)
x.until(900)
check("Free Power: the owner changes the charge power and back to the schedule's 500 W: their 500 W kept",
      x.fpn() == (500, 40) and x.fs().startswith("RESTORED"), f"{x.fpn()} {x.fs()}")
x = H(fp=("18:00:00", 2, 500))
x.owner_set(1000, S.E_PWR, 500)
x.until(1600)
check("Free Power: after the restore the owner picks 500 W by hand: kept, nothing owed again",
      x.fpn() == (500, 40) and x.fs().startswith("RESTORED") and len(x.restore_writes()) == 2, f"{x.fpn()} {x.fs()}")

# ======================================================================================================================
print("\n[9] invalid and stale records")
x = H(dump=lease_dump(dur=5))
x.at(100, lambda: x.w.set(helper("dump", "stop_soc", "saved"), "5.0"))      # below the number's own minimum (10)
x.until(900)
check("an invalid saved Stop SOC (5, below the firmware's minimum 10) is never written: PARTIAL, the duration restored, notified",
      x.dump() == (3000, 15, 60) and x.ds().startswith("PARTIAL") and "Stop SOC (saved value 5 not valid)" in x.ds()
      and [e for _, e, _, _ in x.restore_writes()] == [D.D_DUR] and len(x.created()) == 1 and x.owed("dump") == {},
      f"{x.dump()} {x.ds()} {x.created()}")
x = H(dump=lease_dump(dur=5))
x.at(100, lambda: (x.w.set(helper("dump", "stop_soc", "saved"), "0.0"), x.w.set(helper("dump", "duration", "saved"), "61.5")))
x.until(900)
check("no valid saved value at all (0, and a fraction): FAILED, nothing written, notified, nothing owed",
      x.dump() == (3000, 15, 5) and x.ds().startswith("FAILED") and x.restore_writes() == [] and len(x.created()) == 1
      and x.owed("dump") == {}, f"{x.dump()} {x.ds()}")
x = H(dump=lease_dump(dur=5))
x.at(100, lambda: x.w.set(helper("dump", "power", "saved"), "3050.0"))   # off the 100 W step (only if it were owed)
x.until(900)
check("a saved value for a field that is not owed is ignored (only owed fields are considered)",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED"), x.ds())
x = H(dump=lease_dump(dur=5), outcome="verify_failed")
x.at(25 * 3600, lambda: end_and_restore(x))
x.until(25 * 3600 + 120)
check("an obligation older than 24 h (the snapshot pending for 25 h): STALE, nothing written, notified with the saved values",
      x.dump() == (3000, 15, 5) and x.ds().startswith("STALE") and "Stop SOC 10 %, duration 60 min" in x.ds()
      and x.restore_writes() == [] and len(x.created()) == 1 and x.owed("dump") == {}, f"{x.ds()} {x.restore_writes()}")
x = H(dump=lease_dump(dur=5))
x.at(200, lambda: x.w.set(S.E_ACTIVE, "on"))          # something that never ends (the Free Power lease flag stuck on)
x.until(23 * 3600)
blocked_23h = x.ds().startswith("OWED") and x.restore_writes() == [] and x.created() == []
x.until(26 * 3600)
check("blocked for a day: still OWED at 23 h, then STALE by the 24 h trigger WHILE still blocked: notified, nothing written, "
      "nothing owed", blocked_23h and x.ds().startswith("STALE") and x.restore_writes() == [] and len(x.created()) == 1
      and x.owed("dump") == {} and x.dump() == (3000, 15, 5), f"{blocked_23h} {x.ds()} {x.created()}")
x = H(dump=lease_dump(dur=5))
x.at(100, lambda: x.w.set(DSTATE, "OWED garbage - not a time"))
x.until(900)
check("an unreadable obligation time is treated as stale (never restored blindly)", x.ds().startswith("STALE")
      and x.restore_writes() == [], x.ds())

# ======================================================================================================================
print("\n[10] no loops, one attempt")
x = H(dump=lease_dump(dur=5))
x.at(300, lambda: setattr(x.d, "drop_numbers", True))     # the dongle stops applying number writes (accepted, never published)
x.until(6 * 3600)
check("a restore write the dongle never applies: verified false after 15 s, FAILED once, notified, never retried (6 h)",
      x.ds().startswith("FAILED") and "NOT restored, set by hand: Stop SOC (reads 15.0, should be 10 %)" in x.ds()
      and len(x.restore_writes()) == 2 and len(x.created()) == 1 and x.owed("dump") == {}, f"{x.ds()} {x.restore_writes()}")
runs = [a for a in x.ha.automations if a.id == "ecco_sched_restore_dump_restore"][0].fired
check("the restore automation ran once with an obligation (any later run stops at its first condition: no write)",
      len(x.restore_writes()) == 2, str(runs))
x = H(dump=lease_dump(dur=5))
x.at(300, lambda: x.w.fail_services.__setitem__("number.set_value", 1))   # the first restore write raises (API error)
x.until(3600)
check("a service error on one restore write is contained: the other field restored, PARTIAL, notified once",
      x.ds().startswith("PARTIAL") and len(x.created()) == 1 and x.owed("dump") == {} and x.dump()[1:] in ((15, 60), (10, 5)),
      f"{x.ds()} {x.dump()}")
x = H(dump=lease_dump(dur=5)).until(900)
tracks = [a for a in x.ha.automations if a.id == "ecco_sched_restore_dump_track"][0].fired
check("the restore's own writes are not taken for the owner's (the track sees them, changes nothing): RESTORED, not KEPT",
      x.ds().startswith("RESTORED") and len(tracks) == 4, str(tracks))

# ======================================================================================================================
print("\n[11] a scheduled start that begins during a restore")


def race_at(offset):
    """the dongle publishes slowly (3 s); a second scheduled Dump (3000 W / 15 % / 5 min) starts `offset` s after RESTORING"""
    h = H(dump=lease_dump(dur=5))

    def watch(kind):
        if h.w.state(DSTATE).startswith("RESTORING") and not h.__dict__.get("_raced"):
            h._raced = True

            def go():
                h.w.set("input_datetime.ecco_dump_to_grid_schedule_start", DAY + "19:00:00")
                h.w.set(D_ARMED, "on")
                h.ha.start_script("ecco_dump_to_grid_start_scheduled",
                                  {"duration_minutes": 5, "power_w": 3000, "stop_soc": 15, "window_end_ts": h.w.t + 300})
            h.w.after(offset, go)
    h.w.listeners.append(watch)
    h.at(250, lambda: setattr(h.d, "publish", 3.0))
    h.until(3600)
    return h


for off in (0.01, 1.0, 2.5, 4.0, 8.0):
    h = race_at(off)
    check(f"second scheduled start {off} s into the restore: two leases, and in the end the manual values 3000 / 10 / 60, "
          f"RESTORED, nothing owed, no notification", h.d.successes == 2 and h.dump() == MANUAL_DUMP and h.ds().startswith("RESTORED")
          and h.owed("dump") == {} and h.created() == [] and h.clean()[0], f"{h.d.successes} {h.dump()} {h.ds()} {h.created()}")



def race_before_end(text=PKG_TEXT):
    """White box: the restore's own writes are lost (the dongle accepts and never applies them), and 1 s into the restore a
    scheduled start of the same function runs and stages 15 % / 5 min again - its write lands BEFORE the restore finishes."""
    h = H(smr=text, dump=lease_dump(dur=5))

    def watch(kind):
        if h.w.state(DSTATE).startswith("RESTORING") and not h.__dict__.get("_r"):
            h._r = True
            h.d.drop_numbers = True

            def start():
                h.d.drop_numbers = False
                h.w.set(D_SCRIPT, "on")
                for e, v in ((D.D_SOC, 15), (D.D_DUR, 5)):
                    SOURCE[0] = "schedule"
                    h.w.call("number.set_value", [e], {"value": v})
            h.w.after(1.0, start)
            h.w.after(25.0, lambda: h.w.set(D_SCRIPT, "off"))
    h.w.listeners.append(watch)
    h.until(1800)
    return h


h = race_before_end()
check("a same-function start whose write lands before the restore finishes: kept OWED (not FAILED), then restored once that "
      "start is over; one notification-free outcome", h.dump() == MANUAL_DUMP and h.ds().startswith("RESTORED")
      and h.owed("dump") == {} and h.created() == [], f"{h.dump()} {h.ds()} {h.created()}")

# ======================================================================================================================
print("\n[12] collisions between the two functions")
x = H(dump=lease_dump(dur=5), fp=("18:20:00", 2, 500)).until(3600)
check("Dump 18:00-18:05 then Free Power 18:20-18:22: both restored (3000 / 10 / 60 and 8000 / 40), both RESTORED",
      x.dump() == MANUAL_DUMP and x.fpn() == MANUAL_FP and x.ds().startswith("RESTORED") and x.fs().startswith("RESTORED")
      and x.d.successes == 1 and x.f.successes == 1 and x.created() == [] and x.clean()[0], f"{x.dump()} {x.fpn()} {x.ds()} {x.fs()}")
x = H(dump=lease_dump(dur=5), fp=("18:20:00", 2, 500), outcome="verify_failed").until(1800)
check("the Dump restore blocked (snapshot pending) while a Free Power schedule runs: Free Power owed too, neither restored",
      x.dump() == (3000, 15, 5) and x.fpn() == (500, 2) and x.ds().startswith("OWED") and x.fs().startswith("OWED")
      and x.restore_writes() == [], f"{x.dump()} {x.fpn()} {x.ds()} {x.fs()}")
x.at(1900, lambda: end_and_restore(x))
x.until(2100)
check("...End & Restore clears it: both functions restored", x.dump() == MANUAL_DUMP and x.fpn() == MANUAL_FP
      and x.ds().startswith("RESTORED") and x.fs().startswith("RESTORED") and x.clean()[0], f"{x.dump()} {x.fpn()}")

# ======================================================================================================================
print("\n[13] automation reload")


def hold_snapshot(h):
    h.d.flags["snapshot"] = True


x = H(dump=lease_dump(dur=5), outcome="verify_failed")
x.at(1000, lambda: (x.ha.stop(), end_and_restore(x)))     # automations stop; the snapshot clears while they are being reloaded
x.reload(1010)
x.until(1200)
check("the obligation becomes restorable while the automations reload: the reload event restores it",
      x.dump() == MANUAL_DUMP and x.ds().startswith("RESTORED"), f"{x.dump()} {x.ds()}")


def without_reload_trigger(text):
    return text.replace("      - trigger: event\n        event_type: automation_reloaded\n        id: reloaded\n", "")


y = H(smr=without_reload_trigger(PKG_TEXT), dump=lease_dump(dur=5), outcome="verify_failed")
y.at(1000, lambda: (y.ha.stop(), end_and_restore(y)))
y.reload(1010)
y.until(1200)
check("...without the reload trigger it would stay owed (why the trigger exists)", y.ds().startswith("OWED"), y.ds())

# ======================================================================================================================
print("\n[14] the post-export declaration (PEX entry smr1)")
import _pex  # noqa: E402
import _scope_chain as chain  # noqa: E402
import _smr1_scope as M  # noqa: E402

E = chain.CHAIN.entry("smr1")
ids = [e.id for e in chain.POST_EXPORT_ENTRIES]
# Position and parent are pinned, not "last": a later entry (hd1) is appended after smr1.
check("smr1 is appended right after fcc1 (the nineteenth post-export entry)", "smr1" in ids and ids.index("smr1") == 18
      and chain.CHAIN.prev_id("smr1") == "fcc1", str(ids[-3:]))
check("smr1 chain-pins exactly the manifest, edits no frozen file, adds exactly its files (all present)",
      set(E.reverts) == {M.MANIFEST_REL} and not E.frozen_reverts and E.added_files == M.ADDED_FILES
      and all((ROOT / p).is_file() for p in M.ADDED_FILES), str(sorted(E.added_files)))
cur = _pex.read(M.MANIFEST_REL)   # PEX: today's manifest
before = _pex.as_of(M.MANIFEST_REL, "fcc1", cur)   # PEX: the manifest as of fcc1 (smr1 undone exactly, sha256-checked)
check("undone exactly, the manifest is its fcc1 state, and applying smr1's pair to it gives today's manifest; the checkpoint is "
      "its sha256", M.pre_smr1_manifest(cur) == before and M.add_smr1_manifest(before) == cur
      and E.checkpoints == {chain.HA_MANIFEST: M.sha(cur)})
check("smr1's fingerprint is sealed and linked to fcc1's", E.fingerprint == _pex.fingerprint(E)   # PEX: hash link
      and _pex.record(E)["parent"] == chain.CHAIN.entry("fcc1").fingerprint)

# ======================================================================================================================
print("\n[15] mutation: each named mutant is caught")


def outcome_normal(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5)).until(900)
        return h.dump() == MANUAL_DUMP and h.ds().startswith("RESTORED") and len(h.restore_writes()) == 2 and h.clean()[0]
    except Exception:   # noqa: BLE001 - a mutant that breaks the interpreter is caught
        return False


def outcome_owner_kept(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.owner_set(100, D.D_SOC, 20)
        h.until(900)
        return h.dump() == (3000, 20, 60)
    except Exception:   # noqa: BLE001
        return False


def outcome_owner_back_to_schedule_value(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.owner_set(100, D.D_SOC, 20)
        h.owner_set(150, D.D_SOC, 15)
        h.until(900)
        return h.dump() == (3000, 15, 60)
    except Exception:   # noqa: BLE001
        return False


def outcome_owner_after_restore(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.owner_set(1000, D.D_SOC, 15)       # after the restore: the owner picks the schedule's value by hand
        h.until(1600)
        return h.dump() == (3000, 15, 60) and len(h.restore_writes()) == 2 and h.ds().startswith("RESTORED")
    except Exception:   # noqa: BLE001
        return False


def outcome_waits_for_fp(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(200, lambda: h.w.set(S.E_ACTIVE, "on"))
        h.until(899)
        return h.restore_writes() == []
    except Exception:   # noqa: BLE001
        return False


def outcome_retry_keeps_original(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5), setup=rtc_90s).until(900)
        return h.dump() == MANUAL_DUMP
    except Exception:   # noqa: BLE001
        return False


def outcome_invalid_not_written(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(100, lambda: h.w.set(helper("dump", "stop_soc", "saved"), "5.0"))
        h.until(900)
        return h.dump()[1] == 15 and all(e != D.D_SOC for _, e, _, _ in h.restore_writes())
    except Exception:   # noqa: BLE001
        return False


def outcome_stale(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5), outcome="verify_failed")
        h.at(25 * 3600, lambda: end_and_restore(h))
        h.until(25 * 3600 + 120)
        return h.restore_writes() == [] and h.ds().startswith("STALE")
    except Exception:   # noqa: BLE001
        return False


def outcome_fail_once(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(300, lambda: setattr(h.d, "drop_numbers", True))
        h.until(4 * 3600)
        return (h.ds().startswith("FAILED") and len(h.restore_writes()) == 2 and len(h.created()) == 1
                and h.owed("dump") == {})
    except Exception:   # noqa: BLE001
        return False


def outcome_recheck_after_delay(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(306, lambda: h.w.set(S.E_ACTIVE, "on"))      # inside the restore's 5 s settle delay
        h.until(899)
        return h.restore_writes() == []
    except Exception:   # noqa: BLE001
        return False


def outcome_stale_while_blocked(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(200, lambda: h.w.set(S.E_ACTIVE, "on"))
        h.until(25 * 3600)
        return h.ds().startswith("STALE") and len(h.created()) == 1
    except Exception:   # noqa: BLE001
        return False


def outcome_unreadable_waits(text):
    try:
        h = H(smr=text, dump=lease_dump(dur=5))
        h.at(306, lambda: [h.w.set(e, "unavailable") for e in FIVE[:3]])
        h.at(400, lambda: [h.w.set(e, v) for e, v in ((D.D_PWR, "3000.0"), (D.D_SOC, "15.0"), (D.D_DUR, "5.0"))])
        h.until(900)
        return h.dump() == MANUAL_DUMP and h.ds().startswith("RESTORED")
    except Exception:   # noqa: BLE001
        return False


def outcome_race_before_end(text):
    try:
        h = race_before_end(text)
        return h.dump() == MANUAL_DUMP and h.ds().startswith("RESTORED") and h.created() == []
    except Exception:   # noqa: BLE001
        return False


def outcome_fp_owner_after_restore(text):
    try:
        h = H(smr=text, fp=("18:00:00", 2, 500))
        h.owner_set(1000, S.E_PWR, 500)
        h.until(1600)
        return h.fpn() == (500, 40) and len(h.restore_writes()) == 2
    except Exception:   # noqa: BLE001
        return False


def outcome_fp_owner_back(text):
    try:
        h = H(smr=text, fp=("18:00:00", 2, 500))
        h.owner_set(60, S.E_PWR, 1000)
        h.owner_set(70, S.E_PWR, 500)
        h.until(900)
        return h.fpn() == (500, 40)
    except Exception:   # noqa: BLE001
        return False


def mut(find, put, count=1):
    assert PKG_TEXT.count(find) >= count, find
    return PKG_TEXT.replace(find, put, count)


MUTANTS = [
    ("the schedule-script condition removed from the Dump track (every change is taken for the schedule's)",
     mut("              - condition: state\n                entity_id: script.ecco_dump_to_grid_start_scheduled\n"
         "                state: \"on\"\n", ""), outcome_owner_after_restore),
    ("the once-per-episode guard removed (a retry overwrites the saved value with the schedule's)",
     mut("value_template: \"{{ (states(written) | float(0)) <= 0 }}\"", "value_template: \"{{ true }}\""),
     outcome_retry_keeps_original),
    ("every blocker check removed (trigger, condition, per-field)",
     PKG_TEXT.replace("is_state('sensor.ecco_schedule_restore_blocker', 'none')", "true"), outcome_waits_for_fp),
    ("the Free Power lease dropped from the blocker",
     mut("               ('binary_sensor.ecco_clock_dongle_free_power_active', 'Free Power active'),\n", ""), outcome_waits_for_fp),
    ("the 'still the schedule's value' test removed (c == w): the owner's change overwritten",
     mut("{% elif c == w %}{% set ns.k = ns.k + ['restore'] %}", "{% else %}{% set ns.k = ns.k + ['restore'] %}"),
     outcome_owner_kept),
    ("the owner-change branch removed from the Dump track",
     mut("                value_template: \"{{ state_now.startswith('OWED') and (states(written) | float(0)) > 0 }}\"",
         "                value_template: \"{{ false }}\""), outcome_owner_back_to_schedule_value),
    ("the validity test removed (an invalid saved value written)",
     mut("{% elif not valid %}{% set ns.k = ns.k + ['invalid'] %}", ""), outcome_invalid_not_written),
    ("the 24 h staleness test removed", PKG_TEXT.replace("> 86400", "> 864000"), outcome_stale),
    ("the time-driven 24 h trigger removed (a blocked obligation never times out)",
     PKG_TEXT.replace("(t <= 0 or (as_timestamp(now()) - t) > 86400)", "false"), outcome_stale_while_blocked),
    ("the written values not cleared after a failure (the function stays owed and is retried)",
     mut("or (not is_state('script.ecco_dump_to_grid_start_scheduled', 'on') and w == wplan[repeat.index - 1])) }}", ") }}"),
     outcome_fail_once),
    ("the clearing ignores a scheduled start running now (its new write cleared)",
     mut("(not is_state('script.ecco_dump_to_grid_start_scheduled', 'on') and w == wplan[repeat.index - 1])",
         "(w == wplan[repeat.index - 1] or true)"), outcome_race_before_end),
    ("the final state ignores what is still written (a start during the restore lost)",
     mut("if owed else result }}", "if false else result }}"), outcome_race_before_end),
    ("the 'request number unreadable' clause removed from the blocker",
     mut("{% set ns.b = ns.b + ['request number unreadable'] %}", ""), outcome_unreadable_waits),
    ("the schedule-script condition removed from the Free Power track",
     mut("              - condition: state\n                entity_id: script.ecco_free_power_start_scheduled\n"
         "                state: \"on\"\n", ""), outcome_fp_owner_after_restore),
    ("the owner-change branch removed from the Free Power track",
     PKG_TEXT.replace("                value_template: \"{{ state_now.startswith('OWED') and (states(written) | float(0)) > 0 }}\"",
                      "                value_template: \"{{ false }}\"").replace(
         "                value_template: \"{{ false }}\"",
         "                value_template: \"{{ state_now.startswith('OWED') and (states(written) | float(0)) > 0 }}\"", 1),
     outcome_fp_owner_back),
    ("the restore never writes (the number.set_value step disabled)",
     mut("                    - action: number.set_value\n                      continue_on_error: true\n",
         "                    - action: input_text.set_value\n                      continue_on_error: true\n"), outcome_normal),
    ("the re-check after the settle delay dropped (a lease that begins inside the delay)",
     PKG_TEXT.replace("and (stale or is_state('sensor.ecco_schedule_restore_blocker', 'none')) }}", "}}").replace(
         "{{ plan[repeat.item] == 'restore' and is_state('sensor.ecco_schedule_restore_blocker', 'none')",
         "{{ plan[repeat.item] == 'restore'"), outcome_recheck_after_delay),
]
for name, text, outcome in MUTANTS:
    check(f"mutant caught: {name}", text != PKG_TEXT and not outcome(text))
check("the unmutated package passes every mutation probe",
      all(f(PKG_TEXT) for f in (outcome_normal, outcome_owner_kept, outcome_owner_back_to_schedule_value,
                                outcome_owner_after_restore, outcome_waits_for_fp, outcome_retry_keeps_original,
                                outcome_invalid_not_written, outcome_stale, outcome_fail_once, outcome_recheck_after_delay,
                                outcome_stale_while_blocked, outcome_unreadable_waits, outcome_race_before_end,
                                outcome_fp_owner_after_restore, outcome_fp_owner_back)))

print("")
print(f"{PASSES} passed, {len(FAILURES)} failed")
if FAILURES:
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("ALL PASS")
