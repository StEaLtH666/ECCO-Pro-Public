#!/usr/bin/env python3
"""Offline composition test: R9 (no automatic start of a missed scheduled run after a Home Assistant restart) AND the Energy Actions stage 3
enforcement (backend-enforced Hold battery / Skip tonight / Prepare for power cut and the effective reserve), both in the SAME scheduled Dump to
Grid package, home-assistant/packages/ecco_dump_to_grid_schedule.yaml.

Why a combined suite: each change has its own suite (test_ha_r9_missed_runs.py, test_ecco_plan_enforcement.py), and each is proved on a tree that
does not have the other. R9 lives in the automations (the fire automation's watchdog, the startup recovery, a capture automation); stage 3 lives in the
start script they call. This suite proves, on the tree that has BOTH, that the two layers compose: a start is made only if the missed-run guard
allows it AND the override / reserve checks allow it, every refusal happens before anything is staged or pressed, and the Stop SOC that is staged is
the raised one.

The REAL package YAML (the schedule package, the plan helper package and the guarded start package) runs under the repository's Home Assistant
script / automation interpreter (_ha_script_sim.py, zone-aware through _plan_sim.py) with the Dump to Grid dongle model (_ha_dump_sim.py), on a
virtual clock. Every Jinja condition is the package's own text, rendered by that interpreter; nothing is re-implemented here.

  [0] static      the guard order inside the start script (every refusal is a `choose` branch that stages and presses nothing; the staging and the
                  press sit only in the default branch), the fire automation's branch order, the start calls (only the on-time start and the watchdog's
                  not-missed branch), the startup recovery that starts nothing, the raised Stop SOC the script stages
  [1] (c)         an on-time run with no override starts exactly as before (the staged power, Stop SOC and duration, one press, STARTED OK)
  [2] (a)         a missed run after a restart is refused even when no override is active, on the recovery path, the watchdog path and both
  [3] (b)         an active Hold battery / Skip tonight / Prepare for power cut refuses an on-time run: nothing staged, nothing pressed, one alert
  [4] (d)         the staged Stop SOC is raised to the effective reserve (rounded up) and never lowered
  [5] (e)         an unreadable override record, an unknown reserve, a missing plan package, a reserve with no room under 90 percent: refused, nothing
                  staged or pressed (fail closed)
  [6] (f)         the watchdog's rescue of a lost on-time start obeys (a) and (b) and the raised Stop SOC; the startup recovery never starts a run and
                  never lets an override or a cleared override rescue a missed one
  [7] mutation    in-memory mutants of the merged package (the missed-run guard skipped, the override guard skipped, the unraised Stop SOC staged,
                  the guards swapped behind the press) are each caught
  [8] write enable the dongle's write enable reads OFF at the end of every outcome: refusals on the on-time and the watchdog path (the write enable is
                  left ON beforehand, so the package's own last step is what is read), completed starts, and the startup recovery
  [9] hold state  a plan hold that reads unavailable, junk, empty or a near miss of `clear` refuses (OVERRIDE_UNREADABLE) on the on-time, the watchdog and
                  the recovery paths, nothing staged, armed or pressed (the plan sensor is forced to the state: the real producer never gives it)
  [10] ceil       a fractional effective reserve (forced onto the sensor; the producer publishes whole numbers today, so this is defence in depth on the
                  consumer) is rounded UP (62.4 -> 63; 62.0 -> 62), never down, the request never lowered; an unreadable reserve refuses
  [11] pre-press  the Stop SOC readback is compared with the RAISED value before the press: a readback that is the raw request, or any other value,
                  presses nothing
  [12] mutation   in-memory mutants of the gaps above (the final write-enable OFF removed, an unavailable hold let through, only `unknown` refused, round
                  instead of ceil, the pre-press check against the raw request, the recovery's write-enable OFF removed) are each caught

Writes nothing; no Home Assistant, no network, no hardware. It proves the packages against a model of the dongle; it proves nothing about a live
Home Assistant restart (the capture on the `homeassistant` start event, the restored helper states), the dongle or the inverter.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import _ha_script_sim as S  # noqa: E402
import _ha_dump_sim as D  # noqa: E402
import _plan_sim as P  # noqa: E402

PKGS = ROOT / "home-assistant" / "packages"
DUMP_TEXT = (PKGS / "ecco_dump_to_grid_schedule.yaml").read_text(encoding="utf-8")
PLAN_TEXT = (PKGS / "ecco_plan_helpers.yaml").read_text(encoding="utf-8")
GUARD_TEXT = (PKGS / "ecco_dump_to_grid_guarded_start.yaml").read_text(encoding="utf-8")

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


ARMED = "input_boolean.ecco_dump_to_grid_schedule_armed"
START_E = "input_datetime.ecco_dump_to_grid_schedule_start"
DUR_E = "input_number.ecco_dump_to_grid_schedule_duration"
PWR_E = "input_number.ecco_dump_to_grid_schedule_power"
SOC_E = "input_number.ecco_dump_to_grid_schedule_stop_soc"
LAST = "input_text.ecco_dump_to_grid_schedule_last_result"
NOTE = "ecco_dump_to_grid_schedule"                  # the scheduled start's persistent notification id (missed run, and every BLOCKED / FAILED result)
HOLD, EFF = "sensor.ecco_plan_export_hold", "sensor.ecco_plan_effective_reserve"
OWNER = "input_number.ecco_minimum_reserve_soc"
KINDS = ["hold_battery", "skip_tonight", "prepare_power_cut"]
EXP = {k: f"input_datetime.ecco_plan_override_{k}_expires" for k in KINDS}
SCRIPT = "script.ecco_dump_to_grid_start_scheduled"
MISSED_TEXT = "MISSED - not started after a Home Assistant restart"

ST = S.parse_local("2026-11-17 22:00:00")            # the scheduled start
T0 = ST - 3600                                         # first Home Assistant boot
LOCAL_T0 = "2026-11-17 21:00:00"
DURATION = 60                                          # window 22:00-23:00
POWER = 2000


def walk(obj):
    """Every mapping inside a parsed package (the interpreter's own data), depth first."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def calls(obj, service: str) -> list:
    return [d for d in walk(obj) if d.get("action") == service]


def dump(obj) -> str:
    return json.dumps(obj, sort_keys=False)


def drop_automation(suffix: str):
    def mut(pkg):
        pkg["automation"] = [a for a in pkg["automation"] if not a["id"].endswith(suffix)]
    return mut


def force(x, entity: str, text: str):
    """Make a plan sensor read `text`. The interpreter renders a template sensor on EVERY read, so a plain state write is ignored; the sensor's
    template is replaced by the literal instead (the interpreter's own `template_entities` map, nothing in a simulator is edited). Used for the
    states the real plan helper package never produces (unavailable, a junk text, the empty state, a fractional reserve): the start script
    reads a sensor it does not control and must treat each of them safely. Call it AFTER a restart(): a restarted interpreter loads the sensor
    templates again."""
    x.w.template_entities[entity] = text
    return x


class Combo:
    """Home Assistant (booted at T0) + the real schedule, plan helper and guarded start packages + the Dump to Grid dongle model, armed for ST."""

    def __init__(self, owner=40.0, stop=40, lose=(), mutate=None, install_plan=True):
        self.lose = set(lose)
        self.mutate = mutate
        self.install_plan = install_plan
        self.pw = P.PlanWorld(LOCAL_T0, self._pkgs(), "Etc/GMT-1")
        self.w = w = self.pw.w
        D.add_ha_filters(w)
        self.d = D.DumpDongle(w)
        self.pw.set_local(START_E, "2026-11-17 22:00:00")
        w.set(DUR_E, f"{float(DURATION)}")
        w.set(PWR_E, f"{float(POWER)}")
        w.set(SOC_E, f"{float(stop)}")
        w.set("sensor.ecco_config_maximum_grid_charge_power", "8000")
        w.set(ARMED, "off")
        w.set(LAST, "")
        w.set("input_boolean.ecco_free_power_schedule_armed", "off")
        w.set("input_boolean.ecco_plan_overrides_enabled", "on")
        w.set("input_boolean.ecco_plan_defaults_seeded", "on")
        for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320,
                     "cut_reserve": 80}.items():
            w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
        self.pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
        w.set(OWNER, "unavailable" if owner is None else f"{float(owner)}")
        self.ha = self.pw.ha
        self._boot_hooks()
        self.ha.start()
        w.run_until(T0 + 60)
        w.set(ARMED, "on")                               # armed at T0 + 1 min: its last_changed is earlier than the start

    # -- Home Assistant lifecycle ----------------------------------------------------------------------------------------
    def _pkgs(self):
        pkgs = [yaml.safe_load(t) for t in ((DUMP_TEXT, PLAN_TEXT, GUARD_TEXT) if self.install_plan else (DUMP_TEXT, GUARD_TEXT))]
        if self.mutate:
            self.mutate(pkgs[0])
        return pkgs

    def _boot_hooks(self):
        for a in self.ha.automations:
            a.disabled_triggers |= self.lose

    def restart(self, down_from: float, back_at: float):
        """Home Assistant stops at down_from and starts again at back_at; the dongle keeps running. Every restored entity's last_updated is the
        boot; its last_changed is kept (the model's restore), as in registry/tests/test_ha_r9_missed_runs.py."""
        w = self.w
        w.run_until(down_from)
        self.ha.stop()
        w.run_until(back_at)
        for e in list(w.states):
            w.updated_at[e] = back_at
        self.ha = self.pw.ha = S.HA(w, self._pkgs())
        self._boot_hooks()
        self.ha.start()
        return self

    def until(self, ts: float):
        self.w.run_until(ts)
        return self

    def hold(self, kind: str, minutes: int = 240):
        self.pw.run_script("ecco_plan_override_start", {"kind": kind, "expiry_min": minutes})
        return self

    # -- observations ----------------------------------------------------------------------------------------------------
    def last(self) -> str:
        return self.w.state(LAST)

    def is_armed(self) -> bool:
        return self.w.state(ARMED) == "on"

    def presses(self) -> list:
        return list(self.d.press_log)

    def stop_staged(self) -> list:
        return [v for _t, e, v in self.d.number_log if e == D.D_SOC]

    def untouched(self) -> bool:
        """Nothing staged and nothing pressed. (The script's last step turns the write enable OFF, the safe state, after every outcome.)"""
        return (self.d.press_log == [] and self.d.number_log == [] and self.d.successes == 0
                and not any(s.startswith(("number.", "button.", "switch.turn_on")) for _t, s, _e, _d in self.w.service_log))

    def alerts(self) -> list:
        return [n for n in self.w.notification_log if n[1] == "create" and n[2] == NOTE]

    def started(self) -> int:
        return self.d.successes

    def stale_arm(self):
        """The dongle's write enable left ON before the start (armed from the card and never pressed): the model's own arm flag AND the entity
        Home Assistant reads. Not a service call, so untouched() still means that nothing was staged, armed or pressed BY THE RUN."""
        self.d.arm = True
        self.w.set(D.D_ARM, "on")
        return self

    def write_enable_off(self) -> bool:
        """The write enable at the end of a run: the entity Home Assistant reads AND the dongle model's own flag (the way the reliability suite
        reads it, test_ecco_dump_to_grid_schedule_reliability.py arm_left_on)."""
        return self.w.state(D.D_ARM) == "off" and self.d.arm is False


# ======================================================================================================================
print("[0] static: the composition of the two layers in the merged package")
# ======================================================================================================================
pkg = yaml.safe_load(DUMP_TEXT)
script = pkg["script"]["ecco_dump_to_grid_start_scheduled"]
seq = script["sequence"]
i_vars = next(i for i, a in enumerate(seq) if "variables" in a)
variables = seq[i_vars]["variables"]
i_choose = next(i for i, a in enumerate(seq) if "choose" in a)
choose = seq[i_choose]
branches = choose["choose"]
b_text = [dump(b) for b in branches]
STAGE_OR_PRESS = re.compile(r"number\.set_value|button\.press|switch\.turn_on")


def first(pattern: str) -> int:
    return next((i for i, t in enumerate(b_text) if re.search(pattern, t)), -1)


order = [first(r"plan_hold == 'held'"), first(r"plan_hold != 'clear'"), first(r"plan_reserve < 0"), first(r"requested_stop_soc_raw"),
         first(r"requested_power \| int\(0\)\) < 500"), first(r"requested_stop_soc \| int\(0\)\) < 10"), first(r"dump_to_grid_active")]
check("the start script refuses in this order, one `choose` branch each: override held, override unreadable, reserve unknown, reserve too high, "
      "power range, Stop SOC range, already active", order == list(range(7)), str(order))
check("no refusal branch stages or presses anything (no number.set_value, button.press or switch.turn_on in any `choose` branch)",
      not any(STAGE_OR_PRESS.search(t) for t in b_text), str([i for i, t in enumerate(b_text) if STAGE_OR_PRESS.search(t)]))
default = choose.get("default", [])
check("the staging and the press sit only in the `default` branch: the three staged numbers, the arm, and exactly one press",
      len(calls(default, "number.set_value")) == 3 and len(calls(default, "switch.turn_on")) == 1 and len(calls(default, "button.press")) == 1)
check("the script reads the plan's hold and reserve into variables BEFORE its `choose` (read once; never re-read after a refusal check)",
      i_vars < i_choose and "sensor.ecco_plan_export_hold" in variables["plan_hold"] and "sensor.ecco_plan_effective_reserve" in variables["plan_reserve"])
stop_calls = [c for c in calls(default, "number.set_value") if c["target"]["entity_id"] == D.D_SOC]
check("the Stop SOC the script stages is the RAISED value: requested_stop_soc is the larger of the request and the rounded-up reserve, staged by "
      "number.set_value, and confirmed against requested_stop_soc in the wait and in the pre-press check (never the raw request)",
      "| max" in variables["requested_stop_soc"] and "plan_reserve" in variables["requested_stop_soc"] and "stop_soc | int(25)" in variables["requested_stop_soc"]
      and len(stop_calls) == 1 and stop_calls[0]["data"]["value"] == "{{ requested_stop_soc }}"
      and dump(default).count("== (requested_stop_soc | float(-2))") == 2)
check("the plan sensors the script reads are defined by the plan helper package it depends on",
      all(e.split(".")[1] in PLAN_TEXT for e in (HOLD, EFF)))

fire = next(a for a in pkg["automation"] if a["id"] == "ecco_dump_to_grid_schedule_fire")
rec = next(a for a in pkg["automation"] if a["id"] == "ecco_dump_to_grid_schedule_startup_recovery")
fire_choose = next(a for a in fire["actions"] if "choose" in a)["choose"]
f_text = [dump(b) for b in fire_choose]


def fire_idx(needle: str) -> int:
    return next((i for i, t in enumerate(f_text) if needle in t), -1)


i_ready, i_missed, i_wd, i_start = (fire_idx('"id": "readiness"'), fire_idx('"{{ missed_run }}"'), fire_idx('"{{ not missed_run }}"'), fire_idx('"id": "start"'))
check("the fire automation lists the missed-run record BEFORE the watchdog's start: readiness, missed, watchdog start, on-time start",
      -1 not in (i_ready, i_missed, i_wd, i_start) and i_ready < i_missed < i_wd < i_start, str((i_ready, i_missed, i_wd, i_start)))
callers = [i for i, b in enumerate(fire_choose) if calls(b, SCRIPT)]
check("the schedule script is called from exactly two branches of the fire automation: the watchdog's not-missed branch and the on-time start",
      callers == [i_wd, i_start], str(callers))
check("the missed branch calls neither the schedule script nor any staging or press service; it records, alerts and disarms",
      not calls(fire_choose[i_missed], SCRIPT) and not STAGE_OR_PRESS.search(f_text[i_missed])
      and len(calls(fire_choose[i_missed], "persistent_notification.create")) == 1 and len(calls(fire_choose[i_missed], "input_boolean.turn_off")) == 1)
rec_actions = {d["action"] for d in walk(rec) if "action" in d}
check("the startup recovery starts nothing: no call of the schedule script, no staging, no press (only helper writes, the write-enable OFF and notifications)",
      not calls(rec, SCRIPT) and rec_actions <= {"input_text.set_value", "input_boolean.turn_off", "switch.turn_off", "persistent_notification.create"},
      str(sorted(rec_actions)))
others = [p.name for p in PKGS.glob("*.yaml") if p.name != "ecco_dump_to_grid_schedule.yaml"
          and re.search(r"action:\s*script\.ecco_dump_to_grid_start_scheduled", p.read_text(encoding="utf-8"))]
check("no other package calls the schedule script as an action (the two callers above are the only ones)", others == [], str(others))

# ======================================================================================================================
print("\n[1] (c) an on-time run with no override starts exactly as before")
# ======================================================================================================================
for owner, stop in ((30.0, 40), (40.0, 40)):
    x = Combo(owner=owner, stop=stop).until(ST + 400)
    check(f"owner reserve {owner:g}, requested Stop SOC {stop}: one press, started, staged {POWER} W / Stop SOC {stop} (nothing raised), STARTED OK, disarmed, no alert",
          x.started() == 1 and len(x.presses()) == 1 and getattr(x.d, 'gate_values', (0, 0))[:2] == (POWER, stop) and x.stop_staged() == [stop]
          and x.last().startswith("STARTED OK") and "raised" not in x.last() and not x.is_armed() and x.alerts() == [],
          f"{x.started()} {x.presses()} {getattr(x.d, 'gate_values', None)} {x.stop_staged()} {x.last()!r} {x.alerts()}")
check("the on-time start happens at the start time (inside a minute)", abs(x.d.started_at - ST) < 60, str(x.d.started_at - ST))

# ======================================================================================================================
print("\n[2] (a) a missed run after a Home Assistant restart is refused even when no override is active")
# ======================================================================================================================
for nm, mut, lose, back in (("recovery and watchdog", None, (), ST + 30),
                            ("recovery only (watchdog trigger lost)", None, ("watchdog",), ST + 30),
                            ("watchdog only (no recovery automation)", drop_automation("_startup_recovery"), (), ST + 30),
                            ("recovery and watchdog, back later in the window", None, (), ST + 600)):
    x = Combo(mutate=mut, lose=lose)
    check(f"{nm}: before the restart the plan reads clear and the reserve is known (no override at all)",
          x.w.state(HOLD) == "clear" and float(x.w.state(EFF)) >= 0, f"{x.w.state(HOLD)} {x.w.state(EFF)}")
    x.restart(ST - 120, back).until(ST + DURATION * 60 + 600)
    check(f"{nm}: HA down from {ST - 120 - T0:.0f} s to {back - T0:.0f} s after the first boot (the start fell in the downtime): nothing staged, nothing pressed, "
          "MISSED recorded, alerted, disarmed",
          x.untouched() and x.last() == MISSED_TEXT and not x.is_armed() and any("was missed" in n[3] for n in x.alerts()),
          f"{x.presses()} {x.last()!r} {x.is_armed()} {x.alerts()}")
x = Combo().restart(ST - 120, ST + DURATION * 60 + 300).until(ST + DURATION * 60 + 900)
check("HA back only after the window ended: MISSED recorded, nothing staged or pressed, disarmed", x.untouched() and x.last().startswith("MISSED") and not x.is_armed(), x.last())
x = Combo().restart(ST - 120, ST + 30).until(ST + 7200)
check("the missed run is never started later either: still nothing staged or pressed two hours after the start",
      x.untouched() and x.last().startswith("MISSED"), f"{x.presses()} {x.last()!r}")

# ======================================================================================================================
print("\n[3] (b) an active Hold battery / Skip tonight / Prepare for power cut refuses an on-time run")
# ======================================================================================================================
for kind in KINDS:
    x = Combo()
    x.until(T0 + 120).hold(kind)
    check(f"{kind}: the plan reads held", x.w.state(HOLD) == "held", x.w.state(HOLD))
    x.until(ST + 400)
    check(f"{kind}: the on-time run is refused: nothing staged, nothing pressed, OVERRIDE_ACTIVE, one alert, the schedule disarmed",
          x.untouched() and x.last().startswith("BLOCKED - a Hold battery") and "OVERRIDE_ACTIVE" in x.last()
          and len(x.alerts()) == 1 and "OVERRIDE_ACTIVE" in x.w.notifications.get(NOTE, {}).get("message", "") and not x.is_armed(),
          f"{x.presses()} {x.last()!r} {x.alerts()} {x.is_armed()}")
x = Combo()
x.until(T0 + 120).hold("hold_battery")
x.until(ST - 60)
x.pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
x.until(ST + 400)
check("control: the same run with the Hold battery cancelled before the start starts (the refusal above is the override's, not the harness's)",
      x.started() == 1 and x.last().startswith("STARTED OK") and x.w.state(HOLD) == "clear", f"{x.started()} {x.last()!r} {x.w.state(HOLD)}")

# ======================================================================================================================
print("\n[4] (d) the staged Stop SOC is raised to the effective reserve and never lowered")
# ======================================================================================================================
for owner, stop, want in ((55.0, 40, 55), (62.6, 40, 63), (40.0, 40, 40), (30.0, 40, 40), (55.0, 70, 70), (75.0, 60, 75)):
    x = Combo(owner=owner, stop=stop).until(ST + 400)
    check(f"owner reserve {owner:g}, requested Stop SOC {stop}: staged {want} (the larger of the request and the effective reserve, a whole percent), started, never below the request",
          x.started() == 1 and x.stop_staged() == [want] and getattr(x.d, 'gate_values', (0, 0, 0))[1] == want and want >= stop and x.last().startswith("STARTED OK")
          and x.d.gate_values[0] == POWER,
          f"{x.started()} {x.stop_staged()} {getattr(x.d, 'gate_values', None)} {x.last()!r}")
x = Combo(owner=55.0, stop=40).until(ST + 400)
check("the result the owner reads names the Stop SOC that was staged", "Stop SOC 55%" in x.last() and x.last().startswith("STARTED OK"), x.last())

# ======================================================================================================================
print("\n[5] (e) an unreadable override record or reserve refuses (fail closed): nothing staged, nothing pressed")
# ======================================================================================================================
x = Combo(owner=None)
x.until(ST + 400)
check("the owner's reserve cannot be read: RESERVE_UNKNOWN, refused", x.untouched() and "RESERVE_UNKNOWN" in x.last() and x.last().startswith("BLOCKED") and len(x.alerts()) == 1,
      f"{x.last()!r} {x.presses()}")
x = Combo()
x.w.set(EXP["skip_tonight"], "unavailable")
x.until(ST + 400)
check("an override record is unavailable: OVERRIDE_UNREADABLE, refused", x.untouched() and "OVERRIDE_UNREADABLE" in x.last() and len(x.alerts()) == 1,
      f"{x.last()!r} {x.presses()} {x.w.state(HOLD)}")
x = Combo(install_plan=False)
x.until(ST + 400)
check("the plan helper package is not installed (the sensors do not exist): OVERRIDE_UNREADABLE, refused", x.untouched() and "OVERRIDE_UNREADABLE" in x.last(), f"{x.last()!r}")
x = Combo(owner=95.0, stop=40)
x.until(ST + 400)
check("a reserve with no room under the 90 percent Stop SOC limit: RESERVE_TOO_HIGH, refused", x.untouched() and "RESERVE_TOO_HIGH" in x.last() and len(x.alerts()) == 1, f"{x.last()!r}")

# ======================================================================================================================
print("\n[6] (f) the watchdog rescue and the startup recovery obey (a) and (b)")
# ======================================================================================================================
x = Combo(owner=55.0, stop=40, lose=("start",)).until(ST + 400)
check("unchanged: the on-time trigger lost, nothing wrong: the watchdog starts the run (a start that fell while Home Assistant ran), with its alert, "
      "and the staged Stop SOC is the raised one",
      x.started() == 1 and x.stop_staged() == [55] and getattr(x.d, 'gate_values', (0, 0))[:2] == (POWER, 55) and x.last().startswith("STARTED OK")
      and any("start was missed" in n[3] for n in x.alerts()) and not x.is_armed(), f"{x.started()} {x.stop_staged()} {x.last()!r} {x.alerts()}")
for kind in KINDS:
    x = Combo(lose=("start",))
    x.until(T0 + 120).hold(kind)
    x.until(ST + 400)
    check(f"watchdog rescue, {kind} active: refused by the script (OVERRIDE_ACTIVE), nothing staged, nothing pressed, disarmed",
          x.untouched() and "OVERRIDE_ACTIVE" in x.last() and not x.is_armed(), f"{x.presses()} {x.last()!r} {x.is_armed()}")
x = Combo(owner=None, lose=("start",)).until(ST + 400)
check("watchdog rescue, the reserve unreadable: refused (RESERVE_UNKNOWN), nothing staged, nothing pressed", x.untouched() and "RESERVE_UNKNOWN" in x.last(), f"{x.last()!r}")
for kind in KINDS:
    for nm, mut, lose in (("recovery only", None, ("start", "watchdog")), ("watchdog only", drop_automation("_startup_recovery"), ())):
        x = Combo(mutate=mut, lose=lose)
        x.until(T0 + 120).hold(kind)
        x.restart(ST - 120, ST + 30).until(ST + DURATION * 60 + 600)
        check(f"missed run AND {kind} active ({nm}): not started; recorded as MISSED (the missed-run guard answers first), nothing staged or pressed, disarmed",
              x.untouched() and x.last().startswith("MISSED") and not x.is_armed(), f"{x.presses()} {x.last()!r}")
x = Combo()
x.until(T0 + 120).hold("hold_battery")
x.restart(ST - 120, ST + 30)
x.until(ST + 200)
x.pw.run_script("ecco_plan_override_cancel", {"kind": "hold_battery"})
x.until(ST + DURATION * 60 + 600)
check("an override that ends after the restart does not rescue a missed run (nothing staged or pressed at the end of the window)",
      x.untouched() and x.last().startswith("MISSED"), f"{x.presses()} {x.last()!r} {x.w.state(HOLD)}")
x = Combo(lose=("start", "watchdog"))
x.restart(ST - 120, ST + 30).until(ST + DURATION * 60 + 600)
check("recovery only, no override: the recovery alone never starts a missed run", x.untouched() and x.last() == MISSED_TEXT, f"{x.presses()} {x.last()!r}")

# ======================================================================================================================
print("\n[7] mutation: each composition property is load-bearing (the cases above catch its removal)")
# ======================================================================================================================


def m_skip_missed_guard(p):
    """R9's guard skipped: a missed run is never `missed`, on the fire automation and on the startup recovery."""
    for a in p["automation"]:
        for act in a["actions"]:
            v = act.get("variables") or {}
            if "missed_run" in v:
                v["missed_run"] = "{{ false }}"


def m_skip_override_guard(p):
    """Stage 3's override guard skipped: neither a held nor an unreadable override refuses."""
    ch = next(a for a in p["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"] if "choose" in a)
    ch["choose"] = [b for b in ch["choose"] if "plan_hold" not in dump(b)]


def m_unraised(p):
    """The raise skipped: the script stages the Stop SOC the owner asked for, not the effective reserve."""
    v = next(a for a in p["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"] if "variables" in a)["variables"]
    v["requested_stop_soc"] = "{{ stop_soc | int(25) }}"


def m_press_first(p):
    """Guard order swapped: the staging and the press come BEFORE the refusals (the `default` becomes the first branch)."""
    ch = next(a for a in p["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"] if "choose" in a)
    ch["choose"].insert(0, {"conditions": [{"condition": "template", "value_template": "{{ true }}"}], "sequence": ch.pop("default", [])})


def both(m1, m2):
    def m(p):
        if m1:
            m1(p)
        if m2:
            m2(p)
    return m


def scen_missed(mut) -> bool:
    ok = True
    for m2, lose in ((None, ("watchdog",)), (drop_automation("_startup_recovery"), ())):
        x = Combo(mutate=both(m2, mut), lose=lose).restart(ST - 120, ST + 30).until(ST + DURATION * 60 + 600)
        ok &= x.untouched() and x.last() == MISSED_TEXT and not x.is_armed()
    return ok


def scen_override(mut) -> bool:
    ok = True
    for kind in KINDS:
        x = Combo(mutate=mut)
        x.until(T0 + 120).hold(kind).until(ST + 400)
        ok &= x.untouched() and "OVERRIDE_ACTIVE" in x.last()
    x = Combo(mutate=mut)
    x.w.set(EXP["skip_tonight"], "unavailable")
    x.until(ST + 400)
    return ok and x.untouched() and "OVERRIDE_UNREADABLE" in x.last()


def scen_raise(mut) -> bool:
    x = Combo(owner=55.0, stop=40, mutate=mut).until(ST + 400)
    return x.started() == 1 and x.stop_staged() == [55] and getattr(x.d, 'gate_values', (0, 0))[1] == 55


for name, mut, scen in (("the missed-run guard skipped (R9)", m_skip_missed_guard, scen_missed),
                        ("the override guard skipped (stage 3)", m_skip_override_guard, scen_override),
                        ("the unraised Stop SOC staged", m_unraised, scen_raise),
                        ("the guards swapped behind the press (an override is refused only after the press)", m_press_first, scen_override)):
    check(f"control: unmutated, the scenario of the mutant '{name}' passes", scen(None))
    check(f"mutant caught: {name}", not scen(mut))

# ======================================================================================================================
print("\n[8] the dongle's write enable reads OFF at the end: refusals (on-time and watchdog), completed starts, the startup recovery")
# ======================================================================================================================
# A refusal stages and presses nothing, so a write enable that was OFF stays OFF whatever the script does at the end: the end state proves nothing
# unless the write enable is ON when the run begins (armed from the card and never pressed, say). Each case below leaves it ON first, checks that it
# is ON just before the start, and requires it OFF afterwards: the package's own last step ("the write enable always ends off"), not the dongle.
PATHS = (("on-time start", ()), ("watchdog rescue (on-time trigger lost)", ("start",)))


def hold_of(kind: str):
    return lambda x: x.until(T0 + 120).hold(kind)


REFUSALS = (("Hold battery active", {}, hold_of("hold_battery"), "OVERRIDE_ACTIVE"),
            ("Skip tonight active", {}, hold_of("skip_tonight"), "OVERRIDE_ACTIVE"),
            ("Prepare for power cut active", {}, hold_of("prepare_power_cut"), "OVERRIDE_ACTIVE"),
            ("an override record unavailable", {}, lambda x: x.w.set(EXP["skip_tonight"], "unavailable"), "OVERRIDE_UNREADABLE"),
            ("the plan helper package not installed", {"install_plan": False}, lambda x: None, "OVERRIDE_UNREADABLE"),
            ("the owner's reserve unreadable", {"owner": None}, lambda x: None, "RESERVE_UNKNOWN"),
            ("a reserve with no room under the 90 percent limit", {"owner": 95.0}, lambda x: None, "RESERVE_TOO_HIGH"))
for path, lose in PATHS:
    for label, kw, prep, code in REFUSALS:
        x = Combo(lose=lose, **kw)
        prep(x)
        x.stale_arm().until(ST - 30)
        before = x.w.state(D.D_ARM)
        x.until(ST + 400)
        check(f"{path}, {label}: refused ({code}), the write enable left ON before the start reads OFF at the end (the dongle's switch and its model), nothing staged or pressed",
              before == "on" and code in x.last() and x.untouched() and x.write_enable_off(),
              f"before={before} {x.last()!r} switch={x.w.state(D.D_ARM)} model={x.d.arm} {x.presses()}")
for path, lose in PATHS:
    for stale in (False, True):
        x = Combo(owner=55.0, stop=40, lose=lose)
        if stale:
            x.stale_arm()
        x.until(ST + 400)
        check(f"{path}{', the write enable left ON beforehand' if stale else ''}: after a completed start (Stop SOC raised to 55, Dump to Grid active, STARTED OK) the write enable reads OFF",
              x.started() == 1 and x.stop_staged() == [55] and x.w.state(D.D_ACTIVE) == "on" and x.last().startswith("STARTED OK") and x.write_enable_off(),
              f"{x.started()} {x.stop_staged()} {x.w.state(D.D_ACTIVE)} {x.last()!r} switch={x.w.state(D.D_ARM)} model={x.d.arm}")
for nm, lose in (("recovery and watchdog", ()), ("recovery only (watchdog trigger lost)", ("watchdog",))):
    x = Combo(lose=lose).stale_arm()
    x.restart(ST - 120, ST + 30).until(ST + DURATION * 60 + 600)
    check(f"{nm}: a missed run after a restart with the write enable left ON: the startup recovery turns it OFF, MISSED recorded, nothing staged, nothing pressed",
          x.untouched() and x.last() == MISSED_TEXT and not x.is_armed() and x.write_enable_off(),
          f"{x.last()!r} {x.is_armed()} switch={x.w.state(D.D_ARM)} model={x.d.arm} {x.presses()}")

# ======================================================================================================================
print("\n[9] the plan's hold reads unavailable, junk or empty (states the plan helper package never produces): fail closed")
# ======================================================================================================================
# The sensor is read through force(): the real package gives only held / unknown / clear. The script refuses anything but exactly `clear`
# (OVERRIDE_UNREADABLE), so a sensor that is unavailable, returns a junk text or an empty state never lets a start through.
JUNK = (("unavailable", "unavailable"), ("a junk text", "banana"), ("the empty state", ""), ("a near miss of clear", "Clear"))
for path, lose in PATHS:
    for label, val in JUNK:
        x = Combo(lose=lose)
        force(x, HOLD, val).until(ST + 400)
        check(f"{path}, the plan hold reads {label}: refused (BLOCKED, OVERRIDE_UNREADABLE, the state shown), nothing staged, armed or pressed, alerted, the schedule disarmed",
              x.w.state(HOLD) == val and x.last().startswith("BLOCKED - the plan override records cannot be read") and "OVERRIDE_UNREADABLE" in x.last()
              and f"({val})" in x.last() and x.untouched() and x.write_enable_off() and not x.is_armed()
              and "OVERRIDE_UNREADABLE" in x.w.notifications.get(NOTE, {}).get("message", ""),
              f"{x.w.state(HOLD)!r} {x.last()!r} {x.presses()} {x.is_armed()} {x.alerts()}")
for path, lose in PATHS:
    x = Combo(lose=lose).stale_arm()
    force(x, HOLD, "j" * 200).until(ST + 400)
    check(f"{path}, the plan hold reads an over-long junk text (200 characters: the refusal text then does not fit the 255-character result helper in the interpreter's model, so the safety outcome "
          "alone is asserted): refused, nothing staged, armed or pressed, the write enable left ON beforehand reads OFF, the schedule disarmed",
          x.untouched() and x.write_enable_off() and not x.is_armed(), f"{x.last()!r} {x.presses()} {x.is_armed()} switch={x.w.state(D.D_ARM)}")
for label, val in JUNK:
    for nm, mut, lose in (("recovery only", None, ("start", "watchdog")), ("watchdog only", drop_automation("_startup_recovery"), ())):
        x = Combo(mutate=mut, lose=lose)
        x.restart(ST - 120, ST + 30)
        force(x, HOLD, val).until(ST + DURATION * 60 + 600)
        check(f"missed run AND the plan hold reads {label} ({nm}): not started; recorded as MISSED (the missed-run guard answers first), nothing staged or pressed, disarmed",
              x.untouched() and x.last() == MISSED_TEXT and not x.is_armed(), f"{x.presses()} {x.last()!r}")
x = Combo().restart(ST - 400, ST - 300).until(ST + 400)
check("control: a restart that does NOT miss the start (Home Assistant back five minutes before it) starts the run on time, as before",
      x.started() == 1 and x.last().startswith("STARTED OK") and not x.is_armed(), f"{x.started()} {x.last()!r} {x.is_armed()}")
for label, val in JUNK:
    x = Combo().restart(ST - 400, ST - 300)
    force(x, HOLD, val).until(ST + 400)
    check(f"after a restart that does not miss the start, the plan hold reads {label}: the on-time start is still refused (OVERRIDE_UNREADABLE), nothing staged or pressed, disarmed",
          "OVERRIDE_UNREADABLE" in x.last() and x.untouched() and not x.is_armed(), f"{x.last()!r} {x.presses()} {x.is_armed()}")

# ======================================================================================================================
print("\n[10] the raise rounds UP (ceil), never down, never lowers: fractions forced onto the effective reserve")
# ======================================================================================================================
# The plan helper's effective reserve sensor publishes WHOLE numbers today (it rounds), so a fraction cannot occur with the real producer. These
# cases are defence in depth on the consumer: the start script itself rounds up (62.4 -> 63) and keeps the request when the reserve is lower.
CEIL = (("62.4", 40, 63), ("62.0", 40, 62), ("62.01", 40, 63), ("62.6", 40, 63), ("40.2", 40, 41), ("20.0", 40, 40), ("20.4", 40, 40),
        ("70.0", 70, 70), ("89.2", 40, 90), ("90.0", 40, 90))
for path, lose in PATHS:
    for txt, stop, want in CEIL:
        x = Combo(owner=40.0, stop=stop, lose=lose)
        force(x, EFF, txt)
        x.d.soc = 95.0                                    # the model's gate refuses a Stop SOC at or above the battery SOC
        x.until(ST + 400)
        check(f"{path}, effective reserve {txt} (a fraction on the sensor; the producer publishes whole numbers today, so this is defence in depth on the consumer), request {stop}: "
              f"staged {want} (rounded UP, never down, never below the request), started",
              x.w.state(EFF) == txt and x.started() == 1 and x.stop_staged() == [want] and getattr(x.d, 'gate_values', (0, 0, 0))[1] == want
              and want >= stop and x.last().startswith("STARTED OK") and f"Stop SOC {want}%" in x.last(),
              f"{x.started()} {x.stop_staged()} {getattr(x.d, 'gate_values', None)} {x.last()!r}")
    for txt in ("90.4", "90.01"):
        x = Combo(owner=40.0, stop=40, lose=lose)
        force(x, EFF, txt)
        x.d.soc = 95.0
        x.until(ST + 400)
        check(f"{path}, effective reserve {txt} (a fraction on the sensor; defence in depth): rounded UP it is 91, over the 90 percent limit: RESERVE_TOO_HIGH, nothing staged or pressed",
              "RESERVE_TOO_HIGH" in x.last() and x.untouched() and not x.is_armed(), f"{x.last()!r} {x.stop_staged()} {x.presses()}")
for label, val in (("unavailable", "unavailable"), ("a junk text", "banana"), ("the empty state", "")):
    for path, lose in PATHS:
        x = Combo(lose=lose)
        force(x, EFF, val).until(ST + 400)
        check(f"{path}, the effective reserve reads {label}: RESERVE_UNKNOWN, refused, nothing staged or pressed",
              "RESERVE_UNKNOWN" in x.last() and x.untouched() and not x.is_armed(), f"{x.last()!r} {x.stop_staged()} {x.presses()}")

# ======================================================================================================================
print("\n[11] the pre-press check compares the dongle's Stop SOC readback with the RAISED value, never with the raw request")
# ======================================================================================================================
# The dongle takes every staged number as usual (the model logs it and holds it) but its readback of the Stop SOC then reads `shown`, as a
# dongle that did not keep the raised value would. The script must see that and press nothing.


def read_back(x, entity: str, shown: float):
    orig = x.w.service_handlers["number.set_value"]

    def handler(ent, data):
        orig(ent, data)
        if ent == entity:
            x.w.at(x.w.t + 0.5, lambda: x.w.set(entity, f"{float(shown)}"))
    x.w.service_handlers["number.set_value"] = handler
    return x


x = read_back(Combo(owner=55.0, stop=40), D.D_SOC, 55.0).until(ST + 400)
check("control: the dongle keeps the raised Stop SOC (the readback agrees, 55): the run starts, staged 55",
      x.started() == 1 and x.stop_staged() == [55] and x.last().startswith("STARTED OK"), f"{x.started()} {x.stop_staged()} {x.last()!r}")
for label, shown in (("the raw request (40)", 40.0), ("a value between the request and the raised one (45)", 45.0), ("a value above the raised one (60)", 60.0)):
    x = read_back(Combo(owner=55.0, stop=40), D.D_SOC, shown).until(ST + 900)
    check(f"the dongle's Stop SOC readback reads {label}, not the raised 55: never pressed, the raised 55 staged on every attempt, FAILED TO START at the end of the retries, alerted, write enable OFF",
          x.presses() == [] and x.started() == 0 and len(x.stop_staged()) >= 2 and set(x.stop_staged()) == {55}
          and x.last().startswith("FAILED TO START") and len(x.alerts()) >= 1 and x.write_enable_off(),
          f"{x.presses()} {x.started()} {x.stop_staged()[:3]} {x.last()!r} {x.alerts()}")

# ======================================================================================================================
print("\n[12] mutation: the gaps closed above (each is caught by the running cases of its own section)")
# ======================================================================================================================


def script_seq(p):
    return p["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"]


def edit_template(p, old: str, new: str, must: str = ""):
    """Replace `old` (found once) by `new` inside exactly one `value_template` of the start script that also contains `must`."""
    hits = [d for d in list(walk(script_seq(p))) if isinstance(d.get("value_template"), str) and old in d["value_template"] and must in d["value_template"]]
    assert len(hits) == 1 and hits[0]["value_template"].count(old) == 1, (old, len(hits))
    hits[0]["value_template"] = hits[0]["value_template"].replace(old, new)


def m_no_final_we_off(p):
    """The start script's last step, the write enable turned OFF after every outcome, removed."""
    s = script_seq(p)
    off = [i for i, a in enumerate(s) if a.get("action") == "switch.turn_off"]
    assert len(off) == 1, off
    del s[off[0]]


def m_unavailable_passes(p):
    """An `unavailable` plan hold is not treated as unreadable."""
    edit_template(p, "plan_hold != 'clear'", "plan_hold != 'clear' and plan_hold != 'unavailable'")


def m_unknown_only(p):
    """Only an `unknown` plan hold is treated as unreadable (unavailable, junk and empty pass)."""
    edit_template(p, "plan_hold != 'clear'", "plan_hold == 'unknown'")


def m_round_not_ceil(p):
    """The reserve rounded to the nearest percent instead of up."""
    v = next(a for a in script_seq(p) if "variables" in a)["variables"]
    assert "round(0, 'ceil')" in v["requested_stop_soc"]
    v["requested_stop_soc"] = v["requested_stop_soc"].replace("round(0, 'ceil')", "round(0)")


def m_prepress_raw(p):
    """The pre-press check compares the Stop SOC readback with the raw request (at least), not the raised value."""
    edit_template(p, "== (requested_stop_soc | float(-2))", ">= (requested_stop_soc_raw | float(-2))", must="ecco_dump_to_grid_schedule_armed.last_changed")


def m_recovery_keeps_arm(p):
    """The startup recovery no longer turns a write enable left ON off."""
    a = next(a for a in p["automation"] if a["id"].endswith("_startup_recovery"))
    n = len(a["actions"])
    a["actions"] = [act for act in a["actions"] if not calls(act, "switch.turn_off")]
    assert len(a["actions"]) == n - 1


def scen_write_enable(mut) -> bool:
    ok = True
    for lose in ((), ("start",)):
        for kw, prep in (({}, hold_of("hold_battery")), ({"owner": 95.0}, lambda x: None), ({"owner": None}, lambda x: None)):
            x = Combo(mutate=mut, lose=lose, **kw)
            prep(x)
            x.stale_arm().until(ST + 400)
            ok &= x.untouched() and x.write_enable_off()
    return ok


def scen_hold_state(mut) -> bool:
    ok = True
    for lose, val in (((), "unavailable"), (("start",), "unavailable"), ((), "banana"), (("start",), "banana"), ((), ""), (("start",), "")):
        x = Combo(mutate=mut, lose=lose)
        force(x, HOLD, val).until(ST + 400)
        ok &= x.untouched() and "OVERRIDE_UNREADABLE" in x.last()
    return ok


def scen_ceil(mut) -> bool:
    ok = True
    for txt, want in (("62.4", 63), ("62.0", 62), ("20.0", 40), ("89.2", 90)):
        x = Combo(owner=40.0, stop=40, mutate=mut)
        force(x, EFF, txt)
        x.d.soc = 95.0
        x.until(ST + 400)
        ok &= x.started() == 1 and x.stop_staged() == [want]
    x = Combo(owner=40.0, stop=40, mutate=mut)
    force(x, EFF, "90.4")
    x.until(ST + 400)
    return ok and x.untouched() and "RESERVE_TOO_HIGH" in x.last()


def scen_prepress(mut) -> bool:
    ok = read_back(Combo(owner=55.0, stop=40, mutate=mut), D.D_SOC, 55.0).until(ST + 400).started() == 1
    for shown in (40.0, 45.0):
        x = read_back(Combo(owner=55.0, stop=40, mutate=mut), D.D_SOC, shown).until(ST + 900)
        ok &= x.presses() == [] and x.started() == 0
    return ok


def scen_recovery_arm(mut) -> bool:
    x = Combo(mutate=mut, lose=("watchdog",)).stale_arm()
    x.restart(ST - 120, ST + 30).until(ST + DURATION * 60 + 600)
    return x.untouched() and x.last() == MISSED_TEXT and x.write_enable_off()


for name, mut, scen in (("the final write-enable OFF removed from the start script (refusals leave a write enable that was ON, ON)", m_no_final_we_off, scen_write_enable),
                        ("an unavailable plan hold let through", m_unavailable_passes, scen_hold_state),
                        ("only an unknown plan hold refused (unavailable, junk and empty let through)", m_unknown_only, scen_hold_state),
                        ("the reserve rounded to nearest instead of up", m_round_not_ceil, scen_ceil),
                        ("the pre-press Stop SOC check against the raw request", m_prepress_raw, scen_prepress),
                        ("the startup recovery no longer turns a write enable left ON off", m_recovery_keeps_arm, scen_recovery_arm)):
    check(f"control: unmutated, the scenario of the mutant '{name}' passes", scen(None))
    check(f"mutant caught: {name}", not scen(mut))

check("no helper refused a write (the plan helper range checks of the model)", P.PlanWorld.rejected_all == [], str(P.PlanWorld.rejected_all[:3]))

# ======================================================================================================================
print("")
if FAILURES:
    print(f"{len(FAILURES)} FAILED, {PASSES} passed")
    for f in FAILURES:
        print("  FAILED:", f)
    sys.exit(1)
print(f"All {PASSES} R9 + stage 3 composition checks passed.")
print("These prove the two layers against a model of the dongle on a virtual clock; no Home Assistant restart, no live helper restore and no hardware was involved.")
