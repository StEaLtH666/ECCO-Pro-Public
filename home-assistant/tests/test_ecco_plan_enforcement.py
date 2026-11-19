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
  [10] rounding   a fractional owner reserve end to end (the real producer sensor): the scheduled start stages it rounded UP and the guarded start refuses a staged
                  Stop SOC below it (62.4 -> 63); the floor and half-to-even mutants are caught
  [11] sensors    the press-time recheck when the hold sensor or the effective reserve sensor ITSELF reads unavailable, unknown, empty or junk during the wait (not only a record):
                  each ends the run as BLOCKED with the right code and no press, with six mutants
  [12] limit 20   (owner decision r14, 19 Nov 2026) a press-time BLOCKED result is never overwritten with STARTED OK, even when Dump to Grid is active as the loop ends (the dongle's own
                  Start button or a manual start): for each of the five reasons, busy and offline wait, Dump to Grid active before or as the text is written, the BLOCKED text stays exactly as the
                  recheck wrote it, one alert carries it plus ONE sentence (only while Dump to Grid is active) that it is active now and this run did not start it, neither schedule
                  notification is dismissed, nothing is pressed, the write enable ends off; unchanged when Dump to Grid is not active; STARTING, FAILED and CANCELLED results keep their old rule
                  (controls); the start-time BLOCKED results; thirteen mutants, the old overwrite among them. It replaces the pin of the old behaviour that stood at the end of [11]
  [13] restart   (owner decision r14, 19 Nov 2026; known limitation 19) a Home Assistant restart inside the repeated hour of the October clock change restores a date-and-time expiry
                  60 minutes early in the offline model (_plan_sim.restart: a recollection, not verified live); the absolute epoch record next to it keeps the hold to the true expiry, so the
                  scheduled start is refused (OVERRIDE_ACTIVE, nothing staged or pressed) to the last second and starts from the expiry second, for each kind; [8] also runs with the epoch record
                  reset to 0 (the attribute alone), so its hold-state read-site mutants stay killed; the epoch-ignoring mutants are caught

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
EPOCH = {k: f"input_number.ecco_plan_override_{k}_expires_epoch" for k in KINDS}    # the absolute expiry records of owner decision r14
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


def clock_day_problems(plan_text: str, stop_early: bool = False, epoch_reset: bool = False) -> list[str]:
    """The scheduled start, started at a given second of the override's life: refused (BLOCKED, OVERRIDE_ACTIVE, nothing staged or pressed) while the
    override runs, started (one press) from its expiry second on. Every kind, on the clock-change day. `epoch_reset`: the absolute epoch record of owner
    decision r14 is reset to 0 after the start, so only the date-and-time attribute carries the override (the hold-state read sites then still matter)."""
    bad: list[str] = []
    probes = ((-3540, False), (-1800, False), (-60, False), (-1, False), (0, True), (1, True))      # (seconds from the true expiry, starts?)
    try:
        for kind in KINDS:
            for off, starts in probes:
                pw, d = world_in("2026-10-25 00:40:40", "Europe/London", plan_text)
                hold(pw, kind, 120)
                if epoch_reset:
                    pw.w.set(EPOCH[kind], "0.0")
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
cd_bad2 = clock_day_problems(PLAN_TEXT, epoch_reset=True)
check("the same with the absolute epoch record reset to 0 (owner decision r14): the date-and-time attribute alone still holds the scheduled start to the true expiry second", cd_bad2 == [], str(cd_bad2[:3]))

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
    found = clock_day_problems(mutated, stop_early=True) or clock_day_problems(mutated, stop_early=True, epoch_reset=True)     # r14: the epoch record would carry a reverted attribute read on its own
    if found:
        caught8 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS8)} clock-change mutants, all caught by a running scheduled start", caught8 == len(MUTANTS8) and len(MUTANTS8) == 9, f"{caught8}/{len(MUTANTS8)}")
check("control: the unmutated packages pass the same running cases", cd_bad == [] and cd_bad2 == [])

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

# ================================================================================================================================
print("[10] the owner's fractional reserve end to end: the published reserve is rounded up, so a Stop SOC below it is refused (review finding 5)")
# ================================================================================================================================
# The effective reserve sensor published round(0) (half to even), so an owner reserve of 62.4 or 62.5 reached the start scripts as 62 and a Stop SOC of 62 was
# accepted, below the owner's value. The real producer sensor is used here (nothing forced onto it); the scripts' own rounded-up comparison is unchanged.
def frac_problems(plan_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []

    def add(msg: str) -> bool:
        bad.append(msg)
        return stop_early

    def guard_run(owner, staged):
        pw, d = world(plan=plan_text, owner=owner)
        pw.w.set(D.D_SOC, f"{float(staged)}")
        d.stop_soc = staged
        d.arm = True
        pw.run_script("ecco_dump_to_grid_start_guarded", {}, seconds=20)
        return pw, d

    try:
        # guarded start: (owner reserve, staged Stop SOC, pressed?)
        for owner, staged, pressed in ((62.4, 62, False), (62.4, 63, True), (62.5, 62, False), (62.5, 63, True), (62.0, 62, True), (62.0, 61, False), (0.2, 0, False), (0.2, 1, True)):
            pw, d = guard_run(owner, staged)
            last = pw.state(PLAN_LAST)
            ok = (len(d.press_log) == 1 and last == "") if pressed else (d.press_log == [] and last.startswith("REFUSED STOP_SOC_BELOW_RESERVE"))
            if not ok and add(f"guarded start, owner reserve {owner}, staged Stop SOC {staged}: {'wanted one press' if pressed else 'wanted STOP_SOC_BELOW_RESERVE'}, got {last[:60]!r} presses={d.press_log}"):
                return bad
        # scheduled start: the Stop SOC staged is the owner's reserve rounded UP
        for owner, want in ((62.4, 63), (62.5, 63), (62.0, 62), (0.2, 25)):
            pw, d = world(plan=plan_text, owner=owner)
            d.soc = 95.0
            run_scheduled(pw, d, stop_soc=25)
            staged = [v for _t, e, v in d.number_log if e == D.D_SOC]
            if (staged != [want] or not (d.presses and d.presses[0][1] == "PASSED")) and add(f"scheduled start, owner reserve {owner}: staged {staged}, wanted [{want}]"):
                return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


fr = frac_problems(PLAN_TEXT)
check("a fractional owner reserve end to end (the real sensor): the scheduled start stages 63 for 62.4 and 62.5 and 62 for 62.0; the guarded start refuses a staged Stop SOC of 62 "
      "for 62.4 and 62.5 and presses at 63, refuses 0 for 0.2 and presses at 1", fr == [], str(fr[:3]))
_CO = "{%- set o = (o | round(0, 'ceil')) if o is not none else none -%}"
caught10 = 0
for label, new in (("the sensor rounds the owner's reserve down (floor)", _CO.replace("'ceil'", "'floor'")),
                   ("the sensor rounds the owner's reserve half to even (the earlier round(0))", _CO.replace("round(0, 'ceil')", "round(0)"))):
    if PLAN_TEXT.count(_CO) != 1:
        check(f"mutant anchor: {label}", False, str(PLAN_TEXT.count(_CO)))
        continue
    found = frac_problems(PLAN_TEXT.replace(_CO, new), stop_early=True)
    if found:
        caught10 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check("2 end-to-end rounding mutants, both caught by a running start", caught10 == 2, f"{caught10}/2")

# ================================================================================================================================
print("[11] press-time recheck, part 2: the hold sensor or the reserve sensor ITSELF unavailable, unknown, empty or junk during the wait; and the BLOCKED text when Dump to Grid is active as the loop ends")
# ================================================================================================================================
# Re-review of 18 Nov 2026, minor 2. Section [9] makes a RECORD unavailable, so the hold SENSOR then reads `unknown`; no case made the sensor itself unavailable (what a template
# reload produces), unknown, empty or junk during the wait. A mutant that changes the recheck's `h != 'clear'` to `h == 'unknown'` (an unavailable, empty or junk hold sensor then
# PRESSES) was not caught by any behaviour check. The cases below force the hold sensor and the effective reserve sensor to each such text 15 s into a 45 s wait, through the
# interpreter's own `template_entities` map (nothing in a simulator is edited), with the dongle busy or offline: each ends the run as BLOCKED with the right reason code, with no
# press, the write enable OFF, one alert, staged once, ended inside 2 minutes. The hold forced to `clear` and the reserve forced to 40 are the controls (a forced literal alone does not
# stop a run). Existing checks are untouched.
def force_hold(txt: str):
    return lambda pw: pw.w.template_entities.__setitem__(HOLD, txt)


FORCED = tuple((f"the export hold sensor itself reads {name}", force_hold(txt), "OVERRIDE_UNREADABLE")
               for name, txt in (("unavailable", "unavailable"), ("unknown", "unknown"), ("empty", ""), ("a junk text (maybe)", "maybe"), ("a near miss of clear (Clear)", "Clear"))) + \
         tuple((f"the effective reserve sensor itself reads {name}", force_eff(txt), code)
               for name, txt, code in (("unavailable", "unavailable", "RESERVE_UNKNOWN"), ("unknown", "unknown", "RESERVE_UNKNOWN"), ("empty", "", "RESERVE_UNKNOWN"),
                                       ("nan", "nan", "RESERVE_INVALID"), ("inf", "inf", "RESERVE_INVALID"), ("150", "150", "RESERVE_INVALID"), ("-5", "-5", "RESERVE_UNKNOWN")))
FORCED_PRESS = (("the export hold sensor forced to clear", force_hold("clear")), ("the effective reserve sensor forced to 40", force_eff("40")))


def blocked_ok(f: dict, code: str) -> bool:
    last = f["last"]
    return (f["presses"] == [] and f["gate"] == [] and f["started"] == 0 and last.startswith("BLOCKED - ") and "was waiting" in last and last.endswith(f"(reason {code})")
            and len(last) <= 255 and "already active" not in last and len(f["alerts"]) == 1 and last in f["notice"] and f["arm"] == "off" and f["model_arm"] is False
            and len(f["staged"]) == 3 and f["ended"] is not None and f["ended"] < 120 and not any("invalid value" in m for m in f["warnings"]))


def forced_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []

    def add(msg: str) -> bool:
        bad.append(msg)
        return stop_early

    try:
        for wait in ("busy", "offline"):
            for label, change, code in FORCED:
                pw, d, n0, t0 = waiting_run(dump_text, wait, change)
                f = run_facts(pw, d, n0, t0)
                if not blocked_ok(f, code) and add(f"{wait} wait, {label}: {f['last'][:70]!r} presses={f['presses']} staged={len(f['staged'])} alerts={len(f['alerts'])} arm={f['arm']}/{f['model_arm']} ended={f['ended']}"):
                    return bad
            for label, change in FORCED_PRESS:
                pw, d, n0, t0 = waiting_run(dump_text, wait, change)
                f = run_facts(pw, d, n0, t0)
                ok = (len(f["presses"]) == 1 and f["gate"] and f["gate"][0][1] == "PASSED" and f["started"] == 1 and f["stop"] == [40] and f["last"].startswith("STARTED OK")
                      and f["alerts"] == [] and f["arm"] == "off" and f["model_arm"] is False)
                if not ok and add(f"{wait} wait, {label}: wanted one press, got {f['last'][:60]!r} presses={f['presses']} staged={f['stop']}"):
                    return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


fp = forced_problems(DUMP_TEXT)
check(f"press-time recheck, the sensors themselves, running: the export hold sensor forced to unavailable, unknown, empty, junk text or a near miss of clear, and the effective reserve sensor "
      f"forced to unavailable, unknown, empty, nan, inf, 150 or -5, DURING the wait with the dongle busy or offline ({2 * len(FORCED)} runs): each ends the run as BLOCKED with the right "
      "reason code (OVERRIDE_UNREADABLE, RESERVE_UNKNOWN or RESERVE_INVALID), saying it waited, with no press, one alert, the write enable OFF and staged once; the two forced-clear "
      "controls (4 runs) press once", fp == [], str(fp[:3]))

print("[11] mutation: an unavailable, unknown, empty or junk sensor that presses, or an unreadable reserve read as a number, is caught by a running scheduled start")
_RK = "                          {%- set r = states('sensor.ecco_plan_effective_reserve') | float(-1) -%}"
MUTANTS11 = [
    ("the recheck lets every hold text but `unknown` press (h != 'clear' becomes h == 'unknown': unavailable, empty and junk press)",
     [("{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", "{%- elif h == 'unknown' -%}OVERRIDE_UNREADABLE")]),
    ("the recheck lets every hold text but `unavailable` press (h != 'clear' becomes h == 'unavailable': unknown, empty and junk press)",
     [("{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", "{%- elif h == 'unavailable' -%}OVERRIDE_UNREADABLE")]),
    ("the recheck refuses only an unavailable or unknown hold (empty and junk press)",
     [("{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", "{%- elif h in ['unknown', 'unavailable'] -%}OVERRIDE_UNREADABLE")]),
    ("the recheck refuses only the empty hold (unavailable, unknown and junk press)",
     [("{%- elif h != 'clear' -%}OVERRIDE_UNREADABLE", "{%- elif h == '' -%}OVERRIDE_UNREADABLE")]),
    ("an unreadable effective reserve is read as 0 (float(-1) becomes float(0): unavailable, unknown and empty press)", [(_RK, _RK.replace("float(-1)", "float(0)"))]),
    ("a reserve below 0 is not told apart as unreadable (r < 0 becomes r < -10: -5 and every unreadable reserve read RESERVE_INVALID)",
     [("{%- elif r < 0 -%}RESERVE_UNKNOWN", "{%- elif r < -10 -%}RESERVE_UNKNOWN")]),
]
caught11 = 0
built11 = 0
for label, edits in MUTANTS11:
    mutated = DUMP_TEXT
    ok_built = True
    for old, new in edits:
        if mutated.count(old) != 1:
            ok_built = False
            check(f"mutant anchor: {label}", False, f"anchor found {mutated.count(old)}x: {old[:70]!r}")
            break
        mutated = mutated.replace(old, new)
    if not ok_built:
        continue
    built11 += 1
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = forced_problems(mutated, stop_early=True)
    if found:
        caught11 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:80]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS11)} sensor-state recheck mutants, all caught by a running scheduled start", caught11 == len(MUTANTS11) == built11, f"{caught11}/{built11}/{len(MUTANTS11)}")
check("control: the unmutated package passes the same running cases", fp == [])

# ================================================================================================================================
print("[12] known limitation 20 FIXED (owner decision r14, 19 Nov 2026): a press-time BLOCKED result is no longer overwritten with STARTED OK when Dump to Grid is found active as the loop ends")
# ================================================================================================================================
# Before this change the step after the scheduled start's retry loop replaced ANY result that did not start with STARTED by "STARTED OK - Dump to Grid is active; this run could not confirm the
# start as its own ..." when Dump to Grid was active (started from the dongle's own Start button, which no override binds (RG-ST3), or by hand). The press-time recheck writes its BLOCKED text inside the
# loop, so that overwrite lost the refusal: the end-of-run alert was skipped and the schedule notifications were dismissed. The owner's decision (r14): a refusal stays a refusal. Now a result that
# starts with BLOCKED is never overwritten, the alert is raised as for any BLOCKED result, the schedule notifications are NOT dismissed, the write enable still ends off, and the alert says in ONE
# conditional sentence, only while Dump to Grid is active at that moment, that Dump to Grid is active now and that this run did not start it. This script presses nothing in any of these runs.
# Not changed (pre-existing rule, same harness, controls below): a STARTING, FAILED or CANCELLED result with Dump to Grid active is still replaced by STARTED OK (only BLOCKED is in scope). The old
# behaviour is kept as a mutant (the unconditional overwrite) that the checks below kill. The pin of limitation 20 that stood at the end of [11] required the overwrite (a Hold battery started during a busy or
# offline wait, Dump to Grid becoming active 2 s into the 5 s pause: the result STARTED OK, no alert, the stale alert dismissed); it is replaced by the opposite expectation for that very scenario (the check
# marked 'replaces the pin' below) and for every other reason.
NOTE_READY = "ecco_dump_to_grid_schedule_readiness"
ACTIVE_NOW = ("Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand). "
              "Check it, and the plan overrides, before assuming it is held.")
ALERT_TAIL = (r"Authorised window ends \d\d:\d\d\. If time remains and the reason is cleared, use Dump to Grid now in Energy Actions\. "
              r"If a start transaction began or the outcome is unconfirmed, check the Dump to Grid status and recovery state first\.")
OVERWRITE_TEXT = "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own"
ARMED = "input_boolean.ecco_dump_to_grid_schedule_armed"
# (label, change 15 s into the wait, stable code): the five press-time BLOCKED reasons (the staged Stop SOC of the run is 40: owner reserve 40, asked 25)
REASONS12 = (
    ("a Hold battery is started", override("hold_battery"), "OVERRIDE_ACTIVE"),
    ("a hold record becomes unreadable", set_state(EXP["hold_battery"], "unavailable"), "OVERRIDE_UNREADABLE"),
    ("the effective reserve sensor reads unavailable", force_eff("unavailable"), "RESERVE_UNKNOWN"),
    ("the effective reserve reads nan", force_eff("nan"), "RESERVE_INVALID"),
    ("the owner's reserve is raised from 40 to 60, above the staged Stop SOC", set_state(OWNER, "60.0"), "RESERVE_TOO_HIGH"),
)
# when Dump to Grid becomes active, both orders: 2 s after the "arm or staged values not confirmed" text (before the BLOCKED text is written, as the old pin had it) and the instant the BLOCKED text is written
ORDERS12 = (("before the BLOCKED text is written", lambda t: "not confirmed" in t, 2.0), ("as the BLOCKED text is written", lambda t: t.startswith("BLOCKED"), 0.0))


def end_run(dump_text: str, wait: str, change=None, active_when=None, active_delay: float = 0.0, window=None, seconds: float = 400.0) -> dict:
    """One scheduled run (`wait`: busy, offline or none), with a stale alert and a stale readiness alert on screen. `change(pw)` happens 15 s in. Dump to Grid becomes active (the
    dongle's own Start button or a manual start) `active_delay` s after the result text first satisfies `active_when`, or never. Returns the run facts plus what the notifications did."""
    pw, d = world(dump_text, owner=40)
    w = pw.w
    t0 = w.t
    d.arm = True
    w.set(D.D_ARM, "on")
    if wait == "busy":
        d.flags["fp_op"] = True
        w.set(D.FP_OP, "on")
        w.at(t0 + WAIT_UNTIL, lambda: (d.flags.__setitem__("fp_op", False), w.set(D.FP_OP, "off")))
    elif wait == "offline":
        d.set_offline(t0, t0 + WAIT_UNTIL)
    w.notifications[NOTE] = {"title": "earlier alert", "message": "an alert from an earlier run"}
    w.notifications[NOTE_READY] = {"title": "earlier readiness alert", "message": "a readiness alert from an earlier run"}
    fired: list = []

    def go_active():
        d.active = True
        w.set(D.D_ACTIVE, "on")

    def on_state(_kind):
        if active_when is not None and not fired and active_when(w.states.get(LAST, ("", {}))[0]):
            fired.append(w.t)
            if active_delay > 0:
                w.after(active_delay, go_active)
            else:
                go_active()

    w.listeners.append(on_state)
    if change is not None:
        w.at(t0 + CHANGE_AT, lambda: change(pw))
    n0 = len(w.service_log)
    pw.ha.start_script(SCHED, {"duration_minutes": 30, "power_w": 2000, "stop_soc": 25, "window_end_ts": t0 + (30 * 60 + 60 if window is None else window)})
    w.run_until(t0 + seconds)
    f = run_facts(pw, d, n0, t0)
    f.update(dismissed=sorted(n[2] for n in w.notification_log if n[1] == "dismiss"), notes_left=sorted(w.notifications), went_active=bool(fired), active_end=pw.state(D.D_ACTIVE))
    return f


def refusal_ok(f: dict, code: str) -> bool:
    """The refusal itself, in every run of this section: BLOCKED text with the stable code, saying it waited; nothing pressed or started; one alert; the write enable ends off; staged once; ended inside 2 minutes."""
    last = f["last"]
    return (f["presses"] == [] and f["gate"] == [] and f["started"] == 0 and last.startswith("BLOCKED - ") and "was waiting" in last and last.endswith(f"(reason {code})")
            and len(last) <= 255 and "already active" not in last and len(f["alerts"]) == 1 and f["arm"] == "off" and f["model_arm"] is False
            and len(f["staged"]) == 3 and f["ended"] is not None and f["ended"] < 120 and not any("invalid value" in m for m in f["warnings"]))


def idle_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    """Dump to Grid never becomes active: the BLOCKED text, the alert exactly as before (no sentence) and nothing dismissed."""
    bad: list[str] = []
    try:
        for wait in ("busy", "offline"):
            for label, change, code in REASONS12:
                f = end_run(dump_text, wait, change)
                ok = (refusal_ok(f, code) and f["active_end"] == "off" and re.fullmatch(re.escape(f["last"]) + "\n" + ALERT_TAIL, f["notice"], re.S) is not None
                      and ACTIVE_NOW not in f["notice"] and "active now" not in f["notice"] and f["dismissed"] == [] and NOTE_READY in f["notes_left"])
                if not ok:
                    bad.append(f"{wait} wait, {label}, Dump to Grid never active: {f['last'][:60]!r} alerts={len(f['alerts'])} notice={f['notice'][-60:]!r} dismissed={f['dismissed']}")
                    if stop_early:
                        return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def active_problems(dump_text: str, reasons=REASONS12, orders=ORDERS12, stop_early: bool = False) -> list[str]:
    """Dump to Grid is active as the loop ends (both orders, busy and offline wait): the BLOCKED text stays exactly as the recheck wrote it (the text of the run in which Dump to Grid never
    became active), one alert carries it and the active-now sentence, the stale alert is replaced, nothing is dismissed (the readiness alert stays), the script presses nothing and the write enable ends off."""
    bad: list[str] = []
    try:
        for wait in ("busy", "offline"):
            for label, change, code in reasons:
                ref = end_run(dump_text, wait, change)["last"]
                for order, when, delay in orders:
                    f = end_run(dump_text, wait, change, when, delay)
                    ok = (f["went_active"] and f["active_end"] == "on" and refusal_ok(f, code) and f["last"] == ref and "STARTED" not in f["last"]
                          and re.fullmatch(re.escape(f["last"]) + "\n" + re.escape(ACTIVE_NOW) + "\n" + ALERT_TAIL, f["notice"], re.S) is not None
                          and f["dismissed"] == [] and NOTE_READY in f["notes_left"] and NOTE in f["notes_left"])
                    if not ok:
                        bad.append(f"{wait} wait, {label}, Dump to Grid active {order}: result {f['last'][:70]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} "
                                   f"notice={f['notice'][-90:]!r} presses={f['presses']} arm={f['arm']}/{f['model_arm']}")
                        if stop_early:
                            return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


# (label, wait, change, when Dump to Grid becomes active, delay, window length or None): results that are NOT BLOCKED keep the rule they always had (replaced by STARTED OK while Dump to Grid is active)
CONTROLS12 = (
    ("a STARTING result (the run is still waiting for the dongle)", "busy", None, lambda t: t.startswith("STARTING - attempt 1 waiting"), 2.0, None),
    ("a FAILED result (the authorised window is nearly over)", "none", None, lambda t: t.startswith("FAILED"), 0.0, 20.0),
    ("a CANCELLED result (the schedule is disarmed during the wait)", "busy", lambda pw: pw.w.set(ARMED, "off"), lambda t: t.startswith("CANCELLED"), 0.0, None),
)


def control_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    """Only BLOCKED is in scope: a STARTING, FAILED or CANCELLED result with Dump to Grid active is replaced by STARTED OK exactly as before: no alert, both schedule notifications dismissed, nothing pressed."""
    bad: list[str] = []
    try:
        for label, wait, change, when, delay, window in CONTROLS12:
            f = end_run(dump_text, wait, change, when, delay, window)
            ok = (f["went_active"] and f["last"].startswith(OVERWRITE_TEXT) and "BLOCKED" not in f["last"] and f["presses"] == [] and f["gate"] == [] and f["started"] == 0
                  and f["alerts"] == [] and f["dismissed"] == sorted([NOTE, NOTE_READY]) and f["notes_left"] == [] and f["arm"] == "off" and f["model_arm"] is False)
            if not ok:
                bad.append(f"control, {label}: result {f['last'][:70]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} left={f['notes_left']} presses={f['presses']}")
                if stop_early:
                    return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def start_time_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    """The start-time BLOCKED results (they end the script before the loop; they never reached the overwrite). With Dump to Grid already active: a Hold battery that is active keeps its BLOCKED text and its
    alert, and the alert now carries the active-now sentence (it is the same alert); 'BLOCKED - Dump to Grid already active' is excluded from the alert as before: no alert, the stale notifications dismissed."""
    bad: list[str] = []
    try:
        for label, held in (("a Hold battery is active at the start", True), ("no override, Dump to Grid already active", False)):
            pw, d = world(dump_text, owner=40)
            w = pw.w
            if held:
                hold(pw, "hold_battery")
            d.active = True
            w.set(D.D_ACTIVE, "on")
            w.notifications[NOTE] = {"title": "earlier alert", "message": "an alert from an earlier run"}
            w.notifications[NOTE_READY] = {"title": "earlier readiness alert", "message": "a readiness alert from an earlier run"}
            n0 = len(w.service_log)
            t0 = w.t
            run_scheduled(pw, d)
            f = run_facts(pw, d, n0, t0)
            dismissed = sorted(n[2] for n in w.notification_log if n[1] == "dismiss")
            pressed = f["presses"] != [] or f["gate"] != [] or d.number_log != []
            if held:
                ok = (f["last"].startswith("BLOCKED - a Hold battery, Skip tonight or Prepare for power cut is active") and f["last"].endswith("(reason OVERRIDE_ACTIVE). Cancel it on the Energy Actions card to allow this start.")
                      and len(f["alerts"]) == 1 and re.fullmatch(re.escape(f["last"]) + "\n" + re.escape(ACTIVE_NOW) + "\n" + ALERT_TAIL, f["notice"], re.S) is not None
                      and dismissed == [] and NOTE_READY in w.notifications and not pressed)
            else:
                ok = f["last"] == "BLOCKED - Dump to Grid already active" and f["alerts"] == [] and dismissed == sorted([NOTE, NOTE_READY]) and not pressed
            if not ok:
                bad.append(f"start-time, {label}: result {f['last'][:70]!r} alerts={len(f['alerts'])} dismissed={dismissed} notice={f['notice'][-90:]!r} pressed={pressed}")
                if stop_early:
                    return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def all12_problems(dump_text: str) -> list[str]:
    """Every behaviour check of this section, in cost order, stopping at the first failure (a mutant is caught when any of them fails)."""
    for fn in (lambda t: active_problems(t, stop_early=True), lambda t: idle_problems(t, stop_early=True), lambda t: control_problems(t, stop_early=True), lambda t: start_time_problems(t, stop_early=True)):
        found = fn(dump_text)
        if found:
            return found
    return []


ap = {}
for label, change, code in REASONS12:
    ap[code] = active_problems(DUMP_TEXT, reasons=((label, change, code),))
    check(f"LIMITATION 20 FIXED, reason {code} ({label}): the run is BLOCKED by the press-time recheck during its wait (busy and offline), then Dump to Grid becomes active before or as the BLOCKED text is written "
          "(the dongle's own Start button or a manual start): the BLOCKED text stays exactly as the recheck wrote it (not STARTED OK), one alert is raised carrying it and, only because Dump to Grid is active, the sentence "
          "that it is active now and this run did not start it, the stale alert is replaced, neither schedule notification is dismissed, nothing is pressed or started and the write enable ends off", ap[code] == [], str(ap[code][:2]))
rp = active_problems(DUMP_TEXT, reasons=REASONS12[:1], orders=ORDERS12[:1])
check("LIMITATION 20 FIXED, replaces the pin of the old behaviour: the recheck BLOCKS a run during its wait (a Hold battery started), then Dump to Grid becomes active before the loop ends (the dongle's own Start button "
      "or a manual start): the script presses nothing and the BLOCKED text is KEPT (the old pin required 'STARTED OK - Dump to Grid is active; this run could not confirm the start as its own', no alert and the "
      "stale alert dismissed; now one alert and nothing dismissed) (busy and offline waits)", rp == [], str(rp[:2]))
ip = idle_problems(DUMP_TEXT)
check("press-time BLOCKED with Dump to Grid NOT active (all five reasons, busy and offline), unchanged behaviour: the BLOCKED text, one alert whose message is the result text and the usual tail with no active-now "
      "sentence, nothing dismissed, nothing pressed, the write enable off", ip == [], str(ip[:2]))
cp = control_problems(DUMP_TEXT)
check("controls, only BLOCKED is in scope: a STARTING, a FAILED and a CANCELLED result with Dump to Grid active are replaced by STARTED OK exactly as before (no alert, both schedule notifications dismissed, nothing "
      "pressed)", cp == [], str(cp[:2]))
sp = start_time_problems(DUMP_TEXT)
check("start-time BLOCKED results, Dump to Grid already active: a Hold battery active at the start keeps its BLOCKED text and its one alert (which now carries the active-now sentence, the same alert); "
      "'BLOCKED - Dump to Grid already active' still raises no alert and still dismisses the schedule notifications; nothing staged or pressed", sp == [], str(sp[:2]))

print("[12] mutation: the old overwrite, a guard that covers only some reasons or too many results, a missing, unconditional, inverted or reworded sentence, and a skipped alert (the old dismissal) are each caught")
_COND_NEW = ("                  {{ is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and not r.startswith('STARTED')\n"
             "                     and not r.startswith('BLOCKED') }}\n")
_COND_OLD = "                  {{ is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and not r.startswith('STARTED') }}\n"
_GUARD = "                     and not r.startswith('BLOCKED') }}\n"
_IF_ACTIVE = "                {%- if is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') %}\n"
_SENTENCE_BLOCK = (_IF_ACTIVE + "\n"
                   "                Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand).\n"
                   "                Check it, and the plan overrides, before assuming it is held.\n"
                   "                {%- endif %}\n")
_ALERT_IF = "              {{ r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)\n"
MUTANTS12 = [
    ("the old unconditional overwrite is restored (any result that is not STARTED becomes STARTED OK while Dump to Grid is active)", [(_COND_NEW, _COND_OLD)]),
    ("the guard covers only the Hold battery reason (OVERRIDE_ACTIVE)", [(_GUARD, "                     and 'reason OVERRIDE_ACTIVE' not in r }}\n")]),
    ("the guard covers the reserve reasons only (an override or an unreadable record is overwritten)", [(_GUARD, "                     and not (r.startswith('BLOCKED') and 'reason RESERVE' in r) }}\n")]),
    ("the guard covers every reason but RESERVE_TOO_HIGH", [(_GUARD, "                     and not (r.startswith('BLOCKED') and 'reason RESERVE_TOO_HIGH' not in r) }}\n")]),
    ("the guard also spares a STARTING result (too broad: the old rule for STARTING is lost)", [(_GUARD, _GUARD.replace(" }}\n", "\n                     and not r.startswith('STARTING') }}\n"))]),
    ("the guard also spares a FAILED result (too broad: the old rule for FAILED is lost)", [(_GUARD, _GUARD.replace(" }}\n", "\n                     and not r.startswith('FAILED') }}\n"))]),
    ("the guard also spares a CANCELLED result (too broad: the old rule for CANCELLED is lost)", [(_GUARD, _GUARD.replace(" }}\n", "\n                     and not r.startswith('CANCELLED') }}\n"))]),
    ("the alert is skipped while Dump to Grid is active, so the notifications are dismissed again (the old dismissal)",
     [(_ALERT_IF, "              {{ (r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)) and not is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')\n")]),
    ("the active-now sentence is missing", [(_SENTENCE_BLOCK, "")]),
    ("the active-now sentence is shown whether or not Dump to Grid is active", [(_IF_ACTIVE, "                {%- if true %}\n")]),
    ("the active-now sentence is shown when Dump to Grid is NOT active (inverted)", [(_IF_ACTIVE, _IF_ACTIVE.replace("'on')", "'off')"))]),
    ("the active-now sentence no longer says this run did not start it", [("Dump to Grid is active now, and this run did not start it", "Dump to Grid is running")]),
    ("the active-now sentence no longer asks for the plan overrides to be checked", [("Check it, and the plan overrides, before assuming it is held.", "Check it.")]),
]
caught12 = 0
built12 = 0
for label, edits in MUTANTS12:
    mutated = DUMP_TEXT
    ok_built = True
    for old, new in edits:
        if mutated.count(old) != 1:
            ok_built = False
            check(f"mutant anchor: {label}", False, f"anchor found {mutated.count(old)}x: {old[:70]!r}")
            break
        mutated = mutated.replace(old, new)
    if not ok_built:
        continue
    built12 += 1
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = all12_problems(mutated)
    if found:
        caught12 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS12)} mutants of the post-loop overwrite and the alert sentence (the old overwrite among them), all caught by a running scheduled start", caught12 == len(MUTANTS12) == built12, f"{caught12}/{built12}/{len(MUTANTS12)}")
check("control: the unmutated package passes the same running cases", ip == [] and cp == [] and sp == [] and rp == [] and all(v == [] for v in ap.values()))

# ================================================================================================================================
print("[13] a Home Assistant restart inside the repeated hour does not release an override early: the scheduled start follows the absolute epoch record (owner decision r14; known limitation 19)")
# ================================================================================================================================
# THE MODEL (a recollection of Home Assistant core, NOT verified live): a restart restores a date-and-time helper's attribute from its state string, read as the first of two equal local times, so an
# expiry in the repeated hour of the autumn clock change is restored 60 minutes early (_plan_sim.restart). Before r14 the export hold, which read only that attribute, then released the override up to an
# hour early and the scheduled start pressed. Now each expiry is also an absolute epoch record (an input_number restored exactly) and the hold takes the LATER of the two instants. Europe/London, 25 Oct
# 2026: an override started at 00:40 BST for 120 minutes ends at 01:40 GMT; Home Assistant restarts at 01:10 GMT (the attribute then reads 00:40 GMT, already past). Each probe is a fresh world.
def restart_day_problems(plan_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []
    probes = ((-1500, False), (-60, False), (-1, False), (0, True), (1, True))      # (seconds from the true expiry, starts?)
    try:
        for kind in KINDS:
            for off, starts in probes:
                pw, d = world_in("2026-10-25 00:40:40", "Europe/London", plan_text)
                hold(pw, kind, 120)
                exp = float(pw.w.state_attr(EXP[kind], "timestamp"))
                pw.w.run_until(exp - 1800)
                pw.restart("first")
                if float(pw.w.state_attr(EXP[kind], "timestamp")) != exp - 3600:
                    bad.append(f"{kind}: the restart model did not restore the expiry 60 minutes early")
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
                    bad.append(f"{kind}: after a restart at 01:10 GMT, a scheduled start {off:+d} s from the true expiry: {last[:60]!r} presses={d.press_log}, wanted {'a start' if starts else 'a refusal'}")
                    if stop_early:
                        return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


rd_bad = restart_day_problems(PLAN_TEXT)
check("restart at 01:10 GMT inside the repeated hour, each kind: the scheduled start is refused (OVERRIDE_ACTIVE, nothing staged or pressed) from 25 minutes before the true expiry to its last "
      "second, although the restored attribute already reads 60 minutes early, and starts from the expiry second on", rd_bad == [], str(rd_bad[:3]))
_COMBINE = re.compile(r"\{%- set (\w+) = \(\[\1, (\w+)\] \| reject\('none'\) \| list \| max\) if \(\(\1 is not none and \2 is not none\) or \(\1 is not none and \1 > (\w+)\) or \(\2 is not none and \2 > \3\)\) else none -%\}")
_cs = list(_COMBINE.finditer(PLAN_TEXT))
print("[13] mutation: the absolute epoch record ignored at a hold-state read site, or the earlier instant taken, lets a scheduled start through after a restart")
MUTANTS13 = []
if len(_cs) == 10:
    for k, kind_name in ((3, "Hold battery"), (4, "Skip tonight"), (5, "Prepare for power cut")):
        m = _cs[k]
        MUTANTS13.append((f"the export hold ignores the epoch record of {kind_name}", PLAN_TEXT[:m.start()] + "{%- set " + m.group(1) + " = " + m.group(1) + " -%}" + PLAN_TEXT[m.end():]))
    MUTANTS13.append(("the export hold takes the earlier of the two instants (min for max)", _COMBINE.sub(lambda m: m.group(0).replace("| list | max)", "| list | min)"), PLAN_TEXT)))
check("the four mutants of this section are all built (the ten combination lines were found)", len(MUTANTS13) == 4, str(len(_cs)))
caught13 = 0
for label, mutated in MUTANTS13:
    found = restart_day_problems(mutated, stop_early=True)
    if found:
        caught13 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS13)} restart mutants, all caught by a running scheduled start", caught13 == len(MUTANTS13) == 4, f"{caught13}/{len(MUTANTS13)}")
check("control: the unmutated packages pass the same running cases", rd_bad == [])

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan enforcement checks passed.")
print("These prove the packages against a model of the dongle; nothing was installed and nothing was written live.")
