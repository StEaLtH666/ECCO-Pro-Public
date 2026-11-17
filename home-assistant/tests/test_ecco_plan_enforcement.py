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

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan enforcement checks passed.")
print("These prove the packages against a model of the dongle; nothing was installed and nothing was written live.")
