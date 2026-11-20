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
  [5] clock changes (owner decision of 20 Nov 2026, proposals P-A and P-B of the clock-change examination): under the real London zone the
                 arm validation of BOTH packages refuses a start label that is a skipped, repeated or unreadable local time (every minute of
                 28 Mar 2027, 31 Oct 2027, 25 Oct 2026 and two ordinary days against a zoneinfo oracle), and the Export to Grid TOU overlap walk
                 follows the real instants (a window that crosses a clock change checks the slots it really covers); mutants
  [6] Free Power: the startup recovery never writes STARTED OK over a result this schedule did not verify (owner decision of 20 Nov 2026); mutants
"""

from __future__ import annotations

import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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


UNCONFIRMED_START = "UNCONFIRMED - Dump to Grid is active after a Home Assistant restart"


def session_restart(kind: str, last: str | None = None, mutate=None):
    """A session that the dongle's own Start button started at ST + 5 (the schedule's start triggers lost), Home Assistant restarts at ST + 300 and is back at ST + 600; `last` is the last result the
    schedule held when it went down (default: the ARMED text the arm validation wrote)."""
    x = Run(kind, lose=("start", "watchdog"), mutate=mutate)
    if kind == "dump":
        x.d.manual_start(ST + 5, duration=60, power=3000, stop_soc=40)
    else:
        x.d.manual_start(ST + 5, duration=60)
    if last is not None:
        x.until(x.w.t + 10)                    # the arm validation (it fires on the next event) has written its ARMED text; the text under test replaces it
        x.w.set(x.last_e, last)
    x.restart(ST + 300, ST + 600).until(ST + 900)
    return x


def dump_unverified_ok(x) -> bool:
    """The Dump to Grid recovery's answer for a session that this schedule did not verify (owner decision r15): the UNCONFIRMED text, never a success, disarmed, nothing started."""
    t = x.last()
    return (t.startswith(UNCONFIRMED_START) and "did not confirm that it started it" in t and "STARTED" not in t and len(t) <= 255 and not x.is_armed()
            and not [r for r in x.ha.runs if r[1] == KINDS["dump"]["script"]] and x.missed_alerts() == [] and len(x.presses()) == 1 and x.d.successes == 1)


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
            # PLAN (stage 3, merged with r9): the scheduled start reads the plan's two sensors and fails closed without them. Here no override
            # runs and the effective reserve (20) is below this suite's Stop SOC (40), so nothing is raised; the plan cases are proved by
            # test_ecco_plan_enforcement.py, and the two layers together by test_ecco_r9_stage3_composition.py.
            w.set("sensor.ecco_plan_export_hold", "clear")
            w.set("sensor.ecco_plan_effective_reserve", "20")
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


# Owner decision of 20 Nov 2026 (the Free Power result-integrity fix): the recovery of the Charge Battery (Free Power) package never writes
# STARTED OK over a result this schedule did not verify. Helpers for the checks in [1] and [6].
UNCONFIRMED_FREE = "UNCONFIRMED - Free Power is active after a Home Assistant restart"
FREE_SCRIPT = KINDS["free"]["script"]


def free_restart(last: str | None = None, mutate=None, text: str | None = None, manual: bool = True) -> "Run":
    """A Free Power session that the dongle's own Start button started at ST + 5 (the schedule's start triggers lost), Home Assistant restarts at
    ST + 300 and is back at ST + 600; `last` replaces the last result the schedule held when it went down (default: the ARMED text)."""
    x = Run("free", lose=("start", "watchdog"), mutate=mutate, text=text)
    if manual:
        x.d.manual_start(ST + 5, duration=60)
    if last is not None:
        x.until(x.w.t + 10)                    # the arm validation has written its ARMED text; the text under test replaces it
        x.w.set(x.last_e, last)
    x.restart(ST + 300, ST + 600).until(ST + 900)
    return x


def free_unverified_ok(x: "Run") -> bool:
    """The recovery's answer for a session this schedule did not verify: the UNCONFIRMED text, never a success, disarmed, nothing started."""
    t = x.last()
    return (t.startswith(UNCONFIRMED_FREE) and "did not confirm that it started it" in t and "STARTED" not in t and len(t) <= 255 and not x.is_armed()
            and not [r for r in x.ha.runs if r[1] == FREE_SCRIPT] and x.missed_alerts() == [] and len(x.presses()) == 1 and x.d.successes == 1)


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

    # --- a restart during a running session (recorded and disarmed; nothing started by Home Assistant)
    x = session_restart(kind)
    if kind == "dump":
        # Owner decision r15 (19 Nov 2026), known limitation 20, its last path: this session was started by the dongle's own Start button (a manual start), not verified as THIS schedule's own start, so the recovery must not
        # record it as STARTED OK. It was pinned the other way here ("recorded STARTED OK and disarmed as today"); the old behaviour is kept below as a mutant that the new check kills. The Free Power package is unchanged.
        check(f"{nm} restart during a running session that something else started (the dongle's own Start button): NOT recorded as STARTED OK (owner decision r15): the text says Dump to Grid is active after a Home Assistant restart "
              "and that this schedule did not confirm that it started it, the schedule is disarmed, no start by Home Assistant",
              dump_unverified_ok(x), f"{x.last()!r} {x.ha.runs}")
    else:
        # Owner decision of 20 Nov 2026 (the Free Power result-integrity fix): this session was started by the dongle's own Start button (a manual start), not verified as THIS schedule's own start, so the recovery must not
        # record it as STARTED OK. It was pinned the other way here ("recorded STARTED OK and disarmed as today"); the old behaviour is kept in [6] as a mutant that the new checks kill. The Export to Grid package is not
        # changed by this commit.
        check(f"{nm} restart during a running session that something else started (the dongle's own Start button): NOT recorded as STARTED OK (owner decision of 20 Nov 2026): the text says Free Power is active after a Home "
              "Assistant restart and that this schedule did not confirm that it started it, the schedule is disarmed, no start by Home Assistant",
              free_unverified_ok(x), f"{x.last()!r} {x.ha.runs}")
    if kind == "dump":
        x = session_restart(kind, last="STARTED OK - 3000W for 60 min, Stop SOC 40% (attempt 1; ends by 19:05)")
        check(f"{nm} restart during a session whose start THIS schedule verified (the last result starts with STARTED): recorded STARTED OK - running and disarmed, byte for byte as before (owner decision r15 keeps this path)",
              x.last() == "STARTED OK - running (Home Assistant restarted during the session)" and not x.is_armed() and not [r for r in x.ha.runs if r[1] == KINDS[kind]["script"]], f"{x.last()!r}")
        for refused in ("FAILED TO START - REJECTED - another inverter write is active (attempt 1; nothing written)", "BLOCKED - the effective reserve rose above the Stop SOC staged for this run (40%) while it was waiting; nothing started (reason RESERVE_TOO_HIGH)",
                        "CANCELLED - scheduled Dump to Grid cancelled before it started"):
            x = session_restart(kind, last=refused)
            check(f"{nm} restart while the dongle runs a session and the last result is '{refused.split(' - ')[0]}': the refusal is final and stays exactly as written (never STARTED OK), the schedule is disarmed, nothing started, no new alert",
                  x.last() == refused and not x.is_armed() and not [r for r in x.ha.runs if r[1] == KINDS[kind]["script"]] and x.missed_alerts() == [], f"{x.last()!r}")
        x = session_restart(kind, last="STARTING - 3000W, Stop SOC 40%, until 20:00")
        check(f"{nm} restart while the dongle runs a session and this run was still STARTING: not a success: the UNCONFIRMED text, disarmed, nothing started",
              dump_unverified_ok(x), f"{x.last()!r}")

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



def old_recovery_write(pkg):
    """The recovery's active branch as it stood before owner decision r15: STARTED OK whatever the last result was (the Dump to Grid package only)."""
    rec = next(a for a in pkg["automation"] if a["id"] == "ecco_dump_to_grid_schedule_startup_recovery")
    for act in rec["actions"]:
        for br in act.get("choose", []):
            if any(str(c.get("entity_id", "")).endswith("dump_to_grid_active") for c in br["conditions"]) and any(c.get("value_template") == "{{ now_ts < end_ts }}" for c in br["conditions"]):
                br["sequence"] = [{"action": "input_text.set_value", "target": {"entity_id": "input_text.ecco_dump_to_grid_schedule_last_result"},
                                   "data": {"value": "STARTED OK - running (Home Assistant restarted during the session)"}},
                                  {"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.ecco_dump_to_grid_schedule_armed"}}]


x = session_restart("dump", mutate=old_recovery_write)
check("dump: mutant - the old unconditional STARTED OK write of the startup recovery put back: the r15 check for a session the dongle's own Start button started fails (it reads STARTED OK)",
      x.last().startswith("STARTED OK - running") and not dump_unverified_ok(x), f"{x.last()!r}")
x = session_restart("dump", last="FAILED TO START - REJECTED - another inverter write is active (attempt 1; nothing written)", mutate=old_recovery_write)
check("dump: mutant - the old unconditional write put back: a FAILED result is recorded as STARTED OK (the r15 check for a refusal fails)", x.last().startswith("STARTED OK - running"), f"{x.last()!r}")
x = session_restart("dump", last="CANCELLED - scheduled Dump to Grid cancelled before it started", mutate=old_recovery_write)
check("dump: mutant - the old unconditional write put back: a CANCELLED result is recorded as STARTED OK (the r15 check for a cancel fails)", x.last().startswith("STARTED OK - running"), f"{x.last()!r}")

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

# ======================================================================================================================
print("\n[5] clock changes (28 Mar 2027, 31 Oct 2027, 25 Oct 2026, Europe/London): the arm validation refuses a start label that is a "
      "skipped, repeated or unreadable local time, and checks the TOU slots on the instants the run really covers")
# ======================================================================================================================
# Owner decision of 20 Nov 2026 (item 4; the clock-change examination of 19 Nov, findings T1 to T3 and T7, proposals P-A and P-B).
# The real package YAML runs under the interpreter with the REAL London zone (S.local_zone) instead of its fixed UTC+1. What is a MODEL
# here (RECALLED, not verified against a real Home Assistant; proposal P-F, the supervised template check, is still open): a naive local
# string is read as its first occurrence (fold 0), a skipped one with the offset in force before the change; the suite also runs the
# other reading (fold 1) so that nothing depends on which one is right. Times below are UTC unless a label says otherwise.
LON = ZoneInfo("Europe/London")
CLOCK_TEXT = "REJECTED - the start time is a skipped, repeated or unreadable local time (clock change); pick another time"
FUTURE_TEXT = "REJECTED - scheduled start must be in the future"
TOU_SLOTS = ("00:00", "04:00", "05:30", "12:00", "17:00", "22:00")


def utc_epoch(s: str) -> float:
    f = "%Y-%m-%d %H:%M:%S" if s.count(":") == 2 else "%Y-%m-%d %H:%M"
    return datetime.strptime(s, f).replace(tzinfo=timezone.utc).timestamp()


def slot_table(slot2: str, kinds=("None", "Grid", "None", "None", "None", "None")):
    """Six TOU slots: slot 1 from 00:00, slot 2 from `slot2`, then 05:30, 12:00, 17:00 and 22:00 (a charge source on slot 2 only)."""
    times = ["00:00", slot2, "05:30", "12:00", "17:00", "22:00"]
    return list(zip(times, kinds))


class CC:
    """One schedule package in the REAL arm validation under the current local zone: Home Assistant booted at `boot` (UTC), the start
    helper holds `label` exactly as typed, the schedule is armed at `arm` (UTC); read the arm validation's answer."""

    def __init__(self, kind, label, boot, arm, duration=60, slots=None, text=None, mutate=None, filters=None):
        k = KINDS[kind]
        self.kind, self.p = kind, k["p"]
        p = self.p
        self.armed = f"input_boolean.{p}_schedule_armed"
        self.last_e = f"input_text.{p}_schedule_last_result"
        self.start_e = f"input_datetime.{p}_schedule_start"
        self.w = w = S.World(utc_epoch(boot))
        if kind == "dump":
            D.add_ha_filters(w)
            self.d = D.DumpDongle(w)
        else:
            self.d = S.Dongle(w)
        pkg = yaml.safe_load(text if text is not None else k["text"])
        if mutate:
            mutate(pkg)
        for name, fn in (filters or {}).items():
            w.env.filters[name] = fn
        self.ha = S.HA(w, pkg)
        w.set(self.start_e, label)
        w.set(f"input_number.{p}_schedule_duration", f"{float(duration)}")
        w.set(f"input_number.{p}_schedule_power", "3000.0")
        if kind == "dump":
            w.set(f"input_number.{p}_schedule_stop_soc", "40.0")
        w.set("sensor.ecco_config_maximum_grid_charge_power", "8000")
        w.set(self.armed, "off")
        w.set(self.last_e, "")
        w.set("input_boolean.ecco_free_power_schedule_armed" if kind == "dump" else "input_boolean.ecco_dump_to_grid_schedule_armed", "off")
        for i, (t, c) in enumerate(slots or [], 1):
            w.set(f"sensor.ecco_clock_dongle_ecco_timezone{i}_time", t)
            w.set(f"sensor.ecco_clock_dongle_ecco_timezone{i}_charge", c)
        self.ha.start()
        w.run_until(utc_epoch(arm))
        w.set(self.armed, "on")
        w.run_until(utc_epoch(arm) + 5)

    def verdict(self) -> str:
        t, armed = self.w.state(self.last_e), self.w.state(self.armed)
        if t == CLOCK_TEXT and armed == "off":
            return "CLOCK"
        if t.startswith("ARMED - ") and armed == "on":
            return "ARMED"
        if t.startswith("REJECTED - window overlaps a TOU slot with a charge source set") and armed == "off":
            return "TOU"
        if t == FUTURE_TEXT and armed == "off":
            return "FUTURE"
        return f"OTHER: armed={armed} {t!r}"


def verdict_of(kind, **kw) -> str:
    """The arm validation's answer for one case; a run that raises (the interpreter is fail loud) is a verdict that matches nothing."""
    try:
        return CC(kind, **kw).verdict()
    except Exception as exc:  # noqa: BLE001
        return f"RAISED {type(exc).__name__}: {str(exc)[:100]}"


def london_oracle(day: str) -> dict[str, str]:
    """Independent truth for every wall-clock minute label HH:MM of `day` in Europe/London, built by walking EVERY real UTC minute around the
    day and counting how often each wall label occurs (no fold, no round trip): 0 times NONEXISTENT, once OK, twice AMBIGUOUS."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(hours=14)
    seen: dict[str, int] = {}
    for i in range(52 * 60):
        wall = (start + timedelta(minutes=i)).astimezone(LON)
        if wall.strftime("%Y-%m-%d") == day:
            lab = wall.strftime("%H:%M")
            seen[lab] = seen.get(lab, 0) + 1
    out = {}
    for m in range(1440):
        lab = f"{m // 60:02d}:{m % 60:02d}"
        n = seen.get(lab, 0)
        out[lab] = "NONEXISTENT" if n == 0 else "OK" if n == 1 else "AMBIGUOUS"
    return out


def sweep(kind: str, day: str, text=None, mutate=None) -> tuple[list[str], list[str], list[str]]:
    """Arm every minute label of `day` once in ONE running Home Assistant (armed well before: 12:10 UTC the day before) through the real
    arm validation; returns the labels refused with the clock-change text, the labels armed, and every other answer."""
    prev = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    x = CC(kind, f"{day} 00:00:00", f"{prev} 12:00", f"{prev} 12:10", text=text, mutate=mutate)
    w = x.w
    refused, armed, other = [], [], []
    for m in range(1440):
        hhmm = f"{m // 60:02d}:{m % 60:02d}"
        w.set(x.armed, "off")
        w.set(x.last_e, "")
        w.set(x.start_e, f"{day} {hhmm}:00")
        w.run_until(w.t + 1)
        w.set(x.armed, "on")
        w.run_until(w.t + 2)
        v = x.verdict()
        (refused if v == "CLOCK" else armed if v == "ARMED" else other).append(hhmm if v in ("CLOCK", "ARMED") else f"{hhmm} {v}")
    return refused, armed, other


def span(mins: list[str]) -> str:
    return f"{mins[0]}..{mins[-1]} ({len(mins)})" if mins else "none"


DAYS = (("2027-03-28", "spring forward"), ("2027-10-31", "fall back"), ("2026-10-25", "fall back (past)"), ("2027-06-15", "ordinary summer"),
        ("2027-11-10", "ordinary winter"))

with S.local_zone(LON):
    ORACLE = {day: london_oracle(day) for day, _ in DAYS}
    check("the oracle itself: 60 skipped minutes on 28 Mar 2027 (01:00-01:59), 60 repeated on 31 Oct 2027 and on 25 Oct 2026, none on an ordinary day",
          {d: sum(1 for v in o.values() if v != "OK") for d, o in ORACLE.items()}
          == {"2027-03-28": 60, "2027-10-31": 60, "2026-10-25": 60, "2027-06-15": 0, "2027-11-10": 0}
          and {m for m, v in ORACLE["2027-03-28"].items() if v == "NONEXISTENT"} == {f"01:{i:02d}" for i in range(60)}
          and {m for m, v in ORACLE["2027-10-31"].items() if v == "AMBIGUOUS"} == {f"01:{i:02d}" for i in range(60)})

    # ---- every minute of every day, through the real arm validation, for both packages, under both readings of a naive local string
    for kind in KINDS:
        for fold in (0, 1):
            with S.local_zone(LON, fold=fold):
                for day, what in DAYS:
                    want = sorted(m for m, v in ORACLE[day].items() if v != "OK")
                    refused, armed, other = sweep(kind, day)
                    check(f"{kind}: every minute of {day} ({what}), fold {fold}: exactly the {len(want)} skipped or repeated minutes are refused with the "
                          f"clock-change text ({span(refused)}), the other {1440 - len(want)} are armed, nothing else happens",
                          refused == want and len(armed) == 1440 - len(want) and not other,
                          f"refused {span(refused)} want {span(want)}; armed {len(armed)}; other {other[:3]}")

    # ---- named cases for both packages (arming a day ahead unless said)
    NAMED = [
        # name, label, boot, arm, expected
        ("spring 28 Mar 2027, 01:30 (does not exist)", "2027-03-28 01:30:00", "2027-03-27 20:00", "2027-03-27 20:10", "CLOCK"),
        ("spring, the first skipped minute 01:00", "2027-03-28 01:00:00", "2027-03-27 20:00", "2027-03-27 20:10", "CLOCK"),
        ("spring, the last skipped minute 01:59", "2027-03-28 01:59:00", "2027-03-27 20:00", "2027-03-27 20:10", "CLOCK"),
        ("spring, 00:59 (the last minute before) is armed", "2027-03-28 00:59:00", "2027-03-27 20:00", "2027-03-27 20:10", "ARMED"),
        ("spring, 02:00 BST (valid; the window 02:00-03:00 lies inside one offset) is armed", "2027-03-28 02:00:00", "2027-03-27 20:00", "2027-03-27 20:10", "ARMED"),
        ("autumn 31 Oct 2027, 01:30 (repeated)", "2027-10-31 01:30:00", "2027-10-30 20:00", "2027-10-30 20:10", "CLOCK"),
        ("autumn 25 Oct 2026, 01:30 (repeated)", "2026-10-25 01:30:00", "2026-10-24 20:00", "2026-10-24 20:10", "CLOCK"),
        ("autumn, 00:59 (before the repeated hour) is armed", "2027-10-31 00:59:00", "2027-10-30 20:00", "2027-10-30 20:10", "ARMED"),
        ("autumn, 02:00 GMT (after it) is armed", "2027-10-31 02:00:00", "2027-10-30 20:00", "2027-10-30 20:10", "ARMED"),
        ("arming at 01:10 GMT (the SECOND 01:10) for 01:30: the truthful clock-change text, not 'must be in the future' (T3)",
         "2027-10-31 01:30:00", "2027-10-31 00:20", "2027-10-31 01:10", "CLOCK"),
        ("arming at 00:50 BST (the first 01:xx hour not yet reached) for 01:30", "2027-10-31 01:30:00", "2027-10-31 00:20", "2027-10-31 00:50", "CLOCK"),
        ("arming at 01:10 GMT for 02:30 (valid, ahead) is armed", "2027-10-31 02:30:00", "2027-10-31 00:20", "2027-10-31 01:10", "ARMED"),
        ("control: an ordinary winter evening", "2027-11-10 22:00:00", "2027-11-10 20:00", "2027-11-10 20:10", "ARMED"),
        ("control: an ordinary summer evening", "2027-06-15 22:00:00", "2027-06-15 20:00", "2027-06-15 20:10", "ARMED"),
        ("control: a start in the past keeps its own text", "2027-11-10 09:00:00", "2027-11-10 10:00", "2027-11-10 10:10", "FUTURE"),
        ("unreadable: empty", "", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: unknown", "unknown", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: unavailable", "unavailable", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: text", "tomorrow evening", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: hour 24", "2027-11-10 24:00:00", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: hour 25, minute 61", "2027-11-10 25:61:00", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: no seconds (not the helper's own format)", "2027-11-10 22:00", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
        ("unreadable: the epoch itself (it reads as 0)", "1970-01-01 01:00:00", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
    ]
    for kind in KINDS:
        for name, label, boot, arm, want in NAMED:
            got = verdict_of(kind, label=label, boot=boot, arm=arm)
            check(f"{kind}: {name} -> {want}", got == want, got)
            if "01:30" in name and want == "CLOCK" and "arming at" not in name:
                with S.local_zone(LON, fold=1):
                    got1 = verdict_of(kind, label=label, boot=boot, arm=arm)
                check(f"{kind}: ...the same label when a naive local string is read the other way (fold 1) -> {want}", got1 == want, got1)

    # ---- fail closed: a conversion that cannot be made refuses (the package gives every call a default)
    def broken_custom(value, fmt="%Y-%m-%d %H:%M:%S", local=True, default=S._MISSING):
        if default is S._MISSING:
            raise S.SimError("timestamp_custom raised")
        return default

    for kind in KINDS:
        got = verdict_of(kind, label="2027-11-10 22:00:00", boot="2027-11-10 20:00", arm="2027-11-10 20:10", filters={"timestamp_custom": broken_custom})
        check(f"{kind}: fail closed - the label cannot be converted back (timestamp_custom fails): refused with the clock-change text, never armed", got == "CLOCK", got)

    # ---- the TOU overlap walk on the instants the run really covers (Dump to Grid; the Free Power package has no TOU check)
    TOU_CASES = [
        # name, label, boot, arm, minutes, slot2 start, expected
        ("spring: 00:30 for 120 min, a charge slot from 03:00 BST (really 00:30-01:00 GMT then 02:00-03:30 BST): refused - the old walk accepted it (T7)",
         "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 120, "03:00", "TOU"),
        ("spring: 00:30 for 90 min ends at 03:00 BST, the slot's first minute (the end minute counts): refused",
         "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 90, "03:00", "TOU"),
        ("spring: 00:30 for 89 min ends at 02:59 BST: armed",
         "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 89, "03:00", "ARMED"),
        ("spring: 00:30 for 60 min (00:30-01:00 GMT, 02:00-02:30 BST), slot from 03:00: armed",
         "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 60, "03:00", "ARMED"),
        ("spring: 02:00 for 60 min, slot from 03:00 (the end minute is 03:00): refused",
         "2027-03-28 02:00:00", "2027-03-27 20:00", "2027-03-27 20:10", 60, "03:00", "TOU"),
        ("autumn 31 Oct 2027: 00:45 for 240 min ends 03:45 GMT, a charge slot from 04:00: armed - the old walk refused it (T7)",
         "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 240, "04:00", "ARMED"),
        ("autumn 25 Oct 2026: the same", "2026-10-25 00:45:00", "2026-10-24 20:00", "2026-10-24 20:10", 240, "04:00", "ARMED"),
        ("autumn: 00:45 for 240 min with a slot from 03:00 (a real overlap): refused",
         "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 240, "03:00", "TOU"),
        ("autumn: 00:45 for 180 min ends 02:45 GMT, a slot from 02:45 (the end minute): refused",
         "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 180, "02:45", "TOU"),
        ("autumn: 00:45 for 180 min, a slot from 02:46: armed",
         "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 180, "02:46", "ARMED"),
        ("autumn: 02:00 GMT for 120 min, a slot from 04:00 (the end minute): refused",
         "2027-10-31 02:00:00", "2027-10-30 20:00", "2027-10-30 20:10", 120, "04:00", "TOU"),
        ("control, ordinary winter day: 00:45 for 240 min, slot from 04:00: refused",
         "2027-11-10 00:45:00", "2027-11-09 20:00", "2027-11-09 20:10", 240, "04:00", "TOU"),
        ("control, ordinary winter day: 00:45 for 180 min, slot from 04:00: armed",
         "2027-11-10 00:45:00", "2027-11-09 20:00", "2027-11-09 20:10", 180, "04:00", "ARMED"),
        ("control, ordinary summer day (BST): 00:45 for 240 min, slot from 04:00: refused",
         "2027-06-15 00:45:00", "2027-06-14 20:00", "2027-06-14 20:10", 240, "04:00", "TOU"),
        ("control, ordinary summer day (BST): 00:45 for 180 min, slot from 04:00: armed",
         "2027-06-15 00:45:00", "2027-06-14 20:00", "2027-06-14 20:10", 180, "04:00", "ARMED"),
    ]
    for name, label, boot, arm, mins, slot2, want in TOU_CASES:
        got = verdict_of("dump", label=label, boot=boot, arm=arm, duration=mins, slots=slot_table(slot2))
        check(f"dump: {name}", got == want, got)
    # a slot table that cannot be read still defers to the firmware's own check (unchanged), also on a clock-change day
    unreadable = slot_table("03:00")
    unreadable[2] = ("unavailable", "None")
    got = verdict_of("dump", label="2027-03-28 00:30:00", boot="2027-03-27 20:00", arm="2027-03-27 20:10", duration=120, slots=unreadable)
    check("dump: an unreadable slot table does not refuse (the firmware's own START check stays the authority), as before", got == "ARMED", got)

    def garbage_local(value, default=None):
        return "not-an-iso-timestamp"

    got = verdict_of("dump", label="2027-11-10 00:45:00", boot="2027-11-09 20:00", arm="2027-11-09 20:10", duration=60, slots=slot_table("04:00"),
                     filters={"timestamp_local": garbage_local})
    check("dump: fail closed - a minute whose local time cannot be read refuses the arm (the slot check never silently passes)", got == "TOU", got)

    # ---- the walk against an independent truth, over every quarter hour of every day, three window lengths and three slot tables
    def truth(start_epoch: float, minutes: int, table) -> bool:
        starts = [int(t[:2]) * 60 + int(t[3:5]) for t, _c in table]
        for k in range(minutes + 1):
            wall = datetime.fromtimestamp(start_epoch + 60 * k, LON)
            m = wall.hour * 60 + wall.minute
            for i in range(6):
                s_, e_ = starts[i], starts[(i + 1) % 6]
                if ((e_ > s_ and s_ <= m < e_) or (e_ < s_ and (m >= s_ or m < e_))) and table[i][1] != "None":
                    return True
        return False

    def tou_template(pkg) -> str | None:
        arm_a = next(a for a in pkg["automation"] if a["id"] == "ecco_dump_to_grid_schedule_arm_validation")
        for br in next(a for a in arm_a["actions"] if "choose" in a)["choose"]:
            for c in br["conditions"]:
                if c.get("condition") == "template" and "namespace(ok=true" in c["value_template"]:
                    return c["value_template"]
        return None

    def walk_sweep(text) -> tuple[int, list[str]]:
        tpl = tou_template(yaml.safe_load(text))
        if tpl is None:
            return 0, ["no TOU template found"]
        bad, n = [], 0
        x = CC("dump", "2027-11-10 22:00:00", "2027-11-09 20:00", "2027-11-09 20:10", text=text)
        w = x.w
        for slot2 in ("01:30", "03:00", "04:00"):
            table = slot_table(slot2)
            for i, (t, c) in enumerate(table, 1):
                w.set(f"sensor.ecco_clock_dongle_ecco_timezone{i}_time", t)
                w.set(f"sensor.ecco_clock_dongle_ecco_timezone{i}_charge", c)
            for mins in (45, 120, 240):
                w.set("input_number.ecco_dump_to_grid_schedule_duration", f"{float(mins)}")
                for day, _what in DAYS:
                    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(hours=1)
                    for q in range(0, 26 * 4):
                        st = (base + timedelta(minutes=15 * q)).timestamp()
                        n += 1
                        got = w.render(tpl, {"start_ts": st}).strip() == "True"
                        if got != truth(st, mins, table):
                            bad.append(f"{day} {datetime.fromtimestamp(st, LON):%H:%M%z} {mins} min slot2 {slot2}: package {got}")
        return n, bad

    n_walk, bad_walk = walk_sweep(KINDS["dump"]["text"])
    check(f"dump: the TOU walk agrees with the independent truth (zoneinfo, every real minute) in all {n_walk} combinations of start (every quarter "
          "hour around 28 Mar 2027, 31 Oct 2027, 25 Oct 2026 and two ordinary days), length (45, 120, 240 min) and slot table (a charge slot from 01:30, 03:00, 04:00)",
          n_walk > 0 and not bad_walk, f"{len(bad_walk)} differ, first: {bad_walk[:3]}")

    # ---- mutation: each wrong version of the new logic is caught by the cases above
    def find_branch(pkg, kind, needle):
        arm_a = next(a for a in pkg["automation"] if a["id"].endswith("_schedule_arm_validation"))
        ch = next(a for a in arm_a["actions"] if "choose" in a)["choose"]
        for i, br in enumerate(ch):
            if needle in str(br["sequence"]) or any(needle in str(c.get("value_template", "")) for c in br["conditions"]):
                return ch, i, br
        return ch, -1, None

    def tmpl_mutant(needle, anchor, repl):
        def mut(pkg):
            ch, i, br = find_branch(pkg, None, needle)
            if br is None:
                return
            cond = next(c for c in br["conditions"] if c.get("condition") == "template")
            if cond["value_template"].count(anchor) != 1:
                raise AssertionError(f"mutant anchor {anchor!r} occurs {cond['value_template'].count(anchor)}x")
            cond["value_template"] = cond["value_template"].replace(anchor, repl)
        return mut

    def pa_battery(kind: str, mutate=None, text=None) -> dict:
        res = {}
        if mutate:
            mutate(yaml.safe_load(text if text is not None else KINDS[kind]["text"]))      # an anchor that is not there raises HERE, not inside a run
        for key, label, boot, arm, want in (
                ("spring", "2027-03-28 01:30:00", "2027-03-27 20:00", "2027-03-27 20:10", "CLOCK"),
                ("autumn", "2027-10-31 01:30:00", "2027-10-30 20:00", "2027-10-30 20:10", "CLOCK"),
                ("t3", "2027-10-31 01:30:00", "2027-10-31 00:20", "2027-10-31 01:10", "CLOCK"),
                ("unreadable", "garbage", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
                ("epoch", "1970-01-01 01:00:00", "2027-11-09 20:00", "2027-11-09 20:10", "CLOCK"),
                ("control", "2027-11-10 22:00:00", "2027-11-10 20:00", "2027-11-10 20:10", "ARMED"),
                ("control_spring_valid", "2027-03-28 02:00:00", "2027-03-27 20:00", "2027-03-27 20:10", "ARMED"),
                ("control_autumn_valid", "2027-10-31 02:00:00", "2027-10-30 20:00", "2027-10-30 20:10", "ARMED"),
                ("past", "2027-11-10 09:00:00", "2027-11-10 10:00", "2027-11-10 10:10", "FUTURE")):
            res[key] = verdict_of(kind, label=label, boot=boot, arm=arm, mutate=mutate, text=text) == want
        with S.local_zone(LON, fold=1):
            res["autumn_fold1"] = verdict_of(kind, label="2027-10-31 01:30:00", boot="2027-10-30 20:00", arm="2027-10-30 20:10",
                                             mutate=mutate, text=text) == "CLOCK"
        res["fail_closed"] = verdict_of(kind, label="2027-11-10 22:00:00", boot="2027-11-10 20:00", arm="2027-11-10 20:10", mutate=mutate, text=text,
                                        filters={"timestamp_custom": broken_custom}) == "CLOCK"
        return res

    def drop_branch(pkg):
        ch, i, br = find_branch(pkg, None, "skipped, repeated or unreadable")
        if br is not None:
            del ch[i]

    def move_after_future(pkg):
        ch, i, br = find_branch(pkg, None, "skipped, repeated or unreadable")
        j = next(n for n, b in enumerate(ch) if "must be in the future" in str(b["sequence"]))
        if br is not None:
            ch.insert(j, ch.pop(i))

    def no_disarm(pkg):
        ch, i, br = find_branch(pkg, None, "skipped, repeated or unreadable")
        if br is not None:
            br["sequence"] = [a for a in br["sequence"] if a["action"] != "input_boolean.turn_off"]

    def wrong_text(pkg):
        ch, i, br = find_branch(pkg, None, "skipped, repeated or unreadable")
        if br is not None:
            br["sequence"][-1]["data"]["value"] = "REJECTED - scheduled start must be in the future"

    PA_MUTANTS = [
        ("the branch removed (the old behaviour)", drop_branch),
        ("the round trip dropped (a skipped label is not noticed)", tmpl_mutant("skipped, repeated or unreadable", " or (t | timestamp_custom(f, true, 'unreadable')) != s", "")),
        ("the hour shift dropped (a repeated label is not noticed)",
         tmpl_mutant("skipped, repeated or unreadable", " or ((t + 3600) | timestamp_custom(f, true, 'unreadable')) == s", "")),
        ("only the later reading checked (a repeated label read as its second occurrence is not noticed)",
         tmpl_mutant("skipped, repeated or unreadable", " or ((t - 3600) | timestamp_custom(f, true, 'unreadable')) == s", "")),
        ("the unreadable test dropped (the epoch label reads as a valid one)", tmpl_mutant("skipped, repeated or unreadable", "{{ t <= 0\n   or ", "{{ ")),
        ("no default on the conversions (a conversion that fails raises instead of refusing)",
         tmpl_mutant("skipped, repeated or unreadable", "(t | timestamp_custom(f, true, 'unreadable'))", "(t | timestamp_custom(f))")),
        ("the refusal is checked AFTER 'must be in the future' (T3 is misleading again)", move_after_future),
        ("the refusal does not disarm", no_disarm),
        ("the refusal reuses the 'must be in the future' text", wrong_text),
        ("the round trip inverted (only a label that survives it is refused)",
         tmpl_mutant("skipped, repeated or unreadable", " or (t | timestamp_custom(f, true, 'unreadable')) != s", " or (t | timestamp_custom(f, true, 'unreadable')) == s")),
    ]
    for kind in KINDS:
        base_res = pa_battery(kind)
        check(f"{kind}: the P-A battery holds on the real package", all(base_res.values()), str(base_res))
        for name, mut in PA_MUTANTS:
            try:
                res = pa_battery(kind, mutate=mut)
            except AssertionError as exc:
                check(f"{kind}: P-A mutant '{name}': its anchor is present", False, str(exc))
                continue
            check(f"{kind}: P-A mutant '{name}' is killed (fails: {[k for k, v in res.items() if not v]})", not all(res.values()), str(res))

    UTC_FILTER = {"timestamp_utc": lambda v, default=None: datetime.fromtimestamp(float(v), timezone.utc).isoformat()}   # only a mutant uses it

    def pb_battery(mutate=None, text=None) -> dict:
        res = {}
        if mutate:
            mutate(yaml.safe_load(text if text is not None else KINDS["dump"]["text"]))   # an anchor that is not there raises HERE, not inside a run
        for key, name, label, boot, arm, mins, slot2, want in (
                ("spring_false_accept", "", "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 120, "03:00", "TOU"),
                ("spring_end_minute", "", "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 90, "03:00", "TOU"),
                ("spring_before_end", "", "2027-03-28 00:30:00", "2027-03-27 20:00", "2027-03-27 20:10", 89, "03:00", "ARMED"),
                ("autumn_false_refusal", "", "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 240, "04:00", "ARMED"),
                ("autumn_real_overlap", "", "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 240, "03:00", "TOU"),
                ("autumn_end_minute", "", "2027-10-31 00:45:00", "2027-10-30 20:00", "2027-10-30 20:10", 180, "02:45", "TOU"),
                ("winter_control", "", "2027-11-10 00:45:00", "2027-11-09 20:00", "2027-11-09 20:10", 240, "04:00", "TOU"),
                ("winter_clear", "", "2027-11-10 00:45:00", "2027-11-09 20:00", "2027-11-09 20:10", 180, "04:00", "ARMED"),
                ("summer_control", "", "2027-06-15 00:45:00", "2027-06-14 20:00", "2027-06-14 20:10", 240, "04:00", "TOU"),
                ("summer_clear", "", "2027-06-15 00:45:00", "2027-06-14 20:00", "2027-06-14 20:10", 180, "04:00", "ARMED")):
            res[key] = verdict_of("dump", label=label, boot=boot, arm=arm, duration=mins, slots=slot_table(slot2), mutate=mutate, text=text, filters=UTC_FILTER) == want
        res["fail_closed"] = verdict_of("dump", label="2027-11-10 00:45:00", boot="2027-11-09 20:00", arm="2027-11-09 20:10", duration=60, slots=slot_table("04:00"),
                                        mutate=mutate, text=text, filters={"timestamp_local": garbage_local, **UTC_FILTER}) == "TOU"
        return res

    NEW_STEP = "((start_ts | float(0)) + k * 60) | timestamp_local"
    PB_MUTANTS = [
        ("the old walk put back (continuous wall-clock minutes from the start's minute)",
         tmpl_mutant("charge source set", NEW_STEP, "((start_ts | float(0))) | timestamp_local")),
        ("the step in seconds instead of minutes", tmpl_mutant("charge source set", "k * 60", "k")),
        ("UTC minutes instead of local ones (the zone offset is lost in summer)", tmpl_mutant("charge source set", "| timestamp_local %}", "| timestamp_utc %}")),
        ("the end minute dropped (range up to the duration, not including it)", tmpl_mutant("charge source set", "range(0, dur + 1)", "range(0, dur)")),
        ("one minute too many (range beyond the end minute)", tmpl_mutant("charge source set", "range(0, dur + 1)", "range(0, dur + 2)")),
        ("hour and minute swapped", tmpl_mutant("charge source set", "hh * 60 + mi", "mi * 60 + hh")),
        ("an unreadable minute ignored (the flag is never raised)", tmpl_mutant("charge source set", "{% set ns.bad = true %}", "")),
        ("the flag is raised but not refused", tmpl_mutant("charge source set", "{{ ns.hit > 0 or ns.bad }}", "{{ ns.hit > 0 }}")),
    ]
    base_pb = pb_battery()
    check("dump: the P-B battery holds on the real package", all(base_pb.values()), str(base_pb))
    for name, mut in PB_MUTANTS:
        try:
            res = pb_battery(mutate=mut)
        except AssertionError as exc:
            check(f"dump: P-B mutant '{name}': its anchor is present", False, str(exc))
            continue
        check(f"dump: P-B mutant '{name}' is killed (fails: {[k for k, v in res.items() if not v]})", not all(res.values()), str(res))
    same = pb_battery(text=KINDS["dump"]["text"].replace("k * 60", "60 * k"))
    check("dump: control - an equivalent rewrite of the step (60 * k) survives the battery", all(same.values()), str(same))

# ======================================================================================================================
print("\n[6] Free Power: the startup recovery never writes STARTED OK over a result this schedule did not verify (owner decision of 20 Nov 2026)")
# ======================================================================================================================
# The Charge Battery (Free Power) package's recovery wrote "STARTED OK - running (Home Assistant restarted during the session)" whenever the
# schedule was armed, now was inside the window and Free Power was active, whatever the last result was: a refused (BLOCKED), failed,
# cancelled or restart-killed STARTING run read as a success when the dongle's own Start button, a manual start or another path had started
# Free Power. The recovery cannot tell who started it, so it trusts only the record. The Export to Grid package is not touched by this
# commit (its fix is carried by the stage 3 pull request).
FINAL_FREE = ("FAILED TO START - REJECTED - another inverter write is active (attempt 1; nothing written)",
              "FAILED TO START - no answer from the dongle to attempt 1; outcome unconfirmed, not retried (last status: STARTING)",
              "BLOCKED - requested 3000W above the effective grid charge limit 2000W",
              "CANCELLED - scheduled Free Power cancelled before it started",
              "CANCELLED - scheduled event disarmed")
OTHER_FREE = ("STARTING - 3000W until 20:00", "STARTING - attempt 2 waiting: dongle offline, limit unavailable or another write in progress; retrying until 18:10",
              "ARMED AFTER RESTART - waiting for 2026-10-11 18:00:00", "REJECTED - scheduled start must be in the future", "MISSED - not started after a Home Assistant restart",
              "something this schedule never writes", "")
OWN_FREE = "STARTED OK - 3000W for 60 min (attempt 1; ends by 19:05)"

x = free_restart()
check("free: restart while the dongle runs a session something else started (the dongle's own Start button), the last result the ARMED text: NOT STARTED OK - "
      "the UNCONFIRMED text (Free Power is active after a restart and this schedule did not confirm that it started it), disarmed, nothing started by Home Assistant",
      free_unverified_ok(x), f"{x.last()!r}")
x = free_restart(OWN_FREE)
check("free: ...the last result starts with STARTED (this schedule's own verified start, recorded before the restart): STARTED OK - running and the disarm, byte for byte as before",
      x.last() == "STARTED OK - running (Home Assistant restarted during the session)" and not x.is_armed() and not [r for r in x.ha.runs if r[1] == FREE_SCRIPT]
      and x.missed_alerts() == [], f"{x.last()!r}")
for refused in FINAL_FREE:
    x = free_restart(refused)
    check(f"free: ...the last result is '{refused.split(' - ')[0]} - {refused.split(' - ')[1][:28]}...': final, stays exactly as written (never STARTED OK), the schedule is disarmed, "
          "nothing started, no new alert", x.last() == refused and not x.is_armed() and not [r for r in x.ha.runs if r[1] == FREE_SCRIPT] and x.missed_alerts() == [],
          f"{x.last()!r} armed={x.is_armed()}")
for other in OTHER_FREE:
    x = free_restart(other)
    check(f"free: ...the last result is {other[:48]!r}: not a verified start, so the UNCONFIRMED text (never STARTED OK), disarmed, nothing started", free_unverified_ok(x), f"{x.last()!r}")

# Free Power NOT active at the restart: every outcome is the previous package's, run for run
OLD_RECOVERY_START = "          # Restarted while the session runs: it started; record it and disarm.\n"


def old_recovery_free(pkg):
    """The recovery's active branch as it stood before this decision (r9 as pushed): STARTED OK whatever the last result was."""
    rec = next(a for a in pkg["automation"] if a["id"] == "ecco_free_power_schedule_startup_recovery")
    for act in rec["actions"]:
        for br in act.get("choose", []):
            if any(str(c.get("entity_id", "")).endswith("free_power_active") for c in br["conditions"]) and any(
                    c.get("value_template") == "{{ now_ts < end_ts }}" for c in br["conditions"]):
                br["sequence"] = [{"action": "input_text.set_value", "target": {"entity_id": "input_text.ecco_free_power_schedule_last_result"},
                                   "data": {"value": "STARTED OK - running (Home Assistant restarted during the session)"}},
                                  {"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.ecco_free_power_schedule_armed"}}]


def inactive_scenarios(mutate):
    out = []
    for name, down, back, until, last in (("start in the downtime, window open", ST - 120, ST + 600, ST + 7300, None),
                                          ("start in the downtime, window expired", ST - 120, ST + DURATION * 60 + 100, ST + DURATION * 60 + 400, None),
                                          ("future start kept", ST - 3000, ST - 1800, ST - 1500, None),
                                          ("a FAILED result and Free Power not active", ST - 120, ST + 600, ST + 900, "FAILED TO START - x"),
                                          ("a STARTED result and Free Power not active", ST - 120, ST + 600, ST + 900, OWN_FREE)):
        x = Run("free", mutate=mutate)
        if last is not None:
            x.until(x.w.t + 10)
            x.w.set(x.last_e, last)
        x.restart(down, back).until(until)
        out.append((name, x.last(), x.is_armed(), x.status(), len(x.presses()), x.started(), [n[1:] for n in x.w.notification_log]))
    return out


check("free: with Free Power NOT active at the restart every outcome (last result, armed, status, presses, starts, notifications) equals the previous package's, scenario for scenario",
      inactive_scenarios(None) == inactive_scenarios(old_recovery_free), f"{inactive_scenarios(None)[:1]}")


# ---- mutation
def active_branch(pkg):
    rec = next(a for a in pkg["automation"] if a["id"] == "ecco_free_power_schedule_startup_recovery")
    for act in rec["actions"]:
        for br in act.get("choose", []):
            if any(str(c.get("entity_id", "")).endswith("free_power_active") for c in br["conditions"]) and any(
                    c.get("value_template") == "{{ now_ts < end_ts }}" for c in br["conditions"]):
                return br
    return None


def new_choose(br):
    """The new first action of the branch (a choose), or None while the branch still has the old single write."""
    if br is None or not br["sequence"] or "choose" not in br["sequence"][0]:
        return None
    return br["sequence"][0]


def mut_started_test(repl):
    def mut(pkg):
        ch = new_choose(active_branch(pkg))
        if ch is not None:
            c = ch["choose"][0]["conditions"][0]
            assert "startswith('STARTED')" in c["value_template"]
            c["value_template"] = repl(c["value_template"])
    return mut


def mut_final_list(drop):
    def mut(pkg):
        ch = new_choose(active_branch(pkg))
        if ch is not None:
            c = ch["choose"][1]["conditions"][0]
            assert f"r.startswith('{drop}')" in c["value_template"]
            c["value_template"] = c["value_template"].replace(f" or r.startswith('{drop}')", "").replace(f"r.startswith('{drop}') or ", "")
    return mut


def mut_default_text(pkg):
    ch = new_choose(active_branch(pkg))
    if ch is not None:
        ch["default"][0]["data"]["value"] = "STARTED OK - running (Home Assistant restarted during the session)"


def mut_no_disarm(pkg):
    br = active_branch(pkg)
    if new_choose(br) is not None:
        br["sequence"] = [a for a in br["sequence"] if a.get("action") != "input_boolean.turn_off"]


def mut_no_default(pkg):
    ch = new_choose(active_branch(pkg))
    if ch is not None:
        ch["default"] = []


def mut_final_writes(pkg):
    ch = new_choose(active_branch(pkg))
    if ch is not None:
        ch["choose"][1]["sequence"] = [{"action": "input_text.set_value", "target": {"entity_id": "input_text.ecco_free_power_schedule_last_result"},
                                        "data": {"value": "STARTED OK - running (Home Assistant restarted during the session)"}}]


def mut_press(pkg):
    ch = new_choose(active_branch(pkg))
    if ch is not None:
        ch["default"].append({"action": "script.ecco_free_power_start_scheduled", "data": {"duration_minutes": "{{ duration_min }}", "power_w": "{{ power_w }}",
                                                                                             "window_end_ts": "{{ end_ts }}"}})


def free_battery(mutate=None) -> dict:
    res = {}
    res["unverified"] = free_unverified_ok(free_restart(mutate=mutate))
    x = free_restart(OWN_FREE, mutate=mutate)
    res["own"] = x.last() == "STARTED OK - running (Home Assistant restarted during the session)" and not x.is_armed()
    for key, text in (("failed", FINAL_FREE[0]), ("blocked", FINAL_FREE[2]), ("cancelled", FINAL_FREE[3])):
        x = free_restart(text, mutate=mutate)
        res[key] = x.last() == text and not x.is_armed()
    res["starting"] = free_unverified_ok(free_restart(OTHER_FREE[0], mutate=mutate))
    res["empty"] = free_unverified_ok(free_restart("", mutate=mutate))
    return res


FREE_MUTANTS = [
    ("the old unconditional STARTED OK write put back", old_recovery_free),
    ("the STARTED test always true (every result is recorded as STARTED OK)", mut_started_test(lambda t: "{{ true }}")),
    ("the STARTED test inverted (a verified start loses its text, anything else reads STARTED OK)", mut_started_test(lambda t: t.replace("{{ ", "{{ not (", 1).replace(" }}", ") }}", 1))),
    ("FAILED missing from the final results (a refusal is overwritten)", mut_final_list("FAILED")),
    ("BLOCKED missing from the final results (a refusal is overwritten)", mut_final_list("BLOCKED")),
    ("CANCELLED missing from the final results (a cancel is overwritten)", mut_final_list("CANCELLED")),
    ("the final results rewritten as STARTED OK", mut_final_writes),
    ("the UNCONFIRMED text replaced by STARTED OK", mut_default_text),
    ("no text for any other result (STARTING, ARMED, empty stay as they were)", mut_no_default),
    ("the disarm dropped (the watchdog would then overwrite a refusal with MISSED)", mut_no_disarm),
    ("a start added to the recovery", mut_press),
]
base_free = free_battery()
check("free: the recovery battery holds on the real package", all(base_free.values()), str(base_free))
for name, mut in FREE_MUTANTS:
    try:
        res = free_battery(mutate=mut)
    except AssertionError as exc:
        check(f"free: recovery mutant '{name}': its anchor is present", False, str(exc))
        continue
    check(f"free: recovery mutant '{name}' is killed (fails: {[k for k, v in res.items() if not v]})", not all(res.values()), str(res))

print()
if FAILURES:
    print(f"{len(FAILURES)} check(s) FAILED:")
    for n in FAILURES:
        print("  -", n)
    sys.exit(1)
print(f"ALL PASS ({PASSES} checks)")
