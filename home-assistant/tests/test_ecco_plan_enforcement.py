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
                  notification is dismissed, nothing is pressed, the write enable ends off; unchanged when Dump to Grid is not active; since owner decision r15 (see [14]) a STARTING, FAILED or CANCELLED
                  result is not overwritten with STARTED OK either (the controls now require that); the start-time BLOCKED results; mutants, the old overwrite among them. It replaces the pin of the old
                  behaviour that stood at the end of [11]
  [13] restart   (owner decision r14, 19 Nov 2026; known limitation 19) a Home Assistant restart inside the repeated hour of the October clock change restores a date-and-time expiry
                  60 minutes early in the offline model (_plan_sim.restart: a recollection, not verified live); the absolute epoch record next to it keeps the hold to the true expiry, so the
                  scheduled start is refused (OVERRIDE_ACTIVE, nothing staged or pressed) to the last second and starts from the expiry second, for each kind; [8] also runs with the epoch record
                  reset to 0 (the attribute alone), so its hold-state read-site mutants stay killed; the epoch-ignoring mutants are caught
  [14] status    (owner decision r15, 19 Nov 2026; known limitation 20, extended) the steps after the retry loop never turn a result into a success: a FAILED or CANCELLED result is final and stays exactly as
                  written when Dump to Grid is active (started some other way), a result still STARTING with Dump to Grid active becomes a FAILED TO START text that says Dump to Grid is active now and
                  that this run did not confirm that it started it (CANCELLED if the owner cancelled), the alert's active-now sentence stays true for each result it can accompany, and the in-loop
                  STARTED OK path (this run's own verified start) is unchanged in every shape; a table of every result class x Dump to Grid active or not x armed, run through the real steps and
                  compared with the previous package where Dump to Grid is not active; end-to-end runs; mutants (the old overwrite restored per class, a success text added, wrong sentences)
  [15] recovery  (owner decision r15, 19 Nov 2026; known limitation 20, its last path) the startup recovery after a Home Assistant restart no longer writes STARTED OK over a result this schedule did not verify: only a
                  last result that already starts with STARTED is kept as the old text (and the old disarm), a FAILED, BLOCKED or CANCELLED result stays exactly as written, every other result becomes a truthful UNCONFIRMED
                  text (Dump to Grid is active after a Home Assistant restart, this schedule did not confirm that it started it); the real recovery automation run for every result class x Dump to Grid active or not x
                  armed or not x where now is relative to the window, compared with the previous package where the branch does not run; what the owner still sees; end-to-end runs through the real start script, a restart
                  and the real recovery; the diff is exactly the one branch; mutants (the old unconditional write restored among them)
  [15.6] rebuild  (R9's clock-change refusals merged under this change) the previous package of [14] and [15] is rebuilt by first undoing R9's five declared Dump pairs (the r9 scope module's strict reverter), so the two
                  code-line pins stay as they were; one-character mutants inside R9's region and a package without any of the pairs fail the rebuild

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
sys.path.append(str(ROOT / "registry" / "tests"))      # appended, not inserted: nothing of this directory can shadow a module imported above
import _r9_scope as _r9s  # noqa: E402                  # R9's declared edits to the Dump package (exact pairs and the strict reverter), used by the rebuild of the previous package in [14] and [15]

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


def world(dump=DUMP_TEXT, plan=PLAN_TEXT, guard=GUARD_TEXT, owner=40, stop=None, install_plan=True, pkgs=None):
    pkgs = pkgs if pkgs is not None else [yaml.safe_load(t) for t in ((dump, plan, guard) if install_plan else (dump, guard))]   # `pkgs`: already-parsed packages ([14]'s probe script)
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
# r15 (19 Nov 2026, see [14]): the first version of this section left a STARTING, FAILED or CANCELLED result to the old rule (replaced by STARTED OK while Dump to Grid is active, shown by controls). The owner's
# decision r15 reverses that: the controls below now require the OPPOSITE (never STARTED OK) and the old rule is a mutant for each of the three classes. The old
# behaviour is kept as a mutant (the unconditional overwrite) that the checks below kill. The pin of limitation 20 that stood at the end of [11] required the overwrite (a Hold battery started during a busy or
# offline wait, Dump to Grid becoming active 2 s into the 5 s pause: the result STARTED OK, no alert, the stale alert dismissed); it is replaced by the opposite expectation for that very scenario (the check
# marked 'replaces the pin' below) and for every other reason.
NOTE_READY = "ecco_dump_to_grid_schedule_readiness"
ACTIVE_NOW = ("Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand). "
              "Check it, and the plan overrides, before assuming it is held.")
ALERT_TAIL = (r"Authorised window ends \d\d:\d\d\. If time remains and the reason is cleared, use Dump to Grid now in Energy Actions\. "
              r"If a start transaction began or the outcome is unconfirmed, check the Dump to Grid status and recovery state first\.")
OVERWRITE_TEXT = "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own"
# Owner decision r15: for a FAILED result (and the new STARTING-final text) the alert cannot say "did not start it" (an unconfirmed outcome can be a late start of this run's own press): it says it did not CONFIRM it.
ACTIVE_CONFIRM = ("Dump to Grid is active now, but this run did not confirm that it started it (it may have been started from the dongle's own Start button or by hand, "
                  "or, if a start transaction had begun, late by this run's own press). Check it, and the plan overrides, before assuming it is held.")
FAILED_FINAL = r"FAILED TO START - retries ended at \d\d:\d\d: (.*); Dump to Grid is active now, but this run did not confirm that it started it"
CANCELLED_TEXT = "CANCELLED - scheduled Dump to Grid cancelled before it started"
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


def end_run(dump_text: str, wait: str, change=None, active_when=None, active_delay: float = 0.0, window=None, seconds: float = 400.0, setup=None) -> dict:
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
    if setup is not None:                      # r15 ([14]): dongle or Home Assistant faults that must stand from the start of the run
        setup(pw, d, t0)
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


# (label, wait, change, when Dump to Grid becomes active, delay, window length or None, kind): owner decision r15 (19 Nov 2026) REPLACED the controls that stood here. They required the old rule (a STARTING, a FAILED and a
# CANCELLED result replaced by STARTED OK while Dump to Grid is active, no alert, both schedule notifications dismissed); they now require the OPPOSITE, and the old rule is a mutant for each class below.
CONTROLS12 = (
    ("a STARTING result (the run is still waiting for the dongle)", "busy", None, lambda t: t.startswith("STARTING - attempt 1 waiting"), 2.0, None, "STARTING"),
    ("a FAILED result (the authorised window is nearly over)", "none", None, lambda t: t.startswith("FAILED"), 0.0, 20.0, "FAILED"),
    ("a CANCELLED result (the schedule is disarmed during the wait)", "busy", lambda pw: pw.w.set(ARMED, "off"), lambda t: t.startswith("CANCELLED"), 0.0, None, "CANCELLED"),
)


def control_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    """Owner decision r15, the opposite of the controls that stood here: with Dump to Grid active a STARTING, FAILED or CANCELLED result is NEVER replaced by STARTED OK, and nothing is pressed. FAILED stays exactly as
    written (one alert that says Dump to Grid is active now and this run did not CONFIRM it started it; neither schedule notification dismissed); a STARTING result becomes the FAILED TO START text that says so (same alert,
    nothing dismissed); CANCELLED stays exactly as written, no alert (the alert condition excludes it), the notifications dismissed as before."""
    bad: list[str] = []
    try:
        for label, wait, change, when, delay, window, kind in CONTROLS12:
            f = end_run(dump_text, wait, change, when, delay, window)
            last = f["last"]
            base = (f["went_active"] and "STARTED" not in last and OVERWRITE_TEXT not in last and f["presses"] == [] and f["gate"] == [] and f["started"] == 0
                    and f["arm"] == "off" and f["model_arm"] is False)
            if kind == "CANCELLED":
                ok = base and last.startswith("CANCELLED") and f["alerts"] == [] and f["dismissed"] == sorted([NOTE, NOTE_READY]) and f["notes_left"] == []
            else:
                shape = (last.startswith("FAILED TO START - authorised window ends") if kind == "FAILED" else re.fullmatch(FAILED_FINAL, last) is not None)
                ok = (base and shape and len(last) <= 255 and len(f["alerts"]) == 1
                      and re.fullmatch(re.escape(last) + "\n" + re.escape(ACTIVE_CONFIRM) + "\n" + ALERT_TAIL, f["notice"], re.S) is not None
                      and f["dismissed"] == [] and NOTE in f["notes_left"] and NOTE_READY in f["notes_left"])
            if not ok:
                bad.append(f"control, {label}: result {last[:70]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} left={f['notes_left']} presses={f['presses']}")
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
check("controls, owner decision r15 (the opposite of the old controls): a STARTING, a FAILED and a CANCELLED result with Dump to Grid active are NOT replaced by STARTED OK: FAILED stays as written with one alert ('this run did not confirm that it started it') and nothing dismissed; STARTING becomes the FAILED TO START text that says so (same alert); CANCELLED stays as written with no alert; nothing is pressed", cp == [], str(cp[:2]))
sp = start_time_problems(DUMP_TEXT)
check("start-time BLOCKED results, Dump to Grid already active: a Hold battery active at the start keeps its BLOCKED text and its one alert (which now carries the active-now sentence, the same alert); "
      "'BLOCKED - Dump to Grid already active' still raises no alert and still dismisses the schedule notifications; nothing staged or pressed", sp == [], str(sp[:2]))

print("[12] mutation: the old overwrite restored (unconditional, with a partial BLOCKED guard, or for a STARTING, FAILED or CANCELLED result), a STARTING result left as it is, a missing, unconditional, inverted or reworded sentence, and a skipped alert (the old dismissal) are each caught")
# Owner decision r15: the package's step after the loop now acts on a STARTING result only (NEW_STEP, from its first comment line to the step that follows it). The old behaviour is a mutant: _old_step() is the step as it
# stood at 0a488d8 (the r14 step: `active and not STARTED and not BLOCKED`), its `tail` argument being the end of its condition; _old_class_step() is the pre-r14 overwrite limited to one class.
_NEW_STEP_START = "          # Owner decision r15 (19 Nov 2026): the steps after the loop never turn a result into a success."
_NEW_STEP_END = ("          - if:\n              - condition: template\n                value_template: >-\n"
                 "                  {% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %}\n"
                 "                  {{ not is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')\n"
                 "                     and not r.startswith('STARTED') and not r.startswith('FAILED') and not r.startswith('CANCELLED')\n")


def new_step_of(text: str) -> str:
    a = text.find(_NEW_STEP_START)
    b = text.find(_NEW_STEP_END, a) if a >= 0 else -1
    return text[a:b] if a >= 0 and b > a else ""


NEW_STEP = new_step_of(DUMP_TEXT)
OLD_SUCCESS = '"STARTED OK - Dump to Grid is active; this run could not confirm the start as its own (check power, Stop SOC and end time)"'


def _old_step(tail: str, cond: str = "not r.startswith('STARTED')") -> str:
    return ("          - if:\n"
            "              - condition: template\n"
            "                value_template: >-\n"
            "                  {% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %}\n"
            "                  {{ is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and " + cond + tail + " }}\n"
            "            then:\n"
            "              - action: input_text.set_value\n"
            "                target:\n"
            "                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result\n"
            "                data:\n"
            "                  value: " + OLD_SUCCESS + "\n")


def _old_class_step(cls: str) -> str:
    return _old_step("", cond=f"r.startswith('{cls}')")


_FAILED_VALUE = ("                      value: >-\n"
                 "                        FAILED TO START - retries ended at {{ now().strftime('%H:%M') }}:\n"
                 "                        {{ states('sensor.ecco_clock_dongle_dump_to_grid_status')[:120] }};\n"
                 "                        Dump to Grid is active now, but this run did not confirm that it started it\n")
_IF_ACTIVE = "                {%- if is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') %}\n"
_BLOCKED_SENTENCE = ("                Dump to Grid is active now, and this run did not start it (it may have been started from the dongle's own Start button or by hand).\n"
                     "                Check it, and the plan overrides, before assuming it is held.\n")
_FAILED_SENTENCE = ("                Dump to Grid is active now, but this run did not confirm that it started it (it may have been started from the dongle's own Start button or by hand, "
                    "or, if a start transaction had begun, late by this run's own press).\n"
                    "                Check it, and the plan overrides, before assuming it is held.\n")
_SENTENCE_BLOCK = (_IF_ACTIVE + "\n"
                   "                {% if states('input_text.ecco_dump_to_grid_schedule_last_result').startswith('BLOCKED') -%}\n"
                   + _BLOCKED_SENTENCE +
                   "                {%- else -%}\n"
                   + _FAILED_SENTENCE +
                   "                {%- endif %}\n"
                   "                {%- endif %}\n")
_ALERT_IF = "              {{ r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)\n"
MUTANTS12 = [
    ("the old unconditional overwrite is restored (any result that is not STARTED becomes STARTED OK while Dump to Grid is active)", [(NEW_STEP, _old_step(""))]),
    ("the old guard covers only the Hold battery reason (OVERRIDE_ACTIVE)", [(NEW_STEP, _old_step("\n                     and 'reason OVERRIDE_ACTIVE' not in r"))]),
    ("the old guard covers the reserve reasons only (an override or an unreadable record is overwritten)", [(NEW_STEP, _old_step("\n                     and not (r.startswith('BLOCKED') and 'reason RESERVE' in r)"))]),
    ("the old guard covers every reason but RESERVE_TOO_HIGH", [(NEW_STEP, _old_step("\n                     and not (r.startswith('BLOCKED') and 'reason RESERVE_TOO_HIGH' not in r)"))]),
    ("the old overwrite is restored for a STARTING result (it becomes STARTED OK again, the old rule)", [(_FAILED_VALUE, "                      value: " + OLD_SUCCESS + "\n")]),
    ("the old overwrite is restored for a FAILED result (it becomes STARTED OK again, the old rule)", [(NEW_STEP, _old_class_step("FAILED") + NEW_STEP)]),
    ("the old overwrite is restored for a CANCELLED result (it becomes STARTED OK again, the old rule)", [(NEW_STEP, _old_class_step("CANCELLED") + NEW_STEP)]),
    ("a STARTING result with Dump to Grid active is left as STARTING (no final text, nothing alerted)", [("is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and r.startswith('STARTING') }}",
                                                                                                    "is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and r.startswith('STARTING_') }}")]),
    ("the alert is skipped while Dump to Grid is active, so the notifications are dismissed again (the old dismissal)",
     [(_ALERT_IF, "              {{ (r.startswith('FAILED') or (r.startswith('BLOCKED') and 'already active' not in r)) and not is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on')\n")]),
    ("the active-now sentence is missing", [(_SENTENCE_BLOCK, "")]),
    ("the active-now sentence is shown whether or not Dump to Grid is active", [(_IF_ACTIVE, "                {%- if true %}\n")]),
    ("the active-now sentence is shown when Dump to Grid is NOT active (inverted)", [(_IF_ACTIVE, _IF_ACTIVE.replace("'on')", "'off')"))]),
    ("the active-now sentence no longer says this run did not start it (BLOCKED)", [("Dump to Grid is active now, and this run did not start it", "Dump to Grid is running")]),
    ("the active-now sentence no longer asks for the plan overrides to be checked (BLOCKED)", [(_BLOCKED_SENTENCE, _BLOCKED_SENTENCE.replace("Check it, and the plan overrides, before assuming it is held.", "Check it."))]),
    ("the active-now sentence no longer asks for the plan overrides to be checked (FAILED)", [(_FAILED_SENTENCE, _FAILED_SENTENCE.replace("Check it, and the plan overrides, before assuming it is held.", "Check it."))]),
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


# ================================================================================================================================
print("[14] result status integrity (owner decision r15, 19 Nov 2026; known limitation 20, extended): the steps after the retry loop never turn a STARTING, FAILED, CANCELLED or BLOCKED result into STARTED OK")
# ================================================================================================================================
# THE DEFECT (limitation 20, extended). Since owner decision r14 a BLOCKED result is never overwritten, but the step after the scheduled start's retry loop still replaced EVERY other result that did not start with STARTED by
# "STARTED OK - Dump to Grid is active; this run could not confirm the start as its own ..." whenever Dump to Grid was active at the loop end, for ANY reason (the dongle's own Start button, which no override binds (RG-ST3), a
# manual start, another path): a start refused at the gate, a press nobody answered, a run the owner cancelled, a run still retrying. A rejected, failed or cancelled run was reported as a success, the end-of-run alert was
# skipped and the schedule notifications were dismissed.
# THE OWNER'S DECISION (r15): FAILED and CANCELLED are final and are never converted into success without a genuinely new, verified operation; STARTING may become STARTED only after a VERIFIED start of THIS run, which is the
# in-loop path (this run's own press, a start transaction that began, then Dump to Grid active: 'STARTED OK - ... (attempt N; ends by HH:MM)'), unchanged. So the steps after the loop write no success text at all:
#   - a FAILED, CANCELLED or BLOCKED result stays exactly as written; FAILED and BLOCKED raise the end-of-run alert (not dismissed), CANCELLED raises none (the alert condition is unchanged);
#   - a result still STARTING with Dump to Grid active has no verified start of this run: it becomes CANCELLED if the owner cancelled the schedule, else FAILED TO START with 'retries ended', the last dongle status, and
#     'Dump to Grid is active now, but this run did not confirm that it started it' (kept inside the 255-character helper limit);
#   - a result this script did not write (ARMED, REJECTED, MISSED, empty) is left alone;
#   - the alert's active-now sentence stays true for each result it can accompany: 'this run did not start it' for BLOCKED (nothing was pressed), 'did not CONFIRM that it started it' for FAILED (an unconfirmed outcome can be
#     a late start of this run's own press, which the sentence says);
#   - with Dump to Grid NOT active nothing changes.
# What is still true: a FAILED result can be a false negative when the dongle starts late after a start transaction that began (the stalled-view run below); the alert flags it with the active-now sentence.
# The proof: [14.1] the real steps after the loop and the end-of-run alert, run on their own (a probe script made from the package's own steps, so a change to those steps is what is tested) for 19 result texts x Dump to Grid
# active or not x armed (valid, disarmed, re-armed since the run began); with Dump to Grid not active the outcome must equal the PREVIOUS package's (rebuilt from this package, its code lines pinned by sha256).
# [14.2] end-to-end runs through the real retry loop for every in-loop result a late or foreign activation can meet, and for every shape in which this run's own verified start still ends as STARTED OK. [14.3] mutants.
OLD_CODE_SHA = "e1128832f638f3c5219036feeb31ee4def7d6283d3e03eff761e6f5cfa908457"   # sha256 of the previous package (0a488d8) without its whole-line comments
# Owner decision r15, the startup recovery (see [15]): the package of e1005ad wrote STARTED OK in the recovery's active branch whatever the last result was. REC_OLD_BLOCK is that branch as it stood (its comment line through its disarm);
# the new branch is taken from a package between its own comment line and the comment of the branch that follows it. undo_recovery() puts the old branch back, so before_text() below still rebuilds the package of 0a488d8 and the pin
# OLD_CODE_SHA above is unchanged (a package without the new branch is left as it is: there is nothing to undo).
_REC_START = "          # Restarted while the session runs and Dump to Grid is active."
_REC_END = "          # R9: a start time between the Home Assistant start and this evaluation is not a missed run"
REC_OLD_BLOCK = (
    "          # Restarted while the session runs: it started; record it and disarm.\n"
    "          - conditions:\n"
    "              - condition: template\n"
    "                value_template: \"{{ now_ts < end_ts }}\"\n"
    "              - condition: state\n"
    "                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n"
    "                state: \"on\"\n"
    "            sequence:\n"
    "              - action: input_text.set_value\n"
    "                target:\n"
    "                  entity_id: input_text.ecco_dump_to_grid_schedule_last_result\n"
    "                data:\n"
    "                  value: \"STARTED OK - running (Home Assistant restarted during the session)\"\n"
    "              - action: input_boolean.turn_off\n"
    "                target:\n"
    "                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed\n")


def rec_new_block(text: str) -> str:
    a = text.find(_REC_START)
    b = text.find(_REC_END, a) if a >= 0 else -1
    return text[a:b] if a >= 0 and b > a else ""


def undo_recovery(text: str) -> str:
    """The package with the recovery's active branch as it stood at e1005ad (the text unchanged when it has no new branch)."""
    nb = rec_new_block(text)
    return text.replace(nb, REC_OLD_BLOCK) if nb and text.count(nb) == 1 else text


# R9 (the clock-change refusals, owner decision of 20 Nov 2026, proposals P-A and P-B) is merged under this change: the package now carries R9's five declared Dump pairs (DUMP_6 to DUMP_10 of the r9 scope module: the header
# comment, the arm validation's refusal of a skipped, repeated or unreadable start time, and the TOU overlap walk on real instants). They are NOT part of the previous package (0a488d8, e1005ad), so the rebuild of the previous
# package starts by undoing EXACTLY those pairs with the r9 scope module's own strict reverter (every 'after' text present exactly once, every 'before' anchor unique afterwards: an AssertionError otherwise). The two code-line
# pins (OLD_CODE_SHA, PREV_CODE_SHA) are therefore unchanged and prove that the whole difference between this package and the previous one is R9's declared pairs plus this change's own edits, and nothing else.
R9_CLOCK_PAIRS = (
    (_r9s.DUMP_6_OLD, _r9s.DUMP_6_NEW),
    (_r9s.DUMP_7_OLD, _r9s.DUMP_7_NEW),
    (_r9s.DUMP_8_OLD, _r9s.DUMP_8_NEW),
    (_r9s.DUMP_9_OLD, _r9s.DUMP_9_NEW),
    (_r9s.DUMP_10_OLD, _r9s.DUMP_10_NEW),
)


def undo_clock_changes(text: str) -> str:
    """The package without R9's five declared clock-change pairs; AssertionError unless every one of them is present exactly once (and every anchor is unique afterwards)."""
    return _r9s._revert(text, R9_CLOCK_PAIRS, "the previous package (R9's clock-change pairs)")


_OLD_SENTENCE_BLOCK = _IF_ACTIVE + "\n" + _BLOCKED_SENTENCE + "                {%- endif %}\n"
_R14_TAIL = "\n                     and not r.startswith('BLOCKED')"


def before_text(text: str) -> str:
    """The previous package (0a488d8: the r14 step that spares BLOCKED only, and the one-sentence alert), rebuilt from `text` by undoing exactly the two code edits of this change (and, since [15], the recovery's)."""
    text = undo_recovery(undo_clock_changes(text))
    ns = new_step_of(text)
    if not ns or text.count(_SENTENCE_BLOCK) != 1:
        return text                              # nothing of this change to undo: this IS the previous package
    return text.replace(ns, _old_step(_R14_TAIL)).replace(_SENTENCE_BLOCK, _OLD_SENTENCE_BLOCK)


def code_sha(text: str) -> str:
    import hashlib
    return hashlib.sha256("\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("#")).encode("utf-8")).hexdigest()


BEFORE_TEXT = before_text(DUMP_TEXT)
check("the previous package, rebuilt from this one by undoing the two code edits of this change, has exactly the code lines of 0a488d8 (sha256 of everything but whole-line comments), so the 'Dump to Grid not active: "
      "unchanged' comparison below is against the real previous behaviour", code_sha(BEFORE_TEXT) == OLD_CODE_SHA and (BEFORE_TEXT != DUMP_TEXT or NEW_STEP == ""), code_sha(BEFORE_TEXT)[:16])

POST_PROBE = "ecco_post_loop_probe"
STATUS14 = "ACTIVE - VERIFIED OK; target 3000W export - SETTLING - battery ceiling 2000W (feed-forward start: house 1416W, PV 0W); Stop SOC 40% " + "x" * 90   # longer than the 120 characters the text keeps
ARMED_MODES = ("valid", "off", "rearmed")      # armed and untouched since the run began / disarmed (the cancel) / armed again after the run began (a re-arm)
BOTH = sorted([NOTE, NOTE_READY])


_parsed: dict = {}


def probe_packages(dump_text: str) -> list:
    """The three packages with one more script: the package's own steps after the retry loop, then its steps after the choose (the write enable off, the end-of-run alert). Nothing is copied by hand."""
    import copy
    if dump_text not in _parsed:
        _parsed[dump_text] = [yaml.safe_load(t) for t in (dump_text, PLAN_TEXT, GUARD_TEXT)]
    pkgs = copy.deepcopy(_parsed[dump_text])
    seq = pkgs[0]["script"][SCHED]["sequence"]
    ti = next(i for i, a in enumerate(seq) if "choose" in a)
    default = seq[ti]["default"]
    ri = next(i for i, a in enumerate(default) if "repeat" in a)
    pkgs[0]["script"][POST_PROBE] = {"alias": "probe: the steps after the retry loop", "mode": "single", "sequence": default[ri + 1:] + seq[ti + 1:]}
    return pkgs


def probe(dump_text: str, result: str, active: bool, armed: str, status: str = STATUS14) -> dict:
    pw, d = world(pkgs=probe_packages(dump_text), owner=40)
    w = pw.w
    w.set(LAST, result)
    d.status = status
    w.set(D.D_STATUS, status)
    if active:
        d.active = True
        w.set(D.D_ACTIVE, "on")
    d.arm = True
    w.set(D.D_ARM, "on")
    if armed == "off":
        w.set(ARMED, "off")
    run_started = (w.t + 600) if armed in ("valid", "off") else (w.t - 3600)      # "rearmed": armed is on, but it changed after the run began
    w.notifications[NOTE] = {"title": "earlier alert", "message": "an alert from an earlier run"}
    w.notifications[NOTE_READY] = {"title": "earlier readiness alert", "message": "a readiness alert from an earlier run"}
    n0 = len(w.service_log)
    pw.ha.start_script(POST_PROBE, {"window_end": w.t + 1800, "run_started": run_started})
    w.run_until(w.t + 30)
    return dict(last=pw.state(LAST), alerts=[n for n in w.notification_log if n[1] == "create" and n[2] == NOTE], notice=w.notifications.get(NOTE, {}).get("message", ""),
                dismissed=sorted(n[2] for n in w.notification_log if n[1] == "dismiss"), arm=pw.state(D.D_ARM), presses=list(d.press_log), numbers=list(d.number_log),
                calls=sorted({s for _t, s, _e, _d in w.service_log[n0:]}), warnings=list(w.warnings))


# (label, class, the result text at the loop end). The texts are the package's own, one per way a run can end its loop (the five STARTING texts, the in-loop STARTED OK, the five FAILED texts, both CANCELLED texts,
# the press-time BLOCKED texts) and the four a different writer can leave there (the arm validation's ARMED and REJECTED, the watchdog's MISSED, an empty helper).
CELLS14 = (
    ("STARTING, the run is waiting for the dongle", "STARTING", "STARTING - attempt 3 waiting: dongle offline or another write in progress; retrying until 21:10"),
    ("STARTING, refused at the start gate", "STARTING", "STARTING - attempt 2 refused at the start gate (REJECTED - RTC correction currently active); nothing written; retrying until 21:10"),
    ("STARTING, the press never reached the dongle", "STARTING", "STARTING - attempt 2 never reached the dongle (no start counted); retrying until 21:10"),
    ("STARTING, arm or staged values not confirmed", "STARTING", "STARTING - attempt 4: arm or staged values not confirmed; nothing pressed; retrying until 21:10"),
    ("STARTING, the first text of a run", "STARTING", "STARTING - 2000W, Stop SOC 40% (raised from 25% to the effective reserve), until 21:31"),
    ("STARTED, this run's own verified start", "STARTED", "STARTED OK - 2000W for 30 min, Stop SOC 40% (attempt 1; ends by 21:31)"),
    ("FAILED, the authorised window is over", "FAILED", "FAILED TO START - authorised window ends 21:31; not started (Inactive)"),
    ("FAILED, refused at the gate, nothing written", "FAILED", "FAILED TO START - REJECTED - RECOVERY BLOCKED: durable recovery marker exists but its snapshot data cannot be trusted; deliberate recovery (attempt 1; nothing written)"),
    ("FAILED, a start transaction began and failed", "FAILED", "FAILED TO START - START FAILED - could not capture/durably commit inverter snapshot; nothing written (start transaction began on attempt 1; not retried)"),
    ("FAILED, no answer, outcome unconfirmed", "FAILED", "FAILED TO START - no answer from the dongle to attempt 1; outcome unconfirmed, not retried (last status: Inactive)"),
    ("FAILED, retries ended", "FAILED", "FAILED TO START - retries ended at 21:10: Inactive"),
    ("CANCELLED, written by the retry loop", "CANCELLED", CANCELLED_TEXT),
    ("CANCELLED, written by the cancel script", "CANCELLED", "CANCELLED - scheduled event disarmed"),
    ("BLOCKED, the press-time recheck (an override)", "BLOCKED", "BLOCKED - a Hold battery, Skip tonight or Prepare for power cut became active while this run was waiting (hold_battery); nothing started (reason OVERRIDE_ACTIVE)"),
    ("BLOCKED, the press-time recheck (the reserve)", "BLOCKED", "BLOCKED - the effective reserve rose above the Stop SOC staged for this run (40%) while it was waiting; nothing started (reason RESERVE_TOO_HIGH)"),
    ("ARMED, the owner armed a new schedule during the run", "FOREIGN", "ARMED - 2026-11-17 22:00:00 \u2022 30 min \u2022 2000W \u2022 Stop SOC 40%"),
    ("REJECTED, written by the arm validation", "FOREIGN", "REJECTED - scheduled start must be in the future"),
    ("MISSED, written by the watchdog or the startup recovery", "FOREIGN", "MISSED - not started after a Home Assistant restart"),
    ("empty", "FOREIGN", ""),
)
_before_cache: dict = {}


def probe_before(result: str, active: bool, armed: str) -> dict:
    key = (result, active, armed)
    if key not in _before_cache:
        _before_cache[key] = probe(BEFORE_TEXT, result, active, armed)
    return _before_cache[key]


def notice_is(f: dict, sentence: str | None) -> bool:
    """The alert's message is the result text, then (only while Dump to Grid is active) the sentence, then the usual tail."""
    mid = "" if sentence is None else "\n" + re.escape(sentence)
    return re.fullmatch(re.escape(f["last"]) + mid + "\n" + ALERT_TAIL, f["notice"], re.S) is not None


def cell_check(kind: str, text: str, active: bool, armed: str, f: dict) -> str:
    """'' when the cell is right, else why not."""
    last = f["last"]
    if f["arm"] != "off" or f["presses"] or f["numbers"]:
        return f"the write enable is {f['arm']!r}, presses {f['presses']}, numbers {f['numbers']}: nothing may be pressed or staged after the loop and the write enable ends off"
    if not set(f["calls"]) <= {"input_text.set_value", "switch.turn_off", "persistent_notification.create", "persistent_notification.dismiss"}:
        return f"services called: {f['calls']}"
    if any("invalid value" in m for m in f["warnings"]):
        return f"a text did not fit the helper: {f['warnings'][:1]}"
    if not active:
        g = probe_before(text, active, armed)
        diff = [k for k in g if f[k] != g[k]]
        return f"Dump to Grid not active, but the outcome differs from the previous package in {diff}: {last[:70]!r} vs {g['last'][:70]!r}" if diff else ""
    if "could not confirm the start as its own" in last or (last.startswith("STARTED") and kind != "STARTED"):
        return f"a result of class {kind} was turned into a success: {last[:90]!r}"
    if kind == "STARTING" and armed == "valid":
        m = re.fullmatch(FAILED_FINAL, last)
        ok = (m is not None and m.group(1) == STATUS14[:120] and len(last) <= 255 and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_CONFIRM) and f["dismissed"] == [])
        return "" if ok else f"a STARTING result with Dump to Grid active must end as the FAILED TO START text (retries ended, the last status, active now, not confirmed), alerted, nothing dismissed: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    if kind == "STARTING":
        ok = last == CANCELLED_TEXT and f["alerts"] == [] and f["dismissed"] == BOTH
        return "" if ok else f"a STARTING result of a cancelled run (armed {armed}) must end as CANCELLED, with no alert: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    if kind == "STARTED":
        ok = last == text and f["alerts"] == [] and f["dismissed"] == BOTH
        return "" if ok else f"a verified STARTED OK must stay exactly as written, with no alert: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    if kind == "FAILED":
        ok = last == text and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_CONFIRM) and f["dismissed"] == []
        return "" if ok else f"a FAILED result must stay exactly as written, alerted with 'did not confirm that it started it', nothing dismissed: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} notice={f['notice'][-170:-60]!r}"
    if kind == "CANCELLED":
        ok = last == text and f["alerts"] == [] and f["dismissed"] == BOTH
        return "" if ok else f"a CANCELLED result must stay exactly as written, with no failure alert: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    if kind == "BLOCKED":
        ok = last == text and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_NOW) and f["dismissed"] == [] and "did not confirm" not in f["notice"]
        return "" if ok else f"a BLOCKED result must stay exactly as written, alerted with 'this run did not start it', nothing dismissed: {last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    ok = last == text and f["alerts"] == [] and f["dismissed"] == BOTH
    return "" if ok else f"a result this script did not write must be left alone: {last[:90]!r} (was {text[:40]!r}) alerts={len(f['alerts'])} dismissed={f['dismissed']}"


def cell_problems(dump_text: str, stop_early: bool = False, kinds=None) -> list[str]:
    bad: list[str] = []
    try:
        for label, kind, text in CELLS14:
            if kinds is not None and kind not in kinds:
                continue
            for active in (True, False):
                for armed in ARMED_MODES:
                    why = cell_check(kind, text, active, armed, probe(dump_text, text, active, armed))
                    if why:
                        bad.append(f"{label}, Dump to Grid {'active' if active else 'not active'}, armed={armed}: {why}")
                        if stop_early:
                            return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


print("[14.1] the steps after the retry loop, every result class x Dump to Grid active or not x armed")
cp14: list[str] = []
for kinds, what in ((("STARTING",), "a STARTING result (five texts: waiting, refused at the gate, never reached the dongle, values not confirmed, the first text)"),
                    (("FAILED",), "a FAILED result (five texts: window over, refused with nothing written, a start transaction began and failed, no answer and unconfirmed, retries ended)"),
                    (("CANCELLED",), "a CANCELLED result (the loop's text and the cancel script's)"),
                    (("BLOCKED",), "a press-time BLOCKED result (an override, the reserve)"),
                    (("STARTED", "FOREIGN"), "this run's own verified STARTED OK, and a result another writer left (ARMED, REJECTED, MISSED, empty)")):
    kp = cell_problems(DUMP_TEXT, kinds=kinds)
    cp14 += kp
    check(f"{what}: with Dump to Grid ACTIVE it is never turned into a success text "
          + {"STARTING": "(armed and untouched: the FAILED TO START text, 'retries ended', the last status, Dump to Grid is active now, this run did not confirm that it started it, within 255 characters, one alert, nothing dismissed; "
                         "cancelled or re-armed: CANCELLED, no alert)",
             "FAILED": "(exactly as written; one alert whose sentence says this run did not CONFIRM that it started it; nothing dismissed)",
             "CANCELLED": "(exactly as written; no failure alert)",
             "BLOCKED": "(exactly as written; one alert whose sentence says this run did not start it; nothing dismissed)",
             "STARTED": "(left exactly as written, no alert)"}[kinds[0]]
          + "; with Dump to Grid NOT active the outcome (final text, alerts, message, dismissals, services) equals the previous package's, armed, disarmed and re-armed; nothing pressed or staged after the loop; the write enable ends off",
          kp == [], str(kp[:2]))

# ---- [14.2] end to end -------------------------------------------------------------------------------------------------------------------------------------------------------------
print("[14.2] end to end: the real retry loop, then the steps after it")
STARTED_RE = r"STARTED OK - 2000W for \d+ min, Stop SOC 40% \(attempt (\d+); ends by \d\d:\d\d\)"


def arm_busy(pw):                        # the owner disarms the schedule 15 s into a busy wait
    pw.w.set(ARMED, "off")


def cancel_script(pw):                   # the owner's Cancel: the real cancel script (disarms, writes its own CANCELLED text)
    pw.ha.start_script("ecco_dump_to_grid_cancel_schedule", {})


def cancel_and_active(pw):               # the owner disarms the schedule while Dump to Grid becomes active some other way, both before the loop's next look
    pw.w.set(ARMED, "off")
    pw.w.set(D.D_ACTIVE, "on")


def rearm_and_active(pw):                # the owner arms a new schedule while Dump to Grid becomes active; the arm validation (an automation this harness does not run) writes its ARMED text, written here as it would
    pw.w.set(ARMED, "off")
    pw.w.set(ARMED, "on")
    pw.w.set(LAST, "ARMED - 2026-11-17 22:00:00 \u2022 30 min \u2022 2000W \u2022 Stop SOC 40%")
    pw.w.set(D.D_ACTIVE, "on")


def sv(**kw):
    return lambda pw, d, t0: [setattr(d, k, v) if k != "rtc" else d.rtc.append((t0 + v[0], t0 + v[1])) for k, v in kw.items()]


def fail_press(n):
    return lambda pw, d, t0: pw.w.fail_services.__setitem__("button.press", n)


def stall(a, b):
    return lambda pw, d, t0: d.stalls.append((t0 + a, t0 + b))


def flag(name):
    return lambda pw, d, t0: d.flags.__setitem__(name, True)


# (label, class, end_run arguments). `when`: Dump to Grid becomes active (the dongle's own Start button or a manual start) `delay` s after the result text first satisfies it.
E2E14 = (
    ("STARTING: the run waits for a busy dongle and Dump to Grid becomes active 2 s after the waiting text", "S", dict(wait="busy", active_when=lambda t: t.startswith("STARTING - attempt 1 waiting"), active_delay=2.0)),
    ("STARTING: a start refused at the gate for a transient reason (RTC correction), Dump to Grid becomes active during the retry", "S",
     dict(wait="none", active_when=lambda t: t.startswith("STARTING - attempt 1 refused at the start gate"), active_delay=1.0, setup=lambda pw, d, t0: d.rtc.append((t0 - 5, t0 + 300)))),
    ("STARTING: a press that never reached the dongle (one service error), Dump to Grid becomes active as the text is written (no pause follows it)", "S",
     dict(wait="none", active_when=lambda t: t.startswith("STARTING - attempt 1 never reached"), active_delay=0.0, setup=fail_press(1))),
    ("STARTING: staging that never reaches the dongle (arm or staged values not confirmed), Dump to Grid becomes active during the pause", "S",
     dict(wait="none", active_when=lambda t: "arm or staged values not confirmed" in t, active_delay=1.0, setup=lambda pw, d, t0: setattr(d, "drop_numbers", True))),
    ("FAILED: the authorised window is nearly over (20 s), Dump to Grid becomes active as the text is written", "F", dict(wait="none", active_when=lambda t: t.startswith("FAILED"), window=20.0)),
    ("FAILED: refused at the gate for a reason that needs the owner (recovery blocked): nothing written; Dump to Grid becomes active as the text is written", "F",
     dict(wait="none", active_when=lambda t: t.startswith("FAILED"), setup=flag("corrupt"))),
    ("FAILED: a start transaction began and failed; Dump to Grid becomes active (another path) as the text is written", "F",
     dict(wait="none", active_when=lambda t: t.startswith("FAILED"), setup=lambda pw, d, t0: setattr(d, "outcome", "capture_failed"))),
    ("FAILED, a late start of THIS run's own press: the view stalls right after the press; the outcome is unconfirmed (one transaction, never two), then the dongle shows Dump to Grid active", "L", dict(wait="none", setup=stall(1.05, 45.0), seconds=200.0)),
    ("CANCELLED: the schedule is disarmed during the wait, Dump to Grid becomes active as the CANCELLED text is written", "C", dict(wait="busy", change=arm_busy, active_when=lambda t: t.startswith("CANCELLED"))),
    ("CANCELLED: the real cancel script runs during the wait, Dump to Grid becomes active as its text is written", "C", dict(wait="busy", change=cancel_script, active_when=lambda t: t.startswith("CANCELLED"))),
    ("STARTING and cancelled: the schedule is disarmed and Dump to Grid becomes active at the same moment, before the loop looks again", "C", dict(wait="busy", change=cancel_and_active)),
    ("another writer's result: the owner arms a new schedule during the wait (the arm validation's ARMED text, written by the harness) while Dump to Grid becomes active", "R", dict(wait="busy", change=rearm_and_active)),
)
# every shape in which this run's own verified start ends as STARTED OK (the in-loop path, unchanged): (label, minimum attempt number, end_run arguments)
OK14 = (
    ("immediate: the first press passes, Dump to Grid active within a few seconds", 1, dict(wait="none")),
    ("a slow start transaction (70 s): waited for, one transaction", 1, dict(wait="none", setup=sv(transaction_s=70.0), seconds=300.0)),
    ("active after a retry: the first three presses are refused at the gate (RTC correction)", 2, dict(wait="none", setup=sv(rtc=(-5, 20)))),
    ("active after a press that never reached the dongle, retried once", 2, dict(wait="none", setup=fail_press(1))),
    ("active after waiting for a busy dongle (45 s)", 1, dict(wait="busy")),
    ("active after waiting for an offline dongle (45 s)", 1, dict(wait="offline")),
    ("the view stalls AFTER the start began (the transaction is seen to begin, Dump to Grid active is seen when the view recovers)", 1, dict(wait="none", setup=stall(2.0, 45.0), seconds=200.0)),
)


def e2e_check(kind: str, f: dict, ref: dict | None) -> str:
    last = f["last"]
    if f["arm"] != "off" or f["model_arm"] is not False:
        return f"the write enable ends {f['arm']}/{f['model_arm']}"
    if "could not confirm the start as its own" in last or last.startswith("STARTED"):
        return f"turned into a success: {last[:90]!r}"
    if kind == "S":
        ok = (f["went_active"] and re.fullmatch(FAILED_FINAL, last) is not None and len(last) <= 255 and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_CONFIRM)
              and f["dismissed"] == [] and NOTE in f["notes_left"] and NOTE_READY in f["notes_left"] and f["started"] == 0 and not any(o == "PASSED" for _t, o in f["gate"]))
        return "" if ok else f"{last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} gate={f['gate'][:2]} started={f['started']}"
    if kind == "F":
        ok = (f["went_active"] and last == ref["last"] and last.startswith("FAILED TO START - ") and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_CONFIRM) and f["dismissed"] == []
              and NOTE in f["notes_left"] and NOTE_READY in f["notes_left"] and f["presses"] == ref["presses"] and f["gate"] == ref["gate"] and len(ref["alerts"]) == 1 and notice_is(ref, None))
        return "" if ok else f"{last[:90]!r} (without Dump to Grid active: {ref['last'][:60]!r}) alerts={len(f['alerts'])} dismissed={f['dismissed']} presses={f['presses']} vs {ref['presses']}"
    if kind == "L":
        ok = (last.startswith("FAILED TO START - no answer from the dongle to attempt 1; outcome unconfirmed") and f["started"] == 1 and len(f["presses"]) == 1 and f["active_end"] == "on"
              and len(f["alerts"]) == 1 and notice_is(f, ACTIVE_CONFIRM) and f["dismissed"] == [])
        return "" if ok else f"{last[:90]!r} started={f['started']} presses={f['presses']} active={f['active_end']} alerts={len(f['alerts'])} dismissed={f['dismissed']}"
    if kind == "C":
        ok = (f["active_end"] == "on" and last.startswith("CANCELLED") and f["alerts"] == [] and f["dismissed"] == BOTH and f["notes_left"] == [] and f["presses"] == [] and f["started"] == 0)
        return "" if ok else f"{last[:90]!r} alerts={len(f['alerts'])} dismissed={f['dismissed']} presses={f['presses']}"
    ok = (f["active_end"] == "on" and last.startswith("ARMED - ") and f["alerts"] == [] and f["presses"] == [] and f["started"] == 0)
    return "" if ok else f"{last[:90]!r} alerts={len(f['alerts'])} presses={f['presses']}"


def e2e_problems(dump_text: str, stop_early: bool = False, ok_shapes: bool = True, others: bool = True) -> list[str]:
    bad: list[str] = []
    try:
        if ok_shapes:
            for label, min_attempt, kw in OK14:
                f = end_run(dump_text, **kw)
                m = re.fullmatch(STARTED_RE, f["last"])
                ok = (m is not None and int(m.group(1)) >= min_attempt and "could not confirm" not in f["last"] and f["started"] == 1 and sum(1 for _t, o in f["gate"] if o == "PASSED") == 1
                      and f["alerts"] == [] and f["dismissed"] == BOTH and f["notes_left"] == [] and f["arm"] == "off" and f["model_arm"] is False and f["active_end"] == "on")
                if not ok:
                    bad.append(f"verified start, {label}: {f['last'][:90]!r} started={f['started']} gate={f['gate'][:3]} alerts={len(f['alerts'])} dismissed={f['dismissed']}")
                    if stop_early:
                        return bad
        if others:
            for label, kind, kw in E2E14:
                f = end_run(dump_text, **kw)
                ref = end_run(dump_text, **{k: v for k, v in kw.items() if k != "active_when"}) if kind == "F" else None
                why = e2e_check(kind, f, ref)
                if why:
                    bad.append(f"{label}: {why}")
                    if stop_early:
                        return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


def all14_problems(dump_text: str) -> list[str]:
    """Every behaviour check of this section, in cost order, stopping at the first failure (a mutant is caught when any of them fails)."""
    for fn in (lambda t: cell_problems(t, stop_early=True), lambda t: e2e_problems(t, stop_early=True)):
        found = fn(dump_text)
        if found:
            return found
    return []


ok14 = e2e_problems(DUMP_TEXT, others=False)
check(f"this run's own VERIFIED start still ends as STARTED OK, byte for byte the in-loop text 'STARTED OK - 2000W for N min, Stop SOC 40% (attempt K; ends by HH:MM)' (never the fallback text), in all {len(OK14)} shapes: "
      "immediate, a slow transaction, after a retry, after a press that never arrived, after a busy and an offline wait, and a stalled view after the start began; one transaction, no alert, both schedule notifications dismissed, "
      "the write enable off", ok14 == [], str(ok14[:2]))
for label, kind, kw in E2E14:
    f = end_run(DUMP_TEXT, **kw)
    ref = end_run(DUMP_TEXT, **{k: v for k, v in kw.items() if k != "active_when"}) if kind == "F" else None
    why = e2e_check(kind, f, ref)
    check(f"end to end, {label}: "
          + {"S": "the run ends as the FAILED TO START text that says Dump to Grid is active now and this run did not confirm that it started it (never STARTED OK), one alert, nothing dismissed, no start of this run",
             "F": "the FAILED text stays exactly as the loop wrote it, one alert that says this run did not CONFIRM that it started it, nothing dismissed, no press after the loop",
             "L": "the FAILED (unconfirmed) text stays, one transaction, and the alert says Dump to Grid is active now and this run did not confirm that it started it (a late start of this run's own press: a false negative the alert flags)",
             "C": "the result stays CANCELLED, no failure alert, nothing pressed",
             "R": "the ARMED text the new schedule's arming wrote stays (it is not replaced by a success), no failure alert, nothing pressed"}[kind], why == "", why)

# ---- [14.3] mutants -----------------------------------------------------------------------------------------------------------------------------------------------------------------
print("[14.3] mutation: the old overwrite restored per class, a success text added after the loop, the cancel and sentence variants, the in-loop path broken: each is caught")
_FAILED_SENTENCE_BRANCH = "                {%- else -%}\n" + _FAILED_SENTENCE
_CANCEL_COND = "value_template: >-\n                          {{ not (is_state('input_boolean.ecco_dump_to_grid_schedule_armed', 'on')"
_INLOOP_IF = ("                                - if:\n                                    - condition: state\n                                      entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n"
              "                                      state: \"on\"\n                                  then:\n")
_INLOOP_TEXT = "(attempt {{ repeat.index }}; ends by"
_PRESS_STEP = "          - action: button.press\n            target:\n              entity_id: button.ecco_clock_dongle_start_dump_to_grid_now\n"
MUTANTS14 = [
    ("a success text is written for a result another writer left (the old fallback limited to ARMED, REJECTED, MISSED and empty)",
     [(NEW_STEP, _old_step("\n                     and not r.startswith('STARTING') and not r.startswith('FAILED') and not r.startswith('CANCELLED') and not r.startswith('BLOCKED')") + NEW_STEP)]),
    ("the old overwrite is restored for a BLOCKED result (the pre-r14 rule)", [(NEW_STEP, _old_class_step("BLOCKED") + NEW_STEP)]),
    ("the old overwrite is restored for a FAILED result (the old rule)", [(NEW_STEP, _old_class_step("FAILED") + NEW_STEP)]),
    ("the old overwrite is restored for a CANCELLED result (the old rule)", [(NEW_STEP, _old_class_step("CANCELLED") + NEW_STEP)]),
    ("the old overwrite is restored for a STARTING result (it becomes STARTED OK again)", [(_FAILED_VALUE, "                      value: " + OLD_SUCCESS + "\n")]),
    ("the old unconditional overwrite is restored (every result but STARTED)", [(NEW_STEP, _old_step(""))]),
    ("the step acts on every result while Dump to Grid is active (a FAILED, CANCELLED or BLOCKED result is rewritten as the FAILED TO START text)",
     [("is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') and r.startswith('STARTING') }}", "is_state('binary_sensor.ecco_clock_dongle_dump_to_grid_active', 'on') }}")]),
    ("the step also rewrites this run's own verified STARTED OK as FAILED", [("and r.startswith('STARTING') }}", "and (r.startswith('STARTING') or r.startswith('STARTED')) }}")]),
    ("the step also rewrites a CANCELLED result as FAILED", [("and r.startswith('STARTING') }}", "and (r.startswith('STARTING') or r.startswith('CANCELLED')) }}")]),
    ("the step also rewrites a FAILED result (the last status of a different attempt replaces it)", [("and r.startswith('STARTING') }}", "and (r.startswith('STARTING') or r.startswith('FAILED')) }}")]),
    ("a cancelled run with Dump to Grid active is reported as FAILED (the cancel branch never fires)", [(_CANCEL_COND, _CANCEL_COND.replace("{{ not (", "{{ false and ("))]),
    ("a run that was NOT cancelled is reported as CANCELLED (the cancel branch inverted)", [(_CANCEL_COND, _CANCEL_COND.replace("{{ not (", "{{ ("))]),
    ("the FAILED TO START text no longer says that this run did not confirm that it started it", [(_FAILED_VALUE, _FAILED_VALUE.replace("Dump to Grid is active now, but this run did not confirm that it started it\n", "Dump to Grid is active now\n"))]),
    ("the FAILED TO START text claims that this run started it", [(_FAILED_VALUE, _FAILED_VALUE.replace("but this run did not confirm that it started it", "and this run started it"))]),
    ("the FAILED TO START text drops the last status", [(_FAILED_VALUE, _FAILED_VALUE.replace("                        {{ states('sensor.ecco_clock_dongle_dump_to_grid_status')[:120] }};\n", ""))]),
    ("the FAILED TO START text keeps the whole last status (not cut at 120 characters: it can exceed the 255-character helper)",
     [(_FAILED_VALUE, _FAILED_VALUE.replace("[:120]", ""))]),
    ("the alert's sentence says 'this run did not start it' for a FAILED result too (an unconfirmed outcome can be a late start of this run's own press)", [(_FAILED_SENTENCE, _BLOCKED_SENTENCE)]),
    ("the alert's sentence says 'did not confirm' for a BLOCKED result (nothing was pressed: it did not start it)", [(_BLOCKED_SENTENCE, _FAILED_SENTENCE)]),
    ("the alert has no sentence for a FAILED result", [(_FAILED_SENTENCE_BRANCH, "")]),
    ("a press follows the steps after the loop", [(NEW_STEP, NEW_STEP + _PRESS_STEP)]),
    ("the in-loop path writes STARTED OK when Dump to Grid is NOT active after the transaction (a failed start reads as success)", [(_INLOOP_IF, _INLOOP_IF.replace('state: "on"', 'state: "off"'))]),
    ("the in-loop STARTED OK text says the start could not be confirmed as this run's own", [(_INLOOP_TEXT, "(attempt {{ repeat.index }}; could not confirm the start as its own; ends by")]),
]
caught14 = 0
built14 = 0
for label, edits in MUTANTS14:
    mutated = DUMP_TEXT
    ok_built = True
    for old, new in edits:
        if not old or mutated.count(old) != 1:
            ok_built = False
            check(f"mutant anchor: {label}", False, f"anchor found {mutated.count(old) if old else 0}x: {old[:70]!r}")
            break
        mutated = mutated.replace(old, new)
    if not ok_built:
        continue
    built14 += 1
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = all14_problems(mutated)
    if found:
        caught14 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS14)} mutants of the steps after the loop, the end-of-run alert and the in-loop path (the old overwrite restored for each class among them), all caught by the table or a running scheduled start",
      caught14 == len(MUTANTS14) == built14, f"{caught14}/{built14}/{len(MUTANTS14)}")
check("control: the unmutated package passes the same table and running cases", cp14 == [] and ok14 == [] and not [1 for label, kind, kw in E2E14 if e2e_check(kind, end_run(DUMP_TEXT, **kw), end_run(DUMP_TEXT, **{k: v for k, v in kw.items() if k != "active_when"}) if kind == "F" else None)])

# ================================================================================================================================
print("[15] the startup recovery after a Home Assistant restart never writes STARTED OK over a result this schedule did not verify (owner decision r15, 19 Nov 2026; known limitation 20, its last path)")
# ================================================================================================================================
# THE DEFECT (limitation 20, the last path). The startup recovery (ecco_dump_to_grid_schedule_startup_recovery) wrote "STARTED OK - running (Home Assistant restarted during the session)" whenever the schedule was armed, now was
# inside the window and Dump to Grid was active, WHATEVER the last result was. So a run that was refused (BLOCKED), failed, cancelled, or killed by the restart while still STARTING was reported as a success whenever Dump to Grid
# was active for ANY reason (the dongle's own Start button, which no override binds (RG-ST3), a manual start, another path), with nobody having verified that this schedule started it.
# THE OWNER'S DECISION (r15): protect STARTING, FAILED and CANCELLED from incorrect STARTED OK overwrites; preserve the legitimate transition (STARTING may become STARTED after a verified successful start); FAILED and CANCELLED
# are never converted into success without a genuinely new, verified operation; every final status reflects the actual outcome; a rejected start is never reported as successful. So, in the recovery's active-in-window branch:
#   - a last result that already starts with STARTED (this schedule's own verified start, recorded before the restart): byte for byte as before (the same text, the same disarm);
#   - a last result that starts with FAILED, BLOCKED or CANCELLED is final: its text is left exactly as written (no write at all); the existing disarm stays;
#   - every other last result (STARTING, ARMED and ARMED AFTER RESTART, empty, unknown, REJECTED, MISSED, foreign text): a truthful non-success UNCONFIRMED text that says Dump to Grid is active after a Home Assistant restart and that this
#     schedule did not confirm that it started it (at most 255 characters, never STARTED OK); the existing disarm stays;
#   - nothing is pressed, staged or started by the recovery, no alert and no dismissal is added, and every other branch (not armed, a start running, before the start, the R9 not-missed leave-alone, the missed run, the expired window)
#     and every case with Dump to Grid not active is unchanged.
# The proof: [15.1] the REAL recovery automation, fired as on a Home Assistant start, for every result class x Dump to Grid active or not x armed or not x where now is relative to the window; the cells in which the active branch
# runs are checked against the rule above, every other cell must equal the previous package's (rebuilt from this one, its code lines pinned by sha256). [15.2] what the owner still sees (the refusal stays the status FAILED once Dump to Grid
# is off; no success status for an unverified start). [15.3] end to end through the real start script, a restart and the real recovery. [15.4] the package diff is exactly the one branch. [15.5] mutants (the old unconditional write
# among them).
import datetime as _dt

REC_ID = "ecco_dump_to_grid_schedule_startup_recovery"
START_E, HASTART_E = "input_datetime.ecco_dump_to_grid_schedule_start", "input_datetime.ecco_dump_to_grid_ha_start"
DUR_E, PWR_E, SOC_E = "input_number.ecco_dump_to_grid_schedule_duration", "input_number.ecco_dump_to_grid_schedule_power", "input_number.ecco_dump_to_grid_schedule_stop_soc"
SCRIPT_E, STATUS_E = "script.ecco_dump_to_grid_start_scheduled", "sensor.ecco_dump_to_grid_schedule_status"
STARTED_REC = "STARTED OK - running (Home Assistant restarted during the session)"
UNCONFIRMED_TEXT = ("UNCONFIRMED - Dump to Grid is active after a Home Assistant restart, but this schedule did not confirm that it started it (it may have been started some other way). "
                    "Check it, and the plan overrides, before assuming it is held.")
PREV_CODE_SHA = "f1a10005ecd5de887817f8813f50062fcb2b701043a0dea3d0a812807cc66894"   # sha256 of the previous package (e1005ad) without its whole-line comments
PREV_TEXT = undo_recovery(undo_clock_changes(DUMP_TEXT))
PREV_R9_TEXT = _r9s._apply(PREV_TEXT, R9_CLOCK_PAIRS, "the previous package")      # the previous package carrying R9's declared pairs: the text [15.4] compares this package with
REC_NEW = rec_new_block(DUMP_TEXT)
check("the previous package, rebuilt from this one by undoing the startup recovery edit of this change, has exactly the code lines of e1005ad (sha256 of everything but whole-line comments), so the 'unchanged' comparisons below "
      "are against the real previous behaviour", code_sha(PREV_TEXT) == PREV_CODE_SHA and (PREV_TEXT != DUMP_TEXT or REC_NEW == ""), code_sha(PREV_TEXT)[:16])
check("the recovery's text for an unverified start is a non-success text of at most 255 characters that says Dump to Grid is active after a Home Assistant restart and that this schedule did not confirm that it started it",
      len(UNCONFIRMED_TEXT) <= 255 and not UNCONFIRMED_TEXT.startswith("STARTED") and "STARTED OK" not in UNCONFIRMED_TEXT and "Dump to Grid is active after a Home Assistant restart" in UNCONFIRMED_TEXT
      and "did not confirm that it started it" in UNCONFIRMED_TEXT, str(len(UNCONFIRMED_TEXT)))

_rec_parsed: dict = {}


def rec_packages(dump_text: str) -> list:
    import copy
    if dump_text not in _rec_parsed:
        _rec_parsed[dump_text] = [yaml.safe_load(t) for t in (dump_text, PLAN_TEXT, GUARD_TEXT)]
    return copy.deepcopy(_rec_parsed[dump_text])


TIMING15 = {"before": 1800, "window": -2, "missed": -120, "after": -3600}   # the schedule's start, in seconds from the Home Assistant start (a 30 minute window): in the future / just after the captured start / before it / long over


def local_at(pw, off: float) -> str:
    return _dt.datetime.fromtimestamp(pw.w.t + off, pw.zone).strftime(P.FMT)


def recovery_world(dump_text: str, result: str, active: bool, armed: str = "on", timing: str = "window", script_on: bool = False, capture: str = "known"):
    """A world at the moment Home Assistant starts: the schedule armed (or not) for a start at TIMING15[timing], the last result `result`, the captured Home Assistant start known (or never captured at this boot), the dongle's
    write enable left ON by the restart, Dump to Grid active (started some other way) or not, and the start script running or not."""
    pw, d = world(pkgs=rec_packages(dump_text), owner=40)
    w = pw.w
    w.set(LAST, result)
    w.set(ARMED, "on" if armed == "on" else "off")
    w.set(DUR_E, "30.0")
    w.set(PWR_E, "2000.0")
    w.set(SOC_E, "40.0")
    pw.set_local(START_E, local_at(pw, TIMING15[timing]))
    if capture == "known":
        pw.set_local(HASTART_E, local_at(pw, -5))
    if active:
        d.active = True
        w.set(D.D_ACTIVE, "on")
    d.arm = True
    w.set(D.D_ARM, "on")
    if script_on:
        w.set(SCRIPT_E, "on")
    return pw, d


def fire_recovery(pw, d, seconds: float = 600.0) -> tuple:
    """Home Assistant starts: only the startup recovery runs (the real automation, from its own `homeassistant` start trigger). Returns what the log, the services, the dongle's numbers and its presses held before it ran
    (so a fact is what the recovery did, not what an earlier run did)."""
    w = pw.w
    marks = (len(w.service_log), len(w.notification_log), len(d.number_log), len(d.press_log))
    a = next(x for x in pw.ha.automations if x.id == REC_ID)
    a.setup()
    a.ha_start()
    w.run_until(w.t + seconds)
    return marks


def rec_facts(pw, d, marks: tuple) -> dict:
    w = pw.w
    n0, k0, m0, p0 = marks
    return dict(last=pw.state(LAST), armed=pw.state(ARMED), arm=pw.state(D.D_ARM), model_arm=d.arm,
                notes=[n for n in w.notification_log[k0:] if n[1] == "create"], dismissed=[n for n in w.notification_log[k0:] if n[1] == "dismiss"],
                calls=[(s, e, dd) for _t, s, e, dd in w.service_log[n0:]], presses=list(d.press_log[p0:]), numbers=list(d.number_log[m0:]),
                warnings=list(w.warnings), runs=list(pw.ha.runs), status=pw.state(STATUS_E))


def rec_probe(dump_text: str, result: str, active: bool, armed: str = "on", timing: str = "window", script_on: bool = False, capture: str = "known") -> dict:
    pw, d = recovery_world(dump_text, result, active, armed, timing, script_on, capture)
    return rec_facts(pw, d, fire_recovery(pw, d))


_rec_prev: dict = {}


def rec_prev(result: str, active: bool, armed: str, timing: str, script_on: bool, capture: str) -> dict:
    key = (result, active, armed, timing, script_on, capture)
    if key not in _rec_prev:
        _rec_prev[key] = rec_probe(PREV_TEXT, *key)
    return _rec_prev[key]


FINAL15 = ("FAILED", "BLOCKED", "CANCELLED")
# (label, class, the result text). Every result the schedule can hold when Home Assistant starts: the package's own texts (CELLS14) and the ones that only a restart or another writer leaves.
CELLS15 = CELLS14 + (
    ("ARMED AFTER RESTART, written by an earlier recovery", "FOREIGN", "ARMED AFTER RESTART - waiting for 2026-11-17 21:30:00"),
    ("STARTED OK - running, written by an earlier recovery", "STARTED", STARTED_REC),
    ("unknown (a helper that was not restored)", "FOREIGN", "unknown"),
    ("a text of another writer", "FOREIGN", "Hello from another writer"),
    ("a text that only MENTIONS STARTED OK later (not a start of this schedule)", "FOREIGN", "REJECTED - the STARTED OK of an earlier run does not count"),
    ("a text that only MENTIONS FAILED later (not a final result of this schedule)", "FOREIGN", "REJECTED - the earlier FAILED run is gone"),
)
CHANGED15 = (("window", "known"), ("missed", "known"), ("window", "unknown"))      # where now is inside the window: the recovery's active branch runs when Dump to Grid is active and the schedule armed
REP15 = ("STARTING - attempt 3 waiting: dongle offline or another write in progress; retrying until 21:10", "STARTED OK - 2000W for 30 min, Stop SOC 40% (attempt 1; ends by 21:31)",
         "FAILED TO START - retries ended at 21:10: Inactive", CANCELLED_TEXT, "BLOCKED - the effective reserve rose above the Stop SOC staged for this run (40%) while it was waiting; nothing started (reason RESERVE_TOO_HIGH)",
         "ARMED - 2026-11-17 22:00:00 • 30 min • 2000W • Stop SOC 40%", "")
UNCHANGED15 = (("before", "known"), ("window", "known"), ("missed", "known"), ("after", "known"), ("window", "unknown"))


def rec_expect(kind: str, text: str, f: dict) -> str:
    """'' when a cell in which the active branch runs is right, else why not."""
    last = f["last"]
    if f["armed"] != "off":
        return f"the schedule must be disarmed, as before (armed is {f['armed']!r})"
    if f["arm"] != "off" or f["model_arm"] is not False or f["presses"] or f["numbers"] or f["runs"]:
        return f"nothing may be pressed, staged or started: write enable {f['arm']!r}, presses {f['presses']}, numbers {f['numbers']}, runs {f['runs']}"
    extra = sorted({s for s, _e, _d in f["calls"]} - {"input_text.set_value", "input_boolean.turn_off", "switch.turn_off"})
    if extra or f["notes"] or f["dismissed"]:
        return f"no new service, alert or dismissal: {extra} notes={f['notes']} dismissed={f['dismissed']}"
    if any("invalid value" in m for m in f["warnings"]):
        return f"a text did not fit the helper: {f['warnings'][:1]}"
    writes = [dd["value"] for s, _e, dd in f["calls"] if s == "input_text.set_value"]
    if kind != "STARTED" and (last.startswith("STARTED") or "STARTED OK" in last or any("STARTED OK" in v for v in writes)):
        return f"a result of class {kind} was reported as a success: {last[:90]!r}"
    if kind == "STARTED":
        return "" if last == STARTED_REC and writes == [STARTED_REC] else f"a verified STARTED result must read exactly {STARTED_REC!r}: {last[:90]!r} writes={len(writes)}"
    if kind in FINAL15:
        return "" if last == text and writes == [] else f"a {kind} result is final and must stay exactly as written, with no write at all: {last[:90]!r} writes={len(writes)}"
    return "" if last == UNCONFIRMED_TEXT and writes == [UNCONFIRMED_TEXT] else f"any other result must become the UNCONFIRMED text (once): {last[:90]!r} writes={len(writes)}"


def rec_cell_problems(dump_text: str, stop_early: bool = False, kinds=None, changed: bool = True, unchanged: bool = True) -> list[str]:
    bad: list[str] = []

    def differs(text, active, armed, timing, script_on, capture) -> str:
        f, g = rec_probe(dump_text, text, active, armed, timing, script_on, capture), rec_prev(text, active, armed, timing, script_on, capture)
        diff = [k for k in g if f[k] != g[k]]
        return (f"{text[:24]!r}, Dump to Grid {'active' if active else 'not active'}, armed={armed}, start script {'running' if script_on else 'idle'}, window {timing}/{capture}: "
                f"differs from the previous package in {diff}") if diff else ""
    try:
        if changed:
            for label, kind, text in CELLS15:
                if kinds is not None and kind not in kinds:
                    continue
                for timing, capture in CHANGED15:
                    why = rec_expect(kind, text, rec_probe(dump_text, text, True, "on", timing, False, capture))
                    if why:
                        bad.append(f"{label}, Dump to Grid active, window {timing}/{capture}: {why}")
                        if stop_early:
                            return bad
        if unchanged:
            for text in REP15:
                cases = [(text, active, armed, timing, False, capture) for active in (True, False) for armed in ("on", "off") for timing, capture in UNCHANGED15
                         if not (active and armed == "on" and (timing, capture) in CHANGED15)]
                cases.append((text, True, "on", "window", True, "known"))
                for case in cases:
                    why = differs(*case)
                    if why:
                        bad.append(why)
                        if stop_early:
                            return bad
    except Exception as exc:  # noqa: BLE001 - a package that cannot run is a failed proof
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


print("[15.1] the real startup recovery, every result class x Dump to Grid active or not x armed x where now is relative to the window")
cp15: list[str] = []
for kinds, what, rule in ((("STARTED",), "a result that already starts with STARTED (this schedule's own verified start, recorded before the restart; also the recovery's own earlier text)",
                           f"the text reads exactly {STARTED_REC!r} and the schedule is disarmed, byte for byte as before"),
                          (FINAL15, "a FAILED, BLOCKED or CANCELLED result (the package's own texts: the window over, refused at the gate, a failed transaction, no answer, retries ended, the loop's and the cancel script's CANCELLED, both press-time BLOCKED reasons)",
                           "the text stays exactly as written (no write at all) and the schedule is disarmed as before: a refusal is never turned into a success"),
                          (("STARTING", "FOREIGN"), "any other result (the five STARTING texts, ARMED, ARMED AFTER RESTART, REJECTED, MISSED, empty, unknown, a foreign text, a text that only mentions STARTED OK or FAILED later)",
                           "the text becomes the UNCONFIRMED text (Dump to Grid is active after a Home Assistant restart, this schedule did not confirm that it started it; at most 255 characters; never STARTED OK) and the schedule is disarmed")):
    kp = rec_cell_problems(DUMP_TEXT, kinds=kinds, unchanged=False)
    cp15 += kp
    check(f"{what}, Dump to Grid ACTIVE, armed, the start script not running, the window open (a start after or before the captured Home Assistant start, and the capture unknown): {rule}; nothing is pressed, staged or started; "
          "no alert and no dismissal; the write enable ends off", kp == [], str(kp[:2]))
up15 = rec_cell_problems(DUMP_TEXT, changed=False)
cp15 += up15
check(f"every other case equals the previous package's, field for field (the final text, the armed helper, the write enable, every service call and its data, the alerts and dismissals, the status): Dump to Grid not active, the schedule not armed, "
      f"a start script running, the start still to come, the window over, for {len(REP15)} result texts (one per class) x active or not x armed or not x {len(UNCHANGED15)} window cases", up15 == [], str(up15[:2]))

# ---- [15.2] what the owner still sees --------------------------------------------------------------------------------------------------------------------------------------------------------
print("[15.2] what the owner sees: a refusal stays the status FAILED once Dump to Grid ends, a verified start stays COMPLETED, an unverified one is never COMPLETED")


def visible_problems15(dump_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []
    try:
        for label, kind, text in CELLS15:
            pw, d = recovery_world(dump_text, text, True)
            f0 = rec_facts(pw, d, fire_recovery(pw, d))
            pw.w.set(D.D_ACTIVE, "off")
            d.active = False
            st = pw.state(STATUS_E)
            if kind == "STARTED":
                ok = st == "COMPLETED"
            elif kind in ("FAILED", "BLOCKED"):
                ok = st == "FAILED" and pw.state(LAST) == text and f0["notes"] == []
            elif kind == "CANCELLED":
                ok = st == "IDLE" and pw.state(LAST) == text
            else:
                ok = st not in ("COMPLETED", "ACTIVE", "STARTING") and pw.state(LAST) == UNCONFIRMED_TEXT
            if not ok:
                bad.append(f"{label}: after the recovery and Dump to Grid ending, the status reads {st!r} and the result {pw.state(LAST)[:60]!r}")
                if stop_early:
                    return bad
    except Exception as exc:  # noqa: BLE001
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


vp15 = visible_problems15(DUMP_TEXT)
check("a refusal stays visible without a new alert: after the recovery a FAILED or BLOCKED result still reads exactly as written and the status sensor reads FAILED as soon as Dump to Grid is not active (the recovery raised no notification); "
      "a CANCELLED result reads IDLE; a verified STARTED result reads COMPLETED; an unverified start (the UNCONFIRMED text) never reads COMPLETED", vp15 == [], str(vp15[:2]))

# ---- [15.3] end to end ----------------------------------------------------------------------------------------------------------------------------------------------------------------------
print("[15.3] end to end: the real start script, a Home Assistant restart, the real recovery")


def restart_ha(pw, dump_text: str, d, active: bool = True) -> tuple:
    """Home Assistant restarts while the schedule is still armed and Dump to Grid is (or is not) active: the running scripts die, a new instance loads the packages, the helpers keep their states, and the recovery runs."""
    w = pw.w
    pw.ha.stop()
    pw.ha = S.HA(w, rec_packages(dump_text))
    if active:
        d.active = True
        w.set(D.D_ACTIVE, "on")
    w.set(DUR_E, "30.0")
    pw.set_local(START_E, local_at(pw, -2))
    pw.set_local(HASTART_E, local_at(pw, -5))
    w.set(ARMED, "on")                                         # the fire automation died before it could disarm the schedule
    return fire_recovery(pw, d)


def e2e15_run(dump_text: str, shape: str) -> dict:
    pw, d = world(pkgs=rec_packages(dump_text), owner=40)
    w = pw.w
    t0 = w.t
    if shape == "blocked":                                    # a Hold battery refuses the scheduled start; later the dongle's own Start button starts Dump to Grid; then Home Assistant restarts
        hold(pw, "hold_battery")
        run_scheduled(pw, d, seconds=150)
    elif shape == "failed":                                   # the dongle refuses the start at the gate for a reason that needs the owner; later Dump to Grid is active some other way
        d.flags["corrupt"] = True
        run_scheduled(pw, d, seconds=150)
    elif shape == "starting_offline":                         # the dongle is offline: the run is still STARTING when Home Assistant restarts (the restart kills it); the dongle is back before the recovery looks
        d.set_offline(t0, t0 + 70)
        run_scheduled(pw, d, seconds=60)
    elif shape == "starting_own_press":                       # this run's own press is sent and Home Assistant restarts a moment later, before this run could verify it
        killed: list = []

        def watch(_kind):
            if d.press_log and not killed:
                killed.append(w.t)
                w.after(0.5, lambda: pw.ha.stop())
        w.listeners.append(watch)
        run_scheduled(pw, d, seconds=40)
        w.listeners.remove(watch)
        w.run_until(w.t + 120)                                # the dongle's own start transaction completes without Home Assistant
    elif shape == "verified":                                 # control: this run's own start was verified (STARTED OK written in the loop) before the restart
        run_scheduled(pw, d, seconds=150)
    else:
        raise ValueError(shape)
    before = dict(last=pw.state(LAST), presses=len(d.press_log), started=d.successes, active=pw.state(D.D_ACTIVE))
    marks = restart_ha(pw, dump_text, d, active=shape != "starting_own_press")
    f = rec_facts(pw, d, marks)
    f.update(before=before, started=d.successes)
    return f


E2E15 = (
    ("blocked", "a BLOCKED refusal (a Hold battery was active), then the dongle's own Start button starts Dump to Grid, then Home Assistant restarts: the refusal stays", "final"),
    ("failed", "a FAILED TO START refusal (refused at the start gate), Dump to Grid active some other way, Home Assistant restarts: the refusal stays", "final"),
    ("starting_offline", "a run still STARTING (dongle offline) is killed by the restart and Dump to Grid is active some other way: the UNCONFIRMED text, not a success", "unconfirmed"),
    ("starting_own_press", "a run whose own press started Dump to Grid but whose verification was killed by the restart: the UNCONFIRMED text (this schedule did not confirm it), not a success, and no second press", "unconfirmed"),
    ("verified", "control: this run's own verified STARTED OK, then Home Assistant restarts with Dump to Grid active: STARTED OK - running, as before, disarmed", "verified"),
)


def e2e15_check(kind: str, f: dict, shape: str = "") -> str:
    last = f["last"]
    if f["armed"] != "off" or f["arm"] != "off" or f["model_arm"] is not False:
        return f"the schedule must be disarmed and the write enable off after the recovery: armed {f['armed']!r}, write enable {f['arm']!r}"
    if f["presses"] or f["numbers"] or f["runs"]:
        return f"the recovery pressed, staged or started something: presses {f['presses']}, numbers {f['numbers']}, runs {f['runs']}"
    if shape == "starting_own_press" and (f["started"] != 1 or f["before"]["presses"] != 1):
        return f"this run's own press must have started Dump to Grid exactly once before the restart: started={f['started']} presses={f['before']['presses']}"
    if f["notes"] or f["dismissed"]:
        return f"the recovery raised or dismissed an alert: {f['notes']} {f['dismissed']}"
    if kind == "final":
        ok = last == f["before"]["last"] and f["before"]["last"][:7] in ("BLOCKED", "FAILED ") and not any(s == "input_text.set_value" for s, _e, _d in f["calls"])
        return "" if ok else f"the refusal must stay exactly as written: {last[:90]!r} (was {f['before']['last'][:50]!r})"
    if kind == "unconfirmed":
        ok = last == UNCONFIRMED_TEXT and f["before"]["last"].startswith("STARTING") and f["status"] == "ACTIVE"
        return "" if ok else f"{last[:90]!r} (before the restart: {f['before']['last'][:40]!r}) status={f['status']!r}"
    ok = last == STARTED_REC and f["before"]["last"].startswith("STARTED OK - 2000W") and f["started"] == 1
    return "" if ok else f"{last[:90]!r} (before the restart: {f['before']['last'][:40]!r}) started={f['started']}"


def e2e15_problems(dump_text: str, stop_early: bool = False) -> list[str]:
    bad: list[str] = []
    try:
        for shape, label, kind in E2E15:
            why = e2e15_check(kind, e2e15_run(dump_text, shape), shape)
            if why:
                bad.append(f"{label}: {why}")
                if stop_early:
                    return bad
    except Exception as exc:  # noqa: BLE001
        bad.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return bad


for shape, label, kind in E2E15:
    f = e2e15_run(DUMP_TEXT, shape)
    why = e2e15_check(kind, f, shape)
    check(f"end to end, {label}", why == "", why)

# ---- [15.4] the diff is exactly the one branch ---------------------------------------------------------------------------------------------------------------------------------------------
print("[15.4] the package differs from the previous one in exactly the recovery's active branch; its STARTED OK write and its disarm are the old actions, unchanged")


def branch_of(pkg: dict) -> tuple:
    rec = next(a for a in pkg["automation"] if a["id"] == REC_ID)
    ci = next(i for i, a in enumerate(rec["actions"]) if "choose" in a)
    bi = next(i for i, b in enumerate(rec["actions"][ci]["choose"])
              if any(c.get("entity_id") == "binary_sensor.ecco_clock_dongle_dump_to_grid_active" for c in b["conditions"]))
    return rec, ci, bi


def diff_problems(dump_text: str) -> list[str]:
    import copy
    out: list[str] = []
    try:
        new, old = yaml.safe_load(dump_text), yaml.safe_load(PREV_R9_TEXT)
        rn, ci, bi = branch_of(new)
        ro, cj, bj = branch_of(old)
        if (ci, bi) != (cj, bj):
            return ["the branch moved"]
        bn, bo = rn["actions"][ci]["choose"][bi], ro["actions"][ci]["choose"][bi]
        if bn["conditions"] != bo["conditions"]:
            out.append("the branch's conditions changed")
        old_write, old_disarm = bo["sequence"]
        seq = bn["sequence"]
        if len(seq) != 2 or "choose" not in seq[0] or seq[1] != old_disarm:
            out.append("the branch's sequence must be one choose followed by the old disarm action, unchanged")
        else:
            ch = seq[0]["choose"]
            if not (len(ch) == 2 and ch[0]["sequence"] == [old_write] and ch[1]["sequence"] == [] and len(seq[0]["default"]) == 1
                    and seq[0]["default"][0]["action"] == "input_text.set_value" and seq[0]["default"][0]["data"]["value"] == UNCONFIRMED_TEXT
                    and seq[0]["default"][0]["target"] == old_write["target"]):
                out.append("the choose must hold the old STARTED OK write (unchanged) for a STARTED result, an empty branch for FAILED, BLOCKED or CANCELLED, and the one UNCONFIRMED write by default")
            if ch[0]["conditions"] != [{"condition": "template", "value_template": "{{ states('input_text.ecco_dump_to_grid_schedule_last_result').startswith('STARTED') }}"}]:
                out.append("the STARTED test is not `states(...last_result).startswith('STARTED')`")
            if [c.get("value_template", "").replace("\n", " ").strip() for c in ch[1]["conditions"]] != [
                    "{% set r = states('input_text.ecco_dump_to_grid_schedule_last_result') %} {{ r.startswith('FAILED') or r.startswith('BLOCKED') or r.startswith('CANCELLED') }}"]:
                out.append("the final-result test is not FAILED, BLOCKED or CANCELLED by startswith")
        nn, oo = copy.deepcopy(new), copy.deepcopy(old)
        branch_of(nn)[0]["actions"][ci]["choose"][bi]["sequence"] = None
        branch_of(oo)[0]["actions"][ci]["choose"][bi]["sequence"] = None
        if nn != oo:
            out.append("something other than the branch's sequence changed in the parsed package")
    except Exception as exc:  # noqa: BLE001 - a structure this check cannot read is a failed proof
        out.append(f"raised {type(exc).__name__}: {str(exc)[:140]}")
    return out


dp15 = diff_problems(DUMP_TEXT)
check("the parsed package differs from the previous one only in the sequence of the recovery's active-in-window branch (same conditions); that sequence is one choose (the old STARTED OK write unchanged for a STARTED result, "
      "nothing for FAILED, BLOCKED or CANCELLED, the UNCONFIRMED write by default) and then the old disarm action, unchanged; every other branch, trigger, condition and text of the package is unchanged", dp15 == [], str(dp15))
_walk: list = []


def _collect(node):
    if isinstance(node, list):
        for x in node:
            _collect(x)
    elif isinstance(node, dict):
        if "action" in node:
            _walk.append(node["action"])
        for v in node.values():
            _collect(v)


_collect(next(a for a in yaml.safe_load(DUMP_TEXT)["automation"] if a["id"] == REC_ID)["actions"])
check("the recovery calls only helper writes, the write enable's turn_off and one persistent notification (the missed-run alert): no press, no number, no script, no start",
      set(_walk) <= {"switch.turn_off", "input_text.set_value", "input_boolean.turn_off", "persistent_notification.create"} and "input_text.set_value" in _walk, str(sorted(set(_walk))))
check("the recovery's STARTED OK text is written in one place only (and only for a result that already starts with STARTED), and the UNCONFIRMED text in one place",
      DUMP_TEXT.count('value: "' + STARTED_REC + '"') == 1 and DUMP_TEXT.count('value: "UNCONFIRMED - ') == 1, f"{DUMP_TEXT.count('value: ' + chr(34) + STARTED_REC + chr(34))} {DUMP_TEXT.count('value: ' + chr(34) + 'UNCONFIRMED - ')}")

# ---- [15.5] mutants ------------------------------------------------------------------------------------------------------------------------------------------------------------------------
print("[15.5] mutation: the old unconditional write restored, the STARTED test dropped or moved, FAILED, BLOCKED or CANCELLED overwritten, STARTING left final, success wording added, a press or an alert added: each is caught")
_STARTED_TEST = "value_template: \"{{ states('input_text.ecco_dump_to_grid_schedule_last_result').startswith('STARTED') }}\""
_FINAL_TEST = "{{ r.startswith('FAILED') or r.startswith('BLOCKED') or r.startswith('CANCELLED') }}"
_WRITE_STARTED = ("                      - action: input_text.set_value\n                        target:\n                          entity_id: input_text.ecco_dump_to_grid_schedule_last_result\n"
                  "                        data:\n                          value: \"" + STARTED_REC + "\"\n")
_ACTIVE_COND = "              - condition: state\n                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n                state: \"on\"\n            sequence:\n              - choose:\n"
_WINDOW_COND = ("          - conditions:\n              - condition: template\n                value_template: \"{{ now_ts < end_ts }}\"\n              - condition: state\n"
                "                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n")
_DISARM = "              - action: input_boolean.turn_off\n                target:\n                  entity_id: input_boolean.ecco_dump_to_grid_schedule_armed\n"
_UNC = "UNCONFIRMED - Dump to Grid is active after a Home Assistant restart, but this schedule did not confirm that it started it"
_PRESS = "              - action: button.press\n                target:\n                  entity_id: button.ecco_clock_dongle_start_dump_to_grid_now\n"
_NOTIFY = ("                    sequence:\n                      - action: persistent_notification.create\n                        data:\n                          notification_id: ecco_dump_to_grid_schedule\n"
           "                          title: \"x\"\n                          message: \"x\"\n")
_START_SCRIPT = "              - action: script.ecco_dump_to_grid_start_scheduled\n                data:\n                  duration_minutes: 30\n                  power_w: 2000\n                  stop_soc: 40\n                  window_end_ts: 0\n"
MUTANTS15 = [
    ("the old unconditional write is restored (STARTED OK whatever the last result was)", [(REC_NEW, REC_OLD_BLOCK)]),
    ("the STARTED test is dropped (always true: every result is written as STARTED OK)", [(_STARTED_TEST, "value_template: \"{{ true }}\"")]),
    ("the STARTED test is inverted (a verified start is replaced by the UNCONFIRMED text, anything else is written as STARTED OK)", [(_STARTED_TEST, _STARTED_TEST.replace("{{ states(", "{{ not states("))]),
    ("the STARTED test reads the wrong entity (a verified start is no longer recognised)", [(_STARTED_TEST, _STARTED_TEST.replace("ecco_dump_to_grid_schedule_last_result", "ecco_free_power_schedule_last_result"))]),
    ("the STARTED test looks for STARTED anywhere in the text, not at its start", [(_STARTED_TEST, "value_template: \"{{ 'STARTED' in states('input_text.ecco_dump_to_grid_schedule_last_result') }}\"")]),
    ("a STARTED result is not kept as the old text (the STARTED OK text changed)", [(_WRITE_STARTED, _WRITE_STARTED.replace(STARTED_REC, "STARTED OK - running"))]),
    ("a FAILED result is not final (it is overwritten with the UNCONFIRMED text)", [(_FINAL_TEST, _FINAL_TEST.replace("r.startswith('FAILED') or ", ""))]),
    ("a BLOCKED result is not final (it is overwritten with the UNCONFIRMED text)", [(_FINAL_TEST, _FINAL_TEST.replace("r.startswith('BLOCKED') or ", ""))]),
    ("a CANCELLED result is not final (it is overwritten with the UNCONFIRMED text)", [(_FINAL_TEST, _FINAL_TEST.replace(" or r.startswith('CANCELLED')", ""))]),
    ("a FAILED result is matched anywhere in the text (a foreign text that only mentions FAILED stays as it is)", [(_FINAL_TEST, _FINAL_TEST.replace("r.startswith('FAILED')", "'FAILED' in r"))]),
    ("a STARTING result is final too (it is left as STARTING and no UNCONFIRMED text is written)", [(_FINAL_TEST, _FINAL_TEST.replace("r.startswith('CANCELLED') }}", "r.startswith('CANCELLED') or r.startswith('STARTING') }}"))]),
    ("a FAILED, BLOCKED or CANCELLED result is overwritten with STARTED OK (the final branch writes the old success text)", [("                    sequence: []\n", "                    sequence:\n" + _WRITE_STARTED)]),
    ("success wording is added to the UNCONFIRMED text (it starts with STARTED OK)", [(_UNC, _UNC.replace("UNCONFIRMED - Dump to Grid is active", "STARTED OK - Dump to Grid is active"))]),
    ("the UNCONFIRMED text claims that this schedule started it", [(_UNC, _UNC.replace("but this schedule did not confirm that it started it", "and this schedule started it"))]),
    ("the UNCONFIRMED text no longer says that this schedule did not confirm the start", [(_UNC, _UNC.replace(", but this schedule did not confirm that it started it", ""))]),
    ("the UNCONFIRMED text no longer says that Home Assistant restarted", [(_UNC, _UNC.replace("after a Home Assistant restart", "now"))]),
    ("the UNCONFIRMED text is longer than the 255-character helper (Home Assistant would keep the old value)", [(_UNC, _UNC + " " + "x" * 120)]),
    ("the schedule is no longer disarmed after the recovery (the disarm dropped from the branch)", [(REC_NEW, REC_NEW.replace(_DISARM, ""))]),
    ("the recovery presses the dongle's Start button", [(REC_NEW, REC_NEW + _PRESS)]),
    ("the recovery starts the scheduled start script", [(REC_NEW, REC_NEW + _START_SCRIPT)]),
    ("the recovery raises a new alert for a refusal (a persistent notification in the final branch)", [("                    sequence: []\n", _NOTIFY)]),
    ("the branch also runs while Dump to Grid is NOT active (the active test dropped: a missed run is rewritten)", [(_ACTIVE_COND, "            sequence:\n              - choose:\n")]),
    ("the branch also runs after the window is over (the window test dropped: the expired default is lost)", [(_WINDOW_COND, "          - conditions:\n              - condition: state\n                entity_id: binary_sensor.ecco_clock_dongle_dump_to_grid_active\n")]),
]
caught15 = 0
built15 = 0
for label, edits in MUTANTS15:
    mutated = DUMP_TEXT
    ok_built = True
    for old, new in edits:
        if not old or mutated.count(old) != 1:
            ok_built = False
            check(f"mutant anchor: {label}", False, f"anchor found {mutated.count(old) if old else 0}x: {old[:70]!r}")
            break
        mutated = mutated.replace(old, new)
    if not ok_built:
        continue
    built15 += 1
    try:
        yaml.safe_load(mutated)
    except yaml.YAMLError as exc:
        check(f"mutant loads as YAML: {label}", False, str(exc)[:80])
        continue
    found = (rec_cell_problems(mutated, stop_early=True) or visible_problems15(mutated, stop_early=True) or e2e15_problems(mutated, stop_early=True) or diff_problems(mutated))
    if found:
        caught15 += 1
        print(f"  PASS  mutant caught: {label} (first failing case: {found[0][:90]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label}")
check(f"{len(MUTANTS15)} mutants of the startup recovery (the old unconditional write restored, the STARTED test dropped, inverted or loosened, FAILED, BLOCKED or CANCELLED overwritten, STARTING left final, success wording added, the disarm dropped, "
      "a press, a start or an alert added, the active or window test dropped), all caught by the table, the owner's view, an end-to-end run or the diff", caught15 == len(MUTANTS15) == built15, f"{caught15}/{built15}/{len(MUTANTS15)}")
check("control: the unmutated package passes the same table, view, end-to-end runs and diff", cp15 == [] and vp15 == [] and dp15 == [] and e2e15_problems(DUMP_TEXT) == [])

# ---- [15.6] the rebuild of the previous package undoes EXACTLY R9's declared clock-change pairs --------------------------------------------------------------------------------------------------------
print("[15.6] the previous package (0a488d8, e1005ad) is rebuilt by undoing R9's five declared clock-change pairs and this change's own edits: a stray edit inside R9's region, or a package without the pairs, fails the rebuild")
check("the five pairs are the last five of the r9 scope module's declared Dump pairs (a pair added there later is not silently left out of the rebuild)", tuple(_r9s.DUMP_EDITS[-5:]) == R9_CLOCK_PAIRS and len(R9_CLOCK_PAIRS) == 5)
check("each of R9's five declared texts is in this package exactly once and in neither rebuilt previous package; each of their anchors is in the rebuilt previous packages exactly once",
      all(DUMP_TEXT.count(new) == 1 and BEFORE_TEXT.count(new) == 0 and PREV_TEXT.count(new) == 0 and BEFORE_TEXT.count(old) == 1 and PREV_TEXT.count(old) == 1 for old, new in R9_CLOCK_PAIRS))
check("the previous package plus R9's declared pairs is exactly this package without the startup recovery edit (the text [15.4] compares with), and undoing the pairs again gives the pinned previous package back",
      PREV_R9_TEXT == undo_recovery(DUMP_TEXT) and undo_clock_changes(PREV_R9_TEXT) == PREV_TEXT and code_sha(PREV_TEXT) == PREV_CODE_SHA)


def rebuild_problem(text: str) -> str:
    """'' when `text` rebuilds to BOTH pinned previous packages (0a488d8 by before_text, e1005ad by the recovery undo); else the first reason (an AssertionError of the strict reverter, or a code-line hash that differs)."""
    for name, fn, pin in (("0a488d8", before_text, OLD_CODE_SHA), ("e1005ad", lambda t: undo_recovery(undo_clock_changes(t)), PREV_CODE_SHA)):
        try:
            rebuilt = fn(text)
        except AssertionError as exc:
            return f"{name}: the rebuild raised AssertionError ({str(exc)[:110]})"
        if code_sha(rebuilt) != pin:
            return f"{name}: the code-line hash differs"
    return ""


check("control: this package rebuilds to both pinned previous packages", rebuild_problem(DUMP_TEXT) == "")
# One character altered in the package, inside R9's declared region (the start-label refusal P-A, the walk on real instants P-B, and the two comment blocks the pairs also declare) or, as a control for the hash, outside it.
# Every one of them must make the rebuild raise AssertionError (inside R9's region: the declared text is no longer present exactly once) or the code-line hash differ (outside it).
CLOCK_MUTANTS = [
    ("P-A: the label refusal's zero test flipped (t <= 0 becomes t >= 0)", "{{ t <= 0\n", "{{ t >= 0\n", True),
    ("P-A: the round-trip test flipped (!= s becomes == s)", "'unreadable')) != s", "'unreadable')) == s", True),
    ("P-A: the repeated-hour test reads 3601 s after the label, not 3600", "(t + 3600)", "(t + 3601)", True),
    ("P-A: the repeated-hour test reads 3500 s before the label, not 3600", "(t - 3600)", "(t - 3500)", True),
    ("P-A: the label is converted with another default (as_timestamp(s, 0) becomes (s, 1))", "as_timestamp(s, 0)", "as_timestamp(s, 1)", True),
    ("P-A: the refusal's fail-closed default text is changed in one place", "(t | timestamp_custom(f, true, 'unreadable')) != s", "(t | timestamp_custom(f, true, 'unreadablf')) != s", True),
    ("P-A: the refusal text is changed by one letter", "value: \"REJECTED - the start time is a skipped", "value: \"REJECTED - the start time is a skippeD", True),
    ("P-B: the walk's minute step is 61 s, not 60", "k * 60) | timestamp_local", "k * 61) | timestamp_local", True),
    ("P-B: the walk's hour bound is 22, not 23", "hh > 23", "hh > 22", True),
    ("P-B: the walk's minute bound is 58, not 59", "mi > 59", "mi > 58", True),
    ("P-B: the unreadable-minute flag is never read (ns.bad becomes ns.bac in the result)", "ns.hit > 0 or ns.bad }}", "ns.hit > 0 or ns.bac }}", True),
    ("P-B: the unreadable-minute flag is never set (true becomes trua)", "{% set ns.bad = true %}", "{% set ns.bad = trua %}", True),
    ("P-B: the hour is read from one character more", "sk[11:13] | int(-1)", "sk[11:14] | int(-1)", True),
    ("P-B: the minute's fail-closed default is -2, not -1", "sk[14:16] | int(-1)", "sk[14:16] | int(-2)", True),
    ("P-B: the walk covers one minute more (dur + 2)", "for k in range(0, dur + 1) %}\n                      {% set sk", "for k in range(0, dur + 2) %}\n                      {% set sk", True),
    ("comment of the declared header block (a letter of REFUSES changed)", "REFUSES a start time that is a skipped local time", "REFUSEs a start time that is a skipped local time", True),
    ("comment of the declared P-A block (proposal P-A becomes P-D)", "proposal P-A): a start time", "proposal P-D): a start time", True),
    ("comment of the declared P-B block (proposal P-B becomes P-C)", "proposal P-B): the run window is walked", "proposal P-C): the run window is walked", True),
    ("control outside R9's region: the 'must be in the future' refusal text changed by one letter", "REJECTED - scheduled start must be in the future", "REJECTED - scheduled start must be in the futurf", False),
    ("control outside R9's region: the safe Stop SOC range's upper bound changed by one digit", "scheduled_stop_soc }}% outside safe range 10-90%", "scheduled_stop_soc }}% outside safe range 10-91%", False),
]
caught_cm = built_cm = 0
for label, anchor, repl, inside in CLOCK_MUTANTS:
    if DUMP_TEXT.count(anchor) != 1 or len(anchor) != len(repl) or sum(1 for x, y in zip(anchor, repl) if x != y) != 1:
        check(f"mutant is exactly one character, anchored once: {label}", False, f"anchor found {DUMP_TEXT.count(anchor)}x")
        continue
    built_cm += 1
    mutated = DUMP_TEXT.replace(anchor, repl)
    found = rebuild_problem(mutated)
    if found and (("AssertionError" in found) if inside else ("hash differs" in found)):
        caught_cm += 1
        print(f"  PASS  mutant caught: {label} ({found[:170]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label} ({found or 'the rebuild still reproduces both pins'})")
check(f"{len(CLOCK_MUTANTS)} one-character mutants ({sum(1 for m in CLOCK_MUTANTS if m[3])} inside R9's declared region: the P-A refusal, the P-B walk and their comment blocks; {sum(1 for m in CLOCK_MUTANTS if not m[3])} outside it), each made the rebuild raise AssertionError (inside) or the code-line hash differ (outside)",
      caught_cm == len(CLOCK_MUTANTS) == built_cm and sum(1 for m in CLOCK_MUTANTS if m[3]) == 18 and sum(1 for m in CLOCK_MUTANTS if not m[3]) == 2, f"{caught_cm}/{built_cm}/{len(CLOCK_MUTANTS)}")
# A package without R9's pairs (the package of a840755 plus this change), without one of them, or whose declared text is moved is not the previous package plus R9: the rebuild must refuse it.
no_pairs = undo_clock_changes(DUMP_TEXT)
caught_np = 0
for label, text in ([("the package without any of R9's five pairs (a840755 plus this change)", no_pairs)]
                    + [(f"the package without R9's pair {k} of 5 (only that one undone)", _r9s._revert(DUMP_TEXT, (pair,), "mutant")) for k, pair in enumerate(R9_CLOCK_PAIRS, 1)]):
    found = rebuild_problem(text)
    if "AssertionError" in found:
        caught_np += 1
        print(f"  PASS  mutant caught: {label} ({found[:170]})")
    else:
        FAILURES.append(f"mutant survived: {label}")
        print(f"  FAIL  mutant survived: {label} ({found or 'the rebuild still reproduces both pins'})")
check("a package without R9's pairs, or without any one of them, fails the rebuild with an AssertionError (the pairs are required, not optional)", caught_np == 6 and no_pairs != DUMP_TEXT, str(caught_np))

if FAILURES:
    print(f"\nFAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("\nAll plan enforcement checks passed.")
print("These prove the packages against a model of the dongle; nothing was installed and nothing was written live.")
