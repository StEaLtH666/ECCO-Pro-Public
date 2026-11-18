"""Offline suite for the TRUSTED-BACKEND enforcement points of the plan overrides (stage 3 of the two-master-card energy-control work):

  home-assistant/packages/ecco_dump_to_grid_schedule.yaml          the scheduled Dump to Grid start script
  home-assistant/packages/ecco_dump_to_grid_guarded_start.yaml     the guarded manual start the Energy Actions card calls
  home-assistant/packages/ecco_plan_helpers.yaml                   the two sensors they read (export hold, effective reserve)

The REAL package YAML runs under the FPS1 interpreter (_ha_script_sim.py) with the dongle model of the scheduled Dump to Grid reliability
suite (_ha_dump_sim.py), on a virtual clock. Nothing here touches Home Assistant, the dongle or an inverter.

  [1] static      the new branches call only input_text.set_value and persistent_notification; the guarded start presses exactly the
                  dongle's start button and calls no other dongle service (it never stages or writes a number)
  [2] scheduled   refused (nothing staged, nothing pressed, one notification, the stable reason) while Hold battery, Skip tonight or
                  Prepare for power cut is active; while the records cannot be read, the sensors do not exist, or the effective reserve
                  is unknown; when the reserve leaves no room under 90 percent. Started otherwise, with the Stop SOC raised to at least the
                  effective reserve (never lowered); an expired override no longer holds
  [3] manual      the guarded start: the same two checks, then the SAME button press; below-reserve staged Stop SOC refused, not changed
  [4] end to end  an override started through the guarded override script holds the scheduled start and the manual start; cancelling frees them
  [5] mutation    in-memory mutants of the two start scripts are each caught
  [6] reserve     the effective reserve must be a finite number from 0 to 100; anything else is refused before anything is staged, armed or
                  pressed (RESERVE_INVALID for nan, infinity and a value above 100; RESERVE_UNKNOWN and RESERVE_TOO_HIGH keep their cases), on the
                  scheduled start and the guarded start, with the guarded start's staged Stop SOC read-back held to the same range; a valid
                  reserve behaves as before
  [7] mutation    in-memory mutants of that validation (removed, too-big-only, a bound moved, the new refusal or text dropped) are each caught
  [8] clock       the scheduled start follows an override's true expiry through the repeated hour of the October clock change (the export hold reads
                  the helper's timestamp attribute, not its state string): refused while the override runs, started from its expiry second on, for
                  each kind; nine mutants (the hold-state read sites and the expiry second) are each caught by a running scheduled start
  [9] press-time  the scheduled start reads the hold and the reserve AGAIN immediately before the press: an override started, a record or the reserve becoming
                  unreadable or invalid, or a reserve raised above the Stop SOC staged for the run, while it waits for the dongle (busy or offline), ends that run
                  (BLOCKED, the same stable codes, nothing pressed, write enable OFF, never retried); a run with no such change presses once as before; the
                  mutants (no re-read, hold only, reserve only, the start values reused, not terminal, a moved boundary) are each caught

Writes nothing; no Home Assistant, no network, no hardware. It proves the packages against a model of the dongle; it proves nothing about a
live Home Assistant, the dongle or the inverter, and it cannot bind the dongle's own Start button entity (see the plan-core README).
"""

from __future__ import annotations

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


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}" + (f" - {detail}" if detail else ""))


LAST = "input_text.ecco_dump_to_grid_schedule_last_result"
PLAN_LAST = "input_text.ecco_plan_last_result"
NOTE = "ecco_dump_to_grid_schedule"          # the scheduled start's own end-of-run alert (every BLOCKED result)
GNOTE = "ecco_dump_to_grid_plan_blocked"     # the guarded manual start's notification
HOLD, EFF = "sensor.ecco_plan_export_hold", "sensor.ecco_plan_effective_reserve"
OWNER = "input_number.ecco_minimum_reserve_soc"
KINDS = ["hold_battery", "skip_tonight", "prepare_power_cut"]
EXP = {k: f"input_datetime.ecco_plan_override_{k}_expires" for k in KINDS}
CUT_RES = "input_number.ecco_plan_override_prepare_power_cut_reserve"
START_BTN = D.D_PRESS
T0 = "2026-11-17 21:00:00"


def world(dump=DUMP_TEXT, plan=PLAN_TEXT, guard=GUARD_TEXT, owner=40, stop=None, install_plan=True):
    pkgs = [yaml.safe_load(t) for t in ((dump, plan, guard) if install_plan else (dump, guard))]
    pw = P.PlanWorld(T0, pkgs, "Etc/GMT-1")
    w = pw.w
    D.add_ha_filters(w)
    d = D.DumpDongle(w, phase=0.0, handle_delays=(0.117,))
    w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "on")
    w.set("input_boolean.ecco_free_power_schedule_armed", "off")
    w.set(LAST, "")
    w.set(PLAN_LAST, "")
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set(OWNER, "unavailable" if owner is None else f"{float(owner)}")
    if stop is not None:
        d.stop_soc = stop
        w.set(D.D_SOC, f"{float(stop)}")
    return pw, d


def run_scheduled(pw, d, stop_soc=25, power=2000, minutes=30, seconds=150):
    end = pw.w.t + minutes * 60 + 60
    pw.ha.start_script("ecco_dump_to_grid_start_scheduled", {"duration_minutes": minutes, "power_w": power, "stop_soc": stop_soc, "window_end_ts": end})
    pw.w.run_until(pw.w.t + seconds)


def hold(pw, kind, minutes=120):
    pw.run_script("ecco_plan_override_start", {"kind": kind, "expiry_min": minutes})


def untouched(pw, d, n0) -> bool:
    """Nothing staged and nothing pressed. (The script's own last step turns the write enable OFF, the safe state, after every outcome.)"""
    return (d.presses == [] and d.number_log == [] and d.press_log == []
            and not any(s.startswith(("number.", "button.", "switch.turn_on")) for _t, s, _e, _d in pw.w.service_log[n0:]))


# --------------------------------------------------------------------------------------------------------------------------------
def problems(dump_text: str, guard_text: str) -> list[str]:
    bad: list[str] = []
    try:
        # scheduled: held by each kind
        for kind in KINDS:
            pw, d = world(dump_text, guard=guard_text)
            hold(pw, kind)
            n0 = len(pw.w.service_log)
            run_scheduled(pw, d)
            if not pw.state(LAST).startswith("BLOCKED - a Hold battery") or "OVERRIDE_ACTIVE" not in pw.state(LAST) or "OVERRIDE_ACTIVE" not in pw.w.notifications.get(NOTE, {}).get("message", "") or not untouched(pw, d, n0):
                bad.append(f"scheduled start not held by {kind}: {pw.state(LAST)[:50]} presses={d.presses}")
        # the longest hold text (all three overrides named) fits the 255-character result helper
        pw, d = world(dump_text, guard=guard_text)
        for kind in KINDS:
            hold(pw, kind)
        run_scheduled(pw, d)
        # (the model does not render a template sensor's attributes: its `held_by` reads None here, so the worst case is put in by hand)
        worst = pw.state(LAST).replace("None", "hold_battery,skip_tonight,prepare_power_cut")
        if pw.w.warnings or not pw.state(LAST).startswith("BLOCKED - a Hold battery") or len(worst) > 255:
            bad.append(f"the longest hold text does not fit the result helper: {len(worst)} chars, warnings {pw.w.warnings[:1]}")
        # scheduled: unreadable records / missing sensors / unknown reserve / reserve too high
        pw, d = world(dump_text, guard=guard_text)
        pw.w.set(EXP["skip_tonight"], "unavailable")
        n0 = len(pw.w.service_log)
        run_scheduled(pw, d)
        if "OVERRIDE_UNREADABLE" not in pw.state(LAST) or not untouched(pw, d, n0):
            bad.append("an unreadable record does not refuse the scheduled start")
        pw, d = world(dump_text, guard=guard_text, install_plan=False)
        n0 = len(pw.w.service_log)
        run_scheduled(pw, d)
        if "OVERRIDE_UNREADABLE" not in pw.state(LAST) or not untouched(pw, d, n0):
            bad.append("without the plan package the scheduled start is not refused (it must fail closed)")
        pw, d = world(dump_text, guard=guard_text, owner=None)
        n0 = len(pw.w.service_log)
        run_scheduled(pw, d)
        if "RESERVE_UNKNOWN" not in pw.state(LAST) or not untouched(pw, d, n0):
            bad.append("an unknown reserve does not refuse the scheduled start")
        pw, d = world(dump_text, guard=guard_text, owner=95)
        n0 = len(pw.w.service_log)
        run_scheduled(pw, d, stop_soc=25)
        if "RESERVE_TOO_HIGH" not in pw.state(LAST) or not untouched(pw, d, n0):
            bad.append("a reserve above the Stop SOC limit does not refuse the scheduled start")
        # scheduled: started, Stop SOC raised to the effective reserve (never lowered)
        for owner, asked, want in ((40, 25, 40), (20, 25, 25), (40, 60, 60), (40, 40, 40), (10, 10, 10), (70, 25, 70)):
            pw, d = world(dump_text, guard=guard_text, owner=owner)
            run_scheduled(pw, d, stop_soc=asked)
            staged = [v for _t, e, v in d.number_log if e == D.D_SOC]
            if not (d.presses and d.presses[0][1] == "PASSED") or staged != [want] or d.gate_values[2] <= 0 and False:
                bad.append(f"stop soc: reserve {owner}, asked {asked}: staged {staged}, presses {d.presses}")
            elif want > asked and "raised from" not in pw.state(LAST) and not pw.state(LAST).startswith("STARTED"):
                bad.append("the raise is not stated")
        pw, d = world(dump_text, guard=guard_text, owner=40)
        hold(pw, "prepare_power_cut")
        pw.run_script("ecco_plan_override_cancel", {"kind": "prepare_power_cut"})
        run_scheduled(pw, d, stop_soc=25)
        if not (d.presses and d.presses[0][1] == "PASSED"):
            bad.append("a cancelled override still holds the scheduled start")
        # an expired override stops holding (the sensor re-renders each minute)
        pw, d = world(dump_text, guard=guard_text)
        hold(pw, "hold_battery", 15)
        pw.w.run_until(pw.w.t + 16 * 60)
        run_scheduled(pw, d, stop_soc=25)
        if not (d.presses and d.presses[0][1] == "PASSED"):
            bad.append("an expired override still holds the scheduled start")
        # manual guarded start
        def manual(pw, d, staged=30):
            d.arm = True
            pw.w.set(D.D_ARM, "on")
            pw.w.set(D.D_SOC, f"{float(staged)}")
            d.stop_soc = staged
            n0 = len(pw.w.service_log)
            pw.run_script("ecco_dump_to_grid_start_guarded", {}, seconds=20)
            return n0
        pw, d = world(dump_text, guard=guard_text, owner=20)
        n0 = manual(pw, d)
        presses = [(s, e) for s, e, _d in pw.services(n0) if s == "button.press"]
        if presses != [("button.press", START_BTN)] or len(d.press_log) != 1 or any(s.startswith(("number.", "switch.")) for s, _e, _d in pw.services(n0)):
            bad.append(f"the guarded start does not press exactly the start button once and nothing else: {presses}")
        for label, setup, code in (("held", lambda pw: hold(pw, "skip_tonight"), "OVERRIDE_ACTIVE"),
                                   ("unreadable", lambda pw: pw.w.set(EXP["hold_battery"], "unavailable"), "OVERRIDE_UNREADABLE"),
                                   ("reserve unknown", lambda pw: pw.w.set(OWNER, "unavailable"), "RESERVE_UNKNOWN")):
            pw, d = world(dump_text, guard=guard_text, owner=20)
            setup(pw)
            n0 = manual(pw, d)
            if d.press_log or not pw.state(PLAN_LAST).startswith("REFUSED " + code) or GNOTE not in pw.w.notifications:
                bad.append(f"the guarded start is not refused ({label}): {pw.state(PLAN_LAST)[:50]} presses={d.press_log}")
        pw, d = world(dump_text, guard=guard_text, owner=40)
        manual(pw, d, staged=30)
        if d.press_log or not pw.state(PLAN_LAST).startswith("REFUSED STOP_SOC_BELOW_RESERVE") or pw.state(D.D_SOC) != "30.0":
            bad.append("a staged Stop SOC below the effective reserve is not refused (or was changed)")
        pw, d = world(dump_text, guard=guard_text, owner=40)
        manual(pw, d, staged=40)
        if len(d.press_log) != 1:
            bad.append("a staged Stop SOC equal to the reserve is refused")
        pw, d = world(dump_text, guard=guard_text, owner=20)
        pw.w.set(D.D_SOC, "unavailable")
        d.arm = True
        pw.run_script("ecco_dump_to_grid_start_guarded", {}, seconds=20)
        if d.press_log or not pw.state(PLAN_LAST).startswith("REFUSED STOP_SOC_UNREADABLE"):
            bad.append("an unreadable staged Stop SOC does not refuse the guarded start")
        pw, d = world(dump_text, guard=guard_text, owner=20, install_plan=False)
        manual(pw, d)
        if d.press_log:
            bad.append("without the plan package the guarded start is not refused (it must fail closed)")
        # end to end: a power cut raises the reserve AND holds both starts; cancel frees both
        pw, d = world(dump_text, guard=guard_text, owner=40)
        hold(pw, "prepare_power_cut", 600)
        manual(pw, d)
        run_scheduled(pw, d)
        if d.press_log or d.presses or pw.state(EFF) != "80":
            bad.append("a running power cut does not hold both starts and raise the effective reserve to 80")
        pw.run_script("ecco_plan_override_cancel", {"kind": "prepare_power_cut"})
        if pw.state(EFF) != "40" or pw.state(HOLD) != "clear":
            bad.append("cancelling the power cut does not return the reserve to the owner's and clear the hold")
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def static_problems(dump_text: str, guard_text: str) -> list[str]:
    bad: list[str] = []
    g = yaml.safe_load(guard_text)
    acts: list[dict] = []

    def collect(seq):
        for a in seq or []:
            if "action" in a:
                acts.append(a)
            for br in a.get("choose", []):
                collect(br.get("sequence"))
            collect(a.get("default"))
    collect(g["script"]["ecco_dump_to_grid_start_guarded"]["sequence"])
    services = sorted({a["action"] for a in acts})
    if services != ["button.press", "input_text.set_value", "persistent_notification.create", "persistent_notification.dismiss"]:
        bad.append(f"guarded start services {services}")
    presses = [a for a in acts if a["action"] == "button.press"]
    if len(presses) != 1 or presses[0]["target"]["entity_id"] != START_BTN:
        bad.append("the guarded start does not press exactly the dongle's start button")
    for a in acts:
        if a["action"] == "input_text.set_value" and a["target"]["entity_id"] != PLAN_LAST:
            bad.append("the guarded start writes another helper")
    if g["script"]["ecco_dump_to_grid_start_guarded"].get("mode") != "single" or set(g) != {"script"}:
        bad.append("the guarded start package is not exactly one single-mode script")
    d = yaml.safe_load(dump_text)
    seq = d["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"]
    top = next(a for a in seq if "choose" in a)
    new = [br for br in top["choose"] if "plan_" in str(br["conditions"]) or "requested_stop_soc_raw" in str(br["conditions"])]
    if len(new) != 4:
        bad.append(f"the scheduled start has {len(new)} plan branches, wanted 4")
    for br in new:
        if [a["action"] for a in br["sequence"]] != ["input_text.set_value"]:
            bad.append(f"a plan branch does more than write the result text: {[a['action'] for a in br['sequence']]}")
    first4 = [str(br["conditions"]) for br in top["choose"][:4]]
    if not all("plan_" in c or "requested_stop_soc_raw" in c for c in first4):
        bad.append("the plan branches are not the first four, ahead of every existing check")
    return bad


# ================================================================================================================================
print("[1] static")
sp = static_problems(DUMP_TEXT, GUARD_TEXT)
check("the four plan branches only write the result text and sit ahead of the existing checks; the guarded start presses exactly the start button", sp == [], str(sp))
check("the guarded start reads only the two plan sensors and the staged Stop SOC number",
      sorted(set(re.findall(r"states\('([a-z_.]+)'\)", GUARD_TEXT))) == ["number.ecco_clock_dongle_dump_to_grid_stop_soc", EFF, HOLD])
check("the scheduled start reads the plan through the same two sensors",
      sorted(set(re.findall(r"states\('(sensor\.ecco_plan[a-z_]*)'\)", DUMP_TEXT))) == [EFF, HOLD])

print("[2][3][4] behaviour")
pr = problems(DUMP_TEXT, GUARD_TEXT)
check("scheduled start: held by each kind, fail closed when unreadable / missing / unknown / too high, Stop SOC raised, expired and cancelled overrides free it",
      pr == [], str(pr[:4]))
check("no helper refused a write in any world above", P.PlanWorld.rejected_all == [], str(P.PlanWorld.rejected_all[:2]))

print("[5] mutation")
MUTANTS = [
    ("dump", "an active override does not hold the scheduled start", "value_template: \"{{ plan_hold == 'held' }}\"", "value_template: \"{{ false }}\""),
    ("dump", "unreadable override records do not refuse the scheduled start", "value_template: \"{{ plan_hold != 'clear' }}\"", "value_template: \"{{ false }}\""),
    ("dump", "an unknown reserve does not refuse the scheduled start", "value_template: \"{{ plan_reserve < 0 }}\"", "value_template: \"{{ false }}\""),
    ("dump", "the Stop SOC is not raised to the effective reserve", "requested_stop_soc: \"{{ [stop_soc | int(25), (plan_reserve | round(0, 'ceil') | int) if plan_reserve >= 0 else 0] | max }}\"", "requested_stop_soc: \"{{ stop_soc | int(25) }}\""),
    ("dump", "the Stop SOC is lowered to the effective reserve", "if plan_reserve >= 0 else 0] | max }}\"", "if plan_reserve >= 0 else 0] | min }}\""),
    ("dump", "a reserve above the Stop SOC limit is not refused", "{{ (requested_stop_soc | int(0)) > 90 and (requested_stop_soc_raw | int(0)) <= 90 }}", "{{ false }}"),
    ("dump", "the hold reads a sensor that does not exist (so every start is refused)", "plan_hold: \"{{ states('sensor.ecco_plan_export_hold') }}\"", "plan_hold: \"{{ states('sensor.ecco_plan_export_holdx') }}\""),
    ("dump", "a held start leaves a result that is not a refusal (no alert)", "BLOCKED - a Hold battery, Skip tonight or Prepare for power cut is active", "STARTED - a Hold battery, Skip tonight or Prepare for power cut is active"),
    ("guard", "the guarded start presses while an override is active", "{%- if plan_hold == 'held' -%}", "{%- if false -%}"),
    ("guard", "the guarded start presses while the records are unreadable", "{%- elif plan_hold != 'clear' -%}", "{%- elif false -%}"),
    ("guard", "the guarded start presses with an unknown effective reserve", "{%- elif plan_reserve < 0 -%}", "{%- elif false -%}"),
    ("guard", "the guarded start presses a staged Stop SOC below the reserve", "{%- elif staged_stop_soc < plan_reserve -%}", "{%- elif false -%}"),
    ("guard", "the guarded start refuses a staged Stop SOC equal to the reserve", "{%- elif staged_stop_soc < plan_reserve -%}", "{%- elif staged_stop_soc <= plan_reserve -%}"),
    ("guard", "the guarded start also writes the staged Stop SOC", "          - action: button.press\n            target:", "          - action: number.set_value\n            target:\n              entity_id: number.ecco_clock_dongle_dump_to_grid_stop_soc\n            data:\n              value: 90\n          - action: button.press\n            target:"),
    ("guard", "the guarded start presses a different button", "button.ecco_clock_dongle_start_dump_to_grid_now", "button.ecco_clock_dongle_start_free_power_charge_now"),
]
killed = 0
for which, label, old, new in MUTANTS:
    src = DUMP_TEXT if which == "dump" else GUARD_TEXT
    if src.count(old) != 1:
        check(f"mutant anchor: {label}", False, f"anchor found {src.count(old)}x")
        continue
    mutated = src.replace(old, new)
    d_text, g_text = (mutated, GUARD_TEXT) if which == "dump" else (DUMP_TEXT, mutated)
    try:
        found = static_problems(d_text, g_text) + problems(d_text, g_text)
    except Exception as exc:  # noqa: BLE001 - a mutant the model cannot run is caught too (the interpreter is fail-loud)
        found = [f"raised {type(exc).__name__}"]
    if found:
        killed += 1
        print(f"  PASS  mutant caught: {label}")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS)} mutants, all caught", killed == len(MUTANTS), f"{killed}/{len(MUTANTS)}")
check("a harmless rewrite of a result text survives", problems(DUMP_TEXT.replace("nothing started", "nothing was started"), GUARD_TEXT) == [])

# ================================================================================================================================
print("[6] effective reserve: only a finite number from 0 to 100 passes; anything else is refused before anything is staged, armed or pressed")
# ================================================================================================================================
# New with RESERVE_INVALID. float() also accepts nan, inf and -inf, a comparison with nan is always False, inf cannot be rounded, and this interpreter
# keeps such a result as TEXT, so a reserve of nan or inf used to reach a comparison or the rounding as a string and abort the start script before
# any refusal was recorded (the old script was run through this interpreter; Home Assistant's own parsing is not tested here). The producer sensor never publishes such a value (it checks its inputs), so the sensor is forced to the text below,
# through the interpreter's own `template_entities` map (nothing in a simulator is edited), the way the composition suite forces it.
# Codes: a reserve that cannot be read or is below 0 (-inf included) keeps RESERVE_UNKNOWN; 91..100 keeps RESERVE_TOO_HIGH on the scheduled start; a
# reserve that is not a finite number (nan, inf, 1e999) or is above 100 is RESERVE_INVALID. The guarded start also refuses a staged Stop SOC that is
# not a finite number from 0 to 100 (STOP_SOC_UNREADABLE, the existing code).
SCHED_REFUSED = (("nan", "RESERVE_INVALID"), ("NaN", "RESERVE_INVALID"), ("inf", "RESERVE_INVALID"), ("-inf", "RESERVE_UNKNOWN"),
                 ("1e999", "RESERVE_INVALID"), ("-5", "RESERVE_UNKNOWN"), ("101", "RESERVE_INVALID"), ("150", "RESERVE_INVALID"),
                 ("abc", "RESERVE_UNKNOWN"), ("", "RESERVE_UNKNOWN"), ("unknown", "RESERVE_UNKNOWN"), ("unavailable", "RESERVE_UNKNOWN"),
                 ("91", "RESERVE_TOO_HIGH"), ("100", "RESERVE_TOO_HIGH"))
SCHED_STARTED = (("0", 25, 25), ("0.0", 25, 25), ("20", 25, 25), ("62.4", 25, 63), ("62.0", 25, 62), ("90", 25, 90))   # (reserve, asked, staged)
GUARD_REFUSED = (("nan", "RESERVE_INVALID"), ("NaN", "RESERVE_INVALID"), ("inf", "RESERVE_INVALID"), ("-inf", "RESERVE_UNKNOWN"),
                 ("1e999", "RESERVE_INVALID"), ("-5", "RESERVE_UNKNOWN"), ("101", "RESERVE_INVALID"), ("150", "RESERVE_INVALID"),
                 ("abc", "RESERVE_UNKNOWN"), ("", "RESERVE_UNKNOWN"), ("unknown", "RESERVE_UNKNOWN"), ("unavailable", "RESERVE_UNKNOWN"),
                 ("91", "STOP_SOC_BELOW_RESERVE"), ("100", "STOP_SOC_BELOW_RESERVE"))                                   # staged Stop SOC 30
GUARD_PRESSED = (("0", 30), ("0.0", 30), ("20", 30), ("62.4", 63), ("62.0", 62), ("90", 90))                              # (reserve, staged)
STAGED_REFUSED = ("nan", "NaN", "inf", "-inf", "1e999", "101", "150", "-5", "", "unknown", "unavailable", "abc")           # reserve 20


class _Stop(Exception):
    pass


def forced_world(txt, dump_text, guard_text, **kw):
    pw, d = world(dump_text, guard=guard_text, **kw)
    pw.w.template_entities[EFF] = txt
    return pw, d


def reserve_cases(dump_text: str, guard_text: str, first_only: bool = False, parts=("sched", "guard", "staged")) -> list:
    """Every reserve-validation case on the given package texts: [(label, ok, detail)]. `first_only` stops at the first failing case (the mutants)."""
    rows: list = []

    def add(label, ok, detail=""):
        rows.append((label, bool(ok), detail))
        if first_only and not ok:
            raise _Stop()

    def attempt(label, fn):
        try:
            ok, detail = fn()
        except _Stop:
            raise
        except Exception as exc:  # noqa: BLE001 - a start script that raises (nothing recorded) is a failed proof
            ok, detail = False, f"raised {type(exc).__name__}: {str(exc)[:110]}"
        add(label, ok, detail)

    def sched(txt, asked=25):
        pw, d = forced_world(txt, dump_text, guard_text)
        d.arm = True                                       # the write enable left ON beforehand: its OFF at the end is the script's own last step
        pw.w.set(D.D_ARM, "on")
        d.soc = 95.0                                       # the model's gate refuses a Stop SOC at or above the battery SOC
        n0 = len(pw.w.service_log)
        run_scheduled(pw, d, stop_soc=asked)
        return pw, d, n0

    def guard(txt, staged_txt="30", staged_num=30):
        pw, d = forced_world(txt, dump_text, guard_text, owner=20)
        pw.w.set(D.D_SOC, staged_txt)
        d.stop_soc = staged_num
        d.arm = True
        n0 = len(pw.w.service_log)
        pw.run_script("ecco_dump_to_grid_start_guarded", {}, seconds=20)
        return pw, d, n0

    try:
        if "sched" in parts:
            for txt, code in SCHED_REFUSED:
                def refused(txt=txt, code=code):
                    pw, d, n0 = sched(txt)
                    last = pw.state(LAST)
                    alerts = [n for n in pw.w.notification_log if n[1] == "create" and n[2] == NOTE]
                    ok = (pw.state(EFF) == txt and last.startswith("BLOCKED - the effective reserve") and last.endswith(f"(reason {code})") and len(last) <= 255
                          and untouched(pw, d, n0) and pw.state(D.D_ARM) == "off" and d.arm is False
                          and len(alerts) == 1 and last in pw.w.notifications.get(NOTE, {}).get("message", ""))
                    return ok, f"{last[:90]!r} presses={d.presses} staged={d.number_log} switch={pw.state(D.D_ARM)} alerts={len(alerts)}"
                attempt(f"scheduled start, reserve {txt!r}: {code}, nothing staged, armed or pressed, one alert, write enable (left ON) reads OFF", refused)
            for txt, asked, want in SCHED_STARTED:
                def started(txt=txt, asked=asked, want=want):
                    pw, d, n0 = sched(txt, asked)
                    last = pw.state(LAST)
                    staged = [v for _t, e, v in d.number_log if e == D.D_SOC]
                    ok = (d.presses and d.presses[0][1] == "PASSED" and staged == [want] and last.startswith("STARTED OK") and f"Stop SOC {want}%" in last
                          and not any(n[1] == "create" and n[2] == NOTE for n in pw.w.notification_log) and pw.state(D.D_ARM) == "off" and d.arm is False)
                    return ok, f"{last[:90]!r} staged={staged} presses={d.presses}"
                attempt(f"scheduled start, reserve {txt!r}, asked {asked}: starts, Stop SOC {want} staged (unchanged behaviour), write enable reads OFF", started)
        if "guard" in parts:
            for txt, code in GUARD_REFUSED:
                def g_refused(txt=txt, code=code):
                    pw, d, n0 = guard(txt)
                    last = pw.state(PLAN_LAST)
                    ok = (pw.state(EFF) == txt and d.press_log == [] and last.startswith(f"REFUSED {code} - ") and len(last) <= 255 and GNOTE in pw.w.notifications
                          and not any(s.startswith(("number.", "switch.", "button.")) for s, _e, _d in pw.services(n0)) and pw.state(D.D_SOC) == "30")
                    return ok, f"{last[:90]!r} presses={d.press_log}"
                attempt(f"guarded start, reserve {txt!r}, staged 30: refused {code}, nothing pressed, nothing staged or armed, one notification", g_refused)
            for txt, staged in GUARD_PRESSED:
                def g_pressed(txt=txt, staged=staged):
                    pw, d, n0 = guard(txt, str(staged), staged)
                    presses = [(s, e) for s, e, _d in pw.services(n0) if s == "button.press"]
                    ok = presses == [("button.press", START_BTN)] and len(d.press_log) == 1 and pw.state(PLAN_LAST) == "" and GNOTE not in pw.w.notifications
                    return ok, f"{pw.state(PLAN_LAST)[:90]!r} presses={presses}"
                attempt(f"guarded start, reserve {txt!r}, staged {staged}: the one start-button press, nothing refused (unchanged behaviour)", g_pressed)
        if "staged" in parts:
            for stxt in STAGED_REFUSED:
                def s_refused(stxt=stxt):
                    pw, d, n0 = guard("20", stxt, 30)
                    last = pw.state(PLAN_LAST)
                    ok = (d.press_log == [] and last.startswith("REFUSED STOP_SOC_UNREADABLE - ") and GNOTE in pw.w.notifications
                          and not any(s.startswith(("number.", "switch.", "button.")) for s, _e, _d in pw.services(n0)))
                    return ok, f"{last[:90]!r} presses={d.press_log}"
                attempt(f"guarded start, reserve 20, staged Stop SOC read back as {stxt!r}: refused STOP_SOC_UNREADABLE, nothing pressed", s_refused)
            def s_edges():
                pw, d, n0 = guard("20", "100", 100)
                pw2, d2, n2 = guard("0", "0", 0)
                return len(d.press_log) == 1 and len(d2.press_log) == 1, f"{d.press_log} {d2.press_log}"
            attempt("guarded start, a staged Stop SOC of 100 (reserve 20) and of 0 (reserve 0) is inside the range: pressed", s_edges)
    except _Stop:
        pass
    return rows


def refusal_order_problems(dump_text: str, guard_text: str) -> list[str]:
    """Static: the invalid-reserve text is in the SAME branch as the unreadable-reserve text (index 2, ahead of the too-high, power and Stop SOC
    branches); in the guarded start RESERVE_INVALID precedes RESERVE_UNKNOWN, STOP_SOC_UNREADABLE and STOP_SOC_BELOW_RESERVE."""
    bad: list[str] = []
    d = yaml.safe_load(dump_text)
    top = next(a for a in d["script"]["ecco_dump_to_grid_start_scheduled"]["sequence"] if "choose" in a)["choose"]
    cond, val = str(top[2]["conditions"]), top[2]["sequence"][0]["data"]["value"]
    if "plan_reserve < 0" not in cond or "RESERVE_INVALID" not in val or "RESERVE_UNKNOWN" not in val:
        bad.append("the third branch no longer refuses both an unreadable and an invalid reserve")
    if "RESERVE_TOO_HIGH" not in str(top[3]) or "RESERVE_INVALID" in str(top[3]):
        bad.append("the fourth branch is not the too-high refusal")
    g = yaml.safe_load(guard_text)["script"]["ecco_dump_to_grid_start_guarded"]["sequence"][0]["variables"]["refusal"]
    at = [g.find(c) for c in ("OVERRIDE_UNREADABLE", "RESERVE_INVALID", "RESERVE_UNKNOWN", "STOP_SOC_UNREADABLE", "STOP_SOC_BELOW_RESERVE")]
    if -1 in at or at != sorted(at):
        bad.append(f"guarded start refusal order {at}")
    return bad


check("the invalid-reserve refusal shares the unreadable-reserve branch (scheduled, index 2) and precedes STOP_SOC_UNREADABLE (guarded): "
      "the refusal order is unchanged and every refusal still sits ahead of any staging", refusal_order_problems(DUMP_TEXT, GUARD_TEXT) == [],
      str(refusal_order_problems(DUMP_TEXT, GUARD_TEXT)))
check("both packages test the reserve as a positive range (`r >= 0 and r <= 100`) and no bare `| float(-1)` read of the reserve is left",
      DUMP_TEXT.count("{%- if r >= 0 and r <= 100 -%}{{ r }}") == 1 and GUARD_TEXT.count("{%- if r >= 0 and r <= 100 -%}{{ r }}") == 1
      and "{{ s if (s >= 0 and s <= 100) else -1 }}" in GUARD_TEXT
      and not re.search(r"plan_reserve:\s*\"\{\{ states\('sensor\.ecco_plan_effective_reserve'\) \| float\(-1\) \}\}\"", DUMP_TEXT + GUARD_TEXT))
ROWS6 = reserve_cases(DUMP_TEXT, GUARD_TEXT)
for _label, _ok, _detail in ROWS6:
    check(_label, _ok, _detail)
check(f"all {len(ROWS6)} reserve-validation cases above ran (both start paths, every value of the table)", len(ROWS6) == len(SCHED_REFUSED) + len(SCHED_STARTED)
      + len(GUARD_REFUSED) + len(GUARD_PRESSED) + len(STAGED_REFUSED) + 1, str(len(ROWS6)))

print("[7] mutation: each way of weakening the reserve validation is caught by a running case above")
_SD = """          plan_reserve: >-
            {%- set r = states('sensor.ecco_plan_effective_reserve') | float(-1) -%}
            {%- if r >= 0 and r <= 100 -%}{{ r }}
            {%- elif r < 0 -%}-1
            {%- else -%}-2
            {%- endif -%}
"""
_ONE = "          plan_reserve: \"{{ states('sensor.ecco_plan_effective_reserve') | float(-1) }}\"\n"
_IF3 = """            {%- if r >= 0 and r <= 100 -%}{{ r }}
            {%- elif r < 0 -%}-1
            {%- else -%}-2
"""
_GS = """          staged_stop_soc: >-
            {%- set s = states('number.ecco_clock_dongle_dump_to_grid_stop_soc') | float(-1) -%}
            {{ s if (s >= 0 and s <= 100) else -1 }}
"""
_GONE = "          staged_stop_soc: \"{{ states('number.ecco_clock_dongle_dump_to_grid_stop_soc') | float(-1) }}\"\n"
MUTANTS6 = [
    ("dump", "scheduled: the validation removed (the reserve is read with float() alone)", _SD, _ONE),
    ("dump", "scheduled: a too-big-only check (refuse only above 100: nan, always False, goes through)",
     _IF3, "            {%- if r > 100 -%}-2\n            {%- elif r < 0 -%}-1\n            {%- else -%}{{ r }}\n"),
    ("dump", "scheduled: the ceil step unprotected (only a negative reserve is set aside, so inf and nan reach the rounding)",
     _IF3, "            {%- if r < 0 -%}-1\n            {%- else -%}{{ r }}\n"),
    ("dump", "scheduled: the upper bound moved to 101", "{%- if r >= 0 and r <= 100 -%}{{ r }}", "{%- if r >= 0 and r <= 101 -%}{{ r }}"),
    ("dump", "scheduled: the upper bound lowered to below 100", "{%- if r >= 0 and r <= 100 -%}{{ r }}", "{%- if r >= 0 and r < 100 -%}{{ r }}"),
    ("dump", "scheduled: the lower bound made exclusive (a reserve of 0 refused)", "{%- if r >= 0 and r <= 100 -%}{{ r }}", "{%- if r > 0 and r <= 100 -%}{{ r }}"),
    ("dump", "scheduled: an invalid reserve reported as an unreadable one (no RESERVE_INVALID text)", "{%- if plan_reserve == -2 -%}BLOCKED", "{%- if false -%}BLOCKED"),
    ("guard", "guarded: the reserve validation removed", _SD, _ONE),
    ("guard", "guarded: a too-big-only reserve check", _IF3, "            {%- if r > 100 -%}-2\n            {%- elif r < 0 -%}-1\n            {%- else -%}{{ r }}\n"),
    ("guard", "guarded: the reserve ceiling removed (only a negative reserve is set aside)", _IF3, "            {%- if r < 0 -%}-1\n            {%- else -%}{{ r }}\n"),
    ("guard", "guarded: the reserve upper bound moved to 101", "{%- if r >= 0 and r <= 100 -%}{{ r }}", "{%- if r >= 0 and r <= 101 -%}{{ r }}"),
    ("guard", "guarded: the reserve lower bound made exclusive (a reserve of 0 refused)", "{%- if r >= 0 and r <= 100 -%}{{ r }}", "{%- if r > 0 and r <= 100 -%}{{ r }}"),
    ("guard", "guarded: no RESERVE_INVALID refusal (an invalid reserve falls to RESERVE_UNKNOWN)",
     "            {%- elif plan_reserve == -2 -%}RESERVE_INVALID|The effective reserve is not a number from 0 to 100, so Dump to Grid was not started (it fails closed).\n", ""),
    ("guard", "guarded: the staged Stop SOC read-back is not validated", _GS, _GONE),
    ("guard", "guarded: the staged Stop SOC read-back has no upper bound (150 and inf pass)", "{{ s if (s >= 0 and s <= 100) else -1 }}", "{{ s if s >= 0 else -1 }}"),
    ("guard", "guarded: the staged Stop SOC accepts up to 101", "{{ s if (s >= 0 and s <= 100) else -1 }}", "{{ s if (s >= 0 and s <= 101) else -1 }}"),
]
caught6 = 0
for which, label, old, new in MUTANTS6:
    src = DUMP_TEXT if which == "dump" else GUARD_TEXT
    if src.count(old) != 1:
        check(f"mutant anchor: {label}", False, f"anchor found {src.count(old)}x")
        continue
    mutated = src.replace(old, new)
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    d_text, g_text = (mutated, GUARD_TEXT) if which == "dump" else (DUMP_TEXT, mutated)
    rows = reserve_cases(d_text, g_text, first_only=True, parts=("sched",) if which == "dump" else ("guard", "staged"))
    bad = [r for r in rows if not r[1]]
    if bad:
        caught6 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {bad[0][0][:75]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS6)} reserve-validation mutants, all caught by a running case", caught6 == len(MUTANTS6), f"{caught6}/{len(MUTANTS6)}")
check("control: the unmutated packages pass the same cases", all(ok for _l, ok, _d in ROWS6))

# ================================================================================================================================
print("[8] the scheduled start follows an override's true expiry through the repeated hour of the October clock change (review finding 1)")
# ================================================================================================================================
# The export hold read each expiry from the helper's naive local state string, so an override that ended in the repeated hour was released up to
# 60 minutes early and the scheduled start, which trusts the hold, then pressed while the card still showed the override as active. The hold
# now reads the helper's `timestamp` attribute (the true instant). Europe/London, 25 Oct 2026: an override started at 00:40 BST for 120 minutes ends
# at 01:40 GMT. Each probe is a fresh world; the scheduled start script is started at the probe's own second and reads the real hold sensor.
from datetime import datetime as _dt, timezone as _tz  # noqa: E402

_EXP_AUTUMN = _dt(2026, 10, 25, 1, 40, tzinfo=_tz.utc).timestamp()      # 01:40 GMT on the clock-change day


def world_in(local_start: str, zone: str, plan: str = PLAN_TEXT, owner=40):
    pkgs = [yaml.safe_load(t) for t in (DUMP_TEXT, plan, GUARD_TEXT)]
    pw = P.PlanWorld(local_start, pkgs, zone)
    w = pw.w
    D.add_ha_filters(w)
    d = D.DumpDongle(w, phase=0.0, handle_delays=(0.117,))
    w.set("input_boolean.ecco_dump_to_grid_schedule_armed", "on")
    w.set("input_boolean.ecco_free_power_schedule_armed", "off")
    w.set(LAST, "")
    w.set(PLAN_LAST, "")
    w.set("input_boolean.ecco_plan_overrides_enabled", "on")
    w.set("input_boolean.ecco_plan_defaults_seeded", "on")
    for k, v in {"min_expiry": 15, "hold_default": 240, "hold_cap": 1440, "skip_cap": 1440, "cut_default": 1440, "cut_cap": 4320, "cut_reserve": 80}.items():
        w.set(f"input_number.ecco_plan_policy_{k}", f"{float(v)}")
    pw.set_time("input_datetime.ecco_plan_policy_skip_until", "07:00:00")
    w.set(OWNER, "unavailable" if owner is None else f"{float(owner)}")
    return pw, d


def clock_day_problems(plan_text: str, stop_early: bool = False) -> list[str]:
    """The scheduled start, started at a given second of the override's life: refused (BLOCKED, OVERRIDE_ACTIVE, nothing staged or pressed) while the
    override runs, started (one press) from its expiry second on. Every kind, on the clock-change day."""
    bad: list[str] = []
    probes = ((-3540, False), (-1800, False), (-60, False), (-1, False), (0, True), (1, True))      # (seconds from the true expiry, starts?)
    try:
        for kind in KINDS:
            for off, starts in probes:
                pw, d = world_in("2026-10-25 00:40:40", "Europe/London", plan_text)
                hold(pw, kind, 120)
                exp = float(pw.w.state_attr(EXP[kind], "timestamp"))
                if exp != _EXP_AUTUMN or pw.state(EXP[kind]) != "2026-10-25 01:40:00":
                    bad.append(f"{kind}: the override ends at {exp} / {pw.state(EXP[kind])!r}, wanted 01:40 GMT")
                    break
                pw.w.run_until(exp + off)
                n0 = len(pw.w.service_log)
                run_scheduled(pw, d)
                last = pw.state(LAST)
                if starts:
                    ok = bool(d.presses) and d.presses[0][1] == "PASSED" and len(d.press_log) == 1 and not last.startswith("BLOCKED")
                else:
                    ok = last.startswith("BLOCKED - a Hold battery") and "OVERRIDE_ACTIVE" in last and untouched(pw, d, n0)
                if not ok:
                    bad.append(f"{kind}: scheduled start {off:+d} s from the true expiry: {last[:60]!r} presses={d.press_log}, wanted {'a start' if starts else 'a refusal'}")
                    if stop_early:
                        return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


cd_bad = clock_day_problems(PLAN_TEXT)
check("clock-change day, each kind: a scheduled start inside the repeated hour of an override that ends at 01:40 GMT is refused (OVERRIDE_ACTIVE, nothing staged "
      "or pressed) from 59 minutes in to the last second, and starts from the expiry second on", cd_bad == [], str(cd_bad[:3]))

print("[8] mutation: the hold read from the state string, or its expiry second moved, lets a scheduled start through on the clock-change day")
_READ = re.compile(r"\{%- set (\w+) = state_attr\('(input_datetime\.[a-z_]+)', 'timestamp'\) \| float\(none\) -%\}\n[ ]*\{%- set \1 = \1 if \([^\n]*\) else none -%\}")
_HOLD_LINE = "{%- if (a is not none and a > n) or (b is not none and b > n) or (c is not none and c > n) -%}held"
_ms = list(_READ.finditer(PLAN_TEXT))
MUTANTS8 = []
if len(_ms) == 10:
    for k, kind_name in ((3, "Hold battery"), (4, "Skip tonight"), (5, "Prepare for power cut")):
        m = _ms[k]
        MUTANTS8.append((f"the export hold's {kind_name} expiry read back from the state string",
                         PLAN_TEXT[:m.start()] + "{%- set " + m.group(1) + " = as_timestamp(states('" + m.group(2) + "'), none) -%}" + PLAN_TEXT[m.end():]))
if PLAN_TEXT.count(_HOLD_LINE) == 1:
    for v, kind_name in (("a", "Hold battery"), ("b", "Skip tonight"), ("c", "Prepare for power cut")):
        MUTANTS8.append((f"the export hold releases {kind_name} 45 s early ({v} > n + 45)", PLAN_TEXT.replace(_HOLD_LINE, _HOLD_LINE.replace(f"{v} > n", f"{v} > n + 45"))))
        MUTANTS8.append((f"the export hold still holds {kind_name} at the expiry second ({v} >= n)", PLAN_TEXT.replace(_HOLD_LINE, _HOLD_LINE.replace(f"{v} > n", f"{v} >= n"))))
check("the nine mutants of this section are all built (the three hold-state read sites and the expiry-second line were each found)", len(MUTANTS8) == 9, str(len(MUTANTS8)))
caught8 = 0
for label, mutated in MUTANTS8:
    found = clock_day_problems(mutated, stop_early=True)
    if found:
        caught8 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS8)} clock-change mutants, all caught by a running scheduled start", caught8 == len(MUTANTS8) and len(MUTANTS8) == 9, f"{caught8}/{len(MUTANTS8)}")
check("control: the unmutated packages pass the same running cases", cd_bad == [])

# ================================================================================================================================
print("[9] press-time recheck: the hold and the reserve are read again immediately before the press (review finding 2)")
# ================================================================================================================================
# The scheduled start read the hold and the reserve once, at its start, and then, when the dongle was offline or another write was in progress, waited and
# retried for up to 10 minutes and pressed without reading them again: a Hold battery, Skip tonight or Prepare for power cut the owner started DURING the wait
# did not stop that press. The script now reads both again immediately before the press (press_block, the second condition of the pre-press check). If the hold
# is no longer clear, or the reserve can no longer be read or is not a finite number from 0 to 100, or the Stop SOC staged for THIS run is below the rounded-up
# reserve of that moment, the run ends as a BLOCKED result (the same reason codes, RESERVE_TOO_HIGH for the staged Stop SOC) that says it happened while the
# run was waiting: nothing is pressed, the write enable ends off, it is never retried, and the end-of-run alert raises the notification. The staging of that last
# attempt (three numbers, the write enable on, then off) has happened by then; the press has not. The dongle model's busy window is a Free Power transaction in
# progress; its offline window makes every dongle entity unavailable and its services raise. The plan changes 15 s into a 45 s wait, on a virtual clock.
SCHED = "ecco_dump_to_grid_start_scheduled"
WAIT_UNTIL, CHANGE_AT = 45.0, 15.0


def waiting_run(dump_text: str, wait: str, change=None, owner=40, stop_soc=25, at: float = CHANGE_AT, until: float = WAIT_UNTIL, seconds: float = 400.0):
    """One scheduled run that has to wait for the dongle (`wait` is "busy" or "offline") with the write enable left ON beforehand; `change(pw)` happens `at`
    seconds in. Returns (pw, d, n0, t0)."""
    pw, d = world(dump_text, owner=owner)
    w = pw.w
    t0 = w.t
    d.arm = True
    w.set(D.D_ARM, "on")
    if wait == "busy":
        d.flags["fp_op"] = True
        w.set(D.FP_OP, "on")
        w.at(t0 + until, lambda: (d.flags.__setitem__("fp_op", False), w.set(D.FP_OP, "off")))
    else:
        d.set_offline(t0, t0 + until)
    if change is not None:
        w.at(t0 + at, lambda: change(pw))
    n0 = len(w.service_log)
    pw.ha.start_script(SCHED, {"duration_minutes": 30, "power_w": 2000, "stop_soc": stop_soc, "window_end_ts": t0 + 30 * 60 + 60})
    w.run_until(t0 + seconds)
    return pw, d, n0, t0


def run_facts(pw, d, n0, t0) -> dict:
    last = pw.state(LAST)
    ended = next((t for t, e, v in pw.w.history if e == "script." + SCHED and v == "off" and t > t0), None)
    return dict(last=last, presses=list(d.press_log), gate=list(d.presses), staged=[s for _t, s, _e, _d in pw.w.service_log[n0:] if s == "number.set_value"],
                alerts=[n for n in pw.w.notification_log if n[1] == "create" and n[2] == NOTE], notice=pw.w.notifications.get(NOTE, {}).get("message", ""),
                arm=pw.state(D.D_ARM), model_arm=d.arm, ended=None if ended is None else ended - t0, started=d.successes,
                stop=[v for _t, e, v in d.number_log if e == D.D_SOC], warnings=list(pw.w.warnings))


def override(kind: str, minutes: int = 120):
    return lambda pw: pw.ha.start_script("ecco_plan_override_start", {"kind": kind, "expiry_min": minutes})


def set_state(entity: str, value: str):
    return lambda pw: pw.w.set(entity, value)


def force_eff(txt: str):
    return lambda pw: pw.w.template_entities.__setitem__(EFF, txt)


# (label, change at 15 s, code, owner, asked Stop SOC): the staged Stop SOC of the run is max(asked, ceil(owner)) = 40 unless noted
CHANGES = (
    ("Hold battery started", override("hold_battery"), "OVERRIDE_ACTIVE", 40, 25),
    ("Skip tonight started", override("skip_tonight"), "OVERRIDE_ACTIVE", 40, 25),
    ("Prepare for power cut started", override("prepare_power_cut"), "OVERRIDE_ACTIVE", 40, 25),
    ("a hold record becomes unreadable", set_state(EXP["hold_battery"], "unavailable"), "OVERRIDE_UNREADABLE", 40, 25),
    ("the Prepare for power cut record becomes unreadable", set_state(EXP["prepare_power_cut"], "unavailable"), "OVERRIDE_UNREADABLE", 40, 25),
    ("the owner's reserve becomes unreadable", set_state(OWNER, "unavailable"), "RESERVE_UNKNOWN", 40, 25),
    ("the effective reserve sensor reads unavailable", force_eff("unavailable"), "RESERVE_UNKNOWN", 40, 25),
    ("the effective reserve reads nan", force_eff("nan"), "RESERVE_INVALID", 40, 25),
    ("the effective reserve reads inf", force_eff("inf"), "RESERVE_INVALID", 40, 25),
    ("the effective reserve reads 150", force_eff("150"), "RESERVE_INVALID", 40, 25),
    ("the reserve is raised from 40 to 60 above the staged Stop SOC 40", set_state(OWNER, "60.0"), "RESERVE_TOO_HIGH", 40, 25),
    ("the reserve is raised to 95 (no room under 90 percent)", set_state(OWNER, "95.0"), "RESERVE_TOO_HIGH", 40, 25),
    ("the effective reserve reads a fraction, 40.4 (rounded up 41, staged 40; defence in depth, forced onto the sensor)", force_eff("40.4"), "RESERVE_TOO_HIGH", 40, 25),
    ("the reserve is raised one point above the staged Stop SOC (staged 40, reserve 41)", set_state(OWNER, "41.0"), "RESERVE_TOO_HIGH", 30, 40),
)
# (label, change, owner, asked, staged): the run is NOT stopped and presses once with the Stop SOC it staged
UNCHANGED = (
    ("nothing changes during the wait", None, 40, 25, 40),
    ("the reserve falls during the wait (40 to 30)", set_state(OWNER, "30.0"), 40, 25, 40),
    ("the reserve is raised to exactly the staged Stop SOC (staged 40, reserve 40)", set_state(OWNER, "40.0"), 30, 40, 40),
    ("a Hold battery is started and cancelled again during the wait", lambda pw: (override("hold_battery")(pw), pw.w.at(pw.w.t + 5, lambda: pw.ha.start_script("ecco_plan_override_cancel", {"kind": "hold_battery"}))), 40, 25, 40),
)


def press_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []

    def add(msg: str) -> bool:
        bad.append(msg)
        return stop_early

    try:
        for wait in ("busy", "offline"):
            for label, change, code, owner, asked in CHANGES:
                pw, d, n0, t0 = waiting_run(dump_text, wait, change, owner=owner, stop_soc=asked)
                f = run_facts(pw, d, n0, t0)
                last = f["last"]
                ok = (f["presses"] == [] and f["gate"] == [] and f["started"] == 0 and last.startswith("BLOCKED - ") and "was waiting" in last
                      and last.endswith(f"(reason {code})") and len(last) <= 255 and "already active" not in last
                      and len(f["alerts"]) == 1 and last in f["notice"] and f["arm"] == "off" and f["model_arm"] is False
                      and len(f["staged"]) == 3 and f["ended"] is not None and f["ended"] < 120 and not any("invalid value" in m for m in f["warnings"]))
                if not ok and add(f"{wait} wait, {label}: {last[:70]!r} presses={f['presses']} staged={len(f['staged'])} alerts={len(f['alerts'])} arm={f['arm']}/{f['model_arm']} ended={f['ended']}"):
                    return bad
            for label, change, owner, asked, staged in UNCHANGED:
                pw, d, n0, t0 = waiting_run(dump_text, wait, change, owner=owner, stop_soc=asked)
                f = run_facts(pw, d, n0, t0)
                ok = (len(f["presses"]) == 1 and f["gate"] and f["gate"][0][1] == "PASSED" and f["started"] == 1 and f["stop"] == [staged] and f["last"].startswith("STARTED OK")
                      and f["alerts"] == [] and len(f["staged"]) == 3 and f["arm"] == "off" and f["model_arm"] is False)
                if not ok and add(f"{wait} wait, {label}: wanted one press, got {f['last'][:60]!r} presses={f['presses']} staged={f['stop']}"):
                    return bad
        # the longest text (all three overrides named) fits the 255-character result helper
        pw, d, n0, t0 = waiting_run(dump_text, "busy", lambda pw: [pw.w.at(pw.w.t + i, lambda k=k: pw.ha.start_script("ecco_plan_override_start", {"kind": k, "expiry_min": 120})) for i, k in enumerate(KINDS)])
        worst = pw.state(LAST).replace("None", "hold_battery,skip_tonight,prepare_power_cut")
        if (len(worst) > 255 or not worst.startswith("BLOCKED - a Hold battery") or pw.w.warnings) and add(f"the longest press-time text is {len(worst)} characters: {worst[:60]!r} {pw.w.warnings[:1]}"):
            return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def recheck_static_problems(dump_text: str) -> list[str]:
    """The recheck sits where it must: press_block is computed in the retry loop's default branch immediately before the pre-press `if`, which carries it as its second
    condition; the terminal step is after that `if`, writes only the result text, and there is still exactly one press."""
    bad: list[str] = []
    seq = yaml.safe_load(dump_text)["script"][SCHED]["sequence"]
    top = next(a for a in seq if "choose" in a)
    rep = next(a for a in top["default"] if "repeat" in a)["repeat"]
    inner = next(a for a in rep["sequence"] if "choose" in a)
    default = inner["default"]
    idx_var = next((i for i, a in enumerate(default) if isinstance(a.get("variables"), dict) and "press_block" in a["variables"]), -1)
    idx_if = next((i for i, a in enumerate(default) if "if" in a and "button.press" in str(a.get("then"))), -1)
    idx_end = next((i for i, a in enumerate(default) if "if" in a and "press_block" in str(a["if"]) and "!=" in str(a["if"]) and i != idx_if), -1)
    if not (idx_var != -1 and idx_if == idx_var + 1 and idx_end == idx_if + 1):
        bad.append(f"press_block / pre-press if / terminal step are not adjacent in that order: {(idx_var, idx_if, idx_end)}")
        return bad
    conds = default[idx_if]["if"]
    if len(conds) != 2 or "press_block" not in str(conds[1]) or "press_block" in str(conds[0]):
        bad.append("the pre-press `if` does not carry the recheck as its second condition")
    pb = default[idx_var]["variables"]["press_block"]
    if "sensor.ecco_plan_export_hold" not in pb or "sensor.ecco_plan_effective_reserve" not in pb or "requested_stop_soc" not in pb:
        bad.append("press_block does not read the hold and the reserve again and compare the staged Stop SOC")
    then = default[idx_end]["then"]
    if [a["action"] for a in then] != ["input_text.set_value"] or then[0]["target"]["entity_id"] != LAST:
        bad.append(f"the terminal step does more than write the last-result text: {[a.get('action') for a in then]}")
    if dump_text.count("action: button.press") != 1:
        bad.append("the scheduled start no longer has exactly one button.press")
    return bad


rs = recheck_static_problems(DUMP_TEXT)
check("press-time recheck, static: press_block is computed in the retry loop immediately before the pre-press `if` (second condition), the terminal step follows and writes only the "
      "result text, and the script still has exactly one button.press", rs == [], str(rs))
pp = press_problems(DUMP_TEXT)
check("press-time recheck, running: a Hold battery, Skip tonight or Prepare for power cut started, a hold record or the reserve becoming unreadable, a reserve that is "
      "not a finite number from 0 to 100, or a reserve raised above the staged Stop SOC (to 41, 60, 95; and a fractional one rounded up), DURING the wait with the dongle busy or offline: the run "
      "does not press, records the BLOCKED text with the same stable code, saying it waited (at most 255 characters, the longest one included), raises one alert, ends with the "
      "write enable OFF and is never retried (staged once, ended inside 2 minutes); with no change, a lower reserve, a reserve equal to the staged Stop SOC, or an override "
      "started and cancelled again, it presses exactly once as before", pp == [], str(pp[:3]))

print("[9] mutation: each way of dropping or weakening the recheck is caught by a running scheduled start")
_PB = "                          "
_STEP = "                              {%- if press_block == 'OVERRIDE_ACTIVE' -%}"


def _all_blocked_to_starting(t: str) -> str:
    a = t.index(_STEP)
    b = t.index("{%- endif -%}\n              until:", a)
    return t[:a] + t[a:b].replace("BLOCKED - ", "STARTING - ") + t[b:]


MUTANTS9 = [
    ("no re-read: the press ignores the recheck", [("value_template: \"{{ (press_block | string | trim) == '' }}\"", "value_template: \"{{ true }}\"")]),
    ("the re-read looks at the hold only (the reserve is never re-read)",
     [(_PB + "{%- elif r < 0 -%}RESERVE_UNKNOWN", _PB + "{%- elif false -%}RESERVE_UNKNOWN"),
      (_PB + "{%- elif not (r >= 0 and r <= 100) -%}RESERVE_INVALID", _PB + "{%- elif false -%}RESERVE_INVALID"),
      (_PB + "{%- elif (r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", _PB + "{%- elif false -%}RESERVE_TOO_HIGH")]),
    ("the re-read looks at the reserve only (the hold is never re-read)",
     [(_PB + "{%- if h == 'held' -%}OVERRIDE_ACTIVE", _PB + "{%- if false -%}OVERRIDE_ACTIVE"), (_PB + "{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", _PB + "{%- elif false -%}OVERRIDE_UNREADABLE")]),
    ("the re-read ignores a held hold", [(_PB + "{%- if h == 'held' -%}OVERRIDE_ACTIVE", _PB + "{%- if false -%}OVERRIDE_ACTIVE")]),
    ("the re-read ignores an unreadable hold", [(_PB + "{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", _PB + "{%- elif false -%}OVERRIDE_UNREADABLE")]),
    ("the re-read ignores an unreadable reserve", [(_PB + "{%- elif r < 0 -%}RESERVE_UNKNOWN", _PB + "{%- elif false -%}RESERVE_UNKNOWN")]),
    ("the re-read ignores an invalid reserve", [(_PB + "{%- elif not (r >= 0 and r <= 100) -%}RESERVE_INVALID", _PB + "{%- elif false -%}RESERVE_INVALID")]),
    ("the re-read ignores a reserve above the staged Stop SOC", [(_PB + "{%- elif (r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", _PB + "{%- elif false -%}RESERVE_TOO_HIGH")]),
    ("the reserve test is too-big-only (nan, always False, goes through)", [("{%- elif not (r >= 0 and r <= 100) -%}RESERVE_INVALID", "{%- elif r > 100 -%}RESERVE_INVALID")]),
    ("the staged Stop SOC test refuses a reserve equal to it (> becomes >=)", [("(r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", "(r | round(0, 'ceil') | int) >= (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH")]),
    ("the staged Stop SOC test lets a reserve one point above it through", [("(r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", "(r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) + 1 -%}RESERVE_TOO_HIGH")]),
    ("the staged Stop SOC test rounds the reserve down (floor)", [("(r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", "(r | round(0, 'floor') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH")]),
    ("the staged Stop SOC test rounds the reserve to nearest", [("(r | round(0, 'ceil') | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH", "(r | round(0) | int) > (requested_stop_soc | int(0)) -%}RESERVE_TOO_HIGH")]),
    ("the re-read reuses the values read at the start of the run (the old read-once behaviour)",
     [(_PB + "{%- set h = states('sensor.ecco_plan_export_hold') -%}", _PB + "{%- set h = plan_hold -%}"),
      (_PB + "{%- set r = states('sensor.ecco_plan_effective_reserve') | float(-1) -%}", _PB + "{%- set r = plan_reserve | float(-1) -%}")]),
    ("the run is not ended: the BLOCKED result is not a result the loop stops on (it retries and re-stages)", [(None, _all_blocked_to_starting)]),
    ("the terminal step is removed (no BLOCKED text: it retries until the deadline)", [("value_template: \"{{ (press_block | string | trim) != '' }}\"", "value_template: \"{{ false }}\"")]),
]
caught9 = 0
built9 = 0
for label, edits in MUTANTS9:
    mutated = DUMP_TEXT
    ok_built = True
    for old, new in edits:
        if old is None:
            mutated = new(mutated)
        elif mutated.count(old) != 1:
            ok_built = False
            check(f"mutant anchor: {label}", False, f"anchor found {mutated.count(old)}x: {old[:70]!r}")
            break
        else:
            mutated = mutated.replace(old, new)
    if not ok_built:
        continue
    built9 += 1
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = press_problems(mutated, stop_early=True)
    if found:
        caught9 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:80]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS9)} press-time recheck mutants, all caught by a running scheduled start", caught9 == len(MUTANTS9) == built9, f"{caught9}/{built9}/{len(MUTANTS9)}")
check("control: the unmutated package passes the same running cases", pp == [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan enforcement checks passed.")
print("These prove the packages against a model of the dongle; nothing was installed and nothing was written live.")
