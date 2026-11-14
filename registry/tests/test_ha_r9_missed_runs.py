#!/usr/bin/env python3
"""Offline test for R9 (no automatic start of a missed scheduled run after a Home Assistant restart), both schedule packages:
home-assistant/packages/ecco_dump_to_grid_schedule.yaml (Export to Grid) and ecco_free_power_schedule.yaml (Charge Battery).

Requirement (owner, 12 Nov 2026; docs/dev/grid-loss-interlock-spec.md section 5 R9 and 6.4): a missed scheduled session must not
restart after a Home Assistant restart, on either start path (the startup recovery and the schedule watchdog); future occurrences
are kept; the on-time start is unchanged.

HOW IT PROVES IT. The REAL package YAML runs under the repository's Home Assistant script / automation interpreter
(home-assistant/tests/_ha_script_sim.py, a fail-loud model of the subset the packages use, with a virtual clock) against the
dongle start-gate models (_ha_dump_sim.py, _ha_script_sim.Dongle). Every Jinja condition is the package's own text, rendered by
that interpreter; nothing is re-implemented here. What is a MODEL, not Home Assistant: the interpreter itself, the dongle, and
the restore of helper states across a restart (a restarted entity keeps its state; `restore_last_changed` chooses whether its
last_changed is kept or reset to the boot, and every restored entity's last_updated is the boot, as the guard assumes - the
live behaviour of that last assumption is not proven here). Nothing in this test touches Home Assistant, a dongle or a network.

  [0] static     helper, capture automation, guard definitions identical in both automations, status text, notifications
  [1] cases      per package: downtime start (window open / expired), future start kept and started on time, start between the
                 Home Assistant start and the recovery's evaluation, restart during a running session, restart between an arm
                 and its press, capture unknown (never written / stale / late), last_changed restored and not, either
                 automation first, the watchdog's start of a start that fell while Home Assistant ran (unchanged)
  [2] interlock  a start refused with a `REJECTED - GRID INTERLOCK` status is terminal (one press, no retry)
  [3] mutation   removing a guard, or trusting a stale capture, makes the cases fail
  [4] every start call across home-assistant/, the cards and the tools sits behind the R9 guard or the on-time start trigger
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "home-assistant" / "tests"))
sys.path.insert(0, str(HERE))
import _ha_dump_sim as D  # noqa: E402
import _ha_script_sim as S  # noqa: E402

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


ST = S.parse_local("2026-10-11 18:00:00")          # the scheduled start (a minute boundary: the time trigger fires on it)
T0 = ST - 3600                                      # first Home Assistant boot
MISSED_TEXT = "MISSED - not started after a Home Assistant restart"
UNKNOWN_PREFIX = "MISSED - not started: the Home Assistant start time was unknown"


def failed_closed(s: str) -> bool:
    """The record for an unknown / untrusted Home Assistant start: MISSED, and it does not claim the start fell before the start."""
    return s.startswith(UNKNOWN_PREFIX) and "failed closed" in s and "after a Home Assistant restart" not in s
DURATION = 120                                      # window 18:00-20:00

KINDS = {
    "dump": dict(rel="home-assistant/packages/ecco_dump_to_grid_schedule.yaml", p="ecco_dump_to_grid",
                 script="ecco_dump_to_grid_start_scheduled"),
    "free": dict(rel="home-assistant/packages/ecco_free_power_schedule.yaml", p="ecco_free_power",
                 script="ecco_free_power_start_scheduled"),
}
for k, v in KINDS.items():
    v["text"] = (ROOT / v["rel"]).read_text(encoding="utf-8")


class Run:
    """One schedule on a virtual clock: Home Assistant (booted at T0) + the real package + the dongle model, armed for ST."""

    def __init__(self, kind: str, start_ts: float = ST, mutate=None, lose=(), text: str | None = None,
                 duration: int = DURATION):
        self.kind = kind
        k = KINDS[kind]
        self.p = k["p"]
        self.text = text if text is not None else k["text"]
        self.mutate = mutate
        self.lose = set(lose)
        self.w = S.World(T0)
        if kind == "dump":
            D.add_ha_filters(self.w)
            self.d = D.DumpDongle(self.w)
            self.e_arm, self.e_status, self.e_active = D.D_ARM, D.D_STATUS, D.D_ACTIVE
        else:
            self.d = S.Dongle(self.w)
            self.e_arm, self.e_status, self.e_active = S.E_ARM, S.E_STATUS, S.E_ACTIVE
        self._wrap_interlock()
        w, p = self.w, self.p
        self.armed = f"input_boolean.{p}_schedule_armed"
        self.last_e = f"input_text.{p}_schedule_last_result"
        self.status_e = f"sensor.{p}_schedule_status"
        self.cap_e = f"input_datetime.{p}_ha_start"
        self.start_e = f"input_datetime.{p}_schedule_start"
        w.set(self.start_e, S.local_str(start_ts))
        w.set(f"input_number.{p}_schedule_duration", f"{float(duration)}")
        w.set(f"input_number.{p}_schedule_power", "3000.0")
        if kind == "dump":
            w.set(f"input_number.{p}_schedule_stop_soc", "40.0")
        w.set("sensor.ecco_config_maximum_grid_charge_power", "8000")
        w.set(self.armed, "off")
        w.set(self.last_e, "")
        other = "ecco_free_power" if kind == "dump" else "ecco_dump_to_grid"
        w.set(f"input_boolean.{other}_schedule_armed", "off")
        self.start_ts = start_ts
        self.end_ts = start_ts + duration * 60
        self._boot()
        w.run_until(T0 + 60)
        w.set(self.armed, "on")                       # armed at T0 + 1 min: its last_changed is earlier than the start

    # -- Home Assistant lifecycle ------------------------------------------------------------------------------------
    def _pkg(self):
        pkg = yaml.safe_load(self.text)
        if self.mutate:
            self.mutate(pkg)
        return pkg

    def _boot(self):
        self.ha = S.HA(self.w, self._pkg())
        self.ha.start()
        for a in self.ha.automations:
            a.disabled_triggers |= self.lose

    def restart(self, down_from: float, back_at: float, restore_last_changed: bool = True, pre_boot=None):
        """Home Assistant stops at down_from and starts again at back_at; the dongle keeps running. Every restored entity's
        last_updated is the boot; its last_changed is kept (restore_last_changed) or reset to the boot."""
        self.w.run_until(down_from)
        self.ha.stop()
        self.w.run_until(back_at)
        for e in list(self.w.states):
            self.w.updated_at[e] = back_at
            if not restore_last_changed:
                self.w.changed_at[e] = back_at
        if pre_boot:
            pre_boot(self)
        self._boot()
        return self

    def until(self, ts: float):
        self.w.run_until(ts)
        return self

    # -- dongle: a GRID INTERLOCK refusal (the manual lock of the grid-loss design), modelled at the gate ----------------
    def _wrap_interlock(self):
        d = self.d
        d.flags["interlock"] = False
        orig = d._gate

        def gate():
            if d.flags["interlock"] and not d.op:
                d.arm = False
                text = "REJECTED - GRID INTERLOCK - manual lock after grid loss"
                d.presses.append((d.w.t, text))
                d._pub(self.e_status, text)
                d._pub(self.e_arm, "off", d.publish + 0.0003)
                return
            orig()
        d._gate = gate

    # -- observations ------------------------------------------------------------------------------------------------
    def last(self):
        return self.w.state(self.last_e)

    def is_armed(self):
        return self.w.state(self.armed) == "on"

    def status(self):
        return self.w.state(self.status_e)

    def presses(self):
        return list(self.d.press_log)

    def missed_alerts(self):
        return [n for n in self.w.notification_log
                if n[1] == "create" and n[2] == f"{self.p}_schedule" and "missed" in n[3]]

    def started(self):
        return self.d.successes


def staged_ok(x: Run) -> bool:
    """The dongle ran with the schedule's staged values."""
    if x.kind == "dump":
        return x.d.gate_values == (3000, 40, DURATION) or x.d.gate_values[:2] == (3000, 40)
    return x.d.power == 3000


def drop_capture(pkg):
    pkg["automation"] = [a for a in pkg["automation"] if not a["id"].endswith("_ha_start_capture")]


def late_capture(seconds):
    def mut(pkg):
        for a in pkg["automation"]:
            if a["id"].endswith("_ha_start_capture"):
                a["actions"].insert(0, {"delay": f"00:{seconds // 60:02d}:{seconds % 60:02d}"})
    return mut


# ======================================================================================================================
print("[0] static")
# ======================================================================================================================
for kind, k in KINDS.items():
    pkg = yaml.safe_load(k["text"])
    p = k["p"]
    nm = f"{kind}:"
    check(f"{nm} the captured-start helper is a date+time input_datetime defined in the same package, with no `initial`",
          pkg["input_datetime"].get(f"{p}_ha_start", {}).get("has_date") is True
          and pkg["input_datetime"][f"{p}_ha_start"].get("has_time") is True
          and "initial" not in pkg["input_datetime"][f"{p}_ha_start"])
    cap = next((a for a in pkg["automation"] if a["id"] == f"{p}_ha_start_capture"), None)
    check(f"{nm} one capture automation: trigger homeassistant start; waits (bounded, continuing) for the dongle's NTP synced and "
          "a Home Assistant clock within 120 s of the dongle's NTP time; only then writes that helper, once, from now()",
          cap is not None and cap["triggers"] == [{"trigger": "homeassistant", "event": "start"}]
          and len(cap["actions"]) == 2 and "wait_template" in cap["actions"][0]
          and "binary_sensor.ecco_clock_dongle_ntp_synced" in cap["actions"][0]["wait_template"]
          and "sensor.ecco_clock_dongle_ntp_time" in cap["actions"][0]["wait_template"]
          and "<= 120" in cap["actions"][0]["wait_template"]
          and cap["actions"][0]["timeout"] == "00:10:00" and cap["actions"][0]["continue_on_timeout"] is True
          and cap["actions"][1]["if"] == [{"condition": "template", "value_template": "{{ wait.completed }}"}]
          and len(cap["actions"][1]["then"]) == 1
          and cap["actions"][1]["then"][0]["action"] == "input_datetime.set_datetime"
          and cap["actions"][1]["then"][0]["target"] == {"entity_id": f"input_datetime.{p}_ha_start"}
          and cap["actions"][1]["then"][0]["data"] == {"timestamp": "{{ as_timestamp(now()) | int }}"}, str(cap))
    fire = next(a for a in pkg["automation"] if a["id"] == f"{p}_schedule_fire")
    rec = next(a for a in pkg["automation"] if a["id"] == f"{p}_schedule_startup_recovery")

    def var_blocks(a):
        for act in a["actions"]:
            if "variables" in act and "missed_run" in act["variables"]:
                return act["variables"]
        return None
    vf, vr = var_blocks(fire), var_blocks(rec)
    check(f"{nm} the fire automation and the startup recovery define the R9 guard identically",
          vf is not None and vr is not None
          and all(vf[x] == vr[x] for x in ("ha_start_ts", "ha_start_known", "missed_run")), "")
    known, missed = vf["ha_start_known"], vf["missed_run"]
    check(f"{nm} the guard compares the start time with the captured start (<=: the same second is missed) and never reads last_changed",
          "last_changed" not in known and "last_changed" not in missed and "<= (ha_start_ts | float(0))" in missed
          and "not ha_start_known" in missed, f"{known!r} {missed!r}")
    check(f"{nm} the guard fails closed: unknown / unavailable / epoch / future / stale-vs-last_updated capture is not known",
          all(s in known for s in ("'unknown'", "'unavailable'", "cs > 1000000000", "cs <= as_timestamp(now())",
                                   "last_updated", "abs <= 10")), known)
    check(f"{nm} the capture helper is written by no other automation or script (no other set_datetime in the package)",
          not any("set_datetime" in yaml.dump(x) for x in pkg["automation"] + list(pkg["script"].values())
                  if x.get("id") != f"{p}_ha_start_capture"))
    check(f"{nm} the missed-run status text is in the package and the status sensor treats MISSED as terminal FAILED",
          k["text"].count("{{ '" + MISSED_TEXT + "' if ha_start_known else") == 2 and "r.startswith('MISSED')" in k["text"]
          and k["text"].count("FULL Home Assistant restart") == 1)
    check(f"{nm} the fire automation's `choose` has no `default:` (a watchdog tick can never fall through to a start call)",
          all("default" not in a for a in fire["actions"] if "choose" in a))
    rec_choose = next(a for a in rec["actions"] if "choose" in a)
    leave = [b for b in rec_choose["choose"] if b["sequence"] == [] and any(
        c.get("value_template") == "{{ not missed_run and now_ts < end_ts }}" for c in b["conditions"])]
    check(f"{nm} the recovery's leave-alone branch applies only while the window is open (an expired not-missed start reaches the default)",
          len(leave) == 1 and "default" in rec_choose)
    check(f"{nm} the transient-refusal list is a whitelist that does not include a GRID INTERLOCK refusal",
          "GRID INTERLOCK" not in k["text"] and "REJECTED - Modbus bus busy" in k["text"])

# ======================================================================================================================
print("\n[1] cases (every case for both packages)")
# ======================================================================================================================
for kind in KINDS:
    nm = f"{kind}:"
    p = KINDS[kind]["p"]

    # --- sanity: the capture runs at every boot and the guard reads it as known
    x = Run(kind).until(T0 + 120)
    check(f"{nm} the capture writes the boot time at the first start and it is read as known",
          x.w.state(x.cap_e) == S.local_str(T0), x.w.state(x.cap_e))

    # --- a start time during the downtime, window still open
    x = Run(kind).restart(ST - 120, ST + 600).until(ST + 7300)
    check(f"{nm} start during the downtime, window open: NOT started (no press, no run), MISSED recorded, alerted, only it disarmed",
          x.presses() == [] and x.started() == 0 and x.last() == MISSED_TEXT and not x.is_armed()
          and len(x.missed_alerts()) == 1 and x.status() == "FAILED"
          and not [r for r in x.ha.runs if r[1] == KINDS[kind]["script"]],
          f"{x.presses()} {x.started()} {x.last()!r} {x.is_armed()} {x.missed_alerts()}")

    # --- same, window expired (unchanged behaviour: MISSED recorded, nothing started)
    x = Run(kind).restart(ST - 120, ST + DURATION * 60 + 100).until(ST + DURATION * 60 + 400)
    check(f"{nm} start during the downtime, window expired: MISSED (expired), nothing started, disarmed",
          x.presses() == [] and x.last().startswith("MISSED") and not x.is_armed() and x.status() == "FAILED",
          f"{x.last()!r}")

    # --- a start after the boot is kept and starts on time with its staged values
    x = Run(kind).restart(ST - 3000, ST - 1800)
    x.until(ST - 1500)
    check(f"{nm} start after the boot: kept armed, the recovery only reports it (ARMED AFTER RESTART), staged values untouched",
          x.is_armed() and x.last().startswith("ARMED AFTER RESTART") and x.presses() == []
          and x.w.state(f"input_number.{p}_schedule_power") == "3000.0")
    x.until(ST + 600)
    check(f"{nm} ...and it starts on time through the normal trigger with its staged values, then disarms",
          x.started() == 1 and abs(x.d.started_at - ST) < 60 and staged_ok(x) and not x.is_armed()
          and x.missed_alerts() == [], f"{x.d.started_at and x.d.started_at - ST} {x.last()!r}")

    # --- a start between the Home Assistant start and the recovery's evaluation: not a missed run
    x = Run(kind).restart(ST - 300, ST - 10).until(ST + 90)
    check(f"{nm} start 10 s after the Home Assistant start (before the recovery's evaluation): starts on time, not missed",
          x.started() == 1 and abs(x.d.started_at - ST) < 60 and x.missed_alerts() == [] and not x.last().startswith("MISSED"),
          f"{x.last()!r} {x.started()}")
    x = Run(kind, lose=("start",)).restart(ST - 300, ST - 10).until(ST + 100)
    check(f"{nm} ...with the on-time trigger lost: the recovery (evaluating at +20 s after the start) neither starts nor disarms it",
          x.presses() == [] and x.is_armed() and not x.last().startswith("MISSED") and x.missed_alerts() == [],
          f"{x.presses()} {x.is_armed()} {x.last()!r}")
    x.until(ST + 400)
    check(f"{nm} ...and the watchdog (a start that fell while Home Assistant ran) then starts it as today",
          x.started() == 1 and any("start was missed" in n[3] for n in x.w.notification_log if n[1] == "create"),
          f"{x.started()} {x.w.notification_log}")

    # --- a restart during a running session (recorded and disarmed as today; nothing started by Home Assistant)
    x = Run(kind, lose=("start", "watchdog"))
    if kind == "dump":
        x.d.manual_start(ST + 5, duration=60, power=3000, stop_soc=40)
    else:
        x.d.manual_start(ST + 5, duration=60)
    x.restart(ST + 300, ST + 600).until(ST + 900)
    check(f"{nm} restart during a running session: recorded STARTED OK and disarmed as today, no start by Home Assistant",
          x.last().startswith("STARTED OK - running (Home Assistant restarted during the session)") and not x.is_armed()
          and not [r for r in x.ha.runs if r[1] == KINDS[kind]["script"]] and x.missed_alerts() == [],
          f"{x.last()!r} {x.ha.runs}")

    # --- a restart between an arm and its press: the write enable is turned off; the kept future occurrence is untouched
    x = Run(kind)
    x.w.run_until(ST - 3000)
    x.d._set_arm(True)
    x.restart(ST - 2990, ST - 1800).until(ST - 1500)
    check(f"{nm} restart between an arm and its press: write enable turned off, the future occurrence stays armed, nothing pressed",
          x.w.state(x.e_arm) == "off" and x.is_armed() and x.presses() == [], f"{x.w.state(x.e_arm)} {x.is_armed()}")

    # --- the capture never written / stale / late: fail closed
    x = Run(kind, mutate=drop_capture).restart(ST - 120, ST + 600).until(ST + 7300)
    check(f"{nm} capture never written (automation absent): window open -> not started, MISSED with the reason, disarmed",
          x.presses() == [] and failed_closed(x.last()) and not x.is_armed()
          and len(x.missed_alerts()) == 1, f"{x.presses()} {x.last()!r}")
    x = Run(kind)
    x.mutate = drop_capture                     # the capture existed at the first boot, is gone at the second: a STALE value
    x.restart(ST - 120, ST + 600).until(ST + 7300)
    check(f"{nm} capture stale (written at the previous boot, not at this one): not started, MISSED, failed closed",
          x.presses() == [] and x.started() == 0 and failed_closed(x.last())
          and not x.is_armed(), f"{x.presses()} {x.last()!r}")
    x = Run(kind, mutate=late_capture(400)).restart(ST - 120, ST + 600).until(ST + 7300)
    check(f"{nm} capture late (after the recovery's evaluation): the recovery fails closed, nothing started",
          x.presses() == [] and x.started() == 0 and failed_closed(x.last()) and not x.is_armed(),
          f"{x.presses()} {x.last()!r}")
    x = Run(kind, mutate=drop_capture).restart(ST - 3000, ST - 1800).until(ST - 1500)
    check(f"{nm} capture unknown but the start is later than the boot (proved by now < start): kept and reported, not touched",
          x.is_armed() and x.last().startswith("ARMED AFTER RESTART") and x.presses() == [])
    x.until(ST + 600)
    check(f"{nm} ...and it still starts on time through the on-time trigger",
          x.started() == 1 and abs(x.d.started_at - ST) < 60, f"{x.started()}")
    # a captured start in the future is not credible: fail closed (a lost on-time trigger would otherwise be started by the watchdog)
    x2 = Run(kind, lose=("start",))
    x2.w.set(x2.cap_e, "2099-01-01 00:00:00")
    x2.until(ST + 400)
    check(f"{nm} a future captured start is incredible: the watchdog does not start the lost on-time start",
          x2.presses() == [] and failed_closed(x2.last()), f"{x2.last()!r}")

    # --- last_changed restored / not restored, either automation first (the watchdog's own edge needs the boot at ST+60)
    for restored in (True, False):
        for order in ("recovery first", "watchdog first"):
            x = Run(kind)
            hold = None
            if order == "watchdog first":                # the recovery waits (<= 3 min) for the dongle's active sensor: the watchdog edge
                x.w.at(ST + 60 + 190, lambda x=x: x.w.set(x.e_active, "off"))   # (+180 s) comes first, with the capture already known
                hold = lambda x_: x_.w.set(x_.e_active, "unavailable")  # noqa: E731
            x.restart(ST - 120 if order == "recovery first" else ST - 30,
                      ST + 600 if order == "recovery first" else ST + 60, restore_last_changed=restored, pre_boot=hold)
            x.until(ST + DURATION * 60 + 600)
            # WHICH automation recorded it: the watchdog fires only when armed.last_changed (kept) is earlier than the start. With
            # last_changed NOT restored it is the boot time, later than the start, so the watchdog never fires: the (delayed)
            # recovery writes the record, and that variant is labelled as such.
            wd = any(tid == "watchdog" for a in x.ha.automations if a.id.endswith("_schedule_fire") for _, tid in a.fired)
            expect_wd = order == "watchdog first" and restored
            who = "watchdog first" if expect_wd else ("recovery first" if order == "recovery first" else
                                                      "recovery, delayed (the watchdog cannot fire: last_changed reset to the boot)")
            label = f"{nm} start in the downtime, last_changed {'restored' if restored else 'not restored'}, {who}"
            check(f"{label}: the watchdog {'did' if expect_wd else 'did not'} fire",
                  wd == expect_wd, f"watchdog fired={wd}")
            check(f"{label}: never started, MISSED recorded once, disarmed",
                  x.presses() == [] and x.started() == 0 and x.last() == MISSED_TEXT and not x.is_armed()
                  and len(x.missed_alerts()) == 1 and not [r for r in x.ha.runs if r[1] == KINDS[kind]["script"]],
                  f"{x.presses()} {x.last()!r} alerts={len(x.missed_alerts())} runs={x.ha.runs}")

    # --- R9 review fixes ---------------------------------------------------------------------------------------------
    # a start in the SAME second as the Home Assistant start is a missed run (<=)
    x = Run(kind, lose=("start",)).restart(ST - 120, ST).until(ST + 400)
    check(f"{nm} start in the same second as the Home Assistant start: missed (not started, MISSED recorded, disarmed)",
          x.presses() == [] and x.started() == 0 and x.last() == MISSED_TEXT and not x.is_armed(), f"{x.presses()} {x.last()!r}")

    # a host with no RTC boots with a clock that is BEHIND: nothing is captured until the clock agrees with the dongle's NTP time
    def behind(x_, off=-1200.0):
        x_.w.clock_offset = off
    x = Run(kind, lose=("start",)).restart(ST - 120, ST + 600, pre_boot=behind).until(ST + 1100)
    stale_cap = x.w.state(x.cap_e)
    check(f"{nm} clock behind at the boot: nothing captured (the helper keeps the old value), nothing started (the recovery, on the "
          "wrong clock, still sees the start as future and only reports it)",
          stale_cap == S.local_str(T0) and x.presses() == [] and x.is_armed(), f"{stale_cap} {x.presses()} {x.last()!r}")
    x.w.clock_offset = 0.0                               # NTP steps the clock forward
    x.until(ST + 1500)
    check(f"{nm} ...then the clock is stepped (inside the capture's 10 minutes): the capture is written with the corrected time, the "
          "watchdog's flip finds the start missed, and nothing was ever started",
          x.w.state(x.cap_e) >= S.local_str(ST + 1100) and x.presses() == [] and x.started() == 0
          and x.last().startswith("MISSED") and not x.is_armed(), f"{x.w.state(x.cap_e)} {x.presses()} {x.last()!r}")
    # the same, with the watchdog's own edge produced by the step (armed, not yet disarmed: the recovery's wait is long)
    x = Run(kind, lose=("start",))
    x.d.set_offline(ST + 590, ST + 2100)                 # the dongle is away too: the capture waits, the recovery times out
    x.restart(ST - 120, ST + 600, pre_boot=behind)
    x.until(ST + 2300)
    x.w.clock_offset = 0.0
    x.until(ST + 7300)
    check(f"{nm} clock behind and stepped while the dongle is away: no start by either path, MISSED recorded",
          x.presses() == [] and x.started() == 0 and x.last().startswith("MISSED") and not x.is_armed(), f"{x.presses()} {x.last()!r}")

    # the dongle's NTP not synced / its clock disagreeing: no capture (fail closed); eventually trustworthy: captured, watchdog rescue works
    def ntp_off(x_):
        x_.w.set(S.E_NTP, "off")
    x = Run(kind, lose=("start",)).restart(ST - 120, ST + 600, pre_boot=ntp_off).until(ST + 1500)
    check(f"{nm} dongle NTP not synced: the capture waits its 10 minutes then leaves the helper alone; the recovery fails closed",
          x.w.state(x.cap_e) == S.local_str(T0) and x.presses() == [] and failed_closed(x.last()), f"{x.w.state(x.cap_e)} {x.last()!r}")

    def clock_off(x_):
        x_.w.ntp_off = True
        x_.w.set("sensor.ecco_clock_dongle_ntp_time", S.local_str(x_.w.t + 7200))
    x = Run(kind, lose=("start",)).restart(ST - 120, ST + 600, pre_boot=clock_off).until(ST + 1500)
    check(f"{nm} dongle clock disagreeing with Home Assistant's by 2 h: no capture, fail closed",
          x.w.state(x.cap_e) == S.local_str(T0) and x.presses() == [] and failed_closed(x.last()), f"{x.w.state(x.cap_e)} {x.last()!r}")
    x = Run(kind, lose=("start",)).restart(ST - 3000, ST - 1800, pre_boot=ntp_off)
    x.w.at(ST - 1800 + 300, lambda: x.w.set(S.E_NTP, "on"))
    x.until(ST + 400)
    check(f"{nm} NTP trustworthy after 5 minutes (inside the 10): captured then (not at the boot), and the watchdog rescue of a lost "
          "on-time start works as before",
          x.w.state(x.cap_e) == S.local_str(ST - 1800 + 300) and x.started() == 1,
          f"{x.w.state(x.cap_e)} {x.started()}")

    # DST: a capture made in the fall-back hour parses one hour early (the local string is ambiguous): last_updated disagrees -> unknown
    x = Run(kind, lose=("start",))
    x.until(ST - 600)
    x.w.set(x.cap_e, S.local_str(ST - 600 - 3600))
    x.until(ST + 400)
    check(f"{nm} DST: a capture that parses one hour early is unknown, never trusted: the lost on-time start is not started, MISSED",
          x.presses() == [] and failed_closed(x.last()), f"{x.presses()} {x.last()!r}")

    # a start late in the 20 s - 3 min 20 s window: the start is 180 s after the boot; the recovery evaluates after it (the dongle's
    # active sensor is unavailable for 190 s): not a missed run, left to the normal triggers
    def hold_active(x_):
        x_.w.set(x_.e_active, "unavailable")
    x = Run(kind, lose=("start",))
    x.w.at(ST - 180 + 190, lambda: x.w.set(x.e_active, "off"))
    x.restart(ST - 300, ST - 180, pre_boot=hold_active).until(ST + 100)
    check(f"{nm} start 180 s after the Home Assistant start, recovery evaluating at about +200 s: not missed (not started, not disarmed)",
          x.presses() == [] and x.is_armed() and x.missed_alerts() == [] and not x.last().startswith("MISSED"), f"{x.last()!r} {x.is_armed()}")
    x.until(ST + 500)
    check(f"{nm} ...and the watchdog (start later than the capture) then starts it", x.started() == 1, f"{x.started()}")

    # a not-missed start whose window has already expired reaches the existing 'window already expired' disarm
    x = Run(kind, lose=("start", "watchdog"), duration=1)
    x.w.at(ST - 60 + 190, lambda: x.w.set(x.e_active, "off"))
    x.restart(ST - 200, ST - 60, pre_boot=hold_active).until(ST + 600)
    check(f"{nm} 1-minute window, on-time start lost, recovery evaluating after the window: the expired default disarms it (MISSED expired)",
          x.presses() == [] and x.last().startswith("MISSED - scheduled") and "expired" in x.last() and not x.is_armed(),
          f"{x.last()!r} {x.is_armed()}")

    # a package reload without a restart (the package is installed as a reload): the capture never ran -> unknown -> fail closed
    pre = {"dump": "pre_r9_dump_package", "free": "pre_r9_free_package"}[kind]
    import _r9_scope as _r9s  # noqa: E402
    old_text = getattr(_r9s, pre)(KINDS[kind]["text"])
    x = Run(kind, lose=("start",), text=old_text)
    x.until(ST - 300)
    x.text = KINDS[kind]["text"]
    x.ha.stop()
    x.ha = S.HA(x.w, x._pkg())                          # the reload: automations re-created, NO homeassistant start event
    for a in x.ha.automations:
        a.setup()
        a.disabled_triggers |= x.lose
    x.until(ST + 400)
    check(f"{nm} package reload without a restart: the captured start stays unknown and the watchdog does NOT rescue a lost on-time "
          "start (fail closed; the deploy note requires a full restart)",
          x.w.state(x.cap_e) in ("unknown", "") and x.presses() == [] and failed_closed(x.last()), f"{x.w.state(x.cap_e)!r} {x.last()!r}")

    # --- unchanged: a start that fell while Home Assistant ran (its on-time trigger lost) is started by the watchdog
    x = Run(kind, lose=("start",)).until(ST + 400)
    check(f"{nm} unchanged: the watchdog still starts a start that fell while Home Assistant was running, with its alert",
          x.started() == 1 and any("start was missed" in n[3] for n in x.w.notification_log if n[1] == "create")
          and x.last().startswith("STARTED OK") and not x.is_armed(), f"{x.started()} {x.last()!r}")

    # --- unchanged: the on-time start
    x = Run(kind).until(ST + 400)
    check(f"{nm} unchanged: the on-time start", x.started() == 1 and abs(x.d.started_at - ST) < 60 and staged_ok(x))

    # --- an owner's re-arm of a new schedule during the miss processing is not disarmed (only the missed one is)
    # --- a stale capture on the WATCHDOG path (the capture did not run at this boot; the old value predates the start)
    x = Run(kind, lose=("start",), mutate=drop_capture).restart(ST - 120, ST + 60).until(ST + DURATION * 60 + 600)
    check(f"{nm} stale capture, watchdog path: the stale value is not trusted, nothing is started, MISSED recorded (failed closed)",
          x.presses() == [] and x.started() == 0 and failed_closed(x.last()) and not x.is_armed(),
          f"{x.presses()} {x.last()!r}")

    # --- only the missed occurrence is disarmed: the disarm and the record sit under the fired_for guard
    x = Run(kind).restart(ST - 120, ST + 20)
    x.w.set(x.start_e, S.local_str(ST + 7200 + 3600))          # the owner moves the start while the recovery waits (re-armed)
    x.w.set(x.armed, "off"); x.w.set(x.armed, "on")
    x.until(ST + 600)
    check(f"{nm} a missed run never disarms or rewrites a different, later occurrence armed meanwhile",
          x.is_armed() and x.presses() == [] and not x.last().startswith("MISSED"), f"{x.is_armed()} {x.last()!r}")
    check(f"{nm} the disarm and the MISSED record sit under the fired_for guard (four guarded sites in the package)",
          KINDS[kind]["text"].count("== fired_for") == 4)

# ======================================================================================================================
print("\n[2] a GRID INTERLOCK refusal is terminal, not retried")
# ======================================================================================================================
for kind in KINDS:
    x = Run(kind)
    x.d.flags["interlock"] = True
    x.until(ST + 700)
    check(f"{kind}: a start refused with 'REJECTED - GRID INTERLOCK' is pressed once, recorded FAILED TO START, never retried",
          len(x.presses()) == 1 and x.started() == 0 and x.last().startswith("FAILED TO START - REJECTED - GRID INTERLOCK")
          and "retrying" not in x.last(), f"{x.presses()} {x.last()!r}")

# ======================================================================================================================
print("\n[3] mutation: the cases are not vacuous")
# ======================================================================================================================


def no_watchdog_guard(pkg):
    fire = next(a for a in pkg["automation"] if a["id"].endswith("_schedule_fire"))
    for act in fire["actions"]:
        for br in act.get("choose", []):
            conds = br["conditions"]
            if any(c.get("id") == "watchdog" for c in conds if c.get("condition") == "trigger"):
                for c in conds:
                    if c.get("value_template") == "{{ not missed_run }}":
                        c["value_template"] = "{{ true }}"
                    if c.get("value_template") == "{{ missed_run }}":
                        c["value_template"] = "{{ false }}"


def trust_stale(pkg):
    for a in pkg["automation"]:
        for act in a["actions"]:
            v = act.get("variables") or {}
            if "ha_start_known" in v:
                v["ha_start_known"] = "{{ true }}"


def no_recovery_guard(pkg):
    rec = next(a for a in pkg["automation"] if a["id"].endswith("_startup_recovery"))
    for act in rec["actions"]:
        if "choose" in act:
            for br in act["choose"]:
                for c in br["conditions"]:
                    if c.get("value_template") == "{{ now_ts < end_ts }}" and len(br["conditions"]) == 1:
                        br["sequence"] = [{"action": "script." + KINDS_BY_P[rec["id"][:-len("_schedule_startup_recovery")]],
                                           "data": {"duration_minutes": "{{ duration_min }}", "power_w": "{{ power_w }}",
                                                    **({"stop_soc": "{{ stop_soc }}"} if "dump" in rec["id"] else {}),
                                                    "window_end_ts": "{{ end_ts }}"}}]


KINDS_BY_P = {v["p"]: v["script"] for v in KINDS.values()}
for kind in KINDS:
    x = Run(kind, mutate=no_recovery_guard).restart(ST - 120, ST + 600).until(ST + 900)
    check(f"{kind}: mutant - the recovery's start of a missed run put back: the case fails (it starts)", x.started() == 1)
    x = Run(kind, mutate=no_watchdog_guard)
    x.d.set_offline(ST + 40, ST + 400)
    x.restart(ST + 60, ST + 70).until(ST + 900)
    check(f"{kind}: mutant - the watchdog guard removed: the watchdog-first case fails (it starts)", x.started() == 1,
          f"{x.started()} {x.last()!r}")
    x = Run(kind, lose=("start",), mutate=lambda pkg: (drop_capture(pkg), trust_stale(pkg)))
    x.restart(ST - 120, ST + 60).until(ST + 900)
    check(f"{kind}: mutant - a stale capture trusted: the stale-capture watchdog case fails (the watchdog starts it)",
          x.started() == 1, f"{x.started()} {x.last()!r}")

# ======================================================================================================================
print("\n[4] every call of the two start scripts is behind the R9 guard or the on-time start trigger")
# ======================================================================================================================
SCRIPTS = {f"script.{v['script']}" for v in KINDS.values()}


def walk_calls(node, path, out):
    """Yield (call node, guard conditions along the path) for every action that starts one of the scripts."""
    if isinstance(node, list):
        for i in node:
            walk_calls(i, path, out)
        return
    if not isinstance(node, dict):
        return
    for key in ("action", "service", "perform-action"):
        v = node.get(key)
        if isinstance(v, str) and (v in SCRIPTS or (v in ("script.turn_on", "script.turn_off") and any(
                s in yaml.dump(node.get("target", {})) + yaml.dump(node.get("data", {})) for s in SCRIPTS))):
            out.append((node, list(path)))
    if "choose" in node:
        for br in node["choose"]:
            walk_calls(br.get("sequence", []), path + [("conds", br.get("conditions", []))], out)
        walk_calls(node.get("default", []), path + [("default", None)], out)
        return
    if "if" in node:
        walk_calls(node.get("then", []), path + [("conds", node["if"])], out)
        walk_calls(node.get("else", []), path + [("else", None)], out)
        return
    for v in node.values():
        walk_calls(v, path, out)


def has_guard(path, kind) -> str | None:
    """'start' when an enclosing branch requires the on-time `start` trigger id; 'r9' when it requires `not missed_run`."""
    for tag, conds in path:
        if tag != "conds" or not isinstance(conds, list):
            continue
        for c in conds:
            if c.get("condition") == "trigger" and c.get("id") == "start":
                return "start"
        for c in conds:
            if c.get("condition") == "template" and c.get("value_template") == "{{ not missed_run }}":
                return "r9"
    return None


calls_found = 0
ha_dir = ROOT / "home-assistant"
for f in sorted(ha_dir.rglob("*.yaml")):
    txt = f.read_text(encoding="utf-8")
    if not any(s in txt for s in SCRIPTS):
        continue
    doc = yaml.safe_load(txt)
    found: list = []
    walk_calls(doc, [], found)
    for node, path in found:
        calls_found += 1
        rel = f.relative_to(ROOT).as_posix()
        fn = node.get("action") or node.get("service")
        if fn in ("script.turn_off",):
            check(f"{rel}: a stop of a start script ({fn}) is not a start", True)
            continue
        owner = rel.endswith("ecco_dump_to_grid_schedule.yaml") or rel.endswith("ecco_free_power_schedule.yaml")
        g = has_guard(path, None)
        # the call must be in the fire automation (a start or a guarded watchdog) - never in the startup recovery
        in_recovery = False
        for a in (doc.get("automation") or []):
            blob: list = []
            walk_calls(a.get("actions", []), [], blob)
            if any(n is node for n, _ in blob) and a["id"].endswith("_startup_recovery"):
                in_recovery = True
        check(f"{rel}: call of {fn} is behind {'the on-time start trigger' if g == 'start' else 'the R9 guard' if g == 'r9' else 'NOTHING'}"
              f" and not in the startup recovery", owner and g in ("start", "r9") and not in_recovery, f"{path}")
check("exactly three calls per package (the watchdog's guarded start, the on-time start, nothing in the recovery) were found",
      calls_found == 4, f"calls found: {calls_found}")

# any other file that could start either script (cards, integration, tools): none may mention the script entity ids
other_hits = []
for base, globs in ((ROOT / "frontend", ("*/src/**/*.ts", "*/src/**/*.js")), (ROOT / "custom_components", ("**/*.py",)),
                    (ROOT / "tools", ("**/*.py",)), (ROOT / "intelligence", ("**/*.py",))):
    if not base.exists():
        continue
    for g in globs:
        for f in base.glob(g):
            if "node_modules" in f.parts or "tests" in f.parts or "test" in f.parts:
                continue
            try:
                t = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(s in t for s in SCRIPTS) or any(v["script"] in t for v in KINDS.values()):
                other_hits.append(f.relative_to(ROOT).as_posix())
check("no card, integration or tool source calls either start script (the cards arm the helper; only the packages start)",
      other_hits == [], str(other_hits))

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print("  -", n)
    sys.exit(1)
print(f"ALL PASS ({PASSES} checks)")
